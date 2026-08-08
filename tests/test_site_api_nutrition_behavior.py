"""tests/test_site_api_nutrition_behavior.py — behavioral contracts for the two
reader-facing nutrition endpoints served by ``lambdas/web/site_api_nutrition.py``:

    GET /api/nutrition_overview      (nutrition_overview)
    GET /api/deficit_sustainability  (deficit_sustainability)

These are the numbers a human reader sees on averagejoematt.com's nutrition door:
average intake, the protein target/floor story, the TDEE→deficit→loss-rate chain,
the weight projection, and the "is the cut costing you?" verdict. The contracts
pinned here are the ones a reader depends on:

  * ADR-104 honest numbers — an unlogged day is ABSENT, never a factual zero, and
    never silently dropped from an average it belongs in.
  * ADR-105 rigor — n and a confidence tier accompany every relational claim.
  * #1917 window-name honesty — a field named for an N-day window either spans a
    real N days or carries no value.
  * Privacy — the food-delivery tell (P2.3) and the PROVEN_BLUEPRINT benchmark
    (P2.5, ADR-089) are flag-gated OFF; with the flag off the private partition is
    never even queried.
  * HTTP shape — status, envelope keys, Cache-Control.

Everything is driven through the real handler with the facade's injection surface
(`_g`) supplied by hand, a frozen clock, and hand-rolled bounded fakes (never a
MagicMock inside the pagination-shaped source reads).

Arithmetic expectations are hand-derived in the test body and written as
literals with the derivation shown in a comment — never "whatever the code
returned".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from web import site_api_common as sac, site_api_nutrition as nut

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

FROZEN_NOW = datetime(2026, 5, 10, 17, 40, 0, tzinfo=timezone.utc)
TODAY = "2026-05-10"  # Sunday
D7 = "2026-05-03"  # TODAY - 7 (Sunday)
D30 = "2026-04-10"  # TODAY - 30
D14 = "2026-04-26"  # TODAY - 14
GENESIS_FAR = "2026-01-01"  # far enough back that no window is genesis-clamped


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`.

    A subclass rather than a Mock so `strptime`, `timedelta` arithmetic and
    `.date()` — all of which the module under test uses on the same name — keep
    working.
    """

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FROZEN_NOW.replace(tzinfo=None)
        return FROZEN_NOW.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


# ──────────────────────────────────────────────────────────────────────────────
# Bounded hand-rolled fakes
# ──────────────────────────────────────────────────────────────────────────────


def _date_of(row: dict) -> str:
    return row.get("date") or str(row.get("sk", "")).replace("DATE#", "")


class FakeSources:
    """Stand-in for site_api_common._query_source.

    Faithful to the real thing in the ways the handler depends on: it filters to
    the requested inclusive [start, end] date window (the real one issues
    ``sk BETWEEN``), returns a fresh copy of each row, returns ``[]`` for an
    unknown source, and records every call so a test can assert which partitions
    were (and, for privacy, were NOT) read.
    """

    def __init__(self, **by_source):
        self.data = {k: list(v) for k, v in by_source.items()}
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, source, start, end, include_pilot=False):
        self.calls.append((source, start, end))
        if start > end:
            return []
        return [dict(r) for r in self.data.get(source, []) if start <= _date_of(r) <= end]

    @property
    def sources_read(self) -> set[str]:
        return {c[0] for c in self.calls}


def mf(date: str, **fields) -> dict:
    """A MacroFactor day record keyed the way the real partition keys it."""
    return {"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{date}", **fields}


def row(source: str, date: str, **fields) -> dict:
    return {"pk": f"USER#matthew#SOURCE#{source}", "sk": f"DATE#{date}", **fields}


DEFAULT_PROFILE = {"protein_target_g": 190, "protein_floor_g": 170}


@pytest.fixture(autouse=True)
def _frozen_and_isolated(monkeypatch):
    """Freeze both clocks the handler observes and pin the profile read.

    ``nut.datetime`` is what the handler calls ``now()`` on; ``sac.datetime`` is
    what the REAL ``_experiment_date``/``_clamp_today`` call it on, and the test
    hands the real ``_experiment_date`` to the handler rather than a
    reimplementation, so the genesis-clamp semantics under test are the shipped
    ones.

    ``_get_profile`` is patched on ``nut`` — where the handler looks the name up
    — not on ``site_api_common`` where it is defined. Patching the definition
    site would silently no-op against the ``from … import`` binding.
    """
    monkeypatch.setattr(nut, "datetime", _FrozenDatetime)
    monkeypatch.setattr(sac, "datetime", _FrozenDatetime)
    monkeypatch.setattr(sac, "EXPERIMENT_START", GENESIS_FAR)
    monkeypatch.setattr(nut, "_get_profile", lambda: dict(DEFAULT_PROFILE))
    yield


def make_g(sources: FakeSources) -> dict:
    return {"_query_source": sources, "_experiment_date": sac._experiment_date}


def overview(sources: FakeSources) -> dict:
    """Call the handler and return the parsed JSON body (asserting a 200)."""
    resp = nut.nutrition_overview(_g=make_g(sources))
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


def sustainability(sources: FakeSources) -> dict:
    resp = nut.deficit_sustainability(_g=make_g(sources))
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


# ──────────────────────────────────────────────────────────────────────────────
# 1. HTTP envelope
# ──────────────────────────────────────────────────────────────────────────────


def test_nutrition_overview_answers_200_with_a_json_content_type():
    resp = nut.nutrition_overview(_g=make_g(FakeSources(macrofactor=[mf(TODAY, total_calories_kcal=2000)])))
    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "application/json"


def test_nutrition_overview_body_is_parseable_json_carrying_a_meta_block():
    body = overview(FakeSources(macrofactor=[mf(TODAY, total_calories_kcal=2000)]))
    assert "_meta" in body and "generated_at" in body["_meta"]


def test_a_populated_overview_is_cached_for_an_hour():
    """3600s is the published cache contract for the fully-computed page."""
    resp = nut.nutrition_overview(_g=make_g(FakeSources(macrofactor=[mf(TODAY, total_calories_kcal=2000)])))
    assert resp["headers"]["Cache-Control"] == "public, max-age=3600, s-maxage=3600"
    assert json.loads(resp["body"])["_meta"]["cache_seconds"] == 3600


def test_the_empty_nutrition_state_is_cached_only_briefly_so_first_data_appears_fast():
    """Genesis week: a short TTL so the page stops saying "nothing yet" as soon as
    the first upload lands, rather than an hour later."""
    resp = nut.nutrition_overview(_g=make_g(FakeSources()))
    assert resp["headers"]["Cache-Control"] == "public, max-age=300, s-maxage=300"


def test_deficit_sustainability_answers_200_and_caches_for_an_hour_when_unavailable():
    resp = nut.deficit_sustainability(_g=make_g(FakeSources()))
    assert resp["statusCode"] == 200
    assert resp["headers"]["Cache-Control"] == "public, max-age=3600, s-maxage=3600"


def test_every_response_carries_the_browser_security_headers_the_site_relies_on():
    """The site is served cross-origin from CloudFront; these are not optional."""
    resp = nut.nutrition_overview(_g=make_g(FakeSources()))
    assert resp["headers"]["X-Content-Type-Options"] == "nosniff"
    assert resp["headers"]["Access-Control-Allow-Origin"]


# ──────────────────────────────────────────────────────────────────────────────
# 2. Honest empty state (ADR-104)
# ──────────────────────────────────────────────────────────────────────────────


def test_a_platform_with_no_logged_food_reports_absent_averages_not_zero():
    n = overview(FakeSources())["nutrition"]
    for field in ("avg_calories", "avg_protein_g", "avg_carbs_g", "avg_fat_g", "avg_fiber_g", "tdee", "avg_deficit"):
        assert n[field] is None, f"{field} must be absent, not a fabricated 0"


def test_no_logged_food_reports_zero_days_logged_which_is_a_count_not_a_measurement():
    n = overview(FakeSources())["nutrition"]
    assert n["days_logged"] == 0


def test_no_logged_food_never_claims_a_latest_date_of_today():
    """The old bug: latest_date == today read as "logged today, zero calories"."""
    n = overview(FakeSources())["nutrition"]
    assert n["latest_date"] is None
    assert n["as_of"] is None


def test_no_logged_food_says_todays_intake_is_pending_rather_than_missing():
    n = overview(FakeSources())["nutrition"]
    assert n["today_pending"] is True
    assert n["stalled"] is False


def test_the_empty_overlay_still_publishes_its_sample_size_and_readiness():
    o = overview(FakeSources())["recovery_deficit_overlay"]
    assert o["overlap_days"] == 0
    assert o["ready"] is False
    assert o["min_days"] == nut._RDO_MIN_OVERLAP_DAYS
    assert o["caption"] is None


def test_the_empty_state_publishes_the_same_top_level_keys_as_a_populated_one():
    """A front-end binds to one payload shape. If the genesis-week response omits
    keys the populated response has, every reader in the first days of a cycle
    hits a TypeError on `data.<key>.<field>`.

    The expected key set is DERIVED from a populated response — never a
    hand-listed literal, which would rot the moment a new panel ships.
    """
    populated = overview(FakeSources(macrofactor=[mf(TODAY, total_calories_kcal=2000, expenditure_kcal=2800)]))
    empty = overview(FakeSources())
    missing = set(populated) - set(empty)
    assert not missing, f"empty nutrition state omits keys the populated one publishes: {sorted(missing)}"


def test_the_empty_nutrition_block_publishes_the_same_fields_as_a_populated_one():
    populated = overview(FakeSources(macrofactor=[mf(TODAY, total_calories_kcal=2000, expenditure_kcal=2800)]))["nutrition"]
    empty = overview(FakeSources())["nutrition"]
    missing = set(populated) - set(empty)
    assert not missing, f"empty nutrition block omits fields the populated one publishes: {sorted(missing)}"


def test_the_empty_state_still_shapes_the_weekday_weekend_split_so_the_panel_renders():
    wvw = overview(FakeSources())["weekday_vs_weekend"]
    assert set(wvw) == {"weekday", "weekend"}
    assert wvw["weekday"]["avg_calories"] is None
    assert wvw["weekend"]["days"] == 0


def test_the_empty_state_trend_is_an_empty_series_not_a_row_of_zeros():
    assert overview(FakeSources())["nutrition_trend"] == []


def test_a_future_genesis_yields_the_empty_state_rather_than_an_error(monkeypatch):
    """A reset stages EXPERIMENT_START in the FUTURE; the window collapses and the
    page must render an honest pre-start empty state, never a 500."""
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-06-01")
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000)])
    body = overview(src)
    assert body["nutrition"]["days_logged"] == 0
    assert body["nutrition"]["avg_calories"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 3. Macro aggregation arithmetic (hand-derived)
# ──────────────────────────────────────────────────────────────────────────────


def test_average_calories_is_the_mean_of_the_logged_days_rounded_to_a_whole_kcal():
    # (2000 + 2500 + 1800) / 3 = 2100.0
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", total_calories_kcal=2000),
            mf("2026-05-07", total_calories_kcal=2500),
            mf("2026-05-08", total_calories_kcal=1800),
        ]
    )
    assert overview(src)["nutrition"]["avg_calories"] == 2100


def test_average_protein_keeps_one_decimal_because_a_gram_matters_against_the_target():
    # (150 + 181 + 200) / 3 = 177.0
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", total_protein_g=150),
            mf("2026-05-07", total_protein_g=181),
            mf("2026-05-08", total_protein_g=200),
        ]
    )
    assert overview(src)["nutrition"]["avg_protein_g"] == 177.0


def test_a_day_missing_a_macro_is_excluded_from_that_macros_average_not_counted_as_zero():
    """Two days logged calories, one of them logged no fat. Fat average must be the
    mean of the ONE day that has it (60.0), not 30.0."""
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", total_calories_kcal=2000, total_fat_g=60),
            mf("2026-05-07", total_calories_kcal=2000),
        ]
    )
    n = overview(src)["nutrition"]
    assert n["avg_fat_g"] == 60.0
    assert n["avg_calories"] == 2000


def test_a_day_missing_every_macro_still_counts_as_a_logged_day():
    src = FakeSources(macrofactor=[mf("2026-05-06", total_calories_kcal=2000), mf("2026-05-07")])
    assert overview(src)["nutrition"]["days_logged"] == 2


def test_the_legacy_short_macro_field_names_are_read_as_well_as_the_canonical_ones():
    """Records predating the total_* rename must still average correctly — a
    reader must not see their history vanish."""
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", calories=2000, protein_g=180, carbs_g=200, fat_g=70, fiber_g=30),
            mf("2026-05-07", total_calories_kcal=2200, total_protein_g=190, total_carbs_g=210, total_fat_g=80, total_fiber_g=40),
        ]
    )
    n = overview(src)["nutrition"]
    assert n["avg_calories"] == 2100  # (2000+2200)/2
    assert n["avg_protein_g"] == 185.0  # (180+190)/2
    assert n["avg_carbs_g"] == 205.0
    assert n["avg_fat_g"] == 75.0
    assert n["avg_fiber_g"] == 35.0


def test_records_are_ordered_by_date_regardless_of_the_order_the_partition_returns_them():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-08", total_calories_kcal=1800),
            mf("2026-05-06", total_calories_kcal=2000),
            mf("2026-05-07", total_calories_kcal=2500),
        ]
    )
    body = overview(src)
    assert [t["date"] for t in body["nutrition_trend"]] == ["2026-05-06", "2026-05-07", "2026-05-08"]
    assert body["nutrition"]["latest_date"] == "2026-05-08"


def test_the_daily_trend_carries_one_row_per_logged_day_with_absent_macros_as_null():
    src = FakeSources(macrofactor=[mf("2026-05-06", total_calories_kcal=2000), mf("2026-05-07", total_protein_g=180)])
    trend = overview(src)["nutrition_trend"]
    assert len(trend) == 2
    assert trend[0] == {"date": "2026-05-06", "calories": 2000, "protein_g": None, "carbs_g": None, "fat_g": None}
    assert trend[1]["protein_g"] == 180.0
    assert trend[1]["calories"] is None


def test_a_record_carrying_an_explicit_date_field_is_keyed_by_it_not_by_the_sort_key():
    src = FakeSources(macrofactor=[{"sk": "DATE#2026-05-06", "date": "2026-05-06", "total_calories_kcal": 2000}])
    assert overview(src)["nutrition_trend"][0]["date"] == "2026-05-06"


def test_an_honestly_logged_zero_macro_is_averaged_in_rather_than_dropped():
    # fiber logged as 0 on one day and 10 on the other: honest mean = 5.0
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", total_calories_kcal=2000, fiber_g=0),
            mf("2026-05-07", total_calories_kcal=2000, fiber_g=10),
        ]
    )
    assert overview(src)["nutrition"]["avg_fiber_g"] == 5.0


def test_a_logged_zero_calorie_fast_day_is_reported_as_zero_not_as_unlogged():
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=0)])
    assert overview(src)["nutrition"]["latest_calories"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 4. The protein story — target vs floor, both from the profile
# ──────────────────────────────────────────────────────────────────────────────


def test_the_protein_target_and_floor_come_from_the_profile_not_from_literals(monkeypatch):
    """One protein story on every door: the serving layer must publish whatever
    canonical_facts' producer wrote, so a profile change moves every surface."""
    monkeypatch.setattr(nut, "_get_profile", lambda: {"protein_target_g": 205, "protein_floor_g": 185})
    n = overview(FakeSources(macrofactor=[mf("2026-05-06", total_protein_g=190)]))["nutrition"]
    assert n["protein_target_g"] == 205
    assert n["protein_floor_g"] == 185


def test_a_missing_profile_falls_back_to_the_documented_190_target_and_170_floor(monkeypatch):
    monkeypatch.setattr(nut, "_get_profile", lambda: {})
    n = overview(FakeSources(macrofactor=[mf("2026-05-06", total_protein_g=190)]))["nutrition"]
    assert n["protein_target_g"] == 190
    assert n["protein_floor_g"] == 170


def test_protein_target_is_hit_at_exactly_the_target_not_only_above_it():
    """190 g against a 190 g target is a hit — a reader who lands exactly on the
    number has met it."""
    n = overview(FakeSources(macrofactor=[mf("2026-05-06", total_protein_g=190)]))["nutrition"]
    assert n["protein_hit_days"] == 1
    assert n["protein_hit_pct"] == 100


def test_the_floor_is_graded_separately_and_more_days_clear_the_floor_than_the_target():
    # 4 days: 200, 180, 175, 160  → target 190: 1 hit (25%); floor 170: 3 hits (75%)
    src = FakeSources(
        macrofactor=[
            mf("2026-05-05", total_protein_g=200),
            mf("2026-05-06", total_protein_g=180),
            mf("2026-05-07", total_protein_g=175),
            mf("2026-05-08", total_protein_g=160),
        ]
    )
    n = overview(src)["nutrition"]
    assert n["protein_hit_days"] == 1
    assert n["protein_hit_pct"] == 25
    assert n["protein_floor_hit_days"] == 3
    assert n["protein_floor_hit_pct"] == 75


def test_protein_hit_percentage_is_over_days_with_protein_data_not_over_all_days():
    """Two days logged, only one carries protein and it hit the target → 100%,
    not 50%. A day with no protein logged is absent evidence, not a miss."""
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", total_protein_g=200),
            mf("2026-05-07", total_calories_kcal=2000),
        ]
    )
    n = overview(src)["nutrition"]
    assert n["protein_hit_pct"] == 100
    assert n["protein_hit_days"] == 1


def test_no_protein_data_at_all_reports_zero_hit_percent_alongside_a_null_average():
    """The percentage is a completion count over an empty set; the AVERAGE is what
    must stay null so no fabricated gram count is published."""
    n = overview(FakeSources(macrofactor=[mf("2026-05-06", total_calories_kcal=2000)]))["nutrition"]
    assert n["avg_protein_g"] is None
    assert n["protein_hit_pct"] == 0
    assert n["protein_floor_hit_pct"] == 0


def test_the_loss_rate_panel_repeats_the_same_protein_percentages_as_the_headline():
    """Two panels, one truth — a reader must not see 25% in one place and 75% in
    another for the same word."""
    src = FakeSources(
        macrofactor=[
            mf("2026-05-05", total_protein_g=200),
            mf("2026-05-06", total_protein_g=175),
        ]
    )
    body = overview(src)
    assert body["loss_rate"]["protein_hit_pct"] == body["nutrition"]["protein_hit_pct"]
    assert body["loss_rate"]["protein_floor_hit_pct"] == body["nutrition"]["protein_floor_hit_pct"]
    assert body["loss_rate"]["protein_floor_g"] == body["nutrition"]["protein_floor_g"]


# ──────────────────────────────────────────────────────────────────────────────
# 5. The 7-day window (#1917 window-name honesty)
# ──────────────────────────────────────────────────────────────────────────────


def test_the_recent_average_is_published_with_the_window_it_actually_spans():
    src = FakeSources(macrofactor=[mf("2026-05-08", total_calories_kcal=2000), mf("2026-05-09", total_calories_kcal=2200)])
    n = overview(src)["nutrition"]
    assert n["cal_avg_recent"] == 2100  # (2000+2200)/2
    assert n["cal_avg_recent_window_days"] == 7


def test_older_days_are_excluded_from_the_recent_average_but_kept_in_the_thirty_day_one():
    # 2026-05-01 is outside the 7-day window (d7 = 2026-05-03), inside the 30-day one.
    src = FakeSources(
        macrofactor=[
            mf("2026-05-01", total_calories_kcal=3000),
            mf("2026-05-09", total_calories_kcal=2000),
        ]
    )
    n = overview(src)["nutrition"]
    assert n["cal_avg_recent"] == 2000
    assert n["avg_calories"] == 2500  # (3000+2000)/2


def test_the_seven_day_named_average_is_withheld_when_the_cycle_is_younger_than_seven_days(monkeypatch):
    """#1917: a key named `_7d` must span a real 7 days or carry no value. The
    honest number still ships under the window-generic name."""
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-08")  # genesis 2 days ago
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000, total_protein_g=180)])
    n = overview(src)["nutrition"]
    assert n["cal_7d_avg"] is None
    assert n["pro_7d_avg"] is None
    assert n["cal_avg_recent"] == 2000
    assert n["pro_avg_recent_g"] == 180.0
    assert n["cal_avg_recent_window_days"] == 2


def test_the_seven_day_named_average_ships_once_the_window_genuinely_covers_seven_days():
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000, total_protein_g=180)])
    n = overview(src)["nutrition"]
    assert n["cal_7d_avg"] == 2000
    assert n["pro_7d_avg"] == 180.0


def test_the_recent_window_days_shrinks_with_a_young_cycle_rather_than_claiming_seven(monkeypatch):
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-07")  # genesis 3 days ago
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000)])
    assert overview(src)["nutrition"]["cal_avg_recent_window_days"] == 3


def test_the_seven_day_window_covers_exactly_seven_calendar_dates():
    # One record on each of the 8 dates today-7..today, all 1000 kcal except the
    # oldest (today-7 = 2026-05-03) at 8000. A true 7-day window excludes 05-03,
    # giving 1000; an 8-day window gives (8000 + 7*1000)/8 = 1875.
    days = [(datetime(2026, 5, 10) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(8)]
    rows = [mf(d, total_calories_kcal=(8000 if d == D7 else 1000)) for d in days]
    assert overview(FakeSources(macrofactor=rows))["nutrition"]["cal_avg_recent"] == 1000


# ──────────────────────────────────────────────────────────────────────────────
# 6. TDEE resolution, source labelling and the deficit chain
# ──────────────────────────────────────────────────────────────────────────────


def test_a_measured_adaptive_expenditure_is_labelled_as_measured_not_as_an_estimate():
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=2900)])
    n = overview(src)["nutrition"]
    assert n["tdee"] == 2900
    assert n["tdee_source"] == "macrofactor_adaptive"


def test_without_an_uploaded_expenditure_the_tdee_falls_back_to_a_clearly_labelled_estimate():
    """#484: show a real number, flagged — never conflate an estimate with the
    measured adaptive expenditure."""
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000)],
        withings=[row("withings", "2026-05-09", weight_lbs=200)],
    )
    n = overview(src)["nutrition"]
    assert n["tdee_source"] == "estimate_mifflin"
    # Mifflin-St Jeor, 200 lb = 90.7184 kg:
    #   (10*90.7184 + 6.25*182.88 - 5*35 + 5) * 1.55
    # = (907.184 + 1143.0 - 175 + 5) * 1.55 = 1880.184 * 1.55 = 2914.2852 -> 2914
    assert n["tdee"] == 2914


def test_with_neither_an_expenditure_nor_a_weigh_in_the_tdee_stays_absent():
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000)])
    n = overview(src)["nutrition"]
    assert n["tdee"] is None
    assert n["tdee_source"] is None
    assert n["avg_deficit"] is None


def test_the_average_deficit_is_the_tdee_minus_the_average_intake():
    # tdee 2900, intake mean (2000+2200)/2 = 2100 → deficit 800
    src = FakeSources(
        macrofactor=[
            mf("2026-05-08", total_calories_kcal=2000, expenditure_kcal=2900),
            mf("2026-05-09", total_calories_kcal=2200, expenditure_kcal=2900),
        ]
    )
    n = overview(src)["nutrition"]
    assert n["avg_deficit"] == 800


def test_the_loss_rate_chain_states_the_target_deficit_the_gap_and_the_implied_rate():
    # tdee 2900, intake 2000 → deficit 900; required 3 lb/wk = 3*3500/7 = 1500
    # gap = 1500 - 900 = 600; implied rate = 900*7/3500 = 1.8 lb/wk
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=2900)])
    lr = overview(src)["loss_rate"]
    assert lr["target_rate_lb_wk"] == 3
    assert lr["required_deficit_kcal"] == 1500
    assert lr["actual_deficit_kcal"] == 900
    assert lr["gap_kcal"] == 600
    assert lr["implied_rate_lb_wk"] == 1.8


def test_the_loss_rate_chain_reports_absent_rather_than_zero_when_the_tdee_is_unknown():
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000)])
    lr = overview(src)["loss_rate"]
    assert lr["actual_deficit_kcal"] is None
    assert lr["gap_kcal"] is None
    assert lr["implied_rate_lb_wk"] is None
    assert lr["deficit_pct"] is None
    assert lr["deficit_label"] is None


@pytest.mark.parametrize(
    "intake,expected_label",
    [
        # tdee = 3000. deficit_pct = (3000-intake)/3000*100
        (2000, "aggressive"),  # 33.3%
        (2400, "moderate"),  # 20.0%
        (2700, "mild"),  # 10.0%
        (2900, "maintenance"),  # 3.3%
    ],
)
def test_the_deficit_intensity_label_follows_the_published_percentage_bands(intake, expected_label):
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=intake, expenditure_kcal=3000)])
    assert overview(src)["loss_rate"]["deficit_label"] == expected_label


def test_eating_above_maintenance_is_not_labelled_maintenance():
    # tdee 2500, intake 3100 → deficit -600 (a surplus)
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=3100, expenditure_kcal=2500)])
    assert overview(src)["loss_rate"]["deficit_label"] != "maintenance"


def test_a_corrupt_expenditure_value_is_skipped_in_favour_of_the_last_good_one():
    """A single unparseable Expenditure cell must not become the published TDEE and
    must not knock the deficit chain out — the last real reading still stands."""
    src = FakeSources(
        macrofactor=[
            mf("2026-05-08", total_calories_kcal=2000, expenditure_kcal=2800),
            mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal="--"),
        ]
    )
    n = overview(src)["nutrition"]
    assert n["tdee"] == 2800
    assert n["tdee_source"] == "macrofactor_adaptive"


def test_the_most_recent_record_carrying_an_expenditure_wins_over_an_older_one():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-07", total_calories_kcal=2000, expenditure_kcal=2500),
            mf("2026-05-08", total_calories_kcal=2000),
            mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=3100),
        ]
    )
    assert overview(src)["nutrition"]["tdee"] == 3100


# ──────────────────────────────────────────────────────────────────────────────
# 7. Weekday vs weekend
# ──────────────────────────────────────────────────────────────────────────────


def test_saturday_and_sunday_land_in_the_weekend_bucket_and_the_rest_in_weekday():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-04", total_calories_kcal=2000),  # Mon
            mf("2026-05-08", total_calories_kcal=2200),  # Fri
            mf("2026-05-09", total_calories_kcal=3000),  # Sat
            mf("2026-05-10", total_calories_kcal=3400),  # Sun
        ]
    )
    wvw = overview(src)["weekday_vs_weekend"]
    assert wvw["weekday"]["days"] == 2
    assert wvw["weekend"]["days"] == 2
    assert wvw["weekday"]["avg_calories"] == 2100.0  # (2000+2200)/2
    assert wvw["weekend"]["avg_calories"] == 3200.0  # (3000+3400)/2


def test_a_bucket_with_no_days_reports_absent_averages_rather_than_zero():
    src = FakeSources(macrofactor=[mf("2026-05-04", total_calories_kcal=2000)])  # Mon only
    wvw = overview(src)["weekday_vs_weekend"]
    assert wvw["weekend"]["days"] == 0
    assert wvw["weekend"]["avg_calories"] is None
    assert wvw["weekend"]["avg_protein_g"] is None


def test_an_impossible_date_is_dropped_from_the_weekday_split_rather_than_crashing_the_page():
    """`2026-04-31` sorts inside the sk range the real query issues (so a record
    written under it really does reach the handler) but is not a calendar day — it
    must be dropped from the split, not raise out of the endpoint."""
    src = FakeSources(
        macrofactor=[
            mf("2026-04-31", total_calories_kcal=9999),
            mf("2026-05-04", total_calories_kcal=2000),
        ]
    )
    wvw = overview(src)["weekday_vs_weekend"]
    assert wvw["weekday"]["days"] == 1
    assert wvw["weekend"]["days"] == 0


def test_the_weekday_split_carries_the_full_macro_set_a_reader_can_compare():
    src = FakeSources(
        macrofactor=[mf("2026-05-04", total_calories_kcal=2000, total_protein_g=180, total_carbs_g=200, total_fat_g=70, total_fiber_g=30)]
    )
    wd = overview(src)["weekday_vs_weekend"]["weekday"]
    assert wd["avg_protein_g"] == 180.0
    assert wd["avg_carbs_g"] == 200.0
    assert wd["avg_fat_g"] == 70.0
    assert wd["avg_fiber_g"] == 30.0


def test_a_day_with_no_protein_logged_does_not_count_as_a_missed_protein_day():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-04", total_protein_g=200),  # Mon — hit
            mf("2026-05-05", total_calories_kcal=2000),  # Tue — no protein logged
        ]
    )
    body = overview(src)
    assert body["weekday_vs_weekend"]["weekday"]["protein_hit_pct"] == body["nutrition"]["protein_hit_pct"] == 100


# ──────────────────────────────────────────────────────────────────────────────
# 8. Eating window and meal rhythm
# ──────────────────────────────────────────────────────────────────────────────


def _fl(*entries):
    return [{"time": t, **rest} for t, rest in entries]


def test_the_eating_window_is_the_average_span_between_the_first_and_last_meal():
    # Day 1: 08:00 -> 18:00 = 10.0 h; Day 2: 10:00 -> 18:00 = 8.0 h. Mean 9.0 h.
    # first meals 480, 600 -> avg 540 = 9:00 ; last meals both 1080 -> 18:00
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", food_log=[{"time": "08:00"}, {"time": "18:00"}]),
            mf("2026-05-07", food_log=[{"time": "10:00"}, {"time": "18:00"}]),
        ]
    )
    ew = overview(src)["eating_window"]
    assert ew["avg_hours"] == 9.0
    assert ew["avg_first_meal"] == "9:00"
    assert ew["avg_last_meal"] == "18:00"
    assert ew["days_with_data"] == 2


def test_a_day_with_a_single_meal_time_contributes_no_eating_window():
    """One timestamp is not a window; publishing 0 hours would be a fabricated fast."""
    src = FakeSources(macrofactor=[mf("2026-05-06", food_log=[{"time": "12:00"}])])
    assert overview(src)["eating_window"] is None


def test_no_meal_times_anywhere_leaves_the_eating_window_absent_not_zero():
    src = FakeSources(macrofactor=[mf("2026-05-06", total_calories_kcal=2000)])
    assert overview(src)["eating_window"] is None


def test_an_unparseable_meal_time_is_skipped_without_losing_the_rest_of_the_day():
    src = FakeSources(macrofactor=[mf("2026-05-06", food_log=[{"time": "08:00"}, {"time": "oops"}, {"time": "18:00"}])])
    assert overview(src)["eating_window"]["avg_hours"] == 10.0


def test_average_protein_per_meal_divides_window_protein_by_window_meals():
    # 2 days x 200 g protein = 400 g over 4 + 4 = 8 meals -> 50.0 g/meal
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", total_protein_g=200, total_meals=4),
            mf("2026-05-07", total_protein_g=200, total_meals=4),
        ]
    )
    assert overview(src)["meal_rhythm"]["avg_protein_per_meal"] == 50.0


def test_a_day_without_a_meal_count_does_not_inflate_the_grams_per_meal_figure():
    # Day 1: 200 g over 4 meals. Day 2: 200 g, meal count not recorded.
    # The only defensible figure from the days that carry both is 200/4 = 50.0.
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", total_protein_g=200, total_meals=4),
            mf("2026-05-07", total_protein_g=200),
        ]
    )
    assert overview(src)["meal_rhythm"]["avg_protein_per_meal"] == 50.0


def test_grams_per_meal_is_absent_when_no_day_records_a_meal_count():
    src = FakeSources(macrofactor=[mf("2026-05-06", total_protein_g=200)])
    assert overview(src)["meal_rhythm"]["avg_protein_per_meal"] is None


def test_meal_protein_is_bucketed_into_two_hour_blocks_by_the_block_start_hour():
    # 08:15 -> block 8 ; 13:30 -> block 12 ; 13:59 -> block 12
    src = FakeSources(
        macrofactor=[
            mf(
                "2026-05-06",
                food_log=[
                    {"time": "08:15", "protein_g": 40, "calories_kcal": 500},
                    {"time": "13:30", "protein_g": 30, "calories_kcal": 600},
                    {"time": "13:59", "protein_g": 10, "calories_kcal": 100},
                ],
            )
        ]
    )
    dist = overview(src)["meal_rhythm"]["time_distribution"]
    assert dist == [
        {"hour": 8, "protein_g": 40.0, "calories": 500},
        {"hour": 12, "protein_g": 40.0, "calories": 700},
    ]


def test_the_meal_time_ribbon_is_capped_at_the_last_two_weeks_of_days():
    rows = [
        mf((datetime(2026, 5, 10) - timedelta(days=i)).strftime("%Y-%m-%d"), food_log=[{"time": "08:00"}, {"time": "18:00"}])
        for i in range(20)
    ]
    mr = overview(FakeSources(macrofactor=rows))["meal_rhythm"]
    assert len(mr["per_day_window"]) == 14
    assert mr["per_day_window"][-1]["date"] == TODAY  # newest kept, oldest trimmed
    assert mr["days_with_meal_times"] == 20


def test_the_protein_distribution_score_is_averaged_across_the_days_that_report_one():
    # (60 + 80) / 2 = 70
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", protein_distribution_score=60),
            mf("2026-05-07", protein_distribution_score=80),
            mf("2026-05-08", total_calories_kcal=2000),
        ]
    )
    assert overview(src)["meal_rhythm"]["protein_distribution_score"] == 70


def test_the_distribution_score_is_absent_rather_than_zero_when_no_day_reports_one():
    src = FakeSources(macrofactor=[mf("2026-05-06", total_calories_kcal=2000)])
    assert overview(src)["meal_rhythm"]["protein_distribution_score"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 9. Electrolytes, lean mass, micronutrients
# ──────────────────────────────────────────────────────────────────────────────


def test_average_sodium_is_the_mean_of_the_days_that_recorded_it():
    # (2000 + 3000) / 2 = 2500
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", total_sodium_mg=2000),
            mf("2026-05-07", total_sodium_mg=3000),
            mf("2026-05-08", total_calories_kcal=2000),
        ]
    )
    e = overview(src)["electrolytes"]
    assert e["avg_sodium_mg"] == 2500


def test_sodium_is_framed_against_a_reference_range_not_a_single_target():
    """Sodium is a range, not a more-is-better nutrient — the panel must ship both
    ends so the reader can place the number."""
    src = FakeSources(macrofactor=[mf("2026-05-06", total_sodium_mg=2000)])
    e = overview(src)["electrolytes"]
    assert e["sodium_ref_low"] == 1500
    assert e["sodium_ref_high"] == 2300
    assert e["sodium_ref_low"] < e["sodium_ref_high"]


def test_sodium_is_absent_rather_than_zero_when_no_day_recorded_it():
    src = FakeSources(macrofactor=[mf("2026-05-06", total_calories_kcal=2000)])
    assert overview(src)["electrolytes"]["avg_sodium_mg"] is None


def test_potassium_sufficiency_is_read_from_the_most_recent_day():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", micronutrient_sufficiency={"potassium_mg": {"pct": 40}}),
            mf("2026-05-07", micronutrient_sufficiency={"potassium_mg": {"pct": 85}}),
        ]
    )
    assert overview(src)["electrolytes"]["potassium_pct"] == 85


def test_lean_mass_grounds_the_protein_target_in_grams_per_kilo_of_lean_mass():
    # 150 lb lean = 68.0388 kg. target 190 g / 68.0388 = 2.7925... -> 2.79
    # Helms floor 2.3 g/kg -> 68.0388 * 2.3 = 156.489 -> 156
    src = FakeSources(
        macrofactor=[mf("2026-05-06", total_calories_kcal=2000)],
        withings=[row("withings", "2026-05-06", weight_lbs=200, fat_free_mass_lbs=150)],
    )
    lm = overview(src)["lean_mass"]
    assert lm["lean_mass_lb"] == 150.0
    assert lm["lean_mass_kg"] == 68.0
    assert lm["target_g_per_kg_lean"] == 2.79
    assert lm["floor_g_per_kg_lean"] == 2.3
    assert lm["floor_protein_g"] == 156


def test_lean_mass_is_absent_when_no_body_composition_scan_exists():
    src = FakeSources(
        macrofactor=[mf("2026-05-06", total_calories_kcal=2000)],
        withings=[row("withings", "2026-05-06", weight_lbs=200)],
    )
    assert overview(src)["lean_mass"] is None


def test_lean_mass_uses_the_most_recent_scan_that_actually_carries_it():
    src = FakeSources(
        macrofactor=[mf("2026-05-06", total_calories_kcal=2000)],
        withings=[
            row("withings", "2026-05-05", weight_lbs=205, fat_free_mass_lbs=150),
            row("withings", "2026-05-06", weight_lbs=200),  # weight-only scale reading
        ],
    )
    assert overview(src)["lean_mass"]["lean_mass_lb"] == 150.0


def test_micronutrient_sufficiency_is_stamped_with_the_day_it_came_from():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", micronutrient_sufficiency={"iron_mg": {"pct": 50}}, micronutrient_avg_pct=61),
            mf("2026-05-07", micronutrient_sufficiency={"iron_mg": {"pct": 90}}, micronutrient_avg_pct=77),
        ]
    )
    m = overview(src)["micronutrients"]
    assert m["as_of"] == "2026-05-07"
    assert m["sufficiency"] == {"iron_mg": {"pct": 90}}
    assert m["avg_pct"] == 77


def test_micronutrients_report_an_empty_map_and_a_null_average_when_none_were_ingested():
    src = FakeSources(macrofactor=[mf("2026-05-06", total_calories_kcal=2000)])
    m = overview(src)["micronutrients"]
    assert m["sufficiency"] == {}
    assert m["avg_pct"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 10. Caloric periodization (training days vs rest days)
# ──────────────────────────────────────────────────────────────────────────────


def test_a_day_with_a_recorded_activity_is_a_training_day_and_the_rest_are_rest_days():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-06", total_calories_kcal=2600),
            mf("2026-05-07", total_calories_kcal=2000),
        ],
        strava=[row("strava", "2026-05-06", total_kilojoules=800)],
    )
    p = overview(src)["periodization"]
    assert p["training_day"]["count"] == 1
    assert p["rest_day"]["count"] == 1
    assert p["training_day"]["avg_calories"] == 2600.0
    assert p["rest_day"]["avg_calories"] == 2000.0


def test_with_no_activity_data_every_logged_day_is_a_rest_day_rather_than_unknown():
    src = FakeSources(macrofactor=[mf("2026-05-06", total_calories_kcal=2000)])
    p = overview(src)["periodization"]
    assert p["training_day"]["count"] == 0
    assert p["training_day"]["avg_calories"] is None
    assert p["rest_day"]["count"] == 1


def test_the_per_group_deficit_appears_only_once_a_tdee_is_known():
    src = FakeSources(
        macrofactor=[mf("2026-05-06", total_calories_kcal=2000, expenditure_kcal=2900)],
        strava=[row("strava", "2026-05-06", total_kilojoules=800)],
    )
    p = overview(src)["periodization"]
    assert p["training_day"]["avg_deficit"] == 900  # 2900 - 2000
    assert p["rest_day"]["avg_deficit"] is None  # no rest days logged


def test_no_group_deficit_is_published_when_the_tdee_is_unknown():
    src = FakeSources(macrofactor=[mf("2026-05-06", total_calories_kcal=2000)])
    p = overview(src)["periodization"]
    assert p["training_day"].get("avg_deficit") is None
    assert p["rest_day"].get("avg_deficit") is None


# ──────────────────────────────────────────────────────────────────────────────
# 11. Freshness / staleness honesty
# ──────────────────────────────────────────────────────────────────────────────


def test_todays_intake_is_reported_as_pending_while_only_yesterday_is_uploaded():
    """Nutrition is a manual end-of-day upload — always ~24h behind by design. The
    page must say "through yesterday", never "not logged today"."""
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000)])
    n = overview(src)["nutrition"]
    assert n["as_of"] == "2026-05-09"
    assert n["today_pending"] is True
    assert n["lag_days"] == 1


def test_once_today_is_uploaded_nothing_is_pending():
    src = FakeSources(macrofactor=[mf(TODAY, total_calories_kcal=2000)])
    n = overview(src)["nutrition"]
    assert n["today_pending"] is False
    assert n["lag_days"] == 0
    assert n["stalled"] is False


def test_a_long_dead_log_is_flagged_as_stalled_rather_than_normalised_as_upload_lag():
    """The 2026-07-10 truth-audit incident: a 16-day-dead log rendered as routine
    lag. The threshold is DERIVED from the source registry, never hard-coded here."""
    from ingestion.source_registry import DEFAULT_STALE_HOURS, stale_hours_overrides

    threshold_h = stale_hours_overrides().get("macrofactor") or DEFAULT_STALE_HOURS
    stale_days = int(threshold_h // 24) + 2
    latest = (datetime(2026, 5, 10) - timedelta(days=stale_days)).strftime("%Y-%m-%d")
    src = FakeSources(macrofactor=[mf(latest, total_calories_kcal=2000)])
    n = overview(src)["nutrition"]
    assert n["lag_days"] == stale_days
    assert n["stalled"] is True


def test_a_log_inside_the_registry_threshold_is_not_flagged_as_stalled():
    from ingestion.source_registry import DEFAULT_STALE_HOURS, stale_hours_overrides

    threshold_h = stale_hours_overrides().get("macrofactor") or DEFAULT_STALE_HOURS
    fresh_days = max(0, int(threshold_h // 24) - 1)
    latest = (datetime(2026, 5, 10) - timedelta(days=fresh_days)).strftime("%Y-%m-%d")
    src = FakeSources(macrofactor=[mf(latest, total_calories_kcal=2000)])
    assert overview(src)["nutrition"]["stalled"] is False


def test_the_latest_day_headline_reports_that_days_own_numbers():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-08", total_calories_kcal=1500, total_protein_g=120),
            mf("2026-05-09", total_calories_kcal=2400, total_protein_g=205),
        ]
    )
    n = overview(src)["nutrition"]
    assert n["latest_calories"] == 2400
    assert n["latest_protein_g"] == 205.0


def test_an_unparseable_latest_date_leaves_the_lag_absent_rather_than_failing_the_page():
    """The freshness read is one field; if it cannot be computed the rest of the
    page must still serve, with the lag honestly absent and no stalled claim."""
    src = FakeSources(macrofactor=[mf("2026-04-31", total_calories_kcal=2000)])
    n = overview(src)["nutrition"]
    assert n["lag_days"] is None
    assert n["stalled"] is False
    assert n["avg_calories"] == 2000


def test_the_lag_is_never_negative_even_if_a_record_is_dated_in_the_future():
    src = FakeSources(macrofactor=[mf(TODAY, total_calories_kcal=2000)])
    assert overview(src)["nutrition"]["lag_days"] >= 0


# ──────────────────────────────────────────────────────────────────────────────
# 12. The standing weight projection (a graded, falsifiable bet)
# ──────────────────────────────────────────────────────────────────────────────


def _projection_sources(weight_lbs=200.0, intake=2000, tdee=3000):
    return FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=intake, expenditure_kcal=tdee)],
        withings=[row("withings", "2026-05-09", weight_lbs=weight_lbs)],
    )


def test_the_projection_targets_the_next_five_pound_mark_below_the_current_weight():
    assert overview(_projection_sources(weight_lbs=203.4))["projection"]["target_weight_lbs"] == 200


def test_a_weight_already_on_a_five_pound_mark_projects_to_the_next_one_down():
    """Otherwise the bet would resolve instantly and say nothing."""
    p = overview(_projection_sources(weight_lbs=200.0))["projection"]
    assert p["target_weight_lbs"] == 195


def test_the_projected_date_follows_from_the_implied_rate_and_the_distance_to_go():
    # tdee 3000, intake 2000 -> deficit 1000 -> implied 1000*7/3500 = 2.0 lb/wk
    # weight 203.4 -> target 200 -> 3.4 lb to go -> 1.7 weeks = 11.9 days
    # from 2026-05-10 17:40Z + 11 days 21:36 -> 2026-05-22
    p = overview(_projection_sources(weight_lbs=203.4))["projection"]
    assert p["implied_rate_lb_wk"] == 2.0
    assert p["projected_date"] == "2026-05-22"
    assert p["resolves_on"] == p["projected_date"]


def test_the_projection_publishes_a_confidence_band_that_brackets_the_point_estimate():
    p = overview(_projection_sources(weight_lbs=203.4))["projection"]
    assert p["band_earliest"] < p["projected_date"] < p["band_latest"]


def test_the_projection_starts_life_as_an_ungraded_pending_bet():
    """ADR-105: a forecast is stated, then graded — it is never born correct."""
    p = overview(_projection_sources(weight_lbs=203.4))["projection"]
    assert p["verdict"] == "pending"
    assert p["basis"]


def test_no_projection_is_published_when_intake_is_at_or_above_maintenance():
    """A non-positive rate would project a date that never arrives — better to say
    nothing than to publish a fabricated crossing."""
    assert overview(_projection_sources(intake=3000, tdee=3000))["projection"] is None


def test_no_projection_is_published_without_a_recent_weigh_in():
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=3000)])
    assert overview(src)["projection"] is None


def test_a_weight_just_above_a_five_pound_mark_targets_that_mark():
    assert overview(_projection_sources(weight_lbs=195.05))["projection"]["target_weight_lbs"] == 195


# ──────────────────────────────────────────────────────────────────────────────
# 13. Reconciliation — energy-balance projection vs the scale
# ──────────────────────────────────────────────────────────────────────────────


def _recon_sources(n_days=20, first_weight_day=0):
    """n_days of 1000 kcal/day deficit ending yesterday, with weigh-ins starting
    `first_weight_day` days into the window."""
    days = [(datetime(2026, 5, 9) - timedelta(days=n_days - 1 - i)).strftime("%Y-%m-%d") for i in range(n_days)]
    macro = [mf(d, total_calories_kcal=2000, expenditure_kcal=3000) for d in days]
    weights = [row("withings", d, weight_lbs=200.0 - 0.2 * i) for i, d in enumerate(days) if i >= first_weight_day]
    return FakeSources(macrofactor=macro, withings=weights), days


def test_the_reconciliation_is_withheld_until_two_weeks_of_days_overlap():
    src, _ = _recon_sources(n_days=10)
    r = overview(src)["reconciliation"]
    assert r["overlap_days"] == 10
    assert r["min_days"] == 14
    assert r["ready"] is False
    assert "gap_lbs" not in r


def test_the_reconciliation_publishes_the_gap_once_the_overlap_is_long_enough():
    src, days = _recon_sources(n_days=20)
    r = overview(src)["reconciliation"]
    assert r["ready"] is True
    # 20 days x 1000 kcal = 20000 kcal / 3500 = 5.714... -> 5.71 lb projected
    assert r["projected_loss_lbs"] == 5.71
    # scale: 200.0 down to 200.0 - 0.2*19 = 196.2 -> 3.8 lb actual
    assert r["actual_loss_lbs"] == 3.8
    assert r["gap_lbs"] == round(5.71 - 3.8, 2)


def test_the_reconciliation_series_marks_days_without_a_weigh_in_as_gaps():
    src, days = _recon_sources(n_days=20, first_weight_day=3)
    rows = overview(src)["reconciliation"]["days"]
    assert [r["actual_loss_lbs"] for r in rows[:3]] == [None, None, None]
    assert rows[3]["actual_loss_lbs"] is not None
    assert len(rows) == 20


def test_a_day_with_no_food_logged_contributes_no_deficit_to_the_cumulative_projection():
    """An unlogged day is absent, not a full-TDEE deficit spike — it must drop out
    of the cumulative curve entirely rather than imply a fasted day."""
    src = FakeSources(
        macrofactor=[
            mf("2026-05-07", total_calories_kcal=2000, expenditure_kcal=3000),
            mf("2026-05-08", expenditure_kcal=3000),  # no food logged
            mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=3000),
        ]
    )
    rows = overview(src)["reconciliation"]["days"]
    assert [r["date"] for r in rows] == ["2026-05-07", "2026-05-09"]
    # cumulative deficit 1000 then 2000 kcal → 1000/3500 = 0.29 lb, 2000/3500 = 0.57 lb
    assert [r["projected_loss_lbs"] for r in rows] == [0.29, 0.57]


def test_no_reconciliation_series_is_built_without_a_tdee():
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000)])
    r = overview(src)["reconciliation"]
    assert r["days"] == []
    assert r["overlap_days"] == 0
    assert r["ready"] is False


def test_projected_and_actual_loss_share_a_baseline_on_the_first_weighed_day():
    """The two reconciliation trajectories must start on the same DAY.

    `cum_def` accumulated from the first LOGGED day while `start_actual` anchored to the
    first WEIGHED day, so when the scale started later than the food log every
    pre-weigh-in day was added to the projected line and to nothing on the actual line —
    inflating the published `gap_lbs`, which the page sells to the reader as "logging
    accuracy / TDEE drift".

    CORRECTION to the original marker. It prescribed asserting
    `first_weighed["projected_loss_lbs"] == 0.0` — an EXCLUSIVE baseline, where the
    baseline day's own deficit is not yet on the projected line. That contradicts
    `test_the_reconciliation_publishes_the_gap_once_the_overlap_is_long_enough`, which is
    green and pins the INCLUSIVE convention: with weigh-ins on every one of 20 days it
    expects 5.71 lb projected (20 × 1000 / 3500), and an exclusive baseline would make it
    19 × 1000 / 3500 = 5.43. Satisfying the marker as written would have required
    reversing that green contract. The defect is real and is fixed; only the marker's
    asserted value for the baseline day was wrong.

    Hand-derived, first_weight_day=3 (weigh-ins on days 3..19 of 20, 1000 kcal/day):
      days 0..2 have no baseline to be measured against -> no projected value at all
      day 3 is the baseline: actual 0.0 ; projected = its own 1000 / 3500 = 0.29
      day 19: 17 weighed days x 1000 = 17000 / 3500 = 4.857 -> 4.86 projected
              scale W[3]=199.4 down to W[19]=196.2 -> 3.2 actual ; gap 1.66
      before the fix the projected line also carried the 3-day prefix: 5.71, gap 2.51
    """
    src, days = _recon_sources(n_days=20, first_weight_day=3)
    r = overview(src)["reconciliation"]
    rows = r["days"]
    assert [x["projected_loss_lbs"] for x in rows[:3]] == [None, None, None]
    first_weighed = next(x for x in rows if x["actual_loss_lbs"] is not None)
    assert first_weighed is rows[3]
    assert first_weighed["actual_loss_lbs"] == 0.0
    assert first_weighed["projected_loss_lbs"] == 0.29
    assert r["projected_loss_lbs"] == 4.86
    assert r["actual_loss_lbs"] == 3.2
    assert r["gap_lbs"] == 1.66


# ──────────────────────────────────────────────────────────────────────────────
# 14. Recovery-vs-deficit overlay wiring (ADR-105 rigor on a relational claim)
# ──────────────────────────────────────────────────────────────────────────────


def test_the_overlay_pairs_each_mornings_recovery_with_the_previous_days_deficit():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-08", total_calories_kcal=2000, expenditure_kcal=3000),
            mf("2026-05-09", total_calories_kcal=2500, expenditure_kcal=3000),
        ],
        whoop=[row("whoop", "2026-05-09", recovery_score=61), row("whoop", "2026-05-10", recovery_score=72)],
    )
    days = {d["date"]: d for d in overview(src)["recovery_deficit_overlay"]["days"]}
    assert days["2026-05-09"]["recovery"] == 61
    assert days["2026-05-09"]["prior_deficit_kcal"] == 1000  # 3000 - 2000 on 05-08
    assert days["2026-05-10"]["prior_deficit_kcal"] == 500  # 3000 - 2500 on 05-09


def test_the_overlay_walks_every_calendar_day_so_a_missing_sync_stays_a_visible_gap():
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=3000)],
        whoop=[row("whoop", "2026-05-10", recovery_score=72)],
    )
    o = overview(src)["recovery_deficit_overlay"]
    dates = [d["date"] for d in o["days"]]
    assert dates[0] == D30 and dates[-1] == TODAY
    assert len(dates) == 31  # inclusive both ends
    assert o["days"][0]["recovery"] is None
    assert o["days"][0]["prior_deficit_kcal"] is None


def test_the_overlay_reports_its_sample_size_and_confidence_never_a_bare_claim():
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=3000)],
        whoop=[row("whoop", "2026-05-10", recovery_score=72)],
    )
    o = overview(src)["recovery_deficit_overlay"]
    assert o["overlap_days"] == 1
    assert o["ready"] is False
    assert o["confidence"] in ("LOW", "MEDIUM", "HIGH")
    assert str(o["overlap_days"]) in o["caption"]


def test_an_unparseable_window_yields_a_not_ready_overlay_rather_than_an_exception():
    """The overlay is one panel among many — a bad window must degrade that panel,
    never take the nutrition door down with it."""
    o = nut._recovery_deficit_overlay({"2026-05-09": 800.0}, {"2026-05-10": 70.0}, "not-a-date", TODAY)
    assert o["days"] == []
    assert o["overlap_days"] == 0
    assert o["ready"] is False
    assert o["caption"] is None


def test_the_overlay_never_publishes_a_correlation_coefficient():
    """RQA-08 honesty rule: n and a tier, never a bare r for the reader to over-read."""
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=3000)],
        whoop=[row("whoop", "2026-05-10", recovery_score=72)],
    )
    o = overview(src)["recovery_deficit_overlay"]
    assert "r" not in o and "pearson_r" not in o and "correlation" not in o


def test_no_tdee_means_the_overlay_has_no_deficits_to_pair_and_says_so():
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000)],
        whoop=[row("whoop", "2026-05-10", recovery_score=72)],
    )
    o = overview(src)["recovery_deficit_overlay"]
    assert o["overlap_days"] == 0
    assert all(d["prior_deficit_kcal"] is None for d in o["days"])


# ──────────────────────────────────────────────────────────────────────────────
# 15. Privacy — the two flag-gated panels
# ──────────────────────────────────────────────────────────────────────────────


def test_the_food_delivery_tell_is_private_by_default():
    assert nut._DELIVERY_PUBLIC is False


def test_the_proven_blueprint_benchmark_is_private_by_default():
    """ADR-089: the BENCH-1 training_reference is hard-private."""
    assert nut._BLUEPRINT_PUBLIC is False


def test_with_the_delivery_flag_off_the_private_partition_is_never_even_queried():
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=3000)],
        food_delivery=[row("food_delivery", "2026-05-09", orders=2)],
    )
    body = overview(src)
    assert body["food_delivery"] is None
    assert "food_delivery" not in src.sources_read


def test_with_the_blueprint_flag_off_the_reference_partition_is_never_even_queried():
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=3000)],
        training_reference=[row("training_reference", "2015-06-01", confidence="high")],
    )
    body = overview(src)
    assert body["blueprint_benchmark"] is None
    assert "training_reference" not in src.sources_read


def test_the_public_response_reads_only_the_partitions_the_nutrition_page_needs():
    """Guard the SET: the read set is compared against the partitions the handler
    is allowed to touch with the privacy flags off, so a new private source added
    to this handler fails here rather than shipping."""
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=3000)])
    overview(src)
    allowed = {"macrofactor", "strava", "withings", "whoop"}
    assert src.sources_read <= allowed, f"unexpected partition read: {sorted(src.sources_read - allowed)}"


def test_flipping_the_delivery_flag_is_what_surfaces_the_panel(monkeypatch):
    """Proves the gate is the flag and not an accident of the fixture — if this
    ever stopped surfacing data, the privacy tests above would be vacuous."""
    monkeypatch.setattr(nut, "_DELIVERY_PUBLIC", True)
    src = FakeSources(
        macrofactor=[
            mf("2026-05-08", total_calories_kcal=2000, expenditure_kcal=3000),
            mf("2026-05-09", total_calories_kcal=2800, expenditure_kcal=3000),
        ],
        food_delivery=[row("food_delivery", "2026-05-09", orders=1)],
    )
    src.data["macrofactor"].append(mf("2026-05-07", expenditure_kcal=3000))  # unlogged day
    fd = overview(src)["food_delivery"]
    assert fd["public"] is True
    # the unlogged day joins neither bucket — absence is not a home-cooked day
    assert fd["delivery_days"] == 1 and fd["home_days"] == 1
    assert fd["avg_deficit_delivery"] == 200  # 3000 - 2800
    assert fd["avg_deficit_home"] == 1000  # 3000 - 2000


def test_flipping_the_blueprint_flag_is_what_surfaces_that_panel(monkeypatch):
    monkeypatch.setattr(nut, "_BLUEPRINT_PUBLIC", True)
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000, total_protein_g=180, expenditure_kcal=3000)],
        training_reference=[row("training_reference", "2015-06-01", confidence="high")],
    )
    bb = overview(src)["blueprint_benchmark"]
    assert bb["public"] is True
    assert bb["current_avg_protein_g"] == 180.0
    assert "training_reference" in src.sources_read


def test_no_raw_food_log_entries_leak_into_the_public_payload():
    """The per-entry food log is the private record behind the aggregates; only
    times/aggregates may surface, never the item names."""
    src = FakeSources(
        macrofactor=[
            mf(
                "2026-05-09",
                total_calories_kcal=2000,
                food_log=[{"time": "08:00", "name": "PRIVATE_ITEM_NAME", "protein_g": 40}, {"time": "18:00", "protein_g": 30}],
            )
        ]
    )
    resp = nut.nutrition_overview(_g=make_g(src))
    assert "PRIVATE_ITEM_NAME" not in resp["body"]


# ──────────────────────────────────────────────────────────────────────────────
# 16. /api/deficit_sustainability
# ──────────────────────────────────────────────────────────────────────────────


def _whoop_series(hrv, eff, rec, start="2026-04-30"):
    base = datetime.strptime(start, "%Y-%m-%d")
    return [
        row(
            "whoop",
            (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            hrv=hrv[i],
            sleep_efficiency_pct=eff[i],
            recovery_score=rec[i],
        )
        for i in range(len(hrv))
    ]


FLAT6 = [100, 100, 100, 100, 100, 100]
DROP6 = [100, 100, 90, 90, 70, 70]  # first_avg 100, last_avg 70 -> -30%


def _sust_sources(intake=2000, tdee=3000, hrv=None, eff=None, rec=None, t0=None, kj=None, mf_days=7):
    days = [(datetime(2026, 5, 9) - timedelta(days=mf_days - 1 - i)).strftime("%Y-%m-%d") for i in range(mf_days)]
    macro = [mf(d, total_calories_kcal=intake, expenditure_kcal=tdee) for d in days]
    wdays = [(datetime(2026, 5, 9) - timedelta(days=5 - i)).strftime("%Y-%m-%d") for i in range(6)]
    whoop = [
        row("whoop", d, hrv=(hrv or FLAT6)[i], sleep_efficiency_pct=(eff or FLAT6)[i], recovery_score=(rec or FLAT6)[i])
        for i, d in enumerate(wdays)
    ]
    # `completion_pct` is what ingestion/habitify_lambda.py actually writes, and it is a
    # 0–1 FRACTION (`total_completed / resolved_possible`), not a percentage. The channel
    # is trend-only, so the shared FLAT6/DROP6 magnitudes are scaled rather than
    # redefined. (The fixture used to write `tier_0_completion_rate`, a name no writer in
    # the repo has ever produced — see the reader/writer test below.)
    habit = [row("habitify", d, completion_pct=(t0 or FLAT6)[i] / 100) for i, d in enumerate(wdays)]
    strava = [row("strava", d, total_kilojoules=(kj or FLAT6)[i]) for i, d in enumerate(wdays)]
    return FakeSources(macrofactor=macro, whoop=whoop, habitify=habit, strava=strava)


def test_deficit_sustainability_is_unavailable_and_says_why_below_seven_logged_days():
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000)] * 1)
    ds = sustainability(src)["deficit_sustainability"]
    assert ds["available"] is False
    assert ds["days_logged"] == 1
    assert "7" in ds["reason"]


def test_deficit_sustainability_publishes_no_verdict_or_channels_when_unavailable():
    """An unavailable read must not ship a half-built payload the page can misread."""
    ds = sustainability(FakeSources())["deficit_sustainability"]
    assert "severity" not in ds and "channels" not in ds and "verdict" not in ds


def test_deficit_sustainability_becomes_available_at_exactly_seven_logged_days():
    assert sustainability(_sust_sources(mf_days=7))["deficit_sustainability"]["available"] is True
    assert sustainability(_sust_sources(mf_days=6))["deficit_sustainability"]["available"] is False


def test_the_deficit_block_states_intake_tdee_and_the_labelled_gap():
    # tdee 3000, intake 2000 -> deficit 1000 -> 33.3% -> aggressive
    ds = sustainability(_sust_sources(intake=2000, tdee=3000))["deficit_sustainability"]
    assert ds["deficit"]["avg_intake_kcal"] == 2000
    assert ds["deficit"]["tdee"] == 3000
    assert ds["deficit"]["deficit_kcal"] == 1000
    assert ds["deficit"]["deficit_pct"] == 33.3
    assert ds["deficit"]["label"] == "aggressive"
    assert ds["deficit"]["in_deficit"] is True


def test_the_tdee_used_here_is_the_same_measured_expenditure_the_overview_uses():
    """Two endpoints, one TDEE — a reader crossing panels must not see two numbers."""
    src = _sust_sources(intake=2000, tdee=3000)
    ds = sustainability(src)["deficit_sustainability"]
    assert ds["deficit"]["tdee_source"] == "macrofactor_adaptive"
    assert ds["deficit"]["tdee"] == overview(src)["nutrition"]["tdee"]


def test_without_an_uploaded_expenditure_the_estimate_is_labelled_as_such():
    days = [(datetime(2026, 5, 9) - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    src = FakeSources(
        macrofactor=[mf(d, total_calories_kcal=2000) for d in days],
        withings=[row("withings", "2026-05-09", weight_lbs=200)],
    )
    ds = sustainability(src)["deficit_sustainability"]
    assert ds["deficit"]["tdee_source"] == "estimate_mifflin"
    assert ds["deficit"]["tdee"] == 2914


def test_with_neither_expenditure_nor_weight_the_default_estimate_is_named_as_a_default():
    days = [(datetime(2026, 5, 9) - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    src = FakeSources(macrofactor=[mf(d, total_calories_kcal=2000) for d in days])
    ds = sustainability(src)["deficit_sustainability"]
    assert ds["deficit"]["tdee"] == 2400
    assert ds["deficit"]["tdee_source"] == "estimate_default"


def test_a_small_gap_is_not_treated_as_an_active_deficit():
    # tdee 3000, intake 2900 -> 100 kcal, below the 200 kcal threshold
    ds = sustainability(_sust_sources(intake=2900, tdee=3000))["deficit_sustainability"]
    assert ds["deficit"]["in_deficit"] is False
    assert ds["severity"] == "not_in_deficit"


def test_five_channels_are_always_monitored_and_each_reports_a_direction():
    ds = sustainability(_sust_sources())["deficit_sustainability"]
    names = [c["name"] for c in ds["channels"]]
    assert len(names) == 5 == len(set(names))
    for c in ds["channels"]:
        assert c["status"] in ("stable", "degraded")
        assert c["direction"] in ("improving", "declining", "stable", "insufficient_data")


def test_a_channel_with_too_little_data_says_insufficient_rather_than_stable():
    """ADR-104: silence is not a reading. Four HRV points cannot support a trend."""
    days = [(datetime(2026, 5, 9) - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    src = FakeSources(
        macrofactor=[mf(d, total_calories_kcal=2000, expenditure_kcal=3000) for d in days],
        whoop=[row("whoop", d, hrv=50) for d in days[:4]],
    )
    ds = sustainability(src)["deficit_sustainability"]
    hrv = next(c for c in ds["channels"] if c["name"] == "HRV")
    assert hrv["direction"] == "insufficient_data"
    assert hrv["status"] == "stable"  # absence of evidence is not evidence of strain


def test_a_flat_series_reads_as_stable_with_a_zero_delta():
    ds = sustainability(_sust_sources())["deficit_sustainability"]
    hrv = next(c for c in ds["channels"] if c["name"] == "HRV")
    assert hrv["direction"] == "stable"
    assert hrv["delta_pct"] == 0.0
    assert ds["degraded_count"] == 0


def test_a_sharply_falling_hrv_series_is_reported_as_degraded_with_its_magnitude():
    # first third mean 100, last third mean 70 -> -30.0%
    ds = sustainability(_sust_sources(hrv=DROP6))["deficit_sustainability"]
    hrv = next(c for c in ds["channels"] if c["name"] == "HRV")
    assert hrv["direction"] == "declining"
    assert hrv["delta_pct"] == -30.0
    assert hrv["status"] == "degraded"


def test_a_shallow_decline_below_a_channels_threshold_is_not_called_degraded():
    """Recovery needs more than a 10% drop before it counts as strain — noise must
    not be dressed up as a signal."""
    # 100,100,100,100,93,93 -> first 100, last 93 -> -7.0%: declining but under the bar
    ds = sustainability(_sust_sources(rec=[100, 100, 100, 100, 93, 93]))["deficit_sustainability"]
    rec = next(c for c in ds["channels"] if c["name"] == "Recovery")
    assert rec["direction"] == "declining"
    assert rec["status"] == "stable"


def test_a_channel_starting_from_zero_reads_as_stable_instead_of_an_infinite_change():
    """Two rest days open the window, so training output starts at 0 kJ. There is no
    percentage change to state from a zero baseline — the panel must say stable, not
    divide by zero."""
    ds = sustainability(_sust_sources(kj=[0, 0, 50, 50, 80, 80]))["deficit_sustainability"]
    train = next(c for c in ds["channels"] if c["name"] == "Training output")
    assert train["direction"] == "stable"
    assert train["delta_pct"] == 0
    assert train["status"] == "stable"


def test_a_day_of_zero_habit_completion_drives_the_habit_channel_rather_than_vanishing():
    ds = sustainability(_sust_sources(t0=[80, 80, 50, 50, 0, 0]))["deficit_sustainability"]
    t0 = next(c for c in ds["channels"] if c["name"] == "Habit completion")
    assert t0["direction"] == "declining"
    assert t0["delta_pct"] == -100.0
    assert t0["status"] == "degraded"


def test_two_degraded_channels_raise_a_watch_not_an_alarm():
    ds = sustainability(_sust_sources(hrv=DROP6, rec=DROP6))["deficit_sustainability"]
    assert ds["degraded_count"] == 2
    assert ds["severity"] == "watch"


def test_three_degraded_channels_raise_a_warning():
    ds = sustainability(_sust_sources(hrv=DROP6, rec=DROP6, t0=DROP6))["deficit_sustainability"]
    assert ds["degraded_count"] == 3
    assert ds["severity"] == "warning"


def test_four_degraded_channels_raise_the_critical_back_off_verdict():
    ds = sustainability(_sust_sources(hrv=DROP6, rec=DROP6, t0=DROP6, kj=DROP6))["deficit_sustainability"]
    assert ds["degraded_count"] == 4
    assert ds["severity"] == "critical"
    assert "recovery" in ds["verdict"].lower()


def test_a_deficit_the_body_is_absorbing_reads_as_sustainable():
    ds = sustainability(_sust_sources())["deficit_sustainability"]
    assert ds["severity"] == "sustainable"
    assert ds["verdict"]


def test_no_active_deficit_short_circuits_the_verdict_regardless_of_channel_strain():
    """Nothing to strain means nothing to blame on the cut — the verdict must not
    attribute unrelated fatigue to a deficit that is not happening."""
    ds = sustainability(_sust_sources(intake=2950, tdee=3000, hrv=DROP6, rec=DROP6, t0=DROP6, kj=DROP6))["deficit_sustainability"]
    assert ds["severity"] == "not_in_deficit"
    assert ds["degraded_count"] == 4


def test_the_deep_sleep_signal_is_surfaced_when_it_is_what_triggered_the_strain():
    """A displayed direction of "stable" next to a "degraded" status would read as a
    contradiction — the sub-signal that fired must be the one shown."""
    wdays = [(datetime(2026, 5, 9) - timedelta(days=5 - i)).strftime("%Y-%m-%d") for i in range(6)]
    deep_hours = [2.0, 2.0, 1.8, 1.8, 1.0, 1.0]  # deep% first 25.0, last 12.5 -> -50%
    days = [(datetime(2026, 5, 9) - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    src = FakeSources(
        macrofactor=[mf(d, total_calories_kcal=2000, expenditure_kcal=3000) for d in days],
        whoop=[
            row("whoop", d, sleep_efficiency_pct=95, slow_wave_sleep_hours=deep_hours[i], sleep_duration_hours=8.0)
            for i, d in enumerate(wdays)
        ],
    )
    ds = sustainability(src)["deficit_sustainability"]
    sleep = next(c for c in ds["channels"] if c["name"] == "Sleep quality")
    assert sleep["status"] == "degraded"
    assert sleep["direction"] == "declining"


def test_training_output_sums_multiple_activities_onto_one_day_before_trending():
    """Two rides on one day is one day of output, not two data points."""
    wdays = [(datetime(2026, 5, 9) - timedelta(days=5 - i)).strftime("%Y-%m-%d") for i in range(6)]
    days = [(datetime(2026, 5, 9) - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    strava = []
    for i, d in enumerate(wdays):
        strava.append(row("strava", d, total_kilojoules=DROP6[i] / 2))
        strava.append(row("strava", d, total_kilojoules=DROP6[i] / 2))
    src = FakeSources(
        macrofactor=[mf(d, total_calories_kcal=2000, expenditure_kcal=3000) for d in days],
        strava=strava,
    )
    ds = sustainability(src)["deficit_sustainability"]
    train = next(c for c in ds["channels"] if c["name"] == "Training output")
    assert train["delta_pct"] == -30.0
    assert train["status"] == "degraded"


def test_the_reported_period_starts_at_the_genesis_clamped_window_start(monkeypatch):
    """ADR-077 "clamped, not hidden": after a reset the window shrinks to genesis
    rather than reaching back into the prior cycle, and the payload says so."""
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-03")
    ds = sustainability(_sust_sources())["deficit_sustainability"]
    assert ds["period"]["start"] == "2026-05-03"
    assert ds["period"]["end"] == TODAY


def test_the_reported_period_length_matches_the_window_it_actually_covers(monkeypatch):
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-03")  # genesis 7 days ago
    ds = sustainability(_sust_sources())["deficit_sustainability"]
    assert ds["period"]["days"] == 7


def test_days_with_no_readable_calorie_field_never_publish_a_zero_intake():
    """#2217 (fixed): all 7 days carry only the legacy `calories` field name, never
    `total_calories_kcal`. Before the fix, deficit_sustainability's inline
    `_f(i.get("total_calories_kcal"))` extraction saw nothing on every row, so
    avg_intake_kcal fabricated a 0, deficit_pct fabricated 100%, and the label
    fabricated 'aggressive' out of a genuinely-logged, unremarkable week.

    Hand-derived with the fix (uniform `calories`, all resolved via `_mf`):
      avg_cal = 2000 (uniform) ; tdee = 3000 (expenditure_kcal, uniform)
      deficit_kcal = round(3000 - 2000) = 1000
      deficit_pct = round(1000 / 3000 * 100, 1) = 33.3  -> label "aggressive" (>25)
    """
    days = [(datetime(2026, 5, 9) - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    src = FakeSources(macrofactor=[mf(d, calories=2000, expenditure_kcal=3000) for d in days])
    deficit = sustainability(src)["deficit_sustainability"]["deficit"]
    assert deficit["avg_intake_kcal"] == 2000
    assert deficit["deficit_kcal"] == 1000
    assert deficit["deficit_pct"] == 33.3
    assert deficit["label"] == "aggressive"
    assert deficit["in_deficit"] is True


def test_a_week_split_between_the_legacy_and_current_calorie_field_names_averages_both():
    """#2217: real MacroFactor history can straddle the field-name migration — some
    days logged under the legacy `calories` name, others under the current
    `total_calories_kcal` — within the SAME 14-day window. Both must resolve
    through the one `_mf` accessor and land in the same average, not have the
    legacy-named days silently drop out.

    Hand-derived: 4 days at total_calories_kcal=2000, 3 days at calories=2600,
    expenditure_kcal=3000 on every day.
      avg_cal = round((4*2000 + 3*2600) / 7) = round(15800/7) = round(2257.142857) = 2257
      deficit_kcal = round(3000 - 2257) = 743
      deficit_pct = round(743 / 3000 * 100, 1) = round(24.7666..., 1) = 24.8  -> label "moderate" (>15, <=25)
    """
    days = [(datetime(2026, 5, 9) - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    records = [
        mf(d, total_calories_kcal=2000, expenditure_kcal=3000) if i < 4 else mf(d, calories=2600, expenditure_kcal=3000)
        for i, d in enumerate(days)
    ]
    src = FakeSources(macrofactor=records)
    deficit = sustainability(src)["deficit_sustainability"]["deficit"]
    assert deficit["avg_intake_kcal"] == 2257
    assert deficit["deficit_kcal"] == 743
    assert deficit["deficit_pct"] == 24.8
    assert deficit["label"] == "moderate"
    assert deficit["in_deficit"] is True


def test_each_severity_carries_its_own_prose_verdict_rather_than_one_generic_line():
    """The verdict is what a reader acts on — it must escalate with the severity,
    not restate a constant."""
    watch = sustainability(_sust_sources(hrv=DROP6, rec=DROP6))["deficit_sustainability"]
    critical = sustainability(_sust_sources(hrv=DROP6, rec=DROP6, t0=DROP6, kj=DROP6))["deficit_sustainability"]
    sustainable = sustainability(_sust_sources())["deficit_sustainability"]
    verdicts = {watch["verdict"], critical["verdict"], sustainable["verdict"]}
    assert len(verdicts) == 3
    for v in verdicts:
        assert isinstance(v, str) and len(v) > 20 and v.endswith(".")


def test_deficit_sustainability_reads_only_the_partitions_the_panel_needs():
    src = _sust_sources()
    sustainability(src)
    allowed = {"macrofactor", "whoop", "habitify", "strava", "withings"}
    assert src.sources_read <= allowed, f"unexpected partition read: {sorted(src.sources_read - allowed)}"


def test_the_fourteen_day_window_is_the_one_actually_queried():
    src = _sust_sources()
    sustainability(src)
    macro_calls = [c for c in src.calls if c[0] == "macrofactor"]
    assert macro_calls == [("macrofactor", D14, TODAY)]


# ──────────────────────────────────────────────────────────────────────────────
# 17. Cross-cutting: the handler survives a hostile partition
# ──────────────────────────────────────────────────────────────────────────────


def test_a_single_malformed_macro_value_does_not_take_down_the_whole_nutrition_page():
    src = FakeSources(
        macrofactor=[
            mf("2026-05-08", total_calories_kcal=2000),
            mf("2026-05-09", total_calories_kcal="n/a"),
        ]
    )
    assert overview(src)["nutrition"]["avg_calories"] == 2000


def test_a_withings_row_with_a_non_numeric_weight_falls_back_to_no_estimate():
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000)],
        withings=[row("withings", "2026-05-09", weight_lbs="unknown")],
    )
    n = overview(src)["nutrition"]
    assert n["tdee"] is None
    assert n["tdee_source"] is None


def test_a_zero_or_negative_weight_never_produces_an_estimated_tdee():
    src = FakeSources(
        macrofactor=[mf("2026-05-09", total_calories_kcal=2000)],
        withings=[row("withings", "2026-05-09", weight_lbs=0)],
    )
    assert overview(src)["nutrition"]["tdee"] is None


def test_a_non_positive_expenditure_is_not_accepted_as_a_measured_tdee():
    src = FakeSources(macrofactor=[mf("2026-05-09", total_calories_kcal=2000, expenditure_kcal=0)])
    assert overview(src)["nutrition"]["tdee_source"] is None
