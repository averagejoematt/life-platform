"""
Coach Intelligence MCP tools — query coach threads, predictions, disagreements.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from mcp.core import USER_PREFIX, decimal_to_float, table

logger = logging.getLogger(__name__)

COACH_IDS = ["sleep", "nutrition", "training", "mind", "physical", "glucose", "labs", "explorer"]
COACH_NAMES = {
    "sleep": "Dr. Lisa Park",
    "nutrition": "Dr. Marcus Webb",
    "training": "Dr. Sarah Chen",
    "mind": "Dr. Nathan Reeves",
    "physical": "Dr. Victor Reyes",
    "glucose": "Dr. Amara Patel",
    "labs": "Dr. James Okafor",
    "explorer": "Dr. Henning Brandt",
}


def tool_get_coach_thread(args):
    """Read a coach's thread history — persistent memory of positions, predictions, surprises."""
    coach_id = args.get("coach_id")
    if not coach_id:
        return {"error": "coach_id required. Valid: " + ", ".join(COACH_IDS)}
    limit = int(args.get("limit", 4))

    try:
        # ADR-058: phase=pilot hidden by default.
        from mcp.core import _apply_phase_filter

        resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq("USER#matthew") & Key("sk").begins_with(f"SOURCE#coach_thread#{coach_id}#"),
                    "ScanIndexForward": False,
                    "Limit": limit,
                }
            )
        )
        entries = [decimal_to_float(i) for i in resp.get("Items", [])]
        return {
            "coach_id": coach_id,
            "coach_name": COACH_NAMES.get(coach_id, coach_id),
            "entries": len(entries),
            "thread": [
                {
                    "date": e.get("date"),
                    "week": e.get("week"),
                    "position_summary": e.get("position_summary"),
                    "emotional_investment": e.get("emotional_investment"),
                    "predictions": e.get("predictions", []),
                    "surprises": e.get("surprises", []),
                    "open_questions": e.get("open_questions", []),
                    "stance_changes": e.get("stance_changes", []),
                }
                for e in entries
            ],
        }
    except Exception as ex:
        return {"error": str(ex)}


def tool_get_predictions(args):
    """Cross-coach prediction ledger — all predictions with statuses."""
    status_filter = args.get("status")  # pending, confirmed, refuted, or None
    coach_filter = args.get("coach_id")
    limit = int(args.get("limit", 20))

    all_predictions = []
    coaches_to_check = [coach_filter] if coach_filter else COACH_IDS

    for cid in coaches_to_check:
        try:
            # ADR-058: phase=pilot hidden by default.
            from mcp.core import _apply_phase_filter

            resp = table.query(
                **_apply_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq("USER#matthew") & Key("sk").begins_with(f"SOURCE#coach_thread#{cid}#"),
                        "ScanIndexForward": False,
                        "Limit": 8,
                    }
                )
            )
            for item in resp.get("Items", []):
                entry = decimal_to_float(item)
                for pred in entry.get("predictions", []):
                    if status_filter and pred.get("status") != status_filter:
                        continue
                    all_predictions.append(
                        {
                            "coach_id": cid,
                            "coach_name": COACH_NAMES.get(cid, cid),
                            "date": entry.get("date"),
                            **pred,
                        }
                    )
        except Exception:
            pass

    # Sort by date descending
    all_predictions.sort(key=lambda p: p.get("date", ""), reverse=True)

    summary = defaultdict(int)
    for p in all_predictions:
        summary[p.get("status", "unknown")] += 1

    return {
        "total": len(all_predictions),
        "summary": dict(summary),
        "predictions": all_predictions[:limit],
    }


def tool_get_coach_disagreements(args):
    """Find current inter-coach disagreements from the integrator synthesis."""
    try:
        resp = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"})
        item = decimal_to_float(resp.get("Item", {}))
        disagreements = item.get("disagreements", [])
        return {
            "count": len(disagreements),
            "generated_at": item.get("generated_at"),
            "disagreements": disagreements,
        }
    except Exception as ex:
        return {"error": str(ex)}


def tool_get_coach_track_record(args):
    """Hit-rate track record for a coach over a time window.

    Reads the new `COACH#{coach_id}` partition (post-ADR-047) where the daily
    `coach-prediction-evaluator` Lambda writes verdicts (PREDICTION# records
    get a status update, LEARNING# records archive the audit trail).

    Args:
        coach_id: e.g. "glucose" or "glucose_coach" — accepts either form
        days:     lookback window for evaluations (default 30)
        subdomain: optional filter (e.g. "sleep_quality", "glucose")
    """
    raw_cid = (args.get("coach_id") or "").strip().lower()
    if not raw_cid:
        return {"error": "coach_id required. Valid: " + ", ".join(COACH_IDS)}
    # Normalize: MCP convention is bare names ("glucose"); evaluator stores with
    # _coach suffix ("glucose_coach"). Accept either.
    cid = raw_cid if raw_cid.endswith("_coach") else f"{raw_cid}_coach"
    bare_cid = cid.removesuffix("_coach")  # for COACH_NAMES lookup (keyed on bare form)

    days = int(args.get("days") or 30)
    subdomain_filter = (args.get("subdomain") or "").strip().lower() or None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    coach_pk = f"COACH#{cid}"

    try:
        # LEARNING# is the authoritative per-evaluation audit. Query the date
        # range as a between() against the SK pattern LEARNING#{date}#{slug}.
        from mcp.core import _apply_phase_filter  # ADR-058

        resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").between(f"LEARNING#{cutoff}", "LEARNING#z"),
                    "ScanIndexForward": False,
                }
            )
        )
    except Exception as ex:
        return {"error": str(ex)}

    learnings = [decimal_to_float(i) for i in resp.get("Items", [])]
    if subdomain_filter:
        learnings = [l for l in learnings if l.get("subdomain", "").lower() == subdomain_filter]

    by_outcome = defaultdict(int)
    by_subdomain = defaultdict(lambda: defaultdict(int))
    by_metric = defaultdict(lambda: defaultdict(int))
    for l in learnings:
        status = l.get("status", "unknown")
        subdomain = l.get("subdomain", "unspecified")
        metric = l.get("metric", "unspecified")
        by_outcome[status] += 1
        by_subdomain[subdomain][status] += 1
        by_metric[metric][status] += 1

    decided = by_outcome.get("confirmed", 0) + by_outcome.get("refuted", 0)
    hit_rate_pct = round(100 * by_outcome.get("confirmed", 0) / decided, 1) if decided else None

    # Recent evaluations — last 10 by date, with prediction text from the
    # source PREDICTION# record when accessible.
    recent = []
    for l in learnings[:10]:
        pred_id = l.get("prediction_id", "")
        recent.append(
            {
                "date": l.get("date"),
                "subdomain": l.get("subdomain"),
                "metric": l.get("metric"),
                "status": l.get("status"),
                "reason": l.get("reason"),
                "prediction_id": pred_id,
            }
        )

    return {
        "coach_id": cid,
        "coach_name": COACH_NAMES.get(bare_cid, cid),
        "window_days": days,
        "subdomain_filter": subdomain_filter,
        "total_evaluations": len(learnings),
        "by_outcome": dict(by_outcome),
        "decided_count": decided,
        "hit_rate_pct": hit_rate_pct,
        "by_subdomain": {k: dict(v) for k, v in by_subdomain.items()},
        "by_metric": {k: dict(v) for k, v in by_metric.items()},
        "recent_evaluations": recent,
    }


def tool_evaluate_prediction(args):
    """Manually resolve a prediction — mark as confirmed or refuted."""
    prediction_id = args.get("prediction_id")
    status = args.get("status")
    outcome_note = args.get("outcome_note", "")

    if not prediction_id or not status:
        return {"error": "prediction_id and status (confirmed/refuted) required"}
    if status not in ("confirmed", "refuted"):
        return {"error": "status must be 'confirmed' or 'refuted'"}

    # Find the prediction across all coach threads
    for cid in COACH_IDS:
        try:
            # ADR-058: phase=pilot hidden by default.
            from mcp.core import _apply_phase_filter

            resp = table.query(
                **_apply_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq("USER#matthew") & Key("sk").begins_with(f"SOURCE#coach_thread#{cid}#"),
                        "ScanIndexForward": False,
                        "Limit": 10,
                    }
                )
            )
            for item in resp.get("Items", []):
                entry = decimal_to_float(item)
                for pred in entry.get("predictions", []):
                    if pred.get("prediction_id") == prediction_id:
                        pred["status"] = status
                        pred["outcome_note"] = outcome_note
                        pred["evaluated_at"] = datetime.now(timezone.utc).isoformat()
                        # Write back
                        import json
                        from decimal import Decimal

                        clean = json.loads(json.dumps(entry, default=str), parse_float=Decimal)
                        table.put_item(Item=clean)
                        return {
                            "success": True,
                            "prediction_id": prediction_id,
                            "coach_id": cid,
                            "status": status,
                            "outcome_note": outcome_note,
                        }
        except Exception:
            pass

    return {"error": f"Prediction {prediction_id} not found in any coach thread"}


def tool_get_coaching_summary(args):
    """High-level coaching dashboard data — all coaches' current state."""
    coaches = []
    for cid in COACH_IDS:
        try:
            # ADR-058: phase=pilot hidden by default.
            from mcp.core import _apply_phase_filter

            resp = table.query(
                **_apply_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq("USER#matthew") & Key("sk").begins_with(f"SOURCE#coach_thread#{cid}#"),
                        "ScanIndexForward": False,
                        "Limit": 1,
                    }
                )
            )
            items = resp.get("Items", [])
            if items:
                entry = decimal_to_float(items[0])
                pred_count = len(entry.get("predictions", []))
                pending = sum(1 for p in entry.get("predictions", []) if p.get("status") == "pending")
                coaches.append(
                    {
                        "coach_id": cid,
                        "coach_name": COACH_NAMES.get(cid, cid),
                        "position_summary": entry.get("position_summary", ""),
                        "emotional_investment": entry.get("emotional_investment", "observing"),
                        "prediction_count": pred_count,
                        "pending_predictions": pending,
                        "last_updated": entry.get("date"),
                        "open_questions": entry.get("open_questions", []),
                    }
                )
            else:
                coaches.append(
                    {
                        "coach_id": cid,
                        "coach_name": COACH_NAMES.get(cid, cid),
                        "position_summary": "No thread data yet",
                        "emotional_investment": "detached",
                        "prediction_count": 0,
                    }
                )
        except Exception:
            pass

    # Sort by emotional investment (most invested first)
    investment_order = {"concerned": 0, "invested": 1, "excited": 2, "engaged": 3, "observing": 4, "detached": 5}
    coaches.sort(key=lambda c: investment_order.get(c.get("emotional_investment", ""), 5))

    # Get integrator priority
    priority = None
    try:
        int_resp = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"})
        int_item = decimal_to_float(int_resp.get("Item", {}))
        if int_item.get("analysis"):
            priority = int_item["analysis"]
    except Exception:
        pass

    return {
        "coaches": coaches,
        "weekly_priority": priority,
        "total_coaches": len(coaches),
    }
