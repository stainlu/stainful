"""Pydantic v2 base for generated response models (DESIGN §5).

`_request_id` exposes the `x-request-id` of the originating response
(RESEARCH §4 #5). Generated models subclass this; field aliasing lets the
wire name (`currentTime`) differ from the idiomatic Python name
(`current_time`) the emitter chooses.
"""

from __future__ import annotations

from typing import Any, Optional

import pydantic

__all__ = ["BaseModel", "to_jsonable"]


def to_jsonable(obj: Any) -> Any:
    """Recursively turn request inputs (models / lists / dicts) into JSON.

    Accepts pydantic models *or* plain dicts (the Stainless-style typed-dict
    input), so generated method kwargs serialize correctly either way.
    """
    if isinstance(obj, pydantic.BaseModel):
        return obj.model_dump(by_alias=True, exclude_none=True)
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


class BaseModel(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        populate_by_name=True,   # accept both wire alias and python name
        extra="allow",           # forward-compatible: unknown fields don't break
    )

    # Set by the client after construction; not a wire field.
    _request_id: Optional[str] = pydantic.PrivateAttr(default=None)

    # --- Stainless drop-in helpers ----------------------------------------
    # `.to_dict()` / `.to_json()` are the symbols Stainless customers reach
    # for; we route them to pydantic v2's `model_dump` / `model_dump_json`
    # with `by_alias=True` (Stainless's default: emit the wire name). Users
    # who want python-name keys can still call `model_dump()` directly.

    def to_dict(self, **kwargs: object) -> dict:
        """Serialize to a dict with wire field names. Drop-in alias for
        `pydantic.BaseModel.model_dump(by_alias=True, exclude_unset=True)`
        — matches the Stainless surface; extra kwargs flow to pydantic."""
        kwargs.setdefault("by_alias", True)
        kwargs.setdefault("exclude_unset", True)
        return self.model_dump(**kwargs)              # type: ignore[arg-type]

    def to_json(self, **kwargs: object) -> str:
        """Serialize to a JSON string with wire field names. Drop-in alias
        for `pydantic.BaseModel.model_dump_json(by_alias=True,
        exclude_unset=True)`."""
        kwargs.setdefault("by_alias", True)
        kwargs.setdefault("exclude_unset", True)
        return self.model_dump_json(**kwargs)         # type: ignore[arg-type]
