"""ceiling_proposal.py — a ceiling he beats on most sets two weeks running proposes its own change (#5058).

The charter's `effort_ceilings.ceiling_change_proposal` (`share_of_sets`, `weeks_running`): when
the sets logged ABOVE their prescribed ceiling are more than `share_of_sets` of the graded sets in
each of the last `weeks_running` weeks, the plan carries a PROPOSAL to change that class's
ceiling. An owner ruling applies it — this module never writes, never edits the charter and never
changes a prescription (`auto_applied` is always False).

WHAT IT READS. The stored `adherence` block on each Hevy row (`adherence_calc.calculate_adherence`,
the one grader), per movement:

  * graded sets = `sets_graded` − `sets_progressed` (a self-raised load is progress, #5052 — it
    beat the LOAD, not the ceiling, and is never in a share);
  * beat sets   = `sets_beat_ceiling` (every set above its ceiling, tolerance or not — #5058) or,
    on a row graded before #5058, `sets_over_ceiling` (that grader was strict, so its "over"
    IS "beat").

Grouped by movement class — the stored `movement_class` (#5058) or, on an older row, the
catalog's (`classify`): compound vs isolation, the two bands the charter states. A movement that
cannot be classed is counted under `unclassified` and never proposes.

WEEKS are trailing 7-day windows ending on `date` (week 1 = the 7 days through `date`, week 2
the 7 before it). A week with no graded set is `insufficient`, never a share of zero: absence is
not compliance (ADR-104), and two weeks running means two weeks MEASURED.

Pure: the rows and the catalog are the caller's; the only read is the charter.
"""

from __future__ import annotations

from typing import Any, Callable

from common.pacific_time import shift_day_key

from training import effort_ceilings
from training.training_charter import charter_value, charter_version

COMPOUND = "compound"
ISOLATION = "isolation"
UNCLASSIFIED = "unclassified"
CLASSES = (COMPOUND, ISOLATION)
_BAND_FOR = {COMPOUND: effort_ceilings.COMPOUNDS, ISOLATION: effort_ceilings.LAST_ISOLATION_SET}

APPLIES = "an owner ruling applies it — the platform proposes, never changes a ceiling itself"


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _catalog_entry(movement_key: str, catalog_movements: dict[str, Any] | None) -> dict[str, Any]:
    """By key, or for the ADR-069 `tmpl:<id>` form by the entry whose hint IS that id (adherence_calc's rule)."""
    movements = catalog_movements or {}
    entry = movements.get(movement_key)
    if entry or not str(movement_key or "").startswith("tmpl:"):
        return entry or {}
    tid = str(movement_key)[len("tmpl:") :].upper()
    return next((e for e in movements.values() if str(e.get("hevy_template_id_hint") or "").upper() == tid), {})


def classify(movement_key: str, catalog_movements: dict[str, Any] | None) -> str:
    """compound | isolation | unclassified — a catalog `anchor_family` (or an anchor title) is a compound."""
    from training.program_structure import classify_movement

    entry = _catalog_entry(movement_key, catalog_movements)
    if not entry:
        return UNCLASSIFIED
    if entry.get("anchor_family") or classify_movement(str(entry.get("title") or "")).startswith("anchor:"):
        return COMPOUND
    return UNCLASSIFIED if classify_movement(str(entry.get("title") or "")) == "cardio" else ISOLATION


def _week_of(day: str, date: str, weeks: int) -> int | None:
    """1-based trailing week index for `day` (1 = the 7 days through `date`), or None outside the window."""
    for i in range(1, weeks + 1):
        if shift_day_key(date, -7 * i + 1) <= day <= shift_day_key(date, -7 * (i - 1)):
            return i
    return None


def _movement_counts(m: dict[str, Any]) -> tuple[float, float] | None:
    """(graded, beat) for one stored movement, or None when it was not graded against a ceiling."""
    g = m.get("intensity") or {}
    if g.get("status") != "graded" or g.get("ceiling_rpe") in (None, ""):
        return None
    graded = _num(g.get("sets_graded")) - _num(g.get("sets_progressed"))
    beat = _num(g["sets_beat_ceiling"]) if g.get("sets_beat_ceiling") not in (None, "") else _num(g.get("sets_over_ceiling"))
    return (graded, beat) if graded > 0 else None


def compute(
    rows: list[dict[str, Any]] | None,
    date: str,
    *,
    catalog_movements: dict[str, Any] | None = None,
    read: Callable[..., Any] = charter_value,
) -> dict[str, Any]:
    """The ceiling-change proposal for the plan dated `date` (see the module docstring)."""
    rule = effort_ceilings.proposal_rule(read)
    share, weeks = rule.get("share_of_sets"), rule.get("weeks_running")
    out: dict[str, Any] = {
        "date": date,
        "state": "insufficient",
        "rule": rule,
        "by_class": {},
        "proposals": [],
        "auto_applied": False,
        "applies": APPLIES,
        "charter_version": charter_version(),
    }
    if share is None or not weeks:
        out["reason"] = "the charter states no ceiling_change_proposal rule"
        return out
    weeks = int(weeks)
    tally: dict[str, dict[int, list[float]]] = {}
    for row in rows or []:
        adh = row.get("adherence") if isinstance(row.get("adherence"), dict) else None
        week = _week_of(str(row.get("date") or "")[:10], date, weeks)
        if row.get("tombstone") or adh is None or adh.get("status") != "matched" or week is None:
            continue
        for m in adh.get("movements") or []:
            counts = _movement_counts(m)
            if counts is None:
                continue
            cls = (m.get("intensity") or {}).get("movement_class") or classify(str(m.get("movement_key") or ""), catalog_movements)
            cell = tally.setdefault(cls, {}).setdefault(week, [0.0, 0.0])
            cell[0] += counts[0]
            cell[1] += counts[1]
    measured_any = False
    for cls in (*CLASSES, UNCLASSIFIED):
        by_week = tally.get(cls) or {}
        rows_out = []
        for i in range(1, weeks + 1):
            graded, beat = by_week.get(i, [0.0, 0.0])
            rows_out.append(
                {
                    "week": i,
                    "start": shift_day_key(date, -7 * i + 1),
                    "end": shift_day_key(date, -7 * (i - 1)),
                    "sets_graded": int(graded),
                    "sets_beat_ceiling": int(beat),
                    "share": round(beat / graded, 3) if graded else None,
                }
            )
        measured = all(r["share"] is not None for r in rows_out)
        measured_any = measured_any or measured
        proposed = cls in CLASSES and measured and all(r["share"] > float(share) for r in rows_out)
        band = effort_ceilings.class_bands(read).get(_BAND_FOR.get(cls, ""))
        entry = {"weeks": rows_out, "measured": measured, "proposed": proposed, "charter_band": band}
        out["by_class"][cls] = entry
        if proposed:
            shares = " and ".join(f"{r['share']:.0%}" for r in reversed(rows_out))
            out["proposals"].append(
                {
                    "movement_class": cls,
                    "charter_band": band,
                    "experience_tier": effort_ceilings.current_tier(read),
                    "text": (
                        f"{cls} sets beat their RPE ceiling on {shares} of graded sets, {weeks} weeks running "
                        f"(charter: more than {float(share):.0%}). Proposal: rule on the {cls} band "
                        f"(now RPE {band[0]:g}-{band[1]:g}) — raise it, or keep it and cue it. Nothing changes until you rule."
                        if band
                        else f"{cls} sets beat their RPE ceiling on {shares} of graded sets, {weeks} weeks running. Rule on the band."
                    ),
                }
            )
    out["state"] = "proposed" if out["proposals"] else ("none" if measured_any else "insufficient")
    if out["state"] == "insufficient":
        out["reason"] = f"no movement class has graded sets in each of the last {weeks} weeks"
    return out


def for_plan(
    date: str, rows: list[dict[str, Any]] | None, read_state: str | None, catalog_movements: dict[str, Any] | None
) -> dict[str, Any]:
    """`plan_engine.constraint_block['ceiling_change_proposal']`: `compute`, or `unknown` when the window was not read
    (`read_state` None = a failed read) — never "no proposal" from a read that did not happen (#4072)."""
    if rows is None or read_state is None:
        return {
            "date": date,
            "state": "unknown",
            "reason": f"the prescription window was not read ({read_state or 'read_failed'})",
            "proposals": [],
            "auto_applied": False,
            "applies": APPLIES,
            "charter_version": charter_version(),
        }
    return compute(rows, date, catalog_movements=catalog_movements)
