# Handover — 2026-08-31 (FABLE 5): Session O — the September-eve drain, then the LAUNCH

**Session:** Claude Fable 5, plan-mode entry twice. Two driving asks, sequential: (1) "close
as much of the open issues as possible" + a verdict on review/bash/sanity timing; (2) mid-session
owner pivot — "full website and experiment refresh with a new cycle starting September 1st …
the true official launch … tomorrow I want to shift to being a USER of the platform … Fable
at 5%, everything else Opus or lower." Both plans were approved and both executed to done.

## What shipped (all merged AND deployed/live)

**The drain (16 issues closed, 11 PRs merged):**
- Epic **#2363** (coaches' phone) closed — all 20+ children were already closed; ask delivered.
- Epic **#2801** (September cost base) closed on its Outcome, VERIFIED live at 00:00Z:
  `effective_ceiling=$252` (the permanent $215 base in earned surge, 1,011 uniques),
  `computed_tier=0 prev=2`, no deploy needed. Datum posted to #2883.
- The 8-PR wave: #3380 (batch floor, #3372), #3381 (S3 lifecycle 7d→1d, #3368 — rule verified
  live), #3382 (stale cost table, #3371), #3383 (the #3379 reader-truth structural ruling —
  a temporal_contradiction citing no temporal value cannot gate; 14th ledger ruling),
  #3385 (EMF census budget 120→186 derived, #3370), #3386 (monthly_close assembler +
  5 skill upgrades, #3375 — reproduced August's close to the cent), #3387 (deletion-batch
  docs, #3377), #3388 (weekly analyzer cadence at the CDK rule, #3366). Plus #3389
  (the #3384 mixed-PR test_count exemption, LIVE-PROVEN on its own PR).
- **#3367 closed on a measured NEGATIVE result** (~$1.5/mo, not $4–6; obstacle is prompt
  restructuring, not the cache floor) — rejection logged in the Cost Decisions Log.
- **Owner-granted executions:** the six pending cdk deploys (#3365 closed — zero Plan
  warnings on the tip run, Web CloudFront change read first: em-dash mojibake, comment-only);
  the #3377 deletion batch (buddy-auth secret scheduled-deleted, recoverable to 09-30; both
  us-east-1 billing alarms gone, verified).
- **#1407 → Now** (cycle's one sanctioned Roadmap promotion), **#1365 → Roadmap**, **#3378 → Now** (e9 refill).

**The launch (cycle 15, genesis 2026-09-01):**
- `restart_pipeline.py --genesis 2026-09-01 --override-weight-lbs 326.24 --with-preregistration
  --apply --sync-site` — all three hard gates green (96/96 rendered, 8/8 semantic, AI truth
  clean at 1d pre-start). Site live in countdown; flips to Day 1 at PT midnight automatically.
- Prereg sealed + published (public SHA-256 at `/experiments/prereg/genesis-2026-09-01.sha256.json`),
  predict-week seeded W36. **Prereg lock email deliberately SKIPPED (owner: no email).**
- **Launch prose live** (PR #3393): home + cockpit in launch voice, "starts at the Day-1
  weigh-in" kept verbatim (zero reader-truth coupling), the home beat-cycle panel and cockpit
  "Attempt #N" masthead retired (archives intact); PR #3392 data-bound the attempts count;
  PR #3391 wrote `docs/OPERATING_RHYTHM.md` + the 30/60/90 checkpoints in the operating
  calendar (Oct 1 / Oct 31 / Nov 30, new `starts`/SCHEDULED state — second-read verified sound).
- **Day-1 automation:** cloud routine `trig_01GaG74B22Qfs4yLKbgrEQpZ` fires 03:00 PT →
  verifies the public surface, reports to **#3390** (silent-when-green). #3390 also carries
  the AWS-side hygiene runlist (countdown-gap sweep → prereg-void sweep → supersede reflex →
  integration check) for the first September bug-fix session.
- Final site-deploy (the launch beat + regenerations): **every gate green** — Deploy, smoke
  246/246, visual+AI QA, no rollback.

## Verified
- Live: launch prose rendered (old paragraph absent from rendered body), beat-cycle gone,
  `data-att-starts` bound; countdown numbers honest (nulls by design); freshness genesis
  2026-09-01 after the site-api redeploy; smoke 246/246.
- The reset's own three gates + local test batteries per PR (all real output, cited in PRs).

## Gotchas hit (each fixed structurally, none re-pinned)
1. **A future-genesis reset breaks every time-anchored test family** — five in one night:
   wire-replay corpora (now run under their RECORDED frame), the 2941 boundary instants
   (regenerated), the render gate's wall-clock dependence (clock now PINNED to the site's own
   genesis+5d — derives, so future resets auto-anchor), the prereg seal (tier-2 pause, deferred
   honestly to the 00:00Z drop), and the token-alarm stamp test (now derives a not-committed
   genesis; a pinned date fails on exactly its own cycle's eve).
2. **`gh run rerun --failed` re-tests the run's ORIGINAL merge commit** — post-main-fix reruns
   fail identically; `gh pr update-branch` is the cure (memory + CONVENTIONS row added).
3. **The reset doesn't ship site-api's own-path bundle** (#3396) → the public API served the
   OLD genesis → the #2878 smoke check tripped → **the scope-blind smoke rollback reverted
   wanted prose** (#3395). Fixed live: site-api redeployed, attended re-sync, all green.
4. The #2899 docs-only class hit twice in one day (badge red + the ledger snapshot).
5. Cloud routines have NO AWS credentials — Phase F was split public-surface (routine) vs
   AWS-side (#3390 runlist).

## Gate lines
**Build beat:** 2026-08-31-the-september-first-launch
**Docs:** OPERATING_RHYTHM.md (new) + README index, SCHEMA.md genesis literal, CHARACTER.md
cycle-15 re-verify, CONVENTIONS §6 rerun-merge-ref row, INCIDENT_LOG +2, alarm_citations
s3-size re-pointed, OPERATING_KNOWLEDGE_LEDGER +1 row/snapshot
**Decisions:** none needed — the launch executes ADR-077/ADR-133 and owner decisions recorded
on their issues; no new governance posture
**Main:** green (51c040230) — the approved tip run 33459108973; badge history: red at boot
(#2899 class, fixed), every intermediate lease disposed (3 approved tips, 5 rejected ancestors)
**Incidents:** 2 rows added — the launch-eve scope-blind rollback (#3395/#3396), and the double
#2899-class docs-only red
**Stash/hooks:** clean
**Closures:** #2363, #2801, #3365, #3366, #3367, #3368, #3370, #3371, #3372, #3375, #3377,
#3379, #3384 commented (16 closed incl. milestone moves) · DoD: scanned, hits 1 (#2801
epic-children-open) — dispositioned by re-homing #3369/#3373/#3374/#3376 as standalone
under review:fin-diligence-2026-08-31; re-sweep hits=0
**Backlog:** Now 4 actionable (#1407, #3378 promoted with both edits, #3390, #3396); Later
sweep — no stale Later issues printed; NO REMEDY escalation not needed
**Alarms:** all cited — s3-bucket-size re-pointed to the shipped lifecycle cure with a 09-03
expiry; qa-smoke pair cited (fix deployed, tonight's run is the check); no uncited flaps
**CI warnings:** none — latest completed main run pending at gather; the (e11) scan of the
prior green run printed nothing to triage
**Ledger:** none — no standing machinery shipped (the Day-1 routine is one-shot and
auto-disables; the operating-calendar rows are entries in an existing instrument)

## Residuals / next picks
- **#3390** — Day-1: read the 3am routine's verdict, then the AWS-side runlist (~10-15 min,
  Opus). The supersede reflex lands the real Day-1 weigh-in as baseline.
- **#3396** — the reset pipeline ships site-api (Now, sonnet). **#3395** — smoke-leg rollback
  scope (Next, opus). **#3378** — the docs-only badge inheritance (Now, sonnet). **#1407** —
  Monarch (Now, fable-tagged; owner may re-lane).
- **#2883** — September clean-month drift read accumulates; n=30 re-decision late September
  (not-work — dated measurement, gate:owner).
- Verify tonight's nightly qa-smoke goes clean and `qa-smoke-failures`/`-warnings` return OK
  (the #3379 ruling's last acceptance box) — not-work — self-verifying overnight; if still lit
  next session, that is a NEW finding to file.
- s3-bucket-size alarm: citation expires 09-03 — if still ALARM, file (not-work — dated
  self-clearing window, carried in docs/alarm_citations.json).
- **September posture (owner decision):** sessions are bug-fix-only on Opus or lower; Fable
  is incident reserve; feature re-entry ONLY at the calendared 30/60/90 checkpoints
  (not-work — standing posture, lives in docs/OPERATING_RHYTHM.md).
