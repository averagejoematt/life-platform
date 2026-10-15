"""tests/test_chronicle_rehearsal_window_4535.py — a named-week rehearsal carries ONLY that week (#4535 box 2).

The owner-approved ``{"week": 4, "dry_run": true}`` invoke (2026-10-11) built week 4, but the log first said
``Gathering data: 2026-10-03 -> 2026-10-09`` and ``Data packet: … Week 5``. The code read: the desk's writer is
``story_pipeline.live_week(table, week_end)`` — it never receives the legacy packet — but the handler still stamped
the CURRENT window's end date on the rehearsal's output (``date``, the recap's meta, the confidence day count),
checked the CURRENT week's row for idempotency, and would have fallen back to the legacy writer (the current week)
if the desk declined. Pinned here, end to end through ``_handler_core`` with every AWS / model touch stubbed:

  R1  the desk receives ONLY ``(table, "2026-09-29")`` and the rehearsal reports week 4 / 2026-09-29 — no field
      carries the legacy window's 2026-10-09 or its week 5 (mutation control: ``date_str = data["dates"]["end"]``)
  R2  the legacy packet is never handed to a model, and its log line says it is the current window, not the week
  R3  a desk that declines the named week returns ``rehearsal_not_built`` — never the legacy writer's current week
  R4  the current window's stored row does not refuse a past-week rehearsal (idempotency is not consulted)
  R5  a publishing run is unchanged: its date is the gather window's end
No test here calls Bedrock or any AWS API.
"""

import json
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
from ai import budget_guard as _budget_guard  # noqa: E402

LEGACY_END = "2026-10-09"  # the current window the legacy gather covered on 2026-10-11
WEEK4_END = "2026-09-29"
LEGACY_PACKET = "LEGACY-PACKET-WEEK5 2026-10-03 -> 2026-10-09 weight 999.9"
DESK_MD = (
    '"Day Twenty-Four"\n\n'
    "[Week 4 | 2026-09-23 to 2026-09-29]\n\n"
    "He walked the long loop on Tuesday and wrote it down. The week held together.\n\n"
    "The mornings were steady and the evenings were quieter than the week before. He cooked at home most nights, "
    "kept the training log honest, and noticed that the hard days were the ones he had planned least.\n\n"
    "---\n"
    "*Week 4 of The Measured Life*"
)


class _Table:
    def query(self, **kwargs):
        return {"Items": []}


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(str(msg))

    warning = error = info


def _wire(monkeypatch, *, desk_returns=True, existing=None, craft=()):
    from content import story_pipeline
    from health import whole_life_context

    seen = {"desk_calls": [], "model_calls": 0, "recap_meta": None}

    def _live_week(*args, **kwargs):
        seen["desk_calls"].append((args, {k: v for k, v in kwargs.items() if k != "log"}))
        if not desk_returns:
            return None
        return {
            "week": 4,
            "title": "Day Twenty-Four",
            "stats_line": "Week 4 | 2026-09-23 to 2026-09-29",
            "raw_installment": DESK_MD,
            "budget": {},
            "episode": {},
            "ledger": {},
            "findings": {"post": [], "episode": []},
            "craft_findings": list(craft),
        }

    def _model(*a, **k):
        seen["model_calls"] += 1
        seen["model_input"] = a
        return DESK_MD

    def _recap(data, new_installment_md=None, new_meta=None):
        seen["recap_meta"] = new_meta
        return {"as_of": (new_meta or {}).get("date"), "recent_beats": []}

    log = _Log()
    monkeypatch.setattr(m, "logger", log)
    monkeypatch.setattr(m, "table", _Table())
    monkeypatch.setenv("STORY_DESK", "on")
    monkeypatch.setattr(_budget_guard, "allow", lambda feature: True)
    monkeypatch.setattr(
        m,
        "gather_chronicle_data",
        lambda: {"dates": {"start": "2026-10-03", "end": LEGACY_END}, "prev_installments": [], "profile": {}},
    )
    monkeypatch.setattr(m, "_existing_installment", lambda date_str: existing)
    monkeypatch.setattr(m, "build_data_packet", lambda data: (LEGACY_PACKET, 5))
    monkeypatch.setattr(m, "_load_engagement_signal", lambda: {})
    monkeypatch.setattr(m, "_elena_notebook_block", lambda week_num: "")
    monkeypatch.setattr(m, "_build_elena_prompt_from_config", lambda: "ELENA PROMPT")
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", False)
    monkeypatch.setattr(m, "_HAS_SHARE_KIT", False)
    monkeypatch.setattr(whole_life_context, "fetch_full_installment_archive", lambda *a, **k: [])
    monkeypatch.setattr(m._store, "read_raw_cache", lambda *a, **k: None)
    monkeypatch.setattr(m, "call_anthropic", _model)
    # a mutant that reaches the legacy path must still never touch Bedrock or CloudWatch
    monkeypatch.setattr(m, "_run_margaret_edit_pass", lambda raw, *a, **k: raw)
    monkeypatch.setattr(m, "installment_grounding_findings", lambda *a, **k: [])
    monkeypatch.setattr(m, "build_recap", _recap)
    monkeypatch.setattr(story_pipeline, "live_week", _live_week)
    return seen, log


def test_a_week_4_rehearsal_reports_week_4_and_its_window_only(monkeypatch):
    seen, _log = _wire(monkeypatch)
    out = m._handler_core({"dry_run": True, "week": 4}, None)
    body = json.loads(out["body"])

    # the desk's writer got the table and the rehearsed week end — nothing from the legacy packet
    assert len(seen["desk_calls"]) == 1
    args, kwargs = seen["desk_calls"][0]
    assert args[1:] == (WEEK4_END,) and kwargs == {}
    assert seen["model_calls"] == 0  # the legacy packet never reached a model

    assert out["statusCode"] == 200 and body["status"] == "dry_run"
    assert (body["week"], body["date"], body["title"]) == (4, WEEK4_END, "Day Twenty-Four")
    assert seen["recap_meta"] == {"date": WEEK4_END, "week_number": 4, "title": "Day Twenty-Four"}
    flat = json.dumps(body)
    assert LEGACY_END not in flat and "LEGACY-PACKET" not in flat and "999.9" not in flat


def test_the_legacy_gather_is_labelled_as_the_current_window_in_a_rehearsal(monkeypatch):
    _seen, log = _wire(monkeypatch)
    m._handler_core({"dry_run": True, "week": 4}, None)
    assert not any(line.startswith("Data packet:") for line in log.lines)  # the line the 10-11 run was read by
    labelled = [line for line in log.lines if line.startswith("[#4535] legacy data packet:")]
    assert labelled and "current window Week 5" in labelled[0] and WEEK4_END in labelled[0]
    assert any(line.startswith("[#4535] rehearsal names the week ending 2026-09-29") for line in log.lines)


def test_a_declined_rehearsal_never_falls_back_to_the_current_week(monkeypatch):
    seen, _log = _wire(monkeypatch, desk_returns=False)
    out = m._handler_core({"dry_run": True, "week": 4}, None)
    body = json.loads(out["body"])
    assert out["statusCode"] == 422
    assert body["status"] == "rehearsal_not_built" and body["week_end"] == WEEK4_END
    assert seen["model_calls"] == 0


def test_the_current_weeks_stored_row_does_not_refuse_a_past_week_rehearsal(monkeypatch):
    seen, _log = _wire(monkeypatch, existing={"status": "published", "week_number": 5})
    out = m._handler_core({"dry_run": True, "week": 4}, None)
    assert json.loads(out["body"])["status"] == "dry_run"
    assert len(seen["desk_calls"]) == 1


def test_a_publishing_run_keeps_the_gather_windows_date(monkeypatch):
    # a plain dry run (no named week) is today's window, exactly as before
    seen, log = _wire(monkeypatch)
    from content import story_pipeline

    calls = []

    def _today(table, week_end, *extra, log=None):
        calls.append((week_end,) + extra)
        return {
            "week": 5,
            "title": "T",
            "stats_line": "s",
            "raw_installment": DESK_MD.replace("Week 4 of", "Week 5 of"),
            "budget": {},
            "episode": {},
            "ledger": {},
            "findings": {},
        }

    monkeypatch.setattr(story_pipeline, "live_week", _today)
    body = json.loads(m._handler_core({"dry_run": True}, None)["body"])
    assert calls == [(LEGACY_END,)] and body["date"] == LEGACY_END and body["week"] == 5
    assert any(line.startswith("Data packet:") for line in log.lines)


def test_a_craft_finding_holds_the_installment_and_a_clean_one_publishes(monkeypatch):
    """#4545 box 3: story_craft's residual finding on the final desk texts holds the week (nothing mailed, stored or
    returned as the installment); the same week with no craft finding goes through. Mutation control: drop the
    ``craft_findings`` list from the desk's return (or the handler's hold) and the first assertion goes red."""
    _seen, _log = _wire(monkeypatch, craft=["opens on a date, not the day count"])
    held = m._handler_core({"dry_run": True, "week": 4}, None)
    body = json.loads(held["body"])
    assert body["status"] == "craft_hold" and body["findings"] == ["opens on a date, not the day count"]
    _seen, _log = _wire(monkeypatch)
    assert json.loads(m._handler_core({"dry_run": True, "week": 4}, None)["body"])["status"] == "dry_run"
