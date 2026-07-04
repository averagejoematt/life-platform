# Handover — 2026-07-04 (session 2, part 2) The Fable Later batch: #410 #403 #404 #406 #407 #413 #398

**All seven `model:fable` Later-milestone stories implemented on branch `feat/fable-later-batch` (worktree `honesty-pair`), one commit per issue, PR pending merge.** Full suite **2,712 passed** (only the 5 known pre-existing failures: coaches_api ×4 + i16); synth clean for Email/Web/Operational; black/ruff clean; ~44 new tests. Earlier the same session: the Fable **Next** batch (#392/#387/#397/#396/#380) was merged (PR #453) **and deployed live** (layer v97, postflight 🟢) with wrap PR #454 also merged.

## What each story shipped

1. **#410** — coach compression input BOUNDED: PREDICTION# queried newest-first with a hard limit (SK embeds the date — decided history ages out of the scan, stays stored); prompt windows (15 most-recently-referenced open threads / 15 newest active predictions) with HONEST rollup lines; 24k-char deterministic budget guard (halving, floored, logged). Replay test = the real 52-thread/39-prediction failure. Nothing deleted; track record untouched.
2. **#403** — POST `/api/explain` on the site-api-**ai** lambda: client sends ONLY an allowlisted surface name (observatory_week / what_changed / sleep_correlations); the server refetches the public JSON itself (injection closed by construction, test-pinned); 3-4 correlative sentences, no model arithmetic, experiment-day context for honest thin-chart explanations; ADR-104 fail-closed number gate; shares ask's rate bucket + budget pause + prompt cache. Mounted on cockpit week/month + the sleep correlation board. **New CF behavior `/api/explain` → AiLambdaOrigin.**
3. **#404** — permalinked moments: the daily og-image-generator ends with a moments sweep (`web/og_moments.py`) minting static shells + per-moment OG cards under `generated/moments/` for the weekly recap, each published board answer, and each graded prediction (sourced from the PUBLIC APIs/feeds — a moment can never say more than the site publishes); share buttons (navigator.share/clipboard) on the cockpit week view, answered Q&As, and graded scorecard calls, driven by `/moments/index.json`. **New CF behavior `/moments/*` → S3GeneratedOrigin; OG role + reads answers feed + writes moments prefix.** publish_board_answer.py triggers the sweep on publish.
4. **#406** — GET `/api/last_sync` (site-api data lambda): REAL `ingested_at`/`webhook_ingested_at` stamps for the passive pipes (whoop/eightsleep/apple_health) + server_now; cockpit sync strip ticks "ago" client-side (30s), re-checks (5min), pulse-glows ONLY within the 45-min earned window, stale shown truthfully.
5. **#407** — the loop teaser (data → coaching → protocols → story ↻) now sits UNDER THE H1, verified in-fold locally (y=710 @1440×900, y=509 @390×844, screenshots in scratchpad); constellation caption gains the low→high dot legend + "each scored out of 100 … not a broken one"; full below-fold diagram untouched.
6. **#413** — "where would you land" beat on home: reader types one number (sleep/RHR/weight) → placed against Matthew's real public band; submit is preventDefault-only (no fetch/beacon/storage — local Playwright proved ZERO non-GET requests across the interaction); N=1 + no-advice copy; hides honestly with no public numbers.
7. **#398** — `between-chronicle` email Lambda (Email stack, Sun 17:00 UTC): digest purely from already-computed records (what_changed snapshot, freshly graded predictions, stance shifts) — zero AI (test-pinned); sends ONLY on real, previously-unsent content (content-hash marker `SOURCE#email_digest/STATE#between_chronicle`); NO open tracking (no image at all); **ships dark behind `EXTERNAL_EMAILS_ENABLED=false`** (same kill switch as the chronicle — flipping it is Matthew's call). `dry_run` event previews the digest.

## Deploy sequence (STAGED — run from detached origin/main after the PR merges)

1. `git fetch && git checkout origin/main` + `rm -rf cdk/cdk.out`
2. `cd cdk && npx cdk deploy LifePlatformWeb LifePlatformOperational LifePlatformEmail LifePlatformCompute --require-approval never`
   — Web: `/api/explain` + `/moments/*` CF behaviors; Operational: site-api-ai (explain) + og-image-generator (moments sweep + IAM); Email: the new `between-chronicle` lambda; Compute: coach-history-summarizer windowing. (No layer change this batch — v97 stands.)
3. `bash deploy/deploy_site_api.sh` — /api/last_sync route (site-api data lambda ships via script, not cdk).
4. `bash deploy/sync_site_to_s3.sh` — home (teaser/legend/mirror), cockpit (sync strip + explain + share), coaching/evidence JS, explain.js/share.js, css.
5. Kick the moments sweep once: `aws lambda invoke --function-name og-image-generator --cli-read-timeout 0 /tmp/og.json` → verify `/moments/index.json` 200.
6. Verify: `/api/explain` probe (surface=what_changed) grounded 200; `/api/last_sync` 200 with real stamps + cockpit strip renders; home fold screenshots (1440×900 + 390×844) show the teaser + legend (AC of #407); mirror widget zero-write interaction; `between-chronicle` `dry_run` invoke returns the digest (send stays dark until EXTERNAL_EMAILS_ENABLED flips).

## Gotchas / notes

- test_i5/lambda_map: new lambdas register under `lambda_map["lambdas"]` (the canonical group) — a separate top-level group does NOT satisfy the orphan test.
- KMS: any role with DDB write needs `kms:GenerateDataKey` (test_r2).
- Static `get_item` keys that are lazily created need a `KNOWN_OPTIONAL` entry in test_ddb_key_contracts.
- `og_moments.build_moment_card` imports PIL lazily via og_image_lambda — tests stub it (CI has no Pillow).
- The moments-index prediction key is a plain composite (`coach_id|date|text[:60]`) shared verbatim between `og_moments._prediction_key` and coaching.js — change both or neither.
- Prior outstanding items: shadow-sweep re-measure vs 11/112 baseline (needs daily coach cycles); `EXTERNAL_EMAILS_ENABLED` flip = Matthew's call; todoist false-stale window (00:00–14:00 UTC) is known-benign.
