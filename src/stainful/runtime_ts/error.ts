// Generated SDK runtime — typed exception hierarchy.
//
// Symbol-identical to openai-node's `core/error.ts` so a user's existing
// `import { RateLimitError } from "openai"` keeps resolving when they
// migrate. Brand-agnostic — the cross-SDK catchable symbols ARE the
// drop-in contract.

export class APIError extends Error {
  readonly status: number | undefined;
  readonly request_id: string | undefined;
  readonly headers: Record<string, string> | undefined;
  readonly error: object | undefined;

  readonly code: string | null | undefined;
  readonly param: string | null | undefined;
  readonly type: string | undefined;

  constructor(
    status: number | undefined,
    error: object | undefined,
    message: string | undefined,
    headers: Record<string, string> | undefined,
  ) {
    super(message ?? APIError.makeMessage(status, error, message));
    this.status = status;
    this.headers = headers;
    this.request_id = headers?.['x-request-id'];
    this.error = error;
    const data = (error as Record<string, unknown> | undefined) ?? {};
    const errObj = (data['error'] as Record<string, unknown> | undefined) ?? data;
    this.code = (errObj['code'] as string | null | undefined) ?? undefined;
    this.param = (errObj['param'] as string | null | undefined) ?? undefined;
    this.type = (errObj['type'] as string | undefined) ?? undefined;
  }

  private static makeMessage(
    status: number | undefined,
    error: object | undefined,
    message: string | undefined,
  ): string {
    if (message) return message;
    if (status) return `Error code: ${status}`;
    if (error) return JSON.stringify(error);
    return 'API error';
  }
}

export class APIConnectionError extends APIError {
  constructor({ message, cause }: { message?: string; cause?: Error } = {}) {
    super(undefined, undefined, message ?? 'Connection error.', undefined);
    if (cause) (this as { cause?: Error }).cause = cause;
  }
}

export class APITimeoutError extends APIConnectionError {
  constructor({ message }: { message?: string } = {}) {
    super({ message: message ?? 'Request timed out.' });
  }
}

export class APIUserAbortError extends APIError {
  constructor({ message }: { message?: string } = {}) {
    super(undefined, undefined, message ?? 'Request was aborted.', undefined);
  }
}

export class APIResponseValidationError extends APIError {}

// `status` is set by the parent constructor; narrow the type without
// re-declaring (avoiding `override` + `declare` conflict — see TS1243).
class StatusError extends APIError {}

export class BadRequestError extends StatusError {}
export class AuthenticationError extends StatusError {}
export class PermissionDeniedError extends StatusError {}
export class NotFoundError extends StatusError {}
export class ConflictError extends StatusError {}
export class UnprocessableEntityError extends StatusError {}
export class RateLimitError extends StatusError {}
export class InternalServerError extends StatusError {}

export class InvalidWebhookSignatureError extends Error {}

const STATUS_MAP: Record<number, typeof StatusError> = {
  400: BadRequestError,
  401: AuthenticationError,
  403: PermissionDeniedError,
  404: NotFoundError,
  409: ConflictError,
  422: UnprocessableEntityError,
  429: RateLimitError,
};

/** Map an HTTP status to the precise typed exception. */
export function statusErrorFor(
  status: number,
  error: object | undefined,
  headers: Record<string, string> | undefined,
): APIError {
  const cls = STATUS_MAP[status] ?? (status >= 500 ? InternalServerError : StatusError);
  return new cls(status, error, `Error code: ${status}`, headers);
}
