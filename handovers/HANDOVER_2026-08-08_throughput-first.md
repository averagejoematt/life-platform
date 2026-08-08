# HANDOVER — Throughput first: 27 PRs, 27 closures, and three guards that caught me — 2026-08-08 ~15:38Z → ~20:00Z

> Instruction thread: *"read the 2026-08-08 handover, then the plan at
> `~/.claude/plans/elegant-toasting-hamster.md` and execute it. Opus driving, fully autonomous.
> Phase 0 is the highest-leverage part — arm the gate monitor and write `deploy/agent_commit.sh`;
> last session five implementers ran 4½ hours and landed zero PRs. Then Phase 1: land the five
> salvaged drafts. Launch tranche 4 early. Never stall waiting for me. Hard limits: no
> `model:fable`, no CDK deploys, no repo-settings changes, no OAuth re-auth, no CodeQL dismissals,
> never invoke an email Lambda. Quality bar is the point, not the count. Start /wrap at 13:15Z at
> the latest."*

**A calibration note up front:** the session began at **15:38Z**, so the plan's literal 13:15Z wrap
deadline was already two hours past when I read it. That figure was T+6.5h for a session starting
06:45Z, so I adopted the same budget — wrap at 22:00Z — and started it at 19:40Z, two hours early.
The plan's `12936` test-count figure I re-derived rather than trusted, as instructed; it was still
correct at that moment.

**Main:** green (`e806d7e4`) — `check_main_green.py` exit 0, deploy wedge clean. The local full suite is clean at
`e806d7e4` (**15,711 passed, 0 failed**). The last red (`e7025dd4`) was a coverage-gate failure I had
already fixed two commits later — see Incidents.
**Docs:** `docs/engines/CHARACTER.md`, `READINESS.md`, `SCORING.md` re-verified (not date-bumped);
`docs/alarm_citations.json` gained the freshness entry. All four wiki checkers green.
**Decisions:** none needed — no governance-shaped call. The two closest (splitting modules rather
than grandfathering them; letting the monthly letter actually send) are recorded on the issues and
below, and both follow existing ADRs rather than establishing new policy.
**Incidents:** 2 rows — main red ~70min on a module-size ceiling crossed by two merges, and ~30min
on a second size gate. Both mine, both structural-guard reds, no production defect shipped by either.
**Build beat:** `2026-08-08-the-guards-that-caught-me`.
**Closures:** 27 — #2222, #2234, #2235, #2237–#2250 (the tranche-3 census), #2254–#2259, #2271,
#2276–#2278, and epic #1863. Every one carries an ADR-099 verdict naming what I mutation-proved and
how the deploy was confirmed.
**Backlog:** Now holds 4 actionable; corpus clean (52 open, 0 violations). No stale `Later`.
9 new issues filed (#2271, #2276–#2278, #2286, #2287, #2289–#2291).
**Alarms:** 7 red, all cited. `slo-source-freshness` newly cited with **measured** staleness rather
than the prior handover's inherited list.
**CI warnings:** 7 — **all one class and all already filed as #2213** (per-stack "Lambda config change
that CI's code-deploy cannot ship", needs an owner CDK window; no new warning among them). Deliberate
no-action this session: CDK deploys are out of scope by instruction. **#2259's duration warning is GONE** —
the suite went 6:40 → 4:03, which is the Phase 2 result confirmed by the instrument rather than by me.
**Stash/hooks:** clean — stash empty, hook freshness 🟢.

---

## The headline: throughput was the constraint, and fixing it was worth more than any issue

Last session's five implementers landed **zero** PRs in 4½ hours. This session landed **27 merged
PRs and 27 closures**. The difference was almost entirely Phase 0, which cost ~25 minutes.

`deploy/agent_commit.sh` is the whole trick. The pre-commit hook runs `sync_doc_metadata.py --apply`
and then `git add`s whatever it touched — correct for the driver on `main`, and wrong for an
implementer on a branch, where it sweeps a global `test_count` literal into a feature PR and
guarantees a conflict with every concurrent sibling. Agents hand-fought that loop. The script keeps
the format gate, restores any literal file the agent did not name, stages only named paths, and
commits `--no-verify`.

It also **refused me twice**, correctly: once on `docs/engines/CHARACTER.md` (real content edit —
`ALLOW_DOC_LITERALS=1` is the deliberate override), and its format gate caught staged Python that
would have red-mained lint.

Second-order effect worth keeping: implementers stopped losing time and started **correcting their
own issues**. Nine did, and those corrections are the best output of the session (below).

## What the implementers found that the issues had wrong

Nine self-corrections. These are not nitpicks — several changed the fix:

- **#2242** named `daily_brief_lambda` as "the only writer" of the streak field. There are **two**,
  and that one is the *fallback*. Patching the named file would have left the field unwritten on
  every normal day.
- **#2271** claimed a rename "left readers behind". `git log -S` proves `tasks_completed` has
  **never been written in this repo's history** — every reader was wrong from the day it was
  written. The set was **6, not 4**, and one of the two extra readers counted the length of an
  *open* task list as tasks *completed*. It also dated the dark freshness monitor precisely:
  **~147 days**.
- **#2250** said the enrichment fields sit on the record. `enriched_name` is written **inside each
  activity** in a nested list — a top-level preserve-list, the obvious reading, would have fixed
  nothing.
- **#2240** hand-listed 2 unscreened doors. AST-derivation found **9 across 6 modules**.
- **#2239** called the endpoint "the only unmetered door". There are **11**; the accurate claim is
  narrower (the only one taking a caller-supplied identifier). It also found the only client is a
  page under `/legacy`, unlinked and unreachable.
- **#2277** — mine — said two reads were unguarded. There are **four**, and the two I missed are the
  ones the answer actually leans on.
- **#2222** put the member set at 18. It is **27**, and the issue's own derivation rule returns a
  module it never enumerated.
- **#2254** filed three symptoms as one defect. They have **three separate root causes**, the 1MB
  claim is real-but-not-firing (measured: 401 KB, ~40% of a page), and the issue's suggested fix for
  the third would not have worked — the status page reads that partition with a projection, so
  **the row's existence *is* the claim**.
- **#2256** cited a line number that had shifted — "exactly the hand-listed-set rot the issue is
  arguing against".

The xfail burn produced five more: markers that were **wrong about the remedy**, including two
asking for wiring that #725/#726 had deliberately removed, and one whose prescription referenced a
field no writer emits.

## The two findings I'd most want carried forward

**1. The coverage gate could never fail a build.** #2259 asked me to delete a duplicated full-suite
step. Before doing it I checked what the remaining step actually enforced:

```
$ bash -e -c 'python3 -c "import sys; sys.exit(1)" | tail -100'; echo $?
0
```

The coverage step pipes `pytest … | tail -100`, GitHub's default shell is `bash -e {0}`, and `-e`
does **not** imply `pipefail`. Its exit code was `tail`'s — always 0. So `--cov-fail-under=74` and
every test failure inside it were silently discarded, and the step I was asked to delete was the
**only** one on main whose failures could red the build. Deleting it as filed would have left main
reporting green with no test signal at all.

`set -o pipefail` went in first. Within hours it caught three real reds that had been invisible: an
engine-doc staleness gate, and two module-size ceilings. **That is the gate working, not the gate
being noisy** — those files had been over the line and reporting green.

**2. #2234's monthly letter did not need the CDK deploy it was blocked on.** The cron fires the
first *Sunday*; the handler only ran *Monday*. Rather than change the schedule, the implementer
deleted the weekday guard and replaced it with an idempotency check — *"the cadence guard is
IDEMPOTENCY, not the weekday"* — because the old check took the runtime's **local** date to make a
weekday decision in a repo whose crons are fixed-UTC precisely so weekdays can't drift. A P1 that
was filed as CDK-blocked closed without a CDK window.

## ⚠️ One thing Matthew should know

**The monthly Coach's Letter will now actually send.** It has never delivered mail in its life.
Next fire **2026-09-06** (first Sunday), to **one address** — the `EMAIL_RECIPIENT` env var, i.e.
you, not the subscriber list. Merging alone did nothing; the deploy armed it, and that went out
automatically. There is a month of runway if you'd rather it stayed quiet.

Relatedly: `weekly_plate_lambda` **now has a `dry_run` gate** (#2222). The standing "never invoke an
email Lambda" rule was written partly because it had none. `chronicle-email-sender` still has none
(#2111), so the rule holds for that one.

## What shipped — 27 PRs merged + ~13 direct commits, all deployed

| PR | Issue | What landed |
|---|---|---|
| #2264 | #2247, #2249 | Meeusen demotion fires (`min()` on tier strings is lexicographic); missing import restored |
| #2262 | #2243 | ACWR alert renders — readers asked for bare `zone`/`alert`, writer emits `acwr_*`; + a derived reader/writer contract guard |
| #2263 | #2248 | sodium/caffeine exceedances can register — the branch was nested under a flag those two nutrients don't carry |
| #2260 | #2237, #2238 | one rate-limit chokepoint (4 of 7 doors had no fallback at all); check-in note screened both sides |
| #2261 | #2235 | food-delivery streak withheld once the source goes stale — withhold, not recompute (ADR-104) |
| #2266 | #2246 | Zone 2 board note reads the producer's real keys |
| #2267 | #2245 | weekly digest reads `completed_count` |
| #2270 | #2258, #2259 | **the pre-merge lane closed** + the coverage gate made real |
| #2268 | #2244 | anomaly block renders — a 5-month regression a self-justifying test concealed |
| #2269 | #2256 | `%G-W%V` across a derived set |
| #2265 | #1658 | **tranche 4** — `site_api_ai_lambda` 63.66% → 88.19%; 3 defects filed |
| #2272 | #2250 | Strava's re-fetch no longer wipes enrichment |
| #2273 | #2242 | Tier-0 streak persisted — 11 awards become earnable |
| #2274 | #2271 | 6 todoist readers + a derived contract guard |
| #2275 | #2255 | `dry_run` suppresses the writes and the false success, not just SES |
| #2279 | #2239 | subscriber-membership oracle metered, fail-closed |
| #2280 | #2222 | 17 SES senders behind one derived suppressor, converged onto `common/dry_run` |
| #2281 | #2240 | 9 experiment surfaces screened |
| #2282 | #2241 | genome privacy notice wired at the dispatcher, structurally detected |
| #2283 | #2278 | BP reader resolves from the registry; a vacuously-passing test killed |
| #2284 | #2276, #2277 | grounding gate takes its vocabulary from the **source**, not the truncated prompt; fail-soft derived over the read set |
| #2285 | #2254 | chronicle idempotency — three root causes |
| #2288 | — | xfail burn: `tools_health` 24/24 |
| #2292 | — | xfail burn: `intelligence_common` 13 fixed, 2 records corrected |
| #2293 | #2234 | the monthly letter sends |
| #2294, #2295 | — | two module splits back under the 1200-line ceiling |

Coverage **78.24% → 79.00%**. Suite wall-clock **6:40 → 4:03**. xfail markers **327 → 259**.

## The three guards that caught me — the part I'd read first

1. **My own `agent_commit.sh` refused my `docs/` commit.** Exactly the override case, and it made me
   state the intent rather than sweep the file in.
2. **The blocking backlog-hygiene gate caught me twice.** Three issues I filed failed it for a
   missing `## Outcome`, missing `## Acceptance` checkboxes, no `**Score:**` and no `**Epic:**` —
   then failed *again* on my fix, for naming an audience outside the sanctioned five and for a
   section-ordering mistake. A hygiene gate that only ever passes is evidence of nothing; this one
   caught the person in a hurry. That is the strongest argument for closing epic #1863.
3. **A `%s`-shaped mutation nearly gave me a false negative.** Verifying #2240 I neutered a privacy
   screen by making its condition unreachable *while leaving the call text in place*. The SET guard
   stayed green and I almost concluded it guarded nothing. Removing the screen **properly** failed
   it. Same shape on #2285: a regex mutation missed its target entirely and I nearly recorded a real
   guard as vacuous. **A mutation that doesn't change behaviour proves nothing — check that your
   mutant actually mutates.**

## Gotchas worth carrying

- **`.venv-black` does not exist inside a worktree.** My first fix for the black pin-skew resolved
  `.venv-black` from the worktree root — where it never exists, since it is untracked and lives only
  in the primary clone. Every implementer silently fell back to PATH black 25.9.0 and reintroduced
  the exact skew the guard was added to stop, *the same day*. `git rev-parse --git-common-dir` is
  the fix.
- **PR checks do not run mypy**, and `lambdas/common/`, `lambdas/emails/`, `lambdas/web/` are all in
  the tier-2 clean set. Two PRs red-mained main's Lint job on a `var-annotated` error after merge.
  Run it yourself before merging anything touching those trees.
- **A new module lands in more than one registry.** My `site_api_ai_prompt.py` split needed the
  phase-context census *and* the grounding-surface registry repointed. Both guards found it on the
  first full-suite run; neither is discoverable from the module itself.
- **The module-size ceiling has two independent guards** with different limits (2000 for
  `*_lambda.py`, 1200 for everything) and different registries. A file can slip one and trip the
  other.
- **Two PRs carried the wrong `Fixes #N`**, closing a neighbour's issue and leaving their own open.
  Every fix was merged; only the provenance was crossed. Corrected on both issues — but check the
  line before merging, since `Fixes` fires silently.

## Residual / next picks

- **#2286** — three MCP readers still hand-build `raw/` keys (no live defect; `raw_date_key` already
  covers them).
- **#2287** — eight unaudited `FIELD_COMPLETENESS_CHECKS` entries; `habitify` is the suspicious one.
  Same shape as the todoist monitor that was dark ~147 days. **The highest-value open item.**
- **#2289** — 11 unmetered public read doors; framed as a decision (cache tier vs counter).
- **#2290** — the grounding gate's numeric tolerance can absorb a corrupted trailing decimal.
- **#2291** — whether the 3 event-driven SES senders want a suppressor.
- **#2204** — Whoop token lifetime vs cron interval; code half only, CDK-blocked.
- **#2213** — 7-stack CDK config drift; still needs an owner CDK window.
- **#2221** — the xfail tail tracker, updated with this session's burn. Remaining clusters:
  `mcp_tools_nutrition` (22), `daily_brief` (21), `site_api_social` (19), `html_builder` (18).
- **#2111** — `chronicle-email-sender` still has no `dry_run` gate.
- **Whoop recovered on 2026-08-07** and has data through today — the inherited "latched since 08-04,
  no data" state is **stale**. Its auth alarms are still red because the daily bucket still contains
  failures. not-work — measured this session, no action needed beyond not repeating the stale claim.
- Git worktrees continue to accumulate under `.claude/worktrees/` and `~/Documents/Claude/wt-*`.
  not-work — housekeeping; no gate is affected.
- The two zombie gated runs remain excluded by number in `deploy/watch_deploy_gate.sh`. not-work —
  documented leave-alone; GitHub expires them at 30d.

## OWNER ACTIONS

1. **The monthly letter now sends on 2026-09-06** — see the warning above. Say the word if you'd
   rather it didn't.
2. **A CDK deploy window** clears #2213's warnings and #2204's cron half.
3. **GitHub UI clicks** (unchanged): CodeQL dismissals ×3 (#2046) · PR #2012 revision-history purge ·
   the 2 verified false positives from #2200.
4. Personal calls, no deadline: the #1984 stack decision · the #1905 clinicians call.
5. When accounts exist: Bluesky/Mastodon + the two secrets.

Prior session's narrative: `git show
origin/session-archive:handovers/HANDOVER_2026-08-08_privacy-door-and-the-letter-that-never-sent.md`.
