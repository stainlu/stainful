#!/usr/bin/env bash
# Fetch real Stainless-generated SDKs at PINNED SHAs into tests/oracles/.
#
# These are the conformance oracles (QUALITY_PLAN §3). They are public and
# permissively licensed; we *compare against* them, never copy them into the
# generator. Pinned so the wind-down of hosted Stainless cannot move them.
#
# Idempotent: re-running checks out the pinned SHA again, no-op if already there.
# Partial + sparse clone so we pull only src/ + tests/ + packaging, not history.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/tests/oracles"
mkdir -p "$DEST"

# name | repo | pinned sha | sparse paths
ORACLES=(
  "onebusaway-python-sdk|OneBusAway/python-sdk|c4ce16d7f64ebc6e938481284ce0784c19d5c2cb|src tests pyproject.toml api.md"
  "openai-python|openai/openai-python|658be644f48028ea3c7b1545034470fda75a70ba|src tests pyproject.toml"
  "anthropic-sdk-python|anthropics/anthropic-sdk-python|a28508b8c22d806688e4d4faa97ca60ce04ce745|src tests pyproject.toml"
  # openai-node v6.38.0 — the canonical Stainless-emitted TypeScript SDK.
  # Pinned for stability against the Stainless wind-down. Used as the
  # oracle for the TypeScript emitter (stage-2 from the v0.4 roadmap).
  "openai-node|openai/openai-node|87f3b041c80917f8d416c69f9237ac07239da577|src tests package.json tsconfig.json api.md"
)

want="${1:-all}"   # pass a name to fetch just one (e.g. onebusaway-python-sdk)

for spec in "${ORACLES[@]}"; do
  IFS='|' read -r name repo sha paths <<<"$spec"
  [[ "$want" != "all" && "$want" != "$name" ]] && continue
  dir="$DEST/$name"

  if [[ -d "$dir/.git" ]] && [[ "$(git -C "$dir" rev-parse HEAD 2>/dev/null)" == "$sha" ]]; then
    echo "✓ $name already at $sha"
    continue
  fi

  echo "→ $name @ $sha (sparse: $paths)"
  rm -rf "$dir"
  git clone --quiet --filter=blob:none --no-checkout \
    "https://github.com/$repo" "$dir"
  git -C "$dir" sparse-checkout init --cone
  # shellcheck disable=SC2086
  git -C "$dir" sparse-checkout set $paths
  git -C "$dir" fetch --quiet --depth 1 origin "$sha"
  git -C "$dir" checkout --quiet "$sha"
  echo "✓ $name -> $(git -C "$dir" rev-parse --short HEAD)"
done

echo "oracles in $DEST"
