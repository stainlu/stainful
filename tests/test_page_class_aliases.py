"""Spec-specific page class names — `SyncNextCursorPage`,
`SyncTokenPage`, `SyncPageCursor`, etc. Stainless emits distinct
symbols per pagination shape. All five forward-only cursor variants
across openai+anthropic share the same algorithm; we alias them all
to the same generic class so imports of any specific name resolve.

Closes the "alternate cursor page class names" gap in the migration
guide. The class-name convention comes from `pagination[].name` in
stainless.yml: snake-case → `Sync<Pascal>Page` (suffix-deduped if
the name already ends in `_page`).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from stainful.config import load_config
from stainful.emit.python import emit
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec


def _gen(spec: Path, config: Path, tmp_path: Path):
    api = build_ir(load_spec(str(spec)), load_config(str(config)))
    emit(api, str(tmp_path))
    return tmp_path


def _write_fixture(tmp_path: Path, *, pagination_name: str,
                   request_param: str, response_field: str) -> Path:
    """Write a tiny paginated fixture parameterized over the page name."""
    fix = tmp_path / "in"
    fix.mkdir()
    (fix / "openapi.yml").write_text(f"""\
openapi: 3.0.0
info: {{ title: Tk, version: 1.0.0 }}
servers: [{{ url: https://api.tk.test }}]
paths:
  /widgets:
    get:
      operationId: listWidgets
      parameters:
        - {{ name: {request_param}, in: query, schema: {{ type: string }} }}
        - {{ name: limit, in: query, schema: {{ type: integer }} }}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                required: [data]
                properties:
                  data: {{ type: array, items: {{ type: object }} }}
                  {response_field}: {{ type: string, nullable: true }}
                  has_more: {{ type: boolean }}
components: {{ schemas: {{}} }}
""")
    (fix / "stainless.yml").write_text(f"""\
organization: {{ name: tk }}
resources:
  widgets:
    methods:
      list: {{ endpoint: "get /widgets", paginated: true }}
pagination:
  - name: {pagination_name}
    type: cursor
    request:
      {request_param}: {{ type: string }}
      limit: {{ type: integer }}
    response:
      data: {{ type: array }}
      has_more: {{ type: boolean }}
      {response_field}: {{ type: string, nullable: true }}
targets: {{ python: {{ package_name: tk }} }}
environments: {{ production: https://api.tk.test }}
""")
    return fix


def test_token_page_alias_resolves(tmp_path):
    """`pagination.name: token_page` (anthropic shape) →
    `SyncTokenPage` / `AsyncTokenPage` aliases."""
    fix = _write_fixture(
        tmp_path, pagination_name="token_page",
        request_param="page_token", response_field="next_page",
    )
    out = tmp_path / "out"
    _gen(fix / "openapi.yml", fix / "stainless.yml", out)

    # Resource file uses the named class
    src = (out / "tk" / "resources" / "widgets.py").read_text()
    assert "SyncTokenPage[" in src
    assert "AsyncTokenPage[" in src

    # Runtime exposes both names (aliased to the generic class)
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules if m == "tk" or m.startswith("tk.")]:
        del sys.modules[m]
    pag = importlib.import_module("tk._core.pagination")
    assert pag.SyncTokenPage is pag.SyncCursorPage
    assert pag.AsyncTokenPage is pag.AsyncCursorPage


def test_next_cursor_page_alias_resolves(tmp_path):
    """openai's `next_cursor_page` shape — name ending in `_page` is
    suffix-deduped so we don't get `SyncNextCursorPagePage`."""
    fix = _write_fixture(
        tmp_path, pagination_name="next_cursor_page",
        request_param="after", response_field="next",
    )
    out = tmp_path / "out"
    _gen(fix / "openapi.yml", fix / "stainless.yml", out)
    src = (out / "tk" / "resources" / "widgets.py").read_text()
    assert "SyncNextCursorPage[" in src
    assert "SyncNextCursorPagePage" not in src    # suffix-dedup
    pag_path = out / "tk" / "_core" / "pagination.py"
    pag_src = pag_path.read_text()
    assert "SyncNextCursorPage = SyncCursorPage" in pag_src
    assert "AsyncNextCursorPage = AsyncCursorPage" in pag_src


def test_default_cursor_page_still_works(tmp_path):
    """The original `name: cursor_page` (in `tests/fixtures/paginated/`)
    still resolves to the runtime's built-in `SyncCursorPage` (no alias
    line needed — it's the generic class itself)."""
    out = tmp_path / "out"
    _gen(
        Path(__file__).parent / "fixtures" / "paginated" / "openapi.yml",
        Path(__file__).parent / "fixtures" / "paginated" / "stainless.yml",
        out,
    )
    src = (out / "paginated" / "resources" / "things.py").read_text()
    assert "SyncCursorPage[" in src
    pag_src = (out / "paginated" / "_core" / "pagination.py").read_text()
    # Default `cursor_page` is the built-in class — NO extra alias line.
    assert "SyncCursorPage = SyncCursorPage" not in pag_src
