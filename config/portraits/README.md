# Coach portrait recipes (ADR-106 / DESIGN_SYSTEM_V5 §8.7)

One `<persona_id>.json` per commissioned coach — the code-drawn, layered-SVG recipe that IS
the shipped artifact (never a raster). Schema + line budget: `scripts/v4_build_portraits.py`
(`validate_recipe`); procedure + style bible: `docs/design/PORTRAIT_RUNBOOK.md`.

Two gates stand between a file here and a live page:

1. **Validation** — `tests/test_portrait_recipes.py` + the sync-time build both fail on any
   schema violation.
2. **The sign-off gate** — only recipes with `_meta.sign_off` (Matthew's recorded
   contact-sheet approval) are bundled into `site/assets/js/portrait_data.js`. A valid but
   unsigned recipe sits here inert; every coach without a signed recipe renders their sigil.

Regenerate the bundle after any change: `python3 scripts/v4_build_portraits.py`.
