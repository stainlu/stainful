"""TypeScript emitter — v0.1 slice (Stage 2 from the v0.4 roadmap).

Same IR; different renderer. Generates a TypeScript SDK that
tsc-cleanly type-checks. v0.1 scope: simple types + simple methods +
JSON request/response + path params + query params. Streaming /
pagination / multipart / discriminated unions / webhooks deferred to
v0.2-TS slices.

The `tsc` check runs against a locally-installed TypeScript (npm install
inside the temp dir). Skipped when `node` or `npm` aren't available
(local-only CI lane).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from stainful.config import load_config
from stainful.emit.typescript import emit_ts
from stainful.ir.builder import build_ir
from stainful.openapi.loader import load_spec

EXAMPLE = Path(__file__).parent.parent / "examples" / "onebusaway"


def _gen(tmp_path: Path) -> Path:
    api = build_ir(
        load_spec(str(EXAMPLE / "openapi.yml")),
        load_config(str(EXAMPLE / "stainless.yml")),
    )
    emit_ts(api, str(tmp_path))
    return tmp_path / "onebusaway"


# ----- source-level checks (no Node dep) ------------------------------------


def test_emits_expected_files(tmp_path):
    root = _gen(tmp_path)
    assert (root / "package.json").exists()
    assert (root / "tsconfig.json").exists()
    assert (root / "src" / "index.ts").exists()
    assert (root / "src" / "client.ts").exists()
    # Vendored runtime
    for f in ("client.ts", "resource.ts", "error.ts", "index.ts"):
        assert (root / "src" / "_core" / f).exists(), f
    # One resource per top-level config resource
    assert (root / "src" / "resources" / "agency.ts").exists()


def test_client_class_uses_brand_pascalcase(tmp_path):
    """`<Brand>` matches what openai-node does — `OnebusawaySDK` matches
    the Python emitter's class name."""
    root = _gen(tmp_path)
    src = (root / "src" / "client.ts").read_text()
    assert "export class OnebusawaySDK extends BaseClient" in src
    # And the resource accessor is in place.
    assert "agency: AgencyResource;" in src


def test_resource_methods_use_camelcase(tmp_path):
    """TS convention is camelCase for method names — `current_time.retrieve`
    in Python becomes `currentTime.retrieve` in TS (resource snake_case
    stays as field name; method is camelCase). For OneBusAway most
    methods are already single-word (`retrieve`, `list`)."""
    root = _gen(tmp_path)
    src = (root / "src" / "resources" / "agency.ts").read_text()
    # The method `retrieve` is single-word, stays the same in camelCase.
    assert "retrieve(agency_id: string" in src
    # Method body calls the runtime
    assert "this._client.request<" in src
    assert "method: 'GET'" in src
    assert "path: `/api/where/agency/${agency_id}.json`" in src


def test_response_types_imported_precisely(tmp_path):
    """Only USED type names import from `../types` — `tsc` is strict about
    unused imports (with isolatedModules + strict)."""
    root = _gen(tmp_path)
    src = (root / "src" / "resources" / "agency.ts").read_text()
    assert "import type { AgencyRetrieveResponse } from '../types';" in src


def test_property_names_with_dots_are_quoted(tmp_path):
    """OneBusAway's `Config` has `git.branch` etc. (literal dots in the
    wire name). In TS, those must be quoted: `"git.branch"?: string`."""
    root = _gen(tmp_path)
    src = (root / "src" / "types" / "index.ts").read_text()
    assert '"git.branch"?: string' in src
    # And bare identifiers still aren't quoted.
    assert "id?: string;" in src


# ----- tsc end-to-end (requires npm) ----------------------------------------


def _has_npm() -> bool:
    return shutil.which("npm") is not None and shutil.which("node") is not None


def _tsc_clean(root: Path) -> None:
    """Install TypeScript locally and `tsc --noEmit` the generated SDK.
    Raises an assertion error if tsc reports any diagnostics."""
    subprocess.run(
        ["npm", "init", "-y"], cwd=root, check=True, capture_output=True,
    )
    subprocess.run(
        ["npm", "install", "--save-dev", "--no-audit", "--no-fund",
         "--silent", "typescript@5.6"],
        cwd=root, check=True, capture_output=True,
    )
    result = subprocess.run(
        ["npx", "tsc", "--noEmit"],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"tsc reported errors:\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_generated_sdk_tsc_clean(tmp_path):
    """OneBusAway → tsc-clean TS. This is the actual quality bar for
    the v0.1 slice."""
    _tsc_clean(_gen(tmp_path))


@pytest.mark.skipif(not _has_npm(), reason="npm/node not available")
def test_chat_fixture_tsc_clean(tmp_path):
    """The chat fixture exercises `oneOf` discriminated unions (events)
    and JSON request bodies — broader than OneBusAway's read-only GETs.
    Same emitter must handle it tsc-cleanly."""
    api = build_ir(
        load_spec(str(
            Path(__file__).parent / "fixtures" / "chat" / "openapi.yml"
        )),
        load_config(str(
            Path(__file__).parent / "fixtures" / "chat" / "stainless-config.yml"
        )),
    )
    emit_ts(api, str(tmp_path))
    _tsc_clean(tmp_path / "chat")
