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
2. Run: `python3 tests/visual_qa.py --screenshot`
3. Read the JSON report output and summarize:
   - Total pages checked
   - Pages with failures (list each with the failure reason)
   - Any stale text detected ("Launching April", "Coming Soon", "TODO")
   - Any blank canvas elements (charts not rendering)
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

Page-to-API mapping:
- /glucose/ → /api/glucose_overview, /api/glucose_trend, /api/meal_glucose
- /sleep/ → /api/sleep_detail
- /training/ → /api/training_overview
- /nutrition/ → /api/nutrition_overview
- /mind/ → /api/mind_overview
- /physical/ → /api/vitals
- /story/ → /api/journey
- /pulse/ → /api/pulse

### Output format
Summarize results as a checklist:
- [pass] or [FAIL] for each check
- For failures, include what was expected vs what was found
- End with a recommended action if any failures exist
