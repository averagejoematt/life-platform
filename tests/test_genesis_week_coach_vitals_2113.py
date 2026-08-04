"""tests/test_genesis_week_coach_vitals_2113.py — #2113: a pre-genesis recovery
score is not this cycle's recovery, at any age.

THE LIVE FAILURE (cycle 12, genesis 2026-08-03). `/api/coaching-dashboard` served,
from Dr. Sarah Chen (training):

    "Day one of this experiment gives me exactly one data point for each recovery
     metric ... Your Whoop recovery came in at 59%, HRV at 42 ms, resting HR at 59"

and from Dr. Lisa Park (sleep):

    "I have one night of data — a recovery score of 59%, REM at 26.8%, deep sleep at
     23.9%, sleep efficiency at 96.58%, and HRV of 42 ms"

while `/api/vitals` served recovery 44%, HRV 35.0 ms, RHR 60 bpm.

WHERE THE NUMBERS CAME FROM — measured, not assumed. The `computed_metrics`
partition held, newest-first: 08-03 (recovery 44, hrv 35.05, rhr 60, phase
`experiment`) and 08-02 (recovery 59, hrv 41.97 -> 42, rhr 59, latest_weight 316.97,
phase `pilot`). The coaches ran before the genesis day's daily-metrics-compute had
written the 08-03 row, and `_load_canonical_facts` reads that partition with an
UNBOUNDED newest-first `Limit: 1`. So it returned the pilot-tagged 08-02 record, and
`grounded_generation.authoritative_facts_block` rendered it as "Latest Whoop
recovery: 59%" beneath a HARD RULE instructing the narrator to state exactly that
value. The coach did as it was told.

WHY THE EXISTING GUARDS DID NOT COVER IT.
  * The analyzer's own expert windows were never the leak — `d30` is already
    `max(today-30, EXPERIMENT_START)`, so the sleep coach's whoop window on genesis
    day is genesis-clamped. The leak was the canonical-facts path, which had no date
    bound at all.
  * The #1894/#2104 cross-surface check compares ONE column, weight. It was green
    the entire time this was live. A defect that exists only in a comparison is
    invisible until something compares.
  * `computed_metrics` is EXPERIMENT_SCOPED in phase_taxonomy — precisely the class
    the reset tombstones (ADR-077) — so the taxonomy already knew the answer. The
    read simply never asked it.

THE FIX, in the #2104 shape.
  1. `canonical_facts.build_canonical_facts` withholds every OBSERVED field when the
     record predates genesis. Withheld, not annotated: the value never enters the
     fact set, so `grounded_generation.allowed_numbers` never allows it and the
     existing regen-once harness catches a narrative that cites it as a fabricated
     number. Structural, not advisory (ADR-104/105).
  2. The analyzer's two generic readers bound EXPERIMENT_SCOPED sources at genesis,
     derived from phase_taxonomy per source — so labs (cross_phase) and
     journal_analysis (system_state) are untouched by construction, not by luck.
  3. `assess_cross_surface_vitals` widens the truth gate to the columns the coaches
     actually cite, wired into both the nightly qa-smoke and restart_verify.

These tests pin: the incident replay, the withholding, the field-classification SET,
the rider, the taxonomy-derived read rule, the cross_phase pinning, and the gate —
including that the exact published prose still FAILS and that a reachable cure PASSES.
"""

import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ai import grounded_generation as gg  # noqa: E402
from experiment import (
    canonical_facts as cf,  # noqa: E402
    phase_taxonomy as pt,  # noqa: E402
)
from operational import weight_truth_qa as wq  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GENESIS = "2026-08-03"

# The real rows, at the values and dates the platform actually held them.
_PRE_GENESIS_RECORD = {
    "sk": "DATE#2026-08-02",
    "date": "2026-08-02",
    "recovery_pct": 59,
    "hrv_ms": 41.97,
    "rhr_bpm": 59,
    "latest_weight": 316.97,
    "weekly_rate_lbs": -1.4,
    "protein_g_avg": 132,
    "protein_g_target": 190,
    "protein_g_floor": 170,
}
_GENESIS_DAY_RECORD = {
    "sk": f"DATE#{GENESIS}",
    "date": GENESIS,
    "recovery_pct": 44,
    "hrv_ms": 35.05,
    "rhr_bpm": 60,
    "latest_weight": 321.6,
    "protein_g_target": 190,
    "protein_g_floor": 170,
}

# What the cockpit served at the same moment.
_COCKPIT = {"recovery_pct": 44.0, "hrv_ms": 35.0, "rhr_bpm": 60.0, "sleep_hours": 10.2, "weight_lbs": 322}

# The two cards, verbatim enough to be the real test subject.
_SARAH_CHEN = {
    "name": "Dr. Sarah Chen",
    "position_summary": (
        "Day one of this experiment gives me exactly one data point for each recovery metric — and that's "
        "precisely what it should give me. Your Whoop recovery came in at 59%, HRV at 42 ms, resting HR at 59."
    ),
}
_LISA_PARK = {
    "name": "Dr. Lisa Park",
    "position_summary": (
        "I have one night of data — a recovery score of 59%, REM at 26.8%, deep sleep at 23.9%, sleep "
        "efficiency at 96.58%, and HRV of 42 ms — but one night is a reference point, not yet a baseline."
    ),
}


# ── the premise, established before it is fixed ───────────────────────────────


def test_computed_metrics_is_experiment_scoped_so_the_taxonomy_already_knew():
    """The rule is DERIVED, not invented here: the partition the leak came from is
    the class the reset tombstones. The read simply never consulted it."""
    assert pt.classify("USER#matthew#SOURCE#computed_metrics") == pt.EXPERIMENT_SCOPED


def test_the_pre_genesis_record_really_does_produce_the_published_numbers():
    """Reproduce the bug against the pre-fix behaviour: pin the genesis to a date
    the record is NOT before, and the old (unbounded) reading is exactly what shipped."""
    facts = cf.build_canonical_facts(_PRE_GENESIS_RECORD, genesis="2026-01-01")
    assert facts["recovery_pct"] == 59
    assert facts["hrv_ms"] == 42.0  # 41.97 rounds to the published 42
    assert facts["rhr_bpm"] == 59
    assert facts["latest_weight"] == 317.0  # ...and the #2104 weight, from this same row
    assert "Latest Whoop recovery: 59%" in gg.authoritative_facts_block(facts)


# ── the withholding ───────────────────────────────────────────────────────────


def test_observed_facts_are_withheld_when_the_record_predates_genesis():
    facts = cf.build_canonical_facts(_PRE_GENESIS_RECORD, genesis=GENESIS)

    assert facts["recovery_pct"] is None, "59% must not be offered as this cycle's recovery"
    assert facts["hrv_ms"] is None
    assert facts["rhr_bpm"] is None
    assert facts["latest_weight"] is None
    assert facts["weekly_rate_lbs"] is None
    assert facts["protein_g_avg"] is None
    assert facts["facts_are_pre_genesis"] is True
    assert facts["cycle_genesis"] == GENESIS
    # ...and the record still names itself honestly rather than vanishing.
    assert facts["as_of"] == "2026-08-02"


def test_configured_targets_still_travel():
    """A target is not an observation and does not belong to a cycle. Withholding it
    would leave the coach unable to say what the target even is — the opposite defect."""
    facts = cf.build_canonical_facts(_PRE_GENESIS_RECORD, genesis=GENESIS)
    assert facts["protein_g_target"] == 190
    assert facts["protein_g_floor"] == 170


def test_no_withheld_value_survives_anywhere_in_the_fact_set():
    """Guard the mechanism, not the field name — a refactor that reintroduces any of
    these under another key must fail here."""
    facts = cf.build_canonical_facts(_PRE_GENESIS_RECORD, genesis=GENESIS)
    numeric = [v for v in facts.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    for leaked in (59, 42.0, 41.97, 317.0, 316.97, 132, -1.4):
        assert leaked not in numeric, f"{leaked} is still reachable in the fact set"


def test_every_numeric_field_is_classified_observed_or_configured():
    """The SET guard (not the instance). A field added to FIELD_UNITS later must be
    deliberately classified — it cannot inherit "travels across a reset" by silence."""
    assert set(cf.OBSERVED_FIELDS) | set(cf.CONFIGURED_FIELDS) == set(cf.NUMERIC_FIELDS)
    assert not set(cf.OBSERVED_FIELDS) & set(cf.CONFIGURED_FIELDS), "a field cannot be both"


def test_the_cycle_keys_are_declared_meta_so_no_grounding_pass_gets_quieter():
    """Regression pin, caught by the full suite during this change. The cycle keys are
    NOT facts about a metric, and `field_notes_lambda` feeds this dict straight to a
    contradiction detector that reads it as metric->value pairs. Leaving them in made
    the detector MISS a planted wrong-RHR canary — a truth pass must never get quieter
    as a side effect of a change made somewhere else (ADR-104/105)."""
    facts = cf.build_canonical_facts(_PRE_GENESIS_RECORD, genesis=GENESIS)
    assert set(facts) == set(cf.NUMERIC_FIELDS) | set(cf.META_FIELDS)
    assert set(cf.numeric_facts(facts)) == set(cf.NUMERIC_FIELDS)
    for key in ("facts_are_pre_genesis", "cycle_genesis", "as_of"):
        assert key in cf.META_FIELDS, f"{key} must be declared meta, not left to a caller's literal"

    # ...and the consumer no longer filters by a hardcoded key name at all.
    src = open(os.path.join(REPO, "lambdas", "intelligence", "field_notes_lambda.py")).read()
    assert "observed_facts(metrics_record)" in src
    assert 'if k != "as_of"' not in src, "the literal filter is what the new keys slipped past"


def test_the_contradiction_detector_does_not_go_dark_after_a_reset():
    """The other half of the same lesson. The detector asks a DIFFERENT question from
    the publication view — "does this text contradict the record?" — and the cycle
    boundary has no bearing on it. Collapsing the two would have muted the field-note
    grounding gate for the days after every reset."""
    observed = cf.observed_facts(_PRE_GENESIS_RECORD)
    assert observed["recovery_pct"] == 59, "the as-measured view keeps the value"
    assert observed["rhr_bpm"] == 59
    assert set(observed) == set(cf.NUMERIC_FIELDS), "and carries no provenance keys"

    # ...while the publication view of the same record still withholds it.
    assert cf.build_canonical_facts(_PRE_GENESIS_RECORD, genesis=GENESIS)["recovery_pct"] is None


def test_the_genesis_day_record_restores_everything_once_it_lands():
    """Not a permanent mute — the day's own compute resolves it within hours."""
    facts = cf.build_canonical_facts(_GENESIS_DAY_RECORD, genesis=GENESIS)
    assert facts["recovery_pct"] == 44
    assert facts["hrv_ms"] == 35.0  # 35.05 under the module's 1dp rule — the 35.0 the cockpit serves
    assert facts["facts_are_pre_genesis"] is False


def test_an_ordinary_mid_cycle_record_is_untouched():
    """The regression guard: no behaviour change away from a reset boundary."""
    rec = dict(_GENESIS_DAY_RECORD, sk="DATE#2026-09-14", date="2026-09-14")
    facts = cf.build_canonical_facts(rec, genesis=GENESIS)
    assert facts["recovery_pct"] == 44
    assert facts["latest_weight"] == 321.6
    assert facts["facts_are_pre_genesis"] is False


def test_genesis_defaults_to_the_live_constant_so_no_caller_can_forget():
    """An all-optional anchor is how coverage drifts into convention. Every consumer
    of build_canonical_facts gets the cycle rule without opting in."""
    from common.constants import EXPERIMENT_START_DATE

    facts = cf.build_canonical_facts(_GENESIS_DAY_RECORD)
    assert facts["cycle_genesis"] == EXPERIMENT_START_DATE


def test_a_record_with_no_date_is_left_alone():
    """Undated is unknowable, not pre-genesis — a fabricated withholding would be its
    own dishonesty, and would blank the facts for any producer that omits the field."""
    facts = cf.build_canonical_facts({"recovery_pct": 59}, genesis=GENESIS)
    assert facts["facts_are_pre_genesis"] is False
    assert facts["recovery_pct"] == 59


def test_the_date_can_be_recovered_from_the_sort_key_alone():
    """`_latest_item` hands the raw DDB item straight through; a producer that writes
    no `date` attribute must still be cycle-checkable."""
    facts = cf.build_canonical_facts({"sk": "DATE#2026-08-02", "recovery_pct": 59}, genesis=GENESIS)
    assert facts["as_of"] == "2026-08-02"
    assert facts["facts_are_pre_genesis"] is True
    assert facts["recovery_pct"] is None


# ── the prompt rider ──────────────────────────────────────────────────────────


def test_the_rider_names_the_boundary_and_forbids_the_exact_published_frame():
    facts = cf.build_canonical_facts(_PRE_GENESIS_RECORD, genesis=GENESIS)
    block = gg.authoritative_facts_block(facts)

    assert "CYCLE BOUNDARY" in block
    assert GENESIS in block, "the rider must name the boundary it is enforcing"
    assert "2026-08-02" in block, "and the prior-cycle record it is withholding"
    assert "day one" in block.lower(), "the published lie wore a day-one frame"
    for leaked in ("59%", "42 ms", "317"):
        assert leaked not in block, f"the rider must not smuggle {leaked} back in"


def test_the_rider_renders_even_when_no_numeric_fact_survives():
    """Withholding everything must not leave the prompt SILENT — an empty facts block
    is exactly the state in which a narrator reaches for a remembered number."""
    bare = {"sk": "DATE#2026-08-02", "recovery_pct": 59, "hrv_ms": 42}
    block = gg.authoritative_facts_block(cf.build_canonical_facts(bare, genesis=GENESIS))
    assert "CYCLE BOUNDARY" in block
    assert "AUTHORITATIVE FACTS" not in block, "no facts survived — do not claim a facts list"


def test_the_rider_is_silent_on_an_in_cycle_record():
    block = gg.authoritative_facts_block(cf.build_canonical_facts(_GENESIS_DAY_RECORD, genesis=GENESIS))
    assert "CYCLE BOUNDARY" not in block
    assert "Latest Whoop recovery: 44%" in block


def test_an_empty_facts_dict_still_renders_nothing():
    """The pre-existing contract: no facts and no boundary means no block at all."""
    assert gg.authoritative_facts_block({}) == ""
    assert gg.authoritative_facts_block(None) == ""


# ── the taxonomy-derived read rule ────────────────────────────────────────────


def _analyzer_source():
    return open(os.path.join(REPO, "lambdas", "intelligence", "ai_expert_analyzer_lambda.py")).read()


def test_the_analyzer_reads_are_bounded_by_taxonomy_not_by_a_literal():
    src = _analyzer_source()
    assert "cycle_read_floor" in src
    assert "phase_taxonomy" in src, "the rule must be derived from the ADR-077 registry"
    # A key range, never a filter: DynamoDB applies Limit BEFORE FilterExpression
    # (#1203/#2089), so filtering a Limit:1 read would drop rows for the wrong reason.
    assert "FilterExpression" not in src.split("def _latest_item")[1].split("\ndef ")[0]


def _pk(source):
    return f"USER#matthew#SOURCE#{source}"


def test_only_experiment_scoped_sources_are_cycle_bounded():
    """The behavioural core of the rule, exercised through the real predicate."""
    assert pt.reads_current_cycle_only(_pk("computed_metrics")) is True
    assert pt.reads_current_cycle_only(_pk("weekly_correlations")) is True
    # cross_phase / system_state / raw_timeseries all keep their reads.
    for source in ("labs", "dexa", "journal_analysis", "whoop", "withings", "eightsleep", "apple_health"):
        assert pt.reads_current_cycle_only(_pk(source)) is False, f"{source} must not be cycle-bounded"


def test_the_read_floor_raises_an_experiment_scoped_window_to_genesis():
    assert pt.cycle_read_floor(_pk("computed_metrics"), "2026-07-04", genesis=GENESIS) == GENESIS
    # ...and never LOWERS a caller's window: a tighter floor wins.
    assert pt.cycle_read_floor(_pk("computed_metrics"), "2026-08-20", genesis=GENESIS) == "2026-08-20"
    # An unbounded reader (floor=None) gets bounded — this is the `_latest_item` case
    # that published the 59% recovery.
    assert pt.cycle_read_floor(_pk("computed_metrics"), None, genesis=GENESIS) == GENESIS


def test_the_read_floor_leaves_every_other_class_exactly_as_it_found_it():
    """The acceptance pin, at the level the rule is actually applied."""
    for source in ("labs", "dexa", "journal_analysis", "whoop", "withings"):
        assert pt.cycle_read_floor(_pk(source), "2019-01-01", genesis=GENESIS) == "2019-01-01"
        assert pt.cycle_read_floor(_pk(source), None, genesis=GENESIS) is None


def test_an_unknown_source_is_left_alone_rather_than_silently_narrowed():
    """classify() raises by design so nothing defaults quietly; the conservative
    fall-back is the pre-#2113 read, never a narrowing nobody asked for."""
    assert pt.reads_current_cycle_only(_pk("a_source_that_does_not_exist")) is False
    assert pt.cycle_read_floor(_pk("a_source_that_does_not_exist"), None, genesis=GENESIS) is None


def test_labs_journal_and_correlation_reads_stay_cross_phase_by_design():
    """The acceptance pin. The labs coach reads full draw history on purpose and the
    mind coach's journal partition is SYSTEM_STATE — neither may acquire a genesis
    clamp from this change. Derived from the taxonomy, so it holds if a class moves."""
    for source, expected in (("labs", pt.CROSS_PHASE), ("dexa", pt.CROSS_PHASE), ("journal_analysis", pt.SYSTEM_STATE)):
        assert pt.classify(f"USER#matthew#SOURCE#{source}") == expected

    # ...and the labs read really is still all-time in the analyzer's own source.
    src = _analyzer_source()
    assert '_query_source("labs", "2019-01-01", today)' in src


def test_the_cycle_genesis_is_resolved_per_call_not_frozen_at_import():
    """The import-time-frozen-globals trap: a re-anchor (or a monkeypatch) must land
    without a module reload."""
    from common import constants as c

    original = c.EXPERIMENT_START_DATE
    try:
        c.EXPERIMENT_START_DATE = "2099-01-01"
        assert pt.cycle_read_floor(_pk("computed_metrics")) == "2099-01-01"
        assert cf.build_canonical_facts(_GENESIS_DAY_RECORD)["cycle_genesis"] == "2099-01-01"
    finally:
        c.EXPERIMENT_START_DATE = original
    assert pt.cycle_read_floor(_pk("computed_metrics")) == original


def test_every_analyzer_read_call_site_resolves_to_a_known_taxonomy_class():
    """Guard the SET: AST-derive every literal source the analyzer reads and prove the
    taxonomy classifies it. A call site added later cannot inherit either behaviour by
    accident — an unclassified source shows up here, not in production."""
    tree = ast.parse(_analyzer_source())
    sources = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in ("_query_source", "_latest_item") or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            sources.add(first.value)

    assert len(sources) >= 10, f"AST scan found only {sources} — the scan itself has drifted"
    for source in sorted(sources):
        klass = pt.classify(f"USER#matthew#SOURCE#{source}")
        assert klass in (pt.EXPERIMENT_SCOPED, pt.RAW_TIMESERIES, pt.CROSS_PHASE, pt.SYSTEM_STATE), f"{source} -> {klass}"


# ── the widened gate: the published prose, and what clears it ────────────────


def test_the_published_training_card_fails_the_vitals_check():
    """This is not a mute. The exact card that was live must still be a failure."""
    ok, msg = wq.assess_cross_surface_vitals(_COCKPIT, [_SARAH_CHEN])
    assert ok is False
    assert "recovery 59" in msg and "hrv 42" in msg
    assert "Dr. Sarah Chen" in msg


def test_the_published_sleep_card_fails_the_vitals_check():
    ok, msg = wq.assess_cross_surface_vitals(_COCKPIT, [_LISA_PARK])
    assert ok is False
    assert "recovery 59" in msg and "hrv 42" in msg


def test_the_weight_only_gate_was_green_on_both_cards():
    """Prove the gap the issue names: the pre-#2113 check could not see this. If this
    ever starts failing, the two assessors have begun overlapping and the vitals
    check's justification needs re-reading."""
    ok, _ = wq.assess_cross_surface_weight(_COCKPIT, [_SARAH_CHEN, _LISA_PARK])
    assert ok is True


def test_the_honest_absence_prose_clears_the_check():
    """The cure has to be reachable, or the gate is unpassable (the #1924 lesson)."""
    ok, msg = wq.assess_cross_surface_vitals(
        _COCKPIT,
        [
            {
                "name": "Dr. Sarah Chen",
                "position_summary": "No recovery reading has landed in this cycle yet, so I have no baseline to read from.",
            }
        ],
    )
    assert ok, msg


def test_a_dated_prior_cycle_citation_clears_the_check():
    """The rider's sanctioned escape hatch and the check's exemption are ONE seam —
    `_HISTORICAL_ANCHOR`, shared verbatim with the weight assessor."""
    ok, msg = wq.assess_cross_surface_vitals(
        _COCKPIT,
        [{"name": "Dr. Sarah Chen", "position_summary": "Recovery was 59% as of 2026-08-02, before this cycle began."}],
    )
    assert ok, msg


def test_an_in_cycle_citation_clears_the_check():
    ok, msg = wq.assess_cross_surface_vitals(
        _COCKPIT,
        [{"name": "Dr. Sarah Chen", "position_summary": "Your Whoop recovery came in at 44%, HRV at 35 ms, resting HR at 60 bpm."}],
    )
    assert ok, msg


def test_target_prose_is_not_a_current_claim():
    """The live labs card reads 'The two targets embedded in your plan — RHR 55 bpm and
    HRV 50 ms — aren't arbitrary numbers'. That is correct, clearly-labelled goal prose.
    A gate that fires on it teaches people to ignore the gate (#1924/#1985)."""
    ok, msg = wq.assess_cross_surface_vitals(
        _COCKPIT,
        [
            {
                "name": "Dr. James Okafor",
                "position_summary": (
                    "**Why These Two Biomarkers Matter** The two targets embedded in your plan — RHR 55 bpm and "
                    "HRV 50 ms — aren't arbitrary numbers. They're dashboard indicators for the same system."
                ),
            }
        ],
    )
    assert ok, msg


def test_sleep_architecture_percentages_are_not_recovery_claims():
    """REM share, deep share and sleep efficiency are all percentages living in the same
    sentence as recovery on a real card. Only the number its OWN metric names counts."""
    cited = wq.vitals_cited_in("REM at 26.8%, deep sleep at 23.9%, sleep efficiency at 96.58%.")
    assert cited.get("recovery") is None, f"misread a sleep-architecture share as recovery: {cited}"


def test_a_sleep_duration_disagreement_is_caught():
    ok, msg = wq.assess_cross_surface_vitals(
        _COCKPIT,
        [{"name": "Dr. Lisa Park", "position_summary": "You slept 6.1 hours last night."}],
    )
    assert ok is False
    assert "sleep 6.1" in msg


def test_a_null_cockpit_field_is_a_clean_pass_not_a_failure():
    """ADR-104: absence is absence. A pre-start payload has nothing to contradict."""
    ok, msg = wq.assess_cross_surface_vitals({"recovery_pct": None, "hrv_ms": None, "rhr_bpm": None, "sleep_hours": None}, [_SARAH_CHEN])
    assert ok, msg
    ok, _ = wq.assess_cross_surface_vitals({}, [_SARAH_CHEN])
    assert ok


def test_a_silent_coach_is_not_a_failure():
    ok, msg = wq.assess_cross_surface_vitals(_COCKPIT, [{"name": "Dr. Nathan Reeves", "position_summary": "What is being avoided here?"}])
    assert ok, msg


def test_rounding_and_a_same_day_reread_stay_inside_tolerance():
    """The tolerances absorb honest rounding — the live gaps were 15 points of recovery
    and 7 ms of HRV, an order of magnitude past any of them."""
    ok, msg = wq.assess_cross_surface_vitals(
        _COCKPIT,
        [{"name": "c", "position_summary": "Recovery 45%, HRV 35.9 ms, resting heart rate 61 bpm, slept 10.4 hours."}],
    )
    assert ok, msg


def test_equipment_and_set_counts_are_not_vitals():
    """Numbers outside a metric's real domain are something else that happened to sit
    near the word (ADR-105: bounds from the metric's own domain)."""
    cited = wq.vitals_cited_in("Recovery work: 3 sets at 225 lbs. Resting between sets for 180 seconds.")
    assert not cited.get("recovery"), cited
    assert not cited.get("rhr"), cited


# ── the wiring: both hooks run the one assessor ──────────────────────────────


def test_the_nightly_qa_smoke_reports_the_vitals_leg_separately():
    src = open(os.path.join(REPO, "lambdas", "operational", "weight_truth_qa.py")).read()
    assert '"cross_surface:vitals"' in src, "a recovery contradiction must not report under a check titled 'weight'"
    assert "assess_cross_surface_vitals" in src


def test_restart_verify_checks_the_coaching_door_for_vitals_too():
    src = open(os.path.join(REPO, "deploy", "restart_verify.py")).read()
    assert "assess_cross_surface_vitals" in src, "the post-reset verifier must look at the vitals columns"
    assert "weight_truth_qa" in src, "it must import the nightly's assessor, not re-derive the rule"
    assert "VITALS_TOL = " not in src, "a local tolerance literal is a second copy free to drift"
