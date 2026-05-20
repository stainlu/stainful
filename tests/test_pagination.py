"""Auto-pagination conformance (RESEARCH §4 #1) — end-to-end on a generated
SDK. OneBusAway is `paginated: false` everywhere, so this is the first fixture
that proves `for x in client.things.list(): ...` transparently walks EVERY
page (sync + async), over the vendored runtime. A real Stainless user with a
paginated API hits this immediately.
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

FIX = Path(__file__).parent / "fixtures" / "paginated"


@pytest.fixture(scope="module")
def pag(tmp_path_factory):
    out = tmp_path_factory.mktemp("pag")
    emit(build_ir(load_spec(str(FIX / "openapi.yml")),
                  load_config(str(FIX / "stainless.yml"))), str(out))
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules if m == "paginated" or m.startswith("paginated.")]:
        del sys.modules[m]
    return out, importlib.import_module("paginated")


def _two_page_handler():
    seen = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        if "cursor" not in req.url.params:
            return httpx.Response(200, json={
                "data": [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}],
                "has_more": True, "next_cursor": "c2"})
        return httpx.Response(200, json={
            "data": [{"id": "3", "name": "c"}],
            "has_more": False, "next_cursor": None})

    return h, seen


def test_all_files_compile(pag):
    import py_compile
    out, _ = pag
    for f in out.rglob("*.py"):
        if "/_core/" not in str(f):
            py_compile.compile(str(f), doraise=True)


def test_list_returns_a_page_type(pag):
    out, _ = pag
    src = (out / "paginated" / "resources" / "things.py").read_text()
    assert "_get_api_list(" in src
    assert "SyncCursorPage[" in src and "AsyncCursorPage[" in src
    # Absolute import (depth-agnostic) since resource files now live at
    # variable depths under resources/.
    assert "from paginated._core.pagination import" in src


def test_sync_auto_pagination_walks_all_pages(pag):
    _, p = pag
    h, seen = _two_page_handler()
    c = p.PaginatedSDK(
        api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(h))
    )
    ids = [t.id for t in c.things.list()]
    assert ids == ["1", "2", "3"]                 # transparently followed page 2
    assert len(seen) == 2
    assert seen[1].get("cursor") == "c2"          # next-page cursor was sent


def test_async_auto_pagination_walks_all_pages(pag):
    _, p = pag
    h, _seen = _two_page_handler()

    async def go():
        ac = p.AsyncPaginatedSDK(
            api_key="k",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(h)),
        )
        page = await ac.things.list()
        return [t.id async for t in page]

    assert asyncio.run(go()) == ["1", "2", "3"]
