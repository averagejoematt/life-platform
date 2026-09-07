# Foundation — Push — W1  *(block restart, day 1)*

- **Phase / type / tier:** Foundation / Upper Push (WS4SB hi-rep day) / Tier 1
- **Hevy routine_id:** 7f906e65-3362-4fef-bd86-52fbbf665eb3
- **Platform routine_id:** 947454183948792a30a5207ad212aca2
- **Target date:** 2026-09-08
- **Status:** committed
- **Rendered title:** `Foundation - Push - 1 - 1` — **renamed by hand in the Hevy app.**
  The compiler auto-rendered `Foundation - Push - 3 - 11`; its counter derives from performed
  history, which still includes the 484-workout backfill from the 2024-25 cut, so it read week 3 /
  session 11 on what is day 1 of the block.
  ⚠ A `force_title=true` passed on **commit** did NOT work and silently kept the convention title.
  Root cause: `mcp/tools_hevy_routine.py:785` reads `force_title` at DRAFT time and stores it on
  `ir.inputs_snapshot`; `_resolve_title_inputs()` (line 848) then checks the snapshot, never the
  commit args. **Correct usage: pass `force_title` + `title` on `draft_custom`, not on `commit`.**
  The tool description is misleading on this and should be corrected.
- **Hevy folder:** landed in ROOT, not `Push`. Moved by hand. Two stacked defects:
  (1) `folder_id` is create-only in Hevy and `to_update_body` omits it (`hevy_compiler.py:219`), so
  no API call can ever move an existing routine — dragging is the only remedy after the fact;
  (2) on create, `_ensure_folder()` (`tools_hevy_routine.py:90`) swallows every exception and
  returns None so the commit proceeds unfoldered (`# noqa: BLE001 - never block a commit on folder
  I/O`) — a permanent failure that never surfaces. Unconfirmed which path fires: `list_folders()`
  returning a shape the line-101 parser misses (then attempting a duplicate create), or a 401/403
  on the folder endpoints. Diagnostic: log the raw keys from `list_folders()`.
  Note: `dry_run` showing `folder_id: null` is expected, NOT the bug — `_ensure_folder` runs only
  on the commit path.
- **Bodyweight at authoring:** 327.3 lb (Withings, 2026-09-06). Run gate (~240 lb) firmly closed —
  no running, plyo or rope this tier.
- **Context:** athlete-stated day 1 after a long inconsistent stretch. Only session on record since
  23 Jun is 2026-09-03 (ad-hoc, push-dominant: bench to 205x5, front/lateral raise, cable fly, two
  lat pulldown variants). Loads here are anchored to that bench, NOT to bodyweight. Session 1 of a
  block → no failure sets on any recovery branch (TRAINING_CALIBRATION §4 "NEVER").

## Data caveats at authoring time

Freshness reported green on 11 of 14 sources, but green is a high-water mark and hid a near-total
history gap. Verified by direct read, not accepted from the tool:

| Source | State |
|---|---|
| Hevy | 1 normalised session Jul 1 – Sep 6. Raw S3 = 484 objects, but nothing ingested between 05 Jul and 03 Sep |
| Strava | 3 activities in 30 days, all 2026-09-06 (5.33 mi, 127 min, 100% Zone 2, avg HR 111) |
| Apple Health | 1 day of step data in 20 (06 Sep, 9,653 steps) |
| Withings | 1 weigh-in; `journey_start_date` reset to 2026-09-06 |
| MacroFactor | freshness fresh through 06 Sep, but `get_nutrition` returns "No data" for 16 Aug – 05 Sep — **unresolved contradiction** |
| `get_acwr_status` | returns "No ACWR data found" on 09-05/06/07; a DynamoDB read of `USER#matthew#SOURCE#computed_metrics` for 2026-09-07 also came back empty. Athlete reports 0.929 on full 7/7 and 28/28 coverage from another surface — **tool/telemetry discrepancy, unresolved** |
| `get_muscle_volume` | returns `{}` and self-flags "do not author off this read until it clears" |
| training coach thread | 0 entries — no continuity available |

**ACWR interpretation note (recorded so it isn't re-litigated):** Whoop ACWR is cardiac strain,
acute-over-chronic. Near 1.0 with both windows low is the signature of low consistent load, not of
headroom. It does not license added volume. Retained strength (205x5) is the thing that does.

| # | Exercise | Sets × Reps | Load | Rest | Note (intent) |
|---|----------|-------------|------|------|----------------|
| 0 | *(warm-up, in session note)* | 10 min | — | — | Easy recumbent bike + band pull-aparts before the bench ramp. |
| 1 | Bench Press (Barbell) | ramp 45×10, 95×5, 115×3 → 3 warm-up sets, then 4 × 8 | 155 lb → climb 165–175 | 150s | PRIMARY. Target 3 RIR. Performance-gated: climb if set 1 moves at 4+ RIR. 205x5 e1RM ≈ 230 → 8 @ 3 RIR ≈ 165, so 155 is a deliberate on-ramp with an open ceiling. Elbows ~45°, 2s eccentric. |
| 2 | Incline Bench Press (Dumbbell) | 3 × 10 | 50 lb *(feeler)* | 120s | Upper chest the flat bench under-hits. DBs give the shoulder a free path — kinder than a 2nd barbell press on day 1. 2s down, no hard lockout. 3 RIR. |
| 3 | Shoulder Press (Dumbbell), seated | 3 × 10 | 40 lb *(feeler)* | 90s | Vertical press — 03 Sep had raises but zero overhead pressing. Back pad supported = no stability tax at current bodyweight. Ribs down, full lockout, 2s lower. 3 RIR. |
| 4 | Cable Fly Crossovers | 3 × 12 | 25 lb | 75s | Stretch-biased. Own the bottom, 1s pause at length, 1s squeeze top. **Progress via ROM, not load.** 4 RIR. |
| 5 | Lateral Raise (Dumbbell) | 3 × 15 | 15 lb | 60s | Strict, lead the elbows, 2s lower, no swing. Pump not grind. 4+ RIR. Held at Saturday's load; 3 sets not 4 because press volume is higher. |
| 6 | Triceps Pushdown | 3 × 12 | 50 lb *(feeler)* | 60s | No direct triceps on 03 Sep. Elbows pinned and staying pinned, full lockout, 1s squeeze. 2–3 RIR last set. Rest = doorway pec stretch / shoulder dislocate. |
| 7 | Cycling (RECUMBENT) | 30 min | — | — | INTENT: **Z2 steady** — not intervals, not a flush. One resistance level held 30 min, HR 110–128 (measured Z2 band). Drop a level if HR drifts past 128. BUILDS: aerobic base / mitochondrial density; closes the Z2 gap (127 min logged vs 150 target). **Not the upright, not Zwift** — saddle tolerance at current bodyweight. |
| 8 | Cable Pallof Press | 3 × 12 / side | 30 lb | 45s | STANDING anti-rotation core — ab-spasm safe, no floor compression. Press from sternum, 2s hold at extension, ribs down, hips square. Finisher-frequency checked: 03 Sep had zero core/carry, so this slot is clean. |
| 9 | Stretching | 10 min | — | — | Pliability flow, biased to t-spine / pecs / shoulders + hips post-bike. Feeds the daily stretch habit (30+ wk streak last cut). |

**Recovery branches (authored tier-agnostic — he trains 5am with no chance to adjust).**
Use the LOWER of (Whoop band, how you feel); feel only downgrades.
- 🟢 **GREEN 67–100:** bench climbs toward 175 if set 1 is 4+ RIR; last set of incline + pushdown to
  1–2 RIR; bike 35 min. **Ceiling still excludes failure sets** — day 1 of the block.
- 🟡 **YELLOW 34–66:** exactly as written. The default with no signal.
- 🔴 **RED 1–33:** bench 3×8 @135, cut the DB shoulder press, cable fly to 2 sets, bike 25 min easy.
  Properly wrecked: bike 30 min Z2 + the stretch and walk out — that still counts.

**Volume:** 19 working sets, ~110 min. Compiler warned 27 total sets vs its 25 ceiling; allowed
deliberately — his proven cut ran ~28 sets/session (PROVEN_BLUEPRINT).

**Progression levers next time:** bench load is performance-gated off what today actually moves;
trim rest on the accessory block before adding load; nudge Z2 duration toward the 150 min/wk target.
Next push should undulate to the WS4SB **lo-rep** day (5s), not repeat 8s.

**Standing note — the walking base outranks this session.** At 327 lb the blueprint band is ~10
walks/wk, ~8.5 hr. One logged day (5.3 mi, 06 Sep) is the entire Strava record for the month.
Closing that gap is the higher-leverage move than any lift programming here.

**Prediction (low confidence — thin data):** 155×8 lands at ≥4 RIR and he climbs to 165–175 within
the session. If it doesn't, the 03 Sep 205x5 was closer to a true max than the ramp implied, and the
next push day should start lower, not higher.

**Changelog**
- 2026-09-08 — created & committed (block restart, day 1; push chosen by athlete).
