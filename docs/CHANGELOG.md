## v3.7.80 — 2026-03-19: WR-24 subscriber gate, S2-T2-2 /board/ page, sprint plan cleanup

### Summary
Three pure dev items shipped: (1) WR-24 — subscriber verification gate on /ask/ (3 anon q/hr → 20/hr for confirmed subscribers via HMAC token + /api/verify_subscriber endpoint); (2) S2-T2-2 — "What Would My Board Say?" lead magnet page at /board/ with 6 AI personas (Attia, Huberman, Patrick, Norton, Clear, Goggins) and /api/board_ask endpoint; (3) Sprint plan cleanup marking S2-T1-9 and S2-T1-10 as done. CDK deployed LifePlatformWeb with 2 new CloudFront behaviors. Full site synced to S3.

### Changes

**lambdas/site_api_lambda.py**
- `_get_token_secret()` — derives HMAC signing secret from existing Anthropic API key (no new secrets)
- `_generate_subscriber_token(email)` — 24hr HMAC token (base64-encoded, `email:expires:sig` format)
- `_validate_subscriber_token(token)` — constant-time compare, expiry check
- `_is_confirmed_subscriber(email)` — DDB lookup: `USER#matthew#SOURCE#subscribers / EMAIL#{sha256}`, `status=="confirmed"`
- `_handle_verify_subscriber(event)` — GET `/api/verify_subscriber?email=...` → 404 if not found, 200 + token if confirmed
- `PERSONA_PROMPTS` — 6 persona system prompts (Attia, Huberman, Patrick, Norton, Clear, Goggins)
- `_handle_board_ask(event)` — POST `/api/board_ask` → per-persona Haiku 4.5 calls, 5/hr IP rate limit
- `ROUTES` dict updated — `/api/verify_subscriber` and `/api/board_ask` added (None handlers, dispatched in lambda_handler)
- `lambda_handler` — WR-24 subscriber token check: reads `X-Subscriber-Token` header, validates, sets rate limit to 3 (anon) or 20 (subscriber); routes /api/verify_subscriber and /api/board_ask
- `CORS_HEADERS` — added POST to allowed methods, added `X-Subscriber-Token` to allowed headers
- `_ask_rate_check(ip_hash, limit=3)` — parameterised limit (was hardcoded 5)

**site/ask/index.html — WR-24 subscriber gate**
- `MAX_QUESTIONS = 3` (was 5)
- `SUBSCRIBER_LIMIT = 20`, `SUB_TOKEN_KEY = 'lp_sub_token'`
- `effectiveLimit()` — returns 3 anon or 20 subscriber based on sessionStorage token
- `verifySubscriber()` — calls `/api/verify_subscriber`, stores token, unlocks higher limit
- Rate-banner replaced with subscriber gate UI: email input + Verify button + status + subscribe CTA
- All `MAX_QUESTIONS` comparisons replaced with `effectiveLimit()`
- `X-Subscriber-Token` header forwarded on every `/api/ask` POST
- Hint text updated: "3 questions remaining · subscribe for more"

**site/board/index.html — S2-T2-2 new page**
- Full "What Would My Board Say?" interactive tool
- Board member selector grid: 6 cards with toggle, select-all, select-none
- Suggestion chips (5 random from 8), textarea + Ask button (Cmd+Enter)
- Skeleton loading cards per selected persona
- Per-persona response cards with avatar, name, title, formatted body
- Subscribe CTA shown after first successful response
- 3 q/session rate limit via sessionStorage
- Calls `/api/board_ask` with `{question, personas: [...]}`

**cdk/stacks/web_stack.py**
- Added `/api/verify_subscriber` cache behavior (GET, query_string=True, TTL=0)
- Added `/api/board_ask` cache behavior (all HTTP methods, TTL=0)
- Both inserted before `/api/ask` behavior

**docs/SPRINT_PLAN.md**
- S2-T1-9 (Adaptive Deficit Ceiling): ⬜ → ✅ Done (v3.7.72)
- S2-T1-10 (Weekly Habit Review): ⬜ → ✅ Done (v3.7.72)
- Sprint 5 DoD: both items updated to ✅
- WR-24 and S2-T2-2 added as completed rows in Sprint 5 table
- WR-24 in 90-day backlog updated to ✅ Done (v3.7.80)
- Sprint 5 timeline summary updated

### Deploys
- `LifePlatformWeb` CDK stack: ✅ 2026-03-19 (130s) — SiteApiLambda rebuilt + 2 new CF behaviors
- `site/ask/index.html`: ✅ S3 synced — subscriber gate live
- `site/board/index.html`: ✅ S3 synced — new /board/ page live
- CloudFront: ✅ Invalidated `/*`

### Smoke tests (run after CloudFront propagates ~5min)
```bash
# Board page
curl -s https://averagejoematt.com/board/ | grep -c "What Would My Board Say"

# Verify subscriber endpoint (expect 404 for non-subscriber)
curl -s "https://averagejoematt.com/api/verify_subscriber?email=test@example.com" | python3 -m json.tool

# Board ask endpoint
curl -s -X POST https://averagejoematt.com/api/board_ask \
  -H "Content-Type: application/json" \
  -d '{"question":"How much protein do I need?","personas":["norton"]}' | python3 -m json.tool
```

---

