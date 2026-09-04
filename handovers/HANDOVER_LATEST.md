# Handover — 2026-09-03 (Opus 5): Session U — the Friday re-anchor, and what a green pipeline didn't tell us

**Session:** Claude Opus 5, driven by one owner instruction — *"do another full platform
experiment reset so it all starts on friday september 4th"* — then, after it landed,
*"review and take autonomy on anything you can close in the backlog throughout the night,
and then once you are done - wrap"*, narrowed mid-session to **`model:opus` and below, no
`model:fable` work**, and *"no need to publish email"*.

Not the Session U that was planned. The approved 09-08 plan (Architect ritual + the
time-anchored batch, `~/.claude/plans/lovely-snacking-panda.md`) is **untouched and still
valid** — this session was an owner-initiated re-anchor that arrived five days early.

**Main:** green (4b8660bc)
**Build beat:** none — the reset is a platform-state change, not a shipped feature; the two backlog fixes are internal alarm plumbing with no reader-visible surface
**Docs:** SCHEMA.md (genesis literal), engines/CHARACTER.md (re-verified), MCP_TOOL_CATALOG.md, ARCHITECTURE.md + INFRASTRUCTURE.md + MONITORING.md (alarm count), DEPENDENCY_GRAPH.md + model/platform_model.json, PROPORTIONALITY.md, alarm_citations.json
**Decisions:** none needed — the threshold re-derivation and the extraction both follow existing ADRs (ADR-105 for the derivation, the #2604/#2610/#2977 extraction precedent); neither is a new governance posture
**Incidents:** none — main was red ~22 min (03:50Z v4-site-gate fail → 04:12Z green on the fix commit), under the >1h bar; no auto-rollback fired, no data gap, no budget event. The five gate reds are recorded as #3477 instead, because they recur by construction rather than being an event
**Stash/hooks:** clean
**Closures:** #3473, #3474 commented · DoD: scanned 2, hits 2 — both were `no-outcome-verdict` before the (e8) comments existed; both now carry the ADR-099 `**Shipped:**`/`**Outcome:**` pair, re-scan clean
**Backlog:** Now 1 actionable in the opus lane; **NO REMEDY IN THE CORPUS** — `backlog_next.py --refill-now --lane opus` found zero startable promotions and correctly refused the 11 startable stories outside the lane (promoting one turns the count green while adding nothing this session could start). Floor NOT lowered. Later sweep — no stale issues (31 open all satisfy the contract). Filed #3476, #3477
**Alarms:** 1 flap cited — `ai-tokens-platform-daily-total` fired-and-cleared in the 72h window (#2912 detector); dated self-clearing entry added, prune on/after 2026-09-07. That flap *is* the defect #3474 closed
**CI warnings:** 1 — the `LifePlatformMonitoring` dashboard-`Tags` warning. **Not a pending deploy: it is unshippable.** Filed #3476
**Ledger:** compute-pipeline liveness heartbeat (#3473) row added

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
| `docs/SCHEMA.md:2852` (`check_doc_facts`) + `test_wiki_checkers.py` ×3 | stale genesis literal; `restart_docs_update.py` reported the file "unchanged" |
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

## Residual / next picks

- **#3390** — Day-1 runlist for cycle 16, run ON or AFTER 2026-09-04 (post-genesis by
  construction; `restart_verify.py`, the two reconcilers in order, the supersede reflex).
- **#3477** — the reset pipeline exits 0 over the doc gates CI runs; three reds recur every
  reset. Filed this session.
- **#3476** — the `LifePlatformMonitoring` dashboard-`Tags` CI warning is unshippable and
  fires on every green run. Filed this session.
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
- `not-work — standing observable`: **`compute-pipeline-stale-heartbeat` has not yet
  produced a first verdict** (`INSUFFICIENT_DATA — Unchecked: Initial alarm creation`).
  The emitter is confirmed healthy (1 datapoint/day, 10 consecutive days) so OK is a
  prediction; confirm it settled at the next session.
- `not-work — the approved plan, unchanged`: **Session U proper** (Architect ritual + the
  time-anchored batch) remains scheduled for 2026-09-08,
  `~/.claude/plans/lovely-snacking-panda.md`.
