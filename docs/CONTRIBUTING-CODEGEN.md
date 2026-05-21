# Contributing to stainful's codegen

If you've already skimmed [`CONTRIBUTING.md`](../CONTRIBUTING.md), this is
the deeper guide for the part most contributions actually touch: **closing
parity gaps with real Stainless-generated SDKs**. The project is small,
the architecture is short, and almost every fix lives in the same shape —
*find an oracle, write a fixture, then make the emitter match.*

## What "drop-in" actually means

The product promise is that a Stainless customer can point stainful at
their existing `stainless.yml` + OpenAPI spec and get an SDK that looks
the way Stainless's hosted generator made it — same client class name,
same exception hierarchy, same `SyncCursorPage` / `NotGiven` / typed-error
surface, same per-resource layout. Existing `import` lines and `except`
clauses don't change. That's the contract.

The bottleneck for outside contribution isn't the talent pool of Python or
OpenAPI engineers — it's that the parity contract isn't visible until you
see a few examples. This doc fixes that.

## Architecture in one paragraph

OpenAPI 3.x spec + `stainless.yml` config get loaded into a language-
agnostic **IR** (`src/stainful/ir/`). One emitter renders the IR into a
Python SDK (`src/stainful/emit/python/`); a second renders it into a
TypeScript SDK (`src/stainful/emit/typescript/`); a third writes a
Mintlify-shaped `api.md` (`src/stainful/emit/markdown/`); a fourth emits
an MCP server (`src/stainful/emit/mcp/`). All four share the IR — that's
the reason the project can claim "one config, four artifacts."

Vendored runtimes (`src/stainful/runtime/` for Python, `src/stainful/
runtime_ts/` for TS) get copied verbatim into each generated SDK as
`<pkg>/_core/` so the SDK has no dependency on stainful itself.

## The oracles

`tests/oracles/` holds real Stainless-generated SDKs at pinned SHAs,
fetched by `scripts/fetch_oracles.sh`:

- `onebusaway-python-sdk` — small, full-config-public, the tier-1 parity
  target. 29-of-29 of Stainless's own test files import unchanged
  against stainful's output; this is the import-compat baseline.
- `openai-python` — large, real-world, ground truth for almost every
  Stainless naming convention and runtime helper.
- `anthropic-sdk-python` — second-data-point; specifically used as the
  oracle for the bi-directional `SyncPage` pagination shape.
- `openai-node` — TS oracle for the TypeScript emitter.

We **never copy code from the oracles into the generator** — they're
read for comparison only. They're permissively licensed (Apache 2.0 /
MIT) and pinned by SHA, so a Stainless wind-down can't move them.

## What a parity contribution looks like

The most useful contribution unit is a **fixture + test that pins the
expected output against the oracle**. Here's the shape that has worked
for every recent parity fix:

1. **Find the gap.** Either reading a Stainless-generated SDK and
   noticing it does something we don't, or hitting a real spec that
   surfaces unexpected output. Real example: openai's
   `client.skills.create(files=…)` ships JSON OR multipart on the same
   op; our emitter was picking the first content type and ignoring the
   alternative.
2. **Find the oracle.** Look up how the real Stainless SDK handles it.
   For the multi-content case:
   `tests/oracles/openai-python/src/openai/resources/skills/skills.py`
   showed `extract_files(body, paths=[…])` — a single method that
   auto-detects file-like values at call time. That's the API
   surface we needed to match.
3. **Write a minimal fixture.** Add a directory under
   `tests/fixtures/<name>/` with an `openapi.yml` (the minimal spec
   that reproduces the shape) and a `stainless.yml` (the minimal
   config). The fixture's job is to be the *smallest possible input*
   that exercises the path. For multi-content:
   `tests/fixtures/multi_content/` is 47 lines of OpenAPI + 13 lines
   of config.
4. **Write the failing test.** A new `tests/test_<name>.py` that
   generates the SDK and asserts the parity property the gap was
   about. For multi-content: assert the wire request is multipart
   when `files=…` is passed; JSON when it isn't.
5. **Make it pass.** Touch the IR builder (`src/stainful/ir/builder
   .py`) or the emitter or the runtime as the test demands. Keep the
   diff minimal and oracle-justified.
6. **Re-run the full suite + ruff + mypy + dogfood.** The dogfood
   SDKs at `examples/onebusaway/sdk/` and `examples/openai/sdk/`
   regenerate from the same code; if your change touched the
   emitter, you need to `uv run stainful generate ...` + `uv run
   stainful mcp ...` + `uv run stainful docs ...` and commit the
   regenerated output. CI fails if regeneration changes a byte.
7. **PR with: fixture + test + emitter/runtime change + regenerated
   dogfood.** Short, focused, oracle-cited. Recent examples land in
   ~50-line diffs (sometimes less).

## A worked example — multi-content auto-detect

Concrete walkthrough. The commit lives at `d395e80` (`feat: multi-content
request bodies (JSON ↔ multipart auto-detect)`).

The gap: openai's spec declares JSON + multipart on the same op
(`skills.create`, `containers/files.create`). Our `_body()` was picking
the first content type and dropping the rest.

Files touched (about 270 LOC):

- `src/stainful/ir/model.py` — `BodyShape` got `multi_content: bool` +
  `file_paths: tuple[tuple[str, ...], ...]` (paths to file-like fields
  in the body, using `<array>` as a wildcard segment).
- `src/stainful/ir/builder.py` — detect when `requestBody.content` has
  both JSON and multipart; build the file-path list by walking the
  multipart schema for `{type: string, format: binary}` properties.
- `src/stainful/runtime/_models.py` — new `extract_files(body, paths)`
  helper, mirroring openai-python's `_utils.extract_files`. Walks the
  body dict, pops file-like values, returns `[(wire_name, value), …]`.
- `src/stainful/runtime/_base_client.py` — `_build_request` learns a
  `files=` path; when set, sends `data=<scalars>` + `files=<list>` as
  multipart.
- `src/stainful/emit/python/emitter.py` — when `m.body.multi_content`:
  generate `_files = _extract_files(_body, paths=[…])` and then
  `body=_body if _files else to_jsonable(_body), files=_files or None`.
- `tests/fixtures/multi_content/{openapi.yml, stainless.yml}` — the
  minimal fixture (skills-shape).
- `tests/test_multi_content.py` — 4 cases: signature includes `files`
  as union of JSON + multipart fields; JSON wire path when no files;
  multipart wire path when files present; async parity.

Total diff: +212 lines of source / -2. The oracle (openai-python's
`skills.create` source) was named in the commit body so reviewers can
verify the design choice without reading my mind.

That's the unit. Find a gap, name the oracle, write the fixture,
make it pass.

## Where the gaps are

The migration-guide gap list ([`docs/migrating-from-stainless.md`](
migrating-from-stainless.md)) is currently empty modulo
JSON-OR-form-urlencoded same-op (no auto-detect possible, no public
Stainless oracle). For *new* parity cases, the natural sources:

- Read through `tests/oracles/openai-python/api.md` and compare to
  `examples/openai/api.md`. Anything different (naming, layout,
  symbol surface) is a candidate.
- Generate the OpenAI SDK locally and `mypy` it. mypy errors are
  ground truth for shape mismatches the type system catches.
- Run Stainless's own test suite from `tests/oracles/<sdk>/tests/`
  against stainful's generated output. Anything that doesn't import
  cleanly is a parity miss.

For TypeScript (newer; smaller surface area covered): multipart,
binary upload, nested resource directories (`resources/chat/
completions/messages.ts` shape), and the webhook unwrap surface
are all genuine open contributions with `openai-node` as the oracle.

## Conventions

- **Always cite the oracle in the commit body.** The reviewer's job
  is to verify the design matches what Stainless actually does;
  citing the oracle path makes that one-click.
- **No oracle, no PR.** If you're inventing the surface (no public
  Stainless config or generated SDK exercises it), that's a design
  proposal — open it as a GitHub Discussion first, not a PR.
- **Fixtures stay minimal.** A fixture's job is to be the smallest
  possible input that surfaces the path. Real-world specs are too
  big to debug.
- **Tests assert the property, not the source.** "The wire request
  is multipart when files present" > "the generated source contains
  the string `files=_files`". Prefer behavioral assertions over
  source-string matches.
- **Regenerate the dogfood.** Any emitter change must come with
  regenerated `examples/onebusaway/sdk/` (and usually
  `examples/openai/sdk/`) committed. CI catches this.

## Setup

```bash
git clone https://github.com/stainlu/stainful && cd stainful
uv venv && uv pip install -e ".[dev,generated-runtime]"

# fetch the oracles (pinned SHAs; one-time, idempotent)
bash scripts/fetch_oracles.sh

# run the suite
uv run pytest -q
uv run ruff check src tests
uv run mypy examples/onebusaway/sdk

# regenerate the dogfood after an emitter change
uv run stainful generate --spec examples/onebusaway/openapi.yml \
    --config examples/onebusaway/stainless.yml \
    --out examples/onebusaway/sdk
uv run stainful mcp --spec examples/onebusaway/openapi.yml \
    --config examples/onebusaway/stainless.yml \
    --out examples/onebusaway/sdk/onebusaway/mcp_server.py
uv run stainful docs --spec examples/onebusaway/openapi.yml \
    --config examples/onebusaway/stainless.yml \
    --out examples/onebusaway/api.md
```

That's the whole loop. If anything in this doc is wrong or unclear,
open an issue or PR against it directly — meta-feedback on the
contribution path is itself a useful contribution.
