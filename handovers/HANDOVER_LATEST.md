# Handover — 2026-08-16 (day, ~10:15→14:15 PT): the BodyScan 2 wave, owner-interactive

**Session:** Fable, interactive (Matthew present and answering asks). **Driver:**
`~/.claude/plans/cryptic-cooking-sparkle.md` — board pickup → the Body Scale 2 spike
(file-first, live API capture) → batch the owner-unblock numbered ask EARLY → Fable
continuum → Now-queue paydown. The early batched ask was the session's hinge: Matthew
answered all seven items mid-flight, converting investigation into a shipping wave.

## What shipped — 9 PRs merged + fleet-deployed (main `4b482c441`)

- **#2783** — #2780's sleep contradiction was the CHECKER misreading the wake-date frame
  (proven: live payload night_of 08-15 / as_of 08-16 matches the whoop partition);
  `is_wake_frame_correct` retires the class mid-cycle, scoped + pinned.
- **#2784** — IC-3 success leaves a positive log line (#2668 box-3 evidence upgrade;
  "absence of the failure line" was the exact class the original incident hid behind).
- **#2785** — `dashboard:date` learns the pre-compute morning window: an off-schedule CI
  smoke at 08:45 PT was injecting a false FAIL that re-armed `qa-smoke-failures` for a
  rolling 24h (#2670's live saturation driver).
- **#2786** — the #2758 lane-import guard: AST sweep of tests/ module-scope imports vs a
  single-source dep list, self-protecting, in-suite mutation proof.
- **#2787** — August ceiling $115/$135 → **$200/$235** (owner call vs the measured 171%
  projection; ADR-133 third amendment; September revert + $85 backstop unchanged).
- **#2788** — CloudFront custom error responses REMOVED (they rewrote API 404 bodies to
  HTML and API 403s to a 200 homepage); S3 website ErrorDocument repointed to
  `site/404.html` (it referenced a file that didn't exist); smoke pins both directions.
- **#2794** — **BodyScan 2 ingest-all + `docs/NEW_SIGNAL_PLAYBOOK.md` sanctioned as
  ADR-154.** 12 new meastypes incl. position-aware segmental parsing; SpO2-zero stored as
  absence, afib-zero kept as honest negative; Tier-2 owner-only for vascular/metabolic
  age; SoT rulings in SCHEMA.md.
- **#2795** — chronicle timeout trilogy (#2669): generation cache (a crash retry costs
  $0, and fills ONLY the void a crash left — a changes_requested regen stays fresh),
  reusable `common/timeout_watchdog` + `ChronicleTimeoutImminent`, cdk timeout 120→300.
- **#2796** — `post_cdk_reconcile_smoke.sh` handler check was latently red for ALL seven
  entries since #1653's packaging (first-dot-segment compare); fixed suffix-aware.

**Owner-authorized infra applied live:** `cdk deploy LifePlatformWeb` (error-response
removal, verified: API 404 → `404 application/json` with the handler's envelope) and
`cdk deploy LifePlatformEmail` (chronicle timeout confirmed 300s live) — the latter after
the CDK drift gate correctly REFUSED the pipeline deploy of the IAM diff (the system
working). **S3 lifecycle applied** (#2642): `deploys/` + `site/` noncurrent 7d/keep-1,
`raw/` untouched; census measured 93 GB noncurrent (85.9 under deploys/), found
**`imports/` as an unnoticed 2.2 GB all-ghost prefix** — flagged for owner, not touched.

## Verified

Every merge behind a full unpiped lane (exit + passed line read; final 19,307 passed).
Fleet lease approved at HEAD twice (0483ae3e, then the c3aaeccc rerun) — Deploy ✅ Smoke ✅
visual-QA ✅ both. Four stale leases rejected with reasons. Live probes: CloudFront
contract both directions; chronicle timeout 300s; reconcile smoke ALL GREEN post-#2796.
First governor run under $200/$235: mtd $99.77, projected $223.38 → **tier stays 1** —
the projection (not mtd) drives `_decide_tier`; an accepted overrun keeps tier 1 as
August's operating state by design (recorded on #2734).

## The coherence story (#2735/#2670)

The 18:45Z sentinel run — first scheduled run with the behavioral-excuse fix — WARNs the
MacroFactor rest state correctly AND stayed ALARM on **two genuinely new findings**, filed
as **#2792** (coach rows cite recovery 40 vs canonical 57, no grounding stamp — likely an
ADR-108 hold serving yesterday's row) and **#2793** (day_grade stored 68 vs derived 70).
The 18:30Z qa-smoke sweep was the **first zero-FAIL zero-WARN scheduled run on record**;
both saturated alarms clear ~15:46Z 08-17 when the off-schedule datapoint ages out.

## Gotchas hit (the durable ones are in memory)

- **Task-notification exit codes lie** (twice): the harness reports the wrapper's exit;
  `LANE_EXIT=1` with 22 failures arrived under a "completed (exit code 0)" notification.
  Only the output file's own line is truth (memory: `reference_task_notification_exit_codes_lie`).
- **Four guards caught four of my own mistakes pre-ship**: pin-consistency rejected a
  $DEPS indirection; the size ratchet forced extraction over registration; the
  metric-grant lockstep demanded the watchdog's IAM; design review caught the cache
  serving rejected drafts. Trust a red before overriding it.
- **The facade's imports are `_g`-seam surface**: removing an "unused" `timezone` import
  broke `chronicle_personas` at runtime — now noqa'd with the reason.
- Homebrew black 25.9.0 fights the pinned 26.3.1 — only `.venv/bin/black` is safe.
- Four rounds of doc-literal reconciliation across the 9-PR wave (rail-3 recipe each
  time) — the standing concurrent-merge tax.

## Wrap gates

**Build beat:** 2026-08-16-a-new-scale-arrives-and-writes-the-playbook
**Docs:** SCHEMA.md, NEW_SIGNAL_PLAYBOOK.md (new), DECISIONS.md (ADR-154 + ADR-133 3rd
amendment), docs/README.md + CLAUDE.md indices, COACH_STANCE.md re-verified,
PROPORTIONALITY.md (+#2758 lane-guard row — the #2380 ledger gate), INCIDENT_LOG.md (+1)
**Decisions:** ADR-154 filed (new-signal playbook) + ADR-133 third amendment (both merged)
**Main:** HEAD `4b482c441` was a swallowed push (ZERO runs minted — the #2762 class,
caught by check_main_green exactly as designed); re-dispatched as run 31973036045, in
progress at wrap; the last completed verdict is green at `c3aaeccc` (deployed HEAD-1,
diff since is the deploy-script-only #2796).
**Incidents:** 1 row added — the August ceiling raise as an accepted budget-tier event
**Stash/hooks:** clean
**Closures:** #2680, #2683, #2758, #2780 commented (contract shape; #2780 honestly
`partial` pending tonight's nightly)
**Backlog:** Now live at 22 actionable; no stale Later issues; hygiene — my three filed
issues (#2782/#2792/#2793) fixed to contract, **6 violations remain on #2797–#2802 from a
concurrent session's ~45-issue batch (#2797–#2841) — that session's wrap owns them**
**Alarms:** all red >72h cited (gate passed clean)
**CI warnings:** 1 — the perf-trend persist advisory on visual-QA (known #1435
IAM-staging/transient-S3 class, already documented there) — deliberate no-action this
session, it is #1435's existing scope
**Ledger:** #2758 row added to PROPORTIONALITY.md (posture load-bearing, rent ~2s/run,
demote trigger stated)

## Residuals / next picks

- **#2792** — the coach grounding-stamp investigation (the repaired alarm's first real
  catch; check ADR-108 hold verdicts for nutrition/physical coach 08-15→16). Best first pick.
- **#2793** — day_grade 68 vs 70 re-derivation.
- **#2735 / #2670** — observation boxes: alarms clear ~15:46Z 08-17, then the planted
  OK→ALARM proofs against clean baselines.
- **#2668** — closes Monday evening on 3-of-3 (positive-evidence log line now live).
- **#2669** — Wednesday's scheduled run is the live box (duration + no duplicate generation).
- **#2642** — post-sweep size measure ~08-23; `imports/` lifecycle decision (owner).
- **#2643** — Eight Sleep interior-gap backfill: data-write, awaiting Matthew's explicit OK.
- **#2761 boxes 2–3, #2674, pins #2759/#2760/#2755/#2757** — untouched this session.
- The **#2797–#2841 corpus** (concurrent session's filing wave) — next session triages
  from it via `backlog_next.py`; its 6 hygiene violators belong to that session.
- not-work — owner-only: CONTENT_FILTER_JSON arming (three `!` commands in-session),
  BotFather ×3 + first board-bot message, the gate:owner activation pick
  (#1738/#1571/#1677/#1631 — "none" fine).
