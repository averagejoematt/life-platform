"""
tests/test_coherence_sentinel.py — the Sentinel Lambda's orchestration.

The pure invariants are covered by test_coherence_invariants. Here we drive the
handler end-to-end with the data-adapters monkeypatched to a known-bad live
state (the C-3 all-inconclusive board + a 30-vs-86 narrative split) and assert
run_checks() surfaces the alarms and the digest renders — no AWS, no HTTP.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational"))

import coherence_sentinel_lambda as sentinel  # noqa: E402


def _patch_bad_state(monkeypatch):
    # C-3 signature: many closed predictions, none decided.
    monkeypatch.setattr(
        sentinel,
        "_gather_predictions",
        lambda: [{"status": "inconclusive", "closed": True, "eval_type": "machine"} for _ in range(12)],
    )
    # 30-vs-86 recovery split across served narratives.
    monkeypatch.setattr(
        sentinel,
        "_gather_facts_and_narratives",
        lambda: (
            {"recovery_pct": 30, "hrv_ms": 25.2, "rhr_bpm": 58, "latest_weight": 300.8},
            ["Recovery sat at 30% today.", "With recovery up at 86 you're primed to push."],
            ["expert:training", "expert:nutrition"],
        ),
    )
    monkeypatch.setattr(sentinel, "_gather_computed_checks", lambda: [])
    monkeypatch.setattr(sentinel, "_gather_endpoint_specs", lambda: [])  # skip HTTP
    monkeypatch.setattr(sentinel, "_gather_counts", lambda: [])
    monkeypatch.setattr(sentinel, "_semantic_pass", lambda facts, narr: None)


def test_run_checks_surfaces_known_bugs(monkeypatch):
    _patch_bad_state(monkeypatch)
    findings, semantic = sentinel.run_checks()
    by_name = {f.name: f for f in findings}
    assert by_name["prediction_health"].is_alarm
    assert by_name["facts_agreement"].status in (sentinel.ci.WARN, sentinel.ci.ALARM)
    assert sentinel.ci.overall_status(findings) == sentinel.ci.ALARM


def test_digest_renders(monkeypatch):
    _patch_bad_state(monkeypatch)
    findings, semantic = sentinel.run_checks()
    digest = sentinel._digest(findings, semantic)
    assert "COHERENCE SENTINEL — ALARM" in digest
    assert "prediction_health" in digest


def test_healthy_state_is_ok(monkeypatch):
    monkeypatch.setattr(
        sentinel,
        "_gather_predictions",
        lambda: [{"status": "confirmed", "closed": True, "eval_type": "directional"} for _ in range(6)]
        + [{"status": "pending", "closed": False, "eval_type": "directional"} for _ in range(10)],
    )
    monkeypatch.setattr(
        sentinel,
        "_gather_facts_and_narratives",
        lambda: ({"recovery_pct": 30, "hrv_ms": 25.2}, ["Recovery was 30% today; HRV 25 ms."], ["expert:sleep"]),
    )
    monkeypatch.setattr(sentinel, "_gather_computed_checks", lambda: [])
    monkeypatch.setattr(sentinel, "_gather_endpoint_specs", lambda: [])
    monkeypatch.setattr(sentinel, "_gather_counts", lambda: [])
    monkeypatch.setattr(sentinel, "_semantic_pass", lambda facts, narr: None)
    findings, _ = sentinel.run_checks()
    assert sentinel.ci.overall_status(findings) == sentinel.ci.OK
