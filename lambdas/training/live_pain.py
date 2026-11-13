"""live_pain.py — the pain rule NARROWED to what provokes it (#5861 FIX7, the sixth red team). LIVE only: reached from
`live_program.apply_joint_rule` / `live_rules.isolation_joint_cap` / `live_balance.pain_assess`, which run only past
`selection_engine.mode() == "live"`.

WHY. The sixth red team graded stimulus adequacy C: one flag capped every lift loading the same joint at RPE 7 for the whole
week, or removed the pattern with no pain-free variant — mild 2/10 elbow soreness took chest to 2 hard sets, knee 5/10 took the
quadriceps to zero, and a 2-day week with a 4/10 shoulder had no push at all. Standard pain-monitoring practice acts on the
PROVOKING movement and keeps the muscle trained by a route that does not hurt. The rule (PAIN_SCOPE, every number a labelled
heuristic, safety kept):

  1. SCOPE BY CLASS (`scope`). A discomfort flag at or under `lift_only_max` (2/10) — the engine's light-discomfort class, or a
     discomfort note with no score — touches ONLY the flagged lift (lighter, RPE <= 7, the in-set stop line). Above it, and any
     pain-class flag, the scope is the provoking PATTERN: the members of the flagged movement's pattern group that load the
     flagged joint at moderate or more — never every lift that loads the joint.
  2. SAME FAMILY FIRST (`variant`). Above the mild line ('sharp', > 3/10, or no number on a pain note) the provoking pattern is off
     for THAT session — but first a pain-free member of the SAME family is offered (the session fit's own replacement search,
     capped at LOW stress on the flagged joint: a neutral-grip / dumbbell / machine / range-limited member), served at RPE <= 8
     with the stop line, so a 'pain <= 3/10 -> keep going' test is in the note.
  3. THE MUSCLE KEEPS A ROUTE (`muscle_route`). When the family has no pain-free member, the muscle the dropped lift trained is
     served by any library movement for that muscle that loads every flagged joint LOW; for a PRIORITY muscle with no LOW member,
     the lowest-stress member strictly under the flagged lift's own stress (`priority_ceiling`) at RPE <= 8 with the stop line — a
     priority muscle is never taken to zero sets by one flag.
  5. THE SPINE IS ONE JOINT (`spine_reach`, SPINE_REACH, #5861 FIX8). A low-back flag above the mild line reaches every lift
     that loads the spine at moderate or more whatever its pattern group (squat, hinge, RDL, good morning, bent-over row): each
     is served as a same-family pain-free route (a supported / machine member LOW on the spine) when one exists, else the
     muscle's route, at RPE <= 8 with the stop line and no in-session load step — the week never zeroes a priority muscle.
  4. THE ASSESS LINE ON ITS OWN LIFT. "Still hurts 2 sessions? Get it assessed." prints on the flagged lift (or what stands in
     for it), never on an unrelated one (`assess_target`).
"""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

PAIN_SCOPE: dict[str, dict[str, Any]] = {
    "lift_only_max": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "a discomfort note at or under 2/10 (or the light-discomfort class) changes only the lift it was logged on: "
        "pain-monitoring models tolerate low, settling discomfort during loading (practitioner consensus; the sixth red team)",
    },
    "variant_rpe": {
        "value": 8,
        "label": HEURISTIC,
        "basis": "a pain-free same-family variant is served at RPE <= 8 with the in-set stop line — a test of a pain-free route, "
        "still a hard set (RPE 8 = 2 in reserve)",
    },
    "low_stress": {
        "value": "low",
        "label": HEURISTIC,
        "basis": "a variant or muscle route must load every flagged joint LOW (the library's joint-stress ratings)",
    },
}

SPINE_REACH: dict[str, dict[str, Any]] = {
    "level": {
        "value": 1,
        "label": HEURISTIC,
        "basis": "#5861 FIX8: a low-back flag above the mild line reaches every lift whose library spinal load is moderate (1) or "
        "high (2), whatever its pattern group — the spine is one structure; the squat/hinge split is a programming grouping, not "
        "an anatomical one (practitioner consensus; the seventh red team)",
    },
}


def scope(flag: dict[str, Any], light: set[str], tid: str) -> str:
    """`lift` (only the flagged lift) or `pattern` (the provoking pattern) for one flag (module doc 1)."""
    sev = flag.get("severity")
    if flag.get("source") == "discomfort" and (tid in light or sev is None or float(sev) <= float(PAIN_SCOPE["lift_only_max"]["value"])):
        return "lift"
    return "pattern"


def low_discomfort(workouts: Any) -> set[str]:
    """Template ids whose LATEST note states a score at or under `lift_only_max` and is not 'sharp': the lift stays (the joint
    rule takes it lighter) instead of the anchor swap two discomfort notes would otherwise trigger."""
    from training import live_safety
    from training.training_notes_pain import stated_severity

    cap = float(PAIN_SCOPE["lift_only_max"]["value"])
    out = set()
    for tid, note in live_safety.latest_notes(workouts).items():
        sev = stated_severity(note)
        if sev is not None and sev <= cap and "sharp" not in note.lower():
            out.add(tid)
    return out


def _stress(entry: dict[str, Any], joint: str) -> int:
    from training.live_program import STRESS

    return STRESS.get(str((entry.get("joint_stress") or {}).get(joint)), -1)


def hit(
    entry: dict[str, Any], e: dict[str, Any], flags: list[dict[str, Any]], ctx: dict[str, Any]
) -> tuple[str, dict[str, Any], str] | None:
    """(tier, flag, joint) for the strongest flag whose SCOPE reaches this exposure, else None. `variant`: the session fit's own
    pain swap already stands in LOW on the flagged joint (served as the pain-free variant). A `lift` flag reaches only the
    flagged movement (or what the session fit swapped in for it); a `pattern` flag reaches the members of its pattern group that
    load its joint at moderate or more, and the flagged movement itself."""
    from training.live_program import PAIN_RULE, STRESS, _group

    level = STRESS[str(PAIN_RULE["joint_level"]["value"])]
    mid = (ctx.get("idx") or {}).get("to_lib", {}).get(str(e.get("movement_key")))
    swapped = (ctx.get("idx") or {}).get("to_lib", {}).get(str((e.get("live_swap") or {}).get("from")))
    best = None
    for f in flags:
        own = f["movement_id"] in (mid, swapped)
        if f["movement_id"] == swapped and f["movement_id"] != mid and all(_stress(entry, j) == 0 for j in f["joints"]):
            return ("variant", f, f["joints"][0])  # the session fit already put a member LOW on the flagged joint in its place
        for j in f["joints"]:
            spine = spine_reach(entry, f, j)  # #5861 FIX8: a back flag reaches every spine-loading lift, whatever its pattern group
            if f.get("scope") == "lift":
                reach = own
            else:
                reach = own or spine or (_group(entry.get("pattern")) == f["group"] and _stress(entry, j) >= level)
            if not reach:
                continue
            tier = "avoid" if f["tier"] == "avoid" and (own or spine or _group(entry.get("pattern")) == f["group"]) else "reduce"
            if best is None or (tier == "avoid" and best[0] != "avoid"):
                best = (tier, f, j)
    return best


def spine_reach(entry: dict[str, Any], f: dict[str, Any], joint: str) -> bool:
    """SPINE_REACH (module doc 5): a pattern-scoped flag on the spine (`spinal_load`, a low-back note) above the mild line
    reaches `entry` when it loads the spine at moderate or more — a squat flag reaches the deadlift, the RDL, the good morning and
    the bent-over row; the pain rule's pattern group alone stopped at the squat (the seventh red team's blocking finding)."""
    from training.live_program import PAIN_RULE

    if joint != "spinal_load" or f.get("scope") == "lift" or _stress(entry, "spinal_load") < int(SPINE_REACH["level"]["value"]):
        return False
    sev = f.get("severity")
    return f.get("tier") == "avoid" or (sev is not None and float(sev) > float(PAIN_RULE["mild_max"]["value"]))


def variant(e: dict[str, Any], ctx: dict[str, Any], rotation: dict[str, Any], taken: set[str], joints: list[str]) -> str | None:
    """A same-family member that loads every flagged joint LOW (module doc 2): the session fit's replacement search, capped."""
    from training import live_session

    for j in joints:
        new = live_session._replacement(e, "joint", ctx, rotation, taken, limit=(j, 1))
        if new and all(_stress(live_session._entry(new, ctx) or {}, x) in (0,) for x in joints):
            return new
    return None


def priority_ceiling(e: dict[str, Any], ctx: dict[str, Any], f: dict[str, Any]) -> int | None:
    """For a PRIORITY muscle (`priority_muscles`) with no LOW route: the stress ceiling a relaxed route may carry on the flagged
    joint — strictly under the flagged movement's own (a leg press, not the back squat, for a knee) — else None."""
    from training import live_settings, live_volume

    muscle = live_volume.landmark_muscle(e.get("movement_key"), ctx["catalog"], ctx["lib"])
    if muscle not in [str(m) for m in live_settings.settings(ctx.get("lib")).get("priority_muscles") or []]:
        return None
    flagged = (ctx["lib"].get("movements") or {}).get(f["movement_id"]) or {}
    worst = min((_stress(flagged, j) for j in f["joints"]), default=-1)
    return worst - 1 if worst >= 1 else None


def muscle_route(e: dict[str, Any], ctx: dict[str, Any], taken: set[str], joints: list[str], ceiling: int = 0) -> str | None:
    """Any servable library movement whose landmark muscle is the dropped lift's and that loads every flagged joint at or under
    `ceiling` (LOW by default; `priority_ceiling` for a priority muscle) (module doc 3), best hypertrophy tier first, then the
    most familiar."""
    from training import live_session, live_volume, selection_engine as se, selection_live

    muscle = live_volume.landmark_muscle(e.get("movement_key"), ctx["catalog"], ctx["lib"])
    to_cat = {lid: k for k, lid in ctx["idx"]["to_lib"].items()}
    rank = {t: i for i, t in enumerate("SABCD")}
    out = []
    for lid, entry in sorted((ctx["lib"].get("movements") or {}).items()):
        key = to_cat.get(lid)
        if not key or key in taken or entry.get("pattern") in ("carry", "cardio", "other"):
            continue
        if live_volume.landmark_muscle(key, ctx["catalog"], ctx["lib"]) != muscle:
            continue
        if any(not 0 <= _stress(entry, j) <= ceiling for j in joints):
            continue
        cat = ctx["catalog"].get(key) or {}
        if cat.get("hevy_type") in live_session.NOT_LIFTS or int(cat.get("skill_tier", 99)) > ctx["ceiling"]:
            continue
        if (
            se.availability(entry, ctx["lib"], ctx["overlay"])
            or se.pain_exclusion(entry, ctx["overlay"])
            or live_session._servable(key, ctx)
        ):
            continue
        tier = selection_live.objective_tier(entry, "hypertrophy", muscle)
        out.append((rank.get(str(tier), 9), -int(cat.get("sessions") or 0), key))
    return sorted(out)[0][2] if out else None


def serve_route(e: dict[str, Any], new: str, f: dict[str, Any], how: str) -> dict[str, Any]:
    """The exposure re-pointed at `new`, capped at variant_rpe with the stop line (module doc 2-3)."""
    from training import live_safety

    rpe = int(PAIN_SCOPE["variant_rpe"]["value"])
    out = {k: v for k, v in e.items() if k != "template_id"}
    out |= {
        "movement_key": new,
        "live_swap": {"from": e.get("movement_key"), "code": how},
        "live_stop": live_safety.stop_line(f["severity"]),
    }
    out["live_effort"] = min(rpe, int(e.get("live_effort") or 99))
    return out


def assess_target(rx: dict[str, Any], ctx: dict[str, Any], pains: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The exposure that IS the flagged lift (or stands in for it) — the only one that carries the assess line (module doc 4)."""
    to_lib = (ctx.get("idx") or {}).get("to_lib", {})
    ids = {f["movement_id"] for f in pains}
    for e in rx.get("exposures") or []:
        if to_lib.get(str(e.get("movement_key"))) in ids or to_lib.get(str((e.get("live_swap") or {}).get("from"))) in ids:
            return e
    return None
