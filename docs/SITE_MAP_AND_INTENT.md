# Site Map & Page Intent

> **What each page is for, and why it matters to the platform** — one scannable registry so
> future redesigns start from intent, not guesswork. Pair with [PLATFORM_NORTH_STAR.md](PLATFORM_NORTH_STAR.md)
> (the why), [DESIGN_SYSTEM_V5.md](DESIGN_SYSTEM_V5.md) (the how-it-looks), and
> [SITE_UPLEVEL_PLAYBOOK.md](SITE_UPLEVEL_PLAYBOOK.md) (the how-to-change-it).
>
> Intent-only by design (no counts/dates — those drift). If a page's *purpose* changes, update it here.

## Navigation (v5)

**Home + 5 doors:** `the cockpit · the data · the coaching · the protocols · the story`.
**Method** is footer-tier (no top-nav door) — the "under the hood" pages, reachable from the
footer + About. Old `/evidence/*` URLs 301 to their new pillar homes.

Three pillars (`/data/`, `/protocols/`, `/method/`) are served by **one base-aware engine**
(`site/assets/js/evidence.js` + `scripts/v4_build_evidence.py`, split by registry group).
Coaching (`/coaching/`) and Story (`/story/`) are their own master-detail apps
(`v4_build_coaching.py` / `v4_build_dispatches.py`). Home + Cockpit are hand-authored.

## The doors

### Home — `/` · the front door
- **Loop role:** teaches the loop, then routes in. **Audience:** primarily Reddit newcomers + first-time visitors.
- **Must deliver:** the day-of-experiment counter (the "what day are we on" number), the loop
  diagram (what this site *is*), the headline proof (lbs down, the waveform), and clear doors. Short scroll.
- **Good looks like:** a newcomer understands the whole thing in one screen and wants to explore.
- **Files:** `site/index.html`, `site/assets/js/story.js`, `story.css`. **Endpoints:** `/public_stats.json`, `/api/journey`, `/api/journey_waveform`, `/api/character`, `/api/field_notes`.

### The Cockpit — `/now/` · today's slice
- **Loop role:** today's slice of the whole loop, read back to you. **Audience:** Matthew (daily return) + curious visitors.
- **Must deliver:** today's snapshot (the whole-life score + 7 pillars), what changed since
  yesterday, the board's *one* accurate priority, tonight's forecast, the onboarding card for newcomers.
- **Good looks like:** the page you check every morning; orienting, honest, never harsh. The board
  credits real effort (baseline-relative), never catastrophizes.
- **Files:** `site/now/index.html`, `assets/js/cockpit.js`, `cockpit.css`. **Endpoints:** `/api/snapshot`, `/api/changes-since`, `/api/weekly_priority`, `/api/circadian`.

### The Data — `/data/` · the engine
- **Loop role:** the engine — every source, now & over time. **Audience:** health/QS enthusiasts + Matthew.
- **Sections:** *The body* (vitals, weight/composition, bloodwork, glucose, sleep, training, nutrition),
  *Mind & accountability* (mind, habits, vice streaks, the ledger).
- **Must deliver:** dense, honest, explorable readouts — rings, trends (interactive), correlations —
  each showing *now + over time*, flagged when thin. Live source-freshness.
- **Good looks like:** elite data journalism a QS skeptic trusts; charts you can hover/scrub.
- **Files:** `evidence.js` (the router — registry dispatch + chrome) + per-family renderer modules `evidence_*.js` (`_shared`, `_body`, `_nutrition`, `_sleep`, `_habits`, `_discovery`, `_meta`, `_intelligence`, `_vitals`, `_reading`, `_character`, `_datafigure`; split in #581), `v4_build_evidence.py` (registry/shell), `evidence.css`. **Endpoints:** `/api/pulse`, `/api/sleep_detail`, `/api/training_overview`, `/api/nutrition_overview`, `/api/correlations`, `/api/source_freshness`, etc.

### The Coaching — `/coaching/` · the AI brain
- **Loop role:** AI reads the data and argues about it. **Audience:** everyone — it's the showcase of "AI applied to one life."
- **Sections:** *The Team* (the collective read + per-coach tabbed profiles: Current read / Track record / Bio) and *AI lab notes* (the Third Wall: the AI's read ↔ how it felt). The named experts + their disagreements are the moat.
- **Must deliver:** each coach's stance, track record (predictions, scored), and current feedback;
  the disagreements surfaced (not averaged); honest empty-states before data accrues.
- **Good looks like:** you can watch a model apply real knowledge to real data and take sides.
- **Files:** `coaching.js`, `v4_build_coaching.py`, coach styles in `story.css`. **Endpoints:** `/api/coaches`, `/api/coach/{id}`, `/api/coach_team`, `/api/predictions`, `/api/field_notes`.

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
- **Files:** `dispatches.js`, `v4_build_dispatches.py`; chronicle/podcast generated by `lambdas/emails/wednesday_chronicle_lambda.py` + `coach_panel_podcast_lambda.py`. **Sources:** `/journal/posts.json`, `/generated/panelcast/episodes.json`.

### The Method — `/method/` · under the hood (footer-tier, no door)
- **Loop role:** how the numbers are made, how honest they are, the resets along the way. **Audience:** skeptics + the build-in-public crowd.
- **Sections:** *How it holds up* (methodology, the **character explainer**, predictions, benchmarks,
  biology, post-mortems, survival curve, the mirror, the wrong page, results), *The machine*
  (board, build/architecture, intelligence, platform, data sources, pipeline, tools, cost, inference,
  explorer, ask), *The reset log* (cycles).
- **Must deliver:** the credibility story — the architecture, the budget governor, the AI-failure log,
  the methodology, the character-level explainer (linked from cockpit + timeline).
- **Good looks like:** a skeptic comes away trusting the machine *because* it shows its failures.
- **Files:** `evidence.js`, `v4_build_evidence.py` (EDITORIAL dict for authored pages).
- **The Methods Registry** (`/method/registry/`, #544) is a deliberately standalone sibling —
  every stat's formula/window/limitations, generated from `lambdas/methods_registry.py` (also
  served machine-readably at `/api/methods`). Built by `scripts/v4_build_methods.py`, its own
  static HTML with no `evidence.js` dependency, so it ships independently of the evidence-engine
  refactor (#581). Extend the registry (not this page's markup) when a new stat needs documenting.

### Utility pages
- `/subscribe/` (+ `/confirm/`) — double-opt-in follow-by-email. `/privacy/` — policy + AI disclaimer. `/404.html`. `/legacy/*` — the preserved v3 site (private rollback, never linked).
