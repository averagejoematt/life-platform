"""fingerprint.py — #1379: the Daily Fingerprint (the deterministic mark of a day).

A PURE, deterministic function of one day's real metrics → an inline-SVG mark.
**Zero randomness**: identical inputs produce a BYTE-IDENTICAL SVG string — the
load-bearing invariant proved in tests/test_fingerprint.py. The seed is a SHA-256
of the date plus the day's *normalized* metrics; a tiny deterministic PRNG
(splitmix64, NOT the `random` module and NOT hash() — which is salted per-process)
drives the aesthetic scatter, while the *earned* qualities — the glow radius, the
lit nodes — are a DIRECT function of the real metric values. So the glow can only
be earned by real numbers; it structurally cannot be faked
(DESIGN_SYSTEM_V5 §8, "earned glow / no gloss").

Honesty grammar (ADR-104): thin data — fewer than THIN_N present metrics — renders a
sparse, calm "warming up" mark: dormant nodes, no glow, never a fabricated dense
field. A genuinely low day is sparse but never alarm-red ("down != red"): the palette
never turns to a warning colour, it just withholds the ember.

The geometry is emitted once as role-tagged primitives (`build_mark`) so BOTH
renderers draw the same mark from one source of truth:
  • `mark_to_svg` — inline SVG, fills via `var(--token)` (tokens.css only, no new deps).
  • the OG PNG (lambdas/web/og_image_lambda.build_fingerprint) — Pillow, literal token RGB.

Stdlib only (hashlib). No boto3, no Pillow import here — this module is imported by
both the site-api bundle and the OG bundle, so it must stay dependency-free.
"""

import hashlib
import math

# ── Tunables (documented on /method/fingerprint/ and DESIGN_SYSTEM_V5 §8) ──────
THIN_N = 3  # < THIN_N present metrics ⇒ "warming up" (honest low-n degrade)
GLOW_FLOOR = 0.50  # earned_score below this ⇒ no glow (glow is earned, never given)
LIT_FLOOR = 0.55  # a single node lights (ember) only above this normalized value

# The "good day" metrics, in a FIXED order (node placement is order-stable). Each maps
# a raw value to [0,1] via a soft, documented ceiling — the metric→visual contract.
# down != red: these only ever ADD light; a low value simply contributes little.
_GOOD = [
    ("recovery", 100.0),  # Whoop recovery %      → v/100
    ("sleep_hours", 8.0),  # sleep duration hours   → v/8  (8h = full)
    ("steps", 12000.0),  # daily steps            → v/12000
    ("streak", 30.0),  # tier-0 streak (days)   → v/30
    ("hrv", 120.0),  # HRV ms                 → v/120
    ("strain", 21.0),  # Whoop strain           → v/21
]

_MASK64 = (1 << 64) - 1


def _fmt_num(v):
    """Canonical numeric token: 62, 62.0 and 62.00 all collapse to '62.0' so a
    caller's int-vs-float choice can never change the seed bytes."""
    return repr(round(float(v), 4))


def _canon(date_str, metrics):
    """The deterministic seed string: date + sorted, normalized metric pairs.
    Absent (None) metrics are dropped so a missing reading and an omitted key seed
    identically. Key order in the input dict is irrelevant (sorted here)."""
    parts = []
    for k in sorted(metrics):
        v = metrics[k]
        if v is None:
            continue
        try:
            tok = _fmt_num(v)
        except (TypeError, ValueError):
            tok = str(v)
        parts.append(f"{k}={tok}")
    return f"{str(date_str)}|" + ";".join(parts)


def _seed_int(date_str, metrics):
    digest = hashlib.sha256(_canon(date_str, metrics).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _splitmix(seed):
    """A deterministic, process-independent PRNG (splitmix64). Returns a callable
    yielding uniform floats in [0, 1). NOT random.* (unseeded/global) and NOT
    hash() (PYTHONHASHSEED-salted) — both would break byte-identity."""
    state = seed & _MASK64

    def nxt():
        nonlocal state
        state = (state + 0x9E3779B97F4A7C15) & _MASK64
        z = state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
        z = z ^ (z >> 31)
        return (z >> 11) / float(1 << 53)

    return nxt


def _norm(value, ceiling):
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value) / ceiling))
    except (TypeError, ValueError):
        return None


def build_mark(date_str, metrics):
    """Compute the deterministic primitive spec for a day's mark. Pure; identical
    args ⇒ identical dict. Coordinates live in a fixed 0–100 space (the SVG/PNG
    renderers scale it), rounded to 2 dp so both renderers are byte-stable.

    Returns a dict:
      earned_score float[0,1] · warming_up bool · n int (present good metrics) ·
      core_r · glow {rings:[{r,opacity}]} · nodes [{x,y,r,lit,value}] · rays [{x,y,lit}]
    """
    metrics = metrics or {}
    rnd = _splitmix(_seed_int(date_str, metrics))

    present = [(name, _norm(metrics.get(name), ceil)) for name, ceil in _GOOD]
    present = [(name, v) for name, v in present if v is not None]
    n = len(present)
    warming = n < THIN_N

    # earned_score: the mean of the present "good" values. Absent metrics do not
    # dilute it (you're graded on what was measured), but n < THIN_N still withholds
    # the glow below — thin evidence never earns a full bloom.
    earned = round(sum(v for _, v in present) / n, 4) if n else 0.0

    cx = cy = 50.0
    node_count = max(3, n)
    base_r = 30.0
    core_r = round(6.0 + 8.0 * earned, 2)

    nodes = []
    rays = []
    for i in range(node_count):
        # deterministic angle: even spokes + a bounded seeded jitter
        ang = (360.0 / node_count) * i + (rnd() - 0.5) * 22.0
        rad = base_r + (rnd() - 0.5) * 8.0
        x = round(cx + rad * math.cos(math.radians(ang)), 2)
        y = round(cy + rad * math.sin(math.radians(ang)), 2)
        val = present[i][1] if i < n else 0.0  # padding nodes are dormant (val 0)
        lit = (not warming) and val >= LIT_FLOOR
        nodes.append({"x": x, "y": y, "r": round(2.0 + 4.0 * val, 2), "lit": lit, "value": round(val, 4)})
        rays.append({"x": x, "y": y, "lit": lit})

    # Earned glow: concentric ember halos, present ONLY when the day earned it.
    rings = []
    if (not warming) and earned >= GLOW_FLOOR:
        n_rings = 2 + int(round(earned))  # 2 at the floor, 3 near a perfect day
        for k in range(1, n_rings + 1):
            r = round(core_r + 6.0 * k + 4.0 * earned, 2)
            opacity = round(max(0.04, (0.22 - 0.05 * k) * earned), 3)
            rings.append({"r": r, "opacity": opacity})

    return {
        "date": str(date_str),
        "earned_score": earned,
        "warming_up": warming,
        "n": n,
        "center": [cx, cy],
        "core_r": core_r,
        "glow": {"rings": rings},
        "nodes": nodes,
        "rays": rays,
    }


def _n2(x):
    """Fixed 2-dp formatting — the single source of numeric formatting in the SVG so
    the string bytes never depend on Python's float repr."""
    return f"{x:.2f}"


def mark_to_svg(mark, size=140):
    """Render a mark spec to an inline-SVG string. Fills use `var(--token)` — the
    ember for earned light, ink/ink-faint for structure — so the mark themes with
    the page and adds no colour outside tokens.css. Deterministic given `mark`
    and `size` (integer)."""
    cx, cy = mark["center"]
    parts = [
        f'<svg class="fingerprint" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
        f'width="{int(size)}" height="{int(size)}" role="img" '
        f'aria-label="Daily fingerprint for {mark["date"]}">',
        f'<title>Daily fingerprint — {mark["date"]}</title>',
    ]
    # 1. earned glow (drawn first, behind the structure)
    for ring in mark["glow"]["rings"]:
        parts.append(
            f'<circle cx="{_n2(cx)}" cy="{_n2(cy)}" r="{_n2(ring["r"])}" fill="none" '
            f'stroke="var(--ember)" stroke-width="1.4" opacity="{ring["opacity"]:.3f}"/>'
        )
    # 2. rays from core to each node
    for ray in mark["rays"]:
        colour = "var(--ember)" if ray["lit"] else "var(--ink-faint)"
        op = "0.85" if ray["lit"] else "0.35"
        parts.append(
            f'<line x1="{_n2(cx)}" y1="{_n2(cy)}" x2="{_n2(ray["x"])}" y2="{_n2(ray["y"])}" '
            f'stroke="{colour}" stroke-width="0.8" opacity="{op}"/>'
        )
    # 3. nodes
    for node in mark["nodes"]:
        colour = "var(--ember)" if node["lit"] else "var(--ink-faint)"
        op = "1" if node["lit"] else "0.5"
        parts.append(f'<circle cx="{_n2(node["x"])}" cy="{_n2(node["y"])}" r="{_n2(node["r"])}" fill="{colour}" opacity="{op}"/>')
    # 4. core (structure — ink; warming keeps it hollow so an empty day reads as staged)
    if mark["warming_up"]:
        parts.append(
            f'<circle cx="{_n2(cx)}" cy="{_n2(cy)}" r="{_n2(mark["core_r"])}" fill="none" '
            f'stroke="var(--ink-faint)" stroke-width="1.2" stroke-dasharray="2 2" opacity="0.7"/>'
        )
    else:
        parts.append(f'<circle cx="{_n2(cx)}" cy="{_n2(cy)}" r="{_n2(mark["core_r"])}" fill="var(--ink)" opacity="0.92"/>')
    parts.append("</svg>")
    return "".join(parts)


def fingerprint_svg(date_str, metrics, size=140):
    """The public entry point: a day's date + real metrics → a byte-identical SVG.

    >>> fingerprint_svg("2026-07-25", {"recovery": 62}) == fingerprint_svg("2026-07-25", {"recovery": 62})
    True
    """
    return mark_to_svg(build_mark(date_str, metrics), size=size)
