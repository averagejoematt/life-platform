# Handover -- 2026-02-23 -- Roadmap: Exist.io + Notion Journal Added

## Session Summary
Two sessions this day. First session: infrastructure hardening (CloudTrail, CloudWatch alarms, log retention, Haiku retry logic -- all deployed, see previous handover). Second session: no AWS changes. Roadmap and architecture thinking for the two highest-priority new data sources: Exist.io (mood/energy/stress) and Notion journal (unstructured reflection -> structured P40 insight). PROJECT_PLAN.md fully rewritten to clean up prior encoding corruption and add new items.

---

## Decisions Made This Session

### Exist.io selected for mood/energy/stress tracking (item 8)
Chosen over Daylio (no API, CSV only), custom Lambda questionnaire (requires building input UX), and Apple Health mood (no API, too limited). Exist.io has a proper OAuth2 REST API at `developer.exist.io`, built-in mood tracking on a 1-9 scale, and custom numeric attributes for energy and stress at the same scale. $6.99/month.

Integration plan:
- OAuth Lambda authenticates Exist.io, token -> Secrets Manager `life-platform/exist-token`
- Lambda `exist-ingestion` polls `exist.io/api/2/attributes/with-values/` nightly at 9pm PT
- Fields: `mood`, `energy`, `stress` (all 1-9), `mood_note` (string)
- DynamoDB source: `exist`, same PK/SK pattern as all other sources
- 3 new MCP tools in v2.6.0: `get_mood_summary`, `get_mood_correlations`, `get_best_worst_days`

Unlocks: "what predicts a good day for you?" -- the single most important unanswered question in the platform.

### Notion selected for journal integration (item 9)
Chosen over Day One (no public REST API as of Feb 2026, Zapier integration "in development" but unshipped) and Obsidian (local markdown files, no API, requires launchd watcher + Mac to be on).

Notion wins on automation: full REST API, OAuth2, already connected to this Claude project. Lambda can poll automatically with zero manual steps.

Core design principle: write freely, structure automatically.
- User writes verbose unstructured entries in a Notion "Daily Journal" database (Date + Body properties)
- Nightly Lambda `notion-journal-ingestion` fetches entries updated in last 24hrs
- Each entry passed through Haiku with extraction prompt -> fixed JSON schema
- Extracted schema stored in DynamoDB source `journal`; raw text stored at separate SK `DATE#YYYY-MM-DD#journal#raw`

Haiku extraction schema: `mood_score`, `energy_level`, `stress_level`, `sentiment`, `key_themes[]`, `wins[]`, `challenges[]`, `p40_groups_mentioned[]`, `p40_relevant_notes`, `word_count`

3 new MCP tools in v2.7.0: `get_journal_summary`, `get_journal_p40_context`, `search_journal_themes`

Biggest impact: weekly digest Board of Advisors gains journal context -- coaches would know not just that HRV dropped but that you wrote about a stressful week at work.

Note: If Obsidian is preferred for writing, architecture is identical but Lambda watches an S3 drop folder instead of Notion API. Requires launchd to sync vault on file change. Viable but less reliable.

---

## Files Changed This Session
| File | Change |
|------|--------|
| `PROJECT_PLAN.md` | Full rewrite -- fixed all encoding corruption from prior sessions; added items 8 (Exist.io) and 9 (Notion journal) with full architecture specs; fixed QUICK WINS to correctly show A/C/D/F as done; updated Known Issues and Architecture Notes; updated Future Sources table |
| `handovers/handover-2026-02-23-roadmap-exist-notion.md` | NEW -- this file |

Note: `handovers/handover-2026-02-23-infrastructure-hardening.md` from earlier today remains the authoritative record for AWS changes in session 1.

---

## AWS State
No changes from session 1. All infrastructure from earlier today remains live:
- CloudTrail `life-platform-trail`: ACTIVE
- CloudWatch alarms on all 4 email Lambdas: INSUFFICIENT_DATA (will activate on first error)
- All 12 Lambda log groups: 30-day retention
- All 4 email Lambdas: Haiku retry logic deployed

---

## Next Logical Build Sessions

### Session: Exist.io integration (~3-4 hrs)
1. Sign up for Exist.io ($6.99/mo), set up account, start tracking mood/energy/stress for a few days
2. Create OAuth app at `developer.exist.io`
3. Write OAuth setup script (similar pattern to `setup_eightsleep_auth.py`)
4. Write `exist_ingestion_lambda.py` -- poll attributes/with-values/, write to DynamoDB source `exist`
5. Create IAM role, EventBridge schedule (9pm PT)
6. Add 3 MCP tools to mcp_server.py: `get_mood_summary`, `get_mood_correlations`, `get_best_worst_days`
7. Deploy and test

### Session: Notion journal integration (~4-6 hrs)
1. Create "Daily Journal" database in Notion (Date + Body properties)
2. Write a few entries to test
3. Write `notion_journal_ingestion_lambda.py`:
   - Notion API query for pages updated in last 24hrs
   - Haiku extraction call with schema prompt
   - DynamoDB write (raw + extracted)
4. Add 3 MCP tools: `get_journal_summary`, `get_journal_p40_context`, `search_journal_themes`
5. Inject journal context into weekly digest Board of Advisors section

### Other items still queued
- WAF rate limiting on MCP API Gateway (item E, ~1hr, ~$5/mo)
- Data completeness alerting (item 16, ~2hrs, high operational priority)
- DynamoDB batch optimization (154 get_item -> 2 batch_get_item calls in digest Lambdas)
- Caffeine timing vs sleep tool (item 2, data exists, just needs MCP tool)

---

## Architecture Context for Next Engineer
The Exist.io integration will be the 10th data source. It follows exactly the same pattern as all other ingestion Lambdas (IAM role per function, Secrets Manager for auth token, DynamoDB PK/SK pattern, EventBridge schedule). No new architectural patterns needed.

The Notion journal integration introduces one new pattern: dual-SK storage (raw text + extracted schema for the same date). This is the first source where DynamoDB stores both raw unstructured content and processed structured output. The raw text SK `DATE#YYYY-MM-DD#journal#raw` uses the `begins_with` query pattern already documented in ARCHITECTURE.md.

The Haiku extraction call in the journal Lambda follows the same `call_anthropic_with_retry()` pattern deployed in v2.5.2.
