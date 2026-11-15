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

from ai import grounded_generation as gg  # noqa: E402

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


# ══ #5933 (aiq-1, /review full 2026-11-13) — the ORIGIN idiom ══════════════════
# `stale_baseline` matched framing WORDS ("starting weight", "started at"). The 2026-10-31
# weekly read said "brought him from 305 lbs to 296.1 lbs": 305 was a real mid-cycle weigh-in
# (so the number gate passed it) and the sentence carried no framing word (so this gate never
# looked), yet an unlabelled "from X" reads as where the journey started — 22 lb higher.
#
# Three things are pinned, each as ONE test that iterates and reports every offender:
#   * every origin form the issue names fails when X is not the journey start;
#   * the same forms PASS when X is the journey start (the false-positive guard), and so do
#     a labelled window, a lift, and a figure that is not a body weight;
#   * a "window" as long as the journey, or anchored on the genesis, is not a window.
#
# The frozen specimen itself lives in tests/grounding_corpus/ and is replayed by
# tests/test_grounding_corpus_3614.py. No clock: every date is an argument.
ORIGIN_START_LBS = 327.3
ORIGIN_START = "2026-09-06"
ORIGIN_GEN = "2026-11-13"  # day 69
ORIGIN_ALLOWED = {327.3, 327.0, 296.1, 305.4, 305.0, 3.9, 185.0, 225.0, 20.0, 31.0, 13.0, 17.0, 6.0}


def _stale(text, gen=ORIGIN_GEN):
    findings = gg.grounding_findings(
        text, facts=None, allowed=ORIGIN_ALLOWED, baseline_lbs=ORIGIN_START_LBS, generation_date_iso=gen, start_date_iso=ORIGIN_START
    )
    return [f for f in findings if f["type"] == "stale_baseline"]


MUST_FAIL = [
    # the four framings the issue names
    "He went from 305 lbs to 296.1 lbs since the experiment began.",
    "He is down from 305.4 lbs to 296.1 lbs.",
    "His weight has fallen from 305.4 lbs to 296.1 lbs since the experiment began.",
    "A 3.9 lb per week fat loss has brought him from 305 lbs to 296.1 lbs.",
    # neighbours of the same shape
    "He has dropped from 305.4 pounds, and the trend is holding.",
    "The scale moved from 305.4 to 296.1 lbs.",
    "From roughly 305 pounds down to 296.1 pounds: that is the story.",
]

MUST_PASS = [
    # the journey-start figure, in every one of the same forms
    "He went from 327.3 lbs to 296.1 lbs since the experiment began.",
    "He is down from 327.3 lbs to 296.1 lbs.",
    "His weight has fallen from 327 lbs to 296.1 lbs since the experiment began.",
    "A 3.9 lb per week fat loss has brought him from 327.3 lbs to 296.1 lbs.",
    # a labelled window is an honest claim about that window (#4547)
    "Over the last two weeks he has gone from 305.4 lbs to 296.1 lbs.",
    "Since October 13 he is down from 305.4 lbs to 296.1 lbs.",
    "In 17 days the scale moved from 305.4 lbs to 296.1 lbs.",
    # a load, and a figure that is not a body weight
    "His deadlift went from 185 lbs to 225 lbs.",
    "Total loss went from 20 lbs to 31 lbs.",
    # no origin claim at all
    "He weighs 296.1 lbs this morning.",
]

NOT_A_WINDOW = [
    # day 69: ten weeks is the whole journey; the genesis date and "Day 1" are its start
    "In the last ten weeks he went from 305.4 lbs to 296.1 lbs.",
    "Since September 6 he is down from 305.4 lbs to 296.1 lbs.",
    "Since Day 1 he is down from 305.4 lbs to 296.1 lbs.",
    "Over the last two weeks of the experiment overall he fell from 305.4 lbs to 296.1 lbs.",
]


def test_every_origin_form_is_checked_against_the_journey_start():
    missed = [t for t in MUST_FAIL if not _stale(t)]
    assert not missed, f"the origin idiom walked through stale_baseline: {missed}"
    f = _stale(MUST_FAIL[3])[0]
    assert f["claimed"] == 305.0 and f["expected"] == 327.3 and f["framing"] == "origin"
    assert "Use 327.3 lb" in gg.correction_prompt([f]), "the corrective rewrite must be handed the real start"


def test_the_journey_start_a_labelled_window_and_a_lift_all_pass():
    tripped = {t: _stale(t) for t in MUST_PASS if _stale(t)}
    assert not tripped, f"the origin class is over-firing: {tripped}"


def test_a_window_as_long_as_the_journey_is_not_a_label():
    slipped = [t for t in NOT_A_WINDOW if not _stale(t)]
    assert not slipped, f"a whole-journey span was accepted as a window label: {slipped}"
    # the same ten-week span IS a window once the journey is longer than it (day 100)
    assert _stale(NOT_A_WINDOW[0], gen="2026-12-14") == []


def test_one_weight_is_reported_once_across_both_framings():
    # "started from" (the word class) and "from X to Y" (the origin class) both see 305.4
    assert len(_stale("He started from 305.4 lbs to 296.1 lbs.")) == 1
