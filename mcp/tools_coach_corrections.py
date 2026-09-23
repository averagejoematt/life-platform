"""tools_coach_corrections.py — the MCP feedback channel for the weekly review pack
(#1690, foundation story S3 of epic #1687 "The Coach Correction Loop") AND for any live
chat-session override (#4083).

`log_coach_correction` started as ONE path: Matthew reads the ranked review-pack email
(each generation carries a stable #N) and corrects an item by NUMBER — this resolves #N
back to the exact archived generation the pack numbered and writes ONE row to the
corrections ledger (#1689). The email-reply parser (lambdas/emails/
insight_email_parser_lambda.py) is the twin channel that lands the SAME rows.

  #N  --coach_correction_resolver.resolve_number-->  archived entry + item_ref
      (numbered via review_pack_ranker.numbered_entries over qa_archive.list_day)
  item_ref --coach_corrections.write_correction--> CORRECTION# ledger row (class-tagged)

An unknown / out-of-range / non-numeric number is REPORTED (an explicit error naming how
many items the week's pack has), never silently dropped (AC3).

#4083 — THE SECOND PATH. A live coaching session (daily-debrief / speak-to-coaches /
open-checkin) overrides a coach's read mid-conversation — "that toe flag is stale, the
foot's fine" — and there is no weekly-pack #N to resolve: nothing was numbered, nothing
was archived yet. `signal` is the alternative to `item_number` for exactly this case: the
caller names the SIGNAL that was wrong (the metric/flag id, e.g. 'readiness_low_streak_days'
or 'toe_flag') instead of a pack number, and the tool builds its own `item_ref` (mirroring
`coach.critic_overrides.override_item_ref`'s shape — `surface`/`coach`/`signal` — the SAME
convention the stage-2 veto-override path already writes, #4076) rather than resolving
one. Exactly one of `item_number` / `signal` is required, never both, never neither — an
ambiguous or empty call is reported, not guessed. Both paths converge on the same
`coach_corrections.write_correction` ledger write, so `false_positive_signal_ranking`
(read via `get_intelligence_quality`) sees a signal-named correction regardless of which
door it came through.
"""

from typing import TYPE_CHECKING

from common.pacific_time import pacific_today

from mcp.config import logger, table as _table_ref

try:
    # Shared, bundled modules (#781) — staged at zip root in the Lambda.
    from coach import coach_checkin, coach_correction_resolver as ccr, coach_corrections
except ImportError:  # pragma: no cover — the MCP bundle always ships lambdas/ at root
    if not TYPE_CHECKING:
        from lambdas import coach_checkin, coach_correction_resolver as ccr, coach_corrections


def _normalized_error_class(args) -> tuple[str, str | None]:
    """(class stored, note if the requested class was unrecognized). Never rejects —
    `write_correction` stores an unknown label as 'other' with the original preserved."""
    requested = (args.get("error_class") or "other").strip() or "other"
    normalized = requested if requested in coach_corrections.ERROR_CLASSES else "other"
    note = None
    if normalized != requested:
        note = (
            f"'{requested}' is not a known error-class — stored as 'other' (the original label is kept). "
            f"Known classes: {', '.join(coach_corrections.ERROR_CLASSES)}."
        )
    return requested, note


def _log_pack_number_correction(args, correction_text):
    """Path 1 (#1690): correct a weekly review-pack item by its #N."""
    raw_n = args.get("item_number", args.get("number"))
    try:
        resolution = ccr.resolve_number(raw_n)
    except Exception as e:  # noqa: BLE001 — archive read failed; tell Matthew, don't guess
        logger.warning(f"[#1690] review-pack resolve failed for #{raw_n}: {e}")
        return {"error": f"could not read this week's review pack to resolve #{raw_n} — try again shortly ({e})"}

    if not resolution.get("ok"):
        return {"error": resolution.get("error"), "total_items": resolution.get("total")}

    entry = resolution["entry"]
    item_ref = resolution["item_ref"]
    requested_class, class_note = _normalized_error_class(args)
    stored_class = "other" if class_note else requested_class

    try:
        sk = coach_corrections.write_correction(_table_ref, item_ref, correction_text, requested_class, cycle=coach_checkin.read_cycle())
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
        "error_class": stored_class,
        "message": (
            f"Correction logged for pack item #{resolution['n']} ({where}), tagged '{stored_class}'. "
            "It joins the corrections ledger (epic #1687) so this class of error compounds toward not recurring."
        ),
    }
    if class_note:
        result["error_class_note"] = class_note
    return result


def _log_signal_correction(args, correction_text):
    """Path 2 (#4083): a live-session override with no pack number — the caller names the
    SIGNAL (metric/flag id) that was wrong. `surface` defaults to 'chat_coaching'; `coach`
    is optional (a surface-wide correction, per `coach_corrections._item_ref_matches`)."""
    signal = str(args.get("signal") or "").strip()
    if not signal:
        return {
            "error": "signal required when item_number is not given — the metric/flag id that was wrong (e.g. 'readiness_low_streak_days')"
        }

    coach_raw = (args.get("coach") or "").strip() or None
    item_ref = {
        "surface": (args.get("surface") or "chat_coaching").strip() or "chat_coaching",
        "coach": coach_checkin.normalize_coach_id(coach_raw) if coach_raw else None,
        "signal": signal,
        "date": pacific_today(),
    }
    requested_class, class_note = _normalized_error_class(args)

    try:
        sk = coach_corrections.write_correction(_table_ref, item_ref, correction_text, requested_class, cycle=coach_checkin.read_cycle())
    except Exception as e:  # noqa: BLE001 — a lost correction must be loud (user feedback)
        logger.warning(f"[#4083] signal correction write failed for signal={signal!r}: {e}")
        return {"error": f"correction could not be saved — please retry ({e})"}

    result = {
        "status": "logged",
        "correction_id": sk,
        "item": {"signal": signal, "surface": item_ref["surface"], "coach": item_ref["coach"], "date": item_ref["date"]},
        "error_class": "other" if class_note else requested_class,
        "message": (
            f"Correction logged for signal '{signal}' ({item_ref['surface']}), tagged "
            f"'{'other' if class_note else requested_class}'. It joins the corrections ledger (epic #1687) and "
            "counts toward that signal's false-positive rate (get_intelligence_quality)."
        ),
    }
    if class_note:
        result["error_class_note"] = class_note
    return result


def tool_log_coach_correction(args):
    """Correct a weekly-review-pack item by its number (`item_number`), OR log a live
    chat-session override by naming the SIGNAL that was wrong (`signal`, #4083). Exactly
    one of the two is required. An unknown pack number is reported, not dropped."""
    args = args or {}

    correction_text = (args.get("correction") or args.get("correction_text") or "").strip()
    if not correction_text:
        return {"error": "correction text required — say what was wrong and what it should be (the 'correction' field)"}

    has_number = args.get("item_number", args.get("number")) is not None
    has_signal = bool(str(args.get("signal") or "").strip())
    if has_number and has_signal:
        return {"error": "pass exactly one of item_number / signal, not both — they are two different correction paths"}
    if has_number:
        return _log_pack_number_correction(args, correction_text)
    if has_signal:
        return _log_signal_correction(args, correction_text)
    return {
        "error": (
            "either item_number (the #N from this week's review pack) or signal (the metric/flag id a live "
            "session override was correcting, #4083) is required"
        )
    }
