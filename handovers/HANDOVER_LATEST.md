# HANDOVER — The gates paid for themselves the same day: 27 PRs, 250→28 xfails, and three reds caught *before* merge — 2026-08-08 20:13Z → 2026-08-09 ~00:00Z

> Instruction thread: *"read the 2026-08-08 handover, then the plan at
> `~/.claude/plans/elegant-noodling-blum.md` and execute it. Opus driving, fully autonomous.
> **Compute your wrap deadline as T+6.5h from RIGHT NOW and state it back to me** — last session's
> prompt carried a deadline already two hours past. Main should be green; if it's red that's the
> only thing that preempts Phase 0. Phase 0: move mypy tier-2, both size guards and the two registry
> guards into pr-checks.yml's fast lane. Then Phase 1: the BASELINE registry records a line count
> nothing compares against — expect it to go red immediately on five or six files; that is the gate
> working. Land the mechanism and the re-baselined counts in the same PR. Launch tranche 5 at the
> START of Phase 2. Waves of 4 implementers, one xfail cluster each, largest first. Verify every fix
> yourself before merging, and remember a mutation must actually mutate. Run the FULL suite locally
> before wrap. Never stall waiting for me."*

**Deadline discipline worked.** Computed and stated at the top of the first message: session start
20:13Z → wrap 02:43Z. No inherited clock. Wrap started ~23:20Z, 3h20m early.

**Main:** green (`585b1d58`) — `check_main_green.py` exit 0. It went red once for ~35 min on a
transient I caused; see Incidents.
**Docs:** `docs/engines/HYPOTHESIS.md` re-verified against #2328 (read the diff, not a date bump —
the SPEC_METRICS *vocabulary* changed and nothing else did). All four wiki checkers green.
**Decisions:** none needed — the one governance-shaped call (which surfaces get the exact grounding
tolerance) is recorded on #2290 and in the test module's docstring, and follows ADR-104 rather than
establishing new policy.
**Incidents:** 2 rows — main red ~35 min on a **transient** visual-QA failure caused by my own
deploy timing, and a CI/manual deploy race that shipped a site-api bundle missing a merged PR.
**Build beat:** `2026-08-09-the-gates-that-caught-me-first`.
**Closures:** 5 — #2286, #2287, #2290, #2307, and epic #1461. Each carries the ADR-099 two-line
verdict; #1461's is honestly `partial` (six of its eight children were closed before the verdict
convention existed, so its Slop-Litmus clause is unverifiable from the record).
**Backlog:** 69 open, corpus clean (0 violations). 22 issues filed. `Now` was down to **2**
actionable (the rest `gate:owner` or `model:fable`), so #2305, #2337 and #2343 were promoted from
`Next` by stored rank — which then reds `score_line_canonical` until each score line's `→ Next` is
repointed, a step worth knowing about before you promote. `Later` sweep: no stale issues.
**Alarms:** 6 red, all cited, **none new** — the newest state change (`coherence-overall`, 18:46Z)
predates this session's first commit.
**CI warnings:** 8 — 7 are the known per-stack CDK config-drift class (**#2213**, needs an owner CDK
window; deliberate no-action, CDK deploys are out of scope by instruction). The 8th carried **2 live
reader-truth failures**, deliberately non-gating per ADR-147/#1921 and therefore easy to normalise —
filed as **#2343** and **#2344**, and #2343 turned out to be the sharpest finding of the night.
**Stash/hooks:** clean — stash empty (one entry created and dropped mid-session, verified identical
to its commit first), hook freshness 🟢.

---

## The headline: Phase 0 was worth more than the 27 PRs, and it proved it the same day

The plan called Phase 0 "worth more than any single issue." That was right, but the argument in the
plan was *prospective* — main had gone red four times last session on gates that only run after a
merge. What actually happened is better evidence: **the gates moved left caught three separate reds
within hours, and two of them were mine.**

1. **The module-size ratchet caught a +1-line union breach on main within the hour.** #2299 and
   #2297 were each green alone; together `daily_metrics_compute_lambda.py` went 1369 → **1370**, one
   line over its recorded ceiling. That line is a single `from intelligence.weight_recency import
   week_ago_weight` — the import that gives the compute Lambda and the daily brief *one* definition
   of last week's weight. Bumped to 1370 with the reason, which is the ratchet's sanctioned path.
   This is the third instance of the concurrent-PR union-breach class in two sessions and the first
   time a gate named it instead of a human noticing hours later.

2. **Both size gates caught my own PR pre-merge.** #2323's first draft took
   `site_api_ai_lambda.py` from 1991 to 2004, crossing the 1200-ceiling ratchet *and* the 2000-line
   `*_lambda.py` gate. I did not bump either — my own commit message for the ratchet says raising is
   "never the reflex fix for a red gate." The comment block was restating #2276/#1967 material
   already documented at `_grounding_allow_lists`, so compressing it was a real improvement. Landed
   back at exactly 1991.

3. **The grounding-wiring registry caught a regression in my own PR — and it had run only *after*
   merge for its entire life.** Folding `cycle_gate_params()` into a local dict made the freshness
   gate class invisible to the registry's call-site scan: it read as *"declares freshness, does not
   arm it."* The behaviour was unchanged; the *declaration* had stopped being checkable, which is
   the same defect shape as a guard that guards nothing. Fixed by passing the tolerance through a
   tiny `**_tol` dict so `**cycle_gate_params()` stays literally at the call site.

Cost of moving them left, measured: mypy **0.31s warm** (379 modules), the five structural guards
**1.98s** for 66 tests, ruff ~1s. The fast lane went 117s → ~3m. Mechanism note: no second hand-list
in YAML — `tests/conftest.py` gained a *third source* for the `premerge` marker, so the workflow
still selects one marker and the two lanes cannot drift (the property #2258 bought).

## Phase 1: a registry that documented itself as shrink-only, while 24 of its 28 entries grew

`tests/test_module_size_guard.py` recorded each grandfathered file's line count as a **prose note**
(`"3016 lines"`) and then did `if rel in BASELINE: continue`. Nothing compared a file against its
own number. Measured on main:

| file | baseline | now | drift |
|---|---:|---:|---:|
| `lambdas/web/site_api_social.py` | 1829 | 2708 | **+879 (+48%)** |
| `cdk/stacks/role_policies.py` | 2848 | 3211 | +363 |
| `cdk/stacks/monitoring_stack.py` | 1298 | 1623 | +325 (+25%) |
| `mcp/registry.py` | 2103 | 2409 | +306 |
| …20 more | | | **+3,565 total** |

Two shrank, two were unchanged. Same class as last session's pipefail finding: **a number recorded
in the repo that no gate ever read.** Values are now `int` and enforced; a second check forces the
prune once a file drops back under the ceiling (`site_api_data.py` was baselined at 3016 and is now
**362** — while that entry stood it could have regrown 8× with every gate green).

Re-baselined at measured rather than held, with the drift in the docstring and the commit so the
debt stays visible. The mutation that mattered was appending **two real lines to `mcp/registry.py`**
— proving the gate reacts to the tree, not just to registry edits.

**The ratchet then did the job it was built for, four more times**, and every implementer chose the
right side of it: `weekly_digest` **lowered** its baseline 2216 → **1828** and dropped its
`GRANDFATHERED` entry by extracting pure helpers; `tools_lifestyle` had **one line** of headroom and
lowered 1989 → **1829** by lifting a tool into a sibling; the chronicle facade hit 1207 and moved
two functions out to land at 1169; and `mcp/registry.py` hit 2410 and was **reworded to fit** rather
than bumped. Zero reflex bumps in the whole session.

## Phase 2: the xfail corpus, 250 → 28

Sixteen clusters, one PR each, all merged and deployed. Coverage **79.02% → 80.20%**. Suite
**15,713 → 16,346 passing**.

| cluster | fixed | PR | | cluster | fixed | PR |
|---|---:|---|---|---|---:|---|
| `mcp_tools_nutrition` | 21/22 | #2302 | | `mcp_tools_training` | 9 | #2322 |
| `daily_brief` | 21 | #2299 | | `macrofactor_ingestion` | 9 | #2321 |
| `html_builder` | 18 | #2298 | | `coach_ensemble_digest` | 9 | #2320 |
| `mcp_tools_cgm` | 16 | #2300 | | `challenge_generator` | 8 | #2324 |
| `site_api_social` | 21 cases | #2314 | | `hypothesis_engine` | 8 | #2328 |
| `weekly_digest` | 14 | #2316 | | `nutrition_review` | 8 | #2325 |
| `site_api_nutrition` | 14 | #2313 | | `mcp_tools_lifestyle` | 7 | #2340 |
| `mcp_tools_labs` | 12 | #2312 | | `eightsleep_ingestion` | 7 | #2339 |
| `enrichment_lambda` | 11/12 | #2317 | | `chronicle` + `status` | 10/11 | #2341 |
| `site_api_meals` | 12 | #2318 | | tranche 5 (coverage) | +0.96pp | #2301 |

### The corrections are the output — 50+ of them, and the shape is consistent

**The marker named a real bug and the wrong repair.** Nearly every one. The ones that would have
done harm:

- A remedy that would have **created** a fabricated clinical number: the truthiness bug being
  removed was accidentally suppressing a divide-by-zero, so the fix *alone* starts publishing
  `non_hdl = 200 − 0`.
- A remedy that would have **breached the live #2209 privacy gate**, publishing keys the gated-OFF
  path explicitly asserts are absent.
- A marker demanding a default that turns six *unlogged* days into six recorded *misses* — the exact
  ADR-104 error a sibling marker in the same file exists to remove.
- A marker accusing a reader that was **already correct**: the writer had started emitting the field
  in a PR that merged *after* the marker was written. The stale thing was the test fixture, and
  patching the reader would have broken a working metric.
- A per-candidate `except Exception` that passes the marker's test and silently breaks an
  *already-passing* contract — a DynamoDB outage would become "completed week, wrote nothing."

And **one marker was left in place as correct behaviour**, with the best argument of the session:
the enrichment percentile marker's prescribed `bisect_right` remedy would have *manufactured* the
ADR-104 violation it cites, contradicts three passing sibling contracts, is internally incoherent (a
tie with the max would outrank an outright win), and its stated harm doesn't occur at scale — the
n=3 reproduction is degenerate.

### What the burn actually fixed, in reader terms

The three worth naming: absent CGM readings were published as a glucose **minimum of 0.0 mg/dL** and
**0% time-in-range**, then averaged into summaries — turning a real 96% time-in-range into "48.0%"
*with a fabricated clinical warning*. An unlogged nutrition day rendered a full row of zeros in
**green**, because `0 ≤ target` clears trivially — an unlogged day read as a perfect deficit day. And
`/api/frequent_meals` was publishing `period_days: 30` on **Day 5** of a 5-day-old cycle.

## ⚠️ The thing Matthew should act on

**MacroFactor has ingested nothing for 45 days, and cycle 12 therefore has zero nutrition data.**
Measured three ways tonight: newest DynamoDB record **2026-06-24**, newest raw S3 object the same
date, and the Dropbox poller **healthy** (53 invocations/day, no errors). The pipe is up; no CSV has
been uploaded. Genesis was 2026-08-03, so every nutrition-derived claim in the running cycle is
computed over an empty window. It is classified `behavioral: True`, which is *correct* and means it
never pages — but "never pages" has also meant "never mentioned." Filed as **#2326** (`gate:owner`),
which asks two things: upload an export, and decide whether a `load-bearing` behavioral source going
quiet deserves a non-paging notice somewhere you actually read.

Today's `site_api_nutrition` / `site_api_meals` / `weekly_digest` burns made several of those
surfaces honest about the absence, which is timely but is not the same as having data.

## Three things that caught *me*

1. **zsh does not word-split unquoted parameters — three times.** A verification helper doing
   `mods="$@"` … `for m in $mods` passed all three paths as ONE argument, so `git checkout` failed
   and nothing was reverted. The suite came back green and I nearly recorded four PRs as
   unmutation-proved. The same trap silently no-opped a four-Lambda deploy loop using `set -- $pair`.
2. **`git checkout origin/main -- <file>` STAGES the revert**, so the follow-up `git diff --stat`
   reads **empty** and looks exactly like "the mutation missed." I printed `EMPTY — MUTATION MISSED`
   on four PRs whose reverts had in fact landed (the reds proved it: 22/20/22/16 failures). Three
   implementers hit the same thing independently the same day. `git diff --cached --stat` is the
   comparison that sees it.
3. **`agent_commit.sh` refused me twice** — once on a ruff import-sort error, once with the size
   ratchet red. Both correct. The `ALLOW_DOC_LITERALS=1` override was needed exactly once, for a real
   content edit to `docs/engines/HYPOTHESIS.md`.

Note the shape of (1) and (2): the *mutation* was fine and the *observation* lied. The standing rule
is "a mutation must actually mutate" — the corollary is **check the harness, not just the mutant.**

## What only the full local suite could find

Two items, neither reachable from a per-PR run — which is exactly the argument for the instruction:

- **A stale `XPASS` that had been invisible for a full session.** A `strict=False` marker whose test
  starts passing reports as XPASS, which pytest counts as a **pass**; without `-rX` it is silent.
  #2299 had fixed the defect and left the marker behind, and two implementers independently
  reported it as "a pre-existing xpass elsewhere, not mine."
- **The engine-doc staleness gate** on `HYPOTHESIS.md` — re-verified by reading #2328's diff. Worth
  recording: the model's fields used to splat *last*, so an **LLM could pre-declare its own
  hypothesis `confirmed`** — an ADR-062 boundary breach, fixed in that PR.

## Residual / next picks

- **#2326** — MacroFactor 45 days quiet; cycle 12 has no nutrition data. **The top item**, `gate:owner`.
- **#2333** — `_fallback` has no reader on either coach surface, so an empty AI cycle still shadows
  as genuine coaching. Live: the ensemble is paused at budget tier ≥1, which is the default state.
- **#2343** — a coach card cites HRV 42 ms / recovery 55% against the cockpit's 32 / 31%. **Read
  this one before the others.** All three mechanisms I proposed when filing it were wrong, and the
  measured shape is worse: the card is same-day fresh (not stale), and the cited numbers are
  **2026-08-07's real readings, exact on both metrics** — not an average, not pre-genesis. The day
  is wrong, not the values. Worse, the persona is the *nutrition* one, whose declared fact block
  queries macrofactor only and emits no single-day Whoop reading on either branch — so a single-day
  vital reached a fact set that does not contain it, by a path source-reading did not explain.
  **A grounding check that asks "does this value appear in the fact set" structurally cannot catch
  this** — it is an ADR-104 *day-correspondence* gap, not an existence gap, which is exactly why
  widening a tolerance would be the wrong repair.
- **#2344** — `as_of_date` contradictions inside single payloads, with a deterministic proof rather
  than a code argument: `sleep_trend`'s last row is value-identical to the `sleep_detail` block, so
  the array is wake-keyed and the same night reads as `2026-08-08` in the array and `night_of
  2026-08-07` one level above, in one document. #1923's guard misses it because its AST scan matches
  dict literals publishing a `night_of` key, and an array keyed by `date` is outside that set.
- **Unfiled, needs its own measurement:** the same #2343 card opens with a specific day-count of
  missed food logs, which is hard to reconcile with MacroFactor being quiet 45 days (#2326) *and*
  with that fact block's empty-branch early return setting the field to `None`. Possibly a third
  grounding defect on one card. not-work — a measurement to take, not yet a defect to file.
- **#2329 / #2330 / #2337** — reader-facing nutrition/meals residuals from the burns.
- **#2331** (Strava zero→null is a population-membership decision) · **#2338** (an N-day window
  queries N+1 dates, repo-wide) · **#2310** (two published calorie figures disagree ~2×).
- **#2334** — four modules hand-type the coach roster, not the two first reported.
- **#2335** (`qa_smoke_lambda.py` at 1198/1200) · **#2336** (the null-coercion guard covers
  `operational/` only) · **#2304–#2309** (the tranche-5 census).
- **#2221** — the xfail tail tracker, updated with the full 250→28 burn. Remaining clusters are all
  ≤5: `daily_insight_compute` (5), `weekly_plate` (4), `ai_expert_analyzer` (4).
- **#2213** — 7-stack CDK config drift; still needs an owner CDK window (out of scope by instruction).
- **#2204** — Whoop token lifetime vs cron interval; code half only, CDK-blocked.
- Worktrees continue to accumulate under `.claude/worktrees/` and `~/Documents/Claude/wt-*`.
  not-work — housekeeping; no gate is affected.
- The two zombie gated runs remain excluded by number in `deploy/watch_deploy_gate.sh`. not-work —
  documented leave-alone; GitHub expires them at 30d.
- **Next wrap's archive slug must not be `throughput-first` or this session's** — both sessions ran
  on UTC 2026-08-08 and `archive_handover.py` refuses to clobber an existing dated entry. not-work —
  a naming note for the next wrap, not a defect.

## OWNER ACTIONS

1. **Upload a MacroFactor export** — or cycle 12's nutrition pillar has nothing behind it (#2326).
2. **The monthly Coach's Letter still sends 2026-09-06** to `EMAIL_RECIPIENT` (you) only —
   unchanged from last session's warning, ~4 weeks of runway.
3. **A CDK deploy window** clears #2213's 7 warnings and #2204's cron half.
4. **GitHub UI clicks** (unchanged): CodeQL dismissals ×3 (#2046) · PR #2012 revision-history purge ·
   the 2 verified false positives from #2200.
5. Personal calls, no deadline: the #1984 stack decision · the #1905 clinicians call.
6. When accounts exist: Bluesky/Mastodon + the two secrets. (Both ingestion Lambdas got a real fix
   today — #2314 corrected their share-card writers — but they stay dormant until the accounts exist.)

Prior session's narrative: `git show
origin/session-archive:handovers/HANDOVER_2026-08-08_throughput-first.md`.
