#!/usr/bin/env python3
"""
ai_spend_attribution.py — per-feature AI (Bedrock) spend ranking (#808 · R22-COST-02).

Why this exists
---------------
Haiku overtook Sonnet as the single largest AI cost line (June 2026 Cost Explorer:
Haiku 4.5 $26.91 > Sonnet 4.6 $17.07), inverting the ADR-049 "structured tasks use
Haiku because it's cheap" premise on volume. `cost_governor_lambda` already knows the
per-MODEL total (AWS/Bedrock token metrics × price) but nothing anywhere ranks the
per-FEATURE spend — so there was no way to see *which* Haiku callers (hypothesis
tester, quality gates, semantic/vision QA, board summaries, coach pipeline, …) drive
the line. This is the missing reporting surface, built on metrics that already exist
(no new machinery — ADR-103): `bedrock_client._emit_usage_metrics()` already emits
`EstimatedCostUSD` + token counts per `LambdaFunction` dimension in the
`LifePlatform/AI` namespace. This script queries and ranks them.

The ranking redirects #409 (batch pricing) at the actual top bucket: a 50% batch
discount on a $27/mo line is ~$13/mo — nearly a full budget tier of headroom.

Model attribution
------------------
The per-feature EMF metrics carry a `LambdaFunction` dimension but no `ModelId`, so
this script BACK-SOLVES the model from the emitted cost: `EstimatedCostUSD` was
computed by `bedrock_client` with the real model price, so the model whose price
formula reproduces the feature's cost from its own token counts is the model it used.
A feature that used more than one model in the window won't match any single price
tier and is reported as `mixed`.

Two data sources, deliberately
------------------------------
  • Per-feature ranking       → LifePlatform/AI  (self-emitted at the chokepoint).
    NB: this UNDER-counts — it only fires for calls that reach
    `_emit_usage_metrics` (misses e.g. any pre-instrumentation calls). It is the
    only per-feature source and the ranking (relative shares) is what matters.
  • Authoritative model totals → AWS/Bedrock      (per-ModelId token counts, the
    same source cost_governor trusts). Printed as a reconciliation footer so the
    under-count is visible, not hidden.

Read-only. Queries CloudWatch GetMetricData + ListMetrics only. Never writes.

Usage
-----
    python3 scripts/ai_spend_attribution.py                # current month-to-date
    python3 scripts/ai_spend_attribution.py --month 2026-06 # a specific calendar month
    python3 scripts/ai_spend_attribution.py --days 30       # trailing N days
    python3 scripts/ai_spend_attribution.py --json          # machine-readable

Run it as the periodic drift-check (RUNBOOK → Cost Monitoring): if a "cheap tier"
feature has crept to the top of the ranking, that's the batch-pricing / prompt-diet
target.
"""

import argparse
import calendar
import json
import os
import sys
from datetime import datetime, timedelta, timezone

# Single source of truth for Bedrock prices + the model back-solve helper: the
# same table bedrock_client uses to compute the EstimatedCostUSD we read back.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lambdas"))
from bedrock_client import _PRICES, estimate_cost_usd  # noqa: E402

NAMESPACE = "LifePlatform/AI"
REGION = os.environ.get("AWS_REGION", "us-west-2")

# Metrics emitted per LambdaFunction by bedrock_client._emit_usage_metrics.
_TOKEN_METRICS = {
    "cost": "EstimatedCostUSD",
    "in": "AnthropicInputTokens",
    "out": "AnthropicOutputTokens",
    "cache_read": "AnthropicCacheReadTokens",
    "cache_write": "AnthropicCacheWriteTokens",
}

# A model back-solve is "confident" when its price formula reproduces the emitted
# cost to within this relative tolerance; otherwise the feature spanned models → mixed.
_MODEL_MATCH_TOL = 0.02


def _cw():
    import boto3

    return boto3.client("cloudwatch", region_name=REGION)


def _metric_period(start: datetime, end: datetime) -> int:
    """GetMetricData Period covering the whole window in ONE bucket.

    CloudWatch requires Period to be a multiple of 60, and arbitrary now-anchored
    windows (month-to-date, --days) almost never land on one — so round the window
    length UP to the next minute (up, never down: a shorter period would split the
    window into more than one bucket and break the one-bucket-sum contract).
    Floor of 60 for degenerate/empty windows. (#1335)
    """
    seconds = max(int((end - start).total_seconds()), 60)
    return -(-seconds // 60) * 60  # ceil-divide by 60, back to seconds


def _window(args) -> tuple[datetime, datetime, str]:
    """Resolve the query window → (start, end, human label). Times are UTC."""
    now = datetime.now(timezone.utc)
    if args.month:
        year, month = (int(x) for x in args.month.split("-"))
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        days_in_month = calendar.monthrange(year, month)[1]
        month_end = start + timedelta(days=days_in_month)
        end = min(now, month_end)
        return start, end, f"{args.month} ({start:%b %Y})"
    if args.days:
        start = now - timedelta(days=args.days)
        return start, now, f"trailing {args.days}d"
    # default: current month-to-date
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now, f"month-to-date ({start:%b %Y})"


def _list_features(cw) -> list[str]:
    """Every LambdaFunction value that has emitted an EstimatedCostUSD metric."""
    features: set[str] = set()
    paginator = cw.get_paginator("list_metrics")
    for page in paginator.paginate(Namespace=NAMESPACE, MetricName=_TOKEN_METRICS["cost"]):
        for m in page.get("Metrics", []):
            for d in m.get("Dimensions", []):
                if d["Name"] == "LambdaFunction":
                    features.add(d["Value"])
    return sorted(features)


def _fetch(cw, features: list[str], start: datetime, end: datetime) -> dict[str, dict]:
    """Sum each (feature, metric) over the window via GetMetricData.

    One query id per (feature, metric); GetMetricData allows 500/call so we page
    in chunks. Sum stat over one wide period bucket = window total.
    """
    period = _metric_period(start, end)
    # id → (feature, metric_key)
    id_map: dict[str, tuple[str, str]] = {}
    queries = []
    for fi, feat in enumerate(features):
        for mkey, mname in _TOKEN_METRICS.items():
            qid = f"q{fi}_{mkey}"
            id_map[qid] = (feat, mkey)
            queries.append(
                {
                    "Id": qid,
                    "MetricStat": {
                        "Metric": {
                            "Namespace": NAMESPACE,
                            "MetricName": mname,
                            "Dimensions": [{"Name": "LambdaFunction", "Value": feat}],
                        },
                        "Period": period,
                        "Stat": "Sum",
                    },
                    "ReturnData": True,
                }
            )

    totals: dict[str, dict] = {f: {k: 0.0 for k in _TOKEN_METRICS} for f in features}
    for i in range(0, len(queries), 450):
        chunk_end = i + 450
        chunk = queries[i:chunk_end]
        paginator = cw.get_paginator("get_metric_data")
        for page in paginator.paginate(
            MetricDataQueries=chunk,
            StartTime=start,
            EndTime=end,
        ):
            for res in page.get("MetricDataResults", []):
                feat, mkey = id_map[res["Id"]]
                totals[feat][mkey] += sum(res.get("Values", []))
    return totals


def _guess_model(tok: dict) -> str:
    """Back-solve the model from token counts + emitted cost.

    Returns a model key from _PRICES, or "mixed" if no single tier reproduces the
    cost within tolerance, or "-" if there is no cost/token signal.
    """
    cost = tok["cost"]
    usage = {
        "input_tokens": tok["in"],
        "output_tokens": tok["out"],
        "cache_read_input_tokens": tok["cache_read"],
        "cache_creation_input_tokens": tok["cache_write"],
    }
    if cost <= 0 or not any(usage.values()):
        return "-"
    best, best_err = None, None
    for model in _PRICES:
        expected = estimate_cost_usd(usage, model)
        if expected <= 0:
            continue
        err = abs(expected - cost) / cost
        if best_err is None or err < best_err:
            best, best_err = model, err
    if best is None or best_err > _MODEL_MATCH_TOL:
        return "mixed"
    return best


def _authoritative_by_model(cw, start: datetime, end: datetime) -> dict[str, dict]:
    """Per-MODEL Bedrock token totals from AWS/Bedrock (the source cost_governor
    trusts) → {model_key: {in, out, cost}}. Reconciliation footer only."""
    period = _metric_period(start, end)
    # discover ModelIds
    model_ids: set[str] = set()
    paginator = cw.get_paginator("list_metrics")
    for page in paginator.paginate(Namespace="AWS/Bedrock", MetricName="InputTokenCount"):
        for m in page.get("Metrics", []):
            for d in m.get("Dimensions", []):
                if d["Name"] == "ModelId":
                    model_ids.add(d["Value"])
    out: dict[str, dict] = {}
    for mid in sorted(model_ids):
        # map raw ModelId → price key
        key = next((k for k in _PRICES if k in mid.lower()), "fable")
        qs = []
        for name in ("InputTokenCount", "OutputTokenCount", "CacheReadInputTokenCount", "CacheWriteInputTokenCount"):
            qs.append(
                {
                    "Id": name.lower().replace("count", ""),
                    "MetricStat": {
                        "Metric": {"Namespace": "AWS/Bedrock", "MetricName": name, "Dimensions": [{"Name": "ModelId", "Value": mid}]},
                        "Period": period,
                        "Stat": "Sum",
                    },
                }
            )
        vals = {}
        for page in cw.get_paginator("get_metric_data").paginate(MetricDataQueries=qs, StartTime=start, EndTime=end):
            for res in page.get("MetricDataResults", []):
                vals[res["Id"]] = vals.get(res["Id"], 0.0) + sum(res.get("Values", []))
        usage = {
            "input_tokens": vals.get("inputtoken", 0.0),
            "output_tokens": vals.get("outputtoken", 0.0),
            "cache_read_input_tokens": vals.get("cachereadinputtoken", 0.0),
            "cache_creation_input_tokens": vals.get("cachewriteinputtoken", 0.0),
        }
        cost = estimate_cost_usd(usage, key)
        agg = out.setdefault(key, {"in": 0.0, "out": 0.0, "cost": 0.0})
        agg["in"] += usage["input_tokens"]
        agg["out"] += usage["output_tokens"]
        agg["cost"] += cost
    return out


def _project(cost: float, start: datetime, end: datetime) -> float:
    """Linear monthly projection from the observed window run-rate.

    Anchored to the START month's length; elapsed is capped at a full month so a
    COMPLETED past month projects to itself (factor 1.0) rather than scaling on the
    next month's day count.
    """
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    elapsed = min(max((end - start).total_seconds() / 86400.0, 0.5), float(days_in_month))
    return cost * (days_in_month / elapsed)


def _fmt_tokens(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:.0f}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Per-feature AI (Bedrock) spend ranking (#808).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--month", help="calendar month YYYY-MM (e.g. 2026-06)")
    g.add_argument("--days", type=int, help="trailing N days")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-authoritative", action="store_true", help="skip the AWS/Bedrock reconciliation footer")
    args = ap.parse_args(argv)

    cw = _cw()
    start, end, label = _window(args)
    features = _list_features(cw)
    totals = _fetch(cw, features, start, end)

    rows = []
    for feat in features:
        tok = totals[feat]
        if tok["cost"] <= 0 and tok["in"] <= 0 and tok["out"] <= 0:
            continue
        rows.append(
            {
                "feature": feat,
                "model": _guess_model(tok),
                "input_tokens": tok["in"],
                "output_tokens": tok["out"],
                "cache_read_tokens": tok["cache_read"],
                "cache_write_tokens": tok["cache_write"],
                "cost_usd": round(tok["cost"], 2),
                "projected_month_usd": round(_project(tok["cost"], start, end), 2),
            }
        )
    rows.sort(key=lambda r: r["cost_usd"], reverse=True)

    # per-model rollup from the back-solved features
    by_model: dict[str, float] = {}
    for r in rows:
        by_model[r["model"]] = by_model.get(r["model"], 0.0) + r["cost_usd"]

    authoritative = {} if args.no_authoritative else _authoritative_by_model(cw, start, end)

    if args.json:
        print(
            json.dumps(
                {
                    "window": label,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "features": rows,
                    "by_model_self_reported": {k: round(v, 2) for k, v in sorted(by_model.items(), key=lambda x: -x[1])},
                    "by_model_authoritative": {k: round(v["cost"], 2) for k, v in authoritative.items()},
                },
                indent=2,
            )
        )
        return 0

    total = sum(r["cost_usd"] for r in rows)
    print(f"\nPer-feature AI spend — {label}   (namespace {NAMESPACE}, self-reported)\n")
    hdr = f"{'#':>2}  {'feature':<32} {'model':<7} {'in':>7} {'out':>7} {'$ actual':>9} {'$ proj':>8}"
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(rows, 1):
        print(
            f"{i:>2}  {r['feature']:<32} {r['model']:<7} "
            f"{_fmt_tokens(r['input_tokens']):>7} {_fmt_tokens(r['output_tokens']):>7} "
            f"{r['cost_usd']:>9.2f} {r['projected_month_usd']:>8.2f}"
        )
    print("-" * len(hdr))
    print(f"{'':>2}  {'TOTAL (self-reported)':<32} {'':<7} {'':>7} {'':>7} {total:>9.2f}\n")

    print("By model (self-reported, back-solved from per-feature cost):")
    for model, c in sorted(by_model.items(), key=lambda x: -x[1]):
        share = (c / total * 100) if total else 0
        print(f"  {model:<8} ${c:>7.2f}  ({share:4.1f}%)")
    if by_model.get("mixed", 0) > 0:
        print(
            "  note: 'mixed' = a Lambda that called >1 model in the window (daily-brief and the\n"
            "        coach pipeline blend a Sonnet narrative pass with Haiku extraction passes), so\n"
            "        its Haiku portion is folded into that one row. The authoritative footer below\n"
            "        gives the true per-model split; exact per-feature-per-model $ would need a Model\n"
            "        dimension on the emit (recurring CloudWatch metric cost — a costed follow-up)."
        )

    if authoritative:
        print("\nAuthoritative per-model (AWS/Bedrock token metrics — the source cost_governor trusts):")
        auth_total = sum(v["cost"] for v in authoritative.values())
        for model, v in sorted(authoritative.items(), key=lambda x: -x[1]["cost"]):
            print(f"  {model:<8} ${v['cost']:>7.2f}   in={_fmt_tokens(v['in'])} out={_fmt_tokens(v['out'])}")
        print(f"  {'TOTAL':<8} ${auth_total:>7.2f}")
        if auth_total > 0:
            covered = total / auth_total * 100
            print(
                f"\nSelf-reported per-feature total (${total:.2f}) covers {covered:.0f}% of the "
                f"authoritative AWS/Bedrock total (${auth_total:.2f}).\n"
                "The gap is calls that don't reach the EMF chokepoint; the ranking (relative shares) is what matters."
            )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
