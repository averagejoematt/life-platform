# HANDOVER — Later-milestone drain: 17 /fullreview issues shipped + deployed + verified — 2026-07-18

> Instruction thread: "drain the LATER milestone — close as many OPEN issues as possible,
> PROPERLY" (a real fix + a non-vacuous regression guard proven to FAIL on the pre-fix code,
> merged AND deployed + verified live where it has a runtime surface). Matthew granted full
> authority up front: **"i approve all merges and deploys this session"** (IAM grants still
> user-NAMED).

## Outcome — 17 issues CLOSED, all merged + deployed + verified
All from the /fullreview 2026-07-16 Later backlog. Two `worktree-implementer` fan-out waves
(5 + 4 disjoint-file agents) plus a hand-authored doc bundle and two small direct fixes.
Every fix carries a guard proven to fail on the pre-fix tree (stash/pre-fix run captured each time).

**Wave 1 (code fan-out):**
- **#1246** calibration scoreboard surfaced 23 graded `forecast_resolution` rows (they carry
  `covered`, not `outcome`) — `/api/calibration` platform n **0→23** live (82.6%, verified).
- **#1250** theme toggle exposes `aria-pressed` + accessible name (site, live).
- **#1242** fabricated-date grounding: generalized the chronicle's date allow-list into shared
  `grounded_generation` (`allowed_dates`/`fabricated_dates`) AND **wired it live** into the
  chronicle installment gate (`installment_grounding_findings`) — a real new protection, not
  latent capability (agent's first cut was capability-only; I sent it back to wire the surface).
- **#1261** RSS excerpt → `#1224`'s word-boundary helper (357-slice killed). NB residual: the
  live chronicle item still shows a 300-char mid-sentence excerpt — that's a STALE/separately-
  generated `posts.json` excerpt (predates #1224's line-1864 helper), not the 357-slice; a tiny
  follow-up if desired.
- **#1239** deleted 8 verified-dead functions (intelligence_common ×6, character_engine ×2) from
  every bundle; AST guard.

**Wave 2 (code/site fan-out):**
- **#1254** cost-governor cadence "hourly"→"every 8h" (docstrings, budget_guard, /method/cost
  editorial + 28 regenerated shells) — live.
- **#1260** OG home card "25 data sources"→`len(SOURCE_REGISTRY)` (self-correcting) + check_doc_facts
  og-scan; og-image-generator deployed.
- **#1249** waveform day-bars reach the 44px tap floor via a touch-only `::after` expander;
  promoted the visual-QA tap-target audit **advisory→gating** (both-axes rule) — passed the live
  gating visual-QA.
- **#1247** experiment library deduped 71→67 (4 near-dup pairs, both copies) — `/api/experiments`
  **67** live (needed a root-`config/` S3 re-sync + CDN invalidation; site-deploy only syncs `site/`).

**Doc bundle (#1309, hand-authored — closes 6):** #1258 (deploy quickstart `<source-file>`),
#1245 (SITE_MAP panelcast viewer path), #1241 (mypy ENFORCED not advisory), #1253 (remediation
Mon/Wed/Fri not daily), #1256 (raw_layout `filename` facets — the leaf form varies; framework
`YYYY-MM-DD.json`, HAE-webhook `DD.json`, todoist/garmin flipped mid-tree), #1238 (ADR-103 ledger:
MCP prune EXECUTED, Panel LIVE). One `tests/test_fullreview_doc_drift_guards.py`, all 6 fail pre-fix.

**Direct small fixes (#1314 — closes 2):** #1248 (Elena PERSONA#* comment falsely claimed she was
"carried into EP0" — she's EXPERIMENT_SCOPED/wiped; reconciled with a classify() guard), #1259
(memory orphan gate added to `/wrap`; indexed 4 orphaned topic files while validating).

## Deploys done (all verified live)
site-api ×1 (#1246, calibration n=23) · wednesday-chronicle (#1242) · og-image-generator (#1260) ·
4 site auto-deploys (#1250/#1249/#1254/#1247 — **each passed the gating visual-QA**, incl. #1249's
new tap-target gate) · root `config/experiment_library.json` S3 overwrite + `/api/experiments` CDN
invalidation (#1247 → 67 live) · CI auto-fleet-deployed the shared-module changes (#1239 dead-code,
#1242 grounded_generation). Site `version.json` == HEAD after the last site merge.

## Merge mechanics / gotchas
- **Only the doc bundle (#1309) hit the wiki-drift gate** (it touches `docs/`); the code PRs adding
  test files drift `test_count` but that's fixed post-merge by the reconcile bot. Merged #1309 LAST,
  after main settled, rebasing onto the final reconcile commit + `sync_doc_metadata --apply` (3900) —
  the repeated rebase-conflict on the test_count literal is the [[reference_docsync_literal_cross_pr_drift]]
  class; ending with the doc PR stops the churn.
- **#1247 `/api/experiments` reads the ROOT `config/` S3 object**, which `sync_site_to_s3.sh` (site/
  only) does NOT update — count stayed 71 until I `aws s3 cp config/experiment_library.json` +
  invalidated `/api/experiments`. Same class as [[project_reset_purges_site_config]].
- **#1249 gating-audit risk:** the tap-target audit runs only in the 390px mobile pass (where the
  touch-only `::after` is active) and now fails only when sub-floor in BOTH axes — verified the live
  gating visual-QA passed before merging the other site PRs through the same gate.
- Reused the proven playbook: disjoint-file batches, `worktree remove --force` + `branch -D` after
  each merge, spot-checked every diff against its issue before merging.

## Left OPEN on Later (8) — for Matthew / next session
- **FLAG (do not attempt — infra/audio/gated):** #1257 (delete 2 hand-created EventBridge rules —
  live AWS mutation + CDK), #1255 (chronicle bypasses `allow('chronicle')` — needs a user-NAMED IAM
  grant + CDK deploy, R8-ST6 Plan-red-by-design), #1243 (Prologue Part II read-aloud narrates the
  superseded genesis — podcast AUDIO re-narration), #748 (fulfillment story — data/time-gated).
- **DEFER (code-actionable, careful/solo):** cockpit/home trio #1251 (conflicting HRV scope labels)
  + #1252 (pre-genesis "as of" dates) + #1244 (footer-buried cycle-compare) — shared cockpit files +
  timing judgment, best as one coordinated site-ux slice (testable NOW while cycle-7 is pre-start);
  #1240 (split `site_api_data.py` 4,184 lines/37 handlers — big refactor, own session).

## Operational note (Matthew's domain)
The ingestion **DLQ holds 1 message** — a Withings token-refresh 503 ("invalid refresh_token", the
known [[reference_withings_transient_refresh]] transient) from 15:05 UTC. It reds the **post-deploy
integration check (I1/I2/I5)** on every lambda deploy (cosmetic — smoke passes, no auto-rollback), but
does NOT indicate a code break. Drain via `life-platform-dlq-consumer` or let it age out / self-recover.

**Build beat:** `2026-07-18-later-drain-17` (distilled below — merged + deployed + verified).
**Docs:** #1309 already updated CLAUDE.md/DECISIONS.md/RUNBOOK.md/SITE_MAP/mypy.ini/SCHEMA-verified;
this wrap updates the CLAUDE.md status block only — no other pages invalidated (fixes were self-documenting).

Prior session: `handovers/HANDOVER_2026-07-18_NextSlice3.md`.
