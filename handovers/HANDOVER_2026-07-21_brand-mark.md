# HANDOVER — The AJM brand mark lands (favicon + app icons + header) — 2026-07-21

> Instruction thread: "review these images from claude design and look to incorporate
> the logo appropriately and also the favicon (items 3a), if we need to do a plan first,
> do that" → "cant you get the images from here <claude.ai/design URL>" → plan approved →
> "ok yes i agree with your recommendations" (file the two deferred follow-ups) →
> "i approve you to do all merge and deploys but be conscious of parallel session" →
> "can you /wrap once done". A parallel session was active throughout (multiple worktrees
> on issue-1472/1482/1621/1624 etc.) — every merge/deploy checked for file overlap first.

## What shipped — PR #1638 (MERGED `0e5ac940`, DEPLOYED, live)

The AJM dial mark from the Claude Design project "AJM Logo Marks", **direction 3a** —
the full-gauge dial with a single ember graduation at the 1-o'clock tick. The site had
never had a logo: the header brand was a bare 11px ember square, the favicon a 32×32 PNG
misnamed `.ico` from May 19.

**Source of truth = `scripts/build_brand_assets.py`.** Three hand-authored masters in
`site/assets/marks/` (`mark-a.svg` single-A, `mark-ajm.svg` monogram, `lockup.svg`
wordmark); everything else generated and re-checkable with `--check`. Assets pulled from
the design project via the DesignSync tool.

Surfaces changed (all at **existing stable paths → zero HTML edits**, all 134 pages pick
it up): `site/favicon.ico`, `apple-touch-icon{,-precomposed}.png`, `assets/icons/icon-{192,512}.png`,
new `icon-maskable-512.png`, `manifest.webmanifest` (+maskable entry), and `--brand-mark`
token in `tokens.css` consumed by the three `.brand-mark` rules (cockpit/evidence/story.css).
`design_sync_bundle.py` now carries the marks as a foundation.

## Two decisions worth knowing (both diverged from the approved plan — for good reasons)

1. **Header uses the single-A, not the AJM monogram.** Built it with the monogram first,
   A/B-rendered at the real 20px size: "AJM" collapses to texture, the "A" stays legible.
   Bonus — the tab icon and header mark are now the *same* mark. This is the design doc's
   own favicon rule, extended to the other small surface.
2. **`--brand-mark` is a token in `tokens.css`, NOT a rule keyed to `[data-theme="light"]`
   (which the plan said).** Light mode activates on TWO legs — the OS media query AND the
   explicit toggle — and only `tokens.css` spells both out. The attribute-only rule I'd
   planned would have shipped a dark mark on light paper for any OS-light reader who never
   touched the toggle. Verified the OS-light leg resolves the light variant.

## Verified

- **Text-outlining is real and correct** — the delivered SVGs set letters as live
  `<text font-family='IBM Plex Mono'>` with an empty `<defs>` (the doc's "embedded 13KB
  subset" claim is false); as an `<img>`/favicon/crawler-fetch that falls back to platform
  monospace. Script outlines against the site's own self-hosted Plex Mono Medium via
  fontTools; rendered outlined-vs-live-font side-by-side, letterforms identical. `grep -c
  '<text'` on every generated file = 0.
- **Relative `url(../marks/…)` resolves at every page depth** (0/1/3) → same absolute path,
  HTTP 200. Chosen over absolute because a CSS `url()` resolves against the stylesheet, so
  it's correct sitewide AND portable into the design-sync bundle (which forbids absolute url).
- **Header height unchanged at 53px** across home/cockpit/data/story × dark/light.
- **Suite 6364 passed** (56 skip, 10 xfail); black/flake8/ruff/pii_surface_guard clean.
  `build_brand_assets.py --check` confirms reproducible output.
- **Live surface** (post-deploy curl): favicon.ico = new 32px A-dial (1186b, was 1482b),
  header marks + maskable + manifest(+maskable) all 200, deployed `tokens.css` references
  the relative mark URL.
- **Deploy `0e5ac940`: site-deploy run 29869883945 = success** — Deploy + Site smoke +
  Visual+AI-vision QA all green, auto-rollback did NOT fire.

## Gotchas hit

- **Playwright screenshot rejects a `.ico` path** (dispatches encoder off extension). Fix:
  screenshot to a temp `.png`, copy to the `.ico` name — favicon.ico has always been a PNG.
- **design_sync_bundle forbids absolute `url(/…)`** (`_URL_ABS_RE`) — my first pass used
  `url(/assets/marks/…)` and reded `test_design_sync_bundle`. Switched to relative + taught
  the bundler to copy `mark-header-*.svg` into `marks/`.
- **`tokens.css` has TWO light-mode legs that a test asserts stay identical**
  (`test_paper_ramp_contrast`) — the `--brand-mark` token had to be added to all three
  declarations (root-dark, @media-light, explicit-light).

## Parallel-session hygiene

Confirmed zero file overlap between #1638 and the parallel `issue-1624-first-earn-ledger`
branch, and main's newer commits (July-ceiling #1635, Reddit playbook #1636) don't touch
`site/`. Merge + deploy fully isolated. Nothing to hand off to the other session.

## Residual / next picks

- **#1639** — head-chrome drift: 61 of 82 pages ship no manifest/apple-touch-icon/theme-color,
  and no page offers the SVG favicon; give `v4_apply_chrome.py` ownership of the `<head>`
  block with a `--check` gate (Next, area:site-ux, model:sonnet).
- **#1640** — brand mark on the 13 OG share cards via `card_engine.draw_footer()` (Next,
  area:growth, model:sonnet). Traps documented in the issue: Pillow can't rasterise SVG,
  asset must ship via `build_bundle.py`, use the AJM monogram not the single-A.
- **not-work — owner** — confirm whether `lockup-{dark,light}.svg` (committed, currently
  unused on-site) is the intended YouTube-banner/social-profile asset for epic #1619, or
  should be pruned. It was included deliberately per the design doc delivery table.

**Build beat:** `2026-07-21-the-brand-mark`
**Docs:** none needed — no deploy path / data model / ADR / MCP-tool / secret surface changed;
brand assets are self-documented in `site/assets/marks/README.md` (shipped in #1638).
**Decisions:** none needed — the two divergences (single-A header, token-not-attribute) are
implementation choices, not governance posture; both captured above and in the PR.
**Incidents:** none — deploy 29869883945 green, auto-rollback did not fire.
**Main:** red — pre-existing CDK Plan drift (pending owner `cdk deploy`: Lambda bundle-hash S3Key
churn + a nodejs22→24 runtime bump on the CDK LogRetention helper), red across 6+ prior commits,
unrelated to this session. My brand-mark change is site-only and deployed **green** via the separate
Site-deploy workflow (run 29869883945). **not-work — owner** runs the pending `cdk deploy`.
**Stash/hooks:** clean
