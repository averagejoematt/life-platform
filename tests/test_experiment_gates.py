"""tests/test_experiment_gates.py — #1371 cold start as an armed instrument.

Guards the three server-side legs of #1371:

1. The arming thresholds the engines ENFORCE are the registry's objects
   (lambdas/experiment_gates.py) — a re-hardcoded literal in an engine would
   let the site's rendered trigger silently drift from the real gate.
2. The shaped-empty /api/correlations and /api/hypotheses payloads carry the
   registry's gates + a measured current_n, so zero-states render a computed
   trigger ("first correlations at n≥10 — currently 3/10"), never authored copy.
3. /api/source_freshness stamps cross-cycle provenance (carried +
   carried_from_cycle, derived as a PURE function of the record's date against
   the CYCLE_GENESES ledger — #2002; the original #1371 read of an ADR-077
   `cycle` attribute was structurally dead because no reset-pipeline writer
   ever stamps raw partitions) and the experiment anchor, so a Day-1 board
   labels a 110-day-old chip "carried from attempt 7" instead of rendering an
   unexplained ghost.
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

from experiment import experiment_gates  # noqa: E402
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


# #2002: a pinned ledger — the derivation is pure date-vs-genesis, so the test
# must not drift as restart_pipeline appends real cycles to CYCLE_GENESES.
_TEST_GENESES = {1: "2026-04-01", 7: "2026-07-18", 8: "2026-07-19"}


def _freshness_with(monkeypatch, latest_sk_date, record_extra=None, latest_sk=None):
    from web import site_api_data as sad

    pk = "USER#matthew#SOURCE#testsrc"
    sk = latest_sk or f"DATE#{latest_sk_date}"
    record = {"pk": pk, "sk": sk, **(record_extra or {})}

    def query_hook(table, **kwargs):
        return {"Items": [{"sk": sk}]}

    fake = FakeDdbTable(rows=[record], query_hook=query_hook)
    monkeypatch.setattr(sad, "table", fake)
    monkeypatch.setattr(sad, "_FRESHNESS_SOURCES", {"testsrc": {"label": "Test Source", "desc": "d", "category": "Body"}})
    monkeypatch.setattr(sad, "_FRESHNESS_PAUSED", {})
    monkeypatch.setattr(sad, "CYCLE_GENESES", dict(_TEST_GENESES))
    monkeypatch.setattr(sad, "EXPERIMENT_START", "2026-07-19")  # cycle 8 genesis
    from coach import coach_checkin

    monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 8)
    return sad


def test_pre_genesis_source_carries_cycle_provenance(monkeypatch):
    # Newest record's CONTENT date (never tombstoned_at) predates genesis → the
    # chip is labeled carried history, numbered by DATE against CYCLE_GENESES
    # (#2002): 2026-07-18 falls in cycle 7's [genesis, next-genesis) span. The
    # stored record deliberately has the REAL raw shape — phase tag only, NO
    # `cycle` attribute (no reset-pipeline writer ever stamps one).
    sad = _freshness_with(monkeypatch, "2026-07-18", record_extra={"phase": "pilot"})
    body = _body(sad.handle_source_freshness())
    (entry,) = body["sources"]
    assert entry["carried"] is True
    assert entry["carried_from_cycle"] == 7
    assert body["experiment"]["genesis"] == "2026-07-19"
    assert body["experiment"]["cycle"] == 8


def test_hevy_subrecord_shape_still_gets_numeric_cycle(monkeypatch):
    # #2002: hevy has NO plain DATE#{date} item — only DATE#…#WORKOUT#<uuid>
    # sub-records — which made the old get_item stamp-read structurally
    # unreachable. The date derivation numbers it from the sk's date alone.
    sad = _freshness_with(
        monkeypatch,
        "2026-07-18",
        record_extra={"phase": "pilot"},
        latest_sk="DATE#2026-07-18#WORKOUT#0a1b2c3d-4e5f",
    )
    body = _body(sad.handle_source_freshness())
    (entry,) = body["sources"]
    assert entry["carried"] is True
    assert entry["carried_from_cycle"] == 7


def test_pre_cycle_one_record_stays_unnumbered(monkeypatch):
    # A record predating cycle 1's genesis has no attempt to name — the honest
    # unnumbered "a previous attempt" fallback (ADR-104), never a fabricated 1.
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
    from ai.ai_context import format_experiment_phase_context

    block = format_experiment_phase_context(_pctx(days_in=1))
    assert "RESET-MANUFACTURED GAPS ARE NOT LAPSES" in block
    assert "never scold" in block.lower()


def test_post_early_phase_block_omits_reset_clause():
    from ai.ai_context import format_experiment_phase_context

    block = format_experiment_phase_context(_pctx(days_in=20))
    assert "RESET-MANUFACTURED" not in block
