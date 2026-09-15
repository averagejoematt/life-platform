"""
tools_training_notes.py — read surface for the derived note-signal layer (Phase 1).

get_exercise_notes returns the per-exercise note timeline the coach reads as a trajectory
(the arc, not the latest line). pain_flag is surfaced prominently — this is the §7
pre-flight pain surface. Raw notes stay sovereign; this only reads the derived
`training_notes` projection (written by the on-ingest extractor in hevy_backfill_lambda).
"""

from datetime import timedelta

from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_now  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days
from training.training_notes import DEGRADE_UNRECORDED

from mcp.config import table
from mcp.core import LAYER_DARK, decimal_to_float, derived_layer_status

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

    start = (pacific_now().date() - timedelta(days=lookback_days)).isoformat()
    today = pacific_now().date().isoformat()
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

    start = (pacific_now().date() - timedelta(days=lookback_days)).isoformat()
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
            # #3699: a degraded row says WHY on the row itself. A row with no reason field
            # is not "unknown" — it is a record written before the extractor could say, and
            # it is reported as such rather than re-extracted (a re-derived signal in a
            # measured partition is indistinguishable from an original one, forever).
            "degraded_reason": (
                r.get("degraded_reason")
                or (f"{DEGRADE_UNRECORDED}: written before #3699 added the reason field; not re-derived" if r.get("degraded") else None)
            ),
            "corrected": bool(ov),
        }
        timeline.append(entry)
        if pain:
            pain_dates.append(r.get("date"))
        for s in signals:
            if s.get("class") == "progression" and s.get("value"):
                latest_progression = s["value"]

    # #3767: say whether the layer could be read at all, BEFORE reporting counts from it.
    # The health function has existed since this layer shipped and its docstring says "hook
    # into get_freshness_status"; it was hooked into the freshness TOOL and never into the
    # reader whose zeros it qualifies.
    try:
        from training.training_notes import training_notes_health

        health = training_notes_health(table)
    except Exception as e:  # noqa: BLE001
        health = {"checked": False, "error": f"{type(e).__name__}: {e}"}
    status, reason = derived_layer_status(health)
    dark = status in (LAYER_DARK, "unknown")

    out = {
        "exercise": matched or exercise,
        "template_id": template_id,
        "lookback_days": lookback_days,
        # The contract: a count from an unreadable layer is None, never 0. A caller that
        # sees null knows to ask get_exercise_history (the MEASURED sets) instead of
        # concluding the movement has no history.
        "sessions_with_notes": None if dark else len(timeline),
        "pain_flag_any": None if dark else bool(pain_dates),  # PROMINENT — the pre-flight pain surface (§7)
        "pain_dates": pain_dates,
        "latest_progression": latest_progression,
        "layer_status": status,
        "layer_health": health,
        "note": (
            "Derived note-signal layer (inferred, confidence-tagged); raw Hevy notes are sovereign. "
            "pain_flag is over-inclusive by design — confirm or dismiss before loading that movement."
        ),
    }
    if dark:
        out["layer_reason"] = reason
        out["measured_alternative"] = "get_exercise_history reads the raw logged sets and is unaffected by this layer."
        # No timeline key at all rather than an empty list: an empty list is a claim.
    else:
        out["timeline"] = timeline
        if reason:
            out["layer_reason"] = reason
    return out
