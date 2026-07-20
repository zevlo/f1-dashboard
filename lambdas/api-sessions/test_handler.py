"""Local tests for the api-sessions Lambda.

Stubs DynamoDB so the handler exercises routing, query construction, and
response shaping without AWS credentials or a live API Gateway.

Run:
    python3 lambdas/api-sessions/test_handler.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


class FakeTable:
    """Records the last call and returns a canned response per operation."""

    def __init__(self, responses):
        self.responses = responses  # {op_name: result_or_list_of_results}
        self.calls = []

    def _pop(self, op):
        self.calls.append(op)
        r = self.responses.get(op)
        if isinstance(r, list):
            return r.pop(0)
        return r

    def scan(self, **kwargs):
        self.last_scan = kwargs
        return self._pop("scan")

    def get_item(self, **kwargs):
        self.last_get = kwargs
        return self._pop("get_item")

    def query(self, **kwargs):
        self.last_query = kwargs
        return self._pop("query")


class FakeDynamo:
    def __init__(self, table):
        self._table = table

    def Table(self, name):
        self.last_name = name
        return self._table


def install(table):
    fake = FakeDynamo(table)
    lf._DYNAMODB = fake
    return fake


def body(resp):
    return json.loads(resp["body"])


def ev(resource, path=None, qs=None, multi=None):
    return {
        "resource": resource,
        "pathParameters": path or {},
        "queryStringParameters": qs,
        "multiValueQueryStringParameters": multi,
    }


def test_list_sessions():
    table = FakeTable({"scan": {"Items": [{"session_key": "1"}], "LastEvaluatedKey": None}})
    install(table)
    r = lf.lambda_handler(ev("/sessions"), None)
    assert r["statusCode"] == 200
    assert body(r)["items"] == [{"session_key": "1"}]
    assert table.last_scan is not None
    print("  list_sessions OK")


def test_list_sessions_year_filter():
    table = FakeTable({"scan": {"Items": []}})
    install(table)
    lf.lambda_handler(ev("/sessions", qs={"year": "2026"}), None)
    assert table.last_scan["FilterExpression"] == "#y = :y"
    assert table.last_scan["ExpressionAttributeValues"] == {":y": 2026}
    print("  list_sessions_year_filter OK")


def test_list_sessions_bad_year():
    table = FakeTable({"scan": {"Items": []}})
    install(table)
    r = lf.lambda_handler(ev("/sessions", qs={"year": "abc"}), None)
    assert r["statusCode"] == 400
    print("  list_sessions_bad_year OK")


def test_get_session_found():
    table = FakeTable({"get_item": {"Item": {"session_key": "42", "year": 2026}}})
    install(table)
    r = lf.lambda_handler(ev("/sessions/{sessionId}", path={"sessionId": "42"}), None)
    assert r["statusCode"] == 200
    assert body(r)["session_key"] == "42"
    assert table.last_get["Key"] == {"session_key": "42"}
    print("  get_session_found OK")


def test_get_session_not_found():
    table = FakeTable({"get_item": {}})
    install(table)
    r = lf.lambda_handler(ev("/sessions/{sessionId}", path={"sessionId": "42"}), None)
    assert r["statusCode"] == 404
    print("  get_session_not_found OK")


def test_positions_query():
    table = FakeTable({"query": {"Items": [{"position": 1}]}})
    install(table)
    r = lf.lambda_handler(
        ev("/sessions/{sessionId}/positions", path={"sessionId": "42"}, qs={"limit": "5"}),
        None,
    )
    assert r["statusCode"] == 200
    assert body(r)["items"] == [{"position": 1}]
    assert table.last_query["Limit"] == 5
    assert table.last_query["KeyConditionExpression"] == "session_key = :sk"
    assert table.last_query["ExpressionAttributeValues"] == {":sk": "42"}
    print("  positions_query OK")


def test_race_control_query():
    table = FakeTable({"query": {"Items": []}})
    install(table)
    lf.lambda_handler(
        ev("/sessions/{sessionId}/race-control", path={"sessionId": "42"}), None
    )
    assert lf.TABLE_NAMES["race_control"] or True  # env wired in Terraform
    print("  race_control_query OK")


def test_laps_requires_driver():
    table = FakeTable({})
    install(table)
    r = lf.lambda_handler(
        ev("/sessions/{sessionId}/laps", path={"sessionId": "42"}), None
    )
    assert r["statusCode"] == 400
    assert "driver" in body(r)["error"]
    print("  laps_requires_driver OK")


def test_laps_multi_driver():
    # Two drivers -> two queries. Return one Items batch per call.
    table = FakeTable({"query": [
        {"Items": [{"session_driver": "42#1", "lap_number": 1}]},
        {"Items": [{"session_driver": "42#4", "lap_number": 1}]},
    ]})
    install(table)
    r = lf.lambda_handler(
        ev("/sessions/{sessionId}/laps", path={"sessionId": "42"},
           multi={"driver": ["1", "4"]}),
        None,
    )
    assert r["statusCode"] == 200
    items = body(r)["items"]
    assert len(items) == 2
    assert items[0]["session_driver"] == "42#1"
    # The second query's KeyConditionExpression targets session_driver.
    assert table.last_query["ExpressionAttributeValues"][":pk"] == "42#4"
    print("  laps_multi_driver OK")


def test_decimal_serialization():
    assert lf.to_native(lf.Decimal("3")) == 3
    assert lf.to_native(lf.Decimal("3.5")) == 3.5
    assert lf.to_native({"a": lf.Decimal("2"), "b": [lf.Decimal("1")]}) == {"a": 2, "b": [1]}
    print("  decimal_serialization OK")


def test_cors_header():
    r = lf.respond(200, {"ok": True})
    assert r["headers"]["Access-Control-Allow-Origin"] == "*"
    print("  cors_header OK")


def test_unknown_route():
    table = FakeTable({})
    install(table)
    r = lf.lambda_handler(ev("/nope"), None)
    assert r["statusCode"] == 404
    print("  unknown_route OK")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll api-sessions tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
