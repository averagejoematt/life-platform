"""
insight_writer.py — Shared Insight Ledger utility for all email/digest Lambdas.

Writes structured insight records to DynamoDB after each AI generation.
These records are the compounding substrate for IC-15 through IC-22:
  - Progressive Context: subsequent digests read recent high-value insights
  - Feedback Loop: effectiveness scores written back over time
  - Hypothesis Engine: cross-references insights for pattern discovery
  - Meta-Analysis: quarterly review of insight quality and coverage

DynamoDB key pattern:
  pk = USER#{user_id}#SOURCE#insights
  sk = INSIGHT#{ISO-timestamp}#{digest_type}

Bundled alongside each Lambda handler in its zip package.

Usage:
    import insight_writer
    insight_writer.init(table_resource, user_id)

    # After AI generation:
    insight_writer.write_insight(
        digest_type="daily_brief",
        insight_type="coaching",
        text="Sleep efficiency 71% — wind-down routine missed 5/7 days...",
        pillars=["sleep"],
        tags=["habit_gap", "causal_chain"],
        confidence="high",
        actionable=True,
        date="2026-03-07",
    )

    # Batch write after all AI calls:
    insight_writer.write_insights_batch(insights_list)

    # Read recent insights for context injection:
    recent = insight_writer.get_recent_insights(
        digest_type="daily_brief", days=14, pillars=["sleep", "movement"]
    )

v1.0.0 — 2026-03-07
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

# ── Module state (set by init) ──
_table = None
_USER_ID = "matthew"
_PK = None


def init(table_resource, user_id="matthew"):
    """Initialize with DynamoDB table resource and user ID. Call once at Lambda startup."""
    global _table, _USER_ID, _PK
    _table = table_resource
    _USER_ID = user_id
    _PK = f"USER#{user_id}#SOURCE#insights"


def _text_hash(text):
    """Short hash for deduplication — first 12 chars of SHA-256."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def write_insight(
    digest_type,
    insight_type,
    text,
    pillars=None,
    data_sources=None,
    tags=None,
    confidence="medium",
    actionable=False,
    date=None,
    component_scores=None,
    metadata=None,
):
    """Write a single insight record to DynamoDB.

    Args:
        digest_type: Origin Lambda — "daily_brief", "weekly_digest", "monthly_digest",
                     "chronicle", "nutrition_review", "weekly_plate"
        insight_type: "coaching" | "guidance" | "observation" | "alert" | "hypothesis"
        text: The insight text (truncated to 800 chars)
        pillars: List of pillar names this insight touches (e.g. ["sleep", "nutrition"])
        data_sources: List of data sources that contributed (e.g. ["whoop", "habitify"])
        tags: Semantic tags for retrieval (e.g. ["habit_gap", "causal_chain", "milestone"])
        confidence: "high" | "medium" | "low"
        actionable: Whether this insight suggests a specific action
        date: The date this insight is about (YYYY-MM-DD), defaults to today
        component_scores: Optional dict of day grade component scores at time of insight
        metadata: Optional dict of additional metadata

    Returns:
        The written record, or None if write fails.
    """
    if not _table:
        logger.warning("[insight_writer] Not initialized — call init() first")
        return None

    if not text or len(text.strip()) < 10:
        return None  # Skip trivially short insights

    ts = _now_iso()
    truncated = text[:800]
    thash = _text_hash(truncated)

    item = {
        "pk": _PK,
        "sk": f"INSIGHT#{ts}#{digest_type}",
        "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "digest_type": digest_type,
        "insight_type": insight_type,
        "text": truncated,
        "text_hash": thash,
        "pillars": pillars or [],
        "data_sources": data_sources or [],
        "tags": tags or [],
        "confidence": confidence,
        "actionable": actionable,
        "effectiveness": None,  # Populated by IC-12 feedback loop later
        "ttl": int(time.time()) + (180 * 86400),  # 180-day TTL
    }

    if component_scores:
        # Store as snapshot for later correlation
        item["component_scores"] = json.loads(json.dumps(component_scores, default=str))

    if metadata:
        item["metadata"] = json.loads(json.dumps(metadata, default=str))

    try:
        _table.put_item(Item=json.loads(json.dumps(item, default=str), parse_float=Decimal))
        logger.info("[insight_writer] Wrote insight: %s / %s / %s", digest_type, insight_type, thash)
        return item
    except Exception as e:
        logger.error("[insight_writer] Failed to write insight — context degradation: %s", e)
        return None  # Returns None so callers can count failures; logged as ERROR for monitoring


def write_insights_batch(insights):
    """Write multiple insight records. Each item is a dict of kwargs for write_insight().

    Non-fatal — logs and continues on individual failures.
    Returns count of successfully written records.
    """
    if not insights:
        return 0

    count = 0
    for ins in insights:
        result = write_insight(**ins)
        if result:
            count += 1
        # Small delay to avoid hot partition
        if len(insights) > 5:
            time.sleep(0.05)

    logger.info("[insight_writer] Batch: %d/%d written", count, len(insights))
    return count


def get_recent_insights(digest_type=None, days=14, pillars=None, max_results=20):
    """Retrieve recent insights for context injection into AI prompts.

    Args:
        digest_type: Filter by origin Lambda (None = all)
        days: Look back this many days
        pillars: Filter to insights touching any of these pillars (None = all)
        max_results: Cap on returned records

    Returns:
        List of insight dicts, newest first.
    """
    if not _table:
        logger.warning("[insight_writer] Not initialized — call init() first")
        return []

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        # Query all insights, filter by date
        # SK prefix INSIGHT# sorts chronologically
        from boto3.dynamodb.conditions import Key, Attr

        kwargs = {
            "KeyConditionExpression": Key("pk").eq(_PK) & Key("sk").begins_with("INSIGHT#"),
            "ScanIndexForward": False,  # Newest first
            "Limit": max_results * 3,  # Over-fetch to allow filtering
        }

        resp = _table.query(**kwargs)
        items = resp.get("Items", [])

        # Filter by date cutoff
        items = [i for i in items if i.get("date", "") >= cutoff_date]

        # Filter by digest_type if specified
        if digest_type:
            items = [i for i in items if i.get("digest_type") == digest_type]

        # Filter by pillars if specified (any overlap)
        if pillars:
            pillar_set = set(pillars)
            items = [i for i in items if set(i.get("pillars", [])) & pillar_set]

        return items[:max_results]

    except Exception as e:
        logger.warning("[insight_writer] Failed to read insights: %s", e)
        return []


def build_insights_context(days=14, pillars=None, max_items=5, label="PREVIOUS INSIGHTS"):
    """Build a compact context string from recent insights for prompt injection.

    Returns empty string if no insights found — zero prompt bloat when ledger is empty.
    """
    items = get_recent_insights(days=days, pillars=pillars, max_results=max_items)

    if not items:
        return ""

    lines = [f"{label} (last {days} days, {len(items)} records):"]
    for item in items:
        date = item.get("date", "?")
        dtype = item.get("digest_type", "?")
        text = item.get("text", "")[:200]
        eff = item.get("effectiveness")
        eff_str = f" [effectiveness: {eff}]" if eff is not None else ""
        lines.append(f"  [{date} / {dtype}] {text}{eff_str}")

    lines.append("INSTRUCTION: Reference previous insights when today's data confirms or contradicts them. "
                 "Build on patterns already identified — don't rediscover the same insight.")
    return "\n".join(lines)


def _extract_pillars_from_text(text):
    """Best-effort pillar extraction from insight text."""
    text_lower = text.lower()
    pillars = []
    pillar_keywords = {
        "sleep": ["sleep", "hrv", "recovery", "bedtime", "wind-down", "rem", "deep sleep"],
        "movement": ["training", "exercise", "walk", "zone 2", "steps", "workout", "strain"],
        "nutrition": ["protein", "calories", "cal", "macro", "meal", "food", "eating", "deficit"],
        "mind": ["journal", "mood", "stress", "meditation", "energy", "mental"],
        "metabolic": ["glucose", "weight", "metabolic", "cgm", "blood sugar", "bp"],
        "consistency": ["habit", "streak", "routine", "consistency", "tier 0"],
        "relationships": ["social", "contact", "connection", "relationship"],
    }
    for pillar, keywords in pillar_keywords.items():
        if any(kw in text_lower for kw in keywords):
            pillars.append(pillar)
    return pillars or ["general"]


def extract_daily_brief_insights(bod_insight, tldr_guidance, training_nutrition,
                                  journal_coach_text, date, component_scores=None):
    """Extract structured insights from Daily Brief AI outputs.

    Returns a list of dicts ready for write_insights_batch().
    Called after all AI calls complete in the daily brief Lambda.
    """
    insights = []

    # BoD coaching insight
    if bod_insight and len(bod_insight) > 15:
        insights.append({
            "digest_type": "daily_brief",
            "insight_type": "coaching",
            "text": bod_insight,
            "pillars": _extract_pillars_from_text(bod_insight),
            "tags": ["bod", "coaching"],
            "confidence": "high",
            "actionable": False,
            "date": date,
            "component_scores": component_scores,
        })

    # TL;DR
    tldr_text = tldr_guidance.get("tldr", "") if isinstance(tldr_guidance, dict) else ""
    if tldr_text and len(tldr_text) > 10:
        insights.append({
            "digest_type": "daily_brief",
            "insight_type": "observation",
            "text": tldr_text,
            "pillars": _extract_pillars_from_text(tldr_text),
            "tags": ["tldr", "summary"],
            "confidence": "high",
            "actionable": False,
            "date": date,
        })

    # Guidance items (each is actionable)
    guidance = tldr_guidance.get("guidance", []) if isinstance(tldr_guidance, dict) else []
    for g_item in guidance:
        if isinstance(g_item, str) and len(g_item) > 10:
            insights.append({
                "digest_type": "daily_brief",
                "insight_type": "guidance",
                "text": g_item,
                "pillars": _extract_pillars_from_text(g_item),
                "tags": ["guidance", "actionable"],
                "confidence": "medium",
                "actionable": True,
                "date": date,
            })

    # Training coach
    training_text = training_nutrition.get("training", "") if isinstance(training_nutrition, dict) else ""
    if training_text and len(training_text) > 15:
        insights.append({
            "digest_type": "daily_brief",
            "insight_type": "coaching",
            "text": training_text,
            "pillars": ["movement"],
            "data_sources": ["strava", "garmin", "whoop"],
            "tags": ["training", "coaching"],
            "confidence": "medium",
            "actionable": False,
            "date": date,
        })

    # Nutrition coach
    nutrition_text = training_nutrition.get("nutrition", "") if isinstance(training_nutrition, dict) else ""
    if nutrition_text and len(nutrition_text) > 15:
        insights.append({
            "digest_type": "daily_brief",
            "insight_type": "coaching",
            "text": nutrition_text,
            "pillars": ["nutrition"],
            "data_sources": ["macrofactor"],
            "tags": ["nutrition", "coaching"],
            "confidence": "medium",
            "actionable": True,
            "date": date,
        })

    # Journal coach
    if journal_coach_text and len(journal_coach_text) > 15:
        insights.append({
            "digest_type": "daily_brief",
            "insight_type": "coaching",
            "text": journal_coach_text,
            "pillars": ["mind"],
            "data_sources": ["journal"],
            "tags": ["journal", "coaching", "mind"],
            "confidence": "medium",
            "actionable": True,
            "date": date,
        })

    return insights
