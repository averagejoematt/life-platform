# Handover — v3.9.28

## Session: Challenge System — Full Stack Build (Phases A + B + C)

### What shipped this session (v3.9.27 → v3.9.28)

**v3.9.28**: Challenge system — data foundation, MCP tools, website page, AI generation pipeline.

Joint Product Board + Technical Board session established the architecture:
- Experiments = science (hypothesis, controlled, published data) → "The Lab"
- Challenges = action (participation invitation, gamification, habit-building) → "The Arena"
- 5 generation sources: journal mining, data signals, hypothesis graduates, science scans, manual/community

#### Phase A — Data Foundation ✅ DEPLOYED
- `mcp/config.py` — Added `CHALLENGES_PK` constant
- `mcp/tools_challenges.py` — **New module**: 5 MCP tools
  - `create_challenge` — Create manually or from AI candidate
  - `activate_challenge` — Transition candidate → active
  - `checkin_challenge` — Daily check-in (yes/no + note + rating)
  - `list_challenges` — List with status/source/domain filters + progress stats
  - `complete_challenge` — End challenge, compute success rate, award XP, unlock badges
- `mcp/registry.py` — All 5 tools registered (103 tools total, 7/7 registry tests passed)
- `lambdas/site_api_lambda.py` — `/api/challenges` reads from DynamoDB (S3 fallback), new `/api/challenge_checkin` POST endpoint
- DynamoDB schema: `pk=USER#matthew#SOURCE#challenges`, `sk=CHALLENGE#<slug>_<date>`

#### Phase B — AI Generation Pipeline ✅ WRITTEN (not yet deployed)
- `lambdas/challenge_generator_lambda.py` — **New Lambda**
  - Runs weekly (Sunday 3 PM PT, after hypothesis engine)
  - Gathers 14d context: journal entries (enriched), character sheet, habit scores, confirmed hypotheses, health snapshot
  - Calls Claude Sonnet with structured prompt → 0-5 challenge candidates
  - Dedup against existing challenges
  - Writes candidates to DDB with status='candidate'
  - ~$0.05/week cost
- `ci/lambda_map.json` — Added `challenge-generator` entry (not_deployed: true, needs CDK)

#### Phase C — The Arena Page ✅ DEPLOYED
- `site/challenges/index.html` — **New page**: "The Arena"
  - Amber accent theme (distinct from green Lab/experiments page)
  - Active Challenge Hero with countdown ring, check-in calendar strip, daily check-in buttons
  - Candidates Grid with source badges (Journal pattern, Data signal, etc.)
  - Completed Record showing XP earned, success rates, badges
  - Pipeline nav: Protocols → Experiments → Challenges → Discoveries
  - How It Works explainer + Experiments vs Challenges methodology section
  - Responsive mobile layout
- `site/experiments/index.html` — Removed embedded challenges section, replaced with single-line CTA linking to /challenges/

### Files Created
- `mcp/tools_challenges.py` — Challenge MCP tools module
- `site/challenges/index.html` — The Arena page
- `lambdas/challenge_generator_lambda.py` — AI generation pipeline Lambda

### Files Modified
- `mcp/config.py` — CHALLENGES_PK added
- `mcp/registry.py` — 5 challenge tools imported + registered
- `lambdas/site_api_lambda.py` — DynamoDB challenges endpoint + checkin POST
- `site/experiments/index.html` — Removed Zone 2.5, added Arena CTA
- `ci/lambda_map.json` — challenge-generator entry added
- `deploy/sync_doc_metadata.py` — Version bump v3.9.27 → v3.9.28
- `cdk/stacks/compute_stack.py` — Added ChallengeGenerator Lambda + EventBridge schedule
- `cdk/stacks/role_policies.py` — Added `compute_challenge_generator()` IAM policy

### Deploy Status
- MCP Lambda: ✅ Deployed (v3.9.28 tools live)
- Site API Lambda: ✅ Deployed (DynamoDB challenges + checkin endpoint)
- S3 site sync: ✅ Deployed (challenges page + experiments page update)
- CloudFront invalidation: ✅ Complete
- challenge-generator Lambda: ✅ Deployed via CDK (EventBridge Sunday 3 PM PT)
- Manual invoke test: ✅ `{"status": "completed", "generated": 0, "reason": "no_signal"}` (correct — no data yet)

### CDK Changes (deployed)
- `cdk/stacks/compute_stack.py` — Added ChallengeGenerator Lambda definition
- `cdk/stacks/role_policies.py` — Added `compute_challenge_generator()` policy (DDB + KMS + ai-keys + S3 config)
- EventBridge: `cron(0 22 ? * SUN *)` → Sunday 3 PM PT (22:00 UTC)
- Timeout: 120s, Memory: 512MB
- CloudWatch error alarm auto-created by helper

### Pending Items
- Phase D: Challenge completion → Character Sheet XP integration (wire `character_xp_awarded` into character-sheet-compute)
- Phase E: Science literature scan, metric-auto-verification for step/weight/eating-window challenges
- Nav update: Add /challenges/ to components.js nav dropdown under "Method" section
- Create first manual challenge via MCP to test full flow end-to-end
- SIMP-1 Phase 2 + ADR-025 cleanup targeted ~April 13
- Day 1 checklist (April 1): run `capture_baseline`, verify homepage shows "DAY 1"
