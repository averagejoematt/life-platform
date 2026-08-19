# Handover — 2026-08-19 (afternoon/evening, ~13:28 → ~15:5x PT): the backlog drain, and three tools that reported success while doing nothing

**Session:** Opus, owner-directed (plan `moonlit-inventing-crane.md`, model ceiling Opus — no kernel
builds; **every `model:fable` issue untouchable — 36 of 110, Matthew's explicit call**). Boot was
**charter + `blast_radius.py`**, not a prose re-read. Previous wrap archived as
`HANDOVER_2026-08-18_september-base-decided.md`.

**Build beat:** `2026-08-19-tools-that-lied` — merged AND deployed (fleet deploy owner-approved, shipped 22:33–22:39Z).
**Docs:** `MONITORING.md` (alarm line ~50→103 live-measured, total ~$14→~$19/mo), `OPERATOR_GUIDE.md`
(steady state ~$25-40→~$124/mo), `RUNBOOK.md` (ceiling $85/$100→$150/$176 + recomputed tier bands),
`COST_TRACKER.md` (tier band table, AWS Budgets backstop, September decision settled), `INCIDENT_LOG.md` (+2 rows).
**Decisions:** none needed — no governance-consequential choice was made; the ceiling decision was
settled last session (ADR-133 amendment, #2895) and this session only corrected prose that still
disagreed with it. The Later-sweep dispositions are ADR-099 triage, not new policy.
**Main:** green (`f5582dd1`) — HEAD is `3772cfea` (this wrap commit), a **path-filter skip, not a
swallowed push**: it touches only `handovers/`, `CLAUDE.md`, `docs/**` and `site/**`, none of which are
in `ci-cd.yml`'s `paths:`. Its `site/**` change did fire a real **Site deploy — fully green** (deploy +
smoke + Visual/AI-QA, auto-rollback skipped), and `/version.json` reads `3772cfe` == HEAD with the beat
live at 118. The commit before it, `98d6e13d`, was a `chore(reconcile)` commit that structurally
**never earns a CI/CD run** either: reconcile pushes use `GITHUB_TOKEN`, and GitHub does not dispatch
workflows for those — verified across three samples (`98d6e13d`, `b45f590f`, `06b5bd44` → 0 runs each);
its only code change was a machine-generated `test_count` literal (15749 → 15757). Deliberately did
**not** dispatch a run for either: `site_api_common.py` is a shared module, so a dispatch would open
another fleet-deploy approval gate for a literal-only change.
**Incidents:** 2 rows added — main red 29m on an `aws_cdk` import CI does not install; a 6h22m
production-deploy wedge behind a stranded approval gate.
**Closures:** #2668, #2669, #2790, #2807, #2808, #2812, #2816, #2825, #2897, #2899, #2740, #2541, #1374
commented (#2901 auto-filed/auto-closed by the platform). **#2806 REOPENED** — see below.
**Backlog:** Now live at 10 actionable (no refill needed); Later sweep — all 22 non-fable issues
dispositioned: 3 closed, 8 promoted, 8 kept with written reasons, 3 closed via merge.
**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.
**Alarms:** 0 uncited — every alarm red >72h cites an incident row or issue.
**CI warnings:** 2 — both triaged, neither left to normalize: (1) *"LifePlatformIngestion has a Lambda
config change CI's code-deploy cannot ship"* → **this is #2806's fix**; reopened #2806 rather than
leaving it closed-but-unshipped. (2) *"Unit Tests over the 1200s budget"* — **1323s** on the run I
first read, **1313s** on re-check at wrap, so ~110–125s over on both → #2692, promoted to `Next`, and
**my earlier 937s "trend has reversed" comment withdrawn** (see below).

---

## The count, honestly

**110 → 96 open. 14 net closed.** The plan predicted ~85 and said 30 was unreachable with the fable
set frozen; ~85 was also optimistic. The floor arithmetic is unchanged: **36 `model:fable` issues**
remain untouchable, so closing every reachable issue still lands near 39.

The plan's Phase-2 premise was **wrong**, and that is most of the gap. It described `Later` as
"almost all feature stories (Counterfactual Save States, The Detective, The Replication Kit, Season
Finale, The Blind Week)" with a default expectation of *close*. Every one of those five is
`model:fable` — verified: #1414, #1398, #1391, #1380, #1415, all `fable=true`. The 22 **non-fable**
`Later` issues are **8 bugs + 5 chores + 9 stories**. Applying "default close" would have closed real
defects. I closed 3, promoted 8, and kept 8 with a written reason each.

## Phase 0 — both clocks, and the branch went the other way

Boot was **Wed 20:28Z / Wed 13:28 PDT**. Both crons had *already fired*: the chronicle at 15:00Z
(5.5h earlier), the brief at 17:00Z (3.5h earlier, well past the 17:10Z sampling bar). The hand-off
expected both to be missed. They were observable, and they were the two cheapest closures on the board.

- **#2669 closed — `realized`.** Live run `8af6dda2`, 15:00:34→15:02:45Z: **131,365 ms against a 300s
  timeout** (43.8%). Exactly ONE generation (`Calling Sonnet` ×1, `Installment received: 7681 chars`
  ×1), then `Installment stored: Week 1` and `[#2669] generation cached for 2026-08-18`. **131.4s
  exceeds the original 120s timeout** — that run would have died under the old config, so the defect
  was live, not theoretical.
- **#2668 closed — `realized`.** `max_tokens` 600→1500 sized against the *measured* 1754–2277 char
  truncation ceiling with the reasoning inline; failure path WARN→`[ERROR]` + a keyable
  `IC3AnalysisFailure` metric. Verified 3 consecutive days (08-17/18/19) in CloudWatch: `IC-3 analysis
  parsed clean` present on all three, **zero** truncation lines. 14/14 tests green.

## Phase 1 — the bug clusters (7 PRs merged)

Three Sonnet workers on disjoint clusters, plus my own lane. **Every worker output was verified
against its BRANCH, never its report** — that held for a fifth session, and it caught two things.

| PR | closes | what |
|---|---|---|
| #2902 | #2897 (P1) | `agent_commit.sh` no longer destroys work |
| #2903 | #2790, #2825 | two gates that could pass while inspecting nothing |
| #2904 | #2899 | the doc-facts ceiling scan's three different blind spots |
| #2905 | #2807, #2808 (#2806 reopened) | one registry for the social-channel vocabulary |
| #2906 | — (`Part of #2838`) | cost/alarm prose restated from live measurement |
| #2907 | — (red-main fix) | the `aws_cdk` import |
| #2908 | #2812, #2816 (`Part of #2815`) | the timezone cluster |

**#2897 (P1) — the tool that deleted finished writing and exited 0.** `agent_commit.sh`'s
"did the agent name this file?" test was a literal substring match, so passing the directory `docs/`
made every file under it "unnamed" and `git checkout HEAD --`-ed. Fixed two ways: directory args are
expanded via `git ls-files`, and anything still unnamed is a **REFUSAL**, not a discard. The discard
survives as explicit opt-in (`ALLOW_LITERAL_RESTORE=1`) and now writes a recovery patch first.
Mutation evidence: 3 of 4 new tests go red on the pre-fix script. The 4th passes on both **by design**
— it pins pre-existing behaviour (zsh doesn't word-split `$LIST`), stated in its docstring.

**#2899 — the issue's diagnosis was wrong, in an interesting way.** It hypothesised the gap was
markdown formatting (bold/tables/blockquotes). Reproducing each site against the real matcher first
showed bold was never the problem — there were **three different mechanisms**:

| site | regex found `$85`? | actual cause |
|---|---|---|
| `ARCHITECTURE.md:89` | **yes** | exemption was per-**LINE**; "raised from $75" excused the stale *current* $85 beside it |
| `INFRASTRUCTURE.md:16` | **no** | genuine pattern gap — no trigger word within 20 chars |
| `COST_TRACKER.md:7` | would have flagged | the file is on the gate's own `EXEMPT_FILES` skip list |

Fixed per mechanism: per-**amount** exemption (history is a prefix phenomenon), `all-in` added to the
vocabulary, a targeted ceiling scan for the exempt ledger, and `BUDGET_OK` now **parsed from
`cost_governor_lambda.py`** (never imported — the CI lint job has no boto3) including the dated
window, allowed only while in effect. **The widened gate immediately found 4 live stale sites that
survived two previous ceiling sweeps** (#2836, #2895). Mutation: **18 of 20** fail on the old script.

**Deliberately left open and named in the PR:** `$85 base` in current-tense prose is still unmatched.
Widening to `base|surge` flags 15 sites, most of them legitimate historical analysis in the spend
ledger ("June peaked at 94% of the $85 base"). A narrow trusted gate beats a loud ignored one.

**#2825 — the phantom.** `ALL_LAMBDAS` was frozen at 40 of ~106 and contained `weather_handler.py`,
which exists nowhere in the tree; its W1/W2 checks `pytest.skip()`'d **silently**. Now AST-derived
from CDK: **40 → 103**, phantom resolved to the real `weather_lambda.py`, and a missing file
`pytest.fail()`s instead of skipping. The 19 newly-surfaced W1 gaps were **ratcheted** as a dated
shrink-only ledger, not mass-fixed and not mass-exempted.

## What verification caught that reports did not

**Worker A red-mained the module-size ratchet.** Its branch passed everything it ran; the structural
set caught `source_registry.py` at **1216 lines over the 1200 hard ceiling** and `daily_brief_lambda.py`
at **2750 vs a 2737 baseline**. Sent back with the charter rule (debt only ratchets down) and an
explicit "do NOT raise either baseline". It fixed both by **extraction** — a 44-line
`source_registry_social.py` sibling — landing at 1195/2735 with the import path unchanged. Verified:
no diff to `test_module_size_guard.py`, 168/168 structural.

**Then worker A red-mained main anyway, in a way no local check could see.** Its guard test did
`import stacks.ingestion_stack` to read `SOCIAL_CHANNELS_ENV` — which pulls in `aws_cdk`, **not
installed** in the `Deploy-critical tests` or `test / Unit Tests` jobs. It fails at *collection*, so it
aborts the whole job. Green locally, red in CI, 29 minutes of red main. Fixed in #2907 by reading the
fact via `ast.parse` — the in-repo idiom — which is also the **stronger** guard: it asserts the
assignment is an `ast.Call` into `social_channel_source_ids`, so a hand-typed literal fails on
**shape** before any value comparison. Proven both ways: passes with `aws_cdk` blocked via a
`sys.meta_path` blocker; the planted pre-fix literal produces `got a Constant`.

**Worker B did the hard thing correctly.** I had briefed it that `coach_quality_gate.py:305` must
**not** be converted — it is a genuine shared OUTPUT# frame where producer and consumer key from the
same naive clock, so converting one side desyncs the sk from its reader. It annotated it
`# utc-exempt(#2815)` with the rationale and wrote `Part of #2815`, not `Fixes`. #2815 correctly
remained OPEN after merge.

## The deploy, and merged ≠ deployed

The fleet deploy was **owner-approved** and shipped: Deploy, Smoke, Post-deploy integration checks and
Visual + AI-vision QA all green. Lambdas redeployed 22:33–22:39Z.

**But `SOCIAL_CHANNELS` is still `youtube,bluesky,mastodon` on the live enrichment lambda** — because
it is a **CDK-owned env var**, and a code deploy cannot ship one. `social-enrichment` was redeployed at
22:39:58Z **and the defect survived**. CI said so independently, via the `Plan deployments` warning
naming the exact command. So:

- **#2806 REOPENED** — its stated outcome is not true in production. One command closes it.
- **#2808** is genuinely `realized` — daily-brief has **no** `SOCIAL_CHANNELS` env, which is precisely
  the condition under which its new registry fallback fires.
- **#2807** `realized` for the display layer (site-api redeployed 22:38:01Z).

## Two stranded deploy gates, and the platform noticed before I did

`check_main_green.py` at boot found run `32263995111` (sha `68022d1f`) **waiting 6h22m** at the
production gate, freezing every later CI/CD run behind it (`cancel-in-progress: false`). Its sha was
already an ancestor of main and its only red was `test_gate_steps_cannot_swallow_status_2746` — the
guard whose defect **#2900 had already fixed on a later commit**. **Rejected**, not approved, per
`reject_deployment.sh`'s own rule. A second gate of the same shape (`32300377555`, 9 commits behind,
0-Lambda plan) rejected later.

The detector worked: the remediation agent **auto-filed #2901** ("CI/CD deploy wedge — production
deploys are stalled") at 16:54:42Z, 2h28m into the wedge, and it **auto-closed 4 minutes after** the
rejection cleared it.

## A measurement I made this session and then withdrew

Sweeping `Later`, I read #2692 (Unit Tests wall-clock budget), measured **937s against the 1200s
budget** from run `68022d1f`, and concluded the trend had reversed — keeping it on `Later` on that
basis. The wrap's own `check_ci_warnings.py`, on the next green main run, reported **1323s, 123s over
budget**. I withdrew the "trend has reversed" line on the issue, promoted it to `Next`, and flagged my
own contribution: this session merged ~45 new tests, and #2825's widening of `ALL_LAMBDAS` from 40 to
103 multiplies four parametrised test functions. One good reading between two bad ones is not a
reversal.

## Residual / next picks

- **#2806** — run `bash deploy/cdk_deploy.sh LifePlatformIngestion`, then verify the env reads
  `bluesky,instagram,mastodon,tiktok,x,youtube`. The only thing between this and closed.
- **#2815** — the OUTPUT# frame conversion as a whole (`coach_quality_gate.py:305` +
  `coach_state_updater.py` + `inter_coach_dialogue_lambda.py`); the annotated exemption is correct but
  temporary.
- **#2838** — `partial`: prose corrected, but the *mechanism* (reconcile re-stamping `Verified:` lines
  it never verified) is untouched, and by this issue's own logic the docs now look freshly verified
  again. Narrowed to the stamping mechanism.
- **#2692** — profile the slow tests before anyone touches the 1200s number.
- **#2899 follow-on** — `$85 base` phrasing still unmatched; needs a ledger-history exemption
  discipline before the vocabulary can widen.
- **#2809** (promoted) — Tier-2 withings fields reachable through the MCP row dumpers, and
  `SCHEMA.md:327` records the opposite as verified.
- **#2670 box 2 / #2741 box 5** — not attempted this session; `qa-smoke` `FailCount` unverified.
- **The 36 `model:fable` issues** — *not-work — owner decision: they are the only thing between ~39
  and 30, and cannot move from an Opus session under the standing rule. Needs a Fable session or a
  relabel pass.*
- **A Withings weigh-in** — *not-work — owner action; newest row is still `DATE#2026-08-16`,
  `carried_from_cycle: 13`.*
