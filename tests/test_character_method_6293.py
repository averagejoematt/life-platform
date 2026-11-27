"""tests/test_character_method_6293.py — #6293: the character method revision (owner rulings 2026-11-26).

"Remove journaling frequency, model-inferred values and inappropriate missing-data penalties from psychological
scoring." · "Relationships should remain uninstrumented until a defensible, owner-approved assessment exists." ·
"Missing qualitative information must not automatically mean deterioration." Habit components keep their two-state
rule (an unlogged habit is a failed habit — an earlier owner ruling), so they are pinned here too.

The AMENDMENT (owner ruling 2026-11-26): "Amend the calculation so uninstrumented Relationships is excluded entirely
from consistency, variance and related aggregate calculations. Do not substitute a neutral value of 50 for missing
evidence." · "Also reconcile the already-identified missing-data penalties, XP debt and rest decay. Inactivity, missing
journals or appropriate rest should not automatically imply psychological deterioration or generate punitive character
mechanics." Tests (a)-(f) below pin it.

Every fixture is synthetic. The engine runs under the repo config (the deployable twin of the S3 config).
"""

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lambdas"))

from health import character_engine as ce  # noqa: E402

CONFIG = json.loads((REPO / "config" / "character_sheet.json").read_text(encoding="utf-8"))
RETIRED_MIND = ("journal_consistency", "values_alignment")
RETIRED_RELATIONSHIPS = ("social_interaction_frequency", "interaction_quality", "social_mood_correlation")

# The journal-side inputs a day can carry — every one is the journal or a model's reading of it.
JOURNAL_INPUTS = {
    "journal_entries": [{"sk": "DATE#2026-10-01#journal#evening", "enriched_social_quality": "deep", "enriched_mood": 5}],
    "journal": {"themes": ["friends", "family"], "mood_avg": 9.0},
    "journal_14d_count": 14,
    "flourishing": {"values_lived_count": 3, "social_quality_score": 10.0, "enrichment_model": "synthetic-model"},
}


def _mind_day(**over):
    day = {
        "habit_scores": {"tier0_pct": 0.8, "tier1_pct": 0.5},
        "state_of_mind": {"som_avg_valence": 0.2},
        "vice_streaks": {"synthetic_a": 7, "synthetic_b": 14},
        "reading_session_days_7d": ["d1", "d2"],
    }
    day.update(over)
    return day


def test_config_mind_weights_are_renormalised_explicitly():
    comps = CONFIG["pillars"]["mind"]["components"]
    assert not set(RETIRED_MIND) & set(comps)
    assert {k: v["weight"] for k, v in comps.items()} == {
        "t0_habit_compliance": 0.375,
        "t1_habit_compliance": 0.125,
        "state_of_mind_valence": 0.125,
        "stress_management": 0.125,
        "vice_control": 0.125,
        "reading_practice": 0.125,
    }
    assert math.isclose(sum(v["weight"] for v in comps.values()), 1.0)
    assert CONFIG["pillars"]["relationships"]["components"] == {}
    assert ce.ENGINE_VERSION == "1.10.0" and CONFIG["_meta"]["version"] == "1.7.0"


def test_mind_is_scored_without_the_two_components():
    raw, details = ce.compute_mind_raw(_mind_day(), CONFIG)
    assert not set(RETIRED_MIND) & set(details)
    # t0 80, t1 50, SoM (0.2+1)/2*100 = 60, vice log-curve of avg streak 10.5, reading 2/4 days at perfect 1.25 = 40
    vice = round(100 * math.log(1 + 10.5) / math.log(31), 1)
    expected = (80 * 0.375 + 50 * 0.125 + 60 * 0.125 + vice * 0.125 + 40 * 0.125) / 0.875  # stress held out of both sides
    assert details["_data_coverage"] == 1.0
    assert raw == round(expected, 1)


def test_journal_inputs_move_no_score_even_under_a_stale_config():
    """The S3 twin can lag the repo: a config that still lists the retired components must not revive them."""
    stale = json.loads(json.dumps(CONFIG))
    stale["pillars"]["mind"]["components"].update(
        {"journal_consistency": {"weight": 0.1, "behavioral": True}, "values_alignment": {"weight": 0.1}}
    )
    stale["pillars"]["relationships"]["components"] = {k: {"weight": 0.3} for k in RETIRED_RELATIONSHIPS}
    for cfg in (CONFIG, stale):
        assert ce.compute_mind_raw(_mind_day(**JOURNAL_INPUTS), cfg) == ce.compute_mind_raw(_mind_day(), cfg)
        raw, details = ce.compute_relationships_raw(_mind_day(**JOURNAL_INPUTS), cfg)
        assert raw == 50.0 and details["_not_instrumented"] is True


def test_absent_journal_neither_zeroes_nor_decays_mind_across_a_chain():
    """Two 21-day chains, identical but for the journal: one journals daily, one never does (its 14-day count is 0,
    the lambda's shape for a quiet fortnight). The journal channel is quiet; food is logged, so presence is 'present'.
    Mind's raw, level, XP, debt and decay are identical day by day; Relationships is held in both."""
    engaged = {"presence_class": "present", "gap_days": 0, "planned_pause": False, "channels_quiet": ["Journal"]}

    def chain(journal: bool):
        prev, hist, out = None, {}, []
        for i in range(21):
            day = _mind_day(date=f"2026-10-{i + 1:02d}", engagement_state=engaged)
            day.update(JOURNAL_INPUTS if journal else {"journal_14d_count": 0, "journal_entries": [], "journal": None, "flourishing": None})
            rec = ce.compute_character_sheet(day, prev, hist, CONFIG)
            _append_judged(hist, rec)
            out.append(rec)
            prev = rec
        return out

    with_j, without_j = chain(True), chain(False)
    keys = ("raw_score", "level_score", "level", "xp_total", "xp_debt", "neglect_decay", "absent_behaviors", "data_coverage")
    for a, b in zip(with_j, without_j):
        assert {k: a["pillar_mind"][k] for k in keys} == {k: b["pillar_mind"][k] for k in keys}
        assert a["pillar_mind"]["neglect_decay"] is None
        assert "journal_consistency" not in a["pillar_mind"]["absent_behaviors"]
        for rec in (a, b):
            rel = rec["pillar_relationships"]
            assert rel["not_instrumented"] is True and "level" not in rel and "xp_delta" not in rel
        assert a["character_level"] == b["character_level"]


def test_habit_components_keep_their_two_state_rule():
    """An unlogged habit is a failed habit (earlier owner ruling): no habit_scores record → both habit components
    score 0 at full weight and are listed absent; a logged day scores its share. Unchanged by #6293."""
    raw, details = ce.compute_mind_raw(_mind_day(habit_scores=None), CONFIG)
    assert details["_absent_behaviors"][:2] == ["t0_habit_compliance", "t1_habit_compliance"]
    assert details["t0_habit_compliance"] == {"score": 0.0, "weight": 0.375, "absent": True}
    assert details["t1_habit_compliance"] == {"score": 0.0, "weight": 0.125, "absent": True}
    _raw, logged = ce.compute_mind_raw(_mind_day(), CONFIG)
    assert logged["t0_habit_compliance"]["score"] == 80.0 and logged["t1_habit_compliance"]["score"] == 50.0
    # The core-12 set fills both habit components when armed (#5124) — unchanged.
    _raw, core = ce.compute_mind_raw(_mind_day(habit_scores={"scoring_method": "core_set_v1", "core_pct": 0.75}), CONFIG)
    assert core["t0_habit_compliance"]["score"] == core["t1_habit_compliance"]["score"] == 75.0
    assert raw < _raw  # the absent habits cost the day, as before


# ══════════════════════════════════════════════════════════════════════════════
# The amendment — (a) to (f)
# ══════════════════════════════════════════════════════════════════════════════

PRIMARY = ("sleep", "movement", "nutrition", "metabolic", "mind")


def _append_judged(hist, rec):
    """The history loader's rule (``character_sheet_lambda.load_raw_score_histories``): judged pillar-days only."""
    for key, v in rec.items():
        if key.startswith("pillar_") and isinstance(v, dict) and v.get("raw_score") is not None and not ce.day_is_held(v):
            hist.setdefault(key[7:], []).append(v["raw_score"])


def _full_day(date, **over):
    """A synthetic, fully-measured day across every primary pillar."""
    day = _mind_day(date=date)
    day.update(
        {
            "sleep": {"sleep_duration_hours": 7.6, "sleep_efficiency_pct": 90, "deep_sleep_pct": 0.18, "rem_sleep_pct": 0.22},
            "apple": {"steps": 9500, "blood_glucose_time_in_range_pct": 92},
            "bp_data": {"systolic": 118, "diastolic": 76},
            "whoop": {"resting_heart_rate": 55},
            "strava_7d": [],
            "hevy_workout_days_7d": ["a", "b", "c"],
            "macrofactor": {"calories_kcal": 2300, "protein_g": 180},
            "latest_weight": 250.0,
            "data_completeness_pct": 100.0,
            "todoist": {"overdue_count": 1},
            "engagement_state": {"presence_class": "present", "gap_days": 0, "planned_pause": False},
        }
    )
    day.update(over)
    return day


def _warm_chain(days=21):
    prev, hist = None, {}
    for i in range(days):
        rec = ce.compute_character_sheet(_full_day(f"2026-10-{i + 1:02d}"), prev, hist, CONFIG)
        _append_judged(hist, rec)
        prev = rec
    return prev, hist


def test_a_uninstrumented_relationships_changes_no_aggregate():
    """(a) Relationships is in no aggregate: the variance is over the judged pillars only, the headline is the weighted
    mean without it, the mood composite never sees a 50, and its inputs (or a stale config listing components for it)
    change nothing anywhere in the record."""
    prev, hist = _warm_chain()
    day = _full_day("2026-10-22")
    rec = ce.compute_character_sheet(day, prev, hist, CONFIG)
    assert "relationships" in rec["headline_excluded_pillars"] and rec["uninstrumented_pillars"] == ["relationships"]
    assert "relationships" not in rec["progression_transitions"]["pillars"]
    # The variance: exactly the stdev of the judged primary pillars' raws — no placeholder in it.
    import statistics

    judged = [rec[f"pillar_{p}"]["raw_score"] for p in PRIMARY if not ce.day_is_held(rec[f"pillar_{p}"])]
    assert len(judged) == len(PRIMARY)  # the fixture judges every primary pillar
    var = rec["pillar_consistency"]["components"]["cross_pillar_variance"]["score"]
    assert var == ce._deviation_score(statistics.stdev(judged), ideal=0, worst=30)
    # The headline: the weighted floor-mean over the pillars that carry a level.
    w = {p: CONFIG["pillars"][p]["weight"] for p in (*PRIMARY, "consistency")}
    mean = sum(rec[f"pillar_{p}"]["level"] * w[p] for p in w) / sum(w.values())
    assert rec["character_level"] == max(1, math.floor(mean))
    # The mood composite: the mean of judged raws only.
    comp = rec["character_mood_inputs"]["composite_raw"]
    judged_all = [rec[f"pillar_{p}"]["raw_score"] for p in (*PRIMARY, "consistency") if not ce.day_is_held(rec[f"pillar_{p}"])]
    assert comp == round(sum(judged_all) / len(judged_all), 1)
    # Its inputs and a stale config cannot move a thing.
    stale = json.loads(json.dumps(CONFIG))
    stale["pillars"]["relationships"]["components"] = {k: {"weight": 0.3} for k in RETIRED_RELATIONSHIPS}
    loud = ce.compute_character_sheet(dict(day, **JOURNAL_INPUTS), prev, hist, stale)
    strip = ("computed_at",)
    assert {k: v for k, v in loud.items() if k not in strip} == {k: v for k, v in rec.items() if k not in strip}


def test_a_the_public_method_also_leaves_relationships_out():
    from health import character_privacy

    assert "relationships" in character_privacy.UNSCORED_PUBLIC_PILLARS
    assert character_privacy.UNSCORED_PUBLIC_PILLARS["relationships"] != character_privacy.UNSCORED_PUBLIC_PILLARS["mind"]
    shape = character_privacy.not_scored_pillar("relationships")
    assert not {"raw_score", "level", "xp_total"} & set(shape)


def _silent(date, **over):
    day = {"date": date, "engagement_state": {"presence_class": "dark", "gap_days": 9, "planned_pause": False}}
    day.update(over)
    return day


_FROZEN_KEYS = ("level_score", "level", "xp_total", "xp_debt", "neglect_decay", "streak_below")


def _assert_silence_moves_nothing(days):
    prev, hist = _warm_chain()
    before = {p: {k: prev[f"pillar_{p}"][k] for k in _FROZEN_KEYS} for p in ("sleep", "movement", "nutrition", "metabolic", "consistency")}
    xp_before = {p: prev[f"pillar_{p}"]["xp_total"] for p in (*PRIMARY, "consistency")}
    level_before = prev["character_level"]
    for i, day in enumerate(days):
        rec = ce.compute_character_sheet(day, prev, hist, CONFIG)
        _append_judged(hist, rec)
        for p, frozen in before.items():
            assert {k: rec[f"pillar_{p}"][k] for k in _FROZEN_KEYS} == frozen, (i, p)
        for p, xp in xp_before.items():
            assert rec[f"pillar_{p}"]["xp_total"] >= xp  # XP never falls — Mind included
            assert rec[f"pillar_{p}"]["xp_debt"] == 0
        assert not [e for e in rec["level_events"] if e["type"] in ("level_down", "tier_down") and e.get("pillar") != "mind"]
        assert rec["neglect_decay"] is None and rec["character_xp_debt"] == 0
        prev = rec
    return prev, level_before


def test_b_consecutive_no_data_days_change_no_xp_ema_or_level():
    """(b) 14 days with no data at all and presence dark: every pillar but Mind keeps its EMA level score, level,
    streaks and XP exactly; no pillar's XP falls. (Mind still sees its habits as unlogged — the two-state habit rule,
    unchanged — and nothing else.)"""
    _assert_silence_moves_nothing([_silent(f"2026-10-{22 + i:02d}") for i in range(10)])


def test_c_a_planned_rest_stretch_changes_no_xp_ema_or_level():
    """(c) A planned pause (rest), the wearable off and nothing logged: likewise frozen."""
    rest = {"presence_class": "dark", "gap_days": 6, "planned_pause": True}
    _assert_silence_moves_nothing([_silent(f"2026-10-{22 + i:02d}", engagement_state=rest) for i in range(7)])


def test_b_silent_mind_moves_only_by_its_habits():
    """On a silent day Mind's only scored inputs are its habits (two-state): with the habit record present at the warm
    chain's rate, the day's Mind raw is exactly the habit share — absent reading, valence and vice are unknown."""
    raw, details = ce.compute_mind_raw({"habit_scores": {"tier0_pct": 0.8, "tier1_pct": 0.5}}, CONFIG)
    assert details["_raw_unblended"] == round((80 * 0.375 + 50 * 0.125) / 0.5, 1)
    for name in ("reading_practice", "state_of_mind_valence", "vice_control"):
        assert details[name]["score"] is None and not details[name].get("absent")


def test_d_absent_reading_input_does_not_zero_mind():
    """(d) No reading log: unknown, not 0 at full weight — out of the sum, lowering the coverage."""
    raw_with, with_r = ce.compute_mind_raw(_mind_day(reading_session_days_7d=["d1", "d2", "d3", "d4", "d5"]), CONFIG)
    raw_none, no_r = ce.compute_mind_raw(_mind_day(reading_session_days_7d=None), CONFIG)
    assert no_r["reading_practice"] == {"score": None, "weight": 0.125}
    assert "reading_practice" not in no_r["_absent_behaviors"]
    others = (80 * 0.375 + 50 * 0.125 + 60 * 0.125 + no_r["vice_control"]["score"] * 0.125) / 0.75
    assert no_r["_raw_unblended"] == round(others, 1)
    assert no_r["_data_coverage"] == round(0.75 / 0.875, 3)


def test_d_every_non_habit_component_is_unknown_when_absent():
    """The full list of components whose treatment changed: every config component flagged ``behavioral`` that is not a
    T0/T1 habit."""
    changed = sorted(
        f"{p}.{c}"
        for p, pc in CONFIG["pillars"].items()
        for c, cc in pc.get("components", {}).items()
        if cc.get("behavioral") and c not in ce.HABIT_TWO_STATE_COMPONENTS
    )
    assert changed == [
        "mind.reading_practice",
        "movement.movement_diversity",
        "movement.strength_sessions",
        "movement.training_frequency",
        "movement.zone2_adequacy",
        "nutrition.calorie_adherence",
        "nutrition.consistency",
        "nutrition.protein_distribution",
        "nutrition.protein_total",
    ]
    for entry in changed:
        p, c = entry.split(".")
        _raw, d = ce._weighted_pillar_score({c: None, "_m": 50.0}, {c: CONFIG["pillars"][p]["components"][c], "_m": {"weight": 1.0}})
        assert d[c]["score"] is None and not d["_absent_behaviors"], entry


def test_e_habits_still_two_state_under_the_amendment():
    _raw, d = ce._weighted_pillar_score(
        {"t0_habit_compliance": None, "t1_habit_compliance": None, "_m": 60.0},
        {**{k: CONFIG["pillars"]["mind"]["components"][k] for k in ce.HABIT_TWO_STATE_COMPONENTS}, "_m": {"weight": 0.5}},
    )
    assert d["_absent_behaviors"] == ["t0_habit_compliance", "t1_habit_compliance"]
    assert d["t0_habit_compliance"]["score"] == 0.0 and d["_data_coverage"] == 1.0


def test_f_no_code_path_produces_xp_debt():
    """(f) Every XP entry point, over every raw score, hold state, prior debt and bonus: debt 0, XP never below its
    prior; and a full chain carries 0 debt on every pillar and the headline."""
    for raw in range(0, 101, 5):
        for prev_debt in (0, 7, 100):
            for bonus in (0, 5):
                for hold in (False, True):
                    earned, delta, new_xp, debt = ce.pillar_xp_transition(raw, 30, prev_debt, bonus, hold, CONFIG, day_number=3)
                    assert debt == 0 and new_xp >= 30 and earned >= 0 and delta >= 0
                e2 = ce._compute_xp(raw, 30, CONFIG, previous_debt=prev_debt, bonus_xp=bonus)
                assert e2[3] == 0 and e2[2] >= 30
    prev = {f"pillar_{p}": {"level": 9, "xp_total": 0, "xp_debt": 80} for p in (*PRIMARY, "consistency")}
    prev["character_level"] = 9
    prev["character_xp_debt"] = 480
    rec = ce.compute_character_sheet(_silent("2026-10-22"), prev, {}, CONFIG)
    assert rec["character_xp_debt"] == 0
    assert all(rec[f"pillar_{p}"]["xp_debt"] == 0 for p in (*PRIMARY, "consistency"))
    assert all(not hasattr(ce, n) for n in ("neglect_decay_state", "_behavioral_weight_share", "DEFAULT_DAILY_XP_DECAY"))
    assert not {"daily_xp_decay", "xp_debt_cap", "neglect_decay"} & set(CONFIG["leveling"])
