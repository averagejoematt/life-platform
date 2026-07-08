#!/usr/bin/env python3
"""
batch_feasibility.py — the live trip-wire for #409 batch-inference pricing (ADR-132).

Batch inference (`CreateModelInvocationJob`) is ~50% of on-demand, but Bedrock
enforces a hard floor of 100 records per job, per model. This script answers the
one question that decides whether batch is worth wiring up: **does any single
model's daily scheduled-content volume reach the 100-record floor?**

It reads the per-producer call counts the platform already emits at the inference
chokepoint (`bedrock_client._emit_usage_metrics` → `LifePlatform/AI`
EstimatedCostUSD SampleCount per LambdaFunction), attributes each producer to a
model by back-solving from emitted cost (same method as
`scripts/ai_spend_attribution.py`), and reports per-model calls/day against the
floor plus the batch savings that WOULD be captured above it.

Verdict at first run (2026-07): total ~62 calls/day across ALL scheduled producers,
mixed across models — no single model reaches 100/day. Batch is infeasible; the
`bedrock_batch.py` seam stays dormant. Re-run this as the RUNBOOK trip-wire: when a
single model's calls/day clears ~120 (headroom over the 100 floor), enable batch by
wiring `bedrock_batch.run_or_fallback()` into that producer (ADR-132 enablement).

Read-only. CloudWatch GetMetricData + ListMetrics only. Never writes.

Usage:
    python3 scripts/batch_feasibility.py            # trailing 30 days
    python3 scripts/batch_feasibility.py --days 7
    python3 scripts/batch_feasibility.py --json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lambdas"))
from bedrock_batch import BATCH_DISCOUNT, MIN_RECORDS_PER_JOB  # noqa: E402
from bedrock_client import _PRICES, estimate_cost_usd  # noqa: E402

NAMESPACE = "LifePlatform/AI"
REGION = os.environ.get("AWS_REGION", "us-west-2")
_MODEL_MATCH_TOL = 0.05

# Interactive / latency-sensitive producers that must NOT batch even if volume
# allowed it (the interactive ask endpoints stay real-time — AC of #409).
_INTERACTIVE = {"life-platform-site-api-ai", "life-platform-canary", "ai-quality-canary", "unknown"}


def _cw():
    import boto3

    return boto3.client("cloudwatch", region_name=REGION)


def _list_features(cw):
    features = set()
    paginator = cw.get_paginator("list_metrics")
    for page in paginator.paginate(Namespace=NAMESPACE, MetricName="EstimatedCostUSD"):
        for m in page.get("Metrics", []):
            for d in m.get("Dimensions", []):
                if d["Name"] == "LambdaFunction":
                    features.add(d["Value"])
    return sorted(features)


def _fetch(cw, features, start, end):
    """Per feature: SampleCount (calls) + Sum (cost) of EstimatedCostUSD, and
    Sum of input/output tokens — enough to back-solve the model."""
    period = max(int((end - start).total_seconds()), 60)
    metrics = {
        "calls": ("EstimatedCostUSD", "SampleCount"),
        "cost": ("EstimatedCostUSD", "Sum"),
        "in": ("AnthropicInputTokens", "Sum"),
        "out": ("AnthropicOutputTokens", "Sum"),
    }
    id_map, queries = {}, []
    for fi, feat in enumerate(features):
        for mkey, (mname, stat) in metrics.items():
            qid = f"q{fi}_{mkey}"
            id_map[qid] = (feat, mkey)
            queries.append(
                {
                    "Id": qid,
                    "MetricStat": {
                        "Metric": {"Namespace": NAMESPACE, "MetricName": mname, "Dimensions": [{"Name": "LambdaFunction", "Value": feat}]},
                        "Period": period,
                        "Stat": stat,
                    },
                    "ReturnData": True,
                }
            )
    out = {f: {"calls": 0.0, "cost": 0.0, "in": 0.0, "out": 0.0} for f in features}
    # ~20 producers × 4 metrics ≈ 80 queries — comfortably under GetMetricData's
    # 500-per-call limit, so no paging needed.
    resp = cw.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)
    for r in resp["MetricDataResults"]:
        feat, mkey = id_map[r["Id"]]
        out[feat][mkey] = sum(r["Values"]) if r["Values"] else 0.0
    return out


def _back_solve_model(row) -> str:
    """The model whose price reproduces the emitted cost from this feature's own
    token counts is the model it used. Mixed → 'mixed'."""
    usage = {"input_tokens": row["in"], "output_tokens": row["out"]}
    best, best_err = "mixed", _MODEL_MATCH_TOL
    for name in _PRICES:
        est = estimate_cost_usd(usage, name)
        if row["cost"] <= 0:
            continue
        err = abs(est - row["cost"]) / row["cost"]
        if err < best_err:
            best, best_err = name, err
    return best


def main():
    ap = argparse.ArgumentParser(description="Batch-inference feasibility trip-wire for #409.")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cw = _cw()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    features = _list_features(cw)
    data = _fetch(cw, features, start, end)

    per_model = {}  # model -> {calls_per_day, cost, producers:[...]}
    scheduled_total = 0.0
    for feat in features:
        row = data[feat]
        if row["calls"] <= 0:
            continue
        interactive = feat in _INTERACTIVE
        model = _back_solve_model(row)
        calls_day = row["calls"] / args.days
        if not interactive:
            scheduled_total += calls_day
            pm = per_model.setdefault(model, {"calls_per_day": 0.0, "cost": 0.0, "producers": []})
            pm["calls_per_day"] += calls_day
            pm["cost"] += row["cost"]
            pm["producers"].append({"name": feat, "calls_per_day": round(calls_day, 2)})

    any_eligible = any(m["calls_per_day"] >= MIN_RECORDS_PER_JOB for m in per_model.values())
    verdict = {
        "window_days": args.days,
        "floor_records_per_job": MIN_RECORDS_PER_JOB,
        "batch_discount": BATCH_DISCOUNT,
        "scheduled_calls_per_day_total": round(scheduled_total, 2),
        "any_single_model_reaches_floor": any_eligible,
        "per_model": {
            k: {
                "calls_per_day": round(v["calls_per_day"], 2),
                "reaches_floor": v["calls_per_day"] >= MIN_RECORDS_PER_JOB,
                "cost_window_usd": round(v["cost"], 2),
                "potential_batch_saving_usd": round(v["cost"] * BATCH_DISCOUNT, 2) if v["calls_per_day"] >= MIN_RECORDS_PER_JOB else 0.0,
                "producers": sorted(v["producers"], key=lambda p: -p["calls_per_day"]),
            }
            for k, v in per_model.items()
        },
        "verdict": (
            "BATCH FEASIBLE — wire run_or_fallback into the qualifying producer(s)"
            if any_eligible
            else f"BATCH INFEASIBLE — no single model reaches the {MIN_RECORDS_PER_JOB}/day floor; seam stays dormant (ADR-132)"
        ),
    }

    if args.json:
        print(json.dumps(verdict, indent=2))
        return

    print(f"Batch-inference feasibility — trailing {args.days}d ({start:%Y-%m-%d} → {end:%Y-%m-%d})")
    print(f"Floor: {MIN_RECORDS_PER_JOB} records/job/model · batch discount: {int(BATCH_DISCOUNT*100)}%\n")
    print(f"{'model (back-solved)':28} {'calls/day':>10} {'≥floor?':>8} {'cost':>8} {'save@batch':>11}")
    for model, v in sorted(verdict["per_model"].items(), key=lambda x: -x[1]["calls_per_day"]):
        cpd, floor, cost, save = v["calls_per_day"], str(v["reaches_floor"]), v["cost_window_usd"], v["potential_batch_saving_usd"]
        print(f"{model:28} {cpd:10.1f} {floor:>8} {cost:8.2f} {save:11.2f}")
    print(f"\nTotal scheduled calls/day (all models, excl. interactive): {verdict['scheduled_calls_per_day_total']}")
    print(f"\n{verdict['verdict']}")


if __name__ == "__main__":
    main()
