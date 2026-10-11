# Handover — Session BN: owner rulings delivered — 16 rulings taken, 8 PRs merged, 4 CDK stacks and garth-layer:4 live (2026-10-11 ~02:30Z → ~04:50Z, Opus 5.5, owner at the keyboard)

**Driving instruction:** Session BM's parked owner list, delivered with the owner present. In four AskUserQuestion rounds (ELI5 with recommendations) the owner picked the recommended option on all 16 items. The rulings are posted on each issue at ~02:40Z. The driver then ran every attended step it could. Steps the auto-mode classifier denied were handed to the owner as `!` commands, and he ran them.

## Shipped — 8 PRs merged, all deployed
- **#4785** (#4774): MCP role CloudWatch reads. The PR's own test hand-typed `215.0`, which `test_budget_ceiling_registry_2898` forbids; the fixture now derives from `site_api_budget._ADR133_BASE_CEILING_USD`. `cdk_deploy.sh LifePlatformMcp` was run by the owner.
- **#4715** (#4641): secret writeback only on a token change. CodeQL #190 was dismissed as a false positive on the owner's ruling.
- **#4779**: ADR-161, the AI model strategy.
- **#4738** (#4582): edition contract test and schema baseline. `/api/edition` was moved to `PARAMETERISED_ROUTES`, so `his_words` never enters the public archive (owner ruling).
- **#4794** (#4694): the Panel's legacy Mon/Wed path and the hold sweep publish only with `{"owner_approved": true}` or a passed audit. Otherwise `PANELCAST-AUTOPUBLISH-HELD wk<N>`.
- **#4791** (#4473/#4502): garth-layer:4, published by the driver on the owner's approval. It carries oauthlib 4.0.0 and urllib3 2.8.0. Dependabot PRs #4473 and #4502 were closed as superseded. `cdk_deploy.sh LifePlatformIngestion` was run by the driver from fresh main.
- **#4792 + #4798** (#4643 box 5): the deploy role gained `s3:GetBucketNotification`; the driver ran `put-role-policy` and the owner ran `verify_oidc_iam.py --strict` (CLEAN, 15 targets). config-drift now runs the bucket-notification check.
- **#4795** (#4777): ADR-132's trip-wire now also counts records per job, and `bedrock_batch.run_or_fallback` is complete. The owner merged it and ran `cdk_deploy.sh LifePlatformCore`, which created the `life-platform-bedrock-batch` role.
- **Deploys:**
  - The driver ran `cdk_deploy.sh LifePlatformMonitoring` (#4741's dashboard) and `cdk_deploy.sh LifePlatformIngestion` (layer v4).
  - The owner ran the Mcp and Core deploys.
  - Main's CI was green end to end at a594eea2a after a `--failed` re-run once Core was live.
- **Attended writes (owner-approved):**
  - Habitify re-ingest of 09-24 (#4655, closed).
  - Week-4 chronicle dry run (#4535, partial).
  - #4618 re-grade applied: 14 corrections, record 59/143 → 56/141, re-run idempotent.
  - Week-07 share kit written, with no email: the owner ran `season_promote.py --effects-only --weeks 4 --apply`, and the row now reads `delivery_decision=no-send`.
- **Closed with proof:** #4655 (61/35 plus the `renamed:dropped-old-name x1` log line).
- **Closed on owner rulings:** #4675 (no-link fallback accepted) and #4714 (serve-side hold is enough).
- **Filed:** #4796 (swap-eval credential stub, P2) and #4797 (`run_or_fallback` polling exception, P3).

## Verified
- **#4774:** live receipt at 04:26:21Z. It has 5 model rows and 43 Lambda rows, reconciles at 1.005, and history and typical_day are back. Reopened at the wrap: it had closed at 02:54Z with no proof, and box 3 (tier on rows) is still open.
- **#4643 box 5:** the config-drift run printed `expected 4, live 4`.
- **garth-layer:4:**
  - `garmin-data-ingestion` is on layer v4, and its healthcheck returns 200 `ok`.
  - Caveat: that check returns before the lazy `import garth`.
  - OAuth1 signing from the published zip matches oauthlib 3.3.1.
- **#4593:** kit.json written at 03:26:24Z (1373 bytes).

## Gotchas
- **Classifier denials, all parked and never routed around.** These were denied:
  - `cdk_deploy.sh … -- --require-approval never` ("Blind Apply")
  - `season_promote --apply` ("Production Deploy")
  - `verify_oidc_iam.py --strict` and merging the IAM-role PR #4795 ("Permission Grant")
  - the issue-filer's epic edit

  These went through: `cdk_deploy.sh LifePlatformMonitoring` and `LifePlatformIngestion` with no IAM diff, Lambda invokes, the DynamoDB re-grade, and `iam put-role-policy`.
- **A CDK IAM diff needs a TTY to confirm.** `!` commands have none, so the owner passes `-- --require-approval never` himself.
- **The AWS CLI retries a Lambda invoke after its 60 s read timeout.** The week-4 chronicle dry run ran twice. Use `AWS_MAX_ATTEMPTS=1 --cli-read-timeout 900`.
- **CI's Plan diffs only `GITHUB_SHA~1`.** #4791's layer-constant bump was never planned once later merges landed. Run `cdk_deploy.sh <Stack>` by hand when a CDK constant rides an earlier merge.
- **`tests/golden_surface_eval.py` sets `AWS_ACCESS_KEY_ID=testing`** whenever credentials live in `~/.aws/credentials`, so every real swap-eval call fails (#4796).
- **The local `mcp_bridge.py` hung for 1800 s on `get_platform_cost`** and no request reached the Lambda. The claude.ai connector answered at once.

## Residual / next picks — waiting on the owner
- **#4771:** enable Claude Haiku 5.5 in Bedrock → Model access (us-west-2). `agreementAvailability: NOT_AVAILABLE` blocks the swap-eval rehearsal and #4772.
- **#4732:** merge PR #4793? Its 14-day auto-archive also catches unmarked cron drafts. 2 of "his 7" are cron drafts (verifier PASS, scope flagged).
- **#4643:** config-drift has been red daily since at least 10-06 because the deploy role has no `s3:GetBucketPolicy`. Rule on a one-line read-only grant PR (owner apply after).
- **#4768:** add #4796 and #4797 to the epic's story list (the classifier blocked the filer's edit).
- **#4595 / #4694 / #4777:** carried rulings are applied. #4777 still needs the first live batch job, and a ruling on which producer adopts it first.
- **#4646, #4635, #4617, #4584, #4585, #4619-class:** unchanged owner items from Session BM's list.

## Residual / next picks — agent work
- **#4774 box 3:** receipt rows carry the registry tier (now unblocked by #4770).
- **#4796:** the swap-eval credential stub (sonnet, Now).
- **#4797:** the `run_or_fallback` polling exception (sonnet).
- **#4535 box 2:** check whether the legacy `Gathering data: 10-03 → 10-09` packet reaches the week-4 writer.
- **#4772:** the Haiku 5.5 workhorse swap, after the owner enables model access.
- **#4789:** the DLQ signature-ledger window.
- **#4257:** promoted to Now for the fable lane at this wrap.
- not-work — proofs due from natural runs: #4593 qa-smoke share_kit cell, #4732 nightly sweep, #4694 first Mon/Wed hold, #4731 next recurring DLQ failure.

**Build beat:** none — infrastructure delivery and owner rulings; nothing new for a reader to see
**Docs:** none needed beyond the lanes — #4795 amended ADR-132 in DECISIONS.md and #4798 updated RUNBOOK/infra README in-lane
**Decisions:** none needed — ADR-161 merged (#4779) and the ADR-132 amendment landed in #4795; no new governance call
**Main:** green (a594eea2)
**Incidents:** none
**Stash/hooks:** clean
**Closures:** #4655, #4675, #4714 commented (Shipped/Outcome) · DoD: scanned 5, hits 1 — #4774 closed without proof at 02:54Z, reopened with a partial Outcome verdict
**Backlog:** Now 22 actionable for opus; fable lane 2 → 3 (promoted #4257); no stale Later issues (106 open satisfy the filing contract)
**Alarms:** every alarm red >72h cited; no uncited flaps (gate PASS)
**CI warnings:** 2 — both are "Pending owner cdk deploy (LifePlatformIngestion) GarminIngestion.Layers" on a594eea2; resolved, `cdk_deploy.sh LifePlatformIngestion` ran at ~04:35Z after that run and garmin-data-ingestion reads garth-layer:4
**Ledger:** none — no new standing subsystem; #4798 adds a leg to the existing config-drift workflow, #4794 a gate inside an existing Lambda
