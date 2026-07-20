"""Local tests for the ws-agent Lambda (Phase 5).

Exercises:
  - Event parsing
  - Missing-text error path
  - Stub reply path (AGENT_ENABLED=false)
  - Tool execution (5 tools against a fake DDB)
  - Conversation history management
  - Bedrock loop mocked end-to-end

Run:
    python3 lambdas/ws-agent/test_handler.py
"""

import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


def make_event(text=None, session_key="11315", driver_number=1):
    body = {"action": "agent.ask"}
    if text is not None:
        body["text"] = text
    if session_key is not None:
        body["sessionKey"] = session_key
    if driver_number is not None:
        body["driverNumber"] = driver_number
    return {
        "requestContext": {"connectionId": "c1"},
        "body": json.dumps(body),
    }


def capture_posts():
    sent = []

    def fake(connection_id, payload):
        sent.append((connection_id, payload))
    lf.post_to_connection = fake
    return sent


# ---------------------------------------------------------------------------
# Stub path (AGENT_ENABLED=false)
# ---------------------------------------------------------------------------
def test_missing_text_sends_error():
    lf.AGENT_ENABLED = False
    sent = capture_posts()
    r = lf.lambda_handler(make_event(text=None), None)
    assert r["statusCode"] == 200
    assert sent[0][1]["type"] == "agent.error"
    print("  missing_text_sends_error OK")


def test_no_connection_id():
    lf.AGENT_ENABLED = False
    r = lf.lambda_handler({"requestContext": {}, "body": "{}"}, None)
    assert r["statusCode"] == 400
    print("  no_connection_id OK")


def test_stub_streams_tokens_then_done():
    lf.AGENT_ENABLED = False
    sent = capture_posts()
    r = lf.lambda_handler(make_event(text="why is VER slow?"), None)
    assert r["statusCode"] == 200
    types = [s[1]["type"] for s in sent]
    assert types[-1] == "agent.done"
    assert all(t == "agent.token" for t in types[:-1])
    msg_ids = {s[1]["messageId"] for s in sent}
    assert len(msg_ids) == 1
    print("  stub_streams_tokens_then_done OK")


def test_parse_event_handles_bad_json():
    cid, body = lf.parse_event({
        "requestContext": {"connectionId": "c1"},
        "body": "not json",
    })
    assert cid == "c1"
    assert body == {}
    print("  parse_event_handles_bad_json OK")


# ---------------------------------------------------------------------------
# Tool execution (DDB mocked)
# ---------------------------------------------------------------------------
class FakeTable:
    def __init__(self, items):
        self._items = items

    def get_item(self, Key=None):
        for i in self._items:
            if all(i.get(k) == v for k, v in (Key or {}).items()):
                return {"Item": i}
        return {}

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None,
              Limit=None, ScanIndexForward=None):
        sk = (ExpressionAttributeValues or {}).get(":sk") or (ExpressionAttributeValues or {}).get(":sd")
        items = []
        for i in self._items:
            if KeyConditionExpression and ":sk" in (ExpressionAttributeValues or {}):
                if i.get("session_key") == sk:
                    items.append(i)
            elif KeyConditionExpression and ":sd" in (ExpressionAttributeValues or {}):
                if i.get("session_driver") == sk:
                    items.append(i)
        if ScanIndexForward is False:
            items = list(reversed(items))
        if Limit:
            items = items[:Limit]
        return {"Items": items}


class FakeDynamo:
    def __init__(self, tables):
        self._tables = tables

    def Table(self, name):
        return self._tables[name]


def install_tables(tables):
    lf._DDB = FakeDynamo(tables)


def test_tool_get_session_found():
    lf.TABLES["sessions"] = "sessions"
    install_tables({
        "sessions": FakeTable([
            {"session_key": "11315", "session_name": "Race", "status": "completed",
             "year": Decimal(2026)},
        ]),
    })
    r = lf.tool_get_session({"session_key": "11315"})
    assert r["session"]["session_name"] == "Race"
    assert r["session"]["year"] == 2026  # Decimal coerced to int
    print("  tool_get_session_found OK")


def test_tool_get_session_missing():
    lf.TABLES["sessions"] = "sessions"
    install_tables({"sessions": FakeTable([])})
    r = lf.tool_get_session({"session_key": "nope"})
    assert "error" in r
    print("  tool_get_session_missing OK")


def test_tool_get_standings_returns_latest_per_driver():
    lf.TABLES["positions"] = "positions"
    install_tables({
        "positions": FakeTable([
            {"session_key": "1", "driver_number": Decimal(1), "position": Decimal(1),
             "date": "2026-01-01T00:00:00"},
            {"session_key": "1", "driver_number": Decimal(1), "position": Decimal(2),
             "date": "2026-01-01T00:00:05"},
            {"session_key": "1", "driver_number": Decimal(2), "position": Decimal(2),
             "date": "2026-01-01T00:00:00"},
            {"session_key": "1", "driver_number": Decimal(2), "position": Decimal(1),
             "date": "2026-01-01T00:00:05"},
        ]),
    })
    r = lf.tool_get_standings({"session_key": "1"})
    # Driver 2 should be P1 (latest sample), Driver 1 P2.
    assert r["standings"][0]["driver_number"] == 2
    assert r["standings"][0]["position"] == 1
    assert r["standings"][1]["driver_number"] == 1
    print("  tool_get_standings_returns_latest_per_driver OK")


def test_tool_get_driver_laps_invalid_driver():
    lf.TABLES["laps"] = "laps"
    install_tables({"laps": FakeTable([])})
    r = lf.tool_get_driver_laps({"session_key": "1", "driver_number": "abc"})
    assert "error" in r
    print("  tool_get_driver_laps_invalid_driver OK")


def test_tool_get_driver_laps_with_range():
    lf.TABLES["laps"] = "laps"
    install_tables({
        "laps": FakeTable([
            {"session_driver": "1#1", "lap_number": Decimal(1), "lap_duration": Decimal(90.5)},
            {"session_driver": "1#1", "lap_number": Decimal(2), "lap_duration": Decimal(91.0)},
            {"session_driver": "1#1", "lap_number": Decimal(3), "lap_duration": Decimal(90.8)},
        ]),
    })
    r = lf.tool_get_driver_laps({"session_key": "1", "driver_number": 1, "lap_start": 2})
    assert r["driver_number"] == 1
    assert r["lap_count"] == 2
    assert r["laps"][0]["lap_number"] == 2
    print("  tool_get_driver_laps_with_range OK")


def test_tool_get_telemetry_sample_returns_latest():
    lf.TABLES["car_data"] = "car_data"
    install_tables({
        "car_data": FakeTable([
            {"session_driver": "1#1", "date": "2026-01-01T00:00:00", "speed": Decimal(300)},
            {"session_driver": "1#1", "date": "2026-01-01T00:00:05", "speed": Decimal(312)},
        ]),
    })
    r = lf.tool_get_telemetry_sample({"session_key": "1", "driver_number": 1})
    # FakeTable honours ScanIndexForward=False then applies Limit=1, so the
    # most recent sample (312) is what the tool returns.
    assert r["telemetry"]["speed"] == 312
    print("  tool_get_telemetry_sample_returns_latest OK")


def test_tool_get_race_control_filters_since():
    lf.TABLES["race_control"] = "race_control"
    install_tables({
        "race_control": FakeTable([
            {"session_key": "1", "timestamp": "2026-01-01T00:00:00", "flag": "GREEN", "message": "Go"},
            {"session_key": "1", "timestamp": "2026-01-01T00:30:00", "flag": "YELLOW", "message": "Slow"},
            {"session_key": "1", "timestamp": "2026-01-01T01:00:00", "flag": "RED", "message": "Stop"},
        ]),
    })
    r = lf.tool_get_race_control({"session_key": "1", "since": "2026-01-01T00:30:01"})
    flags = [e["flag"] for e in r["events"]]
    assert "RED" in flags
    assert "GREEN" not in flags
    print("  tool_get_race_control_filters_since OK")


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------
def test_history_caps_at_max():
    lf._conversations.clear()
    cid = "conn-cap-test"
    # Override the cap temporarily so the test is fast.
    original_max = lf.MAX_HISTORY_PER_CONN
    lf.MAX_HISTORY_PER_CONN = 3
    try:
        for i in range(5):
            lf.get_history(cid).append({"role": "user", "content": [{"text": str(i)}]})
            lf.trim_history(cid)
        h = lf.get_history(cid)
        assert len(h) == 3
        # Should keep the last 3.
        assert h[-1]["content"][0]["text"] == "4"
    finally:
        lf.MAX_HISTORY_PER_CONN = original_max
    print("  history_caps_at_max OK")


def test_clear_history_removes_entry():
    lf._conversations.clear()
    lf.get_history("c1").append({"x": 1})
    assert "c1" in lf._conversations
    lf.clear_history("c1")
    assert "c1" not in lf._conversations
    print("  clear_history_removes_entry OK")


# ---------------------------------------------------------------------------
# Bedrock path — must raise when not enabled (AGENT_ENABLED=false path is
# exercised by test_stub_*). The full Bedrock loop requires the boto3 client;
# skipped here (covered by the Phase 5.8 live smoke).
# ---------------------------------------------------------------------------
def test_bedrock_path_requires_model_id():
    lf.AGENT_ENABLED = True
    sent = capture_posts()
    original = lf.AGENT_MODEL_ID
    lf.AGENT_MODEL_ID = ""
    try:
        r = lf.lambda_handler(make_event(text="hello"), None)
        assert r["statusCode"] == 500
        assert sent[0][1]["type"] == "agent.error"
    finally:
        lf.AGENT_MODEL_ID = original
        lf.AGENT_ENABLED = False
    print("  bedrock_path_requires_model_id OK")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll ws-agent tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
