# HANDOVER — Day-1 Next-tier drain: #1527 perf saga, wave 1+2 all merged+deployed, first /design-sync, the CI-outage discovery — 2026-07-19 (day)

> Instruction thread: "ultracode +2M — continue the backlog drain into the Next tier, same
> three-kinds-of-close contract. FIRST PICK #1527 (board perf), then #1526/#1404/#1372/
> #1373/#1378/rigor #1410–#1413/QA+design Next; first /design-sync; #1469 pilot prep;
> Sunday standing ops folded in early; all merges+deploys pre-authorized; wrap per /wrap."
> The five owner-decision slots (#1319, SNS, #1114, #1350, #1329) arrived as UNFILLED
> template brackets — treated as pending, no action taken on any of them.

## Outcome — 10 stories closed honestly (all SHIPPED + live-verified), 2 incidents found+fixed, 1 new incident-class discovery filed

**#1527 (flagship, solo — a three-act saga):** parallel+projected PREDICTION# fetches
(PR #1530) **regressed origin to 12–16s live** — boto3 Session-per-thread is GIL-bound
pure-Python setup at 256MB (~1/6 vCPU); laptop timing masked it. Hotfix #1532 (ONE
shared-table call shape; parity byte-identical) → ~2.4s; serve_stack 256→1024MB (#1534,
CPU scales with memory, ~cost-neutral) → **p50 0.58/0.66s, 3/3 clean cold-cache gating
samples** (each after a completed invalidation). Guard suite proven RED pre-fix; #726's
one-store pin follows the indirection. INCIDENT_LOG row for the regression window (P4).

**Wave 1 (worktree-implementers, every diff driver-verified, full suite no -x per merge):**
- **#1526** (PR #1528): deterministic `wait invalidation-completed` in sync_site_to_s3
  (creds-side) + bounded cache-aware smoke retries (`deploy/lib/cache_aware_fetch.sh`);
  the workflow's blind `sleep 60` removed; IAM GetInvalidation verified live + codified.
- **#1372** (PR #1529): the Evidence Bar — `stats_core.correlation_evidence` (sample/
  CI-width/FDR composition), additive `evidence` on /api/correlations + /api/discoveries,
  point-not-band at LOW; live (correlations honestly empty until the first weekly matrix).
- **#1378** (PR #1531): prereg hash-freeze — cycle-8 stamped honestly (frozen 07-18T22:02,
  stamped 07-19T06:56, both recorded), sha `4751…ed4f` **verified live via curl|shasum**;
  seal on the Prologue page; predict-week rebuilt from frozen specs (W29 — re-run Monday
  for W30, #1378 notes); the lock EMAIL is eve-only by design → first fires cycle 9.
- **#1373** (PR #1533): progression receipts — capture at fire time, replay verdicts,
  `SOURCE#character_receipt` (EXPERIMENT_SCOPED), /api/character_receipt live; **first
  receipt written + self-verified** (digest 842ff146…, replay_verified=true, engine 1.7.0).

**Wave 2 (rigor batch — real cross-PR engine conflicts resolved file-by-file, regenerated
generated pages via generators, never hand-merged):**
- **#1413** (PR #1538): SCED randomized start — pre-declared window, uniform draw frozen
  into prereg, Edgington permutation test on close, cards + method pages.
- **#1411** (PR #1539): fitted-not-authored effects — effect_fitter (lagged r, block
  bootstrap CI, BH-FDR, AR(1) n_eff), quarterly re-fit in hypothesis-engine,
  `SOURCE#effect_fits` (CROSS_PHASE), badges + /api/wrong stream. **First fit ran: 1/6
  fitted over 112d, 5 authored-prior — honest.**
- **#1412** (PR #1541): character targets from personal variance (p75 bands, MIN_N=30,
  fallbacks labeled "population prior"); engine v1.8.0 merge conflict resolved (kept
  1.8.0 + #1412's no-bump note); /method/game/ regenerated (engine v1.8.0 · config
  v1.6.0); config uploaded to S3; baselines snapshot seeded (n≈125 real bands).

**Solo interstitials:** **#1404** (PR #1537, fable): asymmetric-channel fulfillment index —
passive baseline (connection tap 0.5 / interactions 0.2 / journal-presence 0.15 /
values-Todoist 0.15, adoption-gated ADR-104: behavioral=0, pre-adoption=frozen), journal
enrichment adds a resolution block that provably cannot touch the verdict; live at
/api/fulfillment_index serving the honest Day-1 `insufficient_signal` (coverage 0.15 —
evening_ritual wiped at reset; adoption restarts with tonight's first tap). Coaching Day-1
static core (PR #1536 — #1528's live finding: /coaching/ had NO proof-static block; the
board published its first cycle-8 read mid-session, so live now bakes the REAL Kai
Nakamura read; the awaiting-block guards every future reset). Sunday-digest genesis-week
crash (PR #1540 — present-None `.get(k, {})` trap; digest redeployed + re-sent 18:20,
DLQ drained to 0). Nudge-test Sunday wall-clock repair (PR #1535 — main CI was RED on
genesis Sunday; dates pinned + detail-copy fix). Schema recaptures #1542/#1545.

**Design lane:** first **/design-sync** ran — created "AverageJoeMatt Design System v5"
(project bdbc3dc0-1a0c-41a2-9ab7-03b2de8ddf20), 78 files pushed + list_files-verified
(June archive untouched); #1464 fully closed. **#1469 pilot proposals authored + pushed**
(proposals/home-first-screen/, 19 files: 3 variants × preview/rationale/notes/screens) +
screenshots sent to Matthew for the pick (A loop-diagrammatic / B ledger-evidential /
C editorial; B flags a deliberate Litmus-5 trade).

**THE CI-OUTAGE DISCOVERY (#1544):** push-event workflows on main STOPPED QUEUING at
~18:17 UTC — six consecutive merges got zero CI/CD + zero Site-deploy runs while
PR-branch workflows kept running. Leading hypothesis: Actions spending-limit/minutes
exhaustion (private repo; the #1453 lane's exact fear). Billing API needs `gh auth
refresh -s user` (owner). Session response: manual `deploy_fleet.sh` (95/95 green, MCP
included) + `deploy_site_api.sh` + `sync_site_to_s3.sh` (its new #1526 invalidation-wait
visibly working) — **site at cec2a3c4 == main, smoke 152/152, nothing waited on the dead
pipeline.** Until resolved: every merge needs a manual deploy + a check that a run
actually queued.

**Sunday standing ops:** restart_verify 9/12 → 10/12 (day_n=1 ✓); **Withings genesis
weigh-in still missing** (partition empty cycle-to-date; ingestion invoked manually —
`no_data` 6 days back: scale hasn't synced or weigh-in didn't happen on it — attended).
Character sheet computed for 07-18 (pre-genesis honest Level-1). 17:00 brief SENT 17:07
(honest Day-0 F grade). Felt-probe verify (SOURCE#felt_probe + calibration n=1) lands
TONIGHT after Matthew's taps — next session or attended.

## Gotchas hit (durable ones → memory)
- Lambda CPU is memory-fractional: a perf change validated on laptop CPU can invert at
  256MB; boto3 Session construction is GIL-serialized; resource-derived `meta.client`
  auto-transforms values (typed AttributeValues mis-parse as Maps). Measure AT ORIGIN.
- Push-event CI can die silently while PR-event CI stays green — verify a run QUEUED
  after every merge (`gh run list --branch main`), not just that gates were green.
- `d.get(k, {})` doesn't guard a present-None key — the genesis-week empty read is the
  factory for present-Nones (digest crash class, recurs each reset).
- v4_build_* regeneration silently drops the #1468 chrome — ALWAYS re-run
  `v4_apply_chrome.py` after any page regeneration (test_site_chrome catches it).
- Generated-page merge conflicts: resolve by REGENERATING via the generator on the
  merged engine, never by hand-merging HTML.
- `gh pr merge` can report CLEAN then fail on a literal race — re-merge main + re-derive
  literals + push, don't fight the hint.

## Residual / next picks
- **Decision menu (Matthew)** — see the session-close message: #1544 CI outage (billing
  check needs owner auth), #1469 variant pick (screenshots sent), #1319 plan-vs-posture
  (unblocks #1338), SNS confirm-click (not-work — owner click), #1114 portrait pick
  (PR #1512), #1350 retention sign+run, #1329 ai-keys rotate, Withings weigh-in sync
  (not-work — physical-device check).
- Tonight attended (not-work — standing ops): first felt-probe taps → SOURCE#felt_probe
  + /api/character_calibration n=1; first connection tap re-adopts the fulfillment-index
  channel (coverage 0.15→0.65).
- Monday: re-run `deploy/build_genesis_predict_week.py --apply` for W30 (#1378 note);
  first Monday ops email carries the #1446 green report.
- Next-tier remainder: #1410 (Ghost/BSTS — fable, big), #1406, QA Next under #1425,
  design Next #1466/#1467/#1470–#1474, chat epic #1476 children (#1481–#1484), #1455.
- #1543 does not exist — issue numbering gap is #1544's neighbor; no orphan.
- Standing alarms (#1329 checklist): ai-keys staleness continues until Matthew rotates
  (one-command script ready); no other unactioned staleness known at wrap.

**Main:** green (5cacecba) — check_main_green exit 0; a push run DID queue for the final
merge at 19:20 and succeeded (partial resumption — the five middle merges + sibling
workflows still have zero runs, which points at a GH event-delivery incident over a hard
billing stop; #1544 updated with the evidence). Local full suite on the final tree: 5909
passed / 0 failed; fleet 95/95; smoke 152/152 at HEAD.
**Build beat:** `2026-07-19-day1-next-tier-drain` (this session).
**Docs:** SCHEMA (character_receipt, effect_fits partitions — in-PR), INCIDENT_LOG (+3
rows), qa exemption ledgers (in-PR), DESIGN docs untouched (sync used them as-is);
CLAUDE.md endpoint literal auto-bumped 116→118 by doc-sync.
**Decisions:** none needed — all governance-consequential choices landed inside existing
ADR frames (ADR-104/105 implementations; #1544's posture decision is Matthew's fork).
**Incidents:** 4 row(s) added this session (the #1527 12–16s regression window; the
Sunday wall-clock nudge main-CI red; the genesis-week digest DLQ crash; the wrap-deploy
TRUE-POSITIVE rollback — /method/registry/ 390px overflow from #1413's source token,
fixed #1546, deploy green, live-verified) + #1544 filed for the CI outage (row once
root cause confirmed — owner leg pending).
**Stash/hooks:** clean (one transient stash used+popped same-command during a
pre-existing-lint check — stack empty at wrap; hook fresh). Postflight's one 🔴 is
`email-subscriber: NOT DEPLOYED` — the #1350 owner-gated purge lambda awaiting
Matthew's sign + cdk deploy (pre-existing, on the decision menu; not this session's).

Prior session (overnight, same day): `HANDOVER_2026-07-19_AllNighter-BacklogDrain.md`.
