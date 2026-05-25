#!/usr/bin/env python3
"""
Prepend the v6.9.4 entry to docs/CHANGELOG.md.

Idempotent: if v6.9.4 is already in the file, no-op. Otherwise, prepend the
session entry above the v6.9.3 entry.

Run from project root:
    python3 deploy/changelog_v6_9_4.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "docs" / "CHANGELOG.md"

ENTRY = """## v6.9.4 — visual_qa v3.1 + character_stats 503→200 (2026-05-04 very late evening)

Parallel to Claude Code's v6.9.3 (IC-4 detectors). No file overlap.

`tests/visual_qa.py` was unrunnable end-to-end because the site is gated by cf-auth (cookie-based HMAC). Once auth + better detectors were sorted, visual_qa surfaced a real bug: `/api/character_stats` returns HTTP 503 on every homepage load. Fixed both.

### `tests/visual_qa.py` v3.0 → v3.1.0

Three substantive detector rewrites + one cosmetic.

- **Cycle-pause detection** — was matching only DOM markers (`.cycle-pause-band`, `.cycle-pause-overlay`), missed Chart.js plugin renders and raw-canvas pixel renders. Now walks `Chart.instances` for `options.plugins.cyclePause.dates`, treats "script loaded + chart data spans gap" as inferred-pass with warning, recognizes "data doesn't span gap" as correct-absent (warning, not failure). All 3 render flavors from `cycle-pause.js` now matched.
- **Empty-section detection** — was flagging every collapsed `<details>` body on observatory pages (V3 depth-section pattern). Now skips elements inside `<details>` without `[open]`.
- **Homepage timeout** — `networkidle` 15s → falls back to `domcontentloaded` (mirrors `captures/capture.mjs`). Reports fallback as warning, not failure.
- **Known-issue allowlist** — new `KNOWN_JS_ISSUES` dict + `_classify_js_errors()`. `calcOnsetAdherence` is the only entry; surfaces as warning with documented reason.
- **5xx URL logging** (added via `deploy/patch_visual_qa_log_5xx.py`) — Playwright `response` listener captures `status >= 500` with URL. Failing-resource line now includes which endpoint 503'd.

### `lambdas/site_api_lambda.py` — `handle_character_stats()` no 5xx for missing data

Before: `_error(503, "Character sheet not computed yet")`. After: `_ok({"computed": false, "character_stats": null, "pillars": null, "reason": "..."}, cache_seconds=300)`. Pattern matches the existing pre-experiment branch's zeroed return.

Why safe: homepage JS already wraps fetch in `try/catch`, checks `if (cs.level)` (falsy → vitals fallback chain), and primary character data comes from `public_stats.json`. The fix strictly improves on the prior behavior — no client changes needed.

Applied via `deploy/patch_character_stats_503_to_200.py` (idempotent anchor-replace). Deployed:

```
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py
```

Verified: `curl /api/character_stats` returns 200; visual_qa goes from 11/12 to 12/12.

### Final state

```
Visual QA: 12 passed, 0 failed, 3 warning(s) across 12 pages
```

The 3 warnings (Sleep `calcOnsetAdherence` known bug, Glucose/Nutrition cycle-pause correctly absent) are the desired output, not noise.

### Not in scope (deferred next session)

- Sleep `calcOnsetAdherence` real fix (~10 min) — the IIFE writes to a DOM id whose parent grid was wiped by the no-data branch. Tracked in visual_qa allowlist; non-blocking.
- ~15 other `_error(503, ...)` anti-patterns in site_api_lambda.py (lines 838, 997, 1725, 2390, 2519, 3726, 3758, 4059, 5072, 5700, 6252, 6303, 6423, 6468, 6835). Each needs case-by-case 404 vs 200-with-flag judgment; not safe to bulk-replace. Worth a single audit pass when next in this file.
- Actually computing `character_stats.json` on schedule — Lambda now degrades gracefully but no scheduled job writes the partition. Overlaps with Coach Intelligence build-out already queued.

---

"""

# Anchor: the v6.9.3 header — we prepend ABOVE this line.
ANCHOR = "## v6.9.3 — IC-4 failure-pattern detectors implemented (2026-05-03 late evening)"

# Idempotency marker
ALREADY_PATCHED_MARKER = "## v6.9.4 — visual_qa v3.1 + character_stats 503→200"


def main():
    if not TARGET.is_file():
        print(f"ERROR: {TARGET} not found")
        return 1

    src = TARGET.read_text()

    if ALREADY_PATCHED_MARKER in src:
        print("CHANGELOG already has v6.9.4 entry — no changes made.")
        return 0

    if ANCHOR not in src:
        print(f"ERROR: Anchor not found in {TARGET}.")
        print(f"       Looking for: {ANCHOR!r}")
        print(f"       The v6.9.3 entry may have been edited or removed.")
        return 2

    new_src = src.replace(ANCHOR, ENTRY + ANCHOR, 1)
    TARGET.write_text(new_src)
    print(f"Prepended v6.9.4 entry to {TARGET}")
    print(f"  ({len(src)} → {len(new_src)} chars; +{len(new_src) - len(src)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
