"""IR builder (DESIGN §6 slice 3) — (OpenAPI doc + Stainless config) -> API.

This is the moat. By the time it returns:

  * every `components/schemas/<name>` is a named `Model`;
  * every `$ref` to a component is a `ModelRef` — never followed, which makes
    type construction finite and recursion-safe (DESIGN §3: ModelRef is the
    cycle-breaker; real recursion only ever goes through named refs);
  * `allOf` envelopes are merged (delegated to the resolver);
  * cardinality is 3-valued — required, optional, nullable are independent;
  * resources/methods/auth/pagination/streaming are the config's idiomatic
    overlay applied on top of the flat spec.

No fallbacks: a config endpoint absent from the spec is a loud IRBuildError.
"""

from __future__ import annotations

from stainful.config.model import Config, MethodConfig, ResourceConfig
from stainful.errors import IRBuildError, SourceLoc
from stainful.ir.model import (
    API,
    BodyShape,
    ContentType,
    HTTPVerb,
    Method,
    PaginationIntent,
    PaginationStyle,
    Resource,
    SecurityScheme,
    StreamingIntent,
    StreamingTransport,
)
from stainful.ir.types import (
    AnyType,
    ArrayType,
    Discriminator,
    EnumMember,
    EnumType,
    MapType,
    Model,
    ModelRef,
    NullType,
    ObjectType,
    PrimitiveKind,
    PrimitiveType,
    Property,
    Type,
    UnionType,
)
from stainful.openapi.loader import OpenAPIDocument
from stainful.openapi.resolver import flatten_allof, resolve_ref

_SCHEMA_PREFIX = "#/components/schemas/"

# OpenAPI (type, format) -> IR primitive.
_STRING_FORMATS = {
    "date": PrimitiveKind.DATE,
    "date-time": PrimitiveKind.DATETIME,
    "uuid": PrimitiveKind.UUID,
    "byte": PrimitiveKind.BYTES,
    "binary": PrimitiveKind.BYTES,
}
_CONTENT_TYPES = {
    "application/json": ContentType.JSON,
    "multipart/form-data": ContentType.MULTIPART,
    "application/x-www-form-urlencoded": ContentType.FORM,
    "application/octet-stream": ContentType.BINARY,
}


class _Builder:
    def __init__(self, doc: OpenAPIDocument, config: Config) -> None:
        self.doc = doc
        self.config = config
        self.loc = SourceLoc(doc.source)
        self.ops = {(o.verb, o.path): o for o in doc.operations()}
        # component schemas declared shared via config `$shared.models`
        self._shared_components = {
            mc.openapi_ref for mc in config.shared_models.values() if mc.openapi_ref
        }

    # --- type construction (the core) -------------------------------------
    def _is_nullable(self, schema: dict) -> bool:
        # 3.0 `nullable: true`; 3.1 `type: [..., "null"]`.
        if schema.get("nullable") is True:
            return True
        t = schema.get("type")
        return isinstance(t, list) and "null" in t

    def _primitive(self, schema: dict) -> Type:
        t = schema.get("type")
        if isinstance(t, list):  # 3.1 type arrays — drop the "null" sentinel
            non_null = [x for x in t if x != "null"]
            t = non_null[0] if non_null else None
        fmt = schema.get("format")
        if t == "string":
            return PrimitiveType(_STRING_FORMATS.get(fmt, PrimitiveKind.STRING), fmt)
        if t == "integer":
            return PrimitiveType(PrimitiveKind.INTEGER, fmt)
        if t == "number":
            kind = PrimitiveKind.DECIMAL if fmt == "decimal" else PrimitiveKind.NUMBER
            return PrimitiveType(kind, fmt)
        if t == "boolean":
            return PrimitiveType(PrimitiveKind.BOOLEAN, fmt)
        if t == "null":
            return NullType()
        return AnyType()

    def _discriminator(self, schema: dict) -> Discriminator | None:
        d = schema.get("discriminator")
        if not isinstance(d, dict) or "propertyName" not in d:
            return None
        mapping = {}
        for tag, ref in (d.get("mapping", {}) or {}).items():
            name = ref[len(_SCHEMA_PREFIX):] if ref.startswith(_SCHEMA_PREFIX) else ref
            mapping[tag] = name
        return Discriminator(property_name=d["propertyName"], mapping=mapping)

    def _object(self, schema: dict) -> Type:
        required = set(schema.get("required", []) or [])
        props: list[Property] = []
        for pname, pschema in (schema.get("properties", {}) or {}).items():
            props.append(
                Property(
                    name=pname,
                    type=self._type(pschema),
                    required=pname in required,
                    nullable=self._is_nullable(pschema),
                    docs=pschema.get("description") if isinstance(pschema, dict) else None,
                    deprecated=bool(
                        isinstance(pschema, dict) and pschema.get("deprecated")
                    ),
                    default=pschema.get("default") if isinstance(pschema, dict) else None,
                )
            )
        extra: Type | None = None
        ap = schema.get("additionalProperties")
        if isinstance(ap, dict):
            extra = self._type(ap)
        elif ap is True:
            extra = AnyType()
        if not props and extra is not None:
            return MapType(value=extra)
        return ObjectType(properties=tuple(props), extra=extra)

    def _type(self, schema: object) -> Type:
        """OpenAPI schema -> IR Type. Component $ref => ModelRef (never followed)."""
        if not isinstance(schema, dict) or not schema:
            return AnyType()

        if "$ref" in schema:
            ref = schema["$ref"]
            if ref.startswith(_SCHEMA_PREFIX):
                return ModelRef(name=ref[len(_SCHEMA_PREFIX):])  # cycle-break
            # non-component internal ref: resolve one hop and build inline
            return self._type(resolve_ref(self.doc, ref).target)

        if "allOf" in schema:
            # Split shared-$ref members into base classes (Stainless emits
            # `class XResponse(ResponseWrapper): ...`); merge only the rest.
            members = schema["allOf"]
            bases: list[ModelRef] = []
            rest = []
            for m in members:
                ref = isinstance(m, dict) and m.get("$ref")
                if ref and ref.startswith(_SCHEMA_PREFIX) and (
                    ref[len(_SCHEMA_PREFIX):] in self._shared_components
                ):
                    bases.append(ModelRef(name=ref[len(_SCHEMA_PREFIX):]))
                else:
                    rest.append(m)
            merged = flatten_allof(
                self.doc, {**{k: v for k, v in schema.items() if k != "allOf"},
                           "allOf": rest} if rest else
                {k: v for k, v in schema.items() if k != "allOf"}
            )
            obj = self._object(merged)
            if bases and isinstance(obj, ObjectType):
                return ObjectType(
                    properties=obj.properties, extra=obj.extra,
                    bases=tuple(bases),
                )
            return obj

        for key in ("oneOf", "anyOf"):
            if key in schema:
                variants = tuple(self._type(v) for v in schema[key])
                return UnionType(
                    variants=variants, discriminator=self._discriminator(schema)
                )

        if "enum" in schema:
            base = self._primitive(schema)
            if not isinstance(base, PrimitiveType):
                base = PrimitiveType(PrimitiveKind.STRING)
            members = tuple(
                EnumMember(name=str(v), value=v) for v in schema["enum"]
            )
            return EnumType(name="", base=base, members=members)

        t = schema.get("type")
        tl = t if isinstance(t, list) else [t]
        if "array" in tl:
            return ArrayType(item=self._type(schema.get("items", {})))
        if "object" in tl or "properties" in schema or "additionalProperties" in schema:
            return self._object(schema)
        return self._primitive(schema)

    # --- models ------------------------------------------------------------
    def _models(self) -> dict[str, Model]:
        models: dict[str, Model] = {}
        for name, schema in self.doc.schemas.items():
            ir_type = self._type(schema)
            # name anonymous enums after their owning model
            if isinstance(ir_type, EnumType) and not ir_type.name:
                ir_type = EnumType(name=name, base=ir_type.base, members=ir_type.members)
            models[name] = Model(
                name=name,
                type=ir_type,
                docs=schema.get("description") if isinstance(schema, dict) else None,
            )
        return models

    # --- params / body / responses ----------------------------------------
    def _param(self, p: dict) -> Property:
        sch = p.get("schema", {}) or {}
        return Property(
            name=p["name"],
            type=self._type(sch),
            required=bool(p.get("required", False)),
            nullable=self._is_nullable(sch),
            docs=p.get("description"),
        )

    def _body(self, request_body: dict | None) -> BodyShape | None:
        if not request_body:
            return None
        content = request_body.get("content", {}) or {}
        for media, ct in _CONTENT_TYPES.items():
            if media in content:
                schema = content[media].get("schema", {}) or {}
                return BodyShape(
                    content_type=ct,
                    type=self._type(schema),
                    required=bool(request_body.get("required", False)),
                )
        return None

    def _responses(self, responses: dict) -> dict[str, Type]:
        out: dict[str, Type] = {}
        for status, resp in responses.items():
            if not isinstance(resp, dict):
                continue
            content = resp.get("content", {}) or {}
            schema = content.get("application/json", {}).get("schema")
            if schema is None:
                # Non-JSON body (octet-stream, audio/*, image/*, …) → binary
                # download. Returning bytes is correct; JSON-parsing it isn't.
                if content:
                    out[str(status)] = PrimitiveType(PrimitiveKind.BYTES)
                continue
            # Do NOT pre-flatten: _type's allOf branch splits shared bases
            # into inheritance (Stainless envelope shape). Pre-flattening here
            # would merge the shared base away before _type sees it.
            out[str(status)] = self._type(schema)
        return out

    # --- methods / resources ----------------------------------------------
    # Request keys that carry page *size*, not the cursor itself — used to
    # pick the cursor param out of the `request:` block.
    _SIZE_PARAMS = frozenset({
        "limit", "per_page", "page_size", "max_results", "max_items",
    })
    # Response keys that aren't cursor carriers.
    _NON_CURSOR_RESPONSE_KEYS = frozenset({
        "data", "items", "results", "has_more", "object", "total",
    })

    def _pagination(self, mc: MethodConfig) -> PaginationIntent | None:
        if not mc.paginated or not self.config.pagination:
            return None
        p = self.config.pagination[0]
        req = p.request or {}
        resp = p.response or {"data": None}
        cursor_param = next(
            (k for k in req if k not in self._SIZE_PARAMS), None
        )
        cursor_response_field = next(
            (k for k in resp if k not in self._NON_CURSOR_RESPONSE_KEYS), None
        )
        return PaginationIntent(
            style=PaginationStyle(p.type),
            request_params={k: k for k in req},
            data_path=next(iter(resp), "data"),
            continue_on_empty_items=p.continue_on_empty_items,
            cursor_param=cursor_param,
            cursor_response_field=cursor_response_field,
        )

    def _streaming(self, mc: MethodConfig) -> StreamingIntent | None:
        if not mc.streaming:
            return None
        s = mc.streaming
        # `stream_event_model` names a component schema (possibly
        # `$resource.Name`); the suffix is the schema -> a ModelRef.
        ev = s.get("stream_event_model")
        event_type: Type = AnyType()
        if isinstance(ev, str) and ev:
            name = ev.split(".")[-1]
            event_type = ModelRef(name) if name in self.doc.schemas else AnyType()
        return StreamingIntent(
            transport=StreamingTransport(s.get("type", "sse")),
            event_type=event_type,
            discriminator=s.get("param_discriminator"),
        )

    def _method(self, mc: MethodConfig) -> Method:
        if mc.endpoint is None:
            # webhook_unwrap etc. — no HTTP op; carry config through emit_hints.
            hints: dict = {"type": mc.method_type, **mc.extra}
            # For `type: webhook_unwrap`: resolve `event_types` $refs into
            # ModelRefs so the emitter can render a typed discriminated union
            # (matches openai-python's `UnwrapWebhookEvent`).
            if mc.method_type == "webhook_unwrap":
                raw = mc.extra.get("event_types") or {}
                refs: dict[str, ModelRef] = {}
                for name, schema in raw.items():
                    ref = (schema or {}).get("$ref") if isinstance(schema, dict) else None
                    if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
                        continue
                    comp = ref.rsplit("/", 1)[-1]
                    if comp in self.doc.schemas:
                        refs[name] = ModelRef(comp)
                hints["event_types"] = refs
                hints["discriminator"] = mc.extra.get("discriminator") or "type"
            return Method(
                name=mc.name,
                http_verb=HTTPVerb.POST,
                path="",
                emit_hints=hints,
                docs=None,
            )
        key = (mc.endpoint.verb, mc.endpoint.path)
        op = self.ops.get(key)
        if op is None:
            raise IRBuildError(
                f"config method {mc.name!r} -> {mc.endpoint.raw!r} has no matching "
                f"operation in the OpenAPI spec",
                self.loc,
            )
        by_loc: dict[str, list[Property]] = {"path": [], "query": [], "header": []}
        for p in op.parameters:
            loc = p.get("in")
            if loc in by_loc:
                by_loc[loc].append(self._param(p))
        verb = HTTPVerb(mc.endpoint.verb)
        return Method(
            name=mc.name,
            http_verb=verb,
            path=mc.endpoint.path,
            path_params=tuple(by_loc["path"]),
            query_params=tuple(by_loc["query"]),
            header_params=tuple(by_loc["header"]),
            body=self._body(op.request_body),
            responses=self._responses(op.responses),
            unwrap=mc.unwrap_response,
            pagination=self._pagination(mc),
            streaming=self._streaming(mc),
            idempotent=verb in (HTTPVerb.GET, HTTPVerb.PUT, HTTPVerb.DELETE),
            emit_hints={
                k: v
                for k, v in {
                    "positional_params": mc.positional_params,
                    "body_param_name": mc.body_param_name,
                    "skip_test_reason": mc.skip_test_reason,
                    **mc.extra,
                }.items()
                if v
            },
            docs=op.summary,
        )

    def _resource(self, name: str, rc: ResourceConfig) -> Resource:
        return Resource(
            name=name,
            methods=[self._method(m) for m in rc.methods.values()],
            subresources=[
                self._resource(sn, sc) for sn, sc in rc.subresources.items()
            ],
        )

    # --- auth / environments ----------------------------------------------
    def _auth(self) -> list[SecurityScheme]:
        schemes: list[SecurityScheme] = []
        spec_schemes = self.doc.security_schemes
        cfg_schemes = self.config.security_schemes
        for opt in self.config.client_settings.opts.values():
            sname = opt.auth.get("security_scheme")
            spec = spec_schemes.get(sname, {}) or cfg_schemes.get(sname, {}) or {}
            kind = spec.get("type", "apiKey")
            if opt.send_as_query_param:
                location, param = "query", opt.send_as_query_param
            elif kind == "apiKey":
                location, param = spec.get("in", "header"), spec.get("name")
            else:  # http bearer/basic
                location, param = "header", "Authorization"
                kind = f"http-{spec.get('scheme', 'bearer')}"
            schemes.append(
                SecurityScheme(
                    name=opt.name,
                    kind=kind,
                    location=location,
                    param_name=param,
                    read_env=opt.read_env,
                )
            )
        return schemes

    def _environments(self) -> dict[str, str]:
        if self.config.environments:
            return dict(self.config.environments)
        servers = self.doc.servers
        return {"production": servers[0]["url"]} if servers else {}

    # --- entry -------------------------------------------------------------
    def build(self) -> API:
        info = self.doc.info
        root = Resource(
            name="$client",
            methods=[self._method(m) for m in self.config.client_methods.values()],
            subresources=[
                self._resource(n, rc) for n, rc in self.config.resources.items()
            ],
        )
        return API(
            name=self.config.organization.name or info.get("title", "api"),
            version=str(info.get("version", "0.0.0")),
            environments=self._environments(),
            auth=self._auth(),
            models=self._models(),
            shared_models={
                mc.openapi_ref: key
                for key, mc in self.config.shared_models.items()
                if mc.openapi_ref
            },
            root=root,
        )


def build_ir(spec: OpenAPIDocument, config: Config) -> API:
    if not isinstance(spec, OpenAPIDocument):
        raise IRBuildError("build_ir expects a loaded OpenAPIDocument")
    return _Builder(spec, config).build()
