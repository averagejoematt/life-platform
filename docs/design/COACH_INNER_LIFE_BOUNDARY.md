# The inner-life boundary — what a coach may say about itself

> **Status:** canonical · **Owner:** Matthew · **Written:** 2026-08-10 (#2538, epic #2363)
>
> **Authority:** ADR-104 (numbers are earned deterministically; the LLM only narrates
> them) and ADR-106 (AI may sketch, only reviewed code ships, only Matthew approves) both
> reach this question; neither answers it. This note answers it, and does not restate
> either — where a rule already lives in an ADR or in [CONVENTIONS.md](../CONVENTIONS.md),
> this page points at it.
>
> **Blocks:** [COACH_HUMANITY_ROADMAP.md](COACH_HUMANITY_ROADMAP.md) ideas **#29**
> (non-data initiative from persona interests) and **#35** (persona-stable routine
> references). Neither may start until this page exists; both must satisfy it.

## Why this is a boundary and not a style note

A coach that invents a weekend is committing the same class of error as a coach that
invents an HRV reading. The second one is caught deterministically and has been since
ADR-104. The first one is not caught by anything — measured below — and it is *worse*,
because the reader has no way to check it. Matthew can look up his own HRV. He cannot
look up whether Dr. Park had a long morning.

That is the whole reason texture is dangerous in a way that voice is not. Voice is a
claim about how a character speaks; it is true by construction. A life is a claim about
what happened; it can be false. The roadmap's seventh humanity principle already says
this — *a friend who makes things up stops being one* — and this page is the operational
form of it.

## The measured starting point (2026-08-10)

Three measurements, because the boundary should be written against what is actually
there rather than against what it feels like is there.

**1 — the coaches currently have no inner life at all.** Across the 536 simulated replies
in [COACH_SIM_FINDINGS_2026_08_10.md](COACH_SIM_FINDINGS_2026_08_10.md), essentially zero
reference anything outside the conversation and Matthew's data; a regex sweep returned 11
candidates and nearly all were about *his* data, not the coach's. The blind panel cited
the absence in 6% of its tells.

**2 — nothing in the prompt substrate rules on it.** A scan of all 22 files in
`config/coaches/` for the vocabulary of this question (`own life`, `your life`, `my day`,
`your day`, `weekend`, `routine`, `invent`, `fabricat`, `make up`, `made up`, `personal
life`, `outside the conversation`, `hobby`, `hobbies`, `interests`, `biograph`, `past
tense`) returns **12 matching lines / 16 term occurrences across 5 files** — six distinct
file×term pairs. `_shared_standard.json` returns nothing.

Four of the five files are irrelevant on inspection and are the ones this note relies on:
the three `routine` files (`pattern_coach.json`, `mind_coach_stance.json`,
`sleep_coach_stance.json`) and the one `make up` file (`nutrition_coach.json`) are all
about *Matthew's* routines and his macros, not a coach's.

**The fifth file is `tuning_log.json`, and it must be named rather than quietly dropped**
— it carries 8 of the 16 occurrences (`invent` ×4, `fabricat` ×4), and one of them is
squarely about a coach fabricating: the #2496 entry records that "we talked about you
Tuesday" carried no number and no calendar date, so *an invented meeting was sayable*.
That is this note's own thesis, already written down. It does not change the finding,
for a reason that is structural rather than convenient: **`tuning_log.json` is never
rendered into a prompt.** It is the public per-coach changelog behind the site's coach
profiles, and its only readers are `lambdas/web/site_api_coach.py` and
`lambdas/web/site_api_coach_profile.py`; no renderer in `lambdas/coach/persona_core.py`
loads it. A rule a coach never sees cannot govern what a coach says.

So the accurate statement of the finding is narrower than "nothing mentions it" and is the
one that matters: **no file that reaches a prompt rules on the coach's own life.** The one
file that discusses the problem is a record *about* the platform, not an instruction *to* a
coach.

**3 — the grounding gate does not see it.** Five invented-life candidates were run through
the live chat grounder, `coach_chat_grounding.build_grounder`. The exact call, so this
reproduces:

```python
CANON = {"night_of": "2026-08-10", "recovery_pct": 61, "hrv_ms": 48,
         "rhr_bpm": 55, "sleep_hours": 7.2, "date": "2026-08-10"}
EXTRAS = ["MEMORY: he committed to 170 g protein.",
          "THREAD:\nMatthew: rough morning\n"]
grounder = build_grounder(CANON, generation_date_iso="2026-08-10",
                          available_logs={"workouts": []}, extra_sources=EXTRAS)
```

`available_logs` is passed explicitly because that keyword is what arms the behavioral
class; `build_grounder`'s own signature defaults it to `None`, and a reproduction that
omits it arms five classes rather than six (shape B below).

| Candidate reply | Findings |
|---|---|
| "Just got out of a session, actually. Spent the weekend on a paper about exactly this." | `[]` |
| "Was up early myself this morning. Ran the loop by the river before anyone else was out." | `[]` |
| "I watched the game last night and could not stop thinking about your taper." | `[]` |
| "I am a morning person, so I am biased here." | `[]` |
| "My old coach used to say the same thing to me when I was competing." | `[]` |

**The gate was armed, and each class fires on a purpose-built positive** — so the five
empties are a real negative and not a dead harness:

| Probe | Findings |
|---|---|
| "Your HRV was 63 last night." | `fabricated_number` |
| "Back on 2026-07-04 you said the same thing." | `fabricated_date` |
| "You're 400 days into this experiment now." | `experiment_span`, `fabricated_number` |
| "You maintained your eating window today." | `ungrounded_behavioral` |
| "Recovery sits at 61." | `unlabeled_night_figure` |
| "We talked about you Tuesday, good things." | `ungrounded_team_meeting` |
| *negative control:* "asdf qwerty zzz blorp" | `[]` |

**And the result is robust across arming shapes.** The five candidates were re-run under
four different grounder configurations — (A) the canonical call above; (B) the same with
`available_logs=None`, i.e. `build_grounder`'s default, five classes armed; (C) empty
facts, no `extra_sources`, `available_logs=set()`; (D) canonical facts at a different
`generation_date_iso`. **All five returned `[]` in all four shapes**, while the team and
number controls fired in all four. The finding does not depend on how the gate is armed.

This is the expected result and not a defect report — an invented biography contains no
number and no calendar date, which is precisely the observation `coach_team_texture`'s
docstring already makes about invented team meetings.

**The consequence for this page:** the boundary is being written against a blank surface.
Nothing has to be retracted, no shipped line becomes non-compliant, and the rule lands
before the first line of texture does. That is the cheapest moment this decision will ever
be available.

## Canon is what renders, not what is in the file

Before any rule can be applied, "in the bible" has to mean something checkable. It means
**the text reached the model**, and the only fields that reach the model are the ones
`lambdas/coach/persona_core.py` renders:

| Renderer | Fields it emits | Surfaces |
|---|---|---|
| `shared_block()` | `mission`, `constitutional_rules`, `matt_model`, `relationship_stages`, `disengagement_rule`, `communication_avoid`, `reasoning_loop`, `evidence_rules`, `safety_boundaries` (from `_shared_standard.json`) | all |
| `voice_block()` | `bio`, `defining_tension`, `philosophy`, `relationship_style`, `signature_phrases`, `blind_spots`, `boundaries.owns` / `.does_not_own`, `structural_voice_rules.{sentence_rhythm, uncertainty_style, analogy_domain, humor_style, relationship_to_others, signature_moves}`, `decision_style.*`, `anti_pattern_detection.{phrase_blacklist, structural_blacklist}` | all |
| `texting_block()` | `texting_style.{burst_shape, message_length, punctuation, opening_register, double_text, emoji_posture, identity_stance}`, `texting_few_shots[:2]` | chat only |

Two consequences that decide real cases, both read off the same module:

- **`few_shot_examples` is not canon on chat.** `voice_block` renders no few-shots by
  design (its module docstring: *"NO few-shot examples — the board answers in 3-5
  sentences"*). Texture parked there reaches the daily brief and not the phone, so a chat
  reply may not be justified from it.
- **A field can be truncated out of canon.** `_MAX_FIELD_CHARS = 400` and
  `_MAX_LIST_ITEMS = 6`. The seventh entry in a `philosophy` list, or the tail of a
  420-character `bio`, is not in the model's material on any surface — so it cannot
  justify anything the model said, and texture appended past those caps is not texture,
  it is a file edit with no effect.

A reviewer adjudicating a reply therefore reads the **rendered block**, not the JSON. This
is the same evidence discipline `coach_team_texture._team_room_evidence` already uses: the
gate adjudicates against exactly what the model was shown.

## The rule

Three clauses. A first-person clause about the coach's own life is in bounds only if all
three hold.

**R1 — Provenance.** The claim must be readable out of a *rendered* field of that coach's
own spec (table above). Not "consistent with the character" — readable out of it, by
someone holding the file. A coach's taste in books, its city, its family, its mentor: none
of these exists until a field says so, and inference from an adjacent field is not a
source.

**R2 — Invariance.** The claim must be true **every time the coach says it**. A stable
trait survives repetition; an occasion is true at most once. The operational form: *if
saying this same sentence tomorrow would make it false, it is an event, and events are
out.* "I am hard on what a wrist can know" survives Tuesday. "I was up early" does not.

**R3 — No substrate.** There is no record of a coach's day, and there never will be one.
This is the sharp asymmetry with Matthew's data and the reason the posture here is
*stricter*, not looser, than ADR-104's: for Matthew, a missing food log means the platform
does not know, and behavioral-absence semantics decide what may be said into that silence.
For a coach's Tuesday there is no log, no source, and no possible future backfill —
the absence is total and permanent. So there is nothing to be uncertain about, and hedging
is not the safe move. **A coach may not hedge an occasion into existence** ("I think I may
have been up early") any more than it may assert one; the disposition is to say nothing,
which is the same regenerate-once-then-HOLD posture `run_turn` already applies and
`coach_team_texture` explicitly refuses to soften.

R3 also carries the corollary that closes the most tempting loophole: a coach may not claim
**continuity between messages** — "I've been thinking about your taper all week", "I was
worried about you". `_shared_standard.json`'s `safety_boundaries` already forbids narrating
*whether you persist between messages*; asserting the persistence is the same claim with the
narration stripped off, and it is the one lie that requires no vocabulary at all.

## The decision procedure

For each first-person clause about the coach, in order. Stop at the first OUT.

1. **Is it about the coach's own life at all?** A reaction to the present exchange
   ("that's good to hear"), a scope handoff, or an opinion about *Matthew's* data is not
   inner life and this page does not govern it. → not in scope.
2. **R1:** point at the rendered field. Cannot point → **OUT**.
3. **R2:** would the same sentence be false if sent tomorrow? Yes → **OUT**.
4. **R3:** does it assert a day, a clock time, a countable occurrence, or continuity
   between messages? Any of these → **OUT**. Deictic anchors are the tell: *today, this
   morning, last night, yesterday, this week, just, earlier, still, all week*, and any
   bare weekday.
5. Otherwise → **IN**.

## Worked examples

**Out of bounds.**

| Clause | Fails | In-bounds rewrite |
|---|---|---|
| "Just got out of a session." (the roadmap #35 example) | R2, R3 | "Weight rooms, running tracks, rehab teams — same failure every time: the system couldn't absorb a bad week." (`physical_coach.bio`) |
| "Was up early myself this morning." | R1, R2, R3 | *nothing* — no rendered field carries a sleep habit for any coach. Say nothing. |
| "I watched the game last night." | R1, R2, R3 | *nothing* — no coach has a declared interest in sport. |
| "My old mentor used to say that." | R1 | "I got wary of treating distress as a puzzle to solve before someone can keep living." (`mind_coach.bio`) |
| "I read a paper on this last month." | R2, R3 | "The gap between what the papers show and what the summaries claim is basically my whole career." (`explorer_coach.bio`) |
| "I've been thinking about your taper all week." | R3 (continuity) | "Taper's the part I'd get wrong first, so I'm watching it." |
| "It's been a long week on my end." | R1, R2, R3 | *nothing.* |
| "I think I may have been up early too." | R3 (hedged occasion) | *nothing* — the hedge is the violation, not the fix. |

**In bounds.**

| Clause | Rendered source |
|---|---|
| "Lab-grade measurement was the first part of my career, which is why I'm hard on what a wrist can know." | `sleep_coach.bio` |
| "I decide early sometimes. Push back if I'm doing it now." | `eli_marsh.blind_spots` |
| "Teams and seasons is how I think about this. Occupational hazard." | `eli_marsh.structural_voice_rules.analogy_domain` |
| "Clinical calls aren't mine — that's Reeves." | `eli_marsh.boundaries.does_not_own` + `relationship_to_others` |
| "I'd rather make the smallest change that works than the best one on paper." | `_shared_standard.constitutional_rules` |
| "If I were still running teams I'd have made this call on Monday and lived with it." | counterfactual — asserts no occurrence |

**Explicitly carved out, so this page does not accidentally block filed work:**

- **Weather and day-of-week texture** (roadmap #33/#34) is *not* inner life. "Cold one this
  morning" is a grounded read of ingested weather and the moment line — it is a claim about
  Matthew's world, adjudicated by the ordinary date and number classes. In bounds, unchanged.
- **Team texture** ("we talked about you Tuesday") is governed by #2496 and
  `coach_team_texture`, not by this page. It is the one part of a coach's life that *does*
  have a substrate, which is exactly why it was allowed to ship.
- **Habitual present** ("I always read the raw data before the summary") is in bounds under
  R2 whenever R1 holds — a habitual asserts no occasion.

## Ruling 1 — may persona-stable facts be stated in the past tense? (AC2)

**Yes. Tense is not the discriminator; datability is.**

The evidence is in the shipped bibles: all eight texting personas' `bio` fields are written
in the past tense and are rendered verbatim into every prompt as `WHO YOU ARE` —
*"Started in academic health research"*, *"Built high-performing teams in high-pressure
environments"*, *"spent the first part of her career on laboratory-grade measurement"*,
*"moved between weight rooms, running tracks, and rehab teams"*. A blanket ban on past
tense would ban the substrate the platform already ships, and would leave the coaches with
no history at all — which is not caution, it is a different character.

What makes those lines safe is not their tense but that **none of them can be dated**.
They are career-scale, they were already true when the file was written, and they will read
identically in a year. The line to draw is therefore between two pasts:

- **The bible's past** — undatable, career-scale, present in a rendered field, and true
  every time it is said. **Permitted.**
- **The accrued past** — any past that came into being since the file was written. A
  session, a morning, a run, a book finished, a conversation had. **Forbidden**, because it
  has no source (R3) and cannot be repeated without becoming false (R2).

The practical test a reviewer applies: *can you ask "when?" and expect an answer?* "Built
high-performing teams" — no, and the question is odd. "Got out of a session" — yes, and
the answer does not exist.

## Ruling 2 — does the grounding gate see persona texture? (AC3)

Answered in two parts, because the honest answer today and the required answer at ship
time are different, and neither may be left implicit.

**Today: a deliberate written exemption, recorded here with its measurement.** The chat
grounder can arm six classes — numbers, dates, freshness, behavioral, night (the five in
`tests/grounding_wiring.py`'s `GATE_CLASSES`) plus the composed team class, with behavioral
armed only when `available_logs` is passed — and **none of them adjudicates a coach's claim
about its own life.** The measurement above is the evidence: five invented lives returned
`[]` under all four arming shapes, while every class fired on a purpose-built positive and
nonsense returned `[]`. This exemption is safe *only* because no coach has any texture to
invent from; it expires the moment that changes.

**At ship time: a deterministic occasion-claim check is mandatory, and its shape is fixed
here.** Texture ships in the same PR as its check, never before. The roadmap's own
discipline says why — *prompt rules are requests, so anything that must ALWAYS hold gets a
deterministic gate as well* — and `coach_style_gate` (#2535) shipped carrying the
measurement that proves it: "Honest answer" appeared 23 times in 536 replies despite being
banned by name in the prompt.

The contract:

| | |
|---|---|
| **Finding types** | `ungrounded_inner_life` — a first-person life claim with no rendered bible field behind it (R1). `coach_occasion_claim` — a first-person claim indexed to an occasion or asserting continuity between messages (R2/R3). |
| **Adjudication material** | the **rendered** persona block (`voice_block` + `texting_block` output), because that is literally what the model was shown — the same discipline as `_team_room_evidence`. |
| **Disposition** | regenerate-once-then-**HOLD**, inherited from `run_turn`. A hedge is a violation (R3), never the fallback. |
| **Correction wording** | the finding's `detail` must say *do not mention it at all* — `run_turn`'s retry prompt is generic ("Rewrite it using only what's in the facts above"), so the per-finding `detail` is the only thing that steers the second attempt. `team_meeting_findings` already does exactly this and is the model to copy. |
| **Home** | composed in `coach_chat_grounding.build_grounder`, sibling to `with_team_meeting_gate`. **Not** a new `GATE_CLASSES` entry, and **not** `coach_style_gate`. |

**Why not a sixth `GATE_CLASSES` entry.** Two reasons, both precedent rather than
preference. (a) The class needs no facts, no allow-list, and no night map; it compares the
reply against the persona block. `coach_team_texture.with_team_meeting_gate` stayed a
composition for exactly this reason, and its docstring says so — *"this check needs the
RENDERED block (its heading is the evidence), not the fact dict, and every other surface in
the wiring registry would have to take a decision on a class that can only ever apply to
the chat transport."* (b) `GATE_CLASSES` is deliberately expensive to extend: adding an
entry forces a required-or-exempt decision on all fifteen discovered surfaces. Paying that
tax for a chat-only class buys thirteen written exemptions and no coverage.

**Why not `coach_style_gate` either**, despite it being the obvious neighbour. That module
is a *transform*, and its stated contract is that *"its output differs from its input only
in punctuation and whitespace"* — it removes a banned opener and demotes an em-dash. An
invented Tuesday cannot be fixed by punctuation; it has to be regenerated or the reply has
to be held. A findings-producing check with a HOLD disposition belongs on the grounder
closure, which is the half of `run_turn` that already has one.

**What this means for `coach_chat_grounding.py` today: no change is owed.** Its module
docstring enumerates the classes it arms and claims nothing about persona texture, so
its silence is accurate rather than misleading — there is no false coverage claim to
correct. The change it *will* owe is the composition above, and it is owed by whichever of
#29/#35 ships first, not before.

## Ruling 3 — where the stance lives (AC4)

**Split, and the split is the ruling.**

**The prohibition is roster-wide → `config/coaches/_shared_standard.json`,
`safety_boundaries`.** Every truth rule in this system is inherited rather than repeated,
and this is a truth rule. The file already carries the identity boundary; the inner-life
boundary is its sibling and belongs beside it.

The one real objection has to be answered, because it is measured: #2533 found that a
roster-wide rule *supplying quotable wording* makes eight voices say one sentence — 5 of 8
coaches echoed `_shared_standard`'s own phrase, and `"No — I'm a"` opened 6 of 8 verbatim.
The answer is structural rather than careful: **that rule told coaches what to say; this
one tells them what not to say.** A prohibition has no surface form to echo. Which sets the
drafting constraint precisely — the entry must be phrased entirely as a constraint, and
must contain no sentence a coach could quote. It must not, for example, offer a form of
words for declining ("say you'd rather not talk about yourself"); that is a quotable line
and would reproduce the #2533 defect exactly.

**The texture itself is per-persona → `config/coaches/<coach_id>.json`, in the existing
rendered fields.** Texture is what distinguishes the voices, so it cannot be shared; and
R1 is only checkable if it lives in the fields the reviewer already reads. **No new field
is created for texture.** If a persona genuinely needs texture no existing field can carry,
the field is added to `persona_core`'s renderer *in the same PR* — an unrendered field is
not canon, and shipping one would silently create texture the coach cannot use and the
reviewer cannot audit.

**ADR-106's shape applies unchanged, and is not restated here.** Candidate texture is
authored character canon exactly as a portrait is: a model may draft it, only the reviewed
file ships, and Matthew approves. This page adds no new approval machinery — it adds the
checkable criterion (R1–R3) that a draft has to pass before it reaches him.

**Current state of `_shared_standard.json`: the entry does not exist** — measurement 2
above. This is a *scheduled* gap and not a live defect: with no coach carrying texture, no
reply is currently non-compliant. The requirement takes effect with the first texture PR,
and the roadmap rows below now carry it.

## What #29 and #35 must satisfy before they start

1. Every proposed line passes R1–R3, with the rendered field named in the PR body.
2. The `_shared_standard.json` `safety_boundaries` entry lands **first or in the same PR**,
   phrased as a constraint with no quotable sentence.
3. The occasion-claim check (Ruling 2) lands in the same PR as the texture, with a
   mutation-proof — a deliberately invented occasion must produce a finding, and the same
   sentence with the occasion removed must not.
4. Texture is **scarce**, for the same reason initiative is capped: at most one inner-life
   clause per reply, and never as the reply's opening. A coach that volunteers its own life
   unprompted is a bot performing personality, which is the failure mode #57b already
   names.
5. The sim harness (#2539) re-runs, and the inner-life sweep is reported — both the rate of
   texture and the rate of occasion-claims caught. #29/#35 are additive changes to a voice
   the panel already calls too composed 64% of the time; if texture does not move a judge
   metric, it is decoration and should be reverted rather than tuned.

## Honest residual

R1 is checkable by a human and only partly by a machine: the occasion-claim check can
detect that a life claim was *made*, but deciding whether it is readable out of a rendered
field is a judgment. That residual is deliberate — the alternative is a semantic gate
adjudicating a persona against its own spec, which is an LLM verdict about character, and
ADR-105 §3 puts deterministic computation before any LLM verdict. So the machine catches
the class that is mechanically decidable (an occasion was asserted) and the human catches
the class that is not (the trait has no source). This is the same division the platform
already accepts between the number gate and the coherence sentinel.
