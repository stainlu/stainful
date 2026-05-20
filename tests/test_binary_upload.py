"""Raw binary request bodies — `application/octet-stream` uploads (S3 PUT
object, GitHub release-asset upload). End-to-end on a generated SDK.

The previous emitter wrapped bytes in `_body = {"None": body}` and called
`to_jsonable` — broken codegen, latent (no fixture triggered it). This test
nails the path: a `bytes` body is sent verbatim with
`Content-Type: application/octet-stream`, sync + async.
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

FIX = Path(__file__).parent / "fixtures" / "upload_binary"
_PAYLOAD = b"\x00\x01PNG\xff\x00binary-bytes-not-json"


@pytest.fixture(scope="module")
def bu(tmp_path_factory):
    out = tmp_path_factory.mktemp("bu")
    emit(build_ir(load_spec(str(FIX / "openapi.yml")),
                  load_config(str(FIX / "stainless.yml"))), str(out))
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules
              if m == "binary_upload" or m.startswith("binary_upload.")]:
        del sys.modules[m]
    return out, importlib.import_module("binary_upload")


def test_all_files_compile(bu):
    import py_compile
    out, _ = bu
    for f in out.rglob("*.py"):
        if "/_core/" not in str(f):
            py_compile.compile(str(f), doraise=True)


def test_emitted_method_takes_bytes_and_passes_binary_flag(bu):
    out, _ = bu
    src = (out / "binary_upload" / "resources" / "objects.py").read_text()
    assert "body: bytes," in src                         # typed as bytes
    assert "body=body,\n            binary=True," in src # passed raw
    assert "to_jsonable(_body)" not in src               # never JSON-coerced
    assert '"None": body' not in src                     # latent flaw stays fixed


def test_wire_sends_raw_octet_stream_sync_and_async(bu):
    _, b = bu
    seen: list[tuple[bytes, str]] = []

    def h(req: httpx.Request) -> httpx.Response:
        # capture the wire body + content-type the runtime actually sent
        seen.append((req.content, req.headers.get("content-type", "")))
        return httpx.Response(200, json={"etag": "deadbeef"})

    c = b.BinaryUpload(
        api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(h))
    )
    resp = c.objects.put(bucket="bk", key="k1.png", body=_PAYLOAD)
    assert resp.etag == "deadbeef"

    async def go():
        ac = b.AsyncBinaryUpload(
            api_key="k",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(h)),
        )
        return await ac.objects.put(bucket="bk", key="k2.png", body=_PAYLOAD)

    aresp = asyncio.run(go())
    assert aresp.etag == "deadbeef"

    # both sync and async sent the bytes verbatim with octet-stream type
    assert len(seen) == 2
    for content, ctype in seen:
        assert content == _PAYLOAD                       # bytes-for-bytes
        assert ctype.startswith("application/octet-stream")
