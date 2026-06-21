"""
tools_training_notes.py — read surface for the derived note-signal layer (Phase 1).

get_exercise_notes returns the per-exercise note timeline the coach reads as a trajectory
(the arc, not the latest line). pain_flag is surfaced prominently — this is the §7
pre-flight pain surface. Raw notes stay sovereign; this only reads the derived
`training_notes` projection (written by the on-ingest extractor in hevy_backfill_lambda).
"""

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from mcp.config import table
from mcp.core import decimal_to_float

NOTES_SOURCE = "training_notes"


def _resolve_template_id(exercise: str, lookback_days: int) -> tuple[str | None, str | None]:
    """Resolve a human exercise name → (template_id, matched_name) via recent raw Hevy
    workouts. If `exercise` already looks like a template id, pass it through."""
    ex = (exercise or "").strip()
    if not ex:
        return None, None
    # Heuristic: a Hevy template id is hex (8) or a uuid — no spaces. A name has spaces
    # or isn't a bare id. Try direct first only if it has no spaces and isn't obviously words.
    looks_like_id = (" " not in ex) and (len(ex) >= 8) and (all(c in "0123456789abcdefABCDEF-" for c in ex))
    if looks_like_id:
        return ex, None

    start = (datetime.now(timezone.utc).date() - timedelta(days=lookback_days)).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#hevy") & Key("sk").between(f"DATE#{start}", f"DATE#{today}~"),
            ProjectionExpression="exercises",
        )
    except Exception:
        return None, None
    needle = ex.lower()
    best = None
    for it in resp.get("Items", []):
        for e in decimal_to_float(it).get("exercises", []) or []:
            nm = (e.get("name") or e.get("title") or "").lower()
            tid = e.get("template_id")
            if tid and (needle in nm or nm in needle):
                best = (str(tid), e.get("name") or e.get("title"))
                if needle == nm:
                    return best  # exact wins immediately
    return best or (None, None)


def tool_get_exercise_notes(args):
    """Per-exercise note timeline (the arc) + signals + pain flags from the derived layer."""
    args = args or {}
    exercise = args.get("exercise") or args.get("template_id") or ""
    lookback_days = int(args.get("lookback_days") or 180)
    if not exercise:
        return {"error": "Provide 'exercise' (name) or 'template_id'."}

    template_id, matched = _resolve_template_id(exercise, lookback_days)
    if not template_id:
        return {"error": f"No exercise matching {exercise!r} found in the last {lookback_days}d of workouts.", "exercise": exercise}

    start = (datetime.now(timezone.utc).date() - timedelta(days=lookback_days)).isoformat()
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#matthew#SOURCE#{NOTES_SOURCE}#EXERCISE#{template_id}")
            & Key("sk").gte(f"DATE#{start}"),
        )
    except Exception as e:
        return {"error": f"query failed: {e}", "template_id": template_id}

    rows = [decimal_to_float(it) for it in resp.get("Items", [])]
    # Corrections win on read (sk …#CORRECTION) and survive recompute.
    corrections = {r["sk"].replace("#CORRECTION", ""): r for r in rows if r.get("sk", "").endswith("#CORRECTION")}
    timeline = []
    latest_progression = None
    pain_dates = []
    for r in sorted([x for x in rows if not x.get("sk", "").endswith("#CORRECTION")], key=lambda x: x.get("sk", "")):
        ov = corrections.get(r.get("sk", ""))
        signals = (ov or {}).get("signals", r.get("signals", []))
        pain = (ov or {}).get("pain_flag", r.get("pain_flag", False))
        entry = {
            "date": r.get("date"),
            "workout_uid": r.get("workout_uid"),
            "note_raw": r.get("note_raw"),
            "signals": signals,
            "pain_flag": pain,
            "sentiment": (ov or {}).get("sentiment", r.get("sentiment")),
            "degraded": r.get("degraded", False),
            "corrected": bool(ov),
        }
        timeline.append(entry)
        if pain:
            pain_dates.append(r.get("date"))
        for s in signals:
            if s.get("class") == "progression" and s.get("value"):
                latest_progression = s["value"]

    return {
        "exercise": matched or exercise,
        "template_id": template_id,
        "lookback_days": lookback_days,
        "sessions_with_notes": len(timeline),
        "pain_flag_any": bool(pain_dates),  # PROMINENT — the pre-flight pain surface (§7)
        "pain_dates": pain_dates,
        "latest_progression": latest_progression,
        "timeline": timeline,
        "note": (
            "Derived note-signal layer (inferred, confidence-tagged); raw Hevy notes are sovereign. "
            "pain_flag is over-inclusive by design — confirm or dismiss before loading that movement."
        ),
    }
