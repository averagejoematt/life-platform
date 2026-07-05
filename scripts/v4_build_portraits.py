#!/usr/bin/env python3
"""v4_build_portraits.py — validate coach-portrait recipes and bundle the signed ones (#586, ADR-106).

Recipes live in config/portraits/<persona_id>.json (the shipped artifact per ADR-106: a
code-drawn, layered-SVG recipe — never a raster). This script is both the schema authority
(validate_recipe is imported by tests/test_portrait_recipes.py) and the bundler that emits
site/assets/js/portrait_data.js, the generated ES module portraits.js imports. It rides the
site sync (deploy/sync_site_to_s3.sh) exactly like v4_build_data_sources.py, and the output
is deterministic — same recipes, byte-identical module — so the ADR-098 content hash only
moves when a recipe actually changes.

The gate that matters: a recipe without a recorded contact-sheet sign-off (_meta.sign_off,
the ADR-106 §3 human gate) VALIDATES but is NOT bundled — it cannot reach a live page. Test
fixtures and contact-sheet candidates render via portraits.js renderPortrait() directly.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPE_DIR = os.path.join(ROOT, "config", "portraits")
OUT_PATH = os.path.join(ROOT, "site", "assets", "js", "portrait_data.js")

VIEWBOX = "0 0 100 120"

# The fixed layer schema (ADR-106 / PORTRAIT_RUNBOOK §1). `head` is the one required layer.
LAYER_IDS = (
    "frame",
    "bust",
    "head",
    "hair",
    "brow",
    "eyes-open",
    "eyes-closed",
    "glasses",
    "nose",
    "mouth-rest",
    "mouth-a",
    "mouth-b",
    "hatch",
)

# Line budget (runbook §1): stroked elements only — pupils/filled dots are exempt.
MAX_STROKED = 48

# Colour tones (character-illustration style, #587 round 4): a filled element may carry
# `tone`, resolved to the recipe's `palette` hex via CSS custom props. Mirror of
# portraits.js TONES. `accent` falls back to the coach identity channel.
TONES = ("skin", "hair", "cloth", "accent", "blush", "line")

# SVG path data, conservatively: commands + numbers + separators. No refs, no scripts.
_PATH_RE = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE\s,.+-]+$")
_ID_RE = re.compile(r"^[a-z0-9_]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate_recipe(recipe, persona_id=None):
    """Return a list of problems (empty = valid). persona_id, when given, must match."""
    errs = []
    if not isinstance(recipe, dict):
        return ["recipe is not an object"]

    rid = recipe.get("persona_id")
    if not isinstance(rid, str) or not _ID_RE.match(rid or ""):
        errs.append("persona_id missing or not lowercase_snake")
    if persona_id and rid != persona_id:
        errs.append(f"persona_id {rid!r} != filename {persona_id!r}")

    if not isinstance(recipe.get("version"), int) or recipe["version"] < 1:
        errs.append("version must be an int >= 1")
    if recipe.get("viewBox") != VIEWBOX:
        errs.append(f"viewBox must be {VIEWBOX!r}")

    layers = recipe.get("layers")
    if not isinstance(layers, dict) or not layers:
        errs.append("layers must be a non-empty object")
        layers = {}
    unknown = sorted(set(layers) - set(LAYER_IDS))
    if unknown:
        errs.append(f"unknown layer ids: {unknown} (allowed: {list(LAYER_IDS)})")
    if "head" not in layers:
        errs.append("required layer missing: head")

    stroked = 0
    used_tones = set()
    for lid, elems in layers.items():
        if not isinstance(elems, list) or not elems:
            errs.append(f"layer {lid!r} must be a non-empty list")
            continue
        for i, el in enumerate(elems):
            if not isinstance(el, dict) or not isinstance(el.get("d"), str) or not el["d"].strip():
                errs.append(f"layer {lid!r}[{i}]: element needs a non-empty path string 'd'")
                continue
            if not _PATH_RE.match(el["d"]):
                errs.append(f"layer {lid!r}[{i}]: 'd' contains non-path characters")
            extra = set(el) - {"d", "filled", "tone"}
            if extra:
                errs.append(f"layer {lid!r}[{i}]: unknown keys {sorted(extra)}")
            tone = el.get("tone")
            if tone is not None:
                if tone not in TONES:
                    errs.append(f"layer {lid!r}[{i}]: unknown tone {tone!r} (allowed: {list(TONES)})")
                else:
                    used_tones.add(tone)
            elif not el.get("filled"):
                stroked += 1
    if stroked > MAX_STROKED:
        errs.append(f"line budget exceeded: {stroked} stroked elements > {MAX_STROKED} (runbook §1)")

    palette = recipe.get("palette")
    if palette is not None:
        if not isinstance(palette, dict):
            errs.append("palette must be an object of tone -> #rrggbb")
            palette = {}
        for k, v in palette.items():
            if k not in TONES:
                errs.append(f"palette: unknown tone {k!r} (allowed: {list(TONES)})")
            elif not isinstance(v, str) or not _HEX_RE.match(v):
                errs.append(f"palette.{k}: must be #rrggbb, got {v!r}")
    # every used tone must resolve — from the palette, or (accent only) the coach channel
    missing = used_tones - set(palette or {}) - {"accent"}
    if missing:
        errs.append(f"tones used without palette entries: {sorted(missing)}")

    meta = recipe.get("_meta")
    if not isinstance(meta, dict):
        errs.append("_meta block required (ADR-106 §4 provenance)")
        meta = {}
    for key in ("source", "date", "traced_by"):
        if not isinstance(meta.get(key), str) or not meta.get(key):
            errs.append(f"_meta.{key} required")
    if meta.get("date") and not _DATE_RE.match(meta["date"]):
        errs.append("_meta.date must be YYYY-MM-DD")
    if meta.get("source") and meta["source"] != "hand-drawn" and not meta.get("prompt"):
        errs.append("_meta.prompt required when source is a generation model")

    sign = meta.get("sign_off")
    if sign is not None:
        if not isinstance(sign, dict) or not all(isinstance(sign.get(k), str) and sign.get(k) for k in ("by", "date", "sheet")):
            errs.append("_meta.sign_off, when present, needs by/date/sheet strings")
        elif not _DATE_RE.match(sign["date"]):
            errs.append("_meta.sign_off.date must be YYYY-MM-DD")

    # aliases: the OTHER ids this persona travels under at runtime (the V2 engine uses
    # e.g. sleep_coach where the board doc says lisa_park). The bundler emits an alias
    # map so portrait() resolves either key.
    aliases = recipe.get("aliases")
    if aliases is not None:
        if not isinstance(aliases, list) or not all(isinstance(a, str) and _ID_RE.match(a) for a in aliases):
            errs.append("aliases must be a list of lowercase_snake ids")

    return errs


def is_signed(recipe):
    """Bundle gate (ADR-106 §3): only a recorded contact-sheet sign-off ships."""
    sign = (recipe.get("_meta") or {}).get("sign_off")
    return isinstance(sign, dict) and all(sign.get(k) for k in ("by", "date", "sheet"))


def load_recipes():
    """Load + validate every recipe in config/portraits/. Raises on any invalid recipe."""
    recipes = {}
    if not os.path.isdir(RECIPE_DIR):
        return recipes
    for fname in sorted(os.listdir(RECIPE_DIR)):
        if not fname.endswith(".json"):
            continue
        pid = fname[:-5]
        with open(os.path.join(RECIPE_DIR, fname)) as f:
            recipe = json.load(f)
        errs = validate_recipe(recipe, persona_id=pid)
        if errs:
            raise SystemExit(f"❌ config/portraits/{fname}:\n  - " + "\n  - ".join(errs))
        recipes[pid] = recipe
    return recipes


def build():
    """Return the generated portrait_data.js content (signed recipes only)."""
    recipes = load_recipes()
    signed = {pid: r for pid, r in recipes.items() if is_signed(r)}
    skipped = sorted(set(recipes) - set(signed))
    # Alias map: runtime id -> canonical persona_id. Collisions are a build error.
    aliases = {}
    for pid, r in sorted(signed.items()):
        for a in r.get("aliases") or []:
            if a in signed or aliases.get(a, pid) != pid:
                raise SystemExit(f"❌ alias collision: {a!r} (from {pid})")
            aliases[a] = pid
    payload = json.dumps(signed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    alias_payload = json.dumps(aliases, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    header = (
        "// GENERATED by scripts/v4_build_portraits.py — DO NOT EDIT (edit config/portraits/*.json).\n"
        "// Signed recipes only (ADR-106 §3): a portrait without a recorded contact-sheet\n"
        "// sign-off never reaches this bundle. Empty registry = every coach renders their sigil.\n"
    )
    return header + f"export const PORTRAITS = {payload};\nexport const ALIASES = {alias_payload};\n", skipped


def main():
    content, skipped = build()
    with open(OUT_PATH, "w") as f:
        f.write(content)
    n = content.count('"persona_id"')
    print(f"✅ portrait_data.js: {n} signed recipe(s) bundled → {os.path.relpath(OUT_PATH, ROOT)}")
    for pid in skipped:
        print(f"   ⏸  {pid}: valid but unsigned — not bundled (awaiting the contact-sheet gate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
