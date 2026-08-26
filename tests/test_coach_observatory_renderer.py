"""tests/test_coach_observatory_renderer.py — unit tests for the observatory card renderer (#1658).

`lambdas/coach/coach_observatory_renderer.py` is what the observatory page
actually shows about each coach, so the assertions here are about rendered
content: which analysis text wins, which open thread is quoted, how a
down-calibrated confidence ledger reads, what the track-record sentence says,
and that a coach with no OUTPUT# record degrades to an empty card instead of
crashing the page.

Hermetic by construction:
  - `table` is a hand-written in-memory double that evaluates the real boto3
    `Key(...)` condition trees (no MagicMock — a non-terminating mock inside
    the renderer's pagination loop has OOM'd this repo's CI runner before),
    and it honours the ADR-058 phase FilterExpression.
  - `datetime` is frozen inside the module under test, so the 30-day windows
    and the experiment-week arithmetic are exact rather than wall-clock
    dependent. No fixture date is ever compared against a real now().
"""

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_observatory_renderer as cobs  # noqa: E402
from common.constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402

SLEEP_PK = "COACH#sleep_coach"
NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# HAND-WRITTEN FAKES
# ══════════════════════════════════════════════════════════════════════════════


class FakeTable:
    """In-memory DynamoDB Table double that evaluates real boto3 key conditions.

    `query()` walks the `Key(...)` expression tree (Eq / begins_with / BETWEEN,
    combined with AND), applies the ADR-058 phase FilterExpression when
    `with_phase_filter` injected one, then honours ScanIndexForward and Limit —
    which is exactly the surface `_query_begins_with` depends on. `pages`
    lets a test force LastEvaluatedKey pagination.
    """

    def __init__(self, rows=None, fail=False, page_size=None):
        self.rows = [dict(r) for r in (rows or [])]
        self.fail = fail
        self.page_size = page_size
        self.queries = []

    # ── condition-tree evaluation ──
    @staticmethod
    def _matches(condition, item):
        expr = condition.get_expression()
        operator = expr["operator"]
        values = expr["values"]
        if operator == "AND":
            return all(FakeTable._matches(v, item) for v in values)
        attr = values[0].name
        actual = str(item.get(attr, ""))
        if operator == "=":
            return actual == values[1]
        if operator == "begins_with":
            return actual.startswith(values[1])
        if operator == "BETWEEN":
            return values[1] <= actual <= values[2]
        raise AssertionError(f"FakeTable cannot evaluate operator {operator!r}")

    def query(self, **kwargs):
        if self.fail:
            raise RuntimeError("simulated DynamoDB query failure")
        self.queries.append(kwargs)
        items = [dict(r) for r in self.rows if self._matches(kwargs["KeyConditionExpression"], r)]
        if kwargs.get("FilterExpression"):
            values = kwargs.get("ExpressionAttributeValues", {})
            current = values.get(":phase_experiment")
            items = [i for i in items if i.get("phase") in (None, current)]
        items.sort(key=lambda i: str(i.get("sk", "")), reverse=not kwargs.get("ScanIndexForward", True))

        start = kwargs.get("ExclusiveStartKey")
        if start:
            keys = [str(i.get("sk")) for i in items]
            items = items[keys.index(str(start["sk"])) + 1 :]
        resp = {"Items": items}
        if self.page_size and len(items) > self.page_size:
            resp["Items"] = items[: self.page_size]
            resp["LastEvaluatedKey"] = {"pk": resp["Items"][-1]["pk"], "sk": resp["Items"][-1]["sk"]}
        return resp

    def get_item(self, Key=None, **kwargs):
        if self.fail:
            raise RuntimeError("simulated DynamoDB get failure")
        for row in self.rows:
            if row.get("pk") == Key.get("pk") and row.get("sk") == Key.get("sk"):
                return {"Item": dict(row)}
        return {}


class FrozenDatetime(datetime):
    """datetime with a pinned now() — everything else is the real class."""

    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(cobs, "datetime", FrozenDatetime)


def _install(monkeypatch, rows=None, **kwargs):
    table = FakeTable(rows=rows, **kwargs)
    monkeypatch.setattr(cobs, "table", table)
    return table


def _output(sk="OUTPUT#2026-08-09", pk=SLEEP_PK, **fields):
    return {"pk": pk, "sk": sk, **fields}


# ══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE LANGUAGE + PROVENANCE
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "confidence,expected",
    [
        (None, "preliminary"),  # absence is NOT scored as low confidence
        (1.0, "highly_confident"),
        (0.85, "highly_confident"),  # exact boundary
        (0.8499, "fairly_confident"),
        (0.7, "fairly_confident"),
        (0.6999, "moderate"),
        (0.5, "moderate"),
        (0.4999, "preliminary"),
        (0.3, "preliminary"),
        (0.2999, "uncertain"),
        (0.0, "uncertain"),
    ],
)
def test_confidence_to_language_tiers(confidence, expected):
    assert cobs._confidence_to_language(confidence) == expected


def test_confidence_provenance_counts_data_and_conversation():
    records = [
        {"source": "data"},
        {"source": "conversation"},
        {"source": "conversation"},
        {},  # pre-#1481 rows have no source — they are data-path rows
        {"source": "telepathy"},  # an unknown source is never invented as its own bucket
    ]
    assert cobs._confidence_provenance(records) == {"data": 3, "conversation": 2}


@pytest.mark.parametrize("empty", [None, []])
def test_confidence_provenance_empty(empty):
    assert cobs._confidence_provenance(empty) == {"data": 0, "conversation": 0}


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"mean_confidence": 0.72}, 0.72),  # precomputed value wins
        ({"mean_confidence": Decimal("0.4")}, 0.4),
        ({"mean_confidence": "junk", "alpha": 3, "beta_param": 1}, 0.75),  # unparseable → fall through
        ({"alpha": 3, "beta_param": 1}, 0.75),  # the writers' real field name
        ({"alpha": 1, "beta_param": 3}, 0.25),  # a down-calibration must LOWER it (#1792)
        ({"alpha": 3, "beta": 1}, 0.75),  # legacy pre-rename seed
        ({}, 0.5),  # uninformed Beta(1,1) prior
        ({"alpha": 4}, 0.8),  # missing beta defaults to the prior's 1
        ({"alpha": None, "beta_param": 2}, None),
        ({"alpha": 2, "beta_param": None}, None),
        ({"alpha": 0, "beta_param": 0}, None),  # zero division is not a confidence
        ({"alpha": "x", "beta_param": 1}, None),
    ],
)
def test_record_mean_confidence(record, expected):
    got = cobs._record_mean_confidence(record)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_beta_param_is_read_in_preference_to_stale_beta():
    """#1792: `beta_param` is what the writers emit; a bare `beta` must not win."""
    assert cobs._record_mean_confidence({"alpha": 1, "beta_param": 9, "beta": 1}) == pytest.approx(0.1)


def test_tally_learning_statuses_excludes_conversation_channel():
    items = [
        {"status": "confirmed"},
        {"status": "confirmed", "channel": "data"},
        {"status": "refuted"},
        {"status": "inconclusive"},
        {"status": "expired"},
        {"status": "confirmed", "channel": "conversation"},  # never enters the hit rate
        {"status": "refuted", "channel": "conversation"},
        {"status": "not_a_status"},  # unknown statuses are ignored, not counted
        {},
    ]
    counts, conversation = cobs._tally_learning_statuses(items)
    assert counts == {"confirmed": 2, "refuted": 1, "inconclusive": 1, "expired": 1}
    assert conversation == 2


@pytest.mark.parametrize("empty", [None, []])
def test_tally_learning_statuses_empty(empty):
    assert cobs._tally_learning_statuses(empty) == ({"confirmed": 0, "refuted": 0, "inconclusive": 0, "expired": 0}, 0)


# ══════════════════════════════════════════════════════════════════════════════
# DDB READ HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def test_get_item_converts_decimals(monkeypatch):
    _install(monkeypatch, [{"pk": SLEEP_PK, "sk": "RELATIONSHIP#state", "rapport_level": Decimal("0.6")}])
    item = cobs._get_item(SLEEP_PK, "RELATIONSHIP#state")
    assert item["rapport_level"] == 0.6
    assert isinstance(item["rapport_level"], float)


def test_get_item_hides_tombstoned_and_stale_phase_singletons(monkeypatch):
    """#1969: get_item bypasses the query filter, so a wiped cycle's relationship
    state would otherwise keep rendering after an experiment restart."""
    rows = [
        {"pk": SLEEP_PK, "sk": "RELATIONSHIP#state", "tombstone": True, "journey_phase": "wiped"},
        {"pk": "COACH#mind_coach", "sk": "RELATIONSHIP#state", "phase": "pilot", "journey_phase": "old_cycle"},
        {"pk": "COACH#labs_coach", "sk": "RELATIONSHIP#state", "phase": EXPERIMENT_PHASE_CURRENT, "journey_phase": "trust"},
    ]
    _install(monkeypatch, rows)
    assert cobs._get_item(SLEEP_PK, "RELATIONSHIP#state") is None
    assert cobs._get_item("COACH#mind_coach", "RELATIONSHIP#state") is None
    assert cobs._get_item("COACH#labs_coach", "RELATIONSHIP#state")["journey_phase"] == "trust"


def test_get_item_missing_or_failing_returns_none(monkeypatch):
    _install(monkeypatch, [])
    assert cobs._get_item(SLEEP_PK, "RELATIONSHIP#state") is None
    _install(monkeypatch, [], fail=True)
    assert cobs._get_item(SLEEP_PK, "RELATIONSHIP#state") is None


def test_query_begins_with_filters_sorts_and_limits(monkeypatch):
    rows = [
        _output(sk="OUTPUT#2026-08-07", content="oldest"),
        _output(sk="OUTPUT#2026-08-09", content="newest"),
        _output(sk="OUTPUT#2026-08-08", content="middle"),
        _output(sk="THREAD#a", topic="not an output"),
        _output(sk="OUTPUT#2026-08-06", pk="COACH#mind_coach", content="other coach"),
    ]
    _install(monkeypatch, rows)
    newest = cobs._query_begins_with(SLEEP_PK, "OUTPUT#", scan_forward=False, limit=1)
    assert [i["content"] for i in newest] == ["newest"]
    ascending = cobs._query_begins_with(SLEEP_PK, "OUTPUT#")
    assert [i["content"] for i in ascending] == ["oldest", "middle", "newest"]


def test_query_begins_with_paginates_to_completion(monkeypatch):
    rows = [_output(sk=f"OUTPUT#2026-08-{day:02d}", content=str(day)) for day in range(1, 8)]
    _install(monkeypatch, rows, page_size=2)
    got = cobs._query_begins_with(SLEEP_PK, "OUTPUT#")
    assert [i["content"] for i in got] == [str(d) for d in range(1, 8)]


def test_query_begins_with_hides_pilot_phase_rows(monkeypatch):
    rows = [
        _output(sk="OUTPUT#2026-08-08", content="wiped cycle", phase="pilot"),
        _output(sk="OUTPUT#2026-08-07", content="current cycle", phase=EXPERIMENT_PHASE_CURRENT),
    ]
    _install(monkeypatch, rows)
    assert [i["content"] for i in cobs._query_begins_with(SLEEP_PK, "OUTPUT#")] == ["current cycle"]


def test_query_begins_with_converts_decimals_and_survives_failure(monkeypatch):
    _install(monkeypatch, [_output(reference_count=Decimal("3"))])
    assert cobs._query_begins_with(SLEEP_PK, "OUTPUT#")[0]["reference_count"] == 3.0
    _install(monkeypatch, [], fail=True)
    assert cobs._query_begins_with(SLEEP_PK, "OUTPUT#") == []


# ══════════════════════════════════════════════════════════════════════════════
# EXPERIMENT TIMING
# ══════════════════════════════════════════════════════════════════════════════


def test_compute_experiment_timing_counts_day_one_inclusively(monkeypatch):
    monkeypatch.setattr(cobs, "EXPERIMENT_START", "2026-08-10")  # frozen "today"
    assert cobs._compute_experiment_timing() == (1, 1)

    monkeypatch.setattr(cobs, "EXPERIMENT_START", "2026-08-04")
    assert cobs._compute_experiment_timing() == (1, 7)  # day 7 is still week 1

    monkeypatch.setattr(cobs, "EXPERIMENT_START", "2026-08-03")
    assert cobs._compute_experiment_timing() == (2, 8)  # day 8 opens week 2


def test_compute_experiment_timing_clamps_pre_genesis_and_bad_config(monkeypatch):
    monkeypatch.setattr(cobs, "EXPERIMENT_START", "2026-12-25")  # countdown: genesis is in the future
    assert cobs._compute_experiment_timing() == (1, 1)
    monkeypatch.setattr(cobs, "EXPERIMENT_START", "not-a-date")
    assert cobs._compute_experiment_timing() == (1, 1)


# ══════════════════════════════════════════════════════════════════════════════
# CARD ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════


def test_unknown_domain_card(monkeypatch):
    _install(monkeypatch, [])
    assert cobs._render_coach_card("astrology") == {"domain": "astrology", "analysis": None, "error": "unknown_domain"}


def test_empty_card_when_coach_has_no_output(monkeypatch):
    """A coach that has never run must render the empty state, not raise."""
    _install(monkeypatch, [{"pk": SLEEP_PK, "sk": "RELATIONSHIP#state", "journey_phase": "trust"}])
    card = cobs._render_coach_card("sleep")
    assert card == {"coach_id": "sleep_coach", "domain": "sleep", "analysis": None}


def test_card_renders_output_content_and_coach_identity(monkeypatch):
    _install(monkeypatch, [_output(content="Full-length coach output.", created_at="2026-08-09T12:00:00Z")])
    card = cobs._render_coach_card("sleep")
    assert card["analysis"] == "Full-length coach output."
    assert card["coach_name"] == "Dr. Lisa Park"
    assert card["coach_initials"] == "LP"
    # #2757: title/color now derive from the persona registry (config/personas.json)
    # rather than a hand-typed copy that had drifted from it.
    #   - title: the PRE-FIX literal "Sleep & Circadian Rhythm Specialist" is the
    #     descriptive title readers actually saw, so #2757 PROMOTED it into the
    #     registry's own `title` field (registry held the shorter "Sleep &
    #     Recovery" before) rather than discarding it — this assertion is
    #     therefore unchanged from before this issue's fix landed.
    #   - color: "#818cf8", and the reasoning here CHANGED on 2026-08-20 — recorded
    #     rather than quietly edited. #2757 first moved the registry to the roster-v2
    #     "#8b5cf6" (this pin briefly asserted that). The post-deploy visual-QA sweep
    #     then failed /coaching/ and /method/board/ with a NEW *serious* axe
    #     color-contrast violation on exactly the sleep nodes. Measured against the
    #     page background token #16130E: "#8b5cf6" = 4.37:1, under the WCAG AA 4.5:1
    #     floor for normal text; "#818cf8" = 6.21:1. So the registry now carries
    #     "#818cf8" on ACCESSIBILITY grounds, not palette lineage — and #2757's
    #     structural fix is untouched, because both surfaces still derive this one
    #     value from the registry. That the colour was a one-line change is exactly
    #     what the issue set out to achieve.
    assert card["coach_title"] == "Sleep & Circadian Rhythm Specialist"
    assert card["coach_color"] == "#818cf8"
    assert card["generated_at"] == "2026-08-09T12:00:00Z"
    assert card["confidence_language"] == "preliminary"  # no CONFIDENCE# rows yet
    assert card["themes"] == []
    # None-valued fields are stripped rather than shipped as nulls
    assert "key_recommendation" not in card
    assert "thread_reference" not in card


def test_card_prefers_observatory_summary_over_full_content(monkeypatch):
    _install(
        monkeypatch,
        [
            _output(
                observatory_summary="The short version for the card.",
                content="The long version for the coach thread.",
                generated_at="2026-08-09T00:00:00Z",
                themes=["wind-down", "consistency"],
                key_recommendation="Anchor the wake time.",
                elena_quote="Notice what the evening asks of you.",
            ),
            # #3172: journaling_prompt is NEVER on the OUTPUT# row — it lives on the
            # ai_analysis EXPERT# row generate_and_cache actually writes. Putting it
            # here instead would be the fixture-not-the-wire defect this pair-contract
            # issue exists to kill.
            {"pk": f"{cobs.USER_PREFIX}ai_analysis", "sk": "EXPERT#sleep", "journaling_prompt": "What made last night different?"},
        ],
    )
    card = cobs._render_coach_card("sleep")
    assert card["analysis"] == "The short version for the card."
    assert card["themes"] == ["wind-down", "consistency"]
    assert card["key_recommendation"] == "Anchor the wake time."
    assert card["elena_quote"] == "Notice what the evening asks of you."
    assert card["journaling_prompt"] == "What made last night different?"
    assert card["generated_at"] == "2026-08-09T00:00:00Z"  # falls back from created_at


def test_card_journaling_prompt_training_domain_aliases_to_the_physical_expert_key(monkeypatch):
    """#3172: `training` has no ai_analysis EXPERT# row of its own — the coaching-team
    v2 merge folded it into physical_coach, and ai_expert_analyzer_lambda's roster
    never grew a separate "training" expert_key to match. The alias must resolve it."""
    _install(
        monkeypatch,
        [
            _output(sk="OUTPUT#2026-08-09", pk="COACH#physical_coach", observatory_summary="Training summary."),
            {"pk": f"{cobs.USER_PREFIX}ai_analysis", "sk": "EXPERT#physical", "journaling_prompt": "What's the load telling you?"},
        ],
    )
    card = cobs._render_coach_card("training")
    assert card["journaling_prompt"] == "What's the load telling you?"


def test_card_journaling_prompt_is_absent_when_no_ai_analysis_record_exists(monkeypatch):
    """No EXPERT# row yet (e.g. the analyzer hasn't run this cycle) degrades to None,
    which the card's None-stripping step (#3172-adjacent, pre-existing behavior) drops."""
    _install(monkeypatch, [_output(observatory_summary="Short version.")])
    card = cobs._render_coach_card("sleep")
    assert "journaling_prompt" not in card


def test_card_quotes_the_most_referenced_open_thread(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": SLEEP_PK, "sk": "THREAD#1", "status": "open", "reference_count": 2, "summary": "the 11pm drift"},
        {"pk": SLEEP_PK, "sk": "THREAD#2", "status": "open", "reference_count": 5, "summary": "the caffeine cutoff"},
        {"pk": SLEEP_PK, "sk": "THREAD#3", "status": "closed", "reference_count": 99, "summary": "already settled"},
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["thread_reference"] == "the caffeine cutoff"
    assert "thread_reference" not in cobs._render_coach_card("sleep", include_threads=False)


def test_card_thread_reference_falls_back_to_topic(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": SLEEP_PK, "sk": "THREAD#1", "status": "open", "topic": "late meals"},
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["thread_reference"] == "late meals"


def test_card_carries_relationship_state(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": SLEEP_PK, "sk": "RELATIONSHIP#state", "journey_phase": "established_trust", "rapport_level": Decimal("0.72")},
    ]
    _install(monkeypatch, rows)
    card = cobs._render_coach_card("sleep")
    assert card["journey_phase"] == "established_trust"
    assert card["rapport_level"] == 0.72


def test_card_names_the_other_coach_in_an_active_disagreement(monkeypatch):
    rows = [
        _output(content="analysis"),
        {
            "pk": "ENSEMBLE#digest",
            "sk": "CYCLE#2026-08-09",
            "active_disagreements": [
                {"coaches": ["nutrition_coach", "physical_coach"], "topic": "the deficit size"},
                {"coaches": ["sleep_coach", "mind_coach"], "topic": "evening screen time"},
            ],
        },
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["cross_coach_reference"] == "Dr. Nathan Reeves's notes on evening screen time"


def test_card_reads_disagreements_stored_as_a_json_string(monkeypatch):
    rows = [
        _output(content="analysis"),
        {
            "pk": "ENSEMBLE#digest",
            "sk": "CYCLE#2026-08-09",
            "active_disagreements": json.dumps([{"coaches": ["sleep_coach", "glucose_coach"], "topic": "late carbs"}]),
        },
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["cross_coach_reference"] == "Dr. Amara Patel's notes on late carbs"


def test_card_falls_back_to_team_input_request(monkeypatch):
    rows = [
        _output(content="analysis"),
        {
            "pk": "ENSEMBLE#digest",
            "sk": "CYCLE#2026-08-09",
            "active_disagreements": "{not json}",  # unparseable → ignored, not fatal
            "coach_summaries": [
                {"coach_id": "mind_coach", "wants_team_input_on": ["something else"]},
                {"coach_id": "sleep_coach", "wants_team_input_on": ["the 3am wakeups", "naps"]},
            ],
        },
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["cross_coach_reference"] == "Requesting team input on: the 3am wakeups"


def test_card_has_no_cross_coach_reference_when_the_digest_ignores_this_coach(monkeypatch):
    rows = [
        _output(content="analysis"),
        {
            "pk": "ENSEMBLE#digest",
            "sk": "CYCLE#2026-08-09",
            "active_disagreements": [{"coaches": ["nutrition_coach", "physical_coach"], "topic": "the deficit size"}],
            "coach_summaries": json.dumps([{"coach_id": "sleep_coach", "wants_team_input_on": []}]),
        },
    ]
    _install(monkeypatch, rows)
    assert "cross_coach_reference" not in cobs._render_coach_card("sleep")


def test_card_survives_unparseable_coach_summaries(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": "ENSEMBLE#digest", "sk": "CYCLE#2026-08-09", "active_disagreements": [], "coach_summaries": "{not json}"},
    ]
    _install(monkeypatch, rows)
    card = cobs._render_coach_card("sleep")
    assert card["analysis"] == "analysis"
    assert "cross_coach_reference" not in card


# ── ensemble_fallback disclosure (#2333) ───────────────────────────────────────
# coach_ensemble_digest stamps `_fallback: True` on a digest produced without the
# LLM (budget-paused at tier >= 1, ADR-125 — the common case per #1927, not the
# rare one). Nothing here checked the mark, so a template-generated digest
# rendered on the observatory indistinguishably from a genuine cross-coach read.


def test_card_flags_ensemble_fallback_when_the_digest_is_fallback_generated(monkeypatch):
    rows = [
        _output(content="analysis"),
        {
            "pk": "ENSEMBLE#digest",
            "sk": "CYCLE#2026-08-09",
            "_fallback": True,
            "active_disagreements": [],
            "coach_summaries": [],
        },
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["ensemble_fallback"] is True


def test_card_ensemble_fallback_false_for_a_genuine_digest(monkeypatch):
    rows = [
        _output(content="analysis"),
        {
            "pk": "ENSEMBLE#digest",
            "sk": "CYCLE#2026-08-09",
            "active_disagreements": [{"coaches": ["nutrition_coach", "physical_coach"], "topic": "the deficit size"}],
            "coach_summaries": [],
        },
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["ensemble_fallback"] is False


def test_card_ensemble_fallback_false_with_no_digest_at_all(monkeypatch):
    rows = [_output(content="analysis")]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["ensemble_fallback"] is False


def test_card_still_renders_when_the_window_queries_fail(monkeypatch):
    """The track-record and proactivity reads are best-effort — a failure must not
    take the whole card down."""

    class BetweenFailsTable(FakeTable):
        def query(self, **kwargs):
            if "BETWEEN" in _operators(kwargs["KeyConditionExpression"]):
                raise RuntimeError("simulated DynamoDB failure on the windowed read")
            return super().query(**kwargs)

    def _operators(condition):
        expr = condition.get_expression()
        ops = [expr["operator"]]
        for value in expr["values"]:
            if hasattr(value, "get_expression"):
                ops.extend(_operators(value))
        return ops

    table = BetweenFailsTable(rows=[_output(content="analysis")])
    monkeypatch.setattr(cobs, "table", table)
    card = cobs._render_coach_card("sleep")
    assert card["analysis"] == "analysis"
    assert "track_record" not in card
    assert "proactivity" not in card


def test_card_data_availability_takes_the_most_conservative_level(monkeypatch):
    guardrails = {
        "whoop": {
            "sleep_efficiency": {"level": "established"},
            "hrv": {"level": "preliminary"},
            "respiratory_rate": {"level": "observational_only"},
        },
        "withings": {"weight": {"level": "established"}},
    }
    rows = [
        _output(content="analysis"),
        {"pk": "COACH#computation", "sk": "RESULTS#2026-08-09", "statistical_guardrails": json.dumps(guardrails)},
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["data_availability"] == "observational_only"


def test_card_data_availability_reads_a_dict_valued_guardrail(monkeypatch):
    guardrails = {"whoop": {"sleep_efficiency": {"level": "established"}, "hrv": {"level": "established"}}}
    rows = [
        _output(content="analysis"),
        {"pk": "COACH#computation", "sk": "RESULTS#2026-08-09", "statistical_guardrails": guardrails},
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["data_availability"] == "established"


def test_card_omits_data_availability_when_the_source_is_absent_or_unparseable(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": "COACH#computation", "sk": "RESULTS#2026-08-09", "statistical_guardrails": "{oops"},
    ]
    _install(monkeypatch, rows)
    assert "data_availability" not in cobs._render_coach_card("sleep")

    rows[1]["statistical_guardrails"] = json.dumps({"macrofactor": {"protein": {"level": "established"}}})
    _install(monkeypatch, rows)
    assert "data_availability" not in cobs._render_coach_card("sleep")  # no whoop entry for the sleep domain


def test_card_confidence_language_averages_the_ledger_and_reports_provenance(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": SLEEP_PK, "sk": "CONFIDENCE#sleep_quality", "alpha": 9, "beta_param": 1, "source": "data"},  # 0.90
        {"pk": SLEEP_PK, "sk": "CONFIDENCE#timing", "mean_confidence": Decimal("0.8"), "source": "conversation"},
    ]
    _install(monkeypatch, rows)
    card = cobs._render_coach_card("sleep")
    assert card["confidence_language"] == "highly_confident"  # mean 0.85 → exact boundary
    assert card["confidence_provenance"] == {"data": 1, "conversation": 1}


def test_card_confidence_drops_when_the_ledger_is_calibrated_down(monkeypatch):
    """#1792: a down-calibration increments beta_param — the card must show it."""
    up = [_output(content="analysis"), {"pk": SLEEP_PK, "sk": "CONFIDENCE#sleep_quality", "alpha": 9, "beta_param": 1}]
    _install(monkeypatch, up)
    assert cobs._render_coach_card("sleep")["confidence_language"] == "highly_confident"

    down = [_output(content="analysis"), {"pk": SLEEP_PK, "sk": "CONFIDENCE#sleep_quality", "alpha": 1, "beta_param": 9}]
    _install(monkeypatch, down)
    assert cobs._render_coach_card("sleep")["confidence_language"] == "uncertain"


def test_card_revision_signal_formats_the_date_and_reason(monkeypatch):
    rows = [
        _output(content="analysis"),
        {
            "pk": SLEEP_PK,
            "sk": "LEARNING#2026-08-09",
            "type": "position_revision",
            "date": "2026-08-04",
            "reason": "the CGM data disagreed",
        },
    ]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["revision_signal"] == "Updated from my August 4 assessment — the CGM data disagreed"


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"evaluation_type": "position_revision", "date": "2026-08-04"}, "Updated from my August 4 assessment"),
        ({"type": "position_revision", "date": "not-a-date"}, "Updated from not-a-date assessment"),
        ({"type": "position_revision", "summary": "no date at all"}, "Recently revised position"),
    ],
)
def test_card_revision_signal_variants(monkeypatch, record, expected):
    rows = [_output(content="analysis"), {"pk": SLEEP_PK, "sk": "LEARNING#2026-08-09", **record}]
    _install(monkeypatch, rows)
    assert cobs._render_coach_card("sleep")["revision_signal"] == expected


def test_card_has_no_revision_signal_for_ordinary_learnings(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-08-09", "type": "prediction", "status": "confirmed"},
    ]
    _install(monkeypatch, rows)
    assert "revision_signal" not in cobs._render_coach_card("sleep")


def test_card_track_record_counts_only_the_last_thirty_days(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-08-09", "status": "confirmed"},
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-08-05", "status": "confirmed"},
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-08-01", "status": "confirmed"},
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-07-28", "status": "refuted"},
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-07-20", "status": "inconclusive"},
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-06-01", "status": "refuted"},  # older than the window
    ]
    _install(monkeypatch, rows)
    track = cobs._render_coach_card("sleep")["track_record"]
    assert track["window_days"] == 30
    assert track["confirmed"] == 3
    assert track["refuted"] == 1
    assert track["inconclusive"] == 1
    assert track["decided_count"] == 4
    assert track["hit_rate_pct"] == 75
    assert track["summary"] == "3 of 4 predictions confirmed in last 30 days"


def test_card_track_record_keeps_conversation_learnings_out_of_the_hit_rate(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-08-09", "status": "confirmed"},
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-08-08", "status": "refuted"},
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-08-07", "status": "confirmed", "channel": "conversation"},
    ]
    _install(monkeypatch, rows)
    track = cobs._render_coach_card("sleep")["track_record"]
    assert track["decided_count"] == 2
    assert track["hit_rate_pct"] == 50
    assert track["conversation_learnings"] == 1
    assert track["summary"] == "1 of 2 predictions confirmed in last 30 days · 1 conversation-sourced learning(s), not in the hit rate"


def test_card_omits_track_record_when_nothing_has_resolved(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": SLEEP_PK, "sk": "LEARNING#2026-08-09", "status": "inconclusive"},
    ]
    _install(monkeypatch, rows)
    assert "track_record" not in cobs._render_coach_card("sleep")


def test_card_proactivity_grades_the_nudge_record(monkeypatch):
    rows = [
        _output(content="analysis"),
        {
            "pk": SLEEP_PK,
            "sk": "NUDGE#2026-08-09#a",
            "status": "sent",
            "outcome": "hit",
            "prior": Decimal("0.7"),
            "sent_at": "2026-08-09T18:00:00Z",
        },
        {
            "pk": SLEEP_PK,
            "sk": "NUDGE#2026-08-08#b",
            "status": "sent",
            "outcome": "miss",
            "prior": Decimal("0.6"),
            "sent_at": "2026-08-08T18:00:00Z",
        },
        {"pk": SLEEP_PK, "sk": "NUDGE#2026-08-07#c", "status": "sent", "outcome": "pending", "prior": Decimal("0.5")},
        {"pk": SLEEP_PK, "sk": "NUDGE#2026-08-06#d", "status": "blocked"},
    ]
    _install(monkeypatch, rows)
    proactivity = cobs._render_coach_card("sleep")["proactivity"]
    assert proactivity["nudges"] == 4
    assert proactivity["sent"] == 3
    assert proactivity["blocked"] == 1
    assert (proactivity["hit"], proactivity["miss"], proactivity["pending"]) == (1, 1, 1)
    assert proactivity["graded"] == 2
    assert proactivity["hit_rate_pct"] == 50.0
    assert proactivity["window_days"] == 30
    assert proactivity["last_nudge_at"] == "2026-08-09T18:00:00Z"


def test_card_omits_proactivity_when_no_nudges_were_sent(monkeypatch):
    _install(monkeypatch, [_output(content="analysis")])
    assert "proactivity" not in cobs._render_coach_card("sleep")


def test_card_reports_experiment_timing(monkeypatch):
    monkeypatch.setattr(cobs, "EXPERIMENT_START", "2026-08-03")
    _install(monkeypatch, [_output(content="analysis")])
    card = cobs._render_coach_card("sleep")
    assert (card["week_number"], card["days_in_experiment"]) == (2, 8)


def test_extract_cross_coach_ref_is_an_inert_extension_point(monkeypatch):
    assert cobs._extract_cross_coach_ref({"active_disagreements": []}, "sleep_coach", "sleep") is None


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def _body(resp):
    assert resp["statusCode"] == 200  # graceful degradation: never a non-200
    assert resp["headers"]["Content-Type"] == "application/json"
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"
    return json.loads(resp["body"])


def test_handler_single_domain(monkeypatch):
    _install(monkeypatch, [_output(observatory_summary="Sleep is trending later.")])
    body = _body(cobs.lambda_handler({"domain": "sleep"}, None))
    assert body["coach_id"] == "sleep_coach"
    assert body["analysis"] == "Sleep is trending later."


def test_handler_accepts_an_api_gateway_json_body(monkeypatch):
    _install(monkeypatch, [_output(observatory_summary="Sleep is trending later.")])
    body = _body(cobs.lambda_handler({"body": json.dumps({"domain": "SLEEP  "})}, None))
    assert body["coach_id"] == "sleep_coach"  # domain is lowercased + stripped


def test_handler_survives_an_unparseable_body(monkeypatch):
    _install(monkeypatch, [])
    body = _body(cobs.lambda_handler({"body": "{not json", "queryStringParameters": {"domain": "sleep"}}, None))
    assert body["coach_id"] == "sleep_coach"


def test_handler_requires_a_domain(monkeypatch):
    _install(monkeypatch, [])
    body = _body(cobs.lambda_handler({}, None))
    assert body["error"] == "domain parameter required"
    assert body["valid_domains"] == list(cobs.DOMAIN_COACH_MAP)


def test_handler_rejects_an_unknown_domain(monkeypatch):
    _install(monkeypatch, [])
    body = _body(cobs.lambda_handler({"domain": "astrology"}, None))
    assert body["error"] == "unknown domain: astrology"
    assert "sleep" in body["valid_domains"]


def test_handler_all_mode_renders_every_coach(monkeypatch):
    rows = [_output(pk=f"COACH#{coach}", content=f"{coach} says hi") for coach in cobs.DOMAIN_COACH_MAP.values()]
    _install(monkeypatch, rows)
    body = _body(cobs.lambda_handler({"all": True}, None))
    assert [c["domain"] for c in body["coaches"]] == list(cobs.DOMAIN_COACH_MAP)
    assert body["coaches"][0]["analysis"] == "sleep_coach says hi"
    assert all(c["analysis"] for c in body["coaches"])


@pytest.mark.parametrize("flag", ["true", "1", "YES"])
def test_handler_all_mode_via_query_string(monkeypatch, flag):
    _install(monkeypatch, [_output(content="analysis")])
    body = _body(cobs.lambda_handler({"queryStringParameters": {"all": flag}}, None))
    assert len(body["coaches"]) == len(cobs.DOMAIN_COACH_MAP)


def test_handler_query_string_can_disable_threads(monkeypatch):
    rows = [
        _output(content="analysis"),
        {"pk": SLEEP_PK, "sk": "THREAD#1", "status": "open", "summary": "the 11pm drift"},
    ]
    _install(monkeypatch, rows)
    with_threads = _body(cobs.lambda_handler({"queryStringParameters": {"domain": "sleep"}}, None))
    assert with_threads["thread_reference"] == "the 11pm drift"
    without = _body(cobs.lambda_handler({"queryStringParameters": {"domain": "sleep", "include_threads": "false"}}, None))
    assert "thread_reference" not in without


def test_handler_all_mode_degrades_one_broken_card_without_losing_the_others(monkeypatch):
    _install(monkeypatch, [_output(pk=f"COACH#{coach}", content="ok") for coach in cobs.DOMAIN_COACH_MAP.values()])
    real_render = cobs._render_coach_card

    def _flaky(domain, **kwargs):
        if domain == "training":
            raise RuntimeError("renderer blew up")
        return real_render(domain, **kwargs)

    monkeypatch.setattr(cobs, "_render_coach_card", _flaky)
    body = _body(cobs.lambda_handler({"all": True}, None))
    assert len(body["coaches"]) == len(cobs.DOMAIN_COACH_MAP)
    broken = next(c for c in body["coaches"] if c["domain"] == "training")
    assert broken == {"coach_id": "physical_coach", "domain": "training", "analysis": None}
    assert all(c["analysis"] == "ok" for c in body["coaches"] if c["domain"] != "training")


def test_handler_returns_a_200_error_envelope_on_an_unhandled_event(monkeypatch):
    _install(monkeypatch, [])
    body = _body(cobs.lambda_handler(None, None))  # `None` has no .get → unhandled path
    assert body["error"] == "internal_error"
    assert body["message"]
