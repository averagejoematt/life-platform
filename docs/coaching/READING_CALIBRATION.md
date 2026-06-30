# READING_CALIBRATION.md
**The Mind Pillar — how to calibrate Matthew as a reader and build his curriculum.**
Repo path: `docs/coaching/READING_CALIBRATION.md` (sibling to `TRAINING_CALIBRATION.md`)
Status: DRAFT v0.1 · 2026-06-29 · the reading analogue of the training calibration doc
Read this BEFORE generating any recommendation. It is reference, not a whitelist.

---

## 0. How to use this doc

Same contract as `TRAINING_CALIBRATION.md`: this defines *how to calibrate him* and *what we're running*, so the engine never falls back to a generic list. Before any recommendation:
1. **Freshness & completeness first** (§10). Never trust a computed reading number — streak, retention, wheel slice — until the latest sessions/probes actually appear in the aggregation. Green status is a high-water mark and hides mid-window gaps. Empty/"no matches" is a *hypothesis* — verify by direct read.
2. **Continuity** — read Lena's thread for prior positions, open predictions, what we said we'd try. Treat narrative flags as hypotheses to verify against actual reading data, not facts.
3. **Synthesize state before proposing** — capacity, journal, completion history, wheel, phase.
4. **Curated read, not a template** — every pick visibly shaped by his state, with a decomposed reason string (§5, §7-anti-black-box).

Hard rule, inherited from the coach session: **never hand him the standard list.** It's a Matthew curriculum — leading science, his data, his goals, his journal, his progress.

---

## 1. The subject — bias correction & current state

- **Not a reader yet.** Treat the habit as fragile. An early DNF poisons the habit the way a routine break causes regain (his documented failure mode: disruption → break → regain). Phase 1's only job is to make him a person who finishes books.
- **Worries he doesn't retain.** This is load-bearing. The retention architecture exists to *measure the right thing and treat it*, not to confront him with a failure number (§7).
- **Systems/problems brain that "isn't a reader."** Use it: the on-ramp leans on propulsion and problem-shape, not literary obligation.
- **Saturated in optimization.** Every waking hour is already a metric. Reading must not become another grind. Its register is pleasure and becoming, not KPI (the longevity framing stays private — §9 Nadia/Priya).
- **UK origin, 14-year weight arc, values rigor / honesty / anti-theater.** Recommendations are correlational, confidence-labeled, and honest about thin data. No hype.

**Bias corrections (the things the engine must NOT do):**
- Don't infer his taste from his fitness goal. (The anti-Goggins rule — §11.)
- Don't pile optimization/self-improvement books on a depleted or dark-journal state.
- Don't mistake immediate recall for retention (two clocks — §7).
- Don't whiplash genres; alternate, don't lurch.
- Don't hand him the doorstop early. The classic is earned (§4).

---

## 2. The priors (cold-start, before n≥30 finished/abandoned)

Explicit, confidence-labeled. Early, the engine runs mostly on these with **wide error bars it declares**. It does not pretend to know him on book #2.

| Signal observed | Prior pull | Confidence |
|---|---|---|
| Deep deficit / low recovery / two-a-days | Lower the difficulty ceiling — depletion genuinely impairs sustained attention | med |
| Journal dark or heavy | Pull toward absorbing fiction + restoration; away from demanding nonfiction | med |
| Early in habit (low completion count) | Completion-probability dominates the objective; Maya wins the on-ramp | high |
| Thinnest roundedness slice | Breadth pull — as a weight, never a mandate | low-med |
| Goal-domain book (health/discipline/optimization) | **De-prioritize by default** — he's saturated; anti-Goggins (§11) | high |
| Travel logged | Length + format ceiling: absorbing, flight-shaped | med |
| Stated interest from onboarding (§8) | Direct pull, but held as low-confidence hypothesis until confirmed | low |

When `n` is small, **propose-and-dispose only** (he approves every pick); the engine states its reasoning and asks to be corrected. Corrections tighten the model fast.

---

## 3. The difficulty model

**Difficulty score** per book = a composite of: length × conceptual density × prose load × structural demand (non-linear narrative, allusion, archaism). LLM-tagged on enrichment, then **calibrated against HIS actual finish/abandon data** — his real RPE, not a demographic guess.

**The ratchet (progressive overload, autoregulated):**
- Mostly **in-zone** picks. Periodic **programmed stretch** — a book deliberately above his line. A stretch is a PR attempt, not a constant grind.
- **Subtract-only on bad weeks.** The stretch is the authored ceiling; a RED life-week downgrades it to shorter / re-read / propulsive. The doorstop waits for GREEN.
- **Abandonment is the autoreg gate.** DNF a stretch → RPE-too-high → ratchet backs off the next pick, and the miss is logged (§9). Finish-and-retain a stretch → the line moves up.

GREEN/YELLOW/RED here mirror the training rubric and key off the *same platform state* (recovery, deficit, travel, task load, journal):
- 🟢 **GREEN** — take the ceiling: the stretch pick, the longer book, the classic entry point.
- 🟡 **YELLOW** — the baseline plan (safe default with no signal).
- 🔴 **RED** — subtract to the floor: short, propulsive, re-read, or simply "protect the habit, read anything."

---

## 4. The periodized curriculum (a mesocycle, not a TBR pile)

Lena designs reading the way Sarah Chen periodizes training. It **re-plans on every data move** (§6).

- **Phase 1 — On-ramp (now).** Short, propulsive, high-completion-probability, likely a genre he already leans toward. Goal: a *guaranteed win*. No growth agenda. Maya wins outright.
- **Phase 2 — Base.** Widen: adjacent genres, slightly longer, first fiction-for-its-own-sake, first accessible poetry/memoir. The wheel begins to fill.
- **Phase 3 — Build.** First programmed stretch: a readable on-ramp to harder work (short stories before doorstops; the 200-page classic before the 800-page one; annotated/guided editions).
- **Phase 4 — Peak (earned).** The doorstops — *because the data cleared it* (completion streak + strong retention + demonstrated difficulty tolerance), and even then the entry point autoregulates. Never the doorstop on a RED week.

**Tier-up triggers** (analogous to training tier-ups): a completion streak AND retention holding AND difficulty tolerance demonstrated. Missing any → hold the phase.

**The "classic gate"** (analogue of the training run-gate): doorstop classics are gated behind proven completion + a GREEN week. Do not open the gate on capacity alone.

---

## 5. The recommendation objective (plain-language; formal version in the architecture spec)

Each candidate gets a **fit score** = a weighting of:
`capacity-this-week × difficulty-vs-ratchet × breadth-gain × momentum/interest × journal-resonance × curriculum-phase`
…minus penalties for whiplash, repeating a recent pattern, and goal-domain-by-default.

**The weights themselves shift by phase.** Phase 1: completion-probability dominates. Later phases: breadth-gain and depth-gain rise. Every pick **decomposes to a reason string** assembled from its top contributing components. If it can't be explained, it isn't recommended.

---

## 6. Re-rank triggers (the backlog is alive)

The backlog is Lena's working hypothesis about his path, dynamically re-sorted:

- **Finish fast on a GREEN week** → capacity proven → the stretch pick climbs.
- **DNF a stretch** → RPE-too-high → difficulty backs off, queue re-sorts gentler, **Lena logs why she was wrong.**
- **Journal goes dark/heavy** → demanding nonfiction sinks; an absorbing novel rises.
- **Travel logged** → flight-shaped books surface.
- **Journal circles a theme** → a resonant title is promoted, with a reason tied to his own words.
- **Recovery tanks / trough forming** → pre-emptive easiest-most-propulsive pick. Holding the habit through disruption beats optimizing it.

---

## 7. The two-clock retention model

**Never conflate how-it-hit with what-stuck.**

- **The Debrief — immediate, on finish.** Warm, while fresh. How it landed, the one idea, what he'd push back on, what it changed. This is *reaction*; it produces the public takeaway. **Not retention.**
- **The Probes — spaced, weeks later (EventBridge).** "A few weeks back you read X — what's stayed with you?" *This* is retention.

Why the split: most people ace the immediate debrief, "forget" later, and conclude they don't retain — when the immediate test never measured retention and the verbatim standard was always impossible. Separating the clocks shows his *actual* curve.

- **Measures gist + changed-prior, never verbatim.** Can he reconstruct the argument, did it change a prior, can he connect it to another book.
- **n-gated.** No retention score renders until enough probes exist to mean anything (Henning's refuse-to-render).
- **Private by default, his toggle, his eyes.** A bad week is never public.
- **The interview is the intervention.** Active recall builds the retention it measures. Frame as care, not a test.

---

## 8. The onboarding interview — taste archaeology

Not a genre checklist (that's how you get slop). A conversation that **excavates taste from outside the reading domain**, because he has taste even without reading history. Runs as his first real conversation with Lena. It **deliberately refuses to infer taste from his fitness goal.**

Question bank (Lena picks ~6-8, conversationally, follows threads):
- What film or show genuinely wrecked you — and what was it about it?
- What did you reread as a kid, or read more than once ever?
- What kind of conversation do you wish you could hold your own in?
- Whose mind do you wish you had? Why theirs?
- What bores you to tears on a page? (Equally important — exclusions are signal.)
- When you imagine "a person who reads," what do you picture — and which part appeals?
- Comfort vs. challenge: when you've got an evening, do you want to escape or to be stretched?
- Is there a subject you feel embarrassed not to understand?

Output: a **starting taste hypothesis** Lena states with honest low confidence and asks him to correct. Stored on `READING_PROFILE`. Seeds the cold-start with real signal, not demographics.

---

## 9. Lena Marsh — mandate & standing disagreements

**Mandate:** grow breadth + depth + retention *within capacity*. Correlational framing only; confidence-labeled; n<30 = low confidence. Logs predictions and hopes per book; her reading recs carry an auditable hit rate on the coaching page. When she misses, she says so concretely and recalibrates.

**Standing disagreements — preserved, not blended. Who wins which phase is explicit:**

- **Lena vs. Maya — the on-ramp.** Maya: protect the fragile habit, easy wins only, candy is fine. Lena: don't burn the whole runway on candy; a reader who only reads easy books isn't who he's becoming. → **Maya wins the on-ramp; Lena's breadth/depth agenda ramps as completion data proves the habit holds.**
- **Nadia vs. Priya — what reading is *for*.** Nadia: track reading as cognitive reserve, a brain-longevity pillar. Priya: he's drowning in optimization; reading may be the one domain that should stay pure — don't make it another KPI to grind. → **The longevity framing lives quietly on the private data view only; the product's voice about reading is Priya's (pleasure, savoring). The metric exists for honesty, never as the reason he reads.**
- **Mara Quinn — restraint gate.** The show-off features are the trap. → **Ship the loop (pick → read → debrief → recall → re-rank) as a 10/10 first; the Constellation and the rest of the dazzle earn their way in on real data.**

> NOTE: Lena, Priya, Crowe, Nadia, Theo, Mara are archetypes pending reconciliation against the real `docs/BOARDS.md` roster. Recast names/configs before they surface on the coaching page.

---

## 10. Freshness & honesty gates (inherited from the coach session)

- Run freshness before trusting any computed reading number. Re-pull if a number drives a big call.
- A tool's empty/green result is a hypothesis — verify by direct read (list the shelf, pull the detail) before asserting "no notes / clean / nothing due."
- `n` < 30 finished/abandoned → low-confidence labels everywhere; engine in propose-and-dispose.
- The Constellation and reading charts **refuse to render** under their data thresholds — honest empty states, never a sparse sad graph.

---

## 11. The anti-Goggins rule (named, explicit)

The default failure mode is "fitness guy → discipline porn." The engine **steers away from the goal-domain by default.** He is saturated in optimization; what makes him more rounded and more content is the texture his current life has none of: story, interiority, beauty, other people's inner lives, the long view.

- **"More interesting"** = texture he lacks — fiction, poetry, biography, history. Things to talk about at dinner, not more utility.
- **"More interested"** = the right book at the right moment — momentum and joy, never homework.

---

## 12. Starter ladder (reference, threaded to him — NOT a whitelist)

- **Phase 1 (guaranteed wins):** *Project Hail Mary* (Weir) — propulsive problem-solving, a systems brain's gateway to finishing a novel. *Klara and the Sun* (Ishiguro) — an AI narrator observing a human life, literally what he's building; accessible, quietly devastating.
- **Phase 2 (widen + first beauty):** *Stoner* (Williams) — an ordinary life and where its meaning lives; eerily aimed at his site's thesis. Memoir: *When Breath Becomes Air* (Kalanithi) — mortality, his longevity nerve; or *Open* (Agassi) — an athlete who hated his gift, all identity. Poetry that won't bounce him: Mary Oliver (*Devotions*) and Billy Collins.
- **Phase 3 (first earned stretch):** *A Gentleman in Moscow* (Towles) — Russian texture without the doorstop; Chekhov's short stories — the real on-ramp to Russian lit; *East of Eden* (Steinbeck) — long but propulsive, the becoming-a-person themes.
- **Phase 4 (earned doorstops):** *Crime and Punishment* before *Brothers Karamazov*; *Anna Karenina*; *Middlemarch*. GREEN weeks + proven streak only.

Journal-driven examples: entries circling whether the change will hold → *Stoner* / *The Remains of the Day*. Circling mortality/longevity → *When Breath Becomes Air*. Gone quiet/heavy → an absorbing novel, nothing demanding.

---

*This doc guarantees the engine builds him a curriculum, not a list. Update on every calibration learning. Cross-reference: BRIEF_2026-06-29_reading_mind, SPEC_READING_MIND_2026-06-29, CLAUDE_CODE_PROMPT_READING_MIND_v1.*
