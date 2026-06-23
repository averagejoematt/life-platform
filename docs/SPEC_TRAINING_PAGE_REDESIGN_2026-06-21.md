# SPEC — /evidence/training/ Page Redesign
**Date:** 2026-06-21 (rev. with athlete additions)
**Page:** averagejoematt.com → /evidence/training/ — "the work: lifts, cardio, the body's response."
**Source:** elite page-specific design review (physique-transformation + S&C + exercise-phys bench, sports-analytics viz, product/UX bench), grounded in live screenshots (`qa-screenshots/evidence-training*.png`) + real week-one API data, plus athlete-requested visuals folded in.

---

## 0. The one story (the spine)
The page currently leads with an estimated-1RM table marked "✓ goal met" — off-thesis for a ~300 lb beginner in a **Foundation** block, and it invites unsafe maxing. The page must hang off a **twin spine**:

> **"Week one: building the engine — and managing the load so a heavy body absorbs the work instead of breaking."**

Engine (RHR down, Zone-2, walking, the volume ramp) AND load managed (the ramp shown with context, not a trophy).

## 1. Current-state findings (must fix)
- **1RM "✓ goal met" table leads** → reframe as a **Lift Index** trend (see §2). Kill target/checkmark framing; never normalize maxing.
- **RHR 65->55 buried in vitals** → promote to a hero; RHR-down must read ember-POSITIVE. Caveat: early-cut RHR is multi-factorial, "responding," not a VO2max claim.
- **Session volume 6,849 -> 16,567 kg (~2.4x in a week)** → show WITH week-over-week context + load caution; connective tissue lags muscle.
- **Per-lift HR zones from Whoop = 0 for lifts** → honest "not captured for lifting" empty state, never a 0 bar.
- **Stretching/Recovery shown inside "recent cardio"** → give mobility its own home (see modality composition §3).
- **Avg strain as a naked headline** → replace with a daily strain bar / strain-vs-recovery.
- **Walking rendered as a generic step bar** → it's the PRIMARY engine (blueprint); reframe + add HR-of-the-engine.
- **Signatures absent** → deploy measuring-rule tick spine + mono<->serif two-voice.
- **Keep:** expandable strength log; merged Strava+Hevy cardio; dark/light parity; clean mobile reflow.

## 2. Page architecture (top to bottom)
Legend: **[now]** · **[needs-data]** · **[defer]** · **[gated]**.

**§0 — Hero: engine + load.**
- Session-volume ramp (per-session total volume, 6 sessions), WoW % annotated + honest "ACWR unlocks ~4 weeks" placeholder. **[now]**
- RHR decline line (65->55), cut-start marked, two-voice annotation, ember-positive-on-down. **[now]**

**§1a — The engine: aerobic base.** Zone-2 minutes vs 150/week, counting BOTH Strava AND Hevy bike/elliptical (never source from Strava alone). **[now]**
**§1b — HR of the engine.** Avg HR per cardio session + walking-HR trend toward the proven easy-aerobic band (~97 bpm from PROVEN_BLUEPRINT) — proof the easy work stays easy. Cardio HR exists today; lifting HR stays an honest gap. **[now]**
**§1c — Walking as engine.** Steps + walking distance/pace as the primary metabolic driver; proven walking floor is blueprint-derived → **[private/softened]**. Steps render as an ember-intensity heatmap/streak (saturation = volume), low days shown muted-not-hidden (e.g. the real 2,720 / 2,163 dip days). **[now]**

**§2 — The Lift Index (signature).** A grid of main lifts, each a **sparkline + ▲/▼/flat trend tag** ("load moving up / down"), ember = up, muted ink = down, **never red**. Absorbs and replaces the old 1RM-vs-target table. Honesty gate: a tile shows "fills in — N sessions logged" with NO arrow/slope until it has ~3+ sessions of that lift. Keep the expandable per-exercise set/rep/weight log beneath. Binds `strength_benchmarks` / Hevy set-level history as a per-lift trend. **[now scaffold; trends fill in over weeks]**

**§3 — Training time composition.** Stacked-composition bar of MINUTES by modality (lift / walk-cardio / mobility) per day or week — shows whether engine work is happening or getting crowded out, and gives mobility an honest home. Use a tight ember-derived categorical ramp (ember = lift, ember-tint = walk/cardio, muted ink = mobility) — NOT a new hue. Binds per-session duration by type (merged Hevy+Strava). **[now]**

**§4 — Muscle split.** Push / Pull / Legs working-set-volume balance (three-bar or stacked) off Hevy session tags. **[now]** Optional anatomical body-map **[gated on get_muscle_volume core-mapping fix; flagged app-cliché — sequence to Phase 1, eyes open]**.

**§5 — Per-muscle volume vs landmarks.** Horizontal bars per muscle vs MEV/MAV/MRV. **[gated on get_muscle_volume bug — don't ship core reading 0]**.

**§6 — Absorbing the work: strain.** Daily Whoop strain bar **[now]**; richer strain-vs-recovery/HRV overlay (refuses <4 pts) **[now-ish]**.

**§7 — Daily movement table.** Keep, decluttered (mobility out of cardio). **[now]**

**§8 — [Coming online] Load gauge (ACWR / training density).** Placeholder now; populate ~3-4 weeks. **[defer]**

## 3. Features / interactions
- Two-voice annotation on the volume-ramp, RHR, and Lift-Index heroes.
- Honest empty states for per-lift HR zones AND per-lift index tiles under threshold.
- Per-session "what this built" line (Z2 base / pull volume / engine) — never a bare "Recovery."

## 4. Cut list
- "✓ goal met" / 1RM-target framing → Lift Index.
- 0-minute HR-zone bars on lifts → empty state.
- Stretching/mobility listed as cardio → modality composition + own lane.
- Naked avg-strain headline → daily strain bar.
- Premature ACWR/chronic-load → placeholder.

## 5. Data-capture backlog (ranked)
1. **RPE per set** — autoregulation + effort signal, no strap; feeds Training Feedback Loop.
2. **Session sRPE (RPE x duration)** — internal load → honest ACWR later.
3. **HR strap for lifting zones** — fills the Whoop-returns-0 gap.
4. **Rucking load / incline on walks** — makes walking-as-engine progressible.
5. **Bar speed / VBT** — defer; gadget-creep at week one.

## 6. Must-honor constraints
- **Design system:** Fraunces (serif), IBM Plex Mono (data), ONE accent ember `#DD7A37`; down = muted ink, **never red**. First-class dark AND light. Reuse the inline-SVG kit. Deploy tick spine + two-voice here.
- **Color discipline:** where a visual needs >1 category (modality composition, lift up/down), derive a tight ramp from ember (tints/shades + ink) — do NOT introduce a second hue. "More colorful" = more ember intensity/heatmap density, not rainbow.
- **Ember semantics (inverse of nutrition):** down is often the WIN here — RHR-down renders ember-positive.
- **Honesty:** n=1, correlative only, no causal language, no Pearson/correlation chip until >=2 weeks; ACWR ~3-4 weeks; Lift-Index trends need ~3+ sessions/lift. Down days shown. Charts refuse <4 points. Frame is building the engine, NOT PRs — never normalize maxing.
- **Audience/privacy:** me-first; blueprint-derived walking floor + present-vs-past benchmark are private-by-default (explicit opt-in to surface).
