"""web/superseded_gap_reads.py — a stored coach read that states a logging gap the served record contradicts (#4185).

WHY THIS EXISTS

#4227 (merged 2026-09-26T22:00:26Z) put the served food-logging record in front of every coach, so
a coach can no longer narrate a gap the engine does not show. But the reads written BEFORE it are
stored, and `/api/coach/{id}.recent_outputs` still served them: the nutrition coach's 09-23, 09-24
and 09-25 reads ("The food log went dark after September 19th", "Nothing was logged since September
19th", "His food logging went silent after September 19th") and the physical coach's 09-13 read
("His food log went silent after September 10th") — while `/api/nutrition_overview` has a row for
every day after both dates. Regeneration cannot reach a stored past; this is the read-side answer.
Nothing in DynamoDB is written or deleted.

THE RULE (the narrowest one that catches the four live reads and nothing else)

A recent_output is SUPERSEDED when all three hold:
  1. it was written before the fix: no `data_through` stamp (the #4227 writer stamps every OUTPUT#
     row) AND `generated_at` earlier than `LOGGING_RECORD_FIX_INSTANT`;
  2. one of its sentences dates a logging stop — "went dark / silent / quiet after <Mon> <d>",
     "nothing was logged since <Mon> <d>" — read by `coach_input_facts._claimed_last_log`, the SAME
     matcher the #4227 served-fact gate uses on fresh drafts (one reading of the prose, not two);
  3. the served logging record (`health.nutrition_logging.logging_record`, the computation
     `/api/nutrition_overview` serves, over `coach_input_facts.fetch_macrofactor_window`) has a log
     AFTER that date — the claim is contradicted, not merely old.

A superseded read keeps its date and themes (the timeline's day stays in place), loses its
`summary` (null — the false sentence is never served), and carries `superseded` naming why. When
the record cannot be read the reads pass through unchanged: an unread record contradicts nothing.
The record is read only when a candidate exists (condition 1 + 2), so an ordinary profile request
costs no extra query.
"""

from __future__ import annotations

from typing import Any, Optional

LOGGING_RECORD_FIX_INSTANT = "2026-09-26T22:00:26+00:00"  # #4227's merge (830a5bd13) — a lower bound on its deploy
SUPERSEDED_NOTE = "superseded — generated before the logging-record fix"


def _before_fix(o: dict) -> bool:
    from common.pacific_time import parse_iso_utc

    gen, cut = parse_iso_utc(o.get("generated_at")), parse_iso_utc(LOGGING_RECORD_FIX_INSTANT)
    return not o.get("data_through") and gen is not None and cut is not None and gen < cut


def claimed_stop_date(o: dict) -> Optional[str]:
    """The earliest logging-stop date a pre-fix read's summary states, or None."""
    if not o.get("summary") or not _before_fix(o):
        return None
    from coach.coach_input_facts import _claimed_last_log
    from operational.weight_truth_qa import _sentences

    day = str(o.get("date") or o.get("generated_at") or "")[:10]
    dates = [d for d in (_claimed_last_log(s, day) for s in _sentences(o["summary"])) if d]
    return min(dates) if dates else None


def mark(outputs: list, served_last_log: Optional[str]) -> list:
    """Pure: the outputs with every contradicted pre-fix gap read superseded (see the module rule)."""
    if not served_last_log:
        return outputs
    out = []
    for o in outputs:
        d = claimed_stop_date(o)
        if d and served_last_log > d:
            o = {
                **o,
                "summary": None,
                "superseded": {
                    "note": SUPERSEDED_NOTE,
                    "claimed_logging_stopped_after": d,
                    "served_last_log": served_last_log,
                    "ref": "#4185 / #4227",
                },
            }
        out.append(o)
    return out


def apply(outputs: list, table: Any, today: str) -> list:
    """`mark` against the served record — read only when some output is a candidate. Fail-open."""
    if not any(claimed_stop_date(o) for o in outputs):
        return outputs
    try:
        from coach.coach_input_facts import fetch_macrofactor_window
        from health import nutrition_logging

        rows = fetch_macrofactor_window(table, today)
        latest = nutrition_logging.logging_record(rows, today).get("latest_date") if rows is not None else None
    except Exception:  # noqa: BLE001 — an unread record contradicts nothing
        latest = None
    return mark(outputs, latest)
