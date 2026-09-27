# R2 — The Reddit red team: five first visits to averagejoematt.com

**Written:** 2026-09-26 13:00–13:45 PT, against build `5cd8c63` (live 19:32Z). Read-only.
**Method:** the A-grade sweep's 25 phone screenshots + body text (`../grade/`), six laptop shots I took at 1280×800 (`home|cockpit|coaching|coaching_by-coach|story|data_1280.png` beside this file), Playwright measurements of page height, link count and image presence at 390 px, the live JSON in `../b2/` and the coach corpus in `../coachvoice/`. Every quote below is verbatim from the served page; the slug follows it.

**The numbers behind everything else (measured, 390 px):**

| page | height | screens (776 px fold) | words | photos of Matthew |
|---|---|---|---|---|
| `/` | 11,120 px | **14.3** | 1,422 | 0 (one lazy-loaded Pexels stock photo, duotoned) |
| `/cockpit/` | 8,252 px | 10.6 | 1,121 | 0 |
| `/coaching/` | 8,782 px | 11.3 | 1,723 | 0 (portraits = "commissioned illustrations of openly fictional AI personas") |
| `/data/` | 10,000 px | 12.9 | 1,707 | 0 ("A representative figure, not a photo") |
| `/story/` | 3,710 px | 4.8 | 409 | 0 |
| `/coaching/by-coach/` | 4,476 px | 5.8 | 680 | 0 |

There is **no photograph of Matthew anywhere on the 25 reachable pages** (`grep '<img\|<picture'` across `/`, `/story/`, `/story/about/`, `/cockpit/`, `/coaching/by-coach/` = 0 before JS; after JS the home page has exactly one `<img>`: `/assets/images/editorial/chronicle-week-06.jpg`, credited "PHOTO BY TANIKA PIETILÄ ON PEXELS"). The GitHub link exists on exactly one page (`/story/build/`), which is reachable only from the footer. The footer "FOLLOW" list carries seven social handles and no GitHub.

---

## 1. r/loseit — "Three weeks in, 14 lb down, and I let AI coaches run my life. Here's the data."

*She's 34, 60 lb down over two years, lurks daily, has seen a thousand "week 3" posts and knows which ones come back at week 12.*

**First 10 seconds (390 px, `/`):**
Serif headline, dark, monospace kicker: "A MEASURED LIFE · PROOF, NOT PROMISES" / "An honest documentary of an *ordinary* life, rebuilt with AI." Then the orange line: "down 13.5 lb in 21 days — the shape of it, every day, just below."

Inner monologue: *"Rebuilt with AI." Okay so it's a product. "Documentary" — where's the guy? 13.5 in 21 days at 300+ is water plus a real deficit, fine, that's normal for week 3. Where's the before photo. Where's what he eats. Why does this look like a fintech landing page.*

She scrolls once. "Is he okay this week?" and five pill chips: "EATING logged, but the engine scored it low" · "HEADSPACE nothing logged for 17 days". *"The engine scored it low" — what engine? Scored what low? He's eating badly or logging badly?* She does not know, and the page does not say.

**First tap:** THE NUMBERS (bottom bar) — because a loseit lurker wants the weight chart and the food, in that order. She lands on `/data/` with "Weight & composition" already open: "313.8 lb at Saturday's weigh-in — down 13.5 lb from 327.3 on Sunday Sep 6, 13 weigh-ins in 20 days." *That's a real sentence. 13 of 20 — he skips weigh-ins, he admits it. Good.* Then a full screen of "THE DAILY SIGNAL / WEIGH-INS — DAILY SCALE, ~5 DAYS/WK EXPECTED / The fluid layer — the numbers that move morning to morning" before the chart. Then "THE FIGURE, DRAWN FROM THE NUMBERS … A representative figure, not a photo. The silhouette's girth is a direct function of the real measured weight." She laughs out loud. *They built a CGI belly instead of taking a picture.*

**Second tap:** "Eating" (`/data/nutrition/`), 2 taps in. "The engine does not publish a deficit — its estimate exceeds what it will vouch for. Blood sugar — no sensor this cycle." *So the site won't tell me his calories. The cockpit said 182 g protein and "the 170 g floor was cleared on 7 of 20 logged days." Seven of twenty. That's the honest number and it's buried on a different page.*

**Taps to the thing she came for:** the number: 0. The chart: 1 tap + ~2 screens. What he eats (a day of food, a calorie number): **not on the site** — the nutrition page refuses to publish the deficit and there is no food log view. A photo of the man: **does not exist**.

**Where she bounces:** the "representative figure". She came for a human and got a parametric silhouette with a paragraph explaining why it is not a photo.

**The comment she posts (top comment, 340 upvotes):**
> Congrats on the 13.5, that's a normal and good week 3 at your size and I mean that. But OP, this site has eight AI doctors with headshots and zero pictures of you. It has a "representative figure, not a photo" that gets thinner as you lose weight. It has a page explaining why it won't tell me your calories. Every loseit success story that lasts has three things: a face, a plate, and a number you're embarrassed by. You've hidden all three behind a cockpit. Post the plate.

**Score, "would I follow this": 3/10.** She'd follow a person losing 130 lb. She was shown a dashboard.

**The one change:** A photo of Matthew — dated, unflattering, taken on Day 1 and every 30 days — in the hero, above the fold, before the word "AI". The silhouette becomes the overlay on the photo, not the substitute for it. Everything on r/loseit is a before picture with a promise attached; this site has the promise and refused the picture.

---

## 2. r/QuantifiedSelf — "I built a personal data platform: 100+ lambdas, 8 AI coaches, all public."

*Data engineer, ran her own Whoop→Postgres pipeline for three years, read Wolfram's 2012 personal-analytics post and Gary Wolf's early QS posts, has strong opinions about Whoop's "recovery" score being a black box.*

**First 10 seconds (390 px, `/`):**
"An honest documentary of an ordinary life, rebuilt with AI." *Lambdas, you said. Show me the pipeline.* Sees "DAY 21 · WEEK 3", the 13.5 lb line. Scrolls hard, looking for a chart or an architecture diagram. Passes "Is he okay this week?" (*not for me*), passes "How the pieces fit / reads / proposes / shifts / narrates / THE DATA THE COACHING THE PROTOCOLS THE STORY" (*a marketing diagram of the site's own nav*), reaches "THE SEVEN AREAS · MEASURED CO-MOVEMENT" — "85 Sleep · 55 Move · 2 Fuel · 59 Metab · 19 Mind · 50 People · 29 Hold". *Fuel is 2 out of 100? Hold? What is Hold?* Then the small caps: "NEWLY UNLOCKED THIS MONTH: HRV ↔ RECOVERY (R=0.89, N=89, POSITIVE · STRONG) — CORRELATION, NOT CAUSE; ANNOUNCED ONCE."

Inner monologue: *You "unlocked" the correlation between HRV and a score Whoop computes from HRV. r=0.89 is the vendor's formula leaking back out. That's the "insight" the home page leads with. Who is this for.*

**First tap:** she wants raw data and the architecture. Neither is in the bottom bar (TODAY · THE NUMBERS · THE COACHES · WHAT HE TRIES · THE STORY). She scrolls **14 screens** to the footer and finds "HOW IT'S BUILT: Under the hood · The build log · The gear · How the score works". Taps "Under the hood" → `/method/`, which opens on "The wrong page": "39 GRADED FAILURES · 2989 CLAIMS AUDITED · 6 CAUGHT WRONG" and then:

> REFUTED · 2026-09-26 · NUTRITION / We believed: recovery_score trend=up (slope=0.0778), predicted=down / The number that killed it: recovery score measured 0.08

*"Recovery score measured 0.08." That's the slope, not the score. The formatter is printing the wrong field on the site's own honesty page. And "DISPUTE DOCKET RESOLVED: TOTAL_CALORIES_KCAL_7DAY_AVG >= 2200 ON 2026-08-10" appears as a fresh refutation on 09-24, 09-25 and 09-26 — the same August event re-graded three days running.* She has now found two bugs on the page that exists to prove the machine grades itself honestly.

**Second tap:** footer → "The build log" (`/story/build/`): "Fork the architecture, not the data." *So the data is NOT downloadable. The one thing a QS person wants — the CSV — is the thing the tagline says you can't have.* But: "The stack manifest / what its fields mean / the source, in full" → `github.com/averagejoematt/life-platform`. **That's the first thing on the site she respects**, and it is 2 taps + 14 screens + a footer from the home page.

**Taps to the thing she came for:** architecture: 1 tap + 14 screens (footer-only). Raw data export: **does not exist** ("Fork the architecture, not the data"). GitHub: 2 taps + footer. Calibration numbers (she'd love these): the forecast block "RANGE HELD 79% OF 253 GRADED" is on `/cockpit/` 8 screens down; the scorecard "48.6% HIT RATE · 37 DECIDED" is 2 taps.

**Where she stays:** `/coaching/scorecard/` and `/story/attempts/`. "CAREER · EVERY CYCLE 36.9% HIT RATE · 84 DECIDED · 1028 STILL OPEN" and "468 EXPIRED WITH NO COACH FOLLOW-UP · 623 CARRY NO MACHINE-CHECKABLE ACTION" — *that's a real ledger, someone counted the embarrassing rows.* "Dr. Marcus Webb 0% · 0✓ · 5✗" — *the nutrition coach is 0 for 5 and they left it up.* And "Dr. Sarah Chen · 0 DECIDED" — *who? There are eight coaches on the team page and she isn't one of them. A ninth name leaking from an older config.*

**The comment she posts (top, 210 upvotes):**
> The scorecard and the 17-attempts page are the best self-tracking honesty I've seen on a personal site — a 0-for-5 coach and "none of 16 attempts reached day 30" left on the record. Everything else is in the way. Your home page's headline insight is that HRV correlates with Whoop recovery (r=0.89) — recovery is computed from HRV, that's the vendor's formula, not a finding. Your "wrong page" prints the slope as the measured value ("recovery score measured 0.08") and re-refutes an August docket three days in a row. There's no CSV, the repo link is in a footer under 14 screens of copy, and "Fork the architecture, not the data" is a strange flex for a site called proof-not-promises. Put the repo and a data download at the top, delete the "seven areas" bubbles, and lead with the scorecard.

**Score: 5/10.** Would star the repo. Would not bookmark the site.

**The one change:** A `/data/download/` (or a CSV link on every chart) plus the GitHub link in the header, not the footer. The QS reader's entire trust model is "can I check it"; the site currently says "trust our honesty page", and the honesty page has two visible bugs.

---

## 3. Hacker News — "Show HN: an open n=1 experiment where AI coaches argue over my wearables."

*Senior engineer, 20 years, has flagged three "I built an AI agent that…" posts this week, opens the link on a laptop with the console already open.*

**First 10 seconds (1280×800, `/`):**
Left-aligned serif: "An honest documentary of an *ordinary* life, rebuilt with AI." Sub: "One regular guy, the wearables he already owns, and a staff of AI coaches reading every number he produces — published either way, down weeks shown, not hidden."

Inner monologue: *"Rebuilt with AI." "Staff of AI coaches." "Honest documentary." Three trust-words in the first two lines and none of them is a fact. This is a Claude-written landing page. I'd bet money the whole site is.* Scrolls. "The measuring rule, bent into the loop the site runs on. Every station is a door you can walk through — and the cockpit is today's slice of all four at once." *A paragraph about the site's own metaphor, on the site. Slop tell #1: copy that describes its own navigation as if it were content.*

**First tap:** THE COACHES, because the post title promised arguing. `/coaching/` fold: "Eight AI characters, software not people, read his numbers every morning." then "Dr. Henning Brandt · RESEARCH & LONGEVITY — EVIDENCE APPRAISAL · WRITTEN SATURDAY 10:08 AM PT · CHOSEN: THE FRESHEST READ · Two contingent predictions are now live over the next 4–6 days. If the glucose coach recommends carb reduction and protein escalation follows, recovery holding above 81.6% EWMA tells us glucose…" — *a coach predicting what another coach will recommend. The AI is forecasting the AI.*

He scrolls to the argument: "Dr. Marcus Webb · the claim: Protein gap (141g vs 190g) is load-bearing structural deficit requiring immediate intervention" / "Dr. Max Reyes · the reply: You're right that the 49g gap … needs immediate attention. Where we differ: …" / "DR. MARCUS WEBB · the rejoinder: You're right that protein sits upstream of training stimulus utilization. But you've inverted the sequencing logic." *"You're right that… Where we differ." "You're right that… But you've inverted." Every LLM debate ever generated opens its turn by conceding the other's point. "Compliance theater." "Meal architecture." "Load-bearing structural deficit." This is two Claude calls talking to each other and the site's own caption admits it: "GENERATED IN EACH COACH'S OWN VOICE FROM THEIR RECORDED POSITIONS."* And the same 400-word exchange appears in full on `/cockpit/` too — he notices because he had it open in the other tab.

Then the docket: "GLUCOSE · SAYS IT WON'T · STAKE: BRIER 0.25 OVER 3 GRADED CALLS" / "RESOLVES BY CODE recovery_score < 70 · on 2026-09-30". *Okay. That's a real mechanism. A dated, deterministic resolution and a frozen Brier score as the stake. If the argument were one line each and the docket were the page, I'd read this.* Also notices: the glucose coach is staking calls on "CGM data" while `/data/nutrition/` says "Blood sugar — no sensor this cycle", and Dr. Amara Patel's own stance card reads "Data gate: awaiting synchronization · HELD SINCE SEP 23". *The glucose coach has no glucose and is still arguing about glucose.*

**Second tap:** he wants the code. Header: no GitHub. Footer: no GitHub in FOLLOW (Bluesky, X, Instagram, Reddit, YouTube, TikTok, Privacy). He finds it via footer "The build log" → "the source, in full" → `github.com/averagejoematt/life-platform`. Two taps and a 14-screen scroll to reach the only thing that would have made him upvote the Show HN.

**Taps to the thing he came for:** the argument: 1 tap, 3 screens. The code: 3 taps, footer-only. Proof it's not a wrapper: the build log ("The check existed, was green, and never reached the sentence it existed to stop", "Five instruments were green. None of them were measuring anything.") — that's the real engineering and it is the most-hidden page on the site (2,901 words, 0 taps from anywhere but the footer).

**The comment he posts (top, 180 points, the one everybody replies to):**
> The engineering underneath this is real — the build log reads like an honest postmortem feed, the dispute docket resolves by code on a date with a frozen Brier score as the stake, and there's a repo. None of that is on the front page. The front page is "An honest documentary of an ordinary life, rebuilt with AI" followed by 14 screens of Claude explaining the site's own navigation metaphor ("every station is a door you can walk through"). The coaches' "argument" is two LLM turns that each start with "You're right that…", and the glucose coach is arguing about glucose while the data page says there's no glucose sensor. Cut the eight doctors down to the docket, put the repo link in the header, and lead with the build log. Right now it looks like the thing it says it isn't.

**Score: 4/10** (would 8/10 the repo README; 2/10 the home page).

**The one change:** Kill the generated dialogue; keep the docket. One page: the open bets, the stake, the resolve-by-code date, the record. The argument the post title promised is a table, not a screenplay.

---

## 4. His mother / a close friend on the phone — link sent by text

*No health background. Wants one answer: is he okay. Has heard "AI coaches" and privately thinks that sounds lonely.*

**First 10 seconds (390 px, `/`):**
"A MEASURED LIFE · PROOF, NOT PROMISES". "An honest documentary of an ordinary life, rebuilt with AI." *Rebuilt? What was broken?* Scrolls one thumb: "FOR FAMILY & FRIENDS · THE SHORT VERSION — Is he okay this week?" — *oh, good, this is for me* — "The short version: he's down 13.5 lb since the start, and the day-to-day looks like this —" then five chips: "SLEEP on the up / TRAINING holding steady / EATING logged, but the engine scored it low / DAILY HABITS eased off a little / HEADSPACE nothing logged for 17 days".

Inner monologue: *Sleep good, exercise fine. "The engine scored it low" — is he not eating? "Headspace — nothing logged for 17 days" — he's stopped talking to it. That's the one I'd worry about and it's written like a battery indicator.* She wants to see his face and hear his voice. There is no face. The next thing is "A staff of AI coaches — software, not people — reads his numbers every morning and writes him notes."

**First tap:** "The story so far →" (the third of three orange links, because "story" is the only word she trusts). `/story/`: "An AI journalist writes up each week; Matthew writes in his own words." *An AI journalist.* The piece: "The Silence and the Signal — On Monday afternoon, Matthew logged what the platform's daily brief called the biggest training day of the experiment so far: a 130-minute Engine session followed immediately by a 104-minute walk" — *a 104-minute walk at his weight, is that safe?* — "BY ELENA VOSS, THE SITE'S AI JOURNALIST · PHOTO BY TANIKA PIETILÄ ON PEXELS". *A stock photo and a made-up reporter writing about my son in the third person.* Then, inside the piece: "The journal has gone quiet. The food log ran through Saturday and then stopped… the layer of the system that captures his inner weather … is dark. I can see the consequences of the weekend in the physiological data. I can't see the cause." She's now genuinely worried and the person telling her is a fictional character.

**Second tap:** "IN HIS OWN WORDS" — one entry, "The Org Chart of One Human and N Agents · JULY 8 · 80 DAYS AGO", opening: "At 07:45 every morning, an AI agent wakes up, reads my infrastructure's overnight alarms, diagnoses what broke…" *That's not him talking about how he is. That's him talking about servers, three months ago.* "WHO HE IS" is ~250 words, well-written, one line she'd hold on to: "not a challenge, not a 30-day hack, but a proper system", plus an email address. "THE PODCAST": "This week's episode is in final review — it'll drop here as soon as it clears the quality bar." Dated September 4. Three weeks ago.

**Taps to the thing she came for:** "is he okay": 0 taps, 1 scroll — the chips answer it, ambiguously. His voice: 2 taps to a 3-month-old essay about infrastructure. His face: **not on the site**. A way to reach him: the About page email (2 taps).

**Where she bounces:** the chronicle byline. She texts him instead of reading further: "Who is Elena Voss?"

**What she says on the phone (this is her comment):**
> It's very impressive, honey. I couldn't find a picture of you. There's a lady called Elena writing about you and a lot of doctors with drawings. It says you haven't written anything in 17 days and the eating thing said "low". Are you eating? Call me.

**Score: 4/10 as "would I open it again".** She'd open it again if it showed his face and had a line from him. It has neither.

**The one change:** Above the chips, one sentence in Matthew's own words, dated this week, and a photo. "Sep 24, Matthew: 'Rough weekend, didn't log, back on it Monday.'" Twelve words from him beat 1,114 from Elena Voss for this reader, every time.

---

## 5. Matthew himself — Tuesday, 6:40 AM, coffee, phone: "what do I do today, and is it working?"

**First 10 seconds (390 px, `/cockpit/`, because he knows to go there):**
Top: TODAY · WEEK · MONTH · JOURNEY segmented control. Then "THE COCKPIT · TODAY, IN ONE SCREEN" then "**New here?** This page is today, in one screen. Terms are explained where they appear. ×" (the × does persist — tested: `localStorage['ajm-cockpit-intro-v1']` survives a reload — so he sees it once per browser, not every morning; the point stands for the four rows around it), then the loop strip "TODAY · THE NUMBERS → THE COACHES → WHAT HE TRIES → THE STORY ↻", then finally "SATURDAY · DAY 21 · DATA THROUGH SEP 26". Four to five rows of chrome before the first fact, on the page he built to be one screen.

Then the good part: "How's the week? Down 13.5 lb since Sep 6, over 13 weigh-ins; 313.8 lb on Sep 26. The weekly rate is about −4.4 lb a week, but provisional…" / "Last night? 8.6 h asleep; recovery 77%; HRV 46.5 ms vs his 21-day average of 41 (n=21)." / "Today? Flex today — 4 exercises, 9 sets, already in Hevy. Protein on Sep 25: 182 g; the 170 g floor was cleared on 7 of 20 logged days."

Inner monologue: *This is it. Three questions, three answers. I could stop here.* Then: "The one ask: 'Start logging the daily 1-to-5 subjective feeling scale before checking the app' — Dr. Lisa Park, Sep 12, due Sep 19." *That was due a week ago. It's still "the one ask". Nobody — not the coach, not the page — has said "you missed this." It just sits there like a Jira ticket.* And "Today?" doesn't say **when** or **what weight** — "4 exercises, 9 sets" is a count, not a plan; he still has to open Hevy.

**First tap/scroll:** he scrolls for "is it working" and gets "THE DAILY LINE · YESTERDAY'S READ · FROM THE MORNING BRIEF: Recovery peaked at 99 and HRV hit 57ms — but only 1,565 steps and 13 missed habits signal the body is ready while the routine isn't." *That's the email I already got at 10 AM yesterday.* Then the full 400-word Webb/Reyes protein dialogue (the same one on `/coaching/`), then "WHERE THE TEAM STANDS" (seven one-liners: "Get enough hours, regularly." / "First, I just need to see what you eat." / "Felt-Sense Calibration Under Load" / "Data gate: awaiting synchronization"), then LAST NIGHT again as four gauges (recovery 77% · sleep 8.6 h — the same numbers as the "Last night?" paragraph three screens up), then THE LEVERS, THE INPUTS ("JOURNAL 17d"), THE FORECAST. Ten screens. The three-question block at the top was the whole answer and the page keeps going for 9 more screens of the same numbers restated.

**Taps to the thing he came for:** "what do I do today": 0 taps, but the answer is "4 exercises, 9 sets" — he must still open Hevy to know which. "Is it working": 0 taps — "provisional — three weeks is too few to trust it." *Honest, and also the answer every day for the next three weeks.* "What should I fix": the "one ask" is a week overdue and the page doesn't say so; "JOURNAL 17d" is the actual answer and it is a freshness chip 7 screens down.

**Where he bounces:** after the third paragraph. He goes to Hevy for the session. The morning-brief email already tells him the daily line. The site competes with his own email and loses, because the email has no chrome and no repeats.

**The comment he'd post (in the Telegram chat to the coaches):**
> The top of the cockpit is the only thing I read. Why is Lisa's ask from the 12th still "the one ask" on the 26th without anyone saying I blew it? Why does the same protein argument sit on this page and the coaching page? And why is "Today?" a set count instead of the actual session with the weights — I have to open Hevy anyway, so what is this page for.

**Score: 4/10 as "would I open this tomorrow".** He opens it because he built it. On merit the top 3 paragraphs are a 9 and the other nine screens are a 2.

**The one change:** Cut `/cockpit/` to the three questions + the session as it will be lifted (exercise · sets × reps · load, from the block calendar that already serves it — #4089/#4106) + one line that is allowed to say "overdue" or "missed": "Lisa's ask, due Sep 19 — 7 days late." Then stop. Everything else on the page is a link, not a section.

---

## Cross-cutting findings

### (a) What reads as AI slop vs. what reads as real

**Slop signals — the actual words:**

1. **Copy that describes the site instead of the man.** "The measuring rule, bent into the loop the site runs on. Every station is a door you can walk through — and the cockpit is today's slice of all four at once." (`/`) "That's the whole site — and every number lands in public." (`/`) "The weight figures lead the page now — the body-composition percentages move to the dated scan arc below." (`/data/`) — a changelog sentence left in the reader's page. "YOU ARE HERE ON THE LOOP" on every footer.
2. **Trust-words stacked in the hero.** "A MEASURED LIFE · PROOF, NOT PROMISES" / "An honest documentary of an ordinary life, rebuilt with AI." / "One regular guy" / "published either way, down weeks shown, not hidden" / "Not a guru. Not a lab." / "The anti-Blueprint." — six assertions of honesty before a single verifiable fact about the person. Honesty that announces itself is the loudest slop tell there is.
3. **The "Not X. That's Y." cadence, everywhere.** "Not a cool-down stroll. Sustained cardiovascular work." "That's not a good week. That's a body that has been doing serious work." "Not just recovered — it has arrived somewhere new." "This is worth naming honestly rather than papering over." (all `/story/`, Elena Voss). "Not a chatbot guessing; an engine reading one real life's data back to you." (`/`). "A snapshot, not a trend." "an instrument, not the finish line." "the honesty" — the em-dash-then-reversal is the house style, and it's the model's.
4. **LLMs debating LLMs.** "You're right that the 49g gap … Where we differ:" / "You're right that protein sits upstream … But you've inverted the sequencing logic." / "compliance theater" / "meal architecture" / "load-bearing structural deficit" (`/coaching/`, duplicated on `/cockpit/`). The caption confirms it: "GENERATED IN EACH COACH'S OWN VOICE FROM THEIR RECORDED POSITIONS."
5. **A coach forecasting a coach.** "If the glucose coach recommends carb reduction and protein escalation follows, recovery holding above 81.6% EWMA tells us glucose…" (`/coaching/`, TODAY'S READ). And a glucose coach with no glucose: Dr. Amara Patel "Data gate: awaiting synchronization · HELD SINCE SEP 23" beside `/data/nutrition/`'s "Blood sugar — no sensor this cycle."
6. **Machine output pasted onto a reader page.** "We believed: recovery_score trend=up (slope=0.0778), predicted=down / The number that killed it: recovery score measured 0.08" (`/method/`) — and the scorecard's `{"ACTUAL_VALUE": -0.01800574780380214, "REASON": "PREDICTED UP, METRIC FLAT …", "BEATS_NULL": FALSE, "BAYESIAN_UPDATE": "FAILURE", "ALGO_VERSION": "1.0"}` rendered as prose (`/coaching/scorecard/`).
7. **Fictional bylines with stock art.** "BY ELENA VOSS, THE SITE'S AI JOURNALIST · PHOTO BY TANIKA PIETILÄ ON PEXELS" (`/story/`); "COACH PORTRAITS ARE COMMISSIONED ILLUSTRATIONS OF OPENLY FICTIONAL AI PERSONAS" (`/coaching/*`, on four pages). A ninth coach who is on no roster: "Dr. Sarah Chen · 0 DECIDED" (`/coaching/scorecard/`).
8. **Unexplained scores with cute names.** "85 Sleep · 55 Move · 2 Fuel · 59 Metab · 19 Mind · 50 People · 29 Hold" (`/`); "29 consistency" (`/cockpit/`); "THE ENGINE'S WEEK SCORE 74" (`/story/`); "NEWLY UNLOCKED THIS MONTH: HRV ↔ RECOVERY (R=0.89, N=89)". Gamification vocabulary ("unlocked", "the stack", "levers", "milestone ladder … clicks ember") on a site that claims to be sceptical of optimisation culture.
9. **Widgets nobody asked for.** "TRY IT ON · YOUR ONE NUMBER — Where would you land?" and "Ask the data anything … Not a chatbot guessing" (`/`); "Did this page make sense? Yes / Partly / No / What were you looking for?" on all 25 pages.
10. **Staleness that pretends to be live.** "This week's episode is in final review — it'll drop here as soon as it clears the quality bar" (`/story/panel/`, since Sep 4); "The one ask … due Sep 19" shown as current on Sep 26 (`/cockpit/`, `/coaching/`); "In his own words" = one essay from July 8.

**Real signals — the actual words:**

1. "313.8 lb at Saturday's weigh-in — down 13.5 lb from 327.3 on Sunday Sep 6, 13 weigh-ins in 20 days." (`/data/`) — a number, a date, a denominator that admits skipped days.
2. "the 170 g floor was cleared on 7 of 20 logged days." (`/cockpit/`) — a failure rate stated as a fraction.
3. "The engine does not publish a deficit — its estimate exceeds what it will vouch for. Blood sugar — no sensor this cycle." (`/data/nutrition/`)
4. "17 starts, counted … NONE OF 16 ATTEMPTS REACHED [day 30] — NO ODDS SERVED" / "Attempt #14 · AUGUST 17 · SHOWED UP 2 OF 15 DAYS · collapsed on day 1" / "Attempt #8 · SHOWED UP 0 OF 1 DAY" (`/story/attempts/`). The single most credible page on the site.
5. "Dr. Marcus Webb 0% · 0✓ · 5✗" and "CAREER · EVERY CYCLE 36.9% HIT RATE · 84 DECIDED" / "468 EXPIRED WITH NO COACH FOLLOW-UP · 623 CARRY NO MACHINE-CHECKABLE ACTION" (`/coaching/scorecard/`).
6. "RESOLVES BY CODE recovery_score < 70 · on 2026-09-30 … EACH SIDE'S STAKE IS ITS OWN BRIER RECORD, FROZEN WHEN THE DOCKET OPENED." (`/coaching/`)
7. "THE FORECAST EXPECTS · RANGE HELD 79% OF 253 GRADED" (`/cockpit/`) — an 80 % interval that held 79 %. A QS reader will screenshot that.
8. "Matthew hasn't replied to this one yet — and that's allowed; the wall is honest both ways." (`/`) and "HEADSPACE nothing logged for 17 days."
9. "Last blood test: Friday Apr 3 — before this cycle. 152 markers; 26 outside their reference range. No next test scheduled." (`/data/labs/`); "Scanned Monday Mar 30 · ~180 days ago · pre-cut baseline … 42.7% body fat." (`/data/`)
10. "One subscriber so far." (`/subscribe/`) and "matt@averagejoematt.com" (`/story/about/`).
11. The build-log titles: "Five instruments were green. None of them were measuring anything." / "The check existed, was green, and never reached the sentence it existed to stop." (`/story/build/`) — the engineer's voice, hidden in the footer.

The pattern: **every real signal is a number with a denominator or a dated admission; every slop signal is an adjective, a metaphor, or a machine talking to a machine.** The site has both in roughly equal measure and leads with the wrong one on every door.

### (b) The credibility receipts a sceptic looks for

| receipt | exists? | where / what's there |
|---|---|---|
| A real photo of him | **No.** | Zero photos on 25 pages. "A representative figure, not a photo" (`/data/`); Pexels stock on the chronicle; illustrated AI doctors on `/coaching/`. |
| His own words, recent | **Barely.** | `/story/about/` ~250 words, undated; `/story/journal/` one essay, July 8, about infrastructure. Nothing from him this cycle. Wall replies: "Matthew hasn't replied to this one yet." |
| Admitted failures | **Yes — best in class, and buried.** | `/story/attempts/` (16 failed starts), `/coaching/scorecard/` (0-for-5 coach, 36.9 % career), `/method/` "the wrong page", "7 of 20 logged days", "nothing logged for 17 days". None of it is in a hero. |
| Methodology in one paragraph | **No.** | `/method/` opens on the obituary cards; "How the score works" is `/method/character/` (706 words on "pillars"). No single paragraph anywhere says: devices → Python computes → AI narrates → deterministic grader. The north-star doc has that paragraph; the site doesn't. |
| Dated numbers | **Yes, mostly.** | "313.8 lb on Sep 26", "DATA THROUGH SATURDAY SEP 26", "WRITTEN SATURDAY 10:08 AM PT". Broken by ISO leaks ("AS OF 2026-09-25", "2026-W38") and by stale-as-live ("due Sep 19", "in final review" since Sep 4). |
| A way to check | **Half.** | GitHub on one footer-only page; no data download ("Fork the architecture, not the data"); the honesty page has visible grading bugs (slope printed as value; August docket re-refuted 3 days running); `/api/*` JSON is live but unlinked. |
| Someone else vouching | **No.** | "One subscriber so far." No comments, no external quote, no r/ thread linked. |
| A price he's paying | **Partial.** | Supplement costs ("$12/mo") on `/protocols/`; platform cost "published as one machine-readable manifest" — a manifest, not a number on a page. |

### (c) The navigation math

- **Reachable pages:** 25 (sweep) + unlisted ones the home page still links (`/data/glucose/`, `/data/reading/`, `/data/vitals/`, `/data/autonomic/`, `/data/zone2/`). The home page alone links **25 distinct internal pages in its static HTML** (the sweep found two more injected by JS: `/data/glucose/`, `/data/reading/`).
- **Menus per page:** bottom bar (5) + the "loop strip" (5, repeated as text) + door sub-tabs (Coaching: 6 — THE READ / BY COACH / SCORECARD / THE TEAM / WHAT THE AI SAID, AND HOW IT FELT / ASK THE BOARD; Story: 4; Cockpit: 4 — TODAY / WEEK / MONTH / JOURNEY; Data: "ALL 14 TOPICS" dropdown; Method: "ALL 29 TOPICS") + footer (5 groups, ~25 pages, 9 follow links) + "YOU ARE HERE ON THE LOOP" (5 again) + "NEXT ON THE LOOP / OR COME BACK" + the feedback widget. **Four separate renderings of the same five-item nav on every page.**
- **Screens of scroll before value:** home 14.3 screens; the weight chart is ~10 screens down; the footer nav (the only route to the build/method/gear pages) is at the bottom of all 14.
- **Taps to the thing each persona came for:**

| persona | wanted | taps | verdict |
|---|---|---|---|
| r/loseit | his face + his plate | ∞ / ∞ | neither exists |
| r/loseit | weight chart | 1 + 2 screens | fine |
| r/QS | repo | 2 + footer (or 3) | hidden |
| r/QS | CSV | ∞ | doesn't exist |
| HN | the argument as a bet table | 1 + 3 screens | exists (docket), wrapped in a screenplay |
| HN | build log | 2 + footer | the best page, the most hidden |
| Mother | "is he okay" | 0 + 1 scroll | answered by five ambiguous chips |
| Mother | his voice this week | ∞ | July 8 |
| Matthew | today's session with loads | 0 tap + Hevy | set count only |
| Matthew | "what did I miss" | 7 screens (JOURNAL 17d) | the overdue ask isn't marked overdue |

### (d) The return trigger — what would bring each one back

- **r/loseit:** a dated photo every 30 days and a weekly weigh-in post in his words. Return cadence = Sunday. Today the only dated promise on the site is "NEXT WRITE-UP: WEDNESDAY, SEPTEMBER 30" — by an AI.
- **r/QS:** a new graded result. "RESOLVES BY CODE … on 2026-09-30" is a real return date; she'd come back Sep 30 **if** the site let her subscribe to the docket (RSS of resolutions). It doesn't; RSS is the chronicle.
- **HN:** a build-log entry that admits a bug. He'd star the repo and never return to the site — unless the build log were the site.
- **Mother:** his voice. A weekly 3-line note from Matthew, dated, with a photo. Not "Elena". Not the chips.
- **Matthew:** the site telling him something the email didn't: "you missed Lisa's ask, 7 days"; "Thursday's session, loads filled in"; "journal: 17 days — the coaches can't see you". Today the cockpit repeats the 10 AM email and adds chrome.

Common to all five: **a dated promise in a human's voice.** The site has exactly one dated promise and it belongs to a fictional journalist.

### (e) The delete list — nobody would notice

1. "How the pieces fit" loop diagram + "The measuring rule, bent into the loop…" + all four "STATION 0x" blocks (`/`) — the site explaining its own nav.
2. "THE SEVEN AREAS · MEASURED CO-MOVEMENT" bubbles and "NEWLY UNLOCKED" (`/`).
3. "TRY IT ON · YOUR ONE NUMBER" (`/`).
4. "Ask the data anything" (`/`) — rate-limited to 5/hour, "may pause under the budget guard"; a sceptic reads that as a demo.
5. The generated Webb/Reyes dialogue (`/coaching/`, `/cockpit/`) — keep the docket, delete the screenplay. Also "THE INTEGRATOR'S CALL" paragraphs.
6. "WHERE THE TEAM STANDS" seven one-liners ("Felt-Sense Calibration Under Load", "Data gate: awaiting synchronization") (`/cockpit/`).
7. "The engine's score for yesterday — what built it" + "TODAY'S MARK 77% · 8.6 H · 29 consistency" gauges (`/cockpit/`) — the same numbers as the "Last night?" paragraph.
8. "THE CAST SHEET · AUTHORED TRAIT SCORES" sliders (EVIDENCE BAR / BOLDNESS / REVISION SPEED / INTERVENTION URGE / RANGE) (`/coaching/by-coach/`) — character-design metadata for fictional characters.
9. "Did this page make sense? Yes / Partly / No" on every page. "YOU ARE HERE ON THE LOOP" footer block. "NEXT ON THE LOOP / OR COME BACK" block. The loop strip under every H1.
10. `/story/panel/` (a podcast with one prologue and a "final review" notice three weeks old) — until there is a second episode.
11. `/method/character/` "How the score works" — 706 words on pillars; nobody outside the build asks.
12. The "New here?" banner on `/cockpit/` and `/data/` (it does persist its dismissal, so this is a first-visit cost only — but a first visit is the whole audience of a Reddit link).
13. "THE FIGURE, DRAWN FROM THE NUMBERS" silhouette (`/data/`) — replace with a photo or delete.
14. The "MILESTONE LADDER" 17 rungs from 327 to 185 (`/data/`) — two crossed, fifteen empty rungs is a wall of not-yet.
15. Half the footer: the FOLLOW list has seven networks and one subscriber.

### (f) The keep list — what gripped anyone

1. **The three questions on `/cockpit/`** — "How's the week? / Last night? / Today?" with n's, dates and "provisional — three weeks is too few to trust it." Every persona read it to the end. It is the site.
2. **`/story/attempts/`** — "17 starts, counted … NONE OF 16 ATTEMPTS REACHED [day 30]"; "SHOWED UP 0 OF 1 DAY". The most human page, and it has no photo and no link from any hero.
3. **The scorecard's embarrassing rows** — "Dr. Marcus Webb 0% · 0✓ · 5✗", "36.9 % career", "468 EXPIRED WITH NO COACH FOLLOW-UP".
4. **The dispute docket as a table** — "RESOLVES BY CODE recovery_score < 70 · on 2026-09-30 · STAKE: BRIER 0.25 OVER 3 GRADED CALLS". The mechanism, not the dialogue.
5. **The refusals** — "The engine does not publish a deficit", "Blood sugar — no sensor this cycle", "No projection yet — the weigh-in record spans only 20 days", "the 170 g floor was cleared on 7 of 20 logged days", "HEADSPACE nothing logged for 17 days".
6. **"RANGE HELD 79% OF 253 GRADED"** — a calibration number a QS reader would cite.
7. **The build-log titles** (`/story/build/`) — "Five instruments were green. None of them were measuring anything." That is the engineer's real voice and it is the most-hidden text on the site.
8. **"One subscriber so far."** and the email address on About — the only two lines that sound like a person saying something small and true.

---

## The one-paragraph verdict

The site has the receipts of an honest experiment — 16 counted failures, a 0-for-5 coach left on the board, a forecast that says how often it's wrong, a repo — and it hides every one of them under fourteen screens of a language model describing the site's own metaphor, eight illustrated doctors conceding each other's points, and a fictional journalist with a stock photo. There is no photograph of the man and no sentence from him this month. A Reddit reader's slop detector fires on the hero and never gets to the scorecard; his mother gets to the scorecard and can't find his face. The fix is not a redesign of the doors; it is a reversal of the order: the human first (photo, his words, this week), the counted failures second, the mechanism third, the coaches last and short, the machine vocabulary never.
