"""#3919 — (1) operating-calendar.yml names EXIT_STALE_CARRY in its own case arm; (2) an UNSTATED
calibration on a run dated on/after CALIBRATION_REQUIRED_FROM is a MISSING run for the
carry-forward clock; (3) the skill text and the code agree.

Mutation control for (2): set `CALIBRATION_REQUIRED_FROM = date.max` → the post-cutoff UNSTATED run
advances `qs` to 2026-09-20 and `test_an_unstated_run_after_the_cutoff_advances_nothing` reds."""

from __future__ import annotations

import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))

import review_carry_forward as cf  # noqa: E402
from test_review_anchors_3603 import _run, _write_runs  # noqa: E402 — the sibling's grades-artifact fixtures

REPO = os.path.join(os.path.dirname(__file__), "..")


def test_the_workflow_has_an_explicit_arm_for_exit_4():
    text = open(os.path.join(REPO, ".github/workflows/operating-calendar.yml"), encoding="utf-8").read()
    arms = re.findall(r"^\s*([0-9*])\)\s*echo\s*\"::(?:notice|error)::([^\"]*)\"", text, flags=re.M)
    by = dict(arms)
    assert "4" in by, f"no 4) arm — exit 4 falls through to the generic branch: {sorted(by)}"
    assert "EXIT_STALE_CARRY" in by["4"] and "unexpected" not in by["4"].lower()
    assert "*" in by, "the fallback arm must survive for genuinely unknown exits"


def test_an_unstated_run_before_the_cutoff_still_counts_history_is_not_retroactively_disqualified():
    when, run = _run("2026-09-12", {"qs": "A"})
    assert cf.calibration_verdict(run) == cf.UNSTATED
    assert cf.run_counts(run, when) is True
    assert cf.scratch_dates([(when, run)])["qs"] == date(2026, 9, 12)


def test_an_unstated_run_after_the_cutoff_advances_nothing():
    """The reproduction (box 3): feed the clock a post-cutoff grades JSON with no calibration block —
    before #3919 `qs` read 2026-09-20; now it reads the last run that actually calibrated (or was
    grandfathered)."""
    old_when, old = _run("2026-09-12", {"qs": "A"})
    new_when, new = _run("2026-09-20", {"qs": "A"})
    assert cf.calibration_verdict(new) == cf.UNSTATED and new_when >= cf.CALIBRATION_REQUIRED_FROM
    assert cf.run_counts(new, new_when) is False
    assert cf.scratch_dates([(old_when, old), (new_when, new)])["qs"] == date(2026, 9, 12), "the UNSTATED run advanced the clock"
    calibrated = dict(new, calibration={"verdict": "CALIBRATED", "planted_false_findings": {"n": 2, "confirmed_by_verifiers": []}})
    assert cf.scratch_dates([(old_when, old), (new_when, calibrated)])["qs"] == date(2026, 9, 20), "a CALIBRATED run must still advance it"


def test_the_entry_qualifier_reads_the_artifacts_own_date(tmp_path):
    repo = _write_runs(tmp_path, [_run("2026-09-12", {"qs": "A"}), _run("2026-09-20", {"qs": "A"})])
    d = os.path.join(repo, cf.GRADES_DIR)
    names = sorted(n for n in os.listdir(d) if cf.GRADES_RE.match(n))
    assert [cf.calibrated_run(os.path.join(d, n)) for n in names] == [True, False], names


def test_the_report_says_a_post_cutoff_unstated_run_counts_as_missing(tmp_path):
    repo = _write_runs(tmp_path, [_run("2026-09-20", {"qs": "A"})])
    lines, _ = cf.carry_forward_report(date(2026, 9, 21), repo)
    text = "\n".join(lines)
    assert "MISSING run" in text and "#3919" in text, text


def test_the_skill_text_and_the_code_agree_on_the_cutoff():
    skill = open(os.path.join(REPO, ".claude/skills/review/SKILL.md"), encoding="utf-8").read()
    assert (
        cf.CALIBRATION_REQUIRED_FROM.isoformat() in skill and "UNSTATED" in skill
    ), "the skill must state the same mandatory-from date the code enforces"
