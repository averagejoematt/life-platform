"""variant_rotation.py — variant slots and the rotation ledger: anchors fixed per block, accessory slots rotate (#5075).

WHY THIS EXISTS

The 2026-10-18 elite-panel training review counted 31 distinct lifts in 43 days against 534 in the owner's
2021-25 history: every accessory was frozen for the block, so the same seven movements served every upper day
(epic #5050, A4). The charter already carried the cadence (`rotation.anchors_fixed_weeks`,
`rotation.accessory_slots_rotate_every_weeks`) and a named pool (`rotation.pool`); nothing read them. This module
is that reader: a SLOT is one template accessory of one role (`upper_heavy.db_curl`), and each slot serves one
VARIANT per rotation phase, drawn from a vetted pool.

THE RULE, AS ARITHMETIC (every cadence number from the charter)

    block_weeks      = charter `rotation.anchors_fixed_weeks`                (block_model.block_weeks)
    every            = charter `rotation.accessory_slots_rotate_every_weeks`
    week_in_block    = (program_week - 1) % block_weeks + 1                  (session_sequence.ledger's week)
    phase            = (week_in_block - 1) // every + 1                      (2 phases in a 6-week block: weeks 1-3, 4-6)
    s                = (block - 1) x phases_per_block + (phase - 1)           (the slot's rotation step, 0-based)
    variant          = pool[0]                     when s == 0  (block 1's first phase is the template as written)
                     = pool[(s + offset % (n - 1)) % n]  otherwise, n = len(pool) >= 2 (a slot changes at EVERY phase)
    offset           = how many earlier roles in the charter's order carry the same template accessory, so the three
                       curl slots of a week do not all serve the same curl

ANCHORS ARE FIXED PER BLOCK. No anchor pattern is a slot: the anchors keep `program_structure`'s resolution and the
in-block variant rule (`in_block_variant`, #4409) for the whole block — the strength tripwire and the double
progression need the same bar back under him. The owner's two 2026-10-24 pins are never rotated: upper_volume's
bench slot is the incline dumbbell press (ruling B2, an anchor_keys pin) and shoulders_arms' farmer's carry
(ruling B3) is `PINNED_SLOTS`.

THE POOL IS SEEDED FROM HIS HEVY HISTORY. `VETTED_POOLS` names, per template accessory, the candidates a coach
would accept as the same job (isolation for isolation, the same muscle). A candidate enters the slot's pool only
when ALL of these hold, and every refusal is reported with its reason (`seed_pool(...)["excluded"]`):

  * it is in the movement catalog and he has LOGGED it (`sessions` > 0 — the catalog is generated from his whole
    Hevy history by deploy/build_movement_catalog.py, #4108, so this is "templates he has logged ∩ the catalog");
  * the generator may prescribe it (`movement_catalog.generator_eligible` at the week grid's skill ceiling) and it is
    a loaded rep-based template (`hevy_type` weight_reps, or a hand-curated entry with none);
  * its VOLUME SIGNATURE equals the slot's own: the same catalog `primary_muscle` and the same membership in every
    movement-counted set (`volume_floors.MOVEMENT_COUNTED`, `CARRY_MOVEMENTS`). That is what holds the weekly set
    count (75) AND every charter floor and band unchanged under every rotation — a swap that moved a set from one
    count to another is refused, never silently taken (the charter's Pallof press is the specimen: the catalog files
    `cable_pallof_press` under shoulders, so trading it for the crunch would move four sets off the core count);
  * nothing on the charter's owner-editable `equipment.not_available` list names it (key, equipment or title).

THE LEDGER (`USER#matthew#SOURCE#training_constraints` / `ROTATION#B<nnn>#<role>.<accessory>`, docs/SCHEMA.md). One
row per block and slot; each phase is one top-level attribute (`phase_1`, `phase_2`) holding the variant, the weeks it
serves, the target date of the draft that first recorded it and the pool it was drawn from. The write is
`if_not_exists` per phase, so the FIRST draft of a phase decides it and every re-draft reads it back — a catalog
regenerated or a `not_available` edit mid-phase never swaps a movement under him. A ledger variant that has since left
the pool is reported and recomputed for this draft; the row keeps what was served. Written through
`routine_repo.draft_versioned` (the one persist step every drafting path takes), read here fail-soft.

PROVENANCE (ADR-105): the cadence and the pool's family names are the owner's (charter, rulings 2026-10-18); the
per-slot candidate lists, the offset and the s == 0 rule are platform-proposed under that ruling.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

ISSUE = "#5075"
LEDGER_SOURCE = "training_constraints"
LEDGER_PK = f"USER#matthew#SOURCE#{LEDGER_SOURCE}"
LEDGER_SK_PREFIX = "ROTATION#"
LEDGER_STORE = f"{LEDGER_PK} / {LEDGER_SK_PREFIX}B<nnn>#<role>.<accessory> — CROSS_PHASE (ADR-077), Tier 2 owner-only"
PROVENANCE = "cadence + family names: owner (charter `rotation`, 2026-10-18); slot candidate lists: platform-proposed (#5075)"
LOADED_HEVY_TYPES = (None, "weight_reps")

PINNED_SLOTS: dict[str, str] = {
    "shoulders_arms.farmers_walk": "owner ruling B3, 2026-10-24 (#5318): the farmer's carry replaced the shrug — never rotated",
}
"""Accessory slots the owner pinned: they serve their template movement in every phase and are never written to the ledger."""

PINNED_ANCHORS: dict[str, str] = {
    "upper_volume.bench": "owner ruling B2, 2026-10-24 (#5318): the incline dumbbell press (`anchor_keys`) — anchors never rotate",
}
"""Anchor pins, for the record: no anchor is a slot, so these hold by construction (held by a test, never by a branch here)."""

VETTED_POOLS: dict[str, dict[str, Any]] = {
    "db_lateral_raise": {"family": "side_delt", "charter_family": "delts", "candidates": ["lateral_raise_machine"]},
    "face_pull": {
        "family": "rear_delt",
        "charter_family": "delts",
        "candidates": ["reverse_pec_deck", "db_rear_delt_rows", "chest_supported_reverse_fly_dumbbell"],
    },
    "reverse_pec_deck": {
        "family": "rear_delt",
        "charter_family": "delts",
        "candidates": ["face_pull", "chest_supported_reverse_fly_dumbbell", "db_rear_delt_rows"],
    },
    "db_curl": {
        "family": "biceps",
        "charter_family": None,
        "candidates": [
            "hammer_curl_dumbbell",
            "seated_incline_curl_dumbbell",
            "preacher_curl_machine",
            "spider_curl",
            "bicep_curl_cable",
            "bicep_curl_machine",
        ],
    },
    "cable_tricep_pushdown": {
        "family": "triceps",
        "charter_family": None,
        "candidates": ["triceps_extension_cable", "triceps_rope_pushdown", "lying_db_tricep_extension", "triceps_kickback_dumbbell"],
    },
    "cable_chest_fly": {
        "family": "chest_fly",
        "charter_family": None,
        "candidates": ["chest_fly_machine", "butterfly_pec_deck", "chest_fly_dumbbell"],
    },
    "leg_press": {
        "family": "quad_accessory",
        "charter_family": "single_leg_progression",
        "candidates": ["bulgarian_split_squat_dumbbell", "leg_extension_machine", "leg_press_horizontal_machine"],
    },
    "leg_curl": {"family": "hamstring_curl", "charter_family": None, "candidates": ["lying_leg_curl_machine"]},
    "calf_raise_machine": {"family": "calves", "charter_family": None, "candidates": ["standing_calf_raise_machine", "seated_calf_raise"]},
    "machine_crunch": {
        "family": "core",
        "charter_family": "core",
        "candidates": ["cable_pallof_press", "side_bend_dumbbell", "torso_rotation", "cable_twist_up_to_down"],
    },
}
"""Per template accessory: its family, the charter `rotation.pool` family it answers (None = no charter family names it)
and the vetted candidates, most-logged first. The incumbent is always the pool's first member. A candidate listed here is
still refused by `seed_pool` unless he has logged it and it keeps the slot's volume signature."""

CHARTER_FAMILY_DISPOSITION: dict[str, str] = {
    "traps": "pinned — the trap slot is shoulders_arms' farmer's carry (owner ruling B3, 2026-10-24); the barbell shrug is not served",
    "second_press": "anchor — the bench pattern, fixed per block; upper_volume's slot is pinned to the incline DB press (ruling B2)",
    "rows": "anchor — the row pattern, fixed per block (in-block variant rule, #4409)",
    "vertical_pull": "anchor — the vertical-pull pattern, fixed per block",
    "hinge": "anchor — the hinge pattern, fixed per block (the RDL as the moderate hinge; the conventional pull stays gated)",
    "single_leg_progression": "slot — lower_heavy.leg_press rotates through the Bulgarian split squat (the logged step of the progression)",
    "carries": "pinned — the farmer's carry (ruling B3); the suitcase carry is not in his logged history",
    "delts": "slot — every lateral-raise, face-pull and reverse-pec-deck slot",
    "core": "slot — lower_volume.machine_crunch; the Pallof press is refused by the volume rule (the catalog files it under shoulders)",
}
"""Where each charter `rotation.pool` family lands — a test holds these keys equal to the charter's, so a family the
charter adds is never silently ignored."""


# ── the cadence (charter) ────────────────────────────────────────────────────
def rotate_every_weeks() -> int:
    """The charter's `rotation.accessory_slots_rotate_every_weeks`. Raises when the charter cannot say."""
    from training.training_charter import charter_value

    n = charter_value("rotation.accessory_slots_rotate_every_weeks")
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"variant_rotation: charter rotation.accessory_slots_rotate_every_weeks is {n!r}")
    return n


def phases_per_block() -> int:
    from training.block_model import block_weeks

    return -(-block_weeks() // rotate_every_weeks())


def phase_weeks(phase: int) -> list[int]:
    """The weeks of the block (1-based, inclusive) one phase serves."""
    from training.block_model import block_weeks

    every = rotate_every_weeks()
    return [(phase - 1) * every + 1, min(phase * every, block_weeks())]


def position(day_entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """The rotation position of a served session (`session_sequence.next_session`'s week and block), or None when the
    program week is unknown (before the block start, an unread Hevy record)."""
    from training.block_model import block_weeks

    week, block = (day_entry or {}).get("week"), (day_entry or {}).get("block")
    if not isinstance(week, int) or not isinstance(block, int) or week < 1 or block < 1:
        return None
    week_in_block = (week - 1) % block_weeks() + 1
    phase = (week_in_block - 1) // rotate_every_weeks() + 1
    return {
        "block": block,
        "week": week,
        "week_in_block": week_in_block,
        "phase": phase,
        "phases_per_block": phases_per_block(),
        "phase_weeks": phase_weeks(phase),
        "step": (block - 1) * phases_per_block() + (phase - 1),
    }


# ── the slots and their pools ────────────────────────────────────────────────
def slots() -> list[dict[str, Any]]:
    """Every accessory slot of the week, in the charter's order: id, role, template accessory, offset, pin."""
    from training import program_structure

    seen: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for role in program_structure.SPLIT_ROLES:
        for acc in program_structure.SESSION_TEMPLATES[role]["accessories"]:
            sid = f"{role}.{acc}"
            out.append({"slot_id": sid, "role": role, "incumbent": acc, "offset": seen.get(acc, 0), "pinned": PINNED_SLOTS.get(sid)})
            seen[acc] = seen.get(acc, 0) + 1
    return out


def volume_signature(key: str, catalog_movements: dict[str, Any]) -> tuple[Any, ...]:
    """(catalog primary muscle, every movement-counted set the key is summed into) — two keys with one signature move
    every weekly count, floor and band identically (`program_structure.volume_floor_coverage`)."""
    from training import volume_floors

    counted = [name for name, members in volume_floors.MOVEMENT_COUNTED.items() if key in members]
    if key in volume_floors.CARRY_MOVEMENTS:
        counted.append("carry")
    return ((catalog_movements.get(key) or {}).get("primary_muscle"), tuple(sorted(counted)))


def not_available() -> list[str]:
    """The charter's owner-editable `equipment.not_available` list (owner ruling 2026-10-18 on #5075)."""
    from training.training_charter import charter_value

    return [str(x) for x in (charter_value("equipment.not_available") or []) if str(x).strip()]


def _unavailable(key: str, entry: dict[str, Any], missing: list[str]) -> str | None:
    hay = {key.lower(), str(entry.get("equipment") or "").lower()}
    title = str(entry.get("title") or "").lower()
    for item in missing:
        it = item.strip().lower()
        if it in hay or (it and it in title):
            return item
    return None


def _refusal(
    key: str, entry: dict[str, Any] | None, sig: tuple[Any, ...], catalog: dict[str, Any], ceiling: int, missing: list[str]
) -> str | None:
    from training import movement_catalog

    if entry is None:
        return "not in the movement catalog"
    if not int(entry.get("sessions") or 0):
        return "never logged in his Hevy history"
    if not movement_catalog.generator_eligible(entry, ceiling, key=key):
        return f"not generator-eligible at skill ceiling {ceiling}"
    if entry.get("hevy_type") not in LOADED_HEVY_TYPES:
        return f"not a loaded rep-based template (hevy_type {entry.get('hevy_type')})"
    if volume_signature(key, catalog) != sig:
        return f"volume signature {volume_signature(key, catalog)} != the slot's {sig} — the weekly counts would move"
    hit = _unavailable(key, entry, missing)
    return f"on the charter's equipment.not_available list ({hit!r})" if hit else None


def seed_pool(
    incumbent: str, catalog_movements: dict[str, Any], *, skill_ceiling: int = 2, missing: list[str] | None = None
) -> dict[str, Any]:
    """One slot's pool: the template accessory first, then every vetted candidate that passes the rules (module doc)."""
    spec = VETTED_POOLS.get(incumbent) or {"family": None, "charter_family": None, "candidates": []}
    missing = not_available() if missing is None else missing
    sig = volume_signature(incumbent, catalog_movements)
    pool: list[str] = []
    excluded: list[dict[str, str]] = []
    inc_entry = catalog_movements.get(incumbent) or {}
    inc_hit = _unavailable(incumbent, inc_entry, missing)
    if inc_hit:
        excluded.append({"key": incumbent, "reason": f"on the charter's equipment.not_available list ({inc_hit!r})"})
    else:
        pool.append(incumbent)
    for key in spec["candidates"]:
        why = _refusal(key, catalog_movements.get(key), sig, catalog_movements, skill_ceiling, missing)
        if why:
            excluded.append({"key": key, "reason": why})
        elif key not in pool:
            pool.append(key)
    if not pool:  # every member unavailable: the template serves, and says so
        pool = [incumbent]
    return {"family": spec["family"], "charter_family": spec["charter_family"], "pool": pool, "excluded": excluded}


def pick(pool: list[str], step: int, offset: int) -> str:
    """The variant a slot serves at rotation step `step`: the template at step 0, then `pool[(step + offset') % n]` with
    `offset' = offset % (n - 1)` — so step 1 never lands back on the template and every later step moves by one: a slot
    with two or more members changes at EVERY phase boundary (held by a test)."""
    if not pool:
        raise ValueError("variant_rotation.pick: an empty pool")
    n = len(pool)
    if step <= 0 or n == 1:
        return pool[0]
    return pool[(step + offset % (n - 1)) % n]


def resolve_slot(
    slot: str, variants: dict[str, str] | None, catalog_movements: dict[str, Any] | None, skill_ceiling: int, taken: set[str]
) -> tuple[str | None, str | None]:
    """(movement key, resolution note) for one accessory slot of `program_structure.session_prescription_for_role`: its
    rotation variant first, the template's own movement as the fallback. Without the catalog the key is prescribed
    unchecked, as an accessory always was."""
    from training import program_structure

    v = (variants or {}).get(slot, slot)
    if catalog_movements is None:
        return v, None
    return program_structure._resolve_movement(list(dict.fromkeys([v, slot])), catalog_movements, skill_ceiling, taken)


def _title(key: str | None, catalog: dict[str, Any]) -> str:
    return str((catalog.get(key or "") or {}).get("title") or key)


# ── the ledger ───────────────────────────────────────────────────────────────
def ledger_sk(block: int, slot_id: str) -> str:
    return f"{LEDGER_SK_PREFIX}B{int(block):03d}#{slot_id}"


def _ledger_variant(rows: list[dict[str, Any]] | None, block: int, slot_id: str, phase: int) -> str | None:
    for r in rows or []:
        if r.get("sk") == ledger_sk(block, slot_id):
            v = (r.get(f"phase_{phase}") or {}).get("variant")
            return str(v) if v else None
    return None


def load_rows(block: int, table: Any = None) -> list[dict[str, Any]]:
    """The ledger rows of `block` and the block before it (a block's first phase rotates FROM the previous block's last).
    Raises on a failed read."""
    from boto3.dynamodb.conditions import Key

    if table is None:
        from training import exercise_history

        table = exercise_history._table()
    lo = ledger_sk(max(1, int(block) - 1), "")
    hi = ledger_sk(int(block), "~")
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(LEDGER_PK) & Key("sk").between(lo, hi)}
    items: list[dict[str, Any]] = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def load_rows_failsoft(block: int, table: Any = None) -> tuple[list[dict[str, Any]] | None, str]:
    """(`load_rows`, "read") or (None, "read_failed: ...") — an unread ledger computes the rotation, never blocks a draft."""
    try:
        return load_rows(block, table), "read"
    except Exception as e:  # noqa: BLE001
        logger.warning(f"variant_rotation: the ledger read failed ({type(e).__name__}: {e}) — the rotation is computed")
        return None, f"read_failed: {type(e).__name__}"


def _to_ddb(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _to_ddb(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_to_ddb(x) for x in v]
    return v


def record(rotation: dict[str, Any] | None, table: Any, recorded_at: str) -> int:
    """Write every pending phase of a drafted session's rotation (`plan(...)["ledger_writes"]`), each `if_not_exists`
    so the first draft of a phase wins. Numbers go in as Decimal. Returns the number of rows written. Raises."""
    n = 0
    for w in (rotation or {}).get("ledger_writes") or []:
        phase_attr = f"phase_{int(w['phase'])}"
        table.update_item(
            Key={"pk": LEDGER_PK, "sk": ledger_sk(int(w["block"]), w["slot_id"])},
            UpdateExpression="SET #p = if_not_exists(#p, :p), #b = :b, #s = :s, #r = :r, #i = :i, #iss = :iss",
            ExpressionAttributeNames={"#p": phase_attr, "#b": "block", "#s": "slot_id", "#r": "role", "#i": "incumbent", "#iss": "issue"},
            ExpressionAttributeValues=_to_ddb(
                {
                    ":p": {
                        "variant": w["variant"],
                        "weeks": list(w["weeks"]),
                        "first_target_date": w.get("target_date"),
                        "pool": list(w["pool"]),
                        "recorded_at": recorded_at,
                        "charter_version": w.get("charter_version"),
                    },
                    ":b": int(w["block"]),
                    ":s": w["slot_id"],
                    ":r": w["role"],
                    ":i": w["incumbent"],
                    ":iss": ISSUE,
                }
            ),
        )
        n += 1
    return n


def record_failsoft(rotation: dict[str, Any] | None, table: Any, recorded_at: str) -> int | None:
    """`record`, or None when the write failed — logged; the draft already landed and the next draft re-offers the write."""
    if not (rotation or {}).get("ledger_writes"):
        return 0
    try:
        return record(rotation, table, recorded_at)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"variant_rotation: the ledger write failed ({type(e).__name__}: {e}) — the next draft re-offers it")
        return None


# ── the plan: which variant each slot serves ─────────────────────────────────
def _slot_plan(
    slot: dict[str, Any], pos: dict[str, Any], catalog: dict[str, Any], rows: list[dict[str, Any]] | None, ceiling: int, missing: list[str]
) -> dict[str, Any]:
    seeded = seed_pool(slot["incumbent"], catalog, skill_ceiling=ceiling, missing=missing)
    pool, step, block, phase = seeded["pool"], pos["step"], pos["block"], pos["phase"]
    base = {**slot, **seeded, "phase": phase, "weeks": pos["phase_weeks"], "block": block}
    if slot["pinned"]:
        return {**base, "variant": slot["incumbent"], "previous": slot["incumbent"], "source": "pinned", "note": None}
    computed = pick(pool, step, slot["offset"])
    prev_block, prev_phase = (block, phase - 1) if phase > 1 else (block - 1, pos["phases_per_block"])
    previous = (_ledger_variant(rows, prev_block, slot["slot_id"], prev_phase) if prev_block >= 1 else None) or (
        pick(pool, step - 1, slot["offset"]) if step > 0 else slot["incumbent"]
    )
    held = _ledger_variant(rows, block, slot["slot_id"], phase)
    if held and held in pool:
        return {**base, "variant": held, "previous": previous, "source": "ledger", "note": None}
    note = f"the ledger's {held} has left the pool — recomputed for this draft; the row keeps what was served" if held else None
    return {**base, "variant": computed, "previous": previous, "source": "computed", "note": note, "write": held is None}


def _line(s: dict[str, Any], pos: dict[str, Any], catalog: dict[str, Any]) -> str:
    where = (
        f"week {s['weeks'][0]} of block {s['block']} (serves weeks {s['weeks'][0]}–{s['weeks'][1]}; this is week {pos['week_in_block']})"
    )
    if s["source"] == "pinned":
        return f"pinned: {_title(s['variant'], catalog)} — {s['pinned']}"
    if pos["step"] == 0:
        return f"template: {_title(s['variant'], catalog)}, {where} — the first phase serves the template as written [{s['slot_id']}]"
    if s["variant"] == s["previous"]:
        why = "no other member of the vetted pool" if len(s["pool"]) < 2 else "the pool cycled back"
        return f"held: {_title(s['variant'], catalog)}, {where} — {why} [{s['slot_id']}, {s['source']}]"
    return f"rotated: {_title(s['previous'], catalog)} → {_title(s['variant'], catalog)}, {where} [{s['slot_id']}, {s['source']}]"


def plan(
    day_entry: dict[str, Any] | None,
    catalog_movements: dict[str, Any],
    *,
    role: str | None = None,
    rows: list[dict[str, Any]] | None = None,
    ledger_state: str = "not_read",
    skill_ceiling: int = 2,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    """The rotation for one served session (`role`, default the entry's) or, with `role="*"`, every slot of the week.

    `variants` maps a template accessory to the variant it serves for `role` — what
    `program_structure.session_prescription_for_role` takes as `accessory_variants` (`variants_by_role`: every role of the
    week at this position); `slots` carries each of `role`'s slots with its pool, refusals, source and previous variant;
    `rationale` the draft lines ("rotated: X → Y, week 4 of block 1 …"); `ledger_writes` the phases no ledger row holds yet.

    `volume_check` is the live invariant: the week with every role's variants applied against the template week — total
    sets, per-muscle counts, charter floors and bands (`week_volume`). A rotation that would move any of them is REFUSED
    (the template serves, the rationale says why, nothing is written) — the seeding rules make that unreachable, and this
    is the backstop that keeps it so. Pure."""
    from training.block_model import block_weeks
    from training.training_charter import charter_version

    role = role or (day_entry or {}).get("session_role")
    base: dict[str, Any] = {
        "issue": ISSUE,
        "provenance": PROVENANCE,
        "ledger": ledger_state,
        "variants": {},
        "slots": [],
        "ledger_writes": [],
    }
    pos = position(day_entry)
    if pos is None:
        return {**base, "position": None, "rationale": ["rotation: the program week is unknown — the template's accessories serve"]}
    base.update(position=pos, cadence={"anchors_fixed_weeks": block_weeks(), "accessory_slots_rotate_every_weeks": rotate_every_weeks()})
    missing = not_available() if missing is None else missing
    every = [_slot_plan(s, pos, catalog_movements, rows, skill_ceiling, missing) for s in slots()]
    by_role: dict[str, dict[str, str]] = {}
    for p in every:
        by_role.setdefault(p["role"], {})[p["incumbent"]] = p["variant"]
    check = volume_check(catalog_movements, by_role, skill_ceiling)
    planned = [p for p in every if role == "*" or p["role"] == role]
    if not check["unchanged"]:
        return {
            **base,
            "volume_check": check,
            "slots": planned,
            "rationale": [
                f"rotation REFUSED — it would move the week's counts ({', '.join(check['moved'])}); the template's accessories serve"
            ],
        }
    target = (day_entry or {}).get("date") or (day_entry or {}).get("target_date")
    writes = [
        {k: p[k] for k in ("block", "phase", "weeks", "slot_id", "role", "incumbent", "variant", "pool")}
        | {"target_date": target, "charter_version": charter_version()}
        for p in planned
        if p.get("write")
    ]
    base.update(
        variants=by_role.get(str(role), {}),
        variants_by_role=by_role,
        volume_check=check,
        slots=[{k: v for k, v in p.items() if k != "write"} for p in planned],
        ledger_writes=writes,
        rationale=[_line(p, pos, catalog_movements) for p in planned],
    )
    return base


def swaps(rotation: dict[str, Any] | None, catalog_movements: dict[str, Any] | None = None) -> dict[str, str]:
    """The served session's rotated accessories, for the Hevy note (#5083 / #5428): `{served movement key: the title of
    the exercise it replaces}` — exactly the slots the rationale names `rotated: X → Y`. A pinned slot, block 1's first
    phase (the template as written), a held variant (the pool cycled back or has one member) and a REFUSED rotation (the
    template serves) are not swaps. The slot id, the week arithmetic and the issue stay on the rationale and the stored
    `inputs_snapshot.rotation`; the note gets the one fact he needs at the rack."""
    rot = rotation or {}
    pos = rot.get("position") or {}
    served = rot.get("variants") or {}
    if not served or int(pos.get("step") or 0) <= 0:
        return {}
    catalog = catalog_movements or {}
    out: dict[str, str] = {}
    for s in rot.get("slots") or []:
        if s.get("source") == "pinned" or s.get("variant") == s.get("previous") or not s.get("previous"):
            continue
        if served.get(s.get("incumbent")) != s.get("variant"):
            continue
        out[str(s["variant"])] = _title(s["previous"], catalog)
    return out


def volume_check(catalog_movements: dict[str, Any], variants_by_role: dict[str, dict[str, str]], skill_ceiling: int = 2) -> dict[str, Any]:
    """The rotated week (`week_volume` with every role's variants) against the template week: `unchanged`, and what `moved`."""
    rotated = week_volume(catalog_movements, variants_by_role, skill_ceiling)
    template = week_volume(catalog_movements, {}, skill_ceiling)
    moved = [k for k in ("total_sets", "sets_by_muscle", "floors", "bands") if rotated[k] != template[k]]
    return {"unchanged": not moved, "moved": moved, "total_sets": rotated["total_sets"], "template_total_sets": template["total_sets"]}


def for_session(
    day_entry: dict[str, Any] | None,
    catalog_movements: dict[str, Any],
    *,
    rows: list[dict[str, Any]] | None = None,
    read: bool = True,
    skill_ceiling: int = 2,
) -> dict[str, Any]:
    """`plan` for the served session, with the ledger read here (fail-soft) unless `rows` is injected or `read` is False
    (the plan view: no hidden DDB read — `ledger: not_read`, the rotation computed)."""
    pos = position(day_entry)
    state = "injected" if rows is not None else "not_read"
    if rows is None and read and pos is not None:
        rows, state = load_rows_failsoft(pos["block"])
    return plan(day_entry, catalog_movements, rows=rows, ledger_state=state, skill_ceiling=skill_ceiling)


def week_volume(catalog_movements: dict[str, Any], variants_by_role: dict[str, dict[str, str]], skill_ceiling: int = 2) -> dict[str, Any]:
    """The week's total sets, per-muscle counts (movement-counted keys included), charter floors and bands with each
    role's `accessory_variants` applied — the same tallies `program_structure.volume_floor_coverage` reads."""
    from training import program_structure, volume_floors

    by_muscle: dict[str, int] = {}
    by_movement: dict[str, int] = {}
    total = 0
    for role in program_structure.SPLIT_ROLES:
        rx = program_structure.session_prescription_for_role(
            role, catalog_movements=catalog_movements, skill_ceiling=skill_ceiling, accessory_variants=variants_by_role.get(role)
        )
        total += int(rx["total_sets"])
        for e in rx["exposures"]:
            k = e.get("movement_key") or ""
            muscle = (catalog_movements.get(k) or {}).get("primary_muscle") or "unresolved"
            by_muscle[muscle] = by_muscle.get(muscle, 0) + len(e["sets"])
            by_movement[k] = by_movement.get(k, 0) + len(e["sets"])
    counts = volume_floors.movement_counts(by_muscle, by_movement)
    accs = {r: list(t["accessories"]) for r, t in program_structure.SESSION_TEMPLATES.items()}
    return {
        "total_sets": total,
        "sets_by_muscle": dict(sorted(counts.items())),
        "floors": volume_floors.floor_coverage(counts, accs),
        "bands": volume_floors.charter_band_rows(counts),
    }
