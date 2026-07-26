# Portrait art-direction v2 option round — 2026-07-25 (#1114, awaiting the ADR-106 gate)

**The verified complaint (issue #1114):** at 96px — the `coach-head` call sites in
`coaching.js` (`/coaching/`, `/story/` panel heads), the ONLY framed size in practice —
the §8.7 seeded sigil-ring frame (full circle + radial measuring ticks) reads as a
**clock**, and the uniform 1.7px non-scaling engraved ink reads as a **mask**. Verified
art-direction complaint, not a renderer bug (no 40–95 frame call site exists; cockpit
passes 22, popovers 18, dispatches 26/32).

Four code-generated directions, each a coherent **frame composition × engraved-ink
treatment**, rendered through the REAL shipped renderer (`portraits.js renderPortrait`)
inside the REAL 96px coach-head context (tokens.css + story.css, `.portrait-lg`),
light + dark, plus a 40/56/96 consistency strip per option. Baseline (as shipped
today) renders first for honest comparison.

## The options

| id | frame | ink (sil / feat / frame px) | one-line claim |
|---|---|---|---|
| **A — unframed, weighted ink** | none, at any size | 1.8 / 1.05 / — | kills the clock by removal; two-weight ink gives the face a drawn hierarchy so it stops reading as a die-cut mask |
| **B — open arc** | one 235° arc, seeded upper gap, coach-accent dot on the trailing end | 1.7 / 1.3 / 1.1 | keeps the instrument vocabulary as a single engraving flourish — an arc with an upper gap can never close into a dial |
| **C — arch niche** | open-bottom engraved arch (round top, sides run off the bottom edge), seeded coach-accent dot at a side terminus | 1.7 / 1.25 / 1.0 | the classic portrait-cartouche idiom — nothing radial, nothing closed, so neither clock nor photo-frame can read |
| **D — quiet ring** | the same circle, ticks deleted | 1.7 / 1.25 / 0.9 @ opacity 0.22 | the minimal-delta fix: deleting the ticks deletes the clock; hairline weight demotes the ring to atmosphere |

`sil` = silhouette layers (head/hair/bust) · `feat` = facial features
(brow/eyes/glasses/nose/mouth). Frame geometry is an explicit, schema-valid `frame`
layer in each candidate recipe — the shipped renderer draws it as-is. Ink weights are
recorded in `_meta.option.ink` and applied on the sheet as a post-render stroke-width
transform (recipe data cannot express weights today — the chosen direction ships that
as the `portraits.js` change, replacing the fixed 1.7 and, for A, the seeded-frame
composition).

## Reproduction (deterministic — same inputs, byte-identical output)

```bash
python3 docs/design/portrait_candidates/2026-07-25/make_options.py               # candidate recipes (review trio)
python3 docs/design/portrait_candidates/2026-07-25/make_options.py --cast full   # all 10 shipped recipes (post-approval regen)
python3 docs/design/portrait_candidates/2026-07-25/render_sheet.py               # sheet.html + renders/*.png (needs playwright chromium)
```

Candidates derive from the SIGNED shipped recipes (`config/portraits/<pid>.json`),
carry `_meta.derived_from` + `_meta.option` provenance, and are **UNSIGNED** — the
bundler (`v4_build_portraits.py`) can never ship them. Review trio: elena_voss (oblong
base, the lead card), lisa_park (circle base), james_okafor (the bald + glasses
construction) — maximum shape-language spread for judging a frame direction.

## Solo render-review log (runbook §2 discipline)

- **Round 1** (rendered, critiqued at 96px in-situ, both themes):
  - Baseline confirms the complaint verbatim — the ring + ticks is unmistakably a clock face.
  - A: strong; the lead card's own border does the framing work, unframed reads clean.
  - B: arc composition works, but the accent dot (r 1.9 viewBox units ≈ 1.8px on
    screen at 96) was sub-visible, and the 70° gap band let arc ends fall
    near-horizontal into the face.
  - C (was "cartouche plate", a CLOSED rounded rect): read as a phone/photo-booth
    frame and double-framed the lead card. Rejected in-round.
  - D: quiet, honest minimal delta; no further notes.
- **Round 2** (this committed set): B dot r 2.6 + gap band tightened to 60°;
  C rebuilt as the open-bottom arch niche with a side-terminus accent dot.
  All four verified at 96px in-situ, light + dark, plus the 40/56/96 strip.

## Status: awaiting Matthew's ADR-106 gate (the open PR's purpose)

Review sheet (renders/ inlined, both themes):
https://claude.ai/code/artifact/fd385c18-9ed4-4884-a26e-aba6c7b020be — or view
`renders/*.png` directly in this directory.

Per ADR-106 only Matthew approves a direction — that acceptance criterion cannot be
completed by an agent. On approval: implement the chosen direction's ink/frame rules
in `portraits.js` (and the `web/portrait_raster.py` mirror), regenerate the FULL cast
via `make_options.py --cast full` logic folded into the chosen form, re-run the
contact-sheet gate on the full cast (40/56/96, light + dark, sigil-beside — runbook
§3), record `_meta.sign_off`, rebundle `portrait_data.js`, ship, visual-QA. On kill:
delete this directory; the shipped cast is untouched (nothing here is bundled).
