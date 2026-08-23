# AI cost self-metric drift attribution — 2026-08-18

**Issue:** #2883 (successor to #357, closed-but-unfixed — the ratio moved 3x → 2.44x and stopped)
**Scope:** attribution ONLY, per the issue's first acceptance box. No fix is attempted here;
`CostMetricDriftRatio` is still live and un-alarmed after this doc. See `## Left`.
**Window:** MTD 2026-08-01 → 2026-08-19 (~18 days), one live snapshot — n=1 unless noted.
Numbers are point-in-time CloudWatch/Cost-Explorer reads, not a multi-day average; treat every
figure here as a single sample, not a trend (ADR-105).
**Source telemetry:** `LifePlatform/AI` (self-emitted), `LifePlatform/Budget` (the governor's
own published metrics), `AWS/Bedrock` (AWS-native per-model token metrics), Cost Explorer
(`UnblendedCost`, grouped by SERVICE), `cost-governor` CloudWatch Logs, `scripts/ai_spend_attribution.py`.

---

## Headline finding

**The 2.44x drift is NOT mostly "AI cost is undercounted 59%."** `CostMetricDriftRatio` divides
two metrics that are not the same *scope* of spend, and one side is deliberately padded. Once
those two effects are backed out, the genuine self-report undercount is real but modest —
roughly **1.37x**, not 2.44x — and that residual is itself mostly explained by cache-token
undercounting, not by a stale price table or a chokepoint bypass.

```
CostMetricDriftRatio = AuthoritativeCostMTD / self_reported_mtd
                      = (non_ai + ai_buffered) / self_reported_mtd
                      = 110.81 / 45.32 = 2.445   (live 2026-08-18T17:00 PT; issue's 2.44)
```

`non_ai` is **the entire non-Bedrock AWS bill** (CloudWatch, Secrets Manager, Tax, S3, KMS,
Route 53, Cost-Explorer API — everything Cost Explorer bills that isn't a Bedrock line).
`self_reported_mtd` is **Bedrock-only**, self-emitted by `bedrock_client.py`. The ratio compares
"the whole AWS bill, padded" against "AI spend only, unpadded" — that scope mismatch is the
single largest term in the gap, not a hidden accounting bug in the AI metric.

## Decomposition of the raw $65.49 gap (MTD, 2026-08-18T17:00 PT sample)

Source: `cost-governor` log line at `2026-08-19T00:00:15Z` (`/aws/lambda/life-platform-cost-governor`):

```
Spend: non_ai=$39.62 ai=$71.19 (...) mtd=$110.81 ... self_reported_mtd=$45.32 ...
```

| Component | $ | % of raw gap | What it is | Evidence |
|---|---:|---:|---|---|
| **A — Scope mismatch** | $39.62 | 60.5% | `AuthoritativeCostMTD` = non-AI AWS spend + AI, but `self_reported_mtd` is AI-only. All of `non_ai` inflates the ratio for a reason that has nothing to do with AI-cost attribution. | `cost_governor_lambda.py:761-786` (`_emit_metrics`: `mtd = non_ai + ai`, `drift_ratio = mtd / self_reported_mtd`); reconciles to the cent against `aws ce get-cost-and-usage` grouped by SERVICE excluding "bedrock" ($39.62 exactly, both sides). |
| **B — Deliberate 1.15x safety buffer** | $9.29 | 14.2% | `_ai_cost()` multiplies the native token-metric estimate by `_AI_SAFETY_BUFFER = 1.15` on purpose ("bias the AI estimate high so we degrade early, never overshoot"). `self_reported_mtd` carries no such buffer. Comparing a padded estimate to an unpadded one guarantees ≥1.15x drift forever, by design. | `cost_governor_lambda.py:178` (`_AI_SAFETY_BUFFER = 1.15`) applied only in `_ai_cost()` (governor), never in `bedrock_client.estimate_cost_usd()` (self-reported). $71.19 / 1.15 = $61.90. |
| **C — Residual: genuine self-report undercount** | $16.58 | 25.3% | Native (AWS-billed) AI spend, unbuffered, vs the app's own self-reported AI spend — the only piece that is actually a metric-accuracy problem. | $61.90 (unbuffered native) − $45.32 (self-reported) = $16.58. Independent cross-check via `scripts/ai_spend_attribution.py --days 18` (run ~40min later, different CloudWatch sample): native unbuffered $56.50 vs self-reported $45.24 → residual $11.26, "80% coverage." The two residual estimates ($16.58 vs $11.26) disagree by ~$5 across ~40 minutes — too fast to be real usage growth at the governor's own logged trailing rate (~$3/day ≈ $0.13/hr); treat this as CloudWatch-sampling noise on a single-bucket 31-day query, not a trend. **Residual should be read as ~$11–17, not a precise number.** |
| **Raw gap (unattributed above)** | $65.49 | 100% | A + B + C | $39.62 + $9.29 + $16.58 = $65.49 ✓.  ($110.81 − $45.32 = $65.49.) |

**Reading:** strip A and B and the *real* drift ratio (native unbuffered AI ÷ self-reported AI) is
**$61.90 / $45.32 = 1.366**, or **$56.50 / $45.24 = 1.249** on the second sample — call it **≈1.3–1.4x**,
not 2.44x. That's still a real gap worth closing (box 2's job), but it's a third to a half the size
the headline ratio implies, and none of the fix belongs in the AI-cost estimator itself for the A/B
portion — those need the *ratio definition* fixed (see `## Left`), not the AI metric.

## Hypothesis 1 — unattributed callers: **NOT a cost gap, a caller-tagging gap**

The issue's own evidence cites two "live" oddities in `EstimatedCostUSD`'s dimension sets:
`{'LambdaFunction': 'unknown'}` and a bare `{}` set. Investigated both:

- The bare `{}` set is not an anomaly — it's the **intentional dimensionless total**
  `bedrock_client._emit_usage_metrics()` emits on every call (`EstimatedCostUSD` with no
  dimensions, alongside the per-`LambdaFunction` one). It IS `self_reported_mtd` — the governor
  queries it directly with no `--dimensions` filter (`_self_reported_cost_mtd()`,
  `cost_governor_lambda.py:740-758`). Confirmed by direct reproduction: bare-metric MTD sum =
  **$45.32248702** to 8 decimal places, exactly matching `AuthoritativeCostMTD / drift_ratio`.

- `'unknown'` is **already inside** that $45.32 total — it is not a missing dollar, it's a
  dollar that's counted but not attributed to a caller. Proof: summing every *named*
  `LambdaFunction` dimension (21 of them) gives **$26.73**; adding `unknown` ($18.52) gives
  **$45.247** — matching the bare total ($45.322) to within $0.08 (rounding/timing). So
  `named + unknown == bare`, algebraically, by construction: `_LAMBDA_NAME =
  os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")` and AWS *always* sets that env var
  inside a real Lambda — so `'unknown'` can only come from `bedrock_client.invoke()` running
  **outside** a Lambda container.

  Only one non-Lambda call site was found: `tests/visual_ai_qa.py` imports `ai.bedrock_client`
  and calls `bedrock.invoke(body, model_name=_VISION_MODEL)` directly (line ~176). It's driven
  by `tests/visual_qa.py --ai-qa [--reader-truth]`, which runs: (a) post-deploy on every merge
  touching `site/**` (`ci-cd.yml` `visual-qa` job), (b) daily via cron (`visual-qa.yml`), and
  (c) at PR time on `v4-gate.yml`. None of those run inside a Lambda, so none set
  `AWS_LAMBDA_FUNCTION_NAME` — every dollar they spend on Haiku-vision QA + reader-truth checks
  lands in the `'unknown'` bucket. Given the repo's merge cadence (many PRs/day across the
  worktree fleet), this is plausible as the dominant source of the $18.52, but this was not
  proven 1:1 by correlating individual CloudWatch datapoints to individual CI run timestamps —
  flagged as the leading candidate, not a certainty.

  **This does not move `CostMetricDriftRatio` at all** — fixing caller attribution (e.g.
  stamping `INVOCATION_CONTEXT=ci` or a synthetic Lambda-name when
  `AWS_LAMBDA_FUNCTION_NAME` is absent) would change the per-caller table's shape, not the
  self-reported total, and therefore not the ratio. It's a real, separate, smaller fix that the
  issue's own per-caller table (`daily-brief 46.5%` etc.) needs, independent of #2883's drift
  question.

## Hypothesis 2 — cache-token mispricing: **real, and the largest piece of Component C**

`AnthropicCacheWriteTokens`/`AnthropicCacheReadTokens` in `LifePlatform/AI` really do have only
4 dimension sets (confirmed: `unknown`, `telegram-coach-worker`, `state-of-matthew`,
`coach-narrative-orchestrator`) against 24 for `EstimatedCostUSD`. Comparing self-reported cache
token *volume* to the AWS-native `AWS/Bedrock::CacheWriteInputTokenCount` /
`CacheReadInputTokenCount` metrics for the same MTD window (Sonnet + Haiku, the only models with
material cache use):

| | App-reported (`LifePlatform/AI`) | Native (`AWS/Bedrock`, ground truth) | Coverage |
|---|---:|---:|---:|
| Cache **write** tokens | 763,252 | 3,589,258 | **21.3%** |
| Cache **read** tokens | 6,667,393 | 45,310,861 | **14.7%** |

So the app is capturing roughly a fifth to a seventh of the cache tokens Bedrock actually bills.
**This is not mispricing in the sense of "priced as ordinary input"** — `estimate_cost_usd()`
prices `cache_read_input_tokens` / `cache_creation_input_tokens` from the *same* usage dict at
the correct premium/discount rates (verified: Sonnet cache-write $3.75/M vs $3.00/M base = 1.25x
premium; cache-read $0.30/M = 0.1x discount — both match Anthropic's published 5-minute-cache
pricing exactly). It's under-*counting*: for most calls, the usage dict `bedrock_client.py`
receives back from `invoke_model()` either omits or zeroes the cache fields, so those tokens
contribute $0 to that call's estimated cost — not "wrong price," just silently absent from the
sum.

Dollar impact: native cache spend (unbuffered, correct prices) = **$10.87** MTD (Haiku
$8.09 + Sonnet $2.78 — Haiku dominates because of its far higher cache-read volume). App-reported
cache spend, estimated from the 4 tagged callers' actual token counts under the price range those
callers plausibly use (Sonnet vs Haiku pricing bracket) = **$1.62–$4.86**. Missing cache dollars ≈
**$6–9**, which is the majority of Component C's residual (~$11–17) under either sample. **Cache-
token undercounting is very likely the single largest contributor to the genuine (non-scope,
non-buffer) part of the drift**, though the exact split against Hypothesis 4 below is not fully
resolved — see the residual note.

## Hypothesis 3 — stale `_PRICES` table: **ruled out as a material driver**

Both `lambdas/ai/bedrock_client.py::_PRICES` and `lambdas/operational/cost_governor_lambda.py::_PRICES`
carry identical per-model rates (Sonnet $3/$15/$0.30/$3.75, Haiku $1/$5/$0.10/$1.25, Opus
$5/$25/$0.50/$6.25 — in/out/cache-read/cache-write per 1M tokens). Applying that table to the
**true, AWS-billed token counts** (native `AWS/Bedrock` metrics, unbuffered) reproduces Cost
Explorer's real Bedrock bill within single-digit percent: $61.90 (one sample) or $56.50 (a second
sample ~40 min apart) against Cost Explorer's **$61.21–$61.36** MTD. Both samples land within
~1–9% of ground truth, in *both* directions across the two samples — consistent with the same
CloudWatch single-bucket sampling noise flagged in Component C, not a systematic under- or
over-price. A table that were meaningfully stale (say, missing a recent Sonnet/Haiku price
change) would show a *consistent* directional gap at this scale; it doesn't. **Not the driver of
the 2.44x**, and no evidence of staleness large enough to act on.

## Hypothesis 4 — non-chokepoint Bedrock usage: **the in-repo chokepoint is clean; one plausible out-of-repo contributor, unconfirmed**

Grepped the full repo for every `boto3.client("bedrock-runtime")` construction and every
`invoke_model(` call site. Exactly one production call site exists:
`lambdas/ai/bedrock_client.py::_client()` / `invoke()`. `lambdas/ai/bedrock_batch.py` (the
batch-inference companion, ADR-132) is dormant by its own docstring ("nothing in the codebase
calls this today") — `run_or_fallback()` always takes the real-time fallback branch at current
volume, and `submit_batch()` has zero callers anywhere. **No in-repo path bypasses ADR-062's
chokepoint.**

One plausible **out-of-repo** contributor was not ruled out: CLAUDE.md documents the self-healing
remediation agent (`remediation-agent.yml`, Mon/Wed/Fri) as running "Sonnet 4.6 on Bedrock" via
AWS OIDC, but `remediation/agent.py` constructs no `bedrock-runtime` client and never imports
`ai.bedrock_client` — its Bedrock calls, if any, go through the Claude Code CLI/SDK's own
Bedrock provider inside the GitHub Actions runner. If so, those calls would appear in
`AWS/Bedrock`'s native metrics (already inside the $56–62 "native" figure used above) but in
**no** `LifePlatform/AI` metric at all — not even `unknown`, since `_emit_usage_metrics()` is
never reached. This is directionally consistent with the leftover few dollars in Component C
after cache-token undercounting is subtracted, but it was not independently confirmed this
session (would need the remediation workflow's own run logs / token counts, out of scope for the
time-box). Flagged, not measured.

## What this rules in/out for #2836 (the September base decision)

- The per-caller table in the issue (`daily-brief 46.5%`, etc.) is **not** "accounting for under
  half the spend" in the way it reads — the self-reported total it's built from ($45.32) is
  already ~93–100% coverage of *self-reported* dollars once `unknown` is included (named +
  unknown = bare, to the cent). The real question for #2836 is the ~1.3–1.4x gap between
  self-reported and true Bedrock billing (Component C), not the 2.44x headline.
- The dominant lever for #2836 is **not** "fix the AI estimator" — it's recognizing that
  `AuthoritativeCostMTD` already IS a reasonable (if deliberately padded) whole-bill estimate;
  the September base sizing should use `AuthoritativeCostMTD` / the governor's own MTD +
  projection numbers directly, not attempt to derive a whole-bill figure from the AI-only
  self-reported metric.

## Box 2 resolved (2026-08-18, follow-up PR)

`CostMetricDriftRatio` now compares AI-only to AI-only, unbuffered on both sides:
`(ai / _AI_SAFETY_BUFFER) / self_reported_mtd` instead of `mtd / self_reported_mtd`
(`cost_governor_lambda.py::_emit_metrics`). `AuthoritativeCostMTD` is unchanged — it still
publishes `mtd` (the whole padded bill) for dashboards that want that figure; only the ratio's
denominator/numerator scope moved. On the live sample in this doc (non_ai=$39.62 ai=$71.19
self_reported=$45.32) the published ratio moves from 2.445 to 1.366, matching the "≈1.3–1.4x"
figure above. Pinned by `tests/test_cost_governor.py::test_cost_metric_drift_ratio_compares_ai_only_not_whole_bill_2883`.
The <1.15 sustained-7-day target and the alarm (box 3) are still open — see below.

## Left

Per the brief, this issue's remaining acceptance boxes are explicitly follow-on work, not
attempted here:

- **`CostMetricDriftRatio` < 1.15 sustained over 7 days** — the scope fix (box 2, above) moves
  the ratio from ~2.44x to ~1.3–1.4x but does not by itself reach 1.15x. Closing cache-token
  undercounting (Hypothesis 2) is what closes most of the real remaining gap toward 1.15x. Not
  attempted in the box-2 PR.
- **A drift-ratio alarm** — not added. `CostMetricDriftRatio` is already published
  (`LifePlatform/Budget::CostMetricDriftRatio`, every 8h); wiring a CloudWatch alarm on it is
  small but is box 3's job, and doing it before box 2 (fixing the ratio's scope) would alarm on
  the scope-mismatch artifact, not on a real regression.
- **Per-caller table reconciliation to Cost Explorer** — not attempted. Once caller-attribution
  for the `unknown` bucket (CI-driven `visual_ai_qa`/`reader_truth_qa` calls, Hypothesis 1) and
  cache-token accounting (Hypothesis 2) are both fixed, the per-caller table should reconcile
  much closer to Cost Explorer's Bedrock line on its own — but that's downstream of fixes not
  made here.
- The exact split of Component C's residual between cache-token undercounting and a possible
  out-of-repo remediation-agent contribution (Hypothesis 4) is not resolved to the dollar — see
  the residual note above.

---

## Addendum — 2026-08-22: the residual hasn't closed, one real (small) fix, two hypotheses ruled in/out

**The ratio did not drift toward 1.15 on its own after box 2 landed — it drifted slightly away
from it.** Live `LifePlatform/Budget::CostMetricDriftRatio`, hourly, since box 2 shipped:

```
1.3673  2026-08-19T17:00 PT  (box 2 lands)
1.3663  2026-08-20T09:00 PT
1.3613  2026-08-20T17:00 PT
1.3647  2026-08-21T01:00 PT
1.3778  2026-08-21T09:00 PT
1.3800  2026-08-21T17:00 PT
1.4114  2026-08-22T01:00 PT
1.4140  2026-08-22T09:00 PT
1.4177  2026-08-22T17:00 PT  <- latest
```

Cross-checked against the governor's own log line (`/aws/lambda/life-platform-cost-governor`,
`2026-08-23T00:00:14Z`): `non_ai=$46.84 ai=$80.57 mtd=$127.41 self_reported_mtd=$49.42`.
`ai_unbuffered = 80.57 / 1.15 = 70.06`; `70.06 / 49.42 = 1.4177` — matches the CloudWatch series
exactly. **Residual gap is now $20.64 (up from $16.58 on 08-18)** — growing in dollars roughly in
proportion to total spend (not accelerating), so this reads as a steady ~29–30% self-report miss
rate holding over the observation window, not a one-time event trailing off.

### Hypothesis 2 (cache-token undercounting) — narrowed, not fully resolved

Two follow-up questions from the 08-18 doc, answered this session:

1. **Is there a second Bedrock response source we're not reading (an
   `x-amzn-bedrock-invocation-metrics` header carrying more reliable cache counts than the body's
   `usage` object)?** Checked against botocore's own service model (`bedrock-runtime`
   `2023-09-30/service-2.json`, `InvokeModelResponse` shape) rather than assumed: the modeled
   response has exactly four members — `body`, `contentType`, `performanceConfigLatency`,
   `serviceTier` — **no invocation-metrics header exists on synchronous `InvokeModel`**. That
   header/JSON blob is a real AWS mechanism, but it's an invocation-*logging* artifact (written to
   CloudWatch Logs/S3 when Bedrock model-invocation logging is enabled), not something the
   synchronous API response carries. **Ruled out** — `bedrock_client.py` is already reading the
   only source that exists.
2. **Why do only 4 of ~20 reporting callers ever show cache activity at all?** AWS documents two
   real, non-bug reasons a `cache_control`-marked call still reports zero cache tokens: the cached
   prefix must clear a per-model minimum (documented ~1,024–4,096 tokens depending on model tier),
   and the cache has a TTL (5m default, up to 1h) that a call must land inside to register a read.
   Two of the four opt-outs already in the codebase are exactly this, by design and pre-dated this
   session: `ai_calls.py`'s D-01 note (daily-brief: measured 0 reads / 10K writes, caching
   disabled) and `/api/ask`'s system prompt (per-question archive retrieval + live metrics —
   genuinely unstable content, never eligible for a useful cache regardless of `cache_control`).
   These are legitimate, not defects.

### A third instance of the same waste class, found and fixed: State of Matthew

Audited all 4 callers with real cache activity (`AnthropicCacheWriteTokens`/`ReadTokens` present
in `LifePlatform/AI`) for the D-01 signature — writes with no matching reads — over a trailing 30d
window:

| caller | cache-write tokens | cache-read tokens | verdict |
|---|---:|---:|---|
| `wednesday-chronicle` | 9,646 | 9,646 | reused — keep caching |
| `telegram-coach-worker` | 37,066 | 39,416 | reused — keep caching |
| `coach-narrative-orchestrator` | 875,666 | 1,020,339 | reused — keep caching |
| **`state-of-matthew`** | **24,159** | **0** | **100% wasted — same class as D-01** |

`state-of-matthew` makes exactly ONE Bedrock call per run (its own `narrate()` docstring: "the
platform's ONE weekly call, not two") via `whole_life_context.with_cached_archive()`, which wraps
the archive in a 1-hour `cache_control` block. A write with no possible read inside the same call,
and a next run 7 days later (168h, far past even the 1h TTL), pays the ~2x cache-write premium for
a discount that can never be realized. Fixed in this PR: `with_cached_archive()` gained a
`cache: bool = True` parameter; `state_of_matthew_lambda.py` now passes `cache=False`, dropping the
`cache_control` wrapper (archive content and grounding behavior unchanged) — same fix class as
D-01, independently discovered.

**Honest sizing: this is real but small.** `state-of-matthew`'s entire MTD self-reported cost is
$0.032 (of $49.42 total, 0.06%) — the wasted premium within that is on the order of a few tenths
of a cent per month (24,159 tokens × (1.25−1.00)/1M ≈ $0.006/mo at Haiku's cache-write rate). This
fix does not move the $20.64 residual or the 1.4177 ratio in any way a human would notice on a
CloudWatch graph. It's shipped because it's correct and cheap, not because it closes the issue.

### What's still open

The $20.64 residual is **not attributed to a specific remaining code defect** after this session's
narrowing. What's ruled out now, cumulatively: stale pricing (08-18), chokepoint bypass (08-18), a
missed invocation-metrics header (08-22), and the specific write-without-read waste pattern across
every caller that has any cache activity at all (08-22, one real instance found and fixed). What's
still standing as plausible, unconfirmed: (a) Hypothesis 4 from 08-18 — out-of-repo Bedrock usage
(the self-healing remediation agent's own Claude Code/Bedrock calls, which would appear in
`AWS/Bedrock` native totals but never reach `_emit_usage_metrics()`) — and (b) a new candidate this
session did not check: the many concurrent Claude Code agent worktree sessions this repo runs
routinely (dozens observed via `git worktree list` during this session) may also authenticate to
Bedrock directly rather than through `ai.bedrock_client`, which would be invisible to
`LifePlatform/AI` by the same mechanism as (a) but at potentially much higher volume. Neither (a)
nor (b) is fixable from `lambdas/` — confirming or ruling either in requires the CLI/agent
infrastructure's own usage logs, out of scope for a repo-side PR.

**Acceptance-box status, updated:** `CostMetricDriftRatio` is trending slightly *away* from 1.15
(1.36 → 1.42 over four days), not toward it — the 7-day-sustained box remains open and, on current
trend, is not close. The alarm (box 3) is live and correctly in ALARM on this true condition. Box 4
(per-caller reconciliation) is untouched.
