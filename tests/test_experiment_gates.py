"""tests/test_experiment_gates.py — #1371 cold start as an armed instrument.

Guards the three server-side legs of #1371:

1. The arming thresholds the engines ENFORCE are the registry's objects
   (lambdas/experiment_gates.py) — a re-hardcoded literal in an engine would
   let the site's rendered trigger silently drift from the real gate.
2. The shaped-empty /api/correlations and /api/hypotheses payloads carry the
   registry's gates + a measured current_n, so zero-states render a computed
   trigger ("first correlations at n≥10 — currently 3/10"), never authored copy.
3. /api/source_freshness stamps cross-cycle provenance (carried +
   carried_from_cycle from the record's ADR-077 cycle stamp) and the experiment
   anchor, so a Day-1 board labels a 110-day-old chip "carried from attempt 7"
   instead of rendering an unexplained ghost.
4. The mandatory AI phase block carries the reset-aware no-scold clause in the
   early-phase window — day-1 coach output must never frame reset-manufactured
   gaps ("zero food logs") as the person's failure.

All four are red on the pre-#1371 tree: no registry module, no gates key, no
carried stamp, no reset clause.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import experiment_gates  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402


def _body(resp):
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


# ── 1. Engines enforce the registry's objects, not private literals ───────────


def test_correlation_engine_uses_registry():
    from compute import weekly_correlation_compute_lambda as wc

    # Identity, not equality: an engine-local copy would pass == while drifting later.
    assert wc._INTERP_N_REQUIRED is experiment_gates.CORRELATION_INTERP_N
    # interpret_r must actually gate on the registry values.
    assert wc.interpret_r(0.7, n=experiment_gates.CORRELATION_INTERP_N["strong"]) == "strong"
    assert wc.interpret_r(0.7, n=experiment_gates.CORRELATION_INTERP_N["strong"] - 1) == "moderate"


def test_hypothesis_engine_uses_registry():
    from compute import hypothesis_engine_lambda as he

    assert he.MIN_DATA_DAYS == experiment_gates.HYPOTHESIS_MIN_DATA_DAYS
    assert he.MIN_METRICS_PER_DAY == experiment_gates.HYPOTHESIS_MIN_METRICS_PER_DAY
    assert he.MIN_SAMPLE_DAYS_FOR_CHECK == experiment_gates.HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK
    assert he.MIN_DAYS_PER_ARM == experiment_gates.HYPOTHESIS_MIN_DAYS_PER_ARM


def test_coupling_floor_uses_registry():
    from web import site_api_intelligence as intel

    assert intel._COUPLING_MIN_N == experiment_gates.COUPLING_MIN_N


def test_registry_values_are_sane():
    # The gates are load-bearing statistics floors (ADR-105) — a zeroed or negated
    # registry must red, not silently disarm every engine.
    assert experiment_gates.CORRELATION_MIN_N >= 5
    assert (
        experiment_gates.CORRELATION_INTERP_N["weak"]
        <= experiment_gates.CORRELATION_INTERP_N["moderate"]
        <= experiment_gates.CORRELATION_INTERP_N["strong"]
    )
    assert experiment_gates.HYPOTHESIS_MIN_DATA_DAYS >= 5


# ── 2. Shaped-empty payloads carry gates + measured progress ──────────────────


def _intel_with_fake_table(monkeypatch, computed_days):
    from web import site_api_intelligence as intel

    def query_hook(table, **kwargs):
        if kwargs.get("Select") == "COUNT":
            return {"Count": computed_days, "Items": []}
        return {"Items": []}  # no weekly_correlations / hypotheses records — cold start

    monkeypatch.setattr(intel, "table", FakeDdbTable(query_hook=query_hook))
    return intel


def test_correlations_cold_start_serves_engine_gates(monkeypatch):
    intel = _intel_with_fake_table(monkeypatch, computed_days=3)
    body = _body(intel.handle_correlations())
    assert body["count"] == 0
    gates = body["gates"]
    assert gates["min_n"] == experiment_gates.CORRELATION_MIN_N
    assert gates["interp_n"] == experiment_gates.CORRELATION_INTERP_N
    assert gates["current_n"] == 3


def test_hypotheses_cold_start_serves_engine_gates(monkeypatch):
    intel = _intel_with_fake_table(monkeypatch, computed_days=2)
    body = _body(intel.handle_hypotheses())
    assert body["count"] == 0
    gates = body["gates"]
    assert gates["min_data_days"] == experiment_gates.HYPOTHESIS_MIN_DATA_DAYS
    assert gates["current_n"] == 2


def test_correlations_count_failure_serves_null_not_zero(monkeypatch):
    # ADR-104: an unmeasurable progress count renders null (front-end shows "—"),
    # never a fabricated 0.
    from web import site_api_intelligence as intel

    def query_hook(table, **kwargs):
        if kwargs.get("Select") == "COUNT":
            raise RuntimeError("count unavailable")
        return {"Items": []}

    monkeypatch.setattr(intel, "table", FakeDdbTable(query_hook=query_hook))
    body = _body(intel.handle_correlations())
    assert body["gates"]["current_n"] is None


# ── 3. Freshness board: cross-cycle provenance ────────────────────────────────


def _freshness_with(monkeypatch, latest_date, record_extra=None):
    from web import site_api_data as sad

    pk = "USER#matthew#SOURCE#testsrc"
    record = {"pk": pk, "sk": f"DATE#{latest_date}", **(record_extra or {})}

    def query_hook(table, **kwargs):
        return {"Items": [{"sk": f"DATE#{latest_date}"}]}

    fake = FakeDdbTable(rows=[record], query_hook=query_hook)
    monkeypatch.setattr(sad, "table", fake)
    monkeypatch.setattr(sad, "_FRESHNESS_SOURCES", {"testsrc": {"label": "Test Source", "desc": "d", "category": "Body"}})
    monkeypatch.setattr(sad, "_FRESHNESS_PAUSED", {})
    import coach_checkin

    monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 8)
    return sad


def test_pre_genesis_source_carries_cycle_provenance(monkeypatch):
    # Newest record's CONTENT date (never tombstoned_at) predates genesis → the
    # chip is labeled carried history, numbered from the ADR-077 cycle stamp.
    sad = _freshness_with(monkeypatch, "2020-01-01", record_extra={"cycle": 7})
    body = _body(sad.handle_source_freshness())
    (entry,) = body["sources"]
    assert entry["carried"] is True
    assert entry["carried_from_cycle"] == 7
    assert body["experiment"]["genesis"] == sad.EXPERIMENT_START
    assert body["experiment"]["cycle"] == 8


def test_pre_genesis_source_without_stamp_still_marks_carried(monkeypatch):
    sad = _freshness_with(monkeypatch, "2020-01-01")
    body = _body(sad.handle_source_freshness())
    (entry,) = body["sources"]
    assert entry["carried"] is True
    assert entry["carried_from_cycle"] is None


def test_current_cycle_source_is_not_marked_carried(monkeypatch):
    from datetime import datetime, timedelta, timezone

    sad = _freshness_with(monkeypatch, (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d"))
    body = _body(sad.handle_source_freshness())
    (entry,) = body["sources"]
    assert "carried" not in entry


# ── 4. The mandatory phase block never scolds reset-manufactured gaps ─────────


def _pctx(days_in):
    return {
        "pre_start": False,
        "days_until_start": 0,
        "start_date": "2026-07-19",
        "as_of": "2026-07-19",
        "days_in": days_in,
        "week_num": 1,
        "stage": "Foundation",
        "stage_label": "x",
        "start_weight": 200,
        "goal_weight": 185,
        "coaching_principles": [],
        "early_phase": days_in <= 14,
        "audience": "AUDIENCE: test",
    }


def test_early_phase_block_carries_reset_no_scold_clause():
    from ai_context import format_experiment_phase_context

    block = format_experiment_phase_context(_pctx(days_in=1))
    assert "RESET-MANUFACTURED GAPS ARE NOT LAPSES" in block
    assert "never scold" in block.lower()


def test_post_early_phase_block_omits_reset_clause():
    from ai_context import format_experiment_phase_context

    block = format_experiment_phase_context(_pctx(days_in=20))
    assert "RESET-MANUFACTURED" not in block
