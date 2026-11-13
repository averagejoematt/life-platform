#!/usr/bin/env python3
"""sample_weeks_5861.py — a FULL program week from the integrated engine, in LIVE mode, for synthetic profiles (#5861 L6).

WHAT IT DOES. For each profile in `tests/fixtures/sample_week_profiles_5861.json` it builds a synthetic world (a Hevy
record over the prior rotation phase, the rotation ledger, readiness, sleep, steps, equipment, pain and discomfort), flips
an IN-MEMORY copy of `config/exercise_library.json` to `approved` (the committed file is never touched, so the selection
engine runs its live policy), and drafts every session of the week through the real draft path:

  * `full_body_session.full_body_routines` — anchors, the live selection's accessories, the live session fit and the
    fatigue model, loads from the synthetic record, warm-ups and the composed Hevy notes;
  * `mcp.draft_standing_constraint.cardio_block` — the day's cardio block from the charter's menu;
  * `hevy_compiler.to_create_body` — the routine as it would be written to Hevy (the notes as rendered).

Then it measures the week (session minutes by the #5799 model, exercises per session, weekly hard sets per muscle against
`config/training_landmarks.json`, redundant axial fatigue, novelty, cardio placement) and renders it as markdown.

DETERMINISTIC AND OFFLINE: no clock, no AWS, no Hevy. Every input is injected; the same fixture gives byte-identical
output. `--profile-file` reads a profile from a file OUTSIDE the repo (the owner's private run writes only to a path
the caller names, never the repo).

    python3 scripts/sample_weeks_5861.py                      # every profile, markdown to stdout
    python3 scripts/sample_weeks_5861.py --profile a_large_deficit_experienced
    python3 scripts/sample_weeks_5861.py --mode proposed      # the same world through today's (shadow) path
    python3 scripts/sample_weeks_5861.py --json               # the measured week as JSON
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

PROFILES_PATH = REPO / "tests" / "fixtures" / "sample_week_profiles_5861.json"
ISSUE = "#5861"
HISTORY_WEEKS = 3  # the prior rotation phase (weeks 7-9 of block 2) is the synthetic record the live policy reads
LANDMARK_OF = {
    "front_delts": "shoulders",
    "side_delts": "shoulders",
    "rear_delts": "shoulders",
    "obliques": "abs",
    "quadriceps_rectus_femoris": "quadriceps",
    "gastrocnemius": "calves",
    "soleus": "calves",
}
"""Library target -> the volume-landmark muscle it counts toward (config/training_landmarks.json has 11 muscles)."""
SECONDARY_CREDIT = 0.5  # the fatigue model's own fractional-set convention (fatigue_model.THRESHOLDS, heuristic)
SYNTHETIC_LOAD_LB = {"barbell": 175, "machine": 120, "cable": 65, "dumbbell": 50, "kettlebell": 53, "other": 70}
"""Invented starting loads for the synthetic record (no person's numbers), by catalog equipment, in 5-lb implement steps."""
LB_PER_KG = 2.20462


# ── the profile and its synthetic world ──────────────────────────────────────
def load_profiles(path: Path | None = None) -> dict[str, Any]:
    raw = json.loads((path or PROFILES_PATH).read_text())
    out = {}
    for name, p in raw["profiles"].items():
        out[name] = copy.deepcopy(raw["defaults"]) | p | {"name": name, "as_of": raw["as_of"], "position": raw["position"]}
    return out


def _day(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


SETTINGS: dict[str, Any] = {}
"""`--set key=value`: library `programming_settings` applied to the IN-MEMORY library only (live_program.SETTINGS_DEFAULTS), so
both values of an owner-choice setting can be shown side by side; the committed file is never touched."""


def approved_library(lib: dict[str, Any], profile: dict[str, Any], status: str = "approved") -> dict[str, Any]:
    """An in-memory copy with the live switch flipped and the profile's missing equipment marked unavailable."""
    out = copy.deepcopy(lib)
    out["status"] = status
    if SETTINGS:
        out["programming_settings"] = {**(out.get("programming_settings") or {}), **SETTINGS}
    items = (out.get("gym_inventory") or {}).get("items") or {}
    for eid in profile.get("unavailable_equipment") or []:
        items.setdefault(eid, {})["home_gym"] = {"state": "unavailable", "source": f"synthetic profile {profile['name']}"}
    return out


_TITLE_TID: dict[str, str] = {}


def _tid(catalog: dict[str, Any], key: str) -> str | None:
    """The catalog entry's Hevy template id, else (a title-only entry, ADR-069) the library template of the same title."""
    hint = (catalog.get(key) or {}).get("hevy_template_id_hint")
    if hint:
        return str(hint).upper()
    if not _TITLE_TID:
        lib = json.loads((REPO / "config" / "exercise_library.json").read_text())
        _TITLE_TID.update(
            {str(e.get("title") or "").lower(): str(e["template_id"]).upper() for e in lib["movements"].values() if e.get("template_id")}
        )
    return _TITLE_TID.get(str((catalog.get(key) or {}).get("title") or "").lower())


def _trend_for(profile: dict[str, Any], key: str, kind: str, role: str) -> str:
    over = profile.get("trend_overrides") or {}
    return str(over.get(key) or over.get(f"*{kind}_{role}*") or profile.get("trend") or "progressing")


def _sets(load_lb: int, trend: str, week: int, kind: str) -> list[dict[str, Any]]:
    """Three working sets for one synthetic exposure: progressing adds a 5-lb step a week, stalled repeats, regressing
    drops two steps a week with fewer reps. Loads are 5-lb implement steps, stored in kg as Hevy stores them."""
    reps = 6 if kind == "anchor" else 10
    if trend == "progressing":
        lb, r, rpe = load_lb + 5 * week, reps, 8.0
    elif trend == "stalled":
        lb, r, rpe = load_lb, reps, 8.5
    else:
        lb, r, rpe = load_lb - 10 * week, reps - week, 9.0
    return [{"type": "normal", "weight_kg": round(lb / LB_PER_KG, 3), "reps": max(3, r), "rpe": rpe} for _ in range(3)]


def _note(profile: dict[str, Any], key: str, last: bool) -> str:
    for row in (profile.get("discomfort") or []) + (profile.get("pain") or []):
        if row.get("movement") == key and last:
            return str(row.get("note") or "")
    return ""


def synthetic_record(profile: dict[str, Any], served: dict[str, list[tuple[str, str]]], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """The prior phase's Hevy record: every role on its weekday, `served` = {role: [(catalog key, kind)]}, the profile's
    trends, its discomfort/pain notes on the last two exposures, its recent hard cardio, and its adherence."""
    start = _day(profile["as_of"], -7 * HISTORY_WEEKS)
    planned = [(w, i, role) for w in range(HISTORY_WEEKS) for i, role in enumerate(profile["defaults_roles"])]
    keep = 10 if profile.get("sessions_last_14d") is None else int(profile["sessions_last_14d"])  # #5861 FIX8: 0 is a layoff
    recent = [x for x in planned if x[0] >= HISTORY_WEEKS - 2]
    # an adherence dip misses the END of the week first (late-week sessions slip), latest week first
    by_slip = sorted(recent, key=lambda x: (-x[1], -x[0]))
    drop = {(w, i) for w, i, _ in by_slip[: max(0, len(recent) - keep)]}
    out = []
    for w, i, role in planned:
        if (w, i) in drop:
            continue
        day = _day(start, 7 * w + i)
        exercises = []
        for key, kind in served.get(role) or []:
            tid = _tid(catalog, key)
            if not tid:
                continue
            load = SYNTHETIC_LOAD_LB.get(str((catalog.get(key) or {}).get("equipment")), 70)
            note = _note(profile, key, w >= HISTORY_WEEKS - 2)
            sets = _sets(load, _trend_for(profile, key, kind, role), w, kind)
            exercises.append({"name": catalog[key]["title"], "template_id": tid, "notes": note, "sets": sets})
        out.append(_workout(day, role, exercises))
    _with_cardio(out, profile, start)
    return out


def _workout(day: str, role: str, exercises: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "date": day,
        "source_workout_id": f"synthetic-{day}-{role}",
        "title": role,
        "start_time": f"{day}T14:00:00Z",
        "end_time": f"{day}T15:10:00Z",
        "exercises": exercises,
    }


def _with_cardio(record: list[dict[str, Any]], profile: dict[str, Any], start: str) -> None:
    """The profile's hard cardio in the last 7 days, as timed bike blocks at RPE 7.5 on the last week's sessions."""
    hard = int(profile.get("hard_cardio_minutes_7d") or 0)
    last = [w for w in record if w["date"] >= _day(profile["as_of"], -7)]
    for n, w in enumerate(last):
        minutes = hard // max(1, len(last)) + (hard % max(1, len(last)) if n == 0 else 0)
        if minutes:
            w["exercises"].append(
                {"name": "Cycling", "template_id": "D8F7F851", "notes": "", "sets": [{"duration_seconds": minutes * 60, "rpe": 7.5}]}
            )


def history_index(record: list[dict[str, Any]], catalog: dict[str, Any] | None = None, as_of: str | None = None) -> dict:
    """`exercise_history.load_history_indexes()[0]`'s shape, built from the synthetic record (most recent first). An
    experienced profile has also trained, months ago, every catalog movement the catalog records sessions for: one older
    synthetic exposure each, so only a truly new movement reads "find the load" (as it would on a real year of history)."""
    idx: dict[str, list[dict[str, Any]]] = {}
    old = _day(as_of, -120) if as_of else None
    for key, c in (catalog or {}).items():
        tid = _tid(catalog or {}, key)
        if old and tid and int(c.get("sessions") or 0) > 0 and c.get("hevy_type") == "weight_reps":
            lb = SYNTHETIC_LOAD_LB.get(str(c.get("equipment")), 70)
            idx[tid] = [
                {
                    "date": old,
                    "sets": [{"weight_kg": round(lb / LB_PER_KG, 3), "reps": 10, "rpe": 8.0}],
                    "top_weight_kg": round(lb / LB_PER_KG, 3),
                }
            ]
    for w in record:
        for ex in w["exercises"]:
            sets = [{"weight_kg": s["weight_kg"], "reps": s["reps"], "rpe": s.get("rpe")} for s in ex["sets"] if s.get("reps")]
            if sets:
                idx.setdefault(ex["template_id"], []).append(
                    {"date": w["date"], "sets": sets, "top_weight_kg": max(s["weight_kg"] for s in sets)}
                )
    for rows in idx.values():
        rows.sort(key=lambda r: r["date"], reverse=True)
    return idx


def overlay(profile: dict[str, Any], lib: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any] | None:
    """A synthetic private overlay: a pain-class flag on each pain movement (#5806's classed source). None = no overlay."""
    from training import exercise_library as xl

    pains = profile.get("pain") or []
    if not pains:
        return None
    per = {}
    for row in pains:
        tid = _tid(catalog, row["movement"])
        if tid:
            per[tid] = {"note_signals": {"pain_flag": True, "joint_discomfort": 1}}
    return {"pain_source": xl.PAIN_SOURCE_ID, "per_template": per}


def walk_minutes_7d(profile: dict[str, Any]) -> float:
    """The read aerobic minutes a draft caller passes (#4410), for the synthetic profile: its steps over the incidental 5,000 a
    day at 100 steps a minute (`cardio_model`'s own walking-dose heuristic), over 7 days."""
    return float(sum(max(0, n - 5000) / 100 for n in steps_by_day(profile).values()))


def steps_by_day(profile: dict[str, Any]) -> dict[str, int]:
    return {_day(profile["as_of"], -n): int(profile.get("steps_per_day") or 0) for n in range(1, 8)}


# ── the offline harness ──────────────────────────────────────────────────────
@contextlib.contextmanager
def offline(lib: dict[str, Any], hidx: dict[str, Any], weight_lb: float, as_of: str, ov: dict[str, Any] | None) -> Iterator[None]:
    """Every read the draft path makes, answered from the injected world; restored on exit."""
    from unittest.mock import patch

    from training import (
        exercise_library as xl,
        full_body_session as fbs,
        routine_generator as rg,
        selection_engine as se,
        training_charter as tc,
    )

    weights = {_day(as_of, -n): float(weight_lb) for n in range(0, 15)}
    saved_cache = dict(se._LIB_CACHE)
    env = {k: os.environ.pop(k) for k in (tc.PRIVATE_ENV_VAR, xl.PRIVATE_ENV_VAR) if k in os.environ}
    patches = [
        patch.object(tc, "_from_s3", lambda key: None),
        patch.object(xl, "_overlay_from_local", lambda: None),
        patch.object(xl, "_overlay_from_s3", lambda: None),
        patch.object(se, "load_overlay_failsoft", lambda: ov),
        patch.object(rg, "_load_note_indexes", lambda *a, **k: (hidx, weights, {}, {})),
        patch.object(fbs, "_carry_stride", lambda d: None),
    ]
    se._LIB_CACHE.clear()
    se._LIB_CACHE.update(lib=lib, at=float("inf"))
    try:
        for p in patches:
            p.start()
        yield
    finally:
        for p in patches:
            p.stop()
        se._LIB_CACHE.clear()
        se._LIB_CACHE.update(saved_cache)
        os.environ.update(env)


def _entry(role: str, week: int, block: int, n: int, prev: dict[str, Any] | None) -> dict[str, Any]:
    from training import program_structure as ps

    return {
        "session_role": role,
        "week": week,
        "block": block,
        "source": "session_sequence",
        "position_label": f"W{week} S{n}",
        "session_in_week": n,
        "archetype": ps.SESSION_TEMPLATES[role]["archetype"],
        "advanced_by": prev,
    }


def _inputs(profile: dict[str, Any], day: str, record: list[dict[str, Any]], rows: list[dict[str, Any]]) -> Any:
    from training import routine_generator as rg

    acwr = {"safe": "safe", "caution": "caution", "danger": "high"}.get(str(profile.get("acwr")), "safe")  # the cron's live map
    inp = rg.GeneratorInputs(
        target_date=day,
        recovery_tier=str(profile.get("readiness") or "yellow"),
        acwr_flag=acwr,
        block_workouts=record,
        rotation_rows=rows,
        z2_minutes_7d=walk_minutes_7d(profile),
    )
    setattr(inp, "sleep_hours", profile.get("sleep_hours"))
    setattr(inp, "steps_by_day", steps_by_day(profile))  # the cron's live input (steps_resolver), into cardio_model.cardio_load
    setattr(inp, "weights_by_day", weights_by_day(profile, day))  # #5861 FIX6: the advisory loss-rate ceiling's weigh-ins (ruling 11)
    if profile.get("aerobic_record"):
        setattr(inp, "aerobic_record", profile["aerobic_record"])  # #5861 FIX6: recorded outside-the-gym minutes (ruling 12)
    return inp


def weights_by_day(profile: dict[str, Any], day: str, days: int = 35) -> dict[str, float]:
    """Synthetic weigh-ins for the 35 days before `day`: the profile's `bodyweight_lb` today, falling `weekly_loss_pct` (% of
    bodyweight a week, default 0.8) — a straight line, so the ceiling's verdict is read off a known rate."""
    bw, pct = float(profile.get("bodyweight_lb") or 0), float(profile.get("weekly_loss_pct", 0.8))
    if not bw:
        return {}
    return {_day(day, -n): round(bw * (1 + pct / 100 * n / 7), 1) for n in range(1, days + 1)}


def _layer(profile: dict[str, Any], day: str) -> dict[str, Any]:
    """A synthetic recent-aerobic layer: the profile's steps as weight-bearing hours over the last 48 h (100 steps a minute)."""
    hours = round(2 * max(0, int(profile.get("steps_per_day") or 0) - 5000) / 100 / 60, 1)
    days = [_day(day, -1), day]
    return {
        "state": "read",
        "window": {"start": days[0], "end": day},
        "totals": {"weight_bearing_hr_48h": hours, "walks_over_75_min_48h": 0},
        "days": {d: {"walk_minutes": 60} for d in days},
        "walk_days": days,
    }


def _cardio(ideal: Any, profile: dict[str, Any], day: str, cardio_index: dict[str, Any]) -> dict[str, Any]:
    from training import cardio_cues, standing_constraints

    from mcp import draft_standing_constraint as dsc

    c = standing_constraints.active_constraint(day)
    constraint = ({**c, "stop_list": None, "memory_read": "not_read (synthetic)"}) if c else None
    from training import live_program

    live = live_program.cardio_context(ideal)  # the draft path's own live context (gate_draft), None in shadow
    try:
        block, pick = dsc.cardio_block(
            day,
            getattr(ideal, "archetype", "") or "",
            constraint,
            layer=_layer(profile, day),
            cardio_index=cardio_index,
            previous=cardio_cues.previous_of(ideal, day),
            live=live,
        )
    except Exception as e:  # noqa: BLE001 — reported in the week, never a lost sample
        return {"block": None, "error": f"{type(e).__name__}: {e}"}
    if live is not None:
        ideal.rationale = list(ideal.rationale or []) + list((pick or {}).get("live") or [])
        from training.live_shape import walk_note

        walk_note(ideal, (pick or {}).get("live"))  # gate_draft's own step (#5861 FIX4)
    if block is not None:
        ideal.exercises.append(block)
        dsc._refresh_session_shape(ideal)
        tid = "D8F7F851" if block.movement_key == "cycling" else "243710DE"
        cardio_index.setdefault(tid, []).insert(
            0,
            {
                "date": day,
                "name": block.movement_key,
                "note": "",
                "served_kind": (pick or {}).get("menu", {}).get("kind"),
                "duration_sec": block.sets[0].duration_seconds,
            },
        )
    return {"block": block, "pick": (pick or {}).get("menu")}


def _phase_one_picks(lib: dict[str, Any], catalog: dict[str, Any], profile: dict[str, Any]) -> dict[str, str]:
    """The live selection's picks for the PRIOR phase (week 7, empty ledger): what the synthetic record trained."""
    from training import selection_engine as se, selection_live as sl, variant_rotation as vr

    pos = vr.position({"week": profile["position"]["week"] - 3, "block": profile["position"]["block"]})
    policy = sl.build_policy(lib, position=pos, rows=[], block_workouts=None, as_of=profile["as_of"], gate_eval=None)
    sel = se.select_week(pos, copy.deepcopy(catalog), lib, None, rows=[], missing=[], policy=policy)
    return {s["slot_id"]: (s.get("pick") or {}).get("catalog_key") or s["incumbent"] for s in sel["slots"]}


def _phase_one_pools(catalog: dict[str, Any], profile: dict[str, Any]) -> dict[str, str]:
    """The #5075 pools' variants for the PRIOR phase — independent of the library and the selection, so a world built
    from them is the same before and after any library or catalog change (the no-live-change digests use it)."""
    from training import variant_rotation as vr

    entry = {"week": profile["position"]["week"] - 3, "block": profile["position"]["block"], "session_role": "upper_heavy"}
    base = vr.plan(entry, copy.deepcopy(catalog), role="*", rows=[], ledger_state="injected")
    return {s["slot_id"]: s["variant"] for s in base["slots"]}


def _prior_served(picks: dict[str, str], catalog: dict[str, Any], roles: list[str]) -> dict[str, list[tuple[str, str]]]:
    from training import program_structure as ps, variant_rotation as vr

    out = {}
    for role in roles:
        variants = {s["incumbent"]: picks.get(s["slot_id"]) for s in vr.slots() if s["role"] == role}
        rx = ps.session_prescription_for_role(role, catalog_movements=catalog, accessory_variants={k: v for k, v in variants.items() if v})
        out[role] = [(e["movement_key"], e["kind"]) for e in rx["exposures"] if e.get("movement_key")]
    return out


def _ledger(picks: dict[str, str], block: int) -> list[dict[str, Any]]:
    from training import variant_rotation as vr

    return [
        {"sk": vr.ledger_sk(block, sid), "block": block, "phase_1": {"variant": v, "weeks": [1, 3]}} for sid, v in sorted(picks.items())
    ]


def build_world(profile: dict[str, Any], mode: str = "approved", prior: str = "live") -> dict[str, Any]:
    """The synthetic world for one profile: library (switch flipped in memory), catalog, record, ledger, overlay. `prior`:
    what the record trained last phase — the live selection's picks (`live`) or the #5075 pools (`pools`)."""
    from training import routine_generator as rg

    catalog = rg._load_json("movement_catalog.json")
    lib = approved_library(json.loads((REPO / "config" / "exercise_library.json").read_text()), profile, status="approved")
    profile = profile | {"defaults_roles": list(_all_roles())}
    picks = _phase_one_picks(lib, catalog["movements"], profile) if prior == "live" else _phase_one_pools(catalog["movements"], profile)
    record = synthetic_record(profile, _prior_served(picks, catalog["movements"], list(_all_roles())), catalog["movements"])
    lib["status"] = mode
    return {
        "profile": profile,
        "lib": lib,
        "catalog": catalog,
        "record": record,
        "rows": _ledger(picks, profile["position"]["block"]),
        "overlay": overlay(profile, lib, catalog["movements"]),
    }


def _all_roles() -> tuple[str, ...]:
    from training import program_structure as ps

    return tuple(ps.SPLIT_ROLES)


# ── one week ──────────────────────────────────────────────────────────────────
def generate_week(
    profile: dict[str, Any], mode: str = "approved", world: dict[str, Any] | None = None, perform: Any = None
) -> dict[str, Any]:
    """Every session of the profile's week, drafted through the real path (module doc). Pure over the fixture. `perform`
    (#5861 FIX7, `scripts/progression_sim_5861.py`): `(session, day, role) -> workout` records each drafted session as
    performed (the prescription as written) instead of `_performed`; the week's performed rows come back as `performed`."""
    from training import full_body_session as fbs, routine_generator as rg
    from training.program_seam import resolve_week_grid

    world = world or build_world(profile, mode)
    p, catalog = world["profile"], world["catalog"]
    landmarks = rg._load_json("training_landmarks.json")
    rw = resolve_week_grid(rg._load_json)
    record = list(world["record"])
    sessions, cardio_index, prev = [], _cardio_index(record), None
    hidx = history_index(record, catalog["movements"], p["as_of"])
    roles, short_line, plan = list(p["roles"]), None, None
    if mode == "approved":  # #5861 FIX5: the PRODUCTION week plan (`live_sequence`, the cron's sequence reads the same one)
        from training import live_sequence

        days = len(p["days"])
        live_roles, plan = live_sequence.week_roles(days, live_sequence.monday_of(p["days"][0]), record, world["lib"])
        roles = live_roles if (plan or days < len(_all_roles())) else roles
        short_line = (plan or {}).get("line") or (
            f"short week (slide): {days} of {len(_all_roles())} sessions — the sequence slides" if days < len(_all_roles()) else None
        )
    with offline(world["lib"], hidx, p["bodyweight_lb"], p["as_of"], world["overlay"]):
        for n, (role, day) in enumerate(zip(roles, p["days"][: len(roles)]), start=1):
            entry = _entry(role, p["position"]["week"], p["position"]["block"], n, prev)
            if plan:
                from training import live_sequence

                entry["live_week"] = live_sequence.for_role(plan, role)  # what the cron's entry carries (live_sequence.serve)
            inp = _inputs(p, day, record, world["rows"])
            out = fbs.full_body_routines(inp, entry, rw.week, landmarks, catalog, rw, [], block_workouts=record)
            ideal = out[0]
            cardio = _cardio(ideal, p, day, cardio_index)
            sessions.append(_session(ideal, role, day, catalog["movements"], cardio))
            done = (
                perform(sessions[-1], day, role)
                if perform
                else _performed(ideal, day, role, hidx, catalog["movements"], mode == "approved")
            )
            record.append(done)  # the next morning's draft reads this session as done
            prev = {"session_role": role, "date": day, "title": role, "was": "synthetic"}
    out = {"profile": p["name"], "label": p.get("label"), "story": p.get("story"), "mode": mode, "sessions": sessions}
    from training import cardio_model

    recorded = (p.get("aerobic_record") or {}).get("minutes_by_day") or None  # #5861 FIX6 (ruling 12): recorded minutes only
    out["steps_credit"] = cardio_model._walking_dose(steps_by_day(p), recorded)  # steps reported, never credited
    out |= {"performed": record[len(world["record"]) :]} if perform else {}
    return out | ({"short_week": short_line} if short_line else {})


def _performed(
    ideal: Any, day: str, role: str, hidx: dict[str, list[dict[str, Any]]], catalog: dict[str, Any], live: bool = False
) -> dict[str, Any]:
    """The drafted session as performed (synthetic): each lift's working sets at its last synthetic load and the bottom of its
    rep range, RPE 8 — so the week's later drafts see it in the record (adherence, the trend, the 7-day sets)."""
    from training import warmup_sets

    exercises = []
    for b in ideal.exercises:
        tid = _tid(catalog, str(b.movement_key)) or ""
        last = (hidx.get(tid) or [{}])[0].get("top_weight_kg")
        n = warmup_sets.working_set_count(b.sets)
        reps = next((getattr(s, "rep_range_start", None) for s in b.sets if getattr(s, "rep_range_start", None)), None)
        if tid and last and reps and n:
            top = lift_effort(getattr(b, "notes", None)) if live else None
            rpe = min(8.0, top) if top else 8.0  # #5861 FIX7: a lift capped under RPE 8 is logged at its cap (the week floor reads it)
            exercises.append(
                {
                    "name": b.movement_key,
                    "template_id": tid,
                    "notes": "",
                    "sets": [{"type": "normal", "weight_kg": last, "reps": reps, "rpe": rpe}] * n,
                }
            )
    return _workout(day, role, exercises)


def _cardio_index(record: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    for w in record:
        for ex in w["exercises"]:
            secs = sum(int(s.get("duration_seconds") or 0) for s in ex["sets"])
            if secs and not any(s.get("reps") for s in ex["sets"]):
                idx.setdefault(ex["template_id"], []).append({"date": w["date"], "name": ex["name"], "note": "", "duration_sec": secs})
    for rows in idx.values():
        rows.sort(key=lambda r: r["date"], reverse=True)
    return idx


def _session(ideal: Any, role: str, day: str, movements: dict[str, Any], cardio: dict[str, Any]) -> dict[str, Any]:
    from training import hevy_compiler, warmup_sets

    snap = ideal.inputs_snapshot or {}
    rx = snap.get("session_prescription") or {}
    from training import live_balance, session_block
    from training.routine_title import format_why_note

    why = session_block.why_note_for(ideal, format_why_note(ideal))  # the draft path's own WHY line (hevy_routine_cron)
    if RESOLVER["mode"] == "legacy":  # the base tree's simplified lookup: what the no-live-change pins were computed with
        resolve = live_balance.template_resolver(lambda k: str((movements.get(k) or {}).get("hevy_template_id_hint") or k))
    else:
        resolve = cron_resolver(movements)  # #5861 FIX4: the nightly job's lookup (hevy_template_cache), offline
    body = hevy_compiler.to_create_body(ideal, resolve, why_note=why)
    wire_notes = [e.get("notes") or "" for e in body["routine"]["exercises"]]  # branchless: the IR's exercises, in order
    lifts = []
    for b, wire_note in zip(ideal.exercises, wire_notes):
        if str(b.rationale_tag or "").startswith("cardio:"):
            continue
        title = (movements.get(b.movement_key) or {}).get("title") or b.movement_key
        lifts.append(
            {
                "key": b.movement_key,
                "title": title,
                "tag": b.rationale_tag,
                "working_sets": warmup_sets.working_set_count(b.sets),
                "warmup_sets": len(b.sets) - warmup_sets.working_set_count(b.sets),
                "reps": _reps(b.sets),
                "superset": getattr(b, "superset_id", None),
                "hevy_note": wire_note,
            }
        )
    blk = cardio.get("block")
    return {
        "role": role,
        "day": day,
        "title": ideal.title,
        "lifts": lifts,
        "lifting_minutes": (snap.get("session_shape") or {}).get("lifting_minutes"),
        "rx_minutes": (rx.get("session_minutes") or {}).get("lifting_minutes"),
        "fatigue": rx.get("fatigue"),
        "live_fit": (rx.get("live_session") or {}).get("lines"),
        "cardio": (
            {"key": blk.movement_key, "minutes": blk.sets[0].duration_seconds // 60, "note": blk.notes, **(cardio.get("pick") or {})}
            if blk is not None
            else {"error": cardio.get("error")}
        ),
        "rationale": list(ideal.rationale),
        "selection": [ln for ln in ideal.rationale if ln.startswith("selection:")],
        # a carry's distance-typed sets (his steps in the distance box) — rendered, never part of the served digest
        "carry_m": {
            b.movement_key: int(getattr(b.sets[-1], "distance_meters", 0) or 0)
            for b in ideal.exercises
            if getattr(b.sets[-1] if b.sets else None, "distance_meters", None)
        },
        "wire": body["routine"]["exercises"],
    }


STRICT_LINT_CODES = ("L1", "L6", "L12")
"""#5861 FIX7: the note-lint rules the live sample week treats as BLOCKING (`lint_problems`, `--strict-lint`, the acceptance test):
a banned phrase (L1) and exercise 1 opening without its effort-bearing session line (L6 / L12 — the lower-heavy squat note the
sixth red team found). The other rules are reported, not blocking, until their pre-existing proposed-mode findings are paid down."""


def lint_problems(week: dict[str, Any], rules: tuple[str, ...] = STRICT_LINT_CODES) -> list[str]:
    """The note linter (`hevy_note_lint.lint_wire`) over every session's compiled wire: the problems in `rules`."""
    from training import hevy_note_lint

    out = []
    for s in week["sessions"]:
        res = hevy_note_lint.lint_wire({"routine": {"title": s["title"], "exercises": s["wire"]}})
        out += [f"{s['role']}: {ln}" for ln in res.lines() if ln.split(" ", 1)[0] in rules]
    return out


RESOLVER: dict[str, str] = {"mode": "cron"}
"""`cron` (default): the compiled wire uses the nightly job's template lookup (`cron_resolver`). `legacy`: the base tree's own
simplified lookup — `served_digest` uses it, because its pins were computed against the base tree's harness (an apples-to-apples
proof that the SERVED draft did not move; the resolver is a harness component, not the draft)."""


def cron_resolver(movements: dict[str, Any]) -> Any:
    """The nightly job's movement -> Hevy template lookup (`hevy_routine_cron`: `live_balance.template_resolver(
    hevy_template_cache.resolve_movement)`), offline: the S3 cache it reads is replaced by what `reconcile_custom` would have
    cached for a title-only catalog entry (the library template of the same title, `_tid`), the catalog by this world's, and its
    cache write-back is a no-op. A movement the lookup cannot map RAISES, as it does in the cron (the fourth red team: the old
    resolver wrote a title-only entry's catalog KEY as its template id on the sample wire)."""
    from unittest.mock import patch

    from training import hevy_template_cache as htc, live_balance

    cache = {
        "version": 1,
        "movements": {
            k: {"hevy_template_id": _tid(movements, k), "source": "title (offline reconcile_custom)"}
            for k, c in movements.items()
            if not c.get("hevy_template_id_hint") and _tid(movements, k)
        },
    }

    def resolve(key: str) -> str:
        with (
            patch.object(htc, "_load_cache", lambda: copy.deepcopy(cache)),
            patch.object(htc, "_load_catalog", lambda: {"movements": movements}),
            patch.object(htc, "_write_s3_json", lambda *a, **k: None),
        ):
            return htc.resolve_movement(key)

    return live_balance.template_resolver(resolve)


def _reps(sets: list[Any]) -> str:
    work = [s for s in sets if getattr(s, "type", None) != "warmup"]
    if not work:
        return ""
    s = work[0]
    lo, hi = getattr(s, "rep_range_start", None), getattr(s, "rep_range_end", None)
    if lo:
        return f"{lo}-{hi}" if hi and hi != lo else str(lo)
    if getattr(s, "reps", None):
        return str(s.reps)
    return f"{(getattr(s, 'duration_seconds', None) or 0) // 60} min" if getattr(s, "duration_seconds", None) else ""


# ── the measures ─────────────────────────────────────────────────────────────
def _lib_entry(lib: dict[str, Any], catalog: dict[str, Any], key: str) -> dict[str, Any]:
    from training import selection_engine as se

    lid = se.key_index(lib, catalog)["to_lib"].get(key)
    return (lib.get("movements") or {}).get(lid) or {}


def sets_by_muscle(week: dict[str, Any], lib: dict[str, Any], catalog: dict[str, Any]) -> dict[str, float]:
    """Weekly hard sets per landmark muscle: the movement's library target 1.0, each secondary 0.5 (the fatigue model's
    convention). A carry, cardio or control movement with no muscle target counts nowhere."""
    out: Counter = Counter()
    for s in week["sessions"]:
        for lift in s["lifts"]:
            t = _lib_entry(lib, catalog, lift["key"]).get("target") or {}
            prim = LANDMARK_OF.get(str(t.get("primary")), str(t.get("primary") or "unplaced"))
            out[prim] += lift["working_sets"]
            for sec in t.get("secondary") or []:
                m = LANDMARK_OF.get(str(sec), str(sec))
                if m != prim:
                    out[m] += lift["working_sets"] * SECONDARY_CREDIT
    return {k: round(v, 1) for k, v in sorted(out.items())}


def trunk_sets(week: dict[str, Any], lib: dict[str, Any], catalog: dict[str, Any]) -> int:
    """Working sets of trunk-STABILITY work that targets no ab muscle directly (a carry, an anti-movement drill): the trunk
    work the program's design counts beside the direct ab sets (`program_structure` lower_volume: the carry's core sets)."""
    n = 0
    for s in week["sessions"]:
        for lift in s["lifts"]:
            e = _lib_entry(lib, catalog, lift["key"])
            tf = str(e.get("trunk_function") or "")
            if (tf.startswith("anti_") or tf == "loaded_stabilisation") and (e.get("target") or {}).get("primary") != "abs":
                n += lift["working_sets"]
    return n


def landmark_verdicts(sets: dict[str, float], landmarks: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for m, lm in (landmarks.get("muscles") or {}).items():
        n = float(sets.get(m, 0.0))
        v = "below MEV" if n < lm["MEV"] else ("over MRV" if n > lm["MRV"] else ("over MAV" if n > lm["MAV"] else "MEV-MAV"))
        out[m] = {"sets": n, "MEV": lm["MEV"], "MAV": lm["MAV"], "MRV": lm["MRV"], "verdict": v}
    return out


def axial_days(week: dict[str, Any], lib: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Spine-loading lifts per session by THE one definition (`live_balance.spine_loading`, #5861 FIX3 — the stacking rule and
    the acceptance gates read the same one; this generator used to count every free-weight squat/hinge, a dumbbell lunge too)."""
    from training.live_balance import spine_loading

    out = []
    for s in week["sessions"]:
        hits = [lift["key"] for lift in s["lifts"] if spine_loading(_lib_entry(lib, catalog, lift["key"]))]
        out.append({"day": s["day"], "role": s["role"], "axial": hits})
    return out


def measure(week: dict[str, Any], lib: dict[str, Any], catalog: dict[str, Any], landmarks: dict[str, Any]) -> dict[str, Any]:
    sets = sets_by_muscle(week, lib, catalog)
    per_session = [
        {
            "role": s["role"],
            "exercises": len(s["lifts"]),
            "working_sets": sum(x["working_sets"] for x in s["lifts"]),
            "lifting_minutes": s["lifting_minutes"],
            "cardio": s["cardio"].get("key"),
            "cardio_kind": s["cardio"].get("kind"),
            "cardio_minutes": s["cardio"].get("minutes"),
            "morning_minutes": round(float(s["lifting_minutes"] or 0) + float(s["cardio"].get("minutes") or 0), 1),
        }
        for s in week["sessions"]
    ]
    blocks = [int(s["cardio"].get("minutes") or 0) for s in week["sessions"]]
    keys = [x["key"] for s in week["sessions"] for x in s["lifts"]]
    return {
        "trunk_sets": trunk_sets(week, lib, catalog),
        "per_session": per_session,
        "sets_by_muscle": sets,
        "landmarks": landmark_verdicts(sets, landmarks),
        "axial": axial_days(week, lib, catalog),
        "repeats": {k: n for k, n in Counter(keys).items() if n > 1},
        "new_this_week": sorted({x["key"] for s in week["sessions"] for x in s["lifts"] if "New:" in (x["hevy_note"] or "")}),
        "effort_conflicts": _effort_conflicts(week),
        "session_effort_conflicts": _session_effort_conflicts(week),
        "aerobic": {
            "structured_min": sum(blocks),
            "blocks_20_plus": sum(1 for b in blocks if b >= 20),
            "steps_credit_min_per_wk": (week.get("steps_credit") or {}).get("moderate_min_per_wk"),
            "steps_credit_source": (week.get("steps_credit") or {}).get("source"),
            "steps_per_day": (week.get("steps_credit") or {}).get("steps_per_day"),
        },
        "hard_sets": hard_sets_by_muscle(week, lib, catalog),
    }


HARD_RPE = 8
"""#5861 FIX6: a working set prescribed at RPE >= 8 (the top of its effort line) is a HARD set for the weekly count."""


def lift_effort(note: str | None) -> float | None:
    """The top of a lift's prescribed effort: its own effort line (`RPE a–b ...`), else the session line (`... · RPE a–b`)."""
    import re

    lines = [ln.strip() for ln in str(note or "").splitlines()]
    own = next((ln for ln in lines if ln.startswith("RPE")), None) or next((ln for ln in lines if "· RPE" in ln), None)
    m = re.search(r"RPE (\d+(?:\.\d+)?)(?:[–-](\d+(?:\.\d+)?))?", own or "")
    return float(m.group(2) or m.group(1)) if m else None


def hard_sets_by_muscle(week: dict[str, Any], lib: dict[str, Any], catalog: dict[str, Any]) -> dict[str, float]:
    """Weekly HARD sets (prescribed at RPE >= HARD_RPE) per landmark muscle, primary 1.0 and secondary 0.5 (`sets_by_muscle`)."""
    out: Counter = Counter()
    for s in week["sessions"]:
        for lift in s["lifts"]:
            top = lift_effort(lift["hevy_note"])
            if top is None or top < HARD_RPE:
                continue
            t = _lib_entry(lib, catalog, lift["key"]).get("target") or {}
            prim = LANDMARK_OF.get(str(t.get("primary")), str(t.get("primary") or "unplaced"))
            out[prim] += lift["working_sets"]
            for sec in t.get("secondary") or []:
                m = LANDMARK_OF.get(str(sec), str(sec))
                if m != prim:
                    out[m] += lift["working_sets"] * SECONDARY_CREDIT
    return {k: round(v, 1) for k, v in sorted(out.items())}


def _effort_conflicts(week: dict[str, Any]) -> list[str]:
    """Lifts whose note states more than one effort target (#5861 FIX3 guard, `live_balance.effort_targets`)."""
    from training.live_balance import effort_targets

    return [f"{s['role']}: {x['key']}" for s in week["sessions"] for x in s["lifts"] if len(effort_targets(x["hevy_note"])) > 1]


def _redline() -> int:
    from training.live_shape import week_redline

    return week_redline()


def _session_effort_conflicts(week: dict[str, Any]) -> list[str]:
    """The session line against every big lift's own effort, across the session (#5861 FIX4, `live_safety.big_lift_conflicts`)."""
    from types import SimpleNamespace

    from training.live_safety import big_lift_conflicts

    out = []
    for s in week["sessions"]:
        blocks = [SimpleNamespace(movement_key=x["key"], notes=x["hevy_note"], rationale_tag=x["tag"]) for x in s["lifts"]]
        out += [f"{s['role']}: {c}" for c in big_lift_conflicts(blocks)]
    return out


# ── markdown ──────────────────────────────────────────────────────────────────
def render(week: dict[str, Any], m: dict[str, Any]) -> str:
    lines = [f"### {week['label']} — mode `{week['mode']}`", "", f"_{week['story']}_", ""]
    if week.get("short_week"):
        lines += [f"_{week['short_week']}_", ""]
    for s, ps_ in zip(week["sessions"], m["per_session"]):
        lines.append(
            f"**{s['title']}** — {ps_['exercises']} exercises, {ps_['working_sets']} working sets, ~{s['lifting_minutes']} lifting min "
            + (
                f"+ cardio {s['cardio'].get('key')} {s['cardio'].get('kind') or ''} {s['cardio'].get('minutes') or ''} min"
                if s["cardio"].get("key")
                else "+ no cardio block"
            )
        )
        for x in s["lifts"]:
            ss = f" (superset {x['superset']})" if x["superset"] else ""
            reps = x["reps"] or (f"{s['carry_m'][x['key']]} m" if (s.get("carry_m") or {}).get(x["key"]) else "")
            lines.append(f"- {x['title']}: {x['working_sets']} x {reps}{ss} — Hevy note: {_oneline(x['hevy_note'])}")
        if s["cardio"].get("note"):
            lines.append(f"- cardio note: {_oneline(s['cardio']['note'])}")
        fat = s.get("fatigue") or {}
        if fat:
            lines.append(f"- fatigue: {fat.get('state')} / {fat.get('action')}, sets removed {fat.get('sets_removed')}")
        for ln in live_lines(s):
            lines.append(f"- live: {ln}")
        lines.append("")
    lines.append("| muscle | sets/wk | hard sets (RPE 8+) | MEV | MAV | MRV | verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    for mus, v in m["landmarks"].items():
        hard = (m.get("hard_sets") or {}).get(mus, 0)
        lines.append(f"| {mus} | {v['sets']} | {hard} | {v['MEV']} | {v['MAV']} | {v['MRV']} | {v['verdict']} |")
    extra = {k: v for k, v in m["sets_by_muscle"].items() if k not in m["landmarks"]}
    if extra:
        lines.append("")
        lines.append("Other targets (no landmark): " + ", ".join(f"{k} {v}" for k, v in extra.items()))
    lines.append("")
    lines.append("Spine-loading lifts by day: " + "; ".join(f"{a['role']}: {', '.join(a['axial']) or '-'}" for a in m["axial"]))
    lines.append("Morning minutes (lifting + cardio): " + "; ".join(f"{p['role']}: {p['morning_minutes']}" for p in m["per_session"]))
    a = m["aerobic"]
    lines.append(
        f"Aerobic: structured {a['structured_min']} min ({a['blocks_20_plus']} block(s) of 20+ min) + recorded credit "
        f"~{a['steps_credit_min_per_wk']} moderate min/wk ({a['steps_credit_source']}); steps ~{a.get('steps_per_day')}/day "
        "reported as activity, never credited (ruling 12)"
    )
    lines.append(f"Repeated movements: {m['repeats'] or 'none'}; new this week: {', '.join(m['new_this_week']) or 'none'}")
    lines.append(f"Notes with more than one effort target: {', '.join(m['effort_conflicts']) or 'none'}")
    lines.append(f"Session lines contradicting a big lift: {', '.join(m['session_effort_conflicts']) or 'none'}")
    total = sum(p["working_sets"] for p in m["per_session"])
    lines.append(f"Working sets this week: {total} (redline {_redline()})")
    return "\n".join(lines) + "\n"


LIVE_PREFIXES = (
    "swapped (live)",
    "skipped (live)",
    "kept (live)",
    "reduced (live)",
    "dropped (live)",
    "stall (live)",
    "load (live)",
    "cardio (live)",
    "time (live)",
    "rate band",
    "added (live)",
    "trunk floor (live)",
    "kettlebell slot (live)",
    "kept light (live)",
    "one cut a week (live)",
    "cardio room (live)",
    "cardio progression (live)",
    "review (live)",
    "behind schedule",
    "new movement (live)",
    "press (live option)",
    "allocation (live)",
    "moved (live)",
    "pain (live)",
    "adherence dip",
    "no step (live)",
    "order (live)",
    "deadlift (live option)",
    "walk (live)",
    "waits (live)",  # #5861 FIX5
    "set cap (live)",
    "full body (live)",
    "capped (live)",
    "short week (live",
    "lead lift (live)",  # #5861 FIX6
    "top-up (live)",
    "priority (live)",
    "evidence (live)",
    "loss rate (advisory",
)


def live_lines(session: dict[str, Any]) -> list[str]:
    """The live programming lines of one drafted session (what the live policy changed and why); none in shadow."""
    return [ln for ln in session.get("rationale") or [] if ln.startswith(LIVE_PREFIXES)]


def _oneline(text: str | None) -> str:
    return " | ".join(ln.strip() for ln in str(text or "").splitlines() if ln.strip()) or "(none)"


def served_digest(mode: str = "proposed", profiles: dict[str, Any] | None = None) -> dict[str, str]:
    """Per profile, sha256 (16) of everything a drafted week SERVES: titles, each lift's sets/reps/notes, the compiled Hevy
    body, the cardio block, the rationale and the minutes. The no-live-change proof pins it in `proposed` mode."""
    import hashlib

    out = {}
    RESOLVER["mode"] = "legacy"  # the pins' own harness (RESOLVER doc); restored below
    try:
        results = run(None, mode, profiles, prior="pools")
    finally:
        RESOLVER["mode"] = "cron"
    for r in results:
        served = [{k: v for k, v in s.items() if k not in ("fatigue", "live_fit", "carry_m")} for s in r["week"]["sessions"]]
        out[r["week"]["profile"]] = hashlib.sha256(json.dumps(served, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return out


def run(names: list[str] | None = None, mode: str = "approved", profiles: dict[str, Any] | None = None, prior: str = "live") -> list:
    from training import routine_generator as rg

    profiles = profiles or load_profiles()
    landmarks = rg._load_json("training_landmarks.json")
    out = []
    for name in names or list(profiles):
        world = build_world(profiles[name], mode, prior)
        week = generate_week(profiles[name], mode, world)
        out.append({"week": week, "measures": measure(week, world["lib"], world["catalog"]["movements"], landmarks)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", action="append", help="a profile name (repeatable); default every profile")
    ap.add_argument("--profile-file", help="a profiles JSON outside the repo (same shape as the fixture)")
    ap.add_argument("--mode", default="approved", choices=("approved", "proposed"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--set", action="append", default=[], help="a library programming setting for this run, key=true|false|text")
    ap.add_argument("--strict-lint", action="store_true", help="exit 1 on a STRICT_LINT_CODES problem in any drafted week")
    args = ap.parse_args(argv)
    for kv in args.set:
        k, _, v = kv.partition("=")
        SETTINGS[k] = {"true": True, "false": False}.get(v.lower(), v)
    profiles = load_profiles(Path(args.profile_file)) if args.profile_file else None
    results = run(args.profile, args.mode, profiles)
    blocking = [f"{r['week']['profile']}/{p}" for r in results for p in lint_problems(r["week"])]
    for p in blocking:
        print(f"note lint (blocking): {p}", file=sys.stderr)
    if args.strict_lint and blocking:
        return 1
    if args.json:
        print(
            json.dumps([{"week": _jsonable(r["week"]), "measures": r["measures"]} for r in results], indent=1, sort_keys=True, default=str)
        )
        return 0
    for r in results:
        print(render(r["week"], r["measures"]))
    return 0


def _jsonable(week: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in week.items() if k != "sessions"} | {
        "sessions": [{k: v for k, v in s.items() if k != "rationale"} for s in week["sessions"]]
    }


if __name__ == "__main__":
    raise SystemExit(main())
