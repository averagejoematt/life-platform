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

FIX ROUND 9 (consolidation) — tests deleted or rewritten here:
  test_the_kettlebell_slot_names_its_implement_caps_effort_and_loads_the_bell -> deleted: the KB slot machinery (rulings #2/#6/#7:
      no KB hinge slot under live), outcome now `live_volume._kb_slot` (tests/test_consolidation_5861.py)
  test_the_kettlebell_slot_loads_only_a_bell_on_file_and_counts_toward_glutes_and_hamstrings -> rewritten: only its still-true
      half (the logged weekly count credits through the library, never `other`)
  test_an_isolation_load_cut_needs_effort_evidence_not_a_trend_alone -> rewritten on `live_load.decide` (the one step-down)
  test_a_lift_is_never_cut_twice_in_one_week -> rewritten: mark_retreats deleted; the step-down's evidence restarts at a new load
  test_a_new_movement_never_enters_at_a_strength_rep_range -> rewritten: NOVEL_START deleted; a NEW pattern runs RPE <= 7 once
      (`live_load.mark_novelty`)
  test_the_press_sets_option_is_three_by_ruling_and_trades_lateral_raise_sets -> rewritten on the weekly plan (`live_volume`)
  test_the_behind_schedule_week_is_an_off_by_default_option -> deleted: `behind_schedule_week` (a dead alternative; ruling 2's
      dip week is `live_sequence.plan_for_days(4, mode="dip")`, tests/test_programming_fix3_5861.py)
  test_every_live_week_constant_is_a_labelled_heuristic -> rewritten onto `live_settings.HEURISTICS`
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "scripts", REPO / "lambdas" / "operational"):
    sys.path.insert(0, str(_p))

import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    fatigue_model as fm,
    live_load as ll,
    live_program as lp,
    live_settings as lset,
    live_volume as lv,
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
def test_the_logged_weekly_count_credits_a_lift_through_the_library_never_other():
    """The engine's own weekly count (fatigue_model, read by the live fatigue model and the cron's 7-day volume) credits a logged
    lift through the library target (glutes, hamstrings at the secondary credit), never the catalog's `other`. Control: no
    library -> unplaced, never guessed."""
    assert CAT0["kettlebell_deadlift"]["primary_muscle"] == "other"
    rec = [{"date": "2026-11-12", "exercises": [_ex("D20D7BBE", [(35, 8, 8.0), (35, 8, 8.0)])]}]
    hard = fm.hard_sets_by_muscle(rec, fm.library_index(LIB0), as_of="2026-11-13")
    assert hard.get("glutes") == 2 and hard.get("hamstrings") == 1.0 and "other" not in hard and "unplaced" not in hard
    assert fm.hard_sets_by_muscle(rec, {}, as_of="2026-11-13") == {"unplaced": 2.0}  # control


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


def _rows(record: list[dict], tid: str, role: str = "") -> list[dict]:
    return ll.same_role(ll.history(record, {tid})[tid], role, "2026-11-16", 8, 15)


def test_an_isolation_load_cut_needs_effort_evidence_not_a_trend_alone():
    """Second red team on the owner run: a dumbbell lateral raise read 'strength sliding' and dropped a dumbbell step after a
    top set inside its range at a moderate RPE. The fixture reproduces the trigger (the trend IS 'regressing'); the load model
    holds it (reps inside the range are no evidence). Control: two sessions running under the range floor -> a step-down,
    floored to the dumbbell (fix round 10: reps under the floor, never a trend or an RPE, move a load down)."""
    rec = _lateral_record()
    assert fm.movement_signals(rec, as_of="2026-11-16")[LATERAL]["trend"] == "regressing"  # the real-data trigger, reproduced
    d = ll.decide(_rows(rec, LATERAL), 8, 15, "dumbbell")
    assert d["mode"] == "hold" and abs(d["kg"] - 25 * KG) < 0.05
    grind = rec + [
        {"date": "2026-11-12", "exercises": [_ex(LATERAL, [(25, 7, 9.5), (25, 7, 10.0)])]},
        {"date": "2026-11-13", "exercises": [_ex(LATERAL, [(25, 7, 9.5), (25, 6, 10.0)])]},
    ]
    cut = ll.decide(_rows(grind, LATERAL), 8, 15, "dumbbell")
    assert cut["mode"] == "down" and round(cut["kg"] / KG, 1) == 22.5  # control: real evidence -> one dumbbell step
    bar = [{"date": f"2026-10-{d:02d}", "exercises": [_ex(ROW, [(185, r, rpe)] * 2)]} for d, r, rpe in ((20, 6, 8.5),)]
    bar += [{"date": f"2026-10-{d:02d}", "exercises": [_ex(ROW, [(185, 3, 9.5)] * 2)]} for d in (27, 30)]
    one = ll.decide(ll.same_role(ll.history(bar, {ROW})[ROW], "", "2026-11-03", 4, 6), 4, 6, "barbell")
    assert one["mode"] == "down" and 165 <= round(one["kg"] / KG) <= 175  # at least 5%, enough to reach the floor again


def test_a_step_down_continues_only_while_the_reps_stay_under_the_floor():
    """Second red team: a row was cut twice in one week on effort alone. Fix round 10: a step-down needs two exposures running
    under the range floor; the exposure after it, at the new load, back inside the range HOLDS. Control: still under the floor
    at the new load -> it steps down again (the ninth red team: a real decline never grinds under the floor for weeks)."""
    rec = [{"date": "2026-10-20", "exercises": [_ex(ROW, [(80, 6, 8.5), (80, 6, 9.0)])]}]
    rec += [{"date": f"2026-10-{d:02d}", "exercises": [_ex(ROW, [(80, 3, 9.5), (80, 3, 10.0)])]} for d in (27, 30)]
    rows = ll.same_role(ll.history(rec, {ROW})[ROW], "", "2026-11-03", 4, 6)
    first = ll.decide(rows, 4, 6, "machine")
    assert first["mode"] == "down"
    lb2 = first["kg"] / KG
    after = rec + [{"date": "2026-11-03", "exercises": [_ex(ROW, [(lb2, 5, 9.0)])]}]
    rows2 = ll.same_role(ll.history(after, {ROW})[ROW], "", "2026-11-06", 4, 6)
    assert ll.decide(rows2, 4, 6, "machine")["mode"] == "hold"  # back in the range: it holds and the reps climb
    still = rec + [{"date": "2026-11-03", "exercises": [_ex(ROW, [(lb2, 3, 10.0)])]}]
    rows3 = ll.same_role(ll.history(still, {ROW})[ROW], "", "2026-11-06", 4, 6)
    assert ll.decide(rows3, 4, 6, "machine")["mode"] == "down"  # control: still under the floor -> down again


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
    with patch.object(sl, "enforce_novelty", lambda picked, policy, catalog=None: []):  # control: the budget off
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
    assert lw.cardio_progress("tempo", base | {"by_machine": two, "state": "strained"}, 30)[0] == lw.EASY_MIN_BLOCK
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


def test_a_new_pattern_runs_rpe_7_once_a_familiar_one_works_at_target():
    """Red team: a machine hip thrust new to him entered a deload at 4-6, "find the load". Round 9's novelty rule: a NEW pattern
    (none logged in ~8 weeks) runs ONE exposure at RPE <= 7; a familiar pattern (a similar swap included) works at normal
    effort. Control: the same lift with its pattern in the record -> no cap."""
    lib = _lib()
    ctx = {"lib": lib, "idx": se.key_index(lib, CAT0), "catalog": CAT0, "target_date": "2026-11-16"}
    hip = {"kind": "accessory", "movement_key": "machine_hip_thrust", "intensity": "accessory", "sets": [{"reps": [8, 12]}]}
    rx = {"exposures": [dict(hip)]}
    ll.mark_novelty(rx, ctx, [{"date": "2026-11-10", "exercises": [_ex(ROW, [(80, 8, 8.0)])]}])
    e = rx["exposures"][0]
    assert e.get("live_new") and e["live_effort"] == lset.value("new_pattern_rpe")
    pattern = lv.lib_entry("machine_hip_thrust", CAT0, lib).get("pattern")
    same = next(
        str(r["template_id"]).upper()
        for k, r in ((k, lv.lib_entry(k, CAT0, lib)) for k in CAT0)
        if r.get("pattern") == pattern and r.get("template_id") and k != "machine_hip_thrust"
    )
    rx2 = {"exposures": [dict(hip)]}
    ll.mark_novelty(rx2, ctx, [{"date": "2026-11-10", "exercises": [_ex(same, [(80, 8, 8.0)])]}])
    assert rx2["exposures"][0].get("live_familiar") and "live_effort" not in rx2["exposures"][0]  # control: familiar


def test_the_press_sets_option_is_three_by_ruling_and_trades_lateral_raise_sets():
    """Owner ruling 6: 2-3 weekly overhead-press working sets, reallocated from redundant lateral-delt work — `press_sets`
    defaults to 3 and the weekly plan takes the extra sets off the LATERAL raises (down to the side-delt aim), never the rear
    delts. Control: `press_sets: 1` keeps the charter's one set."""

    def plan(n):
        lib = _lib()
        lib["programming_settings"] = dict(lib.get("programming_settings") or {}) | {"press_sets": n}
        return lv.week_plan(CAT0, lib, 5)["rows"]

    def sets(rows, word, role=None):
        return sum(r["sets"] for r in rows if word in str(r["key"]) and (role is None or r["role"] == role))

    on, one = plan(3), plan(1)
    press = next(r for r in on if r["role"] == "shoulders_arms" and r["pattern"] == "overhead_press")
    assert press["sets"] == 3
    assert next(r for r in one if r["role"] == "shoulders_arms" and r["pattern"] == "overhead_press")["sets"] == 1  # control
    # the trade comes off the lateral raises, never the rear delts — and only down to the side-delt aim (ruling #9: each head
    # assessed on its own; overhead pressing credits the side delt half a set)
    assert sets(on, "lateral_raise") <= sets(one, "lateral_raise")
    assert lv._count(on)["side_delts"] >= lset.value("delt_heads")["side_delts"]
    # the rear delts give only what keeps the shoulders at MAV (ruling 9), never under their own aim
    assert lv._count(on)["rear_delts"] >= lset.value("delt_heads")["rear_delts"] and lv._count(on)["shoulders"] <= 16


def test_every_consolidated_heuristic_is_labelled_and_the_ruled_settings_hold():
    """Ruling 18: every number of the consolidated rules is ONE labelled row (`live_settings.HEURISTICS`: value, group, basis,
    re-tune metric); the ruled settings keep their defaults (press 3, no symptom line exists to switch on)."""
    for name, row in lset.HEURISTICS.items():
        assert row["basis"] and row["retune"] and row["group"] in ("progression", "novelty", "volume", "time"), name
    assert lset.defaults()["press_sets"] == 3
    assert not {"symptom_line", "behind_schedule_week", "kb_slot_role"} & set(lset.SETTINGS)
    assert "pinned_light_rpe" not in __import__("training.live_program", fromlist=["x"]).STACK_RULE
