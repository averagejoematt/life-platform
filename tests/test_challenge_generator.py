"""tests/test_challenge_generator.py — #1118: the challenge generator emits the
full protocols-grammar hypothesis contract on every new challenge.

Challenges already persisted `source_detail` (why-now) and `verification_method`
(measured-by); #1118 adds `hoped_outcome` — the falsifiable expected result —
so new challenges carry the same contract as supplements (#1116/#1148) and
experiments from birth. This file is the regression guard the issue demands:

  • the generation prompt DEMANDS hoped_outcome (system schema + rules)
  • store_challenge PERSISTS hoped_outcome on new challenges
  • a model response that omits it stores honest-empty "" (ADR-104 — the render
    shows nothing, never placeholder prose)
  • the phase-context grounding block (#1138) rides the USER prompt, and the
    cache_control-wrapped system prompt stays byte-stable (COST-OPT-2)

No real Bedrock, DDB, S3, or HTTP calls anywhere in this file.
"""

import os
import sys

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pytest  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from intelligence import challenge_generator_lambda as chg  # noqa: E402

CANDIDATE = {
    "name": "No Eating After 8pm",
    "description": "Late-night snacking flagged 6 times in 14 days of journal entries.",
    "source": "journal_mining",
    "source_detail": "avoidance_flag: late_night_snacking ×6 in 14d",
    "domain": "nutrition",
    "difficulty": "moderate",
    "duration_days": 7,
    "protocol": "Kitchen closed after 8pm; herbal tea allowed.",
    "success_criteria": "6 of 7 evenings without eating after 8pm",
    "hoped_outcome": "Fewer late-night snacking flags in the journal by the end of the week — honestly small, one week is one data point.",
    "tags": ["nutrition", "evening"],
    "verification_method": "self_report",
    "metric_targets": {},
}


@pytest.fixture()
def fake_table(monkeypatch):
    table = FakeDdbTable()
    monkeypatch.setattr(chg, "table", table)
    return table


class TestPromptContract:
    def test_system_prompt_demands_hoped_outcome(self):
        # The required-fields rule AND the JSON schema example both name it —
        # the model can't ship a challenge without stating its hypothesis.
        assert chg.SYSTEM_PROMPT.count("hoped_outcome") >= 2

    def test_system_prompt_keeps_why_now_and_measured_by_fields(self):
        # The pre-existing halves of the protocols grammar stay demanded.
        assert "source_detail" in chg.SYSTEM_PROMPT
        assert "verification_method" in chg.SYSTEM_PROMPT


class TestStoreChallenge:
    def test_new_challenge_persists_hoped_outcome(self, fake_table):
        challenge_id = chg.store_challenge(dict(CANDIDATE))
        assert challenge_id
        assert len(fake_table.puts) == 1
        item = fake_table.puts[0]
        assert item["hoped_outcome"] == CANDIDATE["hoped_outcome"]
        # the why-now / measured-by pair persists alongside it
        assert item["source_detail"] == CANDIDATE["source_detail"]
        assert item["verification_method"] == "self_report"

    def test_missing_hoped_outcome_stores_honest_empty(self, fake_table):
        legacy = {k: v for k, v in CANDIDATE.items() if k != "hoped_outcome"}
        assert chg.store_challenge(legacy)
        item = fake_table.puts[0]
        # ADR-104: absent means empty string — the render shows nothing, and no
        # placeholder prose is ever invented server-side.
        assert item["hoped_outcome"] == ""

    def test_duplicate_challenge_not_rewritten(self, fake_table):
        assert chg.store_challenge(dict(CANDIDATE))
        assert chg.store_challenge(dict(CANDIDATE)) is None
        assert len(fake_table.puts) == 1


class TestPhaseContextPlacement:
    def test_generation_prompt_carries_phase_block(self):
        # #1138: hoped_outcome is AI-written narrative — the writer must know
        # what day/phase it is (a Day-2 challenge can't hope for a 30-day trend).
        # The canonical registry lives in tests/test_phase_context_coverage.py;
        # this pins the same contract next to the generator's own tests.
        import ai_context

        prompt = chg.build_generation_prompt({})
        assert ai_context.PHASE_CONTEXT_MARKER in prompt

    def test_cached_system_prompt_stays_byte_stable(self):
        # COST-OPT-2: SYSTEM_PROMPT ships under cache_control — the daily-
        # changing phase block must never ride it.
        import ai_context

        assert ai_context.PHASE_CONTEXT_MARKER not in chg.SYSTEM_PROMPT
