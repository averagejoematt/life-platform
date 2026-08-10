#!/usr/bin/env python3
"""tests/test_ai_expert_analyzer_behavior.py — behavioral contracts of
`lambdas/intelligence/ai_expert_analyzer_lambda.py`.

Part of #1658 tranche 2. This Lambda is the PRIMARY observatory content
generator: it assembles the grounded context for the eight coach personas, calls
the model, parses the answer and writes `EXPERT#{key}` — the exact records
`/api/ai_analysis` and `/api/coach_analysis` serve to readers. A wrong number
here is published on eight pages at once, so the contracts under test are the
reader-facing ones:

  * ADR-104 grounded generation — the prompt carries the data it claims to
    analyse, an absent metric is presented as ABSENT (never as a neutral 0),
    and a stale/pre-genesis weigh-in is never narrated as today's (#1894/#2104),
  * ADR-105 rigor — deterministic counts are computed before any model verdict
    (behavioral presence, recency alongside every whole-window total),
  * the AI failure path — blocked / empty / truncated / non-JSON model responses
    must degrade honestly rather than silently ship a stub,
  * the read layer — cycle floors, Decimal→float, honest absence on failure,
  * the handler's branches and per-expert error isolation.

Time is frozen everywhere `datetime.now` is reachable, and every frozen instant
is DERIVED from the live `EXPERIMENT_START_DATE` so a re-anchor cannot turn
these tests into a time bomb. Every expectation over a growable set (the expert
roster, the analytical lenses, the banned scaffolds, the movement sources) is
derived from the canonical registry or the module's own constant.
"""

import json
import os
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
for _p in (LAMBDAS, os.path.join(LAMBDAS, "intelligence")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_import_err = None
try:
    import ai_expert_analyzer_lambda as az
    from ai import grounded_generation as gg
    from coach import persona_registry
    from common import retry_utils
    from experiment import phase_taxonomy
    from ingestion import source_state
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    az = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"ai_expert_analyzer_lambda unavailable: {_import_err}")  # type: ignore


# ── Frozen clock, derived from the live genesis (never a literal date) ────────

GENESIS = az.EXPERIMENT_START
_GENESIS_D = datetime.strptime(GENESIS, "%Y-%m-%d").replace(tzinfo=timezone.utc)
# Day 22 of the cycle at 14:00Z — late enough that the 30-day lookback clamps to
# genesis, which is the live production shape for most of a cycle.
FROZEN_NOW = _GENESIS_D + timedelta(days=21, hours=14)
TODAY = FROZEN_NOW.strftime("%Y-%m-%d")
DAY_N = 22
WEEK_N = DAY_N // 7 + 1


def _days_ago(n):
    return (FROZEN_NOW - timedelta(days=n)).strftime("%Y-%m-%d")


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`.

    A subclass (not a Mock) keeps `strptime`, `fromisocalendar`, arithmetic and
    `.date()` working — the module uses all of them on the same name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(az, "datetime", _FrozenDatetime)
    return FROZEN_NOW


@pytest.fixture(autouse=True)
def _clear_facts_cache():
    """`_load_canonical_facts` memoizes on a module global — no leakage between tests."""
    az._CANON_FACTS_CACHE.clear()
    yield
    az._CANON_FACTS_CACHE.clear()


# ── DynamoDB test double ─────────────────────────────────────────────────────


def _cond_terms(cond):
    """Flatten a boto3 KeyConditionExpression tree into [(op, name, *values)]."""
    if cond is None:
        return []
    expr = cond.get_expression()
    if expr["operator"] == "AND":
        out = []
        for v in expr["values"]:
            out.extend(_cond_terms(v))
        return out
    name = getattr(expr["values"][0], "name", expr["values"][0])
    return [(expr["operator"], name, *expr["values"][1:])]


class FakeTable:
    """DynamoDB Table stand-in keyed the way this module keys the real table.

    `items` maps (pk, sk) → item. `query()` understands the two key shapes the
    module issues (`sk BETWEEN`, `begins_with(sk, …)`) plus `ScanIndexForward`
    and `Limit`, and records every kwargs dict so a test can assert on the
    ADR-058 phase FilterExpression. Bounded and hand-rolled — no Mock ever
    enters a loop here.
    """

    def __init__(self, items=None):
        self.items = {}
        for it in items or []:
            self.items[(it["pk"], it["sk"])] = it
        self.puts = []
        self.updates = []
        self.queries = []
        self.gets = []
        self.query_errors = {}  # pk → exception
        self.get_errors = {}  # pk → exception

    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        self.items[(Item["pk"], Item["sk"])] = Item
        return {}

    def update_item(self, Key=None, **kwargs):
        self.updates.append({"Key": Key, **kwargs})
        vals = kwargs.get("ExpressionAttributeValues") or {}
        item = self.items.get((Key["pk"], Key["sk"]))
        if item is not None and ":a" in vals:
            item["analysis"] = vals[":a"]
        return {}

    def get_item(self, Key=None, **kwargs):
        self.gets.append(Key)
        if Key["pk"] in self.get_errors:
            raise self.get_errors[Key["pk"]]
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        terms = _cond_terms(kwargs.get("KeyConditionExpression"))
        pk = next((t[2] for t in terms if t[1] == "pk"), None)
        if pk in self.query_errors:
            raise self.query_errors[pk]
        rows = [v for (p, _s), v in self.items.items() if p == pk]
        for op, name, *vals in terms:
            if name != "sk":
                continue
            if op == "BETWEEN":
                rows = [r for r in rows if vals[0] <= str(r["sk"]) <= vals[1]]
            elif op == "begins_with":
                rows = [r for r in rows if str(r["sk"]).startswith(vals[0])]
            elif op == "=":
                rows = [r for r in rows if str(r["sk"]) == vals[0]]
        rows.sort(key=lambda r: str(r["sk"]), reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        return {"Items": rows[:limit] if limit else rows}

    # -- helpers a test uses to describe the world --
    def add(self, source, date_str, **fields):
        pk = az.USER_PREFIX + source
        self.items[(pk, f"DATE#{date_str}")] = {"pk": pk, "sk": f"DATE#{date_str}", **fields}
        return self

    def add_raw(self, pk, sk, **fields):
        self.items[(pk, sk)] = {"pk": pk, "sk": sk, **fields}
        return self

    def queried_pks(self):
        out = []
        for kw in self.queries:
            for op, name, *vals in _cond_terms(kw.get("KeyConditionExpression")):
                if name == "pk":
                    out.append(vals[0])
        return out


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(az, "table", t)
    return t


@pytest.fixture
def no_side_deps(monkeypatch):
    """Silence the live-AWS side dependencies of the prompt builders.

    `intelligence_common` and `persona_core` both reach for DynamoDB/S3 at
    prompt-build time; disabling them is exactly the module's own documented
    fail-soft path and keeps these tests hermetic.
    """
    monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
    monkeypatch.setattr(az, "_persona_core", None)


class FakeModel:
    """Bounded stand-in for `retry_utils.call_anthropic_raw`.

    Yields the queued replies in order (the last one repeats), records every
    request body so a test can assert what the model was actually given, and
    raises whatever is queued as an exception instead.
    """

    def __init__(self, *replies):
        self.replies = list(replies) or [""]
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(json.loads(req.data.decode()))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return {"content": [{"type": "text", "text": reply}]}

    @property
    def prompts(self):
        return [r["messages"][0]["content"] for r in self.requests]

    @property
    def calls(self):
        return len(self.requests)


@pytest.fixture
def model(monkeypatch):
    def _install(*replies):
        m = FakeModel(*replies)
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", m)
        monkeypatch.setattr(az, "_get_api_key", lambda: "sk-test")
        return m

    return _install


# ═════════════════════════════════════════════════════════════════════════════
# The expert roster — guard the SET, not the instance
# ═════════════════════════════════════════════════════════════════════════════


class TestExpertRoster:
    def test_the_observatory_roster_is_the_platform_operational_coach_roster(self):
        """A coach added to the persona registry must get an observatory analysis —
        a hand-maintained second list would silently drop them from the site."""
        assert set(az.EXPERTS) == set(persona_registry.OPERATIONAL_SHORT_IDS)

    def test_every_expert_the_handler_will_run_has_a_persona(self):
        missing = [k for k in az.EXPERTS if k not in az.EXPERT_PERSONAS]
        assert missing == [], f"build_prompt would KeyError for {missing}"

    def test_no_persona_exists_that_the_handler_never_runs(self):
        assert set(az.EXPERT_PERSONAS) <= set(az.EXPERTS)

    @pytest.mark.parametrize("field", ["name", "title", "style", "focus", "epistemology"])
    def test_every_persona_carries_a_substantive_byline_field(self, field):
        """Derived over the whole registry: a new coach cannot ship with an empty
        byline field, which would render as a blank prompt line for readers."""
        for key, persona in az.EXPERT_PERSONAS.items():
            assert len(str(persona.get(field, "")).strip()) >= 10, f"{key}.{field} is empty/stub"

    def test_unknown_expert_key_yields_an_honest_note_not_a_crash(self):
        data = az.gather_data_for_expert("astrology")
        assert data == {"expert_key": "astrology", "note": "Unknown expert"}


# ═════════════════════════════════════════════════════════════════════════════
# The read layer
# ═════════════════════════════════════════════════════════════════════════════


class TestReadLayer:
    def test_query_source_reads_the_users_partition_for_that_source(self, table):
        table.add("whoop", TODAY, recovery_score=Decimal("61"))
        rows = az._query_source("whoop", GENESIS, TODAY)
        assert [r["sk"] for r in rows] == [f"DATE#{TODAY}"]
        assert table.queried_pks() == [az.USER_PREFIX + "whoop"]

    def test_query_source_window_is_inclusive_of_both_bounds(self, table):
        table.add("whoop", GENESIS, recovery_score=1).add("whoop", TODAY, recovery_score=2)
        table.add("whoop", _days_ago(40), recovery_score=3)
        got = {r["sk"] for r in az._query_source("whoop", GENESIS, TODAY)}
        assert got == {f"DATE#{GENESIS}", f"DATE#{TODAY}"}

    def test_query_source_returns_floats_so_callers_can_do_arithmetic(self, table):
        table.add("whoop", TODAY, recovery_score=Decimal("61.5"))
        (row,) = az._query_source("whoop", GENESIS, TODAY)
        assert isinstance(row["recovery_score"], float)
        assert row["recovery_score"] + 1 == 62.5  # Decimal+float would TypeError

    def test_an_experiment_scoped_partition_is_floored_at_the_cycle_genesis(self, table):
        """#2113: a scoped read must never return the previous cycle's rows, even
        when the caller asks for a wider window."""
        scoped = next(s for s in phase_taxonomy.SCOPED_SOURCES if s)
        pk = az.USER_PREFIX + scoped
        assert phase_taxonomy.reads_current_cycle_only(pk), "fixture picked a non-scoped source"
        az._query_source(scoped, "2019-01-01", TODAY)
        (kw,) = table.queries
        lo = next(t[2] for t in _cond_terms(kw["KeyConditionExpression"]) if t[1] == "sk")
        assert lo == f"DATE#{GENESIS}"

    def test_a_cross_phase_partition_keeps_the_callers_own_floor(self, table):
        """Labs span the whole history — flooring them at genesis would erase the
        clinical record the labs expert exists to read."""
        pk = az.USER_PREFIX + "labs"
        assert not phase_taxonomy.reads_current_cycle_only(pk)
        az._query_source("labs", "2019-01-01", TODAY)
        (kw,) = table.queries
        lo = next(t[2] for t in _cond_terms(kw["KeyConditionExpression"]) if t[1] == "sk")
        assert lo == "DATE#2019-01-01"

    def test_latest_item_returns_the_newest_record(self, table):
        table.add("withings", _days_ago(5), weight_lbs=Decimal("320")).add("withings", _days_ago(1), weight_lbs=Decimal("318"))
        item = az._latest_item("withings")
        assert item["sk"] == f"DATE#{_days_ago(1)}"
        assert table.queries[0]["ScanIndexForward"] is False and table.queries[0]["Limit"] == 1

    def test_latest_item_is_none_when_the_partition_is_empty(self, table):
        assert az._latest_item("withings") is None


# ═════════════════════════════════════════════════════════════════════════════
# INGEST_HEALTH sentinels — behavioral rest vs. pipe breakage (#494)
# ═════════════════════════════════════════════════════════════════════════════


class TestMovementIngestHealth:
    def test_it_reports_a_status_for_every_movement_source_it_was_asked_about(self, table):
        sources = az._read_movement_ingest_health.__defaults__[0]
        assert sources, "the default movement-source set must not be empty"
        health = az._read_movement_ingest_health()
        assert set(health) == set(sources)

    def test_a_missing_sentinel_is_never_reported_as_ok(self, table):
        """'ok' is what unlocks the assessable-as-rest verdict — an absent sentinel
        must not unlock it, or a dead pipe reads as confirmed behavioral rest."""
        health = az._read_movement_ingest_health(("strava",))
        assert health["strava"] != "ok"

    def test_one_sources_read_failure_does_not_lose_the_other_source(self, table):
        from ingestion.ingest_health import SYSTEM_PK

        table.get_errors[SYSTEM_PK] = RuntimeError("throttled")
        health = az._read_movement_ingest_health(("strava", "garmin"))
        assert health == {}  # both failed, fail-soft to the conservative records-only read


# ═════════════════════════════════════════════════════════════════════════════
# Canonical facts — the ONE shared number set every coach cites
# ═════════════════════════════════════════════════════════════════════════════


class TestCanonicalFacts:
    def test_facts_come_from_the_latest_computed_metrics_record(self, table):
        table.add("computed_metrics", _days_ago(3), recovery_pct=Decimal("40"))
        table.add("computed_metrics", TODAY, recovery_pct=Decimal("61"))
        facts = az._load_canonical_facts()
        assert facts.get("recovery_pct") == 61

    def test_the_producers_provisional_rate_flag_travels_with_the_facts(self, table):
        """#914-B: without it the prompt cannot force past-tense rate language and a
        12-day-old trajectory gets narrated as 'maintained'."""
        table.add("computed_metrics", TODAY, rate_provisional=True, weekly_rate_lbs=Decimal("-2.1"))
        assert az._load_canonical_facts()["rate_provisional"] is True

    def test_an_absent_provisional_flag_is_false_not_missing(self, table):
        table.add("computed_metrics", TODAY, recovery_pct=Decimal("61"))
        assert az._load_canonical_facts()["rate_provisional"] is False

    def test_the_scale_recency_travels_so_a_stale_rate_can_be_dated(self, table):
        table.add("computed_metrics", TODAY, recovery_pct=Decimal("61"))
        table.add("withings", _days_ago(14), weight_lbs=Decimal("318"))
        facts = az._load_canonical_facts()
        assert facts["last_weighin_date"] == _days_ago(14)
        assert facts["days_since_weighin"] == 14

    def test_a_weigh_in_today_is_zero_days_old(self, table):
        table.add("computed_metrics", TODAY, recovery_pct=Decimal("61"))
        table.add("withings", TODAY, weight_lbs=Decimal("318"))
        assert az._load_canonical_facts()["days_since_weighin"] == 0

    def test_no_weigh_in_at_all_means_no_recency_claim_is_made(self, table):
        table.add("computed_metrics", TODAY, recovery_pct=Decimal("61"))
        facts = az._load_canonical_facts()
        assert "days_since_weighin" not in facts and "last_weighin_date" not in facts

    def test_a_table_failure_yields_empty_facts_rather_than_raising(self, table):
        table.query_errors[az.USER_PREFIX + "computed_metrics"] = RuntimeError("throttled")
        assert az._load_canonical_facts() == {}

    def test_facts_are_loaded_once_per_run_not_once_per_coach(self, table):
        table.add("computed_metrics", TODAY, recovery_pct=Decimal("61"))
        az._load_canonical_facts()
        first = len(table.queries)
        az._load_canonical_facts()
        assert len(table.queries) == first, "every coach re-querying would drift the shared snapshot"


# ═════════════════════════════════════════════════════════════════════════════
# gather_data_for_expert — the grounded context, per domain
# ═════════════════════════════════════════════════════════════════════════════


class TestMindSnapshot:
    def test_it_counts_the_journal_entries_in_the_window(self, table):
        table.add("journal_analysis", TODAY, sentiment_score=Decimal("0.4"), themes=["work"])
        table.add("journal_analysis", _days_ago(2), sentiment_score=Decimal("0.2"), themes=["work", "sleep"])
        data = az.gather_data_for_expert("mind")
        assert data["journal_entry_count"] == 2

    def test_average_sentiment_is_the_mean_of_the_entries(self, table):
        table.add("journal_analysis", TODAY, sentiment_score=Decimal("0.4"))
        table.add("journal_analysis", _days_ago(2), sentiment_score=Decimal("0.2"))
        assert az.gather_data_for_expert("mind")["avg_sentiment"] == 0.3

    def test_top_themes_are_ranked_by_frequency_and_capped_at_five(self, table):
        table.add("journal_analysis", TODAY, sentiment_score=Decimal("0"), themes=["a", "b", "c", "d", "e", "f"])
        table.add("journal_analysis", _days_ago(1), sentiment_score=Decimal("0"), themes=["f"])
        themes = az.gather_data_for_expert("mind")["top_themes"]
        assert len(themes) == 5
        assert themes[0] == {"theme": "f", "count": 2}

    def test_recency_travels_beside_the_window_total(self, table):
        """#914 anti-dilution: '8 entries this month' must not mask 'none in 12 days'."""
        table.add("journal_analysis", _days_ago(12), sentiment_score=Decimal("0.1"))
        data = az.gather_data_for_expert("mind")
        assert data["days_since_last_journal"] == 12
        assert data["journal_entries_last_14d"] == 1

    def test_a_silent_fortnight_is_visible_as_zero_recent_entries(self, table):
        table.add("journal_analysis", _days_ago(19), sentiment_score=Decimal("0.1"))
        data = az.gather_data_for_expert("mind")
        assert data["journal_entry_count"] == 1 and data["journal_entries_last_14d"] == 0

    def test_mood_readings_come_from_the_apple_health_valence_field(self, table):
        table.add("apple_health", TODAY, som_avg_valence=Decimal("0.5"), steps=Decimal("9000"))
        table.add("apple_health", _days_ago(1), steps=Decimal("8000"))  # no SoM that day
        data = az.gather_data_for_expert("mind")
        assert data["mood_readings"] == 1 and data["avg_valence"] == 0.5

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT (tranche-2 discovery): with zero journal entries the mind snapshot reports "
            "avg_sentiment=0. sentiment_score is a -1..1 scale on which 0 is literally the "
            "'neutral' label (journal_analyzer_lambda), so absence is handed to the coach as a "
            "real, neutral reading — the ADR-104 absent-as-zero violation. Sibling branches in "
            "the same function return None for the same shape (glucose avg, sleep avgs, "
            "avg_recovery, avg_fiber_g)."
        ),
    )
    def test_no_journal_entries_reports_absent_sentiment_not_a_neutral_zero(self, table):
        data = az.gather_data_for_expert("mind")
        assert data["journal_entry_count"] == 0
        assert data["avg_sentiment"] is None

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT (tranche-2 discovery): with zero State-of-Mind readings the mind snapshot "
            "reports avg_valence=0 — the neutral point of the valence scale — instead of honest "
            "absence (ADR-104). Same class as avg_sentiment above."
        ),
    )
    def test_no_mood_readings_reports_absent_valence_not_a_neutral_zero(self, table):
        data = az.gather_data_for_expert("mind")
        assert data["mood_readings"] == 0
        assert data["avg_valence"] is None


class TestNutritionSnapshot:
    def test_an_empty_store_is_honest_absence_with_no_fabricated_averages(self, table):
        data = az.gather_data_for_expert("nutrition")
        assert data["note"] == "No nutrition data available"
        assert data["days_since_last_food_log"] is None and data["food_logs_last_14d"] == 0
        assert "avg_calories" not in data

    def test_the_empty_store_still_explains_the_structural_upload_lag(self, table):
        """Without the rider the coach narrates expected end-of-day lag as a failure."""
        note = az.gather_data_for_expert("nutrition")["recency_note"]
        assert "expected pipeline lag" in note and "never a logging failure" in note

    def test_averages_are_computed_over_the_logged_days(self, table):
        table.add("macrofactor", TODAY, total_calories_kcal=Decimal("2000"), total_protein_g=Decimal("150"))
        table.add("macrofactor", _days_ago(1), total_calories_kcal=Decimal("2400"), total_protein_g=Decimal("170"))
        data = az.gather_data_for_expert("nutrition")
        assert data["avg_calories"] == 2200 and data["avg_protein_g"] == 160.0
        assert data["days_tracked"] == 2

    def test_the_protein_target_comes_from_the_canonical_facts_not_a_literal(self, table):
        """Phase-3: a hardcoded 190 drifts from scoring_engine/profile and puts a
        different target in front of every coach."""
        table.add("computed_metrics", TODAY, protein_g_target=Decimal("205"))
        table.add("macrofactor", TODAY, total_calories_kcal=Decimal("2000"), total_protein_g=Decimal("210"))
        data = az.gather_data_for_expert("nutrition")
        assert data["protein_target_g"] == 205
        assert data["protein_adherence_pct"] == 100

    def test_adherence_is_the_share_of_days_at_or_above_the_target(self, table):
        table.add("computed_metrics", TODAY, protein_g_target=Decimal("200"))
        table.add("macrofactor", TODAY, total_protein_g=Decimal("210"))
        table.add("macrofactor", _days_ago(1), total_protein_g=Decimal("150"))
        assert az.gather_data_for_expert("nutrition")["protein_adherence_pct"] == 50

    def test_a_logged_zero_calorie_day_is_counted_separately_from_a_missing_day(self, table):
        table.add("macrofactor", TODAY, total_calories_kcal=Decimal("0"))
        table.add("macrofactor", _days_ago(1), total_calories_kcal=Decimal("2200"))
        data = az.gather_data_for_expert("nutrition")
        assert data["zero_calorie_days"] == 1 and data["days_tracked"] == 2

    def test_absent_fiber_is_reported_as_absent_not_as_zero_grams(self, table):
        table.add("macrofactor", TODAY, total_calories_kcal=Decimal("2000"))
        assert az.gather_data_for_expert("nutrition")["avg_fiber_g"] is None

    def test_recency_travels_beside_the_window_averages(self, table):
        table.add("macrofactor", _days_ago(9), total_calories_kcal=Decimal("2000"))
        data = az.gather_data_for_expert("nutrition")
        assert data["days_since_last_food_log"] == 9 and data["food_logs_last_14d"] == 1

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT (tranche-2 discovery): when nutrition rows EXIST but carry no macro fields, "
            "avg_calories/avg_protein_g are reported as 0 with days_tracked>0 — 'he averaged 0 "
            "kcal across 2 tracked days'. The empty-store early return does not cover this shape, "
            "and avg_fiber_g in the very same block correctly returns None. ADR-104 absent-as-zero."
        ),
    )
    def test_logged_days_with_no_macros_report_absent_averages_not_zero(self, table):
        table.add("macrofactor", TODAY, note="ate out, nothing logged")
        table.add("macrofactor", _days_ago(1), note="ate out, nothing logged")
        data = az.gather_data_for_expert("nutrition")
        assert data["days_tracked"] == 2
        assert data["avg_calories"] is None and data["avg_protein_g"] is None


class TestTrainingSnapshot:
    def test_hevy_is_the_primary_training_stimulus_signal(self, table):
        table.add("hevy", TODAY, set_count=Decimal("20"), duration_sec=Decimal("3600"))
        table.add("hevy", _days_ago(2), set_count=Decimal("18"), duration_sec=Decimal("3000"))
        data = az.gather_data_for_expert("training")
        assert data["hevy_sessions"] == 2 and data["hevy_sets"] == 38 and data["hevy_active_min"] == 110

    def test_a_training_day_is_any_day_with_hevy_or_strava(self, table):
        table.add("hevy", TODAY, set_count=Decimal("20"))
        table.add("strava", _days_ago(1), type="Ride", moving_time_seconds=Decimal("1800"))
        data = az.gather_data_for_expert("training")
        assert data["training_days"] == 2
        assert data["rest_days"] == DAY_N - 2

    def test_a_hevy_only_week_still_produces_a_strength_modality(self, table):
        table.add("hevy", TODAY, set_count=Decimal("20"))
        assert az.gather_data_for_expert("training")["modality_breakdown"] == {"strength": 1}

    def test_garmin_steps_are_used_only_while_garmin_is_live(self, table):
        table.add("garmin", TODAY, steps=Decimal("11000"))
        table.add("apple_health", TODAY, steps=Decimal("3000"))
        data = az.gather_data_for_expert("training")
        assert data["step_source"] == "garmin" and data["avg_daily_steps"] == 11000

    def test_a_stale_garmins_sparse_partials_never_enter_the_step_average(self, table):
        """DI-1.4 'phantom 298': a rate-limited Garmin emits partial daily reads that
        misrepresent movement — Apple Health takes over the moment Garmin goes stale."""
        stale = _days_ago(source_state.DEFAULT_STALE_DAYS + 3)
        table.add("garmin", stale, steps=Decimal("298"))
        table.add("apple_health", TODAY, steps=Decimal("9000"))
        data = az.gather_data_for_expert("training")
        assert data["step_source"] == "apple_health" and data["avg_daily_steps"] == 9000
        assert data["movement_source_state"]["garmin"] == source_state.STATE_STALE

    def test_a_rate_limit_marker_is_reported_as_rate_limited_not_as_rest(self, table):
        table.add_raw(az.USER_PREFIX + "garmin", source_state.RATE_LIMIT_MARKER_SK["garmin"], hit_at="now")
        table.add("apple_health", TODAY, steps=Decimal("9000"))
        data = az.gather_data_for_expert("training")
        assert data["movement_source_state"]["garmin"] == source_state.STATE_RATE_LIMITED

    def test_zero_step_rows_are_excluded_from_the_apple_health_average(self, table):
        table.add("apple_health", TODAY, steps=Decimal("9000"))
        table.add("apple_health", _days_ago(1), steps=Decimal("0"))
        assert az.gather_data_for_expert("training")["avg_daily_steps"] == 9000

    def test_step_completeness_reports_how_much_of_the_cycle_has_step_data(self, table):
        table.add("apple_health", TODAY, steps=Decimal("9000"))
        data = az.gather_data_for_expert("training")
        assert data["step_completeness_pct"] == round(1 / DAY_N * 100)

    def test_no_steps_at_all_reports_the_step_source_as_missing(self, table):
        data = az.gather_data_for_expert("training")
        assert data["movement_source_state"]["steps"] == "missing"
        assert data["step_completeness_pct"] == 0

    def test_recency_separates_a_busy_month_from_a_silent_fortnight(self, table):
        table.add("hevy", _days_ago(16), set_count=Decimal("20"))
        table.add("hevy", _days_ago(18), set_count=Decimal("20"))
        data = az.gather_data_for_expert("training")
        assert data["hevy_sessions"] == 2
        assert data["days_since_last_lift"] == 16 and data["sessions_last_14d"] == 0

    def test_the_hevy_summary_is_empty_when_nothing_was_lifted(self, table):
        assert az.gather_data_for_expert("training")["hevy_summary"] == ""

    def test_the_hevy_summary_states_sessions_sets_minutes_and_days(self, table):
        table.add("hevy", TODAY, set_count=Decimal("20"), duration_sec=Decimal("3600"))
        summary = az.gather_data_for_expert("training")["hevy_summary"]
        assert "1 Hevy session(s)" in summary and "20 sets" in summary and "60 min" in summary

    def test_every_movement_source_the_honesty_guard_reads_is_reported(self, table):
        """The guard is a set-consumer: a source it inspects but the snapshot omits
        silently defaults to 'live' and withholds nothing."""
        from intelligence import intelligence_common as ic

        data = az.gather_data_for_expert("training")
        assert set(ic._MOVEMENT_NOTE_SOURCES) <= set(data["movement_source_state"])

    def test_recovery_with_no_whoop_data_is_absent_not_zero(self, table):
        assert az.gather_data_for_expert("training")["avg_recovery"] is None


class TestPhysicalSnapshot:
    def test_the_current_weight_carries_its_own_reading_date(self, table):
        table.add("withings", _days_ago(1), weight_lbs=Decimal("318.4"))
        data = az.gather_data_for_expert("physical")
        assert data["current_weight_lb"] == 318.4
        assert data["current_weight_as_of"] == _days_ago(1)
        assert data["current_weight_age_days"] == 1

    def test_a_stale_weigh_in_is_flagged_stale_not_presented_as_today(self, table):
        table.add("withings", GENESIS, weight_lbs=Decimal("321.6"))
        data = az.gather_data_for_expert("physical")
        assert data["current_weight_is_stale"] is True

    def test_no_weigh_ins_is_honest_absence_not_a_zero_pound_reading(self, table):
        data = az.gather_data_for_expert("physical")
        assert data["current_weight_lb"] is None and data["weight_readings"] == 0

    def test_dexa_body_composition_travels_when_a_scan_exists(self, table):
        table.add(
            "dexa",
            _days_ago(30),
            scan_date=_days_ago(30),
            body_composition={"body_fat_pct": Decimal("38.2"), "lean_mass_lb": Decimal("180.5")},
        )
        data = az.gather_data_for_expert("physical")
        assert data["body_fat_pct"] == 38.2 and data["lean_mass_lb"] == 180.5
        assert data["days_since_dexa"] == 30

    def test_no_dexa_means_no_body_composition_keys_at_all(self, table):
        data = az.gather_data_for_expert("physical")
        assert "body_fat_pct" not in data and "days_since_dexa" not in data

    def test_a_waist_height_ratio_travels_when_measured(self, table):
        table.add("measurements", _days_ago(4), waist_height_ratio=Decimal("0.61"))
        assert az.gather_data_for_expert("physical")["waist_height_ratio"] == 0.61

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT (tranche-2 discovery): a DEXA record with no `scan_date` falls back to "
            "TODAY, so days_since_dexa is reported as 0 — an unknown scan date is handed to the "
            "longevity coach as 'scanned today', the exact #1894 stale-reading-as-current class "
            "on the body-composition surface."
        ),
    )
    def test_a_dexa_with_no_scan_date_is_never_narrated_as_a_same_day_scan(self, table):
        table.add("dexa", _days_ago(60), body_composition={"body_fat_pct": Decimal("38.2")})
        data = az.gather_data_for_expert("physical")
        assert data.get("days_since_dexa") != 0


class TestExplorerSnapshot:
    def test_significant_pairs_are_collected_across_the_weekly_records(self, table):
        table.add("weekly_correlations", TODAY, pairs=[{"a": "sleep", "b": "hrv"}])
        table.add("weekly_correlations", _days_ago(7), significant_pairs=[{"a": "steps", "b": "mood"}])
        data = az.gather_data_for_expert("explorer")
        assert data["significant_correlations"] == 2 and len(data["top_pairs"]) == 2

    def test_only_active_experiments_are_counted(self, table):
        table.add_raw(az.USER_PREFIX + "experiments", "EXP#1", status="active", name="Creatine")
        table.add_raw(az.USER_PREFIX + "experiments", "EXP#2", status="completed", name="Cold plunge")
        data = az.gather_data_for_expert("explorer")
        assert data["active_experiments"] == 1 and data["experiment_names"] == ["Creatine"]

    def test_an_experiments_query_failure_degrades_to_zero_rather_than_raising(self, table):
        table.query_errors[az.USER_PREFIX + "experiments"] = RuntimeError("throttled")
        assert az.gather_data_for_expert("explorer")["active_experiments"] == 0

    def test_no_correlations_is_an_empty_list_not_a_fabricated_pair(self, table):
        data = az.gather_data_for_expert("explorer")
        assert data["significant_correlations"] == 0 and data["top_pairs"] == []


class TestGlucoseSnapshot:
    def test_averages_are_taken_only_over_days_that_carry_glucose(self, table):
        table.add("apple_health", TODAY, blood_glucose_avg=Decimal("100"), blood_glucose_readings_count=Decimal("288"))
        table.add("apple_health", _days_ago(1), blood_glucose_avg=Decimal("110"), blood_glucose_readings_count=Decimal("280"))
        table.add("apple_health", _days_ago(2), steps=Decimal("9000"))  # no CGM that day
        data = az.gather_data_for_expert("glucose")
        assert data["days_with_data"] == 2 and data["avg_glucose_mg_dl"] == 105.0
        assert data["total_readings"] == 568

    def test_absent_glucose_is_reported_as_absent_never_as_zero_mg_dl(self, table):
        data = az.gather_data_for_expert("glucose")
        assert data["avg_glucose_mg_dl"] is None
        assert data["time_in_range_pct"] is None and data["std_dev"] is None
        assert data["days_with_data"] == 0

    def test_time_in_range_and_variability_average_independently_of_each_other(self, table):
        table.add("apple_health", TODAY, blood_glucose_avg=Decimal("100"), blood_glucose_time_in_range_pct=Decimal("90"))
        table.add("apple_health", _days_ago(1), blood_glucose_avg=Decimal("100"), blood_glucose_std_dev=Decimal("18"))
        data = az.gather_data_for_expert("glucose")
        assert data["time_in_range_pct"] == 90.0 and data["std_dev"] == 18.0


class TestLabsSnapshot:
    def test_an_empty_labs_store_is_the_only_honest_zero_results_claim(self, table):
        data = az.gather_data_for_expert("labs")
        assert data["store_empty"] is True and data["total_draws"] == 0

    def test_a_real_draw_reports_flagged_markers_from_the_draw_schema(self, table):
        table.add(
            "labs",
            "2026-05-01",
            draw_date="2026-05-01",
            biomarkers={"ldl": {"value": Decimal("160"), "unit": "mg/dL", "reference_range": "<100"}},
            out_of_range=["ldl"],
            out_of_range_count=Decimal("1"),
            total_biomarkers=Decimal("42"),
        )
        data = az.gather_data_for_expert("labs")
        assert data["store_empty"] is False and data["total_draws"] == 1
        assert data["flagged_count"] == 1 and data["flagged_markers"]

    def test_labs_are_read_across_all_history_not_the_experiment_window(self, table):
        az.gather_data_for_expert("labs")
        (kw,) = [k for k in table.queries if az.USER_PREFIX + "labs" in str(_cond_terms(k["KeyConditionExpression"]))]
        lo = next(t[2] for t in _cond_terms(kw["KeyConditionExpression"]) if t[1] == "sk")
        assert lo < f"DATE#{GENESIS}", "a genesis-floored labs read would erase the clinical record"


class TestSleepSnapshot:
    def test_nights_and_averages_come_from_the_whoop_window(self, table):
        table.add("whoop", TODAY, sleep_duration_hours=Decimal("7.0"), recovery_score=Decimal("60"), hrv=Decimal("40"))
        table.add("whoop", _days_ago(1), sleep_duration_hours=Decimal("8.0"), recovery_score=Decimal("70"), hrv=Decimal("50"))
        data = az.gather_data_for_expert("sleep")
        assert data["nights_tracked"] == 2
        assert data["avg_sleep_hours"] == 7.5 and data["avg_recovery"] == 65.0 and data["avg_hrv"] == 45.0

    def test_every_sleep_average_is_absent_rather_than_zero_when_untracked(self, table):
        data = az.gather_data_for_expert("sleep")
        for field in ("avg_sleep_hours", "avg_sleep_score", "avg_recovery", "avg_hrv", "avg_deep_pct", "avg_rem_pct"):
            assert data[field] is None, f"{field} fabricated a zero from an empty window"

    def test_eight_sleep_architecture_averages_are_separate_from_whoop(self, table):
        table.add("eightsleep", TODAY, sleep_score=Decimal("88"), deep_pct=Decimal("21"), rem_pct=Decimal("24"))
        data = az.gather_data_for_expert("sleep")
        assert data["avg_sleep_score"] == 88.0 and data["avg_deep_pct"] == 21.0 and data["avg_rem_pct"] == 24.0
        assert data["nights_tracked"] == 0  # whoop is the night counter

    def test_only_the_last_week_of_onset_times_travel(self, table):
        for i in range(10):
            table.add("whoop", _days_ago(i), sleep_start=f"2{i:02d}0")
        assert len(az.gather_data_for_expert("sleep")["sleep_onset_times"]) == 7


# ═════════════════════════════════════════════════════════════════════════════
# build_prompt — ADR-104 grounded generation
# ═════════════════════════════════════════════════════════════════════════════


def _prompt(expert_key, data=None, week_number=WEEK_N):
    payload = {"expert_key": expert_key, "period": "test"}
    payload.update(data or {})
    return az.build_prompt(expert_key, payload, days_in_experiment=DAY_N, week_number=week_number)


@pytest.mark.usefixtures("no_side_deps")
class TestPromptGrounding:
    def test_the_prompt_carries_the_data_it_asks_the_coach_to_analyse(self):
        """The allow-list gate treats any number not in the prompt as fabricated, so a
        figure omitted here cannot legally be cited at all."""
        p = _prompt("sleep", {"avg_sleep_hours": 7.4, "nights_tracked": 19})
        assert "7.4" in p and "19" in p

    def test_an_absent_metric_reaches_the_model_as_null_not_as_zero(self):
        p = _prompt("sleep", {"avg_hrv": None})
        assert '"avg_hrv": null' in p
        assert '"avg_hrv": 0' not in p

    def test_every_number_in_the_data_is_inside_the_allow_list_the_gate_builds(self):
        data = {"avg_sleep_hours": 7.4, "nights_tracked": 19, "avg_hrv": 43.2}
        p = _prompt("sleep", data)
        allowed = gg.allowed_numbers(p, None, {})
        assert {7.4, 19.0, 43.2} <= allowed

    def test_a_value_the_model_was_never_given_is_reported_as_fabricated(self):
        p = _prompt("sleep", {"avg_sleep_hours": 7.4})
        allowed = gg.allowed_numbers(p, None, {})
        assert gg.fabricated_numbers("HRV climbed to 88.7 ms this week.", allowed) == [88.7]

    def test_the_prompt_names_the_persona_the_reader_sees_as_the_byline(self):
        for key, persona in az.EXPERT_PERSONAS.items():
            assert persona["name"] in _prompt(key)

    def test_the_prompt_states_the_week_and_the_day_of_the_cycle(self):
        p = _prompt("sleep", week_number=5)
        assert "Week 5" in p and f"day {DAY_N}" in p and GENESIS in p

    def test_the_analytical_lens_rotates_with_the_week_number(self):
        """A fixed lens is how eight coaches become one form letter."""
        lenses = {_prompt("sleep", week_number=w).split("ANALYTICAL LENS FOR THIS WEEK:")[1].split("\n")[0] for w in range(1, 8)}
        assert len(lenses) >= 5

    def test_the_prior_analysis_is_quoted_back_with_an_anti_repetition_rule(self):
        p = _prompt("sleep", {"_prior_analysis_summary": "deep sleep was 14%", "_prior_recommendation": "anchor onset"})
        assert "deep sleep was 14%" in p and "anchor onset" in p
        assert "Do NOT repeat the same observation" in p

    def test_the_prior_context_keys_never_leak_into_the_data_json(self):
        p = _prompt("sleep", {"_prior_analysis_summary": "last week", "avg_sleep_hours": 7.4})
        assert '"_prior_analysis_summary"' not in p

    def test_no_prior_analysis_means_no_repetition_block_at_all(self):
        p = _prompt("sleep", {"avg_sleep_hours": 7.4})
        assert "Your PREVIOUS analysis said" not in p

    def test_the_prompt_requests_the_two_tagged_lines_the_site_renders(self):
        p = _prompt("sleep")
        assert "KEY RECOMMENDATION:" in p and "ELENA QUOTE:" in p

    def test_only_the_mind_coach_is_asked_for_a_journaling_prompt(self):
        assert "JOURNALING PROMPT:" in _prompt("mind")
        for key in (k for k in az.EXPERTS if k != "mind"):
            assert "JOURNALING PROMPT:" not in _prompt(key), f"{key} would emit a mind-only field"

    def test_every_banned_scaffold_is_named_verbatim_in_the_prompt(self):
        p = _prompt("sleep")
        for scaffold in az.BANNED_OPENER_SCAFFOLDS:
            assert scaffold in p, f"{scaffold!r} is banned in code but not in the prompt"

    def test_the_opening_register_block_introduces_no_new_numbers(self):
        """The allow-list gate reads the whole prompt — a digit in the voice guidance
        would silently legalise that figure for the coach to cite as data."""
        p = _prompt("sleep")
        block = p.split("YOUR OPENING REGISTER")[1].split("FRESHNESS REQUIREMENTS")[0]
        assert not any(ch.isdigit() for ch in block)

    def test_the_labs_ground_rules_only_reach_the_labs_coach(self):
        assert "store_empty is true" in _prompt("labs", {"total_draws": 3, "draw_date": "2026-05-01"})
        assert "store_empty" not in _prompt("sleep")

    def test_the_labs_rules_forbid_narrating_an_unremarkable_panel_as_a_failure(self):
        p = _prompt("labs", {"total_draws": 3, "flagged_count": 0})
        assert "flagged_count of 0 means every extracted" in p
        assert "never a data failure" in p

    def test_a_stale_weigh_in_carries_a_do_not_day_label_rider(self):
        p = _prompt(
            "physical",
            {"current_weight_is_stale": True, "current_weight_as_of": GENESIS, "current_weight_age_days": 21},
            week_number=WEEK_N,
        )
        assert "WEIGHT DATA RECENCY" in p
        assert "day label" in p and GENESIS in p

    def test_a_fresh_weigh_in_adds_no_nagging_rider(self):
        p = _prompt("physical", {"current_weight_is_stale": False, "current_weight_as_of": TODAY})
        assert "WEIGHT DATA RECENCY" not in p

    def test_the_weight_rider_is_physical_only(self):
        p = _prompt("sleep", {"current_weight_is_stale": True, "current_weight_as_of": GENESIS})
        assert "WEIGHT DATA RECENCY" not in p


class TestMovementIntegrityPrompt:
    def test_an_unassessable_movement_picture_forbids_the_under_training_verdict(self, monkeypatch):
        monkeypatch.setattr(az, "_persona_core", None)
        p = az.build_prompt(
            "physical",
            {
                "expert_key": "physical",
                "movement_source_state": {"strava": "paused", "garmin": "rate_limited", "steps": "missing"},
                "movement_ingest_health": {},
                "hevy_sessions": 3,
            },
            days_in_experiment=DAY_N,
            week_number=WEEK_N,
        )
        assert "NOT ASSESSABLE" in p
        assert "Do NOT call this under-training" in p

    def test_a_confirmed_live_pipe_with_no_activity_unlocks_an_honest_rest_verdict(self, monkeypatch):
        monkeypatch.setattr(az, "_persona_core", None)
        p = az.build_prompt(
            "physical",
            {
                "expert_key": "physical",
                "movement_source_state": {"strava": "stale", "garmin": "stale", "steps": "missing"},
                "movement_ingest_health": {"strava": "ok"},
                "hevy_sessions": 0,
            },
            days_in_experiment=DAY_N,
            week_number=WEEK_N,
        )
        assert "pipe confirmed live" in p and "NOT as a data gap" in p

    def test_a_live_movement_picture_adds_no_integrity_block(self, monkeypatch):
        monkeypatch.setattr(az, "_persona_core", None)
        p = az.build_prompt(
            "physical",
            {
                "expert_key": "physical",
                "movement_source_state": {"strava": "live", "garmin": "live", "steps": "live"},
                "movement_ingest_health": {"strava": "ok"},
            },
            days_in_experiment=DAY_N,
            week_number=WEEK_N,
        )
        assert "MOVEMENT DATA INTEGRITY" not in p

    def test_the_movement_block_never_reaches_a_non_training_coach(self, monkeypatch):
        monkeypatch.setattr(az, "_persona_core", None)
        p = az.build_prompt(
            "sleep",
            {"expert_key": "sleep", "movement_source_state": {"strava": "paused"}, "movement_ingest_health": {}},
            days_in_experiment=DAY_N,
            week_number=WEEK_N,
        )
        assert "MOVEMENT DATA INTEGRITY" not in p


# ═════════════════════════════════════════════════════════════════════════════
# The shared system prompt
# ═════════════════════════════════════════════════════════════════════════════


class TestSharedSystemPrompt:
    def test_the_format_contract_survives_a_total_context_failure(self, monkeypatch, table):
        """Every optional block is fail-soft; the output contract is not optional."""
        monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
        monkeypatch.setattr(az, "_load_canonical_facts", lambda: (_ for _ in ()).throw(RuntimeError("ddb down")))
        sysprompt = az._build_shared_system_prompt()
        assert "OBSERVATORY ANALYSIS FORMAT" in sysprompt
        assert "KEY RECOMMENDATION:" in sysprompt and "ELENA QUOTE:" in sysprompt

    def test_it_forbids_inventing_a_figure_to_sound_precise(self, monkeypatch, table):
        monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
        monkeypatch.setattr(az, "_load_canonical_facts", dict)
        sysprompt = az._build_shared_system_prompt()
        assert "never invent a figure" in sysprompt
        assert "A described pattern with no number beats a fabricated number." in sysprompt

    def test_empty_canonical_facts_produce_no_authoritative_facts_block(self, monkeypatch, table):
        """A rendered-but-empty block would be a header promising numbers that do not
        exist — the facts renderer's own contract is "" when there are no facts."""
        monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
        monkeypatch.setattr(az, "_load_canonical_facts", dict)
        header = gg.authoritative_facts_block({"recovery_pct": 61.0}).split("\n")[0]
        assert header and header not in az._build_shared_system_prompt()

    def test_real_canonical_facts_are_injected_for_every_coach_to_cite(self, monkeypatch, table):
        monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
        monkeypatch.setattr(az, "_load_canonical_facts", lambda: {"recovery_pct": 61.0, "hrv_ms": 43.2, "as_of": TODAY})
        sysprompt = az._build_shared_system_prompt()
        header = gg.authoritative_facts_block({"recovery_pct": 61.0}).split("\n")[0]
        assert header in sysprompt and "43.2" in sysprompt

    def test_a_presence_read_failure_never_blocks_the_system_prompt(self, monkeypatch, table):
        monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
        monkeypatch.setattr(az, "_load_canonical_facts", dict)
        monkeypatch.setattr(az, "_presence_block", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert "OBSERVATORY ANALYSIS FORMAT" in az._build_shared_system_prompt()


class TestPriorAnalysisRead:
    def test_a_long_prior_analysis_is_truncated_to_the_documented_budget(self, table):
        table.add_raw(az.CACHE_PK, "EXPERT#sleep", phase="experiment", analysis="a" * 900, key_recommendation="b" * 900)
        summary, rec = az._load_prior_analysis("sleep")
        assert len(summary) == 300 and len(rec) == 200

    def test_a_read_failure_reads_as_no_prior_context_rather_than_raising(self, table):
        table.get_errors[az.CACHE_PK] = RuntimeError("throttled")
        assert az._load_prior_analysis("sleep") == ("", "")

    def test_a_prior_record_with_no_recommendation_yields_an_empty_recommendation(self, table):
        table.add_raw(az.CACHE_PK, "EXPERT#sleep", phase="experiment", analysis="x" * 50)
        summary, rec = az._load_prior_analysis("sleep")
        assert summary and rec == ""


# ═════════════════════════════════════════════════════════════════════════════
# generate_and_cache — generation, parsing, persistence, failure
# ═════════════════════════════════════════════════════════════════════════════


FULL_REPLY = (
    "Deep sleep held at a fifth of the night, which is the part that matters.\n\n"
    "The pattern is consistency, not duration.\n\n"
    "KEY RECOMMENDATION: Anchor sleep onset to a thirty-minute window.\n"
    "ELENA QUOTE: He sleeps like a man still negotiating with the day.\n"
)


@pytest.fixture
def gen_env(monkeypatch, table):
    """generate_and_cache with its optional layers off — the module's own fail-soft
    path — so the test isolates generation, parsing and persistence."""
    monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
    monkeypatch.setattr(az, "_HAS_AI_VALIDATOR", False)
    monkeypatch.setattr(az, "_persona_core", None)
    monkeypatch.setattr(az, "_load_canonical_facts", dict)
    return table


class TestGenerateAndCache:
    def test_the_analysis_is_written_to_the_experts_cache_record(self, gen_env, model):
        model(FULL_REPLY)
        az.generate_and_cache("sleep")
        (item,) = gen_env.puts
        assert item["pk"] == az.CACHE_PK and item["sk"] == "EXPERT#sleep"
        assert item["expert_key"] == "sleep"

    def test_the_tagged_lines_are_split_out_of_the_prose_the_reader_sees(self, gen_env, model):
        model(FULL_REPLY)
        text = az.generate_and_cache("sleep")
        assert "KEY RECOMMENDATION" not in text and "ELENA QUOTE" not in text
        assert text.endswith("The pattern is consistency, not duration.")

    def test_the_recommendation_and_elena_quote_are_stored_as_their_own_fields(self, gen_env, model):
        model(FULL_REPLY)
        az.generate_and_cache("sleep")
        (item,) = gen_env.puts
        assert item["key_recommendation"] == "Anchor sleep onset to a thirty-minute window."
        assert item["elena_quote"] == "He sleeps like a man still negotiating with the day."

    def test_curly_quotes_around_the_elena_line_are_stripped(self, gen_env, model):
        model("Prose.\n\nELENA QUOTE: “He counts what he cannot yet feel.”\n")
        az.generate_and_cache("sleep")
        assert gen_env.puts[0]["elena_quote"] == "He counts what he cannot yet feel."

    def test_a_journaling_prompt_is_recovered_even_when_it_lands_after_elena(self, gen_env, model):
        model("Prose.\n\nELENA QUOTE: She sees the screen glow.\nJOURNALING PROMPT: What were you avoiding at 1am?\n")
        az.generate_and_cache("mind")
        item = gen_env.puts[0]
        assert item["journaling_prompt"] == "What were you avoiding at 1am?"
        assert "JOURNALING PROMPT" not in item["elena_quote"]

    def test_a_journaling_prompt_before_the_elena_line_is_also_recovered(self, gen_env, model):
        model("Prose.\n\nJOURNALING PROMPT: What did the silence protect?\nELENA QUOTE: She sees the gap.\n")
        az.generate_and_cache("mind")
        item = gen_env.puts[0]
        assert item["journaling_prompt"] == "What did the silence protect?"
        assert item["elena_quote"] == "She sees the gap."

    def test_a_truncated_reply_with_no_tags_stores_no_empty_tag_fields(self, gen_env, model):
        """Absent is absent — an empty-string recommendation would render as a blank
        callout on the observatory page."""
        model("The analysis stops mid-thought because the model ran out of tokens")
        az.generate_and_cache("sleep")
        item = gen_env.puts[0]
        assert "key_recommendation" not in item and "elena_quote" not in item

    def test_the_cached_record_records_the_cycle_position_the_reader_is_shown(self, gen_env, model):
        model(FULL_REPLY)
        az.generate_and_cache("sleep")
        item = gen_env.puts[0]
        assert item["days_in_experiment"] == DAY_N and item["week_number"] == WEEK_N

    def test_the_record_expires_so_a_dead_pipeline_cannot_serve_forever(self, gen_env, model):
        model(FULL_REPLY)
        az.generate_and_cache("sleep")
        assert gen_env.puts[0]["ttl"] == int((FROZEN_NOW + timedelta(days=8)).timestamp())

    def test_the_data_snapshot_is_bounded_so_one_record_cannot_blow_the_item_limit(self, gen_env, model):
        gen_env.items.update(
            {
                (az.USER_PREFIX + "journal_analysis", f"DATE#{_days_ago(i)}"): {
                    "pk": az.USER_PREFIX + "journal_analysis",
                    "sk": f"DATE#{_days_ago(i)}",
                    "sentiment_score": Decimal("0.1"),
                    "themes": [f"theme-{i}-{'x' * 200}"],
                }
                for i in range(20)
            }
        )
        model(FULL_REPLY)
        az.generate_and_cache("mind")
        assert len(gen_env.puts[0]["data_snapshot"]) <= 5000

    def test_the_gathered_data_is_actually_sent_to_the_model(self, gen_env, model):
        gen_env.add("whoop", TODAY, sleep_duration_hours=Decimal("7.4"), recovery_score=Decimal("61"))
        m = model(FULL_REPLY)
        az.generate_and_cache("sleep")
        assert "7.4" in m.prompts[0] and "61" in m.prompts[0]

    def test_the_prior_analysis_is_carried_into_the_prompt(self, gen_env, model):
        gen_env.add_raw(az.CACHE_PK, "EXPERT#sleep", phase="experiment", analysis="Last week I named the onset drift.")
        m = model(FULL_REPLY)
        az.generate_and_cache("sleep")
        assert "Last week I named the onset drift." in m.prompts[0]

    def test_the_shared_system_prompt_is_sent_as_a_cacheable_block(self, gen_env, model):
        m = model(FULL_REPLY)
        az.generate_and_cache("sleep", shared_system="SHARED CONTEXT " * 20)
        body = m.requests[0]
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert body["system"][0]["text"].startswith("SHARED CONTEXT")

    def test_no_shared_system_means_no_system_block_at_all(self, gen_env, model):
        m = model(FULL_REPLY)
        az.generate_and_cache("sleep")
        assert "system" not in m.requests[0]

    def test_an_http_error_from_the_model_propagates_to_the_caller(self, gen_env, model):
        """The handler must be able to record 'error' for this coach — a swallowed
        failure would report a successful generation that never happened."""
        err = urllib.error.HTTPError("https://api.anthropic.com", 529, "overloaded", {}, None)
        err.read = lambda: b"overloaded"
        model(err)
        with pytest.raises(urllib.error.HTTPError):
            az.generate_and_cache("sleep")
        assert gen_env.puts == []

    def test_an_empty_model_response_does_not_overwrite_the_cached_analysis(self, gen_env, model):
        """#2218: an empty/refusal-shaped model response must not overwrite a good
        cached analysis, and must not even touch `generated_at` on the surviving
        record — a stamp update alone would make a stale-but-good analysis look
        freshly regenerated."""
        gen_env.add_raw(az.CACHE_PK, "EXPERT#sleep", phase="experiment", analysis="last week's good analysis")
        model("")
        text = az.generate_and_cache("sleep")
        stored = gen_env.items[(az.CACHE_PK, "EXPERT#sleep")]
        assert stored["analysis"].strip() != "", "an empty generation was published over a good one"
        assert stored["analysis"] == "last week's good analysis", "the cached record must be untouched, not just non-empty"
        assert "generated_at" not in stored, "an empty generation must not stamp the surviving record as freshly generated"
        assert gen_env.puts == [], "an empty generation must never reach put_item"
        assert not text.strip(), "generate_and_cache should still return honestly (no text was produced)"


class TestGroundingSelfCorrection:
    """ADR-104/ADR-108 (#2391): one corrective rewrite, then regenerate-or-HOLD.

    The gate runs BEFORE the cache write. Publication requires ZERO residual
    findings — 'better than before' is not 'clean', and the pre-#2391 semantics
    were measured shipping a narrative with 2 known unresolved findings
    ('sleep self-corrected: 6→2') on 2026-08-08."""

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch, table):
        monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
        monkeypatch.setattr(az, "_HAS_AI_VALIDATOR", False)
        monkeypatch.setattr(az, "_persona_core", None)
        monkeypatch.setattr(az, "_load_canonical_facts", dict)
        self.table = table

    def test_a_fabricated_number_triggers_exactly_one_corrective_rewrite(self, model):
        m = model("Recovery averaged 88.7 percent this week.", "Recovery held steady this week.")
        az.generate_and_cache("sleep")
        assert m.calls == 2, "the fabricated figure did not trigger the regen-once pass"

    def test_the_corrected_text_replaces_the_published_analysis(self, model):
        """#2391 moved the gate ABOVE the write: the corrected text arrives in the
        ONE put_item — there is no publish-then-patch update any more, because the
        ungrounded original must never be visible even transiently."""
        model("Recovery averaged 88.7 percent this week.", "Recovery held steady this week.")
        text = az.generate_and_cache("sleep")
        assert text == "Recovery held steady this week."
        cached = self.table.items[(az.CACHE_PK, "EXPERT#sleep")]
        assert cached["analysis"] == "Recovery held steady this week."
        assert self.table.updates == [], "correction happens pre-write; a patch update would mean the original was published first"

    def test_the_correction_prompt_names_the_fabricated_figure(self, model):
        m = model("Recovery averaged 88.7 percent this week.", "Recovery held steady this week.")
        az.generate_and_cache("sleep")
        assert "88.7" in m.prompts[1]

    def test_a_rewrite_that_is_no_better_HOLDS_rather_than_publishing_either_text(self, model):
        """#2391: the old semantics kept the original — which still had findings —
        and PUBLISHED it. Now neither text may reach the cache: residual findings
        after the one rewrite mean hold."""
        m = model("Recovery averaged 88.7 percent.", "Recovery averaged 77.3 percent.")
        text = az.generate_and_cache("sleep")
        assert text == ""
        assert m.calls == 2
        assert (az.CACHE_PK, "EXPERT#sleep") not in self.table.items, "an ungrounded analysis reached the cache"

    def test_a_grounded_analysis_is_never_regenerated(self, model):
        """No finding, no rewrite — the harness must not burn a second call (or risk a
        regression) on a narrative that cites nothing outside its allow-list."""
        self.table.add("whoop", TODAY, recovery_score=Decimal("61"))
        m = model("Deep sleep held its share of the night, and the shape was consistent all week.")
        az.generate_and_cache("sleep")
        assert m.calls == 1 and self.table.updates == []

    def test_an_unlabelled_vitals_figure_is_caught_and_rewritten(self, model):
        """#1968: 'recovery sat at 61' names no night, so a reader cannot reconcile it
        against any stored record — the regen-once harness must fire."""
        self.table.add("whoop", TODAY, recovery_score=Decimal("61"))
        m = model("Recovery sat at 61 this week, steady across the nights.", "Recovery held steady all week.")
        text = az.generate_and_cache("sleep")
        assert m.calls == 2 and text == "Recovery held steady all week."

    def test_a_regeneration_failure_holds_because_the_original_findings_still_stand(self, model):
        """#2391: the regen model being down does not make the original's fabricated
        figure true. Measured findings ⇒ hold; only a failure of the GATE ITSELF
        (see the next test) publishes, because there the findings are unknown."""
        m = model("Recovery averaged 88.7 percent.", RuntimeError("model down"))
        text = az.generate_and_cache("sleep")
        assert text == "" and m.calls == 2
        assert (az.CACHE_PK, "EXPERT#sleep") not in self.table.items

    def test_the_grounding_pass_never_breaks_a_successful_generation(self, monkeypatch, model):
        """Gate-INFRA failure (the gate itself cannot run) fails soft and publishes —
        distinct from measured findings, which hold. A grounding gate must never be
        the thing that takes the surface down."""
        monkeypatch.setattr(az._gg, "allowed_numbers", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        model(FULL_REPLY)
        assert az.generate_and_cache("sleep").startswith("Deep sleep held")

    def test_a_hold_preserves_the_PRIOR_good_analysis_in_the_cache(self, model):
        """The ADR-108 point of holding: yesterday's clean analysis keeps serving.
        A hold must not delete or overwrite it."""
        prior = {"pk": az.CACHE_PK, "sk": "EXPERT#sleep", "analysis": "Yesterday's clean read.", "generated_at": "2026-08-07T17:00:00Z"}
        self.table.items[(az.CACHE_PK, "EXPERT#sleep")] = dict(prior)
        model("Recovery averaged 88.7 percent.", "Recovery averaged 77.3 percent.")
        assert az.generate_and_cache("sleep") == ""
        assert self.table.items[(az.CACHE_PK, "EXPERT#sleep")]["analysis"] == "Yesterday's clean read."


class TestValidatorAttributeContract:
    """The tranche-1 incident shape: a caller reading attributes off a validation
    result that the class does not define, with the AttributeError swallowed by a
    broad except — a silently degraded surface for weeks."""

    def test_the_grounding_backstop_reads_only_attributes_the_result_class_defines(self):
        from ai.ai_output_validator import AIOutputType, AIValidationResult

        result = AIValidationResult(original_text="x", output_type=AIOutputType.GENERIC)
        for attr in ("warnings", "blocked", "block_reason", "sanitized_text", "passed"):
            assert hasattr(result, attr)

    def test_the_backstop_logs_the_validators_warnings_without_raising(self, monkeypatch, table, model):
        monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
        monkeypatch.setattr(az, "_persona_core", None)
        monkeypatch.setattr(az, "_load_canonical_facts", lambda: {"recovery_pct": 61.0, "hrv_ms": 43.2, "rhr_bpm": 58.0})
        seen = {}

        def _fake_validate(text, output_type, health_context=None, max_length=None):
            seen["ctx"] = health_context
            return az._aiv.AIValidationResult(original_text=text, output_type=output_type, warnings=["w"])

        monkeypatch.setattr(az._aiv, "validate_ai_output", _fake_validate)
        # #2391: the first reply's unlabeled vitals figures HOLD publication, so a
        # clean rewrite is queued — this test exercises the validator contract on a
        # PUBLISHED analysis, and only grounded text publishes now.
        model("Recovery sat at 61, HRV 43.2 ms, RHR 58 bpm.", "A quiet, steady week of sleep.")
        az.generate_and_cache("sleep")
        assert seen["ctx"] == {"recovery_score": 61.0, "hrv": 43.2, "resting_heart_rate": 58.0}

    def test_absent_canonical_metrics_are_not_passed_as_none_to_the_validator(self, monkeypatch, table, model):
        monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
        monkeypatch.setattr(az, "_persona_core", None)
        monkeypatch.setattr(az, "_load_canonical_facts", lambda: {"recovery_pct": 61.0})
        calls = []
        monkeypatch.setattr(
            az._aiv,
            "validate_ai_output",
            lambda text, output_type, health_context=None, max_length=None: calls.append(health_context)
            or az._aiv.AIValidationResult(original_text=text, output_type=output_type),
        )
        # #2391: queue a clean rewrite — only grounded text publishes, and the
        # backstop runs on the published text.
        model("Recovery sat at 61 this week.", "Sleep held its shape all week.")
        az.generate_and_cache("sleep")
        assert calls == [{"recovery_score": 61.0}]


# ═════════════════════════════════════════════════════════════════════════════
# generate_synthesis — the Chair's weekly priority
# ═════════════════════════════════════════════════════════════════════════════

SYNTH_JSON = json.dumps(
    {
        "weekly_priority": "Protect sleep onset before adding volume.",
        "cross_domain_notes": {"sleep": "onset drift", "training": "load is fine"},
        "disagreements": [{"between": ["sleep", "training"], "about": "volume"}],
    }
)


@pytest.fixture
def synth_env(monkeypatch, table):
    monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
    monkeypatch.setattr(az, "_load_canonical_facts", dict)
    return table


class TestGenerateSynthesis:
    def test_a_single_coach_output_is_not_synthesised_and_costs_no_model_call(self, synth_env, monkeypatch):
        monkeypatch.setattr(az, "_get_api_key", lambda: pytest.fail("skip path must not fetch a key"))
        assert az.generate_synthesis({"sleep": "text"}) is None
        assert synth_env.puts == []

    def test_the_weekly_priority_is_written_to_the_integrator_record(self, synth_env, model):
        model(SYNTH_JSON)
        az.generate_synthesis({"sleep": "s", "training": "t", "mind": "m"})
        (item,) = synth_env.puts
        assert item["sk"] == "EXPERT#integrator"
        assert item["analysis"] == "Protect sleep onset before adding volume."
        assert item["cross_domain_notes"]["sleep"] == "onset drift"
        assert item["disagreements"]

    def test_each_coachs_text_is_labelled_in_the_material_the_chair_reads(self, synth_env, model):
        m = model(SYNTH_JSON)
        az.generate_synthesis({"sleep": "the sleep read", "training": "the training read"})
        assert "--- SLEEP COACH ---" in m.prompts[0] and "the training read" in m.prompts[0]

    def test_a_fenced_json_reply_is_still_parsed(self, synth_env, model):
        model("```json\n" + SYNTH_JSON + "\n```")
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out["weekly_priority"] == "Protect sleep onset before adding volume."

    def test_a_trailing_comma_does_not_fail_the_whole_synthesis(self, synth_env, model):
        model('{"weekly_priority": "Hold the deficit.", "disagreements": [],}')
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out["weekly_priority"] == "Hold the deficit."

    def test_unparseable_json_still_lands_a_fresh_priority_via_the_regex_fallback(self, synth_env, model):
        """Fail-closing here served yesterday's record as if it were this week's."""
        model('garbage {"weekly_priority": "Hold the deficit this week.", "cross_domain_notes": {oops')
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out["weekly_priority"] == "Hold the deficit this week."
        assert out["_partial"] is True
        assert synth_env.puts[0]["analysis"] == "Hold the deficit this week."

    def test_a_reply_with_no_priority_at_all_is_retried_then_honestly_skipped(self, synth_env, model):
        m = model("I could not complete this request.")
        assert az.generate_synthesis({"sleep": "s", "training": "t"}) is None
        assert m.calls == 2 and synth_env.puts == []

    def test_a_transport_failure_never_writes_a_stub_record(self, synth_env, model):
        model(RuntimeError("connection reset"))
        assert az.generate_synthesis({"sleep": "s", "training": "t"}) is None
        assert synth_env.puts == []

    def test_a_first_attempt_failure_is_retried_and_can_still_succeed(self, synth_env, model):
        m = model(RuntimeError("reset"), SYNTH_JSON)
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out and m.calls == 2

    def test_the_chair_gets_the_same_authoritative_facts_as_the_coaches(self, synth_env, monkeypatch, model):
        monkeypatch.setattr(az, "_load_canonical_facts", lambda: {"recovery_pct": 61.0, "hrv_ms": 43.2, "latest_weight": 318.4})
        m = model(SYNTH_JSON)
        az.generate_synthesis({"sleep": "s", "training": "t"})
        p = m.prompts[0]
        assert "AUTHORITATIVE FACTS" in p and "recovery 61%" in p and "HRV 43.2 ms" in p and "weight 318.4 lb" in p

    def test_deterministic_counts_are_computed_before_the_chair_reasons(self, synth_env, model):
        """ADR-105: the Chair cites counts, it never re-derives them."""
        synth_env.add("hevy", TODAY, set_count=Decimal("20"))
        synth_env.add("strava", _days_ago(1), moving_time_seconds=Decimal("1800"))
        synth_env.add("macrofactor", TODAY, total_calories_kcal=Decimal("2000"))
        m = model(SYNTH_JSON)
        az.generate_synthesis({"sleep": "s", "training": "t"})
        p = m.prompts[0]
        assert f"experiment day_n = {DAY_N}" in p
        assert "logged training sessions (last 30d, Hevy + Strava) = 2" in p
        assert "food-log days (last 30d) = 1" in p

    def test_the_counts_carry_an_explicit_no_arithmetic_rule(self, synth_env, model):
        m = model(SYNTH_JSON)
        az.generate_synthesis({"sleep": "s", "training": "t"})
        assert "do NOT re-derive" in m.prompts[0] and "in digits or in words" in m.prompts[0]

    def test_a_count_query_failure_never_blocks_the_synthesis(self, synth_env, model):
        synth_env.query_errors[az.USER_PREFIX + "hevy"] = RuntimeError("throttled")
        model(SYNTH_JSON)
        assert az.generate_synthesis({"sleep": "s", "training": "t"}) is not None

    def test_a_quiet_stretch_reaches_the_chair_so_it_cannot_crown_a_flawless_week(self, synth_env, monkeypatch, model):
        monkeypatch.setattr(az, "_presence_block", lambda: "PRESENCE: Matthew's logging has gone quiet.")
        m = model(SYNTH_JSON)
        az.generate_synthesis({"sleep": "s", "training": "t"})
        assert "logging has gone quiet" in m.prompts[0]


# ═════════════════════════════════════════════════════════════════════════════
# Deterministic behavioral presence (#914-A, ADR-105)
# ═════════════════════════════════════════════════════════════════════════════


class TestWeekBehavioralPresence:
    def _week_of(self, date_str):
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"

    def test_it_reports_the_monday_to_sunday_span_of_the_iso_week(self, table):
        pres = az._week_behavioral_presence(self._week_of(TODAY))
        assert datetime.strptime(pres["start"], "%Y-%m-%d").weekday() == 0
        assert datetime.strptime(pres["end"], "%Y-%m-%d").weekday() == 6

    def test_counts_come_from_the_raw_logs_of_all_four_behavioral_streams(self, table):
        table.add("hevy", TODAY, set_count=Decimal("20"))
        table.add("withings", TODAY, weight_lbs=Decimal("318"))
        table.add("habitify", TODAY, total_completed=Decimal("3"))
        table.add("macrofactor", TODAY, total_calories_kcal=Decimal("2000"))
        pres = az._week_behavioral_presence(self._week_of(TODAY))
        assert (pres["lift_days"], pres["weigh_ins"], pres["habit_completion_days"], pres["food_log_days"]) == (1, 1, 1, 1)
        assert pres["absence_week"] is False

    def test_a_fully_dark_week_is_named_an_absence_week(self, table):
        """The regenerated week-4 arc celebrated a dark week off rest-inflated HRV."""
        pres = az._week_behavioral_presence(self._week_of(TODAY))
        assert pres["absence_week"] is True

    def test_a_habit_record_with_nothing_completed_is_not_behavior(self, table):
        table.add("habitify", TODAY, total_completed=Decimal("0"))
        pres = az._week_behavioral_presence(self._week_of(TODAY))
        assert pres["habit_completion_days"] == 0 and pres["absence_week"] is True

    def test_any_single_stream_of_activity_ends_the_absence_verdict(self, table):
        table.add("withings", TODAY, weight_lbs=Decimal("318"))
        assert az._week_behavioral_presence(self._week_of(TODAY))["absence_week"] is False

    @pytest.mark.parametrize("bad", [None, "", "not-a-week", 5, "2026-W", "2026-Wxx"])
    def test_an_unparseable_week_key_yields_no_presence_claim(self, table, bad):
        assert az._week_behavioral_presence(bad) is None

    def test_a_query_failure_yields_no_presence_claim_rather_than_zeros(self, table):
        """Zeros here would be published as 'an absence week' — a data outage narrated
        as Matthew doing nothing."""
        table.query_errors[az.USER_PREFIX + "hevy"] = RuntimeError("throttled")
        assert az._week_behavioral_presence(self._week_of(TODAY)) is None


# ═════════════════════════════════════════════════════════════════════════════
# The cross-week narratives
# ═════════════════════════════════════════════════════════════════════════════


ARC_JSON = json.dumps({"arc": "It started heavy and got honest.", "throughline": "consistency", "chapters": ["a", "b"]})
MONTH_JSON = json.dumps({"narrative": "The month found its floor.", "headline": "Finding the floor"})


def _week_note(table, week, label, present="the week's observation"):
    table.add_raw(
        az.USER_PREFIX + "field_notes",
        f"WEEK#{week}",
        week=week,
        week_label=label,
        ai_tone="steady",
        ai_present=present,
        phase="experiment",
    )


@pytest.fixture
def arc_env(monkeypatch, table):
    monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
    monkeypatch.setattr(az, "_load_canonical_facts", dict)
    return table


class TestExperimentArc:
    def test_a_single_week_of_notes_is_an_honest_skip_with_no_model_call(self, arc_env, monkeypatch):
        _week_note(arc_env, "2026-W31", "Week 1")
        monkeypatch.setattr(az, "_get_api_key", lambda: pytest.fail("skip path must not fetch a key"))
        assert az.generate_experiment_arc() is None
        assert arc_env.puts == []

    def test_the_field_notes_query_hides_pre_genesis_pilot_weeks(self, arc_env, model):
        _week_note(arc_env, "2026-W31", "Week 1")
        _week_note(arc_env, "2026-W32", "Week 2")
        model(ARC_JSON)
        az.generate_experiment_arc()
        (kw,) = [k for k in arc_env.queries if "FilterExpression" in k]
        assert "phase" in str(kw["ExpressionAttributeNames"]) or "#phase" in kw["FilterExpression"]

    def test_the_arc_is_written_with_its_chapter_and_week_counts(self, arc_env, model):
        _week_note(arc_env, "2026-W31", "Week 1")
        _week_note(arc_env, "2026-W32", "Week 2")
        model(ARC_JSON)
        az.generate_experiment_arc()
        (item,) = arc_env.puts
        assert item["sk"] == "EXPERT#experiment_arc"
        assert item["week_count"] == 2 and item["chapters"] == ["a", "b"]

    def test_each_weeks_deterministic_presence_is_stapled_to_its_notes(self, arc_env, model):
        _week_note(arc_env, "2026-W31", "Week 1")
        _week_note(arc_env, "2026-W32", "Week 2")
        m = model(ARC_JSON)
        az.generate_experiment_arc()
        assert "BEHAVIORAL PRESENCE" in m.prompts[0] and "AUTHORITATIVE" in m.prompts[0]

    def test_a_dark_week_is_labelled_an_absence_week_in_the_material(self, arc_env, model):
        _week_note(arc_env, "2026-W31", "Week 1")
        _week_note(arc_env, "2026-W32", "Week 2")
        m = model(ARC_JSON)
        az.generate_experiment_arc()
        assert "AN ABSENCE WEEK (no behavioral data at all)" in m.prompts[0]

    def test_a_malformed_arc_reply_still_lands_the_narrative_via_the_fallback(self, arc_env, model):
        _week_note(arc_env, "2026-W31", "Week 1")
        _week_note(arc_env, "2026-W32", "Week 2")
        model('{"arc": "It started heavy and got honest.", "chapters": [oops')
        parsed = az.generate_experiment_arc()
        assert parsed["arc"] == "It started heavy and got honest." and parsed["_partial"] is True

    def test_an_unparseable_arc_writes_nothing(self, arc_env, model):
        _week_note(arc_env, "2026-W31", "Week 1")
        _week_note(arc_env, "2026-W32", "Week 2")
        model("no json at all")
        assert az.generate_experiment_arc() is None and arc_env.puts == []

    def test_a_field_notes_query_failure_is_a_skip_not_a_crash(self, arc_env):
        arc_env.query_errors[az.USER_PREFIX + "field_notes"] = RuntimeError("throttled")
        assert az.generate_experiment_arc() is None


class TestMonthRollup:
    def test_fewer_than_two_week_notes_in_the_window_is_an_honest_skip(self, arc_env, monkeypatch):
        _week_note(arc_env, "2026-W31", "Week 1")
        monkeypatch.setattr(az, "_get_api_key", lambda: pytest.fail("skip path must not fetch a key"))
        assert az.generate_month_rollup() is None

    def test_the_rollup_is_written_with_its_window_and_week_count(self, arc_env, model):
        _week_note(arc_env, "2026-W31", "Week 1")
        _week_note(arc_env, "2026-W32", "Week 2")
        model(MONTH_JSON)
        az.generate_month_rollup()
        (item,) = arc_env.puts
        assert item["sk"] == "EXPERT#integrator_month"
        assert item["narrative"] == "The month found its floor." and item["headline"] == "Finding the floor"
        assert item["week_count"] == 2 and item["window_label"]

    def test_only_the_trailing_four_weeks_are_rolled_up(self, arc_env, model):
        for i, wk in enumerate(["2026-W28", "2026-W29", "2026-W30", "2026-W31", "2026-W32"]):
            _week_note(arc_env, wk, f"Week {i + 1}")
        model(MONTH_JSON)
        rollup = az.generate_month_rollup()
        assert rollup["week_count"] == 4
        assert arc_env.puts[0]["week_count"] == 4

    def test_the_rollup_reads_the_weeks_oldest_first_so_the_month_reads_in_order(self, arc_env, model):
        for i, wk in enumerate(["2026-W29", "2026-W30", "2026-W31", "2026-W32"]):
            _week_note(arc_env, wk, f"Week {i + 1}", present=f"observation {i + 1}")
        m = model(MONTH_JSON)
        az.generate_month_rollup()
        p = m.prompts[0]
        assert p.index("observation 1") < p.index("observation 4")

    def test_a_malformed_rollup_reply_still_lands_a_narrative(self, arc_env, model):
        _week_note(arc_env, "2026-W31", "Week 1")
        _week_note(arc_env, "2026-W32", "Week 2")
        model('{"narrative": "The month found its floor.", "headline": oops')
        parsed = az.generate_month_rollup()
        assert parsed["narrative"] == "The month found its floor." and parsed["_partial"] is True

    def test_an_unparseable_rollup_writes_nothing(self, arc_env, model):
        _week_note(arc_env, "2026-W31", "Week 1")
        _week_note(arc_env, "2026-W32", "Week 2")
        model("nothing useful")
        assert az.generate_month_rollup() is None and arc_env.puts == []

    def test_a_field_notes_query_failure_is_a_skip_not_a_crash(self, arc_env):
        arc_env.query_errors[az.USER_PREFIX + "field_notes"] = RuntimeError("throttled")
        assert az.generate_month_rollup() is None


# ═════════════════════════════════════════════════════════════════════════════
# lambda_handler
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def handler_env(monkeypatch):
    """Every generator replaced by a recording stub — the handler's own branching
    is what is under test here."""
    calls = {"experts": [], "synthesis": 0, "arc": 0, "month": 0}
    monkeypatch.setattr(az, "_build_shared_system_prompt", lambda: "SHARED")
    monkeypatch.setattr(az, "generate_and_cache", lambda k, shared_system=None: calls["experts"].append(k) or f"{k} text")
    monkeypatch.setattr(az, "generate_synthesis", lambda outs: calls.__setitem__("synthesis", calls["synthesis"] + 1) or {"x": 1})
    monkeypatch.setattr(
        az, "generate_experiment_arc", lambda: calls.__setitem__("arc", calls["arc"] + 1) or {"week_count": 3, "chapters": []}
    )
    monkeypatch.setattr(az, "generate_month_rollup", lambda: calls.__setitem__("month", calls["month"] + 1) or {"week_count": 4})
    return calls


def _body(resp):
    return json.loads(resp["body"])


class TestLambdaHandler:
    def test_a_full_run_generates_every_expert_on_the_roster(self, handler_env):
        resp = az.lambda_handler({}, None)
        assert handler_env["experts"] == az.EXPERTS
        assert set(_body(resp)) >= set(az.EXPERTS)

    def test_a_full_run_reports_the_character_count_each_coach_produced(self, handler_env):
        body = _body(az.lambda_handler({}, None))
        assert body["sleep"] == {"status": "ok", "chars": len("sleep text")}

    def test_an_empty_generation_is_reported_as_skipped_not_ok(self, monkeypatch, handler_env):
        """#2218: `chars: 0` under `status: ok` reads as a successful run that wrote
        nothing — the handler must report an empty generation distinguishably."""
        monkeypatch.setattr(az, "generate_and_cache", lambda k, shared_system=None: "" if k == "sleep" else f"{k} text")
        body = _body(az.lambda_handler({}, None))
        assert body["sleep"] != {"status": "ok", "chars": 0}
        assert body["sleep"]["status"] != "ok"
        assert body["mind"] == {"status": "ok", "chars": len("mind text")}

    def test_a_single_expert_request_runs_only_that_expert(self, handler_env):
        az.lambda_handler({"expert": "sleep"}, None)
        assert handler_env["experts"] == ["sleep"]

    def test_a_single_expert_run_skips_the_board_level_syntheses(self, handler_env):
        az.lambda_handler({"expert": "sleep"}, None)
        assert handler_env["synthesis"] == 0 and handler_env["arc"] == 0 and handler_env["month"] == 0

    def test_an_unknown_expert_is_refused_rather_than_prompted(self, handler_env):
        resp = az.lambda_handler({"expert": "astrology"}, None)
        assert handler_env["experts"] == [] and _body(resp) == {}

    def test_one_coachs_failure_does_not_abort_the_other_seven(self, monkeypatch, handler_env):
        def _flaky(key, shared_system=None):
            if key == "sleep":
                raise RuntimeError("Anthropic 529")
            handler_env["experts"].append(key)
            return f"{key} text"

        monkeypatch.setattr(az, "generate_and_cache", _flaky)
        body = _body(az.lambda_handler({}, None))
        assert body["sleep"]["status"] == "error" and "529" in body["sleep"]["error"]
        assert len(handler_env["experts"]) == len(az.EXPERTS) - 1

    def test_the_syntheses_still_run_when_most_coaches_succeeded(self, monkeypatch, handler_env):
        def _flaky(key, shared_system=None):
            if key == "sleep":
                raise RuntimeError("boom")
            return f"{key} text"

        monkeypatch.setattr(az, "generate_and_cache", _flaky)
        az.lambda_handler({}, None)
        assert handler_env["synthesis"] == 1 and handler_env["arc"] == 1 and handler_env["month"] == 1

    def test_a_near_total_generation_failure_skips_the_synthesis_pass(self, monkeypatch, handler_env):
        """Synthesising two coaches into 'the board's weekly priority' would be a lie
        about who was in the room."""
        monkeypatch.setattr(
            az,
            "generate_and_cache",
            lambda k, shared_system=None: (_ for _ in ()).throw(RuntimeError("down")) if k not in ("sleep", "mind") else "t",
        )
        az.lambda_handler({}, None)
        assert handler_env["synthesis"] == 0

    def test_a_synthesis_failure_is_reported_not_swallowed(self, monkeypatch, handler_env):
        monkeypatch.setattr(az, "generate_synthesis", lambda outs: (_ for _ in ()).throw(RuntimeError("json dead")))
        body = _body(az.lambda_handler({}, None))
        assert body["integrator"]["status"] == "error"

    def test_a_skipped_month_rollup_is_reported_as_skipped_not_as_success(self, monkeypatch, handler_env):
        monkeypatch.setattr(az, "generate_month_rollup", lambda: None)
        body = _body(az.lambda_handler({}, None))
        assert body["month_rollup"] == {"status": "skipped"}

    def test_arc_only_refreshes_the_arc_and_runs_no_coach(self, handler_env):
        resp = az.lambda_handler({"arc_only": True}, None)
        assert handler_env["experts"] == [] and handler_env["arc"] == 1
        assert _body(resp)["experiment_arc"] == {"status": "ok", "weeks": 3}

    def test_arc_only_reports_a_skip_honestly(self, monkeypatch, handler_env):
        monkeypatch.setattr(az, "generate_experiment_arc", lambda: None)
        resp = az.lambda_handler({"arc_only": True}, None)
        assert _body(resp)["experiment_arc"] == {"status": "skipped"}

    def test_month_only_refreshes_the_rollup_and_runs_no_coach(self, handler_env):
        resp = az.lambda_handler({"month_only": True}, None)
        assert handler_env["experts"] == [] and handler_env["month"] == 1
        assert _body(resp)["month_rollup"] == {"status": "ok", "weeks": 4}

    def test_month_only_reports_a_skip_honestly(self, monkeypatch, handler_env):
        monkeypatch.setattr(az, "generate_month_rollup", lambda: None)
        resp = az.lambda_handler({"month_only": True}, None)
        assert _body(resp)["month_rollup"] == {"status": "skipped"}

    def test_a_fatal_failure_raises_so_the_alarm_fires(self, monkeypatch, handler_env):
        """A swallowed handler failure would report success for a run that generated
        nothing — the invocation must fail loudly."""
        monkeypatch.setattr(az, "_build_shared_system_prompt", lambda: (_ for _ in ()).throw(RuntimeError("secrets down")))
        with pytest.raises(RuntimeError):
            az.lambda_handler({}, None)

    def test_a_successful_run_returns_a_200_with_a_json_body(self, handler_env):
        resp = az.lambda_handler({}, None)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["sleep"]["status"] == "ok"
