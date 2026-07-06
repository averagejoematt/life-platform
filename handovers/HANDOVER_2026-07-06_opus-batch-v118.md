# HANDOVER — Opus backlog batch → layer v118 (3 issues merged + deployed) — 2026-07-06

> Two instructions: **"do all the appropriate open opus issues"** then **"I approve you
> to do all merges and deploys this session."** Shipped 3 of the milestone-prioritized
> opus issues end-to-end (code → PR → merge → deploy → live-verify), scoped-and-deferred
> #730, left the Attended/gated/large-feature opus issues for focused sessions. Single-
> threaded on `main`. **Main CI green.**

## What shipped (all merged + deployed + LIVE-verified)

| Issue | ADR | What | Merge |
|-------|-----|------|-------|
| **#737** | ADR-125 | budget-guard re-banded by **audience**: internal/dev AI (ensemble, coherence_semantic [was unlisted→defaulted tier-3, a real inversion], chronicle_editor) pauses tier 1; reader narrative (coach_narrative **1→2**, state_of_matthew 1→2, chronicle) tier 2; irreducible reader (website_ai, daily_brief_ai) tier 3 | PR #770 `d6f3420f` |
| **#738** | ADR-126 | hash-and-reuse coach generation briefs — new layer module `generation_cache.py` fingerprints the semantic brief (`system_prompt`+`user_message`, `_`-prefixed+timestamp keys stripped, Decimal→float), reuses the last gate-passed output on an exact match, skips Sonnet+gates. Honesty invariant: any semantic change (incl. `gap_days` ticking) busts the hash. Metric `GenerationSkippedUnchanged` | PR #771 `f4122316` |
| **#733** | — | per-post **share affordance** in `dispatches.js` (`dx-share-btn` → native share / clipboard copy of the crawlable permalink). ~80% of #733 was already done (RSS permalinks, subscribe CTA) | PR #772 `dd8d51a5` |

## Deploy (authorized: "all merges and deploys")

- **Layer v117 → v118** (`budget_guard.py` re-band + new `generation_cache.py`):
  `build_layer.sh` → `deploy/cdk_deploy.sh LifePlatformCore` (published v118) → verified
  118 live → `deploy/cdk_deploy.sh LifePlatformCompute LifePlatformEmail LifePlatformMcp
  LifePlatformWeb` → `deploy/deploy_site_api.sh` (auto-attaches; 117→118). Spot-verified
  daily-brief / coach-narrative-orchestrator / coach-memoir / life-platform-mcp /
  life-platform-site-api all on **118**.
- **Ingestion + Operational stay on v115 DELIBERATELY** (HAE gate — unchanged; reconcile
  WITH Matthew). **Consequence:** `coherence_sentinel` (Operational) still runs the old
  `budget_guard`, so the new `coherence_semantic` tier-1 pause is NOT active there yet —
  benign (fail-open), lands when the held stack is deployed.
- **`life-platform-site-api-ai` is on v115** (pre-existing — the last session left it
  there too). #737 left `website_ai`'s cutoff at tier 3 **unchanged**, so its behavior is
  not affected; no functional need to redeploy it.
- **Site synced** (`sync_site_to_s3.sh`): share button live, sitemap post URLs live,
  chronicle noscript dated list live. version.json == `e85198c9`.

## The deploy-verify catch (a real miss I'd mis-assessed)

#733's "posts in sitemap" AC was **NOT actually live**: `v4_build_sitemap.py` had the
machinery but was **never wired into the deploy** (`sync_site_to_s3.sh` ran only
`v4_build_rss.py`), so `site/sitemap.xml` had silently drifted post-less and the live
sitemap carried only the hubs. Fixed (`e85198c9`): ran the builder (4 `/journal/posts/
week-N/` URLs + a dated `<noscript>` list injected into `/story/chronicle/`) and **wired
`v4_build_sitemap.py` into `sync_site_to_s3.sh`** (fail-soft, like the rss build) so both
stay fresh. This also delivered the **chronicle half of #730** as a bonus.

## Three post-merge CI reds (all fixed, main green)

Lint gates are sequential — a red one masks the rest — so these came one at a time:
1. **ruff isort I001** on the new test — I ran `black`+`flake8` but **not `ruff`**
   (`reference_ci_masking_and_creds`: run FULL ruff before merge). `82796751`.
2. **LV4 `test_layer_version_consistency`** — a new layer module must be registered in
   **`ci/lambda_map.json` `shared_layer.modules`** too, not just `build_layer.sh`. `00bcfbbf`.
3. **`test_coach_memoir_lambda`** tier-1 pause test — `coach_narrative` cutoff moved 1→2,
   same class as the `state_of_matthew` fix already in the PR. `39acd3b3`.

## Gotchas confirmed

- **Merge order** #770→#771 conflicted at the `DECISIONS.md` EOF (both append an ADR block)
  — resolved to ADR-125 then ADR-126; #771→#772 conflicted on the doc-sync `test_count`.
- **Pre-commit doc-sync** leaves `lambdas/web/site_api_common.py` dirty after commits —
  `git add` + `--amend` each time (recurred ~4× this session).
- **New layer module checklist:** `build_layer.sh` **AND** `ci/lambda_map.json` **AND**
  (if a coach/AI consumer) it rides the layer bump + consumer redeploy.

## Not done (by design)

- **#730 static-render proof surfaces** — SCOPED + deferred, full plan posted as an issue
  comment. Scorecard half needs a daily generation Lambda (like OG images) writing HTML
  into `generated/` + a CloudFront route + template rework + deploy (**attended**). The
  chronicle-list half is now effectively live (see the deploy-verify catch above).
- The rest of the opus backlog untouched: **Attended** (#755 DR restore, #750 site-CI
  deploy, #687 OIDC tighten), **gated** (#746), **large independent features** (#734 audio,
  #409 batch-inference, #422, #421, #742, #753, #395, #749, #475) — each a focused session.

## Next

- Deploy the held **Operational** stack to v118 when the HAE reconciliation happens, to
  land `coherence_semantic`'s tier-1 pause.
- The `GenerationSkippedUnchanged` metric will show #738's reuse rate over the coming days
  (activates on each coach generation cycle; fail-soft, self-healing cache partition
  `USER#matthew#SOURCE#coach_gen_cache`).
- **Optional session-close ritual not done:** a public build beat for `/story/build/`
  (#380) — merged+deployed work qualifies; left for Matthew's call (outward-facing content).
- Untracked `docs/reviews/R21_BACKLOG.md` left alone (pre-existing).
