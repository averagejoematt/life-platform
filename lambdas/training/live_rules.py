"""live_rules.py — the fifth red team's SESSION fixes (#5861 FIX5). LIVE only: every entry point is reached from a live hook
(`live_session.for_live_draft`, `live_program.plan` / `annotate`, `live_week.symptom_gate`, `fatigue_model.movement_signals`
through `live_session`), each of which returns before reading anything unless the draft ran the live session fit
(`live_session.MARK`, which exists only when the exercise library is `approved`). tests/test_no_live_change_5861_l6.py pins the
served proposed-mode drafts byte for byte.

WHY IT EXISTS. A fifth independent red team (2026-11-13, B-) read the generated weeks as a coach would:

  1. THE SET CAP (`fit_set_cap`). The short week piled the carry, the trunk floor and the kettlebell slot onto one session with
     no set guard, and `full_body_session` asserted (`total_sets 23 > cap 20`) — a crash. Every live session is now held to the
     week grid's session set ceiling: added work goes first, then accessory sets (drop, don't shave), never an anchor's top set.
  2. FULL-BODY DAYS (`full_body`). A 3-day or 2-day week (`live_sequence.SHORT_WEEK_PLANS`) gives a session its partner role's
     anchors, so legs and the upper body each train twice — not an upper half and a lower half.
  3. NO ADDED WORK ON A BAD DAY (`no_added_work`). The quadriceps slot (a leg extension "first time in 18 weeks") was added on a
     deload-recommended week and on a red, short-sleep morning; the kettlebell slot moved onto another session the same day.
     On a strained, overreached or deload-recommended day nothing is ADDED: the quadriceps slot, the trunk floor and a relocated
     kettlebell slot wait. (`kb_slot_under_strain` — today's default `as_today` — still governs the slot in its HOME session;
     the fourth and fifth red teams both recommend `drop`.)
  4. SAME-JOINT ISOLATION (`isolation_joint_cap`). Under a pain or discomfort flag, every isolation lift working the flagged joint
     is capped at RPE 7 with the in-set stop line, whatever the joint data says (triceps work served to RPE 9-10 under an
     elbow flag).
  5. "SORE" IS DISCOMFORT (`note_class`). The note layer's net leaves out burn / sore / tight on purpose (#5800), so "elbow a bit
     sore 2/10" read as nothing at all. The ENGINE reads a joint-located sore / achy / tight note at or under the mild line as
     discomfort — kept, lighter (the joint rule's reduce tier). The note layer's own class is unchanged.
  6. THE KETTLEBELL DEADLIFT AS FILLER (`kb_filler`). One bell between the feet sits far under a working effort for a lifter who
     already deadlifts a barbell: the slot serves the swing when it is servable, else it is dropped.
  7. THE SELF-REPORTED STOP LINES (`self_report`). The symptom line says "Stop, log it." — a Hevy note naming a racing or
     irregular heartbeat, or fainting / near-fainting / dizziness, in the last fortnight now trips the draft's symptom gate (no
     hard cardio, a review line). The platform tripwire's own palpitations / syncope arms stay `unknown` (their input is the
     check-in lane's, #5819).

Every number here is a labelled PLATFORM HEURISTIC (practitioner consensus at best), owner-adjustable; none is validated.
"""

from __future__ import annotations

import re
from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

SET_CAP: dict[str, Any] = {
    "added_first": ("quad_slot", "trunk_floor", "kb_slot_moved", "short_week_carry"),
    "accessory_floor": 2,
    "anchor_floor": 2,
    "label": HEURISTIC,
    "basis": "the week grid's session set ceiling (20, owner 2026-09-30) holds every live session: live additions go first "
    "(last-listed first), then accessory sets surplus-last-listed first down to two, then whole accessories (drop, don't shave), "
    "then an anchor's back-offs down to two; an anchor's top set never",
}
FULL_BODY: dict[str, Any] = {
    "partner_sets": 2,
    "label": HEURISTIC,
    "basis": "a full-body day's second half: the partner role's anchors at two working sets each (the session still fits the set "
    "cap and the 75 minutes; practitioner consensus for a 2-3 day full-body week)",
}
JOINT_ISOLATION: dict[str, tuple[str, ...]] = {
    "elbow": ("triceps_extension", "curl"),
    "shoulder": ("lateral_raise", "rear_delt", "shoulder_rotation", "chest_fly"),
    "wrist": ("curl",),
    "knee": ("leg_extension", "leg_curl"),
    "hip": ("hip_abduction", "hip_adduction", "hip_extension"),
}
"""Joint -> the isolation patterns that WORK it (heuristic, practitioner consensus): under a flag on the joint each is capped at
PAIN_RULE reduce_rpe with the stop line, independent of the library's joint-stress rating."""
DISCOMFORT_WORDS = r"\b(?:sore(?:ness)?|ach(?:e|es|ing|y|ey)|tight(?:ness)?|cranky|niggl\w*|tweaky)\b"
"""A joint-located sensation word the engine reads as discomfort at or under the mild line (heuristic)."""
KB_FILLER: dict[str, Any] = {
    "label": HEURISTIC,
    "basis": "the kettlebell deadlift is an entry drill into the swing (owner ruling #5774); for a lifter whose record holds a "
    "loaded barbell or trap-bar deadlift it trains a hinge he already loads far heavier — one bell sits under a working effort "
    "(fifth red team: two sets with one light bell is junk volume counted as glute sets). The swing serves when "
    "servable; else the slot is dropped",
}
SELF_REPORT: dict[str, Any] = {
    "window_days": 14,
    "palpitations": r"palpitation\w*|heart (?:was )?(?:racing|pounding|fluttering|skipping)|racing heart|irregular (?:heart ?beat|pulse|rhythm)|skipped beats?|flutter\w*",
    "syncope": r"faint\w*|passed out|black(?:ed)? out|syncop\w*|dizz\w*|light ?headed\w*|nearly (?:fell|went down)",
    "label": HEURISTIC,
    "basis": "the stop line asks him to stop and LOG it: a Hevy note in the last fortnight naming a racing or irregular heartbeat "
    "(palpitations) or fainting, near-fainting or dizziness (syncope / presyncope) is that log",
}


def _entry(key: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    lid = ctx["idx"]["to_lib"].get(str(key)) if key else None
    return ((ctx["lib"].get("movements") or {}).get(lid) or {}) if lid else {}


def _title(key: Any, ctx: dict[str, Any]) -> str:
    return str((ctx["catalog"].get(key) or {}).get("title") or key)


# ── 1. the session set cap ───────────────────────────────────────────────────
def _pinned(rx: dict[str, Any]) -> set[str]:
    from training import selection_live

    role = str(rx.get("session_role") or "")
    return {sid.split(".", 1)[1] for sid in selection_live.SLOT_OBJECTIVES if sid.startswith(f"{role}.")}


SURPLUS_FIRST: tuple[str, ...] = ("lateral_raise", "rear_delt", "reverse_pec_deck", "face_pull", "reverse_fly")
"""#5861 FIX7 (sixth red team: the set cap took triceps under MEV while 5 lateral-raise sets stood): the session set cap trims the
week's habitual surplus — side- and rear-delt isolation (the shoulders sit near MAV in every template week) — before any other
accessory. Heuristic; re-tuned at the block retro with the allocation."""


def fit_set_cap(rx: dict[str, Any], cap: Any) -> list[str]:
    """IN PLACE: hold the session at `cap` working sets (SET_CAP). Returns the rationale lines."""
    if not cap:
        return []
    ex = rx["exposures"]
    total = sum(len(e.get("sets") or []) for e in ex)
    if total <= int(cap):
        return []
    before, gone = total, []
    added = [e for e in reversed(ex) if e.get("live_added") in SET_CAP["added_first"]]
    added.sort(key=lambda e: SET_CAP["added_first"].index(e["live_added"]))
    pinned = _pinned(rx)
    acc = [e for e in reversed(ex) if e.get("kind") == "accessory" and not e.get("live_added") and e.get("slot") not in pinned]
    acc += [e for e in reversed(ex) if e.get("kind") == "accessory" and not e.get("live_added") and e.get("slot") in pinned]
    acc.sort(key=lambda e: not any(k in str(e.get("movement_key")) for k in SURPLUS_FIRST))  # FIX7: delt surplus goes first
    for e in added:  # 1. live additions, whole
        if total <= int(cap):
            break
        total -= len(e["sets"])
        gone.append(e)
    for e in acc:  # 2. accessory sets to the floor, then the accessory whole
        while total > int(cap) and len(e["sets"]) > int(SET_CAP["accessory_floor"]):
            e["sets"].pop()
            total -= 1
        if total > int(cap):
            total -= len(e["sets"])
            gone.append(e)
    for e in [x for x in ex if x.get("kind") == "anchor"]:  # 3. an anchor's back-offs, never its top set
        while total > int(cap) and len(e["sets"]) > int(SET_CAP["anchor_floor"]):
            idx = [i for i, s in enumerate(e["sets"]) if s.get("kind") != "top"]
            if not idx:
                break
            e["sets"].pop(idx[-1])
            total -= 1
    rx["exposures"] = [e for e in ex if not any(e is g for g in gone)]
    names = ", ".join(str(e.get("movement_key")) for e in gone)
    return [f"set cap (live): {before} working sets > the {cap}-set session ceiling -> {total}" + (f"; dropped {names}" if names else "")]


# ── 2. full-body days ────────────────────────────────────────────────────────
def full_body(rx: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """IN PLACE, a short week's full-body day: the partner role's ANCHORS join the session at FULL_BODY partner_sets each (a
    movement the session already serves is not doubled). Returns the rationale lines."""
    partner = ctx.get("partner")
    if not partner:
        return []
    from training import program_structure as ps

    other = ps.session_prescription_for_role(partner, catalog_movements=ctx["catalog"])
    have = {e.get("movement_key") for e in rx["exposures"]}
    add = []
    for e in other["exposures"]:
        if e.get("kind") != "anchor" or not e.get("movement_key") or e["movement_key"] in have:
            continue
        sets = list(e.get("sets") or [])[: int(FULL_BODY["partner_sets"])]
        add.append(e | {"sets": sets, "live_full_body": partner})
    rx["exposures"] += add
    names = ", ".join(_title(e["movement_key"], ctx) for e in add)
    return (
        [f"full body (live): + {partner}'s anchors ({names}) at {FULL_BODY['partner_sets']} sets — a short week's full-body day"]
        if add
        else []
    )


# ── 3. no added work on a bad day ────────────────────────────────────────────
def bad_day(rx: dict[str, Any]) -> bool:
    fat = rx.get("fatigue") or {}
    return fat.get("state") in ("strained", "overreached") or fat.get("action") == "deload_recommended"


def no_added_work(rx: dict[str, Any]) -> list[str]:
    """IN PLACE, after the fatigue model: on a strained / overreached / deload-recommended day the live ADDITIONS wait — the
    quadriceps slot and a relocated kettlebell slot (the trunk floor checks `bad_day` itself). Returns the rationale lines."""
    if not bad_day(rx):
        return []
    gone = [e for e in rx["exposures"] if e.get("live_added") in ("quad_slot", "kb_slot_moved", "week_floor")]  # FIX7: + floor
    if not gone:
        return []
    rx["exposures"] = [e for e in rx["exposures"] if e not in gone]
    state = (rx.get("fatigue") or {}).get("state")
    return [f"waits (live): {', '.join(str(e.get('movement_key')) for e in gone)} — added work, and today is {state}: nothing is added"]


def waited(lines: list[str]) -> list[str]:
    """The movement keys a `no_added_work` line names."""
    return [k for ln in lines if ln.startswith("waits (live): ") for k in ln[len("waits (live): ") :].split(" — ", 1)[0].split(", ")]


# ── 4. same-joint isolation under a flag ─────────────────────────────────────
def isolation_joint_cap(rx: dict[str, Any], ctx: dict[str, Any], flags: list[dict[str, Any]]) -> list[str]:
    """IN PLACE: every isolation exposure whose pattern works a flagged joint (JOINT_ISOLATION) is capped at PAIN_RULE reduce_rpe
    and carries the stop line — the data-independent half of the pain rule. Returns the rationale lines."""
    from training import live_safety
    from training.live_program import PAIN_RULE

    rpe = int(PAIN_RULE["reduce_rpe"]["value"])
    lines = []
    for e in rx["exposures"]:
        entry = _entry(e.get("movement_key"), ctx)
        if entry.get("job") != "isolation" or e.get("intensity") == "carry":
            continue
        from training.live_program import _group  # #5861 FIX7: above the mild line every same-joint isolation; at/under it only the

        # provoking pattern's; a lift-only (<= 2/10 discomfort) flag never

        f = next(
            (
                f
                for f in flags
                for j in f["joints"]
                if entry.get("pattern") in JOINT_ISOLATION.get(j, ())
                and f.get("scope") != "lift"
                and (f.get("tier") == "avoid" or _group(entry.get("pattern")) == f.get("group"))
            ),
            None,
        )
        if f is None or (int(e.get("live_effort") or 99) <= rpe and e.get("live_stop")):
            continue
        e["live_effort"] = min(rpe, int(e.get("live_effort") or 99))
        e["live_stop"] = e.get("live_stop") or live_safety.stop_line(f["severity"])
        lines.append(
            f"capped (live): {entry.get('title') or e.get('movement_key')} — isolation on the flagged {'/'.join(f['joints'])}: RPE <= {rpe}"
        )
    return lines


# ── 5. the engine's note class ───────────────────────────────────────────────
LIGHT = "light_discomfort"
"""The engine's own class (module doc 5): light-and-keep — the joint rule reduces the lift; nothing swaps it out."""


def note_class(note: str | None) -> str | None:
    """The engine's read of one note: the note layer's class (`training_notes_pain.pain_class`, #5800), or — when that is None —
    `LIGHT` for a joint-located sore / achy / tight note at or under the mild line (module doc 5)."""
    from training import live_safety
    from training.live_program import PAIN_RULE
    from training.training_notes_pain import _negated, pain_class, stated_severity

    text = str(note or "")
    cls = pain_class(text)
    if cls is not None or not live_safety.note_site(text):
        return cls
    low = " ".join(text.lower().split())
    hit = [m for m in re.finditer(DISCOMFORT_WORDS, low) if not _negated(low, m.start(), m.end())]
    sev = stated_severity(text)
    return LIGHT if hit and (sev is None or sev <= float(PAIN_RULE["mild_max"]["value"])) else None


# ── 6. the kettlebell deadlift as filler ─────────────────────────────────────
def deadlifts(workouts: Any, ctx: dict[str, Any]) -> bool:
    """The record holds a loaded working set of a primary hinge (a barbell or trap-bar deadlift: the library's strength lift)."""
    tids = {
        str(e.get("template_id") or "").upper()
        for e in (ctx["lib"].get("movements") or {}).values()
        if e.get("pattern") == "hinge" and (e.get("objective_inputs") or {}).get("strength_lift")
    }
    return any(
        str(x.get("template_id") or "").upper() in tids and any(float(s.get("weight_kg") or 0) > 0 for s in x.get("sets") or [])
        for w in workouts or []
        for x in w.get("exercises") or []
    )


def kb_choice(ctx: dict[str, Any], workouts: Any) -> tuple[str | None, str | None]:
    """(the movement the kettlebell slot serves in place of the KB deadlift, the reason) under KB_FILLER: the deadlift itself for a
    lifter who does not deadlift (no reason), else the swing when servable (equipment, pain, gates), else None (drop the slot)."""
    from training import kb_entry, live_session as ls

    if not deadlifts(workouts, ctx):
        return kb_entry.ENTRY, None
    swing = kb_entry.TARGET
    if swing in ctx["catalog"] and ls._blocked(swing, ctx, False) is None and ls._servable(swing, ctx) is None:
        return swing, "the KB deadlift is filler for a lifter who deadlifts — the swing serves (KB_FILLER, heuristic)"
    return None, "the KB deadlift is filler for a lifter who deadlifts, and the swing is not servable (KB_FILLER, heuristic)"


def kb_filler(rx: dict[str, Any], ctx: dict[str, Any], workouts: Any) -> list[str]:
    """IN PLACE (KB_FILLER) on the slot in its HOME session (a relocated slot is chosen by `live_balance.place_kb` through
    `kb_choice`): the KB deadlift becomes the swing, or the slot is dropped. Returns the rationale lines."""
    from training import kb_entry
    from training.live_balance import KB_SLOT_KEY

    kb = [
        e for e in rx["exposures"] if e.get("slot") == KB_SLOT_KEY and e.get("movement_key") == kb_entry.ENTRY and not e.get("live_added")
    ]
    if not kb:
        return []
    key, why = kb_choice(ctx, workouts)
    if key == kb_entry.ENTRY:
        return []
    if key:
        for e in kb:
            e["movement_key"] = key
            e["live_kb_filler"] = True
        return [f"kettlebell slot (live): {why}"]
    rx["exposures"] = [e for e in rx["exposures"] if e not in kb]
    return [f"dropped (live): the kettlebell slot — {why}"]


# ── 7. the self-reported stop lines ──────────────────────────────────────────
def self_report(workouts: Any, as_of: str | None) -> dict[str, Any] | None:
    """{tripwire, lines} when a Hevy note in SELF_REPORT window_days before `as_of` names a palpitations or syncope symptom
    (negated mentions excluded), else None."""
    from common.pacific_time import shift_day_key

    from training.training_notes_pain import _negated

    if not as_of or not workouts:
        return None
    since = shift_day_key(str(as_of)[:10], -int(SELF_REPORT["window_days"]))
    hit: set[str] = set()
    for w in workouts:
        day = str(w.get("date") or str(w.get("sk") or "")[5:15])[:10]
        if not (since <= day < str(as_of)[:10]):
            continue
        for x in w.get("exercises") or []:
            low = " ".join(str(x.get("notes") or "").lower().split())
            for arm in ("palpitations", "syncope"):
                if any(not _negated(low, m.start(), m.end()) for m in re.finditer(SELF_REPORT[arm], low)):
                    hit.add(arm)
    return {"tripwire": "medical_stop_lines (self-report, Hevy note)", "lines": sorted(hit)} if hit else None
