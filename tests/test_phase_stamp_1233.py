"""tests/test_phase_stamp_1233.py — #1233 write-time cycle/phase provenance.

phase_taxonomy.py promised "experiment_scoped writers stamp cycle + phase at write
time so records self-describe on partitions the tagger cannot reach" — but the live
COACH#/ENSEMBLE#/NARRATIVE# intelligence output writers stamped neither. These tests
pin the shared helper (phase_taxonomy.experiment_stamp) and prove the coach OUTPUT#
writer's put_item payload now carries phase + cycle.

Non-vacuity: the coach-output-writer assertions fail against the pre-fix writer,
whose item dict has no phase/cycle keys (KeyError on item["phase"]).
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach"))

import coach_checkin  # noqa: E402
import phase_taxonomy as pt  # noqa: E402
from constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402

# ── the shared helper ─────────────────────────────────────────────────────────


class TestExperimentStamp:
    def test_phase_and_cycle_when_cycle_reads(self, monkeypatch):
        monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 7)
        stamp = pt.experiment_stamp()
        assert stamp["phase"] == EXPERIMENT_PHASE_CURRENT
        assert stamp["cycle"] == 7

    def test_phase_only_when_cycle_unreadable(self, monkeypatch):
        # read_cycle is fail-soft (returns None) when SSM is unreachable.
        monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: None)
        stamp = pt.experiment_stamp()
        assert stamp == {"phase": EXPERIMENT_PHASE_CURRENT}
        assert "cycle" not in stamp

    def test_never_raises_if_read_cycle_throws(self, monkeypatch):
        # Provenance must NEVER break a write — an exploding read still returns a stamp.
        def _boom(ssm_client=None):
            raise RuntimeError("ssm exploded")

        monkeypatch.setattr(coach_checkin, "read_cycle", _boom)
        stamp = pt.experiment_stamp()
        assert stamp == {"phase": EXPERIMENT_PHASE_CURRENT}

    def test_include_phase_false_is_cycle_only(self, monkeypatch):
        # NARRATIVE#arc path: preserve the arc `phase`, stamp cycle only.
        monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 7)
        stamp = pt.experiment_stamp(include_phase=False)
        assert stamp == {"cycle": 7}
        assert "phase" not in stamp


# ── the coach OUTPUT# writer's put_item payload (the regression guard) ─────────


class TestCoachOutputWriterStamps:
    def _capture_table(self, monkeypatch):
        import coach_state_updater as su

        captured = {}

        class _FakeTable:
            def put_item(self, Item=None):
                captured["item"] = Item

        monkeypatch.setattr(su, "table", _FakeTable())
        monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 7)
        return su, captured

    def test_output_record_payload_has_phase_and_cycle(self, monkeypatch):
        su, captured = self._capture_table(monkeypatch)
        su._write_output_record(
            "explorer_coach",
            "2026-07-18",
            "daily_brief",
            "Some coach output text with several words in it.",
            {"themes": ["sleep"], "structural_fingerprint": {}},
        )
        item = captured["item"]
        # The row is genuinely the COACH# OUTPUT# record...
        assert item["pk"] == "COACH#explorer_coach"
        assert item["sk"].startswith("OUTPUT#2026-07-18")
        # ...and it now self-describes (this fails against the pre-fix writer).
        assert item["phase"] == EXPERIMENT_PHASE_CURRENT
        assert item["cycle"] == 7

    def test_voice_state_payload_has_phase_and_cycle(self, monkeypatch):
        su, captured = self._capture_table(monkeypatch)
        su._update_voice_state("explorer_coach", {"structural_fingerprint": {"opening_type": "question"}})
        item = captured["item"]
        assert item["sk"] == "VOICE#state"
        assert item["phase"] == EXPERIMENT_PHASE_CURRENT
        assert item["cycle"] == 7

    def test_stamp_does_not_clobber_explicit_item_keys(self, monkeypatch):
        # The item's own keys win over the stamp (merge order {**stamp, **item}).
        import coach_state_updater as su

        captured = {}

        class _FakeTable:
            def put_item(self, Item=None):
                captured["item"] = Item

        monkeypatch.setattr(su, "table", _FakeTable())
        monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 7)
        su._put_item({"pk": "COACH#x", "sk": "OUTPUT#z", "phase": "pilot"})
        # An explicit phase (e.g. an archived row) is preserved, not overwritten.
        assert captured["item"]["phase"] == "pilot"
        assert captured["item"]["cycle"] == 7
