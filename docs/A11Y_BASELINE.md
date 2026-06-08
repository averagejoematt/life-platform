# Accessibility & Performance Baseline

> **Status: PRE-v4 baseline (2026-05-24).** Captured on the v3 "dashboard" site, *before* the v4 three-door site (`/now/`, `/story/`, `/evidence/`) went live (v8.3.0, 2026-06-02). The numbers/fixes below reflect v3 and are **not representative of the live v4 site** — a fresh baseline on the v4 pages is needed. (Ongoing v4 a11y/render checks run via `tests/visual_qa.py`, ADR-076.)

First baseline captured 2026-05-24 as part of P2.4. Use this to detect regressions on future Lighthouse runs.

## How to re-run

```bash
npx lighthouse https://averagejoematt.com/          --form-factor=mobile --throttling-method=devtools --quiet --chrome-flags="--headless=new" --output=json --output-path=/tmp/lh-home.json
npx lighthouse https://averagejoematt.com/subscribe/ --form-factor=mobile --throttling-method=devtools --quiet --chrome-flags="--headless=new" --output=json --output-path=/tmp/lh-sub.json
```

Lighthouse 13.x, mobile profile, devtools throttling.

## Scores

### Homepage (`/`)

| Category        | 2026-05-24 baseline | 2026-05-24 after P2.4 fixes |
|-----------------|---------------------|-----------------------------|
| Performance     | 85                  | **90** ↑                    |
| Accessibility   | 92                  | **100** ↑                   |
| Best Practices  | 100                 | 100                         |
| SEO             | 100                 | 100                         |

Perf metrics (after): FCP 2.4s · LCP 3.0s · CLS 0.079 · TBT 40ms.

### Subscribe (`/subscribe/`)

| Category        | 2026-05-24 baseline | 2026-05-24 after P2.4 fixes |
|-----------------|---------------------|-----------------------------|
| Performance     | 82                  | 82                          |
| Accessibility   | 93                  | **100** ↑                   |
| Best Practices  | 100                 | 100                         |
| SEO             | 100                 | 100                         |

Perf metrics (after): FCP 3.0s · LCP 3.4s · CLS 0.151 · TBT 0ms. CLS is over the 0.1 budget; suspected from hero animation but not yet diagnosed.

## What changed in P2.4

1. **`--c-text-muted`** lifted from `#5a7565` (3.9:1) to `#708a7a` (5.2:1) on `#080c0a`. This single token fix resolved ~80% of color-contrast hits across the site, not just on homepage.
2. **`--c-green-300`** (= `--accent-dim`) lifted from `#258a68` (4.29:1) to `#2da97e` (5.5:1) on surface `#0f1612`.
3. **`.btn--cta`** text changed from `#fff` (2.77:1 on `#ff6b6b`) to `#0a0e0b` (7.6:1). Light-mode `:root[data-theme="light"] .btn--cta { color: #fff; }` rule deleted — it also failed (4.45:1 on `#cc4444`).
4. **Skip-link** added on homepage and subscribe page. Styled in `base.css` — hidden by default, visible on `:focus`.
5. **`<main id="main">`** landmark added to homepage and subscribe page.
6. **Six decorative gauge SVGs** on the homepage marked `aria-hidden="true" focusable="false"`. The value + label are in adjacent visible text, so the ring SVG is purely decorative.
7. **`.fp-masthead__strip` Yesterday/Tomorrow** spans changed from inline `opacity:0.5` (which composited the lifted token back below 4.5:1) to a `.fp-masthead__strip-dim` class that uses `--text-muted` directly.
8. **`components.js` email-CTA template** changed `<h3>` to `<h2>` — fixes the page-wide heading-order violation (homepage went `h1` → `h3`).

## Guard tests

- `tests/test_site_a11y_landmarks.py` — six guard assertions that pin every fix above. If a future palette change drops `#708a7a` back to a 3.9:1 value, this test fails.

## Observatory audit (P2.3 finding — 2026-05-24)

The investment plan's premise that some observatory pages are stubs needing "Coming Soon" banners turned out to be outdated. Audit of `/sleep/`, `/glucose/`, `/training/`, `/nutrition/`, `/mind/`:

| Page         | Size  | Sections | API-backed | Status  |
|--------------|-------|----------|------------|---------|
| `/sleep/`    | 42 KB | 6        | yes        | shipping |
| `/glucose/`  | 38 KB | 4        | yes        | shipping |
| `/training/` | 46 KB | 6        | yes        | shipping |
| `/nutrition/`| 46 KB | 5        | yes        | shipping |
| `/mind/`     | 38 KB | 4        | yes        | shipping |

All five are in `deploy/restart_verify_rendered.py`'s 27-page audit set. Homepage cards have graceful em-dash fallbacks when data isn't ready (no "Coming Soon" or broken layout). No commit-or-hide decision was needed — they're already committed.

Real follow-up if Day-1 cards look too thin: change em-dash to "Awaiting Week 1" copy in `site/index.html` lines 767/774/781/788. Defer to first launch-day visit.

## Open items / known issues

- **Subscribe page CLS 0.151 (over 0.1 budget).** Likely from the `.subscribe-title` animation or layout shift as JS-loaded nav settles. Defer until after the site-api split (P1.1) — they'll likely converge on a fix together.
- **Other 18 site pages** weren't audited yet. Same `--c-text-muted` lift will help them automatically; skip-link + `<main>` are still missing.
- **Lighthouse-CI advisory in CI**: not wired yet. Pinning to a manual quarterly cadence for now — at single-operator pace, every-PR Lighthouse is more noise than signal.
