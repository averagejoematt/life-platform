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
# v1.4.0 — 2026-08-11 (#2570: the format gate resolves black/ruff at the version CI
#          pins via deploy/lib/pinned_formatters.sh instead of off bare PATH, and
#          FAILS CLOSED when the pin is missing — a PATH black 25.9.0 vs CI's
#          26.3.1 blocked commits CI would pass and reformats CI then rejected)

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

# ── Format gate (#785 / CLAUDE-02; PINNED by #2570) ───────────────────────────
# Match CI's Lint job (black --check + ruff) on staged Python before the commit
# lands, so an unformatted or unsorted file can't red main and email a failure.
#
# The tools must be the EXACT versions CI pins. This gate used to resolve them
# off bare PATH, and on 2026-08-11 that PATH black was 25.9.0 against CI's
# 26.3.1 — the two disagree on real files in this tree, so the hook refused
# commits CI would have passed and the reformat it demanded produced a tree CI
# then rejected (#2570). deploy/lib/pinned_formatters.sh reads the pin from
# requirements-dev.txt and version-verifies every candidate binary.
#
# There is deliberately NO fall back to PATH and no fail-open skip: an unpinned
# gate is worse than no gate because it lies with authority. If the pin isn't
# installed the hook says exactly that and exits 1. Emergency bypass is the
# normal git one: `git commit --no-verify`.
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM | grep -E '^(lambdas|mcp|cdk|tests|scripts|deploy)/.*\.py$' || true)
if [[ -n "$STAGED_PY" ]]; then
  PF_LIB="$PROJ_ROOT/deploy/lib/pinned_formatters.sh"
  if [[ ! -f "$PF_LIB" ]]; then
    echo "[pre-commit] ❌ $PF_LIB is missing — cannot verify the formatter pin." >&2
    echo "[pre-commit]    Refusing to run an unpinned format gate (#2570)." >&2
    exit 1
  fi
  # shellcheck source=/dev/null
  source "$PF_LIB"
  if ! BLACK_BIN="$(resolve_pinned_formatter black)"; then
    echo "[pre-commit] ❌ format gate FAILED CLOSED — no black at the pinned version (#2570)." >&2
    exit 1
  fi
  if ! RUFF_BIN="$(resolve_pinned_formatter ruff)"; then
    echo "[pre-commit] ❌ format gate FAILED CLOSED — no ruff at the pinned version (#2570)." >&2
    exit 1
  fi
  if ! "$BLACK_BIN" --check $STAGED_PY; then
    echo "[pre-commit] ❌ black would reformat staged files — run: $BLACK_BIN $STAGED_PY" >&2
    exit 1
  fi
  if ! "$RUFF_BIN" check $STAGED_PY; then
    echo "[pre-commit] ❌ ruff check failed on staged files — run: $RUFF_BIN check --fix $STAGED_PY" >&2
    exit 1
  fi
  echo "[pre-commit] ✓ black $(pinned_formatter_version black) + ruff $(pinned_formatter_version ruff) clean on staged Python"
fi

# ── Doc-sync (#818: hook runs sync_doc_metadata.py directly — this IS the
#    documented behavior in docs/CONVENTIONS.md, no wrapper indirection) ──────
if [[ -f "$PROJ_ROOT/deploy/sync_doc_metadata.py" ]]; then
  echo "[pre-commit] Running sync_doc_metadata.py --apply..."
  python3 "$PROJ_ROOT/deploy/sync_doc_metadata.py" --apply 2>&1 | sed 's/^/  /'

  # Stage whatever the sync touched (it may write any of these, not just
  # ARCHITECTURE.md — see the RULES table in sync_doc_metadata.py).
  # #3101: the counters moved to lambdas/web/platform_counts.py. Listing
  # site_api_common.py here after the move would be actively harmful — the sync no
  # longer writes it, so the only diff this pathspec could pick up would be the
  # committer's OWN unstaged edits to a hot shared module, swept in unasked.
  SYNCED_CHANGED=$(git -C "$PROJ_ROOT" diff --name-only -- docs/ CLAUDE.md .claude/README.md lambdas/web/platform_counts.py || true)
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
