"""effort_ceilings.py — the RPE ceilings by experience tier and movement class (#5058, epic #5050).

ONE READER for `config/training_charter.json` `effort_ceilings`. The charter states the bands
per MOVEMENT CLASS (`by_movement_class`: compounds, the last set of an isolation movement) and
the lifter's experience tier picks which bands are in force (`experience_tier.current`, then
`experience_tier.<tier>`: `compounds_rpe`, `last_isolation_set_rpe`, `back_off_rpe`). The
ceiling a set is graded against is the HIGH end of its class band (`experience_tier.ceiling_is`):
the band is the prescription, its top the ceiling. A set within `overage_tolerance_rpe` above
the ceiling is not a breach.

Every consumer reads through here — the generator's cues (`program_structure.EXPOSURES`), the
load ramp's slot ceiling (`load_ramp.slot_rpe_ceiling`), the progression rule
(`load_progression.effort_limits`), the adherence grader's program default
(`health.adherence_calc`) and the disruption minimum session — so a tier change moves all of
them at once and none of them carries a typed RPE number.

`read` is injectable (default `training_charter.charter_value`) so a caller that already
monkeypatches its own charter reader keeps doing so. Absence is absence (ADR-105): an
unreadable charter returns empty bands / None, never a default ceiling.
"""

from __future__ import annotations

from typing import Any, Callable

from training.training_charter import charter_value

COMPOUNDS = "compounds_rpe"
LAST_ISOLATION_SET = "last_isolation_set_rpe"
BACK_OFF = "back_off_rpe"
CLASS_KEYS = (COMPOUNDS, LAST_ISOLATION_SET, BACK_OFF)

Reader = Callable[..., Any]


def current_tier(read: Reader = charter_value) -> str | None:
    """The owner's experience tier (`effort_ceilings.experience_tier.current`), or None."""
    tier = read("effort_ceilings.experience_tier.current")
    return str(tier) if tier else None


def class_bands(read: Reader = charter_value) -> dict[str, list[Any]]:
    """{compounds_rpe, last_isolation_set_rpe, back_off_rpe} -> [lo, hi] for the CURRENT tier.

    A class the tier does not name falls back to `by_movement_class` (the charter's stated class
    bands); a class neither names is absent from the result — never a typed default."""
    base = dict(read("effort_ceilings.by_movement_class", {}) or {})
    tier = current_tier(read)
    tiered = dict(read(f"effort_ceilings.experience_tier.{tier}", {}) or {}) if tier else {}
    out: dict[str, list[float]] = {}
    for key in CLASS_KEYS:
        band = tiered.get(key) if tiered.get(key) else base.get(key)
        if band:
            out[key] = [min(band), max(band)]  # the charter's own numbers (whole RPEs stay whole)
    return out


def ceiling(key: str, read: Reader = charter_value) -> float | None:
    """The ceiling for one class band: its HIGH end (`experience_tier.ceiling_is`)."""
    band = class_bands(read).get(key)
    return float(band[1]) if band else None


def tolerance_rpe(read: Reader = charter_value) -> float | None:
    """`effort_ceilings.overage_tolerance_rpe` — the overage that is NOT a breach."""
    tol = read("effort_ceilings.overage_tolerance_rpe")
    return float(tol) if tol is not None else None


def band_text(key: str, read: Reader = charter_value) -> str | None:
    """'8–9' for a class band (whole numbers print whole), or None when the charter names none."""
    band = class_bands(read).get(key)
    return f"{band[0]:g}–{band[1]:g}" if band else None


def proposal_rule(read: Reader = charter_value) -> dict[str, Any]:
    """`effort_ceilings.ceiling_change_proposal` ({} when unreadable)."""
    return dict(read("effort_ceilings.ceiling_change_proposal", {}) or {})


def summary(read: Reader = charter_value) -> dict[str, Any]:
    """The tier, its bands, the ceilings and the tolerance as read — the plan's stamp."""
    bands = class_bands(read)
    return {
        "experience_tier": current_tier(read),
        "bands": bands,
        "ceilings": {k: v[1] for k, v in bands.items()},
        "tolerance_rpe": tolerance_rpe(read),
        "source": "effort_ceilings.experience_tier (#5058)",
    }
