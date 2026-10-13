"""tests/test_chronicle_rehearsal_envelope_4865.py — a rehearsed past week's envelope, recap and length check (#4865).

The 2026-10-12 17:02Z ``{"week": 4, "dry_run": true}`` rehearsal (request 139be759) logged three warnings that were
read as "the rehearsal's current-window gather is withheld, so the fields are null". The code read otherwise: the
envelope's three numbers come from the Story Desk's MACHINE HEADER (``story_pipeline.stats_line``), which is
``Day 18 to Day 24 · 309.4 lbs (-1.6 this week) · 5 training sessions`` — a weight and no grade or streak — so every
desk-written week (live or rehearsed) failed the legacy schema. Pinned here with the exact log strings:

  E1  the week-4 desk envelope validates against the desk schema; the weight is read from THAT week's header
  E2  the legacy schema still rejects that envelope (so the desk schema, not a weaker legacy one, is what passes)
      and a wrongly typed number in the desk's envelope is still an error
  E3  end to end through ``_handler_core``: no ``[#1385]`` warning on a week-4 rehearsal
  R1  the recap guard names the cited vital in the rejection line (and still rejects)
  L1  the AI-3 length warning names the writer and the ceiling; a 6,530-char desk post no longer warns
  L2  the legacy writer keeps its 5,000 ceiling
No test here calls Bedrock or any AWS API.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_chronicle_recap as recap_t  # noqa: E402
import test_chronicle_rehearsal_window_4535 as sib  # noqa: E402
from content import chronicle_schema as cs  # noqa: E402

m = sib.m

WEEK4_HEADER = "Day 18 to Day 24 · 309.4 lbs (-1.6 this week) · 5 training sessions"


def _desk_md(chars=6530):
    body = "He walked the long loop on Tuesday and wrote it down. " * ((chars // 54) + 1)
    text = f'"Day Twenty-Four"\n\n[{WEEK4_HEADER}]\n\n{body}'[:chars]
    return text[: text.rindex(".") + 1]  # a whole last sentence — AI-3 blocks a truncated tail


def _wire(monkeypatch, raw):
    seen, log = sib._wire(monkeypatch)
    from content import story_pipeline

    live = story_pipeline.live_week

    def _live(*a, **k):
        out = live(*a, **k)
        out["stats_line"] = WEEK4_HEADER
        out["raw_installment"] = raw
        return out

    monkeypatch.setattr(story_pipeline, "live_week", _live)
    return seen, log


def test_e1_week_4_desk_envelope_validates_and_reads_that_weeks_weight():
    title, stats_line, body = m.parse_installment(_desk_md())
    env = cs.desk_installment_from_stats(title, cs.stats_fields(stats_line), body)
    assert env["weight_lbs"] == 309.4 and "week_grade" not in env and "t0_streak_days" not in env
    assert cs.validate_installment(env, cs.DESK_INSTALLMENT_SCHEMA) == []


def test_e2_legacy_schema_still_rejects_it_and_a_wrong_type_is_still_an_error():
    title, stats_line, body = m.parse_installment(_desk_md())
    legacy = cs.installment_from_stats(title, cs.parse_stats_line(stats_line), body)
    errs = cs.validate_installment(legacy)
    assert any("weight_lbs" in e for e in errs) and any("week_grade" in e for e in errs) and any("t0_streak_days" in e for e in errs)
    bad = {"title": "t", "body_markdown": "b", "weight_lbs": "309.4"}
    assert cs.validate_installment(bad, cs.DESK_INSTALLMENT_SCHEMA) == ["field 'weight_lbs': expected number, got str"]
    assert cs.validate_installment({"title": "t"}, cs.DESK_INSTALLMENT_SCHEMA) == ["missing required field: 'body_markdown'"]


def test_e3_a_week_4_rehearsal_logs_no_envelope_warning(monkeypatch):
    _seen, log = _wire(monkeypatch, _desk_md())
    out = m._handler_core({"dry_run": True, "week": 4}, None)
    assert json.loads(out["body"])["status"] == "dry_run"
    assert not [line for line in log.lines if "[#1385] installment envelope" in line], log.lines


def test_r1_the_recap_rejection_names_the_cited_vital(monkeypatch):
    lines = []

    class _L(sib._Log):
        def warning(self, msg, *a, **k):
            lines.append(str(msg) % a if a else str(msg))

    monkeypatch.setattr(recap_t.chron, "logger", _L())
    story = "Three rest days rewarded Matthew with four mornings at 98% recovery and a scale reading of 308.9 pounds."
    recap_t._mock_llm(monkeypatch, {"story_so_far": story, "recent_beats": [], "where_we_are_now": "", "threads_to_watch": []})
    assert recap_t.chron.build_recap(recap_t._data()) is None
    rejected = [line for line in lines if "story_so_far cites a raw vital" in line]
    assert rejected and "'98%'" in rejected[0], lines


def test_l1_the_ai3_warning_names_the_writer_and_a_desk_post_does_not_warn(monkeypatch):
    _seen, log = _wire(monkeypatch, _desk_md(6530))
    m._handler_core({"dry_run": True, "week": 4}, None)
    assert not [line for line in log.lines if "[AI-3] Chronicle warnings" in line], log.lines
    _seen, log = _wire(monkeypatch, _desk_md(9500))
    m._handler_core({"dry_run": True, "week": 4}, None)
    warned = [line for line in log.lines if "[AI-3] Chronicle warnings" in line]
    assert warned and "writer=story_desk" in warned[0] and "max_length=9000" in warned[0], log.lines


def test_l2_the_legacy_writer_keeps_its_ceiling():
    assert m.AI3_LEGACY_MAX_CHARS == 5_000 and m.AI3_DESK_MAX_CHARS > 6530
