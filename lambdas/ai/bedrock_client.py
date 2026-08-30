"""
bedrock_client.py — AWS Bedrock inference primitive for Claude models.

Migrated from the direct Anthropic API on 2026-05-27 (ADR-062). Replaces
urllib POSTs to api.anthropic.com with boto3 bedrock-runtime invoke_model,
so Claude inference bills through the AWS account instead of prepaid
Anthropic credits (no more "credit balance too low" cliff that takes every
AI feature down at once).

Key facts:
  • Auth is IAM — no API key. Lambda roles need bedrock:InvokeModel on the
    inference-profile ARN + the underlying foundation-model ARN.
  • On-demand 4.x Claude models REQUIRE an inference profile (the `us.`
    prefix). Bare `anthropic.claude-*` IDs reject with
    "on-demand throughput isn't supported".
  • The InvokeModel response for Claude is byte-identical to the direct
    Anthropic Messages API (content[], usage{}, stop_reason, …) so all
    downstream parsing is unchanged.
  • Prompt caching is GA on Bedrock for supported Claude models via the
    same cache_control blocks used on the direct API — no beta header.

This module is bundled into every function's deploy package (#781 retired the shared Lambda layer).
"""

import contextlib
import contextvars
import json
import os

import boto3
from botocore.config import Config

# ── Model-name → Bedrock inference-profile ID ──────────────────────────────
# The platform's AI_MODEL / AI_MODEL_HAIKU env vars hold Anthropic-style names
# (e.g. "claude-sonnet-4-6"). Map them to the us-region cross-region inference
# profiles that Bedrock requires for on-demand throughput.
_MODEL_MAP = {
    "claude-fable-5": "us.anthropic.claude-fable-5",
    "claude-opus-4-8": "us.anthropic.claude-opus-4-8",
    "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6",
    "claude-sonnet-4-5-20250929": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-haiku-4-5-20251001": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-7": "us.anthropic.claude-opus-4-7",
    "claude-opus-4-6": "us.anthropic.claude-opus-4-6-v1",
    "claude-3-5-haiku-20241022": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
}

# Fable 5 / Opus 4.7+ removed sampling params (temperature/top_p/top_k → 400);
# Fable additionally rejects an explicit thinking disable. Scrub at this single
# chokepoint so callers (retry_utils, ai_calls) stay model-agnostic.
_ADAPTIVE_SURFACE_MARKERS = ("fable", "opus-4-7", "opus-4-8")

# Fallback if an unmapped model name shows up — Haiku 4.5 (cheapest current).
_DEFAULT_PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-2")

_BEDROCK = None

# ── Cost telemetry (G1) ─────────────────────────────────────────────────────
# ADR-062 makes invoke() the single chokepoint for every Claude call, so it is
# the one correct place to meter token usage + spend. Metering here (rather than
# only in ai_calls / retry_utils, which cover just the daily-brief path) makes
# per-feature AI cost attributable in one CloudWatch query — site-api-ai,
# partner, the podcast, coach reflections, the canary etc. were previously
# invisible — and feeds the daily-spend anomaly alarm (G2). Strictly fail-open:
# a telemetry error must never surface to an AI caller.
_CW_NAMESPACE = "LifePlatform/AI"
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")

# ── Feature attribution outside Lambda (#2888) ──────────────────────────────
# `_LAMBDA_NAME` above is the whole of the per-feature attribution, and outside a
# Lambda container it is the literal string "unknown". Measured 2026-08-27,
# `LifePlatform/AI` trailing 30d: `unknown` is the **largest single row in the
# ranking** — 17.9M input tokens, $33.19, 46% of all self-reported AI spend, more
# than daily-brief and the entire coach pipeline combined. #2888 asks for "the top
# three features by uncached input"; the actual #1 has no name, so the ranking is
# unusable exactly where it matters most, and PR #3138 skipped that row for that
# reason and worked #2 downward.
#
# Every byte of it is the two AI CI gates, both of which run inside ONE process
# (`tests/visual_qa.py --ai-qa --reader-truth`), so `sys.argv[0]` cannot separate
# them either — the split has to come from the code that owns each pass.
#
# The rules, in the same discipline as `caller_class()` below:
#   • The Lambda runtime's own variable ALWAYS wins. Nothing a caller sets can
#     move spend out of the function that actually incurred it, so this cannot be
#     used to hide a Lambda's cost under a gate's name.
#   • Outside Lambda, an ALLOWLISTED label applies. The allowlist is the point:
#     a CloudWatch custom metric is ~$0.30/metric/month and this dimension carries
#     six metric names, so an unbounded label (argv, a free-form string) would add
#     recurring cost to a cost-reduction change. An unrecognised label is ignored.
#   • The residual is still "unknown", deliberately — the historical series stays
#     continuous, and a SHRINKING `unknown` is itself the proof the attribution
#     landed. It is a residual bucket, not an error state.
ATTRIBUTABLE_FEATURES: frozenset = frozenset(
    {
        # tests/visual_ai_qa.py — the Claude-vision judge. Screenshot IMAGE input
        # (up to 1,568 visual tokens per tile, #3067) dominates its bill and is
        # structurally uncacheable: every capture differs on every run.
        "visual-ai-qa",
        # lambdas/operational/reader_truth_qa.py run from CI rather than from the
        # qa-smoke Lambda. In the Lambda this label never applies — the runtime
        # variable wins and the row stays `life-platform-qa-smoke`, so the CI copy
        # and the nightly Lambda copy of the SAME gate stop being summed together.
        "reader-truth-qa",
    }
)

_FEATURE = contextvars.ContextVar("bedrock_feature", default="")


@contextlib.contextmanager
def attributed_to(feature: str):
    """Attribute Bedrock spend inside this block to `feature` (#2888).

    A no-op inside a Lambda container (the runtime's own function name wins) and
    a no-op for any label outside `ATTRIBUTABLE_FEATURES`. Context-local, so two
    passes in one process — which is exactly what `tests/visual_qa.py` runs — are
    attributed separately without either of them touching the ~40 call sites.
    """
    token = _FEATURE.set(feature or "")
    try:
        yield
    finally:
        _FEATURE.reset(token)


def feature_name() -> str:
    """The `LambdaFunction` dimension value for the call being metered.

    Lambda runtime name → allowlisted context label → `"unknown"`. See the block
    comment above for why each step is in that order. Reads the environment live
    (not the module-level `_LAMBDA_NAME` snapshot) so the precedence rule is
    testable without reimporting the module.
    """
    lam = (os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or "").strip()
    if lam:
        return lam
    label = _FEATURE.get()
    return label if label in ATTRIBUTABLE_FEATURES else "unknown"


# ── Caller-class attribution (#2892) ────────────────────────────────────────
# The governor's month-end projection extrapolates a trailing daily rate over the
# days remaining in the month. Before this dimension existed it extrapolated ONE
# undifferentiated AI rate, so a single dev session (08-10: $18.33 against a
# ~$1.9/day steady state) read as a permanent run-rate change — that is what trips
# tiers and what forced the August ceiling window. Splitting spend by the CLASS of
# execution context lets the projection extrapolate only the classes that actually
# recur, while total spend (the real money, the real ceiling) is unchanged.
#
# Exactly FOUR values, fixed — the cardinality is part of the contract (#2837's EMF
# budget). CALLER_CLASSES is the registry both sides read: cost_governor_lambda
# partitions THIS tuple into projected vs. episodic, and its test fails if a fifth
# class appears here without being assigned a side.
CALLER_CLASS_DIMENSION = "CallerClass"
CALLER_CLASS_PROD_CRON = "prod-cron"
CALLER_CLASS_CI = "ci"
CALLER_CLASS_DEV_SESSION = "dev-session"
CALLER_CLASS_REMEDIATION = "remediation"
CALLER_CLASSES = (
    CALLER_CLASS_PROD_CRON,
    CALLER_CLASS_CI,
    CALLER_CLASS_DEV_SESSION,
    CALLER_CLASS_REMEDIATION,
)

# COST-05 legacy: the MCP Lambda sets INVOCATION_CONTEXT=dev (cdk/stacks/mcp_stack.py)
# because its traffic is Matthew debugging interactively, not a cron. That env var is
# still honored, but ONLY as a DE-ESCALATION: it can move spend out of prod-cron and
# into dev-session, never the other way. See caller_class() for why that direction is
# the whole security property.
_SELF_DECLARED_DEV_VALUES = frozenset({"dev", "dev-session", "interactive", "local"})
# GitHub Actions marks its own environment; the remediation agent's workflow is
# `name: Remediation Agent` (.github/workflows/remediation-agent.yml), which GHA
# exports as GITHUB_WORKFLOW (and inside GITHUB_WORKFLOW_REF as the file path).
_REMEDIATION_WORKFLOW_MARKER = "remediation"
# $/1M tokens, keyed by a substring of the resolved model id. An unmapped model
# prices as the most expensive tier so a new/unknown model can never under-report
# spend.
#
# #2883: this table is now the PLATFORM'S ONE price registry, not a mirror.
# `cost_governor_lambda` imports it (as `_PRICES`) instead of hand-maintaining a
# second copy, and `site_api_budget` already imports the governor's name. That
# matters because the governor's numerator (AWS/Bedrock token metrics x price) and
# this module's denominator (estimate_cost_usd -> LifePlatform/AI::EstimatedCostUSD)
# are the two halves of `CostMetricDriftRatio`: if they price the same model
# differently, the ratio measures a TABLE MISMATCH rather than an attribution gap.
# It did — see the `titan` note below.
#
# `cache_write` is the 5-minute-TTL rate (1.25x base input). `cache_write_1h` is the
# one-hour-TTL rate (2x base input) — `prompt_cache.cached_block(ttl="1h")` can ask
# for it, and only this chokepoint can see which TTL was actually billed (the nested
# `usage.cache_creation` breakdown). Without the second rate a 1h write meters at
# 62.5% of what it costs.
PRICES = {
    "fable": {"in": 10.00, "out": 50.00, "cache_read": 1.00, "cache_write": 12.50, "cache_write_1h": 20.00},
    "opus": {"in": 5.00, "out": 25.00, "cache_read": 0.50, "cache_write": 6.25, "cache_write_1h": 10.00},
    "sonnet": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75, "cache_write_1h": 6.00},
    "haiku": {"in": 1.00, "out": 5.00, "cache_read": 0.10, "cache_write": 1.25, "cache_write_1h": 2.00},
    # #1384: Amazon Titan Text Embeddings V2 — input-only, $0.02/1M tokens, no output/
    # cache tiers. Keyed by the "titan" substring of amazon.titan-embed-text-v2:0 so
    # embed_text() spend meters correctly instead of defaulting to the most-expensive tier.
    # #2883: the governor's copy of this table had NO titan row, so its `_price_for`
    # fell through to the fable tier and priced embedding tokens at $10/1M — 500x. That
    # inflated only the drift ratio's NUMERATOR, which is why the ratio read as an
    # attribution gap. Measured 2026-08-30: 576,561 Titan input tokens MTD metered as
    # $5.77 against $0.0115 of real cost.
    "titan": {"in": 0.02, "out": 0.00, "cache_read": 0.00, "cache_write": 0.00, "cache_write_1h": 0.00},
}
# Back-compat alias: ~8 modules/scripts/tests already read `_PRICES` from here.
_PRICES = PRICES
_DEFAULT_PRICE = PRICES["fable"]

# ── Titan-v2 embeddings (semantic recall #1384) ─────────────────────────────
# Amazon Titan is NOT an inference profile: a bare foundation-model id, on-demand,
# no `us.` prefix and not in _MODEL_MAP. 256 dims (Titan v2 supports 256/512/1024)
# is plenty for a small corpus and keeps each stored vector ~1KB; normalize=True so
# cosine reduces to a dot product. Titan does no sampling, so the embedding is
# DETERMINISTIC — the same text always yields the same vector, the property #1384's
# reproducible retrieval relies on.
TITAN_EMBED_MODEL_ID = os.environ.get("TITAN_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
TITAN_EMBED_DIMENSIONS = int(os.environ.get("TITAN_EMBED_DIMENSIONS", "256"))
_CW = None


def _cw():
    """Lazy-init a CloudWatch client for metric emission (separate from the
    bedrock-runtime client; only created if/when telemetry actually runs)."""
    global _CW
    if _CW is None:
        _CW = boto3.client("cloudwatch", region_name=BEDROCK_REGION)
    return _CW


def caller_class(env=None) -> str:
    """Which of CALLER_CLASSES this Bedrock call is running under (#2892).

    Derived from the EXECUTION CONTEXT, never from a caller-supplied argument.
    That is deliberate: with ~40 call sites, a new `caller_class=` parameter would
    (a) need all 40 to adopt it and (b) let any one of them mislabel dev spend as
    prod, which is precisely the number the projection extrapolates. Instead:

      • `AWS_LAMBDA_FUNCTION_NAME` — set by the Lambda runtime itself, not by us —
        means a real Lambda container, i.e. a scheduled/production trigger:
        `prod-cron`. (The absence of this var is also what produces the `unknown`
        LambdaFunction bucket the 2026-08-18 drift audit traced to CI.)
      • No Lambda container + GitHub Actions markers → `ci`, or `remediation` when
        the workflow is the remediation agent's.
      • Anything else — a laptop, an MCP session, a scratch script → `dev-session`.

    The one self-reported input, INVOCATION_CONTEXT, is honored in a single
    direction: it can only move a call OUT of `prod-cron` and into `dev-session`.
    Nothing a caller can set moves spend INTO the class the projection trusts, so
    the classification cannot be gamed to hide a dev spike inside the prod rate —
    the worst a misconfigured Lambda can do is under-project its own recurring cost,
    which shows up immediately in ACTUAL mtd (the tier's binding constraint).

    Pure: reads a mapping (defaults to os.environ) and returns a string. `env` is a
    parameter so this is testable without mutating process state.
    """
    env = os.environ if env is None else env
    if (env.get("AWS_LAMBDA_FUNCTION_NAME") or "").strip():
        declared = (env.get("INVOCATION_CONTEXT") or "").strip().lower()
        if declared in _SELF_DECLARED_DEV_VALUES:
            return CALLER_CLASS_DEV_SESSION
        return CALLER_CLASS_PROD_CRON
    if (env.get("GITHUB_ACTIONS") or "").strip() or (env.get("CI") or "").strip():
        workflow = f"{env.get('GITHUB_WORKFLOW') or ''} {env.get('GITHUB_WORKFLOW_REF') or ''}".lower()
        if _REMEDIATION_WORKFLOW_MARKER in workflow:
            return CALLER_CLASS_REMEDIATION
        return CALLER_CLASS_CI
    return CALLER_CLASS_DEV_SESSION


def _price_for(model_id: str) -> dict:
    mid = (model_id or "").lower()
    for key, price in _PRICES.items():
        if key in mid:
            return price
    return _DEFAULT_PRICE


def cache_write_split(usage: dict) -> tuple[int, int]:
    """(5-minute-TTL tokens, 1-hour-TTL tokens) from a Messages `usage` block (#2883).

    The wire shape — Bedrock returns the Anthropic Messages `usage` object verbatim —
    carries the cache-write total as a flat `cache_creation_input_tokens` AND, when the
    request used an explicit TTL, a nested breakdown:

        "usage": {"input_tokens": 12, "output_tokens": 87,
                  "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 10000,
                  "cache_creation": {"ephemeral_5m_input_tokens": 4000,
                                     "ephemeral_1h_input_tokens": 6000}}

    The flat total is authoritative — it is what was billed — so the 1h leg is CARVED
    OUT of it rather than added to it, and a nested breakdown that disagrees with the
    total can never make this function drop billed tokens. When the flat total is
    absent but the breakdown is present (a shape older clients did not emit), the total
    is derived from the breakdown, which is the same never-under-count direction.

    A response with no nested `cache_creation` — every in-repo caller today, since all
    of them take `cached_block`'s "5m" default — returns `(total, 0)` and prices
    exactly as it did before this function existed.
    """
    total = int(usage.get("cache_creation_input_tokens", 0) or 0)
    detail = usage.get("cache_creation")
    one_hour = 0
    if isinstance(detail, dict):
        one_hour = int(detail.get("ephemeral_1h_input_tokens", 0) or 0)
        if not total:
            total = one_hour + int(detail.get("ephemeral_5m_input_tokens", 0) or 0)
    one_hour = max(0, min(one_hour, total))
    return total - one_hour, one_hour


def estimate_cost_usd(usage: dict, model_id: str) -> float:
    """Estimated USD for one Claude call from its usage dict + resolved model.
    Pure — no I/O — so it is unit-testable without AWS.

    All four billed token legs are priced: uncached input, output, cache READ (a
    ~90% discount on base input) and cache WRITE (a 1.25x premium at 5m TTL, 2x at
    1h). Cache tokens dominate the token volume on a caching workload — 60.9M of the
    account's 111M Bedrock tokens MTD on 2026-08-30 — so an estimate that priced only
    input+output would be a different number, not a rounding error.
    """
    p = _price_for(model_id)
    write_5m, write_1h = cache_write_split(usage)
    return (
        int(usage.get("input_tokens", 0) or 0) * p["in"]
        + int(usage.get("output_tokens", 0) or 0) * p["out"]
        + int(usage.get("cache_read_input_tokens", 0) or 0) * p["cache_read"]
        + write_5m * p["cache_write"]
        + write_1h * p.get("cache_write_1h", p["cache_write"])
    ) / 1_000_000.0


def _emit_usage_metrics(usage: dict, model_id: str) -> None:
    """Meter token usage + estimated spend at the inference chokepoint (G1).

    Emits per-LambdaFunction token metrics (per-feature attribution) plus a
    dimensionless AnthropicOutputTokens (feeds the existing platform-total
    alarm) and EstimatedCostUSD both per-feature and dimensionless (the latter
    feeds the daily-spend anomaly alarm, G2), plus a per-CallerClass copy of
    EstimatedCostUSD (#2892 — the split the cost governor projects on).
    Fully fail-open."""
    md: list = []
    try:
        in_tok = int(usage.get("input_tokens", 0) or 0)
        out_tok = int(usage.get("output_tokens", 0) or 0)
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
        if not (in_tok or out_tok or cache_read or cache_write):
            return
        cost = estimate_cost_usd(usage, model_id)
        fn_dim = [{"Name": "LambdaFunction", "Value": feature_name()}]
        class_dim = [{"Name": CALLER_CLASS_DIMENSION, "Value": caller_class()}]
        md = [
            {"MetricName": "AnthropicInputTokens", "Dimensions": fn_dim, "Value": in_tok, "Unit": "Count"},
            {"MetricName": "AnthropicOutputTokens", "Dimensions": fn_dim, "Value": out_tok, "Unit": "Count"},
            # Dimensionless output-token total — feeds ai-tokens-platform-daily-total.
            {"MetricName": "AnthropicOutputTokens", "Value": out_tok, "Unit": "Count"},
            # Estimated spend: per-feature attribution + a dimensionless aggregate (G2 alarm).
            {"MetricName": "EstimatedCostUSD", "Dimensions": fn_dim, "Value": cost, "Unit": "None"},
            {"MetricName": "EstimatedCostUSD", "Value": cost, "Unit": "None"},
            # #2892: caller-class-tagged spend. ADDITIVE — the dimensionless
            # EstimatedCostUSD above is untouched, so the ai-daily-spend-high alarm and
            # the governor's _self_reported_cost_mtd()/CostMetricDriftRatio math see no
            # discontinuity; this dimension only lets the governor SPLIT that same total
            # into the classes that recur vs. the ones that track a human's session.
            # Supersedes the 2-valued COST-05 `Context` dimension, which had no consumer
            # (no alarm, no dashboard, no script) and self-reported "prod" for every CI
            # run — the exact misattribution #2892 exists to fix.
            {"MetricName": "EstimatedCostUSD", "Dimensions": class_dim, "Value": cost, "Unit": "None"},
        ]
        if cache_read or cache_write:
            md.append({"MetricName": "AnthropicCacheReadTokens", "Dimensions": fn_dim, "Value": cache_read, "Unit": "Count"})
            md.append({"MetricName": "AnthropicCacheWriteTokens", "Dimensions": fn_dim, "Value": cache_write, "Unit": "Count"})
            # #2883: THE DIMENSIONLESS TWINS. CloudWatch does not roll a custom metric
            # up across dimension sets, so the platform-wide self-reported cache-token
            # total was only obtainable by enumerating every LambdaFunction value and
            # summing — which is exactly what three separate hand audits of this issue
            # had to do, and is the #3260 shape (an alarm/consumer reading the bare
            # series sees a series nothing writes). Cache tokens are the largest single
            # component of the drift gap (60.9M native cache-read MTD vs 5.7M
            # self-reported on 2026-08-30), so box 4's reconciliation to Cost Explorer
            # must be ONE query against the same bare series `_self_reported_cost_mtd`
            # already uses for dollars. Two new series, no new dimension cardinality.
            md.append({"MetricName": "AnthropicCacheReadTokens", "Value": cache_read, "Unit": "Count"})
            md.append({"MetricName": "AnthropicCacheWriteTokens", "Value": cache_write, "Unit": "Count"})
        _cw().put_metric_data(Namespace=_CW_NAMESPACE, MetricData=md)
    except Exception as e:  # never break an AI call on telemetry
        # ERROR, not WARN — a fail-open side channel that fails 100% of the time is
        # invisible at WARN (#2974: the visual-qa CI role lacked PutMetricData, so
        # every CI Bedrock call billed but never recorded, undercounting the AI-cost
        # self-metric #2883 measures). Name the namespace + dropped metrics so the
        # loss is greppable/alarmable; still never raise to the AI caller.
        dropped = ", ".join(sorted({m["MetricName"] for m in md})) or "n/a"
        print(
            f"[ERROR] bedrock cost telemetry emit failed (non-fatal, datapoints DROPPED): namespace={_CW_NAMESPACE} metrics=[{dropped}]: {e}"
        )


def first_text(resp: dict) -> str | None:
    """The first text block of a Messages response, or None if there isn't one.

    #2893: `resp["content"][0]["text"]` raises IndexError on an empty `content`
    list — which is exactly the shape a `max_tokens` stop with no emitted text
    returns. Both retry wrappers used to do that destructure INSIDE their retry
    `try`, so a shape error on an already-billed response was caught by the
    generic `except Exception` and re-invoked the model up to 4×. Callers use
    this helper and handle None themselves, outside the retry loop.
    """
    if not isinstance(resp, dict):
        return None
    for block in resp.get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            return block["text"]
    return None


class _BudgetGuardUnavailable(BaseException):
    """Never raised. The `except` target when `budget_guard` cannot be imported.

    Keeps `budget_stop_cls()` fail-open in the same shape `invoke()` already is:
    if the guard is missing there is no tier-3 stop to special-case, so the
    caller's generic retry path must be left exactly as it was.
    """


def budget_stop_cls() -> type[BaseException]:
    """The exception class the tier-3 budget backstop raises (#3084).

    A budget stop is a REFUSAL, not a transport error: `invoke()` raises it
    *before* `invoke_model`, so nothing is billed, and nothing about attempt 2
    would differ. Both retry wrappers (`common/retry_utils`, `ai/ai_transport`)
    except this class ahead of their generic `except Exception` so it returns or
    re-raises immediately — the generic catch used to sleep 5+15+45 = 65s per
    call, which across the daily brief's ~62 AI calls is ~67 minutes of pointless
    backoff against a Lambda timeout, exactly when the platform is already over
    its ceiling, and logged the stop as a transport-shaped WARN that buried the
    real cause.

    Returned as a class rather than imported at either wrapper's module scope for
    the same reason `invoke()` imports the guard lazily: `common/` must not take a
    hard import-time dependency on `ai/`, and a missing guard must degrade to
    "no budget stop exists", never to an ImportError on the AI path.
    """
    try:
        from ai.budget_guard import BudgetExceeded

        return BudgetExceeded
    except ImportError:
        return _BudgetGuardUnavailable


def _note_truncation(parsed: dict, bedrock_body: dict, model_id: str) -> None:
    """Meter responses that stopped at `max_tokens` (#2893). Strictly fail-open.

    A truncated response is billed in full and is then unparseable by every JSON
    caller in the fleet — the #2668 class. Before this, `stop_reason` was read in
    exactly zero places, so the only way to find the class was a hand audit of
    CloudWatch logs. `TruncatedResponses` / `TruncatedCostUSD` make it a standing
    measurement (per-LambdaFunction and platform-wide) instead.

    Deliberately a metric plus a WARN, not an ERROR: a few call sites cap on
    purpose (e.g. the podcast's 5-token yes/no classifier), so a truncation is
    evidence to weigh, not an automatic failure.
    """
    try:
        if (parsed.get("stop_reason") or "") != "max_tokens":
            return
        usage = parsed.get("usage") or {}
        cap = int(bedrock_body.get("max_tokens") or 0)
        out_tok = int(usage.get("output_tokens", 0) or 0)
        cost = estimate_cost_usd(usage, model_id)
        fn_dim = [{"Name": "LambdaFunction", "Value": feature_name()}]
        _cw().put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {"MetricName": "TruncatedResponses", "Dimensions": fn_dim, "Value": 1, "Unit": "Count"},
                {"MetricName": "TruncatedResponses", "Value": 1, "Unit": "Count"},
                {"MetricName": "TruncatedCostUSD", "Dimensions": fn_dim, "Value": cost, "Unit": "None"},
                {"MetricName": "TruncatedCostUSD", "Value": cost, "Unit": "None"},
            ],
        )
        print(
            f"[WARN] bedrock response TRUNCATED at max_tokens={cap} (output_tokens={out_tok}, "
            f"est ${cost:.6f}, model={model_id}) — billed in full; any JSON parse of it will fail (#2893)"
        )
    except Exception as e:  # never break an AI call on telemetry
        print(f"[ERROR] bedrock truncation telemetry emit failed (non-fatal, datapoints DROPPED): {e}")


def _note_cache_noop(parsed: dict, bedrock_body: dict, model_id: str) -> None:
    """Meter requests that ASKED for prompt caching and got none (#2888).

    Strictly fail-open, and deliberately at the same chokepoint as the spend it
    explains.

    A `cache_control` block on a prefix shorter than the model's minimum
    cacheable length is accepted by the API and then silently does nothing —
    no error, no warning, `cache_creation_input_tokens` just stays 0. Nothing
    anywhere read that field back, so the defect had no observable surface at
    all: five features (daily-brief, ai-expert-analyzer, life-platform-qa-smoke,
    coach-quality-gate, coach-state-updater) carried the wrapper and cached
    nothing, indefinitely, while the 2026-05-29 audit's "0% hit rate" finding
    sat in a document rather than in a metric.

    `PromptCacheNoOp` closes that: asked-for-caching AND zero cache tokens is a
    defect with a name, per-LambdaFunction and platform-wide. A request that
    never asked for caching emits nothing (not a defect), and a genuine cache
    MISS on a first call is indistinguishable from a no-op on that one call —
    which is why this is a metric to trend, not an alarm to page on. A feature
    whose series is pinned at its call count has a wrapper that has never once
    engaged; a feature that writes then reads shows up as a decaying series.

    The log line names the shortfall in tokens so the fix is actionable without
    a second investigation: `prompt_cache.cache_floor()` is the documented
    minimum and `cacheable_prefix_text()` is the lower bound on what was
    actually sent.
    """
    try:
        from ai.prompt_cache import cache_floor, cacheable_prefix_text, estimate_tokens, requests_caching

        if not requests_caching(bedrock_body):
            return  # never asked to cache — nothing to report
        usage = parsed.get("usage") or {}
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
        if cache_read or cache_write:
            return  # caching engaged (write on a first call, read thereafter)
        fn_dim = [{"Name": "LambdaFunction", "Value": feature_name()}]
        _cw().put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {"MetricName": "PromptCacheNoOp", "Dimensions": fn_dim, "Value": 1, "Unit": "Count"},
                {"MetricName": "PromptCacheNoOp", "Value": 1, "Unit": "Count"},
            ],
        )
        floor = cache_floor(model_id)
        est = estimate_tokens(cacheable_prefix_text(bedrock_body))
        print(
            f"[WARN] prompt cache NO-OP: request carried cache_control but usage reported 0 cache tokens "
            f"(model={model_id}, cacheable prefix ~{est} tok vs {floor} tok minimum, "
            f"short by ~{max(0, floor - est)}) — the wrapper is billing full-price input (#2888)"
        )
    except Exception as e:  # never break an AI call on telemetry
        print(f"[ERROR] bedrock prompt-cache telemetry emit failed (non-fatal, datapoints DROPPED): {e}")


def _client():
    """Lazy-init bedrock-runtime client. Read timeout generous for long
    Sonnet narrative passes; botocore adaptive retries on throttling."""
    global _BEDROCK
    if _BEDROCK is None:
        _BEDROCK = boto3.client(
            "bedrock-runtime",
            region_name=BEDROCK_REGION,
            config=Config(
                # 60s was too short for long Sonnet narrative passes (4k-token
                # podcast scripts) → intermittent ReadTimeout. 180s gives headroom.
                read_timeout=180,
                connect_timeout=10,
                retries={"max_attempts": 2, "mode": "adaptive"},
            ),
        )
    return _BEDROCK


def resolve_model_id(model_name: str | None) -> str:
    """Map an Anthropic model name to a Bedrock inference-profile ID.

    Pass-through if already a profile id (us.* / global.*) or a full ARN.
    """
    if not model_name:
        return _DEFAULT_PROFILE
    if model_name.startswith(("us.", "global.", "arn:")):
        return model_name
    return _MODEL_MAP.get(model_name, _DEFAULT_PROFILE)


def structured_output_config(schema: dict) -> dict:
    """Build the Anthropic Structured Outputs `output_config` for a JSON `schema`
    (#1385). Bedrock supports Structured Outputs GA via the same wire shape as the
    direct API, so the value is passed straight through by invoke() (it forwards
    every body key except "model"). Callers do:

        body["output_config"] = structured_output_config(MY_SCHEMA)

    to constrain the model's output to `schema` — schema-guaranteed shape instead of
    parse-and-pray. No beta header; no chokepoint change beyond this builder.
    """
    return {"format": {"type": "json_schema", "schema": schema}}


def invoke(body: dict, model_name: str | None = None) -> dict:
    """Invoke a Claude model on Bedrock.

    Args:
        body: an Anthropic Messages dict — {messages, max_tokens, system?}.
              A top-level "model" key (Anthropic-style name) is honored for
              routing if model_name isn't passed, then stripped from the
              Bedrock request body. Any "output_config" (Structured Outputs,
              #1385) or cache_control blocks pass straight through to Bedrock.
        model_name: explicit model name/profile override.

    Returns the parsed JSON response — identical shape to the direct
    Anthropic Messages API (content[], usage{}, role, stop_reason, …).

    Raises botocore.exceptions.ClientError on Bedrock errors (ThrottlingException,
    ModelTimeoutException, ServiceUnavailableException, AccessDeniedException, …)
    — callers handle retry/backoff.
    """
    # COST-05: Shadow mode — exercises the pipeline without model calls (for debugging
    # coach regeneration without burning budget). Set BEDROCK_SHADOW_MODE=1 to enable.
    if os.environ.get("BEDROCK_SHADOW_MODE"):
        return {
            "id": "shadow-stub",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "[SHADOW MODE — Bedrock call suppressed; BEDROCK_SHADOW_MODE=1]"}],
            "model": "shadow",
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    # Budget guardrail (Tier-3 hard stop): the single backstop every AI call
    # routes through. If the monthly ceiling is reached, refuse — callers
    # catch this and degrade (coaches → fallback brief, ai_calls → [AI_UNAVAILABLE]).
    # Fail-open: if budget_guard is unavailable, proceed (never break AI on a blip).
    # #1230: no hardcoded dollar figure here — the ceiling floats ($85 base / $100 surge,
    # ADR-133), so a literal is guaranteed to drift; the tier alone says AI is paused.
    try:
        from ai.budget_guard import BudgetExceeded, current_tier

        if current_tier() >= 3:
            raise BudgetExceeded("AI paused — monthly budget ceiling reached (tier 3). Auto-resumes at month rollover.")
    except ImportError:
        pass

    model_id = resolve_model_id(model_name or body.get("model"))
    bedrock_body = {k: v for k, v in body.items() if k != "model"}
    if any(marker in model_id.lower() for marker in _ADAPTIVE_SURFACE_MARKERS):
        for param in ("temperature", "top_p", "top_k"):
            bedrock_body.pop(param, None)
        if "fable" in model_id.lower() and (bedrock_body.get("thinking") or {}).get("type") == "disabled":
            bedrock_body.pop("thinking", None)
    # Bedrock requires this exact version string for the Anthropic schema.
    bedrock_body["anthropic_version"] = "bedrock-2023-05-31"

    resp = _client().invoke_model(
        modelId=model_id,
        body=json.dumps(bedrock_body),
        contentType="application/json",
        accept="application/json",
    )
    parsed = json.loads(resp["body"].read())
    # G1: meter token usage + estimated spend at the single chokepoint. Fail-open.
    _emit_usage_metrics(parsed.get("usage") or {}, model_id)
    # #2893: meter billed-but-unparseable output at the same chokepoint. Fail-open.
    _note_truncation(parsed, bedrock_body, model_id)
    # #2888: meter cache_control that asked for caching and got none. Fail-open.
    _note_cache_noop(parsed, bedrock_body, model_id)
    return parsed


def _shadow_embedding(text: str, dims: int) -> list:
    """Deterministic pseudo-embedding for BEDROCK_SHADOW_MODE — a unit-length vector
    seeded from a hash of the text, so shadow/dev pipelines (and the backfill's
    no-spend path) produce STABLE vectors without a real Bedrock call. Same text ⇒
    same vector; different text ⇒ (almost surely) different vector."""
    import hashlib
    import math as _math

    vec = []
    for i in range(dims):
        h = hashlib.sha256(f"{text}|{i}".encode("utf-8")).digest()
        # Map the first 4 bytes to a float in [-1, 1].
        n = int.from_bytes(h[:4], "big") / 0xFFFFFFFF
        vec.append(2.0 * n - 1.0)
    norm = _math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def embed_text(text: str, *, dimensions: int | None = None, model_id: str | None = None, normalize: bool = True) -> list:
    """Return a Titan-v2 text embedding (list[float]) — the Bedrock chokepoint's
    embeddings arm (ADR-062: every Bedrock call routes through this module).

    Deterministic by construction (Titan does no sampling). Respects the same
    tier-3 budget backstop as invoke() (fail-open on a missing budget_guard) and
    meters spend through the shared _emit_usage_metrics path (Titan priced via the
    "titan" _PRICES entry). Raises ValueError on empty input; propagates
    botocore ClientError on Bedrock errors so callers own retry/fallback.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("embed_text: empty input text")
    dims = int(dimensions or TITAN_EMBED_DIMENSIONS)
    mid = model_id or TITAN_EMBED_MODEL_ID

    if os.environ.get("BEDROCK_SHADOW_MODE"):
        return _shadow_embedding(text, dims)

    # Budget backstop — the same tier-3 hard stop invoke() enforces. At tier 3 all
    # AI is paused; pausing embeddings too is correct (backfill runs off-peak anyway).
    try:
        from ai.budget_guard import BudgetExceeded, current_tier

        if current_tier() >= 3:
            raise BudgetExceeded("AI paused — monthly budget ceiling reached (tier 3). Auto-resumes at month rollover.")
    except ImportError:
        pass

    body = {"inputText": text, "dimensions": dims, "normalize": bool(normalize)}
    resp = _client().invoke_model(
        modelId=mid,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    parsed = json.loads(resp["body"].read())
    # Titan reports inputTextTokenCount (no output tokens) — meter it fail-open.
    tok = int(parsed.get("inputTextTokenCount", 0) or 0)
    _emit_usage_metrics({"input_tokens": tok, "output_tokens": 0}, mid)
    return parsed.get("embedding") or []
