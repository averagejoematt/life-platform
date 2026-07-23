"""tools_coach_corrections.py — the MCP feedback channel for the weekly review pack
(#1690, foundation story S3 of epic #1687 "The Coach Correction Loop").

`log_coach_correction` lets Matthew correct a weekly-review-pack item by NUMBER from
chat today: he says "item #3 is wrong — the 315 lbs baseline is stale", the tool
resolves #3 → the archived generation the pack numbered, and writes ONE row to the
corrections ledger (#1689). The email-reply parser (lambdas/emails/
insight_email_parser_lambda.py) is the twin channel that lands the SAME rows.

Resolution + the write both reuse landed modules — this tool invents nothing:
  #N  --coach_correction_resolver.resolve_number-->  archived entry + item_ref
      (numbered via review_pack_ranker.numbered_entries over qa_archive.list_day)
  item_ref --coach_corrections.write_correction--> CORRECTION# ledger row (class-tagged)

An unknown / out-of-range / non-numeric number is REPORTED (an explicit error naming how
many items the week's pack has), never silently dropped (AC3).
"""

from typing import TYPE_CHECKING

from mcp.config import logger, table as _table_ref

try:
    # Shared, bundled modules (#781) — staged at zip root in the Lambda.
    import coach_correction_resolver as ccr
    import coach_corrections
except ImportError:  # pragma: no cover — the MCP bundle always ships lambdas/ at root
    if not TYPE_CHECKING:
        from lambdas import coach_correction_resolver as ccr, coach_corrections


def tool_log_coach_correction(args):
    """Correct a weekly-review-pack item by its number. Resolves #N to the archived
    generation it numbered and writes a class-tagged row to the corrections ledger
    (epic #1687). An unknown number is reported, not dropped."""
    args = args or {}

    correction_text = (args.get("correction") or args.get("correction_text") or "").strip()
    if not correction_text:
        return {"error": "correction text required — say what was wrong and what it should be (the 'correction' field)"}

    raw_n = args.get("item_number", args.get("number"))
    if raw_n is None:
        return {"error": "item_number required — the #N from this week's review pack (e.g. 3 for pack item #3)"}

    # Resolve #N against the SAME week's archive the pack numbered. A read failure is
    # surfaced honestly (never masqueraded as 'unknown #N'); a bad number is reported.
    try:
        resolution = ccr.resolve_number(raw_n)
    except Exception as e:  # noqa: BLE001 — archive read failed; tell Matthew, don't guess
        logger.warning(f"[#1690] review-pack resolve failed for #{raw_n}: {e}")
        return {"error": f"could not read this week's review pack to resolve #{raw_n} — try again shortly ({e})"}

    if not resolution.get("ok"):
        return {"error": resolution.get("error"), "total_items": resolution.get("total")}

    entry = resolution["entry"]
    item_ref = resolution["item_ref"]

    # Optional class override. write_correction normalizes an unknown class to 'other'
    # (preserving the raw label in error_class_raw) per #1689 — so we never reject; we
    # report when a supplied class wasn't recognized.
    requested_class = (args.get("error_class") or "other").strip() or "other"
    normalized_class = requested_class if requested_class in coach_corrections.ERROR_CLASSES else "other"

    try:
        sk = coach_corrections.write_correction(_table_ref, item_ref, correction_text, requested_class)
    except Exception as e:  # noqa: BLE001 — a lost correction must be loud (user feedback)
        logger.warning(f"[#1690] correction write failed for #{resolution['n']}: {e}")
        return {"error": f"correction could not be saved — please retry ({e})"}

    surface = entry.get("surface")
    coach = entry.get("variant")
    where = " · ".join(str(b) for b in (surface, coach, entry.get("date")) if b)
    result = {
        "status": "logged",
        "correction_id": sk,
        "item": {"number": resolution["n"], "surface": surface, "coach": coach, "date": entry.get("date")},
        "error_class": normalized_class,
        "message": (
            f"Correction logged for pack item #{resolution['n']} ({where}), tagged '{normalized_class}'. "
            "It joins the corrections ledger (epic #1687) so this class of error compounds toward not recurring."
        ),
    }
    if normalized_class != requested_class:
        result["error_class_note"] = (
            f"'{requested_class}' is not a known error-class — stored as 'other' (the original label is kept). "
            f"Known classes: {', '.join(coach_corrections.ERROR_CLASSES)}."
        )
    return result
