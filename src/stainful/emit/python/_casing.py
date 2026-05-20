"""Naming transforms. Wire names (camelCase, kebab) -> idiomatic Python.

The emitter chooses snake_case symbols and carries the original wire name as a
pydantic `alias` (DESIGN §3 / golden target). PascalCase for classes.
"""

from __future__ import annotations

import re

_CAMEL_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_2 = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]+")


def snake(name: str) -> str:
    # Any separator/punctuation (`-`, `.`, space, `/`, …) collapses to `_`,
    # so arbitrary OpenAPI property names become valid identifiers.
    s = _NON_ALNUM.sub("_", name)
    s = _CAMEL_1.sub(r"\1_\2", s)
    s = _CAMEL_2.sub(r"\1_\2", s)
    return re.sub(r"_+", "_", s).strip("_").lower()


# Whole-token initialisms Stainless renders ALL-CAPS in PascalCase names
# (verified vs the real Stainless OneBusAway SDK: `RouteIDsForAgency`,
# `NearbyStopID`). Exact-token match (not substring) so `Identifier` is safe.
_INITIALISMS = {
    "id", "url", "uri", "api", "sdk", "http", "https", "html", "xml", "json",
    "sql", "cli", "io", "ai", "ip", "db", "ui", "jwt", "csv", "ssl", "tls",
    "sse", "gps", "vin",
}


def _cap_token(p: str) -> str:
    low = p.lower()
    if low in _INITIALISMS:
        return p.upper()                         # Id -> ID, Url -> URL
    if low.endswith("s") and low[:-1] in _INITIALISMS:
        return p[:-1].upper() + "s"              # Ids -> IDs
    return p[:1].upper() + p[1:]


def pascal(name: str) -> str:
    # User override (custom_casings) wins outright — the whole-name version.
    # We look up the snake-cased input; that's the canonical form Stainless
    # configs use (`openai_id_string: OpenAIIDString`).
    override = _USER_CASINGS.get(snake(name))
    if override is not None:
        return override
    parts = _NON_ALNUM.split(_CAMEL_2.sub(r"\1_\2", name))
    return "".join(_cap_token(p) for p in parts if p)


def pascal_singular_last(name: str) -> str:
    """PascalCase, but singularize the LAST word — Stainless's resource→type
    prefix rule: `trip-details` → `TripDetail` (type names) while the resource
    *class* stays `TripDetailsResource`; `agencies_with_coverage` is unchanged
    (last word "coverage" already singular). Verified across the OneBusAway
    corpus — do not blanket-singularize the whole name.
    """
    parts = [p for p in _NON_ALNUM.split(_CAMEL_2.sub(r"\1_\2", name)) if p]
    if parts:
        parts[-1] = singularize(parts[-1])
    return "".join(_cap_token(p) for p in parts)


def singularize(word: str) -> str:
    """English-ish singular for an array field's path segment.

    Stainless names a nested array-item model after the SINGULAR of the field
    (`arrivalsAndDepartures: [X]` -> `...ArrivalsAndDeparture`,
    `agencies` -> `Agency`, `trips` -> `Trip`). Pragmatic ruleset — covers the
    real OneBusAway corpus; not a full inflector.
    """
    w = word
    if len(w) > 2 and w.endswith("ies"):
        return w[:-3] + "y"                     # Agencies -> Agency
    if w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return w[:-2]                            # Boxes -> Box
    if (
        w.endswith("s")
        and not w.endswith(("ss", "us", "is", "Status"))
        and len(w) > 1
    ):
        return w[:-1]                            # Trips -> Trip
    return w




# Compound brand names that bake an initialism into one lowercase token —
# the well-known cases shipped as a default. Users declare additional
# overrides via `custom_casings:` in stainless.yml — those go into
# `_USER_CASINGS` below and take precedence here AND inside `pascal()`.
# Heuristic auto-splitting on initialism suffixes would over-match real
# English words (`chai`, `tai`, `media` → `MediA`, …), which is exactly
# why Stainless makes users declare these explicitly.
_COMPOUND_BRANDS = {
    "openai": "OpenAI",
    "openapi": "OpenAPI",
    "anthropic": "Anthropic",
    "cloudflare": "Cloudflare",
}

# Per-generation user overrides from `custom_casings:` in stainless.yml.
# Populated by the emitter at the start of an emit() pass via
# `set_user_casings(...)`; consulted by `pascal()` and `brand()` before
# heuristics. Module-level (process-global) by design — `emit()` is single-
# threaded and clears between runs.
_USER_CASINGS: dict[str, str] = {}


def set_user_casings(casings: dict[str, str] | None) -> None:
    """Install user-declared casings for the duration of an emit() pass."""
    global _USER_CASINGS
    _USER_CASINGS = dict(casings or {})


def brand(api_name: str) -> str:
    """`onebusaway-sdk` -> `OnebusawaySDK` (matches the real Stainless output).

    The client class name is a *symbol-level drop-in contract*: a user's
    `from onebusaway import OnebusawaySDK` must keep compiling. `sdk` is kept
    and upper-cased as an initialism, NOT stripped.

    Resolution order: `custom_casings` whole-name override → per-token
    compound-brand defaults → initialism set → standard PascalCase.
    """
    # Whole-name custom_casings wins outright.
    override = _USER_CASINGS.get(snake(api_name))
    if override is not None:
        return override
    tokens = _NON_ALNUM.split(_CAMEL_2.sub(r"\1_\2", api_name))
    out = []
    for tok in tokens:
        if not tok:
            continue
        low = tok.lower()
        # Per-token user override (e.g. someone declared `inputs: Inputs`).
        if low in _USER_CASINGS:
            out.append(_USER_CASINGS[low])
        elif low in _COMPOUND_BRANDS:
            out.append(_COMPOUND_BRANDS[low])         # openai -> OpenAI
        elif low in _INITIALISMS:
            out.append(tok.upper())
        else:
            out.append(tok[:1].upper() + tok[1:])
    return "".join(out)


def package(api_name: str) -> str:
    """`onebusaway-sdk` -> `onebusaway` (importable package name).

    The package dir drops `-sdk` (the real published package is `onebusaway`),
    even though the *class* keeps `SDK`.
    """
    base = re.sub(r"[-_]sdk$", "", api_name, flags=re.IGNORECASE)
    return snake(base)
