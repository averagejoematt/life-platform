# Coach Portrait Runbook — commissioning, style bible, onboarding

**Authority:** ADR-106 (the commissioning rule) + DESIGN_SYSTEM_V5 §8.7. This runbook is the
procedure; if it ever disagrees with the ADR, the ADR wins. Renderer + schema live in story #586
(`site/assets/js/portraits.js`, `config/portraits/`); the pilot commissioning is story #587.

The one-sentence version: **AI may sketch, only code ships, only Matthew approves.**

---

## 1. The style bible — "commissioned character identity"

> **Amended 2026-07-05 with the pilot approval (#587, rounds 1–4).** The original bible said
> engraved stroke-only line work; the taste gate steered to **flat-vector character
> illustration** — animated-TV register, full character colour. The four gate rounds are the
> provenance: "they look the same" → distinct facial constructions; "less sketch, more
> animated" → filled duotone; "identifiable like animated-film characters, no name needed" →
> shape language + owned palettes (this standard). Photoreal remains NO-GO (ADR-106 §5).

The bar, verbatim from the gate: **a reader who has followed for a few weeks knows who is who
without the name next to them.**

**Shape language (the recognisability engine)**
- **Each coach is built on a distinct geometric base** — e.g. Elena oblong, Park circle,
  Chen wedge. A new portrait must claim a base not already in the cast, or differentiate
  hard within one.
- **One hyper-distinctive feature per coach**, carried by silhouette (hair mass, accessory,
  collar): the slate-streak bob · the pinned top-bun · the swooping ponytail. Never props
  overload — ONE quiet wardrobe cue (collar style, zip line) at most.
- **The silhouette litmus is mandatory on every contact sheet:** render the batch as solid
  single-colour shapes, no faces, no names. If reviewers can't tell who is who, the designs
  fail before Matthew ever sees a face.
- **viewBox `0 0 100 120`** (renderer contract, #586). Eye-line ≈ y 45–47; bust runs off the
  bottom edge (no floating heads).

**Colour (the tone palette — schema `palette` + per-element `tone`, PR #612)**
- Filled masses carry the character: hair, wardrobe, skin, blush — each a flat hex in the
  recipe's validated `palette` (`skin/hair/cloth/blush/line`); **`accent` always resolves to
  the coach identity channel** (`var(--coach)`) and should appear somewhere signature (Elena's
  streak, Chen's headband/elastic).
- **Flat colour only** — no gradients, no soft shading (that way lies the photoreal NO-GO).
  Mid-value hexes that read on both themes; the contact sheet shows light AND dark, always.
- **Skin tones are in the language** (amended): flat, stylised, derived from the persona
  document's own identity — drawn respectfully and reviewed at the gate like everything else.
- Ink contours (`stroke="currentColor"`, 1.7 non-scaling, round caps) stay on top of the fills
  so portraits still sit in the site's drawn idiom next to the sigils.
- **Line budget: ≤ 48 stroked elements (target 22–35); fills are free.**

**Face rules (the uncanny guards — unchanged)**
- **No teeth, ever.** Mouths closed or lip-shapes; `mouth-a`/`mouth-b` stay closed-lip.
- **Pupil-size guard:** filled circles r 1.4–2.3. `eyes-open` must include pupils;
  `eyes-closed` is a lid line per eye (the blink frame).
- Almond lid shapes + a lid-crease stroke read "animated realistic"; avoid full-round
  passport stares except where the construction calls for it (Park's big open eyes).

**The fixed layer schema** (ids are the renderer contract — all optional except `head`):

| layer id | content | animated by |
|---|---|---|
| `frame` | optional ring/arc composing the sigil-as-frame at ≥ 40 px | draw-in |
| `bust` | shoulders, collar, bust cut | draw-in |
| `head` | face outline + ears | draw-in |
| `hair` | the silhouette-defining mass | draw-in |
| `brow` | brow lines | draw-in |
| `eyes-open` | lids + pupils (default visible) | blink (swap) |
| `eyes-closed` | lid lines (default hidden) | blink (swap) |
| `glasses` | optional | draw-in |
| `nose` | nose line | draw-in |
| `mouth-rest` | resting mouth (default visible) | — |
| `mouth-a` / `mouth-b` | optional closed-lip variants (default hidden) | future speaking states |
| `hatch` | engraved shading strokes — the ONE `var(--coach)` accent layer | breath (subtle) |

---

## 2. Commissioning a batch (the only sanctioned AI-image workflow)

1. **Ground in the persona document.** Pull the coach's `config/board_of_directors.json` block
   (voice, personality, relationship notes). Write a one-paragraph physical brief per persona
   *derived from what the record already implies* (Park's pinned hair, Chen's mesocycle
   precision) — the brief is checked in with the batch notes.
2. **One pinned-style generation session.** A single session, one style prompt pinned across all
   candidates (engraved bust, ¾ view, stroke-only line art, plate-engraving idiom). **6–10
   reference candidates per persona.** References live OUTSIDE the repo (scratch/local) — they
   are working material, never artifacts. Record model + prompt + date for `_meta`.
3. **Reverse-image sanity check** on the shortlist: no resemblance to a findable real person.
   A hit kills the candidate, no appeal.
4. **Trace, don't embed.** Winners are traced into the layer schema (AI-assisted vectorization
   is fine as a *tool*) then hand-cleaned to the line budget and the face rules. The recipe JSON
   is the artifact; the reference is discarded.
5. **Validate.** The schema unit test must pass (`tests/test_portrait_recipes.py`); render the
   candidate through `portraits.js` — never review raw reference images as if they were the work.

## 3. The contact-sheet gate (hard gate — Matthew only)

- One sheet per batch: **all personas side-by-side, light AND dark theme, at 40/56/96 px**, plus
  the sigil fallback beside each for comparison.
- **Approve the sheet, not portraits in isolation** — the cast has to read as one engraving hand.
- Outcomes: **approve** (batch ships) · **revise** (specific notes, one round) ·
  **kill** (after 2 failed revision rounds the coach stays sigil-only and rollout stories close).
- Approval is recorded in each recipe's `_meta.sign_off` (who/date/sheet reference) and in the
  shipping PR body. No `_meta.sign_off` → validation fails → the recipe never renders.

## 4. Shipping

- Recipes land in `config/portraits/<persona_id>.json`; the build regenerates the bundled module
  (`portrait_data.js`) which rides the ADR-098 content-hashed graph via `sync_site_to_s3.sh`.
- Live pages must pass visual QA + the AI-vision pass (`tests/visual_qa.py --screenshot --ai-qa`)
  before the deploy is called done.
- Rollback is structural: delete/revert the recipe → the fallback chain renders the sigil,
  pixel-identical to before.

## 5. New-coach onboarding

The default for any new coach is **sigil-only** (it's free, deterministic, and on-brand — §8.2).
A portrait is opt-in: run §2–§4 as a batch of one, same gate, same kill criterion. Never ship a
portrait for a coach whose persona document doesn't yet establish who they are — the drawing
follows the character, not the other way around.

## 6. Disclosure spec

- **aria-label convention** (renderer default, #586): `Illustrated portrait of <name>, a
  fictional AI persona`. Decorative placements pass `title: ""` → `aria-hidden`, same as sigils.
- **The disclosure sentence** — required once per team/about surface that shows portraits:

  > Coach portraits are commissioned illustrations of openly fictional AI personas — no real
  > people are depicted.

- Never present a portrait in a context that implies a human staff member (no "Our team"
  photo-grid framing without the disclosure line adjacent).
