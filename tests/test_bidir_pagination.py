"""Bi-directional pagination — anthropic-shape (`before_id`/`after_id`).
Oracle: `tests/oracles/anthropic-sdk-python/.../pagination.py::SyncPage`.
Closes the last documented pagination gap in the migration guide.

Algorithm: the *initial* request's params decide direction. If the
caller set `before_id`, we're walking backwards → next page sends
`before_id=<first_id>`. Otherwise we walk forwards → `after_id=<last_id>`.
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

FIX = Path(__file__).parent / "fixtures" / "bidir_pagination"


@pytest.fixture(scope="module")
def bidir(tmp_path_factory):
    out = tmp_path_factory.mktemp("bidir")
    emit(build_ir(load_spec(str(FIX / "openapi.yml")),
                  load_config(str(FIX / "stainless.yml"))), str(out))
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules if m == "anth" or m.startswith("anth.")]:
        del sys.modules[m]
    return out, importlib.import_module("anth")


def test_resource_uses_bidirectional_page_class(bidir):
    out, _ = bidir
    src = (out / "anth" / "resources" / "things.py").read_text()
    # Stainless config named it `page` → SyncPage / AsyncPage aliases
    assert "SyncPage[" in src and "AsyncPage[" in src
    # pagination_cfg threaded the bi-direction wire names
    assert '"before_param": "before_id"' in src
    assert '"after_param": "after_id"' in src
    assert '"first_field": "first_id"' in src
    assert '"last_field": "last_id"' in src


def test_aliases_route_to_bidirectional_runtime(bidir):
    out, anth = bidir
    pag = importlib.import_module("anth._core.pagination")
    assert pag.SyncPage is pag.SyncBiDirectionalPage
    assert pag.AsyncPage is pag.AsyncBiDirectionalPage
    # They're distinct from the forward-only cursor class
    assert pag.SyncCursorPage is not pag.SyncBiDirectionalPage


def _two_page_handler(direction: str):
    """Mock server: returns two pages. `direction` selects which side
    of the bi-directional walk we expect — `seen` records the wire
    params actually received."""
    assert direction in ("forward", "backward")
    seen: list[dict] = []
    call_count = [0]                       # mutable closure counter

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        call_count[0] += 1
        if direction == "forward":
            if call_count[0] == 1:
                return httpx.Response(200, json={
                    "data": [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}],
                    "has_more": True, "first_id": "1", "last_id": "2",
                })
            return httpx.Response(200, json={
                "data": [{"id": "3", "name": "c"}],
                "has_more": False, "first_id": "3", "last_id": "3",
            })
        # backward — user originally set before_id; runtime sends
        # before_id=<first_id> on subsequent calls.
        if call_count[0] == 1:
            return httpx.Response(200, json={
                "data": [{"id": "3", "name": "c"}],
                "has_more": True, "first_id": "3", "last_id": "3",
            })
        return httpx.Response(200, json={
            "data": [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}],
            "has_more": False, "first_id": "1", "last_id": "2",
        })

    return h, seen


def test_forward_direction_uses_after_id(bidir):
    _, anth = bidir
    h, seen = _two_page_handler("forward")
    c = anth.Anth(
        api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(h))
    )
    ids = [t.id for t in c.things.list()]
    assert ids == ["1", "2", "3"]
    # Forward direction: next-page request carried `after_id=<last_id>`.
    assert len(seen) == 2
    assert seen[1].get("after_id") == "2"
    assert "before_id" not in seen[1]


def test_backward_direction_uses_before_id(bidir):
    """If the caller starts with `before_id=...`, subsequent pages use
    `before_id=<first_id>` — the bi-directional logic kicks in."""
    _, anth = bidir
    h, seen = _two_page_handler("backward")
    c = anth.Anth(
        api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(h))
    )
    ids = [t.id for t in c.things.list(before_id="seed")]
    assert ids == ["3", "1", "2"]   # one page of 1, then two more
    assert len(seen) == 2
    # Backward: next-page request carried before_id=<first_id>=3
    assert seen[1].get("before_id") == "3"
    assert "after_id" not in seen[1]


def test_async_bidirectional_walk(bidir):
    _, anth = bidir
    h, _ = _two_page_handler("forward")

    async def go():
        ac = anth.AsyncAnth(
            api_key="k",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(h)),
        )
        page = await ac.things.list()
        return [t.id async for t in page]

    assert asyncio.run(go()) == ["1", "2", "3"]
