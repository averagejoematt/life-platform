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

from datetime import datetime
from typing import Any, Dict, List, Optional

from common.pacific_time import pacific_now  # #2811: THE Pacific day helper

# #3283: the nested-map read is the shared accessor — this module and
# health.labs_coaching each independently shipped the same "top-level schema
# that never existed" bug (#1993 / #3283), so the schema read lives once in
# health.labs_schema and both consumers import it.
from health.labs_schema import biomarker_map


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
    biomarkers: Dict[str, Dict[str, Any]] = biomarker_map(latest)
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


def labs_prompt_block(data: Dict[str, Any]) -> str:
    """The labs expert's prompt frame — the sentences that tell the model how to read
    the fact block above it.

    Lives here rather than in `ai_expert_analyzer_lambda` (#3728) because it is the
    other half of `build_labs_fact_block`: the block says `total_draws: 8, draw_date:
    2026-04-03`, and this says what those two numbers mean and what may not be
    inferred from them. Keeping them apart is how they drifted.

    The `#1993` half is the original: a zero-results narration is honest ONLY when
    `store_empty` is true, and `flagged_count: 0` is an unremarkable panel, never a
    sync failure (ADR-104).

    The `#3728` half is newer and was learned the expensive way. Naming only the DATE
    was not enough. The model was simultaneously being told "You have 0 blood draws of
    data" by the maturity voice — `build_data_inventory` counted labs over a rolling
    90-day window and all 8 draws are older than that — and it reconciled the
    contradiction by reading 2026-04-03 as a date in the FUTURE, telling Matthew on the
    public dashboard to "schedule the draw" before it. The inventory window is fixed at
    the source (`intelligence/inventory_window.py`); this states the direction of time
    so the frame cannot be misread again from a different direction.
    """
    draw_date = data.get("draw_date") or "unknown"
    draw_age = ""
    try:
        age_days = (pacific_now().date() - datetime.strptime(str(draw_date)[:10], "%Y-%m-%d").date()).days
        if age_days >= 0:
            draw_age = f" — {age_days} days ago, ALREADY DRAWN AND RESULTED"
    except (ValueError, TypeError):
        pass
    return f"""
IMPORTANT: Lab data spans Matthew's full history, not just the current experiment.
The data shows {data.get('total_draws', 0)} total blood draws, with the most recent
on {draw_date}{draw_age}. Do NOT describe this as "draws during the
experiment" — these are periodic lab draws over time.
EVERY draw named above is in the PAST. Never write about a past draw as if it were
scheduled, upcoming, or still to be booked, and never tell Matthew to prepare for a
date that has already gone by. If you want to talk about the NEXT panel, say so
without borrowing a date from the list above.
DATA-INTEGRITY GROUND RULES (ADR-104, #1993): you may describe the labs store as
empty ("zero results", "no draws", "a sync failure") ONLY when store_empty is true
in the data above. When draws exist, flagged_count of 0 means every extracted
biomarker was in range — an unremarkable panel, never a data failure. If
extraction_incomplete appears, name it as a platform extraction gap on real draws,
not as missing labs.
"""


def coach_domain_block(raw: Any) -> Dict[str, Any]:
    """The labs coach's `LABS DATA:` block — facts AND the frame, in one object (#3792).

    `ai_context._build_labs_data` used to hand-build this dict, reading
    `flagged_markers` / `flagged_count` / `total_draws` off top-level keys that #1993
    proved no draw record carries, and emitting `draw_date` as a bare date with no age
    and no statement that the draw is done. Handed `"2026-04-03"` beside
    `"total_draws": 0`, the model narrated a 166-day-old panel as forthcoming, live on
    `/api/coaching-dashboard`. It lives here so the window framing has ONE home: re-typing
    the sentence into a second place is how #3737's analyzer and that producer drifted.

    `raw` is the brief's `data["labs"]` — the chronological draw list, or a single record
    from a caller predating that shape. The single-record path still renders the frame but
    DROPS `total_draws`: one record is honest about the panel and says nothing about the
    history, and a bare "0 total blood draws" beside a real date is the exact
    contradiction #3728 traced the defect to.

    Pure: no DDB, no clock beyond `pacific_now()`. Proof in
    `tests/test_labs_producer_import_graph_3792.py`.
    """
    draws = raw if isinstance(raw, list) else ([raw] if raw else [])
    block = build_labs_fact_block(draws)
    if draws and not isinstance(raw, list):
        block.pop("total_draws", None)
    block["labs_framing_note"] = labs_prompt_block(block)
    return block
