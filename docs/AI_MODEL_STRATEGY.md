# Life Platform — AI Model Strategy

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-10

This page decides which model each AI job runs on: a frontier Claude model, a cheap Claude model, an open-weight model, a batch job or a cached prefix. It also records how a job moves from one to another. The decision itself is **ADR-161** (`docs/DECISIONS.md`). The work is epic **#4768**. Budget mechanics (ceiling, tiers, governor) stay in `docs/COST_TRACKER.md` and ADR-063/125/133.

## 1. Where the money goes

Cost Explorer, 2026-09-10 → 2026-10-10, measured 2026-10-10:

```bash
aws ce get-cost-and-usage --time-period Start=2026-09-10,End=2026-10-10 --granularity MONTHLY \
  --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE
# Bedrock by usage type: the same, filtered to the two Claude services, grouped by USAGE_TYPE
```

| Line | 30-day $ | Note |
|---|---|---|
| Claude Haiku 4.5 (Bedrock) | 57.40 | Structured and internal tier, CI judges, remediation |
| Claude Sonnet 4.6 (Bedrock) | 59.55 | Reader voice. Includes the Oct 1–2 Story Desk rebuild (~$45 over two days) |
| CloudWatch | 27.09 | Largest non-AI line |
| Secrets Manager | 12.10 | Credential churn, #4641 |
| Everything else | ~10 | |

The same Bedrock spend by usage type:

| Usage type | $ |
|---|---|
| Uncached input | 69.13 (59%) |
| Output | 36.12 |
| Cache write (5 min + 1 h) | 7.86 |
| Cache read | 3.84 |

Two consequences:

- **Sonnet's cache reads were $0.31 against $35.97 of uncached Sonnet input.**
- **Most Haiku `cache_control` markers do nothing.** Their prefixes are under Haiku 4.5's 4,096-token floor (`lambdas/ai/prompt_cache.py`). The daily brief's shared prefix (~784 tokens) is under Sonnet 4.6's 1,024 floor, and #2888 priced that whole prize at about $1/mo (`lambdas/ai/ai_calls.py:228`).

Steady state is about $1.5–3 a day of AI. The governor projected about $140 for October against the $215 ceiling.

## 2. What's on the shelf (us-west-2, checked 2026-10-10)

Commands: `aws bedrock list-inference-profiles --region us-west-2` and `aws bedrock list-foundation-models --region us-west-2`.

Prices are list prices per 1M tokens (input / output). **Unverified (†) until the epic's probes run.** The AWS pricing page did not render for the research, so † figures come from AWS docs fragments and third-party trackers.

| Model | Access | $ in / out | Cache floor | Notes |
|---|---|---|---|---|
| Claude Sonnet 4.6 | `us.` profile | 3.30 / 16.50 (`us.`) | 1,024 | Today's narrative tier |
| Claude Haiku 4.5 | `us.` profile | 1.10 / 5.50 (`us.`) | 4,096 | Today's structured tier |
| **Claude Haiku 5.5** | `us.` / `global.` | 0.10 / 0.50 † | 512 | Model card lists **no structured outputs, no Batch** †. Tokenizer ~30% more tokens † |
| **Claude Sonnet 5.5** | `us.` / `global.` | 2 / 10 † | 512 | |
| gpt-oss-120b | **in-region** | 0.15 / 0.60 † | — | Structured outputs, tools |
| gpt-oss-20b | **in-region** | 0.07 / 0.30 † | — | |
| gpt-oss-safeguard-20b / 120b | **in-region** | † | — | Classifies against a written policy |
| Qwen3-32B | **in-region** | ~0.15 / 0.60 † | — | |
| Nova Micro (not open-weight) | `us.` profile | 0.035 / 0.14 † | 1K | Caches |
| Llama 4 Maverick / Scout | `us.` profile | ~0.24 / 0.97 † | — | No structured outputs |

`global.` Claude profiles are about 10% cheaper than `us.`, but they route requests outside the US. That needs an owner ruling (a row on #4768); this page assumes `us.`.

## 3. The policy

Ask in order. The first yes decides.

1. **Can code compute it?** Then use no model. ADR-104: numbers are computed, and the model only narrates them.
2. **Is it a safety or privacy gate** (the hazard gate, privacy filters, grounded generation)? It is never moved to a cheaper model. A cheaper model may only be **added** as an extra layer, after an eval on `fixtures/safety_eval/`.
3. **Is it reader-facing voice or narrative, or a multi-turn agent?** Use the **narrative tier**: Sonnet. It moves to Sonnet 5.5 only on a swap eval plus the owner's blind read (#4775). Opus and Fable are for dev sessions only, never runtime.
4. **Is it structured** (extract, classify, judge, tag, internal summary)? Use the **workhorse tier**: Haiku 5.5 (#4772). Where a strict schema is required and Haiku 5.5 can't do it, use Haiku 4.5, or gpt-oss-120b if the trial adopts it.
5. **Is it trivial** (liveness ping, one-label classification)? Use the **economy tier**: gpt-oss-20b or Nova Micro, only if the trial adopts one. Otherwise use workhorse.
6. **Overlays, applied after the tier is chosen:**
   - **Cache** when the shared prefix is at or above the running model's floor, it is byte-stable, and there are 2+ calls inside the TTL. This is the #3139 rule. Proof is `AnthropicCacheReadTokens` and `PromptCacheNoOp`, never the presence of a marker (#4778).
   - **Batch** when the job is deferrable and has ≥100 records for one model in one job. That means bulk rebuilds and backfills, not daily crons (#4777). Batch and caching don't combine.
7. **Swaps** are per feature, through the registry (#4770). Each lands only after the swap eval (#4771) shows non-inferior quality with n and an interval, and with every deterministic gate passing (ADR-104/105). A cheaper path skips no gate (ADR-132).

## 4. Open-weight models, honestly

Once the workhorse tier is on Haiku 5.5, it costs about $5 a month. Open-weight models can then save about **$1–3/mo**, so price is not their case. They are trialled (#4776) for four other reasons:

- **In-region processing.** gpt-oss and Qwen3 run in us-west-2 itself; Claude's `us.` profiles route across US regions.
- **Strict JSON**, where Haiku 5.5 lacks it.
- **A second provider** when Claude is throttled or down.
- **Guard classifiers built for the job** (gpt-oss-safeguard), as an extra layer only. This is a row on #4768.

| Model | Trial role |
|---|---|
| gpt-oss-120b | Workhorse challenger and outage fallback: coach quality gate, coach state updater, coherence sentinel |
| gpt-oss-20b | Economy tier |
| Qwen3-32B | Second-family challenger, so a result isn't one vendor's luck |
| Nova Micro | Economy challenger (not open-weight) |

**Not trialled:**

- Llama 4: no structured outputs.
- DeepSeek-R1: priced like a reasoning model and weak at tools.
- Mistral Large 3: costs more than Haiku 5.5.
- Gemma: weak tool use.
- Bedrock Intelligent Prompt Routing: it can't pair these with Claude 5.5.
- Distillation: serving the result is poor value at this volume.

**Kill criterion.** Adopt for a feature only if all of these hold. Otherwise the spike closes not-realized, with its table.

- Quality is non-inferior to Haiku 5.5, with n and an interval.
- Every gate passes.
- It is **either** ≥30% cheaper **or** it delivers a named non-price benefit.

## 5. Architecture

```
caller ──feature key──▶ model_routing (feature → tier → model id, price row)      #4770
                              │
                              ▼
             bedrock_client.invoke()  — the one chokepoint (ADR-062)
   budget tier · dev cap · resolve · ┬─ Anthropic Messages body (Claude)
   usage metrics · PromptCacheNoOp   └─ Converse adapter (non-Anthropic)          #4776
                              │
                 bedrock_batch.run_or_fallback (bulk jobs ≥100 records)           #4777

model_swap_eval: replay frozen inputs → incumbent vs candidate → deterministic gates
                 → blind pairwise judge → win/tie/loss, n, Wilson interval        #4771
```

- **Registry.** It lives in code (`lambdas/ai/model_routing.py`), not `config/`. Feature keys are those of `budget_guard._FEATURE_CUTOFF` and `scripts/ai_budget_ledger.py`. Every routable model has a `PRICES` row, because an unpriced model is metered at the Fable fallback today (`bedrock_client._DEFAULT_PRICE`). A guard fails on a model literal outside it. The first instance of that bug class is #4769.
- **IAM.** It widens only to named model ARNs (`cdk/stacks/role_policies_base.py`), as an ask-first CDK deploy.
- **Proof surface.** The inference receipt (`/api/inference_receipt`, MCP `get_platform_cost`) carries per-feature and per-model dollars. It was failing on 2026-10-10 (#4774).

## 6. Session and SDLC lanes

These costs are on the Claude plan, not AWS, so the governor does not see them.

| Work | Model |
|---|---|
| Mechanical subagents (`issue-filer`, `render-qa`, `story-auditor`) | Sonnet |
| `/review` and `/uplevel` panelists and surveyors | Sonnet |
| Verification (`finding-verifier`) and score steps | Strong model |
| `worktree-implementer` | The issue's `model:*` label |
| Owner conversations (interviews, debriefs, coach sessions) | Frontier, for voice |

This is tracked on #4773.

CI judges run Haiku on Bedrock through OIDC; their cost and cadence are #4652. The remediation agent is #4651.

## 7. Expected effect

These are estimates. Each story's closure carries the measured number.

| Lever | ≈ $/mo |
|---|---|
| Workhorse → Haiku 5.5 (#4772) | −35 to −45 |
| CI judges (#4652) | −15 to −25 |
| Remediation agent (#4651, currently off) | up to −30 |
| Narrative → Sonnet 5.5 (#4775, if ruled yes) | −10 to −15 |
| Batch for bulk rebuilds (#4777) | −50% of each rebuild spike |
| Caching re-decisions (#4778) | small (correctness) |
| Open-weight trial (#4776) | −1 to −3, plus non-price benefits |

Projected month: about $140 → **$70–90**.
