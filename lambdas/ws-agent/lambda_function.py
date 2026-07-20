"""WebSocket agent relay Lambda (v2 — Phase 5).

Handles `agent.ask` action on the WebSocket API:

    client -> {action: "agent.ask", text: "...", sessionKey: "...", driverNumber: 1}
    server -> {type: "agent.token", messageId: "...", token: "..."} (many)
    server -> {type: "agent.done",  messageId: "..."}
    server -> {type: "agent.error", error: "..."} (on failure)

Implementation:
  - Bedrock Nova Pro via converse_stream (not AgentCore Runtime — raw Converse
    gets the same UX with fewer moving parts)
  - 5 telemetry-lookup tools implemented as inline DDB queries
  - Conversation history kept in-memory per connectionId (lost on cold start;
    fine for a demo and avoids adding an AgentSessions table)
  - When the model emits tool_use, we execute the tool and re-call
    converse_stream with the tool_result. Loop until no more tool_use.
"""

import json
import logging
import os
import time
from decimal import Decimal

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
WEBSOCKET_API_ENDPOINT = os.environ.get("WEBSOCKET_API_ENDPOINT") or None
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE") or None
AGENT_MODEL_ID = os.environ.get("AGENT_MODEL_ID", "amazon.nova-pro-v1:0")
AGENT_ENABLED = os.environ.get("AGENT_ENABLED", "false").lower() == "true"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Telemetry tables (read by tools).
TABLES = {
    "sessions":     os.environ.get("SESSIONS_TABLE", ""),
    "drivers":      os.environ.get("DRIVERS_TABLE", ""),
    "positions":    os.environ.get("POSITIONS_TABLE", ""),
    "laps":         os.environ.get("LAPS_TABLE", ""),
    "race_control": os.environ.get("RACE_CONTROL_TABLE", ""),
    "car_data":     os.environ.get("CAR_DATA_TABLE", ""),
}

# Cap how many tool-use round-trips we allow per agent.ask. Guards against
# runaway loops if the model keeps calling tools forever.
MAX_TOOL_ROUNDS = 5

# Cap rows returned per tool so a chatty model can't OOM the Lambda.
ROWS_PER_QUERY = 50

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# --------------------------------------------------------------------------
# Boto3 clients (lazy so module imports without creds for local tests)
# --------------------------------------------------------------------------
_APIGW = None
_DDB = None
_BEDROCK = None


def apigw():
    global _APIGW
    if _APIGW is None:
        import boto3
        _APIGW = boto3.client("apigatewaymanagementapi", endpoint_url=WEBSOCKET_API_ENDPOINT)
    return _APIGW


def ddb():
    global _DDB
    if _DDB is None:
        import boto3
        _DDB = boto3.resource("dynamodb")
    return _DDB


def bedrock():
    global _BEDROCK
    if _BEDROCK is None:
        import boto3
        _BEDROCK = boto3.client("bedrock-runtime")
    return _BEDROCK


# --------------------------------------------------------------------------
# In-memory conversation history per connectionId.
# Lost on cold start; the UI already resets chat on reconnect, so this is fine.
# Cap messages per connection to bound memory.
# --------------------------------------------------------------------------
MAX_HISTORY_PER_CONN = 30
_conversations: dict[str, list[dict]] = {}


def get_history(connection_id: str) -> list[dict]:
    return _conversations.setdefault(connection_id, [])


def trim_history(connection_id: str) -> None:
    h = _conversations.get(connection_id)
    if h and len(h) > MAX_HISTORY_PER_CONN:
        # Keep system-prompt-less user/assistant turns; drop oldest.
        _conversations[connection_id] = h[-MAX_HISTORY_PER_CONN:]


def clear_history(connection_id: str) -> None:
    _conversations.pop(connection_id, None)


# --------------------------------------------------------------------------
# WS -> client helpers
# --------------------------------------------------------------------------
def post_to_connection(connection_id, payload):
    """Send one JSON message to a WebSocket connection. Swallows GoneException."""
    try:
        apigw().post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(payload, default=str).encode("utf-8"),
        )
    except Exception as e:
        # GoneException subclass check without importing the exception class.
        code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
        if code == "GoneException":
            logger.info("client %s gone; clearing history", connection_id)
            clear_history(connection_id)
            return
        logger.exception("post_to_connection failed for %s", connection_id)
        raise


def parse_event(event):
    ctx = event.get("requestContext", {})
    connection_id = ctx.get("connectionId")
    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError:
        body = {}
    return connection_id, body


# --------------------------------------------------------------------------
# DDB coercion (Decimals -> int/float, drop None)
# --------------------------------------------------------------------------
def from_dynamo(item):
    out = {}
    for k, v in dict(item).items():
        if hasattr(v, "as_integer_ratio"):
            try:
                f = float(v)
                out[k] = int(f) if f.is_integer() else f
            except Exception:
                out[k] = str(v)
        else:
            out[k] = v
    return out


# ----------------------------------------------------------------------------
# Driver registry — one DynamoDB Query on the Drivers table per agent.ask
# invocation, shared across all tools. Provides the acronym/full_name lookup
# so tool responses (and the model's replies) can reference drivers by name
# instead of just driver_number.
# ----------------------------------------------------------------------------
def load_driver_registry(session_key):
    """Return dict[driver_number_int, {name_acronym, full_name, team_name, team_colour}].

    Empty dict on miss / error — tools fall back to number-only responses.
    """
    registry = {}
    if not session_key or not TABLES.get("drivers"):
        return registry
    try:
        r = ddb().Table(TABLES["drivers"]).query(
            KeyConditionExpression="session_key = :sk",
            ExpressionAttributeValues={":sk": str(session_key)},
        )
    except Exception:
        logger.exception("driver registry load failed for session_key=%s", session_key)
        return registry
    for item in r.get("Items", []):
        d = from_dynamo(item)
        dn = d.get("driver_number")
        if dn is None:
            continue
        try:
            dn_int = int(dn)
        except (TypeError, ValueError):
            continue
        registry[dn_int] = {
            "name_acronym": d.get("name_acronym") or "",
            "full_name": d.get("full_name") or "",
            "team_name": d.get("team_name") or "",
            "team_colour": d.get("team_colour") or "",
        }
    return registry


def driver_view(registry, driver_number):
    """Look up a driver's name fields from the registry. Returns a dict with
    name_acronym/full_name/team_name (empty strings if not found)."""
    return registry.get(int(driver_number), {
        "name_acronym": "",
        "full_name": "",
        "team_name": "",
        "team_colour": "",
    })


# ============================================================================
# TOOLS — 5 read-only telemetry lookups.
# Each returns a dict that gets JSON-serialised into the tool_result content.
# ============================================================================

def tool_get_session(args, registry):
    """get_session: session metadata for one session_key.

    `registry` is unused — accepted for dispatch consistency with other tools.
    """
    sk = str(args.get("session_key", "")).strip()
    if not sk:
        return {"error": "session_key is required"}
    r = ddb().Table(TABLES["sessions"]).get_item(Key={"session_key": sk})
    item = r.get("Item")
    if not item:
        return {"error": f"session {sk} not found"}
    return {"session": from_dynamo(item)}


def tool_get_standings(args, registry):
    """get_standings: latest position per driver for a session.

    Returns an array of {driver_number, position, name_acronym, full_name,
    team_name, ts} sorted P1..Pn.
    """
    sk = str(args.get("session_key", "")).strip()
    if not sk:
        return {"error": "session_key is required"}
    r = ddb().Table(TABLES["positions"]).query(
        KeyConditionExpression="session_key = :sk",
        ExpressionAttributeValues={":sk": sk},
        Limit=ROWS_PER_QUERY * 4,  # 50 drivers * ~4 samples each is enough for standings
    )
    # Keep only the latest sample per driver.
    latest: dict[int, dict] = {}
    for item in r.get("Items", []):
        d = from_dynamo(item)
        dn = d.get("driver_number")
        if dn is None:
            continue
        prev = latest.get(dn)
        if prev is None or str(d.get("date", "")) > str(prev.get("date", "")):
            latest[dn] = d
    standings = sorted(latest.values(), key=lambda x: x.get("position", 999))
    # Slim each row for token efficiency. Include name fields so the agent can
    # reply with "NOR is leading" instead of "Driver number 1".
    slim = []
    for row in standings[:ROWS_PER_QUERY]:
        dn = row.get("driver_number")
        drv = driver_view(registry, dn) if dn is not None else {}
        slim.append({
            "position": row.get("position"),
            "driver_number": dn,
            "name_acronym": drv.get("name_acronym"),
            "full_name": drv.get("full_name"),
            "team_name": drv.get("team_name"),
            "ts": row.get("date"),
        })
    return {"standings": slim}


def tool_get_driver_laps(args, registry):
    """get_driver_laps: lap times + sectors for one driver.

    Optional lap_start/lap_end range; defaults to all laps. Response includes
    the driver's name_acronym + full_name + team_name so the agent can refer
    to them by name in the reply.
    """
    sk = str(args.get("session_key", "")).strip()
    driver_number = args.get("driver_number")
    if not sk or driver_number is None:
        return {"error": "session_key and driver_number are required"}
    try:
        driver_number = int(driver_number)
    except (TypeError, ValueError):
        return {"error": "driver_number must be an integer"}

    sd = f"{sk}#{driver_number}"
    r = ddb().Table(TABLES["laps"]).query(
        KeyConditionExpression="session_driver = :sd",
        ExpressionAttributeValues={":sd": sd},
        Limit=ROWS_PER_QUERY,
    )
    laps = [from_dynamo(i) for i in r.get("Items", [])]

    lap_start = args.get("lap_start")
    lap_end = args.get("lap_end")
    if lap_start is not None:
        laps = [l for l in laps if l.get("lap_number", 0) >= int(lap_start)]
    if lap_end is not None:
        laps = [l for l in laps if l.get("lap_number", 0) <= int(lap_end)]

    drv = driver_view(registry, driver_number)
    return {
        "driver_number": driver_number,
        "name_acronym": drv.get("name_acronym"),
        "full_name": drv.get("full_name"),
        "team_name": drv.get("team_name"),
        "lap_count": len(laps),
        "laps": [
            {
                "lap_number": l.get("lap_number"),
                "lap_duration": l.get("lap_duration"),
                "sector_1": l.get("sector_1"),
                "sector_2": l.get("sector_2"),
                "sector_3": l.get("sector_3"),
                "compound": l.get("compound"),
            }
            for l in laps
        ],
    }


def tool_get_telemetry_sample(args, registry):
    """get_telemetry_sample: latest car_data sample for one driver.

    Returns speed/throttle/brake/gear/rpm/drs at the most recent timestamp.
    Response includes the driver's name so the agent can refer to them by name.
    """
    sk = str(args.get("session_key", "")).strip()
    driver_number = args.get("driver_number")
    if not sk or driver_number is None:
        return {"error": "session_key and driver_number are required"}
    try:
        driver_number = int(driver_number)
    except (TypeError, ValueError):
        return {"error": "driver_number must be an integer"}

    sd = f"{sk}#{driver_number}"
    # Query in descending date order, take the first (most recent).
    r = ddb().Table(TABLES["car_data"]).query(
        KeyConditionExpression="session_driver = :sd",
        ExpressionAttributeValues={":sd": sd},
        Limit=1,
        ScanIndexForward=False,
    )
    items = r.get("Items", [])
    drv = driver_view(registry, driver_number)
    if not items:
        return {
            "driver_number": driver_number,
            "name_acronym": drv.get("name_acronym"),
            "full_name": drv.get("full_name"),
            "team_name": drv.get("team_name"),
            "telemetry": None,
            "note": "no car_data samples",
        }
    return {
        "driver_number": driver_number,
        "name_acronym": drv.get("name_acronym"),
        "full_name": drv.get("full_name"),
        "team_name": drv.get("team_name"),
        "telemetry": from_dynamo(items[0]),
    }


def tool_get_race_control(args, registry):
    """get_race_control: flags + incidents for a session, newest first.

    Optional `since` filters to events after the given ISO timestamp. Events
    with a driver_number include name_acronym when the driver is in the
    registry.
    """
    sk = str(args.get("session_key", "")).strip()
    if not sk:
        return {"error": "session_key is required"}
    r = ddb().Table(TABLES["race_control"]).query(
        KeyConditionExpression="session_key = :sk",
        ExpressionAttributeValues={":sk": sk},
        Limit=ROWS_PER_QUERY,
        ScanIndexForward=False,  # newest first
    )
    events = [from_dynamo(i) for i in r.get("Items", [])]
    since = args.get("since")
    if since:
        events = [e for e in events if str(e.get("timestamp", "")) > str(since)]
    # Strip session_key from each row (redundant in this context). Include
    # name_acronym for events scoped to a driver.
    slim = []
    for e in events:
        dn = e.get("driver_number")
        row = {
            "timestamp": e.get("timestamp"),
            "category": e.get("category"),
            "flag": e.get("flag"),
            "message": e.get("message"),
            "driver_number": dn,
        }
        if dn is not None:
            row["name_acronym"] = driver_view(registry, dn).get("name_acronym")
        slim.append(row)
    return {"events": slim}


# Tool dispatch — name -> callable(args) -> dict.
TOOLS = {
    "get_session":         tool_get_session,
    "get_standings":       tool_get_standings,
    "get_driver_laps":     tool_get_driver_laps,
    "get_telemetry_sample": tool_get_telemetry_sample,
    "get_race_control":    tool_get_race_control,
}


# ============================================================================
# Tool specifications handed to Bedrock. The model uses these to decide when
# to emit tool_use blocks. Keep the descriptions specific enough that the
# model picks the right tool for the question.
# ============================================================================
TOOL_SPECS = [
    {
        "toolSpec": {
            "name": "get_session",
            "description": (
                "Fetch metadata for a single F1 session (circuit, date range, status). "
                "Call this when the user asks about the session itself — what circuit, "
                "what race weekend, when did it start/end, is it live or historical."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "session_key": {
                            "type": "string",
                            "description": "The OpenF1 session_key (numeric string).",
                        },
                    },
                    "required": ["session_key"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_standings",
            "description": (
                "Fetch the current race standings (P1..Pn) for a session. Returns one row "
                "per driver with their latest position and the timestamp of that sample. "
                "Call this for questions like 'who is leading', 'what's the running order', "
                "'where is VER'."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string"},
                    },
                    "required": ["session_key"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_driver_laps",
            "description": (
                "Fetch lap times + sector splits for one driver in a session. Use for "
                "questions like 'show VER lap times', 'what was NOR's fastest lap', "
                "'compare sector 2 across laps'. Optional lap_start/lap_end to scope "
                "the range. Returns up to 50 laps in descending recency."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "session_key":   {"type": "string"},
                        "driver_number": {"type": "number", "description": "OpenF1 driver number (e.g. 1 for Verstappen, 4 for Norris)."},
                        "lap_start":     {"type": "number", "description": "Optional inclusive lower bound."},
                        "lap_end":       {"type": "number", "description": "Optional inclusive upper bound."},
                    },
                    "required": ["session_key", "driver_number"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_telemetry_sample",
            "description": (
                "Fetch the most recent car telemetry sample (speed, throttle, brake, gear, "
                "rpm, drs) for one driver. Use for 'how fast is VER right now', 'is he "
                "on the throttle', 'what gear through turn X'. Note: returns ONE sample — "
                "do not call for trends over a lap, use get_driver_laps for that."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "session_key":   {"type": "string"},
                        "driver_number": {"type": "number"},
                    },
                    "required": ["session_key", "driver_number"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_race_control",
            "description": (
                "Fetch race-control events — flags (yellow/red/green/blue), safety car, "
                "incidents — newest first. Use for 'what happened', 'why was there a safety "
                "car', 'any penalties'. Optional `since` ISO timestamp to scope to events "
                "after a given moment."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "session_key": {"type": "string"},
                        "since":       {"type": "string", "description": "Optional ISO timestamp."},
                    },
                    "required": ["session_key"],
                }
            },
        }
    },
]


# ============================================================================
# Race-engineer system prompt. Persona + scope guardrails.
# ============================================================================
SYSTEM_PROMPT = """You are the Race Engineer for an F1 telemetry dashboard.

Your job: answer the user's questions about the currently selected session
using the telemetry-lookup tools available to you. Be concise, technical,
and direct — like a real race engineer radio. No marketing fluff.

Rules:
1. ALWAYS use a tool when the user asks a factual question about the session,
   drivers, laps, telemetry, or race-control events. Never guess — the data
   is one tool call away.
2. Prefer batched, specific questions. If you need both standings and a
   driver's laps, call both tools in one assistant turn.
3. ALWAYS refer to drivers by their 3-letter acronym (e.g. VER, NOR, RUS, HAM)
   in replies. NEVER say "Driver number X" — race engineers don't talk like
   that. Tool responses include name_acronym for every driver; use it.
4. If the user mentions a driver by name (e.g. "Verstappen", "Max", "VER")
   and you don't already know their driver_number from prior tool results,
   call get_standings first to resolve the acronym to a driver_number before
   calling per-driver tools like get_driver_laps or get_telemetry_sample.
5. Numbers are sacred. Quote lap times to 3 decimal places, speeds as integers.
   Never round, never invent.
6. If a tool returns empty results, say so plainly — don't make up data.
7. For comparisons ("who was faster on sector 2"), do the math yourself from
   the tool results. Show the delta. Use acronyms for both drivers.
8. Keep replies under 4 sentences unless the user asks for detail. Race
   engineers speak in bursts.
9. Don't refer to "tools" or "APIs" or "calls" — you "checked the timing
   tower" or "pulled the lap chart" or "looked at the most recent sample".
10. Do NOT wrap internal reasoning in <thinking> or <reasoning> tags. Do NOT
    reveal chain-of-thought. Respond directly with the answer.

The current session_key is injected at the start of each user turn by the
runtime. Use that session_key in tool calls unless the user explicitly
asks about a different session."""


# ============================================================================
# Converse loop
# ============================================================================

def stream_assistant(connection_id, message_id, messages, registry):
    """Call bedrock converse_stream, forward text tokens to the client, and
    accumulate any tool_use blocks. Returns the assistant message in the
    Bedrock message format (role + content blocks).

    Loops through tool round-trips: if the assistant emitted tool_use, we
    execute each tool (with the driver registry so responses include names),
    append tool_result messages, and call again.
    """
    rounds = 0
    while True:
        rounds += 1
        if rounds > MAX_TOOL_ROUNDS:
            post_to_connection(connection_id, {
                "type": "agent.token",
                "messageId": message_id,
                "token": " (tool-call limit reached)",
            })
            break

        assistant_content_blocks = []
        tool_use_blocks = []  # accumulate {toolUseId, name, input}
        current_tool_use = None  # building block while streaming

        # First call (or after tool_results): stream the assistant turn.
        resp = bedrock().converse_stream(
            modelId=AGENT_MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            toolConfig={"tools": TOOL_SPECS},
            inferenceConfig={"maxTokens": 800, "temperature": 0.4},
        )

        for event in resp.get("stream", []):
            # Text token — stream to client.
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"]["delta"]
                if "text" in delta:
                    assistant_content_blocks.append({"text": delta["text"]})
                    post_to_connection(connection_id, {
                        "type": "agent.token",
                        "messageId": message_id,
                        "token": delta["text"],
                    })
                elif "toolUse" in delta:
                    # Stream input JSON deltas into the current toolUse block.
                    if current_tool_use is None:
                        # Shouldn't happen — contentBlockStart fires first — but guard.
                        continue
                    input_delta = delta["toolUse"].get("input", "")
                    if isinstance(input_delta, str) and input_delta:
                        current_tool_use["input_buffer"] += input_delta

            # Block start — registers a new content block (text or tool_use).
            elif "contentBlockStart" in event:
                start = event["contentBlockStart"]
                if start.get("start", {}).get("toolUse"):
                    tu = start["start"]["toolUse"]
                    current_tool_use = {
                        "toolUseId": tu.get("toolUseId"),
                        "name": tu.get("name"),
                        "input_buffer": "",
                    }

            # Block stop — flushes the current block.
            elif "contentBlockStop" in event:
                if current_tool_use is not None:
                    # Parse the accumulated input JSON.
                    try:
                        parsed = json.loads(current_tool_use["input_buffer"] or "{}")
                    except json.JSONDecodeError:
                        parsed = {}
                    current_tool_use["input"] = parsed
                    tool_use_blocks.append(current_tool_use)
                    # Record this as a toolUse block in the assistant content.
                    assistant_content_blocks.append({
                        "toolUse": {
                            "toolUseId": current_tool_use["toolUseId"],
                            "name": current_tool_use["name"],
                            "input": parsed,
                        }
                    })
                    current_tool_use = None

            elif "internalServerException" in event or "serviceQuotaExceededException" in event \
                 or "throttlingException" in event or "modelStreamErrorException" in event:
                err = (event.get("internalServerException", {})
                       or event.get("serviceQuotaExceededException", {})
                       or event.get("throttlingException", {})
                       or event.get("modelStreamErrorException", {}))
                msg = err.get("message", "Bedrock stream error")
                raise RuntimeError(f"Bedrock stream error: {msg}")

        # Append the assistant turn to the conversation.
        messages.append({"role": "assistant", "content": assistant_content_blocks})

        # If no tool_use, we're done.
        if not tool_use_blocks:
            break

        # Otherwise: execute each tool, append tool_result, and loop.
        logger.info(
            "agent round %d: executing %d tool calls: %s",
            rounds, len(tool_use_blocks), [t["name"] for t in tool_use_blocks],
        )
        tool_results = []
        for t in tool_use_blocks:
            fn = TOOLS.get(t["name"])
            if fn is None:
                result = {"error": f"unknown tool {t['name']}"}
            else:
                try:
                    result = fn(t["input"], registry)
                except Exception as e:
                    logger.exception("tool %s failed", t["name"])
                    result = {"error": f"{type(e).__name__}: {e}"}
            tool_results.append({
                "toolResult": {
                    "toolUseId": t["toolUseId"],
                    "content": [{"json": result}],
                }
            })

        messages.append({"role": "user", "content": tool_results})
        # Loop continues — converse_stream again with the tool_results.


# ============================================================================
# Entrypoint
# ============================================================================

def run_stub(connection_id, text, session_key, driver_number):
    """Phase 2 stub — kept for the agent_enabled=false path so the panel is
    still demoable without paying for Bedrock invoke."""
    messageId = f"stub-{int(time.time() * 1000)}"
    stub = (
        f"Race Engineer agent isn't wired yet — AGENT_ENABLED=false. "
        f"Your message was received: {text[:80]!r}."
    )
    for tok in stub.split(" "):
        post_to_connection(connection_id, {
            "type": "agent.token",
            "messageId": messageId,
            "token": tok + " ",
        })
    post_to_connection(connection_id, {"type": "agent.done", "messageId": messageId})


def run_bedrock(connection_id, text, session_key, driver_number):
    """Phase 5 path: real Bedrock Nova Pro via converse_stream with tools."""
    if not AGENT_MODEL_ID:
        raise RuntimeError("AGENT_MODEL_ID not configured")

    # Pull conversation history for this connection. Append the user's new
    # turn (with runtime context injected) and run the loop.
    history = get_history(connection_id)

    # Always load the driver registry once per agent.ask — gives every tool
    # access to name_acronym + full_name for the session's 20 drivers without
    # each tool re-querying. Cheap (~10ms, one DDB Query, ~20 rows).
    registry = load_driver_registry(session_key)
    if registry:
        logger.info(
            "loaded driver registry: %d drivers for session %s",
            len(registry), session_key,
        )

    # Construct the user message. Include session context so the model can
    # call tools without the user repeating the session_key each turn.
    user_text = text
    if session_key:
        ctx = f"[context] session_key={session_key}"
        if driver_number is not None:
            ctx += f", focused_driver_number={driver_number}"
            # Resolve the focused driver's acronym so the model knows who
            # the user is currently looking at without an extra tool call.
            drv = registry.get(int(driver_number)) if registry else None
            if drv and drv.get("name_acronym"):
                ctx += f", focused_driver_acronym={drv['name_acronym']}"
        user_text = f"{ctx}\n[user] {text}"

    user_msg = {"role": "user", "content": [{"text": user_text}]}
    history.append(user_msg)
    messages = list(history)  # snapshot for the loop

    message_id = f"m-{int(time.time() * 1000)}"
    try:
        stream_assistant(connection_id, message_id, messages, registry)
    except Exception:
        # On failure, pop the user message we just appended so a retry
        # doesn't carry a dangling turn.
        if history and history[-1] is user_msg:
            history.pop()
        raise

    # Signal completion so the client knows the stream is finished.
    post_to_connection(connection_id, {"type": "agent.done", "messageId": message_id})

    # Update stored history with the assistant turns + tool results from this
    # exchange. Cap per-connection memory.
    # `messages` now contains the full exchange; we replace history with it.
    _conversations[connection_id] = messages[-MAX_HISTORY_PER_CONN:]
    trim_history(connection_id)


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
