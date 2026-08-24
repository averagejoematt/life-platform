"""tests/test_ai_calls_output_frame_2815.py — #2815: the OUTPUT# frame's two
`ai_calls.py` writers, PT/UTC-boundary pinned.

`ai_calls._run_coach_v2_pipeline` invokes `coach-state-updater` (async) at two
sites: the fresh-generation write (Step 7) and the cache-reuse write (the #738
hash-and-reuse skip path). Both used to key `generation_date` from a naive
`_date_cls.today()` — the OUTPUT# sk's UTC frame the issue retires — and now
both resolve `common.pacific_time.pacific_today()`, the SAME primitive
`coach_state_updater.py`'s own no-generation_date fallback and
`coach_quality_gate.py`'s same-day self-exclusion resolve (see
tests/test_coach_state_updater.py and tests/test_coach_repetition_detector_2350.py
for the sibling pins on those two). This file drives the REAL production
pipeline function at a pinned PT-evening instant — where the UTC calendar day
has already rolled to tomorrow — through fakes for Bedrock/S3/DynamoDB/Lambda,
never a reimplementation of its date logic.
"""

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai import ai_calls  # noqa: E402
from common import pacific_time  # noqa: E402

VOICE_SPEC = {
    "display_name": "Dr. Sarah Chen",
    "domain": "sleep",
    "few_shot_examples": [],
    "structural_voice_rules": {},
    "decision_style": {},
    "anti_pattern_detection": {},
}

# 2026-08-24 20:00 PDT == 2026-08-25 03:00 UTC — the two frames disagree.
_PT_EVENING_INSTANT = datetime(2026, 8, 24, 20, 0, 0, tzinfo=pacific_time.PACIFIC)
_PT_DAY = "2026-08-24"
_UTC_DAY = _PT_EVENING_INSTANT.astimezone(timezone.utc).strftime("%Y-%m-%d")

assert _UTC_DAY == "2026-08-25" and _UTC_DAY != _PT_DAY  # sanity: the pinned instant really straddles the boundary


def _state_updater_payloads(fake_lambda):
    return [
        json.loads(c.kwargs["Payload"]) for c in fake_lambda.invoke.call_args_list if c.kwargs.get("FunctionName") == "coach-state-updater"
    ]


def _fake_boto_env(monkeypatch, fake_lambda_invoke, fake_table=None):
    """Wire ai_calls.boto3 to fakes — mirrors tests/test_coach_prompt_hygiene_952.py's
    `_fake_pipeline_env`, the established pattern for driving `_run_coach_v2_pipeline`
    without AWS."""
    fake_lambda = MagicMock()
    fake_lambda.invoke.side_effect = fake_lambda_invoke

    fake_s3 = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps(VOICE_SPEC).encode()
    fake_s3.get_object.return_value = {"Body": body}

    if fake_table is None:
        fake_table = MagicMock()
        fake_table.query.side_effect = RuntimeError("no DDB in tests")
        fake_table.get_item.side_effect = RuntimeError("no DDB in tests")
        fake_table.put_item.side_effect = RuntimeError("no DDB in tests")
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table

    fake_boto3 = MagicMock()
    fake_boto3.client.side_effect = lambda service, **kw: fake_lambda if service == "lambda" else fake_s3
    fake_boto3.resource.return_value = fake_resource
    monkeypatch.setattr(ai_calls, "boto3", fake_boto3)
    return fake_lambda, fake_table


def _standard_lambda_invoke(**kwargs):
    fn = kwargs["FunctionName"]
    payload_mock = MagicMock()
    if fn == "coach-narrative-orchestrator":
        brief = {"generation_brief": {"voice_guidance": {}, "decision_class_ceiling": "observational"}}
        payload_mock.read.return_value = json.dumps({"body": json.dumps(brief)}).encode()
    elif fn == "coach-quality-gate":
        payload_mock.read.return_value = json.dumps({"statusCode": 200, "passed": True, "score": 90}).encode()
    else:  # coach-state-updater (async, fire-and-forget)
        payload_mock.read.return_value = b"{}"
    return {"Payload": payload_mock}


class TestFreshGenerationWriteDate:
    def test_records_the_pacific_day_not_utc(self, monkeypatch):
        monkeypatch.setattr(ai_calls, "_comp_results_cache", {"trends": {}})
        monkeypatch.setattr(pacific_time, "pacific_now", lambda: _PT_EVENING_INSTANT)
        monkeypatch.setattr(ai_calls, "call_anthropic", lambda *a, **kw: "Sleep looked steady this week.")

        fake_lambda, _ = _fake_boto_env(monkeypatch, _standard_lambda_invoke)
        result = ai_calls._run_coach_v2_pipeline("sleep_coach", {"whoop": {}}, "sleep", {}, "")
        assert result == "Sleep looked steady this week."

        payloads = _state_updater_payloads(fake_lambda)
        assert payloads, "expected a coach-state-updater invoke"
        assert payloads[0]["generation_date"] == _PT_DAY, "must land on the Pacific day, not the UTC one"


class TestCacheReuseWriteDate:
    def test_records_the_pacific_day_not_utc(self, monkeypatch):
        from common import generation_cache

        monkeypatch.setattr(ai_calls, "_comp_results_cache", {"trends": {}})
        monkeypatch.setattr(pacific_time, "pacific_now", lambda: _PT_EVENING_INSTANT)
        monkeypatch.setattr(
            ai_calls, "call_anthropic", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not regenerate on a cache hit"))
        )

        # A cache HIT: check_reuse_or_explain returns the previously-gated text.
        monkeypatch.setattr(
            generation_cache,
            "check_reuse_or_explain",
            lambda table, coach_id, output_type, parts: ("fp-123", "Same steady week as before.", "2026-08-20"),
        )
        recorded_reuse = {}
        monkeypatch.setattr(
            generation_cache,
            "record_reuse",
            lambda table, coach_id, output_type, today: recorded_reuse.update(today=today),
        )
        monkeypatch.setattr(generation_cache, "emit_skip_metric", lambda *a, **kw: None)

        fake_lambda, _ = _fake_boto_env(monkeypatch, _standard_lambda_invoke)
        result = ai_calls._run_coach_v2_pipeline("sleep_coach", {"whoop": {}}, "sleep", {}, "")
        assert result == "Same steady week as before."

        assert recorded_reuse["today"] == _PT_DAY, "reuse bookkeeping must also use the Pacific day"
        payloads = _state_updater_payloads(fake_lambda)
        assert payloads, "expected a coach-state-updater invoke on the reuse path too"
        assert payloads[0]["generation_date"] == _PT_DAY, "must land on the Pacific day, not the UTC one"
