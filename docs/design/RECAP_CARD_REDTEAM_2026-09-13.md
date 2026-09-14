# The daily card, red-teamed — 2026-09-13

> **Status:** design record · **Trigger:** the owner reviewed the first seven rendered cards
> and rejected them · **Boards:** Product (all eight seats), Personal (selected), plus the
> platform's own north star as a standing constraint.

## The verdict that started this

> *"I was not impressed with them at all. They are not posts i would be excited to post each
> day to recap the past 24 hours, i think more creative, more data, more detail, more
> throughline, more nod to the experiment, there is a lot more that could be done to these."*

And, decisively, the brief that was missing from the original spec:

> *"imagine you want these posts to get engagement, snowballed engagement, maybe a few likes
> in the first few days, but these captivate audiences who follow it day after day, my story
> and post, its a social media campaign, and so this data and story narrative is to be told
> through these daily posts."*

That second message is not a refinement of the first. It changes the artefact. A *recap card*
answers "what happened yesterday". A *campaign post* has to earn the next one. Everything
below follows from taking the second framing seriously.

---

## 1. What was actually built, measured

Seven cards rendered from live data, Days 1–7 of cycle 17. Each drew **one big number, a
label, two or three mono lines, and sometimes a second small block.** Roughly 60% of the
frame was empty.

The day's record in DynamoDB holds **53 fields**. The cards drew **four**.

| Available and unused | Value on Day 7 |
|---|---|
| `day_grade_letter` — the platform's own verdict | **C-** |
| `component_scores` — six graded dimensions | movement 57 · habits 67 · hydration 84 · sleep 66 · **nutrition 29** · recovery 59 |
| `readiness_score` | 58 (and 76 → 44 → 58 across the week) |
| cumulative loss since Day 1 | **−7.66 lb** |
| distance to goal | 134.7 lb |
| `missed_tier0` — *which* habits were missed | "Walk 5k", "Morning Sunlight" |
| `vice_streaks` | 7d, 7d, 5d, 1d… |
| `acwr` / `acwr_zone` | 1.30, safe |
| `sleep_debt_7d_hrs` / `hrv_ms` | 4.6 / 33.9 |
| `tsb` / `ctl` / `atl` | −55.2 / 21.8 / 77.0 |

**Three findings the render exposed that no test caught:**

1. **The Week-1 headline never appeared.** 327.3 → 319.7 is **−7.66 lb in seven days**, and
   it is on none of the seven cards. Every template was scoped to a single day, so the
   cumulative story — the only number a follower actually tracks — had no home.
2. **The day's grade was ignored entirely**, and it has a genuine arc: C → B- → B- → B- →
   C- → C- → C-. A slide. That is a *story*, and the platform computed it daily and drew
   it never.
3. **Two cards were wrong, not just thin.** Days 4 and 5 headlined "2.7 lb UP THIS WEEK".
   `week_ago_weight` on those days points **before genesis**, so the comparison crossed the
   cycle boundary: a cross-cycle artifact rendered as a gain. Nothing in the test suite
   could catch it because the fixtures were hand-built and internally consistent. Rendering
   real data caught it in one look.

---

## 2. The board

### Sofia Herrera — CMO · *"Would someone share this?"*
> "No. And the reason is not polish, it's that there's no reason to come back. I'm shown a
> number and a label. There's no stake, no question left open, nothing that makes tomorrow's
> post matter. You've built a *receipt*. A campaign needs a *serial*.
>
> And you're sitting on the best hook I've seen in this category and not using it: **sixteen
> loss episodes since 2012, zero held.** That's the account. 'I've lost this weight sixteen
> times and gained it back sixteen times. Here's attempt seventeen, instrumented, in public,
> and you get to watch whether it holds.' That has jeopardy. Weight-loss content has no
> jeopardy — everyone posts the after photo. Nobody posts from inside an attempt that has
> failed sixteen times."

### Jordan Kim — Growth · *"Will this get shared? Will it convert?"*
> "Day 1 has zero followers. So the first ten posts have to work for a stranger who sees ONE
> of them mid-scroll with no context. Right now a stranger sees '2.3 lb' and keeps scrolling.
> They need, in under a second: who, what attempt, how far in, how far to go.
>
> Put the serial marker on every single card — **DAY 8 · ATTEMPT #17** — and the progress bar
> on every single card. That's what makes card 40 legible to someone who's never seen cards
> 1–39, and it's what makes the grid читается as one body of work instead of 40 unrelated
> screenshots."

### Ava Moreau — Content Strategist · *"What's the engine that runs without Matthew?"*
> "The picker is the right idea and the wrong axis. It picks by *data magnitude*. A campaign
> picks by **narrative beat**. Those aren't the same: a day where he missed two habits and
> scored 29 on nutrition is a BETTER post than a clean day, because 'here's what I blew' is
> the content that builds trust and gets saved. Right now a bad day produces a quiet card.
>
> I'd define the beats explicitly — milestone, streak, grind, honest miss, comeback, first-in-
> N-days, weekly reckoning — and let the picker choose the beat, then choose the layout that
> serves it."

### Tyrell Washington — Design/Brand · *"Does this look world-class?"*
> "It's tasteful and it's empty. Restraint is the house style and I defend that — but
> restraint means *nothing decorative*, not *nothing present*. Sixty percent dead frame isn't
> restraint, it's an unfinished composition. The type scale is right, the palette is right,
> the mark placement is right. Give the composition something to hold: a sparkline, a
> progress bar, component bars, a dot row. Small marks, high density, still quiet."

### Mara Chen — UX · *"Can someone use this without instructions?"*
> "Test it: cover the caption and show a stranger one card. Do they know what they're looking
> at? Today: no. Add the serial marker and the progress bar and the answer becomes yes.
> One caution against Raj and Ava — **don't put eleven things on it.** Instagram is a
> thumb-stop. One hero, one supporting structure, a footer of facts. Dense ≠ cluttered."

### Dr. Lena Johansson — Longevity Science · *"Is this defensible?"*
> "Careful. Everything the others want pushes toward drama, and this platform's entire moat is
> that it does not do that. I'll hold three lines and I won't move:
> **(a)** a projected rate does not go on a public frame as fact — the provisional gate stays;
> **(b)** a weekly rate whose confidence interval straddles zero is not a direction, and must
> not headline — the demotion you added today is correct, keep it;
> **(c)** the cumulative number is honest and postable, but week-one loss is substantially
> water and the card should not imply otherwise. If you show −7.7 lb in week 1, the card
> should also carry what that is and is not."

### Raj Mehta — Product Strategy · *"Does it move the metric that matters?"*
> "The metric that matters isn't likes, it's **returnability** — does he still post on Day 90.
> So optimise for the thing that makes a daily habit survivable: it must be genuinely
> zero-effort and the card must never embarrass him. A card that overstates gets deleted and
> the habit dies with it."

### Dr. Henning Brandt — Biostatistics *(Personal board, invited)*
> "Every number on that frame needs its n and its uncertainty or it doesn't go on. You did
> this correctly with the CI sub-line. Do not drop it for aesthetics. And the sparkline: he
> has **one weigh-in this week**. A seven-point line drawn through one measurement is a
> fabrication. Break the line at gaps. Draw nothing where nothing was measured."

### Viktor Sorokin — Adversarial · *"Is this actually necessary?"*
> "Push back on the whole variation programme. Four layouts is four things to maintain and
> the owner will post whichever one looks best and ignore the rest. Ship ONE excellent layout
> that adapts its density to the day's data. The 'variations' he asked for are a review
> device — show him four tonight so he can *choose*, then converge to one."

---

## 3. The disagreements that matter, and the calls

**Sofia/Jordan (drama) vs Lena/Henning (rigor).** The standing tension pair, live.

**Call: there is no trade here, and believing there is would be the mistake.** The honesty *is*
the hook. "Sixteen attempts, zero held, watch attempt seventeen" is more compelling than any
transformation claim precisely because it can fail in public. The north star already says it —
*proof, not promises · honesty is the moat; never trade it for hype* — and the campaign framing
does not weaken that rule, it monetises it. Every one of Lena's three lines holds. A card that
shows a C- and a nutrition score of 29 is **better content**, not a compromise.

**Ava (beats) vs the existing picker (magnitude).** Ava is right. The picker moves to
narrative beats; magnitude becomes one input to choosing a beat, not the axis itself.

**Mara (one hero) vs Raj/Ava (more).** Mara holds on composition: one hero, one supporting
structure, a fact footer. Density comes from *marks*, not from more text blocks.

**Viktor on variations.** Accepted with a fork: build four for tomorrow's review because he
asked to choose; converge to one plus a weekly variant once he has.

---

## 4. What the campaign actually is

**The spine:** *Attempt #17. Sixteen times the weight came off. Zero times it stayed off.
This one is instrumented, public, and gets graded every single day — including the days it
goes badly.*

**Why anyone follows day after day:** they are watching an experiment resolve, not a highlight
reel. The interesting part is not week 1; it is month 6, where all sixteen previous attempts
died. The account's promise is that they will see that moment honestly whichever way it goes.

**What every card therefore carries, without exception:**
- the serial marker — `DAY N · ATTEMPT #17` — so any single card is legible standalone;
- the arc — baseline → now → goal, as a bar that visibly fills over months;
- the day's own verdict, including when it is bad.

**What varies:** the beat, and the layout that serves it.

---

## 5. What ships from this

1. `lambdas/web/recap_charts.py` — sparkline (gaps stay gaps), progress bar, component bars,
   dot rows, grade badge, measured text fitting.
2. A richer fact surface: grade, components, readiness, ACWR, streaks, missed habits by name,
   cumulative loss, distance to goal, the cycle's weight and grade series.
3. Beat-based selection replacing magnitude-based selection.
4. Four layouts for review, converging to one.
5. The privacy consequence, stated: habit and vice NAMES now reach the card surface, and one
   of his live vice streaks is a blocked-category name. Those names travel through
   `item_labels()` into the gate — which is precisely why the gate shipped before the
   renderer.

---

## 6. Honest note on my own work

The first cards were not a misunderstanding of the brief; they were an under-reading of it.
"A visual graphic I can post" was taken as a floor and built to. The available data was
inventoried at the point of *writing the template functions*, not at the point of *designing
the card*, which is how 53 fields became four. And the two misleading cards shipped because
every test fixture was hand-built and internally consistent — the cross-cycle `week_ago_weight`
bug cannot appear in a fixture someone wrote to be correct.

The general lesson, and it is the same one this platform keeps re-learning: **render the real
data early.** One look at seven real cards found three defects that twenty-six passing tests
did not.
