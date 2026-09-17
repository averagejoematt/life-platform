"""tests/test_reset_cadence_refusal_3601.py — the minimum-cycle-length refusal (#3601).

WHY A REFUSAL AND NOT A WARNING. Measured 2026-09-16 off `CYCLE_GENESES` itself rather
than restated from the issue:

    17 cycles on record, 16 re-anchors over 158 days (2026-04-01 -> 2026-09-06)
    gap days: median 5.5   mean 9.9   min 1   max 61
    rate: 9.2 per QUARTER  (3.04 per 30 days)

`docs/PROPORTIONALITY.md` row 86 prices the reset machinery against "a few times a
quarter" — roughly a third of the measured rate — so every reset-machinery demote trigger
in that ledger has been judged against the wrong cadence.

THE WINDOW IS AN OWNER RULING, NOT A NUMBER PICKED IN THE CODE. Owner, 2026-09-05,
recorded on #3606 as ruling 1: *"Reset cadence: minimum cycle length 30 days. The reset
tool refuses a re-anchor inside 30 days without an explicit override flag (#3601)."*

A warning does not stop a typo. The 2026-09-04 mis-dated genesis cost a SECOND full reset
inside 24h (Session U), and cycle 15 lasted three days — so "Day 4 of cycle 15" never
existed and every clause written against it was unfalsifiable for a whole cycle.

THE OVERRIDE IS NOT A BARE --force. `--reanchor-of <date>` makes the operator NAME the
genesis being superseded, so a deliberate correction states what it corrects and a
mistyped date cannot satisfy it by accident. That asymmetry is the whole design and it is
asserted below in both directions.
"""

from __future__ import annotations

import datetime
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "deploy") not in sys.path:
    sys.path.insert(0, str(ROOT / "deploy"))
if str(ROOT / "lambdas") not in sys.path:
    sys.path.insert(0, str(ROOT / "lambdas"))

import restart_cadence as rp  # noqa: E402  (#1665: extracted from restart_pipeline)

_TODAY = datetime.date(2026, 9, 16)
_PRIOR = "2026-09-06"  # cycle 17 genesis — 10 days old on _TODAY
_OLD = "2026-08-01"  # 46 days old on _TODAY


def test_MUST_FAIL_a_reanchor_inside_the_window_is_REFUSED():
    """The defect in one assertion: a second reset ten days into a cycle just happens."""
    with pytest.raises(rp.CadenceRefusal) as exc:
        rp.check_cadence("2026-09-20", _PRIOR, None, today=_TODAY)
    msg = str(exc.value)
    assert "MINIMUM CYCLE LENGTH (30d) NOT MET" in msg
    assert _PRIOR in msg, "the refusal must NAME the prior genesis — box 1's wording"
    assert "10d" in msg, "the refusal must state how long the outgoing cycle actually ran"
    assert f"--reanchor-of {_PRIOR}" in msg, "the refusal must hand the operator the exact override, not just deny"


def test_the_override_NAMING_the_prior_genesis_proceeds():
    line = rp.check_cadence("2026-09-20", _PRIOR, _PRIOR, today=_TODAY)
    assert "OVERRIDE ACCEPTED" in line
    assert "correction of that genesis, not as a new cycle's worth of evidence" in line


def test_the_override_with_the_WRONG_date_is_still_refused():
    """The asymmetry that makes this an override rather than a --force.

    `2026-09-05` is a real genesis in the registry (cycle 16), so this is not a
    nonsense value — it is the plausible off-by-one an operator actually makes, and
    a flag that accepts it is a flag that accepts a typo.
    """
    with pytest.raises(rp.CadenceRefusal) as exc:
        rp.check_cadence("2026-09-20", _PRIOR, "2026-09-05", today=_TODAY)
    assert "does not name the genesis this reset supersedes" in str(exc.value)


def test_a_cycle_PAST_the_window_needs_no_flag():
    """The control in the opposite direction — a check that refuses everything is not a
    check, it is an outage."""
    line = rp.check_cadence("2026-09-20", _OLD, None, today=_TODAY)
    assert "OK" in line and "46d" in line


def test_the_boundary_is_inclusive_at_exactly_thirty_days():
    at = (_TODAY - datetime.timedelta(days=rp.MIN_CYCLE_DAYS)).isoformat()
    under = (_TODAY - datetime.timedelta(days=rp.MIN_CYCLE_DAYS - 1)).isoformat()
    assert "OK" in rp.check_cadence("2026-09-20", at, None, today=_TODAY)
    with pytest.raises(rp.CadenceRefusal):
        rp.check_cadence("2026-09-20", under, None, today=_TODAY)


def test_an_unreadable_prior_genesis_SKIPS_rather_than_refusing():
    """Fail-open on a malformed input, and say so. A reset blocked because a date string
    could not be parsed is an outage caused by the guard, and the guard is not what the
    operator came to fix."""
    line = rp.check_cadence("2026-09-20", "not-a-date", None, today=_TODAY)
    assert "SKIPPED" in line


def test_the_window_is_the_OWNER_RULING_not_a_number_chosen_in_the_code():
    """30 is not an engineering judgement and must not read like one."""
    assert rp.MIN_CYCLE_DAYS == 30
    src = (ROOT / "deploy" / "restart_cadence.py").read_text(encoding="utf-8")
    block = src[src.index("# ── #3601: the minimum cycle length") : src.index("MIN_CYCLE_DAYS = 30")]
    assert "#3606" in block and "2026-09-05" in block, "the ruling's provenance is not recorded beside the constant"
    assert "minimum cycle length 30 days" in block


def test_the_preflight_runs_BEFORE_the_completeness_preflights():
    """Ordering is load-bearing, and this change's first cut got it wrong.

    With the check at [0c] the 2026-09-16 dry run never reached it — Step 0 aborted first
    on an unclassified partition. "Should this happen at all" is cheaper to answer and
    more fundamental than "is the machinery complete", and a refusal an operator only
    meets after fixing two unrelated things is a refusal they meet late.
    """
    src = (ROOT / "deploy" / "restart_pipeline.py").read_text(encoding="utf-8")
    assert src.index("# Step 0a (#3601)") < src.index("# Step 0 (#1234)"), "the cadence check no longer runs first"
    assert src.index("# Step 0a (#3601)") < src.index("# Step 0b (#3671)")


def test_a_RE_CONVERGE_of_the_current_genesis_is_never_refused():
    """`--apply` with no `--genesis` re-runs the pipeline against the SAME genesis — the
    documented recovery path for a partial run. The ruling is about how often the
    experiment STARTS OVER, not how often the tooling is re-run, so this must not be
    gated at all."""
    block = (ROOT / "deploy" / "restart_cadence.py").read_text(encoding="utf-8")
    assert "if target == old_genesis:" in block, "a re-converge is not exempted — it would be refused as a re-anchor"
    assert "re-converging the CURRENT genesis" in block


@pytest.mark.serial
def test_END_TO_END_the_real_pipeline_refuses_and_writes_nothing():
    """Box 1, against the real script rather than the pure function.

    Observed 2026-09-16 with cycle 17 ten days old: `--apply --genesis 2026-09-20` exits
    **6** and aborts at [0a], before Step 1 fetches anything. With
    `--reanchor-of 2026-09-06` it proceeds past [0a] and stops later for an unrelated
    reason. This re-runs the refusing half only — the accepting half would continue into
    a real pipeline.
    """
    proc = subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "restart_pipeline.py"), "--genesis", "2026-09-20", "--apply"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 6, f"expected the cadence exit code 6, got {proc.returncode}\n{proc.stdout[-2000:]}"
    assert "CADENCE PREFLIGHT FAILED" in proc.stdout
    assert "ABORTING before any reset step — nothing was fetched, written or deployed" in proc.stdout
    # It must abort BEFORE any later step announces itself.
    assert not re.search(r"^\[1\]|Step 1: fetch", proc.stdout, re.M), "the pipeline advanced past the refusal"


# ── #3601 box 2 (partial): the monthly close prints the cadence ──────────────


def test_the_monthly_close_DERIVES_the_cadence_and_matches_the_ledger_row():
    """The number in `docs/PROPORTIONALITY.md` row 86 and the number the tool prints must
    be the same number, because one is a copy of the other.

    Row 86 is corrected to 9.2/quarter and a 5.5d median. Both come from here. The median
    is the one that bit: `sorted(gaps)[n//2]` returns the UPPER of the two middles on an
    even n — 6 where the true median is 5.5 — so the doc and its source disagreed by half
    a day on first write.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from monthly_close import reset_cadence

    rc = reset_cadence(datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), today=_TODAY)
    assert not rc.get("error"), rc
    assert round(rc["per_quarter"], 1) == 9.2
    assert rc["median_gap"] == 5.5
    row86 = (ROOT / "docs" / "PROPORTIONALITY.md").read_text(encoding="utf-8")
    assert "~9.2 per QUARTER" in row86, "row 86 no longer states the measured cadence"
    assert "median gap **5.5d**" in row86
    assert "a few times a quarter" not in row86, "the pre-#3601 claim is back in the ledger"


def test_the_cadence_read_cannot_report_a_VACUOUS_zero():
    """A registry that parses empty must be an error, not 'zero resets'. A cadence of zero
    and a cadence it could not read are opposite facts and would print identically."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import monthly_close

    src = (ROOT / "scripts" / "monthly_close.py").read_text(encoding="utf-8")
    body = src[src.index("def reset_cadence") : src.index("def main(argv")]
    assert "parsed EMPTY" in body, "an empty CYCLE_GENESES would be reported as a clean zero"
    assert monthly_close.reset_cadence.__doc__ and "PARTIAL" in monthly_close.reset_cadence.__doc__


def test_the_UNSHIPPED_half_of_box_2_says_so_in_the_output():
    """`$ per reset` and the DEMOTE-candidate list are box 2 and are NOT delivered. The
    output names them rather than letting a shorter report read as a complete one — the
    same rule the rest of this repo applies to a degraded check."""
    src = (ROOT / "scripts" / "monthly_close.py").read_text(encoding="utf-8")
    assert "NOT PRINTED, and not invented" in src
    assert "DEMOTE-candidate list" in src
