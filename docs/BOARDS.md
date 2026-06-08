# Life Platform — Board of Directors Reference

> Three expert boards advise different aspects of the platform. Invoke by name or board type.
> This file is the single reference for all board composition. Claude Code should read this when board input is needed.
> Last updated: 2026-05-19 (v8.0.0). Personal Board roster cross-checked against `s3://matthew-life-platform/config/board_of_directors.json`.

---

## 1. Personal Board of Directors

**Purpose**: Advise Matthew as an individual on health, longevity, behavior, mental health, and social connection.
**Invocation**: "personal board" or by member name
**Config**: `s3://matthew-life-platform/config/board_of_directors.json` — loaded by `lambdas/board_loader.py` (shared layer).
**Consumed by**: daily brief, weekly digest, monthly digest, nutrition review, chronicle, observatory renderer.
**Convenes**: Daily brief, weekly digest, monthly digest, nutrition reviews, chronicle interviews, observatory pages.

Note on identity: the JSON config keeps **legacy keys** (e.g. `peter_attia`, `paul_conti`, `andrew_huberman`, `rhonda_patrick`) holding **fictional replacement personas** for backward-compatibility with existing prompts. The displayed name on every public surface is the fictional persona — never the real public figure. The legacy keys are mirrored by canonical keys (`victor_reyes`, `nathan_reeves`, `integrator`, `amara_patel`) used by observatory pages.

### Active personas (20 distinct in the live config; representative set below)

| Display name | Title | Type | Config key(s) | Domains |
|--------------|-------|------|---------------|---------|
| Dr. Sarah Chen | Sports Scientist | fictional | `sarah_chen` | Training, exercise physiology, periodization, recovery |
| Dr. Marcus Webb | Nutritionist (panel) / Macros (long-form) | fictional + legacy `layne_norton` | `marcus_webb`, `layne_norton` | Nutrition, macros, meal timing, deficit sustainability |
| Dr. Lisa Park | Sleep Scientist & Circadian Specialist | fictional | `lisa_park` | Sleep architecture, circadian rhythm, sleep debt |
| Dr. James Okafor | Longevity & Preventive Medicine | fictional | `james_okafor` | Biomarkers, trajectory analysis, ASCVD risk |
| Coach Maya Rodriguez | Behavioural Performance Coach | fictional | `maya_rodriguez` | Habit formation, motivation, knowing-doing gap |
| Dr. Amara Patel | Micronutrients, Genome & Longevity | fictional (replaces Patrick) | `rhonda_patrick`, `amara_patel` | Nutrigenomics, supplementation, SNP analysis |
| Dr. Victor Reyes | Metabolic Health & Longevity | fictional (replaces Attia) | `peter_attia`, `victor_reyes` | CGM, body composition, exercise medicine, DEXA |
| Dr. Kai Nakamura | Neuroscience & Protocols / Integrator | fictional (replaces Huberman) | `andrew_huberman`, `integrator` | Circadian biology, dopamine, stress protocols, cross-domain integration |
| Dr. Nathan Reeves | Psychiatrist — Self-Structure | fictional (replaces Conti) | `paul_conti`, `nathan_reeves` | Defense mechanisms, grief, identity, self-compassion |
| Dr. Vivek Murthy | Social Connection & Loneliness | real_expert | `vivek_murthy` | Male isolation, community health, belonging |
| Dr. Henning Brandt | Biostatistician — N=1 Research | fictional | `henning_brandt` | Statistical rigor, confidence intervals, false-positive risk |
| Elena Voss | Embedded Journalist — "The Measured Life" | narrator | `elena_voss` | Weekly chronicle author |
| Margaret Calloway | Senior Editor — Longform | fictional | `margaret_calloway` | Edits Elena's work, narrative structure, prose craft |
| The Chair | Board Chair — Verdict & Priority | meta_role | `the_chair` | Cross-domain synthesis, one priority, verdict |

**Source of truth**: this table is derived from the live S3 config. To re-verify:
```bash
aws s3 cp s3://matthew-life-platform/config/board_of_directors.json - | python3 -c "import sys, json; d=json.load(sys.stdin); [print(f\"{k} → {v.get('name','?')} ({v.get('type','?')})\") for k,v in d['members'].items()]"
```

**Backlog addition**: Sports Medicine / Movement Quality specialist — injury prevention, biomechanics of training at higher body weight, joint health screening.

**Interim placeholder (2026-05-31, live)**: "Dr. Iris Tanaka — Sports Medicine (interim)" — narrow mandate (don't-get-hurt only — high-skill-exercise veto, joint-friendliness rubric, re-entry sign-off). Appointed in ADR-066 and added to `config/board_of_directors.json` (key `iris_tanaka_interim`). Retire the entry when a named Sports Med voice fills the real seat; the `_sunset_trigger` field in the config flags the procedure.

---

## 2. Technical Board of Directors

**Purpose**: Review architecture, security, code quality, data models, AI trustworthiness, cost, and operational reliability.
**Invocation**: "tech board" or by member name
**Convenes**: Architecture reviews, deploy decisions, design reviews, incident response
**Sub-boards**: Architecture Review (Priya, Marcus, Yael, Jin, Elena, Omar) | Intelligence & Data (Anika, Henning, Omar, Elena) | Productization (Raj, Sarah, Viktor, Dana, Priya)

| Name | Title | Archetype | Standing Question |
|------|-------|-----------|-------------------|
| Dr. Priya Nakamura | Principal Cloud Architect | Netflix/Stripe distributed systems | "Is the system shape right?" |
| Marcus Webb | AWS Serverless Architect | Lambda team alum, fintech | "Is this the right AWS implementation?" |
| Yael Cohen | Cloud Security + IAM | NSA → Google Cloud → CISO | "How could this fail or be exploited?" |
| James "Jin" Park | SRE / Production Operations | Google SRE lead | "What breaks at 2 AM?" |
| Dr. Elena Reyes | Staff Software Engineer | Principal at GitHub | "Could another team own this?" |
| Omar Khalil | Data Architect | Databricks, Epic health data | "Is the data model coherent?" |
| Dr. Anika Patel | AI/LLM Systems Architect | LLM research, AI platforms | "Is the intelligence layer trustworthy?" |
| Dr. Henning Brandt | Statistician | Cochrane Collaboration biostatistician | "Are the conclusions actually valid?" |
| Sarah Chen | Product Architect / PM | VP Product at Stripe | "Is this solving the right problem?" |
| Raj Srinivasan | Technical Founder / CTO | Serial founder, health data | "What's the wedge? Where are you fooling yourself?" |
| Viktor Sorokin | Adversarial Reviewer | Amazon "Principal of No" | "Is this actually necessary?" |
| Dana Torres | FinOps / Cloud Cost | AWS cost optimization | "What does this cost at scale?" |

---

## 3. Product Board of Directors

**Purpose**: Advise on UI/UX, customer journey, audience growth, new features, monetization, vision, story, throughline, and content strategy.
**Invocation**: "product board" or by member name
**Convenes**: Website reviews, feature planning, launch strategy, content calendar, growth reviews
**First convened**: Website Strategy Review #3 (2026-03-23)

| Name | Title | Archetype | Focus | Standing Question |
|------|-------|-----------|-------|-------------------|
| Mara Chen | UX Lead | ex-Spotify/Peloton, health app IA | Information architecture, user flows, mobile experience, accessibility | "Can someone use this without instructions?" |
| James Okafor | CTO / Technical Architect | Full-stack CTO, health tech | Technical feasibility, system design for product features, API design, performance | "Can we build this without breaking what exists?" |
| Sofia Herrera | CMO | DTC health brands, Peloton/Whoop marketing | Brand positioning, messaging, shareability, audience segmentation, monetization paths | "Would someone share this? Would they pay for it?" |
| Dr. Lena Johansson | Longevity Science Advisor | Research scientist, published longevity author | Scientific credibility, medical accuracy, evidence standards, N=1 methodology defense | "Is this scientifically defensible?" |
| Raj Mehta | Product Strategist | VP Product at a health tech unicorn | Feature prioritization, engagement loops, retention, product-market fit, roadmap | "Does this move the needle on the metric that matters?" |
| Tyrell Washington | Web Designer / Brand | Award-winning health/wellness web design | Visual design, brand consistency, design system, dark/light mode, responsive | "Does this look and feel world-class?" |
| Jordan Kim | Growth & Distribution Lead | ex-Substack growth team, 100K health newsletter | Subscriber acquisition, SEO, social distribution, email funnels, onboarding, community | "Will this get shared? Will this convert?" |
| Ava Moreau | Content Strategist | ex-editorial lead at health media co, newsletter operator | Content calendar, format strategy (cards/newsletter/long-form/social), repurposing, Elena pipeline | "What's the content engine that runs without Matthew?" |

### Product Board Dynamics

**Healthy tension pairs** (by design):
- **Mara (simplify) vs Raj (add features)** — UX purity vs product depth. Prevents both over-simplification and feature bloat.
- **Sofia (marketing appeal) vs Lena (scientific rigor)** — shareability vs accuracy. Prevents both dry academic content and clickbait.
- **James (technical constraints) vs Tyrell (design ambition)** — what's buildable vs what's beautiful. Prevents both ugly pragmatism and impractical polish.
- **Jordan (growth tactics) vs Ava (content quality)** — distribution speed vs editorial standards. Prevents both content spam and beautiful-but-invisible work.

**Decision framework**: When the board disagrees, the tiebreaker is the throughline — does this help a visitor connect the story from any page to any other page? If yes, it ships. If no, it goes to backlog.

---

## Board Boundaries

| Question type | Board |
|---------------|-------|
| "Should I add berberine to my stack?" | Personal |
| "Should the IAM role use least privilege?" | Technical |
| "Should the supplements page group by purpose or timing?" | Product |
| "Is my sleep protocol working?" | Personal |
| "Should we use DynamoDB or S3 for this?" | Technical |
| "How do we get to 500 subscribers?" | Product |
| "Am I overtraining?" | Personal |
| "Is the Lambda cold start acceptable?" | Technical |
| "What page should a new visitor see first?" | Product |

Each board stays in its lane. The Personal Board never opines on CSS. The Technical Board never opines on whether a page "feels right." The Product Board never opines on IAM policies.

---

## How to Invoke

In any Claude session (claude.ai or Claude Code):
- **"Ask the personal board about my sleep protocol"** → Personal Board convenes
- **"Tech board review this Lambda change"** → Technical Board convenes
- **"Product board — should we build the Data Explorer or Milestones first?"** → Product Board convenes
- **"All boards — is the platform ready for public launch?"** → All three convene with their respective lenses

---

## Coach Intelligence (related, but separate)

The Personal Board personas above appear in the **email + observatory surface**. The platform also runs an **8-agent Coach Intelligence pipeline** (ADR-047, ADR-055) with internal coach IDs that drive the underlying deterministic computation and stateful memory. The two systems are connected (coaches contribute to brief sections), but the IDs are different.

Coach IDs (from `lambdas/coach_computation_engine.py:COACH_IDS`):
`dr_johansson` · `fitness_coach` · `nutrition_coach` · `mind_coach` · `sleep_coach` · `body_comp_coach` · `lifestyle_coach` · `recovery_coach`

Each coach maintains episodic memory under `COACH#<coach_id>` partitions, with cross-coach summary under `ENSEMBLE#`, narrative arcs under `NARRATIVE#`, and prediction outcomes under `PREDICTION#` / `LEARNING#`. Prediction loop closed end-to-end per ADR-055.

---

**Verified:** 2026-05-19
