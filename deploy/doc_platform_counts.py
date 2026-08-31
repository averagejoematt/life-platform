#!/usr/bin/env python3
"""deploy/doc_platform_counts.py — the /api/platform_stats literal sync (#3101), extracted
from sync_doc_metadata.py (#3384 — the host file sits at zero module-size headroom).

The credibility numbers served at /api/platform_stats (rendered on the /method/ pages —
the surface a skeptic cross-checks against the public repo) are stamped into the GENERATED
module lambdas/web/platform_counts.py. Hand-editing rotted (2026-07-01: 303 claimed tests
vs ~1,290 actual), so sync_doc_metadata rewrites the discovered literals; judgment /
live-AWS fields (monthly_cost, review_grade, active_secrets, site_pages…) are never
touched here.

THE #3384 EXEMPTION. The reconcile bot on main is the counter module's single writer
(#3101): `agent_commit.sh` refuses the file, so a branch is policy-FORBIDDEN to commit
the very literal that goes stale the moment its own PR adds a test. #2982 dropped
`tests/**` from docs-ci's pull_request trigger so test-ONLY PRs never meet the gate — but
a mixed code+tests PR enters through a code-path trigger and `--check` sweeps the whole
tree, counter included. That PR cannot go green either way (hit live 2026-08-31 on
PR #3383). So: on a `pull_request` event, staleness in a PR_EXEMPT_FIELDS literal is
reported as a visible INFO line (prefix "  i ") that --check does not count as drift.
Push/main runs — and every other literal, on every event — stay fully enforced, so a
wrong count on main still reds main's own run and the bot's ownership is unchanged.

PR_EXEMPT_FIELDS is EXACTLY {"test_count"}; widening it, or honouring the exemption on
any other event, is pinned shut by tests/test_docs_ci_owns_doc_gates.py.
"""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "lambdas" / "web" / "platform_counts.py"

# The bot-owned (#3101) literals a pull_request run reports instead of failing on (#3384).
# Exactly one field by design — see the module docstring and the pinning tests.
PR_EXEMPT_FIELDS = frozenset({"test_count"})


def _is_pr_event() -> bool:
    """True only inside a GitHub Actions `pull_request` run (GITHUB_EVENT_NAME is set by
    Actions on every job; locally it is absent, so local runs always enforce)."""
    return os.environ.get("GITHUB_EVENT_NAME") == "pull_request"


def sync(values: dict, dry_run: bool, path: Path = PATH) -> list[str]:
    """Rewrite the discovered literals in lambdas/web/platform_counts.py (#3101).

    Returned display-line prefixes are the contract with sync_doc_metadata's --check:
      "  ~" — drift (counted, fails --check; --apply rewrites it)
      "  !" — a field's literal is missing from the module (loud, never skipped)
      "  i" — the #3384 PR-event exemption: stale, named, but NOT counted as drift
    """
    if not path.exists():
        return [f"  SKIP (not found): {path}"]
    src = path.read_text(encoding="utf-8")
    changes = []
    for field, value in values.items():
        if value is None:
            continue
        pattern = rf'("{field}": )\d+'
        m = re.search(pattern, src)
        if not m:
            changes.append(f"  ! DISCOVERED_COUNTS field {field!r} not found (literal int expected)")
            continue
        old = int(m.group(0).split(":")[1])
        if old == int(value):
            continue
        if field in PR_EXEMPT_FIELDS and _is_pr_event():
            changes.append(
                f"  i PR-EXEMPT {field}: {old} → {int(value)} — bot-owned literal (#3101), skipped on pull_request; "
                f"the reconcile bot on main enforces + rewrites it (#3384)"
            )
            continue
        src = re.sub(pattern, rf"\g<1>{int(value)}", src, count=1)
        changes.append(f"  ~ DISCOVERED_COUNTS {field}: {old} → {int(value)}")
    if any(c.startswith("  ~") for c in changes) and not dry_run:
        path.write_text(src, encoding="utf-8")
    return changes
