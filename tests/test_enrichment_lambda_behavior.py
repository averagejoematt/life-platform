"""tests/test_enrichment_lambda_behavior.py — behavioural contracts for the
nightly activity enricher (`lambdas/ingestion/enrichment_lambda.py`).

The `activity-enrichment` Lambda is a WRITE-BACK enricher: it re-opens stored
Strava day records and stamps `enriched_name` / `enriched_at` onto every nested
activity. Five reader surfaces render that label —
`lambdas/web/site_api_autonomic.py`, `lambdas/web/site_api_vitals_depth.py`,
the weekly + monthly digest emails, and `mcp/tools_data.py::search_activities`
(which SEARCHES it) — so a defect here is simultaneously a website defect, an
email defect and a retrieval defect.

What these tests pin:

  * **ADR-104 honest numbers** — a percentile rank is a factual claim about
    where an activity sits in the all-time population; an absent recovery score
    must produce no emoji rather than a red one.
  * **Reader/writer field agreement** — every activity field this module READS
    is derived from `strava_lambda._normalize()`'s own key set, not a literal
    list, so a renamed upstream field fails here instead of going silently dark.
  * **ADR-058 phase treatment** — strava and whoop are RAW_TIMESERIES, so these
    reads must NOT carry the phase filter (the #2109 class, inverted). The
    expectation is derived from `phase_taxonomy`, never asserted as a constant.
  * **Decimal before DynamoDB** — no bare float may reach `update_item`.
  * **Crash paths** — one malformed activity must not abort the whole nightly
    run; `lambda_handler` re-raises, so an escape is a failed invocation and a
    CloudWatch alarm, not a partial success.
  * **Durability** — an enrichment that is overwritten by the next ingest of the
    same day is an enrichment that never existed.

Tests marked xfail record defects discovered by this tranche; they are NOT
fixed here (test-only change).
"""

import ast
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import enrichment_lambda as en  # noqa: E402
import strava_lambda as sv  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402
from experiment.phase_filter import source_reads_cross_phase  # noqa: E402

MODULE_SRC = os.path.join(ROOT, "lambdas", "ingestion", "enrichment_lambda.py")


# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock — never mix a fixture date with the real wall clock.
# ──────────────────────────────────────────────────────────────────────────────

FROZEN_NOW = datetime(2026, 8, 7, 15, 30, 0, tzinfo=timezone.utc)
FROZEN_TODAY = "2026-08-07"
FROZEN_YESTERDAY = "2026-08-06"
FROZEN_STAMP = "2026-08-07T15:30:00+00:00"


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`.

    A subclass (not a Mock) keeps arithmetic, `timedelta` and `.strftime()`
    working — `lambda_handler` uses all three off the same name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(en, "datetime", _FrozenDatetime)
    return FROZEN_NOW


# ──────────────────────────────────────────────────────────────────────────────
# Hand-rolled bounded test doubles (never a MagicMock in a paginated read).
# ──────────────────────────────────────────────────────────────────────────────


def _pk_in(condition):
    """The `USER#…#SOURCE#…` literal inside a boto3 KeyConditionExpression tree.

    Walks the condition's own expression tuple rather than parsing a repr, so a
    boto3 formatting change cannot silently make the dispatch stop working.
    """
    expr = condition.get_expression()
    for value in expr["values"]:
        if hasattr(value, "get_expression"):
            found = _pk_in(value)
            if found:
                return found
        elif isinstance(value, str) and value.startswith("USER#"):
            return value
    return None


class FakeTable:
    """DynamoDB Table stand-in that dispatches queries by partition key.

    `pages[pk]` is a LIST OF PAGES — each page is a list of items. The fake
    serves them in order and only sets `LastEvaluatedKey` while pages remain, so
    the module's pagination loop is exercised with a hard, finite bound (no
    MagicMock, which is what turned a pagination loop into an OOM once before).
    """

    MAX_PAGES = 20

    def __init__(self, pages=None):
        self.pages = dict(pages or {})
        self.query_calls = []
        self.updates = []
        self._cursor = {}

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        pk = _pk_in(kwargs["KeyConditionExpression"])
        pages = self.pages.get(pk, [[]])
        index = kwargs.get("ExclusiveStartKey", {}).get("_page", 0)
        assert index < self.MAX_PAGES, "pagination did not terminate"
        resp = {"Items": list(pages[index])}
        if index + 1 < len(pages):
            resp["LastEvaluatedKey"] = {"_page": index + 1}
        return resp

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}


def find_floats(obj, path="values"):
    """Every path in `obj` holding a native Python float (which boto3 rejects)."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, float):
        return [path]
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            out += find_floats(v, f"{path}.{k}")
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for i, v in enumerate(obj):
            out += find_floats(v, f"{path}[{i}]")
        return out
    return []


def activity(name="Mailbox Peak", **fields):
    act = {"name": name}
    act.update(fields)
    return act


def strava_day(date, activities):
    return {"pk": f"{en.USER_PREFIX}strava", "sk": f"DATE#{date}", "date": date, "source": "strava", "activities": activities}


def whoop_day(date, recovery):
    return {"pk": f"{en.USER_PREFIX}whoop", "sk": f"DATE#{date}", "date": date, "recovery_score": recovery}


@pytest.fixture
def table(monkeypatch):
    fake = FakeTable()
    monkeypatch.setattr(en, "table", fake)
    return fake


# ══════════════════════════════════════════════════════════════════════════════
# is_generic_name — deciding whether Strava named the activity or Matthew did
# ══════════════════════════════════════════════════════════════════════════════


def test_a_bare_activity_type_is_a_strava_auto_name():
    assert en.is_generic_name("Run") is True
    assert en.is_generic_name("Ride") is True


def test_a_time_of_day_plus_type_is_a_strava_auto_name():
    assert en.is_generic_name("Morning Run") is True
    assert en.is_generic_name("Lunch Ride") is True


def test_generic_detection_ignores_case_and_padding():
    assert en.is_generic_name("  MORNING run  ") is True


def test_a_name_matthew_chose_is_never_treated_as_generic():
    """The whole point of the generic check: a real title must survive intact."""
    for chosen in ("Mailbox Peak", "Machu Picchu day 3", "Run to the store", "Morning"):
        assert en.is_generic_name(chosen) is False, chosen


def test_every_generic_type_is_recognised_on_its_own_and_after_every_prefix():
    """Guard the SET: derived from the module's own two vocabularies, so a type
    or prefix added to one list but forgotten in the matcher fails here."""
    for kind in en.GENERIC_TYPES:
        assert en.is_generic_name(kind), kind
        for prefix in en.GENERIC_PREFIXES:
            assert en.is_generic_name(f"{prefix} {kind}"), f"{prefix} {kind}"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): enrichment_lambda.py:129 is_generic_name() only "
        "matches a TWO-token name (`len(parts) == 2`), but Strava auto-names "
        "sport-qualified activities with three tokens — 'Morning Trail Run', "
        "'Afternoon Mountain Bike Ride', 'Evening Weight Training'. Those are exactly "
        "as generic as 'Morning Run', yet the location is appended as a suffix "
        "instead of promoted to the primary identifier, so the site + digests show "
        "'Morning Trail Run — Issaquah, WA' where the design says 'Issaquah, WA "
        "TrailRun'. Hurts every reader of the four surfaces that render enriched_name."
    ),
)
def test_a_three_token_strava_auto_name_is_also_generic():
    assert en.is_generic_name("Morning Trail Run") is True


# ══════════════════════════════════════════════════════════════════════════════
# percentile / percentile_label — the "top 1% ever" factual claim
# ══════════════════════════════════════════════════════════════════════════════


def test_an_absent_value_has_no_percentile_rank():
    """ADR-104: no elevation figure is not a 0th-percentile climb."""
    assert en.percentile([1.0, 2.0, 3.0], None) is None


def test_an_empty_population_yields_no_percentile_rank():
    assert en.percentile([], 5.0) is None


def test_the_percentile_is_the_share_of_the_population_strictly_below():
    # 50 of the 100 values 0..99 are strictly below 50.0 -> 100 * 50/100 = 50.0
    population = [float(i) for i in range(100)]
    assert en.percentile(population, 50.0) == 50.0


def test_the_all_time_best_of_a_hundred_ranks_top_one_percent():
    # 99 of the 100 values 0..99 are strictly below 99.0 -> 100 * 99/100 = 99.0
    population = [float(i) for i in range(100)]
    assert en.percentile(population, 99.0) == 99.0


def test_a_value_below_everything_ranks_at_the_bottom():
    assert en.percentile([10.0, 20.0], 1.0) == 0.0


def test_percentile_accepts_the_string_free_numeric_forms_the_store_returns():
    from decimal import Decimal

    assert en.percentile([1.0, 2.0, 3.0], Decimal("2")) == pytest.approx(100.0 * 1 / 3, abs=0.05)


def test_only_a_genuinely_rare_effort_earns_a_label():
    assert en.percentile_label(89.9, "elevation") is None
    assert en.percentile_label(90.0, "elevation") == "top 10% elevation ever"
    assert en.percentile_label(95.0, "elevation") == "top 5% elevation ever"
    assert en.percentile_label(99.0, "elevation") == "top 1% elevation ever"


def test_an_unrankable_effort_gets_no_label_rather_than_a_neutral_one():
    """ADR-104: 'not remarkable' and 'unknown' must both render as nothing."""
    assert en.percentile_label(None, "distance") is None


def test_the_label_names_the_metric_it_ranked():
    assert "distance" in en.percentile_label(99.0, "distance")


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): enrichment_lambda.py:161 percentile() uses "
        "bisect_LEFT, which counts only values STRICTLY below. An activity tied with "
        "the all-time maximum therefore ranks at 0.0 — identical to the all-time "
        "WORST. Measured: percentile([1000,1000,1000], 1000) == 0.0. Any repeated "
        "route (the same 1,000 ft hill climbed three times) silently loses its 'top "
        "1% elevation ever' label, and the rank shown is a false factual claim "
        "(ADR-104). bisect_right — the share at-or-below — is the honest statistic. "
        "Hurts every reader of enriched_name and every search over it."
    ),
)
def test_an_effort_tied_with_the_all_time_best_still_ranks_at_the_top():
    assert en.percentile([1000.0, 1000.0, 1000.0], 1000.0) == 100.0


# ══════════════════════════════════════════════════════════════════════════════
# build_percentile_lookup — the all-time population the ranks are computed over
# ══════════════════════════════════════════════════════════════════════════════


def test_the_population_is_sorted_ascending_for_both_metrics():
    days = [
        strava_day("2026-08-01", [activity(total_elevation_gain_feet=900, distance_miles=6)]),
        strava_day("2026-08-02", [activity(total_elevation_gain_feet=100, distance_miles=2)]),
    ]
    elevations, distances = en.build_percentile_lookup(days)
    assert elevations == [100.0, 900.0]
    assert distances == [2.0, 6.0]


def test_activities_missing_a_metric_do_not_enter_that_population():
    days = [strava_day("2026-08-01", [activity(distance_miles=3), activity(total_elevation_gain_feet=500)])]
    elevations, distances = en.build_percentile_lookup(days)
    assert elevations == [500.0]
    assert distances == [3.0]


def test_a_day_with_no_activities_contributes_nothing():
    assert en.build_percentile_lookup([{"date": "2026-08-01"}]) == ([], [])


def test_every_activity_across_every_day_reaches_the_population():
    days = [
        strava_day("2026-08-01", [activity(distance_miles=1), activity(distance_miles=2)]),
        strava_day("2026-08-02", [activity(distance_miles=3)]),
    ]
    _, distances = en.build_percentile_lookup(days)
    assert distances == [1.0, 2.0, 3.0]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): enrichment_lambda.py:148-151 gates the "
        "percentile population on truthiness (`if elev:` / `if dist:`), so a "
        "genuinely-flat activity (0 ft elevation gain — every treadmill run, pool "
        "swim and flat city walk) is EXCLUDED from the all-time population rather "
        "than ranked at the bottom of it. Removing the bottom of the distribution "
        "shrinks the denominator, which UNDERSTATES every remaining activity's "
        "percentile: with [0, 0, 100] the 100 ft climb is at the 66th percentile of "
        "what Matthew has actually done, but the code ranks it against [100] alone "
        "and returns 0.0. The published 'top N% ever' claim is therefore computed "
        "over a population that silently excludes real efforts (ADR-104)."
    ),
)
def test_a_genuinely_flat_effort_counts_as_a_zero_not_as_an_absence():
    days = [strava_day("2026-08-01", [activity(total_elevation_gain_feet=0), activity(total_elevation_gain_feet=100)])]
    elevations, _ = en.build_percentile_lookup(days)
    assert elevations == [0.0, 100.0]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): enrichment_lambda.py:149-151 calls float(elev) "
        "with no guard, and build_percentile_lookup() runs over the ENTIRE Strava "
        "history before any day is enriched. One non-numeric elevation or distance "
        "anywhere in the archive therefore raises ValueError out of "
        "enrich_date_range() and out of lambda_handler() (which re-raises), so the "
        "nightly run fails wholesale and NO activity is enriched — including the "
        "thousands of clean ones. A per-value guard would cost the one bad row only."
    ),
)
def test_one_unparseable_metric_in_the_archive_cannot_kill_the_whole_population():
    days = [strava_day("2026-08-01", [activity(total_elevation_gain_feet="n/a"), activity(total_elevation_gain_feet=100)])]
    elevations, _ = en.build_percentile_lookup(days)
    assert 100.0 in elevations


# ══════════════════════════════════════════════════════════════════════════════
# recovery_emoji — the recovery context glyph
# ══════════════════════════════════════════════════════════════════════════════


def test_no_recovery_reading_produces_no_glyph():
    """ADR-104: a missing Whoop night is not a red recovery day."""
    assert en.recovery_emoji(None) is None


def test_the_green_band_starts_at_sixty_seven():
    assert en.recovery_emoji(67) == en.RECOVERY_EMOJI["green"]
    assert en.recovery_emoji(66) == en.RECOVERY_EMOJI["yellow"]


def test_the_yellow_band_starts_at_thirty_four():
    assert en.recovery_emoji(34) == en.RECOVERY_EMOJI["yellow"]
    assert en.recovery_emoji(33) == en.RECOVERY_EMOJI["red"]


def test_a_measured_zero_recovery_is_red_not_absent():
    """0 is a reading Whoop can actually return; it must not read as no data."""
    assert en.recovery_emoji(0) == en.RECOVERY_EMOJI["red"]


def test_every_band_in_the_glyph_registry_is_reachable():
    """Guard the SET: derived from RECOVERY_EMOJI, so an added band that no
    threshold can produce fails here."""
    produced = {en.recovery_emoji(score) for score in range(0, 101)}
    assert produced == set(en.RECOVERY_EMOJI.values())


# ══════════════════════════════════════════════════════════════════════════════
# build_enriched_name — the label four reader surfaces render
# ══════════════════════════════════════════════════════════════════════════════


def test_a_chosen_name_is_preserved_and_the_location_appended():
    label = en.build_enriched_name(activity("Mailbox Peak", location_city="North Bend", location_state="WA"), None, None, None, [], [])
    assert label == "Mailbox Peak — North Bend, WA"


def test_a_generic_name_is_replaced_by_the_location_and_sport():
    label = en.build_enriched_name(
        activity("Morning Run", location_city="Seattle", location_state="WA", sport_type="Run"), None, None, None, [], []
    )
    assert label == "Seattle, WA Run"


def test_a_city_without_a_state_still_locates_the_activity():
    label = en.build_enriched_name(activity("Mailbox Peak", location_city="North Bend"), None, None, None, [], [])
    assert label == "Mailbox Peak — North Bend"


def test_a_state_without_a_city_still_locates_the_activity():
    label = en.build_enriched_name(activity("Mailbox Peak", location_state="WA"), None, None, None, [], [])
    assert label == "Mailbox Peak — WA"


def test_an_activity_with_no_location_keeps_its_name_alone():
    assert en.build_enriched_name(activity("Mailbox Peak"), None, None, None, [], []) == "Mailbox Peak"


def test_stats_are_joined_into_one_middle_dot_segment():
    label = en.build_enriched_name(
        activity("Mailbox Peak", distance_miles=6.2, total_elevation_gain_feet=4000, average_heartrate=142),
        None,
        None,
        None,
        [],
        [],
    )
    assert label == "Mailbox Peak · 6.2mi · 4,000ft · 142bpm avg"


def test_a_missing_stat_is_omitted_rather_than_rendered_as_zero():
    """ADR-104: an activity with no HR strap must not claim 0 bpm."""
    label = en.build_enriched_name(activity("Mailbox Peak", distance_miles=6.2), None, None, None, [], [])
    assert "bpm" not in label and "ft" not in label


def test_elevation_over_a_thousand_feet_is_thousands_separated():
    label = en.build_enriched_name(activity("X", total_elevation_gain_feet=12345), None, None, None, [], [])
    assert "12,345ft" in label


def test_the_recovery_glyph_follows_the_stats():
    label = en.build_enriched_name(activity("X", distance_miles=3.0), 80, None, None, [], [])
    assert label == "X · 3.0mi · " + en.RECOVERY_EMOJI["green"]


def test_a_percentile_note_is_appended_when_the_effort_is_rare():
    population = [float(i) for i in range(100)]
    # 99 of 100 values are strictly below 99.0 -> 99th percentile -> "top 1%"
    label = en.build_enriched_name(activity("X", total_elevation_gain_feet=99.0), None, None, None, population, [])
    assert label.endswith("top 1% elevation ever")


def test_elevation_wins_over_distance_when_both_are_remarkable():
    population = [float(i) for i in range(100)]
    label = en.build_enriched_name(
        activity("X", total_elevation_gain_feet=99.0, distance_miles=99.0), None, None, None, population, population
    )
    assert "elevation ever" in label and "distance ever" not in label


def test_a_distance_note_surfaces_when_only_the_distance_is_remarkable():
    population = [float(i) for i in range(100)]
    label = en.build_enriched_name(activity("X", distance_miles=99.0), None, None, None, [], population)
    assert "top 1% distance ever" in label


def test_a_single_personal_record_is_singular_and_two_are_plural():
    assert en.build_enriched_name(activity("X", pr_count=1), None, None, None, [], []).endswith("1 PR")
    assert en.build_enriched_name(activity("X", pr_count=2), None, None, None, [], []).endswith("2 PRs")


def test_no_personal_records_adds_no_pr_segment():
    assert "PR" not in en.build_enriched_name(activity("X", pr_count=0), None, None, None, [], [])


def test_the_full_label_orders_identity_stats_recovery_rank_then_records():
    population = [float(i) for i in range(100)]
    label = en.build_enriched_name(
        activity(
            "Morning Run",
            location_city="Issaquah",
            location_state="WA",
            sport_type="Run",
            distance_miles=6.2,
            total_elevation_gain_feet=99.0,
            average_heartrate=142,
            pr_count=2,
        ),
        80,
        None,
        None,
        population,
        population,
    )
    assert label == "Issaquah, WA Run · 6.2mi · 99ft · 142bpm avg · 🟢 · top 1% elevation ever · 2 PRs"


def test_rebuilding_the_same_activity_produces_an_identical_label():
    """Idempotency at the builder — the write-back is gated on label equality,
    so an unstable builder would rewrite the whole day every night."""
    act = activity("Mailbox Peak", location_city="North Bend", location_state="WA", distance_miles=6.2)
    assert en.build_enriched_name(act, 80, None, None, [], []) == en.build_enriched_name(dict(act), 80, None, None, [], [])


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): enrichment_lambda.py:201 does "
        "`activity.get('name', '').strip()` — the default only applies when the KEY "
        "is absent, so a stored activity whose `name` is explicitly None raises "
        "AttributeError. There is no per-activity try/except anywhere in "
        "enrich_date_range(), and lambda_handler() re-raises, so ONE such row aborts "
        "the entire nightly run and every other activity that night goes unenriched. "
        "Same shape at line 214 for `sport_type` (`.title()` on None)."
    ),
)
def test_an_activity_stored_without_a_name_degrades_rather_than_raising():
    assert isinstance(en.build_enriched_name({"name": None}, None, None, None, [], []), str)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): enrichment_lambda.py:214 renders the sport "
        "with `.title()`, which lowercases every character after the first of each "
        "word. Strava's `sport_type` values are CamelCase tokens — TrailRun, "
        "MountainBikeRide, WeightTraining, VirtualRide — so the label published to "
        "the site, both digest emails and the MCP search index reads 'Issaquah, WA "
        "Trailrun'. It also makes the enriched label un-searchable by the real sport "
        "token, which is the stated purpose of search_activities matching "
        "enriched_name (docs/SCHEMA.md:365)."
    ),
)
def test_the_sport_token_is_rendered_as_strava_spells_it():
    label = en.build_enriched_name(
        activity("Morning Run", location_city="Issaquah", location_state="WA", sport_type="TrailRun"), None, None, None, [], []
    )
    assert label == "Issaquah, WA TrailRun"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): enrichment_lambda.py:214 defaults sport_type "
        "to '' and then unconditionally concatenates it, so a generic-named activity "
        "with no sport_type yields a label with a TRAILING SPACE — 'Seattle, WA '. "
        "That string is written to DynamoDB and rendered verbatim by "
        "site_api_autonomic.py:303, site_api_vitals_depth.py:237 and both digest "
        "emails; it also defeats the label-equality idempotency check's intent by "
        "storing whitespace as content."
    ),
)
def test_a_generic_activity_with_no_sport_type_has_no_trailing_whitespace():
    label = en.build_enriched_name(activity("Morning Run", location_city="Seattle", location_state="WA"), None, None, None, [], [])
    assert label == label.strip()


# ══════════════════════════════════════════════════════════════════════════════
# query_source — the paginated partition read
# ══════════════════════════════════════════════════════════════════════════════


def test_the_read_targets_the_user_scoped_source_partition(table):
    en.query_source("strava", "2026-08-01", "2026-08-07")
    assert _pk_in(table.query_calls[0]["KeyConditionExpression"]) == f"USER#{en.USER_ID}#SOURCE#strava"


def test_the_window_upper_bound_admits_every_sort_key_on_the_end_date(table):
    """`DATE#{end}~` is the guard: '~' (0x7E) sorts after every character a
    DATE# suffix can carry, so a same-day record with a suffix is not dropped."""
    en.query_source("strava", "2026-08-01", "2026-08-07")
    expression = table.query_calls[0]["KeyConditionExpression"].get_expression()
    bounds = [v for v in expression["values"] if hasattr(v, "get_expression")][-1].get_expression()["values"]
    assert list(bounds[1:]) == ["DATE#2026-08-01", "DATE#2026-08-07~"]


def test_every_page_of_a_paginated_partition_is_returned(table):
    table.pages[f"{en.USER_PREFIX}strava"] = [
        [strava_day("2026-08-01", [])],
        [strava_day("2026-08-02", [])],
        [strava_day("2026-08-03", [])],
    ]
    items = en.query_source("strava", "2026-08-01", "2026-08-07")
    assert [i["date"] for i in items] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert len(table.query_calls) == 3


def test_the_read_hands_back_floats_not_decimals(table):
    from decimal import Decimal

    table.pages[f"{en.USER_PREFIX}strava"] = [[strava_day("2026-08-01", [activity("X", distance_miles=Decimal("6.2"))])]]
    items = en.query_source("strava", "2026-08-01", "2026-08-07")
    assert items[0]["activities"][0]["distance_miles"] == 6.2
    assert isinstance(items[0]["activities"][0]["distance_miles"], float)


def test_both_sources_this_lambda_reads_are_kept_across_experiment_cycles():
    """ADR-058/#2109: strava and whoop are RAW_TIMESERIES, so a phase filter on
    these reads would truncate the all-time percentile population to the current
    cycle's age. Derived from the taxonomy, never asserted as a literal."""
    for source in ("strava", "whoop"):
        assert phase_taxonomy.classify(f"USER#matthew#SOURCE#{source}") == phase_taxonomy.RAW_TIMESERIES
        assert source_reads_cross_phase(source) is True


def test_the_read_carries_no_phase_filter_as_the_taxonomy_requires(table):
    en.query_source("strava", "2026-08-01", "2026-08-07")
    assert "FilterExpression" not in table.query_calls[0]


# ══════════════════════════════════════════════════════════════════════════════
# Reader/writer field agreement — derived from the Strava writer's own key set
# ══════════════════════════════════════════════════════════════════════════════


def _activity_fields_read_by_enrichment():
    """Every `<activity>.get("literal")` field name in the module source.

    Derived by AST from the module itself so a field added to the reader later
    is covered automatically — the "guard the SET, not the instance" rule.
    """
    tree = ast.parse(open(MODULE_SRC, encoding="utf-8").read())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "get" or not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id not in ("activity", "act"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            found.add(node.args[0].value)
    return found


def test_the_reader_actually_reads_the_fields_this_test_thinks_it_does():
    fields = _activity_fields_read_by_enrichment()
    assert {"name", "distance_miles", "total_elevation_gain_feet", "average_heartrate", "pr_count"} <= fields


def test_every_activity_field_read_here_is_one_the_strava_writer_stores():
    """The tranche-2 field-name-mismatch class: a read of a field nobody writes
    leaves the feature permanently, silently dark. The writer's key set is
    derived from strava_lambda._normalize(), never re-typed."""
    written = set(sv._normalize({}).keys())
    own = {"enriched_name", "enriched_at"}  # this Lambda's own write-back fields
    unknown = _activity_fields_read_by_enrichment() - written - own
    assert unknown == set(), f"read but never written by strava_lambda._normalize: {sorted(unknown)}"


def test_the_day_level_fields_read_here_are_ones_the_strava_writer_stores():
    day = sv.transform({"activities": [{"name": "X"}]}, "2026-08-06")[0]
    assert "date" in day and "activities" in day


def test_the_recovery_field_read_from_whoop_is_the_one_whoop_validates():
    """`recovery_score` is the field enrich_date_range reads off the Whoop day;
    the ingestion validator's own whoop schema is the writer-side source."""
    from ingestion.ingestion_validator import _SCHEMAS

    whoop_schema = _SCHEMAS["whoop"]
    declared = set(whoop_schema.get("typed_fields", {})) | set(whoop_schema.get("range_checks", {}))
    assert "recovery_score" in declared


# ══════════════════════════════════════════════════════════════════════════════
# enrich_date_range — the write-back
# ══════════════════════════════════════════════════════════════════════════════


def _seed(table, strava_days, whoop_days=()):
    table.pages[f"{en.USER_PREFIX}strava"] = [list(strava_days)]
    table.pages[f"{en.USER_PREFIX}whoop"] = [list(whoop_days)]


def test_a_day_in_the_window_is_enriched_and_written_back(table, frozen_clock):
    _seed(table, [strava_day("2026-08-06", [activity("Mailbox Peak", distance_miles=6.2)])])
    result = en.enrich_date_range("2026-08-06", "2026-08-06")
    assert result == {"enriched": 1, "skipped": 0, "days_processed": 1}
    assert len(table.updates) == 1


def test_the_write_back_targets_the_strava_day_partition(table, frozen_clock):
    _seed(table, [strava_day("2026-08-06", [activity("X", distance_miles=1.0)])])
    en.enrich_date_range("2026-08-06", "2026-08-06")
    assert table.updates[0]["Key"] == {"pk": f"{en.USER_PREFIX}strava", "sk": "DATE#2026-08-06"}


def test_the_write_back_replaces_the_activities_list_and_stamps_the_day(table, frozen_clock):
    _seed(table, [strava_day("2026-08-06", [activity("Mailbox Peak", distance_miles=6.2)])])
    en.enrich_date_range("2026-08-06", "2026-08-06")
    update = table.updates[0]
    assert update["UpdateExpression"] == "SET activities = :acts, enriched_at = :ts"
    assert update["ExpressionAttributeValues"][":ts"] == FROZEN_STAMP
    assert update["ExpressionAttributeValues"][":acts"][0]["enriched_name"] == "Mailbox Peak · 6.2mi"


def test_the_enrichment_stamp_on_each_activity_is_utc(table, frozen_clock):
    _seed(table, [strava_day("2026-08-06", [activity("X", distance_miles=1.0)])])
    en.enrich_date_range("2026-08-06", "2026-08-06")
    assert table.updates[0]["ExpressionAttributeValues"][":acts"][0]["enriched_at"] == FROZEN_STAMP


def test_no_bare_float_reaches_dynamodb(table, frozen_clock):
    """boto3 rejects native floats — a single one loses the whole write."""
    _seed(table, [strava_day("2026-08-06", [activity("X", distance_miles=6.25, total_elevation_gain_feet=1234.5)])])
    en.enrich_date_range("2026-08-06", "2026-08-06")
    assert find_floats(table.updates[0]["ExpressionAttributeValues"]) == []


def test_re_running_over_already_enriched_activities_writes_nothing(table, frozen_clock):
    """Idempotency: the nightly cron re-reads the same day for three more days
    of trailing coverage; an unconditional write would churn the whole archive."""
    act = activity("Mailbox Peak", distance_miles=6.2)
    act["enriched_name"] = "Mailbox Peak · 6.2mi"
    _seed(table, [strava_day("2026-08-06", [act])])
    result = en.enrich_date_range("2026-08-06", "2026-08-06")
    assert result["enriched"] == 0 and result["skipped"] == 1
    assert table.updates == []


def test_the_recovery_context_comes_from_the_same_calendar_day(table, frozen_clock):
    _seed(
        table,
        [strava_day("2026-08-06", [activity("X", distance_miles=1.0)])],
        [whoop_day("2026-08-05", 20), whoop_day("2026-08-06", 80)],
    )
    en.enrich_date_range("2026-08-06", "2026-08-06")
    assert en.RECOVERY_EMOJI["green"] in table.updates[0]["ExpressionAttributeValues"][":acts"][0]["enriched_name"]


def test_a_day_with_no_whoop_reading_gets_no_recovery_glyph(table, frozen_clock):
    """ADR-104: a missing Whoop night must not render as any recovery state."""
    _seed(table, [strava_day("2026-08-06", [activity("X", distance_miles=1.0)])])
    en.enrich_date_range("2026-08-06", "2026-08-06")
    label = table.updates[0]["ExpressionAttributeValues"][":acts"][0]["enriched_name"]
    assert not any(glyph in label for glyph in en.RECOVERY_EMOJI.values())


def test_days_outside_the_window_are_read_for_context_but_never_written(table, frozen_clock):
    """The all-time read exists to build the percentile population; writing
    outside the requested window would be a silent archive-wide rewrite."""
    _seed(
        table,
        [
            strava_day("2020-01-01", [activity("Old", distance_miles=1.0)]),
            strava_day("2026-08-06", [activity("New", distance_miles=1.0)]),
        ],
    )
    result = en.enrich_date_range("2026-08-06", "2026-08-06")
    assert result["days_processed"] == 1
    assert [u["Key"]["sk"] for u in table.updates] == ["DATE#2026-08-06"]


def test_the_percentile_population_spans_the_whole_archive_not_just_the_window(table, frozen_clock):
    """A percentile computed over one night would be a meaningless 'ever' claim
    (#1917 window honesty) — the context query must reach back to the start."""
    _seed(table, [strava_day("2026-08-06", [activity("X", distance_miles=1.0)])])
    en.enrich_date_range("2026-08-06", "2026-08-06")
    context_bounds = table.query_calls[0]["KeyConditionExpression"].get_expression()
    lower = [v for v in context_bounds["values"] if hasattr(v, "get_expression")][-1].get_expression()["values"][1]
    assert lower == "DATE#2000-01-01"


def test_a_day_with_no_activities_is_skipped_without_a_write(table, frozen_clock):
    _seed(table, [strava_day("2026-08-06", [])])
    result = en.enrich_date_range("2026-08-06", "2026-08-06")
    assert result["enriched"] == 0 and table.updates == []


def test_only_the_days_that_changed_are_written(table, frozen_clock):
    unchanged = activity("Old", distance_miles=1.0)
    unchanged["enriched_name"] = "Old · 1.0mi"
    _seed(
        table,
        [
            strava_day("2026-08-05", [unchanged]),
            strava_day("2026-08-06", [activity("New", distance_miles=2.0)]),
        ],
    )
    en.enrich_date_range("2026-08-05", "2026-08-06")
    assert [u["Key"]["sk"] for u in table.updates] == ["DATE#2026-08-06"]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): enrich_date_range() (enrichment_lambda.py:289) "
        "has no per-activity error boundary, and lambda_handler() re-raises "
        "(line 362). One malformed activity anywhere in the window therefore aborts "
        "the run, so every LATER day in the batch is silently left unenriched while "
        "the invocation reports a hard failure. Days already written stay written, so "
        "the archive is left half-enriched with no record of where it stopped."
    ),
)
def test_one_malformed_activity_does_not_abort_the_rest_of_the_batch(table, frozen_clock):
    _seed(
        table,
        [
            strava_day("2026-08-05", [{"name": None}]),
            strava_day("2026-08-06", [activity("Good", distance_miles=2.0)]),
        ],
    )
    en.enrich_date_range("2026-08-05", "2026-08-06")
    assert [u["Key"]["sk"] for u in table.updates] == ["DATE#2026-08-06"]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): a Strava day record that arrived without a "
        "`date` attribute is invisible to enrichment. enrich_date_range() filters the "
        "target window on `d.get('date', '')` (line 266) rather than on the `sk` it "
        "already queried by, so '' never falls inside the window and the day is "
        "skipped in silence — even though the sk-range query returned it. The two "
        "notions of 'which day is this' should not be allowed to disagree."
    ),
)
def test_a_day_identified_only_by_its_sort_key_is_still_enriched(table, frozen_clock):
    day = strava_day("2026-08-06", [activity("X", distance_miles=1.0)])
    del day["date"]
    _seed(table, [day])
    result = en.enrich_date_range("2026-08-06", "2026-08-06")
    assert result["days_processed"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — modes and the response contract
# ══════════════════════════════════════════════════════════════════════════════


def test_the_nightly_default_enriches_yesterday(table, frozen_clock):
    import json

    _seed(table, [strava_day(FROZEN_YESTERDAY, [activity("X", distance_miles=1.0)])])
    body = json.loads(en.lambda_handler({}, None)["body"])
    assert body["mode"] == "nightly"
    assert body["start_date"] == body["end_date"] == FROZEN_YESTERDAY


def test_an_explicit_range_is_honoured(table, frozen_clock):
    import json

    _seed(table, [strava_day("2026-08-01", [activity("X", distance_miles=1.0)])])
    body = json.loads(en.lambda_handler({"start_date": "2026-08-01", "end_date": "2026-08-03"}, None)["body"])
    assert (body["start_date"], body["end_date"], body["mode"]) == ("2026-08-01", "2026-08-03", "nightly")


def test_backfill_mode_defaults_its_end_to_today(table, frozen_clock):
    import json

    _seed(table, [])
    body = json.loads(en.lambda_handler({"backfill": True}, None)["body"])
    assert body["mode"] == "backfill" and body["end_date"] == FROZEN_TODAY


def test_the_response_reports_the_counts_the_run_actually_achieved(table, frozen_clock):
    import json

    _seed(table, [strava_day(FROZEN_YESTERDAY, [activity("A", distance_miles=1.0), activity("B", distance_miles=2.0)])])
    body = json.loads(en.lambda_handler({}, None)["body"])
    assert body["enriched"] == 2 and body["skipped"] == 0 and body["days_processed"] == 1


def test_the_handler_returns_a_two_hundred_on_a_clean_run(table, frozen_clock):
    _seed(table, [])
    assert en.lambda_handler({}, None)["statusCode"] == 200


def test_a_failed_read_surfaces_as_a_failed_invocation(monkeypatch, frozen_clock):
    """Re-raising is the contract — the ingestion-error alarm is what pages."""

    class Broken:
        def query(self, **kwargs):
            raise RuntimeError("ddb down")

    monkeypatch.setattr(en, "table", Broken())
    with pytest.raises(RuntimeError):
        en.lambda_handler({}, None)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): lambda_handler() (enrichment_lambda.py:339) "
        "requires BOTH start_date and end_date to honour an explicit range. An event "
        "carrying only `start_date` silently falls through to the nightly branch and "
        "enriches yesterday instead — the operator's requested window is discarded "
        "with no warning log and no error. Same shape as the #1917 window-honesty "
        "class: the run reports a window it was never asked for."
    ),
)
def test_a_one_sided_range_is_rejected_rather_than_silently_reinterpreted(table, frozen_clock):
    import json

    _seed(table, [])
    body = json.loads(en.lambda_handler({"start_date": "2026-07-01"}, None)["body"])
    assert body["start_date"] == "2026-07-01"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery): `{'backfill': true}` with no start_date "
        "defaults to 2020-01-01 (enrichment_lambda.py:336) while the percentile "
        "context query already reaches back to 2000-01-01 (line 259). The docstring "
        "calls this 'Full backfill', but any activity before 2020 is counted in the "
        "ranking population and never enriched itself — a silently partial backfill."
    ),
)
def test_a_full_backfill_covers_the_whole_archive_it_ranks_against(table, frozen_clock):
    import json

    _seed(table, [strava_day("2019-06-01", [activity("Ancient", distance_miles=1.0)])])
    body = json.loads(en.lambda_handler({"backfill": True}, None)["body"])
    assert body["days_processed"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Durability — enrichment vs. the next ingest of the same day
# ══════════════════════════════════════════════════════════════════════════════


def test_the_strava_writer_rebuilds_the_day_from_the_api_alone():
    """`transform()` composes the day record purely from the freshly-fetched
    activities, so nothing a later pass added to the stored record survives it."""
    day = sv.transform({"activities": [sv._normalize({"id": 1, "name": "Morning Run"})]}, "2026-08-06")[0]
    assert "enriched_name" not in day["activities"][0]


def test_the_strava_source_re_fetches_days_that_are_already_stored():
    """refresh_trailing_days is what puts enrichment and ingestion on a collision
    course — read from the source's own config, never asserted as a literal."""
    assert sv._config.refresh_trailing_days >= 1
    assert sv._config.refresh_today is True


# ── The real store path, not a simulation of it ───────────────────────────────
# #2250 is fixed in `ingestion_framework._store_item`, so the durability tests
# below drive THAT function with a bounded fake table. Asserting against a
# hand-rolled "simulated replace" would pin the simulation, not the pipeline.


class StoreTable:
    """`get_item`/`put_item` stand-in for the framework's store path.

    Holds exactly one item (the day being re-ingested) and records every call, so
    a test can assert both the merged result AND whether the read happened at all.
    """

    def __init__(self, item=None, get_raises=None):
        self.item = item
        self.puts = []
        self.get_calls = []
        self.get_raises = get_raises

    def get_item(self, Key):
        self.get_calls.append(Key)
        if self.get_raises:
            raise self.get_raises
        return {"Item": self.item} if self.item is not None else {}

    def put_item(self, Item):
        self.puts.append(Item)
        self.item = Item
        return {}


def _reingest(stored_day, fresh_day, config=None):
    """Store `fresh_day` over `stored_day` through the framework's real path.

    Returns the item that actually reached `put_item` — i.e. what the next
    reader of that partition would see.
    """
    import logging

    from ingestion import ingestion_framework as fw

    date_str = fresh_day["date"]
    key = {"pk": f"{en.USER_PREFIX}strava", "sk": f"DATE#{date_str}"}
    table = StoreTable({**key, **stored_day} if stored_day is not None else None)
    item = {**key, "source": "strava", **fresh_day}
    fw._store_item(table, None, config or sv._config, item, date_str, logging.getLogger("test-2250"))
    return table, table.puts[-1]


def _api_day(date_str="2026-08-06", activities=((1, "Morning Run"),)):
    """A day record exactly as strava_lambda builds it from an API response."""
    normalized = [sv._normalize({"id": i, "name": n, "distance": 4828.0}) for i, n in activities]
    return sv.transform({"activities": normalized}, date_str)[0]


def test_enrichment_survives_a_re_ingest_of_the_same_day():
    """#2250, the headline: the label the enricher wrote at 15:30 UTC is still
    there after the 16:10 UTC Strava run replaces the same day record."""
    stored = _api_day()
    stored["activities"][0]["enriched_name"] = "Issaquah, WA Run · 3.0mi"
    stored["activities"][0]["enriched_at"] = "2026-08-07T15:30:00+00:00"
    stored["enriched_at"] = "2026-08-07T15:30:00+00:00"

    _, written = _reingest(stored, _api_day())

    assert written["activities"][0]["enriched_name"] == "Issaquah, WA Run · 3.0mi"
    assert written["activities"][0]["enriched_at"] == "2026-08-07T15:30:00+00:00"
    assert written["enriched_at"] == "2026-08-07T15:30:00+00:00"


def test_the_label_follows_its_activity_when_a_late_arrival_shifts_the_list():
    """Late arrivals are the whole reason refresh_trailing_days exists, so the
    carry-forward must match on the activity's own id, never on list position."""
    stored = _api_day(activities=((1, "Morning Run"),))
    stored["activities"][0]["enriched_name"] = "Issaquah, WA Run · 3.0mi"

    # The re-fetch picks up an evening walk that sorts FIRST in the API response.
    _, written = _reingest(stored, _api_day(activities=((2, "Evening Walk"), (1, "Morning Run"))))

    by_id = {a["strava_id"]: a for a in written["activities"]}
    assert by_id["1"]["enriched_name"] == "Issaquah, WA Run · 3.0mi"
    assert "enriched_name" not in by_id["2"], "an activity the enricher never saw must not borrow a label"


def test_an_activity_the_store_never_had_carries_no_label():
    stored = _api_day(activities=((1, "Morning Run"),))
    stored["activities"][0]["enriched_name"] = "Issaquah, WA Run · 3.0mi"
    _, written = _reingest(stored, _api_day(activities=((9, "Brand New Hike"),)))
    assert "enriched_name" not in written["activities"][0]


def test_the_first_ingest_of_a_date_stores_plainly():
    """No stored record → nothing to carry, and no crash on the empty read."""
    table, written = _reingest(None, _api_day())
    assert table.get_calls == [{"pk": f"{en.USER_PREFIX}strava", "sk": "DATE#2026-08-06"}]
    assert "enriched_name" not in written["activities"][0]


def test_a_failed_read_of_the_stored_record_never_blocks_the_ingest():
    """Losing a label is bad; losing the day's data is worse."""
    import logging

    from ingestion import ingestion_framework as fw

    table = StoreTable({}, get_raises=RuntimeError("throttled"))
    item = {"pk": f"{en.USER_PREFIX}strava", "sk": "DATE#2026-08-06", "source": "strava", **_api_day()}
    fw._store_item(table, None, sv._config, item, "2026-08-06", logging.getLogger("test-2250"))
    assert len(table.puts) == 1


def test_a_source_with_no_downstream_writer_pays_nothing_for_the_hook():
    """The merge is opt-in per source: without carry_forward_fn the framework
    must not spend a read on every store."""
    from ingestion.ingestion_framework import IngestionConfig

    plain = IngestionConfig(source_name="strava")
    assert plain.carry_forward_fn is None
    table, _ = _reingest(_api_day(), _api_day(), config=plain)
    assert table.get_calls == []


def test_the_strava_source_actually_declares_the_merge():
    """Derived from the source's own config — the fix is inert if this is unset."""
    assert sv._config.carry_forward_fn is sv.carry_forward_enrichment


def test_the_carried_fields_are_exactly_the_ones_the_enricher_writes():
    """Guard the SET: if the enricher grows a third write-back field, the merge
    must grow with it rather than silently dropping it on the next ingest."""
    written_by_enricher = set()
    tree = ast.parse(open(MODULE_SRC, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            value = node.slice.value
            if isinstance(value, str) and value.startswith("enriched"):
                written_by_enricher.add(value)
    assert written_by_enricher, "AST derivation found nothing — the guard would be vacuous"
    assert written_by_enricher <= set(sv.ENRICHMENT_CARRY_FORWARD_FIELDS)


def test_the_weekly_digest_renders_the_label_that_survived_the_re_ingest():
    """End-to-end acceptance: a real downstream reader, fed the record that the
    real store path actually wrote after a re-ingest."""
    os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
    os.environ.setdefault("EMAIL_SENDER", "test@example.com")
    sys.path.insert(0, os.path.join(ROOT, "lambdas", "emails"))
    import weekly_digest_lambda as wd

    stored = _api_day()
    stored["activities"][0]["enriched_name"] = "Issaquah, WA Run · 3.0mi"
    _, written = _reingest(stored, _api_day())

    block = wd.ex_strava({"2026-08-06": written}, {"max_heart_rate": 186})
    assert block["activities"][0]["name"] == "Issaquah, WA Run · 3.0mi"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, docs): the module docstring "
        "(enrichment_lambda.py:3) states 'EventBridge: 06:00 UTC = 10pm PT'. The live "
        "schedule in cdk/stacks/ingestion_stack.py:427 is cron(30 15 * * ? *) — "
        "15:30 UTC. Nine and a half hours of drift on the one line an operator reads "
        "to decide when the nightly run happens, and it is the line that makes the "
        "'runs after all daily syncs complete' claim (which the 15:30 slot does not "
        "satisfy — Strava ingests hourly through 23:10 UTC)."
    ),
)
def test_the_docstring_states_the_schedule_the_stack_actually_deploys():
    stack = open(os.path.join(ROOT, "cdk", "stacks", "ingestion_stack.py"), encoding="utf-8").read()
    marker = stack.split('function_name="activity-enrichment"', 1)[1]
    schedule = marker.split("schedule=", 1)[1].split("\n", 1)[0]
    hour = schedule.split("(", 1)[1].split(" ")[1]
    assert f"{int(hour):02d}:" in en.__doc__


def test_the_enricher_and_the_strava_ingester_write_the_same_partition():
    """Both write USER#…#SOURCE#strava DATE# rows — which is precisely why the
    write-back has to coexist with the ingest, not race it."""
    assert sv._config.source_name == "strava"
    assert en.USER_PREFIX + "strava" == f"USER#{en.USER_ID}#SOURCE#strava"


# ══════════════════════════════════════════════════════════════════════════════
# floats_to_decimal — the shared conversion this module writes through
# ══════════════════════════════════════════════════════════════════════════════


def test_booleans_survive_the_decimal_conversion_as_booleans():
    """`isinstance(True, int)` is a classic trap — a flipped flag would rewrite
    every activity's `trainer`/`commute`/`private` marker."""
    converted = en.floats_to_decimal({"private": True, "commute": False})
    assert converted["private"] is True and converted["commute"] is False


def test_nested_activity_floats_are_converted_at_every_depth():
    converted = en.floats_to_decimal({":acts": [{"distance_miles": 6.2, "hr_recovery": {"hr_peak": 170.5}}]})
    assert find_floats(converted) == []


def test_the_yesterday_the_handler_targets_is_one_day_before_today(frozen_clock):
    """Hand-derived: the frozen clock is 2026-08-07T15:30Z, so yesterday is the
    6th — no month or DST boundary involved."""
    assert (FROZEN_NOW - timedelta(days=1)).strftime("%Y-%m-%d") == FROZEN_YESTERDAY
