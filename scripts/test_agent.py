"""End-to-end test for the Phase 5 agent.

Connects to the live WebSocket API, opens a connection for the seeded
session 11315 (Austria 2026 race), sends an agent.ask, and prints every
agent.token / agent.done / agent.error event received.

Usage:
    source .venv/bin/activate
    python3 scripts/test_agent.py ["your question"]

Defaults to "Who is leading right now?" if no question supplied.
"""

import asyncio
import json
import os
import sys
import subprocess

import websockets


def get_ws_url():
    """Read the WS URL from terraform output."""
    r = subprocess.run(
        ["terraform", "output", "-raw", "websocket_url"],
        cwd=os.path.join(os.path.dirname(__file__), "..", "terraform", "environments", "dev"),
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout.strip()


async def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "Who is leading right now?"
    session_key = os.environ.get("SESSION_KEY", "11315")
    ws_base = get_ws_url()
    url = f"{ws_base}?sessionId={session_key}"
    print(f"=== connecting to {url} ===")
    print(f"=== session_key: {session_key} ===")
    print(f"=== question: {question!r}")
    print()

    async with websockets.connect(url, open_timeout=15) as ws:
        # Send the agent.ask action.
        await ws.send(json.dumps({
            "action": "agent.ask",
            "text": question,
            "sessionKey": session_key,
            "driverNumber": None,
        }))
        print("--- awaiting stream ---")

        received_text = []
        message_id = None
        try:
            # Loop until we see agent.done or agent.error (or 60s timeout).
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    print(f"  [bad json] {raw!r}")
                    continue

                t = msg.get("type")
                if t == "agent.token":
                    message_id = msg.get("messageId")
                    tok = msg.get("token", "")
                    received_text.append(tok)
                    print(tok, end="", flush=True)
                elif t == "agent.done":
                    print()
                    print(f"\n--- agent.done (messageId={msg.get('messageId')}) ---")
                    break
                elif t == "agent.error":
                    print()
                    print(f"\n--- agent.error: {msg.get('error')} ---")
                    break
                else:
                    # Could be a live telemetry tick if the poller is running.
                    print(f"\n  [ignoring {t}]")

        except asyncio.TimeoutError:
            print("\n[60s timeout]")
        except websockets.ConnectionClosed as e:
            print(f"\n[connection closed: {e}]")

    print()
    print("=== final assembled reply ===")
    print("".join(received_text))


if __name__ == "__main__":
    asyncio.run(main())
