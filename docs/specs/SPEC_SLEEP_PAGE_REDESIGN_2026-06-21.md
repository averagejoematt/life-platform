# SPEC — /evidence/sleep/ Page Redesign
**Date:** 2026-06-21 (rev. with cross-source correlation board)
**Page:** averagejoematt.com → /evidence/sleep/ — "last night, and what tonight should be."
**Source:** elite page-specific design review (sleep-medicine + circadian + thermoregulation/HRV bench, viz, product/UX), grounded in live screenshots (`qa-screenshots/evidence-sleep.png`, `-mobile.png`; NO light capture exists — verify light parity at build) + real week-one API data, plus athlete-requested cross-source overlays.

---

## 0. The one story (the spine)
The page is retrospective: it leads with last-night figures, then stages, then a physiology table, then the trend, and tucks the **circadian-compliance forecast into a bottom tile**. That's backwards. The forecast — predictive, DST-aware, act-now, four anchors — is the most distinctive asset on any of the three Evidence pages. Flip retrospective → prospective.

> **Spine: "Tonight's odds — and the night that proves the model."**

Lead with the forecast as a "tonight" gauge (four actionable anchors); demote last-night architecture/physiology to evidence beneath; TRACK the forecast (self-grading) so its prominence is earned.

## 1. Current-state findings (must fix)
- **Forecast buried as a bottom tile** → promote to hero "tonight's odds" gauge with its four anchors.
- **Last-night sleep SCORE dominates as the headline** → demote; expose its inputs or stop leading with the black box.
- **Stages-&-physiology table renders all metrics as equal** → keep the few that drive the story (efficiency, WASO, time-to-sleep).
- **Dual-device stage data (Whoop + Eight Sleep) shown but not as AGREEMENT** → add the device-agreement view.
- **No regularity/consistency view** → add it; regularity predicts more than single-night architecture.
- **No cross-source overlays** → add the confidence-graded correlation board (see §8) — the page's wow.
- **Single-night metrics implicitly framed as verdicts** → one night is noise; say so.
- **Signatures** → deploy measuring-rule tick spine + mono<->serif two-voice.
- **Keep:** last-night stage stacked bar; nightly sleep-score trend; cross-wearable reconciliation under the hood.

## 2. Page architecture (top to bottom)
Legend: **[now]** · **[needs-data]** · **[defer]**.

**§0 — Hero: tonight's odds (the forecast).** Circadian 0-100 split into FOUR anchors, each with current status + the lever to pull NOW. Two-voice. Binds `/api/circadian`. **At-risk = muted ink / low-ember, NEVER red.** **[now]**
**§1 — Last night: the evidence (demoted figures).** Score, hours, efficiency, recovery, HRV, RHR beneath the forecast as evidence. Binds `/api/sleep_detail`. **[now]**
**§2 — Dual-device stage agreement.** Whoop vs Eight Sleep per stage as a dumbbell/paired bar; gap = honest spread; "agreement, not truth." Binds dual-device stages. **[now]**
**§3 — Regularity / consistency.** Bedtime & wake consistency band/scatter + social-jet-lag readout (weekday vs weekend midpoint; empty state until a weekend). Binds onset/midpoint/consistency. **[now; jet-lag needs-data]**
**§4 — Stage composition over the week.** Stacked-composition bar per night (deep/REM/light hours); refuses <4 points. **[now]**
**§5 — Environment: bed-temp vs deep-sleep.** Eight Sleep temp overlaid with deep-sleep minutes; observation-only. Binds bed temp + deep hours. **[now, observation]**
**§6 — Recovery readout (cross-page link).** HRV/RHR/recovery framed as "what sleep defends in a deficit." **[now-ish]**
**§7 — Autonomic downshift readout.** A single "did the body downshift tonight" state from `get_autonomic_balance` (HRV + RHR + respiratory). Honest at low n because it's a STATE snapshot, not a claimed relationship. **[now]**
**§8 — Cross-source signal board (the wow).** See dedicated section below. **[scaffold now; coefficients at >=2 weeks]**
**§9 — [Coming online] Forecast self-grading.** Did high-risk-forecast nights actually score lower? **[needs ~2 weeks]**

## 3. CROSS-SOURCE SIGNAL BOARD (§8 detail — the differentiator)
A board of candidate cross-source relationships that POLICES ITS OWN CONFIDENCE. This — not the pairs themselves — is the wow: the only correlation surface that tells you when NOT to trust it.

**Honesty mechanics (hard):**
- Each card shows the pair, the **n**, the **overlap weeks**, and a **confidence tag**.
- **< 2 weeks overlap → "watching — too early": DIRECTION ONLY, no coefficient, no correlation chip.**
- **>= 2 weeks → surface the Pearson + the correlation chip**, still labeled with n and confidence.
- Thin/volatile pairs carry an explicit **"likely noise at this n"** flag.
- Powered by `get_cross_source_correlation` (Pearson + day-lag), `get_sleep_environment_analysis`, `get_decision_fatigue_signal`, `get_journal_sentiment_trajectory`, `get_jet_lag_recovery`.

**Cards, ranked (cool x honest-now):**
- **A1 — Last night sleep/recovery → today's training capacity** (LEAD: the only arrow that changes tomorrow morning). Cross-link to training. **[now, watching]**
- **A2 — Day strain → next-night deep sleep / recovery** (day-lagged; "did I earn it"). **[now, watching]**
- **A3 — Bed temp → deep sleep** (mechanistic; = §5). **[now]**
- **A4 — Eating-window / last-meal time → sleep** (reuse nutrition's 19:15). **[now, watching]**
- **B1 — Decision fatigue (Todoist load) → wind-down/sleep** (no app has this). **[now, watching]**
- **B2 — Journal mood → sleep** (bidirectional). **[needs active journaling]**
- **B3 — Day-of-week best duration** (legible; n=1/day at week one = noise). **[needs ~4 weeks]**
- **C1 — Sleep vs weight** (athlete-requested; HIGHEST false-positive risk in a water-weight cut — show last, label loudest, coefficient withheld until well past the early water phase). **[defer coefficient; scaffold labeled]**

## 4. Features / interactions
- The four forecast anchors are tappable → "what to do now."
- Two-voice on the hero and the dual-device view.
- Correlation cards expand to show n / overlap / the day-lag used.
- Honest empty states everywhere thin.

## 5. Cut list
- Last-night SCORE as dominating headline → demote.
- Dense all-equal physiology table → keep the few story-driving metrics.
- Any single-night metric framed as a verdict.
- Forecast rendered as red/alarm → muted-ink at-risk.
- Any correlation coefficient shown under 2 weeks of overlap.

## 6. Data-capture backlog (ranked)
1. **Caffeine + alcohol timing** — biggest modifiable levers; feed forecast anchors + the board. Privacy-tier.
2. **Subjective "how rested" 1-5** — ground truth wearables miss.
3. **Last-meal time** — already on nutrition page; free cross-link.
4. **Light exposure (AM/PM)** — circadian anchor; capture honestly (screen-time proxy, flagged).

## 7. Must-honor constraints
- **Design system:** Fraunces, IBM Plex Mono, ONE accent ember `#DD7A37`; down = muted ink, **never red**. First-class dark AND light (verify light — no light screenshot yet). Reuse the inline-SVG kit (incl. the correlation chip for >=2-week pairs). Deploy tick spine + two-voice.
- **Ember semantics:** higher deep/recovery = good, RHR-down = good, bed-temp is optimal-band (not monotonic). Ember = "on track / protective," muted = "at risk / off." Forecast at-risk stays muted, never an alarm.
- **Honesty / rigor (Henning standard):** n=1, correlative only, no causal language, **no Pearson/correlation chip until >=2 weeks overlap**; one night is never a verdict; thin pairs flagged "likely noise"; wearable stages are estimates not PSG. Down nights shown. Charts refuse <4 points.
- **Audience/privacy:** me-first; caffeine/alcohol + any behavioral inputs privacy-tier.
