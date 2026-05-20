"""Rich `APIResponse` via `with_raw_response.*` — end-to-end on a
generated SDK. Was a v1.1 backlog item; v0.4 ships the real thing.

Oracle: openai-python's `APIResponse[T]` (`.http_response`, `.headers`,
`.status_code`, `.request_id`, `.parse()`). We don't replicate the
full surface (no `.read()` / `.iter_bytes()` — those are stream-side),
but enough for real users to grab headers/status/request_id and the
typed model from the same call.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import httpx
import pytest

from stainful.config import load_config
from stainful.emit.python import emit
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

FIX = Path(__file__).parent / "fixtures" / "chat"


@pytest.fixture(scope="module")
def chat(tmp_path_factory):
    out = tmp_path_factory.mktemp("apiresp")
    emit(build_ir(load_spec(str(FIX / "openapi.yml")),
                  load_config(str(FIX / "stainless-config.yml"))), str(out))
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules if m == "chat" or m.startswith("chat.")]:
        del sys.modules[m]
    return out, importlib.import_module("chat")


def test_brand_aliases_apiresponse_at_package_root(chat):
    """Drop-in: `from chat import ChatSDKAPIResponse` resolves to the
    same generic class as `from chat import APIResponse` (matches
    openai-python's `OpenAIAPIResponse` convention)."""
    _, c = chat
    assert hasattr(c, "APIResponse")
    assert hasattr(c, "ChatSDKAPIResponse")          # brand is `ChatSDK` here
    assert c.APIResponse is c.ChatSDKAPIResponse


def test_with_raw_response_returns_rich_wrapper(chat):
    _, c = chat
    body_seen: list = []

    def h(req: httpx.Request) -> httpx.Response:
        body_seen.append(req.content)
        return httpx.Response(
            201,
            json={"id": "cmp_1", "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}]},
            headers={"x-request-id": "req-abc", "x-extra": "y"},
        )

    client = c.ChatSDK(
        api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(h))
    )
    # Regular call: typed model directly
    plain = client.chat.completions.create(
        model="m", messages=[{"role": "user", "content": "hi"}]
    )
    assert plain.id == "cmp_1"

    # `with_raw_response`: same call, rich APIResponse wrapping the same model
    wrapped = client.chat.completions.with_raw_response.create(
        model="m", messages=[{"role": "user", "content": "hi"}]
    )
    assert isinstance(wrapped, c.APIResponse)
    assert wrapped.status_code == 201
    assert wrapped.headers["x-request-id"] == "req-abc"
    assert wrapped.headers["x-extra"] == "y"
    assert wrapped.request_id == "req-abc"
    parsed = wrapped.parse()
    assert parsed.id == "cmp_1"
    # `.parse()` returns the SAME typed instance — no re-parse.
    assert wrapped.parse() is parsed


def test_async_with_raw_response_returns_rich_wrapper(chat):
    _, c = chat

    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": "cmp_2", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}]},
            headers={"x-request-id": "req-xyz"},
        )

    async def go():
        client = c.AsyncChatSDK(
            api_key="k",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(h)),
        )
        return await client.chat.completions.with_raw_response.create(
            model="m", messages=[{"role": "user", "content": "hi"}]
        )

    wrapped = asyncio.run(go())
    assert isinstance(wrapped, c.APIResponse)
    assert wrapped.status_code == 200
    assert wrapped.request_id == "req-xyz"
    assert wrapped.parse().id == "cmp_2"


def test_context_does_not_leak_to_next_call(chat):
    """The wrap-raw context-var must be reset in finally so the next
    plain call returns the unwrapped model, not APIResponse."""
    _, c = chat

    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": "x", "choices": [{"index": 0, "message": {"role": "assistant", "content": "y"}}]},
            headers={"x-request-id": "rid"},
        )

    client = c.ChatSDK(
        api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(h))
    )
    raw = client.chat.completions.with_raw_response.create(
        model="m", messages=[{"role": "user", "content": "."}]
    )
    assert isinstance(raw, c.APIResponse)
    # Right after a with_raw_response call, a plain call must NOT be wrapped.
    plain = client.chat.completions.create(
        model="m", messages=[{"role": "user", "content": "."}]
    )
    assert not isinstance(plain, c.APIResponse)
    assert plain.id == "x"
