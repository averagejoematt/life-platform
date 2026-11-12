"""selection_engine.py — each accessory slot filled by the best-evidenced movement he can do, with the reason recorded (#5773).

WHAT IT REPLACES

#5075's `variant_rotation.VETTED_POOLS` are platform-proposed lists with equal standing: nothing ranks one candidate
above another (the upper-heavy triceps pool omits the overhead cable extension, owner report 2026-11-11). This module
ranks the exercise library (#5769, `config/exercise_library.json`) per slot, deterministically:

    candidates  = library movements for the slot's muscle AND job (the movement patterns of the slot's template accessory
                  and its vetted pool, `exercise_library.movement_pattern`), never a skill/athletic or strength-anchor
                  entry, that are
                    * UNLOCKED — every locking gate on the entry reads LOCKED until #5772 evaluates gates (an unknown input
                      is locked, `exercise_library.UNKNOWN_INPUT`); a `clinical_cue` never locks;
                    * AVAILABLE at `home_gym` — the entry's own state AND every equipment id in the inventory (the 5-year
                      rule; `unknown` is not available) AND the overlay's learned unavailability ("gym doesn't have X");
                      contention ("X was taken", "no bench free") never makes anything unavailable; plus the charter's
                      owner-editable `equipment.not_available` list;
                    * NOT PAIN-EXCLUDED — see PAIN SOURCE below;
                    * PRESCRIBABLE — a movement-catalog entry with the slot's volume signature (`variant_rotation`), the
                      generator's skill ceiling and a loaded rep template (or the template accessory's own Hevy type). A library movement the catalog cannot write
                      is RANKED and reported (`above_pick`), never served.
    rank        = tier for the slot's muscle (A over B over C)
                  -> N=1 fit from the owner-private overlay (progression, pain history, sentiment; swap-out frequency
                     demotes; an absent overlay is `unknown`, score 0 — never an error)
                  -> variety (not served in the last VARIETY_LOOKBACK_BLOCKS blocks of the rotation ledger; not already
                     served by another slot this week; then familiar before new-to-him; then history exposures)
    C           = served only with a recorded reason (`C_REASONS`): an A/B candidate for the slot exists and is excluded
                  by equipment, pain, a locked gate, or the catalog; the slot is an owner pin or the skill track; or
                  the library holds no A/B movement for the slot's job at all (`library_gap`).
    lengthened  = each muscle gets at least one lengthened-bias movement per week: when a muscle's picks hold none, the
                  first slot of that muscle whose candidates hold a lengthened movement at the SAME tier and N=1 score
                  takes it (variety never outranks tier or fit). An unmet muscle is reported, never forced.
    novelty     = at most NOVELTY_PER_SLOT new-to-him movement per slot per rotation (pick + fallbacks). A new pick
                  carries the novel-again caps (`layoff_tiers.EXPOSURE_CAPS`: RPE <= 7, reps <= 8 for exposures 1-3)
                  and a cue sheet (`form_cue_sheets`); a new movement with no cue sheet is not a candidate.
    fallbacks   = every pick carries its ranked same-stimulus fallbacks (the slot's next eligible candidates, those that
                  share no equipment with the pick first, so a missing item is a swap and not the same hole). The
                  Hevy note names them (#5771, `note_fallbacks` -> `lift_note.fit_fallback`: `If taken: X, then Y.`),
                  on the wire only once the library is approved; `fallback_note` records the slot's line.

Anchors are not slots (`variant_rotation`): they stay fixed for the block. Pinned slots keep their pin (`owner_pin`).

THE SWITCH (owner, 2026-11-11). The engine changes live drafts ONLY when the library's `status` is `approved`. While it
is `proposed` it runs in SHADOW: the selection is computed beside the #5075 pools and recorded on the draft
(`inputs_snapshot.selection_shadow`), and the pools serve. No library => `no_library`, the pools serve, said so.

PAIN SOURCE. #5806's rule (`training_notes_pain.pain_class` / `record_pain_class`): only a `pain`-class note excludes;
`discomfort` and `form_or_equipment` never do (discomfort is an N=1 demotion through `joint_discomfort`). The overlay
carries it as the coded `pain_flag` tag, which `exercise_library.note_signal_tags` sets only for `pain`; an overlay
written before that rule (no `pain_source` stamp equal to `exercise_library.PAIN_SOURCE_ID`) has an over-inclusive tag,
so it is NOT trusted to exclude and the record says `stale_overlay` until the writer re-runs. A library
`not_for_you_now` is the library's own curated verdict (with an unlock condition) and excludes as `not_for_you_now`,
not as pain. `PAIN_SOURCE` and `pain_source_state` name it on every record.

Every draft records `library_version` (`routine_repo.stamp_library_version`), as it records `charter_version`.
Pure apart from the fail-soft loaders at the top.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from training import exercise_library as xl

logger = logging.getLogger(__name__)

ISSUE = "#5773"
APPROVED = "approved"
MODE_LIVE = "live"
MODE_SHADOW = "shadow"
MODE_NO_LIBRARY = "no_library"
TIER_RANK = {"A": 0, "B": 1, "C": 2}
VARIETY_LOOKBACK_BLOCKS = 1  # the ledger read window (`variant_rotation.load_rows`: this block and the one before)
NOVELTY_PER_SLOT = 1
MAX_FALLBACKS = 3
EXCLUDED_FAMILIES = ("skill_athletic", "strength_anchor")
GLOBAL_GATE_KINDS = ("pain_flag_exclusion", "equipment_available")  # evaluated here directly, not as a lock
PAIN_SOURCE = (
    "training_notes_pain.pain_class (#5806): only a `pain`-class note excludes, via the overlay's pain_flag tag; discomfort "
    "and form/equipment never exclude; a library not_for_you_now excludes as its own curated verdict"
)
GATES_SOURCE = "every locking gate reads LOCKED until #5772 evaluates gates (unknown input = locked)"
C_REASONS: dict[str, str] = {
    "equipment": "an A/B movement for this slot exists but is not available at home_gym",
    "pain_swap": "an A/B movement for this slot exists but is pain-excluded",
    "gate_locked": "an A/B movement for this slot exists but its gate is locked",
    "not_prescribable": "an A/B movement for this slot exists but the movement catalog cannot write it",
    "owner_pin": "the owner pinned this slot",
    "skill_track": "a skill/athletic track slot (never a hypertrophy slot)",
    "library_gap": "the library holds no A/B movement for this slot's job",
    "weekly_floor": "an A/B movement for this slot exists but the slot serves the week's family floor (#5759)",
    "not_for_you_now": "an A/B movement for this slot exists but the library marks it not-for-you-now (unlock recorded)",
}
"""Why a C movement is served. `equipment`, `pain_swap`, `owner_pin` and `skill_track` are the owner's (2026-11-11);
`gate_locked`, `not_prescribable`, `library_gap`, `weekly_floor` and `not_for_you_now` are platform-proposed: they name the A/B the slot could not serve."""
PROGRESSION_DROP = 0.05  # platform-proposed: a latest band best >5 % under the best band's e1RM reads as regressing
SKILL_TRACK_VOLUME = {"sets_max": 2, "reps_max": 5, "rpe_max": 7, "provenance": "platform-proposed (#5773), low volume"}

_LIB_TTL_S = 900
_LIB_CACHE: dict[str, Any] = {}


# ── loaders (fail-soft) ──────────────────────────────────────────────────────
def _read_library() -> dict[str, Any] | None:
    try:
        return xl.load_library()
    except (OSError, ValueError):
        pass
    try:  # the Lambda bundle does not stage config/: the S3 twin (synced on merge) is the runtime copy
        import boto3

        bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
        region = os.environ.get("AWS_REGION", "us-west-2")
        body = boto3.client("s3", region_name=region).get_object(Bucket=bucket, Key=f"config/{xl.LIBRARY_BASENAME}")["Body"].read()
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001 — fail soft: no library => the pools serve, and the record says so
        logger.warning(f"selection_engine: the exercise library is unreadable ({type(e).__name__}) — the #5075 pools serve")
        return None


def load_library_failsoft() -> dict[str, Any] | None:
    """The library, cached per container for `_LIB_TTL_S` (an approval flip arrives within the TTL). None when unreadable."""
    now = time.monotonic()
    if "lib" in _LIB_CACHE and now - _LIB_CACHE["at"] < _LIB_TTL_S:
        return _LIB_CACHE["lib"]
    lib = _read_library()
    _LIB_CACHE.update(lib=lib, at=now)
    return lib


def load_overlay_failsoft() -> dict[str, Any] | None:
    """The owner-private overlay — S3 only inside a Lambda (a laptop/test run reads env or the gitignored file). None on
    any failure: the N=1 fit is then `unknown`, never an error."""
    return xl.load_private_overlay(allow_s3=bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME")))


def library_version(lib: dict[str, Any] | None = None) -> str | None:
    """The library version a plan was made under (None = no library read), for `inputs_snapshot.library_version`."""
    lib = load_library_failsoft() if lib is None else lib
    return str(lib.get("version")) if isinstance(lib, dict) and lib.get("version") else None


def mode(lib: dict[str, Any] | None) -> str:
    """`live` only for an APPROVED library; `shadow` for any other status; `no_library` when none was read."""
    if not isinstance(lib, dict):
        return MODE_NO_LIBRARY
    return MODE_LIVE if lib.get("status") == APPROVED else MODE_SHADOW


# ── the library <-> catalog join ─────────────────────────────────────────────
def key_index(lib: dict[str, Any], catalog: dict[str, Any]) -> dict[str, dict[str, str]]:
    """`{"to_lib": catalog key -> library id, "to_cat": library id -> catalog key}` by Hevy template id (the catalog's
    `hevy_template_id_hint`, the library's raw `template_id`). A library id that is itself a catalog key also joins."""
    by_tid: dict[str, str] = {}
    for k, e in xl.movements(lib).items():
        if e.get("template_id"):
            by_tid[str(e["template_id"]).upper()] = k
    to_lib: dict[str, str] = {}
    for ck, c in catalog.items():
        lid = by_tid.get(str(c.get("hevy_template_id_hint") or "").upper()) or (ck if ck in xl.movements(lib) else None)
        if lid:
            to_lib[ck] = lid
    to_cat: dict[str, str] = {}
    for ck, lid in to_lib.items():
        to_cat.setdefault(lid, ck)
    return {"to_lib": to_lib, "to_cat": to_cat}


# ── per-movement facts ───────────────────────────────────────────────────────
def availability(
    entry: dict[str, Any], lib: dict[str, Any], overlay: dict[str, Any] | None, inventory: dict[str, Any] | None = None
) -> str | None:
    """Why `entry` is NOT available at home_gym, or None when it is. `inventory` defaults to the library's own
    `gym_inventory` (a #5771 `config/gym_inventory.json` passes its own). Contention is never read here."""
    row = (entry.get("availability") or {}).get(xl.LOCATION_ID) or {}
    if row.get("state") != "available":
        return f"availability at {xl.LOCATION_ID} is {row.get('state') or 'unknown'} ({row.get('source') or 'no source'})"
    items = ((inventory or lib.get("gym_inventory") or {}).get("items")) or {}
    learned = (overlay or {}).get("availability_learned") if isinstance(overlay, dict) else None
    for eid in entry.get("equipment") or []:
        st = ((items.get(eid) or {}).get(xl.LOCATION_ID) or {}).get("state")
        if st != "available":
            return f"equipment {eid} is {st or 'unknown'} at {xl.LOCATION_ID}"
        if (((learned or {}).get(eid) or {}).get(xl.LOCATION_ID) or {}).get("state") == "unavailable":
            return f"equipment {eid} learned unavailable at {xl.LOCATION_ID} (owner-confirmable)"
    return None


def locked_gates(entry: dict[str, Any], lib: dict[str, Any]) -> list[str]:
    """The entry's locking gates (every one LOCKED until #5772 — `GATES_SOURCE`). A clinical cue never locks; the two
    global gates (pain, equipment) are evaluated here directly."""
    gates = lib.get("gates") or {}
    return [g for g in entry.get("gates") or [] if (gates.get(g) or {}).get("locks") and gates[g].get("kind") not in GLOBAL_GATE_KINDS]


def pain_source_state(overlay: dict[str, Any] | None) -> str:
    """`classed` (the overlay's pain tags follow #5806's pain_class), `stale_overlay` (written before it — not trusted to
    exclude) or `absent`."""
    if not isinstance(overlay, dict):
        return "absent"
    return "classed" if overlay.get("pain_source") == xl.PAIN_SOURCE_ID else "stale_overlay"


def not_for_you_now(entry: dict[str, Any]) -> str | None:
    """The library's curated `not_for_you_now` verdict, or None."""
    nfy = entry.get("not_for_you_now")
    return f"not_for_you_now ({nfy.get('reason_code')}; unlock: {nfy.get('unlock_condition')})" if nfy else None


def pain_exclusion(entry: dict[str, Any], overlay: dict[str, Any] | None) -> str | None:
    """Why `entry` is pain-excluded (`PAIN_SOURCE`): a `pain`-class note on this template in a classed overlay. Never a
    discomfort or form note; never from a stale overlay."""
    if pain_source_state(overlay) == "classed" and xl.n1_view(entry, overlay).get("pain_flagged"):
        return "a pain-class note on this template (training_notes_pain.pain_class)"
    return None


def _target_matches(target: str, muscle: str) -> bool:
    t, m = str(target or "").lower(), str(muscle or "").lower()
    if not t or not m:
        return False
    sub = {"calves": ("gastrocnemius", "soleus")}
    return t == m or t.startswith(m) or m.startswith(t) or t.startswith(sub.get(m, ("\0",)))


def tier_for(entry: dict[str, Any], muscle: str) -> str:
    """The best hypertrophy tier among the entry's rows for `muscle` (a sub-target counts: `triceps_long_head` is
    triceps, `gastrocnemius` is calves). No row for the muscle => C."""
    ranks = [TIER_RANK.get(r.get("tier"), 2) for r in entry.get("hypertrophy") or [] if _target_matches(r.get("target"), muscle)]
    return "ABC"[min(ranks)] if ranks else "C"


def _progression(best_by_band: Any) -> int | None:
    rows = [r for r in (best_by_band or {}).values() if isinstance(r, dict) and r.get("weight_kg") and r.get("reps")]
    if len(rows) < 2:
        return None
    e1 = [(str(r.get("date") or ""), float(r["weight_kg"]) * (1 + int(r["reps"]) / 30.0)) for r in rows]
    latest = max(e1)[1]
    top = max(v for _, v in e1)
    return 1 if latest >= top else (-1 if latest < top * (1 - PROGRESSION_DROP) else 0)


def n1_fit(entry: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    """His N=1 fit from the overlay: progression (+1 latest band best is his best, -1 >5 % under), pain history
    (-1 per coded joint-discomfort tag, capped -2), sentiment (+1 net positive, -1 net negative), swap-out frequency
    (-1 when >= 2 swap notes). The weights are platform-proposed. Overlay silent => `unknown`, score 0."""
    view = xl.n1_view(entry, overlay)
    if view["n1_fit"] != "known":
        return {"fit": "unknown", "score": 0, "components": {}}
    sig = view.get("note_signals") or {}
    comp = {
        "progression": _progression(view.get("best_set_by_band")),
        "pain_history": -min(2, int(sig.get("joint_discomfort") or 0)),
        "sentiment": (lambda d: (d > 0) - (d < 0))(int(sig.get("sentiment_positive") or 0) - int(sig.get("sentiment_negative") or 0)),
        "swap_out": -1 if int(sig.get("swap") or 0) >= 2 else 0,
    }
    return {"fit": "known", "score": sum(v for v in comp.values() if v), "components": comp}


def is_novel(entry: dict[str, Any], catalog_entry: dict[str, Any] | None) -> bool:
    """New to him: an expansion candidate, or no logged exposure in either the library or the catalog."""
    exposures = int(((entry.get("history") or {}).get("exposures")) or 0)
    return entry.get("source") == "expansion" or (exposures < 1 and not int((catalog_entry or {}).get("sessions") or 0))


# ── one slot ─────────────────────────────────────────────────────────────────
def slot_spec(slot: dict[str, Any], catalog: dict[str, Any], lib: dict[str, Any], idx: dict[str, dict[str, str]]) -> dict[str, Any]:
    """The slot's stimulus: its muscle (the template accessory's library target, else its catalog muscle), its JOB (the
    movement patterns of the template accessory and its #5075 vetted pool) and its volume signature."""
    from training import variant_rotation as vr

    inc = slot["incumbent"]
    pool = [inc] + list((vr.VETTED_POOLS.get(inc) or {}).get("candidates") or [])
    lid = idx["to_lib"].get(inc)
    muscle = ((xl.movements(lib).get(lid) or {}).get("target") or {}).get("primary") if lid else None
    return {
        "muscle": muscle or (catalog.get(inc) or {}).get("primary_muscle"),
        "patterns": sorted({xl.movement_pattern(str((catalog.get(k) or {}).get("title") or "")) for k in pool} - {"other"}),
        "signature": vr.volume_signature(inc, catalog),
        "hevy_types": sorted({str(t) for t in vr.LOADED_HEVY_TYPES + ((catalog.get(inc) or {}).get("hevy_type"),) if t}),
        "incumbent_library_id": lid,
    }


def _not_prescribable(ck: str | None, spec: dict[str, Any], catalog: dict[str, Any], ceiling: int, missing: list[str]) -> str | None:
    from training import movement_catalog, variant_rotation as vr

    entry = catalog.get(ck or "")
    if not ck or entry is None:
        return "no movement-catalog entry (the generator cannot write it)"
    if vr.volume_signature(ck, catalog) != spec["signature"]:
        return "a different volume signature — the week's counts would move"
    if not movement_catalog.generator_eligible(entry, ceiling, key=ck):
        return f"not generator-eligible at skill ceiling {ceiling}"
    if entry.get("hevy_type") and entry["hevy_type"] not in spec["hevy_types"]:
        return f"not a loaded rep-based template (hevy_type {entry.get('hevy_type')})"
    hit = vr._unavailable(ck, entry, missing)
    return f"on the charter's equipment.not_available list ({hit!r})" if hit else None


def _exclusion(lid: str, e: dict[str, Any], ck: str | None, ctx: dict[str, Any]) -> tuple[str, str] | None:
    """(C-reason code, why) for a library movement this slot cannot serve, or None."""
    why = pain_exclusion(e, ctx["overlay"])
    if why:
        return "pain_swap", why
    why = not_for_you_now(e)
    if why:
        return "not_for_you_now", why
    why = availability(e, ctx["lib"], ctx["overlay"], ctx["inventory"])
    if why:
        return "equipment", why
    gates = locked_gates(e, ctx["lib"])
    if gates:
        return "gate_locked", f"gate {', '.join(gates)} locked ({GATES_SOURCE})"
    why = _not_prescribable(ck, ctx["spec"], ctx["catalog"], ctx["ceiling"], ctx["missing"])
    if why:
        return "not_prescribable", why
    if ctx["floor_members"] is not None and ck not in ctx["floor_members"]:
        return "weekly_floor", f"not a {ctx['floor']} member — the weekly floor serves only its family here (#5759)"
    if is_novel(e, ctx["catalog"].get(ck or "")):
        from training import form_cue_sheets

        if form_cue_sheets.sheet_for(str(e.get("title") or "")) is None:
            return "not_prescribable", "new to him and no cue sheet exists for it"
    return None


def _candidate(lid: str, e: dict[str, Any], ck: str | None, ctx: dict[str, Any]) -> dict[str, Any]:
    novel = is_novel(e, ctx["catalog"].get(ck or ""))
    return {
        "movement_id": lid,
        "catalog_key": ck,
        "title": e.get("title"),
        "tier": tier_for(e, ctx["spec"]["muscle"]),
        "n1": n1_fit(e, ctx["overlay"]),
        "length_bias": e.get("length_bias"),
        "equipment": list(e.get("equipment") or []),
        "novel": novel,
        "exposures": int(((e.get("history") or {}).get("exposures")) or 0),
    }


def candidates(ctx: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(eligible, excluded) library movements for one slot. `excluded` keeps every movement of the slot's job the slot
    could not serve, with its C-reason code — that is what names the reason a C pick is served."""
    spec, lib = ctx["spec"], ctx["lib"]
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for lid, e in sorted(xl.movements(lib).items()):
        if e.get("family") in EXCLUDED_FAMILIES or (e.get("target") or {}).get("primary") != spec["muscle"]:
            continue
        if xl.movement_pattern(str(e.get("title") or "")) not in spec["patterns"]:
            continue
        ck = ctx["idx"]["to_cat"].get(lid)
        c = _candidate(lid, e, ck, ctx)
        hit = _exclusion(lid, e, ck, ctx)
        if hit:
            excluded.append({**c, "code": hit[0], "why": hit[1]})
        else:
            eligible.append(c)
    return eligible, excluded


def rank_key(c: dict[str, Any], recent: set[str], week_taken: set[str]) -> tuple[Any, ...]:
    """Tier, then N=1 fit, then variety: not served in the lookback, not taken by another slot this week, familiar
    before new, more exposures, then the id (deterministic)."""
    ck = c.get("catalog_key") or ""
    return (TIER_RANK[c["tier"]], -c["n1"]["score"], ck in recent, ck in week_taken, c["novel"], -c["exposures"], c["movement_id"])


def c_reason(pick: dict[str, Any], excluded: list[dict[str, Any]], *, pinned: bool = False) -> dict[str, str] | None:
    """The recorded reason a C pick is served (None for an A/B pick). The A/B exclusion with the best tier names it."""
    if pick["tier"] != "C":
        return None
    if pinned:
        return {"code": "owner_pin", "why": C_REASONS["owner_pin"]}
    above = sorted((x for x in excluded if x["tier"] != "C"), key=lambda x: (TIER_RANK[x["tier"]], x["movement_id"]))
    if above:
        x = above[0]
        return {"code": x["code"], "why": f"{x['title']} (tier {x['tier']}): {x['why']}", "blocked": x["movement_id"]}
    return {"code": "library_gap", "why": C_REASONS["library_gap"]}


def fallbacks(pick: dict[str, Any], ranked: list[dict[str, Any]], *, novel_budget: int) -> list[dict[str, Any]]:
    """The pick's ranked same-stimulus fallbacks: the slot's next eligible candidates, those sharing no equipment with the
    pick first (a missing item is a swap, not the same hole), new-to-him ones only inside the slot's novelty budget."""
    out, used = [], 0
    rest = [c for c in ranked if c["movement_id"] != pick["movement_id"]]
    rest.sort(key=lambda c: bool(set(c["equipment"]) & set(pick["equipment"])))
    for c in rest:
        if c["novel"] and used >= novel_budget:
            continue
        used += int(c["novel"])
        out.append(
            {k: c[k] for k in ("movement_id", "catalog_key", "title", "tier", "novel")}
            | {"shares_equipment": bool(set(c["equipment"]) & set(pick["equipment"]))}
        )
        if len(out) >= MAX_FALLBACKS:
            break
    return out


def _novel_terms(pick: dict[str, Any]) -> dict[str, Any] | None:
    if not pick.get("novel"):
        return None
    from training import form_cue_sheets, layoff_tiers

    return {
        "caps": dict(layoff_tiers.EXPOSURE_CAPS),
        "ruling": layoff_tiers.OD1_RULING,
        "cue_sheet": form_cue_sheets.sheet_for(str(pick["title"] or "")),
    }


def select_slot(slot: dict[str, Any], ctx: dict[str, Any], recent: set[str], week_taken: set[str]) -> dict[str, Any]:
    """One slot's selection: the ranked eligible candidates, the pick, its C-reason, its fallbacks, the exclusions."""
    eligible, excluded = candidates(ctx)
    ranked = sorted(eligible, key=lambda c: rank_key(c, recent, week_taken))
    above = [x for x in excluded if TIER_RANK[x["tier"]] < TIER_RANK[ranked[0]["tier"]]] if ranked else excluded
    base = {"slot_id": slot["slot_id"], "role": slot["role"], "incumbent": slot["incumbent"], "spec": ctx["spec"], "floor": ctx["floor"]}
    if not ranked:
        return {
            **base,
            "pick": None,
            "reason": "no eligible library candidate — the template accessory serves",
            "ranked": [],
            "excluded": excluded,
        }
    pick = ranked[0]
    budget = NOVELTY_PER_SLOT - int(pick["novel"])
    return {
        **base,
        "pick": pick | {"c_reason": c_reason(pick, excluded), "novel_terms": _novel_terms(pick)},
        "fallbacks": fallbacks(pick, ranked, novel_budget=budget),
        "ranked": [c["movement_id"] for c in ranked],
        "above_pick": [{k: x[k] for k in ("movement_id", "title", "tier", "code", "why")} for x in above],
        "excluded": [{k: x[k] for k in ("movement_id", "tier", "code", "why")} for x in excluded],
    }


def _pinned(slot: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """An owner-pinned slot keeps its pin (`owner_pin`); it still carries its ranked fallbacks."""
    lid = ctx["idx"]["to_lib"].get(slot["incumbent"])
    e = xl.movements(ctx["lib"]).get(lid or "") or {"title": slot["incumbent"]}
    pick = _candidate(lid or slot["incumbent"], e, slot["incumbent"], ctx)
    pick |= {"c_reason": c_reason(pick, [], pinned=True), "novel_terms": None}
    eligible, _excluded = candidates(ctx)
    ranked = sorted(eligible, key=lambda c: rank_key(c, set(), set()))
    return {
        "slot_id": slot["slot_id"],
        "role": slot["role"],
        "incumbent": slot["incumbent"],
        "pinned": slot["pinned"],
        "pick": pick,
        "fallbacks": fallbacks(pick, ranked, novel_budget=NOVELTY_PER_SLOT),
        "ranked": [c["movement_id"] for c in ranked],
        "above_pick": [],
        "excluded": [],
    }


# ── the week ─────────────────────────────────────────────────────────────────
def recent_uses(rows: list[dict[str, Any]] | None, position: dict[str, Any] | None) -> set[str]:
    """Catalog keys the rotation ledger served in the lookback (this block's earlier phases and the block before), never
    the current phase's own row (that is this draft's held pick)."""
    out: set[str] = set()
    for r in rows or []:
        blk = int(r.get("block") or str(r.get("sk") or "ROTATION#B000#").split("#")[1][1:] or 0)
        for k, v in r.items():
            if not (k.startswith("phase_") and isinstance(v, dict) and v.get("variant")):
                continue
            if position and blk == position.get("block") and k == f"phase_{position.get('phase')}":
                continue
            out.add(str(v["variant"]))
    return out


def _ctx(slot: dict[str, Any], env: dict[str, Any], step: int) -> dict[str, Any]:
    from training import variant_rotation as vr
    from training.week_floors import WEEKLY_FAMILY_FLOORS, family_members

    fam = (vr.VETTED_POOLS.get(slot["incumbent"]) or {}).get("charter_family")
    floor = fam if fam in WEEKLY_FAMILY_FLOORS and step > 0 else None
    spec = slot_spec(slot, env["catalog"], env["lib"], env["idx"])
    return {**env, "spec": spec, "floor": floor, "floor_members": family_members(floor) if floor else None}


def _lengthened_pass(picked: list[dict[str, Any]], full: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Each muscle >= 1 lengthened-bias movement per week — inside the pick's tier and N=1 score only."""
    rows = []
    for muscle in sorted({p["spec"]["muscle"] for p in picked if p.get("spec") and p.get("pick")}):
        group = [p for p in picked if p.get("spec", {}).get("muscle") == muscle and p.get("pick") and not p.get("pinned")]
        if any(p["pick"]["length_bias"] == "lengthened" for p in group):
            rows.append({"muscle": muscle, "state": "met"})
            continue
        swapped = None
        for p in group:
            alt = next(
                (
                    c
                    for c in full[p["slot_id"]]
                    if c["length_bias"] == "lengthened" and c["tier"] == p["pick"]["tier"] and c["n1"]["score"] == p["pick"]["n1"]["score"]
                ),
                None,
            )
            if alt:
                p["pick"] = alt | {"c_reason": p["pick"]["c_reason"], "novel_terms": _novel_terms(alt)}
                p["fallbacks"] = fallbacks(p["pick"], full[p["slot_id"]], novel_budget=NOVELTY_PER_SLOT - int(alt["novel"]))
                p["lengthened_swap"] = True
                swapped = p["slot_id"]
                break
        rows.append(
            {"muscle": muscle, "state": "adjusted" if swapped else "unmet", "slot_id": swapped}
            | ({} if swapped else {"why": "no lengthened candidate at the pick's tier and N=1 fit"})
        )
    return rows


def _skill_track(lib: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    """The optional skill/athletic track: its own ladders (the library's chain gates), low volume, never a hypertrophy
    slot. A rung is open when the movement is available and no locking gate holds it (all locked until #5772)."""
    mv = xl.movements(lib)
    nxt: dict[str, str] = {}
    for gid, g in sorted((lib.get("gates") or {}).items()):
        carriers = sorted(k for k, e in mv.items() if gid in (e.get("gates") or []))
        for pre in g.get("chain_prerequisites") or []:
            for k in carriers:
                nxt.setdefault(pre, k)
    roots = sorted(k for k in nxt if k not in nxt.values() and k in mv)
    ladders = []
    for root in roots:
        chain, k = [root], root
        while k in nxt and nxt[k] not in chain:
            k = nxt[k]
            chain.append(k)
        if not any(mv.get(m, {}).get("family") == "skill_athletic" for m in chain):
            continue
        rungs = [
            {"movement_id": m, "open": not locked_gates(mv[m], lib) and availability(mv[m], lib, env["overlay"], env["inventory"]) is None}
            for m in chain
        ]
        ladders.append({"ladder": chain, "current_rung": next((r["movement_id"] for r in rungs if r["open"]), None), "rungs": rungs})
    return {
        "optional": True,
        "volume": SKILL_TRACK_VOLUME,
        "c_reason": "skill_track",
        "never_in": "a hypertrophy slot",
        "ladders": ladders,
        "served": False,
    }


def _trim(p: dict[str, Any]) -> dict[str, Any]:
    """The stored shape: the pick, its fallbacks, the five best-ranked ids, the A/B above the pick, counts of the rest."""
    counts: dict[str, int] = {}
    for x in p.get("excluded") or []:
        counts[x["code"]] = counts.get(x["code"], 0) + 1
    out = {k: v for k, v in p.items() if k not in ("excluded", "ranked", "spec")}
    pick = out.get("pick")
    if pick:
        out["pick"] = {
            k: pick[k] for k in ("movement_id", "catalog_key", "title", "tier", "n1", "length_bias", "novel", "c_reason", "novel_terms")
        }
    return out | {
        "muscle": (p.get("spec") or {}).get("muscle"),
        "ranked_top": (p.get("ranked") or [])[:5],
        "excluded_counts": counts,
        "fallback_note": fallback_note_line(pick, p.get("fallbacks")),  # the slot's line, recorded (#5771 renders note_fallbacks)
    }


def select_week(
    position: dict[str, Any] | None,
    catalog: dict[str, Any],
    lib: dict[str, Any],
    overlay: dict[str, Any] | None,
    *,
    rows: list[dict[str, Any]] | None = None,
    missing: list[str] | None = None,
    skill_ceiling: int = 2,
    inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Every accessory slot of the week ranked from the library. Pure (the caller loads library, overlay and ledger)."""
    from training import variant_rotation as vr

    env = {
        "lib": lib,
        "catalog": catalog,
        "overlay": overlay,
        "inventory": inventory,
        "idx": key_index(lib, catalog),
        "ceiling": skill_ceiling,
        "missing": vr.not_available() if missing is None else missing,
    }
    step = int((position or {}).get("step") or 0)
    recent, taken = recent_uses(rows, position), set[str]()
    picked: list[dict[str, Any]] = []
    full: dict[str, list[dict[str, Any]]] = {}
    for slot in vr.slots():
        ctx = _ctx(slot, env, step)
        if slot["pinned"]:
            p = _pinned(slot, ctx) | {"spec": ctx["spec"]}
        else:
            p = select_slot(slot, ctx, recent, taken)
            full[slot["slot_id"]] = sorted(candidates(ctx)[0], key=lambda c: rank_key(c, recent, taken))
        if p.get("pick") and p["pick"].get("catalog_key"):
            taken.add(p["pick"]["catalog_key"])
        picked.append(p)
    lengthened = _lengthened_pass(picked, full)
    by_role: dict[str, dict[str, str]] = {}
    for p in picked:
        by_role.setdefault(p["role"], {})[p["incumbent"]] = (p.get("pick") or {}).get("catalog_key") or p["incumbent"]
    from training import week_floors

    served = [{"key": v, "slot_id": f"{r}.{inc}", "role": r} for r, m in by_role.items() for inc, v in m.items()]
    return {
        "issue": ISSUE,
        "library_version": library_version(lib),
        "library_status": lib.get("status"),
        "pain_source": PAIN_SOURCE,
        "pain_source_state": pain_source_state(overlay),
        "gates_source": GATES_SOURCE,
        "position": position,
        "variety_lookback_blocks": VARIETY_LOOKBACK_BLOCKS,
        "slots": [_trim(p) for p in picked],
        "variants_by_role": by_role,
        "lengthened": lengthened,
        "novelty": {"per_slot": NOVELTY_PER_SLOT, "novel_picks": [p["slot_id"] for p in picked if (p.get("pick") or {}).get("novel")]},
        "skill_track": _skill_track(lib, env),
        "week_check": week_floors.check_week(served, [], catalog, status=lib.get("status")),  # #5759/#5774's own check, unchanged
    }


# ── the switch: shadow beside the pools, live only for an approved library ───
def _compare(rotation: dict[str, Any], sel: dict[str, Any]) -> list[dict[str, Any]]:
    pools = rotation.get("variants_by_role") or {}
    return [
        {
            "slot_id": s["slot_id"],
            "pool": (pools.get(s["role"]) or {}).get(s["incumbent"], s["incumbent"]),
            "selection": (s.get("pick") or {}).get("catalog_key") or s["incumbent"],
            "tier": (s.get("pick") or {}).get("tier"),
        }
        for s in sel["slots"]
    ]


def _live(
    rotation: dict[str, Any],
    sel: dict[str, Any],
    catalog: dict[str, Any],
    rows: list[dict[str, Any]] | None,
    skill_ceiling: int,
    target_date: str | None,
) -> dict[str, Any]:
    """The approved library serves: each of the served role's slots takes its selection pick — or the ledger's variant for
    this phase when that is still an eligible candidate (the first draft of a phase decides it). A selection that would
    move the week's counts is refused and the pools serve, said so."""
    from training import variant_rotation as vr

    pos = rotation.get("position") or {}
    if int(pos.get("step") or 0) <= 0:
        return rotation | {"selection_note": "block 1's first phase serves the template as written (#5075 step 0)"}
    by_slot = {s["slot_id"]: s for s in sel["slots"]}
    by_role = {r: dict(v) for r, v in (rotation.get("variants_by_role") or {}).items()}
    slots, writes = [], []
    for s in rotation.get("slots") or []:
        chosen = by_slot.get(s["slot_id"]) or {}
        pick = (chosen.get("pick") or {}).get("catalog_key")
        if s.get("source") == "pinned" or not pick:
            slots.append(s)
            continue
        held = vr._ledger_variant(rows, pos["block"], s["slot_id"], pos["phase"])
        eligible = {(chosen.get("pick") or {}).get("catalog_key")} | {f.get("catalog_key") for f in chosen.get("fallbacks") or []}
        variant = held if held and held in eligible else pick
        by_role.setdefault(s["role"], {})[s["incumbent"]] = variant
        pool = [k for k in [pick] + [f.get("catalog_key") for f in chosen.get("fallbacks") or []] if k]
        slots.append(s | {"variant": variant, "source": "ledger" if variant == held else "selection", "pool": pool})
        if not held:
            writes.append(
                {**{k: s[k] for k in ("block", "phase", "weeks", "slot_id", "role", "incumbent")}, "variant": variant, "pool": pool}
            )
    check = vr.volume_check(catalog, by_role, skill_ceiling)
    if not check["unchanged"]:
        return rotation | {
            "selection_note": f"selection REFUSED — it would move the week's counts ({', '.join(check['moved'])}); the pools serve"
        }
    from training.training_charter import charter_version

    writes = [w | {"target_date": target_date, "charter_version": charter_version()} for w in writes]
    role = (rotation.get("slots") or [{}])[0].get("role")
    return rotation | {
        "variants": by_role.get(role, rotation.get("variants") or {}),
        "variants_by_role": by_role,
        "slots": slots,
        "ledger_writes": writes,
        "volume_check": check,
        "source": "selection",
        "rationale": list(rotation.get("rationale") or []) + [_line(s) for s in sel["slots"] if s["role"] == role],
    }


def _line(s: dict[str, Any]) -> str:
    p = s.get("pick") or {}
    why = f" — C because {p['c_reason']['code']}: {p['c_reason']['why']}" if p.get("c_reason") else ""
    return f"selection: {p.get('title') or s['incumbent']} [tier {p.get('tier')}] for {s['slot_id']}{why}"


def apply(
    rotation: dict[str, Any],
    catalog: dict[str, Any],
    *,
    rows: list[dict[str, Any]] | None = None,
    skill_ceiling: int = 2,
    target_date: str | None = None,
    lib: Any = ...,
    overlay: Any = ...,
) -> dict[str, Any]:
    """The rotation a draft serves, with the selection attached. `live` (an approved library) rewrites the served role's
    accessory variants; `shadow` leaves the #5075 pools serving and attaches the selection for comparison; `no_library`
    attaches the state. Never raises: a selection that fails is recorded as `failed` and the pools serve."""
    lib = load_library_failsoft() if lib is ... else lib
    m = mode(lib)
    if m == MODE_NO_LIBRARY:
        return rotation | {"selection": {"issue": ISSUE, "mode": m, "library_version": None}}
    try:
        overlay = load_overlay_failsoft() if overlay is ... else overlay
        sel = select_week(rotation.get("position"), catalog, lib, overlay, rows=rows, skill_ceiling=skill_ceiling)
    except Exception as e:  # noqa: BLE001 — the selection never blocks a draft
        logger.warning(f"selection_engine: the selection failed ({type(e).__name__}: {e}) — the #5075 pools serve")
        return rotation | {"selection": {"issue": ISSUE, "mode": m, "state": "failed", "error": f"{type(e).__name__}: {e}"[:200]}}
    sel |= {"mode": m, "overlay": "read" if isinstance(overlay, dict) else "absent (N=1 fit unknown)", "compare": _compare(rotation, sel)}
    if m == MODE_LIVE:
        return _live(rotation, sel, catalog, rows, skill_ceiling, target_date) | {"selection": sel}
    return rotation | {"selection": sel}


def snapshot_fields(rotation: dict[str, Any]) -> dict[str, Any]:
    """The draft's `inputs_snapshot` fields, popped off the rotation: `selection_shadow` while the library is proposed
    (the pools served), `selection` once it serves live."""
    sel = rotation.pop("selection", None)
    if not sel:
        return {}
    return {"selection" if sel.get("mode") == MODE_LIVE else "selection_shadow": sel}


def fallback_note_line(pick: dict[str, Any] | None, fallbacks_: list[dict[str, Any]] | None) -> str | None:
    """The slot's recorded fallback line — "If taken: X, then Y." (`hevy_note_grammar.fallback_line`), library titles. None
    when there is no fallback. The WIRE line is `note_fallbacks` -> `lift_note.fit_fallback` (catalog titles, the budget)."""
    from training import hevy_note_grammar

    names = [str(f.get("title") or f.get("movement_id")) for f in fallbacks_ or [] if f.get("catalog_key")]
    if not pick or not names:
        return None
    return hevy_note_grammar.fallback_line(names)


# ── the Hevy note's fallback line (#5771) ────────────────────────────────────
def _library_fallbacks(key: str, env: dict[str, Any]) -> list[str]:
    """The served key's library `fallbacks` (ranked same-stimulus at build time), as catalog keys, kept only when each one
    is usable today: available at home_gym (inventory + learned unavailability; contention never removes one), not
    pain-excluded, not `not_for_you_now`, no locked gate, and PRESCRIBABLE with the served lift's volume signature — an
    anchor's fallback that would move the week's counts is not named (owner brief, 2026-11-11)."""
    from training import variant_rotation as vr

    lid = env["idx"]["to_lib"].get(key)
    mv = xl.movements(env["lib"])
    if not lid or lid not in mv:
        return []
    spec = {
        "muscle": None,
        "patterns": [],
        "signature": vr.volume_signature(key, env["catalog"]),
        "hevy_types": sorted({str(t) for t in vr.LOADED_HEVY_TYPES + ((env["catalog"].get(key) or {}).get("hevy_type"),) if t}),
    }
    ctx = {**env, "spec": spec, "floor": None, "floor_members": None}
    out = []
    for fb in mv[lid].get("fallbacks") or []:
        m = fb.get("movement_id")
        ck = env["idx"]["to_cat"].get(m or "")
        if m in mv and ck and ck != key and _exclusion(m, mv[m], ck, ctx) is None:
            out.append(ck)
    return out


def _slot_fallbacks(key: str, sel: dict[str, Any], role: str | None) -> list[str] | None:
    """The served key's ranked fallbacks from its slot's selection (live: the slot serves its pick, or a ledger-held
    fallback — then the pick leads the rest), as catalog keys; None when no slot of the served role serves `key`."""
    for s in sel.get("slots") or []:
        if role and s.get("role") != role:
            continue
        pick = (s.get("pick") or {}).get("catalog_key")
        rest = [f.get("catalog_key") for f in s.get("fallbacks") or [] if f.get("catalog_key")]
        if pick == key:
            return rest
        if key in rest:
            return [k for k in [pick] + rest if k and k != key]
    return None


def note_fallbacks(
    rotation: dict[str, Any] | None,
    served_keys: list[str],
    catalog: dict[str, Any],
    *,
    skill_ceiling: int = 2,
    lib: Any = ...,
    overlay: Any = ...,
) -> dict[str, Any]:
    """Per served lift, the ranked same-stimulus fallback titles its Hevy note names (`lift_note.fit_fallback`, owner ruling
    2026-11-11 on #5771): `{"mode", "render", "by_key": {served key: [Hevy title, ...]}}`.

    An accessory slot's list is its selection's (the slot's next eligible candidates, equipment-disjoint first); any other
    served lift (an anchor, or an accessory the #5075 pools serve in shadow) takes its library entry's ranked `fallbacks`,
    filtered for today (`_library_fallbacks`). A movement served elsewhere in the session is never a fallback (that is a
    second set of the same lift, not a swap). Unavailable is never named; contention-only equipment still is.

    `render` is True only when the library is APPROVED (THE SWITCH): while it is `proposed` the lines are computed and
    recorded (`inputs_snapshot["note_fallbacks"]`) but stay off the wire. Never raises: a failure is `state: failed`."""
    sel = (rotation or {}).get("selection") or {}
    m = sel.get("mode") or MODE_NO_LIBRARY
    if m == MODE_NO_LIBRARY:
        return {"issue": "#5771", "mode": m, "render": False, "by_key": {}}
    try:
        lib = load_library_failsoft() if lib is ... else lib
        if not isinstance(lib, dict):
            return {"issue": "#5771", "mode": MODE_NO_LIBRARY, "render": False, "by_key": {}}
        overlay = load_overlay_failsoft() if overlay is ... else overlay
        from training import variant_rotation as vr

        env = {
            "lib": lib,
            "catalog": catalog,
            "overlay": overlay,
            "inventory": None,
            "idx": key_index(lib, catalog),
            "ceiling": skill_ceiling,
            "missing": vr.not_available(),
        }
        role = ((rotation or {}).get("slots") or [{}])[0].get("role")
        served = set(served_keys)
        by_key: dict[str, list[str]] = {}
        for key in served_keys:
            ranked = _slot_fallbacks(key, sel, role)
            if ranked is None:
                ranked = _library_fallbacks(key, env)
            titles = [str((catalog.get(k) or {}).get("title") or k) for k in ranked if k not in served]
            if titles:
                by_key[key] = titles[:MAX_FALLBACKS]
    except Exception as e:  # noqa: BLE001 — a fallback line never blocks a draft
        logger.warning(f"selection_engine: note fallbacks failed ({type(e).__name__}: {e}) — no fallback line")
        return {"issue": "#5771", "mode": m, "render": False, "state": "failed", "error": f"{type(e).__name__}: {e}"[:200], "by_key": {}}
    return {"issue": "#5771", "mode": m, "render": m == MODE_LIVE, "by_key": by_key}
