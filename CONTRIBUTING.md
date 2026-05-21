# Contributing to stainful

Thanks for helping build the open-source Stainless. This project values
**deep modules, clean interfaces, and honest scope**.

> **Closing a parity gap with a real Stainless SDK?** Read
> [`docs/CONTRIBUTING-CODEGEN.md`](docs/CONTRIBUTING-CODEGEN.md) first —
> it's the deeper guide for the part most contributions actually touch
> (fixture pattern, oracle harness, worked example end-to-end).

## Setup

```bash
uv venv
uv pip install -e ".[dev,generated-runtime]"
uv run pytest -q            # 37 tests, ~5s
uv run ruff check src tests
```

## Architecture in one breath

`config + openapi → IR → emit`. The **IR** (`src/stainful/ir/`) is a
fully-resolved, language-agnostic semantic model and the heart of the project.
Front-half loaders never know about Python; the emitter never parses OpenAPI.
Four public functions, one per module — keep that boundary clean.

## Ground rules

- **No fallbacks.** Unsupported input fails loud with a sourced error, never a
  silent degrade. (See `errors.py`, `SourceLoc`.)
- **Root-cause, not band-aid.** A failing fixture means the IR or emitter is
  wrong — fix it there, not at the call site.
- **Conformance-driven.** `tests/fixtures/onebusaway` (REST/allOf/recursion) and
  `tests/fixtures/chat` (streaming/unions/bodies) are the oracles. New capability
  ⇒ extend or add a fixture + a test that fails first.
- **Subtraction over addition.** Prefer removing a special case to adding one.
- Match the surrounding code's idiom and comment density.

## Good first issues

The v1.1 backlog (see the README **Status** section) — each item is
self-contained behind the IR boundary: `to_json()/.to_dict()` helpers, a richer
raw-response object, per-file model modules, typed error-body models,
`custom_casings`.

## PR checklist

- [ ] `uv run pytest -q` green
- [ ] `uv run ruff check src tests` clean
- [ ] New behavior covered by a fixture-driven test
- [ ] No fallback added; errors carry source location

By contributing you agree your work is licensed under MIT.
