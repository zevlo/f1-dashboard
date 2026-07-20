"""Local tests for the ws-agent Lambda stub.

Doesn't exercise the Bedrock path (Phase 5). Validates:
  - Event parsing
  - Missing-text error path
  - Stub reply sends the expected {token, token, ..., done} sequence

Run:
    python3 lambdas/ws-agent/test_handler.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lambda_function as lf  # noqa: E402


def make_event(text=None, session_key="123", driver_number=1):
    body = {"action": "agent.ask"}
    if text is not None:
        body["text"] = text
    if session_key is not None:
        body["sessionKey"] = session_key
    if driver_number is not None:
        body["driverNumber"] = driver_number
    return {
        "requestContext": {"connectionId": "c1"},
        "body": json.dumps(body),
    }


def capture_posts():
    sent = []

    def fake(connection_id, payload):
        sent.append((connection_id, payload))
    lf.post_to_connection = fake
    return sent


def test_missing_text_sends_error():
    lf.AGENT_ENABLED = False
    sent = capture_posts()
    r = lf.lambda_handler(make_event(text=None), None)
    assert r["statusCode"] == 200
    assert len(sent) == 1
    assert sent[0][1]["type"] == "agent.error"
    print("  missing_text_sends_error OK")


def test_no_connection_id():
    lf.AGENT_ENABLED = False
    r = lf.lambda_handler({"requestContext": {}, "body": "{}"}, None)
    assert r["statusCode"] == 400
    print("  no_connection_id OK")


def test_stub_streams_tokens_then_done():
    lf.AGENT_ENABLED = False
    sent = capture_posts()
    r = lf.lambda_handler(make_event(text="why is VER slow?"), None)
    assert r["statusCode"] == 200
    # Expect: multiple agent.token events followed by exactly one agent.done.
    types = [s[1]["type"] for s in sent]
    assert types[-1] == "agent.done"
    assert all(t == "agent.token" for t in types[:-1])
    assert len(types) >= 2  # at least one token + done
    # messageId consistent across tokens + done
    msg_ids = {s[1]["messageId"] for s in sent}
    assert len(msg_ids) == 1
    # Reconstructed text matches STUB_REPLY
    streamed = "".join(s[1]["token"] for s in sent if s[1]["type"] == "agent.token")
    assert streamed == lf.STUB_REPLY
    print("  stub_streams_tokens_then_done OK")


def test_bedrock_path_raises_when_not_implemented():
    lf.AGENT_ENABLED = True
    sent = capture_posts()
    r = lf.lambda_handler(make_event(text="hello"), None)
    # The NotImplementedError is caught + sent as agent.error
    assert r["statusCode"] == 500
    assert sent[0][1]["type"] == "agent.error"
    lf.AGENT_ENABLED = False  # reset
    print("  bedrock_path_raises_when_not_implemented OK")


def test_parse_event_handles_bad_json():
    cid, body = lf.parse_event({
        "requestContext": {"connectionId": "c1"},
        "body": "not json",
    })
    assert cid == "c1"
    assert body == {}
    print("  parse_event_handles_bad_json OK")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll ws-agent tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
