"""lambdas/web/site_api_ledger.py — accountability + discoveries surface split out of
site_api_data.py (#1654): ledger / what_changed / discoveries. Reads facade state via `_g`."""

import json
import os

import stats_core
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter

from web.site_api_common import S3_REGION, USER_PREFIX, _decimal_to_float, _ok, logger


def ledger(*, _g) -> dict:
    """
    GET /api/ledger
    Returns: Ledger transactions (by event and by cause) + running totals.
    Source: ledger DynamoDB partition + config/ledger.json from S3.
    Cache: 3600s.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    boto3 = _g["boto3"]
    table = _g["table"]
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


def what_changed(*, _g) -> dict:
    """GET /api/what_changed — SS-08 monthly "what changed": real trailing-30d vs
    prior-30d deltas + correlations newly FDR-significant in the last 30 days, so a
    flat day still shows monthly motion. Written weekly by weekly-correlation-compute.
    Shaped-empty 200 before the first run; honest_null on a genuinely steady month."""
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    table = _g["table"]
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


def discoveries(*, _g) -> dict:
    """
    GET /api/discoveries
    Returns structured content for the Discoveries page:
    - active_hypotheses: from experiment_library S3 config (active experiments)
    - inner_life: from insights partition (chronicle observations)
    - ai_findings: from weekly_correlations (FDR-significant pairs)
    Cache: 1800s (30 min).
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    boto3 = _g["boto3"]
    table = _g["table"]
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
                    # #1089: these library entries are ONGOING supplement protocols —
                    # cross_phase by design (ADR-077), deliberately carried across cycle
                    # resets (active since Feb 2026). They are NOT discoveries or
                    # current-cycle findings; the front-end must label them as carried
                    # protocols so the pre-start surface never reads like leaked findings.
                    "carried_over": True,
                    "protocol_kind": "ongoing_protocol",
                    "active_since": exp.get("promoted_date") or None,
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
                # #1372 Evidence Bar: pass the stored FDR verdict through honestly —
                # a legacy record with only the pre-FDR `significant` flag serves
                # fdr_significant=None ("not checked"), never a fake pass.
                fdr_flag = c.get("fdr_significant")
                ai_findings.append(
                    {
                        "week": week,
                        "metric_a": a,
                        "metric_b": b,
                        "r": round(r, 2) if r else 0,
                        "n": c.get("n", 0),
                        "title": f"{a} × {b}: {direction} correlated",
                        "body": f"r={r:+.2f}, n={c.get('n', '?')} days. " f"FDR-corrected significant finding from {week}.",
                        # #1372: per-claim rigor readout from the ONE sanctioned pure
                        # function (stats_core.correlation_evidence, ADR-105).
                        "evidence": stats_core.correlation_evidence(
                            r, c.get("n", 0), fdr_significant=(bool(fdr_flag) if fdr_flag is not None else None)
                        ),
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
