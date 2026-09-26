"""scripts/v7 — the per-page body templates of the nine v7 pages (#4182, plan D3).

Each module exposes `CSS` and `JS` (root-absolute asset paths — never under the base,
plan D4) and `body(base) -> str`, the inner HTML of `<main>`. `scripts/v7_build.py`
registers them in its `BODIES` table; a page with no module keeps the scaffold body.
"""
