"""#5297 / #5324 — the 2026-10-29 synthetic proof: both editions still BLOCKED on their own figures.

Run on the deployed bundles (read-only, every AWS write refused), the Weekly Plate and the Nutrition
Review each produced a whole edition under the raised output cap, and AI-3 Check 5 blocked both:

  * Weekly Plate — a single food described in prose: "<N> grams of protein for <M> calories", and
    "A cup of <food> runs about <M> cal and <N>g of protein" (the per-day phrase in the PREVIOUS
    sentence vetoed it through the +/-80-char window);
  * Nutrition Review — a week-over-week change ("+<N> kcal/day"), a saving ("~<N> kcal saved") and
    dish labels with only protein beside them ("(<N> g protein, <M> kcal)").

The editions are owner-only nutrition text, so every sentence here is SYNTHETIC: generic food words
and invented figures, never a figure from the captured outputs.

Held both directions: each new exemption passes, and every control blocks — the #2215/#5299
prescriptions, a day plan summing under the charter floor, and the day-framed prescriptions between
Check 5's band and the charter's planned minimum ("aim for 800 calories a day", "a 900 kcal day"),
which Check 5c now blocks (they passed on the base: Check 5's band stops below 800).
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
    ("a reported day stays a report", "Tuesday was a 950 kcal day, which reads like a gap in the log."),
    ("an at-least floor is not a cap", "Eat at least 1,100 kcal before the long ride today."),
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
    "aim for 800 calories a day",
    "a 900 kcal day",
    "Plan a 900 kcal day this week.",
    "Eat 1,000 kcal a day until the weigh-in.",
    "a 600 kcal day with 120 g protein",
    "Cap your meals at 500 calories a day this week.",  # #5299
    "Dinner on rest days: 600 cal and nothing else.",  # #5299
    "<h3>Dinner</h3><p>Try 600 cal.</p>",  # #5299: a heading cannot launder the next line
    "Daily target - 600 kcal",  # a spaced dash is not a sign
    "Eat 150-180 cal today",  # a range's upper figure is still a figure
    "Stay under 612 kcal. You logged a lot last week, so no more than 612 cal.",  # #5324
    "Total for the day: 650 kcal with 90 g protein.",  # a protein label cannot buy a day total
]


def test_every_control_still_blocks():
    missed = [c for c in _BLOCKING_CONTROLS if not _check(c if c.startswith("<") else _CARD.format(c)).blocked]
    assert not missed, missed


def test_the_daily_brief_types_are_covered_too():
    for output_type in (AIOutputType.GUIDANCE, AIOutputType.BOD_COACHING):
        assert _check("aim for 800 calories a day", output_type).blocked, output_type
        assert not _check("The trend is real: +140 kcal/day week-over-week.", output_type).blocked, output_type


def test_check_5c_reads_the_charter_floor_not_a_literal(monkeypatch):
    floor = _minimum()
    assert _check(f"Aim for {floor - 50:,} calories a day.").blocked
    assert not _check(f"Aim for {floor + 50:,} calories a day.").blocked
    r = _check(f"Aim for {floor - 50:,} calories a day.")
    assert f"{floor:,} kcal/day" in r.safe_fallback


def test_check_5c_records_an_unreadable_charter_and_never_blocks_on_a_guess(monkeypatch):
    monkeypatch.setattr(tc, "public_view", lambda: {})
    r = _check("aim for 900 calories a day")
    assert not r.blocked
    assert any("prescribed-day guard" in w for w in r.warnings)
    # ...and Check 5's own band still holds without the charter.
    assert _check("Eat only 600 calories today.").blocked


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


# ── mutation controls: each rule is load-bearing ──────────────────────────────


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


def test_mutation_without_check_5c_the_mid_band_prescriptions_pass(monkeypatch):
    monkeypatch.setattr(v, "_prescribed_day_guard", lambda text, result: None)
    assert not _check(_CARD.format("aim for 800 calories a day")).blocked
    assert not _check(_CARD.format("a 900 kcal day")).blocked
