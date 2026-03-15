#!/usr/bin/env bash
# scripts/update_architecture_header.sh
#
# Thin wrapper kept for backwards compatibility.
# All counter auto-discovery is now done in deploy/sync_doc_metadata.py
# which is the single source of truth for all platform facts.
#
# v2.0.0 — 2026-03-14 (R11 item 3: delegate to sync_doc_metadata.py)

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -f "$PROJ_ROOT/deploy/sync_doc_metadata.py" ]]; then
    python3 "$PROJ_ROOT/deploy/sync_doc_metadata.py" --apply --quiet
else
    echo "[WARN] sync_doc_metadata.py not found — skipping header update"
fi
