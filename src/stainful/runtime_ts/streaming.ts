// Generated SDK runtime — Server-Sent Events streaming.
//
// Symbol-compatible with openai-node's `Stream<T>`: a class that
// implements `AsyncIterable<T>` so users write
//
//     for await (const event of stream) { ... }
//
// against a typed event stream. Methods declared with the `streaming`
// stainless.yml block get overloads — `stream: true` returns
// `Promise<Stream<Event>>`; the default returns `Promise<JsonResponse>`.

/** One SSE event block — minimal shape; the runtime just yields data. */
type SSEBlock = { data: string };

/**
 * `Stream<T>` over an SSE response. Parses `data: <json>\n\n` blocks;
 * stops at `data: [DONE]` (openai convention). Each yielded item is
 * the JSON-decoded payload.
 */
export class Stream<T> implements AsyncIterable<T> {
  constructor(private response: Response, private controller?: AbortController) {}

  [Symbol.asyncIterator](): AsyncIterator<T> {
    return this._iterate();
  }

  /** Cancel the underlying response (closes the connection). */
  abort(): void {
    this.controller?.abort();
  }

  private async *_iterate(): AsyncGenerator<T, void, void> {
    if (!this.response.body) return;
    const reader = this.response.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          // Flush any trailing block (in case the server didn't send
          // the final `\n\n` before EOF).
          const tail = _parseBlock(buf);
          if (tail !== null) {
            if (tail.data === '[DONE]') return;
            try {
              yield JSON.parse(tail.data) as T;
            } catch {
              // Ignore non-JSON tail; tolerant of probe/keepalive frames.
            }
          }
          return;
        }
        buf += decoder.decode(value, { stream: true });
        // SSE events are separated by `\n\n`.
        let idx: number;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const parsed = _parseBlock(block);
          if (parsed === null) continue;
          if (parsed.data === '[DONE]') return;
          try {
            yield JSON.parse(parsed.data) as T;
          } catch {
            // Non-JSON event (e.g. comment / keepalive) — skip.
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
}

/** Extract the concatenated `data:` lines from one SSE event block. */
function _parseBlock(block: string): SSEBlock | null {
  const lines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('data:')) {
      lines.push(line.slice(5).replace(/^ /, ''));
    }
  }
  return lines.length > 0 ? { data: lines.join('\n') } : null;
}
