"""tests/test_character_sheet_lambda.py — unit coverage for the daily character
sheet compute lambda (#1658 coverage ratchet).

Everything is offline: the module-level DDB table is replaced with a small
hand-written in-memory double (`_PkTable`) that actually honours the pk + sk
range of a query, so the key shapes the lambda builds are exercised for real
rather than waved through. No S3, no network, no `MagicMock` inside a
pagination loop, and no wall-clock arithmetic against fixture dates — the one
place the module reads `now()` (the engagement-state recency fallback) gets a
frozen `datetime`.

What is pinned here:
  - the DDB read helpers' key construction, pagination and fail-soft contracts,
    including the two that need bespoke bounds (hevy's `#zzzz` end sentinel so
    the end date's per-workout rows are not silently dropped, and reading's
    ADR-097 GSI2 window)
  - the EMA-history loader's window + its 40.0 default for an unscored pillar
  - the food-delivery modifier's exact streak thresholds
  - challenge-XP collection (which challenges qualify, domain→pillar mapping,
    aggregation) and the post-store consume marking
  - the #1373 receipt provenance (`collect_input_rows`) and the write path's
    self-replay verdict
  - `assemble_data`'s completeness/BP/labs/journal derivations and the
    presence-signal recency fallback
  - the handler's branches: healthcheck, idempotency, `force`, sick-day EMA
    freeze (both with and without previous state), config-load failure, and the
    full store → consume → receipt → site-writer path

Existing suites already pin `fetch_date`'s phase/tombstone semantics
(test_character_sheet_phase_947.py) and the journal merge/mood mapping
(test_character_sheet_journal_890.py); those are deliberately not repeated.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

import character_sheet_lambda as csl  # noqa: E402
import pytest  # noqa: E402
from common import constants  # noqa: E402
from content import site_writer  # noqa: E402
from experiment import effect_fitter  # noqa: E402
from health import (  # noqa: E402
    character_engine,
    personal_baselines,
    progression_receipts,
    sick_day_checker,
)
from pacific_clock import freeze_pacific  # noqa: E402 — #2811: the PT clock the module actually calls

PREFIX = "USER#matthew#SOURCE#"
# A Wednesday. The whole fixture web below hardcodes dates around it; tests whose
# assertions depend on where genesis falls relative to DATE pin the genesis via
# monkeypatch (see the `wired` fixture) — the live constant moves every re-anchor
# and made this date pre-genesis at the cycle-13 reset (genesis 2026-08-10).
DATE = "2026-08-05"
_NOW = datetime(2026, 8, 6, 17, 35, tzinfo=timezone.utc)  # the 17:35 UTC cron slot, the day after


class _FrozenDatetime(datetime):
    """datetime subclass with a fixed now(); strptime/strftime stay real."""

    @classmethod
    def now(cls, tz=None):
        return _NOW if tz is not None else _NOW.replace(tzinfo=None)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(csl, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, csl, _FrozenDatetime)
    return _NOW


# ═══════════════════════════════════════════════════════════════════════════
# In-memory table double
# ═══════════════════════════════════════════════════════════════════════════


class _PkTable:
    """DynamoDB `Table` stand-in that honours pk + sk-range key conditions.

    String KeyConditionExpressions (`pk = :pk AND sk BETWEEN :s AND :e`) are
    evaluated against the seeded rows so the *bounds the lambda builds* decide
    what comes back. boto3 `Key(...)` condition objects (the challenges scan and
    the ADR-097 GSI2 reading index) are served from explicit lists instead —
    dispatched on `IndexName` — rather than pretending to parse a condition
    tree. Deliberately not a MagicMock: every read terminates.
    """

    def __init__(self, rows=None, gsi2_rows=None, key_cond_rows=None, pages=None, fail=False):
        self.rows = list(rows or [])
        self.gsi2_rows = list(gsi2_rows or [])
        self.key_cond_rows = list(key_cond_rows or [])
        self.pages = list(pages) if pages is not None else None
        self.fail = fail
        self.store = {(r.get("pk"), r.get("sk")): r for r in self.rows}
        self.query_calls = []
        self.puts = []
        self.updates = []

    # -- reads ------------------------------------------------------------
    def get_item(self, Key=None, **kwargs):
        if self.fail:
            raise RuntimeError("ddb down")
        item = self.store.get((Key.get("pk"), Key.get("sk")))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        if self.fail:
            raise RuntimeError("ddb down")
        if self.pages is not None:
            return self.pages.pop(0) if self.pages else {"Items": []}
        if kwargs.get("IndexName") == "GSI2":
            return {"Items": list(self.gsi2_rows)}
        kce = kwargs.get("KeyConditionExpression")
        if not isinstance(kce, str):
            return {"Items": list(self.key_cond_rows)}
        eav = kwargs.get("ExpressionAttributeValues") or {}
        pk, lo, hi = eav.get(":pk"), eav.get(":s"), eav.get(":e")
        items = [r for r in self.store.values() if r.get("pk") == pk]
        if lo is not None:
            items = [r for r in items if lo <= str(r.get("sk", "")) <= hi]
        items.sort(key=lambda r: str(r.get("sk", "")))
        if kwargs.get("Select") == "COUNT":
            return {"Count": len(items)}
        return {"Items": items}

    # -- writes -----------------------------------------------------------
    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        self.store[(Item.get("pk"), Item.get("sk"))] = Item
        return {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}


def _row(source, sk, **fields):
    row = {"pk": PREFIX + source, "sk": sk}
    row.update(fields)
    return row


def _install(monkeypatch, table):
    monkeypatch.setattr(csl, "table", table)
    return table


# ═══════════════════════════════════════════════════════════════════════════
# Range / window readers
# ═══════════════════════════════════════════════════════════════════════════


class TestFetchRange:
    def test_returns_records_in_key_order_with_decimals_converted(self, monkeypatch):
        table = _install(
            monkeypatch,
            _PkTable(
                [
                    _row("whoop", "DATE#2026-08-04", date="2026-08-04", recovery_score=Decimal("61.5")),
                    _row("whoop", "DATE#2026-08-02", date="2026-08-02", recovery_score=Decimal("48")),
                    _row("whoop", "DATE#2026-07-20", date="2026-07-20"),  # outside the window
                ]
            ),
        )

        out = csl.fetch_range("whoop", "2026-08-01", DATE)

        assert [r["date"] for r in out] == ["2026-08-02", "2026-08-04"]
        assert out[1]["recovery_score"] == 61.5
        assert isinstance(out[1]["recovery_score"], float)
        assert table.query_calls[0]["ExpressionAttributeValues"][":pk"] == PREFIX + "whoop"

    def test_paginates_until_the_last_evaluated_key_is_gone(self, monkeypatch):
        table = _install(
            monkeypatch,
            _PkTable(pages=[{"Items": [{"date": "a"}], "LastEvaluatedKey": {"pk": "p", "sk": "s"}}, {"Items": [{"date": "b"}]}]),
        )

        assert [r["date"] for r in csl.fetch_range("strava", "2026-08-01", DATE)] == ["a", "b"]
        assert table.query_calls[1]["ExclusiveStartKey"] == {"pk": "p", "sk": "s"}

    def test_query_failure_is_fail_soft(self, monkeypatch):
        _install(monkeypatch, _PkTable(fail=True))
        assert csl.fetch_range("whoop", "2026-08-01", DATE) == []


class TestFetchDate:
    def test_read_failure_is_fail_soft(self, monkeypatch):
        # phase + tombstone semantics are pinned by test_character_sheet_phase_947;
        # this covers the remaining branch — a DDB error must not raise.
        _install(monkeypatch, _PkTable(fail=True))
        assert csl.fetch_date("whoop", DATE) is None


class TestLoadPreviousState:
    def test_scans_back_past_missed_days_to_keep_level_continuity(self, monkeypatch):
        # A skipped compute (missing env var, lambda failure) must not reset the
        # level — the back-scan reaches up to 7 days.
        _install(monkeypatch, _PkTable([_sheet_row("2026-08-02", 8)]))

        state = csl.load_previous_state(DATE)

        assert state["date"] == "2026-08-02"
        assert state["character_level"] == 8

    def test_nothing_within_seven_days_is_a_cold_start(self, monkeypatch):
        _install(monkeypatch, _PkTable([_sheet_row("2026-07-20", 8)]))
        assert csl.load_previous_state(DATE) is None


class TestFetchJournalEntries:
    def test_only_the_days_templated_entries_come_back(self, monkeypatch):
        table = _install(
            monkeypatch,
            _PkTable(
                [
                    _row("notion", f"DATE#{DATE}#journal#morning", enriched_mood=Decimal("4")),
                    _row("notion", f"DATE#{DATE}#journal#evening"),
                    _row("notion", "DATE#2026-08-04#journal#morning"),
                ]
            ),
        )

        entries = csl.fetch_journal_entries(DATE)

        assert len(entries) == 2
        assert {e["sk"] for e in entries} == {f"DATE#{DATE}#journal#morning", f"DATE#{DATE}#journal#evening"}
        morning = [e for e in entries if e["sk"].endswith("morning")][0]
        assert morning["enriched_mood"] == 4.0
        eav = table.query_calls[0]["ExpressionAttributeValues"]
        assert eav[":s"] == f"DATE#{DATE}#journal#"
        assert eav[":e"] == f"DATE#{DATE}#journal#zzz"

    def test_query_failure_is_fail_soft(self, monkeypatch):
        _install(monkeypatch, _PkTable(fail=True))
        assert csl.fetch_journal_entries(DATE) == []


class TestFetchHevyWorkoutDays:
    def test_end_date_workouts_are_included_via_the_high_sentinel(self, monkeypatch):
        # The regression this bound exists for (#965): `DATE#{end}#WORKOUT#...`
        # sorts AFTER the bare `DATE#{end}`, so a plain end bound drops the last
        # day's strength work entirely.
        table = _install(
            monkeypatch,
            _PkTable(
                [
                    _row("hevy", f"DATE#{DATE}#WORKOUT#aaa"),
                    _row("hevy", f"DATE#{DATE}#WORKOUT#bbb"),
                    _row("hevy", "DATE#2026-08-03#WORKOUT#ccc"),
                ]
            ),
        )

        assert csl.fetch_hevy_workout_days("2026-07-30", DATE) == ["2026-08-03", DATE]
        assert table.query_calls[0]["ExpressionAttributeValues"][":e"] == f"DATE#{DATE}#zzzz"

    def test_tombstoned_workouts_do_not_count_as_a_training_day(self, monkeypatch):
        _install(
            monkeypatch,
            _PkTable(
                [
                    _row("hevy", "DATE#2026-08-03#WORKOUT#a", tombstone=True),
                    _row("hevy", f"DATE#{DATE}#WORKOUT#b"),
                ]
            ),
        )
        assert csl.fetch_hevy_workout_days("2026-07-30", DATE) == [DATE]

    def test_paginates(self, monkeypatch):
        _install(
            monkeypatch,
            _PkTable(
                pages=[
                    {"Items": [{"sk": "DATE#2026-08-01#WORKOUT#a"}], "LastEvaluatedKey": {"k": 1}},
                    {"Items": [{"sk": "DATE#2026-08-02#WORKOUT#b"}]},
                ]
            ),
        )
        assert csl.fetch_hevy_workout_days("2026-07-30", DATE) == ["2026-08-01", "2026-08-02"]

    def test_failure_scores_an_honest_empty_week(self, monkeypatch):
        _install(monkeypatch, _PkTable(fail=True))
        assert csl.fetch_hevy_workout_days("2026-07-30", DATE) == []


class TestFetchReadingSessionDays:
    def test_uses_gsi2_and_keeps_only_in_range_days(self, monkeypatch):
        table = _install(
            monkeypatch,
            _PkTable(
                gsi2_rows=[
                    {"GSI2SK": "2026-08-04T07:15:00Z"},
                    {"GSI2SK": "2026-08-04T21:40:00Z"},  # same day, one entry
                    {"GSI2SK": f"{DATE}T08:00:00Z"},
                    {"GSI2SK": "2026-08-06T00:05:00Z"},  # the exclusive-ish ceiling day
                    {"GSI2SK": "2026-07-01T08:00:00Z"},  # before the window
                ]
            ),
        )

        assert csl.fetch_reading_session_days("2026-07-30", DATE) == ["2026-08-04", DATE]
        assert table.query_calls[0]["IndexName"] == "GSI2"
        # reading rows are CROSS_PHASE — the ADR-058 phase filter must not apply
        assert "FilterExpression" not in table.query_calls[0]

    def test_failure_is_fail_soft(self, monkeypatch):
        _install(monkeypatch, _PkTable(fail=True))
        assert csl.fetch_reading_session_days("2026-07-30", DATE) == []


class TestSafeFloat:
    def test_numeric_strings_and_decimals_convert(self):
        assert csl._safe_float({"w": Decimal("321.6")}, "w") == 321.6
        assert csl._safe_float({"w": "180"}, "w") == 180.0

    def test_missing_field_or_unparseable_value_is_none(self):
        assert csl._safe_float({"w": 1}, "other") is None
        assert csl._safe_float({"w": "heavy"}, "w") is None
        assert csl._safe_float(None, "w") is None


# ═══════════════════════════════════════════════════════════════════════════
# EMA history window
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadRawScoreHistories:
    def _sheet(self, date_str, **pillars):
        row = _row("character_sheet", "DATE#" + date_str, date=date_str)
        for name, score in pillars.items():
            row["pillar_" + name] = {"raw_score": Decimal(str(score))}
        return row

    def test_window_ends_the_day_before_and_spans_the_requested_days(self, monkeypatch):
        table = _install(monkeypatch, _PkTable([self._sheet("2026-08-04", sleep=52)]))

        histories, records = csl.load_raw_score_histories(DATE, window=21)

        eav = table.query_calls[0]["ExpressionAttributeValues"]
        assert eav[":s"] == "DATE#2026-07-15"  # 2026-08-05 minus 21 days
        assert eav[":e"] == "DATE#2026-08-04"  # never the day being computed
        assert [r["date"] for r in records] == ["2026-08-04"]
        assert histories["sleep"] == [52.0]

    def test_every_pillar_is_keyed_and_unscored_days_default_to_40(self, monkeypatch):
        _install(monkeypatch, _PkTable([self._sheet("2026-08-03", sleep=61), self._sheet("2026-08-04", movement=70)]))

        histories, _ = csl.load_raw_score_histories(DATE)

        assert set(histories) == set(csl.PILLAR_ORDER)
        assert histories["sleep"] == [61.0, 40.0]  # day 2 carried no sleep raw_score
        assert histories["movement"] == [40.0, 70.0]
        assert histories["mind"] == [40.0, 40.0]

    def test_no_history_yields_empty_lists_not_missing_keys(self, monkeypatch):
        _install(monkeypatch, _PkTable([]))
        histories, records = csl.load_raw_score_histories(DATE)
        assert records == []
        assert all(histories[p] == [] for p in csl.PILLAR_ORDER)


# ═══════════════════════════════════════════════════════════════════════════
# Food-delivery modifier
# ═══════════════════════════════════════════════════════════════════════════


class TestFoodDeliveryModifier:
    def _table(self, monkeypatch, **streak):
        # #2235: updated_at defaults FRESH (real now) so these tests exercise the
        # streak-threshold logic, not the freshness gate — see TestFoodDeliveryFreshness
        # below for the stale-source behavior.
        row = {
            "pk": "USER#matthew#SOURCE#food_delivery",
            "sk": "STREAK#current",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        row.update(streak)
        return _install(monkeypatch, _PkTable([row]))

    def test_delivery_on_the_scored_date_takes_the_penalty(self, monkeypatch):
        self._table(monkeypatch, streak_days=40, last_order_date=DATE)
        assert csl.get_food_delivery_modifier(DATE) == 0.85

    def test_penalty_is_keyed_to_the_scored_date_not_the_run_date(self, monkeypatch):
        # An order placed the day AFTER the date being scored must not penalise
        # that date (the #961 regression).
        self._table(monkeypatch, streak_days=8, last_order_date="2026-08-06")
        assert csl.get_food_delivery_modifier(DATE) == 1.02

    def test_streak_thresholds_at_their_exact_boundaries(self, monkeypatch):
        for days, expected in ((30, 1.10), (29, 1.05), (14, 1.05), (13, 1.02), (7, 1.02), (6, 1.0), (0, 1.0)):
            self._table(monkeypatch, streak_days=days, last_order_date="2026-01-01")
            assert csl.get_food_delivery_modifier(DATE) == expected, days

    def test_no_streak_row_is_neutral(self, monkeypatch):
        _install(monkeypatch, _PkTable([]))
        assert csl.get_food_delivery_modifier(DATE) == 1.0

    def test_read_failure_is_neutral(self, monkeypatch):
        _install(monkeypatch, _PkTable(fail=True))
        assert csl.get_food_delivery_modifier(DATE) == 1.0

    def test_a_stale_source_yields_the_neutral_modifier_not_a_frozen_streak(self, monkeypatch):
        """#2235: a streak_days=40 row (would be the 1.10x bonus band) frozen at an
        `updated_at` older than food_delivery's stale_hours threshold (336h = 14 days,
        source_registry.py) must NOT reach the engine as a live bonus."""
        stale_updated_at = (datetime.now(timezone.utc) - timedelta(hours=337)).isoformat()
        row = {
            "pk": "USER#matthew#SOURCE#food_delivery",
            "sk": "STREAK#current",
            "streak_days": 40,
            "last_order_date": "2026-01-01",
            "updated_at": stale_updated_at,
        }
        _install(monkeypatch, _PkTable([row]))
        assert csl.get_food_delivery_modifier(DATE) == 1.0

    def test_a_record_just_inside_the_threshold_still_counts(self, monkeypatch):
        """Sanity companion: the freshness gate is bounded, not permanently closed."""
        fresh_updated_at = (datetime.now(timezone.utc) - timedelta(hours=335)).isoformat()
        row = {
            "pk": "USER#matthew#SOURCE#food_delivery",
            "sk": "STREAK#current",
            "streak_days": 40,
            "last_order_date": "2026-01-01",
            "updated_at": fresh_updated_at,
        }
        _install(monkeypatch, _PkTable([row]))
        assert csl.get_food_delivery_modifier(DATE) == 1.10


# ═══════════════════════════════════════════════════════════════════════════
# Challenge bonus XP
# ═══════════════════════════════════════════════════════════════════════════


def _challenge(sk, **fields):
    ch = {
        "pk": PREFIX + "challenges",
        "sk": sk,
        "status": "completed",
        "completed_at": DATE + "T18:04:00Z",
        "character_xp_awarded": Decimal("25"),
        "domain": "movement",
        "name": "10k steps",
    }
    ch.update(fields)
    return ch


class TestCollectChallengeBonus:
    def test_sums_per_pillar_across_the_domain_map(self, monkeypatch):
        _install(
            monkeypatch,
            _PkTable(
                key_cond_rows=[
                    _challenge("CHALLENGE#a", domain="movement", character_xp_awarded=Decimal("25")),
                    _challenge("CHALLENGE#b", domain="supplements", character_xp_awarded=Decimal("10")),
                    _challenge("CHALLENGE#c", domain="nutrition", character_xp_awarded=Decimal("15")),
                    _challenge("CHALLENGE#d", domain="wildcard", character_xp_awarded=Decimal("5")),
                ]
            ),
        )

        bonus, items = csl.collect_challenge_bonus(DATE)

        assert bonus == {"movement": 25, "nutrition": 25, "consistency": 5}
        assert len(items) == 4

    def test_failed_challenges_still_settle_their_awarded_xp(self, monkeypatch):
        _install(monkeypatch, _PkTable(key_cond_rows=[_challenge("CHALLENGE#a", status="failed", domain="mental")]))
        bonus, items = csl.collect_challenge_bonus(DATE)
        assert bonus == {"mind": 25}
        assert len(items) == 1

    def test_skips_other_days_open_challenges_zero_awards_and_already_consumed(self, monkeypatch):
        _install(
            monkeypatch,
            _PkTable(
                key_cond_rows=[
                    _challenge("CHALLENGE#other-day", completed_at="2026-08-04T09:00:00Z"),
                    _challenge("CHALLENGE#open", status="active"),
                    _challenge("CHALLENGE#zero", character_xp_awarded=Decimal("0")),
                    _challenge("CHALLENGE#spent", xp_consumed_at="2026-08-06T00:00:00Z"),
                    _challenge("CHALLENGE#no-completion", completed_at=None),
                ]
            ),
        )

        assert csl.collect_challenge_bonus(DATE) == ({}, [])

    def test_query_failure_credits_nothing(self, monkeypatch):
        _install(monkeypatch, _PkTable(fail=True))
        assert csl.collect_challenge_bonus(DATE) == ({}, [])


class TestMarkChallengesConsumed:
    def test_stamps_each_credited_challenge(self, monkeypatch, frozen_clock):
        table = _install(monkeypatch, _PkTable())

        csl.mark_challenges_consumed([_challenge("CHALLENGE#a"), _challenge("CHALLENGE#b")])

        assert [u["Key"]["sk"] for u in table.updates] == ["CHALLENGE#a", "CHALLENGE#b"]
        assert table.updates[0]["Key"]["pk"] == PREFIX + "challenges"
        assert table.updates[0]["UpdateExpression"] == "SET xp_consumed_at = :ts"
        assert table.updates[0]["ExpressionAttributeValues"][":ts"] == _NOW.isoformat()

    def test_a_failed_stamp_does_not_abort_the_rest(self, monkeypatch):
        class _HalfBroken(_PkTable):
            def update_item(self, **kwargs):
                self.updates.append(kwargs)
                if kwargs["Key"]["sk"] == "CHALLENGE#a":
                    raise RuntimeError("throttled")
                return {}

        table = _install(monkeypatch, _HalfBroken())
        csl.mark_challenges_consumed([_challenge("CHALLENGE#a"), _challenge("CHALLENGE#b")])
        assert len(table.updates) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Receipt provenance (#1373)
# ═══════════════════════════════════════════════════════════════════════════


class TestCollectInputRows:
    def test_groups_keys_by_partition_deduped_and_sorted(self):
        data = {
            "whoop": _row("whoop", "DATE#" + DATE),
            "macrofactor": _row("macrofactor", "DATE#" + DATE),
            "sleep_14d": [_row("whoop", "DATE#2026-08-04"), _row("whoop", "DATE#" + DATE)],
            "strava_7d": [_row("strava", "DATE#2026-08-01")],
        }

        rows = csl.collect_input_rows(data, [])

        by_pk = {r["pk"]: r["sks"] for r in rows}
        assert by_pk[PREFIX + "whoop"] == ["DATE#2026-08-04", "DATE#" + DATE]  # deduped + sorted
        assert by_pk[PREFIX + "strava"] == ["DATE#2026-08-01"]
        assert [r["pk"] for r in rows] == sorted(by_pk)

    def test_only_real_rows_are_claimed(self):
        # ADR-104: a receipt never claims an input that was not recorded.
        data = {"whoop": None, "apple": {"no": "keys"}, "todoist": _row("todoist", "DATE#" + DATE)}
        rows = csl.collect_input_rows(data, [])
        assert rows == [{"pk": PREFIX + "todoist", "sks": ["DATE#" + DATE]}]

    def test_history_and_challenge_rows_are_included(self):
        history = [_row("character_sheet", "DATE#2026-08-04")]
        rows = csl.collect_input_rows({}, history, [_challenge("CHALLENGE#a")])
        pks = {r["pk"] for r in rows}
        assert PREFIX + "character_sheet" in pks
        assert PREFIX + "challenges" in pks

    def test_food_delivery_streak_row_is_claimed_only_when_it_modified_the_score(self):
        modified = {"raw_score_modifiers": {"nutrition": {"multiplier": 0.85, "source": "food_delivery"}}}
        rows = csl.collect_input_rows(modified, [])
        assert {"pk": "USER#matthew#SOURCE#food_delivery", "sks": ["STREAK#current"]} in rows
        assert csl.collect_input_rows({"raw_score_modifiers": {}}, []) == []

    def test_derived_day_lists_are_labelled_not_faked_as_rows(self):
        data = {"hevy_workout_days_7d": ["2026-08-03", DATE], "reading_session_days_7d": []}
        rows = csl.collect_input_rows(data, [])
        assert rows == [{"derived": "hevy_workout_days_7d", "values": ["2026-08-03", DATE]}]


class TestWriteProgressionReceipt:
    def _cfg(self):
        return {"pillars": {}}

    def test_a_record_without_transitions_never_fabricates_a_receipt(self, monkeypatch):
        table = _install(monkeypatch, _PkTable())
        assert csl.write_progression_receipt({"date": DATE}, self._cfg(), {}, [], [], DATE) is None
        assert table.puts == []

    def test_verified_replay_stores_the_receipt_and_flags_it(self, monkeypatch, capsys):
        stored = {}
        monkeypatch.setattr(
            progression_receipts, "build_receipt", lambda rec, cfg, input_rows=None: {"digest": "d" * 64, "rows": input_rows}
        )
        monkeypatch.setattr(progression_receipts, "replay", lambda receipt, cfg: {"verified": True})
        monkeypatch.setattr(progression_receipts, "store_receipt", lambda tbl, pk, receipt: stored.update(pk=pk, receipt=receipt))
        _install(monkeypatch, _PkTable())

        data = {"todoist": _row("todoist", "DATE#" + DATE)}
        out = csl.write_progression_receipt({"date": DATE}, self._cfg(), data, [], [], DATE)

        assert out["replay_verified"] is True
        assert stored["pk"] == PREFIX + "character_receipt"
        assert stored["receipt"]["rows"] == [{"pk": PREFIX + "todoist", "sks": ["DATE#" + DATE]}]
        # the EMF drift metric is emitted on every write, mismatch or not
        assert "ReceiptReplayMismatch" in capsys.readouterr().out

    def test_replay_mismatch_is_recorded_on_the_receipt(self, monkeypatch, capsys):
        monkeypatch.setattr(progression_receipts, "build_receipt", lambda rec, cfg, input_rows=None: {"digest": "d" * 64})
        monkeypatch.setattr(progression_receipts, "replay", lambda receipt, cfg: {"verified": False, "mismatches": [{"pillar": "sleep"}]})
        monkeypatch.setattr(progression_receipts, "store_receipt", lambda tbl, pk, receipt: None)
        _install(monkeypatch, _PkTable())

        out = csl.write_progression_receipt({"date": DATE}, self._cfg(), {}, [], [], DATE)

        assert out["replay_verified"] is False
        assert '"ReceiptReplayMismatch"' in capsys.readouterr().out

    def test_receipt_failure_never_takes_down_the_stored_sheet(self, monkeypatch):
        def _boom(rec, cfg, input_rows=None):
            raise RuntimeError("receipt module broken")

        monkeypatch.setattr(progression_receipts, "build_receipt", _boom)
        _install(monkeypatch, _PkTable())

        assert csl.write_progression_receipt({"date": DATE}, self._cfg(), {}, [], [], DATE) is None


# ═══════════════════════════════════════════════════════════════════════════
# Data assembly
# ═══════════════════════════════════════════════════════════════════════════


class TestAssembleData:
    def test_completeness_counts_the_five_expected_sources(self, monkeypatch, frozen_clock):
        _install(
            monkeypatch,
            _PkTable(
                [
                    _row("whoop", "DATE#" + DATE, date=DATE),
                    _row("macrofactor", "DATE#" + DATE, date=DATE),
                    _row("apple_health", "DATE#" + DATE, date=DATE),
                    _row("strava", "DATE#" + DATE, date=DATE),
                    _row("habitify", "DATE#" + DATE, date=DATE),
                ]
            ),
        )

        data = csl.assemble_data(DATE)

        assert data["data_completeness_pct"] == 100.0
        assert data["date"] == DATE
        assert data["sleep"] is data["whoop"]  # whoop is SOT for sleep

    def test_partial_day_reports_a_partial_percentage(self, monkeypatch, frozen_clock):
        _install(monkeypatch, _PkTable([_row("whoop", "DATE#" + DATE, date=DATE), _row("apple_health", "DATE#" + DATE, date=DATE)]))
        assert csl.assemble_data(DATE)["data_completeness_pct"] == 40.0

    def test_empty_platform_yields_honest_nulls(self, monkeypatch, frozen_clock):
        _install(monkeypatch, _PkTable([]))

        data = csl.assemble_data(DATE)

        assert data["data_completeness_pct"] == 0.0
        assert data["bp_data"] is None
        assert data["labs_latest"] is None
        assert data["latest_weight"] is None
        assert data["journal_14d_count"] == 0
        assert data["vice_streaks"] is None
        assert data["journal"] is None

    def test_blood_pressure_needs_both_halves(self, monkeypatch, frozen_clock):
        _install(
            monkeypatch,
            _PkTable([_row("apple_health", "DATE#" + DATE, date=DATE, blood_pressure_systolic=Decimal("124"))]),
        )
        assert csl.assemble_data(DATE)["bp_data"] is None

        _install(
            monkeypatch,
            _PkTable(
                [
                    _row(
                        "apple_health",
                        "DATE#" + DATE,
                        date=DATE,
                        blood_pressure_systolic=Decimal("124"),
                        blood_pressure_diastolic=Decimal("78"),
                    )
                ]
            ),
        )
        assert csl.assemble_data(DATE)["bp_data"] == {"systolic": 124.0, "diastolic": 78.0}

    def test_latest_labs_and_journal_day_count_come_from_the_windows(self, monkeypatch, frozen_clock):
        _install(
            monkeypatch,
            _PkTable(
                [
                    _row("labs", "DATE#2024-02-02", date="2024-02-02", apoB=Decimal("90")),
                    _row("labs", "DATE#2026-07-01", date="2026-07-01", apoB=Decimal("78")),
                    _row("notion", f"DATE#{DATE}#journal#morning"),
                    _row("notion", "DATE#2026-08-04#journal#evening"),
                    _row("notion", "DATE#2026-08-04#journal#morning"),  # same day, counted once
                ]
            ),
        )

        data = csl.assemble_data(DATE)

        assert data["labs_latest"]["apoB"] == 78.0
        assert data["journal_14d_count"] == 2

    def test_vice_streaks_are_lifted_out_of_the_habit_record(self, monkeypatch, frozen_clock):
        _install(
            monkeypatch,
            _PkTable([_row("habit_scores", "DATE#" + DATE, date=DATE, vice_streaks={"alcohol": Decimal("12")})]),
        )
        assert csl.assemble_data(DATE)["vice_streaks"] == {"alcohol": 12.0}

    def test_recent_day_without_a_dated_presence_row_falls_back_to_state_current(self, monkeypatch, frozen_clock):
        # DATE is one day before the frozen "today" — inside the 2-day window.
        _install(
            monkeypatch,
            _PkTable([{"pk": PREFIX + "engagement_state", "sk": "STATE#current", "presence_class": "dark", "gap_days": Decimal("9")}]),
        )

        data = csl.assemble_data(DATE)

        assert data["engagement_state"]["presence_class"] == "dark"
        assert data["engagement_state"]["gap_days"] == 9.0

    def test_historical_rebuild_never_smears_todays_presence_backwards(self, monkeypatch, frozen_clock):
        old_date = "2026-07-01"
        _install(
            monkeypatch,
            _PkTable([{"pk": PREFIX + "engagement_state", "sk": "STATE#current", "presence_class": "dark"}]),
        )
        assert csl.assemble_data(old_date)["engagement_state"] is None

    def test_presence_fallback_read_failure_is_non_fatal(self, monkeypatch, frozen_clock):
        class _PresenceReadBroken(_PkTable):
            def get_item(self, Key=None, **kwargs):
                if Key.get("sk") == "STATE#current":
                    raise RuntimeError("ddb down")
                return super().get_item(Key=Key, **kwargs)

        _install(monkeypatch, _PresenceReadBroken([]))

        data = csl.assemble_data(DATE)

        assert data["engagement_state"] is None
        assert data["date"] == DATE  # assembly completes regardless

    def test_a_wiped_singleton_is_not_read_as_presence(self, monkeypatch, frozen_clock):
        # #946: get_item bypasses the phase filter — a tombstoned singleton must
        # not leak the previous cycle's presence into the rebuild.
        _install(
            monkeypatch,
            _PkTable([{"pk": PREFIX + "engagement_state", "sk": "STATE#current", "tombstone": True, "presence_class": "dark"}]),
        )
        assert csl.assemble_data(DATE)["engagement_state"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Handler
# ═══════════════════════════════════════════════════════════════════════════


def _sheet_row(date_str, level, **pillars):
    row = _row("character_sheet", "DATE#" + date_str, date=date_str, character_level=level, character_tier="Foundation")
    for name in csl.PILLAR_ORDER:
        row["pillar_" + name] = {"raw_score": Decimal(str(pillars.get(name, 45)))}
    return row


class TestHandlerShortCircuits:
    def test_healthcheck_never_touches_the_platform(self, monkeypatch):
        _install(monkeypatch, _PkTable(fail=True))
        assert csl.lambda_handler({"healthcheck": True}, None) == {"statusCode": 200, "body": "ok"}

    def test_already_computed_day_is_skipped_idempotently(self, monkeypatch):
        table = _install(monkeypatch, _PkTable([_sheet_row(DATE, 9)]))

        out = csl.lambda_handler({"date": DATE}, None)

        assert out["statusCode"] == 200
        assert out["body"] == f"Already computed for {DATE}"
        assert out["character_level"] == 9
        assert table.puts == []

    def test_force_bypasses_the_idempotency_check(self, monkeypatch):
        _install(monkeypatch, _PkTable([_sheet_row(DATE, 9)]))
        monkeypatch.setattr(sick_day_checker, "check_sick_day", lambda t, u, d: None)
        monkeypatch.setattr(character_engine, "load_character_config", lambda s3, bucket: None)

        # Getting as far as the config load proves the skip was bypassed; an
        # unreadable config must RAISE (DLQ + alarm), never return a 200.
        with pytest.raises(RuntimeError, match="failed to load config"):
            csl.lambda_handler({"date": DATE, "force": True}, None)

    def test_target_date_defaults_to_yesterday(self, monkeypatch, frozen_clock):
        table = _install(monkeypatch, _PkTable([_sheet_row(DATE, 4)]))
        out = csl.lambda_handler({}, None)
        # frozen now = 2026-08-06 → yesterday = DATE
        assert out["body"] == f"Already computed for {DATE}"
        assert table.puts == []


class TestHandlerSickDayFreeze:
    def test_previous_state_is_copied_forward_with_no_gain_or_penalty(self, monkeypatch, frozen_clock):
        prev = _sheet_row("2026-08-04", 7)
        prev["character_xp"] = Decimal("1420.5")
        table = _install(monkeypatch, _PkTable([prev]))
        monkeypatch.setattr(sick_day_checker, "check_sick_day", lambda t, u, d: {"reason": "flu"})

        out = csl.lambda_handler({"date": DATE}, None)

        assert out["sick_day"] is True
        assert out["frozen_from"] == "2026-08-04"
        assert out["character_level"] == 7
        assert out["character_tier"] == "Foundation"

        item = table.puts[0]
        assert item["pk"] == PREFIX + "character_sheet"
        assert item["sk"] == "DATE#" + DATE
        assert item["date"] == DATE
        assert item["sick_day"] is True  # bools survive the Decimal conversion
        assert item["sick_day_reason"] == "flu"
        assert item["frozen_from"] == "2026-08-04"
        assert item["character_xp"] == Decimal("1420.5")  # EMA frozen, not advanced

    def test_nested_floats_are_decimal_converted_and_nulls_dropped(self, monkeypatch, frozen_clock):
        prev = _sheet_row("2026-08-04", 7)
        prev["active_effects"] = [{"name": "Vice Shield", "magnitude": 1.5}]
        prev["character_mood"] = None
        table = _install(monkeypatch, _PkTable([prev]))
        monkeypatch.setattr(sick_day_checker, "check_sick_day", lambda t, u, d: {"reason": "rest"})

        csl.lambda_handler({"date": DATE}, None)

        item = table.puts[0]
        assert item["active_effects"] == [{"name": "Vice Shield", "magnitude": Decimal("1.5")}]
        assert "character_mood" not in item

    def test_sick_day_with_no_history_computes_nothing_at_all(self, monkeypatch, frozen_clock):
        table = _install(monkeypatch, _PkTable([]))
        monkeypatch.setattr(sick_day_checker, "check_sick_day", lambda t, u, d: {"source": "manual"})

        out = csl.lambda_handler({"date": DATE}, None)

        assert out["sick_day"] is True
        assert "no previous state" in out["body"]
        assert table.puts == []


def _stub_record(date_str):
    record = {
        "date": date_str,
        "character_level": 11,
        "character_tier": "Momentum",
        "character_tier_emoji": "🌱",
        "character_xp": 2480.0,
        "computed_at": "2026-08-06T17:35:00+00:00",
        "engine_version": "test",
        "challenge_bonus_xp": {"movement": 25},
        "active_effects": [{"emoji": "🛡️", "name": "Vice Shield"}],
        "level_events": [
            {
                "date": date_str,
                "type": "pillar_tier_up",
                "pillar": "movement",
                "old_level": 11,
                "new_level": 12,
                "new_tier": "Momentum",
                "top_driver": "zone2_minutes",
                "top_driver_value": "142",
                "streak_days": 5,
                "xp_earned": 40,
            },
            {"date": date_str, "type": "pillar_level_down", "pillar": "sleep", "new_level": 3, "streak_days": 1, "xp_earned": 0},
        ],
    }
    for i, name in enumerate(csl.PILLAR_ORDER):
        record["pillar_" + name] = {
            "raw_score": 50.0 + i,
            "level": 10 + i,
            "tier": "Momentum",
            "tier_emoji": "🌱",
            "xp_delta": 3.0 if name == "movement" else 0.0,
            "challenge_bonus_xp": 25 if name == "movement" else 0,
        }
    return record


class TestHandlerFullCompute:
    @pytest.fixture
    def wired(self, monkeypatch, frozen_clock):
        table = _install(
            monkeypatch,
            _PkTable(
                rows=[
                    _sheet_row("2026-07-28", 6),
                    _sheet_row("2026-08-04", 10),
                    {
                        "pk": "USER#matthew#SOURCE#food_delivery",
                        "sk": "STREAK#current",
                        "streak_days": Decimal("30"),
                        "updated_at": _NOW.isoformat(),  # #2235: fresh relative to frozen_clock's _NOW
                    },
                ],
                key_cond_rows=[_challenge("CHALLENGE#a", domain="movement")],
            ),
        )
        config = {"pillars": {p: {} for p in csl.PILLAR_ORDER}}
        captured = {}

        monkeypatch.setattr(sick_day_checker, "check_sick_day", lambda t, u, d: None)
        # Pin the genesis this fixture web was authored against — the live constant
        # moves every re-anchor (cycle 13 made DATE pre-genesis → phase flipped to
        # "pilot"). Two seams: character_engine's import-time copy, and
        # compute_metadata._infer_phase_from_record's call-time `from common.constants
        # import …`, which reads the constants module attribute fresh each call.
        monkeypatch.setattr(character_engine, "EXPERIMENT_START_DATE", "2026-08-03")
        monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", "2026-08-03")
        monkeypatch.setattr(character_engine, "load_character_config", lambda s3, bucket: config)
        monkeypatch.setattr(personal_baselines, "effective_character_config", lambda cfg, tbl, prefix: cfg)
        monkeypatch.setattr(effect_fitter, "load_latest_fit", lambda tbl, user: None)
        monkeypatch.setattr(csl, "assemble_data", lambda d: {"date": d, "whoop": {"pk": PREFIX + "whoop", "sk": "DATE#" + d}})

        def _compute(data, previous_state, histories, cfg):
            captured["data"] = data
            captured["previous_state"] = previous_state
            captured["histories"] = histories
            return _stub_record(data["date"])

        monkeypatch.setattr(character_engine, "compute_character_sheet", _compute)
        monkeypatch.setattr(site_writer, "write_character_stats", lambda **kwargs: captured.update(site=kwargs) or True)
        return table, captured

    def test_stores_the_sheet_and_returns_the_computed_headline(self, wired):
        table, _ = wired

        out = csl.lambda_handler({"date": DATE}, None)

        assert out["statusCode"] == 200
        assert out["date"] == DATE
        assert out["character_level"] == 11
        assert out["character_tier"] == "Momentum"
        assert len(out["events"]) == 2

        stored = [p for p in table.puts if p["sk"] == "DATE#" + DATE][0]
        assert stored["pk"] == PREFIX + "character_sheet"
        assert stored["character_level"] == 11
        # ADR-058: a post-genesis date is tagged with the live phase, never "pilot"
        assert stored["phase"] == "experiment"
        assert stored["run_id"]

    def test_behavioral_modifiers_and_challenge_xp_reach_the_engine_as_inputs(self, wired):
        _, captured = wired

        csl.lambda_handler({"date": DATE}, None)

        data = captured["data"]
        assert data["raw_score_modifiers"] == {"nutrition": {"multiplier": 1.10, "source": "food_delivery"}}
        assert data["challenge_bonus_xp"] == {"movement": 25}
        # #962 consistency inputs are derived from the same 21-day window
        assert "streak_all_above_30th" in data and "weekend_weekday_ratio" in data

    def test_continuity_state_and_ema_history_come_from_the_stored_sheets(self, wired):
        _, captured = wired

        csl.lambda_handler({"date": DATE}, None)

        assert captured["previous_state"]["date"] == "2026-08-04"
        assert captured["previous_state"]["character_level"] == 10
        assert captured["histories"]["sleep"] == [45.0, 45.0]  # both prior sheets

    def test_challenge_xp_is_consumed_only_after_a_successful_store(self, wired):
        table, _ = wired

        csl.lambda_handler({"date": DATE}, None)

        assert [u["Key"]["sk"] for u in table.updates] == ["CHALLENGE#a"]

    def test_a_store_failure_surfaces_and_never_eats_the_challenge_xp(self, monkeypatch, wired):
        table, _ = wired

        def _boom(tbl, prefix, record):
            raise RuntimeError("ProvisionedThroughputExceeded")

        monkeypatch.setattr(character_engine, "store_character_sheet", _boom)

        with pytest.raises(RuntimeError, match="ProvisionedThroughputExceeded"):
            csl.lambda_handler({"date": DATE}, None)

        assert table.updates == []

    def test_a_compute_failure_is_raised_not_returned_as_a_200(self, monkeypatch, wired):
        def _boom(data, previous_state, histories, cfg):
            raise ValueError("bad pillar config")

        monkeypatch.setattr(character_engine, "compute_character_sheet", _boom)

        with pytest.raises(ValueError, match="bad pillar config"):
            csl.lambda_handler({"date": DATE}, None)

    def test_site_payload_carries_every_pillar_and_a_described_timeline(self, wired):
        _, captured = wired

        csl.lambda_handler({"date": DATE}, None)

        site = captured["site"]
        assert site["character"]["level"] == 11.0
        assert site["character"]["tier"] == "Momentum"
        assert site["character"]["xp_total"] == 2480.0
        assert site["character"]["level_events_count"] == 2
        assert site["character"]["days_active"] == 2  # depth of the EMA history
        assert site["character"]["challenge_bonus_xp"] == {"movement": 25}

        assert [p["name"] for p in site["pillars"]] == csl.PILLAR_ORDER
        movement = [p for p in site["pillars"] if p["name"] == "movement"][0]
        assert movement["trend"] == "up"  # positive xp_delta
        assert movement["challenge_bonus_xp"] == 25.0
        assert movement["emoji"] == "🏋️"
        assert [p["trend"] for p in site["pillars"] if p["name"] == "sleep"] == ["neutral"]

        tier_up, level_down = site["timeline"]
        assert tier_up["event"] == "Movement tier up: Momentum — zone2_minutes at 142, 5-day streak, +40 XP"
        assert tier_up["type"] == "pillar_tier_up"
        assert tier_up["character_level"] == 12.0
        # a level-DOWN keeps its raw type so the front end never celebrates it
        assert level_down["event"] == "Sleep → Level 3"
        assert level_down["type"] == "pillar_level_down"

    def test_weekly_pillar_history_groups_by_iso_week(self, wired):
        _, captured = wired

        csl.lambda_handler({"date": DATE}, None)

        history = captured["site"]["pillar_history"]
        assert [h["week_end"] for h in history] == ["2026-07-28", DATE]
        assert history[-1]["week_start"] == "2026-08-03"  # Monday of the week
        assert history[-1]["week_label"].startswith("Wk ")
        assert set(history[-1]["pillars"]) == set(csl.PILLAR_ORDER)
        assert history[0]["pillars"]["sleep"] == 45.0

    def test_site_writer_failure_never_fails_the_compute(self, monkeypatch, wired):
        def _boom(**kwargs):
            raise RuntimeError("s3 down")

        monkeypatch.setattr(site_writer, "write_character_stats", _boom)

        assert csl.lambda_handler({"date": DATE}, None)["statusCode"] == 200

    def test_pillar_history_failure_never_blocks_the_stats_write(self, monkeypatch, wired):
        table, captured = wired
        # An unparseable stored date makes the weekly rollup raise; the write
        # must still happen with an empty history rather than losing the day.
        table.store[(PREFIX + "character_sheet", "DATE#2026-07-28")]["date"] = "not-a-date"

        assert csl.lambda_handler({"date": DATE}, None)["statusCode"] == 200
        assert captured["site"]["pillar_history"] == []

    def test_a_validator_crash_does_not_block_the_write(self, monkeypatch, wired):
        table, _ = wired
        from ingestion import ingestion_validator

        def _boom(source, item, date_str):
            raise RuntimeError("schema registry unavailable")

        monkeypatch.setattr(ingestion_validator, "validate_item", _boom)

        assert csl.lambda_handler({"date": DATE}, None)["statusCode"] == 200
        assert [p for p in table.puts if p["sk"] == "DATE#" + DATE]

    def test_validation_failure_blocks_the_write(self, monkeypatch, wired):
        table, _ = wired
        from ingestion import ingestion_validator

        class _Rejected:
            should_skip_ddb = True
            errors = ["character_level out of range"]
            warnings = []

        monkeypatch.setattr(ingestion_validator, "validate_item", lambda source, item, date_str: _Rejected())

        out = csl.lambda_handler({"date": DATE}, None)

        assert out["statusCode"] == 500
        assert "Validation failed" in out["body"]
        assert [p for p in table.puts if p["sk"] == "DATE#" + DATE] == []
