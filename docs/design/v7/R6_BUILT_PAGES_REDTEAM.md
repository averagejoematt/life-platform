# R6 — The same five readers, the three built pages

**Written:** 2026-09-26 15:30–15:55 PT. Read-only; nothing committed in any lane.
**Heads rendered:** Home `897bcd021` (PR #4235, in CI at hand-back), The coaches `3cdd64a8c` (PR #4234, red/conflicting and being fixed — this is the pre-fix head), This week `c3cb37f32` (PR #4233, since merged).
**Method:** each lane's `site/` served by `harness/render.py` (routes `/api/*`, `public_stats.json`, `journal/posts.json` to the 16:46Z `b2/` corpus; the corpus predates #4230 and #4225) at 390×844 and 1280×800 → `v7/r6/{home,coaches,week}/*.png|txt`. Then `v7/r6/measure.py`: a JS-off render (`java_script_enabled=False`), fold word count from text-node rects above 844 px, an inventory of every `[data-src]`, `scrollWidth`, and a degraded render with `api_journey`, `api_calibration`, `api_coaching-dashboard`, `api_coach_docket`, `api_sleep_detail` and `journal/posts.json` deleted (`v7/r6/degraded_*`). Prototype C's screens from `r5/C_*_390_*.png` and `r5/C_text.txt`. Every number checked against `b2/*.json` by hand. Quotes are verbatim from the rendered page.

**Measured (390, JS on, 0 page errors on all three, `scrollWidth` 390 at 390 and 1280 at 1280 — no overflow):**

| page | height | words | fold words | first entry closes at | JS-off words |
|---|---|---|---|---|---|
| Home `/next/` | 4,336 px (5.5 screens) | 830 (C: 1,016) | 144 (C ≈116) | 725 px — the lead sentence is inside the first screen | 190 |
| The coaches `/next/coaching/` | 4,232 px (5.4) | 655 (C: 766) | 135 | **2,324 px — "Today's read" alone is 2.9 screens** | 110 |
| This week `/next/story/` | 2,091 px (2.6) | 260 (C: 288) | 101 | 899 px | 41 |

Owner ruling 14:10 PT (no cycle/attempt/start count on the site) is honoured on all three: the "seventeenth counted start" lead, the attempts chart and "the sixteen before it" are gone from Home by design. I do not score against the ruling; I do note what each reader lost.

---

## Scores (would I follow)

C's per-screen numbers are my re-read of R5 by persona (R5 scored the prototype whole at 36); the built columns are fresh.

| persona | C log → **Home** | C coaches → **The coaches** | C week → **This week** |
|---|---|---|---|
| r/loseit | 8 → **8** | 6 → **5** | 7 → **7** |
| r/QuantifiedSelf | 7 → **7** | 7 → **6** | 7 → **7** |
| Hacker News | 8 → **8** | 8 → **6** | 8 → **7** |
| his mother | 7 → **7** | 7 → **5** | 7 → **7** |
| Matthew, Tuesday | 6 → **6** | 6 → **6** | 6 → **6** |
| **total** | 36 → **36** | 34 → **28** | 35 → **34** |

---

## Home — 36/50 (holds C)

**Ten seconds (390 fold, verbatim):** "No photo yet. The first is due Monday, October 5 — day 30." — "313.8 lb · Saturday, September 26 · Down 13.5 lb in 21 days, from 327.3. · 13 weigh-ins · about 4.4 lb a week (2.8 to 4.7), provisional. · **This week: 315.0 → 313.8 lb since Tuesday's write-up.**" — "Day 21 of an experiment run in public: a 300-plus-pound man, his own numbers, eight AI coaches reading them — published either way. Matthew weighed 327.3 lb on Sunday, September 6, the day it began. Day 30 is Monday, October 5." — "Data through Saturday, September 26 · the coaches' checked calls so far, by the site's scorekeeper: 18 of 37 right · next write-up Wednesday, September 30".

**Order rule — passes.** Human (frame, number, the strip, "In his words") → counted failures ("the scale was skipped on 8 of the 21 days", "170 g protein floor was cleared on 7 of those 20 days", "Steps are the weak spot", "468 asks expired", two scorekeepers that disagree, "What he skips, counted") → mechanism ("How it works", the repo) → coaches last, in a five-row table, one line each.

**Lint — clean on the reader side.** No cycle/reset/attempt/seventeenth, no ISO date, no `n=`, no EWMA, no snake_case, no "gates", no "DUE"; "Graded by code" ×3, "scorekeeper(s)" ×3 (house jargon a mother meets in the fold, as in R5). Dates all in words.

**Trace — 66 `data-src`s, every one resolved in `b2/`:** 313.8 · 2026-09-26 · 13.5 · 21 · 327.3 · 13 · 4.36→4.4 with CI −4.74/−2.75 → "(2.8 to 4.7)" (labels map correctly to `ci_high`/`ci_low`) · 315.0→313.8 · 18/37 · Sep 30 · Sep 6→12 gap and 8 of 21 (from `weight_progress` + `weighin_span_days 20`) · `decisions[5].note` (note_at 03:31Z = **8:31 pm PT Sep 6**, the true earliest) and `decisions[0]` (Sep 23 8:10 pm) · journal gap 17 · 8.6 h (`eightsleep.total_sleep_hours` 8.6 = `whoop.total_sleep_hours` 8.6 — "the wrist strap and the bed sensor agree" is earned this time, `figure_scope.total_sleep_hours_source: eightsleep`) · 77 · 46.5 vs 41.0 · 20 days / 1,577 / 153 / 7 · deficit refused (`avg_deficit_published false`) · 72-min walk, 60-min treadmill 3.1 mi, 15 min stretching · rest day · 2,245 · Webb 0/5 vs 20/25 (`wrong.by_coach.nutrition confirmed 20 refuted 5`) · Brandt 3/4 vs 3/24 (`explorer confirmed 3 refuted 21`) · 468/49/37 · CGM 30 / BP 17 / SoM 18 / Garmin 103 · 13/11/1/1 · 8 · $102.74 · 1 · Sep 27 earliest due · both docket rows (sides: `nutrition_coach: true` → "Dr. Marcus Webb says … under 70"; `sleep_coach: true` → Park says 80 or better) · Sep 27 = `last_weighin_date + 1`.
**Served but carrying no `data-src`:** "19 lifting sessions" (`training.strength_sessions_30d` 19, line 277), "14 walks" (`walking.total_walks_30d`, 278), "170 g" (`protein_floor_g`, 265), "averaged over 20 days" (`avg_daily_steps_n`, 302), "21-day average" (`hrv_avg_window_days`, 242). **Mislabelled:** every `nutrition.*` data-src names `/api/nutrition` (which serves `{"error":…}` in the corpus); the page fetches `/api/nutrition_overview`. **Not a field:** the 30 in "Day 30 is Monday, October 5" and "+ 29 days" is `HORIZON = 30` in JS.

**1280:** top bar, masthead with THE CODE at the right edge, column 300–980 px with the margin dates ("26 SEP Saturday", "6 SEP to today"), strip with its ember last dot, right third empty as in C. Holds.

**JS off:** eight "Loading the numbers — this line fills from the site's served data." lines plus the `<noscript>` sentence; no number in the static HTML. Honest. **Degraded (journey/calibration/sleep 404):** "The latest weigh-in is not served right now." / "The lead is not served right now." / "no checked coach call is served yet" / "Friday night's sleep is not served." — absence as absence, and the strip still draws from `weight_progress`. Right.

**The twenty-week test — one frame-breaker:** "the next weigh-in is due Sunday, September 27" is `last_weighin_date + 1`. On a week he skips the scale the Follow line and "What resolves next" print a **past** date as "next … due" — worse than C's "tomorrow". "This week: no weigh-in since the last write-up; the latest is X on <day>" (line 94) is the right shape and exists one line up.

**What the readers lost to the ruling:** r/loseit's favourite sentence ("Sixteen quit starts, said out loud") and the mother's "That's him" line — the 9:02 pm "I am 320+lb…" note lost not to the ruling but to the sort: both day-1 notes are the same evening (8:31 and 9:02 pm) and the page prints only the first. The "runway before work starts" note is fine; the 320-lb line was better.

---

## The coaches — 28/50 (down from C's 34)

**Ten seconds (390 fold):** "The coaches · The witnesses, on the record. · Eight AI characters — software, not people — … Data through Saturday, September 26." — "TODAY'S READ · Dr. Lisa Park · sleep · written Friday, September 25, at one minute past ten in the morning, Pacific time" — "**No checked call yet.**" — "**The last six checked calls, newest first — two right, four wrong:**" — "right · For Saturday, September 12, Park said the night's recovery would land near 52.9, give or take 18.6 — it came in at 59."

*Every persona trips on the same two lines: "No checked call yet." directly above six checked calls.* `readHTML` prints the null branch when `profile.latest_checked` is **absent** (the corpus predates #4230) exactly as it would for `null`; the PR calls this "the null branch … honestly". It is not honest: the page contradicts itself in its first screen, and it will do so live until #4230's site-api is deployed, and again for any coach whose profile drops the key.

**Then, still on the main screen, in the serif quote style:** "On the night of 2026-09-23, Whoop logged 86% recovery, HRV at 48.2 ms, resting heart rate at 54 bpm, deep sleep at 30.6%, and REM at 25.9% — strong readings on their surface. But I cannot validate…" — an ISO date, a brand, five percentages, cut mid-sentence. **Lint FAILS here** (the only failure across the three pages). The source is `coaching-dashboard.coaches[].position_summary`, pre-#4225; the PR says the live slot is guarded on main. Inference, not verified: #4225 guards *register* (second person, vocative), not machine words — the page has no client-side check, so whatever the guard passes prints in the reader's face.

**Then a debug line:** "chosen: the best checked record since Day 1 — 7 of 17 held up." — lowercase, muted, `pick.reason` printed raw; "7 of 17" is `calibration.coaches[sleep] confirmed 7 / n 17` (traced) with no `data-src`.

**The ask thread — R5 §2 LANDED, R5 §4 NOT:** "On **14** of nineteen mornings since Sunday, September 6, by a keyword count of the mornings (a summary that mentions the morning and a rating, note, log, word, check or how he felt), Park has asked him for the same thing." — the count is now a named rule over `recent_outputs` (19 rows; my own pass agrees at 14) and carries `data-src="… recent_outputs (count)"`. The rule's parenthetical is the page explaining its regex to a mother. Then: "Nothing has come back yet." — **rendered in red** (`.v7c-thread .v7c-late { color: var(--alert); font-weight: 600 }`). R5 §4: "it must not wear the margin red … print it in ink." C's "and there is no channel yet to receive one" is gone too, so the red now reads purely as a scold.

**Where two disagree — R5's #1 fix LANDED, and its class came back one row up.** "Says yes." / "Says no — named, not quoted: a blood-sugar sensor is not worn." / the readings "98 · 90 · 78 · 80 · 86 · 99 · 77 — the last seven nightly recovery readings, September 19 to September 26; the average over twenty-one nights is 73.9" / "Code, on Wednesday, September 30: the night's recovery under 70 and Dr. Marcus Webb wins." — every value traced (`sleep_trend` last seven, `avg_recovery_window 73.9`, `avg_window_days 21`; sides map to the right names; Patel is dark via `cgm.dark true` and her claim never reaches the DOM). The served claims are under "+ What each wrote, as served". **But THE QUESTION row prints the raw `topic`:** "Carb reduction recommendation: will it degrade recovery or improve glucose dynamics?" and "Recovery rebound interpretation: mean reversion vs. corrective action" — the same LLM register R5 sent under a `<details>`, now in the table header position. C wrote the question by hand ("Was the jump from a 24 recovery … real repair, or a bounce back to his normal?"); the built page has no hand and no substitute. The criterion fields are already in `docketRow` — the question can be built from them in words.

**The record:** "18 of 37 checked calls right so far; 31 of 84 all time" — traced. The per-coach paragraph verbatim from C. "The rest of the staff (7)" one tap down; roster rows carry `calibration.coaches[…]` data-srcs.

**1280:** the "Today's read" column runs 1,696 px before the docket; the layout holds, right third empty.

**JS off — FAILS.** The static HTML says "No read is served today." / "No open disagreement on the record." / "No checked call yet." — three false facts asserted by the shell, with no `<noscript>` and no "loading" line (Home has both). **Degraded (dashboard/docket/calibration 404):** the same three sentences print on a fetch failure — "No open disagreement on the record." is a claim about the record, made because a request failed. Home's "is not served right now" is the honest shape; this page conflates *empty* with *unreachable*.

**Lost from C:** the second coach (Reyes: "Of the 36 asks he has made of Matthew, 8 were kept and 3 broken — the only coach with a 'broken' on his ledger") — the page is one coach by design; fine. The Brier gloss ("0.25 is what a coin flip scores") — gone with the frozen records; fine.

---

## This week — 34/50 (holds C within a point)

**Ten seconds:** "This week · The write-up of the week, with the page before and the page after. · Data through Saturday, September 26." — "22 SEP · THE LATEST WRITE-UP · Tuesday, September 22 · week 3 · 1,114 words · The Silence and the Signal · Drafted by the site's AI writer; Matthew reads each draft before it publishes. The number that week: 315.0 lb." — the opening lines — "Opening lines, as served. Read the full piece (1,114 words) →".

Near-verbatim C. **Trace — 30 `data-src`s, all resolved:** posts[0..2] date/label/word_count/title/stats_line (315.0 parsed from "Weight: 315.0 lbs"; 318.9; 327.3) · the prologue (3) = the three week-0 posts · "313.8 lb on Saturday, September 26, from 315.0 on Tuesday, September 22" (`weight_progress`) · "9 workouts and 1,055 minutes this calendar week" (`weekly_trend[2026-W39]`) · "recovery ran 86, 99 and 77" (`sleep_trend` Sep 24–26) · "nothing in the journal for 17 days" · "None on file. The site has put 3 weekly notes to him (Week 1 to Week 3); he has not answered one yet." (`field_notes.entries[].week_label`, all `has_matthew_response false`) · Sep 30 (`content_cadence`) · "the Dr. Amara Patel–Dr. Marcus Webb bet settles by code on Wednesday, September 30" (`docket.open[0]`) · Sep 27 = `last_weighin_date + 1` (the same past-date hazard as Home). The panel line is absent because the harness does not serve `/panelcast/episodes.json` — the honest-absent branch, as the PR says.

**Lint — clean.** "The Fifteenth Reset" and "Engine session" are served content, printed verbatim; the page's own copy has no ruled word.

**Order:** the write-up (an AI's words, labelled so) → previously → the week in numbers → his testimony (honest-empty, in ink, on the human) → next. The human is a "None on file" — that is the truth of the corpus, not the page's fault.

**JS off:** five "Not loaded yet." — honest, says nothing (41 words; no `<noscript>`). **Degraded (posts.json 404):** "No write-up has been published yet." / "Nothing before this one yet." — a 404 printed as a publishing fact; same class as the coaches page.

**1280:** holds; the column at 295–985 px, "Read the full piece" in ember.

---

## R5's three fixes — did they land?

1. **Plain-words rule on the docket claims — LANDED** (claims under `<details>`, "Says yes/no", the engine's number between them). The `topic` row is the same class, un-fixed.
2. **No bold number without a field — LANDED.** "14 of nineteen" is a rule over a served list with a `data-src`; the lead sentence reads `journey.{day_n,start_weight_lbs,started_date}`; "settled on August 10", "four silent days" and "the next weigh-in is tomorrow" are gone or served. Residue: five Home figures and "7 of 17" traced but untagged.
3. **The fold's this-week line + empty states — LANDED** ("This week: 315.0 → 313.8 lb since Tuesday's write-up"; "Nothing is on the docket and no graded call is due." exists at line 431).
R5's minor §4 (the red on "None has come back") — **NOT landed**; it is now "Nothing has come back yet." in `--alert`.

---

## The top five fixes, in priority order

1. **The coaches — `site/assets/js/v7_coaches.js` `readHTML`:** never print "No checked call yet." above a non-empty `recent` list. Print it only when `profile.latest_checked === null` **and** `recent.length === 0`; when the key is absent, print nothing (the ledger list stands in). Same file/page, the static shell (`scripts/v7/coaches.py` → `site/next/coaching/index.html`): replace "No read is served today." / "No open disagreement on the record." / "No checked call yet." with Home's "Loading the numbers — this line fills from the site's served data." + a `<noscript>`; in `run()`, print the fact-sentence only for a served empty list and "… is not served right now." for a null fetch. (Apply the same split to `v7_week.js` `renderLatest`/`renderPreviously`: "No write-up has been published yet." must not print on a 404.)
2. **The coaches — the raw model text on the main screen.** (a) `docketRow`: build THE QUESTION from the criterion, not `item.topic` — "Will the night's recovery read under 70 on Wednesday, September 30?" / "Will the seven-night average recovery be 80 or better on Wednesday, October 7?" — `metricWords`, `conditionWords`, `threshold`, `resolution_date` are all already in hand; keep `topic` under "What each wrote, as served". (b) `readHTML`: run `position_summary` through a client-side lint (ISO date `\d{4}-\d{2}-\d{2}`, `%`, `Whoop|Eight Sleep|Hevy|Garmin`, `night of`) before it prints; on a hit, fold it under the same `<details>` as `daily` and print "No public read is served for today." in its place.
3. **The coaches — `site/assets/css/v7_coaches.css` line 119:** `.v7c-thread .v7c-late { color: var(--alert); font-weight: 600 }` → ink (`--ink-muted`, no weight). Restore C's clause: "Nothing has come back yet — there is no channel yet to receive one." And `readHTML`: drop `pick.reason` ("chosen: …") or print it as a sentence with a `data-src="api_calibration.coaches[sleep].{confirmed,n}"`: "Park is here today because hers is the best checked record so far: 7 of 17 held up."
4. **Home + This week — the past-date "next weigh-in".** `v7_home.js` lines 431 and 447, `v7_week.js` `renderNext`: when `last_weighin_date + 1` is before the data-through day, print "no weigh-in since <day> — N days" instead of "the next weigh-in is due <past day>".
5. **Home — tag and relabel.** Wrap "19 lifting sessions" (`training.strength_sessions_30d`), "14 walks" (`walking.total_walks_30d`), "170 g" (`nutrition_overview.nutrition.protein_floor_g`), "averaged over 20 days" (`walking.avg_daily_steps_n`), "21-day average" (`vitals.hrv_avg_window_days`) in `data-src` spans; rename every `nutrition.*` data-src to `nutrition_overview.nutrition.*`. And in `wordsBlock`, print both notes of the first evening (`decisions[5]` 8:31 pm and `decisions[4]` 9:02 pm — "I am 320+lb …") before the latest, so the page's best human line survives the sort.

## Verdict

**Ship Home and This week to `/next/` as they are; hold The coaches for fixes 1–3 first** (the self-contradicting first screen, the raw model text in the table and the quote, the red). Fixes 4–5 can follow in the group's next pass.
