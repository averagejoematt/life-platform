#!/usr/bin/env python3
"""portrait_variants_1114.py — art-direction-v2 CANDIDATE recipes for issue #1114 (ADR-106).

Matthew's complaint (verifier-corrected in #1114): the seeded sigil-ring frame reads as a
CLOCK (ring + tick marks, portraits.js seededFrame), and the 1.7px engraved stroke reads
as a MASK at 96px. Direction for this batch, verbatim: "real future-AI characters,
Pixar/cartoon energy, 3D feeling".

This script derives 3 variant candidates per coach from the SIGNED shipped recipes —
deterministically, so the round is reproducible (ADR-106 §4 provenance):

  v1_unframed  — no frame at all ("frame": [] — renders frameless via renderPortrait;
                 NOTE: shipping this shape needs a one-line schema amendment, the
                 validator currently requires layers be non-empty). Reduced interior
                 ink (neck line pair dropped) + the dimensional pass below.
  v2_openarc   — recipe-owned frame: ONE filled annular arc in the coach accent channel,
                 open at the crown so the head breaks the frame. Dial vocabulary without
                 clock geometry (no ticks, never a closed circle). + dimensional pass.
  v3_backdrop  — recipe-owned frame: a flat coach-tinted disc behind the bust (character-
                 poster chip; the `line` palette slot carries the tint). Dimensional pass
                 minus the hair sheen (the free slot is spent on the chip — a picked
                 combined direction would need a 7th tone slot, noted in the PR).

The dimensional pass ("Pixar energy, 3D feeling" WITHIN the flat-vector bible — layered
flat fills only, no gradients, photoreal stays NO-GO): a hair-sheen band (light source
upper-left, `line` slot), an under-fringe forehead shade + an under-jaw neck shade
(warm `blush` slot). Every added shape is a flat hex from the validated palette system.

Candidates land in config/portraits/candidates_1114/ — OUTSIDE the shipped glob
(`config/portraits/*.json`), unsigned (`_meta.sign_off` absent), so the ADR-106 gate is
structurally intact: nothing here can bundle, nothing ships. Only Matthew's pick, carried
through a follow-up PR with a recorded sign-off, ever will.

Usage:
    python3 scripts/portrait_variants_1114.py          # write candidates + validate
"""

import copy
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.v4_build_portraits import validate_recipe  # noqa: E402

RECIPE_DIR = os.path.join(ROOT, "config", "portraits")
OUT_DIR = os.path.join(RECIPE_DIR, "candidates_1114")

DATE = "2026-07-18"

# The validator requires non-empty layer lists; v1's "frame": [] is the ONE deliberate
# deviation (renderPortrait treats [] as "explicitly no frame" — the proposed amendment).
ALLOWED_ERRS = {"layer 'frame' must be a non-empty list"}


def r2(n):
    v = round(n, 2)
    return int(v) if v == int(v) else v


def pt(x, y):
    return f"{r2(x)},{r2(y)}"


def cubic_band(p0, c1, c2, p1, depth, inset=1.0):
    """A flat shading band: forward cubic p0→p1, then the same curve offset down by
    `depth` traversed back, endpoints inset toward each other so the band tapers."""
    sx = 1 if p1[0] >= p0[0] else -1
    q1 = (p1[0] - inset * sx, p1[1] + depth)
    q0 = (p0[0] + inset * sx, p0[1] + depth)
    return f"M{pt(*p0)} C{pt(*c1)} {pt(*c2)} {pt(*p1)} " f"L{pt(*q1)} C{pt(c2[0], c2[1] + depth)} {pt(c1[0], c1[1] + depth)} {pt(*q0)} Z"


def ring_arc(cx, cy, r_out, r_in, start_deg, end_deg):
    """Filled annular arc (donut segment), angles clockwise from +x, y-down."""

    def p(r, deg):
        a = math.radians(deg)
        return pt(cx + r * math.cos(a), cy + r * math.sin(a))

    large = 1 if (end_deg - start_deg) > 180 else 0
    return (
        f"M{p(r_out, start_deg)} A{r2(r_out)},{r2(r_out)} 0 {large},1 {p(r_out, end_deg)} "
        f"L{p(r_in, end_deg)} A{r2(r_in)},{r2(r_in)} 0 {large},0 {p(r_in, start_deg)} Z"
    )


def disc(cx, cy, r):
    return f"M{pt(cx - r, cy)} a{r2(r)},{r2(r)} 0 1,0 {r2(2 * r)},0 a{r2(r)},{r2(r)} 0 1,0 {r2(-2 * r)},0 Z"


# Per-coach art table. Curves are (p0, c1, c2, p1) cubics in recipe space (0 0 100 120):
#   sheen       — hair-sheen band along the crown (light upper-left) + depth
#   fringe      — under-fringe forehead shade band + depth
#   jaw         — under-jaw neck shade band + depth (None where the signed recipe
#                 already carries a blush neck shade)
#   drop_ink    — exact stroked `d` strings removed in every variant (the vertical
#                 neck ink pair — the heaviest "mask" contributor below the face)
#   sheen_hex   — lighter-of-the-hair-tone flat hex (`line` slot, v1/v2)
#   chip_hex    — the v3 backdrop tint (`line` slot, v3): coach channel desaturated
#                 to a mid value that reads on BOTH themes
ART = {
    "elena_voss": {
        "sheen": (((38.0, 20.0), (42.0, 15.6), (47.0, 14.2), (54.0, 14.4)), 3.4),
        "fringe": (((39.3, 33.8), (44.0, 30.5), (51.0, 29.5), (56.5, 27.0)), 3.0),
        "jaw": None,  # signed recipe already shades the neck in blush
        "drop_ink": [
            "M44.4,72.5 C44.7,79 44.1,85.5 43,91.2",
            "M56.1,71 C56,78 56.6,85 57.7,91.2",
        ],
        "sheen_hex": "#665f72",
        "chip_hex": "#8fa0b3",
    },
    "eli_marsh": {
        "sheen": (((41.5, 23.6), (47.0, 23.6), (53.0, 23.6), (58.5, 23.6)), 2.6),
        "fringe": (((42.6, 28.4), (46.0, 27.5), (54.0, 27.5), (57.4, 28.4)), 3.0),
        "jaw": (((44.5, 67.0), (47.0, 69.6), (53.0, 69.6), (55.5, 66.0)), 3.4),
        "drop_ink": [
            "M44.2,68 C44.4,74.5 44,81 43.1,87.3",
            "M55.7,67 C55.6,74 56.1,81 56.9,87.3",
        ],
        "sheen_hex": "#90929b",
        "chip_hex": "#56809a",
    },
    "sarah_chen": {
        "sheen": (((40.0, 21.2), (43.6, 18.8), (47.0, 18.0), (53.0, 18.2)), 3.2),
        "fringe": (((42.8, 28.1), (46.0, 27.0), (54.0, 27.0), (57.2, 28.1)), 3.0),
        "jaw": None,  # signed recipe already shades the neck in blush
        "drop_ink": [
            "M44.9,71 C45.1,76.5 44.7,81.5 43.8,86.3",
            "M55,69.5 C54.9,75.5 55.4,81 56.2,86.3",
        ],
        "sheen_hex": "#544a40",
        "chip_hex": "#3f9ecb",
    },
    "lisa_park": {
        "sheen": (((39.5, 22.5), (43.0, 20.2), (46.5, 19.4), (52.5, 19.6)), 3.2),
        "fringe": (((39.2, 32.9), (43.5, 30.5), (56.5, 30.5), (60.8, 32.9)), 3.2),
        "jaw": (((45.2, 70.0), (47.5, 72.4), (52.5, 72.4), (54.8, 69.0)), 3.2),
        "drop_ink": [
            "M44.8,70.5 C45,76.5 44.6,82 43.7,87.3",
            "M55.1,69.5 C55,76 55.5,82 56.3,87.3",
        ],
        "sheen_hex": "#584f61",
        "chip_hex": "#937fc4",
    },
}

# v2 open arc: sweeps OVER the crown (aura, not horseshoe — round-1 kill note); the
# 76° opening sits at the bottom, swallowed by the bust, so no closed circle ever shows.
ARC = ring_arc(50, 51, 42, 38.8, 128, 412)
# v3 backdrop chip: one flat disc, bust runs off its lower edge.
CHIP = disc(50, 49, 43)

VARIANTS = ("v1_unframed", "v2_openarc", "v3_backdrop")


def _strip_ink(recipe, drops):
    for elems in recipe["layers"].values():
        elems[:] = [el for el in elems if el.get("d") not in drops]


def _dimensional_pass(recipe, art, with_sheen):
    """Append the flat shading/sheen fills. Bands go right after the base fills of
    their layer (before the ink contours) so ink stays on top within the layer."""
    layers = recipe["layers"]

    def insert_after_fills(lid, el):
        elems = layers.get(lid)
        if not elems:
            return
        i = len([e for e in elems if e.get("tone") or e.get("filled")])
        elems.insert(i, el)

    if with_sheen:
        (curve, depth) = art["sheen"]
        insert_after_fills("hair", {"d": cubic_band(*curve, depth), "tone": "line"})
    (curve, depth) = art["fringe"]
    insert_after_fills("head", {"d": cubic_band(*curve, depth), "tone": "blush"})
    if art["jaw"]:
        (curve, depth) = art["jaw"]
        insert_after_fills("head", {"d": cubic_band(*curve, depth), "tone": "blush"})


def build_variant(base, variant):
    art = ART[base["persona_id"]]
    r = copy.deepcopy(base)
    r["version"] = base["version"] + 1
    r.pop("aliases", None)
    _strip_ink(r, set(art["drop_ink"]))

    if variant == "v1_unframed":
        r["layers"]["frame"] = []  # explicitly no frame (needs the schema amendment)
        r["palette"]["line"] = art["sheen_hex"]
        _dimensional_pass(r, art, with_sheen=True)
    elif variant == "v2_openarc":
        r["layers"]["frame"] = [{"d": ARC, "tone": "accent"}]
        r["palette"]["line"] = art["sheen_hex"]
        _dimensional_pass(r, art, with_sheen=True)
    elif variant == "v3_backdrop":
        r["layers"]["frame"] = [{"d": CHIP, "tone": "line"}]
        r["palette"]["line"] = art["chip_hex"]
        _dimensional_pass(r, art, with_sheen=False)
    else:
        raise ValueError(variant)

    r["_meta"] = {
        "source": "hand-drawn",
        "prompt": (
            f"#1114 art-direction-v2 CANDIDATE ({variant}) — deterministically derived from the "
            f"signed v{base['version']} recipe by scripts/portrait_variants_1114.py; direction: "
            '"real future-AI characters, Pixar/cartoon energy, 3D feeling" (flat-vector bible intact)'
        ),
        "date": DATE,
        "traced_by": "claude-fable-5 — candidate round, ADR-106 gate pending (NO sign_off: cannot bundle, cannot ship)",
    }
    return r


def build_all():
    out = {}
    for pid in ART:
        with open(os.path.join(RECIPE_DIR, f"{pid}.json")) as f:
            base = json.load(f)
        for variant in VARIANTS:
            out[f"{pid}__{variant}"] = build_variant(base, variant)
    return out


def main():
    candidates = build_all()
    os.makedirs(OUT_DIR, exist_ok=True)
    bad = 0
    for key, recipe in sorted(candidates.items()):
        errs = [e for e in validate_recipe(recipe) if e not in ALLOWED_ERRS]
        if errs:
            bad += 1
            print(f"❌ {key}:\n  - " + "\n  - ".join(errs))
        path = os.path.join(OUT_DIR, f"{key}.json")
        with open(path, "w") as f:
            json.dump(recipe, f, indent=1, ensure_ascii=True)
            f.write("\n")
        signed = "SIGNED?!" if (recipe.get("_meta") or {}).get("sign_off") else "unsigned"
        print(f"✅ {key} → {os.path.relpath(path, ROOT)} ({signed})")
    if bad:
        return 1
    print(f"\n{len(candidates)} candidates written — all unsigned, none bundleable (ADR-106 gate intact).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
