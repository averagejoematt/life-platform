"""tests/test_restraint_public_figures_6224.py — no public output moves with a restraint habit (#6224).

Owner ruling 2026-11-24: restraint habits are private — no names, streaks or counts, and no figure from which their
count or behaviour can be derived, unless an owner approval is on record (``RESTRAINT_DATA_PUBLISHED`` is False). Two
live exposures survived the first pass (#6262), both reproduced here on synthetic fixtures and both now held:

  1. the PUBLIC character variant took the restraint streaks: a cross-pillar effect whose condition reads them was
     evaluated and served by name, and Mind scored a restraint component and named it as a driver;
  2. the tier-0 figures (``/api/habit_streaks``, ``public_stats.json``'s streak and habits line, the og cards drawn from
     it, the achievements' streak badges, the public Ask context) were the stored counts and run, which count every
     tier-0 habit, restraint habits among them.

The strongest form is invariance: the public output is identical whether the restraint streak is 0 or 90 and
whether the restraint habits were kept or not. Each invariance has a must-fail control (the switch an owner approval
would flip), so the check is shown to see what it guards.

Names are synthetic throughout ("restraint_a" …); the route walk's canaries are tests/restraint_route_walk.py's.
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
from common import (
    activity_publication as AP,  # noqa: E402
    restraint_publication as RP,  # noqa: E402
)
from health import character_engine, character_privacy, character_public  # noqa: E402

CONFIG = json.load(open(ROOT / "config" / "character_sheet.json", encoding="utf-8"))
GENESIS = "2026-09-06"
N_DAYS = 40  # past the any_vice_streak > 30 threshold, so the restraint effect really fires in method 1
RESTRAINT = "restraint_a"
ORDINARY = "ordinary_a"


# ── 1. the character sheet's public variant ───────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _scores_live_6224(monkeypatch):
    """#6224: this file tests the SCORED public serving — the state after a verified recompute flips
    ``PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE`` off. The pending state is tests/test_public_mind_unscored_6224.py's."""
    from health import character_privacy as _cp

    monkeypatch.setattr(_cp, "PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE", False)


def _days(n=N_DAYS):
    return [(date.fromisoformat(GENESIS) + timedelta(days=i)).isoformat() for i in range(n)]


def _inputs(i: int, d: str, streak: float) -> dict:
    """One day's public inputs (identical in both histories) plus the restraint streak (the ONLY difference)."""
    return {
        "date": d,
        "sleep": {"sleep_duration_hours": 6.0 + (i % 5) * 0.5, "sleep_efficiency_percentage": 80 + (i % 7) * 2},
        "habit_scores": {
            "scoring_method": "core_set_v1",
            "core_pct": round(0.4 + (i % 6) * 0.1, 3),
            "date": d,
            "computed_at": f"{(date.fromisoformat(d) + timedelta(days=1)).isoformat()}T17:40:10+00:00",
            "input_manifest": {"sources": {"habitify": {"latest_day": d}}},
        },
        "vice_streaks": {RESTRAINT: float(streak)},
        "reading_session_days_7d": [d] * (i % 4),
        "data_completeness_pct": 60.0 + (i % 3) * 20,
        "todoist": {"overdue_count": float(i % 5)},
        "engagement_state": {
            "presence_class": "present",
            "gap_days": 0,
            "planned_pause": False,
            "public": {"presence_class": "present", "gap_days": 0, "planned_pause": False},
        },
    }


def _history(streak_of) -> tuple:
    """(method-1 records, habit_scores) the live compute would have stored, with the restraint streak ``streak_of(i)``."""
    records, scores = {}, {}
    for i, d in enumerate(_days()):
        data = _inputs(i, d, streak_of(i))
        hist = B.window_records(records, d)
        data.update(character_engine.derive_consistency_inputs(hist, d))
        rec = character_engine.compute_character_sheet(data, B.previous_record(records, d), B.raw_histories(hist), CONFIG)
        rec.pop("progression_transitions", None)
        rec["sk"] = f"DATE#{d}"
        records[d] = B.as_stored(rec)
        scores[d] = dict(data["habit_scores"], vice_streaks=data["vice_streaks"])
    return records, scores


def _replay(records, scores) -> dict:
    engagement = {d: _inputs(0, d, 0)["engagement_state"] for d in records}
    out = B.replay_character(records, engagement, scores, CONFIG, "2026-11-25T00:00:00+00:00")
    return {d: r["public"] for d, r in out.items()}


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


@pytest.fixture(scope="module")
def histories():
    zero = _history(lambda _i: 0)
    ninety = _history(lambda i: 90 + i)  # a held streak far past the effect's threshold on every day
    return zero, ninety, _replay(*zero), _replay(*ninety)


def test_method1_really_moves_with_the_restraint_streak(histories):
    """The control that the private input is really there: method 1 fires the restraint effect and scores the
    component differently between the two histories."""
    (zero, _), (ninety, _), _, _ = histories
    last = _days()[-1]
    names0 = {e["name"] for e in zero[last].get("active_effects") or []}
    names90 = {e["name"] for e in ninety[last].get("active_effects") or []}
    restraint_effects = {e["name"] for e in CONFIG["cross_pillar_effects"] if character_privacy.effect_reads_restraint(e)}
    assert restraint_effects and restraint_effects <= names90 and not (restraint_effects & names0)
    m0 = zero[last]["pillar_mind"]["components"]["vice_control"]["score"]
    m90 = ninety[last]["pillar_mind"]["components"]["vice_control"]["score"]
    assert m0 != m90


def test_the_public_variant_is_identical_whatever_the_restraint_streak(histories):
    """Every public block of the replayed history — score, level, XP, effects, drivers — is byte-identical."""
    _, _, pub0, pub90 = histories
    assert list(pub0) == list(pub90)
    moved = [d for d in pub0 if _canon(pub0[d]) != _canon(pub90[d])]
    assert moved == [], f"public character variant moved with the restraint streak on {moved}"


def test_the_public_variant_names_no_restraint_input(histories):
    _, _, pub0, pub90 = histories
    for pub in (pub0, pub90):
        for d, block in pub.items():
            assert not [e for e in block.get("active_effects") or [] if character_privacy.effect_reads_restraint(e)], d
            mind = block.get("pillar_mind") or {}
            assert "vice_control" not in (mind.get("components") or {}), d
            assert not any("vice_control" in (v or []) for v in (mind.get("drivers") or {}).values()), d


def test_must_fail_control_with_the_switch_on_the_public_variant_moves(histories, monkeypatch):
    """With ``RESTRAINT_DATA_PUBLISHED`` on (what an owner approval would do) the same replay DOES move — the
    invariance above is the hold, not a fixture that never carried the input."""
    (zero, s0), (ninety, s90), _, _ = histories
    monkeypatch.setattr(RP, "RESTRAINT_DATA_PUBLISHED", True)
    a, b = _replay(zero, s0), _replay(ninety, s90)
    assert any(_canon(a[d]) != _canon(b[d]) for d in a)


def test_public_config_holds_restraint_effects_and_components_out():
    cfg = character_public.public_config(CONFIG)
    assert not [e for e in cfg["cross_pillar_effects"] if character_privacy.effect_reads_restraint(e)]
    assert "vice_control" not in cfg["pillars"]["mind"]["components"]
    assert len(cfg["cross_pillar_effects"]) == len(CONFIG["cross_pillar_effects"]) - sum(
        1 for e in CONFIG["cross_pillar_effects"] if character_privacy.effect_reads_restraint(e)
    )
    assert not character_privacy.component_is_publishable("vice_control")


def _stored_pre_6224_variant() -> dict:
    """A stored public variant computed BEFORE #6224 (it carries the restraint names), as the table holds it now."""
    pv = {
        "public_method_version": character_privacy.PUBLIC_METHOD_VERSION,
        "origin": "live",
        "character_level": 5,
        "active_effects": [
            {"name": "Restraint Effect Canary", "condition": "any_vice_streak > 30", "targets": {}},
            {"name": "Ordinary Effect", "condition": "sleep > 70", "targets": {}},
        ],
        "pillar_mind": {
            "raw_score": 60.0,
            "components": {"vice_control": {"score": 100.0, "weight": 0.1}, "t0_habit_compliance": {"score": 50.0, "weight": 0.3}},
            "drivers": {"top": ["t0_habit_compliance", "vice_control"], "dragging": [], "absent": [], "no_data": []},
            "absent_behaviors": [],
        },
        "level_events": [{"pillar": "mind", "top_driver": "Vice Control", "top_driver_value": 100.0}],
    }
    return {"sk": "DATE#2026-11-20", "date": "2026-11-20", "public": pv}


def test_a_stored_pre_6224_variant_is_served_without_any_restraint_name():
    record = _stored_pre_6224_variant()
    before = copy.deepcopy(record)
    view = character_privacy.public_sheet(record)
    assert [e["name"] for e in view["active_effects"]] == ["Ordinary Effect"]
    # since Mind is not scored in public (owner rulings 2026-11-26) its block, drivers and events are gone entirely
    assert view["pillar_mind"] == character_privacy.not_scored_pillar("mind")
    assert view["level_events"] == []
    assert record == before, "the scrub must not mutate the stored record it was handed"


def test_must_fail_control_the_scrub_keys_off_the_switch(monkeypatch):
    monkeypatch.setattr(RP, "RESTRAINT_DATA_PUBLISHED", True)
    view = character_privacy.public_sheet(_stored_pre_6224_variant())
    assert "Restraint Effect Canary" in [e["name"] for e in view["active_effects"]]


# ── 2. the public tier-0 figures: one predicate ───────────────────────────────────────────

REGISTRY = {
    ORDINARY: {"status": "active", "tier": 0},
    "ordinary_b": {"status": "active", "tier": 0},
    RESTRAINT: {"status": "active", "tier": 0},  # a restraint by its tracker group below
    "restraint_b": {"status": "active", "tier": 0, "vice": True},  # a restraint by the registry flag
    "restraint_c": {"status": "active", "tier": 0},  # a restraint by a stored streak key only
}
_PUBLIC_IDS = sorted(AP.PUBLIC_HABIT_IDS)


def _statuses(restraint_done: bool, ordinary_done: bool = True) -> dict:
    def st(i, group, done):
        return {"status": "completed" if done else "failed", "habit_id": _PUBLIC_IDS[i], "group": group, "scheduled_today": True}

    return {
        ORDINARY: st(0, "Core", ordinary_done),
        "ordinary_b": st(1, "Core", True),
        RESTRAINT: st(2, "Vice", restraint_done),
        "restraint_b": st(3, "Core", restraint_done),
        "restraint_c": st(4, "Core", restraint_done),
    }


def test_public_tier0_counts_are_identical_whether_the_restraint_habits_were_kept():
    kept = AP.public_tier0_counts(_statuses(True), REGISTRY, {"restraint_c"})
    missed = AP.public_tier0_counts(_statuses(False), REGISTRY, {"restraint_c"})
    assert kept == missed == (2, 2)


def test_must_fail_control_the_counts_see_an_ordinary_habit_and_the_switch(monkeypatch):
    """Non-vacuous twice over: an ordinary habit's miss moves the count, and with the switch on the restraint
    habits are counted (so the invariance above is the hold, not an empty predicate)."""
    assert AP.public_tier0_counts(_statuses(True, ordinary_done=False), REGISTRY, {"restraint_c"}) == (1, 2)
    monkeypatch.setattr(RP, "RESTRAINT_DATA_PUBLISHED", True)
    assert AP.public_tier0_counts(_statuses(True), REGISTRY, {"restraint_c"}) == (5, 5)
    assert AP.public_tier0_counts(_statuses(False), REGISTRY, {"restraint_c"}) == (2, 5)


def test_the_public_run_is_perfect_public_days_only():
    assert AP.public_tier0_streak([(2, 2), (2, 2), (1, 2), (2, 2)]) == 2
    assert AP.public_tier0_streak([(0, 0), (2, 2)]) == 0  # a day with no public tier-0 habit ends the run


class _Table:
    """A Query-only fake (the stats refresh's role grants nothing else): partition, sort-key range, order, Limit."""

    def __init__(self, rows):
        self.rows = rows

    def query(self, KeyConditionExpression=None, ScanIndexForward=True, Limit=None, **_kw):
        expr = KeyConditionExpression.get_expression()
        parts = expr["values"] if expr["operator"] == "AND" else [KeyConditionExpression]
        pk = sk_eq = sk_range = None
        for p in parts:
            e = p.get_expression()
            name, vals = e["values"][0].name, e["values"][1:]
            if name == "pk":
                pk = vals[0]
            elif e["operator"] == "=":
                sk_eq = vals[0]
            else:
                sk_range = (vals[0], vals[1])
        items = [r for r in self.rows if r["pk"] == pk]
        if sk_eq is not None:
            items = [r for r in items if r["sk"] == sk_eq]
        if sk_range is not None:
            items = [r for r in items if sk_range[0] <= r["sk"] <= sk_range[1]]
        items.sort(key=lambda r: r["sk"], reverse=not ScanIndexForward)
        return {"Items": items[: int(Limit)] if Limit else items}

    def get_item(self, **_kw):  # pragma: no cover — the summary must not need it
        raise AssertionError("public_tier0_summary must read through Query only")


def _summary(restraint_done: bool, streak: int) -> dict:
    from web import site_api_habits

    U = "USER#matthew"
    days = [(date(2026, 11, 20) - timedelta(days=i)).isoformat() for i in range(5)]
    rows = [{"pk": U, "sk": "PROFILE#v1", "habit_registry": copy.deepcopy(REGISTRY)}]
    rows += [{"pk": f"{U}#SOURCE#habitify", "sk": f"DATE#{d}", "date": d, "habit_statuses": _statuses(restraint_done)} for d in days]
    rows.append({"pk": f"{U}#SOURCE#habit_scores", "sk": f"DATE#{days[0]}", "vice_streaks": {"restraint_c": streak}})
    return site_api_habits.public_tier0_summary(_Table(rows), days[0], days[-1])


def test_the_public_tier0_summary_is_identical_across_the_restraint_state():
    low, high = _summary(False, 0), _summary(True, 90)
    assert low == high == {"as_of_date": "2026-11-20", "done": 2, "total": 2, "pct": 100, "streak": 5}


def test_the_public_habits_line_reads_the_public_figures():
    from web import site_api_habits

    assert site_api_habits.public_tier0_narrative({"streak": 5, "total": 2, "pct": 100}) == "Tier 0 streak: 5 days — 100% completion today."
    assert site_api_habits.public_tier0_narrative({"streak": 0, "total": 0, "pct": 0}) == "Tier 0 streak: 0 days."
    assert site_api_habits.public_tier0_narrative(None) is None


# ── 3. every public route, across the two restraint states ────────────────────────────────


def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "restraint_route_walk.py"), *args],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def walks() -> dict:
    """Four walks at ONE frozen instant: the two restraint states, gated and with the switch on (the control)."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    runs = {
        ("gated", "low"): ("--state", "low", "--now", now),
        ("gated", "high"): ("--state", "high", "--now", now),
        # #6224: the control also turns the containment switch off, or no restraint-derived character value is served
        ("published", "low"): ("--state", "low", "--now", now, "--published", "--scores-live"),
        ("published", "high"): ("--state", "high", "--now", now, "--published", "--scores-live"),
    }
    with ThreadPoolExecutor(max_workers=int(os.environ.get("RESTRAINT_WALK_WORKERS", "4"))) as pool:
        futures = {k: pool.submit(_walk, *a) for k, a in runs.items()}
        return {k: f.result() for k, f in futures.items()}


def _moved(walks, mode) -> list:
    a, b = walks[(mode, "low")]["all_bodies"], walks[(mode, "high")]["all_bodies"]
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def test_the_invariance_walk_reaches_every_route(walks):
    for k, out in walks.items():
        assert out["answered"] >= 140 and out["raised"] == {} and out["unparsed_queries"] == 0, (k, out["answered"], out["raised"])


def test_no_public_route_moves_with_the_restraint_habits(walks):
    """Every public GET route's whole body is identical whether every restraint habit was kept with a 90-day streak or
    missed with none — the tier-0 routes, the achievements' streak badges and the character routes included."""
    assert _moved(walks, "gated") == [], "public routes whose body moves with the restraint habits alone"


def test_no_public_route_names_a_restraint_derived_character_input(walks):
    for state in ("low", "high"):
        assert walks[("gated", state)]["leaks"] == {}, walks[("gated", state)]["leaks"]


def test_must_fail_control_with_the_switch_on_the_walk_sees_both_exposures(walks):
    """The walk is not blind: with ``RESTRAINT_DATA_PUBLISHED`` on, the tier-0 routes move with the restraint state and
    the stored variant's restraint names reach /api/character — the two exposures #6224 closed."""
    moved = set(_moved(walks, "published"))
    assert {"/api/habit_streaks", "/api/habits"} <= moved, moved
    for state in ("low", "high"):
        assert "/api/character" in walks[("published", state)]["leaks"], walks[("published", state)]["leaks"]
