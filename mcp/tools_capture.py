"""tools_capture.py — get_capture_queues: the one-call session opener (#1478).

Every chat mode (workout debrief, journal interview, speak-to-the-coaches, open
check-in) needs the same pre-flight picture: what's pending across every
manual-capture surface. Before this tool, opening a session meant 4-6 separate
MCP calls; get_capture_queues aggregates all of them into one.

Read-only composition over six existing tools' internals — this module never
re-implements their logic and never opens a new key family:

  coach_checkin    — the PERSISTED open questions only (cc.recent_checkins /
                      cc.open_checkins — the read-only half of
                      get_coach_checkin_queue). Deliberately does NOT trigger
                      fresh-question generation on an empty queue: that path
                      calls Bedrock and persists new records, which is neither
                      read-only nor a fit for a <2s aggregate opener. An empty
                      queue here is a legitimate "nothing pending" state — call
                      get_coach_checkin_queue directly when a fresh ask is
                      wanted.
  habit_reflection — missed-needing-why / completed-needing-driver COUNTS from
                      get_habit_reflection_queue (default 7-day window).
  field_note       — this week's status only (generated? responded?) from
                      get_field_notes — not the note text.
  evening_intake   — logged tonight? + dose-response arming progress (#1405),
                      read via intake_response.fetch_intake_by_date (the
                      single-query read). Deliberately skips
                      compute_intake_response's per-evening next-day whoop
                      lookups — get_intake_response already covers the full
                      dose-response read on demand; this is a status check.
  reading_recalls  — due recall prompt count from get_due_recalls.
  freshness_flags  — stale sources ONLY, name + days_dark, from
                      get_freshness_status (full per-source detail — fresh
                      sources, interior gaps, macro drift — stays behind that
                      tool).

Fail-soft per section (#1478 hard requirement): each section is computed
inside its own try/except via `_section()`. One broken sub-queue (a DynamoDB
read failure, a missing key, an import error) never kills the aggregate call —
it reports `{"status": "unavailable", "error": "<short reason>"}` for that
section only, and the other five still return complete data.
"""

from datetime import datetime, timezone

from mcp.config import logger, table
from mcp.tools_coach_checkin import _present as _present_checkin
from mcp.tools_coach_intelligence import COACH_IDS
from mcp.tools_habits import tool_get_habit_reflection_queue
from mcp.tools_labs import tool_get_freshness_status
from mcp.tools_lifestyle import tool_get_field_notes
from mcp.tools_reading import tool_get_due_recalls

try:
    # Shared, bundled modules (#781) — staged at zip root in the Lambda.
    import coach_checkin as cc
    import intake_response as ir
except ImportError:  # pragma: no cover — MCP bundle always ships lambdas/ at root
    from lambdas import coach_checkin as cc, intake_response as ir

# Evening-intake arming progress reads over the same window compute_intake_response
# defaults to (#1405), so the fraction reported here matches get_intake_response.
_INTAKE_ARMING_WINDOW_DAYS = 180


def _section(label, fn):
    """Run one sub-queue in isolation; never let it take the whole aggregate
    down (#1478). Returns fn()'s result, or a labeled unavailable marker."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — fail-soft is the entire point of this tool
        logger.warning(f"[#1478] capture-queue section '{label}' failed: {e}")
        return {"status": "unavailable", "error": str(e)[:200]}


def _coach_checkin_section():
    """Persisted open questions only — see module docstring for why this
    never triggers fresh-question generation."""
    open_items = cc.open_checkins(cc.recent_checkins(table, COACH_IDS))
    questions = [_present_checkin(it) for it in open_items[: cc.MAX_OPEN_QUESTIONS]]
    return {"open_questions": questions, "count": len(questions)}


def _habit_reflection_section():
    q = tool_get_habit_reflection_queue({})
    if q.get("error"):
        raise RuntimeError(q["error"])
    return {
        "window_days": q.get("window_days"),
        "missed_needs_why_count": q.get("missed_needs_why_total", 0),
        "completed_needs_driver_count": q.get("completed_needs_driver_total", 0),
    }


def _field_note_section():
    fn = tool_get_field_notes({})
    if fn.get("status") == "not_yet_generated":
        return {"week": fn.get("week"), "generated": False, "responded": False}
    return {
        "week": fn.get("week"),
        "generated": True,
        "responded": bool(fn.get("has_matthew_response")),
    }


def _evening_intake_section():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_date = ir.fetch_intake_by_date(table, window_days=_INTAKE_ARMING_WINDOW_DAYS)
    nonzero = sum(1 for c in by_date.values() if c > 0)
    return {
        "logged_tonight": today in by_date,
        "logged_evenings": len(by_date),
        "nonzero_evenings": nonzero,
        "dose_response_arming": f"{nonzero}/{ir.DOSE_RESPONSE_MIN_NONZERO}",
    }


def _reading_recalls_section():
    out = tool_get_due_recalls({})
    return {"count": out.get("count", 0)}


def _freshness_flags_section():
    fs = tool_get_freshness_status({})
    flags = [{"source": s.get("source"), "label": s.get("label"), "days_dark": s.get("age_days")} for s in fs.get("stale_sources", [])]
    return {"status": fs.get("status"), "stale_count": len(flags), "flags": flags}


def tool_get_capture_queues(args):
    """One-call session opener: every pending capture surface in one read (#1478).

    Aggregates six existing read tools' internals — no new key families, no
    re-implemented logic. Each section fails soft independently (see module
    docstring); a broken sub-queue never blocks the other five. Skip-without-
    penalty framing throughout — nothing here is a nag, just what's possible.
    """
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "coach_checkin": _section("coach_checkin", _coach_checkin_section),
        "habit_reflection": _section("habit_reflection", _habit_reflection_section),
        "field_note": _section("field_note", _field_note_section),
        "evening_intake": _section("evening_intake", _evening_intake_section),
        "reading_recalls": _section("reading_recalls", _reading_recalls_section),
        "freshness_flags": _section("freshness_flags", _freshness_flags_section),
        "how_to_use": (
            "One call, six pending-capture surfaces — the canonical session opener for workout debriefs, "
            "journal interviews, speak-to-the-coaches, and open check-ins. Everything here is optional: skip "
            "anything empty or 'unavailable' without penalty, and never nag Matthew about what's pending."
        ),
    }
