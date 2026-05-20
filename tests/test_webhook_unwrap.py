"""Webhook unwrap — full version with **typed discriminated event union**.
End-to-end on a generated SDK.

Algorithm = Standard Webhooks (https://www.standardwebhooks.com/), pinned
by the openai-python oracle (`resources/webhooks/webhooks.py`):

  • Headers:   webhook-signature, webhook-timestamp, webhook-id
  • Signed:    f"{webhook_id}.{timestamp}.{body}"
  • Signature: HMAC-SHA256, base64-encoded, `v1,<sig>` (multi-value)
  • Secret:    if `whsec_*` → base64-decode the remainder, else raw bytes
  • Replay:    timestamp must be within ±tolerance (default 300s)

The fixture's `event_types:` resolves into a `WebhookUnwrapEvent` discriminated
union (pydantic, discriminator=`type`) — `unwrap(...)` returns the **right
typed variant**, not just a parsed dict. Bad signature → InvalidWebhookSignatureError;
stale timestamp → InvalidWebhookSignatureError; missing header → same.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import sys
import time
from pathlib import Path

import pytest

from stainful.config import load_config
from stainful.emit.python import emit
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

FIX = Path(__file__).parent / "fixtures" / "webhooks"
SECRET = "topsecret"
WEBHOOK_ID = "msg_2qX3rRtest"


@pytest.fixture(scope="module")
def wh(tmp_path_factory):
    out = tmp_path_factory.mktemp("wh")
    emit(build_ir(load_spec(str(FIX / "openapi.yml")),
                  load_config(str(FIX / "stainless.yml"))), str(out))
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules if m == "hooks" or m.startswith("hooks.")]:
        del sys.modules[m]
    return out, importlib.import_module("hooks")


def _sign(payload: str, *, secret: str = SECRET, timestamp: int | None = None,
          webhook_id: str = WEBHOOK_ID) -> tuple[dict, str]:
    """Return (headers, payload) signed per Standard Webhooks."""
    ts = str(timestamp if timestamp is not None else int(time.time()))
    signed = f"{webhook_id}.{ts}.{payload}"
    secret_bytes = (
        base64.b64decode(secret[6:]) if secret.startswith("whsec_")
        else secret.encode()
    )
    sig = base64.b64encode(
        hmac.new(secret_bytes, signed.encode(), hashlib.sha256).digest()
    ).decode()
    headers = {
        "webhook-id": webhook_id,
        "webhook-timestamp": ts,
        "webhook-signature": f"v1,{sig}",
    }
    return headers, payload


def test_all_files_compile(wh):
    import py_compile
    out, _ = wh
    for f in out.rglob("*.py"):
        if "/_core/" not in str(f):
            py_compile.compile(str(f), doraise=True)


def test_typed_event_union_is_emitted(wh):
    out, _ = wh
    src = (out / "hooks" / "types" / "webhooks_unwrap_event.py").read_text()
    assert "WebhookUnwrapEvent = Annotated[" in src
    assert "OrderCreatedEvent" in src and "OrderCancelledEvent" in src
    assert 'PropertyInfo(discriminator="type")' in src


def test_unwrap_returns_typed_event_variant(wh):
    _, h = wh
    body = json.dumps({"type": "order.created", "id": "evt_1", "order_id": "o_42"})
    headers, payload = _sign(body)
    client = h.Hooks(api_key="k")
    evt = client.webhooks.unwrap(payload, headers, secret=SECRET)
    # Discriminated union → the right concrete pydantic model class.
    from hooks.types.shared import OrderCancelledEvent, OrderCreatedEvent
    assert isinstance(evt, OrderCreatedEvent)
    assert not isinstance(evt, OrderCancelledEvent)
    assert evt.id == "evt_1" and evt.order_id == "o_42"


def test_unwrap_discriminates_second_variant(wh):
    _, h = wh
    body = json.dumps({"type": "order.cancelled", "id": "evt_9",
                       "order_id": "o_99"})
    headers, payload = _sign(body)
    client = h.Hooks(api_key="k")
    evt = client.webhooks.unwrap(payload, headers, secret=SECRET)
    from hooks.types.shared import OrderCancelledEvent
    assert isinstance(evt, OrderCancelledEvent)
    assert evt.order_id == "o_99"


def test_bad_signature_raises(wh):
    _, h = wh
    body = json.dumps({"type": "order.created", "id": "x", "order_id": "y"})
    headers, payload = _sign(body, secret="WRONG-SECRET")
    client = h.Hooks(api_key="k")
    with pytest.raises(h.InvalidWebhookSignatureError):
        client.webhooks.unwrap(payload, headers, secret=SECRET)


def test_stale_timestamp_raises(wh):
    _, h = wh
    body = json.dumps({"type": "order.created", "id": "x", "order_id": "y"})
    # 1 hour in the past — well outside the default 300s tolerance.
    headers, payload = _sign(body, timestamp=int(time.time()) - 3600)
    client = h.Hooks(api_key="k")
    with pytest.raises(h.InvalidWebhookSignatureError):
        client.webhooks.unwrap(payload, headers, secret=SECRET)


def test_missing_header_raises(wh):
    _, h = wh
    body = json.dumps({"type": "order.created", "id": "x", "order_id": "y"})
    headers, payload = _sign(body)
    headers.pop("webhook-signature")
    client = h.Hooks(api_key="k")
    with pytest.raises(h.InvalidWebhookSignatureError):
        client.webhooks.unwrap(payload, headers, secret=SECRET)


def test_whsec_prefixed_secret_is_decoded(wh):
    """A `whsec_<base64>` secret must be base64-decoded before HMAC (oracle:
    openai-python's `_decode_secret`). Without this, a signature signed with
    the decoded bytes wouldn't validate."""
    _, h = wh
    raw_secret_bytes = b"\x01\x02secret-bytes\xff"
    whsec = "whsec_" + base64.b64encode(raw_secret_bytes).decode()
    body = json.dumps({"type": "order.created", "id": "x", "order_id": "y"})
    headers, payload = _sign(body, secret=whsec)
    client = h.Hooks(api_key="k")
    evt = client.webhooks.unwrap(payload, headers, secret=whsec)
    assert evt.id == "x"


def test_verify_signature_no_event_parse(wh):
    _, h = wh
    body = json.dumps({"type": "order.created", "id": "x", "order_id": "y"})
    headers, payload = _sign(body)
    client = h.Hooks(api_key="k")
    # Should not raise; returns None.
    assert client.webhooks.verify_signature(payload, headers, secret=SECRET) is None


def test_invalid_webhook_signature_error_is_exported_at_root(wh):
    """Drop-in symbol contract: `from <pkg> import InvalidWebhookSignatureError`
    must work — matches openai-python's exception export."""
    _, h = wh
    assert hasattr(h, "InvalidWebhookSignatureError")
    assert issubclass(h.InvalidWebhookSignatureError, Exception)
