"""tests/test_coach_state_updater.py — unit coverage for the coach post-generation
state updater (#1658 coverage ratchet).

The updater is the write half of Coach Intelligence: it turns one LLM extraction into
a set of DynamoDB state transitions (OUTPUT#, VOICE#state, THREAD#, TRACE#,
PREDICTION#, COMMITMENT#, RELATIONSHIP#state). These tests pin the transitions
themselves — which input produces which new state, what is carried forward unchanged,
and which guard paths write nothing at all.

Complements the existing narrow suites rather than repeating them: #813/#2023 already
own the liveness gate and direction inference, #532 owns commitment record shape, #536
owns the rapport arithmetic, #1987 owns the register regexes. What was untested — and
is tested here — is the VOICE#state staleness state machine, the thread open/reference
transitions, the DynamoDB read/write wrappers' failure fallbacks, the S3 voice-spec
loader, the LLM response parser, the default (fallback) extraction, and the handler's
end-to-end orchestration + validation guards.

Fully offline: no AWS, no network, no sleeps. Every boto3 handle is replaced with a
hand-written fake (never MagicMock — a non-terminating mock in the liveness pagination
loop has OOM'd this repo's CI runner before).
"""

import json
import os
import sys
from datetime import datetime
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_state_updater as su  # noqa: E402
from coach import coach_checkin  # noqa: E402
from common import retry_utils  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
# Hand-written fakes (no MagicMock anywhere — see module docstring)
# ══════════════════════════════════════════════════════════════════════════════


def _queries_a_source_partition(condition):
    """True when a boto3 key condition pins a `USER#…#SOURCE#…` pk (#2575)."""
    try:
        values = condition.get_expression()["values"]
    except (AttributeError, KeyError, TypeError):
        return False
    return any(isinstance(v, str) and v.startswith("USER#") and "#SOURCE#" in v or _queries_a_source_partition(v) for v in values)


class FakeTable:
    """DynamoDB Table stand-in: records writes, serves canned reads, paginates finitely."""

    def __init__(self, items=None, query_pages=None, liveness_pages=None, begins_pages=None, vitals_pages=None, fail=()):
        self.puts = []
        self.updates = []
        self.get_calls = []
        self.query_calls = []
        self._items = dict(items or {})  # (pk, sk) -> Item
        self._pages = list(query_pages or [])  # generic queue of {"Items": [...], maybe LastEvaluatedKey}
        # The handler issues two *kinds* of query in an interleaved order; route them
        # by shape rather than by call index. The liveness read passes a raw string
        # KeyConditionExpression; _query_begins_with passes a boto3 condition object.
        self._liveness_pages = None if liveness_pages is None else list(liveness_pages)
        self._begins_pages = None if begins_pages is None else list(begins_pages)
        self._vitals_pages = list(vitals_pages or [])  # #2575: the Truth-Spine stamp's SOURCE# reads
        self._fail = set(fail)  # any of {"get", "put", "query", "update"}

    def get_item(self, Key):  # noqa: N803 — boto3's kwarg name
        self.get_calls.append((Key["pk"], Key["sk"]))
        if "get" in self._fail:
            raise RuntimeError("simulated get_item failure")
        item = self._items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def put_item(self, Item):  # noqa: N803
        if "put" in self._fail:
            raise RuntimeError("simulated put_item failure")
        self.puts.append(Item)
        return {}

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        if "query" in self._fail:
            raise RuntimeError("simulated query failure")
        is_liveness = isinstance(kwargs.get("KeyConditionExpression"), str)
        # #2575: the Truth-Spine stamp reads SOURCE# partitions from this same table.
        # Route those to their own (empty by default) queue — routing by shape, exactly
        # as the liveness read already is. Without it the Spine's whoop/garmin reads
        # DRAIN the COACH# pages, and the state assertions fail on a queue that ran out
        # rather than on anything the handler did.
        if not is_liveness and _queries_a_source_partition(kwargs.get("KeyConditionExpression")):
            return self._vitals_pages.pop(0) if self._vitals_pages else {"Items": []}
        queue = self._liveness_pages if is_liveness else self._begins_pages
        if queue is None:
            queue = self._pages
        # Every queue is a plain list that DRAINS — pagination here always terminates.
        return queue.pop(0) if queue else {"Items": []}

    def update_item(self, **kwargs):
        if "update" in self._fail:
            raise RuntimeError("simulated update_item failure")
        self.updates.append(kwargs)
        return {}

    def sk_of(self, prefix):
        return [p["sk"] for p in self.puts if p["sk"].startswith(prefix)]


class FakeS3Exceptions:
    class NoSuchKey(Exception):
        pass


class FakeS3:
    """s3 client stand-in for the voice-spec loader."""

    def __init__(self, body=None, raise_no_such_key=False, raise_other=False):
        self.exceptions = FakeS3Exceptions
        self._body = body
        self._nsk = raise_no_such_key
        self._other = raise_other
        self.calls = []

    def get_object(self, Bucket, Key):  # noqa: N803
        self.calls.append((Bucket, Key))
        if self._nsk:
            raise FakeS3Exceptions.NoSuchKey("nope")
        if self._other:
            raise RuntimeError("S3 unavailable")
        return {"Body": _FakeBody(self._body)}


class _FakeBody:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()


class FakeCloudWatch:
    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    def put_metric_data(self, **kwargs):
        if self._fail:
            raise RuntimeError("cloudwatch unavailable")
        self.calls.append(kwargs)


class _FrozenDatetime(datetime):
    """datetime with a pinned now() — no wall-clock math against fixture dates."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 6, 30, 12, 0, 0, tzinfo=tz)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """Nothing in this module may touch AWS: DDB, S3, CloudWatch, SSM (via the
    write-time experiment stamp) are all replaced up front."""
    monkeypatch.setattr(su, "table", FakeTable())
    monkeypatch.setattr(su, "s3", FakeS3(body={}))
    monkeypatch.setattr(su, "_cw", FakeCloudWatch())
    monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 12)
    monkeypatch.setattr(su, "datetime", _FrozenDatetime)


# ══════════════════════════════════════════════════════════════════════════════
# _parse_confidence — the defensive coercion (V2 P1.3)
# ══════════════════════════════════════════════════════════════════════════════


class TestParseConfidence:
    def test_missing_confidence_is_neutral(self):
        assert su._parse_confidence(None) == 0.5
        assert su._parse_confidence("") == 0.5

    def test_word_scale(self):
        assert su._parse_confidence("high") == 0.85
        assert su._parse_confidence("  MEDIUM ") == 0.5
        assert su._parse_confidence("low") == 0.2
        assert su._parse_confidence("very high") == 0.95
        assert su._parse_confidence("very low") == 0.1
        assert su._parse_confidence("unknown") == 0.5

    def test_percent_strings_become_fractions(self):
        assert su._parse_confidence("40%") == 0.4
        assert su._parse_confidence("7.5%") == 0.075

    def test_bare_numbers_pass_through(self):
        assert su._parse_confidence(0.4) == 0.4
        assert su._parse_confidence("0.65") == 0.65

    def test_out_of_range_values_are_clamped(self):
        assert su._parse_confidence("250%") == 1.0
        assert su._parse_confidence(-3) == 0.0

    def test_unparseable_text_falls_back_to_neutral(self):
        assert su._parse_confidence("pretty sure honestly") == 0.5
        assert su._parse_confidence(["not", "scalar"]) == 0.5


# ══════════════════════════════════════════════════════════════════════════════
# _build_prediction_eval_spec + _timeframe_to_window_days
# ══════════════════════════════════════════════════════════════════════════════


class TestEvalSpecAndWindows:
    def test_metric_plus_direction_is_gradable(self):
        spec = su._build_prediction_eval_spec("hrv", "up", 21)
        assert spec["type"] == "directional"
        assert spec["metric"] == "hrv" and spec["condition"] == "up"
        assert spec["evaluation_window_days"] == 21
        assert spec["threshold"] is None  # directional grading needs no threshold

    def test_a_metric_with_no_resolvable_direction_stays_qualitative(self):
        spec = su._build_prediction_eval_spec("hrv", None, 14)
        assert spec["type"] == "qualitative"
        assert spec["metric"] == "hrv"  # the hint is kept for context …
        assert spec["condition"] is None  # … but nothing claims to be gradable

    def test_no_metric_is_qualitative_with_no_metric(self):
        assert su._build_prediction_eval_spec("", "up", 14) == {
            "type": "qualitative",
            "metric": None,
            "condition": None,
            "threshold": None,
            "evaluation_window_days": 14,
            "null_hypothesis": None,
            "beats_null_if": None,
        }

    def test_bare_number_timeframe_falls_back_to_the_default(self):
        assert su._timeframe_to_window_days("sometime soon") == 7
        assert su._timeframe_to_window_days("4") == 7  # no unit word -> default
        assert su._timeframe_to_window_days("in 6 days", default=3) == 6
        assert su._timeframe_to_window_days("a few days", default=3) == 3

    def test_unit_words_without_a_number_assume_one(self):
        assert su._timeframe_to_window_days("next week") == 7
        assert su._timeframe_to_window_days("2 months") == 60
        assert su._timeframe_to_window_days("over the coming month") == 30


# ══════════════════════════════════════════════════════════════════════════════
# DynamoDB wrappers — the fallbacks when a read or write FAILS
# ══════════════════════════════════════════════════════════════════════════════


class TestDynamoWrappers:
    def test_get_item_converts_decimals(self, monkeypatch):
        t = FakeTable(items={("COACH#sleep_coach", "VOICE#state"): {"rapport": Decimal("0.42"), "n": Decimal("3")}})
        monkeypatch.setattr(su, "table", t)
        out = su._get_item("COACH#sleep_coach", "VOICE#state")
        assert out == {"rapport": 0.42, "n": 3}

    def test_missing_item_is_none(self, monkeypatch):
        monkeypatch.setattr(su, "table", FakeTable())
        assert su._get_item("COACH#sleep_coach", "VOICE#state") is None

    def test_a_tombstoned_singleton_is_invisible(self, monkeypatch):
        # #1969: a restart's tombstone must not seed the fresh cycle's evolved state.
        t = FakeTable(items={("COACH#sleep_coach", "VOICE#state"): {"tombstone": True, "recent_openings": ["lead_with_data"]}})
        monkeypatch.setattr(su, "table", t)
        assert su._get_item("COACH#sleep_coach", "VOICE#state") is None

    def test_a_wrong_phase_singleton_is_invisible(self, monkeypatch):
        t = FakeTable(items={("COACH#sleep_coach", "VOICE#state"): {"phase": "pilot", "recent_openings": ["lead_with_data"]}})
        monkeypatch.setattr(su, "table", t)
        assert su._get_item("COACH#sleep_coach", "VOICE#state") is None

    def test_a_failed_read_degrades_to_none(self, monkeypatch):
        monkeypatch.setattr(su, "table", FakeTable(fail={"get"}))
        assert su._get_item("COACH#sleep_coach", "VOICE#state") is None

    def test_put_item_stamps_provenance_and_casts_floats(self, monkeypatch):
        t = FakeTable()
        monkeypatch.setattr(su, "table", t)
        assert su._put_item({"pk": "COACH#c", "sk": "OUTPUT#x", "score": 0.5}) is True
        written = t.puts[0]
        assert written["score"] == Decimal("0.5")  # boto3 rejects float
        assert written["cycle"] == 12 and written["phase"]

    def test_the_items_own_keys_win_over_the_stamp(self, monkeypatch):
        t = FakeTable()
        monkeypatch.setattr(su, "table", t)
        su._put_item({"pk": "COACH#c", "sk": "OUTPUT#x", "phase": "pilot"})
        assert t.puts[0]["phase"] == "pilot"

    def test_a_failed_write_reports_false_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(su, "table", FakeTable(fail={"put"}))
        assert su._put_item({"pk": "COACH#c", "sk": "OUTPUT#x"}) is False

    def test_query_begins_with_returns_converted_items(self, monkeypatch):
        t = FakeTable(query_pages=[{"Items": [{"sk": "THREAD#a", "reference_count": Decimal("2")}]}])
        monkeypatch.setattr(su, "table", t)
        assert su._query_begins_with("COACH#c", "THREAD#") == [{"sk": "THREAD#a", "reference_count": 2}]

    def test_a_failed_query_degrades_to_an_empty_list(self, monkeypatch):
        monkeypatch.setattr(su, "table", FakeTable(fail={"query"}))
        assert su._query_begins_with("COACH#c", "THREAD#") == []


# ══════════════════════════════════════════════════════════════════════════════
# _load_voice_spec — S3 read + both failure fallbacks
# ══════════════════════════════════════════════════════════════════════════════


class TestVoiceSpecLoader:
    def test_loads_the_spec_from_the_config_prefix(self, monkeypatch):
        fake = FakeS3(body={"anti_pattern_detection": {"phrase_blacklist": ["circle back"]}})
        monkeypatch.setattr(su, "s3", fake)
        spec = su._load_voice_spec("sleep_coach")
        assert spec["anti_pattern_detection"]["phrase_blacklist"] == ["circle back"]
        assert fake.calls == [(su.S3_BUCKET, "config/coaches/sleep_coach.json")]

    def test_a_missing_spec_is_an_empty_default(self, monkeypatch):
        monkeypatch.setattr(su, "s3", FakeS3(raise_no_such_key=True))
        assert su._load_voice_spec("new_coach") == {}

    def test_an_s3_outage_is_an_empty_default(self, monkeypatch):
        monkeypatch.setattr(su, "s3", FakeS3(raise_other=True))
        assert su._load_voice_spec("sleep_coach") == {}


# ══════════════════════════════════════════════════════════════════════════════
# _call_haiku — response parsing (the shapes an LLM actually returns)
# ══════════════════════════════════════════════════════════════════════════════


def _stub_raw(monkeypatch, text):
    monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda req: {"content": [{"text": text}]})


class TestCallHaiku:
    def test_plain_json_is_parsed(self, monkeypatch):
        _stub_raw(monkeypatch, '  {"themes": ["hrv_recovery"]}  ')
        assert su._call_haiku("sys", "msg") == {"themes": ["hrv_recovery"]}

    def test_json_fenced_block_is_unwrapped(self, monkeypatch):
        _stub_raw(monkeypatch, 'Here you go:\n```json\n{"themes": ["sleep"]}\n```\n')
        assert su._call_haiku("sys", "msg") == {"themes": ["sleep"]}

    def test_bare_fenced_block_is_unwrapped(self, monkeypatch):
        _stub_raw(monkeypatch, '```\n{"themes": ["glucose"]}\n```')
        assert su._call_haiku("sys", "msg") == {"themes": ["glucose"]}

    def test_unparseable_text_is_returned_verbatim(self, monkeypatch):
        _stub_raw(monkeypatch, "I could not comply with that request.")
        assert su._call_haiku("sys", "msg") == "I could not comply with that request."

    def test_a_fence_containing_broken_json_falls_through_to_text(self, monkeypatch):
        payload = '```json\n{"themes": [oops}\n```'
        _stub_raw(monkeypatch, payload)
        assert su._call_haiku("sys", "msg") == payload

    def test_a_bare_fence_containing_broken_json_falls_through_to_text(self, monkeypatch):
        payload = "```\n{oops}\n```"
        _stub_raw(monkeypatch, payload)
        assert su._call_haiku("sys", "msg") == payload

    def test_an_unterminated_fence_falls_through_to_text(self, monkeypatch):
        payload = '```json\n{"themes": ["sleep"]}'  # truncated response, no closing fence
        _stub_raw(monkeypatch, payload)
        assert su._call_haiku("sys", "msg") == payload

    def test_the_request_carries_the_cached_system_block(self, monkeypatch):
        captured = {}

        def _capture(req):
            captured["body"] = json.loads(req.data.decode())
            captured["url"] = req.full_url
            return {"content": [{"text": "{}"}]}

        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _capture)
        su._call_haiku("SYSTEM TEXT", "USER TEXT", max_tokens=250, temperature=0.0)
        body = captured["body"]
        assert body["max_tokens"] == 250 and body["temperature"] == 0.0
        assert body["messages"] == [{"role": "user", "content": "USER TEXT"}]
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}

    def test_no_system_prompt_means_no_system_block(self, monkeypatch):
        captured = {}

        def _capture(req):
            captured["body"] = json.loads(req.data.decode())
            return {"content": [{"text": "{}"}]}

        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _capture)
        su._call_haiku(None, "USER TEXT")
        assert "system" not in captured["body"]


# ══════════════════════════════════════════════════════════════════════════════
# CloudWatch emitters — non-fatal by contract
# ══════════════════════════════════════════════════════════════════════════════


class TestMetricEmitters:
    def test_failure_metric_is_dimensioned_by_lambda(self, monkeypatch):
        cw = FakeCloudWatch()
        monkeypatch.setattr(su, "_cw", cw)
        su._emit_failure_metric()
        md = cw.calls[0]["MetricData"][0]
        assert cw.calls[0]["Namespace"] == "LifePlatform/AI"
        assert md["MetricName"] == "AnthropicAPIFailure" and md["Value"] == 1

    def test_a_cloudwatch_outage_never_propagates(self, monkeypatch):
        monkeypatch.setattr(su, "_cw", FakeCloudWatch(fail=True))
        su._emit_failure_metric()  # must not raise
        su._emit_prediction_gradability(1, 1)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# _metric_has_recent_data — pagination + the non-numeric guard
# (the fail-open and dead-source cases are owned by test_prediction_triage_813 /
#  test_gradability_liveness_cross_phase_2023; only the gaps are covered here)
# ══════════════════════════════════════════════════════════════════════════════


class TestLivenessPagination:
    def test_counts_across_every_page(self, monkeypatch):
        # 3 + 2 = 5 numeric values, exactly _LIVENESS_MIN_POINTS, spread over 2 pages.
        pages = [
            {"Items": [{"hrv": 60}, {"hrv": 61}, {"hrv": 62}], "LastEvaluatedKey": {"sk": "DATE#2026-06-15"}},
            {"Items": [{"hrv": 63}, {"hrv": 64}]},
        ]
        t = FakeTable(query_pages=pages)
        monkeypatch.setattr(su, "table", t)
        assert su._metric_has_recent_data("hrv", {}) is True
        assert len(t.query_calls) == 2  # the continuation token was followed
        assert t.query_calls[1]["ExclusiveStartKey"] == {"sk": "DATE#2026-06-15"}

    def test_non_numeric_values_do_not_count_as_data(self, monkeypatch):
        pages = [{"Items": [{"hrv": "n/a"}, {"hrv": None}, {"hrv": "--"}, {"hrv": 60}, {"hrv": 61}, {"hrv": 62}]}]
        monkeypatch.setattr(su, "table", FakeTable(query_pages=pages))
        assert su._metric_has_recent_data("hrv", {}) is False  # only 3 real values < 5


# ══════════════════════════════════════════════════════════════════════════════
# VOICE#state — the staleness state machine
# ══════════════════════════════════════════════════════════════════════════════


def _extraction(opening="lead_with_data", **over):
    base = {
        "themes": ["hrv_recovery"],
        "structural_fingerprint": {"opening_type": opening, "paragraph_count": 3},
        "threads_opened": [],
        "threads_referenced": [],
        "predictions_made": [],
        "commitments_made": [],
        "decision_classes_used": ["observational"],
        "anti_pattern_violations": [],
    }
    base.update(over)
    return base


class TestVoiceState:
    def _run(self, monkeypatch, current, extraction):
        written = []
        monkeypatch.setattr(su, "_get_item", lambda pk, sk: current)
        monkeypatch.setattr(su, "_put_item", lambda item: written.append(item) or True)
        assert su._update_voice_state("sleep_coach", extraction) is True
        return written[0]

    def test_first_ever_output_seeds_the_history(self, monkeypatch):
        item = self._run(monkeypatch, None, _extraction("lead_with_data"))
        assert item["pk"] == "COACH#sleep_coach" and item["sk"] == "VOICE#state"
        assert item["recent_openings"] == ["lead_with_data"]
        assert item["overused_patterns"] == []  # 1 < STALENESS_THRESHOLD
        assert item["last_updated"] == "2026-06-30T12:00:00+00:00"

    def test_a_missing_fingerprint_records_other(self, monkeypatch):
        item = self._run(monkeypatch, None, _extraction(structural_fingerprint={}))
        assert item["recent_openings"] == ["other"]

    def test_openings_append_to_the_existing_history(self, monkeypatch):
        current = {"recent_openings": ["lead_with_observation", "lead_with_correction"]}
        item = self._run(monkeypatch, current, _extraction("lead_with_data"))
        assert item["recent_openings"] == ["lead_with_observation", "lead_with_correction", "lead_with_data"]

    def test_history_is_trimmed_to_the_maximum(self, monkeypatch):
        current = {"recent_openings": [f"o{i}" for i in range(su.MAX_RECENT_OPENINGS)]}
        item = self._run(monkeypatch, current, _extraction("lead_with_data"))
        assert len(item["recent_openings"]) == su.MAX_RECENT_OPENINGS
        assert item["recent_openings"][0] == "o1"  # the oldest fell off
        assert item["recent_openings"][-1] == "lead_with_data"

    def test_two_of_the_last_five_is_not_yet_stale(self, monkeypatch):
        current = {"recent_openings": ["lead_with_data", "a", "b", "c"]}
        item = self._run(monkeypatch, current, _extraction("lead_with_data"))
        assert item["overused_patterns"] == []  # 2 < STALENESS_THRESHOLD (3)

    def test_three_of_the_last_five_flips_the_pattern_to_overused(self, monkeypatch):
        current = {"recent_openings": ["lead_with_data", "a", "lead_with_data", "b"]}
        item = self._run(monkeypatch, current, _extraction("lead_with_data"))
        assert item["overused_patterns"] == ["opening_with_lead_with_data"]

    def test_the_window_is_the_last_five_only(self, monkeypatch):
        # Three old uses fall outside STALENESS_WINDOW — they must not trip the flag.
        current = {"recent_openings": ["lead_with_data"] * 3 + ["a", "b", "c", "d"]}
        item = self._run(monkeypatch, current, _extraction("lead_with_data"))
        assert item["recent_openings"][-5:] == ["a", "b", "c", "d", "lead_with_data"]
        assert item["overused_patterns"] == []

    def test_two_patterns_can_be_flagged_at_once(self, monkeypatch):
        # A 6-entry history whose last 5 are x,y,x,y,x -> x appears 3x, y 2x.
        current = {"recent_openings": ["z", "x", "y", "x", "y"]}
        item = self._run(monkeypatch, current, _extraction("x"))
        assert item["overused_patterns"] == ["opening_with_x"]

    def test_existing_signature_and_anti_patterns_are_carried_forward(self, monkeypatch):
        current = {
            "recent_openings": [],
            "signature_patterns_to_reinforce": ["names the mechanism"],
            "anti_patterns": ["never say circle back"],
        }
        item = self._run(monkeypatch, current, _extraction())
        assert item["signature_patterns_to_reinforce"] == ["names the mechanism"]
        assert item["anti_patterns"] == ["never say circle back"]

    def test_new_violations_are_recorded_on_the_state(self, monkeypatch):
        item = self._run(monkeypatch, None, _extraction(anti_pattern_violations=["used 'circle back'"]))
        assert item["last_violations"] == ["used 'circle back'"]

    def test_a_failed_write_is_reported(self, monkeypatch):
        monkeypatch.setattr(su, "_get_item", lambda pk, sk: None)
        monkeypatch.setattr(su, "_put_item", lambda item: False)
        assert su._update_voice_state("sleep_coach", _extraction()) is False


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT# record — content + the #1987 register guard
# ══════════════════════════════════════════════════════════════════════════════


class TestOutputRecord:
    def _capture(self, monkeypatch):
        written = []
        monkeypatch.setattr(su, "_put_item", lambda item: written.append(item) or True)
        return written

    def test_the_record_mirrors_the_extraction(self, monkeypatch):
        written = self._capture(monkeypatch)
        extraction = _extraction(
            threads_opened=[{"thread_slug": "hrv_inflection_watch", "type": "concern"}],
            threads_referenced=[{"topic": "late caffeine", "context": "updated"}],
            observatory_summary="I'm watching your **HRV** inflection.",
            key_recommendation="Move the last coffee before 2 PM.",
            elena_quote="He is not looking at the glucose curve.",
        )
        assert su._write_output_record("sleep_coach", "2026-06-30", "weekly_email", "one two three", extraction) is True
        item = written[0]
        assert item["pk"] == "COACH#sleep_coach"
        assert item["sk"] == "OUTPUT#2026-06-30#weekly_email"
        assert item["content"] == "one two three" and item["word_count"] == 3
        assert item["threads_opened"] == ["hrv_inflection_watch"]
        assert item["threads_referenced"] == ["late caffeine"]
        assert item["decision_classes"] == ["observational"]
        assert item["key_recommendation"] == "Move the last coffee before 2 PM."
        assert item["created_at"] == "2026-06-30T12:00:00+00:00"
        # Markdown emphasis is stripped unconditionally before publication.
        assert item["observatory_summary"] == "I'm watching your HRV inflection."

    def test_third_person_register_is_rejected_so_the_reader_gets_the_full_content(self, monkeypatch):
        written = self._capture(monkeypatch)
        su._write_output_record(
            "sleep_coach",
            "2026-06-30",
            "weekly_email",
            "body text",
            _extraction(observatory_summary="The sleep coach is in calibration mode this week."),
        )
        assert written[0]["observatory_summary"] is None  # read site falls back to `content`

    def test_a_bare_extraction_still_writes_a_complete_record(self, monkeypatch):
        written = self._capture(monkeypatch)
        su._write_output_record("mind_coach", "2026-06-30", "daily_brief_section", "hello", {})
        item = written[0]
        assert item["themes"] == [] and item["structural_fingerprint"] == {}
        assert item["predictions_made"] == [] and item["anti_pattern_violations"] == []
        assert item["key_recommendation"] is None and item["elena_quote"] is None

    def test_a_failed_write_is_reported(self, monkeypatch):
        monkeypatch.setattr(su, "_put_item", lambda item: False)
        assert su._write_output_record("sleep_coach", "2026-06-30", "weekly_email", "x", {}) is False


# ══════════════════════════════════════════════════════════════════════════════
# THREAD# — open and reference transitions
# ══════════════════════════════════════════════════════════════════════════════


class TestThreadRecords:
    def test_opened_threads_become_open_records_with_a_sanitized_slug(self, monkeypatch):
        written = []
        monkeypatch.setattr(su, "_put_item", lambda item: written.append(item) or True)
        created = su._create_thread_records(
            "sleep_coach",
            "2026-06-30",
            [
                {"thread_slug": "HRV Inflection-Watch", "type": "concern", "summary": "HRV is drifting.", "tags": ["hrv"]},
                {},  # nothing extracted — still a valid, named record
            ],
        )
        assert created == 2
        assert written[0]["sk"] == "THREAD#2026-06-30#hrv_inflection_watch"  # spaces + dashes normalized
        assert written[0]["status"] == "open"
        assert written[0]["type"] == "concern"
        assert written[0]["reference_count"] == 1
        assert written[0]["opened_date"] == "2026-06-30" and written[0]["last_referenced"] == "2026-06-30"
        assert written[1]["sk"] == "THREAD#2026-06-30#unnamed"
        assert written[1]["type"] == "observation"  # the default class

    def test_failed_writes_are_not_counted_as_created(self, monkeypatch):
        monkeypatch.setattr(su, "_put_item", lambda item: False)
        assert su._create_thread_records("sleep_coach", "2026-06-30", [{"thread_slug": "a"}]) == 0

    def test_an_unparseable_generation_date_leaves_a_commitment_undated(self, monkeypatch):
        written = []
        monkeypatch.setattr(su, "_put_item", lambda item: written.append(item) or True)
        created, checkable = su._create_commitment_records(
            "sleep_coach", "not-a-date", [{"commitment_natural": "walk after dinner", "timeframe_hint": "this week"}]
        )
        assert created == 1 and checkable == 0
        assert written[0]["due_date"] is None  # honest absence, not a fabricated date
        assert written[0]["window_days"] == 7

    def test_no_references_is_a_no_op(self, monkeypatch):
        t = FakeTable()
        monkeypatch.setattr(su, "table", t)
        assert su._update_referenced_threads("sleep_coach", "2026-06-30", []) == 0
        assert t.query_calls == []  # the guard returns before any read

    def test_a_reference_bumps_the_matching_thread(self, monkeypatch):
        t = FakeTable(query_pages=[{"Items": [{"sk": "THREAD#2026-06-01#caffeine_timing", "summary": "late caffeine intake", "tags": []}]}])
        monkeypatch.setattr(su, "table", t)
        updated = su._update_referenced_threads("sleep_coach", "2026-06-30", [{"topic": "caffeine timing"}])
        assert updated == 1
        upd = t.updates[0]
        assert upd["Key"] == {"pk": "COACH#sleep_coach", "sk": "THREAD#2026-06-01#caffeine_timing"}
        assert upd["ExpressionAttributeValues"][":lr"] == "2026-06-30"
        assert upd["ExpressionAttributeValues"][":one"] == Decimal("1")

    def test_a_tag_match_also_counts(self, monkeypatch):
        t = FakeTable(query_pages=[{"Items": [{"sk": "THREAD#2026-06-01#x", "summary": "unrelated", "tags": ["glucose_variability"]}]}])
        monkeypatch.setattr(su, "table", t)
        assert su._update_referenced_threads("glucose_coach", "2026-06-30", [{"topic": "glucose"}]) == 1

    def test_only_the_first_match_is_bumped_per_reference(self, monkeypatch):
        items = [
            {"sk": "THREAD#2026-06-01#caffeine_a", "summary": "caffeine timing", "tags": []},
            {"sk": "THREAD#2026-06-02#caffeine_b", "summary": "caffeine timing again", "tags": []},
        ]
        t = FakeTable(query_pages=[{"Items": items}])
        monkeypatch.setattr(su, "table", t)
        assert su._update_referenced_threads("sleep_coach", "2026-06-30", [{"topic": "caffeine"}]) == 1
        assert t.updates[0]["Key"]["sk"] == "THREAD#2026-06-01#caffeine_a"

    def test_short_words_and_empty_topics_never_match(self, monkeypatch):
        t = FakeTable(query_pages=[{"Items": [{"sk": "THREAD#2026-06-01#an_apple", "summary": "an apple a day", "tags": []}]}])
        monkeypatch.setattr(su, "table", t)
        # "an" and "a" are under the 3-character floor — matching on them would
        # bump essentially every thread on the partition.
        assert su._update_referenced_threads("sleep_coach", "2026-06-30", [{"topic": "an a"}, {"topic": ""}]) == 0
        assert t.updates == []

    def test_a_failed_update_is_not_counted(self, monkeypatch):
        t = FakeTable(
            query_pages=[{"Items": [{"sk": "THREAD#2026-06-01#caffeine", "summary": "caffeine timing", "tags": []}]}], fail={"update"}
        )
        monkeypatch.setattr(su, "table", t)
        assert su._update_referenced_threads("sleep_coach", "2026-06-30", [{"topic": "caffeine"}]) == 0


# ══════════════════════════════════════════════════════════════════════════════
# TRACE# and the fallback extraction
# ══════════════════════════════════════════════════════════════════════════════


class TestReasoningTrace:
    def test_trace_composes_the_extraction_into_the_audit_shape(self):
        extraction = _extraction(
            themes=[f"t{i}" for i in range(7)],
            threads_opened=[
                {"thread_slug": "hrv_watch", "type": "concern", "summary": "HRV drifting"},
                {"thread_slug": "bed_time", "type": "recommendation_pending", "summary": "Shift lights out"},
                {"thread_slug": "noise", "type": "observation", "summary": "Just noticing"},
            ],
            threads_referenced=[
                {"topic": "training load", "context": "from the training coach"},
                {"topic": "weather", "context": "it was warm"},
            ],
            predictions_made=[{"claim_natural": "HRV rises next week"}],
        )
        trace = su._build_reasoning_trace("sleep_coach", "2026-06-30", "weekly_email", extraction)
        assert trace["sk"] == "TRACE#2026-06-30#weekly_email"
        # Only concerns and pending recommendations become recommendations.
        assert trace["recommendations_made"] == ["HRV drifting", "Shift lights out"]
        assert trace["primary_drivers"] == ["t0", "t1", "t2", "t3", "t4"]  # top 5 only
        assert trace["predictions_made"] == ["HRV rises next week"]
        # Only cross-domain references are logged as cross-coach inputs.
        assert trace["cross_coach_inputs_used"] == ["training load: from the training coach"]
        assert trace["threads_status"] == [
            {"thread": "hrv_watch", "action": "opened", "type": "concern"},
            {"thread": "bed_time", "action": "opened", "type": "recommendation_pending"},
            {"thread": "noise", "action": "opened", "type": "observation"},
            {"thread": "training load", "action": "referenced"},
            {"thread": "weather", "action": "referenced"},
        ]
        assert trace["counterfactuals_considered"] == []
        assert trace["created_at"] == "2026-06-30T12:00:00+00:00"

    def test_an_empty_extraction_yields_an_empty_but_well_formed_trace(self):
        trace = su._build_reasoning_trace("mind_coach", "2026-06-30", "weekly_email", {})
        assert trace["recommendations_made"] == [] and trace["primary_drivers"] == []
        assert trace["threads_status"] == [] and trace["cross_coach_inputs_used"] == []


class TestDefaultExtraction:
    def test_paragraphs_are_counted_without_the_llm(self):
        out = su._build_default_extraction("first para\n\nsecond para\n\n   \n\nthird para")
        assert out["_fallback"] is True
        assert out["structural_fingerprint"]["paragraph_count"] == 3  # the blank block is dropped
        assert out["structural_fingerprint"]["opening_type"] == "other"
        assert out["structural_fingerprint"]["uses_analogy"] is False
        assert out["decision_classes_used"] == ["observational"]
        assert out["themes"] == [] and out["predictions_made"] == [] and out["commitments_made"] == []

    def test_empty_text_has_no_paragraphs(self):
        assert su._build_default_extraction("")["structural_fingerprint"]["paragraph_count"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# _build_extraction_message
# ══════════════════════════════════════════════════════════════════════════════


class TestExtractionMessage:
    def test_the_output_text_and_type_are_carried_verbatim(self):
        msg = su._build_extraction_message("sleep_coach", "THE OUTPUT", "weekly_email", {})
        assert "## Coach: sleep_coach" in msg
        assert "## Output Type: weekly_email" in msg
        assert "THE OUTPUT" in msg
        assert "Anti-Pattern Checklist" not in msg  # no spec -> no checklist section

    def test_the_voice_specs_blacklists_are_rendered_as_a_checklist(self):
        spec = {
            "anti_pattern_detection": {
                "phrase_blacklist": ["circle back"],
                "structural_blacklist": ["three-bullet summary"],
            }
        }
        msg = su._build_extraction_message("sleep_coach", "text", "weekly_email", spec)
        assert "### Forbidden Phrases" in msg and '"circle back"' in msg
        assert "### Forbidden Structural Patterns" in msg and '"three-bullet summary"' in msg

    def test_an_empty_anti_pattern_block_adds_no_headings(self):
        msg = su._build_extraction_message("sleep_coach", "text", "weekly_email", {"anti_pattern_detection": {}})
        assert "Anti-Pattern Checklist" not in msg


# ══════════════════════════════════════════════════════════════════════════════
# RELATIONSHIP#state — the deterministic rapport writer's wiring (#536)
# ══════════════════════════════════════════════════════════════════════════════


class TestRelationshipSignals:
    def test_a_first_ever_cycle_has_nothing_to_diff_against(self, monkeypatch):
        called = []
        monkeypatch.setattr(su, "_query_begins_with", lambda pk, prefix: called.append(prefix) or [])
        assert su._gather_relationship_signals("sleep_coach", None) == {
            "kept_commitments": 0,
            "broken_commitments": 0,
            "confirmed_predictions": 0,
            "refuted_predictions": 0,
            "board_interactions": 0,
        }
        assert called == []  # the guard short-circuits before any query

    def test_only_outcomes_after_the_cursor_are_counted(self, monkeypatch):
        by_prefix = {
            "COMMITMENT#": [
                {"outcome_date": "2026-06-20", "status": "kept"},  # before cursor
                {"outcome_date": "2026-06-28", "status": "kept"},
                {"outcome_date": "2026-06-29", "status": "broken"},
                {"outcome_date": "2026-06-29", "status": "pending"},  # ungraded
                {"status": "kept"},  # no outcome_date at all
            ],
            "PREDICTION#": [
                {"outcome_date": "2026-06-28", "status": "confirmed"},
                {"outcome_date": "2026-06-29", "status": "refuted"},
                {"outcome_date": "2026-06-01", "status": "confirmed"},  # before cursor
            ],
            "INTERACTION#": [
                {"created_at": "2026-06-29T10:00:00+00:00"},
                {"created_at": "2026-06-25T10:00:00+00:00"},  # == cursor, not newer
                {},
            ],
        }
        monkeypatch.setattr(su, "_query_begins_with", lambda pk, prefix: by_prefix[prefix])
        signals = su._gather_relationship_signals("sleep_coach", "2026-06-25")
        assert signals == {
            "kept_commitments": 1,
            "broken_commitments": 1,
            "confirmed_predictions": 1,
            "refuted_predictions": 1,
            "board_interactions": 1,
        }

    def test_a_failing_category_yields_zero_for_that_category_only(self, monkeypatch):
        def _query(pk, prefix):
            if prefix == "COMMITMENT#":
                raise RuntimeError("query blew up")
            if prefix == "PREDICTION#":
                return [{"outcome_date": "2026-06-29", "status": "confirmed"}]
            return [{"created_at": "2026-06-29T00:00:00+00:00"}]

        monkeypatch.setattr(su, "_query_begins_with", _query)
        signals = su._gather_relationship_signals("sleep_coach", "2026-06-25")
        assert signals["kept_commitments"] == 0  # the failed category degrades to zero …
        assert signals["confirmed_predictions"] == 1  # … the others still report
        assert signals["board_interactions"] == 1

    def test_each_category_fails_independently(self, monkeypatch):
        def _query(pk, prefix):
            if prefix == "COMMITMENT#":
                return [{"outcome_date": "2026-06-29", "status": "kept"}]
            raise RuntimeError(f"{prefix} query blew up")

        monkeypatch.setattr(su, "_query_begins_with", _query)
        signals = su._gather_relationship_signals("sleep_coach", "2026-06-25")
        assert signals["kept_commitments"] == 1
        assert signals["confirmed_predictions"] == 0 and signals["refuted_predictions"] == 0
        assert signals["board_interactions"] == 0


class TestRelationshipStateUpdate:
    def test_a_brand_new_relationship_starts_clinical_and_is_written(self, monkeypatch):
        written = []
        monkeypatch.setattr(su, "_get_item", lambda pk, sk: None)
        monkeypatch.setattr(su, "_put_item", lambda item: written.append(item) or True)
        monkeypatch.setattr(
            su,
            "_gather_relationship_signals",
            lambda cid, since: dict.fromkeys(
                ("kept_commitments", "broken_commitments", "confirmed_predictions", "refuted_predictions", "board_interactions"), 0
            ),
        )
        out = su._update_relationship_state("sleep_coach", "2026-06-30")
        assert out["pk"] == "COACH#sleep_coach" and out["sk"] == "RELATIONSHIP#state"
        assert out["journey_phase"] == "clinical"
        assert out["interaction_count"] == 1  # this cycle counts
        assert out["last_interaction_date"] == "2026-06-30"
        assert written and written[0]["sk"] == "RELATIONSHIP#state"

    def test_kept_commitments_raise_rapport_above_a_bare_cycle(self, monkeypatch):
        base = {
            "coach_id": "sleep_coach",
            "rapport_level": 0.30,
            "interaction_count": 4,
            "journey_phase": "clinical",
            "first_interaction_date": "2026-05-01",
            "last_interaction_date": "2026-06-20",
        }

        def _run(signals):
            monkeypatch.setattr(su, "_get_item", lambda pk, sk: dict(base))
            monkeypatch.setattr(su, "_put_item", lambda item: True)
            monkeypatch.setattr(su, "_gather_relationship_signals", lambda cid, since: signals)
            return su._update_relationship_state("sleep_coach", "2026-06-30")

        zeros = dict.fromkeys(
            ("kept_commitments", "broken_commitments", "confirmed_predictions", "refuted_predictions", "board_interactions"), 0
        )
        quiet = _run(dict(zeros))
        engaged = _run({**zeros, "kept_commitments": 2})
        broken = _run({**zeros, "broken_commitments": 2})
        assert engaged["rapport_level"] > quiet["rapport_level"] > broken["rapport_level"]
        # The cursor advances so the next run cannot double-count the same outcomes.
        assert engaged["last_interaction_date"] == "2026-06-30"


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — validation guards + end-to-end orchestration
# ══════════════════════════════════════════════════════════════════════════════


class TestHandlerValidation:
    def test_missing_coach_id_is_rejected(self):
        with pytest.raises(ValueError, match="coach_id"):
            su.lambda_handler({"output_text": "x"}, None)

    def test_missing_output_text_is_rejected(self):
        with pytest.raises(ValueError, match="output_text"):
            su.lambda_handler({"coach_id": "sleep_coach"}, None)

    def test_a_missing_generation_date_defaults_to_today(self, monkeypatch):
        t = FakeTable()
        monkeypatch.setattr(su, "table", t)
        monkeypatch.setattr(su, "_call_haiku", lambda **k: _extraction())
        su.lambda_handler({"coach_id": "sleep_coach", "output_text": "body"}, None)
        # now() is pinned to 2026-06-30 — no wall clock in this assertion.
        assert t.sk_of("OUTPUT#") == ["OUTPUT#2026-06-30#weekly_email"]


class TestHandlerEndToEnd:
    def _extraction_with_everything(self):
        return _extraction(
            threads_opened=[{"thread_slug": "hrv_watch", "type": "concern", "summary": "HRV drifting"}],
            threads_referenced=[{"topic": "caffeine timing", "context": "updated with new data"}],
            predictions_made=[
                {
                    "claim_natural": "HRV will improve over the next two weeks",
                    "metric_hint": "hrv",
                    "direction": "up",
                    "timeframe_hint": "2 weeks",
                    "confidence_stated": "70%",
                },
                {
                    "claim_natural": "You'll feel more like yourself",
                    "metric_hint": None,
                    "timeframe_hint": "a month",
                },
                {"claim_natural": ""},  # blank claim — skipped entirely
            ],
            commitments_made=[
                {
                    "commitment_natural": "Move the last coffee before 2 PM",
                    "action_check": "resting_heart_rate",
                    "direction": "down",
                    "timeframe_hint": "this week",
                }
            ],
        )

    def _wire(self, monkeypatch, *, live_metrics=True):
        t = FakeTable(
            items={("COACH#sleep_coach", "VOICE#state"): {"recent_openings": ["lead_with_data", "lead_with_data"]}},
            liveness_pages=[{"Items": [{"hrv": v} for v in (60, 61, 62, 63, 64)] if live_metrics else []}],
            begins_pages=[
                # the THREAD# scan for referenced-thread matching; the later
                # RELATIONSHIP# signal queries drain to empty pages.
                {"Items": [{"sk": "THREAD#2026-06-01#caffeine_timing", "summary": "late caffeine", "tags": ["caffeine"]}]},
            ],
        )
        monkeypatch.setattr(su, "table", t)
        monkeypatch.setattr(su, "_call_haiku", lambda **k: self._extraction_with_everything())
        return t

    def test_the_output_record_freezes_the_cockpits_reading_at_publication(self, monkeypatch):
        """#2575: `published_vitals` must reach the OUTPUT# row through the real handler.

        The nightly `cross_surface:vitals` check compares a coach's prose against this
        stamp; without it the comparison is a frozen artifact against a surface that
        has moved on. Absence of the stamp is a silent revert to that, so it is proved
        end-to-end here, not only at the helper.
        """
        t = self._wire(monkeypatch)
        t._vitals_pages = [{"Items": [{"sk": "DATE#2026-06-30", "recovery_score": 54, "hrv": 41.07, "resting_heart_rate": 56}]}]
        monkeypatch.setattr(su, "_cw", FakeCloudWatch())
        su.lambda_handler(
            {
                "coach_id": "sleep_coach",
                "output_text": "para one\n\npara two",
                "output_type": "weekly_email",
                "generation_date": "2026-06-30",
            },
            None,
        )
        stamp = next(p for p in t.puts if p["sk"] == "OUTPUT#2026-06-30#weekly_email")["published_vitals"]
        assert float(stamp["recovery_pct"]) == 54 and float(stamp["hrv_ms"]) == 41.07 and float(stamp["rhr_bpm"]) == 56
        assert stamp["recovery_as_of"] == "2026-06-30"

    def test_a_dark_spine_writes_no_stamp_rather_than_an_empty_one(self, monkeypatch):
        """An empty stamp reads as "the cockpit had no reading" — the check must instead
        see "not stamped" and fall back to the live comparison."""
        t = self._wire(monkeypatch)  # vitals_pages defaults to empty -> Spine finds nothing
        monkeypatch.setattr(su, "_cw", FakeCloudWatch())
        su.lambda_handler(
            {
                "coach_id": "sleep_coach",
                "output_text": "para one\n\npara two",
                "output_type": "weekly_email",
                "generation_date": "2026-06-30",
            },
            None,
        )
        assert "published_vitals" not in next(p for p in t.puts if p["sk"].startswith("OUTPUT#"))

    def test_one_run_writes_every_state_partition(self, monkeypatch):
        t = self._wire(monkeypatch)
        cw = FakeCloudWatch()
        monkeypatch.setattr(su, "_cw", cw)
        trace = su.lambda_handler(
            {
                "coach_id": "sleep_coach",
                "output_text": "para one\n\npara two",
                "output_type": "weekly_email",
                "generation_date": "2026-06-30",
            },
            None,
        )
        assert t.sk_of("OUTPUT#") == ["OUTPUT#2026-06-30#weekly_email"]
        assert t.sk_of("VOICE#state") == ["VOICE#state"]
        assert t.sk_of("THREAD#") == ["THREAD#2026-06-30#hrv_watch"]
        assert t.sk_of("TRACE#") == ["TRACE#2026-06-30#weekly_email"]
        assert t.sk_of("RELATIONSHIP#state") == ["RELATIONSHIP#state"]
        assert len(t.sk_of("PREDICTION#")) == 2  # the blank claim was dropped
        assert len(t.sk_of("COMMITMENT#")) == 1
        assert t.updates and t.updates[0]["Key"]["sk"] == "THREAD#2026-06-01#caffeine_timing"
        # The handler returns the trace, Decimal-free for JSON serialization.
        assert trace["sk"] == "TRACE#2026-06-30#weekly_email"
        # The trace mirrors the raw extraction (blank claim included); only the
        # PREDICTION# writer filters claimless entries.
        assert trace["predictions_made"] == ["HRV will improve over the next two weeks", "You'll feel more like yourself", ""]
        # Three uses of lead_with_data in the last five outputs -> flagged overused.
        voice = next(p for p in t.puts if p["sk"] == "VOICE#state")
        assert voice["overused_patterns"] == ["opening_with_lead_with_data"]
        # SS-06 gradability metric: one directional, one qualitative.
        share = [m for c in cw.calls for m in c["MetricData"] if m["MetricName"] == "PredictionGradableShare"]
        assert share and share[0]["Value"] == 0.5

    def test_a_metric_backed_prediction_becomes_gradable(self, monkeypatch):
        t = self._wire(monkeypatch)
        su.lambda_handler(
            {"coach_id": "sleep_coach", "output_text": "body", "generation_date": "2026-06-30"},
            None,
        )
        preds = {p["sk"]: p for p in t.puts if p["sk"].startswith("PREDICTION#")}
        directional = [p for p in preds.values() if p["evaluation"]["type"] == "directional"]
        qualitative = [p for p in preds.values() if p["evaluation"]["type"] == "qualitative"]
        assert len(directional) == 1 and len(qualitative) == 1
        d = directional[0]
        assert d["evaluation"]["metric"] == "hrv" and d["evaluation"]["condition"] == "up"
        assert d["evaluation"]["evaluation_window_days"] == 14  # "2 weeks"
        assert d["subdomain"] == "hrv"
        assert d["confidence"] == Decimal("0.7")  # "70%"
        assert d["status"] == "pending" and d["outcome"] is None
        assert d["decision_class"] == "observational"
        assert qualitative[0]["evaluation"]["evaluation_window_days"] == Decimal("30")  # "a month"
        assert qualitative[0]["confidence"] == Decimal("0.5")  # none stated -> neutral

    def test_a_dead_metric_source_downgrades_the_prediction_to_qualitative(self, monkeypatch):
        # #813: a gradable spec over a source producing no data can only expire
        # inconclusive — qualitative is the honest classification.
        t = self._wire(monkeypatch, live_metrics=False)
        su.lambda_handler({"coach_id": "sleep_coach", "output_text": "body", "generation_date": "2026-06-30"}, None)
        preds = [p for p in t.puts if p["sk"].startswith("PREDICTION#")]
        assert all(p["evaluation"]["type"] == "qualitative" for p in preds)

    def test_an_llm_failure_falls_back_to_the_default_extraction(self, monkeypatch):
        t = FakeTable()
        monkeypatch.setattr(su, "table", t)

        def _boom(**kwargs):
            raise RuntimeError("Bedrock unavailable")

        monkeypatch.setattr(su, "_call_haiku", _boom)
        trace = su.lambda_handler(
            {"coach_id": "sleep_coach", "output_text": "one\n\ntwo", "generation_date": "2026-06-30"},
            None,
        )
        # State is still written — a failed extraction must not lose the output.
        assert t.sk_of("OUTPUT#") == ["OUTPUT#2026-06-30#weekly_email"]
        assert trace["decision_classes_used"] == ["observational"]
        assert t.sk_of("PREDICTION#") == [] and t.sk_of("THREAD#") == []
        out = next(p for p in t.puts if p["sk"].startswith("OUTPUT#"))
        assert out["structural_fingerprint"]["paragraph_count"] == Decimal("2")

    def test_a_non_dict_llm_response_falls_back_too(self, monkeypatch):
        t = FakeTable()
        monkeypatch.setattr(su, "table", t)
        monkeypatch.setattr(su, "_call_haiku", lambda **k: "I'm sorry, I can't do that.")
        su.lambda_handler({"coach_id": "sleep_coach", "output_text": "body", "generation_date": "2026-06-30"}, None)
        out = next(p for p in t.puts if p["sk"].startswith("OUTPUT#"))
        assert out["themes"] == []  # the raw string was never treated as an extraction

    def test_timeframe_hints_map_to_evaluation_windows(self, monkeypatch):
        t = FakeTable(liveness_pages=[{"Items": [{"hrv": v} for v in (60, 61, 62, 63, 64)]}])
        monkeypatch.setattr(su, "table", t)
        monkeypatch.setattr(
            su,
            "_call_haiku",
            lambda **k: _extraction(
                predictions_made=[
                    {"claim_natural": "a rises", "metric_hint": "hrv", "direction": "up", "timeframe_hint": "in 3 weeks"},
                    {"claim_natural": "b rises", "metric_hint": "hrv", "direction": "up", "timeframe_hint": "over the next month"},
                    {"claim_natural": "c rises", "metric_hint": "hrv", "direction": "up", "timeframe_hint": "in 10 days"},
                    {"claim_natural": "d rises", "metric_hint": "hrv", "direction": "up", "timeframe_hint": "in a few weeks"},
                    {"claim_natural": "e rises", "metric_hint": "hrv", "direction": "up", "timeframe_hint": "in a few days"},
                    {"claim_natural": "f rises", "metric_hint": "hrv", "direction": "up", "timeframe_hint": ""},
                ]
            ),
        )
        su.lambda_handler({"coach_id": "sleep_coach", "output_text": "body", "generation_date": "2026-06-30"}, None)
        windows = {p["claim_natural"]: p["evaluation"]["evaluation_window_days"] for p in t.puts if p["sk"].startswith("PREDICTION#")}
        assert windows["a rises"] == 21  # 3 weeks
        assert windows["b rises"] == 30  # a month
        assert windows["c rises"] == 10  # 10 days
        assert windows["d rises"] == 14  # unit word, no number -> the 14-day default
        assert windows["e rises"] == 14
        assert windows["f rises"] == 14  # no hint at all

    def test_a_metric_hint_that_does_not_normalize_is_qualitative(self, monkeypatch):
        t = FakeTable()
        monkeypatch.setattr(su, "table", t)
        monkeypatch.setattr(
            su,
            "_call_haiku",
            lambda **k: _extraction(
                predictions_made=[
                    {
                        "claim_natural": "your general vibe will improve",
                        "metric_hint": "overall sense of wellbeing",  # prose, not an allowlisted key
                        "direction": "up",
                    }
                ]
            ),
        )
        su.lambda_handler({"coach_id": "sleep_coach", "output_text": "body", "generation_date": "2026-06-30"}, None)
        pred = next(p for p in t.puts if p["sk"].startswith("PREDICTION#"))
        assert pred["evaluation"]["type"] == "qualitative"
        assert pred["evaluation"]["metric"] is None
        assert pred["subdomain"] == "general"

    def test_a_relationship_failure_never_blocks_the_rest_of_the_run(self, monkeypatch):
        t = self._wire(monkeypatch)

        def _boom(coach_id, generation_date):
            raise RuntimeError("relationship engine exploded")

        monkeypatch.setattr(su, "_update_relationship_state", _boom)
        trace = su.lambda_handler({"coach_id": "sleep_coach", "output_text": "body", "generation_date": "2026-06-30"}, None)
        assert trace["sk"] == "TRACE#2026-06-30#weekly_email"
        assert t.sk_of("OUTPUT#") and t.sk_of("TRACE#")
        assert t.sk_of("RELATIONSHIP#state") == []
