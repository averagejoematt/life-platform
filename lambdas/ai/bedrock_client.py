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
  • A model NAME that maps to nothing raises UnknownModelError here (#4275);
    it is never silently rewritten to another model.
  • #4776: a NON-Anthropic family (gpt-oss, Qwen3, Nova) is spoken to through the
    Bedrock Converse API from the SAME `invoke()`. The Anthropic Messages body is
    translated on the way out and the reply is translated back into the Messages
    shape, so no caller changes; every guard and meter in `invoke()` stays in the
    path (budget tier, dev-session cap, usage metrics, truncation, cache no-op).
    `converse_family()` / `to_converse_request()` / `from_converse_response()`.

This module is bundled into every function's deploy package (#781 retired the shared Lambda layer).
"""

import contextlib
import contextvars
import json
import os
import random
import sys
import threading
import time

import boto3
from botocore.config import Config

from ai import model_routing  # #4770: a leaf (imports only model_defaults), so no cycle

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
    # ── Claude 5 family (#4275). Every profile id below was read LIVE from
    # `aws bedrock list-inference-profiles --region us-west-2` on 2026-09-26: all four
    # are ACTIVE, SYSTEM_DEFINED, and exist in both the `us.` and `global.` variants.
    # Resolvable-and-priced is not selected: no surface moves off its current model
    # here — that flip is #4278 (gate:owner) and happens through AI_MODEL, not this map.
    "claude-fable-5-1": "us.anthropic.claude-fable-5-1",
    "claude-opus-5": "us.anthropic.claude-opus-5",
    "claude-opus-5-5": "us.anthropic.claude-opus-5-5",
    "claude-sonnet-5": "us.anthropic.claude-sonnet-5",
    # ── Claude 5.5 Haiku / Sonnet (#4770). Profile ids read LIVE from
    # `aws bedrock list-inference-profiles --region us-west-2` on 2026-10-10: both ACTIVE, in
    # `us.` and `global.`. Resolvable-and-priced is not selected: no route in
    # `ai/model_routing.py` points at either — the workhorse move is #4772 and the narrative
    # move #4775, each behind the #4771 swap eval. Whether either rejects sampling params or
    # an explicit thinking-disable (the two marker tuples below) is unprobed: "sonnet-5"
    # already scrubs sampling for Sonnet 5.5; Haiku 5.5 matches neither tuple. #4772/#4775
    # probe that before any traffic moves.
    "claude-haiku-5-5": "us.anthropic.claude-haiku-5-5",
    "claude-sonnet-5-5": "us.anthropic.claude-sonnet-5-5",
    # ── #4776 open-weight trial: the four Converse-family candidates. Ids read LIVE on
    # 2026-10-11 from `aws bedrock list-foundation-models --region us-west-2` (gpt-oss-120b,
    # gpt-oss-20b and qwen3-32b: ON_DEMAND, ACTIVE, in-region — no inference profile) and
    # `list-inference-profiles` (Nova Micro is INFERENCE_PROFILE-only: `us.` profile, ACTIVE,
    # SYSTEM_DEFINED, fanning out across us-east-1/us-east-2/us-west-2). Resolvable-and-priced is
    # not routed: no `ai/model_routing.py` row points at any of them — adoption is the #4776 kill
    # criterion (non-inferior with n and an interval, every gate, >=30% cheaper OR a named
    # non-price benefit) against the Haiku 5.5 baseline, which waits on #4772's model access.
    # gpt-oss-safeguard-20b/120b exist (ON_DEMAND) but carry no published price in the issue,
    # so they are NOT mapped: a mapped model must price on its own row (#2883's rule).
    "gpt-oss-120b": "openai.gpt-oss-120b-1:0",
    "gpt-oss-20b": "openai.gpt-oss-20b-1:0",
    "qwen3-32b": "qwen.qwen3-32b-v1:0",
    "nova-micro": "us.amazon.nova-micro-v1:0",
}

# ── #4776: the non-Anthropic families, spoken to through the Bedrock Converse API ─────
# Keyed by the model-id prefix AFTER any `us.`/`global.` region prefix. Anything not listed
# here — every Claude profile, Titan — takes the Anthropic Messages / InvokeModel path exactly
# as before. A family row is a TRANSPORT fact, not a route: `ai/model_routing.py` still decides
# which feature runs on what.
CONVERSE_FAMILIES = {
    "openai.gpt-oss": "gpt-oss",
    "qwen.": "qwen",
    "amazon.nova": "nova",
}
_REGION_PREFIXES = ("us.", "global.", "eu.", "apac.")
# The Converse-family ids `resolve_model_id` passes through unchanged: exactly the mapped
# ones, so an unmapped sibling (`openai.gpt-oss-safeguard-20b`) or a profile-only model's
# bare id (`amazon.nova-micro-v1:0`) is an UnknownModelError, never a quiet pass-through.
_CONVERSE_MAPPED_IDS = frozenset(v for v in _MODEL_MAP.values() if v.removeprefix("us.").startswith(tuple(CONVERSE_FAMILIES)))

# Fable 5 / Opus 4.7+ removed sampling params (temperature/top_p/top_k → 400), and so
# did the whole Claude 5 line: Sonnet 5, Opus 5 and Opus 5.5 all reject them (#4275).
# Scrub at this single chokepoint so callers (retry_utils, ai_calls, the ~40 helpers
# that still pass `temperature=0.2`) stay model-agnostic. "opus-5" also covers
# "opus-5-5"; neither matches "opus-4-5-…", and "sonnet-5" does not match "sonnet-4-5-…".
_ADAPTIVE_SURFACE_MARKERS = ("fable", "opus-4-7", "opus-4-8", "opus-5", "sonnet-5")

# An explicit `thinking: {type: "disabled"}` is a 400 on Fable (5 and 5.1) and on Opus 5.5
# at every effort level. Opus 5 accepts it at effort high or below and Sonnet 5 accepts
# it outright, so those two are deliberately NOT here — the body passes through.
_THINKING_DISABLE_REJECTED_MARKERS = ("fable", "opus-5-5")

# Used ONLY when no model is named at all (None / ""), i.e. a caller that built a raw
# body without a "model" key. It is NOT a fallback for an unrecognised NAME: since
# #4275 an unmapped name raises UnknownModelError at the chokepoint — the old
# `.get(name, _DEFAULT_PROFILE)` quietly rewrote `AI_MODEL=claude-sonnet-5` (or any
# typo) into Haiku 4.5 on every narrative surface, with no error anywhere.
_DEFAULT_PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


class UnknownModelError(ValueError):
    """A model NAME that maps to no Bedrock inference profile (#4275).

    Raised by `resolve_model_id` — before `invoke_model`, so nothing is billed — in
    place of the silent Haiku fallback that used to run here. The message names the
    input and every name that would have resolved, so the misconfiguration reads as
    one in the log rather than as a brief that quietly got worse. Both retry wrappers
    (`common/retry_utils`, `ai/ai_transport`) except this class ahead of their generic
    handler: a name that is wrong on attempt 1 is wrong on attempt 4, so it never
    enters the 5+15+45s backoff ladder (#3084's rule for the budget stop, same reason).
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        known = ", ".join(sorted(_MODEL_MAP))
        super().__init__(
            f"unknown AI model name {model_name!r}: not a Bedrock profile id (us./global./arn:), not a mapped "
            f"Converse-family foundation-model id [{', '.join(sorted(_CONVERSE_MAPPED_IDS))}] "
            f"and not one of the {len(_MODEL_MAP)} mapped names [{known}] — refusing to guess a model (#4275)"
        )


BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-2")

_BEDROCK = None

# #3419: board_ask invokes this module from worker THREADS (parallel persona
# pass). boto3 client CREATION is not thread-safe (calls on a built client
# are), so the two lazy inits below take this lock. Single-threaded callers
# pay one uncontended acquire on first use — nothing else changes.
_CLIENT_INIT_LOCK = threading.Lock()

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
# (`qa/visual_qa.py --ai-qa --reader-truth`), so `sys.argv[0]` cannot separate
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
#   • #4589: a call that is neither in Lambda nor labelled, made from a WORKSTATION
#     (`caller_class()` == dev-session), is booked to the one fixed label
#     `DEV_SESSION_FEATURE` instead of the residual. Measured 2026-10-01..03: 30.65 USD
#     of self-metered spend sat in `unknown` — 68% of all AI spend those three days —
#     and every dollar of it was dev-session (two Story Desk season rebuilds and a fix
#     run, all Sonnet 4.6, hours 19–21Z Oct 1 and 01–03Z Oct 2). The CallerClass
#     dimension already knew it was a workstation; the per-feature ranking and the
#     receipt did not, so the largest row read as "no name". One fixed value, not a
#     free-form label: the cardinality bound above is unchanged in kind (+1 value).
#     CI keeps the `unknown` residual — its two gates are labelled by `attributed_to`.
ATTRIBUTABLE_FEATURES: frozenset = frozenset(
    {
        # qa/visual_ai_qa.py — the Claude-vision judge. Screenshot IMAGE input
        # (up to 1,568 visual tokens per tile, #3067) dominates its bill and is
        # structurally uncacheable: every capture differs on every run.
        "visual-ai-qa",
        # lambdas/operational/reader_truth_qa.py run from CI rather than from the
        # qa-smoke Lambda. In the Lambda this label never applies — the runtime
        # variable wins and the row stays `life-platform-qa-smoke`, so the CI copy
        # and the nightly Lambda copy of the SAME gate stop being summed together.
        "reader-truth-qa",
        # qa/comprehension_qa.py (#4182, M4) — the newcomer-comprehension judge:
        # a blind reader + a text-only grader over the six flagship doors. Advisory
        # (never gates the deploy), so its spend is metered separately from the two
        # deploy-gating judges above rather than falling into the "unknown" residual.
        "comprehension_qa",
        # scripts/fresh_eyes_discovery.py (#823) — the weekly Sunday 15:00Z
        # `Fresh-Eyes Discovery` workflow: one Haiku vision read per door screenshot
        # plus one Sonnet board synthesis. #5136: the ONLY caller still landing in
        # `unknown` after #4589 — 9 calls / ~$0.08 a run, at 10-04 16:25Z, 10-11 15:15Z
        # and 10-18 15:10Z, the minutes of its three October runs.
        "fresh-eyes-discovery",
    }
)

# #4589: the per-feature label every unlabelled WORKSTATION call carries (see the bullet above).
DEV_SESSION_FEATURE = "dev-session"
# The residual: a call outside Lambda, carrying no allowlisted label, from a non-workstation
# context (CI or the remediation agent). Kept under its historic name (series continuity), but
# since #5136 it is never SILENT — `_note_unattributed()` prints who reached the meter unnamed.
UNATTRIBUTED_FEATURE = "unknown"

_FEATURE = contextvars.ContextVar("bedrock_feature", default="")


@contextlib.contextmanager
def attributed_to(feature: str):
    """Attribute Bedrock spend inside this block to `feature` (#2888).

    A no-op inside a Lambda container (the runtime's own function name wins) and
    a no-op for any label outside `ATTRIBUTABLE_FEATURES`. Context-local, so two
    passes in one process — which is exactly what `qa/visual_qa.py` runs — are
    attributed separately without either of them touching the ~40 call sites.
    """
    token = _FEATURE.set(feature or "")
    try:
        yield
    finally:
        _FEATURE.reset(token)


def feature_name() -> str:
    """The `LambdaFunction` dimension value for the call being metered.

    Lambda runtime name → allowlisted context label → `"dev-session"` for an unlabelled
    workstation call (#4589) → `"unknown"`. See the block comment above for why each
    step is in that order. Reads the environment live (not the module-level
    `_LAMBDA_NAME` snapshot) so the precedence rule is testable without reimporting
    the module.
    """
    lam = (os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or "").strip()
    if lam:
        return lam
    label = _FEATURE.get()
    if label in ATTRIBUTABLE_FEATURES:
        return label
    return DEV_SESSION_FEATURE if caller_class() == CALLER_CLASS_DEV_SESSION else UNATTRIBUTED_FEATURE


def _note_unattributed(feature: str, cost_usd: float, env=None) -> str | None:
    """Make an unnamed call LOUD at the moment it is metered (#5136). Returns the line printed.

    The residual bucket exists on purpose (series continuity), but nothing told anyone a
    caller had landed in it: #5136 found $35.52 of October's receipt in `unknown` two weeks
    after the fact, by reading a monthly total. The spend is still metered under the residual
    — dropping or guessing it would break ADR-104 — but the run that incurred it now prints
    the caller class, the GitHub workflow and the entrypoint, so a CI log names the caller
    the same day and the fix is one `attributed_to()` + one `ATTRIBUTABLE_FEATURES` entry.

    No new metric: a dimension value per offender is the unbounded cardinality the allowlist
    exists to prevent. Pure apart from the print; `env` is injectable for tests.
    """
    if feature != UNATTRIBUTED_FEATURE:
        return None
    env = os.environ if env is None else env
    workflow = (env.get("GITHUB_WORKFLOW") or "").strip() or "-"
    entry = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else "-"
    line = (
        f"[WARN] UNATTRIBUTED Bedrock spend ${cost_usd:.4f} booked to LambdaFunction={UNATTRIBUTED_FEATURE}: "
        f"caller_class={caller_class(env)} workflow={workflow!r} entrypoint={entry!r}. Wrap the caller in "
        "bedrock_client.attributed_to(<label>) and add the label to ATTRIBUTABLE_FEATURES (#5136)."
    )
    try:
        print(line, file=sys.stderr)
    except Exception:  # noqa: BLE001 — a broken stderr must never cost the datapoint itself
        pass
    return line


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
# $/1M tokens, keyed by a substring of the resolved model id. Matching is LONGEST KEY
# FIRST (`price_key_for`), so a specific row ("sonnet-5") beats its family row
# ("sonnet"); the dict is ALSO ordered specific-before-generic so the first-match
# consumers that iterate it in insertion order (`web/site_api_budget._price_for_model`,
# `scripts/ai_spend_attribution.py`, `scripts/batch_feasibility.py`) land on the same row
# — `tests/test_bedrock_client.py` holds the two orderings equal for every mapped model.
# An unmapped model prices as the most expensive tier so a new/unknown model can never
# under-report spend.
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
#
# #4275: every rate here is the Anthropic LIST price, which is what this table has always
# carried (ADR-062: "Bedrock Claude pricing ≈ direct API"). Two facts a reader should
# hold: (a) the AWS Pricing API (`aws pricing get-products --service-code AmazonBedrock`,
# regionCode=us-west-2, 1,052 rows on 2026-09-26) lists only Claude 2.x / 3 / Instant —
# the current models are Marketplace-billed and absent from it, so the list price is the
# best VERIFIABLE number; (b) Anthropic's pricing page states that on Bedrock the
# REGIONAL `us.` profiles this platform invokes carry a 10% premium over `global.` for
# 4.5+ models, which no row here includes — the governor's `_AI_SAFETY_BUFFER` (1.15) is
# what covers it, and re-pricing the rows the platform runs on today would move the
# month-end projection, which is a ceiling decision (ADR-133), not a model-map fix.
# `PRICE_PROVENANCE` records the source and the date each row was last read against it.
PRICES = {
    # ── Claude 5 family (#4275): explicit rows BEFORE the family rows they would
    # otherwise fall into. Sonnet 5 would have metered at Sonnet 4.6's $3/$15 (1.5x its
    # real $2/$10 — the introductory price Anthropic made permanent); Fable 5.1 and
    # Opus 5.5 carry cache-read rates (0.025x / 0.05x base) the family rows (0.1x) cannot
    # express, so a caching Fable 5.1 workload metered on the "fable" row would over-count
    # its reads 4x.
    "fable-5-1": {"in": 10.00, "out": 50.00, "cache_read": 0.25, "cache_write": 12.50, "cache_write_1h": 20.00},
    "opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00, "cache_write_1h": 8.00},
    "opus-5": {"in": 5.00, "out": 25.00, "cache_read": 0.50, "cache_write": 6.25, "cache_write_1h": 10.00},
    # #4770: Claude 5.5 Haiku / Sonnet, ahead of "sonnet-5" and the family rows they would
    # otherwise fall into ("haiku" would meter Haiku 5.5 at 10x). Rates UNVERIFIED — see
    # PRICE_PROVENANCE; cache legs at the standard 0.1x / 1.25x / 2x of input.
    "haiku-5-5": {"in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125, "cache_write_1h": 0.20},
    "sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50, "cache_write_1h": 4.00},
    "sonnet-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50, "cache_write_1h": 4.00},
    # ── Family rows: Fable 5 · Opus 4.5–4.8 · Sonnet 4.5/4.6 · Haiku 4.5.
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
    # #4776: the four Converse-family trial candidates. Keys are substrings of the live ids
    # (`openai.gpt-oss-120b-1:0`, `openai.gpt-oss-20b-1:0`, `qwen.qwen3-32b-v1:0`,
    # `us.amazon.nova-micro-v1:0`) and collide with no Claude row, so first-match and
    # longest-match agree. Cache legs are 0 on purpose: the Converse adapter translates no
    # `cachePoint`, so no cache token can be billed through it; re-read Nova's cache rates
    # before translating one. Rates UNVERIFIED (see PRICE_PROVENANCE) — none is routed today.
    "gpt-oss-120b": {"in": 0.15, "out": 0.60, "cache_read": 0.00, "cache_write": 0.00, "cache_write_1h": 0.00},
    "gpt-oss-20b": {"in": 0.07, "out": 0.30, "cache_read": 0.00, "cache_write": 0.00, "cache_write_1h": 0.00},
    "qwen3-32b": {"in": 0.15, "out": 0.60, "cache_read": 0.00, "cache_write": 0.00, "cache_write_1h": 0.00},
    "nova-micro": {"in": 0.035, "out": 0.14, "cache_read": 0.00, "cache_write": 0.00, "cache_write_1h": 0.00},
}
# Back-compat alias: ~8 modules/scripts/tests already read `_PRICES` from here.
_PRICES = PRICES
_DEFAULT_PRICE = PRICES["fable"]

# ── Where each price row came from, and when it was last read there (#4275) ─────
# Not consumed by any pricing path — `PRICES` rows stay pure {leg: rate} dicts because
# ~8 consumers index them by leg. This is the audit trail the rows lacked: a row with no
# source is a remembered number, and remembered numbers are how Titan was metered at
# 500x (#2883). `tests/test_bedrock_client.py` asserts every PRICES key has an entry.
_ANTHROPIC_PRICING_DOC = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICE_PROVENANCE = {
    "fable-5-1": {"source": _ANTHROPIC_PRICING_DOC, "verified_on": "2026-09-26", "note": "cache read 0.025x base (page footnote 1)"},
    "opus-5-5": {"source": _ANTHROPIC_PRICING_DOC, "verified_on": "2026-09-26", "note": "cache read 0.05x base (page footnote 2)"},
    "opus-5": {"source": _ANTHROPIC_PRICING_DOC, "verified_on": "2026-09-26", "note": "same rates as the Opus 4.5-4.8 family row"},
    "haiku-5-5": {
        "source": "https://aws.amazon.com/bedrock/pricing/",
        "verified_on": "2026-10-10",
        "note": "UNVERIFIED (#4770): $0.10/$0.50 from the #4768 research (docs/AI_MODEL_STRATEGY.md, marked †: the AWS "
        "page did not render, figures from AWS doc fragments + trackers); cache legs assumed at 0.1x/1.25x/2x. Re-read "
        "before #4772 routes spend here. No route uses it today, so no metered dollar depends on it yet",
    },
    "sonnet-5-5": {
        "source": "https://aws.amazon.com/bedrock/pricing/",
        "verified_on": "2026-10-10",
        "note": "UNVERIFIED (#4770): $2/$10 from the #4768 research (†, as haiku-5-5); cache legs assumed at "
        "0.1x/1.25x/2x. Re-read before #4775. No route uses it today",
    },
    "sonnet-5": {
        "source": _ANTHROPIC_PRICING_DOC,
        "verified_on": "2026-09-26",
        "note": "introductory $2/$10 made the standard price (page footnote 3); the scheduled 2026-09-01 rise to $3/$15 did not occur",
    },
    "fable": {"source": _ANTHROPIC_PRICING_DOC, "verified_on": "2026-09-26", "note": "Fable 5"},
    "opus": {
        "source": _ANTHROPIC_PRICING_DOC,
        "verified_on": "2026-09-26",
        "note": "Opus 4.5-4.8. Opus 4.1 and earlier list at $15/$75 and are not in _MODEL_MAP",
    },
    "sonnet": {"source": _ANTHROPIC_PRICING_DOC, "verified_on": "2026-09-26", "note": "Sonnet 4.5 / 4.6"},
    "haiku": {
        "source": _ANTHROPIC_PRICING_DOC,
        "verified_on": "2026-09-26",
        "note": "Haiku 4.5. Haiku 3.5 (claude-3-5-haiku-20241022, still in _MODEL_MAP) lists at $0.80/$4 and is OVER-metered by this row — the conservative direction",
    },
    "titan": {
        "source": "https://aws.amazon.com/bedrock/pricing/ — Amazon Titan Text Embeddings V2",
        "verified_on": "2026-08-30",
        "note": "#1384/#2883: input-only $0.02/1M, measured against real cost 2026-08-30",
    },
    # #4776: every row below is UNVERIFIED (†) — the figures come from the issue's own table and
    # docs/AI_MODEL_STRATEGY.md §2 (the AWS pricing page did not render for that research; AWS doc
    # fragments + trackers). Nothing is routed to them, so no metered dollar depends on them yet;
    # re-read against the AWS page before the first real eval call and again before any adoption.
    "gpt-oss-120b": {
        "source": "https://aws.amazon.com/bedrock/pricing/",
        "verified_on": "2026-10-11",
        "note": "UNVERIFIED (#4776): $0.15/$0.60 in-region, no cache tier translated. Against haiku-5-5 ($0.10/$0.50) this is "
        "DEARER, so adoption needs a named non-price benefit (in-region, strict JSON, second provider)",
    },
    "gpt-oss-20b": {
        "source": "https://aws.amazon.com/bedrock/pricing/",
        "verified_on": "2026-10-11",
        "note": "UNVERIFIED (#4776): $0.07/$0.30 in-region — 30% / 40% under haiku-5-5, on the price arm of the kill criterion",
    },
    "qwen3-32b": {
        "source": "https://aws.amazon.com/bedrock/pricing/",
        "verified_on": "2026-10-11",
        "note": "UNVERIFIED (#4776): ~$0.15/$0.60 in-region (the issue's own '~'); dearer than haiku-5-5, non-price benefit required",
    },
    "nova-micro": {
        "source": "https://aws.amazon.com/bedrock/pricing/",
        "verified_on": "2026-10-11",
        "note": "UNVERIFIED (#4776): $0.035/$0.14 via the us. profile — 65% / 72% under haiku-5-5. Nova caches natively; the "
        "adapter translates no cachePoint, so its cache rates are deliberately not carried (0)",
    },
}

# ── Titan-v2 embeddings (semantic recall #1384) ─────────────────────────────
# Amazon Titan is NOT an inference profile: a bare foundation-model id, on-demand,
# no `us.` prefix and not in _MODEL_MAP. 256 dims (Titan v2 supports 256/512/1024)
# is plenty for a small corpus and keeps each stored vector ~1KB; normalize=True so
# cosine reduces to a dot product. Titan does no sampling, so the embedding is
# DETERMINISTIC — the same text always yields the same vector, the property #1384's
# reproducible retrieval relies on.
TITAN_EMBED_MODEL_ID = model_routing.model_for("semantic_recall.embed")  # #4770: embed tier, env TITAN_EMBED_MODEL_ID
TITAN_EMBED_DIMENSIONS = int(os.environ.get("TITAN_EMBED_DIMENSIONS", "256"))
_CW = None


def _cw():
    """Lazy-init a CloudWatch client for metric emission (separate from the
    bedrock-runtime client; only created if/when telemetry actually runs)."""
    global _CW
    if _CW is None:
        with _CLIENT_INIT_LOCK:  # #3419: creation-locked — see the lock's comment
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

    #5135: `dev-session` is therefore every workstation call (laptop, agent lane, script)
    PLUS a Lambda container that declares a dev context (today only the MCP Lambda). Which
    of those the dev-session cap refuses and which it only counts toward the $60-a-month
    envelope is written in `ai/dev_session_cap.py` (COVERAGE) — keep the two in step.

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


def price_key_for(model_id: str) -> str | None:
    """The `PRICES` key that prices `model_id`, or None when no key matches (#4275).

    Longest key first — the same discipline as `prompt_cache.cache_floor` — so
    `us.anthropic.claude-sonnet-5` lands on "sonnet-5", not "sonnet", and
    `…-opus-5-5` on "opus-5-5", not "opus-5" or "opus". Exposed (not underscored) so a
    test can ask WHICH row priced a model rather than only what number came back.
    """
    mid = (model_id or "").lower()
    for key in sorted(_PRICES, key=len, reverse=True):
        if key in mid:
            return key
    return None


def _price_for(model_id: str) -> dict:
    key = price_key_for(model_id)
    return _PRICES[key] if key is not None else _DEFAULT_PRICE


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


def _emit_usage_metrics(usage: dict, model_id: str, cost_scale: float = 1.0) -> None:
    """Meter token usage + estimated spend at the inference chokepoint (G1).

    `cost_scale` prices the same tokens at a different rate — a Bedrock batch record
    (#4777, ADR-132) bills the identical token counts at `bedrock_batch.BATCH_DISCOUNT`
    off, so it is metered at 0.5x rather than at the on-demand price.

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
        cost = estimate_cost_usd(usage, model_id) * float(cost_scale)
        feature = feature_name()
        _note_unattributed(feature, cost)
        fn_dim = [{"Name": "LambdaFunction", "Value": feature}]
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


def _dev_cap_check() -> None:
    """#4589: refuse a laptop dev-session call that has reached its spend cap. A missing
    module degrades to "no cap", the same shape as the tier-3 stop; the refusal itself
    (a BudgetExceeded) propagates."""
    try:
        from ai import dev_session_cap
    except ImportError:
        return
    dev_session_cap.check(caller_class(), _cw)


def _dev_cap_record(usage: dict, model_id: str) -> None:
    """#4589: add one billed call's estimated cost to this run's tally. Fail-open."""
    try:
        from ai import dev_session_cap

        dev_session_cap.record(caller_class(), estimate_cost_usd(usage, model_id))
    except Exception:  # noqa: BLE001 — never break a call that already succeeded
        pass


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
    if _BEDROCK is not None:
        return _BEDROCK
    with _CLIENT_INIT_LOCK:  # #3419: creation-locked — see the lock's comment
        if _BEDROCK is None:
            _BEDROCK = boto3.client(
                "bedrock-runtime",
                region_name=BEDROCK_REGION,
                config=Config(
                    # 60s was too short for long Sonnet narrative passes (4k-token
                    # podcast scripts) → intermittent ReadTimeout. 180s gives headroom.
                    read_timeout=180,
                    connect_timeout=10,
                    # #4279: botocore retries OFF. `invoke_with_retry` below is the ONE
                    # retry policy. The old `{"max_attempts": 2, "mode": "adaptive"}`
                    # was NOT two attempts: botocore reads client-config `max_attempts`
                    # as RETRIES and adds one (`total_max_attempts = 3`), and the three
                    # app-level loops each ran 4 on top — 12 invoke_model sends per call
                    # worst case. `total_max_attempts` is the unambiguous key.
                    retries={"total_max_attempts": 1, "mode": "standard"},
                ),
            )
    return _BEDROCK


def resolve_model_id(model_name: str | None) -> str:
    """Map an Anthropic model name to a Bedrock inference-profile ID.

    Pass-through if already a profile id (us.* / global.*), a full ARN, or one of the
    Converse-family foundation-model ids `_MODEL_MAP` names (#4776 — the exact id, not
    the family prefix). No name at all (None / "") is the one case that takes
    `_DEFAULT_PROFILE`. A NAME that maps to nothing raises `UnknownModelError` (#4275)
    — it used to return `_DEFAULT_PROFILE` too, which turned `AI_MODEL=claude-sonnet-5`
    into a silent Haiku 4.5 downgrade of every narrative surface. Absent is not
    unknown; unknown fails loudly.
    """
    if not model_name:
        return _DEFAULT_PROFILE
    if model_name.startswith(("us.", "global.", "arn:")):
        return model_name
    if model_name in _CONVERSE_MAPPED_IDS:
        # #4776: a bare in-region foundation-model id of a Converse family (`openai.gpt-oss-120b-1:0`)
        # takes no inference profile, so like a `us.` id it is already the thing Bedrock wants — but
        # ONLY the ids `_MODEL_MAP` names. A family prefix alone passed `openai.gpt-oss-safeguard-20b`
        # (unmapped, unpriced: it would have metered at the Fable default) and a bare
        # `amazon.nova-micro-v1:0` (reachable only through its `us.` profile). #4275's rule — refuse
        # to guess — holds for the Converse families too: a mapped model prices on its own row.
        return model_name
    try:
        return _MODEL_MAP[model_name]
    except KeyError:
        raise UnknownModelError(model_name) from None


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


# ── #4776: the Converse adapter ────────────────────────────────────────────────────────
# Bedrock's Converse API is the one request shape every non-Anthropic family on Bedrock
# speaks (the InvokeModel bodies differ per vendor). The translation is PURE in both
# directions so it is unit-testable with no AWS, and it is deliberately narrow: what the
# platform's ~40 callers actually send (text system + text messages, max_tokens,
# temperature/top_p, stop_sequences, a JSON-schema output_config, cache_control markers) is
# translated; anything else raises `ConverseUnsupported` BEFORE a send rather than being
# dropped on the floor — a silently dropped tool list or image would return confident garbage.
#
# What is translated how, and why:
#   • system / messages text blocks → Converse `{"text": …}` blocks. `cache_control` markers are
#     DROPPED (not translated to `cachePoint`): none of the four trial families is known to honour
#     one through Converse, and `_note_cache_noop` below then reports the no-op honestly.
#   • output_config.format json_schema → the schema is rendered into a trailing system block as an
#     instruction ("schema_via": "instruction"). Converse has no Anthropic `output_config`, and a
#     wire-level constraint (a forced tool, or a vendor `response_format`) is per-family and
#     unprobed; the reply is still parsed and checked against the schema by `structured_json`
#     and the swap eval's schema gate, so a model that cannot hold the shape is MEASURED, not hidden.
#   • max_tokens / temperature / top_p / stop_sequences → inferenceConfig. top_k, thinking,
#     metadata and anthropic_version have no Converse equivalent and are dropped (recorded in
#     the reply's `_converse.dropped`).
#   • stopReason → stop_reason (same vocabulary for end_turn / max_tokens / stop_sequence /
#     tool_use; anything else passes through verbatim so a new reason is visible, not masked).
#   • usage.inputTokens/outputTokens(/cacheRead/cacheWrite) → the Messages `usage` keys, so
#     `estimate_cost_usd`, the dev-session cap and every CloudWatch meter read it unchanged.
_CONVERSE_TRANSLATED_KEYS = frozenset({"messages", "system", "max_tokens", "temperature", "top_p", "stop_sequences", "output_config"})
_CONVERSE_DROPPED_KEYS = frozenset({"top_k", "thinking", "metadata", "anthropic_version"})
_CONVERSE_STOP_REASONS = {"end_turn": "end_turn", "max_tokens": "max_tokens", "stop_sequence": "stop_sequence", "tool_use": "tool_use"}
CONVERSE_SCHEMA_INSTRUCTION = (
    "Respond with ONLY a single JSON object that conforms to this JSON Schema — no prose before or after it, " "no code fence:\n"
)


class ConverseUnsupported(ValueError):
    """A Messages-body feature the Converse adapter does not translate (#4776).

    Raised by `to_converse_request` — before any send, so nothing is billed — for an image,
    document, tool_use or tool_result block, a `tools`/`tool_choice`/`stream` key, or an
    output_config that is not a json_schema. A REFUSAL, not a transport failure: attempt 2
    would carry the same body, so every retry loop excepts this class ahead of its generic
    handler — `invoke_with_retry` (the one loop, in its `refusals` tuple), both
    `common/retry_utils` wrappers (re-raise) and `ai/ai_transport.call_anthropic` (the
    outage sentinel, failure metric fired). Being a ValueError is NOT what makes it a
    refusal: the generic `except Exception` in each loop would retry a bare ValueError
    three times with ~20 s of backoff — the verifier reproduced exactly that before the
    class was named in each loop (#4776).
    """


def converse_family(model_id: str | None) -> str | None:
    """The CONVERSE_FAMILIES name for `model_id`, or None for the Anthropic / InvokeModel path.

    Accepts a bare id, a `us.`/`global.` profile id or a full ARN (the resource's leaf is read).
    """
    m = (model_id or "").strip().lower().split("/")[-1]
    for prefix in _REGION_PREFIXES:
        if m.startswith(prefix):
            m = m[len(prefix) :]
            break
    for prefix, family in CONVERSE_FAMILIES.items():
        if m.startswith(prefix):
            return family
    return None


def _converse_text_blocks(content, where: str, dropped: set) -> list:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"text": content}]
    blocks = []
    for block in content:
        if not isinstance(block, dict):
            raise ConverseUnsupported(f"{where}: a non-dict content block is not translated by the Converse adapter (#4776)")
        kind = block.get("type", "text")
        if kind != "text":
            raise ConverseUnsupported(f"{where}: a {kind!r} block is not translated by the Converse adapter (#4776)")
        if block.get("cache_control"):
            dropped.add("cache_control")
        blocks.append({"text": str(block.get("text") or "")})
    return blocks


def to_converse_request(body: dict, model_id: str) -> tuple[dict, dict]:
    """Translate an Anthropic Messages `body` (no "model" key) into `converse()` kwargs.

    Returns `(request, note)`: the kwargs for `bedrock-runtime.converse`, and the adapter's
    record of what it did (`family`, `schema_via`, `dropped`) which rides the reply as
    `_converse`. Pure — no I/O. Raises `ConverseUnsupported` on anything it will not translate.
    """
    family = converse_family(model_id)
    if family is None:
        raise ConverseUnsupported(f"{model_id!r} is not a Converse-family model id (#4776)")
    unknown = sorted(k for k in body if k not in _CONVERSE_TRANSLATED_KEYS and k not in _CONVERSE_DROPPED_KEYS)
    if unknown:
        raise ConverseUnsupported(f"Messages key(s) {unknown} are not translated by the Converse adapter (#4776)")
    dropped: set = {k for k in _CONVERSE_DROPPED_KEYS if k in body}
    system_blocks = _converse_text_blocks(body.get("system"), "system", dropped)
    messages = []
    for i, m in enumerate(body.get("messages") or []):
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            raise ConverseUnsupported(f"messages[{i}]: role must be user or assistant for the Converse adapter (#4776)")
        messages.append({"role": m["role"], "content": _converse_text_blocks(m.get("content"), f"messages[{i}]", dropped)})
    schema_via = None
    if body.get("output_config") is not None:
        fmt = (body.get("output_config") or {}).get("format") or {}
        if fmt.get("type") != "json_schema" or fmt.get("schema") is None:
            raise ConverseUnsupported("output_config: only a json_schema format is translated by the Converse adapter (#4776)")
        system_blocks.append({"text": CONVERSE_SCHEMA_INSTRUCTION + json.dumps(fmt["schema"], sort_keys=True)})
        schema_via = "instruction"
    inference: dict = {}
    if body.get("max_tokens") is not None:
        inference["maxTokens"] = int(body["max_tokens"])
    if body.get("temperature") is not None:
        inference["temperature"] = float(body["temperature"])
    if body.get("top_p") is not None:
        inference["topP"] = float(body["top_p"])
    if body.get("stop_sequences"):
        inference["stopSequences"] = [str(s) for s in body["stop_sequences"]]
    request: dict = {"modelId": model_id, "messages": messages}
    if system_blocks:
        request["system"] = system_blocks
    if inference:
        request["inferenceConfig"] = inference
    return request, {"family": family, "schema_via": schema_via, "dropped": sorted(dropped)}


def from_converse_response(resp: dict, model_id: str, note: dict | None = None) -> dict:
    """Translate a `converse()` reply into the Anthropic Messages response shape.

    Only `text` content blocks are carried (gpt-oss's `reasoningContent` is not text a caller
    can use and is not billed as output here — it is counted in `outputTokens`, which IS carried).
    Pure — no I/O.
    """
    message = ((resp or {}).get("output") or {}).get("message") or {}
    content = [
        {"type": "text", "text": block["text"]}
        for block in message.get("content") or []
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]
    u = (resp or {}).get("usage") or {}
    usage = {"input_tokens": int(u.get("inputTokens") or 0), "output_tokens": int(u.get("outputTokens") or 0)}
    if u.get("cacheReadInputTokens"):
        usage["cache_read_input_tokens"] = int(u["cacheReadInputTokens"])
    if u.get("cacheWriteInputTokens"):
        usage["cache_creation_input_tokens"] = int(u["cacheWriteInputTokens"])
    stop = (resp or {}).get("stopReason")
    return {
        "id": ((resp or {}).get("ResponseMetadata") or {}).get("RequestId") or "converse",
        "type": "message",
        "role": message.get("role") or "assistant",
        "content": content,
        "model": model_id,
        "stop_reason": _CONVERSE_STOP_REASONS.get(stop, stop),
        "stop_sequence": None,
        "usage": usage,
        "_converse": dict(note or {"family": converse_family(model_id)}),
    }


def invoke(body: dict, model_name: str | None = None) -> dict:
    """Invoke a Claude model on Bedrock — or, for a Converse family (#4776), the same call
    translated through the Converse API; the caller sees one shape either way.

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
    ModelTimeoutException, ServiceUnavailableException, AccessDeniedException, …).
    ONE attempt, no retry (botocore retries are off, #4279) — a caller that wants the
    platform's retry policy calls `invoke_with_retry`, never a loop of its own.
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
    # #4589: a laptop dev session is capped per run and per trailing day. Never applies
    # inside a Lambda container, in CI or to the scheduled platform.
    _dev_cap_check()

    model_id = resolve_model_id(model_name or body.get("model"))
    bedrock_body = {k: v for k, v in body.items() if k != "model"}
    lowered = model_id.lower()
    if any(marker in lowered for marker in _ADAPTIVE_SURFACE_MARKERS):
        for param in ("temperature", "top_p", "top_k"):
            bedrock_body.pop(param, None)
    if any(marker in lowered for marker in _THINKING_DISABLE_REJECTED_MARKERS):
        if (bedrock_body.get("thinking") or {}).get("type") == "disabled":
            bedrock_body.pop("thinking", None)
    if converse_family(model_id) is not None:
        # #4776: a non-Anthropic family — translate out, send through Converse, translate back.
        # Every guard above already ran; every meter below runs on the translated reply.
        request, note = to_converse_request(bedrock_body, model_id)
        parsed = from_converse_response(_client().converse(**request), model_id, note)
    else:
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
    _dev_cap_record(parsed.get("usage") or {}, model_id)
    # #2893: meter billed-but-unparseable output at the same chokepoint. Fail-open.
    _note_truncation(parsed, bedrock_body, model_id)
    # #2888: meter cache_control that asked for caching and got none. Fail-open.
    _note_cache_noop(parsed, bedrock_body, model_id)
    return parsed


# ── #4279 — the ONE retry policy for every Bedrock Messages call ─────────────
#
# Before: botocore retried each send (config `max_attempts: 2` = 3 sends — see
# `_client`) AND three app-level loops (`ai_transport.call_anthropic`,
# `retry_utils.call_anthropic_api`, `retry_utils.call_anthropic_raw`) each made 4
# attempts with fixed 5/15/45 s sleeps around that: 4 x 3 = 12 invoke_model sends
# and >= 65 s of sleep per call on a sustained throttle, before a single 180 s read
# timeout is counted. The helpers that looked like more copies (the digests'
# `call_anthropic_with_retry`, the `_call_haiku` family) already delegated to
# `call_anthropic_raw` — they carry no loop of their own.
#
# After: botocore sends once; THIS loop is the only retry. App-level rather than
# botocore-level because (a) the budget stop and the unknown-model refusal are
# raised before invoke_model and must never be retried — botocore cannot see them,
# (b) the retryable set is Bedrock-specific (ModelNotReady / ModelTimeout are not in
# botocore's generic transient list), and (c) every attempt passes through
# `invoke()`'s metering, so a retried call is visible, not folded into one send.
INVOKE_MAX_ATTEMPTS = 3
INVOKE_RETRY_BASE_DELAYS = (5, 15)  # seconds before attempt 2, attempt 3 (equal jitter)
RETRYABLE_BEDROCK_CODES = frozenset(
    {
        "ThrottlingException",
        "ModelTimeoutException",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelNotReadyException",
    }
)
_jitter = random.random  # patched by tests for a deterministic schedule


def retry_delay(attempt: int) -> float:
    """Seconds to wait after failed `attempt` (1-based): equal jitter on the base —
    half fixed, half random — so concurrent Lambdas throttled together do not
    retry in lock-step, and the worst case stays bounded by the base."""
    base = float(INVOKE_RETRY_BASE_DELAYS[attempt - 1])
    return base / 2 + _jitter() * base / 2


def invoke_with_retry(body: dict, model_name: str | None = None) -> dict:
    """`invoke()` under the platform's single retry policy (#4279).

    Worst case: INVOKE_MAX_ATTEMPTS sends and sum(INVOKE_RETRY_BASE_DELAYS) = 20 s of
    sleep. Never retried: the tier-3 budget stop (#3084), UnknownModelError (#4275)
    and ConverseUnsupported (#4776) — all three refusals raised before any send,
    nothing billed, and attempt 2 would be identical — and a non-retryable
    ClientError (validation, access).
    A non-ClientError exception (connection reset, read timeout) is retried: the
    send did not return, so nothing was received to re-bill (#2893's rule).
    The final failure is re-raised unchanged; callers own the degrade path.
    """
    import botocore.exceptions as _bce

    refusals = (budget_stop_cls(), UnknownModelError, ConverseUnsupported)
    for attempt in range(1, INVOKE_MAX_ATTEMPTS + 1):
        try:
            # Looked up at call time, so a monkeypatched `bedrock_client.invoke` is what runs.
            return invoke(body, model_name=model_name)
        except refusals:
            raise
        except _bce.ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            print(f"[WARN] Bedrock {code} attempt {attempt}/{INVOKE_MAX_ATTEMPTS}")
            if code not in RETRYABLE_BEDROCK_CODES or attempt >= INVOKE_MAX_ATTEMPTS:
                raise
        except Exception as e:
            print(f"[WARN] Bedrock error attempt {attempt}/{INVOKE_MAX_ATTEMPTS}: {e}")
            if attempt >= INVOKE_MAX_ATTEMPTS:
                raise
        delay = retry_delay(attempt)
        print(f"[INFO] Retrying in {delay:.1f}s...")
        time.sleep(delay)
    raise AssertionError("unreachable: the loop returns or raises on its last attempt")


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
    _dev_cap_check()  # #4589

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
    _dev_cap_record({"input_tokens": tok, "output_tokens": 0}, mid)
    return parsed.get("embedding") or []
