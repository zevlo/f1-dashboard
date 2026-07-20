"""WebSocket agent relay Lambda (v2 — Phase 2 stub).

Handles `agent.ask` action on the WebSocket API:

    client -> {action: "agent.ask", text: "...", sessionKey: "...", driverNumber: 1}
    server -> {type: "agent.token", token: "..."} (one per streamed chunk)
    server -> {type: "agent.done",  messageId: "..."}
    server -> {type: "agent.error", error: "..."} (on failure)

Phase 2: AGENT_ENABLED defaults to false, so this Lambda returns a stubbed
reply explaining that AgentCore wiring lands in Phase 5. The shape of the
protocol is real — the frontend AgentChatPanel can be built against it.

Phase 5 (deferred):
  - When AGENT_ENABLED=true, call Bedrock InvokeModelWithResponseStream on
    AGENT_MODEL_ID with the user's prompt + system instructions + tool defs.
  - Each chunk in the response stream is forwarded to the caller's
    connectionId via apigatewaymanagementapi.post_to_connection.
"""

import json
import logging
import os

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
WEBSOCKET_API_ENDPOINT = os.environ.get("WEBSOCKET_API_ENDPOINT") or None
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE") or None
AGENT_MODEL_ID = os.environ.get("AGENT_MODEL_ID", "amazon.nova-pro-v1:0")
AGENT_ENABLED = os.environ.get("AGENT_ENABLED", "false").lower() == "true"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

_APIGW = None


def apigw():
    """Boto3 apigatewaymanagementapi client bound to this WS API endpoint."""
    global _APIGW
    if _APIGW is None:
        import boto3
        # The endpoint URL has the form https://{api-id}.execute-api.{region}.amazonaws.com/{stage}
        _APIGW = boto3.client("apigatewaymanagementapi", endpoint_url=WEBSOCKET_API_ENDPOINT)
    return _APIGW


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def post_to_connection(connection_id, payload):
    """Send one JSON message to a WebSocket connection. Swallows GoneException
    so dropped clients don't crash the loop."""
    try:
        apigw().post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(payload).encode("utf-8"),
        )
    except apigw().exceptions.GoneException:
        logger.info("client %s gone; dropping", connection_id)
    except Exception:
        logger.exception("post_to_connection failed for %s", connection_id)
        raise


def parse_event(event):
    """Pull connectionId + body out of the WS event shape."""
    ctx = event.get("requestContext", {})
    connection_id = ctx.get("connectionId")
    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError:
        body = {}
    return connection_id, body


# --------------------------------------------------------------------------
# Stub reply (Phase 2 default — AGENT_ENABLED=false)
# --------------------------------------------------------------------------
STUB_REPLY = (
    "Race Engineer agent isn't wired yet — this is a stub reply so the chat "
    "panel can be built and tested. AgentCore (Amazon Nova Pro) integration "
    "lands in Phase 5. Your message was received."
)


def run_stub(connection_id, text, session_key, driver_number):
    """Stream the stub reply token-by-token to mimic the real Bedrock stream."""
    import time
    messageId = f"stub-{int(time.time() * 1000)}"
    # Tokenise on word boundaries so the UI sees realistic streaming cadence.
    tokens = STUB_REPLY.split(" ")
    for i, tok in enumerate(tokens):
        suffix = " " if i < len(tokens) - 1 else ""
        post_to_connection(connection_id, {
            "type": "agent.token",
            "messageId": messageId,
            "token": tok + suffix,
        })
        # No sleep in real Lambda — this is just a stub. Real streaming reads
        # from Bedrock's response iterator which has natural pacing.
    post_to_connection(connection_id, {
        "type": "agent.done",
        "messageId": messageId,
    })
    logger.info(
        "STUB reply sent to %s (session=%s driver=%s text=%r)",
        connection_id, session_key, driver_number, text[:80],
    )


# --------------------------------------------------------------------------
# Real reply (Phase 5 — invoked when AGENT_ENABLED=true)
# --------------------------------------------------------------------------
def run_bedrock(connection_id, text, session_key, driver_number):
    """Invoke Bedrock InvokeModelWithResponseStream and forward each chunk.

    Stubbed here — the actual implementation lands in Phase 5 once we wire
    Bedrock AgentCore (system prompt, tool definitions, conversation memory).
    """
    raise NotImplementedError(
        "Bedrock streaming lands in Phase 5. Set AGENT_ENABLED=false for now."
    )


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def lambda_handler(event, context):
    connection_id, body = parse_event(event)
    if not connection_id:
        logger.error("no connectionId in event: %s", event)
        return {"statusCode": 400}

    text = (body.get("text") or "").strip()
    session_key = body.get("sessionKey") or body.get("session_key")
    driver_number = body.get("driverNumber") or body.get("driver_number")

    if not text:
        post_to_connection(connection_id, {
            "type": "agent.error",
            "error": "missing 'text' field",
        })
        return {"statusCode": 200}

    try:
        if AGENT_ENABLED:
            run_bedrock(connection_id, text, session_key, driver_number)
        else:
            run_stub(connection_id, text, session_key, driver_number)
    except Exception as e:
        logger.exception("agent run failed for %s", connection_id)
        post_to_connection(connection_id, {
            "type": "agent.error",
            "error": f"agent failed: {e}",
        })
        return {"statusCode": 500}

    return {"statusCode": 200}
