"""tests/test_root_clutter_guard.py — #1652: the root-clutter ratchet guard (D1).

The tree self-documents: a newcomer reading `ls` at the root can tell load-bearing dirs
from support dirs without opening the README (docs/ENGINEERING_STANDARDS.md §1 "Repo
cleanliness"). This guard is the ratchet that keeps that true — it pins an ALLOWLIST of
sanctioned first-party top-level directories, each with a one-line reason, and FAILS CI
when a NEW, unlisted top-level directory appears in the git index.

Ratchet semantics (the tree can only get better, never worse):

  * A new tracked top-level dir that is NOT on the allowlist -> FAIL. Fix by adding it to
    ALLOWLIST WITH a real one-line reason, or by not committing it at the repo root.
  * Deleting a top-level dir is ALWAYS allowed — the guard asserts the tracked set is a
    SUBSET of the allowlist, never equality. A sibling cleanup story (#1648 S1-S3) that
    prunes the tree never reds this guard; prune the now-stale allowlist entry in the same
    PR for hygiene, but nothing forces it (so the two stories can't deadlock each other).

Scope = git-tracked directories only (via `git ls-files`), so gitignored build/scratch
output (.venv/, cdk.out/, qa-screenshots/, datadrops/, __pycache__/, …) is structurally
out of scope and can never trip the guard.

The allowlist below is the sanctioned set as of #1652, cross-checked against
docs/REPO_STRUCTURE.md (the canonical top-level registry). The AC's aspirational "≤~10
after S1-S3" is a target for the sibling cleanup stories; this guard's only job is to stop
the tree getting worse while they land — it does NOT delete or count dirs.
"""

import os
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

# Sanctioned first-party top-level directories: name -> why it is kept.
# Adding a new top-level dir REQUIRES adding it here with a real reason (D1 ratchet).
# Cross-checked against docs/REPO_STRUCTURE.md; support dirs also carry a one-line README.
ALLOWLIST = {
    # --- Load-bearing: the running system ---
    "lambdas": "All Lambda source (ingestion/compute/email/web/operational/intelligence) + shared modules, bundled per #781.",
    "mcp": "MCP server — domain tool modules (tools_*.py) wired in registry.py.",
    "cdk": "Infrastructure-as-code — the 9 CDK stacks; the only sanctioned way infra changes.",
    "site": "v4 static site (Cockpit/Story/Evidence), deployed to S3 + CloudFront.",
    "deploy": "Build/deploy scripts — build_bundle.py, deploy_*.sh, restart_pipeline.py, smoke tests, lib/.",
    "scripts": "Operational helpers — v4_build_*.py site generators + migration/reporting tooling.",
    "tests": "pytest (unit/contract/structural) + Playwright visual_qa.py + AI-vision QA.",
    "docs": "Architecture, runbooks, ADRs, schema — the docs-as-code source of truth.",
    "config": "Runtime config catalogs the lambdas load (schemas, user_goals.json genesis/baseline, feature configs).",
    # --- Sanctioned support (each carries a README.md explaining why it is kept) ---
    "ci": "CI support data — lambda_map.json (source-file -> function -> stack mapping) + related CI manifests.",
    "handovers": "Session handover docs — HANDOVER_LATEST.md is the live driver; prior ones dated + archived.",
    "remediation": "Self-healing agent (agent.py/automerge.py) driven by .github/workflows/remediation-agent.yml.",
    "assets": "Repo-level static asset(s) — the platform icon (site/OG images live under the S3 generated/ prefix, not here).",
    "ingest": "Local macOS launchd drop-folder watchers for manual data uploads (operator-machine tooling).",
    "setup": "One-time OAuth/credential setup scripts per integration — the DR/operator toolkit.",
    "seeds": "Test/dev bootstrap data generators (kept JSON seeds) for DynamoDB state.",
    "infra": "IAM policy/trust JSON snapshots (infra/iam/) — the audit record of the GitHub-Actions OIDC roles.",
    # --- Tooling / repo config ---
    ".github": "GitHub Actions workflows, composite actions, CODEOWNERS, dependabot — the CI/CD control plane.",
    ".claude": "Claude Code project config — agents, slash commands, settings (checked-in harness config).",
}


def _tracked_top_level_dirs():
    """The set of top-level directories that currently carry git-tracked files."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    dirs = set()
    for path in out.split("\0"):
        if not path:
            continue
        head, sep, _rest = path.partition("/")
        if sep:  # path has a directory component -> head is a top-level dir
            dirs.add(head)
    return dirs


def _unlisted(tracked, allowlist):
    """Pure ratchet check: tracked top-level dirs that are not on the allowlist."""
    return sorted(set(tracked) - set(allowlist))


# --- A. THE RATCHET (real tree) ---------------------------------------------------------
def test_no_unlisted_top_level_dir():
    """A new tracked top-level dir must be added to ALLOWLIST with a reason (D1 ratchet)."""
    tracked = _tracked_top_level_dirs()
    unlisted = _unlisted(tracked, ALLOWLIST)
    plural = len(unlisted) != 1
    assert not unlisted, (
        "New unlisted top-level director%s in the git index: %s.\n"
        "Add %s to ALLOWLIST in tests/test_root_clutter_guard.py WITH a one-line reason, "
        "or don't commit at the repo root (see docs/ENGINEERING_STANDARDS.md §1)."
        % ("ies" if plural else "y", unlisted, "them" if plural else "it")
    )


def test_allowlist_reasons_are_nonempty():
    """Every allowlist entry states WHY the dir is kept — a reasonless allowlist is decorative."""
    missing = sorted(d for d, reason in ALLOWLIST.items() if not (reason and reason.strip()))
    assert not missing, "ALLOWLIST entries need a non-empty reason: %s" % missing


# --- B. THE LOGIC (synthetic, guard-red) ------------------------------------------------
def test_guard_flags_a_new_unlisted_dir():
    """A dir absent from the allowlist is reported (the guard actually catches regressions)."""
    assert _unlisted({"lambdas", "totally_new_dir"}, ALLOWLIST) == ["totally_new_dir"]


def test_guard_allows_deletion_below_the_allowlist():
    """A tree that is a strict subset of the allowlist passes — pruning dirs never reds CI."""
    shrunk = set(list(ALLOWLIST)[:3])
    assert _unlisted(shrunk, ALLOWLIST) == []
