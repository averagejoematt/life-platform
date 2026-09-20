# Foundation — Pull — 4 — 14  *(held flat; first routine red-teamed by the critics, #3752)*

- **Phase / type / tier:** Foundation / Pull / Tier 1
- **Hevy routine_id:** 720eee53-8e43-49c7-9b56-25e991b5cdea (platform routine 73bc228c202b7e65b09975aff1a7fa57)
- **Target date:** 2026-09-20
- **Status:** committed (2026-09-19 19:18 PT), folder Pull (3087800), readback-verified
- **Context:** day 14 of a training streak (every day since 09-07), readiness GREEN 80 on the
  night before (Whoop recovery 98, HRV 10% above baseline), ACWR 1.24 safe, TSB −62 (duration
  proxy), aggressive deficit (~1,470 kcal/day logged vs a 5,059 kcal TDEE estimate — see #3931 on
  that estimate), protein under the 180 g floor on 4 of the 5 logged trailing days, rate 3.7 lb/wk
  ABOVE the 1.6–3.2 lb/wk band. Last Pull 09-16: lat pulldown 140×10×4 (RPE 8–9), close-grip 120×10×3,
  DB row 80×8×4, straight-arm 57.5×12×3, face pull 57.5–65×12×3, hammer curl 22.5×12×3, 60 min bike.
  Muscle-volume week: back 20 sets (approaching MRV 25), push:pull 1.73 → the pull day is owed.

**Red team (stage 2 of `plan_next_session`, 4 separate Haiku calls, disjoint packets):**

| Critic | Verdict | Number it argued from |
|---|---|---|
| muscle-defense | CHANGE → hold volume (no growth this week) | `protein_days_missed_7d = 4` (floor 180 g, threshold 3, provenance owner); anchor drop 0.0% on lat pulldown 140 / close-grip 120 |
| joints/tendons | CHANGE → `session.total_sets` 22 → 18 (applied, round-robin from the largest exercise) | `consecutive_training_days = 13`; no pain flag on any of the 8 movements (note layer *degraded*: cap_exceeded, deterministic pain lexicon still ran) |
| rate-advocate | APPROVE | tripwires 2 clear / 1 tripped / 2 unreadable; walking 5.09 hr/wk Strava-only (#3930); rate 3.7 ABOVE the 3.2 top; 7 lifts in 7d |
| blueprint historian | APPROVE | band 300–309, **7 lb lighter — not a mirror**; 2 wk in the current block so the band figure is descriptive; attested overlay 0.28 hr/wk **OWNER-ATTESTED, NOT MEASURED** (the measured figure is a floor, #3717) |

Intake is NOT comparable to the prior cut (MacroFactor begins 2025-11-24, ADR-104).

| # | Exercise | Sets × Reps | Load | Rest | Note (intent) |
|---|----------|-------------|------|------|----------------|
| 1 | Lat Pulldown (Cable) | 3 × 10 *(was 4)* | 140 lb | 120s | Anchor, held. Cap RPE 8.5 (set 4 hit 9 on 09-16). GREEN: +1 rep on the last set if 1–2 moved at ≤8. RED: drop to 125. Carries the RED TEAM block on its notes (#3937). |
| 2 | Lat Pulldown - Close Grip (Cable) | 3 × 10 | 120 lb | 90s | Elbows to hips, no lean-back. GREEN: rest 75s. RED: 2 sets. |
| 3 | Dumbbell Row | 3 × 8 *(was 4)* | 80 lb | 120s | Held. One-count pause at the top is the progression, not load. GREEN: rest 105s. RED: 70 lb. |
| 4 | Straight Arm Lat Pulldown (Cable) | 3 × 12 | 57.5 lb | 75s | 3 s eccentric. RED: 2 sets. |
| 5 | Face Pull | 2 × 12 *(was 3)* | 57.5 lb | 60s | 65 only if set 1 was ≤8 (GREEN). Pause, external rotation at the end. |
| 6 | Hammer Curl (Dumbbell) | 2 × 12 *(was 3)* | 22.5 lb | 60s | Stop at 8.5 (set 3 was 9.5 last time). |
| 7 | Cycling | 45 min | Z2, L10–12 | — | Steady, HR ~115–120 (the band reference's 119 bpm). Builds the base — not a flush. RED: 30 min L8. Treadmill 3 mph / 0.5% if the bikes are taken. |
| 8 | Stretching | 15 min | — | — | Lats, thoracic, hips. |

**Progression levers next time:** load is frozen until protein is back over 180 g on most days
(muscle-defense) and the streak breaks or a rest day lands (joints/tendons); density (rest) and
pause/tempo carry the week. Reopen a 4th set on the two anchors when both critics approve.

**Changelog**
- 2026-09-19 — created & committed. First routine through stage 2: v2 trimmed the cut out of the
  last two accessories (3 → 1 each) — fixed the same night (#3936) to round-robin from the largest
  exercise, re-drafted, re-run (same four verdicts), committed as v5. Readback from Hevy found the
  routine-level notes field is not returned by the API (#3938); the verdict block moved onto
  exercise 1's notes (#3937).
