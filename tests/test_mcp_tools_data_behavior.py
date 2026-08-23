"""tests/test_mcp_tools_data_behavior.py — behavioural contracts for
``mcp/tools_data.py`` (#1658 coverage tranche 5).

Measured 10.2% covered before this file (158 of 176 statements missing). This
is the generic data-access surface — ``get_sources``, ``get_daily_snapshot``,
``get_date_range``, ``find_days``, ``search_activities``,
``get_intelligence_quality`` — i.e. the tools Claude Desktop reaches for when
the question isn't domain-specific. Every one of them was unexercised.

Contracts pinned here:

  * **ADR-058 phase filtering is applied on the read, not hoped for.** Every
    query this module issues without ``include_pilot`` must carry the phase
    FilterExpression; the assertion reads the kwargs the fake table received,
    and it is derived from ``mcp.core``'s own constant rather than restated.
  * **The aggregation switch is a window-size decision with a named boundary.**
    ``RAW_DAY_LIMIT`` days is raw; one day more is monthly; beyond two years is
    yearly. Both sides of both boundaries are pinned.
  * **A filter that cannot be evaluated must not silently match.** ``find_days``
    filters are the tool's whole point — a filter on a field the record does
    not carry excludes the day.
  * **Percentile context is all-time, not window-relative** — the rank comes
    from the full activity population read, so a "top 1%" claim means what it
    says (ADR-105).
  * **Absence is absence** — ``get_sources`` reports ``available: False`` for a
    partition with no dated record rather than inventing a date, and a record
    missing its ``date`` attribute does not raise.

No AWS, no network: the DynamoDB table and ``query_source`` are replaced with
bounded fakes. Arithmetic is hand-derived in the body.
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402

from mcp import core as mcore, tools_data as td  # noqa: E402

PHASE_EXPR = mcore._PHASE_FILTER_EXPRESSION


# ──────────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────────


class _FakeTable:
    """Records every query kwargs and replays canned pages."""

    def __init__(self, responder=None):
        self.calls: list[dict] = []
        self._responder = responder or (lambda kwargs, n: {"Items": []})

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return self._responder(kwargs, len(self.calls))


@pytest.fixture()
def fake_table(monkeypatch):
    def _install(responder=None, sources=("whoop", "withings")):
        t = _FakeTable(responder)
        monkeypatch.setattr(td, "table", t)
        monkeypatch.setattr(td, "SOURCES", list(sources))
        return t

    return _install


@pytest.fixture()
def fake_query_source(monkeypatch):
    def _install(items):
        calls: list[tuple] = []

        def _q(source, start_date, end_date, **kw):
            calls.append((source, start_date, end_date, kw))
            return list(items)

        _q.calls = calls  # type: ignore[attr-defined]
        monkeypatch.setattr(td, "query_source", _q)
        return _q

    return _install


# ──────────────────────────────────────────────────────────────────────────────
# tool_get_sources
# ──────────────────────────────────────────────────────────────────────────────


def test_get_sources_reports_first_and_latest_per_source(fake_table):
    def responder(kwargs, n):
        # Two queries per source: oldest (ScanIndexForward=True) then newest.
        oldest = kwargs["ScanIndexForward"]
        if n <= 2:  # whoop
            return {"Items": [{"sk": "DATE#2025-01-01" if oldest else "DATE#2026-08-07", "date": "2025-01-01" if oldest else "2026-08-07"}]}
        return {"Items": []}  # withings has nothing

    t = fake_table(responder)
    out = td.tool_get_sources({})

    assert out["whoop"] == {"available": True, "first_date": "2025-01-01", "latest_date": "2026-08-07", "state": "stale"}
    assert out["withings"] == {"available": False, "first_date": None, "latest_date": None, "state": "stale"}
    assert len(t.calls) == 4, "two bounded Limit=1 probes per source, never a scan"
    assert all(c["Limit"] == 1 for c in t.calls)
    # #2671: the projection now pulls `sk` as well, because the sk is the authoritative
    # copy of the date and the `date` attribute is a duplicate that is not always written.
    assert all(c["ProjectionExpression"] == "sk, #dt" for c in t.calls), "existence probe must not pull the whole row"


def test_get_sources_probes_only_inside_the_date_key_space(fake_table):
    """#2671: unconstrained edge queries let a marker row decide availability.

    apple_health's lexically-first row is `ALERTSTATE#ah_activity_degraded` and
    food_delivery's last is `YEAR#2026`; both are real, neither is an observation. Every
    domain tool ranges inside `DATE#`, so this must too — that is the single truth source.
    """
    t = fake_table(lambda kwargs, n: {"Items": []}, sources=("whoop",))
    td.tool_get_sources({})
    for call in t.calls:
        expr = call["KeyConditionExpression"].get_expression()
        sk_cond = expr["values"][1].get_expression()
        assert sk_cond["operator"] == "begins_with" and sk_cond["values"][1] == "DATE#", call


def test_get_sources_survives_a_record_with_no_date_attribute(fake_table):
    """2026-05-03 regression, AMENDED BY #2671. Two halves; one stands, one is overturned.

    The original: a partition record with no `date` field raised KeyError and tanked the
    whole tool. That must never come back, and does not — nothing here raises.

    What that fix left behind is what #2671 is about. It answered the KeyError with
    `.get()` and therefore with `available: False`, so a DATE# row whose duplicate `date`
    attribute simply was not written read as "this source has no data" — the crash became
    silence. Live, that was labs: `DATE#2019-05-01`, no `date` attribute, seven years of
    bloodwork reported absent. The sk is what the write built the key from, so the sk is
    what gets read.
    """
    fake_table(lambda kwargs, n: {"Items": [{"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2019-05-01"}]}, sources=("whoop",))
    out = td.tool_get_sources({})
    assert out["whoop"]["available"] is True, "a DATE# row is data whether or not the duplicate attribute was written"
    assert (out["whoop"]["first_date"], out["whoop"]["latest_date"]) == ("2019-05-01", "2019-05-01")


def test_get_sources_reports_a_row_it_cannot_date_as_absent_rather_than_guessing(fake_table):
    """The other side of the same rule: no sk date and no attribute means no claim."""
    fake_table(lambda kwargs, n: {"Items": [{"pk": "USER#matthew#SOURCE#whoop", "sk": "ALERTSTATE#degraded"}]}, sources=("whoop",))
    out = td.tool_get_sources({})
    assert out["whoop"]["first_date"] is None and out["whoop"]["latest_date"] is None


# ──────────────────────────────────────────────────────────────────────────────
# tool_get_daily_snapshot — view routing
# ──────────────────────────────────────────────────────────────────────────────


def test_daily_snapshot_rejects_an_unknown_view_with_the_valid_set(fake_table):
    fake_table()
    out = td.tool_get_daily_snapshot({"view": "wibble"})
    assert out["error"].startswith("Unknown view 'wibble'")
    assert set(out["valid_views"]) == {"summary", "latest"}
    assert "hint" in out


def test_daily_snapshot_defaults_to_summary_and_requires_a_date(fake_table):
    fake_table()
    with pytest.raises(ValueError, match="'date' is required"):
        td.tool_get_daily_snapshot({})


@pytest.mark.parametrize("view", ["LATEST", "  latest  ", "latest"])
def test_daily_snapshot_view_is_case_and_whitespace_insensitive(fake_table, view):
    fake_table()
    out = td.tool_get_daily_snapshot({"view": view})
    assert set(out) == {"whoop", "withings"}, "the latest view answers for every source, even empty ones"


def test_latest_view_returns_none_for_a_source_with_no_records(fake_table):
    def responder(kwargs, n):
        return {"Items": [{"date": "2026-08-07", "recovery_score": 55}]} if n == 1 else {"Items": []}

    fake_table(responder)
    out = td.tool_get_daily_snapshot({"view": "latest"})
    assert out["whoop"]["recovery_score"] == 55
    assert out["withings"] is None, "absent is None, not {} or 0 (ADR-104)"


def test_summary_view_omits_sources_with_no_row_for_the_date(fake_table):
    def responder(kwargs, n):
        return {"Items": [{"date": "2026-08-07", "recovery_score": 55}]} if n == 1 else {"Items": []}

    fake_table(responder)
    out = td.tool_get_daily_snapshot({"view": "summary", "date": "2026-08-07"})
    assert list(out) == ["whoop"], "a source with no row that day is absent from the payload entirely"


def test_latest_and_summary_apply_the_phase_filter_unless_pilot_is_requested(fake_table):
    t = fake_table()
    td.tool_get_daily_snapshot({"view": "latest"})
    assert all(c["FilterExpression"] == PHASE_EXPR for c in t.calls)
    assert all(c["ExpressionAttributeValues"] == {":phase_experiment": "experiment"} for c in t.calls)

    t2 = fake_table()
    td.tool_get_daily_snapshot({"view": "latest", "include_pilot": True})
    assert all("FilterExpression" not in c for c in t2.calls), "include_pilot must lift the ADR-058 filter"

    t3 = fake_table()
    td.tool_get_daily_snapshot({"view": "summary", "date": "2026-08-07"})
    assert all(c["FilterExpression"] == PHASE_EXPR for c in t3.calls)


# ──────────────────────────────────────────────────────────────────────────────
# tool_get_date_range
# ──────────────────────────────────────────────────────────────────────────────


def test_get_date_range_requires_all_three_arguments():
    for args in ({}, {"source": "whoop"}, {"source": "whoop", "start_date": "2026-01-01"}):
        with pytest.raises(ValueError, match="are required"):
            td.tool_get_date_range(args)


def test_get_date_range_rejects_an_unknown_source():
    with pytest.raises(ValueError, match="Unknown source 'nope'"):
        td.tool_get_date_range({"source": "nope", "start_date": "2026-01-01", "end_date": "2026-01-02"})


def test_get_date_range_returns_raw_at_the_limit_and_aggregates_one_day_past_it(fake_table, fake_query_source):
    fake_table()
    rows = [{"date": "2026-01-15", "weight_lbs": 320}, {"date": "2026-02-15", "weight_lbs": 310}]
    fake_query_source(rows)

    # RAW_DAY_LIMIT is 90; a window of exactly 90 days is still raw.
    at_limit = td.tool_get_date_range({"source": "whoop", "start_date": "2026-01-01", "end_date": "2026-04-01"})
    assert td.date_diff_days("2026-01-01", "2026-04-01") == 90
    assert at_limit["note"] == "Raw daily data."
    assert at_limit["items"] == rows
    assert "aggregated" not in at_limit

    past = td.tool_get_date_range({"source": "whoop", "start_date": "2026-01-01", "end_date": "2026-04-02"})
    assert past["period"] == "month"
    assert "91 days" in past["note"]
    # Hand-derived: two monthly buckets, one row each.
    assert [b["period"] for b in past["aggregated"]] == ["2026-01", "2026-02"]
    assert past["aggregated"][0]["weight_lbs_avg"] == 320


def test_get_date_range_switches_to_yearly_past_two_years(fake_table, fake_query_source):
    fake_table()
    fake_query_source([{"date": "2024-05-01", "weight_lbs": 340}, {"date": "2026-05-01", "weight_lbs": 320}])
    out = td.tool_get_date_range({"source": "whoop", "start_date": "2024-01-01", "end_date": "2026-06-01"})
    assert out["period"] == "year"
    assert [b["period"] for b in out["aggregated"]] == ["2024", "2026"]


# ──────────────────────────────────────────────────────────────────────────────
# tool_find_days
# ──────────────────────────────────────────────────────────────────────────────


DAYS = [
    {"date": "2026-08-01", "recovery_score": 30, "hrv": 40},
    {"date": "2026-08-02", "recovery_score": 70, "hrv": 60},
    {"date": "2026-08-03", "recovery_score": 70},  # no hrv attribute at all
]


def test_find_days_requires_source_and_both_dates():
    with pytest.raises(ValueError, match="are required"):
        td.tool_find_days({"source": "whoop", "start_date": "2026-08-01"})


# Hand-derived expectations, one row per operator. The coverage test below pins
# this list to the FIND_DAYS_OPERATORS dispatch table, so adding an operator to
# the table without a behaviour row here fails the suite (#2306).
OPERATOR_CASES = [
    (">", 50, ["2026-08-02", "2026-08-03"]),
    (">=", 70, ["2026-08-02", "2026-08-03"]),
    ("<", 70, ["2026-08-01"]),
    ("<=", 30, ["2026-08-01"]),
    ("=", 70, ["2026-08-02", "2026-08-03"]),
]


def test_find_days_operator_cases_cover_the_dispatch_table():
    """Guard the SET: every operator the tool supports has a behaviour case."""
    assert {op for op, _, _ in OPERATOR_CASES} == set(td.FIND_DAYS_OPERATORS)


@pytest.mark.parametrize("op,value,expected_dates", OPERATOR_CASES)
def test_find_days_applies_each_comparison_operator(fake_query_source, op, value, expected_dates):
    fake_query_source(DAYS)
    got = td.tool_find_days(
        {
            "source": "whoop",
            "start_date": "2026-08-01",
            "end_date": "2026-08-03",
            "filters": [{"field": "recovery_score", "op": op, "value": value}],
        }
    )
    assert [d["date"] for d in got] == expected_dates


def test_find_days_excludes_a_day_that_lacks_the_filtered_field(fake_query_source):
    """A missing attribute is not a 0 and not a pass — the day drops out."""
    fake_query_source(DAYS)
    got = td.tool_find_days(
        {"source": "whoop", "start_date": "2026-08-01", "end_date": "2026-08-03", "filters": [{"field": "hrv", "op": ">=", "value": 0}]}
    )
    assert [d["date"] for d in got] == ["2026-08-01", "2026-08-02"]


def test_find_days_ands_multiple_filters(fake_query_source):
    fake_query_source(DAYS)
    got = td.tool_find_days(
        {
            "source": "whoop",
            "start_date": "2026-08-01",
            "end_date": "2026-08-03",
            "filters": [{"field": "recovery_score", "op": ">=", "value": 70}, {"field": "hrv", "op": ">", "value": 50}],
        }
    )
    assert [d["date"] for d in got] == ["2026-08-02"]


def test_find_days_with_no_filters_returns_the_window(fake_query_source):
    fake_query_source(DAYS)
    assert len(td.tool_find_days({"source": "whoop", "start_date": "2026-08-01", "end_date": "2026-08-03"})) == 3


def test_find_days_resolves_field_aliases_through_core(fake_query_source, monkeypatch):
    monkeypatch.setattr(td, "resolve_field", lambda source, field: {"recovery": "recovery_score"}.get(field, field))
    fake_query_source(DAYS)
    got = td.tool_find_days(
        {
            "source": "whoop",
            "start_date": "2026-08-01",
            "end_date": "2026-08-03",
            "filters": [{"field": "recovery", "op": ">", "value": 50}],
        }
    )
    assert [d["date"] for d in got] == ["2026-08-02", "2026-08-03"]


def test_find_days_slims_oversized_result_sets_to_the_key_fields(fake_query_source):
    rows = [{"date": f"2026-{m:02d}-{d:02d}", "recovery_score": 60, "note": "x" * 50} for m in (1, 2, 3, 4, 5, 6, 7) for d in range(1, 31)]
    assert len(rows) == 210
    fake_query_source(rows)
    got = td.tool_find_days({"source": "whoop", "start_date": "2026-01-01", "end_date": "2026-07-30"})
    assert len(got) == 210
    assert all("note" not in r for r in got), "over 200 matches, the payload projects down to key fields"
    assert all(set(r) == {"date", "recovery_score"} for r in got)


def test_find_days_under_the_slim_threshold_keeps_every_field(fake_query_source):
    rows = [{"date": f"2026-01-{d:02d}", "recovery_score": 60, "note": "keep me"} for d in range(1, 31)]
    fake_query_source(rows)
    got = td.tool_find_days({"source": "whoop", "start_date": "2026-01-01", "end_date": "2026-01-30"})
    assert all(r["note"] == "keep me" for r in got)


@pytest.mark.parametrize("bad_op", ["!=", "==", ">>", None])
def test_find_days_unknown_operator_raises_naming_it_and_the_supported_set(fake_query_source, bad_op):
    """An unrecognised operator errors instead of matching every day (#2306).

    The message names the offending operator and lists the supported set,
    which is read from the dispatch table itself — never hand-listed.
    """
    fake_query_source(DAYS)
    with pytest.raises(ValueError) as excinfo:
        td.tool_find_days(
            {
                "source": "whoop",
                "start_date": "2026-08-01",
                "end_date": "2026-08-03",
                "filters": [{"field": "recovery_score", "op": bad_op, "value": 70}],
            }
        )
    msg = str(excinfo.value)
    assert f"'{bad_op}'" in msg
    for supported in td.FIND_DAYS_OPERATORS:
        assert supported in msg


# ──────────────────────────────────────────────────────────────────────────────
# Tier-2 privacy strip (#2809) — the generic row dumpers must never hand withings'
# owner-only trio (vascular_age / metabolic_age / afib_result) into conversation
# context. docs/SCHEMA.md:327 previously (and falsely) recorded every consumer as
# field-selective; these four ARE the dumpers that weren't. Field NAMES only below —
# no real measurement values, per the public-repo privacy discipline.
# ──────────────────────────────────────────────────────────────────────────────

TIER2_TRIO = {"vascular_age", "metabolic_age", "afib_result"}


def _withings_row(**extra):
    row = {"date": "2026-08-15", "weight_lbs": 180, "vascular_age": 40, "metabolic_age": 38, "afib_result": 0}
    row.update(extra)
    return row


def test_get_sources_derived_tier2_fixture_actually_carries_the_trio():
    """Vacuity guard: if the fixture didn't carry the trio, every assertion below
    would pass whether or not the strip exists."""
    assert TIER2_TRIO <= set(_withings_row())


def test_latest_view_strips_tier2_fields_for_withings(fake_table):
    def responder(kwargs, n):
        return {"Items": [{"date": "2026-08-07", "recovery_score": 55}]} if n == 1 else {"Items": [_withings_row()]}

    fake_table(responder)
    out = td.tool_get_daily_snapshot({"view": "latest"})
    assert out["withings"]["weight_lbs"] == 180, "non-Tier-2 fields must survive the strip"
    assert not (TIER2_TRIO & set(out["withings"])), out["withings"]
    assert not (TIER2_TRIO & set(out["whoop"])), "the strip must not touch a source with no Tier-2 facet's own fields"


def test_summary_view_strips_tier2_fields_for_withings(fake_table):
    def responder(kwargs, n):
        return {"Items": [_withings_row()]} if n == 2 else {"Items": []}

    fake_table(responder)
    out = td.tool_get_daily_snapshot({"view": "summary", "date": "2026-08-15"})
    assert list(out) == ["withings"]
    assert not (TIER2_TRIO & set(out["withings"][0])), out["withings"][0]
    assert out["withings"][0]["weight_lbs"] == 180


def test_get_date_range_strips_tier2_fields_in_the_raw_path(fake_table, fake_query_source):
    fake_table()
    fake_query_source([_withings_row()])
    out = td.tool_get_date_range({"source": "withings", "start_date": "2026-08-01", "end_date": "2026-08-15"})
    assert out["note"] == "Raw daily data."
    assert not (TIER2_TRIO & set(out["items"][0])), out["items"][0]
    assert out["items"][0]["weight_lbs"] == 180


def test_get_date_range_does_not_strip_a_source_with_no_tier2_facet(fake_table, fake_query_source):
    """The control: a source outside TIER2_STRIP_FIELDS is untouched by the strip."""
    fake_table()
    rows = [{"date": "2026-08-07", "recovery_score": 55}]
    fake_query_source(rows)
    out = td.tool_get_date_range({"source": "whoop", "start_date": "2026-08-01", "end_date": "2026-08-15"})
    assert out["items"] == rows


def test_find_days_strips_tier2_fields_from_matched_rows(fake_query_source):
    fake_query_source([_withings_row()])
    got = td.tool_find_days(
        {
            "source": "withings",
            "start_date": "2026-08-01",
            "end_date": "2026-08-15",
            "filters": [{"field": "weight_lbs", "op": ">", "value": 0}],
        }
    )
    assert len(got) == 1
    assert not (TIER2_TRIO & set(got[0])), got[0]
    assert got[0]["weight_lbs"] == 180


def test_tier2_strip_fields_registry_matches_the_declared_registry():
    """Structural guard: the strip set IS the field_tiers derivation — it still covers
    docs/SCHEMA.md's PhenoAge-posture trio (a partial strip is a leak), and it cannot
    be wider or narrower than the registry declares (#3045 widened the declared set
    deliberately, per ADR-155; owner-published fields like weight_lbs must NOT appear —
    strip_map() excludes them by construction, so the owner's row dumps are never
    stricter than the public site)."""
    from privacy.field_tiers import strip_map

    assert td.TIER2_STRIP_FIELDS["withings"] >= TIER2_TRIO
    assert {s: set(f) for s, f in td.TIER2_STRIP_FIELDS.items()} == {s: set(f) for s, f in strip_map().items()}
    assert "weight_lbs" not in td.TIER2_STRIP_FIELDS["withings"]
    assert "hrv" not in td.TIER2_STRIP_FIELDS.get("whoop", frozenset())


# ──────────────────────────────────────────────────────────────────────────────
# tool_search_activities
# ──────────────────────────────────────────────────────────────────────────────


def _day(date_str, *acts):
    return {"date": date_str, "activities": list(acts)}


ACT_DAYS = [
    _day("2026-01-01", {"name": "Morning Ride", "sport_type": "Ride", "distance_miles": 10, "total_elevation_gain_feet": 500}),
    _day("2026-02-01", {"name": "Long Ride", "sport_type": "Ride", "distance_miles": 60, "total_elevation_gain_feet": 4000}),
    _day("2026-03-01", {"name": "Recovery Walk", "sport_type": "Walk", "distance_miles": 2, "total_elevation_gain_feet": 20}),
    _day("2026-04-01", {"name": "Tempo Run", "enriched_name": "Threshold session", "sport_type": "Run", "distance_miles": 6}),
]


@pytest.fixture()
def act_query(monkeypatch, fake_query_source):
    monkeypatch.setattr(td, "get_sot", lambda domain: "strava")
    return fake_query_source(ACT_DAYS)


def test_search_activities_reads_the_cardio_source_of_truth(act_query):
    td.tool_search_activities({})
    assert act_query.calls[0][0] == "strava"


def test_search_activities_sorts_descending_and_reports_totals(act_query):
    out = td.tool_search_activities({})
    assert out["sorted_by"] == "distance_miles"
    assert out["total_matched"] == 4
    assert out["showing"] == 4
    assert out["all_time_total_acts"] == 4
    assert [a["name"] for a in out["activities"]] == ["Long Ride", "Morning Ride", "Tempo Run", "Recovery Walk"]


def test_search_activities_percentile_is_all_time_and_hand_derivable(act_query):
    out = td.tool_search_activities({})
    by_name = {a["name"]: a for a in out["activities"]}
    # Sorted distances all-time: [2, 6, 10, 60]. bisect_left gives the count of
    # strictly-smaller values; rank = 100 * pos / 4.
    assert by_name["Recovery Walk"]["distance_miles_all_time_percentile"] == 0.0  # pos 0
    assert by_name["Tempo Run"]["distance_miles_all_time_percentile"] == 25.0  # pos 1
    assert by_name["Morning Ride"]["distance_miles_all_time_percentile"] == 50.0  # pos 2
    assert by_name["Long Ride"]["distance_miles_all_time_percentile"] == 75.0  # pos 3


def test_search_activities_labels_only_the_genuine_top_tail(act_query):
    out = td.tool_search_activities({})
    assert all("context" not in a for a in out["activities"]), "a 4-activity corpus has no 90th-percentile claim to make"


def test_search_activities_top_tail_context_bands():
    """The three bands are 99 / 95 / 90 — checked against a population large
    enough that a percentile means something (ADR-105)."""
    days = [_day(f"2026-01-{i:02d}", {"name": f"a{i}", "sport_type": "Ride", "distance_miles": i}) for i in range(1, 101)]

    def _q(source, start, end, **kw):
        return days

    import mcp.tools_data as mod

    orig_q, orig_sot = mod.query_source, mod.get_sot
    mod.query_source, mod.get_sot = _q, (lambda d: "strava")
    try:
        out = mod.tool_search_activities({"limit": 100})
    finally:
        mod.query_source, mod.get_sot = orig_q, orig_sot

    by_name = {a["name"]: a for a in out["activities"]}
    assert by_name["a100"]["context"] == "ALL-TIME top 1% for distance_miles"  # pos 99 → 99.0
    assert by_name["a97"]["context"] == "Top 5% all-time for distance_miles"  # pos 96 → 96.0
    assert by_name["a92"]["context"] == "Top 10% all-time for distance_miles"  # pos 91 → 91.0
    assert "context" not in by_name["a50"]


def test_search_activities_name_filter_matches_the_enriched_name_too(act_query):
    out = td.tool_search_activities({"name_contains": "THRESHOLD"})
    assert [a["name"] for a in out["activities"]] == ["Tempo Run"]


def test_search_activities_sport_type_is_a_case_insensitive_substring(act_query):
    out = td.tool_search_activities({"sport_type": "ride"})
    assert {a["name"] for a in out["activities"]} == {"Morning Ride", "Long Ride"}


def test_search_activities_minimum_filters_drop_activities_missing_the_field(act_query):
    out = td.tool_search_activities({"min_elevation_gain_feet": 100})
    assert {a["name"] for a in out["activities"]} == {
        "Morning Ride",
        "Long Ride",
    }, "Tempo Run has no elevation field and cannot clear a floor"

    out2 = td.tool_search_activities({"min_distance_miles": 10})
    assert {a["name"] for a in out2["activities"]} == {"Morning Ride", "Long Ride"}


def test_search_activities_limit_truncates_the_page_not_the_match_count(act_query):
    out = td.tool_search_activities({"limit": 2})
    assert out["total_matched"] == 4
    assert out["showing"] == 2
    assert [a["name"] for a in out["activities"]] == ["Long Ride", "Morning Ride"]


def test_search_activities_on_an_empty_corpus_reports_no_percentiles(monkeypatch, fake_query_source):
    monkeypatch.setattr(td, "get_sot", lambda domain: "strava")
    fake_query_source([])
    out = td.tool_search_activities({})
    # `population` (#2331) names what `all_time_total_acts` counts — it is a definition,
    # not a measurement, so it is stated even when the corpus is empty and no percentile
    # is claimed. That is the point: the denominator's meaning does not depend on data.
    assert out == {
        "total_matched": 0,
        "showing": 0,
        "sorted_by": "distance_miles",
        "all_time_total_acts": 0,
        "population": td._population_label("distance_miles"),
        "activities": [],
    }


# ──────────────────────────────────────────────────────────────────────────────
# tool_get_intelligence_quality
# ──────────────────────────────────────────────────────────────────────────────


QUALITY_ROWS = [
    {
        "date": "2026-08-06",
        "coach_id": "physiology",
        "domain": "recovery",
        "checks_run": 4,
        "flags": [
            {"severity": "error", "check": "null_claim_vs_data", "message": "claimed a number with no data"},
            {"severity": "warning", "check": "stale_action", "message": "action is 20 days old"},
        ],
    },
    {
        "date": "2026-08-07",
        "coach_id": "nutrition",
        "domain": "fuel",
        "checks_run": 4,
        "flags": [{"severity": "warning", "check": "overconfidence", "message": "unearned certainty"}],
    },
]


@pytest.fixture()
def quality_table(monkeypatch):
    def _install(rows=QUALITY_ROWS, boom=None):
        t = _FakeTable(lambda kwargs, n: {"Items": list(rows)})
        if boom:

            def _raise(**kwargs):
                raise RuntimeError(boom)

            t.query = _raise  # type: ignore[assignment]
        monkeypatch.setattr(mcore, "table", t)
        return t

    return _install


def test_intelligence_quality_queries_the_profile_partition_with_the_phase_filter(quality_table):
    t = quality_table()
    td.tool_get_intelligence_quality({"days": 7})
    (kwargs,) = t.calls
    assert kwargs["FilterExpression"] == PHASE_EXPR
    assert "KeyConditionExpression" in kwargs


def test_intelligence_quality_flattens_flags_with_their_provenance(quality_table):
    quality_table()
    out = td.tool_get_intelligence_quality({})
    assert out["total_flags"] == 3
    assert out["errors"] == 1
    assert out["warnings"] == 2
    first = out["flags"][0]
    assert first["date"] == "2026-08-06" and first["coach"] == "physiology" and first["domain"] == "recovery"
    assert first["check"] == "null_claim_vs_data", "the flag's own fields survive the merge"
    assert sorted(out["coaches_checked"]) == ["nutrition", "physiology"]


def test_intelligence_quality_severity_and_coach_filters(quality_table):
    quality_table()
    only_errors = td.tool_get_intelligence_quality({"severity": "error"})
    assert only_errors["total_flags"] == 1 and only_errors["errors"] == 1 and only_errors["warnings"] == 0

    only_nutrition = td.tool_get_intelligence_quality({"coach": "nutrition"})
    assert only_nutrition["coaches_checked"] == ["nutrition"]
    assert only_nutrition["total_flags"] == 1


def test_intelligence_quality_window_matches_the_requested_day_count(quality_table):
    quality_table()
    out = td.tool_get_intelligence_quality({"days": 30})
    from datetime import date as _d

    span = (_d.fromisoformat(out["period"]["end"]) - _d.fromisoformat(out["period"]["start"])).days
    assert span == 30, "#1917: a window named for N days spans N days"


def test_intelligence_quality_caps_the_flag_list_but_not_the_counts(quality_table):
    many = [{"date": "2026-08-06", "coach_id": "c", "domain": "d", "checks_run": 4, "flags": [{"severity": "warning"}] * 50}]
    quality_table(many)
    out = td.tool_get_intelligence_quality({})
    assert out["total_flags"] == 50
    assert len(out["flags"]) == 20, "the payload is capped for readability; the tally is not"


def test_intelligence_quality_surfaces_a_query_failure_as_an_error_payload(quality_table):
    quality_table(boom="ProvisionedThroughputExceeded")
    out = td.tool_get_intelligence_quality({})
    assert "ProvisionedThroughputExceeded" in out["error"]
    assert set(out) == {"error"}, "a failed read must not also report zero flags as if it had looked"


def test_intelligence_quality_total_checks_is_the_sum_of_each_rows_own_checks_run(quality_table):
    # #2305: the denominator comes from what the validator actually stored per
    # row — heterogeneous counts, so no `len(items) * K` can reproduce the sum
    # (2 rows, total 7: any uniform multiplier gives an even number).
    rows = [
        {"date": "2026-08-06", "coach_id": "physiology", "domain": "recovery", "checks_run": 4, "flags": []},
        {"date": "2026-08-07", "coach_id": "nutrition", "domain": "fuel", "checks_run": 3, "flags": []},
    ]
    quality_table(rows)
    out = td.tool_get_intelligence_quality({})
    assert out["total_checks"] == 7, "total_checks must follow the rows' own checks_run, not a per-coach constant"

    # The default fixture too: rows store the writer's derived count.
    quality_table()
    out = td.tool_get_intelligence_quality({})
    assert out["total_checks"] == sum(r["checks_run"] for r in QUALITY_ROWS)


def test_intelligence_quality_a_row_missing_checks_run_contributes_nothing_not_a_fabricated_count(quality_table):
    # #2305 acceptance: a row without checks_run is excluded from the
    # denominator — it must not be backfilled with any assumed check count.
    rows = [
        {"date": "2026-08-06", "coach_id": "physiology", "domain": "recovery", "checks_run": 4, "flags": []},
        {"date": "2026-08-07", "coach_id": "nutrition", "domain": "fuel", "flags": []},  # no checks_run
    ]
    quality_table(rows)
    out = td.tool_get_intelligence_quality({})
    assert out["total_checks"] == 4, "a row missing checks_run is absent from the denominator, never invented"


def test_guard_intelligence_quality_reader_carries_no_hand_typed_check_count():
    """#2305 set-guard: the reader must never re-learn the validator's check count.

    The forbidden band is DERIVED from ``_VALIDATOR_CHECKS`` (never hand-typed
    here): any integer literal within ±1 of the registry's size appearing in
    the reader's source is treated as a re-introduced hand-typed check count —
    that band catches both the historical ``* 5`` (off-by-one against the
    4-check registry) and a "corrected" ``* 4`` that would silently drift the
    next time the check set changes. Legitimate literals in the reader (the
    7-day default window, the 20-flag display cap) sit outside the band.
    """
    import ast
    import inspect
    import textwrap

    from intelligence.intelligence_common import _VALIDATOR_CHECKS

    n = len(_VALIDATOR_CHECKS)
    forbidden = {n - 1, n, n + 1}
    tree = ast.parse(textwrap.dedent(inspect.getsource(td.tool_get_intelligence_quality)))
    offenders = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool) and node.value in forbidden
    ]
    assert not offenders, (
        f"hand-typed check count(s) {offenders} in tool_get_intelligence_quality — "
        f"the validator registry has {n} checks ({', '.join(_VALIDATOR_CHECKS)}); "
        "the denominator must be summed from each row's stored checks_run, never a literal"
    )
