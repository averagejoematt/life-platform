"""tools_habits.py — habit causality reflection loop (#422, EVR-01/02).

The SECONDARY capture channel for habit causality. The PRIMARY channel is Habitify
notes (ingested by lambdas/ingestion/habitify_lambda.py — captured in the app at the
moment of behaviour). This module is the *reflection* channel: when Matthew is already
talking to Claude, Claude can look at what recently happened, ask about the gaps, and log
his answers as the richer context layer.

Mirrors the Field-Notes reflection idiom (tools_lifestyle.get_field_notes /
log_field_note_response): a READ tool surfaces what to ask about, a WRITE tool records the
answer with update semantics so nothing is clobbered.

  get_habit_reflection_queue — recent habit-days still missing causality context
                               (missed days with no why; completed days with no
                               trigger/reward), last N days + a weekly view. This is what
                               lets a conversation know what to ask. Read-only, no nagging.
  log_habit_reflection       — record Matthew's answer keyed to habit + date
                               (trigger / reward / why-missed / free-text context),
                               tagged channel="claude_reflection".

Store (the Claude-sourced half of the unified causality view):
  pk = USER#matthew#SOURCE#habit_causality
  sk = HABITDAY#<date>#<slug>
Habitify-sourced notes live on the habitify record (habit_statuses[name].notes); the
habits page and get_habit_reflection_queue MERGE both, each tagged with its channel, so
the two coexist per habit-day and never overwrite each other.
"""

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from mcp.config import USER_ID as _user_id_ref, table as _table_ref
from mcp.core import decimal_to_float as _d2f

try:
    # Shared, bundled module (#781) — the deterministic conventions live here.
    from habit_causality import clip_note, parse_note, slugify_habit
except ImportError:  # pragma: no cover — MCP bundle always ships lambdas/ at root
    from lambdas.habit_causality import clip_note, parse_note, slugify_habit

CAUSALITY_SOURCE = "habit_causality"
HABITIFY_SOURCE = "habitify"
CHANNEL_REFLECTION = "claude_reflection"
CHANNEL_HABITIFY = "habitify_note"

# A missed day is one Habitify resolved as not-done.
_MISSED_STATES = {"failed", "skipped"}


def _pk(source):
    return f"USER#{_user_id_ref}#SOURCE#{source}"


def _causality_sk(date_str, name):
    return f"HABITDAY#{date_str}#{slugify_habit(name)}"


def _recent_habitify(days):
    """Latest-per-day Habitify records for the trailing `days` window (inclusive today)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")
    resp = _table_ref.query(
        KeyConditionExpression=Key("pk").eq(_pk(HABITIFY_SOURCE)) & Key("sk").between(f"DATE#{start}", f"DATE#{today}"),
        ScanIndexForward=True,
    )
    return _d2f(resp.get("Items", []))


def _captured_reflections(days):
    """Existing claude_reflection records in the window, indexed by (date, slug)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")
    resp = _table_ref.query(
        KeyConditionExpression=Key("pk").eq(_pk(CAUSALITY_SOURCE)) & Key("sk").between(f"HABITDAY#{start}", f"HABITDAY#{today}~"),
        ScanIndexForward=True,
    )
    out = {}
    for it in _d2f(resp.get("Items", [])):
        out[(it.get("date"), it.get("slug"))] = it
    return out


def tool_get_habit_reflection_queue(args):
    """Recent habit-days still missing causality context — what Claude can ask about.

    Deterministic (no AI): returns missed days lacking a why-missed reason and completed
    days lacking a trigger/reward, scoped to the last N days. "Optionally" is the whole
    point — this only makes the ask *possible* when Matthew is already in a conversation;
    it schedules nothing and pushes nothing.
    """
    days = int(args.get("days", 7))
    days = max(1, min(days, 31))

    try:
        habitify = _recent_habitify(days)
    except Exception as e:  # pragma: no cover — live DDB only
        return {"error": f"could not read habit history: {e}"}
    reflections = _captured_reflections(days)

    missed_needs_why = []
    done_needs_driver = []
    for rec in habitify:
        date = rec.get("date") or rec.get("sk", "").replace("DATE#", "")
        statuses = rec.get("habit_statuses") or {}
        for name, st in statuses.items():
            st = st if isinstance(st, dict) else {}
            status = st.get("status")
            group = st.get("group") or "Other"
            slug = slugify_habit(name)
            refl = reflections.get((date, slug)) or {}
            habitify_notes = st.get("notes") or []

            if status in _MISSED_STATES:
                has_why = bool(refl.get("why_missed")) or bool(habitify_notes)
                if not has_why:
                    missed_needs_why.append({"habit": name, "date": date, "group": group, "status": status})
            elif status == "completed":
                has_driver = bool(refl.get("trigger") or refl.get("reward")) or bool(habitify_notes)
                if not has_driver:
                    done_needs_driver.append({"habit": name, "date": date, "group": group})

    # Newest-first, bounded — a conversation asks about a handful, not everything.
    missed_needs_why.sort(key=lambda x: x["date"], reverse=True)
    done_needs_driver.sort(key=lambda x: x["date"], reverse=True)

    return _d2f(
        {
            "window_days": days,
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "missed_needs_why": missed_needs_why[:15],
            "completed_needs_driver": done_needs_driver[:15],
            "missed_needs_why_total": len(missed_needs_why),
            "completed_needs_driver_total": len(done_needs_driver),
            "already_captured": len(reflections),
            "how_to_ask": (
                "Ask Matthew about a couple of these — e.g. 'You missed {habit} on {date} — what got in the way?' "
                "or 'Nice, you kept {habit} — what cued it / what did it pay back?' — then call log_habit_reflection "
                "with his answer. Only if he's up for it; never nag."
            ),
        }
    )


def tool_log_habit_reflection(args):
    """Log Matthew's reflection about a habit on a date (the Claude-sourced context layer).

    Records any of trigger / reward / why_missed / free-text context, keyed to habit+date.
    Uses update semantics: re-logging fills in fields without clobbering, and it lives in a
    separate channel from Habitify notes so the two never overwrite each other. Stored
    verbatim (ADR-104) — no inference beyond the literal trigger:/reward: note convention.
    """
    name = (args.get("habit") or "").strip()
    if not name:
        return {"error": "habit is required (the habit name as it appears in the tracker)"}
    date = (args.get("date") or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    trigger = clip_note(args.get("trigger"))
    reward = clip_note(args.get("reward"))
    why_missed = clip_note(args.get("why_missed"))
    context = clip_note(args.get("context"))

    # A bare context/note may carry an explicit "trigger:"/"reward:" convention — lift it,
    # deterministically, exactly as the Habitify-note path does.
    if context and not (trigger or reward):
        parsed = parse_note(context)
        trigger = trigger or (parsed.get("trigger") or "")
        reward = reward or (parsed.get("reward") or "")

    if not (trigger or reward or why_missed or context):
        return {"error": "provide at least one of: trigger, reward, why_missed, context"}

    sk = _causality_sk(date, name)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    # Base attributes always set (identity of the record); channel is fixed for this tool.
    update_parts = [
        "habit = :h",
        "#d = :date",
        "slug = :slug",
        "channel = :ch",
        "#src = :src",
        "updated_at = :ts",
    ]
    expr_names = {"#d": "date", "#src": "source"}
    expr_values = {
        ":h": name,
        ":date": date,
        ":slug": slugify_habit(name),
        ":ch": CHANNEL_REFLECTION,
        ":src": CAUSALITY_SOURCE,
        ":ts": ts,
    }
    for field, val in (("trigger", trigger), ("reward", reward), ("why_missed", why_missed), ("context", context)):
        if val:
            update_parts.append(f"{field} = :{field}")
            expr_values[f":{field}"] = val

    _table_ref.update_item(
        Key={"pk": _pk(CAUSALITY_SOURCE), "sk": sk},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )

    captured = [f for f, v in (("trigger", trigger), ("reward", reward), ("why_missed", why_missed), ("context", context)) if v]
    return {
        "status": "saved",
        "habit": name,
        "date": date,
        "channel": CHANNEL_REFLECTION,
        "captured": captured,
        "message": (
            f"Logged reflection for '{name}' on {date} ({', '.join(captured)}). "
            "It'll show on the habits page next to any in-app Habitify note — both are kept."
        ),
    }
