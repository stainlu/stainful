"""Hand-written SDK runtime.

Vendored verbatim by the emitter into `<generated_pkg>/_core/`. This code is
licensed MIT (see the project LICENSE) and travels into generated SDKs under
the same terms. Brand-agnostic: the catchable symbols here are identical
across every generated SDK — that sameness is the drop-in contract.

Submodules use relative imports so this package works unchanged when copied
under another package name. The golden tape-out target
(`tests/golden/onebusaway/`) pins exactly this public surface.
"""

from ._base_client import AsyncAPIClient, SyncAPIClient
from ._exceptions import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    InternalServerError,
    InvalidWebhookSignatureError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from ._models import BaseModel, to_jsonable
from ._request_options import RequestOptions, make_request_options
from ._resource import AsyncAPIResource, SyncAPIResource
from ._response import (
    async_to_raw_response_wrapper,
    async_to_streamed_response_wrapper,
    to_raw_response_wrapper,
    to_streamed_response_wrapper,
)
from ._sentinels import NOT_GIVEN, NotGiven, Omit, not_given, omit
from ._streaming import AsyncStream, Stream
from ._types import Body, FileTypes, Headers, Query
from .pagination import (
    AsyncCursorPage,
    AsyncPage,
    PageInfo,
    SyncCursorPage,
    SyncPage,
)

__all__ = [
    "SyncAPIClient",
    "AsyncAPIClient",
    "SyncAPIResource",
    "AsyncAPIResource",
    "BaseModel",
    "to_jsonable",
    "RequestOptions",
    "make_request_options",
    "NotGiven",
    "not_given",
    "NOT_GIVEN",
    "Omit",
    "omit",
    "Headers",
    "Query",
    "Body",
    "FileTypes",
    "Stream",
    "AsyncStream",
    "PageInfo",
    "SyncPage",
    "AsyncPage",
    "SyncCursorPage",
    "AsyncCursorPage",
    "APIError",
    "APIStatusError",
    "APIConnectionError",
    "APITimeoutError",
    "APIResponseValidationError",
    "BadRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "UnprocessableEntityError",
    "RateLimitError",
    "InternalServerError",
    "InvalidWebhookSignatureError",
    "to_raw_response_wrapper",
    "async_to_raw_response_wrapper",
    "to_streamed_response_wrapper",
    "async_to_streamed_response_wrapper",
]
