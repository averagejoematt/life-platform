# CLAUDE CODE PROMPT — Physical Page Redesign (v2 — weight-cockpit-first, PhenoAge)
**Target:** averagejoematt.com → `/evidence/physical/`
**Companion spec:** `docs/SPEC_PHYSICAL_PAGE_REDESIGN_2026-06-21.md` (read first — the two-tier structure, the visual treatments, the PhenoAge honesty rules)
**Date:** 2026-06-21

Implement in phases. Inspect existing code before changing it. API: `lambdas/site_api_lambda.py` (Lambda `life-platform-site-api`, **us-west-2**); page consumes `/api/physical_overview`, `/api/weight_progress`, `/api/journey`. PhenoAge inputs come from the bloodwork/labs source (9 standard markers). Locate the front-end `/evidence/physical/` components; reuse the inline-SVG kit, the weight-driven silhouette, and the measuring-rule spine (no new deps).

---

## HARD RULES (non-negotiable)
1. **Weight is the page; composition + bio-age are an episodic ARC.** Tier 1 = daily weight cockpit; Tier 2 = countdown-driven composition chapters.
2. **No fabricated data.** Line charts refuse <4 points. Honest empty states for composition velocity / tape / photos.
3. **ONE DEXA is a point, not a trend.** NO composition velocity / progress / `changes_vs_baseline`-as-progress until a second scan exists. The only honest "change" now is WEIGHT. All composition figures DATED + labeled pre-cut baseline (2026-03-30, ~80 days old).
4. **Goal 185 is an ANNOTATION, never an axis anchor.** Plot the real slope; mark genesis (2026-06-14). Trend-weight shows BOTH raw daily dots and the smoothed trend line.
5. **PhenoAge = transparent.** Levine Phenotypic Age (2018), 9 blood markers + age; ALWAYS show the 9 inputs; per-draw cadence (NOT daily); caveats: population-level not diagnostic, blood-based Phenotypic Age NOT the DNAm epigenetic clock. Replaces the DEXA black-box "biological age."
6. **Suppress/flag implausible + black-box values.** Bone T-score +3.9 → suppress/flag as artifact. DEXA "Body Score" → demote/replace.
7. **Ember = "toward goal / protective," direction contextual. NEVER red.** weight-down / fat-down / lean-up / younger-bio-age render ember-positive. Early weight rate framed as water.
8. **Design tokens only:** Fraunces, IBM Plex Mono, tick spine, two-voice, silhouette. First-class dark AND light (NO light screenshot — verify yourself).
9. **Privacy:** progress photos private-by-default + explicit opt-in; silhouette is the public-safe proxy.

---

## PHASE 0 — Tier 1: the weight cockpit (buildable now, from weight_progress)
**P0.1 — Trend-weight hero (dual-layer).** Faint raw daily dots + confident ember trend line; dot-vs-line gap labeled noise; goal as annotation; genesis line; two-voice. Binds `weight_progress`.
**P0.2 — Silhouette scrubber (linked).** Girth = f(weight); drag start→now→goal; scrubs in lockstep with the trend line. Reuse existing silhouette.
**P0.3 — Stat cluster.** High / Latest / Low; Yesterday; % complete (314.5→185). Replaces DEXA percentages as the top figures.
**P0.4 — Milestone ladder.** Vertical measuring-rule spine 315→185; each 10-lb rung clicks ember when crossed; days-between-rungs annotated. Unifies %-complete + milestones + signature.
**P0.5 — Rate tempo strip.** 7d/30d/90d/since-genesis as slope-gauges (ember intensity = pace); 7d flagged "early = water."
**P0.6 — Projection cone.** Widening confidence cone to 185 with rung-crossing date-markers; wide now, tightens as data accrues; loud "early-rate, will slow" caveat; render the bet AND grade it on resolution.
**P0.7 — BMI (de-emphasized).** Small, captioned with its limitation; never a hero.

## PHASE 1 — Tier 2: the composition arc (buildable now where noted)
**P1.1 — Next-DEXA countdown** (arc anchor). "Scan two in ~X days."
**P1.2 — DEXA baseline (dated).** Lean-vs-fat ONE stacked bar, "2026-03-30 · ~80 days ago · pre-cut baseline."
**P1.3 — Visceral fat callout (dated)** + risk-band context.
**P1.4 — Lean / ALMI longevity context (dated, demoted).**
**P1.5 — PhenoAge bio-age (transparent).** Compute Levine Phenotypic Age from the 9 lab markers (albumin, creatinine, glucose, hs-CRP, alkaline phosphatase, WBC, lymphocyte %, MCV, RDW) + age. Two-ages dial (chronological vs phenotypic; gap ember/muted), expandable to the 9 drivers; per-draw stamp; population-level + not-DNAm caveats; cross-link Bloodwork. Verify all 9 markers exist in the labs source first; if any missing, render an honest "needs marker X" state — do NOT approximate silently.
**P1.6 — Full-scan expander** (dated); +3.9 T-score suppressed/flagged.

## PHASE 2 — New capture + velocity (gated)
- **P2.1 DEXA cadence / scan-two scheduling** → drives the countdown; unlocks velocity.
- **P2.2 Tape measurements** → between-DEXA proxy; feeds silhouette/segmental.
- **P2.3 Progress photos** → private-by-default capture; explicit opt-in before any public/blurred render.
- **P2.4 Composition velocity** → lean/fat/visceral change vs the new scan, ONLY once two valid DEXAs exist and the delta clears DEXA least-significant-change. Placeholder until then.
- **P2.5 (optional) complementary ages** — Withings PWV vascular age; VO2max fitness age. PhenoAge stays the anchor. (WHOOP Age is NOT in the official API — do not build on the unofficial password-auth scrape without explicit sign-off + a "fragile source" label.)

---

## ACCEPTANCE CRITERIA / QA
Re-capture `evidence-physical.png` + `-mobile.png` (390px) AND a NEW light capture. Verify:
- [ ] Tier 1 weight cockpit leads: trend-weight (raw + smoothed), silhouette scrubber, stat cluster, milestone ladder, rate tempo, projection cone, BMI demoted.
- [ ] Goal 185 is an annotation, not an axis anchor; genesis line marked; 7d rate flagged as water.
- [ ] Projection cone WIDENS for uncertainty; bet is gradeable.
- [ ] Tier 2 arc: next-DEXA countdown present; all composition DATED + pre-cut-labeled; no composition trend/velocity.
- [ ] PhenoAge shows all 9 inputs, per-draw stamp, population-level + not-DNAm caveats; missing-marker → honest state, not silent approximation.
- [ ] +3.9 T-score suppressed/flagged; Body Score replaced.
- [ ] `changes_vs_baseline` not presented as progress.
- [ ] Ember positive on down/younger; no red. Tick spine + >=1 serif annotation. <4-point charts refuse.
- [ ] Dark AND light first-class (verify the new light capture).

## STOP-AND-ASK gates (no proceed without sign-off)
- Any public render of progress photos.
- Building composition velocity before a valid scan two.
- Building on the unofficial WHOOP Age source.
- Any deploy.

## DEPLOY (per convention)
`deploy/deploy_lambda.sh` for `life-platform-site-api` (us-west-2), 10s between deploys. Update CHANGELOG + PROJECT_PLAN; data-model changes → ARCHITECTURE/SCHEMA/DATA_DICTIONARY; `python3 deploy/sync_doc_metadata.py --apply` if counts changed; commit + push.

## OUT OF SCOPE
Composition trend/velocity from one scan; `changes_vs_baseline` as progress; +3.9 T-score as fact; black-box Body Score / bio-age (use transparent PhenoAge); bio-age as a daily metric; goal anchoring the weight axis; red/alarm states; unofficial WHOOP Age without sign-off; public progress-photo render without opt-in.
