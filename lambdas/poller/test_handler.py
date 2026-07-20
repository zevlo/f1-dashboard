"""Local test harness for the poller.

Exercises OpenF1 fetch + envelope logic against the real API without needing
AWS credentials (Kinesis/DynamoDB are only touched by run_live, which this
script does not call).

Run from anywhere:
    python3 lambdas/poller/test_handler.py
"""

import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


def banner(s):
    print(f"\n=== {s} ===")


def main():
    banner("config")
    print(f"  OPENF1_BASE_URL = {lf.OPENF1_BASE_URL}")
    print(f"  STREAM_NAME     = {lf.STREAM_NAME or '(unset)'}")
    print(f"  DRIVERS_TABLE   = {lf.DRIVERS_TABLE or '(unset)'}")
    print(f"  LOOP_COUNT      = {lf.LOOP_COUNT}")

    banner("resolve_target_session()")
    target = lf.resolve_target_session()
    print(f"  mode = {target['mode']}")
    s = target.get("session") or {}
    if s:
        print(f"  session_key  = {s.get('session_key')}")
        print(f"  session_name = {s.get('session_name')}")
        print(f"  session_type = {s.get('session_type')}")
        print(f"  circuit      = {s.get('circuit_short_name')}, {s.get('country_name')}")
        print(f"  date_start   = {s.get('date_start')}")
        print(f"  date_end     = {s.get('date_end')}")
        print(f"  is_cancelled = {s.get('is_cancelled')}")
    else:
        print("  (no session returned)")

    if not s:
        print("\nNothing to fetch against. Exiting.")
        return 0

    banner("fetch_telemetry() — first 60s window from session start")
    since = lf.parse_iso(s["date_start"])
    until = lf.parse_iso(s["date_start"]) + timedelta(seconds=60)
    records = lf.fetch_telemetry(
        s["session_key"],
        since_iso=lf.fmt_iso(since),
        until_iso=lf.fmt_iso(until),
    )
    print(f"  fetched {len(records)} enveloped records")
    if records:
        sample = json.loads(records[0]["Data"].decode("utf-8"))
        print("  sample envelope:")
        print(json.dumps(sample, indent=2)[:800])
        print(f"  sample PartitionKey = {records[0]['PartitionKey']}")

    banner("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
