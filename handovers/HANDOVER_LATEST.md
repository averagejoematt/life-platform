# HANDOVER — Day 3: THE CYCLE-9 RESET, verified by behavior for the first time — 2026-07-19/20 (night)

> Instruction thread: "ultracode +2M — ARC 1 the cycle-9 reset (genesis Monday 2026-07-20,
> #1433 merge first, BUILD #1559 before the reset so the reset becomes its first customer),
> ARC 2 keep draining, three-kinds-of-close, all merges/deploys/pushes authorized incl. the
> reset. Decision brackets arrived UNFILLED (= pending, no re-asking) — then Matthew answered
> the one that mattered mid-session: '315lb for now, and will weigh in at the morning' — the
> reset went from staged to EXECUTED the same hour." Clock discipline: prompt said Monday,
> clock said Sunday evening PT — but tonight was the genesis EVE, which made the eve-only
> machinery (lock email) fire honestly instead of being skipped.

## Outcome — the reset ran, the harness proved it, 13 PRs merged, CI's killer identified

**ARC 1 — THE RESET (all four planned steps + the execution itself):**
1. **#1433 a11y salvaged** — the Day-2 agent had finished but never committed/pushed; work
   recovered from its worktree, verified, PR #1560, merged. axe 4.12.1 vendored, 73-page
   debt-ledger baseline, gate = NEW serious/critical only.
2. **#1559 BUILT + proven pre-reset** (PR #1585): `deploy/restart_integration_check.py` —
   four legs (ingestion/compute/serving/ops) + `--synthetic` HAE round-trip + the STATIC
   present-None gate. The gate proved **RED on 12 unguarded pillar chain-reads across 4
   email lambdas** (monday_compass:415 — which fires Monday 15:00 UTC on the Day-1 sheet —
   wednesday_chronicle ×2, weekly_digest ×5 — #1540 had fixed only the withings site —
   monthly_digest, + pillar_scores/pillar_summary siblings); all 12 fixed with the
   `(d.get(k) or {})` idiom and the gate now lives in CI permanently. Two prove-the-harness
   runs against live cycle-8: run 1 caught 4 harness bugs (dropbox partition-False facet,
   `character_level` field name, urllib redirect-following masking a 301, brief timeout);
   run 2 = clean instrument reporting exactly the true findings.
3. **THE RESET EXECUTED** (~19:45–20:15 PT): `restart_pipeline.py --genesis 2026-07-20
   --override-weight-lbs 315 --with-preregistration --apply`. All 16 steps + gates:
   rendered PASS, semantic PASS (0 poisoned rows / 32 sources), truth SKIPPED honestly
   (tier-1). One abort at the last hook — the frozen-artifact protection REFUSED to
   silently regenerate cycle-8's prereg (working as designed, #976/#1378): archived it per
   convention (`genesis_preregistration_2026-07-19_cycle8.json` + stamp), re-seeded, then
   the attended chain: publish (dry-run reviewed → --apply), **seal
   908fa45acca1840713e258d4d6ad6129bf6eece7f7356000999247cdc7181ecc** live at
   /experiments/prereg/genesis-2026-07-20.json, predict-week live (stamped W29 = tonight's
   ISO week; **re-run Monday to roll to W30**), and the eve-only **lock email SENT 1/1** —
   the machinery's first honest eve since it was built. Reset commit d819bdba; cycle-8
   closed as the honest one-day cycle (LIFETIME# rolled).
4. **First real #1559 execution post-reset** (`--synthetic --expect-cycle 9`): **cycle=9 ✓,
   Day-0 Level-1 sheet + replay_verified receipt ✓, 80/80 serving URLs ✓, DLQ 0 ✓, crons
   armed ✓, synthetic webhook PERFECT (350ml dedup exact, idempotent re-send, verified
   cleanup)**. True positives it caught same-run: the mid-deploy withings DLQ message
   (drained), the withings transient token 503 (self-recovered — token healthy for the
   morning weigh-in), an SoM tz-rollover leak in its own synthetic payload (2099-01-02 row
   — found + deleted; fixed in follow-up PR #1588 with dual-day cleanup + `--brief-full`).
   `restart_verify.py` (12/12, day_n>=1 + genesis weigh-in) is deliberately Monday-morning.

**THE #1544 ROOT CAUSE, CONFIRMED:** GitHub Actions job annotations state verbatim:
*"The job was not started because recent account payments have failed or your spending
limit needs to be increased."* — **owner-side billing**. Evidence on #1544. CI went from
intermittent to dead mid-session; all 13 merges carried on local full suites (no -x) +
manual deploys + attended site syncs (version.json verified each time). Matthew push-notified.

**ARC 2 — 13 PRs merged, every one verified, two BLOCKED-then-fixed:**
#1560 (a11y, #1433) · #1579 (#1438 write-path E2E) · #1562 (#1467 design-sync captures) ·
#1561 (#1443 canary 3×/wk + heartbeat 7d→4d) · #1585 (#1559) · #1580 (#1455 heartbeat
completeness — 70 scheduled lambdas: alarm-verified + 45 dated exemptions + 2 NEW
compute-output alarms) · #1565 (#1406 glucose-CV/MAGE + values→adherence lagged edges;
review's fabricated-zero-CV guard applied + regression case) · #1583 (#1470 paper-elevation
ramp, both themes, browser-faithful contrast test) · #1584 (#1484 unified evening flow —
real PT-vs-UTC keying bug fixed, ADR-137 drinks-only) · #1581 (#1482 coach memory — review
BLOCKED on a real Limit-200 category-alphabetical starvation trap; fixed with per-category
begins_with reads + flood-fixture regression) · #1582 (#1441 AI-surface archive — review
BLOCKED on the versioned-bucket lifecycle making "90d retention" false at the byte level +
a never-screenshotted surface; both fixed, TRUE 90d retention now) · #1587 (#1466 Slop
Litmus canonical + structurally-advisory gloss lens, fable solo) · #1588 (#1559 follow-up).
Adversarial review earned its keep: **2 of 3 deep-reviewed PRs were BLOCKED on real MAJORs.**
Issue #1586 filed (qa_audit's 39-unchecked-API-deps finding). Deploys: the reset's
`cdk deploy --all` consolidated the fleet at a5a1057e; targeted post-reset deploys for
every later merge (4 guard-fixed emails, MCP ×2, daily-brief, chronicle, state-of-matthew,
coach-memoir, field-notes, site-api, lifecycle rules, Compute/Email/Serve role grants);
site synced attended, live == 232c838d content, invalidations completed.

## Live state at wrap
- **Cycle 9, genesis 2026-07-20 (today), baseline 315.0 lb (override)** — site in the
  pre-start countdown state; first weigh-in syncs on the hourly Withings run after Matthew
  steps on the scale; computes anchor Day 1 at 16:30 UTC; brief 17:00 UTC.
- **Harness verdict**: everything the platform controls is green; the 4 dark sources are
  human/provider-side: withings (scale, resolves at the weigh-in), **hevy last row
  2026-06-25** (poller + cursor healthy — either no lifts logged in 25d or a cursor-jump
  gap; ASK MATTHEW), **notion journal last 2026-05-25**, **strava last 2026-07-14** (the
  #1330 token-health class, gate:owner).
- **Budget tier 1** (today's Ghost + tonight's ultracode load) — accepted posture per the
  ADR-133 amendment; internal AI paused (incl. visual_ai_qa + the truth gate); reader
  surfaces + brief protected. ai-canary-heartbeat alarm fires until Monday 16:20 UTC's
  first 3×/wk run (deploy-order artifact of the 7d→4d window, self-heals).
- **felt_probe n=0** at wrap — the taps didn't happen tonight; fulfillment adoption
  unchanged.
- **Board: ~89 open** (tonight closed #1433 #1438 #1441 #1443 #1455 #1406 #1467 #1470
  #1482 #1484 #1466 #1559; filed #1586).

## Gotchas hit (durable)
- **Rebase conflict markers can get COMMITTED when `checkout --ours` reports "Updated 0
  paths"** — the hook had already staged the conflicted file; a SyntaxError in
  site_api_common.py surfaced only at the next collection (56 errors). Always
  `py_compile` / collect after any conflicted rebase, never trust the hook's green alone.
- **Reconcile discipline: take main's copy ONLY for the generated literal files** — I
  briefly restored DECISIONS.md/CLAUDE.md from main during #1584's reconcile and threw away
  ADR-137 + reverted the other session's wrap block (caught both in-session via the ADR
  index count + a CLAUDE.md diff). The ritual's file list is exact for a reason.
- **A concurrent session wrapped and pushed to main mid-train** — the reconcile flow
  absorbed it cleanly (my linearized commit landed on top of their wrap); the ancestry
  check before every merge is what made that safe.
- The `--with-preregistration` fold ABORTS (by design) when a prior cycle's freeze exists —
  archive it per the in-place convention first; the pipeline is idempotent from there.
- An -0800 EVENING timestamp in any synthetic payload lands on the NEXT UTC day — assert
  and clean BOTH days (the #1588 class).

## Residual / next picks
- **Monday morning (owner or next session):** weigh-in → hourly sync → `python3
  deploy/restart_verify.py` (12/12) → `python3 deploy/build_genesis_predict_week.py
  --apply` (rolls W29→W30) → glance the 16:00 UTC ops email (first #1446 green report; the
  2 GitHub drift lines + billing line are EXPECTED) → Monday Compass 15:00 UTC now safe
  (guards deployed).
- **Engine-doc drift advisory** (handed over from the voice session): CHARACTER.md /
  HYPOTHESIS.md / COACH_STANCE.md / READINESS.md flagged behind their sources — this
  session's surfaces to re-verify; untouched tonight (the reset owned the docs surface).
- Next-tier drain remainder: #1442 (now unblocked by #1582's archive), #1472/#1474 design
  (one CSS story at a time), chat #1481/#1483 (fable), #1586 (just filed), the #1581 MINOR
  (deterministic coach_context-number check), #1406's MAGE-backfill question.
- Pre-existing open PRs unchanged: #1543 deep-context, #1512 portraits (DO-NOT-MERGE),
  #1491 gh-quota (its drift_sentinel reconcile note stands), #1191 dependabot.
- The #1582 attended IAM leg: diagnosis-role screenshot grant staged in
  `infra/iam/github-actions-diagnosis-role.permissions.json` — `verify_oidc_iam.py
  --strict` shows ONE expected staged drift until Matthew applies it.

**Main:** green by local verification — the last 5 suite runs each 6100+ passed with only
`test_i16` (live dark-source freshness, self-resolves as cycle-9 data lands). CI cannot
attest: GitHub billing refusals (see incident row) — every merge tonight was
locally-suite-verified + manually deployed instead. Live site == main content,
invalidations completed. **Build beat:** `2026-07-20-cycle9-reset-verified-by-behavior`
(the reset a harness proved, not just a checklist — merged + deployed + live).
**Docs:** RUNBOOK (harness + drill step 4), PHASE_TAXONOMY xref, DESIGN_SYSTEM_V5 (§litmus
+ §4a ramp), DATA_GOVERNANCE (retention truth), DECISIONS (ADR-137), INCIDENT_LOG (+2).
**Decisions:** ADR-137 (evening ledger stays one-tap); no other new ADR — the reset
followed ADR-058/059/077 as written. **Incidents:** 2 rows (billing refusals P3
owner-gated; mid-deploy withings DLQ P4 resolved). **Stash/hooks:** stash empty; merged
worktrees + branches pruned; hook fresh. **Memory + S3 backup:** updated (monday_reset →
cycle 9, push_ci_silent_death → billing root cause, shipped archive) + synced.

Prior sessions (same day): `HANDOVER_2026-07-19_VoiceStudio-Plan.md`,
`HANDOVER_2026-07-19_Day2-drain.md`.
