# Life Platform Handover — v3.7.82
**Date:** 2026-03-20

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.82 |
| MCP tools | 95 |
| Data sources | 19 active |
| Lambdas | 49 (CDK, us-west-2 + us-east-1) + 1 Lambda@Edge (manually managed) |
| Tests | 853 passing |
| Architecture grade | A (R16) |
| Website | **12 pages live** at averagejoematt.com |
| CI | ✅ GREEN |

---

## What Was Done This Session

### v3.7.80: WR-24 + S2-T2-2 + Sprint plan cleanup
- Subscriber gate on `/ask/`: 3 anon q/hr → verify email → 20 q/hr for confirmed subscribers
- `GET /api/verify_subscriber?email=` — HMAC token, 24hr, no new secrets
- `/board/` lead magnet page live — 6 AI personas (Attia, Huberman, Patrick, Norton, Clear, Goggins)
- `POST /api/board_ask` — per-persona Haiku 4.5 calls
- CDK: 2 new CloudFront behaviors + SiteApiLambda rebuilt
- Sprint plan: S2-T1-9, S2-T1-10 marked done; WR-24 + S2-T2-2 added

### v3.7.81: Nav + footer standardised
- Nav audit: 8 of 12 pages were unreachable from main nav (including /story/)
- New primary nav: Story · Live · Journal · Platform · Character · Subscribe
- New full footer: all 12 pages linked
- `deploy/update_nav.py` script added

### v3.7.82: Fix AccessDeniedException alarms
- Root cause: `_ask_rate_check()` + `_handle_board_ask()` called `table.put_item()` but site_api role is read-only (no PutItem — Yael directive)
- Fix: switched both to in-memory dicts (`_ask_rate_store`, `_board_rate_store`) — sliding window, no DDB writes
- Deployed via `aws lambda update-function-code` to us-east-1
- Alarm flood stopped

### Doc sweep (this session end)
- `docs/ARCHITECTURE.md`: MCP tools 87→95, memory 768→1024 MB, IC features 14 of 30→16 of 31, IC-29+IC-30 added to live list, WEB LAYER diagram updated to show 12-page site + site-api routes, IAM roles 43→49, local structure updated with site_api_lambda.py note
- `docs/PROJECT_PLAN.md`: header updated to v3.7.82, lambda count 48→49 CDK, website roadmap updated to show all 12 pages live (added /ask/ and /board/), completed items table updated
- `docs/SPRINT_PLAN.md`: Sprint 5 statuses updated (WR-11/12/13/16/19/21/22/23 all ✅), Sprint 5 DoD updated, v3.7.81/82 added to sprint timeline

---

## Open Items

| Issue | Priority | Notes |
|-------|----------|-------|
| `/story` prose | **CRITICAL** | Distribution gate. Matthew writes 5 chapters. Prompts in `site/story/index.html`. |
| DIST-1 | HIGH | HN post / Twitter thread — blocked on /story |
| SIMP-1 Phase 2 | ~Apr 13 | 95 → ≤80 tools. EMF telemetry review. |
| WR-17 Function URL 403 | LOW | OG image Lambda@Edge partially wired, needs debug |
| Privacy policy on /subscribe | LOW | Yael requirement, not yet added |

---

## Key Files Changed This Session

```
lambdas/site_api_lambda.py    — in-memory rate limit stores (v3.7.82)
site/ask/index.html           — subscriber gate (v3.7.80)
site/board/index.html         — /board/ page (v3.7.80)
site/*/index.html (12 pages)  — nav + footer standardised (v3.7.81)
deploy/update_nav.py          — new nav patch script (v3.7.81)
cdk/stacks/web_stack.py       — 2 new CloudFront behaviors (v3.7.80)
docs/ARCHITECTURE.md          — doc sweep (this session)
docs/PROJECT_PLAN.md          — doc sweep (this session)
docs/SPRINT_PLAN.md           — doc sweep (this session)
docs/CHANGELOG.md             — v3.7.80/81/82 entries
handovers/HANDOVER_v3.7.82.md — this file
```

---

## Git Commits This Session

- `7df9223` — v3.7.80: WR-24 + S2-T2-2 + sprint plan cleanup
- `12973b7` — v3.7.81: nav + footer standardisation (20 files, 277 insertions)
- `85e807b` — fix: in-memory rate limiting (stopped AccessDeniedException alarms)

**Pending commit** (doc sweep):
```bash
cd ~/Documents/Claude/life-platform
git add docs/ARCHITECTURE.md docs/PROJECT_PLAN.md docs/SPRINT_PLAN.md handovers/HANDOVER_v3.7.82.md
git commit -m "docs: v3.7.82 doc sweep — ARCHITECTURE, PROJECT_PLAN, SPRINT_PLAN accuracy fixes

ARCHITECTURE.md: MCP tools 87→95, memory 768→1024MB, IC features 14of30→16of31,
IC-29+IC-30 added to live list, WEB LAYER diagram updated to 12-page site,
site-api Lambda documented, IAM roles 43→49

PROJECT_PLAN.md: header v3.7.69→v3.7.82, lambda count 48→49 CDK, website roadmap
updated with /ask/ and /board/ as live pages, completed items table updated

SPRINT_PLAN.md: Sprint 5 statuses updated, v3.7.81/82 in timeline summary"
git push
```

---

## AWS Identifiers

- CloudFront AMJ: `E3S424OXQZ8NBE`
- Site API Function URL: `https://lxhjl2qvq2ystwp47464uhs2jti0hpdcq.lambda-url.us-east-1.on.aws/`
- Subscriber Function URL: `https://z4mtkuendtd3prnh2jw67gran40wnvve.lambda-url.us-east-1.on.aws/`
- DynamoDB: `life-platform` (us-west-2)
- S3: `matthew-life-platform`
- MCP Lambda: `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws`

---

## Next Session

1. Commit doc sweep (command above)
2. Write `/story` prose — 5 chapters, prompts already in place
3. DIST-1 — first external distribution event (HN / Twitter)
4. ~Apr 13: SIMP-1 Phase 2 (95 → ≤80 tools)
