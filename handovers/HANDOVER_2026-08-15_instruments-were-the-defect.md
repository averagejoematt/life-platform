# Handover — 2026-08-15 (evening): the instruments were the defect

**Session:** interactive, Opus. Driver only, no subagents.
**Driver:** the approved plan `~/.claude/plans/joyful-whistling-scott.md` — work the ranked non-fable queue to the **evidence bar, closure count as output not target**. Batches: the 9-issue MCP tool surface, the site-api honesty class, gate-honesty chores. Standing discipline: a regression test **watched failing** against unfixed code, a **live probe after deploy**, `partial` with unmet boxes named rather than a close, assume the filed scope is smaller than the defect, never raise a module-size baseline. Mid-session the owner extended it twice — first to two issues found while verifying, then to "take care of those non-fable items as much as makes sense".

**Build beat:** `2026-08-15-the-instruments-were-the-defect`
**Docs:** `docs/RUNBOOK.md` (the dropbox role-grant row named a secret deleted 2026-05-17) · `docs/alarm_citations.json` (+1 entry, #2734) · `mypy.ini` + `tests/mypy_clean_set.py` (measured disable-list cost + owner moved off a closed issue)
**Decisions:** none needed — the session applied existing contracts (ADR-104 honest numbers, ADR-105 rigor, ADR-099 filing/closure, ADR-125 budget bands, ADR-153's own amendments). The one governance-shaped question raised — what should answer Grand Rounds — is deliberately left to Matthew on #2719 rather than decided unilaterally.
**Main:** green (`6b486bfc`) — verified by `check_main_green.py`. A fresh `deploy_all=true` dispatch (run `31908196662`, sha `c83725f8`) is in flight and **awaits Matthew's production approval**; two older gated runs were REJECTED, not left waiting (see gotcha 5).
**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢
**Closures:** 19 commented with live evidence (#2650, #2651, #2653, #2660–#2666, #2671, #2676, #2677, #2681, #2682, #2686, #2698, #2715, #2724). Four carry an honest `partial` naming unmet boxes: #2638, #2639, #2652, #2719.
**Incidents:** 1 row — my own #2639 test reddened the deploy-critical lane and skipped `Deploy` (see gotcha 1)
**Backlog:** Now live at 10 actionable; no stale `Later` issues; 2 filed this session (#2715, #2719) plus #2734 from the wrap's own alarm gate
**Alarms:** 1 red >72h, now cited — `budget-tier-sustained-7d` → #2734
**CI warnings:** 4, all one class — CDK config drift only an owner-run `cdk deploy` can ship (Operational is #2694, Email is #2669; Compute and Ingestion carry drift from earlier sessions and clear with the same deploy). Deliberate no-action this session: `cdk deploy` is owner-gated.

---

## What shipped — 21 PRs, all merged AND deployed

| PR | Issue | What |
|---|---|---|
| #2710 | #2666 | error suggestions name tools that exist — **2 dead names, 4 sites**, not the 1 filed |
| #2711 | #2660, #2664 | a supplied MCP argument is applied or refused — **27 declared enums, none enforced** |
| #2712 | #2663 | `days` filtered on **category names**, not dates |
| #2713 | #2662 | an unknown source no longer reads as "everything is fresh" |
| #2714 | #2671 | `get_sources` agrees with the domain tools — the 4th source was **`dexa`**, not `strava` |
| #2716 | #2661 | zone-2 adherence divides by the weeks asked about |
| #2717 | #2665 | the reading shelf returns books, not identifiers |
| #2718 | #2677 | the telegram router outlived the ADR that killed its route |
| #2720 | #2715 | a paused-by-design source no longer turns the verdict **red** |
| #2721 | #2719 | a route with no persona refuses instead of answering nameless |
| #2722 | #2682 | `experiment_suggest` keys on content — a double-click costs one review |
| #2723 | #2686 | a 200 from inside an `except` says it is a fallback — all 14 sites |
| #2725 | #2650 | the QA audit's budget bands derive from the runtime's own table |
| #2726 | #2639 | the gate census had the blind spot it exists to find — **20 gates, not 2** |
| #2727 | #2638 | the mypy disable list is priced (**415**), not implied-empty |
| #2728 | #2652 | API coverage counts against the live route table |
| #2729 | #2698 | a follow address is recorded unverified, and nothing may mail it |
| #2730 | #2653 | a docstring must not name a secret nothing can read |
| #2731 | #2676 | a narrative figure names the metric it came from |
| #2732 | — | hotfix: my own census test reddened the deploy lane |
| #2733 | #2640 | the hero-weight check was armed; it could not say it checked nothing |

**Deployed** per-function: `life-platform-mcp`, `life-platform-site-api`, `telegram-webhook`, `telegram-coach-worker`, `life-platform-qa-smoke`, `dropbox-poll`. Site smoke **241/0** at both ends. Doc literals in sync, zero open PRs, tree clean.

## The through-line

Last session's was "working code that discarded the reason it failed". This one is narrower and worse: **four of the defects were in the instruments built to catch that class.**

- `qa_audit` reported the AI CI gates budget-dark; #1927 moved them out of band 1 months ago, and `/qa` tells the operator to read that line first (#2650)
- `gate_census` — the instrument whose whole purpose is finding blind spots — had one (#2639)
- `qa_audit` reported "0 endpoints uncovered" because its denominator was the registry, not the router; two live 502s sat inside the 82 it could not see (#2652)
- `mypy.ini`'s residual pointed at a **closed** issue, so a reader concluded the disable list was empty (#2638)

And the hero-weight check (#2640) reported **green when it had examined nothing** — a green from a check that checked nothing is indistinguishable from a green from a check that checked something and liked it.

**The filed scope was smaller than the defect in every single issue worked, again.** 1 dead suggestion → 2. 1 coerced enum → 27 declared and none enforced. 2 missed CI gates → 20. 6 handlers to fix → all 14, uniformly. `strava` → `dexa`. That is now two consecutive sessions; treat the issue body as the *lower* bound and derive the set from source before writing a line of fix.

## Gotchas — read these before the next session

1. **My own new test reddened the deploy lane and skipped `Deploy`.** `test_gate_census_error_bars_2639.py` builds the census at **import** time, which pulls in PyYAML; `gate_census` imports it lazily precisely so the module stays importable without it, and a module-level build defeats that. The deploy-critical lane installs a minimal dependency set. Caught by the `deploy_all` run, not by me. Fixed in #2732 with `pytest.importorskip` — and checked that the gate still runs in the full `test / Unit Tests` lane, because a guard that skips everywhere is the "cannot fail" pattern that file exists to measure.
2. **`agent_commit.sh` restored a file I did not EXPLICITLY name, and I nearly shipped nine call sites without their function signature.** I passed the directory `lambdas/web/`; the script restores any doc-literal file not named individually, so `site_api_common.py` — carrying `_ok`'s new `degraded=` parameter — was reverted out of the commit. Every degraded path would have raised `TypeError` **inside its own except**, turning a degraded 200 into a 502. Caught only by re-running the suite AFTER the commit. **A directory argument is not a name.**
3. **A measurement that aborts silently reports zero.** All four mypy codes measured as **0 errors** — 436 filenames overflowed the shell's argv, mypy aborted with `File name too long`, and `grep -c` counted an empty run. A clean, plausible "this costs nothing to enable" that would have justified exactly the wrong decision. The real answer is **415**. `scripts/mypy_disable_cost.py` now uses an `@response` file and **raises** when mypy gives no summary line.
4. **I built the wrong fix for #2677 first and an existing test caught it.** I added back a `telegram_route_aliases` entry, believing ADR-153's data had never been written. `tests/test_persona_registry.py` pins `persona_for_telegram_route("training") == (None, None)` precisely because the **2026-08-12 amendment reversed the 08-10 one**. The alias was retired for a load-bearing reason — the primary route is the canonical OUTBOUND route, so an alias-only seat can be texted but can never text first. Read for a *later* amendment before "restoring" anything an ADR describes.
5. **A gated run pinned to a stale sha must be REJECTED, not approved.** Two `deploy_all` runs aged at the production gate; both were 13–16 commits behind main, so approving either would have rolled back everything already deployed per-function. `approve_deployment.sh`'s own header says to reject in exactly that case — but the auto-filed wedge alert (#2724) recommends *approve* unconditionally. Its advice has no ancestry check.
6. **My first three telegram probes proved nothing.** They used a wrong secret token, so all three died at gate 1 (secret check) and never reached routing. The discriminating probe is a **correct** secret with an **unauthorized chat id**: `resolve_coach` runs before `authorize_chat`, so the rejection *reason* in the log distinguishes the two gates — and the worker is never invoked, so nothing is sent.
7. **Module-size guards fired 3× more** (`registry.py` 2424, `tools_lifestyle.py` 1829, `site_api_ai_lambda.py` 1991). All paid for in-file: a description that duplicated the enum beside it, a comment folded from three lines to two, a generator rejoined. **Never raise a baseline.**
8. **`ALLOW_DOC_LITERALS=1`** is the sanctioned escape when a genuine content edit touches `site_api_common.py`, `docs/`, `CLAUDE.md` or `.claude/README.md`.

## Where I pushed back rather than complying

Recorded because each is a place the acceptance box was wrong, not the code:

- **#2653 box 2** wanted `grep -rn 'life-platform/dropbox' docs/` to return nothing. It cannot: three docs record the secret as **deleted, with dates**. Scrubbing accurate history to satisfy a grep makes the docs less honest. A test now pins that those rows **stay**.
- **#2683** was confirmed CloudFront-side (`Server: AmazonS3`, `X-Cache: Error from cloudfront`) — the excluded distribution work — and stopped rather than half-done. Labelled `gate:owner`.
- **#2639 boxes 2–3, #2652 box 3, #2638 boxes 2–3** all ask for *adjudication* — reading 38 workflow steps, writing 69 route reasons, fixing 415 type errors. Each shipped the mechanism and left a **named, finite, printed queue** instead of asserting it away. `partial`, with the residual counted.

## Residual queue / next picks

- **#2734** — filed by the wrap's own alarm gate: projected month-end **$230.58 against a $135 ceiling** that reverts to $85/$100 on 2026-09-01. Tier pinned at 1 since Aug 5. The tier being 1 not 3 is **correct** (N-08 caps projection one tier above actual mtd) — the finding is that the slowest early-warning has been lit 3 days with nobody obligated to answer.
- **#2694, #2669** — the batched owner `cdk deploy` list, and the cause of all 4 CI warnings: `cd cdk && npx cdk deploy LifePlatformOperational LifePlatformEmail LifePlatformCompute LifePlatformIngestion`
- **#2719** — the board bot's routing is a Grand Rounds design call under epic #2363; the refusal half shipped
- **#2638, #2639, #2652** — mechanisms shipped, residuals named and printed; each needs human adjudication
- **#2634, #2668, #2670, #2705** — multi-day observations and a `published_vitals` semantics call
- **#2674, #2692** — the two I deliberately did not start at depth: #2674 needs browser measurement + screenshots, #2692 needs `--durations` off a real CI run
- **#2642, #2643** — stay excluded (destructive S3 / data write)
- **#2680, #1221, #1571, #1738, #1677, #2683** — `gate:owner`
- not-work — re-run `python3 scripts/check_main_green.py` once run `31908196662` is approved and completes; it is what levels `lambdas/ingestion/source_state.py` (a shared bundle module changed by #2715) across the fleet. Only 6 Lambdas got it per-function, so `ai-expert-analyzer` and `pipeline-health-check` — the two consumers #2715 deliberately changes — still run the old copy.
