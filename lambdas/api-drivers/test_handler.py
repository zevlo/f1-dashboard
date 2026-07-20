"""Local tests for the api-drivers Lambda (v2).

Exercises both routes (bulk DDB + per-driver OpenF1 proxy) without network or
AWS credentials by stubbing the fetches.

Run:
    python3 lambdas/api-drivers/test_handler.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


def body(resp):
    return json.loads(resp["body"])


def bulk_ev(session_id):
    return {
        "resource": "/sessions/{sessionId}/drivers",
        "pathParameters": {"sessionId": session_id},
    }


def single_ev(driver_number):
    return {
        "resource": "/drivers/{driverNumber}",
        "pathParameters": {"driverNumber": driver_number},
    }


def stub_fetch(result):
    def fake(path, params):
        if callable(result):
            raise result()
        return result
    lf.fetch_json = fake


def stub_ddb_query(items):
    """Pre-seed the lazy client so ddb() returns a fake without importing boto3."""
    class FakeDDB:
        def query(self, **kwargs):
            return {"Items": items}
    lf._DDB = FakeDDB()


# ---------------------------------------------------------------------------
# Bulk endpoint tests
# ---------------------------------------------------------------------------
def test_bulk_returns_sorted_drivers():
    lf.DRIVERS_TABLE = "test-drivers"
    stub_ddb_query([
        {"session_key": {"S": "123"}, "driver_number": {"N": "16"},
         "full_name": {"S": "Charles Leclerc"}, "team_colour": {"S": "E8002D"}},
        {"session_key": {"S": "123"}, "driver_number": {"N": "1"},
         "full_name": {"S": "Max Verstappen"}, "team_colour": {"S": "3671C6"}},
    ])
    r = lf.lambda_handler(bulk_ev("123"), None)
    assert r["statusCode"] == 200
    rows = body(r)
    assert len(rows) == 2
    assert rows[0]["driver_number"] == 1  # sorted ascending
    assert rows[0]["full_name"] == "Max Verstappen"
    assert rows[1]["driver_number"] == 16
    print("  bulk_returns_sorted_drivers OK")


def test_bulk_missing_session():
    r = lf.lambda_handler({"resource": "/sessions/{sessionId}/drivers", "pathParameters": {}}, None)
    assert r["statusCode"] == 400
    print("  bulk_missing_session OK")


def test_bulk_table_unset():
    lf.DRIVERS_TABLE = None
    r = lf.lambda_handler(bulk_ev("123"), None)
    assert r["statusCode"] == 500
    print("  bulk_table_unset OK")


def test_bulk_empty_returns_200_array():
    lf.DRIVERS_TABLE = "test-drivers"
    stub_ddb_query([])
    r = lf.lambda_handler(bulk_ev("123"), None)
    assert r["statusCode"] == 200
    assert body(r) == []
    print("  bulk_empty_returns_200_array OK")


# ---------------------------------------------------------------------------
# Per-driver (OpenF1 proxy) tests
# ---------------------------------------------------------------------------
def test_single_found():
    stub_fetch([{"driver_number": 1, "full_name": "Max"}])
    r = lf.lambda_handler(single_ev("1"), None)
    assert r["statusCode"] == 200
    assert body(r)["full_name"] == "Max"
    print("  single_found OK")


def test_single_not_found():
    stub_fetch([])  # OpenF1 404 normalised to []
    r = lf.lambda_handler(single_ev("9999"), None)
    assert r["statusCode"] == 404
    print("  single_not_found OK")


def test_single_bad_number():
    r = lf.lambda_handler(single_ev("abc"), None)
    assert r["statusCode"] == 400
    assert "integer" in body(r)["error"]
    print("  single_bad_number OK")


def test_single_upstream_error():
    stub_fetch(lambda: (_ for _ in ()).throw(ConnectionError("boom")))
    r = lf.lambda_handler(single_ev("1"), None)
    assert r["statusCode"] == 502
    print("  single_upstream_error OK")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def test_unknown_route():
    r = lf.lambda_handler({"resource": "/totally/unknown", "pathParameters": {}}, None)
    assert r["statusCode"] == 404
    print("  unknown_route OK")


def test_cors_header():
    r = lf.respond(200, {"ok": True})
    assert r["headers"]["Access-Control-Allow-Origin"] == "*"
    print("  cors_header OK")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll api-drivers tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
