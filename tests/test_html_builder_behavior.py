#!/usr/bin/env python3
"""tests/test_html_builder_behavior.py — behavioral contracts of
`lambdas/content/html_builder.py`, the renderer for the Daily Brief email.

Part of #1658 tranche 3. There is exactly one reader of this output — Matthew,
at 10 AM PT, every morning — so the contracts pinned here are the ones that
reach a human eye:

  * ADR-104 honest numbers — an unmeasured quantity must never surface as a
    factual 0, a neutral 50, or a default "level 1". `avg([])` returning None is
    the standard the rest of the module is measured against.
  * ADR-105 rigor — an average or a percentage ships with the n behind it.
  * reader/writer field-name parity — this module reads field names off records
    written elsewhere in the repo. Every field it reads is checked against the
    module that actually writes it; a mismatch leaves a feature permanently dark
    with no error anywhere (the dominant defect class in tranche 2).
  * honest degradation — every section is wrapped so one bad record cannot kill
    the email; a section that *can* crash the whole render is a defect, and a
    section that silently renders empty where an error is the truth is also a
    defect.
  * trend/delta direction — a decline is never described as an improvement.
  * arithmetic the reader sees — completion percentages, streaks, progress bars.
    Every expectation below is hand-derived in the test body with the derivation
    written as a comment; never "whatever the code returned".
  * escaping — every string this module interpolates into HTML comes from a
    model (coach narrative, TL;DR, board insight), a third-party API (a Strava
    activity name), or a config file (a habit name). None of it is escaped.

Growable sets are DERIVED, never restated: the scorecard tiles come from
`health.scoring_engine.COMPONENT_SCORERS`, the V2 coach roster comes from
`build_html`'s own signature, and the habit lists come from the profile's
`habit_registry`.

Nothing here touches AWS, the network, or SES. `html_builder` is a pure renderer
with no boto3 import at all — that property is itself asserted below, because it
is what makes this file safe to run against the module that composes the email.

CLOCK NOTE: the module reads the wall clock in exactly one place (the Board of
Directors confidence badge, which does a function-local `from datetime import
datetime as _dt` and so cannot be reached by patching a module attribute). That
single site is pinned by `test_module_reads_the_wall_clock_in_exactly_one_place`
and every other test avoids depending on `now()`. No fixture date is ever
combined with real-clock arithmetic.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

from content import html_builder as hb  # noqa: E402
from health.scoring_engine import COMPONENT_SCORERS  # noqa: E402  — the growable scorer registry

HB_SOURCE = open(os.path.join(LAMBDAS, "content", "html_builder.py"), encoding="utf-8").read()


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures — a minimal, frozen data packet. No wall clock anywhere.
# ══════════════════════════════════════════════════════════════════════════════

DATE = "2026-06-10"  # a Wednesday; fixed, never derived from now()

PROFILE = {
    "calorie_target": 1500,
    "protein_target_g": 190,
    "goal_weight_lbs": 185,
    "journey_start_weight_lbs": 311.0,
    # far past on purpose — the BoD badge derives days-of-data from wall-clock now();
    # a date this old keeps it stable without this file ever asserting on it.
    "journey_start_date": "2024-01-01",
    "habit_registry": {},
}


def _profile(**over):
    p = dict(PROFILE)
    p.update(over)
    return p


def _data(**over):
    d = {"date": DATE, "hrv": {"hrv_7d": None, "hrv_30d": None}}
    d.update(over)
    return d


def _build_kwargs(**over):
    """The full positional surface of build_html as keywords, minimally populated."""
    kw = dict(
        data=_data(),
        profile=_profile(),
        day_grade_score=None,
        grade="C",
        component_scores={},
        component_details={},
        readiness_score=None,
        readiness_colour="gray",
        tldr_guidance=None,
        bod_insight=None,
        training_nutrition=None,
        journal_coach_text=None,
        mvp_streak=0,
        full_streak=0,
    )
    kw.update(over)
    return kw


# ══════════════════════════════════════════════════════════════════════════════
# §0 — module-level safety properties
# ══════════════════════════════════════════════════════════════════════════════


def test_renderer_imports_no_aws_client():
    """The daily-brief renderer must stay a pure function of its inputs.

    This is what makes it safe to exercise every section here without a single
    stub: there is no boto3 client, no table handle, no SES send in the module.
    """
    assert "boto3" not in HB_SOURCE
    assert "send_email" not in HB_SOURCE


def test_module_reads_the_wall_clock_in_exactly_one_place():
    """Pin the single `now()` site (the BoD confidence badge).

    A renderer that reads the clock cannot be snapshot-tested and drifts against
    the date it is rendering *for* — `data["date"]`. One site is a known,
    documented exception; a second one appearing is a regression.
    """
    now_sites = re.findall(r"\.now\(", HB_SOURCE)
    assert len(now_sites) == 1, f"expected 1 wall-clock read, found {len(now_sites)}"


# ══════════════════════════════════════════════════════════════════════════════
# §1 — avg / clamp / fmt_num
# ══════════════════════════════════════════════════════════════════════════════


def test_avg_of_nothing_is_none_not_zero():
    """ADR-104: no observations means no average, never 0."""
    assert hb.avg([]) is None
    assert hb.avg([None, None]) is None


def test_avg_ignores_none_and_rounds_to_one_decimal():
    # (10 + 11) / 2 = 10.5 -> round(10.5, 1) = 10.5
    assert hb.avg([10, None, 11]) == 10.5
    # (1 + 2 + 4) / 3 = 2.3333... -> round(..., 1) = 2.3
    assert hb.avg([1, 2, 4]) == 2.3


def test_avg_rounds_half_to_even():
    """round() is banker's rounding — pinned so a change is deliberate.

    (1.25 + 1.25) / 2 = 1.25 -> round(1.25, 1) = 1.2, NOT 1.3.
    """
    assert hb.avg([1.25, 1.25]) == 1.2


def test_avg_raises_on_a_decimal_float_mix():
    """DynamoDB hands back Decimal; a caller that mixes one float in crashes.

    Not currently reachable — every in-module caller funnels through
    `safe_float` first — but the helper is exported and the trap is real, so it
    is pinned rather than left to be discovered in a Lambda log.
    """
    with pytest.raises(TypeError):
        hb.avg([Decimal("1"), 2.0])


def test_clamp_constrains_to_the_inclusive_band():
    assert hb.clamp(150) == 100
    assert hb.clamp(-5) == 0
    assert hb.clamp(50) == 50
    assert hb.clamp(5, 10, 20) == 10
    assert hb.clamp(50, 10, 20) == 20


def test_clamp_on_none_raises():
    """`clamp(None)` is a TypeError, not a 0 — pinned as honest-crash behavior."""
    with pytest.raises(TypeError):
        hb.clamp(None)


def test_clamp_is_dead_code_in_this_module():
    """`clamp` is defined, exported, and called by nobody.

    `daily_brief_lambda` — the only importer of this module — has its own
    `clamp`. Pinned so the next reader does not assume the brief's scores are
    being clamped here.
    """
    assert len(re.findall(r"\bclamp\(", HB_SOURCE)) == 1  # the `def` line only


def test_fmt_num_none_is_an_em_dash_not_zero():
    """ADR-104 at the formatting layer: absent renders as absent."""
    assert hb.fmt_num(None) == "—"


def test_fmt_num_comma_groups_and_rounds():
    # round(12345.6) = 12346 -> "12,346"
    assert hb.fmt_num(12345.6) == "12,346"
    assert hb.fmt_num(0) == "0"


def test_fmt_num_rounds_half_to_even():
    """round() again — 2.5 renders as "2", 3.5 as "4"."""
    assert hb.fmt_num(2.5) == "2"
    assert hb.fmt_num(3.5) == "4"


def test_fmt_num_never_renders_negative_zero():
    # round(-0.4) -> int 0, so the "-0" trap does not fire here.
    assert hb.fmt_num(-0.4) == "0"


def test_fmt_num_crashes_on_nan_and_inf():
    """A non-finite float takes down the whole enclosing section.

    `fmt_num` is called on calorie totals and Hevy volume — both derived from
    division upstream — so a NaN is not purely theoretical.
    """
    with pytest.raises(ValueError):
        hb.fmt_num(float("nan"))
    with pytest.raises(OverflowError):
        hb.fmt_num(float("inf"))


# ══════════════════════════════════════════════════════════════════════════════
# §2 — get_current_phase
# ══════════════════════════════════════════════════════════════════════════════

PHASES = [
    {"name": "Phase 1", "end_lbs": 280},
    {"name": "Phase 2", "end_lbs": 240},
    {"name": "Phase 3", "end_lbs": 200},
]


def test_get_current_phase_picks_the_first_band_the_weight_still_qualifies_for():
    prof = _profile(weight_loss_phases=PHASES)
    assert hb.get_current_phase(prof, 300)["name"] == "Phase 1"
    assert hb.get_current_phase(prof, 260)["name"] == "Phase 2"
    assert hb.get_current_phase(prof, 210)["name"] == "Phase 3"


def test_get_current_phase_is_inclusive_at_the_boundary():
    """A weight sitting exactly on `end_lbs` stays in the phase it just finished.

    280.0 == Phase 1's end_lbs, and `>=` keeps it there rather than promoting it
    to Phase 2. Pinned because it is the boundary a reader notices on the one
    morning they hit the number exactly.
    """
    prof = _profile(weight_loss_phases=PHASES)
    assert hb.get_current_phase(prof, 280)["name"] == "Phase 1"
    # one tenth of a pound below the boundary flips it
    assert hb.get_current_phase(prof, 279.9)["name"] == "Phase 2"


def test_get_current_phase_below_every_band_falls_back_to_the_last():
    prof = _profile(weight_loss_phases=PHASES)
    assert hb.get_current_phase(prof, 150)["name"] == "Phase 3"


def test_get_current_phase_with_no_phases_is_none():
    assert hb.get_current_phase(_profile(), 300) is None
    assert hb.get_current_phase(_profile(weight_loss_phases=[]), 300) is None


def test_get_current_phase_on_a_none_weight_raises():
    """`None >= int` is a TypeError.

    Not reachable from `_brief_lifestyle` (guarded by `if latest_weight:`), but
    the helper is exported and this is what it does.
    """
    with pytest.raises(TypeError):
        hb.get_current_phase(_profile(weight_loss_phases=PHASES), None)


def test_get_current_phase_a_phase_missing_end_lbs_captures_every_weight():
    """`p.get("end_lbs", 0)` defaults a malformed phase to a floor of 0.

    A profile whose first phase is missing `end_lbs` therefore matches ANY
    positive weight, and the brief silently reports that phase forever. Fails
    soft in the worst way: no error, just a permanently wrong phase name.
    """
    prof = _profile(weight_loss_phases=[{"name": "typo'd phase"}] + PHASES)
    assert hb.get_current_phase(prof, 210)["name"] == "typo'd phase"


# ══════════════════════════════════════════════════════════════════════════════
# §3 — hrv_trend_str
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "hrv_7d,hrv_30d,expected",
    [
        # (62/58 - 1) * 100 = 6.8965... -> round -> 7  => up
        (62, 58, "62ms 7d avg (+7% vs 30d, trending up)"),
        # (58/62 - 1) * 100 = -6.4516... -> round -> -6 => down
        (58, 62, "58ms 7d avg (-6% vs 30d, trending down)"),
        # equal -> 0% -> inside the +/-2 band => stable, and the "+" arrow is added
        (60, 60, "60ms 7d avg (+0% vs 30d, stable)"),
        # (61.2/60 - 1) * 100 = 2.0 -> exactly on the up threshold
        (61.2, 60, "61ms 7d avg (+2% vs 30d, trending up)"),
        # (58.8/60 - 1) * 100 = -2.0 -> exactly on the stable floor
        (58.8, 60, "59ms 7d avg (-2% vs 30d, stable)"),
    ],
)
def test_hrv_trend_direction_and_wording(hrv_7d, hrv_30d, expected):
    assert hb.hrv_trend_str(hrv_7d, hrv_30d) == expected


@pytest.mark.parametrize("args", [(None, 60), (60, None), (60, 0), (0, 60), (None, None)])
def test_hrv_trend_missing_inputs_say_so(args):
    """ADR-104: no comparison basis means "no trend data", never a fabricated 0%."""
    assert hb.hrv_trend_str(*args) == "no trend data"


def test_hrv_trend_never_calls_a_decline_an_improvement():
    """Property sweep over the whole band: sign is never inverted.

    HRV up = recovery up. Any 7-day mean materially below the 30-day mean must
    read "trending down"; any materially above must read "trending up".
    """
    base = 60.0
    for pct in range(-40, 41):
        seven = base * (1 + pct / 100.0)
        s = hb.hrv_trend_str(seven, base)
        if pct <= -3:
            assert "trending down" in s, (pct, s)
            assert "trending up" not in s
        elif pct >= 3:
            assert "trending up" in s, (pct, s)
            assert "trending down" not in s


def test_hrv_trend_accepts_decimal_from_dynamodb():
    assert hb.hrv_trend_str(Decimal("62"), Decimal("58")) == "62ms 7d avg (+7% vs 30d, trending up)"


def test_hrv_trend_rounds_the_percent_before_banding():
    """A +1.7% week is reported as "+2% ... trending up".

    `pct` is rounded to a whole number BEFORE the +/-2 band is applied, so a
    change strictly inside the stable band can be promoted to "trending up".
    Cosmetic, but pinned so the threshold semantics are explicit.
    """
    # (61.02/60 - 1) * 100 = 1.7 -> round -> 2 -> "trending up"
    assert "trending up" in hb.hrv_trend_str(61.02, 60)


# ══════════════════════════════════════════════════════════════════════════════
# §4 — _section_error_html
# ══════════════════════════════════════════════════════════════════════════════


def test_section_error_html_names_the_failing_section():
    out = hb._section_error_html("Nutrition Report", ValueError("boom"))
    assert "Nutrition Report" in out
    assert "section unavailable" in out


def test_section_error_html_does_not_leak_the_exception_text_to_the_reader():
    """The reader sees "X section unavailable"; the traceback goes to the log."""
    out = hb._section_error_html("CGM", ValueError("secret-token-abc"))
    assert "secret-token-abc" not in out


def test_section_error_html_does_not_escape_the_section_name():
    """Section names are code literals today, so this is latent, not live."""
    out = hb._section_error_html("<b>x</b>", ValueError("e"))
    assert "<b>x</b>" in out


# ══════════════════════════════════════════════════════════════════════════════
# §5 — _compute_weekly_habit_review
# ══════════════════════════════════════════════════════════════════════════════
#
# Writer contract (verified against lambdas/emails/daily_brief_lambda.py
# ::store_habit_scores): the habit_scores record carries tier0_done/tier0_total
# as ints, tier0_pct/tier1_pct as Decimal, missed_tier0 as a list of names, and
# synergy_groups as a name->Decimal map. `None`-valued keys are STRIPPED before
# the put_item, so an absent key and a null are the same thing on read.


def _hs(date, done, total, pct=None, missed=None, t1_pct=None, synergy=None):
    """A habit_scores record in exactly the shape store_habit_scores writes."""
    rec = {"date": date, "tier0_done": done, "tier0_total": total}
    if pct is not None:
        rec["tier0_pct"] = Decimal(str(pct))
    if missed:
        rec["missed_tier0"] = list(missed)
    if t1_pct is not None:
        rec["tier1_pct"] = Decimal(str(t1_pct))
    if synergy:
        rec["synergy_groups"] = {k: Decimal(str(v)) for k, v in synergy.items()}
    return rec


REG_4_T0 = {
    "Sleep 7h": {"tier": 0, "status": "active"},
    "Log food": {"tier": 0, "status": "active"},
    "Walk 8k": {"tier": 0, "status": "active"},
    "Lift": {"tier": 0, "status": "active"},
    "Read": {"tier": 1, "status": "active"},
    "Retired habit": {"tier": 0, "status": "archived"},
}


def test_whr_no_records_is_none_not_an_empty_week():
    assert hb._compute_weekly_habit_review([], _profile()) is None
    assert hb._compute_weekly_habit_review(None, _profile()) is None


def test_whr_basic_arithmetic():
    recs = [
        _hs("2026-06-08", 4, 4, "1.0"),
        _hs("2026-06-09", 2, 4, "0.5", missed=["Walk 8k", "Lift"]),
        _hs("2026-06-10", 3, 4, "0.75", missed=["Lift"]),
    ]
    whr = hb._compute_weekly_habit_review(recs, _profile(habit_registry=REG_4_T0))

    assert whr["days"] == 3
    assert whr["perfect_days"] == 1  # only 2026-06-08 has done == total > 0
    # (1.0 + 0.5 + 0.75) / 3 = 0.75 -> round(0.75, 3) = 0.75
    assert whr["avg_t0_pct"] == 0.75
    rows = {h["name"]: h for h in whr["t0_habits"]}
    # 4 active tier-0 habits; the archived one and the tier-1 one are excluded
    assert set(rows) == {"Sleep 7h", "Log food", "Walk 8k", "Lift"}
    # Lift missed on 2 of 3 days -> 1/3 -> round(1/3, 3) = 0.333
    assert rows["Lift"]["days_done"] == 1 and rows["Lift"]["pct"] == 0.333
    # Walk 8k missed on 1 of 3 -> 2/3 -> 0.667
    assert rows["Walk 8k"]["days_done"] == 2 and rows["Walk 8k"]["pct"] == 0.667
    # never missed -> 3/3
    assert rows["Sleep 7h"]["days_done"] == 3 and rows["Sleep 7h"]["pct"] == 1.0
    # best-first ordering
    assert [h["pct"] for h in whr["t0_habits"]] == sorted((h["pct"] for h in whr["t0_habits"]), reverse=True)


def test_whr_derives_its_habit_list_from_the_registry():
    """The T0 habit list is the registry's active tier-0 set — never a literal.

    Adding a habit to the profile must add a row; archiving one must remove it.
    """
    reg = dict(REG_4_T0)
    reg["Cold plunge"] = {"tier": 0, "status": "active"}
    whr = hb._compute_weekly_habit_review([_hs("2026-06-10", 5, 5, "1.0")], _profile(habit_registry=reg))
    expected = {n for n, m in reg.items() if m.get("tier") == 0 and m.get("status") == "active"}
    assert {h["name"] for h in whr["t0_habits"]} == expected


def test_whr_sorts_records_by_date_regardless_of_query_order():
    recs = [_hs("2026-06-10", 1, 4, "0.25"), _hs("2026-06-08", 4, 4, "1.0"), _hs("2026-06-09", 2, 4, "0.5")]
    whr = hb._compute_weekly_habit_review(recs, _profile())
    assert [d["date"] for d in whr["daily"]] == ["2026-06-08", "2026-06-09", "2026-06-10"]


def test_whr_falls_back_to_the_sort_key_when_date_is_absent():
    rec = {"sk": "DATE#2026-06-10", "tier0_done": 2, "tier0_total": 4, "tier0_pct": Decimal("0.5")}
    whr = hb._compute_weekly_habit_review([rec], _profile())
    assert whr["daily"][0]["date"] == "2026-06-10"


def test_whr_a_perfect_day_requires_a_nonzero_total():
    """0-of-0 is not a perfect day. (Contrast the percentage — see the xfail below.)"""
    whr = hb._compute_weekly_habit_review([_hs("2026-06-10", 0, 0)], _profile())
    assert whr["perfect_days"] == 0
    assert whr["daily"][0]["perfect"] is False


def test_whr_tier1_average_is_none_when_no_day_reported_one():
    """ADR-104: a tier-1 average nobody measured is absent, not 0%."""
    whr = hb._compute_weekly_habit_review([_hs("2026-06-10", 2, 4, "0.5")], _profile())
    assert whr["avg_t1_pct"] is None


def test_whr_tier1_average_spans_only_the_days_that_reported_one():
    recs = [
        _hs("2026-06-08", 4, 4, "1.0", t1_pct="0.8"),
        _hs("2026-06-09", 4, 4, "1.0"),  # no tier1_pct — stripped by the writer
        _hs("2026-06-10", 4, 4, "1.0", t1_pct="0.6"),
    ]
    whr = hb._compute_weekly_habit_review(recs, _profile())
    # (0.8 + 0.6) / 2 = 0.7 — the silent day is excluded, not counted as 0
    assert whr["avg_t1_pct"] == 0.7


def test_whr_synergy_averages_over_the_days_that_carried_the_group():
    recs = [
        _hs("2026-06-08", 4, 4, "1.0", synergy={"sleep_stack": "1.0", "food_stack": "0.5"}),
        _hs("2026-06-09", 2, 4, "0.5", synergy={"sleep_stack": "0.5"}),
    ]
    whr = hb._compute_weekly_habit_review(recs, _profile())
    # sleep_stack: (1.0 + 0.5) / 2 = 0.75 -> round(..., 2) = 0.75
    # food_stack:  0.5 / 1 = 0.5
    assert whr["synergy"] == {"sleep_stack": 0.75, "food_stack": 0.5}


def test_whr_window_length_is_the_record_count_not_a_hardcoded_seven():
    """A quiet week reports the days it actually has — honest by construction."""
    whr = hb._compute_weekly_habit_review([_hs("2026-06-09", 4, 4, "1.0"), _hs("2026-06-10", 4, 4, "1.0")], _profile())
    assert whr["days"] == 2


def test_whr_duplicate_date_records_inflate_the_window():
    """No dedup by date — two rows for one day make it a "3-day window".

    `fetch_range` returns one row per date today, so this is latent; pinned
    because `days` is the denominator of every percentage in the section.
    """
    recs = [_hs("2026-06-09", 4, 4, "1.0"), _hs("2026-06-10", 4, 4, "1.0"), _hs("2026-06-10", 4, 4, "1.0")]
    assert hb._compute_weekly_habit_review(recs, _profile())["days"] == 3


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:135 _compute_weekly_habit_review — "
        "`t0_pct = float(raw_pct) if raw_pct is not None else (t0_done / t0_total if t0_total else 0)`. "
        "A day with zero applicable tier-0 habits (every T0 habit scoped `applicable_days: weekdays` "
        "on a weekend; store_habit_scores strips tier0_pct because `t0.get('total')` is falsy) is "
        "folded into the weekly mean as a hard 0.0. Should be EXCLUDED from the mean with n reported "
        "(ADR-104/105) — the same function already gets this right for `perfect` on line 137 "
        "(`(t0_total > 0) and ...`). Hurts Matthew: a week whose only measured day was 4/4 is "
        "reported as '50% T0 — Needs attention' in Sunday's brief."
    ),
)
def test_whr_a_day_with_no_applicable_tier0_habits_must_not_count_as_zero_percent():
    recs = [
        _hs("2026-06-09", 4, 4, "1.0"),  # measured: perfect
        _hs("2026-06-10", 0, 0),  # nothing applicable — tier0_pct stripped by the writer
    ]
    whr = hb._compute_weekly_habit_review(recs, _profile(habit_registry=REG_4_T0))
    # Honest answer: the one measured day was 100%. Current answer: (1.0 + 0.0)/2 = 0.5.
    assert whr["avg_t0_pct"] == 1.0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:165-172 _compute_weekly_habit_review — "
        "`days_done = days - days_missed` treats 'not in missed_tier0' as 'done'. A tier-0 habit that "
        "was NOT APPLICABLE on a day (weekday-only habit on a weekend, post_training habit with no "
        "workout) never enters tier_status[0] in scoring_engine.score_habits_registry, so it never "
        "enters missed_tier0 either — and is silently credited. Should count only the days the habit "
        "was actually evaluated, with that n as the denominator (ADR-105). Hurts Matthew: a habit he "
        "missed every single day it applied is reported at 4/7 in Sunday's Weekly Habit Review. "
        "The fix likely needs store_habit_scores to persist the applicable set, not just the misses."
    ),
)
def test_whr_a_habit_that_was_never_applicable_must_not_be_credited_as_done():
    reg = {"Weekday lift": {"tier": 0, "status": "active"}}
    recs = [
        # 3 weekdays: the habit was evaluated and missed each time
        _hs("2026-06-08", 0, 1, "0.0", missed=["Weekday lift"]),
        _hs("2026-06-09", 0, 1, "0.0", missed=["Weekday lift"]),
        _hs("2026-06-10", 0, 1, "0.0", missed=["Weekday lift"]),
        # 4 days it was not applicable at all — absent from tier_status, so absent from missed_tier0
        _hs("2026-06-11", 0, 0),
        _hs("2026-06-12", 0, 0),
        _hs("2026-06-13", 0, 0),
        _hs("2026-06-14", 0, 0),
    ]
    whr = hb._compute_weekly_habit_review(recs, _profile(habit_registry=reg))
    row = next(h for h in whr["t0_habits"] if h["name"] == "Weekday lift")
    # Honest answer: 0 of the 3 days it applied. Current answer: 7 - 3 = 4 of 7.
    assert row["days_done"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# §6 — _render_weekly_habit_review
# ══════════════════════════════════════════════════════════════════════════════


def _whr(**over):
    base = {
        "days": 2,
        "daily": [
            {"date": "2026-06-09", "t0_done": 4, "t0_total": 4, "t0_pct": 1.0, "perfect": True, "missed": []},
            {"date": "2026-06-10", "t0_done": 2, "t0_total": 4, "t0_pct": 0.5, "perfect": False, "missed": ["Lift"]},
        ],
        "perfect_days": 1,
        "avg_t0_pct": 0.75,
        "avg_t1_pct": None,
        "t0_habits": [{"name": "Lift", "days_done": 1, "days_total": 2, "pct": 0.5}],
        "synergy": {},
    }
    base.update(over)
    return base


def test_render_whr_none_renders_nothing():
    assert hb._render_weekly_habit_review(None) == ""
    assert hb._render_weekly_habit_review({}) == ""


def test_render_whr_headline_numbers():
    html = hb._render_weekly_habit_review(_whr())
    assert "Weekly Habit Review" in html
    # int(0.75 * 100) = 75 -> ">= 65 and < 85" -> "Mixed week"
    assert ">75<span" in html and "Mixed week" in html
    assert "2-day window" in html
    assert ">1/2</p>" in html  # perfect days
    # int(1 / 2 * 100) = 50
    assert "perfect days (50%)" in html


def test_render_whr_band_labels():
    # int(0.9 * 100) = 90 -> >= 85 -> Strong
    assert "Strong week" in hb._render_weekly_habit_review(_whr(avg_t0_pct=0.9))
    # int(0.65 * 100) = 65 -> >= 65 -> Mixed (lower boundary)
    assert "Mixed week" in hb._render_weekly_habit_review(_whr(avg_t0_pct=0.65))
    # int(0.64 * 100) = 64 -> Needs attention
    assert "Needs attention" in hb._render_weekly_habit_review(_whr(avg_t0_pct=0.64))


def test_render_whr_marks_perfect_days_with_a_star():
    html = hb._render_weekly_habit_review(_whr())
    assert "4/4 &#9733;" in html  # the perfect day carries the crown
    assert "2/4 &#9733;" not in html


def test_render_whr_day_initial_comes_from_the_date_not_the_position():
    """2026-06-09 is a Tuesday and 2026-06-10 a Wednesday -> "T", "W"."""
    html = hb._render_weekly_habit_review(_whr())
    labels = re.findall(r'font-size:8px;color:#94a3b8;margin-top:3px;">(.)</div>', html)
    assert labels == ["T", "W"]


def test_render_whr_unparseable_date_falls_back_to_a_positional_initial():
    """The fallback is position-based (M,T,W,...), so a window that does not
    start on a Monday is mislabeled. Latent — the strptime path wins for any
    real record."""
    whr = _whr(daily=[{"date": "", "t0_done": 1, "t0_total": 2, "t0_pct": 0.5, "perfect": False, "missed": []}])
    html = hb._render_weekly_habit_review(whr)
    assert 'margin-top:3px;">M</div>' in html


def test_render_whr_zero_days_does_not_divide_by_zero():
    html = hb._render_weekly_habit_review(_whr(days=0, daily=[], perfect_days=0, t0_habits=[]))
    assert "perfect days (0%)" in html


def test_render_whr_a_zero_percent_day_draws_the_same_bar_as_a_low_one():
    """`pct_bar = max(8, int(pct * 60))` floors every day at 8px.

    0% and 13% are visually identical. Cosmetic, but the bar row is the reader's
    at-a-glance summary of the week.
    """
    zero = _whr(daily=[{"date": "2026-06-10", "t0_done": 0, "t0_total": 4, "t0_pct": 0.0, "perfect": False, "missed": []}])
    low = _whr(daily=[{"date": "2026-06-10", "t0_done": 0, "t0_total": 4, "t0_pct": 0.13, "perfect": False, "missed": []}])
    assert "height:8px;background:#ef4444" in hb._render_weekly_habit_review(zero)
    assert "height:8px;background:#ef4444" in hb._render_weekly_habit_review(low)


def test_render_whr_tier1_line_absent_when_the_average_is():
    assert "Tier 1 avg" not in hb._render_weekly_habit_review(_whr(avg_t1_pct=None))
    # int(0.8 * 100) = 80 -> >= 75 -> green
    assert "Tier 1 avg" in hb._render_weekly_habit_review(_whr(avg_t1_pct=0.8))


def test_render_whr_synergy_chips_sorted_best_first():
    html = hb._render_weekly_habit_review(_whr(synergy={"food": 0.4, "sleep": 0.9}))
    assert html.index("sleep 90%") < html.index("food 40%")


def test_render_whr_long_habit_name_is_truncated_at_32_chars():
    name = "A" * 40
    html = hb._render_weekly_habit_review(_whr(t0_habits=[{"name": name, "days_done": 1, "days_total": 2, "pct": 0.5}]))
    assert "A" * 32 + "…" in html
    assert "A" * 33 not in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:216 (and 227/271/298-299/322) _render_weekly_habit_review — "
        "percentages use `int(pct * 100)`, which TRUNCATES. `_compute_weekly_habit_review` line 135 "
        "converts the stored Decimal to a float, so 0.29 * 100 == 28.999999999999996 in IEEE-754 and "
        "the header renders '28% T0' for a 29% week (same for the per-habit rows, the perfect-day "
        "percentage, the synergy chips and the tier-1 line). Should be `round(pct * 100)`. Hurts "
        "Matthew: every percentage in Sunday's Weekly Habit Review is systematically biased low, "
        "by a full point wherever the float lands just under."
    ),
)
def test_render_whr_percentages_round_rather_than_truncate():
    # two measured days at 28% and 30% -> mean exactly 0.29
    recs = [_hs("2026-06-09", 28, 100, "0.28"), _hs("2026-06-10", 30, 100, "0.30")]
    whr = hb._compute_weekly_habit_review(recs, _profile())
    assert whr["avg_t0_pct"] == 0.29  # the compute layer is correct
    html = hb._render_weekly_habit_review(whr)
    assert '>29<span style="font-size:14px;">%</span> T0' in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:275/278 _render_weekly_habit_review — habit names are "
        "interpolated into the row markup with no escaping, and the 32-char truncation can also slice "
        "a multi-byte name mid-entity. Habit names come from `profile['habit_registry']` (config, "
        "S3-hosted), so this is not attacker-controlled today — but an ampersand or an angle bracket "
        "in a habit name silently corrupts the section for the one reader. Should escape via "
        "html.escape before interpolation. Same class as the AI-narrative sites in §12."
    ),
)
def test_render_whr_escapes_habit_names():
    html = hb._render_weekly_habit_review(_whr(t0_habits=[{"name": "Fish oil & <b>D3</b>", "days_done": 1, "days_total": 2, "pct": 0.5}]))
    assert "<b>D3</b>" not in html
    assert "&amp;" in html


# ══════════════════════════════════════════════════════════════════════════════
# §7 — _brief_header
# ══════════════════════════════════════════════════════════════════════════════


def _header(**over):
    kw = dict(
        brief_mode="standard",
        data=_data(),
        day_grade_score=None,
        grade="C",
        tldr_guidance=None,
        vacation_fund=None,
        banner_color="#1a1a2e",
        day_label="Wednesday, Jun 10",
    )
    kw.update(over)
    return hb._brief_header(**kw)


def test_header_opens_a_dark_scheme_document():
    html = _header()
    assert html.startswith("<!DOCTYPE html>")
    assert 'name="color-scheme" content="dark"' in html
    assert "Wednesday, Jun 10" in html


def test_header_day_grade_block_omitted_when_the_grade_is_unscored():
    """ADR-104: no day grade means no grade card — never a rendered 0/100."""
    assert "DAY GRADE" not in _header(day_grade_score=None)
    html = _header(day_grade_score=83, grade="B")
    assert "DAY GRADE" in html and "83/100" in html


def test_header_grade_colour_falls_back_for_an_unknown_letter():
    """`letter_grade` emits A+/A-/B+ ... — none of which are in the 5-key colour map."""
    assert "#94a3b8" in _header(day_grade_score=91, grade="A-")


def test_header_adaptive_mode_banners():
    assert "FLOURISHING MODE" in _header(brief_mode="flourishing")
    assert "SUPPORT MODE" in _header(brief_mode="struggling")
    assert "MODE —" not in _header(brief_mode="standard")


def test_header_travel_banner_renders_destination_and_jet_lag_protocol():
    travel = {"destination": "Tokyo", "country": "Japan", "timezone": "Asia/Tokyo", "tz_offset": 9, "direction": "east"}
    html = _header(data=_data(travel_active=travel))
    assert "TRAVELING: Tokyo, Japan" in html
    assert "Asia/Tokyo, UTC+9" in html
    assert "Jet lag protocol" in html and "Morning sunlight ASAP" in html


def test_header_small_timezone_shift_gets_no_jet_lag_note():
    # abs(2) < 5 -> no protocol line
    travel = {"destination": "Denver", "tz_offset": 2, "direction": "east"}
    assert "Jet lag protocol" not in _header(data=_data(travel_active=travel))


def test_header_vacation_fund_needs_both_halves_or_renders_nothing():
    """A partial fund record is dropped silently rather than shown half-empty."""
    assert "Vacation fund" not in _header(vacation_fund={"total_usd": 120})
    html = _header(vacation_fund={"total_usd": 1234.4, "total_miles": 1234.44})
    # f"${1234.4:,.0f}" -> "$1,234"; f"{1234.44:,.1f}" -> "1,234.4"
    assert "$1,234" in html and "1,234.4 mi" in html


def test_header_vacation_fund_failure_degrades_to_a_section_error():
    """The one block in this function that IS guarded — contrast the travel test below."""
    html = _header(vacation_fund={"total_usd": "not-a-number", "total_miles": 1.0})
    assert "Vacation Fund section unavailable" in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:458-480 _brief_header — the travel banner is the ONLY "
        "section in the whole renderer that runs outside a try/except. `abs(tz_offset)` on line 468 "
        "raises TypeError for a trip row whose tz_offset_hours is null or a string, and the exception "
        "propagates out of _brief_header, out of build_html (which has no guard of its own), and "
        "aborts the entire email. The vestigial `try: pass  # travel already handled above` on lines "
        "482-485 shows the guard was meant to wrap this block and does not. Should degrade to "
        "_section_error_html like every other section. Hurts Matthew: one malformed manually-entered "
        "TRIP# row and there is no morning brief at all."
    ),
)
def test_header_a_malformed_trip_row_degrades_instead_of_killing_the_brief():
    travel = {"destination": "Tokyo", "timezone": "Asia/Tokyo", "tz_offset": None, "direction": "east"}
    html = hb.build_html(**_build_kwargs(data=_data(travel_active=travel)))
    assert "Travel section unavailable" in html


def test_header_travel_crash_currently_propagates_out_of_build_html():
    """The live behavior the xfail above describes, pinned so it cannot get worse."""
    travel = {"destination": "Tokyo", "timezone": "Asia/Tokyo", "tz_offset": None, "direction": "east"}
    with pytest.raises(TypeError):
        hb.build_html(**_build_kwargs(data=_data(travel_active=travel)))


# ══════════════════════════════════════════════════════════════════════════════
# §8 — _brief_character
# ══════════════════════════════════════════════════════════════════════════════

PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]


def _sheet(**over):
    cs = {
        "character_level": 21,
        "character_tier": "Momentum",
        "character_tier_emoji": "⚡",
        "character_xp": 4200,
    }
    for p in PILLARS:
        cs["pillar_" + p] = {"level": 10, "tier": "Foundation"}
    cs.update(over)
    return cs


def test_character_absent_sheet_renders_nothing():
    assert hb._brief_character(None, [], []) == ""


def test_character_level_and_tier_progress():
    html = hb._brief_character(_sheet(), [], [])
    # ((21 - 1) % 20) + 1 = 1 -> "Level 1/20 in Momentum tier"
    assert "Level 1/20 in Momentum tier" in html
    assert "⚡ Level 21 — Momentum" in html
    assert "4200 total XP" in html


def test_character_unknown_tier_falls_back_to_the_foundation_palette():
    html = hb._brief_character(_sheet(character_tier="Transcendent"), [], [])
    assert "#78716c" in html and "background:#1c1917" in html


def test_character_renders_one_bar_per_pillar():
    html = hb._brief_character(_sheet(), [], [])
    assert html.count("border-radius:2px;height:32px;width:16px") == len(PILLARS)


def test_character_level_event_variants():
    events = [
        {"type": "character_level_up", "old_level": 20, "new_level": 21},
        {"type": "pillar_tier_up", "pillar": "sleep", "old_tier": "Foundation", "new_tier": "Momentum"},
        {"type": "pillar_level_up", "pillar": "mind", "old_level": 8, "new_level": 9},
        {"type": "pillar_level_down", "pillar": "mind", "old_level": 9, "new_level": 8},
    ]
    html = hb._brief_character(_sheet(level_events=events), [], [])
    assert "Character Level 20 → 21" in html
    assert "Sleep Tier: Foundation → Momentum" in html
    assert "↑ Mind Level 8 → 9" in html
    assert "↓ Mind Level 9 → 8" in html


def test_character_a_level_event_from_zero_loses_its_old_value():
    """`ev.get("old_level") or ev.get("old_tier", "")` — 0 is falsy, so a
    level-0 -> level-1 event renders "Level  → 1" with a blank."""
    html = hb._brief_character(_sheet(level_events=[{"type": "pillar_level_up", "pillar": "mind", "old_level": 0, "new_level": 1}]), [], [])
    assert "Mind Level  → 1" in html


def test_character_rewards_and_protocol_recs_render():
    html = hb._brief_character(
        _sheet(),
        [{"pillar": "sleep", "dropped": True, "protocols": [{"name": "No screens after 21:00"}, "Magnesium"]}],
        [{"title": "New shoes", "description": "30 workouts logged"}],
    )
    assert "REWARD UNLOCKED: New shoes" in html and "30 workouts logged" in html
    assert "PROTOCOL RECOMMENDATIONS" in html
    assert "No screens after 21:00" in html and "Magnesium" in html
    assert "↓ Sleep:" in html


def test_character_a_malformed_sheet_degrades_to_a_section_error():
    html = hb._brief_character({"character_level": "twenty-one", "character_tier": "Momentum"}, [], [])
    assert "Character Sheet section unavailable" in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:584-586 _brief_character — `pd.get('level', 1) if pd else 1` "
        "renders a pillar the character engine has never scored as a factual 'Level 1' with a drawn "
        "bar, indistinguishable from a genuinely level-1 pillar. ADR-104 says absence must render as "
        "absence (an em dash / greyed bar). Hurts Matthew: after a cycle reset every unscored pillar "
        "reads as a real level-1 score in the brief's headline character block."
    ),
)
def test_character_an_unscored_pillar_is_not_reported_as_level_1():
    sheet = _sheet()
    del sheet["pillar_mind"]
    html = hb._brief_character(sheet, [], [])
    # six scored pillars at level 10, one absent -> six "10" labels and no fabricated "1"
    assert html.count('font-size:8px;margin:0;">1</p>') == 0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:657 _brief_character — `eff.get('description', '')` is a "
        "bare expression whose value is discarded; the active-effect description is read and thrown "
        "away, so only the emoji + name ever reach the reader. Should either render the description "
        "or stop reading it. Hurts Matthew: the character engine writes an explanation for every "
        "active effect and none of it is ever shown."
    ),
)
def test_character_active_effect_descriptions_reach_the_reader():
    effects = [{"name": "Sleep Drag", "emoji": "😵", "description": "3 nights under 6h — recovery penalty"}]
    html = hb._brief_character(_sheet(active_effects=effects), [], [])
    assert "Sleep Drag" in html  # the name does render
    assert "recovery penalty" in html


# ══════════════════════════════════════════════════════════════════════════════
# §9 — _brief_scorecards
# ══════════════════════════════════════════════════════════════════════════════


def _scorecards(**over):
    kw = dict(
        component_details={},
        component_scores={},
        data=_data(),
        mvp_streak=0,
        profile=_profile(),
        readiness_colour="gray",
        vice_streaks=None,
    )
    kw.update(over)
    return hb._brief_scorecards(**kw)


def test_scorecard_renders_a_tile_for_every_registered_component_scorer():
    """The tile set is DERIVED from health.scoring_engine.COMPONENT_SCORERS.

    A ninth scorer added to the engine without a tile here would leave its score
    computed, stored, and invisible — exactly the silent-dark class. Each key is
    given a distinct value so a mis-wired tile shows up as a missing number.
    """
    scores = {name: 30 + i for i, name in enumerate(sorted(COMPONENT_SCORERS))}
    html = _scorecards(component_scores=scores)
    for name, val in scores.items():
        assert f">{val}</p>" in html, f"component {name} (score {val}) never reached the scorecard"


def test_scorecard_absent_component_renders_an_em_dash_not_a_zero():
    """ADR-104: an unscorable component is blank, never a factual 0."""
    html = _scorecards(component_scores={"sleep_quality": None})
    assert ">—</p>" in html
    assert ">0</p>" not in html


def test_scorecard_a_genuine_zero_renders_as_zero():
    html = _scorecards(component_scores={"sleep_quality": 0})
    assert ">0</p>" in html


@pytest.mark.parametrize("score,colour", [(80, "#22c55e"), (79, "#f59e0b"), (60, "#f59e0b"), (59, "#ef4444")])
def test_scorecard_colour_bands(score, colour):
    html = _scorecards(component_scores={"sleep_quality": score})
    assert colour in html


def test_scorecard_habit_tier_breakdown_and_vice_streaks():
    details = {"habits_mvp": {"tier0": {"done": 5, "total": 7}, "tier1": {"done": 2, "total": 4}}}
    html = _scorecards(component_details=details, vice_streaks={"Weed": 12, "Porn": 0})
    assert "T0 (non-neg): 5/7" in html and "T1 (high): 2/4" in html
    assert "Weed: 12d streak avoided" in html
    assert "Porn" not in html  # a 0-day streak is not a streak


def test_scorecard_sleep_architecture_numbers():
    sleep = {"sleep_duration_hours": 7.62, "sleep_score": 84.4, "sleep_efficiency_pct": 91.6, "deep_pct": 21.4, "rem_pct": 18.6}
    html = _scorecards(data=_data(sleep=sleep))
    assert "SLEEP ARCHITECTURE" in html
    assert ">7.6h</p>" in html  # round(7.62, 1)
    assert ">84</p>" in html  # round(84.4)
    assert ">92%</p>" in html  # round(91.6)
    assert ">21%</p>" in html and "#22c55e" in html  # deep >= 20 -> green
    assert ">19%</p>" in html  # round(18.6) = 19; below 20 -> amber


def test_scorecard_hrv_line_renders_with_the_trend():
    data = _data(hrv={"hrv_7d": 62, "hrv_30d": 58}, whoop={"hrv": 60.4})
    html = _scorecards(data=data)
    assert "📡 HRV: " in html and "60ms yesterday" in html
    assert "trending up" in html


def test_essential_seven_derives_its_rows_from_the_habit_registry():
    reg = {
        "Sleep 7h": {"tier": 0, "status": "active"},
        "Log food": {"tier": 0, "status": "active"},
        "Read": {"tier": 1, "status": "active"},
        "Old habit": {"tier": 0, "status": "archived"},
    }
    details = {"habits_mvp": {"tier_status": {0: {"Sleep 7h": True, "Log food": False}}}}
    html = _scorecards(component_details=details, profile=_profile(habit_registry=reg), mvp_streak=4)
    expected = {n for n, m in reg.items() if m.get("tier") == 0 and m.get("status") == "active"}
    for name in expected:
        assert name in html
    assert "Read" not in html and "Old habit" not in html
    assert "4d streak" in html
    # done_count 1 of 2 -> round(1/2*100) = 50
    assert "1/2 complete" in html and "width:50%" in html


def test_essential_seven_falls_back_to_mvp_habits_when_the_registry_is_empty():
    details = {"habits_mvp": {"tier_status": {0: {}}}}
    html = _scorecards(component_details=details, profile=_profile(mvp_habits=["Walk", "Water"]))
    assert "Walk" in html and "Water" in html


def test_essential_seven_reads_both_int_and_string_tier_keys():
    """DynamoDB coerces map keys to strings; scoring_engine builds them as ints.

    Both shapes must resolve — this is the one place in the module that already
    defends the round trip, and it is pinned so the defense is not "simplified"
    away.
    """
    reg = {"Sleep 7h": {"tier": 0, "status": "active"}}
    prof = _profile(habit_registry=reg)
    in_memory = _scorecards(component_details={"habits_mvp": {"tier_status": {0: {"Sleep 7h": True}}}}, profile=prof)
    from_ddb = _scorecards(component_details={"habits_mvp": {"tier_status": {"0": {"Sleep 7h": True}}}}, profile=prof)
    assert "&#10003;" in in_memory  # check mark
    assert "&#10003;" in from_ddb
    assert "1/1 complete" in in_memory and "1/1 complete" in from_ddb


def test_readiness_signal_labels():
    for colour, label in [("green", "GO"), ("yellow", "MODERATE"), ("red", "EASY DAY"), ("gray", "NO DATA")]:
        assert label in _scorecards(readiness_colour=colour)


def test_readiness_unknown_colour_degrades_to_no_data():
    html = _scorecards(readiness_colour="chartreuse")
    assert ">—</p>" in html  # unknown label falls back to an em dash
    assert "⚪" in html


def test_readiness_vitals_row():
    data = _data(whoop={"recovery_score": 68.4, "strain": 12.34, "resting_heart_rate": 57.6})
    html = _scorecards(data=data)
    assert ">68%</p>" in html  # round(68.4)
    assert ">12.3</p>" in html  # round(12.34, 1)
    assert ">58 bpm</p>" in html  # round(57.6)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:874/894 _brief_scorecards — the Essential Seven treats a "
        "habit ABSENT from tier_status[0] as a miss (`tier0_status.get(h_name, False)`), renders it "
        "with an ✗, and counts it in the 'n/7 complete' denominator. scoring_engine omits a habit "
        "that was not applicable that day (weekday-scoped habit on a weekend, post_training habit "
        "with no workout) rather than marking it False. ADR-104: not-applicable must be visually "
        "distinct from missed. Hurts Matthew: the above-the-fold section of every weekend brief "
        "shows habits he was never expected to do as failures, and understates the completion bar."
    ),
)
def test_essential_seven_distinguishes_not_applicable_from_missed():
    reg = {"Sleep 7h": {"tier": 0, "status": "active"}, "Weekday lift": {"tier": 0, "status": "active"}}
    # Saturday: only Sleep 7h was evaluated; Weekday lift is absent, not False.
    details = {"habits_mvp": {"tier_status": {0: {"Sleep 7h": True}}}}
    html = _scorecards(component_details=details, profile=_profile(habit_registry=reg))
    assert "1/1 complete" in html  # honest; currently renders "1/2 complete"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:830-839 _brief_scorecards — the HRV line is wrapped in a "
        "bare `except Exception: pass`. `data['hrv']` is a hard subscript, so any packet without the "
        "'hrv' key (or with hrv=None) makes the whole HRV readout vanish with no placeholder, no log "
        "line and no _section_error_html. Should use .get() and render 'no trend data', or surface "
        "the failure. Hurts Matthew: HRV silently disappearing from the scorecard is "
        "indistinguishable from a quiet day."
    ),
)
def test_scorecard_missing_hrv_block_is_reported_not_swallowed():
    data = {"date": DATE, "whoop": {"hrv": 60.4}}  # no "hrv" key at all
    html = _scorecards(data=data)
    assert "📡 HRV:" in html or "section unavailable" in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:806-818 _brief_scorecards — the sleep-architecture cells use "
        "truthiness (`str(round(deep_pct)) + '%' if deep_pct else '—'`), so a MEASURED 0 renders as "
        "the same em dash as an unmeasured night. ADR-104 cuts both ways: absence must not look like "
        "0, and 0 must not look like absence. Hurts Matthew: a night Whoop recorded genuinely zero "
        "deep sleep — clinically the most alarming reading in the block — is displayed as 'no data'."
    ),
)
def test_scorecard_a_measured_zero_deep_percentage_is_shown_as_zero():
    sleep = {"sleep_duration_hours": 6.0, "sleep_score": 40.0, "deep_pct": 0.0, "rem_pct": 12.0}
    html = _scorecards(data=_data(sleep=sleep))
    assert ">0%</p>" in html


# ══════════════════════════════════════════════════════════════════════════════
# §10 — _brief_training_body
# ══════════════════════════════════════════════════════════════════════════════


def _training(**over):
    kw = dict(data=_data(), full_streak=0, mvp_streak=0, profile=_profile(), training_nutrition=None)
    kw.update(over)
    return hb._brief_training_body(**kw)


def test_training_no_data_says_so():
    html = _training()
    assert "No training data for yesterday." in html


def test_training_garmin_fallback_uses_an_em_dash_for_missing_steps():
    """ADR-104 via fmt_num: a garmin record with no step count is not "0 steps"."""
    assert "Steps: —" in _training(data=_data(garmin={"resting_hr": 55}))
    assert "Steps: 9,200" in _training(data=_data(garmin={"steps": 9200}))


def test_training_strava_activity_stats():
    act = {
        "name": "Morning Walk",
        "sport_type": "Walk",
        "moving_time_seconds": 2730,
        "distance_miles": 3.24,
        "average_heartrate": 111.6,
        "elevation_gain_ft": 88.4,
    }
    html = _training(data=_data(strava={"activities": [act]}))
    assert "Morning Walk" in html and ">Walk</p>" in html
    assert "46 min" in html  # round(2730 / 60) = 45.5 -> banker's -> 46
    assert "3.2 mi" in html  # round(3.24, 1)
    assert "avg HR 112" in html  # round(111.6)
    assert "88ft gain" in html  # round(88.4)


def test_training_tsb_bands():
    # tsb > 10 -> Fresh; > 0 -> Optimal; > -20 -> Tired; else Overreached
    assert "(Fresh)" in _training(data=_data(tsb=12.0))
    assert "(Optimal)" in _training(data=_data(tsb=3.0))
    assert "(Tired)" in _training(data=_data(tsb=-8.0))
    assert "(Overreached)" in _training(data=_data(tsb=-25.0))
    assert "TSB: " in _training(data=_data(tsb=0.0))  # a zero TSB still renders


def test_training_coach_commentary_renders():
    html = _training(training_nutrition={"training": "You backed off at the right time."})
    assert "COACH ANALYSIS" in html and "backed off at the right time" in html


def test_nutrition_absent_says_nothing_was_logged():
    """ADR-104: no MacroFactor record renders a sentence, not a grid of zeros."""
    html = _training()
    assert "No nutrition data logged yesterday." in html
    assert "Calories" not in html


def test_nutrition_macro_grid_arithmetic():
    mf = {"total_calories_kcal": 1480, "total_protein_g": 185.4, "total_fat_g": 55.2, "total_carbs_g": 120.6, "total_fiber_g": 31.4}
    html = _training(data=_data(macrofactor=mf))
    assert ">1,480</p>" in html  # fmt_num
    assert "Calories/1500" in html  # the target ships with the number
    assert ">185g</p>" in html  # round(185.4)
    assert "Protein/190g" in html
    assert ">55g</p>" in html and ">121g</p>" in html  # round(55.2), round(120.6)
    assert "Fiber: 31g" in html
    # cal_pct = round(1480 / 1500 * 100) = round(98.67) = 99 -> inside 85..110 -> green
    # prot_pct = round(185.4 / 190 * 100) = round(97.58) = 98 -> >= 95 -> green
    assert html.count("#22c55e") >= 2


def test_nutrition_zero_calories_is_rendered_not_hidden():
    """`if cals is not None` — a genuinely-zero fast day shows 0, correctly."""
    html = _training(data=_data(macrofactor={"total_calories_kcal": 0}))
    assert ">0</p>" in html
    assert "No nutrition data logged yesterday." not in html


def test_nutrition_missing_protein_colours_the_tile_red_while_showing_an_em_dash():
    """`prot_pct` falls to 0 when protein is absent, so the "—" tile is painted
    as if the target were badly missed. Cosmetic, but it reads as a judgement on
    a number nobody measured."""
    html = _training(data=_data(macrofactor={"total_calories_kcal": 1480}))
    assert "#ef4444" in html


def test_habits_deep_dive_groups_by_tier_from_the_registry():
    reg = {
        "Sleep 7h": {"tier": 0, "status": "active", "why_matthew": "the whole engine runs on this"},
        "Read": {"tier": 1, "status": "active"},
        "Stretch": {"tier": 2, "status": "active"},
        "Old": {"tier": 0, "status": "archived"},
    }
    data = _data(habitify={"habits": {"Sleep 7h": 1, "Read": 0}})
    html = _training(data=data, profile=_profile(habit_registry=reg))
    assert "TIER 0 — NON-NEGOTIABLE" in html
    assert "TIER 1 — HIGH PRIORITY" in html
    assert "TIER 2 — GOOD TO DO" in html
    assert "Old" not in html
    assert "✅" in html and "❌" in html
    # the "why" line only appears for a missed habit
    assert "the whole engine runs on this" not in html


def test_habits_deep_dive_shows_the_why_only_on_a_miss():
    reg = {"Sleep 7h": {"tier": 0, "status": "active", "why_matthew": "the whole engine runs on this"}}
    html = _training(data=_data(habitify={"habits": {"Sleep 7h": 0}}), profile=_profile(habit_registry=reg))
    assert "the whole engine runs on this" in html


def test_habits_deep_dive_counts_an_untracked_habit_as_missed():
    """`h_map.get(h_name, 0)` — a habit Habitify never reported is an ❌.

    Same ADR-104 class as the Essential Seven xfail; pinned here because this is
    a separate code path with a separate default.
    """
    reg = {"Sleep 7h": {"tier": 0, "status": "active"}}
    html = _training(data=_data(habitify={"habits": {}}), profile=_profile(habit_registry=reg))
    assert "❌" in html


def test_habits_synergy_alert_needs_half_missed_and_at_least_three_in_the_group():
    reg = {
        "A": {"tier": 0, "status": "active", "synergy_group": "sleep_stack"},
        "B": {"tier": 0, "status": "active", "synergy_group": "sleep_stack"},
        "C": {"tier": 0, "status": "active", "synergy_group": "sleep_stack"},
    }
    # 2 of 3 missed -> 2 >= 3 * 0.5 and 3 >= 3 -> alert
    html = _training(data=_data(habitify={"habits": {"A": 1, "B": 0, "C": 0}}), profile=_profile(habit_registry=reg))
    assert "Synergy alert: sleep_stack" in html
    # 1 of 3 missed -> 1 < 1.5 -> no alert
    html = _training(data=_data(habitify={"habits": {"A": 1, "B": 1, "C": 0}}), profile=_profile(habit_registry=reg))
    assert "Synergy alert" not in html


def test_habits_legacy_map_path_when_no_registry():
    html = _training(data=_data(habitify={"habits": {"A": 1, "B": 0, "C": 1}}))
    assert "2 / 3 habits completed" in html


def test_supplements_grouped_by_timing():
    supps = {
        "supplements": [
            {"name": "Creatine", "dose": 5, "unit": "g", "timing": "morning_fasted"},
            {"name": "Magnesium", "timing": "evening_sleep"},
        ]
    }
    html = _training(data=_data(supplements_today=supps))
    assert "MORNING (FASTED)" in html
    assert "EVENING / SLEEP" in html and "• Magnesium" in html
    # lambdas/content/html_builder.py:1256 — `(" — " + dose + " " + unit).strip()` strips the
    # LEADING space it just added, so the name and the dash collide: "Creatine— 5 g".
    # Cosmetic, but it is in every brief that lists a dosed supplement.
    assert "• Creatine— 5 g" in html
    assert "• Creatine — 5 g" not in html


def test_supplements_absent_says_so():
    assert "No supplement data for yesterday." in _training()
    assert "No supplement data logged." in _training(data=_data(supplements_today={"supplements": []}))


def test_cgm_spotlight_numbers():
    apple = {
        "blood_glucose_avg": 96.4,
        "blood_glucose_time_in_range_pct": 88.2,
        "blood_glucose_std_dev": 12.36,
        "blood_glucose_min": 70.4,
        "blood_glucose_max": 148.0,
    }
    html = _training(data=_data(apple=apple))
    assert ">96</p>" in html  # round(96.4)
    assert ">88%</p>" in html  # round(88.2)
    assert ">70</p>" in html  # round(70.4)
    assert ">12.4</p>" in html  # round(12.36, 1)
    # min 70.4 < 72 -> hypo callout, with the number restated
    assert "Hypoglycemia signal: overnight low 70 mg/dL" in html


def test_cgm_absent_says_so():
    assert "No glucose data for yesterday." in _training()


def test_cgm_seven_day_trend_needs_three_days():
    two = [{"blood_glucose_avg": 95}, {"blood_glucose_avg": 105}]
    assert "7-day avg" not in _training(data=_data(apple={"blood_glucose_avg": 96}, apple_7d=two))
    three = two + [{"blood_glucose_avg": 100}]
    html = _training(data=_data(apple={"blood_glucose_avg": 96}, apple_7d=three))
    # avg([95, 105, 100]) = 100.0 -> round -> 100
    assert "7-day avg: " in html and ">100 mg/dL<" in html


def test_gait_absent_says_so():
    assert "No gait data available." in _training()


def test_gait_numbers_and_bands():
    apple = {"walking_speed_mph": 3.14, "walking_step_length_in": 28.36, "walking_asymmetry_pct": 2.44, "walking_double_support_pct": 27.66}
    html = _training(data=_data(apple=apple))
    assert ">3.14 mph</p>" in html  # round(3.14, 2); >= 3.0 -> green
    assert '>28.4"</p>' in html  # round(28.36, 1); >= 27 -> green
    assert ">2.4%</p>" in html  # round(2.44, 1); < 3 -> green
    assert ">27.7%</p>" in html  # round(27.66, 1)


def test_habit_streaks_absent_says_start_today():
    assert "No active streak. Start today." in _training()


def test_habit_streaks_render_both_counters():
    html = _training(mvp_streak=12, full_streak=3)
    assert "T0 Streak (days)" in html and ">12</p>" in html
    assert "T0+T1 Streak" in html and ">3</p>" in html


def test_acwr_renders_when_given_the_field_names_this_module_reads():
    """Control for the mismatch xfail below — the rendering logic itself works."""
    cm = {"acwr": 1.42, "zone": "high", "alert": True, "alert_reason": "Acute load 42% above chronic."}
    html = _training(data=_data(computed_metrics=cm))
    assert "ACWR: " in html and ">1.42" in html
    assert "— HIGH" in html
    assert "TRAINING LOAD ALERT" in html
    assert "Acute load 42% above chronic." in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:1078-1080 _brief_training_body — reads "
        "computed_metrics['zone'], ['alert'] and ['alert_reason']. "
        "lambdas/compute/acwr_compute_lambda.py:286-288 (_write_acwr) writes them onto the SAME "
        "computed_metrics record as 'acwr_zone', 'acwr_alert' and 'acwr_alert_reason' — only the bare "
        "'acwr' key (line 1077) matches. The sibling reader "
        "lambdas/ai/ai_context.py:1059-1061 uses the acwr_-prefixed names, confirming the writer's "
        "contract. Consequence: acwr_alert is ALWAYS False, so the TRAINING LOAD ALERT box has never "
        "rendered; the zone label is always blank; and the ACWR colour can never go red-for-alert. "
        "Hurts Matthew: an injury-risk warning computed daily and displayed never — a permanently "
        "dark safety feature with no error anywhere."
    ),
)
def test_acwr_alert_renders_for_a_record_written_by_acwr_compute_lambda():
    cm = {
        "acwr": Decimal("1.42"),
        "acwr_zone": "high",
        "acwr_alert": True,
        "acwr_alert_reason": "Acute load 42% above chronic — elevated injury risk.",
        "acute_load_7d": Decimal("512.0"),
        "chronic_load_28d": Decimal("360.0"),
    }
    html = _training(data=_data(computed_metrics=cm))
    assert "ACWR: " in html  # the number does render
    assert "— HIGH" in html
    assert "TRAINING LOAD ALERT" in html
    assert "elevated injury risk" in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:1021-1022 + 1047-1051 _brief_training_body — total_vol and "
        "total_sets are read off the DAY aggregate `mf_workouts` but rendered INSIDE the per-workout "
        "loop, so on a two-a-day the same day total is printed under each workout. "
        "lambdas/emails/daily_brief_lambda.py:471-475 (fetch_hevy_workouts) confirms there is exactly "
        "one total for the whole day and its docstring says 'possibly several a day'. Should either "
        "hoist the totals out of the loop or aggregate per workout. Hurts Matthew: a two-session day "
        "reads as ~2x the volume actually lifted."
    ),
)
def test_hevy_volume_is_not_the_day_total_repeated_under_every_workout():
    mf_workouts = {
        "workouts": [
            {"workout_name": "AM Push", "exercises": [{"exercise_name": "Bench", "sets": [{"reps": 8, "weight_lbs": 135}]}]},
            {"workout_name": "PM Pull", "exercises": [{"exercise_name": "Row", "sets": [{"reps": 8, "weight_lbs": 135}]}]},
        ],
        "total_volume_lbs": 2160.0,  # 8*135 + 8*135 for the whole day
        "total_sets": 2,
    }
    html = _training(data=_data(mf_workouts=mf_workouts))
    assert html.count("Volume: 2,160 lbs") == 1


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:1279 _brief_training_body — "
        "`safe_float(apple, 'blood_glucose_max')` is a bare expression whose value is discarded. "
        "health_auto_export_lambda writes blood_glucose_max on every CGM day and the CGM Spotlight "
        "reads it and drops it, so the reader sees the overnight LOW and the SD but never the peak. "
        "Should render it beside the low (the hypo callout has a hyper counterpart) or stop reading "
        "it. Hurts Matthew: the single most actionable CGM number of the day is computed, stored, "
        "read, and thrown away."
    ),
)
def test_cgm_spotlight_shows_the_daily_maximum_it_reads():
    apple = {"blood_glucose_avg": 96.0, "blood_glucose_min": 70.0, "blood_glucose_max": 187.0}
    html = _training(data=_data(apple=apple))
    assert "187" in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:1249-1257 _brief_training_body — the supplement render loop "
        "iterates the three keys of the hardcoded `timing_labels` map, not the groups actually "
        "present in `by_timing`. Any supplement whose `timing` is anything else (including the "
        "module's own default of 'other' on line 1242) is collected into by_timing and then never "
        "printed. Should iterate the derived groups, labelling unknown ones. Hurts Matthew: a "
        "supplement he took is silently absent from the brief's SUPPLEMENTS list with no 'and N more'."
    ),
)
def test_supplements_with_an_unlisted_timing_are_still_shown():
    supps = {"supplements": [{"name": "Creatine", "timing": "morning_fasted"}, {"name": "Ashwagandha", "timing": "pre_bed"}]}
    html = _training(data=_data(supplements_today=supps))
    assert "Creatine" in html
    assert "Ashwagandha" in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:1313-1321 _brief_training_body — the CGM '7-day avg' line "
        "ships a mean with no n, and the underlying window is whatever `apple_7d` happened to "
        "contain (the guard is only `len >= 3`). ADR-105 requires the n beside every statistical "
        "claim, and #1917 requires a window-named figure to span its window or carry no value. "
        "Hurts Matthew: a '7-day avg' computed from 3 days reads as a full week."
    ),
)
def test_cgm_seven_day_average_ships_its_n():
    apple_7d = [{"blood_glucose_avg": 95}, {"blood_glucose_avg": 105}, {"blood_glucose_avg": 100}]
    html = _training(data=_data(apple={"blood_glucose_avg": 96}, apple_7d=apple_7d))
    assert "n=3" in html or "3 days" in html or "3-day" in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:982 _brief_training_body — "
        "`dur_min = round((act.get('moving_time_seconds') or 0) / 60)` renders an activity whose "
        "duration Strava did not report as a factual '0 min'. ADR-104: absent is an em dash. Hurts "
        "Matthew: a logged workout appears in the Training Report claiming zero minutes."
    ),
)
def test_training_activity_without_a_duration_is_not_reported_as_zero_minutes():
    act = {"name": "Hike", "sport_type": "Hike", "distance_miles": 4.0}
    html = _training(data=_data(strava={"activities": [act]}))
    assert "0 min" not in html


# ══════════════════════════════════════════════════════════════════════════════
# §11 — _brief_lifestyle
# ══════════════════════════════════════════════════════════════════════════════


def _lifestyle(**over):
    kw = dict(data=_data(), profile=_profile(), tldr_guidance=None)
    kw.update(over)
    return hb._brief_lifestyle(**kw)


def test_weather_hi_lo_renders():
    html = _lifestyle(data=_data(weather_yesterday={"temp_high_f": 78.4, "temp_low_f": 55.6}))
    assert "WEATHER CONTEXT" in html
    assert ">78°/56°F</p>" in html  # round(78.4), round(55.6)


def test_weather_absent_renders_no_card_at_all():
    assert "WEATHER CONTEXT" not in _lifestyle()


def test_blood_pressure_numbers_and_n():
    bp = {"systolic": 118.4, "diastolic": 76.6, "class": "Elevated", "class_color": "#f59e0b", "pulse": 62.4, "readings": 3}
    html = _lifestyle(data=_data(bp_data=bp))
    assert ">118/77</p>" in html  # round(118.4), round(76.6)
    assert "Elevated" in html and "AHA Class" in html
    assert ">62 bpm</p>" in html
    assert "3 readings avg" in html  # ADR-105: the n ships with the average


def test_blood_pressure_single_reading_shows_no_n():
    """A single reading is not an average, so no n is claimed. Correct as-is."""
    bp = {"systolic": 118, "diastolic": 76, "readings": 1}
    assert "readings avg" not in _lifestyle(data=_data(bp_data=bp))


def test_blood_pressure_malformed_row_degrades_to_a_section_error():
    """`round(None)` inside the section -> honest placeholder, not a dead card."""
    html = _lifestyle(data=_data(bp_data={"diastolic": 76}))
    assert "Blood Pressure section unavailable" in html


def test_task_load_bands():
    for overdue, label in [(31, "HIGH"), (16, "ELEVATED"), (6, "MODERATE"), (5, "CLEAR")]:
        html = _lifestyle(data=_data(todoist={"overdue_count": overdue, "completed_count": 1}))
        assert label in html, (overdue, label)


def test_task_load_top_projects():
    todoist = {"completed_count": 9, "completions_by_project": {"Platform": 5, "Home": 3, "Errands": 1, "Misc": 0}}
    html = _lifestyle(data=_data(todoist=todoist))
    assert "Platform</span> 5" in html and "Home</span> 3" in html and "Errands</span> 1" in html
    assert "Misc" not in html  # top-3 only


def test_weight_phase_progress_arithmetic():
    prof = _profile(journey_start_weight_lbs=311.0, goal_weight_lbs=185.0, weight_loss_phases=PHASES)
    html = _lifestyle(data=_data(latest_weight=280.0, week_ago_weight=282.4), profile=prof)
    assert ">280.0 lbs</p>" in html
    # total_to_lose = 311 - 185 = 126; lost = 311 - 280 = 31; round(31/126*100) = round(24.6) = 25
    assert "width:25%" in html and ">25% to goal</p>" in html
    # delta = round(280.0 - 282.4, 1) = -2.4 -> down -> green, minus sign
    assert "−2.4 lbs vs 7d ago" in html and "#22c55e" in html
    # 280 >= Phase 1's end_lbs of 280 -> Phase 1
    assert "Phase: <strong>Phase 1</strong>" in html and "target 280 lbs" in html


def test_weight_phase_a_gain_clamps_the_bar_at_zero():
    prof = _profile(journey_start_weight_lbs=311.0, goal_weight_lbs=185.0)
    html = _lifestyle(data=_data(latest_weight=315.0, week_ago_weight=312.0), profile=prof)
    assert "width:0%" in html and ">0% to goal</p>" in html
    # delta = +3.0 -> > 0.5 -> red
    assert "+3.0 lbs vs 7d ago" in html and "#ef4444" in html


def test_weight_phase_flat_week_is_amber_not_red():
    prof = _profile(journey_start_weight_lbs=311.0, goal_weight_lbs=185.0)
    html = _lifestyle(data=_data(latest_weight=300.0, week_ago_weight=299.7), profile=prof)
    # delta = round(300.0 - 299.7, 1) = 0.3 -> not < 0, not > 0.5 -> amber
    assert "+0.3 lbs vs 7d ago" in html and "#f59e0b" in html


def test_weight_phase_absent_weight_says_so():
    assert "No weight data recorded recently." in _lifestyle()


def test_guidance_items_render_in_order():
    html = _lifestyle(tldr_guidance={"guidance": ["Walk before noon.", "Protein at breakfast."]})
    assert "TODAY'S GUIDANCE" in html
    assert html.index("Walk before noon.") < html.index("Protein at breakfast.")


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:1417-1421 _brief_lifestyle — the WEATHER CONTEXT card reads "
        "'condition', 'precip_in', 'aqi', 'sunrise_local' and 'sunset_local'. "
        "lambdas/ingestion/weather_lambda.py:102-114 writes temp_high_f / temp_low_f / temp_avg_f / "
        "humidity_pct / precipitation_mm / wind_speed_max_mph / pressure_hpa / daylight_hours / "
        "sunshine_hours / uv_index_max — and strips None keys. Repo-wide, 'aqi', 'condition', "
        "'precip_in', 'sunrise_local' and 'sunset_local' appear ONLY on this read side: no writer "
        "produces any of them. Consequence: four of the card's five cells have never rendered, and "
        "the section is permanently a bare Hi/Lo. 'precip_in' is additionally a unit mismatch against "
        "the stored millimetres. Hurts Matthew: sunrise, precipitation, air quality and conditions — "
        "the context the section exists to give — are all dark."
    ),
)
def test_weather_card_renders_the_fields_the_weather_lambda_actually_writes():
    # exactly what weather_lambda.transform() puts in DynamoDB
    rec = {
        "source": "weather",
        "date": DATE,
        "temp_high_f": 78.0,
        "temp_low_f": 55.0,
        "temp_avg_f": 66.0,
        "humidity_pct": 41.0,
        "precipitation_mm": 5.1,
        "wind_speed_max_mph": 9.0,
        "daylight_hours": 14.2,
        "uv_index_max": 7.0,
    }
    html = _lifestyle(data=_data(weather_yesterday=rec))
    assert ">78°/55°F</p>" in html  # this part works
    assert "Precip" in html  # precipitation was measured and is nowhere in the card
    assert "Conditions" in html or "Sunrise" in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "lambdas/content/html_builder.py:1512-1515 _brief_lifestyle — "
        "`int(todoist.get('active_count', 0))` and siblings turn a missing count into a factual 0, "
        "and the load band is then derived from that fabricated 0 ('CLEAR'). todoist_lambda writes "
        "these keys only when it has them, and ingestion_validator.py:305 only requires "
        "`at_least_one_of` completed/active/overdue — so a partial record is an expected shape, not "
        "a corruption. ADR-104: absent must render as an em dash and must not drive a load verdict. "
        "Hurts Matthew: a partial Todoist sync reports '0 DONE YESTERDAY' and a green 'CLEAR' load "
        "signal on a day with 40 overdue tasks."
    ),
)
def test_task_load_missing_counts_are_not_reported_as_zero():
    html = _lifestyle(data=_data(todoist={"active_count": 120}))  # only one of the four keys present
    assert "CLEAR" not in html
    assert ">0</p>" not in html


# ══════════════════════════════════════════════════════════════════════════════
# §12 — _brief_journal_coaches
# ══════════════════════════════════════════════════════════════════════════════

V2_COACH_PARAMS = sorted(p for p in inspect.signature(hb.build_html).parameters if p.endswith("_coach_v2_text"))


def _coaches(**over):
    kw = dict(
        bod_insight=None,
        data=_data(),
        explorer_coach_v2_text=None,
        glucose_coach_v2_text=None,
        journal_coach_text=None,
        labs_coach_v2_text=None,
        mind_coach_v2_text=None,
        nutrition_coach_v2_text=None,
        physical_coach_v2_text=None,
        profile=_profile(),
        sleep_coach_v2_text=None,
        training_coach_v2_text=None,
        weekly_habit_review=None,
    )
    kw.update(over)
    return hb._brief_journal_coaches(**kw)


def test_the_v2_coach_roster_is_derived_from_the_build_html_signature():
    """Every `*_coach_v2_text` parameter must produce a visible section.

    The roster is growable (8 coaches today); deriving it from the signature
    means adding a ninth parameter without wiring a section fails here instead
    of shipping a coach whose analysis is computed and never displayed.
    """
    assert len(V2_COACH_PARAMS) == 8  # sanity: the derivation found the set
    for param in V2_COACH_PARAMS:
        marker = f"UNIQUE-COACH-MARKER-{param}"
        html = _coaches(**{param: marker})
        assert marker in html, f"{param} was accepted by build_html but never rendered"
        section_id = param.replace("_text", "")
        assert f"<!-- S:{section_id} -->" in html


def test_a_coach_narrative_is_split_into_paragraphs():
    html = _coaches(sleep_coach_v2_text="First paragraph.\n\nSecond paragraph.\n\n   \n\nThird.")
    assert html.count('color:#c7d2fe;font-size:13px;line-height:1.6;margin:0 0 8px 0;">') == 3  # the blank chunk is dropped


def test_absent_coach_text_renders_only_the_section_marker():
    html = _coaches()
    for param in V2_COACH_PARAMS:
        section_id = param.replace("_text", "")
        assert f"<!-- S:{section_id} -->" in html
    assert "INTELLIGENCE</p>" not in html  # no empty coach cards


def test_journal_coach_splits_reflection_from_tactic():
    html = _coaches(journal_coach_text="You wrote about the same thing twice. || Name it before bed.")
    assert '"You wrote about the same thing twice."' in html
    assert "TODAY'S TACTIC" in html and "Name it before bed." in html


def test_journal_coach_without_a_separator_renders_reflection_only():
    html = _coaches(journal_coach_text="Just the one thought.")
    assert "Just the one thought." in html
    assert "TODAY'S TACTIC" not in html


def test_journal_pulse_scores_and_inverted_stress_scale():
    journal = {"mood_avg": 4.2, "energy_avg": 2.8, "stress_avg": 4.4, "themes": ["work", "sleep"]}
    html = _coaches(data=_data(journal=journal))
    assert ">4.2/5</p>" in html and ">2.8/5</p>" in html and ">4.4/5</p>" in html
    # mood 4.2 >= 4 -> green; energy 2.8 < 3 -> red; stress 4.4 >= 4 -> red (inverted, correctly)
    assert html.count("#ef4444") == 2
    assert "Themes:" in html and "work, sleep" in html


def test_journal_pulse_omits_a_metric_nobody_scored():
    """ADR-104: `if j_val is not None` — a missing mood is absent, not 0/5."""
    html = _coaches(data=_data(journal={"energy_avg": 3.0}))
    assert ">3.0/5</p>" in html
    assert "Mood" not in html


def test_journal_themes_capped_at_five():
    themes = ["t1", "t2", "t3", "t4", "t5", "t6"]
    html = _coaches(data=_data(journal={"mood_avg": 3.0, "themes": themes}))
    assert "t5" in html and "t6" not in html


def test_board_of_directors_insight_renders():
    html = _coaches(bod_insight="Three weeks of the same trade-off. Pick one.")
    assert "BOARD OF DIRECTORS" in html
    assert "Three weeks of the same trade-off." in html


def test_board_confidence_badge_is_computed_from_the_wall_clock_not_the_brief_date():
    """The badge's n is `now() - journey_start_date`, so the same packet
    rendered for a different date produces the same badge.

    Pinned as a documented property: it means a brief regenerated months later
    carries a confidence badge for TODAY's data volume, not that day's.
    """
    a = _coaches(bod_insight="x", data=_data())
    b = _coaches(bod_insight="x", data={"date": "2025-01-01", "hrv": {}})
    # re.DOTALL matters: without it `.` skips newlines, so a multi-line HTML
    # comment survives the strip and the two renders compare unequal for a
    # reason that has nothing to do with the property under test. (CodeQL
    # py/bad-tag-filter flags the newline-blind form; this is a test-local
    # normaliser, not a sanitiser, but the correctness point stands.)
    strip = re.compile(r"<!--.*?-->", re.DOTALL)
    assert strip.sub("", a) == strip.sub("", b)


def test_anomaly_alerts_capped_at_three():
    alerts = [{"metric": f"m{i}", "message": f"msg{i}"} for i in range(5)]
    html = _coaches(data=_data(anomaly={"has_anomalies": True, "alerts": alerts}))
    assert "ANOMALY ALERT" in html
    assert "msg0" in html and "msg2" in html
    assert "msg3" not in html


def test_anomaly_alerts_require_the_has_anomalies_flag():
    """Alerts present but the flag absent -> nothing renders.

    A single missing boolean suppresses every alert; pinned because the flag and
    the list are written by the same producer and can drift apart.
    """
    alerts = [{"metric": "hrv", "message": "down 3 SD"}]
    assert "ANOMALY ALERT" not in _coaches(data=_data(anomaly={"alerts": alerts}))


def test_weekly_habit_review_is_appended_when_supplied():
    html = _coaches(weekly_habit_review=_whr())
    assert "Weekly Habit Review" in html


def test_weekly_habit_review_failure_degrades_to_a_section_error():
    html = _coaches(weekly_habit_review={"days": 2, "daily": [{"date": "x"}], "t0_habits": []})
    assert "Weekly Habit Review section unavailable" in html


@pytest.mark.xfail(
    strict=False,
    reason=(
        "html_builder interpolates every model-generated and third-party string straight into the "
        "email body with no escaping: the TL;DR (line 442), a guidance item (1643), the board insight "
        "(1858), every V2 coach paragraph (1744/1765/1786/1815), an anomaly message (1879), a journal "
        "theme (1704) and a Strava activity name (990). The coach/board/TL;DR strings are Bedrock "
        "output and the activity name is third-party API text, so a stray '<' or '&' silently "
        "corrupts the section and an emitted tag is rendered as markup by the mail client. Should "
        "route every interpolated value through html.escape. Hurts Matthew: a garbled or truncated "
        "section in the one email he reads daily, with no error to explain it."
    ),
)
@pytest.mark.parametrize(
    "kind",
    ["tldr", "guidance", "bod", "coach", "anomaly", "theme", "activity_name"],
)
def test_interpolated_strings_are_escaped(kind):
    payload = "<script>alert(1)</script> & more"
    if kind == "tldr":
        html = _header(tldr_guidance={"tldr": payload})
    elif kind == "guidance":
        html = _lifestyle(tldr_guidance={"guidance": [payload]})
    elif kind == "bod":
        html = _coaches(bod_insight=payload)
    elif kind == "coach":
        html = _coaches(sleep_coach_v2_text=payload)
    elif kind == "anomaly":
        html = _coaches(data=_data(anomaly={"has_anomalies": True, "alerts": [{"metric": "hrv", "message": payload}]}))
    elif kind == "theme":
        html = _coaches(data=_data(journal={"mood_avg": 3.0, "themes": [payload]}))
    else:
        html = _training(data=_data(strava={"activities": [{"name": payload, "moving_time_seconds": 60}]}))
    assert "<script>" not in html
    assert "&amp;" in html


# ══════════════════════════════════════════════════════════════════════════════
# §13 — _brief_footer
# ══════════════════════════════════════════════════════════════════════════════

FOOTER_SOURCES = [
    ("whoop", "Whoop"),
    ("strava", "Strava"),
    ("macrofactor", "MacroFactor"),
    ("apple", "Apple Health"),
    ("habitify", "Habitify"),
    ("garmin", "Garmin"),
    ("journal", "Notion"),
]


def test_footer_lists_only_the_sources_that_actually_reported():
    data = _data(whoop={"hrv": 60}, apple={"steps": 100})
    html = hb._brief_footer("", False, data, DATE)
    assert "Whoop &middot; Apple Health" in html
    for key, label in FOOTER_SOURCES:
        if key not in ("whoop", "apple"):
            assert label not in html


def test_footer_says_so_when_nothing_reported():
    """ADR-104 at the provenance line: no sources is stated, not implied."""
    assert "No data sources" in hb._brief_footer("", False, _data(), DATE)


def test_footer_every_known_source_can_be_listed():
    data = _data(**{k: {"x": 1} for k, _ in FOOTER_SOURCES})
    html = hb._brief_footer("", False, data, DATE)
    for _, label in FOOTER_SOURCES:
        assert label in html


def test_footer_stale_compute_banner_is_explicit():
    html = hb._brief_footer("is 3 days old", True, _data(), DATE)
    assert "Compute data is 3 days old" in html
    assert "some metrics may be estimated" in html


def test_footer_stale_compute_with_no_message_says_unavailable():
    assert "Compute data unavailable" in hb._brief_footer("", True, _data(), DATE)


def test_footer_budget_headroom_line_is_optional():
    assert "$12 left" not in hb._brief_footer("", False, _data(), DATE)
    assert "$12 left" in hb._brief_footer("", False, _data(), DATE, budget_headroom_line="$12 left")


def test_footer_carries_the_medical_disclaimer_and_the_date():
    html = hb._brief_footer("", False, _data(), DATE)
    assert "not medical advice" in html
    assert DATE in html
    assert html.endswith("</div></body></html>")


def test_footer_version_string_is_hardcoded():
    """ "Life Platform v2.36" is a literal, not the build fingerprint.

    Pinned so the drift is visible: the footer cannot tell Matthew which build
    rendered the email he is reading.
    """
    assert "Life Platform v2.36" in hb._brief_footer("", False, _data(), DATE)


# ══════════════════════════════════════════════════════════════════════════════
# §14 — build_html (orchestration)
# ══════════════════════════════════════════════════════════════════════════════


def test_build_html_minimal_packet_renders_a_whole_document_with_no_section_errors():
    html = hb.build_html(**_build_kwargs())
    assert html.startswith("<!DOCTYPE html>") and html.endswith("</html>")
    assert "section unavailable" not in html
    # every section marker the orchestrator is responsible for
    for marker in ["S:scorecard", "S:readiness", "S:training", "S:nutrition", "S:habits", "S:cgm", "S:weather", "S:bod"]:
        assert f"<!-- {marker} -->" in html


def test_build_html_requires_a_date():
    kw = _build_kwargs(data={"hrv": {}})
    with pytest.raises(KeyError):
        hb.build_html(**kw)


def test_build_html_formats_the_day_label_from_the_date():
    html = hb.build_html(**_build_kwargs())
    # 2026-06-10 is a Wednesday
    assert "Wednesday, Jun 10" in html


def test_build_html_unparseable_date_falls_back_to_the_raw_string():
    html = hb.build_html(**_build_kwargs(data=_data(date="not-a-date")))
    assert "not-a-date" in html


def test_build_html_intake_line_renders_above_the_footer():
    html = hb.build_html(**_build_kwargs(intake_line="Evening intake: n=12, 95% CI [3.1, 4.4]"))
    assert "Evening intake: n=12" in html
    assert html.index("Evening intake") < html.index("not medical advice")


def test_build_html_ignores_readiness_score_and_engagement_score():
    """Two parameters are accepted and never read — dead API surface.

    `readiness_score` and `engagement_score` are threaded all the way from
    daily_brief_lambda into a signature that drops them. Pinned so a caller does
    not assume passing them changes anything.
    """
    baseline = hb.build_html(**_build_kwargs())
    noisy = hb.build_html(**_build_kwargs(readiness_score=99, engagement_score=1234))
    assert baseline == noisy


def test_build_html_defaults_reward_and_protocol_lists():
    """None must not reach the character section as a non-iterable."""
    html = hb.build_html(**_build_kwargs(character_sheet=_sheet(), triggered_rewards=None, protocol_recs=None))
    assert "CHARACTER SHEET" in html
    assert "section unavailable" not in html


def test_build_html_banner_colour_tracks_the_brief_mode():
    assert "#064e3b" in hb.build_html(**_build_kwargs(brief_mode="flourishing"))
    assert "#1e1b4b" in hb.build_html(**_build_kwargs(brief_mode="struggling"))
    assert "linear-gradient(135deg,#1a1a2e,#16213e" in hb.build_html(**_build_kwargs())


def test_three_vestigial_try_blocks_guard_nothing():
    """`try: pass` / `except Exception as _e: out += _section_error_html(...)`.

    There are three of these — the Travel guard (lines 482-485), an Adaptive
    Mode leftover, and a "dummy try block" in the scorecard (909-912). They are
    the fossil of guards that were moved or never wired, and the Travel one is
    the reason a malformed trip row takes down the whole email (see the xfail in
    §7). Pinned by count so removing or wiring them is a deliberate act.
    """
    assert HB_SOURCE.count("try:\n        pass") == 2
    assert "# travel already handled above" in HB_SOURCE
    assert "# dummy try block" in HB_SOURCE


def test_acwr_line_vanishes_silently_on_a_non_numeric_value():
    """`except Exception: pass` around the whole ACWR block (lines 1102-1103).

    A string where the float is expected removes the readout with no
    placeholder — the same silent-swallow shape as the HRV line.
    """
    html = _training(data=_data(computed_metrics={"acwr": "one point four"}))
    assert "ACWR:" not in html
    assert "section unavailable" not in html


def test_board_confidence_badge_vanishes_silently_on_a_bad_start_date():
    """The badge is wrapped in its own `except: _badge = ""`, so an unparseable
    `journey_start_date` drops the confidence signal while the insight itself
    still renders — a claim shipped without its confidence marker."""
    html = _coaches(bod_insight="Keep going.", profile=_profile(journey_start_date="not-a-date"))
    assert "Keep going." in html
    assert "BOARD OF DIRECTORS" in html


def test_hevy_set_detail_renders_reps_weight_and_rir():
    mf_workouts = {
        "workouts": [
            {
                "workout_name": "Push",
                "exercises": [
                    {"exercise_name": "Bench", "sets": [{"reps": 8, "weight_lbs": 135.4, "rir": 2}, {"reps": 6, "weight_lbs": 0}]}
                ],
            }
        ],
        "total_volume_lbs": 1083.2,
        "total_sets": 2,
    }
    html = _training(data=_data(mf_workouts=mf_workouts))
    assert "💪 Push" in html
    # round(float(135.4)) = 135; rir present -> " RIR2"; a 0-lb (bodyweight) set shows reps only
    assert "Bench</span>: 8@135lb RIR2, 6" in html
    assert "Volume: 1,083 lbs · 2 sets" in html  # fmt_num(1083.2) = "1,083"


def test_weather_card_renders_every_cell_when_given_the_names_it_reads():
    """Control for the weather mismatch xfail: the rendering logic is fine.

    This is the shape `_brief_lifestyle` expects — and which nothing in the repo
    writes. Feeding it by hand proves the four dark cells are a naming defect,
    not missing code.
    """
    rec = {
        "temp_high_f": 78.0,
        "temp_low_f": 55.0,
        "condition": "Partly cloudy",
        "precip_in": 0.24,
        "aqi": 42.0,
        "sunrise_local": "05:42:00",
        "sunset_local": "20:31:00",
    }
    html = _lifestyle(data=_data(weather_yesterday=rec))
    assert "Partly cloudy" in html and "Conditions" in html
    assert '>0.24"</p>' in html and "Precip" in html  # round(0.24, 2)
    assert ">42</p>" in html and "AQI" in html and "#22c55e" in html  # aqi < 50 -> green
    assert ">05:42</p>" in html and "Sunrise" in html  # sunrise_local[:5]
    assert "Sunset" not in html  # read on line 1421 and discarded


def test_weather_falls_back_to_todays_record_when_yesterdays_is_missing():
    html = _lifestyle(data=_data(weather_today={"temp_high_f": 70.0, "temp_low_f": 50.0}))
    assert "WEATHER CONTEXT" in html and ">70°/50°F</p>" in html


def test_weather_high_aqi_bands():
    base = {"temp_high_f": 78.0, "temp_low_f": 55.0}
    assert "#f59e0b" in _lifestyle(data=_data(weather_yesterday=dict(base, aqi=75.0)))  # 50 <= aqi < 100
    assert "#ef4444" in _lifestyle(data=_data(weather_yesterday=dict(base, aqi=160.0)))  # >= 100


# ── honest degradation: one bad value must cost one section, never the email ──
#
# Every entry below is a value shape a real record could carry (a string where a
# number is expected, a null in a list, a scalar where a map is expected). The
# contract is that the reader gets a named placeholder for that one section and
# a complete email everywhere else.

_DEGRADE_CASES = [
    ("Scorecard", lambda: _scorecards(component_scores={"sleep_quality": "eighty"})),
    ("Essential Seven", lambda: _scorecards(component_details={"habits_mvp": {}}, profile=_profile(habit_registry={"A": 5}))),
    ("Training Report", lambda: _training(data=_data(strava={"activities": [{"moving_time_seconds": "1200"}]}))),
    ("Nutrition Report", lambda: _training(data=_data(macrofactor={"total_calories_kcal": 1480}), profile=_profile(calorie_target="x"))),
    ("Habits Deep-Dive", lambda: _training(data=_data(habitify={"habits": {}}), profile=_profile(habit_registry={"A": 5}))),
    ("Supplements", lambda: _training(data=_data(supplements_today={"supplements": [None]}))),
    ("CGM Spotlight", lambda: _training(data=_data(apple={"blood_glucose_avg": 96}, apple_7d=[1, 2, 3]))),
    ("Habit Streaks", lambda: _training(mvp_streak="many")),
    ("Weather", lambda: _lifestyle(data=_data(weather_yesterday={"temp_high_f": 78.0, "sunrise_local": 542}))),
    ("Task Load", lambda: _lifestyle(data=_data(todoist={"overdue_count": "many"}))),
    ("Weight Phase", lambda: _lifestyle(data=_data(latest_weight="280"))),
    ("Guidance", lambda: _lifestyle(tldr_guidance={"guidance": [None]})),
    ("Journal Pulse", lambda: _coaches(data=_data(journal={"mood_avg": "high"}))),
    ("Journal Coach", lambda: _coaches(journal_coach_text=1234)),
    ("Sleep Coach V2", lambda: _coaches(sleep_coach_v2_text=1234)),
    ("Nutrition Coach V2", lambda: _coaches(nutrition_coach_v2_text=1234)),
    ("Training Coach V2", lambda: _coaches(training_coach_v2_text=1234)),
    ("mind_coach_v2", lambda: _coaches(mind_coach_v2_text=1234)),
    ("Board of Directors", lambda: _coaches(bod_insight=1234)),
    ("Anomaly Alert", lambda: _coaches(data=_data(anomaly={"has_anomalies": True, "alerts": [{"metric": None, "message": "x"}]}))),
]


@pytest.mark.parametrize("section,render", _DEGRADE_CASES, ids=[c[0] for c in _DEGRADE_CASES])
def test_a_bad_value_costs_one_named_section_not_the_email(section, render):
    html = render()
    assert f"{section} section unavailable" in html, f"{section} did not degrade to a named placeholder"


def test_build_html_survives_a_packet_that_breaks_several_sections_at_once():
    """The composite of the above: a wide-blast-radius record still ships mail."""
    data = _data(
        strava={"activities": [{"moving_time_seconds": "1200"}]},
        todoist={"overdue_count": "many"},
        latest_weight="280",
        journal={"mood_avg": "high"},
    )
    html = hb.build_html(**_build_kwargs(data=data, bod_insight=1234))
    assert html.startswith("<!DOCTYPE html>") and html.endswith("</html>")
    assert html.count("section unavailable") >= 4
    assert "not medical advice" in html  # the footer still lands


def test_build_html_a_rich_packet_still_renders_no_section_errors():
    """The everything-on path: every optional section populated at once."""
    data = _data(
        whoop={"recovery_score": 68, "hrv": 41.2, "strain": 12.1, "resting_heart_rate": 58},
        sleep={"sleep_duration_hours": 7.8, "sleep_score": 84, "sleep_efficiency_pct": 91, "deep_pct": 21, "rem_pct": 22},
        hrv={"hrv_7d": 42.0, "hrv_30d": 40.0},
        macrofactor={"total_calories_kcal": 1480, "total_protein_g": 185, "total_fat_g": 55, "total_carbs_g": 120},
        habitify={"habits": {"Sleep 7h": 1}},
        strava={"activities": [{"name": "Walk", "sport_type": "Walk", "moving_time_seconds": 2400, "distance_miles": 3.1}]},
        apple={"blood_glucose_avg": 96, "walking_speed_mph": 3.1, "walking_step_length_in": 28.0},
        apple_7d=[{"blood_glucose_avg": 95}, {"blood_glucose_avg": 97}, {"blood_glucose_avg": 99}],
        weather_yesterday={"temp_high_f": 78, "temp_low_f": 55},
        bp_data={"systolic": 118, "diastolic": 76, "readings": 2},
        todoist={"completed_count": 9, "overdue_count": 3, "due_today_count": 4, "active_count": 60},
        latest_weight=280.0,
        week_ago_weight=282.0,
        journal={"mood_avg": 4.0, "energy_avg": 3.5, "stress_avg": 2.0, "themes": ["work"]},
        anomaly={"has_anomalies": True, "alerts": [{"metric": "hrv", "message": "down 2 SD"}]},
        supplements_today={"supplements": [{"name": "Creatine", "dose": 5, "unit": "g", "timing": "morning_fasted"}]},
        mf_workouts={"workouts": [{"workout_name": "Push", "exercises": []}], "total_volume_lbs": 8000, "total_sets": 18},
        computed_metrics={"acwr": 1.1, "zone": "optimal"},
        travel_active={"destination": "Tokyo", "country": "Japan", "timezone": "Asia/Tokyo", "tz_offset": 9, "direction": "east"},
    )
    reg = {"Sleep 7h": {"tier": 0, "status": "active"}, "Read": {"tier": 1, "status": "active"}}
    kw = _build_kwargs(
        data=data,
        profile=_profile(habit_registry=reg, weight_loss_phases=PHASES),
        day_grade_score=83,
        grade="B",
        component_scores={name: 70 for name in COMPONENT_SCORERS},
        component_details={
            "habits_mvp": {"tier0": {"done": 1, "total": 1}, "tier1": {"done": 0, "total": 1}, "tier_status": {0: {"Sleep 7h": True}}}
        },
        readiness_colour="green",
        tldr_guidance={"tldr": "Steady.", "guidance": ["Walk before noon."]},
        bod_insight="Keep going.",
        training_nutrition={"training": "Good volume.", "nutrition": "Protein on target."},
        journal_coach_text="You noticed it. || Write it down.",
        mvp_streak=12,
        full_streak=3,
        vice_streaks={"Weed": 12},
        character_sheet=_sheet(),
        brief_mode="flourishing",
        triggered_rewards=[{"title": "New shoes", "description": "30 workouts"}],
        protocol_recs=[{"pillar": "sleep", "protocols": ["No screens after 21:00"]}],
        compute_stale=True,
        compute_age_msg="is 1 day old",
        weekly_habit_review=_whr(),
        vacation_fund={"total_usd": 1234.0, "total_miles": 1234.0},
        budget_headroom_line="$40 headroom",
        intake_line="n=12",
        **{p: f"{p} says hello." for p in V2_COACH_PARAMS},
    )
    html = hb.build_html(**kw)
    assert "section unavailable" not in html
    assert len(html) > 15000
    for p in V2_COACH_PARAMS:
        assert f"{p} says hello." in html
