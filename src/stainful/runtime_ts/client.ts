// Generated SDK runtime — base HTTP client.
//
// Modeled on openai-node's `client.ts` (the cross-SDK shape is the
// drop-in contract). Uses native `fetch` (Node 18+, modern browsers,
// edge runtimes) — no dependency hell. Retries with backoff + jitter +
// `Retry-After` + idempotency on retried writes. Typed-error mapping.

import {
  APIConnectionError,
  APITimeoutError,
  APIError,
  APIResponseValidationError,
  statusErrorFor,
} from './error';

export type Headers = Record<string, string>;
export type Query = Record<string, string | number | boolean | undefined | null>;
export type Body = Record<string, unknown>;

export interface RequestOptions {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: string;
  query?: Query;
  body?: unknown;
  headers?: Headers;
  files?: Array<[string, unknown]>;   // multipart parts (multi-content auto-detect)
  timeout?: number;                    // ms
  signal?: AbortSignal;
}

export interface ClientOptions {
  apiKey?: string;
  baseURL?: string;
  timeout?: number;                    // ms; default 60_000
  maxRetries?: number;                 // default 2
  fetch?: typeof fetch;                // dependency-injectable for tests
  defaultHeaders?: Headers;
  defaultQuery?: Query;
}

const RETRY_STATUSES = new Set([408, 409, 429]);
const INITIAL_RETRY_DELAY = 500;       // ms
const MAX_RETRY_DELAY = 8_000;         // ms

export abstract class BaseClient {
  protected readonly _baseURL: string;
  protected readonly _apiKey: string | undefined;
  protected readonly _timeout: number;
  protected readonly _maxRetries: number;
  protected readonly _fetch: typeof fetch;
  protected readonly _defaultHeaders: Headers;
  protected readonly _defaultQuery: Query;

  constructor(opts: ClientOptions = {}) {
    this._baseURL = (opts.baseURL ?? this.defaultBaseURL()).replace(/\/$/, '');
    this._apiKey = opts.apiKey;
    this._timeout = opts.timeout ?? 60_000;
    this._maxRetries = opts.maxRetries ?? 2;
    this._fetch = opts.fetch ?? fetch;
    this._defaultHeaders = opts.defaultHeaders ?? {};
    this._defaultQuery = opts.defaultQuery ?? {};
  }

  /** Each generated brand client overrides this with its env's prod URL. */
  protected abstract defaultBaseURL(): string;

  protected authHeaders(): Headers {
    return this._apiKey ? { Authorization: `Bearer ${this._apiKey}` } : {};
  }

  /** Build the URL with query string. */
  private buildURL(path: string, query?: Query): string {
    const url = new URL(
      path.startsWith('http') ? path : `${this._baseURL}/${path.replace(/^\//, '')}`,
    );
    const merged: Query = { ...this._defaultQuery, ...(query ?? {}) };
    for (const [k, v] of Object.entries(merged)) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, String(v));
    }
    return url.toString();
  }

  /** Run an HTTP request with retries + typed-error mapping. */
  async request<T>(opts: RequestOptions): Promise<T> {
    const url = this.buildURL(opts.path, opts.query);
    let lastErr: unknown;
    for (let attempt = 0; attempt <= this._maxRetries; attempt++) {
      const headers: Headers = {
        Accept: 'application/json',
        ...this.authHeaders(),
        ...this._defaultHeaders,
        ...(opts.headers ?? {}),
      };
      let body: BodyInit | undefined;
      if (opts.files && opts.files.length > 0) {
        const fd = new FormData();
        if (opts.body && typeof opts.body === 'object') {
          for (const [k, v] of Object.entries(opts.body as Record<string, unknown>)) {
            if (v === undefined || v === null) continue;
            fd.append(k, typeof v === 'string' ? v : JSON.stringify(v));
          }
        }
        for (const [name, value] of opts.files) {
          fd.append(name, value as Blob);
        }
        body = fd;
        // Do NOT set Content-Type — `fetch` adds the boundary itself.
      } else if (opts.body !== undefined && opts.body !== null) {
        body = JSON.stringify(opts.body);
        headers['Content-Type'] = headers['Content-Type'] ?? 'application/json';
      }
      if (attempt > 0 && (opts.method === 'POST' || opts.method === 'PATCH')) {
        // Auto idempotency-key on retried writes (matches Python runtime).
        headers['Idempotency-Key'] = headers['Idempotency-Key'] ?? this.randomKey();
      }
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), opts.timeout ?? this._timeout);
      try {
        const resp = await this._fetch(url, {
          method: opts.method,
          headers,
          body,
          signal: opts.signal ?? ac.signal,
        });
        if (resp.ok) {
          const text = await resp.text();
          if (!text) return undefined as T;
          const data = JSON.parse(text);
          return this.processResponseData<T>(data, resp);
        }
        if (attempt < this._maxRetries && this.shouldRetry(resp.status)) {
          await this.sleep(this.retryDelay(resp, attempt));
          continue;
        }
        const text = await resp.text();
        let errBody: object | undefined;
        try {
          errBody = text ? JSON.parse(text) : undefined;
        } catch {
          errBody = text ? { message: text } : undefined;
        }
        const headerObj: Headers = {};
        resp.headers.forEach((v, k) => { headerObj[k] = v; });
        throw statusErrorFor(resp.status, errBody, headerObj);
      } catch (e) {
        if (e instanceof APIError) throw e;
        if ((e as { name?: string }).name === 'AbortError') {
          lastErr = new APITimeoutError();
        } else {
          lastErr = new APIConnectionError({ message: (e as Error).message, cause: e as Error });
        }
        if (attempt < this._maxRetries) {
          await this.sleep(this.retryDelay(undefined, attempt));
          continue;
        }
        throw lastErr;
      } finally {
        clearTimeout(timer);
      }
    }
    throw lastErr ?? new APIConnectionError({ message: 'unreachable' });
  }

  protected processResponseData<T>(data: unknown, _resp: Response): T {
    // Generated method-specific cast happens at the call site; the
    // runtime just hands back the parsed JSON. Validation lives in the
    // typed interfaces emitted alongside the method (compile-time
    // checks only — no runtime schema validation in v0.5-TS, by design).
    return data as T;
  }

  private shouldRetry(status: number): boolean {
    return RETRY_STATUSES.has(status) || status >= 500;
  }

  private retryDelay(resp: Response | undefined, attempt: number): number {
    if (resp) {
      const ra = resp.headers.get('retry-after');
      if (ra && /^\d+$/.test(ra)) {
        return Math.min(Number(ra) * 1000, MAX_RETRY_DELAY);
      }
    }
    const base = Math.min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY);
    return base * (0.5 + Math.random() / 2);
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((r) => setTimeout(r, ms));
  }

  private randomKey(): string {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return `stainful-retry-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`;
  }
}
