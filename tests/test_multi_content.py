"""Multi-content request bodies — JSON ↔ multipart auto-detect. Closes
the last documented Python gap in the migration guide.

Oracle: openai-python's `client.skills.create(files=…)` — single method,
runtime extracts file-like values from the body; if found → multipart;
else → JSON. The same `client.x.create(...)` call shape works for both
wire shapes, decided by the *arguments* the user passes.
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

FIX = Path(__file__).parent / "fixtures" / "multi_content"


@pytest.fixture(scope="module")
def mc(tmp_path_factory):
    out = tmp_path_factory.mktemp("mc")
    emit(build_ir(load_spec(str(FIX / "openapi.yml")),
                  load_config(str(FIX / "stainless.yml"))), str(out))
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules if m == "skills" or m.startswith("skills.")]:
        del sys.modules[m]
    return out, importlib.import_module("skills")


# ----- signature shape -------------------------------------------------------


def test_signature_includes_files_param(mc):
    """The single method exposes the union of JSON + multipart fields —
    here `files: List[FileTypes]` from the multipart schema."""
    out, _ = mc
    src = (out / "skills" / "resources" / "skills.py").read_text()
    assert "files: List[FileTypes]" in src
    # Non-file fields still present (JSON shape's fields are a subset
    # of multipart's in this fixture — both share `name`/`description`).
    assert "name: str" in src
    assert "description: str" in src
    # Dispatch: extract_files + conditional body
    assert "_extract_files(_body, paths=" in src
    assert "body=_body if _files else to_jsonable(_body)" in src
    assert "files=_files or None" in src


# ----- runtime: JSON path (no files) ----------------------------------------


def test_json_path_when_no_files(mc):
    """Caller didn't pass `files=` → SDK sends JSON. Wire request has
    Content-Type: application/json and a JSON body with the scalars."""
    _, s = mc
    seen = {}

    def h(req: httpx.Request) -> httpx.Response:
        seen["content_type"] = req.headers.get("content-type", "")
        seen["body"] = req.content
        return httpx.Response(200, json={"id": "sk_1", "name": "n"})

    c = s.Skills(
        api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(h))
    )
    resp = c.skills.create(files=[], name="my-skill", description="d")  # type: ignore[arg-type]
    assert resp.id == "sk_1"
    assert seen["content_type"].startswith("application/json")
    # Body is JSON (not multipart). `files` was filtered out because it
    # was empty → extract_files found nothing → JSON path.
    import json
    parsed = json.loads(seen["body"])
    assert parsed["name"] == "my-skill"
    assert parsed["description"] == "d"
    # No "files[]" in body (multipart path didn't trigger)
    assert "files" not in parsed or parsed["files"] == []


# ----- runtime: multipart path (with files) ---------------------------------


def test_multipart_path_when_files_present(mc):
    """Caller passes `files=[bytes]` → SDK sends multipart. Wire request
    has Content-Type: multipart/form-data and the bytes as one of the
    parts; non-file fields ride along as form data."""
    _, s = mc
    seen = {}

    def h(req: httpx.Request) -> httpx.Response:
        seen["content_type"] = req.headers.get("content-type", "")
        seen["body"] = req.content
        return httpx.Response(200, json={"id": "sk_2", "name": "n"})

    c = s.Skills(
        api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(h))
    )
    file_bytes = b"\x00\x01PNG-ish-bytes\xff"
    resp = c.skills.create(
        files=[file_bytes],
        name="my-skill-with-files",
        description="d",
    )
    assert resp.id == "sk_2"
    # Multipart wire shape
    assert seen["content_type"].startswith("multipart/form-data")
    # The bytes appear in the multipart body. (Don't parse multipart;
    # just sanity-check the file content is in there.)
    assert file_bytes in seen["body"]
    # Form-style scalars also appear in the multipart body.
    assert b"my-skill-with-files" in seen["body"]


def test_async_parity(mc):
    """Same auto-detect on AsyncSkills."""
    _, s = mc

    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "sk_3", "name": "n"})

    async def go(with_files: bool):
        ac = s.AsyncSkills(
            api_key="k",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(h)),
        )
        if with_files:
            return await ac.skills.create(files=[b"x"], name="a")
        return await ac.skills.create(files=[], name="a")  # type: ignore[arg-type]

    assert asyncio.run(go(True)).id == "sk_3"
    assert asyncio.run(go(False)).id == "sk_3"
