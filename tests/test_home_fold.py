"""#1469 → ADR-157 — the v7 Home fold: the dated photograph beside the number.

The v4 fold was the loop dial (a code-drawn SVG of the four stations with the day counter
at the hub). Prototype C's screen I — the owner's pick — opens the log on the day-1
photograph beside the weight with its day and range, then the lead sentence and the alive
line; the constellation and the dial are retired with the v4 Home. Source-level pins on
the committed shell (scripts/v7/home.py):

  1. the fold entry is the first entry of the log and holds the photograph frame, the
     number slot, the lead and the alive line, in that order;
  2. the photograph is the owner-approved day-1 image (#3761), eager-loaded with its
     intrinsic size (the fold's LCP, no layout shift) and a real alt text;
  3. the retired v4 fold pieces (loop dial, constellation, the okay beat markup) are gone.
"""

import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = open(os.path.join(_REPO, "site/index.html"), encoding="utf-8").read()
MAIN = HOME[HOME.index('<main id="main"') : HOME.index("</main>")]


def _fold() -> str:
    start = MAIN.index(">", MAIN.index('id="v7h-fold"')) + 1
    return MAIN[start : MAIN.rindex("<div", 0, MAIN.index('id="v7h-weighins"'))]


def test_the_fold_is_the_first_entry_and_holds_the_four_pieces_in_order():
    first_entry = MAIN.index('class="v7h-entry"')
    assert MAIN.index('id="v7h-fold"') - first_entry < 40, "the fold is not the first entry of the log"
    fold = _fold()
    idx = [fold.index(m) for m in ('id="v7h-photo"', 'id="v7h-number"', 'id="v7h-lead"', 'id="v7h-alive"')]
    assert idx == sorted(idx), "the fold's pieces are out of order (photo · number · lead · alive)"


def test_the_photograph_is_the_day_one_frame_eager_and_sized():
    img = re.search(r"<img [^>]*>", _fold()).group(0)
    assert 'src="/assets/images/photo-2026-09-06-day1-sm.jpg"' in img
    assert "/assets/images/photo-2026-09-06-day1.jpg 900w" in img
    assert 'alt="Matthew on day 1, Sunday September 6, front view"' in img
    assert 'loading="eager"' in img and 'width="360"' in img and 'height="480"' in img
    for stem in ("photo-2026-09-06-day1-sm.jpg", "photo-2026-09-06-day1.jpg"):
        assert os.path.isfile(os.path.join(_REPO, "site", "assets", "images", stem)), stem


def test_the_caption_and_the_number_slot_carry_no_baked_number():
    fold = _fold()
    assert 'id="v7h-photo-cap"' in fold and "Day one, front view." in fold
    text = re.sub(r"<[^>]+>", " ", fold)
    assert not re.search(r"\d", text), f"a number baked into the fold: {text.strip()[:160]!r}"


def test_the_v4_fold_is_retired():
    for retired in ('class="loop-dial"', 'class="constellation"', 'class="beat beat-okay', 'id="arc"', "beat-dispatches"):
        assert retired not in MAIN, f"the v4 fold is back: {retired}"
