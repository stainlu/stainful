# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
