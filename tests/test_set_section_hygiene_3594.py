"""tests/test_set_section_hygiene_3594.py — #3594: every review/incident-filed
bug or story carries a `## Set` section, and the surfaces that touch its
lifecycle (the lint, the implementer's step 6b, `/land` §5, the PR template)
all know about it.

Root-cause class closed (per the issue body): "Guard the instance, not the
set — and guards born unproven." 33 of 99 findings in the 2026-09-05
`/review full` baseline cited only the specimen issue whose class they
re-instantiated, because the issue body — the one thing a fresh-context agent
reliably reads — named only the specimen.

This is a PROCESS-layer story: no new test files over `tests/` other than this
one asserting the four surfaces changed (the issue explicitly says the
positive-control and scan-set meta-rules are NOT added — see its own text).
The linter rule itself (`rule_set_section`) is tested with full mutation
proof in tests/test_backlog_hygiene_gate.py; this file does not re-test it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPLEMENTER = REPO_ROOT / ".claude" / "agents" / "worktree-implementer.md"
LAND_SKILL = REPO_ROOT / ".claude" / "skills" / "land" / "SKILL.md"
PR_TEMPLATE = REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
HYGIENE = REPO_ROOT / "scripts" / "check_backlog_hygiene.py"
CONTRACT = REPO_ROOT / "scripts" / "backlog_contract.py"


def test_worktree_implementer_step_6b_present():
    text = IMPLEMENTER.read_text(encoding="utf-8")
    assert "6b." in text, "worktree-implementer.md must carry a step 6b for the #3594 Set-section reflex"
    assert "## Set" in text
    assert "#3594" in text


def test_land_skill_section_5_reads_the_member_list():
    text = LAND_SKILL.read_text(encoding="utf-8")
    assert "## Set" in text
    assert "instance-only" in text
    assert "partial" in text
    assert "#3594" in text


def test_pr_template_names_the_set_and_the_must_fail_case():
    text = PR_TEMPLATE.read_text(encoding="utf-8")
    assert "Set and registry" in text
    assert "Must-fail case" in text
    assert "#3594" in text


def test_hygiene_linter_carries_the_set_section_rule():
    text = HYGIENE.read_text(encoding="utf-8")
    assert "rule_set_section" in text
    m = re.search(r"^PER_ISSUE_RULES:.*?=\s*\[(.*?)\]", text, re.S | re.M)
    assert m, "could not locate the PER_ISSUE_RULES list literal — check_backlog_hygiene.py's shape changed"
    assert "rule_set_section" in m.group(1), "rule_set_section must be wired into PER_ISSUE_RULES"


def test_contract_module_owns_the_set_grammar_not_the_linter():
    """Same discipline as every other rule in this linter: the grammar lives in
    backlog_contract.py, the linter only calls it."""
    contract_text = CONTRACT.read_text(encoding="utf-8")
    assert "SET_HEADING_RE" in contract_text
    assert "set_section_text" in contract_text
    assert "set_section_has_count" in contract_text
    assert "filed_from_review_or_incident" in contract_text


def test_no_new_positive_control_or_scan_set_meta_rule_files_added():
    """The issue's own sequencing note: this story adds no guard and no test
    file beyond what proves ITS OWN four-surface change — the positive-control
    and scan-set meta-rules over tests/ are explicitly deferred to #3536's
    per-entrant proof rule, sequenced BEFORE any new guard of that shape."""
    forbidden_names = {"test_set_section_meta_gate.py", "test_positive_control_registry.py"}
    existing = {p.name for p in (REPO_ROOT / "tests").glob("*.py")}
    assert not (forbidden_names & existing), "a scan-set/positive-control meta-rule file landed — #3594 explicitly defers this"
