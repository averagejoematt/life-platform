"""tests/test_ci_run_verdicts_timeout_3678.py — the `cancelled-means-timeout` trap
(#3678, acceptance box 3): a job that hit ITS OWN `timeout-minutes` ceiling must be
told apart from a job cancelled by a `cancel-in-progress` concurrency eviction.

`scripts/ci_run_verdicts.py` already carries the #3530 discriminator for a
`cancelled` ROLLUP (superseded vs. carries-a-failure vs. indeterminate) — this file
proves the #3678 sibling: CANCELLED_TIMEOUT, at both the run-level
(`classify_cancelled_run`, fed by `check_main_green.py`/`check_ci_warnings.py`) and
the check-level (`classify_cancelled_check`, fed by `deploy/wait_pr_green.sh`, which
never has a `jobs` array — only the `startedAt`/`completedAt` `gh pr checks --json`
already attaches).

MUTATION PROOF: the same job dict flipped between three durations (well under its
ceiling, exactly at it, and with a real failing step) proves this module is
measuring something, not just returning one hardcoded answer.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import ci_run_verdicts as civ  # noqa: E402


def _job(name="Collect + deploy-critical + format", conclusion="cancelled", started="2026-09-07T18:00:00Z", completed=None, steps=None):
    return {"name": name, "conclusion": conclusion, "started_at": started, "completed_at": completed, "steps": steps or []}


# ── job_duration_seconds — pure, offline ────────────────────────────────────


def test_job_duration_seconds_computes_the_gap():
    j = _job(started="2026-09-07T18:00:00Z", completed="2026-09-07T18:15:22Z")
    assert civ.job_duration_seconds(j) == 922.0


def test_job_duration_seconds_none_on_missing_timestamps():
    assert civ.job_duration_seconds({"conclusion": "cancelled"}) is None
    assert civ.job_duration_seconds({"started_at": "2026-09-07T18:00:00Z"}) is None


def test_job_duration_seconds_none_on_unparseable_timestamps():
    assert civ.job_duration_seconds({"started_at": "not-a-date", "completed_at": "also-not"}) is None


# ── job_hit_its_own_timeout — the slack window, both directions ────────────


def test_job_hit_its_own_timeout_true_at_the_observed_incident_shape():
    """The exact #3678 incident: 15m ceiling, killed at 15m22s (22s over)."""
    j = _job(completed="2026-09-07T18:15:22Z")
    assert civ.job_hit_its_own_timeout(j, timeout_minutes=15) is True


def test_job_hit_its_own_timeout_false_when_cancelled_early():
    """A `cancel-in-progress` eviction lands seconds in, nowhere near the ceiling."""
    j = _job(completed="2026-09-07T18:00:08Z")
    assert civ.job_hit_its_own_timeout(j, timeout_minutes=15) is False


def test_job_hit_its_own_timeout_none_without_a_known_ceiling():
    j = _job(completed="2026-09-07T18:15:22Z")
    assert civ.job_hit_its_own_timeout(j, timeout_minutes=None) is None


def test_job_hit_its_own_timeout_false_for_a_non_cancelled_job():
    j = _job(conclusion="success", completed="2026-09-07T18:15:22Z")
    assert civ.job_hit_its_own_timeout(j, timeout_minutes=15) is False


def test_job_hit_its_own_timeout_none_when_duration_unknown():
    assert civ.job_hit_its_own_timeout({"conclusion": "cancelled"}, timeout_minutes=15) is None


# ── classify_cancelled_run — the run-level sibling of #3530's discriminator ──


def test_classify_cancelled_run_reproduces_pre_3678_behaviour_without_a_timeouts_map():
    """No `timeouts_by_job_name` supplied: a timed-out-shaped job (all steps green,
    conclusion cancelled) still reads SUPERSEDED — upgrading this module must not
    change any existing caller's verdict by itself."""
    jobs = [_job(completed="2026-09-07T18:15:22Z")]
    assert civ.classify_cancelled_run(jobs) == civ.CANCELLED_SUPERSEDED


def test_classify_cancelled_run_finds_timeout_when_a_ceiling_is_supplied():
    jobs = [_job(completed="2026-09-07T18:15:22Z")]
    timeouts = {"Collect + deploy-critical + format": 15}
    assert civ.classify_cancelled_run(jobs, timeouts_by_job_name=timeouts) == civ.CANCELLED_TIMEOUT


def test_classify_cancelled_run_prefers_carries_failure_over_timeout():
    """A REAL failure anywhere always wins — #3678 only refines the "nothing
    failed" branch, it never softens a genuine red."""
    jobs = [
        _job(name="a genuinely broken job", conclusion="failure", completed="2026-09-07T18:00:05Z"),
        _job(name="Collect + deploy-critical + format", completed="2026-09-07T18:15:22Z"),
    ]
    timeouts = {"Collect + deploy-critical + format": 15}
    assert civ.classify_cancelled_run(jobs, timeouts_by_job_name=timeouts) == civ.CANCELLED_CARRIES_FAILURE


def test_classify_cancelled_run_supersedes_when_duration_is_short_even_with_a_ceiling():
    jobs = [_job(completed="2026-09-07T18:00:08Z")]
    timeouts = {"Collect + deploy-critical + format": 15}
    assert civ.classify_cancelled_run(jobs, timeouts_by_job_name=timeouts) == civ.CANCELLED_SUPERSEDED


def test_classify_cancelled_run_still_indeterminate_on_no_jobs():
    assert civ.classify_cancelled_run(None, timeouts_by_job_name={"x": 15}) == civ.CANCELLED_INDETERMINATE
    assert civ.classify_cancelled_run([], timeouts_by_job_name={"x": 15}) == civ.CANCELLED_INDETERMINATE


def test_cancelled_timeout_is_not_skippable():
    """#3678: a genuine timeout is a defect to surface, never a non-verdict to
    walk past the way a supersession is."""
    assert civ.cancelled_is_skippable(civ.CANCELLED_TIMEOUT) is False


def test_describe_cancelled_names_the_timeout_class_distinctly_from_superseded():
    run = {"databaseId": 1, "headSha": "abcdef1234567890"}
    timeout_line = civ.describe_cancelled(run, civ.CANCELLED_TIMEOUT, [])
    superseded_line = civ.describe_cancelled(run, civ.CANCELLED_SUPERSEDED, [])
    assert "timeout-minutes" in timeout_line
    assert "raising or splitting" in timeout_line or "raise" in timeout_line.lower()
    assert "supersession" in superseded_line
    assert timeout_line != superseded_line


# ── classify_cancelled_check — the wait_pr_green.sh-facing sibling ─────────


def test_classify_cancelled_check_timeout_from_pr_checks_timestamps():
    timeouts = {"Collect + deploy-critical + format": 15}
    verdict = civ.classify_cancelled_check("Collect + deploy-critical + format", "2026-09-07T18:00:00Z", "2026-09-07T18:15:22Z", timeouts)
    assert verdict == civ.CANCELLED_TIMEOUT


def test_classify_cancelled_check_superseded_from_pr_checks_timestamps():
    timeouts = {"Collect + deploy-critical + format": 15}
    verdict = civ.classify_cancelled_check("Collect + deploy-critical + format", "2026-09-07T18:00:00Z", "2026-09-07T18:00:08Z", timeouts)
    assert verdict == civ.CANCELLED_SUPERSEDED


def test_classify_cancelled_check_indeterminate_without_a_known_ceiling():
    verdict = civ.classify_cancelled_check("Some unregistered check", "2026-09-07T18:00:00Z", "2026-09-07T18:15:22Z", {})
    assert verdict == civ.CANCELLED_INDETERMINATE


def test_classify_cancelled_check_indeterminate_on_missing_timestamps():
    timeouts = {"Collect + deploy-critical + format": 15}
    verdict = civ.classify_cancelled_check("Collect + deploy-critical + format", None, None, timeouts)
    assert verdict == civ.CANCELLED_INDETERMINATE


def test_describe_cancelled_check_lines_differ_by_verdict():
    lines = {
        v: civ.describe_cancelled_check("X", v) for v in (civ.CANCELLED_TIMEOUT, civ.CANCELLED_SUPERSEDED, civ.CANCELLED_INDETERMINATE)
    }
    assert len(set(lines.values())) == 3
    assert all(line.startswith("CANCEL-DIAGNOSIS X:") for line in lines.values())
