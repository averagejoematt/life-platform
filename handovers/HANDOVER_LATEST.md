# Handover — 2026-08-18 (evening, ~19:26 → ~22:10 PT): the September base got decided, and the deselection gap bit a third time

**Session:** Opus, owner-directed (plan `three-observations-and-a-number.md`, model ceiling Opus —
no kernel builds; #2846/#2847 stay Fable-sequenced, every `model:fable` issue skipped). Boot was
**charter + `blast_radius.py`**, not a prose re-read. Fourth Opus session of 2026-08-18; the previous
wrap is archived as `HANDOVER_2026-08-18_wrong-day-wrong-gauge.md`.

**Build beat:** `2026-08-18-september-base` — the permanent ceiling decision, merged and deployed.
**Docs:** ADR-133 amendment + index row; 13 docs swept (`ARCHITECTURE`, `COST_TRACKER`,
`INFRASTRUCTURE`, `MONITORING`, `ONBOARDING`, `OPERATOR_GUIDE`, `QUICKSTART`, `README` ×2,
`RUNBOOK`, `SECURITY`, `DIARY_STUDIO_KIT`, `COACH_HUMANITY_ROADMAP`); `INCIDENT_LOG` +1 row.
**Decisions:** ADR-133 amendment filed (2026-08-18, #2836 — the September base, permanent).
**Main:** green (`b69eab778`) — verified via `check_main_green.py` after a 1h02m red, see Incidents.
The wrap commit `4c3f7028` itself earns **no CI/CD run, correctly**: its four paths (`CLAUDE.md`,
`docs/INCIDENT_LOG.md`, `handovers/`, `site/story/build/beats.json`) are all outside `ci-cd.yml`'s
`paths:` filter — the documented path-filter skip, **not** the swallowed-push shape (#2762). It did
fire a real **Site deploy**, which went green on Deploy + Smoke with rollback skipped; the beat is
live (117 beats, `/version.json` build `4c3f702` == HEAD).
**Incidents:** 1 row added — main red 1h02m on the $150 ceiling merge (four deselected stale-literal
test failures; deploy gate rejected, not approved; fixed by #2896).
**Alarms:** clean — every alarm red >72h cites an issue/incident row; none red >14d uncited.
**CI warnings:** 1 — `Unit Tests 1233s vs the 1200s budget`. **Deliberate no-action this session:**
this is #2692 verbatim, already filed, with PR #2894 open against its real cause (the deselection
gap, not the duration). No new issue; raising the budget is exactly what #2692 forbids.
**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.
**Backlog:** Now live at 12 actionable; no stale `Later` issues; hygiene OK across 109 open issues.
**Closures:** #2876, #2836 commented with the ADR-099 two-line verdict.

---

## The clock branch fired again — third session running, third different shape

Boot printed both clocks, as instructed:

```
UTC:   2026-08-19 02:26:45 Wednesday
LOCAL: 2026-08-18 19:26:45 Tuesday PDT
```

It **was** Wednesday in UTC — but **12h33m before** the 15:00Z chronicle and **14h33m before** the
17:00Z brief. Last session sat 17 minutes *after* rollover and read "Wednesday" as live; this one sat
2h09m after rollover and was still on the wrong side of both crons. Same trap, different geometry.

**All three Phase-0 boxes were unobservable again** (#2669, #2668, #2741 box 5). Said so and moved
on rather than hunting. The three alarm predictions were re-verified live and all held exactly:
`ingest-auth-unhealthy-whoop` (ALARM since 08-17 05:01 PT), `qa-smoke-failures` (08-17 11:32 PT),
`qa-smoke-warnings` (since 2026-07-18) — all `Period 86400`, unchanged.

---

## What shipped

| PR | What | State |
|---|---|---|
| **#2885** | #2670 — chronic-ize the recurring config/engine drift warn | merged `2b13c708`, qa-smoke **deployed** |
| **#2882** | #2876 — single dispatch exit point; EMF dimensions → properties | merged `cd9652a3`, site-api + Monitoring CDK **deployed** |
| **#2895** | #2836 — **the September base, $85 → $150 / surge $176** | merged `71607f78`, cost-governor + Core CDK + site-api **deployed** |
| **#2896** | four ceiling literals the pre-merge lane deselected | merged `b69eab77`, main green |
| #2887 | #2883 box 2 — drift ratio scoped to AI-only, unbuffered (2.445 → 1.366) | **open** (Sonnet worker) |
| #2894 | #2692 — pre-merge deselection made visible + guards pulled in | **open** (Sonnet worker) |

### The owner decisions, all three answered

1. **September base = $150** (surge $176). Permanent, not a fourth dated window.
2. **Merge + deploy #2882** — done, both deploys.
3. **Merge + deploy #2885** — done.

The $150 was derived from **measured steady state, not the projection**: $4.12/day, sd $0.66, n=6 →
~$124/mo, 95% CI $108–139. Bands verified by *executing* `_tier_for`, not by arithmetic: at $150 they
trip at $110.00 / $130.00 / $146.00. **Nothing changes tonight** — the August window ($200/$235) is
still in effect and untouched; the new pair takes over on 2026-09-01 with no deploy. Verified live in
the governor's own payload after deploying:

```json
"ceiling_window": { "start": "2026-08-01", "end_exclusive": "2026-09-01",
  "reverts_to_base_ceiling": 150.0, "reverts_to_surge_ceiling": 176.0 }
```

AWS Budgets `life-platform-monthly-75` now reads **150.0**. `cdk diff` on Core showed exactly one
changed line (`85 → 150`) and nothing else before deploying.

### #2670 box 1 — realized, with a conserved-count proof

`LifePlatform/QaSmoke`, the exact metrics the alarms read:

| metric | 14:03 PT (pre-deploy) | 19:48 PT (post-deploy) |
|---|---|---|
| `WarnCount` | 1.0 | **0.0** |
| `ChronicWarnCount` | 7.0 | **8.0** |
| `FailCount` | 0.0 | **1.0** |

7+1 → 8+0. The count is **conserved**, which is what makes this a reclassification rather than a
suppression. Box 2 (the planted OK→ALARM transition) stays open.

---

## Three findings worth more than the merges

### 1. `agent_commit.sh` silently destroyed ~13 files of finished work (#2897, P1)

`ALLOW_DOC_LITERALS=1` was set and honoured. The damage came from the *next* block: the
"did the agent name this file?" check is a **literal substring match** on the joined path list, so
passing the directory `docs/` does not make `docs/ARCHITECTURE.md` named — and every changed file
under it got `git checkout HEAD --`-ed. It printed `✅ committed 13 path(s)` and exited 0.

The entire ADR-133 amendment was gone. Replayed from context; no work was ultimately lost, but only
because the text happened to still be in the session. **Every other guard in this repo fails loudly;
this one deletes authored prose and reports success.**

Adjacent: passing the list via an unquoted `$DOCS` also misbehaves — zsh doesn't word-split unquoted
expansions, so the whole list arrives as one path. *There* the script refused correctly, which is
exactly the behaviour the directory case should have.

### 2. Green PR ≠ green main, for the third consecutive session (#2692)

#2895 was **9/9 green** and had deselected **~11,482 tests**. Four of them failed on push. The CI
warning that same run says `Unit Tests 1233s vs 1200s` — the duration is the symptom everyone looks
at; the deselection is the defect. Worker PR #2894 measures it independently at 11,519 → 11,429 and
adds a job-summary line reporting what the fast lane did not run.

My own process miss compounded it: the broad grep-driven sweep I ran before merging **silently failed
on the zsh quirk above**, and I proceeded on a narrower hand-listed set instead of re-running it. The
fix PR ran the grep properly — 12 files, 633 passed.

### 3. The ceiling is hand-maintained in 5 code sites + ~18 prose sites (#2898, #2899)

Moving one number was a 26-file sweep. Charter standing-rule-1 violation with no dated exemption.
Worse, `check_doc_facts` **misses** three live statements it should catch (`ARCHITECTURE.md:89`,
`INFRASTRUCTURE.md:16`, `COST_TRACKER.md:7` — all bold/table/blockquote forms) while flagging
`ARCHITECTURE.md:430` in the same file. Evidence it matters: `coach_sim_scoreboard.py` and
`COACH_HUMANITY_ROADMAP.md` still said the August window was **$115** when #2734 raised it to **$200**
twelve days earlier, and two guards ran over them the whole time.

#2896 converted one assertion to derive from `MONTHLY_CEILING` — the pattern to replicate.

---

## Gotchas hit

- **#2885 was a DRAFT.** `gh pr view --json state` returns `OPEN` for drafts; only the merge attempt
  revealed it (`Pull Request is still a draft`). Check `isDraft`, not `state`.
- **A negated closing keyword was avoided by inspection, not luck.** #2885's body ended `Fixes #2670`
  — which would have closed an issue whose acceptance needs a live observation no merge can satisfy.
  Rewrote to `Part of #2670` before merging; asserted `state=OPEN` after. The scan for
  keyword-adjacent refs (`(clos|fix|resolv)\w*[\s:]+#\d+`) is worth keeping.
- **A genuine reader-truth FAIL exists on the live site.** qa-smoke's post-deploy run returned
  `failed: 1` — `temporal_contradiction·539c6d`: Home promises "Every week gets written down. A
  chronicle, a podcast" while cycle 14 is on **Day 2** and no chronicle exists. This **overturns the
  plan's prediction**: `qa-smoke-failures` will not clear at ~14:16Z; earliest OK moves to ~08-19
  19:48 PT and only if no further FAIL lands.
- **The `/aws/lambda/life-platform-qa-smoke` dry-run works** (`[DRY-RUN] SES send suppressed`) but the
  handler still returns `"emailed": true` and logs "email sent". Small ADR-104 honesty defect.
- **CloudFront cached my verification.** Three `curl`s to `/api/vitals` returned 200 without ever
  reaching the Lambda; only a cache-buster produced a real emission to check.
- **A false finding I nearly filed:** the deploy plan logs `⚡ Shared module changed → fleet deploy`
  then prints `Deploy plan: 1 Lambda(s)`. That is **not** a bug — `FLEET_CHANGED` is honoured through
  `deploy_fleet.sh` on a separate path from the deploy matrix. Read the workflow before filing.
- **Two docs-only commits by `integration@local` landed on main mid-session** (19:41, 19:42) carrying
  a `/cost-diligence` ritual I did not create — almost certainly a concurrent session. Docs-only, no
  interference; flagged rather than chased.
- `tests/test_gate_census_2578.py` fails to collect standalone without `scripts/` on `PYTHONPATH`.
  Reproduced on untouched `main` and independently by both Sonnet workers — pre-existing, environmental.

---

## Residual / next picks

- **#2669** — the Wednesday chronicle box. Unobservable until **2026-08-26** (15:00Z, weekly). #2669
- **#2668** — the 3-of-3 daily-brief close; next observable run 08-19 17:10Z+. #2668
- **#2741 box 5** — blocked on `FailCount` returning to 0, which the Day-2 Home-copy contradiction
  prevents. #2741
- **#2670 box 2** — still needs a *planted* failure driving OK→ALARM. #2670
- **The Day-2 temporal contradiction on Home** — genuine, live, and now the thing holding
  `qa-smoke-failures` red. #2741
- **Merge #2887** (drift ratio, #2883 box 2) — needs a rebase; it collides with #2895 in
  `test_cost_governor.py`. Implies a `cost-governor` deploy. #2883
- **Merge #2894** (#2692 deselection) — CI-tooling only, nothing to deploy. #2692
- **#2897 / #2898 / #2899** — the three filed tonight; #2897 is P1. #2897
- **A Withings weigh-in** — newest row still `DATE#2026-08-16`. not-work — only Matthew can do it.
- **~100 accumulated git worktrees**, most prunable. not-work — pre-existing housekeeping, owner's call.
