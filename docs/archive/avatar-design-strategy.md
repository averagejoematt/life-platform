# Life Platform Avatar System — Design Strategy

**Document type:** Creative Consultation Brief
**Date:** March 2, 2026
**Subject:** Matthew Walker — Reference Photos Reviewed
**Version:** 1.0

---

## The Panel

This document synthesizes perspectives from five disciplines to arrive at a unified avatar strategy for the Life Platform character sheet. Each consultant reviewed the three reference photos, the existing dashboard aesthetic (dark theme, DM Sans + JetBrains Mono, #0c0c0f background, accent palette of emerald/amber/coral/blue), and the tier progression spec (Foundation → Momentum → Discipline → Mastery → Elite).

---

## 1. Reference Photo Analysis

**Consultant: Character Design Lead**

Three professional-quality reference shots provide excellent coverage for sprite translation:

**Photo 1 — Studio headshot, neutral background.** Clean front-facing angle. This is the primary reference for facial feature mapping: short brown hair with a clean fade, blue-grey eyes, trimmed full beard, strong brow line, defined jawline. Expression is calm and confident — the "resting state" of the character.

**Photo 2 — Studio portrait, arms crossed, three-quarter turn.** This gives us the posture and attitude. Arms crossed reads as "composed, ready" — a natural idle pose for an RPG character portrait. The slight smile adds approachability. The watch on the left wrist is clearly visible — important accessory detail. Build is athletic, shoulders broad relative to frame.

**Photo 3 — Outdoor, brick wall, half-body.** This is the gold mine. We get the full silhouette: athletic build, V-taper visible through the black tee, hand in pocket reads as relaxed confidence. The Whoop band on the right wrist is visible here — this is a *character-defining accessory* for a health platform avatar. The brick texture behind creates natural warm tones that suggest the Momentum/Discipline color palette.

**Key distinguishing features for pixel translation:**
- Short brown hair, faded sides — translates to 3-4 pixel rows on top, 1-pixel sides
- Blue-grey eyes — a single bright pixel per eye at this scale, but the color matters
- Trimmed beard — 2-3 pixel rows of brown below the face, distinguishes from clean-shaven generic sprites
- Athletic build — broader shoulder-to-waist ratio than a default sprite
- Black t-shirt — signature look, serves as the "base costume" across all tiers
- Whoop band (right wrist) + metal watch (left wrist) — dual wrist accessories are uniquely identifying; no other RPG character has a fitness tracker

**Verdict:** These photos give us everything we need. The face has strong, clean geometry that will reduce well to pixel art. The beard and dual wrist accessories make the character instantly recognizable even at 32×32.

---

## 2. Art Direction & Style

**Consultant: Pixel Art Director (specializing in indie RPG aesthetics)**

### Why 16-bit and not 8-bit or HD

The spec calls for "Chrono Trigger / Final Fantasy" and that instinct is correct, but let me be precise about why and refine the target:

**8-bit (NES-era, 16×16 to 24×24):** Too abstract. At this resolution, the beard disappears, the Whoop band is impossible, and tier progression has to rely entirely on palette swaps. There's no room for "gear upgrades" to read visually. Charming but wrong for this use case.

**HD pixel art (Octopath Traveler, 64×64+):** Too detailed. The rendering effort multiplies — five tier variants at this fidelity is a serious production. It also doesn't embed well in emails or small dashboard tiles. And the "game" nostalgia signal is weaker; it starts feeling like illustration rather than gamification.

**16-bit sweet spot (SNES-era, 32×48 to 48×64 sprite, rendered at 3-4x):** This is the target. Specifically, I'd reference:

- **Chrono Trigger character portraits** — the menu portraits are roughly 48×48 with incredible personality. They manage facial hair, accessories, and expression in very few pixels.
- **Final Fantasy VI (FFVI) field sprites** — 16×24 base with 2x rendering. The genius of these is how gear changes read clearly: Terra's base outfit vs. her Esper form is unmistakable even at that tiny scale.
- **Stardew Valley portraits** — modern take on the SNES portrait style. 64×64 with clean outlines, limited palette, maximum personality. This is probably the closest modern reference for what we want.

### Recommended Spec

**Base sprite canvas:** 48×48 pixels
**Render size:** 4x = 192×192 on dashboard, 3x = 144×144 in email
**Style:** Clean outlines (1px dark border), limited palette (12-16 colors per tier variant), slight anime proportions (head slightly large for readability), three-quarter view facing right (standard RPG portrait orientation)
**Pose:** Standing confident, slight three-quarter turn (echoing Photo 2). Not arms-crossed (too static for a character that will gain effects and badges) — instead, a relaxed "ready stance" with hands visible at sides, allowing space for gear/effects to populate the silhouette.

### Why three-quarter and not front-facing

Front-facing portraits feel like mugshots. The three-quarter view:
- Creates depth and movement
- Gives the character a "looking toward something" energy that matches the journey metaphor
- Leaves visual real estate on the trailing side for pillar badges to orbit
- Is the canonical RPG portrait angle (every FF menu portrait, every Chrono Trigger dialogue portrait)

---

## 3. Tier Progression Design

**Consultant: Game Designer (progression systems, visual reward design)**

This is where the avatar earns its place in the system. The tier progression needs to satisfy three competing goals:

1. **Each tier must feel like a meaningful visual upgrade** — the player should *want* the next tier
2. **The base character must remain recognizable** — Matthew should always see himself, not a different character
3. **The progression must feel earned, not arbitrary** — visual complexity should correlate with achievement

### The Progression Philosophy: "Same Person, Growing Power"

The mistake most gamification avatars make is costume changes — you're a peasant, then a knight, then a king. That's fantasy. The Life Platform isn't fantasy; it's *reality with a game layer*. The avatar should always look like Matthew. What changes is the *energy around him*.

Think of it like Dragon Ball Z: Goku always looks like Goku. But the aura, the hair glow, the energy crackling — that's what tells you he powered up. Our version is subtler (we're not going Super Saiyan), but the principle is the same: the person stays constant, the surrounding energy reflects achievement.

### Tier Visual Design

**🔨 Foundation (Level 1–20) — "Day One"**

The base sprite. Black t-shirt, jeans, clean design. Muted palette — colors are slightly desaturated, as if the character is in shadow or early morning light. No accessories beyond the Whoop band and watch (which are always present — they're part of the character, not rewards).

The background/frame is empty. Just the character on the dark dashboard surface. This emptiness is intentional — it creates visual hunger. There should be something here, and there will be, once you earn it.

*Palette: 10 colors. Browns, dark grey, muted skin tones. The only bright pixels are the eyes.*

**🔥 Momentum (Level 21–40) — "The Spark"**

The character's palette warms. Skin tones brighten slightly. The black t-shirt develops a subtle texture (single-pixel cross-hatching to suggest fabric quality — a "nicer" black tee). A faint warm glow appears at the character's feet — amber/orange, like standing near a campfire. 2-3 pixels of soft light on the ground plane.

The Whoop band gets a single green pixel — it's "active." The watch face gets a tiny highlight. These are small, but they reward close looking.

*Palette shift: +2 colors (amber glow, warm highlight). Total: 12 colors.*

**⚔️ Discipline (Level 41–60) — "The Forge"**

This is the pivotal tier — the one where the avatar transforms from "person" to "character." The glow at the feet rises to a half-body aura — a subtle blue-tinted energy field, 1-2 pixels wide around the torso and arms. The character's posture subtly shifts: shoulders slightly back, chin slightly up. Confidence rendered in 2 pixels of adjustment.

The t-shirt develops a faint emblem over the heart — a small geometric mark (3×3 pixels) that suggests the Life Platform logo or a shield shape. It's not a literal logo; it's an RPG "faction mark" that signals belonging to something.

This is also the tier where **pillar badges begin appearing**. Small 8×8 pixel icons that orbit the character at cardinal positions. At Discipline, they appear dim — present but not glowing. More on badges in Section 4.

*Palette shift: +3 colors (blue aura, emblem, badge base). Total: 15 colors.*

**🏆 Mastery (Level 61–80) — "The Aura"**

Full-body energy field. The aura shifts from blue to the character's tier color (green for Mastery) and gains subtle animation potential (2-frame shimmer if we ever do GIF, but works as static glow for MVP). The character is visually "lit from within" — highlight pixels on the hair, shoulders, and arms suggest internal radiance.

The emblem on the chest is now clearly defined and glows. Pillar badges that have reached Discipline+ are at full brightness, with dim/hidden ones still in position. The overall composition now has genuine visual complexity — there's a lot happening around the character, but the face remains the clear focal point.

A subtle "ground effect" — 3-4 pixels of scattered light dots below the character, suggesting energy radiating downward. Think of the save-point sparkles in Final Fantasy.

*Palette: Full 16-color palette with glow variants. Green dominant accent.*

**👑 Elite (Level 81–100) — "The Apotheosis"**

This should feel *rare and legendary*. Most players will never see this state for more than brief periods, which makes it aspirational.

Golden highlight accent replaces green. The aura gains a second outer ring — a faint purple/violet edge (the Elite tier color) that creates a "double aura" effect. A crown or halo element appears: not a literal crown (too medieval) but a subtle geometric ring of light above the head — 5-6 bright pixels arranged in an arc, suggesting transcendence.

All active pillar badges are at maximum brightness with connecting lines of light between them — the "constellation" effect. When all 7 badges are active and bright, they form a complete ring of power around the character. This is the visual payoff of the Alignment Bonus.

The ground effect becomes a full circle of light — the character is standing in their own light source.

*Palette: Full 16 colors with gold and violet accents. Maximum visual density while maintaining the character at center.*

### The Critical Principle: Reversibility Must Feel Okay

When someone drops from Mastery back to Discipline, the aura dims but doesn't vanish. The transition should feel like "powering down" not "losing everything." The badges earned at lower tiers remain visible (dim). The emblem stays. Only the top-tier effects recede. This is crucial for emotional design — loss aversion is real, and the avatar shouldn't make level-downs feel like punishment.

---

## 4. Pillar Badge System

**Consultant: UI/UX Designer (icon systems, information density)**

### Badge Design Language

Each of the 7 pillars gets an 8×8 pixel badge icon. These are the "orbiting satellites" around the character that appear at Discipline tier (level 41+) for each respective pillar. The badges use a consistent visual language:

**Shape:** Circular base (6px diameter) with a 1px icon interior. This keeps them readable at small sizes while maintaining pixel art crispness.

**Three states:**
- **Hidden** (pillar below 41): Badge position empty — no visual. Clean silhouette.
- **Dim** (pillar 41-60, Discipline): Badge appears as a faint outline with muted fill. Present but not drawing attention. "You've unlocked this, now grow it."
- **Bright** (pillar 61+, Mastery/Elite): Badge at full color with a 1px glow halo. Draws the eye. Achievement radiating.

### Badge Iconography

| Pillar | Icon Concept | Design Notes |
|--------|-------------|--------------|
| Sleep | Crescent moon | Classic, universally readable. Tilt slightly for dynamism. |
| Movement | Lightning bolt | Energy, speed, power. More dynamic than a dumbbell at 8×8. Reads better than a running figure at this scale. |
| Nutrition | Leaf/sprout | Growth, nourishment. Avoids the "plate and fork" cliché that doesn't pixel well. |
| Metabolic | Heart with pulse | The classic vital sign. A heart shape with a single zigzag pixel = heartbeat line. |
| Mind | Diamond/gem | Clarity, focus, value. Better than a brain at 8×8 (brains look like blobs). A faceted gem = sharp mind. |
| Relationships | Two-dot constellation | Two dots connected by a line. Simple, abstract, reads as "connection." Avoids the handshake (too complex at 8×8). |
| Consistency | Star | The meta-pillar gets the meta-symbol. A 5-point star is the universal "achievement" icon. |

### Badge Positioning

Badges orbit the character in a consistent arrangement — they don't move randomly. Using clock positions:

```
        Sleep (12:00)
   Mind          Movement
 (10:30)         (1:30)

Relation-    ★    Nutrition
ships(9:00) [CHAR] (3:00)

 Consist-        Metabolic
  ency(7:30)     (4:30)
```

This places Sleep at top (the pillar that affects everything), Movement and Nutrition flanking (the two action pillars), Metabolic and Consistency at the base (foundational metrics), Mind and Relationships at the sides (internal + external). The arrangement has visual balance and conceptual logic.

### Badge Interaction with Effects

When a cross-pillar effect is active, the relevant badges get visual connectors:

- **Sleep Drag:** Sleep badge gets a "zzz" emanation (2-3 tiny pixels trailing off). Movement and Mind badges dim slightly even if they're at Mastery+.
- **Synergy Bonus:** A lightning-bolt line connects Nutrition and Movement badges through the character — the "power circuit" visual.
- **Alignment Bonus:** All badges connect into a complete ring of light — the constellation becomes a crown.

---

## 5. Active Effects Visualization

**Consultant: VFX Artist (game visual effects, particle systems in constrained resolution)**

Effects need to work within the pixel art constraints while being immediately readable. The principle: each effect gets ONE visual signature that players learn to recognize instantly.

### Effect Visual Catalog

**🛏️ Sleep Drag**
Three small "Z" characters (2×3 pixels each) floating above and to the right of the character's head, in descending size. Color: muted blue-grey (#72717a — the dashboard's --muted color). The character's overall palette shifts 10% toward grey/blue, as if slightly washed out. Subtle but the trained eye catches it: "something's off."

**💪 Training Boost**
2-3 small diagonal "energy lines" emanating upward from the character's shoulders, in the Movement pillar color. Think of the "power up" lines from Dragon Ball or the "getting stronger" visual from Pokémon evolution. Just 4-5 bright pixels total, but they communicate upward energy.

**🧠 Focus Buff**
A subtle "sparkle" effect — 3 single-pixel dots arranged in a triangle near the character's head, alternating bright/dim (in a 2-frame animation if GIF, or just the bright state for static). Color: Mind pillar blue. The character's eyes might get an extra highlight pixel.

**⚡ Synergy Bonus**
Small lightning bolt icon between the relevant badges (see Section 4). Color: amber/electric (#fbbf24). This is the most visually active effect — it should feel like energy is flowing through the badge constellation.

**🌟 Alignment Bonus**
The badge constellation completes its ring — all 7 badges connect with faint lines of gold light, forming a heptagonal halo around the character. This is the rarest visual state and should feel genuinely special. The ground effect intensifies. The character is fully illuminated.

**🛡️ Vice Shield**
A subtle circular shield outline (1px, semi-transparent) around the character, in a protective blue-green. Not flashy — it's a "passive buff" visual. Present but quiet, like actual discipline.

### Layering Order (back to front)

```
1. Ground effect (glow beneath character)
2. Aura field (tier-colored energy around character)
3. Badge connection lines (if Alignment Bonus active)
4. Base character sprite (the person)
5. Pillar badges (orbiting positions)
6. Active effect overlays (zzz, energy lines, sparkles)
7. Crown/halo element (Elite tier only)
```

This layering ensures the character is always readable and effects enhance rather than obscure.

---

## 6. Technical Architecture

**Consultant: Technical Art Director (asset pipeline, web rendering, performance)**

### The Compositing Decision: CSS Layers vs Pre-Composed

The spec offers two paths and I strongly recommend **CSS compositing with individual layers**, not pre-composed combinations. Here's why:

Pre-composed would require generating every possible combination of: 5 tiers × (7 badges × 3 states each) × (6 possible active effects) = thousands of unique images. That's combinatorial explosion.

CSS compositing needs: 5 base sprites + 7 badge sprites (×3 states = 21) + 6 effect overlays + 2-3 crown/halo variants = roughly **35 individual PNGs**. The dashboard HTML stacks them with absolute positioning. Total asset weight: under 200KB.

### Asset Pipeline

```
s3://matthew-life-platform/dashboard/avatar/
├── base/
│   ├── foundation.png    (192×192, 4x rendered from 48×48)
│   ├── momentum.png
│   ├── discipline.png
│   ├── mastery.png
│   └── elite.png
├── badges/
│   ├── sleep-hidden.png  (transparent 32×32)
│   ├── sleep-dim.png
│   ├── sleep-bright.png
│   ├── movement-hidden.png
│   ├── movement-dim.png
│   ├── movement-bright.png
│   └── ... (7 pillars × 3 states = 21 files)
├── effects/
│   ├── sleep-drag.png
│   ├── training-boost.png
│   ├── focus-buff.png
│   ├── synergy-bonus.png
│   ├── alignment-bonus.png
│   └── vice-shield.png
├── crown/
│   ├── elite-halo.png
│   └── alignment-ring.png
└── email/
    ├── foundation-composite.png  (pre-composed for email)
    ├── momentum-composite.png
    ├── discipline-composite.png
    ├── mastery-composite.png
    └── elite-composite.png
```

The `email/` directory contains 5 pre-composed "best case" images (one per tier) for inline email rendering, since email clients can't do CSS compositing. These show the base character at each tier with a representative badge/effect configuration. Updated periodically (weekly or on tier change), not daily.

### Dashboard CSS Compositing

```css
.avatar-frame {
  position: relative;
  width: 192px;
  height: 192px;
  image-rendering: pixelated;      /* Critical: prevents anti-aliasing blur */
  image-rendering: crisp-edges;    /* Firefox fallback */
}
.avatar-frame img {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  image-rendering: inherit;
}
.avatar-base    { z-index: 1; }
.avatar-aura    { z-index: 0; }    /* Behind character */
.avatar-badge   { z-index: 2; }    /* In front of character */
.avatar-effect  { z-index: 3; }    /* Topmost layer */
```

### Pixel-Perfect Rendering

The single most important technical detail: **`image-rendering: pixelated`**. Without this, browsers will bilinear-filter the 48×48 sprites when scaling to 192×192, turning crisp pixels into blurry mush. This CSS property forces nearest-neighbor scaling, preserving every pixel edge. It's the difference between "retro game art" and "blurry thumbnail."

### Data Contract

The avatar state in `data.json` drives the compositing:

```json
{
  "avatar": {
    "tier": "discipline",
    "badges": {
      "sleep": "bright",
      "movement": "dim",
      "nutrition": "bright",
      "metabolic": "hidden",
      "mind": "dim",
      "relationships": "hidden",
      "consistency": "dim"
    },
    "effects": ["training_boost"],
    "elite_crown": false,
    "alignment_ring": false
  }
}
```

---

## 7. Production Strategy

**Consultant: Production Lead (asset creation, tooling, timeline)**

### How to Actually Create the Sprites

This is the practical question: who or what makes the pixel art?

**Option A: AI-generated base → human polish.** Use an AI image generator to create the initial 48×48 sprites from the reference photos with a "16-bit RPG pixel art" prompt, then manually polish in Aseprite or Piskel. This gives you 80% quality in 20% of the time, with the remaining 20% of polish being the hand-tuning that makes it feel crafted.

**Option B: Commission a pixel artist.** A skilled pixel artist on Fiverr or specialized platforms (PixelJoint community, Lospec) can produce 5 tier variants from reference photos for $150-400. Turnaround: 1-2 weeks. Quality: highest possible. The artist handles all the subtle decisions about which facial features to prioritize at low resolution.

**Option C: Hand-pixel from scratch.** Matthew or a collaborator opens Aseprite and builds pixel-by-pixel. Most time-intensive, but most personal. Good if this is also a hobby/creative outlet.

**Recommendation: Option A** for MVP speed, with Option B as a future polish pass. Generate the AI base sprites, validate they capture the key features (beard, eyes, build, Whoop band), and hand-edit in Piskel (free, browser-based) for any corrections. The badges and effects are simple enough to hand-pixel from scratch — they're 8×8 icons with 3-4 colors each.

### Prompt Engineering for AI Sprite Generation

For the AI generation pass, the prompt structure that works:

```
"16-bit SNES-style pixel art character portrait, 48x48 pixels,
[tier-specific description], male character with short brown hair,
trimmed beard, blue eyes, black t-shirt, fitness tracker on right
wrist, metal watch on left wrist, athletic build, three-quarter
view facing right, dark background, clean pixel outlines,
limited color palette, [tier-specific palette notes]"
```

Each tier gets its own generation pass with specific environmental/effect descriptions added.

### Production Timeline

| Phase | Task | Time |
|-------|------|------|
| 1 | Generate 5 base tier sprites (AI + polish) | 2-3 hours |
| 2 | Hand-pixel 7 badge icons × 3 states | 1-2 hours |
| 3 | Create 6 effect overlay PNGs | 1-2 hours |
| 4 | Build dashboard CSS compositing layer | 1 hour |
| 5 | Integrate avatar state into data.json pipeline | 30 min |
| 6 | Create 5 pre-composed email PNGs | 30 min |
| 7 | Testing across tiers and badge combinations | 1 hour |
| **Total** | | **7-10 hours** |

---

## 8. The Emotional Design Arc

**Consultant: Behavioral Design Lead**

Let me step back from pixels and talk about what this avatar is actually *for*.

The Character Sheet gives Matthew a number. The radar chart gives him a shape. The avatar gives him a **self-image**. This is the most powerful of the three because humans are visual identity creatures — we care about how we look, including our digital representations.

### The Psychological Journey

**Foundation (Level 1-20):** The avatar is deliberately understated. Not ugly, not sad — just quiet. It looks like a person at the start of something. When Matthew sees this state, the feeling should be: "I'm just getting started, but I'm here." The emptiness around the character is potential energy, not failure.

**Momentum (Level 21-40):** The first warmth appears. That amber glow at the feet is the "first campfire" — you've been walking and you've found warmth. The Whoop band turning green is a micro-reward that says "your tools are working." The feeling: "Something is happening."

**Discipline (Level 41-60):** The aura and emblem are the "identity shift" moment. This is where the avatar stops being "a person who tracks health data" and becomes "a person who IS this." The pillar badges appearing for the first time is a genuine visual milestone — suddenly there's a constellation around you. The feeling: "I'm becoming someone."

**Mastery (Level 61-80):** The full glow state is aspirational but achievable. Most dedicated users will reach this tier on at least some pillars. It should feel like "arriving" — not at the end, but at competence. The feeling: "I know what I'm doing. The data proves it."

**Elite (Level 81-100):** This is the "screenshot tier." It should look so good that Matthew would share it. The golden accents, the full constellation, the ground effect — this is the visual reward for sustained excellence. The feeling: "I earned this. This is rare."

### The Tom Factor

Tom sees this avatar on the buddy page. When Matthew's avatar visibly evolves — when badges light up, when the aura intensifies — Tom sees it too. The avatar becomes a *shared language* for accountability. Tom doesn't need to ask "how's the health stuff going?" — he can see the answer in the avatar state. And when Matthew's avatar dims (Sleep Drag, tier drop), Tom can see that too. The avatar makes the invisible visible for both parties.

### The Chronicle Factor

Elena can reference the avatar as a narrative device. "The week the seventh badge finally lit — all seven satellites in orbit around a character who, twelve weeks ago, stood alone in the dark." The avatar gives the Chronicle visual milestones to anchor story beats to. It's not just data anymore; it's imagery.

---

## 9. Summary Recommendations

### Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Art style | 16-bit SNES / Stardew Valley portrait | Best balance of personality, scalability, and nostalgia |
| Sprite canvas | 48×48 pixels, rendered at 4x (192×192) | Enough detail for beard/accessories, clean at any display size |
| Pose | Three-quarter standing, facing right | Canonical RPG portrait, leaves space for badge constellation |
| Progression model | Same person, growing energy | Avoids costume-change artificiality, matches "reality + game layer" |
| Compositing | CSS layers on dashboard, pre-composed for email | 35 assets vs thousands of combinations |
| Badge positioning | Fixed clock positions, consistent layout | Learnable, balanced, conceptually logical |
| Production method | AI-generate base → hand polish | Speed for MVP, upgradeable later |
| Rendering | `image-rendering: pixelated` | Non-negotiable for pixel art fidelity |

### What This Gives Matthew

The avatar transforms the Character Sheet from a spreadsheet into a mirror. Every morning when the Daily Brief arrives, there's a tiny pixel version of Matthew staring back — and the state of that pixel person tells the story of the last 21 days of effort, consistency, and growth. It's the most human element in a platform built on data.

### Immediate Next Steps

1. **Approve this design direction** — are the tier progressions right? Does the badge constellation concept resonate? Any pillar icon changes?
2. **Generate the 5 base sprites** — starting with Foundation, working up to Elite. Each one reviewed and polished before moving to the next.
3. **Build the dashboard compositing layer** — the CSS and HTML that assembles the avatar from individual layers. Can be built in parallel with sprite generation.
4. **Integrate avatar state into the data pipeline** — add avatar state computation to the character-sheet-compute Lambda output.

---

*"Every pixel should earn its place. In a 48×48 canvas, there are 2,304 pixels. That's 2,304 decisions. Make each one tell the story of someone becoming who they want to be."*

— The Panel
