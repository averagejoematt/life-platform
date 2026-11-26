"""tests/test_character_method_6293.py — #6293: the character method revision (owner rulings 2026-11-26).

"Remove journaling frequency, model-inferred values and inappropriate missing-data penalties from psychological
scoring." · "Relationships should remain uninstrumented until a defensible, owner-approved assessment exists." ·
"Missing qualitative information must not automatically mean deterioration." Habit components keep their two-state
rule (an unlogged habit is a failed habit — an earlier owner ruling), so they are pinned here too.

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
            for p, v in rec.items():
                if p.startswith("pillar_"):
                    hist.setdefault(p[7:], []).append(v["raw_score"])
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
            assert rel["not_instrumented"] is True and rel["xp_delta"] == 0 and rel["level"] == 1
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


def test_mind_still_qualifies_for_atrophy_by_its_habits_not_its_journal():
    share = ce._behavioral_weight_share(CONFIG["pillars"]["mind"])
    assert share == 0.625  # t0 + t1 + reading; the journal no longer contributes
    assert share >= CONFIG["leveling"]["neglect_decay"]["min_behavioral_share"]
    assert ce._behavioral_weight_share(CONFIG["pillars"]["relationships"]) == 0.0
