"""live_pain.py — the pain rule's reach and routes (#5861; fix round 10: ONE joint rule). LIVE only: reached from
`live_program.apply_joint_rule` / `live_rules.isolation_joint_cap` / `live_balance.pain_assess`, which run only past
`selection_engine.mode() == "live"`. Every number is a row of `live_program.PAIN_RULE` (labelled heuristics).

  1. SCOPE BY CLASS (`scope`). A discomfort flag at or under `lift_only_max` (2/10) — the light-discomfort class, or a discomfort
     note with no score — touches ONLY the flagged lift. Any other flag is scoped by its JOINT.
  2. ONE JOINT RULE (`hit`; fix round 11 — the tenth red team: a 4/10 hip flag on the split squat removed every lower compound in
     a garage). A joint-scoped flag reaches every lift that loads the flagged joint at moderate or more, whatever its pattern.
     Above the mild line (`avoid`) ONLY the provoking lift is ROUTED (below); every other lift it reaches — pain-free compounds
     included — HOLDS its load at RPE <= `pain_rpe` with the in-set stop line. At or under the mild line every lift it reaches
     holds the same way. The low back is this rule on `spinal_load` — no separate spine rule.
  3. ROUTES (`variant`, `muscle_route`). A routed lift is replaced by a pain-free same-family member first, else by any movement
     for the muscle it trained, each loading every flagged joint LOW — and REVIEWED: a movement whose joint stress is defaulted or
     unreviewed (`reviewed`) is never a pain route (owner ruling 16: missing data is not proof of suitability). For a PRIORITY
     muscle with no LOW member, the lowest-stress reviewed member strictly under the flagged lift's own stress
     (`priority_ceiling`). No route: the muscle is zero this week by design, said plainly.
  4. THE ASSESS LINE ON ITS OWN LIFT (`assess_target`)."""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"


def _rule(name: str) -> Any:
    from training.live_program import PAIN_RULE

    return PAIN_RULE[name]["value"]


def reviewed(entry: dict[str, Any]) -> bool:
    """Module doc 3: the library row's inputs (joint stress included) were reviewed, not derived by a title rule or defaulted."""
    return bool((entry.get("objective_inputs") or {}).get("reviewed"))


def _low(entry: dict[str, Any], joints: list[str], ceiling: int = 0) -> bool:
    """A reviewed movement loading every flagged joint at or under `ceiling` (LOW by default) — the only kind a route may use."""
    return reviewed(entry) and all(0 <= _stress(entry, j) <= ceiling for j in joints)


def scope(flag: dict[str, Any], light: set[str], tid: str) -> str:
    """`lift` (only the flagged lift) or `joint` (every lift loading the flagged joint) for one flag (module doc 1)."""
    sev = flag.get("severity")
    if flag.get("source") == "discomfort" and (tid in light or sev is None or float(sev) <= float(_rule("lift_only_max"))):
        return "lift"
    return "joint"


def low_discomfort(workouts: Any) -> set[str]:
    """Template ids whose LATEST note states a score at or under `lift_only_max` and is not 'sharp': the lift stays (the joint
    rule takes it lighter) instead of the anchor swap two discomfort notes would otherwise trigger."""
    from training import live_safety
    from training.training_notes_pain import stated_severity

    cap = float(_rule("lift_only_max"))
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
    """(tier, flag, joint) for the strongest flag that reaches this exposure, else None (module doc 2). `variant`: the session
    fit's own pain swap already stands in, reviewed and LOW on the flagged joint; `avoid`: route it; `hold`: keep it, load held,
    RPE <= pain_rpe, the stop line."""
    from training.live_program import STRESS

    level = STRESS[str(_rule("joint_level"))]
    mid = (ctx.get("idx") or {}).get("to_lib", {}).get(str(e.get("movement_key")))
    swapped = (ctx.get("idx") or {}).get("to_lib", {}).get(str((e.get("live_swap") or {}).get("from")))
    best = None
    for f in flags:
        own = f["movement_id"] in (mid, swapped)
        if f["movement_id"] == swapped and f["movement_id"] != mid and _low(entry, f["joints"]):
            return ("variant", f, f["joints"][0])  # the session fit already put a reviewed member LOW on the flagged joint in its place
        for j in f["joints"]:
            if not (own or (f.get("scope") != "lift" and _stress(entry, j) >= level)):
                continue
            tier = "avoid" if f["tier"] == "avoid" and own else "hold"  # fix round 11: only the provoking lift is routed
            if best is None or (tier == "avoid" and best[0] != "avoid"):
                best = (tier, f, j)
    return best


def variant(e: dict[str, Any], ctx: dict[str, Any], rotation: dict[str, Any], taken: set[str], joints: list[str]) -> str | None:
    """A reviewed same-family member that loads every flagged joint LOW (module doc 3): the session fit's replacement search."""
    from training import live_session

    for j in joints:
        new = live_session._replacement(e, "joint", ctx, rotation, taken, limit=(j, 1))
        if new and _low(live_session._entry(new, ctx) or {}, joints):
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
    """Any servable, REVIEWED library movement whose landmark muscle is the dropped lift's and that loads every flagged joint at or
    under `ceiling` (LOW by default; `priority_ceiling` for a priority muscle) (module doc 3), best hypertrophy tier first, then
    the most familiar."""
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
        if not _low(entry, joints, ceiling):
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
    """The exposure re-pointed at `new`, capped at pain_rpe with the stop line (module doc 3)."""
    from training import live_safety

    rpe = int(_rule("pain_rpe"))
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
