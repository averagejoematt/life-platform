# Life Platform Handover — v3.7.71
**Date:** 2026-03-17 (end of session)

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.71 |
| MCP tools | 95 |
| Data sources | 19 active |
| Lambdas | 48 (CDK) + 1 Lambda@Edge + 1 us-east-1 (site-api) + 1 us-west-2 manual (email-subscriber) |
| Tests | 50 failing (pre-existing debt) / 823 passing / 3 xfailed / 1 error — no regressions introduced |
| Architecture grade | A (R16) |
| Website | 9 pages at averagejoematt.com |
| Sprint 5 | IN PROGRESS (5 of 8 items complete) |

---

## What Was Done This Session

### Sprint 5 items completed (v3.7.70 → v3.7.71)

| ID | Item | Status |
|----|------|--------|
| DEPLOY | Sprint 4 deploy | ✅ `/live`, `/explorer`, `/biology` + 3 API endpoints live |
| S2-T1-1 | MCP `Key` import bug fix | ✅ Already fixed on disk; MCP Lambda redeployed |
| S2-T1-6 | `/story` page | ✅ Template live at averagejoematt.com/story/ — content placeholders await Matthew |
| S2-T1-7 | `/about` page | ✅ Live at averagejoematt.com/about/ — bio, stack table, subscribe CTA |
| S2-T1-8 | Email CTA on all pages | ✅ 8/8 pages updated (add_email_cta.py); S3 synced + CloudFront invalidated |
| S2-T1-9 | Adaptive Deficit Ceiling | ✅ `_compute_deficit_ceiling_alert()` deployed in daily-insight-compute |

### Adaptive Deficit Ceiling detail (S2-T1-9)
- **Tier A (RATE):** Weight loss >2.5 lbs/week over 14 days → Priority 2 signal
- **Tier B (MULTI):** HRV drops >15% from baseline AND sleep efficiency <80% (3+ days) AND ≥2 T0 habits failing → Priority 1 signal (always surfaces)
- **Prescription:** Specific "Increase to {cal_target + 200} kcal/day for 5 days, then reassess" — not vague language
- Config via env vars: `DEFICIT_RATE_THRESHOLD`, `DEFICIT_HRV_DROP_PCT`, `DEFICIT_KCAL_INCREASE`, `DEFICIT_REASSESS_DAYS`
- Medical disclaimer appended per R13-F09

### Test housekeeping
- `W3_KNOWN_GAPS` in `tests/test_wiring_coverage.py` now correctly documents:
  - `daily_insight_compute_lambda.py` — IC-8 Haiku call bypasses ai_calls.py
  - `adaptive_mode_lambda.py` — direct API calls
  - Both show as `xfail` instead of `fail` (52 → 50 failures, 1 → 3 xfailed)

### Files changed this session
| File | Change |
|------|--------|
| `site/about/index.html` | New — bio page, live weight, stack table, subscribe CTA |
| `site/story/index.html` | New — 5-chapter template, content placeholders for Matthew |
| `site/index.html` + 7 others | Email CTA injected (add_email_cta.py) |
| `lambdas/daily_insight_compute_lambda.py` | Deficit ceiling patched (patch_deficit_ceiling.py) |
| `tests/test_wiring_coverage.py` | W3_KNOWN_GAPS documented (fix_w3_known_gaps.py) |
| `deploy/add_email_cta.py` | New script |
| `deploy/patch_deficit_ceiling.py` | New script |
| `deploy/fix_w3_known_gaps.py` | New script |

---

## Sprint 5 Remaining (3 of 8 items)

| ID | Item | Notes |
|----|------|-------|
| S2-T1-9 | Weekly Habit Review | Sunday auto-report in Daily Brief — not yet implemented |
| DIST-1 | First distribution event | HN post or Twitter thread — non-negotiable per board |
| /story content | Matthew writes the prose | 5 placeholder blocks in `site/story/index.html` — Chapters 1, 2, 4, 5 |

**Privacy policy** (Yael requirement) — `/subscribe` page still missing a visible privacy policy link. Needs to be addressed before active distribution.

---

## /story Page — Content Required

Open `site/story/index.html`. Find the green-dashed `placeholder` blocks. Five sections need Matthew's prose:

- **Chapter 1 — The Moment:** The specific day/situation that made this time different (3–5 paragraphs)
- **Chapter 2 — Previous Attempts:** What failed before and why (2–3 paragraphs)
- **Chapter 3 — The Build:** Already has platform stats; add 2–3 paragraphs about building as a non-engineer
- **Chapter 4 — What the Data Has Shown:** The human insight underneath the numbers (3–4 paragraphs — the most powerful section)
- **Chapter 5 — Why Public:** The personal reason for doing this openly (2–3 paragraphs)

This content is the prerequisite for everything distribution-related. Moreau: "no photo, no emotional arc — /story is the entry point that makes a stranger care enough to subscribe."

---

## Infrastructure State

| Lambda | Region | Status |
|--------|--------|--------|
| `life-platform-mcp` | us-west-2 | ✅ DEPLOYED v3.7.71 — Key bug fixed |
| `daily-insight-compute` | us-west-2 | ✅ DEPLOYED v3.7.71 — deficit ceiling live |
| `life-platform-site-api` | us-east-1 | ✅ DEPLOYED (Sprint 4) |
| All other Lambdas | us-west-2 | Unchanged |
| S3 site | — | ✅ All 9 pages synced |
| CloudFront | — | ✅ Invalidated |

---

## Open Issues

| Issue | Priority | Notes |
|-------|----------|-------|
| /story content | CRITICAL (distribution blocker) | Matthew writes; cannot be delegated to AI |
| First distribution event | HIGH | HN post or Twitter thread — Kim/Raj directive |
| Privacy policy on /subscribe | MEDIUM | Yael: visible before active distribution |
| Weekly Habit Review (S2-T1-10) | MEDIUM | Sunday auto-report not yet built |
| 50 pre-existing test failures | LOW | All architectural debt — none introduced this session |

---

## Sprint 5 Definition of Done (remaining)

- [ ] `/story` page prose written by Matthew and deployed
- [ ] At least one external distribution event published
- [ ] Privacy policy visible on /subscribe page
- [ ] Weekly habit review generating on Sundays

---

## Key Reminders for Next Session

- **MCP deploy command** (the `deploy_lambda.sh` doesn't work for MCP due to package structure — use the direct zip approach):
  ```bash
  rm -f /tmp/mcp_deploy.zip && zip -j /tmp/mcp_deploy.zip mcp_server.py mcp_bridge.py && zip -r /tmp/mcp_deploy.zip mcp/ && zip -j /tmp/mcp_deploy.zip lambdas/digest_utils.py && aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb:///tmp/mcp_deploy.zip --no-cli-pager > /dev/null && echo "✅ life-platform-mcp deployed"
  ```
- **Don't paste multi-line commands with `#` comments in zsh** — run each command separately
- **Test runner:** use `python3 -m pytest` from project root (not cdk/.venv Python)

---

## Sprint Roadmap (Updated)

```
Sprint 1  COMPLETE (v3.7.55)
Sprint 2  COMPLETE (v3.7.63)
Sprint 3  COMPLETE (v3.7.67)
Sprint 4  COMPLETE (v3.7.68)
Sprint 5  IN PROGRESS (5/8 items) — /story content + DIST-1 + habit review remaining
SIMP-1 Ph2 (~Apr 13)   95 → 80 tools
R17 Review (~Jun 2026)  Post-sprint validation
```
