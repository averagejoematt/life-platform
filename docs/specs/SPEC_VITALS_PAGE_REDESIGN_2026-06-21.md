# SPEC — /evidence/vitals/ Page Redesign (v2 — glance-first landing page)
**Date:** 2026-06-21 (rev. — Altitude-1 instrument panel; red allowed as reserved alert)
**Page:** averagejoematt.com → /evidence/vitals/ — "today's read, in context." (THE landing page / daily hub)
**Source:** elite page-specific design review (longevity/physiology + HRV/autonomic + QS-dashboard + wearable-data bench, viz, product/UX), grounded in live screenshots (`qa-screenshots/evidence-vitals.png`, `-mobile.png`; NO light capture — verify at build) + real week-one data (8/8 days), plus athlete direction (glanceable Whoop-homepage-style status board).

---

## 0. The one story (the spine)
Vitals is THE landing page — bookmarkable, readable in two seconds, then bleeding into the analysis. It works at THREE ALTITUDES, top to bottom:
- **Altitude 1 — THE GLANCE:** an instrument panel anyone (you at 6am, a day-one stranger) reads instantly.
- **Altitude 2 — THE SYNTHESIS:** the one story the data tells — the autonomic system downshifting into recovery (RHR down + HRV up together).
- **Altitude 3 — THE ANALYSIS:** the drill-down (2x2, small-multiples, background vitals, hub-links out).

> **Spine: "An instant, honest tell at the top; the full documentary as you scroll."**

## 1. Current-state findings (must fix)
- **No glanceable top — page opens into a narrative + 8 equal charts** → add Altitude-1 instrument panel; the glance is the landing-page's whole job.
- **8 separate equal-weight trend charts** → demote to the small-multiples grid (Altitude 3); keep 1 autonomic hero (Altitude 2).
- **RHR + HRV as separate lines** → combine into the autonomic-recovery hero.
- **No decomposed readiness / no status read** → add a status word + component rings (NOT a black-box grade).
- **Minor vitals (SpO2/skin temp/resp rate) charted as equal trends** → background strip, flag only on deviation.
- **Keep + elevate:** the two-voice pulse narrative; the last-night/same-day temporal frame (the ownable honesty signature).

## 2. Page architecture (three altitudes, top to bottom)
Legend: **[now]** · **[needs-data]** · **[needs-weeks]**.

### ALTITUDE 1 — THE GLANCE (new; the instrument panel)
**§0.1 — Status read (word + component rings).** A plain-language status — e.g. "RECOVERED · the body's ready" — backed by 3-4 rings/arcs that EACH ARE a component (recovery, HRV, RHR, sleep). The glance is made of the real parts, so it's instant AND decomposed (never a single black-box grade). Binds `/api/pulse` + components. **[now]**
**§0.2 — Now vs 7-day vs 30-day ladder.** Under each ring: today's value + faint 7-day and 30-day baseline ticks ("am I above/below my normal"). 30-day shows "fills in" honestly at week one. Binds `pulse_history`. **[now; 30d forming]**
**§0.3 — Earned glyphs (light up only on real signal).** A row of glyphs that light ember as real daily signals fire: today's habits checked vs the average checked-by-this-hour (cross-links to Habits), on-protocol streak, recovered/ready. NOT decorative — glyphs that are "always lit" (e.g. SpO2 normal) are banned. Binds habit completion (by hour) + status. **[now if hourly habit-completion history exists; else "X of N today" simple form]**
**§0.4 — Thin-data honesty stamp.** The status band wears a quiet "8 days in — baseline still forming" stamp; rings show their thin-data state rather than projecting false certainty. A confident "RECOVERED" on day 8 of a water-confounded cut must not overclaim. **[now]**

### ALTITUDE 2 — THE SYNTHESIS
**§1.0 — Today's pulse narrative (kept + elevated).** Two-voice (mono = numbers, serif = what today is for), retied to the autonomic story. **[now]**
**§1.1 — Autonomic-recovery hero (RHR + HRV in one frame).** Shared time axis; RHR inverted so down = ember-positive; HRV up = ember-positive; "the body downshifting" annotation; mono caveat (early moves partly water/novelty). Binds `pulse_history` RHR + HRV. **[now]**
**§1.2 — Readiness read, decomposed.** Recovery % broken into drivers (HRV, RHR, sleep) — same decomposition as the Altitude-1 rings, expanded. **[now]**

### ALTITUDE 3 — THE ANALYSIS
**§2.0 — Autonomic-balance 2x2 snapshot.** FLOW/STRESS/RECOVERY/BURNOUT from strain-vs-recovery; last 7-8 days as dots; NO trajectory arrows at n=8. **[now, snapshot]**
**§2.1 — Small-multiples grid.** Sparkline grid (recovery/HRV/RHR/strain/weight/steps), each stamped temporal-frame + trend direction; tap to expand. Replaces the big equal charts. **[now]**
**§2.2 — Background-vitals strip.** SpO2 / skin temp / resp rate as a quiet "all in range" sparkline strip; surfaces a flag (incl. red) only on deviation; resp-rate kept trend-able. **[now]**
**§2.3 — Hub links.** Each tile links OUT to its domain page (recovery → sleep, strain → training, weight → physical). The landing page is the front door. **[now]**

## 3. Features / interactions
- Tap a ring/glyph/small-multiple → expand to the component's full chart/context.
- Last-night vs same-day framing stays as the organizing scaffold.
- Two-voice on the autonomic hero; honest "n=8 - one week" stamps.

## 4. Cut list
- Page opening into 8 equal charts → glance panel first, charts demoted to the grid.
- Black-box readiness grade → status word + component rings (decomposed).
- Minor vitals as equal daily charts → background strip.
- Always-lit decorative glyphs → glyphs light only on real daily signal.
- Cross-metric correlation chip at week one → >=2-week gate.

## 5. Data-capture backlog (ranked)
1. **Blood pressure (cuff)** — highest; most valuable missing daily vital for a heavy man in a cut; will visibly improve.
2. **Hourly habit-completion history** — powers the §0.3 "checked-off-by-this-hour" glyph benchmark (if not already available).
3. **Continuous / walking HR** — feeds Z2 + autonomic.
4. **VO2max trend** — longevity gold-standard; arc cadence.
5. **Subjective energy/mood 1-5** — ground-truth overlay on readiness.

## 6. Must-honor constraints
- **Design system:** Fraunces, IBM Plex Mono, primary accent ember `#DD7A37`. First-class dark AND light (verify light — no light screenshot yet). Reuse the inline-SVG kit; deploy tick spine + two-voice.
- **COLOR / RED (updated):** ember = good / on-protocol / recovered (the brand's "green"); muted ink = neutral / low / forming; **RED = reserved alert, used sparingly, ONLY for a genuine STATE (run-down / out-of-range / attention).** RED NEVER encodes a DIRECTION — RHR-down / HRV-up / weight-down stay ember-positive even though they fall. (System-level note: red may later propagate to sleep/nutrition at-risk states — not yet applied there.)
- **Anti-black-box:** the status read is always built from visible component rings; never a lone grade/number.
- **Temporal honesty:** every chart + ring labeled last-night (sets up today) vs same-day.
- **Thin-data honesty:** glance wears the "baseline forming" stamp; 30-day baselines show "fills in"; a confident status must not overclaim on ~8 water-confounded days.
- **Rigor:** n=1, correlative only, no causal language, NO Pearson/correlation chip until >=2 weeks. Charts refuse <4 points. Big early autonomic moves framed as "responding."
- **Audience:** me-first; bookmarkable glance at the top; the hub links out to the domain pages.
