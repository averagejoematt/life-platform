"""tests/test_coach_ensemble_digest_behavior.py — behavioural contracts for the
post-cycle cross-coach digest (`lambdas/coach/coach_ensemble_digest.py`).

This Lambda is the only writer of two partitions that several public surfaces
read: `ENSEMBLE#digest / CYCLE#{date}` (rendered as the cross-coach reference by
`site_api_coach_stance.py` and `coach_observatory_renderer.py`) and
`ENSEMBLE#disagreements / ACTIVE#{slug}` (rendered into the Friday Panel podcast
script by `emails/podcast_script_v2.py`, including a literal `cycle_count`
claim). It also WRITES BACK into every coach's `COMPRESSED#latest`, which is the
memory those coaches are re-prompted from next cycle — so a bad write here is
replayed as if it were the coaches' own recollection.

What these tests pin:

  * **ADR-058 phase treatment** — COACH#/ENSEMBLE#* are EXPERIMENT_SCOPED, so
    every query must carry the filter and every `get_item` singleton must pass
    `singleton_visible`. The expectation is DERIVED from `phase_taxonomy`.
  * **ADR-104 / grounded generation** — an AI-failure or budget-paused run must
    be distinguishable from a genuine digest, and must not overwrite real coach
    memory with empty lists that later prompts read as fact.
  * **Budget gating (ADR-125)** — `ensemble` is a band-1 internal feature; the
    guard must actually fire, and the fallback must be honest.
  * **Reader/writer field agreement** — every field read off a coach's stored
    records is checked against the module that actually writes it
    (`coach_history_summarizer` for COMPRESSED#latest, `coach_state_updater`
    for OUTPUT#).
  * **Idempotency** — `cycle_count` is published as "how many cycles this
    argument has persisted"; a re-run of one cycle must not inflate it.
  * **Decimal before DynamoDB** — no bare float may reach `put_item`.

The nine defects this tranche discovered were carried as xfail markers until
#2221; they are now FIXED in `lambdas/coach/coach_ensemble_digest.py` and the
markers are gone. Every assertion below is a live contract — nothing in this
file is allowed to fail again.
"""

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")

import ai.budget_guard as budget_guard  # noqa: E402
import coach.coach_checkin as coach_checkin  # noqa: E402
import coach.dispute_docket as dispute_docket  # noqa: E402
import common.retry_utils as retry_utils  # noqa: E402
from coach import coach_ensemble_digest as ced  # noqa: E402
from coach.persona_registry import OPERATIONAL_COACH_IDS  # noqa: E402
from common.constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock — never mix a fixture date with the real wall clock.
# ──────────────────────────────────────────────────────────────────────────────

FROZEN_NOW = datetime(2026, 8, 7, 19, 0, 0, tzinfo=timezone.utc)
FROZEN_TODAY = "2026-08-07"
FROZEN_STAMP = "2026-08-07T19:00:00+00:00"
FROZEN_CYCLE = 12


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()` — keeps strftime/arithmetic."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


# ──────────────────────────────────────────────────────────────────────────────
# Hand-rolled bounded doubles — no MagicMock anywhere near a query.
# ──────────────────────────────────────────────────────────────────────────────


def _string_operands(condition):
    """The string literals in a boto3 condition tree, in tree order — the `pk`
    then the sk prefix in `Key('pk').eq(pk) & Key('sk').begins_with(prefix)`."""
    out = []
    for value in condition.get_expression()["values"]:
        if hasattr(value, "get_expression"):
            out += _string_operands(value)
        elif isinstance(value, str):
            out.append(value)
    return out


class CoachTable(FakeDdbTable):
    """FakeDdbTable with a real (bounded) pk + sk-prefix query.

    `_query_latest` depends on ScanIndexForward=False + Limit=1 meaning "newest",
    so a fake that ignores ordering would let an unsorted `[0]` pass. This one
    sorts by sk and honours both flags.
    """

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        condition = kwargs["KeyConditionExpression"]
        operands = _string_operands(condition)
        pk = operands[0]
        prefix = operands[1] if len(operands) > 1 else ""
        items = [i for i in self.store.values() if i.get("pk") == pk and str(i.get("sk", "")).startswith(prefix)]
        items.sort(key=lambda i: str(i.get("sk", "")), reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}


class ExplodingTable:
    """Every access raises — for pinning the fail-soft contracts."""

    def get_item(self, **kwargs):
        raise RuntimeError("ddb down")

    def query(self, **kwargs):
        raise RuntimeError("ddb down")

    def put_item(self, **kwargs):
        raise RuntimeError("ddb down")


class FakeCloudWatch:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("cloudwatch down")
        return {}


def find_floats(obj, path="item"):
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


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Nothing in this file may touch AWS or the network.

    `experiment_stamp()` reads the cycle from SSM; pinning `read_cycle` keeps the
    real stamp logic (phase from constants) while making it offline + frozen.
    """
    monkeypatch.setattr(coach_checkin, "read_cycle", lambda *a, **k: FROZEN_CYCLE)
    monkeypatch.setattr(ced, "datetime", _FrozenDatetime)
    monkeypatch.setattr(ced, "_cw", FakeCloudWatch())
    monkeypatch.setattr(budget_guard, "allow", lambda feature: True)

    def _no_network(*args, **kwargs):
        raise AssertionError("a test reached the real Anthropic/Bedrock path")

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _no_network)


@pytest.fixture
def table(monkeypatch):
    fake = CoachTable()
    monkeypatch.setattr(ced, "table", fake)
    return fake


def coach_output(coach_id="sleep_coach", date="2026-08-06", **fields):
    item = {
        "pk": f"COACH#{coach_id}",
        "sk": f"OUTPUT#{date}#daily",
        "content": "Bedtime has drifted 40 minutes later across the week.",
        "themes": ["sleep debt"],
        "decision_classes": ["observe"],
        "predictions_made": [{"claim_natural": "HRV recovers within 7 days"}],
        "threads_opened": ["bedtime-drift"],
        "threads_referenced": ["screen-time"],
        "created_at": "2026-08-06T12:00:00+00:00",
    }
    item.update(fields)
    return item


def coach_compressed(coach_id="sleep_coach", **fields):
    item = {
        "pk": f"COACH#{coach_id}",
        "sk": "COMPRESSED#latest",
        "summary": "A real compressed history for this coach.",
        "key_concerns": ["late bedtime drift", "low REM"],
        "key_recommendations": ["lights out by 22:30"],
        "recent_themes": ["sleep debt", "screen time"],
        "confidence_state": {"sleep": 0.7},
    }
    item.update(fields)
    return item


# ══════════════════════════════════════════════════════════════════════════════
# The coach roster — derived, never re-typed
# ══════════════════════════════════════════════════════════════════════════════


def test_the_digest_roster_is_the_platforms_operational_coach_roster():
    """A coach on the roster but missing from ALL_COACH_IDS is silently excluded
    from every ensemble digest AND rejected by the dispute-docket identity gate."""
    assert set(ced.ALL_COACH_IDS) == set(OPERATIONAL_COACH_IDS)


def test_the_roster_has_no_duplicate_entries():
    assert len(ced.ALL_COACH_IDS) == len(set(ced.ALL_COACH_IDS))


def test_the_dispute_docket_identity_gate_reads_this_modules_roster():
    """#1797 makes ALL_COACH_IDS load-bearing outside this module — a change here
    changes which coach pairs may open a docket."""
    source = open(os.path.join(ROOT, "lambdas", "coach", "dispute_docket.py"), encoding="utf-8").read()
    assert "from coach.coach_ensemble_digest import ALL_COACH_IDS" in source
    assert dispute_docket is not None


def test_the_digest_roster_is_the_registry_itself_not_a_copy():
    assert ced.ALL_COACH_IDS == OPERATIONAL_COACH_IDS


# ══════════════════════════════════════════════════════════════════════════════
# _slugify — the disagreement sort key
# ══════════════════════════════════════════════════════════════════════════════


def test_a_topic_becomes_a_lowercase_underscore_slug():
    assert ced._slugify("Protein Timing") == "protein_timing"


def test_punctuation_and_repeated_separators_collapse():
    assert ced._slugify("Protein-timing:  when?!") == "protein_timing_when"


def test_leading_and_trailing_separators_are_trimmed():
    assert ced._slugify("  --protein--  ") == "protein"


def test_an_empty_topic_gets_a_named_placeholder_not_an_empty_key():
    """An empty sort key would be an unaddressable DynamoDB row."""
    assert ced._slugify("   ") == "unnamed"
    assert ced._slugify("!!!") == "unnamed"


def test_the_slug_is_bounded_so_it_cannot_blow_the_sort_key():
    assert len(ced._slugify("a" * 500)) == 80


# ══════════════════════════════════════════════════════════════════════════════
# _get_item — the ADR-058 singleton read
# ══════════════════════════════════════════════════════════════════════════════


def test_a_present_singleton_is_returned(table):
    table.put_item(Item=coach_compressed())
    assert ced._get_item("COACH#sleep_coach", "COMPRESSED#latest")["summary"].startswith("A real")


def test_a_missing_singleton_reads_as_absent(table):
    assert ced._get_item("COACH#nobody", "COMPRESSED#latest") is None


def test_a_tombstoned_singleton_is_hidden(table):
    """ADR-077: the restart wipe tombstones rather than deletes; a get_item that
    ignored it would feed the wiped cycle's positions into a fresh digest."""
    table.put_item(Item=coach_compressed(tombstone=True))
    assert ced._get_item("COACH#sleep_coach", "COMPRESSED#latest") is None


def test_a_singleton_from_a_previous_experiment_phase_is_hidden(table):
    table.put_item(Item=coach_compressed(phase="pilot"))
    assert ced._get_item("COACH#sleep_coach", "COMPRESSED#latest") is None


def test_a_singleton_stamped_with_the_current_phase_is_visible(table):
    table.put_item(Item=coach_compressed(phase=EXPERIMENT_PHASE_CURRENT))
    assert ced._get_item("COACH#sleep_coach", "COMPRESSED#latest") is not None


def test_stored_decimals_come_back_as_floats(table):
    table.put_item(Item=coach_compressed(confidence_state={"sleep": Decimal("0.75")}))
    assert ced._get_item("COACH#sleep_coach", "COMPRESSED#latest")["confidence_state"]["sleep"] == 0.75


def test_a_failed_read_degrades_to_absent_rather_than_raising(monkeypatch):
    monkeypatch.setattr(ced, "table", ExplodingTable())
    assert ced._get_item("COACH#sleep_coach", "COMPRESSED#latest") is None


# ══════════════════════════════════════════════════════════════════════════════
# _put_item — provenance stamping + Decimal
# ══════════════════════════════════════════════════════════════════════════════


def test_the_partitions_this_module_writes_are_experiment_scoped():
    """Derived from the taxonomy — the reason every write is stamped and every
    read is filtered."""
    assert phase_taxonomy.classify("ENSEMBLE#digest") == phase_taxonomy.EXPERIMENT_SCOPED
    assert phase_taxonomy.classify("COACH#sleep_coach") == phase_taxonomy.EXPERIMENT_SCOPED


def test_every_write_carries_its_own_phase_and_cycle_provenance(table):
    ced._put_item({"pk": "ENSEMBLE#digest", "sk": "CYCLE#2026-08-07"})
    written = table.puts[0]
    assert written["phase"] == EXPERIMENT_PHASE_CURRENT
    assert written["cycle"] == FROZEN_CYCLE


def test_an_items_own_phase_wins_over_the_write_time_stamp(table):
    ced._put_item({"pk": "ENSEMBLE#digest", "sk": "CYCLE#2026-08-07", "phase": "pilot"})
    assert table.puts[0]["phase"] == "pilot"


def test_no_bare_float_reaches_dynamodb(table):
    ced._put_item({"pk": "ENSEMBLE#digest", "sk": "CYCLE#x", "confidence_state": {"sleep": 0.7}, "scores": [1.5, 2.5]})
    assert find_floats(table.puts[0]) == []


def test_a_failed_write_reports_failure_rather_than_raising(monkeypatch):
    monkeypatch.setattr(ced, "table", ExplodingTable())
    assert ced._put_item({"pk": "ENSEMBLE#digest", "sk": "CYCLE#x"}) is False


def test_a_successful_write_reports_success(table):
    assert ced._put_item({"pk": "ENSEMBLE#digest", "sk": "CYCLE#x"}) is True


# ══════════════════════════════════════════════════════════════════════════════
# _query_latest — the newest OUTPUT#, phase-filtered
# ══════════════════════════════════════════════════════════════════════════════


def test_the_newest_record_is_returned_not_the_first_one_stored(table):
    """An unsorted `[0]` where 'latest' is meant is a recurring class — the fake
    honours ScanIndexForward so this can actually fail."""
    table.put_item(Item=coach_output(date="2026-08-01", content="older"))
    table.put_item(Item=coach_output(date="2026-08-06", content="newer"))
    assert ced._query_latest("COACH#sleep_coach", "OUTPUT#")["content"] == "newer"


def test_the_query_asks_for_exactly_one_record_newest_first(table):
    table.put_item(Item=coach_output())
    ced._query_latest("COACH#sleep_coach", "OUTPUT#")
    call = table.query_calls[0]
    assert call["Limit"] == 1 and call["ScanIndexForward"] is False


def test_the_query_carries_the_adr_058_phase_filter(table):
    table.put_item(Item=coach_output())
    ced._query_latest("COACH#sleep_coach", "OUTPUT#")
    call = table.query_calls[0]
    assert "FilterExpression" in call
    assert call["ExpressionAttributeValues"][":phase_experiment"] == EXPERIMENT_PHASE_CURRENT
    assert call["ExpressionAttributeNames"]["#phase"] == "phase"


def test_an_empty_partition_reads_as_absent(table):
    assert ced._query_latest("COACH#nobody", "OUTPUT#") is None


def test_a_failed_query_degrades_to_absent_rather_than_raising(monkeypatch):
    monkeypatch.setattr(ced, "table", ExplodingTable())
    assert ced._query_latest("COACH#sleep_coach", "OUTPUT#") is None


# ══════════════════════════════════════════════════════════════════════════════
# _gather_coach_data
# ══════════════════════════════════════════════════════════════════════════════


def test_a_coach_with_both_records_is_gathered_whole(table):
    table.put_item(Item=coach_output())
    table.put_item(Item=coach_compressed())
    data = ced._gather_coach_data(["sleep_coach"])
    assert data["sleep_coach"]["output"]["content"].startswith("Bedtime")
    assert data["sleep_coach"]["compressed"]["summary"].startswith("A real")


def test_a_coach_with_only_one_record_is_still_gathered(table):
    table.put_item(Item=coach_output())
    data = ced._gather_coach_data(["sleep_coach"])
    assert data["sleep_coach"]["output"] is not None
    assert data["sleep_coach"]["compressed"] is None


def test_a_coach_with_no_records_is_omitted_entirely(table):
    """ADR-104: a coach that never reported must be absent, not an empty voice."""
    table.put_item(Item=coach_output())
    assert list(ced._gather_coach_data(["sleep_coach", "labs_coach"])) == ["sleep_coach"]


def test_every_coach_on_the_roster_can_be_gathered(table):
    """Guard the SET: derived from the roster, so a coach whose partition key
    convention drifted fails here."""
    for coach_id in ced.ALL_COACH_IDS:
        table.put_item(Item=coach_compressed(coach_id))
    assert set(ced._gather_coach_data(ced.ALL_COACH_IDS)) == set(ced.ALL_COACH_IDS)


# ══════════════════════════════════════════════════════════════════════════════
# The system prompt — the docket metric vocabulary
# ══════════════════════════════════════════════════════════════════════════════


def test_the_metric_vocabulary_placeholder_is_always_substituted():
    """A leftover `{metric_keys}` would invite the model to propose a criterion
    against a literal placeholder, which the deterministic gate then rejects."""
    assert "{metric_keys}" not in ced._ensemble_system_prompt()


def test_the_prompt_offers_exactly_the_metrics_the_evaluator_can_grade():
    """#1386: derived from METRIC_SOURCES so the proposable and gradable sets
    cannot diverge."""
    from experiment.measurable_metrics import METRIC_SOURCES

    prompt = ced._ensemble_system_prompt()
    for key in sorted(METRIC_SOURCES):
        assert key in prompt, key


def test_an_unavailable_metric_map_tells_the_model_to_propose_nothing(monkeypatch):
    import experiment.measurable_metrics as mm

    monkeypatch.delattr(mm, "METRIC_SOURCES")
    prompt = ced._ensemble_system_prompt()
    assert "propose no resolution_criterion" in prompt


def test_the_prompt_forbids_calling_a_partial_consensus_unanimous():
    assert "unanimous" in ced.ENSEMBLE_SYSTEM_PROMPT.lower()
    assert "majority" in ced.ENSEMBLE_SYSTEM_PROMPT.lower()


# ══════════════════════════════════════════════════════════════════════════════
# _build_user_message
# ══════════════════════════════════════════════════════════════════════════════


def test_the_message_reports_how_many_of_the_expected_coaches_reported():
    message = ced._build_user_message({"sleep_coach": {"output": None, "compressed": None}}, FROZEN_TODAY)
    assert f"Coaches with data: 1/{len(ced.ALL_COACH_IDS)}" in message


def test_every_absent_coach_is_named_so_consensus_cannot_be_overclaimed():
    """Phase 3.7: without this the model called 1-of-8 agreement 'unanimous'."""
    message = ced._build_user_message({"sleep_coach": {"output": None, "compressed": None}}, FROZEN_TODAY)
    for coach_id in ced.ALL_COACH_IDS:
        if coach_id != "sleep_coach":
            assert coach_id in message, coach_id


def test_a_full_roster_produces_no_absence_warning(table):
    data = {cid: {"output": None, "compressed": None} for cid in ced.ALL_COACH_IDS}
    message = ced._build_user_message(data, FROZEN_TODAY)
    assert "Coaches WITHOUT data this cycle" not in message


def test_an_explicit_expected_roster_narrows_the_absence_list():
    message = ced._build_user_message(
        {"sleep_coach": {"output": None, "compressed": None}},
        FROZEN_TODAY,
        expected_coach_ids=["sleep_coach", "labs_coach"],
    )
    assert "Coaches with data: 1/2" in message
    assert "labs_coach" in message and "glucose_coach" not in message


def test_a_coach_without_records_is_declared_missing_rather_than_blank():
    message = ced._build_user_message({"sleep_coach": {"output": None, "compressed": None}}, FROZEN_TODAY)
    assert "#### Most Recent Output: None available" in message
    assert "#### Compressed State: None available" in message


def test_the_output_excerpt_is_bounded():
    output = coach_output(content="x" * 5000)
    message = ced._build_user_message({"sleep_coach": {"output": output, "compressed": None}}, FROZEN_TODAY)
    assert "x" * 500 in message and "x" * 501 not in message


def test_the_keys_are_stripped_from_the_compressed_state_in_the_prompt():
    message = ced._build_user_message({"sleep_coach": {"output": None, "compressed": coach_compressed()}}, FROZEN_TODAY)
    assert "COMPRESSED#latest" not in message
    assert "late bedtime drift" in message


def test_every_output_field_named_in_the_prompt_is_one_the_output_writer_stores():
    """Reader/writer agreement: coach_state_updater._write_output_record is the
    only writer of COACH#*/OUTPUT#*."""
    writer = open(os.path.join(ROOT, "lambdas", "coach", "coach_state_updater.py"), encoding="utf-8").read()
    for field in ("content", "themes", "decision_classes", "predictions_made", "threads_opened", "threads_referenced", "created_at"):
        assert f'"{field}":' in writer, field


# ══════════════════════════════════════════════════════════════════════════════
# _build_default_digest — the no-AI fallback
# ══════════════════════════════════════════════════════════════════════════════


def test_the_fallback_digest_declares_itself_a_fallback():
    """ADR-104: an AI-failure stub must never be filed as genuine content."""
    digest = ced._build_default_digest({"sleep_coach": {"output": None, "compressed": coach_compressed()}}, FROZEN_TODAY)
    assert digest["_fallback"] is True
    assert digest["created_at"] == FROZEN_STAMP


def test_the_fallback_asserts_no_disagreements_and_no_unanimity():
    digest = ced._build_default_digest({"sleep_coach": {"output": None, "compressed": coach_compressed()}}, FROZEN_TODAY)
    assert digest["active_disagreements"] == [] and digest["unanimous_flags"] == []


def test_the_fallback_carries_each_coachs_stored_confidence_state():
    digest = ced._build_default_digest({"sleep_coach": {"output": None, "compressed": coach_compressed()}}, FROZEN_TODAY)
    assert digest["coach_summaries"][0]["confidence_state"] == {"sleep": 0.7}


def test_the_fallback_carries_the_coachs_own_active_predictions():
    digest = ced._build_default_digest({"sleep_coach": {"output": coach_output(), "compressed": None}}, FROZEN_TODAY)
    assert digest["coach_summaries"][0]["predictions_active"] == ["HRV recovers within 7 days"]


def test_a_prediction_stored_as_plain_text_still_survives_the_fallback():
    output = coach_output(predictions_made=["HRV up", "weight down"])
    digest = ced._build_default_digest({"sleep_coach": {"output": output, "compressed": None}}, FROZEN_TODAY)
    assert digest["coach_summaries"][0]["predictions_active"] == ["HRV up", "weight down"]


def test_the_fallback_survives_a_coach_with_neither_record():
    digest = ced._build_default_digest({"sleep_coach": {"output": None, "compressed": None}}, FROZEN_TODAY)
    assert digest["coach_summaries"][0]["coach_id"] == "sleep_coach"


def test_the_fallback_reports_the_concerns_the_compressed_state_actually_holds():
    digest = ced._build_default_digest({"sleep_coach": {"output": None, "compressed": coach_compressed()}}, FROZEN_TODAY)
    summary = digest["coach_summaries"][0]
    assert summary["key_concerns"] == ["late bedtime drift", "low REM"]
    assert summary["key_recommendations"] == ["lights out by 22:30"]


# ══════════════════════════════════════════════════════════════════════════════
# _write_digest
# ══════════════════════════════════════════════════════════════════════════════


def test_the_digest_is_keyed_by_cycle_date(table):
    ced._write_digest({"coach_summaries": [], "active_disagreements": [], "unanimous_flags": []}, FROZEN_TODAY)
    assert (table.puts[0]["pk"], table.puts[0]["sk"]) == ("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}")


def test_the_digest_body_is_stored_alongside_the_keys(table):
    ced._write_digest({"coach_summaries": [{"coach_id": "sleep_coach"}], "unanimous_flags": ["x"]}, FROZEN_TODAY)
    assert table.puts[0]["coach_summaries"] == [{"coach_id": "sleep_coach"}]
    assert table.puts[0]["unanimous_flags"] == ["x"]


def test_a_failed_digest_write_is_reported_to_the_caller(monkeypatch):
    monkeypatch.setattr(ced, "table", ExplodingTable())
    assert ced._write_digest({}, FROZEN_TODAY) is False


# ══════════════════════════════════════════════════════════════════════════════
# _write_disagreements — the partition the Friday Panel reads
# ══════════════════════════════════════════════════════════════════════════════


def disagreement(topic="Protein timing", **fields):
    item = {
        "topic": topic,
        "coaches": ["sleep_coach", "nutrition_coach"],
        "positions": {"sleep_coach": "later", "nutrition_coach": "earlier"},
        "data_needed_to_resolve": "two more weeks of CGM",
    }
    item.update(fields)
    return item


def test_a_new_disagreement_is_keyed_on_its_topic_slug(table):
    ced._write_disagreements([disagreement()], FROZEN_TODAY)
    assert (table.puts[0]["pk"], table.puts[0]["sk"]) == ("ENSEMBLE#disagreements", "ACTIVE#protein_timing")


def test_a_new_disagreement_starts_at_one_cycle_and_stamps_both_timestamps(table):
    ced._write_disagreements([disagreement()], FROZEN_TODAY)
    written = table.puts[0]
    assert written["cycle_count"] == 1
    assert written["first_seen"] == written["last_seen"] == FROZEN_STAMP


def test_a_recurring_disagreement_keeps_its_first_seen_and_advances_the_count(table):
    ced._write_disagreements([disagreement()], "2026-08-01")
    with_later_clock = ced._write_disagreements([disagreement()], "2026-08-07")
    stored = table.store[("ENSEMBLE#disagreements", "ACTIVE#protein_timing")]
    assert with_later_clock == 1
    assert stored["cycle_count"] == 2
    assert stored["last_cycle_date"] == "2026-08-07"


def test_a_disagreement_defaults_to_unresolved_when_the_model_omits_a_status(table):
    ced._write_disagreements([disagreement()], FROZEN_TODAY)
    assert table.puts[0]["status"] == "unresolved"


def test_a_machine_checkable_criterion_is_carried_through_to_the_docket_gate(table):
    criterion = {"metric": "hrv", "condition": "gt", "threshold": 60, "resolution_days": 14}
    ced._write_disagreements([disagreement(resolution_criterion=criterion)], FROZEN_TODAY)
    assert table.puts[0]["resolution_criterion"] == criterion


def test_a_narrative_only_disagreement_stores_no_criterion(table):
    ced._write_disagreements([disagreement(resolution_criterion=None)], FROZEN_TODAY)
    assert "resolution_criterion" not in table.puts[0]


def test_a_malformed_criterion_is_dropped_rather_than_stored(table):
    ced._write_disagreements([disagreement(resolution_criterion="hrv goes up")], FROZEN_TODAY)
    assert "resolution_criterion" not in table.puts[0]


def test_the_count_of_written_records_is_returned(table):
    assert ced._write_disagreements([disagreement("A"), disagreement("B")], FROZEN_TODAY) == 2


def test_a_write_failure_is_excluded_from_the_reported_count(monkeypatch):
    monkeypatch.setattr(ced, "table", ExplodingTable())
    assert ced._write_disagreements([disagreement()], FROZEN_TODAY) == 0


def test_re_running_one_cycle_does_not_inflate_the_persistence_count(table):
    ced._write_disagreements([disagreement()], FROZEN_TODAY)
    ced._write_disagreements([disagreement()], FROZEN_TODAY)
    assert table.store[("ENSEMBLE#disagreements", "ACTIVE#protein_timing")]["cycle_count"] == 1


def test_two_topics_in_one_run_that_share_a_slug_do_not_inflate_the_count(table):
    ced._write_disagreements([disagreement("Protein timing"), disagreement("protein-TIMING?")], FROZEN_TODAY)
    assert table.store[("ENSEMBLE#disagreements", "ACTIVE#protein_timing")]["cycle_count"] == 1


def test_a_disagreement_naming_a_coach_who_does_not_exist_is_not_stored(table):
    ced._write_disagreements([disagreement(coaches=["coach_a", "Dr. Someone Real"])], FROZEN_TODAY)
    assert table.puts == []


# ══════════════════════════════════════════════════════════════════════════════
# _update_coach_compressed_states — the write-back into coach memory
# ══════════════════════════════════════════════════════════════════════════════


def _digest_with(summary=None, disagreements=None):
    return {
        "coach_summaries": [summary] if summary else [],
        "active_disagreements": disagreements or [],
        "unanimous_flags": [],
    }


def test_each_coachs_contribution_is_recorded_against_the_cycle(table):
    table.put_item(Item=coach_compressed())
    summary = {"coach_id": "sleep_coach", "key_concerns": ["drift"], "key_recommendations": ["earlier"]}
    updated = ced._update_coach_compressed_states(_digest_with(summary), {"sleep_coach": {}}, FROZEN_TODAY)
    contribution = table.store[("COACH#sleep_coach", "COMPRESSED#latest")]["digest_contribution"]
    assert updated == 1
    assert contribution["cycle_date"] == FROZEN_TODAY
    assert contribution["key_concerns_captured"] == ["drift"]
    assert contribution["updated_at"] == FROZEN_STAMP


def test_the_rest_of_the_compressed_state_is_left_intact(table):
    table.put_item(Item=coach_compressed())
    ced._update_coach_compressed_states(_digest_with(), {"sleep_coach": {}}, FROZEN_TODAY)
    stored = table.store[("COACH#sleep_coach", "COMPRESSED#latest")]
    assert stored["summary"].startswith("A real")
    assert stored["key_concerns"] == ["late bedtime drift", "low REM"]


def test_a_coach_with_no_compressed_state_is_skipped_not_created(table):
    assert ced._update_coach_compressed_states(_digest_with(), {"sleep_coach": {}}, FROZEN_TODAY) == 0
    assert table.puts == []


def test_a_disagreement_is_recorded_from_the_coachs_own_point_of_view(table):
    table.put_item(Item=coach_compressed())
    d = {"topic": "Protein timing", "coaches": ["sleep_coach", "nutrition_coach"], "positions": {"sleep_coach": "later"}}
    ced._update_coach_compressed_states(_digest_with(disagreements=[d]), {"sleep_coach": {}}, FROZEN_TODAY)
    involved = table.store[("COACH#sleep_coach", "COMPRESSED#latest")]["digest_contribution"]["active_disagreements"]
    assert involved == [{"topic": "Protein timing", "with_coaches": ["nutrition_coach"], "my_position": "later"}]


def test_a_disagreement_the_coach_is_not_part_of_is_not_attributed_to_them(table):
    table.put_item(Item=coach_compressed())
    d = {"topic": "Protein timing", "coaches": ["labs_coach", "nutrition_coach"], "positions": {}}
    ced._update_coach_compressed_states(_digest_with(disagreements=[d]), {"sleep_coach": {}}, FROZEN_TODAY)
    contribution = table.store[("COACH#sleep_coach", "COMPRESSED#latest")]["digest_contribution"]
    assert "active_disagreements" not in contribution


def test_a_tombstoned_compressed_state_is_never_resurrected_by_the_write_back(table):
    """The read is `singleton_visible`-guarded, so a wiped cycle's record must
    not be re-put with a fresh stamp and thereby made live again."""
    table.put_item(Item=coach_compressed(tombstone=True))
    assert ced._update_coach_compressed_states(_digest_with(), {"sleep_coach": {}}, FROZEN_TODAY) == 0


# ══════════════════════════════════════════════════════════════════════════════
# _call_haiku — response parsing
# ══════════════════════════════════════════════════════════════════════════════


def _respond(monkeypatch, text):
    monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda req: {"content": [{"text": text}]})


def test_a_clean_json_response_is_parsed(monkeypatch):
    _respond(monkeypatch, '{"coach_summaries": []}')
    assert ced._call_haiku("sys", "user") == {"coach_summaries": []}


def test_a_json_fenced_response_is_unwrapped(monkeypatch):
    _respond(monkeypatch, 'here you go\n```json\n{"unanimous_flags": ["a"]}\n```\n')
    assert ced._call_haiku("sys", "user") == {"unanimous_flags": ["a"]}


def test_a_bare_fenced_response_is_unwrapped(monkeypatch):
    _respond(monkeypatch, '```\n{"unanimous_flags": []}\n```')
    assert ced._call_haiku("sys", "user") == {"unanimous_flags": []}


def test_unparseable_prose_is_handed_back_as_text_for_the_caller_to_reject(monkeypatch):
    _respond(monkeypatch, "I cannot produce that.")
    assert ced._call_haiku("sys", "user") == "I cannot produce that."


def test_a_truncated_fence_falls_back_to_the_raw_text(monkeypatch):
    _respond(monkeypatch, '```json\n{"coach_summaries": [')
    assert isinstance(ced._call_haiku("sys", "user"), str)


def test_a_closed_json_fence_holding_invalid_json_falls_back_to_the_raw_text(monkeypatch):
    """The truncation class (#1386's max_tokens bump): a complete fence whose
    contents are still cut off must degrade, not raise."""
    _respond(monkeypatch, '```json\n{"coach_summaries": [{"coach_id"\n```')
    assert isinstance(ced._call_haiku("sys", "user"), str)


def test_a_closed_bare_fence_holding_invalid_json_falls_back_to_the_raw_text(monkeypatch):
    _respond(monkeypatch, "```\nnot json at all\n```")
    assert isinstance(ced._call_haiku("sys", "user"), str)


def test_the_system_prompt_is_sent_as_a_cacheable_block(monkeypatch):
    captured = {}

    def _capture(req):
        captured["body"] = json.loads(req.data.decode())
        return {"content": [{"text": "{}"}]}

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _capture)
    ced._call_haiku("the system prompt", "the user message", max_tokens=6000, temperature=0.2)
    assert captured["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert captured["body"]["max_tokens"] == 6000 and captured["body"]["temperature"] == 0.2


def test_the_structured_task_uses_the_haiku_tier(monkeypatch):
    captured = {}

    def _capture(req):
        captured["body"] = json.loads(req.data.decode())
        return {"content": [{"text": "{}"}]}

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _capture)
    ced._call_haiku(None, "user")
    assert "haiku" in captured["body"]["model"]
    assert "system" not in captured["body"]


def test_an_empty_completion_degrades_rather_than_raising_an_index_error(monkeypatch):
    monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda req: {"content": []})
    assert ced._call_haiku("sys", "user") in (None, "", {})


# ══════════════════════════════════════════════════════════════════════════════
# _emit_failure_metric
# ══════════════════════════════════════════════════════════════════════════════


def test_the_failure_metric_names_this_lambda(monkeypatch):
    cw = FakeCloudWatch()
    monkeypatch.setattr(ced, "_cw", cw)
    ced._emit_failure_metric()
    metric = cw.calls[0]["MetricData"][0]
    assert metric["MetricName"] == "AnthropicAPIFailure"
    assert metric["Dimensions"][0]["Value"] == ced._LAMBDA_NAME


def test_a_cloudwatch_outage_never_propagates(monkeypatch):
    monkeypatch.setattr(ced, "_cw", FakeCloudWatch(fail=True))
    ced._emit_failure_metric()  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler
# ══════════════════════════════════════════════════════════════════════════════


def _seed_one_coach(table):
    table.put_item(Item=coach_output())
    table.put_item(Item=coach_compressed())


def _llm(monkeypatch, payload):
    monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda req: {"content": [{"text": json.dumps(payload)}]})


def test_the_cycle_date_defaults_to_today(table, monkeypatch):
    _seed_one_coach(table)
    _llm(monkeypatch, {"coach_summaries": [], "active_disagreements": [], "unanimous_flags": []})
    ced.lambda_handler({}, None)
    assert ("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}") in table.store


def test_an_explicit_cycle_date_is_honoured(table, monkeypatch):
    _seed_one_coach(table)
    _llm(monkeypatch, {"coach_summaries": [], "active_disagreements": [], "unanimous_flags": []})
    ced.lambda_handler({"cycle_date": "2026-08-01"}, None)
    assert ("ENSEMBLE#digest", "CYCLE#2026-08-01") in table.store


def test_an_unknown_coach_id_is_dropped_from_the_target_list(table, monkeypatch):
    _seed_one_coach(table)
    _llm(monkeypatch, {"coach_summaries": [], "active_disagreements": [], "unanimous_flags": []})
    result = ced.lambda_handler({"coach_ids": ["sleep_coach", "not_a_coach"]}, None)
    assert "coach_summaries" in result


def test_an_entirely_invalid_coach_list_falls_back_to_the_whole_roster(table, monkeypatch):
    _seed_one_coach(table)
    _llm(monkeypatch, {"coach_summaries": [], "active_disagreements": [], "unanimous_flags": []})
    ced.lambda_handler({"coach_ids": ["nobody"]}, None)
    # One OUTPUT# query per targeted coach — the whole roster, not zero coaches.
    assert len(table.query_calls) == len(ced.ALL_COACH_IDS)
    assert ("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}") in table.store


def test_a_cycle_with_no_coach_data_writes_an_explicitly_empty_digest(table):
    result = ced.lambda_handler({}, None)
    stored = table.store[("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}")]
    assert result["coach_summaries"] == []
    assert "No coach data available" in stored["note"]


def test_a_cycle_with_no_coach_data_does_not_touch_coach_memory(table):
    ced.lambda_handler({}, None)
    assert [p["pk"] for p in table.puts] == ["ENSEMBLE#digest"]


def test_a_successful_digest_is_stored_and_returned(table, monkeypatch):
    _seed_one_coach(table)
    _llm(
        monkeypatch,
        {
            "coach_summaries": [{"coach_id": "sleep_coach", "key_concerns": ["drift"]}],
            "active_disagreements": [],
            "unanimous_flags": ["everyone likes sleep"],
        },
    )
    result = ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert result["unanimous_flags"] == ["everyone likes sleep"]
    assert table.store[("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}")]["coach_summaries"][0]["coach_id"] == "sleep_coach"


def test_a_digest_omitting_a_required_section_is_defaulted_not_dropped(table, monkeypatch):
    _seed_one_coach(table)
    _llm(monkeypatch, {"coach_summaries": [{"coach_id": "sleep_coach"}]})
    result = ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert result["active_disagreements"] == [] and result["unanimous_flags"] == []


def test_a_non_dict_llm_response_falls_back_and_says_so(table, monkeypatch):
    _seed_one_coach(table)
    monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda req: {"content": [{"text": "sorry, no"}]})
    result = ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert result["_fallback"] is True
    assert table.store[("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}")]["_fallback"] is True


def test_an_llm_outage_falls_back_and_says_so(table, monkeypatch):
    _seed_one_coach(table)
    monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda req: (_ for _ in ()).throw(RuntimeError("bedrock down")))
    result = ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert result["_fallback"] is True


def test_the_ensemble_is_a_band_one_internal_ai_feature():
    """ADR-125: derived from the budget ladder, so a re-band that forgot this
    Lambda fails here rather than silently changing what pauses first."""
    assert budget_guard._FEATURE_CUTOFF["ensemble"] == 1


def test_a_budget_paused_cycle_skips_the_llm_entirely(table, monkeypatch):
    _seed_one_coach(table)
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    # `call_anthropic_raw` is the autouse no-network guard: reaching it fails.
    result = ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert result["_fallback"] is True


def test_a_budget_paused_cycle_files_an_honestly_marked_digest(table, monkeypatch):
    _seed_one_coach(table)
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert table.store[("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}")]["_fallback"] is True


def test_the_budget_gate_asks_about_this_feature_by_name(table, monkeypatch):
    _seed_one_coach(table)
    asked = []
    monkeypatch.setattr(budget_guard, "allow", lambda feature: asked.append(feature) or False)
    ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert asked == ["ensemble"]


def test_disagreements_from_the_digest_reach_their_own_partition(table, monkeypatch):
    _seed_one_coach(table)
    _llm(
        monkeypatch,
        {"coach_summaries": [], "active_disagreements": [disagreement()], "unanimous_flags": []},
    )
    monkeypatch.setattr(dispute_docket, "open_from_disagreements", lambda d, c: {"opened": [], "skipped": []})
    ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert ("ENSEMBLE#disagreements", "ACTIVE#protein_timing") in table.store


def test_a_docket_failure_never_sinks_the_digest(table, monkeypatch):
    _seed_one_coach(table)
    _llm(monkeypatch, {"coach_summaries": [], "active_disagreements": [disagreement()], "unanimous_flags": []})

    def _boom(disagreements, cycle_date):
        raise RuntimeError("docket down")

    monkeypatch.setattr(dispute_docket, "open_from_disagreements", _boom)
    result = ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert ("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}") in table.store
    assert "docket" not in result


def test_the_returned_digest_carries_no_decimals_for_a_json_caller(table, monkeypatch):
    """A Decimal reaching json.dumps raises — the return value is the handler's
    contract with whatever invoked it."""
    table.put_item(Item=coach_output())
    table.put_item(Item=coach_compressed(confidence_state={"sleep": Decimal("0.75")}))
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    result = ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    json.dumps(result)  # must not raise


def test_a_fallback_cycle_does_not_write_empty_findings_into_coach_memory(table, monkeypatch):
    _seed_one_coach(table)
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    contribution = table.store[("COACH#sleep_coach", "COMPRESSED#latest")].get("digest_contribution")
    assert contribution is None or contribution.get("_fallback") is True


def test_the_docket_outcome_is_persisted_with_the_digest_that_produced_it(table, monkeypatch):
    _seed_one_coach(table)
    _llm(monkeypatch, {"coach_summaries": [], "active_disagreements": [disagreement()], "unanimous_flags": []})
    monkeypatch.setattr(dispute_docket, "open_from_disagreements", lambda d, c: {"opened": ["x"], "skipped": []})
    result = ced.lambda_handler({"coach_ids": ["sleep_coach"]}, None)
    assert result["docket"] == {"opened": 1, "skipped": 0}
    assert table.store[("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}")]["docket"] == {"opened": 1, "skipped": 0}


def test_an_empty_cycle_marks_itself_the_same_way_every_other_fallback_does(table):
    ced.lambda_handler({}, None)
    assert table.store[("ENSEMBLE#digest", f"CYCLE#{FROZEN_TODAY}")].get("_fallback") is True
