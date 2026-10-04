# R7 — The same five readers, all nine pages on `/next/`

**Written:** 2026-10-03 17:15–18:00 PT. Read-only; no site file changed.
**Model:** Claude Fable 5.1 (`claude-fable-5-1`) — the same family as R2, R4, R5 and R6.
**Build shot:** live `https://averagejoematt.com/next/` at main `83f3bd53e` (site-deploy green 2026-10-03 05:16Z), captured 2026-10-04 00:16–00:19Z.
**Method:** R6's, against the live preview instead of a harness. Playwright (Chromium, `service_workers="block"`, `networkidle` + 1.5 s) at 390×844 and 1280×800 on the nine pages; fold text from text-node rects above the fold; an inventory of every `[data-src]`; `scrollWidth`; page and console errors; every `/api/*` and data-JSON body the page fetched, saved, and each figure quoted below checked against those bodies by hand; a JS-off render (`java_script_enabled=False`); a degraded render (every `/api/*`, `journal/posts.json`, `panelcast/*` and `public_stats.json` answered 404); `tests/vendor/axe.min.js` injected, serious + critical counted at both widths; a vocabulary grep (cycle, reset, attempt, restart, the ordinals) over the full rendered text. Quotes are verbatim from the rendered page.

**Measured (390, JS on):**

| page | height | words | `data-src` | page errors | failed requests | overflow | axe serious + critical (390 / 1280) |
|---|---|---|---|---|---|---|---|
| Home `/next/` | 4,465 px (5.3 screens) | 818 | 90 | 0 | 0 | none | 0 / 0 |
| Today `/next/cockpit/` | 2,207 px (2.6) | 262 | 39 | 0 | 0 | none | 0 / 0 |
| This week `/next/story/` | 2,042 px (2.4) | 269 | 26 | 0 | 0 | none | 0 / 0 |
| His numbers `/next/data/` | 4,298 px (5.1) | 506 | 52 | 0 | 0 | none | 0 / 0 |
| The coaches `/next/coaching/` | 3,865 px (4.6) | 573 | 34 | 0 | 0 | none | 0 / 0 |
| What he's trying `/next/protocols/` | 8,154 px (9.7) | 1,265 | 132 | 0 | 0 | none | 0 / 0 |
| Who he is `/next/story/about/` | 2,510 px (3.0) | 339 | 29 | 0 | 0 | none | 0 / 0 |
| Under the hood `/next/method/` | 4,084 px (4.8) | 603 | 154 | 0 | 0 | none | 0 / 0 |
| Follow `/next/subscribe/` | 1,576 px (1.9) | 115 | 7 | 0 | 0 | none | 0 / 0 |

Vocabulary grep: **zero hits on all nine pages** (the owner ruling of 2026-09-26 holds; the published titles are now "The Body Answers Back", "Storming Mode", "Nine Days and No Rest" — the reset-count title #4330 asked about is gone from the page). All 18 internal links the nine pages carry return 200; none points at `/legacy`.

---

## Verdict

**Not ready to cut over on the stated bar; close.** Three of the five criteria R7 can measure are met: the personas (each ≥ 7, two of them at exactly 7), axe (0 serious, 0 critical, nine pages, both widths) and the ten-second test (the photo is there now). The A-grade sweep is **unmet: 2 A, 5 B, 2 C**. The comprehension judge and the gate rehearsal are **unmeasured** here — they need the cut-over branch and belong to the scorecard issue.

What stands between the preview and A is small and specific: ten fixes, all in the page scripts, none needing an engine change. Six of them are sentences that are false or self-contradicting on the day they were shot; those are the ones a Reddit or HN reader would quote back.

| cut-over criterion | R7 |
|---|---|
| A on all nine, the sweep rubric | **unmet** — Today and Who he is grade A; Home, This week, What he's trying, Under the hood, Follow grade B; His numbers and The coaches grade C |
| the five personas ≥ 7 | **met** — 8 · 7 · 7 · 7 · 7 (R2 live was 3 · 5 · 4 · 4 · 4) |
| axe serious = 0 | **met** — 0 serious, 0 critical, nine pages × two widths |
| the comprehension judge ≥ 2 on every door | **unmeasured** — needs the new manifest intents on the cut-over branch; budget tier read 0 at 00:10Z, so the judge will run |
| the ten-second test with a real photo | **met** — the day-1 photograph, dated, beside 311.0 lb with its day, its range and the premise |
| the rehearsal (`QA_SITE_URL=…/next`) | **unmeasured** — the scorecard issue's step |
| vocabulary (owner ruling) | **met** — zero hits |

---

## Scores (would I open it again)

| persona | Home | Today | This week | His numbers | The coaches | Trying | Who | Hood | Follow | **the site** |
|---|---|---|---|---|---|---|---|---|---|---|
| r/loseit | 9 | 7 | 7 | 7 | 6 | 6 | 8 | 5 | 7 | **8** |
| r/QuantifiedSelf | 7 | 7 | 7 | 8 | 6 | 7 | 6 | 7 | 7 | **7** |
| Hacker News | 8 | 7 | 7 | 7 | 7 | 6 | 7 | 8 | 7 | **7** |
| his mother | 8 | 6 | 7 | 6 | 6 | 5 | 9 | 4 | 7 | **7** |
| Matthew, Tuesday | 7 | 8 | 6 | 7 | 6 | 6 | 6 | 6 | 6 | **7** |
| **page total** | 39 | 35 | 34 | 35 | 31 | 30 | 36 | 30 | 34 | **36** |

R6's three, for comparison: Home 36 → **39**, The coaches 28 → **31**, This week 34 → **34**.

What moved each reader:
- **r/loseit (8).** The fold is the thing they came for: a real photograph, 311.0 lb, "Down 16.3 lb in 28 days, from 327.3", and then the failures counted without flinching — "The 170 g protein floor was cleared on 7 of those 26 days." The two day-1 notes are both printed now.
- **r/QuantifiedSelf (7).** CSVs exist on every block of His numbers; two sleep instruments are shown side by side. Held at 7 by three counts that do not agree with each other (fix 6) and a steps claim the page itself refutes (fix 3).
- **Hacker News (7).** The code link, the cost line and the corrections column are the draw. Held at 7 by the corrections column's second row — "total protein would come in at 46.0 g give or take 73.1" — which reads as a broken model, not an honest miss (fix 8), and by raw metric names in the docket (fix 2).
- **His mother (7).** Who he is carries it (9): the photographs and his own paragraph. The coaches still says "Dr." five times on its first screen; Under the hood is not for her and does not need to be.
- **Matthew, Tuesday (7).** Today is a real screen now: the session "as it will be lifted" with loads, the one ask with its due day, last night. It is the first prototype of that page to score above the frame alone.

---

## The A-grade table

Rubric: the eight items in `BUILD_WEEK_BRIEF.md` §4 row 1. A = 8 of 8, B = one miss, C = two or more.

| page | grade | the losing sentence |
|---|---|---|
| Home | **B** | item 5 — "Sun Sep 27 · The next graded call of any kind comes due." printed on October 3, under a "27 SEP" margin date: a past day offered as the next thing to come back for. |
| Today | **A** | — |
| This week | **B** | item 7 — the opening lines print their markdown: "\*He has trained every day for 23 days straight … the coming week.\*…" with literal asterisks, in the fold. |
| His numbers | **C** | item 4 — "The engine dates the goal Wednesday, June 9." with no year (the served date is 2027-06-09; read cold in October it is a day that has passed). Item 5 — the page ends on a folded "The engine's score" with no next step and no dated return. |
| The coaches | **C** | item 3 — "lead · written Saturday…" and "Dr. Eli Marsh" in the fold, and below it "Will total protein g 7day avg be 190 or better on Monday, October 12?" Item 4 — the read's last sentence in the fold column: "He weighs 311.0 pounds as of Friday, October 2." |
| What he's trying | **B** | item 6 — the note "I am 320+lb and have not worked out consistently…" is dated "Tuesday, September 8" here and "Sunday, September 6, 9:02 pm" on Home: one served record, two days. |
| Who he is | **A** | — |
| Under the hood | **B** | item 2 — the fold is one undated paragraph ("13 devices and apps are wired in … 11 reported this week"); the margin carries "§", and the first date is a screen down. |
| Follow | **B** | item 2 — "One subscriber so far." carries no day; the dated lines ("The next write-up is drafted Wednesday, October 7…") start below the fold. |

---

## Trace — what was checked against the served bodies

**Resolved, exactly:** 311.0 lb · Saturday, October 3 · 16.3 · 327.3 · 20 weigh-ins · day 28 (`journey.{current_weight_lbs,last_weighin_date,lost_lbs,start_weight_lbs,weighin_count,day_n}`) · "about 3.5 lb a week (2.5 to 3.8)" (`weekly_rate_lbs −3.54`, CI −3.81 / −2.49) · 312.3 → 311.0 since Tuesday (`weight_progress` 09-29, 10-03) · "41 of 96" and "50 of 135 all time" (`predictions.overall.{confirmed,decided}`, `.lifetime`) · 8.9 h bed sensor / 8.8 h wrist strap, recovery 98, HRV 58.0, 28-day recovery average 74.1 (`sleep_detail`) · 1,537 calories, 147 g, 7 of 26 days · 25 strength sessions, 18 walks, 43 workouts, 896 minutes over 6 workouts this calendar week (`training_overview`) · the 241-minute, 12.0-mile walk (`cardio_sessions[0]`, Strava) · the recovery series 89 · 64 · 54 · 59 · 62 · 98 · 98 · $59.70 (`receipts.month_to_date_usd`) · the two day-1 notes at 8:31 pm and 9:02 pm PT (`decisions[5,4].note_at`) · the three weekly notes unanswered (`field_notes.entries[].has_matthew_response` all false) · Eli Marsh's "No checked call yet." (`latest_checked: null`, zero rows in `track_record.recent` — the honest branch this time, not R6's absent-key case).

**Where the page and the body part ways:**
1. **"Sun Sep 27 — the next graded call"** is `predictions.overall.due.earliest_due` = 2026-09-27 with `due_now: 2` — two calls are *overdue*, and the page calls the oldest one "next".
2. **"Steps are the weak spot: 3,450 a day"** — `walking.daily_steps_trend` reads 9,913 steps on October 3, the day of the 12.0-mile walk two lines above it, and 1,113–1,561 on days with a logged training session. Inference, not verified: a 12-mile walk is on the order of 24,000 steps, so the step series is a phone that is not always on him, not a behaviour. The page turns an instrument gap into a verdict about the man.
3. **"Saturday: a 241-minute walk (12.0 miles). Saturday: rest day."** — both true (no lifting), read together as a contradiction.
4. **Three day counts for one span.** Home and Who: "20 weigh-ins in 28 days" (`day_n`). His numbers: "20 weigh-ins in 27 days" (`weighin_span_days`). His numbers again: "Trained on 28 of 29 days since September 6" — `daily_modality_minutes_30d` has 29 rows because its first row is September 5, the day before the start.
5. **One note, two days** — `decisions[4]` has `date` 2026-09-08 and `note_at` 2026-09-07T04:02Z (September 6, 9:02 pm PT). Home prints the instant; What he's trying prints `date`.
6. **The read against the engine, same screen.** Marsh: "a weekly loss rate of 3.6 pounds per week, likely between 2.5 and 3.9"; the engine, on Home and Today: 3.5, 2.5 to 3.8. The served text is not the page's to rewrite; it is the generator's to get right, and it is the class `qa-smoke`'s coach-versus-engine leg exists for.
7. **"Will total protein g 7day avg be 190 or better"** — `metricWords` has no entry for `total_protein_g_7day_avg` or `deep_pct_7day_avg`, so the question row prints the field name with its underscores opened. The 190 itself is the profile's stale target, not the plan's 170 g floor (tracked separately as the plan-targets issue).
8. **Sleep, one night, two figures across pages** — Home: "8.9 hours — the wrist strap and the bed sensor agree"; Today: "8.8 h asleep"; His numbers shows both and says so. His numbers is right; the other two each pick one.

---

## JS off and degraded

**JS off — honest on all nine.** Home, Today, This week, The coaches and Under the hood carry a `<noscript>` sentence and name what each entry holds ("This entry holds the latest weigh-in and the weekly rate."). The coaches' three false static facts from R6 are gone ("This page pours its numbers with JavaScript; with it off, nothing here is a claim."). His numbers, What he's trying, Who he is and Follow print "Not loaded yet." with no `<noscript>` — honest, and mute.

**Degraded — R6's class is fixed where R6 named it, and still open one row along.** Fixed: The coaches ("The coaches' reads are not served right now." / "The docket is not served right now."), This week's write-up rows, Today (every row), Under the hood, Follow. Still printing a failed fetch as a fact about him or the record:
- Home: "No notes of his are on file." · "Nothing else is on the record yet."
- This week: "No notes have been put to him yet." · "Nothing is scheduled." · "Nothing served for this week yet."
- What he's trying: "Nothing is scheduled."
- His numbers: "Journal — not in today's payload." (five rows; also a builder word)

---

## The top ten fixes, in priority order

1. **Home — `site/assets/js/v7_home.js:436`.** "The next graded call of any kind comes due." must not print a past day. When `earliest_due` is before the data-through day: "Two graded calls are overdue — the oldest was due Sunday, September 27." (`due_now`, `earliest_due`), sorted to the top without a future-looking margin date.
2. **The coaches + Home — `site/assets/js/v7_coaches.js:80-99` (`METRIC_WORDS`) and `v7_home.js:447`.** Add `total_protein_g_7day_avg` ("the seven-day average protein, in grams"), `deep_pct_7day_avg` ("the seven-night average share of deep sleep") and the other `_7day_avg` forms by rule, not by row; a test that every metric in a served docket fixture has words. On Home, a docket row without a criterion prints the model's topic — "disagree on fuel-cognition link mechanistic validity" — build it from the criterion or print only "disagree; graded by code".
3. **Home — `v7_home.js:323`.** Drop "Steps are the weak spot". Print the count as an instrument reading: "His phone counted 3,450 steps a day over 27 days — it is not always on him: Saturday's 12.0-mile walk shows as 9,913." or omit the steps sentence until the series is trustworthy. Same paragraph: "Saturday: rest day" → "no lifting Saturday".
4. **This week — `site/assets/js/v7_week.js:51` (`openingLines`).** Strip markdown emphasis from the excerpt (`*…*`, `_…_`) before printing; the dek is served in italics markup and the page prints the asterisks.
5. **Home + His numbers — `v7_home.js:189`, `site/assets/js/v7_numbers.js:78`.** "The served date to goal is Wednesday, June 9." / "The engine dates the goal Wednesday, June 9." → a year and a range, in reader words: "At this rate the goal lands around June 2027 — between May and September 2027." (`projected_goal_date`, `_earliest`, `_latest`).
6. **His numbers — `v7_numbers.js:134` and the weight sentence.** One day count: filter `daily_modality_minutes_30d` to `started_date` onward (28 of 28, not 28 of 29) and say "20 weigh-ins in 28 days" as Home and Who do, or name the span ("across a 27-day span").
7. **What he's trying — `site/assets/js/v7_tries.js:160`.** Date each call from `note_at` in Pacific time, as Home does; fall back to `date` only when `note_at` is absent.
8. **Under the hood — `site/assets/js/v7_hood.js:237` and the call template.** "What we changed." prints how the call was graded, not a change — label it "How it was graded." A band wider than its value ("46.0 g give or take 73.1") needs a gloss or the row leads with the measured side: "He ate 166 g of protein on October 1; Webb's call was 46 g, with a band so wide it would have counted almost any day — it still missed." "deep" → "the share of deep sleep" through the same `metricWords`.
9. **Home, This week, What he's trying, His numbers — the degraded rows listed above** (`v7_home.js:201,372`, `v7_week.js:122,297`, `v7_tries.js:287`, `v7_numbers.js:205-218`): split a null fetch ("… is not served right now.") from a served empty list, as The coaches and Today now do. Add the `<noscript>` sentence to the four pages without one.
10. **Chrome and the last rows.** His numbers ends without a next step — add the same "Next" entry the other pages carry (next weigh-in, next write-up). Under the hood and Follow: put one dated served fact in the fold (the data-through day beside the device count; the next write-up's day beside the subscriber count). Home and Today: one sleep sentence, both instruments, as His numbers has it. "Dr." on five pages is already ruled out and in flight as its own issue.

Not a page fix, and reported because the page prints it: "Running all of it has cost $59.70 so far in October" on the third day of the month (`receipts.projected_month_end_usd` 256.12 against a 215 ceiling).
