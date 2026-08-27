#!/usr/bin/env python3
"""cache_aware_model_tiering.py — is ADR-049's Haiku-for-structured default inverted
by caching economics? (#3139, epic #2801)

THE CLAIM UNDER TEST
--------------------
#3139: "a Sonnet cache READ ($0.30/M) is 3.3x cheaper than an uncached Haiku input
token ($1.00/M)", so any structured feature with a large stable prefix and a small
per-call payload should be routed to Sonnet-cached instead of Haiku-uncached.

The per-token claim is TRUE and this script verifies it against the live price table
in `ai.bedrock_client._PRICES` rather than a remembered number. What the claim omits
is that a per-token ratio is not a per-RUN cost: on Sonnet the *volatile* input is
3x dearer and the *output* is 3x dearer, and a cache READ only exists if a cache
WRITE for the same byte-identical prefix happened inside the TTL.

THE MODEL (per run, rates per 1M tokens)
----------------------------------------
    P = stable prefix tokens      V = volatile input tokens
    O = output tokens             h = cache hit rate (fraction of runs that READ)

    Haiku, uncached:  C_H = (P + V)*in_H + O*out_H
    Sonnet, cached:   C_S = h*P*read_S + (1-h)*P*write_S + V*in_S + O*out_S

A cache WRITE replaces the input charge for those tokens (it does not add to it),
which is why the miss branch prices P at `write_S` and not `in_S + write_S`.

THE TWO GATES A FEATURE MUST PASS
---------------------------------
1. **The arithmetic gate.** Solving C_S < C_H at the most generous possible
   assumptions — h = 1 (every run reads) and V = 0 (every input token is stable
   prefix) — leaves a necessary condition that depends on nothing but the two
   numbers CloudWatch already records per feature:

       P > (2V + 10O) / 0.70   ->  with V=0:  P > 14.29 * O

   and since P can never exceed total input I, the screen is **I > 14.29 * O**.
   A feature failing this cannot be rescued by ANY prompt restructuring, because
   it already assumes the restructuring succeeded perfectly. That is what makes
   the screen worth running first: it is an upper bound, not an estimate.

2. **The cadence gate.** h is not a free parameter. The default TTL is 5 minutes;
   h > 0 requires a second call on a byte-identical prefix inside that window. For
   a once-daily cron singleton h = 0 by construction, and at h = 0 the Sonnet
   branch prices the prefix at a cache WRITE — $3.75/M against Haiku's $1.00/M,
   i.e. **3.75x worse on the very tokens the swap was supposed to make cheaper**.
   The issue's comparison is read-vs-uncached; the achievable comparison for most
   of this platform's structured features is write-vs-uncached.

INPUTS
------
Per-feature call count, input tokens and output tokens are the trailing-30d
`LifePlatform/AI` CloudWatch sums (`AnthropicInputTokens` / `AnthropicOutputTokens`
by `LambdaFunction`, Sum and SampleCount). Pass `--live` to re-pull them; the
default runs against the 2026-08-27 snapshot embedded below so the verdict is
reproducible without AWS credentials.

Usage:
    python3 scripts/cache_aware_model_tiering.py           # embedded snapshot
    python3 scripts/cache_aware_model_tiering.py --live    # re-pull from CloudWatch
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ai.bedrock_client import _PRICES  # noqa: E402
from ai.prompt_cache import cache_floor  # noqa: E402

# ── The measured corpus ─────────────────────────────────────────────────────
# Trailing 30d to 2026-08-27, `LifePlatform/AI` namespace, us-west-2.
# (feature, calls, input_tokens_total, output_tokens_total)
# Only the STRUCTURED tier is listed — the features ADR-049 Phase 2 routed to
# Haiku, which are the ones #3139 proposes to invert. Narrative Sonnet features
# (daily-brief, wednesday-chronicle, state-of-matthew) are out of scope: they are
# already on Sonnet, so there is nothing to invert.
SNAPSHOT_30D: list[tuple[str, int, int, int]] = [
    ("ai-expert-analyzer", 560, 2_490_295, 310_864),
    ("life-platform-qa-smoke", 506, 2_172_309, 123_015),
    ("coach-quality-gate", 435, 989_264, 287_048),
    ("coach-state-updater", 290, 679_905, 380_829),
    ("coach-daily-reflection", 275, 227_167, 46_942),
    ("life-platform-site-api-ai", 168, 318_727, 22_205),
    ("coach-history-summarizer", 84, 299_354, 120_919),
    ("daily-debrief", 27, 18_945, 9_971),
    ("life-platform-ai-quality-canary", 12, 19_394, 2_976),
    ("field-notes-generate", 6, 4_964, 2_798),
    ("journal-enrichment", 3, 2_944, 1_136),
    ("challenge-generator", 3, 8_293, 4_317),
]

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"


def haiku_cost(prefix: float, volatile: float, output: float) -> float:
    """USD for one uncached Haiku run. Every input token pays full input rate."""
    p = _PRICES["haiku"]
    return ((prefix + volatile) * p["in"] + output * p["out"]) / 1_000_000.0


def sonnet_cost(prefix: float, volatile: float, output: float, hit_rate: float) -> float:
    """USD for one Sonnet run whose stable prefix is cached at `hit_rate`.

    A cache write REPLACES the input charge for the prefix rather than adding to
    it, so the miss branch prices `prefix` at `cache_write` alone.
    """
    p = _PRICES["sonnet"]
    cached = hit_rate * prefix * p["cache_read"] + (1.0 - hit_rate) * prefix * p["cache_write"]
    return (cached + volatile * p["in"] + output * p["out"]) / 1_000_000.0


def prefix_multiple_required(output_per_call: float) -> float:
    """Stable-prefix tokens needed per output token for Sonnet-cached to break even
    against Haiku-uncached, at h=1 and V=0 — the most generous case that exists.

    Derivation: 0.30P + 15O < 1.00P + 5.00O  ->  0.70P > 10O  ->  P > 14.29 * O.
    Written from `_PRICES` rather than hard-coded so a price change moves it.
    """
    h, s = _PRICES["haiku"], _PRICES["sonnet"]
    slack = h["in"] - s["cache_read"]  # what a cached prefix token saves
    penalty = s["out"] - h["out"]  # what an output token costs extra on Sonnet
    return (penalty / slack) * output_per_call


def required_hit_rate(prefix: float, volatile: float, output: float) -> float | None:
    """The cache hit rate at which Sonnet-cached exactly equals Haiku-uncached.

    Returns None when no hit rate in [0, 1] can close the gap — i.e. the swap
    loses even at a perfect 100% hit rate.
    """
    lo, hi = sonnet_cost(prefix, volatile, output, 1.0), haiku_cost(prefix, volatile, output)
    if lo >= hi:
        return None
    at_zero = sonnet_cost(prefix, volatile, output, 0.0)
    if at_zero <= hi:
        return 0.0
    return (at_zero - hi) / (at_zero - lo)


def pull_live() -> list[tuple[str, int, int, int]]:
    """Re-pull the corpus from CloudWatch. Read-only."""
    import boto3

    cw = boto3.client("cloudwatch", region_name="us-west-2")
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=30)
    rows = []
    for name, *_ in SNAPSHOT_30D:
        dims = [{"Name": "LambdaFunction", "Value": name}]
        q = [
            {
                "Id": f"q{i}",
                "MetricStat": {
                    "Metric": {"Namespace": "LifePlatform/AI", "MetricName": m, "Dimensions": dims},
                    "Period": 2592000,
                    "Stat": stat,
                },
            }
            for i, (m, stat) in enumerate(
                [("AnthropicInputTokens", "SampleCount"), ("AnthropicInputTokens", "Sum"), ("AnthropicOutputTokens", "Sum")]
            )
        ]
        res = cw.get_metric_data(MetricDataQueries=q, StartTime=start, EndTime=end)["MetricDataResults"]
        vals = {r["Id"]: (sum(r["Values"]) if r["Values"] else 0) for r in res}
        rows.append((name, int(vals["q0"]), int(vals["q1"]), int(vals["q2"])))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="re-pull the 30d corpus from CloudWatch instead of the embedded snapshot")
    args = ap.parse_args()

    corpus = pull_live() if args.live else SNAPSHOT_30D
    source = "LIVE CloudWatch (trailing 30d)" if args.live else "embedded snapshot (30d to 2026-08-27)"

    h, s = _PRICES["haiku"], _PRICES["sonnet"]
    print(f"Rates per 1M tok (ai.bedrock_client._PRICES) — haiku in ${h['in']:.2f} / out ${h['out']:.2f}")
    print(f"  sonnet in ${s['in']:.2f} / out ${s['out']:.2f} / cache_read ${s['cache_read']:.2f} / cache_write ${s['cache_write']:.2f}")
    print(f"  #3139's headline ratio, verified: sonnet cache_read vs haiku input = {h['in'] / s['cache_read']:.2f}x cheaper")
    print(f"  the ratio it omits: sonnet cache_WRITE vs haiku input = {s['cache_write'] / h['in']:.2f}x DEARER")
    print(f"  cacheable-prefix floors: haiku {cache_floor(HAIKU_MODEL):,} tok · sonnet {cache_floor(SONNET_MODEL):,} tok")
    print(f"\nCorpus: {source}\n")

    hdr = f"{'feature':<34}{'n':>5}{'in/call':>9}{'out/call':>9}{'P needed':>10}{'P avail':>9}{'ratio':>7}  verdict"
    print(hdr)
    print("-" * len(hdr))

    passes = []
    for name, calls, in_tok, out_tok in corpus:
        if not calls:
            continue
        per_in, per_out = in_tok / calls, out_tok / calls
        need = prefix_multiple_required(per_out)
        # P can never exceed total input; assume the entire input is stable prefix.
        avail = per_in
        ratio = avail / need if need else float("inf")
        ok = avail > need
        if ok:
            passes.append(name)
        print(
            f"{name:<34}{calls:>5}{per_in:>9,.0f}{per_out:>9,.0f}{need:>10,.0f}{avail:>9,.0f}"
            f"{ratio:>7.2f}  {'SURVIVES screen' if ok else 'IMPOSSIBLE — no prompt shape wins'}"
        )

    print(
        "\n'P needed' is the stable-prefix tokens required for Sonnet-cached to beat Haiku-uncached at a\n"
        "PERFECT 100% cache hit rate with ZERO volatile input. 'P avail' is total input — the absolute\n"
        "upper bound on any prefix. ratio < 1.00 means the swap loses even if the prompt were rebuilt\n"
        "so that every single input token were a byte-stable, always-hitting cached prefix."
    )

    print(f"\nSurvived the arithmetic screen: {passes or 'NONE'}")
    for name, calls, in_tok, out_tok in corpus:
        if name not in passes:
            continue
        per_in, per_out = in_tok / calls, out_tok / calls
        hr = required_hit_rate(per_in, 0.0, per_out)
        print(f"  {name}: needs h >= {hr:.1%} at P={per_in:,.0f}/V=0 — and P={per_in:,.0f} is only reachable if the prompt is 100% stable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
