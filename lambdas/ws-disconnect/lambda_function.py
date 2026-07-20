"""WebSocket $disconnect Lambda.

Delete the connection row. Idempotent: if the row is already gone (TTL or a
prior disconnect), DynamoDB DeleteItem on a missing PK is a no-op.
"""

import logging
import os

CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

_DYNAMODB = None


def dynamodb():
    global _DYNAMODB
    if _DYNAMODB is None:
        import boto3
        _DYNAMODB = boto3.resource("dynamodb")
    return _DYNAMODB


def lambda_handler(event, context):
    connection_id = event.get("requestContext", {}).get("connectionId")
    if not connection_id:
        logger.error("No connectionId in event: %s", event)
        return {"statusCode": 500, "body": "missing connectionId"}

    dynamodb().Table(CONNECTIONS_TABLE).delete_item(Key={"connection_id": connection_id})
    logger.info("Disconnected %s", connection_id)
    return {"statusCode": 200, "body": "disconnected"}
