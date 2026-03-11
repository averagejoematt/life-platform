#!/usr/bin/env bash
# scripts/install_hooks.sh — Install git pre-commit hook
#
# Installs a pre-commit hook that:
#   1. Auto-updates ARCHITECTURE.md Lambda + tool counts (Item 3)
#   2. Stages the updated ARCHITECTURE.md so the count is always correct in commits
#
# Run once after cloning or when hooks need to be refreshed.
#
# Usage: bash scripts/install_hooks.sh
#
# v1.0.0 — 2026-03-10 (Item 3, board review sprint v3.5.0)

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
# pre-commit hook — auto-update ARCHITECTURE.md header counts
# Installed by: bash scripts/install_hooks.sh

PROJ_ROOT="$(git rev-parse --show-toplevel)"

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
