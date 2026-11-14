"""#5861 fix round 11 — the tenth red team's conditions as OUTCOMES on SERVED synthetic weeks, each with a must-fail control in
the same test. Synthetic profiles only; the red team's athletes are ported as `progression_sim_5861.Scripted` (a true strength that
follows a schedule, one-off jumps, and logged rep noise).

  1  the heavy lower morning: the squat leads, the deadlift runs a notch lower and still progresses — over weeks, no ratchet;
  2  ONE performance signal: a flat lifter whose reps swing +-2 is not "strained" (<= 10 % of sessions), priority muscles at aim;
  4  priority muscles aim above MEV and get there by spending minutes, never by cutting an arm under its own aim;
  5  the one spend step: what the gym or the pain rule took goes back; consecutive short weeks rotate the free slots;
  6  a stated pain score routes only the provoking lift; the other lifts loading the joint hold at RPE 8 with the stop line;
  7  the layoff dose: 21+ days off -> the first session back starts under the last load;
  8  R3 restored in one bounded form, only where the session-to-session rule allows it;
  9  every lift note fits four phone lines;
  10 the harness, the docstring, the hip thrust in a hinge slot, the abs on a short week;
  E6 live needs status approved AND a valid approved_on; an approved library without one serves exactly what proposed serves.
"""

from __future__ import annotations

import copy
import hashlib
import json
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
    fatigue_model as fm,
    hevy_note_grammar as g,
    live_load,
    live_pain,
    live_safety,
    live_session as ls,
    live_settings,
    live_volume,
    selection_engine as se,
)

FIXTURES = REPO / "tests" / "fixtures"
PROFILES = sw.load_profiles()
FIX10 = sw.load_profiles(FIXTURES / "sample_week_stress_profiles_fix10_5861.json")
A = PROFILES["a_large_deficit_experienced"]
LANDMARKS = json.loads((REPO / "config" / "training_landmarks.json").read_text())["muscles"]
NOISE = [2, -2, 1, -2, 2, 0, -1, 1, -2, 2, 0, -1]
KG = 0.45359237


def _patched(patches: dict | None):
    stack = ExitStack()
    for (m, a), v in (patches or {}).items():
        stack.enter_context(patch.object(m, a, v))
    return stack


def _week(prof: dict, patches: dict | None = None, settings: dict | None = None, days: int | None = None) -> dict:
    prof = prof | ({"days": prof["days"][:days]} if days else {})
    with patch.dict(sw.SETTINGS, settings or {}), _patched(patches):
        world = sw.build_world(prof, "approved")
        week = sw.generate_week(prof, "approved", world)
    return {"world": world, "week": week, "hard": sw.hard_sets_by_muscle(week, world["lib"], world["catalog"]["movements"])}


def _lifts(week: dict, role: str | None = None) -> list[dict]:
    return [x for s in week["sessions"] if role in (None, s["role"]) for x in s["lifts"]]


def _sim(weeks: int, athlete, patches: dict | None = None) -> list[dict]:
    with _patched(patches):
        return sim.simulate(A, weeks, athlete)


def _strained(rows: list[dict]) -> tuple[int, int]:
    """(sessions the fatigue model read strained or overreached, sessions)."""
    hit = sum(
        1
        for r in rows
        for lines in r["rationale"].values()
        if any(ln.startswith(("fatigue (live): strained", "fatigue (live): overreached")) for ln in lines)
    )
    return hit, sum(len(r["roles"]) for r in rows)


# ── 1. the heavy lower morning over weeks ────────────────────────────────────────────────────────────────────────────────────
def test_the_heavy_lower_lifts_progress_over_weeks_with_no_ratchet():
    """The tenth red team: under the ISO-week alternation the deadlift ran 185 -> 175 -> 185 -> 165 and a squat logging 8 reps at
    RPE 6 read 'Lighter today'. Now (owner ruling 5, the simpler rule): the squat leads every week, the deadlift is a top set + one
    back-off at RPE 8 every week, both loaded from their newest same-role exposure. Over five weeks a steady lifter's heavy-day
    loads never fall and print no 'Lighter today'; a gaining lifter's capped deadlift still steps up after an easy top set.
    Control: the round-10 second-lift cap (never above its last load) -> the gaining deadlift never steps up."""
    steady = _sim(5, sim.Physiological())
    for key in ("squat_barbell", "deadlift_barbell"):
        seq = [r["role_loads"].get((key, "lower_heavy")) for r in steady]
        assert all(b >= a for a, b in zip(seq, seq[1:])), (key, seq)
    week = _week(A)["week"]
    notes = {x["key"]: x["hevy_note"] or "" for x in _lifts(week, "lower_heavy")}
    assert sw.lift_effort(notes["deadlift_barbell"]) == live_settings.value("deadlift_rpe") and sw.lift_effort(notes["squat_barbell"]) == 9
    assert not any(
        "Lighter today" in x["hevy_note"] for x in _lifts(week, "lower_heavy") if x["key"] in ("squat_barbell", "deadlift_barbell")
    )
    gain = _sim(5, sim.Scripted(schedule={k: 0.03 for k in range(1, 6)}))
    dl = [r["role_loads"].get(("deadlift_barbell", "lower_heavy")) for r in gain]
    assert dl[-1] > dl[0], dl
    decide = live_load.decide

    def capped(rows, lo, hi, eq, **k):  # control: the round-10 second lift — never above its last load
        d = decide(rows, lo, hi, eq, **k)
        if d and k.get("target_rpe", 9.0) < 9.0:
            d = d | {"kg": min(d["kg"], live_load._top(rows[0])["kg"])}
        return d

    off = _sim(5, sim.Scripted(schedule={k: 0.03 for k in range(1, 6)}), {(live_load, "decide"): capped})
    dl_off = [r["role_loads"].get(("deadlift_barbell", "lower_heavy")) for r in off]
    assert dl_off[-1] <= dl_off[0], dl_off


# ── 2. one performance signal ────────────────────────────────────────────────────────────────────────────────────────────────
def test_rep_noise_on_a_flat_lifter_is_not_strain_and_priority_muscles_keep_their_aim():
    """The tenth red team: a flat lifter whose reps swing +-2 spent 37 of 50 sessions in 'reduce', chest and quadriceps cut under
    MEV — rep noise voted twice (a strength vote AND an effort-drift vote on one series). Now ONE performance read
    (`fatigue_model.declined`, median + two exposures + a 5 % band) feeds ONE vote (the systemic slump): <= 10 % of sessions
    strained, chest and quadriceps at or over MEV every week. Control: the round-10 reads (best-before, and two votes from one
    series) -> most sessions strained and a priority muscle under MEV."""
    rows = _sim(10, sim.Scripted(noise=NOISE))
    hit, n = _strained(rows)
    assert hit <= 0.10 * n, (hit, n)
    assert all(r["hard"].get(m, 0) >= LANDMARKS[m]["MEV"] for r in rows for m in ("chest", "quadriceps"))
    real = fm._systemic

    def two_votes(*a):
        out = [s for s in real(*a) if s["signal"] != "strength"]
        reg = [t for t, s in a[6].items() if s.get("trend") == "regressing"]
        return out + [
            fm._signal("strength", "strain" if reg else "ok", "", None),
            fm._signal("effort_drift", "strain" if reg else "ok", "", None),
        ]

    best = lambda e1: len(e1) > 2 and all(v < max(e1[:-2]) * 0.95 for v in e1[-2:])  # noqa: E731
    off = _sim(10, sim.Scripted(noise=NOISE), {(fm, "declined"): best, (fm, "_systemic"): two_votes})
    hit_off, _n = _strained(off)
    prio = lambda rr: sum(r["hard"].get("chest", 0) + r["hard"].get("quadriceps", 0) for r in rr)  # noqa: E731
    assert hit_off > 0.5 * n and prio(off) < prio(rows)


# ── 4. priority above MEV, never by cutting an arm ────────────────────────────────────────────────────────────────────────────
def test_priority_muscles_aim_above_mev_and_naming_others_raises_them():
    """The tenth red team: 'priority' meant MEV + 1 (chest 9 while back 14), reached by cutting the arms; naming back + glutes
    changed nothing for them. Now the served full week holds chest and quadriceps OVER MEV and the arms at or over their own MEV;
    naming back + glutes raises both. Control (the red team's M7): the priority aim at MEV with no arm reference -> fewer
    chest + quadriceps sets."""
    base = _week(A)
    h = base["hard"]
    assert all(h[m] > LANDMARKS[m]["MEV"] for m in ("chest", "quadriceps")), h
    assert all(h[m] >= LANDMARKS[m]["MEV"] for m in ("biceps", "triceps")), h
    other = _week(A, settings={"priority_muscles": ["back", "glutes"]})["hard"]
    lib = json.loads((REPO / "config" / "exercise_library.json").read_text())
    named = live_volume.targets(lib | {"programming_settings": {**lib["programming_settings"], "priority_muscles": ["back", "glutes"]}}, 5)
    assert all(other[m] >= named[m]["aim"] > LANDMARKS[m]["MEV"] for m in ("back", "glutes")), (other, named)
    assert other["back"] + other["glutes"] > h["back"] + h["glutes"], (other, h)
    with patch.dict(live_settings.HEURISTICS["priority_aim_share"], {"value": 0.0}):
        flat = _week(A, {(live_volume, "ARMS"): ()})["hard"]
    assert flat["chest"] + flat["quadriceps"] < h["chest"] + h["quadriceps"], (flat, h)


# ── 5. the one spend step ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_what_the_gym_took_goes_back_through_the_one_spend_step():
    """The garage week (c): the band pull-up is gated (ruling #3), the row family loses its biceps credit, a curl slot cannot be
    served — the one spend step puts biceps back to MEV in that morning's free minutes, from reviewed movements the gym serves.
    Control: the session's spend step off -> biceps under MEV."""
    c = _week(PROFILES["c_equipment_limited"])
    assert c["hard"]["biceps"] >= LANDMARKS["biceps"]["MEV"], c["hard"]
    off = _week(PROFILES["c_equipment_limited"], {(live_volume, "spend_session"): lambda *a: []})
    assert off["hard"]["biceps"] < LANDMARKS["biceps"]["MEV"], off["hard"]


def _logging_athlete():
    """The Hevy-like athlete: every served lift logged (an unloaded crunch too), so the weekly memory sees what was trained."""
    from training import routine_generator as rg

    cat = rg._load_json("movement_catalog.json")["movements"]

    def perform(session, day, role):
        w = sim.Athlete().perform(session, day, role)
        have = {x["name"] for x in w["exercises"]}
        for lift in session["lifts"]:
            if lift["key"] not in have and lift.get("working_sets"):
                sets = [{"type": "normal", "weight_kg": 0, "reps": 12, "rpe": 8.0}] * int(lift["working_sets"])
                w["exercises"].append(
                    {"name": lift["key"], "template_id": sw._tid(cat, lift["key"]) or lift["key"], "notes": "", "sets": sets}
                )
        return w

    return perform


def _short_run(days: int, weeks: int = 4, patches: dict | None = None) -> list[dict]:
    p0 = A | {"days": A["days"][:days]}
    out = []
    with _patched(patches):
        world = sw.build_world(p0, "approved")
        for k in range(weeks):
            p = sim._shift(p0, k)
            world["profile"] = world["profile"] | {"days": p["days"], "as_of": p["as_of"]}
            wk = sw.generate_week(world["profile"], "approved", world, perform=_logging_athlete())
            world["record"] = list(world["record"]) + list(wk["performed"])
            hs = sw.hard_sets_by_muscle(wk, world["lib"], world["catalog"]["movements"])
            out.append(hs | sw.delt_heads(wk, world["lib"], world["catalog"]["movements"]))
    return out


def test_consecutive_short_weeks_rotate_the_free_slots_in_the_served_weeks():
    """The tenth red team: four 2-morning weeks served identical sessions with calves 0 every week; four 3-morning weeks served
    the side delts never. Now the one spend step breaks ties by the muscle trained longest ago (the weekly memory), in the SERVED
    weeks: at 2 and 3 mornings calves and side delts each get work inside four weeks, and the 2-morning weeks are not all the
    same. Control: no memory -> four identical 2-morning weeks."""
    for days in (2, 3):
        weeks = _short_run(days)
        for m in ("calves", "side_delts"):
            assert any(w.get(m, 0) > 0 for w in weeks), (days, m, weeks)
        if days == 2:
            assert len({json.dumps(w, sort_keys=True) for w in weeks}) > 1
    same = _short_run(2, patches={(live_volume, "last_trained"): lambda *a: {}})
    assert len({json.dumps(w, sort_keys=True) for w in same}) == 1


def test_squat_and_hinge_never_load_the_spine_three_mornings_running():
    """The tenth red team: a 3-morning week on consecutive days ran squat, squat + deadlift, RDL. A full-body morning's guest
    hinge after a spine-loading day takes a low-spinal-load member (`live_program.axial_yesterday`). Control: off -> the RDL."""
    keys = {x["key"] for x in _lifts(_week(A, days=3)["week"], "upper_volume")}
    assert "romanian_deadlift_barbell" not in keys
    from training import live_program

    off = _week(A, {(live_program, "axial_yesterday"): lambda *a: []}, days=3)
    assert "romanian_deadlift_barbell" in {x["key"] for x in _lifts(off["week"], "upper_volume")}


# ── 6. pain: route the provoking lift only ──────────────────────────────────────────────────────────────────────────────────
def test_a_stated_pain_score_routes_only_the_provoking_lift():
    """The tenth red team (r5: garage, hip 4/10 on the split squat, knee 2/10 on the squat): quads 0, glutes 0 and a 16-minute
    morning. Now the provoking lift alone is routed; the squat and deadlift hold at RPE <= 8 with the stop line; every morning is
    at least `min_session_minutes` or says why. Control: the round-10 reach (group + HIGH stress) -> fewer quad and glute sets."""
    w = _week(FIX10["r5_garage_hip_knee"])
    assert w["hard"].get("quadriceps", 0) >= LANDMARKS["quadriceps"]["MEV"] and w["hard"].get("glutes", 0) > 0, w["hard"]
    for x in _lifts(w["week"], "lower_heavy"):
        if x["key"] in ("squat_barbell", "deadlift_barbell"):
            assert (sw.lift_effort(x["hevy_note"]) or 9) <= 8 and "stop this lift" in x["hevy_note"], x
    floor = live_settings.value("min_session_minutes")
    assert all(s["lifting_minutes"] >= floor or any("a short morning" in ln for ln in s["rationale"]) for s in w["week"]["sessions"])
    real = live_pain.hit
    wide = _week(
        FIX10["r5_garage_hip_knee"],
        {(live_pain, "hit"): lambda en, e, flags, ctx: real(en, e, [f | {"severity": None} for f in flags], ctx)},
    )
    assert wide["hard"].get("quadriceps", 0) + wide["hard"].get("glutes", 0) < w["hard"]["quadriceps"] + w["hard"]["glutes"]


# ── 7. the layoff dose ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_long_layoff_returns_under_the_last_load_a_short_one_at_it():
    """The tenth red team: a 38-day layoff returned at the last load and ground under the floor. 10-20 days: RPE 8 at the last load
    (owner ruling #10); 21+ days: `long_layoff_pct` under it, floored to the implement. Control: the threshold out of reach -> the
    last load."""
    rows = [{"date": "2026-10-01", "role": "upper_heavy", "sets": [{"kg": 100.0, "reps": 5, "rpe": 8.0}]}]
    short = live_load.decide(rows, 4, 6, "barbell", hold="first session back", layoff_days=14)
    assert short["mode"] == "hold" and short["kg"] == 100.0
    long = live_load.decide(rows, 4, 6, "barbell", hold="first session back", layoff_days=30)
    assert long["mode"] == "down" and 100.0 * 0.90 <= long["kg"] <= 100.0 * 0.95 and "30 days off" in long["clause"]
    with patch.dict(live_settings.HEURISTICS["long_layoff_days"], {"value": 99}):
        assert live_load.decide(rows, 4, 6, "barbell", hold="first session back", layoff_days=30)["kg"] == 100.0
    world = sw.build_world(A, "approved")  # served: the same record, the week drafted five weeks on (35 days off)
    later = A | {"days": [sw._day(d, 35) for d in A["days"]], "as_of": sw._day(A["as_of"], 35)}
    world["profile"] = world["profile"] | {"days": later["days"], "as_of": later["as_of"]}
    week = sw.generate_week(later, "approved", world)
    first = next(s for s in week["sessions"] if s["role"] == "upper_heavy")
    assert any("first session back after" in (x["hevy_note"] or "") and "Lighter today" in x["hevy_note"] for x in first["lifts"])


# ── 8. R3, bounded ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_r3_rides_only_where_the_session_to_session_rule_allows_it():
    """The owner's 2026-10-27 R3 in-session rule, restored in ONE bounded form (pending his confirmation): 'Set 1 at RPE 7 or
    easier -> one load step on later sets', never down, on a straight-set lift the load model does not hold for a reason, step
    down, cap or treat as new. The served week carries it and contradicts nothing; a pain-held lift never carries it. Control: R3
    on every lift -> the contradiction lint fires."""
    a = _week(A)["week"]
    r3 = [x for x in _lifts(a) if "Set 1 at RPE 7 or easier" in (x["hevy_note"] or "")]
    assert r3 and not any(s.get("contradictions") for s in a["sessions"])
    heavy = [x for s in a["sessions"] if s["role"] in ("upper_heavy", "lower_heavy") for x in s["lifts"] if x["tag"].endswith(":heavy")]
    assert heavy and not any("Set 1 at RPE 7" in (x["hevy_note"] or "") for x in heavy)  # a top set + back-offs is not "later sets"
    r5 = _week(FIX10["r5_garage_hip_knee"])["week"]
    assert not any("stop this lift" in (x["hevy_note"] or "") and "Set 1 at RPE 7" in x["hevy_note"] for x in _lifts(r5))
    from training import session_block as sb

    def everywhere(blocks, rx):  # control: the R3 line on every loaded lift, eligible or not
        for b in blocks:
            if any(getattr(st, "weight_kg", None) for st in b.sets):
                b.notes = sb.add_reason(b.notes, live_safety.r3_text([5.0, False]))
        return []

    off = _week(FIX10["r5_garage_hip_knee"], {(live_safety, "r3_lines"): everywhere})
    assert any(s.get("contradictions") for s in off["week"]["sessions"])


# ── 9. notes ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_every_lift_note_fits_four_phone_lines():
    """The tenth red team: 58 notes past 4 phone lines at 5 am. Each lift's own note is held to `LIFT_MAX_LINES` (a form cue goes
    first; effort, load reason and stop line stay). Control: the cap off -> a note over 4 lines on the pain-flagged week."""
    from training import session_block as sb

    def over(w):
        return [x["key"] for x in _lifts(w["week"]) if g.phone_lines(sb.split(x["hevy_note"] or "")[1].strip()) > g.LIFT_MAX_LINES]

    for prof in (A, FIX10["r5_garage_hip_knee"], PROFILES["b_shoulder_flag_low_recovery"]):
        assert over(_week(prof)) == [], prof["name"]
    off = _week(PROFILES["b_shoulder_flag_low_recovery"], {(live_safety, "cap_lines"): lambda blocks: []})
    assert over(off)


# ── 10. the harness, the slot, the short week ─────────────────────────────────────────────────────────────────────────────
def test_a_movement_swapped_into_a_slot_takes_its_own_rep_range():
    """The tenth red team (f): a hip thrust swapped into the deadlift slot ran at 4-6. It now runs its own range. Control: off ->
    the slot's 4-6."""
    f = _week(PROFILES["f_high_fatigue_poor_sleep"])["week"]
    hip = [x for x in _lifts(f, "lower_heavy") if "hip_thrust" in x["key"]]
    assert hip and all(x["reps"] != "4-6" for x in hip)
    off = _week(PROFILES["f_high_fatigue_poor_sleep"], {(ls, "_reps_follow_the_movement"): lambda rx, ctx: []})["week"]
    assert any(x["reps"] == "4-6" for x in _lifts(off, "lower_heavy") if "hip_thrust" in x["key"])


def test_the_harness_logs_volume_day_anchors_inside_their_range():
    """The tenth red team: the sample-week record logged every anchor at 6 reps, so a volume day's 8-12 squat read 'under the
    floor' and printed 'Lighter today' on a progressing profile. Live worlds now log a volume-day anchor inside its range.
    Control: the old 6 reps -> a 'Lighter today' on a volume day."""
    w = _week(A)["week"]
    assert not any("Lighter today" in (x["hevy_note"] or "") for s in w["sessions"] if "volume" in s["role"] for x in s["lifts"])
    with patch.dict(sw.ROLE_ANCHOR_REPS, {"upper_volume": 6, "lower_volume": 6}):
        off = _week(A)["week"]
    assert any("Lighter today" in (x["hevy_note"] or "") for s in off["sessions"] if "volume" in s["role"] for x in s["lifts"])


def test_a_short_week_halves_the_abs_and_the_four_day_week_holds_the_arms():
    """Ruling #8: ~4 direct ab sets a week, halved on a 1-3 morning week (the high-fatigue halving was inert and is gone — a
    strained day's trim is the fatigue model's). Ruling 3: the 4-morning week holds shoulders, biceps and triceps at MEV,
    served. Controls: the ab setting doubled -> the short week's aim doubles; the 4-day hold off -> an arm under MEV."""
    lib = json.loads((REPO / "config" / "exercise_library.json").read_text())
    assert live_volume.targets(lib, 3)["abs"]["aim"] == 2 and live_volume.targets(lib, 5)["abs"]["aim"] == 4
    doubled = copy.deepcopy(lib) | {"programming_settings": {**lib["programming_settings"], "abs_direct_sets_per_week": 8}}
    assert live_volume.targets(doubled, 3)["abs"]["aim"] == 4
    e = _week(PROFILES["e_short_week"])
    assert all(e["hard"].get(m, 0) >= LANDMARKS[m]["MEV"] for m in ("shoulders", "biceps", "triceps")), e["hard"]
    with patch.object(live_volume, "FOUR_DAY_MEV", ()):
        off = _week(PROFILES["e_short_week"])
    assert any(off["hard"].get(m, 0) < LANDMARKS[m]["MEV"] for m in ("shoulders", "biceps", "triceps")), off["hard"]


# ── E6: live needs the approval day ───────────────────────────────────────────────────────────────────────────────────────────
def _served(prof: dict, lib_edit) -> str:
    world = sw.build_world(prof, "proposed", prior="pools")
    lib_edit(world["lib"])
    week = sw.generate_week(prof, "proposed", world)  # the harness's own branches as proposed; the ENGINE reads the library
    keep = [{k: v for k, v in s.items() if k not in ("fatigue", "live_fit", "carry_m", "contradictions")} for s in week["sessions"]]
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:16]


def test_an_approved_library_without_its_approval_day_serves_exactly_what_proposed_serves():
    """Coordinator E6 (owner ruling #4 of fix round 8: the sequence rules start the Monday after final approval, never
    retroactive): live mode needs BOTH `status: approved` AND a valid `approved_on`. Approved with no stamp (or an unparseable
    one) serves byte-for-byte what proposed serves; with a stamp it is live and the rules start the Monday after. Control: the
    round-10 switch (status alone) -> the stampless approved library serves a different (live) week."""
    prof = PROFILES["a_large_deficit_experienced"]

    def approve(stamp):
        def edit(lib):
            lib["status"] = "approved"
            lib.pop("approved_on", None)
            if stamp:
                lib["approved_on"] = stamp

        return edit

    proposed = _served(prof, lambda lib: None)
    assert _served(prof, approve(None)) == proposed and _served(prof, approve("2026-13-01")) == proposed
    assert _served(prof, approve("2026-01-02")) != proposed
    lib = {"status": "approved", "approved_on": "2026-11-18"}
    from training import live_sequence

    assert se.mode(lib) == se.MODE_LIVE and live_sequence.rule_from(lib) == "2026-11-23"
    from training import exercise_library as xl

    assert any(
        "approved_on" in e
        for e in xl.validate(json.loads((REPO / "config" / "exercise_library.json").read_text()) | {"status": "approved"})
    )
    with patch.object(se, "approved_stamp", lambda lib: "2026-01-02"):  # control: status alone switches live
        assert _served(prof, approve(None)) != proposed
