# averagejoematt.com — Launch Readiness Implementation Spec
**Issued:** 2026-03-31  
**Scope:** 4 targeted changes from Product Board pre-launch review  
**Implementer:** Claude Code  
**Priority:** Soft-launch foundation — all changes are additive, no destructive edits  
**Version:** 1.1 (updated after codebase inspection — see discovery notes per change)

---

## CONTEXT FOR IMPLEMENTER

This site is a live personal health data observatory. It soft-launches April 1 with no social promotion — data accumulates over 30-60 days before any public sharing. These 4 changes build the foundation for eventual audience. All changes are conservative: no structural redesigns, no new pages, no new infrastructure. Work entirely within existing files.

**Do not touch:** Design tokens, the evidence badge system, pull-quote markup, gauge ring animations, the SECTIONS array structure in `components.js`, any Lambda or DynamoDB code, the deploy pipeline, the Elena Voss narrative system.

**Project root:** `site/` for HTML, `site/assets/js/` for shared JS, `lambdas/` for Lambda code.

---

## CHANGE 1: Data Freshness — Observatory Pages

### Brief
Make it visually clear to visitors that this is a living, updating platform. The homepage already appends "Updated Xh ago" to the hero stats line (in the `public_stats.json` fetch block). The `initObsFreshness()` function and full `obs-freshness` CSS/HTML system already exists — it is defined in `site/assets/js/engagement.js` and the **mind page** (`site/mind/index.html`) already uses it correctly.

**The work:** Check each remaining observatory page (`sleep`, `glucose`, `nutrition`, `training`, `physical`) for the `#obs-freshness` element and `initObsFreshness()` call. If missing, add both using the mind page as the exact reference pattern.

### Reference Pattern (copy from `site/mind/index.html`)

**HTML element** — place in each page's hero section, near the stat strip or gauge row:
```html
<div class="obs-freshness" id="obs-freshness" style="display:none">
  <span class="obs-freshness__label">Last data: <span id="obs-fresh-time">—</span></span>
  <span class="obs-freshness__sub">Updated daily</span>
  <span class="obs-freshness__dot obs-freshness__dot--live" id="obs-fresh-dot"></span>
</div>
```

**JS call** — add in the script block at the bottom of each page, after the main data fetch resolves. Pattern from mind page:
```javascript
fetch('/api/observatory_week?domain=DOMAIN_NAME').then(r=>r.json()).then(d=>{
  if(d.last_updated) initObsFreshness(d.last_updated);
}).catch(function(){});
```
Replace `DOMAIN_NAME` with: `sleep`, `glucose`, `nutrition`, `training`, or `physical` as appropriate.

**Note:** `initObsFreshness()` is already globally available from `engagement.js` — no import needed. The CSS for `.obs-freshness` may be in the observatory shared stylesheet (`site/assets/css/observatory.css`) or inline in the mind page `<style>` block — check which and ensure the other pages can access those styles.

### Verification
After implementation, each observatory page hero should show a small pulsing dot + "Last data: Xh ago / today / X days ago" that appears only when data loads successfully.

---

## CHANGE 2: Inner Life Card Visual Elevation (Homepage)

### Brief
The 5-card observatory grid (`h-obs-grid` in `site/index.html`) gives every page equal visual weight. Inner Life is the site's most differentiated page — tracked psychology is what no other health site does. It should visually signal that distinction without disrupting the grid layout.

### Discovery Note
Inner Life is currently last in the 5-column grid and has no visual differentiation from the other 4 cards. **Do not change the card order** — Sleep → Glucose → Nutrition → Training → Inner Life follows a logical body-to-mind arc. Elevate visually, not structurally.

### Exact Change — `site/index.html`

Find the Inner Life obs card:
```html
<a href="/mind/" class="h-obs-card" style="border-left:3px solid var(--h-violet);">
  <div class="h-obs-card__name">INNER LIFE</div>
  <div class="h-obs-card__metric" id="h-obs-mind">&mdash;</div>
  <div class="h-obs-card__desc">Journaling, mood, mental health tracking. The data behind the data &mdash; what numbers can&rsquo;t capture alone.</div>
  <div class="h-obs-card__link">Explore &rarr;</div>
</a>
```

Replace with:
```html
<a href="/mind/" class="h-obs-card h-obs-card--featured" style="border-left:3px solid var(--h-violet);">
  <div style="font-family:var(--font-mono);font-size:var(--text-3xs);letter-spacing:2px;text-transform:uppercase;color:var(--h-violet);margin-bottom:var(--space-1);opacity:0.8">★ FEATURED</div>
  <div class="h-obs-card__name">INNER LIFE</div>
  <div class="h-obs-card__metric" id="h-obs-mind">&mdash;</div>
  <div class="h-obs-card__desc">Journaling, mood, mental health tracking. The data behind the data &mdash; what numbers can&rsquo;t capture alone.</div>
  <div class="h-obs-card__callout" style="font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--h-violet);margin-top:var(--space-2);opacity:0.75;transition:opacity var(--dur-fast)">The only page like this on the internet.</div>
  <div class="h-obs-card__link">Explore &rarr;</div>
</a>
```

Add to the homepage `<style>` block (use rgba fallback — `color-mix` may not be in all browsers):
```css
.h-obs-card--featured { background: rgba(129, 140, 248, 0.04); }
.h-obs-card--featured:hover { background: rgba(129, 140, 248, 0.08); }
.h-obs-card--featured:hover .h-obs-card__callout { opacity: 1; }
```

---

## CHANGE 3: "Why Public?" Micro-Statement (Homepage)

### Brief
Skeptical first-time visitors ask "why is this public?" within their first 30 seconds. If unanswered, they leave. The `#amj-bio` div already exists below the hero and contains Matthew's name and starting weight — extend it with one sentence that answers the question before it's asked.

### Exact Change — `site/index.html`

Find:
```html
<div id="amj-bio" style="max-width:var(--max-width);margin:0 auto;padding:var(--space-4) var(--page-padding);">
  <div style="font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-wide);text-transform:uppercase;color:var(--text-faint);">Matthew &middot; Seattle, WA</div>
  <div style="font-size:var(--text-sm);color:var(--text-muted);line-height:1.7;margin-top:var(--space-1);">Started at 307 lbs. Built this entire platform with Claude as a development partner.</div>
</div>
```

Replace with:
```html
<div id="amj-bio" style="max-width:var(--max-width);margin:0 auto;padding:var(--space-4) var(--page-padding);">
  <div style="font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-wide);text-transform:uppercase;color:var(--text-faint);">Matthew &middot; Seattle, WA</div>
  <div style="font-size:var(--text-sm);color:var(--text-muted);line-height:1.7;margin-top:var(--space-1);">Started at 307 lbs. Built this entire platform with Claude as a development partner.</div>
  <div style="font-size:var(--text-sm);color:var(--text-faint);line-height:1.7;margin-top:var(--space-1);font-style:italic;">Made public because accountability needs an audience.</div>
</div>
```

No CSS changes needed. `var(--text-faint)` color makes this read as a secondary annotation, not a headline — intentional.

---

## CHANGE 4: Email Welcome Message

### Brief
New subscribers receive a confirmation/welcome email. This is the first impression of the ongoing relationship. It should feel like a direct dispatch from Matthew, set honest expectations, and give the subscriber one concrete thing to do right now.

### Discovery Note
The subscribe flow goes through `lambdas/email_subscriber_lambda.py`. Find the function that sends the post-confirmation welcome email (sent after the subscriber clicks the confirm link in double opt-in). If no welcome email exists beyond the confirmation click, add one. Do **not** change the weekly Chronicle digest format.

### Email Content

**Subject:** `You're in. Here's what you just signed up for.`  
**Preheader/preview text:** `Every Wednesday. Real data. No highlight reel.`

**Plain-text body:**
```
Hey —

You just subscribed to The Measured Life. Every Wednesday, you'll get a dispatch 
from the experiment: what the data showed, what I tried, what surprised me, and 
what I'm thinking about next.

This is a real experiment with real data. Not a highlight reel. The weeks the 
numbers go the wrong direction are in there too.

Right now, the site is brand new and the data is just starting to accumulate. 
That's on purpose — I wanted you to be able to see the whole journey from the 
beginning, not just the polished version.

A few things worth looking at while you're here:

→ The Score (character sheet): https://averagejoematt.com/character/
→ Inner Life Observatory: https://averagejoematt.com/mind/
→ The Story (why I started): https://averagejoematt.com/story/

See you Wednesday.

— Matt

averagejoematt.com
[Unsubscribe link]
```

### Implementation Notes
- Match the existing SES send pattern already in `email_subscriber_lambda.py` — use the same `boto3` SES client, same from-address, same reply-to
- Use `Body={'Text': {'Data': body_text, 'Charset': 'UTF-8'}}` — plain text is preferred at this stage over HTML template
- If a double opt-in confirmation link flow exists, this welcome email fires **after** confirmation is clicked, not at initial subscribe
- If the Lambda currently only records the subscription and sends a single confirmation email (no separate welcome), convert the post-confirmation send into the welcome copy above
- Do **not** change the `wednesday_chronicle_lambda.py` or Elena Voss narrative in any way

### Lambda Deploy
After editing:
```
bash deploy/deploy_lambda.sh email-subscriber
```

---

## DEPLOY CHECKLIST

### Site files (Changes 1, 2, 3)
Copy each modified file individually — **never use `aws s3 sync --delete`** against bucket root:
```
aws s3 cp site/index.html s3://matthew-life-platform/site/index.html
aws s3 cp site/sleep/index.html s3://matthew-life-platform/site/sleep/index.html
aws s3 cp site/glucose/index.html s3://matthew-life-platform/site/glucose/index.html
aws s3 cp site/nutrition/index.html s3://matthew-life-platform/site/nutrition/index.html
aws s3 cp site/training/index.html s3://matthew-life-platform/site/training/index.html
aws s3 cp site/physical/index.html s3://matthew-life-platform/site/physical/index.html
```
(Mind page already has freshness — skip unless other changes were made to it)

### CloudFront invalidation
```
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"
```

### Lambda (Change 4 only)
```
bash deploy/deploy_lambda.sh email-subscriber
```

---

## VERIFICATION CHECKLIST

- [ ] Each observatory page hero shows `#obs-freshness` element with pulsing dot when data loads
- [ ] Element is hidden (`display:none`) when data fetch fails — no error state shown
- [ ] Inner Life card in homepage obs grid has `★ FEATURED` badge above card name
- [ ] Inner Life card has subtle violet-tinted background vs white of other cards
- [ ] Inner Life card shows "The only page like this on the internet." callout on hover at full opacity
- [ ] `#amj-bio` on homepage shows "Made public because accountability needs an audience." in italic faint text
- [ ] No layout breaks on mobile — test obs grid at 600px viewport
- [ ] Subscribe flow: new subscriber receives welcome email with correct subject and body after confirming
- [ ] No JavaScript console errors on homepage or observatory page loads
- [ ] CloudFront invalidation confirmed before testing live

---

## SCOPE GATE

If any change requires: a new Lambda function, a new DynamoDB partition, a new API endpoint, a new site page, or changes to the CI/CD pipeline — **stop and flag it**. All four changes should be achievable with HTML/CSS edits to existing files plus one email body update. Simpler is always correct.

**Do not touch:** The hero title/subtitle copy, the pull-quote markup, the evidence badge system, the SECTIONS array in `components.js`, the Elena Voss chronicle system, gauge ring animations, or anything in `deploy/deploy_lambda.sh` logic itself.
