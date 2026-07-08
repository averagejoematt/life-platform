"""
tests/test_bedrock_batch.py — the batch-inference seam (#409, ADR-132).

The module is a latent capability (no producer calls it at current volume), so
these tests pin the *decision logic* that is load-bearing today — the 100-record
eligibility floor, the real-time fallback, the record formatting that keeps batch
byte-identical to invoke(), and the 50%-savings math — plus mock-level coverage of
the submit/poll wrappers so the enablement path is not untested.

Run:  python3 -m pytest tests/test_bedrock_batch.py -v
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import bedrock_batch as bb  # noqa: E402


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
    monkeypatch.setitem(sys.modules, "budget_guard", stub)
    ok, reason = bb.batch_preflight(500, "claude-sonnet-4-6")
    assert ok is False
    assert "tier 3" in reason


def test_tier0_allows_above_floor(monkeypatch):
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: 0
    monkeypatch.setitem(sys.modules, "budget_guard", stub)
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


def test_run_or_fallback_above_floor_not_yet_enabled(monkeypatch):
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: 0
    monkeypatch.setitem(sys.modules, "budget_guard", stub)
    records = [bb.build_jsonl_record(f"R{i}", {"messages": [], "max_tokens": 5}, "claude-sonnet-4-6") for i in range(150)]
    with pytest.raises(NotImplementedError):
        bb.run_or_fallback(records, "claude-sonnet-4-6", lambda mi: None)


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
