# Handover — Session Z: plan from the campaign that worked (2026-09-08 ~14:00 PT → 2026-09-08 ~18:15 PT)

**Driver:** Opus 5 (1M). **Owner instruction:** started as "evaluate the Hevy handoff for
working this session", became "I authorize you to do everything this session" once the
work turned out to be the training planner's blindness rather than the parked Hevy bugs.

---

## The through-line

The owner asked, from the gym, why the planner guessed a load for a lift he had done 80
times and why it hedged about target heart rate. Both had the same shape and it was not
prompting: **every input the night-before authoring path reads is a recent window.** The
`daily-debrief` skill pulls 14 tools; not one carries a prior campaign, and not one
carries a heart rate. An order-taker is the only thing that architecture can produce.

Measured, live, before any change:

```
distinct movements ever logged   537      visible to the planner    48
movements with history the 180-day window could not see            489
  (Deadlift, 80 sessions, rendered as "no history")

trailing 30d      +1.62 lb/wk   2.51 walk mi/wk   1.42 hr/wk   0.70 lift d/wk
the 2024-25 cut, its first 31d  -5.10 lb/wk  21.50 mi/wk  14.51 hr/wk  4.06 d/wk
```

Seven stories built on `feat/campaign-reference-3708-3709` (PR #3713). **Nothing is
merged and nothing is deployed** — the whole branch is correct code that nothing
consults yet.

## What shipped to the branch (PR #3713, 7 stories, 8 commits)

- **#3708** — the exercise-history window reaches the prior campaign. Live after: 337
  cues render, 293 carrying bodyweight context (`Last: 84kg 8/8/8/8 (Nov 2025, at 263 lb)`).
  The floor is enforced in `routine_generator`, NOT in `training_week.json` — that config
  is not staged into the bundle, so the runtime reads S3 and a repo-side fix would have
  been inert (#3675's trap, #3671's lesson).
- **#3709** — `training_reference` v2: all-history bands, nearest-band resolution with
  `band_distance_lb`, per-band `n_days`/`n_weighins`/`n_eff`. Bands are summed over
  **in-band days**, not `min..max` — the owner crosses each band repeatedly across 14
  years, so the naive window made every band a lifetime average wearing a band's name.
- **#3710/#3711** — the `prescription` and `campaign` views on `get_benchmark`, plus the
  `daily-debrief` skill wired to read them. `get_benchmark` had existed since BENCH-1
  with nothing in the training path ever calling it.
- **#3716** — cycling was dropped from every covariate (`Ride`/`VirtualRide` → `None`).
  394 rides never reached a single band. At 230-239 lb cycling is **62% of cardio hours**;
  the old reference said 3.77 hr/wk against a true 9.92. Invisible above 300 lb (0-6%),
  which is why it read plausibly exactly where he is standing.
- **#3717** — the attestation layer. The owner asked whether we could imply the
  uncaptured post-lift cardio or backfill it onto old Hevy workouts. **Rejected**: a
  synthetic row in `SOURCE#hevy` is indistinguishable from a measured one and `raw/*` is
  delete-protected. Shipped a declared layer that never merges into a measured field,
  carries a low/typical/high range and `OWNER-ATTESTED, NOT MEASURED`.
- **#3718** — a commit verifies by readback (template ids + `updated_at` moved) before it
  may say "committed"; `hevy_folder_id` recorded from the readback, never from intent;
  `create_missing` defaults to **false**.

**Evidence tiers** came from actual research, not a chosen number: the volume floor is 21
effective days — the lower bound of the 21-28d chronic window from the acute:chronic
workload literature, already sanctioned here via the Gabbett ACWR zones. Floors apply to
`n_eff` from `stats_core`, computed per contiguous visit and summed. The result sits on
the line and is honest: the 300-309 proven band nearest 327 lb is 24 raw days but
**n_eff 19.5** — just under. So the platform may describe that period and may not
prescribe from it.

## What was found by RUNNING it, not by reading it

Four defects shipped and fixed inside the session, each silent:

1. A **v1 `training_reference`** made the prescription view report "no comparable period"
   — which reads as a finding about his history and was an undeployed Lambda.
   `reference_schema` now separates the two.
2. The campaign signal printed **"97% of the comparable losing period"** from a 3-day
   extrapolation, sitting directly beneath its own `rates_are_artifacts: True`. The flag
   existed and the headline ignored it.
3. The proven curve used an **exact-match** date lookup for the window boundary. There is
   no weigh-in on 2024-09-05, so it produced **zero curve points silently**.
4. `_verify_commit_landed` had `wc` out of scope, and the fail-soft `except` swallowed the
   `NameError` — **every commit in production would have reported "unverified."** Found
   only by testing the verifier directly; the older fixtures patch it out.

## Gotchas worth carrying

- **A guard satisfied by a token is not a guard.** `test_wallclock_fixture_bombs_2376.py`
  correctly caught the new test file, but it is a **text matcher** — the first mutation
  stayed green purely because the word "frozen" survived in a test *name*. My own first
  version of the attestation write-guard had the same flaw: it grepped for `SOURCE#hevy`
  and matched the module's own docstring explaining why it doesn't write there. Both now
  parse AST.
- **Obeying one gate can red another.** `mcp/registry.py` was at its #1665 ceiling, whose
  sanctioned remedy is to extract to a sibling and reference it — which broke
  `generate_mcp_tool_catalog.py` (it `literal_eval`s the schema and hit a bare `Name`).
  Fixed by teaching the generator to resolve `mcp/tools_*.py` constants.
- **Two guards wanted the same thing and both were right.** The Hevy-isolation guard and
  the module-size guard both fired on `_verify_commit_landed` living in the tool layer.
  Moving it to `hevy_write_client.verify_commit_landed` satisfied both and is better
  design — the client that performs the write owns "did this write land".
- **Run the premerge lane locally BEFORE pushing.** The first push skipped it and CI found
  the time-bomb guard 15 minutes later; every push since ran it first and matched CI exactly.

## Live corrections made to the owner mid-session

- Told him tomorrow's Legs routine did not exist (true at 23:29Z — June content,
  `updated_at` unmoved). **Corrected at 23:40Z**: a later attempt landed at 23:38:39Z. The
  P0 framing was withdrawn and #3718 downgraded to P1. The folder half stayed false and
  was real: it was in Archive, not Legs.
- Corrected the desktop session's claim that the routine "should still be sitting in Legs
  from the original push" — verified live it was not.
- Checked his recollection of daily recumbent-bike work: **four hypotheses tested and
  rejected** (Cross Training is the lift itself, residual 0 min in every paired case;
  `Sport_128` is 20-min median with no HR; 1 of 486 lifts has a session running past it).
  It is absent, not mislabelled.

**Main:** green (68a5954f) — HEAD minted no CI/CD run of its own: bot-push-no-dispatch (expected, not a swallow)
**Build beat:** none — PR #3713 is open and unmerged; nothing from this session is live, and a beat narrates shipped-and-deployed work only
**Docs:** none needed — no shipped change invalidated a wiki page; the branch's own docs (MCP catalog, platform model) regenerate with it and are committed on the branch
**Decisions:** none needed — the evidence-floor and attestation rulings are recorded in-code with their provenance and on #3717; neither changes platform governance, and the ADR-155 question they surfaced is #3719's for the owner to rule on
**Incidents:** none — the Hevy commit misreport is a product defect tracked on #3718, not an availability/rollback/data-loss event; main never went red this session
**Stash/hooks:** clean
**Closures:** none — no issues closed this session · DoD: scanned 0, hits 0 — nothing closed to audit
**Backlog:** Now live at 12 actionable opus-lane stories after this session's 11 filings; no promotion needed and no stale Later issues surfaced
**Alarms:** 1 flap uncited — named: `commitments-ungraded` (fired and cleared inside the 72h window; not investigated this session, no standing red)
**CI warnings:** 7 — 5 are the #3640 playwright-skip notices (expected on a non-chromium runner, no action); the Unit Tests duration budget (2622s vs 1950s) and the coverage floor drift (74% vs 84.2%) are both known recurring classes with their own records and are deliberately not re-triaged in a wrap that shipped no CI change
**Ledger:** none — no standing machinery shipped; the branch adds no scheduled job, no alarm, no watcher and no new gate (the two new tests ride the existing premerge lane)

## Residual / next picks

- **#3719 — the live one.** `/api/physical_overview` serves the full tape-measurement
  panel publicly with no `field_tiers` entry and no consent stamp, while adjacent DEXA
  data carries `TIER_OWNER_PUBLISHED` with a dated decision. Owner must rule: publish
  deliberately, or restrict. Blocks the progress-photo plan.
- **#3713** — merge and deploy. Local premerge green (10,630 passed); CI re-running at wrap.
  Deploy is `episode-detect` + the MCP bundle, then invoke to write the v2 reference, then
  verify the prescription view returns live instead of `reference_schema: 1`. Deliberately
  NOT deployed unattended tonight: it changes tomorrow morning's authoring path.
- **#3714** — adherence is blind to the `rpe` it already stores; both cycle-17 sessions
  reported 100% while he hit RPE 10.0 and 9.5. The strongest independent next pick.
- **#3715** — `TRAINING_CONTEXT.md` does not exist anywhere; injury constraints live only
  in session context.
- **#3712** — the graded-forecast loop; correctly last, it depends on #3710/#3711 being live.
- **#3716** — owner ruling needed on whether Whoop `Cross Training` is the recumbent-bike work.
- **#3717** — attestation is active on the confirmed window; extending its end date past
  2025-04-30 needs a date from the owner.
- Progress-photo plan approved and saved at `~/.claude/plans/cozy-doodling-cookie.md` —
  not-work — blocked on #3719, and the owner may still decide it is not worth building.
- The pre-existing backlog corpus carries 61 hygiene violations (52 `set_section`) on
  issues this session did not touch — not-work — out of scope for this wrap, and the gate
  was red on them before it started.
