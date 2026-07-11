# HANDOVER — Mobile plan executed end-to-end: Epics A + B + C shipped & live (16 issues, PRs #1030–#1038) — 2026-07-11

> Instruction: "read handover and memory and lets work on the mobile fixes" → "i approve
> all merges and deploys" → (after Epic A + C + B#1006/#1008 shipped) "ok do it" to the
> Epic B + C plan → chose **"Do all of Epic B now"** and **"Do #1009 now, full partial"**
> at the two decision points → "good to /wrap then /clear?"

## What ran

Executed the ENTIRE filed mobile plan (the 2026-07-11 review's Epics A/B/C) end-to-end —
not review-only this time. **16 issues closed, 8 PRs merged + deployed, 1 tests-only PR,
9 site deploys** (one caught auto-rollback, recovered). Every site deploy passed the
visual + AI-vision QA gate. Sequenced Epic C FIRST so its mobile CI gate protected all
subsequent Epic B PRs (it did — caught an app-bar-overflow regression mid-#1010).

## What shipped (all merged to main + deployed live, verified)

**Epic A #997 — launch-critical reader bugs (PR #1030):**
- #1002 scroll-reveal height-independent `threshold:0` (blank challenges/experiments backlogs fixed)
- #1003 app-bar overflow / unreachable toggle — `:not(.nav-follow)` + icon-over-label column
- #1004 subscribe.html viewport meta · #1005 dead "preserved Explorer" copy · #1022 $75→$85 ceiling

**Epic C #999 — mobile in CI, landed first (PR #1031, tests-only, no deploy):**
- #1012 390+360 viewports in `pr_render_gate.py` · #1013 the Epic-A failure classes asserted
  in `visual_qa.py` (app-bar overflow / stuck reveals / viewport meta gating; tap audit advisory)

**Epic B #998 — foundation (PRs #1032, #1033+#1034, #1035, #1036, #1037, #1038):**
- #1006 17 breakpoints → 6 canonical boundaries (max=token / min=token+1 convention) — #1032
- #1008 `.table-scroll` primitive + labs polish — #1033 **auto-rolled-back** (data-driven
  /data/vitals/ +255px overflow the empty-mock gate missed), fixed forward #1034 (width:100% + restore .rd-sec)
- #1007 bottom app-bar rebuilt with CSS `@layer chrome-base, chrome` — **!important 16→0** — #1035
- #1010 44px tap-target floor (vertical `::after` overlays, form min-heights, label-tap) — #1036
- #1011 DESIGN_SYSTEM_V5 §10 mobile spec (doc had zero mobile content before) — #1037
- #1009 shared-chrome build partial (`scripts/v4_chrome.py` + `v4_apply_chrome.py`, run
  LAST by `sync_site_to_s3.sh`) — killed 5-nav/7-footer drift, 5 icon-less pages gained
  door icons, footer unified UP so no wayfinding lost, 45 canonical pages byte-identical — #1038

## Verification

Every merged PR: local `pr_render_gate.py` 8/8 + CI render gate green before merge. Every
site deploy: smoke + visual + AI-vision QA green (the one #1008 FAIL auto-rolled-back and
was fixed forward). #1007 verified across all 10 door types × 4 widths (360/390/768/1366)
by measured geometry. #1009 verified: canonical `/data/`+`/method/` pages byte-identical
(the safety property), diffs confined to nav/footer spans, subscribe door icons confirmed
LIVE. Live build `1ef8ed1`. Epic trackers #997/#998/#999 all closed.

## Gotchas hit

- **The render gate mocks APIs EMPTY → blind to data-driven overflow.** #1008 passed the
  gate locally + in CI but blew out /data/vitals/ +255px under REAL data; only the live
  visual-AI QA + auto-rollback caught it. Fix-forward: `width:100%` block-scroll (never
  `width:auto`) + restore the `.rd-sec { overflow-x:auto }` section-scroll for wide NON-table
  content. **A realistic-data pass in the gate is worth filing.** (See [[reference_local_render_qa]].)
- **`@layer` de-overlap:** a naïve breakpoint collapse (759→760) reintroduces a min/max
  boundary double-fire; convention is max-width=token, min-width=token+1. And a max-width
  token−1 blanket shift broke the 600 chrome boundary (desktop nav overflowed at exactly 600px).
- **Tap-target `::after` overlay overflows at the right edge** — a `max(100%,44px)`-wide
  overlay on the app-bar's rightmost toggle pushed past the fixed bar (the #1003 assertion I'd
  just built caught it). Expand overlays VERTICALLY only near edges.
- **`now/index.html`'s doors nav had no `</nav>`** (browser auto-closes) — a naïve regex
  over-matched; the apply script anchors on the theme-toggle `<button>` with `</nav>` optional.
- **Careless `git stash -u` during review** captured settings.local.json into the shared
  stash stack — popped it back; the other 3 stashes belong to other sessions, left alone.
  (Reinforces [[reference_git_stash_shared_across_worktrees]] — don't stash in this repo.)

## Next picks / residual

- **Epics D (#1000 wayfinding) + E (#1001 perf/PWA)** remain on Later, untouched by design.
- **File:** a realistic-data pass for `pr_render_gate.py` (the empty-mock blind spot that
  cost the #1008 rollback).
- **Matthew Sunday queue (unchanged, carried):** weigh-in → pipeline re-run →
  `fix_prologue_cycle_and_subscribe_ttl.py --apply` → `seed_genesis_preregistration.py --apply`
  + `publish_genesis_preregistration.py --apply`. Plus the timeline accuracy issue #1021
  (Day-1 self-contradiction) — deliberately left for the pipeline-crossing context, not a mobile fix.
- Still open from prior sessions: #741, char-math #956, #977; laptop-resilience #1024–#1029.

**Build beat:** mobile-plan-executed (see below) — Epics A/B/C all merged + deployed live.

**Docs:** DESIGN_SYSTEM_V5.md §10 (new mobile spec, #1011) + SITE_UPLEVEL_PLAYBOOK.md
cross-link shipped IN the work; SITE_AUTHORING.md updated by #1009 for the chrome-partial
build step. No further wrap-time doc updates needed — the shipped work carried its own docs.
