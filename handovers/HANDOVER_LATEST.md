# Handover — 2026-09-03/04 (Opus 5): Session U — the re-anchor (Friday, then corrected to Saturday), the drain, and the sweep proving itself

**Session:** Claude Opus 5, driven by one owner instruction — *"do another full platform
experiment reset so it all starts on friday september 4th"* — then, after it landed,
*"review and take autonomy on anything you can close in the backlog throughout the night,
and then once you are done - wrap"*, narrowed mid-session to **`model:opus` and below, no
`model:fable` work**, and *"no need to publish email"*.

Not the Session U that was planned. The approved 09-08 plan (Architect ritual + the
time-anchored batch, `~/.claude/plans/lovely-snacking-panda.md`) is **untouched and still
valid** — this session was an owner-initiated re-anchor that arrived five days early.

**Main:** green (eb777b5b) — it went red twice tonight, both mine, both from running targeted tests instead of the full suite: 5 checks after #3473 (fixed b73b41f58) and 4 ratchets after #3477 (fixed eb777b5b5, CI/CD success). Tip 87ec9d667 (the Day-1 static rebake) has its run in flight; v4 site gate, Cron freshness and CodeQL already green on it. Every red surfaced under a CI/CD `cancelled` rollup — three times in one night
**Build beat:** none — the reset is a platform-state change and the rest is internal gate plumbing; the one reader-visible change (the Day-1 static rebake) is the reset flipping its own copy, not new work
**Docs:** SCHEMA.md (genesis literal), engines/CHARACTER.md (re-verified), MCP_TOOL_CATALOG.md, ARCHITECTURE.md + INFRASTRUCTURE.md + MONITORING.md (alarm count), DEPENDENCY_GRAPH.md + model/platform_model.json, PROPORTIONALITY.md, alarm_citations.json
**Decisions:** none needed — the threshold re-derivation and the extraction both follow existing ADRs (ADR-105 for the derivation, the #2604/#2610/#2977 extraction precedent); neither is a new governance posture
**Incidents:** none — main was red ~22 min (03:50Z v4-site-gate fail → 04:12Z green on the fix commit), under the >1h bar; no auto-rollback fired, no data gap, no budget event. The five gate reds are recorded as #3477 instead, because they recur by construction rather than being an event
**Stash/hooks:** clean
**Closures:** #3473, #3474, #3477, #3476 commented · DoD: scanned 4, hits 0 — every closure carries the ADR-099 `**Shipped:**`/`**Outcome:**` pair
**Backlog:** filed #3478 from the Day-1 runlist. Now 1 actionable in the opus lane; **NO REMEDY IN THE CORPUS** — `backlog_next.py --refill-now --lane opus` found zero startable promotions and correctly refused the 11 startable stories outside the lane (promoting one turns the count green while adding nothing this session could start). Floor NOT lowered. Later sweep — no stale issues (31 open all satisfy the contract). Filed #3476, #3477
**Alarms:** 1 flap cited — `ai-tokens-platform-daily-total` fired-and-cleared in the 72h window (#2912 detector); dated self-clearing entry added, prune on/after 2026-09-07. That flap *is* the defect #3474 closed
**CI warnings:** none — the `LifePlatformMonitoring` dashboard-`Tags` warning is GONE. #3476 shipped and `check_ci_warnings.py` now exits 0 with no `--decoded`, which is the one acceptance box I said could not be confirmed tonight
**Ledger:** compute-pipeline liveness heartbeat (#3473) + reset doc-gate sweep (#3477) rows added; the #3477 row then AMENDED for #3479 (its JS leg went from one file to the v4 gate's whole `node --test`)

---

## Part 1 — The reset (the instruction)

Cycle 15 (genesis 2026-09-01) → **cycle 16, genesis 2026-09-04 (Friday)**. Run as a
future/eve genesis from 2026-09-03 ~20:45 PT.

```
python3 deploy/restart_pipeline.py --genesis 2026-09-04 \
  --override-weight-lbs 324.64 --with-preregistration --sync-site --apply
```

- **Baseline 324.64 lbs** — the 2026-09-03 weigh-in, the last real reading. The override
  is mandatory for a future genesis; the supersede reflex is owed when Friday's weigh-in
  lands (tracked on the re-anchored #3390).
- Census preflight **98/98** pk families classify. 50 rows re-phased to `pilot`, **314
  intelligence rows tombstoned** with `cycle=15` on the archive, ledger rolled to
  `LIFETIME#aggregate` with `TOTALS#current` zeroed, **45 open pre-registered bets voided**.
- Prologue lead-ins re-dated to genesis −6 / −2 / −1. Full `cdk deploy --all`, site synced.
- **Hard gates: rendered 96/96 · semantic 8/8 · truth 8 surfaces clean** at 1d pre-start.
  The truth gate ran for real (budget tier 0), not a loud skip.
- Live by content: `/api/journey` and `/api/character` both serve `start_date: 2026-09-04`,
  `day_n: 0`, `pre_start: true`. All 104 lambdas re-stamped 03:38–03:51Z.

**Cycle 15 closes SEALED, not grandfathered.** Its prereg artifact + SHA-256 stamp are
still live and verifying at `/experiments/prereg/genesis-2026-09-01.json`, so unlike
cycles 10 and 13 it needs no `prereg_seal_gate.py` record. Its frozen file was archived in
place as `genesis_preregistration_2026-09-01_cycle15.json` **before** seeding cycle 16 —
the seeder aborts otherwise.

**Cycle 16's claims are frozen but NOT public**: 8 coaches, 2 hypotheses, sha
`cd8156f1…`. Predict-the-week seeded off them (week 2026-W36, 2 subjects).

### The reset's real lesson — a pipeline that exits 0 and reds main by construction

`restart_pipeline.py` exited 0 with all three of its own gates green, and the resulting
commit produced **five** gate reds. Three of them recur on *every* reset:

| red | cause |
|---|---|
| `tests/js/genesis_pt_2941.test.mjs` ×6 (v4 site gate) | genesis-anchored boundary instants; its own first assertion is the drift detector, and the file says "regenerate them with the sweep, don't loosen" |
| `docs/SCHEMA.md:2852` (`check_doc_facts`) + `test_wiki_checkers.py` ×3 | stale genesis literal. **My first explanation was wrong** — see Part 3: `sync_doc_metadata` ran and *refused* the rewrite, because #2986's freshness hold classified a semantic date fact as a cosmetic re-stamp |
| `docs/engines/CHARACTER.md` (`check_doc_index --strict`) | the reset rewrites `config/character_sheet.json`, invalidating the doc's `Verified` stamp **every time** |
| `docs/MCP_TOOL_CATALOG.md` | the pipeline's catalog write disagrees with the canonical generator |

Cause: the pipeline runs **one** doc gate (`sync_doc_metadata.py --apply`); CI runs
**twelve**. Filed as **#3477** with the full table.

The `CHARACTER.md` stamp was **re-derived, not date-bumped** (#973/#2619 — the stamp is a
claim): whole-file config diff is 4 insertions / 4 deletions confined to `_meta` + the
baseline block, line count 571 → 571, zero commits to `character_engine.py` or
`character_sheet_lambda.py` since the 09-02 verify, so every line citation is unshifted by
construction.

## Part 2 — The backlog night (the autonomy grant)

Lane filter applied: `model:opus` and below. That correctly dropped **#3422, #3436, #3373,
#3042** (all `model:fable`). **#3403** is genuinely date-gated — its last acceptance box
requires a week of post-#3378 data (~09-08).

### #3474 — the token alarm fired on the platform's ordinary working day · CLOSED

150,000 was set 2026-06-24 against a ~59k/day baseline peaking ~121k. Measured over 31 days
it had become **the 75th percentile**.

```
n=31 to 2026-09-02 · median 87,046 · Q1 68,592 · Q3 145,161 · p90 220,318 · max 492,314
breach @150k: 8/31 = 25.8% [13.7%, 43.2%] Wilson → ~7.7 fires/30d
```

Every one of the 8 breaches fell on a working-session day, so the question is not "is this
day expensive" but "is it anomalous for *this* distribution". The distribution is strongly
right-skewed (CV 0.79), so mean±sd is meaningless here; two **robust** estimators bracket
it and agree closely — Tukey `Q3+1.5·IQR` = **260,014**, `median+3·1.4826·MAD` =
**221,743**. Shipped **250,000**, between them, rounded, erring low (an alarm should fail
toward firing). New rate 3/31 = 9.7% [3.3%, 24.9%] ≈ 2.9/30d.

Scoped explicitly rather than silently: this is **not** budget protection — 250k/day of
output is ~$112/mo at sonnet's $15/1M against a $215 ceiling. Sustained burn is
`cost_governor`'s tiering, which already exists. Whether the outlier detector earns its keep
*beside* the governor is a proportionality question left for the owner, stated on the issue.

Paid for **in place** (`monitoring_stack.py` was AT its 1331 ceiling): the new derivation
REPLACES the 2026-06 one, 1331 → 1331.

### #3473 — a heartbeat, and the ledger that should have caught its absence · CLOSED

`compute-pipeline-stale` had no heartbeat, so a dark emitter read as a permanently healthy
pipeline. **The missing alarm was the symptom.** The cause: `test_silent_failure_heartbeats.py`'s
`_DETECTORS` ledger — the registry asserting every daily detector has *both* halves — named
five pairs and **neither compute pair**. So this gap was invisible to the guard built to see
it, *and* `compute-outputs-heartbeat` (shipped #1455) was equally unasserted — deleting it
tomorrow would have gone unnoticed. Both pairs are ledgered now. That ledger also read
`monitoring_stack.py` **by name**, so an alarm became "missing" the moment it moved to a
sibling — the same fragility #2977 fixed in `cdk_alarm_pins.py`; it now scans all of
`cdk/stacks/*.py`.

Negative-controlled both ways: delete the heartbeat call → 2 tests red; keep the NAME but
build it through the problem-alarm helper (silently `NOT_BREACHING`) → 1 test red; restore →
3 green. The second control is the one that matters.

**days=2, not the >26h the issue asked for — the issue's bar was unachievable.** The metric
is emitted once daily at 17:00Z while CloudWatch's 86400s periods align to UTC midnight, so
the in-progress period is empty 00:00Z–17:00Z *every day*; a 1-day BREACHING heartbeat would
fire every morning. days=2 reds after >31h of real silence.

Paid for by **extraction** (the FULL-file rule, never a raise): the compute liveness *pairs*
moved to `cdk/stacks/monitoring_compute_alarms.py` with a stated membership rule. 51 lines
out for a 5-line call site + import; measured 1290, baseline 1331 → **1300** (10 banked = a
fifth, the #2610 rule).

Verified against **live deployed state**, not a second synth: `85 → 86` resources, **zero
dropped**, exactly one added, all three moved constructs keeping their logical ids.

### #3390 — re-anchored, not closed

Was titled for cycle 15 (genesis 09-01, override 326.24). My reset made its Outcome
unachievable — cycle 15's Day 1 is history and its intelligence is tombstoned. Re-anchored
in place to cycle 16, with the countdown-gap window corrected (~3.25h, vs cycle 15's
~10.75h) and a section listing what the reset already verified so tomorrow's runlist is
shorter and honest.

## Gotchas hit this session

- **`REAL_EXIT` is not the task's exit code.** Two background tasks reported "exit code 0"
  while the wrapped command exited 1 and 4. Read the `REAL_EXIT=` line, always.
- **`gh run list --commit <short-sha>` returns zero runs, silently.** Nearly read a bot
  commit as swallowed. Resolve the full sha, or query `?head_sha=` via the API.
- **zsh does not word-split an unquoted `$var`.** A loop over gate commands returned exit 2
  for eleven of twelve gates — every one had run as a single filename, not a command. An
  all-red board that is actually a shell bug.
- **A local full-suite run concurrent with edits is evidence in neither direction.** It
  produced one spurious failure *and* missed three real ones, because it read a
  half-fixed tree in both directions.
- **`git stash push` silently skips untracked files**, which made a before/after `cdk synth`
  diff vacuous — both sides were identical. Compared against the live deployed stack instead,
  which is better evidence anyway.
- **Docs CI reports `cancelled`, not `failure`, over real step failures** — three hidden the
  first time, one the second. On this repo a `cancelled` Docs CI is not a timeout; open the
  steps.
- **`agent_commit.sh` reverts `platform_counts.py`** rather than committing it (refused
  outright, no escape hatch). On main the driver folds it in with `--amend --no-verify`;
  leaving it stale reds 3 tests.
- The reconcile bot raced me **twice**, both times making the identical fix. Rebase; the
  duplicate commit drops out as already-applied.
- **A CI/CD `cancelled` rollup hid real failures THREE times tonight.** Never read it as a
  timeout or a concurrency cancel without opening the steps.
- **`agent_commit.sh` reverts `platform_counts.py` and refuses it outright.** On main the
  driver regenerates and folds it in with `--amend --no-verify`; do it AFTER agent_commit
  runs, or the revert eats it.
- **Backticks in a commit message passed as a shell argument** get command-substituted by
  zsh. Write the message to a file and pass `"$(cat file)"`.
- **`npx cdk diff | grep` can come back empty when the diff is non-empty** (buffering);
  redirect to a file and grep the file, or you will "prove" a drift is gone when it isn't.
- **A monitor's `until grep -q 'passed'`** matched black's "All checks passed!" and fired
  ~13 minutes early. Wait on a token only the target emits (`REAL_EXIT`).

## Part 3 — After the first wrap: "fix them then" (the post-midnight run)

The wrap at `3ff0b5480` was not the end. The owner asked for #3477, #3476 and (at
genesis) #3390. What follows is the honest record, including two self-inflicted reds.

### I broke main. Twice, the same way.
After #3473 I ran targeted tests and not the full suite; five checks caught it
(`b73b41f5`). After #3477 I did **exactly the same thing** and four ratchets caught it
(`eb777b5b5`). Both times the failure surfaced under a CI/CD **`cancelled`** rollup —
which on this repo has now hidden real failures **three times in one night**. A
`cancelled` CI/CD here is not a timeout; open the steps.

The second breakage is the more interesting one: the two module-size failures were caused
by **comments I wrote explaining the fix**, not the fix. The ratchet was right — the
narrative already lived in the test docstrings — and the cure it demands (shrink, never
raise) produced better code than what I first wrote.

### #3477 — CLOSED, and the filed mechanism was wrong
I blamed `restart_docs_update.py`. In fact `sync_doc_metadata --apply` ran as designed and
reported "Applied 1 change(s)" — it *refused* this one rewrite. #2986's "no manufactured
freshness" hold defers anything that `differs_only_by_date_stamp`, and
`(currently 2026-09-01)` → `(currently 2026-09-04)` differs only by a date. **The one rule
whose job is converging the genesis literal was structurally unable to fire.** CLAUDE.md's
twin escaped by accident: it carries the cycle number, so masking leaves `cycle 15` vs
`cycle 16` visible.

The distinction already existed (`doc_restamp_guard.stamped_rules()`); it just wasn't
consulted where the decision is made. Exactly two rules are in the semantic-date class,
both genesis anchors — and #2986/#2649's own 167 tests still pass.

Plus `deploy/restart_verify_gates.py`: the pipeline now runs CI's twelve doc gates
**derived from `docs-ci.yml`**, never restated, as its final sub-script. It caught a stale
`test_count` on its first run — one the tests written for #3477 had themselves moved.

### #3476 — CLOSED without crossing a security boundary
The obvious fix is a `TOLERATED_NON_IAM` entry. **That set is a ratchet that may only
shrink**, and its own design says a widening must reach the owner via the ADR-065 baseline
block, because tolerating a delta lets additive IAM ship beside it. So the fix changes
**one advisory line and no verdict**, keyed on `(resource type, property)` rather than
message text. Mutation-proven both ways, including the positive control.

Verified after the fact: `check_ci_warnings.py` now exits 0 **with no `--decoded`** — the
acceptance box I had recorded as unconfirmable tonight.

### #3390 — worked to its limit, deliberately NOT closed
**The genesis flip worked unattended**: at PT midnight `/api/journey` went `day_n` 0 → 1,
`pre_start` true → false, `started_date: 2026-09-04`; `/api/predict_week` lit for 2026-W36.

`restart_verify` finished **23 pass / 2 fail**, both owner-only: no Day-1 weigh-in yet
(supersede reflex still owed) and cycle 16 still unsealed. Cleared during the run: the
character sheet (forced compute wrote `DATE#2026-09-04`, `replay_verified=True`) and the
baked static proof (`87ec9d667` — without it every meta card and noscript block still
advertised "the experiment begins Friday, September 4" after it had begun).
`restart_integration_check --expect-cycle 16`: **30 pass / 2 fail**, both known —
three cited alarms, and `notion` stale 607h on a source whose registry says
`behavioral: True, monitored: False`, i.e. a gate that reds on honest human behaviour.

En route it turned out **this issue's own verifier had a check that had never once run**:
the #2116 composite leg called `describe_alarms` without `AlarmTypes` (metric alarms only),
so two deployed composites read as "not deployed" — and that verdict took the tolerant
branch, silently skipping the four assertions beneath it. Fixed in `a5fce037b`; both now
execute and pass.

### Filed from the runlist
**#3478** — `/api/journey` serves `last_weighin_date: 2026-09-04` and `weighin_count: 1`
when no weigh-in happened. Mechanism verified, not guessed: the reset re-phased the 09-03
row to `pilot`, `_latest_item` hides pilot by default, the series empties, and the
genesis-baseline fallback supplies the genesis date *as a measurement date*. The
`pre_start` branch already nulls exactly this ghost (#948); Day 1 has no equivalent guard.

### The through-line, extended
Six instruments this session were unable to fail, or failed to mean what they said:
`restart_pipeline` (one gate vs twelve), the `_DETECTORS` ledger, the unshippable CI
warning, `restart_verify`'s composite leg, its "raw alarm missing" message on a **passing**
check — and my own first wire-guard for #3477, which passed over the exact defect it was
written to catch until I mutated it.

## Part 4 — the owner typo, and the sweep earning its keep the same night

At 01:2x PT the owner said the reset should have been **Saturday 2026-09-05**, not Friday.
Cycle 16 was ~1h old with **no weigh-in, no brief and no published prereg** — nothing of
record.

**Re-anchored IN PLACE rather than closing a phantom cycle** (owner picked this):
`--genesis 2026-09-05 --no-close-cycle`, plus a hand-corrected `CYCLE_GENESES[16]`
(2026-09-04 → 2026-09-05, with a comment saying why it is a correction and not an append).
SSM stays 16. The deciding factor was the seal gate: cycle 16's prereg was frozen but never
published, so **closing it would have required a permanent grandfather record** in
`prereg_seal_gate.py` — the right record for cycle 13, which genuinely ran and missed its
seal, and the wrong one for a typo caught in 90 minutes. The correction is still recorded
three ways: the CYCLE_GENESES comment, the RESET_LOG line, and the archived Friday freeze
(`genesis_preregistration_2026-09-04_cycle16.json`).

### The #3477 sweep proved itself on its first live reset — twice
It **ABORTED the pipeline** rather than letting it exit 0, both times:

1. `generate_mcp_tool_catalog --check` + the genesis-anchored JS fixtures.
2. After regenerating both: the **catalog again**.

The second abort root-caused a defect that had been silently recurring on EVERY reset:
`restart_docs_update.py` appended a `### Phase-filter behavior (ADR-058)` section to
`docs/MCP_TOOL_CATALOG.md` — a file `scripts/generate_mcp_tool_catalog.py` regenerates
WHOLE, and which already emits its own `##` version of that exact section ("behavioral doc,
stable across regenerations"). Two writers, one file, a staler duplicate: the generator
wiped the append, the append re-added itself, and `--check` redded whichever way the last
write went. **The #1287 owned-manifest clobber, third specimen.** The duplicate writer is
gone; the generator is the single owner.

Scoreboard for #3477's three "recurs every reset" items, measured rather than argued:
`SCHEMA.md` genesis literal **fixed at source** (converged automatically, gate passed);
JS fixtures **caught pre-commit**; MCP catalog **caught pre-commit and root-caused**.

### Verified live after the re-anchor
`day_n: 0 · pre_start: true · started_date: 2026-09-05 · days_until_start: 1`, character
`pre_start: true`, constants `2026-09-05`, SSM cycle **16** (unchanged), prereg re-frozen
for Saturday (8 coaches, 2 hypotheses). Gates: rendered **96/96**, semantic **8/8**, truth
**8 surfaces clean**, and the doc-gate sweep green.

### Two more the re-anchor surfaced, AFTER the handover was first written

**The engine-doc gate cannot be caught pre-commit.** `check_doc_index --strict` reds on
`docs/engines/CHARACTER.md` the moment `config/character_sheet.json` is COMMITTED — it
compares commit dates, so it is structurally invisible to the #3477 sweep, which runs
against the working tree. It duly redded right after the re-anchor commit. Re-derived (2
lines changed: `start_date` → 2026-09-05, `_meta.last_updated`; the weight did NOT move,
only the date it anchors to) and the limitation is now recorded in the stamp itself so the
next reset does not rediscover it.

**#3479 — a fixture that redded main on a DATE, and the sweep running a subset of its
gate.** `tests/js/coach_asof.test.mjs` pinned a hardcoded `2026-08-27` stamp and asserted
the FRESH rendering; `weeklyAsOf` appends "— next refresh pending" past 8 days, so on
2026-09-04, *exactly* 8 days later, it redded the v4 site gate on a commit that touched
none of it. The sibling assertion one test above used the same stamp and survived only
because its regex lacked a `$` anchor — **one case failed loudly and one passed wrongly
off identical input, and the difference was an anchor character.**

And the sweep did not catch it because its JS leg ran ONE file while the v4 site gate runs
the whole `node --test`. That is #3477's own principle turned on #3477: **a check that
executes a subset of another check can promise nothing about it.** Fixtures now derive from
`Date.now()`; the sweep runs bare `node --test`; a guard pins it.

## Residual / next picks

- **#3390** — Day-1 runlist for cycle 16, now run ON or AFTER **2026-09-05** (post-genesis by
  construction; `restart_verify.py`, the two reconcilers in order, the supersede reflex).
- **#3478** — `/api/journey` reports a weigh-in that never happened on Day 1 of a cycle
  (ADR-104). Filed from the Day-1 runlist; self-heals on the first weigh-in. Confirmed
  scoped to POST-genesis Day 1: the pre-start branch correctly nulls both fields today.
- **#3390** — still open by design: the Day-1 weigh-in + supersede reflex, the attended
  prereg publish + stamp, and the cloud routine's own public-surface verdict. Its runlist
  is otherwise executed and recorded on the issue.
- **#3403** — CI duration budget; blocked until ~09-08 by its own acceptance (needs a week
  of post-#3378 data).
- **#2978** — deploy-race umbrella, `blocked:date` (~09-08).
- **#2883** — AI-cost self-metric drift, `gate:owner`.
- **#3422 / #3436 / #3373 / #3042** — all `model:fable`; out of lane for this session by
  owner instruction, not by blocker.
- `not-work — owner-only, and deliberately not automated`: **cycle 16's pre-registration is
  frozen but unpublished** (sha `cd8156f1…`). `publish_genesis_preregistration.py` +
  `genesis_prereg_stamp.py --apply` are attended by #1092 posture; the owner chose
  "seed + review, then publish", and the publish dry-run was additionally blocked by the
  auto-mode classifier. Cycle 16 stays unsealed until this runs — cycle 13's precedent is
  a grandfather record.
- `not-work — expired by design, owner declined`: the **genesis-eve prereg lock email**
  was not sent ("no need to publish email"). It refuses after PT midnight by design;
  recording the skip rather than backdating it.
- `not-work — owner judgement`: **the `notion` staleness FAIL** in
  `restart_integration_check` — that source is `behavioral: True, monitored: False`, so its
  staleness is the datum, yet a flat 336h threshold reds the behavioural check. File it or
  waive it; I did not want to manufacture an issue out of journaling habits.
- `not-work — standing observable`: **`compute-pipeline-stale-heartbeat` has not yet
  produced a first verdict** (`INSUFFICIENT_DATA — Unchecked: Initial alarm creation`).
  The emitter is confirmed healthy (1 datapoint/day, 10 consecutive days) so OK is a
  prediction; confirm it settled at the next session.
- `not-work — the approved plan, unchanged`: **Session U proper** (Architect ritual + the
  time-anchored batch) remains scheduled for 2026-09-08,
  `~/.claude/plans/lovely-snacking-panda.md`.
