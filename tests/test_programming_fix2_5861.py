"""#5861 second red team (2026-11-13) — the PROGRAMMING fixes, gated on the generated weeks and on realistic histories.

A second independent red team graded the integrated engine's generated weeks C+. Its findings on the owner's real-data run
could not be reproduced by the flat synthetic fixtures (100 lb for every accessory, one exposure each), so the fixtures here
are SHAPED like that run — several exposures per lift, logged RPE and rep counts, a dumbbell jump that makes e1RM noisy, a
lift performed earlier in the same week, a shadow-era rotation ledger carried into the phase — and every number is invented
(no person's loads). Each gate has a MUST-FAIL CONTROL run in the same test (the guarded behaviour patched out -> red).

  1. the kettlebell slot names its implement, caps effort at RPE 7-8, loads the bell he swings, counts toward glutes/hamstrings
  2. stacking never displaces the session's only squat to protect the pinned third hinge (also acceptance d2b)
  3. cardio: room under the shared cap (acceptance d3b), week-to-week progression, hard -> easy on a bad day, the stop line
  4. a load cut on an isolation / machine lift needs effort evidence; one cut per lift per week
  5. the novelty budget covers every movement the served week changes, ledger-carried ones included
  6. coverage: a vertical pull in the garage week, a new movement never starts at 4-6, the press-sets option
  7. the behind-schedule week (off by default)

Live mode = an IN-MEMORY approved copy of the library (the committed file stays `proposed`; acceptance e3 holds that).
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
from collections import Counter
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "scripts", REPO / "lambdas" / "operational"):
    sys.path.insert(0, str(_p))

import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    fatigue_model as fm,
    live_program as lp,
    live_rules as lrules,
    live_week as lw,
    selection_engine as se,
    selection_live as sl,
)

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
LANDMARKS = json.loads((REPO / "config" / "training_landmarks.json").read_text())
PROFILES = sw.load_profiles()
KG = 0.45359237


def _lib() -> dict:
    lib = copy.deepcopy(LIB0)
    lib["status"] = "approved"
    return lib


def _week(name: str, patches: dict | None = None, settings: dict | None = None) -> dict:
    """One profile's week drafted live, with `patches` ({(module, attr): value}) and in-memory library settings."""
    prof = PROFILES[name]
    with patch.dict(sw.SETTINGS, settings or {}):
        world = sw.build_world(prof, "approved")
        ps = [patch.object(m, a, v) for (m, a), v in (patches or {}).items()]
        for p in ps:
            p.start()
        try:
            week = sw.generate_week(prof, "approved", world)
        finally:
            for p in ps:
                p.stop()
    return {"world": world, "week": week, "m": sw.measure(week, world["lib"], world["catalog"]["movements"], LANDMARKS)}


def _lift(week: dict, role: str, key: str) -> dict | None:
    s = next(s for s in week["sessions"] if s["role"] == role)
    return next((x for x in s["lifts"] if x["key"] == key), None)


def _ex(tid: str, sets: list[tuple[float, int, float | None]]) -> dict:
    return {"template_id": tid, "sets": [{"type": "normal", "weight_kg": round(lb * KG, 3), "reps": r, "rpe": rpe} for lb, r, rpe in sets]}


@pytest.fixture(scope="module")
def weeks() -> dict:
    return {
        n: _week(n)
        for n in ("a_large_deficit_experienced", "b_shoulder_flag_low_recovery", "c_equipment_limited", "f_high_fatigue_poor_sleep")
    }


# ── 1. the kettlebell slot ────────────────────────────────────────────────────
def test_the_kettlebell_slot_names_its_implement_caps_effort_and_loads_the_bell(weeks):
    """The KB deadlift logs as Hevy's "Sumo Deadlift" (an owner-ruled stand-in): the note must name the kettlebell, cap the
    effort at RPE 7-8 (an entry drill — 7 when it is also the session's third hinge), and carry the bell he swings instead of
    "find the load". Control: the KB rules off -> no implement on the note and the load to find."""
    # FIX3 (third red team): the slot moves off lower volume (two spine-loading lifts already) to shoulders+arms by default
    # #5861 FIX5: the KB deadlift is served only to a lifter who does not deadlift a barbell (else it is filler: KB_FILLER)
    # #5861 FIX6: under the ruled shared cap the slot passes over the conditioning host — this test holds the default-cap placement
    nodl = _week(
        "a_large_deficit_experienced", {(lrules, "deadlifts"): lambda workouts, ctx: False}, {"session_cap_includes_cardio": False}
    )
    kb = _lift(nodl["week"], "shoulders_arms", "kettlebell_deadlift")
    assert kb is not None and kb["title"] == "Sumo Deadlift"
    note = kb["hevy_note"]
    assert lw.KB_SLOT["implement_line"]["value"] in note.split("\n")
    assert note.startswith(("RPE 7\n", "RPE 7–8\n")) and "9–10" not in note and "find the load" not in note
    off = _week(
        "a_large_deficit_experienced",
        {(lw, "kb_slot"): lambda rx, ctx: [], (lw, "kb_seed"): lambda *a, **k: None, (lrules, "deadlifts"): lambda workouts, ctx: False},
        {"session_cap_includes_cardio": False},
    )
    bare = _lift(off["week"], "shoulders_arms", "kettlebell_deadlift")["hevy_note"]
    assert lw.KB_SLOT["implement_line"]["value"] not in bare and "find the load" in bare


def test_the_kettlebell_slot_loads_only_a_bell_on_file_and_counts_toward_glutes_and_hamstrings():
    """`kb_seed` takes the entry's own last load, else the swing's; with neither on file the load is genuinely unknown and the
    rows stay empty. Its sets count toward glutes (and hamstrings at the secondary credit), never `other`."""
    from training.routine_ir import ExerciseBlock, Set

    rx = {"exposures": [{"movement_key": "kettlebell_deadlift", "live_kb": True}]}

    def block():
        return ExerciseBlock(movement_key="kettlebell_deadlift", sets=[Set(type="normal", rep_range_start=6, rep_range_end=8)] * 2)

    swing = {"F8A0FCCA": [{"date": "2026-11-02", "sets": [{"weight_kg": 24.0, "reps": 10, "rpe": 7}]}]}
    b, lines = block(), []
    lw.kb_seed([b], rx, swing, CAT0, "2026-11-20", lines)
    assert all(abs(float(s.weight_kg) - 24.0) < 0.1 for s in b.sets) and lines
    b2 = block()
    lw.kb_seed([b2], rx, {}, CAT0, "2026-11-20", [])
    assert all(getattr(s, "weight_kg", None) is None for s in b2.sets)  # control: nothing on file -> nothing invented
    assert CAT0["kettlebell_deadlift"]["primary_muscle"] == "other"
    assert lw.landmark_muscle("kettlebell_deadlift", CAT0, LIB0) == "glutes"
    week = {"sessions": [{"lifts": [{"key": "kettlebell_deadlift", "working_sets": 2}]}]}
    sets = sw.sets_by_muscle(week, LIB0, CAT0)
    assert sets.get("glutes") == 2 and sets.get("hamstrings") == 1.0
    assert lw.landmark_muscle("kettlebell_deadlift", CAT0, None) == "other"  # control: the catalog alone hides the sets
    # the engine's own weekly count (fatigue_model, read by the live fatigue model and the cron's 7-day volume) credits the
    # KB slot's logged sets through the library (template D20D7BBE), never the catalog's `other`; the catalog stays as ruled
    rec = [{"date": "2026-11-12", "exercises": [_ex("D20D7BBE", [(35, 8, 7.0), (35, 8, 7.0)])]}]
    hard = fm.hard_sets_by_muscle(rec, fm.library_index(LIB0), as_of="2026-11-13")
    assert hard.get("glutes") == 2 and hard.get("hamstrings") == 1.0 and "other" not in hard and "unplaced" not in hard
    assert fm.hard_sets_by_muscle(rec, {}, as_of="2026-11-13") == {"unplaced": 2.0}  # control: no library -> not placed


def test_a_reviewed_rating_ranks_ahead_of_a_provisional_one_at_an_equal_tier():
    """Rubric 3.2.0 (FIX2-DATA): unreviewed ratings carry `provisional: true`. Inside the live rank, at an equal tier and fit,
    the reviewed row wins. Control: with the flag ignored the order falls to the next key (variety / the movement id)."""
    base = {"tier": "A", "n1": {"score": 0}, "fatigue_cost": 1, "novel": False, "exposures": 0, "evidence": None}
    rev = base | {"catalog_key": "z_reviewed", "movement_id": "z_reviewed", "provisional": False}
    prov = base | {"catalog_key": "a_provisional", "movement_id": "a_provisional", "provisional": True}
    ranked = sorted([prov, rev], key=lambda c: sl.rank_key(c, set(), {}, ("S", "A")))
    assert ranked[0]["catalog_key"] == "z_reviewed"
    flat = [c | {"provisional": False} for c in (prov, rev)]  # control
    assert sorted(flat, key=lambda c: sl.rank_key(c, set(), {}, ("S", "A")))[0]["catalog_key"] == "a_provisional"


# ── 4. load cuts need evidence; one cut a week ────────────────────────────────
LATERAL = "422B08F1"
ROW = "F1E57334"


def _lateral_record() -> list[dict]:
    """A real-shaped isolation history (invented numbers): 25-lb dumbbells, one session on the next dumbbell (e1RM jumps),
    then back at 25 with good reps at RPE 7. The e1RM trend reads 'regressing'; nothing about the effort does."""
    rows = [
        ("2026-10-20", [(25, 13, 8.0), (25, 12, 8.5), (25, 11, 9.0)]),
        ("2026-10-27", [(27.5, 13, 8.5), (27.5, 11, 9.0)]),
        ("2026-11-03", [(25, 12, 7.0), (25, 11, 8.0)]),
        ("2026-11-10", [(25, 11, 7.0), (25, 11, 8.0)]),
    ]
    return [{"date": d, "exercises": [_ex(LATERAL, s)]} for d, s in rows]


def test_an_isolation_load_cut_needs_effort_evidence_not_a_trend_alone():
    """Second red team on the owner run: a dumbbell lateral raise read 'strength sliding' and dropped a dumbbell step after a
    top set inside its range at a moderate RPE (the 2.5-lb dumbbell grid turns a 10% cut into more). The fixture reproduces the
    trigger (the trend IS 'regressing'); the guard now HOLDS without effort evidence. Controls: evidence present cuts; the
    evidence rule off cuts a whole dumbbell step."""
    rec = _lateral_record()
    assert fm.movement_signals(rec, as_of="2026-11-16")[LATERAL]["trend"] == "regressing"  # the real-data trigger, reproduced
    acc = {"kind": "accessory", "live_cost": "low"}
    prev = {"lb": 25.0, "reps": 11, "rpe": 7.0}
    d = lp.load_decision(acc, "regressing", prev, "normal", 8)
    assert d["mode"] == "hold" and d["why"] == "trend down, effort fine"
    assert lp.load_decision(acc, "regressing", prev | {"reps": 7, "rpe": 9.5}, "normal", 8)["mode"] == "down"  # real evidence cuts
    cable = {"kind": "anchor", "live_cost": "moderate"}  # the lat pulldown: a cable compound reads the same rule
    assert lp.load_decision(cable, "regressing", {"lb": 120.0, "reps": 9, "rpe": 7.5}, "normal", 6)["mode"] == "hold"
    barbell = {"kind": "anchor", "live_cost": "high"}  # a barbell trend mixing rep ranges holds too; a grind still cuts
    assert lp.load_decision(barbell, "regressing", {"lb": 185.0, "reps": 9, "rpe": 8.5}, "normal", 8)["mode"] == "hold"
    assert lp.load_decision(barbell, "regressing", {"lb": 185.0, "reps": 4, "rpe": 9.0}, "normal", 4)["mode"] == "down"
    with patch.object(lp, "effort_evidence", lambda previous, rep_lo: True):  # control: the trend alone cuts again
        cut = lp.load_decision(acc, "regressing", prev, "normal", 8)
        assert cut["mode"] == "down"
        assert round(lp._floor_to_implement(25 * KG * (1 - cut["pct"] / 100), "dumbbell") / KG, 1) == 22.5  # a whole dumbbell step


def _row_record(done_monday: bool) -> list[dict]:
    """A row trained twice a week (invented numbers): last week's heavy day overshot (a top set at RPE 9.5); this Monday's heavy
    day was done at the guarded, lighter load (or not done at all)."""
    rec = [
        {"date": "2026-10-27", "exercises": [_ex(ROW, [(80, 6, 8.5), (80, 6, 9.0)])]},
        {"date": "2026-11-03", "exercises": [_ex(ROW, [(85, 6, 9.0)])]},
        {"date": "2026-11-06", "exercises": [_ex(ROW, [(65, 12, 8.5), (65, 11, 9.0)])]},
        {"date": "2026-11-10", "exercises": [_ex(ROW, [(85, 4, 9.5)])]},
    ]
    return rec + ([{"date": "2026-11-16", "exercises": [_ex(ROW, [(80, 6, 8.5), (80, 6, 8.5)])]}] if done_monday else [])


def _row_rx() -> dict:
    return {
        "session_role": "upper_volume",
        "exposures": [
            {
                "kind": "anchor",
                "pattern": "row",
                "intensity": "volume",
                "movement_key": "one_arm_db_row",
                "sets": [{"kind": "working", "reps": [8, 12]} for _ in range(3)],
            }
        ],
    }


def test_a_lift_is_never_cut_twice_in_one_week():
    """Second red team on the owner run: a row was cut on Monday (an overshoot) and stall-reset on Thursday. With
    Monday DONE, Thursday holds: no second cut, no stall reset. Controls: Monday not done -> Thursday's reset stands (the rule
    reads what happened, never a plan); the rule off -> the second retreat returns."""
    lib = _lib()
    ctx = {"lib": lib, "idx": se.key_index(lib, CAT0), "catalog": CAT0, "target_date": "2026-11-19"}
    trends = {ROW: "stalled"}
    rx = _row_rx()
    lines = lp.mark_retreats(rx, ctx, _row_record(True), trends) + lp.stall_scheme(rx, ctx, trends)
    e = rx["exposures"][0]
    assert e.get("live_retreated") and e["sets"][0]["reps"] == [8, 12] and any(ln.startswith("one cut a week (live)") for ln in lines)
    assert lp.load_decision(e, "stalled", {"lb": 80.0, "reps": 6, "rpe": 8.5}, "normal", 8)["mode"] == "hold"
    rx2 = _row_rx()  # control 1: Monday not done -> Thursday's reset is the week's only retreat
    lp.mark_retreats(rx2, ctx, _row_record(False), trends)
    lp.stall_scheme(rx2, ctx, trends)
    assert not rx2["exposures"][0].get("live_retreated") and rx2["exposures"][0]["sets"][0]["reps"] == [10, 14]
    rx3 = _row_rx()  # control 2: the rule off -> the second retreat (reset + 10% less load) returns
    lp.stall_scheme(rx3, ctx, trends)
    assert rx3["exposures"][0]["live_load"]["pct"] == 10


# ── 5. the novelty budget ─────────────────────────────────────────────────────
def _slot(sid: str, pick: str, prev: str | None, trigger: str | None, fallbacks: list[str], hold: str | None = None) -> dict:
    rot = {"action": "rotate" if trigger else "hold", "previous": prev, "trigger": trigger}
    out = {
        "slot_id": sid,
        "pick": {"catalog_key": pick, "rotation": rot, "novel": False},
        "fallbacks": [{"catalog_key": f} for f in fallbacks],
    }
    if hold:
        out["novelty_hold"] = {
            "slot_id": sid,
            "pick": {"catalog_key": hold, "rotation": {"action": "hold", "previous": prev, "reason": sl.NOVELTY_HOLD}},
        }
    return out


def test_the_novelty_budget_counts_every_served_change_and_defers_the_optional_ones():
    """The owner run served four new movements against a budget of two. Forced changes (the previous movement cannot serve —
    equipment, no longer servable) keep their place; past the budget a stall rotation and a ledger-carried calendar change
    wait, the calendar change first. Control: the budget raised -> nothing waits."""
    policy = {"position": {"block": 2, "phase": 2, "phases_per_block": 2}, "rows": [], "recent_tids": set()}
    picked = [
        _slot("r.forced_a", "new_a", "gone_a", "equipment", ["x"]),
        _slot("r.forced_b", "new_b", "gone_b", "no_longer_servable", ["y"]),
        _slot("r.stall", "new_c", "old_c", "stall", ["old_c"], hold="old_c"),
        _slot("r.pool", "new_d", "old_d", "pool_change", ["old_d"], hold="old_d"),
    ]
    with patch.object(sl, "MAX_NEW_PER_WEEK", 99):
        assert sl.enforce_novelty(copy.deepcopy(picked), dict(policy), CAT0) == []  # control
    out = copy.deepcopy(picked)
    deferred = sl.enforce_novelty(out, dict(policy), CAT0)
    assert deferred == ["r.stall", "r.pool"] or set(deferred) == {"r.stall", "r.pool"}
    assert [p.get("novelty_serve") for p in out[2:]] == ["old_c", "old_d"]
    assert sum(1 for p in out if sl.changes_served(p, policy, CAT0)) == 2
    with patch.object(sl, "MAX_NEW_PER_WEEK", 3):  # one place left: the stall keeps it, the upgrade waits
        out = copy.deepcopy(picked)
        assert sl.enforce_novelty(out, dict(policy), CAT0) == ["r.pool"]


def _carried_served(week: dict, world: dict) -> list[str]:
    """The carried (shadow-way) ledger variants the drafted week actually SERVES in their role — each new to him (never in the
    record)."""
    out = []
    for r in world["rows"]:
        alt = (r.get("phase_2") or {}).get("variant")
        role = str(r["sk"]).split("#")[-1].split(".")[0]
        if alt and any(x["key"] == alt for s in week["sessions"] if s["role"] == role for x in s["lifts"]):
            out.append(alt)
    return out


def _carried_ledger_world() -> tuple[dict, int]:
    """Profile (a)'s world with THIS phase's ledger rows written the shadow way: four slots rotated to an eligible peer the
    record never trained (a #5075 calendar rotation the live policy did not ask for). Returns (world, slots rotated)."""
    from training import variant_rotation as vr

    prof = PROFILES["a_large_deficit_experienced"]
    world = sw.build_world(prof, "approved")
    lib, cat = world["lib"], world["catalog"]["movements"]
    pos = vr.position({"week": prof["position"]["week"], "block": prof["position"]["block"]})
    policy = sl.build_policy(lib, position=pos, rows=world["rows"], block_workouts=world["record"], as_of=prof["as_of"], gate_eval=None)
    sel = se.select_week(pos, copy.deepcopy(cat), lib, None, rows=world["rows"], missing=[], policy=policy)
    recent = policy["recent_tids"] or set()
    rows, n = copy.deepcopy(world["rows"]), 0
    for slot in sel["slots"]:
        pick = (slot.get("pick") or {}).get("catalog_key")
        alt = next(
            (
                f["catalog_key"]
                for f in slot.get("fallbacks") or []
                if str((cat.get(f["catalog_key"]) or {}).get("hevy_template_id_hint") or "").upper() not in recent
            ),
            None,
        )
        if not pick or not alt or slot.get("pinned") or n >= 4:
            continue
        row = next(r for r in rows if r["sk"] == vr.ledger_sk(pos["block"], slot["slot_id"]))
        row[f"phase_{pos['phase']}"] = {"variant": alt, "weeks": pos["phase_weeks"]}
        n += 1
    return world | {"rows": rows}, n


def test_a_ledger_carried_rotation_is_inside_the_weekly_novelty_budget():
    """The owner-run failure, reproduced: this phase's ledger carries four rotations decided the shadow way, and `_live` serves a
    ledger variant whenever it is one of the pick's fallbacks — four "New:" movements. Now the week serves at most
    MAX_NEW_PER_WEEK new movements (none of these is forced). Control: the budget's post-pass off -> all four serve."""
    world, n = _carried_ledger_world()
    assert n == 4
    prof = PROFILES["a_large_deficit_experienced"]
    week = sw.generate_week(prof, "approved", world)
    served = _carried_served(week, world)
    assert len(served) <= sl.MAX_NEW_PER_WEEK, served
    assert len(sw.measure(week, world["lib"], world["catalog"]["movements"], LANDMARKS)["new_this_week"]) <= sl.MAX_NEW_PER_WEEK
    assert any("novelty budget" in ln for s in week["sessions"] for ln in s["selection"])
    # control (FIX4: with the weekly redline, which may drop a whole slot, off too)
    with (
        patch.object(sl, "enforce_novelty", lambda picked, policy, catalog=None: []),
        patch("training.live_shape.week_ceiling", lambda env, adds: []),
    ):
        off = sw.generate_week(prof, "approved", world)
    # FIX4 (drop, don't shave): four new movements each add a find-the-load warm-up, so the time fit may DROP a whole carried
    # accessory rather than shave it to one set — it was still served by the selection, and the time line names it
    cat = world["catalog"]["movements"]
    timed = " ".join(ln for s in off["sessions"] for ln in s["rationale"] if ln.startswith("time (live)"))
    carried = [(r.get("phase_2") or {}).get("variant") for r in world["rows"] if (r.get("phase_2") or {}).get("variant")]
    dropped = [k for k in carried if k not in _carried_served(off, world) and "dropped " in timed and cat[k]["title"] in timed]
    assert len(_carried_served(off, world)) + len(dropped) == n


# ── 3. cardio ─────────────────────────────────────────────────────────────────
def test_hard_cardio_turns_easy_on_a_red_readiness_short_sleep_week(weeks):
    """Red team: in a red-readiness, 5.6-h-sleep week (state `strained`, not a deload) the tempo and intervals stayed. Now hard
    work turns easy on such a day. Control: the same profile with the bad-day signals removed keeps its hard blocks."""
    b = weeks["b_shoulder_flag_low_recovery"]["week"]
    assert not [s["role"] for s in b["sessions"] if s["cardio"].get("kind") in lp.HARD_KINDS]
    assert any("recovery is strained" in ln for s in b["sessions"] for ln in s["rationale"])
    prof = PROFILES["b_shoulder_flag_low_recovery"] | {"readiness": "green", "sleep_hours": 7.5}
    good = sw.generate_week(prof, "approved", sw.build_world(prof, "approved"))
    assert [s["role"] for s in good["sessions"] if s["cardio"].get("kind") in lp.HARD_KINDS]


def _tripped_row() -> dict:
    return {
        "id": "medical_stop_lines",
        "state": "tripped",
        "observed": {"arms": {"RHR +12 over the 14-day baseline": {"state": "tripped"}, "palpitations": {"state": "unknown"}}},
    }


def test_a_tripped_medical_stop_line_blocks_hard_cardio_and_says_review():
    """The draft reads `owner_redlines` `medical_stop_lines` (its one reader: health.tripwire_readers). Tripped -> no hard
    cardio, a review line, the conditioning note says so; `unknown` (the self-report palpitations / syncope arms, which have no
    input) is never read as tripped. Control: the same week with the row unknown keeps its hard blocks."""
    assert (
        lw.symptom_gate({"id": "medical_stop_lines", "state": "unknown", "observed": {"arms": {"palpitations": {"state": "unknown"}}}})
        is None
    )
    assert lw.symptom_gate(_tripped_row())["lines"] == ["RHR +12 over the 14-day baseline"]
    real = sw._inputs

    def with_row(row):
        def _inp(profile, day, record, rows):
            inp = real(profile, day, record, rows)
            setattr(inp, "medical_stop_lines", row)
            return inp

        return _inp

    tripped = _week("a_large_deficit_experienced", {(sw, "_inputs"): with_row(_tripped_row())})["week"]
    assert not [s for s in tripped["sessions"] if s["cardio"].get("kind") in lp.HARD_KINDS]
    assert all(any(ln.startswith("review (live): medical_stop_lines tripped") for ln in s["rationale"]) for s in tripped["sessions"])
    unknown = _week("a_large_deficit_experienced", {(sw, "_inputs"): with_row(_tripped_row() | {"state": "unknown"})})["week"]
    assert [s for s in unknown["sessions"] if s["cardio"].get("kind") in lp.HARD_KINDS]  # control


def test_the_cron_reads_the_medical_stop_line_from_the_whoop_rows_it_already_reads(monkeypatch):
    """Live only: the cron's one whoop read covers the RHR arm's 14 nights; inside an HR regime window it reads nothing."""
    import hevy_routine_cron_lambda as cron
    from health import hr_regime

    monkeypatch.setattr(se, "load_library_failsoft", lambda: _lib())
    monkeypatch.setattr(hr_regime, "is_rebaselining", lambda *a, **k: False)
    nights = [{"sk": f"DATE#2026-11-{d:02d}", "resting_heart_rate": 60} for d in range(1, 14)]
    spike = nights + [{"sk": "DATE#2026-11-14", "resting_heart_rate": 80, "recovery_score": 50}]
    out = cron._live_inputs("2026-11-15", read=lambda source, start, end: spike if source == "whoop" else [])
    assert out["medical_stop_lines"]["state"] == "tripped" and lw.symptom_gate(out["medical_stop_lines"])
    calm = nights + [{"sk": "DATE#2026-11-14", "resting_heart_rate": 61}]
    assert lw.symptom_gate(cron._live_inputs("2026-11-15", read=lambda s, a, b: calm if s == "whoop" else [])["medical_stop_lines"]) is None
    monkeypatch.setattr(hr_regime, "is_rebaselining", lambda *a, **k: True)  # control: the regime window reads nothing
    assert "medical_stop_lines" not in cron._live_inputs("2026-11-15", read=lambda source, start, end: spike if source == "whoop" else [])


def _bike(rows: list[tuple[str, int, float | None]]) -> dict:
    return {"cycling": [{"date": d, "duration_sec": m * 60, "served_kind": "tempo", "note": "", "set_rpe": r} for d, m, r in rows]}


def test_the_cardio_block_progresses_week_to_week_by_the_cardio_model():
    """`cardio_model.progress` is wired: two tempo blocks held at 20 min with the logged RPE inside the band -> 25 min (duration
    first); poor recovery steps back; an unlogged RPE holds (never evidence). Control: the progression off -> the menu's dose."""
    base = {"target_date": "2026-11-18", "state": "normal"}
    two = _bike([("2026-11-11", 20, 6.5), ("2026-11-04", 20, 6.5)])
    minutes, lines = lw.cardio_progress("tempo", base | {"by_machine": two}, 30)
    assert minutes == 25 and "add_duration" in lines[0]
    assert lw.cardio_progress("tempo", base | {"by_machine": two, "state": "strained"}, 30)[0] == lw.CARDIO_ROOM["min_block"]["value"]
    unlogged = _bike([("2026-11-11", 20, None), ("2026-11-04", 20, None)])
    held, hl = lw.cardio_progress("tempo", base | {"by_machine": unlogged}, 30)
    assert held == 30 and "hold" in hl[0]
    assert lw.cardio_progress("tempo", base | {"by_machine": {}}, 30) == (30, [])  # control: nothing performed -> the menu's dose


# ── 6. coverage ───────────────────────────────────────────────────────────────
def _vertical_pulls(week: dict, lib: dict, cat: dict) -> int:
    return sum(1 for s in week["sessions"] for x in s["lifts"] if sw._lib_entry(lib, cat, x["key"]).get("pattern") == "vertical_pull")


def test_the_garage_week_keeps_a_vertical_pull_through_the_fallback_order(weeks):
    """Red team: profile (c) has a pull-up bar but no pulldown station, and served no vertical pull all week. The bodyweight
    pull-up family is gate-locked for this lifter (fail-closed). FOURTH red team (#5861 FIX4): the dumbbell pull-over is not a
    vertical pull — Hevy's built-in "Pull Up (Band)" is now a library and catalog movement of the vertical-pull family, so the
    garage serves the band rung. Controls: without the band rung the fallback order serves the pull-over (the old answer);
    without the band rung AND the fallback -> no vertical pull."""
    from training import live_session as ls

    c = weeks["c_equipment_limited"]
    lib, cat = c["world"]["lib"], c["world"]["catalog"]["movements"]
    assert _vertical_pulls(c["week"], lib, cat) >= 2
    served = {x["key"] for s in c["week"]["sessions"] for x in s["lifts"]}
    assert "pull_up_band" in served and "db_lat_pullovers" not in served
    gated = {"pull_up", "chin_up", "pull_up_negative", "pull_up_weighted", "chin_up_weighted"}
    assert not gated & served  # a locked gate is never opened here
    real = ls._anchor_candidates
    no_band = {(ls, "_anchor_candidates"): lambda e, ctx, role: [k for k in real(e, ctx, role) if k != "pull_up_band"]}
    no_band[(lw, "VERTICAL_PULL_FALLBACK")] = tuple(k for k in lw.VERTICAL_PULL_FALLBACK if k != "pull_up_band")
    old = _week("c_equipment_limited", no_band)
    assert _vertical_pulls(old["week"], lib, cat) >= 2 and "pull_up_band" not in {
        x["key"] for s in old["week"]["sessions"] for x in s["lifts"]
    }
    off = _week("c_equipment_limited", no_band | {(lw, "vertical_pull_fallback"): lambda e, ctx, taken: None})
    assert _vertical_pulls(off["week"], lib, cat) == 0


def test_a_new_movement_never_enters_at_a_strength_rep_range(weeks):
    """Red team: the deadlift discomfort swap put a machine hip thrust new to him into a deload at 4-6, "find the load". A
    movement swapped in that he has not done this block starts at NOVEL_START (6-8, RPE <= 7). Control: the rule off -> 4-6."""
    f = weeks["f_high_fatigue_poor_sleep"]["week"]
    hip = _lift(f, "lower_heavy", "machine_hip_thrust")
    assert hip is not None and hip["reps"] == "6-8" and hip["hevy_note"].startswith("RPE 7")
    off = _week("f_high_fatigue_poor_sleep", {(lw, "novel_start"): lambda rx, ctx, workouts: []})
    assert _lift(off["week"], "lower_heavy", "machine_hip_thrust")["reps"] == "4-6"


def test_the_press_sets_option_is_three_by_ruling_and_trades_lateral_raise_sets():
    """The week's one vertical-press set was a charter decision (`split.frequency.overhead_press_per_wk` 1, #5162). Owner ruling 6
    (2026-11-13, #5861 FIX6): 2-3 weekly working sets, reallocated from redundant lateral-delt work — `press_sets` defaults to 3
    and the extra sets come off the LATERAL raises (`live_rulings.press_trade`), never the rear delts first. Control:
    `press_sets: 1` serves the charter's one set."""
    a = _week("a_large_deficit_experienced", settings={"press_sets": 1})["week"]
    on = _week("a_large_deficit_experienced")["week"]

    def sa(week):
        s = next(s for s in week["sessions"] if s["role"] == "shoulders_arms")
        return {x["key"]: x["working_sets"] for x in s["lifts"]}

    press = next(k for k in sa(a) if "press" in k)
    assert sa(a)[press] == 1  # control: the charter's one set
    # #5861 FIX4: the week's allocation counts the press option, so the trade lands on the week's delt isolation (whichever
    # day holds the surplus), not only this morning's face pull: the WEEK's sets and its shoulders stay put
    # #5861 FIX8: the upper sessions' sets — the lower-volume time fit (the week floor's abs, a calf block) moves on its own
    week_sets = lambda w: sum(
        x["working_sets"] for s in w["sessions"] if not s["role"].startswith("lower") for x in s["lifts"]
    )  # noqa: E731
    assert sa(on)[press] == 3 and week_sets(on) <= week_sets(a) + 2

    def week_of(w, word):
        return sum(x["working_sets"] for s in w["sessions"] for x in s["lifts"] if word in x["key"])

    assert week_of(on, "lateral_raise") < week_of(a, "lateral_raise")  # the trade is the lateral raises'
    assert week_of(on, "reverse_pec_deck") + week_of(on, "face_pull") >= 4  # the rear delts keep two sets twice a week


# ── 7. behind schedule ───────────────────────────────────────────────────────
def test_the_behind_schedule_week_is_an_off_by_default_option():
    """Red team: 5 of 14 days' sessions done changed almost nothing (2 sets off a session). The live option
    `behind_schedule_week` (off by default; owner decision) offers a shorter week instead: four sessions of ~45 lifting min that
    keep every anchor, with at most one accessory per major muscle. Controls: the default (off) drafts the usual five; on, with
    the miss threshold out of reach, nothing changes."""
    # FIX3: the DEFAULT response to a dip is now the shorter week (live_balance.lighter_week, tests/test_programming_fix3_5861.py);
    # `adherence_response=trim_sets` is today's old answer — five sessions, two sets off
    off = _week("d_stalled_anchor_adherence_dip", settings={"adherence_response": "trim_sets"})
    assert len(off["week"]["sessions"]) == 5 and not off["week"].get("short_week")
    on = _week("d_stalled_anchor_adherence_dip", settings={"behind_schedule_week": True})
    w = on["week"]
    assert w["short_week"].startswith("behind schedule") and len(w["sessions"]) == 4
    assert all((s["lifting_minutes"] or 0) <= lw.BEHIND_SCHEDULE["session_minutes"]["value"] for s in w["sessions"])
    from training import program_structure as ps

    for s in w["sessions"]:
        anchors = [x for x in s["lifts"] if str(x["tag"]).startswith("anchor:")]
        assert len(anchors) == len(ps.SESSION_TEMPLATES[s["role"]]["anchors"]), s["role"]  # every anchor kept
        acc = [x for x in s["lifts"] if str(x["tag"]).startswith("accessory:") and not str(x["tag"]).endswith(":carry")]
        mus = Counter(lw.landmark_muscle(x["key"], on["world"]["catalog"]["movements"], on["world"]["lib"]) for x in acc)
        assert all(n == 1 for m, n in mus.items() if m in lw.MAJOR), (s["role"], mus)
    with patch.dict(lw.BEHIND_SCHEDULE, {"missed_min": {"value": 99}}):
        assert len(_week("d_stalled_anchor_adherence_dip", settings={"behind_schedule_week": True})["week"]["sessions"]) == 5


def test_every_live_week_constant_is_a_labelled_heuristic():
    for table in (lw.KB_SLOT, lw.CARDIO_ROOM, lw.BEHIND_SCHEDULE, lw.NOVEL_START):
        for name, row in table.items():
            assert row["label"] == "heuristic" and row["basis"], name
    for name in ("evidence_rpe", "one_retreat_per_week"):
        assert lp.LOAD_POLICY[name]["label"] == "heuristic"
    assert "pinned_light_rpe" not in lp.STACK_RULE  # FIX3: "kept light" was not a limit — the pinned slot moves or is dropped
    assert lp.SETTINGS_DEFAULTS["behind_schedule_week"] is False and (LIB0.get("programming_settings") or {})["press_sets"] == 3
    assert lp.SETTINGS_DEFAULTS["symptom_line"] == ""  # #5861 FIX6, owner ruling 10: no symptom warning line by default
