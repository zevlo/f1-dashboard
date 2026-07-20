"""Local tests for the ws-connect Lambda (DynamoDB stubbed, no AWS creds).

Run:
    python3 lambdas/ws-connect/test_handler.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


class FakeTable:
    def __init__(self):
        self.put = None

    def put_item(self, **kwargs):
        self.put = kwargs["Item"]


class FakeDynamo:
    def __init__(self, table):
        self._table = table

    def Table(self, name):
        self.last_name = name
        return self._table


def ev(connection_id=None, qs=None):
    return {
        "requestContext": {"connectionId": connection_id},
        "queryStringParameters": qs,
    }


def install():
    table = FakeTable()
    lf._DYNAMODB = FakeDynamo(table)
    return table


def test_missing_session_id_rejected():
    table = install()
    r = lf.lambda_handler(ev(connection_id="c1", qs={}), None)
    assert r["statusCode"] == 401
    assert table.put is None
    print("  missing_session_id_rejected OK")


def test_missing_connection_id():
    install()
    r = lf.lambda_handler(ev(connection_id=None, qs={"sessionId": "11315"}), None)
    assert r["statusCode"] == 500
    print("  missing_connection_id OK")


def test_successful_connect_persists_item():
    lf.CONNECTIONS_TABLE = "connections-table"
    table = install()
    r = lf.lambda_handler(ev(connection_id="c1", qs={"sessionId": "11315"}), None)
    assert r["statusCode"] == 200
    item = table.put
    assert item["connection_id"] == "c1"
    assert item["session_key"] == "11315"
    assert "ttl" in item and item["ttl"] > 0
    assert "connected_at" in item
    print("  successful_connect_persists_item OK")


def test_ttl_is_future():
    import time
    install()
    lf.lambda_handler(ev(connection_id="c1", qs={"sessionId": "11315"}), None)
    # Indirectly: run again with a known floor.
    before = int(time.time()) + 7000  # > 2h-ish check: ttl must exceed now+7000 is false;
    # Just assert ttl is at least now + 1h.
    floor = int(time.time()) + 3600
    table = install()
    lf.lambda_handler(ev(connection_id="c1", qs={"sessionId": "11315"}), None)
    assert table.put["ttl"] >= floor
    print("  ttl_is_future OK")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll ws-connect tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
