"""lambdas/web/site_api_budget.py — the AI-spend transparency surface.

Split out of ``site_api_intelligence.py`` (#1654 — god-module breakup). One
seam, one domain: **what the platform spends on inference and the envelope that
governs it.** That is `/api/inference_receipt` (per-model tokens, priced with the
governor's own table) and `/api/receipts` (the Glass Engine — month-to-date, the
month-end projection, the live ADR-063/ADR-133 ceiling, the tier and what it
pauses), plus the `/api/status` cost block that reads the same breakdown so the
two can never disagree.

The routed handler entrypoints stay in the ``site_api_intelligence`` facade as
thin delegators; the logic lives here. Unlike the other split siblings, nothing
in this module reads injectable per-request state, so its functions take no
``_g``: the only substitutable dependency is ``boto3.client``, and the tests that
stub it (``test_receipts_endpoint``, ``test_inference_receipt_*``) patch the
attribute on the **boto3 module object** — which every importer shares — not on a
module-level binding. This module does NOT import the facade; no import cycle.
"""

import calendar
import json
from datetime import datetime, timezone

import boto3
from common.pacific_time import parse_iso_utc  # #1964: the ONE ISO-8601 parser

# #1997: import (never hand-copy) the governor's price table + safety buffer so the
# public inference receipt cannot silently drift from the number that actually gates
# the budget tier. Importing the module executes its body — it constructs its own
# cloudwatch/ssm/sns/ce boto3 clients (pure local object construction, no network call,
# no new IAM requirement since site-api's role never calls their methods) — a deliberate,
# informed cold-start tradeoff over a second hand-maintained copy that can drift.
from operational.cost_governor_lambda import _AI_SAFETY_BUFFER, _PRICES as _BEDROCK_PRICES

from web.site_api_common import _error, _ok, logger

__all__ = [
    "_ADR133_BASE_CEILING_USD",
    "_AI_SAFETY_BUFFER",
    "_BEDROCK_PRICES",
    "_BREAKDOWN_MAX_AGE_S",
    "_BUDGET_TIER_STATUS",
    "_TIER_SEMANTICS",
    "_budget_cost_block",
    "_budget_history",
    "_ceiling_envelope",
    "_ceiling_window_clause",
    "_price_for_model",
    "inference_receipt",
    "receipts",
]

# ══════════════════════════════════════════════════════════════════════════════
# The inference receipt (2026-06-13) — radical cost transparency.
# Every Claude call already lands in two metric streams: AWS/Bedrock emits
# token counts per ModelId, and the bundled modules emit per-Lambda tokens to
# LifePlatform/AI. This endpoint reads both, prices them with the same table
# the cost governor enforces, and publishes the meter.
# ══════════════════════════════════════════════════════════════════════════════
# _BEDROCK_PRICES / _AI_SAFETY_BUFFER are imported above, straight from the governor —
# see the #1997 comment at the import site. Nothing hand-maintained here anymore.


def _price_for_model(model_id: str):
    """Match against the governor's own family keys (imported, not copied — #1997).
    Returns None — never a fallback price — for a model outside those families (e.g.
    amazon.titan-embed-text-v2, an embedding model with no verified per-token price
    anywhere in this codebase). ADR-104 forbids inventing a number we can't ground;
    the old Sonnet-rate fallback was exactly that. Callers treat None as: show token
    counts, omit the dollar estimate — never silently price it."""
    m = (model_id or "").lower()
    for k, p in _BEDROCK_PRICES.items():
        if k in m:
            return p
    return None


# #1230: the ADR-133 base ceiling (amendment 2026-07-08, $75→$85). The live ceiling is
# derived from the governor's /life-platform/budget-breakdown param (#822) — it floats to
# $100 in reader-traffic surge mode. This constant is ONLY the fail-closed fallback when
# that read fails; never the retired $75.
#
# #1999: it is now a fallback in the strict sense. The breakdown payload carries
# `base_ceiling`/`surge_ceiling`/`ceiling_window`, and the handlers below read the base
# from there. This literal is reached only when the payload is missing, unreadable, or
# predates that schema (old payloads persist until the governor's next 8h run rewrites
# them) — never as the published number when the governor has stated one.
_ADR133_BASE_CEILING_USD = 150.0


def _ceiling_envelope(breakdown):
    """(base_ceiling, surge_ceiling, ceiling_window) from a breakdown dict (#1999).

    The base fails closed to `_ADR133_BASE_CEILING_USD` when the governor hasn't
    stated one; surge and window stay None rather than being guessed, so a page
    renders an honest gap instead of a fabricated envelope. Never raises — a
    garbled field costs the envelope, never the receipt.
    """
    base, surge, window = _ADR133_BASE_CEILING_USD, None, None
    if isinstance(breakdown, dict):
        try:
            if breakdown.get("base_ceiling") is not None:
                base = float(breakdown["base_ceiling"])
            if breakdown.get("surge_ceiling") is not None:
                surge = float(breakdown["surge_ceiling"])
        except (TypeError, ValueError):
            base, surge = _ADR133_BASE_CEILING_USD, None
        w = breakdown.get("ceiling_window")
        if isinstance(w, dict) and w:
            window = w
    return base, surge, window


def _ceiling_window_clause(window) -> str:
    """Reader-facing prose for an active dated ceiling window, or "" (#1999).

    This is the sentence whose absence was the defect: during the July 2026
    window the receipt served the module base literal, a higher ceiling in
    effect, and `surge_active: false` — three honest numbers and no mechanism
    that explained the gap between them. Everything here is projected from the
    governor's own descriptor; nothing is inferred, and an incomplete descriptor
    yields "" rather than a half-sentence.
    """
    if not isinstance(window, dict):
        return ""
    try:
        start = str(window["start"])
        end = str(window["end_exclusive"])
        win_base = float(window["base_ceiling"])
        reverts = float(window["reverts_to_base_ceiling"])
    except (KeyError, TypeError, ValueError):
        return ""
    clause = (
        f" The base is temporarily ${win_base:.0f} rather than the usual ${reverts:.0f}, "
        f"under a dated window running {start} until {end}."
    )
    reason = str(window.get("reason") or "").strip()
    if reason:
        clause += f" {reason}"
    return clause


def inference_receipt() -> dict:
    """GET /api/inference_receipt — today's AI calls + month-to-date, priced."""
    try:
        cw = boto3.client("cloudwatch", region_name="us-west-2")
        ssm = boto3.client("ssm", region_name="us-west-2")
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ── One batched read, not ~62 serial ones (#1911) ──────────────────────
        # This handler used to call get_metric_statistics once per (metric, window,
        # dimension): 6 models x 2 windows x 2 metrics + 19 lambdas x 2 metrics ≈ 62
        # SEQUENTIAL CloudWatch calls. That is ~1.6s warm, and when any of those calls
        # is throttled (boto3 then retries with exponential backoff) the handler ran
        # 11-15s. Measured at the origin, that is exactly what auto-rolled-back two
        # correct merged deploys: 2026-07-29 ended at 16:10:19 after 11,628ms and
        # 2026-07-30 at 18:00:15 after 14,934ms, both with NO cold start (InitDuration
        # absent) — the smoke's `curl --max-time 10` gave up mid-flight and its exit 28
        # was read as a bad deploy. (The earlier cold-start hypothesis was wrong; this
        # is handler cost.) Readers rarely saw it because the response is edge-cached
        # for 900s — but the smoke deliberately cache-busts, so it always pays full price.
        #
        # GetMetricData takes up to 500 queries in ONE call, so the whole sweep is now a
        # single round trip. Threads were considered and rejected: #1527 showed a
        # per-thread boto3 Session on this fleet REGRESSED origin latency 3.6s -> 12-16s
        # (Session construction is pure-Python setup the GIL serializes).
        #
        # Windows: one query per (metric, dimension) over the MONTH at Period=86400
        # yields per-day buckets — "month" sums them all, "today" sums the buckets at or
        # after midnight UTC. Same numbers as the old two-window pair, half the queries,
        # and today's figure can no longer disagree with the month's (they now derive
        # from one read instead of two taken seconds apart).
        def _batch_daily(specs):
            """specs: list of (id, namespace, metric, dim_name, dim_value).
            Returns {id: [(timestamp, value), ...]} from a single GetMetricData sweep."""
            if not specs:
                return {}
            queries = [
                {
                    "Id": qid,
                    "MetricStat": {
                        "Metric": {"Namespace": ns, "MetricName": mn, "Dimensions": [{"Name": dn, "Value": dv}]},
                        "Period": 86400,
                        "Stat": "Sum",
                    },
                    "ReturnData": True,
                }
                for qid, ns, mn, dn, dv in specs
            ]
            out: dict = {}
            token = None
            # GetMetricData caps at 500 queries per call; chunk so the sweep stays
            # correct if the platform ever emits more metrics than that.
            for i in range(0, len(queries), 500):
                chunk = queries[i : i + 500]
                token = None
                while True:
                    kwargs = {"MetricDataQueries": chunk, "StartTime": month_start, "EndTime": now}
                    if token:
                        kwargs["NextToken"] = token
                    resp = cw.get_metric_data(**kwargs)
                    for r in (resp or {}).get("MetricDataResults") or []:
                        out.setdefault(r.get("Id"), []).extend(zip(r.get("Timestamps") or [], r.get("Values") or []))
                    token = (resp or {}).get("NextToken")
                    if not token:
                        break
            return out

        def _split(points):
            """(month_total, today_total) from one metric's daily buckets.

            Timestamps are normalised to UTC-aware before comparing: boto3 returns
            tz-aware datetimes, but a naive one would raise TypeError here and — because
            the whole handler is wrapped in a try/except — silently 503 the endpoint
            rather than surface the bug.
            """
            month_total = 0.0
            today_total = 0.0
            for ts, v in points:
                val = float(v)
                month_total += val
                if ts is not None and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts is not None and ts >= day_start:
                    today_total += val
            return month_total, today_total

        # Per-model (AWS/Bedrock emits these for every invoke) + per-feature (the
        # bundled modules' own dimension) are gathered in ONE batch.
        model_ids: list = []
        specs: list = []
        qid_map: dict = {}
        seen = cw.list_metrics(Namespace="AWS/Bedrock", MetricName="InputTokenCount")
        for m in seen.get("Metrics", []):
            mid = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "ModelId"), None)
            if not mid:
                continue
            model_ids.append(mid)
            # #1997: cache read/write ride the same sweep as in/out — the governor's own
            # _ai_cost() reads these four metrics per model; the receipt must match.
            for field, metric_name in (
                ("in", "InputTokenCount"),
                ("out", "OutputTokenCount"),
                ("cache_read", "CacheReadInputTokenCount"),
                ("cache_write", "CacheWriteInputTokenCount"),
            ):
                qid = f"q{len(specs)}"
                qid_map[("model", mid, field)] = qid
                specs.append((qid, "AWS/Bedrock", metric_name, "ModelId", mid))

        fn_names = []
        fn_metrics = cw.list_metrics(Namespace="LifePlatform/AI", MetricName="AnthropicInputTokens")
        for m in fn_metrics.get("Metrics", []):
            fn = next((d["Value"] for d in m["Dimensions"] if d["Name"] == "LambdaFunction"), None)
            if not fn:
                continue
            fn_names.append(fn)
            for field, metric_name in (("in", "AnthropicInputTokens"), ("out", "AnthropicOutputTokens")):
                qid = f"q{len(specs)}"
                qid_map[("feature", fn, field)] = qid
                specs.append((qid, "LifePlatform/AI", metric_name, "LambdaFunction", fn))

        series = _batch_daily(specs)

        models = []
        unpriced_models = set()
        for mid in model_ids:
            price = _price_for_model(mid)
            in_month, in_today = _split(series.get(qid_map[("model", mid, "in")], []))
            out_month, out_today = _split(series.get(qid_map[("model", mid, "out")], []))
            cr_month, cr_today = _split(series.get(qid_map[("model", mid, "cache_read")], []))
            cw_month, cw_today = _split(series.get(qid_map[("model", mid, "cache_write")], []))
            row = {"model": mid.split("/")[-1]}
            for label, tin, tout, tcr, tcw in (
                ("today", in_today, out_today, cr_today, cw_today),
                ("month", in_month, out_month, cr_month, cw_month),
            ):
                est_cost = None
                if price is not None:
                    raw = (tin * price["in"] + tout * price["out"] + tcr * price["cache_read"] + tcw * price["cache_write"]) / 1_000_000
                    # #1997: buffer applied per-row (not just to the aggregate) so every
                    # displayed dollar figure — today, month, and sum(rows) == total —
                    # stays consistent, matching the governor's _ai_cost() x1.15.
                    est_cost = round(raw * _AI_SAFETY_BUFFER, 4)
                row[label] = {
                    "input_tokens": int(tin),
                    "output_tokens": int(tout),
                    "cache_read_tokens": int(tcr),
                    "cache_write_tokens": int(tcw),
                    "est_cost_usd": est_cost,
                }
            if (
                row["month"]["input_tokens"]
                or row["month"]["output_tokens"]
                or row["month"]["cache_read_tokens"]
                or row["month"]["cache_write_tokens"]
            ):
                models.append(row)
                if price is None:
                    unpriced_models.add(row["model"])

        features = []
        for fn in fn_names:
            tin, _ = _split(series.get(qid_map[("feature", fn, "in")], []))
            tout, _ = _split(series.get(qid_map[("feature", fn, "out")], []))
            if tin or tout:
                features.append({"lambda": fn, "month_input_tokens": int(tin), "month_output_tokens": int(tout)})
        features.sort(key=lambda f: -(f["month_input_tokens"] + f["month_output_tokens"]))

        try:
            tier = int(ssm.get_parameter(Name="/life-platform/budget-tier")["Parameter"]["Value"])
        except Exception:
            tier = None

        # #1230: derive the ceiling from the governor's breakdown param (#822 / ADR-133)
        # rather than a hardcoded literal — the base is $85 and floats to $100 in surge
        # mode, so a hardcoded number is guaranteed to be a lie. Fail closed to the $85
        # base (never the retired $75) if the breakdown read fails.
        ceiling_usd = _ADR133_BASE_CEILING_USD
        surge_active = False
        breakdown = None
        try:
            breakdown = json.loads(ssm.get_parameter(Name="/life-platform/budget-breakdown")["Parameter"]["Value"])
            ceiling_usd = float(breakdown["ceiling"])
            surge_active = bool(breakdown.get("surge_active", False))
        except Exception:
            breakdown = None
        # #1999: the base comes from the governor's payload too — the literal above is
        # the fail-closed fallback for a missing/pre-#1999 payload, not the published number.
        base_ceiling_usd, _surge_ceiling_usd, ceiling_window = _ceiling_envelope(breakdown)

        # #1997: unpriced (e.g. Titan/embedding) rows contribute tokens, not dollars —
        # None rows are skipped rather than treated as $0 or guessed at Sonnet rates.
        month_total = round(sum(r["month"]["est_cost_usd"] for r in models if r["month"]["est_cost_usd"] is not None), 2)
        surge_clause = " — reader-traffic surge mode" if surge_active else ""
        unpriced_clause = ""
        if unpriced_models:
            plural = "s" if len(unpriced_models) != 1 else ""
            unpriced_clause = (
                f" {len(unpriced_models)} model{plural} this period ({', '.join(sorted(unpriced_models))}) "
                "have no verified per-token price in this codebase (e.g. embedding models) — "
                "token counts are shown, no dollar figure is estimated for them, and they are "
                "excluded from the total below rather than guessed."
            )
        note = (
            "Every Claude call routes through one audited chokepoint (ADR-062). "
            "Costs are estimated from token metrics (including cache read/write) x "
            "list prices, x1.15 — the same math and the same x1.15 safety buffer the "
            f"budget governor enforces.{unpriced_clause} The ${base_ceiling_usd:.0f} "
            f"base ceiling (${ceiling_usd:.0f} in effect{surge_clause}) covers the WHOLE "
            "platform, not just AI."
            f"{_ceiling_window_clause(ceiling_window)}"
        )
        return _ok(
            {
                "as_of": now.isoformat(timespec="seconds"),
                "budget_ceiling_usd": ceiling_usd,
                "budget_base_ceiling_usd": base_ceiling_usd,
                "budget_surge_ceiling_usd": _surge_ceiling_usd,
                "budget_ceiling_window": ceiling_window,
                "budget_surge_active": surge_active,
                "budget_tier": tier,
                "ai_month_to_date_usd": month_total,
                "models": models,
                "features": features,
                "note": note,
            },
            cache_seconds=900,
        )
    except Exception as e:
        logger.warning(f"[inference_receipt] failed: {e}")
        return _error(503, "Inference receipt temporarily unavailable.")


# ══════════════════════════════════════════════════════════════════════════════
# The Glass Engine (#1397) — the budget tier as an instrument.
#
# /api/inference_receipt already publishes the AI half (per-model tokens, priced).
# This endpoint publishes the ENVELOPE that governs it: the governor's own
# month-to-date and month-end projection, the live ceiling (ADR-063/ADR-133,
# floating to the surge ceiling), the tier and what that tier actually pauses,
# and the daily spend curve.
#
# Every number is read from what cost_governor_lambda already writes — the SSM
# breakdown param (#822) and its CloudWatch metrics (LifePlatform/Budget). No
# hand-maintained figures, and no recomputation of the governor's math here: if
# the two ever disagreed, the page would be lying about the thing it exists to
# make legible.
#
# Honesty rules this endpoint enforces (ADR-104 / AC4):
#   * The breakdown param is the only source of mtd/projected/ceiling. If it is
#     missing or stale, the payload says so via `stale` + `stale_reason` and the
#     figures are omitted rather than frozen at their last value. A silently
#     stale cost page is worse than an absent one.
#   * Per-feature spend is reported in TOKENS, not dollars. The per-Lambda metric
#     stream (LifePlatform/AI) carries no model dimension, so tokens cannot be
#     priced per feature without inventing a model mix. Stating tokens and saying
#     why is honest; a plausible dollar figure would not be.
# ══════════════════════════════════════════════════════════════════════════════

# Mirrors cost_governor_lambda._TIER_LABELS. Kept as prose the reader can act on:
# each entry names what is actually switched off at that tier, not a severity word.
# tests/test_receipts_endpoint.py asserts this stays lockstep with the governor.
_TIER_SEMANTICS = {
    0: "All AI features active. Nothing is paused.",
    1: "Internal/dev AI paused — the ensemble, the chronicle editor, and coherence-semantic checks. Reader-facing AI is untouched.",
    2: "Reader narratives paused as well — coach commentary, State of Matthew, the chronicle.",
    3: "Hard stop. The ask endpoints are paused and the daily brief ships data-only, without AI narrative.",
}

# The governor writes the breakdown every enforcement run (~every 8h). Past this
# age the figures stop being "live" in any meaningful sense — same 48h bound
# budget_guard._BREAKDOWN_MAX_AGE_S applies, kept in sync by the same test.
_BREAKDOWN_MAX_AGE_S = 48 * 3600

# #1909: /api/status's traffic-light, derived from the tier rather than from a
# percentage against an invented denominator. Keyed to what a READER loses, which
# is what a status page is answering — the exact machine state is published
# alongside as `tier` + `tier_semantics`, so nothing is hidden by the collapse.
#
# Tier 1 is yellow, not green: something IS switched off. Calling it green would
# be the flattering-number half of the same ADR-104 failure this issue fixes on
# the alarming side. #1927 makes the case concretely — band 1 contains two CI
# gates, and 26 straight days of "green" while they were paused is exactly the
# reading this mapping refuses to produce.
_BUDGET_TIER_STATUS = {0: "green", 1: "yellow", 2: "yellow", 3: "red"}


def _budget_history(cw, month_start, now) -> list:
    """Daily month-to-date spend curve from the governor's own CloudWatch metric.

    LifePlatform/Budget::EstimatedMonthToDateSpend is emitted every enforcement
    run, so a day holds several datapoints — Maximum collapses each day to that
    day's high-water MTD, which is what a cumulative curve should show. Fail-soft
    to [] (the chart simply doesn't render) — a missing curve must never take the
    rest of the receipt down with it.
    """
    try:
        r = cw.get_metric_statistics(
            Namespace="LifePlatform/Budget",
            MetricName="EstimatedMonthToDateSpend",
            StartTime=month_start,
            EndTime=now,
            Period=86400,
            Statistics=["Maximum"],
        )
        pts = sorted(r.get("Datapoints", []), key=lambda p: p["Timestamp"])
        return [{"date": p["Timestamp"].strftime("%Y-%m-%d"), "mtd_usd": round(float(p["Maximum"]), 2)} for p in pts]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[receipts] history unavailable: {e}")
        return []


def receipts() -> dict:
    """GET /api/receipts — the live bill and the budget tier, as an instrument (#1397)."""
    try:
        cw = boto3.client("cloudwatch", region_name="us-west-2")
        ssm = boto3.client("ssm", region_name="us-west-2")
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # The calendar-deterministic day the projection lands on. This is NOT a
        # forecast (the DOLLAR figure is the governor's projected_month_end_usd, below)
        # — just the x-axis anchor the spend curve extends its dashed projection to, so
        # the front-end never has to derive a date and risk a second projection (#1618).
        # utc-exempt(#2414): the AWS billing month is a UTC calendar month (Cost
        # Explorer / the governor's projection window) — not the reader's Pacific day.
        month_end_date = now.replace(day=calendar.monthrange(now.year, now.month)[1]).strftime("%Y-%m-%d")

        try:
            tier = int(ssm.get_parameter(Name="/life-platform/budget-tier")["Parameter"]["Value"])
        except Exception:
            tier = None

        # The breakdown carries every dollar figure on this page. Anything it
        # doesn't give us stays None and renders as an honest gap.
        breakdown, stale, stale_reason = None, True, "budget breakdown unavailable"
        try:
            raw = ssm.get_parameter(Name="/life-platform/budget-breakdown")["Parameter"]["Value"]
            candidate = json.loads(raw)
            computed_at = candidate.get("computed_at")
            age_s = None
            if computed_at:
                try:
                    parsed = parse_iso_utc(computed_at)
                    age_s = (now - parsed).total_seconds() if parsed else None
                except Exception:  # noqa: BLE001
                    age_s = None
            if age_s is None:
                stale_reason = "budget breakdown carries no readable computed_at"
            elif age_s > _BREAKDOWN_MAX_AGE_S:
                stale_reason = f"budget breakdown last computed {int(age_s // 3600)}h ago (governor runs every 8h)"
            else:
                breakdown, stale, stale_reason = candidate, False, None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[receipts] breakdown read failed: {e}")

        ceiling = float(breakdown["ceiling"]) if breakdown and breakdown.get("ceiling") is not None else None
        mtd = float(breakdown["mtd"]) if breakdown and breakdown.get("mtd") is not None else None
        projected = float(breakdown["projected"]) if breakdown and breakdown.get("projected") is not None else None
        surge_active = bool(breakdown.get("surge_active", False)) if breakdown else False
        # #1999: the ADR-133 envelope (base/surge pair + any dated window) now comes from
        # the governor rather than a literal, so the page can explain a raised base instead
        # of serving an unattributed delta.
        base_ceiling, surge_ceiling, ceiling_window = _ceiling_envelope(breakdown)

        payload = {
            "as_of": now.isoformat(timespec="seconds"),
            "stale": stale,
            "stale_reason": stale_reason,
            "tier": tier,
            "tier_semantics": _TIER_SEMANTICS.get(tier) if tier is not None else None,
            "base_ceiling_usd": base_ceiling,
            "surge_ceiling_usd": surge_ceiling,
            # The dated ADR-133 window in effect, or null. Present so the page can
            # attribute a raised base instead of leaving the delta unexplained (#1999).
            "ceiling_window": ceiling_window,
            "ceiling_usd": ceiling,
            "surge_active": surge_active,
            "surge_threshold_uniques": (breakdown or {}).get("surge_threshold"),
            "recent_uniques": (breakdown or {}).get("recent_uniques"),
            "month_to_date_usd": mtd,
            "projected_month_end_usd": projected,
            # Where the projection lands (last day of the current month) — the dashed
            # spend-curve segment extends to this date, anchored on projected above (#1618).
            "month_end_date": month_end_date,
            "ai_daily_usd": (breakdown or {}).get("ai_daily"),
            "non_ai_daily_usd": (breakdown or {}).get("non_ai_daily"),
            "computed_at": (breakdown or {}).get("computed_at"),
            "history": _budget_history(cw, month_start, now),
            # Why there is no per-feature dollar column — surfaced in the payload so
            # the page can state it rather than leave a reader guessing.
            "per_feature_note": (
                "Per-feature usage is reported in tokens, not dollars: the per-Lambda "
                "metric stream carries no model dimension, so pricing it would mean "
                "inventing a model mix. See /method/inference/ for per-model cost."
            ),
            "note": (
                "One AWS budget covers the WHOLE platform, not just AI. The governor "
                "reprojects month-end spend every 8 hours and writes the tier it "
                "implies; every AI feature reads that tier before it runs."
                f"{_ceiling_window_clause(ceiling_window)}"
            ),
        }
        if ceiling and projected is not None:
            payload["projected_pct_of_ceiling"] = round(projected / ceiling * 100, 1)
        if ceiling and mtd is not None:
            payload["mtd_pct_of_ceiling"] = round(mtd / ceiling * 100, 1)
        return _ok(payload, cache_seconds=900)
    except Exception as e:
        logger.warning(f"[receipts] failed: {e}")
        return _error(503, "Receipts temporarily unavailable.")


def _budget_cost_block() -> dict:
    """The /api/status cost block, from the governor's own numbers (#1909).

    A module-level function rather than an inline stretch of handle_status so it
    can be exercised on its own: the honesty of these figures is the whole point
    of the issue, and a test that had to stand up the entire status handler
    (DynamoDB, CloudWatch, every pipeline component) to reach four lines of
    arithmetic would be testing everything except the thing that was wrong.
    """
    # ── Cost: report the number the SYSTEM acts on (#1909) ──────────────────
    # This block used to call Cost Explorer itself and divide by a hardcoded
    # `budget = 15.0` — a literal that predates the ADR-063 budget system and has
    # no relation to any real ceiling. It published `pct_of_budget: 627, status:
    # "red"` on a platform operating correctly INSIDE its ceiling: the inverse of
    # the usual honest-numbers failure, a needlessly alarming number rather than a
    # flattering one. ADR-104 cuts both ways.
    #
    # It also re-derived the projection with its own assumptions (`days_in_month =
    # 30`), so the platform published TWO different projections of one quantity,
    # ~$8 apart. And `TimePeriod={"Start": month_start, "End": today}` is an empty
    # range on the 1st of the month, which CE rejects — so the whole cost block
    # silently vanished every month-start (confirmed in the site-api log:
    # 3 x ValidationException on 2026-08-01, none on other days).
    #
    # All three come from re-deriving what cost_governor already computes. Read
    # its persisted breakdown instead — same numbers the tier decision is made
    # from, so they cannot disagree by construction. It carries the EFFECTIVE
    # ceiling, so the ADR-133 dated window and the surge float are handled without
    # this endpoint knowing they exist. No Cost Explorer call, no $0.01/call, no
    # 24h cache to reason about, and nothing to break on the 1st.
    #
    # read_breakdown() returns None when the parameter is missing, unparseable or
    # >48h stale, and never raises. None means we publish NO cost block rather
    # than a stale or invented one.
    cost_info = {}
    try:
        from ai import budget_guard

        breakdown = budget_guard.read_breakdown()
        if breakdown:
            ceiling = float(breakdown["ceiling"])
            projected = float(breakdown["projected"])
            tier = int(breakdown["tier"])
            cost_info = {
                "mtd": round(float(breakdown["mtd"]), 2),
                "projected": round(projected, 2),
                "budget": ceiling,  # key name kept — existing readers of this payload
                "tier": tier,
                # Same prose /api/receipts publishes, from the same dict — one
                # vocabulary for one fact (a test keeps it lockstep with the governor).
                "tier_semantics": _TIER_SEMANTICS.get(tier),
                "status": _BUDGET_TIER_STATUS.get(tier, "yellow"),
                "pct_of_budget": round((projected / ceiling) * 100) if ceiling else None,
                "as_of": breakdown.get("computed_at"),
            }
    except Exception as e:  # noqa: BLE001 — display-only; never break /api/status
        logger.warning(f"[status] budget breakdown unavailable (non-fatal): {e}")
    return cost_info
