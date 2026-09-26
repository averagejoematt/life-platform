# Site Transformation v6 — a site worth opening

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-09-26
> Written 2026-09-26 by Session AV (overnight, Fable 5.1) · **Epic:** #4182
> Companions: [PLATFORM_NORTH_STAR.md](PLATFORM_NORTH_STAR.md) (the why — unchanged), [SITE_MAP_AND_INTENT.md](SITE_MAP_AND_INTENT.md) (per-page intent — amended by §5), [DESIGN_SYSTEM_V5.md](DESIGN_SYSTEM_V5.md) (the kit — unchanged), [SITE_UPLEVEL_PLAYBOOK.md](SITE_UPLEVEL_PLAYBOOK.md) (how to change it — unchanged).

## 0. What this is

The owner, 2026-09-25, three weeks into cycle 17: *"I don't like averagejoematt.com. I have not used it in the 3 weeks of this experiment, and friends who go to it are overwhelmed with the layout, the content, what to do, and even some of the words describing things and explaining things — and 'AI coaches' isn't all making sense."*

The north star's own bar for the subject is *"a daily instrument he returns to."* Zero visits in 21 days is the platform's most consequential defect, ahead of every engine bug on the Now milestone. This document is the end-to-end transformation: the evidence, the reader model, the rulings (red-teamed by the Product Board personas plus four stand-ins, with dissent recorded), the page-by-page changes, the instruments that keep it honest, and the sequencing — what shipped overnight, what waits for the owner's morning, what is a week's work.

**The one-line thesis:** the site was organised around the builder's model (the loop, the pillars, the calibration machinery). It has to be organised around the three questions every non-enthusiast asks — *who is he, how is it going, what do I look at today* — with the builder's depth one click down, not cut.

## 1. The evidence (2026-09-26, all verified live)

| finding | measured | source |
|---|---|---|
| The subject doesn't open it | 0 visits in 21 days | owner's report |
| Readers arrive and don't return | ~1,116 uniques / trailing 7 d (surge threshold 1,407) | `/api/receipts` |
| Every door fails the 10-second test on a phone | `/` 3 · `/cockpit/` 2 · `/data/` 2 · `/coaching/` 2 · `/protocols/` 2 · `/story/` 3 · `/data/glucose/` 1 · `/data/labs/` 1 (5 = a friend gets it) | B1 audit, 60 screenshots at 390/1280 |
| The friends' answer exists and is buried | "Is he okay this week?" (#789) sat ~2,250 px down, 2.7 phone-viewports under a 90-word manifesto | B1 `strips/home_m_02.png` |
| The cockpit opens on an invented score | "6 · Foundation" under "a 1–100 score of Matthew's whole day"; weight first appears ~6,100 px down | B1 `cockpit_m_fold_dismissed.png` |
| The coaching door opens on Monday, on Friday | weekly priority `as_of_day_n 16` served on Day 20; two figures stale (316.9 lb / 3.7 lb/wk vs 313.1 / −4.58) | `/api/coaching-dashboard` |
| Seven of fourteen audited pages open on a tutorial | full-viewport "NEW HERE?" cards on `/cockpit/` and every `/data/*` page | B1 §5 item 3 |
| Builder vocabulary, undefined | 71 of 88 pages use it with no gloss; zero `<dfn>` site-wide; one "what's a…?" affordance | B3 census |
| Too many pages | 91 reader-facing pages; 39 reachable from `/` by static links; 52 orphaned from a static crawl | B3 nav reach |
| Two numbers for one quantity | weekly rate −4.58 provisional (`/api/journey`) vs −4.36 firm with a 2027-04-20 goal date (`public_stats.json`); protein 106.9 / 141 / 154 / 153.3 / 142 g across coaches and engine; bedtime "4:45 AM" (a UTC instant) vs 10:30 PM | B2 §4, driver-verified |
| Coach premises the engine contradicts | "six days without logs" against 20/20 days logged, 139–186 g each day | `/api/nutrition_overview` |
| Machine leaks in public prose | `</decision> <parameter name="followed">true` in `/api/decisions`; `[Weight: 315.0 lbs \| Week Grade: avg 74 \| T0 Streak: 0 days]` opening the chronicle | `/protocols/experiments/`, `/story/` |

The pattern is not taste. It is that every first screen answers the builder's question ("which station of the loop is this?") and none answers the reader's.

## 2. The reader model

**Three questions, in order:** who is he · how is it going · what do I look at today. Every door's first screen answers all three in ≤120 words on a 390 px phone, third person, with the date in words.

**The four audiences, re-ordered for this cycle** (the north star's list is unchanged; the *order* flips): the subject and his friends first; enthusiasts keep their depth one click down (`/data/`, `/method/` are un-fronted, never cut); newcomers get the loop as the second screen, not the first.

**The subject's morning questions** (B2, in his voice, each mapped to a served field): did I sleep and can I train hard · what's the scale doing this week, not this morning · what's today's session · am I hitting protein · what did the coaches say I should *do* · what changed since yesterday · is anything about to resolve — and one the platform cannot yet receive: *how do I feel before the number tells me* (#4189).

**Honesty is unchanged and load-bearing (ADR-104/105):** absence reads as absence; n and CI on every statistical claim; the model never does the math; a coach's served text is never rewritten (glossed and, where a figure disagrees with the engine, marked disputed); nothing in the engine changes to make a page simpler — the reader surface is a projection.

## 3. The rulings (red-teamed 2026-09-26; full record in the session's panel verdict, dissent in §9)

Panel: the Product Board (docs/BOARDS.md §3 — Mara, Sofia, Lena, Raj, Tyrell, Jordan, Ava, James) plus Matthew (from the memory record), a friend on a phone, his mother, and an outside data-journalism editor. Tiebreak: the throughline.

| # | ruling | shipped overnight? |
|---|---|---|
| i | **Home** leads with the friends' read directly under the claim; the coaches defined once, in the fold; the three doors as sentences; the loop dial follows as "How the pieces fit" | yes (PR A) |
| ii | **Cockpit** first screen = "the three questions" (how's the week / last night / today), ≤3 numbers per block, third person | yes (PR B) |
| iii | **Character level + pillars:** BELOW the fold on `/cockpit/` only, collapsed, plain key, the same-day served count printed beside any "absent" pillar; the level *name* and XP off reader pages (kept on `/method/character/`). Reverses to OFF if a pillar contradicts its served count on >3 of the next 14 days | yes, except the level-name removal (owner's morning "yes", §7) |
| iv | **Coaching door:** today's read at the top with its written-time in words; the weekly call labelled weekly; a >48 h freshness banner with engine-computed deltas; >7 d → not on the first screen; the docket stays uncollapsed as the return trigger | yes (PR C) |
| v | **"NEW HERE?" cards** → a one-line strip; the definitions move to inline glosses | yes (PR B) |
| vi | **Page-count ratchet:** nav-reachable pages capped, everything else unlisted-but-served; ratchet down from 39 | mechanism yes (PR E); the number (24 proposed) is the owner's |
| vii | **Vocabulary registry** — the fifteen rulings in §6 | registry + guard yes (PR E); the copy changes land door by door |
| viii | **Door names:** subtitles become contents ("today, in one screen" / "his numbers" / …); the nav LABELS (TODAY · THE NUMBERS · THE COACHES · WHAT HE TRIES · THE STORY) are a taste swing to render for the owner | subtitles on the three flagship doors; labels wait |
| ix | Additions: bottom-bar occlusion fixed; the subscribe field in its fold; one canonical weekly rate (#4184); tile titles wrap; dates in words; n beside every percentage; leaks stripped at write/serve (#4190, #4191) | the fixes are filed; the site-side ones ship with their doors |

## 4. Page by page

Format: **what a friend sees now → what it becomes → status.**

### Home `/`
- **Now:** a 60-word manifesto, then the loop dial cut off at the fold; the answer ("down 14.2 lb") one small mono line; "Is he okay this week?" 2.7 viewports down.
- **Becomes:** claim (one line) → one sentence on the setup → day stamp → **Is he okay this week?** (the existing #789 read: the weight move + five plain chips, dated in words) → "A staff of AI coaches — software, not people — reads his numbers every morning and writes him notes. Their calls get checked." → three doors as sentences → *How the pieces fit* (the dial, retitled) → the rest of the arc unchanged.
- **Kept on purpose:** the H1 ("An honest documentary…"), Sofia's share line. **Struck:** "a transformation you can watch happen in real time" (a promise). **Not shipped:** a weight-led headline (Lena's dissent; render for the owner). **No new fetch, no engine change** — the same renderer, moved.
- **Status:** PR A (overnight). Reverses the 2026-07-19 fold pick (#1469 variant A) on the owner's 2026-09-25 ruling; `tests/test_home_okay.py` re-pinned to the new order and says so.

### The Cockpit `/cockpit/`
- **Now:** a full-viewport tutorial; then "6 Foundation"; then rings; weight ~6,100 px down; four different "recovery" numbers on one page; three freshness stamps.
- **Becomes:** kicker "THE COCKPIT · today, in one screen" → **How's the week?** (down X lb over N weigh-ins; Friday's weight; the rate marked provisional with its CI while `rate_provisional`) → **Last night?** (hours, recovery, HRV vs the 20-day baseline with n, the night named) → **Today?** (the session kind + sets from `/api/routine`; yesterday's protein against the floor; *the one ask* from `open_actions[0]` when served — never invented) → one "data through <date>" line → the daily line → rings (the null readiness ring removed) → **the engine's score for yesterday — what built it** (the level, collapsed, with the plain key and the same-day served count beside any "absent" area) → the rest.
- **Status:** PR B (overnight). The level name/XP removal is the one piece held for the owner (§7).

### The Coaching `/coaching/`
- **Now:** a navigation paragraph ("Start with the read… the Third Wall…"); the portraits disclaimer as the first definition of "AI coaches"; Monday's read on Friday.
- **Becomes:** kicker "THE COACHING · Day N" → the definition line → **TODAY'S READ** (the freshest served coach read, verbatim, "written Fri 10:05 AM PT", with the ask when served and the record as "N predictions checked, K came true") → the freshness banner when >48 h → where they disagree (uncollapsed) → the other coaches one line each with their dates → **THE WEEK'S CALL · written Monday <date>** → sections. "AI lab notes / the Third Wall" → "What the AI said, and how it felt." `/method/board/` states the weekly cadence (closes the open half of #4163).
- **Status:** PR C (overnight). A *daily* grounded lead read is #4188 (engine); until it exists the door shows the freshest staff read with its age in words.

### The Data `/data/` and topics
- **Now:** the tutorial card, then a paragraph of "correlative, read-only, flagged when thin"; no number in the fold; `/data/glucose/` is a page of "NO SENSOR YET"; `/data/labs/` opens on an April draw and 16,000 px of rows.
- **Becomes:** strip instead of card (PR B ships the strip for every `/data/*` page); subtitle "his numbers"; the fold carries one number per topic (the topic's headline stat is already served — the renderer surfaces it above the chart rail); glucose says "blood sugar — no sensor this cycle" everywhere it is named and is unlinked from the nav once the owner confirms no sensor is planned; labs opens on "last blood test: April 3, before this cycle" and the flagged markers, with the printout collapsed; tile titles wrap so "153 bior" never happens.
- **Status:** the strip overnight; the rest this week (stories to file after the owner's review — each is a renderer change in `evidence_*.js`).

### The Protocols `/protocols/`
- **Now:** "the levers" + "the N=1 instrument: hypotheses run as read-only proof"; a seven-week-old CORRECTION box as the first block; raw decision logs with a tool-call tag and "from the mcp · overrode it".
- **Becomes:** subtitle "what he takes and tries"; cards say "what he's trying" and "measured by" in plain words; the correction box moves under the cards with its date; the decision log renders his words only (the residue stripped at write and serve — #4190; the transport name never rendered).
- **Status:** #4190 lane overnight (engine + serve); the copy this week.

### The Story `/story/`
- **Now:** the closest to what a friend wants (score 3), but opens on process ("Next Chronicle installment drafted Wednesday…"), the latest entry six titles down, and the first sentence is `[Weight: … | Week Grade: … | T0 Streak: …]`.
- **Becomes:** the latest entry's first paragraph in the fold, its date in words, "next write-up: Wednesday Sep 30" as the return trigger; the bracketed stat line parsed into a labelled stat row or moved to a structured field (#4191); "chronicle" stays in Elena's byline, the nav word becomes "the weekly write-up"; the week label and the permalink agree (S13).
- **Status:** #4191 renderer side this week; the write-side fix is the same issue.

### The Method `/method/*`, `/gear/`, `/subscribe/`, `/privacy/`
- Footer-tier stays footer-tier; nothing here is cut. `/subscribe/`: the field moves into the fold; the page says "averagejoematt", not "The Measured Life" (S16); the subscriber counter is the owner's call (§7). `/method/board/` gets the cadence line (PR C). `/method/registry/` (3,640 words) is the builder's page and stays as it is.

## 5. Amendments to SITE_MAP_AND_INTENT.md (intent, not counts)

- **Home — must deliver**, in this order: the friends' read (weight move + five plain lines, dated in words), the coaches defined once, three doors as sentences; *then* the loop diagram. The day counter stays.
- **The Cockpit — must deliver:** the three questions first; the whole-life score is a second-screen instrument with a plain key, never the first thing on the page.
- **The Coaching — must deliver:** one read per day at the top with its written-time; the weekly call labelled weekly; freshness stated in words on the first line.
- **Every door — first screen:** answers *who / how it's going / what to look at* before it answers "which part of the loop am I". The loop rule stands for the second screen.

## 6. The vocabulary rulings (the registry's seed — PR E)

| term | ruling | reader-facing form |
|---|---|---|
| reset | rename | "a fresh start" in prose; "cycle 17, started Sep 6" in labels |
| correlation | keep + gloss | "moves together with — not caused by" |
| cockpit | page name only; nav label renamed later | "today's page" |
| chronicle | rename | "the weekly write-up" (byline keeps Elena's title) |
| model | rename by sense | "the forecast" / "the engine" |
| as of / as_of | rename | "data through Sep 25" · "written Fri 10:05 AM PT" |
| cycle | keep + gloss | "one attempt at this experiment, from a start date" |
| Third Wall | cut | "What the AI said, and how it felt" |
| pillar | rename | "the seven areas" (his word "pillars" as the gloss) |
| protocol | keep on the door; rename in cards | "what he's trying" |
| gate | cut from reader pages | (stays on `/method/*` and essays) |
| HRV | keep + gloss | "heart-rate variability — a nightly nervous-system reading; higher is usually better rested" |
| glucose | keep, with the honest state | "blood sugar — no sensor this cycle" |
| Whoop + devices | keep + gloss once per page | "Whoop (a wrist band that scores sleep and recovery)" |
| character level | rename | "the engine's score" |

Mechanism (charter primitives 1+2): `site/data/glossary.json` is the registry; a test walks every reader page's main content and fails when a registered term appears with no gloss on its first use, with the current occurrences carried as a dated, shrink-only baseline.

## 7. The owner's morning decisions (one numbered list)

1. **The door labels** — render TODAY · THE NUMBERS · THE COACHES · WHAT HE TRIES · THE STORY beside the current set; pick.
2. **The home headline** — keep "An honest documentary of an ordinary life, rebuilt with AI." (shipped) or lead with "Matthew is losing weight in public, with his own numbers." (Lena dissents; the friend and the mother asked for it).
3. **The level name and XP** off reader pages (the panel's ruling; it deletes a mechanic you built).
4. **The page cap number** — 24 proposed (`/` · `/cockpit/` · `/data/` + sleep, training, nutrition, physical, labs · `/coaching/` + read, by-coach, scorecard · `/protocols/` + supplements, experiments · `/story/` + chronicle, journal, about · `/method/` + character, registry · `/subscribe/` · `/privacy/`); strike or add.
5. **Unlink `/data/glucose/`** until a sensor is worn — confirm none is planned this cycle.
6. **The subscriber counter** ("Subscriber 1 so far") — hide below a threshold, or keep the honest number.
7. **Engine PRs to merge + deploy** (outside the overnight site grant): #4192 (`open_actions`), #4193 (the genesis-bounded rate), the reader-truth legs (#4180+#4186), the residue guard (#4190) — one fleet deploy, plus `deploy_site_api.sh`.
8. **The 09-08 decision record scrub** (a DDB write) and the already-published chronicle issues carrying the bracketed line (a regenerate-or-edit of stored artifacts).
9. **Photos (#3761)** — now on the critical path of the front door.

## 8. Sequencing

- **Overnight (2026-09-26, shipped as PRs, merged through the visual gate under the 09-25 grant):** PR A home · PR B cockpit + strips · PR C coaching + `/method/board/` cadence · PR D leak renderers · PR E the two registries. Engine lanes opened, not merged: #4192, #4193, #4180+#4186, #4190.
- **This week:** the data and protocols door copy; the story fold; the vocabulary passes door by door against the registry; the nav labels once picked; the coach-vs-coach and coach-vs-engine legs live; #4185 (coach premises) and #4188 (a daily lead read) in the engine.
- **Measured at 30 days:** the owner's own visit count (his report) and the return rate from `/api/receipts` — recorded on #4182. The site is not "done" when the PRs merge; it is done when he opens it.

## 9. Dissent register (so the owner can overrule)

- Home order — Raj (wanted the dial in the fold), Sofia (wanted the H1 as the fold headline; it is kept in the fold tonight).
- Cockpit — Raj (wanted the score + rings first); Tyrell (rings on screen two, not one).
- Pillars — Mara, Sofia, the friend (wanted OFF entirely); Raj (wanted the level name kept).
- Vocabulary — Ava ("Third Wall"); Raj ("character level"); Sofia ("chronicle" as a nav word).
- Door names — Sofia (the labels).
- Voice — Raj (second person on the cockpit); the panel ruled third person site-wide.
- Kicker — Ava ("a transformation you can watch happen in real time"); struck as a promise.
- Weight-led home headline — Lena dissents on north-star grounds; deferred to the owner.

## 10. How to verify a change to any of this

The playbook loop, unchanged: render before and after at 390 + 1280 with **real data** (the overnight harness routes `/api/*` to saved live JSON — `tests/pr_render_gate.py` is empty-mock and structurally blind to data-driven layout), `node scripts/import_site_js_graph.mjs`, `node --test`, `tests/test_css_tokens.py` on any CSS diff, the structure tests named in each PR, then the live smoke after deploy. Every first-screen number carries its `[served: field]` provenance in the PR body.
