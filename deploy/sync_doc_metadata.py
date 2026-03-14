#!/usr/bin/env python3
"""
deploy/sync_doc_metadata.py — Single source of truth for platform metadata across all docs.

THE PROBLEM THIS SOLVES:
  Platform facts (tool count, Lambda count, secret count, alarms, version, schedule times)
  live in 6+ docs. Any change means manually hunting down every occurrence. Today's audit
  found 19 stale facts across ARCHITECTURE, INFRASTRUCTURE, RUNBOOK, COST_TRACKER,
  DECISIONS, DATA_DICTIONARY, SLOs after a single session.

THE SOLUTION:
  One authoritative dict (PLATFORM_FACTS) → applied to all docs via targeted replacements.
  Run at the END of any session where platform facts changed.

USAGE:
  python3 deploy/sync_doc_metadata.py          # dry run (shows diff, writes nothing)
  python3 deploy/sync_doc_metadata.py --apply  # apply changes

WHAT IT UPDATES:
  - Version + date in all doc headers
  - Lambda count, tool count, module count, secret count, alarm count
  - Secret state (active vs deleted)
  - Secrets Manager cost line

WHAT IT DOES NOT UPDATE (requires human judgment):
  - Schedule times (EventBridge cron changes need ARCHITECTURE + RUNBOOK table edits)
  - IAM role names (structural changes, not counters)
  - New features or ADRs (always human-written)
  - CHANGELOG entries (always human-written)
  - INCIDENT_LOG entries (always human-written)

v1.0.0 — 2026-03-14 (post doc-audit that found 19 stale facts)
"""

import re
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# ══════════════════════════════════════════════════════════════════════════════
# PLATFORM FACTS — update this dict when platform state changes
# This is the ONLY place these numbers should live.
# ══════════════════════════════════════════════════════════════════════════════

PLATFORM_FACTS = {
    # Core counts
    "version":          "v3.7.15",
    "date":             "2026-03-13",
    "lambda_count":     42,
    "tool_count":       116,
    "module_count":     31,       # mcp/ modules
    "secret_count":     10,       # active secrets (verified by r8_p0_verify.sh)
    "alarm_count":      47,       # CloudWatch alarms
    "data_sources":     19,
    "cdk_stacks":       8,
    "iam_roles":        43,

    # Secret state
    "api_keys_status":  "PERMANENTLY DELETED 2026-03-14",

    # Cost
    "secrets_cost":     "$4.00",  # secret_count × $0.40
    "secrets_cost_note": "10 active secrets × $0.40/secret/month. `api-keys` permanently deleted 2026-03-14.",
}

# ══════════════════════════════════════════════════════════════════════════════
# REPLACEMENT RULES
# Each rule: (doc_path, search_pattern, replacement_template)
# Templates may use {key} references to PLATFORM_FACTS.
# Patterns use regex; replacements are literal (no regex groups needed).
# ══════════════════════════════════════════════════════════════════════════════

RULES = [

    # ── ARCHITECTURE.md ──────────────────────────────────────────────────────
    (
        "docs/ARCHITECTURE.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version} — {tool_count} tools, {module_count}-module MCP package, "
        "{data_sources} data sources, {lambda_count} Lambdas, {secret_count} secrets, "
        "{alarm_count} alarms, {cdk_stacks} CDK stacks deployed)",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"MCP Server Lambda \(\d+ tools, 1024 MB\)",
        "MCP Server Lambda ({tool_count} tools, 1024 MB)",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"MCP Lambda \(\d+ tools\)",
        "MCP Lambda ({tool_count} tools)",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"\d+-module package structure:",
        "{module_count}-module package structure:",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"mcp/                            ← MCP server package \(\d+ modules\)",
        "mcp/                            ← MCP server package ({module_count} modules)",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"MCP_TOOL_CATALOG\.md           ← All \d+ tools with params",
        "MCP_TOOL_CATALOG.md           ← All {tool_count} tools with params",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"\*\*~\d+ metric alarms\*\*",
        "**~{alarm_count} metric alarms**",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"CloudWatch metric alarms: \*\*~\d+ total\*\*",
        "CloudWatch metric alarms: **~{alarm_count} total**",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"\*\*\d+ active secrets\*\*[^\n]*",
        "**{secret_count} active secrets** at $0.40/month each = **~{secrets_cost}/month**",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"Secrets Manager \([^)]+\) \| ~\$[\d.]+",
        "Secrets Manager ({secret_count} active secrets) | ~{secrets_cost}",
    ),

    # ── INFRASTRUCTURE.md ────────────────────────────────────────────────────
    (
        "docs/INFRASTRUCTURE.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version} — {lambda_count} Lambdas, {secret_count} active secrets, "
        "{tool_count} MCP tools, ~{alarm_count} alarms)",
    ),
    (
        "docs/INFRASTRUCTURE.md",
        r"\| Tools \| \d+ across \d+ modules \|",
        "| Tools | {tool_count} across {module_count} modules |",
    ),
    (
        "docs/INFRASTRUCTURE.md",
        r"## Secrets Manager \([^)]+\)",
        "## Secrets Manager ({secret_count} active secrets)",
    ),
    (
        "docs/INFRASTRUCTURE.md",
        r"CloudWatch alarms \| ~\d+ metric alarms",
        "CloudWatch alarms | ~{alarm_count} metric alarms",
    ),

    # ── RUNBOOK.md ────────────────────────────────────────────────────────────
    (
        "docs/RUNBOOK.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version} — {tool_count} MCP tools, {module_count}-module package, "
        "{lambda_count} Lambdas, {data_sources} data sources)",
    ),

    # ── COST_TRACKER.md ──────────────────────────────────────────────────────
    (
        "docs/COST_TRACKER.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version})",
    ),
    (
        "docs/COST_TRACKER.md",
        r"\| \*\*Secrets Manager\*\* \| \$[\d.]+ \|[^\n]+",
        "| **Secrets Manager** | {secrets_cost} | {secrets_cost_note} |",
    ),

    # ── MCP_TOOL_CATALOG.md ──────────────────────────────────────────────────
    (
        "docs/MCP_TOOL_CATALOG.md",
        r"\*\*Version:\*\* [^\|]+ \| \*\*Last updated:\*\* [^\|]+ \| \*\*Total tools:\*\* \d+",
        "**Version:** {version} | **Last updated:** {date} | **Total tools:** {tool_count}",
    ),

    # ── DATA_DICTIONARY.md ───────────────────────────────────────────────────
    (
        "docs/DATA_DICTIONARY.md",
        r"\*\*Version:\*\* [^\|]+ \| \*\*Last updated:\*\* \d{4}-\d{2}-\d{2}",
        "**Version:** {version} | **Last updated:** {date}",
    ),

    # ── SLOs.md ──────────────────────────────────────────────────────────────
    (
        "docs/SLOs.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version})",
    ),

    # ── DECISIONS.md ─────────────────────────────────────────────────────────
    (
        "docs/DECISIONS.md",
        r"\*Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)\*",
        "*Last updated: {date} ({version})*",
    ),

    # ── SCHEMA.md ────────────────────────────────────────────────────────────
    (
        "docs/SCHEMA.md",
        r"\*\*Last updated:\*\* \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "**Last updated:** {date} ({version} — {tool_count} MCP tools, {data_sources} data sources, {lambda_count} Lambdas, 12 cached tools)",
    ),
]


def apply_facts(template: str) -> str:
    """Replace {key} placeholders in template with PLATFORM_FACTS values."""
    result = template
    for key, val in PLATFORM_FACTS.items():
        result = result.replace("{" + key + "}", str(val))
    return result


def process_doc(rel_path: str, dry_run: bool) -> list[str]:
    """Apply all matching rules to a doc. Returns list of change descriptions."""
    full_path = ROOT / rel_path
    if not full_path.exists():
        return [f"  SKIP (not found): {rel_path}"]

    original = full_path.read_text(encoding="utf-8")
    current = original
    changes = []

    for doc, pattern, replacement_template in RULES:
        if doc != rel_path:
            continue
        replacement = apply_facts(replacement_template)
        new = re.sub(pattern, replacement, current)
        if new != current:
            # Find what changed for reporting
            old_match = re.search(pattern, current)
            if old_match:
                old_text = old_match.group(0)[:80]
                new_text = replacement[:80]
                changes.append(f"  ~ {old_text!r}\n    → {new_text!r}")
            current = new

    if current != original and not dry_run:
        full_path.write_text(current, encoding="utf-8")

    return changes


def main():
    dry_run = "--apply" not in sys.argv
    mode = "DRY RUN (pass --apply to write changes)" if dry_run else "APPLYING CHANGES"

    print(f"\n{'='*60}")
    print(f"  sync_doc_metadata.py — {mode}")
    print(f"  Platform version: {PLATFORM_FACTS['version']} ({PLATFORM_FACTS['date']})")
    print(f"  Lambdas: {PLATFORM_FACTS['lambda_count']}  Tools: {PLATFORM_FACTS['tool_count']}  "
          f"Secrets: {PLATFORM_FACTS['secret_count']}  Alarms: {PLATFORM_FACTS['alarm_count']}")
    print(f"{'='*60}\n")

    # Get unique docs to process
    docs_to_process = sorted(set(doc for doc, _, _ in RULES))
    total_changes = 0

    for rel_path in docs_to_process:
        changes = process_doc(rel_path, dry_run)
        if changes:
            print(f"[{rel_path}]")
            for c in changes:
                print(c)
            print()
            total_changes += len(changes)
        else:
            print(f"[{rel_path}] — already in sync ✓")

    print(f"\n{'='*60}")
    if total_changes == 0:
        print("  ✅ All docs already in sync with PLATFORM_FACTS.")
    elif dry_run:
        print(f"  Found {total_changes} change(s). Run with --apply to write.")
    else:
        print(f"  ✅ Applied {total_changes} change(s) across {len(docs_to_process)} docs.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
