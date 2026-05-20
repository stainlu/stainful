"""`stainful docs` — emits an `api.md` from the same spec + config as
`stainful generate`. Format matches Stainless's `api.md` convention
(oracle: `tests/oracles/openai-python/api.md`): per-resource sections,
Methods lists with `<code title="<verb> <path>">client.<chain>.<a
href=...>method</a>(...) -> <ReturnLink></code>`. Mintlify-compatible
by virtue of being valid Markdown + inline HTML.

This is the docs leg of the v0.4 announcement story: SDK + docs from one
spec.
"""

from __future__ import annotations

from pathlib import Path


from stainful.config import load_config
from stainful.emit.markdown import emit_docs
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).parent.parent / "examples"


def _render(spec: Path, config: Path, tmp_path: Path) -> str:
    api = build_ir(load_spec(str(spec)), load_config(str(config)))
    out = tmp_path / "api.md"
    emit_docs(api, str(out))
    return out.read_text()


def test_onebusaway_docs_shape(tmp_path):
    md = _render(
        EXAMPLES / "onebusaway" / "openapi.yml",
        EXAMPLES / "onebusaway" / "stainless.yml",
        tmp_path,
    )
    # Header + shared types
    assert md.startswith("# onebusaway\n")
    assert "# Shared Types" in md
    # Per-resource section
    assert "# Agency" in md
    # Stainless-style method line: `<code title="<verb> <path>">…</code>`
    assert '<code title="get /api/where/agency/' in md
    assert "client.agency.<a " in md
    assert ">retrieve</a>" in md
    # Inline ObjectType responses use the path-named class
    assert "AgencyRetrieveResponse" in md


def test_openai_docs_resolves_pagination_item(tmp_path):
    """Real spec — paginated list returns should show the *item* type,
    not `SyncCursorPage[object]`. Resolves ModelRef → ObjectType to
    find the `data: List[T]` element."""
    md = _render(
        EXAMPLES / "openai" / "openapi.yml",
        EXAMPLES / "openai" / "stainless.yml",
        tmp_path,
    )
    assert "SyncCursorPage[FineTuningJob]" in md
    assert "SyncCursorPage[OpenAIFile]" in md
    assert "SyncCursorPage[Batch]" in md
    # nested resource heading depth
    assert "## Completions" in md
    assert "### Messages" in md


def test_streaming_overload_response_does_not_break_doc(tmp_path):
    """A streaming method (chat.completions.create) has a JSON variant
    response — the docs link should show the JSON return type, NOT the
    SSE event type."""
    md = _render(
        EXAMPLES / "openai" / "openapi.yml",
        EXAMPLES / "openai" / "stainless.yml",
        tmp_path,
    )
    # The line for chat.completions.create
    line = next(
        line for line in md.splitlines()
        if 'title="post /chat/completions"' in line and ">create</a>" in line
    )
    assert "CreateChatCompletionResponse" in line


def test_webhook_unwrap_has_no_verb_path(tmp_path):
    """A `type: webhook_unwrap` method has no HTTP endpoint — its docs
    line should NOT render `<code title="<verb> <path>">`."""
    md = _render(
        FIXTURES / "webhooks" / "openapi.yml",
        FIXTURES / "webhooks" / "stainless.yml",
        tmp_path,
    )
    assert "# Webhooks" in md
    # No `<code title="..."` for unwrap; just plain `client.webhooks.unwrap(...)`
    lines = [line for line in md.splitlines() if "unwrap" in line]
    assert any("client.webhooks.unwrap" in line for line in lines)
    assert not any('title="post ' in line for line in lines)


def test_cli_smoke(tmp_path, monkeypatch):
    """`stainful docs --spec ... --config ... --out api.md` end-to-end."""
    from stainful.cli import main
    out = tmp_path / "api.md"
    rc = main([
        "docs",
        "--spec", str(EXAMPLES / "onebusaway" / "openapi.yml"),
        "--config", str(EXAMPLES / "onebusaway" / "stainless.yml"),
        "--out", str(out),
    ])
    assert rc == 0
    md = out.read_text()
    assert md.startswith("# onebusaway")
    assert "# Agency" in md
