# Handover — Session AK: three issues the plan said were one box from done, and none of them was (2026-09-19 00:36Z → 04:00Z)

**Driver:** Opus 5 (1M), autonomous drain. Owner brief: *"close issues on demonstrated evidence"*, target 112 → 100-104
measured, standing merge+deploy authority (CDK included, announce before running), no `--deliver`, issue numbers
sigil-free near closing verbs, every deploy lease disposed. Plan: `~/.claude/plans/iterative-prancing-starlight.md`.

**112 → 105 open, measured two ways (`search total_count` AND a paginated id-set, agreeing). **7 closed** on demonstrated
evidence, 0 filed, **10 PRs merged**, 6 production deploys (site-api direct, two successful
`site-deploy`s, three approved fleet deploys), 7 superseded leases rejected by name and 3 approved.** One outside the 100-104 target, and the reason is the
through-line below rather than a shortfall of work: the plan's arithmetic rested on three issues being one box from
done, and measurement said otherwise on all three.

## The through-line

The plan's key finding was that **the ranker scores stale bodies** — nine ranked issues had boxes already landed under
`Refs`. That is true, and it produced two of the five closures. What it did not anticipate is that **the correction
runs both ways.** Three issues the plan sized as nearly-done were not:

- **3614** — box 2's third clause (a `check_backlog_hygiene` rule blocking a grounding finding's closure until its
  specimen is in the corpus) simply does not exist; `grep 'corpus' scripts/check_backlog_hygiene.py` returns the
  `## Set` intake and nothing else. 3 of the corpus's 8 specimens are also still `status: open`.
- **3670** — box 4 as literally written ("the title **counters** cannot reach behind `EXPERIMENT_START_DATE`")
  contradicts an owner ruling recorded verbatim on #3671: *N answers "Pull #3 of Foundation" even where Foundation
  spans two cycles.* The lane implemented it, flagged it as a reviewer decision point, and I ruled it reverted.
- **3599** — box 2 (the scoped-writer guard generalised to `classify()==EXPERIMENT_SCOPED`) is unpaid on main; the
  #2119 guard is still scoped to `COACH#` pk tokens with no `SOURCE#insights` control.

All three lanes delivered good work and all of it merged. **A body can be stale in the "further along than it reads"
direction and in the "an owner already ruled against this box" direction, and only reading the code and the owner's
own words separates them.**

## What closed, and on what

| # | Closed on |
|---|---|
| **3829** | The box-3 instrument caught firing on a real hole at 16:06:55Z and going quiet at 18:31:17Z; producer side verified by unzipping the live Lambda (`stored=pending` at :1199, `Timeout 300`) |
| **3792** | The framing flipped on the first `coach_state_updater` run after the deploy, with the day before it as a negative control in the same partition |
| **3835** | The shed measured — median 2850s → 1970.5s (n=9 → n=24), **1.45×** — and the budget deliberately not raised, with the residual and the p50-vs-p90 question written into the class record |
| **3669** | `assert_registry_coverage` passing on the live census with `COACH#brand_new` as its must-fail control; the measured Set was **67 of 83**, not the 4 filed |
| **3511** | `/method/predictions/` rendering `sealed 16 / in-cycle 24` where it read `sealed 0 / in-cycle 40`; `SEALED_ROW_MISSING: 0`; the cycle-17 sweep sanctioning 16 coach rows, none by a bare cycle stamp |
| **3878** | The two labels measured at **11.00px** on the deployed site at both widths; `visual_qa --screenshot` **94 passed / 0 failed**; CI/CD `35415903531` concluded **success** with `Visual + AI-vision QA: success` |
| **3604** | Auto-closed on the green standalone sweep it names in its own close policy — dispatched after the site was verified clean, never closed by hand |

## What shipped

| PR | Issue | What | Live? |
|---|---|---|---|
| #3879 | 3511 | `admit_sealed` — the seal survives the ledger's newest-first slice, in the API and the renderer | site-api + site |
| #3880 | 3835 | the duration class record gains its post-change distribution (n=24) | repo-side |
| #3883 | 3878 | two labels onto `--fs-label`; the spine rail sizes to its content instead of clipping | site |
| #3872 | 3669 | `labs` registered with a derived cadence, `inbound_email` retired, every live `SOURCE#` dispositioned | fleet |
| #3881 | 3670 | `list_all_folders` walks every page and REPORTS a truncated sweep; box 4 reverted on the owner ruling | fleet (MCP verified) |
| #3882 | 3614 | the audience/fail-mode facet on all 32 surfaces + the derived phase-prose census | repo-side |
| #3884 | 3599 | the pre-seal truth gate, positive control = the live published seal | repo-side |
| #3885 | — | 4 `PROPORTIONALITY` rows for this session's standing machinery | repo-side |
| #3886 | 3877 | the nudge writer stamps per ROW at the single write site | **needed a recovery deploy — see finding 9** |
| #3887 | — | the #736 build beat | site (verified served: 142 beats) |

## Findings the work produced that the issues did not predict

**1. Two sub-floor labels were auto-rolling-back EVERY site deploy — not just reddening a badge.** #3878 says a
standing red trains readers to stop reading the badge. Measured, it was worse: `site-deploy.yml` run `35363669931`
shows `Auto-rollback site … success` with `all 2 failed page(s) are site/**-reachable (site-shell=2)`. The #3652 scope
check was working exactly as designed — those failures *are* site-reachable. The last successful site deploy before
this session was 2026-09-16T06:29Z. **This session watched it happen to its own work:** #3879's renderer fix deployed,
was reverted, and in that window `/method/predictions/` rendered `sealed 6` instead of `sealed 16` — a number matching
that renderer's own mutation control exactly.

**2. An acceptance box can be fully satisfied and produce no reader-visible effect.** #3511 box 4 asked that the
projection carry `pre_registered` and the ledger table render sealed vs unsealed. Both shipped; both were live. And a
reader could not reach a single sealed row, because a pre-registered bet is dated at genesis and is therefore the
**oldest** row in the season, so every newest-first slice drops it first. Two truncations, in the API and in the
renderer.

**3. Raising a font to a floor CLIPPED a label the gate never named.** The #3878 Set was two elements, but
`.chart-spine-v` comes from a shared producer, so sweeping all 93 QA pages found a third: `'22407.5 kg'` on
`/data/training/` fits exactly at 9.6px and clips at 11px (`scrollWidth 46` vs `clientWidth 40`). Invisible to a
page-level overflow read — the #3734 class. **The fix would have shipped the defect if the Set had not been swept.**

**4. The published cycle-17 pre-registration is untrue in seven places.** Lane A's positive control is the live seal,
hash-verified (`curl … | shasum` == the fixture, `bd225d24f673…`), and the gate reports 7 blocking findings against it:
a retired coach sealed (`training_coach` / "Dr. Sarah Chen", after ADR-153), a wrong byline (`physical_coach` sealed
"Dr. Victor Reyes" vs the registry's "Dr. Max Reyes"), three assertions of a 326.2 lb start against a 327.34 baseline,
and two bare literal `min_effect` values. The seal is permanent, so this is an amendment question, not an edit one.

**5. `an md5 on the source proves the FILE changed, never that the CODE UNDER TEST did.`** Lane A's third mutation
reported GREEN falsely: `100.0 → 400.0` is byte-length preserving, and CPython validates a cached `.pyc` on
`(mtime, size)`, so the stale bytecode ran. The fix (purge `__pycache__`, run with `-B` before reading any verdict) and
the reasoning now live in `scripts/gate_census_mutations.py`'s module docstring, in front of the next author of a
mutation control. **This is the most transferable thing the session produced.**

**6. Filed member counts in the provenance family are systematically low.** #3669 filed "4 live partitions with no
entry" and measures **67 of 83**; #3513 filed 6 unstamped rows and measures **109**; #3877 filed 9 and is **10**,
growing by one a day. All were filed from review sweeps that sampled rather than enumerated. #3594's `## Set` intake is
the structural answer and is going-forward-only.

**7. A text matcher read my own prose four more times.** The closure sweep's `post-close-assertion` rule fired on a
sentence about a *different* issue's lifecycle in my 3669 comment; its `unhomed-residual` rule fired on my quoting an
earlier comment's marker; and **the note I wrote explaining the first false positive reproduced the trigger phrase and
tripped it again.** Reworded each time rather than answered by changing a detector. Closure sweep now: 0 findings.

**8. The #2119 writer guard sees 7 of 154 `put_item` call sites.** Measured read-only with the guard's OWN helpers,
so this is its definition of visibility rather than mine: 154 functions under `lambdas/` call `put_item`; **7** carry a
literal pk token and are therefore visible; **143 are blind and do not stamp**; 4 are blind and stamp anyway. The guard
flags on `if pks and not _stamps_directly(fn)`, so a writer whose pk is built at runtime cannot be flagged whatever it
does — ~95% of call sites. I hit this concretely: I moved #3877's stamp to its `put_item` site specifically hoping it
would land inside the guard, and measured that it did not.

**It is NOT 143 defects** — most of those partitions are `system_state` or `cross_phase`, where not stamping is exactly
right. What is unknown is how many write an `EXPERIMENT_SCOPED` row, and that cannot be answered by AST at all, because
the pk is the runtime value the AST cannot see. The cheaper and more complete answer is to **invert the check**:
enumerate ROWS, not writers — `pk_census` already walks every live family and `classify()` already rules on each, so a
nightly "every EXPERIMENT_SCOPED family has zero unstamped rows" catches the defect regardless of which writer produced
it. #3877's box 4 is a single-partition version of exactly that. Recorded on #3599, which owns the widening.

**9. "The tip carries a strict superset" is FALSE, and I wrote it into five rejection comments before catching it.**
`ci-cd.yml`'s Plan diffs **`${GITHUB_SHA}~1 HEAD`** — its OWN commit against its OWN parent — so each run deploys only
what its commit changed. `cd6014f36` (#3886, a `lambdas/` provenance fix) had its lease rejected as an ancestor; the
tip `a3c62024d` (#3887, `site/story/build/beats.json` only) then recorded **`Deploy: skipped`**, and `coach-nudge`
stayed on the previous bundle — `grep experiment_stamp_for` on the **deployed artifact** returned 0. The merged fix was
shipped by nobody.

It looked fine earlier only by accident: the previous tip `f80e88a50` was a reconcile commit touching an UNMAPPED
`lambdas/` file, which sets `FLEET_CHANGED=true`, and a fleet deploy does ship the whole bundle. The premise held by
luck, not by rule. Recovered with `gh workflow run ci-cd.yml --ref main -f deploy_all=true`.

**The only reason this was caught is the standing rule to verify by SHIPPED CONTENT rather than by a merge or a badge.**
Every badge in that chain was green.

## Deploys and leases

- `deploy/deploy_site_api.sh` at `9258da37` (direct; ancestry preflight + postflight both confirmed), verified by
  unzipping the deployed artifact — `def admit_sealed` at :258, on the call path at :879.
- `site-deploy` succeeded on `f22c66ad` (visual QA **success**, auto-rollback **skipped**) — the first successful site
  deploy since 2026-09-16T06:29Z.
- The build beat is live and verified as served, not merely merged: `curl https://averagejoematt.com/story/build/beats.json`
  returns **142 beats** with `2026-09-19-the-seal-nobody-could-see` at the top, on site build `a3c6202`. Its `site-deploy`
  concluded success with `Visual + AI-vision QA: success` — the second site deploy in a row to survive its own gate.
- CI/CD fleet deploy approved on main's **tip** `f80e88a50`, and verified by reach rather than by the job's green:
  **105 of 111 Lambdas** carry a `LastModified` between 02:47Z and 03:00Z. Spot-checked by shipped content — the
  deployed MCP package carries `list_all_folders` with `FOLDER_PAGE_LIMIT = 20` and the `unfoldered: <reason>`
  reporting, so #3670's duplicate-folder hazard (a commit that creates a second `Push` folder and reports success) is
  no longer live.
- **A rejection comment is CONSUMED by an instrument, not just etiquette.** `check_main_green.py` reads the
  rejection text back and classifies the run as *"production deployment REJECTED and superseded (#2467 lease actioned),
  not a red main"*, quoting the reason inline. So the prose written on a rejection is what stops a correctly-disposed
  lease from reading as a broken main at the next wrap. Worth knowing before writing a terse one.
- **7 leases rejected by name** (`df9cfca1`, `c9411dbf`, `0ce5b1ea`, `63c7fc33`, `29549cfd6`, `9b19afc87`,
  `cd6014f36`), each as a superseded
  ancestor with its reasoning recorded on the rejection, and **3 approved** — `f80e88a50`, `e2cfee176`, and the dispatched
  `deploy_all` recovery on `a3c62024d`, each the tip at the moment it gated. The second was approved rather than held back for a batch, deliberately: I had three PRs still
  going green, and holding a tip's lease open until they land is exactly the eviction that wedged six merges for 12.5h
  on 2026-09-18. A second fleet deploy is cheap; a held lease is not. A persistent monitor watched the gate for the whole
  session rather than the check being a wrap step — the direct answer to that incident.

## Owner asks

**The 8 gated questions are still unanswered** (last activity is AJ's own 2026-09-18T00:59Z posts): **3716 3717 3750
3753 3755 3761 3770 3771** — the last open children of five epics, ~13 closures for near-zero engineering. They are the
single largest available move on the board and no session can make it.

Four more, each one sentence:

- **3571** — the `dropbox` ruling on MacroFactor's CSV upload. Its derived denominator is **7**, not the 1 its text
  implies, and the `capture_channel` facet comment is stale (`progress_photos` has carried `'telegram'` since #3757).
- **3563** — the scoped `logs:FilterLogEvents` grant.
- **3601** — the reset-cadence ruling. (Its box 2 is a sleeper: `monthly_close.py:573` says in its own output that
  `$/reset` needs a per-reset cost model that does not exist.)
- **3670 box 4, NEW this session** — the box says *"the title **counters**"* (plural) and #3671 records the opposite
  ruling for N. If the ruling stands, box 4 should be reworded to name **Y** and ticked as already paid by #3671. If
  you have changed your mind, the implementation existed and reverting it was one commit.

And the **5 standing `acceptance_count` violations** (3607 3611 3615 3617 3621) still red `check_backlog_hygiene` all
day. They need splitting, not trimming — untouched by instruction.

## Residuals, named precisely

- **`docs/PROPORTIONALITY.md` rows for Session AJ's four subsystems** — the two #3506 alarms (the AI-canary dead-man
  and the cadence assertion), #3785's config-ownership registry, #3514's SCHEMA census gate. I wrote rows for **this**
  session's four (#3511, #3829, #3614, #3670 — PR #3885) and deliberately did not write AJ's: I did not build them and
  have measured only part of them, and writing rent I have not measured is the failure the ledger exists to prevent.
- **A three-issue provenance cluster with one shape:** #3513, #3877, and **#3599 box 2**, which is the one that makes
  the other two unable to recur. Paying them separately means writing the same guard three times. Whoever takes any one
  should read all three first. #3877 has a PR open (#3886) paying box 1 only.
- **#3877 boxes 1 and 3 are now paid and live** — the writer fix deployed (verified by unzipping `coach-nudge`:
  `experiment_stamp_for` at :470, the bare `cycle` gone from the builder), then the backfill applied **10 rows written,
  77 correctly protected**, and a read-only re-run reports *"nothing to repair — every EXPERIMENT_SCOPED row on the
  audited COACH#/ENSEMBLE# partitions carries a phase stamp."* Boxes 2 (the guard's reach) and 4 (needs the ~18:30Z
  nightly) remain, so the issue stays open. The 77 protected rows matter as much as the 10: stamping a `CHAT#` or
  `RELATIONSHIP#state` row would be #3514's defect running backwards.
- **#3546's shrink list has grown 11 → 50 across 48 pages**, measured by this session's own sweep. Every stale entry is
  a live (page, rule) pair that has stopped gating. Do not harvest before its box 2 `phase_dependent` flag exists.
- **122 worktrees**, and two agent lanes from prior sessions flagged their own locks still present
  (`issue-3688-judge-truncation-retry`, `issue-3699-training-notes-degrade-reason`). `/worktree` inventory is overdue.
- **`#3699` owes three deploys** from a prior session's lane (per its own agent's report) — `cdk_deploy.sh
  LifePlatformIngestion`, then `deploy_lambda.sh life-platform-mcp`, then the freshness checker. Not this session's,
  surfaced because the agent reported it here.

---

**Build beat:** `2026-09-19-the-seal-nobody-could-see` — "The pre-registration nobody could see" (PR #3887). Merged AND
deployed AND live: `/method/predictions/` renders `sealed 16 / in-cycle 24` where it rendered `sealed 0 / in-cycle 40`.
**Doc-impact sweep:** no canonical wiki page was invalidated, and here is the per-item reason rather than silence.
`admit_sealed` (#3511) changes which rows `/api/predictions` returns, not its contract, its field set or the endpoint
count `ARCHITECTURE.md` carries. #3669's registry work is exactly the kind of fact `CLAUDE.md` already delegates to
`source_registry.py` ("read the registry, don't hand-state a source's schedule here") — and `check_doc_facts.py` is the
gate that would catch a drift, run green. #3878 moved two component rules onto an EXISTING token; `DESIGN_SYSTEM_V5.md`
documents the §10.5 floor and the `--fs-label` step already, and neither changed. #3614, #3670, #3877 and #3884 are
tests, internal writers and a `deploy/` script — no public surface, no MCP tool added or retired, no new ADR, no
secret or account. Nothing load-bearing was retired, so `docs/_lint/tombstones.txt` needs no rule. The three docs that
DID change are listed below because they are the subject of the change, not collateral.
**Docs:** `docs/PROPORTIONALITY.md` (+4 ledger rows, PR #3885) · `docs/alarm_citations.json` (qa-smoke-warnings pruned
to its one live leg) · `site/story/build/beats.json` (+1 beat) · `tests/test_duration_budget_ratchet.py`'s class record
(the post-change distribution) · `scripts/gate_census_mutations.py` (the `.pyc` trap, via #3884).
**Decisions:** none needed — every call applied an existing ADR (099 closure contract, 103/144 ledger posture, 104
honest numbers, 077 phase classes, 133 ceiling untouched). **One owner RULING was applied rather than made:** #3671's
recorded preference decided #3670 box 4 against the box's own wording.
**Main:** green, verified at wrap rather than assumed — `check_main_green.py` reports *"✅ main GREEN — latest
completed CI/CD run (a3c62024) succeeded"* with `HEAD-COVERAGE: covered a3c62024`. It read RED earlier in the session
for two reasons, both benign and both now cleared: a reconcile-push race on `f22c66ad` (my four back-to-back merges
raced the reconcile bot twice; the error says so itself — *"the queued run will reconcile"* — and `f80e88a50` did),
and the seven lease REJECTIONS, each of which concludes its run as `failure` by construction. The checker already
distinguishes the latter, reading the rejection prose back as *"production deployment REJECTED and superseded (#2467
lease actioned), not a red main"*.
**Incidents:** none added — no incident occurred. The lease discipline that AJ's incident row demanded was applied
continuously (a persistent monitor, 5 leases disposed) rather than retro-fitted.
**Stash/hooks:** clean — one uncommitted file all session (`.claude/settings.local.json`, pre-existing), no stashes.
**Closures:** 3511, 3604, 3669, 3792, 3829, 3835, 3878 — every one commented AND ADR-099 verdict-stamped · DoD:
`closure_sweep.py --session` ends at **scanned=7 hits=0 findings=0 blocking=none**, after four rounds of rewording my
own verdict prose (see finding 7). 3604 was auto-closed by its own workflow's close policy, never by hand.
**Backlog:** 105 open, measured two ways (search `total_count` and a paginated id-set, agreeing). Bare hygiene ends at the 5 standing `acceptance_count` violations (3607 3611
3615 3617 3621) — the owner's, untouched by instruction, red all day by construction.
**Alarms:** ✅ clean. `qa-smoke-warnings`'s citation was pruned in the session's first 20 minutes: both of its dated
expiry legs had resolved **on the run they named**, leaving only the chronic leg, owned by #3877. The `cause` key was
REMOVED rather than left naming the cured pair — with an empty live cause list there is nothing to declare, and
removing it re-arms `undeclared_causes`, which fires the moment the channel names anything again.
**CI warnings:** unverified at the time of the gate run (it triages the latest GREEN completed main run, and two were
mid-flight). Not a clean board being claimed.
**Ledger:** 4 rows added for this session's own standing machinery (#3511, #3829, #3614, #3670). AJ's four remain
unwritten and are named individually in the residuals above — I did not build them and have measured only part of them.
