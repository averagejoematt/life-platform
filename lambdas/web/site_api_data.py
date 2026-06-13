"""
lambdas/web/site_api_data.py — domain-data endpoint handlers.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 6, 2026-05-26).

Endpoints in this module:
  /api/glucose, /api/sleep_detail
  /api/habits, /api/habit_streaks, /api/habit_registry
  /api/correlations, /api/genome_risks
  /api/observatory_week, /api/changes-since
  /api/supplements, /api/vice_streaks, /api/experiments
  /api/ledger, /api/discoveries
  /api/status/summary (footer dot)
  /api/labs, /api/protocols
  /api/tools_baseline, /api/platform_stats, /api/domains
"""

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal  # noqa: F401

import boto3
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058

from web.site_api_common import (
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    EXPERIMENT_START,
    PLATFORM_STATS,
    PT,
    S3_REGION,
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _experiment_date,
    _get_profile,
    _is_blocked_vice,
    _latest_item,
    _load_s3_json,
    _load_supp_metadata,
    _ok,
    _query_source,
    logger,
    table,
)

# Module-owned S3 config caches (read by handle_protocols + handle_domains)
_protocols_cache = None
_domains_cache = None


def handle_tools_baseline() -> dict:
    """
    GET /api/tools_baseline
    Returns baseline (first week of experiment) and current values for the
    Tools page comparison badges: RHR, HRV, sleep quality, weight.
    Cache: 3600s — baseline is fixed, current shifts slowly.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Baseline: first 7 days of the experiment
    baseline_end = (datetime.strptime(EXPERIMENT_START, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")

    # Current: last 7 days
    d7 = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    baseline_whoop = _query_source("whoop", EXPERIMENT_START, baseline_end)
    current_whoop = _query_source("whoop", d7, today)

    def first_val(records, field):
        """First non-null value from sorted records."""
        for r in sorted(records, key=lambda x: x.get("sk", "")):
            if r.get(field) is not None:
                return round(float(r[field]), 1)
        return None

    def avg_val(records, field):
        """Average of non-null values."""
        vals = [float(r[field]) for r in records if r.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    baseline = {
        "rhr_bpm": first_val(baseline_whoop, "resting_heart_rate"),
        "hrv_ms": first_val(baseline_whoop, "hrv"),
        "sleep_score": first_val(baseline_whoop, "sleep_quality_score"),
        "sleep_hours": first_val(baseline_whoop, "sleep_duration_hours"),
    }
    current = {
        "rhr_bpm": avg_val(current_whoop, "resting_heart_rate"),
        "hrv_ms": avg_val(current_whoop, "hrv"),
        "sleep_score": avg_val(current_whoop, "sleep_quality_score"),
        "sleep_hours": avg_val(current_whoop, "sleep_duration_hours"),
    }

    # Weight — baseline uses EXPERIMENT_BASELINE_WEIGHT_LBS (ADR-058: May 18 Withings reading)
    _p = _get_profile()
    baseline["weight_lbs"] = float(_p.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))

    latest_withings = _latest_item("withings")
    current["weight_lbs"] = round(float(latest_withings["weight_lbs"])) if latest_withings and latest_withings.get("weight_lbs") else None

    return _ok(
        {
            "baseline": baseline,
            "baseline_date": EXPERIMENT_START,
            "current": current,
            "current_date": today,
        },
        cache_seconds=3600,
    )


def handle_platform_stats() -> dict:
    """GET /api/platform_stats — authoritative platform counts for all site pages."""
    return _ok(PLATFORM_STATS, cache_seconds=3600)


# ── Source freshness (public pipeline-status feed) ──────────────────────────
# Mirrors lambdas/emails/freshness_checker_lambda.py (SOURCES / SOURCE_STALE_HOURS /
# BEHAVIORAL_SOURCES / paused list). KEEP IN SYNC if sources are added/paused there.
# Active = ingested into DATE# records; paused = intentionally off (shown, never "stale").
_FRESHNESS_SOURCES = {
    "whoop": {"label": "Whoop", "desc": "Recovery, sleep, HRV", "category": "Wearables"},
    "withings": {"label": "Withings", "desc": "Weight & body composition", "category": "Wearables"},
    "eightsleep": {"label": "Eight Sleep", "desc": "Sleep stages, HR, HRV", "category": "Wearables"},
    "apple_health": {"label": "Apple Health", "desc": "Steps & active energy", "category": "Wearables"},
    "habitify": {"label": "Habitify", "desc": "Daily habit completions", "category": "Inputs"},
    "todoist": {"label": "Todoist", "desc": "Tasks completed", "category": "Inputs"},
    "measurements": {"label": "Tape measure", "desc": "Body measurements", "category": "Manual logs", "behavioral": True},
    "food_delivery": {"label": "Food delivery", "desc": "Delivery behavioral signal", "category": "Manual logs", "behavioral": True},
}
# Per-source stale thresholds in hours (default 48). Mirrors SOURCE_STALE_HOURS.
_FRESHNESS_STALE_HOURS = {"withings": 7 * 24, "todoist": 48, "measurements": 60 * 24, "food_delivery": 90 * 24}
_FRESHNESS_DEFAULT_STALE_HOURS = 48
# Intentionally paused — reported as status "paused", never counted stale (ADR-074 etc.).
_FRESHNESS_PAUSED = {
    "garmin": {"label": "Garmin", "desc": "Biometrics — paused (vendor anti-automation, ADR-074)", "category": "Wearables"},
    "strava": {"label": "Strava", "desc": "Activities — paused (API 402)", "category": "Wearables"},
    "macrofactor": {"label": "MacroFactor", "desc": "Nutrition — retired (Firebase App Check)", "category": "Manual logs"},
}


def _latest_date_str(source: str) -> str | None:
    """Latest YYYY-MM-DD among a source's DATE# records, or None.

    Uses begins_with('DATE#') so non-DATE sort keys (e.g. measurements' YEAR# rollup)
    don't shadow the real latest day. Projects sk only — cheap.
    """
    kwargs = with_phase_filter(
        {
            "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}{source}") & Key("sk").begins_with("DATE#"),
            "ScanIndexForward": False,
            "Limit": 1,
            "ProjectionExpression": "sk",
        }
    )
    items = table.query(**kwargs).get("Items", [])
    if not items:
        return None
    return str(items[0]["sk"]).replace("DATE#", "")[:10]


def handle_source_freshness() -> dict:
    """GET /api/source_freshness — live pipeline status per data source.

    status ∈ {fresh, stale, behavioral-stale, paused}. Behavioral sources (manual
    logs) report "behavioral-stale" rather than "stale" so a lapse in logging never
    reads as a broken pipeline. Always a shaped 200 — sparse/empty data still renders.
    """
    now = datetime.now(timezone.utc)
    sources = []
    summary = {"fresh": 0, "stale": 0, "paused": 0, "total": 0}

    for sid, meta in _FRESHNESS_SOURCES.items():
        last_update = None
        age_hours = None
        status = "stale"
        try:
            date_str = _latest_date_str(sid)
            if date_str:
                last_update = date_str
                last_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age_hours = round((now - last_dt).total_seconds() / 3600, 1)
                threshold = _FRESHNESS_STALE_HOURS.get(sid, _FRESHNESS_DEFAULT_STALE_HOURS)
                if age_hours <= threshold:
                    status = "fresh"
                elif meta.get("behavioral"):
                    status = "behavioral-stale"
                else:
                    status = "stale"
            elif meta.get("behavioral"):
                status = "behavioral-stale"
        except Exception as e:  # never let one source break the feed
            logger.warning("source_freshness: %s failed: %s", sid, e)
            status = "unknown"
        sources.append(
            {
                "id": sid,
                "label": meta["label"],
                "desc": meta["desc"],
                "category": meta["category"],
                "last_update": last_update,
                "age_hours": age_hours,
                "status": status,
                "is_behavioral": bool(meta.get("behavioral")),
            }
        )
        summary["total"] += 1
        if status == "fresh":
            summary["fresh"] += 1
        elif status in ("stale", "behavioral-stale", "unknown"):
            summary["stale"] += 1

    for sid, meta in _FRESHNESS_PAUSED.items():
        sources.append(
            {
                "id": sid,
                "label": meta["label"],
                "desc": meta["desc"],
                "category": meta["category"],
                "last_update": None,
                "age_hours": None,
                "status": "paused",
                "is_behavioral": False,
            }
        )
        summary["paused"] += 1
        summary["total"] += 1

    return _ok({"sources": sources, "summary": summary}, cache_seconds=300)


def handle_ledger() -> dict:
    """
    GET /api/ledger
    Returns: Ledger transactions (by event and by cause) + running totals.
    Source: ledger DynamoDB partition + config/ledger.json from S3.
    Cache: 3600s.
    """
    ledger_pk = f"{USER_PREFIX}ledger"

    # 1. Fetch TOTALS#current
    totals_resp = table.get_item(Key={"pk": ledger_pk, "sk": "TOTALS#current"})
    totals_item = _decimal_to_float(totals_resp.get("Item", {}))

    totals = {
        "total_donated_usd": totals_item.get("total_donated_usd", 0),
        "total_bounties_usd": totals_item.get("total_bounties_usd", 0),
        "total_punishments_usd": totals_item.get("total_punishments_usd", 0),
        "bounty_count": totals_item.get("bounty_count", 0),
        "punishment_count": totals_item.get("punishment_count", 0),
    }

    # 2. Fetch LEDGER# transaction records
    txn_resp = table.query(
        KeyConditionExpression=Key("pk").eq(ledger_pk) & Key("sk").begins_with("LEDGER#"),
        ScanIndexForward=False,
        Limit=200,
    )
    txn_items = _decimal_to_float(txn_resp.get("Items", []))

    earned = []
    reluctant = []
    for txn in txn_items:
        entry = {
            "ledger_id": txn.get("sk", "").replace("LEDGER#", ""),
            "date": txn.get("date", ""),
            "source_type": txn.get("source_type", ""),
            "source_id": txn.get("source_id", ""),
            "source_name": txn.get("source_name", ""),
            "outcome": txn.get("outcome", ""),
            "amount_usd": txn.get("amount_usd", 0),
            "cause_id": txn.get("cause_id", ""),
            "cause_name": txn.get("cause_name", ""),
        }
        if txn.get("type") == "punishment" or txn.get("outcome") in ("abandoned", "failed"):
            reluctant.append(entry)
        else:
            earned.append(entry)

    # 3. Fetch config/ledger.json from S3 for display metadata
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3_client = boto3.client("s3", region_name=S3_REGION)
        s3_resp = s3_client.get_object(Bucket=S3_BUCKET, Key="config/ledger.json")
        ledger_config = json.loads(s3_resp["Body"].read())
    except Exception:
        ledger_config = {"earned_causes": [], "reluctant_causes": []}

    # 4. Build by_cause with merged metadata
    by_cause_raw = totals_item.get("by_cause", {})
    earned_causes = []
    for cause_cfg in ledger_config.get("earned_causes", []):
        cid = cause_cfg.get("id", "")
        cause_data = by_cause_raw.get(cid, {})
        earned_causes.append(
            {
                **cause_cfg,
                "total_usd": cause_data.get("total_usd", 0),
                "count": cause_data.get("count", 0),
            }
        )

    reluctant_causes = []
    for cause_cfg in ledger_config.get("reluctant_causes", []):
        cid = cause_cfg.get("id", "")
        cause_data = by_cause_raw.get(cid, {})
        reluctant_causes.append(
            {
                **cause_cfg,
                "total_usd": cause_data.get("total_usd", 0),
                "count": cause_data.get("count", 0),
            }
        )

    return _ok(
        {
            "totals": totals,
            "by_event": {"earned": earned, "reluctant": reluctant},
            "by_cause": {"earned_causes": earned_causes, "reluctant_causes": reluctant_causes},
        },
        cache_seconds=3600,
    )


def handle_discoveries() -> dict:
    """
    GET /api/discoveries
    Returns structured content for the Discoveries page:
    - active_hypotheses: from experiment_library S3 config (active experiments)
    - inner_life: from insights partition (chronicle observations)
    - ai_findings: from weekly_correlations (FDR-significant pairs)
    Cache: 1800s (30 min).
    """
    # ── 1. Active hypotheses from experiment library ──
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    active_hypotheses = []
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key="config/experiment_library.json")
        lib = json.loads(obj["Body"].read())
        for exp in lib.get("experiments", []):
            if exp.get("status") != "active":
                continue
            active_hypotheses.append(
                {
                    "name": exp.get("name", ""),
                    "description": exp.get("description", ""),
                    "hypothesis": exp.get("hypothesis_template", ""),
                    "protocol": exp.get("protocol_template", ""),
                    "pillar": exp.get("pillar", ""),
                    "evidence_tier": exp.get("evidence_tier", ""),
                    "metrics": exp.get("metrics_measurable", []),
                    "duration_days": exp.get("suggested_duration_days"),
                    "why": exp.get("why_it_matters", ""),
                    "evidence_for": exp.get("evidence_for", []),
                    "evidence_against": exp.get("evidence_against", []),
                    "rationale": exp.get("rationale", ""),
                }
            )
    except Exception as e:
        logger.warning(f"[discoveries] experiment library read failed: {e}")

    # ── 2. Inner life observations from insights partition ──
    inner_life = []
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot insights
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}insights"),
                    "ScanIndexForward": False,
                    "Limit": 50,
                }
            )
        )
        for item in _decimal_to_float(resp.get("Items", [])):
            digest_type = item.get("digest_type", "")
            insight_type = item.get("insight_type", "")
            date = item.get("date", "")
            # Chronicle observations are AI narrative findings
            if digest_type == "chronicle" and insight_type == "observation":
                category = "Journal Breakthrough"
            elif digest_type == "weekly_digest":
                category = "Weekly Pattern"
            elif digest_type == "monday_compass":
                category = "Coaching Insight"
            elif digest_type == "weekly_plate":
                category = "Nutrition Pattern"
            else:
                continue

            # Extract a clean title from the HTML text
            text = item.get("text", "")
            title = ""
            # Try to find a heading in the HTML
            import re

            heading_match = re.search(r"font-weight:\s*7[0-9]{2}[^>]*>([^<]{10,80})<", text)
            if heading_match:
                title = heading_match.group(1).strip()
            if not title:
                # Fall back to first substantial text
                text_match = re.search(r">([A-Z][^<]{20,100})<", text)
                if text_match:
                    title = text_match.group(1).strip()
            if not title:
                title = f"{category} — {date}"

            # Extract a body snippet
            body = ""
            # Find first paragraph-like content
            para_match = re.search(r"font-size:\s*1[3-5]px[^>]*>([^<]{30,200})<", text)
            if para_match:
                body = para_match.group(1).strip()

            inner_life.append(
                {
                    "date": date,
                    "category": category,
                    "title": title,
                    "body": body,
                    "confidence": item.get("confidence", ""),
                    "actionable": item.get("actionable", False),
                    "pillars": item.get("pillars", []),
                }
            )

        # Dedupe by title, keep most recent
        seen_titles = set()
        deduped = []
        for il in inner_life:
            if il["title"] not in seen_titles:
                seen_titles.add(il["title"])
                deduped.append(il)
        inner_life = deduped[:12]  # Cap at 12 cards
    except Exception as e:
        logger.warning(f"[discoveries] insights read failed: {e}")

    # ── 3. AI findings from weekly correlations ──
    ai_findings = []
    try:
        corr_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot correlations
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}weekly_correlations"),
                    "ScanIndexForward": False,
                    "Limit": 4,
                }
            )
        )
        _LABELS = {
            "hrv": "HRV",
            "recovery_score": "Recovery",
            "sleep_duration": "Sleep Duration",
            "sleep_score": "Sleep Score",
            "resting_hr": "Resting HR",
            "strain": "Strain",
            "training_kj": "Training Load",
            "protein_g": "Protein",
            "calories": "Calories",
            "steps": "Steps",
            "habit_pct": "Habit Completion",
            "day_grade": "Day Grade",
        }
        for item in _decimal_to_float(corr_resp.get("Items", [])):
            week = item.get("week", item.get("sk", "").replace("WEEK#", ""))
            corrs = item.get("correlations", [])
            if isinstance(corrs, str):
                try:
                    corrs = json.loads(corrs)
                except (json.JSONDecodeError, TypeError):
                    corrs = []
            if not isinstance(corrs, list):
                continue
            for c in corrs:
                if not (c.get("fdr_significant") or c.get("significant")):
                    continue
                a = _LABELS.get(c.get("metric_a", ""), c.get("metric_a", ""))
                b = _LABELS.get(c.get("metric_b", ""), c.get("metric_b", ""))
                r = c.get("r", 0)
                direction = "positively" if r > 0 else "negatively"
                ai_findings.append(
                    {
                        "week": week,
                        "metric_a": a,
                        "metric_b": b,
                        "r": round(r, 2) if r else 0,
                        "n": c.get("n", 0),
                        "title": f"{a} × {b}: {direction} correlated",
                        "body": f"r={r:+.2f}, n={c.get('n', '?')} days. " f"FDR-corrected significant finding from {week}.",
                    }
                )
    except Exception as e:
        logger.warning(f"[discoveries] correlations read failed: {e}")

    return _ok(
        {
            "active_hypotheses": active_hypotheses,
            "inner_life": inner_life,
            "ai_findings": ai_findings,
        },
        cache_seconds=1800,
    )


def handle_habit_streaks() -> dict:
    """
    GET /api/habit_streaks
    Returns: Tier 0 habit streaks for public display (aggregate streak only, no habit names).
    Cache: 3600s (1 hr).
    """
    datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Read latest habit_scores record
    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": pk},
                "ScanIndexForward": False,
                "Limit": 3,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))
    record = items[0] if items else None

    if not record:
        # Genesis week — shaped-empty 200 (the Essential-Seven badge shows 0, not an error).
        return _ok(
            {"habit_streaks": {"as_of_date": yesterday, "tier0_pct": 0, "tier0_done": 0, "tier0_total": 1, "aggregate_streak": 0}},
            cache_seconds=300,
        )

    t0_done = int(record.get("tier0_done", 0))
    t0_total = int(record.get("tier0_total", 1))
    t0_pct = round(t0_done / t0_total * 100) if t0_total else 0

    # Compute aggregate T0 streak from habit_scores (t0_streak field if present)
    t0_streak = int(record.get("t0_perfect_streak") or record.get("t0_aggregate_streak") or 0)

    return _ok(
        {
            "habit_streaks": {
                "as_of_date": record.get("date", yesterday),
                "tier0_pct": t0_pct,
                "tier0_done": t0_done,
                "tier0_total": t0_total,
                "aggregate_streak": t0_streak,
            }
        },
        cache_seconds=3600,
    )


def handle_experiments() -> dict:
    """
    GET /api/experiments
    Returns: list of experiments with status (no sensitive metric data).
    Cache: 3600s (1 hr).
    """
    pk = f"{USER_PREFIX}experiments"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot experiments
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": pk},
                "ScanIndexForward": False,
                "Limit": 50,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))

    datetime.now(timezone.utc).strftime("%Y-%m-%d")

    experiments = []
    for item in items:
        if not item.get("sk", "").startswith("EXP#"):
            continue
        start = item.get("start_date", "")
        end = item.get("end_date")
        status = item.get("status", "unknown")

        # Compute duration in days
        duration_days = None
        try:
            end_d = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now(timezone.utc).replace(tzinfo=None)
            start_d = datetime.strptime(start, "%Y-%m-%d")
            duration_days = max(0, (end_d - start_d).days)
        except Exception:
            pass

        # Day number (for active experiments) — April 1 start = Day 1 on April 1, Day 2 on April 2, etc.
        days_in = None
        planned_duration = item.get("planned_duration_days")
        if status == "active" and start:
            try:
                days_in = (datetime.now(PT).date() - datetime.strptime(start, "%Y-%m-%d").date()).days + 1
            except Exception:
                pass

        # Progress pct for active
        progress_pct = None
        if status == "active" and days_in is not None and planned_duration:
            progress_pct = min(100, round(days_in / int(planned_duration) * 100))

        experiments.append(
            {
                "id": item.get("sk", "").replace("EXP#", ""),
                "name": item.get("name", "Unnamed"),
                "status": status,
                "start_date": start,
                "end_date": end,
                "hypothesis": item.get("hypothesis", ""),
                "tags": item.get("tags", []),
                # Phase 2 additions
                "outcome": item.get("outcome") or item.get("result_summary"),
                "result_summary": item.get("result_summary") or item.get("outcome"),
                "primary_metric": item.get("primary_metric"),
                "baseline_value": item.get("baseline_value"),
                "result_value": item.get("result_value"),
                "metrics_tracked": item.get("metrics_tracked", []),
                "planned_duration_days": planned_duration,
                "duration_days": duration_days,
                "days_in": days_in,
                "progress_pct": progress_pct,
                "confirmed": item.get("confirmed", False),
                "hypothesis_confirmed": item.get("hypothesis_confirmed"),
                # EXP-2: depth fields
                "mechanism": item.get("mechanism"),
                "key_finding": item.get("key_finding"),
                "protocol": item.get("protocol"),
                "evidence_tier": item.get("evidence_tier"),
                # EL-16+: Evolution fields for Record zone
                "grade": item.get("grade"),
                "compliance_pct": item.get("compliance_pct"),
                "reflection": item.get("reflection"),
                "library_id": item.get("library_id"),
                "duration_tier": item.get("duration_tier"),
                "experiment_type": item.get("experiment_type"),
                "iteration": item.get("iteration", 1),
            }
        )
    experiments.sort(key=lambda x: x["start_date"], reverse=True)

    return _ok({"experiments": experiments}, cache_seconds=3600)


def handle_supplements() -> dict:
    """
    GET /api/supplements
    Returns full supplement registry (groups, items, genome SNPs) from S3 config.
    Merges DynamoDB adherence data when available.
    Cache: 3600s (1 hr).
    """
    registry = _load_supp_metadata()
    if not registry or not registry.get("groups"):
        # Registry config unavailable — shaped-empty 200 rather than a console 503.
        return _ok(
            {"groups": {}, "total_count": 0, "genome_snps": [], "as_of_date": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
            cache_seconds=300,
        )

    # Try to merge DynamoDB adherence data
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    pk = f"{USER_PREFIX}supplements"
    item = None
    for date in (today, yesterday):
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date}"})
        item = _decimal_to_float(resp.get("Item"))
        if item:
            break
    if not item:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk),
            ScanIndexForward=False,
            Limit=5,
        )
        items = _decimal_to_float(resp.get("Items", []))
        item = items[0] if items else None

    # Build adherence lookup from DynamoDB
    adherence_lookup = {}
    if item:
        for s in item.get("supplements", []):
            name = s.get("name", "").lower().replace(" ", "_").replace("-", "_")
            adherence_lookup[name] = s.get("adherence_pct")

    as_of_date = item.get("date", yesterday) if item else yesterday

    # Merge adherence into registry groups
    groups = registry.get("groups", {})
    total_count = 0
    for gkey, group in groups.items():
        for supp in group.get("items", []):
            total_count += 1
            adh = adherence_lookup.get(supp.get("key", ""))
            if adh is not None:
                supp["adherence_pct"] = adh

    return _ok(
        {
            "as_of_date": as_of_date,
            "groups": groups,
            "genome_snps": registry.get("genome_snps", []),
            "total_count": total_count,
        },
        cache_seconds=3600,
    )


def handle_vice_streaks() -> dict:
    """
    GET /api/vice_streaks
    Returns content-filtered vice streak portfolio from habit_scores.vice_streaks.
    Computes current streak, 90-day best, and relapse count per vice.
    Blocked vices (per content_filter.json) are excluded from the response.
    Cache: 3600s (1 hr).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ninety_days_ago = _experiment_date(90)

    # Stage0 Fix 1 (2026-05-30): _is_blocked_vice catches both blocked_vices
    # (exact full names) AND blocked_vice_keywords (substring match). Previously
    # only the former was filtered here, while the client shipped the keyword
    # list to do the substring check itself — leaking the keywords in JS.
    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{ninety_days_ago}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))

    if not items:
        return _ok({"vices": [], "total_held": 0, "total_tracked": 0, "as_of_date": today}, cache_seconds=3600)

    # Gather per-vice streak history (chronological)
    vice_history: dict = {}
    for item in items:
        vs = item.get("vice_streaks") or {}
        if not isinstance(vs, dict):
            continue
        for vice_name, streak_val in vs.items():
            if _is_blocked_vice(vice_name):
                continue
            if vice_name not in vice_history:
                vice_history[vice_name] = []
            vice_history[vice_name].append(int(streak_val or 0))

    if not vice_history:
        return _ok({"vices": [], "total_held": 0, "total_tracked": 0, "as_of_date": today}, cache_seconds=3600)

    # Current state from latest record
    latest = items[-1]
    latest_vs = {}
    raw_vs = latest.get("vice_streaks") or {}
    if isinstance(raw_vs, dict):
        latest_vs = {k: int(v or 0) for k, v in raw_vs.items() if not _is_blocked_vice(k)}

    vices = []
    for vice_name, history in vice_history.items():
        current_streak = latest_vs.get(vice_name, history[-1] if history else 0)
        best_streak = max(history) if history else 0
        # Relapse = streak dropped from >0 to 0
        relapses = sum(1 for i in range(1, len(history)) if history[i - 1] > 0 and history[i] == 0)
        vices.append(
            {
                "name": vice_name,
                "current_streak": current_streak,
                "best_streak": best_streak,
                "relapses_90d": relapses,
                "holding": current_streak > 0,
            }
        )

    # Sort: holding first, then by streak descending
    vices.sort(key=lambda v: (-int(v["holding"]), -v["current_streak"]))

    total_held = int(latest.get("vices_held", 0) or 0)
    total_tracked = len(vices)

    return _ok(
        {
            "as_of_date": latest.get("date", today),
            "vices": vices,
            "total_held": total_held,
            "total_tracked": total_tracked,
        },
        cache_seconds=3600,
    )


def handle_habits() -> dict:
    """
    GET /api/habits
    Returns 90-day daily habit completion history (aggregate only — no habit names).
    Used by /habits/ page for the heatmap and group adherence bars.
    Cache: 3600s (1 hr).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ninety_days_ago = _experiment_date(90)

    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{ninety_days_ago}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))

    # ── Also pull by_group from habitify partition (group data lives there, not in habit_scores)
    hab_pk = f"{USER_PREFIX}habitify"
    hab_resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habitify records
                "KeyConditionExpression": Key("pk").eq(hab_pk) & Key("sk").between(f"DATE#{ninety_days_ago}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    habitify_by_date = {}
    for hi in _decimal_to_float(hab_resp.get("Items", [])):
        date_key = hi.get("date") or hi.get("sk", "").replace("DATE#", "")
        by_group = hi.get("by_group", {})
        if by_group and isinstance(by_group, dict):
            # by_group[Group] = {completed, possible, pct, habits_done}
            # pct is 0.0–1.0, convert to 0–100
            habitify_by_date[date_key] = {g: round(float(v.get("pct", 0) or 0) * 100) for g, v in by_group.items() if isinstance(v, dict)}

    history = []
    for item in items:
        date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
        t0_done = int(item.get("tier0_done", 0) or 0)
        t0_total = int(item.get("tier0_total", 1) or 1)
        t01_done = int(item.get("tier01_done", t0_done) or t0_done)
        t01_total = int(item.get("tier01_total", t0_total) or t0_total)
        t0_pct = round(t0_done / t0_total * 100) if t0_total else 0
        t01_pct = round(t01_done / t01_total * 100) if t01_total else 0
        int(item.get("t0_perfect_streak") or item.get("t0_aggregate_streak") or 0)

        # Per-group breakdown: prefer flat group_* fields on habit_scores;
        # fall back to habitify by_group data if present
        group_data = {}
        for key, val in item.items():
            if key.startswith("group_") and isinstance(val, (int, float)):
                group_data[key.replace("group_", "")] = val
        if not group_data and date_str in habitify_by_date:
            group_data = habitify_by_date[date_str]

        day = {
            "date": date_str,
            "tier0_pct": t0_pct,
            "tier01_pct": t01_pct,
            "t0_done": t0_done,
            "t0_total": t0_total,
            "perfect": t0_pct == 100,
        }
        if group_data:
            day["groups"] = group_data
        history.append(day)

    # Latest record for current streak
    history[-1] if history else {}
    latest_streak = 0
    if items:
        last_item = _decimal_to_float(items[-1])
        latest_streak = int(last_item.get("t0_perfect_streak") or last_item.get("t0_aggregate_streak") or 0)

    # ── Day-of-week analysis (0=Mon ... 6=Sun)
    dow_sums = [0.0] * 7
    dow_counts = [0] * 7
    for day in history:
        try:
            d = datetime.strptime(day["date"], "%Y-%m-%d")
            dow = d.weekday()  # 0=Mon ... 6=Sun
            dow_sums[dow] += day.get("tier0_pct", 0) or 0
            dow_counts[dow] += 1
        except Exception:
            pass
    dow_avgs = [round(dow_sums[i] / dow_counts[i]) if dow_counts[i] else None for i in range(7)]
    valid_dow = [(i, v) for i, v in enumerate(dow_avgs) if v is not None]
    best_dow = max(valid_dow, key=lambda x: x[1])[0] if valid_dow else None
    worst_dow = min(valid_dow, key=lambda x: x[1])[0] if valid_dow else None

    # ── 90-day per-group averages + keystone identification
    group_90d_sums: dict = {}
    group_90d_counts: dict = {}
    for day in history:
        for gname, gpct in (day.get("groups") or {}).items():
            if isinstance(gpct, (int, float)):
                group_90d_sums[gname] = group_90d_sums.get(gname, 0) + gpct
                group_90d_counts[gname] = group_90d_counts.get(gname, 0) + 1
    group_90d_avgs = {g: round(group_90d_sums[g] / group_90d_counts[g]) for g in group_90d_sums if group_90d_counts.get(g, 0) > 0}
    keystone_group = max(group_90d_avgs, key=group_90d_avgs.get) if group_90d_avgs else None
    keystone_group_pct = group_90d_avgs.get(keystone_group) if keystone_group else None

    # ── HAB-3: Pearson correlation per habit group vs character score ──────────
    keystone_correlations = []
    try:
        import math as _math

        # Fetch character_sheet records for same window
        cs_pk = f"{USER_PREFIX}character_sheet"
        cs_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot character sheets
                    "KeyConditionExpression": Key("pk").eq(cs_pk) & Key("sk").between(f"DATE#{ninety_days_ago}", f"DATE#{today}"),
                    "ScanIndexForward": True,
                }
            )
        )
        cs_items = _decimal_to_float(cs_resp.get("Items", []))

        # Build date → pillar sum (character health proxy)
        PILLARS_CS = [
            "pillar_sleep",
            "pillar_movement",
            "pillar_nutrition",
            "pillar_metabolic",
            "pillar_mind",
            "pillar_relationships",
            "pillar_consistency",
        ]
        char_by_date = {}
        for ci in cs_items:
            cs_date = ci.get("date") or ci.get("sk", "").replace("DATE#", "")
            psum = 0.0
            for pkey in PILLARS_CS:
                pdata = ci.get(pkey) or {}
                if isinstance(pdata, dict):
                    ls = pdata.get("level_score")
                    if ls is not None:
                        psum += float(ls)
            if psum > 0:
                char_by_date[cs_date] = psum

        # For each group, collect matched (char_score, group_pct) pairs
        group_series: dict = {}
        for day in history:
            d = day.get("date")
            if d not in char_by_date:
                continue
            cs_score = char_by_date[d]
            for gname, gpct in (day.get("groups") or {}).items():
                if isinstance(gpct, (int, float)):
                    if gname not in group_series:
                        group_series[gname] = []
                    group_series[gname].append((float(gpct), cs_score))

        # Pearson r helper
        def _pearson(pairs):
            n = len(pairs)
            if n < 5:
                return None
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            mx = sum(xs) / n
            my = sum(ys) / n
            num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
            dx = _math.sqrt(sum((x - mx) ** 2 for x in xs))
            dy = _math.sqrt(sum((y - my) ** 2 for y in ys))
            if dx == 0 or dy == 0:
                return None
            return round(num / (dx * dy), 3)

        corr_list = []
        for gname, pairs in group_series.items():
            r = _pearson(pairs)
            if r is not None:
                corr_list.append(
                    {
                        "group": gname,
                        "correlation_r": r,
                        "avg_pct": group_90d_avgs.get(gname),
                        "n_days": len(pairs),
                    }
                )
        corr_list.sort(key=lambda x: abs(x["correlation_r"]), reverse=True)
        keystone_correlations = corr_list[:5]
    except Exception as _hc_e:
        logger.warning("[handle_habits] keystone_correlations failed (non-fatal): %s", _hc_e)

    return _ok(
        {
            "as_of_date": today,
            "days_tracked": len(history),
            "current_streak": latest_streak,
            "history": history,
            "day_of_week_avgs": dow_avgs,
            "best_day": best_dow,
            "worst_day": worst_dow,
            "group_90d_avgs": group_90d_avgs,
            "keystone_group": keystone_group,
            "keystone_group_pct": keystone_group_pct,
            # HAB-3: top 5 habit groups by |Pearson r| vs character score
            "keystone_correlations": keystone_correlations,
        },
        cache_seconds=3600,
    )


def handle_correlations(event: dict = None) -> dict:
    """
    GET /api/correlations
    Returns the most recent weekly correlation matrix (23 pairs)
    for the public Correlation Explorer.

    HP-06: When ?featured=true is passed, returns a flat array of
    the top N significant correlations (default 3) for the homepage
    dynamic discoveries section. Response shape changes to:
      {"correlations": [{...}, ...], "week": "...", "count": N}
    so the homepage JS can iterate directly.

    Cache: 3600s.
    """
    # HP-06: Parse query params
    params = {}
    if event:
        params = event.get("queryStringParameters") or {}
    featured = (params.get("featured") or "").lower() == "true"
    limit = None
    if params.get("limit"):
        try:
            limit = max(1, min(20, int(params["limit"])))
        except (ValueError, TypeError):
            pass

    pk = f"{USER_PREFIX}weekly_correlations"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot weekly correlations
                "KeyConditionExpression": Key("pk").eq(pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        # Genesis week / weekly-correlation compute hasn't run — shaped-empty 200
        # so the site shows an honest "fills as data accrues" state, not a 503.
        return _ok({"correlations": [], "week": None, "start_date": None, "end_date": None, "count": 0}, cache_seconds=300)

    record = items[0]
    week = record.get("sk", "").replace("WEEK#", "")
    start_date = record.get("start_date", "")
    end_date = record.get("end_date", "")

    # The compute lambda stores correlations as a dict (label → data).
    # Convert to list for the public API. Also supports legacy "pairs" list format.
    raw_corrs = record.get("correlations", {})
    if isinstance(raw_corrs, list):
        # Legacy format: already a list
        pairs = raw_corrs
    elif isinstance(raw_corrs, dict):
        # Current format: dict keyed by label. Convert to list.
        pairs = []
        for label, data in raw_corrs.items():
            entry = dict(data)
            entry["label"] = label
            pairs.append(entry)
    else:
        pairs = []

    # Human-readable labels and source names for each metric
    _METRIC_META = {
        "hrv": {"label": "Heart Rate Variability", "source": "Whoop"},
        "recovery_score": {"label": "Recovery Score", "source": "Whoop"},
        "sleep_duration": {"label": "Sleep Duration", "source": "Whoop"},
        "sleep_score": {"label": "Sleep Score", "source": "Whoop"},
        "resting_hr": {"label": "Resting Heart Rate", "source": "Whoop"},
        "strain": {"label": "Strain", "source": "Whoop"},
        "tsb": {"label": "Training Stress Balance", "source": "Computed"},
        "training_kj": {"label": "Training Load (kJ)", "source": "Strava"},
        "training_mins": {"label": "Training Minutes", "source": "Strava"},
        "protein_g": {"label": "Protein (g)", "source": "MacroFactor"},
        "calories": {"label": "Calories", "source": "MacroFactor"},
        "carbs_g": {"label": "Carbs (g)", "source": "MacroFactor"},
        "fat_g": {"label": "Fat (g)", "source": "MacroFactor"},
        "steps": {"label": "Steps", "source": "Apple Health"},
        "habit_pct": {"label": "Habit Completion %", "source": "Habitify"},
        "day_grade": {"label": "Day Grade", "source": "Computed"},
        "readiness": {"label": "Readiness Score", "source": "Computed"},
        "tier0_streak": {"label": "Tier 0 Streak", "source": "Computed"},
    }

    public_pairs = []
    for p in pairs:
        metric_a = p.get("metric_a", p.get("field_a", ""))
        metric_b = p.get("metric_b", p.get("field_b", ""))
        meta_a = _METRIC_META.get(metric_a, {})
        meta_b = _METRIC_META.get(metric_b, {})
        r_val = float(p.get("pearson_r", p.get("r", 0)) or 0)
        public_pairs.append(
            {
                "source_a": meta_a.get("source", p.get("source_a", "")),
                "field_a": metric_a,
                "label_a": meta_a.get("label", p.get("label_a", metric_a)),
                "source_b": meta_b.get("source", p.get("source_b", "")),
                "field_b": metric_b,
                "label_b": meta_b.get("label", p.get("label_b", metric_b)),
                "r": round(r_val, 3),
                "p": round(float(p.get("p_value", p.get("p", 1)) or 1), 4),
                "n": int(p.get("n_days", p.get("n", 0)) or 0),
                "strength": p.get("interpretation", p.get("strength", "weak")),
                "fdr_significant": p.get("fdr_significant", False),
                "correlation_type": p.get("correlation_type", "cross_sectional"),
                "lag_days": int(p.get("lag_days", 0) or 0),
                "description": p.get("description", ""),
                "direction": p.get("direction", ""),
                # DISC-1: counterintuitive flag from compute lambda
                "counterintuitive": p.get("counterintuitive", False),
                "expected_direction": p.get("expected_direction", ""),
                # HP-06: metric labels for homepage cards
                "metric_a": meta_a.get("label", p.get("label_a", metric_a)),
                "metric_b": meta_b.get("label", p.get("label_b", metric_b)),
            }
        )

    # Sort all by absolute r descending
    public_pairs.sort(key=lambda x: -abs(x["r"]))

    # HP-06: Featured mode — return flat array of top significant correlations
    if featured:
        # Filter to significant only (p < 0.05 or FDR-significant)
        significant = [p for p in public_pairs if p.get("fdr_significant") or p.get("p", 1) < 0.05]
        # Fall back to strongest by |r| if no significant ones found
        if not significant:
            significant = public_pairs
        # Apply limit (default 3)
        top = significant[: limit or 3]
        # Auto-generate description if missing
        for p in top:
            if not p.get("description"):
                direction = "positive" if p["r"] > 0 else "inverse"
                p["description"] = f"{direction.title()} correlation between " f"{p['metric_a']} and {p['metric_b']} " f"(r={p['r']:.2f})"
        return _ok(
            {
                "correlations": top,
                "week": week,
                "count": len(top),
            },
            cache_seconds=3600,
        )

    # Standard mode — return full object for explorer page
    return _ok(
        {
            "correlations": {
                "week": week,
                "start_date": start_date,
                "end_date": end_date,
                "pairs": public_pairs,
                "count": len(public_pairs),
                "methodology": "Pearson r over 90-day rolling window. Benjamini-Hochberg FDR correction. n-gated strength labels.",
            }
        },
        cache_seconds=3600,
    )


def handle_genome_risks() -> dict:
    """
    GET /api/genome_risks
    Returns genome SNPs grouped by category with risk levels.
    No raw genotypes exposed. Cache: 86400s (24h).
    """
    pk = f"{USER_PREFIX}genome"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk))
    items = _decimal_to_float(resp.get("Items", []))

    if not items:
        # No genome uploaded yet — shaped-empty 200 so the page shows "not yet published".
        return _ok(
            {"genome": {"total_snps": 0, "risk_summary": {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}, "categories": {}}},
            cache_seconds=3600,
        )

    categories = {}
    risk_summary = {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}

    for snp in items:
        cat = snp.get("category", "other")
        risk = snp.get("risk_level", "neutral")
        risk_summary[risk] = risk_summary.get(risk, 0) + 1

        if cat not in categories:
            categories[cat] = []
        categories[cat].append(
            {
                "gene": snp.get("gene", ""),
                "rsid": snp.get("rsid", snp.get("sk", "").replace("SNP#", "")),
                "risk_level": risk,
                "summary": snp.get("summary", ""),
                "implications": snp.get("implications", ""),
                "interventions": snp.get("interventions", []),
                "evidence": snp.get("evidence_strength", "moderate"),
            }
        )

    for cat in categories:
        categories[cat].sort(key=lambda x: {"unfavorable": 0, "mixed": 1, "neutral": 2, "favorable": 3}.get(x["risk_level"], 2))

    return _ok(
        {
            "genome": {
                "total_snps": len(items),
                "risk_summary": risk_summary,
                "categories": categories,
            }
        },
        cache_seconds=86400,
    )


def handle_glucose() -> dict:
    """
    GET /api/glucose
    Returns: 30-day CGM stats — time-in-range, variability, daily trend.
    Source: apple_health DynamoDB records.
    Cache: 3600s (1h).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    records = _query_source("apple_health", d30, today)
    cgm_days = [r for r in records if r.get("blood_glucose_avg") is not None and r.get("sk", "").replace("DATE#", "") >= EXPERIMENT_START]
    cgm_days.sort(key=lambda x: x.get("sk", ""))

    if not cgm_days:
        return _ok({"glucose": None, "glucose_trend": []}, cache_seconds=3600)

    latest = cgm_days[-1]

    # 30-day averages
    avg_vals = [float(r["blood_glucose_avg"]) for r in cgm_days if r.get("blood_glucose_avg")]
    tir_vals = [float(r["blood_glucose_time_in_range_pct"]) for r in cgm_days if r.get("blood_glucose_time_in_range_pct")]
    opt_vals = [float(r["blood_glucose_time_in_optimal_pct"]) for r in cgm_days if r.get("blood_glucose_time_in_optimal_pct")]
    std_vals = [float(r["blood_glucose_std_dev"]) for r in cgm_days if r.get("blood_glucose_std_dev")]

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    # Daily trend array for chart
    trend = [
        {
            "date": r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(r["blood_glucose_avg"]), 1) if r.get("blood_glucose_avg") else None,
            "tir": round(float(r["blood_glucose_time_in_range_pct"]), 1) if r.get("blood_glucose_time_in_range_pct") else None,
            "std": round(float(r["blood_glucose_std_dev"]), 1) if r.get("blood_glucose_std_dev") else None,
        }
        for r in cgm_days
    ]

    tir_today = float(latest.get("blood_glucose_time_in_range_pct", 0))
    tir_status = "excellent" if tir_today >= 90 else ("good" if tir_today >= 70 else "needs_attention")
    std_today = float(latest.get("blood_glucose_std_dev", 99))
    variability_status = "low" if std_today < 15 else ("moderate" if std_today < 25 else "high")

    # Best/worst day by TIR (or avg glucose if all 100% TIR)
    best_day = None
    worst_day = None
    if len(cgm_days) >= 2:
        sorted_by_tir = sorted(
            cgm_days, key=lambda r: (float(r.get("blood_glucose_time_in_range_pct", 0)), -float(r.get("blood_glucose_std_dev", 99)))
        )
        worst_r = sorted_by_tir[0]
        best_r = sorted_by_tir[-1]
        worst_day = {
            "date": worst_r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(worst_r.get("blood_glucose_avg", 0)), 1),
            "tir": round(float(worst_r.get("blood_glucose_time_in_range_pct", 0)), 1),
        }
        best_day = {
            "date": best_r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(best_r.get("blood_glucose_avg", 0)), 1),
            "tir": round(float(best_r.get("blood_glucose_time_in_range_pct", 0)), 1),
        }

    return _ok(
        {
            "glucose": {
                "avg_mg_dl": round(float(latest.get("blood_glucose_avg", 0)), 1) if latest.get("blood_glucose_avg") else None,
                "std_dev": round(float(latest.get("blood_glucose_std_dev", 0)), 1) if latest.get("blood_glucose_std_dev") else None,
                "time_in_range_pct": round(tir_today, 1),
                "time_in_optimal_pct": (
                    round(float(latest.get("blood_glucose_time_in_optimal_pct", 0)), 1)
                    if latest.get("blood_glucose_time_in_optimal_pct")
                    else None
                ),
                "time_above_140_pct": (
                    round(float(latest.get("blood_glucose_time_above_140_pct", 0)), 1)
                    if latest.get("blood_glucose_time_above_140_pct")
                    else None
                ),
                "cgm_source": latest.get("cgm_source", "unknown"),
                "tir_status": tir_status,
                "variability_status": variability_status,
                "30d_avg_mg_dl": avg(avg_vals),
                "30d_avg_tir": avg(tir_vals),
                "30d_avg_optimal": avg(opt_vals),
                "30d_avg_std": avg(std_vals),
                "days_tracked": len(cgm_days),
                "as_of_date": latest.get("sk", "").replace("DATE#", ""),
                "best_day": best_day,
                "worst_day": worst_day,
            },
            "glucose_trend": trend,
        },
        cache_seconds=3600,
    )


def handle_sleep_detail() -> dict:
    """
    GET /api/sleep_detail
    Returns: 30-day sleep stats from Eight Sleep + Whoop cross-referenced.
    Shows sleep score, efficiency, bed temp, quality, and daily trend.
    Cache: 3600s (1h).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    eight_days = _query_source("eightsleep", d30, today)
    whoop_days = _query_source("whoop", d30, today)

    # Index whoop by date for cross-referencing
    whoop_by_date = {r.get("sk", "").replace("DATE#", ""): r for r in whoop_days if r.get("sk")}

    eight_days.sort(key=lambda x: x.get("sk", ""))
    # Filter to experiment window — EXPERIMENT_QUERY_START fetches 1 day early for sleep lookback,
    # but we only display data from EXPERIMENT_START onwards
    eight_with_data = [
        r for r in eight_days if r.get("sleep_score") is not None and r.get("sk", "").replace("DATE#", "") >= EXPERIMENT_START
    ]

    if not eight_with_data:
        return _ok({"sleep_detail": None, "sleep_trend": []}, cache_seconds=3600)

    latest = eight_with_data[-1]
    latest_date = latest.get("sk", "").replace("DATE#", "")
    whoop_latest = whoop_by_date.get(latest_date, {})
    # If latest Eight Sleep record has no matching Whoop recovery, use most recent that does
    if not whoop_latest.get("recovery_score"):
        for r in reversed(eight_with_data):
            _rd = r.get("sk", "").replace("DATE#", "")
            _wm = whoop_by_date.get(_rd, {})
            if _wm.get("recovery_score"):
                whoop_latest = _wm
                break

    # 30-day averages (actual field names: sleep_efficiency_pct, sleep_duration_hours)
    score_vals = [float(r["sleep_score"]) for r in eight_with_data if r.get("sleep_score")]
    eff_vals = [float(r["sleep_efficiency_pct"]) for r in eight_with_data if r.get("sleep_efficiency_pct")]
    temp_vals = [float(r["bed_temp_f"]) for r in eight_with_data if r.get("bed_temp_f")]

    # Find best-performing temp range by pairing temp with sleep score
    temp_score_pairs = [
        (float(r["bed_temp_f"]), float(r["sleep_score"])) for r in eight_with_data if r.get("bed_temp_f") and r.get("sleep_score")
    ]
    optimal_temp = None
    if len(temp_score_pairs) >= 7:
        # Group by 2°F buckets, find highest average score bucket
        buckets = {}
        for temp, score in temp_score_pairs:
            bucket = round(temp / 2) * 2  # nearest 2°F
            buckets.setdefault(bucket, []).append(score)
        best_bucket = max(buckets, key=lambda b: sum(buckets[b]) / len(buckets[b]))
        optimal_temp = best_bucket

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    # Daily trend — filter to experiment start (EXPERIMENT_QUERY_START is 1 day early for sleep lookback)
    trend = []
    for r in eight_with_data:
        date = r.get("sk", "").replace("DATE#", "")
        if date < EXPERIMENT_START:
            continue  # Don't include pre-experiment days in trend output
        w = whoop_by_date.get(date, {})
        trend.append(
            {
                "date": date,
                "sleep_score": round(float(r["sleep_score"]), 0) if r.get("sleep_score") else None,
                "efficiency": round(float(r["sleep_efficiency_pct"]), 1) if r.get("sleep_efficiency_pct") else None,
                "bed_temp_f": round(float(r["bed_temp_f"]), 1) if r.get("bed_temp_f") else None,
                "hours": round(float(w["sleep_duration_hours"]), 1) if w.get("sleep_duration_hours") else None,
                "whoop_quality": round(float(w["sleep_quality_score"]), 0) if w.get("sleep_quality_score") else None,
                "deep_sleep_hours": round(float(w["slow_wave_sleep_hours"]), 2) if w.get("slow_wave_sleep_hours") else None,
                "rem_sleep_hours": round(float(w["rem_sleep_hours"]), 2) if w.get("rem_sleep_hours") else None,
                "deep_pct": round(float(r["deep_pct"]), 1) if r.get("deep_pct") else None,
                "rem_pct": round(float(r["rem_pct"]), 1) if r.get("rem_pct") else None,
                "light_pct": round(float(r["light_pct"]), 1) if r.get("light_pct") else None,
                "recovery_score": round(float(w["recovery_score"]), 0) if w.get("recovery_score") else None,
                "hrv": round(float(w["hrv"]), 1) if w.get("hrv") else None,
                "rhr": round(float(w["resting_heart_rate"]), 0) if w.get("resting_heart_rate") else None,
                "sleep_start": w.get("sleep_start"),
            }
        )

    score_today = float(latest.get("sleep_score", 0))
    score_status = "excellent" if score_today >= 85 else ("good" if score_today >= 70 else "needs_attention")

    # Compute bed time / wake time averages and social jet lag from Whoop sleep_start/end
    bed_times_weekday = []
    bed_times_weekend = []
    wake_times = []
    for w in whoop_days:
        ss = w.get("sleep_start")
        se = w.get("sleep_end")
        if not ss or "#WORKOUT#" in w.get("sk", ""):
            continue
        try:
            start_dt = datetime.fromisoformat(ss.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(se.replace("Z", "+00:00"))
            start_pt = start_dt.astimezone(PT)
            end_pt = end_dt.astimezone(PT)
            # Normalize bed hour: treat times after 6 PM as evening (18-30), before 6 AM as late night (24-30)
            bed_hour = start_pt.hour + start_pt.minute / 60
            if bed_hour < 6:
                bed_hour += 24  # 1 AM → 25, so avg with 11 PM (23) works correctly
            wake_hour = end_pt.hour + end_pt.minute / 60
            wake_times.append(wake_hour)
            if start_pt.weekday() in (4, 5):  # Fri/Sat night = weekend sleep
                bed_times_weekend.append(bed_hour)
            else:
                bed_times_weekday.append(bed_hour)
        except Exception:
            continue

    def _fmt_hour(h):
        """Convert decimal hour to HH:MM AM/PM."""
        h = h % 24
        hr = int(h)
        mn = int((h - hr) * 60)
        ampm = "AM" if hr < 12 else "PM"
        hr12 = hr % 12 or 12
        return f"{hr12}:{mn:02d} {ampm}"

    all_bed = bed_times_weekday + bed_times_weekend
    avg_bed = round(sum(all_bed) / len(all_bed), 2) if all_bed else None
    avg_bed_wd = round(sum(bed_times_weekday) / len(bed_times_weekday), 2) if bed_times_weekday else None
    avg_bed_we = round(sum(bed_times_weekend) / len(bed_times_weekend), 2) if bed_times_weekend else None
    avg_wake = round(sum(wake_times) / len(wake_times), 2) if wake_times else None
    social_jet_lag_hrs = round(abs((avg_bed_wd or 0) - (avg_bed_we or 0)), 1) if avg_bed_wd is not None and avg_bed_we is not None else None

    return _ok(
        {
            "sleep_detail": {
                "sleep_score": round(score_today, 0),
                "sleep_efficiency": round(float(latest.get("sleep_efficiency_pct", 0)), 1) if latest.get("sleep_efficiency_pct") else None,
                "bed_temp_f": round(float(latest.get("bed_temp_f", 0)), 1) if latest.get("bed_temp_f") else None,
                "total_sleep_hours": round(float(latest.get("sleep_duration_hours", 0)), 1) if latest.get("sleep_duration_hours") else None,
                "whoop_quality": (
                    round(float(whoop_latest.get("sleep_quality_score", 0)), 0) if whoop_latest.get("sleep_quality_score") else None
                ),
                "whoop_hours": (
                    round(float(whoop_latest.get("sleep_duration_hours", 0)), 1) if whoop_latest.get("sleep_duration_hours") else None
                ),
                "deep_sleep_hours": (
                    round(float(whoop_latest.get("slow_wave_sleep_hours", 0)), 2) if whoop_latest.get("slow_wave_sleep_hours") else None
                ),
                "rem_sleep_hours": round(float(whoop_latest.get("rem_sleep_hours", 0)), 2) if whoop_latest.get("rem_sleep_hours") else None,
                "recovery_score": round(float(whoop_latest.get("recovery_score", 0)), 0) if whoop_latest.get("recovery_score") else None,
                "hrv": round(float(whoop_latest.get("hrv", 0)), 1) if whoop_latest.get("hrv") else None,
                "rhr": round(float(whoop_latest.get("resting_heart_rate", 0)), 0) if whoop_latest.get("resting_heart_rate") else None,
                "score_status": score_status,
                "deep_pct": round(float(latest.get("deep_pct", 0)), 1) if latest.get("deep_pct") else None,
                "rem_pct": round(float(latest.get("rem_pct", 0)), 1) if latest.get("rem_pct") else None,
                "light_pct": round(float(latest.get("light_pct", 0)), 1) if latest.get("light_pct") else None,
                "30d_avg_recovery": (
                    avg(
                        [
                            float(whoop_by_date.get(r.get("sk", "").replace("DATE#", ""), {}).get("recovery_score", 0))
                            for r in eight_with_data
                            if whoop_by_date.get(r.get("sk", "").replace("DATE#", ""), {}).get("recovery_score")
                        ]
                    )
                    if whoop_by_date
                    else None
                ),
                "optimal_temp_f": optimal_temp,
                "30d_avg_score": avg(score_vals),
                "30d_avg_efficiency": avg(eff_vals),
                "30d_avg_temp": avg(temp_vals),
                "days_tracked": len(eight_with_data),
                "as_of_date": latest_date,
                "avg_bedtime": _fmt_hour(avg_bed) if avg_bed is not None else None,
                "avg_bedtime_weekday": _fmt_hour(avg_bed_wd) if avg_bed_wd is not None else None,
                "avg_bedtime_weekend": _fmt_hour(avg_bed_we) if avg_bed_we is not None else None,
                "avg_waketime": _fmt_hour(avg_wake) if avg_wake is not None else None,
                "social_jet_lag_hrs": social_jet_lag_hrs,
            },
            "sleep_trend": trend,
        },
        cache_seconds=3600,
    )


def handle_protocols() -> dict:
    """GET /api/protocols — Return protocol definitions from DynamoDB."""
    protocols_pk = f"{USER_PREFIX}protocols"
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot protocols
                    "KeyConditionExpression": Key("pk").eq(protocols_pk) & Key("sk").begins_with("PROTOCOL#"),
                    "ScanIndexForward": True,
                }
            )
        )
        protocols = []
        for item in _decimal_to_float(resp.get("Items", [])):
            item.pop("pk", None)
            item.pop("sk", None)
            protocols.append(item)
        return _ok({"protocols": protocols, "count": len(protocols)}, cache_seconds=3600)
    except Exception as e:
        logger.warning("handle_protocols: DynamoDB query failed, falling back to S3: %s", e)
        global _protocols_cache
        if _protocols_cache is None:
            _protocols_cache = _load_s3_json("site/config/protocols.json", "protocols")
        protocols = _protocols_cache.get("protocols", [])
        return _ok({"protocols": protocols, "count": len(protocols)}, cache_seconds=3600)


def handle_domains() -> dict:
    """GET /api/domains — Return domain groupings from S3 config."""
    global _domains_cache
    if _domains_cache is None:
        _domains_cache = _load_s3_json("site/config/domains.json", "domains")
    domains = _domains_cache.get("domains", [])
    return _ok({"domains": domains, "count": len(domains)}, cache_seconds=3600)


def handle_habit_registry() -> dict:
    """GET /api/habit_registry — Return habit registry from DynamoDB PROFILE#v1.

    Stage0 Fix 1 (2026-05-30): blocked vice/habit names are stripped here so
    the client never sees them. Previously the client filtered, which shipped
    the keyword list in plaintext JS.
    """
    try:
        resp = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        profile = resp.get("Item", {})
        registry = profile.get("habit_registry", {})
        habits = []
        for name, meta in registry.items():
            if _is_blocked_vice(name):
                continue
            h = {"name": name}
            for k, v in meta.items():
                h[k] = float(v) if isinstance(v, Decimal) else v
            habits.append(h)
        tier_order = {"T0": 0, "T1": 1, "T2": 2}
        habits.sort(key=lambda x: (tier_order.get(x.get("tier", "T2"), 9), x.get("name", "")))
        return _ok({"habits": habits, "count": len(habits)}, cache_seconds=3600)
    except Exception as e:
        logger.error(f"[habit_registry] Error: {e}")
        return _error(500, "Failed to load habit registry")


def handle_labs() -> dict:
    """GET /api/labs — Returns lab biomarkers from clinical.json in S3."""
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=f"dashboard/{USER_ID}/clinical.json")
        data = json.loads(resp["Body"].read())
        labs = data.get("labs", {})
        if not labs or not labs.get("biomarkers"):
            return _error(404, "No lab data available.")
        return _ok({"labs": labs}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[labs] Failed to load clinical.json: {e}")
        return _error(503, "Lab data temporarily unavailable.")


def handle_changes_since(qs: dict = None) -> dict:
    """GET /api/changes-since?ts=EPOCH — Returns notable changes since timestamp."""
    qs = qs or {}
    ts_str = qs.get("ts", "")
    if not ts_str:
        return _error(400, "Missing ts parameter")

    try:
        since_ts = int(ts_str)
    except (ValueError, TypeError):
        return _error(400, "Invalid ts parameter")

    from datetime import datetime, timedelta, timezone

    since_dt = datetime.fromtimestamp(since_ts, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    days_ago = max(1, (now - since_dt).days)
    # Cap lookback to 30 days
    if days_ago > 30:
        since_dt = now - timedelta(days=30)
        days_ago = 30

    start_date = since_dt.strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    # Fetch weight, HRV, sleep, character data
    deltas = {}
    try:
        whoop_items = _query_source("whoop", start_date, end_date)
        withings_items = _query_source("withings", start_date, end_date)

        # Weight delta
        weights = [
            float(i.get("weight_kg", 0)) * 2.20462 for i in withings_items if i.get("weight_kg") and float(i.get("weight_kg", 0)) > 0
        ]
        if len(weights) >= 2:
            spark = weights[-7:] if len(weights) > 7 else weights
            deltas["weight"] = {
                "from": round(weights[0], 1),
                "to": round(weights[-1], 1),
                "change": round(weights[-1] - weights[0], 1),
                "unit": "lbs",
                "sparkline": [round(w, 1) for w in spark],
            }

        # HRV delta
        hrvs = [float(i.get("hrv", 0)) for i in whoop_items if i.get("hrv") and float(i.get("hrv", 0)) > 0]
        if len(hrvs) >= 2:
            spark = hrvs[-7:] if len(hrvs) > 7 else hrvs
            trend = "climbing" if hrvs[-1] > hrvs[0] else "declining" if hrvs[-1] < hrvs[0] else "stable"
            deltas["hrv"] = {
                "from": round(hrvs[0]),
                "to": round(hrvs[-1]),
                "change": round(hrvs[-1] - hrvs[0]),
                "unit": "ms",
                "trend": trend,
                "sparkline": [round(h) for h in spark],
            }

        # Sleep delta
        sleeps = [
            float(i.get("sleep_duration_hours", 0))
            for i in whoop_items
            if i.get("sleep_duration_hours") and float(i.get("sleep_duration_hours", 0)) > 0
        ]
        if len(sleeps) >= 2:
            spark = sleeps[-7:] if len(sleeps) > 7 else sleeps
            trend = "improving" if sleeps[-1] > sleeps[0] else "declining"
            deltas["sleep"] = {
                "from": round(sleeps[0], 1),
                "to": round(sleeps[-1], 1),
                "change": round(sleeps[-1] - sleeps[0], 1),
                "unit": "hrs",
                "trend": trend,
                "sparkline": [round(s, 1) for s in spark],
            }
    except Exception as e:
        logger.warning(f"[changes-since] DynamoDB query failed: {e}")

    # Character delta
    try:
        char_items = _query_source("character_sheet", start_date, end_date)
        scores = [float(i.get("overall_score", 0)) for i in char_items if i.get("overall_score")]
        if len(scores) >= 2:
            deltas["character"] = {
                "from": round(scores[0]),
                "to": round(scores[-1]),
                "change": round(scores[-1] - scores[0]),
                "unit": "pts",
                "sparkline": [round(s) for s in (scores[-7:] if len(scores) > 7 else scores)],
            }
    except Exception:
        pass

    # Events (experiments completed, chronicles published)
    events_list = []
    try:
        exp_items = _query_source("experiments", start_date, end_date)
        for e in exp_items:
            if e.get("status") == "completed":
                events_list.append(
                    {
                        "type": "experiment_complete",
                        "title": e.get("name", "Experiment"),
                        "link": "/experiments/",
                        "date": e.get("sk", "").replace("DATE#", ""),
                    }
                )
    except Exception:
        pass

    return _ok(
        {
            "since": since_dt.isoformat(),
            "days_ago": days_ago,
            "deltas": deltas,
            "events": events_list[:5],
        },
        cache_seconds=300,
    )


def handle_observatory_week(qs: dict = None) -> dict:
    """GET /api/observatory_week?domain=sleep — Returns 7-day summary for a domain."""
    qs = qs or {}
    domain = (qs.get("domain") or "sleep").lower().strip()
    valid_domains = {"sleep", "glucose", "nutrition", "training", "mind", "physical"}
    if domain not in valid_domains:
        return _error(400, f"Invalid domain. Use: {', '.join(sorted(valid_domains))}")

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = max((now - timedelta(days=7)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    prev_start = max((now - timedelta(days=14)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    prev_end = max((now - timedelta(days=8)).strftime("%Y-%m-%d"), EXPERIMENT_START)

    try:
        if domain == "sleep":
            items = _query_source("whoop", start_date, end_date)
            prev_items = _query_source("whoop", prev_start, prev_end)

            durations = [float(i.get("sleep_duration_hours", 0)) for i in items if i.get("sleep_duration_hours")]
            prev_durations = [float(i.get("sleep_duration_hours", 0)) for i in prev_items if i.get("sleep_duration_hours")]
            avg_dur = sum(durations) / len(durations) if durations else 0
            prev_avg = sum(prev_durations) / len(prev_durations) if prev_durations else 0

            best = max(items, key=lambda i: float(i.get("sleep_duration_hours", 0)), default={})
            worst = min(items, key=lambda i: float(i.get("sleep_duration_hours", 99)), default={})

            eff_vals = [
                float(i.get("sleep_quality_score") or i.get("sleep_efficiency_pct") or 0)
                for i in items
                if i.get("sleep_quality_score") or i.get("sleep_efficiency_pct")
            ]
            best_eff = max(eff_vals) if eff_vals else None

            summary = {
                "primary": {
                    "label": "Average Duration",
                    "value": round(avg_dur, 1),
                    "unit": "hrs",
                    "delta": round(avg_dur - prev_avg, 1),
                    "delta_label": f"vs {round(prev_avg, 1)} last week",
                    "trend": "up" if avg_dur > prev_avg else "down",
                    "sparkline": [round(d, 1) for d in durations],
                },
                "highlight": {
                    "label": "Best Night",
                    "value": f"{best.get('sk', '').replace('DATE#', '')[5:]} · {round(float(best.get('sleep_duration_hours', 0)), 1)}h",
                    "detail": f"Recovery {round(float(best.get('recovery_score', 0)))}%",
                },
                "lowlight": {
                    "label": "Worst Night",
                    "value": f"{worst.get('sk', '').replace('DATE#', '')[5:]} · {round(float(worst.get('sleep_duration_hours', 0)), 1)}h",
                    "detail": "",
                },
                "best_efficiency": round(best_eff) if best_eff else None,
            }
            notable = f"Avg sleep {'improved' if avg_dur > prev_avg else 'declined'} {abs(round(avg_dur - prev_avg, 1))}h vs last week"

        elif domain == "nutrition":
            items = _query_source("macrofactor", start_date, end_date)
            prev_items = _query_source("macrofactor", prev_start, prev_end)

            cals = [
                float(i.get("total_calories_kcal") or i.get("calories") or 0)
                for i in items
                if i.get("total_calories_kcal") or i.get("calories")
            ]
            prev_cals = [
                float(i.get("total_calories_kcal") or i.get("calories") or 0)
                for i in prev_items
                if i.get("total_calories_kcal") or i.get("calories")
            ]
            avg_cal = sum(cals) / len(cals) if cals else 0
            prev_avg_cal = sum(prev_cals) / len(prev_cals) if prev_cals else 0
            proteins = [
                float(i.get("total_protein_g") or i.get("protein_g") or 0) for i in items if i.get("total_protein_g") or i.get("protein_g")
            ]
            avg_protein = sum(proteins) / len(proteins) if proteins else 0

            summary = {
                "primary": {
                    "label": "Avg Calories",
                    "value": round(avg_cal),
                    "unit": "kcal",
                    "delta": round(avg_cal - prev_avg_cal),
                    "delta_label": f"vs {round(prev_avg_cal)} last week",
                    "trend": "up" if avg_cal > prev_avg_cal else "down",
                    "sparkline": [round(c) for c in cals],
                },
                "highlight": {"label": "Avg Protein", "value": f"{round(avg_protein)}g/day", "detail": ""},
                "lowlight": {"label": "Logged Days", "value": f"{len(cals)}/7", "detail": ""},
            }
            notable = f"Protein averaged {round(avg_protein)}g/day this week"

        elif domain == "training":
            items = _query_source("whoop", start_date, end_date)
            strains = [float(i.get("strain", 0)) for i in items if i.get("strain")]
            recoveries = [float(i.get("recovery_score", 0)) for i in items if i.get("recovery_score")]
            avg_strain = sum(strains) / len(strains) if strains else 0
            avg_recovery = sum(recoveries) / len(recoveries) if recoveries else 0

            summary = {
                "primary": {
                    "label": "Avg Strain",
                    "value": round(avg_strain, 1),
                    "unit": "",
                    "delta": 0,
                    "delta_label": "",
                    "trend": "flat",
                    "sparkline": [round(s, 1) for s in strains],
                },
                "highlight": {"label": "Avg Recovery", "value": f"{round(avg_recovery)}%", "detail": ""},
                "lowlight": {"label": "Active Days", "value": f"{len([s for s in strains if s > 5])}/7", "detail": ""},
            }
            notable = f"Average recovery {round(avg_recovery)}% this week"

        elif domain == "glucose":
            items = _query_source("apple_health", start_date, end_date)
            tirs = [float(i.get("blood_glucose_time_in_range_pct", 0)) for i in items if i.get("blood_glucose_time_in_range_pct")]
            avg_tir = sum(tirs) / len(tirs) if tirs else 0
            avg_glucoses = [float(i.get("blood_glucose_avg", 0)) for i in items if i.get("blood_glucose_avg")]
            avg_glucose = sum(avg_glucoses) / len(avg_glucoses) if avg_glucoses else 0

            summary = {
                "primary": {
                    "label": "Avg TIR",
                    "value": round(avg_tir, 1),
                    "unit": "%",
                    "delta": 0,
                    "delta_label": "",
                    "trend": "flat",
                    "sparkline": [round(t, 1) for t in tirs],
                },
                "highlight": {
                    "label": "Best Day",
                    "value": f"{round(max(tirs))}% TIR" if tirs else "\u2014",
                    "detail": f"Avg glucose {round(avg_glucose)} mg/dL" if avg_glucose else "",
                },
                "lowlight": {"label": "Worst Day", "value": f"{round(min(tirs))}% TIR" if tirs else "\u2014", "detail": ""},
            }
            notable = f"Average time-in-range {round(avg_tir)}% this week"

        elif domain == "mind":
            items = _query_source("journal", start_date, end_date)
            moods = [float(i.get("mood_valence", 0)) for i in items if i.get("mood_valence") is not None]
            avg_mood = sum(moods) / len(moods) if moods else 0

            summary = {
                "primary": {
                    "label": "Avg Mood",
                    "value": round(avg_mood, 2),
                    "unit": "",
                    "delta": 0,
                    "delta_label": "",
                    "trend": "flat",
                    "sparkline": [round(m, 2) for m in moods],
                },
                "highlight": {"label": "Journal Entries", "value": str(len(items)), "detail": "this week"},
                "lowlight": {"label": "Energy", "value": "—", "detail": ""},
            }
            notable = f"{len(items)} journal entries this week"

        elif domain == "physical":
            items = _query_source("withings", start_date, end_date)
            weights = [float(i.get("weight_lbs", 0)) for i in items if i.get("weight_lbs")]
            if weights:
                start_w = weights[0]
                end_w = weights[-1]
                delta = round(end_w - start_w, 1)
                summary = {
                    "primary": {
                        "label": "Weight Change",
                        "value": round(end_w),
                        "unit": "lbs",
                        "delta": delta,
                        "delta_label": f"{delta:+.1f} lbs this week",
                        "trend": "down" if delta < 0 else "up",
                        "sparkline": [round(w) for w in weights],
                    },
                    "highlight": {"label": "Weigh-ins", "value": str(len(weights)), "detail": "this week"},
                    "lowlight": {"label": "Current", "value": f"{round(end_w)} lbs", "detail": ""},
                }
                notable = f"Weight {'dropped' if delta < 0 else 'gained'} {abs(delta)} lbs this week"
            else:
                summary = {
                    "primary": {
                        "label": "Weight",
                        "value": None,
                        "unit": "lbs",
                        "delta": 0,
                        "delta_label": "",
                        "trend": "flat",
                        "sparkline": [],
                    },
                    "highlight": {"label": "Weigh-ins", "value": "0", "detail": "this week"},
                    "lowlight": {"label": "", "value": "", "detail": ""},
                }
                notable = "No weigh-ins recorded this week"

        else:
            return _error(400, "Unsupported domain")

        return _ok(
            {
                "domain": domain,
                "period": {"start": start_date, "end": end_date},
                "summary": summary,
                "notable": notable,
                "last_updated": now.isoformat(),
            },
            cache_seconds=900,
        )

    except Exception as e:
        logger.warning(f"[observatory_week] {domain} failed: {e}")
        return _error(503, f"Weekly {domain} data temporarily unavailable.")


# ══════════════════════════════════════════════════════════════════════════════
# Cycle-over-cycle comparison (2026-06-13)
# The experiment restarts under ADR-058/077; raw timeseries survive every reset,
# so the same first-K-days window can be compared across restart generations.
# Genesis dates per cycle — there is no machine registry of past geneses (SSM
# holds only the current cycle number), so this is the explicit record:
# ══════════════════════════════════════════════════════════════════════════════
CYCLE_GENESES = {
    1: "2026-04-01",  # original launch (Day 1)
    2: "2026-06-01",  # first reset (ADR-077 tooling)
    3: "2026-06-08",  # current run (baseline 311.62)
}


def handle_cycle_compare() -> dict:
    """GET /api/cycle_compare — matched-window comparison across cycles.

    Window K = days elapsed in the CURRENT cycle (capped at 28), applied
    identically to every cycle so day-5 of cycle 3 is compared with day-5 of
    cycles 1 and 2 — never a 5-day run vs a 60-day run.
    """
    try:
        current = max(CYCLE_GENESES)
        today = datetime.now(PT).date()
        elapsed = (today - datetime.strptime(CYCLE_GENESES[current], "%Y-%m-%d").date()).days + 1
        window = max(1, min(elapsed, 28))

        cycles = []
        for n, genesis in sorted(CYCLE_GENESES.items()):
            g = datetime.strptime(genesis, "%Y-%m-%d").date()
            end = (g + timedelta(days=window - 1)).isoformat()
            wd = _query_source("withings", genesis, end, include_pilot=True)
            wh = _query_source("whoop", genesis, end, include_pilot=True)

            weights = [(r["sk"][5:], float(r["weight_lbs"])) for r in wd if r.get("weight_lbs")]
            weights.sort()
            rec = [float(r["recovery_score"]) for r in wh if r.get("recovery_score")]
            slp = [float(r["sleep_duration_hours"]) for r in wh if r.get("sleep_duration_hours")]

            cycles.append(
                {
                    "cycle": n,
                    "genesis": genesis,
                    "is_current": n == current,
                    "weight_start_lbs": round(weights[0][1], 1) if weights else None,
                    "weight_delta_lbs": round(weights[-1][1] - weights[0][1], 1) if len(weights) >= 2 else None,
                    "avg_recovery_pct": round(sum(rec) / len(rec), 1) if rec else None,
                    "avg_sleep_hours": round(sum(slp) / len(slp), 2) if slp else None,
                    "days_with_data": len({r["sk"] for r in wd} | {r["sk"] for r in wh}),
                }
            )

        return _ok(
            {
                "window_days": window,
                "current_cycle": current,
                "cycles": cycles,
                "note": (
                    f"Each cycle measured over its own first {window} days — matched windows, "
                    "never a short run vs a long one. Correlative, N=1."
                ),
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[cycle_compare] failed: {e}")
        return _error(503, "Cycle comparison temporarily unavailable.")


# ══════════════════════════════════════════════════════════════════════════════
# The inference receipt (2026-06-13) — radical cost transparency.
# Every Claude call already lands in two metric streams: AWS/Bedrock emits
# token counts per ModelId, and the shared layer emits per-Lambda tokens to
# LifePlatform/AI. This endpoint reads both, prices them with the same table
# the cost governor enforces, and publishes the meter.
# ══════════════════════════════════════════════════════════════════════════════
_BEDROCK_PRICES = {  # USD per 1M tokens — keep in sync with cost_governor_lambda._PRICES
    "fable": {"in": 10.00, "out": 50.00},
    "sonnet": {"in": 3.00, "out": 15.00},
    "haiku": {"in": 1.00, "out": 5.00},
    "opus": {"in": 5.00, "out": 25.00},
}


def _price_for_model(model_id: str) -> dict:
    m = (model_id or "").lower()
    for k, p in _BEDROCK_PRICES.items():
        if k in m:
            return p
    return _BEDROCK_PRICES["sonnet"]


def handle_inference_receipt() -> dict:
    """GET /api/inference_receipt — today's AI calls + month-to-date, priced."""
    try:
        cw = boto3.client("cloudwatch", region_name="us-west-2")
        ssm = boto3.client("ssm", region_name="us-west-2")
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def _sum(namespace, metric, dim_name, dim_value, start):
            r = cw.get_metric_statistics(
                Namespace=namespace, MetricName=metric,
                Dimensions=[{"Name": dim_name, "Value": dim_value}],
                StartTime=start, EndTime=now, Period=86400, Statistics=["Sum"],
            )
            return sum(p["Sum"] for p in r.get("Datapoints", []))

        # Per-model (AWS/Bedrock emits these for every invoke)
        models = []
        seen = cw.list_metrics(Namespace="AWS/Bedrock", MetricName="InputTokenCount")
        for m in seen.get("Metrics", []):
            mid = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "ModelId"), None)
            if not mid:
                continue
            price = _price_for_model(mid)
            row = {"model": mid.split("/")[-1]}
            for label, start in (("today", day_start), ("month", month_start)):
                tin = _sum("AWS/Bedrock", "InputTokenCount", "ModelId", mid, start)
                tout = _sum("AWS/Bedrock", "OutputTokenCount", "ModelId", mid, start)
                row[label] = {
                    "input_tokens": int(tin),
                    "output_tokens": int(tout),
                    "est_cost_usd": round((tin * price["in"] + tout * price["out"]) / 1_000_000, 4),
                }
            if row["month"]["input_tokens"] or row["month"]["output_tokens"]:
                models.append(row)

        # Per-feature (the shared layer dimensions by Lambda function)
        features = []
        fn_metrics = cw.list_metrics(Namespace="LifePlatform/AI", MetricName="AnthropicInputTokens")
        for m in fn_metrics.get("Metrics", []):
            fn = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "LambdaFunction"), None)
            if not fn:
                continue
            tin = _sum("LifePlatform/AI", "AnthropicInputTokens", "LambdaFunction", fn, month_start)
            tout = _sum("LifePlatform/AI", "AnthropicOutputTokens", "LambdaFunction", fn, month_start)
            if tin or tout:
                features.append({"lambda": fn, "month_input_tokens": int(tin), "month_output_tokens": int(tout)})
        features.sort(key=lambda f: -(f["month_input_tokens"] + f["month_output_tokens"]))

        try:
            tier = int(ssm.get_parameter(Name="/life-platform/budget-tier")["Parameter"]["Value"])
        except Exception:
            tier = None

        month_total = round(sum(r["month"]["est_cost_usd"] for r in models), 2)
        return _ok(
            {
                "as_of": now.isoformat(timespec="seconds"),
                "budget_ceiling_usd": 75,
                "budget_tier": tier,
                "ai_month_to_date_usd": month_total,
                "models": models,
                "features": features,
                "note": (
                    "Every Claude call routes through one audited chokepoint (ADR-062). "
                    "Costs are estimated from token metrics x list prices — the same math "
                    "the budget governor enforces. The $75 ceiling covers the WHOLE platform, "
                    "not just AI."
                ),
            },
            cache_seconds=900,
        )
    except Exception as e:
        logger.warning(f"[inference_receipt] failed: {e}")
        return _error(503, "Inference receipt temporarily unavailable.")


# ══════════════════════════════════════════════════════════════════════════════
# The Wrong Page (2026-06-13) — the AI's misses, in public.
# Three streams of being wrong, all already recorded:
#   1. The post-generation validator: coach claims contradicted by the data
#      (USER#matthew / SOURCE#intelligence_quality#date — errors[] + flags[])
#   2. The prediction evaluator: per-coach LEARNING# verdicts
#      (confirmed / refuted / inconclusive / expired)
#   3. Refuted hypotheses from the weekly engine
# Nothing here is curated. An empty refuted column after a reset is honest,
# not flattering — the ledger fills as calls resolve.
# ══════════════════════════════════════════════════════════════════════════════
_WRONG_COACHES = ("sleep", "nutrition", "training", "glucose", "mind", "physical", "labs", "explorer")


def handle_wrong() -> dict:
    """GET /api/wrong — the public ledger of AI misses."""
    try:
        # 1. Validator catches (last 120 days)
        start = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("USER#matthew")
            & Key("sk").between(f"SOURCE#intelligence_quality#{start}", "SOURCE#intelligence_quality#~"),
        )
        items = _decimal_to_float(resp.get("Items", []))
        checks_run = int(sum(i.get("checks_run", 0) or 0 for i in items))
        catches, numeric_caught = [], 0
        for i in items:
            for field, sev in (("errors", "error"), ("flags", "flag")):
                v = i.get(field)
                if isinstance(v, list):
                    for e in v:
                        what = (e.get("detail") or e.get("check") or str(e)) if isinstance(e, dict) else str(e)
                        catches.append({"date": i.get("date"), "coach": i.get("coach_id"), "severity": sev, "what": str(what)[:240]})
                elif isinstance(v, (int, float)) and v:
                    numeric_caught += int(v)  # older records store counts, not detail
        catches.sort(key=lambda c: c.get("date") or "", reverse=True)

        # 2. Prediction verdicts per coach
        ledger, recent_misses = [], []
        for c in _WRONG_COACHES:
            r = table.query(
                KeyConditionExpression=Key("pk").eq(f"COACH#{c}_coach") & Key("sk").begins_with("LEARNING#"),
            )
            recs = _decimal_to_float(r.get("Items", []))
            live = [x for x in recs if not x.get("tombstone")]
            counts = {}
            for x in live:
                counts[x.get("status", "unknown")] = counts.get(x.get("status", "unknown"), 0) + 1
            if live:
                ledger.append({"coach": c, **{k: counts.get(k, 0) for k in ("confirmed", "refuted", "inconclusive", "expired")}})
            for x in live:
                if x.get("status") == "refuted":
                    recent_misses.append(
                        {"date": x.get("date"), "coach": c, "what": str(x.get("condition") or x.get("reason") or "")[:240]}
                    )
        recent_misses.sort(key=lambda m: m.get("date") or "", reverse=True)

        return _ok(
            {
                "validator": {"claims_checked": checks_run, "caught": len(catches) + numeric_caught, "recent": catches[:25]},
                "predictions": {"by_coach": ledger, "refuted_recent": recent_misses[:25]},
                "note": (
                    "Uncurated. The validator audits every coach claim against the data it cites; "
                    "the evaluator scores every dated prediction. A thin refuted column right after "
                    "a reset means the slate is young, not that the model is right — inconclusive "
                    "and expired are claims that could not be proven either."
                ),
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[wrong] failed: {e}")
        return _error(503, "The wrong page is temporarily unavailable.")
