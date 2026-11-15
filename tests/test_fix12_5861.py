"""#5861 fix round 12 — the owner's rulings of 2026-11-14 and the final review's narrow fails, as OUTCOMES on SERVED synthetic
weeks and multi-week simulations, each with a must-fail control in the same test. Synthetic profiles only.

  1  75 minutes is a ceiling, never a target: the week's hard conditioning dose is the ONLY gym block; a high-fatigue week adds
     no cardio (the dose is dropped, not served easy) and its mornings end when the work is done; unknown inputs are never a gap;
  2  a 1-3 morning week follows WHICH mornings: squat and hinge loading is not stacked on consecutive days, a rest day between
     allows it, a bare count is read as consecutive and says so, and the week names the anchors it leaves out;
  3  effort by role, not RPE 9 on everything — and recovery-aware, compounds before isolation;
  4  no in-session load step on any served week (the round-11 bounded step is off and deleted);
  5  the simulator: a week not trained logs nothing; runs under the floor are counted on LOGGED reps; recovery can vary by week;
     a step-down needs fresh evidence at the new load, is capped at 10 %, and stops after two (held and flagged);
  7  every held lift says what moves it, a carry names its next-session rule, PREVIOUS from the other day is said, and the
     public weeks lint clean;
  8  a priority muscle reaches its OWN aim with first call on free minutes; sets move only at the weekly redline, and are named;
     a priority that cannot reach its aim says so and names the trade — it never takes the conditioning dose;
  E5 rollback: a live draft's rotation picks never change what the proposed path serves.
"""

from __future__ import annotations

import copy
import json
import logging
import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "lambdas"), str(REPO / "scripts"), str(REPO / "deploy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import progression_sim_5861 as sim  # noqa: E402
import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    hevy_note_grammar as g,
    live_load,
    live_program,
    live_rulings,
    live_safety,
    live_sequence,
    live_settings,
    live_shape,
    live_volume,
    variant_rotation as vr,
)

PROFILES = sw.load_profiles()
FIXTURES = REPO / "tests" / "fixtures"
A = PROFILES["a_large_deficit_experienced"]
LANDMARKS = json.loads((REPO / "config" / "training_landmarks.json").read_text())["muscles"]
POOR = {"readiness": "red", "sleep_hours": 5.1, "acwr": "danger"}
MON, TUE, WED, THU, FRI = A["days"]
STEP_WORDS = ("later sets", "RPE 7 or easier", "Set 1 at RPE", "Set 1:")
MAJOR = ("chest", "back", "shoulders", "biceps", "triceps", "quadriceps", "hamstrings", "glutes", "calves", "abs")


def _patched(patches: dict | None):
    stack = ExitStack()
    for (m, a), v in (patches or {}).items():
        stack.enter_context(patch.object(m, a, v))
    return stack


def _week(
    prof: dict, patches: dict | None = None, settings: dict | None = None, days: list | None = None, spacing: str | None = None
) -> dict:
    prof = prof | ({"days": list(days), "roles": prof["roles"][: len(days)]} if days else {}) | ({"spacing": spacing} if spacing else {})
    with patch.dict(sw.SETTINGS, settings or {}), _patched(patches):
        world = sw.build_world(prof, "approved")
        week = sw.generate_week(prof, "approved", world)
    m = sw.measure(week, world["lib"], world["catalog"]["movements"], {"muscles": LANDMARKS})
    return {"world": world, "week": week, "m": m, "hard": m["hard_sets"]}


def _lifts(week: dict, role: str | None = None) -> list[dict]:
    return [x for s in week["sessions"] if role in (None, s["role"]) for x in s["lifts"]]


def _note(week: dict, role: str, key: str) -> str:
    return next(x["hevy_note"] or "" for x in _lifts(week, role) if x["key"] == key)


def _minutes(w: dict) -> list[float]:
    return [p["morning_minutes"] for p in w["m"]["per_session"]]


def _cardio(w: dict) -> list[tuple[str, str, int]]:
    return [(s["role"], s["cardio"].get("kind"), s["cardio"].get("minutes")) for s in w["week"]["sessions"] if s["cardio"].get("key")]


def _lines(w: dict, prefix: str) -> list[str]:
    return [ln for s in w["week"]["sessions"] for ln in list(s["rationale"]) + list(s.get("live_fit") or []) if ln.startswith(prefix)]


# ── 1. 75 minutes is a ceiling ───────────────────────────────────────────────────────────────────────────────────────────────
def test_a_high_fatigue_week_adds_no_cardio_and_its_mornings_end_when_the_work_is_done():
    """Owner ruling 2026-11-14 (1): the high-fatigue week ran five mornings of 72-75 min — an easy block filled every freed
    minute. Now the week's hard conditioning dose is the ONLY gym block, and on a strained read it is DROPPED, never served
    easy: no cardio on any morning, every morning shorter than the normal week's, each anchor still 2+ sets with a hard top
    set, and no muscle with an MEV at zero hard sets. Control: the strain read hidden from the cardio fit -> a block is served."""
    normal, hf = _week(A), _week(A | POOR)
    assert _cardio(hf) == [], _cardio(hf)
    assert len(_cardio(normal)) == 1 and _lines(normal, "cardio (live): ")  # the normal week's one block, with its reason
    assert any("purpose: the week's conditioning dose" in ln for ln in _lines(normal, "cardio (live): "))
    assert all(b < a + 0.01 for a, b in zip(_minutes(normal), _minutes(hf))), (_minutes(normal), _minutes(hf))
    assert sum(_minutes(hf)) <= sum(_minutes(normal)) - 30, (_minutes(normal), _minutes(hf))  # genuinely shorter, not refilled
    for s in hf["week"]["sessions"]:
        for x in s["lifts"]:
            if str(x["tag"] or "").startswith("anchor:"):
                assert x["working_sets"] >= 2 and (sw.lift_effort(x["hevy_note"]) or 0) >= 8, (s["role"], x["key"])
    assert all(hf["hard"].get(m, 0) > 0 for m in MAJOR), hf["hard"]
    ctx = live_program.cardio_context

    def blind(ideal):  # control: the cardio fit no longer sees the strain
        out = ctx(ideal)
        return out and out | {"state": "recovered", "strain": [], "action": "maintain", "cardio_strain": False}

    assert _cardio(_week(A | POOR, {(live_program, "cardio_context"): blind})), "control: without the strain read a block is served"


def test_unknown_inputs_are_never_an_aerobic_gap_and_no_easy_block_fills_a_morning():
    """Owner ruling 2026-11-14 (1): missing step or sleep data is UNKNOWN, never evidence that aerobic work is short. With no
    steps read and no aerobic record read, no morning gets an easy block or a walk prompt; and where the record IS read and
    short with low steps, the answer is one optional walk prompt outside the gym — still no easy block. Control: the unread
    record treated as read -> the walk prompt appears."""
    unread = _week(A | {"steps_per_day": 0})
    assert [k for _r, k, _m in _cardio(unread)] in ([], ["tempo"], ["intervals"], ["hills"]), _cardio(unread)
    assert not _lines(unread, "walk (live):") and not any("min short" in ln for ln in _lines(unread, "cardio (live): "))
    short = A | {"steps_per_day": 3000, "aerobic_record": {"minutes_by_day": {}, "line": "recorded outside the gym: 0 min credited"}}
    w = _week(short)
    assert len(_lines(w, "walk (live):")) == 1  # one prompt a week, on the host morning
    assert all(k in live_program.HARD_KINDS for _r, k, _m in _cardio(w)) and len(_cardio(w)) <= 1
    aerobic = live_program.aerobic

    def read(inputs):  # control: the unread record counted as read
        return (aerobic(inputs) or {}) | {"record_read": True, "steps_per_day": 0}

    assert _lines(_week(A | {"steps_per_day": 0}, {(live_program, "aerobic"): read}), "walk (live):")


# ── 2. the declared mornings ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_short_weeks_follow_the_declared_mornings():
    """Owner ruling 2026-11-14 (2): the engine took a COUNT; it now follows WHICH mornings. Three or two consecutive mornings
    never put a spine-loading squat or hinge on the morning beside the heavy lower day (a low-spine member serves); with a rest
    day between, the guest barbell squat and RDL stay. A bare count is read as consecutive days and says so. The week line
    names the usual anchors it leaves out. Control: the declared days ignored -> the consecutive week stacks."""

    def axial(w: dict) -> list[list[str]]:
        return [a["axial"] for a in w["m"]["axial"]]

    cons3, spread3 = _week(A, days=[MON, TUE, WED]), _week(A, days=[MON, WED, FRI])
    assert axial(cons3)[0] == [] and len(axial(cons3)[1]) == 2 and axial(cons3)[2] == [], axial(cons3)
    assert "squat_barbell" in axial(spread3)[0] and "romanian_deadlift_barbell" in axial(spread3)[2], axial(spread3)
    cons2, spread2 = _week(A, days=[MON, TUE]), _week(A, days=[MON, THU])
    assert axial(cons2)[0] == [] and len(axial(cons2)[1]) == 2, axial(cons2)
    assert {"squat_barbell", "romanian_deadlift_barbell"} <= set(axial(spread2)[0]), axial(spread2)
    bare = _week(A, days=[MON, TUE, WED], spacing="undeclared")
    assert axial(bare) == axial(cons3) and "consecutive days assumed" in bare["week"]["short_week"]
    assert "consecutive days assumed" not in cons3["week"]["short_week"]
    for w in (cons2, spread2, _week(A, days=[MON])):
        assert "left out this week: " in w["week"]["short_week"] and "heavy" in w["week"]["short_week"], w["week"]["short_week"]
    for w in (cons3, spread3, cons2, spread2):
        assert all(len(s["lifts"]) >= 4 and all(x["working_sets"] >= 2 for x in s["lifts"]) for s in w["week"]["sessions"])
    for_role = live_sequence.for_role

    def blind(plan, role):  # control: which mornings they are is not read
        out = for_role(plan, role)
        return out and out | {"heavy_lower_tomorrow": False}

    off = _week(A, {(live_sequence, "for_role"): blind}, days=[MON, TUE, WED])
    assert "squat_barbell" in axial(off)[0], "control: without the declared days the squat sits the morning before the heavy day"


# ── 3. effort by role ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_effort_targets_are_by_role_and_weekly_hard_sets_do_not_fall():
    """Owner ruling 2026-11-14 (3): nearly every working set was prescribed at RPE 9. ONE role table (`effort_targets`): a
    heavy-day anchor works at RPE 8 with only its last set to 9, the deadlift stays at 8, a volume-day compound 8-9, accessories
    8-9 with the last set 9-10. Weekly hard sets per muscle are unchanged against the flat table, and double progression
    still fires at the role's working RPE. Control: the heavy row of the table flattened to 9 -> the note reads the old band."""
    w = _week(A)
    heavy = "RPE 8, last set RPE 8–9"
    assert heavy in _note(w["week"], "upper_heavy", "barbell_bench_press") and heavy in _note(w["week"], "lower_heavy", "squat_barbell")
    dl = _note(w["week"], "lower_heavy", "deadlift_barbell")
    assert sw.lift_effort(dl) == 8 and "last set" not in dl
    assert "RPE 8–9" in _note(w["week"], "upper_volume", "incline_db_press") and heavy not in _note(
        w["week"], "upper_volume", "incline_db_press"
    )
    iso = [
        x
        for x in _lifts(w["week"])
        if not str(x["tag"] or "").startswith("anchor:") and "RPE 8–9, last set RPE 9–10" in (x["hevy_note"] or "")
    ]
    assert len(iso) >= 8, len(iso)
    flat_table = dict(live_settings.value("effort_targets")) | {"heavy_compound": [9, 9]}
    with patch.dict(live_settings.HEURISTICS["effort_targets"], {"value": flat_table}):  # control: the universal target
        flat = _week(A)
    assert heavy not in _note(flat["week"], "upper_heavy", "barbell_bench_press")
    assert w["hard"] == flat["hard"], (w["hard"], flat["hard"])  # the stimulus count does not fall with the lower target
    row = lambda reps, rpe: {
        "date": "2026-11-0",
        "role": "upper_heavy",
        "sets": [{"kg": 100.0, "reps": reps, "rpe": rpe}] * 3,
    }  # noqa: E731
    heavy_e, acc_e = {"kind": "anchor", "intensity": "heavy"}, {"kind": "accessory", "intensity": "accessory"}
    assert live_load.step_rpe(heavy_e) == 8 and live_load.step_rpe(acc_e) == 9 and live_load.step_rpe(heavy_e | {"live_effort": 7}) == 7
    assert live_load.decide([row(6, 8)], 4, 6, "barbell", target_rpe=live_load.step_rpe(heavy_e))["mode"] == "up"
    held = live_load.decide([row(6, 9)], 4, 6, "barbell", target_rpe=live_load.step_rpe(heavy_e))
    assert held["mode"] == "hold" and "6 reps at RPE 8 or less, then up" in held["clause"]
    assert live_load.decide([row(15, 9)], 8, 15, "machine", target_rpe=live_load.step_rpe(acc_e))["mode"] == "up"


def test_one_strain_signal_lowers_compounds_before_isolation():
    """Recovery-aware effort: ONE strain signal (a short night) holds every compound at RPE 8 — a heavy lift's last-set allowance
    goes — while isolation keeps its last set at 9-10; two or more (a strained day) hold isolation at 8 too; an anchor's top set
    never goes under the hard-set line. Control: the same week with no strain signal keeps the heavy lift's last-set allowance."""
    one = _week(A | {"sleep_hours": 5.5})
    fat = {s["role"]: s["fatigue"] for s in one["week"]["sessions"]}
    assert all(f["state"] == "normal" and f["strain_signals"] == ["sleep"] for f in fat.values()), fat
    bench = _note(one["week"], "upper_heavy", "barbell_bench_press")
    assert sw.lift_effort(bench) == 8 and "last set" not in bench
    assert sw.lift_effort(_note(one["week"], "upper_volume", "incline_db_press")) == 8
    assert any("last set RPE 9–10" in (x["hevy_note"] or "") for x in _lifts(one["week"], "upper_heavy"))  # isolation untouched
    two = _week(A | POOR)
    assert all((sw.lift_effort(x["hevy_note"]) or 0) == 8 for x in _lifts(two["week"]) if "Farmers" not in x["title"])
    assert "last set RPE 8–9" in _note(_week(A)["week"], "upper_heavy", "barbell_bench_press")  # control: no strain, the allowance


# ── 4. no in-session step ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_no_served_week_prints_an_in_session_load_step(caplog):
    """Owner ruling 2026-11-14 (4): the in-session step-up rule is OFF. No lift note and no session block of any public served
    week carries an in-session load rule, no week reports a note contradiction, and the engine's own note lint is clean on all
    six (26 problems before this round). Control: the engine's in-session lines left in -> they are served and the lint fires."""

    def steps(week: dict) -> list[str]:
        return [
            f"{s['role']}/{x['key']}" for s in week["sessions"] for x in s["lifts"] if any(t in (x["hevy_note"] or "") for t in STEP_WORDS)
        ]

    with caplog.at_level(logging.WARNING):
        weeks = {name: _week(prof) for name, prof in PROFILES.items()}
    lint = [r.getMessage() for r in caplog.records if "hevy note lint" in r.getMessage()]
    assert lint == [], lint
    for name, w in weeks.items():
        assert steps(w["week"]) == [], (name, steps(w["week"]))
        assert sw.lint_problems(w["week"]) == [], (name, sw.lint_problems(w["week"]))
    assert not hasattr(live_load, "r3_eligible") and not hasattr(live_safety, "r3_lines")
    off = _week(A, {(live_safety, "no_step"): lambda blocks, rx: []})  # control: the in-session lines left in
    assert steps(off["week"]) and any("CONTRADICTION" in p for p in sw.lint_problems(off["week"]))


# ── 5. the simulator and the step-down limits ────────────────────────────────────────────────────────────────────────────────
def test_a_week_not_trained_logs_nothing_and_floor_runs_read_the_logged_reps():
    """Owner ruling 2026-11-14 (5): the alternate-week and layoff runs logged the skipped weeks as performed. Now a week
    `skip(k)` names is not drafted and not performed: no exposure of the athlete's record is dated in it. Runs under the floor
    are counted on LOGGED reps (what the engine sees); the true reps are reported beside. Control: no skip -> the same weeks
    hold exposures; the true-reps count differs from the logged one for a noisy logger."""
    ath = sim.Scripted(jump={3: 0.95})
    rows = sim.simulate(A, 4, ath, skip=lambda k: k == 1)
    skipped = rows[1]
    assert skipped["skipped"] and skipped["loads"] == {} and skipped["roles"] == []
    week1 = {sw._day(d, 7) for d in A["days"]}
    assert not [d for d in ath.done if d["date"] in week1]
    full = sim.Scripted()
    sim.simulate(A, 2, full)
    assert [d for d in full.done if d["date"] in week1]  # control: a trained week is in the record
    noisy = sim.Scripted(noise=[2, -2, 1, -2, 2, 0, -1, 1, -2, 2, 0, -1])
    sim.simulate(A, 4, noisy)
    assert any(d["reps"] != d["true_reps"] for d in noisy.done)
    assert sim.floor_runs(noisy) != sim.floor_runs(noisy, field="true_reps")
    honest = sim.Physiological()
    sim.simulate(A, 2, honest)
    assert all(d["reps"] == d["true_reps"] for d in honest.done)


def test_recovery_can_vary_by_week_and_a_poor_week_holds_then_releases():
    """Owner ruling 2026-11-14 (5): varying recovery. A poor week (red readiness, a short night, ACWR high) reads strained and
    holds every load; the good week after it is not strained and progression resumes — no cardio is added in the poor week.
    Control: the same run with no poor week never reads strained."""
    rows = sim.simulate(A, 4, sim.Scripted(), recovery=lambda k: POOR if k % 2 == 1 else None)
    states = [{v.split("/")[0] for v in r["fatigue"].values()} for r in rows]
    assert states[1] <= {"strained", "overreached"} and states[3] <= {"strained", "overreached"}, states
    assert not states[0] & {"strained", "overreached"} and not states[2] & {"strained", "overreached"}, states
    ups = lambda r: [ln for v in r["rationale"].values() for ln in v if ln.startswith("today: heavier")]  # noqa: E731
    assert not ups(rows[1]) and not ups(rows[3])
    flat = sim.simulate(A, 4, sim.Scripted())
    assert not any({v.split("/")[0] for v in r["fatigue"].values()} & {"strained", "overreached"} for r in flat)  # control


def test_a_second_step_down_needs_fresh_evidence_is_capped_and_stops_after_two():
    """The final review: a stalled deadlift ran 190, 190, 170, 155, 140, 125, 110, 100 — one more exposure under the floor cut it
    again, because the two-exposure count spanned the reset. Now a step-down needs two exposures under the floor AT THE NEW
    LOAD, never takes more than 10 %, and after two inside the window the lift is HELD and flagged. Control: the fresh-evidence
    rule off (the count spans the reset) -> a step-down every week."""
    rows = sim.simulate(A, 8, sim.Athlete(stalled={"deadlift_barbell"}))
    dl = [r["role_loads"].get(("deadlift_barbell", "lower_heavy")) for r in rows]
    downs = [e for e in sim.step_down_events(rows) if e["lift"].startswith("Deadlift")]
    assert len(downs) == 2 and all(e["trigger"].startswith("under ") for e in downs), downs
    assert dl[-1] >= dl[0] * 0.80 and dl[-1] == dl[-2] == dl[-3], dl  # held, not halved
    assert all(b >= a * 0.9 - 0.01 for a, b in zip(dl, dl[1:])), dl  # no single step over 10 %
    assert any("flagged, not cut again" in ln for r in rows for v in r["rationale"].values() for ln in v)
    row = lambda kg, reps: {"date": "2026-11-0", "role": "lower_heavy", "sets": [{"kg": kg, "reps": reps, "rpe": 9.5}]}  # noqa: E731
    assert live_load.decide([row(90.0, 3), row(100.0, 3), row(100.0, 3)], 4, 6, "barbell")["mode"] == "hold"  # one at the new load
    assert live_load.decide([row(90.0, 3), row(90.0, 3), row(100.0, 3)], 4, 6, "barbell")["mode"] == "down"  # two at the new load
    third = live_load.decide([row(81.0, 3), row(81.0, 3), row(90.0, 3), row(90.0, 3), row(100.0, 3)], 4, 6, "barbell")
    assert third["mode"] == "hold" and third.get("flag") and "after 2 step-downs" in third["clause"]
    deep = live_load.decide([row(100.0, 1), row(100.0, 1)], 4, 6, "barbell")
    assert deep["mode"] == "down" and 100.0 * 0.9 - 0.01 <= deep["kg"] < 100.0
    span = lambda rows_, lo, n=None: len(rows_) >= 2 and all(live_load._top(r)["reps"] < lo for r in rows_[:2])  # noqa: E731
    with patch.object(live_load, "below_floor", span), patch.dict(live_settings.HEURISTICS["step_downs_per_window"], {"value": 99}):
        off = sim.simulate(A, 6, sim.Athlete(stalled={"deadlift_barbell"}))
    assert len([e for e in sim.step_down_events(off) if e["lift"].startswith("Deadlift")]) >= 4  # control: the old cascade


# ── 7. notes ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_every_loaded_lift_says_what_moves_it_and_the_carry_names_its_next_session_rule():
    """Owner ruling 2026-11-14 (7): every note is coherent on a phone — what to load, how many, how hard, and what makes it go
    up or down. Every lift with a load on its rows carries ONE load line (heavier / same load and what moves it / lighter and
    why); a lift with none carries the "find the load" set; the carry names its start load, where the steps go and its
    next-session rule (no in-session step). Control: the round-11 quiet hold -> held lifts say nothing."""
    w = _week(A)
    heads = ("Heavier", "Lighter", "Same load: ", "Same load all sets: ", "New: replaces ")
    for s in w["week"]["sessions"]:
        wires = [e for e in s["wire"] if not any(st.get("duration_seconds") for st in e.get("sets") or [])]
        for x, e in zip(s["lifts"], wires):
            note = x["hevy_note"] or ""
            lines = [ln.strip() for ln in note.splitlines()]
            loaded = any(st.get("weight_kg") for st in e.get("sets") or [] if st.get("type") != "warmup")
            if "Farmers" in x["title"]:
                assert live_safety.CARRY_NEXT_LINE in lines and g.CARRY_STEPS_LINE in lines and g.CARRY_LINE1_RE.match(lines[0]), note
                assert g.CARRY_ADJUST_RE.match(live_safety.CARRY_NEXT_LINE) and "+10 lb" not in note
            elif loaded:
                assert sum(ln.startswith(heads) for ln in lines) == 1, (s["role"], x["key"], note)
            else:
                assert g.PICK_LOAD_OPEN_TAIL in note, (s["role"], x["key"], note)
            assert g.phone_lines("\n".join(ln for ln in lines if ln and "·" not in ln and not ln.startswith("Low energy"))) <= 5
    decide = live_load.decide

    def quiet(rows, lo, hi, eq, **k):  # control: round 11's hold with no line
        d = decide(rows, lo, hi, eq, **k)
        return d | {"clause": None} if d and d["mode"] == "hold" else d

    off = _week(A, {(live_load, "decide"): quiet})
    said = lambda wk: sum(  # noqa: E731
        1 for x in _lifts(wk) if any(ln.strip().startswith(heads) for ln in (x["hevy_note"] or "").splitlines())
    )
    assert said(off["week"]) < said(w["week"])


def test_a_previous_load_from_the_other_day_is_said():
    """Owner ruling 2026-11-14 (7): Hevy's PREVIOUS shows his last session of the template whatever its day. A volume-day row
    more than a step under a heavy-day PREVIOUS says so (and the reverse); the same exposure, a step-down or a stack with no
    fixed step says nothing extra."""
    heavy = {"date": "2026-11-10", "role": "", "sets": [{"kg": 50.0, "reps": 5, "rpe": 9.0}]}
    volume = {"date": "2026-11-06", "role": "", "sets": [{"kg": 43.0, "reps": 10, "rpe": 8.0}]}
    hold = {"kg": 43.0, "mode": "hold", "why": "reps first", "clause": "x"}
    assert live_load.previous_clause(hold, [volume], [heavy, volume], "dumbbell", "2026-11-12") == "Lighter: PREVIOUS was the heavy day."
    up = {"kg": 50.0, "mode": "hold", "why": "reps first", "clause": "x"}
    later_volume = volume | {"date": "2026-11-11"}
    assert (
        live_load.previous_clause(up, [heavy], [later_volume, heavy], "dumbbell", "2026-11-12") == "Heavier: PREVIOUS was the volume day."
    )
    assert live_load.previous_clause(hold, [volume], [volume], "dumbbell", "2026-11-12") is None  # PREVIOUS is its own exposure
    assert live_load.previous_clause(hold | {"mode": "down"}, [volume], [heavy, volume], "dumbbell", "2026-11-12") is None
    assert live_load.previous_clause(hold, [volume], [heavy, volume], "cable", "2026-11-12") is None  # a stack: no fixed step
    assert g.REASON_RE.match("Lighter: PREVIOUS was the heavy day.")


def test_a_full_body_guest_reads_its_partner_roles_history():
    """Fix round 12: a guest anchor on a full-body morning (the volume squat on the upper-heavy day of a 3-morning week) is its
    PARTNER role's lift — loaded from the lower-volume day's last set, never left to the engine's role-blind load. Control: the
    guest read under the host's role -> no same-role decision exists for it."""
    w = _week(A, days=[MON, WED, FRI])
    loads = [ln for ln in _lines(w, "load (live): Squat (Barbell)")]
    assert any("(last lower volume" in ln for ln in loads), loads
    same_role = live_load.same_role
    off = _week(
        A,
        {(live_load, "same_role"): lambda rows, role, *a: same_role(rows, "upper_heavy" if role == "lower_volume" else role, *a)},
        days=[MON, WED, FRI],
    )
    assert not any("(last lower volume" in ln for ln in _lines(off, "load (live): Squat (Barbell)"))


# ── 8. priority ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_priority_muscle_reaches_its_own_aim_and_no_arm_set_moves_for_it():
    """Owner ruling 2026-11-14 (8): a priority muscle reaches its OWN aim; it does not have to exceed the arms, and no arm set is
    cut for it. Chest and quadriceps reach their aims with first call on the free minutes; the direct curl and triceps sets are
    the same as in a run with no priority named; any set that moves does so at the weekly redline only, from a muscle that
    stays over its own aim, and the week names it. Control: no first call for the priority muscles -> chest stays under its aim."""
    w, none = _week(A), _week(A, settings={"priority_muscles": []})
    tg = live_volume.targets(w["world"]["lib"], 5)
    cat, lib = w["world"]["catalog"]["movements"], w["world"]["lib"]

    def served(week: dict) -> dict:  # every working set as served (a fill new to him runs its FIRST exposure at RPE 7)
        return live_volume.hard_sets(
            (live_volume.lib_entry(x["key"], cat, lib), x["working_sets"], None, x["key"], cat) for x in _lifts(week)
        )

    assert served(w["week"])["chest"] >= tg["chest"]["aim"] and served(w["week"])["quadriceps"] >= tg["quadriceps"]["aim"], served(
        w["week"]
    )
    assert any("Leg Extension" in x["title"] for x in _lifts(w["week"]))  # the added quadriceps sets are a low-fatigue isolation
    assert not hasattr(live_volume, "ARMS") and not hasattr(live_volume, "_aim")

    def direct(week: dict, muscle: str) -> int:
        return sum(x["working_sets"] for x in _lifts(week) if live_volume.landmark_muscle(x["key"], cat, lib) == muscle)

    from training import program_structure as ps

    template = [e for role in ps.SPLIT_ROLES for e in ps.session_prescription_for_role(role, catalog_movements=cat)["exposures"]]
    for arm in ("biceps", "triceps"):  # no template arm set is cut: the direct sets are at least the template's own
        base = sum(
            len(e["sets"]) for e in template if e["kind"] == "accessory" and live_volume.landmark_muscle(e["movement_key"], cat, lib) == arm
        )
        assert direct(w["week"], arm) >= base and direct(none["week"], arm) >= base, (arm, base, direct(w["week"], arm))
        assert w["hard"][arm] >= LANDMARKS[arm]["MEV"]
    plan = live_volume.week_plan(w["world"]["catalog"]["movements"], w["world"]["lib"], 5)
    assert sum(r["sets"] for r in plan["rows"]) <= live_volume._redline_sets()
    moved = [ln for ln in plan["lines"] if ln.startswith("moved: ")]
    assert all("stays at or over its aim" in ln for ln in moved)
    assert not any(ln.startswith("spend: time short") for ln in plan["lines"])  # no set is taken to buy a morning's minutes
    # control: the priority aim at MEV (no priority above it) -> chest and quadriceps take fewer sets
    with patch.dict(live_settings.HEURISTICS["priority_aim_share"], {"value": 0.0}):
        off = _week(A)
    assert served(off["week"])["chest"] + served(off["week"])["quadriceps"] < served(w["week"])["chest"] + served(w["week"])["quadriceps"]


def test_a_priority_that_cannot_reach_its_aim_says_so_and_never_takes_the_conditioning_dose():
    """Owner ruling 2026-11-14 (8): conditioning is never sacrificed automatically for a lower-body priority. Naming glutes as a
    priority leaves the week's conditioning dose served; when the muscle cannot reach its aim the week says so in ONE line and
    names the trade. The trade is the owner's existing setting: `hard_conditioning_doses` 0 serves no dose and gives the host
    its minutes back. Control: the same week at 0 doses has no conditioning block."""
    named = _week(A, settings={"priority_muscles": ["glutes"]})
    assert len(_cardio(named)) == 1
    cat, lib = named["world"]["catalog"]["movements"], named["world"]["lib"]
    tg = live_volume.targets(lib, 5)["glutes"]
    lines = _lines(named, "priority (live): ")
    if named["hard"].get("glutes", 0) + 1e-9 < tg["aim"]:  # fix round 14 (B23): the served count, the plan's own
        assert len(set(lines)) == 1 and "glutes" in lines[0] and any(w in lines[0] for w in ("your call", "ceiling", "new to you")), lines
    else:
        assert lines == []
    four_lib = sw.approved_library(lib, A)
    four = live_volume.week_plan(cat, four_lib, 4)  # the 4-morning week: a priority muscle under its aim says so
    prio = (four_lib.get("programming_settings") or {}).get("priority_muscles") or ()
    assert (four["priority_line"] is None) == all(four["counts"].get(m, 0) + 1e-9 >= four["targets"][m]["aim"] for m in prio)
    assert live_rulings.conditioning_hosts("lower_volume", lib | {"programming_settings": {"hard_conditioning_doses": 0}}) == []
    off = _week(A, settings={"priority_muscles": ["glutes"], "hard_conditioning_doses": 0})
    assert _cardio(off) == [] and any("hard_conditioning_doses is 0" in ln for ln in _lines(off, "cardio (live): "))


# ── the final review's narrow fails ──────────────────────────────────────────────────────────────────────────────────────────
def test_a_strained_day_introduces_no_movement_new_to_him():
    """The final review (B27): his high-fatigue week served two movements new to him. On a day whose inputs read strained, an
    accessory he has not logged in this block goes back to the movement its slot served last phase (when he logged that one) or
    is not served; the plan's fill is not added unless he has logged it. Control: the rule off -> a never-logged movement is
    served on the strained day."""

    def unlogged(w: dict) -> list[str]:
        logged = {str(x.get("template_id") or "").upper() for wk in w["world"]["record"] for x in wk["exercises"]}
        cat = w["world"]["catalog"]["movements"]
        return [
            x["key"] for x in _lifts(w["week"]) if not str(x["tag"] or "").startswith("anchor:") and sw._tid(cat, x["key"]) not in logged
        ]

    hf = _week(A | POOR)
    assert unlogged(hf) == [], unlogged(hf)
    from training import live_session as ls

    off = _week(A | POOR, {(ls, "_no_new_on_a_strained_day"): lambda *a: [], (live_volume, "apply"): _apply_without_no_new()})
    assert unlogged(off), "control: with the rule off the strained week serves a movement he has not logged"


def _apply_without_no_new():
    apply = live_volume.apply
    return lambda rx, ctx, plan: apply(rx, ctx | {"no_new": False}, plan)


def test_the_weekly_redline_and_the_cardio_machine_hold_on_pain_and_equipment_weeks():
    """The final review (B26, B31): 76-79 working sets on pain and equipment weeks, and an Elliptical served where the profile
    has none. What a morning puts back never exceeds the sets its plan gave it, and a cardio block names only a machine the gym
    has. Control: the session's set budget off -> a pain week runs past the redline."""
    fix7 = sw.load_profiles(FIXTURES / "sample_week_stress_profiles_fix7_5861.json")
    fix10 = sw.load_profiles(FIXTURES / "sample_week_stress_profiles_fix10_5861.json")
    u = next(p for n, p in fix7.items() if n.startswith("u_"))
    r1 = next(p for n, p in fix10.items() if n.startswith("r1_"))
    redline = live_volume._redline_sets()
    for prof in (u, r1):
        w = _week(prof)
        assert sum(p["working_sets"] for p in w["m"]["per_session"]) <= redline, prof["name"]
        gone = set(prof.get("unavailable_equipment") or [])
        for s in w["week"]["sessions"]:
            note = str(s["cardio"].get("note") or "")
            assert not ("elliptical" in gone and "Elliptical" in note), (prof["name"], note)
    spend = live_volume.spend
    off = _week(
        r1, {(live_volume, "spend"): lambda *a, **k: spend(*a, **(k | ({"budget": None} if "budget" in k and len(a[2]) == 1 else {})))}
    )
    assert sum(p["working_sets"] for p in off["m"]["per_session"]) > sum(p["working_sets"] for p in _week(r1)["m"]["per_session"])


def test_a_live_drafts_rotation_picks_never_change_what_the_proposed_path_serves():
    """The final review (E5, rollback): a live draft persisted its rotation picks where the proposed path reads them — after
    reverting the status the proposed week changed in three sessions. Now a live draft's picks are their own list
    (`live_ledger_writes`), recorded to `live_phase_N`, which no proposed reader matches: approve in memory, draft, record, roll
    back -> the proposed week is identical. Control: the live picks recorded where the proposed path reads -> it changes."""

    class Table:  # the ledger's update_item with `if_not_exists`, in memory
        def __init__(self, rows):
            self.rows = {r["sk"]: copy.deepcopy(r) for r in rows}

        def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):  # noqa: N803
            row = self.rows.setdefault(Key["sk"], {"sk": Key["sk"]})
            row.setdefault(ExpressionAttributeNames["#p"], ExpressionAttributeValues[":p"])
            row["block"] = int(ExpressionAttributeValues[":b"])

    def rotations(mode: str, rows: list) -> tuple[dict, list]:
        seen: list = []
        session = sw._session

        def spy(ideal, role, day, movements, cardio):
            seen.append(copy.deepcopy((ideal.inputs_snapshot or {}).get("rotation") or {}))
            return session(ideal, role, day, movements, cardio)

        world = sw.build_world(A, mode)
        with patch.object(sw, "_session", spy):
            week = sw.generate_week(A, mode, world | {"rows": rows})
        return week, seen

    def served(week: dict) -> list:
        return [(s["role"], [(x["key"], x["working_sets"], x["hevy_note"]) for x in s["lifts"]]) for s in week["sessions"]]

    clean = sw.build_world(A, "proposed")["rows"]
    before, _ = rotations("proposed", clean)
    live_week, live_rot = rotations("approved", clean)
    assert any(r.get("live_ledger_writes") for r in live_rot) and not any(r.get("ledger_writes") for r in live_rot)
    table = Table(clean)
    for r in live_rot:
        vr.record(r, table, "2026-11-16T00:00:00+00:00")
    after_rows = list(table.rows.values())
    assert any(k.startswith(vr.LIVE_PHASE_PREFIX) for r in after_rows for k in r)
    after, _ = rotations("proposed", after_rows)  # the rollback: the status is proposed again, the ledger keeps the live rows
    assert served(after) == served(before)
    lib_live = sw.approved_library(json.loads((REPO / "config" / "exercise_library.json").read_text()), A)
    assert vr.ledger_view(after_rows, {"status": "proposed"}) is after_rows  # shadow reads the rows as they are
    view = vr.ledger_view(after_rows, lib_live)  # live reads its own picks over the shadow ones
    assert not any(k.startswith(vr.LIVE_PHASE_PREFIX) for r in view for k in r)
    leaky = Table(clean)
    for r in live_rot:  # control: the live picks written where the proposed path reads them
        vr.record({"ledger_writes": r.get("live_ledger_writes") or []}, leaky, "2026-11-16T00:00:00+00:00")
    changed, _ = rotations("proposed", list(leaky.rows.values()))
    assert served(changed) != served(before)


def test_the_settings_table_carries_the_effort_roles_and_no_in_session_switch():
    rows = live_settings.HEURISTICS
    assert set(rows["effort_targets"]["value"]) == {"heavy_compound", "deadlift", "heavy_lower_other", "volume_compound", "accessory"}
    assert all(
        rows[k]["label"] == "heuristic" and rows[k]["retune"] for k in ("effort_targets", "step_down_max_pct", "step_downs_per_window")
    )
    assert "deadlift_rpe" not in rows and not [k for k in list(rows) + list(live_settings.SETTINGS) if k.startswith(("r3", "in_session"))]
    assert live_shape.aerobic_gap({"aerobic": {"walking_min_per_wk": 0, "steps_per_day": 3000}}) is None  # no record read: unknown
    assert live_shape.aerobic_gap({"aerobic": {"walking_min_per_wk": 0, "record_read": True}}) is None  # no steps read: unknown
    assert (
        live_shape.aerobic_gap({"aerobic": {"walking_min_per_wk": 0, "record_read": True, "steps_per_day": 3000}, "target_date": MON})
        == 150
    )
