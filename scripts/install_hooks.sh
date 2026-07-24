#!/usr/bin/env bash
# scripts/install_hooks.sh — Install git hooks (pre-commit + commit-msg)
#
# Installs a pre-commit hook that:
#   1. Format gate (#785/CLAUDE-02): black --check + ruff on staged Python — matches
#      CI's Lint job so an unformatted/unsorted file can't red main after the fact
#   2. Runs `deploy/sync_doc_metadata.py --apply` (Item 3) — the single source of
#      truth for platform facts across ALL docs (ARCHITECTURE.md, CLAUDE.md,
#      .claude/README.md, PLATFORM_STATS, ...), not just ARCHITECTURE.md
#   3. Stages whatever the sync touched so counts are always correct in commits
#
# ...and a commit-msg hook that:
#   4. Conventional-Commits gate (#1663): rejects a commit subject that isn't
#      `<type>(<optional-scope>): <subject>` so the convention is mechanical, not
#      cultural. Shell-only (no Node/husky) to match this repo's toolchain.
#
# Run once after cloning or when hooks need to be refreshed.
#
# Usage: bash scripts/install_hooks.sh
#
# v1.0.0 — 2026-03-10 (Item 3, board review sprint v3.5.0)
# v1.1.0 — 2026-07-06 (#785: pre-commit black+ruff format gate)
# v1.2.0 — 2026-07-08 (#818: hook now calls sync_doc_metadata.py --apply directly,
#          matching docs/CONVENTIONS.md — the update_architecture_header.sh
#          indirection is retired, it was a same-behavior wrapper)
# v1.3.0 — 2026-07-24 (#1663: add a shell commit-msg Conventional-Commits gate)

set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_DIR="$PROJ_ROOT/.git/hooks"
HOOK_FILE="$HOOK_DIR/pre-commit"
MSG_HOOK_FILE="$HOOK_DIR/commit-msg"

if [[ ! -d "$HOOK_DIR" ]]; then
  echo "[ERROR] .git/hooks not found. Are you in a git repo?"
  exit 1
fi

cat > "$HOOK_FILE" << 'EOF'
#!/usr/bin/env bash
# pre-commit hook — format gate + auto-update doc-sync literals
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

# ── Doc-sync (#818: hook runs sync_doc_metadata.py directly — this IS the
#    documented behavior in docs/CONVENTIONS.md, no wrapper indirection) ──────
if [[ -f "$PROJ_ROOT/deploy/sync_doc_metadata.py" ]]; then
  echo "[pre-commit] Running sync_doc_metadata.py --apply..."
  python3 "$PROJ_ROOT/deploy/sync_doc_metadata.py" --apply 2>&1 | sed 's/^/  /'

  # Stage whatever the sync touched (it may write any of these, not just
  # ARCHITECTURE.md — see the RULES table in sync_doc_metadata.py)
  SYNCED_CHANGED=$(git -C "$PROJ_ROOT" diff --name-only -- docs/ CLAUDE.md .claude/README.md lambdas/web/site_api_common.py || true)
  if [[ -n "$SYNCED_CHANGED" ]]; then
    git -C "$PROJ_ROOT" add $SYNCED_CHANGED
    echo "[pre-commit] Staged doc-sync updates:"
    echo "$SYNCED_CHANGED" | sed 's/^/    /'
  fi
else
  echo "[pre-commit] ⚠ deploy/sync_doc_metadata.py not found — skipping doc-sync" >&2
fi

exit 0
EOF

chmod +x "$HOOK_FILE"

# ── commit-msg hook (#1663): Conventional-Commits gate ────────────────────────
# Separate heredoc, distinct marker (MSGEOF) + variable ($MSG_HOOK_FILE) so the
# pre-commit freshness check (deploy/session_postflight.py, which extracts the
# FIRST `$HOOK_FILE` << 'EOF' block) is unaffected. Shell-only — the repo has no
# Node dev dependency for hooks, so husky/commitlint would be new machinery.
cat > "$MSG_HOOK_FILE" << 'MSGEOF'
#!/usr/bin/env bash
# commit-msg hook — Conventional-Commits gate (#1663)
# Installed by: bash scripts/install_hooks.sh
#
# Rejects a commit whose subject isn't `<type>(<optional-scope>): <subject>`,
# with the exact type set this repo uses. Machine-generated subjects (merge,
# revert, fixup!/squash!/amend!) are exempt. Bypass in a real emergency with
# `git commit --no-verify`.

MSG_FILE="$1"

# Subject = first line that is neither blank nor a comment.
SUBJECT="$(grep -vE '^[[:space:]]*#' "$MSG_FILE" | grep -vE '^[[:space:]]*$' | head -n1)"

# Skip subjects git itself generates.
case "$SUBJECT" in
  "Merge "* | "Revert "* | "fixup! "* | "squash! "* | "amend! "*) exit 0 ;;
esac

# type(optional-scope)!: subject  — types are the set actually used here.
PATTERN='^(feat|fix|chore|docs|refactor|test|ci|build|perf|style|revert)(\([a-z0-9._-]+\))?!?: .+'
if printf '%s' "$SUBJECT" | grep -qE "$PATTERN"; then
  exit 0
fi

{
  echo "[commit-msg] ❌ subject is not a Conventional Commit:"
  echo "    $SUBJECT"
  echo ""
  echo "  Expected:  <type>(<optional-scope>): <subject>"
  echo "  Types:     feat fix chore docs refactor test ci build perf style revert"
  echo "  Examples:  feat(coaching): add streak card"
  echo "             fix: correct sleep-duration rounding"
  echo "             docs(readme): fix a broken link"
  echo ""
  echo "  Bypass in a genuine emergency with: git commit --no-verify"
} >&2
exit 1
MSGEOF

chmod +x "$MSG_HOOK_FILE"

echo "✅  Hooks installed:"
echo "      pre-commit  → $HOOK_FILE"
echo "      commit-msg  → $MSG_HOOK_FILE"
echo "    On every commit: doc-sync literals (Lambda/tool/ADR counts, versions) auto-update,"
echo "    and the commit subject is checked for a Conventional-Commits prefix."
echo ""
echo "    To test immediately:"
echo "      python3 deploy/sync_doc_metadata.py --apply"
