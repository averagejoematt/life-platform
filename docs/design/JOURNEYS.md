# The Four Audience Journeys

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-18

> The site's four north-star audiences ([PLATFORM_NORTH_STAR.md](../PLATFORM_NORTH_STAR.md))
> have always had a *destination* (the doors registry, [SITE_MAP_AND_INTENT.md](../SITE_MAP_AND_INTENT.md)),
> but never a *deliberate path* — entry → hook → next station → return trigger, per
> audience, closed on every page. This doc is that path, the audit of the gap it closed,
> and the mechanism that keeps it closed. Filed for #1468 (part of epic #1461,
> the 2026-07-18 design-partner plan session).

## Why this exists

The causal loop (data → coaching → protocols → story, cycling; cockpit = today's slice)
is the platform's one through-line. Before this issue, every page *taught* the loop
(the `.loop-ribbon` wayfinder, #578) but no page *closed* one — the only thing at the
bottom of every page was the `.site-foot` mega-menu, a directory of ~30 links with no
opinion about what to do next. A directory is not a journey. A reader who finished
`/data/sleep/` had to self-navigate to find out the AI team's take on it; a reader who
finished the chronicle had no prompt to check today's live numbers. Zero pages were
technically "dead" (the footer always had links), but zero pages *pulled the reader
forward*, which is the actual return-visit lever the epic is chasing.

## The four journeys

Each journey names: **entry point** (where this audience actually lands), **first hook**
(what earns 10 more seconds), **next station** (the deliberate forward path through the
loop, now implemented as the `.loop-forward` close on every page — see
[the mechanism](#the-mechanism-loopforward)), and **return trigger** (what brings them
back).

### 1. Reddit newcomers
- **Entry point:** `/` (home) — almost always via a Reddit/HN link, cold, skeptical of
  "another AI wellness thing."
- **First hook:** the loop diagram + headline proof (lbs down, the waveform) in one
  screen, no scroll required — home's whole job per SITE_MAP_AND_INTENT.md.
- **Next station:** home's loop-forward close now points at **the cockpit** ("start with
  today's live read") — the fastest way to see the loop is *actually running*, not just
  diagrammed. From the cockpit the close continues the loop: cockpit → data → coaching →
  protocols → story → cockpit, so a newcomer who keeps clicking "next" walks the entire
  causal loop once, in order, without having to understand the IA first.
- **Return trigger:** the loop-forward's constant second line — "follow by email" — is
  the low-friction ask (no account, one link) that turns a browse into a subscriber.

### 2. Matthew (the N=1 subject)
- **Entry point:** `/cockpit/` directly (bookmarked) — this is the daily-return
  audience; he does not enter through home.
- **First hook:** today's snapshot + what changed since yesterday — already live,
  unaffected by this issue.
- **Next station:** cockpit's loop-forward → **the data** ("see what's driving today's
  read") — the natural drill-down from a summary number to its inputs, matching how he
  actually uses the site (glance at cockpit, then check the metric that moved).
- **Return trigger:** none needed — the cockpit itself *is* the return trigger (a daily
  instrument he checks by habit). The loop-forward's follow-by-email line is redundant
  for this audience and deliberately harmless (he's not going to re-subscribe to his own
  site); consistency across all four audiences was worth the one no-op line here.

### 3. Friends & family
- **Entry point:** `/story/` or a specific chronicle/journal entry, usually linked
  directly ("here's this week's update").
- **First hook:** the human drama — is he okay, is it working — carried by the
  chronicle's narrative voice, not numbers.
- **Next station:** story's loop-forward → **the cockpit** ("check today's live read") —
  the bridge from "read about it" to "see it live," which is the credibility move for an
  audience that trusts narrative more than charts but should see the charts are real.
- **Return trigger:** "follow by email" — this audience is the most likely to actually
  want a weekly nudge rather than remembering to check back, so the universal return
  trigger does its most real work here.

### 4. Health / quantified-self enthusiasts
- **Entry point:** `/data/` or a specific topic page (`/data/sleep/`, `/method/`), often
  arriving deep via search or a shared link to a specific stat.
- **First hook:** density and credibility — live numbers, methodology, sources shown,
  failures not hidden.
- **Next station:** data's loop-forward → **the coaching** ("see what the AI team makes
  of it") and protocols' → **the story** ("follow whether it moved anything") — this
  audience came for evidence, so the forward path is deliberately the *rest of the
  causal chain* (does the AI act on this data, did the lever move it) rather than a
  generic subscribe nudge. Method pages (footer-tier, no door of their own) inherit the
  Data door's next station — a reader here came for credibility and the natural next
  move is watching the AI apply it, not a fifth destination.
- **Return trigger:** "follow by email" for the digest, but this audience's real return
  driver is new data landing — outside this issue's scope (that's the ingestion pipeline,
  not the IA).

## The audit: exit links vs. the map, before and after

The audit runs at the **door level** — every page under a door shares that door's
loop-forward mapping by construction (`scripts/v4_chrome.py::NEXT_STATION`), so auditing
per-door covers all 78 chrome-bearing pages without re-litigating page-by-page (a page
whose door differs from its siblings would be a bug the guard test below would catch).

| Door / section | Actual exit links, before #1468 | Gap | Actual exit, after #1468 |
|---|---|---|---|
| Home (`/`) | `.site-foot` mega-menu only (~30 links, no ranking) | No deliberate next step; a newcomer had to choose among 30 links with no guidance | `.loop-forward` → `/cockpit/` ("start with today's live read"), then the footer |
| Cockpit (`/cockpit/`) | `.loop-ribbon` (wayfinding, not a close) + footer | Ribbon orients but doesn't propose an action; nothing *pulls* toward the data | `.loop-forward` → `/data/` ("see what's driving today's read") |
| Data (`/data/*`, 47 pages) | Ribbon + footer | Same as above — a reader who finished a topic readout had no prompt toward the AI's take on it | `.loop-forward` → `/coaching/` ("see what the AI team makes of it") |
| Coaching (`/coaching/*`, 8 pages) | Ribbon + footer | No prompt from "the AI's opinion" to "the levers it implies" | `.loop-forward` → `/protocols/` ("see what levers get pulled next") |
| Protocols (`/protocols/*`, 6 pages) | Ribbon + footer | No prompt from "the lever" to "did it work" | `.loop-forward` → `/story/` ("follow whether it moved anything") |
| Story (`/story/*`, 10 pages) | Ribbon + footer | No prompt back to the live instrument after reading the narrative | `.loop-forward` → `/cockpit/` ("check today's live read") |
| Method (`/method/*`, nav-highlights Data) | Ribbon (unmarked — footer-tier) + footer | Deepest-credibility pages had the *weakest* close — just the directory | `.loop-forward` → `/coaching/` (inherits Data's next station) |
| `/gear/`, home-adjacent utility pages (privacy, subscribe, 404, the essay) | Footer only, no ribbon | These had no forward signal at all beyond the sitemap | `.loop-forward` → `/cockpit/` (`DEFAULT_NEXT`) |
| `/subscribe/`, `/subscribe/confirm/` | Footer only | The universal return trigger would have self-linked ("follow by email" while already on the follow page) | Swapped to "keep exploring the loop" → `/` (audit finding, fixed in the same mechanism — see `_RETURN_SELF_SWAP` in `v4_chrome.py`) |
| `/mind/`, `/subscribe.html` (redirect stubs) | No chrome at all (by design — instant redirect) | N/A — not a real page a reader lands on | Unchanged; deliberately excluded (verified by `test_redirect_stubs_stay_chrome_free`) |

**Finding, in one line:** every door's only close was the mega-menu — a map, not a
decision — and two utility pages would have self-linked under a naive universal return
trigger. Both are now fixed structurally, not per-page.

## The mechanism: `loop_forward`

`scripts/v4_chrome.py::loop_forward(current_door, self_path=None)` is the single source
(alongside `doors_nav` and `site_footer`, #1009). It's keyed off the *same* detected door
as the doors nav (not `v4_kit.loop_ribbon`'s short-key scheme) — see its docstring for
why Method/registry/game correctly inherit Data's next station rather than getting no
next station at all.

Two paths ship it on every page:
1. **`scripts/v4_apply_chrome.py`** — the authoritative post-build chrome pass (runs last
   in `sync_site_to_s3.sh`) inserts/re-flattens the canonical `.loop-forward` on every
   page carrying a doors nav, keyed off the door it already detects. This is what makes
   "zero dead-end pages" a structural sweep over the real `site/` tree rather than a
   hand-maintained list — any future page that ships with the standard doors nav
   automatically gets one.
2. **`scripts/v4_build_game_explained.py`** additionally calls `loop_forward()` directly
   in its own shell template, because `tests/test_game_explained.py` enforces that the
   committed page equals the *raw generator output* byte-for-byte (a stronger guarantee
   than the apply-chrome safety net for that one page).

## Zero dead-end pages — verified

`tests/test_site_chrome.py::test_every_content_page_has_one_loop_forward_close_before_the_footer`
walks every non-legacy page under `site/`, asserts every doors-nav page carries exactly
one `.loop-forward` with a real (non-empty, non-`#`) forward link positioned before the
footer, and asserts the sweep actually ran over something (guards against the check
silently no-op'ing). `test_loop_forward_never_self_links_the_return_trigger` pins the
subscribe-page audit finding both ways. `scripts/v4_apply_chrome.py --check` (already in
the CI Unit Tests gate via `test_apply_chrome_check_is_green`) fails the build if any page
drifts from the canonical partial.

At the time of writing: 80 non-legacy HTML files in `site/`, 78 carry a doors nav (and
now a loop-forward close), 2 are the redirect stubs (`/mind/`, `/subscribe.html`)
correctly excluded by construction.
