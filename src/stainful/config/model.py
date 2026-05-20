"""Typed model of the Stainless config (`stainless.yml` / `stainful.yml`).

Goal: **drop-in compatibility**. We strongly-type the keys the IR builder needs and
*preserve* everything else in `.extra` rather than rejecting it — a real-world config
(e.g. `readme`, `query_settings`, `codeflow`) must load even before we act on those
keys. Unknown keys are kept, not silently dropped; the loader emits soft diagnostics.

Pure dataclasses, no behavior (DESIGN §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Stainless method shorthand verbs.
HTTP_VERBS = frozenset({"get", "post", "put", "patch", "delete"})

# Reserved resource keys with special meaning (not real resources).
SHARED_KEY = "$shared"
CLIENT_KEY = "$client"


@dataclass
class Endpoint:
    """Parsed `"<verb> <path>"` method shorthand."""

    verb: str
    path: str

    @property
    def raw(self) -> str:
        return f"{self.verb} {self.path}"


@dataclass
class MethodConfig:
    name: str
    endpoint: Endpoint | None = None       # None for webhook_unwrap etc.
    paginated: bool | None = None
    unwrap_response: str | None = None
    method_type: str | None = None         # config `type:` (e.g. webhook_unwrap)
    positional_params: list[str] = field(default_factory=list)
    body_param_name: str | None = None
    skip_test_reason: str | None = None
    streaming: dict | None = None
    # Everything we don't yet model, preserved verbatim.
    extra: dict = field(default_factory=dict)


@dataclass
class ModelConfig:
    name: str
    openapi_ref: str                       # schema name or "#/components/..."
    deduplicate: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class ResourceConfig:
    name: str
    methods: dict[str, MethodConfig] = field(default_factory=dict)
    models: dict[str, ModelConfig] = field(default_factory=dict)
    subresources: dict[str, "ResourceConfig"] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


@dataclass
class Organization:
    name: str
    docs: str | None = None
    contact: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class TargetConfig:
    language: str
    package_name: str | None = None
    gem_name: str | None = None
    reverse_domain: str | None = None
    production_repo: str | None = None
    publish: dict = field(default_factory=dict)
    skip: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class OptConfig:
    """A `client_settings.opts.<name>` entry — an auth/credential input."""

    name: str
    type: str = "string"
    auth: dict = field(default_factory=dict)         # {security_scheme, header, role}
    read_env: str | None = None
    send_as_query_param: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ClientSettings:
    opts: dict[str, OptConfig] = field(default_factory=dict)
    idempotency: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


@dataclass
class PaginationDef:
    name: str
    type: str                                        # cursor|cursor_id|offset|page_number
    request: dict = field(default_factory=dict)
    response: dict = field(default_factory=dict)
    continue_on_empty_items: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class Config:
    organization: Organization
    resources: dict[str, ResourceConfig] = field(default_factory=dict)
    # $shared.models and $client.methods, lifted out of `resources`.
    shared_models: dict[str, ModelConfig] = field(default_factory=dict)
    client_methods: dict[str, MethodConfig] = field(default_factory=dict)
    targets: dict[str, TargetConfig] = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    client_settings: ClientSettings = field(default_factory=ClientSettings)
    environments: dict[str, str] = field(default_factory=dict)
    pagination: list[PaginationDef] = field(default_factory=list)
    security: list = field(default_factory=list)
    security_schemes: dict = field(default_factory=dict)
    streaming: dict = field(default_factory=dict)
    # User-declared name overrides — snake-cased input -> PascalCase output.
    # Stainless calls this `custom_casings`. Used to spell out compound
    # names where the heuristics can't infer the right casing
    # (`openai_id_string` -> `OpenAIIDString`, etc.). Accepts either the
    # dict form `{snake: Pascal}` or the list-of-singletons form
    # `[{snake: Pascal}, ...]`; the loader normalizes both.
    custom_casings: dict[str, str] = field(default_factory=dict)
    # Unrecognized top-level keys (readme, query_settings, codeflow, …) preserved
    # so a real config round-trips and the IR builder can opt in later.
    extra: dict = field(default_factory=dict)
