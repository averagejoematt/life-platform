# R3 — Content inventory for the v7 redesign of averagejoematt.com

Written 2026-09-26 ~13:00 PT, read-only. Corpus: the 91 `index.html` under `site/` at worktree `av-plan` (7d25556c8); live JSON saved in `scratchpad/b2/` (fetched 04:40Z and 16:46Z on 09-26) and `scratchpad/coachvoice/` (19:31Z); the 25 fold/body dumps in `scratchpad/grade/`. Every number below names its field. Nothing was fetched, deployed or written outside this file. "Day 21" = `journey.day_n 21`, genesis `2026-09-06`.

Two facts that frame all three parts:
- The site serves **two front doors** (`/` and `/cockpit/`), **two coaching doors** (`/coaching/`, `/coaching/read/`), **two team pages** (`/coaching/team/`, `/coaching/coaches/`), **two character explainers** (`/method/character/`, `/method/game/`), **two platform-stats pages** (`/method/platform/`, `/method/tools/`) and **two weight pages** (`/data/physical/`, `/method/results/`). Twelve pages, six things.
- The nav-reachable set is 25 (`docs/SITE_MAP_AND_INTENT.md`, `NAV_REACH_CEILING`); 66 of the 91 are reachable only by URL or the footer. Taps below: door = 1, door sub-page = 2, footer-tier = F (one footer tap from any page), unlisted = ∞ (URL only).

---

## PART 1 — The inventory

Legend: **SPINE** must exist as itself · **FOLD → target** its one useful thing moves · **ARCHIVE** served, unlinked, nobody would notice · **KILL** misleading or empty.

| # | slug | what it is, six words | data it actually shows | taps | verdict | reason |
|---|---|---|---|---|---|---|
| 1 | `/` | landing: claim, friends' read, three doors | `/api/journey` (313.8 lb, −13.5, n=13), `/api/character`, `/api/journal_quotes`, `/api/cycle_compare` | 0 | **SPINE** (absorbs cockpit) | one front door, and it must be the daily instrument, not a landing |
| 2 | `/cockpit/` | today in three questions, then the level | `/api/snapshot` (vitals+journey+character), `/api/routine`, `/api/coaching-dashboard`, `/api/changes-since`, `/api/nutrition_overview`, `/api/observatory_week`, `/api/presence`, `/api/fingerprint`, `/api/experiments` | 1 | **FOLD → `/`** | the best page on the site (grade B, 10-s 5) is the second door, not the first |
| 3 | `/data/` | hub of 14 topic tiles | `/api/pulse` + the tile endpoints | 1 | **SPINE → `/numbers/`** | the hub becomes the page; topics become sections |
| 4 | `/data/physical/` | every weigh-in and the provisional rate | `/api/physical_overview`; journey: 13 weigh-ins 09-06→09-26, −4.36/wk CI [−4.74, −2.75], `rate_provisional true`, `projected_goal_date null` | 2 | FOLD → `/numbers/` weight | the headline number; also on `/` — one home |
| 5 | `/data/sleep/` | last night by two devices, recovery | `/api/sleep_detail`: night of 09-25 Whoop 8.6 h/84, Eight Sleep 8.6 h/96, recovery 77 %, 21-d avg 73.9 | 2 | FOLD → `/numbers/` sleep | keep the two-instrument honesty (Part 2 #6) |
| 6 | `/data/training/` | gym sessions, walks, steps, lifts | `/api/training_overview`: 33 sessions/30 d, 19 strength, 14 walks, 6.3 mi, 2,245 steps/d n=20 | 2 | FOLD → `/numbers/` training | the walk numbers need explaining, not another page (Part 2 #10) |
| 7 | `/data/nutrition/` | calories, protein, days logged | `/api/nutrition_overview`: `days_logged 20`, `avg_protein_g 153.3`, floor 170 hit 7/20, target 190 hit 2/20, deficit refused | 2 | FOLD → `/numbers/` food | carries the two hardest honest lines on the site (deficit refused, no sensor) |
| 8 | `/data/labs/` | blood tests, flagged markers first | `/api/labs`: `latest_draw_date 2026-04-03`, 152 markers, `flagged_count 26`, `draws_this_cycle 0`, 156 days before genesis | 2 | FOLD → `/numbers/` labs | one dated line ("last test Apr 3, none scheduled") plus a collapsed printout |
| 9 | `/data/vitals/` | today's weight/HRV/recovery/steps | `/api/pulse` (same fields as `snapshot.vitals`) | ∞ (still on the "ALL 14 TOPICS" rail) | **KILL** | duplicate of the cockpit's "Last night?" block |
| 10 | `/data/glucose/` | blood sugar — no sensor worn | `/api/glucose`; `source_freshness.apple_health.datatypes.cgm last_seen 2026-08-27`, `dark true`, 30 days | ∞ (unlisted; home still links it) | **KILL** | a page of "NO SENSOR"; its one line moves to the `/numbers/` absence strip |
| 11 | `/data/autonomic/` | nervous-system balance vs baseline | `/api/autonomic_balance`; vitals `hrv_ms 46.5` vs `hrv_avg_ms 41.0 n=21` | ∞ | FOLD → `/numbers/` sleep | one sentence beside HRV |
| 12 | `/data/zone2/` | easy-cardio minutes vs 150 | `/api/zone2`; `training.z2_weekly_avg_min 625` vs `public_stats.training.zone2_this_week_min 59` | ∞ | FOLD → `/numbers/` training | two numbers for one quantity (625 vs 59) — pick the field, then one line |
| 13 | `/data/mind/` | mood, journal, meditation | `/api/mind_overview`; `pulse.glyphs.journal.gap_days 17`; `character.pillars.mind.absence.days_dark 17` (notion last log 09-09) | ∞ | FOLD → `/numbers/` mind | the "17 days silent" line is a headline (Part 2 #3), not a page |
| 14 | `/data/habits/` | daily habits kept | `/api/habits`; `character.pillars.mind.absent_behaviors [t0_habit_compliance, t1_habit_compliance]`; `public_stats.platform.tier0_streak 0` | ∞ | FOLD → `/numbers/` mind | one row |
| 15 | `/data/reading/` | books finished, shelf, ideas kept | `/api/reading_overview`; mind drivers `dragging: reading_practice` | ∞ (unlisted) | ARCHIVE | no served reading activity in the corpus this cycle |
| 16 | `/data/vices/` | days held, named privately | `/api/vice_streaks`; mind `no_data: vice_control` | ∞ | ARCHIVE | the engine reports no vice data; privacy-sensitive; nobody would notice |
| 17 | `/data/ledger/` | bounties earned, punishments donated | `/api/ledger` | ∞ (unlisted) | ARCHIVE | already off the rail by intent (#1109); no activity served |
| 18 | `/data/horizons/` | Mind coach's weekly media pick | `/api/horizons` | ∞ | ARCHIVE | niche; no reader question leads here |
| 19 | `/data/character/` | the RPG sheet: 7 pillars, XP | `/api/character`: level 7, composite 41.6 = mean of 6/7, nutrition pillar **1.6/100** with `absent_behaviors [calorie_adherence, protein_total, …]` on a day `nutrition_overview` shows 20/20 logged, 182 g | ∞ | FOLD → `/numbers/` (collapsed, plain key) | the panel demoted it; it still contradicts MacroFactor on its face |
| 20 | `/data/badges/` | every mark, earned ones lit | `/api/achievements` | ∞ | **KILL** | a mechanic of the demoted level; no reader asked |
| 21 | `/data/wall/` | one deterministic mark per day | `/api/wall` | ∞ | ARCHIVE | the survival strips (#83) already show every attempt, every day |
| 22 | `/coaching/` | the door: today's read, the week's call | `/api/coaching-dashboard` (priority `as_of_day_n 16`, `open_actions []`), `/api/coach_team`, `/api/coach_docket` (2 open bets), `/api/calibration` | 1 | **SPINE → `/coaches/`** | the moat, if the coaches read as characters (Part 3) |
| 23 | `/coaching/read/` | the same read, again | same JS, same endpoints as #22; title "What the AI board is saying… today and this week" | 2 | **KILL** | duplicate door |
| 24 | `/coaching/by-coach/` | each coach's dossier and timeline | `/api/coach/{id}`: `stance`, `daily`, `recent_outputs[]` (dated), `dossier.commitments[]`, `report_card` | 2 | FOLD → `/coaches/<id>/` | the only place the full read + dated asks live; keep as the per-coach serial |
| 25 | `/coaching/scorecard/` | every call graded | `/api/predictions`: 322 total, 37 decided (18/19), 113 pending, 169 observational; 16 of the latest 50 `pre_registered` | 2 | FOLD → `/coaches/` record | with the double-count fixed first (Part 2 #4) |
| 26 | `/coaching/team/` | who the coaches are, cast sheet | `/personas.json`, `/api/coaches` (roster of 8), authored `trait_scores` | ∞ | FOLD → `/coaches/` one line each | the bios belong under the character, not on a page of their own |
| 27 | `/coaching/coaches/` | "The Team" — a second time | same as #26 | ∞ | **KILL** | duplicate of `/coaching/team/` (both titled "The Team") |
| 28 | `/coaching/lab-notes/` | the AI's read beside how it felt | `/api/field_notes`: 3 weeks (W36–W38), `has_matthew_response false` ×3 | 2 | FOLD → `/week/` | the "how it felt" half has been empty all three weeks; the AI half is the weekly write-up's sidebar |
| 29 | `/coaching/qa/` | ask the board a question | `/api/board_question`, `/board_answers/answers.json`; `ladder_counts`: subscriber 1, predictor 0, contributor 0 | ∞ | ARCHIVE | no evidence of readers asking; keep the endpoint, drop the page |
| 30 | `/protocols/` | what he takes and tries | `/api/supplements`, `/api/protocols`, `/api/experiments`, `/api/challenges`, `/api/discoveries` | 1 | **SPINE → `/tries/`** | with the decision log folded in (#31–#35) |
| 31 | `/protocols/supplements/` | what he takes, what it should move | `/api/supplements` (38 KB; withdrawn citations marked, #1892) | ∞ (unlisted) | FOLD → `/tries/` | the honest citations survive as a collapsed list |
| 32 | `/protocols/protocols/` | active deliberate interventions | `/api/protocols` | ∞ | FOLD → `/tries/` | same door, sub-URL |
| 33 | `/protocols/experiments/` | what he'd try next | `/api/experiments`: 67 library entries, statuses only `available`/`backlog` — **no active experiment on Day 21** | 2 | FOLD → `/tries/` | the honest line ("nothing formal is running") is one sentence |
| 34 | `/protocols/challenges/` | time-boxed challenges, XP | `/api/challenges` | ∞ (unlisted) | ARCHIVE | already unlisted; XP mechanic |
| 35 | `/protocols/discoveries/` | hypotheses and findings the engine surfaces | `/api/discoveries`; `calibration.strata.hypotheses n=0, insufficient_data` | ∞ | **KILL** | empty by the engine's own count |
| 36 | `/story/` | the weekly write-up hub | `/journal/posts.json` (6 posts: 3 weekly + 3 prologue; latest "The Silence and the Signal" 09-22, 1,114 words), `/api/content_cadence` (next 09-30) | 1 | **SPINE → `/week/`** | graded A; the only dated return trigger on the site |
| 37 | `/story/chronicle/` | the write-ups, listed | same `posts.json` | ∞ | FOLD → `/week/` | the hub IS the list |
| 38 | `/story/journal/` | his own words, first person | `/journal/blog.json`, `/api/journal_quotes` | 2 | FOLD → `/week/` sidebar | his voice has been silent since 09-09 (`notion last_log_date`); say so where the write-up is |
| 39 | `/story/panel/` | the weekly two-host podcast | `/panelcast/episodes.json`; body says "in final review" — no episode since the 09-04 prologue (grade sweep row 10) | 2 | FOLD → `/week/` | zero episodes this cycle; one honest line under the write-up |
| 40 | `/story/about/` | who he is, in his words | static | 2 | **SPINE → `/about/`** | the friends' first question |
| 41 | `/story/attempts/` | every start, counted | `/api/cycle_compare`, `/api/survival`: 16 prior cycles, 0 reached day 30, longest 13 days | 2 | FOLD → `/misses/` | the most gripping page on the site is two taps down and titled like a spreadsheet (Part 2 #1) |
| 42 | `/story/timeline/` | level-ups and milestones | `/api/journey_timeline` | ∞ | FOLD → `/misses/` | milestones of this attempt beside the record of the others |
| 43 | `/story/build/` | engineering dispatches | `/story/build/beats.json`, `stack.json`, `schema.json` | 2 (footer) | FOLD → `/about/` | builder's log; footer-tier |
| 44 | `/story/build/agent-review/` | the remediation agent's record | static | ∞ | ARCHIVE | builder's instrument (ADR-064: it merges nothing) |
| 45 | `/story/agents/` | watchdog agents and what they caught | `/api/agent_activity` | ∞ | ARCHIVE | builder |
| 46 | `/story/diary/` | video-diary shelf, where cleared | `/api/diary_shelf` | ∞ | ARCHIVE | no cleared entries evident in the corpus |
| 47 | `/story/broadcast/` | his posts, self-hosted | `/api/broadcast` | ∞ | ARCHIVE | nobody would notice |
| 48 | `/story/membrane/` | what I said, where it went | `/api/membrane` | ∞ | ARCHIVE | builder concept, builder word |
| 49 | `/story/theme-river/` | journal themes across the attempt | `/data/theme_river.json`: `state "empty"`, `n_entries 0`, `n_days 0` | ∞ | **KILL** | a chart of nothing |
| 50 | `/journal/essays/org-chart-of-one/` | one essay: one human, N agents | static | ∞ | FOLD → `/about/` | it is the "how it's built" essay |
| 51 | `/method/` | how every number is made | evidence hub; lead = wrong | F | FOLD → `/about/` | footer-tier stays footer-tier |
| 52 | `/method/character/` | the level explained | editorial | F | FOLD → `/about/` | one explainer (with #57) |
| 53 | `/method/game/` | the rulebook: XP, streak gates, tiers | `/character_sheet.json` | ∞ | FOLD → `/about/` | second explainer of the same system |
| 54 | `/method/wrong/` | every time the AI was wrong | `/api/wrong`: 39 obituaries, validator 2,989 claims / 6 caught, 25 recent refutations, `effect_fits as_of 2026-07-19` | ∞ | **SPINE → `/misses/`** | the honesty page; today it is unreachable from the nav |
| 55 | `/method/survival/` | odds this cycle reaches day 30 | `/api/survival`: `p_reach_30_pct null`, ceiling 6 %, `longest_run_days 13`, cycle 17 strip 21/21 | ∞ | FOLD → `/misses/` | Part 2 #1 lives here, unlinked |
| 56 | `/method/postmortems/` | what each dead cycle taught | `/api/survival` | ∞ | FOLD → `/misses/` | same endpoint as #55 |
| 57 | `/method/cycles/` | cycle vs cycle, same window | `/api/cycle_compare` | ∞ | FOLD → `/misses/` | |
| 58 | `/method/calibration/` | Brier per coach, reliability curve | `/api/calibration`: platform n=147, 70.7 % [62.9, 77.5], Brier 0.1908, `not_yet_skillful` | ∞ | FOLD → `/coaches/` record | the calibration record belongs on the coach, not under the hood |
| 59 | `/method/predictions/` | the model's forward calls | `/api/predictions` (same as #25) | ∞ | FOLD → `/coaches/` record | duplicate of the scorecard |
| 60 | `/method/board/` | the named AI experts — reads & roster | `/api/coaching-dashboard` (same as #22) | ∞ | **KILL** | third coaching door |
| 61 | `/method/voicefidelity/` | can a blind panel tell coaches apart | `/api/voice_fidelity` | ∞ | ARCHIVE | builder instrument |
| 62 | `/method/verify/` | cross-device agreement, raw sample | `/api/device_agreement` | ∞ | FOLD → `/numbers/` | the Whoop-vs-Eight-Sleep line (Part 2 #6) |
| 63 | `/method/pipeline/` | which sources flow, which are dark | `/api/source_freshness`: 11 fresh / 1 stale / 1 paused; CGM dark 30 d, BP 17 d, State of Mind 18 d, Garmin paused 103 d | ∞ | FOLD → `/numbers/` absence strip | "what he skips and what the machine can't see" in one strip |
| 64 | `/method/data/` | every source, what, how often | `/data/data_sources.json` | ∞ | FOLD → `/about/` | with gear (#88) |
| 65 | `/method/platform/` | architecture by the numbers | `/api/platform_stats`: 86 tools, 20 sources, 106 lambdas | ∞ | FOLD → `/about/` | |
| 66 | `/method/tools/` | the MCP tools Claude uses | `/api/platform_stats` (same as #65) | ∞ | **KILL** | duplicate |
| 67 | `/method/build/` | build-in-public essay | editorial | ∞ | FOLD → `/about/` | |
| 68 | `/method/methodology/` | N=1, correlation engine, confidence | editorial | ∞ | FOLD → `/about/` | |
| 69 | `/method/cost/` | what running this costs | `/api/platform_stats` | ∞ | FOLD → `/about/` cost | with #70/#71 — one money page |
| 70 | `/method/receipts/` | the live bill and the tier | `/api/receipts`: MTD $102.74, projected $118.98 of $215, tier 0, AI $2.74/d, non-AI $1.53/d | ∞ | FOLD → `/about/` cost | Part 2 #7 |
| 71 | `/method/inference/` | every AI call, priced | `/api/inference_receipt` | ∞ | FOLD → `/about/` cost | |
| 72 | `/method/results/` | outcomes to date | `/api/journey` (same as `/` and #4) | ∞ | **KILL** | third weight page |
| 73 | `/method/explorer/` | today's raw record | `/api/snapshot` (same as #2) | ∞ | **KILL** | a JSON dump of the cockpit |
| 74 | `/method/intelligence/` | cross-source correlations | `/api/correlations`; `what_changed.newly_unlocked`: hrv↔recovery r 0.89 n=89, rhr↔recovery r −0.73 | ∞ | **KILL** | its strongest "findings" correlate Whoop's recovery score with the inputs Whoop computes it from |
| 75 | `/method/scenarios/` | pick a day, see what followed | `/api/scenarios` | ∞ | ARCHIVE | enthusiast tool |
| 76 | `/method/benchmarks/` | vs age-band and centenarian targets | `/api/benchmark_trends` | ∞ | ARCHIVE | enthusiast |
| 77 | `/method/biology/` | genome risk by category | `/api/genome_risks` (Tier-2 identifiers owner-only, #1943) | ∞ | ARCHIVE | nobody asked; privacy-adjacent |
| 78 | `/method/kitchen/` | meal intelligence from CGM + macros | editorial: "fills as data accrues"; CGM dark 30 d | ∞ | **KILL** | empty by construction |
| 79 | `/method/eyeball/` | AI meal-photo error, graded | `/data/eyeball_calibration.json`: `state "empty"`, `n_days 0`, `as_of 2026-07-24` | ∞ | **KILL** | graded on zero photos |
| 80 | `/method/mirror/` | your Whoop CSV on my instruments | `/data/mirror_distributions.json` (browser-side); `ladder_counts.replicator 0` | ∞ | ARCHIVE | a good tool with zero users; serve, don't front |
| 81 | `/method/grade-your-coach/` | paste your coach's calls, grade them | `/data/calibration_demo.json` | ∞ | ARCHIVE | same rung, same count |
| 82 | `/method/ask/` | put a question to the data | ~20 endpoints, interactive | ∞ | ARCHIVE | no evidence of use; endpoint-heavy |
| 83 | `/method/registry/` | every stat's formula and limits | `/api/methods` + `/api/journey`, `/api/calibration`, `/api/coach_team`, `/api/vitals` (3,640 words) | ∞ | ARCHIVE | the builder's page; linked from `/about/` as a footnote, never fronted |
| 84 | `/method/state/` | how the build is going | `/data/platform_state.json` `generated_at 2026-09-07` (19 days stale) | ∞ (unlisted) | ARCHIVE | owner-only audience by its own doc; stale |
| 85 | `/method/fingerprint/` | how a day becomes its mark | editorial | ∞ | ARCHIVE | goes with the wall (#21) |
| 86 | `/method/tone/` | three coach registers, prompts verbatim | static | ∞ | ARCHIVE | builder |
| 87 | `/mind/` | 701-byte redirect stub | `mind_redirect.js` → `/data/reading/` | ∞ | **KILL** | not a page |
| 88 | `/gear/` | every device behind the data | static list; `source_freshness.summary` 13 sources | F | FOLD → `/about/` | with #64 |
| 89 | `/subscribe/` | follow by email | `/api/sub_count` (1), `/api/ladder_counts` | F | **SPINE** | graded A; one promise, one field, one honest counter |
| 90 | `/subscribe/confirm/` | double-opt-in landing | — (title still says "The Measured Life") | ∞ | SPINE (utility state) | fix the name |
| 91 | `/privacy/` | policy + AI disclaimer + permanence | `continuity.json`, `manifest.json` | F | **SPINE** (utility) | legal; one URL |

### Counts

**SPINE 10** (`/`, `/data/`, `/coaching/`, `/protocols/`, `/story/`, `/story/about/`, `/method/wrong/`, `/subscribe/`, `/subscribe/confirm/`, `/privacy/`) · **FOLD 43** · **ARCHIVE 23** · **KILL 15** = 91 (counted by script over the table). `/coaching/by-coach/` is a FOLD in the table and becomes the per-coach template (page 5 below).

### The proposed site — 9 pages

| # | page | first screen | absorbs |
|---|---|---|---|
| 1 | **`/` — Today** | Day N in words · How's the week (weight, n, provisional rate with CI) · Last night (two devices) · Today's session · yesterday's protein vs floor · the one ask (from the coach who asked it, dated) · what he skipped (journal N days, no sensor) | `/cockpit/`, `/data/vitals/`, `/method/explorer/`, `pulse`, `changes-since`, `forecast` |
| 2 | **`/week/` — This week's write-up** | the latest chronicle's first paragraph, dated in words, "next: Wednesday Sep 30" · the week's call (Eli) labelled weekly with its age · the podcast when one exists · his own words when he writes | `/story/*` (hub, chronicle, journal, panel), `/coaching/lab-notes/`, `field_notes` |
| 3 | **`/numbers/` — His numbers** | one number per topic above a chart rail: weight · sleep · training · food · labs · mind — then **the absence strip**: journal 17 d, CGM none, BP 17 d, State of Mind 18 d, Garmin paused (from `source_freshness` + `character.absence`) — then the engine's score, collapsed, with a key | all 14 `/data/*` topics, `/method/pipeline/`, `/method/verify/` |
| 4 | **`/coaches/` — The staff** | one card per coach: name, what they're on about (thread), last said (date), the ask (with "asked N times since <date>"), record "N checked, K held up" from ONE producer, open bets with resolution dates | `/coaching/*` (door, read, scorecard, team ×2, qa), `/method/board/`, `/method/calibration/`, `/method/predictions/`, `coach_docket` |
| 5 | **`/coaches/<id>/` — the serial** (one template, 8 URLs) | the thread as a dated timeline: what I said → what happened → what I retract/keep; the commitments ledger deduplicated; the learnings verbatim | `/coaching/by-coach/` |
| 6 | **`/tries/` — What he takes and tries** | what's running (today: nothing formal — 67 library entries, 0 active) · supplements with what each should move · **the decision log in his words** (3 of 6 overridden; `api_decisions`) | `/protocols/*` ×6, `/method/scenarios/` |
| 7 | **`/misses/` — What went wrong** | "Day 21 is the farthest he has ever got" (survival strips, 16 prior cycles) · the obituaries (39) · the validator's catches · this cycle's milestones | `/method/wrong/`, `/method/survival/`, `/method/postmortems/`, `/method/cycles/`, `/story/attempts/`, `/story/timeline/` |
| 8 | **`/about/` — Who he is, how it's built, what it costs** | his own words · one paragraph on the setup · the engine's score explained (one explainer) · the devices · the bill ($102.74 MTD, $215 ceiling) · build log · methodology · registry link | `/story/about/`, `/gear/`, `/method/*` editorial + cost pages (character, game, build, methodology, platform, tools, cost, receipts, inference, data), `/story/build/`, the essay |
| 9 | **`/subscribe/`** | as it is | `/subscribe/confirm/` as a state |

Utility URLs outside the count: `/privacy/`, `/404`. Everything ARCHIVE keeps its URL and leaves the nav, the footer and the sitemap.

---

## PART 2 — The ten most gripping true things (as served, 2026-09-26)

**1. Day 21 is the farthest he has ever got.**
Headline: *Sixteen starts, none reached a month. This one just passed the old record.*
Numbers: `survival.n_prior_cycles 16` · `reached_horizon_n 0` · `longest_run_days 13` · `collapsed_before_horizon_n 7` · `censored_before_horizon_n 9` · cycle 17 `engaged_days 21` of `window_days 21`, strip `█████████████████████` · `p_reach_30_pct null` (the 6 % is served as a ceiling, "the prior's residue, not evidence") · `collapse_definition`: 4+ days with no weigh-in, food log or journal entry · `current_silent_days 0`.
Why it grips: the whole site exists because he keeps restarting; the engine has a page that handicaps its own human and today that page says the streak is unprecedented — and refuses to give odds. The write-up of 09-08 is titled "The Fifteenth Reset, or: What the Body Remembers" (`journal_posts[2].title`).
Where: `/method/survival/` (∞, unlinked) and `/story/attempts/` (2 taps, titled "Every start, counted"). Not on `/`.

**2. Down 13.5 lb in 20 days — and the site refuses to say when he'll arrive.**
Headline: *327.3 to 313.8 in thirteen weigh-ins; the rate is real, the finish line is withheld.*
Numbers: `journey.start_weight_lbs 327.3` (09-06) → `current_weight_lbs 313.8` (`last_weighin_date 09-26`) · `lost_lbs 13.5` · `weighin_count 13`, `weighin_span_days 20` · `weekly_rate_lbs −4.36`, CI `[−4.74, −2.75]`, `rate_provisional true` · `projected_goal_date null` · `remaining_lbs 128.8`, `progress_pct 9.5`. The first six days had one weigh-in (`weight_progress`: 09-06, then 09-12). Contradiction still live: `public_stats.journey` (daily-brief-lambda, 09-25) serves `rate_provisional false`, `projected_goal_date 2027-04-20`, CI `[−4.96, −3.83]` — two producers, two rates (#4184).
Why: the honest refusal ("no dated projection yet", `/data/physical/` fold) is the site's character; the second producer undercuts it on the same day.
Where: `/` (0), `/cockpit/` (1), `/data/physical/` (2), `/method/results/` (∞).

**3. Twenty of twenty days logged — while three coaches say he went dark.**
Headline: *The food log never stopped. The coaches' memory of a gap did.*
Numbers: `nutrition_overview.nutrition.days_logged 20`, `nutrition_trend` has a row for every date 09-06→09-25, `lag_days 1`, `stalled false`, `latest_date 09-25` 182 g / 1,761 kcal. Against it: Webb `position_summary` 09-25 "The food log went dark after September 19th"; Webb `analysis` 09-26 "The six-day logging silence since September 19th"; Patel `recent_outputs` 09-24 "meal logging has been absent since 2026-09-10"; Brandt 09-14→09-20 "Restart food logging immediately" ×5; Brandt `daily` "zero food logs"; Reeves 09-13 "the two-day logging silence". Patel holds 15 `pending` commitments that are the same "restart meal logging". The character engine agrees with the coaches, not the log: `character.pillars.nutrition.raw_score 1.6`, `absent_behaviors [calorie_adherence, protein_total, protein_distribution, consistency]` on the same day.
Why: this is the platform's stated thesis (memory over state) failing in public — a false premise stated once became an open thread fed back every morning (`analysis.thread_reference`). The reader sees the accusation on `/coaching/` one tap from home and the refutation on `/data/nutrition/` two taps away, and nothing connects them.
Where: `/coaching/` (1), `/coaching/by-coach/` (2), `/data/nutrition/` (2).

**4. What he skips, in five vocabularies.**
Headline: *He stopped writing on September 9. Five pages say so, none the same way.*
Numbers: journal — `pulse.glyphs.journal.gap_days 17`, `character.pillars.mind.absence.days_dark 17`, `last_log_date 2026-09-09`, `stale_hours 336`; the coaches: Reeves "six-day journaling silence" (stance 09-20), "eleven days" (`public_read` 09-26), Eli "10 gap days" (09-21). CGM — `source_freshness.apple_health.datatypes.cgm last_seen 2026-08-27`, `dark true`, 30 days; Patel 09-24: "the CGM is active and the sensor is accumulating data"; Brandt `daily`: "The glucose trace arrives tomorrow". Blood pressure dark 17 d (last 09-09); State of Mind dark 18 d (09-08); Garmin `paused`, `days_dark 103`; `food_delivery` last 2026-03-28. Field notes: `has_matthew_response false` ×3 (W36–W38). Habits: `tier0_streak 0`; `brief_excerpt` "9 missed morning habits". The staff's standing ask — a morning felt-sense note — has no channel: Park "sixteen days of unmet morning-check requests" (09-26); her ledger `commitment_counts held 40 / kept 1 / pending 30`.
Why: the misses are the honest story and the site already has every number — but as `gap_days`, `days_dark`, `dark_datatypes`, `absent_behaviors` and prose counts that disagree (6, 10, 11, 17). One strip, one vocabulary, one count.
Where: `/method/pipeline/` (∞), `/data/mind/` (∞), `/cockpit/` (1, one line), `/coaching/by-coach/` (2).

**5. The nutrition coach is 80 % right, 0 % right, or 20-for-25 — depending on the page.**
Headline: *Three scorekeepers, one coach, three records.*
Numbers: `api_coaches.headline_stat` Webb "80 % hit-rate · n=25"; `api_wrong.predictions.by_coach` nutrition 20 confirmed / 5 refuted; `api_calibration.coaches[nutrition]` `n 5, confirmed 0, refuted 5, accuracy 0.0 %`, `calibration "over-confident"`. The 20 "confirmed" are one event: `dossier.learnings` holds "dispute docket resolved: total_calories_kcal_7day_avg >= 2200 on 2026-08-10" **20 times** (once per day 09-07→09-26); Brandt's side of the same bet is his 20 of 24 "refuted" — hence his served "12 % hit-rate · n=24". The bet resolved on **2026-08-10**, 27 days before this cycle began. Platform-wide: `calibration.platform n 147, accuracy 70.7 % [62.9, 77.5], brier 0.1908, skilled false`; `predictions.overall decided 37, confirmed 18, refuted 19`.
Why: the calibration record is the platform's proof of honesty (ADR-105), and the two coaches with the "best" and "worst" records owe both to one pre-cycle dispute re-graded daily. Every other coach is at n ≤ 17.
Where: `/coaching/scorecard/` (2), `/method/calibration/` (∞), `/method/wrong/` (∞), `/coaching/` (1: "37 predictions checked, 18 came true").

**6. The sleep coach has been wrong 10 times in 17 — and her position has not moved a word.**
Headline: *Ten misses, an "over-confident" grade, and a stance the engine wrote for her.*
Numbers: Park `report_card.track_record confirmed 7, refuted 10, decided 17, hit_rate_pct 41.2`; lifetime `n 25, 8/17, 32.0 %`, `calibration "over-confident"` (`api_calibration`). The misses: predicted recovery 66.2 ±17.9 for a night that came in **24** (09-11), 52.9 for a 73 (09-13), "predicted up, metric flat" ×2. What changed: `stance.how_my_read_changed ""`, `stance_history []`, `stance.source "ladder"` — her served headline ("At this stage the single biggest lever is total sleep and a consistent bedtime. Architecture can wait.") is the ladder's authored rung text (`stance.rung.read_of_him`), identical to `coach_team.huddle[0].read_of_him`. Her one live bet: recovery 24→94 was "genuine architectural improvement" (docket, vs Reeves, resolves 10-07 on `recovery_score_7day_avg >= 80`).
Why: the site promises coaches "quick to say she was wrong" (`trait_scores.note`) and serves a record that says otherwise — the calibration exists, the character never reads it.
Where: `/coaching/by-coach/` (2), `/coaching/scorecard/` (2).

**7. Two devices on one body disagreed by up to 8.5 hours a night — and the sleep coach's biggest claim rests on one of those nights.**
Headline: *The mattress saw 30 minutes; the wristband saw nine hours.*
Numbers (`sleep_detail.sleep_trend`, rows keyed by wake date): 09-11 Whoop 4.7 h vs Eight Sleep 2.1 h · 09-13 Whoop **9.0 h** vs Eight Sleep **0.5 h** · 09-19 Whoop 8.6 h vs Eight Sleep 1.7 h, deep 27.6 % (Whoop) vs 2.9 % (Eight Sleep) · 09-25 9.9 vs 10.0 (agree). `figure_scope.divergence null` — the payload has a slot for the disagreement and leaves it empty. Park's thread: `analysis_sleep.thread_reference` "27.6 % deep sleep … sits 1.8 SD above baseline but lacks thermal anchor" — the 27.6 % is the 09-19 row, the night the mattress recorded 1.7 h. Also: `sleep_start` is served in UTC; Eli's cross-domain note reads "median ~4:45 AM onset" against `avg_bedtime 10:31 PM`.
Why: "two instruments, both shown" is the right rule; the page shows both and never says they disagree, and a coach builds a hypothesis on the disputed night.
Where: `/data/sleep/` (2), `/method/verify/` (∞).

**8. From 24 % to 99 % in two weeks — and two coaches have staked their records on why.**
Headline: *The worst night and the best night of the experiment are thirteen days apart.*
Numbers (`sleep_trend`): night of 09-10 (row 09-11) recovery **24**, HRV 22.2, Whoop 4.7 h; night of 09-24 (row 09-25) recovery **99**, HRV 56.8, 9.9 h; last night 77, HRV 46.5, 8.6 h. Cycle baseline `sleep_detail.avg_recovery_window 73.9` (21 d), `vitals.hrv_avg_ms 41.0 n=21`. The forecast under-called the 9.9 h night (`forecast.resolutions_today`: point 7.4, [5.8–9.1], `covered false`); forecast coverage `78.5 % n=247`. The bet: `coach_docket.open[1]` Reeves "regression toward baseline after a floor event" vs Park "genuine architectural improvement", criterion `recovery_score_7day_avg >= 80 on 2026-10-07`, stakes frozen (Park brier 0.2507 n=20; Reeves 0.25 n=4).
Why: a real arc with a date and a verdict the code will write — the closest thing the site has to a plot.
Where: `/coaching/` "Where they disagree" (1), `/data/sleep/` (2); the resolution date is on no first screen.

**9. $102.74 this month, one subscriber.**
Headline: *Eight coaches, 106 functions, four dollars a day, an audience of one confirmed reader.*
Numbers: `receipts.month_to_date_usd 102.74` (09-26), `projected_month_end_usd 118.98` of `ceiling_usd 215` (55.3 %), `tier 0`, `ai_daily_usd 2.74`, `non_ai_daily_usd 1.53`, `recent_uniques 1116` (7 d; surge at 1,407). `sub_count.count 1`; `ladder_counts`: predictor 0, replicator 0, contributor 0. `platform_stats`: 86 tools, 20 sources, 106 lambdas.
Why: radical accessibility is the pitch; the number is small, public and unflattering, and it sits on two footer pages nobody reaches.
Where: `/method/receipts/`, `/method/cost/`, `/method/inference/` (all ∞); `/subscribe/` says "One subscriber so far" (F).

**10. Twenty-four workouts the AI planned that nobody did — and three of six calls the man overruled.**
Headline: *The training engine drafts; the human decides.*
Numbers: 24 routine drafts older than 7 days never committed or archived, all pre-genesis, kept the nightly `qa-smoke-warnings` lit; the 09-21 citation expired 09-22 (#4183; `qa_smoke_lambda.check_orphan_routine_drafts`, #3772: the soft-timeout "lands the draft and tells the client it timed out … one sat from 2026-09-08 with nobody knowing"). Today: `routine.status "draft"`, `pushed false`, archetype lower, 5 exercises / 11 sets, on a day `pulse.glyphs.lift` reads "Rest day". `api_decisions` (6 records): 09-23 switch to Upper/Lower — `followed false`, his note "i dont think i like this routine, i think i prefer PPL or WS4B3"; 09-19 skip lifting — `followed false`, "No I wanna do push"; 09-08 prepared lunch — `followed false`, "I was trying to solve the problem: Hey, I'm hungry now"; the 09-08 training record carries `</decision> <parameter name="followed">true` inside the served text (#4190).
Why: the man arguing with the machine, in his own words, is the most human content the platform holds, and it is served raw on `/protocols/experiments/` under a tool-call tag.
Where: the drafts are on no page (nightly QA only); the decisions on `/protocols/experiments/` (2).

**Also true and worth a line each:** the walks — `training.walking`: 14 walks, 823 min, avg HR 117, **6.3 mi total** at 21.5 min/mi (≈135 min of the 823 have distance); `z2_minutes_walking 762` vs `public_stats.zone2_this_week_min 59`; steps `daily_steps_trend` 9,653 on Day 1 then 940–3,578 (`avg 2,245 n=20`), which is the "36 % step contraction" Reyes has carried since 09-18 with three different number pairs (3,010→2,386 / 2,510→1,774 / 2,083→1,865) · zero formal experiments in the experiment (`experiments` 67 entries, all `available`/`backlog`; `calibration.strata.hypotheses n 0`) · the week's call is five days old with four wrong numbers (`weekly_priority as_of_day_n 16`: 316.9 lb, 3.7 lb/wk, 106.9 g/14 d, "zero Strava sessions") and the door now says so ("This read is 5 days old") · protein floor 170 hit 7 of 20 days, target 190 hit 2 of 20; 245 g on 09-13, 90 g on 09-15 · `predictions.overall observational 169` of 322 — half the "predictions" are not predictions · last blood test 156 days before Day 1, `draws_this_cycle 0`.

---

## PART 3 — The coaches as characters with memory

Corpus fields: `stance` / `stance_history` / `stance.how_my_read_changed`, `daily`, `recent_outputs[]` (dated `summary`), `dossier.{commitments, learnings, docket_positions, relationship, retracted, withheld}`, `report_card.{track_record, tuning_log}`, `analysis_<domain>.{analysis, public_read, thread_reference, elena_quote, key_recommendation}`. Person is judged on what a visitor is served (`position_summary` on `/coaching/`, `headline_read` + `daily` + `recent_outputs[].summary` on `/coaching/by-coach/`).

| coach | domain | shows memory (dated) | shows none (dated) | record | person served | the character a reader infers | followable? |
|---|---|---|---|---|---|---|---|
| **Dr. Eli Marsh** | lead / orchestration | 09-21: "I've asked him to spend the next week identifying which meals are the protein leak and locking one concrete change" (`weekly_priority`) | The same 09-21 text is still the door's "week's call" on 09-26 with 316.9 lb / 3.7 lb/wk / 106.9 g / "zero Strava sessions" — all contradicted by `journey`, `nutrition_overview`, `training_overview`; no follow-up exists: `recent_outputs []`, `commitment_counts` all 0, `stance.headline_read ""`, `daily null` | n=0, "preliminary" | **third** (the only one) | the manager who speaks once a week and never hears back | **No.** One paragraph a week, no thread, no ledger, no record. |
| **Dr. Lisa Park** | sleep | 09-17: "I've asked four times — on 2026-09-07, 09-08, 09-09, and 09-10 — for two specific inputs"; 09-19: "Four cycles now, Matthew, and the morning subjective rating still hasn't come in"; 09-20: "Simplify the morning rating protocol to a three-word scale … to reduce friction"; 09-26: "sixteen days of unmet morning-check requests is a dataset in itself" | 09-15: "clarify your timezone … to resolve the 04:57 UTC onset anomaly" (she reads a UTC instant as his bedtime; `avg_bedtime 10:31 PM`); 10 refutations and `how_my_read_changed ""`, `stance_history []`, `stance.source "ladder"` — the served stance is authored rung text, not hers | 7/17 held up (41.2 %); lifetime 8/25; "over-confident" | **second** ("Matthew," "you") | the persistent one — bargains a 1–5 scale down to four words over sixteen mornings and never gets them | **Yes** — the only coach with a visible arc (one ask, renegotiated, unanswered, counted) — *if* the page showed it as one thread with a count instead of 30 pending duplicates. |
| **Dr. Marcus Webb** | nutrition | 09-19: "Two weeks ago you committed to verifying that tortilla fiber entry — 30 g of fiber logged for two tortillas … almost certainly a double-count" (refs his 09-10/09-11 asks); 09-11→09-22 the dinner-fragility thread ("name a concrete backup protein source") | 09-23→09-26: "the six-day logging gap since September 19th" while `nutrition_trend` has every day; 09-26: "Restart logging tomorrow" on `days_logged 20` | 20/25 served (80 %) — 20 are one 08-10 docket; `api_calibration` says 0/5 | position_summary **third**; outputs **imperative** ("Restart logging tomorrow") | the auditor who remembers a tortilla and forgets twenty days of logs | **Partly.** Two real serial threads (the tortilla, the backup dinner); the false gap poisons the read every morning. |
| **Dr. Nathan Reeves** | mind | `stance_history` 09-13 → 09-20 with `how_my_read_changed`: "The journaling silence has moved from a hypothesis I was holding lightly to a more central concern. I initially framed it as 'plausible but incomplete' …" — the only served "what shifted in my read"; 09-09: "what enabled you to engage in harder work yesterday despite 2/10 depletion" | The silence has four lengths: "two-day" (09-13), "six-day" (stance 09-20), "eleven days" (`public_read` 09-26), "11-day" (commitment 09-26) vs `pulse gap_days 17`; the felt-sense-before-the-device question is asked on 09-10, 11, 12, 15, 19, 20, 21, 23, 24, 25, 26 with no sentence noting it is unanswered | 4/5 (80 %); "under-confident" | **second** ("You're still operating under significant structural load—grief") | the therapist who asks the same question every morning and calls the silence data | **Yes as a thread, no as served** — the repetition reads as eleven fresh insights; a count and a "still unanswered" would make it a story. (And "grief" is a private disclosure served on a public page.) |
| **Dr. Max Reyes** | physical | 09-26 `analysis`: "Now the commitment I owe you an accounting on. On 2026-09-18 I flagged the step contraction as a DUE item — I committed to revisiting the explanation explicitly this cycle"; 09-22: "what changed? Garmin is paused as a source right now" | 09-10: "Defer detailed coaching on protein intake until the nutrition coach has seven or more days of logged data" → 09-12: "Increase protein intake to 190 g/day immediately" — reversed in 48 h without a word; the "36 %" contraction carries three number pairs (thread_reference 3,010→2,386; 09-22 2,510→1,774; 09-26 2,083→1,865); 09-08/09-13 "Restore Garmin sync" — Garmin is paused by the platform (ADR-074), not by him | 2/3; commitments 39 held / 8 kept / **3 broken** (the only coach with a "broken") | **second**, imperative | the engineer who keeps a ledger and moves the decimal | **Yes** — the step thread has a date, a DUE item and an accounting; the best-shaped thread in the corpus. |
| **Dr. Amara Patel** | glucose | `stance_history` 09-23 (one entry); 09-15 "usable window 2026-09-10 to 2026-09-17" → 09-23 "the CGM sensor window closes in one to two days" — she tracks a sensor window across days | The sensor does not exist: `cgm last_seen 2026-08-27`, dark 30 d; 09-24 "the CGM is active and the sensor is accumulating data", stance "Your CGM is warming up"; 09-24 "meal logging has been absent since 2026-09-10" on 20/20; 15 pending commitments that are one sentence | 1/2; commitments 33 held / 8 kept / 15 pending | **second** | the specialist waiting on an instrument that isn't on his arm | **No.** 19 of 19 outputs are the same ask; no arc until a sensor is worn — then, possibly, the best one. |
| **Dr. James Okafor** | labs | 09-22: "It is now 171 days since your April 3rd draw. Not 'a while.' Not 'a few months.' … three specific things I asked for are still in future tense" | 09-06→09-16 (nine outputs): "Schedule the baseline lab draw for April 3rd, 2026", "before the April 3rd draw", "Capture your fatigue rating … today before the April 3rd draw" — instructions to schedule a draw that happened five months earlier (`labs.latest_draw_date 2026-04-03`, `total_draws 8`, `draws_this_cycle 0`) | 1/0 — served as "100 % hit-rate · n=1" | **second** | the doctor who wrote the same order twenty mornings running and, for eleven of them, thought April was next month | **No** until a draw is booked; the ask could be one standing thread with a day-count ("172 days since the last panel"). |
| **Dr. Henning Brandt** | explorer / n=1 stats | 09-08: "The first prediction evaluation I owe you is from the sleep model's opening call: it expected approximately 7.1 hours tonight, with an 80 % interval of 5.5–8.8" — grades a prior call; 09-06: "watch whether the lunch protein pattern holds once novelty attention fades in weeks two and three" | 09-14→09-20 "Resume/restart food logging immediately" ×5 on logged days; `daily`: "The glucose trace arrives tomorrow … zero food logs" (no sensor, 20 logs); the served "12 % hit-rate · n=24" is 20 restatements of one pre-cycle docket | 3/24 served; distinct: 3 confirmed / 2 refuted | `daily` first-person plural ("we're flying blind"); outputs imperative | the statistician who says "we barely have data" while filing 39 predictions (`by_coach.explorer total 39`) | **No as served; yes if the open docket bet (carb-cut vs recovery, resolves 09-30) were his serial.** |

### What the content model needs, and what already exists

The owner's bar: "real thoughts on the experiment, the transformation, with memory, instead of just state in time." Four structures make that true or false on the page; for each, what the engine already stores and what does not exist.

**1. Threads that persist (one ask = one thread with a count, not N records).**
- Exists: `analysis.thread_reference` (one carried string per coach per run, e.g. Reyes' step contraction, Park's 27.6 % night, Webb's calorie-neutral guardrail); `dossier.docket_positions[]` (topic, my_claim, versus, criterion, resolution_date — the two open bets are the best thread objects on the platform); `dossier.commitments[]` with `record_id`, `date`, `status`, `due_date`, `outcome`, `check`, `evidence_link`.
- Missing: a thread identity across days. Each morning's restatement is a new `record_id` (Park: 30 pending; Okafor: 54; Patel: 15), so "asked 16 times since Sep 7" is something Park has to *say* in prose rather than something the page can print. No `first_asked`, `asked_n`, `answered` fields; `check` is null on every sampled commitment, so "kept" can't be machine-graded (Okafor 1 kept of 60).

**2. Retractions and refuted premises ("I said six days dark; the log says 20 of 20").**
- Exists: `dossier.retracted` (0 on all eight) and `dossier.withheld` (Webb 1) — the counters exist; `stance.how_my_read_changed` + `stance_history[]` (populated for Reeves n=2 and Patel n=1; empty string and `source "ladder"` for Park, Webb, Reyes, Okafor, Brandt — five of seven staff serve an authored rung as their stance); `report_card.tuning_log[]` (the engine remembers its own prompt edits, dated 08-10/08-16).
- Missing: nothing marks a thread `refuted_by_engine`, so a false premise (the six-day gap, the April draw, the warming-up sensor) has no closing move; no served retraction sentence anywhere in the corpus; the input side hands the coach one day's nutrition with no `days_logged` (`COACH_VOICE_REDTEAM.md` §0), so the premise can't be corrected at the source.

**3. "Last week I said X — it turned out Y."**
- Exists: `dossier.learnings[]` verbatim (status, metric, reason, `evidence.{prediction_id, actual_value, threshold}`, `evidence_link`); `report_card.track_record.recent[]`; `api_wrong.obituaries[]` (39, each with `believed`, `number`, `what_changed`, a permalink and an OG image); `predictions[].pre_registered` (16 of the latest 50 true) and `due_date`.
- Missing: the link back into the next day's text — no coach cites its own obituary; the ledger double-counts (one 08-10 docket = 20 learnings each for Brandt and Webb), so the number the page would print is wrong before it is printed; `daily` is populated for only two of eight coaches, and the lead's is null.

**4. The calibration record on the page, beside the claim.**
- Exists, three times: `report_card.track_record` (with `n_note` and the self-assessment caveat), `api_calibration.coaches[]` (Brier, CI95, label, lifetime), `coach_team.huddle[].calibration`.
- Missing: one producer. `api_coaches.headline_stat`, `api_calibration` and `api_wrong` disagree for the same coach on the same day (Webb 80 %/n25 · 0 %/n5 · 20/5). Until one field is canonical, the record cannot sit beside a sentence.

**Two more that the owner's brief implies:**
- **Memory of the man's own words.** `dossier.relationship` (`rapport_level 0.884`, `interaction_count 45`, `tenure_days 31`, `first_interaction_date 2026-08-26` — the relationship predates the 09-06 reset, ADR-153) and `conversations.count 0` with the ADR-142 note exist; but his overrides in `api_decisions` ("No I wanna do push", "i prefer PPL") appear in no coach's dossier, and the field notes have `has_matthew_response false` ×3. The coaches remember him; they do not remember what he answered.
- **A channel for what he feels.** Two coaches have asked ~27 times (Park 16 mornings, Reeves 11) for a felt-sense word before he opens Whoop; no ingest, endpoint or field receives it (#4189). Every "thread with memory" above ends at the same wall: the platform can remember what it asked and cannot receive the answer.

**Also stored and usable now:** `analysis.elena_quote` — every coach already writes one line *for the journalist*, so the chronicle can quote a thread the way a reporter would; `report_card.tuning_log` is a public record that the coaches themselves were edited (dated, with rationale) — the honest "these characters are maintained" note the coaching door lacks.
