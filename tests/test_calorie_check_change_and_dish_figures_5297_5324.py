"""#5297 / #5324 — the 2026-10-29 synthetic proof: both editions still BLOCKED on their own figures.

Run on the deployed bundles (read-only, every AWS write refused), the Weekly Plate and the Nutrition
Review each produced a whole edition under the raised output cap, and AI-3 Check 5 blocked both:

  * Weekly Plate — a single food described in prose: "<N> grams of protein for <M> calories", and
    "A cup of <food> runs about <M> cal and <N>g of protein" (the per-day phrase in the PREVIOUS
    sentence vetoed it through the +/-80-char window);
  * Nutrition Review — a week-over-week change ("+<N> kcal/day"), a saving ("~<N> kcal saved") and
    dish labels with only protein beside them ("(<N> g protein, <M> kcal)").

The same proof showed the day-sum guard (the backstop the #5299/#5350 meal-figure exemptions were
accepted on) reading each edition's MASTHEAD ("<Weekday> Edition · <date>") as a day heading, so the
whole edition was one "day" whose sum always cleared the floor and the guard could never fire.

The editions are owner-only nutrition text, so every sentence here is SYNTHETIC: generic food words
and invented figures, never a figure from the captured outputs.

The 2026-10-30 re-proof on the deployed bundle (main e0e515920) blocked three more editions, each on
one figure: a saving named BEFORE the figure ("Saves ~<N> kcal, ...", "Net savings: ~<N> kcal, ...")
and a single food's portion cap given as a mass ("cap <food> at <N> g (≈<M> kcal)").

Held both directions: each new exemption passes; every control blocks (the #2215/#5299/#5324
prescriptions, a day plan summing under the charter floor); a masthead never opens a day.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

from ai import ai_output_validator as v  # noqa: E402
from ai.ai_output_validator import AIOutputType, validate_ai_output  # noqa: E402
from training import training_charter as tc  # noqa: E402

_CARD = '<div style="border-left:3px solid #10b981"><p>{}</p></div>'


@pytest.fixture(autouse=True)
def _offline_charter(monkeypatch):
    """The tracked public charter only: no S3 probe, no laptop twin."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _check(text, output_type=AIOutputType.NUTRITION_COACH):
    return validate_ai_output(text, output_type, {}, max_length=40_000)


def _minimum():
    return tc.public_view()["nutrition"]["calories"]["planned_minimum_any_weight_kcal"]


# ── the new exemptions pass ───────────────────────────────────────────────────

# (shape, synthetic sentence). The shape names which root cause each sentence reproduces.
_PASSING_SHAPES = [
    ("signed week-over-week change", "The trend is real: +140 kcal/day week-over-week."),
    ("signed change, unicode minus", "Intake moved −160 kcal versus last week."),
    ("signed change, plus-minus", "The estimate is good to ±150 kcal."),
    ("saving after the unit", "Swap half the rice for greens: same prep, ~350 kcal saved, more fibre."),
    ("change word after a per-day unit", "That is 210 kcal a day more than the week before."),
    ("dish label, protein only", "The lentil bowl after training (48 g protein, 540 kcal) is well-timed."),
    ("dish label, grams of protein", "26 grams of protein for 170 calories is a strong ratio."),
    ("dish label, g of protein", "A cup of plain yogurt runs about 230 cal and 22g of protein, and it works sweet or savoury."),
    (
        "per-day phrase in the PREVIOUS sentence",
        "Yogurt is one of the easiest foods to fit at the target calories a day. "
        "A cup of plain yogurt runs about 230 cal and 22g of protein.",
    ),
    ("saving before the figure", "Saves ~350 kcal, adds 6 g fiber, keeps the flavour intact."),
    ("net savings before the figure", "Net savings: ~420 kcal, +3 g fiber, +200 mg potassium."),
    ("food mass then figure", "Use the leaner cut, add a cup of greens, cap the rice at 150 g (≈200 kcal)."),
    ("figure then food mass", "Keep the granola to 250 kcal (≈60 g) and add berries."),
]


def test_each_new_exemption_passes_and_reports_every_offender():
    offenders = []
    for shape, sentence in _PASSING_SHAPES:
        r = _check(_CARD.format(sentence))
        if r.blocked:
            offenders.append((shape, r.block_reason))
    assert not offenders, offenders


def test_a_review_narrative_with_every_shape_passes_whole():
    """One edition-shaped narrative carrying all of the shapes at once, as the real ones did."""
    html = "".join(_CARD.format(s) for _shape, s in _PASSING_SHAPES)
    r = _check(html)
    assert not r.blocked, r.block_reason


# ── the controls still block ──────────────────────────────────────────────────

_BLOCKING_CONTROLS = [
    "Eat only 600 calories today.",
    "a 600 kcal day with 120 g protein",
    "Cap your meals at 500 calories a day this week.",  # #5299
    "Dinner on rest days: 600 cal and nothing else.",  # #5299
    "<h3>Dinner</h3><p>Try 600 cal.</p>",  # #5299: a heading cannot launder the next line
    "Daily target - 600 kcal",  # a spaced dash is not a sign
    "Eat 150-180 cal today",  # a range's upper figure is still a figure
    "Stay under 612 kcal. You logged a lot last week, so no more than 612 cal.",  # #5324
    "Total for the day: 650 kcal with 90 g protein.",  # a protein label cannot buy a day total
    "Cut to 600 kcal today.",  # 2026-10-30: a change word must sit right before the figure
    "Savings aside, eat 600 calories today.",
    "Eat 300 g (≈600 kcal) of food today.",  # a day framing beats a food mass
    "Limit yourself to 600 kcal (about 400 g of food).",  # so does a restriction
]


def test_every_control_still_blocks():
    missed = [c for c in _BLOCKING_CONTROLS if not _check(c if c.startswith("<") else _CARD.format(c)).blocked]
    assert not missed, missed


def test_the_daily_brief_types_are_covered_too():
    for output_type in (AIOutputType.GUIDANCE, AIOutputType.BOD_COACHING):
        assert _check("Eat only 600 calories today.", output_type).blocked, output_type
        assert not _check("The trend is real: +140 kcal/day week-over-week.", output_type).blocked, output_type


# ── the day-sum guard still runs, and the exemptions cannot hide a low day ────


def _day(name, rows):
    return f"<h3>{name}</h3>" + "".join(f"<p>{row}</p>" for row in rows)


def test_a_low_day_sum_still_blocks_with_protein_labelled_meals():
    html = _day(
        "Monday",
        ["Breakfast — 200 cal (25 g protein)", "Lunch — 250 cal (30 g protein)", "The bowl (40 g protein, 300 kcal)"],
    )
    r = _check(html)
    assert r.blocked and "Monday" in r.block_reason, r.block_reason
    assert r.day_sums["Monday"]["total_kcal"] == 750


def test_a_change_figure_is_not_summed_into_a_day():
    """'~N kcal saved' is no meal: summing it would lift a low day over the floor."""
    floor = int(_minimum() * v._DAY_SUM_MARGIN)
    rows = ["Breakfast — 200 cal", "Lunch — 250 cal", "Dinner — 300 cal", f"Swap the dinner side: ~{floor} kcal saved."]
    r = _check(_day("Monday", rows))
    assert r.blocked, r.block_reason
    assert r.day_sums["Monday"]["total_kcal"] == 750


def test_a_check_5_pass_still_reaches_the_day_sum_guard():
    """Every figure here is exempt from Check 5 (meal-labelled); only the sum guard can block it."""
    rows = ["Breakfast — 200 cal", "Lunch — 250 cal", "Dinner — 300 cal"]
    r = _check(_day("Tuesday", rows))
    assert r.blocked and "Tuesday" in r.block_reason, r.block_reason


# ── the masthead is never a day heading (the real layout) ─────────────────────

# The real editions' header shape: a centred masthead whose small line OPENS WITH A WEEKDAY, then
# sections. Synthetic text; only the structure is the captures'.
_MASTHEAD_PLATE = (
    '<div style="text-align:center;padding:24px 0 16px;">'
    '<div style="font-size:22px;font-weight:700;">THE WEEKLY PLATE</div>'
    '<div style="color:#888;font-size:12px;">Friday Edition · January 9, 2026</div></div>'
)
_MASTHEAD_REVIEW = (
    '<div style="text-align:center;">'
    '<div style="font-size:11px;text-transform:uppercase;">Saturday Nutrition Review · Week 3</div>'
    '<div style="font-size:22px;font-weight:700;">January 3–9, 2026</div></div>'
)


def _plan_edition(masthead, days):
    """A synthetic edition: masthead, intro cards (one carrying a per-serving figure, as the real
    Greatest Hits cards do), then one plan block per day."""
    intro = _CARD.format("Here is the week, built around the foods you already rotate.") + _CARD.format(
        "Greatest hit: the oat bowl · Per serving: 310 cal · 18g P / 40g C / 8g F"
    )
    blocks = "".join(_day(name, [f"{label} — {kcal} cal · 30g P" for label, kcal in rows]) for name, rows in days)
    return masthead + intro + blocks


_NORMAL_DAY = [("Breakfast", 400), ("Lunch", 450), ("Snack", 150), ("Dinner", 500)]
_LOW_DAY = [("Breakfast", 200), ("Lunch", 250), ("Snack", 100), ("Dinner", 300)]


@pytest.mark.parametrize("masthead", [_MASTHEAD_PLATE, _MASTHEAD_REVIEW], ids=["plate-masthead", "review-masthead"])
def test_a_low_day_in_an_edition_shaped_plan_blocks_and_the_masthead_is_not_a_day(masthead):
    r = _check(_plan_edition(masthead, [("Monday", _NORMAL_DAY), ("Tuesday", _LOW_DAY), ("Wednesday", _NORMAL_DAY)]))
    assert r.blocked and "Tuesday" in r.block_reason, r.block_reason
    assert set(r.day_sums) <= {"Monday", "Tuesday"}, r.day_sums  # the guard stops at the first low day
    assert not any("Edition" in k or "Review" in k for k in r.day_sums), r.day_sums


@pytest.mark.parametrize("masthead", [_MASTHEAD_PLATE, _MASTHEAD_REVIEW], ids=["plate-masthead", "review-masthead"])
def test_normal_days_in_an_edition_shaped_plan_pass_and_each_is_judged(masthead):
    r = _check(_plan_edition(masthead, [("Monday", _NORMAL_DAY), ("Day 2", _NORMAL_DAY)]))
    assert not r.blocked, r.block_reason
    assert set(r.day_sums) == {"Monday", "Day 2"}
    assert all(e["judged"] for e in r.day_sums.values())


def test_a_cards_edition_under_a_masthead_is_ungrouped_and_recorded_not_one_big_day():
    """The real Weekly Plate is cards, not a plan: no day heading, so the recorded-warning fallback."""
    cards = "".join(_CARD.format(f"{label} — {kcal} cal · 30g P") for label, kcal in _LOW_DAY)
    r = _check(_MASTHEAD_PLATE + cards)
    assert not r.blocked, r.block_reason
    assert r.day_sums == {"_ungrouped": {"judged": False}}


def test_masthead_lines_are_never_day_headings_but_plan_headings_are():
    for line in ("Friday Edition · January 9, 2026", "Saturday Nutrition Review · Week 3", "Sunday Digest"):
        assert not v._is_day_heading(line), line
    for line in ("Monday", "Tuesday — rest day", "Day 3: lifting day", "Sunday · January 11"):
        assert v._is_day_heading(line), line


# ── mutation controls: each rule is load-bearing ──────────────────────────────


def test_mutation_title_as_heading_reds_the_masthead_assertions(monkeypatch):
    """The pre-fix heading reading (any weekday-led short line): the masthead opens a 'day'. The
    edition-shape assertions above must fail under it, and the cards edition is judged as ONE day
    whose sum clears the floor, which is the false assurance the captures showed."""
    monkeypatch.setattr(v, "_MASTHEAD_WORDS_RE", v.re.compile(r"(?!x)x"))
    assert v._is_day_heading("Friday Edition · January 9, 2026")

    for masthead in (_MASTHEAD_PLATE, _MASTHEAD_REVIEW):
        r = _check(_plan_edition(masthead, [("Monday", _NORMAL_DAY), ("Day 2", _NORMAL_DAY)]))
        assert set(r.day_sums) != {"Monday", "Day 2"}, r.day_sums  # the masthead became a "day"

    cards = "".join(_CARD.format(f"{label} — {kcal} cal · 30g P") for label, kcal in _NORMAL_DAY * 2)
    r = _check(_MASTHEAD_PLATE + cards)
    masthead_days = [e for k, e in r.day_sums.items() if "Edition" in k]
    assert masthead_days and masthead_days[0]["judged"] is True, r.day_sums


def test_mutation_without_the_change_rule_the_change_shapes_block(monkeypatch):
    monkeypatch.setattr(v, "_is_change_figure", lambda text, match: False)
    assert _check(_CARD.format("Swap half the rice for greens: same prep, ~350 kcal saved, more fibre.")).blocked
    assert _check(_CARD.format("The trend is real: +140 kcal/day week-over-week.")).blocked


def test_mutation_without_the_protein_label_the_dish_label_blocks(monkeypatch):
    monkeypatch.setattr(v, "_PROTEIN_LABEL_RE", v.re.compile(r"(?!x)x"))
    assert _check(_CARD.format("The lentil bowl after training (48 g protein, 540 kcal) is well-timed.")).blocked


def test_mutation_with_the_window_the_previous_sentence_vetoes_again(monkeypatch):
    sentence = "Yogurt fits at the target calories a day. A cup of plain yogurt runs about 230 cal and 22g of protein."
    assert not _check(_CARD.format(sentence)).blocked

    def _window_as_segment(text, match):  # the pre-fix reading: the +/-80-char window, across sentence ends
        return text[max(0, match.start() - v._CALORIE_CONTEXT_WINDOW) : match.end() + v._CALORIE_CONTEXT_WINDOW]

    monkeypatch.setattr(v, "_enclosing_segment", _window_as_segment)
    assert _check(_CARD.format(sentence)).blocked
