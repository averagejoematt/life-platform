# HANDOVER — fable queue at ZERO; the team view comes back + the beat lands — 2026-07-05 (session 14)

Session opened on "work on all fable items in backlog" with Matthew authorizing all merges and
deploys up front. **The fable backlog is EMPTY** — all 36 `model:fable` issues are CLOSED
(verified `gh issue list --search "label:model:fable" --state all`); every open story is
deliberately `model:opus`/`model:sonnet` ("don't spend Fable tokens here" per the label scheme).
The fable-tier work remaining was the session-13 handover's own Next list; both flagged items
shipped in **PR #622** (squash `49182230`, merged + deployed + live-verified 8/8).

---

## What shipped (PR #622)

1. **The collective "My Team" read re-mounted (the orphan resolved).** coaching.js's "The Team"
   section now leads with a "My Team" entry rendering the CC-10 collective read
   (`/api/coach_team`): Marsh's lead block — **his signed portrait is reachable again** — staff
   focus, live tensions, and the 8-coach huddle with click-through to each profile. The
   handover's "re-mount or retire" fork resolved as BOTH: re-mount on the coaching door (its
   natural home; matches the section's existing lead-entry pattern), retire the orphan.
2. **A deep-link bug found and fixed along the way:** `/coaching/coaches/` set
   `__COACHING_START__ = "coaches"` — a key NOT in coaching.js BYKEY, so the page silently fell
   back to The Read and dropped `#coach` deep links. Podcast guest bylines, old
   `/story/coaches/` 301s, AND every coach_popover "full page →" link were landing wrong. Now
   starts at the team section, where entry ids are persona ids, so `#nutrition_coach` resolves.
3. **dispatches.js retired:** the dead `kind:"coaches"` machinery deleted (renderTeamView,
   renderCoachPage + 5 HTML helpers, both branches, the unused `sigil` import) — no story-door
   section has mounted it since v4. Net −107 lines.
4. **Session-13's build beat distilled** ("The whole cast gets faces — seven portraits, one
   review round") — appended to beats.json per BUILD_DISPATCH_CHECKLIST.md, narrating PRs
   #618/#619 with the ear-line gotcha and honest misses (including the then-unreachable Marsh
   portrait, which this same PR fixed). Content-policy scan PASS. Live on /story/build/.

## Gotchas learned

1. **The site's service worker bypasses Playwright `page.route` mocks.** Local render QA must
   create the browser context with `service_workers="block"`, or in-page API fetches after the
   first load silently 404 against the static server while the initial fetches mock fine —
   a confusing half-working state. (This extends the route-mocked local-QA recipe.)
2. **Motion.js scroll-reveals make full-page screenshots lie:** below-fold sections sit at
   opacity 0 until intersected, so a full-page shot shows blank space where content exists.
   Verify with DOM counts/offsetHeight, or scroll_into_view before shooting.

## Verification

- Local Playwright render QA (route-mocked live-prod fixtures): **11/11 PASS**, including the
  deep-link case `/coaching/coaches/#nutrition_coach` → Webb's team profile.
- PR #622 CI green → squash-merged → `deploy/sync_site_to_s3.sh` from main →
  `version.json == 49182230` → **live verification 8/8 PASS** (My Team leads, Marsh portrait
  SVG, huddle, deep link, beat on build log, zero page errors). Ship-commit "v4 site gate"
  completed SUCCESS before close.

## Watch

- **Sun 07-06** (unchanged): journal-seeded hypothesis engine; panelcast v2; inter-coach
  dialogue SKIPS. **Mon 07-07**: data-recon on derived rows.
- Forecast resolutions accruing since 07-05 (cockpit coverage line at n≥1);
  slo-source-freshness 7-day window from 07-04.
- **GitHub Pages still enabled + public on the repo** (session-13 flag, unactioned — Matthew's
  call: disable or bless).

## Next

- **Session-14's own beat slot is OPEN** (the shipped beat narrates session 13, per the
  one-beat-per-session carry pattern). The team-view resurrection + the deep-link fix is a
  small honest candidate for next session's beat.
- **Fable-tier backlog: NONE.** A next fable session should either (a) triage fresh fable-tier
  stories out of the epics (#525–#528 / #575) as they reach Now, or (b) run `/uplevel` for a
  fresh-eyes flagship slice. The Now milestone (#577–#581) is all sonnet/opus — cheaper
  sessions by design.
- Nakamura's portrait when a head surface exists; Murthy rename decision if he ever needs a
  head; Cora Vance when the reading surface lands; speaking mouth-frames (mouth-a/b) still
  undriven.
