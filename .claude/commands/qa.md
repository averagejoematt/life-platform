Run a QA sweep of averagejoematt.com to check for broken pages, stale data, and rendering issues.

## Arguments: $ARGUMENTS

## Instructions

Parse `$ARGUMENTS` to determine the scope. Default to "quick" if no arguments.

### Mode: quick (default, no args)
1. Run: `bash deploy/smoke_test_site.sh`
2. WebFetch these API endpoints and verify each returns valid JSON with recent dates (today or yesterday):
   - `https://averagejoematt.com/api/vitals`
   - `https://averagejoematt.com/api/character`
   - `https://averagejoematt.com/api/pulse`
3. Report any failures, stale data (dates older than yesterday), or HTTP errors.

### Mode: `full`
1. Run everything from "quick" mode above.
2. Run: `python3 tests/visual_qa.py --screenshot --ai-qa`
   (Playwright sweep of the v4 surfaces — renders, the cockpit pillar interaction,
   responsive overflow — then Claude/Bedrock semantic vision QA of each screenshot.
   Drop `--ai-qa` to skip the AI layer / Bedrock calls. Needs `playwright install chromium`.)
3. Read `qa-screenshots/report.json` and summarize:
   - Total pages checked; pages with failures (each with the reason)
   - Broken API calls (e.g. a 4xx the page requested) and any JS errors
   - Stale text ("ships after April", "Coming Soon", "TODO") or blank sections
   - The per-page AI verdict (`ai_verdict`: severity + summary) — high = a real render
     problem; warnings on med/low; sparse-data states are correctly judged "ok"
4. If failures are found, offer to fix them.

### Mode: `api`
Only run step 2 from "quick" mode — just the API freshness checks. Also check these additional endpoints:
- `https://averagejoematt.com/api/training_overview`
- `https://averagejoematt.com/api/nutrition_overview`
- `https://averagejoematt.com/api/sleep_detail`
- `https://averagejoematt.com/api/glucose_overview`
- `https://averagejoematt.com/api/mind_overview`
For each, verify the response has data and dates are within the experiment window (April 1, 2026 onward).

### Mode: page path (e.g. `/glucose/`, `/sleep/`, `/training/`)
1. WebFetch `https://averagejoematt.com{path}` and check:
   - Page returns 200
   - No "undefined", "NaN", or "null" visible in data sections
   - No "Loading..." text stuck on screen
   - Content sections are present (not empty divs)
2. Identify the relevant API endpoint(s) for that page and WebFetch them to check data freshness.

Page-to-API mapping: **derive it from THE page registry** — `tests/qa_manifest.py`
(#1426; the `api_deps` facet per page, plus `tests/site_review_bindings.py` for
secondary endpoints). Do not maintain a mapping here. Quick lookups:
```bash
python3 tests/qa_manifest.py --emit paths          # every live page
python3 -c "import sys; sys.path.insert(0,'tests'); from qa_manifest import PAGES_BY_PATH; print(PAGES_BY_PATH['/data/glucose/']['api_deps'])"
```
(The pre-#1426 hand mapping here listed pre-v4 slugs like /glucose/ — 301s now.)

### Output format
Summarize results as a checklist:
- [pass] or [FAIL] for each check
- For failures, include what was expected vs what was found
- End with a recommended action if any failures exist
