#!/usr/bin/env python3
"""progression_sim_5861.py — a MULTI-WEEK progression simulation through the real draft path (#5861 FIX7).

WHY IT EXISTS. The sixth red team (2026-11-13) found a stall-reset ratchet that every single-week test missed: a stalled anchor
was reset 10%, the athlete did the reset exactly as written, and the next week's draft judged the lighter session against the
PRE-reset best and reset it again (175 -> 155 -> 135 lb). Only a test that feeds each week's prescription back as the next
week's record can see that. This module does exactly that:

  * week 0 is `sample_weeks_5861.build_world(profile)` (the synthetic prior phase, the library flipped to `approved` in memory);
  * each week is drafted by `sample_weeks_5861.generate_week` (the real path: `full_body_session.full_body_routines`, the live
    session fit, the fatigue model, the load guard, the compiled Hevy wire);
  * every drafted session is recorded as PERFORMED by an `Athlete` — each working set at the prescribed load, with reps and RPE
    from the athlete's policy — and appended to the record the next week's drafts read.

The dates move a week at a time (the ISO-week lead-lift parity moves with them); the program position is held, so the block
calendar never confounds the progression read. Deterministic and offline, like the sample weeks.

    python3 scripts/progression_sim_5861.py --weeks 6                      # profile a, as-prescribed athlete, a table
    python3 scripts/progression_sim_5861.py --weeks 6 --athlete stalled:deadlift_barbell
"""

from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_weeks_5861 as sw  # noqa: E402

LB_PER_KG = 2.20462


@dataclass
class Athlete:
    """How a drafted session is performed. `reps`: `top` (the top of each prescribed range) or `bottom`; `rpe` logged on every
    working set. `stalled`: catalog keys performed at the BOTTOM of the range minus one rep at RPE 9.5 (a genuine stall: rep
    loss with effort drift) whatever the load."""

    reps: str = "top"
    rpe: float = 8.0
    stalled: set[str] = field(default_factory=set)
    capacity: dict[str, float] = field(default_factory=dict)
    """Catalog key -> a FIXED e1RM (lb): a plateaued lifter. Each set gets the reps that e1RM allows at the load (Epley inverse,
    capped at the range top) at RPE 9 when that is at or under the range floor, else 8.5 — a genuine stall, whatever the load."""

    def perform(self, session: dict[str, Any], day: str, role: str) -> dict[str, Any]:
        from training import routine_generator as rg

        catalog = rg._load_json("movement_catalog.json")["movements"]
        wires = [w for w in session.get("wire") or [] if _not_cardio(w)]
        exercises = []
        for lift, ex in zip(session.get("lifts") or [], wires):
            key = str(lift.get("key"))
            tid = sw._tid(catalog, key) or key
            sets = []
            for s in ex.get("sets") or []:
                rr = s.get("rep_range") or {}
                if s.get("type") == "warmup" or not s.get("weight_kg") or not rr:
                    continue
                if key in self.capacity:
                    lb = float(s["weight_kg"]) * LB_PER_KG
                    can = max(1, min(int(rr["end"]), int(30 * (self.capacity[key] / lb - 1))))
                    reps, rpe = can, (9.0 if can <= int(rr["start"]) else 8.5)
                elif key in self.stalled:
                    reps, rpe = max(1, int(rr["start"]) - 1), 9.5
                else:
                    reps, rpe = int(rr["end"] if self.reps == "top" else rr["start"]), self.rpe
                sets.append({"type": "normal", "weight_kg": round(float(s["weight_kg"]), 3), "reps": reps, "rpe": rpe})
            if sets:
                exercises.append({"name": key, "template_id": tid, "notes": "", "sets": sets})
        return sw._workout(day, role, exercises)


@dataclass
class Physiological:
    """#5861 FIX8 — the seventh red team's RECORD-SEEDED athlete, ported: each lift has a TRUE e1RM (lb), seeded from the record's
    latest top set (reps + reps in reserve, Epley), that drifts `drift` a week (0 steady, +0.005 gaining, -0.01 losing). Every
    working set is performed at the prescribed load to the prescribed effort (reps in reserve = 10 - the note's top RPE): reps =
    min(range top, reps-to-failure - RIR); a set it cannot take to the range floor at that effort is ground out at RIR 1.
    `under`: one rep fewer and RPE +1 on every set. Unlike `Athlete`, the load matters — a heavy day served a volume day's load
    is performed at an effort far under its band, which is what the role-blind guard did (the seventh red team)."""

    drift: float = 0.0
    under: bool = False
    true: dict[str, float] = field(default_factory=dict)
    seed: dict[str, float] = field(default_factory=dict)

    def start(self, record: list[dict[str, Any]]) -> None:
        for w in sorted(record, key=lambda w: w["date"]):
            for x in w["exercises"]:
                st = [s for s in x["sets"] if s.get("weight_kg") and s.get("reps")]
                if st:
                    top = max(st, key=lambda s: float(s["weight_kg"]))
                    rir = 10 - float(top.get("rpe") or 8)
                    self.seed[str(x["template_id"]).upper()] = float(top["weight_kg"]) * LB_PER_KG * (1 + (int(top["reps"]) + rir) / 30)

    def next_week(self) -> None:
        for k in self.true:
            self.true[k] *= 1 + self.drift

    def perform(self, session: dict[str, Any], day: str, role: str) -> dict[str, Any]:
        import math

        from training import routine_generator as rg

        catalog = rg._load_json("movement_catalog.json")["movements"]
        wires = [w for w in session.get("wire") or [] if _not_cardio(w)]
        exercises = []
        for lift, ex in zip(session.get("lifts") or [], wires):
            key = str(lift.get("key"))
            tid = sw._tid(catalog, key) or key
            rir = max(0.0, 10.0 - (sw.lift_effort(lift.get("hevy_note")) or 8.0))
            sets = []
            for s in ex.get("sets") or []:
                rr = s.get("rep_range") or {}
                if s.get("type") == "warmup" or not s.get("weight_kg") or not rr:
                    continue
                lb = float(s["weight_kg"]) * LB_PER_KG
                if key not in self.true:
                    mid = (int(rr["start"]) + int(rr["end"])) / 2
                    self.true[key] = self.seed.get(str(tid).upper()) or lb * (1 + (mid + 2) / 30)
                rtf = max(0.0, 30 * (self.true[key] / lb - 1))
                reps = min(int(rr["end"]), int(math.floor(rtf - rir + 1e-9)))
                if reps < int(rr["start"]):
                    reps = max(1, min(int(rr["start"]), int(math.floor(rtf - 1 + 1e-9))))
                reps = max(1, reps - 1) if self.under else reps
                rpe = min(10.0, 10.0 - (rtf - reps)) if rtf >= reps else 10.0
                rpe = min(10.0, rpe + 1) if self.under else rpe
                sets.append({"type": "normal", "weight_kg": round(float(s["weight_kg"]), 3), "reps": int(reps), "rpe": round(rpe * 2) / 2})
            if sets:
                exercises.append({"name": key, "template_id": tid, "notes": "", "sets": sets})
        return sw._workout(day, role, exercises)


def _not_cardio(ex: dict[str, Any]) -> bool:
    """A wire exercise the sample week lists as a lift (a cardio block's sets carry only a duration)."""
    return any((s.get("rep_range") or s.get("reps") or s.get("weight_kg") or s.get("distance_meters")) for s in ex.get("sets") or [])


def _shift(profile: dict[str, Any], weeks: int) -> dict[str, Any]:
    out = copy.deepcopy(profile)
    out["days"] = [sw._day(d, 7 * weeks) for d in profile["days"]]
    out["as_of"] = sw._day(profile["as_of"], 7 * weeks)
    return out


def top_loads(week: dict[str, Any]) -> dict[str, list[float]]:
    """Catalog key -> the top prescribed working load (lb) of each of its exposures this week, in session order."""
    out: dict[str, list[float]] = {}
    for s in week["sessions"]:
        wires = [w for w in s.get("wire") or [] if _not_cardio(w)]
        for lift, ex in zip(s.get("lifts") or [], wires):
            loads = [float(x["weight_kg"]) for x in ex.get("sets") or [] if x.get("type") != "warmup" and x.get("weight_kg")]
            if loads:
                out.setdefault(str(lift["key"]), []).append(round(max(loads) * LB_PER_KG / 2.5) * 2.5)
    return out


def simulate(profile: dict[str, Any], weeks: int, athlete: Athlete | Physiological | None = None, skip: Any = None) -> list[dict[str, Any]]:
    """`weeks` drafted weeks, each performed by `athlete` and fed to the next (a week `skip(k)` names is drafted but NOT
    performed: the alternate-week misser). Returns per week: the date, each lift's top prescribed loads, its reps, the roles,
    the prescribed HARD sets per muscle (`sample_weeks_5861.hard_sets_by_muscle`) and the rationale."""
    athlete = athlete or Athlete()
    world = sw.build_world(profile, "approved")
    if isinstance(athlete, Physiological):
        athlete.start(world["record"])
    out = []
    for k in range(weeks):
        p = _shift(profile, k)
        world["profile"] = world["profile"] | {"days": p["days"], "as_of": p["as_of"]}
        if isinstance(athlete, Physiological):
            athlete.next_week()
        week = sw.generate_week(p, "approved", world, perform=athlete.perform)
        skipped = bool(skip and skip(k))
        if not skipped:
            world["record"] = list(world["record"]) + list(week["performed"])
        out.append(
            {
                "week": k,
                "monday": p["days"][0],
                "skipped": skipped,
                "roles": [s["role"] for s in week["sessions"]],
                "loads": top_loads(week),
                "reps": {lift["key"]: lift["reps"] for s in week["sessions"] for lift in s["lifts"]},
                "hard": sw.hard_sets_by_muscle(week, world["lib"], world["catalog"]["movements"]),
                "rationale": {s["role"]: s["rationale"] for s in week["sessions"]},
            }
        )
    return out


def heavy_day_falls(rows: list[dict[str, Any]], keys: tuple[str, ...], limit: float = 0.10) -> dict[str, float]:
    """#5861 FIX8 acceptance (the seventh red team): each key's HEAVY-day load (its first exposure of the week) as its largest
    fall under its week-0 load, for every key whose fall exceeds `limit` — {} when none does."""
    out = {}
    for k in keys:
        loads = [(r["loads"].get(k) or [None])[0] for r in rows]
        base = loads[0]
        worst = min((x for x in loads if x), default=base)
        if base and worst and worst < base * (1 - limit):
            out[k] = round(1 - worst / base, 3)
    return out


def resets(rows: list[dict[str, Any]], key: str, drop: float = 0.07) -> list[int]:
    """The weeks whose first prescribed top load of `key` sits `drop` or more under the week before's (a reset or a cut)."""
    seq = [(r["week"], (r["loads"].get(key) or [None])[0]) for r in rows]
    return [w for (_w0, a), (w, b) in zip(seq, seq[1:]) if a and b and b <= a * (1 - drop)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--profile", default="a_large_deficit_experienced")
    ap.add_argument("--profile-file", type=Path)
    ap.add_argument("--weeks", type=int, default=6)
    ap.add_argument("--loss-pct", type=float, default=None, help="weekly loss %%BW for the synthetic weigh-ins (0 = no deficit)")
    ap.add_argument(
        "--athlete",
        default="top",
        help="top | bottom | stalled:<key>[,<key>] | capacity:<key>=<e1rm lb>[,...] | physio:<steady|gain|drop|under|skip_odd>",
    )
    ap.add_argument("--keys", default="squat_barbell,deadlift_barbell,barbell_bench_press")
    a = ap.parse_args(argv)
    prof = sw.load_profiles(a.profile_file)[a.profile]
    prof = prof | ({"weekly_loss_pct": a.loss_pct} if a.loss_pct is not None else {})
    if a.athlete.startswith("stalled:"):
        ath = Athlete(stalled=set(a.athlete.split(":", 1)[1].split(",")))
    elif a.athlete.startswith("capacity:"):
        ath = Athlete(capacity={k: float(v) for k, v in (x.split("=") for x in a.athlete.split(":", 1)[1].split(","))})
    elif a.athlete.startswith("physio:"):
        mode = a.athlete.split(":", 1)[1]
        ath = Physiological(drift={"gain": 0.005, "drop": -0.01}.get(mode, 0.0), under=mode == "under")
    else:
        ath = Athlete(reps=a.athlete)
    skip = (lambda k: k % 2 == 1) if a.athlete == "physio:skip_odd" else None
    rows = simulate(prof, a.weeks, ath, skip=skip)
    keys = a.keys.split(",")
    print("| week | monday | " + " | ".join(keys) + " |")
    print("|---|---|" + "---|" * len(keys))
    for r in rows:
        cells = [f"{'/'.join(f'{x:g}' for x in r['loads'].get(k) or []) or '-'} ({r['reps'].get(k, '-')})" for k in keys]
        print(f"| {r['week']} | {r['monday']} | " + " | ".join(cells) + " |")
    for k in keys:
        print(f"resets {k}: {resets(rows, k)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
