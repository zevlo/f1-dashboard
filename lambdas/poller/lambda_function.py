"""OpenF1 poller Lambda (v2 — live-only).

Triggered by EventBridge every 60s. Internally loops N times (default 12)
to achieve ~5s polling cadence despite EventBridge's 60s floor. Pushes
enveloped telemetry records to Kinesis.

v2 changes vs v1:
  - Replays are client-side now (frontend bulk-fetches via /sessions/{key}/replay
    and walks the data with a local clock). The poller is live-only.
  - On session discovery, the poller bulk-upserts all 20 drivers into the
    Drivers DynamoDB table. The frontend reads them via one
    GET /sessions/{key}/drivers call so names render immediately.

Sources fetched per cycle (live mode):
  - /position, /car_data, /race_control — filtered by a sliding time window
    (since last cycle). Race-control events share the OpenF1 `date` quirk
    documented below, so they reuse the same filter.
  - /laps — fetched once for the whole session each cycle. Laps have no clean
    time-window filter; the transformer dedupes via conditional put on
    (session_driver, lap_number).
  - /drivers — fetched once at the top of each invocation and bulk-upserted
    to the Drivers table. OpenF1 returns 20-ish rows; cheap.
  - /sessions — one session envelope emitted at the top of each invocation
    so the Sessions table stays populated (and status transitions from
    active -> completed as wall-clock crosses date_end).

Modes:
  - live: auto-discovers the currently-active session via ?session_key=latest.
          No-op when no session is active (off-season / between sessions).
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Configuration (env vars wired by Terraform)
# --------------------------------------------------------------------------
OPENF1_BASE_URL = os.environ.get("OPENF1_BASE_URL", "https://api.openf1.org/v1")
STREAM_NAME = os.environ.get("STREAM_NAME", "")
DLQ_URL = os.environ.get("DLQ_URL") or None
DRIVERS_TABLE = os.environ.get("DRIVERS_TABLE") or None
LOOP_COUNT = int(os.environ.get("LOOP_COUNT", "12"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

POLL_INTERVAL_SECONDS = 5
LIVE_OVERLAP_SECONDS = 1
HTTP_TIMEOUT_SECONDS = 4
HTTP_MAX_RETRIES = 2
HTTP_BACKOFF_BASE_SECONDS = 0.5
KINESIS_BATCH_LIMIT = 500
DDB_BATCH_WRITE_LIMIT = 25  # BatchWriteItem hard cap
TIMEOUT_BUFFER_MS = 5000

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# --------------------------------------------------------------------------
# Boto3 clients — lazy so the module imports without AWS creds (local tests)
# --------------------------------------------------------------------------
_KINESIS = None
_DDB = None


def kinesis():
    global _KINESIS
    if _KINESIS is None:
        import boto3
        _KINESIS = boto3.client("kinesis")
    return _KINESIS


def ddb():
    global _DDB
    if _DDB is None:
        import boto3
        _DDB = boto3.client("dynamodb")
    return _DDB


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
DATE_OPERATORS = (">=", "<=", ">", "<")


def build_openf1_url(path, params):
    """Build an OpenF1 URL.

    OpenF1 quirks (verified 2026-06):
      - Date operators (date>=, date<, date<=, date>) must be sent as a single
        URL token like 'date%3E%3Dvalue' — NOT 'date%3E%3D=value'. The latter
        returns 404. So we build the query string by hand for these and let
        urllib.parse.urlencode handle the rest.
      - The 'limit' parameter returns 404 when combined with 'date>=' filters,
        even when records exist. Callers must not pass 'limit' alongside date
        filters.
    """
    parts = []
    for k, v in params.items():
        k_str = str(k)
        if any(k_str.startswith(f"date{op}") for op in DATE_OPERATORS):
            parts.append(f"{k_str}{urllib.parse.quote(str(v), safe=':')}")
        else:
            encoded = urllib.parse.urlencode({k_str: v})
            parts.append(encoded)
    return f"{OPENF1_BASE_URL}{path}?{'&'.join(parts)}"


def fetch_json(path, params):
    """GET an OpenF1 endpoint with bounded retry on 429/5xx/timeout.

    OpenF1 returns {"detail": "No results found."} (a dict) for empty queries;
    we normalise that to an empty list so callers can always iterate.
    """
    url = build_openf1_url(path, params)
    last_exc = None
    for attempt in range(HTTP_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "f1-telemetry-poller/2.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    logger.debug("fetch_json empty/odd response from %s: %s", path, data)
                    return []
                return data
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code == 404:
                try:
                    body = e.read().decode("utf-8")
                    if "No results" in body:
                        return []
                except Exception:
                    pass
            transient = e.code == 429 or 500 <= e.code < 600
            if transient and attempt < HTTP_MAX_RETRIES:
                time.sleep(HTTP_BACKOFF_BASE_SECONDS * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_exc = e
            if attempt < HTTP_MAX_RETRIES:
                time.sleep(HTTP_BACKOFF_BASE_SECONDS * (attempt + 1))
                continue
            raise
    raise last_exc  # pragma: no cover


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def parse_iso(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


# --------------------------------------------------------------------------
# Session resolution
# --------------------------------------------------------------------------
def resolve_target_session():
    """Decide what to do this invocation. Returns one of:
      {"mode": "live",  "session": {...}}  active session, poll it
      {"mode": "idle",  "session": {...|None}}  nothing to do
    """
    sessions = fetch_json("/sessions", {"session_key": "latest"})
    if not sessions:
        return {"mode": "idle", "session": None}

    session = sessions[0]
    if session.get("is_cancelled"):
        return {"mode": "idle", "session": session}

    now = datetime.now(timezone.utc)
    start = parse_iso(session["date_start"])
    end = parse_iso(session["date_end"])
    if start <= now <= end:
        return {"mode": "live", "session": session}
    return {"mode": "idle", "session": session}


# --------------------------------------------------------------------------
# Drivers upsert (v2)
# --------------------------------------------------------------------------
def upsert_drivers(session_key):
    """Bulk-fetch /drivers?session_key=X from OpenF1 and BatchWriteItem into
    the Drivers table. Idempotent — re-running overwrites with the same data.

    OpenF1 /drivers schema (per session) gives us: driver_number, full_name,
    name_acronym, team_name, team_colour, country_code, headshot_url, etc.
    We persist the union needed by the frontend tower + chart + telemetry panel.
    """
    if not DRIVERS_TABLE:
        logger.warning("DRIVERS_TABLE not set; skipping driver upsert")
        return 0

    drivers = fetch_json("/drivers", {"session_key": session_key})
    if not drivers:
        logger.info("DRIVERS: OpenF1 returned no drivers for session_key=%s", session_key)
        return 0

    items = []
    for d in drivers:
        # driver_number is the sort key (N). All other attrs are stored as-is.
        # We use PutRequest (idempotent overwrite) — drivers don't change
        # mid-session, but if OpenF1 corrects metadata we want to pick it up.
        attrs = {
            "session_key": {"S": str(session_key)},
            "driver_number": {"N": str(d["driver_number"])},
        }
        for field, attr in (
            ("full_name", "full_name"),
            ("broadcast_name", "broadcast_name"),
            ("name_acronym", "name_acronym"),
            ("team_name", "team_name"),
            ("team_colour", "team_colour"),
            ("country_code", "country_code"),
            ("headshot_url", "headshot_url"),
            ("driver_number_str", "driver_number"),  # convenience for UI keys
        ):
            val = d.get(field if attr != "driver_number" else "driver_number")
            if val is not None and val != "":
                if attr == "driver_number":
                    attrs["driver_number_str"] = {"S": str(val)}
                else:
                    attrs[attr] = {"S": str(val)}

        items.append({"PutRequest": {"Item": attrs}})

    # BatchWriteItem caps at 25 request items per call.
    written = 0
    for i in range(0, len(items), DDB_BATCH_WRITE_LIMIT):
        batch = items[i:i + DDB_BATCH_WRITE_LIMIT]
        r = ddb().batch_write_item(RequestItems={DRIVERS_TABLE: batch})
        # Unprocessed items are retried once; if still stuck, we log and move on
        # — next invocation's bulk upsert will re-attempt idempotently.
        unprocessed = r.get("UnprocessedItems", {}).get(DRIVERS_TABLE, [])
        if unprocessed:
            logger.warning(
                "DRIVERS: %d/%d unprocessed after BatchWriteItem (will retry next invocation)",
                len(unprocessed), len(batch),
            )
        written += len(batch) - len(unprocessed)

    logger.info("DRIVERS: upserted %d/%d for session_key=%s", written, len(drivers), session_key)
    return written


# --------------------------------------------------------------------------
# Telemetry fetch + envelope
# --------------------------------------------------------------------------
def envelope(source, session_key, payload):
    """Wrap an OpenF1 record into a Kinesis record (Data + PartitionKey)."""
    driver = payload.get("driver_number", 0)
    ts = payload.get("date") or payload.get("date_start") or fmt_iso(datetime.now(timezone.utc))
    return {
        "Data": json.dumps({
            "source": source,
            "session_key": session_key,
            "driver_number": driver,
            "ts": ts,
            "payload": payload,
        }).encode("utf-8"),
        "PartitionKey": f"{session_key}#{driver}",
    }


def fetch_telemetry(session_key, since_iso, until_iso=None, include_laps=True):
    """Fetch /position, /car_data, /race_control for a time window (+ all
    /laps for the session when include_laps). Returns enveloped Kinesis records.
    """
    pos_params = {"session_key": session_key, "date>=": since_iso}
    car_params = {"session_key": session_key, "date>=": since_iso}
    rc_params = {"session_key": session_key, "date>=": since_iso}
    if until_iso:
        pos_params["date<"] = until_iso
        car_params["date<"] = until_iso
        rc_params["date<"] = until_iso

    records = []
    for r in fetch_json("/position", pos_params):
        records.append(envelope("position", session_key, r))
    for r in fetch_json("/car_data", car_params):
        records.append(envelope("car_data", session_key, r))
    for r in fetch_json("/race_control", rc_params):
        records.append(envelope("race_control", session_key, r))
    if include_laps:
        for r in fetch_json("/laps", {"session_key": session_key}):
            records.append(envelope("lap", session_key, r))
    return records


def put_records(records):
    """Batch-push to Kinesis (500 per call). Returns count successfully written."""
    if not records:
        return 0
    written = 0
    for i in range(0, len(records), KINESIS_BATCH_LIMIT):
        batch = records[i:i + KINESIS_BATCH_LIMIT]
        r = kinesis().put_records(StreamName=STREAM_NAME, Records=batch)
        failed = r.get("FailedRecordCount", 0)
        written += len(batch) - failed
        if failed:
            logger.warning(
                "put_records partial failure: %d/%d failed (will be re-fetched next cycle; transformer dedupes)",
                failed, len(batch),
            )
    return written


# --------------------------------------------------------------------------
# Live mode
# --------------------------------------------------------------------------
def run_live(session, should_stop):
    """Live mode: poll the active session at ~5s cadence."""
    session_key = session["session_key"]
    logger.info("LIVE: polling session_key=%s (%s)", session_key, session.get("session_name"))

    # Upsert drivers once per invocation so the frontend's bulk fetch always
    # has fresh metadata. Drivers don't change mid-session, but the first
    # invocation after session discovery populates the table.
    try:
        upsert_drivers(session_key)
    except Exception:
        logger.exception("DRIVERS: upsert failed (continuing — telemetry is unaffected)")

    last_seen = datetime.now(timezone.utc) - timedelta(seconds=POLL_INTERVAL_SECONDS)
    pushed_total = 0
    cycles = 0
    for i in range(LOOP_COUNT):
        if should_stop():
            logger.info("LIVE: stopping early at cycle %d/%d (Lambda timeout approaching)", i, LOOP_COUNT)
            break
        records = fetch_telemetry(
            session_key,
            since_iso=fmt_iso(last_seen),
            include_laps=(i == 0),
        )
        if records:
            pushed_total += put_records(records)
        last_seen = datetime.now(timezone.utc) - timedelta(seconds=LIVE_OVERLAP_SECONDS)
        cycles += 1
        if i < LOOP_COUNT - 1 and not should_stop():
            time.sleep(POLL_INTERVAL_SECONDS)

    logger.info("LIVE: pushed %d records across %d cycles", pushed_total, cycles)
    return pushed_total


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def lambda_handler(event, context):
    """EventBridge entrypoint. Resolves mode, runs the loop, returns a summary."""
    start = time.monotonic()

    def should_stop():
        return context.get_remaining_time_in_millis() < TIMEOUT_BUFFER_MS

    try:
        target = resolve_target_session()
    except Exception:
        logger.exception("Failed to resolve target session from OpenF1")
        raise

    mode = target["mode"]
    session = target["session"]

    if mode == "idle":
        if session:
            logger.info(
                "IDLE: latest session %s (%s) not currently active; skipping",
                session.get("session_key"), session.get("session_name"),
            )
        else:
            logger.info("IDLE: OpenF1 returned no sessions")
        return {"statusCode": 200, "mode": "idle", "pushed": 0}

    # Emit one session metadata envelope per invocation so the Sessions table
    # stays populated (status: active -> completed). Transformer upserts on PK.
    put_records([envelope("session", session["session_key"], session)])

    try:
        if mode == "live":
            pushed = run_live(session, should_stop)
        else:
            raise RuntimeError(f"Unknown mode: {mode!r}")
    except Exception:
        logger.exception("Poller failed mid-execution (mode=%s)", mode)
        raise

    elapsed = time.monotonic() - start
    logger.info("DONE: mode=%s pushed=%d elapsed=%.1fs", mode, pushed, elapsed)
    return {
        "statusCode": 200,
        "mode": mode,
        "pushed": pushed,
        "elapsed_s": round(elapsed, 1),
    }
