"""live_program.py — the PROGRAMMING half of the live policy (#5861, red-team fixes). LIVE only: every entry point returns its
input untouched (or None) unless the draft ran the live session fit (`live_session.MARK` on the prescription, which exists
only when `selection_engine.mode() == "live"`, i.e. the library is `approved`). tests/test_no_live_change_5861_l6.py pins the
served proposed-mode drafts byte for byte.

WHY IT EXISTS. An independent red team (2026-11-12) read the integrated engine's generated weeks as a coach would and graded
them C+: the architecture was right, the weeks were not. Every rule below answers one of its findings, against the GENERATED
week (`scripts/sample_weeks_5861.py`), not the architecture:

  1. LOAD SAFETY (`guard_loads`). The load floor and the double progression only ever raise, so a regressing squat (last
     exposure 4 reps at RPE 9, e1RM sliding) in an overreached week read "Heavier" +20 lb. Under live a load never steps UP on
     a regressing lift, a lift whose last top set was a grind at the bottom of its range, a stalled lift, or on a day the
     fatigue model reads strain or overreach; it HOLDS at the last top set, and steps DOWN (LOAD_POLICY) when the
     e1RM regresses or an anchor's last top set overshot its RPE band. The commit gate reuses the generator's floor audit, so
     the guarded load is written into that audit row (`live_guard`) — a recorded, sanctioned reduction, never a silent one.
  2. DELOAD SHAPE (`fatigue_cost`, read by `fatigue_model.apply_to_session`). A recommended deload cuts the heavy compounds
     first (sets and effort), keeps isolation work, and turns a hard cardio block easy (`cardio_fit`). Under `reduce` the
     trim takes high-fatigue work before low-cost isolation.
  3. PAIN BY JOINT (`joint_flags`, `apply_joint_rule`). A pain or discomfort flag on one movement reaches every movement that
     loads the same joint at moderate or more (the library's joint-stress ratings), for every session while the flag stands —
     not only the named exercise. The pain-monitoring rule (PAIN_RULE) is a labelled heuristic for the owner to confirm.
  4. STACKING AND STALLS (`avoid_stacking`, `stall_scheme`). Past AXIAL_PER_SESSION spinal-loading squat/hinge compounds in
     one session the lowest-priority one is swapped for a low-spinal-load member (a unilateral one for a unilateral slot) or
     dropped; a stalled anchor changes its rep scheme (and its load with it), the stall machinery's own call.
  5. CARDIO (`cardio_context`, `cardio_fit`, `cardio_note`). The cardio model is wired: steps first (an easy block on top of a
     week the steps already cover is dropped), conditioning never on the heavy lower day nor the session before it, hard work
     turned easy under strain or a recommended deload, the `session_cap_includes_cardio` setting (default False: today's
     separate cap), a generic symptom line on conditioning (wording a library setting), and the loss-rate band shown as
     advisory text only (`rate_line` — nothing about nutrition changes).

Every number here is a labelled PLATFORM HEURISTIC (practitioner consensus at best), owner-adjustable; none is validated.
"""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

LOAD_POLICY: dict[str, dict[str, Any]] = {
    "regress_down_pct": {
        "value": 10,
        "label": HEURISTIC,
        "basis": "a lift whose e1RM regresses (fatigue_model: the latest pair both more than 5% under the best before) steps "
        "10% under its last top set — the usual practitioner reset after a regression, not a measured dose",
    },
    "overshoot_rpe": {
        "value": 9.5,
        "label": HEURISTIC,
        "basis": "a last top set logged at 9.5 or more is past an anchor's charter effort band (effort_ceilings): it overshot",
    },
    "overshoot_down_pct": {"value": 5, "label": HEURISTIC, "basis": "an overshoot steps 5% under the last top set (half the reset)"},
    "grind_rpe": {
        "value": 9.0,
        "label": HEURISTIC,
        "basis": "a last top set at RPE 9+ at or under the bottom of the prescribed rep range earned no step: the load holds",
    },
    "evidence_rpe": {
        "value": 9.0,
        "label": HEURISTIC,
        "basis": "second red team (2026-11-13): an e1RM 'regression' is noisy — a stack, an attachment, a grip, a 2.5-lb dumbbell "
        "jump on an isolation lift; heavy and volume rep ranges mixed in one e1RM trend on a compound (the owner run's volume squat "
        "read 'sliding' after a top set at RPE 8.5) — so a regression cuts the load only with EFFORT evidence: the last top set at "
        "RPE 9+ or under the rep range's floor, or a joint flag. A trend alone HOLDS (no step up), never cuts",
    },
    "one_retreat_per_week": {
        "value": 6,
        "label": HEURISTIC,
        "basis": "a lift already cut or stall-reset at an exposure in the last 6 days (the program week) is held at its next "
        "exposure, never cut again: two retreats on one lift in one week is a lot of retreat (red team: the DB row cut twice)",
    },
    "hold_states": {
        "value": ["strained", "overreached"],
        "label": HEURISTIC,
        "basis": "on a day the fatigue model reads strain (2+ signals) or overreach, no load steps up anywhere; an adherence trim "
        "is not a recovery verdict and holds nothing",
    },
}
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
        "basis": "pain at or under 3/10 (the platform's own pain tripwire, training_notes_pain.SEVERITY_THRESHOLD) is allowed "
        "with reduced load on every movement loading that joint; above it, or a 'sharp' note, or no stated number, the "
        "same-pattern movements that load the joint are AVOIDED (swapped for a lower-stress member, else skipped) and the rest "
        "are reduced — a common pain-monitoring rule (owner to confirm the line)",
    },
    "reduce_pct": {"value": 10, "label": HEURISTIC, "basis": "a joint-flag reduction is 10% under the last top set"},
    "reduce_rpe": {"value": 7, "label": HEURISTIC, "basis": "and stops at RPE 7"},
    "joint_level": {"value": "moderate", "label": HEURISTIC, "basis": "a movement 'loads the joint' at moderate or high joint stress"},
}
STACK_RULE: dict[str, dict[str, Any]] = {
    "axial_per_session": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "at most two spinal-loading (moderate or more) squat/hinge compounds in one session: the third is swapped for a "
        "low-spinal-load member or dropped (fatigue_model's axial-stacking finding, acted on)",
    },
}
STALL_RULE: dict[str, dict[str, Any]] = {
    "rep_shift": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "a stalled anchor (no new best e1RM over 3+ exposures at working effort) moves its rep range up by 2 at ~10% "
        "less load — a rep-scheme change, the stall machinery's 'adjust the loading' answer; never more volume in a deficit",
    },
    "load_pct": {"value": 10, "label": HEURISTIC, "basis": "see rep_shift"},
}
SETTINGS_KEY = "programming_settings"
SETTINGS_DEFAULTS: dict[str, Any] = {
    "session_cap_includes_cardio": True,  # #5861 FIX6: owner ruling 1 (2026-11-13), was False
    "symptom_line": "",  # #5861 FIX6: owner ruling 10 — no symptom warning line (the `extended` preset stays available)
    "short_week_rule": "skip_shoulders_arms",
    "behind_schedule_week": False,
}
"""Library-carried settings (`config/exercise_library.json` `programming_settings`), read with these defaults when absent.
`session_cap_includes_cardio` False keeps today's 75-min LIFTING cap with the cardio block apart; True makes the cap cover lifting
+ cardio and puts hard conditioning on the shoulders+arms day. `symptom_line` is the owner's own wording (OWNER DECISION); the default is one phone line (<= 40 characters) so a tempo
note stays inside its 6-line budget (hevy_note_lint L7) — a longer wording still prints, safety over the line budget.
`short_week_rule` `skip_shoulders_arms` (L5's rule) or `slide` (today's sequence) — `live_sequence.SHORT_WEEK_PLANS` (#5861 FIX5). Second red team (2026-11-13),
both OWNER DECISIONS, both off by default: `behind_schedule_week` (live_week.behind_schedule: a shorter 'keep the anchors' week
after a run of missed sessions) and `press_sets` (live_week.press_sets, read there with its default 1 — the charter's one set —
until the library builder carries the key: the shoulders+arms press above one set)."""
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


def is_live(rx: dict[str, Any] | None) -> bool:
    from training.live_session import MARK

    return bool(rx) and MARK in (rx or {})


def settings(lib: dict[str, Any] | None) -> dict[str, Any]:
    """The library's programming settings over SETTINGS_DEFAULTS (a missing key reads its default)."""
    from training.live_balance import SETTINGS_DEFAULTS as FIX3  # #5861 FIX3: the third red team's settings
    from training.live_safety import SETTINGS_DEFAULTS as FIX4_SAFETY  # #5861 FIX4: the fourth red team's settings
    from training.live_shape import SETTINGS_DEFAULTS as FIX4_SHAPE

    got = (lib or {}).get(SETTINGS_KEY) or {}
    from training.live_rulings import SETTINGS_DEFAULTS as FIX6  # #5861 FIX6: the owner's rulings of 2026-11-13

    return {k: got.get(k, v) for k, v in {**SETTINGS_DEFAULTS, **FIX3, **FIX4_SAFETY, **FIX4_SHAPE, **FIX6}.items()}


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
    the surplus-first order (`live_session.surplus_first`). One set per pass, so the cut spreads. `order.adherence` is the
    adherence trim's order (a shorter session, not a recovery verdict): isolation only, surplus first — the compounds that
    hold strength stay whole."""

    def adherence(exposures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [e for e in surplus(exposures) if e.get("live_cost") == "low"]

    def order(exposures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rank = {"high": 0, "moderate": 1}
        comp = sorted((e for e in exposures if e.get("live_cost") in rank), key=lambda e: (rank[e["live_cost"]], e.get("kind") == "anchor"))
        return comp + adherence(exposures)

    order.adherence = adherence  # type: ignore[attr-defined]
    return order


SHORT_WEEK_SKIP = "shoulders_arms"


def deload_shape(exposures: list[dict[str, Any]]) -> int:
    """IN PLACE, a RECOMMENDED deload's reduction (applying the deload itself stays his word): every compound to
    DELOAD_SHAPE compound_sets (back-offs go, the top set stays) at RPE <= compound_rpe, its load held or stepped down;
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
            e["live_effort"] = min(int(DELOAD_SHAPE["compound_rpe"]["value"]), int(e.get("live_effort") or 99))
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
    return out


def _joint_hit(entry: dict[str, Any], flags: list[dict[str, Any]]) -> tuple[str, dict[str, Any], str] | None:
    """(tier, flag, joint) for the strongest flag this movement falls under, else None."""
    level = STRESS[str(PAIN_RULE["joint_level"]["value"])]
    best = None
    for f in flags:
        for j in f["joints"]:
            if _stress(entry, j) < level:
                continue
            tier = "avoid" if f["tier"] == "avoid" and _group(entry.get("pattern")) == f["group"] else "reduce"
            if best is None or (tier == "avoid" and best[0] != "avoid"):
                best = (tier, f, j)
    return best


def apply_joint_rule(rx: dict[str, Any], ctx: dict[str, Any], rotation: dict[str, Any], flags: list[dict[str, Any]]) -> list[str]:
    """IN PLACE: every exposure that loads a flagged joint (module doc 3). `avoid` (above the mild line, "sharp" or no number):
    the flagged PATTERN is off for the session — every member of the flag's pattern group that loads the joint at moderate or
    more is dropped, and so is the session fit's pain swap for the flagged movement itself (#5861 FIX5: no substitute of the
    same pattern); `reduce`: kept, marked for a load cut (`live_load`) and an RPE cap. Returns the rationale lines."""
    from training import live_safety

    if not flags:
        return []
    lines: list[str] = []
    keep = []
    for e in rx["exposures"]:
        entry = _entry(e.get("movement_key"), ctx)
        hit = _joint_hit(entry, flags) if entry and e.get("intensity") != "carry" else None
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
        if tier == "avoid":  # #5861 FIX5 (fifth red team): no moderate-stress member of the same pattern — the pattern is off
            lines.append(f"skipped (live): {name} — {why}: above the mild line, the flagged pattern is off today — nothing fills it")
            continue
        e["live_load"] = {
            **(e.get("live_load") or {}),
            "pct": int(PAIN_RULE["reduce_pct"]["value"]),
            "why": f"{joint.replace('_', ' ')} flag",
        }
        e["live_effort"] = min(int(PAIN_RULE["reduce_rpe"]["value"]), int(e.get("live_effort") or 99))
        e["live_stop"] = stop
        keep.append(e)
        lines.append(f"reduced (live): {name} — {why}: loads that joint, {PAIN_RULE['reduce_pct']['value']}% lighter, RPE <= 7")
    rx["exposures"] = [{k: v for k, v in e.items() if not (k == "template_id" and v is None)} for e in keep]
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


def stall_scheme(rx: dict[str, Any], ctx: dict[str, Any], trends: dict[str, str]) -> list[str]:
    """IN PLACE: a STALLED anchor (fatigue_model's trend: no new best e1RM over 3+ exposures at working effort — never a
    `step_due`, which is the load step's own call) moves its rep range up by STALL_RULE rep_shift and its load down by
    load_pct (`live_load`). The note reads `Now aiming a–b: …`. Returns the rationale lines."""
    shift = int(STALL_RULE["rep_shift"]["value"])
    lines = []
    for e in rx["exposures"]:
        entry = _entry(e.get("movement_key"), ctx)
        tid = str(entry.get("template_id") or "").upper()
        if e.get("kind") != "anchor" or trends.get(tid) != "stalled" or e.get("live_load") or e.get("live_retreated"):
            continue
        for s in e.get("sets") or []:
            if s.get("reps"):
                s["reps"] = [int(s["reps"][0]) + shift, int(s["reps"][1]) + shift]
        lo, hi = e["sets"][0]["reps"]
        e["live_load"] = {"pct": int(STALL_RULE["load_pct"]["value"]), "why": "stall", "stall": [lo, hi]}
        lines.append(
            f"stall (live): {entry.get('title')} — no new best over 3+ exposures: rep range -> {lo}-{hi} at "
            f"{STALL_RULE['load_pct']['value']}% less load (STALL_RULE, heuristic)"
        )
    return lines


TRUNK_FLOOR: dict[str, dict[str, Any]] = {
    "role": {
        "value": "shoulders_arms",
        "label": HEURISTIC,
        "basis": "the week's one trunk-STABILITY exposure (anti-extension / anti-rotation / anti-lateral flexion, not a carry) "
        "rides the shortest session: the template's only trunk work is 2 crunch sets (below the abs MEV) and the carry, and "
        "priority 4 (movement quality, functional resilience) was otherwise unserved",
    },
    "sets": {"value": 2, "label": HEURISTIC, "basis": "two working sets, 8-12 reps, last-listed (the time fit drops it first)"},
}
TRUNK_FUNCTIONS = ("anti_extension", "anti_rotation", "anti_lateral_flexion")


TRUNK_FALLBACK_ORDER: dict[str, tuple[str, ...]] = {
    "loaded_flexion": ("loaded_flexion", "lateral_flexion", "rotation", "anti_extension", "anti_rotation", "anti_lateral_flexion"),
    "lateral_flexion": ("lateral_flexion", "anti_lateral_flexion", "loaded_flexion", "rotation", "anti_rotation", "anti_extension"),
    "rotation": ("rotation", "anti_rotation", "loaded_flexion", "lateral_flexion", "anti_extension", "anti_lateral_flexion"),
}
"""HEURISTIC (practitioner consensus, labelled): when a trunk slot's movement can't be served at home_gym and no member with
the SAME trunk function is servable, the slot takes the nearest other dynamic trunk job in this order rather than leaving
the week's only direct ab work empty (red team / FIX-DATA: an equipment-limited week lost its crunch slot)."""
LIVE_TRUNK_HEVY_TYPES = ("weight_reps", "bodyweight_weighted", "reps_only")
"""Under live a trunk fallback may be a loaded bodyweight movement (`bodyweight_weighted`, e.g. a weighted crunch) — the
shadow selection's loaded-types rule (`variant_rotation.LOADED_HEVY_TYPES`) is unchanged."""


def trunk_fallback(e: dict[str, Any], ctx: dict[str, Any], taken: set[str]) -> str | None:
    """A live-only fallback for an unservable TRUNK accessory (`live_session.fit_exposures`): the best-tier servable movement
    by TRUNK_FALLBACK_ORDER of the SLOT's trunk function (its template incumbent; else the served movement's), never a carry, familiar first. None when the exposure is not a
    trunk slot or nothing is servable."""
    from training import live_session as ls

    tf = _entry(e.get("slot"), ctx).get("trunk_function") or _entry(e.get("movement_key"), ctx).get("trunk_function")  # the slot's job
    order = TRUNK_FALLBACK_ORDER.get(str(tf))
    if e.get("kind") != "accessory" or not order:
        return None
    to_cat = {lid: k for k, lid in ctx["idx"]["to_lib"].items()}
    rank = {t: i for i, t in enumerate("SABCD")}
    best = None
    for lid, entry in sorted((ctx["lib"].get("movements") or {}).items()):
        key = to_cat.get(lid)
        c = ctx["catalog"].get(key or "") or {}
        if not key or key in taken or entry.get("trunk_function") not in order or entry.get("pattern") == "carry":
            continue
        if c.get("hevy_type") not in LIVE_TRUNK_HEVY_TYPES or int(c.get("skill_tier", 99)) > ctx["ceiling"]:
            continue
        if ls._blocked(key, ctx, False) is not None or ls._servable(key, ctx) is not None:
            continue
        r = entry.get("ratings") or {}
        tier = min(rank.get(str((r.get("hypertrophy") or {}).get("tier")), 9), rank.get(str((r.get("functional") or {}).get("tier")), 9))
        loaded = c.get("hevy_type") != "reps_only"  # a loadable drill first: progression by load, not by reps alone
        stable = {"high": 0, "moderate": 1}.get(str(entry.get("stability")), 2)  # a stable drill trains near failure safely
        cand = (order.index(entry["trunk_function"]), not loaded, tier, stable, -int(c.get("sessions") or 0), key)
        best = cand if best is None or cand < best else best
    return best[-1] if best else None


def trunk_floor(rx: dict[str, Any], ctx: dict[str, Any], state: str | None = None) -> list[str]:
    """IN PLACE, live only: on TRUNK_FLOOR's role, one trunk-stability exposure — the best FUNCTIONAL tier among the library's
    non-carry anti-movement drills that the gym has, the catalog can write and the selection could serve (familiar first: no
    load-finding). Purpose-driven, never a filler: skipped on a strained/overreached day, when the session already has one,
    or when nothing is servable. Returns the rationale lines."""
    from training import live_session as ls
    from training.live_rules import bad_day  # #5861 FIX5: a deload-recommended day adds nothing either
    from training.program_structure import EXPOSURES

    host = ctx.get("short_week_host") or TRUNK_FLOOR["role"]["value"]
    if rx.get("session_role") != host or state in ("strained", "overreached") or bad_day(rx) or ctx.get("behind"):
        return []
    if any(_entry(e.get("movement_key"), ctx).get("trunk_function") in TRUNK_FUNCTIONS for e in rx["exposures"]):
        return []
    to_cat = {lid: k for k, lid in ctx["idx"]["to_lib"].items()}
    rank = {t: i for i, t in enumerate("SABCD")}
    best = None
    for lid, entry in sorted((ctx["lib"].get("movements") or {}).items()):
        key = to_cat.get(lid)
        c = ctx["catalog"].get(key or "") or {}
        if entry.get("trunk_function") not in TRUNK_FUNCTIONS or entry.get("pattern") == "carry" or not key:
            continue
        if c.get("hevy_type") in ls.NOT_LIFTS or int(c.get("skill_tier", 99)) > ctx["ceiling"]:
            continue
        if ls._blocked(key, ctx, False) is not None or ls._servable(key, ctx) is not None:
            continue
        tier = rank.get(str(((entry.get("ratings") or {}).get("functional") or {}).get("tier")), 9)
        cand = (tier, -int(c.get("sessions") or 0), key)
        best = cand if best is None or cand < best else best
    if best is None:
        return ["trunk floor (live): no servable trunk-stability drill — nothing added"]
    key = best[2]
    n = int(TRUNK_FLOOR["sets"]["value"])
    rx["exposures"].append(
        {
            "kind": "accessory",
            "pattern": None,
            "slot": "live_trunk_floor",
            "intensity": "accessory",
            "movement_key": key,
            "resolution_note": None,
            "sets": [{"kind": "working", "reps": [8, 12]} for _ in range(n)],
            "rest_seconds": int(EXPOSURES["accessory"]["rest_seconds"]),
            "live_added": "trunk_floor",
            "live_cost": "low",
        }
    )
    title = (ctx["catalog"].get(key) or {}).get("title") or key
    return [f"added (live): {title} {n} x 8-12 — the week's trunk-stability floor (TRUNK_FLOOR, heuristic; priority 4)"]


def short_week_carry(rx: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """IN PLACE, live only: in a short week that skipped shoulders+arms (`live_sequence.SHORT_WEEK_PLANS`), the week's host session (its
    last) takes that day's carry exposure — the owner-pinned weekly carry (the concession ledger's "carries weekly") is not
    lost with the day. Returns the rationale lines."""
    from training import program_structure as ps

    if not ctx.get("short_week_host") or rx.get("session_role") != ctx["short_week_host"]:
        return []
    if SHORT_WEEK_SKIP not in (ctx.get("week_skip") or (SHORT_WEEK_SKIP,)):
        return []
    sa = ps.session_prescription_for_role(SHORT_WEEK_SKIP, catalog_movements=ctx["catalog"])
    carries = [e for e in sa["exposures"] if e.get("intensity") == "carry" and e.get("movement_key")]
    have = {e.get("movement_key") for e in rx["exposures"]}
    add = [e | {"live_added": "short_week_carry", "live_cost": "low"} for e in carries if e["movement_key"] not in have]
    rx["exposures"] += add
    return [
        f"added (live): {(ctx['catalog'].get(e['movement_key']) or {}).get('title')} — short week: the weekly carry moves here" for e in add
    ]


def _record_index(workouts: Any) -> dict[str, list[dict[str, Any]]]:
    """`exercise_history.load_history_indexes()[0]`'s shape (template id -> sessions, most recent first) from the Hevy record."""
    idx: dict[str, list[dict[str, Any]]] = {}
    for w in workouts or []:
        day = str(w.get("date") or str(w.get("sk") or "")[5:15])[:10]
        for x in w.get("exercises") or []:
            sets = [s for s in x.get("sets") or [] if str(s.get("type") or "normal") != "warmup" and s.get("weight_kg")]
            if sets and x.get("template_id"):
                idx.setdefault(str(x["template_id"]).upper(), []).append({"date": day, "sets": sets})
    for rows in idx.values():
        rows.sort(key=lambda r: r["date"], reverse=True)
    return idx


def mark_retreats(rx: dict[str, Any], ctx: dict[str, Any], workouts: Any, trends: dict[str, str]) -> list[str]:
    """IN PLACE (LOAD_POLICY one_retreat_per_week): a lift performed earlier this week whose guard would have cut it then (the
    same rule, judged on the session before that exposure) or whose stall reset applied then is marked `live_retreated` —
    the guard holds it and the stall scheme leaves it. Judged from the Hevy record, so it holds only when the earlier
    session was actually done. Returns the rationale lines."""
    from common.pacific_time import shift_day_key

    from training.exercise_history import previous_load

    target = str(ctx.get("target_date") or "")
    if not target or not workouts:
        return []
    since = shift_day_key(target, -int(LOAD_POLICY["one_retreat_per_week"]["value"]))
    hist = _record_index(workouts)
    lines = []
    for e in rx["exposures"]:
        entry = _entry(e.get("movement_key"), ctx)
        tid = str(entry.get("template_id") or "").upper()
        week = sorted(r["date"] for r in hist.get(tid) or [] if since <= r["date"] < target)
        if not tid or not week:
            continue
        lo = ((e.get("sets") or [{}])[0].get("reps") or [None])[0]
        judged = e | {"live_cost": fatigue_cost(e, ctx), "live_retreated": False}
        prior, done = previous_load(hist, tid, week[0]), previous_load(hist, tid, shift_day_key(week[0], 1))
        cut = (load_decision(judged, trends.get(tid), prior, None, lo) or {}).get("mode") == "down"
        # the cut must have HAPPENED: the earlier exposure's top load sits under the session before it (a guard cut the engine's
        # own lower load already met changed nothing, and holds nothing now)
        cut = cut and prior is not None and done is not None and float(done["lb"]) < float(prior["lb"]) - 0.5
        if cut or (e.get("kind") == "anchor" and trends.get(tid) == "stalled"):
            e["live_retreated"] = True
            lines.append(
                f"one cut a week (live): {entry.get('title') or e.get('movement_key')} — already cut or reset on {week[0]}; held "
                "today (LOAD_POLICY one_retreat_per_week, heuristic)"
            )
    return lines


def plan(rx: dict[str, Any], rotation: dict[str, Any], ctx: dict[str, Any], workouts: Any, sig: dict[str, Any]) -> list[str]:
    """The pre-load live programming pass (`live_session.for_live_draft`), IN PLACE, in this order: pain by joint, axial
    stacking, the stall scheme, then each exposure's fatigue cost (read by the fatigue model that runs next). The trunk floor
    runs after the fatigue model (it reads the day's state). Returns the rationale lines."""
    trends = {tid: str(v.get("trend")) for tid, v in (sig or {}).items()}
    from training import live_week, selection_live

    sel = (rotation.get("selection") or {}).get("slots") or []
    pinned = {str(s.get("incumbent")) for s in sel if (s.get("owner_pin") or {}).get("state") == "held"}
    pinned |= {sid.split(".", 1)[1] for sid in selection_live.SLOT_OBJECTIVES if sid.startswith(f"{rx.get('session_role')}.")}
    from training import (
        live_balance as lb,  # #5861 FIX3
        live_rulings,  # #5861 FIX6: the owner's rulings of 2026-11-13
        live_shape,  # #5861 FIX4
    )

    lines = live_shape.add_slots(rx, ctx)  # the quadriceps slot, BEFORE the pain rule so a knee flag reaches it
    gate = live_rulings.stimulus_gate(rx, ctx, trends)  # ruling 9: added only when stimulus AND performance ask for it
    held = "quadriceps" in (ctx.get("stimulus_hold") or set())
    lines = [ln for ln in lines if not (held and "QUAD_SLOT" in ln)] + gate
    lines += lb.place_kb(rx, ctx, workouts)  # FIX4: placed first, so a pain flag reaches the slot where it lands
    from training import live_rules  # #5861 FIX5

    lines += live_rules.kb_filler(rx, ctx, workouts)  # the KB deadlift as filler: the swing, else nothing
    flags = joint_flags(ctx, workouts, (ctx.get("discomfort") or set()) | (ctx.get("light_discomfort") or set()))
    lines += apply_joint_rule(rx, ctx, rotation, flags) + lb.pain_assess(rx, ctx, flags, workouts)
    lines += live_rules.isolation_joint_cap(rx, ctx, flags)  # every isolation lift on a flagged joint: RPE <= 7, stop line
    lines += live_week.kb_slot(rx, ctx)  # the kettlebell slot names its implement, capped at RPE 7-8 (before stacking)
    lines += lb.allocate(rx, ctx)  # volume by priority: at/over-MAV isolation gives, priority muscles at MEV + 2 take (FIX4)
    lines += live_week.press_sets(rx, ctx)  # FIX4: the week's allocation already counted the press option's sets
    lines += live_rulings.arms_top_up(rx, ctx, workouts)  # FIX6 ruling 3: the short week's arms counted from the record
    lines += avoid_stacking(rx, ctx, rotation, pinned)
    lines += mark_retreats(rx, ctx, workouts, trends)
    lines += stall_scheme(rx, ctx, trends)
    lines += short_week_carry(rx, ctx)
    lines += live_shape.deadlift_shape(rx, ctx["lib"]) + live_shape.order_lower_volume(rx)  # FIX4: the heavy pull, squat first
    lines += live_rulings.lead_lift(rx, ctx)  # FIX6 ruling 5: squat and deadlift never both maximal in one session
    mark_costs(rx, ctx)
    return lines


# ── 1. load safety ────────────────────────────────────────────────────────────
def effort_evidence(previous: dict[str, Any] | None, rep_lo: int | None) -> bool:
    """LOAD_POLICY evidence_rpe: the last top set was a grind (RPE 9+) or fell under the rep range's floor."""
    rpe, reps = (previous or {}).get("rpe"), (previous or {}).get("reps")
    grind = rpe is not None and float(rpe) >= float(LOAD_POLICY["evidence_rpe"]["value"])
    return grind or bool(reps and rep_lo and int(reps) < int(rep_lo))


def load_decision(
    e: dict[str, Any], trend: str | None, previous: dict[str, Any] | None, state: str | None, rep_lo: int | None
) -> dict[str, Any] | None:
    """What the guard does to one exposure's load: {mode: down|hold, pct, why, clause} or None (the engine's load stands).
    `previous` is Hevy's PREVIOUS (`exercise_history.previous_load`): lb, reps, rpe. Second red team (2026-11-13): a regression
    cuts only with effort evidence (`effort_evidence`) — a trend alone holds; a lift already cut once this week
    (`live_retreated`, `mark_retreats`) holds."""
    if not previous or not previous.get("lb"):
        return None
    rpe, reps = previous.get("rpe"), previous.get("reps")
    mark = e.get("live_load") or {}
    said = f"{int(reps)} reps was RPE {float(rpe):g}" if rpe is not None and reps else None
    if e.get("live_retreated"):
        return {"mode": "hold", "pct": 0, "why": "cut once already this week"}
    pct, why, noisy = 0, None, False
    if trend == "regressing":
        if effort_evidence(previous, rep_lo):
            pct, why = int(LOAD_POLICY["regress_down_pct"]["value"]), "strength sliding"
        else:
            noisy = True  # a trend alone on an isolation / machine lift: hold, never cut
    elif e.get("kind") == "anchor" and rpe is not None and float(rpe) >= float(LOAD_POLICY["overshoot_rpe"]["value"]):
        pct, why = int(LOAD_POLICY["overshoot_down_pct"]["value"]), said
    if mark.get("pct") and int(mark["pct"]) > pct:
        pct, why = int(mark["pct"]), str(mark.get("why"))
    if pct:
        return {"mode": "down", "pct": pct, "why": why, "stall": mark.get("stall")}
    if noisy:
        return {"mode": "hold", "pct": 0, "why": "trend down, effort fine"}
    if state in LOAD_POLICY["hold_states"]["value"] or mark.get("hold"):
        return {"mode": "hold", "pct": 0, "why": "recovery first"}
    if trend == "stalled":
        return {"mode": "hold", "pct": 0, "why": "stalled, no step"}
    if rpe is not None and float(rpe) >= float(LOAD_POLICY["grind_rpe"]["value"]) and reps and rep_lo and int(reps) <= int(rep_lo):
        return {"mode": "hold", "pct": 0, "why": said}
    return None


def guard_loads(
    blocks: list[Any],
    rx: dict[str, Any],
    load_floors: dict[str, Any],
    history_index: dict[str, list],
    movements: dict[str, Any],
    target_date: str,
    rationale: list[str],
) -> list[dict[str, Any]]:
    """IN PLACE, live only, AFTER the floor and the double progression and BEFORE the back-offs and warm-ups (so both follow
    the guarded top set): no working set above the guard's cap (module doc 1). The audit row the commit gate reuses gets the
    guarded `floor_kg` and a `live_guard` record, and its progression is marked held so the note never says "Heavier".
    Never raises a load. Returns the decisions (also on `rx[live_session.MARK]["load_guard"]`)."""
    if not is_live(rx):
        return []
    from training import live_session as ls, live_week
    from training.exercise_history import previous_load

    live_week.kb_seed(blocks, rx, history_index, movements, target_date, rationale)  # the bell he swings, never "find the load"
    trends = (rx.get(ls.MARK) or {}).get("trends") or {}
    by_key = {e.get("movement_key"): e for e in rx.get("exposures") or []}
    state = (rx.get("fatigue") or {}).get("state")
    rows = (load_floors or {}).get("movements") or {}
    out = []
    for b in blocks:
        e = by_key.get(b.movement_key) or {}
        entry = movements.get(b.movement_key) or {}
        tid = str(entry.get("hevy_template_id_hint") or "").upper()
        if not e or not tid or e.get("intensity") == "carry":
            continue
        work = [s for s in b.sets if str(getattr(s, "type", "") or "normal") != "warmup" and getattr(s, "weight_kg", None)]
        if not work:
            continue
        reps = [int(getattr(s, "rep_range_start", 0) or 0) for s in work]
        prev = previous_load(history_index, tid, target_date)
        d = load_decision(e, trends.get(tid), prev, state, min(reps) if reps else None)
        if not d or prev is None:
            continue
        prev_kg = float(prev["lb"]) * 0.45359237
        cap = prev_kg if d["mode"] == "hold" else _floor_to_implement(prev_kg * (1 - d["pct"] / 100.0), entry.get("equipment"))
        top = max(float(s.weight_kg) for s in work)
        if (top - cap) / 0.45359237 < 0.5:  # under half a pound apart: the same load on the rack
            continue
        for s in work:
            if float(s.weight_kg) > cap:
                s.weight_kg = cap
        hi = max((int(getattr(s, "rep_range_end", 0) or 0) for s in work), default=0)
        # a held load whose PREVIOUS reached the top of the range at RPE <= 8.5: the composer's own held-top line (set 1 → the
        # step on later sets, the session's load rule) is the reason — the start load holds, an easy set 1 still steps
        held_top = d["mode"] == "hold" and hi and int(prev.get("reps") or 0) >= hi and float(prev.get("rpe") or 99) <= 8.5
        rec = {"key": b.movement_key, "from_kg": round(top, 2), "to_kg": round(cap, 2), **d, "held_top": bool(held_top)}
        out.append(rec)
        row = rows.get(b.movement_key)
        if row is not None:
            row["live_guard"] = rec | {"rule": "live_program.LOAD_POLICY (heuristic)"}
            row["floor_kg"] = min(float(row.get("floor_kg") or cap), cap)
            prog = row.get("progression") or {}
            row["progression"] = {**prog, "basis": "hold", "changes": [], "live_guard": True}
        lb = lambda kg: f"{round(kg / 0.45359237 * 2) / 2:g} lb"  # noqa: E731
        rationale.append(
            f"load (live): {(entry.get('title') or b.movement_key)} {lb(top)} -> {lb(cap)} — {d['mode']}"
            + (f" {d['pct']}% under the last top set ({prev['lb']:g} lb)" if d["pct"] else " at the last top set")
            + f": {d['why']} (last {prev['lb']:g} lb x {prev.get('reps')} @ RPE {prev.get('rpe')}; LOAD_POLICY, heuristic)"
        )
    if ls.MARK in rx:
        rx[ls.MARK]["load_guard"] = out
    return out


def _floor_to_implement(kg: float, equipment: str | None) -> float:
    """`kg` rounded DOWN to the implement's step (a down-step never rounds back up past its cut); a stack with no fixed step
    rounds down on the 5-lb grid (`rep_scheme.load_step_kg`)."""
    import math

    from training.rep_scheme import implement_step_lb, load_step_kg

    lb = kg / 0.45359237
    step = implement_step_lb(equipment, lb)
    if not step:
        return load_step_kg(kg, down=True)
    return math.floor(lb / step + 1e-9) * step * 0.45359237


def _clause(d: dict[str, Any]) -> str:
    from training import session_block

    if d.get("stall"):
        lo, hi = d["stall"]
        return f"Now aiming {lo}–{hi}: stalled, lighter reset."
    if d["mode"] == "down":
        return session_block.applied_clause("weight_lbs", lighter=True, reason=str(d["why"])) or "Lighter today."
    line = f"Same load: {d['why']}."
    return line if len(line) <= session_block.CLAUSE_MAX_CHARS else "Same load: recovery first."


def _cap_effort(note: str, rpe_max: int, clause: str | None, band: Any = None) -> str:
    """Line 1 capped at RPE `rpe_max` (inserted when the lift's own note opens without an effort line — the first lift's
    effort sits in the session block) and `clause` as the one reason line. `band` (lo, hi) renders the cap as a range."""
    from training import hevy_note_grammar as g, session_block as sb
    from training.lift_note import keep_stricter

    block, own = sb.split(note)
    lines = sb._own_lines(block, own)
    cap = g.effort_line(tuple(band) if band and int(band[-1]) <= rpe_max else rpe_max)
    if lines and g.EFFORT_RE.match(lines[0]):
        lines[0] = keep_stricter(lines[0], cap) if _top(lines[0]) > rpe_max else lines[0]
    else:
        lines = [cap] + lines
    text = sb._join(block, lines)
    return sb.add_reason(text, clause) if clause else text


def _novel_cap(note: str, e: dict[str, Any]) -> str:
    """#5861 FIX5 (fifth red team: a new preacher curl at "RPE 8–9, last set 9–10, find the load"): a lift whose rows carry no
    load on file — the "find the load" feeler, i.e. new to him — starts at the novel-again cap (NOVEL_START rpe), isolation
    included. The kettlebell slot keeps its own band."""
    from training import hevy_note_grammar as g
    from training.live_week import NOVEL_START

    if g.PICK_LOAD_OPEN_TAIL not in note or e.get("live_kb"):
        return note
    cap = int(NOVEL_START["rpe"]["value"])
    e["live_effort"] = min(cap, int(e.get("live_effort") or 99))
    return _cap_effort(note, cap, None)


def _top(effort: str) -> float:
    import re

    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", effort)]
    return max(nums) if nums else 99.0


def annotate(blocks: list[Any], rx: dict[str, Any]) -> None:
    """IN PLACE, live only, after the notes are composed: each guarded lift's reason line (`Lighter today: …`, `Same load:
    …`, `Now aiming a–b: …`) and each capped effort (deload shape, a joint flag) on its own Hevy note."""
    if not is_live(rx):
        return
    from training import live_balance, live_session as ls, live_week, session_block

    guard = {d["key"]: d for d in (rx.get(ls.MARK) or {}).get("load_guard") or []}
    by_key = {e.get("movement_key"): e for e in rx.get("exposures") or []}
    for b in blocks:
        e = by_key.get(b.movement_key) or {}
        d, cap = guard.get(b.movement_key), e.get("live_effort")
        clause = _clause(d) if d and not d.get("held_top") else None
        if cap:
            b.notes = _cap_effort(b.notes or "", int(cap), clause, e.get("live_effort_band"))
        elif clause:
            b.notes = session_block.add_reason(b.notes, clause)
        if e.get("live_kb"):
            b.notes = live_week.kb_note(b.notes or "")
        b.notes = live_balance.assess_note(live_balance.one_effort(b.notes), str(e.get("live_assess") or ""))  # FIX3
        b.notes = live_balance.assess_note(b.notes, str(e.get("live_stop") or ""))  # FIX4: the in-set stop line
        b.notes = _novel_cap(b.notes or "", e)  # FIX5: a lift with no load on file (new to him) starts at RPE <= 7
    from training import live_safety, selection_engine as se  # #5861 FIX4: no load step on a held lift; one effort; stop line

    rx[ls.MARK].setdefault("lines", []).extend(live_safety.no_step(blocks, rx))
    live_safety.coherent_effort(blocks, rx)
    live_safety.lifting_day_symptom(blocks, settings(se.load_library_failsoft()))


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
    return {"volume_covered": plan_["volume_covered"], "walking_min_per_wk": w["moderate_min_per_wk"], "line": line}


def rate_line(fatigue: dict[str, Any] | None, sleep_hours: Any) -> str | None:
    """The loss-rate band as ADVISORY text for the rationale (`live_balance.rate_band`, L5's proposal): nothing
    reads it back, no kcal or target changes — the live rate and titration are untouched (owner decision to wire)."""
    from training.live_balance import rate_band

    band = rate_band(fatigue, sleep_hours)  # #5861 FIX3: the owner's body_fat_tier and rate_band_mode settings
    lo, hi = band["band_pct_bw_per_wk"]
    how = "advisory only, not applied" if band["mode"] == "advisory" else "recorded on the draft for a nutrition reader; none reads it yet"
    return f"rate band ({how}): {lo}-{hi} %BW/wk — {band['reason']}"


def cardio_context(ideal: Any) -> dict[str, Any] | None:
    """What the live cardio fit reads from the drafted routine; None in shadow (the cardio block is then built as before)."""
    snap = getattr(ideal, "inputs_snapshot", None) or {}
    rx = snap.get("session_prescription") or {}
    if not is_live(rx):
        return None
    from training import live_session as ls, selection_engine as se

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
        "settings": settings(se.load_library_failsoft()),
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
        elif shared and role != live.get("host", SHORT_WEEK_SKIP):
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
        if room < live_balance.min_block(kind, MIN_CARDIO_MINUTES):  # an easy stub under 20 min is worthless
            lines.append(f"cardio (live): no block — the shared {live['cap']}-min cap leaves {max(room, 0)} min after lifting")
            return None, lines + live_shape.walk_prompt(live)
        if room < minutes:
            lines.append(f"cardio (live): {minutes} -> {room} min — the shared {live['cap']}-min cap (session_cap_includes_cardio)")
            minutes = room
    return {**menu, "kind": kind, "live_minutes": minutes}, lines + live_shape.walk_prompt(live, minutes)


def cardio_note(notes: str, live: dict[str, Any] | None, kind: str) -> str:
    """Live only, a conditioning (hard) block: the owner-wordable symptom line (`programming_settings.symptom_line`) as the
    note's last line. Generic on purpose — no condition named, no heart-rate number (owner rulings)."""
    if live and live.get("tripwire") and live_review_note() not in notes:
        notes = f"{notes}\n{live_review_note()}".strip()
    if live:
        from training import live_balance, selection_engine as se

        notes = live_balance.machine_label(notes, se.load_library_failsoft())  # FIX3: no "Recumbent" without one
    if not live or kind not in HARD_KINDS:
        return notes
    from training.live_safety import symptom_text

    line = symptom_text(live.get("settings"))  # #5861 FIX4: a preset name (`extended`) or the owner's literal wording
    return f"{notes}\n{line}".strip() if line and line not in notes else notes


def live_review_note() -> str:
    """The conditioning note's line on a day a medical stop line is tripped (live_week.symptom_gate): one phone line."""
    return "Stop line flagged: easy only, review."
