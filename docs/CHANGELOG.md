# Life Platform — Changelog

## v3.7.63 — 2026-03-17: BS-02 hero live, journal Signal alignment, SES sandbox exit

### Summary
Post-Sprint-1 cleanup session. BS-02 hero drop-in applied to `index.html` and deployed live. Journal page brought into Signal design system parity (ticker, live data, nav/CSS path fixes, animate-in). SES production access request submitted. `ci/lambda_map.json` confirmed already had `chronicle_email_sender` — no action needed.

### Modified Files
- `site/index.html`: BS-02 hero drop-in applied (transformation story format: 302→current→185 counter, progress bar, stat chips, Chronicle teaser). JS unified to single fetch `/site/public_stats.json`. OG description updated to 89 tools. **DEPLOYED ✅** (S3 + CloudFront invalidation E3S424OXQZ8NBE)
- `site/journal/index.html`: Signal design system alignment — ticker added with live data feed, CSS paths corrected to absolute (`/assets/css/`), nav links fixed (`/platform/` `/journal/` `/character/`), `animate-in` classes added to header + list, footer links/copy updated, live data JS added (populates ticker + nav date from `/site/public_stats.json`).
- `lambdas/daily_brief_lambda.py` (via `site_writer.py`): Redeployed to pick up hero changes. **DEPLOYED ✅**

### Infrastructure
- SES production access request submitted via `aws sesv2 put-account-details`. Pending AWS review (~24h).
- CloudFront invalidation ICSV1P164RAIOE8A6WR5RNEBI in progress for `E3S424OXQZ8NBE` (averagejoematt.com).

### Pending (next session)
- BS-02 paragraph: write 50-word `HERO_WHY_PARAGRAPH` in `site_writer.py`, set `paragraph_is_placeholder: False`, redeploy daily-brief
- Verify SES production access granted: `aws sesv2 get-account`
- Deploy journal page to S3
- Sprint 2 prereqs: BS-08 sleep conflict rules doc, BS-05 confidence spec per-insight-type

---

## v3.7.62 — 2026-03-17: Sprint 1 complete — BS-01, BS-02, BS-03, BS-05, BS-09

### Summary
All 5 Sprint 1 features implemented and deployed. Board architecture decision (4-0): separate `chronicle-email-sender` Lambda over inline call. BS-01 and BS-09 were already code-complete from prior sessions; MCP registry entries confirmed present. BS-03 (new Lambda + CDK + IAM), BS-05 (confidence wiring into Chronicle), and BS-02 (hero section in `public_stats.json` + homepage HTML snippet) built and deployed this session.

### New Files
- `lambdas/chronicle_email_sender_lambda.py`: **NEW** — BS-03. Delivers Chronicle installment to confirmed email subscribers. Viktor guard: clean no-op if no installment found this week. Rate-limited (1/sec, bumped after SES production access). Personalized unsubscribe link per subscriber (CAN-SPAM). Signal-branded HTML email. `_confidence_badge_html` field read from DDB installment record (BS-05 integration).
- `deploy/hero_snippet_bs02.html`: **NEW** — BS-02 homepage hero drop-in. Reads from `public_stats.json` via fetch. Live weight counter (302 → current → 185), progress bar, days on journey, streak chip, Chronicle teaser. Skeleton loading state. Placeholder paragraph flag (`paragraph_is_placeholder: true`) until Matthew writes his 50-word paragraph.
- `deploy/patch_chronicle_bs05.py`: Patches wednesday_chronicle_lambda.py BS-05 (duplicate confidence block insertion — superseded by fix_chronicle_bs05.py).
- `deploy/fix_chronicle_bs05.py`: Cleaned up duplicate confidence block, updated store_installment kwargs call.
- `deploy/fix_store_installment_sig.py`: Updated `store_installment()` signature at line 1497 to accept `confidence_level` and `confidence_badge_html` kwargs.
- `deploy/patch_role_policies_bs03.py`: Inserted `email_chronicle_sender()` IAM policy function into role_policies.py.

### Modified Files
- `cdk/stacks/email_stack.py`: Added `ChronicleEmailSender` Lambda entry. `cron(10 15 ? * WED *)` — 8:10 AM PT Wednesday. `timeout=300s`, `SEND_RATE_PER_SEC=1.0`, `SITE_URL` env vars. **DEPLOYED ✅**
- `cdk/stacks/role_policies.py`: Added `email_chronicle_sender()` function (DDB GetItem/Query, KMS Decrypt, SES send, DLQ — no ai-keys, no S3 read). **DEPLOYED ✅**
- `lambdas/site_writer.py`: v1.1.0. Added `hero` section to `public_stats.json` (BS-02): narrative paragraph, live weight, progress pct, days on journey. Added `chronicle_latest` section (latest Chronicle headline for below-fold). Updated `write_public_stats()` signature with `table_client` and `user_id` params. **DEPLOYED ✅** (via daily-brief)
- `lambdas/wednesday_chronicle_lambda.py`: BS-05 confidence block in lambda_handler, `build_email_html()` injects confidence badge, `store_installment()` signature updated with confidence kwargs, `_confidence_level` + `_confidence_badge_html` fields written to DDB item. **DEPLOYED ✅**

### Architecture Decision
**BS-03 routing — Board vote 4-0 (Marcus/Jin/Elena/Priya):** Separate Lambda over inline call. Clean separation of concerns, independent DLQ/alarm/retry. Viktor guard: no-op if no Chronicle installment found this week — makes the 10-min EventBridge timing gap irrelevant to correctness.

### Deployments (all ✅)
- `LifePlatformEmail` CDK deploy: `chronicle-email-sender` Lambda created. IAM role: DynamoDB GetItem/Query, KMS Decrypt, SES send, DLQ. EventBridge `cron(10 15 ? * WED *)`.
- Post-CDK smoke: 10/10 passed.
- `wednesday-chronicle` Lambda (BS-05): confidence block wired.
- `daily-brief` Lambda (BS-02): site_writer hero section.
- `life-platform-mcp`: BS-01 `get_essential_seven` + BS-09 `get_acwr_status` both confirmed in registry.

### Remaining Manual Steps
- `ci/lambda_map.json`: Add `chronicle_email_sender` entry
- Homepage hero: drop `deploy/hero_snippet_bs02.html` into `index.html`
- BS-02 paragraph: edit `HERO_WHY_PARAGRAPH` in `site_writer.py` + set `paragraph_is_placeholder: False`
- SES sandbox exit: request production SES access (blocks real subscriber delivery)

### Sprint 1 Status: COMPLETE ✅
| ID | Feature | Status |
|----|---------|--------|
| BS-01 | Essential Seven Protocol | ✅ Deployed (was already code-complete) |
| BS-02 | Website Hero Redesign | ✅ site_writer updated; hero_snippet ready to drop in |
| BS-03 | Chronicle → Email Pipeline | ✅ chronicle-email-sender deployed |
| BS-05 | AI Confidence Scoring | ✅ wired into Chronicle (DDB + email) |
| BS-09 | ACWR Training Load Model | ✅ Deployed (was already code-complete) |

---

## v3.7.61 — 2026-03-16: Board Summit gap-fill + full sprint plan
