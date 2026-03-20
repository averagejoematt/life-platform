# Life Platform — Project Plan

> Living document. For completed work and version history, see CHANGELOG.md / CHANGELOG_ARCHIVE.md.
> Last update: 2026-03-20 (v3.7.82 — R17 Architecture Review conducted (A-). 13 findings, 6 board decisions. Sprint 6 (R17 Hardening) created with 18 items. Platform cost approved to increase ~$13→~$20.40/month for WAF + separate API key. See docs/SPRINT_PLAN.md.)

---

## Active Priorities

### P0 — Completed (v3.7.15)
All P0 items from Architecture Review #8 are resolved.

---

## Backlog — Prioritized

### Tier 1 — Do Next (30 days) — all complete ✅

### Tier 2 — Near-Term (60 days) — all complete ✅

### Tier 3 — Strategic (90 days) — all complete ✅

### Website Strategy Review (2026-03-18, v3.7.75) — see WR items below

| ID | Item | Status |
|----|------|--------|
| WR-01 through WR-13 | Stats, OG, sitemap, 404, disclaimers, sparklines, brief widget, /ask/ frontend, RSS, story prompts, trend arrays, AI brief, /api/ask backend | ✅ All done (v3.7.75–76) |
| WR-14 | **Write /story page content** — 5 chapters | ⬜ Distribution gate — Matthew only |
| WR-15 | **Before/during photos** | ⬜ Matthew only |
| WR-16 | Dual-path navigation | ✅ Done (v3.7.76) |
| WR-17 | Dynamic social cards (Lambda@Edge) | ⚠️ Partial — Function URL 403 TBD |
| WR-18 | "Build Your Own" guide/course MVP | ⬜ Gated on /story + 10 weeks data |
| WR-19 | Press page on /about | ✅ Done (v3.7.76) |
| WR-20 | Video: morning brief recording | ⬜ Matthew only |
| WR-21–23 | Self-host fonts · scroll animations · biology noindex | ✅ All done (v3.7.76) |
| WR-24 | Subscriber gate on /ask/ | ✅ Done (v3.7.80/82) |

---

## Operational Efficiency Roadmap (2026-03-20)

> Stack-ranked by ROI. Derived from analysis of all project conversation history.
> Goal: reduce friction, accelerate development velocity, improve code quality.

| Rank | ID | Item | Effort | Status |
|------|------|------|--------|--------|
| 1 | OE-01 | **Adopt Claude Code for dev sessions** — eliminate cd/chmod/paste friction, auto-iterate on errors, full repo context without handover reads | 2hr setup | ⬜ |
| 2 | OE-02 | **Shell aliases + project Makefile** — `lp` alias, `lpd`, `lpc` shortcuts, `make deploy-mcp`, `make test`, `make commit` | 15min | ⬜ |
| 3 | OE-03 | **Tool surface management** — create build-mode (LP+FS+AWS only) vs planning-mode tool configs. Disconnect unused MCP tools per session type. | 10min/session | ⬜ |
| 4 | OE-04 | **Pin stable docs as Project Knowledge** — ARCHITECTURE.md, SCHEMA.md, DECISIONS.md as auto-loaded project context. Reserve handovers for session state only. | 15min | ⬜ |
| 5 | OE-05 | **Terminal anti-pattern fixes** — disable AWS CLI pager (`aws configure set cli_pager ""`), always use `bash script.sh` not `./script.sh`, never paste multi-line with `#` comments | 5min | ⬜ |
| 6 | OE-06 | **Local test-before-deploy discipline** — `make test` before every `make deploy`. Catch missing modules, bad imports, broken signatures pre-production. | Ongoing | ⬜ |
| 7 | OE-07 | **Expand operational memory** — commit anti-patterns to memory proactively on first encounter (not after 2nd/3rd). Focus on "things that break every few weeks." | Ongoing | ⬜ |
| 8 | OE-08 | **Use Deep Research for technical decisions** — complement Board of Directors (qualitative judgment) with Deep Research (quantitative data, benchmarks, current best practices) | Per-decision | ⬜ |
| 9 | OE-09 | **Consolidate session-end documentation** — audit FEATURES.md, USER_GUIDE.md, MCP_TOOL_CATALOG.md for overlap. Reduce 8+ doc updates to essential 3-4. | 1hr | ⬜ |
| 10 | OE-10 | **Local dev environment standardization** — pinned Python venv with `requirements-dev.txt`, consistent `pip install` without `--break-system-packages`. Consider Docker dev container. | 1hr | ⬜ |

---

## Board Summit Roadmap (2026-03-16)

### Synthesized Priority Stack (Top 15)

| Rank | ID | Feature | Champion | Status |
|------|-----|---------|----------|--------|
| 1 | BS-01 | Essential Seven Protocol | Clear | ✅ Sprint 1 done |
| 2 | BS-02 | Website Hero Redesign | Moreau | ✅ Sprint 1 done |
| 3 | BS-03 | Email Capture + Weekly Signal | Kim / Marcus | ✅ Sprint 1 done |
| 4 | BS-04 | Pre-Computed Composite Scores | Priya | ✅ Done (ADR-025) |
| 5 | BS-05 | AI Confidence Scoring | Henning | ✅ Sprint 1 done |
| 6 | BS-06 | Habit Cascade Detector | Clear / Anika | Backlog (~May 2026) |
| 7 | BS-07 | Website API Layer | Marcus | ✅ Sprint 2 done |
| 8 | BS-08 | Unified Sleep Record | Omar / Huberman | ✅ Sprint 2 done |
| 9 | BS-09 | ACWR Training Load Model | Attia / Jin | ✅ Sprint 1 done |
| 10 | BS-10 | Meal-Level CGM Response Scorer | Patrick / Anika | Backlog (~June 2026) |
| 11 | BS-11 | Transformation Timeline (Website) | Moreau / Kim | ✅ Done (v3.7.68) |
| 12 | BS-12 | Deficit Sustainability Tracker | Norton / Attia | ✅ Done (v3.7.67) |
| 13 | BS-13 | N=1 Experiment Archive (Website) | Patrick / Kim | ✅ Done (v3.7.65) |
| 14 | BS-14 | Multi-User Data Isolation Design | Yael / Omar | ✅ Done (v3.7.68) |
| 15 | BS-15 | Board of Directors Interactive Tool | Chen / Kim | Backlog |

### Board Technical Roadmap

All Tier 1 (Sprint 1–4) items complete. See SPRINT_PLAN.md for full inventory.

**Tier 2 additions (90-180 Days):**
- BS-T2-1/BS-14: Multi-User Isolation Design ✅ Done (v3.7.68)
- BS-T2-2: Biomarker Trajectory Engine (data-gated ~2028+)
- BS-T2-3: DEXA-Anchored Composition Model (needs DEXA #2)
- BS-T2-5: Chronicle → Newsletter Pipeline ✅ Done (v3.7.67)
- BS-T2-6: Decision Journal Analytics (50+ decisions needed)
- BS-T2-7: Experiment Results Auto-Analysis (5+ experiments needed)

**Tier 3 additions (180-365 Days):** BS-T3-1 Auth · BS-T3-2 Data Source Abstraction · BS-T3-3 AI Personalization · BS-T3-4 Compliance · BS-T3-5 Real-Time Streaming (~Sep 2026) · BS-T3-6 Multi-Tenant DDB (user count >10)

---

## Board Summit #2 Roadmap (2026-03-17)

> Focus: Distribution + Website + Behavior Change

### Website Roadmap (12 pages live as of v3.7.82)

| # | Page | Purpose | Status |
|---|------|---------|--------|
| 1 | `/` (Home) | Transformation story hero — live weight, progress bar, Chronicle excerpt | ✅ Live |
| 2 | `/story` | Deep origin narrative — emotional anchor | ✅ Structure live · **Content pending (Matthew)** |
| 3 | `/live` | Transformation Timeline — interactive weight chart | ✅ Live |
| 4 | `/journal` | Weekly Signal newsletter + data essays + build logs | ✅ Live (evolve) |
| 5 | `/experiments` | N=1 Experiment Archive with case studies | ✅ Live |
| 6 | `/character` | Character Sheet — 7-pillar radar chart | ✅ Live (evolve) |
| 7 | `/explorer` | Correlation Explorer — 23-pair Pearson matrix | ✅ Live |
| 8 | `/biology` | Genome Risk Dashboard — 110 SNPs | ✅ Live (noindex) |
| 9 | `/platform` | Platform architecture — "how I built this" | ✅ Live (evolve) |
| 10 | `/ask` | Ask the Platform — AI Q&A on live data (3 anon / 20 sub q/hr) | ✅ Live (v3.7.80) |
| 11 | `/board` | "What Would My Board Say?" — 6 AI personas lead magnet | ✅ Live (v3.7.80) |
| 12 | `/subscribe` | Email list landing page | ✅ Live |
| 13 | `/about` | Brief bio, professional context, press section | ✅ Live (v3.7.72) |
| — | `/tools` | Free interactive tools: sleep calc, habit audit | Later (S2-T2-2 backlog) |

### Design Language (Ava Moreau)
- Background: `#0D1117` · Text: `#E6EDF3` · Accent: `#F0B429`
- Data positive: `#2EA98F` · Data negative: `#E85D5D` · Secondary: `#8B949E`
- Typography: Inter (headlines) · JetBrains Mono (data/code)

### Commercialization
- Wedge: AI Health Coaching Email ($19-49/month). Infrastructure built. Needs audience first.
- Path 3 (Content/Media) elevated — fastest to first dollar, no extra engineering.
- Per-user Opus cost ~$1.80/month — model routing essential before multi-user.

### Next Summit Trigger
Board Summit #3: 500 subscribers OR 90-day journey milestone (2026-05-22), whichever comes first.

---

## Completed Items (Recent)

| ID | Item | Version | Date |
|----|------|---------|------|
| R17 | Architecture Review #17 — grade A-. 13 findings, Sprint 6 created. | v3.7.82 | 2026-03-20 |
| v3.7.82 | In-memory rate limiting for ask + board_ask — stopped AccessDeniedException alarm flood | v3.7.82 | 2026-03-20 |
| v3.7.81 | Nav + footer standardised across all 12 pages — /story/ promoted to primary nav | v3.7.81 | 2026-03-19 |
| v3.7.80 | WR-24 subscriber gate on /ask/ · S2-T2-2 /board/ page · sprint plan cleanup | v3.7.80 | 2026-03-19 |
| Sprint 1–4 | 30 Board Summit features shipped — see SPRINT_PLAN.md for full inventory | v3.7.55–68 | Mar 2026 |
| R16 | Architecture Review #16 — grade A | v3.7.47 | 2026-03-15 |
| R13 | Architecture Review #13 conducted (B+/A-) — 15 findings | v3.7.29 | 2026-03-14 |
| PROD-1 | CDK migration (8 stacks) | v3.4.0 | 2026-03-10 |
| SEC-1 | Per-function IAM roles (43 dedicated) | v3.4.0 | 2026-03-10 |

---

## Architecture Review History

| # | Date | Version | Grade | Key Findings |
|---|------|---------|-------|-------------|
| R17 | 2026-03-20 | v3.7.82 | A- | 13 findings, 6 board decisions. Public endpoint hardening. Sprint 6 created. |
| R16 | 2026-03-15 | v3.7.47 | A | 6 findings. CI/CD activation. Google Calendar retirement cleanup. |
| R15 | 2026-03-15 | v3.7.43 | A | 6 Low findings (doc drift). Platform in steady-state. |
| R14 | 2026-03-15 | v3.7.40 | A | 8 findings. MCP canary + X-Ray tracing. Security hardening. |
| R13 | 2026-03-14 | v3.7.29 | B+/A- | 15 findings. No CI/CD (#1 risk), correlation n-gating, no PITR drill. 30-60-90 roadmap. |
| R12 | 2026-03-15 | v3.7.25 | A- | Validator S3 bug, 4 partitions unwired, composite_scores stale. All resolved. |
| R11 | 2026-03-15 | v3.7.24 | A | Engineering strategy. All items resolved. |
| R10 | 2026-03-15 | v3.7.23 | A | Double-warmer, Calendar pre-auth handler. All resolved. |
| R9 | 2026-03-14 | v3.7.22 | A | tools_calendar cold-start, n-gated correlations. All 21 items resolved. |
| R8 | 2026-03-13 | v3.7.15 | A- | COST-B secret drift, webhook auth broken. |
| R1–R7 | 2026-02-28–03-11 | various | — | See `docs/reviews/` |

---

## Key Metrics

| Metric | Current | Target | Notes |
|--------|---------|--------|-------|
| MCP tools | 95 | ≤80 (SIMP-1 Phase 2) | Phase 2 gated ~Apr 13 |
| Lambdas | 49 (CDK) + 1 Lambda@Edge (manually managed) | — | site-api + email-subscriber CDK-managed in us-east-1 |
| CloudWatch alarms | 49 | — | |
| Monthly cost | ~$13 (→ ~$20.40 post-R17 hardening) | <$25 | WAF +$7, API key secret +$0.40 approved |
| Active secrets | 9 (→ 10 after R17-04) | — | webhook-key + google-calendar + api-keys deleted |
| IC features live | 16 of 31 | — | IC-29 + IC-30 deployed v3.7.67 |
| Data sources | 19 | — | google_calendar retired (ADR-030) |
| Architecture review grade | A- | A | R17 grade A-. R18 targeting post-DIST-1 (~June 2026). |
| Email subscribers | 0 | 500 (6 months) | Subscribe backend live. Distribution is #1 priority. |
| Website pages live | 12 | — | /ask/ + /board/ added v3.7.80 |
