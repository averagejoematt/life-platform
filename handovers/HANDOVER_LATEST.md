# HANDOVER — Day-1 max paydown + the stale-PR flush: 11 PRs, 8 issues, queue emptied twice — 2026-08-03 evening → 08-04

> Instruction thread: *"maximum backlog paydown down the stored rank with the same operating
> model that worked: Fable drives only … every implementer a worktree-implementer on its issue's
> own model:* label; waves of ≤5 … deploy-per-merge, not end-batch"* — plus, mid-session:
> *"i see these 5 open prs in git for a while, can you decide whether to close, merge, squash,
> etc. these so they are cleared?"* and one live decision from Matthew: **#2084 → promote to
> config/ twin**.

**Main:** green (`2f120b5c` — final run completed success; every merge this session deployed and
gate-verified through six production-gate approvals). Three mid-session runs (7f4d24c7, cd69f763,
5fa8d52f) redded ONLY their Unit Tests job on the #2091 seed-path break — decoded below, fixed
same-hour by #2095; their Deploy/smoke/QA jobs were all green, no rollback fired.
**Docs:** ADR-148 + ADR-139 amendment + CONVENTIONS §4a0 + MANAGED_WHERE_LEDGER rows all landed
in-PR (#2094); layer-build runbook lives in PR #2100's body; no additional wrap-time pages needed —
the doc machinery is green.
**Decisions:** ADR-148 filed in-PR (#2094) — fast-lane required checks + auto-merge posture
(Option C), CodeQL settled as stays-advisory.
**Incidents:** 1 row added — main's full test suite red ~55min (the #2091 seed-path break;
deploy path unaffected).
**Build beat:** 2026-08-04-the-body-doesnt-reset-with-the-experiment.
**Closures:** #2085 #2080 #2081 #2084 #2089 #1662 #2093 #2099 all commented (ADR-099 two-line
verdicts; honest partials on #1662 and #2099 where the live half waits on owner-run commands).
**Backlog:** corpus fully contract-clean — `check_backlog_hygiene.py` prints **OK** (zero
violations zero advisories, first time including the queue rules); Now refilled by stored rank to
#2090/#1383/#1114 (all `model:fable`) plus **#2104** (opus, filed at wrap by the alarm gate);
Later sweep — no stale issues printed.
**Alarms:** 1 red >72h, cited — `qa-smoke-failures` is REAL genesis-week reader dishonesty
(a coach card citing pre-genesis 317.0 lb vs cockpit 322.0; a Home Day-1 temporal contradiction)
→ filed **#2104** (Now) + `docs/alarm_citations.json` entry; gate green.
**Stash/hooks:** clean — stash empty, hook freshness 🟢.

---

## What shipped (11 PRs merged, all deployed; 8 issues closed, 5 filed)

**The Day-1-bite pair + the class members found en route (the session's spine):**
- **#2080 + #2081 → PR #2088** (one PR, one implementer): the brief's per-source staleness scan
  and the anomaly detector's 30-day baseline both read cross-phase now. Premise check: both
  defects held verbatim — but the brief's claimed shared enabler was FALSE (neither site touches
  `digest_utils`; nothing was threaded). Non-vacuity proven by real revert (10/19 tests fail).
- **#2089 → PR #2092** (filed mid-session from #2088's verified leftover): the brief's trend
  windows (`_latest_item`/`fetch_range` — HRV, Banister CTL/ATL/TSB, weight, latest measurements)
  go cross-phase via a **taxonomy-derived** `include_pilot` — not a blanket flip, because
  `fetch_range` also serves `habit_scores` which is EXPERIMENT_SCOPED and must stay filtered.
- **#2085 → PR #2086**: a verified re-auth clears the AUTH_FAILURE breaker latch in the same
  script run — wired through `setup/oauth_reauth_common.py` into all six oauth-facet re-auth
  scripts, set derived from the registry, coverage test guards future scripts.
- **#2084 → PR #2091** (owner decision: promote to config/ twin): measuring changed the bytes —
  the bucket-root "live" object was itself the superseded 2026-07-11 cast; the roster-clean
  #1904 bytes (site/config) are the twin. **Live defect fixed:** `/api/challenges` served 49
  off-roster names; post-merge twin sync → **0 off-roster, 39/39 twins match** (live-verified).
- **#1662 → PR #2094**: branch protection Option C as settings-as-code (`apply_branch_protection.py`
  dry-run/apply/check, github_posture.json, drift-sentinel GitHub legs, ADR-148). **The live
  mutation did NOT apply** — needs a repo-admin token (`GH_POSTURE_TOKEN` unset; sandbox blocks
  settings mutation). One owner command closes it (below).
- **#2093 → PR #2096**: the weight-recency test's import-time `TODAY` vs call-time `now()` flake
  (bit #2092's own suite run at UTC midnight) — pinned through the repo's frozen-datetime seam,
  with an explicit midnight-boundary test.
- **#2099 → PR #2100** (filed from the dependabot verification, below): scripted deterministic
  builds for the binary Lambda layers + manifest drift gate + fixed the **inert
  `PILLOW_LAYER_VERSION`** (operational_stack hardcoded the v1 ARN — env bumps deployed nothing).
  Findings: Pillow 12.3.0 is fully audit-clean; garth layer really carries 6 advisories (rebuild
  clears 5); the last one needs the 0.3.x auth migration → filed **#2101** (Later).

**Driver fix-PRs:** **#2087** — the hygiene checker's score-arithmetic advisory false-fired on
exact half boundaries (0.375→0.38 tripped the float epsilon; `.2f` would trip 1.125→1.13
half-even); Decimal ROUND_HALF_UP on both sides. **#2095** — `test_privacy_guard` still opened
`seeds/content_filter.json` after #2091 promoted it; redded main's full suite (the PR fast lane
never runs that test).

**The stale-PR flush (owner ask, all 5 cleared):** #2096 was already merged; **#1768** (portrait
option round) closed unmerged with the work preserved at `ff5c74fadcd7` — ADR-106 makes the pick
owner-only, #1114 stays open; **#1779** superseded by **PR #2097** (black 26.3.1 taken atomically
with the 79-file reformat + every pin location + two dead pip-audit waivers retired);
**#1778/#1780** closed with measured rationale — pillow/garminconnect ship via **offline-built
layers**, so the manifest bumps deploy nothing, the manifests were stale in the *opposite*
direction (live: Pillow 11.3.0, garminconnect 0.2.40), and garminconnect 0.3.x is
code-incompatible with the lambda's garth-injection auth. **PR #2098** corrected the manifests to
the verified deployed versions.

## Verifications run

- Cycle-12 wrap deploy + build beat confirmed live before starting (85 beats, all green runs).
- **#2079 acceptance box 4: still not confirmable** — every 08-03 coach run (17:01–17:40Z,
  reset-transition window) logs `0 gradable / N qualitative (0%)`; needs the first genuinely
  post-genesis run. Check `coach-state-updater` CloudWatch logs on 08-04 (#2079 closure comment
  already records this).
- Day-1 brief sane: one real send 17:10Z (grade 40/F prices pre-genesis Aug 2), honest source
  presence (macrofactor 0 = the 24h lag), `JOURNAL_COACH BLOCKED empty` = the known genesis-week
  present-None class, brief still sent.
- Worktree cleanup: **134 → 19** registered worktrees (112 pruned — merged-PR branches with clean
  status only; 14 CLOSED-unmerged + 1 open-PR + 1 dirty + brand-marks all deliberately kept).

## Gotchas worth carrying

- **An implementer that reverts the doc-sync pre-commit stamp reds its own PR's wiki gate** — the
  stamp is REQUIRED on the branch (the gate checks the merge preview). The working flow: implementer
  commits what the hook stages; driver regenerates via `sync_doc_metadata.py --apply` at each
  rebase. Three rebases this session, all clean under that flow.
- **"Live is truth" needs ALL the copies on the table** — #2084's bucket-root object was newer
  than the seed but older than the third copy (`site/config/`, the #1904 roster-clean). The
  implementer's parity test caught it before the twin codified a live defect. Measure-first
  premise falls this session: 3 (digest_utils enabler, live-is-truth, dependabot's
  manifest-deploys-something assumption).
- **The PR fast lane does not run the full suite** — #2091 broke a main-only test (seed-path
  read in `test_privacy_guard`), invisible until the push run. With ADR-148's required checks
  scoped to the fast lane, this class lands by design; the full suite stays the push-run's job
  and the fix bar is same-hour (#2095 was one line).
- **Dependabot watches manifests that may deploy nothing** — layer-shipped deps (pillow, garth)
  are structurally invisible to it; #2100's drift gate + measured `.deployed.json` manifests are
  the counter. The `pip-audit` coverage was also blind: `garmin.txt` pinned 2 of the 14 packages
  actually in the layer.
- **`gh pr merge` on a conflicted PR fails cleanly** (GraphQL "merge conflicts") — the doc-sync
  literal is still the usual suspect; resolve at rebase one file at a time, then regen.
- The exit-code-eats-pipe trap bit ME this session (`--check | tail; echo $?` read tail's exit) —
  re-verified state read-only before believing the apply had run.

## Residual / next picks

- **Owner, one command:** `python3 scripts/apply_branch_protection.py --apply && python3
  scripts/apply_branch_protection.py --check` from main with a repo-admin token
  (`GH_POSTURE_TOKEN` or an admin gh login) — then watch the next merge-day's reconcile push
  land (the bypass is the one production-only assertion). #1662's closure comment carries the
  same runbook. not-work — owner-only act (token + settings mutation).
- **Owner-approved deploy:** the layer rebuild (PR #2100's runbook: build zips → pip-audit →
  publish → env-var bumps → `cdk_deploy.sh LifePlatformOperational` + `LifePlatformIngestion` →
  `--promote` the manifests → watch the next Garmin run + one OG generation). #2099's boxes 2/4
  stay open until then. not-work — CDK deploys are owner-ask-only per standing rule.
- **#2079 box 4** — read `coach-state-updater` logs after the first post-genesis run (expect
  gradability >0%); recorded on the closed issue. not-work — verification step on a closed issue.
- **#2104 (P2, Now, opus) — genesis-week reader dishonesty**: coach cards cite pre-genesis
  numbers until their weekly regen; Home Day-1 temporal contradiction. Found at wrap by the
  alarm gate; qa-smoke has been honestly red on it since genesis. Top non-fable pick for the
  next session.
- **Now queue (model:fable):** #2090 (ratchet constant-key blind spot, 1.00), #1383 (Coach
  Line channel, 0.94), #1114 (portrait art direction v2 — reopen from branch
  `issue-1114-portrait-art-v2` @ `ff5c74fadcd7`, per the #1768 closure).
- **#1872 blocking flip** — its precondition ("a clean ungroomed day") is now genuinely met: the
  corpus prints OK with zero violations AND zero advisories including queue rules.
- Prior-session owner items still pending: 3 CodeQL dismissals (#2046's alerts 131–133), PR
  #2012's revision purge, review of the Aug-5 first live Wednesday subscriber send. not-work —
  owner-only acts carried from the 08-03 handover.

Full narrative of the prior session: `git show
origin/session-archive:handovers/HANDOVER_2026-08-02_cycle-12-sealed.md`.
