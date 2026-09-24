"""program_conflicts.py — where the v0.3 program disagrees with what is already stated (#3755, #4080).

Extracted from `program_structure.py` (which crossed the 1000-line module ceiling, #4080) as
one cohesive unit: the program's AUDIT against the owner's redlines and the movement
catalog, plus the owner ruling that settled one of those conflicts.

  - `ANCHOR_SKILL_CEILING_RULING` — the owner's 2026-09-23 option-B ruling (#4080): the four
    core anchor families are exempt from the interim `skill_ceiling`.
    `program_structure._resolve_movement` reads it at call time.
  - `conflicts()` — where v0.3 contradicts `owner_redlines`, computed, never asserted;
    `program_structure.summary()` carries it into every constraint block.
  - `catalog_gaps()` — anchor/accessory keys the movement catalog does not carry;
    `routine_generator` records it on every generation.

Dependency direction: `program_structure` imports this module at load; this module reads
`program_structure`'s tables lazily inside each function (call time), so there is no
import cycle and a test that patches `program_structure.ANCHORS` is seen here.
"""

from __future__ import annotations

from typing import Any, Iterable

# ── the anchor skill-ceiling exemption (owner ruling 2026-09-23, #4080) ──────
# The issue asked which way to resolve the barbell-anchors-vs-skill-ceiling conflict named
# below (`conflicts()`): exempt anchors, raise the ceiling, or keep the machine/DB fallback (leg press at
# 316 lb). The owner chose OPTION B — exempt the four core anchor pattern FAMILIES, not the
# ceiling itself. `skill_ceiling` (2) is UNCHANGED for accessories and every other pattern
# (overhead press, vertical pull); this is a narrow, named carve-out, not a raise, which is
# why it is its own dict next to `skill_ceiling` rather than a second copy of that key.
ANCHOR_SKILL_CEILING_RULING: dict[str, Any] = {
    "exempt_families": ("squat", "hinge", "bench", "row"),
    "effective_ceiling": 3,
    "provenance": "owner",
    "stated": "2026-09-23",
    "decision": "option B",
    "issue": "#4080",
    "note": (
        "Owner ruling 2026-09-23 ~05:45 PT (#4080, option B): the four core anchor pattern families — squat, hinge, bench, row — "
        "are EXEMPT from the interim `skill_ceiling` of 2 (config/training_week.json's note: 'until the Sports Medicine seat is "
        "fully staffed'). A tier-3 barbell member of one of these families is reachable by `_resolve_movement` once it exists in "
        "the catalog (since #4108/#4124: `squat_barbell`, `front_squat`, `deadlift_trap_bar` and `barbell_bench_press`; the row "
        "family has no tier-3 member). `effective_ceiling` (3) is the highest real skill_tier the catalog uses today, not an unlimited ceiling: a "
        "movement whose `skill_tier` is unset still falls back to `_resolve_movement`'s 99 sentinel and stays excluded. "
        "Accessories and every non-exempt pattern (overhead press, vertical pull) are UNCHANGED — `skill_ceiling` itself was not "
        "raised. The Minimum Viable Session floor (`full_body_session.full_body_routines`, skill_ceiling=1, anchors-only) opts "
        "OUT of this exemption deliberately: that ceiling is a separate design choice (the tired-day session stays machine/DB-only "
        "regardless of family), not an instance of the interim Sports-Medicine ceiling this ruling targets."
    ),
}


# ── the conflicts this program has not resolved ──────────────────────────────
# Named here rather than discovered later. `summary()` carries them into every constraint
# block, so a plan built on this program cannot be built on a silent override.
def conflicts() -> list[dict[str, Any]]:
    """Where v0.3 contradicts something already stated. Computed against owner_redlines."""
    from training import owner_redlines, program_structure

    lifting = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    lift_days = len(program_structure.lifting_days())
    required_days = len([k for k in program_structure.lifting_days() if not program_structure._SCHEDULE[k].get("optional")])
    out: list[dict[str, Any]] = []
    if lift_days > lifting["high"] or required_days < lifting["low"]:
        out.append(
            {
                "id": "lifting_frequency_vs_redline",
                "program_says": f"{required_days} required + {lift_days - required_days} optional lifting days/wk ({program_structure.SPLIT})",
                "redline_says": f"{lifting['low']}-{lifting['high']} lifting sessions/wk ({lifting['provenance']}, stated {lifting['stated']})",
                "resolved": False,
                "note": "The program's lifting days fall outside the redline's band. The engine must not pick a side silently.",
            }
        )
    tier3 = [k for k, v in program_structure.ANCHORS.items() if any(c == "barbell_bench_press" for c in v["catalog_keys"])]
    if tier3:
        exempt_families = set(ANCHOR_SKILL_CEILING_RULING["exempt_families"])
        still_blocked = sorted(k for k in tier3 if k not in exempt_families)
        resolved = not still_blocked
        entry: dict[str, Any] = {
            "id": "barbell_anchors_vs_skill_ceiling",
            "program_says": "the bench anchor names the barbell bench press among its members",
            "redline_says": "week grid skill_ceiling=2 excludes barbell tier-3 movements until the Sports Medicine seat is staffed",
            "resolved": resolved,
            "note": (
                (
                    "RESOLVED by owner ruling 2026-09-23 (#4080, option B): the bench anchor is one of the four core anchor "
                    "pattern families ANCHOR_SKILL_CEILING_RULING exempts from skill_ceiling, so `barbell_bench_press` "
                    "(skill_tier 3) is reachable by the generator today. Accessories and every non-exempt pattern still stay "
                    "capped at skill_ceiling=2; the ceiling itself was not raised."
                )
                if resolved
                else (
                    "The generator CANNOT select a tier-3 barbell movement for "
                    f"{', '.join(still_blocked)} while skill_ceiling is 2, so that family resolves to the "
                    "dumbbell/machine members of the pattern today. That is a real substitution and it is stated rather than "
                    "hidden. Raising the ceiling for a non-exempt family is a separate owner decision."
                )
            ),
        }
        if resolved:
            entry["resolved_on"] = ANCHOR_SKILL_CEILING_RULING["stated"]
            entry["resolution_source"] = (
                f"owner ruling recorded on {ANCHOR_SKILL_CEILING_RULING['issue']} ({ANCHOR_SKILL_CEILING_RULING['decision']})"
            )
        out.append(entry)
    return out


def catalog_gaps(catalog_movement_keys: Iterable[str]) -> dict[str, list[str]]:
    """Anchor/accessory keys named here that the movement catalog does not carry.

    Injected, not loaded: this module does no I/O (the catalog is a config the caller
    already read). A gap means the generator cannot select that movement — the program
    names a lift the engine has no way to prescribe.
    """
    from training import program_structure

    known = set(catalog_movement_keys)
    gaps: dict[str, list[str]] = {}
    for name, anchor in program_structure.ANCHORS.items():
        missing = [k for k in anchor["catalog_keys"] if k not in known]
        if missing:
            gaps[f"anchor:{name}"] = missing
    for day, pool in program_structure.ACCESSORY_POOL.items():
        missing = [k for k in pool if k not in known]
        if missing:
            gaps[f"accessory:{day}"] = missing
    return gaps
