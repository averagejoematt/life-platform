# Handover — 2026-03-07 — QA Smoke Test + Blog Cleanup

## Session Summary

Built and deployed the QA smoke test system. Debugged 4 reported issues.
Fixed 2 bugs (blog links, dashboard threshold). Diagnosed 2 as correct behavior.
Cleaned up blog: removed ghost DynamoDB record, restored correct article content.
Added Daily Brief compute refactor to roadmap.

---

## What Was Built

### QA Smoke Test System (v2.81.0)
- **`lambdas/qa_smoke_lambda.py`** — 31st Lambda. Runs at 10:30 AM PT daily. 5 check categories:
  - Data Freshness: 7 required + 3 optional DynamoDB sources
  - Output Files: dashboard/data.json (4h), clinical.json (26h), buddy/data.json (26h)
  - Score Sanity: date, readiness, sleep, weight, HRV, glucose, hydration, day_grade, character_sheet
  - Blog Links: all week-*.html hrefs in index resolve in S3
  - Avatar Assets: all 15 sprites (5 tiers × 3 frames) present
- **`tests/smoke_test.py`** — CLI version, color output, `--quick` and `--date` flags
- **`tests/validate_links.py`** — Blog-only link checker with orphan detection and `--fix` mode
- **`deploy/deploy_qa_smoke.sh`** — Fixed role: `lambda-weekly-digest-role` (not `life-platform-lambda-role`)
- **EventBridge:** `cron(30 18 ? * * *)` = 10:30 AM PT daily

### Blog Cleanup
- Deleted ghost DynamoDB chronicle record: `sk=DATE#2026-03-04`, "The Week Everything Leveled Up (And Nothing Changed)"
- Rebuilt `blog/index.html` from scratch — hero: The Empty Journal, archive: Before the Numbers
- Restored `blog/week-02.html` with correct full article text (The Empty Journal)
- All blog patches in `patches/`: `remove_chronicle_record.py`, `rebuild_blog_index.py`, `restore_week02.py`

---

## Issue Diagnosis

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| ❌ dashboard/data.json stale (2h) | Evening refresh fires at 5 PM PST (1 AM UTC) pre-DST; at 7:30 PM that's 2.5h stale | Raised threshold to 4h in QA |
| ❌ blog broken links week-0.0.html / week-2.0.html | Stale index written by older chronicle code serializing week_number as float | Rebuilt index from scratch |
| ✅ Weight 290.28 (expected 288.4) | Correct — brief uses `yesterday` as lookback end; 288.4 weigh-in was today, appears tomorrow | No fix needed |
| ✅ Hydration warning despite apple_health passing | Correct — record exists (freshness pass) but water field genuinely sparse (known HAE gap) | No fix needed |

---

## Roadmap Addition

**#53 — Daily Brief compute refactor** added to Tier 3.
- Brief currently does 30 DynamoDB fetches + inline computation (TSB, HRV avgs, weight delta, sleep debt, habit scores, readiness)
- Correct pattern: new `daily-metrics-compute` Lambda at 9:40 AM writes `computed_metrics` record; brief reads only
- Follows established `character-sheet-compute` pattern
- Fixes dual `day_grade` write paths

---

## Platform State

- **Version:** v2.81.0
- **Lambdas:** 31 (added `life-platform-qa-smoke`)
- **MCP tools:** 124 (unchanged)
- **Blog:** 2 live posts — week-00.html (Prologue), week-02.html (The Empty Journal)
- **QA:** Live, firing daily at 10:30 AM PT, emailing to awsdev@mattsusername.com

---

## Next Up

1. **Set BRITTANY_EMAIL** — command in previous handover, just needs real address
2. **Reward seeding** — prerequisite for Character Sheet Phase 4 completion
3. **Google Calendar** — #2 North Star gap, Board rank #9
4. **Daily Brief compute refactor** (#53) — when ready to tackle tech debt
