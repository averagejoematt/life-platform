# Story & About Page Review Spec
## `/story/index.html` and `/about/index.html`

> Authored by: Product Board of Directors, Life Platform
> Date: 2026-03-28
> For: Claude Code — complete implementation guide
> Priority: Pre-launch (April 1) + Week-of-launch improvements

---

## Overall Assessment

The Story page is exceptional — one of the best founder-story pages the board has reviewed.
The prose is raw, honest, and earns trust immediately. Chapter 1 in particular is outstanding.
The About page has strong bones but needs a few targeted improvements: a JS bug to fix, a
bridge sentence to connect it emotionally to the Story, and the Mission Brief sidebar updated
from static placeholder to live data.

The notes below are surgical, not fundamental. Do not rewrite — refine.

---

## SECTION 1 — BUGS (fix before April 1)

### Bug 1: Broken JS reference on About page

**File:** `site/about/index.html`

**Issue:** The JavaScript at the bottom of the page attempts to set the text content of
an element with `id="about-weight"`, but no such element exists anywhere in the HTML.
This silently fails on every page load.

```javascript
// This line exists in the about page JS but the element doesn't exist:
document.getElementById('about-weight').textContent = ...
// Results in: Cannot set properties of null (reading 'textContent')
```

**Fix option A (recommended):** Add a live weight display to the Mission Brief sidebar.
In the dossier sidebar, find the Physical section row for "Weight" which currently reads:

```html
<span style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text);">
  <span data-const="journey.start_weight">302</span> &rarr;
  <span data-const="journey.goal_weight" style="color:var(--accent)">185</span> lbs
</span>
```

Replace the start weight span with a live current weight display:

```html
<span style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text);">
  <span id="about-weight" data-const="journey.start_weight">302</span> &rarr;
  <span data-const="journey.goal_weight" style="color:var(--accent)">185</span> lbs
</span>
```

Now `getElementById('about-weight')` finds this element and updates it with the live value.

**Fix option B (minimal):** If the live weight display isn't wanted on the About page, just
remove the JS block that attempts to update it. Search for `about-weight` in the script at
the bottom and delete that block.

---

### Bug 2: Story Day Counter pre-launch and Day 1 states

**File:** `site/story/index.html`

**Issue:** The "Days in — and counting" milestone computes from April 1, 2026. Before
launch, `Math.max(0, ...)` floors it to 0, which shows as `0` — reads oddly.
On April 1 exactly, it shows `0`, not `1`.

**Fix:** Update the day calculation in the story page script to:
1. Show a pre-launch label before April 1
2. Show "Day 1" on April 1
3. Show correct day count after

Find the existing day calculation block:
```javascript
var daysIn = (d.journey || {}).days_in || (d.platform || {}).days_in;
if (daysIn == null) daysIn = Math.max(0, Math.floor((Date.now() - new Date('2026-04-01').getTime()) / 86400000));
var dxEl = document.getElementById('story-day-x');
if (dxEl) dxEl.textContent = daysIn;
```

Replace with:
```javascript
var daysIn = (d.journey || {}).days_in || (d.platform || {}).days_in;
var dxEl = document.getElementById('story-day-x');
if (dxEl) {
  if (daysIn != null) {
    dxEl.textContent = daysIn;
  } else {
    var msIn = Date.now() - new Date('2026-04-01T07:00:00-07:00').getTime();
    if (msIn < 0) {
      dxEl.textContent = '0';
      var label = dxEl.closest('.milestone');
      if (label) {
        var lbl = label.querySelector('.milestone__label');
        if (lbl) lbl.textContent = 'Launching April 1';
      }
    } else {
      dxEl.textContent = Math.max(1, Math.floor(msIn / 86400000) + 1);
    }
  }
}
```

Also update the static milestone label in the HTML from:
```html
<div class="milestone__label">Days in &mdash; and counting</div>
```
to:
```html
<div class="milestone__label" id="story-days-label">Day &mdash; and counting</div>
```

---

### Bug 3: Chapter 4 "experiment hasn't started yet" copy

**File:** `site/story/index.html`

**Issue:** Chapter 4 currently contains: *"This chapter is deliberately short, because the
experiment hasn't started yet."* This copy will be visible indefinitely after April 1 unless
updated.

**Fix:** Add launch-aware state switching. Find the Chapter 4 section and replace the
placeholder paragraph with a two-state version:

Find:
```html
<p>
  This chapter is deliberately short, because the experiment hasn't started yet.
</p>
<p>
  What I do have is history. Ten years of weight scale logs...
</p>
```

Replace with:
```html
<p id="ch4-prelaunch" class="ch4-state">
  This chapter is deliberately short, because the experiment hasn't started yet.
  What I do have is history — ten years of weight scale logs that tell the same
  story on repeat. April 1 is when the real data begins.
</p>
<p id="ch4-postlaunch" class="ch4-state" style="display:none">
  The data is accumulating. What follows will grow as the experiment runs —
  updated as patterns emerge and findings solidify.
  <a href="/explorer/" style="color:var(--accent);border-bottom:1px solid var(--accent-dim);">See the live correlations &rarr;</a>
</p>
```

Add to the launch-detection script block (the one that already checks `AMJ_EXPERIMENT.isLive`):
```javascript
// Chapter 4 state flip
var isLive = (window.AMJ_EXPERIMENT && window.AMJ_EXPERIMENT.isLive) ||
             (new Date() >= new Date('2026-04-01T00:00:00-07:00'));
if (isLive) {
  var pre = document.getElementById('ch4-prelaunch');
  var post = document.getElementById('ch4-postlaunch');
  if (pre) pre.style.display = 'none';
  if (post) post.style.display = '';
}
```

---

### Bug 4: Subscriber count endpoint

**File:** `site/story/index.html`

**Issue:** The story page bottom CTA shows "Join — people following the experiment" and
fetches `/api/subscriber_count`. This endpoint may not exist. If it returns a non-OK
response or throws, the count stays `—` forever.

**Fix:** Verify the endpoint exists. If it does exist: ensure it returns `{"count": N}`.
If it doesn't exist yet: hide the entire count line until it does:

Find:
```javascript
fetch('/api/subscriber_count').then(r=>r.ok?r.json():null).then(d=>{if(d&&d.count>50)document.getElementById('story-sub-count').textContent=d.count}).catch(()=>{});
```

The current code already guards against showing counts ≤ 50 (`d.count > 50`), which is
correct — don't show a small count. The `catch(()=>{})` means it fails silently. This is
fine as-is; verify the endpoint returns valid JSON when it has data.

---

## SECTION 2 — WAVEFORM EMPTY STATE REDESIGN

**File:** `site/story/index.html`

**Issue:** When no waveform data exists, the chart area shows:
```
"The pattern emerges as data accumulates — check back after Week 4"
```
in a plain div inside the chart container. This reads as a loading failure, not an
intentional design state.

**Fix:** Replace the fallback text with a designed empty state. Find the waveform
rendering block:

```javascript
var chart = document.getElementById('waveform-chart');
if (!chart || !days.length) return;
```

The `.catch()` block and the early return both fall through to the original placeholder.
Replace the original placeholder HTML with a designed empty state.

Find in the HTML:
```html
<div class="waveform-chart" id="waveform-chart">
  <div style="width:100%;padding:var(--space-4);font-size:var(--text-xs);color:var(--text-faint);font-family:var(--font-mono);text-align:center;">The pattern emerges as data accumulates &mdash; check back after Week 4</div>
</div>
```

Replace with:
```html
<div class="waveform-chart" id="waveform-chart">
  <div id="waveform-empty" style="width:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--space-3);">
    <div style="display:flex;align-items:flex-end;gap:3px;height:80px;opacity:0.12;">
      <!-- Ghost bars — intentional empty state, not a loading error -->
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:35%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:55%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:40%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:70%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:45%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:60%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:30%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:80%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:50%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:65%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:45%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:75%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:35%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:55%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:90%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:60%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:40%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:70%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:50%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:85%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:45%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:60%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:30%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:75%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:55%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:40%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:65%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:50%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:80%"></div>
      <div style="flex:1;background:var(--surface-raised);border-radius:2px 2px 0 0;height:35%"></div>
    </div>
    <div style="font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);color:var(--text-faint);text-transform:uppercase;">Signal emerging &mdash; data accumulates from April 1</div>
  </div>
</div>
```

Also update the waveform JS: when the fetch succeeds and days are rendered, hide the
`#waveform-empty` element:
```javascript
// After the days.forEach loop that builds bars:
var empty = document.getElementById('waveform-empty');
if (empty) empty.style.display = 'none';
```

And in the `.catch()` block, show it explicitly (it's already shown by default, so no change
needed there).

---

## SECTION 3 — ABOUT PAGE CONTENT BRIDGE

**File:** `site/about/index.html`

**Issue:** A visitor who arrives on the About page directly (e.g. from a share of the
about URL, or via a search) encounters a professional bio with no emotional context. The
About page reads like a LinkedIn profile compared to the Story page's raw honesty. They're
the same person, same project — they should feel like the same voice.

**Fix:** Add one bridge sentence to the first paragraph of the bio prose. This is a
content edit, not a structural one.

Find the opening of the bio prose:
```html
<p>
  I've spent my career in IT — building teams, managing vendors, running infrastructure
  at scale. My job has always been making complex systems reliable and getting people to
  actually use them. I'm not a developer by training...
```

Replace the opening paragraph with:
```html
<p>
  I've lost 100 pounds before. Multiple times. This platform is my attempt to understand
  why it keeps coming back — and whether a system can catch what willpower can't.
</p>
<p>
  I've spent my career in IT — building teams, managing vendors, running infrastructure
  at scale. My job has always been making complex systems reliable and getting people to
  actually use them. I'm not a developer by training...
```

This one paragraph addition does three things: it creates immediate emotional context,
it tethers the About page to the Story, and it gives visitors who land here directly the
same hook that the Story page earns through five chapters.

---

## SECTION 4 — MISSION BRIEF SIDEBAR CLEANUP

**File:** `site/about/index.html`

**Issue:** The Mission Brief dossier shows:
1. `Status: Day 1 — April 2026` — will be immediately stale after launch
2. Physical goals include "300lb+ compound lifts" and "Half marathon baseline" which are
   long-horizon aspirational goals that may read as misleading given current fitness state

**Fix 1 — Status line (launch-aware):**

Find:
```html
<div style="display:flex;justify-content:space-between;align-items:baseline;">
  <span style="font-family:var(--font-mono);...color:var(--text-faint);">Status</span>
  <span style="font-family:var(--font-mono);...color:var(--c-amber-500);">Day 1 &mdash; April 2026</span>
</div>
```

Replace with a JS-updated live status:
```html
<div style="display:flex;justify-content:space-between;align-items:baseline;">
  <span style="font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-faint);">Status</span>
  <span id="about-status-day" style="font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--c-amber-500);">Launching April 1</span>
</div>
```

Add to the JS block at the bottom of the about page:
```javascript
// Update status day
(function() {
  var el = document.getElementById('about-status-day');
  if (!el) return;
  var msIn = Date.now() - new Date('2026-04-01T07:00:00-07:00').getTime();
  if (msIn >= 0) {
    var dayNum = Math.max(1, Math.floor(msIn / 86400000) + 1);
    el.textContent = 'Day ' + dayNum + ' \u2014 Active';
  }
})();
```

**Fix 2 — Simplify Physical goals:**

The current physical goal rows include aspirational metrics. Simplify to just what's
verified and meaningful for a visitor who doesn't know Matthew's history:

Find the Physical section in the dossier and replace the rows with:
```html
<div style="display:flex;flex-direction:column;gap:var(--space-2);">
  <div style="display:flex;justify-content:space-between;align-items:baseline;">
    <span style="font-size:var(--text-xs);color:var(--text-muted);">Weight</span>
    <span style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text);"><span id="about-weight" data-const="journey.start_weight">302</span> &rarr; <span data-const="journey.goal_weight" style="color:var(--accent)">185</span> lbs</span>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:baseline;">
    <span style="font-size:var(--text-xs);color:var(--text-muted);">Lost so far</span>
    <span style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--accent);" id="about-lost">— lbs</span>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:baseline;">
    <span style="font-size:var(--text-xs);color:var(--text-muted);">Movement</span>
    <span style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text);">Walk, lift, run. Daily.</span>
  </div>
</div>
```

Add live "lost so far" calculation to the about page JS:
```javascript
// After getting live weight:
var lostEl = document.getElementById('about-lost');
if (lostEl && w) {
  var startWeight = 302;
  var lost = Math.max(0, startWeight - Math.round(w * 10) / 10);
  if (lost > 0) lostEl.textContent = lost.toFixed(1) + ' lbs';
}
```

---

## SECTION 5 — SUBSCRIBE CTA PLACEMENT ON STORY PAGE

**File:** `site/story/index.html`

**Issue:** Chapter 5 ("Why Public") ends with: *"You're welcome to watch."*
This is the emotional high point of the entire story — arguably the best line on the site.
The subscribe form is not immediately below it. Instead there are ~400px of "tech/life
intersection" cards before the CTA appears.

The emotional momentum that "You're welcome to watch." builds dissipates before the
conversion moment arrives.

**Fix:** Move the subscribe CTA section to appear directly after the `</div>` that closes
Chapter 5, before the story-nav and before the intersection cards.

1. Find the subscribe CTA section (starts with `<section style="padding: var(--space-16) var(--page-padding); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); background: var(--surface); text-align: center;">` and ends with `</section>`)
2. Cut it from its current position
3. Paste it immediately after `</div><!-- /story-body -->` and before `<!-- Journey Timeline -->`

The intersection cards and journey timeline should come after the CTA, not before it.
Visitors who want to go deeper find the data sections; visitors who are ready to subscribe
convert at the emotional peak.

**Note:** The `<hr class="chapter-divider">` that currently precedes Chapter 5 ends cleanly.
After moving the CTA, the section order should be:
1. Story body (chapters 1–5)
2. Subscribe CTA ← move here
3. Journey Timeline
4. Waveform
5. Intersection cards
6. Story nav

---

## SECTION 6 — "WHY NOT JUST APPLE HEALTH" CALLOUT — ELEVATE

**File:** `site/about/index.html`

**Issue:** The "Why not just Apple Health?" callout is the single most persuasive piece of
content on the About page. It directly addresses the objection every technically-curious
visitor will have. It's currently buried at the bottom of the bio section, after the
link cards.

**Fix:** Move it up — make it the anchor between the bio prose and the link cards section.

Current page order:
1. Page header
2. Bio prose + dossier sidebar (two columns)
3. "Why not just Apple Health?" callout ← currently here
4. "What I've built" link cards
5. "The build" stack rows
6. Connect / email section
7. Subscribe CTA

**Recommended order:**
1. Page header
2. Bio prose + dossier sidebar
3. "Why not just Apple Health?" callout ← move UP (between bio and link cards)
4. "What I've built" link cards
5. "The build" stack rows
6. Connect / email section
7. Subscribe CTA

This is a cut-and-paste of the `<section style="padding:var(--space-10)...">` block.
No content change needed — just position.

---

## SECTION 7 — ABOUT PAGE META TAG FIXES

**File:** `site/about/index.html`

**Issue:** The page meta description says:
`"About Matthew — the person behind the Life Platform experiment."`

This is generic and wastes the OG/Twitter card opportunity. After the content bridge
(Section 3) lands, the About page will lead with the weight loss story hook. The meta
description should match:

**Fix:**
```html
<!-- Replace: -->
<meta name="description" content="About Matthew — the person behind the Life Platform experiment.">
<meta property="og:description" content="Career IT background. No engineering degree. Building the infrastructure to understand himself.">
<meta name="twitter:description" content="Career IT background. No engineering degree. Building the infrastructure to understand himself.">

<!-- With: -->
<meta name="description" content="I've lost 100 pounds before. Multiple times. This platform is my attempt to understand why it keeps coming back.">
<meta property="og:description" content="IT career, no engineering degree. Building a 19-source AI health platform to catch what willpower can't. Starting April 1.">
<meta name="twitter:description" content="IT career, no engineering degree. Building a 19-source AI health platform to catch what willpower can't. Starting April 1.">
```

Also update the About page `<title>`:
```html
<!-- Replace: -->
<title>About — Matthew</title>
<!-- With: -->
<title>The Mission — averagejoematt.com</title>
```

---

## Implementation Checklist for Claude Code

Complete in this order. All items marked [APRIL 1] must be done before launch.
Items marked [WEEK 1] can be done in the first week after launch.

```
BUGS — MUST FIX BEFORE APRIL 1
[ ] 1.  [APRIL 1] Fix Bug 1: add id="about-weight" to Mission Brief weight span (Section 1, Bug 1)
[ ] 2.  [APRIL 1] Fix Bug 2: update story day counter for pre/post launch states (Section 1, Bug 2)
[ ] 3.  [APRIL 1] Fix Bug 3: add Chapter 4 two-state logic with isLive detection (Section 1, Bug 3)
[ ] 4.  [APRIL 1] Verify Bug 4: confirm /api/subscriber_count exists and returns valid JSON

WAVEFORM EMPTY STATE
[ ] 5.  [APRIL 1] Replace inline placeholder text with designed ghost bars (Section 2)
[ ] 6.  [APRIL 1] Update waveform JS to hide ghost bars when real data renders (Section 2)

ABOUT PAGE CONTENT
[ ] 7.  [APRIL 1] Add bridge paragraph to About page bio opening (Section 3)
[ ] 8.  [APRIL 1] Replace Status line with JS-updated live day counter (Section 4, Fix 1)
[ ] 9.  [APRIL 1] Simplify Physical goals — add "Lost so far" live row (Section 4, Fix 2)
[ ] 10. [APRIL 1] Update About page meta description and title tag (Section 7)

STORY PAGE CTA PLACEMENT
[ ] 11. [APRIL 1] Move subscribe CTA to directly after Chapter 5 (Section 5)

ABOUT PAGE LAYOUT
[ ] 12. [WEEK 1] Move "Why not Apple Health?" callout up before link cards (Section 6)

SMOKE TESTS
[ ] 13. Open /about/ — verify no JS console errors, live weight displays, day counter works
[ ] 14. Open /story/ — verify day counter shows correct value, waveform shows ghost bars
[ ] 15. Open /story/ — verify subscribe CTA appears directly after "You're welcome to watch."
[ ] 16. Check /story/ on mobile — waveform and milestone bar should be readable
[ ] 17. git add -A && git commit -m "fix: story + about pre-launch punch list — product board review"
[ ] 18. Add CHANGELOG entry
```

---

## Notes for Claude Code

1. **Do not rewrite the Story page prose.** The writing is excellent and was approved by the
   Product Board. All changes are structural (CTA placement, empty states, JS fixes) — not
   content.

2. **The bridge paragraph on the About page (Section 3)** is the highest-impact single
   change on that page. It transforms the emotional register from professional bio to
   personal story. Be precise with this edit.

3. **The waveform ghost bars (Section 2)** should feel like an EKG waiting for signal —
   not a loading spinner. The low opacity (0.12) is intentional. Don't increase it.

4. **Section 4 goal simplification:** When removing the "Half marathon" and "300lb+ compound
   lifts" rows, the dossier will have fewer rows. This is fine — a tighter dossier is
   better than one with aspirational placeholder goals that may not land for 18+ months.

5. **All JS changes on the About page** should go in the existing `<script>` block at the
   bottom of the file, not as new separate script tags.

6. **The Chapter 4 post-launch state** (the `ch4-postlaunch` element) will start empty.
   Do not add fake data — the copy as written ("The data is accumulating...") is intentionally
   honest about having no findings yet. Matthew will update this content manually once
   patterns emerge after week 2-3.
