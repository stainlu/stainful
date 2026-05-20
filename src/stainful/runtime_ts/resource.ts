// Base class for generated resource classes.
// Symbol-identical to openai-node's `core/resource.ts`.

import type { BaseClient } from './client';

export abstract class APIResource {
  protected _client: BaseClient;
  constructor(client: BaseClient) {
    this._client = client;
  }
}
