"""#5861 fix round 9 — THE CONSOLIDATION'S ACCEPTANCE: outcomes on realistic synthetic athletes, with fewer mechanisms.

The eighth red team graded simplicity D+ and found the engine's own tests pinned rules, not doses or realistic athletes. This file
pins OUTCOMES, each with a must-fail control in the same test:

  * PROGRESSION (`live_load`) — the red team's simulator athletes, ported (`scripts/progression_sim_5861.Physiological`), each fed
    8 drafted weeks: steady, gaining, over-performing, one-rep-short, alternate-week, RPE-10-always, no-RPE, -0.5 %/wk and
    -1 %/wk. No load falls >10% without step-down evidence; no 160 -> 140 -> 125 -> 160 oscillation; at most one step-down per
    lift per 3 weeks; a slump hold when the anchors decline together.
  * SHORT WEEKS (`live_volume.SHORT_WEEKS`) — 1/2/3 declared mornings are full-body mornings: 4-6 movements, 2-3 working sets per
    anchor, each priority muscle and major pattern at maintenance, inside 75 minutes.
  * THE 75-MINUTE MORNING on every public and stress fixture, both cap settings.
  * THE NOTES — no contradiction between a note and its routine (`live_session.contradictions`); 3-5 rationale lines from the
    final routine (`live_session.summary`); a priority muscle a pain flag takes to zero is said plainly.
  * SIMPLICITY RATCHETS — one settings table, the per-round mechanisms gone.

Replaces tests/test_programming_fix7_5861.py and tests/test_programming_fix8_5861.py (their mechanisms are deleted; every outcome
they held is here or in tests/test_owner_rulings_5861.py — the map is `REPLACED` below). Synthetic profiles only.
"""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "lambdas"), str(REPO / "scripts"), str(REPO / "deploy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import progression_sim_5861 as sim  # noqa: E402
import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    live_load,
    live_pain,
    live_sequence,
    live_session as ls,
    live_settings,
    live_volume,
)

PROFILES = sw.load_profiles()
FIXTURES = REPO / "tests" / "fixtures"
FIX9 = sw.load_profiles(FIXTURES / "sample_week_stress_profiles_fix9_5861.json")
FIX8 = sw.load_profiles(FIXTURES / "sample_week_stress_profiles_fix8_5861.json")
STRESS = (
    "sample_week_stress_profiles_5861",
    "sample_week_stress_profiles_rt5_5861",
    "sample_week_stress_profiles_fix7_5861",
    "sample_week_stress_profiles_fix8_5861",
    "sample_week_stress_profiles_fix9_5861",
)
A = PROFILES["a_large_deficit_experienced"]
ATHLETES = {
    "steady": {},
    "gain": {"drift": 0.005},
    "over": {"over": True},
    "one_short": {"under": True},
    "alternate": {},
    "rpe10": {"log": "rpe10"},
    "norpe": {"log": "none"},
    "decline": {"drift": -0.005},
    "drop": {"drift": -0.01},
}
REPLACED = {
    "fix7: a reset performed as written is never reset again": "test_no_athlete_loses_load_without_evidence_or_oscillates",
    "fix7: an athlete doing exactly what is prescribed never loses load": "test_no_athlete_loses_load_without_evidence_or_oscillates",
    "fix7: a genuinely stalled lift resets at most once per 3": "test_a_step_down_needs_three_grinding_sessions_at_one_load",
    "fix7: a held e1RM in a deficit holds": "test_a_systemic_decline_holds_every_load_and_trims_accessories",
    "fix7: a fast cut with every lift regressing keeps loads": "test_a_systemic_decline_holds_every_load_and_trims_accessories",
    "fix7: every muscle reaches MEV in hard sets": "ruled outcome: priority >= MEV, others >= MV (test_short_and_normal_weeks_meet_their_floors)",
    "fix7: a like-for-like swap is not capped as new": "test_owner_rulings_5861::test_ruling_10_familiar_patterns...",
    "fix7/fix8 mechanism tests (ROLE_REF, SECOND_LIFT, hard_capable, WEEK_FLOOR, PARITY, the KB slot)": "deleted with the mechanism",
    "fix8: a steady or gaining athlete never loses a heavy-day load": "test_no_athlete_loses_load_without_evidence_or_oscillates",
    "fix8: every declared morning count is restructured by coverage": "test_one_to_three_mornings_are_real_full_body_weeks",
    "fix8: every session of every fixture fits 75 minutes": "test_every_session_of_every_fixture_fits_the_75_minute_ceiling",
    "fix8: a sharp low-back flag reaches every spine-loading lift": "test_a_sharp_low_back_flag_reaches_every_spine_loading_lift",
    "fix8: sequence rules start the Monday after approval": "test_sequence_rules_start_the_monday_after_approval",
}


def _week(prof: dict, patches: dict | None = None, settings: dict | None = None) -> dict:
    with patch.dict(sw.SETTINGS, settings or {}):
        world = sw.build_world(prof, "approved")
        ps_ = [patch.object(m, a, v) for (m, a), v in (patches or {}).items()]
        for p in ps_:
            p.start()
        try:
            week = sw.generate_week(prof, "approved", world)
        finally:
            for p in ps_:
                p.stop()
    return {"world": world, "week": week, "hard": sw.hard_sets_by_muscle(week, world["lib"], world["catalog"]["movements"])}


def _run(name: str, weeks: int = 8, patches: dict | None = None) -> list[dict]:
    ps_ = [patch.object(m, a, v) for (m, a), v in (patches or {}).items()]
    for p in ps_:
        p.start()
    try:
        skip = (lambda k: k % 2 == 1) if name == "alternate" else None
        return sim.simulate(A, weeks, sim.Physiological(**ATHLETES[name]), skip=skip)
    finally:
        for p in ps_:
            p.stop()


def _windows(downs: dict) -> list:
    """(lift, weeks) with two step-downs inside 3 weeks."""
    return [(k, w) for k, w in downs.items() if any(b - a < 3 for a, b in zip(w, w[1:]))]


# ── 1. progression: the red team's athletes over 8 weeks ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(ATHLETES))
def test_no_athlete_loses_load_without_evidence_or_oscillates(name):
    rows = _run(name)
    assert sim.falls_without_evidence(rows) == {}, name
    assert sim.oscillations(rows) == {}, name
    assert _windows(sim.step_downs(rows)) == [], name
    loads = sim.role_loads(rows)
    if name == "over":  # the over-performer climbs every exposure
        assert all((s[-1] or 0) > (s[0] or 0) for (k, r), s in loads.items() if k in ("barbell_bench_press", "lat_pulldown"))
    if name in ("rpe10", "norpe"):  # unreliable RPE never collapses a lift (the red team: bench 185 -> 105 in five weeks)
        assert all(min(x for x in s if x) >= 0.94 * next(x for x in s if x) for s in loads.values() if any(s))


def test_unreliable_rpe_is_effort_unknown_and_never_a_step_down():
    """RPE 10 logged on every set (the red team: bench 185 -> 105 in five weeks) or no RPE at all is EFFORT UNKNOWN: the lift
    progresses on reps and load only and never steps down on effort. Control: the plausibility rule off -> the same record cuts."""
    row = lambda reps, rpe: {
        "date": "2026-11-0",
        "role": "upper_heavy",
        "sets": [{"kg": 100.0, "reps": reps, "rpe": rpe}] * 3,
    }  # noqa: E731
    always10 = [row(5, 10), row(5, 10), row(5, 10), row(6, 10)]
    assert live_load.effort_unknown(always10) and not live_load.step_down_due(always10)
    assert live_load.effort_unknown([row(5, None), row(6, None)])
    topped = [row(6, 10), row(5, 10)]
    assert live_load.decide(topped, 4, 6, "barbell")["mode"] == "up"  # reps reached the top: it progresses on reps alone
    with patch.object(live_load, "effort_unknown", lambda rows: False):  # control
        assert live_load.step_down_due(always10)
        assert live_load.decide(topped, 4, 6, "barbell")["mode"] == "hold"


def test_a_step_down_needs_three_grinding_sessions_at_one_load():
    kg = 100.0
    row = lambda reps, rpe, load=kg: {
        "date": "2026-11-0",
        "role": "upper_heavy",
        "sets": [{"kg": load, "reps": reps, "rpe": rpe}],
    }  # noqa: E731
    grind = [row(4, 10), row(4, 10), row(4, 10), row(6, 9)]  # newest first: three sessions under the 6 done at this load, all RPE 10
    assert live_load.step_down_due(grind)
    assert not live_load.step_down_due([row(4, 10), row(4, 9), row(4, 10), row(6, 9)])  # one set at target vetoes
    assert not live_load.step_down_due([row(4, 10), row(4, 10), row(4, 10, 105), row(6, 9)])  # a load change restarts the count
    assert not live_load.step_down_due([row(6, 10), row(6, 10), row(6, 10), row(6, 10)])  # reps held: RPE 10 alone is no evidence
    assert not live_load.step_down_due([dict(r, sets=[dict(r["sets"][0], rpe=None)]) for r in grind])  # no RPE: effort unknown
    with patch.dict(live_settings.HEURISTICS["step_down_exposures"], {"value": 1}):  # control: one session would do it
        assert live_load.step_down_due([row(4, 10), row(4, 9), row(6, 9)])
    d = live_load.decide(grind, 4, 6, "barbell")
    assert d["mode"] == "down" and kg * 0.92 <= d["kg"] < kg  # one 5% step, floored to the implement (never 10%)


def test_a_systemic_decline_holds_every_load_and_trims_accessories():
    rows = _run("drop", 6)
    held = [r["week"] for r in rows if any(ln.startswith("today: every load held") for v in r["rationale"].values() for ln in v)]
    assert held, "a -1 %/wk athlete reads as a systemic decline"
    assert sim.step_downs(rows) == {}  # held, never a cascade of cuts (the red team: six anchors -10% in one week)
    off = _run("drop", 6, {(live_load, "slump"): lambda *a, **k: None})  # control: no slump rule
    assert not any(ln.startswith("today: every load held") for r in off for v in r["rationale"].values() for ln in v)


def test_the_same_template_on_a_heavy_and_a_volume_day_is_two_lifts():
    """The owner-data ratchet (160 -> 140 -> 125 -> 160 on a volume-day pulldown): a lift is judged by its own session role."""
    rows = _run("steady", 6)
    loads = sim.role_loads(rows)
    assert ("lat_pulldown", "upper_heavy") in loads and ("lat_pulldown", "upper_volume") in loads
    assert sim.oscillations(rows) == {}
    blind = {(live_load, "same_role"): lambda rows, role, target_date, lo, hi: rows}  # control: role-blind references
    mixed = _run("steady", 6, blind)
    assert sim.role_loads(mixed) != loads


# ── 2. short weeks: real full-body mornings ──────────────────────────────────────────────────────────────────────────────────
SHORT = ("n8_one_morning_clean", "n7_two_mornings_clean", "n9_three_mornings_clean_low_steps")


@pytest.mark.parametrize("name", SHORT)
def test_one_to_three_mornings_are_real_full_body_weeks(name):
    w = _week(FIX9[name])
    days = len(FIX9[name]["days"])
    tg = live_volume.targets(w["world"]["lib"], days)
    for s in w["week"]["sessions"]:
        assert 4 <= len(s["lifts"]) <= 6, (name, s["role"], len(s["lifts"]))
        assert all(2 <= x["working_sets"] <= 3 for x in s["lifts"]), (name, s["role"], [(x["key"], x["working_sets"]) for x in s["lifts"]])
        assert float(s["lifting_minutes"]) <= 75.05, (name, s["role"])
    for mu in ("chest", "quadriceps", "back", "hamstrings"):
        assert w["hard"].get(mu, 0) >= tg[mu]["floor"], (name, mu, w["hard"].get(mu), tg[mu])
    off = _week(FIX9[name], {(live_volume, "FULL_BODY_SETS"): (1, 1)})  # control: the old guest anchors at one set -> caught
    assert any(x["working_sets"] < 2 for s in off["week"]["sessions"] for x in s["lifts"])


def test_short_and_normal_weeks_meet_their_floors():
    for mornings, name in ((5, "a_large_deficit_experienced"), (4, "e_short_week")):
        w = _week(PROFILES[name])
        tg = live_volume.targets(w["world"]["lib"], mornings)
        under = {
            m: (w["hard"].get(m, 0), t["floor"]) for m, t in tg.items() if m not in live_volume.HEADS and w["hard"].get(m, 0) < t["floor"]
        }
        assert under == {}, (name, under)
    plan = live_volume.week_plan(w["world"]["catalog"]["movements"], w["world"]["lib"], 4)
    assert plan["under"] == []
    with patch.dict(live_settings.HEURISTICS["slot_max_sets"], {"value": 2}):  # control: no slot may grow -> a floor unmet
        assert live_volume.week_plan(w["world"]["catalog"]["movements"], w["world"]["lib"], 4)["under"]


# ── 3. the 75-minute morning, every fixture, both cap settings ───────────────────────────────────────────────────────────────
def _all_profiles() -> list[tuple[str, dict]]:
    out = list(PROFILES.items())
    for fx in STRESS:
        out += list(sw.load_profiles(FIXTURES / f"{fx}.json").items())
    return out


@pytest.mark.parametrize("shared", [False, True])
def test_every_session_of_every_fixture_fits_the_75_minute_ceiling(shared):
    bad = {}
    for name, prof in _all_profiles():
        w = _week(prof, settings={"session_cap_includes_cardio": shared})
        over = [
            (s["role"], float(s["lifting_minutes"] or 0) + (float(s["cardio"].get("minutes") or 0) if shared else 0.0))
            for s in w["week"]["sessions"]
        ]
        over = [o for o in over if o[1] > 75.05]
        if over:
            bad[name] = over
        assert not any(s.get("contradictions") for s in w["week"]["sessions"]), (
            name,
            [s.get("contradictions") for s in w["week"]["sessions"]],
        )
    assert bad == {}
    if shared:
        off = _week(PROFILES["e_short_week"], {(live_volume, "time_fit"): lambda *a, **k: []})
        assert any(float(s["lifting_minutes"]) > 75.05 for s in off["week"]["sessions"]), "control: no time fit -> over the cap"


# ── 4. the notes and the rationale ───────────────────────────────────────────────────────────────────────────────────────────
def test_the_rationale_is_three_to_five_lines_from_the_final_routine():
    w = _week(A)
    for s in w["week"]["sessions"]:
        today = [ln for ln in s["rationale"] if ln.startswith("today:")]
        assert len(today) <= 5
        titles = {x["title"] for x in s["lifts"]}
        for ln in today:
            if not ln.startswith(("today: heavier: ", "today: lighter: ", "today: new to you")):
                continue
            named = ln.split(": ", 2)[-1].split(", ")
            assert all(any(n.startswith(t) for t in titles) for n in named), ln  # every lift it names is in the routine


def test_a_note_never_contradicts_its_routine():
    from types import SimpleNamespace

    blk = SimpleNamespace(
        movement_key="x", notes="RPE 8\nW set: up to 8 easy reps, find the load.", sets=[SimpleNamespace(type="normal", weight_kg=40.0)]
    )
    rx = {"exposures": [{"movement_key": "x", "live_familiar": True}], ls.MARK: {"load_guard": [{"key": "x", "mode": "down"}]}}
    assert ls.contradictions([blk], rx)  # control: a find-the-load over a written load is caught
    blk.notes = "RPE 8\nHeavier: 6 reps reached."
    assert ls.contradictions([blk], rx)  # a step down with a 'Heavier' note
    blk.notes = "RPE 8\nSame load: first time in 19 weeks."
    rx[ls.MARK]["load_guard"] = []
    assert ls.contradictions([blk], rx)  # a layoff line on a familiar pattern
    blk.notes = "RPE 8\nLighter today: 3 grinding sessions."
    rx[ls.MARK]["load_guard"] = [{"key": "x", "mode": "down"}]
    assert ls.contradictions([blk], rx) == []


def test_a_priority_muscle_a_pain_flag_takes_to_zero_is_said_plainly():
    w = _week(FIX9["n6_garage_sharp_shoulder"])
    assert w["hard"].get("chest", 0) == 0
    lines = [ln for s in w["week"]["sessions"] for ln in s["rationale"]]
    assert any(ln.startswith("today: chest 0 here by design") for ln in lines)
    assert not any("chest held" in ln for ln in lines)
    off = _week(FIX9["n6_garage_sharp_shoulder"], {(ls, "_zero_by_design"): lambda *a: []})  # control: silent zero
    assert not any(ln.startswith("today: chest 0") for s in off["week"]["sessions"] for ln in s["rationale"])


def test_a_sharp_low_back_flag_reaches_every_spine_loading_lift():
    w = _week(FIX8["x_sharp_low_back_5day"])
    keys = {x["key"] for s in w["week"]["sessions"] for x in s["lifts"]}
    assert not keys & {"deadlift_barbell", "romanian_deadlift_barbell", "squat_barbell"}
    assert w["hard"].get("quadriceps", 0) >= 8
    off = _week(FIX8["x_sharp_low_back_5day"], {(live_pain, "spine_reach"): lambda entry, f, joint: False})  # control
    assert {x["key"] for s in off["week"]["sessions"] for x in s["lifts"]} & {"deadlift_barbell", "romanian_deadlift_barbell"}


def test_sequence_rules_start_the_monday_after_approval():
    lib = {"status": "approved", "approved_on": "2026-11-18", "programming_settings": {}}
    assert live_sequence.rule_from(lib) == "2026-11-23"
    assert live_sequence.rule_from(lib | {"programming_settings": {"sequence_rule_from": "2026-12-02"}}) == "2026-11-30"
    assert live_sequence.rule_from({"status": "approved"}) is None  # control: no stamp -> from the block start


# ── 5. simplicity ratchets ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_one_settings_table_and_the_per_round_mechanisms_are_gone():
    src = {p.name: p.read_text() for p in (REPO / "lambdas" / "training").glob("live_*.py")}
    assert not [n for n, t in src.items() if "SETTINGS_DEFAULTS" in t and n != "live_settings.py"]
    assert not (REPO / "lambdas" / "training" / "live_stimulus.py").exists()
    assert not (REPO / "lambdas" / "training" / "live_progress.py").exists()
    gone = ("LOAD_POLICY", "STALL_RULE", "ALLOCATION", "PARITY", "PRIORITY_ADD", "QUAD_SLOT", "WEEK_FLOOR", "ARMS_FLOOR", "TRUNK_FLOOR",
            "CARDIO_ROOM", "SET_CAP", "TIME_FIT", "NOVEL_START", "FAMILIAR_SWAP", "KB_SLOT", "KB_FILLER")  # fmt: skip
    assert not [(n, g) for n, t in src.items() for g in gone if f"\n{g}: dict" in t or f"\n{g} = " in t]
    assert len(live_settings.SETTINGS) <= 7
    assert all(row.get("label") == "heuristic" and row.get("basis") and row.get("retune") for row in live_settings.HEURISTICS.values())


def test_a_hold_day_holds_every_load_and_stops_every_lift_at_rpe_8():
    """A strained or overreached day (two or more strain signals): every load holds and no lift grinds — RPE 8 everywhere (the
    red team's praised high-fatigue week: hard work kept, nothing past RPE 8). Control: the cap lifted -> a lift at RPE 9+."""
    w = _week(PROFILES["b_shoulder_flag_low_recovery"])
    assert all((s["fatigue"] or {}).get("state") in ("strained", "overreached") for s in w["week"]["sessions"])
    lifts = lambda wk: [
        x for s in wk["week"]["sessions"] for x in s["lifts"] if "walk" not in x["key"]
    ]  # noqa: E731 — a carry: load per hand
    assert all((sw.lift_effort(x["hevy_note"]) or 0) <= 8 for x in lifts(w))
    with patch.dict(live_settings.HEURISTICS["first_back_rpe"], {"value": 10}):
        off = _week(PROFILES["b_shoulder_flag_low_recovery"])
    assert any((sw.lift_effort(x["hevy_note"]) or 0) > 8 for x in lifts(off))


def test_a_slump_trims_about_a_third_of_each_accessory_never_an_anchor():
    """The slump's volume answer (the red team's N7 survivor): accessories lose about a third of their working sets, never under 2;
    anchors keep theirs. Control: the drop athlete's slump week serves fewer accessory sets than the same week without the trim."""
    rx = {"exposures": [
        {"kind": "anchor", "sets": [{}] * 3}, {"kind": "accessory", "sets": [{}] * 3}, {"kind": "accessory", "sets": [{}] * 4},
        {"kind": "accessory", "sets": [{}] * 2},
    ]}  # fmt: skip
    lines = live_load.slump_trim(rx)
    assert [len(e["sets"]) for e in rx["exposures"]] == [3, 2, 3, 2] and lines
    rows = _run("drop", 4)
    off = _run("drop", 4, {(live_load, "slump_trim"): lambda rx: []})
    acc = lambda rr: sum(sum(len(v) for v in r["loads"].values()) for r in rr)  # noqa: E731 — exposures served
    held = [r["week"] for r in rows if any(ln.startswith("today: every load held") for v in r["rationale"].values() for ln in v)]
    assert held
    sets = lambda rr: sum(n for r in rr for n in r["hard"].values())  # noqa: E731
    assert sets(rows) < sets(off) and acc(rows) <= acc(off)


def test_a_cut_regressing_or_capped_lift_never_leads_the_heavy_lower_day():
    """Ruling 5's lead by state (the red team's N12 survivor): a joint-flag cut, a regressing trend or an effort cap at RPE 7
    blocks the lead; a clean lift may lead. Control: the same clean exposure is never blocked."""
    from training import live_rulings

    assert live_rulings.lead_blocked({"live_load": {"pct": 10, "why": "knee flag"}}, None) == "knee flag"
    assert live_rulings.lead_blocked({}, "regressing") == "regressing"
    assert live_rulings.lead_blocked({"live_effort": 7}, None) == "effort capped"
    assert live_rulings.lead_blocked({"live_effort": 9}, "progressing") is None
