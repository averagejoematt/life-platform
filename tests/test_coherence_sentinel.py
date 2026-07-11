"""
tests/test_coherence_sentinel.py — the Sentinel Lambda's orchestration.

The pure invariants are covered by test_coherence_invariants. Here we drive the
handler end-to-end with the data-adapters monkeypatched to a known-bad live
state (the C-3 all-inconclusive board + a 30-vs-86 narrative split) and assert
run_checks() surfaces the alarms and the digest renders — no AWS, no HTTP.
"""

import datetime as _dt
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


def _pin_continuity(monkeypatch, genesis="2026-06-08", today="2026-07-01", surfaced=()):
    """Pin the SS-05 continuity gather to explicit fixture dates. The real gather
    reads the LIVE constants.EXPERIMENT_START_DATE and the wall clock (plus a real
    DDB get_item) — which made every run_checks() test silently dependent on
    "genesis <= today": a reset staging a FUTURE genesis (the sanctioned #931
    pre-start window) flipped check_experiment_continuity to ALARM and broke the
    OK-expecting tests. Pinned mid-experiment dates keep each test about ITS
    invariant; the future-genesis semantics of the pure check are pinned in
    test_coherence_invariants.py::test_genesis_in_future_alarms."""
    monkeypatch.setattr(sentinel, "_gather_experiment_continuity", lambda: (genesis, today, list(surfaced)))


def _patch_bad_state(monkeypatch):
    _pin_continuity(monkeypatch)
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


def test_semantic_incoherence_is_advisory_not_alarm_driving():
    # The Haiku semantic read is too noisy to drive a daily-emailing alarm (it lists
    # confirmations as "issues"). So a semantic-only flag with all deterministic
    # invariants green stays status=ok (the alarm won't fire), but semantic_incoherent
    # is recorded as advisory context for a human/agent to weigh.
    ok = [sentinel.ci.Finding("prediction_health", sentinel.ci.OK, 0.0, "fine")]
    semantic = {"coherent": False, "issues": ["borderline HRV variance"]}
    record = sentinel.build_record(ok, semantic, "digest", sentinel.ci.OK)
    assert record["status"] == sentinel.ci.OK  # deterministic drives the alarm
    assert record["deterministic_status"] == sentinel.ci.OK
    assert record["semantic_incoherent"] is True  # but the advisory flag is preserved


def test_deterministic_alarm_still_drives_status():
    bad = [sentinel.ci.Finding("facts_agreement", sentinel.ci.ALARM, 2.0, "two contradictions")]
    record = sentinel.build_record(bad, {"coherent": True, "issues": []}, "d", sentinel.ci.ALARM)
    assert record["status"] == sentinel.ci.ALARM


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


def _patch_empty_post_reset_board(monkeypatch, age_days):
    """A freshly-reset cycle (ADR-077): every cycle-scoped surface is legitimately
    empty. All the endpoint specs' required keys are present-but-empty containers
    (never None), so only the non_degenerate gate is in play."""
    monkeypatch.setattr(sentinel, "_gather_predictions", lambda: [])
    monkeypatch.setattr(sentinel, "_gather_facts_and_narratives", lambda: ({}, [], []))
    monkeypatch.setattr(sentinel, "_gather_computed_checks", lambda: [])
    monkeypatch.setattr(sentinel, "_gather_counts", lambda: [])
    monkeypatch.setattr(sentinel, "_semantic_pass", lambda facts, narr: None)
    monkeypatch.setattr(sentinel, "_experiment_age_days", lambda: age_days)
    # freshly-reset cycle: genesis just passed, nothing surfaced to readers yet;
    # today derives from the pinned genesis + the test's age, never the wall clock
    _today = (_dt.date.fromisoformat("2026-06-08") + _dt.timedelta(days=age_days)).isoformat()
    _pin_continuity(monkeypatch, genesis="2026-06-08", today=_today, surfaced=())
    empty_payload = {
        "overall": {"total": 0},
        "predictions": [],
        "nutrition": {},
        "coaches": [],
        "vitals": {},
    }
    monkeypatch.setattr(sentinel, "_get_json", lambda path: empty_payload)


def test_post_reset_empty_board_reports_ok(monkeypatch):
    # BUG-05 / #379 — replay: a reset just happened (age=1 day), every public
    # endpoint is a legitimately empty shell. The sentinel must NOT alarm.
    _patch_empty_post_reset_board(monkeypatch, age_days=1)
    findings, _ = sentinel.run_checks()
    shape_findings = [f for f in findings if f.name.startswith("endpoint_shape:")]
    assert shape_findings, "expected the default endpoint specs to run"
    assert all(f.status == sentinel.ci.OK for f in shape_findings)
    assert sentinel.ci.overall_status(findings) == sentinel.ci.OK


def test_same_empty_board_alarms_once_past_the_grace_window(monkeypatch):
    # Identical degenerate payloads, but well past the reset (age=30 days) — this
    # is the genuine handle_predictions signature and must still alarm exactly
    # as before the gate was added.
    _patch_empty_post_reset_board(monkeypatch, age_days=30)
    findings, _ = sentinel.run_checks()
    shape_findings = [f for f in findings if f.name.startswith("endpoint_shape:")]
    assert any(f.is_alarm for f in shape_findings)
    assert sentinel.ci.overall_status(findings) == sentinel.ci.ALARM


def test_healthy_state_is_ok(monkeypatch):
    _pin_continuity(monkeypatch, surfaced=[{"name": "experiment_arc_week_count", "week": 4}])
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
