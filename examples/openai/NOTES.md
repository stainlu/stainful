# examples/openai/

A real-world stress test: can stainful generate a working OpenAI SDK from
the public Stainless-processed openai-openapi spec?

## What's here

- `openapi.yml` — the **Stainless-processed** openai-openapi spec, pinned by
  SHA in its source URL (committed for reproducibility — see Source below).
- `stainless.yml` — a hand-written stainful config. **Not** OpenAI's real
  Stainless config (private). Models the resource tree using endpoints
  observed in the spec + matched against `tests/oracles/openai-python/`
  resource layout. Covers a representative slice (chat.completions,
  embeddings, files, audio.speech, fine_tuning.jobs, webhooks, models)
  to exercise every capability stainful v0.2.0 supports — streaming, JSON
  body, multipart upload, binary download, cursor pagination, webhook
  unwrap.
- `sdk/` — generated, **gitignored**. Regenerate with the command below.

## Generate / regenerate

```bash
uv run stainful generate \
  --spec examples/openai/openapi.yml \
  --config examples/openai/stainless.yml \
  --out  examples/openai/sdk
```

## Source

`openapi.yml` was fetched from the Stainless openapi-specs CDN. The URL,
which embeds a SHA-256 of the spec content (so the file is content-pinned
even before we commit it), comes from `openai-python/.stats.yml`:

```
https://storage.googleapis.com/stainless-sdk-openapi-specs/openai/openai-50d816559ef0935e64d07789ff936a2b762e26ab0714a2fa6bc06d06d4484294.yml
```

We commit it (rather than fetch on-demand) because the Stainless hosted
products are winding down (Anthropic acquisition, 2026-05-18) — that bucket
URL is not guaranteed to remain reachable.

## Honest scope

This is a **generator-intrinsic** test: the SDK we emit is compared for
shape against the real openai-python (in `tests/oracles/`), but byte-for-
byte parity isn't the goal — OpenAI's real Stainless config is private, so
class names / model names / module layout will differ in places that pure
config (not generator) controls. The goal is: stainful survives a real
163-path, 983-schema spec and emits a mypy-clean, importable SDK whose
public method surfaces match what an OpenAI user expects.

Not affiliated with OpenAI, Stainless, or Anthropic.
