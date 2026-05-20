# HN — Show HN draft

**Tone notes:** Show HN posts that land use direct first-person prose,
say what's running, and credit prior art honestly. HN downvotes
breathless marketing language ("revolutionary", "game-changing", "first
of its kind"). Lead with the wind-down hook (it's the reason to care
right now), then the artifacts you can see, then the honest scope.

Post `https://github.com/stainlu/stainful` as the URL; the body fills
in below. Posting Tue–Thu 8–10am PT lands best on HN.

---

## Title

```
Show HN: stainful – open-source SDK + docs + MCP server from one stainless.yml
```

Alternates if you want to lean harder on the wind-down angle:

```
Show HN: stainful – open-source alternative to Stainless after the Anthropic acquisition
Show HN: Stainful – OSS continuation path for stainless.yml after the hosted product wound down
```

## Body

```
Anthropic acquired Stainless this month and announced their hosted
SDK-generator product is winding down. If you've been using a
`stainless.yml` to generate your Python SDK – OpenAI, Cloudflare,
Increase, Lithic, Modern Treasury, anyone whose SDKs were built that
way – you have an open question about where the regenerate button
goes next.

stainful is a fully open-source, MIT-licensed CLI that reads the same
`stainless.yml` + your OpenAPI 3.x spec and emits three artifacts:

  stainful generate – an idiomatic Python SDK (pydantic v2 models,
                      sync + async, retries with backoff + jitter +
                      Retry-After + idempotency keys, typed errors,
                      auto-pagination, SSE streaming, multipart,
                      binary up/down, webhook unwrap with Standard
                      Webhooks signature verify)
  stainful docs     – a Stainless-shaped api.md (per-resource sections,
                      Methods lists with verb+path, links into the
                      generated SDK; Mintlify-compatible)
  stainful mcp      – a Model Context Protocol server (one MCP tool
                      per HTTP method, runs over stdio, drops into
                      Claude Desktop / Cline / mcp-cli)

Drop-in symbol contract with what Stainless was emitting: the client
class name, the typed exception hierarchy (`RateLimitError` etc.),
`NotGiven` / `NOT_GIVEN` / `Omit`, `SyncCursorPage` (and the spec-
specific aliases – `SyncTokenPage`, `SyncNextCursorPage`, …), resource
class naming, `<pkg>.types.shared.ErrorObject`, `with_raw_response.*`
returning a real `APIResponse[T]`. Existing `import` lines and
`except` clauses generally don't change.

Quality is measured against the real Stainless-generated SDKs at
pinned SHAs, CI-gated:

  • 29/29 (100%) of Stainless's own OneBusAway test files import
    unchanged against stainful's output
  • The full public openai-openapi spec (162 paths, 983 schemas)
    generates a mypy-clean SDK – ~22 resources, 172 files, exercising
    every capability stainful supports: streaming, JSON, multipart,
    raw binary upload, audio binary download, cursor pagination
    (config-driven wire param), anthropic-shape bi-directional
    pagination, typed discriminated-union responses, nested
    subresources, webhook unwrap
  • 118 tests, mypy 0 on 253 generated source files, CI green on
    py3.10–3.12

Honest scope:

  • Python only; TypeScript is the next wedge (not today)
  • Multi-content request bodies (one operation declaring JSON OR
    multipart OR form-urlencoded on the same op) still pick the
    first match – no public Stainless oracle to verify the exact
    surface design; documented in the migration guide
  • Not affiliated with Stainless, OpenAI, or Anthropic

  pip install stainful
  stainful generate --spec openapi.yml --config stainless.yml --out ./sdk

Repo (MIT): https://github.com/stainlu/stainful
PyPI: https://pypi.org/project/stainful/

Feedback, bug reports, "this is what's missing for my use case" – all
welcome.
```

## Likely top comments to be ready for

- **"Why not just Fern / OpenAPI Generator?"** Answer: drop-in for the
  *exact* `stainless.yml` format Stainless customers already have, plus
  the SDK quality bar (auto-pagination, typed errors, retries, idempotency)
  that OpenAPI Generator doesn't ship. Fern is open-core; stainful is
  fully OSS, no SaaS, no account.
- **"How close to Stainless's actual output?"** Answer with the
  29/29 number + mypy-clean openai SDK from the public spec. Be honest
  about the still-deferred multi-content case.
- **"Will you support <X> language?"** Honest: Python only for v0.4.
  TypeScript is the next wedge. The IR is language-agnostic, so the
  emitter sit is the real work.
- **"This isn't really 'the open-source Stainless' because Stainless
  also does X / Y / Z."** Honest acknowledgment of breadth difference
  (their 9 languages, MCP-front, Mintlify docs site infra, hosted CI/CD
  per-language SDK PR pipeline) — call out the wedge: one language done
  well first, broaden over time.
