"""Telemetry-stream fanout Lambda.

Triggered by the Positions/CarData/Laps/RaceControl DynamoDB Streams
(NEW_IMAGE) via one event source mapping per table. For each new item:

  1. Dispatch on the source table (from the record's eventSourceARN) to build
     the frontend WS message(s) — spec §6.5:
       Positions   -> position.update
       CarData     -> car_data.update
       Laps        -> lap.complete
       RaceControl -> race_control.event (+ flag.change when it's a flag)
  2. Query the Connections table's by_session GSI for every client watching
     that session_key.
  3. post_to_connection each message to each. On GoneException (410) the client
     dropped without $disconnect — delete the stale row. Other per-connection
     post errors are logged and swallowed so one bad client doesn't fail the
     record (which would duplicate-deliver to everyone else on retry).

Uses DynamoDB Streams batch item failures: only record-level failures (bad
image / query error) are reported, so Kinesis-style redelivery is bounded.
"""

import json
import logging
import os

CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "")
SESSION_INDEX_NAME = os.environ.get("SESSION_INDEX_NAME", "by_session")
WEBSOCKET_API_ENDPOINT = os.environ.get("WEBSOCKET_API_ENDPOINT", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# --------------------------------------------------------------------------
# Boto3 — lazy so the module imports without AWS creds (local tests)
# --------------------------------------------------------------------------
_DYNAMODB = None
_APIMGMT = None


def dynamodb():
    global _DYNAMODB
    if _DYNAMODB is None:
        import boto3
        _DYNAMODB = boto3.resource("dynamodb")
    return _DYNAMODB


def apimgmt():
    global _APIMGMT
    if _APIMGMT is None:
        import boto3
        _APIMGMT = boto3.client("apigatewaymanagementapi", endpoint_url=WEBSOCKET_API_ENDPOINT)
    return _APIMGMT


# --------------------------------------------------------------------------
# Stream record deserialization
#
# DynamoDB Streams delivers NewImage as type-tagged values ({"S": "..."},
# {"N": "123"}, {"BOOL": true}). We only need S/N/BOOL/NULL for Positions
# items, so a small inline converter avoids importing boto3 on this pure path
# (the module imports without AWS creds; clients stay lazy).
# --------------------------------------------------------------------------
def _scalar(typed):
    if "S" in typed:
        return typed["S"]
    if "N" in typed:
        n = typed["N"]
        f = float(n)
        return int(f) if f.is_integer() else f
    if "BOOL" in typed:
        return typed["BOOL"]
    if "NULL" in typed:
        return None
    # Fall through for any edge types (B, L, M, SS, NS) — not present on
    # Positions items, but don't choke if one shows up.
    return next(iter(typed.values()))


def deserialize_image(image):
    """Convert a DynamoDB Stream NewImage (typed) to a plain dict."""
    return {k: _scalar(v) for k, v in image.items()}


# --------------------------------------------------------------------------
# Source dispatch + message builders (spec §6.5)
#
# Each builder is a pure function: item dict -> list of WS messages. Table
# names follow "{project}-{env}-{suffix}", so we dispatch on the suffix parsed
# out of the record's eventSourceARN.
# --------------------------------------------------------------------------

# OpenF1 DRS codes: 10/12/14 mean the flap is open; everything else is closed.
_DRS_OPEN_CODES = {10, 12, 14}


def table_from_arn(event_source_arn):
    """'arn:aws:dynamodb:...:table/{name}/stream/{ts}' -> '{name}' ('' if malformed)."""
    parts = (event_source_arn or "").split(":table/")
    if len(parts) != 2:
        return ""
    return parts[1].split("/")[0]


def source_for_table(table_name):
    """Table name -> logical source key, or None for unrecognized tables."""
    for suffix, source in (
        ("-positions", "positions"),
        ("-car-data", "car_data"),
        ("-laps", "laps"),
        ("-race-control", "race_control"),
    ):
        if table_name.endswith(suffix):
            return source
    return None


def session_key_of(item, source):
    """Extract session_key. CarData/Laps key on session_driver='{session}#{driver}'."""
    if source in ("car_data", "laps"):
        session_driver = item.get("session_driver") or ""
        return session_driver.split("#", 1)[0] or None
    return item.get("session_key")


def build_position_messages(item):
    return [{
        "type": "position.update",
        "data": {
            "driver_number": item.get("driver_number"),
            "position": item.get("position"),
            "ts": item.get("date"),
        },
    }]


def build_car_data_messages(item):
    drs = item.get("drs")
    return [{
        "type": "car_data.update",
        "data": {
            "driver_number": item.get("driver_number"),
            "speed": item.get("speed"),
            "gear": item.get("gear"),
            "rpm": item.get("rpm"),
            "drs": drs in _DRS_OPEN_CODES,
            "throttle": item.get("throttle"),
            # Stored as a boolean; frontend renders a 0-100 bar.
            "brake": 100 if item.get("brake") else 0,
            "ts": item.get("date"),
        },
    }]


def build_lap_messages(item):
    return [{
        "type": "lap.complete",
        "data": {
            "driver_number": item.get("driver_number"),
            "lap_number": item.get("lap_number"),
            "lap_duration": item.get("lap_duration"),
            "sector_1": item.get("sector_1"),
            "sector_2": item.get("sector_2"),
            "sector_3": item.get("sector_3"),
            "compound": item.get("compound"),
        },
    }]


def build_race_control_messages(item):
    messages = [{
        "type": "race_control.event",
        "data": {
            "category": item.get("category"),
            "flag": item.get("flag"),
            "message": item.get("message"),
            "driver_number": item.get("driver_number"),
            "ts": item.get("timestamp"),
        },
    }]
    if item.get("category") == "Flag" and item.get("flag"):
        messages.append({
            "type": "flag.change",
            "data": {"flag": item.get("flag")},
        })
    return messages


BUILDERS = {
    "positions": build_position_messages,
    "car_data": build_car_data_messages,
    "laps": build_lap_messages,
    "race_control": build_race_control_messages,
}


# --------------------------------------------------------------------------
# Fanout
# --------------------------------------------------------------------------
def find_connections(session_key):
    """All connection_ids watching `session_key` (paginate the by_session GSI)."""
    table = dynamodb().Table(CONNECTIONS_TABLE)
    ids = []
    kwargs = {
        "IndexName": SESSION_INDEX_NAME,
        "KeyConditionExpression": "session_key = :sk",
        "ProjectionExpression": "connection_id",
        "ExpressionAttributeValues": {":sk": str(session_key)},
    }
    while True:
        r = table.query(**kwargs)
        for row in r.get("Items", []):
            ids.append(row["connection_id"])
        lek = r.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return ids


def deliver(connection_id, payload_bytes):
    """post_to_connection; delete stale row on GoneException. Returns True on
    success, False on transient error (caller decides retry)."""
    try:
        apimgmt().post_to_connection(ConnectionId=connection_id, Data=payload_bytes)
        return True
    except apimgmt().exceptions.GoneException:  # 410 — client gone
        logger.info("Stale connection %s; deleting", connection_id)
        try:
            dynamodb().Table(CONNECTIONS_TABLE).delete_item(
                Key={"connection_id": connection_id}
            )
        except Exception:
            logger.exception("Failed deleting stale connection %s", connection_id)
        return True  # not a failure — handled
    except Exception as e:
        logger.warning("post_to_connection failed for %s: %s", connection_id, e)
        return False


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def process_record(record):
    """Return True if the record was processed (ok or best-effort), False to retry."""
    new = record.get("dynamodb", {}).get("NewImage")
    if not new:
        return True  # skip REMOVE/UPDATE-old-only records cleanly

    source = source_for_table(table_from_arn(record.get("eventSourceARN")))
    if source is None:
        logger.warning("Unrecognized event source %r; skipping", record.get("eventSourceARN"))
        return True

    item = deserialize_image(new)
    session_key = session_key_of(item, source)
    if session_key is None:
        logger.warning("%s record has no session_key: %s", source, item)
        return True

    messages = BUILDERS[source](item)

    connections = find_connections(session_key)
    if not connections:
        return True  # no viewers; not a failure

    delivered = 0
    attempted = 0
    for message in messages:
        payload = json.dumps(message).encode("utf-8")
        for cid in connections:
            attempted += 1
            if deliver(cid, payload):
                delivered += 1
    logger.info(
        "%s session=%s driver=%s pushed=%d/%d",
        " + ".join(m["type"] for m in messages),
        session_key, item.get("driver_number"), delivered, attempted,
    )
    return True


def lambda_handler(event, context):
    """DynamoDB Streams entrypoint. Returns batchItemFailures for record-level errors."""
    failures = []
    pushed = 0
    for record in event.get("Records", []):
        seq = record.get("dynamodb", {}).get("sequenceNumber")
        try:
            if process_record(record):
                pushed += 1
            else:
                if seq:
                    failures.append(seq)
        except Exception:
            logger.exception("Failed processing stream record seq=%s", seq)
            if seq:
                failures.append(seq)

    logger.info("DONE: processed=%d failed=%d", pushed, len(failures))
    return {
        "batchItemFailures": [{"itemIdentifier": seq} for seq in failures]
    } if failures else {"batchItemFailures": []}
