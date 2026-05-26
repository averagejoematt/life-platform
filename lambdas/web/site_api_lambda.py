"""
site_api_lambda.py — Real-time public API for averagejoematt.com

PURPOSE:
    Serves live health/journey/character data to the website.
    This is a SEPARATE, READ-ONLY Lambda from the MCP server.
    Never expose the MCP endpoint publicly — this Lambda is the
    only thing the website talks to.

ARCHITECTURE:
    Browser → CloudFront (TTL cache) → API Gateway → this Lambda → DynamoDB

    CloudFront TTL tiers (set on each route):
      /api/vitals      → 300s  (5 min) — weight, HRV, recovery
      /api/journey     → 3600s (1 hr)  — weight trajectory, goal date
      /api/character   → 900s  (15 min) — pillar scores, level
      /api/status      → 60s   (1 min) — system health check

DEPLOYMENT:
    1. Lambda: life-platform-site-api
    2. Reserved concurrency: 20 (hard cap — returns 429 if exceeded)
    3. Function URL or API Gateway HTTP route
    4. CloudFront distribution with /api/* → Lambda origin
    5. Add to CDK: operational_stack.py

IAM ROLE:
    Primary (read):  dynamodb:GetItem/Query, s3:GetObject
    Limited writes: vote/follow/checkin/suggestion records
    AI endpoints:   handled by life-platform-site-api-ai (ADR-036)
    NO access to MCP server.

P1.1 Phase B (2026-05-26):
    Shared helpers, CORS, AWS clients, caches, request-id state are now in
    lambdas/web/site_api_common.py and imported here. Site-api-only logic
    (endpoint handlers + routing) stays in this file.

v1.0.0 — 2026-03-16
"""
# stdlib
import hashlib  # noqa: F401 — used by handlers
import json
import os
import re
import time
import urllib.request  # noqa: F401 — used by AI handlers (kept for backward-compat)
import base64 as _b64  # noqa: F401 — used by subscriber-token helpers
import hmac as _hmac  # noqa: F401 — used by subscriber-token helpers
from datetime import datetime, timezone, timedelta
from decimal import Decimal  # noqa: F401 — kept for backward-compat with handlers

# third-party
import boto3  # noqa: F401 — kept for handlers that create clients
from boto3.dynamodb.conditions import Key

# shared layer
from phase_filter import with_phase_filter  # noqa: F401 — used by handlers below

# P1.1 Phase B (2026-05-26): shared helpers extracted to sibling module.
# Re-import as module-level names so the rest of this file (and the
# ROUTES dict) reference them unchanged.
from web.site_api_common import (
    logger,
    # config
    TABLE_NAME, USER_ID, USER_PREFIX, PT, DDB_REGION, S3_REGION,
    EXPERIMENT_START, EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_QUERY_START,
    # AWS
    dynamodb, table,
    # CORS
    CORS_ORIGIN, SITE_API_ORIGIN_SECRET, CORS_HEADERS,
    # caches
    STATUS_CACHE_TTL, PLATFORM_STATS,
    # helpers
    _cached_secret,
    _decimal_to_float,
    _experiment_date,
    _query_source,
    _latest_item,
    _get_profile,
    _load_supp_metadata,
    _load_content_filter,
    _scrub_blocked_terms,
    _is_blocked_vice,
    _request_id_headers,
    _ok,
    _error,
    # request-id state (set by lambda_handler; read by _ok/_error)
    set_request_id, get_request_id,
)

# P1.1 Phase B step 2 (2026-05-26): observatory handlers extracted to sibling module.
from web.site_api_observatory import (
    handle_nutrition_overview,
    handle_training_overview,
    handle_weekly_physical_summary,
    handle_protein_sources,
    handle_physical_overview,
    handle_journal_analysis,
    handle_mind_overview,
    handle_frequent_meals,
    handle_meal_glucose,
    handle_strength_benchmarks,
    handle_food_delivery_overview,
    handle_strength_deep_dive,
    handle_benchmark_trends,
    handle_meal_responses,
)

# P1.1 Phase B step 3 (2026-05-26): status + pulse handlers extracted.
from web.site_api_intelligence import (
    handle_status,
    handle_status_summary,
    handle_pulse,
    handle_pulse_history,
)

# P1.1 Phase B step 4 (2026-05-26): social cluster extracted to sibling module.
from web.site_api_social import (
    _handle_verify_subscriber,
    handle_subscriber_count,
    _handle_nudge,
    _handle_submit_finding,
    handle_experiment_library,
    _handle_experiment_vote,
    _handle_experiment_follow,
    _handle_experiment_detail,
    _handle_experiment_suggest,
    handle_challenge_catalog,
    handle_challenges,
    _handle_challenge_vote,
    _handle_challenge_follow,
    _handle_challenge_checkin,
    handle_current_challenge,
)

# P1.1 Phase B step 5 (2026-05-26): vitals cluster extracted.
from web.site_api_vitals import (
    handle_vitals,
    handle_journey,
    handle_character,
    handle_weight_progress,
    handle_character_stats,
    handle_journey_timeline,
    handle_journey_waveform,
    handle_achievements,
    handle_snapshot,
    handle_timeline,
)


# ── Endpoint handlers ───────────────────────────────────────

def handle_tools_baseline() -> dict:
    """
    GET /api/tools_baseline
    Returns baseline (first week of experiment) and current values for the
    Tools page comparison badges: RHR, HRV, sleep quality, weight.
    Cache: 3600s — baseline is fixed, current shifts slowly.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Baseline: first 7 days of the experiment
    baseline_end = (datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
                    + timedelta(days=7)).strftime("%Y-%m-%d")

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
    current["weight_lbs"] = (round(float(latest_withings["weight_lbs"]))
                             if latest_withings and latest_withings.get("weight_lbs")
                             else None)

    return _ok({
        "baseline": baseline,
        "baseline_date": EXPERIMENT_START,
        "current": current,
        "current_date": today,
    }, cache_seconds=3600)


def handle_platform_stats() -> dict:
    """GET /api/platform_stats — authoritative platform counts for all site pages."""
    return _ok(PLATFORM_STATS, cache_seconds=3600)


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
        earned_causes.append({
            **cause_cfg,
            "total_usd": cause_data.get("total_usd", 0),
            "count": cause_data.get("count", 0),
        })

    reluctant_causes = []
    for cause_cfg in ledger_config.get("reluctant_causes", []):
        cid = cause_cfg.get("id", "")
        cause_data = by_cause_raw.get(cid, {})
        reluctant_causes.append({
            **cause_cfg,
            "total_usd": cause_data.get("total_usd", 0),
            "count": cause_data.get("count", 0),
        })

    return _ok({
        "totals": totals,
        "by_event": {"earned": earned, "reluctant": reluctant},
        "by_cause": {"earned_causes": earned_causes, "reluctant_causes": reluctant_causes},
    }, cache_seconds=3600)


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
        obj = s3_client.get_object(Bucket=S3_BUCKET,
                                   Key="config/experiment_library.json")
        lib = json.loads(obj["Body"].read())
        for exp in lib.get("experiments", []):
            if exp.get("status") != "active":
                continue
            active_hypotheses.append({
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
            })
    except Exception as e:
        logger.warning(f"[discoveries] experiment library read failed: {e}")

    # ── 2. Inner life observations from insights partition ──
    inner_life = []
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}insights"),
            ScanIndexForward=False,
            Limit=50,
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
            heading_match = re.search(
                r'font-weight:\s*7[0-9]{2}[^>]*>([^<]{10,80})<', text)
            if heading_match:
                title = heading_match.group(1).strip()
            if not title:
                # Fall back to first substantial text
                text_match = re.search(r'>([A-Z][^<]{20,100})<', text)
                if text_match:
                    title = text_match.group(1).strip()
            if not title:
                title = f"{category} — {date}"

            # Extract a body snippet
            body = ""
            # Find first paragraph-like content
            para_match = re.search(
                r'font-size:\s*1[3-5]px[^>]*>([^<]{30,200})<', text)
            if para_match:
                body = para_match.group(1).strip()

            inner_life.append({
                "date": date,
                "category": category,
                "title": title,
                "body": body,
                "confidence": item.get("confidence", ""),
                "actionable": item.get("actionable", False),
                "pillars": item.get("pillars", []),
            })

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
            KeyConditionExpression=Key("pk").eq(
                f"{USER_PREFIX}weekly_correlations"),
            ScanIndexForward=False,
            Limit=4,
        )
        _LABELS = {
            "hrv": "HRV", "recovery_score": "Recovery",
            "sleep_duration": "Sleep Duration", "sleep_score": "Sleep Score",
            "resting_hr": "Resting HR", "strain": "Strain",
            "training_kj": "Training Load", "protein_g": "Protein",
            "calories": "Calories", "steps": "Steps",
            "habit_pct": "Habit Completion", "day_grade": "Day Grade",
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
                ai_findings.append({
                    "week": week,
                    "metric_a": a,
                    "metric_b": b,
                    "r": round(r, 2) if r else 0,
                    "n": c.get("n", 0),
                    "title": f"{a} × {b}: {direction} correlated",
                    "body": f"r={r:+.2f}, n={c.get('n', '?')} days. "
                            f"FDR-corrected significant finding from {week}.",
                })
    except Exception as e:
        logger.warning(f"[discoveries] correlations read failed: {e}")

    return _ok({
        "active_hypotheses": active_hypotheses,
        "inner_life": inner_life,
        "ai_findings": ai_findings,
    }, cache_seconds=1800)


def handle_habit_streaks() -> dict:
    """
    GET /api/habit_streaks
    Returns: Tier 0 habit streaks for public display (aggregate streak only, no habit names).
    Cache: 3600s (1 hr).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Read latest habit_scores record
    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": pk},
        ScanIndexForward=False,
        Limit=3,
    )
    items = _decimal_to_float(resp.get("Items", []))
    record = items[0] if items else None

    if not record:
        return _error(503, "Habit scores not available")

    t0_done = int(record.get("tier0_done", 0))
    t0_total = int(record.get("tier0_total", 1))
    t0_pct = round(t0_done / t0_total * 100) if t0_total else 0

    # Compute aggregate T0 streak from habit_scores (t0_streak field if present)
    t0_streak = int(record.get("t0_perfect_streak") or record.get("t0_aggregate_streak") or 0)

    return _ok({
        "habit_streaks": {
            "as_of_date":      record.get("date", yesterday),
            "tier0_pct":       t0_pct,
            "tier0_done":      t0_done,
            "tier0_total":     t0_total,
            "aggregate_streak": t0_streak,
        }
    }, cache_seconds=3600)


def handle_experiments() -> dict:
    """
    GET /api/experiments
    Returns: list of experiments with status (no sensitive metric data).
    Cache: 3600s (1 hr).
    """
    pk = f"{USER_PREFIX}experiments"
    resp = table.query(
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": pk},
        ScanIndexForward=False,
        Limit=50,
    )
    items = _decimal_to_float(resp.get("Items", []))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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
                days_in = (datetime.now(PT).replace(tzinfo=None) - datetime.strptime(start, "%Y-%m-%d")).days + 1
            except Exception:
                pass

        # Progress pct for active
        progress_pct = None
        if status == "active" and days_in is not None and planned_duration:
            progress_pct = min(100, round(days_in / int(planned_duration) * 100))

        experiments.append({
            "id":                item.get("sk", "").replace("EXP#", ""),
            "name":              item.get("name", "Unnamed"),
            "status":            status,
            "start_date":        start,
            "end_date":          end,
            "hypothesis":        item.get("hypothesis", ""),
            "tags":              item.get("tags", []),
            # Phase 2 additions
            "outcome":           item.get("outcome") or item.get("result_summary"),
            "result_summary":    item.get("result_summary") or item.get("outcome"),
            "primary_metric":    item.get("primary_metric"),
            "baseline_value":    item.get("baseline_value"),
            "result_value":      item.get("result_value"),
            "metrics_tracked":   item.get("metrics_tracked", []),
            "planned_duration_days": planned_duration,
            "duration_days":     duration_days,
            "days_in":           days_in,
            "progress_pct":      progress_pct,
            "confirmed":         item.get("confirmed", False),
            "hypothesis_confirmed": item.get("hypothesis_confirmed"),
            # EXP-2: depth fields
            "mechanism":         item.get("mechanism"),
            "key_finding":       item.get("key_finding"),
            "protocol":          item.get("protocol"),
            "evidence_tier":     item.get("evidence_tier"),
            # EL-16+: Evolution fields for Record zone
            "grade":             item.get("grade"),
            "compliance_pct":    item.get("compliance_pct"),
            "reflection":        item.get("reflection"),
            "library_id":        item.get("library_id"),
            "duration_tier":     item.get("duration_tier"),
            "experiment_type":   item.get("experiment_type"),
            "iteration":         item.get("iteration", 1),
        })
    experiments.sort(key=lambda x: x["start_date"], reverse=True)

    return _ok({"experiments": experiments}, cache_seconds=3600)


# ── BS-11: Timeline data ────────────────────────────────────────

# ── Sprint 9: Supplements + Habits public endpoints ─────────────

def handle_supplements() -> dict:
    """
    GET /api/supplements
    Returns full supplement registry (groups, items, genome SNPs) from S3 config.
    Merges DynamoDB adherence data when available.
    Cache: 3600s (1 hr).
    """
    registry = _load_supp_metadata()
    if not registry or not registry.get("groups"):
        return _error(503, "Supplement data not available")

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
            ScanIndexForward=False, Limit=5,
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

    return _ok({
        "as_of_date": as_of_date,
        "groups": groups,
        "genome_snps": registry.get("genome_snps", []),
        "total_count": total_count,
    }, cache_seconds=3600)


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

    content_filter = _load_content_filter()
    blocked_set = set(v.lower().strip() for v in content_filter.get("blocked_vices", []))

    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{ninety_days_ago}", f"DATE#{today}"
        ),
        ScanIndexForward=True,
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
            if vice_name.lower().strip() in blocked_set:
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
        latest_vs = {k: int(v or 0) for k, v in raw_vs.items() if k.lower().strip() not in blocked_set}

    vices = []
    for vice_name, history in vice_history.items():
        current_streak = latest_vs.get(vice_name, history[-1] if history else 0)
        best_streak = max(history) if history else 0
        # Relapse = streak dropped from >0 to 0
        relapses = sum(1 for i in range(1, len(history)) if history[i - 1] > 0 and history[i] == 0)
        vices.append({
            "name":           vice_name,
            "current_streak": current_streak,
            "best_streak":    best_streak,
            "relapses_90d":   relapses,
            "holding":        current_streak > 0,
        })

    # Sort: holding first, then by streak descending
    vices.sort(key=lambda v: (-int(v["holding"]), -v["current_streak"]))

    total_held = int(latest.get("vices_held", 0) or 0)
    total_tracked = len(vices)

    return _ok({
        "as_of_date":    latest.get("date", today),
        "vices":         vices,
        "total_held":    total_held,
        "total_tracked": total_tracked,
    }, cache_seconds=3600)


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
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{ninety_days_ago}", f"DATE#{today}"
        ),
        ScanIndexForward=True,
    )
    items = _decimal_to_float(resp.get("Items", []))

    # ── Also pull by_group from habitify partition (group data lives there, not in habit_scores)
    hab_pk = f"{USER_PREFIX}habitify"
    hab_resp = table.query(
        KeyConditionExpression=Key("pk").eq(hab_pk) & Key("sk").between(
            f"DATE#{ninety_days_ago}", f"DATE#{today}"
        ),
        ScanIndexForward=True,
    )
    habitify_by_date = {}
    for hi in _decimal_to_float(hab_resp.get("Items", [])):
        date_key = hi.get("date") or hi.get("sk", "").replace("DATE#", "")
        by_group = hi.get("by_group", {})
        if by_group and isinstance(by_group, dict):
            # by_group[Group] = {completed, possible, pct, habits_done}
            # pct is 0.0–1.0, convert to 0–100
            habitify_by_date[date_key] = {
                g: round(float(v.get("pct", 0) or 0) * 100)
                for g, v in by_group.items()
                if isinstance(v, dict)
            }

    history = []
    for item in items:
        date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
        t0_done = int(item.get("tier0_done", 0) or 0)
        t0_total = int(item.get("tier0_total", 1) or 1)
        t01_done = int(item.get("tier01_done", t0_done) or t0_done)
        t01_total = int(item.get("tier01_total", t0_total) or t0_total)
        t0_pct = round(t0_done / t0_total * 100) if t0_total else 0
        t01_pct = round(t01_done / t01_total * 100) if t01_total else 0
        streak = int(item.get("t0_perfect_streak") or item.get("t0_aggregate_streak") or 0)

        # Per-group breakdown: prefer flat group_* fields on habit_scores;
        # fall back to habitify by_group data if present
        group_data = {}
        for key, val in item.items():
            if key.startswith("group_") and isinstance(val, (int, float)):
                group_data[key.replace("group_", "")] = val
        if not group_data and date_str in habitify_by_date:
            group_data = habitify_by_date[date_str]

        day = {
            "date":      date_str,
            "tier0_pct": t0_pct,
            "tier01_pct": t01_pct,
            "t0_done":   t0_done,
            "t0_total":  t0_total,
            "perfect":   t0_pct == 100,
        }
        if group_data:
            day["groups"] = group_data
        history.append(day)

    # Latest record for current streak
    latest = history[-1] if history else {}
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
    dow_avgs = [
        round(dow_sums[i] / dow_counts[i]) if dow_counts[i] else None
        for i in range(7)
    ]
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
    group_90d_avgs = {
        g: round(group_90d_sums[g] / group_90d_counts[g])
        for g in group_90d_sums
        if group_90d_counts.get(g, 0) > 0
    }
    keystone_group = max(group_90d_avgs, key=group_90d_avgs.get) if group_90d_avgs else None
    keystone_group_pct = group_90d_avgs.get(keystone_group) if keystone_group else None

    # ── HAB-3: Pearson correlation per habit group vs character score ──────────
    keystone_correlations = []
    try:
        import math as _math

        # Fetch character_sheet records for same window
        cs_pk = f"{USER_PREFIX}character_sheet"
        cs_resp = table.query(
            KeyConditionExpression=Key("pk").eq(cs_pk) & Key("sk").between(
                f"DATE#{ninety_days_ago}", f"DATE#{today}"
            ),
            ScanIndexForward=True,
        )
        cs_items = _decimal_to_float(cs_resp.get("Items", []))

        # Build date → pillar sum (character health proxy)
        PILLARS_CS = ["pillar_sleep", "pillar_movement", "pillar_nutrition",
                      "pillar_metabolic", "pillar_mind", "pillar_relationships", "pillar_consistency"]
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
                corr_list.append({
                    "group":         gname,
                    "correlation_r": r,
                    "avg_pct":       group_90d_avgs.get(gname),
                    "n_days":        len(pairs),
                })
        corr_list.sort(key=lambda x: abs(x["correlation_r"]), reverse=True)
        keystone_correlations = corr_list[:5]
    except Exception as _hc_e:
        logger.warning("[handle_habits] keystone_correlations failed (non-fatal): %s", _hc_e)

    return _ok({
        "as_of_date":             today,
        "days_tracked":           len(history),
        "current_streak":         latest_streak,
        "history":                history,
        "day_of_week_avgs":       dow_avgs,
        "best_day":               best_dow,
        "worst_day":              worst_dow,
        "group_90d_avgs":         group_90d_avgs,
        "keystone_group":         keystone_group,
        "keystone_group_pct":     keystone_group_pct,
        # HAB-3: top 5 habit groups by |Pearson r| vs character score
        "keystone_correlations":  keystone_correlations,
    }, cache_seconds=3600)


# ── WEB-CE: Correlation data ────────────────────────────────────

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
    resp = table.query(**with_phase_filter({  # ADR-058: hide pilot weekly correlations
        "KeyConditionExpression": Key("pk").eq(pk),
        "ScanIndexForward": False,
        "Limit": 1,
    }))
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        return _error(503, "No correlation data available yet.")

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
        "hrv":            {"label": "Heart Rate Variability", "source": "Whoop"},
        "recovery_score": {"label": "Recovery Score",         "source": "Whoop"},
        "sleep_duration": {"label": "Sleep Duration",         "source": "Whoop"},
        "sleep_score":    {"label": "Sleep Score",            "source": "Whoop"},
        "resting_hr":     {"label": "Resting Heart Rate",     "source": "Whoop"},
        "strain":         {"label": "Strain",                 "source": "Whoop"},
        "tsb":            {"label": "Training Stress Balance", "source": "Computed"},
        "training_kj":    {"label": "Training Load (kJ)",     "source": "Strava"},
        "training_mins":  {"label": "Training Minutes",       "source": "Strava"},
        "protein_g":      {"label": "Protein (g)",            "source": "MacroFactor"},
        "calories":       {"label": "Calories",               "source": "MacroFactor"},
        "carbs_g":        {"label": "Carbs (g)",              "source": "MacroFactor"},
        "fat_g":          {"label": "Fat (g)",                "source": "MacroFactor"},
        "steps":          {"label": "Steps",                  "source": "Apple Health"},
        "habit_pct":      {"label": "Habit Completion %",     "source": "Habitify"},
        "day_grade":      {"label": "Day Grade",              "source": "Computed"},
        "readiness":      {"label": "Readiness Score",        "source": "Computed"},
        "tier0_streak":   {"label": "Tier 0 Streak",          "source": "Computed"},
    }

    public_pairs = []
    for p in pairs:
        metric_a = p.get("metric_a", p.get("field_a", ""))
        metric_b = p.get("metric_b", p.get("field_b", ""))
        meta_a = _METRIC_META.get(metric_a, {})
        meta_b = _METRIC_META.get(metric_b, {})
        r_val = float(p.get("pearson_r", p.get("r", 0)) or 0)
        public_pairs.append({
            "source_a":  meta_a.get("source", p.get("source_a", "")),
            "field_a":   metric_a,
            "label_a":   meta_a.get("label", p.get("label_a", metric_a)),
            "source_b":  meta_b.get("source", p.get("source_b", "")),
            "field_b":   metric_b,
            "label_b":   meta_b.get("label", p.get("label_b", metric_b)),
            "r":         round(r_val, 3),
            "p":         round(float(p.get("p_value", p.get("p", 1)) or 1), 4),
            "n":         int(p.get("n_days", p.get("n", 0)) or 0),
            "strength":  p.get("interpretation", p.get("strength", "weak")),
            "fdr_significant": p.get("fdr_significant", False),
            "correlation_type": p.get("correlation_type", "cross_sectional"),
            "lag_days":  int(p.get("lag_days", 0) or 0),
            "description": p.get("description", ""),
            "direction":   p.get("direction", ""),
            # DISC-1: counterintuitive flag from compute lambda
            "counterintuitive":    p.get("counterintuitive", False),
            "expected_direction":  p.get("expected_direction", ""),
            # HP-06: metric labels for homepage cards
            "metric_a":  meta_a.get("label", p.get("label_a", metric_a)),
            "metric_b":  meta_b.get("label", p.get("label_b", metric_b)),
        })

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
        top = significant[:limit or 3]
        # Auto-generate description if missing
        for p in top:
            if not p.get("description"):
                direction = "positive" if p["r"] > 0 else "inverse"
                p["description"] = (
                    f"{direction.title()} correlation between "
                    f"{p['metric_a']} and {p['metric_b']} "
                    f"(r={p['r']:.2f})"
                )
        return _ok({
            "correlations": top,
            "week":  week,
            "count": len(top),
        }, cache_seconds=3600)

    # Standard mode — return full object for explorer page
    return _ok({
        "correlations": {
            "week":  week,
            "start_date": start_date,
            "end_date":   end_date,
            "pairs": public_pairs,
            "count": len(public_pairs),
            "methodology": "Pearson r over 90-day rolling window. Benjamini-Hochberg FDR correction. n-gated strength labels.",
        }
    }, cache_seconds=3600)


# ── BS-BM2: Genome risk data ────────────────────────────────────

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
        return _error(503, "No genome data available.")

    categories = {}
    risk_summary = {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}

    for snp in items:
        cat = snp.get("category", "other")
        risk = snp.get("risk_level", "neutral")
        risk_summary[risk] = risk_summary.get(risk, 0) + 1

        if cat not in categories:
            categories[cat] = []
        categories[cat].append({
            "gene":         snp.get("gene", ""),
            "rsid":         snp.get("rsid", snp.get("sk", "").replace("SNP#", "")),
            "risk_level":   risk,
            "summary":      snp.get("summary", ""),
            "implications":  snp.get("implications", ""),
            "interventions": snp.get("interventions", []),
            "evidence":     snp.get("evidence_strength", "moderate"),
        })

    for cat in categories:
        categories[cat].sort(key=lambda x: {"unfavorable": 0, "mixed": 1, "neutral": 2, "favorable": 3}.get(x["risk_level"], 2))

    return _ok({
        "genome": {
            "total_snps":   len(items),
            "risk_summary": risk_summary,
            "categories":   categories,
        }
    }, cache_seconds=86400)


# ── WR-24: Subscriber verification ──────────────────────────────────────────

import hmac as _hmac
import base64 as _b64


# ── S2-T2-2: Board Ask ────────────────────────────────────────────────────────

PERSONA_PROMPTS = {
    "vasquez": {
        "name": "Dr. Elena Vasquez",
        "title": "Metabolic Medicine & Longevity",
        "system": (
            "You are Dr. Elena Vasquez, MD, a metabolic medicine physician specializing in longevity. "
            "Focus on: VO2max, Zone 2 training, strength, metabolic health, and the major drivers of chronic disease. "
            "Evidence-based and nuanced. Distinguish strong evidence from speculation. "
            "Your perspective is informed by current peer-reviewed research. Do not reference specific researchers by name. "
            "Use first person. 3-5 sentences. Note N=1 for any comparative claim. "
            "Never give medical advice — reference a physician only if clinically urgent."
        ),
    },
    "okafor": {
        "name": "Dr. James Okafor",
        "title": "Performance Neuroscience",
        "system": (
            "You are Dr. James Okafor PhD, a performance neuroscientist. "
            "Focus on: sleep architecture, light exposure, stress resilience, neuroplasticity, and dopamine. "
            "Explain the mechanism first, then the protocol. "
            "Your perspective is informed by current peer-reviewed research. Do not reference specific researchers by name. "
            "Use phrases like 'the data are clear' and 'the mechanism here is'. "
            "3-5 sentences. Actionable and specific."
        ),
    },
    "patrick": {
        "name": "Rhonda Patrick",
        "title": "Cellular Biology & Nutrition",
        "system": (
            "You are Rhonda Patrick PhD, biochemist and FoundMyFitness founder. "
            "Focus on: micronutrients, cellular resilience, omega-3s, heat/cold exposure, inflammation. "
            "Cite mechanisms. Use 'the research shows' and 'at the cellular level'. "
            "Thorough, not reductive. 3-5 sentences."
        ),
    },
    "norton": {
        "name": "Layne Norton",
        "title": "Evidence-Based Nutrition",
        "system": (
            "You are Layne Norton PhD, nutrition scientist and evidence-based coach. "
            "Focus on: protein synthesis, body composition, muscle retention in deficit. "
            "No-nonsense, skeptical of broscience. "
            "Use 'the evidence actually shows' and 'people get this wrong because'. "
            "Emphasize protein quality, leucine threshold, and adherence. 3-5 sentences."
        ),
    },
    "clear": {
        "name": "James Clear",
        "title": "Habit Architecture",
        "system": (
            "You are James Clear, author of Atomic Habits. "
            "Focus on: identity-based change, the four laws of behavior change, habit stacking, systems over goals. "
            "Aphorism-style language. Make abstract ideas concrete with specific examples. "
            "3-5 sentences. Actionable and memorable."
        ),
    },
    "goggins": {
        "name": "David Goggins",
        "title": "Mental Toughness",
        "system": (
            "You are David Goggins, retired Navy SEAL and ultra-endurance athlete. "
            "You believe most people quit at 40% capacity and that the mind is the limit. "
            "Brutally honest, intense, no coddling. Use 'stay hard' and 'nobody is coming to save you'. "
            "3-5 sentences. High energy."
        ),
    },
}

BOARD_RATE_LIMIT = 5  # per IP per hour
# ── Ask the Platform (AI Q&A) ─────────────────────────────────────


# R17-04: Separate Anthropic key for site-api — injected via CDK env var
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME",  "life-platform/site-api-ai-key")


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
    cgm_days = [
        r for r in records
        if r.get("blood_glucose_avg") is not None
        and r.get("sk", "").replace("DATE#", "") >= EXPERIMENT_START
    ]
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
        sorted_by_tir = sorted(cgm_days, key=lambda r: (
            float(r.get("blood_glucose_time_in_range_pct", 0)),
            -float(r.get("blood_glucose_std_dev", 99))
        ))
        worst_r = sorted_by_tir[0]
        best_r = sorted_by_tir[-1]
        worst_day = {"date": worst_r.get("sk", "").replace("DATE#", ""), "avg": round(float(worst_r.get("blood_glucose_avg", 0)), 1), "tir": round(float(worst_r.get("blood_glucose_time_in_range_pct", 0)), 1)}
        best_day = {"date": best_r.get("sk", "").replace("DATE#", ""), "avg": round(float(best_r.get("blood_glucose_avg", 0)), 1), "tir": round(float(best_r.get("blood_glucose_time_in_range_pct", 0)), 1)}

    return _ok({
        "glucose": {
            "avg_mg_dl":          round(float(latest.get("blood_glucose_avg", 0)), 1) if latest.get("blood_glucose_avg") else None,
            "std_dev":            round(float(latest.get("blood_glucose_std_dev", 0)), 1) if latest.get("blood_glucose_std_dev") else None,
            "time_in_range_pct":  round(tir_today, 1),
            "time_in_optimal_pct": round(float(latest.get("blood_glucose_time_in_optimal_pct", 0)), 1) if latest.get("blood_glucose_time_in_optimal_pct") else None,
            "time_above_140_pct": round(float(latest.get("blood_glucose_time_above_140_pct", 0)), 1) if latest.get("blood_glucose_time_above_140_pct") else None,
            "cgm_source":         latest.get("cgm_source", "unknown"),
            "tir_status":         tir_status,
            "variability_status": variability_status,
            "30d_avg_mg_dl":      avg(avg_vals),
            "30d_avg_tir":        avg(tir_vals),
            "30d_avg_optimal":    avg(opt_vals),
            "30d_avg_std":        avg(std_vals),
            "days_tracked":       len(cgm_days),
            "as_of_date":         latest.get("sk", "").replace("DATE#", ""),
            "best_day":           best_day,
            "worst_day":          worst_day,
        },
        "glucose_trend": trend,
    }, cache_seconds=3600)


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
    whoop_by_date = {
        r.get("sk", "").replace("DATE#", ""): r
        for r in whoop_days
        if r.get("sk")
    }

    eight_days.sort(key=lambda x: x.get("sk", ""))
    # Filter to experiment window — EXPERIMENT_QUERY_START fetches 1 day early for sleep lookback,
    # but we only display data from EXPERIMENT_START onwards
    eight_with_data = [
        r for r in eight_days
        if r.get("sleep_score") is not None and r.get("sk", "").replace("DATE#", "") >= EXPERIMENT_START
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
        (float(r["bed_temp_f"]), float(r["sleep_score"]))
        for r in eight_with_data
        if r.get("bed_temp_f") and r.get("sleep_score")
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
        trend.append({
            "date":          date,
            "sleep_score":   round(float(r["sleep_score"]), 0) if r.get("sleep_score") else None,
            "efficiency":    round(float(r["sleep_efficiency_pct"]), 1) if r.get("sleep_efficiency_pct") else None,
            "bed_temp_f":    round(float(r["bed_temp_f"]), 1) if r.get("bed_temp_f") else None,
            "hours":         round(float(w["sleep_duration_hours"]), 1) if w.get("sleep_duration_hours") else None,
            "whoop_quality": round(float(w["sleep_quality_score"]), 0) if w.get("sleep_quality_score") else None,
            "deep_sleep_hours":  round(float(w["slow_wave_sleep_hours"]), 2) if w.get("slow_wave_sleep_hours") else None,
            "rem_sleep_hours":   round(float(w["rem_sleep_hours"]), 2) if w.get("rem_sleep_hours") else None,
            "deep_pct":          round(float(r["deep_pct"]), 1) if r.get("deep_pct") else None,
            "rem_pct":           round(float(r["rem_pct"]), 1) if r.get("rem_pct") else None,
            "light_pct":         round(float(r["light_pct"]), 1) if r.get("light_pct") else None,
            "recovery_score":    round(float(w["recovery_score"]), 0) if w.get("recovery_score") else None,
            "hrv":               round(float(w["hrv"]), 1) if w.get("hrv") else None,
            "rhr":               round(float(w["resting_heart_rate"]), 0) if w.get("resting_heart_rate") else None,
            "sleep_start":       w.get("sleep_start"),
        })

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

    return _ok({
        "sleep_detail": {
            "sleep_score":       round(score_today, 0),
            "sleep_efficiency":  round(float(latest.get("sleep_efficiency_pct", 0)), 1) if latest.get("sleep_efficiency_pct") else None,
            "bed_temp_f":        round(float(latest.get("bed_temp_f", 0)), 1) if latest.get("bed_temp_f") else None,
            "total_sleep_hours": round(float(latest.get("sleep_duration_hours", 0)), 1) if latest.get("sleep_duration_hours") else None,
            "whoop_quality":     round(float(whoop_latest.get("sleep_quality_score", 0)), 0) if whoop_latest.get("sleep_quality_score") else None,
            "whoop_hours":       round(float(whoop_latest.get("sleep_duration_hours", 0)), 1) if whoop_latest.get("sleep_duration_hours") else None,
            "deep_sleep_hours":  round(float(whoop_latest.get("slow_wave_sleep_hours", 0)), 2) if whoop_latest.get("slow_wave_sleep_hours") else None,
            "rem_sleep_hours":   round(float(whoop_latest.get("rem_sleep_hours", 0)), 2) if whoop_latest.get("rem_sleep_hours") else None,
            "recovery_score":    round(float(whoop_latest.get("recovery_score", 0)), 0) if whoop_latest.get("recovery_score") else None,
            "hrv":               round(float(whoop_latest.get("hrv", 0)), 1) if whoop_latest.get("hrv") else None,
            "rhr":               round(float(whoop_latest.get("resting_heart_rate", 0)), 0) if whoop_latest.get("resting_heart_rate") else None,
            "score_status":      score_status,
            "deep_pct":          round(float(latest.get("deep_pct", 0)), 1) if latest.get("deep_pct") else None,
            "rem_pct":           round(float(latest.get("rem_pct", 0)), 1) if latest.get("rem_pct") else None,
            "light_pct":         round(float(latest.get("light_pct", 0)), 1) if latest.get("light_pct") else None,
            "30d_avg_recovery":  avg([float(whoop_by_date.get(r.get("sk", "").replace("DATE#", ""), {}).get("recovery_score", 0)) for r in eight_with_data if whoop_by_date.get(r.get("sk", "").replace("DATE#", ""), {}).get("recovery_score")]) if whoop_by_date else None,
            "optimal_temp_f":    optimal_temp,
            "30d_avg_score":     avg(score_vals),
            "30d_avg_efficiency": avg(eff_vals),
            "30d_avg_temp":      avg(temp_vals),
            "days_tracked":      len(eight_with_data),
            "as_of_date":        latest_date,
            "avg_bedtime":       _fmt_hour(avg_bed) if avg_bed is not None else None,
            "avg_bedtime_weekday": _fmt_hour(avg_bed_wd) if avg_bed_wd is not None else None,
            "avg_bedtime_weekend": _fmt_hour(avg_bed_we) if avg_bed_we is not None else None,
            "avg_waketime":      _fmt_hour(avg_wake) if avg_wake is not None else None,
            "social_jet_lag_hrs": social_jet_lag_hrs,
        },
        "sleep_trend": trend,
    }, cache_seconds=3600)


# ── ARCH-03: Achievements endpoint ──────────────────────────

# ── ARCH-02: Snapshot endpoint ──────────────────────────────

# ── ACCT-2: Nudge handler ───────────────────────────────────

NUDGE_CATEGORIES = {"back_on_it", "watching", "take_your_time", "you_got_this"}
NUDGE_LABELS = {
    "back_on_it":    "Get back on it 🔥",
    "watching":      "We're watching 👀",
    "take_your_time": "Take your time ⏰",
    "you_got_this":  "You've got this 💪",
}


# ── NEW-1: Submit Finding ────────────────────────────────────

FINDING_RATE_LIMIT = 3  # per IP per hour


# ── EL-2: Experiment Library endpoint ───────────────────────

# ── EL-3/4: Experiment Vote POST handler ────────────────────

# ── EL-F1: Per-experiment follow (email interest) ─────────

# ── EL-F2: Single experiment detail endpoint ────────────────

# ── Router ──────────────────────────────────────────────────

# ── S3 config caches for data-driven pages ─────────────────
_protocols_cache = None
_challenges_cache = None
_challenge_catalog_cache = None
_domains_cache = None

def _load_s3_json(key, cache_name):
    """Load a JSON file from S3. Returns parsed dict. Cached per Lambda container."""
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        data = json.loads(resp["Body"].read())
        logger.info(f"[{cache_name}] Loaded from S3: {key}")
        return data
    except Exception as e:
        logger.warning(f"[{cache_name}] Failed to load {key}: {e}")
        return {}

# ── PULSE-A4: Pulse endpoint ───────────────────────────────────────────────

def handle_protocols() -> dict:
    """GET /api/protocols — Return protocol definitions from DynamoDB."""
    protocols_pk = f"{USER_PREFIX}protocols"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(protocols_pk) & Key("sk").begins_with("PROTOCOL#"),
            ScanIndexForward=True,
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
    """GET /api/habit_registry — Return habit registry from DynamoDB PROFILE#v1."""
    try:
        resp = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        profile = resp.get("Item", {})
        registry = profile.get("habit_registry", {})
        habits = []
        for name, meta in registry.items():
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


# ── Observatory API endpoints ────────────────────────────────────────────────

def handle_ai_analysis() -> dict:
    """
    GET /api/ai_analysis?expert=mind|nutrition|training|physical
    Returns cached AI expert analysis from DynamoDB.
    Cache: 300s.
    """
    # Note: query params handled in lambda_handler before ROUTES dispatch
    # This function is not directly called via ROUTES; handled specially
    pass


# ── BL-02: Bloodwork/Labs endpoint ─────────────────────────────
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


# ── Frequent Meals endpoint ───────────────────────────────────
# ── Meal Glucose Response endpoint ─────────────────────────────
# ── Strength Benchmarks endpoint ──────────────────────────────
# ── Phase 1: Changes-Since endpoint ─────────────────────────────
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

    from datetime import datetime, timezone, timedelta
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
        weights = [float(i.get("weight_kg", 0)) * 2.20462 for i in withings_items
                    if i.get("weight_kg") and float(i.get("weight_kg", 0)) > 0]
        if len(weights) >= 2:
            spark = weights[-7:] if len(weights) > 7 else weights
            deltas["weight"] = {
                "from": round(weights[0], 1), "to": round(weights[-1], 1),
                "change": round(weights[-1] - weights[0], 1), "unit": "lbs",
                "sparkline": [round(w, 1) for w in spark],
            }

        # HRV delta
        hrvs = [float(i.get("hrv", 0)) for i in whoop_items if i.get("hrv") and float(i.get("hrv", 0)) > 0]
        if len(hrvs) >= 2:
            spark = hrvs[-7:] if len(hrvs) > 7 else hrvs
            trend = "climbing" if hrvs[-1] > hrvs[0] else "declining" if hrvs[-1] < hrvs[0] else "stable"
            deltas["hrv"] = {
                "from": round(hrvs[0]), "to": round(hrvs[-1]),
                "change": round(hrvs[-1] - hrvs[0]), "unit": "ms",
                "trend": trend, "sparkline": [round(h) for h in spark],
            }

        # Sleep delta
        sleeps = [float(i.get("sleep_duration_hours", 0)) for i in whoop_items
                  if i.get("sleep_duration_hours") and float(i.get("sleep_duration_hours", 0)) > 0]
        if len(sleeps) >= 2:
            spark = sleeps[-7:] if len(sleeps) > 7 else sleeps
            trend = "improving" if sleeps[-1] > sleeps[0] else "declining"
            deltas["sleep"] = {
                "from": round(sleeps[0], 1), "to": round(sleeps[-1], 1),
                "change": round(sleeps[-1] - sleeps[0], 1), "unit": "hrs",
                "trend": trend, "sparkline": [round(s, 1) for s in spark],
            }
    except Exception as e:
        logger.warning(f"[changes-since] DynamoDB query failed: {e}")

    # Character delta
    try:
        char_items = _query_source("character_sheet", start_date, end_date)
        scores = [float(i.get("overall_score", 0)) for i in char_items if i.get("overall_score")]
        if len(scores) >= 2:
            deltas["character"] = {
                "from": round(scores[0]), "to": round(scores[-1]),
                "change": round(scores[-1] - scores[0]), "unit": "pts",
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
                events_list.append({
                    "type": "experiment_complete",
                    "title": e.get("name", "Experiment"),
                    "link": "/experiments/",
                    "date": e.get("sk", "").replace("DATE#", ""),
                })
    except Exception:
        pass

    return _ok({
        "since": since_dt.isoformat(),
        "days_ago": days_ago,
        "deltas": deltas,
        "events": events_list[:5],
    }, cache_seconds=300)


# ── Phase 1: Observatory Week endpoint ─────────────────────────
def handle_observatory_week(qs: dict = None) -> dict:
    """GET /api/observatory_week?domain=sleep — Returns 7-day summary for a domain."""
    qs = qs or {}
    domain = (qs.get("domain") or "sleep").lower().strip()
    valid_domains = {"sleep", "glucose", "nutrition", "training", "mind", "physical"}
    if domain not in valid_domains:
        return _error(400, f"Invalid domain. Use: {', '.join(sorted(valid_domains))}")

    from datetime import datetime, timezone, timedelta
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

            eff_vals = [float(i.get("sleep_quality_score") or i.get("sleep_efficiency_pct") or 0)
                       for i in items if i.get("sleep_quality_score") or i.get("sleep_efficiency_pct")]
            best_eff = max(eff_vals) if eff_vals else None

            summary = {
                "primary": {"label": "Average Duration", "value": round(avg_dur, 1), "unit": "hrs",
                            "delta": round(avg_dur - prev_avg, 1), "delta_label": f"vs {round(prev_avg, 1)} last week",
                            "trend": "up" if avg_dur > prev_avg else "down", "sparkline": [round(d, 1) for d in durations]},
                "highlight": {"label": "Best Night", "value": f"{best.get('sk', '').replace('DATE#', '')[5:]} · {round(float(best.get('sleep_duration_hours', 0)), 1)}h",
                              "detail": f"Recovery {round(float(best.get('recovery_score', 0)))}%"},
                "lowlight": {"label": "Worst Night", "value": f"{worst.get('sk', '').replace('DATE#', '')[5:]} · {round(float(worst.get('sleep_duration_hours', 0)), 1)}h",
                             "detail": ""},
                "best_efficiency": round(best_eff) if best_eff else None,
            }
            notable = f"Avg sleep {'improved' if avg_dur > prev_avg else 'declined'} {abs(round(avg_dur - prev_avg, 1))}h vs last week"

        elif domain == "nutrition":
            items = _query_source("macrofactor", start_date, end_date)
            prev_items = _query_source("macrofactor", prev_start, prev_end)

            cals = [float(i.get("total_calories_kcal") or i.get("calories") or 0) for i in items if i.get("total_calories_kcal") or i.get("calories")]
            prev_cals = [float(i.get("total_calories_kcal") or i.get("calories") or 0) for i in prev_items if i.get("total_calories_kcal") or i.get("calories")]
            avg_cal = sum(cals) / len(cals) if cals else 0
            prev_avg_cal = sum(prev_cals) / len(prev_cals) if prev_cals else 0
            proteins = [float(i.get("total_protein_g") or i.get("protein_g") or 0) for i in items if i.get("total_protein_g") or i.get("protein_g")]
            avg_protein = sum(proteins) / len(proteins) if proteins else 0

            summary = {
                "primary": {"label": "Avg Calories", "value": round(avg_cal), "unit": "kcal",
                            "delta": round(avg_cal - prev_avg_cal), "delta_label": f"vs {round(prev_avg_cal)} last week",
                            "trend": "up" if avg_cal > prev_avg_cal else "down", "sparkline": [round(c) for c in cals]},
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
                "primary": {"label": "Avg Strain", "value": round(avg_strain, 1), "unit": "",
                            "delta": 0, "delta_label": "", "trend": "flat",
                            "sparkline": [round(s, 1) for s in strains]},
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
                "primary": {"label": "Avg TIR", "value": round(avg_tir, 1), "unit": "%",
                            "delta": 0, "delta_label": "", "trend": "flat",
                            "sparkline": [round(t, 1) for t in tirs]},
                "highlight": {"label": "Best Day", "value": f"{round(max(tirs))}% TIR" if tirs else "\u2014", "detail": f"Avg glucose {round(avg_glucose)} mg/dL" if avg_glucose else ""},
                "lowlight": {"label": "Worst Day", "value": f"{round(min(tirs))}% TIR" if tirs else "\u2014", "detail": ""},
            }
            notable = f"Average time-in-range {round(avg_tir)}% this week"

        elif domain == "mind":
            items = _query_source("journal", start_date, end_date)
            moods = [float(i.get("mood_valence", 0)) for i in items if i.get("mood_valence") is not None]
            avg_mood = sum(moods) / len(moods) if moods else 0

            summary = {
                "primary": {"label": "Avg Mood", "value": round(avg_mood, 2), "unit": "",
                            "delta": 0, "delta_label": "", "trend": "flat",
                            "sparkline": [round(m, 2) for m in moods]},
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
                    "primary": {"label": "Weight Change", "value": round(end_w), "unit": "lbs",
                                "delta": delta, "delta_label": f"{delta:+.1f} lbs this week",
                                "trend": "down" if delta < 0 else "up", "sparkline": [round(w) for w in weights]},
                    "highlight": {"label": "Weigh-ins", "value": str(len(weights)), "detail": "this week"},
                    "lowlight": {"label": "Current", "value": f"{round(end_w)} lbs", "detail": ""},
                }
                notable = f"Weight {'dropped' if delta < 0 else 'gained'} {abs(delta)} lbs this week"
            else:
                summary = {
                    "primary": {"label": "Weight", "value": None, "unit": "lbs", "delta": 0, "delta_label": "", "trend": "flat", "sparkline": []},
                    "highlight": {"label": "Weigh-ins", "value": "0", "detail": "this week"},
                    "lowlight": {"label": "", "value": "", "detail": ""},
                }
                notable = "No weigh-ins recorded this week"

        else:
            return _error(400, "Unsupported domain")

        return _ok({
            "domain": domain,
            "period": {"start": start_date, "end": end_date},
            "summary": summary,
            "notable": notable,
            "last_updated": now.isoformat(),
        }, cache_seconds=900)

    except Exception as e:
        logger.warning(f"[observatory_week] {domain} failed: {e}")
        return _error(503, f"Weekly {domain} data temporarily unavailable.")


# ── Benchmark trends endpoint ─────────────────────────────────
# ── Meal responses endpoint ───────────────────────────────────
# ── Experiment suggestion POST handler ────────────────────────
ROUTES = {
    "/api/vitals":          handle_vitals,
    "/api/journey":         handle_journey,
    "/api/character":       handle_character,
    "/api/status":          handle_status,
    "/api/status/summary":  handle_status_summary,
    # BS-07: new public endpoints
    "/api/weight_progress": handle_weight_progress,
    "/api/character_stats": handle_character_stats,
    "/api/habit_streaks":   handle_habit_streaks,
    "/api/experiments":        handle_experiments,
    "/api/current_challenge":  handle_current_challenge,
    # Sprint 4: BS-11, WEB-CE, BS-BM2
    "/api/timeline":           handle_timeline,
    "/api/correlations":       handle_correlations,
    "/api/genome_risks":       handle_genome_risks,
    # Sprint 9: new public endpoints
    "/api/supplements":        handle_supplements,
    "/api/habits":             handle_habits,
    "/api/vice_streaks":       handle_vice_streaks,
    "/api/journey_timeline":   handle_journey_timeline,
    "/api/journey_waveform":   handle_journey_waveform,
    # Sprint 11: glucose + sleep intelligence pages
    "/api/glucose":            handle_glucose,
    "/api/sleep_detail":       handle_sleep_detail,
    # ARCH-03: Achievement badges
    "/api/achievements":       handle_achievements,
    # ARCH-02: Combined snapshot — single-call summary for pages that need vitals + journey + character
    "/api/snapshot":           handle_snapshot,
    # WR-24 + S2-T2-2: handled specially in lambda_handler (POST routes)
    "/api/verify_subscriber":  None,
    "/api/board_ask":          None,
    "/api/submit_finding":     None,  # NEW-1: POST handler in lambda_handler
    # EL-2: Experiment library (GET) + EL-3: Experiment vote (POST)
    "/api/experiment_library":  handle_experiment_library,
    "/api/experiment_vote":     None,  # POST handler in lambda_handler
    "/api/experiment_follow":   None,  # EL-F1: POST handler in lambda_handler
    "/api/experiment_detail":   None,  # EL-F2: GET with query params
    # DATA-DRIVEN: S3 config + DynamoDB source-of-truth endpoints
    "/api/protocols":          handle_protocols,
    "/api/challenges":         handle_challenges,
    "/api/challenge_catalog":  handle_challenge_catalog,
    "/api/challenge_vote":     None,  # POST handler in lambda_handler
    "/api/challenge_follow":   None,  # POST handler in lambda_handler
    "/api/challenge_checkin":  None,  # POST handler in lambda_handler
    "/api/domains":            handle_domains,
    "/api/habit_registry":     handle_habit_registry,
    # PULSE-A4: Daily pulse endpoint
    "/api/pulse":              handle_pulse,
    "/api/pulse_history":      handle_pulse_history,
    # Subscriber count social proof (read-only) — must NOT match /api/subscribe* CloudFront pattern
    "/api/sub_count":          handle_subscriber_count,
    # Observatory pages
    "/api/nutrition_overview":  handle_nutrition_overview,
    "/api/training_overview":   handle_training_overview,
    "/api/mind_overview":       handle_mind_overview,
    "/api/physical_overview":   handle_physical_overview,
    "/api/journal_analysis":    handle_journal_analysis,
    "/api/ai_analysis":         None,  # GET with ?expert= query param, handled in lambda_handler
    "/api/coach_analysis":      None,  # GET with ?domain= query param, handled in lambda_handler (Coach Intelligence)
    "/api/weekly_priority":     None,  # GET — integrator synthesis, handled in lambda_handler
    # BL-03: The Ledger / Snake Fund
    "/api/ledger":              handle_ledger,
    # BL-04: Field Notes
    "/api/field_notes":         None,  # GET with optional ?week= query param, handled in lambda_handler
    # BL-02: Bloodwork/Labs
    "/api/labs":                handle_labs,
    "/api/frequent_meals":      handle_frequent_meals,
    "/api/protein_sources":     handle_protein_sources,
    "/api/weekly_physical_summary": handle_weekly_physical_summary,
    "/api/strength_deep_dive":      handle_strength_deep_dive,
    "/api/food_delivery_overview":  handle_food_delivery_overview,
    "/api/meal_glucose":        handle_meal_glucose,
    "/api/strength_benchmarks": handle_strength_benchmarks,
    # Benchmark trends + meal responses (stub endpoints)
    "/api/benchmark_trends":    handle_benchmark_trends,
    "/api/meal_responses":      handle_meal_responses,
    # Tools page: baseline vs current comparison
    "/api/tools_baseline":      handle_tools_baseline,
    # Platform stats: single source of truth for all site pages
    "/api/platform_stats":      handle_platform_stats,
    # Discoveries page: active hypotheses + inner life + AI findings
    "/api/discoveries":         handle_discoveries,
    # Experiment suggestion (POST)
    "/api/experiment_suggest":  None,  # POST handler in lambda_handler
    # Phase 1: Reader engagement
    "/api/changes-since":       None,  # GET with ?ts= query param
    "/api/observatory_week":    None,  # GET with ?domain= query param
    # Coaching Dashboard
    "/api/coaching-dashboard":  None,  # GET — assembled coaching dashboard data
    # Prediction Ledger + Coach Timeline
    "/api/predictions":         None,  # GET with ?status=&coach_id=&limit= query params
    "/api/coach_timeline":      None,  # GET with ?coach_id= query param
}


_COLD_START = True


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4.5 SCOPED (2026-05-16): router dispatch table
# ═══════════════════════════════════════════════════════════════════════════
# Replaces 14 sequential `if path == "..."` / method-check / delegate branches
# in lambda_handler with a single dict lookup. Each entry is:
#   path → (allowed_methods, handler_fn)
# where allowed_methods is a set (or None for "any method").
#
# Only "simple delegate" routes are captured here. Complex routes (those that
# inline query-param logic, multi-step DDB queries, or branch on event shape)
# stay inline in lambda_handler. Full router-with-handler-extraction is the
# multi-week P4.5 work; this is the scoped subset that pays for itself today.

_SIMPLE_ROUTES = {
    "/api/verify_subscriber": ({"GET", "OPTIONS"}, _handle_verify_subscriber),
    "/api/nudge":             ({"POST"},           _handle_nudge),
    "/api/submit_finding":    ({"POST"},           _handle_submit_finding),
    "/api/experiment_vote":   ({"POST"},           _handle_experiment_vote),
    "/api/experiment_follow": ({"POST"},           _handle_experiment_follow),
    "/api/experiment_suggest": ({"POST"},           _handle_experiment_suggest),
    "/api/challenge_checkin": ({"POST"},           _handle_challenge_checkin),
    "/api/challenge_vote":    ({"POST"},           _handle_challenge_vote),
    "/api/challenge_follow":  ({"POST"},           _handle_challenge_follow),
    "/api/experiment_detail": (None,               _handle_experiment_detail),
}


def lambda_handler(event, context):
    """
    Main Lambda handler. Supports both API Gateway HTTP API and Function URL events.
    """
    import time as _time
    import uuid as _uuid
    _req_start = _time.time()

    path = event.get("rawPath") or event.get("path", "/")
    method = (event.get("requestContext", {}).get("http", {}).get("method") or
              event.get("httpMethod", "GET")).upper()

    # P3.4: assign a per-request correlation ID. Honor an inbound x-request-id
    # header if the client (CloudFront / a debugging operator) set one — this
    # lets the same id flow end-to-end. Otherwise generate a fresh uuid4.
    inbound_headers = event.get("headers") or {}
    incoming_rid = (inbound_headers.get("x-request-id") or inbound_headers.get("X-Request-Id"))
    set_request_id(incoming_rid if incoming_rid else _uuid.uuid4().hex[:16])

    # Phase 2.2 (2026-05-16): centralized request envelope validation.
    # Catches oversized bodies, injection patterns, malformed user_id/date/source
    # before any handler runs. Returns 4xx for obvious abuse; legit traffic unaffected.
    try:
        from request_validator import validate_envelope, ValidationError
        validate_envelope(event, path=path, method=method)
    except ImportError:
        pass  # Validator not yet deployed; fall through to legacy behavior
    except Exception as _ve:
        # Imported as ValidationError above when import succeeds
        if _ve.__class__.__name__ == "ValidationError":
            return {
                "statusCode": getattr(_ve, "status", 400),
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": getattr(_ve, "message", str(_ve))}),
            }
        raise

    def _emit_route_log(status_code):
        """Emit structured JSON route metric to CloudWatch Logs.

        Uses CloudWatch EMF (Embedded Metric Format) so per-route latency is
        auto-extracted as a real CloudWatch metric (no PutMetricData cost).
        Dimensions: Route + Method. The Logs Insights query can pivot on either
        via the JSON object — same line, two consumers.
        """
        global _COLD_START
        try:
            duration_ms = round((_time.time() - _req_start) * 1000, 1)
            emf = {
                # _aws block → CloudWatch automatically ingests the named
                # fields as metrics. Cheap (≤ 5 dimension sets, no API call).
                "_aws": {
                    "Timestamp": int(_time.time() * 1000),
                    "CloudWatchMetrics": [{
                        "Namespace": "LifePlatform/SiteAPI",
                        "Dimensions": [["Route", "Method"]],
                        "Metrics": [
                            {"Name": "DurationMs", "Unit": "Milliseconds"},
                            {"Name": "ColdStart", "Unit": "Count"},
                        ],
                    }],
                },
                "_type":      "route_metric",
                "Route":      path,
                "Method":     method,
                "status":     status_code,
                "DurationMs": duration_ms,
                "ColdStart":  1 if _COLD_START else 0,
                "request_id": get_request_id(),
                "duration_ms": duration_ms,  # back-compat field name
                "cold_start":  _COLD_START,
            }
            print(json.dumps(emf))
        except Exception:
            pass
        _COLD_START = False

    # CORS preflight
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # /api/healthz — lightweight health check (no auth, no PII)
    if path == "/api/healthz" and method == "GET":
        try:
            ddb_start = _time.time()
            table.get_item(Key={"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-01-01"})
            ddb_ms = round((_time.time() - ddb_start) * 1000)
            ddb_ok = True
        except Exception:
            ddb_ms = -1
            ddb_ok = False
        try:
            s3_client = boto3.client("s3", region_name=S3_REGION)
            stats_obj = s3_client.get_object(Bucket=os.environ.get("S3_BUCKET", "matthew-life-platform"), Key="generated/public_stats.json")
            refreshed = json.loads(stats_obj["Body"].read()).get("_meta", {}).get("refreshed_at", "unknown")
        except Exception:
            refreshed = "unavailable"
        total_ms = round((_time.time() - _req_start) * 1000)
        health = {
            "status": "ok" if ddb_ok else "degraded",
            "version": "v4.5.1",
            "checks": {
                "dynamodb": {"status": "ok" if ddb_ok else "error", "latency_ms": ddb_ms},
                "last_daily_refresh": refreshed,
                "lambda_warm": not _COLD_START,
            },
            "response_ms": total_ms,
        }
        _emit_route_log(200)
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps(health)}

    # SEC-04: Reject requests that didn't come through CloudFront (when secret is configured).
    if SITE_API_ORIGIN_SECRET:
        req_headers = event.get("headers") or {}
        incoming = req_headers.get("x-amj-origin") or req_headers.get("X-AMJ-Origin") or ""
        import hmac as _hmac
        if not _hmac.compare_digest(incoming, SITE_API_ORIGIN_SECRET):
            return _error(403, "Forbidden")

    # Phase 4.5 SCOPED (2026-05-16): single dispatch for 11 simple delegate
    # routes. The complex inline routes (correlations, changes_since, etc.)
    # remain below — they include query-param parsing or multi-step logic.
    _route_entry = _SIMPLE_ROUTES.get(path)
    if _route_entry:
        _allowed_methods, _handler_fn = _route_entry
        if _allowed_methods is not None and method not in _allowed_methods:
            return _error(405, f"Method not allowed; use {'/'.join(sorted(_allowed_methods))}")
        return _handler_fn(event)

    # HP-06: Correlations with optional ?featured=true&limit=N
    if path == "/api/correlations":
        return handle_correlations(event)

    # Phase 1: Changes-since (GET with query params)
    if path == "/api/changes-since":
        qs = event.get("queryStringParameters") or {}
        return handle_changes_since(qs)

    # Phase 1: Observatory week (GET with query params)
    if path == "/api/observatory_week":
        qs = event.get("queryStringParameters") or {}
        return handle_observatory_week(qs)

    # BL-04: Field Notes (GET with optional ?week= query param)
    if path == "/api/field_notes":
        qs = event.get("queryStringParameters") or {}
        week_param = qs.get("week")
        fn_pk = f"{USER_PREFIX}field_notes"

        if week_param:
            # Single entry mode
            item = table.get_item(Key={"pk": fn_pk, "sk": f"WEEK#{week_param}"}).get("Item")
            if not item:
                return _ok({"entry": None, "week": week_param}, cache_seconds=300)
            item = _decimal_to_float(item)
            return _ok({"entry": {
                "week": item.get("week", week_param),
                "ai_present": item.get("ai_present", ""),
                "ai_cautionary": item.get("ai_cautionary"),
                "ai_affirming": item.get("ai_affirming"),
                "ai_tone": item.get("ai_tone", "mixed"),
                "ai_generated_at": item.get("ai_generated_at"),
                "matthew_agreement": item.get("matthew_agreement"),
                "matthew_logged_at": item.get("matthew_logged_at"),
            }}, cache_seconds=300)
        else:
            # List mode — return all weeks (most recent first)
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(fn_pk),
                ScanIndexForward=False,
                Limit=52,
            )
            items = _decimal_to_float(resp.get("Items", []))
            entries = [{
                "week": i.get("week", i.get("sk", "").replace("WEEK#", "")),
                "ai_tone": i.get("ai_tone", "mixed"),
                "ai_generated_at": i.get("ai_generated_at"),
                "has_matthew_response": bool(i.get("matthew_agreement")),
            } for i in items]
            return _ok({"entries": entries, "count": len(entries)}, cache_seconds=300)

    # AI Analysis (GET with ?expert= query param)
    if path == "/api/ai_analysis":
        qs = event.get("queryStringParameters") or {}
        expert_key = qs.get("expert", "mind")
        if expert_key not in ("mind", "nutrition", "training", "physical", "explorer", "labs", "glucose", "sleep"):
            return _error(400, "Invalid expert key")
        ai_pk = f"{USER_PREFIX}ai_analysis"
        ai_item = table.get_item(Key={"pk": ai_pk, "sk": f"EXPERT#{expert_key}"}).get("Item")
        if not ai_item:
            return _ok({"expert_key": expert_key, "analysis": None, "generated_at": None}, cache_seconds=300)
        ai_item = _decimal_to_float(ai_item)
        analysis_val = ai_item.get("analysis", "")
        if "[AI_UNAVAILABLE]" in (analysis_val or ""):
            analysis_val = None
        resp_data = {
            "expert_key": expert_key,
            "analysis": analysis_val,
            "generated_at": ai_item.get("generated_at", ""),
        }
        if ai_item.get("key_recommendation"):
            resp_data["key_recommendation"] = ai_item["key_recommendation"]
        if ai_item.get("journaling_prompt"):
            resp_data["journaling_prompt"] = ai_item["journaling_prompt"]
        if ai_item.get("elena_quote"):
            resp_data["elena_quote"] = ai_item["elena_quote"]
        if ai_item.get("week_number"):
            resp_data["week_number"] = int(ai_item["week_number"])
        if ai_item.get("days_in_experiment"):
            resp_data["days_in_experiment"] = int(ai_item["days_in_experiment"])
        return _ok(resp_data, cache_seconds=300)

    # Coach Intelligence Analysis (GET with ?domain= query param)
    if path == "/api/coach_analysis":
        qs = event.get("queryStringParameters") or {}
        domain = qs.get("domain", "sleep")
        _coach_map = {
            "sleep": "sleep_coach", "nutrition": "nutrition_coach", "training": "training_coach",
            "mind": "mind_coach", "physical": "physical_coach", "glucose": "glucose_coach",
            "labs": "labs_coach", "explorer": "explorer_coach",
        }
        coach_id = _coach_map.get(domain)
        if not coach_id:
            return _error(400, "Invalid domain")

        _coach_display = {
            "sleep_coach": {"name": "Dr. Lisa Park", "initials": "LP", "title": "Sleep & Circadian Rhythm Specialist", "color": "#818cf8"},
            "nutrition_coach": {"name": "Dr. Marcus Webb", "initials": "MW", "title": "Evidence-Based Nutrition", "color": "#10b981"},
            "training_coach": {"name": "Dr. Sarah Chen", "initials": "SC", "title": "Exercise Physiology & Strength", "color": "#3db88a"},
            "mind_coach": {"name": "Dr. Nathan Reeves", "initials": "NR", "title": "Psychiatrist \u2014 Behavioral Patterns", "color": "#a78bfa"},
            "physical_coach": {"name": "Dr. Victor Reyes", "initials": "VR", "title": "Longevity & Body Composition", "color": "#f59e0b"},
            "glucose_coach": {"name": "Dr. Amara Patel", "initials": "AP", "title": "Metabolic Health & CGM", "color": "#2dd4bf"},
            "labs_coach": {"name": "Dr. James Okafor", "initials": "JO", "title": "Clinical Pathology & Preventive Labs", "color": "#5ba4cf"},
            "explorer_coach": {"name": "Dr. Henning Brandt", "initials": "HB", "title": "Biostatistics & N=1 Research", "color": "#e879f9"},
        }

        try:
            coach_pk = f"COACH#{coach_id}"

            # 1. Most recent OUTPUT# record
            out_resp = table.query(
                KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("OUTPUT#"),
                ScanIndexForward=False, Limit=1,
            )
            out_items = out_resp.get("Items", [])
            if not out_items:
                return _ok({"coach_id": coach_id, "domain": domain, "analysis": None}, cache_seconds=300)

            output = _decimal_to_float(out_items[0])
            # Prefer observatory_summary over full content
            analysis_text = output.get("observatory_summary") or output.get("content", "")
            if "[AI_UNAVAILABLE]" in (analysis_text or ""):
                analysis_text = None

            # 2. Open threads
            thread_reference = None
            try:
                thread_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("THREAD#"),
                )
                threads = [_decimal_to_float(t) for t in thread_resp.get("Items", []) if t.get("status") == "open"]
                if threads:
                    # Pick most recently referenced thread
                    threads.sort(key=lambda t: t.get("last_referenced", ""), reverse=True)
                    thread_reference = threads[0].get("summary", "")
            except Exception:
                pass

            # 3. Ensemble digest — cross-coach references
            cross_coach_reference = None
            try:
                dig_resp = table.query(
                    KeyConditionExpression=Key("pk").eq("ENSEMBLE#digest") & Key("sk").begins_with("CYCLE#"),
                    ScanIndexForward=False, Limit=1,
                )
                dig_items = dig_resp.get("Items", [])
                if dig_items:
                    digest = _decimal_to_float(dig_items[0])
                    disagreements = digest.get("active_disagreements", [])
                    for d in disagreements:
                        coaches = d.get("coaches", [])
                        if coach_id in coaches:
                            cross_coach_reference = d.get("topic", "")
                            break
            except Exception:
                pass

            # 4. Computation guardrails — data availability
            data_availability = "preliminary"
            try:
                comp_resp = table.query(
                    KeyConditionExpression=Key("pk").eq("COACH#computation") & Key("sk").begins_with("RESULTS#"),
                    ScanIndexForward=False, Limit=1,
                )
                comp_items = comp_resp.get("Items", [])
                if comp_items:
                    guardrails = _decimal_to_float(comp_items[0]).get("statistical_guardrails", {})
                    # Find the guardrail for this domain's primary source
                    for source_name, source_guardrails in guardrails.items():
                        if isinstance(source_guardrails, dict):
                            for metric, g in source_guardrails.items():
                                if isinstance(g, dict):
                                    data_availability = g.get("data_availability", "preliminary")
                                    break
                            break
            except Exception:
                pass

            # 5. Revision signal — recent learning records
            revision_signal = None
            try:
                learn_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("LEARNING#"),
                    ScanIndexForward=False, Limit=3,
                )
                for item in learn_resp.get("Items", []):
                    item = _decimal_to_float(item)
                    if item.get("type") == "position_revision":
                        revision_signal = item.get("revised_position", "")[:100]
                        break
            except Exception:
                pass

            # 6. Confidence language
            confidence_language = "preliminary"
            try:
                themes = output.get("themes", [])
                # Use the overall confidence from the generation if available
                conf = output.get("confidence")
                if conf is not None:
                    conf_f = float(conf)
                    if conf_f >= 0.85:
                        confidence_language = "highly_confident"
                    elif conf_f >= 0.7:
                        confidence_language = "fairly_confident"
                    elif conf_f >= 0.5:
                        confidence_language = "moderate"
                    elif conf_f >= 0.3:
                        confidence_language = "preliminary"
                    else:
                        confidence_language = "uncertain"
            except Exception:
                pass

            display = _coach_display.get(coach_id, {})
            resp = {
                "coach_id": coach_id,
                "coach_name": display.get("name", ""),
                "coach_initials": display.get("initials", ""),
                "coach_title": display.get("title", ""),
                "coach_color": display.get("color", ""),
                "domain": domain,
                "analysis": analysis_text,
                "key_recommendation": output.get("key_recommendation") or (
                    output.get("themes", [""])[0] if output.get("themes") else None
                ),
                "elena_quote": output.get("elena_quote"),
                "journaling_prompt": output.get("journaling_prompt"),
                "thread_reference": thread_reference,
                "revision_signal": revision_signal,
                "cross_coach_reference": cross_coach_reference,
                "confidence_language": confidence_language,
                "data_availability": data_availability,
                "generated_at": output.get("created_at") or output.get("generated_at", ""),
                "week_number": output.get("week_number"),
                "days_in_experiment": output.get("days_in_experiment"),
            }

            # Add cross-domain context note from the integrator (if available)
            try:
                _int_resp = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"})
                _int_item = _decimal_to_float(_int_resp.get("Item", {}))
                _cdn = _int_item.get("cross_domain_notes", {})
                if isinstance(_cdn, dict) and domain in _cdn:
                    resp["cross_domain_note"] = _cdn[domain]
                if _int_item.get("analysis"):
                    resp["weekly_priority"] = _int_item["analysis"]
            except Exception:
                pass

            # Strip None values for cleaner JSON
            resp = {k: v for k, v in resp.items() if v is not None}
            return _ok(resp, cache_seconds=300)
        except Exception as _e:
            print(f"[WARN] /api/coach_analysis failed: {_e}")
            return _ok({"coach_id": coach_id, "domain": domain, "analysis": None}, cache_seconds=60)

    # Coaching Dashboard (GET — assembled dashboard data)
    if path == "/api/coaching-dashboard":
        try:
            _cd_coach_display = {
                "sleep": {"coach_id": "sleep", "name": "Dr. Lisa Park", "initials": "LP", "title": "Sleep & Circadian Rhythm Specialist", "color": "#818cf8", "observatory_link": "/sleep/"},
                "nutrition": {"coach_id": "nutrition", "name": "Dr. Marcus Webb", "initials": "MW", "title": "Evidence-Based Nutrition", "color": "#10b981", "observatory_link": "/nutrition/"},
                "training": {"coach_id": "training", "name": "Dr. Sarah Chen", "initials": "SC", "title": "Exercise Physiology & Strength", "color": "#3db88a", "observatory_link": "/training/"},
                "mind": {"coach_id": "mind", "name": "Dr. Nathan Reeves", "initials": "NR", "title": "Psychiatrist — Behavioral Patterns", "color": "#a78bfa", "observatory_link": "/mind/"},
                "physical": {"coach_id": "physical", "name": "Dr. Victor Reyes", "initials": "VR", "title": "Longevity & Body Composition", "color": "#f59e0b", "observatory_link": "/physical/"},
                "glucose": {"coach_id": "glucose", "name": "Dr. Amara Patel", "initials": "AP", "title": "Metabolic Health & CGM", "color": "#2dd4bf", "observatory_link": "/glucose/"},
                "labs": {"coach_id": "labs", "name": "Dr. James Okafor", "initials": "JO", "title": "Clinical Pathology & Preventive Labs", "color": "#5ba4cf", "observatory_link": "/labs/"},
                "explorer": {"coach_id": "explorer", "name": "Dr. Henning Brandt", "initials": "HB", "title": "Biostatistics & N=1 Research", "color": "#e879f9", "observatory_link": "/explorer/"},
            }
            _cd_coach_id_map = {
                "sleep": "sleep_coach", "nutrition": "nutrition_coach", "training": "training_coach",
                "mind": "mind_coach", "physical": "physical_coach", "glucose": "glucose_coach",
                "labs": "labs_coach", "explorer": "explorer_coach",
            }

            # 1. Weekly priority from integrator
            _cd_priority = {"text": None, "coach_name": "Dr. Kai Nakamura", "generated_at": None}
            try:
                _cd_int = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"}).get("Item")
                if _cd_int:
                    _cd_int = _decimal_to_float(_cd_int)
                    _cd_priority["text"] = _cd_int.get("analysis", "")
                    _cd_priority["generated_at"] = _cd_int.get("generated_at", "")
            except Exception:
                pass

            # 2. Open actions from coach_actions source
            _cd_actions = []
            try:
                _cd_act_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}coach_actions"),
                    Limit=50,
                )
                for _act in _cd_act_resp.get("Items", []):
                    _act = _decimal_to_float(_act)
                    if _act.get("status") == "open":
                        _cd_actions.append({
                            "coach_id": _act.get("coach_id", ""),
                            "domain": _act.get("domain", ""),
                            "action_text": _act.get("action_text", _act.get("action", "")),
                            "issued_date": _act.get("issued_date", _act.get("sk", "").replace("DATE#", "")),
                            "status": "open",
                        })
            except Exception:
                pass

            # 3. Coach thread summaries + predictions
            _cd_coaches = []
            _cd_predictions = []
            for _cd_domain, _cd_info in _cd_coach_display.items():
                _cd_coach_pk = f"COACH#{_cd_coach_id_map[_cd_domain]}"
                coach_entry = dict(_cd_info)
                coach_entry["position_summary"] = ""
                coach_entry["emotional_investment"] = "neutral"
                coach_entry["prediction_count"] = 0
                coach_entry["data_phase"] = "established"

                # Latest output for position_summary
                try:
                    _cd_out = table.query(
                        KeyConditionExpression=Key("pk").eq(_cd_coach_pk) & Key("sk").begins_with("OUTPUT#"),
                        ScanIndexForward=False, Limit=1,
                    )
                    _cd_out_items = _cd_out.get("Items", [])
                    if _cd_out_items:
                        _cd_out_item = _decimal_to_float(_cd_out_items[0])
                        coach_entry["position_summary"] = (
                            _cd_out_item.get("position_summary")
                            or _cd_out_item.get("observatory_summary", "")[:200]
                            or _cd_out_item.get("content", "")[:200]
                        )
                        coach_entry["emotional_investment"] = _cd_out_item.get("emotional_investment", "neutral")
                        # Count predictions
                        preds = _cd_out_item.get("predictions", [])
                        if isinstance(preds, list):
                            coach_entry["prediction_count"] = len(preds)
                            for _p in preds[-3:]:
                                if isinstance(_p, dict):
                                    _cd_predictions.append({
                                        "coach_id": _cd_domain,
                                        "text": _p.get("text", _p.get("prediction", "")),
                                        "confidence": _p.get("confidence", "medium"),
                                        "status": _p.get("status", "pending"),
                                        "date": _cd_out_item.get("sk", "").replace("OUTPUT#", ""),
                                    })
                except Exception:
                    pass

                _cd_coaches.append(coach_entry)

            # Sort coaches: invested/concerned first, then neutral
            _ei_order = {"concerned": 0, "invested": 1, "curious": 2, "neutral": 3}
            _cd_coaches.sort(key=lambda c: _ei_order.get(c.get("emotional_investment", "neutral"), 3))

            # Limit predictions to 10 most recent
            _cd_predictions = _cd_predictions[-10:]

            return _ok({
                "weekly_priority": _cd_priority,
                "open_actions": _cd_actions,
                "coaches": _cd_coaches,
                "predictions": _cd_predictions,
            }, cache_seconds=300)
        except Exception as _e:
            print(f"[WARN] /api/coaching-dashboard failed: {_e}")
            return _ok({"weekly_priority": {}, "open_actions": [], "coaches": [], "predictions": []}, cache_seconds=60)

    # Prediction Ledger (GET with query params)
    if path == "/api/predictions":
        try:
            qs = event.get("queryStringParameters") or {}
            status_filter = qs.get("status", "all")
            coach_filter = qs.get("coach_id", "")
            limit = min(int(qs.get("limit", "50")), 200)

            _pred_coach_names = {
                "sleep": "Dr. Lisa Park", "nutrition": "Dr. Marcus Webb",
                "training": "Dr. Sarah Chen", "mind": "Dr. Nathan Reeves",
                "physical": "Dr. Victor Reyes", "glucose": "Dr. Amara Patel",
                "labs": "Dr. James Okafor", "explorer": "Dr. Henning Brandt",
            }
            _pred_coach_ids = list(_pred_coach_names.keys())
            _pred_coach_id_map = {
                "sleep": "sleep_coach", "nutrition": "nutrition_coach",
                "training": "training_coach", "mind": "mind_coach",
                "physical": "physical_coach", "glucose": "glucose_coach",
                "labs": "labs_coach", "explorer": "explorer_coach",
            }

            if coach_filter and coach_filter not in _pred_coach_ids:
                return _error(400, "Invalid coach_id")

            scan_coaches = [coach_filter] if coach_filter else _pred_coach_ids
            all_predictions = []
            by_coach = {}

            for cid in scan_coaches:
                coach_pk = f"COACH#{_pred_coach_id_map[cid]}"
                by_coach[cid] = {"total": 0, "confirmed": 0, "refuted": 0, "pending": 0}

                try:
                    out_resp = table.query(
                        KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("OUTPUT#"),
                        ScanIndexForward=False,
                        Limit=12,
                    )
                    for out_item in out_resp.get("Items", []):
                        out_item = _decimal_to_float(out_item)
                        preds = out_item.get("predictions", [])
                        out_date = out_item.get("sk", "").replace("OUTPUT#", "")
                        if not isinstance(preds, list):
                            continue
                        for p in preds:
                            if not isinstance(p, dict):
                                continue
                            p_status = p.get("status", "pending")
                            by_coach[cid]["total"] += 1
                            if p_status in ("confirmed", "refuted", "pending"):
                                by_coach[cid][p_status] += 1
                            else:
                                by_coach[cid]["pending"] += 1

                            if status_filter != "all" and p_status != status_filter:
                                continue

                            all_predictions.append({
                                "coach_id": cid,
                                "coach_name": _pred_coach_names[cid],
                                "text": p.get("text", p.get("prediction", "")),
                                "confidence": p.get("confidence", "medium"),
                                "status": p_status,
                                "date": out_date,
                                "target_date": p.get("target_date", ""),
                            })
                except Exception:
                    pass

            # Sort predictions by date descending
            all_predictions.sort(key=lambda x: x.get("date", ""), reverse=True)
            all_predictions = all_predictions[:limit]

            # Compute overall stats
            total = sum(c["total"] for c in by_coach.values())
            confirmed = sum(c["confirmed"] for c in by_coach.values())
            refuted = sum(c["refuted"] for c in by_coach.values())
            pending = sum(c["pending"] for c in by_coach.values())
            resolved = confirmed + refuted
            accuracy_pct = round(confirmed / resolved * 100, 1) if resolved > 0 else 0

            return _ok({
                "overall": {
                    "total": total, "confirmed": confirmed,
                    "refuted": refuted, "pending": pending,
                    "accuracy_pct": accuracy_pct,
                },
                "by_coach": by_coach,
                "predictions": all_predictions,
            }, cache_seconds=300)
        except Exception as _e:
            print(f"[WARN] /api/predictions failed: {_e}")
            return _ok({"overall": {}, "by_coach": {}, "predictions": []}, cache_seconds=60)

    # Coach Learning Timeline (GET with ?coach_id= query param)
    if path == "/api/coach_timeline":
        try:
            qs = event.get("queryStringParameters") or {}
            coach_id = qs.get("coach_id", "")

            _tl_coach_names = {
                "sleep": "Dr. Lisa Park", "nutrition": "Dr. Marcus Webb",
                "training": "Dr. Sarah Chen", "mind": "Dr. Nathan Reeves",
                "physical": "Dr. Victor Reyes", "glucose": "Dr. Amara Patel",
                "labs": "Dr. James Okafor", "explorer": "Dr. Henning Brandt",
            }
            _tl_coach_id_map = {
                "sleep": "sleep_coach", "nutrition": "nutrition_coach",
                "training": "training_coach", "mind": "mind_coach",
                "physical": "physical_coach", "glucose": "glucose_coach",
                "labs": "labs_coach", "explorer": "explorer_coach",
            }

            if coach_id not in _tl_coach_names:
                return _error(400, "Invalid or missing coach_id")

            coach_pk = f"COACH#{_tl_coach_id_map[coach_id]}"
            milestones = []

            # Query OUTPUT# records for stance_changes, predictions, surprises, emotional_investment
            try:
                out_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("OUTPUT#"),
                    ScanIndexForward=False,
                    Limit=20,
                )
                prev_investment = None
                for out_item in out_resp.get("Items", []):
                    out_item = _decimal_to_float(out_item)
                    out_date = out_item.get("sk", "").replace("OUTPUT#", "")

                    # Stance changes
                    stance_changes = out_item.get("stance_changes", [])
                    if isinstance(stance_changes, list):
                        for sc in stance_changes:
                            if isinstance(sc, dict):
                                milestones.append({
                                    "date": out_date,
                                    "type": "stance_change",
                                    "text": sc.get("topic", sc.get("text", "Position revised")),
                                    "detail": sc.get("new_stance", sc.get("detail", "")),
                                })
                            elif isinstance(sc, str):
                                milestones.append({
                                    "date": out_date,
                                    "type": "stance_change",
                                    "text": sc,
                                    "detail": "",
                                })

                    # Resolved predictions
                    preds = out_item.get("predictions", [])
                    if isinstance(preds, list):
                        for p in preds:
                            if isinstance(p, dict) and p.get("status") in ("confirmed", "refuted"):
                                milestones.append({
                                    "date": out_date,
                                    "type": "prediction_resolved",
                                    "text": p.get("text", p.get("prediction", "")),
                                    "detail": f"Status: {p['status']}",
                                })

                    # Surprises
                    surprises = out_item.get("surprises", [])
                    if isinstance(surprises, list):
                        for s in surprises:
                            if isinstance(s, dict):
                                milestones.append({
                                    "date": out_date,
                                    "type": "surprise",
                                    "text": s.get("text", s.get("observation", "")),
                                    "detail": s.get("detail", s.get("significance", "")),
                                })
                            elif isinstance(s, str):
                                milestones.append({
                                    "date": out_date,
                                    "type": "surprise",
                                    "text": s,
                                    "detail": "",
                                })

                    # Emotional investment changes
                    current_investment = out_item.get("emotional_investment", "neutral")
                    if prev_investment and current_investment != prev_investment:
                        milestones.append({
                            "date": out_date,
                            "type": "investment_change",
                            "text": f"Investment shifted: {prev_investment} -> {current_investment}",
                            "detail": "",
                        })
                    prev_investment = current_investment

                    # Learning log entries
                    learning_log = out_item.get("learning_log", [])
                    if isinstance(learning_log, list):
                        for entry in learning_log:
                            if isinstance(entry, dict):
                                milestones.append({
                                    "date": out_date,
                                    "type": "stance_change",
                                    "text": entry.get("lesson", entry.get("text", "")),
                                    "detail": entry.get("detail", ""),
                                })
            except Exception:
                pass

            # Also check LEARNING# records
            try:
                learn_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with("LEARNING#"),
                    ScanIndexForward=False,
                    Limit=20,
                )
                for l_item in learn_resp.get("Items", []):
                    l_item = _decimal_to_float(l_item)
                    l_date = l_item.get("sk", "").replace("LEARNING#", "")
                    l_type = l_item.get("type", "stance_change")
                    milestones.append({
                        "date": l_date,
                        "type": l_type if l_type in ("stance_change", "prediction_resolved", "surprise", "investment_change") else "stance_change",
                        "text": l_item.get("lesson", l_item.get("revised_position", l_item.get("text", ""))),
                        "detail": l_item.get("detail", l_item.get("evidence", "")),
                    })
            except Exception:
                pass

            # Sort by date descending, deduplicate by text
            milestones.sort(key=lambda m: m.get("date", ""), reverse=True)
            seen_texts = set()
            unique_milestones = []
            for m in milestones:
                key = m.get("text", "")[:80]
                if key and key not in seen_texts:
                    seen_texts.add(key)
                    unique_milestones.append(m)

            return _ok({
                "coach_id": coach_id,
                "coach_name": _tl_coach_names[coach_id],
                "milestones": unique_milestones[:50],
            }, cache_seconds=600)
        except Exception as _e:
            print(f"[WARN] /api/coach_timeline failed: {_e}")
            return _ok({"coach_id": "", "coach_name": "", "milestones": []}, cache_seconds=60)

    # Weekly Priority (GET — integrator synthesis)
    if path == "/api/weekly_priority":
        try:
            _int_resp = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"})
            _int_item = _decimal_to_float(_int_resp.get("Item", {}))
            if not _int_item:
                return _ok({"weekly_priority": None, "cross_domain_notes": {}}, cache_seconds=300)
            return _ok({
                "weekly_priority": _int_item.get("analysis", ""),
                "cross_domain_notes": _int_item.get("cross_domain_notes", {}),
                "generated_at": _int_item.get("generated_at", ""),
                "week_number": _int_item.get("week_number"),
                "coach_name": "Dr. Kai Nakamura",
                "coach_title": "Integrative Health Director",
            }, cache_seconds=300)
        except Exception as _e:
            print(f"[WARN] /api/weekly_priority failed: {_e}")
            return _ok({"weekly_priority": None}, cache_seconds=60)


    if method != "GET":
        return _error(405, "Method not allowed")

    handler = ROUTES.get(path)
    if not handler:
        _emit_route_log(404)
        return _error(404, "Not found")

    try:
        result = handler()
        _emit_route_log(result.get("statusCode", 200))
        return result
    except Exception as e:
        logger.error(f"[site_api] {path} failed: {e}")
        _emit_route_log(500)
        return _error(500, "Internal error — check CloudWatch logs")
