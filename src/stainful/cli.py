"""`stainful generate` — the single CLI entry point (DESIGN.md §5).

Wires the four pipeline functions. Unbuilt slices fail loud with a clear message
rather than producing a half-broken SDK.
"""

from __future__ import annotations

import argparse
import sys

from stainful import __version__
from stainful.errors import StainfulError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stainful")
    parser.add_argument("--version", action="version", version=f"stainful {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate a Python SDK from a spec + config.")
    gen.add_argument("--spec", required=True, help="Path to the OpenAPI 3.x document.")
    gen.add_argument("--config", required=True, help="Path to stainless.yml / stainful.yml.")
    gen.add_argument("--out", required=True, help="Output directory for the SDK.")

    doc = sub.add_parser("docs", help="Emit a Markdown API doc (api.md) from a spec + config.")
    doc.add_argument("--spec", required=True, help="Path to the OpenAPI 3.x document.")
    doc.add_argument("--config", required=True, help="Path to stainless.yml / stainful.yml.")
    doc.add_argument(
        "--out", default="api.md",
        help="Output file path for the docs (default: ./api.md).",
    )

    mcp = sub.add_parser(
        "mcp",
        help="Emit a Model Context Protocol (MCP) server that exposes the SDK's methods as tools.",
    )
    mcp.add_argument("--spec", required=True, help="Path to the OpenAPI 3.x document.")
    mcp.add_argument("--config", required=True, help="Path to stainless.yml / stainful.yml.")
    mcp.add_argument(
        "--out", required=True,
        help="Output Python file path (typically <sdk_dir>/<pkg>/mcp_server.py).",
    )

    gents = sub.add_parser(
        "generate-ts",
        help="Generate a TypeScript SDK from a spec + config (Stage 2 / experimental v0.1 slice).",
    )
    gents.add_argument("--spec", required=True, help="Path to the OpenAPI 3.x document.")
    gents.add_argument("--config", required=True, help="Path to stainless.yml / stainful.yml.")
    gents.add_argument("--out", required=True, help="Output directory for the SDK.")

    args = parser.parse_args(argv)

    if args.command == "generate":
        return _generate(args.spec, args.config, args.out)
    if args.command == "docs":
        return _docs(args.spec, args.config, args.out)
    if args.command == "mcp":
        return _mcp(args.spec, args.config, args.out)
    if args.command == "generate-ts":
        return _generate_ts(args.spec, args.config, args.out)
    return 2


def _generate(spec_path: str, config_path: str, out_dir: str) -> int:
    # Imports are local so partial slices don't break `--version`/`--help`.
    from stainful.config.loader import load_config
    from stainful.emit.python import emit
    from stainful.ir.builder import build_ir
    from stainful.openapi.loader import load_spec

    try:
        config = load_config(config_path)
        spec = load_spec(spec_path)
        api = build_ir(spec, config)
        emit(api, out_dir)
    except StainfulError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Generated SDK at {out_dir}")
    return 0


def _docs(spec_path: str, config_path: str, out_path: str) -> int:
    from stainful.config.loader import load_config
    from stainful.emit.markdown import emit_docs
    from stainful.ir.builder import build_ir
    from stainful.openapi.loader import load_spec

    try:
        config = load_config(config_path)
        spec = load_spec(spec_path)
        api = build_ir(spec, config)
        emit_docs(api, out_path)
    except StainfulError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote docs to {out_path}")
    return 0


def _generate_ts(spec_path: str, config_path: str, out_dir: str) -> int:
    from stainful.config.loader import load_config
    from stainful.emit.typescript import emit_ts
    from stainful.ir.builder import build_ir
    from stainful.openapi.loader import load_spec

    try:
        config = load_config(config_path)
        spec = load_spec(spec_path)
        api = build_ir(spec, config)
        emit_ts(api, out_dir)
    except StainfulError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Generated TS SDK at {out_dir}")
    return 0


def _mcp(spec_path: str, config_path: str, out_path: str) -> int:
    from stainful.config.loader import load_config
    from stainful.emit.mcp import emit_mcp
    from stainful.ir.builder import build_ir
    from stainful.openapi.loader import load_spec

    try:
        config = load_config(config_path)
        spec = load_spec(spec_path)
        api = build_ir(spec, config)
        emit_mcp(api, out_path)
    except StainfulError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote MCP server to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
