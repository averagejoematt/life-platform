## v3.7.83 — 2026-03-20: Operational Efficiency Roadmap + Claude Code Adoption

### Changes

**docs/PROJECT_PLAN.md** — updated
- Added Operational Efficiency Roadmap section (OE-01 through OE-10), stack-ranked by ROI
- Derived from full conversation history analysis across all Life Platform sessions
- Covers: Claude Code adoption, shell aliases, tool surface management, Project Knowledge, terminal anti-patterns, test discipline, memory strategy, Deep Research, doc consolidation, dev environment

**OE-01: Claude Code installed and verified (v2.1.80)**
- Native binary installed via `curl -fsSL https://claude.ai/install.sh | bash`
- PATH configured in ~/.zshrc
- Authenticated via browser (uses existing Pro subscription)
- First session launched in life-platform directory
- Claude Code cheat sheet PDF created (2-page transition guide: before/after comparisons, essential commands, Chat vs Code decision matrix)

---

## R17 Architecture Review — 2026-03-20

### Summary
Architecture Review #17 conducted (grade A-). 13 findings across security, observability, architecture, compliance, and code hygiene. 6 board decisions made. Sprint 6 (R17 Hardening) created with 18 items across 3 tiers. Grade drops from A to A- because the platform crossed the public-exposure threshold (AI endpoints on the open internet) and defensive controls haven't fully caught up.

Key board decisions: WAF rate-based rules on CloudFront (+$7/mo, replaces in-memory rate limiting as primary layer), move site-api to us-west-2 (60-day, $0), separate Anthropic API key for public endpoints (+$0.40/mo), graceful degradation pattern for AI calls (no new deps), UptimeRobot free tier for external monitoring. Platform cost increases from ~$13 to ~$20.40/month (under $25 budget cap). All decisions approved by Matthew.

Critical pre-DIST-1 items: WAF, privacy policy page, CloudWatch dashboard, PITR drill, separate API key.

### Changes

**docs/reviews/REVIEW_2026-03-20_v17.md** — new
- Full R17 review document (14-member board, 13 findings, 6 board decisions)
- Per-panelist grades: Yael B+ (security gaps on public endpoints), Raj B+ (distribution vs infrastructure ratio), Viktor B+ (attack surface analysis), all others A- to A
- Board deliberation on 6 open decisions with full rationale

**docs/SPRINT_PLAN.md** — updated
- Sprint 6 (R17 Hardening) added: 8 Tier 0 items (pre-DIST-1), 6 Tier 1 (60-day), 4 Tier 2 (90-day)
- Sprint Timeline Summary updated with Sprint 6 and corrected R18 target
- Footer updated with R17 review reference

### Architecture Review #17 Findings Summary
| ID | Severity | Finding |
|----|----------|---------|
| R17-F01 | Critical | Public AI endpoints lack persistent rate limiting |
| R17-F02 | High | In-memory rate limiting resets on cold start |
| R17-F03 | High | No WAF on public-facing CloudFront distributions |
| R17-F04 | Medium | Subscriber email verification has no rate limit |
| R17-F05 | High | Cross-region DynamoDB reads (site-api us-east-1 → DDB us-west-2) |
| R17-F06 | Medium | No observability on public API endpoints |
| R17-F07 | Medium | CORS headers not evidenced on site API |
| R17-F08 | Low | google_calendar still in config.py SOURCES list |
| R17-F09 | Low | MCP Lambda memory discrepancy in documentation |
| R17-F10 | Low | Site API AI calls use hardcoded model strings |
| R17-F11 | Medium | No privacy policy or terms of service on public website |
| R17-F12 | Medium | PITR restore drill still not executed (carried since R13) |
| R17-F13 | Medium | 95 tools creates context window pressure for Claude |

---

## v3.7.81 — 2026-03-19: Standardise nav + footer across all 12 pages

### Summary
Navigation audit revealed 8 of 12 pages were unreachable from the main nav — including /story/ (the distribution gate), /board/, /ask/, /explorer/, /experiments/, /biology/, /about/, and /live/. New consistent nav ships Story · Live · Journal · Platform · Character · Subscribe across all 12 pages. New full footer links all 12 pages. `deploy/update_nav.py` added for future nav maintenance.

### Changes

**deploy/update_nav.py** — new script
- Regex-patches nav + footer blocks across all 12 site pages in one pass
- Per-page active state on nav links, dry-run mode

**All 12 site pages — nav updated**
- Old: The experiment · The platform · Journal · Character (4 items, inconsistent)
- New: Story · Live · Journal · Platform · Character · [Subscribe →] (6 items, consistent)
- /story/ promoted into nav — was completely invisible despite being the distribution gate
- /live/ promoted into nav — was only reachable via homepage dual-CTA

**All 12 site pages — footer updated**
- Old: Story · Journal · Platform · Character · Subscribe
- New: Story · Live · Journal · Platform · Character · Experiments · Explorer · Biology · Ask · Board · About · Subscribe + Privacy
- /board/, /ask/, /explorer/, /experiments/, /biology/ no longer orphaned

### Deploys
- 12 static pages: ✅ S3 synced, CloudFront invalidated `/*`

---

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
- `ROUTES` dict updated, `lambda_handler` updated, `CORS_HEADERS` updated
- `_ask_rate_check(ip_hash, limit=3)` — parameterised limit (was hardcoded 5)

**site/ask/index.html — WR-24 subscriber gate**
- `MAX_QUESTIONS = 3`, `SUBSCRIBER_LIMIT = 20`, `effectiveLimit()`, `verifySubscriber()`
- Rate-banner replaced with subscriber gate UI
- `X-Subscriber-Token` header forwarded on every `/api/ask` POST

**site/board/index.html — S2-T2-2 new page**
- "What Would My Board Say?" — 6 AI personas, selector grid, skeleton loaders, subscribe CTA

**cdk/stacks/web_stack.py**
- Added `/api/verify_subscriber` and `/api/board_ask` cache behaviors

**docs/SPRINT_PLAN.md**
- S2-T1-9, S2-T1-10 marked ✅ Done; WR-24 + S2-T2-2 added as completed Sprint 5 rows

### Deploys
- `LifePlatformWeb` CDK stack: ✅ 2026-03-19 (130s)
- `site/ask/index.html`, `site/board/index.html`: ✅ S3 synced
- CloudFront: ✅ Invalidated `/*`

---
