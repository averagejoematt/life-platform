# Lower — 2026-09-28 (Lower-volume, week 1 · session 3 of 4)  *(bike, not treadmill, after a 4.4 h walking weekend)*

- **Phase / type / tier:** Block 1 / Lower (volume) / wake-tier table on exercise 1
- **Hevy routine_id:** 9347cff2-0fca-4cab-a1fc-b89898851a1b (platform routine f905fdc257cb45c03a1c3f98f050d095, v3)
- **Target date:** 2026-09-28
- **Status:** committed (pushed to Hevy 2026-09-27 19:13 PT, folder 3744982), `created_by chat`, `source_action draft_custom`. The loads and sets were set by hand in the chat; the generator did NOT compute them.
- **Context:** the nightly pre-draft (`4300a686…`, 02:00Z) programmed 60 min of incline treadmill after trap bar + squat. Its only aerobic input was a 7-day walking total that ended at target−2. It never saw Sunday: 4.4 h / 13.4 mi of outdoor walking over Sat–Sun, both walks over the 75-min and HR-105 redlines. The chat swapped the cardio to the recumbent bike and held the sets. The engine gaps are filed as #4387 (recent aerobic load) and #4388 (entry-ramp base). Correction `CORRECTION#2026-09-27#5a60fd05`.

**Red team (stage 2, critics@1.5.0, 4 critics, 2026-09-28):**

| Critic | Verdict | Number it argued from |
|---|---|---|
| muscle-defense | CHANGE → hold (no growth this week) | `protein_days_missed_7d = 5` (floor 180 g, threshold 3, provenance owner) |
| joints/tendons | APPROVE | nothing in its packet crosses a stated threshold. It could not see the weekend walks (#4387) |
| rate-advocate | APPROVE | nothing crosses a stated threshold |
| blueprint historian | APPROVE | nothing crosses a stated threshold |

| # | Exercise | Sets × Reps | Load | Rest | Note (intent) |
|---|----------|-------------|------|------|----------------|
| 1 | Trap Bar Deadlift | 2 × 8–10 | 122 lb (55.5 kg) | 120s | First exposure in 325 days, a re-grooving session. Cap RPE 6–7, 3+ reps in reserve every set. Load held at the engine floor. Carries the wake-tier table and the RED TEAM block. |
| 2 | Squat (Barbell) | 3 × 8–12 | 135 lb (61.2 kg) | 120s | 60% of band e1RM (103 kg from 195×5 @ 7.5 on 09-24). Leave 1–3 in the tank. Volume day: no top set, no ramp to heavy. |
| 3 | Seated Leg Curl | 2 × 8–15 | 75 lb | 90s | 60% of band e1RM (90×12 on 09-24). RIR 1–2. |
| 4 | Calf Press (on leg press) | 2 × 8–15 | 290 lb | 90s | 60% of band e1RM (320×15 on 09-24). RIR 1–2. |
| 5 | Machine Crunch | 2 × 8–15 | feeler | 90s | No history: pick the load that gives 12 at RIR 2 on set 1 and log it. Flexion; Saturday's core was anti-rotation and carries. |
| 6 | Cycling (recumbent) | 60 min | easy, HR < 105 | — | Last: level 15, 10.70 mi in 45:00 on 09-21; L9–10 is his "easy". RECUMBENT, not treadmill: 4.4 h / 13.4 mi walked Sat–Sun, and the legs just did trap bar + squat. Conversational. Counts toward the walking floor. |

**Wake tier** (use the LOWER of Whoop and feel; feel only downgrades):
- 🟢 67–100: everything as written + 60 min bike.
- 🟡 34–66: reps at the bottom of each range, bike 45.
- 🔴 1–33: trap bar + squat only, 2 sets each, RPE 6; skip accessories; 30 min easy bike.

**Progression levers next time:** load and sets are held while protein is under 180 g on most days (muscle-defense). The trap bar moves off the floor only after this session logs clean at RPE ≤ 7. Cardio modality follows the last 48 h of weight-bearing hours (#4387), not the previous session's block.

**Changelog**
- 2026-09-27: created in chat over the nightly pre-draft (v2 → v3), committed and pushed to Hevy 19:13 PT. The squat entry uses 60% of band e1RM (135 lb), not the engine's 60%-of-set-weight floor (118 lb); that mismatch is #4388.
