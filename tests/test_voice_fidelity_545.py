"""tests/test_voice_fidelity_545.py — the blind voice-fidelity harness (#545, epic #526).

Pins the deterministic scorer (voice_fidelity_core: majority vote resolution +
the confusion-matrix/distinguishability scoring) and the harness orchestration
(voice_fidelity_harness: JSON-vote parsing, sample selection, the budget/monthly-
dedupe gates, the end-to-end write shape) with every Bedrock/DynamoDB call mocked
— no real inference, no real AWS calls.
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

import voice_fidelity_core as vfc  # noqa: E402
import voice_fidelity_harness as vfh  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
# voice_fidelity_core — pure scorer
# ══════════════════════════════════════════════════════════════════════════════


class TestMajorityGuess:
    def test_unanimous(self):
        votes = [{"guess": "sleep_coach", "confidence": 0.9}] * 3
        predicted, agreement, mean_conf = vfc.majority_guess(votes)
        assert predicted == "sleep_coach"
        assert agreement == 1.0
        assert mean_conf == 0.9

    def test_majority_wins(self):
        votes = [
            {"guess": "sleep_coach", "confidence": 0.8},
            {"guess": "sleep_coach", "confidence": 0.6},
            {"guess": "training_coach", "confidence": 0.95},
        ]
        predicted, agreement, _ = vfc.majority_guess(votes)
        assert predicted == "sleep_coach"
        assert round(agreement, 2) == round(2 / 3, 2)

    def test_tie_breaks_by_summed_confidence(self):
        votes = [
            {"guess": "sleep_coach", "confidence": 0.9},
            {"guess": "training_coach", "confidence": 0.3},
            {"guess": "training_coach", "confidence": 0.2},
        ]
        # sleep_coach: 1 vote, conf 0.9. training_coach: 2 votes, conf 0.5 total.
        # counts differ (1 vs 2) so this isn't actually a tie — training_coach wins on count.
        predicted, _, _ = vfc.majority_guess(votes)
        assert predicted == "training_coach"

    def test_true_tie_breaks_by_confidence_then_id(self):
        votes = [
            {"guess": "training_coach", "confidence": 0.9},
            {"guess": "mind_coach", "confidence": 0.1},
        ]
        # both have 1 vote each — tie on count, training_coach wins on higher confidence
        predicted, _, _ = vfc.majority_guess(votes)
        assert predicted == "training_coach"

    def test_exact_tie_breaks_lexicographically(self):
        votes = [
            {"guess": "training_coach", "confidence": 0.5},
            {"guess": "mind_coach", "confidence": 0.5},
        ]
        predicted, _, _ = vfc.majority_guess(votes)
        assert predicted == "mind_coach"  # lexicographically smaller

    def test_empty_votes(self):
        predicted, agreement, mean_conf = vfc.majority_guess([])
        assert predicted is None and agreement == 0.0 and mean_conf is None

    def test_votes_missing_guess_are_ignored(self):
        predicted, _, _ = vfc.majority_guess([{"confidence": 0.5}, {"guess": "sleep_coach", "confidence": 0.5}])
        assert predicted == "sleep_coach"


class TestScoreRun:
    def test_empty_judgments(self):
        result = vfc.score_run([], candidate_pool_size=8)
        assert result["n"] == 0
        assert result["accuracy_pct"] is None
        assert result["chance_accuracy_pct"] == 12.5
        assert result["verdict"] == "insufficient_data"
        assert result["worst_confused_pair"] is None
        assert result["per_coach"] == []

    def test_drops_rows_without_a_prediction(self):
        judgments = [{"actual_coach_id": "sleep_coach", "predicted_coach_id": None}]
        result = vfc.score_run(judgments, candidate_pool_size=8)
        assert result["n"] == 0

    def test_perfect_accuracy_all_coaches_distinct(self):
        # 8 coaches x 8 correct judgments each -> well above n=6 floor and far above chance.
        judgments = []
        for coach in ["a", "b", "c", "d", "e", "f", "g", "h"]:
            judgments += [{"actual_coach_id": coach, "predicted_coach_id": coach}] * 8
        result = vfc.score_run(judgments, candidate_pool_size=8)
        assert result["n"] == 64
        assert result["accuracy_pct"] == 100.0
        assert result["verdict"] == "distinct"
        for c in result["per_coach"]:
            assert c["distinguishability"] == "distinct"
        assert result["worst_confused_pair"] is None  # no off-diagonal entries at all

    def test_chance_level_confusion_is_confusable(self):
        # sleep_coach's real output gets guessed as sleep/train/nutri/mind evenly (~chance
        # at pool size 4) — repeat enough times to clear the n floor.
        guesses = ["sleep_coach", "training_coach", "nutrition_coach", "mind_coach"] * 3
        judgments = [{"actual_coach_id": "sleep_coach", "predicted_coach_id": g} for g in guesses]
        result = vfc.score_run(judgments, candidate_pool_size=4)
        coach_row = result["per_coach"][0]
        assert coach_row["n"] == 12
        assert coach_row["distinguishability"] == "confusable"

    def test_insufficient_data_below_n_floor(self):
        judgments = [{"actual_coach_id": "sleep_coach", "predicted_coach_id": "sleep_coach"}] * 2
        result = vfc.score_run(judgments, candidate_pool_size=8)
        assert result["per_coach"][0]["distinguishability"] == "insufficient_data"
        assert result["verdict"] == "insufficient_data"

    def test_confusion_matrix_and_worst_pair(self):
        judgments = (
            [{"actual_coach_id": "sleep_coach", "predicted_coach_id": "training_coach"}] * 5
            + [{"actual_coach_id": "training_coach", "predicted_coach_id": "sleep_coach"}] * 3
            + [{"actual_coach_id": "mind_coach", "predicted_coach_id": "sleep_coach"}] * 1
        )
        result = vfc.score_run(judgments, candidate_pool_size=8)
        assert result["confusion"]["sleep_coach"]["training_coach"] == 5
        assert result["confusion"]["training_coach"]["sleep_coach"] == 3
        # sleep<->training: 5+3=8 combined, the largest off-diagonal pair total
        assert result["worst_confused_pair"] == {"coaches": ["sleep_coach", "training_coach"], "confusions": 8}

    def test_worst_pair_tie_break_is_deterministic(self):
        judgments = [
            {"actual_coach_id": "b", "predicted_coach_id": "a"},
            {"actual_coach_id": "d", "predicted_coach_id": "c"},
        ]
        result = vfc.score_run(judgments, candidate_pool_size=8)
        # both pairs have 1 confusion each; ("a","b") sorts before ("c","d")
        assert result["worst_confused_pair"] == {"coaches": ["a", "b"], "confusions": 1}


# ══════════════════════════════════════════════════════════════════════════════
# voice_fidelity_harness — orchestration, all I/O mocked
# ══════════════════════════════════════════════════════════════════════════════


class TestParseVote:
    VALID = {"sleep_coach", "training_coach"}

    def test_plain_json(self):
        vote = vfh._parse_vote('{"guess": "sleep_coach", "confidence": 0.7, "reasoning": "x"}', self.VALID)
        assert vote == {"guess": "sleep_coach", "confidence": 0.7}

    def test_fenced_json(self):
        text = '```json\n{"guess": "training_coach", "confidence": 0.4}\n```'
        vote = vfh._parse_vote(text, self.VALID)
        assert vote == {"guess": "training_coach", "confidence": 0.4}

    def test_bare_fence(self):
        text = '```\n{"guess": "sleep_coach", "confidence": 0.9}\n```'
        vote = vfh._parse_vote(text, self.VALID)
        assert vote["guess"] == "sleep_coach"

    def test_guess_outside_roster_is_dropped(self):
        assert vfh._parse_vote('{"guess": "made_up_coach", "confidence": 0.5}', self.VALID) == {}

    def test_malformed_json_is_dropped(self):
        assert vfh._parse_vote("not json at all", self.VALID) == {}

    def test_missing_confidence_defaults(self):
        vote = vfh._parse_vote('{"guess": "sleep_coach"}', self.VALID)
        assert vote["confidence"] == 0.5

    def test_confidence_is_clamped(self):
        vote = vfh._parse_vote('{"guess": "sleep_coach", "confidence": 5}', self.VALID)
        assert vote["confidence"] == 1.0


class TestBuildUserMessage:
    def test_roster_and_passage_present(self):
        candidates = [{"coach_id": "sleep_coach", "name": "Dr. Lisa Park", "domain": "sleep_science"}]
        msg = vfh._build_user_message(candidates, "some passage text")
        assert "sleep_coach" in msg and "Dr. Lisa Park" in msg and "sleep_science" in msg
        assert "some passage text" in msg


class TestRunPanel:
    CANDIDATES = [
        {"coach_id": "sleep_coach", "name": "Dr. Lisa Park", "domain": "sleep_science"},
        {"coach_id": "training_coach", "name": "Dr. Sarah Chen", "domain": "exercise_physiology"},
    ]

    def test_three_calls_collected(self, monkeypatch):
        calls = []

        class _BR:
            @staticmethod
            def invoke(body, model_name=None):
                calls.append(body)
                return {"content": [{"type": "text", "text": '{"guess": "sleep_coach", "confidence": 0.6}'}]}

        monkeypatch.setitem(sys.modules, "bedrock_client", _BR)
        votes = vfh._run_panel(self.CANDIDATES, "a passage")
        assert len(calls) == 3
        assert len(votes) == 3
        # panel temperature diversity — not 3 copies of one call
        assert len({c["temperature"] for c in calls}) == 3

    def test_one_panelist_failure_shrinks_panel_not_crashes(self, monkeypatch):
        state = {"n": 0}

        class _BR:
            @staticmethod
            def invoke(body, model_name=None):
                state["n"] += 1
                if state["n"] == 2:
                    raise RuntimeError("throttled")
                return {"content": [{"type": "text", "text": '{"guess": "training_coach", "confidence": 0.5}'}]}

        monkeypatch.setitem(sys.modules, "bedrock_client", _BR)
        votes = vfh._run_panel(self.CANDIDATES, "a passage")
        assert len(votes) == 2

    def test_all_malformed_returns_no_votes(self, monkeypatch):
        class _BR:
            @staticmethod
            def invoke(body, model_name=None):
                return {"content": [{"type": "text", "text": "garbage"}]}

        monkeypatch.setitem(sys.modules, "bedrock_client", _BR)
        assert vfh._run_panel(self.CANDIDATES, "a passage") == []


class TestSampleRecentOutputs:
    def test_filters_short_passages_and_truncates(self, monkeypatch):
        items = [
            {"sk": "OUTPUT#2026-07-04#brief", "content": "x" * 50},  # too short, skipped
            {"sk": "OUTPUT#2026-07-03#brief", "content": "y" * 3000},  # kept, truncated
            {"sk": "OUTPUT#2026-07-02#brief", "content": "z" * 500},  # kept
            {"sk": "OUTPUT#2026-07-01#brief", "content": "w" * 500},  # not needed (n=2 already hit)
        ]
        monkeypatch.setattr(vfh.table, "query", lambda **kw: {"Items": items})
        samples = vfh._sample_recent_outputs("sleep_coach", n=2)
        assert len(samples) == 2
        assert samples[0]["sample_date"] == "2026-07-03"
        assert len(samples[0]["passage"]) == vfh.PASSAGE_TRUNCATE_CHARS
        assert samples[1]["sample_date"] == "2026-07-02"

    def test_query_failure_returns_empty(self, monkeypatch):
        def _boom(**kw):
            raise RuntimeError("ddb down")

        monkeypatch.setattr(vfh.table, "query", _boom)
        assert vfh._sample_recent_outputs("sleep_coach") == []


class TestLoadCumulativeJudgments:
    def test_aggregates_across_coaches(self, monkeypatch):
        def _fake_query(**kwargs):
            return {"Items": [{"actual_coach_id": "sleep_coach", "predicted_coach_id": "sleep_coach"}]}

        monkeypatch.setattr(vfh.table, "query", _fake_query)
        judgments = vfh._load_cumulative_judgments(["sleep_coach", "training_coach"])
        assert len(judgments) == 2  # one fake row per coach queried


class TestLambdaHandler:
    def _clean_tier(self, monkeypatch):
        import budget_guard

        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)

    def test_budget_gate_skips(self, monkeypatch):
        import budget_guard

        monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)
        result = vfh.lambda_handler({}, None)
        assert result == {"skipped": "budget", "tier": 1}

    def test_already_ran_this_month_skips(self, monkeypatch):
        self._clean_tier(monkeypatch)
        monkeypatch.setattr(vfh.table, "get_item", lambda **kw: {"Item": {"pk": vfh.SCOREBOARD_PK}})
        result = vfh.lambda_handler({}, None)
        assert result["skipped"] == "already_ran_this_month"

    def test_force_bypasses_monthly_dedupe(self, monkeypatch):
        self._clean_tier(monkeypatch)
        monkeypatch.setattr(vfh.table, "get_item", lambda **kw: (_ for _ in ()).throw(AssertionError("should not check")))
        monkeypatch.setattr(vfh, "_load_candidates", lambda: [])
        result = vfh.lambda_handler({"force": True}, None)
        assert result == {"skipped": "roster_unavailable"}

    def test_happy_path_writes_scoreboard(self, monkeypatch):
        self._clean_tier(monkeypatch)
        monkeypatch.setattr(vfh.table, "get_item", lambda **kw: {"Item": None})

        candidates = [
            {"coach_id": "sleep_coach", "name": "Dr. Lisa Park", "domain": "sleep_science"},
            {"coach_id": "training_coach", "name": "Dr. Sarah Chen", "domain": "exercise_physiology"},
        ]
        monkeypatch.setattr(vfh, "_load_candidates", lambda: candidates)

        def _fake_samples(coach_id, n=vfh.SAMPLES_PER_COACH, lookback=8):
            return [{"coach_id": coach_id, "sample_date": "2026-07-01", "passage": "some passage"}]

        monkeypatch.setattr(vfh, "_sample_recent_outputs", _fake_samples)

        # sleep_coach's output is correctly identified; training_coach's is misread as sleep_coach.
        def _fake_panel(cands, passage):
            return [{"guess": "sleep_coach", "confidence": 0.8}] * 3

        monkeypatch.setattr(vfh, "_run_panel", _fake_panel)

        written = []
        monkeypatch.setattr(vfh.table, "put_item", lambda Item: written.append(Item))

        cumulative = [
            {"actual_coach_id": "sleep_coach", "predicted_coach_id": "sleep_coach"},
            {"actual_coach_id": "training_coach", "predicted_coach_id": "sleep_coach"},
        ]
        monkeypatch.setattr(vfh, "_load_cumulative_judgments", lambda coach_ids: cumulative)

        result = vfh.lambda_handler({}, None)

        assert result["new_samples"] == 2  # one judgment written per coach
        assert result["cumulative_n"] == 2
        assert result["accuracy_pct"] == 50.0

        judgment_writes = [w for w in written if str(w["pk"]).startswith("VOICEFIDELITY#") and str(w["sk"]).startswith("JUDGMENT#")]
        assert len(judgment_writes) == 2
        assert {w["actual_coach_id"] for w in judgment_writes} == {"sleep_coach", "training_coach"}

        scoreboard_writes = [w for w in written if w["pk"] == vfh.SCOREBOARD_PK]
        skeys = {w["sk"] for w in scoreboard_writes}
        assert "latest" in skeys
        assert any(str(sk).startswith("RUN#") for sk in skeys)

    def test_panel_with_no_usable_votes_writes_no_judgment(self, monkeypatch):
        self._clean_tier(monkeypatch)
        monkeypatch.setattr(vfh.table, "get_item", lambda **kw: {"Item": None})
        monkeypatch.setattr(
            vfh,
            "_load_candidates",
            lambda: [{"coach_id": "sleep_coach", "name": "x", "domain": "y"}, {"coach_id": "training_coach", "name": "z", "domain": "w"}],
        )
        monkeypatch.setattr(
            vfh,
            "_sample_recent_outputs",
            lambda coach_id, n=vfh.SAMPLES_PER_COACH, lookback=8: [{"coach_id": coach_id, "sample_date": "2026-07-01", "passage": "p"}],
        )
        monkeypatch.setattr(vfh, "_run_panel", lambda cands, passage: [])  # every panelist failed
        written = []
        monkeypatch.setattr(vfh.table, "put_item", lambda Item: written.append(Item))
        monkeypatch.setattr(vfh, "_load_cumulative_judgments", lambda coach_ids: [])

        result = vfh.lambda_handler({}, None)
        assert result["new_samples"] == 0
        judgment_writes = [w for w in written if str(w["sk"]).startswith("JUDGMENT#")]
        assert judgment_writes == []
