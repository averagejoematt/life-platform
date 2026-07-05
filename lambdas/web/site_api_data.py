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
import stats_core  # shared layer (#529): the one sanctioned stats implementation (ADR-105)
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058
from source_registry import (  # #392: canonical source classification (shared layer)
    DEFAULT_STALE_HOURS as _FRESHNESS_DEFAULT_STALE_HOURS,
    public_board_sources,
    public_paused_sources,
    stale_hours_overrides,
)

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
# #392: the board derives from the ONE canonical registry (source_registry.py,
# shared-layer module) instead of hand-mirroring freshness_checker_lambda under
# a "KEEP IN SYNC" comment — the mirrors had drifted (withings/strava read as
# infrastructure; food_delivery thresholds disagreed). Per-source rationale
# lives in the registry. Behavioral staleness stays honestly visible here —
# only what pages the operator changed.
_FRESHNESS_SOURCES = public_board_sources()
_FRESHNESS_STALE_HOURS = stale_hours_overrides(_FRESHNESS_SOURCES)
_FRESHNESS_PAUSED = public_paused_sources()


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


def _apple_health_datatypes():
    """Per-datatype HAE liveness the freshness-checker stores (D-4/#468). None if absent."""
    try:
        rec = table.get_item(Key={"pk": USER_PREFIX + "apple_health", "sk": "DATATYPE_LIVENESS"}).get("Item")
        if not rec:
            return None
        return _decimal_to_float(rec).get("datatypes")
    except Exception as e:  # never break the feed for a missing sentinel
        logger.warning("source_freshness: apple_health datatypes read failed: %s", e)
        return None


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
        entry = {
            "id": sid,
            "label": meta["label"],
            "desc": meta["desc"],
            "category": meta["category"],
            "last_update": last_update,
            "age_hours": age_hours,
            "status": status,
            "is_behavioral": bool(meta.get("behavioral")),
        }
        # D-4 (#468): apple_health is one partition fed by many sensors, so its single
        # "fresh" hides a months-dark CGM/BP/SoM/workout stream. Surface the per-datatype
        # liveness the freshness-checker stores so the darkness is visible.
        if sid == "apple_health":
            dts = _apple_health_datatypes()
            if dts:
                entry["datatypes"] = dts
                entry["dark_datatypes"] = [d["label"] for d in dts if d.get("dark")]
        sources.append(entry)
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


# ── #406: intra-day sync freshness (the cockpit's "measured — live" proof) ──
# REAL ingestion write times only: the latest DATE# records' ingested_at /
# webhook_ingested_at stamps, never the day-granular DATE key. Passive pipes
# only — these sync without Matthew's participation, so an "x min ago" here is
# genuine motion, not implied continuity.
# #491/M-5: withings included so the cockpit sync strip can carry the weigh-in
# recency (behavioral cadence — a gap means "didn't step on", not "pipe broke").
_SYNC_SOURCES = {"whoop": "Whoop", "eightsleep": "Eight Sleep", "apple_health": "Apple Health", "withings": "Withings scale"}


def handle_last_sync() -> dict:
    """GET /api/last_sync — per passive source, the real last ingestion write.

    Returns {sources: [{id, label, last_write}], freshest, server_now}. The
    client computes and ticks the "ago" display (server_now closes clock skew).
    A source with no write stamp is reported with last_write null — shown
    honestly or omitted by the front-end, never faked."""
    now_iso = datetime.now(timezone.utc).isoformat()
    sources = []
    for sid, label in _SYNC_SOURCES.items():
        last_write = None
        try:
            kwargs = with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}{sid}") & Key("sk").begins_with("DATE#"),
                    "ScanIndexForward": False,
                    "Limit": 3,  # today's record + possible sub-records; max() picks the true latest write
                    "ProjectionExpression": "ingested_at, webhook_ingested_at",
                }
            )
            for it in table.query(**kwargs).get("Items", []):
                ts = str(it.get("webhook_ingested_at") or it.get("ingested_at") or "")
                if ts and (last_write is None or ts > last_write):
                    last_write = ts
        except Exception as e:
            logger.warning("last_sync: %s failed: %s", sid, e)
        sources.append({"id": sid, "label": label, "last_write": last_write})
    with_writes = [s for s in sources if s["last_write"]]
    freshest = max(with_writes, key=lambda s: s["last_write"]) if with_writes else None
    return _ok({"sources": sources, "freshest": freshest, "server_now": now_iso}, cache_seconds=60)


# Presence classes the public surface treats as "in a lull" (worth showing a line).
_PRESENCE_LOUD = {"light", "quiet", "dark"}


def handle_presence() -> dict:
    """GET /api/presence — the honest "quiet stretch" state for the cockpit line +
    Story beat: is Matthew actively logging, or has he gone quiet?

    FAIL-CLOSED public projection: this builds the response field-by-field from an
    explicit allowlist and NEVER spreads the stored record — so no private
    per-channel detail, no passive_read internals, no retention/mood ever leak.
    Day-counts are already publicly disclosed via /api/source_freshness, so this is
    consistent with existing disclosure. Honest 'present' default before the first
    compute (front-end simply hides). Always a shaped 200."""
    try:
        resp = table.get_item(Key={"pk": USER_PREFIX + "engagement_state", "sk": "STATE#current"})
        rec = resp.get("Item") or {}
    except Exception as e:
        logger.warning("handle_presence read failed: %s", e)
        rec = {}

    rec = _decimal_to_float(rec)
    presence_class = rec.get("presence_class") or "present"
    returned = bool(rec.get("returned"))
    in_lull = presence_class in _PRESENCE_LOUD

    out = {
        "available": bool(rec),
        "presence_class": presence_class,
        "in_lull": in_lull,
        "gap_days": rec.get("gap_days"),
        "last_log_date": rec.get("last_food_log_date"),
        "channels_quiet_count": rec.get("channels_quiet_count") or len(rec.get("channels_quiet") or []),
        "passive_still_flowing": rec.get("passive_still_flowing"),
        "planned_pause": bool(rec.get("planned_pause")),
        "planned_pause_reason": rec.get("planned_pause_reason") or "",
        "returned": returned,
        "resumed_after_days": rec.get("resumed_after_days") if returned else None,
        "weight_delta_over_gap_lbs": rec.get("weight_delta_over_gap") if returned else None,
        "as_of": rec.get("date"),
    }
    return _ok(out, cache_seconds=300)


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


def handle_what_changed() -> dict:
    """GET /api/what_changed — SS-08 monthly "what changed": real trailing-30d vs
    prior-30d deltas + correlations newly FDR-significant in the last 30 days, so a
    flat day still shows monthly motion. Written weekly by weekly-correlation-compute.
    Shaped-empty 200 before the first run; honest_null on a genuinely steady month."""
    item = table.get_item(Key={"pk": f"{USER_PREFIX}what_changed", "sk": "SNAPSHOT#current"}).get("Item")
    if not item:
        return _ok(
            {"deltas": [], "newly_unlocked": [], "honest_null": True, "window_start": None, "window_end": None, "week": None},
            cache_seconds=900,
        )
    item = _decimal_to_float(item)
    return _ok(
        {
            "deltas": item.get("deltas", []),
            "newly_unlocked": item.get("newly_unlocked", []),
            "honest_null": bool(item.get("honest_null", False)),
            "window_start": item.get("window_start"),
            "window_end": item.get("window_end"),
            "week": item.get("week"),
            "computed_at": item.get("computed_at"),
        },
        cache_seconds=900,
    )


_COUPLING_PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
_COUPLING_WINDOW = 60  # trailing character-sheet records to read
_COUPLING_MIN_N = 6  # a pair needs this many co-present real days or it's honestly omitted


def _coupling_real_score(pd: dict):
    """The pillar's raw_score for a day IF that day carried real signal, else None.

    ADR-104/105: a held/zero-coverage day is NOT a real low — counting a floored or
    carried-forward score would manufacture spurious (anti-)correlation, especially
    across a manual-logging gap. We correlate only days with genuine data.
    """
    if not isinstance(pd, dict):
        return None
    v = pd.get("raw_score")
    if v is None:
        return None
    if pd.get("coverage_hold"):
        return None
    cov = pd.get("data_coverage")
    if cov is not None and float(cov) <= 0:
        return None
    return float(v)


def handle_pillar_coupling() -> dict:
    """GET /api/pillar_coupling — #590: how the seven pillars have actually co-moved.

    Deterministic pairwise Pearson of each pillar's daily raw_score over a trailing
    window (real-signal days only, per _coupling_real_score). Every edge carries its
    own n; pairs below the n floor or with no variance are omitted, never faked — the
    constellation draws thin/absent data honestly faint. No AI, no forecast: this is a
    descriptive statistic over the last ~60 days, labeled by its actual date range.
    """
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}character_sheet") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=_COUPLING_WINDOW,
    )
    recs = _decimal_to_float(resp.get("Items", []))
    recs.sort(key=lambda r: str(r.get("sk", "")))  # chronological
    if len(recs) < _COUPLING_MIN_N:
        return _ok(
            {
                "edges": [],
                "pillars": [],
                "window_start": None,
                "window_end": None,
                "window_days": 0,
                "min_n": _COUPLING_MIN_N,
                "honest_null": True,
            },
            cache_seconds=3600,
        )

    series = {p: [_coupling_real_score(r.get(f"pillar_{p}")) for r in recs] for p in _COUPLING_PILLARS}
    present = [p for p in _COUPLING_PILLARS if any(v is not None for v in series[p])]

    edges = []
    for i in range(len(present)):
        for j in range(i + 1, len(present)):
            a, b = present[i], present[j]
            r = stats_core.pearson_r(series[a], series[b], min_n=_COUPLING_MIN_N)
            if r is None:  # thin or flat → no honest edge to draw
                continue
            n = sum(1 for x, y in zip(series[a], series[b]) if x is not None and y is not None)
            p_val = stats_core.pearson_p_value(r, n)
            edges.append(
                {
                    "a": a,
                    "b": b,
                    "r": round(r, 2),
                    "n": n,
                    "p": round(p_val, 3) if p_val is not None else None,
                    "significant": bool(p_val is not None and p_val < 0.05),
                }
            )
    edges.sort(key=lambda e: -abs(e["r"]))
    return _ok(
        {
            "edges": edges,
            "pillars": present,
            "window_start": str(recs[0].get("sk", "")).replace("DATE#", "")[:10],
            "window_end": str(recs[-1].get("sk", "")).replace("DATE#", "")[:10],
            "window_days": len(recs),
            "min_n": _COUPLING_MIN_N,
            "honest_null": not edges,
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
                    # Substitute the {duration} token (was leaking literally on /protocols/discoveries:
                    # "Tongkat Ali … for {duration} days"). Same fix the experiments handler already has.
                    "hypothesis": (exp.get("hypothesis_template", "") or "").replace(
                        "{duration}", str(exp.get("suggested_duration_days") or "several")
                    ),
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

        # Dedupe by title, keep most recent. Drop empty-body entries — a card titled
        # "Journal Breakthrough" with a "high confidence" badge and NO text reads as broken
        # and implies a finding that isn't shown. No body → no card.
        seen_titles = set()
        deduped = []
        for il in inner_life:
            if il["title"] not in seen_titles and (il.get("body") or "").strip():
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
                # Substitute the {duration} template token (was leaking literally into the
                # rendered hypothesis: "...for {duration} days will reduce...").
                "hypothesis": (item.get("hypothesis", "") or "").replace("{duration}", str(planned_duration or duration_days or "several")),
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
                # #539: the frozen n-of-1 design + pre-registration stamp + the
                # deterministic close-path analysis (effect, CI, n's, verdict).
                "design": item.get("design"),
                "pre_registered_at": item.get("pre_registered_at"),
                "analysis": item.get("analysis"),
                "origin": "live",  # an actual run on the ledger (this experiment cycle)
            }
        )
    experiments.sort(key=lambda x: x["start_date"], reverse=True)

    # Overlay the experiment library (the catalog of what's planned / in flight).
    # Live runs take precedence; library entries already running are not duplicated.
    live_lib_ids = {x.get("library_id") for x in experiments if x.get("library_id")}
    live_names = {(x.get("name") or "").strip().lower() for x in experiments}
    experiments.extend(_experiment_catalog(live_lib_ids, live_names))

    return _ok({"experiments": experiments}, cache_seconds=3600)


def _experiment_catalog(exclude_ids: set, exclude_names: set) -> list:
    """experiment_library.json → display items tagged origin='library', so the page
    shows the pipeline (planned/backlog experiments) even when nothing is running."""
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    out = []
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key="config/experiment_library.json")
        lib = json.loads(obj["Body"].read())
    except Exception as e:
        logger.warning("[experiments] library unavailable: %s", e)
        return out
    for exp in lib.get("experiments", []):
        if exp.get("id") in exclude_ids:
            continue
        if (exp.get("name") or "").strip().lower() in exclude_names:
            continue
        # library status: 'active' = promoted/ready to run → "available"; else backlog.
        shelf = "available" if exp.get("status") == "active" else "backlog"
        out.append(
            {
                "id": exp.get("id"),
                "name": exp.get("name", "Unnamed"),
                "status": shelf,
                "origin": "library",
                # Substitute the {duration} token in the library hypothesis_template (was
                # rendering literally: "16:8 fasting for {duration} days will reduce...").
                "hypothesis": (exp.get("hypothesis_template", "") or "").replace(
                    "{duration}", str(exp.get("suggested_duration_days") or "several")
                ),
                "pillar": exp.get("pillar", ""),
                "difficulty": exp.get("difficulty"),
                "evidence_tier": exp.get("evidence_tier"),
                "result_summary": exp.get("why_it_matters", "") or exp.get("description", ""),
                "planned_duration_days": exp.get("suggested_duration_days"),
                "tags": exp.get("tags", []),
                "votes": exp.get("votes", 0),
                # Source attribution: where the idea came from (published study citation +
                # first supporting evidence URL). Surfaced on the site so each experiment
                # shows its provenance rather than appearing to arrive from nowhere.
                "evidence_citation": exp.get("evidence_citation"),
                "source_url": ((exp.get("evidence_for") or [{}])[0] or {}).get("url"),
            }
        )
    # most-voted backlog first, then alphabetical
    out.sort(key=lambda x: (-(x.get("votes") or 0), x.get("name", "").lower()))
    return out


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

    # Count actual holding vices, not the stored `vices_held` aggregate — that field read 7
    # against 6 tracked (more held than exist), a visible lie on the marquee stat. Derive it.
    total_held = sum(1 for v in vices if v["holding"])
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
    _habit_agg = {}  # P0.5: per-habit window adherence for the state taxonomy
    for hi in _decimal_to_float(hab_resp.get("Items", [])):
        date_key = hi.get("date") or hi.get("sk", "").replace("DATE#", "")
        by_group = hi.get("by_group", {})
        if by_group and isinstance(by_group, dict):
            # by_group[Group] = {completed, possible, pct, habits_done}
            # pct is 0.0–1.0, convert to 0–100
            habitify_by_date[date_key] = {g: round(float(v.get("pct", 0) or 0) * 100) for g, v in by_group.items() if isinstance(v, dict)}
        # Aggregate per-habit completed/scheduled across the window (state taxonomy).
        for hname, st in (hi.get("habit_statuses") or {}).items():
            if _is_blocked_vice(hname):
                continue
            st = st if isinstance(st, dict) else {}
            a = _habit_agg.setdefault(hname, {"scheduled": 0, "completed": 0, "group": st.get("group") or "Other"})
            if st.get("scheduled_today", True):
                a["scheduled"] += 1
                if st.get("status") == "completed":
                    a["completed"] += 1

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

    # P0.5 — per-habit state taxonomy inputs: window adherence + a state label.
    per_habit = []
    for hname, a in sorted(_habit_agg.items(), key=lambda kv: -(kv[1]["completed"] / kv[1]["scheduled"] if kv[1]["scheduled"] else -1)):
        sched, comp = a["scheduled"], a["completed"]
        pct = round(comp / sched * 100) if sched else None
        if comp == 0:
            state = "backlog"
        elif pct >= 85:
            state = "automatic"
        elif pct >= 60:
            state = "holding"
        else:
            state = "needs_attention"
        per_habit.append(
            {"name": hname, "group": a["group"], "scheduled_days": sched, "completed_days": comp, "adherence_pct": pct, "state": state}
        )

    return _ok(
        {
            "as_of_date": today,
            "days_tracked": len(history),
            "current_streak": latest_streak,
            "per_habit": per_habit,
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


def _corr_p_value(p: dict):
    """Serve the stored p-value faithfully, or None when absent.

    The compute lambda rounds p to 4 decimals, so a highly-significant pair
    stores p=0.0 — and the old `float(... or 1)` coerced that 0.0 to 1.0,
    rendering the flagship FDR-significant pair as "p 1.000". Zero is a
    value, not a missing value.
    """
    raw = p.get("p_value", p.get("p"))
    if raw is None:
        return None
    return round(float(raw), 4)


def _corr_strength(r_val: float, stored: str) -> str:
    """Deterministic strength label from |r| (Cohen-style bands).

    The stored `interpretation` has disagreed with the number it sits next
    to (r=0.843 labeled "weak"); the served label must match the served r.
    Falls back to the stored label only for degenerate r=0 rows so
    "insufficient_data" survives.
    """
    a = abs(r_val)
    if a >= 0.7:
        return "strong"
    if a >= 0.4:
        return "moderate"
    if a > 0:
        return "weak"
    return stored or "weak"


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
                "p": _corr_p_value(p),
                "n": int(p.get("n_days", p.get("n", 0)) or 0),
                "strength": _corr_strength(r_val, p.get("interpretation", p.get("strength", ""))),
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
        # Filter to significant only (p < 0.05 or FDR-significant).
        # p may be None (absent) — and p=0.0 is maximally significant, not missing.
        significant = [p for p in public_pairs if p.get("fdr_significant") or (p.get("p") is not None and p["p"] < 0.05)]
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


def _sane_sleep_score(raw, hours, whoop_quality):
    """Gate an implausible nightly sleep score. A score <40 next to >=6h slept AND/OR a healthy
    Whoop quality (>=70) is a scoring/attribution glitch (the live '12' next to 8.2h + 84%
    quality), not a real terrible night — fall back to Whoop quality so one bad number doesn't
    make the whole sleep page look broken. Returns a rounded score or None."""
    if raw is None:
        return None
    try:
        raw = round(float(raw), 0)
    except (TypeError, ValueError):
        return None
    hrs = float(hours) if hours else 0
    wq = float(whoop_quality) if whoop_quality else 0
    if raw < 40 and (hrs >= 6 or wq >= 70):
        return round(wq, 0) if wq else None
    return raw


# ── Cross-source correlation board (sleep §8, Phase 2) ───────────────────────
# Self-policing: every card carries n + overlap_weeks + a confidence tag. The Pearson
# coefficient is computed ONLY at >=14 overlapping days (>=2 weeks); below that it's
# direction-only ("watching — too early"). Sleep-vs-weight (C1) is hard-WITHHELD through
# the water-weight phase. Powered by the same raw sources the platform tools read; the
# Pearson + day-lag logic is replicated compactly here (site-api can't import mcp/).
_CORR_MIN_COEF_DAYS = 14  # >=2 weeks of overlap before any coefficient
_CORR_MIN_DIR_DAYS = 4  # below this, not even a direction


def _shift_date(d, lag):
    try:
        return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=lag)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _corr_card(cid, label, predictor, outcome, pred_series, outc_series, lag=0, withhold=False, note=""):
    """Build one self-policing correlation card from two {date: value} maps."""
    xs, ys = [], []
    for d, x in (pred_series or {}).items():
        d2 = _shift_date(d, lag)
        if d2 and d2 in (outc_series or {}) and x is not None and outc_series[d2] is not None:
            xs.append(float(x))
            ys.append(float(outc_series[d2]))
    n = len(xs)
    card = {
        "id": cid,
        "label": label,
        "predictor": predictor,
        "outcome": outcome,
        "n": n,
        "overlap_weeks": round(n / 7, 1),
        "lag_days": lag,
        "direction": "insufficient",
        "coefficient": None,
        "withheld": bool(withhold),
        "confidence": "watching — too early",
        "noise": False,
        "note": note,
    }
    if n >= _CORR_MIN_DIR_DAYS:
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        card["direction"] = "moves together" if cov > 0 else ("moves opposite" if cov < 0 else "flat")
        card["noise"] = n < 7  # thin pairs are likely noise
    if withhold:
        card["confidence"] = "withheld — water-weight phase"
        card["coefficient"] = None
    elif n >= _CORR_MIN_COEF_DAYS:
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        sx = sum((a - mx) ** 2 for a in xs) ** 0.5
        sy = sum((b - my) ** 2 for b in ys) ** 0.5
        card["coefficient"] = round(cov / (sx * sy), 2) if sx > 0 and sy > 0 else None
        card["confidence"] = "low confidence" if n < 30 else "moderate"
    return card


def _whoop_daily(d30, today):
    """Whoop daily metrics keyed by date: recovery, strain, deep hours, sleep hours."""
    out = {}
    for w in _query_source("whoop", d30, today):
        if "#WORKOUT#" in w.get("sk", ""):
            continue
        dt = w.get("sk", "").replace("DATE#", "")[:10]
        if not dt:
            continue
        out[dt] = {
            "recovery": _f(w.get("recovery_score")),
            "strain": _f(w.get("strain")),
            "deep": _f(w.get("slow_wave_sleep_hours")),
            "hours": _f(w.get("sleep_duration_hours")),
            "hrv": _f(w.get("hrv")),
        }
    return out


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def handle_sleep_correlations() -> dict:
    """
    GET /api/sleep_correlations
    The self-policing cross-source signal board. Each card: n + overlap-weeks + confidence;
    direction-only under 2 weeks (no coefficient); Pearson only at >=2 weeks. Sleep-vs-weight
    withheld through the water-weight phase. Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    wd = _whoop_daily(d30, today)
    recovery = {d: v["recovery"] for d, v in wd.items() if v["recovery"] is not None}
    strain = {d: v["strain"] for d, v in wd.items() if v["strain"] is not None}

    cards = []
    # A1 (LEAD) — last night's recovery → today's training capacity (same-day; the only
    # arrow that changes tomorrow morning). Outcome proxy: the day's Whoop strain.
    cards.append(
        _corr_card(
            "A1",
            "Last night's recovery → today's training capacity",
            "sleep recovery",
            "day strain",
            recovery,
            strain,
            lag=0,
            note="The only arrow that changes tomorrow morning — high recovery should let the day carry more strain.",
        )
    )
    # A2 — day strain → next-night deep sleep (day-lagged: "did I earn it?").
    deep = {d: v["deep"] for d, v in wd.items() if v["deep"] is not None}
    cards.append(
        _corr_card(
            "A2",
            "Day strain → next-night deep sleep",
            "day strain",
            "deep sleep",
            strain,
            deep,
            lag=1,
            note="Did I earn it? — yesterday's training load against tonight's deep sleep.",
        )
    )
    # Eight Sleep nightly sleep-score series (feeds the A4 last-meal card).
    # NB: the former "A3 — bed temp → deep sleep" card was retired (ADR-118,
    # #489) — the Eight Sleep temperature pipeline is dead (dead /v2/intervals
    # endpoint, no bed_temp_f for 4+ months), so the card only ever rendered empty.
    eight = {}
    for e in _query_source("eightsleep", d30, today):
        dt = e.get("sk", "").replace("DATE#", "")[:10]
        if dt:
            eight[dt] = {"score": _f(e.get("sleep_score"))}
    sleep_score = {d: v["score"] for d, v in eight.items() if v["score"] is not None}
    # A4 — last meal time → sleep score. MacroFactor food_log latest time per day.
    last_meal = {}
    for m in _query_source("macrofactor", d30, today):
        dt = m.get("date") or m.get("sk", "").replace("DATE#", "")[:10]
        times = []
        for ent in m.get("food_log") or []:
            try:
                p = str(ent.get("time")).split(":")
                times.append(int(p[0]) * 60 + int(p[1]))
            except (ValueError, IndexError, AttributeError):
                pass
        if times and dt:
            last_meal[dt] = max(times)
    cards.append(
        _corr_card(
            "A4",
            "Last meal time → sleep score",
            "last meal",
            "sleep score",
            last_meal,
            sleep_score,
            lag=0,
            note="Eating late can blunt the night — last-meal minutes against how the night scored.",
        )
    )
    # B1 — decision fatigue (Todoist completed-task load) → sleep score. No app tracks this.
    todoist = {}
    for t in _query_source("todoist", d30, today):
        dt = t.get("date") or t.get("sk", "").replace("DATE#", "")[:10]
        v = _f(t.get("completed_count") or t.get("tasks_completed") or t.get("completed") or t.get("completed_today"))
        if v is not None and dt:
            todoist[dt] = v
    cards.append(
        _corr_card(
            "B1",
            "Decision load (Todoist) → sleep score",
            "Todoist load",
            "sleep score",
            todoist,
            sleep_score,
            lag=0,
            note="A heavy decision day against how the night scored — the cross-source signal no sleep app has.",
        )
    )
    # B2 — mood/journal → sleep (bidirectional). State-of-Mind valence as the mood proxy;
    # empty (n=0 → watching) when mood/journal logging is stale.
    mood = {}
    # SoM daily valence lands on the apple_health partition as som_avg_valence
    # (there is no separate state_of_mind partition).
    for sm in _query_source("apple_health", d30, today):
        dt = sm.get("date") or sm.get("sk", "").replace("DATE#", "")[:10]
        v = _f(sm.get("som_avg_valence"))
        if v is not None and dt:
            mood[dt] = v
    cards.append(
        _corr_card(
            "B2",
            "Mood → sleep score",
            "mood / valence",
            "sleep score",
            mood,
            sleep_score,
            lag=0,
            note="Mood and sleep move together both ways — gated on active mood/journal logging; empty until entries accrue.",
        )
    )
    # B3 — day-of-week best duration. Not a Pearson pair; n=1/day at week one = noise.
    durations = {d: v["hours"] for d, v in wd.items() if v["hours"] is not None}
    dow = {}
    for d, h in durations.items():
        try:
            dow.setdefault(datetime.strptime(d, "%Y-%m-%d").weekday(), []).append(h)
        except ValueError:
            pass
    _wk = round(len(durations) / 7, 1)
    b3 = {
        "id": "B3",
        "label": "Day-of-week → best sleep duration",
        "predictor": "day of week",
        "outcome": "sleep duration",
        "n": len(durations),
        "overlap_weeks": _wk,
        "lag_days": 0,
        "coefficient": None,
        "withheld": False,
        "direction": "fills in ~4 weeks",
        "confidence": "watching — needs ~4 weeks",
        "noise": True,
        "note": "Which weekday sleeps best needs ~4 weeks — one Tuesday is not a pattern.",
    }
    if _wk >= 4 and dow:
        _best = max(dow, key=lambda k: sum(dow[k]) / len(dow[k]))
        _names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        b3.update(
            {
                "direction": f"best on {_names[_best]} ({round(sum(dow[_best]) / len(dow[_best]), 1)}h avg)",
                "confidence": "low confidence",
                "noise": False,
            }
        )
    cards.append(b3)
    # C1 (shown LAST, labelled loudest) — sleep vs weight. HIGHEST false-positive risk in a
    # water-weight cut; the coefficient is HARD-WITHHELD until well past the early water phase
    # AND explicit sign-off (the STOP-AND-ASK gate). Direction is still shown honestly.
    weight = {}
    for w in _query_source("withings", d30, today):
        dt = w.get("date") or w.get("sk", "").replace("DATE#", "")[:10]
        v = _f(w.get("weight_lbs"))
        if v is not None and dt:
            weight[dt] = v
    cards.append(
        _corr_card(
            "C1",
            "Sleep → weight",
            "sleep score",
            "weight",
            sleep_score,
            weight,
            lag=0,
            withhold=True,
            note="Highest false-positive risk in a water-weight cut — the coefficient stays withheld until well past the early water phase.",
        )
    )

    return _ok({"cards": cards, "min_coef_days": _CORR_MIN_COEF_DAYS, "as_of": today}, cache_seconds=3600)


def handle_sleep_detail() -> dict:
    """
    GET /api/sleep_detail
    Returns: 30-day sleep stats from Eight Sleep + Whoop cross-referenced.
    Shows sleep score, efficiency, quality, and daily trend.
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
    # #495/M-9: if the latest Eight Sleep night has no matching Whoop recovery,
    # borrow the most recent night that has one — but ONLY the recovery block
    # (recovery/HRV/RHR), and SAY SO via recovery_night_of. The old code swapped
    # the whole Whoop record, so night-A hours/stages + night-B recovery rendered
    # under one dated header with no per-field date.
    whoop_recovery_rec = whoop_latest
    recovery_night_of = None
    if not whoop_latest.get("recovery_score"):
        for r in reversed(eight_with_data):
            _rd = r.get("sk", "").replace("DATE#", "")
            _wm = whoop_by_date.get(_rd, {})
            if _wm.get("recovery_score"):
                whoop_recovery_rec = _wm
                if _rd != latest_date:
                    recovery_night_of = _rd
                break

    # 30-day averages (actual field names: sleep_efficiency_pct, sleep_duration_hours)
    score_vals = [float(r["sleep_score"]) for r in eight_with_data if r.get("sleep_score")]
    eff_vals = [float(r["sleep_efficiency_pct"]) for r in eight_with_data if r.get("sleep_efficiency_pct")]
    # Bed-temperature surfaces retired (ADR-118, #489) — the Eight Sleep temp
    # pipeline is dead (dead /v2/intervals endpoint, no bed_temp_f for 4+ months).

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
                "sleep_score": _sane_sleep_score(r.get("sleep_score"), w.get("sleep_duration_hours"), w.get("sleep_quality_score")),
                "efficiency": round(float(r["sleep_efficiency_pct"]), 1) if r.get("sleep_efficiency_pct") else None,
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

    # Use the gated latest trend score so a glitch score (the '12') doesn't drive the headline.
    score_today = float(trend[-1]["sleep_score"]) if trend and trend[-1].get("sleep_score") else float(latest.get("sleep_score", 0) or 0)
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
                "recovery_score": (
                    round(float(whoop_recovery_rec.get("recovery_score", 0)), 0) if whoop_recovery_rec.get("recovery_score") else None
                ),
                # #495/M-9: when the recovery/HRV/RHR trio above comes from a different
                # night than the Eight Sleep record, this carries that night's date (else null).
                "recovery_night_of": recovery_night_of,
                "hrv": round(float(whoop_recovery_rec.get("hrv", 0)), 1) if whoop_recovery_rec.get("hrv") else None,
                "rhr": (
                    round(float(whoop_recovery_rec.get("resting_heart_rate", 0)), 0)
                    if whoop_recovery_rec.get("resting_heart_rate")
                    else None
                ),
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
                "30d_avg_score": avg(score_vals),
                "30d_avg_efficiency": avg(eff_vals),
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


def handle_circadian() -> dict:
    """
    GET /api/circadian
    Today's circadian-compliance score — computed daily by
    circadian_compliance_lambda and stored at SOURCE#circadian | DATE#<today>,
    but (until now) never surfaced. A *predictive* 0–100 behavioral score across
    four anchors (wake light, meal timing, screen wind-down, sleep consistency):
    it estimates what tonight's sleep will look like based on today's behaviors.
    Cache: 900s — recomputed once daily; refreshing faster gains nothing.
    """
    item = _latest_item("circadian")
    if not item:
        return _ok({"available": False}, cache_seconds=900)

    comps = item.get("components", {}) or {}
    components = {
        name: {
            "score": c.get("score"),
            "max": c.get("max"),
            "note": c.get("note"),
        }
        for name, c in comps.items()
    }
    return _ok(
        {
            "available": True,
            "date": item.get("date"),
            # Temporal frame (additive): this is a forward-looking forecast of how
            # tonight's sleep will turn out given today's behaviours — not a measurement.
            "frame": "tonight",
            "score": item.get("score"),
            "category": item.get("category"),
            "prescription": item.get("prescription"),
            "weakest_component": item.get("weakest_component"),
            "components": components,
        },
        cache_seconds=900,
    )


def handle_forecast() -> dict:
    """
    GET /api/forecast
    The forecast engine's daily summary (#541) — deterministic EWMA expectations
    for recovery / sleep / weight with 80% intervals, today's graded resolutions
    (expected vs actual), and the running interval-coverage stat. SOURCE#forecast
    holds frozen FORECAST# rows plus one DATE#<today> summary; we serve the
    latest summary with internal keys stripped. The anti-causal framing ships in
    the payload so every consumer renders it: these are expectations from
    observed patterns, not causal claims. Cache: 900s — recomputed once daily.
    """
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}forecast") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        return _ok({"available": False}, cache_seconds=900)
    _INTERNAL = {"pk", "sk", "run_id", "computed_at", "phase", "cycle", "record_type"}
    data = {k: v for k, v in items[0].items() if k not in _INTERNAL}
    data["available"] = True
    data["framing"] = "what the model expects from observed patterns — correlative, not causal"
    return _ok(data, cache_seconds=900)


def handle_scenarios() -> dict:
    """
    GET /api/scenarios
    The scenario explorer's nightly precompute (#550) — for each curated lever
    ("slept 7.5h+", "20+ zone-2 minutes", …), the distribution of what FOLLOWED
    similar days (next-day recovery/sleep/HRV/mood/energy) with block-bootstrap
    CIs and honest n / n_eff labels; thin cells are pre-hidden by the compute's
    effective-n gate. Anti-causal framing ships in the payload. Read-only;
    cache 3600s — recomputed nightly.
    """
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}scenarios") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        return _ok({"available": False}, cache_seconds=3600)
    _INTERNAL = {"pk", "sk", "run_id", "computed_at", "phase", "cycle", "record_type"}
    data = {k: v for k, v in items[0].items() if k not in _INTERNAL}
    data["available"] = True
    return _ok(data, cache_seconds=3600)


def handle_state_of_matthew() -> dict:
    """
    GET /api/state_of_matthew
    The weekly "State of Matthew" model brief (#552) — the deterministic
    assembly of the forecast engine (#541), the hypothesis engine's live
    pre-registered bets (#530/ADR-105), the coaching panel's current
    consensus/disputes, and the calibration scoreboard (#538) into one
    narrated read-back, computed weekly by state-of-matthew-lambda. Each of
    the four sections is independently present-or-absent per
    `sections_available` — a source with genuinely nothing yet (e.g. n=0
    calibration post-reset) is omitted rather than zero-filled. The one
    Haiku call that wrote `narrative` never computed a number; every figure
    traces back to the section it's quoted from. Read-only; cache 3600s —
    recomputed once a week (Sundays).
    """
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}state_of_matthew") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        return _ok({"available": False}, cache_seconds=3600)
    _INTERNAL = {"pk", "sk", "run_id", "computed_at", "phase", "cycle", "record_type"}
    data = {k: v for k, v in items[0].items() if k not in _INTERNAL}
    data["available"] = True
    return _ok(data, cache_seconds=3600)


# handle_sleep_reconciliation — RETIRED 2026-07-05 (#487 / ADR-113). The /api/sleep_reconciliation
# endpoint served SOURCE#sleep_unified, whose per-field merge read record fields that never existed
# (it was the Whoop record plus one Eight Sleep score, not the promised best-source merge) and whose
# night_of ran 1–2 nights stale — mislabelling the public /data/sleep "night of" header. Zero compute
# consumers; /api/sleep_detail carries the same figures, fresher, and is now the sole source of that
# header date. The orphan sleep_unified DDB partition is left in place (read by nothing).


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
    """GET /api/habit_registry — the habits being tracked, grouped.

    Source of truth is Habitify (USER#…#SOURCE#habitify, latest DATE# record):
    its ``habit_statuses`` map carries every scheduled habit with its area/group
    and periodicity. We surface that list grouped by area so the public habits
    page shows "everything I'm trying to do" even right after an experiment reset
    (when the PROFILE#v1 registry and the phase-scoped habit_scores are empty).

    Blocked vice/habit names (porn, marijuana, …) are stripped server-side via
    ``_is_blocked_vice`` — content_filter.json's ``habit_data`` rule — so they
    never reach the client even though Habitify tracks them.
    """
    try:
        habits = _habits_from_habitify()
        source = "habitify"
        if not habits:
            # Fallback: legacy PROFILE#v1 registry (pre-Habitify-sourcing).
            resp = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
            registry = resp.get("Item", {}).get("habit_registry", {})
            for name, meta in registry.items():
                if _is_blocked_vice(name):
                    continue
                h = {"name": name, "group": meta.get("group") if isinstance(meta, dict) else None}
                if isinstance(meta, dict):
                    for k, v in meta.items():
                        h[k] = float(v) if isinstance(v, Decimal) else v
                habits.append(h)
            source = "profile"

        # Stable group ordering: known P40-ish groups first, then alpha, "Other" last.
        seen, groups = set(), []
        for h in habits:
            g = h.get("group") or "Other"
            if g not in seen:
                seen.add(g)
                groups.append(g)
        groups.sort(key=lambda g: (g == "Other", g.lower()))
        habits.sort(key=lambda x: ((x.get("group") or "Other") == "Other", (x.get("group") or "Other").lower(), x.get("name", "").lower()))
        # P1.1 — auto-derived taxonomy (time-of-day / type / logical group), labeled derived.
        for h in habits:
            h["taxonomy"] = _derive_habit_taxonomy(h.get("name", ""))
        return _ok(
            {"habits": habits, "groups": groups, "count": len(habits), "source": source, "taxonomy_derived": True},
            cache_seconds=3600,
        )
    except Exception as e:
        logger.error(f"[habit_registry] Error: {e}")
        return _error(500, "Failed to load habit registry")


_TAX_TIME = [
    ("morning", ("morning", "wake", "wakeup", "wake-up", "am ", "breakfast", "sunrise", "first thing", "dawn")),
    ("evening", ("evening", "night", "bed", "bedtime", "pm ", "dinner", "sunset", "wind down", "wind-down", "before sleep")),
    ("midday", ("lunch", "midday", "afternoon", "noon")),
]
_TAX_AVOID = ("no ", "avoid", "quit", "limit", "less ", "skip", "cut ", "abstain", "stop ", "zero ")
_TAX_MAINTAIN = ("track", "log ", "logging", "weigh", "measure", "record", "review", "check ", "plan ")
_TAX_GROUP_HINTS = [
    ("Nutrition", ("eat", "protein", "hydrate", "water", "meal", "calorie", "macro", "veg", "food", "supplement", "creatine", "fiber")),
    ("Training", ("walk", "run", "lift", "workout", "train", "gym", "steps", "stretch", "mobility", "cardio", "zone", "ruck")),
    ("Recovery", ("sleep", "bed", "meditat", "breath", "sauna", "cold", "plunge", "rest", "recovery", "nap", "sunlight")),
    ("Mind", ("read", "journal", "write", "learn", "study", "gratitude", "reflect", "focus", "deep work")),
]


def _derive_habit_taxonomy(name: str) -> dict:
    """P1.1 — deterministic, name-only inference of a habit's context.

    Re-derives time-of-day, type (do/avoid/maintain) and a logical group from the
    habit *name* (Habitify's stored area is storage, not logic). Heuristic + n=1:
    always returned under ``derived: True`` and labeled "auto-derived" on the surface,
    never presented as fact. No causal claims — this only classifies, it does not score.
    """
    n = f" {(name or '').lower().strip()} "
    time_of_day = "anytime"
    for label, keys in _TAX_TIME:
        if any(k in n for k in keys):
            time_of_day = label
            break
    if any(k in n for k in _TAX_AVOID):
        htype = "avoid"
    elif any(k in n for k in _TAX_MAINTAIN):
        htype = "maintain"
    else:
        htype = "do"
    group = None
    for g, keys in _TAX_GROUP_HINTS:
        if any(k in n for k in keys):
            group = g
            break
    return {"time_of_day": time_of_day, "type": htype, "group": group, "derived": True}


def _habits_from_habitify() -> list:
    """Latest Habitify record → [{name, group, frequency, scheduled_today}], filtered."""
    pk = f"{USER_PREFIX}habitify"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=1)
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        return []
    statuses = items[0].get("habit_statuses") or {}
    out = []
    for name, st in statuses.items():
        if _is_blocked_vice(name):
            continue
        st = st if isinstance(st, dict) else {}
        out.append(
            {
                "name": name,
                "group": st.get("group") or "Other",
                "frequency": st.get("periodicity") or "daily",
                "scheduled_today": bool(st.get("scheduled_today", True)),
            }
        )
    return out


# ── PhenoAge (Levine et al. 2018) — transparent biological age (P1.5) ──────────────
# Replaces the DEXA black-box "biological age" with a published formula over 9 standard blood
# markers + chronological age. PRIVACY (owner decision, Option A): chronological age is used
# ONLY to compute — it is NEVER returned, and neither is the chrono−pheno gap, so the page
# can't be used to back out the owner's real age. (Residual: the 9 markers are public on the
# labs page, so a determined reader applying this formula could approximate age from a precise
# phenotypic number — flagged for review.) Population-level, correlative, NOT the DNAm clock.
_PHENOAGE_COEF = {  # (coefficient, reference value in formula units) — ref = healthy midpoint
    "albumin_gL": (-0.0336, 45.0),
    "creatinine_umolL": (0.0095, 80.0),
    "glucose_mmolL": (0.1953, 5.0),
    "lncrp": (0.0954, None),  # ln(CRP mg/dL); handled separately
    "lymphocyte_pct": (-0.0120, 32.0),
    "mcv_fL": (0.0268, 90.0),
    "rdw_pct": (0.3306, 13.0),
    "alp_UL": (0.00188, 65.0),
    "wbc_1000": (0.0554, 6.0),
}
_PHENOAGE_LABELS = {
    "albumin_gL": "Albumin",
    "creatinine_umolL": "Creatinine",
    "glucose_mmolL": "Glucose",
    "lncrp": "hs-CRP",
    "lymphocyte_pct": "Lymphocyte %",
    "mcv_fL": "MCV",
    "rdw_pct": "RDW",
    "alp_UL": "Alkaline phosphatase",
    "wbc_1000": "WBC",
}


def _compute_phenoage(vals: dict, age_years: float):
    """Levine Phenotypic Age from the 9 converted markers (formula units) + chronological age.
    Returns the exact phenotypic age in years, or None on bad inputs. Age is an INPUT only."""
    import math

    try:
        g = 0.0076927
        xb = (
            -19.9067
            - 0.0336 * vals["albumin_gL"]
            + 0.0095 * vals["creatinine_umolL"]
            + 0.1953 * vals["glucose_mmolL"]
            + 0.0954 * math.log(max(0.01, vals["crp_mgdL"]))
            - 0.0120 * vals["lymphocyte_pct"]
            + 0.0268 * vals["mcv_fL"]
            + 0.3306 * vals["rdw_pct"]
            + 0.00188 * vals["alp_UL"]
            + 0.0554 * vals["wbc_1000"]
            + 0.0804 * age_years
        )
        mort = 1.0 - math.exp(-math.exp(xb) * (math.exp(120.0 * g) - 1.0) / g)
        if mort <= 0 or mort >= 1:
            return None
        pheno = 141.50225 + math.log(-0.00553 * math.log(1.0 - mort)) / 0.090165
        return pheno
    except (ValueError, KeyError, ZeroDivisionError, OverflowError):
        return None


def handle_phenoage() -> dict:
    """GET /api/phenoage — transparent Levine Phenotypic Age. Option A privacy: returns the
    phenotypic age + the 9 driver markers ONLY; never chronological age or the gap."""
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=f"dashboard/{USER_ID}/clinical.json")
        data = json.loads(resp["Body"].read())
        labs = data.get("labs", {})
        markers = labs.get("biomarkers", []) or []
        by = {}
        for m in markers:
            nm = str(m.get("name", "")).strip().lower()
            if nm and nm not in by:
                by[nm] = m

        def _num(name):
            m = by.get(name)
            if not m:
                return None
            try:
                return float(str(m.get("value")).replace("<", "").replace(">", "").strip())
            except (TypeError, ValueError):
                return None

        raw = {
            "albumin": _num("albumin"),
            "creatinine": _num("creatinine"),
            "glucose": _num("glucose"),
            "crp": _num("crp hs"),
            "mcv": _num("mcv"),
            "rdw": _num("rdw"),
            "alp": _num("alkaline phosphatase"),
            "wbc": _num("wbc"),
            "abs_lymph": _num("absolute lymphocytes"),
        }
        # Lymphocyte % derived from absolute lymphocytes ÷ WBC (2a — exact, labeled).
        lymph_pct = None
        lymph_derived = False
        if raw["abs_lymph"] is not None and raw["wbc"]:
            lymph_pct = round(raw["abs_lymph"] / (raw["wbc"] * 1000.0) * 100.0, 1)
            lymph_derived = True

        required = {
            "Albumin": raw["albumin"],
            "Creatinine": raw["creatinine"],
            "Glucose": raw["glucose"],
            "hs-CRP": raw["crp"],
            "Lymphocyte %": lymph_pct,
            "MCV": raw["mcv"],
            "RDW": raw["rdw"],
            "Alkaline phosphatase": raw["alp"],
            "WBC": raw["wbc"],
        }
        missing = [k for k, v in required.items() if v is None]
        # Chronological age (compute-only; never returned). From profile DOB.
        prof = _get_profile() or {}
        dob = prof.get("date_of_birth")
        age_years = None
        if dob:
            try:
                d = datetime.strptime(str(dob)[:10], "%Y-%m-%d")
                age_years = (datetime.now(timezone.utc).replace(tzinfo=None) - d).days / 365.25
            except (ValueError, TypeError):
                age_years = None

        if missing or age_years is None:
            return _ok(
                {
                    "phenoage": None,
                    "missing": missing or (["chronological age (profile)"] if age_years is None else []),
                    "as_of": labs.get("latest_draw_date"),
                    "lymphocyte_derived": lymph_derived,
                },
                cache_seconds=3600,
            )

        # Convert to formula units.
        vals = {
            "albumin_gL": raw["albumin"] * 10.0,  # g/dL → g/L
            "creatinine_umolL": raw["creatinine"] * 88.42,  # mg/dL → µmol/L
            "glucose_mmolL": raw["glucose"] / 18.0182,  # mg/dL → mmol/L
            "crp_mgdL": raw["crp"] / 10.0,  # mg/L → mg/dL
            "lymphocyte_pct": lymph_pct,
            "mcv_fL": raw["mcv"],
            "rdw_pct": raw["rdw"],
            "alp_UL": raw["alp"],
            "wbc_1000": raw["wbc"],
        }
        pheno = _compute_phenoage(vals, age_years)
        if pheno is None:
            return _ok({"phenoage": None, "missing": ["computation failed"], "as_of": labs.get("latest_draw_date")}, cache_seconds=3600)

        # Per-marker driver direction (younger/older) vs healthy reference — transparent, but
        # NOT the raw contribution (keeps the published surface from adding inversion precision).
        import math

        drivers = []
        for key, (coef, ref) in _PHENOAGE_COEF.items():
            if key == "lncrp":
                val_f = math.log(max(0.01, vals["crp_mgdL"]))
                ref_f = math.log(0.1)
                disp_val, disp_unit = raw["crp"], "mg/L"
            else:
                val_f = vals[key]
                ref_f = ref
                disp_val, disp_unit = {
                    "albumin_gL": (raw["albumin"], "g/dL"),
                    "creatinine_umolL": (raw["creatinine"], "mg/dL"),
                    "glucose_mmolL": (raw["glucose"], "mg/dL"),
                    "lymphocyte_pct": (lymph_pct, "%"),
                    "mcv_fL": (raw["mcv"], "fL"),
                    "rdw_pct": (raw["rdw"], "%"),
                    "alp_UL": (raw["alp"], "U/L"),
                    "wbc_1000": (raw["wbc"], "K/µL"),
                }[key]
            push = coef * (val_f - ref_f)  # >0 raises pheno (older), <0 lowers (younger)
            direction = "older" if push > 0.02 else ("younger" if push < -0.02 else "neutral")
            drivers.append(
                {
                    "name": _PHENOAGE_LABELS[key],
                    "value": disp_val,
                    "unit": disp_unit,
                    "direction": direction,
                    "derived": (key == "lymphocyte_pct" and lymph_derived),
                }
            )

        # Round to the nearest year for display; chronological age and the gap are NOT returned.
        return _ok(
            {
                "phenoage": round(pheno),
                "as_of": labs.get("latest_draw_date"),
                "drivers": drivers,
                "lymphocyte_derived": lymph_derived,
                "missing": [],
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[phenoage] failed: {e}")
        return _error(503, "Phenotypic age temporarily unavailable.")


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
    """GET /api/observatory_week?domain=sleep[&date=YYYY-MM-DD] — 7-day domain summary.

    With ?date= (Phase 4 historical window): the 7-day window AS OF that date — records
    served verbatim (gaps stay gaps, never interpolated), pilot/prior-cycle records
    included (history is explicitly cross-cycle, mirroring handle_character), a future
    date clamps to today, and the response caches a full day (the past is immutable).
    """
    qs = qs or {}
    domain = (qs.get("domain") or "sleep").lower().strip()
    valid_domains = {"sleep", "glucose", "nutrition", "training", "mind", "physical"}
    if domain not in valid_domains:
        return _error(400, f"Invalid domain. Use: {', '.join(sorted(valid_domains))}")

    import re as _re
    from datetime import datetime, timedelta, timezone

    date = (qs.get("date") or "").strip()
    if date and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return _error(400, "date must be YYYY-MM-DD")
    ip = bool(date)  # ADR-058: include pilot/prior-cycle records only when time-travelling

    now = datetime.now(timezone.utc)
    # Anchor the window to `date` (clamped to today so a future scrub shows the live week),
    # else to now. start/prev_* derive off the anchor — every domain branch below is unchanged.
    anchor = min(date, now.strftime("%Y-%m-%d")) if date else now.strftime("%Y-%m-%d")
    _anchor = datetime.strptime(anchor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_date = anchor
    start_date = max((_anchor - timedelta(days=7)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    prev_start = max((_anchor - timedelta(days=14)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    prev_end = max((_anchor - timedelta(days=8)).strftime("%Y-%m-%d"), EXPERIMENT_START)

    try:
        if domain == "sleep":
            items = _query_source("whoop", start_date, end_date, include_pilot=ip)
            prev_items = _query_source("whoop", prev_start, prev_end, include_pilot=ip)

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
            items = _query_source("macrofactor", start_date, end_date, include_pilot=ip)
            prev_items = _query_source("macrofactor", prev_start, prev_end, include_pilot=ip)

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

            # Nutrition uploads at end of day, so today is structurally never logged yet.
            # Counting it in the denominator (the old "X/7") made perfect logging read as a
            # gap. Denominator = COMPLETE days in the window (through yesterday); today's
            # absence is expected, surfaced via current_day_pending — not a miss.
            try:
                _complete_days = max(1, (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days)
            except Exception:
                _complete_days = 6
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
                "lowlight": {
                    "label": "Days logged",
                    "value": f"{len(cals)}/{_complete_days}",
                    "detail": "complete days · today uploads tonight",
                },
                "current_day_pending": True,
            }
            notable = f"Protein averaged {round(avg_protein)}g/day this week"

        elif domain == "training":
            items = _query_source("whoop", start_date, end_date, include_pilot=ip)
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
            items = _query_source("apple_health", start_date, end_date, include_pilot=ip)
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
            items = _query_source("journal", start_date, end_date, include_pilot=ip)
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
            items = _query_source("withings", start_date, end_date, include_pilot=ip)
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
                "as_of_date": end_date,
                "time_travel": ip,
            },
            cache_seconds=86400 if ip else 900,  # the past is immutable
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
    3: "2026-06-08",  # baseline 311.62
    4: "2026-06-14",  # current run — Sunday-anchored routine (baseline 306.87)
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
                Namespace=namespace,
                MetricName=metric,
                Dimensions=[{"Name": dim_name, "Value": dim_value}],
                StartTime=start,
                EndTime=now,
                Period=86400,
                Statistics=["Sum"],
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


# ══════════════════════════════════════════════════════════════════════════════
# The Survival Curve (2026-06-13) — the model handicaps its own human.
# "Engagement" = a day with any deliberate behavioral input: a weigh-in
# (withings), a food log (macrofactor), or a journal entry (notion). Passive
# wearable streams don't count — they flow whether or not Matthew shows up.
# Collapse = the first 4+ consecutive silent days. With n=2 prior cycles this
# is narrative statistics, and the payload says so loudly.
# ══════════════════════════════════════════════════════════════════════════════
_ENGAGEMENT_SOURCES = ("withings", "macrofactor", "notion")
_COLLAPSE_GAP = 4
_SURVIVAL_HORIZON = 30


def _engaged_dates(start: str, end: str) -> set:
    days = set()
    for src in _ENGAGEMENT_SOURCES:
        for r in _query_source(src, start, end, include_pilot=True):
            days.add(str(r.get("sk", ""))[5:15])
    return days


def handle_survival() -> dict:
    """GET /api/survival — per-cycle engagement strips + a loudly-caveated
    probability that the current cycle reaches day 30."""
    try:
        today = datetime.now(PT).date()
        geneses = sorted(CYCLE_GENESES.items())
        cycles, priors = [], []
        for idx, (n, genesis) in enumerate(geneses):
            g = datetime.strptime(genesis, "%Y-%m-%d").date()
            next_g = datetime.strptime(geneses[idx + 1][1], "%Y-%m-%d").date() if idx + 1 < len(geneses) else None
            last = min((next_g - timedelta(days=1)) if next_g else today, g + timedelta(days=69))
            window = (last - g).days + 1
            if window < 1:
                continue
            engaged = _engaged_dates(genesis, last.isoformat())
            strip = [(g + timedelta(days=i)).isoformat() in engaged for i in range(window)]
            collapse_day = None
            for i in range(0, window - _COLLAPSE_GAP + 1):
                if not any(strip[i : i + _COLLAPSE_GAP]):
                    collapse_day = i + 1
                    break
            is_current = next_g is None
            ended_by_reset = next_g is not None and collapse_day is None
            cycles.append(
                {
                    "cycle": n,
                    "genesis": genesis,
                    "is_current": is_current,
                    "window_days": window,
                    "engaged_days": sum(strip),
                    "strip": "".join("█" if d else "·" for d in strip),
                    "collapse_day": collapse_day,
                    "censored": ended_by_reset,  # re-anchored while still engaged
                }
            )
            if not is_current:
                priors.append((collapse_day, window))

        # Laplace-smoothed survival-to-30 from prior cycles: a cycle counts as a
        # survivor if it stayed engaged through day 30 OR was reset while still
        # engaged before 30 (censored — treated optimistically, and we say so).
        survivors = sum(1 for cd, w in priors if cd is None or cd > _SURVIVAL_HORIZON)
        p30 = round((survivors + 1) / (len(priors) + 2) * 100)

        cur = next((c for c in cycles if c["is_current"]), None)
        cur_strip = cur["strip"] if cur else ""
        silent_now = len(cur_strip) - len(cur_strip.rstrip("·")) if cur else 0

        return _ok(
            {
                "horizon_days": _SURVIVAL_HORIZON,
                "p_reach_30_pct": p30,
                "method": f"Laplace-smoothed over {len(priors)} prior cycles: (survivors+1)/(n+2). n=2 is narrative, not statistics.",
                "current_silent_days": silent_now,
                "collapse_definition": f"{_COLLAPSE_GAP}+ consecutive days with no weigh-in, food log, or journal entry",
                "cycles": cycles,
                "confidence": "preliminary pattern · n=2 cycles",
                "note": (
                    "The model handicapping its own human. Engagement counts only deliberate "
                    "acts — weigh-ins, food logs, journal entries — never passive wearable data. "
                    "Treat the probability as a mirror, not a forecast."
                ),
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[survival] failed: {e}")
        return _error(503, "Survival curve temporarily unavailable.")
