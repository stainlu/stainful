"""Typed error-body model — auto-promote the spec's most-referenced 4XX
error schema to `<pkg>.types.shared.ErrorObject` (oracle: openai-python's
`openai.types.shared.ErrorObject`). Skipped if the user already declared
an `error_object` in `$shared.models`. Single-field wrappers like
`{error: $ref X}` are unwrapped to `X`.

Closes the "typed error-body models" gap in the migration guide.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


from stainful.config import load_config
from stainful.emit.python import emit
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

EXAMPLES = Path(__file__).parent.parent / "examples"


def _gen(spec: Path, config: Path, tmp_path: Path):
    api = build_ir(load_spec(str(spec)), load_config(str(config)))
    emit(api, str(tmp_path))
    return tmp_path, api


def test_openai_error_object_auto_promoted_with_flat_shape(tmp_path):
    """Real spec — `Error` (flat: code/message/param/type) wins over
    `ErrorResponse` (a `{error: $ref Error}` wrapper) because the
    heuristic prefers the error-shape after unwrapping wrappers."""
    out, api = _gen(
        EXAMPLES / "openai" / "openapi.yml",
        EXAMPLES / "openai" / "stainless.yml",
        tmp_path,
    )
    assert api.shared_models.get("Error") == "error_object"
    shared = (out / "openai" / "types" / "shared.py").read_text()
    assert "class ErrorObject(BaseModel):" in shared
    # The flat openai shape — code, message, param, type
    for f in ("code", "message", "param", "type"):
        assert f"    {f}:" in shared, f"expected field {f} in ErrorObject"
    # Drop-in: `from openai.types.shared import ErrorObject` resolves
    sys.path.insert(0, str(out))
    for m in [m for m in sys.modules if m == "openai" or m.startswith("openai.")]:
        del sys.modules[m]
    openai = importlib.import_module("openai")
    from openai.types.shared import ErrorObject
    err = ErrorObject(code="rate_limited", message="too fast",
                      param=None, type="rate_limit_error")
    assert err.code == "rate_limited"
    assert openai.types.ErrorObject is ErrorObject


def test_user_declared_error_object_wins_over_auto_detect(tmp_path):
    """If a user explicitly declares `$shared.models.error_object: SomeType`
    in stainless.yml, that wins — auto-detect doesn't override."""
    # Write a tiny fixture inline.
    fix = tmp_path / "fixture"
    fix.mkdir()
    (fix / "openapi.yml").write_text("""\
openapi: 3.0.0
info: { title: t, version: 1.0.0 }
servers: [{ url: https://api.t.test }]
paths:
  /things:
    get:
      operationId: listThings
      responses:
        "200": { description: ok, content: { application/json: { schema: { type: object } } } }
        "4XX":
          description: error
          content: { application/json: { schema: { $ref: "#/components/schemas/CommonError" } } }
        "default":
          description: default error
          content: { application/json: { schema: { $ref: "#/components/schemas/CommonError" } } }
components:
  schemas:
    CommonError:
      type: object
      required: [message, code]
      properties:
        message: { type: string }
        code: { type: string }
    MyCustomError:
      type: object
      required: [reason]
      properties:
        reason: { type: string }
""")
    (fix / "stainless.yml").write_text("""\
organization:
  name: t-sdk
resources:
  $shared:
    models:
      error_object: MyCustomError
  things:
    methods:
      list: { endpoint: "get /things" }
targets:
  python:
    package_name: t
environments:
  production: https://api.t.test
""")
    out = tmp_path / "sdk"
    _gen(fix / "openapi.yml", fix / "stainless.yml", out)
    shared = (out / "t" / "types" / "shared.py").read_text()
    # User said MyCustomError; auto-detect would have picked CommonError
    assert "class ErrorObject(BaseModel):" in shared
    assert "    reason:" in shared          # MyCustomError's field
    assert "    code:" not in shared        # CommonError's field, not used


def test_no_promotion_when_only_one_op_has_4xx(tmp_path):
    """Heuristic threshold: a one-off 4XX ref isn't a "common error". No
    auto-promotion in that case — the model is just emitted per-op."""
    fix = tmp_path / "fixture"
    fix.mkdir()
    (fix / "openapi.yml").write_text("""\
openapi: 3.0.0
info: { title: t, version: 1.0.0 }
servers: [{ url: https://api.t.test }]
paths:
  /things:
    get:
      operationId: listThings
      responses:
        "200": { description: ok, content: { application/json: { schema: { type: object } } } }
        "4XX":
          description: error
          content: { application/json: { schema: { $ref: "#/components/schemas/OneOffError" } } }
components:
  schemas:
    OneOffError:
      type: object
      properties: { message: { type: string }, code: { type: string } }
""")
    (fix / "stainless.yml").write_text("""\
organization:
  name: t-sdk
resources:
  things:
    methods:
      list: { endpoint: "get /things" }
targets:
  python:
    package_name: t
environments:
  production: https://api.t.test
""")
    out = tmp_path / "sdk"
    _, api = _gen(fix / "openapi.yml", fix / "stainless.yml", out)
    # One ref → no auto-promotion. shared_models stays empty.
    assert api.shared_models == {}
