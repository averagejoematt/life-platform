"""#3046 (DIL-007) — prediction gradeability: no prediction ungradeable-by-construction.

Closed #715's acceptance included "zero predictions ungradeable-by-construction".
The 2026-08-23 diligence audit found 28 of 50 pending predictions carrying
`eval_type: "qualitative"` — records coach_prediction_evaluator structurally
skips, so they could only pend forever. These tests re-assert #715 criterion 3
as a standing regression gate on the EMISSION path (the real record builder the
writer Lambda calls — coach.prediction_emission), plus the two mop-up mechanisms:
the evaluator's window-end retirement of the legacy rows, and the GradableShare
metric the prediction-gradable-share-low alarm watches.

Offline: DynamoDB/CloudWatch are stubbed; no AWS is touched.
"""

import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_prediction_evaluator as ev  # noqa: E402
from coach import (
    prediction_emission as pe,  # noqa: E402
    prediction_windows as pw,  # noqa: E402
)

# ── The emission contract (#715 criterion 3, re-asserted) ─────────────────────


class TestEmissionContract:
    def test_a_directional_claim_is_emitted_pending_and_deterministic(self):
        spec = pe.build_prediction_eval_spec("hrv", "up", 14)
        rec = pe.build_prediction_record("sleep_coach", "2026-08-23", "HRV will rise", spec, 0.7, "observational")
        assert rec["status"] == "pending"
        assert rec["gradeable_by"] == pe.GRADEABLE_BY_DETERMINISTIC

    def test_a_qualitative_claim_is_emitted_as_observation_never_pending(self):
        """THE regression: a claim with no grading path must never be written with
        status 'pending' — pending promises the evaluator will grade it."""
        spec = pe.build_prediction_eval_spec("", None, 14)
        assert spec["type"] == "qualitative"
        rec = pe.build_prediction_record("mind_coach", "2026-08-23", "You will feel more grounded", spec, 0.5, "observational")
        assert rec["status"] == pe.OBSERVATION_STATUS
        assert rec["gradeable_by"] == pe.GRADEABLE_BY_NONE
        assert rec["status"] not in ev.EVALUABLE_STATUSES

    def test_no_emittable_spec_shape_can_produce_an_ungradeable_pending_record(self):
        """Exhaustive over the spec builder's whole input space class: every spec
        the writer can construct either has a deterministic grading path or is
        emitted outside the pending-grading corpus. Zero ungradeable-by-construction."""
        for metric in ("hrv", "", None):
            for direction in ("up", "down", None, "sideways"):
                spec = pe.build_prediction_eval_spec(metric, direction, 14)
                status, gradeable_by = pe.emission_status(spec)
                if status in ev.EVALUABLE_STATUSES:
                    assert pw.is_gradeable(spec), f"pending-but-ungradeable emitted for metric={metric!r} direction={direction!r}"
                    assert gradeable_by == pe.GRADEABLE_BY_DETERMINISTIC
                else:
                    assert status == pe.OBSERVATION_STATUS
                    assert gradeable_by == pe.GRADEABLE_BY_NONE

    def test_the_writer_lambda_uses_the_contracted_builder(self):
        """The extract-the-right-real-source guard: coach_state_updater's emission
        loop must build records through prediction_emission.build_prediction_record
        (where the contract lives), not an inline dict that could regress."""
        import coach_state_updater as su

        assert su._build_prediction_record is pe.build_prediction_record
        assert su._build_prediction_eval_spec is pe.build_prediction_eval_spec
        import ast  # noqa: E401
        import inspect

        src = inspect.getsource(su)
        tree = ast.parse(src)
        calls = {getattr(n.func, "id", getattr(n.func, "attr", "")) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        assert "_build_prediction_record" in calls, "the emission loop no longer routes through the contract builder"


# ── The window/due-date policy shared with the public surface ─────────────────


class TestSharedWindowPolicy:
    def test_evaluator_delegates_to_the_shared_clamp(self):
        assert ev._get_effective_window({"evaluation_window_days": 5}, "sleep") == pw.effective_window_days(
            {"evaluation_window_days": 5}, "sleep"
        )
        assert ev.DOMAIN_MIN_WINDOWS is pw.DOMAIN_MIN_WINDOWS
        assert ev.SUBDOMAIN_TO_DOMAIN is pw.SUBDOMAIN_TO_DOMAIN

    def test_due_date_is_created_plus_the_clamped_window(self):
        # sleep floor is 7d: a 1-day stated window still grades 7 days out.
        assert pw.due_date("2026-08-17", {"evaluation_window_days": 1}, "sleep") == "2026-08-24"
        # stated window above the floor is respected.
        assert pw.due_date("2026-08-17", {"evaluation_window_days": 30}, "sleep") == "2026-09-16"

    def test_due_date_degrades_to_none_on_garbage(self):
        assert pw.due_date(None, {}, "sleep") is None
        assert pw.due_date("not-a-date", {}, "sleep") is None

    def test_gradeability_predicate_matches_the_evaluator_skip(self):
        assert pw.is_gradeable({"type": "directional"})
        assert pw.is_gradeable({"type": "machine"})
        assert pw.is_gradeable({})  # legacy blank type grades as machine
        assert not pw.is_gradeable({"type": "qualitative"})


# ── Legacy mop-up: window-end retirement of pending-qualitative rows ──────────


class _TableCapture:
    def __init__(self):
        self.updates = []

    def update_item(self, **kwargs):
        self.updates.append(kwargs)


def _qual_pred(created_date, window_days=7, subdomain="sleep", pred_id="q1"):
    return {
        "pk": "COACH#sleep_coach",
        "sk": f"PREDICTION#{pred_id}",
        "prediction_id": pred_id,
        "coach_id": "sleep_coach",
        "created_date": created_date,
        "subdomain": subdomain,
        "status": "pending",
        "evaluation": {"type": "qualitative", "metric": None, "evaluation_window_days": window_days},
    }


class TestUngradeableRetirement:
    def test_a_past_window_qualitative_row_expires(self, monkeypatch):
        table = _TableCapture()
        monkeypatch.setattr(ev, "table", table)
        retired = ev._retire_ungradeable([_qual_pred("2026-08-10", window_days=7)], "2026-08-23")
        assert retired == 1
        assert len(table.updates) == 1
        vals = table.updates[0]["ExpressionAttributeValues"]
        assert vals[":status"] == "expired"
        assert vals[":odate"] == "2026-08-23"
        assert "ungradeable-by-construction" in vals[":notes"]

    def test_an_open_window_qualitative_row_is_left_alone(self, monkeypatch):
        """No 2x grace shortcut in reverse either: inside the window the claim is
        still a labeled observational entry on the surface, not retired early."""
        table = _TableCapture()
        monkeypatch.setattr(ev, "table", table)
        retired = ev._retire_ungradeable([_qual_pred("2026-08-20", window_days=7)], "2026-08-23")
        assert (retired, table.updates) == (0, [])

    def test_the_window_is_domain_clamped_not_the_stated_one(self, monkeypatch):
        """A 1-day stated window on a body_composition claim clamps to 28 days —
        retirement must use the SAME clamp grading would have."""
        table = _TableCapture()
        monkeypatch.setattr(ev, "table", table)
        pred = _qual_pred("2026-08-10", window_days=1, subdomain="body_composition")
        assert ev._retire_ungradeable([pred], "2026-08-23") == 0
        assert ev._retire_ungradeable([pred], "2026-09-08") == 1

    def test_garbage_created_date_is_skipped_not_fatal(self, monkeypatch):
        table = _TableCapture()
        monkeypatch.setattr(ev, "table", table)
        assert ev._retire_ungradeable([{"created_date": None, "evaluation": {}}], "2026-08-23") == 0


# ── The GradableShare metric the ratio alarm watches ──────────────────────────


class _CWCapture:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


def _metrics(cw):
    return {m["MetricName"]: m["Value"] for m in cw.calls[-1]["MetricData"]}


class TestGradableShareMetric:
    def _emit(self, monkeypatch, gradable, ungradeable):
        cw = _CWCapture()
        monkeypatch.setattr(ev, "_cw", cw)
        monkeypatch.setattr(ev, "_write_last_decided_date", lambda d: None)
        monkeypatch.setattr(ev, "_read_last_decided_date", lambda: None)
        out = ev.emit_grading_liveness({}, gradable, "2026-08-23", ungradeable_count=ungradeable)
        return out, cw

    def test_the_dil007_corpus_shape_reads_below_the_alarm_threshold(self, monkeypatch):
        """The audited corpus (22 gradable / 28 qualitative-pending) must emit a
        share the prediction-gradable-share-low alarm (< 0.5) actually fires on —
        the stalled alarm alone cannot see a structurally-skipped majority."""
        out, cw = self._emit(monkeypatch, 22, 28)
        m = _metrics(cw)
        assert m["GradableCount"] == 22.0
        assert m["UngradeablePendingCount"] == 28.0
        assert m["GradableShare"] == 22 / 50
        assert m["GradableShare"] < 0.5
        assert out["gradable_share"] == 22 / 50

    def test_a_healthy_corpus_reads_above_threshold(self, monkeypatch):
        out, cw = self._emit(monkeypatch, 10, 0)
        assert _metrics(cw)["GradableShare"] == 1.0

    def test_an_empty_pending_corpus_emits_no_share(self, monkeypatch):
        """No composition to judge — the alarm treats missing as not-breaching
        (a dead evaluator is grading-stalled's BREACHING gauge's job)."""
        out, cw = self._emit(monkeypatch, 0, 0)
        assert "GradableShare" not in _metrics(cw)
        assert out["gradable_share"] is None
