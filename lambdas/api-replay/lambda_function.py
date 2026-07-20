"""REST API Lambda for bulk session replay (v2).

GET /sessions/{sessionId}/replay -> {
  session:        {...}                  # session metadata
  drivers:        [{...}, ...]           # all 20 drivers (sorted by number)
  positions:      [{...}, ...]           # all position samples (~3.5s cadence)
  race_control:   [{...}, ...]           # flags, incidents, safety car
  laps:           [{...}, ...]           # all lap rows across all drivers
}

The frontend fetches this ONCE on session load (when entering replay mode)
and walks it locally with a client-side clock driven by ReplayControls.
No server-side cursor, no transport round-trips during scrubbing.

CarData is intentionally NOT included — at ~3.5s sampling x 20 drivers x
2 hours, that's ~40k rows. The telemetry panel in replay mode shows the
lap-time chart + position tower without per-sample speed/throttle traces.
Live mode carries car_data via WebSocket as before.

Schema reference (DynamoDB):
  Sessions     PK: session_key
  Drivers      PK: session_key, SK: driver_number
  Positions    PK: session_key, SK: ts_driver
  Laps         PK: session_driver (= "session_key#driver_number"), SK: lap_number
  RaceControl  PK: session_key, SK: timestamp

The Laps PK is composite, so we first list driver_numbers from Drivers and
then Query Laps per (session_driver) — ~20 cheap queries, faster than a Scan.
"""

import json
import logging
import os

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE") or None
POSITIONS_TABLE = os.environ.get("POSITIONS_TABLE") or None
LAPS_TABLE = os.environ.get("LAPS_TABLE") or None
RACE_CONTROL_TABLE = os.environ.get("RACE_CONTROL_TABLE") or None
CAR_DATA_TABLE = os.environ.get("CAR_DATA_TABLE") or None  # unused in payload; kept for future use
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Soft cap on rows returned per section. A full race is ~9k positions, ~1500
# laps, ~200 race-control events — well under these limits, but the caps
# protect against an accidental unbounded Scan.
POSITION_LIMIT = 30_000
LAPS_PER_DRIVER_LIMIT = 200
RACE_CONTROL_LIMIT = 2_000

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

_DDB = None


def ddb():
    global _DDB
    if _DDB is None:
        import boto3
        _DDB = boto3.resource("dynamodb")
    return _DDB


# --------------------------------------------------------------------------
# Response helper
# --------------------------------------------------------------------------
def respond(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        # Reserialise once — Table.scan()/query() returns Decimals which json
        # can't handle directly. We cast on read in `from_dynamo`.
        "body": json.dumps(body, default=str),
    }


# --------------------------------------------------------------------------
# DDB -> plain dict (strips type wrappers, coerces Decimals to int/float)
# --------------------------------------------------------------------------
def from_dynamo(item):
    out = {}
    for k, v in dict(item).items():
        # boto3 resource (dynamodb.Table) returns native Python types, but
        # some attributes (Decimals) still need coercion for json.dumps.
        if hasattr(v, "as_integer_ratio"):  # Decimal-like
            try:
                f = float(v)
                out[k] = int(f) if f.is_integer() else f
            except Exception:
                out[k] = str(v)
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------
# Section fetchers
# --------------------------------------------------------------------------
def fetch_session(session_key):
    if not SESSIONS_TABLE:
        return None
    r = ddb().Table(SESSIONS_TABLE).get_item(Key={"session_key": str(session_key)})
    item = r.get("Item")
    return from_dynamo(item) if item else None


def fetch_drivers(session_key):
    if not SESSIONS_TABLE:
        return []
    # NOTE: we reuse the Drivers table — but it lives behind the api-drivers
    # Lambda's IAM. To keep this Lambda self-contained we query it directly.
    # The api module grants this Lambda read on Sessions/Positions/Laps/
    # RaceControl/CarData — Drivers is added there too via storage outputs.
    drivers_table = os.environ.get("DRIVERS_TABLE")
    if not drivers_table:
        return []
    r = ddb().Table(drivers_table).query(
        KeyConditionExpression="session_key = :sk",
        ExpressionAttributeValues={":sk": str(session_key)},
    )
    drivers = [from_dynamo(i) for i in r.get("Items", [])]
    drivers.sort(key=lambda d: int(d.get("driver_number", 0)))
    return drivers


def fetch_positions(session_key):
    if not POSITIONS_TABLE:
        return []
    table = ddb().Table(POSITIONS_TABLE)
    items = []
    last = None
    while True:
        if last:
            r = table.query(
                KeyConditionExpression="session_key = :sk",
                ExpressionAttributeValues={":sk": str(session_key)},
                ExclusiveStartKey=last,
                Limit=POSITION_LIMIT,
            )
        else:
            r = table.query(
                KeyConditionExpression="session_key = :sk",
                ExpressionAttributeValues={":sk": str(session_key)},
                Limit=POSITION_LIMIT,
            )
        items.extend(r.get("Items", []))
        if len(items) >= POSITION_LIMIT or not r.get("LastEvaluatedKey"):
            break
        last = r["LastEvaluatedKey"]
    return [from_dynamo(i) for i in items[:POSITION_LIMIT]]


def fetch_laps(session_key, driver_numbers):
    """Loop over known drivers and Query Laps per (session_driver)."""
    if not LAPS_TABLE or not driver_numbers:
        return []
    table = ddb().Table(LAPS_TABLE)
    laps = []
    for n in driver_numbers:
        r = table.query(
            KeyConditionExpression="session_driver = :sd",
            ExpressionAttributeValues={":sd": f"{session_key}#{n}"},
            Limit=LAPS_PER_DRIVER_LIMIT,
        )
        laps.extend(from_dynamo(i) for i in r.get("Items", []))
    laps.sort(key=lambda l: (int(l.get("lap_number", 0)), str(l.get("session_driver", ""))))
    return laps


def fetch_race_control(session_key):
    if not RACE_CONTROL_TABLE:
        return []
    table = ddb().Table(RACE_CONTROL_TABLE)
    r = table.query(
        KeyConditionExpression="session_key = :sk",
        ExpressionAttributeValues={":sk": str(session_key)},
        Limit=RACE_CONTROL_LIMIT,
    )
    events = [from_dynamo(i) for i in r.get("Items", [])]
    events.sort(key=lambda e: str(e.get("timestamp", "")))
    return events


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def lambda_handler(event, context):
    """GET /sessions/{sessionId}/replay -> bulk replay payload."""
    path_params = event.get("pathParameters") or {}
    session_key = path_params.get("sessionId")
    if not session_key:
        return respond(400, {"error": "missing sessionId"})

    logger.info("GET /sessions/%s/replay", session_key)

    try:
        session = fetch_session(session_key)
        if not session:
            return respond(404, {"error": f"session {session_key} not found"})

        drivers = fetch_drivers(session_key)
        driver_numbers = [int(d["driver_number"]) for d in drivers if "driver_number" in d]

        positions = fetch_positions(session_key)
        laps = fetch_laps(session_key, driver_numbers)
        race_control = fetch_race_control(session_key)
    except Exception:
        logger.exception("replay fetch failed for session_key=%s", session_key)
        return respond(502, {"error": "failed to fetch replay data"})

    payload = {
        "session": session,
        "drivers": drivers,
        "positions": positions,
        "laps": laps,
        "race_control": race_control,
        "counts": {
            "drivers": len(drivers),
            "positions": len(positions),
            "laps": len(laps),
            "race_control": len(race_control),
        },
    }
    logger.info(
        "replay payload: drivers=%d positions=%d laps=%d race_control=%d",
        len(drivers), len(positions), len(laps), len(race_control),
    )
    return respond(200, payload)
