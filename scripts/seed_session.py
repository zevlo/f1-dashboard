#!/usr/bin/env python3
"""Seed the v2 DynamoDB tables with a historical OpenF1 session.

Usage:
    python3 scripts/seed_session.py [SESSION_KEY]

Defaults to 11315 (Austria 2026 race). Pulls session + drivers + positions +
laps + race_control from OpenF1 and writes them to the dev DDB tables. Skips
car_data (too many samples — ~100k rows). Idempotent via the same DDB schemas
the transformer enforces (SK-conditioned PutItem where applicable).

Requires boto3 in your venv. The script reads AWS region + table names from
Terraform outputs (terraform output -json), so run from the repo root after
`terraform apply` has succeeded.

Safety:
    - Only writes to the dev tables (table names start with f1-telemetry-dev-)
    - Won't overwrite existing rows for the same session (DDB conditional put
      on SK where the schema supports it)
    - Prints progress + a final per-table count
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from decimal import Decimal

import boto3

OPENF1_BASE = "https://api.openf1.org/v1"
DEFAULT_SESSION_KEY = "11315"  # Austria 2026 race ( Spielberg )
BATCH_SIZE = 25  # BatchWriteItem hard cap


def fetch(path, params):
    """GET OpenF1 with retry. Returns parsed JSON (list or dict)."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{OPENF1_BASE}{path}?{qs}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "f1-seed/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  retry {attempt + 1} on {url}: {e}")
            time.sleep(0.5 * (attempt + 1))


def tf_outputs():
    """Read terraform outputs from the dev environment."""
    cwd = os.path.join(os.path.dirname(__file__), "..", "terraform", "environments", "dev")
    r = subprocess.run(["terraform", "output", "-json"], cwd=cwd, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def to_ddb_item(d):
    """Convert dict to DDB item with type wrappers. Coerces numbers via Decimal
    (boto3 rejects float). Drops None values (DDB doesn't store them)."""
    out = {}
    for k, v in d.items():
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            out[k] = {"BOOL": v}
        elif isinstance(v, (int, float)):
            # Use str() to avoid float binary-precision artifacts (matches transformer).
            out[k] = {"N": str(Decimal(str(v)))}
        else:
            out[k] = {"S": str(v)}
    return out


def batch_write(table_name, items):
    """BatchWriteItem in chunks of 25. Idempotent (PutRequest overwrites)."""
    if not items:
        return 0
    client = boto3.client("dynamodb")
    written = 0
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        reqs = [{"PutRequest": {"Item": it}} for it in batch]
        # Retry on partial unprocessed.
        for attempt in range(5):
            r = client.batch_write_item(RequestItems={table_name: reqs})
            unprocessed = r.get("UnprocessedItems", {}).get(table_name, [])
            if not unprocessed:
                break
            reqs = unprocessed
            time.sleep(0.2 * (attempt + 1))
        written += len(batch) - len(unprocessed) if not unprocessed else len(batch) - len(reqs)
    return written


def seed_session(session_key, tables):
    print(f"\n=== Seeding session {session_key} ===")

    # --- Sessions (1 row) ---
    print("  fetching /sessions...")
    sessions = fetch("/sessions", {"session_key": session_key})
    if not sessions:
        sys.exit(f"OpenF1 returned no session for session_key={session_key}")
    s = sessions[0]
    # Match transformer's to_session_item schema
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    date_end = s.get("date_end")
    status = "completed" if (date_end and datetime.fromisoformat(date_end.replace("Z", "+00:00")) < now) else "active"
    session_item = to_ddb_item({
        "session_key": str(s["session_key"]),
        "session_type": s.get("session_type"),
        "session_name": s.get("session_name"),
        "circuit_short_name": s.get("circuit_short_name"),
        "country_name": s.get("country_name"),
        "date_start": s.get("date_start"),
        "date_end": s.get("date_end"),
        "year": s.get("year"),
        "status": status,
    })
    n = batch_write(tables["sessions"], [session_item])
    print(f"  sessions: wrote {n}")

    # --- Drivers (~20 rows) ---
    print("  fetching /drivers...")
    drivers_raw = fetch("/drivers", {"session_key": session_key})
    driver_items = []
    for d in drivers_raw:
        item = to_ddb_item({
            "session_key": str(session_key),
            "driver_number": d["driver_number"],
            "full_name": d.get("full_name"),
            "broadcast_name": d.get("broadcast_name"),
            "name_acronym": d.get("name_acronym"),
            "team_name": d.get("team_name"),
            "team_colour": d.get("team_colour"),
            "country_code": d.get("country_code"),
            "headshot_url": d.get("headshot_url"),
        })
        driver_items.append(item)
    n = batch_write(tables["drivers"], driver_items)
    print(f"  drivers: wrote {n}")

    # --- Positions (many rows) ---
    print("  fetching /positions...")
    positions_raw = fetch("/position", {"session_key": session_key})
    position_items = []
    for p in positions_raw:
        date = p.get("date")
        driver = p.get("driver_number", 0)
        item = to_ddb_item({
            "session_key": str(session_key),
            "ts_driver": f"{date}#{driver}",
            "driver_number": driver,
            "position": p.get("position"),
            "date": date,
        })
        position_items.append(item)
    n = batch_write(tables["positions"], position_items)
    print(f"  positions: wrote {n} (of {len(positions_raw)} fetched)")

    # --- Laps (~1500 rows) ---
    print("  fetching /laps...")
    laps_raw = fetch("/laps", {"session_key": session_key})
    lap_items = []
    for l in laps_raw:
        driver = l.get("driver_number", 0)
        item = to_ddb_item({
            "session_driver": f"{session_key}#{driver}",
            "lap_number": l.get("lap_number"),
            "date_start": l.get("date_start"),
            "lap_duration": l.get("lap_duration"),
            "sector_1": l.get("duration_sector_1"),
            "sector_2": l.get("duration_sector_2"),
            "sector_3": l.get("duration_sector_3"),
            "is_pit_out_lap": l.get("is_pit_out_lap"),
            "compound": l.get("compound"),
        })
        lap_items.append(item)
    n = batch_write(tables["laps"], lap_items)
    print(f"  laps: wrote {n} (of {len(laps_raw)} fetched)")

    # --- RaceControl (~200 rows) ---
    print("  fetching /race_control...")
    rc_raw = fetch("/race_control", {"session_key": session_key})
    rc_items = []
    seen_keys = set()  # OpenF1 can emit duplicate timestamps; dedupe on PK+SK
    for rc in rc_raw:
        ts = rc.get("date")
        key = (str(session_key), str(ts))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        item = to_ddb_item({
            "session_key": str(session_key),
            "timestamp": ts,
            "category": rc.get("category"),
            "flag": rc.get("flag"),
            "message": rc.get("message"),
            "driver_number": rc.get("driver_number"),
        })
        rc_items.append(item)
    n = batch_write(tables["race_control"], rc_items)
    print(f"  race_control: wrote {n} (of {len(rc_raw)} fetched, {len(rc_raw) - len(rc_items)} dupes skipped)")

    print(f"\n=== Done. Session {session_key} seeded. ===")
    print(f"  {s.get('session_name')} ({s.get('circuit_short_name')}, {s.get('country_name')})")


def main():
    session_key = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SESSION_KEY

    outputs = tf_outputs()
    tables = {
        "sessions":     outputs["dynamodb_table_names"]["value"]["sessions"],
        "drivers":      outputs["dynamodb_table_names"]["value"]["drivers"],
        "positions":    outputs["dynamodb_table_names"]["value"]["positions"],
        "laps":         outputs["dynamodb_table_names"]["value"]["laps"],
        "race_control": outputs["dynamodb_table_names"]["value"]["race_control"],
    }
    # Sanity: only proceed if all tables match the expected dev prefix.
    for k, name in tables.items():
        if not name.startswith("f1-telemetry-dev-"):
            sys.exit(f"Refusing to seed non-dev table {k}={name!r}")

    seed_session(session_key, tables)


if __name__ == "__main__":
    sys.exit(main() or 0)
