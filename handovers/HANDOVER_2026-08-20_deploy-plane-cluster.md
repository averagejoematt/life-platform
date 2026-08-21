# Handover — 2026-08-20 (afternoon/evening, ~13:32 → ~16:4x PT): the deploy plane stops lying, and it lied about my own fix twice

**Session:** Opus, owner-directed (plan `quizzical-wandering-dawn.md`, model ceiling Opus). Boot was
**charter + `blast_radius.py`**. **No `model:fable` issue was touched** — by design; the whole plan was
built from the 59 workable non-fable issues. Previous wrap archived as
`HANDOVER_2026-08-20_fable-triage-and-the-unstranding.md`.

**Build beat:** none — every merge is internal CI machinery (a rollup assertion, a scheduled detector,
derived deploy triggers, a pre-merge ordering check). Per `docs/content/BUILD_DISPATCH_CHECKLIST.md` a
beat must be merged **and** deployed work a reader can see. Nothing here is reader-visible.

**Main:** green — but it took two fixes found *during the wrap* to get there (below).
**Closures:** #2830, #2826, #2920, #2831 (4). **Filed:** #2924 (1). **Rescoped, not closed:** #2829.
**Count: 89 → 86.** `model:fable` **25, unchanged and untouched.**
**Deploys:** none. Every merge is CI-logic-only — no Lambda code, no CDK, no bundled-config *content* —
so a fleet redeploy would be a no-op. **Four production gates rejected**, one of which I let strand
(below). **Stash/hooks:** clean. **Alarms:** 0 uncited.

---

## The cluster, and why these four

Epic **#2799** — "the silent-failure floor: nothing user- or data-facing may fail dark." I picked
these four because **I had personally hit three of them in the preceding session** without knowing
they were already filed:

| issue | what it prevents now |
|---|---|
| **#2830** | an empty **or incomplete** check rollup reading as green |
| **#2826** | a swallowed push going undetected between sessions |
| **#2920** | a bundled file changing while the deploy plan doesn't notice |
| **#2831** | a page shipping before the API route it calls |

All four are now rows in **`docs/CONVENTIONS.md` §9**, landed as **one consolidated commit** — every
worker was told to put its entry in the PR body as text and not touch the file, so four PRs could not
pile up on it and the rows would read as a set. (The registry then rejected my first attempt:
`test_gate_registry_is_pointers_not_restatements` caps the pointer cell at 120 chars and mine was 135.
Its own rule is *pointers, not restatements*.)

## Phase 0 paid for itself twice, before any worker started

**A false positive that would have made #2826 actively harmful.** `check_main_green` reported main's
HEAD as the swallowed-push shape. It wasn't: `8cbf075f` touched only `CLAUDE.md` + a handover, and
**`Docs CI` ran on that exact sha**. Wired into a 15-minute cron unchanged it would have paged on every
docs commit and been muted inside a week. Worker 2's brief was rewritten to require the discriminator
*and* a silent-on-`8cbf075f` proof.

**#2920's premise — my own filing from three hours earlier — was wrong.** I had blamed the workflow
`paths:` filter; `config/**` is **already** in it, so my stated fix was a no-op. The real skip is at
`ci-cd.yml:634`, where the Plan job diffs only `lambdas/ mcp/ mcp_server.py`. And sixteen lines below:

```bash
VOCAB_CHANGED=$(git diff … -- config/food_vocabulary.json)
[ -n "$VOCAB_CHANGED" ] && FLEET_CHANGED="true"   # ⚡ fleet deploy
```

**One bundled config file had a hand-written trigger; the other was forgotten** — though
`build_bundle.py` stages both identically. Corrected and retitled the issue rather than editing the
body quietly. That is four wrong premises in two sessions, and this one was mine.

## The derivation found 15 files nobody knew about

Worker 3 replaced the hand-typed list with `build_bundle.py --print-bundled-config-paths`. It returns
**17 paths**, not the 2 I assumed:

```
config/coaches/{sleep,nutrition,mind,physical,glucose,labs,explorer,pattern,career,training}_coach.json
config/coaches/{_shared_standard,influence_graph,tuning_log,eli_marsh}.json
config/food_vocabulary.json      ← the one with a hand-written trigger
config/personas.json             ← the bug I filed
redirects.map
```

Every `config/coaches/*.json` ships in every bundle and had **no deploy trigger** — a coach-config
change would have gone green with `Deploy: skipped`, exactly as the personas a11y fix did. Verified the
`VOCAB_CHANGED` special case is genuinely **removed** (0 occurrences on the branch, 2 on main), not
left alongside the derived set.

## I replayed my own near-miss through #2830, in both dialects

```
what I computed that day: total=7 notgreen=0  ->  "GREEN, merge it"

assert_pr_green.py:  bucket dialect -> exit 1
                     rollup dialect -> exit 1
                     identical verdict: True

❌ 1 expected check(s) MISSING from the rollup entirely:
   - Collect + deploy-critical + format
   (absent, not failed — it has not registered yet, or will never run on this PR)
```

Worker 1 derived the expected set from `deploy/github_posture.json`'s required-checks ruleset — its own
call, and the reason this lands: that file holds exactly two entries and the missing one is the first.
I sent it back once to accept the `gh pr checks --json bucket` dialect too, because that is the shape
the near-miss and the issue's own precedent both used; a tool that cries "7 NOT GREEN out of 7" on a
green PR gets bypassed.

## I shipped a live false positive and caught it 20 minutes later

**The worst thing in this session, and it was mine.** #2925 wired `head_coverage()` into a 15-minute
cron. Running it against real main immediately after:

```
🛑 SWALLOWED PUSH (#2826 class) at 33a40b93: other workflow(s) ran (['Dependabot Auto-merge'])
   but NOT ci-cd.yml, even though the diff touches its paths: filter
```

`33a40b93` is a routine `chore(reconcile)` commit. It hit the **partial-swallow** branch because it
satisfies both halves: it is pushed with `GITHUB_TOKEN`, which **GitHub never dispatches workflows
for** (anti-recursion, by design — `total_count: 0` confirmed), *and* it regenerates
`lambdas/web/site_api_common.py`, so its diff hits the filter's first entry.

**A reconcile commit follows every merge**, so the cron would have paged forever — the exact
false-positive-generator I had warned Worker 2 about, arriving through the one case neither of us
enumerated. Worker 2's discriminator handled path-filter-skip correctly; it had no state for *"the push
could not have dispatched in the first place."*

Fixed in **#2927**: `ZR_BOT_PUSH_NO_DISPATCH`, checked before every other branch since it holds
regardless of diff or sibling runs. The committer comes from a payload the caller already fetches — no
extra request. Verified on merged main, with a regression guard that a **human** zero-run push still
pages.

## The wrap itself found two more — including a gate I had let strand

I only discovered the record was stale because Matthew asked "did we wrap". The honest answer was no,
and checking turned up two live problems:

1. **A production approval gate parked 2.6h** — past the #1901 threshold, queueing every later CI/CD
   run behind it. I had swept for waiting gates twice and rejected two, and this one still slipped
   through; a third appeared behind it. **Sweeping once is not enough** — drain in a loop until the
   query returns empty on a second pass.
2. **Main was genuinely red**, and not merely from my rejection: Worker 3's new gate step lacked
   `if: always()`, so `test_premerge_lane.py::test_the_lane_gates_report_independently` failed —
   *"pre-merge gate step(s) without `if: always()` will be masked by an earlier red."* **The gate built
   to stop silent failures could itself be silently masked** (#749). Fixed on main.

## The recurring lesson, now at five instances

**The 168-test "structural set" is not a proxy for CI.** It went green through every failure in the
last two sessions: the `aws_cdk` collection error, the `alarm_count` ±5 drift, the stale
`DEPENDENCY_GRAPH` + a wrap failing its own #1340 gate, the citation-pin prune, and now the
`if: always()` miss. It is **not in `CONVENTIONS.md`, not a script, not a workflow** — oral tradition
with a number attached, underived from anything that actually gates `main`. Filed as **#2924** with the
evidence; it belongs near the front of the next session.

Also worth keeping: the **#2372 tree-sweep gate fired on two different workers' new tests** in one
session. It works correctly, but "adds a tree-sweeping test" is a predictable trap no brief warned
about — it belongs in the standing worker brief.

And I nearly filed a bug against working code: `ci_cd_push_paths` looked missing and
`--head-coverage-check` looked ignored. My local checkout was four commits stale.

## Residual / next picks

- #2924 — the 168-test pre-merge proxy is undocumented, underived, and green through five main-reds.
- #2829 — rescoped on measured ownership: CDK owns **one** of the six us-east-1 alarms
  (`email-subscriber-errors`). Route that (pure modify, deploys clean); the three orphan adoptions need
  `cdk import` and two of them already route correctly.
- #2921 — `/api/sleep_detail` interleaves Eight Sleep and Whoop in one object; confirmed by the oracle.
- #2918 — two of six AI validation results never report `BLOCKED`, including the TL;DR headline.
- #2919 — `pattern_coach` (3.89:1) and `career_coach` (3.69:1) fail the WCAG AA contrast floor.
- #2912 — an alarm that flaps for 60s is invisible to the >72h citation gate.
- #1221 — the live P1: 21/21 CloudFront behaviours still on legacy `ForwardedValues`, so
  `CloudFront-Viewer-Address` never reaches the origin and per-IP limits stay evadable. Wants its own
  session — it is a public-distribution migration.
- #2809 — `partial`; verifiable only once a post-genesis Withings weigh-in exists.
- #2708 — `partial`; the chronicle runs Wednesdays, next 2026-08-26.
- The #2831 gate is advisory, not required — not-work — promoting it needs an owner-run
  `python3 scripts/apply_branch_protection.py --apply`.
- A Withings weigh-in — not-work — owner action; also unblocks #2809's verification.
- Two duplicate us-east-1 billing alarms to delete — not-work — an AWS mutation recorded in #2829.

## Owner asks

1. **A Withings weigh-in** — newest row is still `DATE#2026-08-16`.
2. The one-line coach-colour call: `sleep_coach` is `#818cf8` on accessibility grounds (6.21:1 vs the
   roster-v2 value's 4.37:1, under the AA floor). One line in `config/personas.json`.
3. `gate:owner`: **#1738, #1571, #1677, #1631**; **#2833/#2834** are `model:opus` + `gate:owner`.
4. Promote the #2831 API-before-frontend check from advisory to required, if wanted.
