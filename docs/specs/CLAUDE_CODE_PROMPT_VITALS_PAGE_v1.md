# CLAUDE CODE PROMPT — Vitals Page Redesign (v2 — glance-first landing page)
**Target:** averagejoematt.com → `/evidence/vitals/`
**Companion spec:** `docs/SPEC_VITALS_PAGE_REDESIGN_2026-06-21.md` (read first — the three altitudes, the status-rings rule, the updated red/color rule)
**Date:** 2026-06-21

Implement in phases. Inspect existing code before changing it. API: `lambdas/site_api_lambda.py` (Lambda `life-platform-site-api`, **us-west-2**); page consumes `/api/pulse`, `/api/pulse_history` (+ habit completion for the glyph row). Locate the front-end `/evidence/vitals/` components; reuse the inline-SVG chart kit (no new deps).

---

## HARD RULES (non-negotiable)
1. **Glance-first, three altitudes.** Altitude 1 = the instant instrument panel; Altitude 2 = the autonomic synthesis; Altitude 3 = the drill-down. The page must be readable in two seconds at the top.
2. **Anti-black-box.** The status read is ALWAYS built from visible component rings (recovery, HRV, RHR, sleep) — never a lone grade/number.
3. **COLOR / RED.** Ember `#DD7A37` = good / on-protocol / recovered (the brand "green"); muted ink = neutral / low / forming; **RED = reserved alert, sparingly, ONLY for a genuine STATE (run-down / out-of-range / attention). RED NEVER encodes DIRECTION** — RHR-down / HRV-up / weight-down stay ember-positive even when the line falls.
4. **Glyphs light only on real daily signal** (today's habits vs avg-by-this-hour, on-protocol streak, recovered). Always-lit decorative glyphs (e.g. SpO2 normal) are BANNED.
5. **Thin-data honesty.** Status band wears a "8 days in — baseline forming" stamp; 30-day baselines show "fills in"; a confident status must not overclaim on ~8 water-confounded days.
6. **Temporal honesty.** Every chart + ring labeled last-night (sets up today) vs same-day; never let last night's recovery read as "now."
7. **No fabricated data / no causal language / n=1.** Charts refuse <4 points; NO Pearson/correlation chip until >=2 weeks. Minor vitals are anomaly detectors, not daily dials.
8. **Design tokens only:** Fraunces, IBM Plex Mono, tick spine, two-voice. First-class dark AND light (NO light screenshot — verify yourself).

---

## PHASE 0 — Altitude 1: the glance (buildable now)
**P0.1 — Status read (word + component rings).** Plain-language status ("RECOVERED · the body's ready") backed by 3-4 rings that each ARE a component (recovery, HRV, RHR, sleep). Decomposed, never a lone grade. Ember good / muted neutral / red reserved-alert. Binds `/api/pulse` + components.
**P0.2 — Now vs 7d vs 30d ladder.** Under each ring: today + faint 7-day + 30-day baseline ticks; 30-day shows "fills in" at week one. Binds `pulse_history`.
**P0.3 — Earned glyph row.** Glyphs light ember on real signal: today's habits checked vs average-checked-by-this-hour (cross-link Habits), on-protocol streak, recovered. If hourly habit-completion history isn't available, fall back to "X of N today" — do NOT fabricate an hourly baseline.
**P0.4 — Thin-data stamp.** "8 days in — baseline forming"; rings render their thin-data state honestly.

## PHASE 1 — Altitude 2: the synthesis (buildable now)
**P1.1 — Today's pulse narrative (keep + elevate).** Two-voice, retied to the autonomic story.
**P1.2 — Autonomic-recovery hero.** RHR + HRV in ONE frame; RHR inverted so down = ember-positive; "the body downshifting" annotation; mono caveat (early moves partly water/novelty). Binds `pulse_history` RHR + HRV.
**P1.3 — Readiness decomposed.** Recovery % broken into drivers (HRV, RHR, sleep) — the Altitude-1 rings expanded.

## PHASE 2 — Altitude 3: the analysis (buildable now)
**P2.1 — Autonomic 2x2 snapshot.** FLOW/STRESS/RECOVERY/BURNOUT from strain-vs-recovery; last 7-8 days as dots; NO trajectory arrows.
**P2.2 — Small-multiples grid.** recovery/HRV/RHR/strain/weight/steps sparklines, each stamped temporal-frame + trend; tap to expand. Replaces the big equal charts.
**P2.3 — Background-vitals strip.** SpO2/skin temp/resp rate quiet "all in range"; flag (incl. red) only on deviation; resp-rate trend-able.
**P2.4 — Hub links.** Each tile links out (recovery → sleep, strain → training, weight → physical).
**P2.5 — Signatures.** Tick spine on the hero; >=1 serif annotation; remove the old 6-8 equal separate charts.

## PHASE 3 — New capture + relationships (gated)
- **P3.1 Blood pressure (cuff)** — add a BP trend once captured.
- **P3.2 Hourly habit-completion history** — upgrades the glyph benchmark to "by this hour."
- **P3.3 Continuous/walking HR; P3.4 VO2max trend; P3.5 subjective energy/mood 1-5.**
- **P3.6 Cross-metric correlations** — direction-only until >=2 weeks; coefficient/chip only at >=2 weeks; reuse the sleep correlation-board pattern, do not duplicate.

---

## ACCEPTANCE CRITERIA / QA
Re-capture `evidence-vitals.png` + `-mobile.png` (390px) AND a NEW light capture. Verify:
- [ ] Altitude 1 leads: a status word + component rings + now/7d/30d ladder + earned glyphs, readable in ~2 seconds.
- [ ] Status is decomposed (rings = components), never a lone black-box grade.
- [ ] Red appears ONLY as a reserved STATE alert; no falling line (RHR/HRV/weight) is rendered red; RHR-down reads ember-positive.
- [ ] Glyphs light only on real signal; nothing always-lit/decorative.
- [ ] Thin-data stamp present; 30-day baselines show "fills in."
- [ ] Autonomic hero (RHR+HRV one frame) + decomposed readiness present (Altitude 2).
- [ ] 2x2 (no arrows) + small-multiples grid + background strip + hub-links present (Altitude 3).
- [ ] Every chart/ring labeled last-night vs same-day; no correlation chip under 2 weeks.
- [ ] Tick spine + >=1 serif annotation; <4-point charts refuse.
- [ ] Dark AND light first-class (verify the new light capture).

## STOP-AND-ASK gates (no proceed without sign-off)
- Expanding red usage beyond reserved state-alerts.
- Any cross-metric correlation before the >=2-week window.
- Any deploy.

## DEPLOY (per convention)
`deploy/deploy_lambda.sh` for `life-platform-site-api` (us-west-2), 10s between deploys. Update CHANGELOG + PROJECT_PLAN; data-model changes → ARCHITECTURE/SCHEMA/DATA_DICTIONARY; `python3 deploy/sync_doc_metadata.py --apply` if counts changed; commit + push.

## OUT OF SCOPE
A black-box readiness grade; red encoding direction; always-lit decorative glyphs; minor vitals as equal daily charts; correlation chip under 2 weeks; a page that opens into 8 equal charts; duplicating the sleep correlation board.
