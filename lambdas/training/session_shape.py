"""session_shape.py — a session's LENGTH and SHAPE, from the training charter (#5069, owner ruling 5).

Owner ruling 5 (2026-10-18, epic #5067) set the lifting minutes; owner ruling A4 (2026-10-24, #5318) made them a CEILING
ONLY: "Accept shorter sessions. 75 sets a week stays the ceiling. Drop the 60-minute lifting floor: 75 minutes is a ceiling,
not a target." The charter's `split.session_minutes` carries the lifting ceiling, the one cardio block's cap and the
stretching cap. There is no floor: a session under the ceiling is reported as its length and nothing ever adds a set to
fill it (the old `under_range` flag is gone with the floor it measured).
This module is the ONE estimate of a session's lifting minutes (`session_minutes_estimate` for a
prescription, `routine_minutes` for a routine's blocks), the trim that fits a prescription to the cap
(`trim_to_time` — accessories first, anchors never), and the shape check / enforcement on a routine's
blocks (`session_shape_problems` for the chat path, which flags; `enforce_session_shape` for the
generator, which cuts). Split out of `training.program_structure` (which re-exports every public name
here) so neither module crosses the 1000-line ceiling (#1665).
"""

from __future__ import annotations

from typing import Any

from training import warmup_sets
from training.training_charter import charter_value, charter_version

# ── the session's LENGTH ─────────────────────────────────────────────────────
# The lifting ceiling: the charter's `split.session_minutes.lifting_ceiling` (A4, #5318 — a ceiling, not a target). One estimate, from the prescription's own numbers: every
# working and warm-up set costs the set itself plus the exposure's rest (`EXPOSURES[*].rest_seconds`). Cardio and
# stretching are NOT lifting minutes — they have their own caps (one cardio block, stretching), enforced on the routine's
# blocks by `enforce_session_shape` / reported by `session_shape_problems`.
SESSION_TIME_MODEL: dict[str, Any] = {
    "set_seconds": 45,
    "provenance": "platform-proposed",
    "stated": "2026-10-18",
    "issue": "#5069",
    "rule": (
        "lifting minutes = sum over exposures of (working sets + warm-up sets) x (set_seconds + the exposure's rest_seconds) / 60; "
        "warm-ups in a PRESCRIPTION are assumed for every anchor in warmup_sets' compound families (the first gets the full "
        "climb, later ones one set) — an upper bound, since a light lift under the warm-up floor gets none; in a ROUTINE the "
        "warm-up sets are counted as written. Cardio and stretching blocks are excluded (their own caps)."
    ),
    "note": "45 s is the platform's time under load + set-up for a 4–15 rep set; re-derive from his Hevy set timestamps when the data allows (ADR-105).",
}


def lifting_minutes_cap() -> int:
    """The lifting-minute ceiling a session is trimmed to (`split.session_minutes.lifting_ceiling`). There is no floor (A4)."""
    return int(charter_value("split.session_minutes.lifting_ceiling"))


def _side_caps() -> dict[str, int]:
    return {
        "cardio_block_max_minutes": int(charter_value("split.session_minutes.cardio_block_max")),
        "stretching_max_minutes": int(charter_value("split.session_minutes.stretching_max")),
    }


def _assumed_warmups(exposures: list[dict[str, Any]]) -> list[int]:
    """Warm-up sets the estimate assumes per exposure: the first compound anchor climbs in full, later ones get one set."""
    rx = warmup_sets.WARMUP_PRESCRIPTION
    families = set(rx["compound_families"])
    out, seen = [], False
    for e in exposures:
        if e.get("kind") == "anchor" and e.get("pattern") in families:
            out.append(len(rx["later_compound"] if seen else rx["first_compound"]))
            seen = True
        else:
            out.append(0)
    return out


def session_minutes_estimate(exposures: list[dict[str, Any]]) -> dict[str, Any]:
    """The lifting-time estimate for a prescription's exposures (`SESSION_TIME_MODEL`), against the charter's ceiling.

    A4 (#5318): the ceiling is the only bound — an estimate under it is just its length; there is no `under_range` and no
    fill action anywhere downstream."""
    set_s = int(SESSION_TIME_MODEL["set_seconds"])
    warm = _assumed_warmups(exposures)
    seconds = sum((len(e["sets"]) + w) * (set_s + int(e.get("rest_seconds") or 0)) for e, w in zip(exposures, warm))
    minutes = round(seconds / 60.0, 1)
    hi = lifting_minutes_cap()
    return {
        "lifting_minutes": minutes,
        "working_sets": sum(len(e["sets"]) for e in exposures),
        "warmup_sets_assumed": sum(warm),
        "cap": hi,
        "within_cap": minutes <= hi,
        **_side_caps(),
        "excludes": "cardio and stretching (their own caps)",
        "charter_version": charter_version(),
    }


def trim_to_time(exposures: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Drop accessories, last-listed first, IN PLACE until the estimate fits the cap; None when it already fits.

    Anchors are never trimmed for time: an anchors-only session still over the cap is flagged (`over_cap_after_trim`)."""
    before = session_minutes_estimate(exposures)
    if before["within_cap"]:
        return None
    dropped: list[str | None] = []
    est = before
    while not est["within_cap"]:
        idx = next((i for i in range(len(exposures) - 1, -1, -1) if exposures[i]["kind"] == "accessory"), None)
        if idx is None:
            break
        dropped.append(exposures.pop(idx).get("movement_key"))
        est = session_minutes_estimate(exposures)
    return {
        "cap_minutes": before["cap"],
        "estimate_before_min": before["lifting_minutes"],
        "estimate_after_min": est["lifting_minutes"],
        "dropped_accessories": dropped,
        "over_cap_after_trim": not est["within_cap"],
        "rule": "accessories first, last-listed first; anchors are never cut for time (charter split.session_minutes.lifting_ceiling, owner rulings 5 + A4)",
    }


LOADED_TIMED_TYPES: frozenset[str] = frozenset({"weight_duration", "short_distance_weight"})
"""Hevy exercise types that are a timed or distance set UNDER LOAD (a carry): lifting, never a cardio or stretching block."""


def _block_title(block: Any, catalog_movements: dict[str, Any]) -> str:
    key = str(getattr(block, "movement_key", "") or "")
    return str((catalog_movements.get(key) or {}).get("title") or key.replace("_", " "))


def _block_kind(block: Any, catalog_movements: dict[str, Any]) -> str:
    """'stretching' | 'cardio' | 'lifting' for one routine block. A TIMED block (every set carries a duration and no reps or
    load) is cardio or stretching — stretching when its title names a stretch, mobility or foam rolling; anything else is
    lifting. By the set shape, not the name alone: a 'walking lunge' or a 'cable stretch curl' is a lift. #5318: a LOADED timed
    movement (Hevy `weight_duration` / `short_distance_weight` — the farmer's carry) is lifting even before its load is
    written: its first load is the owner's pick, so the drafted set carries a duration and no weight."""
    entry = catalog_movements.get(str(getattr(block, "movement_key", "") or "")) or {}
    if entry.get("hevy_type") in LOADED_TIMED_TYPES:
        return "lifting"
    sets = list(getattr(block, "sets", None) or [])
    timed = bool(sets) and all(
        getattr(st, "duration_seconds", None)
        and not getattr(st, "reps", None)
        and not getattr(st, "rep_range_start", None)
        and not getattr(st, "weight_kg", None)
        for st in sets
    )
    if not timed:
        return "lifting"
    title = _block_title(block, catalog_movements).strip().lower()
    return "stretching" if any(h in title for h in ("stretch", "mobility", "foam roll")) else "cardio"


def _block_seconds(block: Any) -> int:
    return sum(int(getattr(s, "duration_seconds", None) or 0) for s in getattr(block, "sets", None) or [])


def routine_minutes(blocks: list[Any], catalog_movements: dict[str, Any]) -> dict[str, Any]:
    """A routine's minutes by kind: lifting (sets as written, warm-ups included, x set time + rest), each cardio block, stretching."""
    set_s = int(SESSION_TIME_MODEL["set_seconds"])
    lifting_s, cardio, stretch_s = 0, [], 0
    for b in blocks:
        kind = _block_kind(b, catalog_movements)
        if kind == "lifting":
            lifting_s += len(getattr(b, "sets", None) or []) * (set_s + int(getattr(b, "rest_seconds", None) or 0))
        elif kind == "cardio":
            cardio.append({"movement_key": b.movement_key, "minutes": round(_block_seconds(b) / 60.0, 1)})
        else:
            stretch_s += _block_seconds(b)
    return {"lifting_minutes": round(lifting_s / 60.0, 1), "cardio_blocks": cardio, "stretching_minutes": round(stretch_s / 60.0, 1)}


def session_shape_problems(blocks: list[Any], catalog_movements: dict[str, Any]) -> list[str]:
    """Where a routine breaks the charter's session shape (owner ruling 5): lifting over the cap, more than one cardio block,
    a cardio block over its cap, stretching over its cap. Read-only — the chat path flags, the generator enforces."""
    m, caps, cap = routine_minutes(blocks, catalog_movements), _side_caps(), lifting_minutes_cap()
    out: list[str] = []
    if m["lifting_minutes"] > cap:
        out.append(f"lifting ~{m['lifting_minutes']} min is over the {cap}-min lifting cap (charter split.session_minutes)")
    if len(m["cardio_blocks"]) > 1:
        out.append(f"{len(m['cardio_blocks'])} cardio blocks — the charter's session shape is ONE deliberate cardio block")
    out += [
        f"cardio block {c['movement_key']} is {c['minutes']} min, over the {caps['cardio_block_max_minutes']}-min cap"
        for c in m["cardio_blocks"]
        if c["minutes"] > caps["cardio_block_max_minutes"]
    ]
    if m["stretching_minutes"] > caps["stretching_max_minutes"]:
        out.append(f"stretching {m['stretching_minutes']} min is over the {caps['stretching_max_minutes']}-min cap")
    return out


def _clamp_seconds(block: Any, allowed_s: int) -> int:
    """Cut a block's timed sets to `allowed_s` seconds in total, in order; returns the seconds removed."""
    removed, left = 0, max(0, int(allowed_s))
    for st in getattr(block, "sets", None) or []:
        dur = int(getattr(st, "duration_seconds", None) or 0)
        keep = min(dur, left)
        if keep < dur:
            st.duration_seconds = keep
            removed += dur - keep
        left -= keep
    return removed


def enforce_session_shape(blocks: list[Any], catalog_movements: dict[str, Any]) -> dict[str, Any]:
    """The generator's session shape, IN PLACE: one cardio block (a second is dropped), the cardio block and the stretching cut to
    their charter caps. Lifting minutes are the prescription's job (`_trim_to_time`); they are reported here, never cut."""
    caps = _side_caps()
    actions: list[str] = []
    keep: list[Any] = []
    cardio_seen, stretch_left = 0, caps["stretching_max_minutes"] * 60
    for b in blocks:
        kind = _block_kind(b, catalog_movements)
        if kind == "cardio":
            if cardio_seen:
                actions.append(f"dropped a second cardio block ({b.movement_key}) — one per session")
                continue
            cardio_seen += 1
            cut = _clamp_seconds(b, caps["cardio_block_max_minutes"] * 60)
            if cut:
                actions.append(f"{b.movement_key}: cut {cut // 60} min to the {caps['cardio_block_max_minutes']}-min cardio cap")
        elif kind == "stretching":
            total = _block_seconds(b)
            cut = _clamp_seconds(b, stretch_left)
            stretch_left -= total - cut
            if cut:
                actions.append(f"{b.movement_key}: cut {cut // 60} min to the {caps['stretching_max_minutes']}-min stretching cap")
        keep.append(b)
    blocks[:] = keep
    return {**routine_minutes(blocks, catalog_movements), **caps, "lifting_cap_minutes": lifting_minutes_cap(), "actions": actions}
