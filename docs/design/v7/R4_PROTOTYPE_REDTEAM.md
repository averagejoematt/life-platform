# R4 — The same five readers, two prototypes

**Written:** 2026-09-26 13:20–14:05 PT. Read-only. Same personas, same scoring as R2 (live site: loseit 3 · QS 5 · HN 4 · mother 4 · Matthew 4).
**Method:** both files wrapped in a doctype + viewport meta and rendered with Playwright at 390×844 and 1280×900; every built screen shot full-page at 390, the home fold at 1280 (`r4/{A,B}_<screen>_{390,1280}_{full,fold}.png` beside this file, `r4/shoot.py`). Every number below was traced against `../b2/*.json` and `../coachvoice/*.json` (fetched 16:46Z). Quotes are verbatim from the page.

**Measured, 390 px (786 px usable fold):**

| | A "The Seventeenth Start" | B "The Logbook" |
|---|---|---|
| Home height / screens / words | 3,591 px · 4.6 · 922 | 4,000 px · 5.1 · 938 |
| Coaches | 2,419 · 3.1 · 666 | 2,529 · 3.2 · 606 |
| This week | 844 · 1.1 · 142 | 1,343 · 1.7 · 303 |
| Horizontal overflow at 390 | none | none |
| JS errors | 0 | 0 |
| GitHub link on home | yes ("How it works") | **none anywhere** |
| Photo of Matthew | empty frame | empty frame |

(The live home was 11,120 px / 14.3 screens. Both prototypes cut it by two-thirds. That alone moves every score.)

---

## 1. r/loseit

**A, first ten seconds:** dashed box "His photo goes here — Matthew adds it. dated · same clothes, same light" · "313.8 lb · Saturday, September 26 · Down **13.5 lb** in 21 days, from 327.3. · 13 weigh-ins · about 4.4 lb a week (2.8 to 4.7), provisional." · the flat sparkline · "His seventeenth counted start; day 21 is already farther than any of the sixteen before it got — the longest ran 13 days."
*Number, date, range, how many times he actually stepped on the scale. And he's saying out loud that he's quit sixteen times. Where's the food.* Scrolls: "averaging 1,577 calories and 153 g of protein. The 170 g protein floor was cleared on 7 of those 20 days." *There it is. 1,577 at 313 lb — that's aggressive, and 7 of 20 on protein is the number he should be embarrassed by. Good.*
**First tap:** "His numbers" → "Not in this prototype." She taps back.
**Posts:** "OK this one has the number, the date, the range, the calories AND the fail count — 7 of 20 on protein, 16 quit starts. The empty photo box that says 'Matthew adds it' is a to-do list I'm not supposed to see. Take the picture."
**Score: 6/10.** **One change:** the frame must not read as a chore assigned to him in public — replace "His photo goes here — Matthew adds it" with a dated promise: "No photo yet. The first is due Monday, October 5 — day 30."

**B, first ten seconds:** the same number in a big condensed face ("313.8 lb · weighed Saturday, September 26 · Down 13.5 lb in 21 days, from 327.3 · 13 weigh-ins · about 4.4 lb a week, provisional (2.8 to 4.7)"), the frame ("taken: —"), then the highlighted "**Day 21 is farther than any of the 16 earlier starts got**", then — still in the fold — "Every weigh-in this start" with thirteen dots and "No weigh-in between Sunday, September 6 and Saturday, September 12; the scale skipped 8 of the 21 days."
*That's the weigh-in chart I always go looking for, on the front page, with the skipped days admitted.* Scrolls: "Logged food 20 of 20 days … 1,577 calories and 153 g protein … 7 of 20 days."
**First tap:** "The numbers" → "Not in this prototype."
**Posts:** "The weigh-in chart with the gaps is the best thing either version has. Lose the typewriter font on his quotes — it's a Telegram message, not a letter from the front."
**Score: 7/10.** **One change:** the "In his own words" entry quotes him on lifting splits ("No I wanna do push"); the mother and loseit both want the September 6 line A found — "I am 320+lb and have not worked out consistently for a long time" — and B doesn't use it.

## 2. r/QuantifiedSelf

**A:** reads the fold, then "How it works" — "Every figure on this page is computed by code, not by an AI, and carries its date and its count … The code, in full: github.com/averagejoematt/life-platform". *Repo on the home page, one screen up from the bottom. And "the coaches' checked calls this start, by the site's scorekeeper: 18 of 37" — a denominator in the masthead line.* On the coaches screen she finds the thing she'd screenshot: "Per-coach 'K of N' is not printed here yet: three scorekeepers disagree on the same day (Webb reads 0 of 5, 20 of 25 and 80 percent)." *A site admitting its three ledgers disagree, and refusing to print any of them until one is canonical. That's the honesty page done right.* Opens devtools: `<script type="application/json" id="served">` — every number keyed to its file.
**First tap:** The coaches. **Posts:** "The 'three scorekeepers disagree so no hit rate is printed' paragraph is the most honest line I've seen on a QS site. Still no CSV." **Score: 6/10.** **One change:** the "hit" line — "He said recovery would trend upward over the first two weeks — it did." — the served record is `recovery_score trend=up (slope=0.1439), predicted=up`; "over the first two weeks" is not in it. Print the graded window or drop the gloss.

**B:** the fold is fine; she goes hunting for the repo and there isn't one — the four-sentence "How it works" says "a store he built and runs himself" and never links it. *Zero GitHub links on a prototype built for the person who asked for the GitHub link in the header.* She does find `data-src="api_journey.journey.current_weight_lbs"` on every figure and a `#served-data` block — better provenance than A's, invisible to a reader. On the coaches screen: "7 of 17 · right; graded over-confident" and, under the fold, "0 of 5 … three scorekeepers disagree on him: 0 of 5 here, 20 of 25 on another page — the 20 are one August bet counted again every day."
**First tap:** The coaches. **Posts:** "Every number has a data-src attribute and none of them is a link. Put the repo in the masthead." **Score: 5/10.** **One change:** the GitHub link, in the masthead line, on every screen.

## 3. Hacker News (1280×900, console open)

**A at 1280:** a 680 px serif column centred in the viewport, a phone bottom bar pinned across the bottom of a laptop window. *It's a phone page, centred.* The prose holds up: "The odds of reaching day 30 are withheld: no start of his ever has." Then the coaches screen: "**miss** For Friday, September 11, he said the night's recovery would land near 60, give or take 18 — it came in at 24." *That's a ledger line.* Then the served paragraph: "His recovery EWMA climbed to 81.6% over seven days with a 99% reading on the night of 2026-09-24 … autocorrelation analysis shows insufficient consecutive same-direction points … lean mass liquidation risk is real … thyroid adaptation risk". *The coach is still an LLM, and the site glosses "EWMA" underneath instead of not printing it.* The disagreement block at ≥601 px becomes three columns — two witnesses, the seven numbers between them — that is the table he asked for.
**Posts:** "The disagreement-with-the-number-between-them and the 'three scorekeepers disagree' admission are real. The coach paragraph is still Claude talking about 'lean mass liquidation'. Repo link is there. Desktop is the phone page centred." **Score: 7/10.** **One change:** the "due" line quotes the coach verbatim — "On 2026-09-18 I flagged the step contraction as a DUE item" — an ISO date and a Jira word in the first thing a reader sees; the rule is guarded or empty, so empty.

**B at 1280:** a left rail (I THE LOG · II THE COACHES · III THIS WEEK · IV THE NUMBERS · V WHO HE IS), a 760 px column with a red margin rule and the day in the margin. *This one was laid out for a laptop.* The coaches screen: "✓ For the night of Friday, September 18 she said about 7.3 hours of sleep, give or take 1.3 — it came in at 7.9. Right. graded Thursday, September 24 · sleep_duration_hours". *Snake_case on the reader page.* Then the served letter: "The morning log you're filling in before Whoop loads is functioning as a crucial calibration tool" — and B's own note under it: "no morning log from him exists in the served data — the platform has no field that can receive one. She is describing entries that were never made." *The site fact-checking its own coach, in line. That's the build-log voice on the front page — and it's a bug report, not journalism.* The versus table with "THE ENGINE, BETWEEN THEM · Recovery 77 this morning · 73.9 average over the 21 nights" is the docket as a table.
**Posts:** "The versus table is exactly the thing. The coach text is a letter about logs that don't exist and the page says so — fix the coach, don't annotate it. No repo link. The typewriter font and the ruled paper are a costume." **Score: 6/10.** **One change:** delete the `sleep_duration_hours` / `recovery_score` grade labels and the "(night_of in the served record)" leak — that is machine vocabulary on the reader page.

## 4. His mother

**A:** "313.8 lb" — "Down 13.5 lb in 21 days" — "His photo goes here — Matthew adds it." *Still no picture.* Then, in the first screen and a half, in his own typing: "I am 320+lb and have not worked out consistently for a long time. So I want tomorrow to be day 1." *That's him.* Then "IS HE OKAY THIS WEEK? SLEEP Friday night he slept 8.6 hours — the wrist strap and the bed sensor agree." *I understand every word of that sentence.* "His journal has been silent since Wednesday, September 9 — 17 days. Nothing from him this week."
**First tap:** The coaches — the word "Dr." — and reads "lean mass liquidation risk is real, and I'm coordinating with the labs coach on thyroid adaptation risk". She calls him about his thyroid.
**Score: 6/10.** "Is he okay" is answered in one screen in plain sentences; the coach text is written *about* him ("His recovery … I've asked him") so it reads as a case note, not a leaked letter — but it is a frightening case note. **One change:** the Reyes paragraph must not be the read of the day; pick a coach whose served text a mother can read, or run the guard and show the ledger lines only.

**B:** the number, then "A 300-plus-pound man on his seventeenth start, publishing his own numbers and eight AI coaches' reads of them, whether or not it works." *Whether or not it works — well, that's honest.* The weigh-in chart. Then "In his own words" in typewriter blue: "Yes lets switch to this - i like it - but we dont need to be so prescriptive of DAY of the week" and "No I wanna do push". *That's him talking to the computer about gym days.* "Is he okay this week?" is 2.5 screens down: "Slept 8.6 hours the night of Friday, September 25 (night_of in the served record); recovery 77 percent; heart-rate variability, a recovery signal, at 46.5 ms against his 21-night average of 41 (n=21)." *What is night_of. What is n.* "JOURNAL Nothing written in 17 days — since Wednesday, September 9. Stated as absence; nobody here calls it 'going dark'." *Who said going dark? Why is it telling me what it isn't saying?*
**First tap:** The coaches: "WRITTEN TO MATTHEW — SERVED AS IS, NOT REWRITTEN / The morning log you're filling in before Whoop loads…" *This is a letter to him. I'm reading his mail.* Then the site says the letter is about logs he never wrote.
**Score: 5/10.** **One change:** the coach quote labelled "Written to Matthew" reads as a leaked letter, and the correction under it tells her the doctor is confused; on the coaches screen show the three ledger lines and the counted thread, and put the served letter one tap down.

## 5. Matthew, Tuesday 6:40 AM

Both "Today" screens are stubs, so he judges the frame. **A:** the masthead says "week 3 · day 21" and the home says everything he already knows; the one line that's for him is in the record table: "Dr. Lisa Park · sleep — has asked for one morning word on 22 dated records since Sunday, September 7; none has come back, and there is no channel yet to receive it." *Twenty-two. Fine. Nobody is saying I blew it, they're saying the form doesn't exist.* **Score 5/10.** **One change:** "What resolves next" is the only forward-looking block on the site and it has no row for him — add the one ask with its due date and the word "late".

**B:** the thread box on the coaches screen: "She has asked for a morning note before he opens the app on 17 of her 19 mornings since Sunday, September 6, and lowered the price each week: a 1-to-5 rating (September 11 to 18) → three words (September 20) → two words (September 23 and 24) → four words (September 25). Latest version, asked Friday, September 25, due Friday, October 2. **Not one has been answered on the record** — 38 asks held, 1 kept, 30 still open." *That's the line I asked for in R2 — someone finally said it.* (Two → four words is not "lowered the price"; the sentence argues with its own sequence.) And on the home: "The next weigh-in is tomorrow morning." **Score 6/10.** **One change:** the Tuesday screen — the three questions + the session with loads + this thread box — is the whole product for him and it is the stub in both.

---

## Cross-cutting

### (a) The ten-second test (photo frame + dated number with range · premise with receipt · alive-and-keeps-score)
Both pass all three inside the 390 fold, measured: A's fold carries the frame, "313.8 lb · Saturday, September 26 · Down 13.5 lb … (2.8 to 4.7), provisional", the seventeenth-start sentence with "the longest ran 13 days", and "Data through Saturday, September 26 · 18 of 37 right · next write-up Wednesday, September 30". B's fold carries the same three and, additionally, the start of the weigh-in chart. B's fold prints the receipt louder (the green-washed "Day 21 is farther than any of the 16 earlier starts got"); A's prints it as a sentence. Both bury "alive" in a mono line a mother skips. Judge-baseline note: both folds would score 2 on "what is this page for"; neither answers "what would you click" — both bars are five nouns.

### (b) "Real thoughts with memory, not state in time" — the coaches screen
- **A** opens Reyes with: "**miss** For Friday, September 11, he said the night's recovery would land near 60, give or take 18 — it came in at 24." Lands — number, date, what he said, what happened. The second line ("trend upward over the first two weeks — it did") is a gloss on `trend=up, predicted=up` and does not land; the third ("On 2026-09-18 I flagged the step contraction as a DUE item") is the coach quoting his own ticket. One of three lands.
- **B** opens Park with: "For Friday, September 11 she said recovery about 66 — it came in at 24, the worst night of this start. Wrong by 42. graded Thursday, September 24." Lands hardest of anything on either page — and then the thread box turns the ledger into memory ("asked on 17 of her 19 mornings … Not one has been answered"). Three of three land; the snake_case grade labels under them undo some of it.
- Both curate: Park's served `recent` has six graded records (2 confirmed, 4 refuted); B shows 1 + 2 and omits the 09-25 confirmed 59-vs-52.9. Reyes has three (2 confirmed, 1 refuted); A shows 1 + 1 and omits the confirmed 64-vs-61. Neither says "the last N graded", so both are a sample presented as the record. Fix in both: "the last three graded" with all three.

### (c) Slop check
- **A:** "The error is theirs, and it is still on their pages." — a person wrote that. Generated-reading: none in A's own prose. The served Reyes paragraph is entirely machine: "favorable data point rather than a confirmed trend", "gates downstream training decisions", "dangerous fragility around dinner dependency", "lean mass liquidation risk is real". **Machine words on A's reader page:** EWMA (twice, once glossed — the gloss is the tell), "DUE item", "2026-09-18", "2026-09-24", "gates". Changelog sentence on a reader page: "one keeper is being made canonical before any hit rate is printed beside a name."
- **B:** generated-reading in B's own prose: "Stated as absence; nobody here calls it 'going dark'." (honesty announcing itself — R2 slop tell #2) · "the one number here that is plainly low" · "the channel for it is being built" (changelog on a reader page) · "memory is a property of the form" lives only in the comment, good. The served Park letter: "functioning as a crucial calibration tool", "fragmenting sleep architecture without necessarily destabilizing autonomic tone", "They're the decoder." **Machine words on B's reader page:** `sleep_duration_hours`, `recovery_score` (grade labels, three times), "night_of", "n=21", "n=20", "calibration ledger" (banned list), "calibration tool" (served).
- Neither has a "Not X. That's Y." sentence, a loop, a station or a pillar. Both cleared R2's main slop findings.

### (d) Honesty check — traced to `../b2/`
Traced and correct in both: 313.8 / 327.3 / 13.5 / 21 / 13 weigh-ins / −4.36 (−4.74, −2.75) / span 20 / 16 prior, 0 reached, longest 13 / 18 of 37, 31 of 84 / 8.6 h, 77, 46.5 vs 41 (n=21) / 20 days, 1,577, 153.3, 7 of 20 / 2,245 (n=20) / journal 17 / $102.74 / one subscriber / next write-up 09-30 / both dockets, both stakes (Park 0.2507 n=20, Reeves 0.25 n=4) / the 24→94 (09-11, 09-17) / the seven nightly readings 98·90·78·80·86·99·77 with none on the 20th / Park's three ledger lines (7.91 vs 7.3±1.25; 44 vs 66.2±17.9; 24 vs 66.2±17.9) / Reyes' miss (24 vs 59.5±17.9) / 36 held, 8 kept, 3 broken / 38 held, 1 kept, 30 pending / 468 unresolved, 49 graded, 37 kept / the two decision notes and their timestamps / journal titles, dates, word counts / the "prior's residue" quote and the 6 % ceiling / 7 collapsed, 9 censored / 33 workouts, 19 strength / 167 strength minutes on 09-25 / W39 9 workouts, 1,055 min / 10:31 PM / 73.9 / forecast 313.2 (303.4–322.9), 89.1 (58.7–100) / cgm last seen 08-27 / 17 of 19 morning asks.

**Not traceable, or stated beyond the data:**
- **A** "Three coaches wrote this week that his food log went dark after September 19" — one traced (`api_coaching-dashboard coaches[1].position_summary`: "The food log went dark after September 19th"); the other two I could not find in `b2/` or `coachvoice/`. Print "the nutrition coach wrote" until three are cited.
- **A** "Five calls filed on day 1 come due" — five predictions due 09-27 exist (3 steps, 2 resting heart rate); nothing in the served record says they were filed on day 1.
- **A** "He said recovery would trend upward over the first two weeks — it did." — "first two weeks" is not in `recovery_score trend=up (slope=0.1439), predicted=up`.
- **A** "Sunday, September 6, 9:02 pm — the evening before day 1" — the served `day_n` makes September 6 day 1 (day 21 = September 26); his note says "I want tomorrow to be day 1". A adopts his count in the caption and the site's in the masthead. Say "the evening of day 1, which he called the day before".
- **A** "Fifteen lifting sessions and fourteen walks in the last 30 days" vs **B** "33 workouts in the last 30 days, 19 of them lifting" — both served (`top_activities` WeightTraining 15 vs `strength_sessions_30d` 19). Two producers for "lifting sessions"; whichever ships, the other must go (engine defect, same class as §14's record producers).
- **A** "22 dated records since Sunday, September 7" vs **B** "17 of her 19 mornings since Sunday, September 6" for the same ask — `dossier.commitments` vs `recent_outputs`. Both true by their field; neither names it. Pick one.
- **B** "Will recovery fall under 70 on Wednesday, September 30, **if evening carbs are cut**?" — the criterion is unconditional `recovery_score < 70 on 2026-09-30`; the conditional comes from the topic text. Code will grade it whether or not carbs are cut. Drop the "if".
- **B** "lowered the price each week: … two words (September 23 and 24) → four words (September 25)" — four is more than two; the sequence is served, the "lowered" is not.
- **B** "Dr. Lisa Park says yes — the jump from 24 to 94 was real repair" — fine; but the same table prints "Brier 0.25" for both with no gloss; A glosses it ("what a coin flip scores"). B's mother cannot read "Brier".
- **Both**: the attempts chart is drawn to a 61-day scale (A: `cell 4.8 × 61 ≈ 293 px of a 358 viewBox`; B labels "day 61"). Row 17 runs off the right edge at day ~61 — the frame's own honesty chart breaks in week 9.
- **Both**: "Day 21 is farther than any of the 16 earlier starts got" is true today and must be rewritten by code on day 31 ("the first start past day 30") or it becomes the site's biggest lie on the day it stops being true.

### (e) The photo frame
Both frames are honest and both read as a note-to-self published by accident — A: "His photo goes here — Matthew adds it. dated · same clothes, same light"; B: "His photo goes here. Matthew adds it — dated, same light each time. taken: —". r/loseit and the mother read "Matthew adds it" as *he hasn't bothered*; HN reads it as a placeholder that shipped. It helps only the QS reader (a stated absence is a receipt). What it should say, in both: **"No photo yet. The first is due Monday, October 5 — day 30."** — a dated promise (§7), no instruction to him, and it converts the empty frame into the site's first return trigger. Keep "same light, same clothes" for the caption once a photo exists.

### (f) The mother test
"Is he okay" is on the home screen in both — A at ~1.5 screens ("Friday night he slept 8.6 hours — the wrist strap and the bed sensor agree" is the most mother-readable sentence either prototype has), B at ~2.5 screens with `night_of` and `n=21` in the sleep line. Neither gives her a line from him about how he *is*; A's first quote ("I am 320+lb and have not worked out consistently for a long time") is the closest thing either has and B doesn't use it. The coach quote: **B's "WRITTEN TO MATTHEW — SERVED AS IS" is a leaked letter by construction** — second person, "the morning log you're filling in", "Keep the logs running. They're the decoder." — and then the page tells her the letter is about logs he never wrote. **A's is a case note** ("His recovery … I've asked him directly") — read as intended, but its content ("lean mass liquidation risk is real … thyroid adaptation risk") sends her to the phone. Neither is safe as the day's read; both need the guard to pick, or the ledger-only render.

### (g) Laptop width
**A does not hold at 1280:** a 680 px column centred in 1280 with a phone bottom bar across the full window width; the only desktop-aware element is the disagreement block (three columns at ≥601 px). It is a phone page centred. **B holds:** at ≥900 px the bar becomes a left rail, the margin widens to 92 px with the weekday shown, the fold grid goes to 150 px + big figure at 96 px, the bet cards go two-up. The right third of the window is empty (760 px column left-hung at 200 px), but it is a laid-out page.

### (h) Which FRAME survives 20 weeks of real data (the deciding question)
- **A, "the case so far":** a summary page that must be re-summarised weekly. A week where nothing happened → the same page as last week with a new date; honest but inert. A week he vanished → "Data through" stops advancing and the attempts chart's row 17 grows pale cells; the reader has to know to read the mono line. A week he gained → the lede is cumulative ("Down 13.5 lb … from 327.3"), so a +2 week hides inside a smaller "down" until the sparkline is read. "In his words" is a curated pair of quotes with no slot for the next one. "What resolves next" empties when no docket is open (the table has no empty state). The frame reports a state; it has no place for time to pass.
- **B, "a logbook kept in public":** every block carries a day in the margin. A week where nothing happened → an entry dated that week that says so. A week he vanished → the top entry's margin date doesn't move, in 18 px bold, at the top of the page — the frame shows absence without a sentence. A week he gained → one more dot on "Every weigh-in this start" and the fold's number goes up; the margin date makes it a dated fact, not a hidden delta. The Park thread box ("asked on 17 of her 19 mornings") is an object that accumulates by construction. B's weakness is that today's log page is *not* actually in date order (26 Sep · 6 Sep→today · 23 Sep · 26 Sep · 17 starts · § · 30 Sep · →) — sections wearing dates — so at week 20 the "In his own words" entry dated 23 Sep would sit visibly stale under a February masthead. That is a virtue (the staleness is printed) and a build obligation (the entry must carry the latest dated note, or say "last note: 23 Sep").
- Both share two 20-week failures: the 61-day attempts chart (breaks week 9) and the day-21 lead sentence (breaks day 31 unless code rewrites it).

**B's frame survives; A's type and voice are the ones to keep.**

---

## THE PICK: B's frame with A's type

Build the logbook — dated margin per entry, the left rail at laptop width, the ledger line with the graded date and "Wrong by 42", the counted thread box, the versus table with the engine's number between the witnesses, the weigh-in chart with the skipped days on the home — and set it in A's type and voice: Newsreader/Plex, third-person captions, no typewriter face, no ruled-paper "hand" (his Telegram notes are typed; the costume is a fib of form), A's "Is he okay" sentences ("the wrist strap and the bed sensor agree"), A's September 6 quote first, A's repo line in "How it works", and A's coin-flip gloss on Brier. Section headers stay as B has them; the day in the margin must be a real date of the entry, not a label.

**Scores (would I follow):**

| persona | live (R2) | A | B |
|---|---|---|---|
| r/loseit | 3 | 6 | 7 |
| r/QuantifiedSelf | 5 | 6 | 5 |
| Hacker News | 4 | 7 | 6 |
| his mother | 4 | 6 | 5 |
| Matthew, Tuesday | 4 | 5 | 6 |
| **total** | 20 | **30** | **29** |

## The five fixes, in priority order (for the picked build)

1. **Strip every machine word from the reader page before anything else:** delete the `sleep_duration_hours` / `recovery_score` grade labels and "(night_of in the served record)", "n=21", "n=20", "calibration ledger" from B; and do not print a served coach paragraph that contains EWMA, an ISO date, "DUE item" or "gates" — the rule is guarded or empty, so render the ledger lines + the thread box and put the served text one tap down under "what she wrote, as served".
2. **Put the repo in the masthead line on every screen** ("averagejoematt · day 21 · the code") and keep A's "How it works" paragraph with its `github.com/averagejoematt/life-platform` link — B has no GitHub link anywhere.
3. **The photo frame text becomes a dated promise:** replace "His photo goes here. Matthew adds it — dated, same light each time. taken: —" with "No photo yet. The first is due Monday, October 5 — day 30."
4. **Print the whole recent record, not a sample:** "the last three graded" for Reyes (24 vs 59.5 miss · trend-up hit · 64 vs 61 hit) and "the last six graded" for Park (two right, four wrong), and cite the count's producer — one of "22 dated records" (`dossier.commitments`) or "17 of 19 mornings" (`recent_outputs`) — not both across the site.
5. **Make the two frame-breakers time-proof now:** the attempts chart draws to the longest strip (row 17 will pass day 61 in week 9), and the lead sentence "Day 21 is farther than any of the 16 earlier starts got" is generated by code with its day-31 successor already written ("the first of his starts to pass day 30"); the "if evening carbs are cut" conditional on the September 30 bet is deleted — code grades `recovery_score < 70` unconditionally.

Also filed against the engine, not the page: two producers for "lifting sessions in 30 days" (`top_activities` 15 vs `strength_sessions_30d` 19); "three coaches wrote that his food log went dark" traces to one served field, not three.
