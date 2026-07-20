"""Local tests for the ws-push fanout Lambda (DynamoDB + mgmt API stubbed).

Run:
    python3 lambdas/ws-push/test_handler.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class FakeTable:
    def __init__(self, items_pages=None):
        self.items_pages = items_pages or []  # list of query-result pages
        self.deleted_keys = []
        self._page = 0

    def query(self, **kwargs):
        page = self.items_pages[self._page] if self._page < len(self.items_pages) else {"Items": []}
        self._page += 1
        self.last_query = kwargs
        return page

    def delete_item(self, **kwargs):
        self.deleted_keys.append(kwargs["Key"])


class FakeDynamo:
    def __init__(self, table):
        self._table = table

    def Table(self, name):
        return self._table


class FakeExceptions:
    class GoneException(Exception):
        pass


class FakeApiMgmt:
    def __init__(self, posts=None, gone=None, fail=None):
        self.exceptions = FakeExceptions
        self.posts = posts or []
        self.gone = set(gone or [])
        self.fail = set(fail or [])
        self.posted = []

    def post_to_connection(self, **kwargs):
        cid = kwargs["ConnectionId"]
        self.posted.append(cid)
        if cid in self.gone:
            raise self.exceptions.GoneException()
        if cid in self.fail:
            raise RuntimeError("transient")
        return {}


def image(**typed):
    """Build a DynamoDB-typed NewImage from python values."""
    out = {}
    for k, v in typed.items():
        if isinstance(v, bool):
            out[k] = {"BOOL": v}
        elif isinstance(v, int):
            out[k] = {"N": str(v)}
        else:
            out[k] = {"S": str(v)}
    return out


def arn(table):
    return f"arn:aws:dynamodb:us-east-1:123456789012:table/{table}/stream/2026-07-05T00:00:00.000"


def stream_record(new_image, seq="1", table="f1-telemetry-dev-positions"):
    return {
        "dynamodb": {"NewImage": new_image, "sequenceNumber": seq},
        "eventName": "INSERT",
        "eventSourceARN": arn(table),
    }


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_build_position_message_shape():
    msgs = lf.build_position_messages({"driver_number": 1, "position": 2, "date": "2026-07-01T10:00:00"})
    assert len(msgs) == 1
    assert msgs[0]["type"] == "position.update"
    assert msgs[0]["data"] == {"driver_number": 1, "position": 2, "ts": "2026-07-01T10:00:00"}
    print("  build_position_message_shape OK")


def test_build_car_data_message_shape():
    msgs = lf.build_car_data_messages({
        "session_driver": "11315#1", "date": "2026-07-01T10:00:00",
        "driver_number": 1, "speed": 348, "throttle": 100, "brake": False,
        "gear": 8, "rpm": 11500, "drs": 12,
    })
    assert len(msgs) == 1
    assert msgs[0]["type"] == "car_data.update"
    d = msgs[0]["data"]
    assert d["speed"] == 348 and d["gear"] == 8 and d["rpm"] == 11500
    assert d["drs"] is True          # DRS code 12 = open
    assert d["throttle"] == 100
    assert d["brake"] == 0           # stored bool -> 0-100 bar value
    # Closed DRS code maps to False.
    closed = lf.build_car_data_messages({"drs": 8, "brake": True})[0]["data"]
    assert closed["drs"] is False and closed["brake"] == 100
    print("  build_car_data_message_shape OK")


def test_build_lap_message_shape():
    msgs = lf.build_lap_messages({
        "session_driver": "11315#1", "driver_number": 1, "lap_number": 35,
        "lap_duration": 84.234, "sector_1": 28.1, "sector_2": 29.0,
        "sector_3": 27.1, "compound": "SOFT",
    })
    assert len(msgs) == 1
    assert msgs[0]["type"] == "lap.complete"
    d = msgs[0]["data"]
    assert d["driver_number"] == 1 and d["lap_number"] == 35 and d["lap_duration"] == 84.234
    assert d["compound"] == "SOFT"
    print("  build_lap_message_shape OK")


def test_build_race_control_messages_flag_emits_flag_change():
    msgs = lf.build_race_control_messages({
        "session_key": "11315", "timestamp": "2026-07-01T10:00:00",
        "category": "Flag", "flag": "YELLOW", "message": "Yellow in sector 2",
    })
    assert [m["type"] for m in msgs] == ["race_control.event", "flag.change"]
    assert msgs[0]["data"]["flag"] == "YELLOW"
    assert msgs[1]["data"] == {"flag": "YELLOW"}
    # Non-flag events emit only race_control.event.
    msgs = lf.build_race_control_messages({
        "session_key": "11315", "timestamp": "t", "category": "Other",
        "message": "Track clear",
    })
    assert [m["type"] for m in msgs] == ["race_control.event"]
    print("  build_race_control_messages_flag_emits_flag_change OK")


def test_source_dispatch_from_arn():
    assert lf.source_for_table(lf.table_from_arn(arn("f1-telemetry-dev-positions"))) == "positions"
    assert lf.source_for_table(lf.table_from_arn(arn("f1-telemetry-dev-car-data"))) == "car_data"
    assert lf.source_for_table(lf.table_from_arn(arn("f1-telemetry-dev-laps"))) == "laps"
    assert lf.source_for_table(lf.table_from_arn(arn("f1-telemetry-dev-race-control"))) == "race_control"
    assert lf.source_for_table(lf.table_from_arn(arn("f1-telemetry-dev-connections"))) is None
    assert lf.source_for_table(lf.table_from_arn("garbage")) is None
    print("  source_dispatch_from_arn OK")


def test_session_key_of_parses_session_driver():
    assert lf.session_key_of({"session_driver": "11315#1"}, "car_data") == "11315"
    assert lf.session_key_of({"session_driver": "11315#44"}, "laps") == "11315"
    assert lf.session_key_of({"session_key": "11315"}, "positions") == "11315"
    assert lf.session_key_of({}, "car_data") is None
    print("  session_key_of_parses_session_driver OK")


def test_deserialize_image():
    # session_key is stored as a string by the transformer; driver/position as N.
    item = lf.deserialize_image(image(session_key="11315", driver_number=1, position=2))
    assert item == {"session_key": "11315", "driver_number": 1, "position": 2}
    print("  deserialize_image OK")


def test_find_connections_paginates():
    lf.CONNECTIONS_TABLE = "conn"
    lf.SESSION_INDEX_NAME = "by_session"
    table = FakeTable(items_pages=[
        {"Items": [{"connection_id": "c1"}, {"connection_id": "c2"}], "LastEvaluatedKey": {"x": "1"}},
        {"Items": [{"connection_id": "c3"}]},
    ])
    lf._DYNAMODB = FakeDynamo(table)
    ids = lf.find_connections(11315)
    assert ids == ["c1", "c2", "c3"]
    assert table.last_query["IndexName"] == "by_session"
    print("  find_connections_paginates OK")


def test_process_record_pushes_to_all_connections():
    lf.CONNECTIONS_TABLE = "conn"
    lf.SESSION_INDEX_NAME = "by_session"
    table = FakeTable(items_pages=[{"Items": [{"connection_id": "c1"}, {"connection_id": "c2"}]}])
    lf._DYNAMODB = FakeDynamo(table)
    api = FakeApiMgmt()
    lf._APIMGMT = api

    ok = lf.process_record(stream_record(image(session_key=11315, driver_number=1, position=2)))
    assert ok is True
    assert api.posted == ["c1", "c2"]
    # Payload is a valid position.update message.
    print("  process_record_pushes_to_all_connections OK")


def test_stale_connection_is_deleted():
    lf.CONNECTIONS_TABLE = "conn"
    lf.SESSION_INDEX_NAME = "by_session"
    table = FakeTable(items_pages=[{"Items": [{"connection_id": "gone"}, {"connection_id": "ok"}]}])
    lf._DYNAMODB = FakeDynamo(table)
    api = FakeApiMgmt(gone={"gone"})
    lf._APIMGMT = api

    lf.process_record(stream_record(image(session_key=11315, driver_number=1, position=3)))
    assert table.deleted_keys == [{"connection_id": "gone"}]
    print("  stale_connection_is_deleted OK")


def test_transient_post_error_does_not_fail_record():
    lf.CONNECTIONS_TABLE = "conn"
    lf.SESSION_INDEX_NAME = "by_session"
    table = FakeTable(items_pages=[{"Items": [{"connection_id": "bad"}]}])
    lf._DYNAMODB = FakeDynamo(table)
    lf._APIMGMT = FakeApiMgmt(fail={"bad"})

    ok = lf.process_record(stream_record(image(session_key=11315, driver_number=1, position=4)))
    assert ok is True  # swallowed, not a record failure
    print("  transient_post_error_does_not_fail_record OK")


def test_no_viewers_is_success():
    lf.CONNECTIONS_TABLE = "conn"
    lf.SESSION_INDEX_NAME = "by_session"
    lf._DYNAMODB = FakeDynamo(FakeTable(items_pages=[{"Items": []}]))
    lf._APIMGMT = FakeApiMgmt()
    ok = lf.process_record(stream_record(image(session_key=11315, driver_number=1, position=5)))
    assert ok is True
    assert lf._APIMGMT.posted == []
    print("  no_viewers_is_success OK")


def test_process_record_car_data_uses_session_driver():
    lf.CONNECTIONS_TABLE = "conn"
    lf.SESSION_INDEX_NAME = "by_session"
    table = FakeTable(items_pages=[{"Items": [{"connection_id": "c1"}]}])
    lf._DYNAMODB = FakeDynamo(table)
    api = FakeApiMgmt()
    lf._APIMGMT = api

    img = image(session_driver="11315#1", date="t", driver_number=1, speed=340, throttle=90, brake=False, gear=7, rpm=11000, drs=0)
    ok = lf.process_record(stream_record(img, table="f1-telemetry-dev-car-data"))
    assert ok is True
    assert api.posted == ["c1"]
    assert table.last_query["ExpressionAttributeValues"] == {":sk": "11315"}
    print("  process_record_car_data_uses_session_driver OK")


def test_process_record_flag_sends_two_messages():
    lf.CONNECTIONS_TABLE = "conn"
    lf.SESSION_INDEX_NAME = "by_session"
    lf._DYNAMODB = FakeDynamo(FakeTable(items_pages=[{"Items": [{"connection_id": "c1"}]}]))
    api = FakeApiMgmt()
    lf._APIMGMT = api

    img = image(session_key="11315", timestamp="t", category="Flag", flag="RED", message="Red flag")
    ok = lf.process_record(stream_record(img, table="f1-telemetry-dev-race-control"))
    assert ok is True
    assert api.posted == ["c1", "c1"]  # race_control.event + flag.change
    print("  process_record_flag_sends_two_messages OK")


def test_unrecognized_source_is_skipped():
    ok = lf.process_record(stream_record(image(session_key="1"), table="f1-telemetry-dev-connections"))
    assert ok is True
    print("  unrecognized_source_is_skipped OK")


def test_skip_remove_records():
    ok = lf.process_record({"dynamodb": {"NewImage": None, "sequenceNumber": "9"}, "eventName": "REMOVE"})
    assert ok is True
    print("  skip_remove_records OK")


def test_handler_returns_no_failures_on_success():
    lf.CONNECTIONS_TABLE = "conn"
    lf.SESSION_INDEX_NAME = "by_session"
    lf._DYNAMODB = FakeDynamo(FakeTable(items_pages=[{"Items": [{"connection_id": "c1"}]}]))
    lf._APIMGMT = FakeApiMgmt()
    ev = {"Records": [stream_record(image(session_key=1, driver_number=1, position=1), seq="100")]}
    r = lf.lambda_handler(ev, None)
    assert r["batchItemFailures"] == []
    print("  handler_returns_no_failures_on_success OK")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll ws-push tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
