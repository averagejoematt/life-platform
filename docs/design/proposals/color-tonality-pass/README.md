# Color & surface tonality pass v5.1 — the paper-elevation ramp (#1470)

Review artifacts for the #1470 tonality pass. The design itself lives in
`site/assets/css/tokens.css` §1 (the ramp) + §9 (the light leg); the standard is
documented in `docs/DESIGN_SYSTEM_V5.md` §4a and enforced by
`tests/test_paper_ramp_contrast.py`.

`render/` — before/after captures from the local render harness
(`tests/pr_render_gate.py` serve + mocks; Chromium, `color_scheme` emulation):

- `*-dark-home.png` — 1280px dark home: the bumped `--ink-faint` label register
  (AA on every ramp step) + tonal steps.
- `*-dark-character.png` — full-page dark method/character: the tile ramp.
- `*-light-mobile-story.png` — 390px light story: the app-bar as raised warm
  paper (`--surface-raised` un-inverted — it previously DARKENED in light mode).

Empty-state light desktop pages are pixel-identical before/after by design —
the light deltas concentrate on floating chrome (app-bar, popovers, tooltips,
sticky TOC), the sunken code wells, and data-populated rails.
