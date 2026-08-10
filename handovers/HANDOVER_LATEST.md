# HANDOVER — The morning the coaches couldn't hear him — 2026-08-10 ~14:35Z → ~16:0xZ

> Instruction thread: *the plan file `~/.claude/plans/proud-fluttering-journal.md` (all owner decisions pre-resolved: fully autonomous, coach cluster at full speed, direct-script deploy path if the owner's cdk run hadn't happened), plus a session prompt making **Act 0 a hard gate** — "deploying #2505 and reading your feedback both change what the rest of the session should do" — and naming the stale-premise problem explicitly as the biggest source of wasted agent time. Opus session: **no `model:fable` work started** (#1114, #2492, the frontier set) — Fable's weekly allowance is spent.*

**The one-line outcome:** Act 0's hard gate paid for itself immediately — reading the *live* Telegram thread instead of waiting for feedback found a **P2 defect that made the coaches structurally unable to acknowledge anything Matthew told them containing a number**, shipped and deployed the fix inside 30 minutes, and then the same measure-first habit caught a **near-miss that would have deleted his entire coach conversation history**. 15 PRs merged, 11 issues closed, open corpus 64 → 56.

## The headline: what the live thread said (read this before tuning coaches again)

There was **no owner feedback** to read — no notes, no screenshots, nothing newer than 08-09 19:09. So I read the data instead. `COACH#physical_coach` had been empty at 07:40 PT and had rows by 08:00: he was texting *while the session ran*, and the #2505 training→Max alias I had just deployed was routing him there.

Two turns, and they are the whole story of where the coaching work stands:

- **Turn 1 — the humanity pass working exactly as designed.** He sent `Hey`. Max replied **"Hey — Day 1. You lifting today?"** Register matched (bare hey → bare hey), experiment-aware (Day 1 of cycle 13 — #2498 live), no stat recital, no filler question. That is #2481 + #2498 doing their job on the first real morning.
- **Turn 2 — a hard failure.** He said he'd woken late and done a short walk instead, with the distance in the sentence. The reply **held twice on `fabricated_number`** and fell back to the deferral string: *"Let me check that before I answer… Ask me again in a minute."* He had not asked a question. Nothing in the system would have had an answer in a minute. He stopped texting.

**Root cause (#2517, PR #2518, merged `5e187d87`, DEPLOYED and symbol-verified live):** the wiring, not the gate. `lambda_handler` called `run_turn(inbound=text, …, grounder=_grounder_for(a))`. `_assemble()` runs *before* the turn, so `a["thread"]` held only PRIOR turns — **the current message reached the model but never the gate.** Any number he states in the message being answered is unsupported by the allow-list. Generalises to every *"I ran 3 miles"*, *"I weighed 214"*, *"I slept 5 hours"*. The gate was right that the figure wasn't in platform facts (nothing had ingested the walk); it should never have been asked to adjudicate his own words.

The tell was an asymmetry between two callers of one helper: `_maybe_refer` already passed its conversation `tail`. Fixed with one extra evidence source, guarded by the property, **its complement** (an unsourced number must STILL fail — the test that stops a grounding fix becoming a grounding bypass), a night-class test proving #2343 stays armed, and an **AST pin at the call site**, because a gate-level test passes with the bug still present.

## The near-miss: a data repair that would have deleted his coach history (#2520, PR #2525)

Found while triaging #2379, by classifying a dry-run's output instead of trusting the tool's own recommendation.

`deploy/backfill_coach_ensemble_phase_stamps.py` (#1970) sweeps **entire** `COACH#*`/`ENSEMBLE#*` partitions and stamps every row lacking `phase`, with **no call to `phase_taxonomy.classify()`**. Correct when written — those partitions held only `PREDICTION#`/`BRIEF#` rows. **ADR-153 then added `CHAT#`/`RELATIONSHIP#` rows to the same partitions**, classified `CROSS_PHASE` ("NEVER tagged") *precisely so conversation history survives a reset*.

Measured live: **all 21 rows in scope would have been mis-stamped** — 15 `cross_phase`, 6 `system_state`, **not one genuinely experiment-scoped**. `phase=experiment` marks a row for the reset wipe, and the write is conditional on `attribute_not_exists(phase)`, so it would **not** have been reversible.

Two compounding failures worth remembering:
- **The platform instructed the operator to do it** — the nightly qa-smoke warning ends in a literal `Run deploy/backfill_…py --apply`.
- **The coverage check counts a correct state as a gap**, so its count **grows every time he texts a coach** and can never reach zero — a permanent feeder of the qa-smoke alarm saturation.

`--apply` was never run; live rows are correctly unstamped. No data repair needed.

## #2379 answered with data, not deferred (the plan said to drop acceptance (a) — don't)

The plan called acceptance (a) un-actionable ("needs a nightly an agent cannot wait for"). It was answerable in one CloudWatch call. `FailCount` has been **nonzero every day since 08-01** — nine consecutive days, daily sums to 99, alarm continuously in ALARM since **07-31** with a `StateReason` still citing one datapoint from that date. By the issue's own decision rule (*"if not, what remains is a new finding, not residue"*), the residue framing is retired. Four live classes enumerated and routed (#2418 / #2520 / #1956) rather than re-filed. Acceptance (b) **kept and narrowed**: #2414's `as_of_agreement_qa` enforces only `stamp <= pacific_today()` and its docstring says "behind is legal" — the served-date correspondence half is genuinely uncovered.

## What shipped (15 PRs merged)

**Coach cluster:** #2518 (the inbound-evidence fix, deployed) · #2519 time-gap awareness — landed with **zero diff to the 862-line worker** by extending `coach_chat_summary` instead · #2521 per-persona availability replies (found `run_turn` needed a new `persona_id`; `coach_id` is not reliably a registry key) · #2524 team texture + track-record humility · #2527 event-triggered outbound + the outbound **provenance ranking** (kept promise > referral > pre-event > soft concern > check-in > celebration; cap stays 2).

**Grounding / honesty:** #2529 observatory_summary — the census was **six** consumers, not the three the issue named or the five the plan named, and the real find was that **`key_recommendation` outranks it on three paths with no guard at all**, and three chains ended at `""` not `content` (a hold would have *blanked* the coach) · #2523 `/api/explain` fails closed · #2526 + #2528 + #2530 the #2221 tranche-2 clusters.

**Infra:** #2516 · #2522 (`_PREMERGE_EXTRA_FILES` derived) · #2525 · #2531/#2532 (my own fallout).

**Closed on measurement, no code (the plan's "free" items — both confirmed stale):** **#2101** — the layer is already on `garminconnect 0.3.8` (`garth-layer:3`, live on the function), the dual-generation seam already spans both, and the CVE mechanism is unreachable (no tokenstore path); the true residual needs an interactive MFA re-auth on a source paused under ADR-074. **#1654** — all four named god-modules are done (`site_api_intelligence` 2,459 → **178**; the comment claiming one remained was itself stale); residual filed as **#2515**.

## Where agents beat their own briefs (the premise discipline paying off)

- **#2522** corrected *my* correction: the list was **26**, not the issue's 23 or my brief's 28 — and the derivation found **36** sweepers with only 17 named. A literal stale in three separate accounts.
- **#2530** fixed the EWMA marker in the **opposite direction from what it asked**: at n=5 the "prior" collapses to a single raw reading, so honouring the marker would have manufactured ADR-105 confidence. Also found `values[:len-7]` goes negative below 7 observations.
- **#2528** found the marker's stated remedy would ship a *new* bug — "anchor on the event date" literally widens both windows by a day and breaks `compute_momentum`'s 7-and-7 split.
- **#2524** refused to fold `inconclusive`/`expired` into hit-or-miss: terminal, but not outcomes — ADR-104 fabrication aimed at the coach's own record.
- **#2529** caught its own **mutation that didn't mutate** (its first proof used a field `guard_derived_summary` already covered).
- **#2527**, sent back on a correct surface-drift red, refused an exemption and made the sweep **report itself** so a heartbeat became possible — errors say "it broke", the new `EventSweepCompleted` series says "it stopped".

## Gotchas (new this session)

- **`black` corrupts JSON — and I did it to `tuning_log.json` on main.** My reconcile loop resolved conflicts by stripping markers then running `black` on every non-doc file. On a `.json` that (a) kept **both** sides — duplicated `_meta` *and* a fully duplicated `entries` array — and (b) added a Python trailing comma. Main carried invalid JSON from `b46ffb5b` until #2532. **Two behavior-pin entries were lost outright** and had to be rewritten from the shipped diffs. Never run a Python formatter over a data file; never resolve a structured file by line-oriented marker stripping. (The trap is already in memory — I walked into it anyway.)
- **The reconcile ritual's "one at a time" is load-bearing.** I batch-reconciled 9 branches, then the first merge advanced main and the other 8 went CONFLICTING at once. Each PR must reconcile against main *after* the previous merge.
- **GitHub's mergeability is stale for a few seconds after a force-push** — a `--squash` immediately after reports "has merge conflicts" on a branch that is provably a clean single commit on top of main.
- **`agent_commit.sh` needs explicit paths** (`"<msg>" <path>…`) and refuses doc-sync literal files without `ALLOW_DOC_LITERALS=1`.
- **`config/personas.json` is read S3-FIRST**, and `config_twin_sync.py` does **not** cover it — the handover's instruction was wrong. The real path is `deploy/deploy_coach_intelligence.sh:44`. A repo-only personas change is silently dead in Lambda.

## Wrap gate ledger

- **Main:** stranded — the R8-ST6 Plan-red is unchanged from session start (the owner's `cdk_deploy.sh LifePlatformServe` still has not run, so every ci-cd deploy strands), and #2527 adds a second CDK-owned resource to that same stack.

  Two things, kept distinct because they clear differently. (1) **Stranded** is the standing condition and only the owner's cdk run clears it. (2) The last completed run, at `cb3b4421`, was *also* genuinely **red on tests** — 11 failures, all from the `tuning_log.json` corruption I caused during the reconcile plus the two literals the merge queue moved. That half is **fixed and pushed** (#2532 + the wrap commit): the same suites now pass 96/96 locally, `check_doc_facts` and `sync_doc_metadata --check` are both ✅, and the full suite was green over the merged tree before the corruption was introduced. The next completed main run should show Plan-red only. **#2468 deliberately left open** (drift still present; do not re-close it by grepping a job log — use annotations or `check_ci_warnings.py`).
- **Build beat:** `2026-08-10-the-coaches-couldnt-hear-you` — merged **and deployed** (#2518).
- **Docs:** `docs/INCIDENT_LOG.md` (+2 rows), `docs/ARCHITECTURE.md` alarm literal 86 → 97.
- **Decisions:** none needed — the outbound provenance ranking is an owner decision pre-resolved in the plan and recorded in `COACH_HUMANITY_ROADMAP.md`, not a new ADR.
- **Incidents:** 2 rows — the inbound-grounding defect (**P2**, live, ~9h undetected, no alarm exists for a held reply) and the phase-stamp near-miss (**P3**, averted).
- **Closures:** #2517, #2520, #2489, #2495, #2496, #2393, #2372, #2101, #1654 commented with the ADR-099 two-line verdict; #2490 and #2418 closed by their PRs. Several honestly `partial` — **merged ≠ deployed while main is stranded**.
- **Backlog:** `check_backlog_hygiene.py` → OK, **56 open**. `Now` refilled to 5 (promoted #2486, #2430, #2493 with their score lines). Epics #1648, #1890, #2363 updated with the new/closed stories.
- **Alarms:** `check_alarm_citations.py` ✅.
- **CI warnings:** not triageable — `check_ci_warnings.py` no-ops while main isn't green.
- **Stash/hooks:** stash empty; pre-commit hook present.
- **Worktrees:** 13 stale ones removed. **6 remain in-repo under `.claude/worktrees/` carrying UNPUSHED commits** — left deliberately rather than destroy another session's work; they pollute scanner globs until someone pushes or discards them.

## Residuals / next picks

- **Owner ① — `bash deploy/cdk_deploy.sh LifePlatformServe`. Still the first command of the morning, and now carrying more:** #2505's IAM + weekday rule, **plus #2527's new EventBridge sweep rule and `telegram-event-sweep-heartbeat` alarm**. Deploy the worker code in the *same* session as the stack — the heartbeat breaches on missing data over 2 daily periods, so its first producer must be live inside that window.
- **Owner ② — the deploy debt is large and real.** Only `telegram-coach-worker`, `telegram-webhook` and `config/personas.json` (S3) were deployed. **Merged but NOT deployed:** site-api (#2523 + #2529), `coach-state-updater`, `coach-daily-reflection`, `coach-panel-podcast` (**#2529 warns: deploy the writer and its three readers in one window, or a held record meets an old reader that ends at `""`**), `qa-smoke` (#2525 — until then the nightly still prints the destructive remediation), `ai-expert-analyzer`, `daily-insight-compute`, `health-auto-export` (#2530 — a fabricated `0` diastolic still reaches readers until it ships), `coach-prediction-evaluator`, `weekly-plate`, `weekly-digest`. Also owed: re-upload `config/personas.json` to S3 after #2521 (`deploy_coach_intelligence.sh` step 1) or every coach keeps the generic availability strings.
- **Owner ③** BotFather trio + Max rename — `not-work — BotFather is owner-only by standing rule; no issue can move it`. Still blocks Eli's check-in and all Vale/Brooks referrals, so every outbound feature merged tonight stays dark until it happens.
- **Owner ④** `CONTENT_FILTER_JSON` repo secret — `not-work — an owner-held credential; the ER-06 vocabulary lives off-repo by design (#2370's closure comment tracks the consequence)`. **⑤** `python3 scripts/reconcile_strava_measured_zero.py` (review the 6-row plan, then `--apply`) — `not-work — a data decision on historical rows; the code fix already shipped (#2331, closed)`. **⑥** coach portraits contact-sheet for Vale/Brooks — #1114 (ADR-106 owner-approval gate either way; `model:fable`, deferred to the Fable reset).
- **Ratification: no ruling was left** — every one of #723/#1668/#2363/#1364/#1365/#1367/#1414/#1402/#1401/#1631 still shows last session's own comment as the latest. Per the plan I did **not** re-comment. One ask, not two.
- **The live acceptance bar is still the live acceptance bar.** #2518 is deployed; the next session should read the thread again, not a queue. #2492 (prompt-pass v3) remains the highest-value coaching follow-up and is deliberately `model:fable`.

**Build beat:** `2026-08-10-the-coaches-couldnt-hear-you` — a grounding gate that muted the user's own words, found by reading the transcript rather than the backlog (merged + deployed, #2518).
