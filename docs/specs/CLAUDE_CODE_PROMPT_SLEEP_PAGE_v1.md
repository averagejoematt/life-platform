# CLAUDE CODE PROMPT — Sleep Page Redesign (v1, rev. with correlation board)
**Target:** averagejoematt.com → `/evidence/sleep/`
**Companion spec:** `docs/specs/SPEC_SLEEP_PAGE_REDESIGN_2026-06-21.md` (read first — rationale, panel disagreements, field bindings, the correlation-board honesty mechanics in §3)
**Date:** 2026-06-21

Implement in phases. Inspect existing code before changing it. API: `lambdas/site_api_lambda.py` (Lambda `life-platform-site-api`, **us-west-2**); page consumes `/api/sleep_detail`, `/api/circadian`, `/api/sleep_reconciliation`. The correlation board is powered by existing platform tools (`get_cross_source_correlation` with day-lag, `get_sleep_environment_analysis`, `get_autonomic_balance`, `get_decision_fatigue_signal`, `get_journal_sentiment_trajectory`, `get_jet_lag_recovery`) — surface via the site API; do not call MCP tools from the front-end. Reuse the inline-SVG chart kit (no new deps).

---

## HARD RULES (non-negotiable)
1. **No fabricated data.** <4 points → honest refusal. Social-jet-lag needs a weekend; forecast grading + correlation coefficients need ~2 weeks — empty/"watching" states until then.
2. **No causal language, n=1, correlative only.** One night is never a verdict.
3. **CORRELATION BOARD POLICES ITSELF.** Every card shows n + overlap-weeks + a confidence tag. **<2 weeks overlap → DIRECTION ONLY, no Pearson, no correlation chip.** >=2 weeks → coefficient + chip, still labeled. Thin/volatile pairs carry an explicit "likely noise at this n" flag. The self-skepticism is the feature — do not strip it.
4. **Prospective, not retrospective.** The circadian forecast leads; last-night figures demoted.
5. **Ember = "on track / protective," muted = "at risk / off." NEVER red.** Forecast at-risk reads muted, not an alarm. RHR-down = good; bed-temp is an optimal band.
6. **Dual-device = "agreement, not truth."** Wearable stages aren't PSG.
7. **Design tokens only:** Fraunces, IBM Plex Mono, tick spine, two-voice. First-class dark AND light (NO light screenshot exists — verify yourself).
8. **Privacy tiering:** caffeine/alcohol + behavioral inputs privacy-tier; no public render without an opt-in flag.

---

## PHASE 0 — Flip the spine + the core visuals (buildable now)
**P0.1 — Forecast hero ("tonight's odds").** Promote from bottom tile to hero: 0-100 split into FOUR anchors + the lever to pull now; two-voice; at-risk muted, never red. Binds `/api/circadian`.
**P0.2 — Demote last-night figures** beneath the forecast; expose sleep-score inputs or stop leading with the composite.
**P0.3 — Dual-device stage agreement** (Whoop vs Eight Sleep dumbbell/paired bar; "agreement, not truth").
**P0.4 — Regularity / consistency** (bedtime/wake band + social-jet-lag readout; empty state until a weekend).
**P0.5 — Stage composition over the week** (stacked bar/night; refuses <4 points).
**P0.6 — Environment overlay** (Eight Sleep temp vs deep-sleep; observation-only).
**P0.7 — Autonomic downshift readout** (`get_autonomic_balance` state snapshot — honest at low n).
**P0.8 — Declutter physiology** (keep efficiency / WASO / time-to-sleep).
**P0.9 — Signatures** (tick spine on trend + composition; >=1 serif annotation on the forecast hero).

## PHASE 1 — Cross-page + new capture (add API field first; never stub)
- **P1.1 Recovery readout** — HRV/RHR/recovery framed as "what sleep defends in a deficit" (cross-link). (Buildable now; sequenced here.)
- **P1.2 Last-meal-time cross-link** — reuse nutrition eating-window; late-eating vs sleep, observation-only.
- **P1.3 Subjective "how rested" 1-5 capture.**
- **P1.4 Caffeine + alcohol timing capture** — feeds forecast anchors + board; privacy-tier.
- **P1.5 Light exposure (AM/PM)** — screen-time proxy, flagged.

## PHASE 2 — Cross-source signal board + calibration (honesty-gated)
Build the board per spec §3. Each card: pair + n + overlap-weeks + confidence tag; direction-only under 2 weeks; coefficient + correlation chip at >=2 weeks; "likely noise" flag on thin pairs.
- **P2.1 A1 — Last night sleep/recovery → today's training capacity** (LEAD card; cross-link to training).
- **P2.2 A2 — Day strain → next-night deep sleep / recovery** (day-lagged).
- **P2.3 A3 — Bed temp → deep sleep** (mechanistic; may reuse P0.6).
- **P2.4 A4 — Eating-window / last-meal → sleep** (reuse nutrition data).
- **P2.5 B1 — Decision fatigue (Todoist load) → sleep** (`get_decision_fatigue_signal`).
- **P2.6 B2 — Journal mood → sleep** — gated on active journaling; empty state if stale.
- **P2.7 B3 — Day-of-week best duration** — scaffold now, "fills in ~4 weeks" (n=1/day at week one).
- **P2.8 C1 — Sleep vs weight** — HIGHEST false-positive risk in a water-weight cut: scaffold, show last, label loudest, WITHHOLD coefficient until well past the early water phase (multiple weeks) AND my sign-off.
- **P2.9 Forecast self-grading** — did high-risk nights score lower? Placeholder until ~2 weeks.

---

## ACCEPTANCE CRITERIA / QA
Re-capture `evidence-sleep.png` + `-mobile.png` (390px) AND a NEW light capture. Verify:
- [ ] Forecast leads as hero; last-night figures demoted; at-risk reads muted, not red.
- [ ] Dual-device agreement labeled "agreement, not truth."
- [ ] Regularity present; social-jet-lag empty-states if no weekend.
- [ ] Autonomic downshift readout present.
- [ ] Correlation board: every card shows n + overlap + confidence; NO coefficient/chip under 2 weeks; "likely noise" flags present; sleep-vs-weight coefficient withheld.
- [ ] No single-night verdicts; physiology decluttered.
- [ ] Tick spine + >=1 serif annotation; single ember accent, no red.
- [ ] Any <4-point chart refuses; no causal language.
- [ ] Dark AND light first-class (verify the new light capture).

## STOP-AND-ASK gates (no proceed without sign-off)
- Surfacing the sleep-vs-weight coefficient (false-positive risk).
- Any public render of caffeine/alcohol inputs.
- Any deploy.

## DEPLOY (per convention)
`deploy/deploy_lambda.sh` for `life-platform-site-api` (us-west-2), 10s between deploys. Update CHANGELOG + PROJECT_PLAN; data-model changes → ARCHITECTURE/SCHEMA/DATA_DICTIONARY; `python3 deploy/sync_doc_metadata.py --apply` if counts changed; commit + push.

## OUT OF SCOPE
Wearable stages as PSG truth; single-night verdicts; red/alarm forecast; ANY correlation coefficient/chip under 2 weeks of overlap; sleep-vs-weight coefficient during the water-weight phase; any public behavioral-input render without opt-in.
