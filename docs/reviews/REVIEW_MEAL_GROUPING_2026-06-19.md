# Review — Meal Grouping (Derived Meal Layer)

> **Destination in repo:** `docs/reviews/REVIEW_MEAL_GROUPING_2026-06-19.md`
> **Date:** 2026-06-19
> **Status:** Approved to build — 11 approve / 0 reject / 1 conditional (Viktor). Conditions folded into spec v1.1.
> **Boards convened:** Technical (Architecture Review · Intelligence & Data · Productization). Product Board lane = Part B of the spec (future nutrition page), not re-reviewed here.
> **Related:** `docs/SPEC_MEAL_GROUPING_2026-06-19.md` (v1.1), `docs/specs/CLAUDE_CODE_PROMPT_MEAL_GROUPING_v1.md`, `docs/BOARDS.md`.

---

## 1. Use case & requirements

Group raw MacroFactor food entries into the realistic meals they were eaten as, as a **derived projection** over an untouched raw log, for meal-level analytics now and a public meal view later. Matthew has approved LLM use for naming novel meals, with a hard cost-effectiveness requirement. The board reviewed architecture **and** costing.

## 2. Proposed approach (the spine — endorsed)

- **Raw is sovereign; meals are a derived, recomputable projection** (`SOURCE#macrofactor_meals`) referencing raw entries by pointer. Three invariants: raw untouched · inferred+labelled · conservation-of-food (`sum(meal rollups) == raw totals`).
- **Deterministic-first grouping** — canonical-token normalization → segment (meal-bucket if present, else time-gap) → content-split (anchor-sets, orphan→side) → template-centroid match → snack bucket. Zero LLM on the hot path.
- **LLM is a cost-bounded naming fallback** — Haiku, residual-only, signature-cached, promote-to-template, frozen-as-data, correctable, never read-path.

## 3. Technical Board

### Architecture Review (Priya, Marcus, Yael, Jin, Elena, Omar)
- **Priya Nakamura** — The deterministic grouper is the system of record; the MEAL# projection is a downstream, replayable artifact stamped with `algo_version`. Correct shape: facts are computed and reproducible, the model only decorates. Endorse.
- **Omar Khalil** — `macrofactor_meals` as a distinct derived source (not folded into `computed_metrics`) is right for clean provenance + freshness tracking. Two new first-class objects need a home: the **canonical food vocabulary** (`config/food_vocabulary.json`) and the **name cache** (`NAMECACHE#<signature>`). The no-write-to-`macrofactor` test is the load-bearing guard — make it un-skippable.
- **Marcus Webb** — Namer is its own small Lambda; own Secrets Manager secret if it calls the Anthropic API directly (bundling principle: same creds + same Lambda set only). Backfill is a Batch-API submit/poll job, not a synchronous loop.
- **Jin Park** — Idempotent upsert by stable ordinal; backfill resumable; **the namer must be rate-limited and the spend guardrail must fail *safe*** — on cap breach it returns "Mixed meal", never errors, never overspends. A half-run backfill must not double-name.
- **Elena Reyes** — Encapsulate the model call in one module so the eventual Anthropic-API → Bedrock swap touches one file. Same discipline as the Hevy compiler.
- **Yael Cohen** — Low surface area: the namer reads a food list and writes a string; no write-capable external tool, no inbound webhook. Main risk is cost-exfiltration via runaway calls — the cap + alarm covers it. Treat the food list as the only input; no free-text passthrough to the model.

### Intelligence & Data (Anika, Henning, Omar, Elena)
- **Dr. Anika Patel** — Deterministic-first is correct; Haiku is the right tier for a naming/classification task (never Sonnet/Opus here). Constrained JSON, self-scored confidence, output frozen and correctable. The signature cache + promote-to-template is what makes this an *intelligence* feature rather than a per-day model dependency: spend decays to zero as the library learns. Endorse.
- **Dr. Henning Brandt** *(hard constraint, satisfied)* — A grouped meal is an inference and a generated name is a label, not a fact. Non-negotiable: **"most-eaten" and every analytic aggregate keys on the deterministic `signature`/`template_id`, never on the display name** — so a flaky or re-generated name can never corrupt a count. Confidence on every record; n-floor before any public surface; correlative framing only. Spec §6/§8 already encode this. Approve with that constraint held.
- **Omar Khalil** — Reconciliation test (conservation-of-food) belongs in CI, run over the whole backfill, not just fixtures. If any day fails to reconcile, the backfill halts.

### Productization (Raj S, Sarah C, Viktor, Dana, Priya)
- **Raj Srinivasan** — The wedge is the meal view + level-up loop; the namer is a cosmetic enabler. Risk to watch: the LLM becomes the project. It shouldn't — it's ~30 lines behind a cache. Keep the energy on templates + the capture loop, which is where accuracy actually comes from.
- **Sarah Chen** *(Tech Board PM)* — Right problem (meal occasions for an outsider-readable view), right unit (the recurring template, per the behavioral lens). Phase gating is correct: prove deterministic grouping privately before a model or a public surface.
- **Viktor Sorokin** *(Principal of No — conditional)* — I still hold that templates + meal-buckets + the capture loop cover ~95%, so the LLM names a shrinking tail. I approve **only** because the cost design bounds it to near-zero and the output is frozen + correctable. My condition: **if the monthly call cap is ever hit, that is a signal the templates are wrong — fix the templates, don't raise the cap.** Wire the alarm to me.
- **Dana Torres** *(FinOps — costing sign-off below)* — Architecturally cheap-by-design. Approve with a budget alarm + monthly cap. Endorse Batch API for backfill; defer Bedrock to the platform-wide migration rather than special-casing this Lambda.

## 4. Costing (Dana Torres)

Model: **Claude Haiku 4.5 — $1.00 / M input, $5.00 / M output; Batch API 50% off; prompt caching 90% off cached input** (Anthropic list price, verified 2026-06-19).

**Per naming call** (minimal system prompt + short canonical food list ≈ 210 input tokens; constrained JSON name+confidence, `max_tokens≈32` ≈ 25 output tokens):

| | Input | Output | Cost/call |
|---|---|---|---|
| Standard | 210 tok × $1/M | 25 tok × $5/M | **≈ $0.00034** |
| Batch (50%) | — | — | **≈ $0.00017** |

**One-time backfill** (history from 2026-02-22, ~118 days). After meal-buckets + templates + the capture loop, only *distinct novel signatures* hit the model — estimate 150–300:

- Batch rate: 300 × $0.00017 ≈ **$0.05**.
- Worst-case sanity bound (1,000 distinct signatures, standard rate): **$0.34**.

**Steady-state:** new distinct signatures/month start ~20–40 and **decay toward zero** as the library saturates (promote-to-template removes them permanently): ≈ **$0.01/month**, trending to $0.

**Guardrail ceiling:** the proposed 500-call/month cap is a hard ceiling of **≈ $0.17/month** — and tripping it fails safe to "Mixed meal", so it's a true ceiling, not a soft target.

**Compute:** the grouper hot path is pure compute on small daily payloads; name-cache reads/writes are trivial. Negligible within the existing ~$20/month AWS envelope. No new always-on service.

**Verdict:** LLM lifetime cost is dominated by a sub-$0.35 one-time backfill plus pennies/month decaying to zero. The cost story is the **architecture** (residual-only + signature cache + promote-to-template), not the rate card. Add a line to `COST_TRACKER` only when the namer (Phase 2) ships; set the budget alarm at the cap. **Costing approved.**

## 5. Consolidated verdict & change list

**Approved to build (11 approve / 0 reject / 1 conditional — Viktor).** Conditions, all folded into spec v1.1:

1. **Aggregate on signature/template, never on the LLM name** (Henning) — analytics immune to naming flakiness.
2. **Spend guardrail fails safe** to "Mixed meal" on cap breach; alarm routed to Viktor (Jin/Dana/Viktor).
3. **Cap is a tripwire, not a budget** — hitting it means fix the templates, not raise the cap (Viktor).
4. **One swappable namer module** (Anthropic API now, Bedrock at platform migration) (Elena/Dana).
5. **Conservation reconciliation in CI**, run over the full backfill; halt on failure (Omar).
6. **Own Secrets Manager secret** for the namer; backfill via **Batch API** (Marcus/Dana).
7. **Canonical vocabulary + name cache** are first-class objects with their own homes (Omar).
8. **Deterministic-first stays the system of record**; model output frozen + correctable, never read-path (Anika/Priya).

## 6. Open items / prerequisites before build

- [ ] **Phase 0 source-label check** — does the raw MacroFactor export carry a meal bucket ingestion is dropping? (Primary vs refinement segmenter.)
- [ ] **Phase 0 history scan** — real collision rate + data-proposed seed templates + canonical-vocab draft.
- [x] **Locked 2026-06-19:** `GAP_MIN`=15 · `CONF_MIN`=0.7 (below = `uncategorized`: excluded from analytics, still counted in totals) · promotion `k`=3 · monthly cap=500 (fail-safe to `uncategorized`) · namer endpoint=**Batch API** (Bedrock deferred to platform migration).
