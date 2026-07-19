"""Regression guard for #1325 — the main-branch ruleset + corrected written posture.

Pins two things so the fix can't silently regress:
1. docs/CONVENTIONS.md no longer describes classic branch-protection machinery on
   `main` that returns 404 live (the stale "enforce_admins:false lets Matthew
   bypass" claim, #1325's evidence finding).
2. The two read-only `gh api` GETs (branch protection, rulesets) that make the
   ruleset posture re-verifiable are present in CONVENTIONS' drift-discovery table,
   naming the created ruleset by id so a future edit can't quietly drop it.

This test only asserts repo-file content (no network/`gh` calls — CI runs offline).
The live-state assertion (does the ruleset actually still exist on GitHub) is the
GitHub-side drift-sentinel leg tracked as #1320 (epic #1355 sibling of #1325); see
the ledger row this PR adds in docs/MANAGED_WHERE_LEDGER.md.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_conventions_no_longer_claims_live_classic_branch_protection():
    txt = _read("docs/CONVENTIONS.md")
    assert (
        "enforce_admins:false` lets" not in txt
    ), "CONVENTIONS.md still describes the stale classic branch-protection posture that 404s live (#1325)"
    assert (
        "Matthew bypass but the bot is not an admin" not in txt
    ), "CONVENTIONS.md still describes dead branch-protection admin-bypass machinery (#1325)"


def test_conventions_states_the_ruleset_posture():
    txt = _read("docs/CONVENTIONS.md")
    assert "main-block-force-push-and-deletion" in txt, "CONVENTIONS.md doesn't name the live main ruleset (#1325)"
    assert "19162901" in txt, "CONVENTIONS.md doesn't pin the live ruleset id (#1325)"
    assert (
        "no required checks, no" in txt or "no PR rule" in txt
    ), "CONVENTIONS.md doesn't state the ruleset is force-push+deletion ONLY (#1325)"


def test_conventions_drift_table_has_both_github_gets():
    txt = _read("docs/CONVENTIONS.md")
    assert "branches/main/protection" in txt, "CONVENTIONS.md's drift-discovery table is missing the branch-protection GET (#1325)"
    assert "repos/<owner>/<repo>/rulesets" in txt, "CONVENTIONS.md's drift-discovery table is missing the rulesets GET (#1325)"


def test_managed_where_ledger_has_the_ruleset_row():
    txt = _read("docs/MANAGED_WHERE_LEDGER.md")
    assert "main-block-force-push-and-deletion" in txt, "MANAGED_WHERE_LEDGER.md is missing the GitHub main ruleset row (#1325)"
    assert (
        "#1320" in txt
    ), "MANAGED_WHERE_LEDGER.md's ruleset row doesn't point at the GitHub-side drift-sentinel leg story (#1320) for the automated assertion"
