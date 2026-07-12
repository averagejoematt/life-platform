"""tests/test_panelcast_repair.py — the podcast no-touch contract (#1170/#1171/#1172, ADR-135).

Offline coverage of the three layers: deterministic seam detection + targeted repair
(then the FULL unchanged gate — repair can never bypass it), the intro-path revision
loop that feeds the judge's exact failure text back to the writer, the grader
calibration agreement (_QA_MAX_CONSECUTIVE vs the judge rubrics), and the bounded
attempt budget with the one-email needs-human escalation on exhaustion.
"""

import json
import logging
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

from emails import (
    coach_panel_podcast_lambda as panel,  # noqa: E402
    panelcast_qa as qa,  # noqa: E402
    panelcast_repair as repair,  # noqa: E402
)

_LOG = logging.getLogger("test-panelcast-repair")


def _invoke_returning(payload):
    """A fake bedrock_client.invoke returning `payload` as the model's JSON text."""

    def _invoke(body, model_name=None):
        return {"content": [{"text": json.dumps(payload)}]}

    return _invoke


def _invoke_capturing(payload, calls):
    def _invoke(body, model_name=None):
        calls.append(body)
        return {"content": [{"text": json.dumps(payload)}]}

    return _invoke


# ── seam detection shares the gate's own primitives (#1170) ───────────────────


def test_structural_seams_matches_gate_detection():
    # 3-in-a-row (over _QA_MAX_CONSECUTIVE=2) → a seam, exactly where the craft check fails.
    over_run = [
        {"speaker": "elena_voss", "line": "Open."},
        {"speaker": "eli_marsh", "line": "One."},
        {"speaker": "eli_marsh", "line": "Two."},
        {"speaker": "eli_marsh", "line": "Three."},
        {"speaker": "elena_voss", "line": "Close."},
    ]
    assert qa.structural_seams(over_run) == [(1, 3)]
    assert any("in a row" in f for f in qa._craft_check(over_run))
    # A 2-run holding a dangling question → a seam, exactly where continuity fails.
    dangling = [
        {"speaker": "elena_voss", "line": "Open."},
        {"speaker": "eli_marsh", "line": "Fine."},
        {"speaker": "elena_voss", "line": "So convince me this isn't theater?"},
        {"speaker": "elena_voss", "line": "Moving on."},
        {"speaker": "eli_marsh", "line": "Close."},
    ]
    assert qa.structural_seams(dangling) == [(2, 3)]
    assert qa._continuity_check(dangling)
    # A benign 2-run (no question/challenge) is NOT a seam — and not a gate failure.
    benign = [
        {"speaker": "elena_voss", "line": "Open."},
        {"speaker": "eli_marsh", "line": "One thought."},
        {"speaker": "eli_marsh", "line": "And a second beat."},
        {"speaker": "elena_voss", "line": "Close."},
    ]
    assert qa.structural_seams(benign) == []
    assert qa._craft_check(benign) == []


# ── targeted repair: alternating, within caps, gate-clean after (#1170) ───────

_SEEDED = [
    {"speaker": "elena_voss", "line": "Here's the hook that got me."},
    {"speaker": "eli_marsh", "line": "Point one about the platform."},
    {"speaker": "eli_marsh", "line": "Point two, and honestly the bigger one."},
    {"speaker": "eli_marsh", "line": "Point three, the risk I carry myself."},
    {"speaker": "elena_voss", "line": "That last one is where I want to stay."},
    {"speaker": "eli_marsh", "line": "Good — it deserves the time."},
]

_REPLACEMENT = [
    {"speaker": "eli_marsh", "line": "Point one about the platform."},
    {"speaker": "elena_voss", "line": "Go on."},
    {"speaker": "eli_marsh", "line": "Point two, and the risk I carry myself — the bigger one."},
]


def test_repair_produces_alternating_turns_within_caps_and_passes_deterministic_checks():
    turns, found, fixed = repair.repair_structure(
        [dict(t) for t in _SEEDED],
        {"elena_voss", "eli_marsh"},
        _invoke_returning(_REPLACEMENT),
        "test-model",
        panel._extract_json,
        _LOG,
    )
    assert (found, fixed) == (1, 1)
    # Fully alternating, every turn within the word cap → the deterministic gate is clean.
    assert qa.structural_seams(turns) == []
    assert qa._craft_check(turns) == []
    speakers = [t["speaker"] for t in turns]
    assert all(a != b for a, b in zip(speakers, speakers[1:]))
    # Surrounding content is preserved verbatim.
    assert turns[0] == _SEEDED[0] and turns[-1] == _SEEDED[-1]


def test_repair_noop_on_already_alternating_script():
    clean = [_SEEDED[0], _SEEDED[1], _SEEDED[4], _SEEDED[5]]

    def _never(*a, **k):
        raise AssertionError("repair must not spend a generation on a clean script")

    turns, found, fixed = repair.repair_structure(clean, {"elena_voss", "eli_marsh"}, _never, "m", panel._extract_json, _LOG)
    assert turns == clean and (found, fixed) == (0, 0)


def test_repair_rejects_invalid_replacement_and_keeps_original_for_the_gate():
    # Replacement that STILL has a same-speaker adjacency → rejected, original kept,
    # and the deterministic gate still fails the script (repair never pre-clears).
    bad = [
        {"speaker": "eli_marsh", "line": "Point one."},
        {"speaker": "eli_marsh", "line": "Point two."},
    ]
    turns, found, fixed = repair.repair_structure(
        [dict(t) for t in _SEEDED], {"elena_voss", "eli_marsh"}, _invoke_returning(bad), "m", panel._extract_json, _LOG
    )
    assert (found, fixed) == (1, 0)
    assert turns == _SEEDED
    assert qa.structural_seams(turns) and qa._craft_check(turns)
    # Over the word cap → rejected too (a merge must split, never breach the cap).
    long_line = "word " * (qa._QA_MAX_WORDS_PER_TURN + 1)
    over = [{"speaker": "eli_marsh", "line": long_line}]
    turns, found, fixed = repair.repair_structure(
        [dict(t) for t in _SEEDED], {"elena_voss", "eli_marsh"}, _invoke_returning(over), "m", panel._extract_json, _LOG
    )
    assert (found, fixed) == (1, 0) and turns == _SEEDED
    # Boundary alternation: last replacement turn may not share a speaker with the
    # turn after the span (elena at index 4) — elena-ending replacement rejected.
    boundary_bad = [{"speaker": "eli_marsh", "line": "Points one and two."}, {"speaker": "elena_voss", "line": "And three?"}]
    turns, found, fixed = repair.repair_structure(
        [dict(t) for t in _SEEDED], {"elena_voss", "eli_marsh"}, _invoke_returning(boundary_bad), "m", panel._extract_json, _LOG
    )
    assert (found, fixed) == (1, 0) and turns == _SEEDED


def test_repair_line_ok_rejects_lines_failing_the_callers_gates():
    tainted = [
        {"speaker": "eli_marsh", "line": "Point one."},
        {"speaker": "elena_voss", "line": "He weighed himself yesterday, right?"},
        {"speaker": "eli_marsh", "line": "Points two and three."},
    ]
    turns, found, fixed = repair.repair_structure(
        [dict(t) for t in _SEEDED],
        {"elena_voss", "eli_marsh"},
        _invoke_returning(tainted),
        "m",
        panel._extract_json,
        _LOG,
        line_ok=lambda line: "weighed" not in line,
    )
    assert (found, fixed) == (1, 0) and turns == _SEEDED


def test_repair_survives_a_generation_error_fail_open_to_the_gate():
    def _boom(*a, **k):
        raise RuntimeError("bedrock down")

    turns, found, fixed = repair.repair_structure(
        [dict(t) for t in _SEEDED], {"elena_voss", "eli_marsh"}, _boom, "m", panel._extract_json, _LOG
    )
    assert (found, fixed) == (1, 0) and turns == _SEEDED  # gate downstream still holds it


# ── #1171: calibration — the two graders agree on the consecutive-turns line ──


def test_qa_max_consecutive_is_two_and_judge_rubrics_state_the_same_bound():
    import re

    assert qa._QA_MAX_CONSECUTIVE == 2
    for rubric in (qa._INTRO_RUBRIC, qa._WEEKLY_RUBRIC):
        m = re.search(r"more than (\d+) consecutive turns", rubric)
        assert m, "judge rubric no longer states the consecutive-turns bound — re-align it with _QA_MAX_CONSECUTIVE"
        # The deterministic bound must be AT LEAST as strict as what the judge is told to fail.
        assert qa._QA_MAX_CONSECUTIVE <= int(m.group(1))


# ── #1171: revision loop feeds the judge's exact failure text to the writer ───


def test_revise_intro_passes_judge_feedback_verbatim():
    calls = []
    out = repair.revise_intro(
        [{"speaker": "elena_voss", "line": "hi"}],
        ["JUDGE-ITEM-ALPHA: lecture rhythm", "JUDGE-ITEM-BETA: unbridged jump"],
        _invoke_capturing([{"speaker": "elena", "line": "revised"}], calls),
        "test-model",
        panel._extract_json,
        _LOG,
    )
    assert out == [{"speaker": "elena", "line": "revised"}]
    user_msg = calls[0]["messages"][0]["content"]
    assert "JUDGE-ITEM-ALPHA: lecture rhythm" in user_msg and "JUDGE-ITEM-BETA: unbridged jump" in user_msg
    assert "elena_voss: hi" in user_msg  # the draft rides along


def test_revise_weekly_passes_judge_feedback_verbatim():
    calls = []
    payload = {"turns": [{"speaker": "elena", "line": "revised"}], "open_bet": "x", "pull_quote": "y"}
    out = repair.revise_weekly(
        [{"speaker": "elena_voss", "line": "hi"}],
        ["JUDGE-ITEM-GAMMA: no humour beat"],
        "Dr. Sarah Chen",
        "The Measured Life",
        _invoke_capturing(payload, calls),
        "test-model",
        panel._extract_json,
        _LOG,
    )
    assert out == payload
    assert "JUDGE-ITEM-GAMMA: no humour beat" in calls[0]["messages"][0]["content"]
    assert "Dr. Sarah Chen" in calls[0]["system"]


def test_revise_intro_fails_soft_to_empty_on_error():
    def _boom(*a, **k):
        raise RuntimeError("down")

    assert repair.revise_intro([{"speaker": "elena_voss", "line": "hi"}], ["f"], _boom, "m", panel._extract_json, _LOG) == []


# ── #1171: ledger shape + #1172: escalation email ─────────────────────────────


def test_ledger_entry_is_compact_and_transcript_free():
    e = repair.ledger_entry(2, 1, ["d" * 500] * 20, ["j" * 500] * 20, repaired_seams=3)
    assert e["attempt"] == 2 and e["revision"] == 1 and e["repaired_seams"] == 3
    assert len(e["deterministic"]) <= 8 and all(len(x) <= 160 for x in e["deterministic"])
    assert len(e["judge"]) <= 8 and all(len(x) <= 160 for x in e["judge"])


class _FakeSES:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send_email(self, **kw):
        if self.fail:
            raise RuntimeError("ses down")
        self.sent.append(kw)


def _ledger_two_attempts():
    return [
        repair.ledger_entry(1, 0, ["eli_marsh speaks 3 turns in a row"], ["lecture rhythm"], 1),
        repair.ledger_entry(1, 1, [], ["lecture rhythm"], 0),
        repair.ledger_entry(2, 0, [], ["unbridged jump"], 0),
    ]


def test_exhaustion_email_sends_once_with_the_ledger_summary():
    ses = _FakeSES()
    out = repair.send_exhaustion_email(
        ses, "from@x.com", "to@x.com", 3, "weekly", _ledger_two_attempts(), _LOG, hold_uri="s3://b/h/wk3.json"
    )
    assert out == {"sent": 1} and len(ses.sent) == 1
    sent = ses.sent[0]
    assert sent["Destination"] == {"ToAddresses": ["to@x.com"]}
    subject = sent["Content"]["Simple"]["Subject"]["Data"]
    assert "Panelcast HOLD" in subject and "failed the gate after 2 attempts" in subject
    body = sent["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert "eli_marsh speaks 3 turns in a row" in body and "unbridged jump" in body
    assert "s3://b/h/wk3.json" in body
    assert "Nothing was published" in body


def test_exhaustion_email_skips_without_recipient_and_fails_open_on_error():
    ses = _FakeSES()
    assert repair.send_exhaustion_email(ses, "from@x.com", "", 3, "weekly", _ledger_two_attempts(), _LOG)["skipped"] == "no recipient"
    assert ses.sent == []
    broken = _FakeSES(fail=True)
    out = repair.send_exhaustion_email(broken, "from@x.com", "to@x.com", 3, "weekly", _ledger_two_attempts(), _LOG)
    assert out["sent"] == 0 and "error" in out  # never raises — the HOLD stands regardless


# ── end-to-end: intro repaired-but-judge-failing → HOLD, never publish ────────


def test_intro_repaired_script_that_still_fails_judge_holds(monkeypatch):
    import bedrock_client

    monkeypatch.setattr(panel, "_load_bible", lambda: {"characters": {"matthew": "an ordinary, technical, curious person"}})
    # Seeded generation: Elena names herself in line 1 (no cold-open prepend), with a
    # 3-in-a-row eli seam the repair pass must fix before the judge sees it.
    seeded = [
        {"speaker": "elena", "line": "I'm Elena Voss, and here is the hook that got me."},
        {"speaker": "eli", "line": "Point one about the platform."},
        {"speaker": "eli", "line": "Point two, the bigger one honestly."},
        {"speaker": "eli", "line": "Point three, the risk I name myself."},
        {"speaker": "elena", "line": "That risk is where I want to stay."},
        {"speaker": "eli", "line": "Good — it deserves the time."},
        {"speaker": "elena", "line": "Say more about the honest version."},
        {"speaker": "eli", "line": "The honest version is slower and truer."},
        {"speaker": "elena", "line": "And the readers see all of it."},
        {"speaker": "eli", "line": "Every line of it."},
    ]
    monkeypatch.setattr(panel, "_build_intro_script", lambda bible: [dict(t) for t in seeded])
    # The only bedrock call left un-patched is the REPAIR generation → return a valid splice.
    replacement = [
        {"speaker": "eli_marsh", "line": "Point one about the platform."},
        {"speaker": "elena_voss", "line": "Go on."},
        {"speaker": "eli_marsh", "line": "Point two and point three — the risk I name myself."},
    ]
    monkeypatch.setattr(bedrock_client, "invoke", _invoke_returning(replacement))
    # The judge still fails the repaired script → the gate must HOLD (repair never pre-clears).
    monkeypatch.setattr(panel, "_qa_review", lambda turns, rubric, gt="": (False, ["judge: still reads as a lecture"]))
    monkeypatch.setattr(panel._repair, "revise_intro", lambda *a, **k: [])  # revisions add nothing here

    held, emails = {}, []
    monkeypatch.setattr(
        panel,
        "_hold_and_alert",
        lambda week, reasons, draft, hold_class="safety": held.update(
            {"week": week, "reasons": reasons, "draft": draft, "hold_class": hold_class}
        )
        or {"statusCode": 200, "body": "{}", "held": True},
    )
    monkeypatch.setattr(panel._repair, "send_exhaustion_email", lambda *a, **k: emails.append((a, k)) or {"sent": 1})
    monkeypatch.setattr(
        panel, "_publish_episode_audio", lambda *a, **k: (_ for _ in ()).throw(AssertionError("published despite judge fails"))
    )

    out = panel._run_intro(dry_run=False)
    assert out.get("held") is True
    assert held["hold_class"] == "quality" and any("still reads as a lecture" in r for r in held["reasons"])
    assert len(emails) == 1  # ONE escalation email on exhaustion
    # The held draft is the REPAIRED script: alternation restored, no gate seams left.
    draft_speakers = [t["speaker"] for t in held["draft"]["turns"]]
    assert all(a != b for a, b in zip(draft_speakers, draft_speakers[1:]))
    assert qa.structural_seams(held["draft"]["turns"]) == []
    # The per-attempt ledger rides the hold record, one row per gate pass, seams counted.
    ledger = held["draft"]["qa_ledger"]
    assert ledger and ledger[0]["repaired_seams"] == 1
    judged = [e for e in ledger if e["judge"]]  # failed revisions honestly log a no-candidate row with no judge verdict
    assert judged and all("still reads as a lecture" in " ".join(e["judge"]) for e in judged)


# ── end-to-end: weekly bounded budget — exhaustion vs in-budget publish ───────


def _weekly_harness(monkeypatch, judge):
    """Wire _run_weekly fully offline: clean material, passing editor, patched judge."""
    panel._content_filter_cache = {"blocked_vices": [], "blocked_vice_keywords": []}
    beats = {
        "week": 3,
        "date": "2026-08-01",
        "title": "Week 3",
        "chronicle": "A solid, ordinary training week with good sleep.",
        "coach_reads": [{"id": "sleep_coach", "name": "Dr. Sarah Chen", "summary": "Sleep held steady all week.", "themes": []}],
        "guest": {"id": "sleep_coach", "name": "Dr. Sarah Chen", "summary": "Sleep held steady all week.", "themes": []},
        "presence_note": "",
        "phase_block": "",
        "last_open_bet": None,
        "recent_topics": [],
        "prev_guest": "",
    }
    script = {
        "turns": [
            {"speaker": ("elena" if i % 2 == 0 else "coach"), "line": f"A clean, safe, number-free line of dialogue, take {'x' * (i + 1)}."}
            for i in range(8)
        ],
        "open_bet": "sleep stays steady",
        "last_bet_result": {"outcome": "none"},
        "pull_quote": "a quiet good week",
        "episode_title": "Quiet Good Week",
    }
    monkeypatch.setattr(panel, "_select_week_post", lambda: {"week": 3, "date": "2026-08-01", "title": "Week 3"})
    monkeypatch.setattr(panel, "_episode_exists", lambda w: False)
    monkeypatch.setattr(panel, "_load_bible", lambda: {})
    monkeypatch.setattr(panel, "_state_read", lambda: {})
    monkeypatch.setattr(panel, "_gather_week", lambda post, state: dict(beats))
    monkeypatch.setattr(panel, "_build_weekly_script_v2", lambda b, bb: {})
    monkeypatch.setattr(panel, "_build_weekly_script", lambda b, bb: json.loads(json.dumps(script)))
    monkeypatch.setattr(panel, "_editor_review", lambda turns, bible: {"verdict": "pass", "issues": [], "pull_quote": ""})
    monkeypatch.setattr(panel, "_qa_review", judge)
    import bedrock_client

    monkeypatch.setattr(
        bedrock_client, "invoke", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no bedrock call expected — script alternates"))
    )
    monkeypatch.setattr(
        panel, "_publish_episode_audio", lambda *a, **k: (_ for _ in ()).throw(AssertionError("published on the exhaustion path"))
    )


def test_weekly_exhaustion_publishes_nothing_and_sends_one_email_with_ledger(monkeypatch):
    _weekly_harness(monkeypatch, judge=lambda turns, rubric, gt="": (False, ["no humour beat"]))
    monkeypatch.setattr(panel._repair, "revise_weekly", lambda *a, **k: {})  # each revision fails → next generation

    held, emails = {}, []
    monkeypatch.setattr(
        panel,
        "_hold_and_alert",
        lambda week, reasons, draft, hold_class="safety": held.update(
            {"week": week, "reasons": reasons, "draft": draft, "hold_class": hold_class}
        )
        or {"statusCode": 200, "body": json.dumps({"week": week, "held": True}), "held": True},
    )
    monkeypatch.setattr(panel._repair, "send_exhaustion_email", lambda *a, **k: emails.append((a, k)) or {"sent": 1})

    out = panel._run_weekly(force=False, dry_run=False)
    assert out.get("held") is True
    assert held["week"] == 3 and held["hold_class"] == "quality"
    assert any("weekly-qa" in r and "no humour beat" in r for r in held["reasons"])
    assert len(emails) == 1  # exactly ONE needs-human email
    ledger = held["draft"]["qa_ledger"]
    assert len({e["attempt"] for e in ledger}) == panel._QA_MAX_ATTEMPTS  # the full 3-generation budget was spent
    assert all("no humour beat" in " ".join(e["judge"]) for e in ledger)
    # And the email carried the same ledger (positional arg 6 of send_exhaustion_email).
    assert emails[0][0][5] == ledger


def test_weekly_passing_attempt_inside_budget_publishes_normally(monkeypatch):
    _weekly_harness(monkeypatch, judge=lambda turns, rubric, gt="": (True, []))
    emails = []
    monkeypatch.setattr(panel._repair, "send_exhaustion_email", lambda *a, **k: emails.append(1) or {"sent": 1})
    monkeypatch.setattr(panel, "_hold_and_alert", lambda *a, **k: (_ for _ in ()).throw(AssertionError("held despite a clean gate pass")))

    out = panel._run_weekly(force=False, dry_run=True)  # dry_run: the full decision path, no TTS/writes
    body = json.loads(out["body"])
    assert body["would"] == "PUBLISH" and body["clean_turns"] == 8 and body["week"] == 3
    assert emails == []  # no escalation on a pass
