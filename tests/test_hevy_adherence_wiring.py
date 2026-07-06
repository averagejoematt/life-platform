"""tests/test_hevy_adherence_wiring.py — #412 pushed-vs-performed wiring.

Covers adherence_calc.derive_adherence (routine match → compute → honest status),
the ADR-069 title-resolved cache fallback, and the pacific_date_of helper that guards
the #475/C-8 UTC-vs-Pacific off-by-one. The pure adherence math is in
test_adherence_calc.py; this file is the wiring around it."""

from __future__ import annotations

import adherence_calc
import routine_repo
from pacific_time import pacific_date_of
from routine_ir import ExerciseBlock, RoutineSpec, Set


def _ir(routine_id="r-1", date="2026-06-01", movements=("db_bench_press_flat", "lat_pulldown")) -> RoutineSpec:
    return RoutineSpec(
        routine_id=routine_id,
        target_date=date,
        archetype="upper",
        exercises=[ExerciseBlock(movement_key=m, sets=[Set(), Set(), Set()]) for m in movements],
    )


# Real Hevy template ids for db_bench_press_flat / lat_pulldown (live reconciled catalog).
_FULL_EXERCISES = [
    {"exercise_template_id": "3601968B", "sets": [{}, {}, {}]},
    {"exercise_template_id": "6A6C31A5", "sets": [{}, {}, {}]},
]


def _performed(routine_id="hevy-123", start="2026-06-01T18:00:00Z", exercises=None):
    return {"routine_id": routine_id, "start_time": start, "exercises": exercises if exercises is not None else _FULL_EXERCISES}


# ── pacific_date_of (the off-by-one guard) ──────────────────────────────────
def test_pacific_date_of_rolls_utc_evening_back_a_day():
    # 04:00 UTC on Jun 2 is 21:00 PDT on Jun 1 — the workout belongs to the Pacific day.
    assert pacific_date_of("2026-06-02T04:00:00Z") == "2026-06-01"


def test_pacific_date_of_bad_input_is_none():
    assert pacific_date_of("") is None
    assert pacific_date_of("not-a-date") is None


# ── exact match via the Hevy routine id (immune to the date bug) ────────────
def test_exact_hevy_routine_id_match(monkeypatch):
    monkeypatch.setattr(routine_repo, "lookup_routine_id", lambda h: "r-1" if h == "hevy-123" else None)
    monkeypatch.setattr(routine_repo, "get_current", lambda rid: _ir() if rid == "r-1" else None)
    # date fallback must NOT be consulted on the exact path
    monkeypatch.setattr(routine_repo, "list_by_date_range", lambda a, b: (_ for _ in ()).throw(AssertionError("date path used")))
    adh = adherence_calc.derive_adherence(_performed())
    assert adh["status"] == "matched"
    assert adh["match_method"] == "hevy_routine_id"
    assert adh["matched_routine_id"] == "r-1"
    assert adh["overall_pct"] == 100.0
    assert adh["routine_target_date"] == "2026-06-01"


# ── ad-hoc: no plan pushed → no fabricated number ───────────────────────────
def test_ad_hoc_when_no_routine(monkeypatch):
    monkeypatch.setattr(routine_repo, "lookup_routine_id", lambda h: None)
    monkeypatch.setattr(routine_repo, "list_by_date_range", lambda a, b: [])
    adh = adherence_calc.derive_adherence(_performed(routine_id=""))
    assert adh["status"] == "ad_hoc"
    assert adh["matched_routine_id"] is None
    assert "overall_pct" not in adh  # ADR-104: never a fabricated 0
    assert "movements" not in adh


# ── date fallback, single routine ───────────────────────────────────────────
def test_date_single_fallback(monkeypatch):
    monkeypatch.setattr(routine_repo, "lookup_routine_id", lambda h: None)
    seen = {}

    def _range(a, b):
        seen["args"] = (a, b)
        return [_ir()]

    monkeypatch.setattr(routine_repo, "list_by_date_range", _range)
    adh = adherence_calc.derive_adherence(_performed(routine_id=""))
    assert adh["status"] == "matched"
    assert adh["match_method"] == "date_single"
    # looked up by the PACIFIC day (18:00Z Jun 1 = 11:00 PDT Jun 1)
    assert seen["args"] == ("2026-06-01", "2026-06-01")


def test_date_fallback_uses_pacific_day_not_utc(monkeypatch):
    # 03:00 UTC Jun 2 = 20:00 PDT Jun 1 — must look up Jun 1, the routine's target_date.
    monkeypatch.setattr(routine_repo, "lookup_routine_id", lambda h: None)
    seen = {}
    monkeypatch.setattr(
        routine_repo, "list_by_date_range", lambda a, b: seen.setdefault("args", (a, b)) and None or [_ir(date="2026-06-01")]
    )
    adh = adherence_calc.derive_adherence(_performed(routine_id="", start="2026-06-02T03:00:00Z"))
    assert seen["args"] == ("2026-06-01", "2026-06-01")
    assert adh["status"] == "matched"


# ── ambiguous: several plans, none matches confidently → say so ─────────────
def test_ambiguous_when_no_overlap(monkeypatch):
    monkeypatch.setattr(routine_repo, "lookup_routine_id", lambda h: None)
    # two candidates whose movements don't overlap the performed template ids at all
    cands = [_ir(routine_id="r-a", movements=("leg_press",)), _ir(routine_id="r-b", movements=("machine_row",))]
    monkeypatch.setattr(routine_repo, "list_by_date_range", lambda a, b: cands)
    adh = adherence_calc.derive_adherence(_performed(routine_id=""))
    assert adh["status"] == "ambiguous"
    assert adh["matched_routine_id"] is None
    assert set(adh["candidate_routine_ids"]) == {"r-a", "r-b"}
    assert "overall_pct" not in adh


def test_overlap_picks_best_candidate(monkeypatch):
    monkeypatch.setattr(routine_repo, "lookup_routine_id", lambda h: None)
    # r-a matches both performed ids; r-b matches none
    cands = [_ir(routine_id="r-a", movements=("db_bench_press_flat", "lat_pulldown")), _ir(routine_id="r-b", movements=("leg_press",))]
    monkeypatch.setattr(routine_repo, "list_by_date_range", lambda a, b: cands)
    adh = adherence_calc.derive_adherence(_performed(routine_id=""))
    assert adh["status"] == "matched"
    assert adh["match_method"] == "date_overlap"
    assert adh["matched_routine_id"] == "r-a"


# ── a derive error must never break ingestion ───────────────────────────────
def test_derive_failure_is_non_fatal(monkeypatch):
    def _boom(_h):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(routine_repo, "lookup_routine_id", _boom)
    assert adherence_calc.derive_adherence(_performed()) is None


# ── ADR-069 "tmpl:<id>" movement keys carry the template id in the suffix ───────
def test_tmpl_prefixed_movement_key_resolves_directly(monkeypatch):
    # A routine can program an exercise by raw template ("tmpl:<id>") rather than a
    # catalog movement. It must count as PERFORMED when the workout has that template id
    # — else adherence is deflated (the real 2026-06-25 workout regression).
    monkeypatch.setattr(adherence_calc, "_load_catalog", lambda: {"movements": {}})
    monkeypatch.setattr(adherence_calc, "_load_template_cache", lambda: {})
    ir = _ir(movements=("tmpl:BE640BA0", "tmpl:54508215-4069-4f0b-bd2a-718dc159e1e1"))
    performed = {
        "exercises": [
            {"exercise_template_id": "BE640BA0", "sets": [{}, {}, {}]},
            {"exercise_template_id": "54508215-4069-4f0b-bd2a-718dc159e1e1", "sets": [{}, {}, {}]},
        ]
    }
    result = adherence_calc.calculate_adherence(ir, performed)
    assert result["overall_pct"] == 100.0
    assert result["missing"] == []


# ── ADR-069 title-resolved movement resolves via the cache, not a catalog hint ─
def test_title_resolved_movement_uses_cache(monkeypatch):
    # reverse_pec_deck has NO catalog hint (ADR-069) — its id lives in the resolved cache.
    monkeypatch.setattr(adherence_calc, "_load_catalog", lambda: {"movements": {"reverse_pec_deck": {"primary_muscle": "shoulders"}}})
    monkeypatch.setattr(
        adherence_calc, "_load_template_cache", lambda: {"movements": {"reverse_pec_deck": {"hevy_template_id": "D8281C62"}}}
    )
    ir = _ir(movements=("reverse_pec_deck",))
    performed = {"exercises": [{"exercise_template_id": "D8281C62", "sets": [{}, {}, {}]}]}
    result = adherence_calc.calculate_adherence(ir, performed)
    assert result["overall_pct"] == 100.0
    assert result["missing"] == []
