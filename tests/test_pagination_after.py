"""Pagination conformance — proves the cursor wire param + response field are
**config-driven**, not hard-coded. This is the openai/anthropic SyncCursorPage
shape (`?after=<last_id>`); the original `tests/test_pagination.py` covers the
legacy `?cursor=<next_cursor>` shape. Both must work over the same generic
runtime `_CursorPage`.
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

FIX = Path(__file__).parent / "fixtures" / "paginated_after"


@pytest.fixture(scope="module")
def pag(tmp_path_factory):
    out = tmp_path_factory.mktemp("pag_after")
    emit(build_ir(load_spec(str(FIX / "openapi.yml")),
                  load_config(str(FIX / "stainless.yml"))), str(out))
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules
              if m == "paginated_after" or m.startswith("paginated_after.")]:
        del sys.modules[m]
    return out, importlib.import_module("paginated_after")


def _two_page_handler():
    seen: list[dict] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        if "after" not in req.url.params:
            return httpx.Response(200, json={
                "data": [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}],
                "has_more": True, "last_id": "2"})
        return httpx.Response(200, json={
            "data": [{"id": "3", "name": "c"}],
            "has_more": False, "last_id": None})

    return h, seen


def test_emitter_passes_pagination_cfg(pag):
    """Generated resource carries the config-derived wire names."""
    out, _ = pag
    src = (out / "paginated_after" / "resources" / "things.py").read_text()
    assert '"cursor_param": "after"' in src
    assert '"cursor_response_field": "last_id"' in src


def test_sync_walks_all_pages_via_after(pag):
    _, p = pag
    h, seen = _two_page_handler()
    c = p.PaginatedAfterSDK(
        api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(h))
    )
    ids = [t.id for t in c.things.list()]
    assert ids == ["1", "2", "3"]                # transparently followed page 2
    assert len(seen) == 2
    # The wire param is `after`, sourced from response `last_id` — NOT the
    # literal "cursor" the old hard-code would have sent.
    assert seen[1].get("after") == "2"
    assert "cursor" not in seen[1]


def test_async_walks_all_pages_via_after(pag):
    _, p = pag
    h, _seen = _two_page_handler()

    async def go():
        ac = p.AsyncPaginatedAfterSDK(
            api_key="k",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(h)),
        )
        page = await ac.things.list()
        return [t.id async for t in page]

    assert asyncio.run(go()) == ["1", "2", "3"]
