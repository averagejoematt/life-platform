"""#3285 — the home OG share card must name the DIRECTION of travel truthfully.

The live `og-home.png` drew the signed `journey.lost_lbs` under a hardcoded "LOST"
caption in `card_engine.GREEN`. The number was honest; the FRAME was not — the day the
delta went the wrong way, the platform's most-distributed artifact published a gain as
"-5 lbs LOST" in the success colour, on every link unfurl on every channel. Same defect
in words on the home `og:description`, which additionally led with the cycle START
weight where a reader scans for "now".

What this file pins, and why each part exists:

  * `classify_delta` is the ONE ruling (`lambdas/web/journey_direction.py`). Its tests
    run with no Pillow so the sign logic is guarded even on a PIL-less runner.
  * The card tests RENDER and read pixels back. A fixture that asserts the mapping table
    alone would pass while `build_home` ignored it (the #2703 class: a test on real code
    the running path never reaches), so the tile colour is sampled out of the drawn
    image the same way the live PNG was sampled when this was filed.
  * The two signs are asserted to DIFFER in caption AND in sampled RGB. A card test that
    cannot fail on a sign flip is not the test.
"""

import io
import os
import re
import sys

import pytest

os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

from web.journey_direction import DOWN, EVEN, UNKNOWN, UP, classify_delta  # noqa: E402

# ── The ruling (stdlib only — no Pillow, always runs) ────────────────────────────


def test_classify_delta_rules_each_sign():
    assert classify_delta(8.0) == (DOWN, 8.0)
    assert classify_delta(-5.2) == (UP, 5.0)
    assert classify_delta(0) == (EVEN, 0.0)


def test_magnitude_is_never_negative():
    """The card draws this straight into the tile. A negative here is the double
    negative the issue is about, one `_fmt` call later."""
    for v in (-0.0, -0.4, -5.2, -100, 0, 3, 41.9):
        _, magnitude = classify_delta(v)
        assert magnitude is None or magnitude >= 0, v


def test_absent_or_unreadable_never_gets_a_direction():
    """ADR-104: absence is an answer. Guessing a direction because nothing came back
    is exactly how a gain ends up captioned LOST."""
    for v in (None, "", "5", [], {}, float("nan"), float("inf"), True, False):
        assert classify_delta(v) == (UNKNOWN, None), v


def test_sub_display_delta_rules_even_not_up():
    """-0.4 lb renders as "0" at whole-pound precision. If the sign were read off the
    RAW value the tile would say "GAINED 0 lbs" — caption and number disagreeing, which
    is the property this fix exists to guarantee. Rounding happens before the sign test."""
    assert classify_delta(-0.4) == (EVEN, 0.0)
    assert classify_delta(0.4) == (EVEN, 0.0)
    assert classify_delta(-0.4, decimals=1) == (UP, 0.4)  # ...and the precision is the caller's


# ── The card: caption + colour, sampled out of a real render ────────────────────

_TILE_BOX = (40, 250, 320, 340)  # the first metric tile, drawn at (48, 260)


def _og():
    pytest.importorskip("PIL")
    from web import og_image_lambda

    return og_image_lambda


def _stats(lost):
    return {
        "journey": {"lost_lbs": lost},
        "vitals": {"hrv_ms": 41},
        "platform": {"days_in": 11, "tier0_streak": 3},
    }


def _tile_counts(img, tokens):
    """Exact-token pixel counts inside the delta tile — the live-PNG sampling method."""
    px = img.convert("RGB").load()
    x0, y0, x1, y1 = _TILE_BOX
    counts = dict.fromkeys(tokens, 0)
    for y in range(y0, y1):
        for x in range(x0, x1):
            p = px[x, y]
            for name, rgb in tokens.items():
                if p == rgb:
                    counts[name] += 1
    return counts


def _tile_bytes(img):
    return img.crop(_TILE_BOX).tobytes()


def _png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_gain_renders_amber_and_loss_renders_green():
    """The acceptance test. Render both signs, sample the tile, and require the colours
    to differ — a gain carries ZERO pixels of the success colour."""
    og = _og()
    from web import card_engine

    tokens = {"GREEN": card_engine.GREEN, "AMBER": card_engine.AMBER}

    loss = _tile_counts(og.build_home(_stats(8.0)), tokens)
    gain = _tile_counts(og.build_home(_stats(-5.2)), tokens)

    assert loss["GREEN"] > 0 and loss["AMBER"] == 0, loss
    assert gain["AMBER"] > 0 and gain["GREEN"] == 0, gain
    assert loss != gain


def test_the_two_signs_render_visibly_different_tiles():
    """Belt and braces on the sampler: the drawn pixels themselves must differ, so a
    change that neutralised the colour mapping without changing the caption still reds."""
    og = _og()
    assert _tile_bytes(og.build_home(_stats(8.0))) != _tile_bytes(og.build_home(_stats(-5.2)))
    assert _png(og.build_home(_stats(0.0))) != _png(og.build_home(_stats(-5.2)))


def test_build_home_passes_a_signed_free_value_and_a_directional_caption():
    """Captures the exact (value, label, colour) triple `build_home` hands the engine —
    the argument list that carried the literals "LOST" and GREEN before this fix."""
    og = _og()
    from web import card_engine

    seen = []
    original = og._draw_metric
    try:
        og._draw_metric = lambda draw, x, y, value, label, color=card_engine.TEXT: seen.append((x, value, label, color))
        og.build_home(_stats(-5.2))
        og.build_home(_stats(8.0))
        og.build_home(_stats(0.0))
        og.build_home(_stats(None))
    finally:
        og._draw_metric = original

    delta_tiles = [t for t in seen if t[0] == 48]
    assert len(delta_tiles) == 4
    gain, loss, even, absent = delta_tiles

    assert (gain[2], gain[3]) == ("GAINED", card_engine.AMBER)
    assert (loss[2], loss[3]) == ("LOST", card_engine.GREEN)
    assert (even[2], even[3]) == ("NET CHANGE", card_engine.TEXT)
    assert (absent[2], absent[3]) == ("NET CHANGE", card_engine.TEXT)

    # Honest at zero and at absence: neither claims a direction, and neither wears GREEN.
    assert even[1] == "0 lbs"
    assert absent[1] == "—"  # card_engine.fmt renders an absent value as an em-dash, suffix dropped
    for _x, value, _label, colour in delta_tiles:
        assert not str(value).startswith("-"), f"double negative back on the card: {value!r}"
        assert colour != card_engine.GREEN or _label == "LOST"


def test_the_caption_and_the_colour_are_never_hardcoded_together_again():
    """The mapping table itself: GREEN is reserved for movement toward the goal, AMBER is
    the repo's existing honest-miss accent (card_engine:42, #405/#551), and the two are
    distinct colours (a table that mapped both directions to one token would satisfy every
    other assertion here)."""
    og = _og()
    from web import card_engine

    assert card_engine.AMBER != card_engine.GREEN
    assert set(og._DELTA_TILE) == {DOWN, UP, EVEN, UNKNOWN}
    assert og._DELTA_TILE[UP][1] == card_engine.AMBER
    assert og._DELTA_TILE[DOWN][1] == card_engine.GREEN
    assert og._DELTA_TILE[UP][0] != og._DELTA_TILE[DOWN][0]
    assert card_engine.GREEN not in {og._DELTA_TILE[d][1] for d in (UP, EVEN, UNKNOWN)}


# ── The home og:description + the no-JS proof sentence ──────────────────────────


def _journey(lost, current):
    return {
        "start_weight": 321.0,
        "goal_weight": 185.0,
        "current_weight": current,
        "lost_lbs": lost,
        "day_n": 11,
        "as_of": "2026-08-27",
    }


def _desc(lost, current):
    import v4_proof

    return v4_proof.home_og(_journey(lost, current), {})[("property", "og:description")]


def test_og_description_states_direction_in_words_under_both_signs():
    gain = _desc(-5.2, 326.2)
    loss = _desc(8.0, 313.0)
    assert "5 lb up." in gain and "down" not in gain
    assert "8 lb down." in loss and " up." not in loss
    assert gain != loss


def test_og_description_never_publishes_a_double_negative():
    """No signed number may reach the sentence — the direction is a word, so a minus
    sign in front of a weight is unreachable by construction. (The `As of YYYY-MM-DD`
    stamp carries hyphens, so the check is scoped to a sign immediately before a lb
    figure rather than to the whole string.)"""
    for lost, current in ((-5.2, 326.2), (-0.4, 321.4), (0.0, 321.0), (8.0, 313.0), (None, None)):
        d = _desc(lost, current)
        assert not re.search(r"-\s*\d+(\.\d+)?\s*lb", d), d
        assert "down" not in d or (isinstance(lost, (int, float)) and lost > 0), d


def test_og_description_leads_with_the_CURRENT_weight_not_the_start():
    """The filed defect: "Day 11: 321 lb toward 185 lb" put the cycle START where a
    reader scans for "now" — 321 is where he began, and the payload carried the current
    weight unused."""
    d = _desc(-5.2, 326.2)
    assert d.startswith("Day 11: 326 lb now,"), d
    assert "321 lb start" in d  # the baseline is still stated, just not mislabelled as now


def test_og_description_is_honest_at_zero_and_when_absent():
    assert "no net change." in _desc(0.0, 321.0)
    assert "no net change." in _desc(-0.4, 321.4)  # sub-pound: even at display precision
    absent = _desc(None, None)
    assert "down" not in absent and " up." not in absent and "no net change" not in absent


def test_noscript_home_proof_uses_the_same_ruling():
    import v4_proof

    gain = v4_proof.home_block_html(_journey(-5.2, 326.2), {})
    loss = v4_proof.home_block_html(_journey(8.0, 313.0), {})
    assert "326 lb now, 5 lb up." in gain
    assert "313 lb now, 8 lb down." in loss
    assert "-5" not in gain
