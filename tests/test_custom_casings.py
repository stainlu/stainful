"""`custom_casings:` config support — Stainless's compound-name override
hook (oracle: `openai_id_string: OpenAIIDString` in real openai configs).
Without it, every non-hardcoded brand emits the wrong casing
(`Openai`/`AcmeAi`/etc.) — that's the #1 adoption blocker after v0.3.0
for anyone whose brand isn't in our 4-entry compound table.
"""

from __future__ import annotations

from pathlib import Path

from stainful.config import load_config
from stainful.emit.python import emit
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

FIX = Path(__file__).parent / "fixtures" / "custom_casings"


def _gen(tmp_path: Path):
    api = build_ir(load_spec(str(FIX / "openapi.yml")),
                   load_config(str(FIX / "stainless.yml")))
    emit(api, str(tmp_path))
    return tmp_path


def test_loader_parses_custom_casings():
    """Both dict-style and list-of-singletons normalize to the same dict."""
    cfg = load_config(str(FIX / "stainless.yml"))
    assert cfg.custom_casings == {
        "acme_ai_sdk": "AcmeAISDK",
        "acme_widget_id_string": "AcmeWidgetIDString",
    }


def test_brand_uses_custom_casings(tmp_path):
    """Heuristic gives `AcmeAiSDK` (Ai lowercase); custom_casings flips it
    to `AcmeAISDK`. This is the adoption-blocker case."""
    out = _gen(tmp_path)
    init = (out / "acme" / "__init__.py").read_text()
    assert "AcmeAISDK" in init
    assert "AsyncAcmeAISDK" in init
    assert "AcmeAiSDK" not in init   # heuristic must NOT leak through
    client = (out / "acme" / "_client.py").read_text()
    assert "class AcmeAISDK(SyncAPIClient)" in client
    assert "class AsyncAcmeAISDK(AsyncAPIClient)" in client


def test_pascal_uses_custom_casings_for_types(tmp_path):
    """`AcmeWidgetIDString` (a component schema) should keep the user-
    declared casing, not the heuristic `AcmeWidgetIdString`."""
    out = _gen(tmp_path)
    # The schema renders into a shared type via _shared_models OR via
    # path-named usage. Easiest check: scan the whole types/ tree.
    found_correct = False
    found_wrong = False
    for f in (out / "acme" / "types").rglob("*.py"):
        src = f.read_text()
        if "AcmeWidgetIDString" in src:
            found_correct = True
        if "AcmeWidgetIdString" in src:
            found_wrong = True
    assert found_correct, "expected AcmeWidgetIDString in generated types"
    assert not found_wrong, "heuristic casing must not leak through"


def test_user_casings_dont_leak_across_emits(tmp_path):
    """Module-level `_USER_CASINGS` is replaced (not merged) at each
    `_Emitter()` construction, so two back-to-back emits with different
    casings don't pollute each other."""
    _gen(tmp_path / "a")  # installs acme-ai-sdk's casings into _USER_CASINGS
    # Now emit a different fixture; its brand should NOT be affected by
    # the acme-ai-sdk casings.
    paginated_fix = Path(__file__).parent / "fixtures" / "paginated"
    api2 = build_ir(load_spec(str(paginated_fix / "openapi.yml")),
                    load_config(str(paginated_fix / "stainless.yml")))
    out2 = tmp_path / "b"
    emit(api2, str(out2))
    init = (out2 / "paginated" / "__init__.py").read_text()
    # paginated-sdk has no custom_casings → heuristic `PaginatedSDK`
    assert "PaginatedSDK" in init
    # And acme's casing must NOT have leaked
    assert "AcmeAI" not in init
