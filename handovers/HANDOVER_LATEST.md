# Handover — Session AA: the poller stopped before he did, and three gates were grading the wrong thing (2026-09-11 ~20:30 PT → 2026-09-12 ~19:30 PT)

**Driver:** Opus 5 (1M). Started as one owner question from the gym floor — *"is the api down? i did log a hevy workout today"* — and became a session about instruments that report confidently on state they cannot see. Owner escalated mid-session to *"i want you to drive it all, get all the deploys etc."*

## The question, and the real answer

Not down. `hevy-backfill` ran `cron(0 12-23 * * ? *)` — hourly, **05:00–16:00 PT**. He finished lifting at **17:30 PT**, 90 minutes after the last poll of the day. The session would have been invisible to every consumer until 05:00 the next morning: an **~11.5h blind window**.

Nothing failed. All 12 runs that day returned `ingested: 0`, `errors: 0`, each `since` window contiguous with the last. The comment above the schedule read *"Adjust if Matthew lifts later."*

**Nothing could have caught it.** Hevy's `stale_hours` is `7*24` — correctly lenient, because lifting is event-driven and a rest week must not read as an outage. A behavioral source with a 7-day threshold **cannot detect a same-day miss by construction**. The owner noticed; no instrument did.

## Shipped (all merged AND deployed, verified live)

- **#3720 / PR #3723** — hevy polls 24h. Widened to `cron(0 * * * ? *)` rather than to a later cutoff: moving the boundary relocates the same bug to whatever hour he eventually trains past. Live: `cron(0 * * * ? *)` ENABLED, target wired to `hevy-backfill`. Deployed via `cdk_deploy.sh LifePlatformIngestion` (both drift guards green) **and** re-applied by CI/CD run 34727155274, whose own reconcile job pushed the tip it then deployed.
- **#3725 / PR #3727** — the accuracy gate called a **beaten** Zone-2 target impossible. `/api/zone2` served `target_pct: 118` (177 min against a 150-min target, `target_met: true` in the same object) and `scan_impossible_pcts` returned three HIGH findings, failing the site deploy. It is the deploy-GATING copy, so it would have blocked **every** site deploy until his weekly Zone-2 fell back under 150 — the pipeline blocked by him training well. Bounded at 1000%, not exempt. Live: 3 findings → **0** across `/api/zone2`, `/api/observatory_week`, `/api/vitals`.
- **#3729 / PR #3730** — the alarm gate's live-cause read was truncated. `fetch_qa_smoke_causes` read ONE page of `filter_log_events`; CloudWatch pages **by log stream**, so page 1 held `CAUSE fail none -` from 09-11 while page 2 held the 09-13 01:20Z `coach_labs:truth`. It reported a **lit** alarm's cause as "no failures". Now paginated AND timestamp-sorted — the second assumption (concatenated pages are in time order) was false too.

**Recovered immediately:** a manual `hevy-backfill` invoke pulled the missing session — `ingested: 1` → `DATE#2026-09-11#WORKOUT#f6e41751…`, 7 exercises, 21 sets, 10,942.93 kg, adherence `matched` 100%.

## Filed, not fixed

- **#3728** — *the one that matters to a reader.* The labs coach's served `position_summary` says "I have zero lab draws to interpret yet" while `/api/labs` serves `total_draws: 8`. Both public. **Not staleness and not fabrication**: the analysis regenerated the same day (`analysis_generated_at 2026-09-12T17:06:57Z`) and still says it, because the coach is cycle-scoped (genesis 09-06; all 8 draws are 2026-04-03, pre-genesis) and `/api/labs` is lifetime-scoped. Neither surface names its window. The check's own remedy ("regenerate the coach analysis") is therefore ineffective, and the check inherits the same flaw by comparing a cycle-scoped narration to a lifetime count.
- **#3721** — `v4_build_gear.py` is stale: regenerating `/gear/` strips theme-color metas, the SVG favicon, manifest, apple-touch-icon and the loop-forward aside, redding 4 chrome tests. Worked around by patching the one string in place.
- **#3722** — `test_regen_once_never_regresses` is a Hypothesis `FlakyFailure`; `regen_once` diverges between first and subsequent calls. Proven independent of the diff by a warm/wiped-DB bisect against pristine main.
- **#3726** — the standalone nightly Visual QA has been red **8 consecutive nights** (09-05 → 09-12), 3 pages failing the sweep. #3650's class returned five days after it was closed.
- **#3731** — Unit Tests duration budget: measured n=14 green-main runs, **13 of 14 over budget**, median 2575s vs 1950s (32% over), spread 48.3%. Not a spike. Filed asking for decomposition, **not** a raise — the number has been raised 7 times and SHED twice by decomposing.
- **#3732** — coverage floor 74% sits 10.2 points under measured 84.2%: the ratchet stopped ratcheting, so ~10 points could be deleted silently.

## Gotchas hit

- **A denied action is not always a missing permission.** `gh pr merge` sat in the allowlist (`Bash(gh pr merge *)`, plus a blanket `Bash(gh pr *)`) and was still refused — by the auto-mode classifier, which sits above the rules. Adding a permission would have fixed nothing; leaving auto mode did.
- **The rollback scope check earned its keep.** The failing site deploy was classified `surface=api`, found not `site/**`-reachable, and the revert was **DECLINED by name**. `/version.json` stayed at `727473d`. That is #3652's mechanism working on a real case, not a drill.
- **A `git checkout` looks like someone else editing your files.** `CLAUDE.md`'s status block appeared to change on disk mid-session; it was my own branch switching. Session Z wrapped on the unmerged #3713 branch, so its block lives only there while main still carried Session Y's.
- **The reconcile bot is real and fast.** `c1c37a2f`'s own reconcile job pushed `dce72b5d` 43 seconds later, which is why the Deploy job checks out `needs.reconcile.outputs.build_sha` and not the run's head sha — the run that *looked* like an ancestor was the one that created the tip.

## Verification

Full suite locally: **25,518 passed** (the 4 reds were the `platform_counts.py` test-count literal, driver-reconciled on main — CI's pre-merge job runs `sync_doc_metadata.py --apply` before the suite for exactly this). Every PR merged green: #3723 11/11, #3727 10/10, #3730 7/7. Both mutation-proof pairs bite: unbounding the pct ceiling and widening its class each red their own control; reverting the log read to one page reds the pagination control.

**Build beat:** none — the three shipped fixes are gate-and-ingestion internals with no reader-visible change; the one reader-facing finding (#3728) is filed and unfixed, and a beat narrating a defect we have not closed would be a plan, not a beat.
**Docs:** `docs/INCIDENT_LOG.md` (+1 row, Patterns regenerated), `docs/alarm_citations.json` (qa-smoke-failures re-cited to the true live cause), `docs/OPERATING_KNOWLEDGE_LEDGER.md` (+6 rows, snapshot + counters recomputed from the rows), plus `docs/ARCHITECTURE.md` / `docs/ONBOARDING.md` / `docs/OPERATOR_GUIDE.md` / `docs/DEPENDENCY_GRAPH.md` in PR #3723.
**Decisions:** none needed — three defect fixes inside existing ADR-104/ADR-105 semantics; no governance posture changed.
**Main:** green (70a5e8ed)
**Incidents:** 1 row added — the accuracy gate failing a healthy site deploy over a beaten Zone-2 target, where the rollback scope check correctly DECLINED the revert.
**Stash/hooks:** clean
**Closures:** #3720, #3725, #3729 commented · DoD: scanned 2, hits 0 after commenting (the sweep's window is `closed:>=` today UTC, so it sees #3725/#3729; #3720 closed just before that boundary and was commented on the same contract).
**Backlog:** Now live at 13 actionable opus stories (floor 3, 0 short — nothing to promote); Later sweep — no stale issues, `later_staleness` clean over 130 open.
**Alarms:** 0 uncited — `qa-smoke-failures` re-cited to its true live cause (#3728) after #3730 made the live-cause read honest; the gate now passes on a paginated read rather than a truncated one.
**CI warnings:** 4 classes over 8 annotations — (1) smoke content-truth failure → #3728, the same cause as the alarm; (2) Unit Tests duration budget → #3731 with the n=14 measurement; (3) coverage floor drift → #3732; (4) 5× playwright-skip notices, deliberate no-action — the skips are by design on a non-chromium runner, though their cited `#3640` is CLOSED, so the pointer is stale even though the behaviour is intended.
**Ledger:** none — no standing machinery shipped; all three fixes changed the behaviour of gates and a schedule that already existed and already carry their rows.

## Two gates red at the wrap, both acknowledged rather than silently passed

- **(e7) backlog-hygiene exits 1 on 62 pre-existing corpus violations, none of them this session's.** All nine issues this session filed, touched or closed (#3720, #3721, #3722, #3725, #3726, #3728, #3729, #3731, #3732) were checked individually and are clean — the session's own contribution went 78 → 62 after fixing labels, `## Outcome`, `## Acceptance`, the canonical `**Score:**` grammar (the `×`/`→` glyphs, not `x`/`->`) and `**Epic:**` links on the three it filed. The residue is 52 `set_section` + 5 `acceptance_count` + 5 `epic_story_coverage` on issues predating those rules, and **#3594 is open and owns that backfill by construction** — it is the issue that introduced the `## Set` requirement.
- **(e11) ci-warnings exits 1 bare and 0 `--decoded`.** Each of the 4 classes is triaged on the `**CI warnings:**` line above; the battery invokes it bare, so it will red at every wrap until the underlying warnings clear.

## Residual / next picks

- **#3728** — the labs coach vs `/api/labs` window mismatch. Reader-facing and live now; the highest-value thing on this list.
- **#3726** — the 8-night-red nightly. A standing red is an absent check.
- **#3721**, **#3722**, **#3732**, **#3731** — the generator, the flake, the two stale ratchets.
- **#3553** — the commitment ledger that has never graded anything (480 records, 0 kept / 0 broken). Owner asked about fable-sized non-feature work; this is the one genuinely ready item in that lane.
- PR **#3713** (Session Z, 7 stories) remains open and unmerged by owner decision — `not-work — the owner is holding it deliberately; it changes the night-before authoring path.`
- **#3719** — tape measurements served publicly with no tier and no consent stamp. `not-work — an owner publish-or-restrict ruling, not an implementation task.`
