# SPEC — /evidence/physical/ Page Redesign (Weight + Body-Composition)
**Date:** 2026-06-21 (rev. — weight-cockpit-first, PhenoAge bio-age)
**Page:** averagejoematt.com → /evidence/physical/ — "weight is the metronome; composition is the arc."
**Source:** elite page-specific design review (body-comp/DEXA + sports-med + metabolic + longevity bench, viz, product/UX), grounded in live screenshots (`qa-screenshots/evidence-physical.png`, `-mobile.png`; NO light capture — verify at build) + real data + athlete direction (HappyScale-style weight cockpit; established bio-age formula; richer visuals).

---

## 0. The one story (the spine)
DEXA and measurements are episodic (weeks/months apart) — a STORY ARC, not a daily page. The daily-meaningful signal is WEIGHT. So the page is two tiers:
- **Tier 1 — the weight cockpit (daily):** the thing someone opens every morning.
- **Tier 2 — the composition arc (episodic):** DEXA, tape, photos, bio-age — countdown-driven chapters, explicitly "next chapter lands in ~X days."

> **Spine: "The scale is moving now; the deeper picture refreshes in chapters — and the next one is coming."**

Scans being months apart is not a weakness to hide — it makes them EVENT content (a season finale), not a stale tile.

## 1. TIER 1 — Weight cockpit (all buildable now, from `weight_progress`)
**§1.0 — Trend-weight hero (dual-layer).** Faint TRUE daily dots + a confident ember TREND line (smoothed, down-weighting daily water/food noise); the dot-vs-line gap labeled as noise. Goal 185 as a distant ANNOTATION (never an axis anchor — anchoring flattens the slope). Genesis line (Jun 14). Two-voice. **[now]**
**§1.1 — Silhouette scrubber (linked hero).** Faceless silhouette, girth = f(weight); drag start → now → goal; scrubs in lockstep with the trend line. Public-safe proxy for a progress photo. Reuse existing silhouette. **[now]**
**§1.2 — Stat cluster (HappyScale-style).** High / Latest / Low; Yesterday; % complete of total (314.5 → 185 denominator). Replaces the DEXA percentages as the top figures. **[now]**
**§1.3 — Milestone ladder (the signature, made to work).** The measuring-rule tick-spine, vertical: 315 → 185, each 10-lb rung a tick that clicks ember as crossed; days-between-rungs annotated (widening gaps = the honest pace arc). Unifies %-complete + milestones + the spine signature into one object. **[now]**
**§1.4 — Rate tempo strip.** 7d / 30d / 90d / since-genesis as small slope-gauges (ember intensity = pace), NOT four naked numbers; the 7d carries the "early = water" flag. **[now]**
**§1.5 — Projection cone.** Rate-based forecast to 185 as a WIDENING confidence cone, with date-markers where it crosses each rung; wide now (water-inflated early rate), tightens as data accrues. Loud "early-rate, will slow" caveat; show the bet AND grade it as it resolves (self-grading prediction). **[now]**
**§1.6 — BMI (de-emphasized).** Include because HappyScale-literate readers expect it, but small and captioned with its own limitation ("near-meaningless on a heavy frame rebuilding lean mass"); never a hero. **[now]**

## 2. TIER 2 — Composition arc (episodic, countdown-driven)
**§2.0 — Next-DEXA countdown (arc anchor).** "Scan two lands in ~X days — composition velocity becomes real then." Turns the single scan into anticipation. **[now]**
**§2.1 — DEXA baseline (dated, honest).** Lean-vs-fat ONE stacked bar, labeled "2026-03-30 · ~80 days ago · pre-cut baseline." A snapshot, never a trend. **[now, dated]**
**§2.2 — Visceral fat callout (dated).** Single figure + risk-band context — the health number that matters more than total %. **[now, dated]**
**§2.3 — Lean / ALMI longevity context (dated, demoted).** Small, reference bands, plain language; out of the raw table. **[now, dated]**
**§2.4 — Biological age (PhenoAge, transparent).** Levine Phenotypic Age (2018): 9 blood markers (albumin, creatinine, glucose, hs-CRP, alkaline phosphatase, WBC, lymphocyte %, MCV, RDW) + chronological age. Render as a TWO-AGES dial (chronological vs phenotypic; gap ember=younger / muted=older), EXPANDABLE to the 9 markers driving it. Recompute per blood draw (arc cadence). Caveats (mandatory): population-level not diagnostic; this is blood-based Phenotypic Age, NOT the DNAm epigenetic clock; "per draw" stamp; volatile to single markers (e.g. CRP). Cross-link to Bloodwork. Replaces the DEXA black-box "biological age." **[now — pure computation from existing labs]**
**§2.5 — Full-scan expander.** Remaining indices/segmental behind a "full 2026-03-30 scan" expander, all dated; +3.9 bone T-score suppressed/flagged as artifact. **[now]**

## 3. Features / interactions
- Silhouette + trend line scrub together (linked).
- Tap a milestone rung → the day crossed + days-since-previous.
- Toggle trend vs raw weight.
- Bio-age dial expands to the 9 contributing markers (which push up/down).
- Honest empty states: composition velocity / tape / photos show "awaits scan two / first measurement."

## 4. Cut list
- DEXA percentages as the page's top figures → replaced by the weight stat cluster.
- +3.9 bone T-score → suppress/flag as artifact.
- DEXA "Body Score" + black-box "biological age" → replaced by transparent PhenoAge (inputs shown).
- `changes_vs_baseline` composition deltas as progress → one scan isn't a trend; only weight is honest "change."
- Jargon index tables as equal rows → expander.
- Bio-age as a DAILY metric → it's a per-draw arc metric, not cockpit.

## 5. Data-capture backlog (ranked)
1. **Schedule scan two (DEXA cadence)** — 8-12 wks from genesis (~early Sept); unlocks composition velocity; the page counts down to it.
2. **Tape measurements** — 0 records; cheap, frequent, between-DEXA proxy; feeds silhouette/segmental.
3. **Progress photos — explicit privacy stance** — most powerful + most sensitive; PRIVATE-BY-DEFAULT, explicit opt-in, silhouette as public-safe version, blur option.
4. **(Optional) complementary "ages"** — vascular age from Withings PWV (type 91); VO2max-based fitness age. Secondary lenses; PhenoAge is the anchor. (WHOOP Age exists but is NOT in the official API — only an unofficial password-auth scrape — so treat as fragile/flagged if ever used.)

## 6. Must-honor constraints
- **Design system:** Fraunces, IBM Plex Mono, ONE accent ember `#DD7A37`; down = muted ink, **never red**. First-class dark AND light (verify light — no light screenshot yet). Reuse the inline-SVG kit + the weight-driven silhouette + the measuring-rule spine (now the milestone ladder). Deploy tick spine + two-voice.
- **Ember semantics (inverse-aware):** weight-down / fat-down / lean-up / younger-bio-age all render ember-POSITIVE; don't mute the win on "down."
- **Honesty / rigor:** n=1, correlative only, no causal language. Trend-weight smoothing shows BOTH raw and trend. ONE DEXA is a point — no composition velocity until scan two; all composition DATED + pre-cut-labeled. PhenoAge shown WITH its 9 inputs, per-draw, population-level + not-DNAm caveats. Implausible/black-box values suppressed/flagged. Early weight rate framed as water. Projection cone widens for uncertainty; line charts refuse <4 points.
- **Audience/privacy:** me-first; progress photos private-by-default + opt-in; silhouette is the public-safe proxy.
