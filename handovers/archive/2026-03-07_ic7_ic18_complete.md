# Handover — 2026-03-07 — v2.89.0: IC-7 Cross-Pillar Trade-offs + IC-18 Hypothesis Engine

## Platform State
- **Version:** v2.89.0
- **MCP tools:** 144 (+2) | **Lambdas:** 34 (+1) | **Modules:** 30 (+1 tools_hypotheses.py)
- **IC features built:** 13 of 30 (IC-1/2/3/6/7/15/16/17/18/19/23/24/25)

---

## Context

Previous session got cut off mid-execution right before writing CHANGELOG + handover.
All code was fully written and deploy script created. This handover documents what was built.

---

## What Was Built

### IC-7: Cross-Pillar Trade-off Reasoning (ai_calls.py)
- `_build_cross_pillar_tradeoffs(component_scores, data, profile)`
- Detects 6 interaction patterns:
  1. Sleep vs Movement conflict (high TSB + poor sleep → hold training)
  2. Nutrition deficit vs TSB (aggressive deficit + elevated TSB → recovery risk)
  3. Stress vs Recovery mismatch (high journal stress + low recovery score)
  4. Metabolic lag (elevated glucose trend + low activity)
  5. Consistency trailing pillar strength (habits < 60% despite strong metrics)
  6. Compounding deficits (2+ pillars below 50 simultaneously)
- Injected into `call_board_of_directors` + `call_tldr_and_guidance`

### IC-18: Cross-Domain Hypothesis Engine
- **New Lambda:** `hypothesis_engine_lambda.py` → `hypothesis-engine`
- **Schedule:** Sunday 11 AM PT (EventBridge `hypothesis-engine-weekly`, cron `0 19 ? * SUN *`)
- **Workflow:**
  1. Pull 14 days all-pillar data (whoop, sleep, macrofactor, strava, habitify, apple, withings, journal, eightsleep, computed_metrics)
  2. Check pending hypotheses against recent data (Haiku, 1 call per hypothesis, skips <3 days old)
  3. Generate 3-5 new cross-domain hypotheses (Sonnet 4.6, ~2000 tokens)
  4. Write monitoring context to `platform_memory` for IC-16 downstream consumption
- **Hypothesis lifecycle:** `pending` → `confirming` → `confirmed` / `refuted` → `archived`
- **Cap:** MAX 20 pending hypotheses; stops generating if cap reached
- **DDB key pattern:** `pk=USER#matthew#SOURCE#hypotheses`, `sk=HYPOTHESIS#<ISO-timestamp>`
- **New MCP module:** `mcp/tools_hypotheses.py`
  - `tool_get_hypotheses(status, domain, days, include_archived)` — list + filter hypotheses
  - `tool_update_hypothesis_outcome(sk, verdict, evidence_note, effectiveness)` — manual update
- **Registry:** `get_hypotheses` + `update_hypothesis_outcome` (142 → 144 tools)
- **Cost:** ~$0.04/week (Sonnet generation + Haiku checks)

---

## Deploy Instructions

```bash
cd ~/Documents/Claude/life-platform
bash deploy/deploy_ic7_ic18.sh
```

Deploys 4 steps sequentially:
1. `daily-brief` — IC-7 in ai_calls.py
2. `life-platform-mcp` — tools_hypotheses.py, 144 tools
3. `hypothesis-engine` Lambda — create or update
4. EventBridge rule — `hypothesis-engine-weekly`

---

## Files Changed
- `lambdas/ai_calls.py` — IC-7 `_build_cross_pillar_tradeoffs()` + injection into 2 AI calls
- `lambdas/hypothesis_engine_lambda.py` — NEW (IC-18 Lambda)
- `mcp/tools_hypotheses.py` — NEW (2 MCP tools)
- `mcp/registry.py` — IC-18 import + 2 tool registrations
- `deploy/deploy_ic7_ic18.sh` — NEW deploy script
- `docs/CHANGELOG.md` — v2.89.0
- `docs/PROJECT_PLAN.md` — IC-7 + IC-18 marked complete (see below — NOT YET DONE, needs update)

---

## Post-Deploy Verification

```bash
# MCP tool count (expect 144)
aws lambda invoke --function-name life-platform-mcp \
  --cli-binary-format raw-in-base64-out \
  --payload '{"requestContext":{"http":{"method":"POST"}},"body":"{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}"}' \
  /tmp/mcp_out.json --region us-west-2 && \
  python3 -c "import json; d=json.load(open('/tmp/mcp_out.json')); b=json.loads(d.get('body','{}')); print(len(b.get('result',{}).get('tools',[])),'tools')"

# Test hypothesis engine (on-demand invoke)
aws lambda invoke --function-name hypothesis-engine \
  --cli-binary-format raw-in-base64-out \
  --payload '{"force_run":true}' /tmp/hypo_out.json --region us-west-2 && cat /tmp/hypo_out.json

# Check DDB for hypotheses after invoke
aws dynamodb query --table-name life-platform \
  --key-condition-expression 'pk = :pk AND begins_with(sk, :prefix)' \
  --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#hypotheses"},":prefix":{"S":"HYPOTHESIS#"}}' \
  --region us-west-2 --output json | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['Items']),'hypotheses')"
```

---

## Pending Items

### Next IC features
- **IC-4: Failure pattern recognition** — needs 6+ weeks data (ready ~April 18)
- **IC-5: Momentum detection** — needs 6+ weeks data
- **IC-8: Intent vs execution gap** — needs 4+ weeks journal data
- **IC-26: Temporal Pattern Mining** — needs 8+ weeks (ready ~May)
- **IC-27: Multi-Resolution Handoff** — needs insight corpus to accumulate

### Other roadmap items ready now
- **Google Calendar integration** (Board rank #9, North Star gap #2) — effort 6-8 hr
- **Monarch Money** (Board rank #14) — effort 4-6 hr
- **IC-7 / P1 already complete** — P1 Weekly Plate memory confirmed live in weekly_plate_lambda.py

## Version
v2.89.0 | 34 Lambdas | 144 MCP tools | 30 modules
