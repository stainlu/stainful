"""Real-world stress test — generate the OpenAI chat.completions SDK from
the public openai-openapi spec (162 paths, 983 schemas) end-to-end.

This is the test that surfaced the bugs in v0.2.x → 0.3.x:
  - allOf merger was too strict (cosmetic, $ref-vs-inline, enum-union,
    nullable lattice) — rejected real-world specs
  - resource-template only imported `Literal`/`overload` from typing —
    real-world signatures need `List`/`Dict`/`Union`/`Annotated` and
    `pydantic.Field` for inlined discriminated unions
  - brand `openai` → `Openai` instead of `OpenAI` — compound names need
    explicit override (no risky auto-split)
  - fields named `schema` (etc.) clash with pydantic-reserved attributes
    — same Python-keyword mangle pattern, extended

The fixture is `examples/openai/` (committed spec + hand-written
stainless.yml). Generated SDK is gitignored — regenerated here every run.
"""

from __future__ import annotations

import importlib
import inspect
import py_compile
import sys
from pathlib import Path

import pytest

from stainful.config import load_config
from stainful.emit.python import emit
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

ROOT = Path(__file__).parent.parent
SPEC = ROOT / "examples" / "openai" / "openapi.yml"
CONF = ROOT / "examples" / "openai" / "stainless.yml"


@pytest.fixture(scope="module")
def oa(tmp_path_factory):
    if not SPEC.exists():
        pytest.skip("examples/openai/openapi.yml not present")
    out = tmp_path_factory.mktemp("oa")
    emit(
        build_ir(load_spec(str(SPEC)), load_config(str(CONF))),
        str(out),
    )
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules if m == "openai" or m.startswith("openai.")]:
        del sys.modules[m]
    return out, importlib.import_module("openai")


def test_emitted_files_compile(oa):
    out, _ = oa
    failures: list[str] = []
    for f in out.rglob("*.py"):
        if "/_core/" in str(f):                # runtime is hand-written
            continue
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{f}: {exc}")
    assert not failures, "\n".join(failures)


def test_client_class_uses_compound_brand_casing(oa):
    """`openai` is a compound brand (`open` + `AI` initialism). The class
    name is `OpenAI`/`AsyncOpenAI` — matches the real openai-python."""
    _, oai = oa
    assert hasattr(oai, "OpenAI")
    assert hasattr(oai, "AsyncOpenAI")
    assert not hasattr(oai, "Openai")  # the wrong casing must not leak


def test_chat_completions_resource_tree(oa):
    _, oai = oa
    c = oai.OpenAI(api_key="sk-test")
    methods = {m for m in dir(c.chat.completions)
               if not m.startswith("_") and callable(getattr(c.chat.completions, m))}
    assert {"create", "retrieve", "update", "list", "delete"} <= methods
    # nested subresource
    assert hasattr(c.chat.completions, "messages")
    assert hasattr(c.chat.completions.messages, "list")


def test_create_has_streaming_overload(oa):
    _, oai = oa
    c = oai.OpenAI(api_key="sk-test")
    ret = str(inspect.signature(c.chat.completions.create).return_annotation)
    # response model | Stream[event model]
    assert "Stream[" in ret and "|" in ret


def test_list_returns_cursor_page(oa):
    _, oai = oa
    c = oai.OpenAI(api_key="sk-test")
    ret = str(inspect.signature(c.chat.completions.list).return_annotation)
    assert ret.startswith("SyncCursorPage[")


def test_pydantic_reserved_field_is_aliased(oa):
    """The `schema` field on `response_format.json_schema` would clash with
    `pydantic.BaseModel.schema()` — must be mangled to `schema_` with
    `Field(alias="schema")`, matching openai-python's
    `schema_: Optional[...] = FieldInfo(alias="schema", ...)`."""
    out, _ = oa
    src = (out / "openai" / "types" / "completions_create_params.py").read_text()
    assert "schema_: Optional" in src
    assert 'alias="schema"' in src
    # the un-mangled `schema:` line must not appear as a model field
    assert "    schema: " not in src
