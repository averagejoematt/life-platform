"""live_rules.py — joint-located isolation caps and the self-report gate (#5861). LIVE only.

  * `isolation_joint_cap` (JOINT_ISOLATION): under a flag on a joint, every isolation lift that works it is capped at PAIN_RULE's
    pain RPE with the stop line.
  * `note_class` (DISCOMFORT_WORDS, LIGHT): a joint-located "sore" at or under the mild line is light discomfort — kept, lighter.
  * `self_report` (SELF_REPORT): his own Hevy note in the last fortnight naming palpitations or fainting trips the no-hard-cardio
    gate (owner ruling 10 follow-up: the behaviour stays; no warning line is printed).

Deleted in fix round 9: the session set cap, the full-body partner rule, the no-added-work rule and the KB-deadlift filler —
`live_volume` (the set ceiling, the full-body weeks) and the plan (nothing is added on a bad day: no addition exists) replace them."""

from __future__ import annotations

import re
from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

JOINT_ISOLATION: dict[str, tuple[str, ...]] = {
    "elbow": ("triceps_extension", "curl"),
    "shoulder": ("lateral_raise", "rear_delt", "shoulder_rotation", "chest_fly"),
    "wrist": ("curl",),
    "knee": ("leg_extension", "leg_curl"),
    "hip": ("hip_abduction", "hip_adduction", "hip_extension"),
}
"""Joint -> the isolation patterns that WORK it (heuristic, practitioner consensus): under a flag on the joint each is capped at
PAIN_RULE pain_rpe with the stop line, independent of the library's joint-stress rating."""
DISCOMFORT_WORDS = r"\b(?:sore(?:ness)?|ach(?:e|es|ing|y|ey)|tight(?:ness)?|cranky|niggl\w*|tweaky)\b"
"""A joint-located sensation word the engine reads as discomfort at or under the mild line (heuristic)."""
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


# ── 2. full-body days ────────────────────────────────────────────────────────


# ── 3. no added work on a bad day ────────────────────────────────────────────


# ── 4. same-joint isolation under a flag ─────────────────────────────────────
def isolation_joint_cap(rx: dict[str, Any], ctx: dict[str, Any], flags: list[dict[str, Any]]) -> list[str]:
    """IN PLACE: every isolation exposure whose pattern works a flagged joint (JOINT_ISOLATION) is capped at PAIN_RULE pain_rpe
    and carries the stop line — the data-independent half of the pain rule. Returns the rationale lines."""
    from training import live_safety
    from training.live_program import PAIN_RULE

    rpe = int(PAIN_RULE["pain_rpe"]["value"])
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
