"""#2639 — the gate census had a blind spot, which is the thing the gate census is for.

Two **real, enforcing** CI steps were invisible to `scripts/gate_census.py`, and both sit in
the exact job slice 2 was sampling:

    ci-lint.yml  Syntax check (py_compile)    ends `if [ "$FAILED" -gt 0 ]; then … exit 1; fi`
    ci-lint.yml  Check lambda_map coverage    ends `if [ $MISSING -gt 0 ]; then … exit 1; fi`

Neither matched `_GATE_VERB`, which recognises a gate by the TOOL it runs, so both were
counted in `steps_nongate` rather than in the inventory. The census reported 421 gates
against a true number of at least 423.

A census with a silent blind spot answers a different question than the one it appears to
answer — the exact defect class #2578 was opened to hunt, now found inside the instrument
built to hunt it.

WIDENED, NOT HAND-ADDED, because the issue is explicit that a hand-added row is the failure
this census exists to replace. `_GATE_ENFORCES` asks the direct question — does this step
DELIBERATELY EXIT NON-ZERO? — which is what "can fail the build" means, whatever tool it
uses or doesn't. Narrow on purpose: `exit 0` is a SWALLOW idiom, not a gate, and a bare
`exit` with no code is not one either.

THE ISSUE NAMED TWO. THE WIDENING FOUND TWENTY. `by_enforcement_only` — CI gates detected
ONLY by their explicit exit and by no tool verb — is 20, and `steps_nongate` fell from 53 to
38. That is the census's own false-negative rate for the verb-only detector, and it is now
computed on every run rather than discovered by hand a second time.

Box 2 was adjudicated in #2746/#2748 (a real false negative found and fixed). Box 3 —
the false-positive rate on the two large risk flags — is adjudicated HERE: a deterministic
every-3rd sample (13-of-38 `vacuous-empty`, 10-of-27 `exempt-by-incompleteness`), read
against this module's own flag definitions rather than judgement calls, wired into the
report as measured proportions with 95% Wilson intervals (`FLAG_PRECISION`,
`_wilson_interval`). Both intervals are wide and both say the same thing: most of these two
flags are noise, not all three of the sampled hits were real, actionable defects. So the
report still calls flag counts an upper bound — now with a number instead of an anecdote.
"""

from __future__ import annotations

import importlib
import json
import os
import pathlib
import sys
import textwrap

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

# `gate_census.discover_ci_gates` imports PyYAML lazily so the module stays importable
# without it — but this file builds the census at IMPORT time, which runs that path. The
# deploy-critical CI lane installs a minimal dependency set and has no yaml, so the whole
# module raised ModuleNotFoundError there and reddened a lane that had nothing to do with
# this change. Skipping is correct rather than a cop-out: the gate still runs in the full
# `test / Unit Tests` lane, where PyYAML IS installed — verified, because a guard that
# skips in every lane is the "cannot fail" pattern this very file exists to measure.
pytest.importorskip("yaml", reason="gate_census's CI-family walk needs PyYAML; the full Unit Tests lane has it")

gate_census = importlib.import_module("gate_census")
# The samples live in gate_census_precision (#2639's own extraction); gate_census
# re-exports FLAG_PRECISION but not the superseded PRIOR_FLAG_PRECISION (#2999).
gate_census_precision = importlib.import_module("gate_census_precision")

CENSUS = gate_census.build_census(pathlib.Path(_REPO))
CI_COUNTERS = (CENSUS.get("counters") or {}).get("ci") or {}
CI_GATES = [g for g in CENSUS["gates"] if g["family"] == "ci-step"]


# ── the two the issue named ──────────────────────────────────────────────────


@pytest.mark.parametrize("needle", ["Syntax check (py_compile)", "Check lambda_map coverage"])
def test_the_two_missed_enforcing_steps_are_now_in_the_inventory(needle):
    assert any(needle in g["name"] for g in CI_GATES), f"{needle!r} is still invisible to the census"


def test_they_are_detected_by_the_widened_derivation_not_a_hand_added_row():
    """Acceptance box 1. A literal step name in the source would be the failure this
    census exists to replace, so assert the source does not contain one."""
    src = (pathlib.Path(_REPO) / "scripts" / "gate_census.py").read_text()
    for needle in ("Syntax check (py_compile)", "Check lambda_map coverage"):
        assert f'"{needle}"' not in src and f"'{needle}'" not in src, f"{needle!r} is hand-listed"
    assert "_GATE_ENFORCES" in src


# ── the derivation itself, mutation-proven ───────────────────────────────────


ENFORCING_BUT_VERBLESS = textwrap.dedent("""
    name: synthetic
    on: [push]
    jobs:
      j:
        runs-on: ubuntu-latest
        steps:
          - name: Enforce a thing with no recognisable tool
            run: |
              COUNT=$(ls -1 | wc -l)
              if [ "$COUNT" -gt 9999 ]; then
                echo "::error::too many"
                exit 1
              fi
    """).strip()

NOT_A_GATE = textwrap.dedent("""
    name: synthetic
    on: [push]
    jobs:
      j:
        runs-on: ubuntu-latest
        steps:
          - name: Just print something
            run: echo "hello"
    """).strip()


def _sweep(tmp_path, workflow_yaml):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "synthetic.yml").write_text(workflow_yaml)
    return gate_census.discover_ci_gates(tmp_path)


def test_a_new_enforcing_step_with_an_unusual_verb_is_detected(tmp_path):
    """Acceptance box 5, as a MUTATION rather than a claim: plant a step that enforces
    something in plain shell with no tool this census has ever heard of, and it must be
    counted. This is the shape both real misses had."""
    gates, counters = _sweep(tmp_path, ENFORCING_BUT_VERBLESS)
    assert len(gates) == 1, f"the planted enforcing step was dropped: {counters}"
    assert counters["by_enforcement_only"] == 1
    assert counters["steps_nongate"] == 0


def test_a_step_that_cannot_fail_is_still_not_a_gate(tmp_path):
    """The control. A widening that swallows everything would inflate n and be worse than
    the undercount it replaced."""
    gates, counters = _sweep(tmp_path, NOT_A_GATE)
    assert gates == []
    assert counters["steps_nongate"] == 1
    assert counters["nongate_sample"] == ["synthetic.yml::j / Just print something"]


@pytest.mark.parametrize(
    "run,expected",
    [
        ("exit 1", True),
        ("exit 2", True),
        ("python3 -c 'import sys; sys.exit(1)'", True),
        ("python3 -c 'raise SystemExit(3)'", True),
        ("foo || exit", True),
        ("exit 0", False),
        ("echo 'exit code 0 means ok'", False),
        ("echo hello", False),
    ],
)
def test_the_enforcement_detector_is_narrow_on_purpose(run, expected):
    """`exit 0` is a SWALLOW idiom, not a gate — treating it as one would classify the
    very steps this census flags as dangerous as gates in good standing."""
    assert bool(gate_census._GATE_ENFORCES.search(run)) is expected


# ── the error bars the report now prints ─────────────────────────────────────


def test_the_widening_found_far_more_than_the_two_that_were_filed():
    """The measured false-negative rate of the verb-only detector."""
    assert CI_COUNTERS["by_enforcement_only"] >= 10, CI_COUNTERS
    assert CI_COUNTERS["by_verb_only"] > 0, "both detectors must be contributing, or one is dead"


def test_the_report_states_its_error_in_both_directions():
    """Acceptance box 4 — `n` must never read as exact."""
    report = gate_census.render_report(CENSUS)
    assert "n is a FLOOR" in report
    assert "FALSE NEGATIVES (measured)" in report
    assert "FALSE POSITIVES (sampled)" in report
    assert "UNADJUDICATED" in report


def test_the_report_quantifies_the_residual_rather_than_hand_waving_it():
    """ "we might be missing some" is not a measurement. The residual has a number."""
    report = gate_census.render_report(CENSUS)
    assert f"UNADJUDICATED: {CI_COUNTERS['steps_nongate']} workflow steps" in report
    assert f"{CI_COUNTERS['by_enforcement_only']} of" in report


def test_the_residual_labels_are_carried_so_the_adjudication_is_possible():
    """Boxes 2 and 3 need a human to read specific steps. The instrument's job is to hand
    over the list, which is what turns an unbounded worry into a finite queue."""
    sample = CI_COUNTERS.get("nongate_sample")
    assert isinstance(sample, list)
    assert len(sample) == CI_COUNTERS["steps_nongate"], "the sample must be the WHOLE residual, not a slice"
    assert all("::" in s and "/" in s for s in sample), sample[:3]


def test_the_json_output_carries_the_counters():
    """`--json` is the machine surface the residual is worked from."""
    blob = json.loads(json.dumps(CENSUS, default=str))
    assert blob["counters"]["ci"]["by_enforcement_only"] == CI_COUNTERS["by_enforcement_only"]


# ── box 3: the two flags now carry a real precision number ──────────────────


def test_the_flag_precision_registry_records_the_owners_sample():
    """RE-SAMPLED 2026-08-27 (#2999 box 2). The 2026-08-16 draw (13-of-38, 10-of-27) was
    taken at populations that had since grown to 54 and 40, and `_render_error_bars` had
    been printing its own DRIFT warning against it for eleven days. Both draws are pinned:
    the current one because it is what the report claims, and the prior one because a
    re-sample that discards the number it replaced hides whether the estimate moved."""
    vacuous = gate_census.FLAG_PRECISION["vacuous-empty"]
    assert (vacuous.n_flagged, vacuous.n_sampled, vacuous.n_fp, vacuous.n_tp) == (54, 18, 14, 4)

    incomplete = gate_census.FLAG_PRECISION["exempt-by-incompleteness"]
    assert (incomplete.n_flagged, incomplete.n_sampled, incomplete.n_fp, incomplete.n_tp) == (40, 14, 11, 3)

    prior_vacuous = gate_census_precision.PRIOR_FLAG_PRECISION["vacuous-empty"]
    assert (prior_vacuous.n_flagged, prior_vacuous.n_sampled, prior_vacuous.n_fp, prior_vacuous.n_tp) == (38, 13, 11, 2)
    prior_incomplete = gate_census_precision.PRIOR_FLAG_PRECISION["exempt-by-incompleteness"]
    assert (prior_incomplete.n_flagged, prior_incomplete.n_sampled, prior_incomplete.n_fp, prior_incomplete.n_tp) == (27, 10, 9, 1)

    for sample in list(gate_census.FLAG_PRECISION.values()) + list(gate_census_precision.PRIOR_FLAG_PRECISION.values()):
        assert sample.n_fp + sample.n_tp == sample.n_sampled, "FP + TP must account for the whole sample"
        assert sample.n_sampled <= sample.n_flagged


@pytest.mark.parametrize(
    "k,n,expected_lo,expected_hi",
    [
        (11, 13, 0.578, 0.957),
        (9, 10, 0.596, 0.982),
    ],
)
def test_the_wilson_helper_matches_the_hand_computed_table(k, n, expected_lo, expected_hi):
    """The issue's own table was verified arithmetically before this was wired in —
    pin the same two known input pairs so the helper can't silently drift from it."""
    lo, hi = gate_census._wilson_interval(k, n)
    assert lo == pytest.approx(expected_lo, abs=0.001)
    assert hi == pytest.approx(expected_hi, abs=0.001)


def test_the_report_prints_the_measured_fp_proportions_for_both_flags():
    """Acceptance box 3, wired into the report a human actually reads.

    Asserted on the ERROR-BAR SECTION, not the whole report: the old form searched the
    full string for "85%", which any proof's prose could satisfy by accident — and after
    the 2026-08-27 re-sample it kept passing on the superseded prior-draw line while the
    current proportion had moved to 78%. A percentage that matches somewhere in a
    900-line report is not evidence the report printed it here."""
    section = gate_census._render_error_bars(CENSUS)
    assert "vacuous-empty" in section and "78%" in section
    assert "exempt-by-incompleteness" in section and "79%" in section
    # the Wilson interval bounds, rendered to the nearest percent
    assert "55%-91%" in section
    assert "52%-92%" in section
    # the superseded draw is still shown, so the movement is visible rather than replaced
    assert "prior draw 2026-08-16" in section and "85%" in section and "90%" in section


def test_the_report_still_calls_flag_counts_an_upper_bound():
    """A real precision number does not license treating the flag count as a defect
    count — most of the sampled hits were noise, and the report must keep saying so."""
    report = gate_census.render_report(CENSUS)
    assert "upper bound" in report.lower()


def test_no_drift_note_when_live_count_matches_the_recorded_sample():
    """Both samples were re-drawn at the live populations on 2026-08-27 (#2999), so no
    drift note should print — and this is the FIRST time this branch has ever run.

    It was written on 2026-08-16 against the whole `render_report` string and the live
    counts had drifted the same week, so only the `else` arm was ever taken. The `if` arm
    would have failed on a substring collision the moment it was reached:
    `gate_census_proofs`'s check_cfn_drift record contains the literal
    `StackDriftStatus=DRIFTED`, so "DRIFT" is in the full report whatever the samples say.
    The `# pragma: no cover` note sat on the arm that DID run. Scoped to the error-bar
    section, which is the only place the note can legitimately appear."""
    error_bars = gate_census._render_error_bars(CENSUS)
    vacuous_live = gate_census._live_flag_count(CENSUS, "vacuous-empty")
    incomplete_live = gate_census._live_flag_count(CENSUS, "exempt-by-incompleteness")
    if vacuous_live == gate_census.FLAG_PRECISION["vacuous-empty"].n_flagged and incomplete_live == (
        gate_census.FLAG_PRECISION["exempt-by-incompleteness"].n_flagged
    ):
        assert "DRIFT" not in error_bars
    else:  # the corpus has moved since the last draw — the note is the whole point
        assert "DRIFT" in error_bars


def test_drift_note_fires_on_a_synthetic_census_when_the_live_count_has_moved():
    """Independently testable without waiting for the real corpus to drift — a hand-built
    census whose live `vacuous-empty` count no longer matches the recorded sample
    must produce a visible note, mirroring `PROVEN_CAN_FAIL`'s stale-name refusal.

    The matching arm is DERIVED from the recorded sample rather than typed, so a future
    re-sample cannot leave this test asserting against a number that moved (which is what
    happened to it on 2026-08-27: the hardcoded 27 became a drift the moment the
    exempt-by-incompleteness population was re-drawn at 40)."""
    n_match = gate_census.FLAG_PRECISION["exempt-by-incompleteness"].n_flagged
    synthetic = {
        "gates": [{"risk_flags": ["vacuous-empty"]} for _ in range(5)]
        + [{"risk_flags": ["exempt-by-incompleteness"]} for _ in range(n_match)],
        "counters": {"ci": {"steps_nongate": 1, "by_enforcement_only": 1, "by_verb_only": 1, "by_both": 1}},
    }
    report = gate_census._render_error_bars(synthetic)
    assert "DRIFT" in report
    assert "live count is now 5" in report
    # the flag that DID match its recorded population must not also be flagged
    assert f"live count is now {n_match}" not in report


def test_live_flag_count_counts_gates_carrying_the_flag():
    census = {
        "gates": [
            {"risk_flags": ["vacuous-empty", "swallowed-exit"]},
            {"risk_flags": ["vacuous-empty"]},
            {"risk_flags": ["exempt-by-incompleteness"]},
            {"risk_flags": []},
        ]
    }
    assert gate_census._live_flag_count(census, "vacuous-empty") == 2
    assert gate_census._live_flag_count(census, "exempt-by-incompleteness") == 1
    assert gate_census._live_flag_count(census, "no-such-flag") == 0
