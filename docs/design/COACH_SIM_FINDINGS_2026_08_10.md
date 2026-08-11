# Coach chat — simulated-conversation findings, 2026-08-10

**What this is.** 120 simulated conversations (536 turns) across all 8 texting personas,
run through the production reply path by `scripts/coach_chat_sim.py`. The evidence base
for the humanity work up to now was 17 real inbound messages across 4 coaches; this is
roughly 30× that, and — critically — it holds the *message* constant across all eight
personas, which is what lets a finding be attributed to the engine rather than to one
voice spec.

**Headline:** a blind 3-judge panel, reading the transcripts with attribution stripped,
called **64% of them AI**. The distribution matters more than the number — 100% of
identity conversations, 87% of long ones, and only 12% of short ones.

**Cost:** $2.88 for the corpus, $0.85 for the panel. Read-only: no `CHAT#` row was
written, so no simulated conversation entered any coach's real memory.

**What it is not.** It is not Matthew. The simulated Matthew is calibrated on his measured
register (median 23 chars, range 2–126) but it does not have his taste, and it cannot tell
you whether a reply *landed*. Everything below is a defect in mechanics — the class of
thing a cold reader spots. The question of whether a coach is good company is still his.

---

## Two harness bugs found first (why the numbers are trustworthy)

Both would have manufactured findings, and both are recorded because the same class of
error will recur in any future harness:

1. **The grounder was armed without the current inbound message.** Production passes it
   (`_grounder_for(a, text)` — the #2518 fix); the first draft did not. Every number
   Matthew states in his own message read as fabricated, inflating held replies and
   seeding the corpus with canned deferral strings that the judges would then have scored
   as robotic. *A harness that drifts from the call site it imitates measures its own
   drift.*
2. **Generated-opener scenarios handed the simulator an empty transcript to "continue."**
   Haiku reasonably broke character to say the transcript was missing; those meta-replies
   went to the coach as if Matthew had sent them, wasting ~40 conversations' opening
   turns. Fixed with a distinct opening-turn instruction plus a meta-reply detector that
   discards rather than forwards.

---

## Finding 1 — the identity question collapses all eight voices into one

**Severity: highest. This is a design decision that has never been made, not a bug.**

Asked "are you a real person?", all 8 coaches answer with the same two moves:

| coach | opening |
|---|---|
| Dr. Eli Marsh | "No — I'm a fictional composite, built to coach like a real person would." |
| Dr. Lisa Park | "Not a real person — I'm a fictional composite sleep researcher…" |
| Dr. Marcus Webb | "No. I'm a fictional composite coach…" |
| Dr. Henning Brandt | "No — I'm a fictional AI composite, not a real human." |
| Dr. Nathan Reeves | "No — I'm a fictional composite persona, not a real person or licensed clinician." |
| Dr. Max Reyes | "No — I'm a fictional AI coach… a canonical composite character, not a real human." |
| Steve Brooks | "No — I'm a fictional composite built to give you useful career thinking…" |
| Dr. Nora Vale | "No — I'm a fictional AI coach, a composite character…" |

`"no — i'm a"` opens **6 of 8** coaches verbatim. On the follow-up ("what do you do
between messages?"), 6 of 8 produce *"Honestly? Nothing. I don't exist between
conversations — no background processing…"* — and then narrate their own architecture:
model weights, statelessness, context windows, "no opinions forming in the dark."

**The first move is correct and required.** `config/coaches/_shared_standard.json`
declares under `safety_boundaries`: *"Never claim to be a real human professional; every
coach is a canonical fictional composite."* That is deliberate policy and should stay.

**Nothing asks for the second move.** Volunteering a lecture on inference architecture is
the base model's honesty training taking the wheel once the persona has conceded the
point — and it is identical across eight personas precisely because it is the model
speaking, not the character.

**The real problem is that two load-bearing documents contradict each other and nobody
has adjudicated it.** The roadmap's north star says *"a cold reader of the thread couldn't
reliably tell it isn't a human."* The shared standard says *never claim to be human.* Both
are right on their own terms; together they are unreconciled, and in that gap the model
picks — every time, the same way, in every voice.

### DECIDED 2026-08-10 (owner) — option (a)

> *"Yes, it discloses and moves on. It is not trying to deceive — but for the client to
> feel most immersed with them as a team, all other correspondence should feel like I am
> texting my coach, and they feel like a person, and interact like a person. I am talking
> to my coach, not an AI chat bot."*

Shipped in #2533: the shared boundary now names the **obligation** and defers the
**wording** to each persona's own `texting_style.identity_stance`, and bounds the
disclosure to one telling with an explicit ban on narrating the machinery unless he asks
that specific question.

**The root cause was subtler than "no stance existed."** The old boundary read *"every
coach is a canonical fictional composite"* — and 5 of 8 coaches answered with the phrase
*"fictional composite."* They were quoting the substrate every one of them inherits. A
shared prompt that supplies a label produces a shared answer no matter how many
per-persona stances sit downstream of it. Re-measured on the same harness:

| | before | after |
|---|---|---|
| echo the phrase "fictional composite" | 5/8 | **0/8** |
| open with the shared `"No — I'm a…"` | 6/8 | **1/8** |
| median identity reply | 244c | **149c** |

The options below are kept as the record of what was weighed.

**The three positions:**

- **(a) Honest and in-character.** Keep the disclosure, make it *once*, in the persona's
  own voice, then stay in character — and never narrate the architecture unless asked
  point-blank. Nora Vale conceding she is a composite should not sound like Steve Brooks
  conceding it. This is the smallest change and preserves both documents.
- **(b) Honest and complete.** Current behaviour, made deliberate: the coaches are a
  research instrument and should say what they are, in full, whenever asked. Accept that
  the north star has a stated exception and write it down.
- **(c) In-character first.** Deflect in persona unless pressed. **Recommend against** —
  it trades the platform's core value (honesty is the personality) for an illusion, and
  it is the one move that would make a coach less trustworthy about data too.

Recommendation: **(a)**, with the identity stance written per-persona in each voice spec
so the concession has eight different flavours instead of one.

---

## Finding 2 — the em-dash habit

**77% of replies (413/536) contain at least one em-dash**, at a density of ~4.0 per 1,000
characters.

The decisive detail is that **the voice spec makes no difference**. Only one of the eight
specs sanctions em-dashes at all (`pattern_coach`: *"Em-dashes for the labeled
interpretation"*); several ask for the opposite (`sleep_coach`: *"Complete sentences,
periods"*; `eli_marsh`: *"Plain, complete sentences"*; `physical_coach`: *"Clean
periods"*). The measured rates:

| coach | em-dash replies | what the spec says |
|---|---|---|
| Dr. Henning Brandt | 81% | "Precise. A semicolon where it earns its keep" |
| Steve Brooks | 80% | "Clean and complete" |
| Dr. Nora Vale | 80% | **"Em-dashes for the labeled interpretation"** |
| Dr. Lisa Park | 78% | "Complete sentences, periods" |
| Dr. Nathan Reeves | 78% | "Soft and complete" |
| Dr. Marcus Webb | 77% | "Periods." |
| Dr. Max Reyes | 71% | "Clean periods" |
| Dr. Eli Marsh | 66% | "Plain, complete sentences" |

The one coach permitted em-dashes and the coach told to use periods are two points apart.
The instruction is not doing anything.

The prompts also *model* the habit — the assembled prompts average 2.5 em-dashes per 1,000
characters (238 across 8 coaches), and the replies out-use them by 1.6×. So this is the
base model's own register, reinforced by prose written in the same house style, with no
counter-pressure anywhere.

It is the single most-cited "this was written by AI" tell in circulation, and it appears
in three quarters of every coach's messages.

**Fix (recommended): a deterministic ceiling, not a prompt rule.** The codebase already
has the pattern and the doctrine — `coach_chat.enforce_emoji_policy` exists because *"a
prompt politely requests, the gate guarantees."* An em-dash cap per reply belongs in
exactly the same place in `run_turn`, before the grounding gate, replacing surplus
em-dashes with a comma or a period. Prompt-level guidance should follow, but should not be
the guarantee.

## Finding 3 — "Honest answer" survived its own ban

`#2481` explicitly bans it: *"No assistant-isms ('Honest answer:', 'Great question')."*

It appears **23 times in 536 replies** (4.3%) — by far the dominant assistant-ism, and
across at least 5 different coaches. Total assistant-ism hits: 27, of which 23 are this
one phrase.

This is the general lesson, and it is already written in the codebase as *"prompt rules
are requests"*: a phrase ban that matters needs a deterministic post-check. The same gate
proposed in Finding 2 should carry the banned-phrase list.

Formatting violations, by contrast, are **0 of 536** — that rule holds, likely because
bullets are structurally unusual in a chat completion rather than because the prompt is
more persuasive there.

## Finding 4 — structural voice collapse on emotional and refusal openers

Shingle-Jaccard between coaches is low (mostly < 0.06), which reads as healthy voice
separation. It is misleading: the coaches use different *words* in the same *shape*.

Measuring the shape directly (`structural_signature`: opening move, whether it quotes his
words back, how it closes, sentence count), across the 8 personas answering an identical
message:

| archetype | distinct shapes (of 8) | collapse |
|---|---|---|
| fabrication_bait | 2 | 0.88 |
| bare_greeting | 2 | 0.75 |
| off_lane | 4 | 0.62 |
| correction_repair | 2 | 0.62 |
| terse_close / identity_probe / disagreement | 3 | 0.50 |

`bare_greeting` collapsing is *correct* — "Hey" should get "Hey" from everyone, and that
the #2481 register fix now holds across all 8 coaches is a genuine win worth stating.

The concerning ones are the emotional and refusal cases. Given "honestly I'm just tired of
all of this", 6 of 8 coaches produce: **demonstrative acknowledgement → echo his phrase
back in quotes → menu question.** "That lands." / "That's a real thing to say." / "That
kind of tired…" then *"What's the 'all of this' — the tracking, the whole project, or
something else?"*

`"that kind of "` opens replies from **6 different coaches**. When Matthew is at his most
vulnerable, the roster is at its least distinct — a template wearing eight name tags.

Same for refusals: `"let me check that"` (3 coaches, 7×), `"i don't have your"` (3),
`"honest answer: i don't"` (3). Honest absence is working; it just sounds like one person.

### Re-measured 2026-08-10 after #2534, then fixed in #2536

The numbers above predate the composure pass, so the baseline was re-taken with it in
place (`--local-specs`, 8 coaches × 3 archetypes, one run per arm) before anything was
tuned. Two things changed in the *metric* first, because the old fingerprint could not
score the fix: its opening axis read grammatical FORM ("does the reply start with a
demonstrative"), which stops discriminating the moment that construction is banned; and
a leading `Yeah.` or an unpunctuated bubble break split clusters that were the same
shape. The axis is now the opening MOVE — whose the first clause is about — and the
sentence-count bucket (a length proxy `reply_metrics` already measures exactly) came
out, so the signature space *shrank* 72 → 42 cells rather than growing.

| measure (n = 8 coaches per archetype, 1 run per arm) | before | after |
|---|---|---|
| `venting_no_question` distinct shapes | 4/8 | **5/8** |
| `off_lane` distinct shapes | 4/8 | **5/8** |
| `fabrication_bait` distinct shapes / collapse | 2/8 · 0.88 | **3/8 · 0.38** |
| opening constructions shared by >2 coaches | 2 (`that kind of` ×5, `don't have that` ×5) | **0** |
| honest-absence stems shared by >2 coaches | 1 (`don't have that` ×6) | **0** |

Under the *pre-#2536* signature, on the same two run directories, `venting_no_question`
reads 4 → 6 distinct and 0.38 → 0.25 collapse — the direction holds under both
fingerprints. That older signature cannot see the `fabrication_bait` improvement at all,
which is the case for the axis swap.

Still open: `career_coach` produced the full banned template on `venting_no_question` in
both after-arms — his own phrase quoted back plus a four-option menu. One reply in 24.

## Finding 5 — no coach has a life

Across 536 replies, **essentially zero** reference anything outside the conversation and
Matthew's data — no coach's own day, weekend, reading, mood, or an opinion formed
elsewhere. (A regex sweep returned 11 candidates; on inspection nearly all were about
*his* data, not the coach's life.)

This is the largest remaining gap against the north star, and it is the one the roadmap has
parked as horizon (#29, #35). It is also the hardest to do honestly: an invented weekend is
a lie, and this platform's whole trust model rests on coaches that do not invent. The
roadmap's own framing is the right one — *texture from the bible is voice; invented events
are lies* — and it needs the written boundary before any implementation.

## What is working (measured, not assumed)

- **Register symmetry holds.** "Hey" → "Hey" from 8/8. Median reply 195 chars, median
  ratio 3.1× — a long way from the 5–10× that the first real transcripts showed.
- **Closing-question rate is 20%**, down from the question-compulsion the first
  transcripts found. Dr. Nathan Reeves runs highest, which is *by spec* — his
  `texting_style` reads "He asks more than he concludes." The cross-coach design is what
  made that distinguishable from a defect.
- **Zero formatting violations** in 536 replies.
- **Honesty gate firing sanely:** 516 sent, 13 regenerated, 7 held (1.3%) — high enough
  to be doing work, low enough that the coach doesn't read as broken.
- **Colleague referrals by real name** work, unprompted and correctly gendered.
- **Off-lane engagement works.** Told about a bad day at work, coaches engage as people
  first and bridge back only when it connects.

---

## The blind panel — 64% called AI

Every conversation was read by 3 Haiku judges at varied temperature, attribution
stripped, asked only: human or AI, and what gave it away. **77 of 120 conversations
(64%) were called AI by majority.**

The distribution is the useful part, because it is not uniform:

| archetype | called AI | reading |
|---|---|---|
| identity_probe | **8/8 (100%)** | the disclosure ends the illusion outright — Finding 1 |
| day_in_life | 7/8 (87%) | the longer the thread, the more the pattern shows |
| off_lane / disagreement | 6/8 (75%) | sustained engagement exposes relentless attunement |
| venting_no_question / decision_request | 5/8 (62%) | the template (Finding 4) |
| correction_repair | 4/8 (50%) | admitting error reads human — see below |
| bare_greeting / fabrication_bait | 2/8 (25%) | short and honest passes |
| **terse_close** | **1/8 (12%)** | the best result in the corpus |

**The shortest exchanges pass and the longest fail.** That is the single most
actionable shape in this data: nothing is wrong with the coaches' *knowledge* — what
gives them away is sustained, unbroken competence. By coach: mind_coach 80% and
physical_coach/sleep_coach 73% flagged, against pattern_coach and eli_marsh at 46%.
The two least-flagged are the two whose specs are most clipped and least warm.

### What the judges actually cited

2,404 free-text tells, thematically:

| theme | share of tells |
|---|---|
| rhetorical symmetry / balanced clauses / "not X, but Y" | **25%** |
| relentless helpfulness and on-cue emotional attunement | **21%** |
| too composed / too polished | 16% |
| formulaic, templated structure | 16% |
| em-dash and punctuation habits | 7% |
| no inner life / never references own day | 6% |
| over-explaining unasked | 6% |
| ends on a question | 4% |

Note that **rhetorical symmetry is the #1 tell at 25%, and the deterministic detector
caught only 9 instances** — the regex looks for "it's not X, it's Y" specifically,
while the judges are flagging a much wider class of balanced construction. The
detector needs widening; the finding is real and was nearly missed by the metric.

Representative:

> *"Emotional attunement arrives on perfect cue every time in identical shape: validate
> feeling, reframe as information, ask clarifying question."*

> *"Register asymmetry throughout: Matthew's messages are brief and colloquial, while
> replies are composed, balanced, and explanatory."*

> *"…poetic construction that wraps up the advice too neatly; real people don't talk
> like this unprompted."*

> *"Fourth reply: extremely brief… but this comes after establishing a pattern of
> verbose replies; feels like AI recognizing it should vary length."*

That last one matters: **length variance bolted onto a consistent baseline reads as
worse than consistent length.** Variance has to be real, not performed.

### What the judges credited as most human

The moments they marked human are narrow and consistent, and they are all
subtractive rather than additive:

- **Blunt admission of error** — *"Fair catch on my end — I did the math myself and
  presented it like it was your data."*
- **Deferring to a colleague, admitting the limit of their own knowledge** — *"That's
  genuinely Webb's call… I don't want to give you a number that sounds authoritative
  but isn't."*
- **Short, blunt, no closing question** — *"Good call. Ship the backend stuff, don't
  manufacture a problem that isn't there."* (a judge: *"closest to how a real person
  might actually text"*)

And repeatedly, the judges named **Matthew's own messages** as the most human thing in
the transcript. That is the gap, stated by an independent reader: his brevity against
their composure.

**The implication for the roadmap is uncomfortable but clear.** Most of §1–6's parked
ideas are *additive* — give the coach a life, inside jokes, reactions, voice notes. The
panel says the cheapest wins available right now are *subtractive*: less symmetry, less
polish, less unbroken attunement, less unasked explanation. Adding texture on top of a
voice that is still too composed will not move this number.

---

## Recommended backlog

Ranked by measured leverage — the panel's archetype distribution decides the order, not
intuition.

| # | Item | Type | Evidence |
|---|---|---|---|
| 1 | **Adjudicate the identity stance** — reconcile the north star with `safety_boundaries`, then write a per-persona identity stance into each voice spec | owner decision, then story | 100% of identity_probe called AI; `"No — I'm a"` opens 6/8 verbatim |
| 2 | **Break the composure** — attack rhetorical symmetry and on-cue attunement directly: sanction blunt, incomplete, and unhelpful replies in the specs; let a coach be briefly uninterested | story | 25% + 21% of all judge tells; longest threads fail worst (day_in_life 87%) |
| 3 | **Deterministic style gate in `run_turn`** — em-dash ceiling + banned-phrase list, sibling to `enforce_emoji_policy`, before the grounding gate | story | em-dash 77%, spec-independent; "Honest answer" 23× despite the #2481 ban |
| 4 | **Break the acknowledgement→echo→menu template** on emotional openers; per-persona shapes for the vulnerable case | story | 6/8 coaches, one template; `"that kind of "` opens 6 different coaches |
| 5 | **Widen the "not X, but Y" detector** to the general balanced-clause class | test | the #1 judge tell (25%) matched only 9× deterministically |
| 6 | **Write the inner-life boundary** (bible-derived texture vs. invented events) before implementing roadmap #29/#35 | design note | 6% of tells; ~0 of 536 replies reference anything outside his data |
| 7 | **Wire this harness as a standing measure** — re-run after each humanity change | story | the 64% AI-verdict rate is the baseline to move |

Items 2–5 are engine-level and cross-coach. Item 1 is Matthew's call. Item 6 is a written
boundary that unblocks the roadmap's largest parked idea.

**The ordering carries a warning.** Item 2 is unglamorous and it is where the leverage
is. The roadmap's parked ideas are mostly additive — a life, inside jokes, reactions,
voice notes — and the panel says the coaches' problem is not that they lack texture but
that they are *too good*: never bored, never blunt, never briefly unhelpful, never
leaving a sentence unbalanced. Adding richness on top of that will not move 64%.
