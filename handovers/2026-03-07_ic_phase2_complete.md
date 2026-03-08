# Handover — 2026-03-07 — v2.88.0: IC-23/24/25 + IC-16 All Digests + IC-19 Decision Journal

## Platform State
- **Version:** v2.88.0
- **MCP tools:** 142 (+3) | **Lambdas:** 33 | **Modules:** 29 (+1 tools_decisions.py)
- **IC features built:** 11 of 30 (IC-1/2/3/6/15/16/17/19/23/24/25)

---

## What Was Built This Session

### IC-23: Attention-Weighted Prompt Budgeting (ai_calls.py)
- `_compute_surprise_scores(data)` — per-metric surprise (0–1) vs 7-day baselines
- `_build_surprise_context()` — only surfaces metrics above 0.4 threshold
- Domains: HRV, sleep, nutrition, steps, glucose, recovery
- Injected into BoD + TL;DR calls

### IC-24: Data Quality Scoring (ai_calls.py)
- `_compute_data_quality(data, profile)` — per-source confidence scoring
- Detects: logging gaps (<50% of target), sync failures, partial data
- Weighted overall score with instruction: "Do NOT coach assertively on incomplete data"
- Injected into BoD, TL;DR, AND training/nutrition coach

### IC-25: Diminishing Returns Detector (ai_calls.py)
- `_compute_diminishing_returns(character_sheet, data, profile)`
- Maps habits to pillars, computes effort vs score trajectory
- Detects saturated pillars (high effort + high score) and underinvested ones
- Coaching redirects to highest-leverage pillar

### IC-16: Progressive Context — All 6 Email Lambdas
- `insight_writer.py` bundled with all digest Lambdas
- Before AI calls: `build_insights_context(days, pillars, max_items)` retrieves recent insights
- After email send: writes structured insight records to Insight Ledger
- Context windows: Daily (14d), Weekly (30d), Monthly (90d), Chronicle (30d), Nutrition (14d), Plate (14d)

### IC-19: Decision Journal (3 new MCP tools)
- **New module:** `mcp/tools_decisions.py`
- **DDB partition:** `pk=USER#matthew#SOURCE#decisions`, `sk=DECISION#<ISO-timestamp>`
- `log_decision` — record what platform recommended + whether followed
- `get_decisions` — retrieve with trust calibration stats (follow vs override effectiveness)
- `update_decision_outcome` — record outcome 1-3 days later

### Roadmap: IC-23–IC-30 added (Expert Panel Phase 3)
- IC-26 Temporal Pattern Mining (Month 2-3)
- IC-27 Multi-Resolution Intelligence Handoff (Month 2-3)
- IC-28 Insight Distillation / Permanent Learnings (Month 3-4)
- IC-29 Coaching Effectiveness A/B Testing (Month 3-4)
- IC-30 Counterfactual Reasoning (Month 5+)

---

## Deploy Instructions

```bash
cd ~/Documents/Claude/life-platform
bash deploy/deploy_ic_phase2.sh
```

Deploys 7 Lambdas sequentially (10s delay between each):
1. `daily-brief` — IC-23/24/25 in ai_calls.py
2. `weekly-digest` — IC-16 
3. `monthly-digest` — IC-16
4. `wednesday-chronicle` — IC-16
5. `nutrition-review` — IC-16
6. `weekly-plate-schedule` — IC-16
7. `life-platform-mcp` — IC-19 (142 tools)

**Deploy status (all 7 confirmed):**
1. daily-brief ✅ (2026-03-08T03:19:50)
2. weekly-digest ✅ (2026-03-08T03:20:02)
3. monthly-digest ✅ (2026-03-08T03:20:14)
4. wednesday-chronicle ✅ (2026-03-08T03:20:26)
5. nutrition-review ✅ (2026-03-08T03:20:38)
6. weekly-plate ✅ (2026-03-08T03:21:50) — deploy script had wrong name `weekly-plate-schedule`, fixed to `weekly-plate`
7. life-platform-mcp ✅ — `deploy_mcp_split.sh` smoke test reported FAIL but CloudWatch confirms clean init (121 MB, tools/list succeeded). False alarm from stale smoke test format.

**Post-deploy verification:**
```bash
# MCP tool count (should be 142)
aws lambda invoke --function-name life-platform-mcp \
  --cli-binary-format raw-in-base64-out \
  --payload '{"requestContext":{"http":{"method":"POST"}},"body":"{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}"}' \
  /tmp/mcp_out.json --region us-west-2 && cat /tmp/mcp_out.json | python3 -c "import sys,json; d=json.load(sys.stdin); b=json.loads(d.get('body','{}')); print(len(b.get('result',{}).get('tools',[])),'tools')"
```

---

## Files Changed
- `lambdas/ai_calls.py` — IC-23, IC-24, IC-25 
- `lambdas/weekly_digest_lambda.py` — IC-16
- `lambdas/monthly_digest_lambda.py` — IC-16
- `lambdas/wednesday_chronicle_lambda.py` — IC-16
- `lambdas/nutrition_review_lambda.py` — IC-16
- `lambdas/weekly_plate_lambda.py` — IC-16
- `mcp/tools_decisions.py` — NEW (IC-19)
- `mcp/registry.py` — IC-19 import + 3 tool registrations
- `deploy/deploy_ic_phase2.sh` — NEW
- `docs/CHANGELOG.md` — v2.88.0
- `docs/PROJECT_PLAN.md` — IC-16/19/23/24/25 marked complete + Phase 3 roadmap

---

## Pending Items

### Next IC features (ready to build)
- **IC-18: Cross-Domain Hypothesis Engine** — weekly Lambda, scientific method on data. 4-5 hr.
- **IC-7: Cross-pillar trade-off reasoning** — prompt enhancement, 1-2 hr.

### Month 2+ (data maturity required)
- IC-4 Failure pattern recognition (6+ weeks data)
- IC-5 Momentum detection / early warning (6+ weeks)
- IC-8 Intent vs execution gap (4+ weeks journal data)
- IC-26 Temporal Pattern Mining (8+ weeks)
- IC-27 Multi-Resolution Intelligence Handoff (insight corpus needed)

### Prompt Intelligence Fixes (carried forward)
- P1: Weekly Plate memory (anti-repeat) — may be partially addressed by IC-16
- P2: Journey context block — done in ai_calls.py
- P3: Training coach walk rewrite — done
- P4: Habit → outcome connector — done (IC-2/IC-3)
- P5: TDEE/deficit context — done

### Other carried forward
- Google Calendar integration (Board rank #9, North Star gap #2)
- HAE/Notion data gap backfill assessment

## Version
v2.88.0 | 33 Lambdas | 142 MCP tools | 29 modules
