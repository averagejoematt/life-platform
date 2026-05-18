# V2 Audit — Website + Product + Developer Experience

**Scope:** static site, public site behavior, MCP usage analytics, SES engagement, DX (tests, CI/CD, deploy, docs, repo hygiene).
**Date:** 2026-05-17. **Repo state:** v1 work uncommitted (115 modified files), HEAD = v7.20.0.

---

## Executive bullets (full summary in caller message)

1. **Site perf is fine.** CDN p50 TTFB ~45ms (cached) / ~120ms (cold). Total static budget ~277 KB before gzip; not a problem.
2. **Three real test failures** (i2 layer-drift, i9 DLQ=63, i11 reconciliation stalled) — all flagged silent ops bugs, not flaky tests.
3. **MCP usage telemetry is honest but the data is brutal**: 11 of 135 tools (8%) used in last 30 days. Average 113 MCP invocations/day, dominated by 2 tools (`get_todoist_snapshot` 20, `get_sources` 16).
4. **SES has zero open/click tracking** — no engagement signal exists for the daily-brief or weekly-digest. Recurring v1 promise; not shipped.
5. **CLAUDE.md drift**: claims layer v41 (actual v50), 115 MCP tools (actual 135), 19 sources in subscriber email (the doc + Lambda copy disagree with 26).
6. **CI flake8 is broken in a way the gate doesn't catch**: 3,981 style findings (~12 MB log noise) AND one real `F821 undefined name 'yesterday_str'` that would fire production NameError in the sick-day branch of freshness_checker.
7. **Repo hygiene: ~5,800 files across 9 "abandoned" dirs**, including a stray `HANDOVER_LATEST copy.md` (mode 600), 3 LEDGER specs at root (~100 KB Mar 30), 4 INTELLIGENCE_LAYER specs in docs/ (~135 KB Apr 7), 52 patches.
8. **RSS feed is 8 weeks stale** (lastBuildDate 2026-03-22, today 2026-05-17). Sitemap has 47 URLs but no `<lastmod>`.
9. **Homepage has no `<h1>`** (only a screen-reader-hidden absolutely-positioned one), no canonical link, no images at all (so the missing `alt=` count is moot).
10. **Subscribe flow is well built** — double opt-in, blocked-domain list, 48h token expiry, no hard-delete on unsub. Confirm path correctly handles already-confirmed and expired tokens.

---

## WEBSITE FINDINGS

### W1 [MEDIUM] Homepage has no proper `<h1>` (visually) — SEO + a11y miss
**Evidence:** `/tmp/homepage.html:526` — `<h1 style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;">` (visually hidden). All other headings are styled divs.
**Action:** Promote `.h-hero__title` (`/tmp/homepage.html:124-132`) to a real `<h1>`. Remove the visually-hidden one.
**Effort:** XS (10 min). **ROI:** SEO ranking signal + screen-reader hierarchy. Low risk.

### W2 [MEDIUM] No `<link rel="canonical">` on any page sampled
**Evidence:** grep returned 0 on homepage, chronicle, about, live, story. CloudFront serves the site at apex; if you ever attach `www.` or staging mirror, Google will see dupes.
**Action:** Add `<link rel="canonical" href="https://averagejoematt.com{path}/">` to base template + each top-level page.
**Effort:** S (1 hour, 47 pages from sitemap). **ROI:** SEO insurance, prevents future dupes.

### W3 [HIGH] RSS feed is 8 weeks stale
**Evidence:** `curl https://averagejoematt.com/rss.xml` → `<lastBuildDate>Sun, 22 Mar 2026 07:06:30 +0000</lastBuildDate>`; latest item Mar 5. Today: May 17. Meanwhile site sitemap is fresh.
**Action:** Find the RSS generator (likely a Lambda or build script) and wire it back into the chronicle publication path. If chronicle posts.json updates, RSS should rebuild.
**Effort:** S (find + rewire). **ROI:** restores the only feed-based engagement channel; RSS readers will resubscribe.

### W4 [MEDIUM] Sitemap has no `<lastmod>` entries
**Evidence:** `curl ... sitemap.xml | grep -c '<lastmod>'` → 0. 47 `<loc>` entries, all with `<changefreq>` and `<priority>` but no `lastmod`.
**Action:** Inject `<lastmod>` from S3 object `LastModified` for each page when generating sitemap. Skip if no generator exists; one-shot static refresh acceptable.
**Effort:** S. **ROI:** Google honors lastmod for crawl prioritization.

### W5 [LOW] `<title>` for chronicle is generic
**Evidence:** `/tmp/chronicle.html` `<title>Chronicle — Matthew</title>` — but OG title is "The Measured Life — Chronicle". Pages should align.
**Action:** Standardize title format across all top-levels: `{Page} | The Measured Life — averagejoematt.com`.
**Effort:** XS. **ROI:** brand consistency in search results.

### W6 [MEDIUM] Inline JS is ~22 KB unminified across 15 `<script>` blocks
**Evidence:** `/tmp/homepage.html` 1366 lines, 21,563 bytes of inline JS in 15 blocks. CSP currently allows `'unsafe-inline'` script.
**Action:** Move repeatable code (API fetchers, count-up wiring, masthead) to `/assets/js/homepage.js` (cacheable, gzipped, can drop `'unsafe-inline'` script-src later). Inline only the small bootstrap snippets.
**Effort:** M (a few hours, careful testing). **ROI:** -22 KB on first-visit, +cache hit on repeat. Unblocks tightening CSP (one of the v1 P2.3 follow-ups). Risk: medium — the inline code touches lots of DOM IDs.

### W7 [LOW] All 40 sampled internal links return 200 — no broken links
**Evidence:** broken-link scan above (every page in nav + sitemap). No 404s.
**Action:** None. Note as positive baseline.

### W8 [LOW] OG image is 10 KB PNG; WebP variant promised in v1 not shipped
**Evidence:** `curl -I .../assets/images/og-home.png` → image/png, 10101 bytes. v1 P-W2 promised WebP fallback + lifecycle on OG bucket. CloudFront serving PNG only.
**Action:** Generate `og-home.webp` alongside PNG in OG Lambda; add `og:image:type` triplet (PNG primary for Slack/LinkedIn, WebP secondary). Lifecycle on `generated/og/` is OUT OF SCOPE for this leg — AWS agent's task.
**Effort:** S. **ROI:** ~30% smaller social-card payload; bandwidth nit.

### W9 [LOW] Color tokens look correctly contrasted; no obvious WCAG fails
**Evidence:** `site/assets/css/tokens.css:160` — `--c-text-secondary: #4a6050; /* 5.6:1 ✅ */` (annotated). The site has pre-computed contrast ratios.
**Action:** None. Run actual axe-core in CI eventually but no fires today.

### W10 [LOW] Subscribe form is keyboard-accessible
**Evidence:** `/tmp/subscribe.html` has `<input type="email" id="email" autocomplete="email">` (label-for-input on `<label for="email">` — present in real subscribe.html under `site/subscribe/index.html`). `<button>` (not `<div onclick>`). All good.
**Action:** None.

### W11 [MEDIUM] Subscribe Lambda calls `table.query` with a `FilterExpression` for confirm-token lookup
**Evidence:** `lambdas/email_subscriber_lambda.py:292-300` — Comment says "DDB has no GSI — acceptable given low subscriber volume at launch; add GSI if >10K subs". Today this is fine — but it scans the entire `SUBSCRIBERS_PK` partition on every confirm click.
**Action:** No change today. **Track**: when subscribers >2,000, switch to storing `pk=USER#matthew#SUBTOKEN#{token}, sk=email#{hash}` as a secondary item rather than adding a GSI (consistent with ADR-005).
**Effort:** Deferred. **ROI:** Future scalability.

### W12 [LOW] Welcome email correctly handles already-confirmed + expired token + non-destructive unsub
**Evidence:** `lambdas/email_subscriber_lambda.py:280-330` — `handle_confirm` covers expired → redirect with `error=token_expired`; already-confirmed → `confirmed=already`. Unsub writes `status=unsubscribed` (Raj directive). Disposable-domain blocklist (`_BLOCKED_DOMAINS`) prevents most SES bounce damage.
**Action:** None. Confirmed working as designed.

### W13 [HIGH] CSP still permits `script-src 'unsafe-inline'`
**Evidence:** Response header on every page: `script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net`.
**Action:** Phase 1: move all 15 inline scripts to `/assets/js/homepage.js` per W6. Phase 2: drop `'unsafe-inline'` from script-src, switch to nonces or hashes for the small bootstrap blocks that remain.
**Effort:** M (depends on W6 completion). **ROI:** XSS reduction. Risk: medium — break the dashboard hydration if any inline code is missed.

---

## PRODUCT / USAGE ANALYTICS

### P1 [CRITICAL] Only 11 of 135 MCP tools used in last 30 days
**Evidence:**
- Per-tool 30-day Sum from `LifePlatform/MCP::ToolInvocations` (output of `/tmp/mcp_usage.py`):
  ```
  get_todoist_snapshot              20
  get_sources                       16
  get_board_of_directors             4
  list_experiments                   3
  end_experiment                     2
  get_journal_entries                2
  get_freshness_status               1
  get_vice_streaks                   1
  get_weight_loss_progress           1
  list_challenges                    1
  get_coach_track_record             0
  ```
- `mcp/handler.py:90-105` confirms `_emit_tool_metric` is called on every dispatch path (success + timeout + exception). So 124 tools with NO metric == 124 tools called zero times.
- MCP Lambda total: 3,388 invocations in 30 days = 113/day average. The discrepancy (3,388 invocations but only ~51 per-tool counts above) = freshness/canary calls + tool-discovery/list calls that don't dispatch a named tool.

**Action:** Bulk-delete or merge ~80 unused MCP tools. Concrete first pass:
- Tools_lifestyle.py (3,400 LOC) and tools_correlation.py (1,553 LOC) — flag every tool not in `/tmp/mcp_tools_with_metrics.txt` for deletion after a 60-day grace period (re-check 2026-07-17).
- Specifically zero-use tools as of today: 124 tools across `tools_health`, `tools_strength`, `tools_cgm`, `tools_labs`, `tools_correlation`, `tools_social`, `tools_calendar` (retired but still in registry per ADR-030), `tools_memory`.
- Concrete deletion candidates with high confidence (each is either an unused alias, an artifact of an old design, or duplicated by simpler tool):
  - `tools_calendar.py` — 352 LOC, ADR-030 retired Google Calendar integration; the file still exists in `mcp/` per ls. Delete.
  - `mcp/tools_correlation.py` (1,553 LOC) — pick top 5 actually-needed correlations, delete the rest.
  - Every `compare_*_periods` variant that's never been called.
**Effort:** L (week of careful pruning, regression risk). **ROI:** Massive cognitive load reduction; faster MCP Lambda cold start; smaller registry to maintain. Cost savings near zero (Lambda is right-sized), value is in DX + correctness.

### P2 [HIGH] SES has zero engagement tracking — daily-brief / weekly-digest open rate is unknown
**Evidence:** `aws sesv2 list-configuration-sets --region us-west-2` → `"ConfigurationSets": []`. Zero open/click destinations exist.
**Action:** (1) Create configuration set `life-platform-emails`. (2) Wire CloudWatch event destination for `Open` + `Click` + `Bounce` + `Complaint`. (3) Update `daily_brief_lambda` + `weekly_digest_lambda` + `subscriber_onboarding_lambda` to set `ConfigurationSetName=life-platform-emails` on `SendEmail`. (4) Inject pixel + UTM-tagged links.
**Effort:** S (1-2 hours setup, requires SES IAM permission update). **ROI:** Unlocks "is anyone reading this?" — without this signal, every email-content investment is blind. Caveat: privacy-conscious mail clients block pixels; expect 40-60% reported opens.

### P3 [MEDIUM] Daily-brief / weekly-digest novelty: data-blocked
**Evidence:** `aws dynamodb query` for `pk=USER#matthew, sk begins_with COACH#` returned 0 items (sample command above). The actual narrative storage is in a different partition shape than `COACH#` — couldn't locate without more time. Coach state likely stored under different SK (e.g., `DATE#YYYY-MM-DD#COACH#sleep`).
**Action:** AI-leg agent should sample coach narratives from the correct partition and assess. Out of scope for this leg.

### P4 [LOW] MCP daily invocations show clear usage signal (113/day)
**Evidence:** Last 7 days: 110, 107, 113, 104, 110, 107, 137. Consistent baseline.
**Action:** None. Healthy.

---

## DEVELOPER EXPERIENCE

### D1 [HIGH] 3 integration tests failing — each surfaces a real ops issue
**Evidence (run from repo root):**
- `test_i2_lambda_layer_version_current` — **7 Lambdas on layer v43, current is v50**: `daily-brief, weekly-digest, life-platform-freshness-checker, anomaly-detector, character-sheet-compute, daily-metrics-compute, daily-insight-compute`. Layer drift means these run with old `retry_utils`, no token telemetry, no Phase 3.6 auth_breaker, no Phase 4.2 numeric helpers.
- `test_i9_dlq_empty` — **DLQ has 63 messages**. At least one Lambda is silently failing.
- `test_i11_data_reconciliation_running` — **life-platform-data-reconciliation last ran 2026-05-11 00:30 UTC, ~6 days ago**. Expected every 48h.
**Action:**
- D1a: Re-deploy the 7 stale Lambdas. `for fn in daily-brief weekly-digest life-platform-freshness-checker anomaly-detector character-sheet-compute daily-metrics-compute daily-insight-compute; do bash deploy/deploy_lambda.sh $fn lambdas/...; done` (find correct source per fn from `ci/lambda_map.json`).
- D1b: Inspect DLQ messages, identify the failing producer, drain.
- D1c: Investigate why data-reconciliation EventBridge schedule hasn't fired since 2026-05-11. Possibly disabled or schedule changed.
**Effort:** D1a S, D1b S, D1c S. **ROI:** High — D1a closes a v1 follow-up; D1b/c are silent-failure detection (the "running but not working" class v2 was explicitly asked to find).

### D2 [HIGH] CI's strict flake8 gate would fire today on a real `F821 undefined name`
**Evidence:**
- `flake8 lambdas/ mcp/ --select=E9,F63,F7,F82` → `lambdas/freshness_checker_lambda.py:185:37: F821 undefined name 'yesterday_str'`. Reading the file: `now` is defined but `yesterday_str` is referenced inside the `if _sick_suppress:` branch with no prior assignment.
- CI definition (`.github/workflows/ci-cd.yml:78`): `flake8 lambdas/ mcp/ --count --select=E9,F63,F7,F82 --show-source --statistics` (this is the hard-fail line).
- **This means CI on next push to main will fail.** Unless freshness_checker isn't in lambda_map.json (it is — it's in the live Lambdas list).
**Action:** Edit `lambdas/freshness_checker_lambda.py:181-186` — add `yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')` before the logger.info call.
**Effort:** XS (5 min). **ROI:** Unblocks CI deploys + fixes a real NameError that would fire when sick-day suppression runs.

### D3 [MEDIUM] Total flake8 findings: 3,981 (mostly style)
**Evidence:** category breakdown: 1,552 E221 (multiple spaces before operator), 544 E701 (multiple statements on one line), 475 F401 (unused imports), 272 E231, 194 E501, etc. The 6 new Phase 4 shared modules are nearly clean: `request_validator.py` has 4 minor (1 unused import, 3 f-string-no-placeholder).
**Action:**
- (a) Add `autopep8 --select=E221,E231,E251,E272 --in-place --recursive lambdas/ mcp/` as a one-shot cleanup commit (~2,400 findings auto-fixable).
- (b) Add `flake8 --select=F401` to a `make lint-strict` target and grep-clean unused imports.
- (c) The 4 findings in `request_validator.py` are easy to fix.
**Effort:** S. **ROI:** Reduces noise so the real F821 from D2 doesn't hide.

### D4 [MEDIUM] pytest-cov not installed locally; CI installs it but doesn't store coverage report
**Evidence:** `python3 -c "import pytest_cov"` → ModuleNotFoundError. CI has `pip install pytest pytest-cov` but the run command `python3 -m pytest tests/test_shared_modules.py -v --tb=short` (single test file, no `--cov`). No coverage gate.
**Action:** (a) `pip install pytest-cov` locally. (b) In CI, expand to `python3 -m pytest tests/ --cov=lambdas --cov=mcp --cov-report=xml --cov-report=term-missing --tb=no -q` and upload XML as artifact. Set fail threshold to `--cov-fail-under=60` (start lenient).
**Effort:** S. **ROI:** Real coverage visibility; protects against the silent-regression class. Risk: low.

### D5 [LOW] Test suite: 1,240 passed, 3 failed, 41 skipped, 10 xfailed in 29 seconds
**Evidence:** see full output above. Slowest 5: `test_i10_mcp_lambda_responds` 14.0s, `test_i3_spot_check_lambda_invocability` 4.1s, `test_i13_freshness_checker_returns_valid_data` 2.8s, `test_i1_lambda_handlers_match_expected` 2.2s, `test_i2_lambda_layer_version_current` 0.8s. All 5 are AWS-integration tests; unit tests sub-100ms.
**Action:** Mark integration tests with `pytest.mark.integration` (already done — see warning) and register the mark in `pytest.ini` to silence the warning. Run `pytest -m 'not integration'` in CI for fast unit cycle; gated `pytest -m integration` after deploy.
**Effort:** XS. **ROI:** Faster developer feedback loop (2s instead of 29s for `pytest`).

### D6 [LOW] CI has no concurrency group — concurrent pushes can race
**Evidence:** `.github/workflows/ci-cd.yml` has no `concurrency:` block. Two pushes in quick succession will run two deploy chains.
**Action:** Add at top of workflow:
```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false
```
**Effort:** XS. **ROI:** Prevents deploy races. Low risk.

### D7 [LOW] CI doesn't cache pip
**Evidence:** Each job does `pip install flake8`, `pip install pytest pytest-cov boto3 botocore`, etc. No setup-python `cache: 'pip'`.
**Action:** Add `cache: 'pip'` to each `actions/setup-python@v5` step. Requires a `requirements*.txt` or pip-compile lockfile (currently `requirements-dev.txt` exists).
**Effort:** XS. **ROI:** -20s per CI run.

### D8 [LOW] Deploy is fast — no friction
**Evidence:** `time bash deploy/build_layer.sh` → 0.06s real. `deploy/deploy_lambda.sh` has good guardrails (validates source, checks for MCP-shaped builds, supports `--extra-files`, sets up rollback artifact in S3).
**Action:** None. This is in a good place.

### D9 [HIGH] `CLAUDE.md` drift — three load-bearing claims are wrong
**Evidence (file: `CLAUDE.md`):**
- "...deployed as a layer (currently **v41**)" — actual v50 per build script + integration test. Off by 9 versions.
- "**115 tools** across 26 domain modules" — actual 135 per `grep -c '"name":' mcp/registry.py`. ARCHITECTURE.md says 127. Three numbers in three files.
- "13 Lambda functions pull from APIs on EventBridge schedules" — actual mix is 8 framework + 6 exempt per ADR-056 = 14 ingestion Lambdas.
**Action:** Edit CLAUDE.md:
- Layer version → `currently v50` and add a note: "Source of truth: `aws lambda list-layer-versions --layer-name life-platform-shared-utils --query 'LayerVersions[0].Version'`."
- Tool count → `135 tools (auto-counted by tests/test_wiring_coverage.py)`.
- Ingestion count → `14 ingestion Lambdas (8 SIMP-2 framework + 6 pattern-exempt per ADR-056)`.
**Effort:** XS. **ROI:** Stops every new audit/agent from inheriting stale numbers.

### D10 [MEDIUM] `docs/ARCHITECTURE.md` line 3 has the same drift — also says "127 MCP tools" and "shared layer v50"
**Evidence:** correct on layer v50, off-by-8 on tools.
**Action:** Single edit to match real 135. Same fix as D9.
**Effort:** XS. **ROI:** Consistency.

### D11 [MEDIUM] ADR coverage looks complete but no auto-check for "silent supersession"
**Evidence:** ADR-001 → ADR-057. ADR-053 explicitly supersedes parts of ADR-046 (S3 KMS). ADR-057 closes items from the v1 audit. No mechanism prevents future ADR-058 from silently overriding ADR-005 (single-table no-GSI) without flagging.
**Action:** Add `tests/test_decisions_consistency.py` that scans `docs/DECISIONS.md` for `Supersedes: ADR-NNN` headers and asserts each cited ADR has a matching `Superseded by:` annotation. Lightweight; catches drift.
**Effort:** S. **ROI:** Future-proofing. Low priority.

---

## REPO HYGIENE

### R1 [HIGH] Duplicate `HANDOVER_LATEST copy.md` in docs/ — delete
**Evidence:** `ls -la docs/HANDOVER_LATEST*.md` →
- `-rw------- HANDOVER_LATEST copy.md` (mode 600, 11,419 bytes, May 3)
- `-rw-r--r-- HANDOVER_LATEST.md` (228 bytes, May 3 — likely a pointer)
**Action:** `git rm "docs/HANDOVER_LATEST copy.md"`. The 11KB version is the stale dup with weird permissions.
**Effort:** XS. **ROI:** Removes confusion.

### R2 [MEDIUM] Three LEDGER/SPEC specs at repo root from March
**Evidence:**
- `LEDGER_SPEC_FINAL.md` (33 KB, Mar 30) — superseded by working code
- `LEDGER_SPEC_v02.md` (26 KB, Mar 30) — superseded by v_FINAL
- `SPEC_CHARACTER_ENGINE_v1.1.0.md` (46 KB, Mar 30) — likely shipped; spec is now `lambdas/character_engine.py`
**Action:** `git mv` all three to `docs/archive/specs-pre-launch/` then update CLAUDE.md to point there. If truly dead, delete after one PR cycle.
**Effort:** XS. **ROI:** Cleaner root; signals what's live vs. historical.

### R3 [MEDIUM] Four INTELLIGENCE_LAYER spec versions in docs/
**Evidence:** `INTELLIGENCE_LAYER.md` (49 KB), `INTELLIGENCE_LAYER_V2_SPEC.md` (36 KB), `INTELLIGENCE_LAYER_V2_1_SPEC.md` (28 KB), `INTELLIGENCE_LAYER_V2_2_SPEC.md` (23 KB). All Apr 7. The current state is whatever shipped; the v2_*_SPEC files are evolution history.
**Action:** Move V2*, V2_1*, V2_2* to `docs/archive/intelligence-layer/`. Keep only `INTELLIGENCE_LAYER.md` (current) at top level. Add a NOTE at top of the kept file: "History in docs/archive/intelligence-layer/".
**Effort:** XS. **ROI:** Future readers don't have to guess which one's current.

### R4 [MEDIUM] Abandoned dirs without README (5 of 9)
**Evidence (no README, oldest contents):**
- `datadrops/` — 96 files, newest May 17 (still in use?)
- `handovers/` — 342 files, newest May 3
- `seeds/` — 14 files, newest Apr 6
- `demo/` — 18 files, newest Mar 6
- `qa-screenshots/` — 34 files, newest May 3
- `show_and_tell/` — 2,201 files, newest Mar 6 (!!)
- `content/` — 1 file, newest Mar 4
- `setup/` — 19 files, newest Mar 30
- `ci/` — 3 files, newest May 16 (this is LIVE — has lambda_map.json)

`show_and_tell/` is by far the biggest accumulator: 2,201 files, untouched since March, no README.

**Action (bulk-delete safe candidates):**
- `git rm -rf show_and_tell/` (move to S3 archive if needed first; 2,201 files / no README / 2 months stale = high confidence dead).
- `git rm -rf content/` (1 file Mar 4 — abandoned).
- `git rm -rf demo/` (18 files Mar 6 — abandoned).
- `git rm -rf qa-screenshots/` (move to docs/archive/ if needed).
- Add README.md to `datadrops/`, `handovers/`, `seeds/`, `setup/`, `ci/` explaining purpose + retention policy.

**Single-bulk-delete command (run from repo root, after confirmation):**
```bash
git rm -rf show_and_tell/ content/ demo/ qa-screenshots/
git rm "docs/HANDOVER_LATEST copy.md"
git mv LEDGER_SPEC_FINAL.md LEDGER_SPEC_v02.md SPEC_CHARACTER_ENGINE_v1.1.0.md docs/archive/specs-pre-launch/
git mv docs/INTELLIGENCE_LAYER_V2_SPEC.md docs/INTELLIGENCE_LAYER_V2_1_SPEC.md docs/INTELLIGENCE_LAYER_V2_2_SPEC.md docs/archive/intelligence-layer/
```
**Effort:** S (one PR, careful review). **ROI:** ~2,250+ files removed from grep/find scope. DX win.

### R5 [LOW] 52 patches in `patches/` — most likely irrelevant
**Evidence:** `patches/` has 52 .py/.sh files dated up to 2026-05-17, README present. Many look like one-off historical patches (`apply_v240_patch.py`, `patch_alcohol_sleep_tool.py`). v2 prompt explicitly asks: "Patches in patches/ (51 files) — same question. Some are already-irrelevant; identify and delete with a single ADR documenting the cleanup."
**Action:** Identify patches >60 days old + already-applied; delete those. Keep a `patches/INDEX.md` documenting what each remaining one is for. Out-of-scope as a single PR for this leg — schedule as a Phase 8 cleanup.
**Effort:** M. **ROI:** Reduces cognitive load.

---

## v1 PROMISES — DRIFT CHECK

| v1 promise | Status today | Evidence |
|---|---|---|
| JSON-LD on index + chronicle | KEPT | `/tmp/homepage.html:21-52`, `/tmp/chronicle.html` |
| Security headers (HSTS, CSP, X-Frame, Referrer, X-Content-Type) | KEPT | `curl -I` shows all present |
| Subscriber double opt-in path | KEPT | `lambdas/email_subscriber_lambda.py:180-330` |
| Rate limiting (P2.1) | KEPT | `lambdas/site_api_lambda.py:2781, 3682` emit `RateLimitHit` metric |
| Layer v50 rolled out to all Lambdas | **DROPPED — 7 still on v43** | test_i2_lambda_layer_version_current fail |
| MCP tool usage analysis | **DROPPED then partially kept** | EMF metrics emit (handler.py:196) but no audit done — surfaced here in P1 |
| SES open-rate analysis | **DROPPED — no tracking exists** | `list-configuration-sets` empty |
| Test coverage report | **DROPPED** | CI doesn't store/gate coverage |
| CI flakiness check | **DROPPED** | No metric, no concurrency group |
| OG image WebP variant + lifecycle | **DROPPED** | PNG only on CDN |
| Email dark mode CSS | **NOT VERIFIED** | Didn't sample email HTML; out of scope here |
| Site API pagination | CLOSED PER ADR-057 | Acceptable closure |

**Summary:** v1 shipped 5 of 12 web/product/DX promises and dropped 6. ADR-057 formally closed 1.

---

## SINGLE BULK-CLEANUP RECOMMENDATION

When ready to execute (post-v2 plan approval), one PR can do:
1. Delete `show_and_tell/ content/ demo/ qa-screenshots/` (~2,250 files).
2. Delete `docs/HANDOVER_LATEST copy.md`.
3. Move root LEDGER + SPEC files to `docs/archive/specs-pre-launch/`.
4. Move docs/INTELLIGENCE_LAYER_V2*_SPEC.md to `docs/archive/intelligence-layer/`.
5. Fix `lambdas/freshness_checker_lambda.py:185` undefined `yesterday_str` (D2).
6. Update CLAUDE.md layer v41→v50, tools 115→135, ingest 13→14 (D9).
7. Update docs/ARCHITECTURE.md tool count 127→135.
8. Re-deploy 7 stale Lambdas to layer v50 (D1a).

Net change: ~2,260 files deleted, 4 files edited, 7 Lambdas re-deployed. Risk: low (every step reversible via git revert + redeploy_lambda.sh rollback artifact).
