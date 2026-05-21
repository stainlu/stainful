"""TypeScript emitter — v0.1 slice (Stage 2 from the v0.4 roadmap).

Same IR; different renderer. Generates a TypeScript SDK that
tsc-cleanly type-checks. v0.1 scope: simple types + simple methods +
JSON request/response + path params + query params. Streaming /
pagination / multipart / discriminated unions / webhooks deferred to
v0.2-TS slices.

The `tsc` check runs against a locally-installed TypeScript (npm install
inside the temp dir). Skipped when `node` or `npm` aren't available
(local-only CI lane).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from stainful.config import load_config
from stainful.emit.typescript import emit_ts
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

EXAMPLE = Path(__file__).parent.parent / "examples" / "onebusaway"


def _gen(tmp_path: Path) -> Path:
    api = build_ir(
        load_spec(str(EXAMPLE / "openapi.yml")),
        load_config(str(EXAMPLE / "stainless.yml")),
    )
    emit_ts(api, str(tmp_path))
    return tmp_path / "onebusaway"


# ----- source-level checks (no Node dep) ------------------------------------


def test_emits_expected_files(tmp_path):
    root = _gen(tmp_path)
    assert (root / "package.json").exists()
    assert (root / "tsconfig.json").exists()
    assert (root / "src" / "index.ts").exists()
    assert (root / "src" / "client.ts").exists()
    # Vendored runtime
    for f in ("client.ts", "resource.ts", "error.ts", "index.ts"):
        assert (root / "src" / "_core" / f).exists(), f
    # One resource per top-level config resource
    assert (root / "src" / "resources" / "agency.ts").exists()


def test_client_class_uses_brand_pascalcase(tmp_path):
    """`<Brand>` matches what openai-node does — `OnebusawaySDK` matches
    the Python emitter's class name."""
    root = _gen(tmp_path)
    src = (root / "src" / "client.ts").read_text()
    assert "export class OnebusawaySDK extends BaseClient" in src
    # And the resource accessor is in place.
    assert "agency: AgencyResource;" in src


def test_resource_methods_use_camelcase(tmp_path):
    """TS convention is camelCase for method names — `current_time.retrieve`
    in Python becomes `currentTime.retrieve` in TS (resource snake_case
    stays as field name; method is camelCase). For OneBusAway most
    methods are already single-word (`retrieve`, `list`)."""
    root = _gen(tmp_path)
    src = (root / "src" / "resources" / "agency.ts").read_text()
    # The method `retrieve` is single-word, stays the same in camelCase.
    assert "retrieve(agency_id: string" in src
    # Method body calls the runtime
    assert "this._client.request<" in src
    assert "method: 'GET'" in src
    assert "path: `/api/where/agency/${agency_id}.json`" in src


def test_nested_resource_directories(tmp_path):
    """Resources with subresources live in directories (matches openai-
    node's layout). A 3-deep case like `chat.completions.messages` lives
    at `resources/chat/completions/messages.ts`, with index.ts
    re-exports for each parent dir."""
    from stainful.emit.typescript import emit_ts as _emit_ts
    api = build_ir(
        load_spec(str(
            Path(__file__).parent / "fixtures" / "chat" / "openapi.yml"
        )),
        load_config(str(
            Path(__file__).parent / "fixtures" / "chat" / "stainless-config.yml"
        )),
    )
    _emit_ts(api, str(tmp_path))
    root = tmp_path / "chat"
    # Chat has a subresource (completions) → branch shape:
    assert (root / "src" / "resources" / "chat" / "chat.ts").exists()
    assert (root / "src" / "resources" / "chat" / "index.ts").exists()
    # Completions has no subresources here → leaf in chat/:
    assert (root / "src" / "resources" / "chat" / "completions.ts").exists()
    # index.ts re-exports the class
    idx = (root / "src" / "resources" / "chat" / "index.ts").read_text()
    assert "export { ChatResource } from './chat';" in idx
    # And the imports inside chat/chat.ts go up two levels (../../_core/...).
    chat_src = (root / "src" / "resources" / "chat" / "chat.ts").read_text()
    assert "from '../../_core/resource'" in chat_src


def test_response_types_imported_precisely(tmp_path):
    """Only USED type names import from `../types` — `tsc` is strict about
    unused imports (with isolatedModules + strict)."""
    root = _gen(tmp_path)
    src = (root / "src" / "resources" / "agency.ts").read_text()
    assert "import type { AgencyRetrieveResponse } from '../types';" in src


def test_property_names_with_dots_are_quoted(tmp_path):
    """OneBusAway's `Config` has `git.branch` etc. (literal dots in the
    wire name). In TS, those must be quoted: `"git.branch"?: string`."""
    root = _gen(tmp_path)
    src = (root / "src" / "types" / "index.ts").read_text()
    assert '"git.branch"?: string' in src
    # And bare identifiers still aren't quoted.
    assert "id?: string;" in src


# ----- tsc end-to-end (requires npm) ----------------------------------------


def _has_npm() -> bool:
    return shutil.which("npm") is not None and shutil.which("node") is not None


def _tsc_clean(root: Path) -> None:
    """Install TypeScript locally and `tsc --noEmit` the generated SDK.
    Raises an assertion error if tsc reports any diagnostics."""
    subprocess.run(
        ["npm", "init", "-y"], cwd=root, check=True, capture_output=True,
    )
    subprocess.run(
        ["npm", "install", "--save-dev", "--no-audit", "--no-fund",
         "--silent", "typescript@5.6"],
        cwd=root, check=True, capture_output=True,
    )
    result = subprocess.run(
        ["npx", "tsc", "--noEmit"],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"tsc reported errors:\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_generated_sdk_tsc_clean(tmp_path):
    """OneBusAway → tsc-clean TS. This is the actual quality bar for
    the v0.1 slice."""
    _tsc_clean(_gen(tmp_path))


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_chat_fixture_tsc_clean(tmp_path):
    """The chat fixture exercises `oneOf` discriminated unions (events)
    and JSON request bodies — broader than OneBusAway's read-only GETs.
    Same emitter must handle it tsc-cleanly."""
    api = build_ir(
        load_spec(str(
            Path(__file__).parent / "fixtures" / "chat" / "openapi.yml"
        )),
        load_config(str(
            Path(__file__).parent / "fixtures" / "chat" / "stainless-config.yml"
        )),
    )
    emit_ts(api, str(tmp_path))
    _tsc_clean(tmp_path / "chat")


# ----- runtime smoke (requires npm) -----------------------------------------


_SMOKE_JS = r"""
// Generated runtime smoke test — verify the SDK actually works.
const assert = require('node:assert');
const sdk = require('./dist/index.js');

let failed = 0;
function check(name, fn) {
  return fn()
    .then(() => console.log(`  ✓ ${name}`))
    .catch((e) => { failed++; console.log(`  ✗ ${name}: ${e.message}`); });
}

const okResponse = (body) => new Response(
  JSON.stringify(body),
  { status: 200, headers: { 'content-type': 'application/json' } }
);

const errorResponse = (status, body) => new Response(
  JSON.stringify(body),
  { status, headers: { 'content-type': 'application/json' } }
);

(async () => {
  // Happy path: URL, method, auth header, JSON parsing.
  await check('happy GET → right URL/headers/parsed body', async () => {
    const calls = [];
    const fetchMock = async (url, init) => {
      calls.push({ url: String(url), method: init?.method,
                   headers: { ...(init?.headers || {}) } });
      return okResponse({
        code: 200, version: 1, currentTime: 1234, text: 'ok',
        data: { entry: { id: 'A1', name: 'T', timezone: 'UTC', url: 'x' },
                references: { agencies: [] } },
      });
    };
    const c = new sdk.OnebusawaySDK({ apiKey: 'k', fetch: fetchMock });
    const r = await c.agency.retrieve('A1');
    assert.strictEqual(r.data.entry.id, 'A1');
    assert.strictEqual(calls.length, 1);
    assert(calls[0].url.endsWith('/api/where/agency/A1.json'),
           `URL was ${calls[0].url}`);
    assert.strictEqual(calls[0].method, 'GET');
    assert.strictEqual(calls[0].headers['Authorization'], 'Bearer k');
    assert.strictEqual(calls[0].headers['Accept'], 'application/json');
  });

  // 404 → NotFoundError (typed exception, status_code attached).
  await check('404 → NotFoundError', async () => {
    const fetchMock = async () => errorResponse(404, {
      code: 404, version: 1, currentTime: 0, text: 'not found',
    });
    const c = new sdk.OnebusawaySDK({
      apiKey: 'k', maxRetries: 0, fetch: fetchMock,
    });
    try {
      await c.agency.retrieve('missing');
      throw new Error('expected NotFoundError');
    } catch (e) {
      assert(e instanceof sdk.NotFoundError, `got ${e.constructor.name}`);
      assert.strictEqual(e.status, 404);
    }
  });

  // 429 → retry-after-respected RateLimitError after retries exhaust.
  await check('429 → RateLimitError after retries', async () => {
    let n = 0;
    const fetchMock = async () => {
      n++;
      return new Response(JSON.stringify({ code: 429 }),
        { status: 429, headers: { 'content-type': 'application/json',
                                   'retry-after': '0' } });
    };
    const c = new sdk.OnebusawaySDK({
      apiKey: 'k', maxRetries: 1, fetch: fetchMock,
    });
    try {
      await c.agency.retrieve('x');
      throw new Error('expected RateLimitError');
    } catch (e) {
      assert(e instanceof sdk.RateLimitError, `got ${e.constructor.name}`);
      assert(n >= 2, `expected at least 2 fetch calls (retry); got ${n}`);
    }
  });

  if (failed > 0) {
    console.error(`\n${failed} smoke test(s) failed`);
    process.exit(1);
  }
})();
"""


_STREAMING_SMOKE_JS = r"""
// Streaming runtime smoke — verify Stream<T> yields typed events
// from an SSE response.
const assert = require('node:assert');
const sdk = require('./dist/index.js');

(async () => {
  // Mock a real SSE wire: three event blocks then [DONE].
  const sseBody =
    `data: {"id":"c1","content":"hello"}\n\n` +
    `data: {"id":"c2","content":" world"}\n\n` +
    `data: {"id":"c3","content":"!"}\n\n` +
    `data: [DONE]\n\n`;

  const fetchMock = async (_url, _init) => {
    return new Response(sseBody, {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    });
  };

  const c = new sdk.ChatSDK({ apiKey: 'k', fetch: fetchMock });
  const stream = await c.chat.completions.create({
    model: 'm', stream: true,
    messages: [{ role: 'user', content: 'hi' }],
  });
  assert(stream instanceof sdk.Stream, `expected Stream, got ${stream.constructor.name}`);

  const ids = [];
  for await (const evt of stream) {
    ids.push(evt.id);
  }
  assert.deepStrictEqual(ids, ['c1', 'c2', 'c3'], `got ${JSON.stringify(ids)}`);
  console.log('streaming smoke OK: 3 events from SSE');
})();
"""


_PAGINATION_SMOKE_JS = r"""
// Pagination runtime smoke — verify CursorPage walks pages via
// `for await`, sending the configured cursor wire param.
const assert = require('node:assert');
const sdk = require('./dist/index.js');

(async () => {
  const seen = [];
  const fetchMock = async (url, init) => {
    seen.push({ url: String(url), method: init?.method });
    const u = new URL(String(url));
    const cursor = u.searchParams.get('cursor');
    if (!cursor) {
      return new Response(
        JSON.stringify({
          data: [{ id: '1', name: 'a' }, { id: '2', name: 'b' }],
          has_more: true,
          next_cursor: 'c2',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response(
      JSON.stringify({
        data: [{ id: '3', name: 'c' }],
        has_more: false,
        next_cursor: null,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  const c = new sdk.PaginatedSDK({ apiKey: 'k', fetch: fetchMock });
  const page = await c.things.list({});
  assert(page instanceof sdk.CursorPage,
         `expected CursorPage, got ${page.constructor.name}`);

  const ids = [];
  for await (const item of page) ids.push(item.id);
  assert.deepStrictEqual(ids, ['1', '2', '3'], `got ${JSON.stringify(ids)}`);
  assert.strictEqual(seen.length, 2, `expected 2 page fetches; got ${seen.length}`);
  assert(seen[1].url.includes('cursor=c2'),
         `second-page request should carry cursor=c2; got ${seen[1].url}`);
  console.log('pagination smoke OK: walked 2 pages, 3 items');
})();
"""


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_runtime_pagination_smoke(tmp_path):
    """A `paginated: true` method returns a `CursorPage<Item>`. `for await`
    walks every page transparently, sending the configured cursor wire
    param on each subsequent request."""
    api = build_ir(
        load_spec(str(
            Path(__file__).parent / "fixtures" / "paginated" / "openapi.yml"
        )),
        load_config(str(
            Path(__file__).parent / "fixtures" / "paginated" / "stainless.yml"
        )),
    )
    emit_ts(api, str(tmp_path))
    root = tmp_path / "paginated"
    subprocess.run(["npm", "init", "-y"], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(
        ["npm", "install", "--save-dev", "--no-audit", "--no-fund",
         "--silent", "typescript@5.6"],
        cwd=root, check=True, capture_output=True,
    )
    tsc = subprocess.run(["npx", "tsc"], cwd=root, capture_output=True, text=True)
    assert tsc.returncode == 0, f"tsc failed:\n{tsc.stdout}\n{tsc.stderr}"
    (root / "smoke.js").write_text(_PAGINATION_SMOKE_JS)
    node = subprocess.run(
        ["node", "smoke.js"], cwd=root, capture_output=True, text=True,
    )
    assert node.returncode == 0, (
        f"pagination smoke failed:\n{node.stdout}\n{node.stderr}"
    )


_BINARY_UPLOAD_SMOKE_JS = r"""
// Raw octet-stream upload (S3-style PUT). `body: Uploadable` ships
// verbatim with Content-Type: application/octet-stream.
const assert = require('node:assert');
const sdk = require('./dist/index.js');

(async () => {
  const calls = [];
  const fetchMock = async (url, init) => {
    const bodyBytes = init?.body ? await new Response(init.body).arrayBuffer() : null;
    calls.push({
      url: String(url),
      contentType: init?.headers?.['Content-Type'] || '<none>',
      bytes: bodyBytes ? Array.from(new Uint8Array(bodyBytes)) : null,
    });
    return new Response(JSON.stringify({ etag: 'deadbeef' }),
      { status: 200, headers: { 'content-type': 'application/json' } });
  };
  const c = new sdk.BinaryUpload({ apiKey: 'k', fetch: fetchMock });
  const payload = new Uint8Array([0x00, 0x01, 0xff]);
  const r = await c.objects.put('bk', 'k1.bin', payload);
  assert.strictEqual(r.etag, 'deadbeef');
  assert(calls[0].url.endsWith('/buckets/bk/objects/k1.bin'),
         `url was ${calls[0].url}`);
  assert.strictEqual(calls[0].contentType, 'application/octet-stream',
                     `ct was ${calls[0].contentType}`);
  assert.deepStrictEqual(calls[0].bytes, [0x00, 0x01, 0xff],
                         `bytes mismatch: ${calls[0].bytes}`);
  console.log('binary smoke OK: octet-stream sent verbatim');
})();
"""


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_runtime_binary_upload_smoke(tmp_path):
    """Raw `application/octet-stream` upload: `body: Uploadable` param,
    bytes sent verbatim, octet-stream Content-Type set by runtime."""
    api = build_ir(
        load_spec(str(
            Path(__file__).parent / "fixtures" / "upload_binary" / "openapi.yml"
        )),
        load_config(str(
            Path(__file__).parent / "fixtures" / "upload_binary" / "stainless.yml"
        )),
    )
    emit_ts(api, str(tmp_path))
    root = tmp_path / "binary_upload"
    subprocess.run(["npm", "init", "-y"], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(
        ["npm", "install", "--save-dev", "--no-audit", "--no-fund",
         "--silent", "typescript@5.6"],
        cwd=root, check=True, capture_output=True,
    )
    tsc = subprocess.run(["npx", "tsc"], cwd=root, capture_output=True, text=True)
    assert tsc.returncode == 0, f"tsc failed:\n{tsc.stdout}\n{tsc.stderr}"
    (root / "smoke.js").write_text(_BINARY_UPLOAD_SMOKE_JS)
    node = subprocess.run(
        ["node", "smoke.js"], cwd=root, capture_output=True, text=True,
    )
    assert node.returncode == 0, (
        f"binary upload smoke failed:\n{node.stdout}\n{node.stderr}"
    )


_MULTI_CONTENT_SMOKE_JS = r"""
// Multi-content auto-detect (JSON ↔ multipart) smoke. When the user
// passes files=[...], the SDK sends multipart; else JSON.
const assert = require('node:assert');
const sdk = require('./dist/index.js');

(async () => {
  // Path A: no files → JSON wire
  {
    const calls = [];
    const fetchMock = async (url, init) => {
      calls.push({
        contentType: init?.headers?.['Content-Type'] || '<none>',
        bodyKind: init?.body?.constructor?.name || typeof init?.body,
      });
      return new Response(JSON.stringify({ id: 'sk1', name: 'n' }),
        { status: 200, headers: { 'content-type': 'application/json' } });
    };
    const c = new sdk.Skills({ apiKey: 'k', fetch: fetchMock });
    await c.skills.create({ files: [], name: 'no-files', description: 'd' });
    assert(calls[0].contentType.startsWith('application/json'),
           `expected JSON; got ${calls[0].contentType}`);
    assert.strictEqual(calls[0].bodyKind, 'String', `body was ${calls[0].bodyKind}`);
  }

  // Path B: files present → multipart wire
  {
    const calls = [];
    const fetchMock = async (url, init) => {
      calls.push({
        contentType: init?.headers?.['Content-Type'] || '<none>',
        bodyKind: init?.body?.constructor?.name || typeof init?.body,
      });
      return new Response(JSON.stringify({ id: 'sk2', name: 'n' }),
        { status: 200, headers: { 'content-type': 'application/json' } });
    };
    const c = new sdk.Skills({ apiKey: 'k', fetch: fetchMock });
    await c.skills.create({
      files: [new Blob([new Uint8Array([0xff, 0x00, 0xfe])])],
      name: 'with-files', description: 'd',
    });
    // For multipart, Content-Type either absent (fetch sets it with
    // boundary) or starts with multipart/form-data. Body is FormData.
    assert.strictEqual(calls[0].bodyKind, 'FormData',
                       `body was ${calls[0].bodyKind}`);
  }
  console.log('multi-content smoke OK: JSON when no files, multipart when files');
})();
"""


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_runtime_multi_content_smoke(tmp_path):
    """JSON ↔ multipart auto-detect via `extractFiles`. The SAME method
    call shape (`create({ files: [...], ... })`) generates a JSON wire
    when files is empty and a multipart wire when files have an
    Uploadable. Mirrors the Python multi-content test."""
    api = build_ir(
        load_spec(str(
            Path(__file__).parent / "fixtures" / "multi_content" / "openapi.yml"
        )),
        load_config(str(
            Path(__file__).parent / "fixtures" / "multi_content" / "stainless.yml"
        )),
    )
    emit_ts(api, str(tmp_path))
    root = tmp_path / "skills"
    subprocess.run(["npm", "init", "-y"], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(
        ["npm", "install", "--save-dev", "--no-audit", "--no-fund",
         "--silent", "typescript@5.6"],
        cwd=root, check=True, capture_output=True,
    )
    tsc = subprocess.run(["npx", "tsc"], cwd=root, capture_output=True, text=True)
    assert tsc.returncode == 0, f"tsc failed:\n{tsc.stdout}\n{tsc.stderr}"
    (root / "smoke.js").write_text(_MULTI_CONTENT_SMOKE_JS)
    node = subprocess.run(
        ["node", "smoke.js"], cwd=root, capture_output=True, text=True,
    )
    assert node.returncode == 0, (
        f"multi-content smoke failed:\n{node.stdout}\n{node.stderr}"
    )


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_runtime_streaming_smoke(tmp_path):
    """A `streaming:` method emits with TS overloads; calling with
    `stream: true` returns a `Stream<T>`; `for await` yields the
    typed event payloads parsed from a mock SSE response. Stops on
    `data: [DONE]`."""
    api = build_ir(
        load_spec(str(
            Path(__file__).parent / "fixtures" / "chat" / "openapi.yml"
        )),
        load_config(str(
            Path(__file__).parent / "fixtures" / "chat" / "stainless-config.yml"
        )),
    )
    emit_ts(api, str(tmp_path))
    root = tmp_path / "chat"
    subprocess.run(["npm", "init", "-y"], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(
        ["npm", "install", "--save-dev", "--no-audit", "--no-fund",
         "--silent", "typescript@5.6"],
        cwd=root, check=True, capture_output=True,
    )
    tsc = subprocess.run(["npx", "tsc"], cwd=root, capture_output=True, text=True)
    assert tsc.returncode == 0, f"tsc failed:\n{tsc.stdout}\n{tsc.stderr}"
    (root / "smoke.js").write_text(_STREAMING_SMOKE_JS)
    node = subprocess.run(
        ["node", "smoke.js"], cwd=root, capture_output=True, text=True,
    )
    assert node.returncode == 0, (
        f"streaming smoke failed:\n{node.stdout}\n{node.stderr}"
    )


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_runtime_smoke_against_mock_fetch(tmp_path):
    """The generated TS SDK actually WORKS at runtime — not just tsc-
    clean. Construct the client with an injectable mock `fetch`,
    call a method, assert the wire request shape + the parsed
    response. Plus error-path coverage (404 → NotFoundError, 429 →
    RateLimitError after retries).

    This is the v0.5-readiness bar for TypeScript: the SDK's
    runtime semantics work, not just the type system.
    """
    root = _gen(tmp_path)
    subprocess.run(
        ["npm", "init", "-y"], cwd=root, check=True, capture_output=True,
    )
    subprocess.run(
        ["npm", "install", "--save-dev", "--no-audit", "--no-fund",
         "--silent", "typescript@5.6"],
        cwd=root, check=True, capture_output=True,
    )
    # Compile to dist/
    tsc = subprocess.run(
        ["npx", "tsc"], cwd=root, capture_output=True, text=True,
    )
    assert tsc.returncode == 0, f"tsc failed:\n{tsc.stdout}\n{tsc.stderr}"
    # Drop the smoke file + run via node
    (root / "smoke.js").write_text(_SMOKE_JS)
    node = subprocess.run(
        ["node", "smoke.js"], cwd=root, capture_output=True, text=True,
    )
    assert node.returncode == 0, (
        f"runtime smoke failed:\n{node.stdout}\n{node.stderr}"
    )


# ----- webhook unwrap (Standard Webhooks) -----------------------------------


def _gen_webhooks(tmp_path: Path) -> Path:
    api = build_ir(
        load_spec(str(
            Path(__file__).parent / "fixtures" / "webhooks" / "openapi.yml"
        )),
        load_config(str(
            Path(__file__).parent / "fixtures" / "webhooks" / "stainless.yml"
        )),
    )
    emit_ts(api, str(tmp_path))
    return tmp_path / "hooks"


def test_webhook_unwrap_emits_typed_event_union_and_methods(tmp_path):
    """`type: webhook_unwrap` emits a `WebhooksUnwrapEvent` union alias
    and `unwrap()` + `verifySignature()` methods on the Webhooks
    resource. No HTTP — just runtime-helper calls."""
    root = _gen_webhooks(tmp_path)
    src = (root / "src" / "resources" / "webhooks.ts").read_text()
    # Type alias hoisted above the class, union of the configured events.
    assert "export type WebhooksUnwrapEvent =" in src
    assert "OrderCreatedEvent" in src
    assert "OrderCancelledEvent" in src
    # Both methods present, calling the runtime helpers.
    assert "async unwrap(" in src
    assert "async verifySignature(" in src
    assert "_webhookUnwrapEvent<WebhooksUnwrapEvent>" in src
    assert "_webhookVerifySignature(" in src
    # Conditional imports threaded in.
    assert "from '../_core/webhooks'" in src
    # Root index re-exports the typed-error class for caller `instanceof`.
    idx = (root / "src" / "index.ts").read_text()
    assert "InvalidWebhookSignatureError" in idx


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_webhook_unwrap_tsc_clean(tmp_path):
    """The webhooks fixture must tsc-clean. Typed event union, runtime
    imports, and Promise return types all need to compose without errors."""
    _tsc_clean(_gen_webhooks(tmp_path))


_WEBHOOK_SMOKE_JS = r"""
// Standard Webhooks runtime smoke — sign a payload with our own helper
// (so the wire shape exactly matches what the SDK expects), then unwrap.
const assert = require('node:assert');
const crypto = require('node:crypto');
const sdk = require('./dist/index.js');

const SECRET = 'sw_test_secret_abc123';
const WEBHOOK_ID = 'msg_abc123';

function signHeaders(payload, secret, ts = Math.floor(Date.now() / 1000)) {
  const signed = `${WEBHOOK_ID}.${ts}.${payload}`;
  const sig = crypto.createHmac('sha256', secret)
    .update(signed).digest('base64');
  return {
    'webhook-id': WEBHOOK_ID,
    'webhook-timestamp': String(ts),
    'webhook-signature': `v1,${sig}`,
  };
}

(async () => {
  const c = new sdk.Hooks({ apiKey: 'k' });

  // Happy path: good signature → typed event back
  {
    const payload = JSON.stringify({ type: 'order.created', id: 'o1' });
    const headers = signHeaders(payload, SECRET);
    const evt = await c.webhooks.unwrap(payload, headers, { secret: SECRET });
    assert.strictEqual(evt.type, 'order.created', `type was ${evt.type}`);
    assert.strictEqual(evt.id, 'o1');
  }

  // Variant: second event type round-trips
  {
    const payload = JSON.stringify({ type: 'order.cancelled', id: 'o2' });
    const headers = signHeaders(payload, SECRET);
    const evt = await c.webhooks.unwrap(payload, headers, { secret: SECRET });
    assert.strictEqual(evt.type, 'order.cancelled');
  }

  // Bad signature → InvalidWebhookSignatureError
  {
    const payload = JSON.stringify({ type: 'order.created', id: 'x' });
    const headers = signHeaders(payload, 'wrong-secret');
    try {
      await c.webhooks.unwrap(payload, headers, { secret: SECRET });
      throw new Error('expected InvalidWebhookSignatureError');
    } catch (e) {
      assert(e instanceof sdk.InvalidWebhookSignatureError,
             `got ${e.constructor.name}`);
    }
  }

  // Stale timestamp → InvalidWebhookSignatureError
  {
    const stale = Math.floor(Date.now() / 1000) - 3600;  // 1h old
    const payload = JSON.stringify({ type: 'order.created', id: 'x' });
    const headers = signHeaders(payload, SECRET, stale);
    try {
      await c.webhooks.unwrap(payload, headers, { secret: SECRET });
      throw new Error('expected InvalidWebhookSignatureError');
    } catch (e) {
      assert(e instanceof sdk.InvalidWebhookSignatureError,
             `got ${e.constructor.name}: ${e.message}`);
    }
  }

  // Missing header → InvalidWebhookSignatureError
  {
    const payload = JSON.stringify({ type: 'order.created', id: 'x' });
    const headers = signHeaders(payload, SECRET);
    delete headers['webhook-signature'];
    try {
      await c.webhooks.unwrap(payload, headers, { secret: SECRET });
      throw new Error('expected InvalidWebhookSignatureError');
    } catch (e) {
      assert(e instanceof sdk.InvalidWebhookSignatureError,
             `got ${e.constructor.name}: ${e.message}`);
    }
  }

  // `whsec_<b64>` prefix: secret should be base64-decoded
  {
    const rawKey = crypto.randomBytes(32);
    const whsecSecret = `whsec_${rawKey.toString('base64')}`;
    const payload = JSON.stringify({ type: 'order.created', id: 'wh1' });
    const ts = Math.floor(Date.now() / 1000);
    const signed = `${WEBHOOK_ID}.${ts}.${payload}`;
    const sig = crypto.createHmac('sha256', rawKey)
      .update(signed).digest('base64');
    const headers = {
      'webhook-id': WEBHOOK_ID,
      'webhook-timestamp': String(ts),
      'webhook-signature': `v1,${sig}`,
    };
    const evt = await c.webhooks.unwrap(payload, headers, { secret: whsecSecret });
    assert.strictEqual(evt.id, 'wh1');
  }

  // verifySignature returns void on success (no parse).
  {
    const payload = JSON.stringify({ type: 'order.created', id: 'vs1' });
    const headers = signHeaders(payload, SECRET);
    const r = await c.webhooks.verifySignature(payload, headers, { secret: SECRET });
    assert.strictEqual(r, undefined);
  }

  console.log('webhook smoke OK: 6 scenarios');
})();
"""


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_runtime_webhook_unwrap_smoke(tmp_path):
    """Standard Webhooks at runtime: HMAC-SHA256 + base64 + `v1,<sig>`
    header. Sign payloads with node's crypto so the wire matches what
    the SDK expects, then unwrap. Covers happy, bad-sig, stale, missing-
    header, `whsec_` base64 secret, and verifySignature."""
    root = _gen_webhooks(tmp_path)
    subprocess.run(["npm", "init", "-y"], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(
        ["npm", "install", "--save-dev", "--no-audit", "--no-fund",
         "--silent", "typescript@5.6"],
        cwd=root, check=True, capture_output=True,
    )
    tsc = subprocess.run(["npx", "tsc"], cwd=root, capture_output=True, text=True)
    assert tsc.returncode == 0, f"tsc failed:\n{tsc.stdout}\n{tsc.stderr}"
    (root / "smoke.js").write_text(_WEBHOOK_SMOKE_JS)
    node = subprocess.run(
        ["node", "smoke.js"], cwd=root, capture_output=True, text=True,
    )
    assert node.returncode == 0, (
        f"webhook smoke failed:\n{node.stdout}\n{node.stderr}"
    )
