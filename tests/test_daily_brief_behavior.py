#!/usr/bin/env python3
"""tests/test_daily_brief_behavior.py — behavioral contracts of
`lambdas/emails/daily_brief_lambda.py` (the Morning Brief, 17:00 UTC / 10:00 PT).

Part of #1658 tranche 3. This is the most-read surface the platform has: one
human opens it every morning, and a slice of what it computes is then published
to `generated/public_stats.json` and `pulse.json`, which the public website and
the OG share cards render. So the contracts under test are the ones that reach
a reader:

  * **honest numbers (ADR-104)** — an absent source must never surface as a
    factual `0` or a neutral mid-scale default. Several sites here do exactly
    that; each is pinned with an `xfail` naming the line;
  * **reader/writer field agreement** — every field this module reads off a
    pre-computed DynamoDB row must be a field some writer in this repo actually
    stores. Tranche 2 found six independent instances of the mismatch class,
    each leaving a feature permanently dark; this file adds the daily brief's;
  * **one concept, one implementation** — where this module and a compute
    Lambda both derive "the same" number differently, the divergence is pinned
    so the reader-visible answer stops depending on which pipeline ran;
  * **window-name honesty (#1917)** — a figure named for a window it does not
    cover;
  * **staleness** — a pre-computed row presented as current on the basis of
    nothing, and a "Data Status" banner whose thresholds contradict the
    canonical source registry;
  * **streaks** — what a missing day does to a streak the reader is shown;
  * **crash paths** — a `None`/malformed cell that escapes `lambda_handler`
    and loses the whole brief;
  * **dry-run + privacy** — which side effects a DRY_RUN invocation still has,
    and which private-by-default data reaches a public artifact.

**Safety.** `daily_brief_lambda` sends real mail through SESv2. No test in this
file can reach a send path, a DynamoDB table, S3, CloudWatch, Bedrock or a
Lambda invoke: every client the module holds (`table`, `ses`, `s3`, `boto3`) is
replaced with a hand-rolled bounded fake, and every lazily-imported collaborator
is stubbed. The one assertion made about SES is that the fake recorded (or did
not record) a call.

Time is frozen module-wide by an autouse fixture pinned to the real cron
instant (17:00 UTC == 10:00 PDT). No fixture date is ever combined with the
wall clock.

Complements rather than repeats: `test_daily_brief_budget_gate.py` (the Band-3
ladder), `test_daily_brief_grounding_and_hold.py` (AI grounding + #966 holds),
`test_genesis_blind_brief_windows_2089.py` / `test_genesis_blind_reads_2080_2081.py`
(the ADR-058 phase-filter decisions), `test_compute_staleness_genesis_window_1962.py`
(the alarm-suppression marker) and `test_daily_brief_golden.py` (markup).
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The module validates these at import time and raises RuntimeError without them.
for _k, _v in [
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("AWS_ACCESS_KEY_ID", "testing"),
    ("AWS_SECRET_ACCESS_KEY", "testing"),
    ("TABLE_NAME", "life-platform"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("USER_ID", "matthew"),
    ("EMAIL_RECIPIENT", "reader@example.invalid"),
    ("EMAIL_SENDER", "brief@example.invalid"),
    ("AI_VALIDATOR_AUTOLOAD", "off"),
]:
    os.environ.setdefault(_k, _v)

sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))

_import_err = None
try:
    import daily_brief_lambda as brief  # noqa: E402
    from experiment import phase_taxonomy as tax  # noqa: E402
    from experiment.phase_filter import PHASE_FILTER_EXPRESSION  # noqa: E402
    from ingestion import source_registry as registry  # noqa: E402
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    brief = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"daily_brief_lambda unavailable: {_import_err}")  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
# Frozen clock
# ══════════════════════════════════════════════════════════════════════════════

# The EventBridge rule is fixed UTC (no DST drift): 17:00 UTC == 10:00 PDT, so
# the UTC date and the rendered PT date agree at the moment the brief runs.
# 2026-08-07 is a Friday — the Sunday-only weekly habit review stays off.
FROZEN_NOW = datetime(2026, 8, 7, 17, 0, 0, tzinfo=timezone.utc)

TODAY = "2026-08-07"  # now().date()
YESTERDAY = "2026-08-06"  # the subject date — today - 1
D7 = "2026-07-31"  # today - 7   (the 7-day windows' inclusive floor)
D14 = "2026-07-24"  # today - 14
D30 = "2026-07-08"  # today - 30
D60 = "2026-06-08"  # today - 60
D90 = "2026-05-09"  # today - 90


class _FrozenDatetime(datetime):
    """`datetime` with a pinned `now()`.

    A subclass, not a Mock: the module uses `strptime`, `fromisoformat`,
    subtraction and `.date()` off this same name, and all of them must keep
    working.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):  # pragma: no cover — not used by the module, kept for parity
        return FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(brief, "datetime", _FrozenDatetime)
    return FROZEN_NOW


# ══════════════════════════════════════════════════════════════════════════════
# Test doubles — hand-rolled and bounded (never a MagicMock inside a read loop)
# ══════════════════════════════════════════════════════════════════════════════


def _flatten_key_condition(expr):
    """Yield (pk_value, begins_with_prefix, between_bounds) from a boto3 `Key`
    condition tree — exactly one member of each triple is non-None."""
    if expr is None:
        return
    operator = expr.get("operator")
    values = expr.get("values", ())
    if operator == "AND":
        for sub in values:
            yield from _flatten_key_condition(sub.get_expression())
        return
    attr, operand = values[0], values[1]
    name = getattr(attr, "name", None)
    if name == "pk" and operator == "=":
        yield operand, None, None
    elif name == "sk" and operator == "begins_with":
        yield None, operand, None
    elif name == "sk" and operator == "BETWEEN":
        yield None, None, (operand, values[2])


class FakeTable:
    """A mini-DynamoDB faithful in the ways this module's reads depend on.

    * both key-condition forms the module uses — the boto3 `Key()` object form
      (`_latest_item`, `fetch_hevy_workouts`, `scan_stale_sources`) and the raw
      expression-string form (`fetch_range`, `fetch_journal_entries`,
      `fetch_social_posts`, the travel read);
    * `sk BETWEEN` and `begins_with` bounds, so "the window bounds the answer"
      is falsifiable;
    * `Limit` applied BEFORE `FilterExpression` and after `ScanIndexForward` —
      DynamoDB's real order, and the mechanism of the #1203/#2080 class;
    * `get_item` / `put_item` / `update_item` against the same keyed store.

    Every call is logged so a test can assert on the window and the ADR-058
    phase filter rather than only on the returned rows.
    """

    def __init__(self, rows=None):
        self.store = {}
        for row in rows or []:
            self.store[(row["pk"], row["sk"])] = row
        self.queries = []
        self.gets = []
        self.puts = []
        self.updates = []
        self.query_error = None
        self.get_error = None
        self.put_error = None

    # -- writes ---------------------------------------------------------------
    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        if self.put_error is not None:
            raise self.put_error
        self.store[(Item["pk"], Item["sk"])] = Item
        return {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    # -- reads ----------------------------------------------------------------
    def get_item(self, Key=None, **kwargs):
        self.gets.append(Key)
        if self.get_error is not None:
            raise self.get_error
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.query_error is not None:
            raise self.query_error
        vals = kwargs.get("ExpressionAttributeValues") or {}
        items = [dict(r) for r in self.store.values()]

        cond = kwargs.get("KeyConditionExpression")
        if isinstance(cond, str):
            pk = vals.get(":pk")
            if pk is not None:
                items = [i for i in items if i.get("pk") == pk]
            if ":s" in vals and ":e" in vals:
                items = [i for i in items if vals[":s"] <= str(i["sk"]) <= vals[":e"]]
            if ":prefix" in vals:
                items = [i for i in items if str(i["sk"]).startswith(vals[":prefix"])]
        else:
            expr = cond.get_expression() if cond is not None else None
            for pk_val, prefix, between in _flatten_key_condition(expr):
                if pk_val is not None:
                    items = [i for i in items if i.get("pk") == pk_val]
                if prefix is not None:
                    items = [i for i in items if str(i["sk"]).startswith(prefix)]
                if between is not None:
                    lo, hi = between
                    items = [i for i in items if lo <= str(i["sk"]) <= hi]

        items.sort(key=lambda i: str(i["sk"]), reverse=not kwargs.get("ScanIndexForward", True))

        limit = kwargs.get("Limit")
        if limit is not None:
            items = items[:limit]
        if kwargs.get("FilterExpression") and ":phase_experiment" in vals:
            current = vals[":phase_experiment"]
            items = [i for i in items if i.get("phase") in (None, current)]
        return {"Items": items}


class FakeSes:
    """SESv2 stand-in. Nothing in this file can reach a real send path."""

    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "fake-message-id"}


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {}

    def get_object(self, **kwargs):  # pragma: no cover — config reads are stubbed out
        raise RuntimeError("no S3 in tests")


class FakeCloudWatch:
    def __init__(self):
        self.metrics = []

    def put_metric_data(self, **kwargs):
        self.metrics.append(kwargs)
        return {}


class FakeLambdaClient:
    def __init__(self):
        self.invocations = []

    def invoke(self, **kwargs):
        self.invocations.append(kwargs)
        return {"StatusCode": 202}


class FakeBoto3:
    """Stands in for the module-level `boto3` name so `boto3.client(...)` inside
    `lambda_handler` (CloudWatch) and `_run_ai_coach_pipeline` (Lambda invoke)
    cannot reach AWS."""

    def __init__(self):
        self.cloudwatch = FakeCloudWatch()
        self.lambda_client = FakeLambdaClient()

    def client(self, service, **kwargs):
        if service == "cloudwatch":
            return self.cloudwatch
        if service == "lambda":
            return self.lambda_client
        raise AssertionError(f"unexpected boto3 client requested in a test: {service}")


class _Recorder:
    """A bounded callable that records its calls and returns a canned value."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


# ══════════════════════════════════════════════════════════════════════════════
# Row builders
# ══════════════════════════════════════════════════════════════════════════════


def row(source, sk, **fields):
    return {"pk": brief.USER_PREFIX + source, "sk": sk, **fields}


def day_row(source, date_str, **fields):
    return row(source, "DATE#" + date_str, date=date_str, **fields)


def whoop_row(date_str, **fields):
    return day_row("whoop", date_str, **fields)


def withings_row(date_str, weight_lbs=None, **fields):
    extra = {} if weight_lbs is None else {"weight_lbs": Decimal(str(weight_lbs))}
    return day_row("withings", date_str, **extra, **fields)


def habitify_row(date_str, habits):
    return day_row("habitify", date_str, habits=habits)


PROFILE = {
    "sleep_target_hours_ideal": 7.5,
    "journey_start_weight_lbs": 321.6,
    "goal_weight_lbs": 185,
    "journey_start_date": "2026-08-03",
    "day_grade_weights": {},
    "day_grade_algorithm_version": "1.1",
    "habit_registry": {},
    "mvp_habits": [],
    "weight_loss_phases": [
        {"name": "Ignition", "end_lbs": 300},
        {"name": "Momentum", "end_lbs": 250},
        {"name": "Refinement", "end_lbs": 185},
    ],
}


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(brief, "table", t)
    return t


@pytest.fixture
def ses(monkeypatch):
    s = FakeSes()
    monkeypatch.setattr(brief, "ses", s)
    return s


# ══════════════════════════════════════════════════════════════════════════════
# 1. Small helpers
# ══════════════════════════════════════════════════════════════════════════════


class TestSmallHelpers:
    def test_avg_of_an_empty_list_is_absence_not_zero(self):
        """ADR-104: the shape `sum(x)/max(1, len(x))` would say 0 here."""
        assert brief.avg([]) is None
        assert brief.avg([None, None]) is None

    def test_avg_ignores_missing_readings_but_keeps_measured_zeros(self):
        # (4.0 + 0.0 + 2.0) / 3 = 2.0 — a measured zero is data, a None is not.
        assert brief.avg([4.0, None, 0.0, 2.0]) == 2.0

    def test_clamp_bounds_a_score_to_the_scale(self):
        assert brief.clamp(-40) == 0
        assert brief.clamp(140) == 100
        assert brief.clamp(55) == 55

    def test_fmt_num_renders_absence_as_an_em_dash(self):
        assert brief.fmt_num(None) == "—"
        assert brief.fmt_num(1234.6) == "1,235"

    def test_current_phase_is_the_first_phase_the_weight_still_clears(self):
        assert brief.get_current_phase(PROFILE, 310.0)["name"] == "Ignition"
        assert brief.get_current_phase(PROFILE, 260.0)["name"] == "Momentum"

    def test_current_phase_falls_back_to_the_last_phase_below_every_floor(self):
        assert brief.get_current_phase(PROFILE, 150.0)["name"] == "Refinement"

    def test_current_phase_is_absent_when_the_profile_declares_none(self):
        assert brief.get_current_phase({}, 300.0) is None


# ══════════════════════════════════════════════════════════════════════════════
# 2. Whoop sleep normalisation
# ══════════════════════════════════════════════════════════════════════════════


class TestNormaliseWhoopSleep:
    def test_none_passes_through(self):
        assert brief._normalize_whoop_sleep(None) is None

    def test_whoop_field_names_are_mapped_to_the_brief_schema(self):
        out = brief._normalize_whoop_sleep(
            {
                "sleep_quality_score": 82,
                "sleep_efficiency_percentage": 91.2,
                "time_awake_hours": 0.6,
                "disturbance_count": 12,
            }
        )
        assert out["sleep_score"] == 82
        assert out["sleep_efficiency_pct"] == 91.2
        assert out["waso_hours"] == 0.6
        assert out["toss_and_turns"] == 12

    def test_an_already_mapped_field_is_never_overwritten(self):
        out = brief._normalize_whoop_sleep({"sleep_quality_score": 82, "sleep_score": 90})
        assert out["sleep_score"] == 90

    def test_the_input_record_is_not_mutated(self):
        src = {"sleep_quality_score": 82}
        brief._normalize_whoop_sleep(src)
        assert src == {"sleep_quality_score": 82}

    def test_staging_percentages_are_derived_from_the_hours(self):
        # 1.4 / 7.0 * 100 = 20.0 ; 1.75 / 7.0 * 100 = 25.0
        out = brief._normalize_whoop_sleep(
            {"sleep_duration_hours": 7.0, "slow_wave_sleep_hours": 1.4, "rem_sleep_hours": 1.75, "light_sleep_hours": 3.85}
        )
        assert out["deep_pct"] == 20.0
        assert out["rem_pct"] == 25.0
        assert out["light_pct"] == 55.0

    def test_no_duration_means_no_derived_percentages(self):
        out = brief._normalize_whoop_sleep({"slow_wave_sleep_hours": 1.4})
        assert "deep_pct" not in out

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:498-503 (_normalize_whoop_sleep): the staging derivation reads "
            "`float(out.get(src_field, 0))`, so a Whoop record that carries a duration but NO staging "
            "breakdown (a partial sync, or a nap-only night) gets deep_pct/rem_pct/light_pct = 0.0 — a "
            "fabricated factual zero for an absent measurement. It should leave the field unset. "
            "This is not cosmetic: output_writers.write_clinical_json:882-889 averages deep_pct/rem_pct "
            "over 30 days filtering on `is not None`, so every staging-less night silently drags the "
            "clinical 30-day average deep-sleep % toward zero. Hurts: Matthew, and anyone reading the "
            "clinical JSON. (The email itself is protected only by accident — html_builder.py:811 "
            "tests truthiness, so 0.0 renders as an em dash.)"
        ),
    )
    def test_absent_staging_is_absence_not_zero_percent(self):
        out = brief._normalize_whoop_sleep({"sleep_duration_hours": 7.0})
        assert out.get("deep_pct") is None, f"fabricated deep_pct={out.get('deep_pct')}"
        assert out.get("rem_pct") is None
        assert out.get("light_pct") is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. The readers
# ══════════════════════════════════════════════════════════════════════════════


class TestReaders:
    def test_fetch_date_returns_the_exact_day_as_plain_floats(self, table):
        table.store[(brief.USER_PREFIX + "whoop", "DATE#" + YESTERDAY)] = whoop_row(YESTERDAY, hrv=Decimal("58.5"))
        assert brief.fetch_date("whoop", YESTERDAY)["hrv"] == 58.5

    def test_fetch_date_on_a_missing_day_is_absence(self, table):
        assert brief.fetch_date("whoop", YESTERDAY) is None

    def test_a_failed_point_read_degrades_to_absence_rather_than_aborting(self, table):
        table.get_error = RuntimeError("throttled")
        assert brief.fetch_date("whoop", YESTERDAY) is None

    def test_latest_item_returns_the_newest_record_for_a_periodic_source(self, table):
        for d, wt in (("2026-01-04", 340.0), ("2026-06-02", 330.0)):
            r = day_row("dexa", d, body_fat_pct=Decimal(str(wt)))
            table.store[(r["pk"], r["sk"])] = r
        assert brief._latest_item("dexa")["date"] == "2026-06-02"

    def test_latest_item_asks_newest_first_with_limit_one(self, table):
        brief._latest_item("dexa")
        q = table.queries[0]
        assert q["ScanIndexForward"] is False
        assert q["Limit"] == 1

    def test_a_failed_latest_read_degrades_to_absence(self, table):
        table.query_error = RuntimeError("throttled")
        assert brief._latest_item("dexa") is None

    def test_fetch_range_bounds_the_answer_by_the_date_window(self, table):
        for d in ("2026-07-30", D7, YESTERDAY, TODAY):
            r = whoop_row(d, hrv=Decimal("50"))
            table.store[(r["pk"], r["sk"])] = r
        got = brief.fetch_range("whoop", D7, YESTERDAY)
        assert [g["date"] for g in got] == [D7, YESTERDAY]

    def test_a_failed_range_read_degrades_to_an_empty_window(self, table):
        table.query_error = RuntimeError("throttled")
        assert brief.fetch_range("whoop", D7, YESTERDAY) == []

    @pytest.mark.parametrize("source", ["whoop", "withings", "strava", "apple_health"])
    def test_raw_timeseries_windows_read_cross_phase(self, table, source):
        """#2089 — the body's timeseries does not reset when the experiment does."""
        brief.fetch_range(source, D7, YESTERDAY)
        assert "FilterExpression" not in table.queries[-1]

    def test_an_experiment_scoped_window_keeps_the_current_cycle_filter(self, table):
        """habit_scores is a current-cycle view by contract — the blanket flip
        would have silently widened it."""
        assert tax.classify(brief.USER_PREFIX + "habit_scores") == tax.EXPERIMENT_SCOPED
        brief.fetch_range("habit_scores", D7, YESTERDAY)
        assert PHASE_FILTER_EXPRESSION in table.queries[-1]["FilterExpression"]

    def test_journal_entries_are_read_by_the_day_prefix(self, table):
        for suffix in ("morning", "evening"):
            r = row("notion", f"DATE#{YESTERDAY}#journal#{suffix}", template=suffix)
            table.store[(r["pk"], r["sk"])] = r
        other = row("notion", f"DATE#{D7}#journal#morning", template="morning")
        table.store[(other["pk"], other["sk"])] = other
        assert sorted(e["template"] for e in brief.fetch_journal_entries(YESTERDAY)) == ["evening", "morning"]

    def test_a_failed_journal_read_degrades_to_no_entries(self, table):
        table.query_error = RuntimeError("throttled")
        assert brief.fetch_journal_entries(YESTERDAY) == []

    def test_social_posts_exclude_the_platforms_own_outbound_echoes(self, table, monkeypatch):
        """#1670 membrane: only human-origin posts are a coach signal."""
        monkeypatch.setenv("SOCIAL_CHANNELS", "youtube")
        for post_id, origin in (("a", "human"), ("b", "platform")):
            r = row("youtube", f"DATE#{YESTERDAY}#{post_id}", origin=origin, text=post_id)
            table.store[(r["pk"], r["sk"])] = r
        assert [p["text"] for p in brief.fetch_social_posts(D7, YESTERDAY)] == ["a"]

    def test_social_posts_read_every_configured_channel(self, table, monkeypatch):
        monkeypatch.setenv("SOCIAL_CHANNELS", "youtube,bluesky")
        brief.fetch_social_posts(D7, YESTERDAY)
        pks = {q["ExpressionAttributeValues"][":pk"] for q in table.queries}
        assert pks == {brief.USER_PREFIX + "youtube", brief.USER_PREFIX + "bluesky"}

    def test_a_failed_channel_read_never_takes_the_other_channels_down(self, table, monkeypatch):
        monkeypatch.setenv("SOCIAL_CHANNELS", "youtube")
        table.query_error = RuntimeError("channel unprovisioned")
        assert brief.fetch_social_posts(D7, YESTERDAY) == []

    def test_an_absent_anomaly_record_is_an_empty_dict_not_none(self, table):
        assert brief.fetch_anomaly_record(YESTERDAY) == {}


class TestFetchHevyWorkouts:
    def _seed(self, table, workouts):
        for i, w in enumerate(workouts):
            r = row("hevy", f"DATE#{YESTERDAY}#WORKOUT#{i}", **w)
            table.store[(r["pk"], r["sk"])] = r

    def test_a_day_with_no_hevy_records_is_absence(self, table):
        assert brief.fetch_hevy_workouts(YESTERDAY) is None

    def test_several_sessions_a_day_fold_into_one_day_aggregate(self, table):
        self._seed(
            table,
            [
                {"title": "Push", "exercises": [{"name": "Bench", "sets": [{"weight_kg": Decimal("100"), "reps": 5}]}]},
                {"title": "Pull", "exercises": [{"name": "Row", "sets": [{"weight_kg": Decimal("60"), "reps": 10}]}]},
            ],
        )
        agg = brief.fetch_hevy_workouts(YESTERDAY)
        assert [w["workout_name"] for w in agg["workouts"]] == ["Push", "Pull"]
        assert agg["total_sets"] == 2
        # 100 kg / 0.45359237 = 220.5 lb (rounded to 1dp) × 5 reps = 1102.5
        #  60 kg / 0.45359237 = 132.3 lb                    × 10 reps = 1323.0
        # total = 2425.5
        assert agg["total_volume_lbs"] == 2425.5

    def test_a_set_without_a_weight_still_counts_as_a_set(self, table):
        """Bodyweight work is training; it just has no volume."""
        self._seed(table, [{"title": "Core", "exercises": [{"name": "Plank", "sets": [{"reps": 1}]}]}])
        agg = brief.fetch_hevy_workouts(YESTERDAY)
        assert agg["total_sets"] == 1
        assert agg["total_volume_lbs"] == 0.0
        assert agg["workouts"][0]["exercises"][0]["sets"][0]["weight_lbs"] is None

    def test_rpe_is_not_relabelled_as_rir(self, table):
        """Different scales — the mapper leaves rir unset rather than mislabel."""
        self._seed(table, [{"title": "Push", "exercises": [{"name": "Bench", "sets": [{"weight_kg": 100, "reps": 5, "rpe": 8}]}]}])
        s = brief.fetch_hevy_workouts(YESTERDAY)["workouts"][0]["exercises"][0]["sets"][0]
        assert "rir" not in s

    def test_an_unnamed_session_gets_a_neutral_label_not_a_crash(self, table):
        self._seed(table, [{"exercises": [{"sets": [{"reps": 3}]}]}])
        agg = brief.fetch_hevy_workouts(YESTERDAY)
        assert agg["workouts"][0]["workout_name"] == "Strength Session"
        assert agg["workouts"][0]["exercises"][0]["exercise_name"] == "?"

    def test_a_failed_hevy_read_is_absence_not_a_zero_volume_day(self, table):
        table.query_error = RuntimeError("throttled")
        assert brief.fetch_hevy_workouts(YESTERDAY) is None


# ══════════════════════════════════════════════════════════════════════════════
# 4. Journal signal extraction
# ══════════════════════════════════════════════════════════════════════════════


class TestExtractJournalSignals:
    def test_no_entries_is_absence(self):
        assert brief.extract_journal_signals([]) is None
        assert brief.extract_journal_signals(None) is None

    def test_enriched_scores_average_across_the_days_entries(self):
        out = brief.extract_journal_signals(
            [
                {"template": "morning", "enriched_mood": 6, "enriched_energy": 5, "enriched_stress": 4},
                {"template": "evening", "enriched_mood": 8, "enriched_energy": 7, "enriched_stress": 2},
            ]
        )
        assert out["mood_avg"] == 7.0  # (6 + 8) / 2
        assert out["energy_avg"] == 6.0  # (5 + 7) / 2
        assert out["stress_avg"] == 3.0  # (4 + 2) / 2

    def test_an_unenriched_entry_falls_back_to_the_raw_self_report(self):
        out = brief.extract_journal_signals([{"template": "morning", "morning_mood": 5, "morning_energy": 3, "stress_level": 7}])
        assert (out["mood_avg"], out["energy_avg"], out["stress_avg"]) == (5.0, 3.0, 7.0)

    def test_entries_with_no_scores_leave_the_averages_absent(self):
        """ADR-104: a journal day with prose but no ratings is not a mood of 0."""
        out = brief.extract_journal_signals([{"template": "morning", "text": "long day"}])
        assert out["mood_avg"] is None and out["energy_avg"] is None and out["stress_avg"] is None

    def test_the_evening_quote_wins_over_an_earlier_one(self):
        out = brief.extract_journal_signals(
            [
                {"template": "morning", "enriched_notable_quote": "morning line"},
                {"template": "evening", "enriched_notable_quote": "evening line"},
            ]
        )
        assert out["notable_quote"] == "evening line"

    def test_themes_and_emotions_are_deduped_and_capped(self):
        out = brief.extract_journal_signals(
            [
                {"template": "morning", "enriched_themes": ["a", "b", "a"], "enriched_emotions": ["x", "x"]},
                {"template": "evening", "enriched_themes": ["c", "d", "e", "f"], "enriched_emotions": ["y"]},
            ]
        )
        assert out["themes"] == ["a", "b", "c", "d"]  # dedup, first four
        assert out["emotions"] == ["x", "y"]

    def test_the_primary_defense_leads_the_defense_list(self):
        out = brief.extract_journal_signals(
            [{"template": "evening", "enriched_defense_patterns": ["intellectualising"], "enriched_primary_defense": "avoidance"}]
        )
        assert out["defense_patterns"][0] == "avoidance"

    def test_social_quality_is_the_most_recent_reading(self):
        out = brief.extract_journal_signals(
            [
                {"template": "morning", "enriched_social_quality": "isolated"},
                {"template": "evening", "enriched_social_quality": "connected"},
            ]
        )
        assert out["social_quality"] == "connected"

    def test_ownership_averages_across_entries(self):
        out = brief.extract_journal_signals(
            [{"template": "morning", "enriched_ownership": 4}, {"template": "evening", "enriched_ownership": 7}]
        )
        assert out["ownership_avg"] == 5.5  # (4 + 7) / 2


# ══════════════════════════════════════════════════════════════════════════════
# 5. Habit streaks
# ══════════════════════════════════════════════════════════════════════════════

STREAK_PROFILE = {
    "habit_registry": {
        "sleep_7h": {"status": "active", "tier": 0},
        "protein": {"status": "active", "tier": 0},
        "walk": {"status": "active", "tier": 1},
        "gym": {"status": "active", "tier": 1, "applicable_days": "weekdays"},
        "no_weed": {"status": "active", "tier": 0, "vice": True},
        "retired": {"status": "retired", "tier": 0},
    },
    "mvp_habits": [],
}


def _seed_habit_days(table, per_day):
    """per_day: {date_str: {habit: done}} — seeds habitify rows for each date."""
    for d, habits in per_day.items():
        r = habitify_row(d, habits)
        table.store[(r["pk"], r["sk"])] = r


def _back(n):
    """The nth day back from the subject date (0 == YESTERDAY)."""
    return (date(2026, 8, 6) - timedelta(days=n)).isoformat()


class TestHabitStreaks:
    def test_a_retired_habit_never_holds_a_streak_hostage(self, table):
        _seed_habit_days(table, {_back(i): {"sleep_7h": 1, "protein": 1, "walk": 1, "gym": 1, "no_weed": 1} for i in range(3)})
        out = brief.compute_habit_streaks(STREAK_PROFILE, YESTERDAY)
        assert out["tier0_streak"] == 3

    def test_a_tier0_miss_ends_the_tier0_streak_on_that_day(self, table):
        # yesterday + 1 day back clean, 2 days back missed protein → streak 2.
        _seed_habit_days(
            table,
            {
                _back(0): {"sleep_7h": 1, "protein": 1, "walk": 1, "gym": 1, "no_weed": 1},
                _back(1): {"sleep_7h": 1, "protein": 1, "walk": 1, "gym": 1, "no_weed": 1},
                _back(2): {"sleep_7h": 1, "protein": 0, "walk": 1, "gym": 1, "no_weed": 1},
            },
        )
        assert brief.compute_habit_streaks(STREAK_PROFILE, YESTERDAY)["tier0_streak"] == 2

    def test_a_weekday_only_habit_is_not_required_at_the_weekend(self, table):
        # 2026-08-06 Thu, 08-05 Wed, 08-04 Tue, 08-03 Mon, 08-02 Sun, 08-01 Sat.
        days = {}
        for i in range(6):
            d = _back(i)
            habits = {"sleep_7h": 1, "protein": 1, "walk": 1, "no_weed": 1}
            if datetime.strptime(d, "%Y-%m-%d").weekday() < 5:
                habits["gym"] = 1
            days[d] = habits
        _seed_habit_days(table, days)
        assert brief.compute_habit_streaks(STREAK_PROFILE, YESTERDAY)["tier01_streak"] == 6

    def test_a_vice_held_every_day_accrues_its_own_streak(self, table):
        _seed_habit_days(table, {_back(i): {"no_weed": 1} for i in range(4)})
        assert brief.compute_habit_streaks(STREAK_PROFILE, YESTERDAY)["vice_streaks"]["no_weed"] == 4

    def test_a_broken_vice_stops_that_vice_only(self, table):
        _seed_habit_days(table, {_back(0): {"no_weed": 1}, _back(1): {"no_weed": 0}, _back(2): {"no_weed": 1}})
        assert brief.compute_habit_streaks(STREAK_PROFILE, YESTERDAY)["vice_streaks"]["no_weed"] == 1

    def test_an_empty_registry_falls_back_to_the_declared_mvp_habits(self, table):
        _seed_habit_days(table, {_back(i): {"mvp_a": 1} for i in range(2)})
        out = brief.compute_habit_streaks({"habit_registry": {}, "mvp_habits": ["mvp_a"]}, YESTERDAY)
        assert out["tier0_streak"] == 2

    def test_the_scan_never_runs_past_its_ninety_day_horizon(self, table):
        _seed_habit_days(table, {(date(2026, 8, 6) - timedelta(days=i)).isoformat(): {"no_weed": 1} for i in range(200)})
        out = brief.compute_habit_streaks(STREAK_PROFILE, YESTERDAY)
        assert out["vice_streaks"]["no_weed"] == 90

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:1210-1211 (compute_habit_streaks): `if not rec: break` treats a day "
            "with NO habitify record as the end of history and stops the scan. A single ingestion gap "
            "(Habitify API blip, a travel day, a phone left off) therefore silently truncates every "
            "streak the reader is shown — a 40-day vice streak renders as 2 — and the number is "
            "presented as a fact, with no marker that the scan hit a data gap rather than a miss. "
            "It should distinguish 'no data' from 'not done' (carry the streak across an absent day, or "
            "surface the gap). Hurts: Matthew, on the single most motivating number in the email."
        ),
    )
    def test_a_missing_habitify_day_does_not_silently_truncate_a_long_streak(self, table):
        # 40 clean days, one ingestion gap 3 days back, clean before and after.
        days = {_back(i): {"no_weed": 1} for i in range(40) if i != 3}
        _seed_habit_days(table, days)
        out = brief.compute_habit_streaks(STREAK_PROFILE, YESTERDAY)
        assert out["vice_streaks"]["no_weed"] > 3, f"streak truncated at the gap: {out['vice_streaks']['no_weed']}"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:1222/1240/1251 (compute_habit_streaks): `habits_map.get(h, 0)` maps an "
            "ABSENT habit key to 0 — 'not done'. A habit added to the profile registry today, or one "
            "Habitify simply did not return for a day, therefore reads as a miss and zeroes the tier "
            "streak. Absence of a reading is not evidence of a miss (ADR-104). Hurts: Matthew — adding a "
            "new tier-0 habit retroactively destroys the existing streak."
        ),
    )
    def test_a_habit_absent_from_the_days_record_is_not_counted_as_a_miss(self, table):
        _seed_habit_days(table, {_back(i): {"sleep_7h": 1, "no_weed": 1} for i in range(3)})  # 'protein' never reported
        assert brief.compute_habit_streaks(STREAK_PROFILE, YESTERDAY)["tier0_streak"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# 6. Readiness
# ══════════════════════════════════════════════════════════════════════════════


def _readiness_data(**over):
    base = {"primary_whoop": None, "whoop": None, "whoop_today": None, "sleep": None, "hrv": {}, "tsb": None}
    base.update(over)
    return base


class TestComputeReadiness:
    def test_no_signal_at_all_is_absence_not_a_neutral_fifty(self):
        score, colour = brief.compute_readiness(_readiness_data())
        assert score is None and colour == "gray"

    def test_a_single_present_component_carries_the_whole_score(self):
        """Weights are renormalised over the components that exist."""
        score, colour = brief.compute_readiness(_readiness_data(primary_whoop={"recovery_score": 88}))
        assert score == 88 and colour == "green"

    def test_the_bands_are_eighty_and_sixty(self):
        assert brief.compute_readiness(_readiness_data(primary_whoop={"recovery_score": 80}))[1] == "green"
        assert brief.compute_readiness(_readiness_data(primary_whoop={"recovery_score": 60}))[1] == "yellow"
        assert brief.compute_readiness(_readiness_data(primary_whoop={"recovery_score": 59}))[1] == "red"

    def test_recovery_and_sleep_combine_on_their_renormalised_weights(self):
        # recovery 90 × 0.40 + sleep 70 × 0.25 = 36 + 17.5 = 53.5 ; / 0.65 = 82.3 → 82
        score, colour = brief.compute_readiness(_readiness_data(primary_whoop={"recovery_score": 90}, sleep={"sleep_score": 70}))
        assert score == 82 and colour == "green"

    def test_the_hrv_trend_component_is_the_seven_over_thirty_day_ratio(self):
        # ratio 1.0 → clamp(round((1.0 - 0.75) × 200)) = 50 ; only component → 50
        score, _ = brief.compute_readiness(_readiness_data(hrv={"hrv_7d": 60.0, "hrv_30d": 60.0}))
        assert score == 50

    def test_a_thirty_day_hrv_of_zero_never_divides(self):
        score, colour = brief.compute_readiness(_readiness_data(hrv={"hrv_7d": 60.0, "hrv_30d": 0.0}))
        assert score is None and colour == "gray"

    def test_the_chosen_whoop_is_preferred_over_the_raw_yesterday_record(self):
        """Phase-3: one chosen record, so the headline and the prose agree."""
        score, _ = brief.compute_readiness(_readiness_data(primary_whoop={"recovery_score": 30}, whoop={"recovery_score": 86}))
        assert score == 30

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:1290-1292 (compute_readiness) reads `data['tsb']`, which "
            "gather_daily_data:631 always populates from training_load.compute_ctl_atl_tsb — and that "
            "returns 0.0, never None, for an EMPTY 60-day Strava window. So a period with no training "
            "data at all contributes a readiness component of clamp(60 + 0×2) = 60, a fabricated "
            "mid-scale 'neutral form' from no measurement (ADR-104). On a day when recovery and sleep "
            "are also absent, readiness is reported as 60/yellow on the strength of nothing. It should "
            "distinguish 'no training data' from 'balanced form'. Hurts: Matthew, and the public "
            "site — the same value ships as `tsb_form` in public_stats.json."
        ),
    )
    def test_an_empty_training_window_does_not_manufacture_a_neutral_form_component(self):
        empty_tsb = brief.compute_tsb([], date(2026, 8, 7))
        assert empty_tsb is None, f"an empty Strava window produced tsb={empty_tsb} rather than absence"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Multi-device activity de-duplication
# ══════════════════════════════════════════════════════════════════════════════


def act(sport, start, **fields):
    return {"sport_type": sport, "start_date_local": start, **fields}


class TestDedupActivities:
    def test_a_single_activity_is_returned_untouched(self):
        one = [act("Run", "2026-08-06T07:00:00")]
        assert brief.dedup_activities(one) == one

    def test_two_devices_recording_one_run_collapse_to_the_richer_record(self):
        kept = act("Run", "2026-08-06T07:00:00", distance_meters=8000, moving_time_seconds=2700, device_name="Garmin")
        dropped = act("Run", "2026-08-06T07:05:00", moving_time_seconds=2650, device_name="Watch")
        out = brief.dedup_activities([kept, dropped])
        assert [a["device_name"] for a in out] == ["Garmin"]

    def test_the_same_sport_more_than_fifteen_minutes_apart_is_two_sessions(self):
        out = brief.dedup_activities(
            [
                act("Run", "2026-08-06T07:00:00", moving_time_seconds=1800),
                act("Run", "2026-08-06T18:00:00", moving_time_seconds=1800),
            ]
        )
        assert len(out) == 2

    def test_different_sports_at_the_same_moment_are_never_merged(self):
        out = brief.dedup_activities(
            [act("Run", "2026-08-06T07:00:00", moving_time_seconds=1800), act("Ride", "2026-08-06T07:02:00", moving_time_seconds=1800)]
        )
        assert len(out) == 2

    def test_an_activity_with_an_unparseable_start_is_kept_rather_than_dropped(self):
        out = brief.dedup_activities([act("Run", "not-a-timestamp"), act("Run", "2026-08-06T07:00:00")])
        assert len(out) == 2

    def test_the_legacy_type_field_is_honoured_when_sport_type_is_absent(self):
        a = {"type": "Run", "start_date_local": "2026-08-06T07:00:00", "moving_time_seconds": 2700, "distance_meters": 8000}
        b = {"type": "Run", "start_date_local": "2026-08-06T07:03:00", "moving_time_seconds": 2600}
        assert len(brief.dedup_activities([a, b])) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 8. The two persistence paths
# ══════════════════════════════════════════════════════════════════════════════


class TestStoreDayGrade:
    def test_the_stored_row_carries_the_grade_the_reader_saw(self, table):
        brief.store_day_grade(YESTERDAY, 84, "B", {"sleep_quality": 90, "nutrition": None}, {"sleep_quality": 0.2}, "1.1")
        item = table.puts[0]
        assert item["sk"] == "DATE#" + YESTERDAY
        assert item["total_score"] == Decimal("84")
        assert item["letter_grade"] == "B"
        assert item["algorithm_version"] == "1.1"

    def test_component_scores_are_stored_as_decimals_never_floats(self, table):
        """boto3 rejects a Python float on a DDB write."""
        brief.store_day_grade(YESTERDAY, 84.0, "B", {"sleep_quality": 90.5}, {}, "1.1")
        assert isinstance(table.puts[0]["component_sleep_quality"], Decimal)
        assert isinstance(table.puts[0]["total_score"], Decimal)

    def test_an_absent_component_is_omitted_rather_than_stored_as_zero(self, table):
        brief.store_day_grade(YESTERDAY, 84, "B", {"nutrition": None}, {}, "1.1")
        assert "component_nutrition" not in table.puts[0]

    def test_every_component_scorer_in_the_registry_can_round_trip(self, table):
        """Derived from health.scoring_engine.COMPONENT_SCORERS — a new scorer
        inherits the guard instead of needing a literal added here."""
        scores = {name: 70 for name in brief.COMPONENT_SCORERS}
        brief.store_day_grade(YESTERDAY, 70, "C", scores, {}, "1.1")
        stored = table.puts[0]
        assert {f"component_{n}" for n in brief.COMPONENT_SCORERS} <= set(stored)

    def test_the_row_is_phase_stamped(self, table):
        """ADR-058 #1814 — an unstamped row passes the default-deny read filter."""
        brief.store_day_grade(YESTERDAY, 84, "B", {}, {}, "1.1")
        assert "phase" in table.puts[0]

    def test_a_failed_grade_write_is_raised_not_swallowed(self, table):
        """Day-grade loss cascades into the character sheet and the insights."""
        table.put_error = RuntimeError("ProvisionedThroughputExceeded")
        with pytest.raises(RuntimeError):
            brief.store_day_grade(YESTERDAY, 84, "B", {}, {}, "1.1")


HABIT_DETAILS = {
    "habits_mvp": {
        "composite_method": "tier_weighted",
        "tier0": {"done": 3, "total": 4},
        "tier1": {"done": 1, "total": 2},
        "vices": {"held": 2, "total": 2},
        "tier_status": {0: {"sleep_7h": True, "protein": False}, 1: {"walk": True}},
    }
}


class TestStoreHabitScores:
    def test_the_tier_percentages_are_the_done_over_total_ratios(self, table):
        brief.store_habit_scores(YESTERDAY, HABIT_DETAILS, {"habits_mvp": 72}, {}, {"habit_registry": {}})
        item = table.puts[0]
        assert item["tier0_pct"] == Decimal("0.75")  # 3 / 4
        assert item["tier1_pct"] == Decimal("0.5")  # 1 / 2

    def test_the_missed_tier0_habits_are_named(self, table):
        brief.store_habit_scores(YESTERDAY, HABIT_DETAILS, {"habits_mvp": 72}, {}, {"habit_registry": {}})
        assert table.puts[0]["missed_tier0"] == ["protein"]

    def test_synergy_groups_are_counted_over_active_registry_habits_only(self, table):
        profile = {
            "habit_registry": {
                "sleep_7h": {"status": "active", "synergy_group": "recovery"},
                "protein": {"status": "active", "synergy_group": "recovery"},
                "old": {"status": "retired", "synergy_group": "recovery"},
            }
        }
        brief.store_habit_scores(YESTERDAY, HABIT_DETAILS, {"habits_mvp": 72}, {}, profile)
        # sleep_7h done, protein missed → 1 of 2 active members = 0.5
        assert table.puts[0]["synergy_groups"]["recovery"] == Decimal("0.5")

    def test_a_non_tier_weighted_day_writes_nothing(self, table):
        brief.store_habit_scores(YESTERDAY, {"habits_mvp": {"composite_method": "flat"}}, {}, {}, {"habit_registry": {}})
        assert table.puts == []

    def test_a_zero_total_tier_leaves_the_percentage_absent_rather_than_dividing(self, table):
        details = {"habits_mvp": {"composite_method": "tier_weighted", "tier0": {"done": 0, "total": 0}, "tier_status": {}}}
        brief.store_habit_scores(YESTERDAY, details, {"habits_mvp": 0}, {}, {"habit_registry": {}})
        assert "tier0_pct" not in table.puts[0]

    def test_a_failed_habit_write_is_raised_not_swallowed(self, table):
        table.put_error = RuntimeError("throttled")
        with pytest.raises(RuntimeError):
            brief.store_habit_scores(YESTERDAY, HABIT_DETAILS, {"habits_mvp": 72}, {}, {"habit_registry": {}})


# ══════════════════════════════════════════════════════════════════════════════
# 9. The food-delivery streak signal
# ══════════════════════════════════════════════════════════════════════════════


class TestFoodDeliverySignal:
    def _streak(self, table, **fields):
        table.store[(f"USER#{brief.USER_ID}#SOURCE#food_delivery", "STREAK#current")] = fields

    def test_no_streak_record_is_no_signal(self, table):
        assert brief.get_food_delivery_brief_signal() is None

    def test_a_zero_day_streak_produces_no_line(self, table):
        self._streak(table, streak_days=0)
        assert brief.get_food_delivery_brief_signal() is None

    @pytest.mark.parametrize(
        "days,expected_multiplier",
        [(7, "1.02x"), (14, "1.05x"), (30, "1.10x")],
    )
    def test_each_bonus_band_names_its_own_multiplier(self, table, days, expected_multiplier):
        self._streak(table, streak_days=days)
        assert expected_multiplier in brief.get_food_delivery_brief_signal()

    def test_a_short_streak_is_reported_without_claiming_a_bonus(self, table):
        self._streak(table, streak_days=3)
        line = brief.get_food_delivery_brief_signal()
        assert "3 days" in line and "bonus" not in line

    def test_an_order_placed_today_overrides_the_streak_line(self, table):
        self._streak(table, streak_days=40, last_order_date=TODAY)
        assert "ordered today" in brief.get_food_delivery_brief_signal()

    def test_a_failed_read_is_non_fatal(self, table):
        table.get_error = RuntimeError("throttled")
        assert brief.get_food_delivery_brief_signal() is None


# ══════════════════════════════════════════════════════════════════════════════
# 10. The send-completion record
# ══════════════════════════════════════════════════════════════════════════════


class TestRecordEmailSend:
    def test_a_completion_row_is_written_for_the_status_page(self):
        t = FakeTable()
        brief.record_email_send(t, "daily_brief")
        item = t.puts[0]
        assert item["pk"].endswith("#email_log#daily_brief")
        assert item["sk"] == "DATE#" + TODAY
        assert item["status"] == "success"

    def test_the_row_expires_so_the_log_cannot_grow_without_bound(self):
        t = FakeTable()
        brief.record_email_send(t, "daily_brief")
        assert t.puts[0]["ttl"] > 0

    def test_a_failed_status_write_never_re_raises_after_the_mail_has_gone(self):
        t = FakeTable()
        t.put_error = RuntimeError("throttled")
        brief.record_email_send(t, "daily_brief")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# 11. gather_daily_data — the windows, the crashes and the divergences
# ══════════════════════════════════════════════════════════════════════════════


class TestGatherDailyData:
    def test_the_hrv_windows_are_seven_and_thirty_days_ending_yesterday(self, table):
        brief.gather_daily_data(PROFILE, YESTERDAY)
        whoop_windows = {
            (q["ExpressionAttributeValues"][":s"], q["ExpressionAttributeValues"][":e"])
            for q in table.queries
            if q.get("ExpressionAttributeValues", {}).get(":pk") == brief.USER_PREFIX + "whoop"
        }
        assert ("DATE#" + D7, "DATE#" + YESTERDAY) in whoop_windows
        assert ("DATE#" + D30, "DATE#" + YESTERDAY) in whoop_windows

    def test_the_banister_window_is_sixty_days_of_strava(self, table):
        brief.gather_daily_data(PROFILE, YESTERDAY)
        strava_windows = {
            q["ExpressionAttributeValues"][":s"]
            for q in table.queries
            if q.get("ExpressionAttributeValues", {}).get(":pk") == brief.USER_PREFIX + "strava"
        }
        assert "DATE#" + D60 in strava_windows

    def test_the_seven_day_hrv_average_is_the_mean_of_the_window(self, table):
        for i, hrv in enumerate([50.0, 60.0, 70.0]):
            r = whoop_row((date(2026, 8, 6) - timedelta(days=i)).isoformat(), hrv=Decimal(str(hrv)))
            table.store[(r["pk"], r["sk"])] = r
        data = brief.gather_daily_data(PROFILE, YESTERDAY)
        assert data["hrv"]["hrv_7d"] == 60.0  # (50 + 60 + 70) / 3

    def test_the_seven_day_hrv_average_is_absent_with_no_readings(self, table):
        data = brief.gather_daily_data(PROFILE, YESTERDAY)
        assert data["hrv"]["hrv_7d"] is None and data["hrv"]["hrv_30d"] is None

    def test_the_latest_weight_is_the_newest_reading_in_the_thirty_day_window(self, table):
        for d, wt in ((D30, 330.0), ("2026-08-02", 318.4), (YESTERDAY, 317.0)):
            r = withings_row(d, wt)
            table.store[(r["pk"], r["sk"])] = r
        assert brief.gather_daily_data(PROFILE, YESTERDAY)["latest_weight"] == 317.0

    def test_a_stale_scale_still_yields_a_weight_from_the_ninety_day_fallback(self, table):
        r = withings_row("2026-05-20", 335.0)  # older than 30d, inside 90d
        table.store[(r["pk"], r["sk"])] = r
        assert brief.gather_daily_data(PROFILE, YESTERDAY)["latest_weight"] == 335.0

    def test_no_weigh_in_anywhere_is_absence_not_zero_pounds(self, table):
        data = brief.gather_daily_data(PROFILE, YESTERDAY)
        assert data["latest_weight"] is None and data["avatar_weight"] is None

    def test_the_seven_day_sleep_debt_only_counts_shortfall(self, table):
        # target 7.5; 6.0 → 1.5 debt, 8.0 → 0 (never negative). Total 1.5.
        for d, hrs in ((YESTERDAY, 6.0), ("2026-08-05", 8.0)):
            r = whoop_row(d, sleep_duration_hours=Decimal(str(hrs)))
            table.store[(r["pk"], r["sk"])] = r
        assert brief.gather_daily_data(PROFILE, YESTERDAY)["sleep_debt_7d_hrs"] == 1.5

    def test_an_active_trip_is_matched_on_its_own_dates_not_its_booking_date(self, table):
        """#2109 — TRIP# rows carry no date in the sort key."""
        trip = row("travel", "TRIP#paris", start_date="2026-08-04", end_date="2026-08-10", destination_city="Paris", phase="pilot")
        table.store[(trip["pk"], trip["sk"])] = trip
        assert brief.gather_daily_data(PROFILE, YESTERDAY)["travel_active"]["destination"] == "Paris"

    def test_a_finished_trip_is_not_reported_as_active(self, table):
        trip = row("travel", "TRIP#old", start_date="2026-06-01", end_date="2026-06-10", destination_city="Rome")
        table.store[(trip["pk"], trip["sk"])] = trip
        assert brief.gather_daily_data(PROFILE, YESTERDAY)["travel_active"] is None

    def test_blood_pressure_is_classified_on_the_aha_bands(self, table):
        r = day_row(
            "apple_health",
            YESTERDAY,
            blood_pressure_systolic=Decimal("135"),
            blood_pressure_diastolic=Decimal("85"),
        )
        table.store[(r["pk"], r["sk"])] = r
        bp = brief.gather_daily_data(PROFILE, YESTERDAY)["bp_data"]
        assert bp["class"] == "Stage 1"

    def test_a_half_recorded_blood_pressure_reading_is_absence(self, table):
        r = day_row("apple_health", YESTERDAY, blood_pressure_systolic=Decimal("135"))
        table.store[(r["pk"], r["sk"])] = r
        assert brief.gather_daily_data(PROFILE, YESTERDAY)["bp_data"] is None

    def test_todays_whoop_is_chosen_only_once_recovery_is_finalized(self, table):
        y = whoop_row(YESTERDAY, recovery_score=Decimal("30"))
        t = whoop_row(TODAY, hrv=Decimal("55"))  # synced, but no recovery yet
        for r in (y, t):
            table.store[(r["pk"], r["sk"])] = r
        assert brief.gather_daily_data(PROFILE, YESTERDAY)["primary_whoop"]["recovery_score"] == 30.0

    def test_a_finalized_today_recovery_wins_over_yesterdays(self, table):
        y = whoop_row(YESTERDAY, recovery_score=Decimal("30"))
        t = whoop_row(TODAY, recovery_score=Decimal("86"))
        for r in (y, t):
            table.store[(r["pk"], r["sk"])] = r
        assert brief.gather_daily_data(PROFILE, YESTERDAY)["primary_whoop"]["recovery_score"] == 86.0

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:627-628 (gather_daily_data): "
            "`[float(r['hrv']) for r in hrv_7d_recs if 'hrv' in r]` tests for KEY PRESENCE, not for a "
            "value. A DynamoDB row that carries an explicit NULL `hrv` (boto3 returns it as None — a "
            "shape whoop_lambda can write on a partial sync) makes float(None) raise TypeError inside "
            "gather_daily_data, which lambda_handler does NOT wrap: the exception escapes and the "
            "ENTIRE brief is lost for that day. It should filter on the value the way safe_float does. "
            "Hurts: Matthew — one malformed cell costs the whole morning email. Severity P1 (crash)."
        ),
    )
    def test_one_null_hrv_cell_does_not_cost_the_whole_brief(self, table):
        good = whoop_row(YESTERDAY, hrv=Decimal("58"))
        bad = whoop_row("2026-08-05", hrv=None)
        for r in (good, bad):
            table.store[(r["pk"], r["sk"])] = r
        data = brief.gather_daily_data(PROFILE, YESTERDAY)
        assert data["hrv"]["hrv_7d"] == 58.0

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:666-671 (gather_daily_data) picks week_ago_weight with a LAST-WINS "
            "loop over an ascending 14-day window — the NEWEST weigh-in at or before day-7. "
            "daily_metrics_compute_lambda.py:1030-1037 implements the same concept as `next(...)` over "
            "the same ascending window — the OLDEST, i.e. a reading up to 14 days old. One concept, two "
            "answers, and lambda_handler:1864-1865 lets the compute value overwrite the brief's whenever "
            "computed_metrics exists — so the weekly weight delta the reader sees flips depending on "
            "whether a pipeline ran, and the figure published as `weight_delta_7d` (#1917 renamed it for "
            "honesty) can span up to 14 days on the compute path. One definition, one place. "
            "Hurts: Matthew and every reader of public_stats.json / the weekly-signal email."
        ),
    )
    def test_week_ago_weight_agrees_with_the_compute_lambdas_definition(self, table):
        # Two weigh-ins at or before the day-7 target (2026-07-31): 07-26 and 07-30.
        for d, wt in (("2026-07-26", 325.0), ("2026-07-30", 320.0), (YESTERDAY, 317.0)):
            r = withings_row(d, wt)
            table.store[(r["pk"], r["sk"])] = r
        brief_value = brief.gather_daily_data(PROFILE, YESTERDAY)["week_ago_weight"]
        withings_14d = brief.fetch_range("withings", D14, YESTERDAY)
        compute_value = next(
            (float(w["weight_lbs"]) for w in withings_14d if w.get("sk", "").replace("DATE#", "") <= D7 and w.get("weight_lbs")),
            None,
        )
        assert brief_value == compute_value, f"brief says {brief_value}, daily-metrics-compute says {compute_value}"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2482-2487 (lambda_handler) builds the /live/ nutrition narrative from "
            "`data.get('cgm') or data.get('cgm_today')`, but gather_daily_data's returned dict "
            "(daily_brief_lambda.py:832-872) contains NEITHER key — no CGM read happens anywhere in this "
            "module. The reader/writer mismatch class: the CGM time-in-range narrative on the cockpit "
            "has therefore never rendered, silently, since it was added. It should read the cgm "
            "partition (or the apple_health CGM aggregate) and populate the key. "
            "Hurts: every reader of averagejoematt.com's cockpit — a whole pillar narrative is dark."
        ),
    )
    def test_the_gathered_data_carries_the_cgm_key_the_cockpit_narrative_reads(self, table):
        data = brief.gather_daily_data(PROFILE, YESTERDAY)
        assert "cgm" in data or "cgm_today" in data


# ══════════════════════════════════════════════════════════════════════════════
# 12. The "Data Status" staleness banner vs. the canonical source registry
# ══════════════════════════════════════════════════════════════════════════════


class TestStalenessScanAgainstTheRegistry:
    def test_a_source_within_its_threshold_is_not_reported(self, table):
        r = whoop_row(YESTERDAY, hrv=Decimal("55"))  # 1 day old, threshold 2 days
        table.store[(r["pk"], r["sk"])] = r
        reported = {s["source"] for s in brief.scan_stale_sources(date(2026, 8, 7))}
        assert "whoop" not in reported
        # The scan is not vacuously empty — the sources with no rows at all are reported.
        assert reported == set(brief.STALENESS_SOURCES) - {"whoop"}

    def test_a_genuinely_dead_pipe_is_reported_with_its_true_age(self, table):
        r = whoop_row("2026-07-20", hrv=Decimal("55"))
        table.store[(r["pk"], r["sk"])] = r
        hit = next(s for s in brief.scan_stale_sources(date(2026, 8, 7)) if s["source"] == "whoop")
        assert hit["age_days"] == 18  # 2026-08-07 - 2026-07-20

    def test_every_source_the_scan_watches_is_a_never_hidden_class(self):
        """#2080 — derived from the module's own list, so a new source inherits
        the check instead of needing a literal added here."""
        never_hidden = {tax.RAW_TIMESERIES, tax.CROSS_PHASE}
        for src in brief.STALENESS_SOURCES:
            assert tax.classify(brief.USER_PREFIX + src) in never_hidden, src

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:356-371: STALENESS_SOURCES / "
            "STALENESS_DEFAULT_THRESHOLD_DAYS / STALENESS_THRESHOLD_OVERRIDE_DAYS are a hand-maintained "
            "second opinion on freshness, while scan_stale_sources' own docstring (line 385 region) "
            "claims it 'Reads the SAME freshness logic the freshness-checker Lambda + "
            "get_freshness_status MCP tool use'. It does not: freshness_checker_lambda.py:45-48 derives "
            "its set and its thresholds from ingestion/source_registry.py "
            "(`checker_sources()` + `stale_hours_overrides()`), the canonical home per #2003. The two "
            "disagree on most of the list — withings (registry 168h, brief 48h), todoist (72h vs 48h), "
            "macrofactor (96h vs 48h — the registry says it is '~24h behind by design'), notion (336h vs "
            "48h) and food_delivery (336h vs 2160h) — so the banner cries wolf on four sources that are "
            "behaving normally and under-reports the one that is not. It should derive from the "
            "registry. Hurts: Matthew — a banner that fires every morning is a banner he stops reading, "
            "and it explicitly tells him his day grade may be wrong."
        ),
    )
    def test_the_scans_thresholds_agree_with_the_canonical_source_registry(self):
        overrides = registry.stale_hours_overrides(brief.STALENESS_SOURCES)
        mismatched = {}
        for src in brief.STALENESS_SOURCES:
            brief_hours = brief.STALENESS_THRESHOLD_OVERRIDE_DAYS.get(src, brief.STALENESS_DEFAULT_THRESHOLD_DAYS) * 24
            canonical = overrides.get(src, registry.DEFAULT_STALE_HOURS)
            if brief_hours != canonical:
                mismatched[src] = (brief_hours, canonical)
        assert not mismatched, f"brief-vs-registry threshold drift: {mismatched}"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:356-369: STALENESS_SOURCES still lists `garmin`, which "
            "source_registry marks `paused: True` (ADR-074 — no EventBridge rule, deliberately not "
            "ingesting). The canonical freshness path excludes paused sources from "
            "`checker_sources()` precisely so they cannot alarm. The brief therefore prints "
            "'garmin — last update … (Nd ago)' in the ⚠️ Data Status banner EVERY morning, forever, for "
            "a source that is off on purpose. It should derive the set from `checker_sources()`. "
            "Hurts: Matthew — a permanent false line in the one banner that is supposed to mean "
            "'today's grade may not be real'."
        ),
    )
    def test_the_scan_never_watches_a_deliberately_paused_source(self):
        watched = set(brief.STALENESS_SOURCES)
        paused = {k for k, v in registry.SOURCE_REGISTRY.items() if v.get("paused")}
        assert not (watched & paused), f"paused sources still alarm daily: {sorted(watched & paused)}"


# ══════════════════════════════════════════════════════════════════════════════
# 13. The regrade branch
# ══════════════════════════════════════════════════════════════════════════════


class TestRegradeHandler:
    def test_each_requested_date_is_regraded_and_stored(self, table, monkeypatch):
        monkeypatch.setattr(brief, "compute_day_grade", lambda data, profile: (81, "B", {"sleep_quality": 80}, {}))
        out = brief._regrade_handler([YESTERDAY, "2026-08-05"], PROFILE)
        assert out["regraded"] == 2
        assert {p["sk"] for p in table.puts} == {"DATE#" + YESTERDAY, "DATE#2026-08-05"}

    def test_one_failing_date_never_aborts_the_rest_of_the_batch(self, table, monkeypatch):
        def flaky(data, profile):
            if data["date"] == YESTERDAY:
                raise ValueError("bad row")
            return (81, "B", {}, {})

        monkeypatch.setattr(brief, "compute_day_grade", flaky)
        out = brief._regrade_handler([YESTERDAY, "2026-08-05"], PROFILE)
        assert out["results"][0]["error"] == "bad row"
        assert out["results"][1]["grade"] == "B"


# ══════════════════════════════════════════════════════════════════════════════
# 14. lambda_handler — dispatch, dry-run and the sick-day branch
# ══════════════════════════════════════════════════════════════════════════════


class _FakeHtmlBuilder:
    def __init__(self):
        self.calls = []
        self.error = None

    def build_html(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return "<!DOCTYPE html><html><body>THE BRIEF</body></html>"

    @staticmethod
    def hrv_trend_str(a, b):
        return "steady"


class _FakeOutputWriters:
    def __init__(self):
        self.inited = 0
        self.dashboard = []
        self.clinical = []
        self.buddy = []
        self.public_stats = []

    def init(self, **kwargs):
        self.inited += 1

    def write_dashboard_json(self, *a, **k):
        self.dashboard.append((a, k))

    def write_clinical_json(self, *a, **k):
        self.clinical.append((a, k))

    def write_buddy_json(self, *a, **k):
        self.buddy.append((a, k))

    def write_public_stats_json(self, *a, **k):
        self.public_stats.append((a, k))

    def evaluate_rewards(self, cs):
        return []

    def get_protocol_recs(self, cs):
        return []

    def sanitize_for_demo(self, html, data, profile):
        return "[SANITIZED]" + html


@pytest.fixture
def handler_env(monkeypatch, table, ses):
    """Wires every collaborator `lambda_handler` reaches — module-level and
    lazily imported — to a bounded fake. Returns the handles a test asserts on.

    Nothing here can reach AWS, Bedrock or the network.
    """
    fake_boto3 = FakeBoto3()
    html = _FakeHtmlBuilder()
    writers = _FakeOutputWriters()
    s3 = FakeS3()

    monkeypatch.setattr(brief, "boto3", fake_boto3)
    monkeypatch.setattr(brief, "s3", s3)
    monkeypatch.setattr(brief, "html_builder", html)
    monkeypatch.setattr(brief, "output_writers", writers)
    monkeypatch.setattr(brief, "fetch_profile", lambda: dict(PROFILE))
    monkeypatch.setattr(brief, "validate_daily_brief_outputs", lambda **kw: {**kw, "validation_warnings": []})

    # The AI pipeline: denied by default so a test opts in explicitly.
    from ai import budget_guard

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
    monkeypatch.setattr(budget_guard, "read_breakdown", lambda *a, **k: None)

    # Lazily imported collaborators — each builds its own AWS client otherwise.
    from coach import intake_response
    from content import site_writer, vacation_fund
    from health import genome_coaching, labs_coaching, sick_day_checker
    from web import vitals_resolver

    monkeypatch.setattr(sick_day_checker, "check_sick_day", lambda *a, **k: None)
    monkeypatch.setattr(labs_coaching, "build_labs_coaching_context", lambda *a, **k: "")
    monkeypatch.setattr(genome_coaching, "build_genome_coaching_context", lambda *a, **k: "")
    monkeypatch.setattr(vacation_fund, "compute_vacation_fund", lambda *a, **k: None)
    monkeypatch.setattr(intake_response, "compute_intake_response", lambda *a, **k: None)
    monkeypatch.setattr(intake_response, "brief_line", lambda payload: None)

    vitals = {
        "recovery_pct": 62.0,
        "recovery_status": "moderate",
        "hrv_ms": 55.0,
        "rhr_bpm": 58.0,
        "sleep_hours": 7.2,
    }
    monkeypatch.setattr(vitals_resolver, "resolve_vitals", lambda *a, **k: dict(vitals))

    public_stats = _Recorder()
    pulse = _Recorder()
    monkeypatch.setattr(site_writer, "write_public_stats", public_stats)
    monkeypatch.setattr(site_writer, "write_pulse_json", pulse)

    insights = _Recorder(result=0)
    monkeypatch.setattr(brief.insight_writer, "extract_daily_brief_insights", lambda **kw: [])
    monkeypatch.setattr(brief.insight_writer, "write_insights_batch", insights)

    return {
        "table": table,
        "ses": ses,
        "s3": s3,
        "boto3": fake_boto3,
        "html": html,
        "writers": writers,
        "public_stats": public_stats,
        "pulse": pulse,
        "budget_guard": budget_guard,
    }


def computed_row(date_str=YESTERDAY, **over):
    fields = {
        "computed_at": "2026-08-07T16:40:00+00:00",  # 20 min before the frozen run
        "day_grade_score": Decimal("84"),
        "day_grade_letter": "B",
        "readiness_score": Decimal("71"),
        "readiness_colour": "yellow",
        "component_scores": {"sleep_quality": Decimal("80")},
        "component_details": {},
        "tier0_streak": Decimal("12"),
        "tier01_streak": Decimal("5"),
        "vice_streaks": {"no_weed": Decimal("40")},
        "latest_weight": Decimal("317.0"),
        "week_ago_weight": Decimal("320.0"),
        "avatar_weight": Decimal("317.0"),
        "hrv_7d": Decimal("55.0"),
        "hrv_30d": Decimal("52.0"),
        "tsb": Decimal("-4.0"),
        "ctl": Decimal("41.0"),
        "atl": Decimal("45.0"),
        "sleep_debt_7d_hrs": Decimal("3.5"),
    }
    fields.update(over)
    return day_row("computed_metrics", date_str, **fields)


class TestHandlerDispatch:
    def test_a_healthcheck_returns_immediately_and_sends_nothing(self, handler_env):
        assert brief.lambda_handler({"healthcheck": True}, None)["statusCode"] == 200
        assert handler_env["ses"].sent == []

    def test_a_missing_profile_raises_so_the_errors_alarm_fires(self, handler_env, monkeypatch):
        """A returned 500 would read as a successful invocation and the brief
        would silently never send."""
        monkeypatch.setattr(brief, "fetch_profile", lambda: None)
        with pytest.raises(RuntimeError, match="no profile"):
            brief.lambda_handler({}, None)

    def test_the_regrade_branch_never_sends_mail(self, handler_env, monkeypatch):
        monkeypatch.setattr(brief, "compute_day_grade", lambda d, p: (80, "B", {}, {}))
        out = brief.lambda_handler({"regrade_dates": [YESTERDAY]}, None)
        assert out["regraded"] == 1
        assert handler_env["ses"].sent == []

    def test_a_normal_run_sends_exactly_one_brief(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        assert len(handler_env["ses"].sent) == 1

    def test_the_subject_carries_the_grade_and_the_readiness_light(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        subject = handler_env["ses"].sent[0]["Content"]["Simple"]["Subject"]["Data"]
        assert "Grade: 84 (B)" in subject
        assert "🟡" in subject  # readiness_colour == yellow

    def test_the_pre_computed_grade_is_used_without_recomputing(self, handler_env, monkeypatch):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        called = _Recorder(result=(1, "F", {}, {}))
        monkeypatch.setattr(brief, "compute_day_grade", called)
        brief.lambda_handler({}, None)
        assert called.calls == []

    def test_budget_tier_three_still_sends_the_brief_data_only(self, handler_env):
        """'Protect longest' by design (ADR-125): AI pauses, the email does not."""
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        assert len(handler_env["ses"].sent) == 1
        # No AI text reached the renderer.
        _, kwargs = handler_env["html"].calls[0]
        assert kwargs["sleep_coach_v2_text"] == ""

    def test_demo_mode_sanitizes_and_prefixes_but_still_sends(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({"demo_mode": True}, None)
        sent = handler_env["ses"].sent[0]
        assert sent["Content"]["Simple"]["Subject"]["Data"].startswith("[DEMO]")
        assert "[SANITIZED]" in sent["Content"]["Simple"]["Body"]["Html"]["Data"]

    def test_demo_mode_writes_none_of_the_public_artifacts(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({"demo_mode": True}, None)
        assert handler_env["public_stats"].calls == []
        assert handler_env["writers"].dashboard == []

    def test_a_crashing_renderer_still_ships_a_minimal_brief(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        handler_env["html"].error = RuntimeError("template exploded")
        brief.lambda_handler({}, None)
        body = handler_env["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "Partial Failure" in body and "template exploded" in body

    def test_a_stale_source_prepends_the_data_status_banner(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        old = whoop_row("2026-07-01", hrv=Decimal("50"))
        handler_env["table"].store[(old["pk"], old["sk"])] = old
        brief.lambda_handler({}, None)
        body = handler_env["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "Data Status" in body and body.index("Data Status") < body.index("THE BRIEF")


class TestDryRun:
    def test_an_event_dry_run_generates_the_brief_but_sends_nothing(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({"dry_run": True}, None)
        assert handler_env["ses"].sent == []
        assert handler_env["html"].calls, "the brief was not generated at all"

    def test_the_dry_run_env_var_also_suppresses_the_send(self, handler_env, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "1")
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        assert handler_env["ses"].sent == []

    def test_force_send_overrides_the_env_var_for_a_one_off_real_send(self, handler_env, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "1")
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({"force_send": True}, None)
        assert len(handler_env["ses"].sent) == 1

    def test_the_sick_day_path_honours_dry_run_too(self, handler_env, monkeypatch):
        from health import sick_day_checker

        monkeypatch.setattr(sick_day_checker, "check_sick_day", lambda *a, **k: {"reason": "flu"})
        brief.lambda_handler({"dry_run": True}, None)
        assert handler_env["ses"].sent == []

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2670 (lambda_handler): `record_email_send(table, 'daily_brief')` runs "
            "unconditionally — outside the `if event['_dry_run_resolved']` branch at 2283 — so a DRY_RUN "
            "invocation writes an email_log row stamped `status: 'success'` for a mail that was never "
            "sent. The row's stated purpose (line 1378) is 'so the status page can track last send', and "
            "the CloudWatch alarm on a missing row is exactly what a dry run should NOT silence. It "
            "should skip the record, or stamp it `dry_run`. Hurts: Matthew — a real send failure on a "
            "day someone was testing looks green."
        ),
    )
    def test_a_dry_run_does_not_claim_a_successful_send_in_the_status_log(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({"dry_run": True}, None)
        email_log = [p for p in handler_env["table"].puts if "email_log" in str(p.get("pk", ""))]
        assert email_log == [], f"a dry run recorded a send: {email_log}"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:1622-1626 (lambda_handler): the DRY_RUN gate covers ONLY the two "
            "ses.send_email calls (2283, 1739). Every side effect downstream still fires: "
            "output_writers.write_dashboard/clinical/buddy/public_stats_json (2301-2317), "
            "site_writer.write_public_stats + write_pulse_json (2520/2633) — which overwrite the LIVE "
            "public artifacts averagejoematt.com serves — the guidance_given update_item (2056) and the "
            "day_grade/habit_scores puts on the fallback path. A dry run is therefore not a dry run: "
            "testing the brief republishes the public site's stats. It should gate the writes too (or "
            "the flag should be named send_only). Hurts: readers of the live site, and anyone who "
            "believes DRY_RUN is side-effect-free."
        ),
    )
    def test_a_dry_run_does_not_republish_the_live_public_artifacts(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({"dry_run": True}, None)
        assert handler_env["public_stats"].calls == [], "DRY_RUN overwrote the public site's stats"
        assert handler_env["pulse"].calls == []


class TestSickDayBrief:
    @pytest.fixture(autouse=True)
    def _sick(self, handler_env, monkeypatch):
        from health import sick_day_checker

        monkeypatch.setattr(sick_day_checker, "check_sick_day", lambda *a, **k: {"reason": "flu"})
        return handler_env

    def test_a_sick_day_sends_the_recovery_brief_instead_of_the_full_one(self, handler_env):
        brief.lambda_handler({}, None)
        sent = handler_env["ses"].sent[0]
        assert "Recovery Day" in sent["Content"]["Simple"]["Subject"]["Data"]
        assert handler_env["html"].calls == [], "the full brief was still rendered"

    def test_the_recovery_brief_is_tagged_separately_for_deliverability_tracking(self, handler_env):
        brief.lambda_handler({}, None)
        assert handler_env["ses"].sent[0]["EmailTags"] == [{"Name": "message_type", "Value": "daily_brief_sick"}]

    def test_absent_vitals_render_as_em_dashes_never_as_zeroes(self, handler_env):
        """ADR-104 — a sick day with no Whoop sync must not read 'Recovery 0%'."""
        brief.lambda_handler({}, None)
        body = handler_env["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        # The three vitals cells are the right-aligned <td>s; match the value slot
        # itself rather than the document (a `width:100%` style would false-match).
        assert 'text-align:right;">0' not in body
        assert body.count('text-align:right;">—</td>') == 3

    def test_the_present_vitals_are_shown(self, handler_env):
        r = whoop_row(YESTERDAY, sleep_duration_hours=Decimal("8.4"), recovery_score=Decimal("41"), hrv=Decimal("62"))
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        body = handler_env["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "8.4 hrs" in body and "41%" in body and "62 ms" in body

    def test_no_grade_is_computed_or_stored_on_a_sick_day(self, handler_env):
        brief.lambda_handler({}, None)
        assert [p for p in handler_env["table"].puts if p.get("pk", "").endswith("day_grade")] == []

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:1766 (lambda_handler): the sick-day branch returns before "
            "record_email_send at 2670, so no email_log row is written on a sick day even though a real "
            "SES send happened. The row exists so 'the status page can track last send' (line 1378) and "
            "a missing row is what monitoring reads as a missed brief — so every sick day produces a "
            "false 'the daily brief did not send' signal. It should record the send it just made. "
            "Hurts: Matthew, exactly on the days he is least able to investigate a false alarm."
        ),
    )
    def test_a_sick_day_send_is_still_recorded_for_the_status_page(self, handler_env):
        brief.lambda_handler({}, None)
        email_log = [p for p in handler_env["table"].puts if "email_log" in str(p.get("pk", ""))]
        assert email_log, "a real send went out with no completion record"


# ══════════════════════════════════════════════════════════════════════════════
# 15. Compute-staleness honesty
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeStaleness:
    def _run_and_get_stale_flag(self, handler_env):
        brief.lambda_handler({}, None)
        _, kwargs = handler_env["html"].calls[0]
        return kwargs["compute_stale"], kwargs["compute_age_msg"]

    def test_a_fresh_computed_row_is_not_flagged(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        assert self._run_and_get_stale_flag(handler_env)[0] is False

    def test_a_row_older_than_four_hours_raises_the_banner(self, handler_env):
        r = computed_row(computed_at="2026-08-06T18:00:00+00:00")  # 23h before the run
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        stale, msg = self._run_and_get_stale_flag(handler_env)
        assert stale is True and msg == "23.0h ago"

    def test_a_missing_computed_row_is_reported_as_not_available(self, handler_env):
        stale, msg = self._run_and_get_stale_flag(handler_env)
        assert stale is True and msg == "not available"

    def test_the_ops_metric_mirrors_the_staleness_decision(self, handler_env):
        r = computed_row(computed_at="2026-08-06T18:00:00+00:00")
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        metric = handler_env["boto3"].cloudwatch.metrics[0]["MetricData"][0]
        assert metric["MetricName"] == "ComputePipelineStaleness"
        assert metric["Value"] == 1.0

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:1804-1805 (lambda_handler): when a computed_metrics row exists but "
            "carries NO `computed_at`, the else-branch logs 'Using pre-computed metrics' and leaves "
            "_compute_stale False — the row is declared fresh on the basis of nothing. The same happens "
            "at 1802-1803 when computed_at is present but unparseable. Both are exactly the shapes a "
            "partial write or a schema change produces, and both suppress the reader-facing 'data may "
            "be estimated' banner AND report 0.0 to the ComputePipelineStaleness alarm. Unknown age "
            "should be treated as stale, not as fresh. Hurts: Matthew — a brief built on a month-old "
            "row presents itself as today's."
        ),
    )
    def test_a_row_with_no_timestamp_is_not_declared_fresh(self, handler_env):
        r = computed_row()
        del r["computed_at"]
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        stale, _ = self._run_and_get_stale_flag(handler_env)
        assert stale is True, "a computed row of unknown age was presented as current"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:1842-1847 (lambda_handler): the pre-computed branch is NOT wrapped in "
            "a try — `int(float(_cm_score))` and the `component_scores` comprehension raise ValueError "
            "on any non-numeric cell (an empty string, an '—' placeholder, a stringified None). The "
            "exception escapes lambda_handler and the entire brief is lost, where the inline fallback "
            "path immediately below (1887-1892) catches exactly this and degrades to defaults. One "
            "malformed cell in a compute output should cost the day grade, not the email. "
            "Hurts: Matthew. Severity P1 (crash)."
        ),
    )
    def test_a_malformed_pre_computed_cell_does_not_lose_the_whole_brief(self, handler_env):
        r = computed_row(day_grade_score="—")
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        assert len(handler_env["ses"].sent) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 16. What the brief publishes to the PUBLIC artifacts
# ══════════════════════════════════════════════════════════════════════════════


def _published(handler_env):
    """The kwargs the handler handed to site_writer.write_public_stats."""
    assert handler_env["public_stats"].calls, "write_public_stats was never called"
    return handler_env["public_stats"].calls[0][1]


class TestPublicStatsTruth:
    @pytest.fixture(autouse=True)
    def _seed_computed(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        return handler_env

    def test_the_journey_block_is_derived_from_the_profile_and_the_scale(self, handler_env):
        brief.lambda_handler({}, None)
        journey = _published(handler_env)["journey"]
        assert journey["current_weight_lbs"] == 317.0
        assert journey["lost_lbs"] == 4.6  # 321.6 - 317.0
        assert journey["remaining_lbs"] == 132.0  # 317.0 - 185

    def test_the_weekly_delta_is_named_for_the_window_it_covers(self, handler_env):
        """#1917 — it shipped as `weight_delta_30d` for a 7-day figure."""
        brief.lambda_handler({}, None)
        vitals = _published(handler_env)["vitals"]
        assert vitals["weight_delta_7d"] == -3.0  # 317.0 - 320.0
        assert vitals["weight_delta_window_days"] == 7
        assert "weight_delta_30d" not in vitals

    def test_the_counts_come_from_the_one_guarded_platform_stats_home(self, handler_env):
        """#1369 — hand-authored counts are what put wrong hero copy live."""
        from web.site_api_common import PLATFORM_STATS

        brief.lambda_handler({}, None)
        platform = _published(handler_env)["platform"]
        assert platform["mcp_tools"] == PLATFORM_STATS["mcp_tools"]
        assert platform["data_sources"] == PLATFORM_STATS["data_sources"]

    def test_the_vitals_come_from_the_canonical_resolver_not_a_local_re_derivation(self, handler_env):
        """#1369 truth spine — public_stats cannot disagree with /api/vitals."""
        brief.lambda_handler({}, None)
        vitals = _published(handler_env)["vitals"]
        assert vitals["recovery_pct"] == 62.0 and vitals["rhr_bpm"] == 58.0

    def test_an_absent_weight_publishes_null_rather_than_zero(self, handler_env):
        r = computed_row()
        for k in ("latest_weight", "avatar_weight", "week_ago_weight"):
            del r[k]
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        published = _published(handler_env)
        assert published["vitals"]["weight_lbs"] is None
        assert published["journey"]["lost_lbs"] is None
        assert published["journey"]["progress_pct"] is None

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2395 (lambda_handler): `_acwr = float(_cm.get('acwr') or 1.1)` "
            "substitutes a fabricated 1.1 — a healthy mid-band acute:chronic ratio — whenever the ACWR "
            "compute has not run or produced no value. That number is published to "
            "generated/public_stats.json and drawn on the daily OG share card "
            "(og_image_lambda.py:145 renders training['acwr']). A reader cannot tell a measured 1.1 from "
            "no measurement at all. ADR-104: it should publish null. "
            "Hurts: every reader of the site and of the share cards."
        ),
    )
    def test_an_absent_acwr_is_published_as_null_not_as_a_healthy_looking_default(self, handler_env):
        r = computed_row()  # no `acwr` key at all
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        assert _published(handler_env)["training"]["acwr"] is None

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2569-2570 (lambda_handler) reads `_cm.get('zone')` and "
            "`_cm.get('alert')` off the computed_metrics row — but the writer, "
            "acwr_compute_lambda.py:284-285 (`_write_acwr`), stores those fields as `acwr_zone` and "
            "`acwr_alert`. Neither bare name is ever written by anything in this repo. The classic "
            "reader/writer mismatch: `form_status` is therefore permanently 'neutral' and `injury_risk` "
            "permanently 'low' in public_stats.json — including on days the ACWR engine has raised a "
            "genuine overtraining alert — and og_image_lambda.py:146 prints that 'NEUTRAL' on the public "
            "share card. The same two bare names are read at daily_brief_lambda.py:798-799 (log only) "
            "and, worse, at html_builder.py:1078-1079, which is what greys out the ACWR zone label and "
            "the alert colour in the email itself. Hurts: Matthew (a suppressed injury warning) and "
            "every reader of the public site."
        ),
    )
    def test_a_raised_acwr_alert_reaches_the_published_injury_risk(self, handler_env):
        r = computed_row(acwr=Decimal("1.62"), acwr_zone="danger", acwr_alert=True)
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        training = _published(handler_env)["training"]
        assert training["injury_risk"] == "high", "an ACWR alert did not reach injury_risk"
        assert training["form_status"] == "danger"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2535 (lambda_handler): `'rhr_trend': 'improving'` is a hard-coded "
            "string published to public_stats.json alongside a real, resolver-derived rhr_bpm. The site "
            "renders it as a measured trend. It has never been computed, so it reads 'improving' on a "
            "day resting heart rate rose. ADR-104 / ADR-105: a claim with no computation behind it "
            "should not ship. Hurts: every reader of averagejoematt.com."
        ),
    )
    def test_the_published_rhr_trend_is_computed_rather_than_asserted(self, handler_env):
        brief.lambda_handler({}, None)
        first = _published(handler_env)["vitals"]["rhr_trend"]
        assert first != "improving", "rhr_trend is a hard-coded constant, not a measurement"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2571-2572 (lambda_handler): `'total_miles_30d': 0` and "
            "`'activity_count_30d': 0` are hard-coded zeros published into public_stats.json's training "
            "block. A reader (and the OG card generator) cannot distinguish 'we do not compute this' "
            "from 'you did nothing for 30 days'. ADR-104: publish null, or compute it — the 60-day "
            "Strava window needed is already in hand at this point in the handler. Hurts: every reader "
            "of the site."
        ),
    )
    def test_uncomputed_training_totals_are_published_as_absence_not_as_zero(self, handler_env):
        brief.lambda_handler({}, None)
        training = _published(handler_env)["training"]
        assert training["total_miles_30d"] is None and training["activity_count_30d"] is None

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2565-2567 (lambda_handler): ctl_fitness / atl_fatigue / tsb_form fall "
            "back to a literal 0 when the computed values are absent (`float(data.get('ctl') if ... else "
            "0)`, `float(data.get('tsb') or 0)`). Zero CTL is not 'unknown fitness', it is 'completely "
            "detrained', and the site plots it on the same axis as a measured value. ADR-104: absence "
            "should publish null. Hurts: every reader of the site's training block."
        ),
    )
    def test_absent_training_load_publishes_null_rather_than_a_detrained_zero(self, handler_env):
        r = computed_row()
        for k in ("ctl", "atl", "tsb"):
            del r[k]
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        training = _published(handler_env)["training"]
        assert training["ctl_fitness"] is None and training["atl_fatigue"] is None

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2489-2495 (lambda_handler) appends "
            "get_food_delivery_brief_signal()'s line — 'Delivery-free streak: N days', or 'Food delivery "
            "ordered today' — into `_group_narratives['nutrition']`, which is written verbatim into "
            "generated/public_stats.json (site_writer.py:384, PUBLIC_STATS_KEY = "
            "'generated/public_stats.json', served publicly via the ADR-046 CloudFront generated "
            "origin). Food-delivery behaviour is private-by-default everywhere else on the platform: "
            "site_api_meals.py:288 gates the identical data class behind NUTRITION_DELIVERY_PUBLIC "
            "(#2209, default off). This is the same data class through a different door, with no gate "
            "at all. It should be gated by the same flag. Hurts: Matthew's privacy. Severity P1."
        ),
    )
    def test_the_food_delivery_streak_is_not_published_to_the_public_artifact(self, handler_env):
        handler_env["table"].store[(f"USER#{brief.USER_ID}#SOURCE#food_delivery", "STREAK#current")] = {"streak_days": Decimal("21")}
        brief.lambda_handler({}, None)
        narratives = _published(handler_env)["group_narratives"]
        assert "delivery" not in str(narratives).lower(), f"delivery behaviour published: {narratives}"


class TestCockpitGroupNarratives:
    """The one-sentence-per-pillar strings written into public_stats.json."""

    @pytest.fixture(autouse=True)
    def _seed_computed(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        return handler_env

    def _narratives(self, handler_env):
        brief.lambda_handler({}, None)
        return _published(handler_env)["group_narratives"]

    def test_the_body_line_names_the_weight_and_the_delta_from_day_one(self, handler_env):
        n = self._narratives(handler_env)
        assert "317.0 lbs" in n["body"] and "4.6 lbs down" in n["body"]

    def test_the_recovery_line_is_built_from_the_readings_that_exist(self, handler_env):
        n = self._narratives(handler_env)
        assert "HRV" in n["recovery"] and "recovery 62%" in n["recovery"]

    def test_the_habits_line_reports_the_tier_zero_streak(self, handler_env):
        assert "Tier 0 streak: 12 days" in self._narratives(handler_env)["habits"]

    def test_a_pillar_with_no_data_gets_no_sentence_rather_than_an_empty_one(self, handler_env):
        """Absence is silence, not "0 min" (ADR-104)."""
        n = self._narratives(handler_env)
        assert "activity" not in n  # no Strava rows seeded
        assert "nutrition" not in n  # no CGM, no delivery streak

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2497-2506 (lambda_handler): the habits narrative appends "
            "'— N% completion today' from `streak_data.get('tier0_pct')` / "
            "`streak_data.get('tier0_completion_pct')` / `_computed.get('tier0_pct')`. None of the three "
            "is ever produced: compute_habit_streaks (daily_brief_lambda.py:1260-1264) returns exactly "
            "{tier0_streak, tier01_streak, vice_streaks}, and daily_metrics_compute_lambda.py:857 writes "
            "tier0_pct onto the SOURCE#habit_scores row, not onto computed_metrics. Reader/writer "
            "mismatch: the completion clause has never rendered on either path. It should read the "
            "habit_scores row. Hurts: readers of the cockpit habits pillar — the sentence is half the "
            "story it was written to tell."
        ),
    )
    def test_the_habits_line_carries_todays_completion_percentage(self, handler_env):
        hs = day_row("habit_scores", YESTERDAY, tier0_pct=Decimal("0.75"), tier0_done=3, tier0_total=4)
        handler_env["table"].store[(hs["pk"], hs["sk"])] = hs
        assert "completion today" in self._narratives(handler_env)["habits"]

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2366-2372 + 2477-2479 + 2573 (lambda_handler): `_z2_this_week` sums "
            "the FULL moving time of every activity whose sport matches "
            "run/walk/ride/swim/elliptical/workout — no heart-rate zone, no pace band, no intensity "
            "filter of any kind — and then publishes it as `zone2_this_week_min` against a 150-minute "
            "Zone 2 target, and narrates it as 'Zone 2 this week: N / 150 min (P% of target)'. A "
            "max-effort interval session counts in full toward a Zone-2 goal. It is total aerobic "
            "moving minutes, and it should be named that (or actually filtered by zone). "
            "#1917 window/label-honesty class. Hurts: Matthew (a training target he can hit without "
            "doing the work) and every reader of the cockpit activity pillar."
        ),
    )
    def test_zone_two_minutes_exclude_work_done_above_zone_two(self, handler_env):
        sprint = day_row(
            "strava",
            YESTERDAY,
            activities=[
                {
                    "sport_type": "Run",
                    "moving_time_seconds": Decimal("1800"),
                    "average_heartrate": Decimal("178"),  # threshold work, not Zone 2
                    "start_date_local": "2026-08-06T07:00:00",
                }
            ],
        )
        handler_env["table"].store[(sprint["pk"], sprint["sk"])] = sprint
        brief.lambda_handler({}, None)
        assert _published(handler_env)["training"]["zone2_this_week_min"] == 0


class TestPublishedTrendArrays:
    @pytest.fixture(autouse=True)
    def _seed(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        for i in range(20):
            d = (date(2026, 8, 6) - timedelta(days=i)).isoformat()
            w = withings_row(d, 320.0 - i * 0.1)
            handler_env["table"].store[(w["pk"], w["sk"])] = w
            k = whoop_row(d, hrv=Decimal("50"), sleep_duration_hours=Decimal("7.0"), recovery_score=Decimal("60"))
            handler_env["table"].store[(k["pk"], k["sk"])] = k
        return handler_env

    def test_the_weight_trend_is_capped_at_thirty_points(self, handler_env):
        brief.lambda_handler({}, None)
        trends = _published(handler_env)["trends"]
        assert len(trends["weight_daily"]) == 20  # all we seeded, under the 30 cap
        assert trends["weight_daily"][-1]["date"] == YESTERDAY

    def test_the_sleep_and_recovery_trends_are_the_last_fourteen_points(self, handler_env):
        brief.lambda_handler({}, None)
        trends = _published(handler_env)["trends"]
        assert len(trends["sleep_daily"]) == 14
        assert len(trends["recovery_daily"]) == 14

    def test_the_thirty_day_sleep_average_is_the_mean_of_the_readings(self, handler_env):
        brief.lambda_handler({}, None)
        assert _published(handler_env)["vitals"]["sleep_hours_30d_avg"] == 7.0

    def test_the_weight_as_of_date_travels_with_the_weight(self, handler_env):
        """#1924 — a reading has to carry its own date or the coach narrates a
        stale number as current."""
        brief.lambda_handler({}, None)
        assert _published(handler_env)["vitals"]["weight_as_of"] == YESTERDAY


class TestInlineFallbackPath:
    """What happens when daily-metrics-compute has not run."""

    @pytest.fixture(autouse=True)
    def _inline(self, handler_env, monkeypatch):
        monkeypatch.setattr(brief, "compute_day_grade", lambda data, profile: (77, "C+", {"sleep_quality": 80}, dict(HABIT_DETAILS)))
        return handler_env

    def test_the_grade_is_computed_and_stored_when_no_pre_computed_row_exists(self, handler_env):
        brief.lambda_handler({}, None)
        grades = [p for p in handler_env["table"].puts if p["pk"].endswith("day_grade")]
        assert grades and grades[0]["letter_grade"] == "C+"

    def test_the_habit_scores_are_stored_on_the_fallback_path_too(self, handler_env):
        brief.lambda_handler({}, None)
        assert [p for p in handler_env["table"].puts if p["pk"].endswith("habit_scores")]

    def test_a_failing_grade_computation_degrades_to_an_em_dash_rather_than_no_email(self, handler_env, monkeypatch):
        def boom(data, profile):
            raise ValueError("scorer exploded")

        monkeypatch.setattr(brief, "compute_day_grade", boom)
        brief.lambda_handler({}, None)
        assert len(handler_env["ses"].sent) == 1
        assert "Grade: —" in handler_env["ses"].sent[0]["Content"]["Simple"]["Subject"]["Data"]

    def test_a_failing_grade_store_never_costs_the_email(self, handler_env):
        handler_env["table"].put_error = RuntimeError("throttled")
        brief.lambda_handler({}, None)
        assert len(handler_env["ses"].sent) == 1

    def test_the_streaks_are_computed_inline_and_reach_the_renderer(self, handler_env, monkeypatch):
        monkeypatch.setattr(brief, "fetch_profile", lambda: dict(STREAK_PROFILE, **{k: PROFILE[k] for k in ("weight_loss_phases",)}))
        for i in range(3):
            r = habitify_row(_back(i), {"sleep_7h": 1, "protein": 1, "walk": 1, "gym": 1, "no_weed": 1})
            handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        args, _ = handler_env["html"].calls[0]
        assert args[12] == 3  # mvp_streak — three clean tier-0 days back from the subject date
        assert args[14] == {"no_weed": 3}  # vice_streaks

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:1215-1229 (compute_habit_streaks): when the profile declares NO "
            "active tier-0 habits and no mvp_habits — the state right after an experiment reset, and "
            "the state of a fresh profile — `tier0_habits` is empty, so the inner `all(...)` loop is "
            "vacuously true and the streak increments once for every day that merely HAS a habitify "
            "record. The brief then renders a growing 'Tier 0 streak: N days' for a set of zero habits, "
            "and publishes the same N to public_stats.json's platform block. A streak over an empty set "
            "is not a streak; it should be absence. Hurts: Matthew and every reader of the cockpit — a "
            "headline number that measures nothing."
        ),
    )
    def test_an_empty_habit_registry_produces_no_streak_rather_than_a_vacuous_one(self, handler_env):
        for i in range(3):
            r = habitify_row(_back(i), {"anything": 1})
            handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)  # the PROFILE fixture declares no habits at all
        assert handler_env["html"].calls[0][0][12] == 0


class TestPreComputedContext:
    @pytest.fixture(autouse=True)
    def _seed(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        return handler_env

    def test_the_adaptive_brief_mode_is_read_and_passed_through(self, handler_env):
        am = day_row("adaptive_mode", YESTERDAY, brief_mode="focus", engagement_score=Decimal("42"))
        handler_env["table"].store[(am["pk"], am["sk"])] = am
        brief.lambda_handler({}, None)
        _, kwargs = handler_env["html"].calls[0]
        assert kwargs["brief_mode"] == "focus" and kwargs["engagement_score"] == 42.0

    def test_a_missing_adaptive_record_defaults_to_the_standard_brief(self, handler_env):
        brief.lambda_handler({}, None)
        assert handler_env["html"].calls[0][1]["brief_mode"] == "standard"

    def test_the_character_sheet_reaches_both_the_renderer_and_the_public_character_block(self, handler_env):
        cs = day_row("character_sheet", YESTERDAY, character_level=Decimal("7"), tier_name="Forged", xp_total=Decimal("4100"))
        handler_env["table"].store[(cs["pk"], cs["sk"])] = cs
        brief.lambda_handler({}, None)
        assert handler_env["html"].calls[0][1]["character_sheet"]["character_level"] == 7.0
        assert _published(handler_env)["character"]["level"] == 7.0

    def test_no_character_sheet_publishes_absence_rather_than_a_level_zero(self, handler_env):
        brief.lambda_handler({}, None)
        assert _published(handler_env)["character"] is None

    def test_the_pre_computed_streaks_are_the_ones_rendered(self, handler_env):
        brief.lambda_handler({}, None)
        args, _ = handler_env["html"].calls[0]
        assert (args[12], args[13]) == (12, 5)  # mvp_streak, full_streak
        assert args[14] == {"no_weed": 40}

    def test_the_uncertainty_travels_with_the_projection(self, handler_env):
        """#535 — the honest finish line is a range, and a provisional rate has
        no projected date at all."""
        r = computed_row(
            weekly_rate_lbs=Decimal("-1.4"),
            weekly_rate_ci_low=Decimal("-2.1"),
            weekly_rate_ci_high=Decimal("-0.7"),
            rate_provisional=False,
            projected_goal_date="2027-11-02",
            projected_goal_date_earliest="2027-06-01",
            projected_goal_date_latest="2028-04-01",
        )
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        journey = _published(handler_env)["journey"]
        assert journey["weekly_rate_ci_low"] == -2.1 and journey["weekly_rate_ci_high"] == -0.7
        assert journey["projected_goal_date_earliest"] == "2027-06-01"

    def test_a_provisional_rate_publishes_no_goal_date(self, handler_env):
        r = computed_row(weekly_rate_lbs=Decimal("-3.9"), rate_provisional=True)
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)
        journey = _published(handler_env)["journey"]
        assert journey["rate_provisional"] is True and journey["projected_goal_date"] is None


class TestWeeklyHabitReview:
    def test_the_review_is_absent_on_a_weekday(self, handler_env):
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        brief.lambda_handler({}, None)  # the frozen clock is a Friday
        assert handler_env["html"].calls[0][1]["weekly_habit_review"] is None

    def test_a_sunday_run_with_no_habit_history_still_sends(self, handler_env, monkeypatch):
        class _Sunday(_FrozenDatetime):
            @classmethod
            def now(cls, tz=None):
                base = datetime(2026, 8, 9, 17, 0, 0, tzinfo=timezone.utc)  # Sunday
                return base if tz else base.replace(tzinfo=None)

        monkeypatch.setattr(brief, "datetime", _Sunday)
        brief.lambda_handler({}, None)
        assert len(handler_env["ses"].sent) == 1
        assert handler_env["html"].calls[0][1]["weekly_habit_review"] is None


class TestAntiRepetitionWriteBack:
    def test_the_guidance_given_is_written_back_for_the_next_brief(self, handler_env, monkeypatch):
        """Phase 1B — so tomorrow's coach does not repeat today's advice."""
        monkeypatch.setattr(handler_env["budget_guard"], "current_tier", lambda: 0)
        from ai import ai_calls

        for name in [n for n in dir(ai_calls) if n.startswith("call_") and n.endswith("_v2")]:
            monkeypatch.setattr(ai_calls, name, lambda *a, **k: "")
        monkeypatch.setattr(ai_calls, "daily_brief_shared_system", lambda *a, **k: None)
        monkeypatch.setattr(ai_calls, "call_board_of_directors", lambda *a, **k: "")
        monkeypatch.setattr(ai_calls, "call_training_nutrition_coach", lambda *a, **k: {})
        monkeypatch.setattr(ai_calls, "call_tldr_and_guidance", lambda *a, **k: {"tldr": "Hold the line.", "guidance": ["walk", "sleep"]})
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r

        brief.lambda_handler({}, None)
        writes = [u for u in handler_env["table"].updates if "guidance_given" in u.get("UpdateExpression", "")]
        assert writes, "no anti-repetition write-back"
        stored = writes[0]["ExpressionAttributeValues"][":gg"]
        assert "Hold the line." in stored and "walk" in stored


class TestAiOutputOrdering:
    @pytest.fixture(autouse=True)
    def _ai_on(self, handler_env, monkeypatch):
        """Budget tier 0 plus a stubbed ai_calls, so the AI path runs offline."""
        monkeypatch.setattr(handler_env["budget_guard"], "current_tier", lambda: 0)

        from ai import ai_calls

        for name in [n for n in dir(ai_calls) if n.startswith("call_") and n.endswith("_v2")]:
            monkeypatch.setattr(ai_calls, name, lambda *a, **k: "")
        monkeypatch.setattr(ai_calls, "daily_brief_shared_system", lambda *a, **k: None)
        monkeypatch.setattr(ai_calls, "call_board_of_directors", lambda *a, **k: "board line")
        monkeypatch.setattr(ai_calls, "call_training_nutrition_coach", lambda *a, **k: {})
        monkeypatch.setattr(ai_calls, "call_journal_coach", lambda *a, **k: "")
        monkeypatch.setattr(
            ai_calls,
            "call_tldr_and_guidance",
            lambda *a, **k: {"tldr": "You slept 12 hours last night.", "guidance": ["walk"]},
        )
        r = computed_row()
        handler_env["table"].store[(r["pk"], r["sk"])] = r
        return handler_env

    def test_every_v2_coach_in_ai_calls_has_a_slot_in_the_pipeline_result(self):
        """Derived from the ai_calls roster — a ninth coach cannot be added
        without a place to put its text."""
        from ai import ai_calls

        roster = [n[len("call_") : -len("_coach_v2")] for n in dir(ai_calls) if n.startswith("call_") and n.endswith("_coach_v2")]
        assert roster, "no v2 coaches discovered — the derivation is stale"
        result = brief._run_ai_coach_pipeline({}, {}, None, "—", {}, {}, None, "gray", None, "standard")
        for domain in roster:
            assert f"{domain}_coach_v2_text" in result, domain

    def test_the_ensemble_digest_is_kicked_off_asynchronously(self, handler_env):
        brief.lambda_handler({}, None)
        invocations = handler_env["boto3"].lambda_client.invocations
        assert invocations and invocations[0]["InvocationType"] == "Event"

    def test_the_journal_coach_is_skipped_when_there_are_no_entries(self, handler_env, monkeypatch):
        from ai import ai_calls

        called = _Recorder(result="text")
        monkeypatch.setattr(ai_calls, "call_journal_coach", called)
        brief.lambda_handler({}, None)
        assert called.calls == []

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:2066-2076 vs 2078-2098 (lambda_handler): `_elena_hero_line` is sliced "
            "out of `tldr_guidance` BEFORE the AI-3 output validator runs and replaces tldr_guidance "
            "with its corrected version. The hero line is then published to "
            "generated/public_stats.json (2602, `elena_hero_line=`) and rendered on the homepage — so "
            "any sentence the validator strips or rewrites for a fabricated number still reaches the "
            "PUBLIC page carrying the un-validated text, while the email shows the corrected one. The "
            "slice should happen after validation. Hurts: every reader of the homepage; it is the one "
            "AI sentence on the public site that bypasses the ADR-104 grounding gate. Severity P1."
        ),
    )
    def test_the_public_hero_line_is_taken_from_the_validated_text(self, handler_env, monkeypatch):
        def scrub(**kw):
            kw = dict(kw)
            kw["tldr_guidance"] = {"tldr": "You slept 7.2 hours last night.", "guidance": ["walk"]}
            kw["validation_warnings"] = ["fabricated sleep duration corrected"]
            return kw

        monkeypatch.setattr(brief, "validate_daily_brief_outputs", scrub)
        brief.lambda_handler({}, None)
        hero = handler_env["public_stats"].calls[0][1]["elena_hero_line"]
        assert "12 hours" not in hero, f"un-validated model text reached the public homepage: {hero!r}"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "daily_brief_lambda.py:1576-1587 (_run_ai_coach_pipeline): when the journal coach returns "
            "empty or under 10 characters, a hard-coded stub ('Quieter journal day — no clear pattern "
            "surfaced. || One small thing: …') is substituted and then flows on exactly like genuine "
            "coaching — it is rendered in the email AND handed to "
            "insight_writer.extract_daily_brief_insights at 2322-2329, which persists it into the "
            "Insight Ledger where later briefs read it back as prior coaching. An AI-failure stub filed "
            "as genuine content is the ADR-104 case the weekly-plate work already fixed elsewhere: it "
            "should be marked so the ledger can exclude it. Hurts: Matthew — the compounding-insight "
            "corpus is diluted with placeholder text he never received advice from."
        ),
    )
    def test_a_journal_coach_stub_is_not_filed_into_the_insight_ledger_as_real_coaching(self, handler_env, monkeypatch):
        from ai import ai_calls

        monkeypatch.setattr(ai_calls, "call_journal_coach", lambda *a, **k: "")
        entry = row("notion", f"DATE#{YESTERDAY}#journal#evening", template="evening", text="hi")
        handler_env["table"].store[(entry["pk"], entry["sk"])] = entry

        seen = {}
        monkeypatch.setattr(
            brief.insight_writer,
            "extract_daily_brief_insights",
            lambda **kw: seen.update(kw) or [],
        )
        brief.lambda_handler({}, None)
        assert "Quieter journal day" not in (seen.get("journal_coach_text") or ""), "an AI-failure stub was filed as genuine coaching"
