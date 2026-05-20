# stainful

**The open-source Stainless.** Generate an idiomatic Python SDK from an OpenAPI
spec and a `stainless.yml` — open source, runs locally and in CI, no hosted service.

[![License](https://img.shields.io/badge/license-MIT-3da639?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![CI](https://img.shields.io/github/actions/workflow/status/stainlu/stainful/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/stainlu/stainful/actions/workflows/ci.yml)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-7c3aed?style=flat-square)](CONTRIBUTING.md)

<img src="assets/architecture.png" alt="stainful — OpenAPI spec + stainless.yml → resolved IR → idiomatic Python SDK" width="100%">

---

stainful turns an **OpenAPI 3.x spec** and a **Stainless config** into a Python SDK
that reads like it was written by hand — typed models, real error classes,
retries, auto-pagination, streaming, sync **and** async. It reuses the
`stainless.yml` format, so if you already have one, you can point stainful at it
as-is.

> **Migrating from Stainless?** Anthropic acquired Stainless and is winding
> down the hosted SDK generator. stainful is a drop-in continuation path —
> see [`docs/migrating-from-stainless.md`](docs/migrating-from-stainless.md)
> for the step-by-step (it should be a few minutes).

## Features

- 🧬 **Typed everything** — pydantic v2 models, real discriminated unions from `oneOf`
- 🔁 **Auto-pagination** — `for item in client.things.list(): ...`
- 🛡️ **Typed errors** — `except RateLimitError:` instead of checking status codes
- 🔄 **Resilient** — retries with exponential backoff + jitter, `Retry-After`, idempotency keys
- 📡 **Streaming** — typed Server-Sent Events, identical surface in sync and async
- 🎯 **Precise optionality** — `required`, `optional`, and `nullable` stay distinct
- 🧭 **Domain-shaped clients** — `client.chat.completions.create(...)`, not flat stubs
- ⚡ **Sync + async** generated from one model
- 📦 **Self-contained output** — the generated SDK depends only on `httpx` + `pydantic`

## Quickstart

```bash
pip install stainful

# generate an idiomatic Python SDK from your OpenAPI spec + stainless.yml
stainful generate --spec openapi.yml --config stainless.yml --out ./sdk
```

The generated SDK feels like an official client:

```python
from onebusaway import OnebusawaySDK

client = OnebusawaySDK(api_key="...")          # or set ONEBUSAWAY_API_KEY
agency = client.agency.retrieve("1")           # typed, retried, idiomatic
print(agency.data.entry.name)
```

Streaming, async, and typed errors work the way you'd expect:

```python
import asyncio
from chat import AsyncChatSDK
from chat import RateLimitError

async def main():
    client = AsyncChatSDK(api_key="...")
    try:
        stream = await client.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "hi"}], stream=True
        )
        async for chunk in stream:
            print(chunk.delta, end="")
    except RateLimitError as e:
        print("rate limited:", e.request_id)

asyncio.run(main())
```

## What you get vs. a mechanical generator

```python
# typical OpenAPI generator                      # stainful
api = DefaultApi(ApiClient(cfg))                  client = OnebusawaySDK()
resp = api.agency_agency_id_json_get(id)          agency = client.agency.retrieve(id)
# loosely typed, no retries, no error classes,    # typed model, retries, typed errors,
# you hand-write the pagination loop              # auto-pagination, request id, async twin
```

## How it works

The pipeline is shown above: an OpenAPI spec and `stainless.yml` are parsed,
resolved, and lowered into an intermediate representation, which the emitter
renders into a Python SDK over a vendored runtime.

The intermediate representation is a fully-resolved, language-agnostic model:
`allOf` is merged, `oneOf` becomes a real tagged union, and optionality is
three-valued. The emitter is a thin renderer over a hand-written runtime, so the
idiomatic behavior lives in audited code rather than per-endpoint templates.

## How it compares

|                                   | OpenAPI Generator | Fern | Stainless | stainful |
|-----------------------------------|:-:|:-:|:-:|:-:|
| Open source                       | ✅ | ✅ | — | ✅ |
| Runs fully locally, no account    | ✅ | ✅ | — | ✅ |
| Reads the `stainless.yml` format  | — | — | ✅ | ✅ |
| Idiomatic output (pagination, typed errors, streaming) | — | ✅ | ✅ | ✅ |

stainful's niche: idiomatic, fully-open, and a drop-in for the Stainless config
you may already have. Different tools fit different teams — this one is for
people who want that workflow without a hosted service.

## Project layout

| Path | What |
|---|---|
| `src/stainful/config/`  | `stainless.yml` loader with precise, located diagnostics |
| `src/stainful/openapi/` | OpenAPI 3.x loader + cycle-safe `$ref` / `allOf` resolver |
| `src/stainful/ir/`      | the intermediate representation |
| `src/stainful/emit/`    | the Python emitter |
| `src/stainful/runtime/` | the hand-written runtime vendored into generated SDKs |
| `tests/fixtures/`       | conformance fixtures (chat / paginated / multipart / binary / webhooks / …) |
| `examples/onebusaway/`  | committed dogfood — regenerated SDK is bit-stable; CI guards it |
| `examples/openai/`      | real-world test: the public openai-openapi spec → mypy-clean SDK |
| `docs/`                 | migration guide and other docs |

## Status

**v0.2.0 on PyPI.** Generates complete sync + async SDKs, verified against
the real Stainless-generated SDKs at pinned SHAs in CI:

- **OneBusAway:** **29/29 (100%)** of Stainless's own `OneBusAway/python-sdk`
  test files import unchanged against stainful's output; generated SDK is
  mypy-clean; regeneration is byte-stable (the repo dogfoods itself).
- **OpenAI:** the public `openai-openapi` spec (162 paths, 983 schemas)
  generates a **mypy-clean** SDK — see [`examples/openai/`](examples/openai/)
  and [`docs/migrating-from-stainless.md`](docs/migrating-from-stainless.md)
  for what's verified and what's still on the gap list.

End-to-end behavioral conformance covers: cursor pagination (wire param
config-driven — `?after=<last_id>` matches openai), SSE streaming with
`@overload` pairs, multipart / file upload, binary download
(`audio/mpeg`, `octet-stream`), raw binary request bodies (S3-style PUT),
typed webhook unwrap (Standard Webhooks scheme).

Not yet at full parity: `.to_json()/.to_dict()` model helpers, richer
`APIResponse`, typed error-body models, `custom_casings`, anthropic
bi-directional pagination, multi-content request bodies. The migration
guide has the honest workaround for each.

**Roadmap:** Python SDK → MCP server from the same model → a second language →
docs site. One language done well first.

## Contributing

PRs welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md).

```bash
git clone https://github.com/stainlu/stainful && cd stainful
uv venv && uv pip install -e ".[dev,generated-runtime]"
uv run pytest -q
uv run ruff check src tests

# regenerate the dogfood SDK (the repo dogfoods itself; CI fails if a
# regeneration changes a byte — see examples/onebusaway/):
uv run stainful generate \
  --spec   examples/onebusaway/openapi.yml \
  --config examples/onebusaway/stainless.yml \
  --out    examples/onebusaway/sdk
```

## License

[MIT](LICENSE). The vendored runtime ships inside generated SDKs under the same
terms.
