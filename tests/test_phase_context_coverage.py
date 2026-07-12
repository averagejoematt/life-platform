"""tests/test_phase_context_coverage.py — #1086: build_experiment_phase_context()
is the ONE mandatory grounding block for every AI narrative prompt builder.

Mirrors the phase_taxonomy full-coverage discipline (ADR-077 / ADR-104): a
REGISTRY of every narrative prompt builder, each driven offline, each asserted
to carry the phase-context block marker in its built prompt — so a narrative
surface cannot ship a prompt that doesn't know what day it is, what phase it
is, and who is reading. A file-level census additionally pins that every
narrative-builder module references the shared formatter (a new builder in one
of these modules that rolls its own context reds this file's census, and any
NEW narrative module must be added to both registries here).

Also pins the builder itself:
  • journey math fused with the pre-start countdown (pre_start_meta semantics
    from web/site_api_common, mirrored WITHOUT importing web/ into compute)
  • the audience descriptor (Matthew AND public readers) on every variant
  • the "numbers that cannot exist yet at this phase" guardrail when days_in
    is small / pre-start — and its absence deep into a cycle
  • the CORE block carries no body-weight numbers (the panelcast safety gate
    bans any spoken weight; only the coaching variant may carry weights)
  • COST-OPT-2: the block never rides inside a cache_control-wrapped system
    block (board_ask's cached persona system stays byte-stable)

All fixture dates are derived from EXPERIMENT_START_DATE — never wall-clock,
never literal (the golden-tests-wallclock lesson).

No real Bedrock, DDB, S3, SES, or HTTP calls anywhere in this file.
"""

import json
import os
import sys
from datetime import date, timedelta

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

import ai_calls  # noqa: E402
import ai_context  # noqa: E402
import bedrock_client  # noqa: E402
import pytest  # noqa: E402
import state_of_matthew_lambda as som  # noqa: E402
import wednesday_chronicle_lambda as chron  # noqa: E402
from emails import (
    coach_panel_podcast_lambda as panel,  # noqa: E402
    podcast_script_v2 as psv2,  # noqa: E402
)
from fakes import FakeDdbTable, json_safe_put_hook  # noqa: E402

MARKER = ai_context.PHASE_CONTEXT_MARKER
GENESIS = date.fromisoformat(ai_context.EXPERIMENT_START_DATE)


def _g(days: int) -> str:
    """A fixture date `days` after genesis (negative = pre-start) — derived
    from the constant so a cycle re-anchor can't turn this file into a bomb."""
    return (GENESIS + timedelta(days=days)).isoformat()


PROFILE = {
    "journey_start_date": ai_context.EXPERIMENT_START_DATE,
    "journey_start_weight_lbs": 300.8,
    "goal_weight_lbs": 185,
}


# ─────────────────────────────────────────────────────────────────────────────
# The builder itself
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildExperimentPhaseContext:
    def test_day_and_week_math_matches_journey_context(self):
        p = ai_context.build_experiment_phase_context(PROFILE, _g(1))
        assert p["pre_start"] is False
        assert p["days_in"] == 2 and p["week_num"] == 1
        j = ai_context._build_journey_context(PROFILE, _g(1))
        assert (p["days_in"], p["week_num"], p["stage"]) == (j["days_in"], j["week_num"], j["stage"])

    def test_pre_start_mirrors_pre_start_meta_semantics(self):
        # web/site_api_common.pre_start_meta: start > today → days_until >= 1
        p = ai_context.build_experiment_phase_context(PROFILE, _g(-2))
        assert p["pre_start"] is True
        assert p["days_until_start"] == 2
        assert p["days_in"] == 0 and p["week_num"] == 0
        assert p["early_phase"] is True  # guardrail always on pre-start
        # on genesis day itself the experiment has started (N >= 1 invariant)
        assert ai_context.build_experiment_phase_context(PROFILE, _g(0))["pre_start"] is False

    def test_guardrail_flag_by_days_in(self):
        early = ai_context.build_experiment_phase_context(PROFILE, _g(3))
        late = ai_context.build_experiment_phase_context(PROFILE, _g(80))
        assert early["early_phase"] is True
        assert late["early_phase"] is False

    def test_bad_inputs_never_raise(self):
        p = ai_context.build_experiment_phase_context({"journey_start_date": "garbage"}, "also-garbage")
        assert p["start_date"] == ai_context.EXPERIMENT_START_DATE
        assert isinstance(p["days_in"], int)

    def test_matches_live_pre_start_meta_verdict(self):
        # Semantic mirror: the compute-path builder (no args = PT today) and
        # the web-path pre_start_meta must agree on whether we're pre-start
        # and, when so, on the countdown. This is the "mirror WITHOUT
        # importing web/ into compute" contract — the TEST may import web/.
        from web.site_api_common import pre_start_meta

        meta = pre_start_meta()
        p = ai_context.build_experiment_phase_context()
        if meta is None:
            assert p["pre_start"] is False
        else:
            assert p["pre_start"] is True
            assert p["days_until_start"] == meta["days_until_start"]
            assert p["start_date"] == meta["start_date"]


class TestFormatExperimentPhaseContext:
    def test_core_block_marker_audience_guardrail(self):
        blk = ai_context.format_experiment_phase_context(ai_context.build_experiment_phase_context(PROFILE, _g(2)))
        assert MARKER in blk
        assert ai_context.PHASE_AUDIENCE_LINE in blk
        assert "NUMBERS THAT CANNOT EXIST YET" in blk
        assert "Day 3" in blk and "Week 1" in blk

    def test_core_block_carries_no_body_weight(self):
        # The panelcast safety gate HOLDs on any spoken body weight — the core
        # block must never hand the writer one.
        for d in (-3, 2, 80):
            blk = ai_context.format_experiment_phase_context(ai_context.build_experiment_phase_context(PROFILE, _g(d)))
            assert "300.8" not in blk and "185" not in blk and "lbs" not in blk

    def test_guardrail_absent_deep_into_cycle(self):
        blk = ai_context.format_experiment_phase_context(ai_context.build_experiment_phase_context(PROFILE, _g(80)))
        assert MARKER in blk
        assert "NUMBERS THAT CANNOT EXIST YET" not in blk
        assert ai_context.PHASE_AUDIENCE_LINE in blk  # audience is unconditional

    def test_pre_start_block_forbids_results(self):
        blk = ai_context.format_experiment_phase_context(ai_context.build_experiment_phase_context(PROFILE, _g(-5)))
        assert MARKER in blk
        assert "PRE-START" in blk and "NOT begun" in blk
        assert "NUMBERS THAT CANNOT EXIST YET" in blk
        assert ai_context.PHASE_AUDIENCE_LINE in blk

    def test_coaching_variant_adds_weights_and_principles(self):
        pctx = ai_context.build_experiment_phase_context(PROFILE, _g(2))
        blk = ai_context.format_experiment_phase_context(pctx, coaching_principles=True)
        assert MARKER in blk
        assert "300.8" in blk and "185" in blk
        assert any(p in blk for p in pctx["coaching_principles"])


# ─────────────────────────────────────────────────────────────────────────────
# The coverage registry — every AI narrative prompt builder carries the block.
# Add every NEW narrative prompt builder here; a builder that omits the block
# must red this class (ADR-104 grounded-generation discipline).
# ─────────────────────────────────────────────────────────────────────────────


def _patch_ai_calls(monkeypatch, response="ok || ok"):
    """Capture every prompt ai_calls sends; no Bedrock, no grounding regen."""
    calls = []

    def _fake_call(prompt, api_key, **kw):
        calls.append(prompt)
        return response

    monkeypatch.setattr(ai_calls, "call_anthropic", _fake_call)
    monkeypatch.setattr(ai_calls, "_run_analysis_pass", lambda *a, **k: {})
    monkeypatch.setattr(ai_calls, "_ground_legacy_output", lambda label, output, regen_fn, *allow: output)
    monkeypatch.setattr(ai_calls, "_build_daily_bod_intro_from_config", lambda *a, **k: "")
    return calls


class TestEveryNarrativePromptBuilderCarriesTheBlock:
    # ── ai_calls (the 4 daily-brief narrative calls + the shared system) ─────
    def test_daily_brief_shared_system(self):
        out = ai_calls.daily_brief_shared_system({"date": _g(2)}, PROFILE)
        assert MARKER in out

    def test_training_nutrition_coach_prompt(self, monkeypatch):
        calls = _patch_ai_calls(monkeypatch)
        ai_calls.call_training_nutrition_coach({"date": _g(2)}, PROFILE, "key")
        assert calls and MARKER in calls[-1]

    def test_journal_coach_prompt(self, monkeypatch):
        calls = _patch_ai_calls(monkeypatch)
        ai_calls.call_journal_coach({"date": _g(2), "journal_entries": [{"raw_text": "Slept well, walked at dusk."}]}, PROFILE, "key")
        assert calls and MARKER in calls[-1]

    def test_board_of_directors_prompt(self, monkeypatch):
        calls = _patch_ai_calls(monkeypatch)
        ai_calls.call_board_of_directors({"date": _g(2)}, PROFILE, 80, "B", {"sleep": 70}, api_key="key")
        assert calls and MARKER in calls[-1]

    def test_tldr_and_guidance_prompt(self, monkeypatch):
        calls = _patch_ai_calls(monkeypatch, response='{"tldr": "x", "guidance": []}')
        ai_calls.call_tldr_and_guidance({"date": _g(2)}, PROFILE, 80, "B", {"sleep": 70}, {}, 75, "green", "key")
        assert calls and MARKER in calls[-1]

    # ── State of Matthew (weekly model brief) ────────────────────────────────
    def test_state_of_matthew_narration(self):
        state = som.assemble_state(None, None, None, None, _g(3))
        body = som.build_narration_body(state)
        assert MARKER in body["system"]
        # the phase numbers ride the payload → the ADR-104 allow-list
        payload = som._narration_payload(state)
        assert payload["phase"]["days_in"] == 4 and payload["phase"]["week_num"] == 1

    def test_state_of_matthew_hand_built_state_still_gets_block(self):
        # fixtures/evals that skip assemble_state cannot dodge the block
        body = som.build_narration_body({"as_of": _g(3)})
        assert MARKER in body["system"]

    # ── Wednesday Chronicle (Elena) ──────────────────────────────────────────
    def _chronicle_data(self, end_days=6):
        return {
            "profile": dict(PROFILE),
            "dates": {"start": _g(end_days - 6), "end": _g(end_days)},
            "withings": {},
            "whoop": {},
            "strava": {},
            "macrofactor": {},
            "eightsleep": {},
            "journal_entries": [],
            "day_grades": {},
            "habit_scores": {},
            "habitify": {},
            "state_of_mind": {},
            "supplements": {},
            "experiments": [],
            "anomalies": {},
            "weather": {},
            "character_sheet": {},
            "prev_installments": [],
            "narrative_arc": {},
            "experiment_arc": {},
            "field_notes": [],
        }

    def test_chronicle_data_packet(self):
        packet, week_num = chron.build_data_packet(self._chronicle_data())
        assert MARKER in packet
        assert week_num == 1

    def test_chronicle_week_math_matches_old_arithmetic(self):
        # the shared block replaced the local week math — pin the equivalence
        # (d days after genesis → d//7 + 1) across week boundaries
        for d in (0, 6, 7, 13, 14, 27):
            _, week_num = chron.build_data_packet(self._chronicle_data(end_days=d))
            assert week_num == d // 7 + 1, f"end_days={d}"

    # ── The Panel (panelcast) — v1 single-call + v2 two-pass ────────────────
    def _beats(self):
        # deliberately NO phase_block key: the builders must self-provision
        return {
            "week": 1,
            "date": _g(6),
            "title": "Week 1",
            "chronicle": "A quiet, steady first week.",
            "coach_reads": [{"id": "sleep_coach", "name": "Dr. Lisa Park", "summary": "Sleep looked steady."}],
            "guest": {"id": "sleep_coach", "name": "Dr. Lisa Park", "summary": "Sleep looked steady.", "themes": []},
            "presence_note": "",
            "last_open_bet": None,
            "recent_topics": [],
            "prev_guest": "",
        }

    def test_panel_v1_weekly_script_prompt(self, monkeypatch):
        captured = []

        def _fake_invoke(body, model_name=None):
            captured.append(body)
            return {"content": [{"type": "text", "text": "not json"}]}

        monkeypatch.setattr(bedrock_client, "invoke", _fake_invoke)
        panel._build_weekly_script(self._beats(), {})
        assert captured
        assert MARKER in captured[0]["messages"][0]["content"]

    def test_panel_v2_weekly_script_prompts(self):
        captured = []

        def _fake_invoke(body, model_name=None):
            captured.append(body)
            return {"content": [{"type": "text", "text": "not json"}]}

        deps = {
            "table": FakeDdbTable(put_item_hook=json_safe_put_hook),
            "s3": None,  # guest_voice_spec fail-softs on any error
            "bucket": "test-bucket",
            "user_id": "matthew",
            "writer_model": "test-model",
            "invoke": _fake_invoke,
            "extract_json": panel._extract_json,
            "elena_host_state": lambda: "",
            "episode_angle": lambda week: "the angle",
            "logger": panel.logger,
        }
        psv2.build_weekly_script_v2(self._beats(), {}, deps)
        assert captured
        assert MARKER in captured[0]["messages"][0]["content"]

    def test_panel_gather_week_seeds_phase_block_into_allowed_material(self, monkeypatch):
        # _gather_week carries the block in beats so _run_weekly's ER-03
        # allowed-number set includes the day/week numbers a host may voice.
        monkeypatch.setattr(panel, "_chronicle_md", lambda d: None)
        monkeypatch.setattr(panel, "_coach_latest", lambda cid: None)
        monkeypatch.setattr(panel, "table", FakeDdbTable())
        beats = panel._gather_week({"week": 1, "date": _g(6), "title": "Week 1"}, {})
        assert MARKER in beats.get("phase_block", "")

    # ── Public AI surfaces (/api/ask + board_ask) ────────────────────────────
    def test_ask_system_prompt(self):
        from web import site_api_ai_lambda as ai

        assert MARKER in ai._ask_build_prompt({})

    def test_board_ask_user_turn_carries_block_and_cached_system_does_not(self, monkeypatch):
        from web import site_api_ai_lambda as ai

        table = FakeDdbTable(put_item_hook=json_safe_put_hook)
        monkeypatch.setattr(ai, "table", table)
        monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
        monkeypatch.setattr(ai, "_get_anthropic_key", lambda: "fake-key")
        monkeypatch.setattr(ai, "_ddb_rate_check", lambda *a, **k: (True, 4, 0))
        monkeypatch.setattr(ai, "_RATE_LIMITER_READY", True)
        monkeypatch.setattr(ai, "_ask_fetch_context", lambda: {"recovery_pct": 64.0})
        monkeypatch.setattr(ai, "_coach_voice_core", lambda pid: "")  # no S3
        captured = {"reqs": []}

        class _FakeBedrock:
            @staticmethod
            def invoke(req):
                captured["reqs"].append(req)
                return {"content": [{"type": "text", "text": "Steady progress — keep the routine consistent."}], "usage": {}}

        monkeypatch.setitem(sys.modules, "bedrock_client", _FakeBedrock)

        event = {
            "rawPath": "/api/board_ask",
            "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.7"}},
            "body": json.dumps({"question": "How is the experiment going so far?", "personas": ["sleep_coach"]}),
        }
        resp = ai._handle_board_ask(event)
        assert resp["statusCode"] == 200
        assert captured["reqs"], "board_ask made no model call"
        req = captured["reqs"][0]
        user_text = req["messages"][0]["content"]
        assert MARKER in user_text
        # COST-OPT-2: the daily-changing block must NOT ride the
        # cache_control-wrapped persona system block (it must stay byte-stable)
        for sys_block in req.get("system") or []:
            if isinstance(sys_block, dict) and sys_block.get("cache_control"):
                assert MARKER not in sys_block.get("text", "")


# ─────────────────────────────────────────────────────────────────────────────
# File-level census — every narrative-builder module references the shared
# formatter (a module that rolls its own phase/week context again reds here).
# ─────────────────────────────────────────────────────────────────────────────

NARRATIVE_BUILDER_FILES = [
    "lambdas/ai_calls.py",
    "lambdas/compute/state_of_matthew_lambda.py",
    "lambdas/emails/wednesday_chronicle_lambda.py",
    "lambdas/emails/coach_panel_podcast_lambda.py",
    "lambdas/emails/podcast_script_v2.py",
    "lambdas/web/site_api_ai_lambda.py",
]


@pytest.mark.parametrize("rel_path", NARRATIVE_BUILDER_FILES)
def test_census_module_references_shared_formatter(rel_path):
    src = open(os.path.join(_REPO, rel_path)).read()
    assert "format_experiment_phase_context" in src, f"{rel_path} no longer references the shared phase-context formatter (#1086)"


def test_census_board_followup_path_carries_block():
    # the follow-up handler assembles its own context block — pin the seam
    src = open(os.path.join(_REPO, "lambdas/web/site_api_ai_lambda.py")).read()
    followup_src = src.split("def _handle_board_followup", 1)[1]
    assert "_phase_context_block()" in followup_src
