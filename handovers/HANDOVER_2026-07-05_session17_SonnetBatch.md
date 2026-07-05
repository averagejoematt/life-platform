# HANDOVER — the model:sonnet Now/Next/Later backlog, end to end: 28 issues → 30 PRs → merged, layer v112, deployed — 2026-07-05 (session 17)

> **This session ran concurrently with session 16** (the opus data-integrity quartet —
> #484/#483/#476, archived at `handovers/HANDOVER_2026-07-05_session16_DataIntegrityOpusQuartet.md`).
> Both sessions' work is now live on the same `main`; this handover covers only session 17's
> work. The two sessions collided repeatedly on `git stash` (see gotcha #1) and on the shared
> `site_api_common.py` doc-metadata counters, but never on actual logic — every collision was
> caught and verified before merge.

Matthew asked: "Look at all issues assigned to sonnet and complete all that are self-contained
(don't risk breaking my other agent fixing the opus issues)." After triage, scope widened to
"everything self-contained, any milestone" (~30 issues), then explicit authorization: **"you
handle merge and deploy."**

---

## Triage: 34 `model:sonnet` issues → 28 attempted, 6 held out

- **#583, #589** — depend on open `model:opus` issues (#582, #588) not yet closed.
- **#592, #594** — coach full-cast portraits chain; needs Matthew's visual sign-off per
  ADR-106 ("AI may sketch, only code ships, only Matthew approves"), not autonomous work.
- **#577, #578** — both required editing `evidence.js`, which opus issue #581 ("split
  evidence.js") is mid-refactoring. Held out specifically to avoid the collision Matthew
  asked to avoid. (Session 16 independently reached the same conclusion about #581.)

## What shipped — 28 issues, 30 PRs, all merged + deployed + verified

Each issue got its own agent in an isolated git worktree (parallel fan-out), then merged
sequentially with conflict resolution against a moving `main` (both my own merges and
session 16's concurrent ones). Full suite green throughout: **3442 passed, 0 failed** on
final `main`; `black`/`ruff`/`flake8`/doc-drift-gate all clean against the session-start
baseline.

**Infra/data (9):** #378 HAE token off query string (superseded by #500, closed — kept only
its regression tests as PR #665) · #379 sentinel post-reset grace window · #381 hermetic test
suite (found + fixed 4 latent `test_coaches_api.py` failures masked by local AWS creds) ·
#382 the dual-deployment-plane guard (`deploy/cdk_deploy.sh` + `check_deploy_drift.py` — used
for the rest of this very session's deploys) · #470 weather joins `source_registry` · #499
least-privilege ingestion secrets IAM · #500 HAE webhook edge into CDK (**this is the one
still not live — see Flags**) · #501 retry convergence onto `http_retry` (found + fixed a
real duplicate-write risk: Hevy's write client was retrying POST/PUT like GET) · #389
`sync_doc_metadata.py --check` promoted to a real CI drift gate (now enforced on every push).

**Site/data-honesty (7):** #383 phase-filter 30-day checkpoint (mechanism only — the actual
verdict is due 2026-07-14, correctly not fabricated) · #386 homepage hero reorder · #388
recovery-vs-deficit overlay (backend only; the chart itself needs an `evidence.js` edit the
agent correctly declined to make) · #400 email dark-mode + h1 pass · #419 coverage floor
9%→25% + mypy tier-2 on `web/` (also documented as ADR-107) · #479 food-delivery idempotent
re-import · #485 brief/digest strength sections repointed to Hevy.

**A11y/perf (2):** #579 focus-visible + ARIA tabs + popover trap (evidence.js's own tabs
explicitly deferred, noted in-PR) · #580 LCP/CLS budgets in `visual_qa.py` + font re-subsetting
(found current CLS is already borderline on data/method pages — flagged as a separate
follow-up, not fixed here).

**Coach intelligence (9):** #390 quality gate advisory→blocking (**bigger than it sounds —
see Flags**, documented as ADR-108) · #533 interaction memory (checked git history first,
correctly found #531 already covered board-Q&A) · #534 event-driven mid-week stance refresh
· #536 `RELATIONSHIP#state` gets its deterministic writer · #544 the Methods page (public
stat registry, unblocks opus #584) · #545 blind voice-fidelity harness · #548 Margaret
Calloway's chronicle red-pen · #549 journal-mood attunement for the mind coach · #552 "State
of Matthew" weekly brief · #553 coach memoirs.

Plus two fix-forward PRs found only by running the full suite on the final merged state:
**#668** (2 new Lambda handlers pushed the untyped-handler-count ratchet over its baseline —
typed them) and **#669** (`ruff` found 4 new import-sort findings — auto-fixed).

## Deployed and live-verified

- **Shared layer v111 → v112**, published via `LifePlatformCore`, all consumers confirmed on
  the new ARN.
- **CDK stacks:** Compute (3 new Lambdas — State of Matthew, Coach Memoir, Voice-Fidelity
  Harness), Email, Mcp, Operational. Every stack diffed before deploy; zero unexpected
  replacements.
- **site-api** redeployed (`deploy_site_api.sh`) — `/api/methods`, `/api/voice_fidelity`,
  `/api/state_of_matthew` all invoked directly, all return 200.
- **Static site** synced + CloudFront invalidated. `curl .../version.json` == `git rev-parse
  --short HEAD` exactly. `smoke_test_site.sh`: **67/67**. `visual_qa.py`: **33/33** (3 benign
  warnings — self-recovered 429 throttles, one honest sparse-data state on `/data/glucose/`).
- **`LifePlatformIngestion` was deliberately NOT deployed.** See Flags — this is the one
  loose end.

## Gotchas learned (load-bearing)

1. **`git stash` is repo-global, not worktree-scoped — never use it when parallel
   worktree agents (or a concurrent session) share one `.git` dir.** 6+ of my 28 fan-out
   agents independently reached for `git stash` and collided with each other and with
   session 16. Every collision self-recovered (`git fsck --unreachable` finds the dangling
   commit) and every final PR verified clean, but it was luck, not design. Saved to
   `feedback_concurrent_session_worktree.md`.
2. **Two independent PRs writing the "next" ADR number is a real collision.** #419 and #390
   both wrote `## ADR-107` independently (different content). Caught it during the merge
   phase, not before — renumbered #390's to ADR-108 by hand (`docs/DECISIONS.md` + the
   `adrs` count in `PLATFORM_STATS` + the `CLAUDE.md` pointer). Worth a lightweight
   reservation mechanism if concurrent-session ADR writes become routine.
3. **The `test_count`/`adrs` doc-metadata counters conflict on almost every merge** when many
   PRs stack off the same base — expected, mechanical, not a real conflict: take either side,
   `python3 deploy/sync_doc_metadata.py --apply`, re-commit. #389's new `--check` gate (this
   session's own work) means a missed re-sync now fails CI outright rather than drifting
   silently — a real improvement, but it also means every subsequent merge in a busy session
   needs this step or main goes red.
4. **A first-time CDK codification of an existing hand-created resource is a replacement, not
   an adoption.** #500's `HttpApi` construct for the HAE webhook diffs as `(requires
   replacement)` against the live `a76xwxt2wa` API Gateway — a plain `cdk deploy` would swap
   in a new URL. `cdk import` is the zero-downtime path; nobody's run it yet for this
   resource type. This is why `LifePlatformIngestion` is still on hold.
5. **`create_platform_lambda`'s default `Code.from_asset("../lambdas")` bundles the whole
   `lambdas/` tree per-function** — so most CDK-managed Lambdas don't strictly need a file to
   be layer-registered for their own cross-imports to work. The shared layer mainly matters
   for script-deployed functions (site-api, single-file `deploy_lambda.sh` pushes). Worth
   knowing before assuming every new root-level `lambdas/*.py` file needs a layer entry.

## Flags for Matthew

- **`LifePlatformIngestion` deploy needs your call.** It bundles #499/#501/#470 (all safe)
  with #500's HAE API Gateway codification (not safe to blind-deploy — see gotcha #4). Three
  paths, in order of my recommendation: (1) I attempt a `cdk import` to bind the existing
  `a76xwxt2wa` API Gateway — zero downtime, but untested for `HttpApi` constructs in this
  repo; (2) deploy now and you update the HAE iOS app's webhook URL right after — a real gap
  in CGM/BP/water/State-of-Mind ingestion until you do; (3) leave it as-is until you're ready
  to do #2 yourself. I didn't pick one — it needs your phone regardless of path.
- **#390 is a bigger behavior change than its title suggests.** Not a CI-gate flip — the
  coach-quality gate went from async fire-and-forget to synchronous-with-regenerate-or-hold
  inside the daily-brief pipeline. It's live now (deployed via the Compute stack). Measured
  first (206 real verdicts over 30 days) rather than guessed; worth your own read of ADR-108
  before the next daily brief runs, since a held cycle means that day's brief ships without
  that coach's narrative.
- **Housekeeping:** 4 harmless `RECOVERED: not mine` stash entries plus older pre-session
  stashes are sitting in the repo's shared stash list (`git stash list`) — safe to drop,
  their content already landed via the real PRs.
- **#544 (Methods registry) is done** — session 16's handover listed it as "not started";
  it shipped this session (PR #660), live at `/method/registry/`.
- **GitHub Pages still enabled+public** — carried forward from sessions 14/15/16, still
  unactioned.

## What's next

- **`LifePlatformIngestion` deploy** — your call per Flags above.
- **`cdk import` for the HAE API Gateway**, if you pick that path — untested territory,
  worth doing attended.
- **#581 — split evidence.js** (opus, deferred by both sessions) — the site-ux churn from
  this session (#579's new `tabs.js`, #580's font/preload changes, #386's homepage edit) has
  now settled; #581 should be safe to pick up next, still attended, still in a worktree.
- **#582/#584** (opus, chart interaction contract v2 / provenance popovers) — both were
  blocked or adjacent to work this session touched; #544 (Methods registry) specifically
  unblocks #584 now that it's live.
