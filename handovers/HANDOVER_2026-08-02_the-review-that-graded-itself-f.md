# HANDOVER — the gate that had been switched off for 26 days — 2026-08-02

> Instruction thread: **#1920 BEFORE #1921**, and let #1920 refute the hypothesis. Then #1921
> (split deploy-health from content-truth), then the rest of epic #1890. Matthew gave standing
> approval mid-session for the merges, the deploy-gate approvals and one CDK deploy; the
> ceiling number in #1927 was explicitly reserved as his.

## Shipped — all merged, deployed and live-verified

| # | what | PR | live evidence |
|---|---|---|---|
| **#1921** | the smoke oracle partitioned; only `deploy_health` may revert | **#1926** (`61a4b23a`) | deployed qa-smoke returns `failed: 1, failed_deploy_health: 0, failed_content_truth: 1` |
| **#1909** | `/api/status` reads the governor's breakdown, not a hardcoded `15.0` | **#1929** (`9bdd172a`) | `budget 85.0 · 22% · green · tier 0` (was `627% / red`) |
| **#1904** | 49 of 82 catalog entries remapped + cast guard generalised | **#1930** (`953babf4`) | live catalog: 82 entries, 8 recommenders, **zero** off-roster |
| **#1923** | the wake-date frame pinned deterministically | **#1932** (`58db6c9c`) | `as_of 2026-07-31 · night_of 2026-07-30 · frame last_night` |
| **#1927** (part) | `budget-tier-sustained-7d` alarm | **#1928** (`037732ba`) | live in AWS: Minimum/21/21/604800s/digest |
| — | ci-cd concurrency salted to v4 after a third wedge | **#1933** (`80d567d5`) | new runs pick up immediately |

**#1920** closed with its measurement. **#1925** closed by filing **ADR-147**.

## The session's actual lesson: four of six premises were wrong

Same shape as the last session, which is now a pattern worth naming rather than re-learning.

| issue | the stated premise | what measuring found |
|---|---|---|
| #1920 | "classify 30 days of stored HIGH verdicts" | the check had been **budget-paused 26 of those 30 days**. Both sides of the argument were about something switched off. |
| #1909 | "`status: red` is load-bearing for `overall`" | it is not — `overall` is computed from component failures **before** the cost block is built. But measuring found a defect nobody had filed: the cost block **vanished every month-start** (`Start == End` → CE `ValidationException`, 3 logged). |
| #1904 | "5 names across 46 entries" | 82 entries, **49** to fix. And the names split two ways — Maya/Kai are in `personas.json`, Lena/Sofia/Raj are in no registry — so a "not in the retired list" guard would have passed 18 of the 49. |
| #1923 | reads as though it covers `recovery_night_of` too | that is a **different quantity** (a borrowed-recovery date, #495/M-9). Asserting the invariant across both would have been wrong. |

**#1921 earned itself within the hour.** The deployed Lambda's very next run returned `failed: 1`
with `failed_deploy_health: 0` — the old oracle would have reverted 100 Lambdas on that; the new
one shipped the deploy and still emailed, logged and alarmed the finding.

## Verified

- **8,230 tests** pass; full suite run before each merge.
- **Every guard negative-tested by breaking the fix**, then restored: oracle split reverted → content test fails; a partition stripped → AST scan fails; the #1345 DR drill moved to `content_truth` → drill test fails; `Minimum`→`Maximum` → sustained-alarm test fails; a 22nd period → the 604800s cap test fails; the `night_of` offset → 3 fail; an inline offset restored → the derived scan fails.
- **Bundle boot from a staged tree with the repo off `sys.path`** for both cross-package changes.
- **Deployed bytes downloaded and inspected**, not inferred — twice, and the second time it caught a stranded deploy.
- **`cdk diff` read before deploying** — it caught my `_alarm()` change adding `DatapointsToAlarm: 1` to ~30 untouched alarms. Scoped to multi-period only; final diff is exactly one new resource.

## Gotchas hit

- **A run can report `Deploy: skipped` AND `success` while leaving a merged change undeployed.** #1923 sat live-less for ~1h because the run that would have shipped it was the one I cancelled, and the next run was on a workflow-only commit. Only inspecting the deployed zip caught it.
- **`git checkout --ours` on a rebase conflict takes main's WHOLE file** — it would have silently deleted the new `night_of_for` helper while every test still passed on the stale copy. Resolve the hunk in place when your branch also modifies that file.
- **I chained shell commands past a failed `git rebase --continue`.** It hadn't succeeded; the following `--amend` rewrote the wrong commit and I force-pushed it. `git rebase --abort` recovered everything, but by luck — the working tree still held the changes. Check the exit code.
- **I hand-listed an allowlist in the #1904 guard and got it wrong** (missed `"Social Connection"`), which would have red-flagged *correct* config — the exact drift class I was fixing. It now imports `OWNER_ROLE_LABELS` from the #1891 guard.
- **Every PR touches the auto-synced `test_count` literal** — three rebase conflicts. Merge one, rebase the next.
- **doc-sync stamps UTC**: crossing 17:00 PT rolled ~10 docs to `2026-08-02` mid-session.
- **`deploy_site_api.sh` prints "✅ site-api OK" on a 403** — it only asserts the handler imported (403 is the correct direct-invoke response for *any* route, `/api/status` included). True to what it checks; more reassuring than the evidence.

**Build beat:** `2026-08-02-the-check-that-had-been-switched-off-for-26-days`
**Docs:** `docs/DECISIONS.md` (**ADR-147** + regenerated index, 145 records), `docs/INCIDENT_LOG.md` (+4 rows), plus the auto-synced literal/stamp pages.
**Decisions:** **ADR-147** filed — the smoke oracle answers two questions; only deploy health may revert a deploy. Closes #1925, whose blocking input (#1920) landed this session.
**Main:** green (`80d567d5`) — `check_main_green.py` ✅.
**Incidents:** 4 rows added — **Whoop ingestion dead since 2026-08-01 12:00Z on an OAuth 401 with the auth breaker latched (P2, a real data gap, #1934 — needs your interactive re-auth)**; the 26-day cutoff-1 band outage (P3); the third phantom concurrency wedge that left #1923 merged-but-undeployed (P4); a visual-QA false positive where a connection reset was recorded as a leak finding (P4).
**Closures:** #1920, #1921, #1923, #1925, #1909, #1904 commented with ADR-099 outcome verdicts.
**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.
**Backlog:** Now live at **6 actionable** (no refill needed, threshold 3); `later_staleness` clean; hygiene **0 violations over 71 open issues** (2 pre-existing rounding advisories on #1677/#1679, not mine).

## Residual / next picks

1. **#1934 — Whoop is dead and only you can fix it.** OAuth 401, auth breaker latched since
   2026-08-01 12:00Z; `DATE#2026-07-31` is the last record and the gap grows daily. Whoop is
   the only fully passive daily source and is `qa_required` — it feeds recovery, HRV, RHR and
   sleep, and therefore the readiness score, the daily brief and `/api/vitals`. Fix:
   `python3 setup/setup_whoop_auth.py --backfill` (redirect `http://localhost:3000/callback`;
   the page will NOT load — paste the full `?code=…` URL back, codes expire in ~30–60s).
   Nothing alarmed: `qa-smoke` checks PT-yesterday, which was still 07-31 all session.
2. **#1931** — the leak sweep records a connection reset as a finding and reds a gating job.
   Small, fully specified, closes a class.
3. **Fable delta review — do this FIRST of the automatable work, and only Fable may do it.** `not-work — a scheduling
   constraint, tracked in [[project_fullreview_panel]].` The run-2 partial has been banked since
   2026-07-28 at 14/17 lenses (72 findings, 0 filed) and is due on/after 2026-08-02, which is now.
   Run the 3 ungraded lenses (security, data-architect, growth), re-apply
   `docs/reviews/fullreview_grades_2026-07-16.json` anchors **verbatim**, then file the ~55 held
   findings in ONE pass (epic #1890 is explicit: not ad hoc).
4. **#1922** — compute phase-plausibility deterministically. Highest-leverage item open: 5 of the
   8 false positives I classified were one arithmetic complaint restated.
5. **#1927** — the **measurement half only** is unowned work: where does $98/month actually go,
   by service and by AI feature. The ceiling number itself is Matthew's and has an **~2026-08-21**
   forcing date (at $85 the simulation reaches tier 3 — all Bedrock off — around then).
6. **#1892 / #1893** (credibility) and **#1896 / #1897** (ai-integrity) — each pair shares a
   subsystem; do them together.
7. **#1919** — the 11 intensive `_Nd` fields left ungated, declared debt.
8. **Standing alarms (#1329)** — `not-work — checked, nothing outstanding.` No digest-routed
   freshness alarm or manual-rotation secret reminder is aging; next MCP-bridge key rotation
   2026-10-05.
9. **Worktree prune** — `not-work — housekeeping, no issue warranted.` ~130 stale entries under
   `.claude/worktrees/`.
10. **If ci-cd wedges a fourth time** — `not-work — a conditional ops instruction.` Do **not** just
   salt to v5; replace the hand-bumped counter with a per-run-unique component.
