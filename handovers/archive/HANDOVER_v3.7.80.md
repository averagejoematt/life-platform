# Life Platform Handover — v3.7.80
**Date:** 2026-03-19

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.80 |
| MCP tools | 95 |
| Data sources | 19 active |
| Lambdas | 49 (CDK) + 1 Lambda@Edge + 1 us-west-2 manual (email-subscriber) |
| Tests | 0 failing / 853 passing / 22 skipped / 11 xfailed |
| Architecture grade | A (R16) |
| Website | **12 pages** at averagejoematt.com (added /board/) |
| CI | ✅ GREEN |

---

## What Was Done This Session

### WR-24: Subscriber Gate on /ask/ ✅
- Anonymous visitors: 3 questions/hr
- Confirmed subscribers: 20 questions/hr (via HMAC token stored in sessionStorage)
- New endpoint: `GET /api/verify_subscriber?email=...`
  - Looks up `USER#matthew#SOURCE#subscribers / EMAIL#{sha256}`, checks `status=="confirmed"`
  - Returns 24hr HMAC token (derived from Anthropic API key — no new secrets)
- `/ask/` page: subscriber gate UI shown after question 3 (email input + Verify button)
- `X-Subscriber-Token` header sent on all `/api/ask` POSTs

### S2-T2-2: "What Would My Board Say?" /board/ ✅
- New page at `averagejoematt.com/board/` — lead magnet / free tool
- 6 AI personas: Attia, Huberman, Patrick, Norton, Clear, Goggins
- Board member selector grid (toggle, select-all/none), suggestion chips, skeleton loaders
- Calls `POST /api/board_ask` — per-persona Haiku 4.5 calls, 5/hr IP rate limit
- Subscribe CTA shown after first response
- 3 questions/session rate limit (sessionStorage)

### Sprint Plan Cleanup ✅
- S2-T1-9 (Adaptive Deficit Ceiling): marked ✅ Done (v3.7.72)
- S2-T1-10 (Weekly Habit Review): marked ✅ Done (v3.7.72)
- WR-24 + S2-T2-2 added as completed rows in Sprint 5 table

### CDK Deploy ✅
- `LifePlatformWeb` deployed (130s)
- 2 new CloudFront behaviors: `/api/verify_subscriber` (GET, no cache) + `/api/board_ask` (POST, no cache)
- SiteApiLambda rebuilt with all new endpoints

### Site Deploy ✅
- `site/ask/index.html` → S3 (subscriber gate)
- `site/board/index.html` → S3 (new /board/ page)
- CloudFront invalidated `/*`

---

## Open Issues

| Issue | Priority | Notes |
|-------|----------|-------|
| /story prose | **CRITICAL** | Distribution gate — Matthew writes 5 chapters |
| DIST-1 | HIGH | HN post / Twitter thread — needs /story first |

---

## Key Files Changed This Session

```
lambdas/site_api_lambda.py    — 3 new endpoints + subscriber token logic + PERSONA_PROMPTS
site/ask/index.html           — WR-24 subscriber gate (3 anon / 20 sub)
site/board/index.html         — New /board/ page (S2-T2-2)
cdk/stacks/web_stack.py       — 2 new CloudFront cache behaviors
docs/SPRINT_PLAN.md           — S2-T1-9, S2-T1-10 marked done; WR-24 + S2-T2-2 added
docs/CHANGELOG.md             — v3.7.80 entry
```

---

## Smoke Tests (run after CF propagates)

```bash
# Board page loads
curl -s https://averagejoematt.com/board/ | grep -c "What Would My Board Say"

# Verify subscriber (expect 404 + "not found" message)
curl -s "https://averagejoematt.com/api/verify_subscriber?email=test@example.com" | python3 -m json.tool

# Board ask (expect responses dict)
curl -s -X POST https://averagejoematt.com/api/board_ask \
  -H "Content-Type: application/json" \
  -d '{"question":"How much protein do I need?","personas":["norton"]}' | python3 -m json.tool
```

---

## Sprint Roadmap

```
Sprint 1–4   COMPLETE
Sprint 5     COMPLETE (buildable) — WR-24 ✅ S2-T2-2 ✅
v3.7.73–79   Maintenance + OG fix + CI fix + website enhancements
v3.7.80      WR-24 subscriber gate + /board/ page + sprint plan cleanup
NEXT         /story prose → DIST-1
SIMP-1 Ph2   (~Apr 13) 95 → ≤80 tools
```
