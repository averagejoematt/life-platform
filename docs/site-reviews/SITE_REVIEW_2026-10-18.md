# Site Review — 2026-10-18 · The twelve v8 kit pages, graded independently, then fixed once (#4580)

> ⚠️ **Internal self-assessment, not external validation** (`docs/REVIEW_METHODOLOGY.md` ER-05;
> `docs/SITE_REVIEW_METHODOLOGY.md`). Every grade below was produced by an AI grader against a
> rubric the platform authored. The graders were not the authors of the pages or of the fixes
> (grader ≠ author), two verifiers reproduced every finding against the source before a lane was
> briefed on it, and the after-round pair was fresh — but all of that measures *conformance to
> the site's own stated bar*, not what a stranger does with the site. The only trustworthy A is a
> real reader using it cold; that is issue #4587 (five real readers before cut-over) and it is open.

**Scope:** the twelve v8 pages under `/next/v8/` — front · start · story · coaches · week · day · trend · call · coach · sheet · built · appendix.
**Fixtures:** the kit gate's own (`tests/fixtures/kit_pages_4586`, captured `2026-10-17T23:33:25Z`), rendered with the clock pinned to the capture instant, 390×844, light and dark. Deterministic floor on every page in both themes: axe serious/critical 0/0, 0 console errors, 0 non-2xx, no horizontal overflow.
**Grades file:** [`site_grades_2026-10-18.json`](site_grades_2026-10-18.json) — the per-page letters exactly as each grader file holds them, the screen counts before/after, the verifier counts.
**Context:** the first review since the 2026-06-21 full-site pass; the site has since been rebuilt twice (v7, then the v8 kit of twelve components and eight tokens, `docs/design/v8/`). This is the "site-to-A" round the owner asked for on 2026-10-17: grade it independently, fix what is verified, grade it again.

## Throughline verdict

Round 1 (before the fixes): **BREAKS AT day** — the front's "168 minutes of walking" became "90 minutes" one tap later on the day page for the same Saturday; the coaches' yardstick ("the simple guess") was defined two different ways across pages; and the journey stopped at the Week 5 chapter on Day 42 with no page naming the missing week.

After round 1 (G9, the fresh pair): **COHERES on the premise and on the one number** (327 → 185, 76 of 183, Day 42 agree on front, start, coaches, week, built) and **still breaks in three places**: story (the missing Week 6 is still not named as missing), coaches (the "simple guess" still changes meaning), and built (which says the owner approves one thing by hand while every story page says he approves each chapter). The 168-vs-90 walking number is fixed engine-side in #4989 but the fixtures were captured before that landed, so the recaptured render is what closes it.

## Method

Eight graders, one lens each, read every page cold from the same render and wrote one JSON each (grade per page, findings with a quoted line and a y-position in screens, one "to A" sentence per page). The lenses and the anchors they graded against (`docs/reviews/anchors/ANCHORS.json`, v1.0.0, frozen 2026-09-20) where the grader cited them:

| Grader | Lens | Bar / anchors cited |
|---|---|---|
| G1 | the eight Product Board personas (Mara UX, Tyrell design, Sofia CMO, Raj product, Jordan growth, Ava content, Lena science, James CTO) | A = the persona says back what the page is in ten seconds, is not lost, and would come back |
| G2 | reader + narrative | `reader.A.1-4`, `reader.C.1`, `narrative.A.1`, `narrative.A.4`, `narrative.C.1`; the throughline test |
| G3 | designer + dataviz | `designer.A.1`, `designer.A.2`, `designer.C.1`, `dataviz.A.1`, `dataviz.A.4`, `dataviz.C.1`; the kit README (twelve components, eight tokens, accent = progress/new only); "a colour can carry a claim" |
| G4 | a11y + security | WCAG 2.2 AA as the floor; every `clean.css` token pair run through the relative-luminance formula in both themes (all text tokens pass AA; faint-on-panel 4.61 light / 4.63 dark is the thinnest) |
| G5 | numbers (ADR-104/105, the `qs` lens) | every printed numeral traced to a fixture field and re-added by hand |
| G6 | CPO + growth | `cpo.A.1`, `cpo.A.4`, `growth.A.1`, `growth.C.1`; `PLATFORM_NORTH_STAR.md` §The success bar; #4580 done-when bullet 5 |
| G7 | North Star | the seven adjectives of `PLATFORM_NORTH_STAR.md` §The success bar, A/B/C/F each; the page grade is the read of the seven, not an average |
| G8 | the v7 R7 method re-run | the eight items of `BUILD_WEEK_BRIEF.md` §4 row 1 (A = 8/8, B = one miss, C = two or more), so the seven pages that have a v7 counterpart get a like-for-like delta |

**Verification.** Two verifiers (pages A: front · start · story · coaches · week · day; pages B: trend · call · coach · sheet · built · appendix) took every grader finding, reproduced it against repo `main` 385917e0e plus the fixtures, merged duplicates into one canonical defect with a fix and a lane, and refuted the rest with a reason. The real counts:

- **363 raw grader findings** (G1 44 · G2 55 · G3 51 · G4 64 · G5 31 · G6 38 · G7 36 · G8 44).
- **144 confirmed canonical defects**, each with a fix sentence and a lane (shared 42 · a 16 · b 13 · c 20 · d 25 · e 18 · owner 10). On the A pages the 59 canonicals absorbed 166 grader findings — the front's top defect alone merged seven findings from five graders.
- **85 entries refuted**: 30 duplicate-of another canonical (G4's skip-link / `<nav>` / "Loading." trio was filed on every page and counted once), 19 the grader's own "no defect" or info-only rows, 12 security or AAA notes that the same grader had not graded down, 9 misreads or evidence that did not reproduce, 5 intentional-by-design (the Start deltas computed from the two rounded printed weights so the row agrees with itself; the per-coach meters removed the same day), 10 harness or ruling artefacts (the coach page rendered its not-found branch because the harness passed no `?c=`; the appendix lists planned pages because the owner's 2026-10-04 ruling keeps retired pages listed).
- So **144 of 363 (40%) survived as a distinct confirmed defect**; by verifier entries, 85 of 229 (37%) were refuted outright and the remainder of the shrinkage is duplication. That is the ~50% refutation-or-duplication rate the lane briefs were written against, and the reason no lane was briefed from a grader file directly.

**Round 1 then round 2.** Six lanes fixed the verified list (below), the branch was re-rendered on the same pinned clock (`a673b6eeb`), and a *fresh* pair graded it: G9 (clarity · truth · calm · voice, every number re-added by hand) and G10 (design light · design dark · a11y · numbers · North Star). Neither had seen the round-1 files.

## Round 1 — the grade table (before the fixes)

| Page | G1 personas | G2 reader | G3 design (dark) | G4 a11y / security | G5 numbers | G6 CPO+growth | G7 North Star | G8 R7 (v7 → delta) |
|---|---|---|---|---|---|---|---|---|
| front | B | B | B (B) | B / A | C | C | B | B (B → 0) |
| start | B | B | B (B) | B / A | B | C | B | B (A "Who he is" → −1) |
| story | B | B | A (A) | B / A | C | C | B | A (B "This week" → +1) |
| coaches | B | B | B (B) | B / A | B | B- | A | B (C → +1) |
| week | B | B | B (B) | B / A | A | C | B | B (new page) |
| day | C | C | B (B) | B / A | B | B- | B | C (A "Today" → −2) |
| trend | C | B | A (A) | B / A | A (vacuous: no numerals render in the index state) | C | C | C (C → 0) |
| call | B | B | B (B) | B / A | B | B | B | B (new page) |
| coach | B | B | B (B) | B / A | A (vacuous: the not-found branch rendered) | C | C | not measured (not-found branch) |
| sheet | B | C | B (B) | B / A | B | B- | C | B (new page) |
| built | B | C | B (B) | B / A | B | B- | A | C (B "Under the hood" → −1) |
| appendix | C | B | B (B) | B / A | A | B- | C | C (new page) |

G8's verdict on the round-1 render, quoted: "Not ready to cut over — because the A-grade sweep is unmet again: 1 A, 6 B, 4 C and 1 unmeasured across twelve pages (R7: 2 A, 5 B, 2 C across nine). On the seven paired pages the like-for-like delta is −2 net." Its misses were concentrated: item 5 (a dated return trigger) was 8 of the 14 misses and one kit component — the Follow box or a "Next" row — placed per page.

G7's seven adjectives, where a page fell below B: start returnability C; story legible C; coaches returnability C (its only non-A); day coherent C; trend interest/returnability/elite/2026-forward C; coach interest/returnability C; sheet elite/2026-forward C; appendix interest/returnability/2026-forward C. Honest was A on nine of twelve pages — the site's standing strength.

## The verified top findings per page, with the lane that took them

Lane letters are the verifiers' (`shared` = structure or engine, used by more than one page; `a`…`e` = one page group; `owner` = needs his words or his ruling). The PR that carried each lane is in the next section.

| Page | Top verified defects (rank order) | Lane |
|---|---|---|
| front | F1 "Today so far … 168 minutes of walking" — the served edition's week block carried October 14's row under October 17; the day page prints the source's 90 (7 findings, 5 graders) · F2 the coaches section opened on a null state ("No open bet between them this week") with no coach voice on the front while the day page carried one · F3 "The clearest miss this week" was a call about a reading 25 days earlier, graded late, with no graded-on line · F4 two yardsticks both called "a guess" (the 42% base rate on front/start/coaches; "nothing changes from the last reading" on week/call) · F16 "In his own words — nothing new since September 23" linked to a page that ends on the same absence | shared · a · a · shared · a |
| start | S1 the recap stopped at Week 5 (Day 31) on Day 42 and "Open now" named only the next draft date; Start did not use the held-chapter line Story does · S3 a full "Open now" section answering with one date · S2 no Follow block on the cold-reader page · S4 the chapter rows were not links · S5 the weight chart scaled y over min–max so a 25 lb drop filled most of the frame, while the front's mark frames start → goal | a |
| story | ST1 "Every episode" ended at EP4 while EP5 is held; every row linked a bare mp3 and no player rendered because the only player is gated on the held episode · ST2 the series title used as an unglossed section kicker · ST3 the held-chapter line inferred "waiting for approval" from date arithmetic with no served marker · ST4 older chapter rows showed no link affordance · ST5 the AI chapter's own hedge ("suggesting 18.4 pounds gone", "a season high") — the served dek, an editorial fix upstream | b · b · b · shared · owner |
| coaches | C1 a Brier skill score printed as "0.9% worse" with no scale · C2 the lead coach listed first with no record and no reason while the served `headline_stat` carries one · C6 no next-to-settle date and no Follow block · C3 the record track filled in the accent — green = earned — beside the sentence saying they do no better than a guess · C4 the sentence that most of the 183 are commentary or hedges set in small grey type under an h1 saying "Every call checked" | b · b · b · shared · b |
| week | W1 the Food row's `not_enough_data` state drew no dot and no line said what filled/hollow/none mean · W2 a "What went right" row keyed "Matthew" that repeated the Sleep row verbatim · W3 the AI rule clause printed twice and naming the wrong yardstick · W4 the page ended on an absence with no next date · W5 the meta description promised a lead-coach section the page removes when absent | c |
| day | D1 "What I lifted." over nothing lifted, with the front's "Planned: …" for the same day omitted · D2 "It came in at 304 lb" above "Weight: 302.2 lb" because the card dropped the served "for October 16" · D3 an undated expectation served as "A call", and "38 days" (the journal) against "since September 23" (his notes) — two records read as one silence of two lengths · D4 first-person static headings beside third-person served sentences · D5 no standfirst saying what the page is | c · c · shared · owner · c |
| trend | 1 the index showed nine bare link rows with no value or date — less than the day page it is entered from · 2 group label "Sleep" over row "Sleep" · 3 no dated line in the header · 4 no context line for a direct entrant · 5 "Recovery" unglossed on the index | c |
| call | 1 one ~120-word served comparison sentence with four "too few calls to tell" clauses · 2 one call restated three to five times in 1.5 screens · 3 the verdict line omitted that the simple guess also won · 4 no unit on the deep-sleep bet threshold (missing from the served `called_short`) · 5 "his weight" in the h1 with no antecedent on a cold share | d |
| coach | 1 a static back-link survived the not-found state, duplicating the header · 2 the long draft-wording footer on a page with no first-person line (same on sheet) · 3 the empty state offered one recovery link instead of the eight names · 4 no standfirst · 5 with JS off, "Loading." as the h1 plus seven empty section headings | d · shared · d · d · shared |
| sheet | 1 "12 level on Friday, October 16" — the number and its word in the wrong order, and a Friday date on a Saturday page unflagged in the headline · 2 served badge labels in "lbs" and "Character Level" against the site's "lb" and "level" · 4 a four-sentence rulebook before the first area and each row a formula dump · 15 the long footer · 3 metabolic health shown as too thin to score yet counted in the composite (`composite_note`: mean of 6 of 7) | d · d · d · shared · owner |
| built | 1 two "as of" dates six days apart in one section (the scheduled-program count is a repo constant, unserved) · 2 "tier 1" used before the table defines it, with the forecast reason inside a closed disclosure · 3 6.54 screens against a ~3.5 bar, prose set in the narrow value column · 5 the owner's best first-person passage last and disclaimed as draft · 4 the approval rule stated three times | e · e · e · owner · e |
| appendix | 1 69 rows over 9.35 screens with no jump list · 2 rows duplicating v8 pages without saying which is the earlier version · 3 internal codenames as titles ("Wrong page" reads as a 404) · 4 a static "Back" link ending the page · 5 the interactive tools group last | e |

Site-wide, the verifiers' shared list was: no skip link and no `<nav>` landmark on any of the twelve (G4, one structure fix); "Loading." as static HTML on ten pages and as the h1 on four; no `og:`/`twitter:` head on eleven of twelve (G6: "for a site whose only growth channel is a pasted link"); the front with no h1; the two biggest doors with no link affordance until hover; and one sentence for the coaches' record worded three ways.

## Round-1 fix lanes

All six landed into the integration PR **#4988** (`issue-4580-site-to-a-round-1`, open against `main`; it merges after the fixtures are recaptured and the kit gate is green on them):

| Lane | PR | What it carried |
|---|---|---|
| S — shared structure | #4986 | skip link, footer `<nav>`, share head + wordmark card on all twelve, static titles instead of "Loading.", doors underlined, RSS + podcast alternates, tap targets |
| J — shared JS | #4987 | the goal-anchored chart frame, the dek printed as served, one recovery unit, the Food dot, trend rows with value + day, the call page rendered once, "Level 12", the coach not-found doors, the held-week line bound to served status |
| E — engine | #4989 | one walking number (the edition's week block), one guess sentence served from one place (`record_words`), served units, the sleep row on the pulse row, the chronicle's own state (`chronicle.latest.status`), `observed_on` |
| A — front + start | #4992 | the two drafted premise sentences (marked draft; #4590), no null coaches heading, one sayable guess sentence, the latest chapter first, Start's chapter doors with their own window's change, Follow on Start, the mark's floor |
| B — story, coaches, week, day | #4991 | the frame sentence, the newest published episode plays, lagging records say their day, a next date on each page, the day's absences said |
| D — sheet, built, appendix, call/coach copy | #4990 | sheet record rows + the hold note, built without the picture (5.5 screens), appendix jump list + groups, a bet's unit, a coach standfirst |

## After round 1 — the fresh pair (render `a673b6eeb`, same pinned clock)

G9 capped **voice** at B on front and start because both carry the two draft-marked premise sentences, pending the owner's recording (#4590), and did not penalise the draft a second time.

| Page | G9 clarity | G9 truth | G9 calm | G9 voice | G10 design | G10 dark | G10 a11y | G10 numbers | G10 North Star |
|---|---|---|---|---|---|---|---|---|---|
| front | B | B | B | B (capped) | B | B | B | B | B |
| start | A | C | A | B (capped) | C | C | B | C | B |
| story | B | B | B | B | B | B | B | B | B |
| coaches | B | B | B | B | B | B | B | A | A |
| week | B | A | A | B | B | B | B | A | B |
| day | B | C | A | C | B | B | B | C | B |
| trend | B | A | A | A | B | B | B | B | B |
| call | C | B | B | B | A | A | B | B | A |
| coach | B | A | A | A | B | B | B | A | B |
| sheet | B | C | A | B | B | B | B | B | B |
| built | A | C | B | B | B | B | B | B | B |
| appendix | A | A | B | A | B | B | B | A | B |

What the pair found that round 1 had not, or that round 1 left:

- **Start, truth C / numbers C (both graders):** the chapter rows' weekly deltas (0.8 / 2.3 / 3.1 / 2.5) are first-to-last weigh-in *inside* each window, while the chapters' own stats lines say 8.4 / 3.9 / 2.6 / 3.5 and the listed weights fall 3.9 / 2.7 / 3.4 between rows — one measure per row is the fix. Also the in-SVG chart labels render at roughly 6 px on a 390 px frame (design C): move them into `ck-ends`.
- **Day, truth C / numbers C:** the 168-vs-90 walking figure is still on the fixture (the engine fix is in #4989; no fixture carries 90), and "38 days" (the Notion journal, `character.json`) still sits beside "since September 23" (`/api/decisions`) — one word, two journals.
- **Built, truth C:** "Matthew approves one thing by hand: a change to what the programs are permitted to do" contradicts front, start, story and week, which all say each chapter and podcast publishes once he approves it. G9 ranks this the site's first fix: it is the human-in-the-loop claim the whole site rests on, stated two ways.
- **Call, clarity C:** 8 listed + 55 earlier + 115 without a page is 178, not the 183 every other page prints (a bet counts once per coach; the page does not say so); four kinds of call appear for the first time unexplained in one sentence.
- **Coaches, numbers A / North Star A:** every number traces (76 = 19+8+18+13+8+9+1; 183 = 46+36+35+27+20+12+7; 42% = 76/183). The record track is now grey — if that is the deliberate result-neutral choice (it is), record it in the kit so it is not read as an off-kit override.
- **Call, design A in both themes:** "the cleanest layout on the site in both themes."
- **Sheet, truth C:** three statements within one screen disagree on whether metabolic health counts (left out · still counts · cannot be scored yet shows Level 1). The hold note from #4990 says the truth; the composite still includes it — the engine's `composite_note` call, below.
- **Week:** the filled accent dot on "Weight down faster than planned" — the served verdict is a distinct state from going-well, and a filled accent dot is a colour carrying a claim the rule itself qualifies.

G10's deterministic floor after the fixes: axe serious/critical 0 on all 24 renders; skip link, `<main>` and `<nav>` present on all twelve; `og:image` on all twelve. Not verified by either grader (no DOM or keyboard in the bundle): heading order beyond text order, focus ring per widget, the `<summary>` hit height, SVG accessible names.

## Screens per page, before → after round 1

The owner's bar is ~3.5 screens for a reader page (the 2026-10-03 clean-look ruling; the kit gate's per-page budgets); built and appendix carry their own budgets (the appendix is the ruled footnote for retired pages, 2026-10-04).

| Page | Before | After | Note |
|---|---|---|---|
| front | 3.65 | 3.81 | the share head, the frame sentence and the chapter row first add; the null coaches heading goes |
| start | 3.49 | 3.71 | Follow block added |
| story | 2.89 | 3.41 | the newest published episode's player and the held row |
| coaches | 3.68 | 3.77 | a next-to-settle row |
| week | 2.66 | 2.57 | the duplicated "went right" row goes |
| day | 2.26 | 2.42 | the standfirst and the said absences |
| trend | 1.55 | 1.59 | values and days on every row |
| call | 3.92 | 3.43 | the call said once; the comparison as rows |
| coach | 1.00 | 1.38 | the not-found state lists the eight doors (the populated state is still unobserved — the harness passes no `?c=`) |
| sheet | 3.47 | 3.14 | record rows instead of formula prose |
| built | 6.54 | 5.50 | the picture gone; still long against its own bar |
| appendix | 9.35 | 9.88 | jump list added; length is by ruling |

## What stays open

**Resolves at the post-deploy recapture** (served data changed in #4989 after the fixtures were captured; the graders could only see the old fixture): the 168-vs-90 walking number on front/week/day/trend; the one guess sentence (`record_words`) on front/start/coaches/week/call; units on the bet thresholds and recovery; the chronicle's own held/published state on start/story (the live premise moved after capture — week 6 published 2026-10-18T04:29Z — so the held-week lines graded here are against a fixture the live site has already left); `observed_on` on the lagging coach records. The kit gate re-runs on the recaptured fixtures with ≥ 0.1 screen headroom per page before #4988 leaves draft.

**The owner's items** (not a lane's to close):
- **#4590** — the two premise sentences on front and start are drafts, marked as such; G9 capped voice at B on both pages until his recorded words replace them.
- **#4646** — the daily mark (`ck-mark`) is a thirteenth component he has not approved (G3, G10 both name it), and the link-preview image that changes daily; round 1 shipped a static wordmark card so the unfurl is no longer empty.
- **#4587** — five real readers before cut-over; nothing in this file substitutes for it (ER-05).
- **The sheet engine's `composite_note`** — metabolic health is on coverage hold at 15% coverage yet its score feeds the composite (mean of six including it). Either exclude held areas from the composite (engine change) or keep saying it counts on a thin score; the page now says the latter, the ruling is his.
- The day page's first-person static headings beside third-person served sentences (D4), and built's "In his words" passage (approve it, then it moves under the hero).

**Kit-ceiling items** (a page cannot earn the grade inside the kit as it stands): the start chart's labels inside the SVG (`ck-ends` is the kit's answer); built at 5.5 screens with every section one idea — the bar is ~3.5; the coach page's populated state, unobserved in both rounds until the render harness passes `?c=<id>`; the trend index, honest but inert until a chart is one tap in; the appendix at 9.9 screens by ruling.

**Still on the fix list for round 2** (verified by the fresh pair, no lane yet): the built approval sentence; the start chapter-row measure; the call page's 178-vs-183; the "simple guess" defined once on coaches; the week page's faster-than-planned dot; the EP5 row's separator; the story accent badge gated on freshness (`chapter.state` is "stale" at 11 days); the coach record column wrap at 390 px.

## Carried forward from the 2026-06-21 review

R-01…R-08 of the June pass graded a site that no longer exists (the four-door v4). None is reopened here; the class behind R-04 (one quantity, two roundings one tap apart) is the class behind this review's top defect, and the cross-page number check is now a grader's whole lens (G5, then G10 numbers) rather than a tolerance in `qa/site_review_bindings.py`.
