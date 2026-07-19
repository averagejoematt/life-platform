# HANDOVER — The all-nighter backlog drain: 44 issues closed (154→110), waves 1–4, Day-1 ops, the plan-gate discovery — 2026-07-19 (overnight)

> Instruction thread: "ultracode +4M — drive the OPEN ISSUE COUNT from ~154 toward zero,
> quality AND efficiency; every close is SHIPPED / VERIFIED-ALREADY-DONE / DISPOSED,
> never silent; triage table first; fan out disjoint smalls in verified waves; solo the
> fable stories; decisions pre-made: #1319 restore-the-gate LAST, prereg publish OK,
> SSM IAM grant + CDK parity, #1114 new portrait batch to a contact sheet, #1350/#1329
> to one-command readiness. Matthew pre-authorized all merges and deploys; honest count
> over theater." Full pre-session brief in the /clear message of session
> `session_016Xq3vYgSCzyaQ5zMXChh4M`.

## Outcome — 44 issues closed honestly (154 → 110 open), all live

**Triage first (the contract):** full-board table posted before building — 6 buckets;
3 epic rollups closed on child evidence (#717, #1194, #1195); the dispose bucket proved
honestly tiny (#1404 is NOT absorbed by #1403 — distinct passive-channel index; board
was well-groomed).

**Day-1 standing ops:** cycle-8 prereg PUBLISHED + live-verified (chronicle row, both
Prologue posts, manifest, invalidation — claims frozen). SSM cycle-param IAM grant
applied (Matthew's CLI had a line-continuation break — corrected via policy file),
then codified in CDK (`role_policies.site_api()` ExperimentCycleRead, PR #1485,
deployed) and the manual inline policy deleted — parity clean;
`/api/source_freshness` serves `experiment.cycle: 8` live. `restart_verify.py` 9/12
(3 fails = pre-genesis-PT timing: day_n=0, no weigh-in yet, no post-genesis sheet —
re-run Sunday, not-work — attended). Tonight's nudge fired with the full ritual
section (intake tap in). Tomorrow's SUNDAY nudge carries the NEW felt-reality probe.

**Solo (fable-class, each guard-red-proven, merged, deployed, live-verified):**
- **#1426 QA tier manifest** (PR #1493): `tests/qa_manifest.py` — 80 pages registered,
  archive entries GENERATED from `v4_build_evidence.REGISTRY`; all four hand lists
  derive from it (visual_qa 36=36 set-verified; restart_verify_rendered 35→77 pages,
  live 84/84 clean; smoke 22→80 pages; bindings 36=36); completeness gate proven red
  on an unregistered page. The four-registry trap is dead.
- **#1409 felt-reality calibration ledger** (PR #1499): weekly 3-item probe
  (felt_vitality/rest/connection) rides the signed one-tap rail Sunday-only →
  NEW `SOURCE#felt_probe` (raw_timeseries); `/api/character_calibration` — pearson r
  vs 7-day mean pillar level_score + Fisher CI on n_eff, ADR-105 grammar (no r below
  5 weeks, no band below 8), aggregates only; card + provenance line on
  `/data/character/`; gates in `experiment_gates.py`. 14 guards, all red on pre-fix
  origin/main. Live: honest `uncalibrated 0/5` on all three probed pillars.
- **#1464 design brief** (PR #1501): `docs/design/DESIGN_PARTNER_BRIEF.md` — north-star
  distillation, 10 hard constraints, **Slop Litmus v1** (10 points), proposals/<slug>
  contract, ADR-106 posture. (Sync-to-project completes on first `/design-sync` run —
  #1463's command shipped tonight too.)

**Fan-out waves (every PR adversarially verified or driver-reviewed before merge; 5
finding-verifier agents ran; ~50%-false-positive rule held — the verifiers caught real
issues):** Wave 1: #1477 MCP domain-filter fix, #1480 notion journal dark-guard, #1432
import()-graph gate, #1437 endpoint-count derivation (115), #1440 budget-pause
visibility, #1444+#1445 urgent-SNS IaC + qa-smoke metrics, #1453+#1334 GitHub billing
observability, #1228+#1257 drift-guard repo halves (AWS deletes verified live — closed
with evidence). Wave 2: #1495 todoist write trio (a verifier DISCOVERY — never worked
live), #1478 get_capture_queues, #1479 chat-mode library, #1462 design bundle builder,
#1431 JS unit harness (53 tests), #1436 API schema snapshots (105), #1376
career-vs-season, #1395 static core + OG (the crawler view lives). Wave 3: #1332+#1340+
#1342 wrap gates + INCIDENT_LOG backfill (9 rows), #1339+#1341+#1343 ADR hygiene
(+ADR-136 site auto-deploy governance), #1323 Makefile, #1325 main ruleset (LIVE:
ruleset 19162901 blocks force-push/deletion), #1326 hooks+stash cleared, #1331 rollback
keys on QA verdict, #1347 tombstone hardening, #1351 DATA_GOVERNANCE truth, #1329/#1350
code halves (one-command readiness — owner acts remain). Wave 4: #1454 surface-drift
gate, #1465 /design-implement, #1468 journeys + loop-forward CTAs (78 pages), #1427
sweep extension (79/79 live), #1428 tiered AI vision, #1463 /design-sync, plus the
schema recapture (#1525).

**Incidents found + fixed same night (all in INCIDENT_LOG):**
- **P3 genesis-eve 500**: `/api/fulfillment_ritual` 500'd ~4h — `_clamp_today` clamped
  UTC while handlers use PT uppers; recurs every future reset. Fixed (PR #1507) +
  regression tests + the pre-existing UTC-semantics tests realigned (PR #1521 after my
  own miss briefly redded main — full-suite-before-merge reflex re-learned).
- **Two site auto-rollbacks of healthy deploys**: (1) smoke asserted
  `/api/character_calibration` while the IAM Plan gate (R8-ST6, by design) blocked the
  fleet — pre-empted on the second pass by fast-path `deploy_site_api.sh`; (2) a
  CloudFront cache-race: smoke read a cached pre-deploy `/coaching/` — healed via
  manual `sync_site_to_s3.sh`, 121/121 smoke green after. (#1331's verdict-keying now
  live narrows the class; the cache-race variant is #1526.)
- **Driver error, owned**: a blind `git add -A` during queue reconciliation committed
  conflict markers into main via #1518 — repaired keep-both (bd96a14e), both gates
  (#1351 + #1347) preserved, full suite green.

**THE #1319 DISCOVERY (decision-menu head-item):** the production approval gate wasn't
deleted — it was silently DROPPED when the repo flipped PRIVATE (2026-07-13):
required-reviewers environment protection needs GitHub Team/Enterprise; the restore
call 422s on the current plan. #1319 + #1338 stay OPEN on Matthew's fork: (a) plan
upgrade (~$4/mo) → restore is one command (`gh api .../environments/production -X PUT`
with reviewer id 174924761, verified staged); (b) sign the gate-less posture into the
ADR (draft covers both branches, scratchpad `adr-1338-draft.md` — re-draft from issue
comments if lost).

**Verified at close:** fleet run 29675370138 — Plan GREEN (post-CDK-deploys), Deploy
GREEN, post-deploy checks GREEN (visual QA still finishing at wrap). Site at HEAD,
121/121 smoke, all five flagship live-verifies pass (honest calibration zero-states,
fulfillment 200, static cores, loop-forward CTAs, career/season fields). MCP
LastModified 05:56 UTC (68 tools). Full local suite 5757+ passed; only the documented
live-AWS i16 Day-1 flake (CI-excluded).

## Gotchas hit (durable ones to memory)
- gh pr merge shows a stale "has conflicts" hint right after a branch push — poll
  `mergeStateStatus` until it leaves UNKNOWN/DIRTY, then merge.
- NEVER `git add -A` mid-conflict — resolve file-by-file; parse-check before commit.
- Site smoke can race CloudFront invalidation on freshly-asserted content (#1526).
- The pre-commit hook auto-runs `sync_doc_metadata --apply` in worktrees — agents must
  revert literal churn; the driver reconciles per merge (held all night, ~15 merges).
- An agent's cwd dies when its worktree is auto-cleaned — `cd` absolute before git ops.
- GitHub environment protection silently drops on visibility flip (the #1319 class) —
  #1320's GitHub-leg asserts will catch the next one.

## Residual / next picks
- **Decision menu (Matthew)** — see the session-close message: #1319 plan-vs-posture
  (unblocks #1338), SNS confirm-click, #1114 portrait pick (PR #1512 contact sheet),
  #1350 retention window sign+run, #1329 ai-keys rotate (one command), #1330/#1336/
  #1345 owner acts, #741 publish, #1029 re-entry checklist (domain renews 2026-08-20),
  #1187 music bed, prereg — DONE tonight (published).
- Sunday attended (not-work — standing ops): `restart_verify.py` post-weigh-in; brief
  writes 64/20/94 natively; first probe taps land in `SOURCE#felt_probe`; first
  post-#1428 deploy shows "tier<=1: 6/36" AI-QA line.
- Now-milestone remainder: #1469 (pilot — needs design-project round-trip + Matthew's
  pick), epics #1425/#1460/#1461/#1476 close via children.
- #1526 smoke-vs-invalidation race hardening (filed at wrap).
- **#1527 FIRST PICK next session**: /api/predictions+calibration origin perf (~3.6s
  after #1505) — clears the /method/board/ LCP budget red on the fleet run's visual-QA.
- Standing alarms (#1329 checklist): ai-keys staleness still firing until Matthew
  rotates (now routed to the curated email, one-command script ready); no other
  unactioned staleness known at wrap.

**Main:** green (b473d028 — latest completed ci-cd run succeeded, verified via
check_main_green.py). Context: the earlier fleet run 29675370138 shows failure from its
Visual-QA job alone (Deploy/tests/smoke all green, fleet live-verified) — one real perf
budget breach, /method/board/ cold-cache LCP from #1505's ~3.6s origin endpoints, filed
#1527 (Now, first pick).
**Build beat:** `2026-07-19-backlog-drain-day1` (this session).
**Docs:** SCHEMA (felt_probe partition), CONVENTIONS §4c/§8a, DATA_GOVERNANCE,
INCIDENT_LOG (11 rows), DESIGN_PARTNER_BRIEF, JOURNEYS, CHAT_MODES, MANAGED_WHERE,
QA exemption ledgers, ADR-136 + ADR index — all shipped inside the night's PRs;
wrap adds SCHEMA felt_probe note verification + doc gates green.
**Decisions:** ADR-136 filed (in #1516); the release-topology ADR (#1338) deliberately
awaits the #1319 fork — not-work — owner decision pending.
**Incidents:** 2 row(s) added this wrap (05:40 cache-race rollback; the 03:45 rollback
+ genesis-eve 500 rows landed via #1514/#1507 earlier tonight).
**Stash/hooks:** clean (stash emptied by #1326; hook freshly installed; one accidental
autostash mid-session popped immediately).

Prior session (same day): `HANDOVER_2026-07-18_BigArchPaydown.md`.
