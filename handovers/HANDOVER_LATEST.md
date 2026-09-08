# Handover — Session Y: unblock the site, build the owner's read, then stabilise for a pause (2026-09-07 ~11:00 PT → 2026-09-08 ~21:30 PT)

**Driver:** Opus 5 (1M), lanes pinned to each issue's model label — Opus or Sonnet only, no Fable.
**Plan:** `~/.claude/plans/transient-honking-flame.md` (Session Y), then a mid-session owner
redirect into a new build (`~/.claude/plans/mellow-pondering-squid.md`), then an explicit
*"do everything that concerns you to get it stable, then wrap"* before a **6-day development pause**.

---

## The shape of the session

Three movements, and the third was the owner's call:

1. **Unblock the site.** 53 reader-facing a11y files had been merged and dark since 03:16Z the
   previous day; every `site/**` deploy since had died at `Deploy public site`.
2. **Build the owner-facing read** (#3691) — the owner asked for a way to see "how is the build
   going" without opening eight things, because a board of ~110 open issues reads as an emergency.
3. **Stabilise for a pause** — the owner asked whether stopping for six days should worry me. It
   should have: **main was RED and had been for ~3h**, and two production deploy leases had been
   stranded 9.1h.

---

## What shipped

**12 PRs merged**, all green at merge, all with swallow-checked pushes.

| PR | What |
|---|---|
| #3665 | the commitments follow-through ledger (#3553) + its full deploy runlist |
| #3680 | the Hevy Y counter derives from `EXPERIMENT_START_DATE` (#3671) |
| #3683 | mobile evidence shells stop scrolling past their own hero (#3542) |
| #3684 | CI timeouts re-derived from measured p95 + a headroom guard (#3678) |
| #3689 | `commitments-ungraded` made creatable + a guard over all 98 alarms (#3685) |
| #3693 | **the build readout** — the join, `/method/state/`, `/qbr` (#3691) |
| #3695 | the readout degraded on its first real deploy — `gh` token + PyYAML |
| #3696 | **main-red fix** — deploy-critical lane had no PyYAML |
| #3697 | the site publicly claimed `review_grade: "A"` (#3690) |
| #3698 | the chronicle manifest check reded the nightly for days (#3650) |
| #3701 | `current_started` re-anchored to the cycle-17 genesis (#3671) |
| #3679 | (inherited, merged at session start) the habitify fixture leak |

**Closed on live proof:** #3652, #3566, #3650, #3685, #3690, #3691, #3687, #3694.
**#3678 REOPENED** — a `Fixes` keyword closed it against my explicit recorded judgement that it
needed a week of runs; the reversal and the mechanism are on the issue.

---

## The flagship: the site path is proven open (#3652, closed)

Three-part proof, all cited by run id:

| # | run | trigger | `version.json` | QA | rollback |
|---|---|---|---|---|---|
| 1 | `34150694105` | dispatch | `533e226` @ 18:13:07Z | success | skipped |
| 2 | `34154159308` | **push** (#3665) | `deaed3e` @ 19:05:06Z | success | skipped |
| 3 | `34160729881` | control, `ai-inject` | — | **red** | **DECLINED by name** |

The control's annotation, verbatim: `Site rollback DECLINED (#3352/#3395) — visual-qa: 1 of 1
failed page(s) are NOT site/**-reachable (surface=ai-unevaluated; all: ai-unevaluated=1)`, with
`version.json` unchanged. Five more clean site deploys followed.

Verified the a11y batch by **content**, not sha: `<title id="archSvgTitle">` + `aria-labelledby`
live on `/method/build/`, `<h1>` on `/subscribe/confirm/`, `cap-h` as `h3` ×5 with no `h4`,
`<th>` labelled, `role="tabpanel"` on a `<div>` with **zero** residual `<article>`.

**Closed on boxes 2–4 only.** Box 1 asked for a *retry* on a truncated judge verdict; #3656
delivered a *budget raise*, which is a mitigation, not the mechanism. Filed as **#3688** rather
than waved through.

---

## The new surface: `/method/state/` (#3691, live)

`https://averagejoematt.com/method/state/` — "The build". Unlisted, deterministic, regenerated on
every site deploy. As served at wrap: **110 open → 72 actionable**, of which **46 came from
commissioned audits**, **10 touch anything a reader sees**, **9 P1 / 0 P0**. Delivery over the true
30-day population: **662 closed, 756 PRs, median cycle 12.6h**, split organic 8.7h vs audit-sourced
29.2h. Plus graded lenses prior→now, what awaits live proof, incidents, gate census (90/637 proven),
and spend from the governor.

**It shipped four bugs and fixed all four — every one found by running it, not reading it:**

1. **It truncated its own population** — capped GitHub paging at 400 and reported `closed: 400,
   prs: 400`, both exactly the cap, with a median over an arbitrary subset. Truncation now derives
   from the search API's own `total_count`.
2. **The page rendered nothing, with ZERO console errors.** `isBad(d)` is a *scalar* placeholder
   detector; `String(anyObject)` is `"[object Object]"`, which matches its `/^\[.*\]$/` test, so the
   guard was unconditionally true. It read as "data not generated yet". → memory
   `reference_isbad_is_a_scalar_detector`.
3. **Month-to-date spend was missing entirely** and ceiling/surge both showed `$252.00` with no
   `surge_active` — the key set was *guessed* and silently kept only what matched.
4. **Three sections vanished silently on failure** while the footer claimed they were "shown as
   gaps above" — found by running the negative control.

**The honesty contract earned its keep on the first real deploy:** it shipped green with **5 of 9
sections null** (`gh` has no token in Actions; the census had no PyYAML). Because each section
carries its own error, one fetch named every cause. A design retaining last-known values would have
shown plausible laptop numbers with no way to know.

---

## The stabilise pass (the owner's "should a 6-day pause worry me?")

**It should have, and the answer was found by checking rather than asserting.**

- **main was RED ~3h** — #3684's new test imports `yaml`; the deploy-critical lane installs no
  PyYAML, and a collection error takes the whole lane. **Third lane in one day**, and the **third
  appearance of this class in `INCIDENT_LOG`**. Fixed in #3696.
- **Two deploy leases stranded 9.1h**, both **ancestors**. Rejected per the standing rule; the
  platform had auto-filed #3694 and nothing escalated it.
- **The site was publicly claiming `review_grade: "A"`** while the newest review graded **zero**
  lenses at A (B+ 9 / B 3 / B- 3 / C+ 2). Now serves `B+` with the distribution beside it, plus
  `site_pages` 77→93 and `active_secrets` 21→28. Deployed and verified live.
- **The nightly had been permanently red since 09-03** on a false positive, so a real regression
  would have been invisible beside it. Fixed and deployed; verified `ok` against the real partition.

---

## Two controls that had expiry dates on them

Both found the same way — by doing the correct thing and watching a guard fail:

- `test_deploy_critical_lane_imports_2758`'s mutation proof planted `import yaml` **because yaml was
  forbidden**. Adding pyyaml legitimately made the plant legal and the control silently stopped
  proving anything. Repointed at `requests`, which CLAUDE.md forbids outright.
- `test_training_phases_config_still_carries_the_phase_anchors` pinned `current_started ==
  "2026-06-16"` — a literal pin on a value **its own docstring says the owner advances by hand**.
  Now asserts the field exists, parses as ISO, and names a real phase; watched red on all three.

**A positive control keyed to a value that can later be sanctioned is a control with an expiry date
on it.** Worth carrying forward.

---

## Owner threads answered mid-session

- **"Pull 3 - 2" naming** — Y=2 correct; N=3 correct *by the rule* and wrong in fact, because
  `current_started` still read `2026-06-16`. Re-anchored in **both** copies; the S3 one is what
  matters (`load_phase_state` reads local-then-S3 and the file is **not** bundled — the #3675 trap).
  Proven on the Lambda's own path with `CONFIG_DIR` pointed at an empty dir.
- **Training-note extractor brief** — verified and **corrected the owner's leading hypothesis**:
  truncation returns `[]` and never raises, so it leaves `degraded: False` — a *silent* degradation
  that doesn't set the flag, which means `degraded` **undercounts**. Filed #3699. Ruled out the
  model id and the monthly cap so nobody re-checks them.
- **"Pull the cardio comments forward"** — the capture side is already correct: today's record
  carries `note="Level 9 - 5.6 miles"`, `distance_m=9012`, `duration_sec=1800`. The gap is one
  branch: `render_history_cue` returns `""` for any set without weight+reps, so cardio gets no cue.
  Filed #3700.

---

## Gate marker lines

**Build beat:** none — the session's headline (`/method/state/`) is an owner-facing internal
surface, and `docs/content/BUILD_DISPATCH_CHECKLIST.md` scopes beats to reader-facing shipped work.
**Docs:** `docs/INCIDENT_LOG.md` (+2 rows), `docs/alarm_citations.json` (re-cited),
`docs/PROPORTIONALITY.md`, `docs/PLATFORM_NORTH_STAR.md` (fifth audience),
`docs/SITE_MAP_AND_INTENT.md` (the new page) — all landed in their own PRs.
**Decisions:** none needed — no governance-consequential choice was made that an existing ADR does
not already cover; the north-star audience addition is recorded in that doc itself.
**Main:** green (ba1cb95a) — HEAD `5262538f` has its run in flight; the two stranded ancestor leases
were rejected, which is what returned the board to green.
**Incidents:** 2 row(s) added — main red ~3h on the recurring undeclared-PyYAML deploy-critical
class (its third appearance in this log), and the 9.1h production-deploy wedge from two
undispositioned ancestor leases.
**Stash/hooks:** clean
**Closures:** #3652, #3566, #3650, #3685, #3690, #3691, #3687, #3694 commented; #3678 REOPENED
(a `Fixes` keyword closed it against a recorded judgement) · DoD: scanned 2, hits 1 —
`post-close-comment` on #3690, which is my own corrected live-proof line (the first carried
`03:1xZ`, a placeholder the instant regex correctly refused); blocking=none.
**Backlog:** Now live at 7 in-lane (floor 3) — nothing to promote; `later_staleness` clean, no stale
`Later` issues to call. `check_backlog_hygiene` prints **61 violations over 56 issues and ZERO of
them is an issue this session filed, touched or closed** (verified by set-differencing the violator
list against this session's 24 issues) — all nine of my filings are contract-clean. The remainder is
the standing pre-#3594 debt: 52 `set_section` on issues filed before that rule existed, 5
`acceptance_count`, 4 `epic_story_coverage`. **#3594 is the issue that owns it**, and paying it down
is a backlog campaign, not a wrap step.
**Alarms:** 4 lit, all cited — `qa-smoke-failures` re-cited 2026-09-08 against the live cause the
#3501 check caught contradicting it; `commitments-ungraded` is deploy-day `INSUFFICIENT_DATA` and
clears over ~7 days; `chronicle-delivery-heartbeat` clears on Wednesday's send; the fourth carries
no actions.
**CI warnings:** 6 — one coverage-floor drift (74% vs 84.2%), filed this session as **#3686**; five
identical playwright-skip lines from **#3640**, which is a by-design loud-skip reporter and needs no
action.
**Ledger:** owner-facing build readout row added (#3691) — posture, rent and demote trigger.

---

## Residual / next picks

- **#3699** — training-note extractor throws every degrade reason away; truncation degrades
  silently. Raw notes are sovereign and backfillable, so the pause costs nothing irreversible.
- **#3700** — cardio has no progression loop; `render_history_cue` returns `""` without weight+reps.
- **#3692** — `mcp/registry.py` is at its size ceiling and cannot accept any new tool.
- **#3688** — the truncated-judge-verdict retry (#3652 box 1).
- **#3686** — the coverage floor sits 10.2 points below measured.
- **#3681** — the theme-river build has never succeeded in CI (no `dynamodb:Query`).
- **#3682** — the wrap's Phase-1 doc gates run before Phase-2 writes the docs they derive from.
- **#3678** (reopened) — needs a week of PR traffic with zero `cancelled` verdicts.
- **#3651** — not closeable as written: all four stuck ledger rows aged out of `RETENTION_DAYS = 7`.
  Disposition recorded on the issue.
- **#3563 leg 2 / #3568** — both need Wednesday 2026-09-09's chronicle send. The IAM grant is
  verified deployed, so `/api/status` should go green on its own.
- **The #3679 history exposure** — `not-work — an owner disclosure decision; a forward fix cannot
  remove a name reachable at `3cea6db44` on a public repo.`
- **`current_started` will drift again at the next reset** — carried on #3671; it is a
  hand-maintained field in an S3-read config `restart_pipeline.py` does not own.

---

## For the next session

Main is green, the site is live at `5262538` matching `main`, no PR is open, no lease is waiting,
and `/method/state/` is the fastest way to see where things stand. Note it regenerates on **site
deploys** — during a development pause it will honestly show its own `generated_at` ageing rather
than refreshing.
