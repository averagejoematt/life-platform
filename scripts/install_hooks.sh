#!/usr/bin/env bash
# scripts/install_hooks.sh — Install git pre-commit hook
#
# Installs a pre-commit hook that:
#   1. Format gate (#785/CLAUDE-02): black --check + ruff on staged Python — matches
#      CI's Lint job so an unformatted/unsorted file can't red main after the fact
#   2. Auto-updates ARCHITECTURE.md Lambda + tool counts (Item 3)
#   3. Stages the updated ARCHITECTURE.md so the count is always correct in commits
#
# Run once after cloning or when hooks need to be refreshed.
#
# Usage: bash scripts/install_hooks.sh
#
# v1.0.0 — 2026-03-10 (Item 3, board review sprint v3.5.0)
# v1.1.0 — 2026-07-06 (#785: pre-commit black+ruff format gate)

set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_DIR="$PROJ_ROOT/.git/hooks"
HOOK_FILE="$HOOK_DIR/pre-commit"

if [[ ! -d "$HOOK_DIR" ]]; then
  echo "[ERROR] .git/hooks not found. Are you in a git repo?"
  exit 1
fi

cat > "$HOOK_FILE" << 'EOF'
#!/usr/bin/env bash
# pre-commit hook — format gate + auto-update ARCHITECTURE.md header counts
# Installed by: bash scripts/install_hooks.sh

PROJ_ROOT="$(git rev-parse --show-toplevel)"

# ── Format gate (#785 / CLAUDE-02) ────────────────────────────────────────────
# Match CI's Lint job (black --check + ruff) on staged Python before the commit
# lands, so an unformatted or unsorted file can't red main and email a failure.
# Only staged files under the CI-formatted roots; fail-open if the tools aren't
# installed so a bare checkout can still commit.
if command -v black >/dev/null 2>&1 && command -v ruff >/dev/null 2>&1; then
  STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM | grep -E '^(lambdas|mcp|cdk|tests|scripts|deploy)/.*\.py$' || true)
  if [[ -n "$STAGED_PY" ]]; then
    if ! black --check $STAGED_PY; then
      echo "[pre-commit] ❌ black would reformat staged files — run: black $STAGED_PY" >&2
      exit 1
    fi
    if ! ruff check $STAGED_PY; then
      echo "[pre-commit] ❌ ruff check failed on staged files — run: ruff check --fix $STAGED_PY" >&2
      exit 1
    fi
    echo "[pre-commit] ✓ black + ruff clean on staged Python"
  fi
else
  echo "[pre-commit] ⚠ black/ruff not installed — skipping format gate" >&2
fi

if [[ -f "$PROJ_ROOT/scripts/update_architecture_header.sh" ]]; then
  echo "[pre-commit] Updating ARCHITECTURE.md header..."
  bash "$PROJ_ROOT/scripts/update_architecture_header.sh" 2>&1 | sed 's/^/  /'

  # Stage the updated file if it was changed
  if git diff --name-only "$PROJ_ROOT/docs/ARCHITECTURE.md" | grep -q "ARCHITECTURE.md"; then
    git add "$PROJ_ROOT/docs/ARCHITECTURE.md"
    echo "[pre-commit] ARCHITECTURE.md staged with updated counts."
  fi
fi

exit 0
EOF

chmod +x "$HOOK_FILE"
echo "✅  Pre-commit hook installed: $HOOK_FILE"
echo "    On every commit: ARCHITECTURE.md Lambda + tool counts auto-update."
echo ""
echo "    To test immediately:"
echo "      bash scripts/update_architecture_header.sh"
