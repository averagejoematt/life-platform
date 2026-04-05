# averagejoematt.com — Visual Asset Brief & Creative Direction

## Prepared by: Product Board of Directors
## Date: March 26, 2026

> **Purpose**: A complete creative direction document defining every visual asset needed, the style requirements, tool-specific prompts, technical specs for integration, and the phased execution plan. This document is designed to be handed to AI image generation tools (Recraft, Kittl, Midjourney, DALL-E) or a human designer and produce consistent, on-brand results.

---

## 1. BRAND IDENTITY FOUNDATION

### The Aesthetic
**"Bloomberg Terminal × Patagonia Documentary"** — this is the board directive from the website strategy. Every visual must live at the intersection of:
- **Signal precision** — clean geometric forms, data-informed composition, monospace labeling
- **Documentary honesty** — grit, texture, reality. Not polished lifestyle content. Not gym-bro motivation posters.
- **Dark biopunk terminal** — the site's native environment is dark (#080c0a background), with signal green (#00e5a0) as the primary accent

### Color Palette (Mandatory)
All generated assets must use ONLY these colors:

| Token | Hex | Usage |
|-------|-----|-------|
| Background | `#080c0a` | SVG/illustration backgrounds |
| Surface | `#0f1612` | Card backgrounds, secondary fills |
| Surface 2 | `#141f17` | Tertiary fills |
| Signal Green | `#00e5a0` | Primary accent, earned/active states |
| Green 400 | `#00c88a` | Secondary green |
| Amber | `#c8843a` | Journal/chronicle accent, streak badges |
| Amber 400 | `#e09a4a` | Warning, building states |
| Coral | `#ff6b6b` | CTA accent, subscribe |
| Blue | `#5ba4cf` | Level-up badges, milestone category |
| Purple | `#8b6cc1` | Data/experiment badges |
| Red | `#e06060` | Science/challenge badges |
| Yellow | `#f59e0b` | Challenge badges |
| Gold | `#d4a520` | Mastery tier |
| Text Primary | `#e8ede9` | Primary text on dark |
| Text Secondary | `#7a9080` | Muted text |
| Text Faint | `#4a6050` | Disabled/faded |

### Typography in Visuals
- **Display**: Bebas Neue (or Impact fallback) — used for level numbers, hero text
- **Mono**: Space Mono — used for labels, tags, data annotations
- **Serif**: Lora — used for editorial/story content (Chronicle pages)
- **Sans**: Inter — used for UI text, descriptions

### Visual Tone Rules
1. **NO candy colors.** No gradients to pink, no neon rainbows.
2. **NO cartoon/Bitmoji style.** Avatar and illustrations should feel like stylized documentary, not Duolingo.
3. **NO stock photography aesthetic.** Nothing that looks like it came from a health influencer's Instagram.
4. **YES to geometric precision.** Clean lines, hexagonal forms, data-grid patterns.
5. **YES to earned weight.** Badges and icons should feel like military insignia, not stickers.
6. **YES to honest imperfection.** Subtle grain, slight texture — this is a real person's real journey, not a sanitized product.

---

## 2. ASSET CATEGORIES & SPECIFICATIONS

---

### CATEGORY A: Achievement Badges (40 badges)

**Where used**: Milestones page (`/achievements/`), Character page badge section, weekly email digests, social sharing cards

**Current state**: Emoji icons inside CSS-styled circles with ring progress indicators. Functional but generic — no visual identity.

**Target state**: Custom illustrated SVG badges, each unique, in a consistent style. Locked badges appear as gray/faded outlines. Earned badges glow with category color and full illustration.

**Style Direction**: Military commendation meets data terminal. Think: embossed metal insignia rendered in flat vector with subtle glow effects. Each badge should feel like something you'd display on a uniform — not collect in a mobile game.

**Format**: SVG, 72×72px nominal size (scalable). Dark background transparent. Must work on both `#080c0a` background AND potential light mode (`#f5f5f0`).

**File naming**: `badge_{id}.svg` — e.g., `badge_week_warrior.svg`, `badge_sub_280.svg`

#### Badge Manifest

**STREAKS (amber accent #c8843a)**

| ID | Name | Description | Visual Concept |
|----|------|-------------|----------------|
| `week_warrior` | Week Warrior | 7-day T0 streak | Single flame inside hexagonal frame |
| `monthly_grind` | Monthly Grind | 30-day T0 streak | Double flame, more elaborate hexagonal frame, 30 notch marks around perimeter |
| `quarterly` | Quarterly | 90-day T0 streak | Triple flame, shield shape, quarter-circle arc motif |
| `half_year` | Half Year | 180-day T0 streak | Flame within hourglass shape, "180" integrated |
| `annual_fire` | Annual Fire | 365-day T0 streak | Full sun/flame radiating from center, most ornate frame |

**LEVELS (signal green #00e5a0)**

| ID | Name | Description | Visual Concept |
|----|------|-------------|----------------|
| `first_level_up` | First Level Up | Reached Level 2 | Single upward chevron, simple hexagon |
| `apprentice` | Apprentice | Level 5 | Double chevron, slightly more detail |
| `journeyman` | Journeyman | Level 10 | Triple chevron inside shield |
| `adept` | Adept | Level 15 | Four-point star with chevrons |
| `expert` | Expert | Level 20 | Tier boundary badge — ornate, marks entry to Momentum |
| `master` | Master | Level 40 | Tier boundary — marks entry to Discipline |

**WEIGHT MILESTONES (blue #5ba4cf)**

| ID | Name | Description | Visual Concept |
|----|------|-------------|----------------|
| `first_10` | First 10 | Lost first 10 lbs | Scale icon with downward arrow, "10" |
| `lost_20` | -20 lbs | Lost 20 lbs from start | Scale with two downward arrows |
| `sub_280` | Sub-280 | Below 280 lbs | Milestone marker with "280" crossed out |
| `sub_260` | Sub-260 | Below 260 lbs | Milestone marker with "260" crossed out |
| `sub_240` | Sub-240 | Below 240 lbs | Halfway point visual — scale balanced at center |
| `sub_220` | Sub-220 | Below 220 lbs | Approaching target — increasing detail |
| `sub_200` | Sub-200 | Below 200 lbs | Major milestone — elaborate frame, "ONDERLAND" text arc |
| `goal_weight` | The Goal | Hit 185 lbs | Most elaborate badge in entire set — crown, laurels, "185" prominent |

**DATA CONSISTENCY (purple #8b6cc1)**

| ID | Name | Description | Visual Concept |
|----|------|-------------|----------------|
| `100_days` | Century | 100 days tracked | Grid of 100 dots (10×10), filled |
| `200_days` | Bicentennial | 200 days tracked | Larger grid, more dense |
| `365_days` | Full Year | 365 days tracked | Calendar-year circle, all days filled |
| `data_complete` | Full Signal | All 19 sources reporting in one day | 19-point star/radial |

**EXPERIMENTS (red #e06060)**

| ID | Name | Description | Visual Concept |
|----|------|-------------|----------------|
| `first_experiment` | First Hypothesis | Completed first N=1 | Single flask/beaker |
| `five_experiments` | Lab Rat | 5 experiments completed | Multiple flasks |
| `hypothesis_confirmed` | Confirmed | First statistically validated finding | Flask with checkmark |
| `ten_experiments` | Mad Scientist | 10 experiments completed | Elaborate lab setup |

**CHALLENGES (yellow #f59e0b)**

| ID | Name | Description | Visual Concept |
|----|------|-------------|----------------|
| `first_challenge` | Challenge Accepted | First challenge completed | Trophy silhouette |
| `five_challenges` | Competitor | 5 challenges completed | Trophy with "5" |
| `ten_challenges` | Champion | 10 challenges | Elaborate trophy |
| `twenty_five` | Hall of Fame | 25 challenges | Most ornate trophy with laurel wreath |
| `perfect_challenge` | Perfect Game | 100% challenge completion | Trophy with sparkle/perfect ring |

**VICE STREAKS (signal green #00e5a0 with dark accent)**

| ID | Name | Description | Visual Concept |
|----|------|-------------|----------------|
| `vice_30` | 30 Days Clean | 30-day vice streak | Broken chain, single link |
| `vice_90` | Quarter Clean | 90-day vice streak | Broken chain, three links scattered |
| `vice_180` | Half Year Clean | 180-day vice streak | Fully shattered chain |
| `vice_365` | Year of Freedom | 365-day vice streak | Phoenix rising from broken chains |

**RUNNING/WALKING**

| ID | Name | Description | Visual Concept |
|----|------|-------------|----------------|
| `first_5k` | First 5K | Completed a 5K | Running shoe silhouette with "5K" |
| `first_10k` | First 10K | Completed a 10K | Shoe with "10K", more detail |
| `half_marathon` | Half Marathon | 13.1 miles | Running figure with "13.1" |

---

#### AI Prompt Template for Badges (use with Recraft/Kittl)

```
Create a flat vector badge icon, 72x72px, dark background (#080c0a).
Style: military insignia meets data terminal. Clean geometric lines,
subtle inner glow effect using [CATEGORY_COLOR]. No gradients to
other colors. Monochrome with single accent color. Hexagonal or
shield frame. Minimal detail that reads clearly at small size.
The badge represents: [DESCRIPTION].
Central motif: [VISUAL_CONCEPT].
Export as SVG with transparent background.
Color palette limited to: #080c0a, #0f1612, [CATEGORY_COLOR],
#e8ede9 for any text.
```

---

### CATEGORY B: Custom Icon Set (25-30 icons)

**Where used**: Site-wide replacement for emoji usage. Glyph strip on Live page, pillar icons on Character page, category headers, navigation, email digests.

**Current state**: Mix of emoji and inline SVG icons (the Live page glyph strip has hand-coded SVG icons).

**Target state**: Unified custom icon set in a consistent geometric style. Each icon 24×24px nominal. Single color (adapts via CSS `currentColor` or `fill` attribute).

**Style Direction**: Geometric, slightly rounded corners, 1.5px stroke weight. Similar to Lucide or Feather icons but with a custom "signal" quality — slightly more angular, slightly more technical.

#### Icon Manifest

| ID | Replaces | Usage | Visual Concept |
|----|----------|-------|----------------|
| `icon-sleep` | 😴 | Sleep pillar | Crescent moon with z-wave |
| `icon-movement` | 🏋️ | Movement pillar | Abstract running figure or heartbeat-with-legs |
| `icon-nutrition` | 🥗 | Nutrition pillar | Fork-and-leaf or macro balance |
| `icon-metabolic` | 📊 | Metabolic pillar | Glucose wave / heartbeat line |
| `icon-mind` | 🧠 | Mind pillar | Brain outline or meditation pose |
| `icon-social` | 💬 | Social/relationships pillar | Two overlapping circles (connection) |
| `icon-consistency` | 🎯 | Consistency pillar | Target/crosshair |
| `icon-scale` | ⚖️ | Weight | Balance scale, minimal |
| `icon-water` | 💧 | Hydration | Water droplet |
| `icon-lift` | 🏋️ | Strength training | Barbell / dumbbell |
| `icon-recovery` | ❤️‍🩹 | Recovery/HRV | Heart with pulse line |
| `icon-journal` | 📓 | Journal/writing | Open book with pen |
| `icon-streak` | 🔥 | Streaks | Flame |
| `icon-experiment` | 🔬 | Experiments | Flask/beaker |
| `icon-discovery` | 💡 | Discoveries | Lightbulb |
| `icon-supplement` | 💊 | Supplements | Capsule |
| `icon-cgm` | 📈 | Glucose/CGM | Continuous line graph |
| `icon-blood` | 🩸 | Labs/bloodwork | Blood drop with + |
| `icon-steps` | 👟 | Step count | Footprint |
| `icon-zone2` | 🏃 | Zone 2 training | Running figure with heart |
| `icon-level-up` | ⬡ | Level up event | Upward chevron in hexagon |
| `icon-tier` | 🏆 | Tier progression | Shield with bar |
| `icon-alert` | ⚡ | Notifications/alerts | Lightning bolt |
| `icon-calendar` | 📅 | Date references | Calendar grid |
| `icon-trend-up` | ↑ | Positive trend | Arrow with sparkline going up |
| `icon-trend-down` | ↓ | Negative trend | Arrow with sparkline going down |

#### AI Prompt Template for Icons

```
Create a minimal vector icon, 24x24px viewBox. Single color (#00e5a0 on
dark or currentColor for adaptability). Geometric style, 1.5px stroke
weight, slightly rounded corners (2px radius). No fill, stroke only.
Must read clearly at 16px display size. The icon represents: [DESCRIPTION].
Export as SVG with no background.
```

---

### CATEGORY C: Matt's Avatar / Character Visual (5-8 states)

**Where used**: Character page hero section, Live page status, weekly email header, social sharing cards, accountability page

**Current state**: No avatar exists. Character page has tier emblem SVG with level number only.

**Target state**: A stylized illustrated avatar of Matt that changes visual state based on current platform data. NOT a photo. NOT a Bitmoji. Think: editorial illustration style from a documentary title card or magazine profile piece.

**Style Direction**: Stylized portrait illustration — slightly abstracted but clearly recognizable. Editorial illustration style (NYT/Wired magazine). Geometric simplification of features. Rendered in the site's color palette.

**Physical reference**: Matt is a tall man (6'2"), currently in the 270-280 lb range, broad build, short hair, facial hair (trimmed beard). Seattle/PNW outdoor aesthetic — approachable and determined, not intimidating.

#### Avatar State Definitions

| State | Trigger Condition | Visual Treatment |
|-------|-------------------|------------------|
| `avatar-strong` | Recovery ≥70%, Score ≥50, active streak | Full color, signal green accent, upright posture, subtle green glow |
| `avatar-building` | Mixed signals, some pillars active | Mostly colored, amber accent, neutral posture |
| `avatar-recovering` | Post-sick day, returning from break | Desaturated with color returning |
| `avatar-dormant` | No data logging for 3+ days | Grayscale/heavily desaturated, faded |
| `avatar-crushing` | Milestone hit, level up, PR | Full color + celebration glow |
| `avatar-focus` | Active experiment running | Color with scientific accent overlay |

**Format**: SVG preferred. If raster, 512×512px minimum. Each state separate file.
**File naming**: `avatar_{state}.svg` or `avatar_{state}.png`

#### AI Prompt Template for Avatar

```
Stylized editorial portrait illustration of a tall, broad-shouldered man
in his 30s with short hair and a trimmed beard. Pacific Northwest outdoors
aesthetic — casual, not gym-bro. Style: New York Times magazine editorial
illustration meets dark data terminal. Color palette: dark background
(#080c0a), primary accent (#00e5a0), with skin tones rendered in muted
warm tones. Geometric simplification — not photorealistic, not cartoon.
Should feel like a documentary protagonist. [STATE_DESCRIPTION].
Shoulders-up or chest-up composition. No text.
```

---

### CATEGORY D: Page Hero Illustrations (8 illustrations)

**Where used**: One per major page section as visual anchor.

**Format**: SVG preferred. If raster, 1200×600px minimum. Must work dark + light mode.

| Page | Illustration Concept | Size |
|------|---------------------|------|
| **Home** | "The Signal" — 19 data streams converging into human silhouette | 1200×400 |
| **Story** | "The Journey" — transformation arc, heaviness → motion/light/data | 1200×400 |
| **Character** | "The Game Board" — avatar at center of 7-pillar radial system | 860×300 |
| **Live/Today** | "The Pulse" — ECG line transforming into PNW mountain silhouette | 1200×200 |
| **Chronicle** | "The Measured Life" editorial masthead | 800×200 |
| **Platform** | Existing architecture SVG — enhance with glow/animation | existing |
| **Milestones** | "The Wall" — trophy case/display case background | 1200×300 |
| **Data Explorer** | "The Telescope" — two data streams crossing at insight point | 800×300 |

---

### CATEGORY E: Board Member Portraits (up to 36)

**Priority**: Product Board (8) → Personal Board (14) → Technical Board (12)

**Style**: Same editorial illustration as avatar but headshot-only, 80×80px circular, more abstracted.

---

### CATEGORY F: OG Image Templates (5)

**Format**: 1200×630px PNG

1. **Default** — site name + tagline + signal green
2. **Character** — avatar + level + score
3. **Milestones** — badge wall preview + earned count
4. **Chronicle** — Elena Voss masthead + entry title
5. **Weekly Snapshot** — week number + key metrics + mini avatar

---

## 3. TOOL RECOMMENDATIONS

| Category | Best Tool | Why |
|----------|-----------|-----|
| Badges (A) | **Recraft** | SVG output, brand color control, consistent set generation |
| Icons (B) | **Claude direct** or Recraft | Simple geometric icons within SVG generation capability |
| Avatar (C) | **Midjourney / DALL-E 3** | Stylized portrait illustration requires image AI |
| Page Heroes (D) | **Midjourney + SVG refinement** | Atmospheric concepts → vectorize |
| Portraits (E) | **Midjourney** | Similar to avatar, headshot-only |
| OG Templates (F) | **Claude direct** | Template-based, code-generated |

---

## 4. INTEGRATION SPECS

### Badges: `site/assets/img/badges/` → badge config gets `svg_path` field → JS loads SVG instead of emoji
### Icons: `site/assets/icons/custom/` → SVG sprite or individual files → CSS `currentColor` for state coloring
### Avatar: `site/assets/img/avatar/` → new API endpoint `handle_avatar_state()` → JS swaps based on state
### Heroes: `site/assets/img/heroes/` → CSS background-image or inline SVG per page

---

## 5. PHASED EXECUTION

1. **Phase 1**: Icon set + badge art (1-2 sessions) → immediate visual upgrade on 3+ pages
2. **Phase 2**: Avatar generation (1 session) → gives the site a face
3. **Phase 3**: Page hero illustrations (1-2 sessions) → each page visually distinct
4. **Phase 4**: Board portraits + OG templates (1 session) → social sharing branded
5. **Phase 5**: Dynamic state wiring (engineering) → visuals respond to live data

---

## 6. OPEN QUESTIONS

1. Avatar style: (a) highly geometric, (b) editorial illustration, or (c) graphic novel?
2. Badge complexity: (a) simple geometric (Claude can generate now), or (b) rich illustrated (needs Recraft/Midjourney)?
3. Photo reference for avatar generation?
4. Light mode compatibility requirement?
5. Budget for AI tools (~$25-55/month for Recraft + Midjourney)?
