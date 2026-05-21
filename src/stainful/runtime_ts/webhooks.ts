// Generated SDK runtime — Standard Webhooks signature verification.
//
// Mirrors the Python runtime's `_webhooks.py`. Wire shape pinned by
// the oracle (openai-node's `resources/webhooks/webhooks.ts` + the
// Standard Webhooks spec at standardwebhooks.com):
//
//   • Headers:   webhook-signature, webhook-timestamp, webhook-id
//   • Signed:    f"{webhook_id}.{timestamp}.{body}"
//   • Sig:       HMAC-SHA256, base64-encoded, `v1,<base64>` header
//                (space-separated; any match wins)
//   • Secret:    if `whsec_<b64>` → base64-decode; else UTF-8 bytes
//   • Replay:    timestamp must be within ±tolerance seconds
//
// Uses Web Crypto (`crypto.subtle.sign`) — available in Node 20+ as a
// global, in modern browsers, and in edge runtimes. Constant-time
// comparison via `crypto.subtle.timingSafeEqual` where available,
// falling back to a sequence-of-byte-XOR loop on browsers that don't
// expose `timingSafeEqual`.

import { InvalidWebhookSignatureError } from './error';
export { InvalidWebhookSignatureError } from './error';

export type WebhookHeaders =
  | Record<string, string | string[] | undefined>
  | Headers
  | Map<string, string>;

export interface VerifyOptions {
  /** Replay window in seconds. Default: 300 (5 minutes). */
  tolerance?: number;
}

/**
 * Verify a Standard Webhooks signature + timestamp. Throws
 * `InvalidWebhookSignatureError` on any mismatch.
 */
export async function verifySignature(
  payload: string | Uint8Array,
  headers: WebhookHeaders,
  secret: string,
  options: VerifyOptions = {},
): Promise<void> {
  if (!secret) {
    throw new Error('The webhook secret must be provided via `secret`.');
  }
  const tolerance = options.tolerance ?? 300;
  const signatureHeader = getRequiredHeader(headers, 'webhook-signature');
  const timestamp = getRequiredHeader(headers, 'webhook-timestamp');
  const webhookId = getRequiredHeader(headers, 'webhook-id');

  const ts = parseInt(timestamp, 10);
  if (!Number.isFinite(ts)) {
    throw new InvalidWebhookSignatureError('Invalid webhook timestamp format');
  }
  const now = Math.floor(Date.now() / 1000);
  if (now - ts > tolerance) {
    throw new InvalidWebhookSignatureError('Webhook timestamp is too old');
  }
  if (ts > now + tolerance) {
    throw new InvalidWebhookSignatureError('Webhook timestamp is too new');
  }

  // `v1,<base64>` (preferred); accept legacy bare-base64 too.
  const signatures = signatureHeader.split(/\s+/).filter(Boolean).map((p) =>
    p.startsWith('v1,') ? p.substring(3) : p,
  );

  const body = typeof payload === 'string' ? payload
    : new TextDecoder().decode(payload);
  const signedPayload = `${webhookId}.${timestamp}.${body}`;
  const expected = await hmacSha256Base64(decodeSecret(secret), signedPayload);

  if (!signatures.some((s) => timingSafeEqualString(expected, s))) {
    throw new InvalidWebhookSignatureError(
      'The given webhook signature does not match the expected signature',
    );
  }
}

/**
 * Verify the signature and JSON-parse the payload. Returns the
 * decoded event (typed by the caller; the generated unwrap method
 * casts to the typed union from `event_types`).
 */
export async function unwrapEvent<T = unknown>(
  payload: string | Uint8Array,
  headers: WebhookHeaders,
  secret: string,
  options: VerifyOptions = {},
): Promise<T> {
  await verifySignature(payload, headers, secret, options);
  const body = typeof payload === 'string' ? payload
    : new TextDecoder().decode(payload);
  return JSON.parse(body) as T;
}

// ----- internals ---------------------------------------------------

function decodeSecret(secret: string): Uint8Array {
  if (secret.startsWith('whsec_')) {
    return base64ToBytes(secret.substring(6));
  }
  return new TextEncoder().encode(secret);
}

// Web-standard base64 helpers — `atob`/`btoa` are global in Node 16+,
// modern browsers, and edge runtimes. Avoids a hard dep on
// `@types/node`'s `Buffer` declaration just for HMAC encoding.
function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]!);
  return btoa(bin);
}

async function hmacSha256Base64(
  keyBytes: Uint8Array, signedPayload: string,
): Promise<string> {
  const cryptoObj = (globalThis as unknown as { crypto?: Crypto }).crypto;
  if (!cryptoObj?.subtle) {
    throw new Error(
      'Webhook signature verification requires Web Crypto (crypto.subtle).',
    );
  }
  const key = await cryptoObj.subtle.importKey(
    'raw', keyBytes,
    { name: 'HMAC', hash: 'SHA-256' },
    false, ['sign'],
  );
  const sig = await cryptoObj.subtle.sign(
    'HMAC', key, new TextEncoder().encode(signedPayload),
  );
  return bytesToBase64(new Uint8Array(sig));
}

function timingSafeEqualString(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

function getRequiredHeader(headers: WebhookHeaders, name: string): string {
  const lower = name.toLowerCase();
  // `Headers` instance
  if (typeof Headers !== 'undefined' && headers instanceof Headers) {
    const v = headers.get(name);
    if (v == null) {
      throw new InvalidWebhookSignatureError(`Missing required header: ${name}`);
    }
    return v;
  }
  // `Map`
  if (headers instanceof Map) {
    for (const [k, v] of headers.entries()) {
      if (k.toLowerCase() === lower) return v;
    }
    throw new InvalidWebhookSignatureError(`Missing required header: ${name}`);
  }
  // Plain object — case-insensitive lookup
  const obj = headers as Record<string, string | string[] | undefined>;
  for (const k of Object.keys(obj)) {
    if (k.toLowerCase() === lower) {
      const v = obj[k];
      if (v == null) break;
      return Array.isArray(v) ? v[0]! : v;
    }
  }
  throw new InvalidWebhookSignatureError(`Missing required header: ${name}`);
}
