"""tests/test_recap_weekly_ground_3741.py — the weekly card's own ground, and what it may not do.

THE COMPLAINT

The owner, scrolling his own profile: *"on instagram its really hard to differentiate the
day cards to the weekly cards."* He is right, and the reason is structural — the weekly
reckoning and the six dailies around it share a ground, a type scale and a hero shape, so
an Instagram grid thumbnail (a square crop at ~110px) has nothing left to tell them apart.

THE FIX, AND ITS ONE HARD RULE

The weekly gets its own ground. The panel that reviewed the candidates (2026-09-19,
the same six seats that graded the first set) ruled on the part that is not taste:

  **The weekly ground is result-neutral.** It marks a card TYPE — "this is the reckoning" —
  never a verdict on how the week went. In this palette green means EARNED and amber means
  an honest miss, so a green ground on a C-average week would borrow a signal the week did
  not earn, and the grade chips already carry the verdict honestly. The ground therefore has
  to be identical on a three-C week and a three-B week, and it has to sit outside the
  semantic vocabulary the accents already own.

So these tests pin four things: the weekly differs from the daily, the DAILIES are untouched,
the ground never varies with the week's result, and the engine default is byte-identical for
every other card family that shares `base_canvas`.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

# PIL is not in the deploy-critical lane's dependency set, and a module-scope import of
# web.recap_layouts (which reaches card_engine -> PIL) is a COLLECTION-time error there —
# which takes the whole lane, not one test. Same class as the repeated PyYAML lane errors.
pytest.importorskip("PIL")

from content.recap_data import DayFacts  # noqa: E402
from web import (  # noqa: E402
    card_engine as ce,
    recap_layouts as L,
)

GOOD_WEEK = ["B+", "A-", "B", "B+", "A-", "B", "B+"]
BAD_WEEK = ["C", "B-", "B-", "B-", "C-", "C-", "C-"]


def _facts(**over):
    base = dict(
        date="2026-09-12",
        day_n=7,
        weight_lb=319.7,
        weighed_today=True,
        baseline_weight_lb=327.34,
        goal_weight_lb=185.0,
        grade_letter="C-",
    )
    base.update(over)
    return DayFacts(**base)


def _weekly(grades, **kw):
    return L.reckoning(
        _facts(),
        week_n=1,
        date_label="week 1 · sun 6 sep – sat 12 sep",
        weight_series=[("2026-09-06", 327.3), ("2026-09-12", 319.7)],
        grade_series=grades,
        totals={"sessions": 6, "sets": 117, "weight_delta": -7.7, "habit_pct": 63},
        **kw,
    )


def _corner(img):
    """The ground, sampled where nothing is ever drawn: below the top accent, left margin."""
    return img.convert("RGB").getpixel((4, 60))


def test_the_weekly_does_not_share_the_daily_ground():
    """The whole point. If these two ever match again, the grid problem is back."""
    weekly = _corner(_weekly(BAD_WEEK))
    daily = _corner(L.scorecard(_facts(), date_label="Sat 12 Sep"))
    assert daily == ce.BG, "the DAILY ground moved — only the weekly was supposed to change"
    assert weekly != daily, "the weekly card is drawn on the daily ground; a grid thumbnail cannot tell them apart"
    assert weekly == L.WEEKLY_GROUND


def test_the_weekly_ground_is_result_neutral():
    """A ground that flexed with the week's result would read as a verdict — the panel's ruling.

    The grade chips carry the verdict. The ground carries the card type, and only that.
    """
    assert _corner(_weekly(GOOD_WEEK)) == _corner(_weekly(BAD_WEEK)), (
        "the weekly ground changed with the week's grades — it is editorialising a result " "the grade chips already report honestly"
    )


def test_the_weekly_ground_is_outside_the_semantic_accents():
    """Green means EARNED and amber means an honest MISS. A ground may mean neither.

    Nearest-accent by squared distance: if the ground sits closer to GREEN or AMBER than it
    does to the daily ground it replaces, it has started borrowing one of their meanings.
    """

    def d2(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b))

    g = L.WEEKLY_GROUND
    assert d2(g, ce.BG) < d2(g, ce.GREEN), "the weekly ground reads as the EARNED accent"
    assert d2(g, ce.BG) < d2(g, ce.AMBER), "the weekly ground reads as the MISS accent"


def test_every_other_card_family_is_byte_identical():
    """`base_canvas` is shared with og_image_lambda and every other card family (#1640).

    A default-argument regression here re-skins cards nobody asked to change, so the default
    is pinned to the exact historic pixels — ground AND the bottom bar derived from it.
    """
    img, _ = ce.base_canvas()
    assert img.getpixel((4, 60)) == ce.BG
    assert img.getpixel((4, img.size[1] - 5)) == (6, 10, 8), "the historic bottom bar moved"


def test_a_ground_never_reaches_the_type():
    """Only the background moves. If a ground argument could dim the text, it is a re-skin."""
    a, _ = ce.base_canvas(ground=(90, 20, 140))
    b, _ = ce.base_canvas()
    assert a.getpixel((4, 60)) != b.getpixel((4, 60))
    # The top accent is brand chrome and stays put on any ground.
    assert a.getpixel((4, 1)) == b.getpixel((4, 1)) == ce.GREEN


def test_the_bar_track_travels_with_the_ground():
    """The defect the first navy render actually showed, caught by looking at the picture.

    The goal bar's unfilled track was a fixed green-black picked against the daily ground.
    On the navy weekly it lay across the card as a foreign strip — the ground had moved and
    one piece of chrome had not. Derived now, so it cannot be left behind again, and the
    daily's historic track is pinned to the exact byte it always was.
    """
    from web import recap_charts as ch

    assert ch.track_for() == (18, 26, 20), "the DAILY bar track moved"
    assert ch.track_for(ce.BG) == (18, 26, 20)

    weekly = _weekly(BAD_WEEK).convert("RGB")
    daily = L.scorecard(_facts(), date_label="Sat 12 Sep").convert("RGB")
    # Sample the goal-bar track well right of the filled sliver, on both cards.
    wt, dt = weekly.getpixel((900, L.BAR_Y + 8)), daily.getpixel((900, L.BAR_Y + 8))
    assert dt == (18, 26, 20), "the daily goal-bar track changed"
    assert wt == ch.track_for(L.WEEKLY_GROUND) != dt, "the weekly still carries the daily's track"


def test_the_weekly_passes_the_render_qa_gate():
    """Whatever the ground, the frame still has to clear the gate that every card clears."""
    from web import recap_qa

    verdict = recap_qa.audit_image(_weekly(BAD_WEEK), margin=L.M)
    assert verdict.may_store, f"render QA held the weekly on its new ground: {verdict.hard[:3]}"
