# DPR-1 Remediation — Claude Code Execution Prompt

Read the following files in order before doing anything:

1. `handovers/HANDOVER_LATEST.md` — current platform state
2. `docs/reviews/DPR1_IMPLEMENTATION_BRIEF.md` — Phase 1 brief (21 items covering The Pulse + The Data pages)
3. `docs/reviews/DPR1_PHASE2_IMPLEMENTATION_BRIEF.md` — Phase 2 brief (13 items covering The Practice + Platform + Chronicle + Utility pages)

These briefs were produced by a Deep Page Review that captured and evaluated every page on averagejoematt.com. Each work item has: What, Why, Where (exact files), How (implementation spec), and Acceptance criteria.

---

## Execution Rules

1. **Work the Combined Priority Stack from the Phase 2 brief.** It sequences all 34 items across both briefs by effort size. Do XS items first (30 min batch), then S items, then M items.

2. **DPR-2.10 first among S items** — it ports the Start page's working narrative logic to the Pulse page and may resolve DPR-1.01 entirely. Investigate what endpoint/logic `site/start/index.html` uses for its pulse narrative feed, then apply the same to `site/live/index.html`.

3. **DPR-2.11 replaces DPR-1.04** — the dynamic Elena quotes pattern fix covers all observatory pages, making the individual Training page fix unnecessary.

4. **Follow the deploy convention**: write deploy scripts to `deploy/`, don't execute deploys directly. Use `deploy/deploy_lambda.sh` for Lambda deploys. Wait 10s between sequential deploys.

5. **Follow the MCP deploy rule**: Never register a tool in TOOLS dict without the implementing function existing. Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy.

6. **Follow the S3 deploy rule**: Never use `aws s3 sync --delete` against bucket root or `site/` prefix.

7. **Site changes**: For HTML/CSS/JS changes to `site/` pages, write the changes and prepare a deploy script that syncs the modified files to S3 and invalidates CloudFront (`E3S424OXQZ8NBE`).

8. **Lambda changes**: For changes to `lambdas/site_api_lambda.py` or other Lambdas, use `deploy/deploy_lambda.sh`.

9. **After completing each work item**: mark it done in a tracking comment at the top of the file you modified, e.g. `<!-- DPR-2.01 DONE -->`.

10. **At the end of the session**: update `CHANGELOG.md`, write a handover to `handovers/`, and update `HANDOVER_LATEST.md`.

---

## Quick Reference: Combined Priority Stack

### XS fixes (do all, ~30 min total):
- DPR-2.01: Intelligence page [object Object] fix (`site/intelligence/index.html`)
- DPR-2.02: Subscribe "1 people" → "1 person" (`site/subscribe/index.html`)
- DPR-2.04: Stack "19 data sources" → dynamic 26 (`site/stack/index.html`)
- DPR-2.05: Cost $19 vs $25.67 reconciliation (`site/cost/index.html`)
- DPR-2.09: Hide Kitchen from nav (`site/assets/js/nav.js` or `components.js`)
- DPR-1.05: Accountability "1 people" + nudge empty states (`site/accountability/index.html`)
- DPR-1.06: Habits count inconsistency + pull-quote attribution + DOW confidence (`site/habits/index.html`)
- DPR-1.07: Labs staleness warning banner (`site/labs/index.html`)
- DPR-1.08: Physical goal date confidence caveat (`site/physical/index.html`)
- DPR-1.09: Character pillar name truncation (`site/character/index.html`)

### S fixes (~2-3 hrs):
- DPR-2.10: Port Start page narrative to Pulse page (`site/start/index.html` → `site/live/index.html`) — **do first, may resolve DPR-1.01**
- DPR-1.02: Pulse state classification fix — gray=no data only (`lambdas/site_api_lambda.py` or compute layer)
- DPR-2.03: Recap weight delta — journey-start framing (`site/recap/index.html`)
- DPR-2.06: Ask page sample response (`site/ask/index.html`)
- DPR-2.07: Community page improvement (`site/community/index.html`)
- DPR-2.08: Discovery entry summaries (`site/discoveries/index.html`)
- DPR-1.03: Training step count data contradiction (investigate `lambdas/site_api_lambda.py`)
- DPR-1.10: Pulse first-time visitor context line (`site/live/index.html`)
- DPR-1.14: Pulse "since yesterday" deltas (`lambdas/site_api_lambda.py` + `site/live/index.html`)
- DPR-1.15: Pulse notable signal banner (`lambdas/site_api_lambda.py` + `site/live/index.html`)
- DPR-1.04: Training Elena Voss quote fix — **skip if doing DPR-2.11**
- DPR-1.12: Training empty section collapse (`site/training/index.html`)
- DPR-2.13: Platform count parameterization (grep + `site_constants.js`)

### M features (~4-6 hrs):
- DPR-2.11: Dynamic Elena Voss observatory quotes (all observatory pages + `wednesday_chronicle_lambda.py`)
- DPR-1.13: Key Recommendation callout pattern (all observatory AI coaching sections + `ai_expert_analyzer_lambda.py`)
- DPR-1.19: Explorer Discovery of the Week (`weekly_correlation_compute_lambda.py` + `site/explorer/index.html`)
- DPR-1.20: "Since your last visit" nav indicators (`site/assets/js/nav.js` + `site_stats_refresh_lambda.py`)
- DPR-1.11: Character heatmap early-data state (`site/character/index.html`)
- DPR-1.16: Character composite delta (`site/character/index.html` + `/api/character`)
- DPR-2.12: Merge Recap into Weekly Snapshots (`site/recap/` + `site/weekly/`)

### L projects (standalone sessions):
- DPR-1.21: Labs observatory full redesign (`site/labs/index.html` + `ai_expert_analyzer_lambda.py`)

---

Begin by reading the three files listed above, then start with the XS batch.
