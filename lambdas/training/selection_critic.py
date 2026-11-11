"""selection_critic.py — the deterministic stage-2 `selection` critic, as a pure function (#5773, handoff #5784).

The Coaching Room lane registers it in the stage-2 critic set (`lambdas/coach/`); this module never imports from there.
No model call. Over one draft (`RoutineSpec` or its dict):

  * every served exercise whose library entry is UNAVAILABLE at home_gym (absent equipment) or PAIN-EXCLUDED gets a
    `change` verdict naming the swap — the selection's ranked fallback when it has one;
  * every ACCESSORY slot (the draft's rotation record names them; anchors are fixed for the block and never judged on
    tier) whose served movement is below the best selectable tier for the slot gets a `change` verdict to that movement,
    unless an owner pin holds the slot; a served movement behind a locked gate (#5772: unknown = locked) gets `change`;
    a served new-to-him movement with no recorded novel-again caps and cue sheet gets `change`;
  * the WEEK fails on an unmet weekly concession-ledger check the draft's rotation record carries (#5759's kettlebell
    BLOCK, a family floor unmet with no recorded gate).

The slot ranking comes from `selection_engine.select_week` when `catalog` is passed (recomputed, pure), else from the
selection record the draft already carries (`inputs_snapshot.selection` or `.selection_shadow`). With neither, the tier
check is `not_evaluated` — said so, never a pass by silence.
"""

from __future__ import annotations

from typing import Any

from training import exercise_library as xl, selection_engine as se

CRITIC = "selection"
ISSUE = "#5773"


def _snapshot(ir: Any) -> tuple[list[str], dict[str, Any]]:
    if isinstance(ir, dict):
        return [str(b.get("movement_key") or "") for b in ir.get("exercises") or []], ir.get("inputs_snapshot") or {}
    return [str(getattr(b, "movement_key", "") or "") for b in getattr(ir, "exercises", []) or []], getattr(
        ir, "inputs_snapshot", None
    ) or {}


def _record(
    snap: dict[str, Any], library: dict[str, Any], inventory: Any, overlay: Any, catalog: dict[str, Any] | None
) -> dict[str, Any] | None:
    if catalog is not None:
        return se.select_week((snap.get("rotation") or {}).get("position"), catalog, library, overlay, inventory=inventory)
    return snap.get("selection") or snap.get("selection_shadow")


def _key_map(record: dict[str, Any] | None, library: dict[str, Any], catalog: dict[str, Any] | None) -> dict[str, str]:
    """catalog key -> library id: the library<->catalog join when the catalog is given, else what the record names."""
    if catalog is not None:
        return se.key_index(library, catalog)["to_lib"]
    out: dict[str, str] = {}
    for s in (record or {}).get("slots") or []:
        for c in [s.get("pick") or {}] + list(s.get("fallbacks") or []):
            if c.get("catalog_key") and c.get("movement_id"):
                out.setdefault(c["catalog_key"], c["movement_id"])
    return out


def _slot_of(key: str, snap: dict[str, Any]) -> dict[str, Any] | None:
    for s in (snap.get("rotation") or {}).get("slots") or []:
        if s.get("variant") == key:
            return s
    return None


def _accessory_verdict(
    key: str, entry: dict[str, Any], slot: dict[str, Any], chosen: dict[str, Any] | None, library: dict[str, Any]
) -> dict[str, Any] | None:
    if slot.get("source") == "pinned" or (chosen or {}).get("pinned"):
        return None
    gates = se.locked_gates(entry, library)
    if gates:
        return {"verdict": "change", "why": f"gate {', '.join(gates)} locked ({se.GATES_SOURCE})"}
    pick = (chosen or {}).get("pick")
    if not pick:
        return {"verdict": "not_evaluated", "why": "no selection record for this slot"}
    muscle = (chosen or {}).get("muscle") or ((entry.get("target") or {}).get("primary"))
    served = se.tier_for(entry, muscle)
    if se.TIER_RANK[served] > se.TIER_RANK[pick["tier"]]:
        return {"verdict": "change", "why": f"tier {served} served where tier {pick['tier']} is selectable", "to": pick.get("catalog_key")}
    if se.is_novel(entry, None) and not (pick.get("catalog_key") == key and pick.get("novel_terms")):
        return {"verdict": "change", "why": "new to him with no recorded novel-again caps and cue sheet", "to": pick.get("catalog_key")}
    return None


def _week(snap: dict[str, Any]) -> list[dict[str, Any]]:
    rot = snap.get("rotation") or {}
    out = []
    kb = rot.get("kettlebell_weekly") or {}
    if kb.get("blocking"):
        out.append({"check": "kettlebell_weekly", "verdict": "fail", "why": kb.get("note")})
    for f in rot.get("family_floors") or []:
        if not f.get("met") and not f.get("gate"):
            out.append({"check": f"family_floor:{f.get('family')}", "verdict": "fail", "why": "unmet with no recorded gate"})
    return out


def evaluate(
    ir: Any,
    library: dict[str, Any],
    inventory: dict[str, Any] | None,
    overlay: dict[str, Any] | None,
    *,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The `selection` critic over one draft. Pure. `verdict`: fail (a weekly check) > change (any exercise) > pass."""
    keys, snap = _snapshot(ir)
    record = _record(snap, library, inventory, overlay, catalog)
    by_slot = {s["slot_id"]: s for s in (record or {}).get("slots") or []}
    kmap = _key_map(record, library, catalog)
    mv = xl.movements(library)
    verdicts = []
    for key in keys:
        lid = kmap.get(key) or (key if key in mv else None)
        if not lid:
            verdicts.append({"movement_key": key, "verdict": "unknown", "why": "no library entry joins this movement"})
            continue
        entry, slot = mv[lid], _slot_of(key, snap)
        chosen = by_slot.get((slot or {}).get("slot_id"))
        why = se.availability(entry, library, overlay, inventory) or se.pain_exclusion(entry, overlay) or se.not_for_you_now(entry)
        if why:
            swap = next((f.get("catalog_key") for f in (chosen or {}).get("fallbacks") or [] if f.get("catalog_key") != key), None)
            v = {"verdict": "change", "why": why, "to": swap}
        else:
            v = _accessory_verdict(key, entry, slot, chosen, library) if slot else None
        verdicts.append({"movement_key": key, "movement_id": lid, "slot_id": (slot or {}).get("slot_id")} | (v or {"verdict": "pass"}))
    week = _week(snap)
    overall = "fail" if week else ("change" if any(v["verdict"] == "change" for v in verdicts) else "pass")
    return {
        "critic": CRITIC,
        "issue": ISSUE,
        "verdict": overall,
        "library_version": se.library_version(library),
        "ranking_source": "recomputed" if catalog is not None else ("draft record" if record else "not_evaluated"),
        "verdicts": verdicts,
        "week": week,
    }
