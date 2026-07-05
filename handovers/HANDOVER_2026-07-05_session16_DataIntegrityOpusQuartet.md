# HANDOVER — the data-integrity opus quartet: TDEE chain + HAE validation + Notion sync (3 of 4 shipped) — 2026-07-05 (session 16)

> **⚠️ A CONCURRENT SESSION ran in parallel** and merged much of the Now/Next site-ux +
> infra backlog to main during this session (visible in git log: **#378, #379, #382,
> #383, #389, #419, #470, #579, #580** and more — a11y, perf budget, weather-in-registry,
> the dual-plane guard, the sync_doc drift gate, coverage ratchet). **This handover covers
> ONLY this session's work (the opus data-integrity quartet).** That other work is real and
> live but not documented here — read its own wrap / the git log. Our changes were verified
> to coexist cleanly (all 47 of this session's tests pass on current main).

Session opened on "read memory + handover, prepare next," then Matthew directed: **"do all
opus items that don't have prereqs"** and **"you do merge and deploys"** (explicit up-front
authorization). Four opus items qualified; **three shipped end-to-end, the fourth (#581)
was deliberately deferred** — see the last section.

---

## What shipped (5 PRs, all merged + deployed + verified)

1. **#484 — Resurrect the TDEE/deficit chain** (PR #633 + follow-up #663). The chain was
   dead from a single field-name mismatch: MacroFactor ingest wrote the adaptive
   maintenance estimate to `expenditure_kcal`, but every reader looked for
   `tdee`/`tdee_kcal`/`expenditure` — names nothing wrote — so `tdee`/`deficit` served
   `null` everywhere. Fixed: ingest now also writes the canonical `tdee_kcal`;
   `_resolve_mf_tdee()` scans MF records newest-first across all name generations with
   honest provenance (`macrofactor_adaptive`); `daily_insight` + `hypothesis_engine`
   readers converged; the dead `weight_lbs = tdee_kcal` proxy deleted. **#663 follow-up:**
   live MF records currently carry NO `expenditure_kcal`, so added the labeled Mifflin
   estimate fallback (the acceptance's stated alternative) from the latest Withings weigh-in.
   **Live-verified:** `/api/nutrition_overview` → `tdee: 3623, source: estimate_mifflin,
   avg_deficit: 2116`. Deployed via `deploy_site_api.sh` (site-api).

2. **#483 — HAE webhook validation, units, cgm cadence, BP break** (PR #649). Four fixes to
   the path that actually delivers CGM/BP/steps: (X-3) `ingestion_validator.validate_fields`
   gates every merge at the `merge_day_to_dynamo` chokepoint — a critical hard-bound
   violation drops the day + trips the error alarm; (D-9) unit-aware water/weight/distance
   conversion; (D-3) `cgm_source` by median inter-reading cadence (≤10 min ⇒ CGM), fixing
   the UTC-truncated partial-day mislabel (verified against `cgm_readings/2026/05/22.json` —
   17 readings @ 5-min); (D-1) the stray separate-format BP `break`. **Deployed via
   `cdk deploy LifePlatformIngestion`** (see gotcha #1). HAE invoke → 200, no ImportError.

3. **#476 — Notion journal: sync edits, reconcile deletions, archive raw** (PR #664 +
   test-fix #666). `last_edited_time` OR-branch so >2-day-old edits re-ingest; stable
   page-id SKs (not positional `#seq` that re-homed enrichment); `_reconcile_deleted`
   removes Notion deletions + legacy `#seq` orphans per day; **raw S3 archive**
   (`raw/matthew/notion/YYYY/MM/DD-<page_id>.json`) so DDB isn't the only copy of the
   journal text; drift fixes (schedule, secret default, `source_registry` raw_layout).
   Deployed via single-file `deploy_lambda.sh` (notion has the layer). Invoke → 200, runs
   clean. **BUT the data-path can't be live-exercised: Notion API is returning 401** (see
   flags).

Shared layer stayed **v111** (no bump). The #483 cdk deploy incidentally reconciled all
ingestion lambdas from a stale **layer v109 → v111** (pre-existing drift). 28 new tests
across 3 files; doc `test_count` re-synced through the stacked-PR merges.

## Gotchas learned (load-bearing)

1. **HAE has NO shared layer** and bundles its siblings (`ingestion_framework`,
   `ingestion_validator`) via its CDK `from_asset("../lambdas")`. Its lambda_map entry
   lacked the `cdk_only` flag → a CI single-file hot-deploy would strip the siblings
   (`Runtime.ImportModuleError`, the #382 dual-plane hazard). **Marked it `cdk_only` and it
   now ships via `cdk deploy LifePlatformIngestion`.** Contrast: notion/whoop/garmin DO have
   the layer attached, so their siblings resolve from `/opt` and single-file deploy is fine.
2. **The doc-drift `test_count` trap compounds across stacked same-base PRs.** Each of my
   PRs synced `test_count` off its own base; after each merge advanced main, the next PR's
   value was stale → a merge-conflict on `site_api_common.py`'s PLATFORM_STATS every time.
   Fix each time: merge main into the branch, take either side, re-run
   `sync_doc_metadata.py --apply` (recomputes the true count), push.
3. **Import-time-frozen module globals make tests order-fragile.** `test_notion_sync_476`
   asserted `nl.S3_BUCKET == "matthew-life-platform"`, but that global freezes at
   notion_lambda import time — the full suite imported it earlier with a different env, so
   it read `'x'` and failed (green in isolation, red in the suite → Deploy skipped, main
   red). Fix: `monkeypatch.setattr(nl, "S3_BUCKET", ...)` — pin the global, don't trust env.
4. **CI Deploy is gated behind Unit Tests** — a red test skips Deploy entirely. My #476
   test failure meant notion never deployed on the merge run; the test-only fix (#666) then
   didn't include notion in the deploy matrix, so I deployed notion **manually**.

## Flags for Matthew

- **Notion API is 401** (expired token — circuit-breaker tripped 07:29, pre-existing, not
  my change). #476's code is deployed + imports clean, but the archive/reconcile **data-path
  is unverified live** until you refresh the Notion token (`setup`/secret rotation). Once
  the token's back, one scheduled run exercises + archives everything.
- **Two Claudes on one repo.** A concurrent session merged a large slice of Now/Next in
  parallel. Main was churny (several CI runs cancelled by the rapid cadence). Worth
  coordinating so sessions don't collide — especially on shared files (both of us touched
  `source_registry.py` and the status block).
- **The I22 site-version lag is red** across the lambda-only merges (site `version.json`
  behind main HEAD) — clears on the next **static-site deploy**, which the concurrent
  session's site-ux work will trigger. Not a real failure.
- **GitHub Pages** still enabled+public (carried from session 14/15, unactioned).

## What's next

- **#581 — Split evidence.js (DEFERRED, do attended).** The 4th opus item. Deferred for two
  converging reasons: (a) the handover has always said *do it attended* — a byte-identical
  refactor of a 3,000-line SPOF; (b) the concurrent session is **actively working the same
  site JS graph** (#579 a11y added `tabs.js`, #580 perf/font, #653) — splitting evidence.js
  now would collide head-on. **Do it once the site-ux churn settles, ideally in a worktree,
  with Matthew watching.** Unblocks #582 (chart contract v2).
- **#544 — Methods registry** (sonnet, Next) still the credibility artifact that unblocks
  #584. Not started.
- **Notion token refresh** → then confirm #476's archive lands in S3.
