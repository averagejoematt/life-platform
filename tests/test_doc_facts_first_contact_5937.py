"""#5937 — CLAUDE.md's first-contact claims, and the proof each new rule can FAIL.

The 2026-11-13 /review full found CLAUDE.md saying the Deploy job needs "manual approval"
(ci-cd.yml: code ships on green, ADR-158), a format command missing `qa/` (ci-lint.yml's
Format gate checks it), and a status stamp 11 days / 191 commits behind main — all under
a green `check_doc_facts.py`. Every test here plants the ACTUAL stale literal and asserts
the rule fires, then asserts the corrected literal passes (#1189/#2578: a rule nobody has
watched fail is not known to be able to fail).
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location("_doc_facts_first_contact_5937", ROOT / "scripts" / "doc_facts_first_contact.py")
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

CI_CD = fc.CI_CD_YML.read_text(encoding="utf-8")
CI_LINT = fc.CI_LINT_YML.read_text(encoding="utf-8")
LIVE_CLAUDE = fc.CLAUDE_MD.read_text(encoding="utf-8")

STALE_CICD = (
    "`.github/workflows/ci-cd.yml`: Lint → Test → Plan → Deploy (manual approval, GitHub Environment `production`) "
    "→ Smoke → auto-rollback; OIDC auth, no long-lived keys.\n"
)
STALE_FORMAT = "**Format gate (ENFORCED)** — CI runs `black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/` (line-length 140).\n"


# ── rule 1: manual approval ──────────────────────────────────────────────────


def test_manual_approval_rule_reds_on_the_original_cicd_sentence():
    hits = fc.manual_approval_hits(STALE_CICD, CI_CD)
    assert len(hits) == 1 and "CLAUDE.md:1:" in hits[0]


def test_manual_approval_rule_passes_when_the_sentence_names_deploy_iam_or_iam():
    ok1 = "Code ships on green; the one manual approval left is `deploy-iam` (GitHub Environment `production`).\n"
    ok2 = "The only manual approval is the additive IAM deploy.\n"
    assert fc.manual_approval_hits(ok1, CI_CD) == []
    assert fc.manual_approval_hits(ok2, CI_CD) == []


def test_manual_approval_is_judged_per_sentence_not_per_line():
    """IAM named in a DIFFERENT sentence on the same line must not excuse the claim."""
    line = "Deploy needs manual approval. The IAM job is separate.\n"
    assert len(fc.manual_approval_hits(line, CI_CD)) == 1


def test_manual_approval_rule_reds_when_the_ci_cd_header_stops_saying_no_approval():
    header_changed = CI_CD.replace("NO manual approval", "a manual approval")
    hits = fc.manual_approval_hits("nothing relevant\n", header_changed)
    assert len(hits) == 1 and "re-key" in hits[0]


# ── rule 2: format command ───────────────────────────────────────────────────


def test_format_dirs_are_derived_from_the_ci_lint_format_gate_step():
    dirs = fc.ci_format_dirs(CI_LINT)
    assert dirs and "qa/" in dirs and "lambdas/" in dirs


def test_format_rule_reds_on_the_original_command_missing_qa():
    hits = fc.format_command_hits(STALE_FORMAT, CI_LINT)
    assert len(hits) == 1 and "qa/" in hits[0]


def test_format_rule_passes_on_the_derived_command():
    fixed = f"CI runs `black --check {' '.join(fc.ci_format_dirs(CI_LINT))}` (line-length 140).\n"
    assert fc.format_command_hits(fixed, CI_LINT) == []


def test_format_rule_reds_when_blind():
    assert len(fc.format_command_hits("no command here\n", CI_LINT)) == 1
    assert "went blind" in fc.format_command_hits(STALE_FORMAT, "jobs: {}\n")[0]


# ── the live CLAUDE.md passes both blocking rules ─────────────────────────────


def test_live_claude_md_passes_both_blocking_rules():
    assert fc.manual_approval_hits(LIVE_CLAUDE, CI_CD) == []
    assert fc.format_command_hits(LIVE_CLAUDE, CI_LINT) == []


# ── rule 3 (warn-only): status-stamp age ─────────────────────────────────────


def test_status_stamp_is_found_on_the_live_claude_md():
    assert fc.status_stamp(LIVE_CLAUDE) is not None


def test_status_stamp_warns_at_the_review_state():
    """The review's own numbers: 11 days and 191 commits behind (inputs fixed, no clock read)."""
    warns = fc.status_stamp_warnings("2026-11-02", "2026-11-13", 191)
    assert len(warns) == 1 and "11d and 191 commits" in warns[0]


def test_status_stamp_needs_both_thresholds():
    assert fc.status_stamp_warnings("2026-11-02", "2026-11-13", 40) == []  # quiet fortnight
    assert fc.status_stamp_warnings("2026-11-12", "2026-11-13", 300) == []  # busy day
    assert fc.status_stamp_warnings("2026-11-12", "2026-11-12", 0) == []


def test_status_stamp_warns_when_the_line_is_missing():
    assert fc.status_stamp("**Status:** see handovers/HANDOVER_LATEST.md\n") is None
    assert "went blind" in fc.status_stamp_warnings(None, "2026-11-13", 0)[0]
