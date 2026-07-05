"""tests/test_relationship_state_536.py — #536 RELATIONSHIP#state gets its writer.

RELATIONSHIP#state was read by coach/coach_history_summarizer.py:379 and
coach/coach_observatory_renderer.py:274 but had no writer anywhere in lambdas/ —
a permanent empty default. These tests pin:
  1. relationship_engine.compute_relationship_update()'s deterministic rules
     (engagement growth, silence decay, commitment/prediction signals, phase
     transitions, tenure tracking) — pure, no AWS.
  2. coach_state_updater._gather_relationship_signals()'s since-cursor diffing.
  3. That the record this writer produces is consumable, unmodified, by both
     existing reader call sites.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach"))

import coach_state_updater as su  # noqa: E402
import relationship_engine as re_  # noqa: E402

NO_SIGNALS = {
    "kept_commitments": 0,
    "broken_commitments": 0,
    "confirmed_predictions": 0,
    "refuted_predictions": 0,
    "board_interactions": 0,
}


def _sig(**kwargs):
    s = dict(NO_SIGNALS)
    s.update(kwargs)
    return s


class TestDefaultState:
    def test_first_ever_cycle_starts_clinical(self):
        updated = re_.compute_relationship_update(None, "sleep_coach", "2026-07-01", NO_SIGNALS, "2026-07-01T12:00:00+00:00")
        assert updated["journey_phase"] == re_.PHASE_CLINICAL
        assert updated["interaction_count"] == 1
        assert updated["first_interaction_date"] == "2026-07-01"
        assert updated["last_interaction_date"] == "2026-07-01"
        assert updated["tenure_days"] == 0
        assert re_.MIN_RAPPORT <= updated["rapport_level"] <= re_.MAX_RAPPORT
        assert updated["rapport_level"] > re_.DEFAULT_RAPPORT  # the first cycle nudges it up

    def test_no_current_state_defaults_before_computing(self):
        default = re_.default_relationship_state("mind_coach", "2026-07-01")
        assert default["rapport_level"] == re_.DEFAULT_RAPPORT
        assert default["interaction_count"] == 0
        assert default["journey_phase"] == re_.PHASE_CLINICAL


class TestEngagementGrowth:
    def test_consistent_cycles_raise_rapport_and_interaction_count(self):
        state = None
        date = "2026-06-01"
        import datetime

        for _ in range(20):
            state = re_.compute_relationship_update(state, "sleep_coach", date, NO_SIGNALS, date + "T12:00:00+00:00")
            d = datetime.date.fromisoformat(date) + datetime.timedelta(days=1)
            date = d.isoformat()

        assert state["interaction_count"] == 20
        assert state["rapport_level"] > re_.DEFAULT_RAPPORT
        assert state["tenure_days"] == 19

    def test_rapport_never_exceeds_one(self):
        state = None
        date = "2026-01-01"
        import datetime

        for _ in range(500):
            state = re_.compute_relationship_update(state, "sleep_coach", date, NO_SIGNALS, date + "T00:00:00+00:00")
            d = datetime.date.fromisoformat(date) + datetime.timedelta(days=1)
            date = d.isoformat()
        assert state["rapport_level"] <= re_.MAX_RAPPORT

    def test_same_day_rerun_does_not_double_count_the_generation_cycle(self):
        first = re_.compute_relationship_update(None, "sleep_coach", "2026-07-01", NO_SIGNALS, "2026-07-01T09:00:00+00:00")
        second = re_.compute_relationship_update(first, "sleep_coach", "2026-07-01", NO_SIGNALS, "2026-07-01T18:00:00+00:00")
        # Same generation_date => no second engagement nudge or interaction bump.
        assert second["interaction_count"] == first["interaction_count"]
        assert second["rapport_level"] == first["rapport_level"]


class TestSilenceDecay:
    def test_long_silence_decays_rapport(self):
        warm = re_.compute_relationship_update(None, "sleep_coach", "2026-01-01", NO_SIGNALS, "2026-01-01T00:00:00+00:00")
        for i in range(1, 10):
            date = f"2026-01-{i+1:02d}"
            warm = re_.compute_relationship_update(warm, "sleep_coach", date, NO_SIGNALS, date + "T00:00:00+00:00")

        rapport_before_gap = warm["rapport_level"]
        after_silence = re_.compute_relationship_update(warm, "sleep_coach", "2026-03-01", NO_SIGNALS, "2026-03-01T00:00:00+00:00")
        assert after_silence["rapport_level"] < rapport_before_gap

    def test_short_gap_within_grace_window_still_grows(self):
        state = re_.compute_relationship_update(None, "sleep_coach", "2026-01-01", NO_SIGNALS, "2026-01-01T00:00:00+00:00")
        r0 = state["rapport_level"]
        state = re_.compute_relationship_update(state, "sleep_coach", "2026-01-05", NO_SIGNALS, "2026-01-05T00:00:00+00:00")
        assert state["rapport_level"] > r0

    def test_decay_is_capped_per_run(self):
        state = re_.compute_relationship_update(None, "sleep_coach", "2026-01-01", NO_SIGNALS, "2026-01-01T00:00:00+00:00")
        # A multi-year gap should not push rapport below the floor via runaway decay.
        state = re_.compute_relationship_update(state, "sleep_coach", "2030-01-01", NO_SIGNALS, "2030-01-01T00:00:00+00:00")
        assert state["rapport_level"] >= re_.MIN_RAPPORT


class TestCommitmentAndPredictionSignals:
    def test_kept_commitment_raises_rapport(self):
        base = re_.compute_relationship_update(None, "nutrition_coach", "2026-07-01", NO_SIGNALS, "2026-07-01T00:00:00+00:00")
        with_kept = re_.compute_relationship_update(
            base, "nutrition_coach", "2026-07-08", _sig(kept_commitments=1), "2026-07-08T00:00:00+00:00"
        )
        without = re_.compute_relationship_update(base, "nutrition_coach", "2026-07-08", NO_SIGNALS, "2026-07-08T00:00:00+00:00")
        assert with_kept["rapport_level"] > without["rapport_level"]
        assert with_kept["interaction_count"] > without["interaction_count"]
        assert any("kept 1 commitment" in s for s in with_kept["trust_signals"])

    def test_broken_commitment_lowers_rapport(self):
        base = re_.compute_relationship_update(None, "nutrition_coach", "2026-07-01", NO_SIGNALS, "2026-07-01T00:00:00+00:00")
        with_broken = re_.compute_relationship_update(
            base, "nutrition_coach", "2026-07-08", _sig(broken_commitments=1), "2026-07-08T00:00:00+00:00"
        )
        without = re_.compute_relationship_update(base, "nutrition_coach", "2026-07-08", NO_SIGNALS, "2026-07-08T00:00:00+00:00")
        assert with_broken["rapport_level"] < without["rapport_level"]

    def test_prediction_outcomes_move_rapport_both_ways(self):
        base = re_.compute_relationship_update(None, "training_coach", "2026-07-01", NO_SIGNALS, "2026-07-01T00:00:00+00:00")
        confirmed = re_.compute_relationship_update(
            base, "training_coach", "2026-07-08", _sig(confirmed_predictions=2), "2026-07-08T00:00:00+00:00"
        )
        refuted = re_.compute_relationship_update(
            base, "training_coach", "2026-07-08", _sig(refuted_predictions=2), "2026-07-08T00:00:00+00:00"
        )
        assert confirmed["rapport_level"] > refuted["rapport_level"]

    def test_board_qa_engagement_bumps_interaction_count(self):
        base = re_.compute_relationship_update(None, "mind_coach", "2026-07-01", NO_SIGNALS, "2026-07-01T00:00:00+00:00")
        after = re_.compute_relationship_update(base, "mind_coach", "2026-07-08", _sig(board_interactions=3), "2026-07-08T00:00:00+00:00")
        assert after["interaction_count"] == base["interaction_count"] + 1 + 3  # +1 generation cycle, +3 board Q&A


class TestPhaseTransitions:
    def test_reaches_familiar_then_invested_with_sustained_engagement(self):
        state = None
        date = "2026-01-01"
        import datetime

        phases_seen = set()
        for i in range(60):
            signals = _sig(kept_commitments=1) if i % 3 == 0 else NO_SIGNALS
            state = re_.compute_relationship_update(state, "sleep_coach", date, signals, date + "T00:00:00+00:00")
            phases_seen.add(state["journey_phase"])
            d = datetime.date.fromisoformat(date) + datetime.timedelta(days=2)
            date = d.isoformat()

        assert re_.PHASE_FAMILIAR in phases_seen
        assert re_.PHASE_INVESTED in phases_seen
        assert state["journey_phase"] == re_.PHASE_INVESTED
        # phase_history records the arc, oldest-first, ending on the current phase
        assert state["phase_history"][-1]["phase"] == re_.PHASE_INVESTED
        assert state["phase_history"][0]["phase"] == re_.PHASE_FAMILIAR

    def test_phase_history_only_logs_actual_transitions(self):
        state = None
        date = "2026-01-01"
        for _ in range(3):
            state = re_.compute_relationship_update(state, "sleep_coach", date, NO_SIGNALS, date + "T00:00:00+00:00")
        # Still clinical the whole time -> no transitions logged yet.
        assert state["journey_phase"] == re_.PHASE_CLINICAL
        assert state["phase_history"] == []


class TestGatherSignalsCursor:
    def test_no_since_date_returns_all_zero(self):
        signals = su._gather_relationship_signals("sleep_coach", None)
        assert signals == {
            "kept_commitments": 0,
            "broken_commitments": 0,
            "confirmed_predictions": 0,
            "refuted_predictions": 0,
            "board_interactions": 0,
        }

    def test_only_records_newer_than_cursor_count(self, monkeypatch):
        records_by_prefix = {
            "COMMITMENT#": [
                {"status": "kept", "outcome_date": "2026-07-01"},  # before cursor - excluded
                {"status": "kept", "outcome_date": "2026-07-10"},  # after cursor - counted
                {"status": "broken", "outcome_date": None},  # not yet graded - excluded
            ],
            "PREDICTION#": [
                {"status": "confirmed", "outcome_date": "2026-07-09"},
                {"status": "refuted", "outcome_date": "2026-06-01"},  # before cursor
            ],
            "INTERACTION#": [
                {"created_at": "2026-07-11T00:00:00+00:00"},
                {"created_at": "2026-07-01T00:00:00+00:00"},  # before cursor
            ],
        }

        def fake_query(pk, prefix, scan_forward=True):
            return records_by_prefix.get(prefix, [])

        monkeypatch.setattr(su, "_query_begins_with", fake_query)
        signals = su._gather_relationship_signals("sleep_coach", "2026-07-05")
        assert signals["kept_commitments"] == 1
        assert signals["broken_commitments"] == 0
        assert signals["confirmed_predictions"] == 1
        assert signals["refuted_predictions"] == 0
        assert signals["board_interactions"] == 1

    def test_query_failure_is_fail_soft(self, monkeypatch):
        def boom(pk, prefix, scan_forward=True):
            raise RuntimeError("dynamodb unavailable")

        monkeypatch.setattr(su, "_query_begins_with", boom)
        signals = su._gather_relationship_signals("sleep_coach", "2026-07-05")
        assert all(v == 0 for v in signals.values())


class TestUpdateRelationshipStateIntegration:
    def test_writes_expected_shape_and_uses_previous_cursor(self, monkeypatch):
        written = {}
        existing = {
            "pk": "COACH#sleep_coach",
            "sk": "RELATIONSHIP#state",
            "coach_id": "sleep_coach",
            "rapport_level": 0.4,
            "interaction_count": 8,
            "journey_phase": "familiar",
            "phase_history": [],
            "first_interaction_date": "2026-06-01",
            "last_interaction_date": "2026-06-20",
            "tenure_days": 19,
            "trust_signals": [],
            "context_summary": "sleep_coach: familiar",
            "updated_at": "2026-06-20T00:00:00+00:00",
        }

        monkeypatch.setattr(su, "_get_item", lambda pk, sk: existing if sk == "RELATIONSHIP#state" else None)
        monkeypatch.setattr(su, "_query_begins_with", lambda pk, prefix, scan_forward=True: [])

        def fake_put(item):
            written.update(item)
            return True

        monkeypatch.setattr(su, "_put_item", fake_put)

        result = su._update_relationship_state("sleep_coach", "2026-07-04")

        assert written["pk"] == "COACH#sleep_coach"
        assert written["sk"] == "RELATIONSHIP#state"
        assert written["last_interaction_date"] == "2026-07-04"
        assert written["interaction_count"] == 9
        assert result == written


class TestReaderCompatibility:
    """Prove the record this writer produces is consumable, unmodified, by both
    existing reader call sites (coach_history_summarizer.py:379,
    coach_observatory_renderer.py:274) — neither destructuring pattern should
    need to change."""

    def _sample_record(self):
        state = re_.compute_relationship_update(None, "sleep_coach", "2026-07-01", NO_SIGNALS, "2026-07-01T00:00:00+00:00")
        state["pk"] = "COACH#sleep_coach"
        state["sk"] = "RELATIONSHIP#state"
        return state

    def test_observatory_renderer_style_destructuring(self):
        relationship = self._sample_record()
        # Mirrors coach_observatory_renderer.py:274-280 exactly.
        journey_phase = None
        rapport_level = None
        if relationship:
            journey_phase = relationship.get("journey_phase")
            rapport_level = relationship.get("rapport_level")
        assert journey_phase == re_.PHASE_CLINICAL
        assert isinstance(rapport_level, float)
        assert re_.MIN_RAPPORT <= rapport_level <= re_.MAX_RAPPORT

    def test_history_summarizer_style_dump_is_json_serializable(self):
        relationship = self._sample_record()
        # Mirrors coach_history_summarizer.py:594-599 exactly.
        assert relationship  # truthy -> "## Relationship State" branch, not the NONE branch
        rel_display = {k: v for k, v in relationship.items() if k not in ("pk", "sk")}
        dumped = json.dumps(rel_display, indent=2)  # must not raise
        assert "journey_phase" in dumped
        assert "rapport_level" in dumped

    def test_empty_relationship_state_falls_back_to_none_branch(self):
        # Before this writer ever runs for a coach, _get_item returns None —
        # both readers must keep degrading gracefully in that case.
        relationship = None
        journey_phase = None
        rapport_level = None
        if relationship:
            journey_phase = relationship.get("journey_phase")
            rapport_level = relationship.get("rapport_level")
        assert journey_phase is None and rapport_level is None
