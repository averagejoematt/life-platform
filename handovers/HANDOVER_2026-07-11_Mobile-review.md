# HANDOVER — Mobile experience review: full-surface phone sweep → 5 epics + 19 stories + 3 accuracy issues filed (#997–#1023), zero code shipped by design — 2026-07-11

> Instruction: "i dont think the mobile app experience is quite as good as the website, can
> you do a full review and put a plan together broken into epics and issues on what you
> think is a good solution that would be endorsed by technical architects also in terms of
> scalability, ease to maintain between updates etc." → then "get all of this in the plan
> into git and wrap this session so i can begin it all in a new session."

## What ran

Review-only session — deliberately NO fixes shipped; everything landed as backlog. Five
parallel agents against the LIVE site (build 21034c4): four render-QA sweeps (Playwright
390×844 @DPR3 + 360×800 spot-checks, touch, iPhone UA — core/cockpit, data wing ×16,
coaching+protocols ×14, story+method ×18; measured geometry + screenshots + probe JSONs
in the session scratchpad) + one Explore architecture review of the responsive layer
(CSS/breakpoints, app-bar, PWA, charts, tables, CI coverage, design-system doc). Both
critical root causes re-verified in source by the driver before filing. Then the
issue-filer agent landed the plan per ADR-099 (dedup vs. 37 open issues: clean).

## The headline findings (all verified)

1. **Scroll-reveal never fires on tall sections (CRITICAL)** — `/protocols/challenges/`
   (80 cards, ~22,600px section) and `/protocols/experiments/` (60 cards) render as blank
   scroll; cards stuck `opacity:0`. Root cause verified: `.rd-sec` in the reveal selector
   (`motion.js:248`) + `threshold: 0.1` (`motion.js:260`) — a 22,600px section can never
   get 10% into an 844px viewport (max ≈3.7%). Challenges is blank on DESKTOP too.
2. **Bottom app-bar overflows every page (MAJOR)** — follow CTA an 11px sliver, theme
   toggle clipped at 390px / fully unreachable at 360px, 5th door truncates to "TH / STO".
   Root cause verified: specificity collision between two `!important` rules — `.doors a
   { display:flex !important }` (`tokens.css:1008`, 0,1,1) resurrects the intentionally
   hidden `.nav-follow` (`tokens.css:1026`, 0,1,0); the `<button>` theme toggle gets no
   `flex:1` and overflows the fixed non-scrollable bar.
3. **Structural layer debt** — 17 hardcoded breakpoints across 6 CSS files (no token; four
   competing "phone" boundaries), app-bar built on ~12 `!important`s (load-order-dependent
   by design), no shared responsive-table primitive, doors-nav markup copy-pasted in ~70
   HTML files (home/now vs subscribe already drifted), pre-merge CI gate is desktop-only
   (1440×900 — the 390px overflow-only check runs post-deploy), and `DESIGN_SYSTEM_V5.md`
   has ZERO occurrences of mobile/responsive/touch.
4. **What's genuinely good** (the plan deliberately keeps it): zero horizontal overflow on
   all 55+ pages, Pointer-Events chart grammar (not hover-first), safe-area-aware app-bar
   anchoring (the old backdrop-filter bug did NOT reproduce), healthy PWA (manifest + active
   SW), honest pre-start states everywhere, comfortable prose measure. The board-ratified
   one-responsive-codebase decision (2026-06-14) holds — review found nothing to overturn it.

## What was filed (the plan — all on GitHub, ADR-099 contract, evidence + acceptance + score lines)

- **#997 EPIC A (Now) — launch-critical defects**: #1002 scroll-reveal threshold (fix in
  motion.js, height-aware — protects all future tall sections), #1003 app-bar overflow,
  #1004 subscribe.html missing viewport meta (verified, one line), #1005 /method/explorer/
  dead "preserved Explorer" promise (broken on desktop too).
- **#998 EPIC B (Next) — responsive foundation**: #1006 breakpoint tokens (17→3-4),
  #1007 app-bar rebuild without the `!important` war, #1008 shared table primitive +
  labs polish, #1009 shared-chrome build partial (~70-file copy-paste), #1010 44px
  tap-target pass (scrubber 117×22, "×" 28×24, toggle 26×28, checkbox 13×13…), #1011
  DESIGN_SYSTEM_V5 mobile section as spec.
- **#999 EPIC C (Next) — mobile in CI**: #1012 390/360 in the pre-merge render gate,
  #1013 assert the discovered failure classes in visual_qa.py (app-bar width, stuck
  opacity:0 reveals, viewport meta, tap-target audit).
- **#1000 EPIC D (Later) — IA & wayfinding**: #1014 sub-nav for deep trees + real links on
  /method/ hub cards, #1015 anchors for 15–19-screen pages (labs/character), #1016 "Pick a
  topic on the left" copy ×16 pages, #1017 constellation 8–9px labels (post-genesis).
- **#1001 EPIC E (Later) — perf & PWA**: #1018 panelcast 16.6MB WAV→AAC, #1019 loading
  skeletons (/story/agents/ 6–9s bare "Loading the week…"), #1020 SW coverage (18/161
  pages) + build-hash cache VERSION.
- **Accuracy lane (no epic)**: #1021 /story/timeline/ Day-1 self-contradiction (Now),
  #1022 /method/cost/ stale $75 ceiling vs ADR-133 $85 (Now), #1023 /privacy/ "no
  affiliate" vs /gear/ affiliate disclosure (Next, Matthew's call).

## Verification

No code changed → no deploys, no test runs needed. Verification was of the findings
themselves: 4 independent sweeps cross-confirmed the app-bar defect with measured rects;
the two critical root causes re-verified in source (`motion.js:248,260`,
`tokens.css:1008` vs `:1026`); subscribe.html viewport-meta absence confirmed by grep;
issue-filer verified all 27 issues via `gh issue view` post-creation.

## Gotchas hit

- **Two `!important` rules can silently fight across selectors** — `.doors a` (0,1,1)
  beats `.nav-follow` (0,1,0); the mobile-hide worked until the app-bar flex rule
  resurrected the pill. `!important` doesn't end the specificity contest, it just moves it.
- **IntersectionObserver `threshold: 0.1` is a time bomb on unbounded-height sections** —
  fires fine until a section grows past ~10 viewport-heights, then never. Any reveal
  wrapper over a data-driven list will eventually hit it.
- Render-QA full-page PNGs of very tall pages show phantom blanks at DPR3 — the agents
  correctly re-verified with live viewport probes before calling blanks real (good
  pattern to keep).
- This wrap found the concurrent T−1 daytime session's wrap uncommitted (staged handover
  rename + untracked LATEST); both wraps folded into this one commit — its narrative is
  intact at `handovers/HANDOVER_2026-07-11_Now-paydown.md`.

## Next picks

1. **Epic A (#997) before or on Day 1** — #1002 and #1003 hit every mobile reader on
   launch day; both are small, root-caused, ready to implement. #1021/#1022 (accuracy,
   Now) are quick copy/data fixes in the same pass.
2. Then Epic B + C together (foundation + the CI gate that keeps it fixed).
3. **Matthew Sunday (carried from the T−1 handovers):** weigh-in → pipeline re-run →
   `fix_prologue_cycle_and_subscribe_ttl.py --apply` → re-run
   `seed_genesis_preregistration.py --apply` + `publish_genesis_preregistration.py
   --apply` (wipe takes prereg records; frozen claims re-land verbatim).
4. Still open from prior sessions: #741 (Matthew-gated publish), char-math #956 stories,
   #977.

**Build beat:** none — review-only session; nothing merged or deployed (the plan itself
landed as issues #997–#1023).

**Docs:** none needed — no shipped code/site changes to document; the one doc gap found
(DESIGN_SYSTEM_V5 has no mobile section) is deliberately filed as story #1011, not
patched at wrap.
