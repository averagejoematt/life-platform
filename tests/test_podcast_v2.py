"""tests/test_podcast_v2.py — podcast two-pass dialogue + show memory (#547).

Pins the pure parts: turn interleaving (pairs, sign-off, cap), the memory block
(callback instruction only when material exists), dispute material shaping, and
the v2→v1 fallback contract (v2 returns {} on any malformed pass so the caller's
`or _build_weekly_script(...)` keeps the show alive).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "emails"))

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import podcast_script_v2 as psv2  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402


class _Log:
    @staticmethod
    def warning(*a):
        pass


def _deps(invoke, dispute=""):
    return {
        "table": FakeDdbTable(),
        "s3": None,
        "bucket": "b",
        "user_id": "matthew",
        "writer_model": "test-model",
        "invoke": invoke,
        "extract_json": _extract_json,
        "elena_host_state": lambda: "",
        "episode_angle": lambda w: "the angle",
        "logger": _Log(),
    }


def _extract_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


class TestInterleave:
    def test_pairs_in_order_with_signoff(self):
        elena = [{"line": "E1"}, {"line": "E2"}, {"line": "signoff"}]
        coach = ["C1", "C2"]
        turns = psv2.interleave_turns(elena, coach)
        assert [(t["speaker"], t["line"]) for t in turns] == [
            ("elena", "E1"),
            ("coach", "C1"),
            ("elena", "E2"),
            ("coach", "C2"),
            ("elena", "signoff"),
        ]

    def test_cap(self):
        elena = [{"line": f"E{i}"} for i in range(30)]
        coach = [f"C{i}" for i in range(30)]
        assert len(psv2.interleave_turns(elena, coach, cap=22)) == 22

    def test_empty_lines_dropped(self):
        turns = psv2.interleave_turns([{"line": "E1"}, {"line": ""}], ["", "C2"])
        assert [(t["speaker"], t["line"]) for t in turns] == [("elena", "E1"), ("coach", "C2")]

    def test_plain_string_turns_accepted(self):
        turns = psv2.interleave_turns(["E1"], ["C1"])
        assert turns[0]["line"] == "E1" and turns[1]["line"] == "C1"


class TestMemoryBlock:
    def test_empty_memory_no_block(self):
        assert psv2.memory_block({"callbacks": [], "guest_history": []}) == ""

    def test_callback_instruction_present_when_material_exists(self):
        block = psv2.memory_block(
            {
                "callbacks": [{"week": 3, "title": "The Plateau", "pull_quote": "the scale lies weekly", "open_bet": "sleep 7h+"}],
                "guest_history": [{"week": 3, "name": "Dr. Park"}],
            }
        )
        assert "LAND AT LEAST ONE CALLBACK" in block
        assert "The Plateau" in block and "wk3 Dr. Park" in block


class TestV2Fallback:
    def _beats(self):
        return {
            "week": 5,
            "title": "Week five",
            "chronicle": "",
            "guest": {"id": "sleep_coach", "name": "Dr. Park", "summary": "sleep steady", "themes": ["sleep"]},
            "coach_reads": [{"id": "x", "name": "X", "summary": "REAL DISPUTE MATERIAL"}],
            "recent_topics": [],
            "last_open_bet": None,
        }

    def test_pass1_garbage_returns_empty(self):
        deps = _deps(lambda body, model_name=None: {"content": [{"type": "text", "text": "not json at all"}]})
        assert psv2.build_weekly_script_v2(self._beats(), {}, deps) == {}

    def test_happy_path_two_calls_and_contract(self, monkeypatch):
        calls = []

        def _invoke(body, model_name=None):
            calls.append(body)
            if len(calls) == 1:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"elena_turns":[{"line":"E1","wants_from_guest":"q1"},{"line":"E2"},{"line":"E3"},{"line":"E4"},{"line":"bye"}],"open_bet":"bet","last_bet_result":{"outcome":"open"},"pull_quote":"pq","episode_title":"The Turn"}',
                        }
                    ]
                }
            return {"content": [{"type": "text", "text": '{"replies":["C1","C2","C3","C4"]}'}]}

        deps = _deps(_invoke)
        monkeypatch.setattr(psv2, "guest_voice_spec", lambda s3, b, gid: ("{}", ""))
        out = psv2.build_weekly_script_v2(self._beats(), {}, deps)
        assert out["script_engine"] == "two-pass-v2"
        assert out["episode_title"] == "The Turn" and out["open_bet"] == "bet"
        assert len(out["turns"]) == 9  # 4 pairs + sign-off
        assert len(calls) == 2  # exactly two passes
        # pass 2 saw Elena's ACTUAL line and the real split material
        pass2 = json.dumps(calls[1])
        assert "E1" in pass2 and "REAL DISPUTE MATERIAL" in pass2

    def test_lambda_wrapper_falls_back_on_engine_error(self, monkeypatch):
        import coach_panel_podcast_lambda as pod

        monkeypatch.setattr(pod._psv2, "build_weekly_script_v2", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
        assert pod._build_weekly_script_v2({}, {}) == {}


class _RecLog:
    def __init__(self):
        self.lines = []

    def warning(self, msg, *a):
        self.lines.append(msg % a if a else msg)

    info = warning


# #4514: the 10-01 15:33Z dry run — pass-1 cut at max_tokens mid-turn (shape of the real reply).
_TRUNCATED_PASS1 = (
    '{"elena_turns":[{"line":"Week three, and the bet from last week is still open.","wants_from_guest":"score the bet"},'
    '{"line":"Sleep held at seven hours on four of six nights","wants_from_guest":"is that'
)


class TestPassBudgetAndFallbackKey4514:
    def _beats(self):
        return TestV2Fallback()._beats()

    def test_truncated_pass1_is_unevaluated_and_the_fallback_is_counted_by_name(self, monkeypatch):
        log = _RecLog()
        deps = _deps(
            lambda body, model_name=None: {
                "content": [{"type": "text", "text": _TRUNCATED_PASS1}],
                "stop_reason": "max_tokens",
            }
        )
        deps["logger"] = log
        assert psv2.build_weekly_script_v2(self._beats(), {}, deps) == {}
        fb = [ln for ln in log.lines if "falling back to v1" in ln]
        assert len(fb) == 1, log.lines
        assert "pass-1 (Elena) UNEVALUATED" in fb[0]
        assert "stop_reason=max_tokens" in fb[0]
        assert "v2_fallback=pass-1" in fb[0]
        assert "JSONDecodeError" in fb[0]  # the decoder's message and position, not a bare "failed"

    def test_truncated_pass2_names_its_stage(self, monkeypatch):
        log = _RecLog()
        calls = []

        def _invoke(body, model_name=None):
            calls.append(body)
            if len(calls) == 1:
                turns = [{"line": f"E{i}", "wants_from_guest": "q"} for i in range(6)]
                return {"content": [{"type": "text", "text": json.dumps({"elena_turns": turns})}], "stop_reason": "end_turn"}
            return {"content": [{"type": "text", "text": '{"replies":["C1","C2'}], "stop_reason": "max_tokens"}

        deps = _deps(_invoke)
        deps["logger"] = log
        monkeypatch.setattr(psv2, "guest_voice_spec", lambda s3, b, gid: ("", ""))
        assert psv2.build_weekly_script_v2(self._beats(), {}, deps) == {}
        assert any("v2_fallback=pass-2" in ln and "stop_reason=max_tokens" in ln for ln in log.lines), log.lines

    def test_both_passes_carry_the_measured_budget_and_a_schema(self, monkeypatch):
        calls = []

        def _invoke(body, model_name=None):
            calls.append(body)
            if len(calls) == 1:
                turns = [{"line": f"E{i}", "wants_from_guest": "q"} for i in range(6)]
                return {"content": [{"type": "text", "text": json.dumps({"elena_turns": turns})}], "stop_reason": "end_turn"}
            return {"content": [{"type": "text", "text": '{"replies":["C1","C2","C3","C4","C5"]}'}], "stop_reason": "end_turn"}

        deps = _deps(_invoke)
        monkeypatch.setattr(psv2, "guest_voice_spec", lambda s3, b, gid: ("", ""))
        out = psv2.build_weekly_script_v2(self._beats(), {}, deps)
        assert out["script_engine"] == "two-pass-v2"
        # The largest measured writer reply was 2,246 tokens (09-17..10-01); the budget sits above it.
        assert psv2.PASS_MAX_TOKENS > 2246
        assert [c["max_tokens"] for c in calls] == [psv2.PASS_MAX_TOKENS, psv2.PASS_MAX_TOKENS]
        fmts = [c["output_config"]["format"]["schema"] for c in calls]
        assert fmts == [psv2.ELENA_OUTPUT_SCHEMA, psv2.GUEST_OUTPUT_SCHEMA]
