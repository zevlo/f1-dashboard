"""Local test harness for the transformer.

Exercises the envelope -> item builder logic without AWS credentials.
The DynamoDB write path (put_item) is only touched if DDB_ENDPOINT is set
(e.g., pointing at localstack); otherwise put_idempotent is mocked.

Run:
    python3 lambdas/transformer/test_handler.py
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


def banner(s):
    print(f"\n=== {s} ===")


def make_env(source, session_key, payload, driver_number=None, ts=None):
    return {
        "source": source,
        "session_key": session_key,
        "driver_number": driver_number if driver_number is not None else payload.get("driver_number", 0),
        "ts": ts or payload.get("date") or payload.get("date_start") or "2026-06-12T14:00:00.000",
        "payload": payload,
    }


SAMPLES = {
    "session": make_env(
        "session", 11307,
        {
            "session_key": 11307, "session_name": "Race", "session_type": "race",
            "circuit_short_name": "Montmeló", "country_name": "Spain",
            "date_start": "2026-06-12T14:00:00+00:00", "date_end": "2026-06-12T15:00:00+00:00",
            "year": 2026,
        },
        driver_number=0,
    ),
    "position": make_env(
        "position", 11307,
        {"date": "2026-06-12T14:01:23.456", "driver_number": 1, "position": 3},
    ),
    "car_data": make_env(
        "car_data", 11307,
        {"date": "2026-06-12T14:01:23.500", "driver_number": 1, "speed": 312,
         "throttle": 99, "brake": 0, "n_gear": 8, "rpm": 11800, "drs": 8},
    ),
    "lap": make_env(
        "lap", 11307,
        {"driver_number": 1, "lap_number": 12, "date_start": "2026-06-12T14:02:00+00:00",
         "lap_duration": 78.421, "duration_sector_1": 26.1, "duration_sector_2": 26.2,
         "duration_sector_3": 26.121, "is_pit_out_lap": False, "compound": "SOFT"},
    ),
    "race_control": make_env(
        "race_control", 11307,
        {"date": "2026-06-12T14:03:00+00:00", "category": "Flag", "flag": "YELLOW",
         "message": "YELLOW FLAG IN SECTOR 2", "driver_number": None},
    ),
}


def main():
    banner("config")
    for k, v in lf.TABLE_NAMES.items():
        print(f"  {k:14s} = {v or '(unset)'}")

    banner("item builders")
    for source, env in SAMPLES.items():
        builder = lf.ROUTING[source]
        table_key, item, sk_attr = builder(env)
        print(f"\n  [{source}] -> table={table_key}, sk={sk_attr}")
        print("  " + json.dumps(item, indent=2, default=str).replace("\n", "\n  "))

    banner("idempotent put (mocked)")
    written_calls = []
    def fake_put(table_key, item, sk_attr):
        written_calls.append((table_key, sk_attr))
        return 1
    with patch.object(lf, "put_item", side_effect=fake_put):
        for env in SAMPLES.values():
            lf.process_record(env)
    print(f"  routed {len(written_calls)} records:")
    for table_key, sk_attr in written_calls:
        print(f"    -> {table_key} (sk check: {sk_attr or 'upsert'})")

    banner("decode from kinesis-shaped record")
    env = SAMPLES["position"]
    raw = {
        "kinesis": {
            "data": __import__("base64").b64encode(json.dumps(env).encode()).decode(),
            "sequenceNumber": "495903382714902566",
        }
    }
    decoded = lf.decode_record(raw)
    assert decoded["source"] == "position"
    assert decoded["session_key"] == 11307
    print(f"  decoded source={decoded['source']} session_key={decoded['session_key']} OK")

    banner("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
