"""
tests/test_bedrock_batch.py — the batch-inference seam (#409, ADR-132).

The module is a latent capability (no producer calls it at current volume), so
these tests pin the *decision logic* that is load-bearing today — the 100-record
eligibility floor, the real-time fallback, the record formatting that keeps batch
byte-identical to invoke(), and the 50%-savings math — plus mock-level coverage of
the submit/poll wrappers so the enablement path is not untested.

Run:  python3 -m pytest tests/test_bedrock_batch.py -v
"""

import json
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from ai import bedrock_batch as bb  # noqa: E402
from bundle_stubs import stub_bundled_module


# ── eligibility floor (the load-bearing gate today) ─────────────────────────
def test_below_floor_not_eligible():
    ok, reason = bb.batch_preflight(62, "claude-haiku-4-5-20251001")
    assert ok is False
    assert "floor" in reason and "62" in reason


def test_at_floor_eligible():
    ok, reason = bb.batch_preflight(bb.MIN_RECORDS_PER_JOB, "claude-haiku-4-5-20251001")
    assert ok is True


def test_floor_is_100():
    assert bb.MIN_RECORDS_PER_JOB == 100


def test_tier3_blocks_even_above_floor(monkeypatch):
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: 3
    stub_bundled_module(monkeypatch, "ai.budget_guard", stub)
    ok, reason = bb.batch_preflight(500, "claude-sonnet-4-6")
    assert ok is False
    assert "tier 3" in reason


def test_tier0_allows_above_floor(monkeypatch):
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: 0
    stub_bundled_module(monkeypatch, "ai.budget_guard", stub)
    ok, _ = bb.batch_preflight(500, "claude-sonnet-4-6")
    assert ok is True


# ── record formatting stays in lockstep with invoke() ───────────────────────
def test_build_jsonl_record_shape():
    rec = bb.build_jsonl_record("R1", {"messages": [], "max_tokens": 10}, "claude-sonnet-4-6")
    assert rec["recordId"] == "R1"
    mi = rec["modelInput"]
    assert mi["anthropic_version"] == "bedrock-2023-05-31"
    assert "model" not in mi  # routing-only key stripped


def test_build_jsonl_record_scrubs_sampling_on_fable():
    rec = bb.build_jsonl_record(
        "R2",
        {"messages": [], "max_tokens": 10, "temperature": 0.7, "top_p": 0.9, "top_k": 5},
        "claude-fable-5",
    )
    mi = rec["modelInput"]
    assert "temperature" not in mi and "top_p" not in mi and "top_k" not in mi


def test_build_jsonl_record_keeps_sonnet_sampling():
    rec = bb.build_jsonl_record("R3", {"messages": [], "max_tokens": 10, "temperature": 0.3}, "claude-sonnet-4-6")
    assert rec["modelInput"]["temperature"] == 0.3


# ── savings math is exactly the 50% discount ────────────────────────────────
def test_estimate_batch_savings_is_half():
    usage = [{"input_tokens": 1000, "output_tokens": 500}] * 4
    s = bb.estimate_batch_savings(usage, "claude-haiku-4-5-20251001")
    assert s["discount"] == 0.5
    assert abs(s["batch_usd"] - s["on_demand_usd"] * 0.5) < 1e-9
    assert abs(s["saved_usd"] - s["on_demand_usd"] * 0.5) < 1e-9
    assert s["on_demand_usd"] > 0


# ── real-time fallback is first-class ───────────────────────────────────────
def test_run_or_fallback_below_floor_runs_realtime():
    calls = []

    def realtime(model_input):
        calls.append(model_input)
        return {"ok": True}

    records = [bb.build_jsonl_record(f"R{i}", {"messages": [], "max_tokens": 5}, "claude-haiku-4-5-20251001") for i in range(62)]
    out = bb.run_or_fallback(records, "claude-haiku-4-5-20251001", realtime)
    assert out["mode"] == "realtime"
    assert len(out["results"]) == 62
    assert len(calls) == 62  # every record ran on the real-time path


def _tier(monkeypatch, n=0):
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: n
    stub_bundled_module(monkeypatch, "ai.budget_guard", stub)


def _records(n, model="claude-sonnet-4-6"):
    return [bb.build_jsonl_record(f"R{i}", {"messages": [{"role": "user", "content": f"q{i}"}], "max_tokens": 5}, model) for i in range(n)]


class _FakeBatch:
    """Stands in for the S3 + Bedrock control-plane calls run_or_fallback makes."""

    def __init__(self, monkeypatch, status="Completed", output_lines=None):
        self.submitted = []
        self.stopped = []
        self.metered = []
        self.status = status
        self.output_lines = output_lines

        def _submit(records, model_name, in_uri, out_uri, role_arn, job_name=None):
            self.submitted.append({"n": len(records), "in": in_uri, "out": out_uri, "role": role_arn, "job_name": job_name})
            return "arn:aws:bedrock:us-west-2:123:model-invocation-job/abc123"

        monkeypatch.setattr(bb, "submit_batch", _submit)
        monkeypatch.setattr(
            bb,
            "wait_for_batch",
            lambda arn, deadline, poll_interval=60.0: {
                "status": self.status,
                "done": self.status in bb._TERMINAL_STATES,
                "succeeded": self.status in bb._SUCCESS_STATES,
                "message": "",
            },
        )
        ctrl = MagicMock()
        ctrl.stop_model_invocation_job.side_effect = lambda jobIdentifier: self.stopped.append(jobIdentifier)
        monkeypatch.setattr(bb, "_ctrl", lambda: ctrl)
        monkeypatch.setattr(bb, "_read_output", lambda uri, key: bb.parse_output_jsonl("\n".join(self.output_lines or [])))
        monkeypatch.setattr(bb, "_cleanup", lambda i, o, log: None)
        monkeypatch.setattr(bb, "_meter_batch_record", lambda usage, model_id: self.metered.append(usage))
        monkeypatch.setattr(bb, "_dev_cap_projected", lambda records, model_name: None)


def _line(rid, text="ok", usage=None):
    out = {"content": [{"type": "text", "text": text}], "usage": usage or {"input_tokens": 10, "output_tokens": 5}}
    return json.dumps({"recordId": rid, "modelInput": {}, "modelOutput": out})


def test_run_or_fallback_above_floor_submits_and_maps_back_by_record_id(monkeypatch):
    _tier(monkeypatch)
    recs = _records(120)
    # Bedrock returns records UNORDERED — reversed here; results must come back in input order.
    fake = _FakeBatch(monkeypatch, output_lines=[_line(r["recordId"], text=r["recordId"]) for r in reversed(recs)])
    realtime_calls = []
    out = bb.run_or_fallback(recs, "claude-sonnet-4-6", lambda mi: realtime_calls.append(mi), role_arn="arn:role", log=lambda m: None)
    assert out["mode"] == "batch"
    assert out["batch_records"] == 120 and out["realtime_records"] == 0
    assert [bb_text(r) for r in out["results"]] == [r["recordId"] for r in recs]
    assert realtime_calls == []
    assert fake.submitted[0]["n"] == 120 and fake.submitted[0]["role"] == "arn:role"
    assert "/bedrock-batch/" in fake.submitted[0]["in"] and "generated/" not in fake.submitted[0]["in"]
    assert len(fake.metered) == 120  # every batch record goes through the chokepoint's telemetry
    assert out["savings"]["discount"] == 0.5
    assert "120 of 120 records answered by batch" in out["reason"]


def bb_text(resp):
    return resp["content"][0]["text"]


def test_run_or_fallback_reruns_errored_and_missing_records_on_demand(monkeypatch):
    _tier(monkeypatch)
    recs = _records(100)
    lines = [_line(r["recordId"]) for r in recs[:97]]
    lines.append(json.dumps({"recordId": "R97", "modelInput": {}, "error": {"errorCode": 400, "errorMessage": "bad"}}))
    # R98 and R99 never appear in the output at all.
    _FakeBatch(monkeypatch, output_lines=lines)
    seen = []
    out = bb.run_or_fallback(recs, "claude-sonnet-4-6", lambda mi: seen.append(mi) or "RT", role_arn="arn:role", log=lambda m: None)
    assert out["mode"] == "batch+realtime"
    assert out["realtime_record_ids"] == ["R97", "R98", "R99"]
    assert out["results"][97:] == ["RT", "RT", "RT"] and len(seen) == 3
    assert out["batch_records"] == 97


def test_run_or_fallback_deadline_miss_stops_job_and_runs_everything_on_demand(monkeypatch):
    _tier(monkeypatch)
    fake = _FakeBatch(monkeypatch, status="InProgress")
    out = bb.run_or_fallback(_records(100), "claude-sonnet-4-6", lambda mi: "RT", role_arn="arn:role", log=lambda m: None)
    assert fake.stopped == ["arn:aws:bedrock:us-west-2:123:model-invocation-job/abc123"]
    assert out["results"] == ["RT"] * 100 and out["batch_records"] == 0
    assert "missed its deadline" in out["reason"]


def _raising_wait(monkeypatch, fake, stop_raises=False):
    from botocore.exceptions import ClientError

    def _wait(arn, deadline, poll_interval=60.0):
        raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "GetModelInvocationJob")

    monkeypatch.setattr(bb, "wait_for_batch", _wait)
    cleaned = []
    monkeypatch.setattr(bb, "_cleanup", lambda i, o, log: cleaned.append((i, o)))
    if stop_raises:
        ctrl = MagicMock()
        ctrl.stop_model_invocation_job.side_effect = RuntimeError("stop denied")
        monkeypatch.setattr(bb, "_ctrl", lambda: ctrl)
    return cleaned


def test_run_or_fallback_wait_exception_stops_job_runs_on_demand_and_cleans_up(monkeypatch):
    _tier(monkeypatch)
    fake = _FakeBatch(monkeypatch)
    cleaned = _raising_wait(monkeypatch, fake)
    out = bb.run_or_fallback(_records(100), "claude-sonnet-4-6", lambda mi: "RT", role_arn="arn:role", log=lambda m: None)
    assert fake.stopped == ["arn:aws:bedrock:us-west-2:123:model-invocation-job/abc123"]
    assert out["results"] == ["RT"] * 100 and out["batch_records"] == 0 and out["realtime_records"] == 100
    assert cleaned == [(fake.submitted[0]["in"], fake.submitted[0]["out"])]
    assert "wait failed" in out["reason"]


def test_run_or_fallback_wait_exception_with_failing_stop_still_falls_back_and_cleans_up(monkeypatch):
    _tier(monkeypatch)
    fake = _FakeBatch(monkeypatch)
    cleaned = _raising_wait(monkeypatch, fake, stop_raises=True)
    logs = []
    out = bb.run_or_fallback(_records(100), "claude-sonnet-4-6", lambda mi: "RT", role_arn="arn:role", log=logs.append)
    assert out["results"] == ["RT"] * 100
    assert cleaned == [(fake.submitted[0]["in"], fake.submitted[0]["out"])]
    assert any("could not stop" in m for m in logs)


def test_run_or_fallback_failed_job_runs_everything_on_demand(monkeypatch):
    _tier(monkeypatch)
    _FakeBatch(monkeypatch, status="Failed")
    out = bb.run_or_fallback(_records(100), "claude-sonnet-4-6", lambda mi: "RT", role_arn="arn:role", log=lambda m: None)
    assert out["results"] == ["RT"] * 100 and "ended Failed" in out["reason"]


def test_run_or_fallback_batch_result_fn_shapes_batch_output_like_realtime(monkeypatch):
    _tier(monkeypatch)
    recs = _records(100)
    _FakeBatch(monkeypatch, output_lines=[_line(r["recordId"], text="t") for r in recs])
    out = bb.run_or_fallback(recs, "claude-sonnet-4-6", lambda mi: "RT", batch_result_fn=bb_text, role_arn="arn:role", log=lambda m: None)
    assert out["results"] == ["t"] * 100


def test_run_or_fallback_force_realtime_never_submits(monkeypatch):
    _tier(monkeypatch)
    fake = _FakeBatch(monkeypatch)
    out = bb.run_or_fallback(_records(150), "claude-sonnet-4-6", lambda mi: "RT", force_realtime=True)
    assert out["mode"] == "realtime" and fake.submitted == []
    assert "real-time requested" in out["reason"]


def test_run_or_fallback_below_floor_says_so_in_its_reason():
    out = bb.run_or_fallback(_records(3), "claude-sonnet-4-6", lambda mi: "RT")
    assert out["mode"] == "realtime" and "floor" in out["reason"] and "on-demand" in out["reason"]


def test_run_or_fallback_refuses_duplicate_record_ids():
    recs = _records(2) + _records(1)
    with pytest.raises(ValueError):
        bb.run_or_fallback(recs, "claude-sonnet-4-6", lambda mi: None)


def test_dev_session_cap_refuses_a_job_before_anything_is_submitted(monkeypatch):
    from ai import dev_session_cap

    real_projected_check = bb._dev_cap_projected
    _tier(monkeypatch)
    fake = _FakeBatch(monkeypatch)
    monkeypatch.setattr(bb, "_dev_cap_projected", real_projected_check)  # keep the S3/Bedrock fakes, use the real cap seam

    def _refuse(caller_class, projected_usd, cloudwatch_factory):
        raise dev_session_cap.DevSessionBudgetExceeded(f"projected {projected_usd}")

    monkeypatch.setattr(dev_session_cap, "check_projected", _refuse)
    with pytest.raises(dev_session_cap.DevSessionBudgetExceeded):
        bb.run_or_fallback(_records(100), "claude-sonnet-4-6", lambda mi: "RT", role_arn="arn:role", log=lambda m: None)
    assert fake.submitted == []


def test_dev_cap_check_projected_refuses_a_job_that_would_cross_the_cap(monkeypatch):
    from ai import dev_session_cap as cap

    monkeypatch.setenv("DEV_AI_CAP_UNDER_TEST", "1")
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv(cap.OVERRIDE_ENV, raising=False)
    cap._reset_for_tests()
    cw = MagicMock()
    cw.get_metric_statistics.return_value = {"Datapoints": []}
    try:
        cap.check_projected("dev-session", 1.0, lambda: cw)  # well under $5
        with pytest.raises(cap.DevSessionBudgetExceeded):
            cap.check_projected("dev-session", cap.PER_RUN_USD + 0.01, lambda: cw)
        cap.check_projected("scheduled", 1000.0, lambda: cw)  # never applies outside a dev session
    finally:
        cap._reset_for_tests()


def test_projected_cost_is_an_upper_bound_at_the_batch_price():
    recs = [bb.build_jsonl_record("A", {"messages": [{"role": "user", "content": "x" * 3000}], "max_tokens": 1000}, "claude-sonnet-4-6")]
    projected = bb.projected_batch_usd(recs, "claude-sonnet-4-6")
    # The same record actually billed at ~750 input tokens (chars/4) and its full max_tokens, batch-priced.
    actual = bb.estimate_batch_savings([{"input_tokens": 750, "output_tokens": 1000}], "claude-sonnet-4-6")["batch_usd"]
    assert projected >= actual > 0


# ── the staging prefix is private ───────────────────────────────────────────
def test_public_prefixes_match_the_bucket_policy():
    """PUBLIC_PREFIXES must be exactly the prefixes deploy/bucket_policy.json grants anonymous GetObject on."""
    with open(os.path.join(ROOT, "deploy", "bucket_policy.json"), encoding="utf-8") as fh:
        policy = json.load(fh)
    public = set()
    for st in policy["Statement"]:
        if st.get("Effect") == "Allow" and st.get("Principal") in ("*", {"AWS": "*"}):
            for res in st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]:
                public.add(res.split(":::", 1)[1].split("/", 1)[1].rstrip("*"))
    assert public == set(bb.PUBLIC_PREFIXES)
    assert not any(bb.BATCH_PREFIX.startswith(p) for p in public)


def test_staging_refuses_a_public_prefix():
    for bad in ("generated/batch/input.jsonl", "site/x.jsonl", "blog/x", "raw/x.jsonl"):
        with pytest.raises(ValueError):
            bb.assert_private_prefix(bad)
    bb.assert_private_prefix("bedrock-batch/job/input.jsonl")
    with pytest.raises(ValueError):
        bb.submit_batch(_records(100), "claude-sonnet-4-6", "s3://b/generated/in.jsonl", "s3://b/bedrock-batch/o/", "arn:role")


def test_job_uris_stay_under_the_private_prefix():
    i, o = bb.job_uris("season rebuild/../generated", bucket="b")
    assert i.startswith("s3://b/bedrock-batch/") and o.startswith("s3://b/bedrock-batch/")
    assert ".." not in i and "/generated" not in i.split("bedrock-batch/", 1)[1].replace("-generated", "")


def test_cdk_role_and_prefix_match_the_module():
    """The CoreStack service role is named and scoped to what bedrock_batch stages to."""
    src = open(os.path.join(ROOT, "cdk", "stacks", "core_stack.py"), encoding="utf-8").read()
    assert f'role_name="{bb.BATCH_ROLE_NAME}"' in src
    assert f'_batch_prefix = "{bb.BATCH_PREFIX}"' in src


def test_parse_output_jsonl_splits_results_and_errors():
    text = "\n".join(
        [
            _line("A"),
            json.dumps({"recordId": "B", "modelInput": {}, "error": {"errorCode": 500}}),
            json.dumps({"recordId": "C", "modelInput": {}}),
            "",
        ]
    )
    outputs, errors = bb.parse_output_jsonl(text)
    assert set(outputs) == {"A"} and set(errors) == {"B", "C"}


def test_batch_metering_uses_the_batch_price(monkeypatch):
    from ai import bedrock_client as bc

    calls = []
    monkeypatch.setattr(bc, "_emit_usage_metrics", lambda usage, model_id, cost_scale=1.0: calls.append(cost_scale))
    bb._meter_batch_record({"input_tokens": 10, "output_tokens": 5}, "us.anthropic.claude-sonnet-4-6")
    assert calls == [1.0 - bb.BATCH_DISCOUNT]


# ── submit refuses under-floor even if called directly ──────────────────────
def test_submit_batch_refuses_below_floor():
    with pytest.raises(ValueError):
        bb.submit_batch([{"recordId": "1"}], "claude-sonnet-4-6", "s3://b/in.jsonl", "s3://b/out/", "arn:role")


# ── poll maps Bedrock job states ────────────────────────────────────────────
def test_poll_batch_maps_states(monkeypatch):
    fake = MagicMock()
    fake.get_model_invocation_job.return_value = {"status": "Completed"}
    monkeypatch.setattr(bb, "_ctrl", lambda: fake)
    snap = bb.poll_batch("arn:job")
    assert snap["done"] is True and snap["succeeded"] is True

    fake.get_model_invocation_job.return_value = {"status": "InProgress"}
    snap = bb.poll_batch("arn:job")
    assert snap["done"] is False and snap["succeeded"] is False

    fake.get_model_invocation_job.return_value = {"status": "Failed", "message": "boom"}
    snap = bb.poll_batch("arn:job")
    assert snap["done"] is True and snap["succeeded"] is False and snap["message"] == "boom"


def test_wait_for_batch_returns_on_deadline(monkeypatch):
    # Never completes; deadline already passed → done=False without sleeping.
    monkeypatch.setattr(bb, "poll_batch", lambda arn: {"status": "InProgress", "done": False, "succeeded": False, "message": ""})
    out = bb.wait_for_batch("arn:job", deadline_epoch=0.0)
    assert out["done"] is False
    assert "deadline" in out["message"]
