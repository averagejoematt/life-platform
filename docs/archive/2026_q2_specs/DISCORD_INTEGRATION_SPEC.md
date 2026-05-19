# Discord Integration Spec & Design Brief
## averagejoematt.com — "Average Joe Community"

**Spec version:** 1.0  
**Discord invite:** https://discord.gg/T4Ndt2WsU  
**Server name:** Average Joe Community  
**Prepared:** March 2026

---

## Philosophy

> *Quiet presence, not aggressive promotion.*

The Discord integration should feel like finding a door you didn't know was there — not a billboard you can't avoid. The site's job is the observatory. The Discord's job is connection. Don't confuse the two. The signal we're sending: *"If you want to talk about this, there's a place for that. No pressure."*

**What this integration is NOT:**
- A persistent floating chat widget
- A popup or modal interrupt
- A hero-section CTA
- A sticky banner
- Something that appears before the visitor has earned it by reading

**What this integration IS:**
- A quiet invitation at the right emotional moment
- Consistent with the site's monospace/amber/dark design language
- Present on every page in one small, unobtrusive form (footer)
- Elevated at the 2–3 pages where connection is most natural

---

## Design Language Reference

All Discord components must use existing site tokens exactly. No new colors, no new type scales.

```
Background base:    #08090e  (site dark)
Surface:            #0f1117  (card bg)
Surface elevated:   #161820  (hover/active)
Amber accent:       #EF9F27  (primary CTA color — gauge rings, monospace headers)
Amber muted:        rgba(239,159,39,0.15)  (subtle fills)
Amber border:       rgba(239,159,39,0.25)  (quiet borders)
Text primary:       #e8e6df
Text secondary:     #8c8a82
Text muted:         #4a4944
Monospace font:     'Courier New', Courier, monospace
Body font:          site body font (match existing)
Border radius:      4px (cards), 2px (tight), 0 (left-accent)
```

**Discord's brand color (#5865F2) must NOT appear on site.** Use the site's amber. The Discord icon/logo can appear but only in white or amber, not in Discord purple.

---

## Component Library

Three components, from smallest to largest. Build all three.

---

### Component A — Footer Pill
**Use:** Site-wide footer. Always present. Smallest possible footprint.

```
[ ⌗ ] Join the Community  ↗
```

**Spec:**
- Inline with other footer links — not a card, not a button
- `⌗` or a minimal hash/grid glyph in amber (12px)
- Text: `"Join the community"` — sentence case, `color: #8c8a82` (secondary)
- Hover: text brightens to `#e8e6df`, amber glyph brightens
- Font: site body, 13px
- Opens Discord in new tab
- No border, no background, no box — pure inline text link treatment
- Position: under "Follow" column in footer, between Subscribe and Chronicle links

**Copy:** `Join the community ↗`

---

### Component B — Understated Card
**Use:** End of Inner Life page, end of Chronicle entries, end of Accountability page. The "you've read enough to want to talk" moment.

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│  ⌗ COMMUNITY ─────────────────────────────         │
│                                                     │
│  Tracking something yourself? Want to talk about    │
│  what the data actually means? There's a place.    │
│                                                     │
│  [ Join Average Joe Community → ]                   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Spec:**
- Width: full-width within content column (matches pull-quote width)
- Background: `#0f1117`
- Left border: 2px solid `rgba(239,159,39,0.4)` — the site's left-accent rule card pattern
- Padding: 24px 28px
- Section header: monospace, 11px, amber, letter-spacing 3px, `COMMUNITY` followed by `──` dash line (matches site pattern)
- Body copy: 15px, `color: #8c8a82`, line-height 1.7 — 2 lines max
- CTA: amber text link with `→` arrow, no box/button, 14px
- Hover: CTA underlines
- No icon, no Discord branding

**Copy variants by page:**

*Inner Life / Mind page:*
> "Tracking your own patterns? Want to compare notes on what you're finding? There's a place for that."

*Chronicle entries:*
> "Have thoughts on this week's data? Want to follow along and talk about it? The community is open."

*Accountability page:*
> "Going through something similar? Following along on your own journey? Come say hi."

*Generic (fallback):*
> "Want to talk about this data, ask questions, or share your own tracking? There's a community for that."

---

### Component C — Section Break CTA
**Use:** One placement only — between sections on the Inner Life page, specifically after the most emotionally resonant section (mood trajectory, journal themes, or the psychological patterns section). This is the page most likely to create a "I feel seen" reaction in a stranger.

```
─────────────────────────────────────────────────────────────

  "If any of this resonates — you're not the only one
   tracking their way through it."

  ⌗ Average Joe Community · discord.gg/T4Ndt2WsU

─────────────────────────────────────────────────────────────
```

**Spec:**
- Full-width horizontal rule above and below (1px, `rgba(239,159,39,0.15)`)
- Padding: 32px 0
- Quote text: italic, 16px, `color: #8c8a82`, centered
- Attribution line: monospace, 12px, amber, letter-spacing 2px, centered
- The URL `discord.gg/T4Ndt2WsU` is the actual clickable link — visible URL, not a button label
- No border, no card, no background — pure typographic moment in the flow
- Feels like a pull-quote, not an ad

---

## Placement Map

| Page | Component | Location | Rationale |
|------|-----------|----------|-----------|
| All pages | A (Footer Pill) | Footer "Follow" column | Persistent, zero friction, non-intrusive |
| Inner Life / Mind | B (Card) | After final section, before page footer | Highest emotional resonance page on site |
| Inner Life / Mind | C (Section Break) | After mood/psychological patterns section | The exact moment a stranger might feel "this is me" |
| Chronicle entries | B (Card) | After each entry body, before pagination | Post-narrative, reader is engaged |
| Accountability | B (Card) | After the current-state section | The "social contract" page invites community naturally |
| Story / About | B (Card) | After journey timeline, before reading path CTA | Stranger has just learned who you are |
| Homepage | — | None | Too early. Visitor hasn't earned it yet. |
| Observatory pages (Sleep, Glucose, etc.) | — | None | Wrong context. Data pages are for reading, not connecting. |
| Character / Habits | — | None | Gamification context — Discord would feel out of place |

**Total instances on any single page:** Maximum 2 (Component C + Component B on Inner Life page only). All other pages: 1 or 0 above-footer instances.

---

## Copy Principles

**1. Never say "Discord."**  
Use "community," "the community," or `discord.gg/T4Ndt2WsU` as the visible URL. The word "Discord" reads as "platform" and distances people. "Community" is the promise.

**2. Make it about them, not about you.**  
Wrong: `"I made a Discord for my readers."`  
Right: `"Tracking something yourself? There's a place."`

**3. Always two lines or fewer.**  
This is an invitation, not a pitch. If you can't say it in 30 words, cut.

**4. Never use urgency language.**  
No "join now," no "be the first," no member counts. Scarcity tactics are incompatible with the site's radical transparency brand.

**5. The URL is the CTA.**  
`discord.gg/T4Ndt2WsU` as visible text (linked) is more authentic than a styled button. It reads as "here's a place" not "click this conversion element."

---

## Implementation Notes

### HTML pattern for Component A (footer pill):
```html
<a href="https://discord.gg/T4Ndt2WsU" target="_blank" rel="noopener" 
   class="footer-community-link">
  <span class="community-glyph">⌗</span> Join the community
</a>
```

```css
.footer-community-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #8c8a82;
  text-decoration: none;
  font-size: 13px;
  transition: color 0.2s;
}
.footer-community-link:hover { color: #e8e6df; }
.community-glyph { color: #EF9F27; font-size: 12px; }
```

---

### HTML pattern for Component B (understated card):
```html
<div class="discord-community-card">
  <div class="community-card-header">⌗ COMMUNITY ──────────────</div>
  <p class="community-card-body">
    Tracking something yourself? Want to compare notes on what 
    you're finding? There's a place for that.
  </p>
  <a href="https://discord.gg/T4Ndt2WsU" target="_blank" rel="noopener"
     class="community-card-cta">Join Average Joe Community →</a>
</div>
```

```css
.discord-community-card {
  border-left: 2px solid rgba(239,159,39,0.4);
  background: #0f1117;
  padding: 24px 28px;
  margin: 40px 0;
  border-radius: 0 4px 4px 0;
}
.community-card-header {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: #EF9F27;
  letter-spacing: 3px;
  margin-bottom: 14px;
}
.community-card-body {
  font-size: 15px;
  color: #8c8a82;
  line-height: 1.7;
  margin: 0 0 16px 0;
}
.community-card-cta {
  font-size: 14px;
  color: #EF9F27;
  text-decoration: none;
}
.community-card-cta:hover { text-decoration: underline; }
```

---

### HTML pattern for Component C (section break):
```html
<div class="discord-section-break">
  <hr class="community-rule">
  <blockquote class="community-quote">
    "If any of this resonates — you're not the only one tracking their way through it."
  </blockquote>
  <p class="community-url">
    ⌗ Average Joe Community · 
    <a href="https://discord.gg/T4Ndt2WsU" target="_blank" rel="noopener">
      discord.gg/T4Ndt2WsU
    </a>
  </p>
  <hr class="community-rule">
</div>
```

```css
.discord-section-break {
  padding: 32px 0;
  text-align: center;
}
.community-rule {
  border: none;
  border-top: 1px solid rgba(239,159,39,0.15);
  margin: 0;
}
.community-quote {
  font-style: italic;
  font-size: 16px;
  color: #8c8a82;
  line-height: 1.7;
  margin: 24px auto;
  max-width: 520px;
}
.community-url {
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: #EF9F27;
  letter-spacing: 2px;
  margin: 0;
}
.community-url a {
  color: #EF9F27;
  text-decoration: none;
}
.community-url a:hover { text-decoration: underline; }
```

---

## Anti-Patterns (Do Not Build)

- ❌ Floating widget or chat bubble in corner
- ❌ Modal or popup triggered by scroll depth or exit intent
- ❌ "X members online" live counter (empty Discord will backfire)
- ❌ Discord purple (#5865F2) anywhere in the UI
- ❌ CTA above the fold on any page
- ❌ More than 2 Discord references visible at once on any page
- ❌ "Follow us on Discord" language — it's a community, not a channel
- ❌ Any Discord embed widget (iframes, activity feeds) — adds weight, looks messy

---

## Launch Sequence

1. **April 1 (launch day):** Deploy Component A (footer pill) only. Zero risk, zero friction.
2. **Week 2:** Deploy Component B to Inner Life page and Chronicle entries.  
3. **After first Reddit post / if Discord gets any members:** Deploy Component C to Inner Life page.
4. **Hold everything else** until you see whether members are actually joining.

This staged approach means you never have a "community CTA on a dead community" moment. The footer pill works whether there's 0 members or 1,000.

---

## Files to Update

| File | Change |
|------|--------|
| `site/assets/css/observatory.css` or page `<style>` blocks | Add `.discord-community-card`, `.discord-section-break`, `.footer-community-link` classes |
| `site/components.js` or footer HTML | Add Component A in footer "Follow" column |
| `site/inner-life/index.html` | Add Component C after mood section, Component B before footer |
| `site/chronicle/posts/*.html` | Add Component B after entry body (template-level) |
| `site/accountability/index.html` | Add Component B after current-state section |
| `site/story/index.html` | Add Component B after journey timeline |

---

*This spec is intentionally minimal. The site is the product. The Discord is the door at the back. Build it so that if someone never notices it, nothing is lost — but when the right person finds it at the right moment, it feels like it was always meant to be there.*
