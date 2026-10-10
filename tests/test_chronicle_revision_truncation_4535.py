"""tests/test_chronicle_revision_truncation_4535.py — the editor pass can no longer ship a cut installment (#4535).

Two installments shipped cut off (wk3 published, wk4 draft): Elena's Haiku revision of
Margaret's notes ran at a flat ``max_tokens=1500`` against a 1,200-1,800-word target, and
nothing read ``stop_reason``, the last sentence or the ``*Week N*`` footer. Pinned here:

  T1  a revision the model stopped at ``max_tokens`` -> the DRAFT ships, and the fallback
      is logged by name (``revision_truncated``) — the issue's acceptance fixture
  T2  the text checks hold even when the stop reason is unknown or ``end_turn``: no
      footer, or prose ending mid-sentence, is a cut installment
  T3  a finished revision (end_turn + terminal sentence + footer) still applies
  T4  the revision runs at a MEASURED budget — enough for the longest revision the
      word-ratio gate accepts on a 1,800-word draft — never the critique's flat 1,500
  T5  end to end through the facade: the revision call's stop_reason reaches the gate,
      and a max_tokens stop returns Elena's draft from ``_run_margaret_edit_pass``
  T6  past-week mode: ``{"week": 4, "dry_run": true}`` names 09-23 -> 09-29 whatever
      today is; a publishing run never resolves a past week
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import wednesday_chronicle_lambda as m  # noqa: E402
from ai import (
    budget_guard as _budget_guard,  # noqa: E402
    margaret_editor_pass as mep,  # noqa: E402
)
from ai.grounded_generation import allowed_numbers as _allowed_numbers  # noqa: E402

DRAFT = (
    '"The Week the Numbers Argued With Him"\n\n'
    "[Weight: 240.1 lbs | Week Grade: avg 71 | T0 Streak: 12 days]\n\n"
    "Matthew logged every meal this week, the way he always does. The scale moved slowly and he let it.\n\n"
    "By Sunday the pattern was plain: the mornings held, the evenings wandered, and he noticed.\n\n"
    "---\n"
    "*Week 8 of The Measured Life*"
)
# What a max_tokens stop looks like: most of the piece, then the reply simply ends mid-clause.
CUT = (
    '"The Week the Numbers Argued With Him"\n\n'
    "[Weight: 240.1 lbs | Week Grade: avg 71 | T0 Streak: 12 days]\n\n"
    "He logged every meal this week. The scale moved slowly and he let it.\n\n"
    "By Sunday the pattern was plain: the mornings held, the evenings wandered, and"
)
FINISHED = DRAFT.replace("Matthew logged every meal this week, the way he always does.", "He logged every meal.")
CRITIQUE = {"craft_score": 4, "works": [], "cut_or_tighten": [], "missing_addition": "", "callback_debt": [], "editors_note": ""}
ALLOWED = _allowed_numbers(DRAFT)


class _Log:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    def info(self, *a, **k):
        pass


# ── T1: the acceptance fixture ────────────────────────────────────────────────


def test_a_revision_stopped_at_max_tokens_ships_the_draft_and_logs_the_fallback(monkeypatch):
    log = _Log()
    monkeypatch.setattr(mep, "logger", log)
    text, applied, reason = mep.apply_revision(DRAFT, CRITIQUE, ALLOWED, revise_fn=lambda s, u: (CUT, "max_tokens"))
    assert (text, applied) == (DRAFT, False)
    assert reason == "revision_truncated:max_tokens"
    assert any("revision_truncated" in w and "max_tokens" in w for w in log.warnings), log.warnings


def test_max_tokens_is_a_cut_even_when_the_text_happens_to_look_finished():
    # the model's own verdict outranks a text that looks complete
    text, applied, reason = mep.apply_revision(DRAFT, CRITIQUE, ALLOWED, revise_fn=lambda s, u: (FINISHED, "max_tokens"))
    assert (text, applied, reason) == (DRAFT, False, "revision_truncated:max_tokens")


# ── T2: the text checks, independent of the stop reason ──────────────────────


def test_a_revision_missing_the_week_footer_is_refused_even_on_end_turn():
    no_footer = FINISHED.split("\n---\n")[0]
    text, applied, reason = mep.apply_revision(DRAFT, CRITIQUE, ALLOWED, revise_fn=lambda s, u: (no_footer, "end_turn"))
    assert (text, applied, reason) == (DRAFT, False, "revision_truncated:end_turn")


def test_a_bare_string_revision_ending_mid_sentence_is_refused():
    # a legacy revise_fn that returns only text: stop reason unknown, the text checks still run
    text, applied, reason = mep.apply_revision(DRAFT, CRITIQUE, ALLOWED, revise_fn=lambda s, u: CUT)
    assert (text, applied, reason) == (DRAFT, False, "revision_truncated:None")


def test_completeness_findings_name_each_failure():
    assert mep.revision_completeness_findings(FINISHED, "end_turn") == []
    f = mep.revision_completeness_findings(CUT, "max_tokens")
    assert any("stop_reason=max_tokens" in x for x in f)
    assert any("footer" in x for x in f)
    assert any("mid-sentence" in x for x in f)


# ── T3: a finished revision still applies ─────────────────────────────────────


def test_a_finished_revision_still_applies():
    text, applied, reason = mep.apply_revision(DRAFT, CRITIQUE, ALLOWED, revise_fn=lambda s, u: (FINISHED, "end_turn"))
    assert (text, applied, reason) == (FINISHED, True, "revised")


# ── T4: the measured budget ───────────────────────────────────────────────────


def test_the_revision_budget_is_measured_and_covers_an_1800_word_installment():
    draft_1800 = " ".join(["word"] * 1800)
    budget = mep.revision_max_tokens(draft_1800)
    # the longest revision the ratio gate accepts, at ~1.33 tokens/word, must fit
    assert budget >= int(1800 * mep.MAX_WORD_RATIO * 1.33)
    assert budget > 1500
    assert mep.revision_max_tokens("") == mep.REVISION_MIN_TOKENS
    assert mep.revision_max_tokens(" ".join(["w"] * 100000)) == mep.REVISION_MAX_TOKENS


# ── T5: end to end through the facade ─────────────────────────────────────────


def _wire_pass(monkeypatch, revision_reply, seen):
    from common import retry_utils

    monkeypatch.setattr(_budget_guard, "allow", lambda feature: True)
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", False)
    monkeypatch.setattr(m, "_due_callback_promises", lambda week_num, limit=5: [])
    monkeypatch.setattr(m, "_margaret_last_note_date", lambda: "2026-10-01")
    monkeypatch.setattr(
        m, "_margaret_haiku_call", lambda system, user: '{"craft_score": 4, "cut_or_tighten": [], "callback_debt": [], "editors_note": ""}'
    )

    def _raw(body, timeout=55):
        seen["body"] = body
        text, stop = revision_reply
        return {"content": [{"type": "text", "text": text}], "stop_reason": stop}

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _raw)


def test_the_live_pass_ships_the_draft_when_the_revision_hits_max_tokens(monkeypatch):
    seen = {}
    _wire_pass(monkeypatch, (CUT, "max_tokens"), seen)
    out = m._run_margaret_edit_pass(DRAFT, 8, "2026-10-06", "ELENA PROMPT", ALLOWED)
    assert out == DRAFT
    assert seen["body"]["max_tokens"] == mep.revision_max_tokens(DRAFT) > 1500
    assert seen["body"]["model"] == m.AI_MODEL_HAIKU
    assert seen["body"]["system"][0]["text"] == "ELENA PROMPT"


def test_the_live_pass_applies_a_finished_revision(monkeypatch):
    seen = {}
    _wire_pass(monkeypatch, (FINISHED, "end_turn"), seen)
    assert m._run_margaret_edit_pass(DRAFT, 8, "2026-10-06", "ELENA PROMPT", ALLOWED) == FINISHED


# ── T6: past-week mode ────────────────────────────────────────────────────────


def test_week_4_dry_run_names_the_season_week_whatever_the_run_date():
    from content import story_dossier

    end = m._rehearsal_week_end({"dry_run": True, "week": 4})
    wk = next(w for w in story_dossier.season_weeks(through=end) if w["end"] == end)
    assert wk["week"] == 4
    assert (wk["start"], wk["end"]) == ("2026-09-23", "2026-09-29")


def test_past_week_mode_is_rehearsal_only_and_rejects_nonsense():
    assert m._rehearsal_week_end({"week": 4}) is None  # a publishing run never names a past week
    assert m._rehearsal_week_end({"dry_run": True, "week": 0}) is None
    assert m._rehearsal_week_end({"dry_run": True, "week": "four"}) is None
    assert m._rehearsal_week_end({"dry_run": True, "week": True}) is None
    assert m._rehearsal_week_end({"dry_run": True, "week": 4, "desk_week_end": "2026-09-22"}) == "2026-09-22"
    assert m._rehearsal_week_end({"dry_run": True}) is None
