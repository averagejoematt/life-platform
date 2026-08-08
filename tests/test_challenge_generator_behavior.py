#!/usr/bin/env python3
"""tests/test_challenge_generator_behavior.py — behavioral contracts of
`lambdas/intelligence/challenge_generator_lambda.py`.

Part of #1658 tranche 2. This weekly Lambda is the only writer of the
`challenges` candidate surface that Matthew reviews and the website publishes,
and it is an AI-narrative path: everything it emits is a claim about what the
data showed. The contracts under test are therefore the honesty ones first:

  * ADR-104 — an unmeasured window is absent, never 0; a challenge never
    carries a field the model did not supply;
  * ADR-105 — a below-floor sample must not reach the generator at all, and a
    hypothesis that is still being tested must not be handed to the writer
    under the label "confirmed";
  * the AI path degrading honestly — a blocked, empty or non-JSON model
    response must never become a shipped stub, and must never be reported as
    a real "no signal" week;
  * deterministic selection — ranking, tie order, the MAX_NEW_CHALLENGES cap
    and same-batch dedup, all pinned to hand-derived values;
  * Decimal before every DynamoDB write;
  * ADR-058 phase scoping on reads, derived from the taxonomy rather than a
    hand-typed source list;
  * fail-soft boundaries — one dead partition must not take the run down.

`tests/test_challenge_generator.py` already covers the #1118 hoped_outcome
contract and the COST-OPT-2 cache stability of SYSTEM_PROMPT; nothing here
repeats it.

No real Bedrock, DynamoDB, S3 or HTTP anywhere in this file. Time is frozen
with a `datetime` subclass on the module's own name.
"""

import ast
import inspect
import json
import math
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

import common.retry_utils as retry_utils  # noqa: E402
from experiment.phase_filter import source_reads_cross_phase  # noqa: E402
from intelligence import challenge_generator_lambda as chg  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock — a fixture date must never meet the real wall clock.
# ──────────────────────────────────────────────────────────────────────────────

FROZEN_NOW = datetime(2026, 8, 7, 17, 0, 0, tzinfo=timezone.utc)
TODAY = "2026-08-07"
WINDOW_START = "2026-07-25"  # FROZEN_NOW - (LOOKBACK_DAYS - 1)


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`.

    A subclass rather than a Mock: the module also does `strftime`, `timedelta`
    arithmetic and `%A` weekday formatting on the same name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(chg, "datetime", _FrozenDatetime)
    return FROZEN_NOW


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """ADR-062: this module builds a legacy urllib Request but the transport is
    Bedrock. Any real urlopen from this suite is a bug in the test or the code."""

    def _boom(*a, **kw):  # pragma: no cover - only runs if something regresses
        raise AssertionError("the challenge generator must never open a socket")

    monkeypatch.setattr(chg.urllib.request, "urlopen", _boom)


# ──────────────────────────────────────────────────────────────────────────────
# Test double
# ──────────────────────────────────────────────────────────────────────────────


def _flatten_key_condition(cond, out=None):
    """Reduce a boto3 `Key(...)` condition tree to {pk, sk_prefix}."""
    out = {} if out is None else out
    expr = cond.get_expression()
    op = expr["operator"]
    vals = expr["values"]
    if op == "AND":
        for sub in vals:
            _flatten_key_condition(sub, out)
    elif op == "=":
        out[vals[0].name] = vals[1]
    elif op == "begins_with":
        out["sk_prefix"] = vals[1]
    return out


class FakeTable:
    """DynamoDB Table stand-in keyed the way this module keys the real table.

    Serves both query shapes the module issues — the shared paginated
    `pk = :pk AND sk BETWEEN :s AND :e` string form (via digest_utils) and the
    `Key("pk").eq(...) & Key("sk").begins_with(...)` object form the three
    direct partition reads use — and applies the ADR-058 phase predicate
    faithfully whenever a FilterExpression naming `#phase` is present, so a
    read that forgets the filter visibly returns wiped-cycle rows.
    """

    def __init__(self):
        self.items = {}
        self.puts = []
        self.queries = []
        self.query_errors = {}  # pk -> exception
        self.get_error = None
        self.pages = None  # optional LastEvaluatedKey-chained page list

    # -- writes --
    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        self.items[(Item["pk"], Item["sk"])] = Item
        return {}

    # -- reads --
    def get_item(self, Key=None, **kwargs):
        if self.get_error is not None:
            raise self.get_error
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        kce = kwargs.get("KeyConditionExpression")
        vals = kwargs.get("ExpressionAttributeValues") or {}
        if isinstance(kce, str):
            pk = vals.get(":pk")
            lo, hi = vals.get(":s"), vals.get(":e")
            prefix = None
        else:
            flat = _flatten_key_condition(kce)
            pk = flat.get("pk")
            lo = hi = None
            prefix = flat.get("sk_prefix")

        if pk in self.query_errors:
            raise self.query_errors[pk]
        if self.pages:
            return self.pages.pop(0)

        rows = [v for (p, _s), v in self.items.items() if p == pk]
        if lo is not None:
            rows = [r for r in rows if lo <= r["sk"] <= hi]
        if prefix:
            rows = [r for r in rows if str(r["sk"]).startswith(prefix)]
        if "#phase" in (kwargs.get("FilterExpression") or ""):
            current = vals.get(":phase_experiment")
            rows = [r for r in rows if r.get("phase") in (None, current)]
        rows = sorted(rows, key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        return {"Items": rows[:limit] if limit else rows}


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(chg, "table", t)
    return t


def _pk(source):
    return f"USER#{chg.USER_ID}#SOURCE#{source}"


def seed(table, source, sk, **fields):
    row = {"pk": _pk(source), "sk": sk, **fields}
    table.items[(row["pk"], row["sk"])] = row
    return row


def seed_date(table, source, date_str, **fields):
    return seed(table, source, f"DATE#{date_str}", **fields)


def read_sources(table):
    """(source, filter_applied) for every query this run issued."""
    out = []
    for kwargs in table.queries:
        kce = kwargs.get("KeyConditionExpression")
        vals = kwargs.get("ExpressionAttributeValues") or {}
        pk = vals.get(":pk") if isinstance(kce, str) else _flatten_key_condition(kce).get("pk")
        if not pk or "#SOURCE#" not in pk:
            continue
        out.append((pk.split("#SOURCE#")[1], "#phase" in (kwargs.get("FilterExpression") or "")))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Canonical fixtures
# ──────────────────────────────────────────────────────────────────────────────

CANDIDATE = {
    "name": "Kitchen Closed At Eight",
    "description": "Late-night snacking flagged repeatedly in the last two weeks.",
    "source": "journal_mining",
    "source_detail": "avoidance_flag: late_night_snacking x6 in 14d",
    "domain": "nutrition",
    "difficulty": "moderate",
    "duration_days": 7,
    "protocol": "Kitchen closed after 8pm; herbal tea allowed.",
    "success_criteria": "6 of 7 evenings without eating after 8pm",
    "hoped_outcome": "Fewer late-night flags by the end of the week; one week is one data point.",
    "tags": ["nutrition", "evening"],
    "verification_method": "self_report",
    "metric_targets": {},
}


def candidate(**overrides):
    out = dict(CANDIDATE)
    out.update(overrides)
    return out


def ai_response(text):
    return {"content": [{"text": text}]}


def stub_model(monkeypatch, text=None, *, payload=None, error=None, response=None):
    """Patch the ONE Bedrock chokepoint where this module looks it up."""
    calls = []

    def _fake(req, timeout=55):
        calls.append(json.loads(req.data.decode()) if hasattr(req, "data") else req)
        if error is not None:
            raise error
        if response is not None:
            return response
        return ai_response(text if text is not None else json.dumps(payload))

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _fake)
    return calls


# ══════════════════════════════════════════════════════════════════════════════
# Journal mining — what the generator is actually allowed to see
# ══════════════════════════════════════════════════════════════════════════════


def _mined_enriched_fields():
    """The `enriched_*` names gather_context looks up, read out of the module's
    own source so a rename can't leave this test asserting the old list."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(chg.gather_context)))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("enriched_")}


def _enrichment_writer_fields():
    """The `enriched_*` names the enrichment Lambda actually persists."""
    src = open(os.path.join(LAMBDAS, "ingestion", "journal_enrichment_lambda.py")).read()
    return set(re.findall(r'"(enriched_[a-z_]+)"', src))


class TestJournalMining:
    def test_every_enriched_field_the_generator_mines_is_one_the_enricher_writes(self):
        """The classic silent-pin: the generator asks for `enriched_avoidance`,
        the enricher writes `enriched_avoidance_flags`, and journal mining is
        permanently dark with no error anywhere. Both sides are derived, so a
        rename on either side surfaces here."""
        mined = _mined_enriched_fields()
        assert mined, "gather_context mines no enriched fields at all"
        assert mined <= _enrichment_writer_fields(), f"mined but never written: {sorted(mined - _enrichment_writer_fields())}"

    def test_an_entry_carries_its_date_template_and_present_enriched_fields(self, table):
        seed(
            table,
            "notion",
            "DATE#2026-08-01#journal#morning",
            template="Morning",
            enriched_themes=["avoidance"],
            enriched_avoidance_flags=["late_night_snacking"],
        )
        entry = chg.gather_context()["journal_14d"][0]
        assert entry["date"] == "2026-08-01"
        assert entry["template"] == "Morning"
        assert entry["enriched_themes"] == ["avoidance"]
        assert entry["enriched_avoidance_flags"] == ["late_night_snacking"]

    def test_an_unenriched_entry_carries_no_empty_enrichment_keys(self, table):
        """ADR-104: an entry the enricher has not reached yet is silent about
        its themes, not an entry whose themes are empty."""
        seed(table, "notion", "DATE#2026-08-01#journal#morning", template="Morning", enriched_themes=[], enriched_mood=None)
        entry = chg.gather_context()["journal_14d"][0]
        assert set(entry) == {"date", "template"}

    def test_free_text_snippets_are_truncated_to_two_hundred_characters(self, table):
        seed(table, "notion", "DATE#2026-08-01#journal#evening", template="Evening", win_of_the_day="w" * 500)
        assert len(chg.gather_context()["journal_14d"][0]["win_of_the_day"]) == 200

    def test_an_empty_free_text_field_is_dropped_rather_than_sent_as_blank(self, table):
        seed(table, "notion", "DATE#2026-08-01#journal#evening", template="Evening", what_drained_me="")
        assert "what_drained_me" not in chg.gather_context()["journal_14d"][0]

    def test_a_platform_with_no_journal_omits_the_journal_block_entirely(self, table):
        """An absent block and an empty block read very differently to the
        writer — the prompt must not say 'here are your 0 entries'."""
        assert "journal_14d" not in chg.gather_context()

    def test_entries_outside_the_fourteen_day_window_are_not_mined(self, table):
        seed(table, "notion", "DATE#2026-06-01#journal#morning", template="Morning", enriched_themes=["old"])
        seed(table, "notion", "DATE#2026-08-01#journal#morning", template="Morning", enriched_themes=["new"])
        entries = chg.gather_context()["journal_14d"]
        assert [e["enriched_themes"] for e in entries] == [["new"]]


# ══════════════════════════════════════════════════════════════════════════════
# Character sheet
# ══════════════════════════════════════════════════════════════════════════════


class TestCharacterContext:
    def _sheet(self, table, date_str=TODAY, **fields):
        return seed_date(table, "character_sheet", date_str, character_level=Decimal("12"), character_tier="Apprentice", **fields)

    def test_only_pillars_the_sheet_actually_carries_are_reported(self, table):
        """A never-instrumented pillar is absent, not level 0 (ADR-104/#960)."""
        self._sheet(table, pillar_sleep={"level": Decimal("22"), "tier": "Foundation", "raw_score": Decimal("41.2")})
        pillars = chg.gather_context()["character"]["pillars"]
        assert set(pillars) == {"sleep"}
        assert pillars["sleep"]["level"] == 22.0
        assert pillars["sleep"]["tier"] == "Foundation"

    def test_the_pillar_facets_read_here_are_ones_the_character_engine_writes(self, table):
        """Cross-partition field names: the engine stores the whole pillar
        result dict, so a facet this module invents would pin as None forever."""
        self._sheet(table, pillar_mind={"level": 4, "tier": "Foundation", "raw_score": 12.0, "level_score": 3.9})
        facets = chg.gather_context()["character"]["pillars"]["mind"]
        engine_src = open(os.path.join(LAMBDAS, "health", "character_engine.py")).read()
        for facet in facets:
            assert f'"{facet}"' in engine_src, f"pillar facet {facet!r} is read here but never written by character_engine"

    def test_the_headline_level_and_tier_ride_the_context(self, table):
        self._sheet(table, pillar_sleep={"level": 1})
        char = chg.gather_context()["character"]
        assert (char["overall_level"], char["overall_tier"]) == (12.0, "Apprentice")

    def test_the_newest_sheet_wins_over_older_ones(self, table):
        self._sheet(table, "2026-08-01", pillar_sleep={"level": 1})
        seed_date(table, "character_sheet", TODAY, character_level=Decimal("30"), character_tier="Adept", pillar_sleep={"level": 9})
        assert chg.gather_context()["character"]["overall_level"] == 30.0

    def test_a_dead_character_partition_never_aborts_the_gather(self, table):
        """Fail-soft: one throttled read must not cost the whole weekly run."""
        table.query_errors[_pk("character_sheet")] = RuntimeError("throttled")
        seed_date(table, "habit_scores", TODAY, tier0_pct=Decimal("1"))
        ctx = chg.gather_context()
        assert "character" not in ctx
        assert "habits" in ctx

    def test_a_platform_with_no_sheet_omits_the_character_block(self, table):
        assert "character" not in chg.gather_context()


# ══════════════════════════════════════════════════════════════════════════════
# Habit signals
# ══════════════════════════════════════════════════════════════════════════════


class TestHabitContext:
    def test_the_tier_zero_fraction_is_reported_as_a_whole_percentage(self, table):
        """habit_scores stores tier0_pct as a 0..1 fraction; the prompt reads a
        percentage. Hand-derived: mean(0.75, 0.5, 1.0) = 0.75 -> 75."""
        for d, pct in (("2026-08-01", "0.75"), ("2026-08-02", "0.5"), ("2026-08-03", "1.0")):
            seed_date(table, "habit_scores", d, tier0_pct=Decimal(pct))
        assert chg.gather_context()["habits"]["avg_tier0_completion"] == 75

    def test_a_window_with_no_scored_tier_zero_day_reports_none_not_zero(self, table):
        """ADR-104: 'no completion data' must not read to the writer as 'you
        completed nothing' — that would justify a challenge the data cannot."""
        seed_date(table, "habit_scores", "2026-08-01", missed_tier0=["steps"])
        assert chg.gather_context()["habits"]["avg_tier0_completion"] is None

    def test_the_most_missed_habits_are_ranked_by_frequency(self, table):
        seed_date(table, "habit_scores", "2026-08-01", missed_tier0=["steps", "water"])
        seed_date(table, "habit_scores", "2026-08-02", missed_tier0=["steps"])
        seed_date(table, "habit_scores", "2026-08-03", missed_tier0=["sleep", "steps", "water"])
        assert chg.gather_context()["habits"]["most_missed_tier0"] == [("steps", 3), ("water", 2), ("sleep", 1)]

    def test_only_the_five_worst_habits_are_offered(self, table):
        for i in range(7):
            seed_date(table, "habit_scores", f"2026-08-0{i + 1}", missed_tier0=[f"h{j}" for j in range(7 - i)])
        ranked = chg.gather_context()["habits"]["most_missed_tier0"]
        assert len(ranked) == 5
        assert [c for _n, c in ranked] == sorted((c for _n, c in ranked), reverse=True)

    def test_the_missed_ranking_is_stable_across_repeated_gathers(self, table):
        """A weekly generator that reshuffles ties writes a different challenge
        each run from identical data."""
        seed_date(table, "habit_scores", "2026-08-01", missed_tier0=["a", "b", "c"])
        first = chg.gather_context()["habits"]["most_missed_tier0"]
        assert chg.gather_context()["habits"]["most_missed_tier0"] == first

    def test_the_day_count_is_the_number_of_scored_days_not_the_window_length(self, table):
        seed_date(table, "habit_scores", "2026-08-01", tier0_pct=Decimal("1"))
        seed_date(table, "habit_scores", "2026-08-02", tier0_pct=Decimal("1"))
        assert chg.gather_context()["habits"]["days_with_data"] == 2

    def test_vice_streaks_come_from_the_most_recent_scored_day(self, table):
        seed_date(table, "habit_scores", "2026-08-01", tier0_pct=Decimal("1"), vice_streaks={"no_weed": Decimal("3")})
        seed_date(table, "habit_scores", "2026-08-05", tier0_pct=Decimal("1"), vice_streaks={"no_weed": Decimal("7")})
        assert chg.gather_context()["habits"]["vice_streaks"] == {"no_weed": 7.0}

    def test_a_history_without_vice_tracking_omits_the_streak_block(self, table):
        seed_date(table, "habit_scores", "2026-08-01", tier0_pct=Decimal("1"))
        assert "vice_streaks" not in chg.gather_context()["habits"]

    def test_a_platform_with_no_habit_history_omits_the_habit_block(self, table):
        assert "habits" not in chg.gather_context()


# ══════════════════════════════════════════════════════════════════════════════
# Hypothesis graduation — the ADR-105 honesty edge
# ══════════════════════════════════════════════════════════════════════════════


def _hyp(table, ts, status, checks, **fields):
    return seed(
        table,
        "hypotheses",
        f"HYPOTHESIS#{ts}",
        status=status,
        check_count=Decimal(str(checks)),
        hypothesis="Late caffeine lowers deep sleep",
        actionable_if_confirmed="Cut caffeine after 2pm",
        domains=["sleep"],
        **fields,
    )


class TestHypothesisGraduation:
    def test_a_hypothesis_checked_fewer_than_twice_never_graduates(self, table):
        """ADR-105: one check is one data point — it cannot found a challenge."""
        _hyp(table, "2026-08-01T00:00:00", "confirmed", 1)
        assert "confirmed_hypotheses" not in chg.gather_context()

    def test_a_twice_checked_confirmed_hypothesis_graduates_with_its_action(self, table):
        _hyp(table, "2026-08-01T00:00:00", "confirmed", 2)
        graduated = chg.gather_context()["confirmed_hypotheses"]
        assert len(graduated) == 1
        assert graduated[0]["actionable_if_confirmed"] == "Cut caffeine after 2pm"
        assert graduated[0]["domains"] == ["sleep"]

    def test_a_refuted_hypothesis_never_graduates(self, table):
        _hyp(table, "2026-08-01T00:00:00", "refuted", 9)
        assert "confirmed_hypotheses" not in chg.gather_context()

    def test_at_most_five_graduates_are_offered(self, table):
        for i in range(8):
            _hyp(table, f"2026-08-0{i + 1}T00:00:00", "confirmed", 4)
        assert len(chg.gather_context()["confirmed_hypotheses"]) == 5

    def test_a_dead_hypothesis_partition_never_aborts_the_gather(self, table):
        table.query_errors[_pk("hypotheses")] = RuntimeError("throttled")
        seed_date(table, "habit_scores", TODAY, tier0_pct=Decimal("1"))
        ctx = chg.gather_context()
        assert "confirmed_hypotheses" not in ctx
        assert "habits" in ctx

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): gather_context admits status=='confirming' "
            "into context['confirmed_hypotheses'], which build_generation_prompt "
            "renders under the header 'CONFIRMED HYPOTHESES' and SYSTEM_PROMPT tells "
            "the model to convert into a challenge ('If a confirmed hypothesis has an "
            "actionable recommendation...'). hypothesis_engine_lambda itself classifies "
            "'confirming' as PENDING, not confirmed (lines 1140-1141: pending = status "
            "in ('pending','confirming'); confirmed = status == 'confirmed'). So a "
            "hypothesis still under test is presented to the writer as established "
            "evidence, and the challenge it produces asserts a finding the data has "
            "not yet supported (ADR-104/105)."
        ),
    )
    def test_a_still_confirming_hypothesis_is_not_presented_as_confirmed(self, table):
        _hyp(table, "2026-08-01T00:00:00", "confirming", 4)
        assert "confirmed_hypotheses" not in chg.gather_context()


# ══════════════════════════════════════════════════════════════════════════════
# Health snapshot
# ══════════════════════════════════════════════════════════════════════════════


class TestHealthSnapshot:
    def test_averages_skip_unmeasured_nights_rather_than_scoring_them_zero(self, table):
        seed_date(table, "whoop", "2026-08-01", hrv=Decimal("50"), recovery_score=Decimal("60"))
        seed_date(table, "whoop", "2026-08-02")
        seed_date(table, "whoop", "2026-08-03", hrv=Decimal("60"), recovery_score=Decimal("80"))
        snap = chg.gather_context()["health_snapshot"]
        assert snap["avg_hrv"] == 55.0
        assert snap["avg_recovery"] == 70.0

    def test_a_window_of_unmeasured_nights_reports_absence_not_zero(self, table):
        seed_date(table, "whoop", "2026-08-01", sleep_duration_hours=Decimal("7"))
        snap = chg.gather_context()["health_snapshot"]
        assert snap["avg_hrv"] is None
        assert snap["avg_recovery"] is None

    def test_the_latest_weigh_in_of_the_window_is_the_one_reported(self, table):
        seed_date(table, "withings", "2026-08-01", weight_lbs=Decimal("321.6"))
        seed_date(table, "withings", "2026-08-05", weight_lbs=Decimal("318.4"))
        assert chg.gather_context()["health_snapshot"]["latest_weight"] == 318.4

    def test_a_weight_only_platform_still_produces_a_snapshot(self, table):
        seed_date(table, "withings", "2026-08-05", weight_lbs=Decimal("318.4"))
        assert chg.gather_context()["health_snapshot"] == {"latest_weight": 318.4}

    def test_a_window_with_no_weigh_in_reports_no_weight_at_all(self, table):
        seed_date(table, "whoop", "2026-08-01", hrv=Decimal("50"))
        assert "latest_weight" not in chg.gather_context()["health_snapshot"]


# ══════════════════════════════════════════════════════════════════════════════
# ADR-058 phase scoping on reads
# ══════════════════════════════════════════════════════════════════════════════


class TestPhaseScopedReads:
    def _seed_every_partition(self, table):
        seed(table, "notion", "DATE#2026-08-01#journal#morning", template="Morning", enriched_themes=["t"])
        seed_date(table, "habit_scores", "2026-08-01", tier0_pct=Decimal("1"))
        seed_date(table, "whoop", "2026-08-01", hrv=Decimal("50"))
        seed_date(table, "withings", "2026-08-01", weight_lbs=Decimal("318"))
        seed_date(table, "character_sheet", "2026-08-01", character_level=Decimal("3"))
        _hyp(table, "2026-08-01T00:00:00", "confirmed", 3)
        seed(table, "challenges", "CHALLENGE#a_2026-08-01", name="A", status="active", domain="sleep")

    def test_the_experiment_scoped_habit_window_is_phase_scoped(self, table):
        """habit_scores is EXPERIMENT_SCOPED, so a prior cycle's derived scores
        must not feed this cycle's challenges."""
        self._seed_every_partition(table)
        chg.gather_context()
        applied = dict(read_sources(table))
        assert source_reads_cross_phase("habit_scores") is False
        assert applied["habit_scores"] is True

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): gather_context's three direct partition "
            "reads — character_sheet (Limit=1 newest), hypotheses (HYPOTHESIS#) and "
            "challenges (CHALLENGE#) — call table.query() with a bare "
            "KeyConditionExpression and NO with_phase_filter, while the same "
            "function's query_range() reads go through digest_utils and are filtered. "
            "All three sources are EXPERIMENT_SCOPED in phase_taxonomy, so after a "
            "reset the wiped prior cycle's rows are still read as live (ADR-058 "
            "default-deny is bypassed on a get-style query path)."
        ),
    )
    def test_every_experiment_scoped_partition_read_is_phase_scoped(self, table):
        self._seed_every_partition(table)
        chg.gather_context()
        for source, applied in read_sources(table):
            if not source_reads_cross_phase(source):
                assert applied, f"{source} is EXPERIMENT_SCOPED but its read carries no phase filter"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery, #2109 class): query_range() calls "
            "digest_utils.query_range_list without include_pilot, so the ADR-058 "
            "filter is applied unconditionally to whoop / withings / notion — all "
            "RAW_TIMESERIES in phase_taxonomy, i.e. kept across resets and tagged "
            "phase='pilot' for every pre-genesis day. On a fresh cycle the 14-day "
            "windows therefore truncate to the cycle's AGE (genesis 2026-08-03 means "
            "a 4-day 'fourteen day' journal/HRV/weight window), and the generator "
            "mines a signal from a window it believes is 14 days long. #2109 fixed "
            "exactly this shape in six other compute readers via "
            "phase_filter.source_reads_cross_phase; this reader was not converted."
        ),
    )
    def test_a_raw_timeseries_window_is_not_truncated_to_the_cycle_age(self, table):
        self._seed_every_partition(table)
        chg.gather_context()
        for source, applied in read_sources(table):
            if source_reads_cross_phase(source):
                assert not applied, f"{source} is RAW_TIMESERIES but its 14-day window is clamped to the current phase"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery, reader-visible consequence of the "
            "unfiltered CHALLENGE# read above): a pre-genesis / wiped-cycle challenge "
            "still appears in context['existing_challenges'], which the prompt renders "
            "as 'EXISTING CHALLENGES (do NOT duplicate)'. The same module's "
            "store_challenge deliberately treats a tombstoned collision as ABSENT "
            "(#1969 — 'the fresh cycle may legitimately re-issue the challenge'), so "
            "the two halves of one Lambda disagree: the writer will re-issue what the "
            "prompt has just forbidden the model to propose."
        ),
    )
    def test_a_wiped_cycles_challenge_is_not_offered_as_an_existing_one(self, table):
        seed(table, "challenges", "CHALLENGE#old_2026-06-01", name="Old", status="active", domain="sleep", phase="pilot", tombstone=True)
        seed(table, "challenges", "CHALLENGE#live_2026-08-04", name="Live", status="candidate", domain="mental")
        names = [c["name"] for c in chg.gather_context()["existing_challenges"]]
        assert names == ["Live"]

    def test_existing_challenges_are_reduced_to_the_three_dedup_facets(self, table):
        seed(table, "challenges", "CHALLENGE#live_2026-08-04", name="Live", status="candidate", domain="mental", protocol="secret")
        assert chg.gather_context()["existing_challenges"] == [{"name": "Live", "status": "candidate", "domain": "mental"}]

    def test_a_dead_challenge_partition_never_aborts_the_gather(self, table):
        table.query_errors[_pk("challenges")] = RuntimeError("throttled")
        seed_date(table, "habit_scores", TODAY, tier0_pct=Decimal("1"))
        assert "existing_challenges" not in chg.gather_context()

    def test_a_window_read_follows_pagination_to_the_last_page(self, table):
        """A truncated first page silently shortens every 14-day signal."""
        table.pages = [
            {"Items": [seed_date(table, "whoop", "2026-08-01", hrv=Decimal("40"))], "LastEvaluatedKey": {"pk": "x", "sk": "y"}},
            {"Items": [seed_date(table, "whoop", "2026-08-02", hrv=Decimal("60"))]},
        ]
        assert len(chg.query_range("whoop", WINDOW_START, TODAY)) == 2

    def test_a_failed_window_read_degrades_to_an_empty_window(self, table):
        table.query_errors[_pk("whoop")] = RuntimeError("throttled")
        assert chg.query_range("whoop", WINDOW_START, TODAY) == []


# ══════════════════════════════════════════════════════════════════════════════
# The generation prompt
# ══════════════════════════════════════════════════════════════════════════════


def _prompt_allowlist(label):
    """The values SYSTEM_PROMPT tells the model are legal, read off the prompt."""
    line = next(ln for ln in chg.SYSTEM_PROMPT.splitlines() if ln.strip().startswith(f"- {label}"))
    return [v.strip().rstrip(".").split(" ")[0] for v in line.split(":", 1)[1].split(",")]


class TestGenerationPrompt:
    def test_every_context_block_reaches_the_writer(self, table):
        ctx = {
            "journal_14d": [{"date": "2026-08-01", "enriched_themes": ["avoidance"]}],
            "character": {"overall_level": 12},
            "habits": {"avg_tier0_completion": 75},
            "confirmed_hypotheses": [{"hypothesis": "caffeine"}],
            "health_snapshot": {"avg_hrv": 55.0},
            "existing_challenges": [{"name": "Live"}],
        }
        prompt = chg.build_generation_prompt(ctx)
        for needle in ("avoidance", "12", "75", "caffeine", "55.0", "Live"):
            assert needle in prompt

    def test_the_prompt_dates_itself_from_the_frozen_clock(self):
        prompt = chg.build_generation_prompt({})
        assert f"Today is {TODAY}" in prompt
        assert "(Friday)" in prompt  # 2026-08-07

    def test_the_journal_block_is_capped_so_one_verbose_fortnight_cannot_evict_the_rest(self):
        ctx = {
            "journal_14d": [{"date": "2026-08-01", "win_of_the_day": "x" * 200} for _ in range(200)],
            "existing_challenges": [{"name": "SentinelChallenge"}],
        }
        prompt = chg.build_generation_prompt(ctx)
        journal_block = prompt.split("JOURNAL ENTRIES", 1)[1].split("CHARACTER SHEET", 1)[0]
        assert len(journal_block) < 4200
        assert "SentinelChallenge" in prompt

    def test_an_empty_platform_still_produces_a_well_formed_prompt(self):
        prompt = chg.build_generation_prompt({})
        assert "EXISTING CHALLENGES" in prompt
        assert "Generate 1-5 challenge candidates" in prompt

    def test_a_broken_phase_context_never_blocks_generation(self, monkeypatch):
        """Grounding is mandatory but fail-soft — a missing ai_context must
        degrade the prompt, not kill the weekly run."""
        import ai.ai_context as ai_context

        monkeypatch.setattr(ai_context, "build_experiment_phase_context", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down")))
        assert chg._phase_context_block() == ""
        assert "JOURNAL ENTRIES" in chg.build_generation_prompt({})

    def test_decimal_context_values_survive_json_encoding_into_the_prompt(self):
        """The direct partition reads hand back Decimals; a TypeError here would
        take the weekly run down on a perfectly normal record."""
        prompt = chg.build_generation_prompt({"habits": {"avg_tier0_completion": Decimal("75")}})
        assert "75" in prompt

    def test_the_request_carries_the_cached_system_block_and_the_configured_model(self, monkeypatch):
        calls = stub_model(monkeypatch, payload={"challenges": []})
        chg.generate_challenges({})
        body = calls[0]
        assert body["model"] == chg.AI_MODEL
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert body["system"][0]["text"] == chg.SYSTEM_PROMPT
        assert body["messages"][0]["content"].startswith("Here is the current platform data")

    @pytest.mark.parametrize("domain", _prompt_allowlist("Domain must be one of"))
    def test_every_domain_the_prompt_offers_is_one_the_writer_accepts(self, table, domain):
        """Guard the SET: the expectation is read off SYSTEM_PROMPT, so adding a
        domain to the prompt without adding it to store_challenge's allowlist —
        which would silently relabel the challenge 'general' — fails here."""
        chg.store_challenge(candidate(name=f"Try {domain}", domain=domain))
        assert table.puts[-1]["domain"] == domain

    @pytest.mark.parametrize("difficulty", _prompt_allowlist("Difficulty"))
    def test_every_difficulty_the_prompt_offers_is_one_the_writer_accepts(self, table, difficulty):
        chg.store_challenge(candidate(name=f"Try {difficulty}", difficulty=difficulty))
        assert table.puts[-1]["difficulty"] == difficulty

    @pytest.mark.parametrize("source", ["journal_mining", "data_signal", "hypothesis_graduate", "science_scan"])
    def test_every_source_the_prompt_names_is_one_the_writer_accepts(self, table, source):
        assert f'"source": "{source}' in chg.SYSTEM_PROMPT or f"{source}|" in chg.SYSTEM_PROMPT or f"|{source}" in chg.SYSTEM_PROMPT
        chg.store_challenge(candidate(name=f"Try {source}", source=source))
        assert table.puts[-1]["source"] == source


# ══════════════════════════════════════════════════════════════════════════════
# The AI path — honest degradation
# ══════════════════════════════════════════════════════════════════════════════


class TestAiDegradation:
    def test_a_clean_json_response_is_parsed(self, monkeypatch):
        stub_model(monkeypatch, payload={"challenges": [candidate()], "reasoning": "because"})
        assert chg.generate_challenges({})["reasoning"] == "because"

    def test_a_fenced_response_is_unwrapped(self, monkeypatch):
        stub_model(monkeypatch, text='```json\n{"challenges": [], "reasoning": "quiet"}\n```')
        assert chg.generate_challenges({})["reasoning"] == "quiet"

    def test_a_single_line_fenced_response_is_unwrapped(self, monkeypatch):
        stub_model(monkeypatch, text='```{"challenges": [], "reasoning": "quiet"}```')
        assert chg.generate_challenges({})["reasoning"] == "quiet"

    def test_prose_instead_of_json_yields_nothing_rather_than_a_stub(self, monkeypatch):
        """The silent-stub trap: a chatty model must never be turned into a
        challenge the reader believes came from the data."""
        stub_model(monkeypatch, text="I could not find a clear signal this week.")
        assert chg.generate_challenges({}) is None

    def test_a_truncated_json_response_yields_nothing(self, monkeypatch):
        """max_tokens truncation is the common failure — half an object must
        not become half a challenge."""
        stub_model(monkeypatch, text='{"challenges": [{"name": "Half')
        assert chg.generate_challenges({}) is None

    def test_a_response_missing_its_content_envelope_yields_nothing(self, monkeypatch):
        stub_model(monkeypatch, response={"stop_reason": "max_tokens"})
        assert chg.generate_challenges({}) is None

    def test_a_guardrail_blocked_response_is_never_parsed_into_challenges(self, monkeypatch):
        """AI-3: a blocked generation must be dropped whole, not salvaged."""

        class _Blocked:
            blocked = True
            block_reason = "unsafe_medical_claim"

        monkeypatch.setattr(chg, "_HAS_AI_VALIDATOR", True)
        monkeypatch.setattr(chg, "validate_ai_output", lambda raw, kind: _Blocked(), raising=False)
        stub_model(monkeypatch, payload={"challenges": [candidate()]})
        assert chg.generate_challenges({}) is None

    def test_an_allowed_response_survives_validation(self, monkeypatch):
        class _Ok:
            blocked = False
            block_reason = None

        monkeypatch.setattr(chg, "_HAS_AI_VALIDATOR", True)
        monkeypatch.setattr(chg, "validate_ai_output", lambda raw, kind: _Ok(), raising=False)
        stub_model(monkeypatch, payload={"challenges": [], "reasoning": "ok"})
        assert chg.generate_challenges({})["reasoning"] == "ok"

    def test_a_budget_cutoff_is_not_swallowed_into_a_quiet_none(self, monkeypatch):
        """At tier 3 bedrock_client raises BudgetExceeded. That is an outage,
        not a week with no signal — it must not be caught here."""
        stub_model(monkeypatch, error=RuntimeError("BudgetExceeded"))
        with pytest.raises(RuntimeError):
            chg.generate_challenges({})


# ══════════════════════════════════════════════════════════════════════════════
# store_challenge — the write contract
# ══════════════════════════════════════════════════════════════════════════════


class TestStoreChallenge:
    def test_the_key_is_the_slugged_name_stamped_with_the_run_date(self, table):
        chg.store_challenge(candidate())
        item = table.puts[0]
        assert item["pk"] == chg.CHALLENGES_PK
        assert item["sk"] == f"CHALLENGE#kitchen-closed-at-eight_{TODAY}"
        assert item["challenge_id"] == f"kitchen-closed-at-eight_{TODAY}"

    def test_a_long_name_is_slugged_to_a_bounded_key(self, table):
        chg.store_challenge(candidate(name="A" * 200))
        assert len(table.puts[0]["challenge_id"]) == 50 + 1 + len(TODAY)

    def test_an_out_of_registry_domain_falls_back_to_general(self, table):
        chg.store_challenge(candidate(domain="astrology"))
        assert table.puts[0]["domain"] == "general"

    def test_an_out_of_registry_difficulty_falls_back_to_moderate(self, table):
        chg.store_challenge(candidate(difficulty="brutal"))
        assert table.puts[0]["difficulty"] == "moderate"

    def test_an_out_of_registry_source_falls_back_to_science_scan(self, table):
        chg.store_challenge(candidate(source="vibes"))
        assert table.puts[0]["source"] == "science_scan"

    def test_a_new_candidate_is_born_inactive_with_an_empty_outcome(self, table):
        """The reader surface must never show an un-reviewed candidate as run."""
        chg.store_challenge(candidate())
        item = table.puts[0]
        assert item["status"] == "candidate"
        assert item["outcome"] == ""
        assert item["activated_at"] == "" and item["completed_at"] == ""
        assert item["daily_checkins"] == []
        assert item["character_xp_awarded"] == 0

    def test_the_provenance_stamps_come_from_the_frozen_clock(self, table):
        chg.store_challenge(candidate())
        item = table.puts[0]
        assert item["generated_by"] == "challenge-generator"
        assert item["generated_at"] == "2026-08-07T17:00:00"
        assert item["created_at"] == item["generated_at"]

    def test_floats_become_decimals_before_the_write(self, table):
        """boto3 rejects native floats — a float target would fail the put."""
        chg.store_challenge(candidate(metric_targets={"hrv_ms": 55.5, "nested": {"pct": 0.75}}))
        targets = table.puts[0]["metric_targets"]
        assert targets["hrv_ms"] == Decimal("55.5")
        assert targets["nested"]["pct"] == Decimal("0.75")
        assert not any(isinstance(v, float) for v in targets.values())

    def test_a_non_finite_target_is_written_as_absent_not_as_nan(self, table):
        """Decimal('NaN') is unwritable; None is the honest sentinel (#1207)."""
        chg.store_challenge(candidate(metric_targets={"ratio": float("nan"), "cap": math.inf}))
        assert table.puts[0]["metric_targets"] == {"ratio": None, "cap": None}

    def test_a_live_duplicate_is_skipped_without_a_second_write(self, table):
        assert chg.store_challenge(candidate())
        assert chg.store_challenge(candidate()) is None
        assert len(table.puts) == 1

    def test_a_tombstoned_prior_cycle_row_is_treated_as_absent_and_reissued(self, table):
        """#1969: a same-day reset archives the old row; the fresh cycle is
        entitled to re-issue the challenge, and the put restamps it."""
        seed(table, "challenges", f"CHALLENGE#kitchen-closed-at-eight_{TODAY}", name="old", tombstone=True)
        assert chg.store_challenge(candidate())
        assert table.puts[0]["status"] == "candidate"

    def test_a_prior_phase_row_is_likewise_treated_as_absent(self, table):
        seed(table, "challenges", f"CHALLENGE#kitchen-closed-at-eight_{TODAY}", name="old", phase="pilot")
        assert chg.store_challenge(candidate())

    def test_a_model_supplied_status_cannot_activate_its_own_challenge(self, table):
        """Only Matthew activates. A model that returns status='active' must not
        be able to publish an unreviewed challenge as live."""
        chg.store_challenge(candidate(status="active", activated_at="2026-08-07T00:00:00"))
        assert table.puts[0]["status"] == "candidate"
        assert table.puts[0]["activated_at"] == ""

    def test_absent_narrative_fields_are_written_as_honest_empty_strings(self, table):
        chg.store_challenge({"name": "Bare"})
        item = table.puts[0]
        for field in ("description", "source_detail", "protocol", "success_criteria", "hoped_outcome"):
            assert item[field] == ""

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): store_challenge allowlists domain, "
            "difficulty and source but passes duration_days straight through "
            "int(challenge.get('duration_days', 7)). SYSTEM_PROMPT states the "
            "contract as 'Duration: 7-30 days', so a model returning 365 (or 0, or "
            "-1) writes a challenge whose stated duration the platform never agreed "
            "to and whose hoped_outcome was written against a different horizon — "
            "the exact class of silent out-of-range value the other three fields are "
            "guarded against."
        ),
    )
    @pytest.mark.parametrize("supplied", [0, -3, 365])
    def test_an_out_of_range_duration_is_clamped_to_the_documented_window(self, table, supplied):
        chg.store_challenge(candidate(name=f"Dur {supplied}", duration_days=supplied))
        assert 7 <= table.puts[-1]["duration_days"] <= 30

    def test_the_modules_own_slug_helper_refuses_to_produce_an_empty_key(self):
        """slug() has the guard store_challenge's inlined copy lacks — the two
        halves of one module disagree about what an unnamed challenge is keyed
        as. This pins the guarded half so the divergence below is unambiguous."""
        assert chg.slug("") == "challenge"
        assert chg.slug(None) == "challenge"
        assert chg.slug("Kitchen Closed At 8pm!") == "kitchen-closed-at-8pm"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): the module defines slug(), which returns "
            "'challenge' for a falsy name, but store_challenge re-implements the same "
            "regex inline WITHOUT that guard. A model returning name='' therefore "
            "writes sk='CHALLENGE#_<date>' with name='' — a nameless row on the "
            "reader-facing challenges surface, and a key that a second unnamed "
            "candidate in the same run collides with (silently dropped as a "
            "duplicate). The duplicated-logic half that has the guard is dead code."
        ),
    )
    def test_a_nameless_candidate_does_not_produce_a_keyless_challenge(self, table):
        challenge_id = chg.store_challenge(candidate(name=""))
        assert challenge_id and not challenge_id.startswith("_")
        assert table.puts[0]["name"]


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — gates, cap, dedup, fail-soft
# ══════════════════════════════════════════════════════════════════════════════


def stub_generation(monkeypatch, result):
    calls = []

    def _fake(ctx):
        calls.append(ctx)
        return result

    monkeypatch.setattr(chg, "generate_challenges", _fake)
    return calls


class TestHandlerGates:
    def test_a_totally_dead_platform_skips_without_calling_the_model(self, table, monkeypatch):
        for source in ("notion", "habit_scores", "whoop", "withings", "character_sheet", "hypotheses", "challenges"):
            table.query_errors[_pk(source)] = RuntimeError("throttled")
        calls = stub_generation(monkeypatch, {"challenges": []})
        assert chg.lambda_handler({}, None) == {"status": "skipped", "reason": "no_data"}
        assert calls == []

    def test_a_below_floor_sample_never_reaches_the_generator(self, table, monkeypatch):
        """ADR-105: two journal entries and nothing else is not a base a
        challenge can honestly be founded on."""
        seed(table, "notion", "DATE#2026-08-01#journal#morning", template="Morning", enriched_themes=["t"])
        seed(table, "notion", "DATE#2026-08-02#journal#morning", template="Morning", enriched_themes=["t"])
        calls = stub_generation(monkeypatch, {"challenges": [candidate()]})
        assert chg.lambda_handler({}, None) == {"status": "skipped", "reason": "insufficient_data"}
        assert calls == []
        assert table.puts == []

    def test_three_journal_entries_alone_clear_the_floor(self, table, monkeypatch):
        for i in range(3):
            seed(table, "notion", f"DATE#2026-08-0{i + 1}#journal#morning", template="Morning", enriched_themes=["t"])
        stub_generation(monkeypatch, {"challenges": []})
        assert chg.lambda_handler({}, None)["status"] == "completed"

    def test_a_character_sheet_alone_clears_the_floor(self, table, monkeypatch):
        seed_date(table, "character_sheet", TODAY, character_level=Decimal("12"), pillar_sleep={"level": Decimal("3")})
        stub_generation(monkeypatch, {"challenges": []})
        assert chg.lambda_handler({}, None)["status"] == "completed"

    def test_habit_history_alone_clears_the_floor(self, table, monkeypatch):
        seed_date(table, "habit_scores", "2026-08-01", tier0_pct=Decimal("0.5"))
        stub_generation(monkeypatch, {"challenges": []})
        assert chg.lambda_handler({}, None)["status"] == "completed"

    def test_a_response_without_a_challenges_key_stores_nothing(self, table, monkeypatch):
        seed_date(table, "habit_scores", "2026-08-01", tier0_pct=Decimal("0.5"))
        stub_generation(monkeypatch, {"reasoning": "I had thoughts"})
        resp = chg.lambda_handler({}, None)
        assert resp["generated"] == 0
        assert table.puts == []


class TestHandlerStorage:
    @pytest.fixture
    def ready(self, table):
        seed_date(table, "habit_scores", "2026-08-01", tier0_pct=Decimal("0.5"), missed_tier0=["steps"])
        return table

    def test_the_cap_bounds_how_many_candidates_one_week_can_add(self, ready, monkeypatch):
        """Derived from the module's own MAX_NEW_CHALLENGES so raising the cap
        cannot leave this test asserting the old ceiling."""
        over = chg.MAX_NEW_CHALLENGES + 3
        stub_generation(monkeypatch, {"challenges": [candidate(name=f"Challenge {i}") for i in range(over)]})
        resp = chg.lambda_handler({}, None)
        assert resp["generated"] == over
        assert resp["stored"] == chg.MAX_NEW_CHALLENGES
        assert len(ready.puts) == chg.MAX_NEW_CHALLENGES

    def test_the_stored_ids_name_exactly_the_rows_that_were_written(self, ready, monkeypatch):
        stub_generation(monkeypatch, {"challenges": [candidate(name="One"), candidate(name="Two")]})
        resp = chg.lambda_handler({}, None)
        assert resp["challenge_ids"] == [f"one_{TODAY}", f"two_{TODAY}"]
        assert [p["challenge_id"] for p in ready.puts] == resp["challenge_ids"]

    def test_a_repeat_of_an_existing_challenge_is_counted_generated_but_not_stored(self, ready, monkeypatch):
        seed(ready, "challenges", f"CHALLENGE#one_{TODAY}", name="One", status="candidate", domain="general")
        stub_generation(monkeypatch, {"challenges": [candidate(name="One"), candidate(name="Two")]})
        resp = chg.lambda_handler({}, None)
        assert (resp["generated"], resp["stored"]) == (2, 1)
        assert resp["challenge_ids"] == [f"two_{TODAY}"]

    def test_two_identically_named_candidates_in_one_batch_are_stored_once(self, ready, monkeypatch):
        stub_generation(monkeypatch, {"challenges": [candidate(name="Same"), candidate(name="Same", protocol="different")]})
        resp = chg.lambda_handler({}, None)
        assert resp["stored"] == 1
        assert len(ready.puts) == 1

    def test_a_zero_challenge_week_completes_without_writing_anything(self, ready, monkeypatch):
        stub_generation(monkeypatch, {"challenges": [], "reasoning": "no clear signal"})
        resp = chg.lambda_handler({}, None)
        assert (resp["status"], resp["generated"], resp["stored"]) == ("completed", 0, 0)
        assert ready.puts == []

    def test_the_reasoning_is_carried_back_but_bounded(self, ready, monkeypatch):
        stub_generation(monkeypatch, {"challenges": [], "reasoning": "R" * 900})
        assert len(chg.lambda_handler({}, None)["reasoning"]) == 500

    def test_the_run_reports_its_own_elapsed_time(self, ready, monkeypatch):
        stub_generation(monkeypatch, {"challenges": []})
        assert chg.lambda_handler({}, None)["elapsed_seconds"] >= 0


class TestHandlerFailSoft:
    @pytest.fixture
    def ready(self, table):
        seed_date(table, "habit_scores", "2026-08-01", tier0_pct=Decimal("0.5"))
        return table

    def test_an_unparseable_model_response_stores_nothing(self, ready, monkeypatch):
        stub_generation(monkeypatch, None)
        assert ready.puts == [] and chg.lambda_handler({}, None)["generated"] == 0

    def test_an_empty_model_envelope_is_reported_as_an_error_not_a_success(self, ready, monkeypatch):
        """resp['content'][0] on an empty content list raises; the run must
        surface that rather than claim a completed generation."""
        stub_model(monkeypatch, response={"content": []})
        resp = chg.lambda_handler({}, None)
        assert resp["status"] == "error"
        assert ready.puts == []

    def test_a_bedrock_outage_is_reported_as_an_error(self, ready, monkeypatch):
        stub_model(monkeypatch, error=RuntimeError("BudgetExceeded"))
        assert chg.lambda_handler({}, None)["status"] == "error"

    def test_a_write_failure_surfaces_instead_of_reporting_phantom_challenges(self, ready, monkeypatch):
        stub_generation(monkeypatch, {"challenges": [candidate()]})
        monkeypatch.setattr(ready, "put_item", lambda **kw: (_ for _ in ()).throw(RuntimeError("ProvisionedThroughputExceeded")))
        resp = chg.lambda_handler({}, None)
        assert resp["status"] == "error"
        assert "stored" not in resp

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): the store loop in lambda_handler has no "
            "per-candidate isolation, and store_challenge coerces duration with a "
            "bare int(...). One malformed candidate (duration_days='seven' or null — "
            "both trivially producible by a free-text model) raises ValueError/"
            "TypeError out of the loop into the handler's blanket except, so the run "
            "returns {'status':'error'} and reports NEITHER the challenges it already "
            "wrote NOR the ones it never reached. The rows are in DynamoDB; the "
            "response, the logs and the CloudWatch metric all say the week produced "
            "nothing."
        ),
    )
    def test_one_malformed_candidate_does_not_discard_the_rest_of_the_batch(self, ready, monkeypatch):
        stub_generation(
            monkeypatch,
            {"challenges": [candidate(name="Good One"), candidate(name="Bad", duration_days="seven"), candidate(name="Good Two")]},
        )
        resp = chg.lambda_handler({}, None)
        assert resp["status"] == "completed"
        assert resp["stored"] == 2

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): generate_challenges returns None for an "
            "AI-3 guardrail BLOCK and for a parse failure alike, and lambda_handler "
            "maps None to {'status':'completed','generated':0,'reason':'no_signal'}. "
            "A blocked or unparseable generation is therefore published to the caller "
            "and to CloudWatch as a genuine quiet week — indistinguishable from the "
            "model honestly finding nothing. ADR-104: the platform must not report an "
            "AI failure as a data finding. The contrast is inside this same handler: "
            "a Bedrock exception DOES surface as status='error'."
        ),
    )
    def test_a_blocked_generation_is_not_reported_as_a_no_signal_week(self, ready, monkeypatch):
        class _Blocked:
            blocked = True
            block_reason = "unsafe_medical_claim"

        monkeypatch.setattr(chg, "_HAS_AI_VALIDATOR", True)
        monkeypatch.setattr(chg, "validate_ai_output", lambda raw, kind: _Blocked(), raising=False)
        stub_model(monkeypatch, payload={"challenges": [candidate()]})
        resp = chg.lambda_handler({}, None)
        assert resp.get("reason") != "no_signal"
