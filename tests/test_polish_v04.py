"""Small v0.4 polish items: Stainless drop-in conveniences that were on
the v1.1 backlog. Each is small but earns a real adoption win.

  - `.to_json()` / `.to_dict()` aliases on every generated BaseModel
    (route to pydantic v2's `model_dump_json` / `model_dump` with
    `by_alias=True, exclude_unset=True` — the Stainless default)
  - Webhook unwrap / verify_signature: env-var fallback for `secret=`
    (matches openai-python's `OPENAI_WEBHOOK_SECRET`)
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

FIXTURES = Path(__file__).parent / "fixtures"


# ---------- to_json / to_dict aliases ----------------------------------------


def test_to_json_and_to_dict_aliases_present_on_generated_models(tmp_path):
    api = build_ir(
        load_spec(str(FIXTURES / "chat" / "openapi.yml")),
        load_config(str(FIXTURES / "chat" / "stainless-config.yml")),
    )
    emit(api, str(tmp_path))
    sys.path.insert(0, str(tmp_path))
    for m in [m for m in sys.modules if m == "chat" or m.startswith("chat.")]:
        del sys.modules[m]
    chat = importlib.import_module("chat")

    # The generated BaseModel inherits from the runtime's BaseModel, which
    # provides to_json/to_dict aliases (drop-in for Stainless). The chat
    # response model is per-op-named — `CompletionCreateResponse`.
    resp = chat.types.CompletionCreateResponse(
        id="c1",
        choices=[{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
    )
    d = resp.to_dict()
    assert d["id"] == "c1"
    assert d["choices"][0]["message"]["content"] == "hi"
    j = resp.to_json()
    assert isinstance(j, str)
    assert json.loads(j)["id"] == "c1"


def test_to_dict_uses_wire_aliases_by_default(tmp_path):
    """When a field is renamed via `Field(alias=...)` (e.g. `from_` →
    `"from"`), `.to_dict()` emits the WIRE key by default (Stainless's
    `by_alias=True` default) — that's what users expect when re-sending."""
    # Use a fixture that doesn't have an alias collision is hard; instead,
    # construct directly to assert pydantic v2's by_alias semantics on the
    # runtime BaseModel.
    from stainful.runtime._models import BaseModel
    from pydantic import Field

    class M(BaseModel):
        from_: str = Field(alias="from")
        body: str

    m = M(**{"from": "x", "body": "y"})
    # WIRE key, not python name
    assert m.to_dict() == {"from": "x", "body": "y"}
    assert m.to_json() == '{"from":"x","body":"y"}'


# ---------- webhook secret env-var fallback ----------------------------------


def _sign(payload: str, *, secret: str, webhook_id: str = "wh_1") -> dict:
    ts = str(int(time.time()))
    signed = f"{webhook_id}.{ts}.{payload}"
    sig = base64.b64encode(
        hmac.new(secret.encode(), signed.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": ts,
        "webhook-signature": f"v1,{sig}",
    }


def test_webhook_secret_falls_back_to_env_var(tmp_path, monkeypatch):
    """`client.webhooks.unwrap(payload, headers)` (no secret kwarg) reads
    `<BRAND_UPPER>_WEBHOOK_SECRET` from the env. The brand for the
    `hooks` fixture is `Hooks` → env var `HOOKS_WEBHOOK_SECRET`."""
    api = build_ir(
        load_spec(str(FIXTURES / "webhooks" / "openapi.yml")),
        load_config(str(FIXTURES / "webhooks" / "stainless.yml")),
    )
    emit(api, str(tmp_path))
    sys.path.insert(0, str(tmp_path))
    for m in [m for m in sys.modules if m == "hooks" or m.startswith("hooks.")]:
        del sys.modules[m]
    hooks = importlib.import_module("hooks")

    body = json.dumps({"type": "order.created", "id": "x", "order_id": "y"})
    headers = _sign(body, secret="env-secret")

    client = hooks.Hooks(api_key="k")

    # No env var, no secret kwarg → ValueError (no fallback path).
    monkeypatch.delenv("HOOKS_WEBHOOK_SECRET", raising=False)
    with pytest.raises(ValueError, match="HOOKS_WEBHOOK_SECRET"):
        client.webhooks.unwrap(body, headers)

    # Env var set → unwrap succeeds.
    monkeypatch.setenv("HOOKS_WEBHOOK_SECRET", "env-secret")
    evt = client.webhooks.unwrap(body, headers)
    assert evt.id == "x"

    # Explicit `secret=` still overrides the env var (per openai-python).
    other_headers = _sign(body, secret="explicit-secret")
    evt2 = client.webhooks.unwrap(body, other_headers, secret="explicit-secret")
    assert evt2.id == "x"


def test_verify_signature_also_falls_back_to_env_var(tmp_path, monkeypatch):
    api = build_ir(
        load_spec(str(FIXTURES / "webhooks" / "openapi.yml")),
        load_config(str(FIXTURES / "webhooks" / "stainless.yml")),
    )
    emit(api, str(tmp_path))
    sys.path.insert(0, str(tmp_path))
    for m in [m for m in sys.modules if m == "hooks" or m.startswith("hooks.")]:
        del sys.modules[m]
    hooks = importlib.import_module("hooks")

    body = json.dumps({"type": "order.created", "id": "x", "order_id": "y"})
    headers = _sign(body, secret="env-secret")

    client = hooks.Hooks(api_key="k")
    monkeypatch.setenv("HOOKS_WEBHOOK_SECRET", "env-secret")
    # No raise = signature verified using the env-var secret.
    assert client.webhooks.verify_signature(body, headers) is None
