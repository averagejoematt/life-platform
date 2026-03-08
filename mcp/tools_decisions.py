"""
tools_decisions.py — IC-19: Decision Journal.

Track platform-guided decisions and their outcomes. Builds a trust-calibration
dataset: when to follow the system vs override it.

DDB key pattern: pk=USER#matthew#SOURCE#decisions, sk=DECISION#<ISO-timestamp>

Tools:
  140. log_decision          — record a decision the platform recommended
  141. get_decisions         — retrieve recent decisions with outcomes
  142. update_decision_outcome — record what happened after a decision

v1.0.0 — 2026-03-07
"""

import json
from datetime import datetime, timedelta, timezone
from .tools_data import _get_table, _get_user_id, _d2f

DECISIONS_SOURCE = "decisions"


def _decisions_pk():
    return f"USER#{_get_user_id()}#SOURCE#{DECISIONS_SOURCE}"


# ==============================================================================
# TOOL FUNCTIONS (must be defined BEFORE TOOLS dict in registry.py)
# ==============================================================================

def tool_log_decision(args):
    """Log a platform-guided decision.

    Records what the platform recommended, what Matthew decided, and context.
    Outcome fields are populated later via update_decision_outcome.
    """
    table = _get_table()
    decision_text = args.get("decision", "").strip()
    source = args.get("source", "daily_brief")
    followed = args.get("followed")
    override_reason = args.get("override_reason", "")
    pillars = args.get("pillars", [])
    date = args.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not decision_text:
        return {"error": "decision text is required"}

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    sk = f"DECISION#{ts}"

    item = {
        "pk": _decisions_pk(),
        "sk": sk,
        "date": date,
        "decision": decision_text[:500],
        "source": source,
        "followed": followed,
        "override_reason": override_reason[:300] if override_reason else None,
        "pillars": pillars,
        "outcome_metric": None,
        "outcome_delta": None,
        "outcome_notes": None,
        "outcome_date": None,
        "effectiveness": None,
    }

    # Clean None values for DDB
    item = {k: v for k, v in item.items() if v is not None}

    table.put_item(Item=item)

    status = "followed" if followed else ("overridden" if followed is False else "pending")
    return {
        "status": "logged",
        "sk": sk,
        "decision": decision_text[:100],
        "followed": status,
        "tip": "Use update_decision_outcome in 1-3 days to record what happened.",
    }


def tool_get_decisions(args):
    """Retrieve recent decisions with outcomes and effectiveness.

    Supports filtering by date range, pillar, and whether outcome is recorded.
    Returns decisions newest-first.
    """
    table = _get_table()
    days = int(args.get("days", 30))
    pillar_filter = args.get("pillar")
    outcome_only = args.get("outcome_only", False)

    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(_decisions_pk()) & Key("sk").begins_with("DECISION#"),
        ScanIndexForward=False,
        Limit=100,
    )
    items = resp.get("Items", [])

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    items = [i for i in items if i.get("date", "") >= cutoff]

    if pillar_filter:
        items = [i for i in items if pillar_filter in i.get("pillars", [])]

    if outcome_only:
        items = [i for i in items if i.get("outcome_metric") or i.get("outcome_notes")]

    # Compute summary stats
    total = len(items)
    followed_count = sum(1 for i in items if i.get("followed") is True)
    overridden_count = sum(1 for i in items if i.get("followed") is False)
    with_outcome = sum(1 for i in items if i.get("outcome_metric") or i.get("outcome_notes"))

    # Effectiveness breakdown
    effective = [i for i in items if i.get("effectiveness") is not None]
    follow_effective = [i for i in effective if i.get("followed") is True]
    override_effective = [i for i in effective if i.get("followed") is False]

    follow_score = (sum(i.get("effectiveness", 0) for i in follow_effective) / len(follow_effective)
                    if follow_effective else None)
    override_score = (sum(i.get("effectiveness", 0) for i in override_effective) / len(override_effective)
                      if override_effective else None)

    return _d2f({
        "total_decisions": total,
        "followed": followed_count,
        "overridden": overridden_count,
        "pending_followup": total - with_outcome,
        "trust_calibration": {
            "follow_effectiveness": round(follow_score, 2) if follow_score is not None else "insufficient data",
            "override_effectiveness": round(override_score, 2) if override_score is not None else "insufficient data",
            "recommendation": (
                "Trust the platform" if (follow_score or 0) > (override_score or 0)
                else "Your overrides are working well" if override_score and (override_score > (follow_score or 0))
                else "Need more outcome data to calibrate"
            ),
        },
        "decisions": [{
            "date": i.get("date"),
            "decision": i.get("decision"),
            "source": i.get("source"),
            "followed": i.get("followed"),
            "override_reason": i.get("override_reason"),
            "outcome_metric": i.get("outcome_metric"),
            "outcome_delta": i.get("outcome_delta"),
            "outcome_notes": i.get("outcome_notes"),
            "effectiveness": i.get("effectiveness"),
        } for i in items[:20]],
    })


def tool_update_decision_outcome(args):
    """Record the outcome of a past decision.

    Called 1-3 days after the original decision to capture what actually happened.
    Computes effectiveness score: positive outcome + followed = good platform advice;
    negative outcome + overridden = good override instinct.
    """
    table = _get_table()
    sk = args.get("sk", "").strip()
    outcome_metric = args.get("outcome_metric", "")
    outcome_delta = args.get("outcome_delta")
    outcome_notes = args.get("outcome_notes", "")
    effectiveness = args.get("effectiveness")

    if not sk:
        return {"error": "sk (sort key) is required — get it from get_decisions"}

    if not sk.startswith("DECISION#"):
        return {"error": "sk must start with DECISION#"}

    # Build update expression
    update_parts = []
    expr_names = {}
    expr_values = {}

    if outcome_metric:
        update_parts.append("#om = :om")
        expr_names["#om"] = "outcome_metric"
        expr_values[":om"] = outcome_metric

    if outcome_delta is not None:
        update_parts.append("outcome_delta = :od")
        expr_values[":od"] = str(outcome_delta)

    if outcome_notes:
        update_parts.append("outcome_notes = :on")
        expr_values[":on"] = outcome_notes[:500]

    if effectiveness is not None:
        update_parts.append("effectiveness = :ef")
        expr_values[":ef"] = int(effectiveness)

    update_parts.append("outcome_date = :odate")
    expr_values[":odate"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not update_parts:
        return {"error": "Provide at least one outcome field"}

    kwargs = {
        "Key": {"pk": _decisions_pk(), "sk": sk},
        "UpdateExpression": "SET " + ", ".join(update_parts),
        "ExpressionAttributeValues": expr_values,
    }
    if expr_names:
        kwargs["ExpressionAttributeNames"] = expr_names

    table.update_item(**kwargs)

    return {
        "status": "outcome recorded",
        "sk": sk,
        "effectiveness": effectiveness,
        "tip": "Over time, get_decisions will show whether following or overriding platform advice produces better outcomes.",
    }
