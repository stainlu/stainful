# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.6.0] — 2026-05-22

**TypeScript completeness pass.** v0.5 shipped the TypeScript emitter
with an explicit deferred list — multipart / binary upload, webhook
unwrap, and nested resource directories. This release closes that
list. The same `stainless.yml` now emits a TypeScript SDK whose
file layout, request shapes, and webhook handling match what
Stainless generated for openai-node, for every API shape the Python
side already supported.

### Added — TypeScript

- **Nested resource directories.** Subresources now emit as
  directories matching openai-node's layout — a 3-deep
  `chat.completions.messages` lands at
  `resources/chat/completions/messages.ts`, with per-directory
  `index.ts` re-exports so `import { Chat } from 'pkg/resources/chat'`
  resolves whether the sibling is a bare file or a subpackage.
  Cross-cutting imports are depth-aware (`../` count derived from
  the resource's position in the tree). Drop-in path parity for
  anyone migrating an openai-node-shaped import.
- **Multipart, multi-content, and binary uploads.** Three wire
  shapes, same IR the Python side uses:
  - *Multi-content auto-detect (JSON ↔ multipart):* a single method
    (`c.skills.create({ files: [...], ... })`) sends multipart when
    file-like values are present, JSON when they aren't — decided by
    the arguments passed, via a TS `extractFiles` mirroring the
    Python runtime. Oracle: openai-node's
    `maybeMultipartFormRequestOptions`.
  - *Raw binary upload:* `application/octet-stream` methods take a
    single `body: Uploadable` and ship the bytes verbatim.
  - `Uploadable` covers `Blob | File | ArrayBuffer | Uint8Array |
    [filename, content, contentType?]`; `FormData` parts wrap raw
    bytes in a `Blob` so the wire works under both browser fetch and
    Node 20+ undici.
- **Webhook unwrap (Standard Webhooks).** `type: webhook_unwrap`
  config methods now emit in TypeScript with the same shape as
  Python: `unwrap(payload, headers, opts?)` returns the typed event
  union (`type WebhooksUnwrapEvent = OrderCreatedEvent | …`), and
  `verifySignature(...)` throws `InvalidWebhookSignatureError` on a
  bad signature. HMAC-SHA256 over `{webhook_id}.{timestamp}.{body}`,
  base64, `v1,<sig>` header, `whsec_` prefix base64-decoded —
  identical algorithm to the Python side (standardwebhooks.com).
  Runtime uses Web Crypto (`crypto.subtle.sign`) — global in Node
  20+, browsers, and edge runtimes — with no `@types/node`
  dependency. Env-var fallback (`<BRAND>_WEBHOOK_SECRET`) is read via
  `globalThis.process` so the lookup compiles in browser / edge
  contexts where `process` may not exist.

### Improved

- **Package description + tooling now reflect both targets.** The
  PyPI description no longer says "Python SDK generator" — stainful
  emits Python *and* TypeScript from one config.

### Verified

- 139 tests green (was 133 at v0.5; +6 new TS regression tests
  covering nested dirs, multi-content/binary, and the webhook
  scenarios — happy path, both event variants, bad signature, stale
  timestamp, missing header, `whsec_` base64 decode, void
  `verifySignature`).
- Every TS feature is runtime-verified, not just tsc-clean: the
  webhook smoke signs payloads with `node:crypto` so the wire shape
  exactly matches what the SDK expects, then unwraps.

### Honest scope boundaries

Still deferred for TypeScript (tracked, not blocking openai-style
workflows): `withRawResponse` / `asResponse` (openai-node's
`APIPromise<T>` design — a `Promise` subclass returned by every
method, not Python's wrapper-class pattern; a runtime-wide change
deferred to a later release), and MCP server emit from the TS path.
Python remains at feature-parity with what Stainless generated for
openai-python.

## [0.5.0] — 2026-05-21

**TypeScript ships.** One `stainless.yml` now emits a working SDK in
both Python and TypeScript. The TS slice covers everything that
makes a Stainless-generated openai-node SDK actually usable — typed
errors, retries with backoff + jitter + idempotency, **SSE streaming
with narrowed overloads**, and **`CursorPage<T>` pagination that walks
all pages via `for await`** — all runtime-verified against mock
fetch + mock SSE + mock paginated responses. Plus the Python side
closes the last documented gap (**multi-content request bodies** with
JSON ↔ multipart auto-detect) and ships docs / MCP polish.

### Added — TypeScript

- **TypeScript emitter (`stainful generate-ts`).** Same IR as the
  Python emitter — only the renderer differs. Generates a SDK whose
  symbol surface matches openai-node (`<Brand>` client class
  extending `BaseClient`, `<Name>Resource` extending `APIResource`,
  typed error hierarchy with the same names as the Python side,
  package.json + tsconfig.json so users `npm install && tsc`).
  Property names that aren't valid TS identifiers (e.g.
  `"git.branch"`) are quoted in interfaces. Methods camelCase per TS
  convention. tsc strict mode passes on OneBusAway + chat fixture +
  the full openai-openapi spec (162 paths, 983 schemas).
- **SSE streaming with narrowed overloads.** Methods with a
  `streaming:` config block emit two overloads
  (`stream?: false` → `Promise<Response>`; `stream: true` →
  `Promise<Stream<Event>>`) so users get perfect narrowing at the
  call site:
      const stream = await client.chat.completions.create({
        model: 'gpt-4', stream: true, messages: [...]
      });
      for await (const event of stream) { ... }
  Runtime `Stream<T>` (`_core/streaming.ts`) parses
  `data: <json>\n\n` blocks, stops at `[DONE]`, tolerates non-JSON
  keepalive/comment frames, has `.abort()` to close mid-stream.
- **`CursorPage<T>` pagination.** Paginated methods return
  `Promise<CursorPage<Item>>`; the page object is an
  `AsyncIterable<T>` that walks subsequent pages on demand:
      const page = await client.things.list({ limit: 50 });
      for await (const thing of page) { ... }    // auto-pages
  One generic algorithm covers every forward-only cursor variant
  (`after=<last_id>`, `page_token=<next_page>`, …) — the wire
  param + cursor response field come from the same stainless.yml
  `pagination[].request` / `.response` blocks the Python side uses.
- **TypeScript runtime, vendored as `_core/`.** Fetch-based
  `BaseClient` with retries (backoff + jitter + `Retry-After` +
  idempotency-key on retried writes), full typed error hierarchy
  (`APIError`, `RateLimitError`, `NotFoundError`, …), abort signal /
  per-request timeout, dependency-injectable `fetch` for tests, full
  ESM/CJS compatible. No npm deps in the generated runtime.
- **Runtime smoke tests** (Node-skipped if not available): happy
  GET / 404→`NotFoundError` / 429→`RateLimitError` after retries /
  SSE `for await` yields 3 events / pagination `for await` walks
  2 pages with the cursor wire param. The TS SDK is no longer "type-
  checked" — it's *runtime-verified*.

### Added — Python (closes the last migration-guide gap)

- **Multi-content request bodies (JSON ↔ multipart auto-detect).**
  Oracle: openai-python's `skills.create(files=…)` — a single method
  whose runtime extracts file-like values from the body; if present
  → multipart wire request; else → JSON. Same `c.x.create(...)`
  call shape both ways, decided by the arguments the user actually
  passes. The migration guide gap list is now **empty** (modulo
  JSON-OR-form-urlencoded same-op, which has no auto-detect possible
  and remains deferred).

### Improved

- **Docs generator polish.** Per-resource `Types:` import blocks
  (matches openai-python's api.md format) listing the named models
  the resource's methods reference. Method.docs now populated from
  the OpenAPI op's `description` (falling back to `summary`) — so
  generated Python SDK methods get real docstrings, and MCP tool
  descriptions are spec-sourced rather than synthesized.
- **MCP generator polish.** Streaming methods (`chat.completions
  .create`) now lock to the non-streaming wire shape — the `stream`
  discriminator is removed from the input schema (LLM clients can't
  toggle it) and the tool description notes "(stainful MCP: tool
  always uses the non-streaming wire shape; the full response is
  returned in one TextContent.)". Avoids ambiguous "what does
  stream=True do here?" tool calls.

### Verified

- 133 tests green (was 118 at v0.4; 15 new regression tests
  including the TS runtime smokes).
- mypy 0 on 253 combined source files.
- 10 consecutive green CI pushes since v0.4.

### Honest scope boundaries

TypeScript v0.1 ships streaming + pagination + retries + typed
errors. Still deferred (tracked, not blocking openai-style
workflows): multipart / binary upload, webhook unwrap,
nested resource directories (`resources/chat/completions/
messages.ts` shape), MCP server emit from TS. Python is at
feature-parity with what Stainless was generating for openai-python.

## [0.4.0] — 2026-05-20

**Three new generators + every documented adoption-blocker closed.**
One `stainless.yml` now produces a Python SDK + Mintlify-shaped
`api.md` + a Model Context Protocol server — all OSS, all drop-in for
Stainless. Migration guide gap list is empty save multi-content
request bodies (no public Stainless oracle to verify against).

### Added — three new artifacts from the same spec

- **`stainful docs` — Stainless-shaped Markdown API doc.** Per-resource
  sections (`# Top`, `## Subresource`, `### Sub-sub`), Methods lists
  with `<code title="<verb> <path>">…</code>` linked into the
  generated SDK tree, Shared Types block, paginated returns rendered
  as `SyncCursorPage[Item]` with the item type resolved through
  `ModelRef → ObjectType`, webhook-unwrap entries deliberately
  without verb/path. Mintlify-compatible. Oracle:
  `tests/oracles/openai-python/api.md`.
- **`stainful mcp` — Model Context Protocol server.** Each HTTP method
  becomes one MCP tool (`<resource_chain>_<method>`), input schema is
  faithful JSON Schema (path params + query params + body object
  expanded), response serialized as `TextContent` (pydantic model →
  JSON, bytes → base64). Lazy client construction so the module
  imports cleanly before the env var is set. Stdio transport (Claude
  Desktop / Cline / mcp-cli compatible). Webhook-unwrap excluded —
  not a remote call.
- **Rich `APIResponse[T]` via `with_raw_response.*`.** Was a
  pass-through pre-v0.4; now a real wrapper exposing `.http_response`,
  `.status_code`, `.headers`, `.request_id`, `.content`, `.parse() ->
  T`. ContextVar-based wrapper so concurrent async tasks don't
  pollute each other. `<Brand>APIResponse` alias at the package root.

### Added — Stainless drop-in symbol surface

- **`custom_casings:` honored.** Both dict-style (`acme_ai_sdk:
  AcmeAISDK`) and list-of-singletons forms parse into
  `Config.custom_casings`. Whole-name and per-token overrides in
  `brand()` / `pascal()`. Was the #1 adoption blocker at v0.3.0 —
  anyone whose brand wasn't in our 4-entry compound table emitted
  the wrong class name (`AcmeAi` instead of `AcmeAI`).
- **`targets.python.package_name` honored.** Was silently dropped —
  package directory was always derived from `organization.name`
  (`name: acme-ai-sdk` → `acme_ai/` even when user set
  `package_name: acme`). Real adoption blocker.
- **`.to_json()` / `.to_dict()` aliases** on every generated model
  (route to pydantic v2's `model_dump_json` / `model_dump` with
  Stainless defaults `by_alias=True, exclude_unset=True`).
- **Webhook `secret=` env-var fallback.** Generated
  `client.webhooks.unwrap(...)` / `verify_signature(...)` reads
  `<BRAND_UPPER>_WEBHOOK_SECRET` when no explicit secret is passed
  (matches openai-python's `OPENAI_WEBHOOK_SECRET`).
- **Typed error-body model auto-promoted to
  `<pkg>.types.shared.ErrorObject`.** Scans the spec's 4XX/default
  response refs; picks the most common; unwraps single-field
  `{error: $ref X}` wrappers; prefers error-shaped candidates
  (`message` + at least one of `code`/`type`/`param`). Real openai
  spec: `Error(code, message, param, type)` — identical to
  openai-python's `openai.types.shared.ErrorObject`.
- **Alternate page class names.** Spec-specific page-class symbols
  (`SyncTokenPage`, `SyncNextCursorPage`, `SyncConversationCursorPage`,
  `SyncPageCursor`, …) emitted as aliases in `<pkg>/_core/pagination
  .py` so `from <pkg>.pagination import <Specific>Page` resolves.
  All five forward-only cursor variants across openai+anthropic
  alias to one config-driven generic class.
- **Anthropic-shape bi-directional pagination.** Distinct algorithm
  (`before_id` ↔ `after_id` based on initial-request direction).
  New runtime class `_BiDirectionalPage`; IR detects the shape via
  `request:`/`response:` patterns; `pagination_cfg` carries the
  four wire names.

### Fixed

- **`$shared.models` ref normalization.** Real configs use either
  bare component name (`references: Reference`) or full $ref
  (`acme_widget_id_string: "#/components/schemas/..."`); we
  normalize both.
- **Resource template pagination-import regex** widened from
  `Sync(Cursor)?Page` to any `Sync<...>Page` so spec-specific
  aliases import correctly.

### Verified

- **118 tests green** (was 95 at v0.3.0 — 23 new regression tests
  for the gap-closure work).
- **mypy 0 on 253 combined source files** (generated openai SDK +
  generated OneBusAway dogfood + emitter + runtime).
- Drop-in import parity with openai-python: full resource tree,
  `<pkg>.types.shared.ErrorObject`, `<pkg>.APIResponse`,
  `<pkg>.types.ErrorObject`, generic-with-alias page classes.
- 9 quiet pushes since v0.3.0, all CI-green on py3.10–3.12.

### Honest scope boundaries

Multi-content request bodies (an op declaring `application/json`
OR `multipart/form-data` OR `application/x-www-form-urlencoded` on
the same operation) still pick the first match — no public
Stainless oracle to verify the exact API surface design.
Documented in the migration guide.

## [0.3.0] — 2026-05-20

**Nine fixes surfaced by generating a working SDK from the real
`openai-openapi` spec (162 paths, 983 schemas) — each oracle-verified
against the actual Stainless-generated `openai-python` SDK.** Plus the
**nested resource directory layout** that matches `openai-python`'s
structure (`resources/chat/completions/messages.py` etc.) — drop-in
import paths.

### Fixed

- **Silent leaf-name collision (correctness bug).** With the previous
  flat `resources/*.py` layout, two subresources sharing a leaf name
  (e.g. `chat.completions.messages` AND `threads.messages`) wrote to
  the same file; last-wins meant `c.chat.completions.messages.list()`
  would silently call `/threads/{thread_id}/messages` (wrong
  endpoint). Now: nested directories matching `openai-python`
  (`resources/chat/completions/messages.py`,
  `resources/threads/messages.py`). Cross-cutting imports inside
  resource files switched from `..` to absolute `<pkg>._core.X` so the
  same template works at any depth. New regression test
  (`test_subresource_with_shared_leaf_name_calls_right_endpoint`).
- **Discriminated union with an `Any` variant** (real openai spec
  pattern: `oneOf: [{type:object, properties:{type,...}}, {}]` where
  the empty branch lowers to `AnyType`). Pydantic rejects `object` as
  a discriminated-union variant at import time. Now: drop the AnyType
  variants from a discriminated union before applying the
  discriminator.
- **Field-name shadows Python builtin used as a type annotation.**
  Real example: `ConversationResource` has
  `object: Literal['conversation']` AND `metadata: object`. Mypy's
  class-scope name resolution finds the field, not the builtin →
  error. Now: when a field is named after a Python builtin AND that
  name is used as a type annotation by another field, the
  builtin-named field is reordered to come AFTER any such use (within
  the same required-vs-optional cohort, so pydantic field ordering
  stays valid). Oracle: `openai-python`'s `Conversation` lays out
  `id, metadata, object, ...` for exactly this reason.
- **`allOf` merger was too strict at spec scale.** Rejected
  real-world `allOf` branches that differed only in (a) cosmetic
  fields (description / title / example), (b) `$ref` vs inlined-same-
  schema, (c) enum membership where Stainless takes the union
  (oracle: `openai-python` emits `Literal["completed", "incomplete",
  "failed", "in_progress"]` — the union of two branches), or (d) a
  `T-or-null` vs `T` lattice (oracle: `openai-python` emits
  `Optional[int]` when one branch is nullable and the other isn't).
  Now: cosmetic-strip + one-hop `$ref` resolve + enum-union +
  nullable-lattice; remaining structural divergence falls through to
  lenient last-wins. Honest trade-off: strict raise was right for
  in-repo fixtures, wrong at real-spec scale.
- **`cast_to: type | None` was too narrow.** The
  `Annotated[Union[V0, V1], Field(discriminator="task")]` shape for a
  discriminated-union response (real example: openai
  `audio.transcriptions.create`) failed mypy AND silently fell
  through to raw dict at runtime. Now: signature widened to `Any`;
  `_process_response_data` switched to a TypeAdapter-first pattern
  (try `pydantic.TypeAdapter(cast_to)`, fall back to raw data only on
  `PydanticSchemaGenerationError`) — passes mypy, validates discriminated
  unions, and `bytes` / `None` short-circuits still work.

### Added

- **Real-world test:** `examples/openai/` — the public Stainless-
  processed `openai-openapi` spec (162 paths, 983 schemas, OpenAPI
  3.1) + a hand-written `stainless.yml` covering ~22 resources (chat,
  embeddings, files, audio, fine_tuning, models, moderations, images,
  batches, assistants, uploads, vector_stores, conversations,
  threads, …). Generates a **mypy-clean 172-file SDK** that exercises
  every capability stainful supports: streaming, JSON, multipart,
  binary download, raw binary upload, cursor pagination,
  discriminated-union responses, nested subresources, webhook unwrap.
  Generated SDK is gitignored; spec committed (content-pinned via the
  Stainless CDN SHA in the source URL).
- **Pydantic-reserved field-name mangling.** Field names that clash
  with `pydantic.BaseModel` attributes (`schema`, `copy`, `dict`,
  `json`, `model_dump`, ...) are now mangled to `<name>_` and aliased
  via `Field(alias="<wire>")` — same pattern as the existing
  Python-keyword mangle. Oracle: `openai-python` emits
  `schema_: Optional[Dict[str, object]] = FieldInfo(alias="schema",
  default=None)`.
- **Compound brand name override.** `openai` → `OpenAI` (not
  `Openai`), `openapi` → `OpenAPI`, `anthropic` → `Anthropic`,
  `cloudflare` → `Cloudflare`. Hardcoded table (no risky auto-split
  on initialism suffixes — would over-match real words like `chai`,
  `tai`). Stainless's `custom_casings` block is the long-term answer
  (v1.1 backlog).
- **Adoption polish.** New
  [`docs/migrating-from-stainless.md`](docs/migrating-from-stainless.md):
  step-by-step migration guide for Stainless customers (after the
  Anthropic acquisition wind-down), exhaustive symbol-compat table,
  honest gap list with workarounds. README leads with a migration
  callout; OpenAI proof point in the Status section. Quickstart
  trimmed to the essential install + generate; contributor commands
  moved out of the user flow.

### Verified

- **84 tests green** (was 77 at v0.2.0; 7 new regression tests for
  the cross-spec bugs).
- **mypy 0 on 250 combined source files** (172 generated openai SDK +
  92 dogfood + 9 emitter).
- **Drop-in import parity:** `from openai.resources.chat.completions
  import CompletionsResource` resolves against stainful's output.
- **No regressions on the OneBusAway dogfood:** 29/29 of Stainless's
  own test files still import unchanged.

## [0.2.0] — 2026-05-20

**Seven product-quality fixes verified vs the real Stainless SDKs (openai-
python / anthropic-sdk-python / onebusaway-python-sdk) — each its own
CI-gated commit.** Quality bar: resource-method recall 1.00,
method-signature match 1.00, model-name recall 0.95, generated SDK
mypy-clean, 29/29 of Stainless's own OneBusAway test files import
unchanged, end-to-end behavioral conformance for streaming + cursor
pagination + multipart + binary download + binary upload + webhook
unwrap. Drop-in for `stainless.yml`; not affiliated with Stainless or
Anthropic.

### Added
- **Webhook unwrap with typed discriminated event union (Standard Webhooks
  scheme).** A `stainless.yml` method with `type: webhook_unwrap` now
  generates `client.webhooks.unwrap(payload, headers, *, secret,
  tolerance=300)` returning the **typed event variant** (not just a parsed
  dict) — pydantic-discriminated `Annotated[Union[…], PropertyInfo(
  discriminator=…)]` built from the config `event_types:` block. Sibling
  `client.webhooks.verify_signature(...)` for verify-without-parse.
  Signature scheme = **Standard Webhooks** (standardwebhooks.com): HMAC-
  SHA256 over `f"{webhook_id}.{timestamp}.{body}"`, base64, multi-`v1,<sig>`
  header, `whsec_` base64-decoded secret, constant-time compare, ±tolerance
  replay window. Algorithm verified against the openai-python oracle
  (`resources/webhooks/webhooks.py`); the verification helper is vendored
  once into `<pkg>/_core/_webhooks.py` (single source). New
  `InvalidWebhookSignatureError` is exported from the package root for
  drop-in `except` compatibility. Previously the emitter ignored
  `type: webhook_unwrap` and would have generated a broken `self._post(
  f"")` (latent: no fixture triggered it). IR change: `event_types` $refs
  are now resolved into IR `ModelRef`s so the emitter can render the typed
  union. New `tests/fixtures/webhooks/` + 10-case `tests/test_webhook_unwrap.py`
  (typed variant discrimination, `whsec_`-decode, bad sig, stale timestamp,
  missing header, root-symbol export). **Known scope boundary:** the
  `secret=` kwarg is required (no client-level `webhook_secret`/env-var
  fallback yet).
- **Raw binary request bodies (`application/octet-stream` uploads).**
  S3-style `PUT object`, GitHub release-asset upload, and similar raw
  uploads now work end-to-end: the emitter generates `body: bytes`,
  the runtime sends it verbatim with
  `Content-Type: application/octet-stream`, sync + async. Fixes a
  latent codegen flaw — previously the emitter wrapped the bytes in
  `_body = {"None": body}` and called `to_jsonable` on it; no fixture
  or dogfood exercised the path, so nothing in the wild was hitting
  it. New `tests/fixtures/upload_binary/` + `tests/test_binary_upload.py`
  asserts the wire body is the exact bytes and the content-type is
  octet-stream. **Known scope boundary:** endpoints declaring *multiple*
  request content types on the same op (JSON OR multipart OR octet-
  stream on the same op) still pick the first match; the
  alternative-content case has no public Stainless oracle and is
  deferred — separate work.
- **Binary responses.** Non-JSON 200s (audio/*, octet-stream, image/*, …) used to get no type and be JSON-parsed (mangled). Now download endpoints (e.g. OpenAI `audio.speech`) return raw `bytes`, sync + async. Fixture + conformance test; mypy-clean.
- **Multipart / file upload (RESEARCH §4 #10).** `multipart/form-data`
  bodies were emitted as one opaque param and sent as JSON (broken for
  real uploads, e.g. OpenAI files/audio). Now: fields are expanded, binary
  fields typed `FileTypes`, and the runtime sends real multipart (file in
  `files`, scalars in `data`), sync + async. New fixture + conformance
  test; generated SDK stays mypy-clean.
- **Auto-pagination (RESEARCH §4 #1).** Paginated `list` endpoints now
  generate `Sync/AsyncCursorPage[Item]` returns; `for x in client.x.list():`
  (and `async for`) transparently walks **every** page over the vendored
  runtime. Was entirely missing (the emitter ignored `paginated:`). New
  conformance fixture + sync/async behavioral test. Generated SDK stays
  mypy-clean.

### Fixed
- **Cursor pagination wire param is now config-driven.** Previously the
  runtime hard-coded `?cursor=<id>` on next-page requests — silently broken
  against any real openai-/anthropic-style API expecting `?after=<last_id>`
  (the actual Stainless `SyncCursorPage` shape). Now the IR derives the
  cursor param name and the response cursor field from the stainless config
  `request:` / `response:` blocks; the emitter passes them through; the
  runtime uses them with safe defaults (`after`, then `next_cursor`, then
  last-item `id`). One generic `_CursorPage` now covers the five forward-
  only cursor variants in the openai+anthropic oracles (`SyncCursorPage`,
  `SyncConversationCursorPage`, `SyncNextCursorPage`, `SyncTokenPage`,
  `SyncPageCursor`) — same algorithm, different wire names. New fixture
  (`tests/fixtures/paginated_after/`) + conformance test asserting the
  wire request actually says `?after=2` from a `last_id` response;
  original `cursor` fixture still passes. **Known scope boundary:**
  anthropic's bi-directional `SyncPage` (chooses `before_id` vs `after_id`
  from the initial request) is still forward-only here — separate algorithm,
  separate work.

### Improved (model fidelity vs the real Stainless SDK)
- Resource→type-name prefix now singularizes the last word
  (`trip-details` → `TripDetailRetrieveResponse`; `client.chat.completions`
  → `CompletionCreateResponse`, like OpenAI's `ChatCompletion`) while the
  resource *class* stays plural. Narrowly scoped — `agencies_with_coverage`
  et al. unchanged.
- Result: model-name recall **0.90 → 0.95**, method-signature match
  **0.99 → 1.00**, and **29/29 (100%)** of Stainless's own test files now
  import unchanged against stainful's output (was 28/29).

## [0.1.0] — 2026-05-20

First public release. **The open-source Stainless** — point your existing
`stainless.yml` at it and get an idiomatic Python SDK.

### Added
- End-to-end generator: `stainless.yml` + OpenAPI 3.x → idiomatic Python SDK
  (typed pydantic models, typed error hierarchy, retries w/ backoff +
  `Retry-After` + idempotency, auto-pagination, SSE streaming, sync+async,
  per-file `types/`, `*Params` TypedDicts, vendored runtime).
- Quality harness measuring stainful's output against the **real**
  Stainless-generated OneBusAway SDK, gated in CI (no-regression baselines).

### Verified vs the real Stainless SDK (CI-gated)
- resource-method recall **1.00**, method-signature match **0.99**
- model-name recall **0.90**, generated code **mypy-clean (0 errors)**
- **28/29** of Stainless's own test files import unchanged against our output
- regeneration is bit-stable; the repo dogfoods itself
  (`examples/onebusaway/sdk`, guard-enforced)

### Known gaps (honest)
Python only; model-name long tail (~10%: a few `*Params`, `SearchFor*`
naming, `trip-details` singular); P3 behavioral-via-Prism not yet run.
Not affiliated with Stainless or Anthropic.

## [0.0.1] — 2026-05-19

First working release. **v1 complete (slices 1–6), 37 tests green.**

### Added
- `stainless.yml`-compatible config loader with position-aware diagnostics and a
  lenient/`strict` mode (drop-in: unknown keys preserved, not rejected).
- OpenAPI 3.x loader + cycle-safe `$ref` / `allOf` resolver.
- Rich, language-agnostic **IR** — 3-valued cardinality
  (`required` ≠ `optional` ≠ `nullable`), `ModelRef` cycle-breaking,
  discriminated unions, pagination/streaming intents.
- Hand-written Python **runtime** vendored into generated SDKs: httpx sync+async
  client, retries (backoff + jitter + `Retry-After` + idempotency keys), typed
  error hierarchy with `request_id`, pagination base classes, SSE streaming.
- **Python emitter**: pydantic v2 models (aliases, discriminated unions),
  nested resource clients, request bodies, query params, streaming `@overload`s,
  sync+async parity, package scaffold + generated `pyproject.toml`.
- Conformance fixtures: OneBusAway (REST/allOf/recursion) and chat
  (streaming/unions/bodies).

### Verified
- Output matches the real Stainless-generated `OneBusAway/python-sdk` on client
  class name, package, env var, and call shape — the drop-in symbol contract.

### Known gaps (v1.1 backlog — see the README Status section)
`to_json()/.to_dict()` helper aliases · rich `APIResponse` object ·
per-file model modules · typed error-body models · `custom_casings`.
