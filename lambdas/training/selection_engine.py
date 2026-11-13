"""selection_engine.py — each accessory slot filled by the best-quality movement he can do, with the reason recorded (#5773).

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
    pool        = the slot's top two non-empty quality bands (owner ruling 2026-11-12: S and A are both programmable); a
                  candidate outside the pool ranks after every pool member, by tier
    rank        = inside the pool: N=1 fit from the owner-private overlay (progression, pain history, sentiment; swap-out frequency
                     demotes; an absent overlay is `unknown`, score 0 — never an error)
                  -> variety (the movement THIS SLOT served least recently in the last VARIETY_LOOKBACK_BLOCKS blocks of the
                     rotation ledger first, #5857: slots sharing one band each rotate within it; then not served by any
                     slot in that window; then
                     familiar before new-to-him; then history exposures)
                  -> the QUALITY tier (S over A, the library's rubric tier, #5857) as a tie-break
                  -> evidence confidence, a tie-break only (rct_direct over rct_characteristic over consensus over
                     none_reviewed — evidence is shown beside the tier, never used as it)
    no repeats  = best per slot, NO REPEATS PER WEEK (owner ruling 2026-11-11): a movement another slot already serves
                  this program week is passed over and the next-best eligible candidate fills the later slot, recorded
                  as `week_repeat` (a repeat only when nothing else is left: `week_repeat_unavoidable`). Pins are exempt.
    B / C / D   = (outside S∪A) served only with a recorded reason (`C_REASONS`, on the pick as `c_reason`): a higher-tier
                  candidate for the slot exists and is excluded by equipment, pain, a locked gate, or the catalog; it ranked
                  below on fit inside the pool (`pool_fit`); the slot is an owner pin or the skill track; or the library
                  holds no higher-tier movement for the slot's job (`library_gap`).
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

OWNER APPROVAL (#5776). `apply(approvals=...)` takes the block design review's resolved approval
(`block_design_review.resolve`, read beside the ledger by `variant_rotation.for_session`). Once it was read, a LIVE draft
serves only owner-approved picks: each approved slot is an owner pin (`_owner_pinned` — an approved movement the slot can
no longer serve is refused, never forced, and the pool's variant serves); a block with no approval serves the prior
block's (said so); with neither, the pools serve. The approval's one-block experiment pin rides its slot (`experiment`).

Every draft records `library_version` (`routine_repo.stamp_library_version`), as it records `charter_version`.
Pure apart from the fail-soft loaders at the top.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from training import exercise_library as xl, selection_live as live

logger = logging.getLogger(__name__)

ISSUE = "#5773"
APPROVED = "approved"
MODE_LIVE = "live"
MODE_SHADOW = "shadow"
MODE_NO_LIBRARY = "no_library"
TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}  # the library's QUALITY tier (#5857, `quality_rubric`)
PROGRAMMABLE_TIERS = ("S", "A")  # owner ruling 2026-11-12 (board rec 2): S and A are both programmable
REASONED_TIERS = ("B", "C", "D")  # a pick outside S∪A is served only with a recorded reason (`c_reason`)
POOL_BANDS = 2  # a slot's pool is its top two non-empty bands
UNRATED_TIER = "D"  # a movement with no hypertrophy row for the slot's muscle
EVIDENCE_RANK = {"rct_direct": 0, "rct_characteristic": 1, "consensus": 2, "none_reviewed": 3}  # a tie-break, never the tier
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
    "equipment": "a higher-tier movement for this slot exists but is not available at home_gym",
    "pain_swap": "a higher-tier movement for this slot exists but is pain-excluded",
    "gate_locked": "a higher-tier movement for this slot exists but its gate is locked",
    "not_prescribable": "a higher-tier movement for this slot exists but the movement catalog cannot write it",
    "owner_pin": "the owner pinned this slot",
    "skill_track": "a skill/athletic track slot (never a hypertrophy slot)",
    "library_gap": "the library holds no higher-tier movement for this slot's job",
    "weekly_floor": "a higher-tier movement for this slot exists but the slot serves the week's family floor (#5759)",
    "not_for_you_now": "a higher-tier movement for this slot exists but the library marks it not-for-you-now (unlock recorded)",
    "week_repeat": "every higher-tier movement for this slot already fills another slot this program week (no repeats)",
    "pool_fit": "a member of the slot's top-two-band pool, ranked below this pick on N=1 fit or slot variety (owner ruling 2026-11-12)",
}
"""Why a C or D movement is served (the codes predate the S-D quality tiers, #5857, and are unchanged). `equipment`, `pain_swap`, `owner_pin` and `skill_track` are the owner's (2026-11-11);
`gate_locked`, `not_prescribable`, `library_gap`, `weekly_floor` and `not_for_you_now` are platform-proposed; `week_repeat`
follows the owner's no-repeats ruling (2026-11-11): they name the higher-tier movement the slot could not serve."""
PROGRESSION_DROP = 0.05  # platform-proposed: a latest band best >5 % under the best band's e1RM reads as regressing
APPROVAL_SERVES = ("approved", "prior_block")  # `block_design_review.APPROVED` / `PRIOR_BLOCK` (#5776)
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
    `hevy_template_id_hint`, the library's raw `template_id`). A library id that is itself a catalog key also joins. A
    catalog entry with NO hint (resolved by title at commit, ADR-069 — `reverse_pec_deck`) joins the one library entry
    whose title is the same, exactly (#5780: without it the incumbent of a slot had no library entry)."""
    by_tid: dict[str, str] = {}
    by_title: dict[str, list[str]] = {}
    for k, e in xl.movements(lib).items():
        if e.get("template_id"):
            by_tid[str(e["template_id"]).upper()] = k
        by_title.setdefault(str(e.get("title") or "").strip().lower(), []).append(k)
    to_lib: dict[str, str] = {}
    for ck, c in catalog.items():
        hint = str(c.get("hevy_template_id_hint") or "").upper()
        same_title = by_title.get(str(c.get("title") or "").strip().lower()) or []
        lid = by_tid.get(hint) or (ck if ck in xl.movements(lib) else None)
        if not lid and not hint and str(c.get("title") or "").strip() and len(same_title) == 1:
            lid = same_title[0]
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
    global gates (pain, equipment) are evaluated here directly. LIVE reads the evaluation (`selection_live.gates`)."""
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


def _rows_for(entry: dict[str, Any], muscle: str) -> list[dict[str, Any]]:
    return [r for r in entry.get("hypertrophy") or [] if _target_matches(r.get("target"), muscle)]


def tier_for(entry: dict[str, Any], muscle: str) -> str:
    """The best QUALITY tier (S-D, the library's rubric tier, #5857) among the entry's rows for `muscle` (a sub-target
    counts: `triceps_long_head` is triceps, `gastrocnemius` is calves). No row for the muscle => D."""
    ranks = [TIER_RANK.get(str(r.get("tier")), TIER_RANK[UNRATED_TIER]) for r in _rows_for(entry, muscle)]
    return "SABCD"[min(ranks)] if ranks else UNRATED_TIER


def evidence_for(entry: dict[str, Any], muscle: str) -> str:
    """The strongest evidence confidence among the entry's rows for `muscle` — a tie-break and a label, never the tier."""
    ranks = [EVIDENCE_RANK.get(str(r.get("evidence_confidence")), 3) for r in _rows_for(entry, muscle)]
    return list(EVIDENCE_RANK)[min(ranks)] if ranks else "none_reviewed"


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
    if why and str(e.get("template_id") or "").upper() not in ((ctx.get("policy") or {}).get("mild_pain") or ()):  # FIX4, live only
        return "pain_swap", why
    why = not_for_you_now(e)
    if why:
        return "not_for_you_now", why
    why = availability(e, ctx["lib"], ctx["overlay"], ctx["inventory"])
    if why:
        return "equipment", why
    gates = live.gates(lid, e, ctx)
    if gates:
        return "gate_locked", f"gate {', '.join(gates)} locked ({live.LIVE_GATES_SOURCE if ctx.get('policy') else GATES_SOURCE})"
    why = _not_prescribable(ck, ctx["spec"], ctx["catalog"], ctx["ceiling"], ctx["missing"])
    if why:
        return "not_prescribable", why
    if ctx["floor_members"] is not None and ck not in ctx["floor_members"]:
        return "weekly_floor", f"not a {ctx['floor']} member — the weekly floor serves only its family here (#5759)"
    if is_novel(e, ctx["catalog"].get(ck or "")):
        from training import selection_cue_sheets  # #5861 L6: the form-guidance sheets + the selection's own

        if selection_cue_sheets.sheet_for(str(e.get("title") or "")) is None:
            return "not_prescribable", "new to him and no cue sheet exists for it"
    return None


def _candidate(lid: str, e: dict[str, Any], ck: str | None, ctx: dict[str, Any]) -> dict[str, Any]:
    novel = is_novel(e, ctx["catalog"].get(ck or ""))
    return {
        "movement_id": lid,
        "catalog_key": ck,
        "title": e.get("title"),
        "tier": tier_for(e, ctx["spec"]["muscle"]),
        "evidence": evidence_for(e, ctx["spec"]["muscle"]),
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
        c = live.decorate(_candidate(lid, e, ck, ctx), e, ctx) if ctx.get("policy") else _candidate(lid, e, ck, ctx)
        if c is None:  # #5861 L3, live only: not applicable to the slot's objective
            continue
        hit = _exclusion(lid, e, ck, ctx)
        if hit:
            excluded.append({**c, "code": hit[0], "why": hit[1], "gates": live.gates(lid, e, ctx) if hit[0] == "gate_locked" else []})
        else:
            eligible.append(c)
    return eligible, excluded


def pool_tiers(eligible: list[dict[str, Any]]) -> tuple[str, ...]:
    """The slot's top two NON-EMPTY quality bands among its eligible candidates (owner ruling 2026-11-12, board rec 2: S
    and A are both programmable — S is first among equals, not exclusive)."""
    present = sorted({c["tier"] for c in eligible}, key=lambda t: TIER_RANK[t])
    return tuple(present[:POOL_BANDS])


def rank_key(
    c: dict[str, Any], recent: set[str], slot_last: dict[str, int] | None = None, pool: tuple[str, ...] | None = None
) -> tuple[Any, ...]:
    """Quality tier, then N=1 fit, then variety (the slot's least-recently-served first, then not served by any slot in
    the lookback, familiar before new, more exposures), then evidence confidence as a tie-break, then the id
    (deterministic). No-repeats-per-week is not a rank term: it is a rule over the ranked list (`select_slot`).

    The slot term (#5857): once a quality band has several members, slots that share it (three curl slots, one curl band)
    each served one of them last phase, so the global term alone ranks them all alike and every slot holds its pick at
    the phase boundary; ranking by when THIS slot last served each one (`slot_last_served`) makes it rotate in the band."""
    ck = c.get("catalog_key") or ""
    ev = EVIDENCE_RANK.get(str(c.get("evidence")), len(EVIDENCE_RANK))
    last = (slot_last or {}).get(ck, -1)
    tier = TIER_RANK[c["tier"]]
    if pool is not None:  # the slot's pool (`pool_tiers`): N=1 fit, then slot variety, then tier as a tie-break
        inside = c["tier"] in pool
        return (
            0 if inside else 1,
            0 if inside else tier,
            -c["n1"]["score"],
            last,
            tier,
            ck in recent,
            c["novel"],
            -c["exposures"],
            ev,
            c["movement_id"],
        )
    return (tier, -c["n1"]["score"], last, ck in recent, c["novel"], -c["exposures"], ev, c["movement_id"])


def c_reason(
    pick: dict[str, Any],
    excluded: list[dict[str, Any]],
    *,
    pinned: bool = False,
    skipped: list[dict[str, Any]] | None = None,
    pooled: list[dict[str, Any]] | None = None,
) -> dict[str, str] | None:
    """The recorded reason a pick outside S∪A is served (None for an S or A pick; owner ruling 2026-11-12). The best
    higher-tier movement the slot could not serve names it — an exclusion, or a movement another slot already serves this
    week (`skipped`, `week_repeat`) — else a higher-tier member of the slot's own pool that ranked below it on N=1 fit or
    slot variety (`pool_fit`), else `library_gap`."""
    if pick["tier"] not in REASONED_TIERS:
        return None
    if pinned:
        return {"code": "owner_pin", "why": C_REASONS["owner_pin"]}
    blocked = list(excluded) + [c | {"code": "week_repeat", "why": "already fills another slot this program week"} for c in skipped or []]
    # at one tier, a movement this slot could serve but another slot took (`week_repeat`) names it before an exclusion
    above = sorted(
        (x for x in blocked if TIER_RANK[x["tier"]] < TIER_RANK[pick["tier"]]),
        key=lambda x: (TIER_RANK[x["tier"]], x["code"] != "week_repeat", x["movement_id"]),
    )
    if above:
        x = above[0]
        return {"code": x["code"], "why": f"{x['title']} (tier {x['tier']}): {x['why']}", "blocked": x["movement_id"]}
    higher = sorted(
        (c for c in pooled or [] if TIER_RANK[c["tier"]] < TIER_RANK[pick["tier"]]), key=lambda c: (TIER_RANK[c["tier"]], c["movement_id"])
    )
    if higher:
        x = higher[0]
        return {"code": "pool_fit", "why": f"{x['title']} (tier {x['tier']}): {C_REASONS['pool_fit']}", "blocked": x["movement_id"]}
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
    from training import layoff_tiers, selection_cue_sheets

    return {
        "caps": dict(layoff_tiers.EXPOSURE_CAPS),
        "ruling": layoff_tiers.OD1_RULING,
        "cue_sheet": selection_cue_sheets.sheet_for(str(pick["title"] or "")),
    }


def select_slot(slot: dict[str, Any], ctx: dict[str, Any], recent: set[str], week_taken: set[str]) -> dict[str, Any]:
    """One slot's selection: the ranked eligible candidates, the pick, its C-reason, its fallbacks, the exclusions."""
    if ctx.get("policy"):  # #5861 L3, LIVE only: hold while progressing, rotate for a named trigger, repeat when it helps
        return live.select_slot(slot, ctx, recent)
    eligible, excluded = candidates(ctx)
    mine = ctx.get("slot_last") or {}
    pool = pool_tiers(eligible)
    ranked = sorted(eligible, key=lambda c: rank_key(c, recent, mine, pool))
    # owner ruling 2026-11-11: best per slot, NO REPEATS PER WEEK — a movement another slot already serves this program week
    # is passed over and the next-best eligible candidate fills this slot (`week_repeat`); a repeat only when none is left
    open_ = [c for c in ranked if (c.get("catalog_key") or "") not in week_taken]
    chosen = open_[0] if open_ else (ranked[0] if ranked else None)
    skipped = ranked[: ranked.index(chosen)] if chosen else []
    above = [x for x in excluded if TIER_RANK[x["tier"]] < TIER_RANK[chosen["tier"]]] if chosen else excluded
    base = {"slot_id": slot["slot_id"], "role": slot["role"], "incumbent": slot["incumbent"], "spec": ctx["spec"], "floor": ctx["floor"]}
    if chosen is None:
        return {
            **base,
            "pick": None,
            "reason": "no eligible library candidate — the template accessory serves",
            "ranked": [],
            "excluded": excluded,
        }
    pick = chosen
    budget = NOVELTY_PER_SLOT - int(pick["novel"])
    repeat = (
        {"code": "week_repeat", "why": C_REASONS["week_repeat"].split(" (")[0], "skipped": [c["movement_id"] for c in skipped]}
        if skipped
        else (
            {"code": "week_repeat_unavoidable", "why": "every eligible candidate already fills another slot this week"}
            if not open_
            else None
        )
    )
    return {
        **base,
        "pick": pick
        | {
            "c_reason": c_reason(pick, excluded, skipped=skipped, pooled=[c for c in eligible if c["tier"] in pool]),
            "novel_terms": _novel_terms(pick),
            "week_repeat": repeat,
        },
        "top_band": top_band(pick, open_ or ranked, pool),
        "fallbacks": fallbacks(pick, ranked, novel_budget=budget),
        "ranked": [c["movement_id"] for c in ranked],
        "above_pick": [{k: x[k] for k in ("movement_id", "title", "tier", "code", "why")} for x in above],
        "excluded": [{k: x[k] for k in ("movement_id", "title", "tier", "code", "why", "gates")} for x in excluded],
    }


def top_band(pick: dict[str, Any], servable: list[dict[str, Any]], pool: tuple[str, ...] = ()) -> dict[str, Any]:
    """The slot's programmable pool as the rotation commitment reads it (owner ruling B on #5856, amended 2026-11-12): the
    pool's tiers, its servable members, and its S∪A members (catalog keys, rank order) — a held pick is accepted only when
    it is the single servable member of S∪A."""
    tiers = tuple(pool) or (pick["tier"],)
    members = [str(c.get("catalog_key")) for c in servable if c["tier"] in tiers and c.get("catalog_key")]
    sa = [str(c.get("catalog_key")) for c in servable if c["tier"] in PROGRAMMABLE_TIERS and c.get("catalog_key")]
    return {"tier": pick["tier"], "tiers": list(tiers), "members": members, "sa_members": sa}


def _owner_pinned(slot: dict[str, Any], ctx: dict[str, Any], pin: dict[str, Any], recent: set[str], week_taken: set[str]) -> dict[str, Any]:
    """A slot the owner approved on the block design review (#5776): it serves the approved movement — the template
    accessory, or one of the slot's eligible candidates. An approved movement the slot can no longer serve (equipment,
    pain, a lock, the catalog) is REFUSED, never forced: the record says why and drafting keeps the pool's variant."""
    eligible, excluded = candidates(ctx)
    ranked = sorted(eligible, key=lambda c: rank_key(c, recent))
    ck = str(pin.get("catalog_key") or "")
    meta = {k: pin.get(k) for k in ("source", "approved_block")} | {"catalog_key": ck, "experiment": pin.get("experiment")}
    hit = next((c for c in ranked if c["catalog_key"] == ck), None)
    if hit is None and ck == slot["incumbent"]:
        lid = ctx["idx"]["to_lib"].get(ck)
        hit = _candidate(lid or ck, xl.movements(ctx["lib"]).get(lid or "") or {"title": ck}, ck, ctx)
    if hit is None:
        why = next((x["why"] for x in excluded if x.get("catalog_key") == ck), "not a candidate for this slot's muscle and job")
        return select_slot(slot, ctx, recent, week_taken) | {"owner_pin": meta | {"state": "refused", "why": why}}
    # an owner-approved pick is exempt from no-repeats, as a pin is (#5773 x #5776)
    pick = hit | {"c_reason": c_reason(hit, excluded, pinned=True), "novel_terms": _novel_terms(hit), "week_repeat": None}
    return {
        "slot_id": slot["slot_id"],
        "role": slot["role"],
        "incumbent": slot["incumbent"],
        "spec": ctx["spec"],
        "floor": ctx["floor"],
        "owner_pin": meta | {"state": "held"},
        "pick": pick,
        "fallbacks": fallbacks(pick, ranked, novel_budget=NOVELTY_PER_SLOT - int(pick["novel"])),
        "ranked": [c["movement_id"] for c in ranked],
        "above_pick": [],
        "excluded": [{k: x[k] for k in ("movement_id", "title", "tier", "code", "why", "gates")} for x in excluded],
    }


def _pinned(slot: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """An owner-pinned slot keeps its pin (`owner_pin`); it still carries its ranked fallbacks."""
    lid = ctx["idx"]["to_lib"].get(slot["incumbent"])
    e = xl.movements(ctx["lib"]).get(lid or "") or {"title": slot["incumbent"]}
    pick = _candidate(lid or slot["incumbent"], e, slot["incumbent"], ctx)
    pick |= {"c_reason": c_reason(pick, [], pinned=True), "novel_terms": None, "week_repeat": None}  # a pin is exempt from no-repeats
    eligible, _excluded = candidates(ctx)
    ranked = sorted(eligible, key=lambda c: rank_key(c, set()))
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
def slot_last_served(rows: list[dict[str, Any]] | None, position: dict[str, Any] | None, slot_id: str) -> dict[str, int]:
    """Catalog key -> when THIS slot last served it in the lookback, as a phase ordinal (higher = more recent); the
    current phase's own row is never counted (that is this draft's held pick)."""
    out: dict[str, int] = {}
    for r in rows or []:
        if not str(r.get("sk") or "").endswith(f"#{slot_id}"):
            continue
        blk = int(r.get("block") or str(r.get("sk") or "ROTATION#B000#").split("#")[1][1:] or 0)
        for k, v in r.items():
            if not (k.startswith("phase_") and isinstance(v, dict) and v.get("variant")):
                continue
            if position and blk == position.get("block") and k == f"phase_{position.get('phase')}":
                continue
            ordinal = blk * 100 + int(k.split("_", 1)[1] or 0)
            out[str(v["variant"])] = max(out.get(str(v["variant"]), -1), ordinal)
    return out


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


def _pool_ranked(eligible: list[dict[str, Any]], recent: set[str], slot_last: dict[str, int]) -> list[dict[str, Any]]:
    pool = pool_tiers(eligible)
    return sorted(eligible, key=lambda c: rank_key(c, recent, slot_last, pool))


def _lengthened_pass(picked: list[dict[str, Any]], full: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Each muscle >= 1 lengthened-bias movement per week — inside the pick's tier and N=1 score only."""
    rows = []
    for muscle in sorted({p["spec"]["muscle"] for p in picked if p.get("spec") and p.get("pick")}):
        group = [
            p
            for p in picked
            if p.get("spec", {}).get("muscle") == muscle
            and p.get("pick")
            and not p.get("pinned")
            and not p.get("owner_pin")
            and not live.held(p)
        ]
        if any(p["pick"]["length_bias"] == "lengthened" for p in group):
            rows.append({"muscle": muscle, "state": "met"})
            continue
        swapped = None
        for p in group:
            others = {(q.get("pick") or {}).get("catalog_key") for q in picked if q is not p}  # never a week repeat
            alt = next(
                (
                    c
                    for c in full[p["slot_id"]]
                    if c["length_bias"] == "lengthened"
                    and c["tier"] == p["pick"]["tier"]
                    and c["n1"]["score"] == p["pick"]["n1"]["score"]
                    and c.get("catalog_key") not in others
                ),
                None,
            )
            if alt:
                p["pick"] = alt | {
                    "c_reason": p["pick"]["c_reason"],
                    "novel_terms": _novel_terms(alt),
                    "week_repeat": p["pick"].get("week_repeat"),
                    **{k: p["pick"][k] for k in ("rotation", "repeat") if k in p["pick"]},  # #5861 L3: a live pick only
                }
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
            k: pick[k]
            for k in (
                "movement_id",
                "catalog_key",
                "title",
                "tier",
                "evidence",
                "n1",
                "length_bias",
                "novel",
                "c_reason",
                "novel_terms",
                "week_repeat",
            )
            + tuple(k for k in live.LIVE_PICK_KEYS if k in pick)  # #5861 L3: present on a LIVE pick only
        }
    locked = sorted(
        (x for x in p.get("excluded") or [] if x.get("code") == "gate_locked"), key=lambda x: (TIER_RANK[x["tier"]], x["movement_id"])
    )
    return out | {
        "muscle": (p.get("spec") or {}).get("muscle"),
        "ranked_top": (p.get("ranked") or [])[:5],
        "locked_next": [{k: x.get(k) for k in ("movement_id", "title", "tier", "gates")} for x in locked],  # #5776: what unlocks next
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
    owner_pins: dict[str, dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Every accessory slot of the week ranked from the library. Pure (the caller loads library, overlay and ledger).
    `owner_pins` {slot_id: {catalog_key, source, approved_block, experiment}} are the block design review's approved
    picks (#5776, `block_design_review.resolve`): each such slot serves its approved movement (`_owner_pinned`)."""
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
        ctx = _ctx(slot, env, step) | {"slot_last": slot_last_served(rows, position, slot["slot_id"])}
        ctx |= {"policy": policy, "slot_id": slot["slot_id"]} if policy is not None else {}  # #5861 L3: `selection_live.build_policy`
        if slot["pinned"]:
            p = _pinned(slot, ctx) | {"spec": ctx["spec"]}
        elif (owner_pins or {}).get(slot["slot_id"]):
            p = _owner_pinned(slot, ctx, (owner_pins or {})[slot["slot_id"]], recent, taken)
            full[slot["slot_id"]] = _pool_ranked(candidates(ctx)[0], recent, ctx["slot_last"])
        else:
            p = select_slot(slot, ctx, recent, taken)
            full[slot["slot_id"]] = _pool_ranked(candidates(ctx)[0], recent, ctx["slot_last"])
        if p.get("pick") and p["pick"].get("catalog_key"):
            taken.add(p["pick"]["catalog_key"])
            live.count_pick(p, policy, ctx)  # #5861 L3: live only (no policy = no-op)
        picked.append(p)
    live.enforce_novelty(picked, policy, catalog)  # #5861 second red team: the budget covers every served change (live only; None = no-op)
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
    } | (live.summary(policy) if policy is not None else {})


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
    approval = sel.get("approval")
    gated = isinstance(approval, dict)  # #5776: an approval READ means drafting serves only owner-approved picks
    if isinstance(approval, dict) and approval.get("state") not in APPROVAL_SERVES:
        return rotation | {
            "selection_note": f"no owner-approved block proposal ({approval.get('note') or approval.get('state')}) — the #5075 pools serve"
        }
    by_slot = {s["slot_id"]: s for s in sel["slots"]}
    by_role = {r: dict(v) for r, v in (rotation.get("variants_by_role") or {}).items()}
    slots, writes = [], []
    for s in rotation.get("slots") or []:
        chosen = by_slot.get(s["slot_id"]) or {}
        pick = (chosen.get("pick") or {}).get("catalog_key")
        op = chosen.get("owner_pin") or {}
        if s.get("source") == "pinned" or not pick:
            slots.append(s)
            continue
        if gated and op.get("state") != "held":
            why = op.get("why") or "the approved proposal holds no pick for this slot"
            slots.append(s | {"approval_note": f"not served from the approval: {why} — the pool's variant serves"})
            continue
        held = vr._ledger_variant(rows, pos["block"], s["slot_id"], pos["phase"])
        fb = [f.get("catalog_key") for f in chosen.get("fallbacks") or []]
        eligible = {pick} if op.get("state") == "held" else {pick} | set(fb)  # an approved pick is served as approved
        # #5861 second red team: a ledger change past the week's novelty budget waits — the pick (the held movement) serves
        variant = chosen.get("novelty_serve") or (held if held and held in eligible else pick)
        by_role.setdefault(s["role"], {})[s["incumbent"]] = variant
        pool = [k for k in [pick] + fb if k]
        source = "ledger" if variant == held else ("owner_approved" if op.get("state") == "held" else "selection")
        extra = {"experiment": op["experiment"]} if op.get("experiment") else {}
        if chosen.get("top_band") and variant == pick:
            extra["top_band"] = chosen["top_band"]  # ruling B (#5856): the rotation commitment reads the band's size
        extra |= live.decision(chosen) if variant == pick else {}  # #5861 L3: a live hold/rotation with its named trigger
        slots.append(s | {"variant": variant, "source": source, "pool": pool} | extra)
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
    why = f" — {p.get('tier')} because {p['c_reason']['code']}: {p['c_reason']['why']}" if p.get("c_reason") else ""
    op = s.get("owner_pin") or {}
    why += live.line_suffix(p)  # #5861 L3: a live pick's hold/rotation and repetition, "" otherwise
    if op.get("state") == "held":
        why += f" — owner-approved (block {op.get('approved_block')}, {op.get('source')})"
        if op.get("experiment"):
            why += f" — EXPERIMENT {op['experiment'].get('technique')} ({op['experiment'].get('experiment_id')}), this block only"
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
    approvals: dict[str, Any] | None = None,
    block_workouts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The rotation a draft serves, with the selection attached. `live` (an approved library) rewrites the served role's
    accessory variants; `shadow` leaves the #5075 pools serving and attaches the selection for comparison; `no_library`
    attaches the state. Never raises: a selection that fails is recorded as `failed` and the pools serve.

    `approvals` (#5776) is `block_design_review.resolve(...)` for the draft's block, or None when it was not read (an
    injected ledger, the plan view). Once read, LIVE drafting serves only owner-approved picks: this block's approval, else
    the prior block's (said so), else the pools; an approved slot serves its approved movement (`owner_pins`)."""
    lib = load_library_failsoft() if lib is ... else lib
    m = mode(lib)
    if m == MODE_NO_LIBRARY:
        return rotation | {"selection": {"issue": ISSUE, "mode": m, "library_version": None}}
    try:
        overlay = load_overlay_failsoft() if overlay is ... else overlay
        pins = (approvals or {}).get("pins") if (approvals or {}).get("state") in APPROVAL_SERVES else None
        pos = rotation.get("position")
        policy = live.for_apply(lib, pos, rows, block_workouts, target_date, approvals) if m == MODE_LIVE else None  # #5861
        sel = select_week(pos, catalog, lib, overlay, rows=rows, skill_ceiling=skill_ceiling, owner_pins=pins, policy=policy)
    except Exception as e:  # noqa: BLE001 — the selection never blocks a draft
        logger.warning(f"selection_engine: the selection failed ({type(e).__name__}: {e}) — the #5075 pools serve")
        return rotation | {"selection": {"issue": ISSUE, "mode": m, "state": "failed", "error": f"{type(e).__name__}: {e}"[:200]}}
    sel |= {"mode": m, "overlay": "read" if isinstance(overlay, dict) else "absent (N=1 fit unknown)", "compare": _compare(rotation, sel)}
    if approvals is not None:
        sel["approval"] = {k: approvals.get(k) for k in ("state", "block", "approved_block", "note")} | {
            "experiment": (approvals.get("experiment") or {}).get("experiment_id")
        }
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
