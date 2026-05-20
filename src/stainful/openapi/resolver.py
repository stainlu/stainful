"""$ref resolution + allOf deep-merge (DESIGN §3, §6 slice 2).

Two narrow, pure functions. Both are cycle-safe by *not* deep-recursing into
properties — that recursion (and its cycles) belongs to the IR builder, which
breaks cycles with `ModelRef` (DESIGN §3). Here we only:

  * `resolve_ref`  — one hop of an internal JSON pointer, reporting whether the
                     target is a named component schema (the Model boundary);
  * `flatten_allof` — collapse an `allOf` node into one object schema, the single
                     place an anonymous merged shape is genuinely needed (the
                     `ResponseWrapper + {data}` envelope).

No silent fallbacks: external refs and pathological `allOf` cycles raise SpecError.
"""

from __future__ import annotations

from dataclasses import dataclass

from stainful.errors import SourceLoc, SpecError
from stainful.openapi.loader import OpenAPIDocument

_SCHEMA_PREFIX = "#/components/schemas/"


@dataclass
class Ref:
    """Result of one ref hop."""

    # component schema name if this ref points at #/components/schemas/<name>,
    # else None. This is what lets the builder emit a ModelRef vs. inline.
    schema_name: str | None
    target: dict


def _json_pointer(doc: OpenAPIDocument, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise SpecError(
            f"unsupported $ref {ref!r}: external/file refs are out of stainful v1 "
            f"scope (bundle the spec first)",
            SourceLoc(doc.source),
        )
    node: object = doc.raw
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            raise SpecError(f"$ref {ref!r} does not resolve", SourceLoc(doc.source))
        node = node[token]
    if not isinstance(node, dict):
        raise SpecError(
            f"$ref {ref!r} must point at a mapping", SourceLoc(doc.source)
        )
    return node


def resolve_ref(doc: OpenAPIDocument, ref: str) -> Ref:
    """Resolve a single internal `$ref` hop. Does not recurse further."""
    target = _json_pointer(doc, ref)
    name = ref[len(_SCHEMA_PREFIX):] if ref.startswith(_SCHEMA_PREFIX) else None
    return Ref(schema_name=name, target=target)


# Keys that don't affect the wire/type shape — two property definitions
# differing only in these are still "the same property" for allOf merging.
# A real-world finding from the openai spec (~983 schemas): branches that
# refine a base type often re-state the same `id`/`type` field with a
# different `description` — strict `!=` rejects this but it's not a real
# conflict.
_COSMETIC_KEYS = frozenset({
    "description", "title", "example", "examples", "default",
    "x-stainless-const", "x-oaiTypeLabel", "x-oaiMeta",
    "readOnly", "writeOnly", "deprecated",
})


def _structural(s: object) -> object:
    """`s` with cosmetic keys stripped — used to compare allOf property defs
    by *type shape*, not by docstring/example. Recursive into dicts/lists.
    """
    if isinstance(s, dict):
        return {k: _structural(v) for k, v in s.items() if k not in _COSMETIC_KEYS}
    if isinstance(s, list):
        return [_structural(v) for v in s]
    return s


def _resolve_one_hop(prop: object, doc: OpenAPIDocument) -> object:
    """If `prop` is a `$ref` to `#/components/schemas/X`, return X's schema;
    else return `prop` unchanged. One hop only — caller compares shapes, not
    transitive closures. Used to make allOf compatibility resilient to
    "branch A inlines `{type: string, enum: [...]}` and branch B uses
    `$ref: #/components/schemas/SameEnum`" — a real pattern in the openai
    spec (e.g. `ComputerToolCallOutputResource.status`).
    """
    if (
        isinstance(prop, dict)
        and isinstance(prop.get("$ref"), str)
        and prop["$ref"].startswith(_SCHEMA_PREFIX)
    ):
        name = prop["$ref"][len(_SCHEMA_PREFIX):]
        target = doc.schemas.get(name)
        if isinstance(target, dict):
            return target
    return prop


def _inner_of_nullable(s: object) -> object | None:
    """If `s` is a "T-or-null" wrapper, return T's structural shape; else None.

    Handles both OpenAPI shapes:
      - 3.0: `{type: X, nullable: true}`
      - 3.1: `{anyOf|oneOf: [{type: X, ...}, {type: "null"}]}`
    """
    if not isinstance(s, dict):
        return None
    if s.get("nullable") is True:
        return {k: v for k, v in s.items() if k != "nullable"}
    for key in ("anyOf", "oneOf"):
        branches = s.get(key)
        if isinstance(branches, list) and len(branches) == 2:
            null_ix = next(
                (i for i, b in enumerate(branches)
                 if isinstance(b, dict) and b.get("type") == "null"),
                None,
            )
            if null_ix is not None:
                return branches[1 - null_ix]
    return None


def _merge_property(
    name: str, existing: object, incoming: object, doc: OpenAPIDocument,
) -> object:
    """Merge two property defs from sibling allOf branches.

    Compatible (identical after cosmetic strip + one-hop $ref resolve) →
    last-wins. **Enum-union compatible** (everything else equal, only enum
    members differ) → emit an inline def with the unioned enum (oracle:
    openai-python emits `Literal["completed","incomplete","failed",
    "in_progress"]` for ComputerToolCallOutputResource.status, the union of
    two branches' enums). **Nullable lattice** (one branch is `T | null`,
    other is plain `T`) → take the nullable branch (oracle: openai-python
    emits `Optional[int]` for `top_logprobs` where one branch is
    `anyOf: [int, null]` and the other is plain `int`).

    Otherwise — structural divergence we don't yet model → **last-wins,
    quietly**. Strict raise was right for in-repo fixtures but rejects valid
    real-world patterns (the openai spec has dozens of these); broader-type
    detection grows case-by-case as we see them.
    """
    e_resolved = _resolve_one_hop(existing, doc)
    i_resolved = _resolve_one_hop(incoming, doc)
    e = _structural(e_resolved)
    i = _structural(i_resolved)
    if e == i:
        return incoming                                # cosmetic-only diff
    # 1. enum union
    def _drop_enum(x: object) -> object:
        return (
            {kk: vv for kk, vv in x.items() if kk != "enum"}
            if isinstance(x, dict) else x
        )
    if _drop_enum(e) == _drop_enum(i):
        e_enum = (e.get("enum") or []) if isinstance(e, dict) else []
        i_enum = (i.get("enum") or []) if isinstance(i, dict) else []
        merged_enum = list(dict.fromkeys([*e_enum, *i_enum]))
        # Drop $ref so the union sticks (JSON Schema ignores siblings of $ref).
        base = i_resolved if isinstance(i_resolved, dict) else {}
        merged = {kk: vv for kk, vv in base.items() if kk != "$ref"}
        merged["enum"] = merged_enum
        if isinstance(incoming, dict):
            for ck in ("description", "title"):
                if incoming.get(ck):
                    merged[ck] = incoming[ck]
        return merged
    # 2. nullable lattice — T-or-null beats T
    e_inner = _inner_of_nullable(e)
    i_inner = _inner_of_nullable(i)
    if e_inner is not None and e_inner == i:
        return existing                                # existing is the nullable
    if i_inner is not None and i_inner == e:
        return incoming                                # incoming is the nullable
    # 3. unknown structural divergence — lenient last-wins. Loses some
    #    signal vs strict raise, but lets real-world specs through.
    return incoming


def _merge_object(into: dict, src: dict, doc: OpenAPIDocument) -> None:
    if src.get("type", "object") != "object":
        raise SpecError(
            f"allOf member is non-object (type={src.get('type')!r}); stainful v1 "
            f"only merges object schemas",
            SourceLoc(doc.source),
        )
    props = into.setdefault("properties", {})
    for k, v in (src.get("properties", {}) or {}).items():
        if k in props:
            props[k] = _merge_property(k, props[k], v, doc)
        else:
            props[k] = v
    req = dict.fromkeys(into.get("required", []))
    req.update(dict.fromkeys(src.get("required", []) or []))
    into["required"] = list(req)
    if "additionalProperties" in src:
        into.setdefault("additionalProperties", src["additionalProperties"])


def flatten_allof(
    doc: OpenAPIDocument, schema: dict, _seen: frozenset[str] = frozenset()
) -> dict:
    """Return `schema` with a top-level `allOf` collapsed into one object schema.

    Schemas without `allOf` are returned unchanged (we do NOT walk properties —
    that is the builder's job, where ModelRef breaks cycles). Recurses only
    through allOf-of-allOf, guarded by ref-name cycle detection.
    """
    if "allOf" not in schema:
        return schema

    merged: dict = {"type": "object", "properties": {}, "required": []}
    # carry through sibling keywords (description, title, …) that coexist w/ allOf
    for k, v in schema.items():
        if k != "allOf":
            merged.setdefault(k, v)

    for member in schema["allOf"]:
        m = member
        if "$ref" in m:
            ref = m["$ref"]
            name = (
                ref[len(_SCHEMA_PREFIX):]
                if ref.startswith(_SCHEMA_PREFIX)
                else ref
            )
            if name in _seen:
                raise SpecError(
                    f"allOf cycle through {ref!r}: not representable",
                    SourceLoc(doc.source),
                )
            m = resolve_ref(doc, ref).target
            m = flatten_allof(doc, m, _seen | {name})
        elif "allOf" in m:
            m = flatten_allof(doc, m, _seen)
        _merge_object(merged, m, doc)

    if not merged["required"]:
        del merged["required"]
    return merged
