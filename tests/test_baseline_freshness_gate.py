"""#1691 (epic #1687) — the baseline-freshness gate must catch the "reset-window
stale-baseline" class the DATA-grounding gates cannot see.

The 2026-07-22 defect: 07-20 coach briefs were frozen with cycle-9 baselines —
"starting weight of 315 lbs" (real cycle-10 baseline 321.38) and "Day 1" during the
pre-start window (genesis 2026-07-22, so 07-20 is PRE-START, not Day 1). `grounded:True`
passed them because the number/date gates check claims-vs-DATA, never framing-vs-CYCLE.
4 of 5 high-concern items that day were this class.

Crux regression: `test_0720_stale_brief_trips_both_classes` replays that exact brief and
asserts BOTH a stale_baseline AND a stale_phase finding. The clean-brief tests are the
false-positive guard — an honest current-weight mention or a correct countdown framing
must produce ZERO findings.

Stdlib-only imports — no layer-only deps at module top (keeps pytest --collect-only clean).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import grounded_generation as gg  # noqa: E402

# The real cycle-10 constants (mirrors lambdas/constants.py).
BASELINE = 321.38
START = "2026-07-22"
GEN_0720 = "2026-07-20"  # pre-start: two days before genesis


def _types(findings):
    return sorted(f["type"] for f in findings)


# ── the crux: the 07-20 "315 lbs / Day 1" brief trips BOTH classes ───────────
def test_0720_stale_brief_trips_both_classes():
    text = (
        "Great work today. You're down from your starting weight of 315 lbs and the "
        "scale is moving. This is Day 1 of the experiment — the foundation you set now "
        "compounds for the next twelve months."
    )
    findings = gg.baseline_freshness_findings(
        text,
        generation_date_iso=GEN_0720,
        baseline_lbs=BASELINE,
        start_date_iso=START,
    )
    assert "stale_baseline" in _types(findings), findings
    assert "stale_phase" in _types(findings), findings

    stale_b = next(f for f in findings if f["type"] == "stale_baseline")
    assert stale_b["claimed"] == 315.0
    assert stale_b["expected"] == 321.38

    stale_p = next(f for f in findings if f["type"] == "stale_phase")
    assert stale_p["claimed_day"] == 1


def test_0720_stale_brief_via_grounding_findings_facade():
    """The same brief is caught through grounding_findings() when the new params are
    supplied — proving the class composes with the shared gate."""
    text = "Down from your baseline of 315 lbs. Day 1 of the experiment begins."
    findings = gg.grounding_findings(
        text,
        baseline_lbs=BASELINE,
        generation_date_iso=GEN_0720,
        start_date_iso=START,
    )
    assert "stale_baseline" in _types(findings)
    assert "stale_phase" in _types(findings)


# ── stale_baseline in isolation ──────────────────────────────────────────────
def test_stale_baseline_only():
    text = "Your starting weight was 315 lb — steady progress since."
    findings = gg.baseline_freshness_findings(text, generation_date_iso="2026-07-25", baseline_lbs=BASELINE, start_date_iso=START)
    assert _types(findings) == ["stale_baseline"]


def test_correct_baseline_within_tolerance_is_clean():
    # 321 lb vs 321.38 baseline is within the 1.0 lb tolerance → no finding.
    text = "You started at 321 lb and you're on your way."
    findings = gg.baseline_freshness_findings(text, generation_date_iso="2026-07-25", baseline_lbs=BASELINE, start_date_iso=START)
    assert findings == []


def test_current_weight_mention_is_not_flagged():
    """A current-weight mention carries no baseline framing → never a false positive."""
    text = "You now weigh 315 lbs this morning — nice work on the scale today."
    findings = gg.baseline_freshness_findings(text, generation_date_iso="2026-07-25", baseline_lbs=BASELINE, start_date_iso=START)
    assert findings == []


def test_baseline_skipped_when_no_baseline_param():
    text = "Your starting weight of 315 lbs is well behind you."
    findings = gg.baseline_freshness_findings(text, generation_date_iso="2026-07-25", baseline_lbs=None, start_date_iso=START)
    assert all(f["type"] != "stale_baseline" for f in findings)


# ── stale_phase in isolation ─────────────────────────────────────────────────
def test_pre_start_any_day_claim_flags():
    text = "This is Day 1 of the experiment."
    findings = gg.baseline_freshness_findings(text, generation_date_iso=GEN_0720, baseline_lbs=BASELINE, start_date_iso=START)
    assert _types(findings) == ["stale_phase"]


def test_in_experiment_wrong_day_flags():
    # 2026-07-25 is Day 4 (genesis 07-22 = Day 1). A "Day 1" claim is stale.
    text = "Day 1 of the experiment and going strong."
    findings = gg.baseline_freshness_findings(text, generation_date_iso="2026-07-25", baseline_lbs=BASELINE, start_date_iso=START)
    phase = [f for f in findings if f["type"] == "stale_phase"]
    assert len(phase) == 1
    assert phase[0]["claimed_day"] == 1
    assert phase[0]["expected_day"] == 4


def test_in_experiment_correct_day_is_clean():
    # 2026-07-24 is Day 3.
    text = "Day 3 of the experiment — the routine is forming."
    findings = gg.baseline_freshness_findings(text, generation_date_iso="2026-07-24", baseline_lbs=BASELINE, start_date_iso=START)
    assert all(f["type"] != "stale_phase" for f in findings)


def test_clean_pre_start_countdown_framing_is_zero_findings():
    """A CLEAN brief: correct baseline, countdown framing, no stale Day-N claim."""
    text = (
        "We start in two days. Your baseline is 321.38 lb and the goal is 185. "
        "Everything you build in these final prep days sets the tone for launch."
    )
    findings = gg.baseline_freshness_findings(text, generation_date_iso=GEN_0720, baseline_lbs=BASELINE, start_date_iso=START)
    assert findings == []


def test_no_claims_at_all_is_clean():
    text = "Hydrate, sleep well, and keep the protein high. Small steps compound."
    findings = gg.baseline_freshness_findings(text, generation_date_iso=GEN_0720, baseline_lbs=BASELINE, start_date_iso=START)
    assert findings == []


# ── back-compat: pre-existing grounding_findings callers unchanged ───────────
def test_grounding_findings_without_new_params_is_pre1691_behavior():
    """A caller that supplies neither generation_date_iso nor start_date_iso gets the
    exact pre-#1691 behavior — no freshness class, identical to the allowed_dates
    optional-param discipline."""
    text = "Your starting weight of 315 lbs. Day 1 of the experiment."
    findings = gg.grounding_findings(text)  # no new params
    assert all(f["type"] not in ("stale_baseline", "stale_phase") for f in findings)


# ── correction_prompt composes the new classes ──────────────────────────────
def test_correction_prompt_renders_both_classes():
    text = "Down from your starting weight of 315 lbs. Day 1 of the experiment."
    findings = gg.baseline_freshness_findings(text, generation_date_iso=GEN_0720, baseline_lbs=BASELINE, start_date_iso=START)
    prompt = gg.correction_prompt(findings)
    assert "321.38" in prompt  # the corrected baseline
    assert "pre-start countdown" in prompt
