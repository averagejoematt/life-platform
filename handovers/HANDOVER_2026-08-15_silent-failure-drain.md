# Handover — 2026-08-15 (overnight): five things were quietly not working, and a green pipeline was hiding them

**Session:** interactive, Opus. Driver only, no subagents (the brief forbade them).
**Driver:** work the ranked non-fable `Now` queue as a straight drain, seeded from `scripts/backlog_next.py`, in printed rank order by each issue's own STORED score. Standing discipline block: every fix ships with a regression test **watched failing** against unfixed code; read `CONVENTIONS.md` §9a before any test crossing a service boundary; assume the filed scope is smaller than the defect and derive the affected set from source; **re-run the live probe AFTER deploying**; never write a closing keyword next to an issue number unless you mean it. Explicit do-not-touch: #2680 and #1221's remaining half (one CloudFront migration, owner present), #2468, `model:fable`. Mid-session the owner extended it to "work as many as you can through the night."

**Build beat:** `2026-08-15-the-green-pipeline-that-was-hiding-five-things`
**Docs:** `.claude/commands/wrap.md` (orphan-gate grep — see gotcha 7) · `docs/engines/COACH_STANCE.md` (re-verified — four `ai_calls.py` spans drifted a uniform +10 from my own additive change; AST-re-derived, new verify entry rather than a rewrite of the prior dated ones) · `docs/INCIDENT_LOG.md` (+1 P3 row, `Last updated:` bumped)
**Decisions:** none needed — the session applied existing contracts (ADR-104 honest numbers, ADR-099 filing + closure, ADR-125 budget bands, §9a fixture-is-the-wire). The one genuine governance question raised — what `published_vitals` should *mean* — is deliberately left to Matthew on #2634 rather than decided unilaterally.
**Main:** stranded — R8-ST6 Plan-red at `ed98d082` (#1901 class). The **cause** is cleared: the owner ran `cdk deploy LifePlatformOperational` at 16:33Z and `cdk diff` now shows **zero** remaining IAM changes, so the next Plan should pass. But the **state** is not: I first wrote that this wrap commit's own run would be the recovery — it is not, because `ci-cd.yml`'s push filter covers `lambdas/** cdk/** tests/** ci/** config/** .github/workflows/**` and a docs/handover/beats commit matches none of them, so no CI/CD run fires. **Recovery is a `deploy_all=true` `workflow_dispatch` of ci-cd.yml** (the gate's own decode), or the next code-touching push. Re-run `check_main_green.py` after either.
**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢
**Closures:** #2644, #2649, #2655, #2659, #2672, #2673, #2688 commented (all `realized`, each with live post-deploy evidence)
**Incidents:** 1 row added — the code-deploy pipeline stranded ~14h by the R8-ST6 IAM gate firing *correctly* on the canary-DLQ grant; every deploy that night went around it via the per-function path
**Backlog:** Now live at 15 actionable; no stale `Later` issues
**Alarms:** 0 uncited — every alarm red >72h cites an incident row or issue
**CI warnings:** none to triage — the latest completed main run isn't green (that's the stranded state above, `check_main_green.py`'s job, not this gate's)

---

## What shipped — 14 PRs, all merged AND deployed

| PR | Issue | What |
|---|---|---|
| #2693 | #2655 | config-channel errors name their cause (denial vs absence) + canary DLQ |
| #2695, #2699 | #2644 | `CONTENT_FILTER_JSON` actually reaches the scan; standing guard over every reusable-workflow call |
| #2696 | #2688 | type guards on all four AI body-parsing sites |
| #2697 | #2681 | follow doors reject the ids their vote siblings reject |
| #2700 | #2659 | schema-driven numeric bounds at the MCP tool boundary |
| #2701 | #2649 | literal-drift gate fails on substance, not the calendar |
| #2702 | #2651 | I16 derives its windows from the source registry |
| #2703, #2704 | #2673 | cockpit distinguishes "request failed" from "hasn't computed" |
| #2706 | #2668 | IC-3 token cap sized against measured output; fails loudly |
| #2707 | #2705 | a failed recall index records WHY, and not at INFO |
| #2709 | #2672 | scope switch is a navigation, not a silent mutation |

**Deployed:** `life-platform-site-api`, `site-api-ai`, `ai-quality-canary`, `mcp`, `daily-brief`, `chronicle-approve` (per-function, `deploy_lambda.sh` / `deploy_site_api.sh`) + two `site/**` auto-deploys. Site smoke **241/0** at both ends. Visual QA 2 passed / 0 failed.

## The through-line

None of these were broken features. All were **working code that discarded the reason it failed** — the safety net did its job and threw away the one detail that made the failure actionable. So most fixes did not change *what happens* on failure; they changed *what gets said about it*, and were deliberately careful not to escalate the ordinary (a paused budget, an idempotent no-op, an empty-text skip all stay quiet — each pinned by a test, because a channel that shouts about everything is exactly as useless as one that says nothing).

## Gotchas — read these before the next session

1. **A fix can ship completely green and do nothing.** #2703 passed 4 unit tests, full CI, the deploy and the visual-QA gates. The live page was unchanged. The deployed file provably contained the change — `load()` fetches through `Promise.allSettled`, which **discards the rejection**, so the tagged error never reached the catch. My tests extracted the *shipped* `getJSON` and ran it under node: real code, honestly exercised, **wrong code path**. §9a in a new costume — extracting real source is necessary and not sufficient if you extract the wrong real source. Only the post-deploy browser probe caught it (#2704 fixed it properly).
2. **The filed scope was smaller than the defect in every single issue worked.** #2688 said three doors returning 500; the wire showed **two** failure modes and a fourth site (the 502s escaped the handler entirely, hitting the *Lambda* error metric). #2659 said "six tools"; the registry says **16 relative-window args**. #2651's test hardcoded 5 sources and a flat window against **6 infrastructure sources with their own thresholds**.
3. **Module-size guards fired four separate times.** `mcp/registry.py` (2424), `lambdas/ai/ai_calls.py` (2396), `site_api_ai_lambda.py` (1991) are all at ceiling. Never raise a baseline — extract a sibling and pay for the lines (#2649 shrank `sync_doc_metadata.py` 1807 → 1780 that way). Watch `ruff`'s isort silently re-expanding an import block (+2 lines) and undoing the saving.
4. **Never `--amend` after a blocked pre-commit.** The hook rejected a commit, so HEAD was still main's tip — the `--amend` rewrote *that*. Reset to `origin/main --soft` and recommit.
5. **`gh issue comment --body` with backticks runs command substitution.** Half a closure comment's inline code was silently eaten. Use `--body-file`.
6. **My own wrong turns, both caught by existing guards.** Built a fix for #2634 on the wrong diagnosis — read a coach's dated citation as honest and loosened the check, which **broke 6 tests in `test_cross_surface_vitals_asof_2575.py`** that exist precisely to stop that loophole. Reverted whole; the old tests were right. And queried `LifePlatform/QA` instead of `LifePlatform/QaSmoke`, got zero datapoints, and nearly published "the metric is dead."

7. **The wrap's own memory orphan-gate was crying wolf 98 times.** Its grep checks only
   `MEMORY.md` and `project_shipped_archive.md`, but the ~55-entry review-discipline set is
   rolled up in `INDEX_review_discipline.md` — so every wrap saw ~98 `ORPHAN:` lines with a
   true count of **zero**. Fixed in `.claude/commands/wrap.md` (added `INDEX_*.md`). Same class
   as everything else this session: a gate nobody can act on is a gate nobody reads.

## Fleet drift worth naming

Everything merged was deployed **per-function** (the 6 Lambdas listed above), because the pipeline was stranded. Two of this session's changes are to **shared bundle modules** — `lambdas/privacy/content_filter_channel.py` (#2655) and `lambdas/ai/ai_calls.py` (#2668) — which ship inside *every* Lambda's bundle. So the rest of the fleet still runs the previous copies until a fleet deploy. Nothing is broken by that (the old code works, just with worse diagnostics), but it means a `deploy_all=true` dispatch is worth doing for the diagnostics to be uniform, not only to clear the badge.

## Residual queue / next picks

- Approved plan for the next session is written: `~/.claude/plans/joyful-whistling-scott.md` — autonomous non-fable drain, **evidence bar not closure count**, batches: the 9-issue MCP tool surface, the site-api honesty class, gate-honesty chores. not-work — a plan file, not a backlog item.
- **#2634** — diagnosed by measurement (both coaches' prose is exactly one morning behind their own stamp; the stamp is taken at *write* time while the narrative was produced earlier). The fix changes what `published_vitals` *means* — a design call for Matthew.
- **#2670** — blocked on #2634 and #2705's nightly re-confirm; do NOT widen a threshold to buy a green alarm over two real failures.
- **#2668** — box 3 is a 3-day observation. Check `aws logs filter-log-events --log-group-name /aws/lambda/daily-brief --filter-pattern '"IC-3 analysis pass failed"'` → expect zero. Never invoke the brief; it sends real mail.
- **#2694** — 13 scheduled operational Lambdas still have no DLQ (`cost-governor` sharpest). Needs an owner `cdk deploy`.
- **#2698**, **#2708** — the two contract-change splits (confirm-opt-in; recall's four-way `None`). Both are features, not logging fixes.
- **#2680 / #1221** — still one ~20-behaviour CloudFront migration off legacy `forwarded_values`; owner present. not-work this session by explicit instruction.
- not-work — after this wrap's CI/CD run completes, re-run `python3 scripts/check_main_green.py` to confirm the stranded state cleared.
