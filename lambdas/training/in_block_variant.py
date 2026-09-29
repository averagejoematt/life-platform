"""in_block_variant.py — within a block, a slot keeps the variant he actually performed in it (#4409).

WHY THIS EXISTS

`program_structure._resolve_movement` picks the FIRST reachable catalog key of an anchor
pattern, in the order `ANCHORS[pattern]['catalog_keys']` lists them. It never looked at the
block's own record, so the 2026-09-29 pre-draft (UPPER-HEAVY, week 1) swapped the dumbbell
row he rowed on 2026-09-25 (90 lb x 8) for `machine_row` — whose only history is May 2025 at a
bodyweight ~120 lb lighter — and the dumbbell shoulder press (52.5 lb x 10, same day) for
`machine_shoulder_press`, anchored to 2023. The in-block variant is the one with a current load;
the catalog default came with a stale anchor and a 54 % re-entry ramp on top of it.

THE RULE (one order, per slot = session role x anchor pattern)

  1. the variant performed in the most recent CREDITED session of the SAME role in this block
     (the slot he filled last time — the lower-heavy RDL stays the lower-heavy hinge); two members
     of one pattern on one day -> the one performed first (anchors lead the session);
  2. else the variant most recently performed in the block for the same PATTERN in any role (the
     09-29 upper-heavy row: upper-heavy had not run yet in block 1, upper-volume rowed the DB row
     on 09-25). At a moderate exposure whose pattern names `moderate_catalog_keys` (the owner's
     RDL-as-moderate-hinge rule, #4147) only those keys count here — a heavy trap-bar pull must
     not take the moderate hinge slot;
  3. else the catalog order, unchanged — a slot with no in-block performance resolves exactly as
     before.

A performance of a key the performed session's role lists as an ACCESSORY never counts for an
anchor slot: `leg_curl` is the hinge's last listed fallback AND a lower accessory, and the 09-28
leg curl was the accessory, not the hinge.

Only the pattern's own listed keys are ever candidates, and `_resolve_movement`'s reachability
checks (catalog membership, the skill ceiling and its #4080 exemption, one key per session) still
run on the reordered list. So a variant change inside the block happens only when the performed
variant is UNREACHABLE for this session, and then it is the pattern's next LISTED member — the
listed swap (`owner_redlines.standing_owner_rules`: "take the listed swap"). The exposure records
it (`in_block.kept` False, with the resolver's reason), never silently.

WHAT "PERFORMED IN BLOCK" MEANS

A loaded set (weight > 0, reps > 0) of the exercise on a day the session sequence CREDITED as a
program session (`session_sequence.completed_positions` — the same credit the sequence advances
on; a Flex complement or a refused log fills no slot). The exercise maps to a catalog key by its
Hevy template id (`hevy_template_id_hint`) or, for a title-only entry (ADR-069 — the catalog's
`db_shoulder_press` carries no hint on purpose), by its exact normalized Hevy title. The template
id then comes from the WIRE — the id Hevy itself served on the performed record — never a
hand-transcribed one, which is the silent mis-map ADR-069 guards against.

A stale anchor is still never used undiscounted: the anchor a resolved key loads from is
`load_ramp.v03_floor`'s, whose detraining discount (#4107) and nearest-band fallback are
unchanged by this module.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

ISSUE = "#4409"

SAME_ROLE = "same_role"
SAME_PATTERN = "same_pattern"


def _norm(title: Any) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip().lower())


def _loaded(ex: dict[str, Any]) -> bool:
    for s in ex.get("sets") or []:
        try:
            if float(s.get("weight_kg") or 0) > 0 and int(s.get("reps") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _key_for(ex: dict[str, Any], by_id: dict[str, str], by_title: dict[str, str]) -> str | None:
    tid = str(ex.get("template_id") or "")
    if tid and tid in by_id:
        return by_id[tid]
    return by_title.get(_norm(ex.get("name") or ex.get("title")))


def performed_in_block(
    block_workouts: Iterable[dict[str, Any]] | None, catalog_movements: dict[str, Any] | None, before_day: str
) -> list[dict[str, Any]]:
    """Every catalog movement performed LOADED in a credited program session of the block before
    `before_day`, oldest first: `{movement_key, template_id, date, position, role, name}`. Pure.

    `block_workouts` is the Hevy per-workout rows since the block start (the raw DDB shape the
    generator and the planner already read); None or no catalog -> []."""
    if not block_workouts or not catalog_movements:
        return []
    from training import session_sequence

    rows = list(block_workouts)
    roles = {p["date"]: p.get("session_role") for p in session_sequence.completed_positions(rows, before_day)}
    by_id = {str(m["hevy_template_id_hint"]): k for k, m in catalog_movements.items() if (m or {}).get("hevy_template_id_hint")}
    by_title = {
        _norm(m.get("title")): k for k, m in catalog_movements.items() if (m or {}).get("title") and not m.get("hevy_template_id_hint")
    }
    out: list[dict[str, Any]] = []
    for w in rows:
        d = str(w.get("date") or "")
        if w.get("tombstone") or d not in roles:
            continue
        for pos, ex in enumerate(w.get("exercises") or []):
            key = _key_for(ex, by_id, by_title)
            if key and _loaded(ex):
                out.append(
                    {
                        "movement_key": key,
                        "template_id": ex.get("template_id"),
                        "date": d,
                        "position": pos,
                        "role": roles[d],
                        "name": ex.get("name"),
                    }
                )
    out.sort(key=lambda r: (r["date"], r["position"]))
    return out


def prefer(
    performed: list[dict[str, Any]] | None, role: str, pattern: str, intensity: str, keys: list[str], moderate_keys: list[str] | None = None
) -> dict[str, Any] | None:
    """The slot's in-block variant (rule 1, else rule 2 — module docstring), or None (rule 3).

    Returns `{keys, performed}`: `keys` is `keys` with the performed variant moved first, so the
    caller's resolver still applies every reachability check to it."""
    from training import program_structure

    def _as_accessory(p: dict[str, Any]) -> bool:
        return p["movement_key"] in (program_structure.SESSION_TEMPLATES.get(p.get("role")) or {}).get("accessories", [])

    # a key the performed session's role lists as an ACCESSORY filled that slot, not this anchor's (the
    # lower-volume leg curl is the hinge's last listed fallback, never the hinge he pulled that day)
    cands = [p for p in performed or [] if p["movement_key"] in keys and not _as_accessory(p)]
    same = [p for p in cands if p.get("role") == role]
    basis = SAME_ROLE
    if not same:
        basis = SAME_PATTERN
        if intensity == "moderate" and moderate_keys:
            cands = [p for p in cands if p["movement_key"] in moderate_keys]
        same = cands
    if not same:
        return None
    last_day = max(p["date"] for p in same)
    hit = min((p for p in same if p["date"] == last_day), key=lambda p: p["position"])  # that day's first-performed member
    return {"keys": [hit["movement_key"]] + [k for k in keys if k != hit["movement_key"]], "performed": {**hit, "basis": basis}}


def exposure_fields(pref: dict[str, Any] | None, resolved: str | None) -> dict[str, Any]:
    """What an exposure records about its in-block variant: kept, or the listed swap and why."""
    if not pref:
        return {}
    p = pref["performed"]
    kept = resolved == p["movement_key"]
    out: dict[str, Any] = {
        "in_block": {
            "performed": p["movement_key"],
            "date": p["date"],
            "role": p.get("role"),
            "basis": p["basis"],
            "kept": kept,
            "rule": f"within a block a slot keeps the variant performed in it; a change is only the pattern's listed swap ({ISSUE})",
        }
    }
    if kept and p.get("template_id"):
        out["template_id"] = p["template_id"]
    return out


def with_performed_template_ids(catalog: dict[str, Any], rx: dict[str, Any]) -> dict[str, Any]:
    """`catalog` with the wire template id of every kept in-block variant whose entry carries no
    `hevy_template_id_hint` (title-only, ADR-069), so the load floor and the history note can read
    its record. A shallow copy — the catalog itself (and its hash on the snapshot) is untouched."""
    movements = dict((catalog or {}).get("movements") or {})
    changed = False
    for e in (rx or {}).get("exposures") or []:
        key, tid = e.get("movement_key"), e.get("template_id")
        if key and tid and key in movements and not (movements[key] or {}).get("hevy_template_id_hint"):
            movements[key] = {
                **movements[key],
                "hevy_template_id_hint": tid,
                "hevy_template_id_source": f"in-block performed record ({ISSUE})",
            }
            changed = True
    return {**catalog, "movements": movements} if changed else catalog
