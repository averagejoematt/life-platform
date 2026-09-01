# Handover — 2026-09-01 (Opus 5): Session P — the Day-1-eve bug drain

**Session:** Claude Opus 5, plan-mode entry. The owner's ask arrived in two parts: a plan
under the September posture ("opus or below only, no fable as we are out of credits"), then
mid-plan — *"basically i want this plan to be paying down as many bugs and open issues"*.
Two clarifications answered live: `#3390`'s post-genesis runlist waits for tomorrow, and no
paid reader-truth re-run tonight. One numbered ask mid-session (the #3402 production
deploy) — approved.

Context: this was the four hours before Day 1 of the launched experiment. Genesis
2026-09-01, site in countdown, flipping at PT midnight.

## What shipped (all merged; one deploy owner-approved and in flight)

**Main was RED at boot and is the first thing that moved.** `59773c2d4` (Session O's wrap)
left `docs/INCIDENT_LOG.md`'s derived Patterns section stale. Regenerated and pushed as
`f82c44f0d`; Docs CI green. That red then became the session's best evidence — see #3378.

**Four PRs, three issues closed:**

- **#3397 → closes #3378** (`dc96746fb`). Removed `ci-cd.yml`'s push-to-main `paths:`
  filter entirely. The issue offered three mechanisms and asked for a measured choice;
  option (b) won once the cost was actually measured: **~39 min wall, $0** (public repo on
  `ubuntu-latest`), and **no added deploy or AI spend** — `plan`'s matrix diffs only
  `lambdas/ mcp/ mcp_server.py`, and `visual-qa` carries `needs: deploy` with no `always()`.
  Scope widened deliberately: `scripts/**` was never on that filter either, though ci-cd's
  own lint job black-checks it. **The list was the defect**, so the cure is no list, pinned
  by `tests/test_ci_main_push_coverage.py` and mutation-proved.
- **#3398 → closes #3396** (`8398131fa`). `restart_verify.py` check 20: the SERVED
  `/api/source_freshness` genesis must equal the staged genesis. **The filed mechanism was
  disproven first** (below); this is the cause-agnostic detector for the symptom.
- **#3400 → #3374 R2 of 3** (`586e96848`). A `COST_TRACKER` Monthly Actuals row growing
  >1.15x must name a `driver:`. Threshold derived, not chosen — the founding incident
  (+16% Jul→Aug floor creep) is 1.158 and *just* trips it.
- **#3402 → closes #3401** (`60edf1e32`). R7's night floor bounded by
  `min(genesis - 1, today - 1)`. Deploy **owner-approved this session**; it reaches the
  qa-smoke Lambda on the tip's lease, which was still forming at the wrap.

**Three issues filed, each with the measurement that justifies it:** #3399 (the reader-truth
judge labelled a self-withdrawn finding `basis: impossibility` and it gated; `basis:
"withdrawn"` was emitted **0 times in 35 findings**), #3401 (fixed same session), #3403 (the
Unit Tests duration budget now sits at the *mean*, not the ceiling).

## Verified

- **Check 20, live in the real verifier**, not just its unit tests:
  `✓ served /api/source_freshness genesis == staged genesis (#3396) — served=2026-09-01
  staged=2026-09-01`. `restart_verify.py` ran 20/24; the four failures are the expected
  pre-genesis states #3390 already predicts.
- **The midnight flip**, checked before it fires: `pre_start_meta()` returns `None` once
  `EXPERIMENT_START <= today(PT)` — a structural no-op derived from the Pacific date, so it
  self-flips with no deploy. 9 tests green. `/api/journey` and `/api/snapshot` are
  `no-cache, no-store`; `/api/wall` is CDN-cached 3600s and can show cycle 15 as `staged`
  for up to an hour past midnight (recorded on #3390, self-heals).
- **Launch-eve site smoke**: exit 0.
- **#3401's fix in all four directions**, incl. a negative control on the *floor itself*;
  654 tests across the plausibility/reader-truth/temporal/genesis selection.
- Per-PR: full local batteries, `flake8`, pinned `black`/`ruff` via `agent_commit.sh`; every
  merge gated on the required check set **asserted by name**, and every push swallow-checked.

## Gotchas hit

1. **A filed issue's mechanism is a hypothesis.** #3396 said `cdk deploy --all` does not
   ship site-api's code. It does (`lambda_helpers.py:309` → `staged_tree_asset()`), and CFN
   shows `SiteApiLambdaA5C2FE08 UPDATE_COMPLETE` at 20:13:43Z *inside* the reset's window.
   Four hypotheses eliminated in total (code channel, the deploy, the staged asset's actual
   contents on disk, CDN caching). **The mechanism is still unexplained and is recorded as
   such** — shipping the filed fix would have added a redundant deploy and masked it.
2. **Removing the path filter moved two consumers CI found and local greps did not** — a
   module-scope `yaml` import that crashes the deploy-critical lane's whole collection, and
   `PUSH_TRIGGER_GLOBS`, whose parity test said "update the detector" in its own failure
   message. Three recorded incident replays now run under their **recorded** filter.
3. **The CI-warnings gate passes by DEGRADE after a lease rejection.** A rejected run is the
   latest completed and is not green, so the gate reports "nothing to triage yet". Absence
   read as success, in the wrap's own battery — caught by re-running it standalone.
4. **`gh api runs?per_page=10` truncates the lease enumeration.** A lease waiting 1.1h on
   `8398131fa` was invisible to it and surfaced only in `check_main_green`'s output. Use
   `per_page=100&status=waiting`.
5. **A lit alarm's citation may contain no closed `#N` anywhere** — including cross-refs in
   its `note`. Citing the issue I had just closed reds the gate twice over.

## Gate lines

**Build beat:** none — every item is internal CI/verifier/gate mechanics with no
reader-visible change, and the launch beat shipped <24h ago; a second beat about our own
path filters would dilute it.
**Docs:** `CONVENTIONS.md` (§4a0 gains the canonical no-filter rule with its measured cost;
the #2899 block at §3 corrected — it stated the filter still declines docs-only pushes,
which #3378 made FALSE; the DEVOPS-01 ledger row and the swallow-detector row annotated),
`alarm_citations.json` (both qa-smoke entries re-cited from measurement)
**Decisions:** none needed — #3378 executed an option the issue itself offered and the cost
was measured, not chosen; no new governance posture
**Main:** green (51c04023) — the tip `28167dacb`'s own run was still in flight at the wrap;
two superseded ancestor leases REJECTED (`8398131fa` waiting 1.1h and invisible to a
`per_page=10` enumeration; `6601cf525`, which predates the R7 merge). The tip's lease is
owner-approved for approval when it appears — it is the only one carrying the R7 fix
**Incidents:** 1 row added — the boot-state docs-only red (#2899 class, third specimen,
cured by #3378 the same session)
**Stash/hooks:** clean
**Closures:** #3396, #3378, #3401 commented · DoD: scanned=4 hits=0
**Backlog:** Now 3 actionable (promoted #3369 and #3374, both `model:opus`, both with the
score-line arrow retargeted); Later sweep — no stale Later issues printed
**Alarms:** all cited — `qa-smoke-failures` newly cited in prose (its owning issue closed
tonight because the cause is fixed); `qa-smoke-warnings` **re-cited because its reason had
rotted**, not aged — it blamed a Withings gap, and `WarnCount` by day (0/0/2/1 against
ChronicWarnCount 8/7/11/11) plus the run log show the sole non-chronic warning is Todoist's
missing 08-31 record
**CI warnings:** unverified — the gate degrades to "nothing to triage" because the latest
completed main run is a rejected-lease run, not green. Triaged by hand off the last green
run (51c04023): 6 pending-owner cdk deploys (standing owner-gated class, accumulated from
the evening's merges — no action, needs an owner-granted `cdk deploy`); 1 smoke
content-truth failure (= the R7 bug, fixed by #3401); 1 unit-test duration budget (measured
n=4, → #3403)
**Ledger:** `MoM close delta clause` row added to `docs/PROPORTIONALITY.md` (#3374 R2 —
~0s CI, $0, one token per tripped month; demote trigger stated both ways)

## Residuals / next picks

- **#3390** — Day 1: read the 03:00 PT routine's verdict, then the AWS-side runlist. This
  session left it **pre-flighted**: `restart_verify.py` run read-only, escapees are **3**
  (habit_scores 1 · computed_metrics 1 · circadian 1) in window
  `[2026-08-31T20:16:14Z → 2026-09-01T07:00:00Z)`. Reconciler order unchanged.
- **#3403** — the Unit Tests duration budget, measured (mean 1942s vs a 1950s budget, spread
  53%). Shed, do not raise.
- **#3399** — the reader-truth `basis` channel is populated and wrong; needs a mechanism
  decision measured against the recorded 35 findings in run 33451827346.
- **#3374 R1 + R3** — R1 can extend an existing census (`model/platform_model.json` already
  derives 2 of the 5 counts); R3 needs real per-feature spend measurement first.
- **#3395** — designed in full on the issue (derive the surface from each check's URL, reuse
  `visual_qa_verdict.py`'s vocabulary, use the existing synthetic-injection hook for the live
  proof). Deliberately not shipped on launch eve.
- **#3369** — promoted to Now; tonight's #3399 finding is direct evidence for it.
- Verify the R7 fix reaches qa-smoke and the alarm clears — **but not from the alarm alone**:
  it has two independent clearing paths and only one of them is the fix (stated in the
  citation). *not-work — dated overnight observation, homed on #3390's runlist.*
- `qa-smoke-warnings` should clear after the 2026-09-01 14:00 UTC Todoist ingestion.
  *not-work — dated self-clearing state, carried in `docs/alarm_citations.json`.*
- The **#3396 divergence has no established mechanism** and deliberately gets no speculative
  carrier. *not-work — check 20 is the detector and will name it if it recurs.*
- **September posture unchanged:** owner USES the platform; sessions bug-fix-only on Opus or
  lower; Fable is out (no credits); feature re-entry only at the 30/60/90 checkpoints.
  *not-work — standing posture, lives in `docs/OPERATING_RHYTHM.md`.*
