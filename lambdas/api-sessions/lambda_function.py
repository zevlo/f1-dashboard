"""REST API Lambda for session-scoped queries.

Serves every /sessions* route from the REST API Gateway. Routes are dispatched
on event["resource"] (the matched route template):

    GET /sessions                              -> list sessions (optional ?year=)
    GET /sessions/{sessionId}                  -> one session
    GET /sessions/{sessionId}/positions        -> position samples (?limit=)
    GET /sessions/{sessionId}/race-control     -> race control events (?limit=)
    GET /sessions/{sessionId}/laps             -> laps, requires ?driver=N (repeatable)

The Laps table is keyed by session_driver = "{session}#{driver}", so "all laps
for a session" has no single query; the caller supplies the driver(s) it wants
(one Query per driver, merged). This matches the dashboard's selected-driver +
comparison-drivers lap chart without needing a GSI.

Responses are Lambda-proxy shaped (statusCode / headers / body). CORS header is
set on every response; preflight OPTIONS is handled by a MOCK integration in
Terraform.
"""

import json
import logging
import os
from decimal import Decimal

# --------------------------------------------------------------------------
# Configuration (env vars are wired by Terraform)
# --------------------------------------------------------------------------
TABLE_NAMES = {
    "sessions":     os.environ.get("SESSIONS_TABLE", ""),
    "positions":    os.environ.get("POSITIONS_TABLE", ""),
    "laps":         os.environ.get("LAPS_TABLE", ""),
    "race_control": os.environ.get("RACE_CONTROL_TABLE", ""),
}
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
MAX_LIMIT = 1000  # cap any ?limit= to avoid runaway scans/queries

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# --------------------------------------------------------------------------
# Boto3 — lazy so the module imports without AWS creds (local tests)
# --------------------------------------------------------------------------
_DYNAMODB = None


def dynamodb():
    global _DYNAMODB
    if _DYNAMODB is None:
        import boto3
        _DYNAMODB = boto3.resource("dynamodb")
    return _DYNAMODB


# --------------------------------------------------------------------------
# Serialization / response helpers
# --------------------------------------------------------------------------
def to_native(obj):
    """Convert a DynamoDB item (Decimal-typed numbers) to JSON-safe natives."""
    if isinstance(obj, Decimal):
        # int if whole, else float
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_native(v) for v in obj]
    return obj


def respond(status, body):
    """Build a Lambda-proxy response with CORS headers."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def parse_limit(qs):
    """Read ?limit=, coerce to int, clamp to [1, MAX_LIMIT]. None = table default."""
    if not qs or "limit" not in qs:
        return None
    try:
        n = int(qs["limit"])
    except (ValueError, TypeError):
        return None
    return max(1, min(n, MAX_LIMIT))


# --------------------------------------------------------------------------
# Route handlers
# --------------------------------------------------------------------------
def list_sessions(qs):
    """GET /sessions — Scan with optional ?year= filter."""
    table = dynamodb().Table(TABLE_NAMES["sessions"])
    kwargs = {}
    year = qs.get("year") if qs else None
    if year:
        try:
            kwargs["FilterExpression"] = "#y = :y"
            kwargs["ExpressionAttributeNames"] = {"#y": "year"}
            kwargs["ExpressionAttributeValues"] = {":y": int(year)}
        except (ValueError, TypeError):
            return respond(400, {"error": "year must be an integer"})
    limit = parse_limit(qs)
    if limit:
        kwargs["Limit"] = limit
    r = table.scan(**kwargs)
    return respond(200, {
        "items": to_native(r.get("Items", [])),
        "nextCursor": r.get("LastEvaluatedKey"),  # opaque; client echoes as ?cursor=
    })


def get_session(session_id):
    """GET /sessions/{sessionId} — GetItem."""
    table = dynamodb().Table(TABLE_NAMES["sessions"])
    r = table.get_item(Key={"session_key": session_id})
    item = r.get("Item")
    if not item:
        return respond(404, {"error": "session not found"})
    return respond(200, to_native(item))


def query_by_session(table_key, session_id, qs):
    """GET /sessions/{sessionId}/positions|race-control — Query PK=session_key."""
    table = dynamodb().Table(TABLE_NAMES[table_key])
    kwargs = {
        "KeyConditionExpression": "session_key = :sk",
        "ExpressionAttributeValues": {":sk": session_id},
    }
    limit = parse_limit(qs)
    if limit:
        kwargs["Limit"] = limit
    r = table.query(**kwargs)
    return respond(200, {
        "items": to_native(r.get("Items", [])),
        "nextCursor": r.get("LastEvaluatedKey"),
    })


def get_laps(session_id, qs):
    """GET /sessions/{sessionId}/laps?driver=N — Query Laps PK=session_driver per driver."""
    drivers = (qs or {}).get("driver")
    if not drivers:
        return respond(400, {"error": "?driver=<number> is required (repeatable)"})
    # API Gateway delivers repeated ?driver= as multiValueQueryStringParameters;
    # the single-value dict only carries the last. Caller passes multi via
    # multiValueQueryStringParameters — but Lambda proxy also exposes that on the
    # event separately. Fall back to comma-split for clients that send one value.
    if not isinstance(drivers, list):
        drivers = [drivers]
    nums = []
    for d in drivers:
        try:
            nums.append(int(d))
        except (ValueError, TypeError):
            return respond(400, {"error": f"driver must be an integer, got {d!r}"})

    table = dynamodb().Table(TABLE_NAMES["laps"])
    out = []
    for n in nums:
        kwargs = {
            "KeyConditionExpression": "session_driver = :pk",
            "ExpressionAttributeValues": {":pk": f"{session_id}#{n}"},
        }
        limit = parse_limit(qs)
        if limit:
            kwargs["Limit"] = limit
        r = table.query(**kwargs)
        out.extend(r.get("Items", []))
    # Sort: driver_number, then lap_number — stable, predictable for the chart.
    out.sort(key=lambda x: (x.get("session_driver", ""), x.get("lap_number", 0)))
    return respond(200, {"items": to_native(out)})


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def lambda_handler(event, context):
    """API Gateway Lambda-proxy entrypoint. Dispatches on the matched resource."""
    resource = event.get("resource", "")
    path_params = event.get("pathParameters") or {}
    qs = event.get("queryStringParameters") or {}
    # Merge multi-value query params (e.g. ?driver=1&driver=4) over single-value.
    multi = event.get("multiValueQueryStringParameters") or {}
    if "driver" in multi:
        qs = dict(qs)
        qs["driver"] = multi["driver"]

    session_id = path_params.get("sessionId")

    logger.info("%s sessionId=%s qs=%s", resource, session_id, qs)

    try:
        if resource == "/sessions":
            return list_sessions(qs)
        if resource == "/sessions/{sessionId}":
            return get_session(session_id)
        if resource == "/sessions/{sessionId}/positions":
            return query_by_session("positions", session_id, qs)
        if resource == "/sessions/{sessionId}/race-control":
            return query_by_session("race_control", session_id, qs)
        if resource == "/sessions/{sessionId}/laps":
            return get_laps(session_id, qs)
        return respond(404, {"error": f"unknown route: {resource}"})
    except Exception:
        logger.exception("handler failed for resource=%s", resource)
        return respond(500, {"error": "internal error"})
