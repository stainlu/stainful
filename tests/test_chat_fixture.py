"""Second fixture (task #10): proves the §4 capabilities OneBusAway cannot —
SSE streaming, oneOf+discriminator tagged unions, request bodies, nullable.

Without this, "green on OneBusAway" is necessary-but-not-sufficient for the
§4 quality-bar / "open-source Stainless" claim (advisor item 5).
"""

from __future__ import annotations

import asyncio
import importlib
import py_compile
import sys
from pathlib import Path

import httpx
import pytest

from stainful.config import load_config
from stainful.emit.python import emit
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

FIX = Path(__file__).parent / "fixtures" / "chat"


@pytest.fixture()
def chat_sdk(tmp_path, monkeypatch):
    api = build_ir(
        load_spec(str(FIX / "openapi.yml")),
        load_config(str(FIX / "stainless-config.yml")),
    )
    emit(api, str(tmp_path))
    monkeypatch.syspath_prepend(str(tmp_path))
    for m in list(sys.modules):
        if m == "chat" or m.startswith("chat."):
            del sys.modules[m]
    return tmp_path, importlib.import_module("chat")


def _completion(_req):
    return httpx.Response(
        200,
        json={"id": "c1", "choices": [
            {"index": 0,
             "message": {"role": "assistant", "content": "hi", "name": None}}]},
    )


def _sse(_req):
    return httpx.Response(
        200,
        content=b'data: {"id":"k","delta":"He"}\n\n'
                b'data: {"id":"k","delta":"llo"}\n\n'
                b"data: [DONE]\n\n",
    )


def test_all_files_compile(chat_sdk):
    out, _ = chat_sdk
    for f in out.rglob("*.py"):
        if "/_core/" not in str(f):
            py_compile.compile(str(f), doraise=True)


def test_subresource_path_and_request_body(chat_sdk):
    # client.chat.completions.create — nested subresource + JSON request body
    _, chat = chat_sdk
    sent = {}

    def h(req):
        sent["body"] = req.read()
        return _completion(req)

    c = chat.ChatSDK(api_key="sk",
                  http_client=httpx.Client(transport=httpx.MockTransport(h)))
    r = c.chat.completions.create(model="m", messages=[{"role": "user", "content": "hey"}])
    # Stainless path-naming: the response model is per-operation, not the
    # component name. chat.completions.create -> CompletionCreateResponse.
    assert type(r).__name__ == "CompletionCreateResponse"
    assert r.choices[0].message.content == "hi"
    assert r.choices[0].message.name is None  # nullable field present-but-null
    assert b'"model"' in sent["body"] and b'"messages"' in sent["body"]


def test_oneof_discriminator_is_a_real_tagged_union(chat_sdk):
    # RESEARCH §4 #8 — parsed into the right variant by the tag field.
    _, chat = chat_sdk
    from pydantic import TypeAdapter

    from chat.types import Event  # per-file layout; package re-exports

    err = TypeAdapter(Event).validate_python({"type": "error", "code": 7})
    msg = TypeAdapter(Event).validate_python({"type": "message", "text": "hi"})
    assert type(err).__name__ == "ErrorEvent" and err.code == 7
    assert type(msg).__name__ == "MessageEvent" and msg.text == "hi"


def test_sse_streaming_sync_and_async(chat_sdk):
    # RESEARCH §4 #6 — stream=True yields typed events, identical surface.
    _, chat = chat_sdk
    cs = chat.ChatSDK(api_key="sk",
                   http_client=httpx.Client(transport=httpx.MockTransport(_sse)))
    chunks = list(
        cs.chat.completions.create(
            model="m", messages=[{"role": "u", "content": "x"}], stream=True
        )
    )
    assert [c.delta for c in chunks] == ["He", "llo"]
    assert type(chunks[0]).__name__ == "CompletionCreateEvent"

    async def go():
        ac = chat.AsyncChatSDK(
            api_key="sk",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(_sse)),
        )
        s = await ac.chat.completions.create(
            model="m", messages=[{"role": "u", "content": "x"}], stream=True
        )
        return [c.delta async for c in s]

    assert asyncio.run(go()) == ["He", "llo"]


def test_streaming_overloads_present_in_source(chat_sdk):
    out, _ = chat_sdk
    # Nested layout: `chat` has a `completions` subresource, so chat is
    # a subpackage and completions sits at `resources/chat/completions.py`
    # (chat itself lives at `resources/chat/chat.py`).
    src = (out / "chat" / "resources" / "chat" / "completions.py").read_text()
    assert src.count("@overload") >= 2          # stream False/True overloads
    assert "Stream[CompletionCreateEvent]" in src  # typed event stream return
    assert 'Field(discriminator="type")' not in src  # union lives in types/
    # per-file layout: the discriminated union + its Literal-narrowed variants
    # live in the shared module (Event is $shared.models)
    types_src = "\n".join(
        p.read_text() for p in (out / "chat" / "types").glob("*.py")
    )
    assert 'Field(discriminator="type")' in types_src
    assert "Literal[" in types_src               # variant tag narrowed
