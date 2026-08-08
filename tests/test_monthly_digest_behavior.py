"""tests/test_monthly_digest_behavior.py — behavioural contracts for the Monthly
Coach's Letter (`lambdas/emails/monthly_digest_lambda.py`).

Before this file the module's only coverage was the presence-block injection
assertion in tests/test_presence_injection_emails.py (two tests against
`call_haiku_monthly`). Nothing pinned the month windows, the extractors, the
annual-goal arithmetic, the HTML a reader actually reads, or the handler — which
is where a monthly email's defects live, because a monthly email is wrong for a
whole month before anyone notices.

What this file covers:

  * `get_date_windows` — the calendar-month labels vs the rolling 30-day windows
    they are attached to (the load-bearing month-boundary arithmetic);
  * the `ex_*` extractor family + `compute_annual_goals`, pinned to hand-derived
    arithmetic with the derivation written out (never "whatever the code
    returns");
  * ADR-104 honest numbers: a month with no logged food / no activities / no
    weigh-ins must not surface as a confident 0, and a rate must not be
    published over an n it wasn't computed from;
  * ADR-105: the n behind every published average;
  * ADR-058 phase scoping — cross-phase sources widen, experiment-scoped ones
    default-deny;
  * what `build_html` shows a reader (which figures, which rows, which sections
    are absent) — not the CSS;
  * `lambda_handler`, which NEVER sends mail here: `ses` is always a fake, no
    deployed Lambda is ever invoked, and nothing reaches AWS or Bedrock.

Clock discipline: this is a MONTHLY sender, so month-boundary and weekday logic
is load-bearing. Every test that touches "now" freezes it — `_FrozenDatetime`
for the module's `datetime`, and `_FrozenDate` swapped onto the stdlib
`datetime` module for the handler's function-local `from datetime import date`.
No test ever combines a fixture date with a real `datetime.now()`.

Fakes are hand-rolled and bounded; no MagicMock appears inside a loop- or
pagination-shaped read.

Tests that document a DEFECT in current behaviour are marked xfail with a
`DEFECT (tranche-3 discovery)` reason naming the module, function, what it does
and what it should do; they assert the behaviour the reader should get and will
flip green when the defect is fixed. No production code is modified here.
"""

import datetime as _datetime_mod
import json
import os
import re
import sys
from datetime import date as _real_date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

# The module reads these at import time (S3_BUCKET/EMAIL_RECIPIENT/EMAIL_SENDER are
# os.environ[...] lookups, not .get) and builds boto3 clients at module level.
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import monthly_digest_lambda as m  # noqa: E402
from experiment.phase_filter import with_phase_filter  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clocks
#
# The CDK schedule is `cron(0 16 ? * 1#1 *)` (cdk/stacks/email_stack.py) and the
# module docstring reads "Fires first Sunday of each month at 16:00 UTC" — in
# EventBridge cron the day-of-week field is 1-7 = SUN-SAT, so `1#1` is the FIRST
# SUNDAY. In 2026 that is 2026-08-02 for August.
#
# lambda_handler additionally refuses to run unless `date.today().weekday() == 0`
# (Monday), so the only clock under which it proceeds is a Monday — a day its own
# schedule never fires on. Both clocks are therefore pinned here.
# ──────────────────────────────────────────────────────────────────────────────

CRON_SUNDAY = datetime(2026, 8, 2, 16, 0, 0, tzinfo=timezone.utc)  # the real fire slot
GUARD_MONDAY = datetime(2026, 8, 3, 16, 0, 0, tzinfo=timezone.utc)  # the only day the guard admits


def _frozen_datetime_class(pinned):
    class _FrozenDatetime(datetime):
        """`datetime` subclass with a pinned `now()`/`utcnow()`.

        A subclass (rather than a Mock) keeps `strptime`, arithmetic, `.date()`
        and `.strftime()` working, which the module uses on the same name.
        """

        @classmethod
        def now(cls, tz=None):
            return pinned if tz else pinned.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return pinned.replace(tzinfo=None)

    return _FrozenDatetime


def _frozen_date_class(pinned):
    class _FrozenDate(_real_date):
        """`date` subclass with a pinned `today()`.

        `lambda_handler` does a function-local `from datetime import date`, so the
        only way to freeze it is to swap this onto the stdlib module attribute.
        monkeypatch reverts it at teardown.
        """

        @classmethod
        def today(cls):
            return pinned.date()

    return _FrozenDate


@pytest.fixture
def frozen_monday(monkeypatch):
    monkeypatch.setattr(m, "datetime", _frozen_datetime_class(GUARD_MONDAY))
    monkeypatch.setattr(_datetime_mod, "date", _frozen_date_class(GUARD_MONDAY))
    return GUARD_MONDAY


@pytest.fixture
def frozen_cron_sunday(monkeypatch):
    monkeypatch.setattr(m, "datetime", _frozen_datetime_class(CRON_SUNDAY))
    monkeypatch.setattr(_datetime_mod, "date", _frozen_date_class(CRON_SUNDAY))
    return CRON_SUNDAY


# Windows the module derives from GUARD_MONDAY = 2026-08-03 (hand-derived):
#   cur_end   = today - 1  = 2026-08-02
#   cur_start = today - 30 = 2026-07-04   (2026-07-04 + 30 days == 2026-08-03)
#   prior_end = today - 31 = 2026-07-03
#   prior_start = today - 60 = 2026-06-04 (2026-06-04 + 60 days == 2026-08-03)
MON_CUR_START, MON_CUR_END = "2026-07-04", "2026-08-02"
MON_PRIOR_START, MON_PRIOR_END = "2026-06-04", "2026-07-03"

WINDOWS = {
    "cur_start": MON_CUR_START,
    "cur_end": MON_CUR_END,
    "prior_start": MON_PRIOR_START,
    "prior_end": MON_PRIOR_END,
    "month_label": "August 2026",
    "prior_label": "July 2026",
}


# ──────────────────────────────────────────────────────────────────────────────
# Bounded fakes
# ──────────────────────────────────────────────────────────────────────────────


def _range_query_hook(table, **kwargs):
    """query_hook for `FakeDdbTable`: honour pk + the `sk BETWEEN :s AND :e`
    range the module actually issues.

    The generic canned-rows flavour cannot serve this module, because the whole
    point of `fetch_range` is that the current-month and prior-month arms read
    DIFFERENT sk slices of the SAME partition — serving both arms the same rows
    would make every month-over-month delta vacuously zero.
    """
    eav = kwargs.get("ExpressionAttributeValues") or {}
    pk = eav.get(":pk")
    items = [i for i in table.store.values() if i.get("pk") == pk]
    lo, hi = eav.get(":s"), eav.get(":e")
    if lo is not None and hi is not None:
        items = [i for i in items if lo <= i.get("sk", "") <= hi]
    items.sort(key=lambda i: i.get("sk", ""))
    return {"Items": items}


def _table_with(rows):
    return FakeDdbTable(rows=rows, query_hook=_range_query_hook)


class FakeSES:
    """Records sends. NOTHING in this file may reach the real SES client."""

    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "fake"}


class FakeS3:
    """Bounded S3 stand-in serving one JSON body for the board config key."""

    def __init__(self, config=None, error=None):
        self.config = config
        self.error = error
        self.calls = []

    def get_object(self, Bucket=None, Key=None):
        self.calls.append((Bucket, Key))
        if self.error:
            raise self.error

        class _Body:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode("utf-8")

        return {"Body": _Body(self.config)}


class FakeInsightWriter:
    def __init__(self, context=""):
        self.context = context
        self.written = []

    def build_insights_context(self, **kwargs):
        return self.context

    def write_insight(self, **kwargs):
        self.written.append(kwargs)
        return kwargs


# ──────────────────────────────────────────────────────────────────────────────
# HTML readers — assert what a reader sees, not the CSS
# ──────────────────────────────────────────────────────────────────────────────


def _rows(html):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        out.append(cells)
    return out


def _row(html, label):
    for r in _rows(html):
        if r and r[0] == label:
            return r
    return None


def _sections(html):
    return re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.S)


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ──────────────────────────────────────────────────────────────────────────────
# Fixture builders
# ──────────────────────────────────────────────────────────────────────────────


def _act(hr=120, secs=1800, miles=2.0, sport="Run", start="2026-07-04T08:00:00", name="AM"):
    return {
        "average_heartrate": hr,
        "moving_time_seconds": secs,
        "distance_miles": miles,
        "sport_type": sport,
        "start_date_local": start,
        "name": name,
    }


def _strava_day(acts, miles, secs, elev=0, date_str="2026-07-04"):
    return {
        "pk": f"USER#{m.USER_ID}#SOURCE#strava",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "activities": acts,
        "total_distance_miles": miles,
        "total_moving_time_seconds": secs,
        "total_elevation_gain_feet": elev,
    }


def _row_for(source, date_str, **fields):
    rec = {"pk": f"USER#{m.USER_ID}#SOURCE#{source}", "sk": f"DATE#{date_str}", "date": date_str}
    rec.update(fields)
    return rec


PROFILE = {
    "goal_weight_lbs": 220.0,
    "journey_start_weight_lbs": 321.6,
    "journey_start_date": "2026-08-03",
    "max_heart_rate": 190,
    "calorie_target": 1800,
    "protein_target_g": 190,
}


# ══════════════════════════════════════════════════════════════════════════════
# get_date_windows — the month-boundary arithmetic
# ══════════════════════════════════════════════════════════════════════════════


def test_the_current_arm_is_the_thirty_days_ending_yesterday(frozen_monday):
    w = m.get_date_windows()
    # today 2026-08-03 -> end = today-1 = 08-02, start = today-30 = 07-04
    assert (w["cur_start"], w["cur_end"]) == (MON_CUR_START, MON_CUR_END)


def test_the_prior_arm_is_the_thirty_days_before_that_with_no_overlap(frozen_monday):
    w = m.get_date_windows()
    assert (w["prior_start"], w["prior_end"]) == (MON_PRIOR_START, MON_PRIOR_END)
    assert w["prior_end"] < w["cur_start"]  # the two arms must not share a day


def test_each_arm_spans_exactly_thirty_days(frozen_monday):
    w = m.get_date_windows()
    for start, end in ((w["cur_start"], w["cur_end"]), (w["prior_start"], w["prior_end"])):
        span = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1
        assert span == 30


def test_the_prior_month_label_is_the_calendar_month_before_today(frozen_monday):
    # today.replace(day=1) = 2026-08-01, minus one day = 2026-07-31 -> "July 2026"
    assert m.get_date_windows()["prior_label"] == "July 2026"


def test_the_windows_are_the_same_on_the_cron_slot_shifted_by_one_day(frozen_cron_sunday):
    """The real fire slot is the first Sunday; pin its windows too so a future
    schedule change is a visible diff rather than a silent shift."""
    w = m.get_date_windows()
    # today 2026-08-02 -> end = 08-01, start = 07-03, prior 06-03..07-02
    assert (w["cur_start"], w["cur_end"]) == ("2026-07-03", "2026-08-01")
    assert (w["prior_start"], w["prior_end"]) == ("2026-06-03", "2026-07-02")


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P1): monthly_digest_lambda.get_date_windows (lines 141-163) labels a ROLLING "
        "30-DAY window with a CALENDAR month name. On its own fire slot (first Sunday, e.g. 2026-08-02) the current "
        "arm is 2026-07-03..2026-08-01 — that is JULY's data — but month_label is today.strftime('%B %Y') = "
        "'August 2026'. build_html then prints it as the <h1> and the subject line. The reader is handed July's "
        "month under August's headline. It should label the completed calendar month the window actually covers "
        "(and read that month's real first-to-last day, not today-30)."
    ),
)
def test_the_month_label_names_the_month_the_data_actually_covers(frozen_cron_sunday):
    w = m.get_date_windows()
    # 29 of the window's 30 days (2026-07-03..2026-08-01) are July days.
    covered = datetime.strptime(w["cur_start"], "%Y-%m-%d").strftime("%B %Y")
    assert w["month_label"] == covered  # "July 2026"; the module says "August 2026"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P1): the same off-by-one-month applies to prior_label. On 2026-08-02 the prior "
        "arm is 2026-06-03..2026-07-02 (June's data) while prior_label reads 'July 2026'. build_html prints "
        "'30-day review · Deltas vs July 2026' over June's numbers, so every delta in the email is attributed to the "
        "wrong month."
    ),
)
def test_the_prior_label_names_the_month_the_prior_arm_actually_covers(frozen_cron_sunday):
    w = m.get_date_windows()
    covered = datetime.strptime(w["prior_start"], "%Y-%m-%d").strftime("%B %Y")
    assert w["prior_label"] == covered  # arm starts 2026-06-03 -> "June 2026", label says "July 2026"


# ══════════════════════════════════════════════════════════════════════════════
# fetch_range — ADR-058 phase scoping + failure semantics
# ══════════════════════════════════════════════════════════════════════════════


def test_a_cross_phase_source_is_read_across_experiment_cycles(monkeypatch):
    """`chronicling` is CROSS_PHASE in phase_taxonomy (the frozen pre-platform
    archive) — narrowing it to the current cycle would blank the 'before'."""
    table = _table_with([])
    monkeypatch.setattr(m, "table", table)
    m.fetch_range("chronicling", MON_CUR_START, MON_CUR_END)
    issued = table.query_calls[0]
    expected = with_phase_filter({"KeyConditionExpression": "x", "ExpressionAttributeValues": {}}, include_pilot=True)
    assert issued.get("FilterExpression") == expected.get("FilterExpression")


def test_an_experiment_scoped_source_defaults_to_the_current_cycle_only(monkeypatch):
    """ADR-058 default-deny: `macrofactor` is RAW_TIMESERIES (cross-phase), but a
    scoped source must not widen. Derive the expectation from the registry rather
    than restating a literal."""
    from experiment.phase_filter import source_reads_cross_phase

    table = _table_with([])
    monkeypatch.setattr(m, "table", table)
    for source in ("chronicling", "whoop", "macrofactor", "strava"):
        table.query_calls.clear()
        m.fetch_range(source, MON_CUR_START, MON_CUR_END)
        expected = with_phase_filter(
            {"KeyConditionExpression": "x", "ExpressionAttributeValues": {}}, include_pilot=source_reads_cross_phase(source)
        )
        assert table.query_calls[0].get("FilterExpression") == expected.get("FilterExpression"), source


def test_fetch_range_reads_only_the_requested_window_of_the_requested_source(monkeypatch):
    table = _table_with(
        [
            _row_for("whoop", "2026-07-03", hrv=50),  # one day before cur_start
            _row_for("whoop", MON_CUR_START, hrv=60),
            _row_for("whoop", MON_CUR_END, hrv=70),
            _row_for("withings", MON_CUR_START, weight_lbs=300),
        ]
    )
    monkeypatch.setattr(m, "table", table)
    got = m.fetch_range("whoop", MON_CUR_START, MON_CUR_END)
    assert [r["hrv"] for r in got] == [60, 70]


def test_fetch_range_converts_dynamodb_decimals_to_numbers(monkeypatch):
    table = _table_with([_row_for("withings", MON_CUR_END, weight_lbs=Decimal("312.4"))])
    monkeypatch.setattr(m, "table", table)
    got = m.fetch_range("withings", MON_CUR_START, MON_CUR_END)[0]["weight_lbs"]
    assert got == 312.4 and isinstance(got, float)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-104): monthly_digest_lambda.fetch_range (lines 132-133) swallows every "
        "exception and returns []. A DynamoDB outage, a throttle, or a malformed key therefore renders as 'no data "
        "this month' — and build_html turns that into confident figures (CTL 0.0 · TSB 0.0 (Neutral), '0%' hit "
        "rates, 'Chronicling data not available'). A read failure must be distinguishable from a genuinely empty "
        "month, and must not be published as measurement."
    ),
)
def test_a_failed_read_is_not_silently_reported_as_an_empty_month(monkeypatch):
    from fakes import raise_hook

    table = FakeDdbTable(query_hook=raise_hook)
    monkeypatch.setattr(m, "table", table)
    with pytest.raises(Exception):
        m.fetch_range("whoop", MON_CUR_START, MON_CUR_END)


# ══════════════════════════════════════════════════════════════════════════════
# ex_strava
# ══════════════════════════════════════════════════════════════════════════════


def test_no_strava_records_reports_absence_not_a_zero_month():
    assert m.ex_strava([]) is None
    assert m.ex_strava(None) is None


def test_strava_totals_come_from_the_day_records():
    recs = [
        _strava_day([_act()], miles=2.0, secs=1800, elev=100, date_str="2026-07-04"),
        _strava_day([_act(start="2026-07-05T08:00:00")], miles=3.5, secs=2400, elev=250, date_str="2026-07-05"),
    ]
    s = m.ex_strava(recs)
    assert s["total_miles"] == 5.5  # 2.0 + 3.5
    assert s["total_minutes"] == 70  # round((1800 + 2400) / 60)
    assert s["total_elevation_feet"] == 350  # 100 + 250
    assert s["activity_count"] == 2


def test_zone_two_minutes_count_only_activities_inside_the_default_hr_band():
    """Default band is ZONE2_HR_LOW..ZONE2_HR_HIGH = 110..129 with no profile."""
    recs = [
        _strava_day(
            [
                _act(hr=120, secs=1800, start="2026-07-04T06:00:00"),  # in band -> 30 min
                _act(hr=150, secs=1800, sport="Ride", start="2026-07-04T09:00:00"),  # above band
            ],
            miles=4.0,
            secs=3600,
        )
    ]
    s = m.ex_strava(recs)
    assert s["zone2_minutes"] == 30
    assert s["zone2_hr_range"] == f"{m.ZONE2_HR_LOW}-{m.ZONE2_HR_HIGH}"
    assert s["zone2_pct"] == 50  # round(30 / round(3600/60) * 100)


def test_the_zone_two_band_is_derived_from_the_profile_max_heart_rate():
    recs = [_strava_day([_act(hr=120, secs=1800)], miles=2.0, secs=1800)]
    s = m.ex_strava(recs, {"max_heart_rate": 190})
    # 190 * 0.60 = 114, 190 * 0.70 = 133
    assert s["zone2_hr_range"] == "114-133"
    assert s["zone2_minutes"] == 30  # 120 bpm sits inside 114-133


def test_an_activity_outside_the_profile_band_is_excluded_even_if_the_default_band_would_keep_it():
    recs = [_strava_day([_act(hr=112, secs=1800)], miles=2.0, secs=1800)]
    default_band = m.ex_strava(recs)
    profile_band = m.ex_strava(recs, {"max_heart_rate": 190})
    assert default_band["zone2_minutes"] == 30  # 112 is inside 110-129
    assert profile_band["zone2_minutes"] == 0  # 112 is below 114


def test_an_activity_with_no_heart_rate_is_counted_but_not_credited_to_zone_two():
    recs = [_strava_day([_act(hr=None, secs=1800)], miles=2.0, secs=1800)]
    s = m.ex_strava(recs)
    assert s["activity_count"] == 1
    assert s["zone2_minutes"] == 0


def test_a_month_with_no_recorded_moving_time_does_not_divide_by_zero():
    recs = [_strava_day([_act(hr=120, secs=0)], miles=0, secs=0)]
    assert m.ex_strava(recs)["zone2_pct"] == 0


def test_an_activity_name_prefers_the_enriched_name():
    recs = [_strava_day([dict(_act(), enriched_name="Green Lake loop")], miles=2.0, secs=1800)]
    assert m.ex_strava(recs)["activity_count"] == 1  # the enriched name is carried on the activity, not the summary


def test_duplicate_activities_are_counted_once():
    """Garmin->Strava auto-sync writes the same session twice; dedup_activities
    collapses them."""
    dup = _act(start="2026-07-04T08:00:00")
    recs = [_strava_day([dup, dict(dup)], miles=2.0, secs=1800)]
    assert m.ex_strava(recs)["activity_count"] == 1


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2): monthly_digest_lambda.ex_strava (lines 188-205) counts Zone-2 minutes from "
        "the DEDUPED per-activity list but divides by total_minutes summed from the day record's UNDEDUPED "
        "`total_moving_time_seconds` (and reports total_miles from the equally undeduped `total_distance_miles`). On "
        "a day with a Garmin->Strava duplicate the numerator is halved against the denominator, so zone2_pct is "
        "reported as half its true value — and activity_count (deduped) disagrees with total_miles (not). Both sides "
        "of the ratio must come from the same deduped set."
    ),
)
def test_the_zone_two_percentage_is_not_halved_by_a_duplicate_activity():
    dup = _act(hr=120, secs=1800, miles=2.0, start="2026-07-04T08:00:00")
    # the ingested day record double-counts the duplicate: 3600 s / 4.0 mi
    recs = [_strava_day([dup, dict(dup)], miles=4.0, secs=3600)]
    s = m.ex_strava(recs)
    assert s["activity_count"] == 1
    assert s["zone2_pct"] == 100  # 30 deduped zone-2 minutes out of 30 deduped minutes


# ══════════════════════════════════════════════════════════════════════════════
# ex_hevy
# ══════════════════════════════════════════════════════════════════════════════


def test_no_strength_records_reports_absence():
    assert m.ex_hevy([]) is None


def test_strength_workouts_are_counted_across_every_day_in_the_window():
    recs = [
        {"workouts": [{"title": "Push", "total_volume_lbs": 12000}, {"title": "Pull", "total_volume_lbs": 9000}]},
        {"workouts": [{"title": "Legs", "total_volume_lbs": 15000}]},
    ]
    assert m.ex_hevy(recs)["workout_count"] == 3


def test_a_day_record_with_no_workouts_contributes_nothing():
    assert m.ex_hevy([{"workouts": []}, {}])["workout_count"] == 0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P3): monthly_digest_lambda.ex_hevy (lines 217-224) builds a full per-workout "
        "list with titles and `total_volume_lbs` and then throws it away, returning only {'workout_count': n}. A "
        "MONTHLY strength review that reports the number of sessions but not a pound of the volume behind them is "
        "the one number a lifter cares least about; the work is already done and discarded."
    ),
)
def test_the_monthly_strength_summary_reports_the_volume_it_computed():
    recs = [{"workouts": [{"title": "Push", "total_volume_lbs": 12000}, {"title": "Pull", "total_volume_lbs": 9000}]}]
    assert m.ex_hevy(recs)["total_volume_lbs"] == 21000  # 12000 + 9000


# ══════════════════════════════════════════════════════════════════════════════
# ex_macrofactor
# ══════════════════════════════════════════════════════════════════════════════


def _mf(cal=None, protein=None):
    rec = {}
    if cal is not None:
        rec["total_calories_kcal"] = cal
    if protein is not None:
        rec["total_protein_g"] = protein
    return rec


def test_no_nutrition_records_reports_absence_not_a_zero_month():
    assert m.ex_macrofactor([]) is None


def test_nutrition_averages_are_the_mean_of_the_logged_days():
    recs = [_mf(1700, 180), _mf(1900, 200), _mf(1800, 190)]
    s = m.ex_macrofactor(recs)
    assert s["calories_avg"] == 1800.0  # (1700 + 1900 + 1800) / 3
    assert s["protein_avg_g"] == 190.0  # (180 + 200 + 190) / 3
    assert s["days_logged"] == 3


def test_hit_rates_are_the_share_of_days_that_met_the_target():
    # module defaults: CALORIE_TARGET 1800, PROTEIN_TARGET_G 180.
    # calories <= 1800 on 2 of 3 (1700, 1800); protein >= 180 on 2 of 3 (180, 200).
    recs = [_mf(1700, 180), _mf(1900, 200), _mf(1800, 170)]
    s = m.ex_macrofactor(recs)
    assert s["calorie_hit_rate"] == 67  # round(2 / 3 * 100)
    assert s["protein_hit_rate"] == 67  # round(2 / 3 * 100)


def test_the_targets_come_from_the_profile_when_it_has_them():
    recs = [_mf(1700, 180)]
    s = m.ex_macrofactor(recs, {"calorie_target": 1600, "protein_target_g": 175})
    assert (s["calorie_target"], s["protein_target"]) == (1600, 175)
    assert s["calorie_hit_rate"] == 0  # 1700 > 1600
    assert s["protein_hit_rate"] == 100  # 180 >= 175


def test_missing_profile_targets_fall_back_to_the_module_defaults():
    s = m.ex_macrofactor([_mf(1700, 180)], {})
    assert (s["calorie_target"], s["protein_target"]) == (m.CALORIE_TARGET, m.PROTEIN_TARGET_G)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-104+105): monthly_digest_lambda.ex_macrofactor (lines 247-248) divides "
        "the hit counts by `days = len(recs)` while the numerator only sees records that CARRY the field. A month "
        "where MacroFactor wrote 30 rows but 10 carry no `total_protein_g` reports protein_hit_rate over n=30 when "
        "it was measured over n=20 — the published rate is diluted by days that were never measured, and "
        "`days_logged` counts unlogged rows as logged. Rate and n must be the same set."
    ),
)
def test_a_hit_rate_is_computed_over_the_days_it_actually_measured():
    # 2 records carry protein (both hit), 2 records carry none at all
    recs = [_mf(1700, 200), _mf(1700, 200), _mf(1700), _mf(1700)]
    s = m.ex_macrofactor(recs)
    assert s["protein_hit_rate"] == 100  # 2/2 measured days hit, not 2/4


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-104): with records present but NO totals on any of them, "
        "ex_macrofactor returns calories_avg=None (honest) alongside calorie_hit_rate=round(0/days*100)=0 — and "
        "build_html renders that as a flat '0%' next to an em-dash average. A month nothing was logged in is "
        "published as a month of 0% adherence. Absence must render as absence on BOTH figures."
    ),
)
def test_a_month_with_no_totals_logged_reports_absent_hit_rates_not_zero_percent():
    s = m.ex_macrofactor([_mf(), _mf(), _mf()])
    assert s["calories_avg"] is None
    assert s["calorie_hit_rate"] is None
    assert s["protein_hit_rate"] is None


# ══════════════════════════════════════════════════════════════════════════════
# ex_character_sheet
# ══════════════════════════════════════════════════════════════════════════════


def _cs(date_str, level=12, xp=4200, tier="Momentum", **pillars):
    rec = {
        "sk": f"DATE#{date_str}",
        "character_level": level,
        "character_xp": xp,
        "character_tier": tier,
        "character_tier_emoji": "🌱",
    }
    for name, lvl in pillars.items():
        rec[f"pillar_{name}"] = {"level": lvl, "tier": "Momentum"}
    return rec


def _all_pillar_names():
    """The pillar roster, derived from the shipped config rather than restated.

    `config/character_sheet.json` is the registry the character engine and the
    generated /method/game/ page both read; a new pillar added there must show up
    in the monthly letter automatically.
    """
    with open(ROOT / "config" / "character_sheet.json") as fh:
        return sorted(json.load(fh)["pillars"].keys())


def test_no_character_records_reports_absence():
    assert m.ex_character_sheet([]) is None


def test_the_character_level_comes_from_the_latest_day_in_the_window():
    recs = [_cs("2026-07-04", level=10, xp=3000), _cs(MON_CUR_END, level=14, xp=5000)]
    s = m.ex_character_sheet(recs)
    assert s["character_level"] == 14.0
    assert s["character_xp"] == 5000.0
    assert s["days_tracked"] == 2


def test_the_latest_day_wins_regardless_of_the_order_records_arrive_in():
    recs = [_cs(MON_CUR_END, level=14, xp=5000), _cs("2026-07-04", level=10, xp=3000)]
    assert m.ex_character_sheet(recs)["character_level"] == 14.0


def test_the_xp_delta_is_the_months_last_reading_minus_its_first():
    recs = [_cs("2026-07-04", xp=3000), _cs("2026-07-20", xp=4100), _cs(MON_CUR_END, xp=5000)]
    assert m.ex_character_sheet(recs)["xp_delta_30d"] == 2000  # 5000 - 3000


def test_a_single_day_of_character_data_reports_no_xp_movement():
    assert m.ex_character_sheet([_cs(MON_CUR_END, xp=5000)])["xp_delta_30d"] == 0


def test_the_tier_is_rendered_with_its_badge():
    assert m.ex_character_sheet([_cs(MON_CUR_END, tier="Discipline")])["character_tier"] == "🌱 Discipline"


def test_a_record_without_a_tier_falls_back_to_foundation():
    rec = {"sk": f"DATE#{MON_CUR_END}", "character_level": 3}
    assert m.ex_character_sheet([rec])["character_tier"].endswith("Foundation")


def test_every_configured_pillar_reaches_the_monthly_summary():
    """Derived from config/character_sheet.json — a pillar added to the registry
    must not silently vanish from the monthly letter."""
    names = _all_pillar_names()
    rec = _cs(MON_CUR_END, **{n: 7 for n in names})
    pillars = m.ex_character_sheet([rec])["pillars"]
    assert sorted(pillars.keys()) == names
    assert all(pillars[n]["level"] == 7.0 for n in names)


def test_a_malformed_pillar_block_is_skipped_without_crashing():
    rec = _cs(MON_CUR_END, sleep=9)
    rec["pillar_movement"] = "not-a-dict"
    pillars = m.ex_character_sheet([rec])["pillars"]
    assert "movement" not in pillars
    assert pillars["sleep"]["level"] == 9.0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-104): monthly_digest_lambda.ex_character_sheet lines 263-266 iterate a "
        "fixed seven-pillar tuple and coerce a MISSING pillar block with `latest.get(f'pillar_{p}') or {}` — an "
        "empty dict is still a dict, so it passes the isinstance check and becomes "
        "{'level': 0.0, 'tier': 'Foundation'}. build_html then prints a row reading 'Level 0 — Foundation' for every "
        "pillar the character engine never scored. Behavioural absence is being rendered as a measured floor score "
        "— exactly what ADR-104 forbids in the character engine."
    ),
)
def test_a_pillar_with_no_stored_block_is_omitted_rather_than_invented_at_level_zero():
    rec = _cs(MON_CUR_END, sleep=9)
    assert list(m.ex_character_sheet([rec])["pillars"]) == ["sleep"]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-104): monthly_digest_lambda.ex_character_sheet line 267 builds the XP "
        "series with `float(r.get('character_xp') or 0)`, so a day whose record is missing character_xp is read as "
        "ZERO XP. If the window's FIRST record is such a day the reported xp_delta_30d becomes the athlete's entire "
        "lifetime XP presented as one month's gain (here +5000 instead of +1000). A missing reading must be skipped, "
        "not treated as a reading of zero."
    ),
)
def test_a_day_missing_its_xp_reading_does_not_become_a_zero_xp_day():
    recs = [_cs("2026-07-04"), _cs("2026-07-20", xp=4000), _cs(MON_CUR_END, xp=5000)]
    del recs[0]["character_xp"]
    assert m.ex_character_sheet(recs)["xp_delta_30d"] == 1000  # 5000 - 4000, the two real readings


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P3): monthly_digest_lambda.ex_character_sheet line 256 sorts its argument IN "
        "PLACE (`recs.sort(...)`). gather_all passes the caller's own list, so the extractor silently reorders data "
        "its caller may read again. An extractor must not mutate its input."
    ),
)
def test_the_character_extractor_does_not_reorder_its_callers_list():
    recs = [_cs(MON_CUR_END, level=14), _cs("2026-07-04", level=10)]
    before = [r["sk"] for r in recs]
    m.ex_character_sheet(recs)
    assert [r["sk"] for r in recs] == before


# ══════════════════════════════════════════════════════════════════════════════
# ex_chronicling
# ══════════════════════════════════════════════════════════════════════════════


def test_no_habit_records_reports_absence():
    assert m.ex_chronicling([]) is None


def test_the_habit_average_is_the_mean_of_the_days_that_scored():
    recs = [{"total_score": 60}, {"total_score": 80}, {"total_score": 70}]
    assert m.ex_chronicling(recs)["score_avg"] == 70.0  # (60 + 80 + 70) / 3


def test_group_averages_are_computed_per_group_across_the_month():
    recs = [
        {"total_score": 70, "group_scores": {"sleep": 80, "food": 40}},
        {"total_score": 70, "group_scores": {"sleep": 60, "food": 60}},
    ]
    g = m.ex_chronicling(recs)["group_avgs"]
    assert g["sleep"] == 70.0  # (80 + 60) / 2
    assert g["food"] == 50.0  # (40 + 60) / 2


def test_the_best_and_weakest_groups_are_the_highest_and_lowest_averages():
    recs = [{"group_scores": {"sleep": 90, "food": 40, "mind": 65}}]
    s = m.ex_chronicling(recs)
    assert s["best_group"] == "sleep"
    assert s["worst_group"] == "food"


def test_a_month_with_scores_but_no_groups_names_no_best_or_worst():
    s = m.ex_chronicling([{"total_score": 70}])
    assert s["best_group"] is None and s["worst_group"] is None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-105): monthly_digest_lambda.ex_chronicling (lines 292-298) publishes "
        "`score_avg` (mean of the records that carry total_score) next to `days` = len(recs) — every record in the "
        "window, scored or not. build_html shows the average as the month's headline P40 figure; the n it is "
        "presented with is not the n it was computed over. Every statistical claim must carry ITS OWN n."
    ),
)
def test_the_habit_average_is_reported_with_the_number_of_days_it_averaged():
    recs = [{"total_score": 60}, {"total_score": 80}, {"note": "no score today"}]
    s = m.ex_chronicling(recs)
    assert s["score_avg"] == 70.0  # (60 + 80) / 2
    assert s["days"] == 2  # not 3


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-104): ex_chronicling line 291 sorts groups by `x[1] or 0`, so a group "
        "whose average is None (present in the schema, never scored this month) sorts as ZERO and is named the "
        "month's '⚠️ Weakest Group' in the email. An unmeasured group is being reported to the reader as the worst-"
        "performing one."
    ),
)
def test_a_group_that_was_never_scored_is_not_named_the_weakest():
    recs = [{"group_scores": {"sleep": 80, "food": 55}}, {"group_scores": {"mind": None}}]
    assert m.ex_chronicling(recs)["worst_group"] == "food"


# ══════════════════════════════════════════════════════════════════════════════
# compute_annual_goals
# ══════════════════════════════════════════════════════════════════════════════


def test_the_year_elapsed_percentage_is_measured_from_january_first(frozen_monday):
    # 2026-01-01 -> 2026-08-03 is 214 days; the module uses (today - year_start).days = 214
    goals = m.compute_annual_goals({}, WINDOWS, {})
    assert goals["year_pct_elapsed"] == round(214 / 365 * 100)  # 59


def test_weight_progress_is_measured_against_the_journey_start_and_the_goal(frozen_monday):
    cur = {"withings": {"weight_latest": 300.0}}
    g = m.compute_annual_goals(cur, WINDOWS, PROFILE)["weight"]
    assert g["lost_lbs"] == 21.6  # 321.6 - 300.0
    assert g["to_go_lbs"] == 80.0  # 300.0 - 220.0
    assert g["pct_complete"] == 21  # round(21.6 / (321.6 - 220.0) * 100) = round(21.26)


def test_weight_progress_falls_back_to_the_platform_baseline_without_a_profile(frozen_monday):
    from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS

    g = m.compute_annual_goals({"withings": {"weight_latest": 310.0}}, WINDOWS, {})["weight"]
    assert g["journey_start_weight"] == float(EXPERIMENT_BASELINE_WEIGHT_LBS)
    assert g["goal_lbs"] == m.GOAL_WEIGHT_LBS


def test_a_month_with_no_weigh_in_publishes_no_weight_goal_block(frozen_monday):
    assert "weight" not in m.compute_annual_goals({"withings": None}, WINDOWS, PROFILE)
    assert "weight" not in m.compute_annual_goals({}, WINDOWS, PROFILE)


def test_weight_gained_since_the_start_is_reported_as_negative_progress(frozen_monday):
    g = m.compute_annual_goals({"withings": {"weight_latest": 330.0}}, WINDOWS, PROFILE)["weight"]
    assert g["lost_lbs"] == -8.4  # 321.6 - 330.0
    assert g["pct_complete"] == -8  # round(-8.4 / 101.6 * 100)


def test_training_consistency_carries_the_activity_and_zone_two_counts(frozen_monday):
    cur = {"strava": {"activity_count": 18, "zone2_minutes": 540}}
    goals = m.compute_annual_goals(cur, WINDOWS, PROFILE)
    assert goals["training_activities_30d"] == 18
    assert goals["zone2_minutes_30d"] == 540


def test_habit_adherence_is_carried_from_the_chronicling_average(frozen_monday):
    goals = m.compute_annual_goals({"chronicling": {"score_avg": 71.5}}, WINDOWS, PROFILE)
    assert goals["habit_score_avg"] == 71.5


def test_a_month_with_no_training_publishes_no_training_goal_numbers(frozen_monday):
    goals = m.compute_annual_goals({"strava": None}, WINDOWS, PROFILE)
    assert "training_activities_30d" not in goals


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P3): monthly_digest_lambda.compute_annual_goals line 320 hard-codes "
        "`days_in_year = 365`, so in a leap year every 'Year elapsed' figure is overstated (and on 2028-12-31 the "
        "year reads as 100% elapsed with a day still to run — the progress bar is only saved by build_html's "
        "min(100, ...) clamp). Derive the year length from the year itself."
    ),
)
def test_the_year_elapsed_percentage_uses_the_real_length_of_the_year(monkeypatch):
    # 2028 is a leap year (366 days). 2028-01-01 -> 2028-02-12 is 42 days elapsed:
    #   correct: round(42 / 366 * 100) = 11        module: round(42 / 365 * 100) = 12
    monkeypatch.setattr(m, "datetime", _frozen_datetime_class(datetime(2028, 2, 12, 16, 0, tzinfo=timezone.utc)))
    assert m.compute_annual_goals({}, WINDOWS, {})["year_pct_elapsed"] == round(42 / 366 * 100)


# ══════════════════════════════════════════════════════════════════════════════
# _build_monthly_prompt_from_config
# ══════════════════════════════════════════════════════════════════════════════


BOARD = {
    "members": {
        "chen": {
            "name": "Dr. Sarah Chen",
            "active": True,
            "emoji": "🏋️",
            "voice": {"tone": "Precise, periodisation-first", "catchphrase": "Build the base."},
            "features": {
                "monthly_digest": {"section_header": "🏋️ DR. SARAH CHEN — MONTHLY TRAINING REVIEW", "prompt_focus": "Training arc."}
            },
        },
        "webb": {
            "name": "Dr. Marcus Webb",
            "active": True,
            "emoji": "🥗",
            "voice": {"tone": "Blunt and practical"},
            "features": {
                "monthly_digest": {"section_header": "🥗 DR. MARCUS WEBB — MONTHLY NUTRITION REVIEW", "prompt_focus": "Adherence."}
            },
        },
    }
}


def _with_board(monkeypatch, config):
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", True)
    monkeypatch.setattr(m.board_loader, "_board_cache", {"data": None, "ts": 0})
    monkeypatch.setattr(m, "s3_client", FakeS3(config))


def test_the_board_prompt_names_every_configured_advisor(monkeypatch):
    _with_board(monkeypatch, BOARD)
    prompt = m._build_monthly_prompt_from_config()
    assert "DR. SARAH CHEN" in prompt and "DR. MARCUS WEBB" in prompt


def test_the_board_prompt_carries_each_advisors_brief_and_voice(monkeypatch):
    _with_board(monkeypatch, BOARD)
    prompt = m._build_monthly_prompt_from_config()
    assert "Training arc." in prompt and "Adherence." in prompt
    assert "Precise, periodisation-first" in prompt
    assert "Build the base." in prompt


def test_the_board_prompt_keeps_the_data_and_goals_placeholders_for_the_caller(monkeypatch):
    _with_board(monkeypatch, BOARD)
    prompt = m._build_monthly_prompt_from_config()
    assert "{data_json}" in prompt and "{goals_json}" in prompt
    assert prompt.format(data_json="{}", goals_json="{}")  # renders without KeyError


def test_the_board_prompt_always_ends_with_the_insight_of_the_month(monkeypatch):
    _with_board(monkeypatch, BOARD)
    assert "INSIGHT OF THE MONTH" in m._build_monthly_prompt_from_config()


def test_an_inactive_advisor_is_left_off_the_monthly_board(monkeypatch):
    config = json.loads(json.dumps(BOARD))
    config["members"]["webb"]["active"] = False
    _with_board(monkeypatch, config)
    prompt = m._build_monthly_prompt_from_config()
    assert "DR. SARAH CHEN" in prompt and "DR. MARCUS WEBB" not in prompt


def test_a_board_with_nobody_assigned_to_this_email_falls_back(monkeypatch):
    _with_board(monkeypatch, {"members": {"chen": {"name": "Dr. Sarah Chen", "active": True, "features": {"weekly_digest": {}}}}})
    assert m._build_monthly_prompt_from_config() is None


def test_no_board_loader_in_the_bundle_falls_back(monkeypatch):
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", False)
    assert m._build_monthly_prompt_from_config() is None


def test_an_unreadable_board_config_falls_back_rather_than_guessing(monkeypatch):
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", True)
    monkeypatch.setattr(m.board_loader, "_board_cache", {"data": None, "ts": 0})
    monkeypatch.setattr(m, "s3_client", FakeS3(None, error=RuntimeError("no such key")))
    assert m._build_monthly_prompt_from_config() is None


def test_an_advisor_with_no_configured_header_gets_one_derived_from_their_name(monkeypatch):
    config = {
        "members": {
            "okafor": {
                "name": "Dr. James Okafor",
                "active": True,
                "emoji": "🩺",
                "features": {"monthly_digest": {"prompt_focus": "Trajectory."}},
            }
        }
    }
    _with_board(monkeypatch, config)
    prompt = m._build_monthly_prompt_from_config()
    assert "🩺 DR. JAMES OKAFOR" in prompt
    assert "Trajectory." in prompt


def test_an_advisor_with_no_configured_brief_is_still_given_a_default_instruction(monkeypatch):
    config = {
        "members": {"okafor": {"name": "Dr. James Okafor", "active": True, "features": {"monthly_digest": {"section_header": "🩺 OKAFOR"}}}}
    }
    _with_board(monkeypatch, config)
    assert "Provide your monthly analysis." in m._build_monthly_prompt_from_config()


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-104): the hardcoded CONTEXT paragraph in "
        "_build_monthly_prompt_from_config (lines 402-405) tells the board 'lose ~117 lbs (302→185)' and '1800 "
        "cal/day, 190g protein, 3 lbs/week target' as fact, while the SAME prompt's {goals_json} block carries the "
        "real profile figures (journey start 321.6, goal 220). The board is handed two contradictory goal weights and "
        "asked to reason about trajectory; the CONTEXT numbers should come from the profile, not a frozen literal."
    ),
)
def test_the_board_context_does_not_hardcode_a_goal_weight_that_contradicts_the_profile(monkeypatch):
    _with_board(monkeypatch, BOARD)
    prompt = m._build_monthly_prompt_from_config()
    assert "302" not in prompt and "185" not in prompt


# ══════════════════════════════════════════════════════════════════════════════
# call_haiku_monthly
# ══════════════════════════════════════════════════════════════════════════════


def _fake_ai(monkeypatch, reply="🎯 THE CHAIR — MONTHLY VERDICT\nA solid month.\n💡 INSIGHT OF THE MONTH\nWalk more.", capture=None):
    def _raw(req, timeout=55):
        if capture is not None:
            capture.append(json.loads(req.data.decode("utf-8")) if hasattr(req, "data") else req)
        return {"content": [{"text": reply}]}

    monkeypatch.setattr(m, "call_anthropic_with_retry", _raw)


def test_the_board_prompt_carries_this_months_data_and_goals(monkeypatch):
    seen = []
    _fake_ai(monkeypatch, capture=seen)
    monkeypatch.setattr(m, "_build_monthly_prompt_from_config", lambda: None)
    monkeypatch.setattr(m, "_presence_block", lambda: "")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    m.call_haiku_monthly({"cur": {"whoop": {"recovery_avg": 61.2}}}, {"year_pct_elapsed": 59})
    prompt = seen[0]["messages"][0]["content"]
    assert "61.2" in prompt
    assert '"year_pct_elapsed": 59' in prompt


def test_decimals_from_dynamodb_are_rendered_as_numbers_in_the_prompt(monkeypatch):
    seen = []
    _fake_ai(monkeypatch, capture=seen)
    monkeypatch.setattr(m, "_build_monthly_prompt_from_config", lambda: None)
    monkeypatch.setattr(m, "_presence_block", lambda: "")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    m.call_haiku_monthly({"cur": {"whoop": {"hrv_avg": Decimal("47.5")}}}, {})
    assert "47.5" in seen[0]["messages"][0]["content"]


def test_previous_insights_are_prepended_to_the_board_prompt(monkeypatch):
    seen = []
    _fake_ai(monkeypatch, capture=seen)
    monkeypatch.setattr(m, "_build_monthly_prompt_from_config", lambda: None)
    monkeypatch.setattr(m, "_presence_block", lambda: "")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", True)
    monkeypatch.setattr(m, "insight_writer", FakeInsightWriter(context="PREVIOUS INSIGHTS (last 90 days, 1 records):"))
    m.call_haiku_monthly({}, {})
    assert seen[0]["messages"][0]["content"].startswith("PREVIOUS INSIGHTS (last 90 days")


def test_a_broken_insight_ledger_never_blocks_the_board_call(monkeypatch):
    class Exploding(FakeInsightWriter):
        def build_insights_context(self, **kwargs):
            raise RuntimeError("ddb down")

    _fake_ai(monkeypatch)
    monkeypatch.setattr(m, "_build_monthly_prompt_from_config", lambda: None)
    monkeypatch.setattr(m, "_presence_block", lambda: "")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", True)
    monkeypatch.setattr(m, "insight_writer", Exploding())
    assert "THE CHAIR" in m.call_haiku_monthly({}, {})


def test_a_configured_board_prompt_is_preferred_over_the_hardcoded_fallback(monkeypatch):
    seen = []
    _fake_ai(monkeypatch, capture=seen)
    monkeypatch.setattr(m, "_build_monthly_prompt_from_config", lambda: "CONFIGURED BOARD\n{data_json}\n{goals_json}")
    monkeypatch.setattr(m, "_presence_block", lambda: "")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    m.call_haiku_monthly({}, {})
    assert seen[0]["messages"][0]["content"].startswith("CONFIGURED BOARD")


def test_the_quiet_stretch_block_is_appended_to_the_board_prompt(monkeypatch):
    seen = []
    _fake_ai(monkeypatch, capture=seen)
    monkeypatch.setattr(m, "_build_monthly_prompt_from_config", lambda: None)
    monkeypatch.setattr(m, "_presence_block", lambda: "=== PRESENCE ===\nLogging went quiet for 9 days.")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    m.call_haiku_monthly({}, {})
    assert seen[0]["messages"][0]["content"].endswith("Logging went quiet for 9 days.")


def test_a_present_month_injects_no_quiet_stretch_block(monkeypatch):
    """engagement_core returns "" when Matthew is present — zero prompt bloat."""
    monkeypatch.setattr(m, "table", FakeDdbTable())
    assert m._presence_block() == ""


def test_a_failed_presence_read_never_blocks_the_board_prompt(monkeypatch):
    from fakes import raise_hook

    monkeypatch.setattr(m, "table", FakeDdbTable(get_item_hook=raise_hook))
    assert m._presence_block() == ""


def test_the_board_call_is_routed_through_the_shared_retry_client(monkeypatch):
    """ADR-062: the urllib Request is a legacy carrier; retry_utils extracts the
    Messages body and calls Bedrock. Nothing here may reach api.anthropic.com."""
    from common import retry_utils

    seen = {}

    def _fake(req, timeout=55):
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["timeout"] = timeout
        return {"content": [{"text": "ok"}]}

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _fake)
    import urllib.request

    req = urllib.request.Request("https://example.invalid", data=json.dumps({"model": "x", "messages": []}).encode(), method="POST")
    assert m.call_anthropic_with_retry(req, timeout=60)["content"][0]["text"] == "ok"
    assert seen["timeout"] == 60


def test_the_board_call_asks_for_enough_tokens_for_six_sections(monkeypatch):
    seen = []
    _fake_ai(monkeypatch, capture=seen)
    monkeypatch.setattr(m, "_build_monthly_prompt_from_config", lambda: None)
    monkeypatch.setattr(m, "_presence_block", lambda: "")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    m.call_haiku_monthly({}, {})
    assert seen[0]["max_tokens"] >= 2500


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P3 / COST-OPT-2): call_haiku_monthly (lines 563-565) sends the ENTIRE board "
        "prompt as a single user message with no `system` block. Prompt caching engages on cache_control blocks "
        "attached to the system message, so this — the platform's largest single monthly prompt — can never be "
        "cached. The persona/rules half of the prompt belongs in `system`."
    ),
)
def test_the_static_half_of_the_board_prompt_is_sent_as_a_cacheable_system_block(monkeypatch):
    seen = []
    _fake_ai(monkeypatch, capture=seen)
    monkeypatch.setattr(m, "_build_monthly_prompt_from_config", lambda: None)
    monkeypatch.setattr(m, "_presence_block", lambda: "")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    m.call_haiku_monthly({}, {})
    assert seen[0].get("system")


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P3): call_haiku_monthly is named for Haiku and every comment/doc calls this the "
        "Haiku council call, but line 564 defaults the model to 'claude-sonnet-4-6'. Under ADR-049 model tiering a "
        "structured, section-templated task is a Haiku task; the letter has been silently billing at Sonnet rates."
    ),
)
def test_the_haiku_council_call_actually_requests_haiku(monkeypatch):
    seen = []
    _fake_ai(monkeypatch, capture=seen)
    monkeypatch.setattr(m, "_build_monthly_prompt_from_config", lambda: None)
    monkeypatch.setattr(m, "_presence_block", lambda: "")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    m.call_haiku_monthly({}, {})
    assert "haiku" in seen[0]["model"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# gather_all
# ══════════════════════════════════════════════════════════════════════════════


def _seeded_table():
    rows = [
        # current arm
        _row_for("whoop", "2026-07-10", hrv=50, recovery_score=60, resting_heart_rate=58),
        _row_for("whoop", MON_CUR_END, hrv=54, recovery_score=70, resting_heart_rate=56),
        _row_for("withings", MON_CUR_END, weight_lbs=Decimal("305.0"), body_fat_pct=Decimal("36.0")),
        _row_for("macrofactor", "2026-07-10", total_calories_kcal=1700, total_protein_g=200),
        _row_for("chronicling", "2026-07-10", total_score=72, group_scores={"sleep": 80, "food": 60}),
        _row_for("todoist", "2026-07-10", tasks_completed=6),
        _row_for("todoist", MON_CUR_END, tasks_completed=4),
        _row_for("hevy", "2026-07-10", workouts=[{"title": "Push", "total_volume_lbs": 12000}]),
        _row_for("character_sheet", MON_CUR_END, character_level=14, character_xp=5000, character_tier="Momentum"),
        _strava_day([_act()], miles=2.0, secs=1800, elev=100, date_str="2026-07-10"),
        # prior arm
        _row_for("whoop", "2026-06-10", hrv=44, recovery_score=52, resting_heart_rate=61),
        _row_for("withings", "2026-06-10", weight_lbs=Decimal("312.0")),
        _row_for("todoist", "2026-06-10", tasks_completed=9),
        {"pk": f"USER#{m.USER_ID}", "sk": "PROFILE#v1", **PROFILE},
    ]
    return _table_with(rows)


def test_gather_reads_both_arms_of_every_source(monkeypatch, frozen_monday):
    table = _seeded_table()
    monkeypatch.setattr(m, "table", table)
    data, goals = m.gather_all()
    assert data["cur"]["whoop"]["days"] == 2
    assert data["prior"]["whoop"]["days"] == 1
    assert data["cur"]["withings"]["weight_latest"] == 305.0
    assert data["prior"]["withings"]["weight_latest"] == 312.0


def test_gather_carries_the_windows_it_read(monkeypatch, frozen_monday):
    monkeypatch.setattr(m, "table", _seeded_table())
    data, _ = m.gather_all()
    assert data["windows"]["cur_start"] == MON_CUR_START
    assert data["windows"]["cur_end"] == MON_CUR_END


def test_gather_sums_completed_tasks_per_arm_with_the_days_behind_them(monkeypatch, frozen_monday):
    monkeypatch.setattr(m, "table", _seeded_table())
    data, _ = m.gather_all()
    assert data["cur"]["todoist"] == {"tasks_completed": 10, "days": 2}  # 6 + 4 over 2 days
    assert data["prior"]["todoist"] == {"tasks_completed": 9, "days": 1}


def test_gather_reads_the_profile_for_target_aware_extraction(monkeypatch, frozen_monday):
    monkeypatch.setattr(m, "table", _seeded_table())
    data, _ = m.gather_all()
    # max_heart_rate 190 -> the zone-2 band is derived, not the module default
    assert data["cur"]["strava"]["zone2_hr_range"] == "114-133"
    assert data["profile"]["goal_weight_lbs"] == 220.0
    assert data["profile"]["journey_start_weight_lbs"] == 321.6


def test_gather_survives_a_missing_profile(monkeypatch, frozen_monday):
    rows = [r for r in _seeded_table().store.values() if r.get("sk") != "PROFILE#v1"]
    monkeypatch.setattr(m, "table", _table_with(rows))
    data, _ = m.gather_all()
    assert data["profile"]["journey_start_weight_lbs"] is None
    assert data["cur"]["strava"]["zone2_hr_range"] == f"{m.ZONE2_HR_LOW}-{m.ZONE2_HR_HIGH}"


def test_a_failed_profile_read_falls_back_to_the_module_targets(monkeypatch, frozen_monday):
    table = _seeded_table()

    def _boom(tbl, key, **kwargs):
        raise RuntimeError("ddb down")

    table._get_item_hook = _boom
    monkeypatch.setattr(m, "table", table)
    data, _ = m.gather_all()
    assert data["profile"]["goal_weight_lbs"] == m.GOAL_WEIGHT_LBS
    assert data["cur"]["strava"]["zone2_hr_range"] == f"{m.ZONE2_HR_LOW}-{m.ZONE2_HR_HIGH}"


def test_gather_derives_sleep_from_the_whoop_partition(monkeypatch, frozen_monday):
    rows = list(_seeded_table().store.values())
    rows.append(_row_for("whoop", "2026-07-11", sleep_score=78, sleep_duration_hours=7.2))
    monkeypatch.setattr(m, "table", _table_with(rows))
    data, _ = m.gather_all()
    assert data["cur"]["sleep"]["score_avg"] == 78.0
    assert data["cur"]["sleep"]["nights"] == 3  # every whoop record in the arm counts as a night


def test_gather_scopes_the_character_sheet_query_to_the_current_cycle(monkeypatch, frozen_monday):
    """ADR-058: character_sheet is EXPERIMENT_SCOPED — a prior cycle's levels must
    not be read into this month's letter."""
    table = _seeded_table()
    monkeypatch.setattr(m, "table", table)
    m.gather_all()
    cs = [q for q in table.query_calls if q["ExpressionAttributeValues"][":pk"].endswith("character_sheet")]
    expected = with_phase_filter({"KeyConditionExpression": "x", "ExpressionAttributeValues": {}})
    assert cs and cs[0].get("FilterExpression") == expected.get("FilterExpression")


def test_gather_computes_the_sixty_day_training_load(monkeypatch, frozen_monday):
    monkeypatch.setattr(m, "table", _seeded_table())
    data, _ = m.gather_all()
    tl = data["training_load"]
    assert set(tl) == {"ctl", "atl", "tsb"}
    assert tl["ctl"] >= 0 and tl["atl"] >= 0  # banister clamps both non-negative


def test_gather_returns_the_annual_goals_alongside_the_data(monkeypatch, frozen_monday):
    monkeypatch.setattr(m, "table", _seeded_table())
    _, goals = m.gather_all()
    assert goals["weight"]["current_lbs"] == 305.0
    assert goals["weight"]["lost_lbs"] == 16.6  # 321.6 - 305.0


def test_a_character_sheet_read_failure_never_blocks_the_letter(monkeypatch, frozen_monday):
    table = _seeded_table()

    def _hook(tbl, **kwargs):
        if kwargs["ExpressionAttributeValues"][":pk"].endswith("character_sheet"):
            raise RuntimeError("ddb down")
        return _range_query_hook(tbl, **kwargs)

    table._query_hook = _hook
    monkeypatch.setattr(m, "table", table)
    data, _ = m.gather_all()
    assert data["cur"]["character_sheet"] is None
    assert data["cur"]["whoop"]["days"] == 2  # the rest of the month survived


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P3): monthly_digest_lambda.gather_all line 584 lists 'eightsleep' among the "
        "sources it fetches for BOTH arms, but `extractors` (lines 585-592) has no eightsleep entry and nothing "
        "downstream reads raw_cur['eightsleep']. Two full DynamoDB range queries per month are issued and discarded, "
        "and the Eight Sleep bed data never reaches the letter at all."
    ),
)
def test_every_source_the_letter_fetches_reaches_the_letter(monkeypatch, frozen_monday):
    monkeypatch.setattr(m, "table", _seeded_table())
    data, _ = m.gather_all()
    fetched = {"whoop", "withings", "strava", "eightsleep", "hevy", "macrofactor", "todoist", "chronicling"}
    assert fetched <= set(data["cur"])


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P3): gather_all lines 605-612 build `cur`/`prior` with every extractor and then "
        "IMMEDIATELY overwrite the strava and macrofactor entries with profile-aware recomputations. ex_strava and "
        "ex_macrofactor each run twice per arm — four wasted passes over the month's records (including a full "
        "dedup_activities sweep) every run."
    ),
)
def test_each_extractor_runs_once_per_arm(monkeypatch, frozen_monday):
    monkeypatch.setattr(m, "table", _seeded_table())
    calls = []
    real = m.ex_strava
    monkeypatch.setattr(m, "ex_strava", lambda recs, profile=None: calls.append(1) or real(recs, profile))
    m.gather_all()
    assert len(calls) == 2  # one current arm, one prior arm


# ══════════════════════════════════════════════════════════════════════════════
# build_html — what the reader actually reads
# ══════════════════════════════════════════════════════════════════════════════

COMMENTARY = (
    "🏋️ DR. SARAH CHEN — MONTHLY TRAINING REVIEW\n"
    "Volume climbed steadily through the month.\n"
    "🥗 DR. MARCUS WEBB — MONTHLY NUTRITION REVIEW\n"
    "Protein adherence held.\n"
    "💡 INSIGHT OF THE MONTH\n"
    "Add one Zone 2 session per week."
)


def _data(**over):
    base = {
        "cur": {
            "whoop": {"recovery_avg": 64.0, "hrv_avg": 52.0, "hrv_min": 40.0, "hrv_max": 66.0, "rhr_avg": 57.0, "days": 30},
            "prior": None,
            "sleep": {"score_avg": 74.0, "duration_avg_hrs": 7.1, "efficiency_avg": 88.0, "rem_pct": 21.0, "deep_pct": 15.0, "nights": 29},
            "strava": {
                "total_miles": 62.5,
                "total_minutes": 940,
                "activity_count": 18,
                "zone2_minutes": 520,
                "zone2_pct": 55,
                "zone2_hr_range": "114-133",
                "total_elevation_feet": 3400,
            },
            "withings": {"weight_latest": 305.0, "weight_avg": 307.4, "weight_min": 304.0, "weight_max": 311.0, "body_fat_avg": 36.0},
            "macrofactor": {
                "calories_avg": 1780.0,
                "protein_avg_g": 192.0,
                "calorie_target": 1800,
                "protein_target": 190,
                "days_logged": 28,
                "protein_hit_rate": 71,
                "calorie_hit_rate": 64,
            },
            "chronicling": {
                "score_avg": 71.0,
                "group_avgs": {"sleep": 80.0, "food": 55.0},
                "days": 30,
                "best_group": "sleep",
                "worst_group": "food",
            },
            "hevy": {"workout_count": 12},
            "character_sheet": {
                "character_level": 14.0,
                "character_xp": 5200.0,
                "character_tier": "🌱 Momentum",
                "xp_delta_30d": 900,
                "pillars": {"sleep": {"level": 12.0, "tier": "Momentum"}},
                "days_tracked": 30,
            },
            "todoist": {"tasks_completed": 140, "days": 30},
        },
        "prior": {
            "whoop": {"recovery_avg": 60.0, "hrv_avg": 48.0, "rhr_avg": 59.0},
            "sleep": {"score_avg": 70.0, "duration_avg_hrs": 6.8, "efficiency_avg": 86.0},
            "strava": {"total_miles": 50.0, "total_minutes": 800, "activity_count": 14, "total_elevation_feet": 2900},
            "withings": {"weight_latest": 312.0, "weight_avg": 313.5, "body_fat_avg": 37.0},
            "macrofactor": {"calories_avg": 1900.0, "protein_avg_g": 175.0},
            "chronicling": {"score_avg": 66.0, "group_avgs": {"sleep": 75.0, "food": 50.0}},
            "hevy": {"workout_count": 9},
            "character_sheet": {"character_level": 13.0, "pillars": {"sleep": {"level": 11.0}}},
        },
        "training_load": {"ctl": 42.5, "atl": 38.1, "tsb": 4.4},
        "profile": {"goal_weight_lbs": 220.0, "journey_start_weight_lbs": 321.6, "journey_start_date": "2026-08-03"},
        "windows": dict(WINDOWS),
    }
    base.update(over)
    return base


GOALS = {
    "year_pct_elapsed": 59,
    "weight": {
        "current_lbs": 305.0,
        "goal_lbs": 220.0,
        "lost_lbs": 16.6,
        "to_go_lbs": 85.0,
        "pct_complete": 16,
        "journey_start_weight": 321.6,
    },
    "training_activities_30d": 18,
    "zone2_minutes_30d": 520,
    "habit_score_avg": 71.0,
}


def _html(**over):
    d = _data(**over)
    return m.build_html(d, GOALS, COMMENTARY, d["windows"])


def test_the_letter_is_headlined_with_the_month_and_the_comparison_month():
    html = _html()
    assert "August 2026" in html
    assert "Deltas vs July 2026" in html


def test_the_letter_carries_every_advisor_section_from_the_commentary():
    body = _text(_html())
    assert "DR. SARAH CHEN" in body and "DR. MARCUS WEBB" in body
    assert "Volume climbed steadily through the month." in body


def test_the_insight_of_the_month_is_lifted_into_its_own_box():
    html = _html()
    box = re.search(r'<div style="background:#fffbeb;border:2px solid #f59e0b;.*?</div>', html, re.S)
    assert box is not None
    assert "Add one Zone 2 session per week." in box.group(0)
    assert "Volume climbed steadily" not in box.group(0)  # the advisor sections stay out of it


def test_the_training_section_reports_the_months_real_figures():
    html = _html()
    assert _row(html, "Total Miles")[1].startswith("62.5 mi")
    assert _row(html, "Activities")[1].startswith("18")
    assert _row(html, "Total Elevation")[1].startswith("3,400 ft")


def test_the_training_section_shows_the_month_over_month_direction():
    html = _html()
    assert "↑12.5 mi" in _row(html, "Total Miles")[1]  # 62.5 - 50.0
    assert "↑4" in _row(html, "Activities")[1]  # 18 - 14


def test_the_zone_two_row_states_the_band_it_was_measured_in():
    html = _html()
    label = [r[0] for r in _rows(html) if r and r[0].startswith("Zone 2")][0]
    assert "114-133 bpm" in label


def test_the_recovery_section_reports_the_hrv_range_it_observed():
    assert _row(_html(), "HRV Range")[1] == "40.0 ms – 66.0 ms"


def test_a_lower_resting_heart_rate_reads_as_an_improvement():
    """RHR is inverted — down is better, so it must render green."""
    html = _html()
    cell = _row(html, "Avg RHR")
    assert "↓2.0 bpm" in cell[1]
    tr = [t for t in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S) if "Avg RHR" in t][0]
    assert "#27ae60" in tr  # green


def test_a_higher_resting_heart_rate_reads_as_a_regression():
    d = _data()
    d["prior"]["whoop"]["rhr_avg"] = 54.0
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    tr = [t for t in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S) if "Avg RHR" in t][0]
    assert "#e74c3c" in tr  # red


def test_a_metric_that_did_not_move_reads_as_unchanged_not_as_a_direction():
    d = _data()
    d["prior"]["whoop"]["hrv_avg"] = 52.0  # identical to the current month
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert "→0" in _row(html, "Avg HRV")[1]


def test_the_sleep_section_reports_the_nights_behind_its_averages():
    """ADR-105: an average published with its n."""
    assert _row(_html(), "Nights Tracked")[1] == "29"


def test_the_weight_section_reports_the_month_end_weight_and_the_journey_total():
    html = _html()
    assert _row(html, "Month-End Weight")[1].startswith("305.0 lbs")
    assert "16.6 lbs lost" in _row(html, "Journey Progress")[1]


def test_the_nutrition_section_reports_the_days_logged_behind_the_averages():
    html = _html()
    assert _row(html, "Avg Calories")[1].startswith("1780.0 kcal")
    assert _row(html, "Days Logged")[1] == "28"


def test_the_habits_section_lists_every_group_it_scored():
    html = _html()
    labels = [r[0] for r in _rows(html) if r]
    assert "↳ sleep" in labels and "↳ food" in labels
    assert _row(html, "🏆 Best Group")[1] == "sleep"


def test_the_character_section_reports_the_level_and_the_months_xp():
    html = _html()
    assert "Level 14" in _row(html, "Character Level")[1]
    assert _row(html, "XP This Month")[1] == "+900 XP"
    assert _row(html, "Total XP")[1] == "5,200"


def test_a_month_of_lost_xp_is_reported_as_a_loss():
    d = _data()
    d["cur"]["character_sheet"]["xp_delta_30d"] = -250
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert _row(html, "XP This Month")[1] == "-250 XP"


def test_a_month_with_no_nutrition_data_says_so_instead_of_showing_zeroes():
    d = _data()
    d["cur"]["macrofactor"] = None
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert "MacroFactor pending" in _text(html)
    assert _row(html, "Avg Calories") is None


def test_a_month_with_no_habit_data_says_so_instead_of_showing_zeroes():
    d = _data()
    d["cur"]["chronicling"] = None
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert "Chronicling data not available" in _text(html)


def test_a_month_with_no_recovery_data_omits_the_recovery_section_entirely():
    d = _data()
    d["cur"]["whoop"] = None
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert "Recovery & HRV" not in " ".join(_sections(html))


def test_a_month_with_no_sleep_or_weight_data_omits_those_sections():
    d = _data()
    d["cur"]["sleep"] = None
    d["cur"]["withings"] = None
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    joined = " ".join(_sections(html))
    assert "Sleep — 30 Days" not in joined
    assert "Weight & Body Composition" not in joined


def test_a_month_with_no_character_data_omits_the_character_section():
    d = _data()
    d["cur"]["character_sheet"] = None
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert "Character Sheet" not in " ".join(_sections(html))


def test_the_first_month_has_no_prior_arm_and_still_renders():
    d = _data(prior={})
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert _row(html, "Total Miles")[1] == "62.5 mi"  # no delta appended
    assert "↑" not in _row(html, "Total Miles")[1]


def test_an_absent_figure_renders_as_an_em_dash_not_a_zero():
    d = _data()
    d["cur"]["macrofactor"]["calories_avg"] = None
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert _row(html, "Avg Calories")[1].startswith("—")


def test_the_annual_goals_bar_reports_the_weight_progress_and_the_year_elapsed():
    body = _text(_html())
    assert "16% done" in body
    assert "59%" in body


def test_the_progress_bars_are_clamped_to_the_bar_width():
    goals = dict(GOALS, year_pct_elapsed=140, weight=dict(GOALS["weight"], pct_complete=-30))
    d = _data()
    html = m.build_html(d, goals, COMMENTARY, d["windows"])
    widths = [int(w) for w in re.findall(r"width:(-?\d+)%", html)]
    assert all(0 <= w <= 100 for w in widths)


def test_every_monthly_letter_carries_the_not_medical_advice_disclaimer():
    assert "not medical advice" in _text(_html())


def test_the_letter_renders_even_when_the_board_commentary_is_empty():
    d = _data()
    html = m.build_html(d, GOALS, "", d["windows"])
    assert "August 2026" in html
    assert _row(html, "Total Miles") is not None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2): build_html line 724 detects an advisor's section header by matching a "
        "HARDCODED six-emoji tuple ('🏋️','🥗','😴','🩺','🧠','🎯'), while _build_monthly_prompt_from_config builds the "
        "headers from whichever members the S3 board config assigns to `monthly_digest`, each with their OWN emoji. "
        "An advisor added to the board (or one whose emoji lacks the exact VS16 variation selector) has their header "
        "rendered as ordinary body prose — the section silently loses its heading. The renderer must derive the "
        "header set from the same board config the prompt was built from."
    ),
)
def test_an_advisor_added_to_the_board_still_gets_a_rendered_section_header():
    commentary = "🧬 DR. HENNING BRANDT — MONTHLY RIGOR REVIEW\nThe n behind each claim held up.\n"
    d = _data()
    html = m.build_html(d, GOALS, commentary, d["windows"])
    header_para = [p for p in re.findall(r"<p[^>]*>(.*?)</p>", html, re.S) if "HENNING BRANDT" in p][0]
    assert "font-weight:700" in header_para


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-104): build_html lines 833-839 render the CTL/TSB rows "
        "unconditionally, outside the `if st_c:` guard. A month with no recorded activity at all still publishes "
        "'CTL — 42-day Fitness: 0.0' and 'TSB — Current Form: 0.0 (Neutral)' — a confident fitness verdict computed "
        "over no data. With nothing measured the rows should be absent, not zeroed."
    ),
)
def test_a_month_with_no_training_does_not_publish_a_fitness_verdict():
    d = _data()
    d["cur"]["strava"] = None
    d["training_load"] = {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert _row(html, "TSB — Current Form") is None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P3): build_html's delta helpers are called as `delta(...) if prior_val else ''` "
        "(sc_pill line 754, habits line 935, character line 958/983). A prior-month value of exactly 0 — zero "
        "activities, a level-0 pillar, a 0% group — is falsy, so the month-over-month arrow is suppressed precisely "
        "when the improvement is largest. The guard should test for None, not falsiness."
    ),
)
def test_an_improvement_from_zero_still_shows_its_arrow():
    d = _data()
    d["prior"]["chronicling"]["group_avgs"]["food"] = 0
    html = m.build_html(d, GOALS, COMMENTARY, d["windows"])
    assert "↑55" in _row(html, "↳ food")[1]  # 55.0 - 0


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — mail is NEVER actually sent
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def handler_env(monkeypatch, frozen_monday):
    """Wire lambda_handler to fakes. `ses` is a fake; no AWS, no Bedrock."""
    ses = FakeSES()
    writer = FakeInsightWriter()
    state = {"commentary": COMMENTARY, "ai_error": None}
    calls = {"ai": []}

    monkeypatch.setattr(m, "ses", ses)
    monkeypatch.setattr(m, "table", _seeded_table())
    monkeypatch.setattr(m, "insight_writer", writer)
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", True)
    monkeypatch.setattr(m, "_HAS_AI_VALIDATOR", True)

    def _fake_haiku(data, goals):
        calls["ai"].append((data, goals))
        if state["ai_error"]:
            raise state["ai_error"]
        return state["commentary"]

    monkeypatch.setattr(m, "call_haiku_monthly", _fake_haiku)
    return {"ses": ses, "writer": writer, "state": state, "calls": calls, "monkeypatch": monkeypatch}


def _sent_html(env):
    return env["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]


def _sent_subject(env):
    return env["ses"].sent[0]["Content"]["Simple"]["Subject"]["Data"]


def test_the_letter_is_sent_once_to_the_configured_recipient(handler_env):
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert len(handler_env["ses"].sent) == 1
    sent = handler_env["ses"].sent[0]
    assert sent["FromEmailAddress"] == m.SENDER
    assert sent["Destination"]["ToAddresses"] == [m.RECIPIENT]


def test_the_subject_line_names_the_month(handler_env):
    m.lambda_handler({}, None)
    assert _sent_subject(handler_env) == "Monthly Coach's Letter · August 2026"


def test_the_send_is_tagged_for_open_and_bounce_tracking(handler_env):
    m.lambda_handler({}, None)
    sent = handler_env["ses"].sent[0]
    assert sent["ConfigurationSetName"] == "life-platform-emails"
    assert sent["EmailTags"] == [{"Name": "message_type", "Value": "monthly_digest"}]


def test_the_board_receives_the_months_real_data(handler_env):
    m.lambda_handler({}, None)
    data, goals = handler_env["calls"]["ai"][0]
    assert data["cur"]["whoop"]["days"] == 2
    assert goals["weight"]["current_lbs"] == 305.0


def test_the_delivered_letter_carries_the_board_commentary(handler_env):
    handler_env["state"]["commentary"] = "🎯 THE CHAIR — MONTHLY VERDICT\nA genuinely good month.\n💡 INSIGHT OF THE MONTH\nKeep going."
    m.lambda_handler({}, None)
    assert "A genuinely good month." in _text(_sent_html(handler_env))


def test_the_delivered_letter_carries_the_months_own_numbers(handler_env):
    m.lambda_handler({}, None)
    html = _sent_html(handler_env)
    assert _row(html, "Month-End Weight")[1].startswith("305.0 lbs")


def test_a_board_failure_still_ships_the_letter_with_the_data_intact(handler_env):
    handler_env["state"]["ai_error"] = RuntimeError("bedrock throttled")
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    html = _sent_html(handler_env)
    assert "Commentary unavailable this month." in _text(html)
    assert _row(html, "Month-End Weight")[1].startswith("305.0 lbs")


def test_a_delivered_letter_is_recorded_in_the_insight_ledger(handler_env):
    m.lambda_handler({}, None)
    assert len(handler_env["writer"].written) == 1
    assert handler_env["writer"].written[0]["digest_type"] == "monthly_digest"


def test_a_broken_insight_ledger_never_blocks_the_letter(handler_env):
    class Exploding(FakeInsightWriter):
        def write_insight(self, **kwargs):
            raise RuntimeError("ddb down")

    handler_env["monkeypatch"].setattr(m, "insight_writer", Exploding())
    assert m.lambda_handler({}, None)["statusCode"] == 200
    assert len(handler_env["ses"].sent) == 1


def test_blocked_board_output_is_replaced_by_the_validators_safe_fallback(handler_env):
    from ai import ai_output_validator as aiv

    result = aiv.AIValidationResult(
        original_text="whatever",
        output_type=aiv.AIOutputType.MONTHLY_DIGEST,
        blocked=True,
        block_reason="hallucinated a lab value",
        safe_fallback="🎯 THE CHAIR\nHeld for review.",
    )
    handler_env["monkeypatch"].setattr(m, "validate_ai_output", lambda *a, **k: result)
    m.lambda_handler({}, None)
    body = _text(_sent_html(handler_env))
    assert "Held for review." in body
    assert "Volume climbed steadily" not in body


def test_board_output_with_warnings_is_still_delivered(handler_env):
    from ai import ai_output_validator as aiv

    result = aiv.AIValidationResult(original_text=COMMENTARY, output_type=aiv.AIOutputType.MONTHLY_DIGEST, warnings=["generic phrasing"])
    handler_env["monkeypatch"].setattr(m, "validate_ai_output", lambda *a, **k: result)
    m.lambda_handler({}, None)
    assert "Volume climbed steadily" in _text(_sent_html(handler_env))


def test_the_letter_does_not_go_out_on_a_day_that_is_not_a_monday(monkeypatch, frozen_cron_sunday):
    ses = FakeSES()
    monkeypatch.setattr(m, "ses", ses)
    resp = m.lambda_handler({}, None)
    assert resp["body"] == "skipped — not Monday"
    assert ses.sent == []


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P1): the monthly letter can never be sent by its own schedule. "
        "cdk/stacks/email_stack.py schedules monthly-digest on `cron(0 16 ? * 1#1 *)` and the module docstring reads "
        "'Fires first Sunday of each month' — in EventBridge cron the day-of-week field is 1-7 = SUN-SAT, so 1#1 is "
        "the FIRST SUNDAY. lambda_handler lines 1033-1036 then return 'skipped — not Monday' unless "
        "date.today().weekday() == 0. Sunday is never Monday, so every scheduled invocation no-ops and Matthew "
        "receives no monthly letter at all. The guard and the schedule must agree on one day."
    ),
)
def test_the_letter_is_sent_on_the_day_its_own_schedule_fires(monkeypatch, frozen_cron_sunday):
    ses = FakeSES()
    monkeypatch.setattr(m, "ses", ses)
    monkeypatch.setattr(m, "table", _seeded_table())
    monkeypatch.setattr(m, "call_haiku_monthly", lambda data, goals: COMMENTARY)
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    m.lambda_handler({}, None)
    assert len(ses.sent) == 1


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2): lambda_handler line 1033 reads `date.today()` — the runtime's LOCAL date "
        "— to make a weekday decision, while every other date in this module comes from "
        "`datetime.now(timezone.utc)`. All EventBridge crons in this repo are fixed-UTC by convention precisely so "
        "the weekday can't drift; a local-time read reintroduces the drift the convention removes. It should be "
        "datetime.now(timezone.utc).date()."
    ),
)
def test_the_weekday_guard_reads_the_clock_in_utc(monkeypatch):
    """Freeze only the module's UTC clock and leave date.today() alone: a
    UTC-derived guard follows the frozen clock, a local one does not."""
    monkeypatch.setattr(m, "datetime", _frozen_datetime_class(GUARD_MONDAY))
    monkeypatch.setattr(m, "ses", FakeSES())
    monkeypatch.setattr(m, "table", _seeded_table())
    monkeypatch.setattr(m, "call_haiku_monthly", lambda data, goals: COMMENTARY)
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    assert m.lambda_handler({}, None)["body"] != "skipped — not Monday"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / #2111 class): monthly_digest_lambda.lambda_handler has NO dry_run gate. "
        "Sibling email lambdas (between_chronicle, chronicle_approve, coach_panel_podcast) honour "
        "{'dry_run': true}. Any manual or regeneration invoke on a Monday mails Matthew a real monthly letter — "
        "there is no way to exercise this function against production data without sending."
    ),
)
def test_a_dry_run_invocation_builds_the_letter_without_mailing_it(handler_env):
    resp = m.lambda_handler({"dry_run": True}, None)
    assert resp["statusCode"] == 200
    assert handler_env["ses"].sent == []


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2): lambda_handler writes no send record and reads none, so nothing prevents "
        "a double-send. Two invocations in the same month (a retry, a manual re-run, an EventBridge at-least-once "
        "redelivery) mail two identical letters and file two identical insights. Every other email lambda in this "
        "package calls record_email_send; this one does not, so the status page also cannot report the monthly "
        "letter's last send at all. cf. #2112, the same class on chronicle-email-sender."
    ),
)
def test_the_monthly_letter_is_not_sent_twice_in_the_same_month(handler_env):
    m.lambda_handler({}, None)
    m.lambda_handler({}, None)
    assert len(handler_env["ses"].sent) == 1


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2 / ADR-104): when the board call fails, lambda_handler substitutes the stub "
        "'🎯 THE CHAIR — MONTHLY OVERVIEW\\nCommentary unavailable this month.' and then gates IC-15 on "
        "`'unavailable' not in commentary[:50]`. The stub's first 50 characters end at '...Commentary unavail' — the "
        "word 'unavailable' starts at index 42 and does not FIT in the slice, so the sentinel can never fire. The "
        "failure stub is filed into the insight ledger as a genuine monthly coaching insight with "
        "confidence='high', actionable=True. The same sentinel guards the AI-3 blocked path."
    ),
)
def test_a_board_failure_stub_is_not_filed_as_a_genuine_monthly_insight(handler_env):
    handler_env["state"]["ai_error"] = RuntimeError("bedrock throttled")
    m.lambda_handler({}, None)
    assert handler_env["writer"].written == []


def test_the_unavailable_sentinel_cannot_see_the_word_it_looks_for():
    """The arithmetic behind the xfail above, pinned so the fix is checkable.

    '🎯 THE CHAIR — MONTHLY OVERVIEW\\n' is 31 characters; 'Commentary ' takes it
    to 42, so 'unavailable' occupies indices 42-52 and is truncated at 50.
    """
    stub = "🎯 THE CHAIR — MONTHLY OVERVIEW\nCommentary unavailable this month.\n💡 INSIGHT OF THE MONTH\nReview your data sections below."
    assert stub.index("unavailable") == 42
    assert "unavailable" not in stub[:50]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-3 discovery, P2, reader/writer mismatch): lambda_handler line 1093 files the monthly "
        "insight with `date=month` — a display label like 'August 2026'. Every other writer stores a YYYY-MM-DD "
        "date, and insight_writer.get_recent_insights filters with a STRING comparison "
        "`i.get('date','') >= cutoff_date`. 'August 2026' > any '2026-..-..' cutoff because 'A' sorts above the "
        "digits, so a monthly insight NEVER ages out of the 14/30/90-day windows — it is replayed into every "
        "downstream AI prompt (daily brief, chronicle, nutrition review) until its 180-day TTL expires."
    ),
)
def test_a_monthly_insight_is_dated_so_that_it_can_age_out_of_the_context_window(handler_env):
    m.lambda_handler({}, None)
    stored_date = handler_env["writer"].written[0]["date"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(stored_date))
