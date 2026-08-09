# HANDOVER — The overnight burn: 46 PRs merged, 49 issues closed (95→60), the census armed, the reset handed as a runbook — 2026-08-09 ~07:58Z → ~17:4xZ

> Instruction thread: *the planned overnight burn (`~/.claude/plans/kind-moseying-crayon.md`,
> owner-approved): fully autonomous, waves of 4 worktree-implementers, Now→Next→Later by
> stored rank, driver verifies everything, cycle-13 reset time-boxed to the final 75 min with
> the runbook as the sanctioned fallback, wrap deadline T+7.5h = 15:28Z. The deadline was
> missed — see the honest-miss paragraph — but the burn itself over-delivered.*

**Main:** red → recovering at the wrap commit — decode: TWO union reds surfaced by the
full-suite dispatches (the pillar_absence×todoist contract, fixed #2463; then the stale
stack manifest from #2406/#2436's derived facets, regenerated `5f164b5d4`); the
deploy-of-record dispatch (take 3, run 31327743460) was in flight with a self-approving
gate waiter when this wrap committed — **#2465 carries its green verification as box 1**.
**Docs:** ADR-133 August amendment + ADR-148 2026-08-09 amendment + ADR-152 (one TDEE) in
DECISIONS.md; SCHEMA.md chronicle sk-invariant; PROPORTIONALITY 3 rows + re-stamp (#2380);
CONVENTIONS §1a (bundle fingerprint, via #2408); wrap.md gained the ledger gate line.
**Decisions:** ADR-152 filed (one TDEE definition); ADR-133 amended (Aug $115/$135,
auto-revert 09-01, Budgets backstop stays $85); ADR-148 amended (strict=false re-decided on
the measured wave; merge-ref lane = the named mechanism).
**Build beat:** `2026-08-09-the-overnight-burn` (46 merged+deploying PRs; see beats.json).
**Incidents:** 2 rows added — (1) the #2052-class phantom deploy wedge, ~09:51→16:17Z:
the merge storm's survivor ci-cd run sat "pending, 0 jobs" (concurrency evaluates before
the environment rule), the wedge-watch failed loudly hourly, recovery via
`check_deploy_wedge.py --recover`; compounded by TWO session harness stalls (~10:00–12:16
and ~12:45–16:00) during which the driver could not act; (2) main unit-tests red from the
first full-union suite run: #2438's new `pillar_absence` × the derived todoist reader
contract — the PR-lane-invisible union class, fixed forward by #2463.
**Closures:** 49 issues closed by this session, every one with an ADR-099 verdict comment
(see the list in the session ledger; verdicts include honest partials/not-realized where
live evidence was missing).
**Backlog:** 95 → **60 open** (16 epics + ~8 gate:owner inside that). Now/Next workable is
effectively drained; what remains is Later + the census-filed gate stories + fable-only.
**Alarms:** cited per the registry at last check; qa-smoke-warnings expected to go quiet
(chronic reclassification #2378) and receipt_replay expected to HEAL at the cycle-13 reset.
**CI warnings:** triage at next green main (this wrap's dispatch); nothing outstanding from
the last green run.
**Stash/hooks:** clean (stash empty; hooks 🟢 at postflight).

---

## What shipped (46 PRs, all merged; deploying via the final dispatch)

**The burn, by family:**
- **Budget/governance (driver):** #2406 the August ceiling window $115/$135 + the
  `tier_crossings` forecast in the breakdown/brief (closes #2381); ADR-148 amendment
  (#2371); PROPORTIONALITY refresh (#2380); ratchet banked 80.20 (#2455/#2374).
- **The #2390 grounding program — the census armed and then USED:** the three-seam
  invoke-site census (#2432; discovered `call_anthropic_api` as seam 3, corrected the
  issue's own premise), 11 findings filed (#2418–#2428,#2430), then SEVEN of them fixed
  the same session: ensemble digest (#2444), partner email + its second seam deleted
  (#2445), hypothesis prose (#2446), field notes (#2450), candidates-private (#2451),
  anomaly conjecture fence (#2453), reading pair (#2458), analyzer 4 paths incl. the
  Mode-B re-gate (#2457), compression path (#2459). The registry's UNGATED tracked table
  is down to a handful, each still filed.
- **Honest-absence/reader-truth:** date-carrying LogAvailability (#2413), family panel +
  the cockpit string-bind bug (#2438), weekly-digest absence line (#2448), protein null
  (#2433), meal columns rebound + the truthy-[] fallback bug (#2434), deficit copy
  (#2456), tensions dated (#2417), observatory Pacific day (#2411), md tokens (#2449).
- **Structure/guards:** bundle fingerprint + ancestry refusal (#2408), PII log guard
  (#2407), SES declared-rule + a revoked mislabeled exemption (#2431), cache-tier posture
  (#2429), null-coercion widened — all 21 hits real, fixed (#2452), roster registry ×17
  copies (#2454), cast guard over prompt literals — 8 live offender files incl. phantom
  chronicle interviewees (#2462), wallclock-bomb gate (#2461), strict xfails (#2441),
  guard coupling (#2439), chronicle sk-invariant (#2435), qa-warnings chronic (#2409 +
  the build_report_html extraction closing #2335), health tally axis (#2447), recall
  link sensor+repair (#2437), brief idempotency (#2440), lead-in word-boundary (#2442),
  weather 4 cells (#2436), find_days operators (#2415), workout uid round-trip (#2412),
  intelligence-quality denominator (#2405), summary bar (#2416), meal_responses retired
  (#2443), union-red fix (#2463).
- **Reconciles without PRs:** #1383 closed as shipped-by-#2363; #2427 keep-both decision;
  #2402 proposals doc committed (`docs/design/TEXTING_REGISTERS_PROPOSAL.md` — taste
  session pending, ADR-106).

## The deploy story (read this before touching CI)

The merge storm (~20 merges/hour) meant EVERY ci-cd Deploy was superseded — nothing
deployed all night, by design safe but then the survivor run hit the **#2052 phantom
wedge** (run-level pending forever, `pending_deployments` empty, the approval watcher
correctly never fires because the run never reaches the gate). The wedge-watch workflow
caught it (hourly failures + a remediation urgent_alarm). Recovery is ONE command:
`python3 scripts/check_deploy_wedge.py --recover` (cancel + `deploy_all=true` dispatch).
The first recovery dispatch then FAILED unit tests on the union red (see Incidents),
fixed by #2463. **The deploy of record is dispatch take 3 (run 31327743460)** — takes 1–2 died to the
phantom wedge and the two union reds above; approve via `deploy/approve_deployment.sh <run>`
if its gate is still waiting when you read this. After green: run
`bash /private/tmp/claude-501/-Users-matthewwalker-Documents-Claude-life-platform/e3618407-6df2-4ec3-b0a3-a6c7b76af781/scratchpad/post_deploy_verify.sh`
(bundle symbol + ancestry postflight + the #2366 recall repair + live spot-checks).

## The honest miss

The wrap deadline (15:28Z) was missed by ~2.5h and **Phase 3 (the cycle-13 reset) was NOT
applied** — not by choice: the session harness stalled twice (~10:00–12:16Z and
~12:45–16:00Z, ~5.5h total dead time) spanning exactly the reset window, while the deploy
sat wedged. Per the owner's own standing instruction ("the fallback is a prepared runbook
I run after my morning weigh-in, never a rushed --apply"), the reset is handed over as the
prepared runbook below, dry-run-verified overnight. Applying it at 10am PDT with main
mid-recovery would have been the rushed apply the instruction forbids.

## CYCLE-13 RESET — the runbook (owner runs after weigh-in) — #2465

Dry-run verified at 09:05Z: census preflight 93 pk families all classify (the new CHAT#
rows are covered — the `COACH#<coach>` "all"-mode wipe archives them with cycle=12,
restorable); override 321.6 resolves; keep-chronicle cross-check green; ~98 prereg bets
void; ~94 items tag. The reset-path hardenings (#2440 idempotent brief, #2442 lead-in
slicer, #2435 sk-invariant check) all merged first. Full runbook with post-checks:
`/private/tmp/claude-501/-Users-matthewwalker-Documents-Claude-life-platform/e3618407-6df2-4ec3-b0a3-a6c7b76af781/scratchpad/cycle13_runbook.md`
(also mirrored in issue #2465). The command (after the weigh-in has synced, drop the
override; before it, keep it):
```bash
git pull --ff-only
python3 deploy/restart_pipeline.py --genesis 2026-08-09 --keep-chronicle DATE#2026-08-02   # review dry-run
python3 deploy/restart_pipeline.py --genesis 2026-08-09 --keep-chronicle DATE#2026-08-02 --apply
```

## Morning owner list

1. **Run the cycle-13 reset** (runbook above — #2465) after the weigh-in syncs.
2. Create explorer+board bots (BotFather limit expired) → `python3 setup/setup_telegram_bots.py`
   → `python3 setup/register_telegram_webhooks.py --url https://hvqippdqcrbngivi5qifoaqmd40owrxu.lambda-url.us-west-2.on.aws` — not-work — owner phone actions (epic #2363).
3. Say "hi" to sleep/mind/physical bots + ENTER-keep re-run — not-work — owner phone actions.
4. MacroFactor export — #2326 (47 days quiet; Webb has nothing to say about food until it lands).
5. #2402 taste session: `docs/design/TEXTING_REGISTERS_PROPOSAL.md` (4-item checklist at the end).
6. Cycle-12 CHAT# rows (yesterday's first coach conversations) archive at the reset —
   say the word to restore/reclassify — not-work — owner preference call.

## Gotchas (the ones that will recur)

- **`agent_commit.sh` can print a black/ruff ❌ and still EXIT 0** — read its output, never
  trust the exit code in a `&&` chain (cost one worktree of redone edits tonight). #2464.
- **The PR fast lane NOW RUNS the mypy clean-set gate AND the size baselines against the
  MERGE REF** — the memory `reference_pr_checks_lack_mypy_gate` is superseded (rewritten);
  brief implementers to annotate new dicts and budget lines on at-baseline files.
- **Merge-storm supersession means NOTHING deploys until a quiesce** — plan explicit
  quiesce windows; and the quiesce's survivor run can phantom-wedge (#2052) — the
  wedge-watch + `check_deploy_wedge.py --recover` is the loop.
- **The union class is real and the lane can't see all of it**: a new module × a derived
  contract scan neither PR executed (tonight: pillar_absence × the todoist reader scan)
  reds only the full suite. The first full-union run after a storm is the moment to watch.
- **Five size-baseline catches in one night** — the ratchet earns its ledger row; the
  legitimate escapes used: compress comments, extract a module (build_report_html,
  weekly-digest absence query, summarizer support), or a CONSIDERED raise with the reason
  in-code (hypothesis gate, registry-import conversions).
- **BotFather-style external limits and `gh pr view mergeable=UNKNOWN`** both just need
  patience loops — poll until recompute, don't force.

## Residual / next picks

- **Deploy-of-record dispatch green + post_deploy_verify.sh** — the one operational loose
  end this wrap leaves; steps in "The deploy story". #2465 carries it with the reset.
- **#2418** — observatory_summary registration: THE Webb-card mechanism candidate; the
  17:02Z day-honesty live check rides it (was #2390's residual acceptance box).
- **#2430** — the five partial-gate reader surfaces (podcast, reflection, memoir, eyeball,
  chronicle_personas) — the census's remaining tracked defects.
- **#2414** — the UTC-today class sweep (~15 sites) + premerge guard.
- **#2379** — qa-smoke FailCount live-confirm post-reset + the day-correspondence move.
- **#2464** — agent_commit.sh exit-code fix (filed this wrap).
- **#2326** — MacroFactor export, `gate:owner`.
- **#2402** — texting registers taste session, `gate:owner` (proposals ready).
- Remaining Later families: #2372 (premerge derivation), #2332, #2349, #2350, #2351,
  #2347, #2348, #2331, #2311-adjacent weather follow-ons — all filed, ranked, clean.
