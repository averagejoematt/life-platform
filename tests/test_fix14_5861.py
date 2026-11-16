"""#5861 fix round 14 — the last narrow fix lane: the second final check's blocking fails, each as an OUTCOME with a must-fail
control in the same test. Synthetic profiles and invented numbers only.

  1  A1(f): on the heavy lower morning no compound but the squat runs above RPE 8 (the effort table's `heavy_lower_other` row);
  2  D7: a load is achievable at its target RPE — the last set logged above the target at the rep floor sets the load the lift's
     own e1RM supports at the target (`live_load.effort_fit`);
  3  A4(f)/G8/B23: the weekly plan counts what the mornings serve — the heavy pull's top set + one back-off, the selection's
     accessory picks, the session set ceiling — and a priority it cannot reach is said with the real reason;
  4  B2: a workout with no role in its title takes its role from its content, and is never another role's reference;
  5  B5: the slump takes about a third of the non-priority accessory SETS, and says exactly what it took;
  6  A2: after a step-down, a lift with no RPE logged climbs back by double progression when the reps reach the top;
  7  H4: the kettlebell swing's readiness is measured on the barbell deadlift the engine serves, plus his technique word;
  8  B9: a movement with no logged set says so and starts from the closest logged movement; one such movement per muscle.
"""

from __future__ import annotations

import json
import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "lambdas"), str(REPO / "scripts"), str(REPO / "deploy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    exercise_gates as eg,
    hevy_note_grammar as g,
    live_load,
    live_program,
    live_rulings,
    live_shape,
    live_volume,
)

PROFILES = sw.load_profiles()
A = PROFILES["a_large_deficit_experienced"]
LANDMARKS = json.loads((REPO / "config" / "training_landmarks.json").read_text())["muscles"]
LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
KG = live_load.KG_PER_LB


def _patched(patches: dict | None):
    stack = ExitStack()
    for (m, a), v in (patches or {}).items():
        stack.enter_context(patch.object(m, a, v))
    return stack


def _week(prof: dict, patches: dict | None = None, settings: dict | None = None) -> dict:
    plans: list[dict] = []
    real = live_volume.week_plan

    def keep(*a, **k):  # the plan each morning drafted from (the press-trade report's own plans are not a morning's)
        out = real(*a, **k)
        plans.append(out)
        return out

    with patch.dict(sw.SETTINGS, settings or {}), _patched((patches or {}) | {(live_volume, "week_plan"): keep}):
        world = sw.build_world(prof, "approved")
        week = sw.generate_week(prof, "approved", world)
    m = sw.measure(week, world["lib"], world["catalog"]["movements"], {"muscles": LANDMARKS})
    return {"world": world, "week": week, "m": m, "hard": m["hard_sets"], "plan": plans[0] if plans else None}


def _lines(w: dict, prefix: str) -> list[str]:
    return [ln for s in w["week"]["sessions"] for ln in list(s["rationale"]) + list(s.get("live_fit") or []) if ln.startswith(prefix)]


def _effort_top(note: str | None) -> float:
    line = next((ln for ln in (note or "").split("\n") if g.EFFORT_RE.match(ln)), "")
    import re

    return max([float(x) for x in re.findall(r"\d+(?:\.\d+)?", line)] or [0.0])


# ── 1. A1(f): the heavy lower morning ────────────────────────────────────────────────────────────────────────────────────────
def test_the_heavy_lower_morning_holds_every_compound_but_the_squat_at_rpe_8():
    """Amended A1(f) and owner ruling 2026-11-14 (3): on the heavy lower morning the squat alone may reach RPE 8-9 on its last
    set; the deadlift and every other compound (a split squat in an accessory slot) stay at RPE 8. Isolation work keeps its
    band. Control: the role lookup without the mark -> the split squat is back at RPE 8-9, last set 9-10."""

    def compounds(w: dict) -> list[tuple[str, float]]:
        cat, lib = w["world"]["catalog"]["movements"], w["world"]["lib"]
        s = next(s for s in w["week"]["sessions"] if s["role"] == "lower_heavy")
        return [
            (x["key"], _effort_top(x["hevy_note"]))
            for x in s["lifts"]
            if x["tag"] != "anchor:squat:heavy" and live_program._compound(live_volume.lib_entry(x["key"], cat, lib))
        ]

    w = _week(A)
    got = compounds(w)
    assert any(k != "deadlift_barbell" for k, _ in got), got  # the profile serves a compound accessory that morning
    assert all(0 < top <= 8 for _, top in got), got
    role = live_load.effort_role
    off = _week(A, {(live_load, "effort_role"): lambda e: role({k: v for k, v in e.items() if k != "live_effort_role"})})
    assert any(top > 8 for _, top in compounds(off)), compounds(off)


# ── 2. D7: a load the target RPE can lift ───────────────────────────────────────────────────────────────────────────────────
def _rows(*sets: tuple[float, int, float | None], role: str = "upper_heavy") -> list[dict]:
    return [
        {"date": f"2026-11-{10 - i:02d}", "role": role, "sets": [{"kg": lb * KG, "reps": r, "rpe": e}]} for i, (lb, r, e) in enumerate(sets)
    ]


def test_a_load_last_logged_above_the_target_at_the_floor_comes_to_what_his_e1rm_supports():
    """The second final check (D7): the target RPE dropped to 8 while the bench stayed at 235, where his last set was 4 reps at
    RPE 9 — about 3 reps at RPE 8, an impossible 4-6. ONE rule, every lift: the last set logged ABOVE the target at or near
    the rep floor -> the load his own e1RM supports at the target for the floor, said in plain words. Controls: the same set at
    the target, with no RPE, or well above the floor holds; the rule off -> the impossible load holds."""
    d = live_load.decide(_rows((235, 4, 9.0)), 4, 6, "barbell", target_rpe=8)
    assert d["mode"] == "down" and round(d["kg"] / KG) == 225, d
    assert d["clause"] == "Lighter: 4 reps was RPE 9 last time; this load is RPE 8 for 4." and g.REASON_RE.match(d["clause"])
    two = [
        {
            "date": "2026-11-10",
            "role": "upper_heavy",
            "sets": [{"kg": 110 * KG, "reps": 5, "rpe": 9.5}, {"kg": 100 * KG, "reps": 6, "rpe": 8.0}],
        }
    ]
    row = live_load.decide(two, 4, 6, "dumbbell", target_rpe=8)
    assert row["mode"] == "down" and round(row["kg"] / KG) == 105, row
    assert live_load.decide(_rows((235, 4, 8.0)), 4, 6, "barbell", target_rpe=8)["mode"] == "hold"
    assert live_load.decide(_rows((235, 4, None), (235, 5, None)), 4, 6, "barbell", target_rpe=8)["mode"] == "hold"  # no RPE
    assert live_load.decide(_rows((235, 6, 9.0)), 4, 6, "barbell", target_rpe=8)["why"] == "the top at RPE 8 first"
    one_under = live_load.decide(_rows((235, 3, 9.0), (235, 5, 8.0)), 4, 6, "barbell", target_rpe=8)  # under the floor ONCE:
    assert one_under["mode"] == "hold" and round(one_under["kg"] / KG) == 235  # the two-exposure rule decides, unchanged
    with patch.object(live_load, "effort_fit", lambda *a, **k: None):  # control: the rule off
        held = live_load.decide(_rows((235, 4, 9.0)), 4, 6, "barbell", target_rpe=8)
    assert held["mode"] == "hold" and round(held["kg"] / KG) == 235


# ── 3. A4(f) / G8 / B23: the plan counts what is served ─────────────────────────────────────────────────────────────────────
def _plan_vs_served(w: dict) -> dict:
    hs = dict(w["hard"]) | dict(w["m"].get("delt_heads") or {})
    pc = w["plan"]["counts"]
    return {m: (pc.get(m, 0.0), hs.get(m, 0.0)) for m in w["plan"]["targets"] if abs(pc.get(m, 0.0) - hs.get(m, 0.0)) > 1e-6}


def test_the_week_plan_counts_the_sets_the_mornings_serve():
    """The second final check (B23): the plan counted the heavy deadlift at its template's 3 sets while the morning serves its
    top set + one back-off, and counted each slot's template accessory instead of the selection's pick — so it saw back and
    glutes at their aims when they were not. The plan now counts the served shape and the served picks: on a full week its
    count is the served counter's, muscle by muscle. Control: the plan back on the template's set count -> they disagree."""
    w = _week(A)
    assert _plan_vs_served(w) == {}, _plan_vs_served(w)
    dl = next(r for r in w["plan"]["rows"] if r["role"] == "lower_heavy" and r["key"] == "deadlift_barbell")
    assert dl["sets"] == 2
    off = _week(A, {(live_shape, "served_sets"): lambda role, e: len(e.get("sets") or [])})
    assert _plan_vs_served(off), "control: the template count disagrees with the served week"


def test_naming_back_and_glutes_reaches_back_and_says_what_holds_glutes():
    """The second final check (A4(f), G8): naming back + glutes changed nothing, because the plan already counted both at their
    aims. Now back reaches its own aim, and a priority still short says so in ONE line with its real reason (a movement new to
    him counts from its second session; the trade is never the conditioning dose — owner ruling 8). Chest and quads still
    reach 10 with the default priorities."""
    base = _week(A)
    assert base["hard"]["chest"] >= 10 and base["hard"]["quadriceps"] >= 10, base["hard"]
    w = _week(A, settings={"priority_muscles": ["back", "glutes"]})
    tg = w["plan"]["targets"]
    assert w["hard"]["back"] >= tg["back"]["aim"], (w["hard"]["back"], tg["back"])
    short = [m for m in ("back", "glutes") if w["hard"].get(m, 0) + 1e-9 < tg[m]["aim"]]
    lines = sorted(set(_lines(w, "priority (live): ")))
    assert (len(lines) == 1 and all(m in lines[0] for m in short)) if short else lines == [], (short, lines)
    assert len([s for s in w["week"]["sessions"] if (s.get("cardio") or {}).get("key")]) == 1  # the dose is never taken


def test_a_priority_short_because_its_movement_is_new_says_so():
    """A priority whose only added movement is new to him (one RPE-7 exposure, counted from next week) names THAT, not the
    75-minute ceiling. Control: no learning row -> the ceiling line."""
    tg = {"glutes": {"floor": 6.0, "aim": 8.0, "cap": 16.0}}
    rows = [{"role": "lower_volume", "key": "db_hip_thrust", "fill": "glutes", "learning": True, "sets": 2}]
    cat = {"db_hip_thrust": {"title": "DB Hip Thrust"}}
    line = live_rulings.priority_trade(["glutes"], {"glutes": 7.5}, tg, "shoulders_arms", {}, LIB, rows, cat)
    assert "DB Hip Thrust is new to you" in line and "ceiling" not in line, line
    assert "ceiling" in live_rulings.priority_trade(["glutes"], {"glutes": 7.5}, tg, "shoulders_arms", {}, LIB, [], cat)


# ── 4. B2: role-less titles ─────────────────────────────────────────────────────────────────────────────────────────────────
def _ex(tid: str, lb: float, reps: int) -> dict:
    return {"template_id": tid, "sets": [{"type": "normal", "weight_kg": lb * KG, "reps": reps, "rpe": 8.5}]}


def test_a_workout_with_no_role_in_its_title_takes_its_role_from_its_content():
    """The second final check (B2): with role-less titles the heavy-day pulldown read the volume day's 160 x 10 every week and
    stepped up ("10 reps reached") at the same load. An untitled workout now takes the role whose template anchors it holds most
    of; a tie stays role-less and is never a named role's reference. Control: the old band test -> the heavy day reads the
    volume day's set."""
    roles = {
        "BENCH": {"upper_heavy"},
        "INCLINE": {"upper_volume"},
        "ROW": {"upper_heavy", "upper_volume"},
        "PULL": {"upper_heavy", "upper_volume"},
    }
    heavy = {"date": "2026-11-09", "title": "Morning Workout", "exercises": [_ex("BENCH", 225, 5), _ex("ROW", 100, 6), _ex("PULL", 165, 9)]}
    volume = {
        "date": "2026-11-12",
        "title": "Morning Workout",
        "exercises": [_ex("INCLINE", 80, 10), _ex("ROW", 90, 10), _ex("PULL", 160, 10)],
    }
    tie = {"date": "2026-11-13", "title": "Morning Workout", "exercises": [_ex("PULL", 150, 10)]}
    hist = live_load.history([heavy, volume, tie], {"PULL"}, roles)["PULL"]
    assert [r["role"] for r in hist] == ["", "upper_volume", "upper_heavy"]
    got = live_load.same_role(hist, "upper_heavy", "2026-11-16", 6, 10)
    assert [(r["date"], r["role"]) for r in got] == [("2026-11-09", "upper_heavy")]
    assert live_load.decide(got, 6, 10, "cable", target_rpe=9)["mode"] == "hold"  # 9 reps: the reps climb first
    blind = live_load.history([heavy, volume, tie], {"PULL"})["PULL"]  # control: no content read, the old band test
    old = [r for r in blind if not r["role"] and r["sets"][0]["reps"] <= 10]
    assert live_load.decide(old, 6, 10, "cable", target_rpe=9)["mode"] == "up", "control: the heavy day reads a 10-rep set"


# ── 5. B5: the slump's third ────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_slump_takes_about_a_third_of_the_accessory_sets_and_says_exactly_what():
    """The second final check (B5): "non-priority accessories -1 set(s) (about a third)" while the week went 74 -> 72 sets —
    2-set slots could not lose a third of themselves. The session's non-priority accessory SETS now come down by about a third
    (a slot at 2 goes whole once every slot is at 2), and the line says how many of how many. Control: the per-slot rule
    took nothing from 2-set slots."""
    acc = lambda k, n: {"kind": "accessory", "intensity": "accessory", "movement_key": k, "sets": [{}] * n}  # noqa: E731
    rx = {"exposures": [{"kind": "anchor", "sets": [{}] * 3}] + [acc(k, 2) for k in ("curl", "pushdown", "raise")] + [acc("fly", 2)]}
    lines = live_load.slump_trim(rx, {"fly"})
    left = {e.get("movement_key"): len(e["sets"]) for e in rx["exposures"]}
    assert left == {None: 3, "curl": 2, "pushdown": 2, "fly": 2}, left  # 2 of 6 non-priority sets: the last slot whole
    assert lines == ["slump (live): non-priority accessories -2 of 6 set(s) (about a third; left out: raise), no load steps up"]
    big = {"exposures": [acc("a", 3), acc("b", 3), acc("c", 3)]}
    live_load.slump_trim(big)
    assert [len(e["sets"]) for e in big["exposures"]] == [2, 2, 2]

    def per_slot(rx: dict, keep: set | None = None) -> list[str]:  # control: round 13's per-slot third, never under 2
        for e in rx["exposures"]:
            if e.get("kind") == "accessory" and e.get("movement_key") not in (keep or set()):
                n = len(e["sets"])
                e["sets"] = e["sets"][: max(2, n - round(n * 0.34))]
        return []

    rx2 = {"exposures": [acc(k, 2) for k in ("curl", "pushdown", "raise")]}
    per_slot(rx2)
    assert sum(len(e["sets"]) for e in rx2["exposures"]) == 6, "control: the per-slot rule takes nothing"


# ── 6. A2: back up after a step-down, reps alone ────────────────────────────────────────────────────────────────────────────
def test_after_a_step_down_a_lift_with_no_rpe_climbs_back_when_the_reps_reach_the_top():
    """The second final check (A2, the no-RPE half): sim10's `norpe_noise` deadlift stepped 190 -> 175 and sat there six weeks.
    The cause is the harness's noise, not the model: its one global noise counter met a week of 25-30 exercises, a multiple of
    the 5-step cycle, so the deadlift drew -2 reps in 7 of 8 weeks — a constant under-log, logged 175 x 4 every week. The model
    steps the reduced load up as soon as the LOGGED reps reach the top, with no RPE (reps alone decide). Control: the
    effort-unknown rule off (RPE required to step) -> it holds."""
    rows = [
        {"date": "2026-12-08", "role": "lower_heavy", "sets": [{"kg": 175 * KG, "reps": 6, "rpe": None}]},
        {"date": "2026-12-01", "role": "lower_heavy", "sets": [{"kg": 175 * KG, "reps": 5, "rpe": None}]},
        {"date": "2026-11-24", "role": "lower_heavy", "sets": [{"kg": 190 * KG, "reps": 2, "rpe": None}]},
        {"date": "2026-11-17", "role": "lower_heavy", "sets": [{"kg": 190 * KG, "reps": 3, "rpe": None}]},
    ]
    assert live_load.decide(rows[2:], 4, 6, "barbell", target_rpe=8)["mode"] == "down"  # the two-exposure rule, unchanged
    up = live_load.decide(rows, 4, 6, "barbell", target_rpe=8, top_set=True)
    assert up["mode"] == "up" and round(up["kg"] / KG) == 180, up
    assert live_load.decide(rows[1:], 4, 6, "barbell", target_rpe=8)["mode"] == "hold"  # 5 reps: the reps climb first
    needs_rpe = lambda r, hi, target, unknown: all(
        x["reps"] >= hi and x["rpe"] is not None and x["rpe"] <= target for x in r["sets"]
    )  # noqa: E731
    with patch.object(live_load, "topped", needs_rpe):  # control: a step that needs a logged RPE never comes for this lifter
        assert live_load.decide(rows, 4, 6, "barbell", target_rpe=8)["mode"] == "hold", "control: RPE required -> no step"


# ── 7. H4: the swing's readiness ────────────────────────────────────────────────────────────────────────────────────────────
def _deadlifts(*rpes: float) -> list[dict]:
    days = ("2026-10-20", "2026-10-27", "2026-11-03", "2026-11-10")
    return [
        {"date": d, "exercises": [{"template_id": "C6272009", "sets": [{"reps": 5, "weight_kg": 100.0, "rpe": r}] * 3}]}
        for d, r in zip(days, rpes)
    ]


def test_the_swing_is_measured_on_the_barbell_deadlift_and_stays_locked_without_his_technique_word():
    """The second final check (H4): `chain_kb_swing` required two kettlebell-deadlift sessions, a movement the engine serves
    zero times. It is now the readiness proposal's standard on the barbell deadlift (3 x 5+ at RPE <= 8, 3 sessions across 2
    weeks, no pain flag in 28 days) AND his one-time technique confirmation on every swing template. The swing stays locked.
    Controls: the standard unmet (RPE 9) -> the chain is locked; a kettlebell-deadlift record no longer opens it; his
    confirmation -> that gate opens for the swing alone."""
    gate = LIB["gates"]["chain_kb_swing"]
    assert gate["chain_prerequisites"] == ["deadlift_barbell"] and gate["standard"]["rpe_max"] == 8
    for k in ("kettlebell_swing", "swing", "double_swings"):
        assert {"chain_kb_swing", "owner_confirmation_skill"} <= set(LIB["movements"][k]["gates"]), k
    met = eg.evaluate_gates(LIB, None, {"as_of": "2026-11-15", "hevy_workouts": _deadlifts(8, 7.5, 8)})
    assert met["chain_kb_swing"]["state"] == eg.UNLOCKED
    swing = eg.movement_states(LIB, met)["kettlebell_swing"]
    assert swing["state"] == eg.LOCKED and "owner_confirmation_skill" in swing["locked_by"], swing
    assert (
        eg.evaluate_gates(LIB, None, {"as_of": "2026-11-15", "hevy_workouts": _deadlifts(9, 9, 9)})["chain_kb_swing"]["state"] == eg.LOCKED
    )
    kb = [
        {"date": d, "exercises": [{"title": "Kettlebell Deadlift", "template_id": "X", "sets": [{"reps": 8, "rpe": 7}] * 3}]}
        for d in ("2026-11-03", "2026-11-10")
    ]
    assert eg.evaluate_gates(LIB, None, {"as_of": "2026-11-15", "hevy_workouts": kb})["chain_kb_swing"]["state"] == eg.LOCKED
    word = eg.confirmation_verdict({"technique_confirmations": {"kettlebell_swing": {"confirmed_on": "2026-11-15"}}}, "kettlebell_swing")
    assert word["state"] == eg.UNLOCKED and eg.confirmation_verdict({}, "kettlebell_swing")["state"] != eg.UNLOCKED


# ── 8. B9: what a new movement's note says ──────────────────────────────────────────────────────────────────────────────────
def test_a_movement_with_no_logged_set_says_so_and_starts_from_the_closest_logged_one():
    """The second final check (B9): "find the load" on a movement whose pattern sat in the record. A movement with no logged
    set now says so and starts near the load of the closest logged movement (same pattern, same equipment: a dumbbell's
    per-hand load never starts a cable movement); with none on file, "find the load" stands, said as new."""
    note = "RPE 8–9, last set RPE 9–10\nW set: up to 8 easy reps, find the load.\nBreathe out on the crunch."
    got = live_load.start_line(note, {"lb": 47.0, "title": "Cable Twist", "new": True})
    assert (
        got.split("\n")[1] == "New to you: start light near your Cable Twist (47 lb), find the working load."
        and g.PICK_LOAD_OPEN_TAIL not in got
    )
    fill = live_load.start_line(note, {"lb": None, "new": False, "for": "calves"})
    assert fill.split("\n")[1] == "Not done lately, for calves: W set up to 8 easy reps, find the load."
    rotated = "RPE 8–9, last set RPE 9–10\nNew: replaces Side Bend.\nW set: up to 8 easy reps, find the load."
    assert live_load.start_line(rotated, {"lb": 30.0, "title": "Curl", "new": True}).endswith(
        "Start light near your Curl (30 lb), find the working load."
    )
    assert live_load.start_line(note, None) == note  # control: no start point -> the note as composed
    assert all(g.phone_lines(x) <= g.LIFT_MAX_LINES for x in (got, fill))


def test_a_week_meets_at_most_one_movement_new_to_him_per_muscle():
    """The second final check (B9): a normal week serves at most ONE movement with no logged set per muscle (a rotation pick
    or a fill), and that movement's phone note carries the reason. Control: the one-per-muscle rule off -> the plan adds a
    second new glute movement."""
    cat = sw.build_world(A, "approved")["catalog"]["movements"]
    tid = lambda k: str(live_volume.lib_entry(k, cat, LIB).get("template_id") or "").upper()  # noqa: E731
    logged = frozenset({tid("barbell_bench_press")})
    one = [{"role": "lower_volume", "key": "db_hip_thrust", "fill": "glutes", "learning": True, "sets": 2}]
    assert live_rulings.new_for("glutes", "glute_kickback_machine", one, cat, LIB, logged)  # a second new glute movement: refused
    assert not live_rulings.new_for("glutes", "glute_kickback_machine", [], cat, LIB, logged)  # the first one: allowed
    assert not live_rulings.new_for("glutes", "glute_kickback_machine", one, cat, LIB, logged | {tid("glute_kickback_machine")})
    assert not live_rulings.new_for("calves", "glute_kickback_machine", one, cat, LIB, logged)  # another muscle's new movement
    w = _week(A)
    for s in w["week"]["sessions"]:
        for x in s["lifts"]:
            if g.PICK_LOAD_OPEN_TAIL in (x["hevy_note"] or "") or "start light" in (x["hevy_note"] or ""):
                assert any(h in x["hevy_note"] for h in ("New: replaces", "New to you", "Not done lately")), (s["role"], x["hevy_note"])


# ── should-fix 9-11 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_accessory_trained_since_a_gap_is_not_a_first_session_back():
    """The second final check (B8): "first session back after 10 days off" on a calf raise trained since on another morning —
    the mark was kept per role. An accessory trained since the gap on any morning is back; an anchor keeps the per-role mark.
    Control: the accessory never trained since -> it is a first session back."""
    cat = {"calf": {"hevy_template_id_hint": "CALF"}, "squat": {"hevy_template_id_hint": "SQ"}}
    ctx = {"target_date": "2026-12-10", "catalog": cat, "lib": {}, "idx": {"to_lib": {}}}
    old = {"date": "2026-11-10", "title": "LOWER-HEAVY — W1", "exercises": [_ex("CALF", 100, 12), _ex("SQ", 200, 5)]}
    since = {"date": "2026-12-03", "title": "LOWER-VOLUME — W2", "exercises": [_ex("CALF", 100, 12), _ex("SQ", 180, 10)]}

    def mark(workouts):
        rx = {
            "session_role": "lower_heavy",
            "exposures": [{"kind": "accessory", "movement_key": "calf"}, {"kind": "anchor", "movement_key": "squat"}],
        }
        live_load.mark_novelty(rx, ctx, workouts)
        return {e["movement_key"]: bool(e.get("live_first_back")) for e in rx["exposures"]}

    assert mark([old, since]) == {"calf": False, "squat": True}  # the squat's heavy day has not been back yet
    assert mark([old]) == {"calf": True, "squat": True}  # control: nothing trained since -> both are back for the first time


def test_a_carry_under_a_back_or_wrist_flag_is_held_at_rpe_8_with_the_stop_line():
    """The second final check (B11/B15): under a sharp low-back or a wrist flag the farmer's walk ran at RPE 8-9 with no stop
    line. A carry loading the flagged joint is held (never routed): RPE <= 8 and the in-set stop line. Control: an
    unflagged week's carry keeps its band."""
    flag = {
        "movement_id": "other",
        "joints": ["spinal_load"],
        "group": "pull",
        "tier": "avoid",
        "severity": 6.0,
        "sharp": False,
        "scope": "pattern",
        "title": "Deadlift",
        "source": "pain",
    }
    lib = {
        "movements": {
            "farmers_walk": {"title": "Farmers Walk", "pattern": "carry", "joint_stress": {"spinal_load": "moderate", "wrist": "moderate"}}
        }
    }
    ctx = {"lib": lib, "catalog": {"farmers_walk": {"title": "Farmers Walk"}}, "idx": {"to_lib": {"farmers_walk": "farmers_walk"}}}
    rx = {"exposures": [{"kind": "accessory", "intensity": "carry", "movement_key": "farmers_walk", "sets": [{}, {}]}]}
    lines = live_program.apply_joint_rule(rx, ctx, {}, [flag])
    e = rx["exposures"][0]
    assert e["live_effort"] == 8 and e.get("live_stop") and lines and lines[0].startswith("held (live): Farmers Walk"), (e, lines)
    clean = {"exposures": [{"kind": "accessory", "intensity": "carry", "movement_key": "farmers_walk", "sets": [{}, {}]}]}
    assert live_program.apply_joint_rule(clean, ctx, {}, []) == [] and "live_effort" not in clean["exposures"][0]


def test_a_short_week_with_no_ab_sets_says_so():
    """The second final check (B24): the 1- and 2-morning weeks served 0 ab sets and no line said so. The plan says it once.
    Control: a full week (abs served) says nothing."""
    cat, lib = sw.build_world(A, "approved")["catalog"]["movements"], sw.approved_library(LIB, A)
    one = live_volume.week_plan(cat, lib, 1)
    said = [ln for ln in one["lines"] if ln.startswith("abs: ")]
    assert (one["counts"].get("abs", 0) == 0) == bool(said) and (not said or "0 direct ab sets" in said[0]), (
        one["counts"].get("abs"),
        said,
    )
    assert not [ln for ln in live_volume.week_plan(cat, lib, 5)["lines"] if ln.startswith("abs: ")]


# ── owner requirements of 2026-11-15: pain-aware selection, one duration model, the fallback joint rule ─────────────────────
def test_a_painful_movement_is_never_replaced_by_one_rated_worse_on_its_joints():
    """B15: under elbow pain the triceps slot rotated into Lying Db Tricep Extension (elbow high) for the flagged Overhead
    Triceps Extension (elbow moderate). The pain route keeps only candidates no harder on any joint the flagged movement loads.
    Control: the rule off -> the elbow-high candidate stays in the route."""
    from training import selection_engine as se, selection_live as sl

    cat = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
    ctx = {"lib": LIB, "idx": se.key_index(LIB, cat)}
    ranked = [{"movement_id": "lying_db_tricep_extension", "catalog_key": "lying_db_tricep_extension"}]
    ranked += [{"movement_id": "triceps_pushdown", "catalog_key": "triceps_pushdown"}]
    kept = [c["catalog_key"] for c in sl.no_worse_for_pain(ranked, "overhead_triceps_extension_cable", ctx)]
    assert kept == ["triceps_pushdown"], kept
    assert len(ranked) == 2  # control: without the rule both were in the route (the pick was the elbow-high one)


def test_a_low_score_flag_holds_only_the_flagged_lift():
    """B16: a 2/10 low-back flag on the deadlift changed five other lifts ("Same load: spinal load flag"). A stated score at or
    under the lift-only line, not sharp, scopes the flag to its lift; a higher score or 'sharp' stays joint-wide."""
    from training import live_pain

    flag = {"source": "pain", "severity": 2.0, "sharp": False}
    assert live_pain.scope(flag, set(), "DL") == "lift"
    assert live_pain.scope(flag | {"severity": 4.0}, set(), "DL") == "joint"  # control: above the line
    assert live_pain.scope(flag | {"sharp": True}, set(), "DL") == "joint"  # control: sharp


def test_no_fallback_rises_to_high_on_a_joint_its_movement_is_below_high():
    """Owner 2026-11-15 ("never a demonstrably worse option for the affected joint"): 24 fallback links stepped a joint from
    moderate to high. The equivalence rule now refuses that rise too; the committed library holds none. Control: a planted
    goblet squat -> zercher squat link (spinal moderate -> high) breaks the rule."""
    from training import library_integrity as li

    mv = LIB["movements"]
    rise = [
        (k, f["movement_id"], j)
        for k, e in mv.items()
        for f in e["fallbacks"]
        for j, v in (mv[f["movement_id"]].get("joint_stress") or {}).items()
        if v == "high" and (e.get("joint_stress") or {}).get(j) in ("low", "moderate")
    ]
    assert rise == [], rise[:5]
    assert "joint_stress" in li._suitability_breaks(mv["goblet_squat"], mv["zercher_squat"])


def test_the_prescription_carries_the_minutes_the_75_minute_fit_enforces():
    """Owner requirement (duration): the prescription's printed minutes and the 75-minute fit's minutes are ONE model — the
    routine as written, warm-ups included. Control: the prescription's own pre-routine estimate differs on a served morning."""
    w = _week(A)
    rows = [(s["role"], s["lifting_minutes"], s["rx_minutes"]) for s in w["week"]["sessions"]]
    assert all(lm == rx for _r, lm, rx in rows), rows
    from training import live_session

    real = live_session.fit_routine

    def stale(blocks, rx, cap, movements, rationale, shape):  # control: the prescription keeps its pre-routine estimate
        before = dict(rx.get("session_minutes") or {})
        out = real(blocks, rx, cap, movements, rationale, shape)
        rx["session_minutes"] = before
        return out

    off = _week(A, {(live_session, "fit_routine"): stale})
    assert any(s["lifting_minutes"] != s["rx_minutes"] for s in off["week"]["sessions"])


def test_a_one_or_two_morning_week_reserves_no_dose_minutes_on_the_fit():
    """Found while reconciling planner and served counts: the 75-minute fit kept the conditioning dose's 10 minutes free on a
    2-morning week's host (where no dose is served and the plan reserves none), and cut a planned calf slot for them. The fit
    now reserves exactly what the plan does. Control: a 3-morning week still reserves them."""
    from training import live_session

    rx = {"session_role": "upper_heavy", live_session.MARK: {"conditioning_host": "upper_heavy", "week_skip": ["a", "b", "c"]}}
    assert live_session._dose_reserve(rx) == 0
    three = rx | {live_session.MARK: rx[live_session.MARK] | {"week_skip": ["a", "b"]}}
    assert live_session._dose_reserve(three) == int(live_volume.reserve_minutes())


def test_a_held_carrys_stop_line_keeps_its_logging_line():
    """The held carry's stop line (B11/B15) displaced 'Steps go in the yards box.' (lint L11) on the phone budget; it now takes
    the posture cue's place. The note keeps line 1, the adjust rule and the yards line."""
    w = _week(PROFILES["a_large_deficit_experienced"])  # an unflagged week: the cue stays
    carry = next(x for s in w["week"]["sessions"] for x in s["lifts"] if x["key"] == "farmers_walk")
    assert g.CARRY_CUE in carry["hevy_note"] and g.CARRY_STEPS_LINE in carry["hevy_note"]


# ── #6015: hold-and-build — the engine's own step up is held and built, not undone ──────────────────────────────────────────────
def _lifter(e1rm_lb: float, weeks: int, start: tuple[float, int, float], equipment: str = "dumbbell", rep_lo: int = 4, rep_hi: int = 6):
    """A closed loop over `live_load.decide`: a synthetic lifter of FIXED strength (`e1rm_lb`, Epley) performs each prescribed load
    to the target RPE 8 (two in reserve) — the floor ground out at one in reserve when two in reserve cannot reach it — and the
    exposure feeds the next decision (the simulator athlete's own model, `progression_sim_5861.Physiological`, without the
    draft path). Returns [(lb, reps, rpe, mode)] per exposure, oldest first."""
    import math

    from common.pacific_time import shift_day_key

    rows = _rows(start)
    out = []
    for i in range(weeks):
        d = live_load.decide(rows, rep_lo, rep_hi, equipment, target_rpe=8)
        lb = round(d["kg"] / KG, 1)
        rtf = 30 * (e1rm_lb / lb - 1)
        reps = min(rep_hi, math.floor(rtf - 2 + 1e-9))
        if reps < rep_lo:
            reps = max(1, min(rep_lo, math.floor(rtf - 1 + 1e-9)))
        rpe = min(10.0, round((10.0 - (rtf - reps)) * 2) / 2)
        out.append((lb, reps, rpe, d["mode"]))
        day = shift_day_key(rows[0]["date"], 7)  # one exposure a week, newest first
        rows = [{"date": day, "role": "upper_heavy", "sets": [{"kg": d["kg"], "reps": reps, "rpe": rpe}]}] + rows
    return out


def test_a_step_up_is_held_and_built_never_undone_by_one_hard_first_exposure():
    """#6015 (the row bounce, owner ruling 2026-11-16): a steady lifter whose dumbbell row tops 60 x 6 at RPE 8 steps to 65, lands
    4 at RPE 9 there — a normal first exposure at a load one coarse 5-lb step (~8 %) heavier — and the D7 fit stepped it back to
    60 every other week (65, 60, 65, 60, ...). Hold-and-build: the raised load HOLDS while the miss is inside the tolerance (the
    floor reached, at most `step_up_hold_rpe_over` RPE over target); a lifter who builds nothing at it for
    `step_up_hold_exposures` exposures reverts ONCE, and the stalled load is not retried until the top comes one RPE easier.
    Twelve exposures, the load never climbs back to a load it was taken off. Control: the rule off (`held_step` -> None, the
    code on main) -> the bounce returns, every other exposure."""
    e1 = 60 * (1 + 8 / 30)  # 60 x 6 at RPE 8, exactly
    seq = _lifter(e1, 12, (60, 6, 8.0))
    loads = [lb for lb, *_ in seq]
    assert loads[:3] == [65, 65, 65] and seq[0][1:3] == (4, 9.0), seq  # stepped up, then HELD at the new load
    assert seq[3][0] == 60 and seq[3][3] == "down", seq  # three exposures with no rep and no RPE gained: a stall, reverted once
    assert set(loads[3:]) == {60} and all(m == "hold" for *_, m in seq[4:]), seq  # ... and the stalled load is not retried
    with patch.object(live_load, "held_step", lambda *a, **k: None):  # control: the rule off -> the bounce
        old = [lb for lb, *_ in _lifter(e1, 12, (60, 6, 8.0))]
    assert old[:6] == [65, 60, 65, 60, 65, 60], old
    gaining = _lifter(e1 * 1.03, 12, (60, 6, 8.0))  # a lifter 3 % stronger than the 60 x 6 says: holds and builds, never bounces
    assert [lb for lb, *_ in gaining][:4] == [65, 65, 65, 65] and "down" not in [m for *_, m in gaining], gaining


def test_a_too_heavy_step_reverts_a_stall_reverts_once_and_d7_is_unchanged_off_a_step():
    """#6015 adverse cases. (1) A step missed by MORE than the tolerance (4 reps at RPE 10 / 9.5 on a target of 8) is a too-heavy
    step: the effort fit reverts it, the same load D7 gave before. (2) Under the floor at the new load stays the two-exposure
    rule's: once holds, twice steps down. (3) A stall — `step_up_hold_exposures` exposures at the held load with no rep gained and
    no RPE shed since the first — reverts with its own reason; one where the RPE came down half a point is building and holds.
    (4) After a stall the lower load steps up again only at the top of the range one RPE under target. (5) Off a step (the load
    not just raised by the engine, raised by more than one step, or already handled at target since the raise) the D7 fit is
    exactly as before."""
    up = (60, 6, 8.0)  # the exposure that earned the step
    for rpe in (10.0, 9.5):
        d = live_load.decide(_rows((65, 4, rpe), up), 4, 6, "dumbbell", target_rpe=8)
        assert d["mode"] == "down" and round(d["kg"] / KG) == 60 and d["why"] == f"4 reps at RPE {rpe:g} last time", d
    assert live_load.decide(_rows((65, 3, 9.0), up), 4, 6, "dumbbell", target_rpe=8)["mode"] == "hold"  # under the floor once
    assert live_load.decide(_rows((65, 3, 9.0), (65, 3, 9.0), up), 4, 6, "dumbbell", target_rpe=8)["mode"] == "down"  # twice
    stall = live_load.decide(_rows((65, 4, 9.0), (65, 4, 9.0), (65, 4, 9.0), up), 4, 6, "dumbbell", target_rpe=8)
    assert stall["mode"] == "down" and round(stall["kg"] / KG) == 60 and stall["why"] == "4 reps at RPE 9, 3 sessions at this load"
    building = live_load.decide(_rows((65, 4, 8.5), (65, 4, 8.5), (65, 4, 9.0), up), 4, 6, "dumbbell", target_rpe=8)
    assert building["mode"] == "hold" and round(building["kg"] / KG) == 65, building
    two = live_load.decide(_rows((65, 4, 9.0), (65, 4, 9.0), up), 4, 6, "dumbbell", target_rpe=8)
    assert two["mode"] == "hold" and two["why"] == "new load: reps first", two  # two of three: still held
    after = _rows((60, 6, 8.0), (65, 4, 9.0), (65, 4, 9.0), (65, 4, 9.0), up)
    held = live_load.decide(after, 4, 6, "dumbbell", target_rpe=8)
    assert held["mode"] == "hold" and held["why"] == "stalled at 65 lb: 6 reps at RPE 7 first", held
    after[0]["sets"][0]["rpe"] = 7.0
    assert live_load.decide(after, 4, 6, "dumbbell", target_rpe=8)["mode"] == "up"  # stronger: retried
    assert live_load.held_step(_rows((65, 4, 9.0), (65, 5, 8.5)), 4, 6, 8, "dumbbell") is None  # not raised: D7 as before
    assert live_load.decide(_rows((65, 4, 9.0), (65, 5, 8.5)), 4, 6, "dumbbell", target_rpe=8)["mode"] == "down"
    assert live_load.held_step(_rows((70, 4, 9.0), up), 4, 6, 8, "dumbbell") is None  # two steps at once: not the engine's step
    assert live_load.held_step(_rows((65, 4, 9.0), (60, 5, 8.0)), 4, 6, 8, "dumbbell") is None  # 60 never topped: not its step
    owned = _rows((65, 4, 9.0), (65, 4, 8.5), (65, 5, 8.0), up)  # he handled 65 at target once: a later miss is a decline
    assert live_load.held_step(owned, 4, 6, 8, "dumbbell") is None
    assert live_load.decide(owned, 4, 6, "dumbbell", target_rpe=8)["mode"] == "down"  # the D7 fit, exactly as before
    with patch.dict(live_load.cfg.HEURISTICS["step_up_hold_rpe_over"], {"value": 2}):  # control: a wider tolerance holds RPE 10
        assert live_load.decide(_rows((65, 4, 10.0), up), 4, 6, "dumbbell", target_rpe=8)["mode"] == "hold"


def test_a_deload_or_red_recovery_day_is_never_a_failed_exposure_at_a_held_step():
    """#6015 adverse case: three exposures at a held step, the middle one on a recorded deload (the owner's DELOAD# word — the only
    way a deload applies) or a red-recovery hold day, is NOT a stall: the excused day neither counts nor resets the count. An
    excused newest exposure holds even above the tolerance. Controls: the same three exposures with nothing excused -> the stall reverts;
    `excused_days` reads only the dates a deload record covers."""
    up = (60, 6, 8.0)
    rows = _rows((65, 4, 9.0), (65, 4, 9.0), (65, 4, 9.0), up)
    assert live_load.decide(rows, 4, 6, "dumbbell", target_rpe=8)["mode"] == "down"  # control: nothing excused -> the stall
    d = live_load.decide(rows, 4, 6, "dumbbell", target_rpe=8, excused={rows[1]["date"]})
    assert d["mode"] == "hold" and round(d["kg"] / KG) == 65, d
    hard = _rows((65, 4, 10.0), up)
    assert live_load.decide(hard, 4, 6, "dumbbell", target_rpe=8, excused={hard[0]["date"]})["mode"] == "hold"
    records = [{"start_date": rows[1]["date"], "days": 1}]
    assert live_load.excused_days(records, {"T": rows}) == [rows[1]["date"]]
    assert live_load.excused_days(None, {"T": rows}) == []


def test_the_hold_and_build_thresholds_are_the_charters_own_numbers():
    """#6015: the two thresholds are named settings (`live_settings.HEURISTICS`) whose values are the charter's: the +1 RPE overage
    tolerance (`effort_ceilings.overage_tolerance_rpe`) and the three-exposure stall (`progression.stall_rule.consecutive_exposures`).
    A charter change that moves either one fails here until the engine's row is re-read with it."""
    from training import live_settings
    from training.training_charter import charter_value

    assert live_settings.value("step_up_hold_rpe_over") == charter_value("effort_ceilings", {})["overage_tolerance_rpe"]
    assert live_settings.value("step_up_hold_exposures") == charter_value("progression", {})["stall_rule"]["consecutive_exposures"]
