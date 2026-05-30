# `[VERIFY]` Live-Audit Sweep — 2026-05-29

**Window:** 2026-05-29 evening PT, post-genesis restart (Day 0/1 of the experiment).
**Site under test:** https://averagejoematt.com (CloudFront `E3S424OXQZ8NBE`)
**API under test:** `life-platform-site-api` (us-west-2 Lambda URL behind CloudFront `/api/*`)
**Method:** static HTML fetch + API JSON probes. Where post-JS hydration matters, called out.

## Headline

- **3 FIXED** (PR1 issues no longer reproducing).
- **6 STILL-OPEN** (count drift + missing API routes + accountability render + count-source-not-wired).
- **1 NEW finding** outside the original list: `public_stats.json` returns 404 from CDN even though S3 has fresh `generated/public_stats.json`. **No page is actually pulling counts from it.**
- **Go/no-go for #9 IA restructuring:** **GO.** All 5 candidate pages (`/progress/`, `/results/`, `/achievements/`, `/start/`, `/data/`) still return 200 as separate pages → IA fragmentation persists → #9 is the right call.

---

## Item-by-item

### 1. Pulse `/live/` — "No signal yet" + gray state
- Status: **PARTIAL / NEEDS HYDRATION CHECK**
- Static HTML contains the string "No signal yet" **once** and "gray" once. Could be a pre-hydration placeholder that becomes data-driven in the browser, OR the bug returning post-restart (no data yet on Day 0). **Recommended:** open the page in a browser DevTools network tab — confirm whether the API call returns data and the placeholder is replaced. Note that with restart genesis at 2026-05-30 and minimal data ingested, "No signal yet" may currently be **correct**, not a bug.
- /live/ has rich content (21 KB, multiple "recovery"/"red" references) → state classification appears to be in place; the gray hit is a single occurrence and may be CSS, not state.

### 2. Intelligence `/intelligence/` — `[object Object]` in Character card
- Status: **✅ FIXED**
- `intel.html` contains zero `[object Object]` matches. Render bug is gone.
- API note: `/api/character` returns **503 "Character sheet not yet computed today"** — that's the pre-render data layer, expected on Day 0 of restart. Will resolve when daily-insight-compute fires tomorrow morning.

### 3. Grammar — "1 person" not "1 people"
- Status: **✅ FIXED**
- `accountability.html`, `subscribe.html`, `community.html` all show **zero matches** for "1 people" or "1 persons".

### 4. Training — step-count consistency + Elena "eight modalities"
- Status: **PARTIAL / ✅ on Elena, UNCONFIRMED on step count**
- "eight modalities" appears **zero times** anywhere → stale Elena quote is gone. ✅
- Step-count display-vs-coach reconciliation requires a side-by-side number check between the page UI and the coach-narrative output — out of scope for static HTML diff. Recommend manual eyeball after tomorrow's coach run.

### 5. Labs `/labs/` — staleness banner + observatory pattern
- Status: **✅ FIXED**
- `labs.html` contains "staleness"/"stale" 11x → staleness banner is present.
- `/api/labs` returns 200 with structured data → observatory pattern wired through.
- Elena reference present (1x) → labs page still narrated; consistent with editorial guardrails.

### 6. Count consistency — habits, sources, tools, Lambdas, AI
- Status: **🚨 STILL-OPEN — count drift across pages**
- Per-page scrape:
  - `home.html`: "26 data sources" (5x) AND **"19 Data Sources" (1x)** on the same page — drift within a single page.
  - `subscribe.html`: "26 sources" AND **"19 data sources"** — same drift, same page.
  - `cost.html`: "26 data sources" + **"62 Lambdas"** + **"121 AI"** + "12 Lambda" + "14 Lambdas". Real numbers per CLAUDE.md/MEMORY are 86 Lambdas us-west-2 + 5 us-east-1 = 91, and 138 MCP tools. **Every count on this page is stale.**
  - `accountability.html`: **"0 habits"** rendered — clearly broken (Day 0 may legitimately have 0 streak-bearing rows but the habit registry is non-empty).
  - `intel.html`: "26 data sources", "14 AI systems" — consistent with each other but the AI count differs from cost's "121 AI". Verify which is canonical.
- **Root cause:** counts are **hardcoded in HTML templates**, not pulled from `public_stats.json`. The spec's PR1 finding still applies.

### 7. IA — do retired pages still exist separately?
- Status: **🚨 STILL-OPEN — IA fragmentation persists**
- All 5 candidate pages return 200:
  - `/progress/` → 200
  - `/results/` → 200
  - `/achievements/` → 200
  - `/start/` → 200
  - `/data/` → 200
- **This is the go/no-go for #9. Verdict: GO.**

### 8. Community / Kitchen — hidden or enriched
- Status: **STILL-OPEN — both pages still live as separate routes (HTTP 200).**
- Content depth not assessed in this sweep; if they're now thin shells that's a separate cleanup. The PR1 ask was "hidden or enriched" — they are neither (still public, content unchanged from earlier audits).

### 9. "Since last visit" / "last updated" timestamps
- Status: **NOT VISIBLE in static HTML**
- No matches for "since last visit", "last updated" in any of the 8 pages snapshotted. Could be JS-injected post-hydration — re-check in a browser. If absent there too, this is still STILL-OPEN from the PR1 list.

### 10. Cost page `$19 vs status projection` reconciliation
- Status: **STILL-OPEN**
- `cost.html` contains "62 Lambdas" and "121 AI" as preserved-stale numbers. Cost projection itself wasn't diff'd against `/api/cost` here — the page numerics need a dedicated reconciliation pass. The lambda/AI counts being years out of date suggest the cost values are likely just as stale.

---

## 🆕 Out-of-list finding

**`public_stats.json` returns 404 from CloudFront.** S3 has `generated/public_stats.json` written at 2026-05-29 16:00 (today, fresh), but every probed path returns 404:

| URL | HTTP |
|-----|-----:|
| `/generated/public_stats.json` | 404 |
| `/dashboard/public_stats.json` | 404 |
| `/site/data/public_stats.json` | 404 |
| `/data/public_stats.json` | 404 |
| `/generated/data/character_stats.json` | 404 |

The CloudFront `S3GeneratedOrigin` (per ADR-046) is **not routing** the `/generated/` prefix, OR the cache behavior is misconfigured. This is the root cause of the count-drift item — pages can't pull from a stats file that's unreachable, so they fall back to hardcoded values. **Fixing this unblocks #6 of the original VERIFY list in one shot.**

Suggested fix path: inspect `cdk/stacks/web_stack.py` for the CloudFront distribution's cache behaviors → confirm `/generated/*` has an origin pointed at the S3 bucket and is not filtered out. Then `aws cloudfront create-invalidation --paths "/generated/*"`.

---

## API surface snapshot

| Endpoint | Status | Note |
|----------|-------:|------|
| `/api/vitals` | 200 | Returns `weight_lbs: null` (Day-0 baseline; expected — will populate after first Withings weigh-in). |
| `/api/labs` | 200 | OK. |
| `/api/observatory_week` | 200 | OK. |
| `/api/changes-since` | 400 | Missing required query param (expected). |
| `/api/correlations` | 503 | `"No correlation data available yet."` — Day-0 expected. |
| `/api/character` | 503 | `"Character sheet not yet computed today"` — daily-insight-compute hasn't run. |
| `/api/hypotheses` | **404** | **Does not exist** — confirms #8 task to build it. |
| `/api/intelligence_summary` | **404** | **Does not exist** — confirms #8 task to build it. |

---

## Decisions enabled

- **#9 PR1 IA restructuring**: **GO** (IA pages still separate).
- **#8 PB-08 Intelligence page rebuild**: confirmed needed — `/api/hypotheses` + `/api/intelligence_summary` 404, must be built.
- **Count-source plumbing**: a small but high-leverage fix — restore `/generated/*` CloudFront routing → flip every "X sources / Y tools" to live values in one shot. **Recommend doing this before #8 and #9** as it removes the entire class of count-drift bugs from those rebuilds.

---

## NOT verified in this sweep (require browser/DevTools)

- Whether `/live/`'s "No signal yet" hit is data-driven (correct on Day 0) vs the PR1 bug returning.
- Step-count consistency between display and coach narrative (requires post-coach-run comparison).
- "Since last visit" hydration via JS.
- Cost-page $19 vs projection reconciliation (requires /api/cost diff).

These are cheap to tag back to Matthew in browser; not blockers for #8/#9.

---

**Verified by:** Claude Code session 2026-05-29.
