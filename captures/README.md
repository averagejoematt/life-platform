# DPR-1 Page Capture

Captures rendered screenshots + visible text from all 13 pages in the Deep Page Review scope.

## Setup (one time)

```bash
cd captures
npm install
npx playwright install chromium
```

## Run

```bash
node capture.mjs
```

Takes ~3-5 minutes. Captures all 13 pages at desktop (1440px) and mobile (390px) viewports.

## Output

```
captures/
  desktop/
    live.png              ← full-page screenshot
    live.txt              ← all visible text after JS hydration
    character.png
    character.txt
    habits.png
    habits.txt
    ... (13 pages)
  mobile/
    live.png
    live.txt
    ... (13 pages)
```

## What to share with Claude

1. **All .txt files** — paste or upload. This is the primary review input (what a visitor actually reads).
2. **Screenshots for specific pages** — upload PNGs when Claude needs to evaluate visual layout, chart rendering, or design quality.

The .txt files contain every visible string on the page *after* API data has loaded — numbers, coaching text, chart labels, navigation, everything. This is what the DPR-1 review evaluates.
