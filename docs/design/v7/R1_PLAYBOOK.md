# R1 — The masters' playbook for averagejoematt.com v7

**Written:** 2026-09-26 13:05 PT · research lane, read-only · Fable 5.1
**Inputs:** the owner's brief (12:40 PT), `PLATFORM_NORTH_STAR.md`, `SITE_MAP_AND_INTENT.md`, `SITE_TRANSFORMATION_V6.md` §7/§9, `DESIGN_SYSTEM_V5.md` (skimmed), the 25-page 390 px grade sweep (`scratchpad/grade/`, 3 A · 12 B · 2 C · 8 D), six screenshots and eleven page bodies read.
**Honesty bar:** "verified" = I fetched or searched it today and the URL is given. "from memory" = I did not verify it online today; treat as a lead, not a citation. Two fetches failed and are marked (feltron.com FAR14 — connection reset; nomadlist.com/open — currently a one-line placeholder "Will be back in a few days while I clean up the code", which is itself worth knowing).

---

## The fifteen principles

### 1. Lead with the sledgehammer number — dated, with its range, in one line

**Principle.** The first screen carries the single most interesting measured fact, its date in words, and its uncertainty; everything else on the site is the argument for that number.

**Exemplars.** The Pudding's own process guide: *"If the central idea that you're investigating is relatively straightforward, you can often begin your project with a 'sledgehammer' stat: your central, most interesting finding"* — and giving it away early *"tends to make tangential and related points more intriguing"* (verified: https://pudding.cool/process/how-to-make-dope-shit-part-3/). Stephen Wolfram's 2012 personal-analytics post opens with one scatter plot — *"the time of each of the third of a million emails I've sent since 1989"* — one picture that carries twenty years before a word of analysis (verified: https://writings.stephenwolfram.com/2012/03/the-personal-analytics-of-my-life/). FiveThirtyEight frames every live number as a probability with a calibration claim (candidates given 30% won about 30% of the time) and rebuilt its 2020 page because the 2016 design "oversimplified" the odds — uncertainty was the thing the redesign was for (verified: https://fivethirtyeight.com/features/how-fivethirtyeights-2020-presidential-forecast-works-and-whats-different-because-of-covid-19/ and https://www.niemanlab.org/2020/07/this-is-how-fivethirtyeight-is-trying-to-build-the-right-amount-of-uncertainty-into-its-2020-election-data-analysis/). The counter-example: the NYT 2016 needle rendered uncertainty as a quivering animation and became "the most hated data visualization in politics" — uncertainty shown as motion reads as panic, uncertainty shown as a range reads as honesty (verified: https://www.fastcompany.com/90459366/the-most-hated-data-visualization-in-politics-is-back-to-spike-your-blood-pressure).

**Why.** Nielsen's inverted-pyramid rule for the web: conclusion first, because readers scan and leave (verified: https://www.nngroup.com/articles/how-users-read-on-the-web/). A number with a date and a range is also the cheapest credibility signal there is — it tells a sceptic you know the difference between a reading and a claim (ADR-105 already says this internally; it has to be visible).

**For averagejoematt.com this means:** every one of the reachable pages opens, above 700 px at 390, with one served number, one date in words, and — where it is a rate or a forecast — its range and n. The home fold's line becomes the site's headline, not a mono caption: **"313.8 lb on Saturday, September 26 — down 13.5 lb in 21 days, 13 weigh-ins. Rate about −4.4 lb a week, provisional (−4.7 to −2.8)."** Testable: a fold check that fails when the first served fact has no date or a percentage has no n.

**Where the site violates it.** `/method/` opens on "39 GRADED FAILURES · 2989 CLAIMS AUDITED · 6 CAUGHT WRONG" with no date and an unformatted thousand; `/coaching/scorecard/` shows "Dr. Marcus Webb 0% · Dr. James Okafor 100%" with no n and the date in ISO below the fold; `/gear/` has no number at all; `/protocols/` puts its date at y 784, under the fixed bar. (`/`, `/cockpit/`, `/data/*` already do this — copy them.)

---

### 2. One job per page, and far fewer of them — cut the choice, not the depth

**Principle.** A reader can hold about five doors; every extra one lowers the chance they open any.

**Exemplars.** Iyengar & Lepper's jam study: a 24-flavour table drew more people (60% vs 40%) but 3% bought, versus ~30% at the 6-flavour table (verified: https://www.coglode.com/research/choice-paradox and the arXiv re-analysis https://arxiv.org/pdf/2212.03931, which is worth knowing exists — the effect is real but smaller and conditional than the folklore). Krug's three truths from usability testing — "we scan, we satisfice, and we muddle through": people click the first plausible link, so a rail of 29 topics is 28 wrong guesses (verified: https://readingraphics.com/book-summary-dont-make-me-think/). Hick's law — decision time grows with the log of the number of options (from memory; the canonical Hick 1952 / Hyman 1953 result).

**Why.** The owner's own diagnosis is choice overload ("a lot of menus, clicks"); the v6 doc measured 91 reader pages and 39 reachable, now ratcheted to 25. Every added page dilutes the return habit because there is no single place to return to.

**For averagejoematt.com this means:** a reachable set of **nine** (see the close, (b)), a bottom bar of five, no "ALL N TOPICS" rails anywhere on a reader page, and depth folded into the page it belongs to (sections and collapsed blocks, not sibling URLs). Testable: `NAV_REACH_CEILING` ratchets from 25 to 9; the door pages carry zero topic rails.

**Where the site violates it.** `/method/` "ALL 29 TOPICS"; `/data/` "ALL 14 TOPICS" (still linking three pages outside the reachable 25); `/coaching/scorecard/` carries a six-tab row that wraps to four lines at 390 before any content; `/protocols/` "ALL 3 TOPICS" where two are unlisted.

---

### 3. Write for scanners: ≤120 words in the fold, one idea per block, headings that are questions

**Principle.** The page must work for someone who reads a fifth of it.

**Exemplars.** Nielsen: 79% of users scanned every new page, 16% read word by word (verified: https://www.nngroup.com/articles/how-users-read-on-the-web/); on an average visit people read at most 28% of the words, more realistically 20%, and read half of a page only when it has ≤111 words (verified: https://www.nngroup.com/articles/how-little-do-users-read/). Krug's billboard: a page is read like a sign at 60 mph (verified via the summary above). The Pudding: *"writing and structuring information with others in mind forces you to create work that is clearer and more accessible than if you were taking notes for yourself"* (verified, same process post).

**Why.** Scanning follows headings and first words; a heading that is the reader's own question ("Last night?") lets them stop when they have the answer. The cockpit's three-question layout is the best thing on the site precisely because of this (grade sweep: 10-s score 5).

**For averagejoematt.com this means:** every door's fold is ≤120 words in ≤4 blocks, each block headed by the reader's question in plain words; no orientation strip, no ribbon, no disclaimer above the first fact. Testable: a word count on the fold DOM per page ≤120; every `h2` in the fold ends in "?" or is a date.

**Where the site violates it.** `/gear/` opens with a 90-word affiliate disclosure and then "HOW THIS LIST STAYS HONEST"; `/story/build/` opens on a manifesto card ("Fork the architecture, not the data") that never says "build log"; `/coaching/` opens on the coach's own jargon ("recovery holding above 81.6% EWMA tells us glucose…") and then spends 60 words glossing it.

---

### 4. Progressive disclosure: depth one tap down, never cut, never on the first screen

**Principle.** Show the novice the small thing; give the expert the whole thing behind one deliberate action.

**Exemplars.** NN/g's definition — defer advanced or rarely used material to a secondary screen; it helps novices avoid mistakes and saves experts scanning past what they don't need (verified: https://www.nngroup.com/articles/progressive-disclosure/). Gwern's "semantic zoom" — the same page reads at abstract, summary and full depth, with collapsible sections and popups, so a 20,000-word essay opens like a 200-word one (verified: https://gwern.net/design and https://gwern.net/about).

**Why.** The north star's fourth audience (QS enthusiasts) needs the 152-marker lab table and the methods registry; the first three need to never see them uninvited. Cutting depth would break the moat; fronting it breaks the door.

**For averagejoematt.com this means:** the numbers page shows one chart and one sentence per topic with a "see all N" that expands in place; labs opens on "last test April 3 — 26 of 152 markers out of range" and the printout is collapsed; method's "wrong page" opens on the count and the three most recent failures as sentences, with the raw evaluator record behind a "show the receipt" toggle. Testable: no reader page exceeds ~3 phone-viewports before its first collapse control.

**Where the site violates it.** `/data/labs/` — 16,000 px of rows (v6 §4); `/method/` — evaluator strings in the cards ("RECOVERY_SCORE=73.00 ON 2026-09-13 VS PREDICTED 52.9 ±18.2532 …"); `/data/nutrition/` — a hero that scrolls 16 px with no keyboard access (axe serious).

---

### 5. Make it a serial: every page says which week it is and when the next thing lands

**Principle.** People come back for the next instalment, not for the archive; a dated "next" is the return trigger.

**Exemplars.** *Dear Data* — 52 weekly postcards, one theme per week, two people; the week number was the structure and the reason to keep going (verified: https://en.wikipedia.org/wiki/Dear_Data, https://www.pentagram.com/work/dear-data/story). Felton's annual reports ran ten years on one cadence, and the final one was announced as final (verified: https://www.itsnicethat.com/articles/nicholas-felton-releases-final-ever-personal-annual-report; the FAR14 page itself failed to fetch). Stratechery: one free weekly article and three subscriber updates a week — a fixed cadence readers plan around, with the audio version cited as why commuters keep the habit (verified: https://stratechery.com/about/ and https://www.thetilt.com/content-entrepreneur/ben-thompson-stratechery). The "previously / this week / next" pattern of television recaps — from memory; no single source.

**Why.** A habit needs a cue; a dated promise is the cue. Loewenstein's curiosity theory (principle 12) says the gap has to be specific — "next write-up Wednesday, September 30" is a gap with a closing date; "follow by email for the next entry" is not.

**For averagejoematt.com this means:** one shared line on every page, from one formatter: **"Week 3 of the experiment · the coaches write every morning · next write-up Wednesday, September 30."** The story page already has exactly this and is one of the three A grades; make its footer the site's footer. Testable: every reachable page's DOM contains a future weekday date.

**Where the site violates it.** Nine pages with no dated return trigger — `/story/journal/`, `/story/about/`, `/story/attempts/`, `/story/build/`, `/method/`, `/method/character/`, `/gear/`, `/privacy/`, `/story/panel/` ("it'll drop here as soon as it clears the quality bar" — an IOU with no date).

---

### 6. The receipts strip: stats-first titles, third-party verification, a real photo

**Principle.** A sceptical audience checks four things in the first ten seconds — the numbers in a fixed format, who verified them, a face, and whether anything is being sold.

**Exemplars.** r/progresspics enforces a title grammar — `M/40/5'10 [338 > 261 = 77 lbs]` plus the time span — before the photo is even seen; the whole genre runs on that line (verified examples: https://pholder.com/r/progresspics/?page=56). r/loseit's most-upvoted posts are before/after photos with the number in the title (verified: https://www.dailydot.com/news/reddit-lose-it-weight-loss-interview/); the community's SV/NSV (scale victory / non-scale victory) convention and the "same clothes, same light" photo rule are from memory. Nomad List's open page labels each metric with its verifier — revenue by Stripe, traffic by Simple Analytics, uptime by Uptimerobot (verified via https://github.com/gabrielperales/awesome-open-startup and https://x.com/levelsio/status/968219339588493312; the page itself is a placeholder as of today). Buffer has published finances and salaries since 2013 and reports doubled job applications in the first 30 days of open salaries (verified: https://buffer.com/transparency and https://buffer.com/resources/salary-system/).

**Why.** Reddit and HN readers pattern-match for the missing receipt: no photo means "could be anyone", no start weight means "cherry-picked", affiliate links above the content mean "a funnel". The site already has the data for the strip; it doesn't render it as one.

**For averagejoematt.com this means:** a fixed receipts strip on home and "who he is", in the r/progresspics grammar, every value served: **"M · 5'11" · start 327.3 lb (Sep 6) · now 313.8 lb (Sep 26) · −13.5 · day 21 · 17th attempt · 12 sources feeding · $5.74/day to run"**, next to a dated photo of him (#3761 is on the critical path — no exemplar in this genre works without the face). Chronological age stays out (privacy absolute); height is the owner's call. Testable: the strip's values are all `[served: field]`-tagged; the photo has a date caption.

**Where the site violates it.** `/story/about/` has not one number; `/gear/` leads with the affiliate disclosure; no reachable page carries a photograph of Matthew; `/story/attempts/` has the best receipt on the site ("17 starts, counted … none of 16 reached day 30") and is a D for a legend and an old wayfinder.

---

### 7. Admitted failure is the moat — told as sentences, not dumped as logs

**Principle.** Show the misses, in words a friend can read, with a date and what changed; a raw evaluator string is not honesty, it is noise wearing honesty's clothes.

**Exemplars.** Gwern tags every essay with a confidence word from the Kesselman estimative list ("certain … highly likely … remote") and a 0–10 importance score, and dates creation and last meaningful edit (verified: https://gwern.net/about). FiveThirtyEight's forecast pages carry a "how this works" methodology piece and a calibration record as part of the product (verified above). r/loseit's culture prizes the "I regained it all and started again" post — from memory, no single URL.

**Why.** A miss stated plainly ("the call was 53 ± 18; it came in at 73") raises trust; the same fact as `|Δ|=20.10 → OUTSIDE TOLERANCE` reads as a machine talking to itself and tells the reader the page was not made for them. The north star says honesty is the moat; the grade sweep shows honesty presented in a way that scores D.

**For averagejoematt.com this means:** the wrong page renders each failure as three sentences from one template — *what we said · what happened · what we changed* — with the date in words and the raw record behind a toggle; the site's "17 starts, none reached day 30" chart moves onto the home second screen as the standing admission. Testable: no `_`-joined identifier, `±` with more than one decimal, or ISO date is visible on a reader page without a toggle open.

**Where the site violates it.** `/method/` — "The number that killed it: recovery score measured 0.08" (a slope printed as a score), "2989", 98 ISO dates in the body; `/coaching/scorecard/` — "0%" on a coach with a handful of calls.

---

### 8. Voice: the slop tells are known — lint the generated text against them

**Principle.** Generated prose reads as a person when it is specific, dated, admits error, and refers to its own past; it reads as slop when it hedges, generalises, and performs significance.

**Exemplars.** Wikipedia's editors maintain a list of the tells: vocabulary ("delve", "underscore", "pivotal", "tapestry", "testament", "showcase"), the "not just X, but Y" construction, the rule of three, marketing verbs ("boasts", "offers"), vague attribution ("experts argue"), "-ing" tails that fake analysis, overuse of bold and em dashes, and outline-shaped conclusions (verified: https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing). Green & Brock (2000): readers who are transported into a narrative "found fewer false notes"; the converse is the point — a false note (a wrong number, a generic sentence) ejects the reader and the belief with them (verified: https://pubmed.ncbi.nlm.nih.gov/11079236/).

**Why.** The owner's fear ("looks like AI slop") is a vocabulary and structure problem before it is a design problem — and it is machine-checkable. Specificity is the single strongest counter-signal: a sentence that names a Tuesday, a gram count and a prior claim cannot be a template.

**For averagejoematt.com this means:** a slop lint (`scripts/`) over every generated surface — coach reads, the write-up, field notes, the daily line — that fails on the Wikipedia tells and on a *specificity floor*: every generated paragraph must contain at least one date, one served number and one reference to a prior claim or a named source. Testable: the lint runs in the quality gate (`ai_calls._enforce_quality_gate` already regenerates-or-holds — add the tells to it).

**Where the site violates it.** `/coaching/lab-notes/` — "Week 2026-W38 marks a notable shift in both training intensity and recovery metrics … This represents either a deliberate …" (marks, notable, represents either — three tells in two sentences); `/coaching/` — "Two contingent predictions are now live over the next 4–6 days" (no number, no date); `/` — "the shape of it, every day, just below" (a flourish).

---

### 9. A coach is a character only if it remembers — "last time I said X; it came in at Y"

**Principle.** Memory is the difference between a persona and a voice: each read must open on its own prior claim and its outcome, and the record must be visible with n.

**Exemplars.** FiveThirtyEight's calibration ("30% chances came in about 30% of the time") is the form — a forecaster who keeps score in public (verified above). Gwern keeps dated predictions and grades them — from memory (PredictionBook; not verified today). Stratechery's "as I wrote in 2015 …" self-citation habit, building one argument across years — from memory. *Dear Data* proves a two-voice weekly correspondence holds attention for 52 weeks (verified above).

**Why.** The owner's test — "real thoughts on the experiment, with memory, instead of just state in time" — is exactly the transportation condition: a character with continuity. Without continuity a coach read is a horoscope. The engine already stores predictions, corrections and a track record; the page just never puts the prior claim next to the new one.

**For averagejoematt.com this means:** every coach read on a reader page is rendered with a one-line ledger above it — **"Sep 19: said protein would hold above 170 g — it did, 6 of 7 days"** — drawn from `get_coach_track_record`; the scorecard renders "7 of 17, through Saturday, September 26" below n=30, never a bare percentage; a coach with fewer than five graded calls shows "too few to score" rather than 0% or 100%. Testable: a reader-page render check that fails when a coach read has no ledger line and a percentage has no n.

**Where the site violates it.** `/coaching/scorecard/` — "Dr. Marcus Webb 0% · Dr. James Okafor 100% · Dr. Sarah Chen 0 decided"; `/coaching/` — today's read carries no reference to what its author said before; `/coaching/by-coach/` — the record with no date.

---

### 10. Transportation needs a protagonist with stakes, in his own words — every week

**Principle.** The site is about a person; his sentences, dated, are the one thing no engine can generate, so they belong in the fold.

**Exemplars.** Green & Brock: transportation (imagery, affect, attention) drives belief and liking of the protagonist across four experiments (verified above). The r/loseit top posts are first-person, plain, with the number and the shame in the same paragraph (verified: dailydot piece above). *Dear Data*'s cards are hand-drawn precisely so the person is visible in the data (verified above).

**Why.** Third person everywhere (the v6 panel's ruling) is right for the engine's claims and wrong for the site's pulse. One dated sentence from him a week — "I skipped the gym Thursday and told nobody; the scale told" — does more for return visits than any chart. The 08-30 tape notes and the vlog/journal channels already produce his words; the site under-uses them.

**For averagejoematt.com this means:** a fixed "his word this week" block on home and the write-up — one to three sentences from Matthew, dated, captured through the existing journal/vlog/intake channels — with an honest empty state ("nothing this week"). Testable: the block renders from a served field with its date; the essay page shows its age in words.

**Where the site violates it.** `/` — zero words of his; `/story/journal/` — latest essay "80 days ago"; `/story/about/` — first person, good, and no date or number.

---

### 11. Design the end of every page — the peak-end rule

**Principle.** A visit is remembered by its best moment and its last one; the page's close is a design object, not a footer.

**Exemplars.** Kahneman, Fredrickson, Schreiber & Redelmeier (1993) and Redelmeier & Kahneman (1996, n=154 colonoscopy patients): remembered pain tracks the peak and the last three minutes, not the duration (verified: https://en.wikipedia.org/wiki/Peak%E2%80%93end_rule and https://lawsofux.com/articles/2020/peak-end-rule/). Stratechery closes each piece on its own argument, not on a feedback widget — from memory.

**Why.** The current pages end on a survey ("Did this page make sense? Yes / Partly / No"), a "YOU ARE HERE ON THE LOOP" wayfinder and a mega-menu — the reader's last impression is chrome. The peak of a page should be the number or the sentence; the end should be the next date and one door.

**For averagejoematt.com this means:** one close, everywhere: **the one thing that changed today · the next dated thing · one link** — and the survey, wayfinder and mega-menu move to a single footer line. Testable: the last content block on every page is the shared close component; no page ends on a form.

**Where the site violates it.** `/story/` (an A page) ends on the survey + wayfinder + mega-menu; `/cockpit/` likewise; every page carries the same three-screen footer stack.

---

### 12. An honest curiosity gap: the open question of the week, with its resolution date

**Principle.** Curiosity needs a specific gap and a promised close; the site's open predictions are its best hooks and are never shown as hooks.

**Exemplars.** Loewenstein (1994): curiosity is an information gap that peaks when you know a little and know exactly what you are missing (verified: https://www.scirp.org/reference/referencespapers?referenceid=2828034 and https://psychologyfanatic.com/information-gap-theory/). FiveThirtyEight's live forecast is a standing open question with a fixed close (election day) — verified above. Clickbait is the dishonest version — a gap with no payoff; the honest version names the payoff and its date.

**Why.** The site has 37 graded predictions and "two contingent predictions live over the next 4–6 days", but the reader never sees "what's about to resolve". A dated open call is the serial's cliffhanger and it is already computed.

**For averagejoematt.com this means:** a "resolves next" block on home and the coaches page: **"Open: Dr. Brandt says recovery holds above 80% through Friday — resolves Friday, October 2."** Drawn from open predictions, with the outcome written back in place when it lands. Testable: the block renders ≥1 open prediction with a future date, or an honest "nothing open".

**Where the site violates it.** `/story/panel/` — an undated IOU; `/protocols/experiments/` — "Nothing is running yet. Four experiments are ready to start; 63 ideas are waiting" (a backlog, not a question); `/coaching/` — the live predictions are mentioned inside a paragraph and never surfaced.

---

### 13. Mobile-first fold discipline: ~700 px, one fact, one picture, one link

**Principle.** On a 390×844 phone with a 68 px bottom bar, the fold is ~700 px; the first fact, a picture that carries it, and one next step must fit, and nothing else may go above them.

**Exemplars.** Wolfram: one chart first (verified above). The Pudding: "begin the story with a single data point" for complex ideas (verified above). Krug's billboard (verified above). NN/g's F-pattern: attention concentrates on the first lines and the left edge; what sits below the first screen is seen by a minority — from the search summary at https://www.nngroup.com/articles/how-users-read-on-the-web/ (the F-pattern paper itself not fetched).

**Why.** The grade sweep is a 390 px fold audit and the misses cluster in the same place: orientation chrome (kicker + day line + H1 + lede + wayfinder ribbon + "New here?" strip) eats 250–700 px before the first fact. The cockpit's fact starts at ~y 540; the method page's at ~y 1,400.

**For averagejoematt.com this means:** a fold budget per page: kicker (1 line) + the fact (≤3 lines) + one figure (chart or photo, ≤280 px) + one link, all inside 700 px; the wayfinder ribbon and the "New here?" strip leave the fold entirely. Testable: the existing Playwright fold harness asserts the first served fact's y < 400 and a figure or photo is present above 700 on every door.

**Where the site violates it.** `/protocols/` and `/protocols/experiments/` — "Data through …" at y 784–785, under the bar; `/method/` — hero and ribbon fill the entire first screen; `/cockpit/` — strip + ribbon + day line before "How's the week?"; `/story/build/` — the fold is a manifesto card.

---

### 14. Jobs-to-be-done: three visitors, three questions, three surfaces — and no fourth

**Principle.** Design the first screen for the job the visitor arrived with: a stranger asks "is this real and should I care?", a friend asks "is he okay this week?", Matthew asks "what do I do today?" — everything else is depth.

**Exemplars.** Jobs-to-be-Done (Christensen; Ulwick) — from memory, no fetch. The v6 document's own reader model ("who is he · how is it going · what do I look at today") is already this framing and the B1 audit measured every door failing it (v6 §1: 10-second scores 1–3 across the doors before the overnight PRs).

**Why.** The loop diagram is the builder's job (which station am I?) and it sat on every first screen for a year; the north star's own rule ("which part of the loop am I?") was optimised for the fifth audience. The fix is to let each page answer one visitor and let the loop be the second screen's explanation, as v6 §5 now says.

**For averagejoematt.com this means:** home serves the stranger and the friend (receipts strip, "is he okay this week", his word, the open question); "today" serves Matthew (the three questions, the session, the ask); the write-up serves the returning friend. No page's first screen serves the builder; `/method/state/` stays unlisted. Testable: each door's fold is labelled with its job in the registry and the sweep grades it against that job's question only.

**Where the site violates it.** `/` — the loop dial and the "STATION 01 … STATION 04" arc are still the second and third screens, ahead of anything a friend would scroll for; `/story/build/` — serves the builder from the story door.

---

### 15. One vocabulary, one date, one voice — consistency is what "elite" looks like

**Principle.** The same fact phrased three ways, or dated two ways, reads as three sources disagreeing; one formatter and one registry make the site feel made by one hand.

**Exemplars.** Gwern's manual of style — one house style, applied over decades, is what makes long content feel like one document (verified: https://gwern.net/style-guide). Felton's reports reuse one visual grammar year after year so the years compare (verified via https://www.moma.org/collection/works/145531 — the pages themselves not fetched). Design systems generally — from memory.

**Why.** The v6 vocabulary registry (`site/data/glossary.json`) and the "dates in words" ruling exist; the grade sweep shows the residue is in kickers, rails and formatters, not in the rules. Consistency is also the cheapest anti-slop signal: templates that agree with each other read as editorial, templates that drift read as generated.

**For averagejoematt.com this means:** one date formatter for every reader surface ("Saturday, September 26"; "4 days ago"; never ISO, never "as of"), one kicker template per door, one name per thing (the write-up, the coaches, his numbers), and the existing residue test extended to kickers and rails. Testable: `site_vocabulary_residue.py` fails on any ISO date or "as of" in a reader-page DOM.

**Where the site violates it.** `/data/` — three phrasings of the same kicker ("WHAT THE BODY & MIND REPORT" / "what his devices record" / "This page is his numbers"); `/protocols/` "Friday, September 25" vs doors' "Friday Sep 25"; `/coaching/lab-notes/` "Week 2026-W38 · 2026-09-20"; `/story/attempts/` wayfinder still reads "NOW · DATA → COACHING"; `/privacy/` calls the newsletter "The Measured Life", which `/subscribe/` never does.

---

## The close

### (a) The organising metaphor: a serialised investigation

**Build the site as one open investigation, published weekly, into a single question: *can AI plus his own data move one ordinary life — and by how much?*** Each week is an instalment with the same parts: the finding (the number, dated, with its range), the evidence (his numbers), the witnesses (the coaches, on the record, scored), the subject's testimony (his words), what's about to resolve, and the corrections to earlier instalments. The archive is the case file.

Why this one: it is the owner's own word set ("investigative, reporting, insightful"); it gives every existing engine part a natural role without inventing anything — predictions become open questions with resolution dates (12), coaches become expert witnesses whose prior testimony is on record (9), the wrong page becomes the corrections column (7), the attempts chart becomes the prior history of the case (6), the write-up becomes the weekly instalment (5). It keeps the sceptic, because an investigation is allowed to find nothing; a transformation story is not. And it scales down: an investigation with nine pages is still an investigation.

**Alternative: a season of a show.** Week N as an episode, "previously on", the panel as cast, a finale date. It is grippier for friends and family and matches the podcast; it is rejected as the primary frame because it drifts toward transformation theatre (the north star's first non-negotiable) and because a "season" implies an ending the terminal-cycle ruling has not set. Borrow its recap grammar (previously / this week / next) inside the investigation.

### (b) Target page count: nine reachable, plus privacy

1. **Home** — the case so far: receipts strip + photo, "is he okay this week", his word, the open question, then the 17-attempts chart, then the loop as "how it works".
2. **Today** — the three questions, the session, the one ask (the cockpit, as v6 ruled).
3. **This week** — the current write-up with the previously/next rail; the archive is a list on the same page.
4. **His numbers** — one page; weight, sleep, training, eating, labs as sections, each one chart + one sentence, "see all" in place.
5. **The coaches** — today's read with its ledger line; where they disagree; the record (n shown); the by-coach roster collapsed below.
6. **What he's trying** — supplements and experiments as "what · should move · how we'd know", the decision log in his words.
7. **Who he is** — about, in first person, with the receipts strip, the photo, every attempt.
8. **Under the hood** — the corrections column (wrong page), how the numbers are made, the gear list, the build log — one page with sections; the registry and state pages stay served and unlisted.
9. **Follow** — subscribe, with the honest count.

Plus `/privacy/`. Everything else keeps its URL, unlisted. Why nine: five bottom-bar items (1–5) is Krug's satisficing limit and the jam study's low table; 6–9 are footer-tier; every visitor job from (14) has exactly one home; and a nine-page site can be re-shot and graded in one sweep every week, which is the only way the A-grade ratchet stays honest.

### (c) The three things a Reddit visitor must see in ten seconds

1. **A dated photo of him beside one number:** "313.8 lb, Saturday, September 26 — down 13.5 lb in 21 days from 327.3." (The face is what the genre runs on; the number is the sledgehammer.)
2. **The premise in one sentence, with the receipt that it's hard:** "An ordinary guy, 300+ lb, on his 17th attempt — this time with the wearables he already wears and a staff of AI coaches, published either way." The "17th" is the honesty signal; a sceptic trusts a site that leads with its failure count.
3. **Proof it's alive and keeps score:** "Data through today · the coaches were right 18 of 37 times · next write-up Wednesday, September 30." Freshness, calibration, cadence — the three things a HN reader checks before deciding it isn't a template.

### (d) What the coaches should be on the page

**Expert witnesses with memory — a small named panel, one voice a day, all on the record.** Not a chorus (eight voices on one screen is the 24-jam table) and not a dashboard of personas. The form that is proven: a forecaster who keeps public score (FiveThirtyEight's calibration — verified) and a two-voice dated correspondence that people followed for 52 weeks (*Dear Data* — verified). On the page that means: one read per day at the top with its written time (v6 ruling iv, keep), opened by its own ledger line ("Sep 19 I said … it came in at …"), the disagreement rendered as two named witnesses with the engine's number between them, and the record as "K of N through <date>" — at most three coaches visible on any screen, the rest one tap down. The owner's test ("real thoughts, with memory, instead of state in time") is passed by the ledger line and failed by everything else; ship the ledger first.

---

## What I could not verify today (leads, not citations)

- r/loseit's SV/NSV convention and the "same clothes, same light" progress-photo rule; the top-of-all-time post list.
- Gwern's dated prediction tracking (PredictionBook); Stratechery's self-citation habit; the TV "previously on" recap grammar.
- Hick's law figures; Jobs-to-be-Done sources; the NN/g F-pattern paper itself (only the search summary).
- A specific viral "I tracked X for a year" Reddit post — searches returned Felton, *Dear Data* and a 168-metric tracker (https://whatcounts.io/p/i-tracked-168-personal-metrics-this-year-here-is-what-i-learned), none confirmed as viral.
- Felton FAR14 page (connection reset); Nomad List's open page (placeholder today).
