"""tests/test_inter_coach_dialogue.py — real inter-coach dialogue (#540).

Pins the deterministic parts: the dispute selector (recurrence + influence
weight, cooldown, position requirements, stable tie-breaks), the ISO-week cap
arithmetic, the turn prompt (the colleague's SPECIFIC claim is in the prompt),
and the ≤4-calls/week structure (2 generations + at most 2 gate regens).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "coach"))

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import inter_coach_dialogue_lambda as icd  # noqa: E402


def _topic(slug, coaches, cycle_count=1, positions=None, status=None, last_aired=None):
    t = {
        "sk": f"ACTIVE#{slug}",
        "topic": slug.replace("_", " "),
        "coaches": coaches,
        "positions": positions if positions is not None else {c: f"{c} position" for c in coaches},
        "cycle_count": cycle_count,
    }
    if status:
        t["status"] = status
    if last_aired:
        t["last_aired_week"] = last_aired
    return t


WEIGHTS = {"sleep_coach → training_coach": 0.9, "mind_coach → sleep_coach": 0.7}


class TestSelector:
    def test_picks_most_persistent_weighted(self):
        topics = [
            _topic("minor_spat", ["nutrition_coach", "training_coach"], cycle_count=1),
            _topic("sleep_vs_training", ["sleep_coach", "training_coach"], cycle_count=4),
        ]
        pick = icd.select_dispute(topics, WEIGHTS, "2026-W27")
        assert pick["topic"]["sk"] == "ACTIVE#sleep_vs_training"
        assert {pick["coach_a"], pick["coach_b"]} == {"sleep_coach", "training_coach"}
        assert pick["influence_weight"] == 0.9

    def test_resolved_and_recently_aired_excluded(self):
        topics = [
            _topic("done", ["a", "b"], cycle_count=9, status="resolved"),
            _topic("fresh_fight", ["a", "b"], cycle_count=1),
            _topic("just_aired", ["a", "b"], cycle_count=9, last_aired="2026-W26"),
        ]
        pick = icd.select_dispute(topics, {}, "2026-W27")
        assert pick["topic"]["sk"] == "ACTIVE#fresh_fight"

    def test_cooldown_expires(self):
        topics = [_topic("old_fight", ["a", "b"], cycle_count=3, last_aired="2026-W20")]
        assert icd.select_dispute(topics, {}, "2026-W27") is not None

    def test_needs_two_recorded_positions(self):
        topics = [
            _topic("half_recorded", ["a", "b"], cycle_count=5, positions={"a": "claim"}),
        ]
        assert icd.select_dispute(topics, {}, "2026-W27") is None

    def test_deterministic_tiebreak(self):
        topics = [
            _topic("zeta", ["a", "b"], cycle_count=2),
            _topic("alpha", ["a", "b"], cycle_count=2),
        ]
        for _ in range(3):
            assert icd.select_dispute(topics, {}, "2026-W27")["topic"]["sk"] == "ACTIVE#alpha"

    def test_empty(self):
        assert icd.select_dispute([], {}, "2026-W27") is None


class TestWeekMath:
    def test_weeks_between(self):
        assert icd._weeks_between("2026-W20", "2026-W27") == 7
        assert icd._weeks_between("2025-W50", "2026-W02") == 4
        assert icd._weeks_between("garbage", "2026-W27") == icd.AIRING_COOLDOWN_WEEKS

    def test_iso_week_format(self):
        from datetime import datetime, timezone

        assert icd.iso_week(datetime(2026, 7, 5, tzinfo=timezone.utc)) == "2026-W27"


class TestTurnPrompt:
    def test_reply_contains_the_specific_claim(self):
        sysb, user = icd.build_turn_prompt(
            {"name": "Dr. Lisa Park", "board_role": "sleep"},
            {"name": "Coach Dan"},
            "protein timing vs sleep",
            "late protein wrecks deep sleep by 40 minutes",
            "protein timing is irrelevant, totals rule",
            "{}",
            "",
        )
        assert "late protein wrecks deep sleep by 40 minutes" in user
        assert "Coach Dan's recorded position" in user
        assert "SPECIFIC claim" in sysb
        assert str(icd.MAX_TURN_WORDS) in sysb

    def test_rejoinder_carries_the_actual_reply(self):
        _sys, user = icd.build_turn_prompt({"name": "A"}, {"name": "B"}, "t", "b-claim", "a-claim", "", "", prior_reply="B's actual words")
        assert "B's actual words" in user
        assert "rejoinder" in user


class TestGatedTurn:
    def test_two_calls_max_per_turn(self, monkeypatch):
        calls = []

        class _BR:
            @staticmethod
            def invoke(body, model_name=None):
                calls.append(body)
                # first call fabricates a number; the regen fixes it
                text = "Recovery hit 87 yesterday." if len(calls) == 1 else "Recovery held steady."
                return {"content": [{"type": "text", "text": text}]}

        monkeypatch.setitem(sys.modules, "bedrock_client", _BR)
        text, left = icd.generate_gated_turn("sys prompt", "user prompt", ["no numbers here"])
        assert text == "Recovery held steady."
        assert left == []
        assert len(calls) == 2  # generation + one corrective regen — never more

    def test_clean_turn_is_single_call(self, monkeypatch):
        calls = []

        class _BR:
            @staticmethod
            def invoke(body, model_name=None):
                calls.append(body)
                return {"content": [{"type": "text", "text": "Sleep first, then load."}]}

        monkeypatch.setitem(sys.modules, "bedrock_client", _BR)
        text, left = icd.generate_gated_turn("s", "u", [])
        assert text and left == [] and len(calls) == 1
