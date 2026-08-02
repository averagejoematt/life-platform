"""labs_facts.py — the labs coach's fact-block builder (#1993).

The old extractor in ai_expert_analyzer_lambda hunted top-level ``*_flag`` keys
with ``'H'``/``'L'`` values — a schema that has never existed. SCHEMA.md (the
authoritative field reference) says a labs draw record stores a nested
``biomarkers`` map plus an ``out_of_range`` key list with ``out_of_range_count``
and ``total_biomarkers``. Against every real draw the old hunt returned
``flagged=[] / flagged_count=0`` and Dr. Okafor narrated the empty extraction as
"zero results … a total sync failure" while /api/labs served 8 draws with 26
flagged biomarkers (ADR-104 breach — the ground itself was mis-extracted).

This module reads the real schema, and it keeps the ADR-104 distinction
STRUCTURAL rather than narrative:

- ``store_empty: True`` appears only when the DDB query itself returned zero
  draw records — the one case where "no labs exist" is honest.
- With draws present, ``flagged_count`` is the record's own declared
  ``out_of_range_count``; a shortfall between that declaration and what detail
  extraction could resolve is surfaced as ``extraction_incomplete`` — an
  extraction gap on real draws, never an empty store.
"""

from typing import Any, Dict, List, Optional


def _as_int(value: Any, default: int) -> int:
    """Coerce a DDB-sourced number (Decimal→float after _decimal_to_float, or a
    stringly value) to int; fall back to the computed default on junk."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _flag_label(raw_flag: Any) -> str:
    flag = str(raw_flag or "").strip().upper()
    return flag if flag else "OUT OF RANGE"


def _describe_marker(key: str, biomarker: Dict[str, Any]) -> str:
    label = key.replace("_", " ").title()
    value = biomarker.get("value")
    unit = str(biomarker.get("unit") or "").strip()
    ref = str(biomarker.get("ref_text") or "").strip()
    desc = f"{label}: {value}"
    if unit:
        desc += f" {unit}"
    desc += f" ({_flag_label(biomarker.get('flag'))}"
    if ref:
        desc += f"; ref {ref}"
    return desc + ")"


def build_labs_fact_block(lab_items: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Build the labs expert's fact block from real draw records (#1993).

    ``lab_items`` is the chronological list of DDB draw records (post
    ``_decimal_to_float``); the newest draw is last. Reads the real schema:
    ``biomarkers`` map + ``out_of_range`` list + ``out_of_range_count`` /
    ``total_biomarkers``.
    """
    if not lab_items:
        # The ONLY honest "zero results": the store itself returned no draws.
        return {
            "expert_key": "labs",
            "period": "all draws",
            "total_draws": 0,
            "store_empty": True,
            "note": "The labs store holds zero draw records (verified empty query) — 'no labs yet' is the honest narration here, and only here.",
        }

    latest: Dict[str, Any] = lab_items[-1] if isinstance(lab_items[-1], dict) else {}
    biomarkers_raw = latest.get("biomarkers")
    biomarkers: Dict[str, Any] = biomarkers_raw if isinstance(biomarkers_raw, dict) else {}
    out_keys = [k for k in (latest.get("out_of_range") or []) if isinstance(k, str)]

    flagged = [_describe_marker(k, biomarkers[k]) for k in out_keys if isinstance(biomarkers.get(k), dict)]
    declared_count = _as_int(latest.get("out_of_range_count"), default=len(flagged))
    total_biomarkers = _as_int(latest.get("total_biomarkers"), default=len(biomarkers))

    draw_date = str(latest.get("draw_date") or "") or str(latest.get("sk") or "").replace("DATE#", "")[:10]

    block: Dict[str, Any] = {
        "expert_key": "labs",
        "period": "most recent draw",
        "store_empty": False,
        "draw_date": draw_date,
        "total_draws": len(lab_items),
        "total_biomarkers": total_biomarkers,
        "flagged_count": declared_count,
        "flagged_markers": flagged[:10],
    }
    if declared_count != len(flagged):
        # Declaration and detail extraction disagree — that is an extraction gap
        # against REAL draws, structurally distinct from an empty store.
        block["extraction_incomplete"] = (
            f"the draw record declares {declared_count} out-of-range biomarkers but detail extraction resolved "
            f"{len(flagged)} — an extraction gap on real data, NOT missing labs; never narrate this as zero "
            "results or a sync failure"
        )
    return block
