#!/usr/bin/env bash
# Post-publish: commit + tag + push + GitHub Release for stainful v0.4.0.
# Run this AFTER `uv publish` succeeds. Idempotent against transient failure
# (tag-exists / release-exists are skipped, not errors).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="0.4.0"
TAG="v$VERSION"

# 1. Verify PyPI has v0.4.0 (no point committing the release if it isn't live)
echo "==> Verifying PyPI has stainful==$VERSION"
if ! uv run --no-project --refresh --with "stainful==$VERSION" \
    python -c "import stainful; assert stainful.__version__ == '$VERSION'" \
    2>/dev/null; then
  echo "error: PyPI does not have stainful==$VERSION yet. Run 'uv publish' first." >&2
  exit 1
fi

# 2. Commit the release (pyproject + CHANGELOG + uv.lock + README + drafts + memory)
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "==> Committing release: $TAG"
  git add -A
  git commit -m "release: $TAG

See CHANGELOG.md [$VERSION] for the full set of changes since 0.3.0.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
else
  echo "==> Nothing to commit (already committed)"
fi

# 3. Tag (idempotent)
if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "==> Tag $TAG already exists"
else
  echo "==> Tagging $TAG"
  git tag -a "$TAG" -m "stainful $TAG"
fi

# 4. Push commit + tag
echo "==> Pushing main"
git push origin main
echo "==> Pushing $TAG"
git push origin "$TAG"

# 5. GitHub Release with CHANGELOG section as notes
NOTES_FILE="$(mktemp -t stainful-$VERSION-notes.XXXXXX.md)"
trap 'rm -f "$NOTES_FILE"' EXIT
uv run python - <<PY >"$NOTES_FILE"
import re, pathlib
text = pathlib.Path("CHANGELOG.md").read_text()
m = re.search(r"^## \[$VERSION\][^\n]*\n(.*?)(?=^## \[)", text, re.M | re.S)
print((m.group(1) if m else "").rstrip())
PY

if gh release view "$TAG" >/dev/null 2>&1; then
  echo "==> Release $TAG already exists — updating notes"
  gh release edit "$TAG" --notes-file "$NOTES_FILE"
else
  echo "==> Creating GitHub Release $TAG"
  gh release create "$TAG" \
    --title "$TAG — SDK + docs + MCP server from one stainless.yml" \
    --notes-file "$NOTES_FILE"
fi

echo
echo "✅ Release $TAG complete"
echo "   PyPI:    https://pypi.org/project/stainful/$VERSION/"
echo "   GitHub:  https://github.com/stainlu/stainful/releases/tag/$TAG"
echo
echo "Announcement drafts (refresh the links if needed, then post):"
echo "   docs/announcement/hackernews-show-hn.md"
echo "   docs/announcement/reddit-python.md"
