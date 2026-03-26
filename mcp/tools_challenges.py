"""
Challenge tools: create, activate, check-in, list, and complete challenges.

Challenges are distinct from experiments:
  - Experiments = science (hypothesis, controlled duration, published data)
  - Challenges  = action (participation invitation, gamification, habit-building)

Sources of challenges:
  1. journal_mining   — AI scans journal for recurring avoidance flags / themes
  2. data_signal      — Platform detects weak pillars, broken streaks, declining metrics
  3. hypothesis_graduate — Hypothesis engine confirms a pattern worth testing behaviourally
  4. science_scan     — AI suggests evidence-based challenges from current research
  5. manual           — Matthew creates one directly
  6. community        — Visitor suggests via site

DynamoDB schema:
  pk: USER#<user_id>#SOURCE#challenges
  sk: CHALLENGE#<slug>_<created_date>
"""
import re
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from boto3.dynamodb.conditions import Key

from mcp.config import (
    table, CHALLENGES_PK, EXPERIMENTS_PK, USER_ID, logger,
)
from mcp.core import decimal_to_float, get_profile

# ── Valid enums ──
VALID_SOURCES = [
    "journal_mining", "data_signal", "hypothesis_graduate",
    "science_scan", "manual", "community",
]
VALID_STATUSES = ["candidate", "active", "completed", "failed", "declined"]
VALID_DIFFICULTIES = ["easy", "moderate", "hard"]
VALID_DOMAINS = [
    "sleep", "movement", "nutrition", "supplements", "mental",
    "social", "discipline", "metabolic", "general",
]
VALID_VERIFICATION = ["self_report", "metric_auto", "hybrid"]


def _slug(name: str) -> str:
    """Generate a URL-safe slug from a challenge name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ═══════════════════════════════════════════════════════════════════════
# Tool 1: create_challenge
# ═══════════════════════════════════════════════════════════════════════

def tool_create_challenge(args):
    """Create a new challenge — manually or from an AI-generated candidate.

    Challenges start as 'candidate' by default. Use activate_challenge to start.
    If status='active' is passed, it starts immediately.
    """
    name = (args.get("name") or "").strip()
    if not name:
        raise ValueError("name is required.")

    catalog_id       = (args.get("catalog_id") or "").strip()
    description      = (args.get("description") or "").strip()
    source           = (args.get("source") or "manual").strip()
    source_detail    = (args.get("source_detail") or "").strip()
    domain           = (args.get("domain") or "general").strip()
    difficulty       = (args.get("difficulty") or "moderate").strip()
    duration_days    = args.get("duration_days", 7)
    protocol         = (args.get("protocol") or "").strip()
    success_criteria = (args.get("success_criteria") or "").strip()
    metric_targets   = args.get("metric_targets") or {}
    status           = (args.get("status") or "candidate").strip()
    verification     = (args.get("verification_method") or "self_report").strip()
    related_experiment = (args.get("related_experiment_id") or "").strip()
    tags             = args.get("tags") or []

    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid source '{source}'. Valid: {VALID_SOURCES}")
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError(f"Invalid difficulty '{difficulty}'. Valid: {VALID_DIFFICULTIES}")
    if domain not in VALID_DOMAINS:
        raise ValueError(f"Invalid domain '{domain}'. Valid: {VALID_DOMAINS}")
    if verification not in VALID_VERIFICATION:
        raise ValueError(f"Invalid verification_method. Valid: {VALID_VERIFICATION}")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Valid: {VALID_STATUSES}")

    duration_days = int(duration_days) if duration_days else 7
    if duration_days < 1 or duration_days > 365:
        raise ValueError("duration_days must be 1-365.")

    created_date = _today()
    slug = _slug(name)
    challenge_id = f"{slug}_{created_date}"
    sk = f"CHALLENGE#{challenge_id}"

    # Dedup check
    existing = table.get_item(Key={"pk": CHALLENGES_PK, "sk": sk}).get("Item")
    if existing:
        raise ValueError(f"Challenge '{challenge_id}' already exists.")

    item = {
        "pk":                   CHALLENGES_PK,
        "sk":                   sk,
        "challenge_id":         challenge_id,
        "catalog_id":           catalog_id,
        "name":                 name,
        "description":          description,
        "source":               source,
        "source_detail":        source_detail,
        "domain":               domain,
        "difficulty":           difficulty,
        "duration_days":        duration_days,
        "protocol":             protocol,
        "success_criteria":     success_criteria,
        "metric_targets":       metric_targets or {},
        "status":               status,
        "verification_method":  verification,
        "tags":                 tags,
        "daily_checkins":       [],
        "outcome":              "",
        "character_xp_awarded": 0,
        "badge_earned":         "",
        "related_experiment_id": related_experiment or "",
        "generated_by":         source,
        "generated_at":         _now_iso(),
        "activated_at":         _now_iso() if status == "active" else "",
        "completed_at":         "",
        "created_at":           _now_iso(),
    }

    # Convert for DynamoDB (Decimal)
    clean = {}
    for k, v in item.items():
        if isinstance(v, float):
            clean[k] = Decimal(str(v))
        elif isinstance(v, int) and not isinstance(v, bool):
            clean[k] = v
        elif v == "" or v == {} or v == []:
            # Keep empty strings/lists/dicts — they're meaningful placeholders
            clean[k] = v
        elif v is None:
            continue
        else:
            clean[k] = v

    table.put_item(Item=clean)
    logger.info(f"create_challenge: created {challenge_id} (source={source})")

    return {
        "created":        True,
        "challenge_id":   challenge_id,
        "name":           name,
        "status":         status,
        "source":         source,
        "domain":         domain,
        "difficulty":     difficulty,
        "duration_days":  duration_days,
        "protocol":       protocol,
    }


# ═══════════════════════════════════════════════════════════════════════
# Tool 2: activate_challenge
# ═══════════════════════════════════════════════════════════════════════

def tool_activate_challenge(args):
    """Activate a candidate challenge — transitions status from 'candidate' to 'active'."""
    challenge_id = (args.get("challenge_id") or "").strip()
    if not challenge_id:
        raise ValueError("challenge_id is required.")

    sk = f"CHALLENGE#{challenge_id}"
    item = table.get_item(Key={"pk": CHALLENGES_PK, "sk": sk}).get("Item")
    if not item:
        raise ValueError(f"Challenge '{challenge_id}' not found.")

    current_status = item.get("status", "")
    if current_status == "active":
        return {"already_active": True, "challenge_id": challenge_id}
    if current_status not in ("candidate", "declined"):
        raise ValueError(f"Cannot activate challenge with status '{current_status}'. Must be 'candidate' or 'declined'.")

    now = _now_iso()
    table.update_item(
        Key={"pk": CHALLENGES_PK, "sk": sk},
        UpdateExpression="SET #s = :s, activated_at = :a, daily_checkins = :dc",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "active",
            ":a": now,
            ":dc": [],  # Reset checkins on activation
        },
    )
    logger.info(f"activate_challenge: {challenge_id} → active")

    return {
        "activated":      True,
        "challenge_id":   challenge_id,
        "name":           item.get("name", ""),
        "duration_days":  decimal_to_float(item.get("duration_days", 7)),
        "activated_at":   now,
    }


# ═══════════════════════════════════════════════════════════════════════
# Phase E: Metric auto-verification
# ═══════════════════════════════════════════════════════════════════════

# Metric → DDB source + field mapping for auto-verification
AUTO_METRIC_MAP = {
    "daily_steps":         {"source": "apple",       "field": "steps"},
    "weight_lbs":          {"source": "withings",    "field": "weight_lbs"},
    "eating_window_hours": {"source": "macrofactor",  "field": "eating_window_hours"},
    "zone2_minutes":       {"source": "strava",       "field": "zone2_minutes"},
    "sleep_hours":         {"source": "whoop",        "field": "sleep_hours"},
    "hrv":                 {"source": "whoop",        "field": "hrv"},
    "calories":            {"source": "macrofactor",  "field": "calories"},
    "protein_g":           {"source": "macrofactor",  "field": "protein_g"},
}


def _check_metric_targets(metric_targets, date_str):
    """Auto-verify metric targets against DDB data for a given date.

    metric_targets: dict like {"daily_steps": {"min": 8000}, "sleep_hours": {"min": 7}}
    Returns: {"passed": bool, "results": {metric: {"target": ..., "actual": ..., "met": bool}}}
    """
    if not metric_targets:
        return {"passed": None, "results": {}}

    results = {}
    all_met = True

    for metric_key, target_spec in metric_targets.items():
        mapping = AUTO_METRIC_MAP.get(metric_key)
        if not mapping:
            results[metric_key] = {"target": target_spec, "actual": None, "met": None, "error": "unknown_metric"}
            continue

        source = mapping["source"]
        field = mapping["field"]
        pk = f"USER#{USER_ID}#SOURCE#{source}"
        sk = f"DATE#{date_str}"

        try:
            resp = table.get_item(Key={"pk": pk, "sk": sk})
            item = resp.get("Item")
            if not item:
                results[metric_key] = {"target": target_spec, "actual": None, "met": None, "error": "no_data"}
                all_met = False
                continue

            raw_val = item.get(field)
            if raw_val is None:
                results[metric_key] = {"target": target_spec, "actual": None, "met": None, "error": "field_missing"}
                all_met = False
                continue

            actual = float(decimal_to_float(raw_val))
            met = True

            # Support min, max, and exact targets
            if "min" in target_spec and actual < float(target_spec["min"]):
                met = False
            if "max" in target_spec and actual > float(target_spec["max"]):
                met = False
            if "exact" in target_spec and abs(actual - float(target_spec["exact"])) > 0.01:
                met = False

            if not met:
                all_met = False

            results[metric_key] = {
                "target": decimal_to_float(target_spec),
                "actual": round(actual, 2),
                "met":    met,
            }
        except Exception as e:
            logger.warning(f"Auto-verify {metric_key} failed: {e}")
            results[metric_key] = {"target": target_spec, "actual": None, "met": None, "error": str(e)}
            all_met = False

    return {"passed": all_met, "results": results}


# ═══════════════════════════════════════════════════════════════════════
# Tool 3: checkin_challenge
# ═══════════════════════════════════════════════════════════════════════

def tool_checkin_challenge(args):
    """Record a daily check-in for an active challenge.

    completed: true/false — did you do it today?
    note: optional reflection text
    rating: optional 1-5 difficulty rating
    date: optional YYYY-MM-DD (default today)
    """
    challenge_id = (args.get("challenge_id") or "").strip()
    if not challenge_id:
        raise ValueError("challenge_id is required.")

    completed = args.get("completed")
    if completed is None:
        raise ValueError("completed (true/false) is required.")
    completed = bool(completed)

    note = (args.get("note") or "").strip()
    rating = args.get("rating")
    date = (args.get("date") or "").strip() or _today()

    sk = f"CHALLENGE#{challenge_id}"
    item = table.get_item(Key={"pk": CHALLENGES_PK, "sk": sk}).get("Item")
    if not item:
        raise ValueError(f"Challenge '{challenge_id}' not found.")
    if item.get("status") != "active":
        raise ValueError(f"Challenge is not active (status: {item.get('status')}).")

    # Phase E: Auto-verification for metric_auto and hybrid challenges
    verification = item.get("verification_method", "self_report")
    metric_targets = item.get("metric_targets") or {}
    auto_result = None

    if verification in ("metric_auto", "hybrid") and metric_targets:
        auto_result = _check_metric_targets(metric_targets, date)
        if verification == "metric_auto":
            # Pure auto: metric result overrides manual input
            completed = auto_result["passed"] if auto_result["passed"] is not None else completed
        # hybrid: auto-check runs for data, but manual 'completed' flag is respected

    # Build checkin entry
    checkin = {
        "date":      date,
        "completed": completed,
        "logged_at": _now_iso(),
    }
    if auto_result:
        checkin["auto_verification"] = auto_result
    if note:
        checkin["note"] = note
    if rating is not None:
        checkin["rating"] = int(rating)

    # Check for duplicate date
    existing_checkins = item.get("daily_checkins", [])
    for i, ci in enumerate(existing_checkins):
        if ci.get("date") == date:
            # Replace existing checkin for this date
            existing_checkins[i] = checkin
            table.update_item(
                Key={"pk": CHALLENGES_PK, "sk": sk},
                UpdateExpression="SET daily_checkins = :dc",
                ExpressionAttributeValues={":dc": existing_checkins},
            )
            logger.info(f"checkin_challenge: {challenge_id} date={date} REPLACED")
            result = {
                "checked_in": True,
                "replaced":   True,
                "challenge_id": challenge_id,
                "date":       date,
                "completed":  completed,
                "total_checkins": len(existing_checkins),
            }
            if auto_result:
                result["auto_verification"] = auto_result
            return result

    # Append new checkin
    table.update_item(
        Key={"pk": CHALLENGES_PK, "sk": sk},
        UpdateExpression="SET daily_checkins = list_append(if_not_exists(daily_checkins, :empty), :ci)",
        ExpressionAttributeValues={
            ":ci":    [checkin],
            ":empty": [],
        },
    )

    total = len(existing_checkins) + 1
    duration = int(decimal_to_float(item.get("duration_days", 7)))
    days_remaining = max(0, duration - total)

    logger.info(f"checkin_challenge: {challenge_id} date={date} completed={completed}")

    result = {
        "checked_in":     True,
        "challenge_id":   challenge_id,
        "date":           date,
        "completed":      completed,
        "total_checkins": total,
        "duration_days":  duration,
        "days_remaining": days_remaining,
        "completion_pct": round(total / duration * 100) if duration else 0,
    }
    if auto_result:
        result["auto_verification"] = auto_result
    return result


# ═══════════════════════════════════════════════════════════════════════
# Tool 4: list_challenges
# ═══════════════════════════════════════════════════════════════════════

def tool_list_challenges(args):
    """List challenges with optional status filter.

    status: candidate, active, completed, failed, declined, or omit for all.
    source: filter by generation source (journal_mining, data_signal, etc.)
    domain: filter by pillar domain
    """
    status_filter = (args.get("status") or "").strip()
    source_filter = (args.get("source") or "").strip()
    domain_filter = (args.get("domain") or "").strip()
    limit = min(int(args.get("limit", 50)), 100)

    resp = table.query(
        KeyConditionExpression=(
            Key("pk").eq(CHALLENGES_PK) & Key("sk").begins_with("CHALLENGE#")
        ),
        ScanIndexForward=False,
    )
    items = resp.get("Items", [])

    # Apply filters
    if status_filter:
        items = [i for i in items if i.get("status") == status_filter]
    if source_filter:
        items = [i for i in items if i.get("source") == source_filter]
    if domain_filter:
        items = [i for i in items if i.get("domain") == domain_filter]

    # Compute live stats for active challenges
    result = []
    for item in items[:limit]:
        ch = decimal_to_float(item)
        # Remove DynamoDB keys from output
        ch.pop("pk", None)
        ch.pop("sk", None)

        # Compute progress for active challenges
        if ch.get("status") == "active":
            checkins = ch.get("daily_checkins", [])
            duration = int(ch.get("duration_days", 7))
            completed_days = sum(1 for c in checkins if c.get("completed"))
            # Overdue detection: activated_at + duration < today
            days_since_activation = 0
            overdue = False
            days_overdue = 0
            activated_at = ch.get("activated_at", "")
            if activated_at:
                try:
                    act_date = datetime.strptime(activated_at[:10], "%Y-%m-%d")
                    days_since_activation = (datetime.utcnow() - act_date).days
                    if days_since_activation >= duration:
                        overdue = True
                        days_overdue = days_since_activation - duration
                except Exception:
                    pass
            ch["progress"] = {
                "checkin_days":   len(checkins),
                "completed_days": completed_days,
                "duration_days":  duration,
                "completion_pct": round(len(checkins) / duration * 100) if duration else 0,
                "success_rate":   round(completed_days / len(checkins) * 100) if checkins else 0,
                "days_since_activation": days_since_activation,
                "overdue":        overdue,
                "days_overdue":   days_overdue,
            }

        result.append(ch)

    # Summary stats
    all_items = resp.get("Items", [])
    # Compute overdue count across all active items
    overdue_count = 0
    for ai in all_items:
        if ai.get("status") == "active":
            act_at = ai.get("activated_at", "")
            dur = int(decimal_to_float(ai.get("duration_days", 7)))
            if act_at:
                try:
                    ad = datetime.strptime(str(act_at)[:10], "%Y-%m-%d")
                    if (datetime.utcnow() - ad).days >= dur:
                        overdue_count += 1
                except Exception:
                    pass
    summary = {
        "total":     len(all_items),
        "candidate": sum(1 for i in all_items if i.get("status") == "candidate"),
        "active":    sum(1 for i in all_items if i.get("status") == "active"),
        "completed": sum(1 for i in all_items if i.get("status") == "completed"),
        "failed":    sum(1 for i in all_items if i.get("status") == "failed"),
        "declined":  sum(1 for i in all_items if i.get("status") == "declined"),
        "overdue":   overdue_count,
    }

    return {
        "challenges": result,
        "count":      len(result),
        "summary":    summary,
    }


# ═══════════════════════════════════════════════════════════════════════
# Tool 5: complete_challenge
# ═══════════════════════════════════════════════════════════════════════

def tool_complete_challenge(args):
    """End an active challenge and compute outcome.

    status: 'completed' (default) or 'failed'
    outcome: free-text summary of what happened
    reflection: what I'd do differently
    """
    challenge_id = (args.get("challenge_id") or "").strip()
    if not challenge_id:
        raise ValueError("challenge_id is required.")

    final_status = (args.get("status") or "completed").strip()
    if final_status not in ("completed", "failed"):
        raise ValueError("status must be 'completed' or 'failed'.")

    outcome    = (args.get("outcome") or "").strip()
    reflection = (args.get("reflection") or "").strip()

    sk = f"CHALLENGE#{challenge_id}"
    item = table.get_item(Key={"pk": CHALLENGES_PK, "sk": sk}).get("Item")
    if not item:
        raise ValueError(f"Challenge '{challenge_id}' not found.")
    if item.get("status") != "active":
        raise ValueError(f"Challenge is not active (status: {item.get('status')}).")

    # Compute completion stats
    checkins = item.get("daily_checkins", [])
    duration = int(decimal_to_float(item.get("duration_days", 7)))
    completed_days = sum(1 for c in checkins if c.get("completed"))
    success_rate = round(completed_days / len(checkins) * 100) if checkins else 0

    # XP calculation: base XP by difficulty × success rate
    xp_base = {"easy": 25, "moderate": 50, "hard": 100}
    difficulty = item.get("difficulty", "moderate")
    base = xp_base.get(difficulty, 50)

    # Only award XP if completed (not failed) and success rate > 50%
    xp_awarded = 0
    if final_status == "completed" and success_rate >= 50:
        xp_awarded = int(base * (success_rate / 100))
        # Bonus for perfect completion
        if success_rate == 100:
            xp_awarded = int(xp_awarded * 1.5)

    # Badge logic — simple tier badges
    badge = ""
    if final_status == "completed":
        # Count total completed challenges (including this one)
        all_resp = table.query(
            KeyConditionExpression=(
                Key("pk").eq(CHALLENGES_PK) & Key("sk").begins_with("CHALLENGE#")
            ),
        )
        completed_count = sum(
            1 for i in all_resp.get("Items", [])
            if i.get("status") == "completed"
        ) + 1  # +1 for this one about to be completed

        if completed_count == 1:
            badge = "first_challenge"
        elif completed_count == 5:
            badge = "five_challenges"
        elif completed_count == 10:
            badge = "ten_challenges"
        elif completed_count == 25:
            badge = "twenty_five_challenges"

        # Perfect completion badge
        if success_rate == 100 and duration >= 7:
            badge = badge or f"perfect_{duration}d"

    now = _now_iso()
    update_expr = (
        "SET #s = :s, completed_at = :ca, outcome = :o, "
        "character_xp_awarded = :xp, badge_earned = :badge"
    )
    expr_values = {
        ":s":     final_status,
        ":ca":    now,
        ":o":     outcome,
        ":xp":    xp_awarded,
        ":badge": badge,
    }
    if reflection:
        update_expr += ", reflection = :r"
        expr_values[":r"] = reflection

    table.update_item(
        Key={"pk": CHALLENGES_PK, "sk": sk},
        UpdateExpression=update_expr,
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=expr_values,
    )

    logger.info(
        f"complete_challenge: {challenge_id} → {final_status} "
        f"(success={success_rate}%, xp={xp_awarded}, badge={badge})"
    )

    return {
        "completed":         True,
        "challenge_id":      challenge_id,
        "name":              item.get("name", ""),
        "final_status":      final_status,
        "duration_days":     duration,
        "checkin_days":      len(checkins),
        "completed_days":    completed_days,
        "success_rate_pct":  success_rate,
        "character_xp_awarded": xp_awarded,
        "badge_earned":      badge or None,
        "completed_at":      now,
        "outcome":           outcome,
    }
