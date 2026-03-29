# Session Handover — 2026-02-28 Session 36: Habit Intelligence + P0 Ingestion Fix

**Platform version:** v2.47.1  
**MCP tools:** 94 → 97  
**Session duration:** ~3 hours  
**Trigger:** "Life Platform"

---

## What shipped this session

### v2.47.0 — Habit Intelligence (65-Habit Registry + Tier-Weighted Scoring)

**Habit Registry** deployed to DynamoDB PROFILE#v1:
- 65 habits across 3 tiers: T0 (7 non-negotiable, 3x weight), T1 (22 high priority, 1x), T2 (36 aspirational, 0.5x)
- Full metadata per habit: scientific mechanism, personal context (`why_matthew`), synergy groups, applicable days, scoring weight
- 5 vices with streak tracking, 8 synergy groups
- Written via `generate_habit_registry.py` → 9 batch DynamoDB updates

**Daily Brief v2.47.0** (3011 lines, +389):
- Tier-weighted composite scoring replaces binary percentage
- Registry-aware vice streaks (90-day lookback, applicable_days aware)
- Rich HTML: T0 red/green per habit, T1 individual habits, vice 🔥 streak chips, T2 collapsed
- AI enrichment: missed T0 by name + `why_matthew`, synergy alerts
- `store_habit_scores()` writes daily to new `habit_scores` DynamoDB partition
- Deployed and live (10:00 AM PT brief tomorrow will be first registry-powered one)

**3 New MCP Tools** (in `mcp/tools_habits.py` + `mcp/registry.py`):
1. `get_habit_registry` — inspect registry with tier/category/vice/synergy filters
2. `get_habit_tier_report` — tier-level adherence trends from habit_scores partition
3. `get_vice_streak_history` — vice streak time series with relapse detection
- **Requires Claude Desktop restart** to load

### v2.47.1 — P0 Ingestion Fix + Process Improvements

**5 of 6 API ingestion Lambdas** failed after prior session's hardening deploy:
- 4 handler mismatches (strava, habitify, eightsleep, withings)
- Garmin: missing deps + IAM gap + macOS binary mismatch
- Withings: cascading OAuth token expiry

**All fixed and verified green:**
| Lambda | Fix | Backfill |
|--------|-----|----------|
| strava | Handler → `lambda_function.lambda_handler` | 4 days |
| habitify | Handler fix | Feb 27 |
| eightsleep | Handler fix | Feb 27 |
| garmin | Linux deps + IAM `Query` + config cold start | Feb 27 |
| withings | OAuth re-auth via new `fix_withings_oauth.py` | Feb 27 |

**Freshness checker** updated: removed Hevy, added garmin + habitify. Deployed.

**PIR written:** `docs/PIR-2026-02-28-ingestion-outage.md` with 7 process improvements:
- Mandatory post-deploy smoke test (invoke + grep ERROR + auto-rollback)
- Handler consistency guard (verify filename matches handler config)
- Cross-platform build enforcement (`--platform manylinux2014_x86_64`)
- IAM policy co-location with code changes
- Deploy manifest tracking handler/deps/IAM per Lambda
- Freshness checker accuracy (per-source thresholds)
- Pre-deploy checklist for multi-Lambda changes

**Apple Health:** Confirmed working — last sync 45KB payload (well under 10MB limit). 4-hour cadence keeps payloads small.

---

## Files modified/created

| File | Action |
|------|--------|
| `lambdas/daily_brief_lambda.py` | Modified (+389 lines, v2.47.0) |
| `lambdas/freshness_checker_lambda.py` | Modified (removed Hevy, added garmin+habitify) |
| `mcp/tools_habits.py` | Modified (+220 lines, 3 new tools) |
| `mcp/registry.py` | Modified (+90 lines, 3 tool registrations) |
| `deploy/fix_garmin_deps.sh` | Created |
| `deploy/deploy_daily_brief_v247.sh` | Created |
| `deploy/deploy_freshness_checker.sh` | Created |
| `setup/fix_withings_oauth.py` | Created |
| `docs/PIR-2026-02-28-ingestion-outage.md` | Created |
| `docs/CHANGELOG.md` | Updated (v2.47.0, v2.47.1) |
| `docs/PROJECT_PLAN.md` | Updated (version, daily brief, completed table) |
| `docs/SCHEMA.md` | Updated (habit_scores partition, habit_registry in profile) |

---

## Known issues

| Issue | Severity | Notes |
|-------|----------|-------|
| **MCP tools need restart** | Low | 3 new habit tools require Claude Desktop restart to load |
| **No historical habit_scores** | Low | habit_scores partition starts populating tomorrow. For trending, backfill past 90 days via daily brief backfill mode |
| **Garmin gap** | Low | 2026-01-19 → 2026-02-23 (app sync issue). Daily Lambda fills going forward |
| **Deploy manifest not yet created** | Medium | PIR recommends `deploy/MANIFEST.md` — not built this session |

---

## Next session priorities

1. **Backfill historical habit_scores** — run daily brief in backfill mode for past 90 days to populate habit_scores partition for trending tools
2. **Deploy manifest** — create `deploy/MANIFEST.md` per PIR recommendation (handler, deps, IAM per Lambda)
3. **Smoke test template** — add standardized invoke+rollback block to all deploy scripts
4. **MCP tool verification** — restart Claude Desktop, test 3 new habit tools
5. **Weekly digest v2** — update weekly digest to consume habit_scores records (tier adherence trends, vice streaks in weekly email)

---

## Context files for next session

Read these before starting:
- `docs/PIR-2026-02-28-ingestion-outage.md` (process improvements to implement)
- `docs/CHANGELOG.md` (v2.47.0 and v2.47.1 entries)
- `docs/SCHEMA.md` (habit_scores partition schema)
- This handover file

---

## Rollback commands

```bash
# Daily Brief v2.47.0 → backup
aws lambda update-function-code --function-name daily-brief --zip-file fileb://lambdas/daily_brief_lambda_BACKUP.zip --region us-west-2

# Garmin → last working zip not preserved (rebuilt from source). Re-run deploy/fix_garmin_deps.sh if needed.

# Freshness checker → manual (restore hevy line, remove garmin+habitify)
```
