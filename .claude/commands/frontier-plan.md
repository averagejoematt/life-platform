# /frontier-plan — the full-horizon review: from quantified self to quantified *life*

You are running a strategy + research + ideation session for averagejoematt.com, ending in a
stack-ranked backlog filed as GitHub issues. This is NOT a bug hunt (/fullreview) and NOT a
single-slice ship session (/uplevel). This is the session where we ask: **given everything this
platform already is, everything wellbeing science says a fulfilled human needs, and everything
AI/LLM technology has just made possible — what should this become next, and in what order?**

Run this in plan mode: research and synthesize first, present the ranked plan for approval,
file issues only after approval. Multi-agent orchestration (workflows, research fan-outs,
verification passes) is explicitly authorized for this session — use it. Check usage headroom
before any large fan-out.

---

## Phase 0 — Load the soul of the thing (before any opinion)

Read, in order: `docs/PLATFORM_NORTH_STAR.md`, `docs/SITE_MAP_AND_INTENT.md`,
`docs/DESIGN_SYSTEM_V5.md`, `docs/ARCHITECTURE.md`, `docs/SCHEMA.md`, `docs/BOARDS.md`,
`lambdas/source_registry.py`, the character engine + gamification model, and the ADRs that
define our integrity posture: **ADR-104 (honest numbers everywhere), ADR-105 (the rigor bar),
ADR-103 (complexity-posture ledger)**. Also skim the open backlog
(`gh issue list --label type:story --state open`) so ideas that already exist get upgraded,
not duplicated.

Internalize the thesis before critiquing it: this platform is a **causal-loop instrument** —
data → intelligence → coaching → behavior change → data — with one real human inside it,
in public. The differentiator is not the dashboards; it's that the loop is *closed*, *honest*,
and *narrated*. Every idea you generate must strengthen that loop or it doesn't rank.

## Phase 1 — Walk the entire site through three pairs of eyes

Do a full-surface walkthrough (every page in the site map, live) three separate times, as
three distinct personas. Use browser tooling or render-qa against live; capture what each
persona actually experiences, not what the code intends.

1. **The subscriber** — someone on a similar transformation journey who checks in weekly.
   What do they come back for? Where does the site give them something *actionable for their
   own life* vs. spectate-only? Where does trust build, where does it leak? What would make
   them evangelize it?
2. **The reader/technologist** — a drive-by from HN/Twitter who's seen a hundred QS
   dashboards. Within 90 seconds, do they understand this is different? Where is the "wait,
   how is it doing THAT?" moment? Where does it read as yet-another-Whoop-wrapper?
3. **Matthew himself** — the subject. Does the platform actually *transform* him, or report
   on him? Where does it change a decision he'd otherwise make? Where does the character
   progression feel earned vs. arbitrary? Where does it nag vs. coach?

For each persona: top 5 moments of delight, top 5 moments of friction/distrust, and the one
missing thing they'd pay for.

## Phase 2 — Ground in the science of a fulfilled human (not just a healthy body)

Deep-research (web, cited, adversarially verified) the current evidence base on human
flourishing, and build a **coverage map**: which pillars does the platform measure, model,
coach, and gamify today — and which are dark?

Frameworks to map against (extend as research warrants): PERMA (Seligman) · Self-Determination
Theory (autonomy/competence/relatedness) · the Harvard Study of Adult Development (relationship
quality as the #1 predictor) · hedonic vs. eudaimonic wellbeing · flow states · sleep/nutrition/
movement foundations · purpose & meaning · social connection & loneliness research · learning
and cognitive engagement · time affluence · financial security & money-wellbeing curves ·
nature exposure, gratitude, awe · stress/recovery balance.

Then audit our actual data against that map: sources in `source_registry.py`, the DynamoDB
schema, MCP tools, Monarch (finance), reading (Mind pillar), journal, social-connection trend,
State of Mind, Todoist. Classify every pillar: **measured & modeled / measured but dark /
measurable with an integration we don't have / genuinely hard to measure (design a proxy)**.
The "synapses" question is first-class: enumerate the cross-domain edges the platform should
understand (sleep→supplements→mood→journal sentiment→reading depth→connection→training→
finance→purpose) and mark which edges have real statistical machinery behind them today
(per the ADR-105 bar) vs. narrative hand-waving vs. nothing.

## Phase 3 — Know the field, then leave it

Parallel research sweeps (each blind to the others):
- **QS/biohacking products & projects**: Gyroscope, Exist.io, Bryan Johnson's Blueprint +
  Rejuvenation Olympics, Whoop/Oura/Levels/Eight Sleep AI coaching, Stephen Wolfram's personal
  analytics, howisFelix.today, notable open-source QS stacks. What do they do better than us?
  What do they all fail at (usually: cross-domain causality, honesty, narrative, the *life*
  beyond the body)?
- **Market & community**: biohacking/longevity market direction, QS community discourse, what
  audiences reward (Blueprint's virality mechanics, build-in-public dynamics), creator-led
  health products.
- **AI frontier**: what LLM/agent capabilities exist NOW that didn't when this site was
  designed — long-context reasoning over a whole life archive, multimodal (voice, vision,
  video), agentic tool-use, generative/adaptive UI, personal fine-tuning/memory systems,
  simulation and digital-twin modeling, forecasting with calibration. For each: the concrete
  feature it unlocks *here*.
- **Adjacent inspiration**: the best data-driven storytelling on the web (pudding.cool-class
  visual essays, F1/sports telemetry UX, game design progression systems that feel earned),
  and what a world-class creative director / behavioral scientist / causal-inference
  statistician would each say this site is missing.

## Phase 4 — Ideate past the possible

Now generate. Fan out idea-generation across lanes, and explicitly include ideas that don't
exist anywhere yet — imagine the panel: a creative director, a complexity scientist, a game
designer, a causal-inference researcher, an AI-native product founder, a subscriber. Lanes
(non-exhaustive — invent lanes if the research demands):

- **New views & visual language** — views of a whole life no one has built
- **New math & models** — causal inference across domains, calibrated forecasting, a personal
  digital twin, variance-derived personal thresholds, counterfactual "what-if" engines
- **Data model & new signals** — missing pillars from Phase 2, new integrations, designed
  proxies for the hard-to-measure (connection quality, purpose, awe)
- **The AI coaches upleveled** — memory, disagreement, track-record-weighted authority, voice,
  proactive intervention, coach-vs-coach adversarial review of each other's advice
- **The character engine & gamification** — progression that is *defendable*: every stat
  change traceable to evidence, and calibrated against felt reality (design the mechanism
  that checks the character sheet against Matthew's subjective self-report — trust is the product)
- **Community & the journey template** — how a reader becomes a participant: follow-along
  protocols, their-data-vs-mine overlays, cohorts, the "fork my life-stack" story
- **Narrative & wow** — the moments that make a technologist say "this is the frontier of
  LLM + personal data," provable on the site itself
- **Behind the scenes** — pipeline, evaluation, self-healing, whatever makes the machine
  itself part of the exhibit

Every idea must state: which persona it serves, which flourishing pillar / causal-loop stage
it strengthens, and how it survives ADR-104/105 (no fabricated numbers, uncertainty shown,
n stated). An idea that needs dishonest data to be impressive is dead on arrival.

## Phase 5 — Verify, rank, and file

1. **Verify**: run the finding-verifier discipline on factual claims (site behavior, data
   coverage, competitor claims) — historically ~50% of first-pass findings are wrong.
2. **Stack-rank** every surviving idea with an explicit rubric, scored and shown:
   **Transform-Matthew impact × Wow/differentiation × Trust & rigor fit × Loop-closure value
   ÷ Effort**. Cost is NOT a ranking factor, but **flag** any idea that meaningfully raises
   the monthly run rate (ADR-063 ceiling context) with a rough $/mo estimate.
3. **Structure into outcomes**: group ranked ideas under 4–8 named outcome epics (each epic =
   a promise to a persona, not a tech theme).
4. **Present the plan** (plan-mode exit): the coverage map, the ranked list with scores, the
   epic structure, and what you'd ship first and why.
5. **On approval, file to GitHub** per ADR-099 via the issue-filer contract: `type:epic` per
   outcome, `type:story` per idea with score line, Now/Next/Later milestones matching the
   ranking, cost flags in-body, links to the research artifacts. Upgrade/dedupe against
   existing open issues rather than double-filing.

Deliverables: the ranked backlog live in GitHub Issues, plus one synthesis document
(`docs/` or handover) capturing the flourishing coverage map and the competitive/frontier
findings so future sessions inherit the research, not just the issue titles.
