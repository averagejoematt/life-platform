"""tests/test_fingerprint.py — #1379 the Daily Fingerprint.

AC1 (the load-bearing spine): the mark is a PURE function of date + real metrics with
ZERO randomness — identical inputs produce a BYTE-IDENTICAL SVG. These tests exercise
that directly (two calls, 100 calls, cross-process-stable seed, key-order invariance)
plus the honesty grammar (thin-n "warming up", earned glow only when earned, down != red).
"""

import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB = os.path.join(_ROOT, "lambdas", "web")
if _WEB not in sys.path:
    sys.path.insert(0, _WEB)

import fingerprint as fp  # noqa: E402

# A representative "good day" and a representative "thin day".
GOOD = {"recovery": 72, "sleep_hours": 7.8, "steps": 11200, "streak": 14, "hrv": 96, "strain": 12.4}
THIN = {"recovery": 41}


# ── AC1: byte-identical determinism ──────────────────────────────────────────────


def test_two_calls_are_byte_identical():
    a = fp.fingerprint_svg("2026-07-25", GOOD)
    b = fp.fingerprint_svg("2026-07-25", dict(GOOD))  # a DIFFERENT dict object, same values
    assert a == b
    assert isinstance(a, str) and a.startswith("<svg") and a.endswith("</svg>")


def test_zero_randomness_100_calls_collapse_to_one():
    outputs = {fp.fingerprint_svg("2026-07-25", GOOD) for _ in range(100)}
    assert len(outputs) == 1, "the mark is not deterministic — 100 identical calls diverged"


def test_metric_key_order_does_not_change_the_bytes():
    reordered = {k: GOOD[k] for k in reversed(list(GOOD))}
    assert fp.fingerprint_svg("2026-07-25", GOOD) == fp.fingerprint_svg("2026-07-25", reordered)


def test_int_vs_float_valued_metric_seeds_identically():
    assert fp.fingerprint_svg("2026-07-25", {"recovery": 62}) == fp.fingerprint_svg("2026-07-25", {"recovery": 62.0})


def test_absent_and_none_metric_seed_identically():
    assert fp.fingerprint_svg("2026-07-25", {"recovery": 62}) == fp.fingerprint_svg("2026-07-25", {"recovery": 62, "hrv": None})


def test_different_date_changes_the_mark():
    assert fp.fingerprint_svg("2026-07-25", GOOD) != fp.fingerprint_svg("2026-07-26", GOOD)


def test_different_metrics_change_the_mark():
    assert fp.fingerprint_svg("2026-07-25", GOOD) != fp.fingerprint_svg("2026-07-25", {**GOOD, "recovery": 30})


def test_determinism_survives_a_fresh_process_with_hash_randomization():
    """hash() is PYTHONHASHSEED-salted; a naive implementation that leaned on it would
    produce a DIFFERENT mark in a fresh interpreter. Prove the seed is stable across
    processes by generating the same mark in two subprocesses with hash randomization
    forced ON, and comparing to this process's output."""
    snippet = (
        "import sys; sys.path.insert(0, r'%s'); import fingerprint as fp; "
        "print(fp.fingerprint_svg('2026-07-25', {'recovery': 72, 'sleep_hours': 7.8, "
        "'steps': 11200, 'streak': 14, 'hrv': 96, 'strain': 12.4}))" % _WEB
    )
    env = {**os.environ, "PYTHONHASHSEED": "random"}
    outs = set()
    for _ in range(2):
        r = subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True, env=env, check=True)
        outs.add(r.stdout.strip())
    outs.add(fp.fingerprint_svg("2026-07-25", GOOD).strip())
    assert len(outs) == 1, "seed is not process-stable — likely leaning on hash()/random"


# ── honesty grammar (ADR-104) ────────────────────────────────────────────────────


def test_thin_data_is_warming_up_and_has_no_glow():
    mark = fp.build_mark("2026-07-25", THIN)
    assert mark["warming_up"] is True
    assert mark["glow"]["rings"] == [], "a warming-up day must not fabricate an earned glow"
    svg = fp.mark_to_svg(mark)
    assert "stroke-dasharray" in svg, "warming-up core should render as the staged (dashed) ring"


def test_earned_glow_appears_only_when_earned():
    strong = fp.build_mark("2026-07-25", {"recovery": 95, "sleep_hours": 8.2, "steps": 14000, "streak": 40, "hrv": 118})
    weak = fp.build_mark("2026-07-25", {"recovery": 20, "sleep_hours": 4.0, "steps": 1200, "streak": 0, "hrv": 40})
    assert strong["glow"]["rings"], "a genuinely strong day should earn a glow"
    assert weak["glow"]["rings"] == [], "a low day must not glow"


def test_down_is_not_red_no_warning_palette():
    """A low day is sparse, never alarm-coloured: the only colours are the ember
    (earned light), ink, and ink-faint tokens — no red/warning token anywhere."""
    svg = fp.fingerprint_svg("2026-07-25", {"recovery": 15, "sleep_hours": 3.5, "steps": 900})
    for banned in ("red", "crimson", "--danger", "--warn", "--error", "#f", "#F"):
        assert banned not in svg, f"low-day mark must not use a warning colour ({banned!r})"
    assert "var(--ember)" in svg or "var(--ink" in svg


def test_svg_uses_only_token_fills_no_new_deps():
    svg = fp.fingerprint_svg("2026-07-25", GOOD)
    # every fill/stroke colour is a token var (or 'none'); no hard-coded hex
    assert "#" not in svg, "the mark must use tokens.css vars, never hard-coded colour"
    assert "var(--" in svg


def test_size_only_changes_width_height_not_geometry():
    small = fp.fingerprint_svg("2026-07-25", GOOD, size=40)
    big = fp.fingerprint_svg("2026-07-25", GOOD, size=200)
    assert small != big
    # the internal geometry (viewBox + coords) is identical; only width/height differ
    assert small.replace('width="40" height="40"', "X") == big.replace('width="200" height="200"', "X")
