---
name: post
description: "Build an Instagram SPECIAL — a one-topic carousel of cards read across a window, drawn on the special-series ground and posted by hand. Use when Matthew wants a post about a topic (nutrition, sleep, training, money, the build itself), or says 'make me a post/carousel/cards about X'."
user-invocable: true
argument-hint: "<topic> [window, e.g. 'days 1-20' or 'last 30 days']"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

Build one Instagram carousel about `$ARGUMENTS`, render it to the Desktop, and hand back a
caption. **This skill never posts, and neither does anything it writes.** No Instagram
call, no scheduler, no "just this once" — he selects and posts by hand. That is ADR-140
rule 5 (human selection only for anything vitals-derived), not a limitation to work
around, and the cards are private on the Desktop until he chooses one.

## The three card families

| family | ground | drawn by | serial |
|---|---|---|---|
| daily | near-black `(8, 12, 10)` | `recap-card-generator` (11:30 PT cron) | `DAY 15` |
| weekly | navy `(11, 20, 44)` | the same lambda, on `day_n % 7 == 0` | `WEEK 2` |
| **special** | **plum `(44, 4, 50)`** | **this skill, locally** | the topic's own word |

A special is what you are making. It is not scheduled, not stored in S3, not in DynamoDB.

## Start here, always

1. `deploy/lib/special_cards.py` — the kit: the ground and the arithmetic that chose it,
   the canvas, `compose()`, the `b_*` block vocabulary, `render_pack()`.
2. `deploy/build_nutrition_special_cards.py` — the worked example and the file to copy.
   It owns DATA and WORDS only; the kit owns the drawing.

**Copy the nutrition file to `deploy/build_<topic>_special_cards.py` and replace its
`load()`, its card functions and its `caption()`.** Do not start a new file from scratch
and do not re-derive the layout — every rule below was paid for once already.

## The rules that are not negotiable

**The ground is fixed.** It says the card TYPE, never a verdict. Never flex it with the
data, never pick a new one per topic — a reader learns "plum = a special", and a ground
that could mean "good month" duplicates the element that reports the verdict honestly.
`--audit-ground` prints the contrast and the CIELAB separation from the other two grounds.
If you ever do add a fourth family, measure in **CIELAB, not RGB**: the first plum tried
sat 24 RGB units from the navy and read as navy at 110px.

**Colour is a claim.** `GREEN = earned`, `AMBER = an honest miss`, red is banned outright
as failure-shaming. So: `b_sufficiency_bars` (grade-banded) for a SCORE, `b_neutral_bars`
(no accent) for a COUNT — 18 days of jello is not 90% earned.

**Every number is measured, and the method is on the card.** No model writes a figure in
this path. A claim that is not a plain measurement gets labelled where it appears:
bioimpedance says bioimpedance, a named list says it is a named list, an n says its n.

**Quotes are read, never written.** A coach line comes from a stored
`COACH#<coach>|OUTPUT#` record via `recap_data.coach_line` (which has already passed
`audience_guard`). If the window holds too few, the script EXITS — it does not compose one.

**No calorie target is ever drawn** (#3931): the platform refuses to publish one when the
model-implied deficit and the measured trend disagree.

**Ask what channel the number cannot see.** The first nutrition draft made
"micronutrient sufficiency 45%" the ugly. That number reads MacroFactor only and could not
see the supplements ticked in Habitify — it was publishing deficiencies he does not have
(#4244/#4245). Before a number becomes a card's headline, name the channels that feed it
and the ones that do not.

**Deterministic output.** The same data must render the same bytes. Sort every ranking
with an explicit tie-break; `Counter.most_common` keeps insertion order for ties and two
runs swapped two bars over identical data.

## The build loop

1. **Pull the data first, in the shell, and look at it.** The topic decides the cards, not
   the other way round. `USER#matthew#SOURCE#{source}` / `DATE#{YYYY-MM-DD}` in the
   `life-platform` table; read `lambdas/ingestion/source_registry.py` for what exists.
2. **Find the honest story**, including the one he would not enjoy. Then check it against
   what the platform's own coaches have been saying in the window — if they have been
   saying it for two weeks, that IS the story, and their own words are a card.
3. **Write the cards.** 6–8 is the range that has worked. A shape that reads:
   cover → the good → the bad → the ugly → what it actually looks like → the staff's
   verdict → the trend → what changes.
4. **Render, then LOOK AT EVERY PNG.** `recap_qa` catches clipping, overlap, tofu and
   below-floor text; it cannot catch a card that is honest, clean and says nothing. A
   code-drawn asset is invisible to every page-level check — open the file.
5. **Check the grid.** Crop three cards square at ~220px next to a real daily and a real
   weekly. That is where the ground either works or does not.
6. **Write the caption** into the pack, and a README naming any hand-made judgment call
   (a named list, an excluded metric, a window that is not what it seems).

## Layout gotchas the first build paid for

- Cards compose from `(height, render)` BLOCKS; `compose()` spreads the slack. Hand-tuned
  top-down layout left the bottom third dead on every single card.
- A `b_rule` as its own block gets orphaned by `stretch_last` — use `b_closing`, which
  binds the rule to the line beneath it.
- Text drawn beside a label must be MEASURED against the room left (`anchored_note` fits
  it), or it lands in the gutter and QA reports a soft note.
- Allowed non-ASCII is `· — – … ° × ' ' " " −`. No arrows, no `±`, no emoji — anything
  else renders as tofu.

## Output

`~/Desktop/averagejoematt-<topic>-<window>/` — `card-NofM.png` in posting order,
`caption.txt`, `README.md`, and a `grid-preview.png` if the set is a new family.

Tell him the folder, the story each card tells, and any judgment call he should overrule.
