# Handover — 2026-03-07 — v2.87.0: IC-15 Insight Ledger + IC-17 Red Team

## Platform State
- **Version:** v2.87.0
- **MCP tools:** 139 | **Lambdas:** 33 | **Modules:** 28 (+1 insight_writer.py shared)

---

## What Was Built This Session

### v2.86.0 Deploy Verified
- `daily-insight-compute` Lambda created, EventBridge rule live (9:42 AM PT)
- Smoke test passed: `{"statusCode": 200, "momentum": "improving"}`
- IC-2, IC-3, IC-6 now live in production

### IC-15: Insight Ledger — Universal Write Utility

**New file:** `lambdas/insight_writer.py`

The compounding substrate. Every AI insight the platform generates now gets persisted to DynamoDB with structured metadata, enabling downstream features (progressive context, feedback loops, meta-analysis, semantic similarity).

**DDB pattern:** `pk=USER#matthew#SOURCE#insights`, `sk=INSIGHT#<ISO-timestamp>#<digest_type>`

**Record schema:**
- `pillars` — which of 7 Character Sheet pillars this insight touches (auto-detected from text)
- `data_sources` — which sources contributed
- `confidence` — high/medium/low
- `insight_type` — coaching / guidance / observation / alert / hypothesis
- `actionable` — boolean
- `tags` — semantic tags for retrieval
- `text` — truncated to 800 chars
- `text_hash` — SHA-256 first 12 chars for dedup
- `component_scores` — snapshot at time of insight (enables correlation later)
- `effectiveness` — null initially, populated by IC-12 feedback loop
- `ttl` — 180-day auto-expiry

**Daily Brief integration:**
- `extract_daily_brief_insights()` extracts 5-7 insights per brief: BoD coaching, TL;DR, each guidance item, training coach, nutrition coach, journal coach
- Called after email send, alongside dashboard/buddy/clinical writes
- Non-fatal: wrapped in try/except

**Read API (for IC-16 Progressive Context):**
- `get_recent_insights(days, pillars, digest_type, max_results)`
- `build_insights_context(days, pillars, max_items, label)` — returns prompt-ready string, empty if no insights

### IC-17: Contrarian "Red Team" Analysis Pass

Three surgical changes, zero new infrastructure:

1. **IC-3 analysis pass** now outputs a `challenge` field — forces the model to identify why its own pattern analysis might be wrong (confounding factors, insufficient data, correlation ≠ causation)

2. **`_format_analysis()`** surfaces the challenge as `⚠️ Red Team challenge:` in the context block that Pass 2 receives

3. **BoD + TL;DR prompts** include `RED TEAM CHECK` instruction — coaching adjusts when the challenge flags weak signal. Result: "sleep dipped but only 2 days of data — monitor rather than react" instead of overconfident causal claims.

### Roadmap Update

Added IC-15 through IC-22 to PROJECT_PLAN.md Tier 7 Phase 2:

| # | Feature | When |
|---|---------|------|
| IC-15 | ✅ Insight Ledger — universal write | Done |
| IC-16 | Progressive Context — all digests | Next |
| IC-17 | ✅ Red Team analysis | Done |
| IC-18 | Cross-Domain Hypothesis Engine | Next |
| IC-19 | Decision Journal | Next |
| IC-20 | Lightweight Semantic Similarity (Titan) | Month 3-4 |
| IC-21 | Annualized Personal Baselines | Month 3-4 |
| IC-22 | Quarterly Meta-Analysis | Month 3-4 |

---

## Deploy Instructions

```bash
cd ~/Documents/Claude/life-platform
bash deploy/deploy_ic15_ic17.sh
```

Deploys daily-brief with:
- `insight_writer.py` (new module in zip)
- Updated `ai_calls.py` (IC-17 Red Team changes)
- Updated `daily_brief_lambda.py` (IC-15 insight write call)

**Post-deploy verification:**

Tomorrow's brief (10 AM PT) will:
1. Log `[INFO] IC-15: X/Y insights persisted` — check CloudWatch
2. BoD coaching should reference Red Team challenge when appropriate

**Manual insight check after first brief runs:**
```bash
aws dynamodb query \
  --table-name life-platform \
  --key-condition-expression 'pk = :pk AND begins_with(sk, :sk)' \
  --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#insights"},":sk":{"S":"INSIGHT#"}}' \
  --scan-index-forward false --limit 10 --region us-west-2 --no-cli-pager
```

---

## Files Changed
- `lambdas/insight_writer.py` — NEW
- `lambdas/ai_calls.py` — IC-17 (challenge field + Red Team instructions)
- `lambdas/daily_brief_lambda.py` — IC-15 import + post-email insight write
- `deploy/deploy_ic15_ic17.sh` — NEW
- `docs/CHANGELOG.md` — v2.87.0
- `docs/PROJECT_PLAN.md` — Tier 7 Phase 2 (IC-15–IC-22)

---

## Pending Items

### Ready to Build (next session)
- **IC-16: Progressive Context — all digests** — extend IC-15 read API into Weekly Digest, Monthly Digest, Chronicle, Nutrition Review, Weekly Plate. Each gets a `build_insights_context()` call before AI generation. 4-5 hr.
- **IC-18: Cross-Domain Hypothesis Engine** — weekly Lambda, scientific method on personal data. 4-5 hr.
- **IC-19: Decision Journal** — MCP tool + DDB partition for tracking platform-guided decisions. 3-4 hr.

### Prompt Intelligence Fixes (from earlier session)
- P1: Weekly Plate memory (anti-repeat)
- P2: Journey context block (centralized)
- P3: Training coach walk rewrite
- P4: Habit → outcome connector ✅ (done in IC-2/IC-3 session)
- P5: TDEE/deficit context ✅ (done in IC-2/IC-3 session)

### Carried Forward
- Google Calendar integration (Board rank #9, North Star gap #2)
- deploy_lambda.sh multi-module fix assessment
- HAE/Notion data gap backfill assessment

## Version
v2.87.0 | 33 Lambdas | 139 MCP tools | 28 modules
