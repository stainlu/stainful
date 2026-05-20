# Migrating from Stainless

If you've been using Stainless's hosted SDK generator and want to keep
shipping the same idiomatic Python SDK without depending on the hosted
service, **stainful is designed to be a drop-in.** It reads your existing
`stainless.yml` and OpenAPI spec; it emits the same drop-in symbols
(`OpenAI`, `NotGiven`, `RateLimitError`, `SyncCursorPage`, …); your existing
`import` lines and `except` clauses generally don't change.

This page is the practical guide. **Not affiliated with Stainless or
Anthropic.**

---

## TL;DR

```bash
pip install stainful
stainful generate \
  --spec   path/to/openapi.yml \
  --config path/to/stainless.yml \
  --out    path/to/sdk
```

That's the same `stainless.yml` you already have. The output is a Python
package; vendor / publish / use it exactly like the SDK Stainless was
generating for you.

---

## Step-by-step

**1. Install.**

```bash
pip install stainful           # or: uv pip install stainful
```

stainful is a CLI plus a library; the **generated** SDK only depends on
`httpx` + `pydantic`, not on stainful itself.

**2. Locate your inputs.** You need two files:

- the **OpenAPI 3.x spec** Stainless was using (whoever owns the API has
  this — if you're an API consumer, find the same `openapi.yml` /
  `openapi.json` your Stainless pipeline pointed at)
- the **`stainless.yml`** that drove the generation (in the Stainless app
  it's the file at the root of your project)

**3. Generate.**

```bash
stainful generate --spec openapi.yml --config stainless.yml --out ./sdk
```

The output is a fully self-contained Python package — a vendored runtime
sits at `<pkg>/_core/`; nothing inside it imports stainful at runtime.

**4. Verify drop-in compatibility.** If you have a project that already
imports from the old Stainless-generated SDK, the names should still
resolve:

```python
# old code, unchanged:
from openai import OpenAI, AsyncOpenAI, RateLimitError, NotGiven, NOT_GIVEN

client = OpenAI(api_key=...)
try:
    page = client.chat.completions.list()
    for completion in page:                    # auto-pagination
        ...
except RateLimitError as e:
    print(e.request_id)
```

The smoke test we ship for OneBusAway runs **29/29** of the real
Stainless-generated `OneBusAway/python-sdk` test files against stainful's
output unchanged — same imports, same exception names, same call shapes.

**5. Vendor / publish.** Treat the output the same way you treated the
Stainless-generated SDK: commit it to your repo, publish to your internal
package index, or `pip install -e ./sdk` for local dev.

---

## What's symbol-identical (drop-in)

These are the cross-SDK surfaces stainful matches verbatim, verified
against the real openai-python / anthropic-sdk-python / onebusaway-python-sdk
SDKs at pinned SHAs (CI-gated):

| Category | Symbols |
|---|---|
| **Client class** | `<Brand>` / `Async<Brand>` (e.g. `OpenAI` / `AsyncOpenAI`, `Anthropic` / `AsyncAnthropic`, `OnebusawaySDK` / `AsyncOnebusawaySDK`) |
| **Sentinels** | `NotGiven`, `not_given`, `NOT_GIVEN`, `Omit`, `omit` |
| **Typed errors** | `APIError`, `APIStatusError`, `APIConnectionError`, `APITimeoutError`, `APIResponseValidationError`, `BadRequestError`, `AuthenticationError`, `PermissionDeniedError`, `NotFoundError`, `ConflictError`, `UnprocessableEntityError`, `RateLimitError`, `InternalServerError`, `InvalidWebhookSignatureError`, brand-root alias `<Brand>Error = APIError` |
| **Pagination** | `SyncCursorPage[T]` / `AsyncCursorPage[T]` — iterable, walks every page transparently |
| **Resource classes** | `<Name>Resource` (e.g. `AgencyResource`, `CompletionsResource`) — Stainless convention |
| **Streaming** | `Stream[T]` / `AsyncStream[T]`, `@overload`'d so `stream=True` narrows the return |
| **Webhooks** | `client.webhooks.unwrap(payload, headers, *, secret) -> EventUnion` (Standard Webhooks scheme) |
| **`_utils`** | `parse_date`, `parse_datetime`, `is_dict`, `PropertyInfo` |

---

## What's the same in behavior

- **Retries** with exponential backoff + jitter, honor `Retry-After`,
  auto idempotency key (`idempotency-key` header) on retried writes
- **Auto-pagination** — iterating the page object fetches subsequent
  pages on demand (sync `__iter__` / async `__aiter__`)
- **SSE streaming** — overload pair (`stream=False` → typed model,
  `stream=True` → `Stream[Event]`)
- **Multipart uploads** — fields are expanded; the runtime splits
  file-like values into `files` and scalars into `data`
- **Binary downloads / uploads** — `application/octet-stream` is bytes
  in/out, not JSON-coerced
- **Webhook unwrap** — Standard Webhooks (`webhook-signature` /
  `webhook-timestamp` / `webhook-id`), HMAC-SHA256 over
  `{id}.{ts}.{body}`, `whsec_*` secrets are base64-decoded, ±300s
  replay window, constant-time compare

---

## What's not yet identical (honest gap list)

stainful is at v0.2.0 — solid but younger than Stainless. The features
below are tracked; PRs welcome.

As of v0.5 the migration-guide gap list is **empty** — every previously
deferred item has shipped. Earlier entries (`custom_casings`, rich
`APIResponse`, typed error-body models, anthropic bi-directional
pagination, alternate page class names, webhook env-var fallback,
multi-content request bodies, `.to_json()`/`.to_dict()` aliases) are
all live in the generated SDK. If you hit a real mismatch with what
Stainless was emitting for your spec, please open an issue — it's
genuinely useful signal.

---

## Verification recipe

When you regenerate with stainful, you'll want to verify the result
matches your expectations. We use these checks:

```bash
# 1. it generated
ls ./sdk/<pkg>/_client.py

# 2. it compiles
python -m compileall ./sdk -q

# 3. it type-checks (recommended)
pip install mypy
mypy ./sdk

# 4. imports resolve like Stainless's output
python -c "from <pkg> import <Brand>, <Brand>Error, NotGiven, NOT_GIVEN"

# 5. (if you have it) the existing Stainless test suite still imports
#    against stainful's output — that's the strongest cross-SDK signal
```

For OneBusAway specifically, our CI runs the **real** openai-python /
anthropic-sdk-python / onebusaway-python-sdk SDKs at pinned SHAs and
diffs the public surface — see `tests/quality/` in the stainful repo if
you want to read the harness.

---

## FAQ

**Q: Will my existing import lines break?**
A: For the symbols listed in [What's symbol-identical](#whats-symbol-identical-drop-in)
above — no. We test this by importing the real Stainless test suite
against stainful's output (29/29 for OneBusAway). For project-specific
type / variable names, check with `mypy` after regeneration.

**Q: Do I need to change my `stainless.yml`?**
A: No. We treat unrecognized keys as forward-compatible (preserved into
`extra`, no diagnostic noise). If something *isn't* honored, the gap
list above explains the practical workaround.

**Q: Is the generated runtime maintained?**
A: It's vendored into your SDK at generation time, so your published
SDK doesn't depend on stainful for runtime updates. To pick up a
runtime fix, regenerate.

**Q: What's the license?**
A: MIT, on both stainful itself and the vendored runtime it copies into
generated SDKs.

**Q: Other languages?**
A: Not yet — Python only for v0.2.0. TypeScript is on the roadmap; one
language done well first.

**Q: How do I report a gap?**
A: https://github.com/stainlu/stainful/issues — concrete examples
(your `stainless.yml` excerpt + what you got + what you expected) are
most useful.
