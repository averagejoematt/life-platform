# Site Map & Page Intent

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-09-26

> **v7 is LIVE (cut over 2026-09-27, ADR-157):** the reachable site is the nine pages below plus `/privacy/`, poured by `scripts/v7_build.py` at their original URLs (no 301s, no deletions). Every other page in this document is SERVED at its URL and UNLISTED — reachable by direct link, the sitemap or search, never from the nine (the reach ratchet `NAV_REACH_CEILING = 10`). The v4/v5 door sections further down are the record of what those archive pages are for; they no longer describe the navigation.

> **What each page is for, and why it matters to the platform** — one scannable registry so
> future redesigns start from intent, not guesswork. Pair with [PLATFORM_NORTH_STAR.md](PLATFORM_NORTH_STAR.md)
> (the why), [DESIGN_SYSTEM_V5.md](DESIGN_SYSTEM_V5.md) (the how-it-looks),
> [SITE_UPLEVEL_PLAYBOOK.md](SITE_UPLEVEL_PLAYBOOK.md) (the how-to-change-it), and
> [design/JOURNEYS.md](design/JOURNEYS.md) (the per-audience path *through* this registry —
> entry → hook → next station → return trigger, and the audit of every door's actual exit
> links against it, #1468).
>
> Intent-only by design (no counts/dates — those drift). If a page's *purpose* changes, update it here.

## Navigation (v7 — ADR-157, the nine)

**The bar (five, fixed at the bottom of every page — `v4_chrome.V7_BAR`):** `Home` (`/`) · `Today` (`/cockpit/`) · `This week` (`/story/`) · `His numbers` (`/data/`) · `The coaches` (`/coaching/`).
**The footer tier (one line on every page — `v4_chrome.V7_FOOT` + RSS + Privacy):** `What he’s trying` (`/protocols/`) · `Who he is` (`/story/about/`) · `Under the hood` (`/method/`) · `Follow` (`/subscribe/`) · `RSS` (`/rss.xml`) · `Privacy` (`/privacy/`).

| # | page · URL | the one job (CONCEPT §3) | template | module |
|---|---|---|---|---|
| 1 | **Home** `/` | The case so far — the day-one photograph beside the number, the lead, every weigh-in, in his words, is he okay this week, also on the record, how it works, what resolves next, follow | `scripts/v7/home.py` | `v7_home.js` |
| 2 | **Today** `/cockpit/` | Matthew’s morning screen, open to anyone — the three questions, the session, the one ask, what he skips, nothing after it | `scripts/v7/today.py` | `v7_today.js` |
| 3 | **This week** `/story/` | The instalment — the latest write-up, previously, the week so far, his testimony, next | `scripts/v7/week.py` | `v7_week.js` |
| 4 | **His numbers** `/data/` | The evidence — weight, sleep, eating, training, blood tests; one chart and one sentence each, CSV under every chart, what is not being recorded | `scripts/v7/numbers.py` | `v7_numbers.js` |
| 5 | **The coaches** `/coaching/` | The witnesses, on the record — today’s read, where two disagree, every checked call right or wrong, the staff one tap down | `scripts/v7/coaches.py` | `v7_coaches.js` |
| 6 | **What he’s trying** `/protocols/` | What he takes and tests, what each should move, how we’d know; his calls in his words | `scripts/v7/tries.py` | `v7_tries.js` |
| 7 | **Who he is** `/story/about/` | The subject, in the first person — his paragraph, the photographs, since the day it began, how to check | `scripts/v7/who.py` | `v7_who.js` |
| 8 | **Under the hood** `/method/` | How a number is made, the corrections column, the build log, the gear, the receipt | `scripts/v7/hood.py` | `v7_hood.js` |
| 9 | **Follow** `/subscribe/` | The return — the promise in weekdays, the field, the honest count, every line with an empty state | `scripts/v7/follow.py` | `v7_follow.js` |

**The rules every page keeps (CONCEPT §2, §10; `docs/SITE_TRANSFORMATION_V7.md`):** served fields only, every figure with its `data-src`; absence as absence, never a promise; no cycle/reset/attempt word; no machine word; dates in words; one "Data through <day>" per page (the `<noscript>` core’s "as of" is the one sanctioned place for that phrase); green means earned; no page link in a body but the repo and `mailto:`; assets flat and root-absolute.

**How the nine are built and held:** `scripts/v7_build.py --base / --allow-live` is the ONE writer (it runs first in `deploy/sync_site_to_s3.sh`; `v4_apply_chrome.write_page` refuses every other generator at the nine’s paths), `--check` is its drift guard; `v4_chrome.EDITION = "v7"` pours the one chrome onto every page including the archive; the six tier-1 manifest rows (`tests/qa_manifest.py`) name the shells’ own selectors so the post-deploy visual gate holds in the empty-data state; the six door `intent`s are the comprehension judge’s ground truth; `tests/site_vocabulary_residue.py` holds the reach (10) and the per-term vocabulary ledger, shrink-only.

**The archive (served, unlisted):** every page the sections below describe — the topic readouts under `/data/`, `/protocols/`, `/method/`, the coaching sections, the story sections, `/gear/`, `/story/build/`, `/method/character/`, `/story/attempts/` (the owner’s 2026-09-26 ruling: the cycle count is internal) — keeps its URL, its body and the same bar and footer as the nine. Nothing links to them from the nine, by rule; `tests/test_site_orphans.py` records the deliberate exceptions.

## The doors — the v4/v5 record (archive pages since ADR-157; intent only)

### Home — `/` · the front door
- **Loop role:** teaches the loop, then routes in. **Audience:** primarily Reddit newcomers + first-time visitors.
- **Must deliver (amended 2026-09-26, #4182 — see `SITE_TRANSFORMATION_V6.md` §5):** in this order — the friends' read (the weight move + five plain lines, dated in words), the coaches defined once (software, not people), three doors as sentences; *then* the loop diagram ("How the pieces fit"), the headline proof and the day counter. Short scroll.
- **Good looks like:** a newcomer understands the whole thing in one screen and wants to explore.
- **Files:** `site/index.html`, `site/assets/js/story.js`, `story.css`. **Endpoints:** `/public_stats.json`, `/api/journey`, `/api/journey_waveform`, `/api/character`, `/api/field_notes`.

### The Cockpit — `/now/` · today's slice
- **Loop role:** today's slice of the whole loop, read back to you. **Audience:** Matthew (daily return) + curious visitors.
- **Must deliver (amended 2026-09-26, #4182):** the three questions first — *how's the week / last night / today* — from served fields with their dates, n and CI; the daily line; the whole-life score is a second-screen instrument under a plain-English key, never the first thing on the page.
- **Good looks like:** the page you check every morning; orienting, honest, never harsh. The board
  credits real effort (baseline-relative), never catastrophizes.
- **Files:** `site/now/index.html`, `assets/js/cockpit.js`, `cockpit.css`. **Endpoints:** `/api/snapshot`, `/api/changes-since`, `/api/weekly_priority`, `/api/circadian`.

### The Data — `/data/` · the engine
- **Loop role:** the engine — every source, now & over time. **Audience:** health/QS enthusiasts + Matthew.
- **Sections:** *The body* (vitals, weight/composition, bloodwork, glucose, sleep, training, nutrition),
  *Mind & accountability* (mind, habits, vice streaks — plus the ledger, registry-flagged
  `unlisted` (#1109): off the tile rail by intent, reachable via the footer Data column + direct URL).
- **Must deliver:** dense, honest, explorable readouts — rings, trends (interactive), correlations —
  each showing *now + over time*, flagged when thin. Live source-freshness.
- **Good looks like:** elite data journalism a QS skeptic trusts; charts you can hover/scrub.
- **Files:** `evidence.js` (the router — registry dispatch + chrome) + per-family renderer modules `evidence_*.js` (`_shared`, `_body`, `_nutrition`, `_sleep`, `_habits`, `_discovery`, `_meta`, `_intelligence`, `_vitals`, `_reading`, `_character`, `_datafigure`; split in #581), `v4_build_evidence.py` (registry/shell), `evidence.css`. **Endpoints:** `/api/pulse`, `/api/sleep_detail`, `/api/training_overview`, `/api/nutrition_overview`, `/api/correlations`, `/api/source_freshness`, etc.

### The Coaching — `/coaching/` · the AI brain
- **Loop role:** AI reads the data and argues about it. **Audience:** everyone — it's the showcase of "AI applied to one life."
- **Sections:** *The Team* (the collective read + per-coach tabbed profiles: Current read / Track record / Bio) and *AI lab notes* (the Third Wall: the AI's read ↔ how it felt). The named experts + their disagreements are the moat.
- **Must deliver (amended 2026-09-26, #4182):** one read per day at the top — chosen by a stated rule, its written-time in words, its age said out loud past 48 h; the weekly call labelled weekly; then each coach's stance and scored track record, the disagreements surfaced (not averaged), honest empty-states before data accrues. Served coach text is never rewritten — glossed, and marked disputed where a figure disagrees with the engine.
- **Good looks like:** you can watch a model apply real knowledge to real data and take sides.
- **Files:** `coaching.js`, `v4_build_coaching.py`, coach styles in `story.css`. **Endpoints:** `/api/coaches`, `/api/coach/{id}`, `/api/coach_team`, `/api/predictions`, `/api/field_notes`, `/api/board_ask` + `/api/board_question` (**reader Q&A — ask-the-board**: the door's engagement/conversion loop, rate-limited 5/IP/hr, moderated via `generated/board_questions/` → `scripts/publish_board_answer.py`; unit-economically protected to degrade LAST per ADR-100/125).

### The Protocols — `/protocols/` · the levers
- **Loop role:** the levers — what gets changed to move the data, and whether it moved. **Audience:** enthusiasts + Matthew.
- **Sections:** supplements · protocols · experiments · challenges · discoveries.
- **Must deliver:** each protocol framed causally — *what data it targets*, *which hypothesis/finding
  spawned it*, *the measured effect*. Reader voting/follow/checkin where built.
- **Good looks like:** it reads as a causal experiment log, not a list of pills.
- **Files:** `evidence.js` (router) + `evidence_discovery.js` (the /protocols/ renderers, split in #581), `v4_build_evidence.py`. **Endpoints:** `/api/supplements`, `/api/experiments`, `/api/challenges`, `/api/discoveries`.

### The Story — `/story/` · the narration
- **Loop role:** the human journey narrating the whole loop, week by week. **Audience:** friends/family + returning followers.
- **Sections:** Chronicle (Elena Voss's weekly narrative), Podcast ("The Panel"), In my own words (journal), Timeline, About.
- **Must deliver:** the *human* drama — grounded, never fabricated (the chronicle must stay inside the
  logged data); the podcast (`EP{n} · short hook`); a timeline that explains the character system.
- **Good looks like:** you come back each week for the next installment, like a show.
- **Files:** `dispatches.js`, `v4_build_dispatches.py`; chronicle/podcast generated by `lambdas/emails/wednesday_chronicle_lambda.py` + `coach_panel_podcast_lambda.py`. The "In my own words" **essay permalink pages** (`/journal/essays/<slug>/`) are generated by `v4_build_journal.py` from `site/journal/blog.json` + each essay's `body.html`/`body.md` fragment (#1566 — no hand-authored page HTML; the generator is dry-run by default, so publishing an essay stays a manual deploy step). **Sources:** `/journal/posts.json`, `/panelcast/episodes.json` (viewer path; the S3 key is `generated/panelcast/episodes.json` per ADR-046).

### The Method — `/method/` · under the hood (footer-tier, no door)
- **Loop role:** how the numbers are made, how honest they are, the resets along the way. **Audience:** skeptics + the build-in-public crowd.
- **Sections:** *How it holds up* (methodology, the **character explainer**, predictions, benchmarks,
  biology, post-mortems, survival curve, **The Mirror**, the wrong page, results), *The machine*
  (board, build/architecture, intelligence, platform, data sources, pipeline, tools, cost, inference,
  explorer, ask), *The reset log* (cycles).
- **The Build** (`/method/state/`, #3691) — **unlisted**, and the only page on the site whose
  audience is Matthew-as-builder rather than any of the four the north star names. The joined
  owner-facing read of how the *building* is going: the open-issue count decomposed into cohorts
  (the number that turns "108 open" into a workload rather than an emergency), delivery rate and
  cycle time split organic-vs-audit, graded lenses prior→now, what is awaiting live proof, incident
  classes, gate-census health, and spend read live from `/api/receipts`. Generated wholly at build
  time by `scripts/build_platform_state.py` into `site/data/platform_state.json` — repo + `gh` +
  public HTTPS only, no IAM. Every section carries its own `as_of`; a section that cannot be
  computed renders as a stated gap, never a stale value. Unlisted is **not** private (the S3
  website endpoint serves `site/*` publicly — see #1905); nothing on it is secret, since the repo
  is public and the cost figures already ship on `/method/receipts/`.
- **The Mirror** (`/method/mirror/`, #1392 — upgraded 2026-08-02 from the type-three-numbers widget):
  a reader's Whoop CSV export scored **in the browser** on the deployed instruments and overlaid on
  Matthew's published year (`site/data/mirror_distributions.json`, regenerate attended via
  `scripts/gen_mirror_distributions.py`). CURATED page (`scripts/v4_build_mirror.py` + apply-chrome),
  not an archive shell — its registry row carries the **`"external"` flag** (keeps the nav tile;
  the evidence build skips writing its index.html; evidence.js follows the link as a real
  navigation). Parity + no-upload privacy are enforced by `tests/test_mirror_parity.py` /
  `tests/js/mirror_core.test.mjs` over `tests/vectors/mirror_vectors.json`. The first rung of
  #1366's participation ladder.
- **Must deliver:** the credibility story — the architecture, the budget governor, the AI-failure log,
  the methodology, the character-level explainer (linked from cockpit + timeline).
- **Good looks like:** a skeptic comes away trusting the machine *because* it shows its failures.
- **Files:** `evidence.js`, `v4_build_evidence.py` (EDITORIAL dict for authored pages).
- **The Methods Registry** (`/method/registry/`, #544) is a deliberately standalone sibling —
  every stat's formula/window/limitations, generated from `lambdas/experiment/methods_registry.py` (also
  served machine-readably at `/api/methods`). Built by `scripts/v4_build_methods.py`, its own
  static HTML with no `evidence.js` dependency, so it ships independently of the evidence-engine
  refactor (#581). Extend the registry (not this page's markup) when a new stat needs documenting.

### Utility pages
- `/subscribe/` (+ `/confirm/`) — double-opt-in follow-by-email. `/privacy/` — policy + AI disclaimer. `/404.html`. `/legacy/*` — the preserved v3 site (private rollback, never linked).
