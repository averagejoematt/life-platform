# Handover — 2026-08-15 (late evening): make the alarm board mean something

**Session:** interactive, Opus. Driver only, no subagents.
**Driver:** the approved plan `~/.claude/plans/alarm-board-that-means-something.md` — *every red CloudWatch alarm either signals, or is silenced with a written reason AND a proof it can still fire. Closure count is the OUTPUT, not the target.* Batch 1 the alarm board (#2670 the anchor, `coherence-overall` triaged first), Batch 2 the three counted residuals (#2639/#2652/#2638), Batch 3 the two deep ones (#2674/#2692). Mid-session the owner extended it twice — first "keep going", then "go to batch 2".

**Build beat:** `2026-08-15-the-alarm-that-cried-rest-day`
**Docs:** `docs/engines/SCORING.md` + `docs/engines/CHARACTER.md` (17 line citations re-derived from the AST, both `Verified:` stamps rewritten) · `docs/alarm_citations.json` (+`coherence-overall`, 2 stale notes re-measured) · `docs/INCIDENT_LOG.md` (+1 row) · `mypy.ini` (tranche-1 record)
**Decisions:** none needed — the session applied existing contracts (ADR-104 behavioural absence, ADR-105 deterministic-before-LLM, ADR-099 filing/closure, #2326 behavioural-never-pages, #1665 never-raise-a-baseline). The two genuinely governance-shaped calls — whether to retire an LLM finding class, and whether to reword the home page — were put to Matthew rather than decided unilaterally.
**Main:** red at close — decoded, and both causes are already fixed on `main`. The newest COMPLETED CI/CD run is `564c1041` (FAILURE), which carries BOTH self-inflicted reds of this session: its `Deploy` was the stale gate I rejected, and its `test / Unit Tests` failed on the disable-list guard that pinned membership — fixed in #2749, merged as `8905a9249`. Two newer runs are in flight and neither had completed at close: the owner-approved `deploy_all` at `1407b0e4` (run `31916736140`) already shows **Deploy ✅ and Smoke ✅**, and `8905a9249`'s own run was still building. Three stale gated runs were REJECTED with reasons, never left waiting — one of them (`31915499337`, sha `f63395bf`) was pinned to the very sha carrying the module-size regression, so approving it would have deployed the bug.
**Stash/hooks:** hook freshness 🟢. `git stash list` empty at close — but see gotcha 4: a `git stash push -- docs/` silently created nothing this session and a doc edit was lost to it.
**Closures:** 3 commented with live evidence — #2736, #2738, #2746. Five carry an honest `partial` with unmet boxes named: #2735, #2741, #2670, #2638, #2639.
**Incidents:** 1 row — a module-size regression merged past a pre-merge gate that had caught it, because my own wait loop read "no checks reported" as "all checks green".
**Backlog:** Now live at 16 (well above the 3-actionable floor); no stale `Later` issues; 6 filed this session (#2735, #2736, #2738, #2740, #2741, #2746), 2 of them fixed at the wrap gate for ADR-099 violations I introduced (a 6-box acceptance list, an unsanctioned `**reader**` audience).
**Alarms:** 7 red, all cited; none red >14d without a filed issue. `coherence-overall` and `qa-smoke-failures` have their **conditions** fixed but not their **alarms** — both are `Maximum` over rolling 24h windows.
**CI warnings:** unverified at close — `check_ci_warnings.py` reads the latest *green* completed main run, and the run at HEAD was still deploying. Nothing was left untriaged; there was simply no green run yet to read.

---

## What shipped — 9 PRs, all merged

| PR | Issue | What |
|---|---|---|
| #2737 | #2735, #2736 | a correct rest state is not an outage; 0 checks is not green |
| #2739 | #2738 | a coach that dates its reading is not contradicting the cockpit |
| #2742 | — | alarm citations: +`coherence-overall`, two stale notes re-measured |
| #2743 | #2741 | a blocking alarm's FAIL boundary is not a coin flip |
| #2744 | #2692 | CI measures WHICH tests are slow, not just that the suite is |
| #2745 | #2638 | mypy `return-value` enabled — 32 sites, zero behaviour change |
| #2747 | #2638 | character_engine back to its 2117 baseline — **I broke it** |
| #2748 | #2746 | a step named "Deterministic verdict (gating, free)" could not fail |
| #2749 | #2638 | the disable-list guard pinned membership, so it failed on progress |

**Deployed** per-function: `life-platform-coherence-sentinel`, `life-platform-qa-smoke` (×2). The four-stack owner `cdk deploy` had already landed — `check_deploy_drift.py` reads clean on all four.

## The through-line

Last session's finding was that four defects sat inside the instruments. This session went one level down: **the instruments were mostly fine — the harm came from measurements that returned a clean number while measuring nothing.**

- `coherence-overall` fired on a **correct rest state**. `macrofactor` is `behavioral: True, posture: load-bearing`, and #2326 (2026-08-09) is explicit that such a source must never page, "because that pages on a correct rest state" — it even cites this same source going dark 45 days before. The sentinel had no notion of `behavioral` at all: `grep -n 'behavioral'` returned **zero hits** across both its modules. The owner's one-line correction — *"I haven't logged anything in macrofactor so it's probably not a technical issue"* — turned a 52-day "outage" investigation into the session's best finding.
- `computed_coherence` reported `ok / "0 computed metrics agree"` on **11 of 11 retained days**. Its adapter read `score`/`grade`; the record has stored `total_score`/`letter_grade` since the OLDEST row in the partition (2023-07-23). It had never executed a single check. All three tests stubbed the broken adapter with `lambda: []` — its own broken return value.
- A step named **"Deterministic verdict (gating, free)"** could not fail. Piped into `tee`, no `pipefail`, last command a `head`. Same bug `ci-test.yml` already fixed and documents beside its coverage gate.
- And my own: a wait loop that read "no checks reported" as "all checks passed", which merged a PR whose pre-merge lane was red.

**Every one is the same shape** — a number arrived, it looked clean, and it described nothing.

## Where the measurement overturned me

Recorded because in both cases the confident answer was wrong and only re-measuring caught it:

- **#2741** — I filed it recommending we RETIRE the reader-truth `temporal_contradiction` class per the #1922/#2613 precedent. Then measured: **2 of 8 runs** on byte-identical content, two severities, two rationales. Those precedents retired classes that were *persistent* (3/3, 4/5); a 2/8 class is flaky, and retiring it would delete real coverage to fix a coin flip. Recommendation withdrawn **on the issue**, and the shipped fix is confirm-before-FAIL instead.
- **A 0/5 that was nearly a false all-clear.** My N=5 harness returned zero findings — a clean, plausible "the fix works". Running the real Lambda as a control produced `failed=1` at 22:16 and `failed=0` at 22:40. Without the control I'd have reported success.
- **#2638** — `mypy.ini` predicted "behavior-adjacent surgery on the scoring path". All 32 were annotations under-describing already-correct code. `load_character_config` looked like a latent `AttributeError` until I read the callers: they already do `if not config: raise RuntimeError(...)`, with a test pinning it.

## Gotchas — read these before the next session

1. **`grep -c` on `gh pr checks` cannot tell "all green" from "no checks yet".** `gh pr checks` prints `no checks reported on the '<branch>' branch` while checks re-register after a push; `grep -cE "fail|pending"` returns **0** for that too. My wait loop broke on it and merged #2745 with a FAILING pre-merge lane. Use a rollup assertion instead: **`total_checks > 0 AND 0 not-green`** — an empty list is NOT READY, never READY.
2. **A `-k` filter narrower than your change is not a test run.** Twice tonight. `-k "mypy_clean"` does not match `test_mypy_disable_cost_2638.py`; `-k "gate_census"` did not match the module-size guard. Both escaped to main. The honest fix is running the full lane before merging, not another gate.
3. **`mypy_disable_cost.py` names TWO places to update when enabling a code; there are THREE.** `mypy.ini`, `GLOBAL_DISABLE_BASELINE`, **and** `test_mypy_disable_cost_2638.py`'s recorded set. That third one pinned membership as a literal and reddened main the moment the tranche it guards made progress — now a ratchet (`declared <= _ORIGINAL_DISABLED`).
4. **`git stash push -- <path>` can silently create nothing, and `stash pop` then says "No stash entries found".** I lost a hand-written `INCIDENT_LOG.md` row that way mid-wrap and had to rewrite it. If you stash before a checkout, verify with `git stash list` **before** switching branches.
5. **`||` is not a pipe.** My first swallow-sweep regex matched `|| cat` and reported `ci-cd.yml`'s smoke and canary steps as unable to fail. Both are fine — each ends on an unpiped `smoke_oracle_decision.py`. I nearly filed "the deploy smoke test cannot fail". Use `(?<!\|)\|(?!\|)`; pinned by a test.
6. **A gate whose title says "Guard the SET" can still pin an instance.** Two examples tonight: the disable-list membership assert, and my own first #2746 guard, which selected on `_GATE_VERB` — and `_GATE_VERB` didn't match `*_eval.py`, so it could not have caught the bug it was written for. Its meta-test caught that. **Write the meta-test.**
7. **"The condition is fixed" and "the alarm returned to OK" are different claims,** and on this board the gap is structural: `coherence-overall` and both `qa-smoke-*` alarms are `Maximum` over a **rolling 24h** window. A fresh `0.0` cannot pull a maximum down until the old datapoint ages out. No deploy shortens that.
8. **A stale gated run must be REJECTED, and tonight one of them proved why:** run `31915499337` was pinned to `f63395bf` — the sha carrying the module-size regression that the very next commit fixed. Approving it would have deployed the bug.

## Residual queue / next picks

- **#2735** — `partial`, 4 of 6. The two unmet boxes are the CloudWatch transition (earliest ~2026-08-16 18:45Z, no deploy needed) and the planted OK→ALARM proof, which the owner chose to run next session against a genuinely-OK baseline.
- **#2670** — `partial`. `FailCount` reached **0** live; the alarm still cannot clear until the day's earlier `1`s age out. The one alarmed WarnCount survivor is `character:receipt_replay`, self-clearing by its own message.
- **#2741** — `partial`. Confirm-before-FAIL is deployed but the confirmation path has **never run in production** (it only fires on a `high`, ~2 nights in 8). Needs a real demotion observed.
- **#2638** — `partial`. Tranche 1 of 4 landed; `assignment` (285), `arg-type` (60), `operator` (38) remain, measured and itemised in `mypy.ini`.
- **#2639** — `partial`. Box 2 adjudicated: the census's false-negative rate on its 38-step residual is **1–2 of 38**, and the one it missed was #2746. Boxes 1 and 3 unchanged.
- **#2652** — untouched this session; its 69-route residual is still counted and named.
- **#2740** — the named residual of #2738: a dated citation is exempt from the currency check but verified by nothing. Deliberately `Later`; acceptance box 1 is "measure whether dated citations are common enough to be worth the machinery".
- **#2674** — still needs real browser measurement + before/after screenshots; not started.
- **#2692** — mechanism shipped (`--durations=25`), measurement lands on the next main run. Nobody has read it yet.
- **#2734** — not-work — a budget decision only Matthew can make; the alarm is cited and correct.
- **#2642, #2643** — not-work — excluded by the brief (destructive S3 / data write).
- **#2468** — not-work — `model:fable`, owner-run `cdk deploy`; drift currently reads clean.
- **#2683, #2680, #1221** — not-work — `gate:owner` / CloudFront-side, excluded.
- not-work — re-run `python3 scripts/check_ci_warnings.py` once run `31916736140` completes green; it could not read a warning board this session because there was no green run yet.
