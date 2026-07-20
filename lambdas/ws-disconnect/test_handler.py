"""Local tests for the ws-disconnect Lambda (DynamoDB stubbed, no AWS creds).

Run:
    python3 lambdas/ws-disconnect/test_handler.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


class FakeTable:
    def __init__(self):
        self.deleted_key = None

    def delete_item(self, **kwargs):
        self.deleted_key = kwargs["Key"]


class FakeDynamo:
    def __init__(self, table):
        self._table = table

    def Table(self, name):
        return self._table


def ev(connection_id=None):
    return {"requestContext": {"connectionId": connection_id}}


def install():
    table = FakeTable()
    lf._DYNAMODB = FakeDynamo(table)
    return table


def test_disconnect_deletes():
    table = install()
    r = lf.lambda_handler(ev(connection_id="c1"), None)
    assert r["statusCode"] == 200
    assert table.deleted_key == {"connection_id": "c1"}
    print("  disconnect_deletes OK")


def test_missing_connection_id():
    install()
    r = lf.lambda_handler(ev(connection_id=None), None)
    assert r["statusCode"] == 500
    print("  missing_connection_id OK")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll ws-disconnect tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
