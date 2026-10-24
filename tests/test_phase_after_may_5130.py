"""tests/test_phase_after_may_5130.py — the May date ends phase one; it is never a finish line (#5130, epic #5120).

# premerge-gate: a repo-shape ratchet — sweeps the charter, the charter prompt guide, the coach context, the coaching skills and every config/coaches/*.json persona for finish-line framing of the target date

Holds (each test iterates its whole set and reports every offender):

  1. THE CHARTER SAYS SO: `governing_goal.target_date_role` and `phase_after_may.target_date_is` name the date a
     milestone that ends phase one; `phase_after_may.plan_location` names where the post-deadline plan lives
     (`phase_after_may.plan`, null until the owner writes it); `plan_prompt` dates the prompt and its dead-man.
  2. NO FINISH-LINE WORDING in the charter's text, the reading guide that rides with it, the coach context, the
     coaching skills or the coach personas — a finish-line phrase is allowed only when it is negated ("not a finish
     line"). Mutation control: the pre-#5130 May-frame line ("holds the band to that date", no phase clause) and a
     planted "the finish line in May" are both caught by the same sweep function.
  3. THE MAY FRAME the coach reads says phase one ends there and whether the plan after it is written.
  4. THE DATED PROMPT: `training.phase_after_may.calibration_row` is ok before the prompt window, due (one prompt,
     a fixed key) inside it, at the dead-man from `dead_man_weeks_before_target`, ok once a plan is written, unknown
     when the charter cannot be read — derived from the charter's own weeks, never a pinned date, and with no clock.
  5. WIRED: `calibration_cadence.read` carries the row, so the coach-event trigger sends the prompt and the
     calibration dead-man alert sends its fixed text.
"""

from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from training import (  # noqa: E402
    calibration_cadence as cc,  # noqa: E402
    coach_context,
    phase_after_may,
    training_charter as tc,
    training_charter_prompt as tcp,  # noqa: E402
)

FINISH = re.compile(
    r"\bfinish[\s-]?line\b|\bthe\s+finish\b|\bcross(?:es|ing)?\s+the\s+(?:finish\s+)?line\b|\bfinal\s+(?:day|weigh[\s-]?in|week)\b"
    r"|\bthe\s+end\s+of\s+the\s+(?:experiment|journey|plan|road|programme|program)\b|\b(?:it'?s|it\s+is|the\s+work\s+is)\s+(?:all\s+)?(?:over|done)\b"
    r"|\bonce\s+(?:may|the\s+(?:target\s+date|deadline))\s+(?:is\s+over|has\s+passed)\b",
    re.I,
)
NEGATED = re.compile(r"\b(?:not|never|no|isn't|nor|rather\s+than)\b[^.;:\n]{0,24}$", re.I)

SKILLS = (
    ".claude/skills/coach-session/SKILL.md",
    ".claude/skills/daily-debrief/SKILL.md",
    ".claude/skills/speak-to-coaches/SKILL.md",
    ".claude/skills/training-review/SKILL.md",
    "docs/coaching/COACH_SESSION.md",
)


@pytest.fixture(autouse=True)
def _public_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, f"{path}[{i}]")


def finish_line_hits(label: str, text: str) -> list[str]:
    """Every un-negated finish-line phrase in `text`, as `label: …phrase…`."""
    out = []
    for m in FINISH.finditer(text):
        if NEGATED.search(text[max(0, m.start() - 40) : m.start()]):
            continue
        out.append(f"{label}: …{text[max(0, m.start() - 50) : m.end() + 30]!r}")
    return out


def _sweep() -> list[str]:
    hits: list[str] = []
    charter = json.load(open(os.path.join(_REPO, "config", "training_charter.json"), encoding="utf-8"))
    for path, s in _strings({k: v for k, v in charter.items() if k != "change_log"}):
        hits += finish_line_hits(f"config/training_charter.json {path}", s)
    for name, s in [("PREAMBLE", tcp.PREAMBLE), ("RULES", tcp.RULES), *tcp.SECTION_GUIDE.items()]:
        hits += finish_line_hits(f"training_charter_prompt {name}", s)
    for rel in ("lambdas/training/coach_context.py", "lambdas/training/phase_after_may.py", *SKILLS):
        p = os.path.join(_REPO, rel)
        if os.path.exists(p):
            hits += finish_line_hits(rel, open(p, encoding="utf-8").read())
    for p in sorted(glob.glob(os.path.join(_REPO, "config", "coaches", "*.json"))):
        hits += finish_line_hits(os.path.relpath(p, _REPO), open(p, encoding="utf-8").read())
    return hits


def test_the_charter_names_the_date_a_milestone_and_where_the_plan_after_it_lives():
    gg, pam = tc.charter_value("governing_goal"), tc.charter_value("phase_after_may")
    assert "phase one" in gg["target_date_role"] and "never a finish line" in gg["target_date_role"]
    assert "milestone" in pam["target_date_is"] and "never a finish line" in pam["target_date_is"]
    assert "plan" in pam and pam["plan"] is None, "the post-deadline plan is unwritten: null, never a placeholder"
    assert pam["plan_location"].startswith("phase_after_may.plan"), "the location is named in the charter"
    pp = pam["plan_prompt"]
    assert pp["weeks_before_target"] > pp["dead_man_weeks_before_target"] > 0, "the prompt comes before its dead-man, both before the date"
    assert "phase_after_may" in tc.NEVER_PUBLISHED and "governing_goal" in tc.NEVER_PUBLISHED, "owner-only, both"
    guide = tcp.SECTION_GUIDE["governing_goal"] + tcp.SECTION_GUIDE["phase_after_may"]
    assert "target_date_role" in guide and "plan_location" in guide and "finish line" in guide


def test_no_finish_line_framing_in_the_charter_its_guide_or_the_coach_prose():
    hits = _sweep()
    assert not hits, "finish-line framing of the target date (#5130) — say milestone / phase one / what follows:\n" + "\n".join(hits)
    # mutation control: the sweep's own function catches the shapes it exists for, and lets the negated one through
    assert finish_line_hits("probe", "May is the finish line; after that it's over")
    assert finish_line_hits("probe", "hold the band to the end of the experiment")
    assert not finish_line_hits("probe", "the date is a milestone, not a finish line")
    assert not finish_line_hits("probe", "consistency is the goal, not a finish line.")


def test_the_may_frame_says_phase_one_ends_there_and_whether_the_plan_after_it_is_written(monkeypatch):
    frame = coach_context.may_frame("2026-10-23")
    assert frame is not None
    line = frame["line"]
    assert "ends phase one" in line and "not a finish line" in line and "not written yet" in line, line
    assert "to that date." not in line, "the pre-#5130 ending (the date as the end of the work)"
    real = tc.charter_value

    def written(path, default=None):
        return {"week_1": "maintenance"} if path == "phase_after_may.plan" else real(path, default)

    monkeypatch.setattr(tc, "charter_value", written)
    assert "is in the charter's phase_after_may.plan" in coach_context.may_frame("2026-10-23")["line"]


def _reader(plan=None, target=None, lead=None, dead=None):
    vals = {
        "governing_goal.target_date": target or tc.charter_value("governing_goal.target_date"),
        "phase_after_may.plan_prompt.weeks_before_target": (
            lead if lead is not None else tc.charter_value("phase_after_may.plan_prompt.weeks_before_target")
        ),
        "phase_after_may.plan_prompt.dead_man_weeks_before_target": (
            dead if dead is not None else tc.charter_value("phase_after_may.plan_prompt.dead_man_weeks_before_target")
        ),
        "phase_after_may.plan": plan,
    }
    return vals.get


def test_the_dated_prompt_and_its_dead_man_follow_the_charters_weeks():
    target = _dt.date.fromisoformat(tc.charter_value("governing_goal.target_date"))
    lead = tc.charter_value("phase_after_may.plan_prompt.weeks_before_target")
    dead = tc.charter_value("phase_after_may.plan_prompt.dead_man_weeks_before_target")
    due, deadman = target - _dt.timedelta(weeks=lead), target - _dt.timedelta(weeks=dead)
    cases = [
        (due - _dt.timedelta(days=1), cc.OK),
        (due, cc.DUE),
        (deadman - _dt.timedelta(days=1), cc.DUE),
        (deadman, cc.MISSED_2),
        (target + _dt.timedelta(days=30), cc.MISSED_2),
    ]
    wrong = []
    for day, want in cases:
        row = phase_after_may.calibration_row(day.isoformat())
        if row["state"] != want:
            wrong.append(f"{day}: {row['state']} != {want}")
        if row["cycle_start"] != due.isoformat() or row["prompt_key"] != cc.prompt_key("post_may_plan", due.isoformat()):
            wrong.append(f"{day}: the prompt key moved ({row.get('prompt_key')}) — one prompt per plan, not per day")
        if want == cc.DUE and not (row["prompt"] and "not a finish line" in row["prompt"] and "phase_after_may.plan" in row["prompt"]):
            wrong.append(f"{day}: the prompt does not name the milestone and the plan's place: {row['prompt']!r}")
        if want == cc.MISSED_2 and not (row.get("alert") and row["prompt"] is None):
            wrong.append(f"{day}: the dead-man carries no fixed alert text")
    assert not wrong, "\n".join(wrong)
    written = phase_after_may.calibration_row(deadman.isoformat(), _reader(plan={"phase": "maintenance"}))
    assert written["state"] == cc.OK and written["prompt"] is None, "a written plan clears the prompt and the dead-man"
    unknown = phase_after_may.calibration_row(due.isoformat(), lambda path: None)
    assert unknown["state"] == cc.UNKNOWN, "no target date or weeks: unknown, never a guessed date"
    assert phase_after_may.calibration_row("not-a-day")["state"] == cc.UNKNOWN


class _EmptyTable:
    def query(self, **kw):
        return {"Items": []}

    def get_item(self, **kw):
        return {}


def test_the_row_rides_the_calibration_cadence_into_the_prompt_and_the_dead_man_alert():
    from coach import calibration_deadman_alert as cda

    target = _dt.date.fromisoformat(tc.charter_value("governing_goal.target_date"))
    lead = tc.charter_value("phase_after_may.plan_prompt.weeks_before_target")
    dead = tc.charter_value("phase_after_may.plan_prompt.dead_man_weeks_before_target")
    in_window = (target - _dt.timedelta(weeks=lead) + _dt.timedelta(days=3)).isoformat()
    block = cc.read(_EmptyTable(), in_window)
    row = block["kinds"]["post_may_plan"]
    assert row["state"] == cc.DUE and row in cc.prompts_due(block), "the dated prompt is one of the owner-channel prompts"
    late = cc.read(_EmptyTable(), (target - _dt.timedelta(weeks=dead)).isoformat())
    assert "post_may_plan" in cc.deadman_kinds(late)
    alerts = {a["kind"]: a for a in cda.due(late)}
    assert alerts["post_may_plan"]["event_id"] == cc.deadman_key("post_may_plan", row["cycle_start"])
    assert "phase_after_may.plan" in alerts["post_may_plan"]["text"]
