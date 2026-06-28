"""
tests/test_coherence_sentinel.py — the Sentinel Lambda's orchestration.

The pure invariants are covered by test_coherence_invariants. Here we drive the
handler end-to-end with the data-adapters monkeypatched to a known-bad live
state (the C-3 all-inconclusive board + a 30-vs-86 narrative split) and assert
run_checks() surfaces the alarms and the digest renders — no AWS, no HTTP.
"""

import json
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


def test_facts_use_canonical_schema_closing_the_grounding_loop(monkeypatch):
    # The Sentinel grounds on the SAME canonical_facts the coaches do — so the
    # protein avg/target/floor are distinct (the 140/170/190 confusion) and HRV
    # is ms. Patch _latest to a known computed_metrics record; the narratives loop
    # fail-softs to empty (table is a stub here).
    monkeypatch.setattr(
        sentinel,
        "_latest",
        lambda src: {"recovery_pct": 30, "hrv_ms": 25.18, "protein_g_avg": 140.7, "protein_g_target": 190, "protein_g_floor": 170},
    )
    monkeypatch.setattr(sentinel, "table", None)  # narratives query → except → []
    facts, narratives, labels = sentinel._gather_facts_and_narratives()
    assert facts["protein_g_avg"] == 140.7
    assert facts["protein_g_target"] == 190 and facts["protein_g_floor"] == 170
    assert facts["hrv_ms"] == 25.2 and "as_of" not in facts  # ms, no stray non-numeric key


def test_build_record_is_serializable_and_complete(monkeypatch):
    _patch_bad_state(monkeypatch)
    findings, semantic = sentinel.run_checks()
    digest = sentinel._digest(findings, semantic)
    worst = sentinel.ci.overall_status(findings)
    record = sentinel.build_record(findings, semantic, digest, worst)
    # The agent reads these keys to triage; they must all be present + JSON-safe.
    assert set(record) >= {"date", "status", "alarms", "findings", "digest"}
    assert "prediction_health" in record["alarms"]
    assert json.loads(json.dumps(record, default=str))  # round-trips


def test_build_record_status_mirrors_alarm_on_semantic_only_incoherence():
    # Deterministic all-green, but the Haiku pass flagged a contradiction. The
    # coherence-overall alarm fires on this (semantic_bad), so the persisted status
    # MUST read alarm — else the agent's status filter drops it and the alarm fires
    # with no detail. deterministic_status preserves the invariant-only verdict.
    ok = [sentinel.ci.Finding("prediction_health", sentinel.ci.OK, 0.0, "fine")]
    semantic = {"coherent": False, "issues": ["a coach invented a weight-loss number"]}
    record = sentinel.build_record(ok, semantic, "digest", sentinel.ci.OK)
    assert record["status"] == sentinel.ci.ALARM
    assert record["deterministic_status"] == sentinel.ci.OK
    assert record["semantic_incoherent"] is True

    # And the clean case stays ok.
    clean = sentinel.build_record(ok, {"coherent": True, "issues": []}, "d", sentinel.ci.OK)
    assert clean["status"] == sentinel.ci.OK and clean["semantic_incoherent"] is False


def test_persist_writes_latest_and_dated_and_is_fail_soft(monkeypatch):
    puts = []
    monkeypatch.setattr(sentinel._s3, "put_object", lambda **kw: puts.append(kw["Key"]))
    record = {"date": "2026-06-28", "status": "alarm", "alarms": ["prediction_health"], "findings": [], "digest": "x"}
    sentinel._persist(record)
    assert "coherence-log/latest.json" in puts
    assert "coherence-log/2026-06-28.json" in puts

    # A persist failure must NOT propagate — detection already emitted metrics.
    def _boom(**kw):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(sentinel._s3, "put_object", _boom)
    sentinel._persist(record)  # no raise


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
