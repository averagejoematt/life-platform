# Site Map & Page Intent

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-18 (#4580 / #4182 — rewritten for the v8 set: the twelve kit pages under `site/next/v8/` are the doors, the cut-over table and the 2026-10-18 rulings on #4588 are recorded, the ~87 pages the kit replaces are the footnote appendix, `/now/` corrected to `/cockpit/`, the reach count re-measured against `NAV_REACH_CEILING`. Prior verify 2026-09-26: the v5 registry, Home + five doors, reach 25 and the v7 nine-page note.)

> **What each page is for, and why it matters to the platform** — one scannable registry so
> future redesigns start from intent, not guesswork. Pair with [PLATFORM_NORTH_STAR.md](PLATFORM_NORTH_STAR.md)
> (the why), [design/v8/README.md](design/v8/README.md) (the kit — the only way to build a reader
> page under epic #4580), [DESIGN_SYSTEM_V5.md](DESIGN_SYSTEM_V5.md) (the standards for every page
> that does not load `clean.css`), [SITE_UPLEVEL_PLAYBOOK.md](SITE_UPLEVEL_PLAYBOOK.md) (the
> how-to-change-it, including the front-page cut-over), and [design/JOURNEYS.md](design/JOURNEYS.md)
> (the per-audience path through the v5 registry, #1468 — it predates the kit).
>
> Intent-only by design (no live numbers — those drift). If a page's *purpose* changes, update it here.

## Where the site is (2026-10-18)

**The v8 kit pages are the approved direction.** The owner rejected six generated designs on
2026-10-03 and approved one ("clean, organized, professional"); the four front-of-house pages were
built from it on the preview path, red-teamed to A / A / A on clarity, truth and calm, and he
recorded **yes per screen on 2026-10-18** (#4586, closed). The history of how the site got here is
[SITE_TRANSFORMATION_V6.md](SITE_TRANSFORMATION_V6.md) (the reader's three questions, #4182) and
[SITE_TRANSFORMATION_V7.md](SITE_TRANSFORMATION_V7.md) (one investigation, nine pages, ADR-157);
the kit supersedes their page lists, not their rulings.

**The cut-over is go for Thursday 2026-10-22, morning PT** (#4588, owner ruling 2026-10-18 ~04:30Z),
provided five readers are recorded on #4587 by Wednesday noon and the rebuilt rehearsal (the HELD
draft PR #4928) is green. Until it merges, the live site at `/` is still the v5 registry described
under [The footnote appendix](#the-footnote-appendix-the-pages-the-kit-replaces) below, and the kit
pages are served `noindex` under `/next/v8/`. Three rulings from that sitting bind every page here:

1. **The appendix link is a footnote, not navigation.** The pages the appendix lists are not
   counted against `NAV_REACH_CEILING` (rehearsal gap C closes on this).
2. **Every layout a cut-over replaces is kept** as a served, `noindex`, out-of-navigation reference
   page, named in the footnote appendix, with the last live sha in its head comment — never deleted.
   This is the standing rule for every future cut-over, not just this one.
3. **`og:image` is a static wordmark card** until the daily mark (`ck-mark`, #4586's one unapproved
   addition to the sheet) is ruled. The front page carries no data-driven unfurl image before then.

## The doors (v8)

The twelve pages under `site/next/v8/` are the site. Each loads `site/assets/css/clean.css` and
nothing else for its look; their shared chrome is the kit's edition header and footer, and their
copy comes from `/api/edition` and the other read-only endpoints through `site/assets/js/ck_*.js`
(`data-ck-page` names the page, `data-ck-base` says where its deep links point). Preview path →
live path is the cut-over table: **four pages move on 2026-10-22; the other eight keep their
`/next/v8/` paths until a later cut-over**, and the four live pages' deep links keep landing on them
(`data-ck-base="/next/v8/"`).

| Door | Preview path | Live path after 2026-10-22 | What the first screen answers |
|---|---|---|---|
| **The front page** | `/next/v8/` | `/` | Who this is and what he is trying to do, in one sentence (327 lb → 185, in public, with AI coaches whose every prediction is graded); the four-week mark of what is gone and what is left; "New here?" to Start here; what the coaches are arguing about today. |
| **Start here** | `/next/v8/start/` | `/start/` | The story in two minutes: who Matthew is, what has happened chapter by chapter, where the weight started and is, what is open now, and that the coaches are software he built with Claude, not people. |
| **The story** | `/next/v8/story/` | `/story/` | The latest chapter and whether the next one is waiting on his approval; every chapter in order with the weight at each; the podcast ("The Panel"); follow by email. |
| **The AI coaches** | `/next/v8/coaches/` | `/coaches/` | One job each, every call checked: the three steps (record, read and predict, code grades), the team and their record beside a simple guess, one right call and one wrong one, who is betting against whom this week. |
| **This week** | `/next/v8/week/` | stays `/next/v8/week/` | How the whole thing is going: one measure per area over seven days, decided by a written rule, the lead coach's read and the week's chapter. |
| **One day** | `/next/v8/day/` | stays `/next/v8/day/` | Everything recorded on one day: what the coaches said, any call checked, what was lifted, what was eaten, sleep, recovery and steps; each number opens its trend. |
| **A trend** | `/next/v8/trend/` | stays `/next/v8/trend/` | One measure over every day of the experiment, newest first; each day opens to everything recorded on it. |
| **A coach's call, checked** | `/next/v8/call/` | stays `/next/v8/call/` | One prediction: what was called, what happened, who was right, and what a simple guess would have said. |
| **An AI coach** | `/next/v8/coach/` | stays `/next/v8/coach/` | One coach: the record beside a simple guess, what settles next, the bets against another coach, what the coach is watching, how the character is written. |
| **The character sheet** | `/next/v8/sheet/` | stays `/next/v8/sheet/` | Seven areas of one life, each a level worked out from the record; why a level and a day's score can sit apart; the badges earned. |
| **How it's built** | `/next/v8/built/` | stays `/next/v8/built/` | What runs, what it costs against its ceiling, the one place a person approves, and what has broken. |
| **Appendix** | `/next/v8/appendix/` | stays `/next/v8/appendix/` | Everything else on the site, in one list — the pages that still use the earlier design, grouped, each with one plain line. A footnote, not navigation (ruling 1). |

**The order rule still holds** (ADR-157, re-affirmed by the 2026-10-18 yes): the human first, the
counted failures second, the mechanism third, the coaches last and short, the machine vocabulary
never. **No cycle count on any reader surface** (owner ruling 2026-09-26): no "17th start", no
attempt or reset count, on a kit page or in the appendix's lines. The coaches are always "software
I built with Claude, not people"; a record is "K of N" beside the simple guess, never a bare
percentage.

**Audience, per door.** The front page and Start here are for the person he just told about it
(the cafe test: someone lands and sees the whole experiment in one throughline); The story is for
friends, family and returning readers; The AI coaches, One day, A trend, A call and An AI coach are
for the reader who wants to check the work; The character sheet is the one page Matthew keeps
coming back to; How it's built is for the skeptic and the build-in-public crowd.

## Navigation and reach

**The kit footer is the whole navigation**: Start here · The story · The AI coaches · How it's
built · Appendix · The code (GitHub). The front page's body adds This week, One day and The
character sheet ("Go deeper — the rest, one tap away") and the follow box links `/subscribe/`.
A trend, A call and An AI coach are reached only from the page that owns the number, the call or
the coach. There is no top-nav bar, no mega-menu and no wayfinder on a kit page.

**The reach ratchet.** `ledgers/site_vocabulary_residue.py::NAV_REACH_CEILING` is **24** today and
may only fall; `tests/test_site_nav_reach_ratchet.py` walks the static links from `site/index.html`
(`tests/site_text.py::static_reach`, `<noscript>` bakes excluded, `site/legacy/` excluded by
standing policy). On the live v5 site the set is 24, at the ceiling. After the cut-over the count is
taken **with the appendix excluded** (ruling 1): the kit's own static set is ten — the front page,
Start here, The story, The AI coaches, This week, One day, The character sheet, How it's built,
`/subscribe/` and the appendix node itself — well under 24. Measured on the preview tree on
2026-10-17 by the same walk with the appendix as a sink, the number is 36, because `/subscribe/`
still wears the v5 chrome and its menu walks the old doors (and `/privacy/` through it); the rebuilt
rehearsal settles that (re-pour the subscribe shell on the kit, or exempt the v5 chrome's menu the
way the appendix is exempt) and lowers the ceiling to what it measures. Until the rehearsal lands,
24 holds.

## The footnote appendix: the pages the kit replaces

**~87 pages** — the 91 reader pages served today less the four the cut-over replaces — stay
**served at their URLs, out of navigation, never deleted** (owner ruling 2026-10-18, "keep the old
layout stored as a reference like all going forward"; the 2026-09-26 panel ruling already said no
URL moves, no 301s, no deletions). They are listed on `/next/v8/appendix/` under the headings the
reader would use, each with one plain line, and the appendix tells the reader they "still use the
site's earlier design". `scripts/v4_build_sitemap.py` keeps them in the sitemap; a page the owner
has not yet ruled on carries `noindex` via `scripts/v4_chrome.py::HELD_UNTIL_RULED` (#4604).

**Reference copies of a replaced layout.** The cut-over keeps the v5 front page (and each page a
future cut-over replaces) as a served, `noindex`, out-of-navigation reference page with the last
live sha in its head comment, named in the appendix (ruling 2). The convention this registry sets
for the rebuilt rehearsal is **`/reference/<date>-<slug>/`** — the v5 home becomes
`/reference/2026-10-22-home-v5/` — one directory per replaced layout, its assets pointing at the
served v5 CSS/JS, never rebuilt by a generator. It does **not** go under `/legacy/`: `/legacy/*` is
the frozen pre-v4 site, private rollback, **never linked from the UI** (SITE_AUTHORING.md), and a
reference page is linked from the appendix by the ruling.

These pages still pour the v5 chrome (`scripts/v4_chrome.py`, the wayfinder from
`scripts/v4_wayfinding.py`), so their station registry stays here — **the wayfinding mirrors this
section**: change a station's loop role here and change it there. Three pillars (`/data/`,
`/protocols/`, `/method/`) are served by one base-aware engine (`site/assets/js/evidence.js` +
`scripts/v4_build_evidence.py`); Coaching and Story's sub-pages are their own master-detail apps
(`v4_build_coaching.py` / `v4_build_dispatches.py`, both of which leave a kit page alone,
`v4_apply_chrome.is_kit_page`, #4588).

### The Cockpit — `/cockpit/` · today's slice
- **Loop role:** today's slice of the whole loop, read back to you. **Audience:** Matthew (daily return) + curious visitors. Its job passes to This week and One day on the kit.
- **Must deliver (amended 2026-09-26, #4182):** the three questions first — *how's the week / last night / today* — from served fields with their dates, n and CI; the daily line; the whole-life score is a second-screen instrument under a plain-English key, never the first thing on the page.
- **Files:** `site/cockpit/index.html`, `assets/js/cockpit.js`, `cockpit.css`. **Endpoints:** `/api/snapshot`, `/api/changes-since`, `/api/weekly_priority`, `/api/circadian`.

### The Data — `/data/` · the engine
- **Loop role:** the engine — every source, now & over time. **Audience:** health/QS enthusiasts + Matthew. Its job passes to A trend and One day on the kit; the topic pages (physical, sleep, training, nutrition, labs, badges) are the appendix's "Detailed data pages".
- **Sections:** *The body* (vitals, weight/composition, bloodwork, glucose, sleep, training, nutrition), *Mind & accountability* (mind, habits, vice streaks — plus the ledger, registry-flagged `unlisted` (#1109)).
- **Must deliver:** dense, honest, explorable readouts — each showing *now + over time*, flagged when thin. Live source-freshness.
- **Files:** `evidence.js` (the router) + per-family renderer modules `evidence_*.js` (split in #581), `v4_build_evidence.py` (registry/shell), `evidence.css`. **Endpoints:** `/api/pulse`, `/api/sleep_detail`, `/api/training_overview`, `/api/nutrition_overview`, `/api/correlations`, `/api/source_freshness`, etc.

### The Coaching — `/coaching/` · the AI brain
- **Loop role:** AI reads the data and argues about it. **Audience:** everyone. Its job passes to The AI coaches, An AI coach and A call on the kit; by-coach, scorecard and lab-notes stay as appendix pages.
- **Must deliver (amended 2026-09-26, #4182):** one read per day at the top — chosen by a stated rule, its written-time in words, its age said out loud past 48 h; the weekly call labelled weekly; each coach's stance and scored track record, the disagreements surfaced (not averaged), honest empty-states. Served coach text is never rewritten — glossed, and marked disputed where a figure disagrees with the engine.
- **Files:** `coaching.js`, `v4_build_coaching.py`. **Endpoints:** `/api/coaches`, `/api/coach/{id}`, `/api/coach_team`, `/api/predictions`, `/api/field_notes`, `/api/board_ask` + `/api/board_question` (**reader Q&A — ask-the-board**, rate-limited 5/IP/hr, moderated via `generated/board_questions/` → `scripts/publish_board_answer.py`; degrades LAST per ADR-100/125).

### The Protocols — `/protocols/` · the levers
- **Loop role:** the levers — what gets changed to move the data, and whether it moved. **Audience:** enthusiasts + Matthew. No kit page owns this yet; experiments, supplements, challenges and discoveries are appendix pages.
- **Must deliver:** each protocol framed causally — *what data it targets*, *which hypothesis/finding spawned it*, *the measured effect*. Reader voting/follow/checkin where built.
- **Files:** `evidence.js` (router) + `evidence_discovery.js`, `v4_build_evidence.py`. **Endpoints:** `/api/supplements`, `/api/experiments`, `/api/challenges`, `/api/discoveries`.

### The Story — `/story/` · the narration (replaced at `/story/` on 2026-10-22)
- **Loop role:** the human journey narrating the whole loop, week by week. The kit's The story takes the URL; the v4 hub's sub-pages — Chronicle (Elena Voss's weekly narrative), Podcast ("The Panel"), In my own words (journal), Timeline, About, the build log at `/story/build/` — stay served and listed in the appendix; `/story/attempts/` and `/method/survival/` stay served and unlisted (the cycle-count ruling).
- **Must deliver:** the *human* drama — grounded, never fabricated (the chronicle must stay inside the logged data); the podcast (`EP{n} · short hook`); a timeline that explains the character system.
- **Files:** `dispatches.js`, `v4_build_dispatches.py`; chronicle/podcast generated by `lambdas/emails/wednesday_chronicle_lambda.py` + `coach_panel_podcast_lambda.py`. The "In my own words" **essay permalink pages** (`/journal/essays/<slug>/`) are generated by `v4_build_journal.py` from `site/journal/blog.json` + each essay's `body.html`/`body.md` fragment (#1566; the generator is dry-run by default, so publishing an essay stays a manual deploy step). **Sources:** `/journal/posts.json`, `/panelcast/episodes.json` (viewer path; the S3 key is `generated/panelcast/episodes.json` per ADR-046).

### The Method — `/method/` · under the hood
- **Loop role:** how the numbers are made, how honest they are, the resets along the way. **Audience:** skeptics + the build-in-public crowd. Its front passes to How it's built on the kit; the rest are the appendix's "How it's built, in detail".
- **Sections:** *How it holds up* (methodology, the **character explainer** `/method/character/`, predictions, benchmarks, biology, post-mortems, survival curve, **The Mirror**, the wrong page, results), *The machine* (board, build/architecture, intelligence, platform, data sources, pipeline, tools, cost, inference, explorer, ask), *The reset log* (cycles, unlisted).
- **The Build** (`/method/state/`, #3691) — **unlisted**, the one page whose audience is Matthew-as-builder: the open-issue count decomposed into cohorts, delivery rate and cycle time, graded lenses, what awaits live proof, incident classes, gate-census health, spend from `/api/receipts`. Built by `scripts/build_platform_state.py` into `site/data/platform_state.json` — repo + `gh` + public HTTPS only, no IAM; every section carries its own `as_of`. Unlisted is **not** private (the S3 website endpoint serves `site/*` publicly — #1905).
- **The Mirror** (`/method/mirror/`, #1392): a reader's Whoop CSV export scored **in the browser** on the deployed instruments and overlaid on Matthew's published year (`site/data/mirror_distributions.json`, regenerate attended via `scripts/gen_mirror_distributions.py`). CURATED page (`scripts/v4_build_mirror.py` + apply-chrome); its registry row carries the **`"external"` flag**. Parity + no-upload privacy are enforced by `tests/test_mirror_parity.py` / `tests/js/mirror_core.test.mjs` over `tests/vectors/mirror_vectors.json`.
- **The Methods Registry** (`/method/registry/`, #544) — every stat's formula/window/limitations, generated from `lambdas/experiment/methods_registry.py` (also served at `/api/methods`). Built by `scripts/v4_build_methods.py`, standalone static HTML. Extend the registry (not the page's markup) when a new stat needs documenting.
- **Files:** `evidence.js`, `v4_build_evidence.py` (EDITORIAL dict for authored pages).

### Utility pages
- `/subscribe/` (+ `/confirm/`) — double-opt-in follow-by-email; the kit's follow box links it. `/privacy/` — policy + AI disclaimer. `/404.html`. `/kit/` — the kit specimen, unlisted and `noindex`. `/legacy/*` — the preserved pre-v4 site (private rollback, never linked from the UI; not where reference copies go).
