# HANDOVER — Eng-excellence Now-tranche drain + Social Membrane foundation shipped — 2026-07-22

> Instruction thread: "clean tree check → (1) owner-merge PR #1647 then drain epic #1648 Now
> tranche via /uplevel; (2) start the Social Membrane foundation #1669+#1670 together. Fan out
> worktree-implementers (open PRs, never merge/deploy); VERIFY every agent finding; full suite before
> any merge; batch merges/deploys into ONE numbered ask; flag every site/** auto-deploy." → batch
> approved (merge all 5 + reconcile; cdk-deploy the dormant youtube Lambda; small secret-hygiene PR)
> → "merge 1685 then wrap".

## What shipped (all merged to main; deploy status per item)

**PR #1647 (epic #1648) — /craft-review skill + ENGINEERING_STANDARDS.md** — merged (docs/command only, no deploy). The 3rd grading ritual + the durable "definition of an A."

**PR #1683 (#1649) — hygiene cleanup safe-subset** — merged. Retired `archive/` (315 tracked/140M) + verified-dead one-shots (`patches/ backfill/ spikes/ backup/ seeds/archive/` + 10 render PNGs): **−429 files / −109k lines**. `git tag pre-hygiene-2026-07-22`; 135M safety zip handed to Matthew (scratch path — MOVE IT, session-scoped). `freshness_checker` one-line string change rides the next LifePlatformEmail deploy (cosmetic SNS hint). **The audit MISLABELED load-bearing dirs** (`setup/` = DR/re-auth toolkit; `lambdas/{fonts,cf-auth,dashboard,requirements}`; `seeds/*.json` incl. content_filter.json; `mcp_server.py`) — all KEPT after a tree survey; #1651/#1652/#1657 re-scoped via comments.

**PR #1680 (#1659) — gitleaks secret-scan** — merged, LIVE (runs PR-diff-scoped on every PR, `--log-opts base..head` so legacy public-era strings don't red every PR).

**PR #1681 (#1660) — CodeQL SAST (python + javascript-typescript)** — merged, LIVE + GREEN on first main run (advisory; promotion-to-blocking is #1662/gate:owner).

**PR #1684 (#1643) — reset regen-list fix** — merged (operator script, no deploy). Real name `daily-brief` + `{"dry_run":true}` payload (a bare `{}` would EMAIL the brief every reset — see [[reference_regen_invoke_email_lambda_trap]]) + a dry-run get-function guard.

**PR #1682 (#1669 + #1670) — Social Membrane inbound foundation** — merged + **CDK deployed** (`LifePlatformIngestion`). New `youtube-social-ingestion` Lambda LIVE but **DORMANT** (smoke-verified: StatusCode 200, records_written:0, errors:0 — no channel-id secret). `lambdas/social_provenance.py` = the loop-breaker membrane. YouTube = keyless per-channel RSS.

**PR #1685 — secret-hygiene follow-up** — merged. Withings `AUTH_CODE` → env var (spent one-time code); eightsleep `KNOWN_*` documented as public app creds + `gitleaks:allow`.

**Reconcile:** doc-sync `lambda_count` 95→96, `test_count` 4869→4887 (commit `4359d22d`, pushed to main after the batch).

## Verified
- Full suite on the cleanup branch: **6415 passed** (sole failure = `test_i16_recent_ingest_records_exist`, a `pytest.mark.integration` live-AWS test CI excludes via `-m "not integration"`; failing locally only because cycle-10 is pre-start Day-0).
- Every merged PR's CI CLEAN/MERGEABLE pre-merge; all 6 `Fixes #N` issues auto-closed (#1649/#1659/#1660/#1669/#1670/#1643).
- CDK deploy exit 0 (145s); youtube Lambda `Active`, no-ops cleanly. `cdk diff` = new youtube resources + one-bundle hash bump on all ingestion lambdas (expected #781 behavior).
- Every agent finding git-grep-verified on-branch. **The Social Membrane agent's FIRST report was incomplete** — missed 3 deploy-critical registry gaps (lambda_map / KNOWN_SECRETS / heartbeat exemption); CI's `deploy_critical` marker lane caught them, sent it back, all fixed + re-verified.

## Gotchas hit
- **Audit findings mislabel load-bearing dirs as throwaway** — survey before ANY delete-per-AC ([[reference_audit_mislabels_loadbearing_dirs]]). Deleting per #1651's ACs would have broken prod + DR.
- **Regen-invoke of an email Lambda with `{}` SENDS the email** — the #1643 latent trap; the wrong function name had been masking it with `err(254)` ([[reference_regen_invoke_email_lambda_trap]]).
- **Agent self-reports need CI cross-check, not just the agent's targeted run** — deploy-critical marker lane ≠ a targeted pytest subset.
- **zsh `$VAR:l`** is a lowercase modifier — `git show "$BR:lambdas/…"` ate the `l`; brace it `"${BR}:…"`.

## Gate outcomes
- **Build beat:** `2026-07-22-repo-craft-hardening` (the security-gates + honest-cleanup story; gotcha = the mislabeled dirs; honest miss = all under-the-hood + the dormant social spine).
- **Docs:** `docs/SCHEMA.md` updated (new `youtube` source + `BROADCAST_ORIGIN#` provenance-ledger key families, Verified→2026-07-22); counts reconciled at merge. `check_doc_index` flags `docs/engines/SCORING.md` re-verify (pre-existing — `daily_metrics_compute_lambda.py` changed 2026-07-21, not this session). Links/tombstones/ADR-index green.
- **Decisions:** none needed — the reset is routine (ADR-077); the security gates were anticipated by ENGINEERING_STANDARDS.md D6 (no new governance choice); the Social Membrane's ADR (if any) lands with #1678's CSP amendment.
- **Main:** parked — latest CI/CD run (`4359d22d` / `e73adf73`) pending at the manual production Deploy gate; automated Lint/Test/Plan green; older runs auto-cancelled (the standing manual-gate park, not a test break).
- **Incidents:** none — no auto-rollback fired, no data gap, no main-red>1h beyond the manual-gate park; the youtube dormant no-op is by design.
- **Stash/hooks:** clean — `git stash list` empty; hook freshness 🟢.
- **Labels:** OK — 91 open type:story issues all carry `model:*`.

## Residual / next-picks
- **Activate YouTube ingestion** — provision the `life-platform/youtube` secret `{"channel_id":"UC..."}`, then flip registry `active_api:True` + drop `freshness:False`/`catalog:False`. `not-work — owner secret provisioning`.
- **Social Membrane Next tranche** — #1671 (enrichment→coach signals), #1672 (broadcast feed page), #1673 (auto-publish safety gate). (#1671/#1672/#1673)
- **Eng-excellence remaining** — #1657 (lint waivers, re-scoped as careful surgical work), #1656/#1658 (mypy strict + coverage 70% big-bang), #1655 (CI composition), #1652 (root-clutter guard — the durable win; handovers/ 479-file reduction is gate:owner). (#1657/#1656/#1658/#1655/#1652)
- **Gate:owner eng-excellence** — #1662 (branch protection Option C), #1666 (proportionality ADR), #1650 (handovers disposition). (#1662/#1666/#1650)
- **#1620** — outbound social links; runs the `v4_apply_chrome` HTML sweep, land AFTER any site/head sweep. (#1620)
- **`freshness_checker` string** — the #1683 one-liner deploys with the next LifePlatformEmail stack deploy (or the CI Deploy gate). `not-work — cosmetic, rides next email deploy`.
- **AiReviewPack (#1594)** fires Sunday 18:00 UTC — Matthew flagged wanting a mute decision. `not-work — owner decision on a just-activated schedule`.
- **`docs/engines/SCORING.md` re-verify** — pre-existing staleness note (source changed 2026-07-21). `not-work — pre-existing doc-verify, unrelated to this session`.
- **Standing alarms:** none newly outstanding; budget **tier 1** (July $115 window, auto-reverts 2026-08-01 — working as designed). `not-work — standing checklist, nothing to action`.

**Build beat:** 2026-07-22-repo-craft-hardening
