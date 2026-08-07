"""tests/test_night_scoped_vitals_1968.py — the night-scope contract (#1968, epic #1890).

WHAT WAS MEASURED
-----------------
Two live reproductions, both against real payloads, both kept here as fixtures.

1. **2026-07-27, the /fullreview panel's finding.** The integrator's weekly priority
   credited "a 7.5-hour sleep"; the sleep coach card said "duration at 6.58 hours /
   efficiency 93.81%"; /api/vitals showed 8.9h for the same night. The corrected causal
   account (both verifiers): the whoop row's `sleep_end` was 14:22Z and the narrative
   generated at 14:02Z, so the packet was an EARLIER partial-night revision of the SAME
   record — the companion numbers (quality 86, deep 17.6%, REM 30.3%) all mismatch the
   final row (83, 24.2%, 22.0%). A canary asking "did the packet match canonical at
   generation time?" would have PASSED. Nothing re-checked afterwards.

2. **2026-08-06, live, re-measured before designing this.** `/api/sleep_detail` published
   `sleep_detail.total_sleep_hours: 8.4` with no night label, while the `sleep_trend` row
   for the same `as_of_date` (2026-08-06) read `hours: null`. Both were true:
   `total_sleep_hours` is EIGHT SLEEP's duration for that wake date; the trend's `hours`
   is WHOOP's, and whoop had been in an auth outage since 08-04. The payload said neither
   thing. That is the issue's evidence comment, still holding, with the figure revised
   from the 8.5 recorded there — i.e. the revision behavior itself, observed again.

WHAT IS ASSERTED
----------------
* the deterministic gate flags an unlabeled vitals figure and a labeled-but-revised one,
  and stays quiet on correct, prescriptive, and non-sleep text (the false-positive
  controls are the point — a noisy gate gets switched off);
* the wake-date→night frame agrees across all THREE modules that now carry it, so it
  cannot fork the way the `_Nd` field families once did;
* R5 fires on the observed pre-fix `/api/sleep_detail` payload and is clean on the
  post-fix one — the acceptance criterion stated as a fixture, not as a promise;
* every pre-#1968 caller is byte-identical when the new parameter is omitted.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from ai import (
    grounded_generation as gg,  # noqa: E402
    night_scope as ns,  # noqa: E402
)
from experiment import canonical_facts as cf  # noqa: E402
from operational import phase_plausibility as pp  # noqa: E402
from web import site_api_common as sac  # noqa: E402

# ── Fixture 1: the 2026-07-27 record, as FINALIZED (what the reader could check) ──
FINAL_NIGHT = "2026-07-26"
FINAL_ROW = {
    "sleep_hours": 8.9,
    "sleep_efficiency_pct": 79.55,
    "sleep_score": 83.0,
    "recovery_pct": 44.0,
    "hrv_ms": 35.0,
    "rhr_bpm": 60.0,
}
NIGHTLY = {FINAL_NIGHT: FINAL_ROW}

# The three published sentences, verbatim in shape.
INTEGRATOR_LINE = "This week's priority is protecting the streak — you earned it with a 7.5-hour sleep."
COACH_CARD_LINE = f"On the night of {FINAL_NIGHT} you held duration at 6.58 hours with efficiency 93.81%."
NUTRITION_LINE = f"Sleep efficiency on the night of {FINAL_NIGHT} was 79.55%, which is where it has been sitting."


# ── the frame, pinned across every module that now carries it ─────────────────


def test_the_wake_date_to_night_frame_is_the_same_in_all_three_modules():
    """One offset, three bundles. A fork here is how two surfaces disagree in public."""
    assert sac.NIGHT_OF_OFFSET_DAYS == ns.NIGHT_OF_OFFSET_DAYS == cf.NIGHT_OF_OFFSET_DAYS == 1
    for as_of in ("2026-07-31", "2026-01-01", "2026-03-01", "2024-03-01", "2026-08-06"):
        assert ns.night_of_for_wake_date(as_of) == sac.night_of_for(as_of)
        assert cf._night_of(as_of) == sac.night_of_for(as_of)


def test_an_unparseable_wake_date_yields_no_night_rather_than_a_guess():
    for bad in (None, "", "not-a-date", "2026-13-45", 12345):
        assert ns.night_of_for_wake_date(bad) is None
        assert cf._night_of(bad) is None


def test_canonical_facts_carries_the_night_and_declares_it_meta():
    facts = cf.build_canonical_facts({"date": "2026-07-27", "recovery_pct": 44, "hrv_ms": 35}, genesis="2026-07-01")
    assert facts["as_of"] == "2026-07-27"
    assert facts["night_of"] == FINAL_NIGHT
    assert "night_of" in cf.META_FIELDS
    # Meta must never reach a contradiction detector as if it were a reading.
    assert "night_of" not in cf.numeric_facts(facts)


def test_the_night_is_in_the_number_allow_list_by_construction():
    """Instructing a narrative to cite the night must not make the number gate flag it.

    `allowed_numbers` json.dumps the facts dict, so carrying `night_of` there is what
    keeps the label and the allow-list from disagreeing — a per-renderer derivation
    would have licensed a `fabricated_number` finding on the very date we asked for.
    """
    facts = cf.build_canonical_facts({"date": "2026-07-27", "recovery_pct": 44.0}, genesis="2026-07-01")
    allowed = gg.allowed_numbers(facts)
    assert not gg.fabricated_numbers(f"on the night of {FINAL_NIGHT} recovery was 44%", allowed)


def test_the_facts_block_names_the_night_when_a_night_scoped_vital_survives():
    facts = cf.build_canonical_facts({"date": "2026-07-27", "recovery_pct": 44.0, "hrv_ms": 35.0}, genesis="2026-07-01")
    block = gg.authoritative_facts_block(facts)
    assert FINAL_NIGHT in block
    assert "THE NIGHT THESE DESCRIBE" in block


def test_the_facts_block_adds_no_night_label_when_there_is_no_vital_to_scope():
    """A scope for nothing is worse than no scope — it implies figures that are absent."""
    facts = cf.build_canonical_facts({"date": "2026-07-27", "protein_g_avg": 180.0}, genesis="2026-07-01")
    assert "THE NIGHT THESE DESCRIBE" not in gg.authoritative_facts_block(facts)


def test_pre_genesis_facts_are_not_labeled():
    """#2113 withholds pre-genesis observations on purpose; labeling them would undo it."""
    facts = cf.build_canonical_facts({"date": "2026-07-27", "recovery_pct": 59.0}, genesis="2026-08-03")
    assert facts["recovery_pct"] is None
    assert "THE NIGHT THESE DESCRIBE" not in gg.authoritative_facts_block(facts)


# ── the gate: the measured incident ──────────────────────────────────────────


def test_the_integrators_unlabeled_sleep_figure_flags():
    findings = ns.night_scoped_vitals_findings(INTEGRATOR_LINE, nightly_vitals=NIGHTLY)
    assert [f["type"] for f in findings] == ["unlabeled_night_figure"]
    assert findings[0]["metric"] == "sleep_hours"
    assert findings[0]["claimed"] == 7.5


def test_the_coach_cards_labeled_but_revised_figures_flag_as_mismatches():
    """The generation-before-data-final class: right when written, wrong once revised."""
    findings = ns.night_scoped_vitals_findings(COACH_CARD_LINE, nightly_vitals=NIGHTLY)
    by_metric = {f["metric"]: f for f in findings}
    assert set(by_metric) == {"sleep_hours", "sleep_efficiency_pct"}
    assert all(f["type"] == "night_value_mismatch" for f in findings)
    assert by_metric["sleep_hours"]["night"] == FINAL_NIGHT
    assert by_metric["sleep_hours"]["stored"] == 8.9
    assert by_metric["sleep_efficiency_pct"]["claimed"] == 93.81


def test_an_unanchored_relative_frame_is_treated_as_unlabeled():
    """ "Last night" with no generation date names nothing a reader can resolve.

    This is the archived-narrative case: the same two words are perfectly reconcilable
    in a dated daily brief and meaningless in a chronicle read a week later. The gate
    does not get to assume the anchor — the caller supplies it.
    """
    text = "Last night your recovery came in at 86%."
    assert [f["type"] for f in ns.night_scoped_vitals_findings(text, nightly_vitals=NIGHTLY)] == ["unlabeled_night_figure"]


def test_a_relative_frame_is_resolved_against_the_generation_date_and_checked():
    """Anchored, the same sentence becomes a checkable claim — and here it is wrong."""
    text = "Last night your recovery came in at 86%."
    anchored = ns.night_scoped_vitals_findings(text, nightly_vitals=NIGHTLY, generation_date_iso="2026-07-27")
    assert [f["type"] for f in anchored] == ["night_value_mismatch"]
    assert anchored[0]["night"] == FINAL_NIGHT
    assert anchored[0]["night_source"] == "relative_frame"


def test_the_sibling_surface_that_was_already_correct_stays_clean():
    """The nutrition thread quoted 79.55% for a labeled night and matched. No finding."""
    assert ns.night_scoped_vitals_findings(NUTRITION_LINE, nightly_vitals=NIGHTLY) == []


def test_a_labeled_and_accurate_narrative_is_clean():
    text = f"On the night of {FINAL_NIGHT} you slept 8.9 hours; recovery came in at 44% with HRV at 35 ms."
    assert ns.night_scoped_vitals_findings(text, nightly_vitals=NIGHTLY) == []


# ── the false-positive controls (a noisy gate gets switched off) ──────────────


def test_a_non_sleep_hours_figure_is_not_graded_as_sleep():
    text = "You rode 2.5 hours on the trainer and held the effort well."
    assert ns.night_scoped_vitals_findings(text, nightly_vitals=NIGHTLY) == []


def test_targets_and_advice_are_not_readings():
    for text in (
        "Aim for 8 hours of sleep tonight and keep the window tight.",
        "Your sleep target is 7.5 hours a night.",
        "You should try for 8.5 hours of sleep.",
        "If you can get 9 hours of sleep, the recovery will follow.",
    ):
        assert ns.night_scoped_vitals_findings(text, nightly_vitals=NIGHTLY) == [], text


def test_a_night_outside_the_supplied_map_is_unknown_not_wrong():
    """Unknown means unknown (ADR-104) — a legitimate history date must not flag."""
    text = "On the night of 2026-06-01 you slept 6.0 hours."
    assert ns.night_scoped_vitals_findings(text, nightly_vitals=NIGHTLY) == []


def test_a_sentence_naming_two_nights_is_left_alone_rather_than_guessed_at():
    text = f"The night of {FINAL_NIGHT} beat the night of 2026-07-25 — 6.0 hours against 5.0."
    assert ns.night_scoped_vitals_findings(text, nightly_vitals=NIGHTLY) == []


def test_a_figure_within_tolerance_does_not_flag():
    text = f"On the night of {FINAL_NIGHT} you slept 8.9 hours and recovery was 45%."
    assert ns.night_scoped_vitals_findings(text, nightly_vitals=NIGHTLY) == []


# ── the opt-out contract (every pre-#1968 caller is byte-identical) ───────────


def test_none_is_the_opt_out_and_an_empty_map_still_arms_the_label_class():
    assert ns.night_scoped_vitals_findings(INTEGRATOR_LINE, nightly_vitals=None) == []
    # "I hold no vitals" does not make an unlabeled figure reconcilable.
    assert [f["type"] for f in ns.night_scoped_vitals_findings(INTEGRATOR_LINE, nightly_vitals={})] == ["unlabeled_night_figure"]


def test_grounding_findings_is_unchanged_when_the_parameter_is_omitted():
    assert gg.grounding_findings(INTEGRATOR_LINE, allowed={7.5}) == []
    armed = gg.grounding_findings(INTEGRATOR_LINE, allowed={7.5}, nightly_vitals=NIGHTLY)
    assert [f["type"] for f in armed] == ["unlabeled_night_figure"]


def test_the_correction_prompt_names_the_night_and_the_stored_value():
    findings = ns.night_scoped_vitals_findings(COACH_CARD_LINE, nightly_vitals=NIGHTLY)
    prompt = gg.correction_prompt(findings)
    assert FINAL_NIGHT in prompt
    assert "8.9" in prompt
    assert "never carry a figure the stored record has since revised" in prompt


def test_regen_once_can_clear_the_findings():
    """The gate has to be ANSWERABLE — a finding with no achievable fix is just noise."""
    fixed = f"On the night of {FINAL_NIGHT} you slept 8.9 hours with efficiency 79.55%."

    def _findings(t):
        return ns.night_scoped_vitals_findings(t, nightly_vitals=NIGHTLY)

    best, left, corrected = gg.regen_once(COACH_CARD_LINE, _findings, lambda _c: fixed)
    assert corrected and left == [] and best == fixed


# ── R5: the payload guard, against the OBSERVED live payloads ────────────────

# Trimmed verbatim from https://averagejoematt.com/api/sleep_detail on 2026-08-06.
OBSERVED_SLEEP_DETAIL = {
    "sleep_detail": {
        "sleep_score": 90.0,
        "sleep_efficiency": 86.9,
        "total_sleep_hours": 8.4,
        "whoop_quality": None,
        "whoop_hours": None,
        "recovery_score": 44.0,
        "recovery_night_of": "2026-08-03",
        "hrv": 35.0,
        "rhr": 60.0,
        "deep_pct": 20.3,
        "rem_pct": 29.8,
        "light_pct": 49.9,
        "days_tracked": 4,
        "as_of_date": "2026-08-06",
    },
    "sleep_trend": [
        {"date": "2026-08-03", "sleep_score": 95.0, "efficiency": 69.9, "hours": 10.2, "recovery_score": 44.0},
        # The seam: same night as the summary above, and the whoop-sourced hours are null.
        {"date": "2026-08-06", "sleep_score": 90.0, "efficiency": 86.9, "hours": None, "recovery_score": None},
    ],
}


def _fixed_sleep_detail():
    """The same payload as this PR's handler now emits it."""
    import copy

    payload = copy.deepcopy(OBSERVED_SLEEP_DETAIL)
    payload["sleep_detail"]["frame"] = sac.NIGHT_OF_FRAME
    payload["sleep_detail"]["night_of"] = sac.night_of_for("2026-08-06")
    payload["sleep_detail"]["figure_scope"] = {
        "frame": sac.NIGHT_OF_FRAME,
        "night_of": sac.night_of_for("2026-08-06"),
        "total_sleep_hours_source": "eightsleep",
        "whoop_hours_source": None,
        "divergence": "…",
    }
    return payload


def test_r5_fires_on_the_observed_pre_fix_payload():
    findings = pp.check_payload("/api/sleep_detail", OBSERVED_SLEEP_DETAIL, day_n=4, strict=True)
    r5 = [f for f in findings if "#1968" in f["note"]]
    assert len(r5) == 1, findings
    assert r5[0]["page"] == "/api/sleep_detail"
    assert "no night label" in r5[0]["note"]


def test_r5_is_clean_on_the_fixed_payload():
    findings = pp.check_payload("/api/sleep_detail", _fixed_sleep_detail(), day_n=4, strict=True)
    assert [f for f in findings if "#1968" in f["note"]] == []


def test_r5_skips_dated_rows_so_a_thirty_day_trend_is_not_thirty_findings():
    """A row keyed by its own date is scoped by its key; flagging all of them buries the one
    object that genuinely floats free."""
    rows = {"sleep_trend": OBSERVED_SLEEP_DETAIL["sleep_trend"]}
    assert pp._night_label_findings("/api/sleep_detail", rows) == []


def test_r5_is_phase_independent():
    """The night-label question is not a question about the experiment day."""
    assert pp.check_payload("/api/sleep_detail", OBSERVED_SLEEP_DETAIL, day_n=0) != []


def test_r5_accepts_the_1923_frame_declaration_as_a_night_label():
    """`/api/vitals` already publishes frame + night_of — it must not become noise."""
    vitals = {"unified": {"recovery_pct": 44, "sleep_hours": 8.9, "as_of_date": "2026-08-06", "frame": sac.NIGHT_OF_FRAME}}
    assert pp._night_label_findings("/api/vitals", vitals) == []
