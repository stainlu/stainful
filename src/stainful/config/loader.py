"""`load_config(path) -> Config` (DESIGN §6 slice 1).

Parses with ruamel.yaml in round-trip mode so we keep source line/column for
quotable diagnostics. YAML anchors/aliases (the OneBusAway `readme` block uses
them) resolve transparently.

Policy:
  * keys we model      -> typed
  * keys we don't model -> preserved in `.extra` + a soft diagnostic (drop-in
                           compatibility: a real config must load before we act
                           on every key)
  * malformed values    -> hard ConfigError with source location (no silent
                           coercion, no fallback)
"""

from __future__ import annotations

import sys
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from stainful.config.model import (
    CLIENT_KEY,
    HTTP_VERBS,
    SHARED_KEY,
    ClientSettings,
    Config,
    Endpoint,
    MethodConfig,
    ModelConfig,
    OptConfig,
    Organization,
    PaginationDef,
    ResourceConfig,
    TargetConfig,
)
from stainful.errors import ConfigError, SourceLoc

_KNOWN_TOP = {
    "edition", "organization", "resources", "targets", "settings",
    "client_settings", "environments", "pagination", "security",
    "security_schemes", "streaming", "custom_casings",
}
# Valid Stainless top-level keys we don't act on yet. These are PRESERVED
# silently — a real `stainless.yml` legitimately has them; warning on them
# would be wrong (implies a problem where there is none). Only *genuinely*
# unrecognized keys (typos / unknown) get a soft warning — that's the signal
# worth keeping.
_KNOWN_DEFERRED = {
    "query_settings", "multipart_settings", "readme",
    "constants", "diagnostics", "unspecified_endpoints", "codeflow",
    "openapi", "$schema",
}


def _parse_custom_casings(node: object) -> dict[str, str]:
    """Normalize `custom_casings:` into a `{snake: PascalCase}` dict.

    Stainless allows two surface forms, both common in real configs:

        custom_casings:
          openai_id_string: OpenAIIDString
          inputs_options: InputsOptions

    or

        custom_casings:
          - openai_id_string: OpenAIIDString
          - inputs_options: InputsOptions

    Empty / unsupported values are ignored — the heuristics fall back.
    """
    out: dict[str, str] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and isinstance(v, str):
                out[k] = v
    elif isinstance(node, list):
        for entry in node:
            if isinstance(entry, dict) and len(entry) == 1:
                k, v = next(iter(entry.items()))
                if isinstance(k, str) and isinstance(v, str):
                    out[k] = v
    return out
_KNOWN_METHOD = {
    "endpoint", "paginated", "unwrap_response", "type", "positional_params",
    "body_param_name", "skip_test_reason", "streaming",
}
_KNOWN_RESOURCE = {"methods", "models", "subresources"}


class _Loader:
    def __init__(self, path: str) -> None:
        self.file = path
        self.diagnostics: list[str] = []

    # --- diagnostics -------------------------------------------------------
    def _loc(self, node: object, key: str | None = None) -> SourceLoc:
        try:
            if key is not None and hasattr(node, "lc"):
                line, col = node.lc.key(key)
                return SourceLoc(self.file, line + 1, col + 1)
            if hasattr(node, "lc") and node.lc.line is not None:
                return SourceLoc(self.file, node.lc.line + 1, node.lc.col + 1)
        except (KeyError, AttributeError, TypeError):
            pass
        return SourceLoc(self.file)

    def _warn(self, msg: str, node: object, key: str | None = None) -> None:
        self.diagnostics.append(f"{self._loc(node, key)}: {msg}")

    def _err(self, msg: str, node: object, key: str | None = None) -> ConfigError:
        return ConfigError(msg, self._loc(node, key))

    @staticmethod
    def _split_known(node: object, known: set[str]) -> dict:
        """Return the non-modeled keys of a mapping (preserved as plain dict)."""
        if not isinstance(node, dict):
            return {}
        return {k: v for k, v in node.items() if k not in known}

    # --- leaves ------------------------------------------------------------
    def _endpoint(self, value: str, node: object, key: str) -> Endpoint:
        parts = value.split(None, 1)
        if len(parts) != 2 or parts[0].lower() not in HTTP_VERBS:
            raise self._err(
                f"invalid endpoint {value!r}; expected '<verb> <path>' with verb "
                f"in {sorted(HTTP_VERBS)}",
                node, key,
            )
        return Endpoint(verb=parts[0].lower(), path=parts[1])

    def _method(self, name: str, value: object, parent: object) -> MethodConfig:
        # Shorthand: `retrieve: get /path`
        if isinstance(value, str):
            return MethodConfig(name=name, endpoint=self._endpoint(value, parent, name))
        if not isinstance(value, dict):
            raise self._err(
                f"method {name!r} must be a string shorthand or a mapping",
                parent, name,
            )
        ep = value.get("endpoint")
        endpoint = self._endpoint(ep, value, "endpoint") if isinstance(ep, str) else None
        return MethodConfig(
            name=name,
            endpoint=endpoint,
            paginated=value.get("paginated"),
            unwrap_response=value.get("unwrap_response"),
            method_type=value.get("type"),
            positional_params=list(value.get("positional_params", []) or []),
            body_param_name=value.get("body_param_name"),
            skip_test_reason=value.get("skip_test_reason"),
            streaming=dict(value["streaming"]) if "streaming" in value else None,
            extra=self._split_known(value, _KNOWN_METHOD),
        )

    def _model(self, name: str, value: object) -> ModelConfig:
        if isinstance(value, str):
            return ModelConfig(name=name, openapi_ref=value)
        if isinstance(value, dict):
            ref = value.get("openapi_uri") or value.get("openapi_ref") or ""
            return ModelConfig(
                name=name,
                openapi_ref=ref,
                deduplicate=list(value.get("deduplicate", []) or []),
                extra={k: v for k, v in value.items()
                       if k not in {"openapi_uri", "openapi_ref", "deduplicate"}},
            )
        raise self._err(f"model {name!r} must be a string ref or a mapping", value)

    def _methods(self, node: object) -> dict[str, MethodConfig]:
        out: dict[str, MethodConfig] = {}
        for mname, mval in (node or {}).items():
            out[mname] = self._method(mname, mval, node)
        return out

    def _models(self, node: object) -> dict[str, ModelConfig]:
        return {n: self._model(n, v) for n, v in (node or {}).items()}

    def _resource(self, name: str, node: object) -> ResourceConfig:
        if not isinstance(node, dict):
            raise self._err(f"resource {name!r} must be a mapping", node)
        sub = {
            sn: self._resource(sn, sv)
            for sn, sv in (node.get("subresources") or {}).items()
        }
        return ResourceConfig(
            name=name,
            methods=self._methods(node.get("methods")),
            models=self._models(node.get("models")),
            subresources=sub,
            extra=self._split_known(node, _KNOWN_RESOURCE),
        )

    # --- top level ---------------------------------------------------------
    def load(self) -> Config:
        text_path = Path(self.file)
        if not text_path.is_file():
            raise ConfigError("config file not found", SourceLoc(self.file))
        yaml = YAML()  # round-trip: keeps positions, resolves anchors/aliases
        try:
            data = yaml.load(text_path.read_text())
        except YAMLError as exc:
            raise ConfigError(f"YAML parse error: {exc}", SourceLoc(self.file)) from exc
        if not isinstance(data, dict):
            raise ConfigError("top-level config must be a mapping", SourceLoc(self.file))

        org_node = data.get("organization")
        if not isinstance(org_node, dict) or "name" not in org_node:
            raise self._err("`organization.name` is required", data, "organization")
        org = Organization(
            name=org_node["name"],
            docs=org_node.get("docs"),
            contact=org_node.get("contact"),
            extra=self._split_known(org_node, {"name", "docs", "contact"}),
        )

        cfg = Config(organization=org)

        # resources, with $shared / $client lifted out
        for rname, rnode in (data.get("resources") or {}).items():
            if rname == SHARED_KEY:
                cfg.shared_models = self._models((rnode or {}).get("models"))
            elif rname == CLIENT_KEY:
                cfg.client_methods = self._methods((rnode or {}).get("methods"))
            else:
                cfg.resources[rname] = self._resource(rname, rnode)

        for tname, tnode in (data.get("targets") or {}).items():
            tnode = tnode or {}
            cfg.targets[tname] = TargetConfig(
                language=tname,
                package_name=tnode.get("package_name"),
                gem_name=tnode.get("gem_name"),
                reverse_domain=tnode.get("reverse_domain"),
                production_repo=tnode.get("production_repo"),
                publish=dict(tnode.get("publish", {}) or {}),
                skip=bool(tnode.get("skip", False)),
                extra=self._split_known(
                    tnode,
                    {"package_name", "gem_name", "reverse_domain",
                     "production_repo", "publish", "skip"},
                ),
            )

        cfg.settings = dict(data.get("settings", {}) or {})
        cfg.environments = dict(data.get("environments", {}) or {})
        cfg.security = list(data.get("security", []) or [])
        cfg.security_schemes = dict(data.get("security_schemes", {}) or {})
        cfg.streaming = dict(data.get("streaming", {}) or {})
        cfg.custom_casings = _parse_custom_casings(data.get("custom_casings"))

        cs_node = data.get("client_settings") or {}
        opts = {}
        for oname, onode in (cs_node.get("opts") or {}).items():
            onode = onode or {}
            opts[oname] = OptConfig(
                name=oname,
                type=onode.get("type", "string"),
                auth=dict(onode.get("auth", {}) or {}),
                read_env=onode.get("read_env"),
                send_as_query_param=onode.get("send_as_query_param"),
                extra=self._split_known(
                    onode, {"type", "auth", "read_env", "send_as_query_param"}
                ),
            )
        cfg.client_settings = ClientSettings(
            opts=opts,
            idempotency=dict(cs_node.get("idempotency", {}) or {}),
            extra=self._split_known(cs_node, {"opts", "idempotency"}),
        )

        for pnode in data.get("pagination", []) or []:
            cfg.pagination.append(
                PaginationDef(
                    name=pnode.get("name", ""),
                    type=pnode.get("type", ""),
                    request=dict(pnode.get("request", {}) or {}),
                    response=dict(pnode.get("response", {}) or {}),
                    continue_on_empty_items=bool(
                        pnode.get("continue_on_empty_items", False)
                    ),
                    extra=self._split_known(
                        pnode,
                        {"name", "type", "request", "response",
                         "continue_on_empty_items"},
                    ),
                )
            )

        # Preserve every non-modeled key for forward compatibility. Warn ONLY
        # for keys that aren't valid Stainless config at all (likely typos) —
        # known-but-deferred Stainless keys are preserved silently.
        for k, v in data.items():
            if k in _KNOWN_TOP:
                continue
            cfg.extra[k] = v
            if k not in _KNOWN_DEFERRED:
                self._warn(
                    f"unrecognized top-level key {k!r} (not valid Stainless "
                    f"config — typo? preserved anyway)",
                    data, k,
                )

        return cfg


def load_config(path: str, *, strict: bool = False) -> Config:
    """Load and normalize a Stainless-format config.

    `strict=True` turns soft diagnostics (unknown keys) into a hard error — useful
    in CI to catch config typos. Default is lenient for drop-in compatibility.
    """
    loader = _Loader(path)
    cfg = loader.load()
    if loader.diagnostics:
        if strict:
            raise ConfigError(
                "strict mode: "
                + "; ".join(loader.diagnostics),
                SourceLoc(path),
            )
        for d in loader.diagnostics:
            print(f"warning: {d}", file=sys.stderr)
    return cfg
