# Character Math Audit — 2026-07

> **Status:** point-in-time review (audit record, not living doc) · **Owner:** Matthew · **Produced:** 2026-07-11 overnight sweep
> **Method:** 2-lens deep read of `lambdas/character_engine.py` (v1.3.0) + `lambdas/compute/character_sheet_lambda.py` + `config/character_sheet.json`, plus a 420-day simulation harness driving the real engine (`scripts/character_sim_year.py`), followed by independent adversarial verification — every number below was reproduced twice (finder + verifier) against the live config.
> **Question asked:** is growth AND retraction defensible over a year-plus, multi-cycle project, across the pillars?
> **Companions:** `docs/engines/CHARACTER.md` (the formulas), `docs/specs/SPEC_CHARACTER_ENGINE_v1.1.0.md`, `docs/reviews/REVIEW_CHARACTER_LEVELING_2026-03-30.md` (F-01…F-15), ADR-104 (behavioral absence), #913/#919 (atrophy/debt/up-gate).

## Verdict table

| # | Mechanic | Verdict | Issue |
|---|---|---|---|
| 1 | Up-gate vs the confidence-blend floor (climb-during-darkness returns ~day 15–17) | **needs-fix, critical** | #957 |
| 2 | Up-gate vs cross-pillar-boosted targets (permanent freeze of boosted pillars) | **needs-fix, critical** | #954 (ships now) |
| 3 | XP demotion buffer `xp_total % 100` (wraps upward as XP declines) | **needs-fix, high** | #954 (ships now) |
| 4 | XP zero-point at raw 80 (visible-debt spiral under realistic-good living) | **needs-fix, high** | #958 |
| 5 | XP from uninstrumented pillars (phantom permanent −100 debt) | **needs-fix, medium** | #964 |
| 6 | Post-engine mutations (food-delivery ×, challenge +XP) bypass all gates | **needs-fix, medium** | #961 |
| 7 | Dead engine inputs (vice_streaks, buddy_freshness_days, streak_all_above_30th, weekend_weekday_ratio) | **needs-fix, medium** | #962 |
| 8 | 30-day dark ≈ 2 headline levels (atrophy blind spot on device pillars) | **design-question** | #959 |
| 9 | Elite tier unreachable at any horizon (L48 after 420 days of raw ~90) | **design-question** | #960 |
| 10 | Cross-pillar conditions evaluate EMA scores, not levels ("meta-achievement" fires week 1) | **design-question** | #963 |
| 11 | Pre-genesis pilot records chain into Day-1 compute | **needs-fix, medium** | #947 (ships now) |
| 12 | Source wiring: hevy/reading/todoist absent — movement is blind to lifting | **design-question** | #965 |
| — | ADR-104 behavioral-absence semantics; sick-day freeze; EMA anti-flip-flop streaks/steps; coverage-hold; deterministic mood ladder | **defensible** | — |

Epic: **#956 Character math v2**. The two gate-arithmetic bugs (#954) and the pilot-chaining filter (#947) ship in tonight's wave; everything else is a scored backlog story because it changes the *model*, which is Matthew's call.

## What the year-scale simulation showed

Five scenarios × 420 days against the real engine + live config (`scripts/character_sim_year.py`; re-run to reproduce):

- **(a) Steady-good, raw ~75:** healthy climb, but metabolic freezes at L1 forever once cross-pillar boosts engage (mechanic 2): boosts inflate its target to ~89 while achievable raw is ~76, so `day_supports_up` never passes again. The "bonus" is a permanent climb blocker.
- **(a2) Sustained excellence, raw ~90:** L10 at day 51, L20 at 126, L30 at 212, L40 at 305, **L48 at day 420** — Elite (81+) is beyond any realistic horizon (mechanic 9). Structural ceiling: with relationships (weight .07) frozen at L1 by design (#747) and metabolic (weight .12) frozen by mechanic 2, max character level = floor(81.19) = 81 — Elite requires literally every other pillar at exactly 100.
- **(b) Oscillator (2 good weeks / 1 bad, mean raw ~65):** reaches **L62 by day 420 — beating the steady-75 performer (L49)** because bad weeks toggle the cross-pillar boosts off and let frozen pillars climb. A perverse inversion: inconsistency out-levels consistency. Also ends at 0 XP / 627 debt (mechanic 4) — a Mastery-tier character wearing a maxed debt badge.
- **(c) Strong start → 30-day total dark at day 90 → recovery:** headline level drops only 19→17 during the silent month, recovers in 2 days, +6 above pre-dark within ~11 (mechanic 8). The honesty is carried by secondary surfaces (mood `dormant` all 30 days, level_score 74→13, atrophy ×0.63, +~250 debt) — the *headline* barely records it. Gates that throttle the drop: streak_below resets after every level_down (each next drop needs a fresh 7-day streak), the XP-buffer modulo gate, and coverage-hold freezing metabolic/consistency in both directions during darkness.
- **(e) Slow improver (raw 45→70 linear):** hits the ALL-pillar debt cap (700) by day 200 and still shows **0 XP / ~700 debt at day 420 despite reaching L57** (mechanic 4). The XP earn/decay calibration (net positive only at raw ≥ 80) predates #913; visible debt made it public.

**The two critical dishonesties are both up-gate arithmetic, not the model:**
1. *Climb-during-darkness is back* (mechanic 1): in total silence a behavioral pillar's blended raw floors at ~15.6 (coverage 0.55 ⇒ confidence 0.688 ⇒ 50-blend floor), atrophy pins level_score to that same floor, EMA converges down to it, and `round(15.6)=16 ≥ target 16` passes **every dark day**. A fresh cycle-5 character that never logs anything reaches **L16 with 12 level-up celebrations in 60 days while mood reads `dormant`**. This is the same class as the 8→13 bug the 2026-07-10 truth audit caught; the #919 fix moved the boundary from day 1 to ~day 15, it didn't close it. The existing regression test guards exactly 14 dark days — the failure begins at ~15–17.
2. *Boost-frozen pillars* (mechanic 2, above).

## Where the model IS defensible

- **Behavioral-absence semantics (ADR-104)** hold everywhere inside the engine: unlogged habits score 0 at full weight, device gaps drop out of the weight sum, zero-data pillars are flagged `not_instrumented` and level-frozen.
- **The EMA + tier-scaled streaks + step bands** anti-flip-flop machinery works as designed — the oscillator does not flip-flop; post-reset convergence via step bands is fast without being jumpy.
- **Deterministic mood** (ADR-105) fired correctly in every scenario (dormant through dark stretches, no thriving without trend + composite).
- **Sick-day freeze** and coverage-hold behave exactly per spec in simulation.

## Recommendations (in ranked order, for the epic)

1. **Fix the gate arithmetic now** (#954, shipping): up-gate compares against unboosted targets; buffer monotone under decline. And **close the darkness loophole** (#957): a dark-presence day must never support a level-up — gate the up-streak on presence/coverage, or evaluate the gate against the unblended raw (0 in silence). These three restore "levels never rise on silence" — the property the site publicly stakes its honesty on.
2. **Recalibrate the XP economy** (#958/#964): decide XP's meaning (within-level progress vs lifetime score), set the zero-point near "a decent day" (raw ~60–65), gate earn/decay on instrumentation, and make debt payable by realistic living. Today XP is a number the site displays but the model barely uses — either make it meaningful or stop displaying it prominently.
3. **Decide the retraction story** (#959): should a silent month cost the *headline* level more than ~2? Options: let atrophy reach device pillars at reduced rate, weight the overall level by presence, or accept secondary-surface honesty and say so in the /method/ explainer.
4. **Make the ceiling honest** (#960): either retune so Elite is reachable under sustained excellence (~1.5–2 yr), or publish the actual math in the character explainer ("Elite is a multi-year asymptote") — the tier ladder currently implies a reachable rung.
5. **Close the bypasses** (#961, #962, #963) and **wire or delete dead inputs** — same disease as the removed body-fat component (#486/B-3 precedent).
6. **Source wiring** (#965): movement blind to lifting is the biggest experiential gap for cycle 5 (Hevy is a primary cycle-5 instrument). Design the components with volume-gaming resistance (ADR-104 behavioral class) before wiring anything.

## Reproduction

```bash
python3 scripts/character_sim_year.py            # 5 scenarios × 420 days + probes
python3 -m pytest tests/test_character_engine.py tests/test_character_neglect.py -q
```
Every claim above carries its file:line in the linked issues (#954, #956–#965, #947).
