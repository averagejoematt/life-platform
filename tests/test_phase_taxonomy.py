"""tests/test_phase_taxonomy.py — the registry is the single source of truth (ADR-077).

LIVE_FAMILIES is the full set of (pk, sk) record families observed in the live
table by the 2026-06-07 census (27,083 items, 180 families). The coverage test
asserts every one classifies to a valid class without raising — so a new source
or pk pattern cannot silently appear unclassified. The spot checks pin the
decided/contentious rows to their agreed class.
"""

from __future__ import annotations

import importlib

import pytest

pt = importlib.import_module("phase_taxonomy")

# ── Full live census (pk, sk) families — coverage fixture ─────────────────────
LIVE_FAMILIES = [
    ("CACHE#matthew", "TOOL#aggregated_summary_month"),
    ("COACH#computation", "RESULTS#2026-04-07"),
    ("COACH#explorer_coach", "BRIEF#2026-04-07"),
    ("COACH#explorer_coach", "COMPRESSED#latest"),
    ("COACH#explorer_coach", "CONFIDENCE#causal_inference"),
    ("COACH#explorer_coach", "LEARNING#2026-04-21#pred"),
    ("COACH#explorer_coach", "OUTPUT#2026-04-06#daily_brief"),
    ("COACH#explorer_coach", "PREDICTION#pred_20260407_hrv"),
    ("COACH#explorer_coach", "RELATIONSHIP#state"),
    ("COACH#explorer_coach", "THREAD#2026-04-06#data_maturity"),
    ("COACH#explorer_coach", "TRACE#2026-04-06#daily_brief"),
    ("COACH#explorer_coach", "VOICE#state"),
    ("ENSEMBLE#digest", "CYCLE#2026-04-08"),
    ("ENSEMBLE#disagreements", "ACTIVE#caloric_deficit"),
    ("ENSEMBLE#influence_graph", "CONFIG#v1"),
    ("NARRATIVE#arc", "HISTORY#2026-05-18"),
    ("NARRATIVE#arc", "STATE#current"),
    ("PULSE", "DATE#2026-04-04"),
    ("USER#matthew#SOURCE#adaptive_mode", "DATE#2026-02-26"),
    ("USER#matthew#SOURCE#ai_analysis", "EXPERT#explorer"),
    ("USER#matthew#SOURCE#anomalies", "DATE#2026-02-22"),
    ("USER#matthew#SOURCE#apple_health", "DATE#2012-06-03"),
    ("USER#matthew#SOURCE#centenarian_progress", "WEEK#2026-W13"),
    ("USER#matthew#SOURCE#challenges", "CHALLENGE#5k-every-day"),
    ("USER#matthew#SOURCE#character_sheet", "DATE#2026-03-27"),
    ("USER#matthew#SOURCE#chronicle", "DATE#2026-02-22"),
    ("USER#matthew#SOURCE#chronicling", "DATE#2025-10-20"),
    ("USER#matthew#SOURCE#circadian", "DATE#2026-03-17"),
    ("USER#matthew#SOURCE#composite_scores", "DATE#2026-03-14"),
    ("USER#matthew#SOURCE#computed_insights", "DATE#2026-03-06"),
    ("USER#matthew#SOURCE#computed_metrics", "DATE#2026-03-05"),
    ("USER#matthew#SOURCE#day_grade", "DATE#2023-07-23"),
    ("USER#matthew#SOURCE#dexa", "DATE#2025-05-10"),
    ("USER#matthew#SOURCE#discovery_annotations", "EVENT#14c27dfa"),
    ("USER#matthew#SOURCE#dropbox_tracker", "FILE#2026-02-25#MacroFactor.csv"),
    ("USER#matthew#SOURCE#dropbox_tracker", "PROCESSED_FILES"),
    ("USER#matthew#SOURCE#eightsleep", "DATE#2023-07-23"),
    ("USER#matthew#SOURCE#email_log#anomaly_detector", "DATE#2026-03-29"),
    ("USER#matthew#SOURCE#email_log#daily_brief", "DATE#2026-03-29"),
    ("USER#matthew#SOURCE#email_log#weekly_plate", "DATE#2026-04-04"),
    ("USER#matthew#SOURCE#experiments", "EXP#breathwork-before-sleep"),
    ("USER#matthew#SOURCE#field_notes", "WEEK#2026-W14"),
    ("USER#matthew#SOURCE#food_delivery", "DATE#2026-03-28"),
    ("USER#matthew#SOURCE#food_delivery", "DATE#2011-09-26#TXN#001"),
    ("USER#matthew#SOURCE#food_delivery", "MONTH#2011-09"),
    ("USER#matthew#SOURCE#food_delivery", "STREAK#current"),
    ("USER#matthew#SOURCE#food_delivery", "YEAR#2011"),
    ("USER#matthew#SOURCE#garmin", "DATE#2022-04-25"),
    ("USER#matthew#SOURCE#genome", "GENE#ABCG8#SNP#rs6544713"),
    ("USER#matthew#SOURCE#genome", "SUMMARY"),
    ("USER#matthew#SOURCE#google_calendar", "DATE#2026-03-08"),
    ("USER#matthew#SOURCE#habit_scores", "DATE#2026-02-23"),
    ("USER#matthew#SOURCE#habitify", "DATE#2026-02-23"),
    ("USER#matthew#SOURCE#health_check", "DATE#2026-03-29"),
    ("USER#matthew#SOURCE#hevy", "DATE#2021-04-12"),
    ("USER#matthew#SOURCE#hevy", "DATE#2021-04-12#WORKOUT#f62548ef"),
    ("USER#matthew#SOURCE#hevy_id_map", "HEVY#24869bbd"),
    ("USER#matthew#SOURCE#hevy_id_map", "PLATFORM#1f1acb0f"),
    ("USER#matthew#SOURCE#hypotheses", "HYPOTHESIS#2026-05-10T19:01:01"),
    ("USER#matthew#SOURCE#insights", "INSIGHT#2026-02-23T02:13:57"),
    ("USER#matthew#SOURCE#journal_analysis", "DATE#2026-03-03"),
    ("USER#matthew#SOURCE#labs", "DATE#2019-05-01"),
    ("USER#matthew#SOURCE#labs", "PROVIDER#function_health#2025-spring"),
    ("USER#matthew#SOURCE#ledger", "TOTALS#current"),
    ("USER#matthew#SOURCE#macrofactor", "DATE#2025-11-24"),
    ("USER#matthew#SOURCE#macrofactor_workouts", "DATE#2021-04-12"),
    ("USER#matthew#SOURCE#measurements", "DATE#2026-03-29"),
    ("USER#matthew#SOURCE#notion", "DATE#2023-12-19#journal#journal#1"),
    ("USER#matthew#SOURCE#nutrition_review", "DATE#2026-02-28"),
    ("USER#matthew#SOURCE#platform_memory", "MEMORY#baseline_snapshot#2026-05-03"),
    ("USER#matthew#SOURCE#platform_memory", "MEMORY#failure_pattern#2026-03-09#0"),
    ("USER#matthew#SOURCE#platform_memory", "MEMORY#failure_patterns#2026-05-03"),
    ("USER#matthew#SOURCE#platform_memory", "MEMORY#hypothesis_monitoring#2026-05-10"),
    ("USER#matthew#SOURCE#platform_memory", "MEMORY#weekly_plate#2026-03-14"),
    ("USER#matthew#SOURCE#protocols", "PROTOCOL#cgm"),
    ("USER#matthew#SOURCE#routine_index", "DATE#2026-06-01#ROUTINE#08626dd0"),
    ("USER#matthew#SOURCE#sick_days", "DATE#2026-03-08"),
    ("USER#matthew#SOURCE#sleep_unified", "DATE#2026-02-01"),
    ("USER#matthew#SOURCE#strava", "DATE#2009-05-27"),
    ("USER#matthew#SOURCE#subscribers", "EMAIL#0269def9"),
    ("USER#matthew#SOURCE#supplements", "DATE#2026-02-24"),
    ("USER#matthew#SOURCE#todoist", "DATE#2022-03-17"),
    ("USER#matthew#SOURCE#weather", "DATE#2026-02-26"),
    ("USER#matthew#SOURCE#weekly_correlations", "WEEK#2026-W11"),
    ("USER#matthew#SOURCE#whoop", "DATE#2020-03-20"),
    ("USER#matthew#SOURCE#whoop", "DATE#2020-03-24#WORKOUT#6c4b981e"),
    ("USER#matthew#SOURCE#withings", "DATE#2012-06-04"),
    ("SUBSCRIBE#rate_limit", "IP#035142ad#BUCKET#5933874"),
    ("USER#matthew", "PROFILE#v1"),
    ("USER#matthew", "SOURCE#coach_thread#explorer#2026-04-08"),
    ("USER#matthew#MEMORY", "CYCLE#1#launch"),
    ("USER#matthew#MEMORY", "MEMORY#re_entry#2026-05-03"),
    ("USER#matthew#ROUTINE#08626dd0", "VERSION#000001"),
    ("USER#system", "CANARY#last_state"),
    ("USER#system", "INGESTION_STATE#hevy"),
    ("VOTES#challenges", "CH#no-doordash-30"),
    ("CHALLENGE_FOLLOWS", "EMAIL#0269def9#CH#no-doordash-30"),
    ("USER#matthew#SOURCE#benchmarks", "EPISODE#2026-06-14"),
    ("ENSEMBLE#dispute", "THREAD#2026-W27#deficit_depth"),
    # Reading / Mind pillar (ADR-097) — CROSS_PHASE, durable identity data
    ("BOOK#0123456789abcdef", "META"),
    ("READING#0123456789abcdef", "STATE"),
    ("READING#0123456789abcdef", "SESSION#2026-06-29T20:00:00+00:00"),
    ("READING#0123456789abcdef", "NOTE#n1"),
    ("READING#0123456789abcdef", "RECALL#p1"),
    ("READING#REC", "REC#2026-06-29T20:00:00+00:00"),
    ("READING#PROFILE", "CURRENT"),
    ("READING#IDEA#idea1", "META"),
    ("READING#IDEA#idea1", "EDGE#idea2"),
    ("READING#NUDGE", "RECALL_QUEUE#current"),  # Phase D recall sweep snapshot
]


@pytest.mark.parametrize("pk,sk", LIVE_FAMILIES)
def test_every_live_family_classifies(pk, sk):
    cls = pt.classify(pk, sk)
    assert cls in pt.VALID_CLASSES, f"{pk} / {sk} → invalid class {cls!r}"


def test_unknown_source_raises_not_defaults():
    with pytest.raises(KeyError):
        pt.classify("USER#matthew#SOURCE#brand_new_source", "DATE#2026-06-07")


def test_unknown_pk_raises():
    with pytest.raises(KeyError):
        pt.classify("WIDGET#mystery", "X#1")


# ── Decision spot-checks (ADR-077) ────────────────────────────────────────────


@pytest.mark.parametrize(
    "source,expected",
    [
        ("labs", pt.CROSS_PHASE),
        ("dexa", pt.CROSS_PHASE),
        ("genome", pt.CROSS_PHASE),
        ("supplements", pt.CROSS_PHASE),  # dec A — med safety
        ("chronicling", pt.CROSS_PHASE),  # dec D — frozen "before" archive
        ("subscribers", pt.CROSS_PHASE),
        ("benchmarks", pt.CROSS_PHASE),  # BENCH-1 cut-benchmarking history — cross-cycle by design
        ("forecast", pt.EXPERIMENT_SCOPED),
        ("state_of_matthew", pt.EXPERIMENT_SCOPED),
        ("engagement_state", pt.EXPERIMENT_SCOPED),
        ("scenarios", pt.EXPERIMENT_SCOPED),
        ("what_changed", pt.EXPERIMENT_SCOPED),
        ("panelcast", pt.EXPERIMENT_SCOPED),
        ("measurements", pt.RAW_TIMESERIES),  # dec B — body fact, GA not hide
        ("day_grade", pt.RAW_TIMESERIES),  # dec C — keep series for Replay
        ("whoop", pt.RAW_TIMESERIES),
        ("hevy", pt.RAW_TIMESERIES),
        ("food_delivery", pt.RAW_TIMESERIES),
        ("email_log", pt.SYSTEM_STATE),  # dec E
        ("journal_analysis", pt.SYSTEM_STATE),
        ("google_calendar", pt.SYSTEM_STATE),  # dead
        ("composite_scores", pt.SYSTEM_STATE),  # dead
        ("insights", pt.EXPERIMENT_SCOPED),
        ("hypotheses", pt.EXPERIMENT_SCOPED),
        ("experiments", pt.EXPERIMENT_SCOPED),
        ("challenges", pt.EXPERIMENT_SCOPED),
        ("chronicle", pt.EXPERIMENT_SCOPED),
        ("habit_scores", pt.EXPERIMENT_SCOPED),
        ("character_sheet", pt.EXPERIMENT_SCOPED),
        ("ledger", pt.EXPERIMENT_SCOPED),
    ],
)
def test_source_decisions(source, expected):
    assert pt.classify(f"USER#matthew#SOURCE#{source}", "DATE#2026-01-01") == expected


@pytest.mark.parametrize(
    "source",
    [
        "email_log#daily_brief",
        "email_log#anomaly_detector",
        "email_log#weekly_plate",
    ],
)
def test_email_log_family_is_system_state(source):
    assert pt.classify(f"USER#matthew#SOURCE#{source}", "DATE#2026-03-29") == pt.SYSTEM_STATE


def test_platform_memory_split():
    pk = "USER#matthew#SOURCE#platform_memory"
    # durable → cross_phase
    assert pt.classify(pk, "MEMORY#baseline_snapshot#2026-05-03") == pt.CROSS_PHASE
    assert pt.classify(pk, category="re_entry") == pt.CROSS_PHASE
    # running-state → experiment_scoped (both failure_pattern spellings, ADR-077 finding 4)
    assert pt.classify(pk, "MEMORY#failure_pattern#2026-03-09") == pt.EXPERIMENT_SCOPED
    assert pt.classify(pk, "MEMORY#failure_patterns#2026-05-03") == pt.EXPERIMENT_SCOPED
    assert pt.classify(pk, category="failure_patterns") == pt.EXPERIMENT_SCOPED
    assert pt.classify(pk, "MEMORY#weekly_plate#2026-03-14") == pt.EXPERIMENT_SCOPED


def test_pk_rules():
    # coach intelligence + ensemble + narrative = experiment_scoped
    assert pt.classify("COACH#sleep_coach", "THREAD#2026-04-06#x") == pt.EXPERIMENT_SCOPED
    assert pt.classify("ENSEMBLE#digest", "CYCLE#2026-04-08") == pt.EXPERIMENT_SCOPED
    assert pt.classify("NARRATIVE#arc", "STATE#current") == pt.EXPERIMENT_SCOPED
    # the coach_thread leak partition (bare USER#matthew pk) = experiment_scoped
    assert pt.classify("USER#matthew", "SOURCE#coach_thread#explorer#2026-04-08") == pt.EXPERIMENT_SCOPED
    # durable + identity + infra = never-touch classes
    assert pt.classify("USER#matthew", "PROFILE#v1") == pt.CROSS_PHASE
    assert pt.classify("USER#matthew#MEMORY", "CYCLE#1#launch") == pt.CROSS_PHASE
    assert pt.classify("ENSEMBLE#influence_graph", "CONFIG#v1") == pt.SYSTEM_STATE
    assert pt.classify("PULSE", "DATE#2026-04-04") == pt.SYSTEM_STATE
    assert pt.classify("USER#system", "CANARY#last_state") == pt.SYSTEM_STATE
    # audience state — kept across resets (reader emails awaiting challenge-start notify)
    assert pt.classify("CHALLENGE_FOLLOWS", "EMAIL#abc#CH#no-doordash-30") == pt.SYSTEM_STATE
    # inter-coach dispute threads (#540) = experiment_scoped, wiped at reset
    assert pt.classify("ENSEMBLE#dispute", "THREAD#2026-W27#deficit_depth") == pt.EXPERIMENT_SCOPED
    # reading / Mind pillar (ADR-097) = cross_phase (durable, never wiped)
    assert pt.classify("BOOK#abc", "META") == pt.CROSS_PHASE
    assert pt.classify("READING#abc", "STATE") == pt.CROSS_PHASE
    assert pt.classify("READING#REC", "REC#2026-06-29T20:00:00+00:00") == pt.CROSS_PHASE
    assert pt.classify("READING#IDEA#x", "EDGE#y") == pt.CROSS_PHASE


def test_helper_predicates():
    assert pt.is_wipeable(pt.EXPERIMENT_SCOPED) is True
    assert pt.is_wipeable(pt.RAW_TIMESERIES) is False
    assert pt.never_touch(pt.CROSS_PHASE) is True
    assert pt.never_touch(pt.SYSTEM_STATE) is True
    assert pt.never_touch(pt.EXPERIMENT_SCOPED) is False
    assert "insights" in pt.SCOPED_SOURCES
    assert "labs" in pt.CROSS_PHASE_SOURCES
    assert "whoop" in pt.RAW_TIMESERIES_SOURCES
