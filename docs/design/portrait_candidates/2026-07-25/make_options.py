#!/usr/bin/env python3
"""make_options.py — #1114 art-direction option round: frame + engraved-ink directions.

The verified complaint (issue #1114): at 96px the §8.7 seeded sigil-ring frame (full
circle + radial measuring ticks) reads as a CLOCK, and the uniform 1.7px engraved
stroke treatment reads as a MASK. This generator produces the candidate recipes for
the rendered option rounds (ADR-106: AI may sketch, only code ships, only Matthew
approves).

Each option is a coherent (frame composition x ink treatment) direction:

  A "unframed, weighted ink"  — no frame at any size; two-weight ink hierarchy
                                 (silhouette heavier than facial features).
  B "open arc"                — one 235-degree arc, seeded gap in the upper region so it
                                 can never close into a dial; a single coach-accent dot
                                 at the arc's trailing end (sigil vocabulary, no ticks).
  C "arch niche"              — an open-bottom engraved arch (round top, straight sides
                                 running off the bottom edge — the classic portrait-niche
                                 cartouche) with one seeded coach-accent dot at a side
                                 terminus (nothing radial, nothing closed).
  D "quiet ring"              — the minimal-delta direction: the same circle, ticks
                                 deleted, hairline weight, frame opacity dropped.

Frame geometry is emitted as an explicit, schema-valid `frame` layer in a candidate
recipe derived from the SIGNED shipped recipe (config/portraits/<pid>.json), so the
real renderer (site/assets/js/portraits.js renderPortrait) draws every option — the
geometry authority never forks. Ink weights cannot be expressed in recipe data today
(portraits.js fixes stroke-width 1.7); each option's weights are recorded in
`_meta.option.ink` and applied by the sheet as a post-render attribute transform —
exactly the renderer change the chosen direction would ship after Matthew's gate.

Candidates are UNSIGNED (no `_meta.sign_off`) — the bundler can never ship them.
Deterministic: same inputs, byte-identical candidate JSON.

Usage:
    python3 docs/design/portrait_candidates/2026-07-25/make_options.py            # sheet trio
    python3 docs/design/portrait_candidates/2026-07-25/make_options.py --cast full  # all shipped recipes (post-approval regen helper)
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

from scripts.v4_build_portraits import load_recipes, validate_recipe  # noqa: E402

DATE = "2026-07-25"
# The review trio: the lead (oblong base), the circle base, and the one bald+glasses
# construction — maximum shape-language spread for judging a frame direction.
TRIO = ("elena_voss", "lisa_park", "james_okafor")

C, CY = 50.0, 46.0  # head centre (renderer contract — seededFrame uses the same)


def fnv1a(s):
    """FNV-1a over the persona id — the same seed family sigils.js/portraits.js use."""
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def mulberry32(a):
    """Python mirror of sigils.js mulberry32 (copied from web/portrait_raster.py)."""
    state = a & 0xFFFFFFFF

    def rnd():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return rnd


def r2(n):
    v = round(n * 100) / 100
    return int(v) if v == int(v) else v


def _pt(r, a_deg, cx=C, cy=CY):
    a = math.radians(a_deg)
    return r2(cx + r * math.cos(a)), r2(cy + r * math.sin(a))


def _dot(cx, cy, r):
    """A filled circle as a two-arc path (recipe elements are path strings only)."""
    return f"M{r2(cx - r)},{r2(cy)} A{r},{r} 0 1 0 {r2(cx + r)},{r2(cy)} A{r},{r} 0 1 0 {r2(cx - r)},{r2(cy)} Z"


# ── frame generators (each returns a schema-valid `frame` element list) ──────────


def frame_open_arc(seed):
    """Option B: one 235-degree arc, seeded gap centred in the upper region
    (-110..-50 deg, screen coords: -90 is straight up), so the opening always breaks
    the dial read. A single coach-accent dot sits on the trailing end.
    Round 2: dot r 1.9 → 2.6 (1.9 viewBox units ≈ 1.8px at 96 — sub-visible in the
    round-1 renders); gap band tightened 70° → 60° so neither arc end can fall
    near-horizontal into the face."""
    rnd = mulberry32(seed)
    R = 42.0
    sweep = 235.0
    gap_centre = -110.0 + rnd() * 60.0
    a0 = gap_centre + (360.0 - sweep) / 2.0  # arc start (clockwise from the gap edge)
    a1 = a0 + sweep
    x0, y0 = _pt(R, a0)
    x1, y1 = _pt(R, a1)
    dx, dy = _pt(R, a1)  # accent dot rides the trailing end
    return [
        {"d": f"M{x0},{y0} A{R},{R} 0 1 1 {x1},{y1}"},
        {"d": _dot(dx, dy, 2.6), "tone": "accent"},
    ]


def frame_arch(seed):
    """Option C (round 2 — was a closed rounded-rect plate, which read as a
    phone/photo-booth frame and double-framed the lead card): an OPEN-BOTTOM engraved
    arch niche — semicircular top, straight sides running off the bottom edge, the
    classic portrait-cartouche idiom. One seeded coach-accent dot at a side terminus
    (seeded left/right), nothing radial, nothing closed."""
    rnd = mulberry32(seed)
    x1, x2, top = 16.0, 84.0, 40.0
    r = (x2 - x1) / 2.0  # 34 — the semicircular top
    y_end = 118.0  # runs off the bottom edge like the bust itself
    arch = f"M{x1},{y_end} L{x1},{top} A{r},{r} 0 0 1 {x2},{top} L{x2},{y_end}"
    side = x1 if rnd() < 0.5 else x2
    return [{"d": arch}, {"d": _dot(side, 108.0, 2.2), "tone": "accent"}]


def frame_quiet_ring(_seed):
    """Option D: the minimal-delta direction — the same circle, no ticks. Weight and
    opacity drop to hairline levels via the option's ink spec."""
    R = 41.0
    return [{"d": f"M{r2(C - R)},{CY} A{R},{R} 0 1 0 {r2(C + R)},{CY} A{R},{R} 0 1 0 {r2(C - R)},{CY} Z"}]


# ── the option table (frame generator + engraved-ink treatment spec) ─────────────
# ink weights are px (the renderer uses vector-effect: non-scaling-stroke, so these
# are literal on-screen widths at every size). `sil` = silhouette layers
# (head/hair/bust), `feat` = facial-feature layers (brow/eyes/glasses/nose/mouth).
OPTIONS = {
    "optA": {
        "name": "unframed, weighted ink",
        "frame": None,
        "ink": {"sil": 1.8, "feat": 1.05, "frame": None, "frame_opacity": None},
        "claim": "kills the clock by removal; the two-weight ink gives the face a drawn hierarchy so it stops reading as a die-cut mask",
    },
    "optB": {
        "name": "open arc",
        "frame": frame_open_arc,
        "ink": {"sil": 1.7, "feat": 1.3, "frame": 1.1, "frame_opacity": None},
        "claim": "keeps the instrument vocabulary as a single engraving flourish — an arc with a seeded upper gap can never close into a dial",
    },
    "optC": {
        "name": "arch niche",
        "frame": frame_arch,
        "ink": {"sil": 1.7, "feat": 1.25, "frame": 1.0, "frame_opacity": None},
        "claim": "the classic portrait-cartouche idiom: an open-bottom arch niche — nothing radial, nothing closed, so neither clock nor photo-frame can read",
    },
    "optD": {
        "name": "quiet ring",
        "frame": frame_quiet_ring,
        "ink": {"sil": 1.7, "feat": 1.25, "frame": 0.9, "frame_opacity": 0.22},
        "claim": "the minimal-delta fix: deleting the ticks deletes the clock; hairline weight + lower opacity demote the ring to atmosphere",
    },
}


def make_candidate(pid, recipe, opt_id):
    opt = OPTIONS[opt_id]
    cand = json.loads(json.dumps(recipe))  # deep copy
    seed = fnv1a(pid)
    if opt["frame"] is not None:
        cand["layers"]["frame"] = opt["frame"](seed)
    meta = dict(cand.get("_meta") or {})
    meta.pop("sign_off", None)  # candidates are UNSIGNED — the bundler can never ship them
    meta["date"] = DATE
    meta["traced_by"] = "claude-fable-5 — #1114 art-direction option round (frame layer generated by make_options.py; no raster step)"
    meta["derived_from"] = {
        "recipe": f"config/portraits/{pid}.json",
        "version": recipe.get("version"),
        "signed": ((recipe.get("_meta") or {}).get("sign_off") or {}).get("date", ""),
    }
    meta["option"] = {
        "id": opt_id,
        "name": opt["name"],
        "issue": 1114,
        "ink": opt["ink"],
        "frame": (
            "none — the chosen renderer change would stop composing a frame at any size"
            if opt["frame"] is None
            else "explicit `frame` layer above (seeded per coach, deterministic)"
        ),
        "claim": opt["claim"],
    }
    cand["_meta"] = meta
    return cand


def main():
    cast = TRIO
    if "--cast" in sys.argv and sys.argv[sys.argv.index("--cast") + 1] == "full":
        cast = None
    recipes = load_recipes()
    pids = sorted(recipes) if cast is None else [p for p in cast if p in recipes]
    wrote = 0
    for pid in pids:
        for opt_id in sorted(OPTIONS):
            cand = make_candidate(pid, recipes[pid], opt_id)
            errs = validate_recipe(cand)  # no filename check — the __opt suffix is the file's, not the persona's
            if errs:
                raise SystemExit(f"❌ {pid} {opt_id}: " + "; ".join(errs))
            out = os.path.join(HERE, f"{pid}__{opt_id}.json")
            with open(out, "w") as f:
                json.dump(cand, f, indent=1, ensure_ascii=True, sort_keys=True)
                f.write("\n")
            wrote += 1
    print(f"✅ {wrote} candidate recipe(s) → {os.path.relpath(HERE, ROOT)} (all schema-valid, all unsigned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
