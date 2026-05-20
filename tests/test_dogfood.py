"""Dogfood guard: the SDK committed at examples/onebusaway/sdk MUST be
exactly what `stainful generate` produces from the committed
examples/onebusaway/{openapi.yml,stainless.yml}.

This makes the repo dogfood itself — the demo command is real, the
committed example can't silently drift, and "regenerate" is enforced in CI
(change the emitter/runtime ⇒ you must regenerate & commit the example).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stainful.config import load_config
from stainful.emit.mcp import emit_mcp
from stainful.emit.python import emit
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

EXAMPLE = Path(__file__).parent.parent / "examples" / "onebusaway"
COMMITTED = EXAMPLE / "sdk"

_REGEN = (
    "uv run stainful generate --spec examples/onebusaway/openapi.yml "
    "--config examples/onebusaway/stainless.yml --out examples/onebusaway/sdk "
    "&& uv run stainful mcp --spec examples/onebusaway/openapi.yml "
    "--config examples/onebusaway/stainless.yml "
    "--out examples/onebusaway/sdk/onebusaway/mcp_server.py"
)


def _tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text()
        for p in sorted(root.rglob("*.py"))
        if "__pycache__" not in p.parts
    }


def test_committed_example_sdk_is_in_sync(tmp_path):
    if not COMMITTED.exists():
        pytest.skip(f"no committed example SDK — run: {_REGEN}")
    api = build_ir(
        load_spec(str(EXAMPLE / "openapi.yml")),
        load_config(str(EXAMPLE / "stainless.yml")),
    )
    emit(api, str(tmp_path))
    # MCP server is treated as part of the dogfood artifact (separate
    # subcommand, but bit-stability matters here too — if the emitter
    # touches the MCP template, CI should fail until the example is
    # regenerated).
    emit_mcp(api, str(tmp_path / "onebusaway" / "mcp_server.py"))

    fresh = _tree(tmp_path / "onebusaway")
    committed = _tree(COMMITTED / "onebusaway")

    added = sorted(set(fresh) - set(committed))
    removed = sorted(set(committed) - set(fresh))
    changed = sorted(
        f for f in (set(fresh) & set(committed)) if fresh[f] != committed[f]
    )
    assert not (added or removed or changed), (
        "examples/onebusaway/sdk is out of sync with `stainful generate`.\n"
        f"Regenerate & commit:\n  {_REGEN}\n"
        f"added={added}\nremoved={removed}\nchanged={changed}"
    )
