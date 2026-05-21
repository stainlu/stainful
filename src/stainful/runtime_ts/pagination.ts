// Generated SDK runtime — cursor pagination.
//
// Symbol-compatible with openai-node's `CursorPage<T>`: an
// `AsyncIterable<T>` that walks every page on demand. Users write
//
//     for await (const item of await client.things.list()) { ... }
//
// and the runtime fetches subsequent pages transparently. The
// per-method pagination_cfg (wire param + response field) comes from
// the stainless.yml config — mirrors the Python runtime's
// `_pagination_cfg` mechanism so the same algorithm covers all the
// forward-only cursor variants (openai's `after=<last_id>`,
// anthropic's `page_token=<next_page>`, etc.).

import type { BaseClient } from './client';

export interface PaginationConfig {
  /** Wire param name carrying the cursor on next-page requests. */
  cursorParam: string;
  /** Response field that carries the next cursor (e.g. `next_cursor`,
   *  `last_id`, `next_page`). When unset/absent, falls back to the
   *  last item's `id`. */
  cursorResponseField?: string;
}

/** Shape of the raw paginated JSON response (`{data: [...], ...}`). */
export interface PagedResponseBody<T> {
  data: T[];
  has_more?: boolean;
  [k: string]: unknown;
}

export class CursorPage<T> implements AsyncIterable<T> {
  data: T[];
  private _client: BaseClient;
  private _path: string;
  private _cfg: PaginationConfig;
  private _raw: PagedResponseBody<T>;

  constructor(
    client: BaseClient,
    path: string,
    cfg: PaginationConfig,
    response: PagedResponseBody<T>,
  ) {
    this._client = client;
    this._path = path;
    this._cfg = cfg;
    this._raw = response;
    this.data = response.data ?? [];
  }

  /** True when the server signaled there are more pages. */
  hasNextPage(): boolean {
    if (this._raw.has_more === false) return false;
    if (this.data.length === 0) return false;
    return this._nextCursor() !== null;
  }

  /** Fetch the next page; returns `null` when exhausted. */
  async nextPage(): Promise<CursorPage<T> | null> {
    const cursor = this._nextCursor();
    if (cursor === null) return null;
    // Re-request with the cursor merged into the query.
    const next = await this._client.request<PagedResponseBody<T>>({
      method: 'GET',
      path: this._path,
      query: { [this._cfg.cursorParam]: cursor },
    });
    return new CursorPage<T>(this._client, this._path, this._cfg, next);
  }

  async *[Symbol.asyncIterator](): AsyncGenerator<T, void, void> {
    let page: CursorPage<T> | null = this;
    while (page) {
      for (const item of page.data) yield item;
      page = await page.nextPage();
    }
  }

  private _nextCursor(): string | null {
    if (this._raw.has_more === false || this.data.length === 0) return null;
    // Configured response field wins (e.g. `next_cursor`, `last_id`).
    if (this._cfg.cursorResponseField) {
      const v = this._raw[this._cfg.cursorResponseField];
      if (typeof v === 'string' && v) return v;
    }
    // Fallback: the last item's `id`. Matches openai-python's behavior.
    const last = this.data[this.data.length - 1] as { id?: unknown };
    if (last && typeof last.id === 'string' && last.id) return last.id;
    return null;
  }
}
