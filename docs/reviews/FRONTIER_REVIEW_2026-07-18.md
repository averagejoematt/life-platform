# Frontier Review — 2026-07-18

> **Status:** research record · **Ritual:** `/frontier-plan` (first run) · **Owner:** Matthew
>
> The full-horizon review: from quantified self to quantified **life**. Three-persona live
> walkthrough + flourishing-science coverage map + QS/biohacking market scan + AI-frontier
> scan → 49 ideas → 7 outcome epics / ~40 stories filed under label
> **`review:frontier-2026-07-18`**. This doc preserves the *research* so future sessions
> inherit the evidence, not just the issue titles. Companion to `/fullreview` (artifact
> grading) and `/sdlc-review` (lifecycle audit): this ritual asks *what should this become
> next, and in what order?*

## 1. Method

Phase 0 recon (3 agents: data/signal inventory, intelligence/character engine, site surface +
backlog) → Phase 1 three-persona live walkthrough (rendered JS via Playwright + raw `/api/*`)
→ Phase 2 flourishing-science research (web, cited, adversarially checked) → Phase 3 market +
AI-frontier sweeps (blind, parallel) → Phase 4 ideation across 8 lanes (3 blind agents) →
Phase 5 verification (load-bearing claims re-tested against live APIs) + stack-rank. Rubric:
Transform-Matthew × Wow/differentiation × Trust-&-rigor fit × Loop-closure ÷ Effort; cost
never a ranking factor, run-rate deltas flagged (ADR-063).

## 2. The flourishing coverage map (the "quantified life" gap analysis)

Ten-pillar model from the evidence (foundations / core needs / life structure). Strongest
evidence in the field: **relationship quality** (Holt-Lunstad 2010: OR 1.5 survival across
308k people; Harvard Study: quality-at-50 predicts health-at-80 better than cholesterol),
**exercise→mood** (Singh 2023 umbrella review, ES −0.43 depression), **purpose** (~2× mortality
hazard low-vs-high, Alimujiang 2019), **SDT** (controlling gamification crowds out intrinsic
motivation — the most important design finding), **time affluence** (time poverty ≈
unemployment-scale wellbeing hit, Whillans 2017). Honest gradings: gratitude effects small
(Cregg & Cheavens 2021), nature moderate/heterogeneous, awe thin, flow a marker not a lever.

| Pillar | Verdict vs. platform (2026-07-18) |
|---|---|
| Sleep / exercise / nutrition / health | **measured & modeled** (the platform's spine) |
| Hedonic mood | **measured & modeled** (State of Mind + evening ritual tap) |
| SDT needs, flow, eudaimonia, gratitude, social *quality* | **measured but DARK** — journal enrichment computes `values_lived / gratitude / flow / growth_signals / ownership / social_quality / emotional_depth` daily, consumed ONLY by narrative prompts; no partition, tool, trend, or page |
| Accomplishment | **mis-framed** — Todoist modeled as cognitive load only, never as mastery/progress |
| Relationships (the best-evidenced pillar) | **most under-instrumented relative to importance** — self-report only, no external graph; character pillar effectively uninstrumented |
| Finance | **one integration away** (Monarch; subjective security is the wellbeing-active part — CFPB-5 scale) |
| Time affluence | **no signal at all** (calendar tools retired, ADR-030) |
| Purpose-as-goal, nature exposure, career/work | **needs designed proxy** |

Short validated instruments suitable for periodic N=1 use: PERMA-Profiler (23), WHO-5 (5),
UCLA-3 loneliness, MLQ (10), Flow Short Scale, PSS-4, BPNSFS, CFPB financial wellbeing (5),
subjective vitality (7). Digital-phenotyping caveat: passive mood proxies are fragile —
hypothesis generators to pair with brief self-report ground truth, never validated scores.

**Highest-evidence cross-domain edges testable today:** exercise→mood; sleep→next-day affect;
**alcohol→HRV/REM (1–2 drinks cut HRV 28–33% — cleanest fast edge, currently uncovered)**;
social interaction→same-day valence; ACWR→HRV→mood mediation; CGM variability→mood (novel);
gratitude→sleep (expect small/null — a finding either way); values_lived→adherence. Not yet:
financial anxiety→sleep (needs Monarch). Today's weekly engine covers 23 pairs but only 3
lagged; alcohol, caffeine, glucose, mood, reading, social, supplements have **zero** edges.

**Five research-grounded warnings (baked into every filed issue):**
1. Tracking valenced states can amplify rumination — track inputs/behaviors; never show a
   declining mood chart without agency framing; offer tracking breaks.
2. Controlling gamification backfires (SDT undermining effect) — streaks as information,
   everything skippable, no loss-framing, no idealized-self comparison.
3. Orthosomnia/optimization-obsession are documented — show uncertainty, suppress noise alarms.
4. Goodhart: an 80%-physio dashboard starves the high-evidence unmeasured pillars — weight the
   UI toward relationships/purpose/time even with cruder measurement.
5. Public N=1 invites performing wellbeing (biases the journal the enrichment depends on) —
   pre-register, lag designs, "one person" labels everywhere.

## 3. Market scan verdicts (2026-07)

Nobody in the space grades their own AI coach or genuinely pre-registers: **the platform's
existing machinery is the flagship white space.** Instructive comparators: Blueprint (steal
data-as-spectacle + leaderboard; beat on real falsifiability — "presentation of rigor is half
the battle," so production values matter); Oura Advisor (60%+ weekly engagement; steal
tone-selection + Memories); eToro CopyTrader (**the model**: public verifiable scored track
record you can follow and act on); Exist.io (alive at $6.99/mo — proof private correlations
alone don't travel); howisFelix.today (openness + permanence ethos); QS Show&Tell (three
questions + no-selling rule; talks travel on **human stakes**).

Five universal QS failure modes vs. us: logging fatigue (partial risk — the journal is
manual); streak trap (character sheet could reinforce streak anxiety — design "gaps are
data"); insight drought (our core strength); AI-credibility gap (uniquely avoided via scored
coaches — the moat); **the "so what?" wall (unsolved — a stranger needs stakes + a replication
path to care about one person's data)**. Five white spaces nobody occupies: scored public
followable coach track record; genuine consumer-N=1 pre-registration; being-wrong-as-content;
one-click replication kits/cohorts; permanence-guaranteed data transparency (timed to the
Whoop/Oura BIPA backlash). Market: biohacking ~$56B 2026 at ~25% CAGR; every wearable ships an
LLM coach; independent testing says they underperform; nobody publishes whether the advice
worked.

## 4. AI-frontier verdicts (mid-2026, Bedrock-constrained)

Stack shifts since the 2025 design: **1M-token context GA un-surcharged** on Bedrock (old
Sonnet-4.5 1M beta retired Apr 2026 — check pinned code); **Structured Outputs GA** (true
constrained decoding — free hardening of the grounded-generation gates); **prompt caching 1-hr
TTL** (whole-life-archive context ≈ +$0.5–2/mo). NOT available: Claude realtime
speech-to-speech on Bedrock (no live voice calls); Claude fine-tuning on Bedrock (and a
"Matthew-model" is a fabrication vector — rejected). Bedrock-native cheap wins: structured
outputs ($0), 1M archive context, vision meal-photo *estimates* (fenced from logged data),
bounded agentic investigation over the MCP tools (+$2–5/mo), Titan-v2 embeddings semantic
recall (~$0, brute-force cosine in Lambda). Credibility techniques ranked: (1) BSTS /
synthetic-control counterfactuals for interventions — the single highest-leverage rigor add;
(2) SCED standards (randomized start points + randomization tests, valid under
autocorrelation); (3) LLM-judge calibration (treat the quality-gate judge as an instrument
with measured error). Design patterns worth stealing: chess.com eval bar; Pudding
scrollytelling; Hades/Dark-Souls earned-progression honesty (low-n/UNSOLVED as dignified
states); deterministic generative-SVG fingerprints (glow that can't be faked); F1 density +
calm-tech periphery. Rejected as gloss/ceiling events: voice cloning, generative video.

## 5. Persona walkthrough verdicts (live, day 1 of cycle 7)

Delights: the Integrator ruling on a real board disagreement; the calibration page ("nobody
else grades their own AI in public"); supplements shipping counter-evidence; /method/cost;
the survival curve; coaches naming the prior failure mode. **Confirmed trust leaks** (live
API checks): `/api/snapshot` recovery 0%/red/sleep-null vs `/api/pulse` 96%/8.4h the same
morning; `brier_skill −0.0047` labeled "authoritative/90"; hero "19 data sources" vs platform
"26" vs `mcp_tools: 121` (registry ≈60); plus (rendered walkthrough) stale "first verdict
expected" date math, /method/wrong 4-vs-2, genesis-day brief saying "starting tomorrow",
day-1 scolding for reset-manufactured gaps, unlabeled cross-cycle ghost chips, and a **blank
OG/no-JS crawler surface** — the growth loop's first impression renders empty. One-missing-
things: subscriber = "run this on ME"; technologist = the calibration engine as an open
artifact; Matthew = **a coach that reaches out first**. Biggest ambition-vs-felt gap: the
machinery of proof is world-class while the proof itself reads 0.0 — and the reset's real
story ("attempt #7 of a serial restarter") leaks as generic cold-start.

## 6. The backlog (filed 2026-07-18)

Seven outcome epics — five new + upgrades to #718 (fulfillment half) and #1080 (coach
experience) — and ~40 scored stories on Now/Next/Later, all under label
**`review:frontier-2026-07-18`** (numbers in the label query; scores and cost flags in each
body). The NOW slice: truth-spine trust repair + honest badge semantics + armed cold-start;
resurrect the OG/no-JS growth surface; the Attempt-#7 frame + career-vs-season stats;
daylight the dark PERMA pillars; the (private) alcohol ledger; the felt-reality calibration
ledger. Run-rate if everything ships: ≈ +$6–11/mo, inside the ADR-063 ceiling at tier 0;
per-story flags on the Detective, 1M-context chronicle, Dispute Docket, nudges, and Mirror-v2.

Matthew's channel/creative asks folded in: Instagram/Bluesky syndication of the daily
fingerprint card; avatar-anonymized video diary with coach reactions (avatar approach = the
open design decision; external avatar services are cost+gloss events); a two-way WhatsApp/
Telegram "Coach Line" (also answers the nudge-channel question); theme-river visualization
(the design-system-honest word cloud) from the existing `enriched_themes`.
