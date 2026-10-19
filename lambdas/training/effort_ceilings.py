"""effort_ceilings.py — the RPE ceilings by movement class (#5058, epic #5050).

ONE READER for `config/training_charter.json` `effort_ceilings`. The charter states the ruled
bands per MOVEMENT CLASS (`by_movement_class`: `compounds_rpe`, and `last_isolation_set_rpe` for
the last set of an isolation movement — owner rulings 2026-10-18 on #5058). There is one band set;
the charter names no experience tier and this module invents none. The ceiling a set is graded
against is the HIGH end of its class band (`effort_ceilings.ceiling_is`): the band is the
prescription, its top the ceiling. A set within `overage_tolerance_rpe` above the ceiling is not
a breach.

Every consumer reads through here — the generator's cues (`program_structure.EXPOSURES`), the
load ramp's slot ceiling (`load_ramp.slot_rpe_ceiling`), the progression rule
(`load_progression.effort_limits`), the adherence grader's program default
(`health.adherence_calc`) and the disruption minimum session — so a ruled band change moves all
of them at once and none of them carries a typed RPE number.

`read` is injectable (default `training_charter.charter_value`) so a caller that already
monkeypatches its own charter reader keeps doing so. Absence is absence (ADR-105): an
unreadable charter returns empty bands / None, never a default ceiling.
"""

from __future__ import annotations

from typing import Any, Callable

from training.training_charter import charter_value

COMPOUNDS = "compounds_rpe"
LAST_ISOLATION_SET = "last_isolation_set_rpe"
CLASS_KEYS = (COMPOUNDS, LAST_ISOLATION_SET)

Reader = Callable[..., Any]


def class_bands(read: Reader = charter_value) -> dict[str, list[Any]]:
    """{compounds_rpe, last_isolation_set_rpe} -> [lo, hi], read from `effort_ceilings.by_movement_class`.

    A class the charter does not name is absent from the result — never a typed default."""
    base = dict(read("effort_ceilings.by_movement_class", {}) or {})
    out: dict[str, list[Any]] = {}
    for key in CLASS_KEYS:
        band = base.get(key)
        if band:
            out[key] = [min(band), max(band)]  # the charter's own numbers (whole RPEs stay whole)
    return out


def ceiling(key: str, read: Reader = charter_value) -> float | None:
    """The ceiling for one class band: its HIGH end (`effort_ceilings.ceiling_is`)."""
    band = class_bands(read).get(key)
    return float(band[1]) if band else None


def tolerance_rpe(read: Reader = charter_value) -> float | None:
    """`effort_ceilings.overage_tolerance_rpe` — the overage that is NOT a breach."""
    tol = read("effort_ceilings.overage_tolerance_rpe")
    return float(tol) if tol is not None else None


def proposal_rule(read: Reader = charter_value) -> dict[str, Any]:
    """`effort_ceilings.ceiling_change_proposal` ({} when unreadable)."""
    return dict(read("effort_ceilings.ceiling_change_proposal", {}) or {})
