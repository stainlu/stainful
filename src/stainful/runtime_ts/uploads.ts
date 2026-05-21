// Generated SDK runtime — multipart file upload helpers.
//
// Mirrors the Python runtime's `extract_files(body, paths)`. The
// emitter calls `extractFiles` at the call site when a method has
// `multi_content: true` (e.g. openai's `skills.create` — JSON OR
// multipart on the same op). If file-like values are present at the
// configured paths, we lift them out and send the request as
// multipart; otherwise the body goes out as JSON unchanged.
//
// Oracle: openai-node's `internal/uploads.ts::maybeMultipartFormRequest
// Options`. We expose the smaller `extractFiles` primitive so the
// emitter can decide content-type without an extra round-trip.

/** A file-like value the runtime can upload. */
export type Uploadable =
  | Blob
  | File
  | ArrayBuffer
  | Uint8Array
  // `[filename, content, ?contentType]` tuple — convenience for
  // Node-side callers that have raw bytes + a logical name.
  | readonly [string, Blob | ArrayBuffer | Uint8Array, string?]
  // Node 20+ Buffer (subclass of Uint8Array, but tooling sometimes
  // pickier about narrowing — accept either)
  | { readonly buffer: ArrayBuffer; readonly byteLength: number };

function isUploadable(v: unknown): v is Uploadable {
  if (v == null) return false;
  if (typeof Blob !== 'undefined' && v instanceof Blob) return true;
  if (v instanceof ArrayBuffer) return true;
  if (ArrayBuffer.isView(v)) return true; // Uint8Array / Buffer / typed arrays
  if (Array.isArray(v) && v.length >= 2 && typeof v[0] === 'string') return true;
  return false;
}

/**
 * Walk `body` at each `path`, lift out uploadable values, return them
 * as `[wireName, value]` tuples — and **mutate** `body` to remove
 * them so they don't ALSO get encoded as form scalars.
 *
 * Each path is a sequence of dict keys / `<array>` sentinels. A
 * `<array>` segment means "iterate over the list at this position",
 * for `files: Uploadable[]` shapes. Wire name follows the multipart
 * array convention (`files[]`).
 */
export function extractFiles(
  body: Record<string, unknown>,
  paths: ReadonlyArray<ReadonlyArray<string>>,
): Array<[string, Uploadable]> {
  const out: Array<[string, Uploadable]> = [];
  for (const path of paths) {
    extractAt(body, [...path], [], out);
  }
  return out;
}

function extractAt(
  cur: unknown,
  remaining: string[],
  nameParts: string[],
  out: Array<[string, Uploadable]>,
): void {
  if (remaining.length === 0) {
    if (isUploadable(cur)) out.push([nameParts.join(''), cur]);
    return;
  }
  const seg = remaining[0]!;
  const rest = remaining.slice(1);
  if (seg === '<array>') {
    if (Array.isArray(cur)) {
      for (const item of cur) extractAt(item, rest, [...nameParts, '[]'], out);
      // Single-file shorthand in an array slot.
      if (isUploadable(cur as unknown)) {
        out.push([nameParts.join('') + '[]', cur as unknown as Uploadable]);
      }
    } else if (isUploadable(cur)) {
      out.push([nameParts.join('') + '[]', cur]);
    }
    return;
  }
  if (typeof cur !== 'object' || cur === null) return;
  const obj = cur as Record<string, unknown>;
  if (!(seg in obj)) return;
  const nextName = nameParts.length === 0 ? [seg] : [...nameParts, `[${seg}]`];
  const val = obj[seg];
  if (rest.length === 0 && isUploadable(val)) {
    out.push([nextName.join(''), val as Uploadable]);
    delete obj[seg];
    return;
  }
  if (rest[0] === '<array>' && Array.isArray(val)) {
    for (const item of val) {
      extractAt(item, rest.slice(1), [...nextName, '[]'], out);
    }
    if (val.some(isUploadable)) delete obj[seg];
    return;
  }
  extractAt(val, rest, nextName, out);
}
