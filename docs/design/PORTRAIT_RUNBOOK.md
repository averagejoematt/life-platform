# Coach Portrait Runbook — commissioning, style bible, onboarding

**Authority:** ADR-106 (the commissioning rule) + DESIGN_SYSTEM_V5 §8.7. This runbook is the
procedure; if it ever disagrees with the ADR, the ADR wins. Renderer + schema live in story #586
(`site/assets/js/portraits.js`, `config/portraits/`); the pilot commissioning is story #587.

The one-sentence version: **AI may sketch, only code ships, only Matthew approves.**

---

## 1. The style bible — "commissioned engraved identity"

The vocabulary extends the instrument language of §8.2 (sigils) to a human mark: an
**engraving**, not an avatar. Think banknote/scientific-plate line work, not cartoon, not
photoreal (photoreal is NO-GO, ADR-106 §5).

**Composition**
- **Engraved bust, ¾ view** (subject turned ~30° toward the reader, both eyes visible). Never
  full-frontal (passport-photo dead stare), never profile (loses recognisability at 40 px).
- **viewBox `0 0 100 120`** (renderer contract, #586). Head centre ≈ (50, 46); **eye-line at
  y = 46 ± 2**; crown clears y ≥ 8; bust cut runs off the bottom edge between y = 104–120 (no
  floating heads — the bust cut is part of the engraving idiom).
- **Signature carried by silhouette, hair, glasses, brow** — the durable identity features that
  survive 40 px. Never by props overload (no stethoscopes, clipboards, barbells; at most ONE
  quiet wardrobe cue in the bust layer, e.g. a collar style).

**Line**
- **Stroke-only, no fills** except: pupils (small filled dots) and ≤ 2 accent nodes if the
  design earns them. Contours `stroke="currentColor"`, `stroke-width 1.7`,
  `vector-effect="non-scaling-stroke"`, round caps/joins — identical to the sigil line so the
  two read as one system.
- **One accent layer** (`hatch`) rides `var(--coach)` — the engraved shading is the persona's
  identity colour, exactly as the sigil colour channel works (§8.2's sanctioned exception).
  Everything else is ink.
- **Line budget: ≤ 48 stroked elements per portrait (target 28–40).** If a trace needs more,
  simplify the reference — density belongs in the `hatch` layer, not the contours. The budget is
  what keeps a portrait legible at 40 px and cheap to draw-in animate.

**Face rules (the uncanny guards)**
- **No teeth, ever.** Mouths are closed or single-line; `mouth-a`/`mouth-b` variants stay
  closed-lip shapes (they exist for future speaking states, not grins).
- **Pupil-size guard:** pupils are filled circles **r 1.4–2.2** at this viewBox. Below 1.4 reads
  as the hollow engraving stare; above 2.2 reads cartoon. `eyes-open` must include pupils;
  `eyes-closed` is a single lid line per eye (the blink frame).
- Eyes are the only place with both a stroke shape and a fill dot — keep them simple: lid line,
  iris arc optional, pupil dot.
- No skin-tone rendering exists in this language (it's ink on paper); ethnicity/identity cues
  come from the persona document's own description via silhouette, hair, and features — drawn
  respectfully, reviewed at the contact-sheet gate like everything else.

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
