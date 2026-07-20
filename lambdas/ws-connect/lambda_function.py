"""WebSocket $connect Lambda.

Client opens:  wss://<api-id>.execute-api.<region>.amazonaws.com/<stage>?sessionId=<session_key>
On connect, persist (connection_id, session_key, ttl) so the push Lambda can
fan out Positions writes to every client watching a given session.

Rejects the connection (401) if sessionId is missing — there's nothing to
subscribe to. ttl (~2h) clears connections that drop without a $disconnect.
"""

import logging
import os
import time
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Configuration (env vars are wired by Terraform)
# --------------------------------------------------------------------------
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "")
CONNECTION_TTL_SECONDS = int(os.environ.get("CONNECTION_TTL_SECONDS", "7200"))  # 2h
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

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


def respond(status, message):
    return {"statusCode": status, "body": message}


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def lambda_handler(event, context):
    request_context = event.get("requestContext", {})
    connection_id = request_context.get("connectionId")
    qs = event.get("queryStringParameters") or {}
    session_key = qs.get("sessionId")

    if not connection_id:
        logger.error("No connectionId in event: %s", event)
        return respond(500, "missing connectionId")
    if not session_key:
        logger.info("Rejecting connect %s: no sessionId", connection_id)
        return respond(401, "sessionId query parameter is required")

    now = int(time.time())
    item = {
        "connection_id": connection_id,
        "session_key": str(session_key),
        "connected_at": datetime.now(timezone.utc).isoformat(),
        "ttl": now + CONNECTION_TTL_SECONDS,
    }
    dynamodb().Table(CONNECTIONS_TABLE).put_item(Item=item)
    logger.info("Connected %s -> session %s", connection_id, session_key)
    return respond(200, "connected")
