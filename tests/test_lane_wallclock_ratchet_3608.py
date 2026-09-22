"""tests/test_lane_wallclock_ratchet_3608.py — #3608 box 4: the measured bar.

THE DEFECT. "Green and fast" was graded from prose. Three numbers for the SAME
pre-merge lane, from three eras, none of them re-measured and none of them
guarded:

  * deploy/github_posture.json  `typical_seconds: 90`    (PR #2094, ~2026-08)
  * tests/conftest.py           "8,813 tests in 155s"    (stamped 2026-08-21)
  * #3678's live sampler        genuine p95 14.87min     (2026-09-07)

Measured again on 2026-09-19 for this issue: p95 = 1037s (17.28min, n=21 genuine
of 25 completed runs). The stored 90 was wrong by a factor of 11.5, and nothing
anywhere could have said so. Two side-findings from that measurement, neither of
them this issue's: the lane's genuine p95 has risen from 14.87min to 17.28min in
twelve days, and at that p95 `scripts/check_job_timeout_headroom.py` now reports
pr-checks.yml's 18-minute ceiling RED (it wants 20.74min at the 1.2 multiplier).
That is #3678's ceiling drifting again, filed there, not fixed here.

THE FIX, and what this file guards:
  1. The lane EMITS its own wall-clock (pr-checks.yml's fast-lane stamps
     LANE_START and its last step — `if: always()`, so reds are measured too —
     prints a `lane-wallclock` ::notice:: carrying one line of JSON).
  2. `deploy/write_lane_posture.py` WRITES `typical_seconds` into the posture
     file together with its provenance. A hand-typed number cannot satisfy the
     provenance assertions below.
  3. THE RATCHET: `typical_seconds` may not exceed the last measured value
     frozen here. When the lane genuinely gets slower, the writer produces a
     bigger number, this test reds by name, and a human re-freezes deliberately
     after deciding whether the slowdown is acceptable — the point is that the
     move is never silent.
"""

import json
import os
import re
from datetime import date

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POSTURE = os.path.join(REPO_ROOT, "deploy", "github_posture.json")
# NB the name: `PR_CHECKS` would match gate_census._REGISTRY_NAME's `.*_CHECKS`
# arm and mint a phantom registry gate (#3315). Renamed, never registered —
# NOT_APPLICABLE_REASONS' precedent.
PR_CHECKS_YML_PATH = os.path.join(REPO_ROOT, ".github", "workflows", "pr-checks.yml")
WRITER = os.path.join(REPO_ROOT, "deploy", "write_lane_posture.py")

# THE RATCHET. Last measured value per required check, 2026-09-21, by
# `python3 deploy/write_lane_posture.py --measure` (p95 of genuine completions
# over the trailing 30 runs). Raise ONLY with a new measurement and a new date —
# never to make a red go away.
#
# 2026-09-22 (session AQ, the #3678 recurrence a third time): re-frozen 1055s -> 1286s (p95 of n=22 genuine
# completions in the trailing 28 runs, `write_lane_posture.py --measure`); the ceiling followed to 26 min
# (21.42 x 1.2 = 25.7). The lane took #4023/#4028/#4033/#4039 in one night (11,553 premerge tests).
# 2026-09-21 (#4011, the #3678 recurrence): re-frozen 1037s -> 1055s (n=13 genuine of
# 28; 15 were timeout casualties, censored). The growth is ACCEPTED and named: the
# premerge lane reached 11,177 tests and the pre-merge step alone runs ~15.5min on the
# GitHub runner; the 18-min ceiling was re-derived to 22 in the same PR. The lane has
# no growth budget of its own (only this ceiling ratchet) — epic #3493 carries that.
#
# The fast lane was sampled twice within the hour and returned 1037s (n=21) then
# 1026s (n=20) as one run rolled out of the trailing window. The ceiling is
# frozen at the HIGHER reading: a ratchet set to the lower one would red on the
# next sample for no reason but window jitter, and a gate that reds on noise is
# a gate people learn to widen. The posture file carries whichever reading the
# writer last took; this is the bar it may not cross.
LAST_MEASURED_SECONDS_2026_09_21 = {
    "Collect + deploy-critical + format": 1286,
    "gitleaks (PR commit range only, not full history)": 12,
}

_PROVENANCE_KEYS = ("typical_measured_on", "typical_measured_by", "typical_statistic", "typical_n")


def _checks() -> list[dict]:
    with open(POSTURE, encoding="utf-8") as f:
        return json.load(f)["main_required_checks_ruleset"]["required_status_checks"]


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_every_required_check_carries_a_measured_duration_with_provenance():
    """A bare `typical_seconds` is the defect. The provenance fields are what
    make the number auditable: WHEN it was taken, BY what, WHICH statistic, over
    HOW MANY samples."""
    for check in _checks():
        ctx = check["context"]
        assert isinstance(check.get("typical_seconds"), int), f"{ctx}: typical_seconds is missing or not an int"
        for key in _PROVENANCE_KEYS:
            assert check.get(key), f"{ctx}: {key} is missing — typical_seconds must be WRITTEN by deploy/write_lane_posture.py, not typed"
        date.fromisoformat(check["typical_measured_on"])  # raises on a stub
        assert int(check["typical_n"]) >= 1, f"{ctx}: typical_n must be a real sample count"


def test_the_ratchet_reds_above_the_last_measured_value():
    for check in _checks():
        ctx = check["context"]
        ceiling = LAST_MEASURED_SECONDS_2026_09_21.get(ctx)
        assert ceiling is not None, (
            f"{ctx} is a required check with no frozen measurement in this test. Measure it "
            "(`python3 deploy/write_lane_posture.py --measure --context ...`) and add the row."
        )
        assert check["typical_seconds"] <= ceiling, (
            f"{ctx}: typical_seconds {check['typical_seconds']}s exceeds the last measured {ceiling}s "
            f"(frozen 2026-09-22). The lane got slower. Decide whether that is acceptable, then re-freeze "
            "this row WITH the new measurement date — do not widen it to clear a red."
        )


def test_the_frozen_rows_match_the_checks_that_actually_exist():
    """The other direction: a stale row here for a check that was renamed or
    retired would leave a real check unguarded while the file still looks full."""
    live = {c["context"] for c in _checks()}
    stale = set(LAST_MEASURED_SECONDS_2026_09_21) - live
    assert not stale, f"frozen rows for checks that no longer exist: {sorted(stale)}"


def test_the_lane_emits_its_own_wallclock():
    text = _read(PR_CHECKS_YML_PATH)
    assert 'echo "LANE_START=$(date +%s)"' in text, "the fast-lane no longer stamps LANE_START — it cannot measure itself"
    assert "--emit-wallclock-since" in text, "the fast-lane no longer emits its wall-clock (#3608 box 4)"
    # The emit has to ride a step that runs on failure too, or the measurement
    # is a sample of green runs only.
    emit_at = text.index("--emit-wallclock-since")
    step_start = text.rindex("      - name:", 0, emit_at)
    assert (
        "if: always()" in text[step_start:emit_at]
    ), "the wall-clock emit sits in a step without `if: always()` — reds would go unmeasured"


def test_the_gate_status_is_not_swallowed_by_the_emit():
    """#2746's lesson, applied to the step this box modified: the bundle-boot
    gate's own exit code must still fail the job. `status=$?` ... `exit $status`
    is the shape; a bare trailing command would make the gate advisory."""
    text = _read(PR_CHECKS_YML_PATH)
    emit_at = text.index("--emit-wallclock-since")
    step_start = text.rindex("      - name:", 0, emit_at)
    step = text[step_start : text.index("\n\n", emit_at) if "\n\n" in text[emit_at:] else len(text)]
    assert "status=$?" in step and "exit $status" in step, f"the wall-clock emit swallowed the gate's exit status:\n{step}"


def test_the_writer_exists_and_states_who_runs_it():
    """An instrument nobody runs is #3860's shape. The writer has to name its
    caller in its own docstring so the answer is not folklore."""
    src = _read(WRITER)
    assert "WHO RUNS IT" in src
    assert re.search(r"wrap", src, re.IGNORECASE), "the writer does not name the ritual that runs it"


# The retired literal, held HERE and only here. Both files that used to carry it
# now describe it instead of reproducing it — a text matcher reads the comment
# explaining it, and a guard whose own evidence resurrects the string it retires
# is the shape that fired four times in one night on 2026-09-16.
_RETIRED_WALLCLOCK_LITERAL = "8,813 tests in " + "155s"


def test_the_hand_stamped_duration_is_gone_from_both_files_that_carried_it():
    """The other two of the three disagreeing numbers. Neither may come back: a
    duration in a comment is unmeasurable and unratchetable by construction."""
    for rel in ("tests/conftest.py", ".github/workflows/pr-checks.yml"):
        text = _read(os.path.join(REPO_ROOT, *rel.split("/")))
        assert _RETIRED_WALLCLOCK_LITERAL not in text, (
            f"the dated wall-clock literal is back in {rel} — point at deploy/github_posture.json's "
            "written measurement instead (#3608 box 4)"
        )
