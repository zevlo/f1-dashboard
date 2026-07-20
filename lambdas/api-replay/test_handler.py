"""Local tests for the api-replay Lambda.

Run:
    python3 lambdas/api-replay/test_handler.py
"""

import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


def body(resp):
    return json.loads(resp["body"])


def ev(session_id):
    return {
        "resource": "/sessions/{sessionId}/replay",
        "pathParameters": {"sessionId": session_id},
    }


class FakeTable:
    def __init__(self, items, by_sk_prefix=None):
        self._items = items
        self._by_sk_prefix = by_sk_prefix or {}
        self.last_query = None

    def get_item(self, Key=None):
        for i in self._items:
            if all(i.get(k) == v for k, v in (Key or {}).items()):
                return {"Item": i}
        return {}

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None,
              ExclusiveStartKey=None, Limit=None):
        self.last_query = {
            "KeyConditionExpression": KeyConditionExpression,
            "ExpressionAttributeValues": ExpressionAttributeValues,
            "ExclusiveStartKey": ExclusiveStartKey,
            "Limit": Limit,
        }
        sk = (ExpressionAttributeValues or {}).get(":sk") or (ExpressionAttributeValues or {}).get(":sd")
        items = []
        for i in self._items:
            if KeyConditionExpression and ":sk" in (ExpressionAttributeValues or {}):
                if i.get("session_key") == sk:
                    items.append(i)
            elif KeyConditionExpression and ":sd" in (ExpressionAttributeValues or {}):
                if i.get("session_driver") == sk:
                    items.append(i)
        return {"Items": items[: (Limit or len(items))]}


class FakeDynamo:
    def __init__(self, tables):
        self._tables = tables

    def Table(self, name):
        return self._tables[name]


def install(tables):
    lf._DDB = FakeDynamo(tables)


def setup_full():
    lf.SESSIONS_TABLE = "sessions"
    lf.POSITIONS_TABLE = "positions"
    lf.LAPS_TABLE = "laps"
    lf.RACE_CONTROL_TABLE = "race_control"
    os.environ["DRIVERS_TABLE"] = "drivers"
    lf.CAR_DATA_TABLE = "car_data"
    install({
        "sessions": FakeTable([
            {"session_key": "123", "session_name": "Race", "status": "completed"},
        ]),
        "drivers": FakeTable([
            {"session_key": "123", "driver_number": Decimal(1), "full_name": "Max"},
            {"session_key": "123", "driver_number": Decimal(16), "full_name": "Charles"},
        ]),
        "positions": FakeTable([
            {"session_key": "123", "ts_driver": "t1#1", "driver_number": Decimal(1), "position": Decimal(1)},
            {"session_key": "123", "ts_driver": "t1#16", "driver_number": Decimal(16), "position": Decimal(2)},
        ]),
        "laps": FakeTable([
            {"session_driver": "123#1", "lap_number": Decimal(1), "lap_duration": Decimal(90.5)},
            {"session_driver": "123#16", "lap_number": Decimal(1), "lap_duration": Decimal(91.2)},
        ]),
        "race_control": FakeTable([
            {"session_key": "123", "timestamp": "2026-01-01T00:00:00", "flag": "GREEN"},
        ]),
        "car_data": FakeTable([]),
    })


def test_missing_session_param():
    r = lf.lambda_handler({"resource": "/sessions/{sessionId}/replay", "pathParameters": {}}, None)
    assert r["statusCode"] == 400
    print("  missing_session_param OK")


def test_session_not_found():
    setup_full()
    r = lf.lambda_handler(ev("nonexistent"), None)
    assert r["statusCode"] == 404
    print("  session_not_found OK")


def test_full_payload_shape():
    setup_full()
    r = lf.lambda_handler(ev("123"), None)
    assert r["statusCode"] == 200
    p = body(r)
    assert p["session"]["session_key"] == "123"
    assert len(p["drivers"]) == 2
    assert p["drivers"][0]["driver_number"] == 1  # sorted ascending
    assert len(p["positions"]) == 2
    assert len(p["laps"]) == 2
    assert len(p["race_control"]) == 1
    assert p["counts"]["drivers"] == 2
    assert p["counts"]["laps"] == 2
    print("  full_payload_shape OK")


def test_decimal_coercion():
    """Decimals from DDB must be JSON-safe (int or float, not Decimal)."""
    setup_full()
    r = lf.lambda_handler(ev("123"), None)
    p = body(r)
    assert isinstance(p["laps"][0]["lap_duration"], (int, float))
    assert not isinstance(p["laps"][0]["lap_duration"], str)
    print("  decimal_coercion OK")


def test_cors_header():
    r = lf.respond(200, {"ok": True})
    assert r["headers"]["Access-Control-Allow-Origin"] == "*"
    print("  cors_header OK")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll api-replay tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
