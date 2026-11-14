"""live_program.py — the programming pass of the live policy (#5861). LIVE only: every entry point returns its input untouched
(or None) unless the draft ran the live session fit (`live_session.MARK` on the prescription, which exists only when
`selection_engine.mode() == "live"`). tests/test_no_live_change_5861_l6.py pins the served proposed-mode drafts byte for byte.

What it owns after fix round 9 (the load model moved to `live_load`, the volume to `live_volume`):
  * PAIN BY JOINT (`joint_flags`, `apply_joint_rule`, PAIN_RULE; the reach and routes are `live_pain`): a flag reaches every
    lift loading its joint at moderate or more; at or under the mild line each is held (load held, RPE <= 8, the stop line), above
    it the flagged pattern and any lift loading the joint high are routed to a reviewed low-stress member, the rest held.
  * AXIAL STACKING (`avoid_stacking`, STACK_RULE): at most two spine-loading squat/hinge compounds a session.
  * THE DELOAD SHAPE (`deload_shape`, DELOAD_SHAPE) and the fatigue cost the fatigue model's one reducer reads (`fatigue_cost`).
  * NOTES (`annotate`): each lift's one load reason (`live_load`) and each effort cap on its own Hevy note.
  * CARDIO (`cardio_context`, `cardio_fit`, `cardio_note`): purposeful blocks only (owner ruling 4), the hard dose on the week's host,
    under the shared cap the minutes lifting leaves (ruling 1), no symptom warning line (ruling 10).

Every number is a labelled PLATFORM HEURISTIC (practitioner consensus at best), owner-adjustable; none is validated."""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

DELOAD_SHAPE: dict[str, dict[str, Any]] = {
    "compound_sets": {"value": 2, "label": HEURISTIC, "basis": "a recommended deload cuts every compound to 2 working sets"},
    "compound_rpe": {"value": 7, "label": HEURISTIC, "basis": "compounds stop at RPE 7 (about 3 in reserve) on a deload-recommended day"},
    "isolation_rpe": {
        "value": 8,
        "label": HEURISTIC,
        "basis": "isolation stops at RPE 8, under its usual last-set band, on a deload-recommended day",
    },
    "isolation_max_sets": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "isolation is KEPT (low systemic cost — it holds the muscle's stimulus) but a 3-4 set slot drops to 2: a "
        "recommended deload still lowers the week's volume, compounds first and hardest",
    },
    "anchor_top_rpe": {
        "value": 8,
        "label": HEURISTIC,
        "basis": "a RECOMMENDED (unconfirmed) deload keeps one top set per anchor at RPE 8 — strength exposure held until the owner "
        "confirms the deload; the RPE-7 compound cap applies once confirmed",
    },
    "reduce_min_sets": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "under reduce a compound gives sets first but never below 2 (an anchor keeps its top set and one more)",
    },
}
PAIN_RULE: dict[str, dict[str, Any]] = {
    "mild_max": {
        "value": 3,
        "label": HEURISTIC,
        "basis": "pain at or under 3/10 (the platform's own pain tripwire, training_notes_pain.SEVERITY_THRESHOLD) keeps every lift "
        "loading that joint, its load held; above it, or a 'sharp' note, or no stated number, the flagged lift, its pattern group "
        "and every lift loading the joint HIGH are routed (a reviewed pain-free member) and the rest held — a common "
        "pain-monitoring rule (owner to confirm the line)",
    },
    "lift_only_max": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "a discomfort note at or under 2/10 (or the light-discomfort class) changes only the lift it was logged on: "
        "pain-monitoring models tolerate low, settling discomfort during loading (practitioner consensus)",
    },
    "pain_rpe": {
        "value": 8,
        "label": HEURISTIC,
        "basis": "every lift the pain rule keeps, routes or holds runs at RPE <= 8 with the in-set stop line and its load HELD (no "
        "step up while a flag stands; reps under the floor still step it down) — still a hard set (RPE 8 = 2 in reserve)",
    },
    "joint_level": {
        "value": "moderate",
        "label": HEURISTIC,
        "basis": "a flag reaches every lift loading its joint at moderate or high stress, whatever the pattern (the low back is "
        "the spinal_load case of the same rule)",
    },
}
STACK_RULE: dict[str, dict[str, Any]] = {
    "axial_per_session": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "at most two spinal-loading (moderate or more) squat/hinge compounds in one session: the third is swapped for a "
        "low-spinal-load member or dropped (fatigue_model's axial-stacking finding, acted on)",
    },
}
MIN_CARDIO_MINUTES = 10  # heuristic: a cardio block shorter than this under the shared cap is dropped, not served as a stub

STRESS = {"low": 0, "moderate": 1, "high": 2}
JOINTS = ("shoulder", "elbow", "wrist", "spinal_load", "shear", "knee", "hip")  # #5861 FIX4: knee + hip (the pain map)
PATTERN_GROUPS = {
    "press": ("horizontal_press", "vertical_press", "press", "chest_fly", "triceps_extension"),
    "pull": ("vertical_pull", "horizontal_pull", "rear_delt", "curl"),
    "hinge": ("hinge", "hip_extension", "leg_curl"),
    "squat": ("squat", "leg_extension"),
}
AXIAL = ("squat", "hinge")
HARD_KINDS = ("tempo", "hills", "intervals")


SHORT_WEEK_SKIP = "shoulders_arms"


def is_live(rx: dict[str, Any] | None) -> bool:
    from training.live_session import MARK

    return bool(rx) and MARK in (rx or {})


def _entry(key: str | None, ctx: dict[str, Any]) -> dict[str, Any]:
    lid = ctx["idx"]["to_lib"].get(str(key)) if key else None
    return ((ctx["lib"].get("movements") or {}).get(lid) or {}) if lid else {}


def _stress(entry: dict[str, Any], joint: str) -> int:
    return STRESS.get(str((entry.get("joint_stress") or {}).get(joint)), -1)


def _group(pattern: Any) -> str | None:
    return next((g for g, ps in PATTERN_GROUPS.items() if pattern in ps), None)


def _unilateral(entry: dict[str, Any]) -> bool:
    return "unilateral" in ((entry.get("objective_inputs") or {}).get("functional") or [])


def _compound(entry: dict[str, Any]) -> bool:
    return entry.get("job") == "compound" and entry.get("pattern") not in ("carry", "cardio")


# ── 2. the cost a set carries (the trim and deload order) ─────────────────────
def fatigue_cost(e: dict[str, Any], ctx: dict[str, Any]) -> str:
    """`high` (a free-weight or spinal-loading compound), `moderate` (another compound), `low` (isolation, carries, trunk) —
    categorical, from the library's job / resistance profile / spinal load / systemic fatigue. Heuristic."""
    entry = _entry(e.get("movement_key"), ctx)
    if not _compound(entry):
        return "low"
    sys_ = (entry.get("objective_inputs") or {}).get("systemic_fatigue")
    if entry.get("resistance_profile") == "free_weight" or _stress(entry, "spinal_load") >= 1 or sys_ == "high":
        return "high"
    return "moderate"


def mark_costs(rx: dict[str, Any], ctx: dict[str, Any]) -> None:
    """IN PLACE: every exposure carries `live_cost` and, under reduce, `live_min_sets` (compounds never below DELOAD_SHAPE
    reduce_min_sets) — what `fatigue_model.apply_to_session` reads to cut high-fatigue work first."""
    for e in rx.get("exposures") or []:
        e["live_cost"] = fatigue_cost(e, ctx)
        if e["live_cost"] != "low" or e.get("intensity") != "carry":  # #5861 FIX4: isolation too — drop, don't shave
            e["live_min_sets"] = int(DELOAD_SHAPE["reduce_min_sets"]["value"])


def trim_order(surplus: Any) -> Any:
    """The reduce trim: compounds first (high cost, then moderate; anchors included, never below 2 sets), then isolation in
    the surplus-first order (`live_session.surplus_first`). One set per pass, so the cut spreads."""

    def order(exposures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rank = {"high": 0, "moderate": 1}
        comp = sorted((e for e in exposures if e.get("live_cost") in rank), key=lambda e: (rank[e["live_cost"]], e.get("kind") == "anchor"))
        return comp + [e for e in surplus(exposures) if e.get("live_cost") == "low"]

    return order


def deload_shape(exposures: list[dict[str, Any]], confirmed: bool = False) -> int:
    """IN PLACE, a RECOMMENDED deload's reduction (applying the deload itself stays his word): every compound to
    DELOAD_SHAPE compound_sets (back-offs go, the top set stays) at RPE <= compound_rpe — an ANCHOR at DELOAD_TOP_SET's RPE 8
    until the owner confirms the deload (`confirmed`, #5861 FIX7) — its load held or stepped down;
    isolation is kept — at most isolation_max_sets, RPE <= isolation_rpe. Returns the sets removed."""
    removed = 0
    for e in exposures:
        sets = e.get("sets") or []
        if e.get("live_cost") in ("high", "moderate"):
            while len(sets) > int(DELOAD_SHAPE["compound_sets"]["value"]):
                idx = [i for i, s in enumerate(sets) if s.get("kind") != "top"]
                if not idx:
                    break
                sets.pop(idx[-1])
                removed += 1
            rpe = int(DELOAD_SHAPE["compound_rpe"]["value"])
            if e.get("kind") == "anchor" and not confirmed:  # #5861 FIX7: until he confirms the deload, the top set stays at RPE 8
                rpe = int(DELOAD_SHAPE["anchor_top_rpe"]["value"])
            e["live_effort"] = min(rpe, int(e.get("live_effort") or 99))
            e["live_load"] = {**(e.get("live_load") or {}), "hold": True, "why": "deload recommended"}
        elif e.get("intensity") != "carry":
            while len(sets) > int(DELOAD_SHAPE["isolation_max_sets"]["value"]):
                sets.pop()
                removed += 1
            e["live_effort"] = min(int(DELOAD_SHAPE["isolation_rpe"]["value"]), int(e.get("live_effort") or 99))  # a stricter cap stays
    return removed


# ── 3. pain by joint ──────────────────────────────────────────────────────────
def joint_flags(ctx: dict[str, Any], workouts: list[dict[str, Any]] | None, discomfort: set[str]) -> list[dict[str, Any]]:
    """One flag per pain-flagged movement (the classed overlay, #5806) and per repeated-discomfort movement (fatigue_model):
    the joint(s) it loads hardest, its pattern group, and the tier the pain-monitoring rule gives (`avoid` | `reduce`).
    Severity is the latest stated n/10 on that movement's notes (training_notes_pain.stated_severity); 'sharp' or no number
    on a pain flag reads `avoid` (the conservative side), a discomfort flag reads `reduce`."""
    from training import live_safety, selection_engine as se
    from training.training_notes_pain import stated_severity

    notes = live_safety.latest_notes(workouts)
    out = []
    for mid, entry in sorted((ctx["lib"].get("movements") or {}).items()):
        tid = str(entry.get("template_id") or "").upper()
        pain = bool(se.pain_exclusion(entry, ctx["overlay"]))
        if not pain and tid not in discomfort:
            continue
        worst = max((STRESS.get(str((entry.get("joint_stress") or {}).get(j)), -1) for j in JOINTS), default=-1)
        note = notes.get(tid, "")
        # #5861 FIX4: the joint the NOTE names (knee, hip, low back, …) first; the movement's worst joint only as the fallback
        joints, group, site = live_safety.flag_joints(
            note, [j for j in JOINTS if worst >= 1 and _stress(entry, j) == worst], _group(entry.get("pattern"))
        )
        if not joints:
            continue
        sev = stated_severity(note) if note else None
        tier = "avoid" if pain and not live_safety.mild(note) else "reduce"
        out.append(
            {
                "movement_id": mid,
                "title": entry.get("title"),
                "joints": joints,
                "group": group,
                "tier": tier,
                "severity": sev,
                "source": "pain" if pain else "discomfort",
                "site": site,
            }
        )
        from training import live_pain  # #5861 FIX7: the flag's reach — the flagged lift, or the provoking pattern

        out[-1]["scope"] = live_pain.scope(out[-1], set(ctx.get("light_discomfort") or ()), tid)
    return out


def apply_joint_rule(rx: dict[str, Any], ctx: dict[str, Any], rotation: dict[str, Any], flags: list[dict[str, Any]]) -> list[str]:
    """IN PLACE: every exposure a flag reaches (`live_pain` module doc: one joint rule). `avoid`: routed — a reviewed pain-free
    member, else the muscle's reviewed route, else skipped (the muscle zero by design); `hold`: kept, its load held (no step up),
    RPE <= pain_rpe, the stop line. Returns the rationale lines."""
    from training import live_pain, live_safety

    if not flags:
        return []
    lines: list[str] = []
    keep = []
    taken = {str(e.get("movement_key")) for e in rx["exposures"]}
    for e in rx["exposures"]:
        entry = _entry(e.get("movement_key"), ctx)
        hit = live_pain.hit(entry, e, flags, ctx) if entry and e.get("intensity") != "carry" else None  # FIX7: scoped
        swap_of = _avoided_swap(e, ctx, flags)
        if swap_of:
            lines.append(f"skipped (live): {entry.get('title') or e.get('movement_key')} — {swap_of}: the flagged pattern is off today")
            continue
        if not hit:
            keep.append(e)
            continue
        tier, f, joint = hit
        name = entry.get("title") or e.get("movement_key")
        why = f"{f['source']} flag on {f['title']} ({joint.replace('_', ' ')}" + (f", {f['severity']:g}/10" if f["severity"] else "") + ")"
        stop = live_safety.stop_line(f["severity"])  # #5861 FIX4: every lift the pain rule touches carries an in-set stop line
        if tier == "variant":  # #5861 FIX7: the session fit's swap is already low on the flagged joint — the pain-free variant
            keep.append(
                e | {k: v for k, v in live_pain.serve_route(e, str(e["movement_key"]), f, "pain_free_variant").items() if k != "live_swap"}
            )
            lines.append(
                f"kept (live): {name} — {why}: a pain-free variant (low on the flagged joint), RPE <= 8 with the stop line (PAIN_RULE)"
            )
            continue
        if tier == "avoid":  # #5861 FIX7: the pattern is off today — a pain-free same-family member first, else the muscle's route
            new, how = live_pain.variant(e, ctx, rotation, taken, f["joints"]), "pain_free_variant"
            if not new:
                new, how = live_pain.muscle_route(e, ctx, taken, f["joints"]), "muscle_route"
            relax = None if new else live_pain.priority_ceiling(e, ctx, f)
            if relax is not None:
                new, how = live_pain.muscle_route(e, ctx, taken, f["joints"], relax), "priority_route"
            if new:
                taken.add(new)
                served = live_pain.serve_route(e, new, f, how)
                keep.append(served)
                title = (ctx["catalog"].get(new) or {}).get("title") or new
                lines.append(
                    f"swapped (live): {name} -> {title} — {why}: above the mild line the provoking pattern is off today; "
                    f"{how.replace('_', ' ')} ("
                    + (
                        "less stress on the flagged joint than the flagged lift"
                        if how == "priority_route"
                        else "low stress on the flagged joint"
                    )
                    + f"), RPE <= {served['live_effort']} with the stop line (PAIN_RULE, heuristic)"
                )
                continue
            lines.append(f"skipped (live): {name} — {why}: above the mild line, the flagged pattern is off today — no pain-free route")
            continue
        e["live_load"] = {**(e.get("live_load") or {}), "hold": True, "why": f"{joint.replace('_', ' ')} flag"}  # fix round 10
        e["live_effort"] = min(int(PAIN_RULE["pain_rpe"]["value"]), int(e.get("live_effort") or 99))
        e["live_stop"] = stop
        keep.append(e)
        lines.append(f"held (live): {name} — {why}: loads that joint, load held, RPE <= {PAIN_RULE['pain_rpe']['value']}, the stop line on")
    rx["exposures"] = [{k: v for k, v in e.items() if not (k == "template_id" and v is None)} for e in keep]
    from training import live_volume  # fix round 11: what the pain rule took goes back through the ONE spend step

    lines += live_volume.spend_session(rx, ctx, flags)
    return lines


def _avoided_swap(e: dict[str, Any], ctx: dict[str, Any], flags: list[dict[str, Any]]) -> str | None:
    """The session fit's pain swap (`live_session.fit_exposures`, code `pain`) for a movement whose flag reads `avoid`, in the same
    pattern group: the reason it is dropped, else None (#5861 FIX5 — above the mild line nothing of the pattern stands in)."""
    swap = e.get("live_swap") or {}
    if swap.get("code") != "pain":
        return None
    src = _entry(swap.get("from"), ctx)
    mid = ctx["idx"]["to_lib"].get(str(swap.get("from")))
    f = next((f for f in flags if f["movement_id"] == mid and f["tier"] == "avoid"), None)
    if f is None or _group(src.get("pattern")) != _group(_entry(e.get("movement_key"), ctx).get("pattern")):
        return None
    from training import live_pain

    if live_pain._low(_entry(e.get("movement_key"), ctx), f["joints"]):
        return None  # a reviewed same-family member LOW on the flagged joint is the pain-free variant — it stands (live_pain)
    return f"stands in for {f['title']}, pain flag" + (f" {f['severity']:g}/10" if f["severity"] else "")


# ── 4. stacking and stalls ────────────────────────────────────────────────────
def _axial(entry: dict[str, Any]) -> bool:
    from training.live_balance import spine_loading  # #5861 FIX3: ONE definition (rule, gates, generator)

    return spine_loading(entry)


def _sole(e: dict[str, Any], axial: list[dict[str, Any]], ctx: dict[str, Any]) -> bool:
    """The session's only squat (or only hinge) among its spinal-loading compounds — never the one a stacking fix moves."""
    pat = _entry(e.get("movement_key"), ctx).get("pattern")
    return sum(1 for x in axial if _entry(x.get("movement_key"), ctx).get("pattern") == pat) <= 1


def avoid_stacking(rx: dict[str, Any], ctx: dict[str, Any], rotation: dict[str, Any], pinned: set[str]) -> list[str]:
    """IN PLACE: past STACK_RULE axial_per_session spinal-loading squat/hinge compounds in one session, in this order:
    (1) an unpinned accessory is swapped for a member of its pattern with LOW spinal load (unilateral kept unilateral), else
    dropped; (2) an owner-pinned slot is never swapped (his ruling) — it is the movable one: placed off a stacked session
    (`live_balance.place_kb`), here DROPPED if still third (third red team: "kept light" was not a limit); (3) a non-heavy
    anchor, squat before hinge — never the session's ONLY squat or ONLY hinge: each lower session keeps one of each."""
    from training import live_session as ls

    cap = int(STACK_RULE["axial_per_session"]["value"])
    ex = rx["exposures"]
    axial = [e for e in ex if _axial(_entry(e.get("movement_key"), ctx))]
    if len(axial) <= cap:
        return []
    order = [e for e in axial if e.get("kind") == "accessory" and e.get("slot") not in pinned]
    order += [e for e in axial if e.get("kind") == "accessory" and e.get("slot") in pinned]
    # then a non-heavy anchor, squat before hinge: a leg press / hack squat keeps the squat's stimulus at low spinal load,
    # while no machine stands in for a hinge as closely
    order += sorted(
        (e for e in axial if e.get("kind") == "anchor" and e.get("intensity") != "heavy"), key=lambda e: e.get("pattern") != "squat"
    )
    lines, drop = [], []
    taken = {str(e.get("movement_key")) for e in ex if e.get("movement_key")}
    over = len(axial) - cap
    for e in order:
        if over <= 0:
            break
        if e.get("kind") == "accessory" and e.get("slot") in pinned:
            drop.append(e)
            lines.append(f"dropped (live): {_entry(e.get('movement_key'), ctx).get('title')} — the third spine-loading lift (STACK_RULE)")
            over -= 1
            continue
        if e.get("kind") == "anchor" and _sole(e, [x for x in axial if x not in drop], ctx):
            continue  # second red team: never the session's only squat or only hinge
        entry = _entry(e.get("movement_key"), ctx)
        uni = _unilateral(entry)
        new = ls._replacement(e, "stacking", ctx, rotation, taken, limit=("spinal_load", 1), unilateral=uni)
        name = entry.get("title") or e.get("movement_key")
        if new:
            taken.add(new)
            idx = ex.index(e)
            ex[idx] = {k: v for k, v in e.items() if k not in ("template_id", "live_load", "live_effort")} | {
                "movement_key": new,
                "live_swap": {"from": e["movement_key"], "code": "stacking"},
            }
            lines.append(
                f"swapped (live): {name} -> {(ctx['catalog'].get(new) or {}).get('title') or new} — axial stacking: the third "
                "spinal-loading squat/hinge in the session (STACK_RULE, heuristic)"
            )
            over -= 1
        elif e.get("kind") == "accessory":
            drop.append(e)
            lines.append(f"dropped (live): {name} — axial stacking, and no low-spinal-load member is servable; nothing fills it")
            over -= 1
    rx["exposures"] = [e for e in ex if e not in drop]
    return lines


def plan(rx: dict[str, Any], rotation: dict[str, Any], ctx: dict[str, Any], workouts: Any) -> list[str]:
    """The pre-load live programming pass (`live_session.for_live_draft`), IN PLACE, in this order: pain by joint, axial
    stacking, the heavy pull's shape and the lower-volume order, the lead lift (ruling 5), then each exposure's fatigue cost
    (read by the fatigue model that runs next). Returns the rationale lines."""
    from training import live_balance as lb, live_rules, live_rulings, live_shape, selection_live

    sel = (rotation.get("selection") or {}).get("slots") or []
    pinned = {str(s.get("incumbent")) for s in sel if (s.get("owner_pin") or {}).get("state") == "held"}
    pinned |= {sid.split(".", 1)[1] for sid in selection_live.SLOT_OBJECTIVES if sid.startswith(f"{rx.get('session_role')}.")}
    flags = joint_flags(ctx, workouts, (ctx.get("discomfort") or set()) | (ctx.get("light_discomfort") or set()))
    lines = apply_joint_rule(rx, ctx, rotation, flags) + lb.pain_assess(rx, ctx, flags, workouts)
    lines += live_rules.isolation_joint_cap(rx, ctx, flags)  # every isolation lift on a flagged joint: RPE <= 7, stop line
    lines += avoid_stacking(rx, ctx, rotation, pinned)
    lines += live_shape.deadlift_shape(rx) + live_shape.order_lower_volume(rx)  # ruling 5: the heavy pull; squat first
    lines += live_rulings.lead_lift(rx, ctx)  # ruling 5: the squat leads, the deadlift top + back-off at RPE <= 8
    mark_costs(rx, ctx)
    return lines


# ── 1. load safety ────────────────────────────────────────────────────────────


def _cap_effort(note: str, rpe_max: int, clause: str | None) -> str:
    """Line 1 capped at RPE `rpe_max` (inserted when the lift's own note opens without an effort line — the first lift's
    effort sits in the session block) and `clause` as the one reason line."""
    from training import hevy_note_grammar as g, session_block as sb
    from training.lift_note import keep_stricter

    block, own = sb.split(note)
    lines = sb._own_lines(block, own)
    cap = g.effort_line(rpe_max)
    if lines and g.EFFORT_RE.match(lines[0]):
        lines[0] = keep_stricter(lines[0], cap) if _top(lines[0]) > rpe_max else lines[0]
    else:
        lines = [cap] + lines
    text = sb._join(block, lines)
    return sb.add_reason(text, clause) if clause else text


def _top(effort: str) -> float:
    import re

    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", effort)]
    return max(nums) if nums else 99.0


def annotate(blocks: list[Any], rx: dict[str, Any]) -> None:
    """IN PLACE, live only, after the notes are composed: each lift's ONE load reason (`live_load.decide`'s clause) and each
    capped effort (a first session back, a new pattern, the second lift, a deload shape, a joint flag) on its own Hevy note."""
    if not is_live(rx):
        return
    from training import live_balance, live_session as ls, session_block

    guard = {d["key"]: d for d in (rx.get(ls.MARK) or {}).get("load_guard") or []}
    by_key = {e.get("movement_key"): e for e in rx.get("exposures") or []}
    for b in blocks:
        e = by_key.get(b.movement_key) or {}
        d, cap = guard.get(b.movement_key), e.get("live_effort")
        clause = d.get("clause") if d else None
        if cap:
            b.notes = _cap_effort(b.notes or "", int(cap), clause)
        elif clause:
            b.notes = session_block.add_reason(b.notes, clause)
        b.notes = live_balance.assess_note(live_balance.one_effort(b.notes), str(e.get("live_assess") or ""))
        b.notes = live_balance.assess_note(b.notes, str(e.get("live_stop") or ""))  # the in-set stop line under a pain flag
    from training import live_safety

    rx[ls.MARK].setdefault("lines", []).extend(live_safety.no_step(blocks, rx) + live_safety.r3_lines(blocks, rx))
    live_safety.coherent_effort(blocks, rx)


# ── 5. cardio ─────────────────────────────────────────────────────────────────
def aerobic(inputs: Any) -> dict[str, Any] | None:
    """The week's aerobic credit for the draft (#5861 FIX6, owner ruling 12): recorded outside-the-gym minutes with intensity
    evidence (`cardio_model.recorded_aerobic`, read by the cron as `aerobic_record`), cadence-qualified minutes where a source
    has them, and the steps REPORTED (never credited). None when neither steps nor a record were read (unknown is never
    'covered')."""
    from training import cardio_model

    steps = getattr(inputs, "steps_by_day", None) or {}
    rec = getattr(inputs, "aerobic_record", None) or {}
    if not steps and not rec:
        return None
    walked = rec.get("minutes_by_day") or None
    cadence = getattr(inputs, "cadence_minutes_by_day", None)  # FIX3: cadence-qualified minutes count first, where a source has them
    plan_ = cardio_model.aerobic_plan(steps, walk_minutes_by_day=walked, cadence_minutes_by_day=cadence, purposes=("intensity_domain",))
    w = plan_["walking"]
    line = rec.get("line") or "no recorded walks read: intensity unknown, nothing credited"
    if w.get("steps_per_day") is not None:
        line += f"; steps ~{w['steps_per_day']}/day reported as activity, not aerobic credit"
    out = {"volume_covered": plan_["volume_covered"], "walking_min_per_wk": w["moderate_min_per_wk"], "line": line}
    return out | {"steps_per_day": w.get("steps_per_day")}  # #5861 FIX8: ruling 12 — unknown intensity is never a deficit


def cardio_context(ideal: Any) -> dict[str, Any] | None:
    """What the live cardio fit reads from the drafted routine; None in shadow (the cardio block is then built as before)."""
    snap = getattr(ideal, "inputs_snapshot", None) or {}
    rx = snap.get("session_prescription") or {}
    if not is_live(rx):
        return None
    from training import live_session as ls, live_settings, selection_engine as se

    fat = rx.get("fatigue") or {}
    mark = rx.get(ls.MARK) or {}
    return {
        "role": rx.get("session_role"),
        "action": fat.get("action"),
        "state": fat.get("state"),
        "strain": list(fat.get("strain_signals") or []),
        "tripwire": mark.get("symptom_tripwire"),
        "cardio_strain": "cardio_load" in (fat.get("strain_signals") or []),
        "lifting_minutes": (snap.get("session_shape") or {}).get("lifting_minutes"),
        "cap": (getattr(ideal, "caps", None) or {}).get("session_minutes"),
        "aerobic": (rx.get(ls.MARK) or {}).get("aerobic"),
        "host": mark.get("conditioning_host") or SHORT_WEEK_SKIP,
        "settings": live_settings.settings(se.load_library_failsoft()),
    }


def _next_role(role: str | None) -> str | None:
    from training import program_structure as ps

    roles = list(ps.SPLIT_ROLES)
    return roles[(roles.index(role) + 1) % len(roles)] if role in roles else None


def cardio_fit(menu: dict[str, Any], live: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[str]]:
    """The live cardio fit over the menu's pick (`draft_standing_constraint.cardio_block`). Shadow (`live` None): unchanged.
    Live, in order: a hard kind turns easy under a recommended deload or high cardio load, on the heavy lower day or the
    session before it, and (shared cap) on any day but shoulders+arms; an easy block (chosen, or a hard one turned easy) is
    dropped when the week's steps already cover the aerobic volume — the walking IS the easy aerobic (steps first); under the shared cap the minutes fit what lifting leaves,
    and a block under MIN_CARDIO_MINUTES is dropped. Returns (menu or None, rationale lines)."""
    if not live:
        return menu, []
    from training import cardio_menu, live_balance, live_week, selection_engine as se

    menu, lines = live_balance.cardio_machine(menu, se.load_library_failsoft())  # FIX3: a machine the gym has
    kind = menu["kind"]
    shared = bool((live.get("settings") or {}).get("session_cap_includes_cardio"))
    role = live.get("role")
    trip = live.get("tripwire")
    if trip:
        lines.append(live_week.review_line(trip))
    hosts = live_rulings_hosts(live)
    if role in hosts[1:] and kind not in HARD_KINDS and not trip and live.get("action") != "deload_recommended":
        hard = next((k for k in ("intervals", "tempo", "hills") if cardio_menu.fits_machine(k, menu["machine"])), None)
        if hard:  # FIX7 `hard_conditioning_doses` 2: the second host's block is the week's second hard dose
            lines.append(f"cardio (live): {kind} -> {hard} — the week's second hard dose (hard_conditioning_doses=2)")
            kind = hard
    if kind in HARD_KINDS:
        why = None
        if trip:
            why = "a medical stop line is tripped: no hard work until it is reviewed"
        elif live.get("action") == "deload_recommended":
            why = "a deload is recommended"
        elif live.get("cardio_strain"):
            why = "hard cardio is itself a strain signal this week"
        elif live.get("state") in ("strained", "overreached") or {"readiness", "sleep"} & set(live.get("strain") or []):
            why = "recovery is strained (red readiness or a short night): easy work first, hard work waits"
        elif role == "lower_heavy" or _next_role(role) == "lower_heavy":
            why = "never on the heavy lower day or the session before it"
        elif shared and role not in live_rulings_hosts(live):  # FIX7: hard_conditioning_doses (default 1: the host only)
            why = f"the shared cap puts conditioning on {live.get('host', SHORT_WEEK_SKIP)}"
        if why:
            easy = "easy" if cardio_menu.fits_machine("easy", menu["machine"]) else "incline_treadmill_walk"
            lines.append(f"cardio (live): {kind} -> {easy} — {why}")
            kind = easy
    from training import live_rulings  # #5861 FIX6 ruling 4: a gym block only for a named purpose

    keep_, why_ = live_rulings.purposeful_cardio(kind, live, HARD_KINDS)
    if not keep_:
        from training import live_shape

        return None, lines + why_ + live_shape.walk_prompt(live)
    lines += why_
    aer = live.get("aerobic") or {}
    if kind not in HARD_KINDS and aer.get("volume_covered"):
        lines.append(
            f"cardio (live): no easy block — recorded walking already gives ~{aer.get('walking_min_per_wk')} moderate min/wk "
            "(cardio_model.aerobic_plan: recorded activity first, no cardio added without a purpose)"
        )
        return None, lines
    from training import live_shape  # #5861 FIX4: a small gap is the walk's, never a silent shortfall

    covered = live_shape.walk_covers(kind, live)
    if covered:
        return None, lines + covered + live_shape.walk_prompt(live)
    keep, gap = live_balance.easy_gap(kind, live)  # FIX3: an easy block closes the week's gap after the walking credit, no more
    if not keep:
        return None, lines + gap + live_shape.walk_prompt(live)
    lines += gap
    minutes, prog = live_week.cardio_progress(kind, live, cardio_menu.block_minutes(kind))  # week to week: cardio_model.progress
    lines += prog
    if shared and live.get("cap") and live.get("lifting_minutes") is not None:
        room = int(float(live["cap"]) - float(live["lifting_minutes"]))
        gap = live_shape.aerobic_gap(live)  # FIX7: a week the record shows short takes the idle cap minutes (>= 10) as aerobic work
        short = kind not in HARD_KINDS and gap is not None and gap >= int(live_shape.WALK_PROMPT["min_minutes"]["value"])
        if room < (MIN_CARDIO_MINUTES if short else live_balance.min_block(kind, MIN_CARDIO_MINUTES)):  # else a stub under 20
            lines.append(f"cardio (live): no block — the shared {live['cap']}-min cap leaves {max(room, 0)} min after lifting")
            return None, lines + live_shape.walk_prompt(live)
        if room < minutes:
            lines.append(f"cardio (live): {minutes} -> {room} min — the shared {live['cap']}-min cap (session_cap_includes_cardio)")
            minutes = room
    return {**menu, "kind": kind, "live_minutes": minutes}, lines + live_shape.walk_prompt(live, minutes)


def live_rulings_hosts(live: dict[str, Any]) -> list[str]:
    """The week's hard-conditioning mornings (`live_rulings.conditioning_hosts` over the live host)."""
    from training import live_rulings, selection_engine as se

    return live_rulings.conditioning_hosts(str(live.get("host", SHORT_WEEK_SKIP)), se.load_library_failsoft())


def cardio_note(notes: str, live: dict[str, Any] | None, kind: str) -> str:
    """Live only: the review line on a day a medical stop line is tripped, and the machine's name. No symptom warning line on
    any block (owner ruling 10, follow-up)."""
    if live and live.get("tripwire") and live_review_note() not in notes:
        notes = f"{notes}\n{live_review_note()}".strip()
    if live:
        from training import live_balance, selection_engine as se

        notes = live_balance.machine_label(notes, se.load_library_failsoft())  # FIX3: no "Recumbent" without one
    return notes


def live_review_note() -> str:
    """The conditioning note's line on a day a medical stop line is tripped (live_week.symptom_gate): one phone line."""
    return "Stop line flagged: easy only, review."
