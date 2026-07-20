"""REST API Lambda for driver metadata (v2).

Handles TWO routes:

  GET /sessions/{sessionId}/drivers       (v2 bulk endpoint — preferred)
    -> Query the Drivers DynamoDB table for all 20 drivers in one call.
       Returns an array of driver objects. This is the route the frontend
       uses on session load; it kills the v1 "drivers show as numbers
       until clicked" bug.

  GET /drivers/{driverNumber}             (per-driver OpenF1 proxy — legacy)
    -> Fetch /drivers?driver_number=<n> from OpenF1. Cheap fallback for
       one-off lookups (e.g. cross-session driver info).

Routing is determined by `event.resource`:
  "/sessions/{sessionId}/drivers"  -> bulk DDB read
  "/drivers/{driverNumber}"        -> per-driver OpenF1 proxy
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
OPENF1_BASE_URL = os.environ.get("OPENF1_BASE_URL", "https://api.openf1.org/v1")
DRIVERS_TABLE = os.environ.get("DRIVERS_TABLE") or None
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

HTTP_TIMEOUT_SECONDS = 4
HTTP_MAX_RETRIES = 2
HTTP_BACKOFF_BASE_SECONDS = 0.5

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# --------------------------------------------------------------------------
# Boto3 client (lazy)
# --------------------------------------------------------------------------
_DDB = None


def ddb():
    global _DDB
    if _DDB is None:
        import boto3
        _DDB = boto3.client("dynamodb")
    return _DDB


# --------------------------------------------------------------------------
# Response helper (CORS on every response; preflight handled in Terraform)
# --------------------------------------------------------------------------
def respond(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


# --------------------------------------------------------------------------
# HTTP — bounded retry on 429/5xx/timeout (for the OpenF1 proxy fallback)
# --------------------------------------------------------------------------
def fetch_json(path, params):
    url = f"{OPENF1_BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    last_exc = None
    for attempt in range(HTTP_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "f1-telemetry-api/2.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code == 404:
                return []
            transient = e.code == 429 or 500 <= e.code < 600
            if transient and attempt < HTTP_MAX_RETRIES:
                time.sleep(HTTP_BACKOFF_BASE_SECONDS * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_exc = e
            if attempt < HTTP_MAX_RETRIES:
                time.sleep(HTTP_BACKOFF_BASE_SECONDS * (attempt + 1))
                continue
            raise
    raise last_exc  # pragma: no cover


# --------------------------------------------------------------------------
# DDB -> plain dict (strips DynamoDB type wrappers)
# --------------------------------------------------------------------------
def from_dynamo(item):
    """Convert a DynamoDB item into a plain dict.

    Numbers come back as strings from boto3; we coerce driver_number back to int
    so the frontend gets the same shape from both routes.
    """
    out = {}
    for k, v in item.items():
        if "S" in v:
            out[k] = v["S"]
        elif "N" in v:
            out[k] = int(v["N"]) if k == "driver_number" else v["N"]
        elif "NULL" in v:
            out[k] = None
        elif "BOOL" in v:
            out[k] = v["BOOL"]
    return out


# --------------------------------------------------------------------------
# Bulk handler: GET /sessions/{sessionId}/drivers
# --------------------------------------------------------------------------
def list_drivers_for_session(session_key):
    if not DRIVERS_TABLE:
        return respond(500, {"error": "DRIVERS_TABLE not configured"})
    try:
        r = ddb().query(
            TableName=DRIVERS_TABLE,
            KeyConditionExpression="session_key = :sk",
            ExpressionAttributeValues={":sk": {"S": str(session_key)}},
        )
    except Exception:
        logger.exception("DDB query failed on %s for session_key=%s", DRIVERS_TABLE, session_key)
        return respond(502, {"error": "failed to query drivers"})

    drivers = [from_dynamo(item) for item in r.get("Items", [])]
    # Sort by driver_number ascending for a stable UI order.
    drivers.sort(key=lambda d: int(d.get("driver_number", 0)))
    return respond(200, drivers)


# --------------------------------------------------------------------------
# Per-driver handler: GET /drivers/{driverNumber} (OpenF1 proxy fallback)
# --------------------------------------------------------------------------
def fetch_single_driver(driver_number):
    try:
        drivers = fetch_json("/drivers", {"driver_number": driver_number})
    except Exception:
        logger.exception("OpenF1 /drivers fetch failed for driver_number=%s", driver_number)
        return respond(502, {"error": "upstream OpenF1 fetch failed"})

    if not drivers:
        return respond(404, {"error": f"driver {driver_number} not found"})
    return respond(200, drivers[0])


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def lambda_handler(event, context):
    """Dispatch on resource path."""
    resource = event.get("resource") or ""
    path_params = event.get("pathParameters") or {}

    if resource == "/sessions/{sessionId}/drivers":
        session_key = path_params.get("sessionId")
        if not session_key:
            return respond(400, {"error": "missing sessionId"})
        logger.info("GET /sessions/%s/drivers", session_key)
        return list_drivers_for_session(session_key)

    if resource == "/drivers/{driverNumber}":
        raw = path_params.get("driverNumber")
        try:
            driver_number = int(raw)
        except (TypeError, ValueError):
            return respond(400, {"error": f"driver number must be an integer, got {raw!r}"})
        logger.info("GET /drivers/%s", driver_number)
        return fetch_single_driver(driver_number)

    return respond(404, {"error": f"unknown route: {resource}"})
