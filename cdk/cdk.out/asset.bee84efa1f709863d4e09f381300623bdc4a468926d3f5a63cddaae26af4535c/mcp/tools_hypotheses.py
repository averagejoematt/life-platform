"""
tools_hypotheses.py — IC-18: Cross-Domain Hypothesis Engine MCP Tools

2 tools:
  get_hypotheses            — list/filter active hypotheses by status, domain
  update_hypothesis_outcome — record a confirming or refuting observation
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from mcp.db import get_table
from mcp.config import USER_ID

HYPOTHESES_PK = f"USER#{USER_ID}#SOURCE#hypotheses"


def _d2f(obj):
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# get_hypotheses
# ─────────────────────────────────────────────────────────────────────────────

def tool_get_hypotheses(status=None, domain=None, days=90, include_archived=False):
    """IC-18: List cross-domain hypotheses. Optionally filter by status or domain."""
    table = get_table()
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": HYPOTHESES_PK,
                ":prefix": "HYPOTHESIS#",
            },
            ScanIndexForward=False,
            Limit=100,
        )
    except Exception as e:
        return {"error": f"DDB query failed: {e}"}

    items = [_d2f(i) for i in resp.get("Items", [])]

    # Date filter
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    items = [i for i in items if i.get("created_at", "")[:10] >= cutoff]

    # Status filter
    if not include_archived:
        items = [i for i in items if i.get("status") != "archived"]
    if status:
        items = [i for i in items if i.get("status") == status]

    # Domain filter
    if domain:
        items = [i for i in items if domain.lower() in [d.lower() for d in i.get("domains", [])]]

    # Sort: confirmed first, then confirming, then pending, then refuted
    status_order = {"confirmed": 0, "confirming": 1, "pending": 2, "refuted": 3, "archived": 4}
    items.sort(key=lambda x: (status_order.get(x.get("status", "pending"), 5), x.get("created_at", "")))

    status_counts = {}
    for item in items:
        s = item.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    formatted = []
    for h in items:
        formatted.append({
            "sk": h.get("sk", ""),
            "hypothesis_id": h.get("hypothesis_id", ""),
            "hypothesis": h.get("hypothesis", ""),
            "status": h.get("status", "pending"),
            "domains": h.get("domains", []),
            "confidence": h.get("confidence", "low"),
            "evidence": h.get("evidence", ""),
            "confirmation_criteria": h.get("confirmation_criteria", ""),
            "actionable_if_confirmed": h.get("actionable_if_confirmed", ""),
            "monitoring_window_days": h.get("monitoring_window_days", 21),
            "check_count": h.get("check_count", 0),
            "created_at": h.get("created_at", "")[:10],
            "last_checked": h.get("last_checked", "")[:10],
            "evidence_log": h.get("evidence_log", []),
        })

    return {
        "total": len(formatted),
        "status_summary": status_counts,
        "hypotheses": formatted,
        "note": (
            "Generated weekly by hypothesis-engine Lambda (Sunday 11 AM PT). "
            "Lifecycle: pending -> confirming -> confirmed (or refuted). "
            "Confirmed hypotheses flow into AI coaching via platform_memory. "
            "Use update_hypothesis_outcome to record manual observations."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# update_hypothesis_outcome
# ─────────────────────────────────────────────────────────────────────────────

def tool_update_hypothesis_outcome(sk, verdict, evidence_note="", effectiveness=None):
    """IC-18: Record a confirming or refuting observation for a hypothesis.

    Args:
        sk:             Sort key from get_hypotheses (starts with 'HYPOTHESIS#')
        verdict:        'confirming' | 'confirmed' | 'refuted' | 'insufficient' | 'archived'
        evidence_note:  What you observed (free text)
        effectiveness:  Optional 1-5 strength of evidence (5=very strong)
    """
    if not sk or not sk.startswith("HYPOTHESIS#"):
        return {"error": "Invalid sk. Must start with 'HYPOTHESIS#' (from get_hypotheses output)."}

    valid_verdicts = ("confirming", "confirmed", "refuted", "insufficient", "archived")
    if verdict not in valid_verdicts:
        return {"error": f"verdict must be one of: {valid_verdicts}"}

    table = get_table()
    now = datetime.now(timezone.utc)

    log_entry = {
        "date": now.date().isoformat(),
        "verdict": verdict,
        "note": evidence_note[:500] if evidence_note else "",
        "source": "manual_mcp",
    }
    if effectiveness is not None:
        log_entry["effectiveness"] = effectiveness

    status_map = {
        "confirming":   "confirming",
        "confirmed":    "confirmed",
        "refuted":      "refuted",
        "insufficient": None,
        "archived":     "archived",
    }
    new_status = status_map.get(verdict)

    try:
        existing = table.get_item(Key={"pk": HYPOTHESES_PK, "sk": sk})
        item = _d2f(existing.get("Item", {}))
        check_count = int(item.get("check_count", 0))

        # Auto-promote to confirmed after 3 confirming checks
        if verdict == "confirming" and check_count >= 2:
            new_status = "confirmed"

        update_expr = (
            "SET last_checked = :lc, check_count = check_count + :one, "
            "evidence_log = list_append(if_not_exists(evidence_log, :empty), :ev)"
        )
        expr_vals = {":lc": now.isoformat(), ":one": 1, ":empty": [], ":ev": [log_entry]}

        if new_status:
            update_expr += ", #s = :s"
            expr_vals[":s"] = new_status

        table.update_item(
            Key={"pk": HYPOTHESES_PK, "sk": sk},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={"#s": "status"} if new_status else {},
            ExpressionAttributeValues=expr_vals,
        )

        final_status = new_status or item.get("status", "pending")
        msg = f"Updated to '{final_status}'."
        if final_status == "confirmed":
            msg += " Confirmed — will flow into AI coaching via platform_memory."
        elif final_status == "refuted":
            msg += " Refuted — will be archived after next hypothesis-engine run."

        return {
            "updated": True,
            "sk": sk,
            "verdict": verdict,
            "new_status": final_status,
            "evidence_note": evidence_note,
            "message": msg,
        }

    except Exception as e:
        return {"error": f"Update failed: {e}"}
