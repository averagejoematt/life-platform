"""tests/test_hevy_adherence_wiring.py — #412 pushed-vs-performed wiring.

Covers adherence_calc.derive_adherence (routine match → compute → honest status),
the ADR-069 title-resolved cache fallback, and the pacific_date_of helper that guards
the #475/C-8 UTC-vs-Pacific off-by-one. The pure adherence math is in
test_adherence_calc.py; this file is the wiring around it."""

from __future__ import annotations

from common.pacific_time import pacific_date_of
from health import adherence_calc
from training import routine_repo
from training.routine_ir import ExerciseBlock, RoutineSpec, Set


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


# ── #4177: the MCP readback asks the SAME matcher, in reverse ───────────────────
# Fixture = the wire, read from the live table 2026-09-26 (read-only `aws dynamodb`):
# routine b1b99604… is the Lower-heavy DATED 2026-09-25 (hevy_routine_id 4b743f67…),
# PERFORMED early on 2026-09-24 as Hevy workout 3ca1117e… (which carries routine_id
# 4b743f67…). Friday 2026-09-25's workout 35882de8… is the Upper session from ANOTHER
# routine (edd83e57…, hevy 28cab4f5…). The old date-only matcher graded the Upper.
_LOWER_RID = "b1b9960468f374e30dcdeca8630dd18f"
_LOWER_HEVY = "4b743f67-df90-4eb9-bd62-9e53ac343435"
_UPPER_RID = "edd83e5731bb675eb312e0cc8f9cd1b7"
_UPPER_HEVY = "28cab4f5-f663-4597-9433-ca98dec2675a"
_LOWER_WORKOUT_ID = "3ca1117e-4e1d-4eba-bc33-7da38d2ae2ca"
_UPPER_WORKOUT_ID = "35882de8-1923-4684-98ec-5fedb8934a73"


def _sets(n, rpe=7.5):
    return [{"type": "normal", "rpe": rpe} for _ in range(n)]


def _lower_ir() -> RoutineSpec:
    # The 12-set Lower-heavy as stored (VERSION#current, v3): squat 3, RDL 3, leg press 2,
    # leg curl 2, calf 2 — `tmpl:` keys are the routine's own movement keys, verbatim.
    return RoutineSpec(
        routine_id=_LOWER_RID,
        target_date="2026-09-25",
        archetype="lower",
        hevy_routine_id=_LOWER_HEVY,
        exercises=[
            ExerciseBlock(movement_key="squat_barbell", sets=[Set(), Set(), Set()]),
            ExerciseBlock(movement_key="tmpl:2B4B7310", sets=[Set(), Set(), Set()]),
            ExerciseBlock(movement_key="tmpl:cb2d3813-d5b7-4c2e-a85e-6508c4a18d8b", sets=[Set(), Set()]),
            ExerciseBlock(movement_key="tmpl:11A123F3", sets=[Set(), Set()]),
            ExerciseBlock(movement_key="tmpl:91237BDD", sets=[Set(), Set()]),
        ],
    )


def _upper_ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id=_UPPER_RID,
        target_date="2026-09-25",
        archetype="upper",
        hevy_routine_id=_UPPER_HEVY,
        exercises=[ExerciseBlock(movement_key="tmpl:79D0BB3A", sets=[Set(), Set(), Set(), Set()])],
    )


def _lower_workout_0924() -> dict:
    # Hevy 3ca1117e… as the /v1/workouts item: `routine_id` (the Hevy id) + exercises[].
    return {
        "id": _LOWER_WORKOUT_ID,
        "title": "Foundation - Lower - 1 - 18",
        "routine_id": _LOWER_HEVY,
        "start_time": "2026-09-24T12:12:06+00:00",
        "exercises": [
            {"exercise_template_id": "D04AC939", "sets": _sets(4, 7.0)},
            {"exercise_template_id": "2B4B7310", "sets": _sets(4, 8.0)},
            {"exercise_template_id": "75A4F6C4", "sets": _sets(2, 8.0)},
            {"exercise_template_id": "cb2d3813-d5b7-4c2e-a85e-6508c4a18d8b", "sets": _sets(3, 8.0)},
            {"exercise_template_id": "91237BDD", "sets": _sets(3, 7.5)},
            {"exercise_template_id": "11A123F3", "sets": _sets(3, 8.5)},
            {"exercise_template_id": "243710DE", "sets": [{"type": "normal"}]},
            {"exercise_template_id": "527DA061", "sets": [{"type": "normal"}]},
        ],
    }


def _upper_workout_0925() -> dict:
    # Hevy 35882de8… — Friday's Upper, on the Lower routine's TARGET date, from another routine.
    return {
        "id": _UPPER_WORKOUT_ID,
        "title": "Foundation - Upper - 2 - 19",
        "routine_id": _UPPER_HEVY,
        "start_time": "2026-09-25T22:08:50+00:00",
        "exercises": [
            {"exercise_template_id": "79D0BB3A", "sets": _sets(7, 9.5)},
            {"exercise_template_id": "F1E57334", "sets": _sets(4, 9.0)},
            {"exercise_template_id": "878CD1D0", "sets": _sets(4, 7.5)},
            {"exercise_template_id": "6A6C31A5", "sets": _sets(2, 7.5)},
            {"exercise_template_id": "651F844C", "sets": _sets(3, 8.0)},
            {"exercise_template_id": "93A552C6", "sets": _sets(3, 7.5)},
            {"exercise_template_id": "37FCC2BB", "sets": _sets(4, 8.5)},
            {"exercise_template_id": "243710DE", "sets": [{"type": "normal"}]},
            {"exercise_template_id": "527DA061", "sets": [{"type": "normal"}]},
        ],
    }


def _wire_repo(monkeypatch, *, id_map=True):
    """The routine repo as the live table has it: id-map both ways, one routine per day
    except 09-25, which holds BOTH the Lower (dated 09-25, done 09-24) and the Upper."""
    irs = {_LOWER_RID: _lower_ir(), _UPPER_RID: _upper_ir()}
    hevy_to_rid = {_LOWER_HEVY: _LOWER_RID, _UPPER_HEVY: _UPPER_RID} if id_map else {}
    monkeypatch.setattr(routine_repo, "lookup_routine_id", lambda h: hevy_to_rid.get(h))
    monkeypatch.setattr(routine_repo, "get_current", lambda rid: irs.get(rid))
    monkeypatch.setattr(
        routine_repo,
        "list_by_date_range",
        lambda a, b: [irs[_LOWER_RID], irs[_UPPER_RID]] if a == b == "2026-09-25" else [],
    )
    return irs


def _newest_first():
    return [_upper_workout_0925(), _lower_workout_0924()]


def test_4177_a_routine_dated_d_performed_on_d_minus_1_resolves_to_that_workout(monkeypatch):
    """Acceptance box 1: the Lower-heavy DATED 09-25 was DONE 09-24 — find THAT workout."""
    irs = _wire_repo(monkeypatch)
    w, method = adherence_calc.find_workout_for_routine(irs[_LOWER_RID], _newest_first())
    assert w is not None and w["id"] == _LOWER_WORKOUT_ID, f"resolved to {w and w['id']}"
    assert method == "hevy_routine_id"


def test_4177_mutation_control_the_date_only_matcher_grades_the_wrong_workout(monkeypatch):
    """The pre-#4177 derivation, replayed on the same wire: it picks Friday's Upper.

    This is the negative control that shows the fixture DISCRIMINATES — the same two
    workouts, the routine's date alone, and the answer is the other routine's session.
    Restoring date-only in `action_adherence` makes the action tests below fail exactly
    this way (see the PR body for the run against origin/main's action)."""
    from common.pacific_time import pacific_date_of

    ir = _lower_ir()
    date_only = next((w for w in _newest_first() if pacific_date_of(w.get("start_time")) == ir.target_date), None)
    assert date_only is not None and date_only["id"] == _UPPER_WORKOUT_ID, "the control stopped discriminating"
    _wire_repo(monkeypatch)
    w, _ = adherence_calc.find_workout_for_routine(ir, _newest_first())
    assert w["id"] != date_only["id"]


def test_4177_action_adherence_grades_the_workout_the_routine_was(monkeypatch):
    """The REAL action on the live pair: `adherence routine_id=b1b99604…` grades Hevy 3ca1117e…
    — 12 of 12 programmed sets performed (what ingestion's row for that workout already
    says), not the 0/12 + 9 extras the Upper produced."""
    from training import hevy_write_client as wc

    from mcp.hevy_readback_report import action_adherence

    _wire_repo(monkeypatch)
    monkeypatch.setattr(wc, "get_workouts", lambda **kw: {"workouts": _newest_first()})
    graded: list[dict] = []
    real_calc = adherence_calc.calculate_adherence

    def _spy(ir, performed):
        graded.append(performed)
        return real_calc(ir, performed)

    monkeypatch.setattr(adherence_calc, "calculate_adherence", _spy)

    out = action_adherence({"routine_id": _LOWER_RID})
    assert out["status"] == "ok", out
    assert out["workout_id"] == _LOWER_WORKOUT_ID
    assert out["match_method"] == "hevy_routine_id"
    assert out["workout_pacific_date"] == "2026-09-24" and out["target_date"] == "2026-09-25"
    assert [g["id"] for g in graded] == [_LOWER_WORKOUT_ID], "a different routine's session was graded"
    sets = out["adherence"]["sets_adherence"]
    assert sets["programmed_sets"] == 12
    assert sets["performed_sets"] == 12, out["adherence"]
    assert out["adherence"]["missing"] == []


def test_4177_no_match_is_a_named_absence_never_another_routines_session(monkeypatch):
    """Acceptance box 2: only Friday's Upper is in the window (the Lower workout not yet
    ingested / paged out). It shares the Lower routine's TARGET DATE — and it is NOT graded."""
    from training import hevy_write_client as wc

    from mcp.hevy_readback_report import action_adherence

    _wire_repo(monkeypatch)
    monkeypatch.setattr(wc, "get_workouts", lambda **kw: {"workouts": [_upper_workout_0925()]})
    monkeypatch.setattr(
        adherence_calc, "calculate_adherence", lambda ir, w: (_ for _ in ()).throw(AssertionError("graded a stranger's session"))
    )

    out = action_adherence({"routine_id": _LOWER_RID})
    assert out["status"] == "no_workout_for_routine", out
    assert out["routine_id"] == _LOWER_RID and out["target_date"] == "2026-09-25"
    assert out["hevy_routine_id"] == _LOWER_HEVY
    assert out["workouts_searched"] == 1
    assert "adherence" not in out


def test_4177_no_match_when_the_window_is_empty(monkeypatch):
    from training import hevy_write_client as wc

    from mcp.hevy_readback_report import action_adherence

    _wire_repo(monkeypatch)
    monkeypatch.setattr(wc, "get_workouts", lambda **kw: {"workouts": []})
    out = action_adherence({"routine_id": _LOWER_RID})
    assert out["status"] == "no_workout_for_routine" and out["workouts_searched"] == 0


def test_4177_without_an_id_link_the_date_and_overlap_steps_still_run_in_order(monkeypatch):
    """The same three steps as ingestion, reversed: strip the id-map and the Lower workout
    still resolves — by overlap, since 09-25 holds two routines — while the Upper on the
    same day resolves to the Upper routine, so it is never the Lower's answer."""
    irs = _wire_repo(monkeypatch, id_map=False)
    lower_0924 = dict(_lower_workout_0924(), start_time="2026-09-25T12:12:06+00:00")  # put it ON the date
    w, method = adherence_calc.find_workout_for_routine(irs[_LOWER_RID], [_upper_workout_0925(), lower_0924])
    assert w["id"] == _LOWER_WORKOUT_ID and method == "date_overlap"
    w, method = adherence_calc.find_workout_for_routine(irs[_UPPER_RID], [_upper_workout_0925(), lower_0924])
    assert w["id"] == _UPPER_WORKOUT_ID and method == "date_overlap"


def test_4177_ingestion_and_readback_share_one_matcher():
    """Structural: `derive_adherence` no longer carries its own id/date/overlap block, and
    the readback module has no private matcher — both go through `resolve_routine_for_workout`."""
    import ast
    import inspect
    import pathlib

    src = inspect.getsource(adherence_calc.derive_adherence)
    assert "resolve_routine_for_workout(" in src
    assert "lookup_routine_id" not in src and "list_by_date_range" not in src
    readback = pathlib.Path(adherence_calc.__file__).resolve().parents[2] / "mcp" / "hevy_readback_report.py"
    tree = ast.parse(readback.read_text(encoding="utf-8"))
    action = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "action_adherence")
    calls = {getattr(c.func, "id", getattr(c.func, "attr", None)) for c in ast.walk(action) if isinstance(c, ast.Call)}
    assert "find_workout_for_routine" in calls
    compares = [n for n in ast.walk(action) if isinstance(n, ast.Compare)]
    for cmp in compares:
        for side in (cmp.left, *cmp.comparators):
            assert not (isinstance(side, ast.Attribute) and side.attr == "target_date"), "a date-only matcher regrew in action_adherence"
