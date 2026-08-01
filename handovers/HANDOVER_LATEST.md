# HANDOVER — the window that was never 30 days, and the gate that was never the bug — 2026-08-01

> Instruction thread: **#1917 FIRST — it is a live blocker.** Every merge was deploying,
> failing smoke, and auto-rolling-back (100 Lambdas reverted on a healthy deploy). Then
> approve the stranded `7408e326` deploy and confirm main goes green. Standing approval was
> given in-session for the merge, the deploys, and the gate approval; a mid-session fork on
> gate posture was escalated and decided by Matthew.

## Shipped (all merged AND live-verified)

- **#1917** (PR **#1918** + follow-ups `00ced6dd`, `cee3cb60`) — no published field named for
  an N-day window carries a value until the window really spans N days. Both halves ship:
  the real number under a window-generic name beside its actual span, and the legacy `_Nd`
  key gated on `full`.
- **#1924** (`5471631a`, `b1c55bb4`) — the daily-brief coach generator now receives its
  weigh-in **with its own date**, and `cross_surface:weight` no longer flags a citation the
  prose explicitly anchors to a past point.

**Outcome that matters:** `qa-smoke` returns `failed: 0` on **4 consecutive runs**, and
ci-cd run **30713984885** completed **success end-to-end — Deploy ✅, Smoke ✅,
Auto-rollback skipped**. First clean merge→deploy since 07-31. The stranded `7408e326` run
was **cancelled, not approved** (below).

## The premise was wrong three times, and only measurement caught it

This is the session's actual lesson. Each wrong answer was plausible and would have shipped
a fix that did nothing.

| # | The plausible story | What the data said |
|---|---|---|
| 1 | #1917: "a real 30-day delta spans genesis" | #1084 already genesis-clamps the window. `/api/weight_progress` returns the WHOLE cycle — 3 records, 321.1 → 317.0 — and `317.0-321.1 = -4.1`, exactly the published `weight_delta_30d`. The arithmetic was always honest; only the **name** lied. |
| 2 | "the summariser hallucinated 316.3" | `position_summary` is **empty** on the OUTPUT# row; the dashboard falls back to raw `content`. No summariser is on that surface at all. |
| 3 | "the stale weight blocked the gate" | `\|316.3-317.0\| = 0.7`, **inside** the 1.5 lb tolerance. It never tripped anything. The blocking failure was **100%** the false positive on the correctly-labelled `321.1 … at Day 1`. |

**#2 cost a whole module.** I built `summary_grounding.py` + 8 tests on that theory and
**reverted it unshipped** — its headline test fed the fact set instead of the real
narrative, so it asserted a repair that would never have happened in production. A green it
had not earned. Deleting it was cheaper than the false confidence.

**#3 was a claim I made to Matthew in writing before checking the tolerance.** Corrected in
the commit message and here; the staleness is a real honesty defect, it simply was never
what blocked the pipeline. One line of qa output looked like one problem and was two.

## What "guard the set" bought — fourth session running

- **#1917's AST registry found 7 fields I had missed by reading.** They use the **prefix**
  form (`30d_avg_mg_dl`) on `/api/glucose` + `/api/sleep`; every `_30d`-**suffix** grep
  misses them, including the one I ran first. Found on the scan's first execution.
- **The worst instance was invisible to qa-smoke entirely**: `daily_brief` wrote
  `weight_delta_30d` from `week_ago_weight` — a **7-day** number under a 30-day name, wrong
  on *every* day of *every* cycle, which `weekly_signal` rendered to a human as
  `(↓4.1 lbs 30d)`.
- **#1924 was the same shape one level up**: #1894 fixed staleness in
  `ai_expert_analyzer`; the **second** coach generator (`daily_brief` →
  `ai_context._build_physical_data`) never got it. A test now asserts BOTH import the shared
  `weight_recency` and that neither re-defines `STALE_AFTER_DAYS` locally.

## The gate-posture fork (Matthew's call, and he was right)

`reader_truth` produced **2 true findings then 6 false positives across 5 runs** — six
different rationales, including flagging the #1917 fix itself, its own `window_disclosure`
echoed back, and the **deliberate, documented** `night_of`/`as_of_date` frame as HIGH.

I recommended demoting it to advisory. **Matthew pushed to fix things properly instead.**
That was the better call — the gate is green because two real defects got fixed and one
under-specified rubric got corrected, **not** because a bar was lowered. Recorded because my
recommendation was the weaker one.

The rubric defect was real and is fixed (`cee3cb60`): it stated only that a window LONGER
than `day_n` is impossible and never that a SHORTER one is expected — so after a reset,
where **every** clamped window is short by design (ADR-077 "clamped, not hidden"), it read
the platform's own honesty as a lie.

## Gotchas hit

- **Approving the stranded `7408e326` run would have REVERTED the day's work.** It is an
  ancestor of the fix; its tree is missing all 6 changed Lambdas. The prior handover said
  "approve it after #1917" — correct when written, a trap once #1917 merged. **Cancelled.**
  (`reference_ci_deploy_race_manual_overwrite`.)
- **I deployed the rubric fix to Lambda ~30 min before pushing it** — repo and live
  disagreed in between. Self-inflicted drift; caught at a routine `git log origin/main..HEAD`.
- **`qa-smoke` invoked off-schedule fails `dashboard:date` legitimately** — daily-brief
  writes the dashboard at 17:00 UTC, so between 00:00 and 17:00 UTC it is one day behind by
  design. I nearly logged a timing artifact as a third blocker.
- **`/api/sleep` is not a route** — it is `/api/sleep_detail`. I invalidated a path that
  does not exist and had to redo it.
- **`deploy_lambda.sh` takes the LIVE function name** (`life-platform-qa-smoke`), not the
  `ci/lambda_map.json` key.
- **CloudFront caches `/api/*` for 300s**, and `reader_truth` fetches through the edge — so
  a post-deploy smoke can read a stale payload. Deploy → invalidate → verify → *then* the
  gate.

## Verified

- **Full suite 8,184 passed**, 0 real failures (two doc-sync count failures cleared by
  `sync_doc_metadata.py --apply`).
- **Deployed bytes inspected, not inferred** — downloaded the live site-api zip; `_window_span`
  present in `site_api_common`, gated keys present in `site_api_vitals`.
- **Bundle boot with the repo OFF `sys.path`** — `ai_context` reaches `weight_recency` across
  packages, the rider fires, the coach sees `as_of 2026-07-28`.
- **Live payloads on all three endpoints**: `_30d` keys null; `weight_delta_lbs -4.1 /
  window_days 5`; `hrv_avg_ms 55.2 / n 5`; glucose + sleep the same shape.
- **Negative-tested both ways** — reverting the `_Nd` gate fails on the live `-4.1`;
  injecting a new field fails the AST scan; a window name in a *comment* does not; an
  undated out-of-tolerance weight still FAILs the cross-surface check.
- `qa-smoke` **4/4 green**; ci-cd **30713984885 success**, auto-rollback **skipped**.

**Build beat:** `2026-08-01-the-window-that-was-never-thirty-days`
**Docs:** none needed — no deploy path, data model, algorithm, MCP tool, secret or site
page changed; the #1917 decision is recorded on `_window_span` where the window is measured,
and the residual debt is issue-tracked (#1919).
**Decisions:** none needed — the gate-posture question is deliberately **not** decided this
session; #1925 files the ADR *after* #1920 measures precision, which is the whole point.
**Main:** green (`b1c55bb4`) — `check_main_green.py` ✅.
**Incidents:** none — the 100-Lambda auto-rollback that motivated #1917 fired 2026-07-31 and
is already logged by the prior session; nothing new fired today.
**Closures:** #1917, #1924 commented with ADR-099 outcome verdicts.
**Stash/hooks:** clean.
**Backlog:** Now live at **8 actionable** (no refill needed — threshold is 3); no stale `Later`
issues, so no promote-or-close calls were due. 6 issues filed (#1919–#1925 less #1918), and the
filing-contract linter now reports **0 violations across all 74 open issues** (was 12 — all mine,
fixed this session: missing `## Outcome`, ASCII score grammar, epic `## Stories` coverage).

## Residual / next picks

1. **#1920 — measure `reader_truth`'s real precision.** Take it BEFORE #1921. I built much
   of today's argument on it being unreliable, then it passed 4/4 after the fixes. That is
   genuinely ambiguous, and #1921's design must not rest on my bad afternoon.
2. **#1921 — split the smoke oracle** so a *content* finding cannot revert *code*. Stands
   regardless of #1920's result: even a perfect check is answering a question that should
   not trigger a rollback. Third instance of the #1911 class in three sessions.
3. **#1919** — the 11 intensive `_Nd` fields left ungated, declared as visible debt in the
   registry rather than silently passing. `group_90d_avgs` is most exposed (under-fills for
   3 months after a restart).
4. **#1922 / #1923** — convert the AI's real findings into deterministic rules
   (phase-plausibility; the `night_of` frame). This is the "AI proposes, rules dispose" loop.
5. **#1909 · #1904 · #1892 / #1893 · #1896 / #1897** — the rest of epic #1890.
6. **Fable delta review due on/after 2026-08-02** — `not-work — a scheduling constraint.`
   Do not let another model finish the banked `/fullreview` partial (14/17 lenses).
7. **The stale coach narrative self-heals at the next 17:00 UTC brief** — `not-work — a
   scheduled regeneration, no action needed.` Today's published text still reads "the
   latest reading is 316.3 lbs"; the check now correctly tolerates it and the generator fix
   is live.
8. **Standing alarms (#1329)** — `not-work — checked, nothing outstanding.` No digest-routed
   freshness alarm or manual-rotation secret reminder is aging; next MCP-bridge key
   rotation is 2026-10-05.
9. **Worktree prune** — `not-work — housekeeping, no issue warranted.` Still ~130 stale
   entries under `.claude/worktrees/`.
