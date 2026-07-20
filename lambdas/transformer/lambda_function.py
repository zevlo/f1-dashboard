"""OpenF1 transformer Lambda.

Triggered by Kinesis EventSource Mapping. Reads enveloped telemetry records
emitted by the poller, routes each by `source`, and writes to the appropriate
DynamoDB table.

Envelope shape (from the poller):
    {
      "source": "position" | "car_data" | "lap" | "race_control" | "session",
      "session_key": <int>,
      "driver_number": <int>,
      "ts": <iso>,
      "payload": { ...OpenF1 record... }
    }

Idempotency: every per-sample write uses a conditional put
(`attribute_not_exists(<SK>)`) so Kinesis redelivery (poller overlap, retries,
batch bisects) is a no-op. Sessions use an unconditional upsert because the
status field mutates over a session's lifetime (active -> completed).
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

# --------------------------------------------------------------------------
# Configuration (env vars are wired by Terraform)
# --------------------------------------------------------------------------
TABLE_NAMES = {
    "sessions":     os.environ.get("SESSIONS_TABLE", ""),
    "positions":    os.environ.get("POSITIONS_TABLE", ""),
    "car_data":     os.environ.get("CAR_DATA_TABLE", ""),
    "laps":         os.environ.get("LAPS_TABLE", ""),
    "race_control": os.environ.get("RACE_CONTROL_TABLE", ""),
}
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# --------------------------------------------------------------------------
# Boto3 — lazy so the module imports without AWS creds (local tests)
# ----------
_DYNAMODB = None


def dynamodb():
    global _DYNAMODB
    if _DYNAMODB is None:
        import boto3
        _DYNAMODB = boto3.resource("dynamodb")
    return _DYNAMODB


# --------------------------------------------------------------------------
# Item builders — pure functions, return (table_key, item, sk_attr).
# sk_attr is the attribute name used in the conditional write; None = upsert.
# --------------------------------------------------------------------------
def _coerce_int(value, default=None):
    if value is None or value == "":
        return default
    return int(value)


def _coerce_float(value, default=None):
    if value is None or value == "":
        return default
    return float(value)


def to_session_item(env):
    """Sessions: PK session_key. Upsert (status mutates over time)."""
    p = env["payload"]
    sk = env["session_key"]
    now = datetime.now(timezone.utc)
    date_end = p.get("date_end")
    status = "completed" if (date_end and datetime.fromisoformat(date_end.replace("Z", "+00:00")) < now) else "active"
    item = {
        "session_key":         str(sk),
        "session_type":        p.get("session_type"),
        "session_name":        p.get("session_name"),
        "circuit_short_name":  p.get("circuit_short_name"),
        "country_name":        p.get("country_name"),
        "date_start":          p.get("date_start"),
        "date_end":            p.get("date_end"),
        "year":                _coerce_int(p.get("year")),
        "status":              status,
    }
    return ("sessions", item, None)


def to_position_item(env):
    """Positions: PK session_key, SK ts_driver = '{date}#{driver}'."""
    p = env["payload"]
    date = p.get("date") or env.get("ts")
    driver = _coerce_int(p.get("driver_number"), default=0)
    item = {
        "session_key":   str(env["session_key"]),
        "ts_driver":     f"{date}#{driver}",
        "driver_number": driver,
        "position":      _coerce_int(p.get("position")),
        "date":          date,
    }
    return ("positions", item, "ts_driver")


def to_car_data_item(env):
    """CarData: PK session_driver = '{session}#{driver}', SK date."""
    p = env["payload"]
    date = p.get("date") or env.get("ts")
    driver = _coerce_int(p.get("driver_number"), default=0)
    item = {
        "session_driver": f"{env['session_key']}#{driver}",
        "date":           date,
        "driver_number":  driver,
        "speed":          _coerce_int(p.get("speed")),
        "throttle":       _coerce_int(p.get("throttle")),
        "brake":          bool(p.get("brake")),
        "gear":           _coerce_int(p.get("n_gear")),
        "rpm":            _coerce_int(p.get("rpm")),
        "drs":            _coerce_int(p.get("drs")),
    }
    return ("car_data", item, "date")


def to_lap_item(env):
    """Laps: PK session_driver, SK lap_number."""
    p = env["payload"]
    driver = _coerce_int(p.get("driver_number"), default=0)
    item = {
        "session_driver": f"{env['session_key']}#{driver}",
        "lap_number":     _coerce_int(p.get("lap_number")),
        "date_start":     p.get("date_start"),
        "lap_duration":   _coerce_float(p.get("lap_duration")),
        "sector_1":       _coerce_float(p.get("duration_sector_1")),
        "sector_2":       _coerce_float(p.get("duration_sector_2")),
        "sector_3":       _coerce_float(p.get("duration_sector_3")),
        "is_pit_out_lap": bool(p.get("is_pit_out_lap")),
        "compound":       p.get("compound"),
    }
    return ("laps", item, "lap_number")


def to_race_control_item(env):
    """RaceControl: PK session_key, SK timestamp (= date)."""
    p = env["payload"]
    ts = p.get("date") or env.get("ts")
    item = {
        "session_key":   str(env["session_key"]),
        "timestamp":     ts,
        "category":      p.get("category"),
        "flag":          p.get("flag"),
        "message":       p.get("message"),
        "driver_number": _coerce_int(p.get("driver_number")),
    }
    return ("race_control", item, "timestamp")


ROUTING = {
    "session":      to_session_item,
    "position":     to_position_item,
    "car_data":     to_car_data_item,
    "lap":          to_lap_item,
    "race_control": to_race_control_item,
}


# --------------------------------------------------------------------------
# Idempotent write
# --------------------------------------------------------------------------
def put_item(table_key, item, sk_attr):
    """Put item with attribute_not_exists(<sk>) condition (or unconditional
    upsert when sk_attr is None). Returns 1 if written, 0 if deduped.

    ConditionalCheckFailedException is swallowed (it means Kinesis redelivered
    a record we already persisted); any other error propagates so the batch
    fails and Kinesis will retry from the last checkpoint.
    """
    table = dynamodb().Table(TABLE_NAMES[table_key])
    # DynamoDB rejects null/None values; drop them (optional fields like
    # driver_number on broadcast race-control events are legitimately absent).
    # boto3 also rejects Python floats — convert to Decimal via str() to avoid
    # binary-representation artifacts (e.g. 78.421 -> 78.42099999...).
    item = {
        k: (Decimal(str(v)) if isinstance(v, float) else v)
        for k, v in item.items()
        if v is not None
    }
    kwargs = {"Item": item}
    if sk_attr:
        # Alias the SK name — some SKs (`date`, `timestamp`, ...) collide with
        # DynamoDB reserved keywords and can't appear raw in a ConditionExpression.
        kwargs["ConditionExpression"] = "attribute_not_exists(#sk)"
        kwargs["ExpressionAttributeNames"] = {"#sk": sk_attr}
    try:
        table.put_item(**kwargs)
        return 1
    except Exception as e:
        # botocore.exceptions.ClientError — avoid hard import for testability
        code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
        if code == "ConditionalCheckFailedException":
            return 0
        raise


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def decode_record(record):
    """Decode a Kinesis event record into the envelope dict."""
    raw = record["kinesis"]["data"]
    return json.loads(base64.b64decode(raw).decode("utf-8"))


def process_record(env):
    """Route one envelope. Returns 1 if written, 0 if skipped/deduped."""
    source = env.get("source")
    builder = ROUTING.get(source)
    if builder is None:
        logger.warning("Unknown source %r; skipping", source)
        return 0
    table_key, item, sk_attr = builder(env)
    return put_item(table_key, item, sk_attr)


def lambda_handler(event, context):
    """Kinesis event source entrypoint. Returns a write/skip summary."""
    written = 0
    skipped = 0
    failed = 0
    for record in event.get("Records", []):
        try:
            env = decode_record(record)
            written += process_record(env)
        except Exception:
            failed += 1
            logger.exception(
                "Failed processing Kinesis record (seq=%s)",
                record.get("kinesis", {}).get("sequenceNumber"),
            )
            # Re-raise on first failure so Kinesis retries the whole batch
            # from the last checkpoint — better than silent partial drops.
            raise

    total = len(event.get("Records", []))
    deduped = total - written - failed
    logger.info(
        "DONE: written=%d deduped_or_skipped=%d failed=%d total=%d",
        written, deduped, failed, total,
    )
    return {
        "statusCode": 200,
        "records":  total,
        "written":  written,
        "skipped":  deduped,
    }
