"""tests/test_public_mind_unscored_6224.py — the public method v2 (#6224, owner rulings 2026-11-26).

The four rulings this file holds, each with a must-fail control so the check is shown to see what it guards:

  1. "Keep Mind unscored publicly." — "Do not publish a derived Mind score using private inputs ... Don't invent a public
     proxy merely to fill a graphical gap." The public variant does not score Mind at all: no score, level, tier, XP,
     driver or event, and nothing of Mind in the composite, the headline level or the XP total. Public routes serve the
     not-scored shape, and no public body carries a Mind score/level/tier/XP value.
  2. "Treat the food-delivery source's last-recorded date as private unless separately authorized." — the source is
     PRIVATE in the activity policy, no public route moves with its newest date, and its Nutrition multiplier never
     reaches the public variant.
  3. "Remove restraint-derived contributions from public streak milestones" — the streak rungs are judged on the PUBLIC
     tier-0 run, and a streak entry written from the stored streak is not served.
  4. "... and correlation metrics." — habit_pct (v2) and tier0_streak (the public run) leave restraint habits out, and a
     record stamped with an older method has those pairs withheld.

"Do not replace private inputs with inferred or renamed equivalents": Mind is not re-scored from a recounted habit share.

Names are synthetic throughout ("restraint_a", "ordinary_a" …); the route walk's canaries are tests/restraint_route_walk.py's.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import backfill_public_variant as B  # noqa: E402
import public_tier0_fixture as F  # noqa: E402
import restraint_route_walk as RW  # noqa: E402 — mind_numbers, the one Mind-number detector
from common import (  # noqa: E402
    activity_publication as AP,
    restraint_publication as RP,
)
from common.input_manifest import public_manifest  # noqa: E402
from health import (  # noqa: E402
    character_engine,
    character_privacy,
    character_public,
    habit_pct_public,
    milestone_ledger,
    public_corrections,
)

CONFIG = json.load(open(ROOT / "config" / "character_sheet.json", encoding="utf-8"))
GENESIS = "2026-09-06"
N_DAYS = 24


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def _days(n=N_DAYS):
    return [(date.fromisoformat(GENESIS) + timedelta(days=i)).isoformat() for i in range(n)]


# ── 1. Mind is not scored in public ───────────────────────────────────────────────────────


def _inputs(i: int, d: str, mind: str, fd: float = 1.0) -> dict:
    """One day's inputs. ``mind`` varies ONLY what Mind reads (its habit share, the reading log, the restraint streak);
    ``fd`` is the food-delivery multiplier method 1 applies to Nutrition. Everything else is identical."""
    hi = mind == "high"
    out = {
        "date": d,
        "sleep": {"sleep_duration_hours": 6.0 + (i % 5) * 0.5, "sleep_efficiency_percentage": 80 + (i % 7) * 2},
        "macrofactor": {"total_calories_kcal": 2000 + 30 * (i % 4), "total_protein_g": 150 + 5 * (i % 3)},
        "habit_scores": {
            "scoring_method": "core_set_v1",
            "core_pct": 0.95 if hi else 0.2,
            "date": d,
            "computed_at": f"{(date.fromisoformat(d) + timedelta(days=1)).isoformat()}T17:40:10+00:00",
            "input_manifest": {"sources": {"habitify": {"latest_day": d}}},
        },
        "vice_streaks": {"restraint_a": float(60 + i if hi else 0)},
        "reading_session_days_7d": [d] * (5 if hi else 0),
        "data_completeness_pct": 60.0 + (i % 3) * 20,
        "todoist": {"overdue_count": float(i % 5)},
        "engagement_state": {
            "presence_class": "present",
            "gap_days": 0,
            "planned_pause": False,
            "public": {"presence_class": "present", "gap_days": 0, "planned_pause": False},
        },
    }
    if fd != 1.0:
        out["raw_score_modifiers"] = {"nutrition": {"multiplier": fd, "source": "food_delivery"}}
    return out


def _history(mind: str, fd: float = 1.0) -> tuple:
    records, scores = {}, {}
    for i, d in enumerate(_days()):
        data = _inputs(i, d, mind, fd)
        hist = B.window_records(records, d)
        data.update(character_engine.derive_consistency_inputs(hist, d))
        rec = character_engine.compute_character_sheet(data, B.previous_record(records, d), B.raw_histories(hist), CONFIG)
        rec.pop("progression_transitions", None)
        rec["sk"] = f"DATE#{d}"
        records[d] = B.as_stored(rec)
        scores[d] = dict(data["habit_scores"], vice_streaks=data["vice_streaks"])
    return records, scores


def _replay(records, scores) -> dict:
    engagement = {d: _inputs(0, d, "low")["engagement_state"] for d in records}
    out = B.replay_character(records, engagement, scores, CONFIG, "2026-11-26T00:00:00+00:00")
    return {d: r["public"] for d, r in out.items()}


@pytest.fixture(scope="module")
def histories():
    low, high = _history("low"), _history("high")
    return low, high, _replay(*low), _replay(*high)


def test_method1_mind_really_moves_with_its_inputs(histories):
    """The control that Mind's inputs are really there: method 1's Mind differs between the two histories."""
    (low, _), (high, _), _, _ = histories
    last = _days()[-1]
    assert low[last]["pillar_mind"]["raw_score"] != high[last]["pillar_mind"]["raw_score"]


def test_the_public_variant_is_identical_whatever_minds_inputs_were(histories):
    """Every public block — composite inputs, level, XP, consistency, effects, mood — is byte-identical whether Mind's
    inputs (its habit share, the reading log, the restraint streak) were high or low on every day."""
    _, _, pub_low, pub_high = histories
    moved = [d for d in pub_low if _canon(pub_low[d]) != _canon(pub_high[d])]
    assert moved == [], f"the public variant moved with Mind's inputs on {moved}"


def test_must_fail_control_a_public_method_that_scored_mind_would_move(histories, monkeypatch):
    """Reopen Mind's scoring (v1's arithmetic): the same replay moves — the invariance above is the hold."""
    (low, s_low), (high, s_high), _, _ = histories
    monkeypatch.setattr(character_public, "UNSCORED_PILLARS", ())
    a, b = _replay(low, s_low), _replay(high, s_high)
    assert any(_canon(a[d]) != _canon(b[d]) for d in a)


def test_the_public_variant_carries_no_mind_number_and_says_why(histories):
    _, _, pub, _ = histories
    for d, block in pub.items():
        assert block["pillar_mind"] == character_privacy.not_scored_pillar("mind"), d
        assert "mind" in block["headline_excluded_pillars"] and block["unscored_pillars"] == ["mind", "relationships"], d
        assert RW.mind_numbers(block) == [], d
        assert not [e for e in block.get("level_events") or [] if e.get("pillar") == "mind"], d
        for ev in block.get("level_events") or []:
            assert not [x for x in ev.get("drivers") or [] if x.get("pillar") == "mind"], d
    shape = character_privacy.not_scored_pillar("mind")
    assert not {"level", "raw_score", "level_score", "tier", "xp_total", "xp_delta"} & set(shape)
    assert shape["not_scored_note"] == "Not scored in public: its inputs are private."


def test_the_engine_leaves_an_unscored_pillar_out_of_the_whole_chain():
    """``unscored_pillars``: no block, no place in the headline mean — the level is the floor of the weighted mean of the
    other pillars, never Mind at a neutral score; and the outputs do not depend on what Mind's computer would say."""
    data = _inputs(3, _days()[3], "high")
    low = dict(data, habit_scores=_inputs(3, _days()[3], "low")["habit_scores"], reading_session_days_7d=[])  # Mind's inputs only
    a = character_engine.compute_character_sheet(dict(data, unscored_pillars=["mind"]), None, {}, CONFIG)
    b = character_engine.compute_character_sheet(dict(low, unscored_pillars=["mind"]), None, {}, CONFIG)
    m1a, m1b = (character_engine.compute_character_sheet(x, None, {}, CONFIG) for x in (data, low))
    assert m1a["pillar_mind"]["raw_score"] != m1b["pillar_mind"]["raw_score"]  # control: Mind's inputs really differ
    assert "pillar_mind" not in a and "mind" not in a["progression_transitions"]["pillars"]
    strip = lambda r: {k: v for k, v in r.items() if k not in ("computed_at", "progression_transitions")}  # noqa: E731
    assert _canon(strip(a)) == _canon(strip(b))
    with_mind = character_engine.compute_character_sheet(data, None, {}, CONFIG)
    assert "pillar_mind" in with_mind  # method 1 (no key) is unchanged


def _v1_variant() -> dict:
    """A variant stored under v1 (Mind scored), as the table holds it until the recompute."""
    pv = {
        "public_method_version": character_privacy.PUBLIC_METHOD_V1,
        "origin": "live",
        "character_level": 7,
        "headline_excluded_pillars": ["relationships"],
        "active_effects": [
            {"name": "Mind Effect", "condition": "mind > 70", "targets": {"consistency": {"value": 0.03}}},
            {"name": "All Effect", "condition": "all_pillars >= 41", "targets": {"_all": {"value": 0.03}}},
            {"name": "Sleep Effect", "condition": "sleep < 35", "targets": {"movement": {"value": -0.08}, "mind": {"value": -0.05}}},
        ],
        "pillar_mind": {"level": 6, "raw_score": 61.0, "tier": "Foundation", "xp_total": 120, "drivers": {"top": ["reading_practice"]}},
        "pillar_sleep": {"level": 9, "raw_score": 72.0, "tier": "Foundation"},
        "level_events": [
            {"type": "level_up", "pillar": "mind", "old_level": 5, "new_level": 6},
            {
                "type": "character_level_up",
                "old_level": 6,
                "new_level": 7,
                "drivers": [{"pillar": "mind", "raw_score": 61.0}, {"pillar": "sleep"}],
            },
        ],
    }
    return {"sk": "DATE#2026-11-20", "date": "2026-11-20", "public": pv}


def test_a_stored_v1_variant_is_served_with_mind_not_scored_and_unnamed():
    record = _v1_variant()
    before = copy.deepcopy(record)
    view = character_privacy.public_sheet(record, pending=False)  # the Mind scrub, apart from the containment switch
    assert record == before, "the stored record is never changed"
    assert view["pillar_mind"] == character_privacy.not_scored_pillar("mind")
    assert [e["name"] for e in view["active_effects"]] == ["Sleep Effect"]  # mind's and (on v1) all_pillars' are gone
    assert view["active_effects"][0]["targets"] == {"movement": {"value": -0.08}}
    assert [e["type"] for e in view["level_events"]] == ["character_level_up"]
    assert view["level_events"][0]["drivers"] == [{"pillar": "sleep"}]
    assert view["headline_excluded_pillars"] == ["mind", "relationships"]  # #6293: both not scored in public
    assert RW.mind_numbers(view) == []
    assert view["pillar_sleep"] == record["public"]["pillar_sleep"]


def test_must_fail_control_without_the_scrub_the_v1_mind_numbers_are_served(monkeypatch):
    monkeypatch.setattr(character_privacy, "scrub_unscored", lambda view: view)
    view = character_privacy.public_sheet(_v1_variant(), pending=False)
    assert RW.mind_numbers(view), "the detector must see a v1 Mind served as stored"


def test_on_a_v2_variant_the_all_pillars_effect_stands():
    """v2's all_pillars reads only the scored pillars, so its firing says nothing about Mind: it is kept."""
    rec = _v1_variant()
    rec["public"]["public_method_version"] = character_privacy.PUBLIC_METHOD_VERSION
    view = character_privacy.public_sheet(rec, pending=False)
    assert {"All Effect", "Sleep Effect"} == {e["name"] for e in view["active_effects"]}


def test_a_method_change_is_never_a_headline_event(histories):
    """The first live v2 day after v1 history: a move from the v1 level is the method changing — no event. Control: the
    same day chained from a v2 state of that level does fire one."""
    (low, s_low), _, pub, _ = histories
    d = _days()[-1]
    prev = character_privacy.public_view({"sk": "x", "date": _days()[-2], "public": dict(pub[_days()[-2]], character_level=60)})
    hist = [character_privacy.public_view({"sk": "x", "date": h, "public": pub[h]}) for h in _days()[-22:-1]]
    hm, vice = B._engine_inputs(low[d], s_low)
    run = lambda p: character_public.compute_public_variant(low[d], p, hist, CONFIG, habit_method=hm, vice_streaks=vice)[0]  # noqa: E731
    v1_prev = dict(prev, public_method_version=character_privacy.PUBLIC_METHOD_V1)
    heads = lambda b: [e for e in b["level_events"] if e["type"].startswith("character_level")]  # noqa: E731
    assert heads(run(v1_prev)) == []
    assert heads(run(prev)), "control: chained from the same level under v2 the drop is an event"


def test_the_method_is_versioned_and_says_mind_is_not_scored():
    assert character_privacy.PUBLIC_METHOD_VERSION == "character-public-v2"
    assert character_privacy.PUBLIC_METHOD_VERSIONS == ("character-public-v1", "character-public-v2")
    note = character_privacy.PUBLIC_METHOD_HISTORY[-1]["note"]
    assert "Mind is not scored in public" in note and "food-delivery" in note
    for origin, label in character_privacy.PUBLIC_METHOD_LABELS.items():
        assert "Mind is not scored in public" in label and "(v2)" in label, origin
    v1 = {"public_method_version": character_privacy.PUBLIC_METHOD_V1, "origin": "recomputed", "character_level": 3}
    assert "(v1)" in character_privacy.public_method_label({"public": v1})["label"]  # a v1 value keeps its own words


def test_the_v2_correction_ledger_has_no_per_date_values():
    led = public_corrections.build_ledger({"2026-09-06": {"character_level": 3}, "2026-09-07": {"character_level": 3}}, "2026-11-26")
    assert led["rows"] == [] and led["dates_recalculated"] == 2 and led["ledger_version"] == public_corrections.LEDGER_VERSION
    assert public_corrections.served_ledger(dict(led, ledger_version="public-correction-ledger-v1")) is None


# ── 2. food delivery ──────────────────────────────────────────────────────────────────────


def test_the_food_delivery_source_is_private():
    assert AP.source_class("food_delivery") == AP.PRIVATE and not AP.source_is_public("food_delivery")
    manifest = {
        "status": "complete",
        "complete": True,
        "degraded": [],
        "unobserved": [],
        "sources": {
            "whoop": {"status": "fresh", "latest_day": "2026-11-25"},
            "food_delivery": {"status": "paused", "latest_day": "2026-05-01"},
        },
    }
    assert "food_delivery" not in public_manifest(manifest)["sources"]


@pytest.fixture(scope="module")
def delivery_histories():
    plain, scores = _history("low")
    taxed, scores_t = _history("low", fd=0.85)
    return (plain, scores), (taxed, scores_t)


def test_method1_nutrition_really_carries_the_multiplier(delivery_histories):
    (plain, _), (taxed, _) = delivery_histories
    d = _days()[-1]
    assert plain[d]["pillar_nutrition"]["raw_score"] != taxed[d]["pillar_nutrition"]["raw_score"]
    assert taxed[d]["pillar_nutrition"]["raw_modifier"]["pre_modifier_raw_unblended"] is not None


def test_the_public_variant_never_carries_the_delivery_multiplier(delivery_histories):
    a, b = _replay(*delivery_histories[0]), _replay(*delivery_histories[1])
    moved = [d for d in a if _canon(a[d]) != _canon(b[d])]
    assert moved == [], f"the public variant moved with the food-delivery multiplier on {moved}"
    assert all(b[d]["pillar_nutrition"].get("raw_modifier") is None for d in b)


def test_must_fail_control_a_public_delivery_source_would_reach_the_variant(delivery_histories, monkeypatch):
    monkeypatch.setitem(AP.ACTIVITY_ONLY_SOURCES, "food_delivery", AP.PUBLIC)
    a, b = _replay(*delivery_histories[0]), _replay(*delivery_histories[1])
    assert any(_canon(a[d]) != _canon(b[d]) for d in a)


def test_a_modifier_without_its_pre_modifier_values_is_refused():
    details = {"_raw_unblended": 40.0, "_modifier": {"source": "food_delivery", "multiplier": 0.85, "pre_modifier_raw": 50.0}}
    with pytest.raises(ValueError):
        character_public.without_private_modifiers(42.5, details)
    ok = dict(details, _modifier=dict(details["_modifier"], pre_modifier_raw_unblended=47.1))
    assert character_public.without_private_modifiers(42.5, ok) == (50.0, {"_raw_unblended": 47.1})


# ── 3 + 4. the shared restraint predicate: milestone streaks and correlation metrics ──────

REG = {
    "ordinary_a": {"status": "active", "tier": 0},
    "restraint_a": {"status": "active", "tier": 0},  # a restraint by its tracker group below
    "restraint_b": {"status": "active", "tier": 0, "vice": True},  # a restraint by the registry flag
}
_IDS = sorted(AP.PUBLIC_HABIT_IDS)


def _habitify(day: str, restraint_done: bool, ordinary_done: bool = True) -> dict:
    def st(i, group, done):
        return {"status": "completed" if done else "failed", "habit_id": _IDS[i], "group": group, "scheduled_today": True}

    statuses = {
        "ordinary_a": st(0, "Core", ordinary_done),
        "restraint_a": st(1, "Vice", restraint_done),
        "restraint_b": st(2, "Core", restraint_done),
    }
    habits = {n: 1 if s["status"] == "completed" else 0 for n, s in statuses.items()}
    return {"date": day, "sk": f"DATE#{day}", "habit_statuses": statuses, "habits": habits}


def test_habit_pct_v2_is_identical_whether_the_restraint_habits_were_kept():
    kept, missed = _habitify("2026-11-20", True), _habitify("2026-11-20", False)
    assert habit_pct_public.public_habit_pct(kept, REG) == habit_pct_public.public_habit_pct(missed, REG) == 1.0
    assert habit_pct_public.public_habit_pct(_habitify("2026-11-20", True, ordinary_done=False), REG) == 0.0  # not vacuous


def test_must_fail_control_habit_pct_with_the_switch_on_moves(monkeypatch):
    monkeypatch.setattr(RP, "RESTRAINT_DATA_PUBLISHED", True)
    assert habit_pct_public.public_habit_pct(_habitify("2026-11-20", True), REG) != habit_pct_public.public_habit_pct(
        _habitify("2026-11-20", False), REG
    )


def _series(monkeypatch, restraint_done: bool, registry=REG) -> dict:
    from compute import weekly_correlation_compute_lambda as wc

    days = [(date(2026, 11, 20) - timedelta(days=i)).isoformat() for i in range(10)][::-1]
    rows = [_habitify(d, restraint_done) for d in days]
    monkeypatch.setattr(wc, "fetch_range", lambda source, s, e: [r for r in rows if s <= r["date"] <= e] if source == "habitify" else [])
    return wc.assemble_daily_series(days[0], days[-1], registry=registry)


def test_the_weekly_correlation_series_never_moves_with_the_restraint_habits(monkeypatch):
    a, b = _series(monkeypatch, True), _series(monkeypatch, False)
    pick = lambda s: {d: (m["habit_pct"], m["tier0_streak"]) for d, m in s.items()}  # noqa: E731
    assert pick(a) == pick(b)
    assert a["2026-11-20"]["tier0_streak"] == 10.0 and a["2026-11-20"]["habit_pct"] == 1.0  # the public run, not vacuous
    assert _series(monkeypatch, True, registry=None)["2026-11-20"]["tier0_streak"] is None  # no registry: no run


def test_must_fail_control_the_series_moves_with_the_switch_on(monkeypatch):
    monkeypatch.setattr(RP, "RESTRAINT_DATA_PUBLISHED", True)
    a, b = _series(monkeypatch, True), _series(monkeypatch, False)
    assert a["2026-11-20"]["tier0_streak"] != b["2026-11-20"]["tier0_streak"]


def _pair(a, b):
    return {"metric_a": a, "metric_b": b, "pearson_r": 0.5, "n_days": 60, "n_eff": 40.0, "p_value": 0.001, "fdr_significant": True}


def test_a_record_stamped_with_an_older_method_serves_no_habit_or_streak_pair():
    corrs = {"a": _pair("habit_pct", "recovery_score"), "b": _pair("tier0_streak", "day_grade"), "c": _pair("hrv", "recovery_score")}
    old = AP.public_correlations(corrs, metric_methods={"day_grade": "day-grade-public-v1", "habit_pct": "habit-pct-public-v1"})
    assert set(old) == {"c"}
    new = AP.public_correlations(
        corrs,
        metric_methods={
            "day_grade": "day-grade-public-v1",
            "habit_pct": habit_pct_public.METHOD_VERSION,
            "tier0_streak": AP.TIER0_STREAK_PUBLIC_METHOD,
        },
    )
    assert set(new) == {"a", "b", "c"}  # the control: stamped with the public methods, the pairs serve


class _Ledger:
    """A query-only fake over pk-keyed rows (the milestone sweep's reads)."""

    def __init__(self, rows):
        self.rows = rows

    def query(self, **kw):
        vals = kw.get("ExpressionAttributeValues", {})
        out = [r for r in self.rows if r["pk"] == vals.get(":pk")]
        if ":s" in vals:
            out = [r for r in out if vals[":s"] <= r["sk"] <= vals[":e"]]
        if ":sk" in vals:
            out = [r for r in out if r["sk"] == vals[":sk"] or str(r["sk"]).startswith(str(vals[":sk"]))]
        return {"Items": sorted(out, key=lambda r: r["sk"])}


def _signals(restraint_done: bool) -> dict:
    U = "USER#matthew#SOURCE#"
    days = [(date(2026, 11, 20) - timedelta(days=i)).isoformat() for i in range(8)]
    rows = [{"pk": "USER#matthew", "sk": "PROFILE#v1", "habit_registry": copy.deepcopy(REG)}]
    rows += [dict(_habitify(d, restraint_done), pk=U + "habitify") for d in days]
    rows.append({"pk": U + "habit_scores", "sk": f"DATE#{days[0]}", "date": days[0], "t0_perfect_streak": 90 if restraint_done else 0})
    return milestone_ledger.collect_signals(_Ledger(rows), U, None, "2026-11-21")


def test_the_milestone_streak_signal_is_the_public_run():
    kept, missed = _signals(True), _signals(False)
    assert kept["tier0_streak"] == missed["tier0_streak"] == 8  # the stored 90/0 is never read
    assert kept["tier0_streak_basis"] == milestone_ledger.TIER0_STREAK_BASIS


def test_must_fail_control_the_milestone_signal_moves_with_the_switch_on(monkeypatch):
    monkeypatch.setattr(RP, "RESTRAINT_DATA_PUBLISHED", True)
    assert _signals(True)["tier0_streak"] != _signals(False)["tier0_streak"]


def test_a_streak_rung_needs_the_public_basis_and_a_stored_streak_entry_is_not_served():
    rule = milestone_ledger.RULES_BY_ID["streak_7"]
    assert milestone_ledger._satisfied(rule, {"tier0_streak": 9}, "2026-11-21") == (False, None)
    ok, meas = milestone_ledger._satisfied(
        rule, {"tier0_streak": 9, "tier0_streak_basis": milestone_ledger.TIER0_STREAK_BASIS}, "2026-11-21"
    )
    assert ok and meas["basis"] == milestone_ledger.TIER0_STREAK_BASIS
    stored = {"ladder": "streak", "announce": True, "event_date": "2026-10-01", "measurement": {"value": 7, "threshold": 7}}
    public = dict(stored, measurement=dict(stored["measurement"], basis=milestone_ledger.TIER0_STREAK_BASIS))
    other = {"ladder": "days_tracked", "announce": True, "event_date": "2026-10-02", "measurement": {"value": 30}}
    assert [milestone_ledger.servable_event(e) for e in (stored, public, other)] == [False, True, True]


def test_the_shared_public_run_matches_the_fixture():
    rows = []
    F.plant_public_run(rows.append, "USER#matthew#SOURCE#", "2026-11-20", 5)
    hab = [r for r in rows if r["pk"].endswith("habitify")]
    reg = rows[0]["habit_registry"]
    assert AP.public_tier0_figures(hab, reg, set(), "2026-11-20", "2026-10-01")["streak"] == 5


# ── every public route: food-delivery axis, and no Mind number anywhere ───────────────────


def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "restraint_route_walk.py"), *args], capture_output=True, text=True, timeout=300, cwd=str(ROOT)
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def walks() -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    runs = {
        "early": ("--state", "low", "--now", now, "--fd", "early"),
        "late": ("--state", "low", "--now", now, "--fd", "late"),
        "high": ("--state", "high", "--now", now, "--fd", "late"),
        "fd_public_early": ("--state", "low", "--now", now, "--fd", "early", "--fd-public"),
        "fd_public_late": ("--state", "low", "--now", now, "--fd", "late", "--fd-public"),
        "mind_scored": ("--state", "low", "--now", now, "--fd", "early", "--mind-scored"),
        "published": ("--state", "low", "--now", now, "--fd", "early", "--published"),
        "scores_live": ("--state", "low", "--now", now, "--fd", "early", "--scores-live"),
    }
    with ThreadPoolExecutor(max_workers=int(os.environ.get("RESTRAINT_WALK_WORKERS", "4"))) as pool:
        futures = {k: pool.submit(_walk, *a) for k, a in runs.items()}
        return {k: f.result() for k, f in futures.items()}


def _moved(a: dict, b: dict) -> list:
    x, y = a["all_bodies"], b["all_bodies"]
    return sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))


def test_the_walks_reach_every_route(walks):
    for k, out in walks.items():
        assert out["answered"] >= 140 and out["raised"] == {} and out["unparsed_queries"] == 0, (k, out["answered"], out["raised"])


def test_no_public_route_moves_with_the_food_delivery_sources_last_date(walks):
    assert _moved(walks["early"], walks["late"]) == [], "public routes whose body says when the food-delivery source last recorded"


def test_must_fail_control_with_the_source_public_the_walk_sees_its_date(walks):
    moved = set(_moved(walks["fd_public_early"], walks["fd_public_late"]))
    assert {"/api/character", "/api/snapshot", "/api/status"} <= moved, moved


def test_no_public_body_carries_a_mind_score_or_level(walks):
    for k in ("early", "late", "high"):
        assert walks[k]["mind"] == {}, (k, walks[k]["mind"])


def test_must_fail_control_a_scored_mind_is_seen_on_the_character_routes(walks):
    seen = set(walks["mind_scored"]["mind"])
    assert {"/api/character", "/api/character_stats", "/api/mind_overview", "/api/snapshot"} <= seen, seen


def test_the_public_engine_contract_carries_no_restraint_input_and_no_mind_scoring(walks):
    """/api/character_config describes the PUBLIC method only (#6224): no restraint component, no restraint-conditioned
    effect, Mind not scored. The gated walks find no restraint name on it (the tokens include the config's own
    restraint-conditioned effect names); with the restraint switch on, the walk does — so it reads that route."""
    for k in ("early", "late", "high"):
        assert "/api/character_config" not in walks[k]["leaks"], walks[k]["leaks"]
    assert "/api/character_config" in walks["published"]["leaks"], walks["published"]["leaks"]


def test_public_contract_drops_restraint_and_mind_scoring_from_the_config():
    cfg = character_public.public_contract(CONFIG)
    assert cfg["pillars"]["mind"]["components"] == {}
    assert not [e for e in cfg["cross_pillar_effects"] if character_privacy.effect_reads_restraint(e)]
    assert not [e for e in cfg["cross_pillar_effects"] if "mind" in str(e.get("condition")).lower().split()]
    assert not [e for e in cfg["cross_pillar_effects"] if "mind" in (e.get("targets") or {})]
    # control: the method-1 config has all three, so the contract is what removed them
    assert CONFIG["pillars"]["mind"]["components"] and any(
        character_privacy.effect_reads_restraint(e) for e in CONFIG["cross_pillar_effects"]
    )
    assert any("mind" in str(e.get("condition")).lower().split() for e in CONFIG["cross_pillar_effects"])
    assert CONFIG["cross_pillar_effects"] != cfg["cross_pillar_effects"]


def test_the_dry_run_manifest_takes_before_from_the_served_public_block(histories):
    """The owner approves the exact public change: a manifest row's "before" is the stored public block readers are
    served today (Mind as stored), never method 1; "after" is the recomputed variant as served (Mind not scored)."""
    import backfill_public_variant_cli as CLI

    (low, s_low), _, pub, _ = histories
    d = _days()[-1]
    stored_block = dict(pub[d], public_method_version=character_privacy.PUBLIC_METHOD_V1, character_level=41, character_xp=999.0)
    stored_block["pillar_mind"] = {"level": 33.0, "raw_score": 61.0, "tier": "Momentum"}
    snap = {"sheets": {d: dict(low[d], public=stored_block)}}
    char = {d: {"public": pub[d], "presence": None, "fidelity": [], "order_fix": None}}
    row = CLI.character_rows(snap, char)[0]
    assert row["character_level"] == [41.0, float(pub[d]["character_level"])] and row["level_changed"]
    assert row["character_xp"][0] == 999.0 and row["mind_level"] == [33.0, None] and row["mind_score"] == [61.0, None]
    assert row["character_level"][0] != float(low[d]["character_level"]) or low[d]["character_level"] == 41  # not method 1
    assert row["method1"]["character_level"][0] == float(low[d]["character_level"])  # method 1 kept for the private trail
    assert CLI.summary([row], [])["level_changed_dates"] == [d]


# ── D. containment: the contaminated chain values are pending a recompute ────────────────


def test_no_public_body_carries_an_overall_level_xp_or_composite_while_pending(walks):
    """Owner ruling 2026-11-26: until the corrected recompute, no public route presents the overall level, tier, XP, XP
    debt or composite as an authoritative value — it serves the "being recalculated" state."""
    assert character_privacy.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE is True
    for k in ("early", "late", "high"):
        assert walks[k]["overall"] == {}, (k, walks[k]["overall"])


def test_must_fail_control_with_the_switch_off_the_overall_values_return(walks):
    seen = set(walks["scores_live"]["overall"])
    assert {"/api/character", "/api/character_stats", "/api/snapshot", "/api/achievements"} <= seen, seen
    assert walks["scores_live"]["mind"] == {}, "Mind stays unscored whatever the switch says"


def test_a_pending_view_keeps_the_verbatim_raw_scores_and_nothing_chain_carried(histories):
    _, _, pub, _ = histories
    d = _days()[-1]
    view = character_privacy.public_sheet({"sk": f"DATE#{d}", "date": d, "public": pub[d]})
    assert view["scores_pending"] and view["score_status"] == "recalculating"
    assert not set(character_privacy.PENDING_OVERALL_KEYS) & set(view)
    assert view["level_events"] == [] and view["active_effects"] == []
    assert view["pillar_consistency"] == character_privacy.pending_pillar("consistency")
    assert view["pillar_mind"] == character_privacy.not_scored_pillar("mind")
    for p in character_public.VERBATIM_PILLARS:
        assert view[f"pillar_{p}"]["raw_score"] == pub[d][f"pillar_{p}"]["raw_score"]
        assert not set(character_privacy.PENDING_PILLAR_KEYS) & set(view[f"pillar_{p}"])
    assert character_privacy.public_event_sheets([{"sk": f"DATE#{d}", "date": d, "public": pub[d]}]) == []
    assert character_privacy.event_level_series([{"sk": f"DATE#{d}", "date": d, "public": pub[d]}]) == []
    live = character_privacy.public_sheet({"sk": f"DATE#{d}", "date": d, "public": pub[d]}, pending=False)
    assert live["character_level"] == pub[d]["character_level"]  # control: the switch is what withholds it


class _AskTable:
    def __init__(self, item):
        self.item = item

    def get_item(self, Key=None, **_kw):
        return {"Item": copy.deepcopy(self.item)} if str(Key.get("pk", "")).endswith("character_sheet") else {}

    def query(self, **_kw):
        return {"Items": []}


def _ask_prompt(monkeypatch, pending: bool) -> tuple:
    from web import site_api_ai_context as AC, site_api_ai_lambda as AI

    block = {
        "public_method_version": character_privacy.PUBLIC_METHOD_V1,
        "origin": "live",
        "character_level": 27,
        "character_tier": "Momentum",
        "character_xp": 219.5,
        "pillar_mind": {"level": 39, "raw_score": 59.1, "tier": "Momentum"},
        "pillar_sleep": {"level": 30, "raw_score": 71.0, "tier": "Momentum"},
    }
    from common.pacific_time import pacific_today

    d = pacific_today()
    monkeypatch.setattr(
        AI, "table", _AskTable({"pk": "USER#matthew#SOURCE#character_sheet", "sk": f"DATE#{d}", "date": d, "public": block})
    )
    monkeypatch.setattr(character_privacy, "PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE", pending)
    ctx = AC._ask_fetch_context()
    return ctx, AI._ask_build_prompt(ctx), AC._board_facts_block(ctx)


def test_the_public_ask_context_states_no_overall_level_and_no_mind_number(monkeypatch):
    """The public Ask and board contexts (#6224): no overall level/tier/XP while pending, never a Mind number, and a plain
    line the model can repeat. No model call is made."""
    import re

    ctx, prompt, facts = _ask_prompt(monkeypatch, pending=True)
    assert (
        "character_level" not in ctx
        and ctx["character_note"] == "the character scores are being recalculated; Mind is not scored in public"
    )
    for text in (prompt, facts):
        assert not re.search(r"\b27(\.0)?\b|219\.5|\b39\b|59\.1", text)
        assert "mind pillar: not scored in public" in text
        assert not re.search(r"(?i)character level: \d", text)
    assert "the character scores are being recalculated" in prompt and "the character scores are being recalculated" in facts


def test_must_fail_control_the_ask_context_states_the_level_when_scores_are_live(monkeypatch):
    ctx, prompt, facts = _ask_prompt(monkeypatch, pending=False)
    assert ctx["character_level"] == 27.0 and "level 27" in prompt and "character level: 27" in facts
    assert "59.1" not in prompt and "mind pillar: not scored in public" in prompt  # Mind is never a number
