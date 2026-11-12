"""selection_critic.py — the deterministic stage-2 `selection` critic, as a pure function (#5775 S6; first cut #5773).

WHAT IT ASKS, PER SLOT. Was a HIGHER-TIER movement available for this accessory slot? "Available" means not excluded by
one of the exclusions the critic honours (`HONORED_EXCLUSIONS` — a locked gate, a pain flag, equipment, the library's
not-for-you-now, the catalog unable to write it, the week's family floor), not held off by an owner pin or approval
(`owner_pin`), and not already served elsewhere this program week (`week_repeat`, owner ruling 2026-11-11: no repeats per
week). When one was, the verdict is `change`: it NAMES that movement and flips the slot's pick to it (`to`, the catalog key;
`field`, `exercises[<idx>].movement_key`), with the reason. When none was, the pick STANDS with the recorded reason — the
best higher-tier movement the slot could not serve and why, or `best_available` when nothing above it existed.

The FACTS (each library movement's tier for the slot's muscle, and which exclusion holds it) are the selection engine's own
(`selection_engine.candidates`, the engine's exclusion predicates over library + inventory + overlay); the DECISION is this
module's — the critic re-ranks every movement of the slot's job, eligible or excluded, and decides for itself which
exclusions stand. So the critic is a red team over the draft, not a replay of the engine's pick: a departure, a stale
rotation, or an engine bug that served a C where an A was open is caught here.

Every served exercise (a slot or not) whose library entry is UNAVAILABLE at home_gym, PAIN-EXCLUDED or not-for-you-now gets
`change` too — to the slot's best available movement (any tier), else the selection record's ranked fallback.

THE WEEK. The critic FAILS on any unmet weekly concession-ledger check (#5774, `week_commitments`): the stage-1 result when
the caller passes it (`week_commitments=`, stage 1's `constraint_block.week_commitments` — the week read with the routines
committed), else `week_commitments.evaluate` over the draft's rotation record with this draft as its role's day (pure, no
routine read), else the rotation record's own #5759 stamp (`kettlebell_weekly`, `family_floors`). A WARN row (the
kettlebell switch before its date) is reported, never a fail; a week that could not be read is `not_evaluated`, named.

`verdict`: fail (a blocking weekly check) > change (any exercise) > pass. `stage2` (`as_critic_verdict`) maps it onto the stage-2
critic shape (`coach.critics.deterministic_verdict`'s keys) for the Coaching Room lane's registry (#5784) — and honours
the engine's switch: while the library is `proposed` a flip is reported (`shadow_changes`), never applied. No model call;
no clock; no I/O (the charter's `equipment.not_available` list is read once when `missing` is not passed). Never imports
`lambdas/coach`.
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from typing import Any

from training import exercise_library as xl, selection_engine as se

CRITIC = "selection"
ISSUE = "#5775"
HONORED_EXCLUSIONS = ("pain_swap", "not_for_you_now", "equipment", "gate_locked", "not_prescribable", "weekly_floor")
"""The engine exclusion codes (`selection_engine._exclusion`) that keep a higher-tier movement out of a slot. Dropping one
makes the critic flip INTO a movement that exclusion holds (the must-fail mutation in tests/test_selection_critic_5775.py)."""
SERVED_BLOCKERS = ("pain_swap", "not_for_you_now", "equipment", "gate_locked")
"""An exclusion that makes the SERVED movement itself wrong to serve (the catalog obviously writes what is served)."""
PIN_SOURCES = ("pinned", "owner_approved")  # a rotation slot the owner holds: the structural pin, or the #5776 approval


# ── the draft ────────────────────────────────────────────────────────────────
def _as_ir(ir: Any) -> Any:
    """A dict draft as an attribute view (`week_commitments.routine_day` reads attributes)."""
    if not isinstance(ir, dict):
        return ir
    ex = [SimpleNamespace(movement_key=b.get("movement_key"), sets=b.get("sets")) for b in ir.get("exercises") or []]
    return SimpleNamespace(**{**ir, "exercises": ex, "inputs_snapshot": ir.get("inputs_snapshot") or {}})


def _keys(ir: Any) -> list[str]:
    return [str(getattr(b, "movement_key", "") or "") for b in getattr(ir, "exercises", None) or []]


def _slot_of(key: str, rot: dict[str, Any]) -> dict[str, Any] | None:
    """The rotation slot this served key fills: the slot serving it, else the slot whose incumbent it is."""
    slots = rot.get("slots") or []
    return next((s for s in slots if s.get("variant") == key), None) or next((s for s in slots if s.get("incumbent") == key), None)


def _pinned(slot: dict[str, Any], rec: dict[str, Any] | None, key: str, owner_pins: dict[str, Any] | None) -> str | None:
    """Why the owner holds this slot's served movement (pin or approval), or None."""
    if slot.get("pinned") or slot.get("source") in PIN_SOURCES:
        return f"rotation slot source {slot.get('source') or 'pinned'}"
    if ((rec or {}).get("owner_pin") or {}).get("state") == "held" or (rec or {}).get("pinned"):
        return "the selection record holds this slot as an owner pin"
    pin = (owner_pins or {}).get(slot.get("slot_id") or "") or {}
    if pin and pin.get("catalog_key") in (key, None):
        return f"owner-approved on the block design review (block {pin.get('approved_block')}, #5776)"
    return None


# ── one slot ─────────────────────────────────────────────────────────────────
def _env(library: dict[str, Any], catalog: dict[str, Any], overlay: Any, inventory: Any, missing: list[str] | None, ceiling: int) -> dict:
    from training import variant_rotation as vr

    return {
        "lib": library,
        "catalog": catalog,
        "overlay": overlay,
        "inventory": inventory,
        "idx": se.key_index(library, catalog),
        "ceiling": ceiling,
        "missing": vr.not_available() if missing is None else list(missing),
    }


def _blocker(c: dict[str, Any], taken: Counter) -> tuple[str, str] | None:
    """(code, why) that keeps candidate `c` out of the slot, or None when the critic finds it available."""
    if c.get("code") in HONORED_EXCLUSIONS:
        return str(c["code"]), str(c.get("why"))
    if taken[c.get("catalog_key") or ""] > 0:
        return "week_repeat", "already served in another slot this program week (no repeats, owner ruling 2026-11-11)"
    return None


def _best(pool: list[dict[str, Any]], prefer: str | None) -> dict[str, Any] | None:
    """The best-tier movement of `pool`; at that tier the selection record's pick first (what drafting would serve)."""
    if not pool:
        return None
    top = min(se.TIER_RANK[c["tier"]] for c in pool)
    at = sorted((c for c in pool if se.TIER_RANK[c["tier"]] == top), key=lambda c: se.rank_key(c, set()))
    return next((c for c in at if prefer and c.get("catalog_key") == prefer), at[0])


def _flip(c: dict[str, Any], why: str) -> dict[str, Any]:
    return {"verdict": "change", "to": c.get("catalog_key"), "to_movement_id": c["movement_id"], "to_tier": c["tier"], "why": why}


def judge_slot(
    key: str, slot: dict[str, Any], ctx: dict[str, Any], taken: Counter, *, pin: str | None, prefer: str | None = None
) -> dict[str, Any]:
    """One accessory slot: flip to the best available higher-tier movement, or stand with the recorded reason."""
    eligible, excluded = se.candidates(ctx)
    pool = eligible + excluded
    lid = ctx["idx"]["to_lib"].get(key)
    entry = xl.movements(ctx["lib"]).get(lid or "")
    served = next((c for c in pool if c.get("catalog_key") == key), None)
    title = (served or {}).get("title") or (entry or {}).get("title") or key
    tier = se.tier_for(entry, ctx["spec"]["muscle"]) if entry else "C"
    base = {"served_tier": tier, "muscle": ctx["spec"]["muscle"]}
    own, own_why = (served or {}).get("code"), (served or {}).get("why")
    if served is None and entry:  # served outside the slot's job (a departure): the engine's predicates still judge it
        own, own_why = se._exclusion(lid or key, entry, key, ctx) or (None, None)
    if own in SERVED_BLOCKERS and own in HONORED_EXCLUSIONS:
        alt = _best([c for c in pool if c is not served and _blocker(c, taken) is None], prefer)
        why = f"{title} is not servable ({own}: {own_why})"
        return base | (
            _flip(alt, f"{why} — {alt['title']} (tier {alt['tier']}) is") if alt else {"verdict": "change", "to": None, "why": why}
        )
    if pin:
        return base | {"verdict": "pass", "stands": "owner_pin", "why": f"{title} stands: {pin} (exempt from the tier check)"}
    above = sorted((c for c in pool if se.TIER_RANK[c["tier"]] < se.TIER_RANK[tier]), key=lambda c: se.rank_key(c, set()))
    open_ = [c for c in above if _blocker(c, taken) is None]
    best = _best(open_, prefer)
    if best:
        why = f"{best['title']} (tier {best['tier']}) was available for {slot.get('slot_id')} — {title} is tier {tier} with no exclusion"
        return base | _flip(best, why)
    if above:
        x = above[0]
        code, why = _blocker(x, taken) or ("?", "?")
        return base | {"verdict": "pass", "stands": code, "blocked": x["movement_id"], "why": f"{x['title']} (tier {x['tier']}): {why}"}
    return base | {"verdict": "pass", "stands": "best_available", "why": f"no movement for this slot's job ranks above tier {tier}"}


def _record_slot(key: str, entry: dict[str, Any], slot: dict[str, Any], rec: dict[str, Any] | None, library: dict) -> dict | None:
    """No catalog: judge against the selection record the draft carries (its pick is the best the engine could serve)."""
    gates = se.locked_gates(entry, library)
    if gates:
        return {
            "verdict": "change",
            "why": f"gate {', '.join(gates)} locked ({se.GATES_SOURCE})",
            "to": ((rec or {}).get("pick") or {}).get("catalog_key"),
        }
    pick = (rec or {}).get("pick")
    if not pick:
        return {"verdict": "not_evaluated", "why": "no selection record for this slot"}
    served = se.tier_for(entry, (rec or {}).get("muscle") or ((entry.get("target") or {}).get("primary")))
    if se.TIER_RANK[served] > se.TIER_RANK[pick["tier"]]:
        return {"verdict": "change", "why": f"tier {served} served where tier {pick['tier']} is selectable", "to": pick.get("catalog_key")}
    if se.is_novel(entry, None) and not (pick.get("catalog_key") == key and pick.get("novel_terms")):
        return {"verdict": "change", "why": "new to him with no recorded novel-again caps and cue sheet", "to": pick.get("catalog_key")}
    return None


# ── the week ─────────────────────────────────────────────────────────────────
def _days(ir: Any, rot: dict[str, Any], catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """This draft as its role's day of the program week (the rest is the plan) — no routine read."""
    from training import week_commitments as wc

    snap = getattr(ir, "inputs_snapshot", None) or {}
    role = ((rot.get("slots") or [{}])[0].get("role")) or (snap.get("calendar") or {}).get("session_role") or snap.get("session_role")
    return {str(role): {"keys": wc.routine_day(ir, catalog), "source": "this draft"}} if role else {}


def week_taken(ir: Any, rot: dict[str, Any], catalog: dict[str, Any] | None) -> Counter:
    """How many times each catalog key is served this program week (this draft for its role, the plan for the rest)."""
    if catalog and rot:
        from training import week_commitments as wc

        return Counter(s["key"] for s in wc.served_week(rot, catalog, _days(ir, rot, catalog)))
    return Counter(_keys(ir))


def _week_rows(result: dict[str, Any], source: str) -> tuple[list[dict[str, Any]], str]:
    verdict = result.get("verdict")
    if verdict not in ("pass", "fail"):
        return [{"check": "week_commitments", "verdict": "not_evaluated", "why": result.get("error") or verdict}], source
    rows = [
        {
            "check": r["id"],
            "verdict": "fail" if r.get("blocking") else ("warn" if r.get("verdict") == "warn" else "met"),
            "why": r.get("detail"),
        }
        for r in result.get("rows") or []
    ]
    return rows, source


def week(ir: Any, library: dict[str, Any], catalog: dict[str, Any] | None, stage1: dict[str, Any] | None) -> tuple[list[dict], str]:
    """The weekly concession checks (#5774) and where they were read from."""
    if isinstance(stage1, dict) and stage1:
        return _week_rows(stage1, "stage 1 (constraint_block.week_commitments)")
    snap = getattr(ir, "inputs_snapshot", None) or {}
    rot = snap.get("rotation")
    if catalog and isinstance(rot, dict):
        from training import week_commitments as wc

        out = wc.evaluate(rot, catalog, on=getattr(ir, "target_date", None), library=library, days=_days(ir, rot, catalog))
        return _week_rows(out, "week_commitments.evaluate (this draft + the plan)")
    rot = rot or {}
    rows = []
    kb = rot.get("kettlebell_weekly") or {}
    if kb:
        rows.append({"check": "kettlebell_weekly", "verdict": "fail" if kb.get("blocking") else "met", "why": kb.get("note")})
    for f in rot.get("family_floors") or []:
        if not f.get("met"):
            rows.append({"check": f"family_floor:{f.get('family')}", "verdict": "warn" if f.get("gate") else "fail", "why": f.get("gate")})
    return rows, ("the rotation record's #5759 stamp" if rot else "not_evaluated (no rotation record)")


# ── the critic ───────────────────────────────────────────────────────────────
def _served_blocker(entry: dict[str, Any], library: dict[str, Any], overlay: Any, inventory: Any) -> str | None:
    return se.availability(entry, library, overlay, inventory) or se.pain_exclusion(entry, overlay) or se.not_for_you_now(entry)


def _one(i: int, key: str, ir: Any, env: dict | None, taken: Counter, records: dict, kmap: dict, args: dict) -> dict[str, Any]:
    library, overlay, inventory = args["library"], args["overlay"], args["inventory"]
    snap = getattr(ir, "inputs_snapshot", None) or {}
    rot = snap.get("rotation") or {}
    mv = xl.movements(library)
    head = {"idx": i, "movement_key": key}
    lid = kmap.get(key) or (key if key in mv else None)
    slot = _slot_of(key, rot) if isinstance(rot, dict) else None
    rec = records.get((slot or {}).get("slot_id"))
    if slot and env is not None:
        from training import variant_rotation as vr

        step = int((rot.get("position") or {}).get("step") or 0)
        spec_slot = next((s for s in vr.slots() if s["slot_id"] == slot["slot_id"]), None)
        if spec_slot:
            ctx = se._ctx(spec_slot, env, step)  # the engine's own per-slot context (muscle, job, floor)
            pin = _pinned(slot, rec, key, args["owner_pins"])
            prefer = ((rec or {}).get("pick") or {}).get("catalog_key")
            return head | {"movement_id": lid, "slot_id": slot["slot_id"]} | judge_slot(key, slot, ctx, taken, pin=pin, prefer=prefer)
    if not lid:
        return head | {"verdict": "unknown", "why": "no library entry joins this movement"}
    entry = mv[lid]
    head |= {"movement_id": lid, "slot_id": (slot or {}).get("slot_id")}
    why = _served_blocker(entry, library, overlay, inventory)
    if why:
        swap = next((f.get("catalog_key") for f in (rec or {}).get("fallbacks") or [] if f.get("catalog_key") != key), None)
        return head | {"verdict": "change", "why": why, "to": swap}
    if slot and not _pinned(slot, rec, key, args["owner_pins"]):
        return head | (_record_slot(key, entry, slot, rec, library) or {"verdict": "pass"})
    return head | {"verdict": "pass"}


def evaluate(
    ir: Any,
    library: dict[str, Any],
    inventory: dict[str, Any] | None,
    overlay: dict[str, Any] | None,
    *,
    catalog: dict[str, Any] | None = None,
    week_commitments: dict[str, Any] | None = None,
    owner_pins: dict[str, dict[str, Any]] | None = None,
    missing: list[str] | None = None,
    skill_ceiling: int = 2,
) -> dict[str, Any]:
    """The `selection` critic over one draft (`RoutineSpec` or its dict). Pure.

    `catalog` (the movement catalog) arms the per-slot red team (`judge_slot`); without it each slot is judged against the
    selection record the draft carries. `week_commitments` is stage 1's #5774 result, when the caller holds it.
    `owner_pins` is the block design review's approved picks (`block_design_review.resolve(...)["pins"]`, #5776)."""
    ir = _as_ir(ir)
    snap = getattr(ir, "inputs_snapshot", None) or {}
    record = snap.get("selection") or snap.get("selection_shadow")
    records = {s.get("slot_id"): s for s in (record or {}).get("slots") or []}
    env = _env(library, catalog, overlay, inventory, missing, skill_ceiling) if catalog is not None else None
    kmap = env["idx"]["to_lib"] if env else {c["catalog_key"]: c["movement_id"] for s in records.values() for c in _named(s)}
    rot = snap.get("rotation") if isinstance(snap.get("rotation"), dict) else {}
    taken = week_taken(ir, rot, catalog)
    args = {"library": library, "overlay": overlay, "inventory": inventory, "owner_pins": owner_pins}
    verdicts = []
    for i, key in enumerate(_keys(ir)):
        verdicts.append(_one(i, key, ir, env, taken, records, kmap, args))
    rows, week_source = week(ir, library, catalog, week_commitments)
    failed = [r for r in rows if r["verdict"] == "fail"]
    overall = "fail" if failed else ("change" if any(v["verdict"] == "change" for v in verdicts) else "pass")
    out = {
        "critic": CRITIC,
        "issue": ISSUE,
        "verdict": overall,
        "library_version": se.library_version(library),
        "mode": se.mode(library),
        "ranking_source": "recomputed" if env else ("draft record" if record else "not_evaluated"),
        "honored_exclusions": list(HONORED_EXCLUSIONS),
        "verdicts": verdicts,
        "week": failed,
        "week_rows": rows,
        "week_source": week_source,
    }
    return out | {"stage2": as_critic_verdict(out)}  # the stage-2 verdict the registry appends (#5784)


def _named(s: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in [s.get("pick") or {}] + list(s.get("fallbacks") or []) if c.get("catalog_key") and c.get("movement_id")]


def as_critic_verdict(out: dict[str, Any]) -> dict[str, Any]:
    """The critic's result in the stage-2 verdict shape (`coach.critics.deterministic_verdict`'s keys), for the Coaching
    Room lane's registry (#5784): a failed weekly check is a `veto`, a flip a `change` on `exercises[<idx>].movement_key`
    (further flips ride as `additional_changes`), else `approve`. While the library is not `approved` (selection_engine's
    THE SWITCH) a flip is recorded as `shadow_changes` on an `approve` and applies nothing — the weekly veto still stands
    (#5774 is live on its own switch). Applying a lift swap is that lane's `critics_apply` work."""
    base = {"critic": CRITIC, "metric": None, "value": None, "field": None, "to": None, "provenance": f"selection critic {ISSUE}"}
    if out["verdict"] == "fail":
        f = out["week"][0]
        why = "; ".join(f"{r['check']}: {r['why']}" for r in out["week"])
        return base | {"verdict": "veto", "metric": f"week_commitments.{f['check']}", "reason": f"unmet weekly concession check — {why}"}
    flips = [
        {"metric": "selection", "field": f"exercises[{v['idx']}].movement_key", "to": v.get("to"), "reason": v["why"]}
        for v in out["verdicts"]
        if v["verdict"] == "change"
    ]
    if flips and out.get("mode") != se.MODE_LIVE:  # THE SWITCH (owner, 2026-11-11): a proposed library changes no live draft
        why = f"library {out.get('mode')}: {len(flips)} flip(s) recorded, none applied until the library is approved"
        return base | {"verdict": "approve", "reason": why, "shadow_changes": flips}
    if not flips:
        return base | {"verdict": "approve", "reason": "every slot serves the best available tier, or stands with its recorded reason"}
    return base | {"verdict": "change", **flips[0]} | ({"additional_changes": flips[1:]} if flips[1:] else {})
