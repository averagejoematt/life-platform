"""tests/test_recap_render_3744.py — the portrait card, and the cards it must not disturb.

WHY A PORTRAIT FORMAT EXISTS AT ALL

#1632 declined Instagram in July and priced the real cost honestly: the 13 daily OG cards
are 1200×630 link-unfurl previews, and on a grid they render "letterboxed and thin". That
decline was about AUTO-POSTING (Meta App Review, a Business account, a linked Page). This
is not that — the card is delivered privately and the owner posts it by hand, which is the
"human selection only" posture ADR-140 rule 5 already requires. So the cost #1632 named is
the work, and this is it.

THE RISK THIS FILE EXISTS FOR

Adding a second format to a shared engine is how two engines start. The mitigation is that
`card_engine` gained one optional `size=` argument on its three size-dependent primitives
and nothing else moved — so the 13 live cards must render EXACTLY as before. That is not a
claim to make in a commit message; it is a hash.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

pytest.importorskip("PIL")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from content.recap_data import DayFacts, WorkoutFact  # noqa: E402
from web import (
    card_engine as ce,  # noqa: E402
    recap_canvas as rc,  # noqa: E402
    recap_templates as rt,  # noqa: E402
)


def _facts(**over) -> DayFacts:
    base = dict(
        date="2026-09-13",
        day_n=8,
        weight_lb=319.7,
        week_ago_weight_lb=322.0,
        weekly_rate_lb=-2.3,
        rate_ci=(-3.0, -1.5),
        rate_provisional=False,
        workouts=[WorkoutFact("Legs", 4, 18, 12000.0, "Squat (Barbell)")],
        tier0_done=8,
        tier0_total=8,
        tier0_pct=100.0,
        tier0_streak=4,
        protein_g=182,
        protein_target_g=180,
        calories=2100,
        journal_templates=["Evening"],
    )
    base.update(over)
    return DayFacts(**base)


def _render(facts, trailing=None):
    picked = rt.pick(facts, trailing or [])
    copies = [rt.copy_for(n, facts) for n in picked]
    return rc.render_card(copies, day_label=f"Day {facts.day_n}", date_label="Sat 13 Sep", footer_left="the measured life")


# ── The existing cards must be untouched ──────────────────────────────────────
def test_the_unfurl_canvas_is_byte_identical_after_the_size_argument():
    """A golden hash, not a promise. 13 live cards depend on this default path."""
    img, _draw = ce.base_canvas()
    assert img.size == (1200, 630)
    digest = hashlib.sha256(img.tobytes()).hexdigest()

    explicit, _d2 = ce.base_canvas(size=(ce.W, ce.H), margin=ce.MARGIN)
    assert (
        hashlib.sha256(explicit.tobytes()).hexdigest() == digest
    ), "passing the defaults explicitly produced a different canvas — the parameterisation is not transparent"


def test_the_module_constants_still_describe_the_unfurl_card():
    assert (ce.W, ce.H) == (1200, 630)
    assert ce.MARGIN == 48


# ── The portrait card ─────────────────────────────────────────────────────────
def test_the_card_is_instagram_portrait():
    assert rc.PORTRAIT == (1080, 1350)
    assert _render(_facts()).size == (1080, 1350)


def test_a_single_template_day_still_produces_a_full_card():
    facts = _facts(
        weight_lb=None,
        week_ago_weight_lb=None,
        weekly_rate_lb=None,
        tier0_done=None,
        tier0_total=None,
        tier0_pct=None,
        protein_g=None,
        journal_templates=[],
    )
    assert rt.pick(facts, []) == ["workout"]
    assert _render(facts).size == (1080, 1350)


def test_a_day_with_nothing_to_say_is_refused_rather_than_drawn_empty():
    """The picker returns no card; the renderer must not invent one."""
    empty = DayFacts(date="2026-09-13", absent=["computed_metrics", "habit_scores", "hevy", "strava", "macrofactor", "notion"])
    assert rt.pick(empty, []) == []
    with pytest.raises(ValueError):
        rc.render_card([])


def test_the_card_carries_the_brand_mark():
    """#1640 put the dial on every card family. A new family inherits it or it is not one."""
    img = _render(_facts())
    # The mark sits top-right; its ember graduation is the only warm pixel up there.
    corner = img.crop((img.width - 160, 0, img.width, 120))
    assert any(r > g and r > 120 for r, g, _b in corner.getdata()), "no brand mark in the top-right corner"


def test_two_templates_do_not_overlap_however_tall_the_hero_ran():
    """A long hero pushes the band down rather than colliding with it."""
    long_hero = _facts(workouts=[WorkoutFact("A Very Long Session Title Indeed", 9, 40, 30000.0, "Deadlift (Barbell)")])
    copies = [rt.copy_for("workout", long_hero), rt.copy_for("habits", long_hero)]
    assert rc.render_card(copies, day_label="Day 8").size == (1080, 1350)


# ── Direction colour is derived, never chosen ─────────────────────────────────
def _label_pixels(img, y0=None):
    """The label row's dominant non-background colour."""
    band = img.crop((72, y0 or 560, 700, (y0 or 560) + 200))
    seen = {}
    for px in band.getdata():
        if sum(px) > 120:  # not the near-black ground
            seen[px] = seen.get(px, 0) + 1
    return sorted(seen.items(), key=lambda kv: -kv[1])


def test_a_loss_is_green_and_a_gain_is_amber_not_green():
    """#3285 shipped a weight GAIN in success green under the caption 'LOST'.

    The card cannot re-make that mistake by construction — the colour comes from
    `classify_delta`'s verdict — but this asserts the wiring, because "by construction"
    is exactly what was believed last time.
    """
    lost = _render(_facts(tier0_done=None, tier0_total=None, tier0_pct=None, protein_g=None, journal_templates=[], workouts=[]))
    gained = _render(
        _facts(
            weight_lb=323.0,
            week_ago_weight_lb=322.0,
            weekly_rate_lb=1.0,
            tier0_done=None,
            tier0_total=None,
            tier0_pct=None,
            protein_g=None,
            journal_templates=[],
            workouts=[],
        )
    )
    assert ce.GREEN in [c for c, _n in _label_pixels(lost)], "a loss did not render in the earned green"
    gained_colours = [c for c, _n in _label_pixels(gained)]
    assert ce.AMBER in gained_colours, "a gain did not render in the honest-miss amber"
    assert ce.GREEN not in gained_colours, "a GAIN rendered in success green — the #3285 defect, on a permanent surface"


# ── Output ────────────────────────────────────────────────────────────────────
def test_png_bytes_are_a_real_png():
    data = rc.to_png_bytes(_render(_facts()))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 5_000


def test_the_card_is_small_enough_to_send():
    """Telegram's sendPhoto caps at 10 MB; an SES message at 40 MB with encoding overhead."""
    assert len(rc.to_png_bytes(_render(_facts()))) < 2_000_000


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
