Run a QA sweep of averagejoematt.com to check for broken pages, stale data, and rendering issues.

## Arguments: $ARGUMENTS

## Instructions

Parse `$ARGUMENTS` to pick a mode. **Default to `quick` if no arguments** (preserves the
pre-#1449 behavior). A leading `/`-path argument (e.g. `/data/glucose/`) selects the
single-page mode.

**Every page and API set below DERIVES from THE page registry — `tests/qa_manifest.py`
(#1426) — never a hand list in this file** (`tests/test_qa_skill_modes.py` enforces).
Useful derivations:

```bash
python3 tests/qa_manifest.py --emit paths      # every live page
python3 tests/qa_manifest.py --emit coverage   # the coverage rollup (#1446)
# API endpoints for a tier (the api_deps facet — tier 1 = the flagship doors):
python3 -c "import sys; sys.path.insert(0,'tests'); from qa_manifest import MANIFEST; \
  print('\n'.join(sorted({d for p in MANIFEST if p['tier']<=1 for d in p['api_deps'] if d.startswith('/api/')})))"
```

**First, in every mode: read + report the QA-depth dial (#1452)** so the report states
what depth the automated estate is currently running at:

```bash
aws ssm get-parameter --name /life-platform/qa-level --region us-west-2 \
  --query Parameter.Value --output text 2>/dev/null || echo "standard (param unset/unreadable — fail-open default)"
```

Values: `full | standard | lean | off` — see `docs/RUNBOOK.md` § QA Depth Dial. The dial
scales the standalone/scheduled QA workflows only; deploy-gating QA is structurally
exempt. If the dial is `lean` or `off`, say so prominently — the scheduled estate is
running shallow, so a manual `/qa full` matters more.

### Mode: `quick` (default, no args)
1. Run: `bash deploy/smoke_test_site.sh`
2. Derive the tier-1 (flagship-door) endpoints from the manifest's `api_deps` facet
   (one-liner above with `tier<=1`), then WebFetch each `https://averagejoematt.com{endpoint}`
   and verify it returns valid JSON with recent dates (today or yesterday; respect the
   nutrition ~24h-lag and pre-genesis semantics).
3. Report any failures, stale data, or HTTP errors.

### Mode: `tier1` — the deploy-gate shape (#1428)
Exactly what the deploy-time gates run — flagship doors only, deterministic + AI:
```bash
python3 tests/visual_qa.py --max-tier 1 --screenshot --ai-qa --ai-qa-max-tier 1
```
Then read `qa-screenshots/report.json` and summarize failures + `ai_verdict`s.

### Mode: `full`
1. Everything from `quick` above.
2. Run the full-surface sweep (all manifest pages with a `visual` def) + full AI-vision
   + reader-truth:
   ```bash
   python3 tests/visual_qa.py --screenshot --ai-qa --reader-truth
   ```
   (Needs `playwright install chromium`. Drop `--ai-qa` to skip Bedrock spend.)
3. Read `qa-screenshots/report.json` and summarize:
   - Total pages checked; pages with failures (each with the reason)
   - Broken API calls the pages requested and any JS errors
   - Stale text ("Coming Soon", "TODO") or blank sections
   - Per-page `ai_verdict` (severity + summary) — high = a real render problem;
     sparse-data states are correctly judged "ok"
4. If failures are found, offer to fix them.

### Mode: `mobile` — the iOS-Safari engine shape (#1434)
The weekly WebKit run, on demand (catches the backdrop-filter/position:fixed class
Chromium emulation cannot see):
```bash
python3 -m playwright install webkit   # once per machine
python3 tests/visual_qa.py --browser webkit --mobile --max-tier 2 --screenshot
```
Tier<=2 = flagship doors + live-data topic pages, iPhone-class profile (390x844,
dpr 3, touch). $0 Bedrock — deterministic only.

### Mode: `ai-review` — full-surface Claude-vision read
```bash
python3 tests/visual_qa.py --screenshot --ai-qa
```
The untiered AI-vision pass over every swept page (what the standalone workflow runs
Sundays). Summarize every non-"ok" `ai_verdict` with its screenshot path. Skips itself
with a SKIPPED-BY-BUDGET line at budget tier >= 1 (ADR-125) — report that honestly.

### Mode: `audit` — recompute the coverage map (#1450)
```bash
python3 scripts/qa_audit.py          # add --live for dial/budget/alarm-state reads, --json for machine output
```
Recomputes site/ vs manifest vs each sweep vs alarm coverage entirely from the repo and
reports uncovered surface + silent-skip states + hard drift (non-zero exit = a registry
or derivation break to fix now). Summarize: the coverage table, every drift line, and
anything newly uncovered. This replaces the annual archaeology dig — run it at the start
of any QA review.

### Mode: `api`
Derive the FULL endpoint set from the manifest (the union of `api_deps` across all
pages — same one-liner without the tier filter), WebFetch each, and verify the response
has data with dates inside the current experiment window (check the live genesis via
`/api/journey` — never assume a hardcoded date).

### Mode: page path (e.g. `/data/glucose/`, `/cockpit/`)
1. WebFetch `https://averagejoematt.com{path}` and check:
   - Page returns the manifest entry's expected `smoke` status
   - No "undefined", "NaN", or "null" visible in data sections
   - No "Loading..." text stuck on screen; content sections present
2. Look up the page's own endpoints in THE registry and check their freshness:
   ```bash
   python3 -c "import sys; sys.path.insert(0,'tests'); from qa_manifest import PAGES_BY_PATH; print(PAGES_BY_PATH['$PATH']['api_deps'])"
   ```
   (plus `tests/site_review_bindings.py` for secondary endpoints).

### Output format
Summarize results as a checklist:
- The QA-depth dial state first (and whether that shrinks the scheduled estate)
- [pass] or [FAIL] for each check; for failures, expected vs found
- End with a recommended action if any failures exist
