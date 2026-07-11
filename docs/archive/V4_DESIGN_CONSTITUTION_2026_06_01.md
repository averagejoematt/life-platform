# averagejoematt.com — v4 Design Constitution

**Status:** Locked (board session 2026-06-01) · **Supersedes:** all prior v4 IA notes
**Purpose:** The single reference both the Claude Design brief and the Claude Code build instruction are written against. When any later decision is contested, this document is the tiebreaker.

---

## 0. The north star (the tiebreaker above all tiebreakers)

> **An honest living documentary of an ordinary life rebuilt with AI — the anti-Blueprint.**

The name *Average Joe Matt* enforces it at the level of the URL. Any design or content choice that drifts toward superhuman, slick, guru, or clinical is not merely off-strategy — it betrays the name. When two good options compete, pick the one that is more *ordinary, honest, and reachable*.

Two tensions this resolves permanently:
- **Polished vs raw →** honest-but-crafted. Elite *craft* in service of honesty; never gloss.
- **Commercialize now vs later →** bottom-up and grounded ("you could do this"), never top-down ("buy my protocol"). Build so commercialization is *possible*; do not build it now.

---

## 1. Who it's for, and what success is

- **Spine = Matthew, daily.** The site is a tool he opens every day. Everything else is a *view onto* that tool, not a co-equal audience.
- **Secondary = the trusted circle** (partner, Tom, a few friends) who check in frequently. This is a genuine connection function, not vanity.
- **Tertiary = the discoverer** — a stranger who lands on the site or is sent the link. Served well, but never the design driver.
- **Success = recurring value.** Matthew returns daily and gets something; the circle returns frequently and gets something. *Not* viral reach. *Not* first-impression wow. When "best for me daily" collides with "legible to a stranger," me-daily wins.

---

## 2. Positioning — the open quadrant

The space has three incumbents, all leaving the same gap:
- **Blueprint:** data + protocol, but superhuman and unreachable (30+ doctors, millions, removes human decision-making).
- **WHOOP / Oura:** clean single-score dashboards, but generic to everyone and carry no story.
- **Transformation blogs:** real story, thin data, no credibility.

**v4 occupies the empty quadrant: numbers + meaning & story, *and* honest & personal.** That quadrant is uniquely defensible right now because the dominant 2026 design movement is a backlash against polished AI-generated sameness — authenticity is the differentiator, not a limitation.

---

## 3. Architecture — one engine, three doors

The data pipelines and AI layer are the engine (unchanged; Matthew is happy with them). v4 is a new *expression* of that engine at three altitudes. Same data, same characters, three doors — routed by who arrives, never stacked in one horizontal menu.

| Door | Audience | The job it does | Default entry for |
|------|----------|-----------------|-------------------|
| **The Cockpit** | Matthew, daily | "Am I winning, and what's the one thing right now?" | A logged-in/returning Matthew |
| **The Story** | Circle + discoverer | "What's the honest arc of this transformation?" (scrollytelling) | Any unknown/first-time visitor or shared link |
| **The Evidence** | Skeptic + would-be-copier | "What's the protocol, what's it built on, does the data hold up?" | Anyone drilling for depth |

The old 7-section horizontal nav and footer sprawl are retired. Content is not deleted — it is re-sorted by *depth*, not laid out as equals.

---

## 4. The disclosure model (kills the navigation pendulum)

The repeated failure (menu → subpages → Observatory tiles) was treating a **disclosure** problem as a **navigation** problem: detail always sat behind a navigation jump, and synthesis was always the user's job. v4 changes the axis:

1. **Detail opens in place.** Pick a pillar and it expands on the surface you're already on — no destination change, nothing lost.
2. **Lateral movement.** Switching between the seven pillars is a swap on the same canvas, not a trip to another page.
3. **Synthesis is delivered, not assembled.** Surface The Chair's existing cross-pillar verdict (already computed for the daily/weekly digests) at the top. Matthew stops synthesizing by hand.

---

## 5. The two jobs (LOCKED)

- **The Cockpit answers, in one glance:** *"Am I winning, and what's the one thing right now?"*
  → Character Level + tier + today's movement + The Chair's single verdict + a board one-liner.
- **A pillar view answers:** *"Why is this pillar where it is, where's it heading, and what do I do?"*
  → pillar score + trend across the time-scope + the components driving it + the relevant persona's read + one action.

These two jobs are the acceptance test for the Cockpit interaction pattern (see §10).

---

## 6. The pillar model (LOCKED)

The real, computed model — not a guess:
- **Character Level 1–100**, five tiers: Foundation → Momentum → Discipline → Mastery → Elite.
- **7 pillars:** Sleep, Movement, Nutrition, Metabolic, Mind, Relationships, Consistency.

**Glance grouping (LOCKED):** two domains plus one cross-cutting band.
- **Body:** Movement, Nutrition, Sleep, Metabolic
- **Mind:** Mind, Relationships
- **Consistency** spans everything as a *discipline band*, not a sixth peer tile (it is adherence *across* pillars, not a topic).

Two scannable domains on the glance; the seven live one drill beneath. Grouping is for orientation only and must not distort the underlying scoring weights.

**Time-scope** is one global control (Today · Week · Month · Journey), not four separate page-sets. Daily-Matthew lives in Today/Week; historicals are present but not foregrounded.

---

## 7. The moat — what makes it elite, not just clean

Protect these four; they are the reasons a competitor with a $300 ring cannot reproduce v4.

1. **The interpretation layer.** A board of *named characters* who argue about Matthew, a journalist (Elena) writing the weekly story, and the Third Wall where Matthew talks back to the AI. This is the literal embodiment of "my friend used Claude to hack his life — come see what it says about him." It is the soul of the site, not a feature.
2. **Honesty as a design principle.** Down weeks, relapses, and absences (the WR-47 "pause" problem) are *shown and narrated*, not hidden. Visible setbacks and visible uncertainty make the N=1 more credible than Blueprint's certainty, not less. This is also the antidote to WHOOP's documented weakness (no concept of planned rest → missing targets just feels discouraging).
3. **Radical accessibility positioning.** Built with Claude + the consumer wearables already on his body, not a million-dollar lab. "You could do this" is the throughline.
4. **The gamified character layer.** Levels, tiers, and pillar progress — already computed — are the human-friendly synthesis of the hard science and are squarely on-trend for 2026 engagement.

---

## 8. Experiments & challenges (LOCKED)

- Build as **Matthew's N=1 instrument first**, exposed publicly as **read-only proof** inside The Evidence door.
- Reader-interactive participation is a **later bet**, not a v4 driver — but architect the data/exposure so reader features can switch on later **without a rebuild**.
- Consistent with the deferred-commercialization stance (§0).

---

## 9. Design language (2026, grounded)

- **Dark-mode-first.**
- **Bento-grid glance surface** — each module a self-contained story (a stat, a verdict, a trend), scannable but rewarding to explore. This *replaces* the flat equal-weight tiles Matthew disliked.
- **Scrollytelling for The Story** — the journey unfolds as you scroll (the NYT / The Pudding technique), turning data + arc into a cinematic, emotional, digestible narrative.
- **Editorial craft over dopamine-neon.** Restraint reads as credibility. Type as content. Motion only where it earns its weight.
- **Mobile-first Cockpit** (daily glance happens on a phone); richer on desktop for the deep read.
- **Do not echo WHOOP's actual dashboard look** — it undercuts the authenticity wedge, and WHOOP is currently litigating "look and feel."
- **Correlative framing everywhere** (Henning standard). The delivered cross-pillar synthesis must never assert causation; N<30 = low confidence, <12 obs = "preliminary pattern."

---

## 10. Open / deferred to the design brief

- **The Cockpit interaction pattern: Mara's focus model vs Tyrell's relational canvas.** Deliberately not pre-decided. With the two jobs (§5) locked, Tyrell + Mara prototype *both* and test against the job rather than argue taste. The job is the acceptance criterion.

---

## 11. Editorial guardrails (carry over to The Story and all public surfaces)

Existing platform guardrails remain in force on anything public-facing:
- No employer, industry, or role specifics.
- Partner is never named publicly.
- The two designated vice categories are never named publicly.
- Past bereavement stays out unless Matthew explicitly opts in.
- Chest-tightness references are paired with cardiovascular bloodwork framing only.
- Escapism stays metaphorical.

Honesty about the *journey* (the down days, the pauses) is required; honesty does not mean disclosing the items above.

---

## 12. Governance (who owns which call going forward)

- **Product Board** — UI/UX, journey, audience, story, monetization. Owns The Story and Cockpit experience decisions.
- **Technical Board** — architecture, data model, security, cost, AI trustworthiness. Owns how the three doors are built over the one engine.
- **Personal Board** — purpose, the human truth, the honesty principle, the pillar/scoring integrity. Owns *why*, not the CSS.
- Full rosters: `docs/BOARDS.md`. When boards disagree, the tiebreaker is the throughline and the north star (§0): does this help an ordinary person connect the story and believe it?

---

## Next deliverables (this doc feeds both)
1. **Claude Design brief** (Tyrell + Mara): visual system, the bento Cockpit, the scrollytelling Story, the in-place disclosure interaction — prototyping the §10 pattern against §5.
2. **Claude Code build instruction**: the implementation spec for the three doors over the existing engine.
