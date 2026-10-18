"""tests/test_story_staging_gate_fixes_4993.py — the three tooling defects that refused a repaired season (#4993).

The cycle-17 season was repaired on 2026-10-18 and ``season_promote.py`` still exited 3 on findings no repair could clear:

  1. the repeat gate flagged the canonical sign-off the sign-off gate REQUIRES — one shared constant now feeds both,
     and the repeat gate reads the show's fixed lines as format, never as a repeat;
  2. the body-number regex read "2.64 pounds per week" (the real wk4 episode line) as "64 pounds" — a rate is a pace,
     not a weigh-in; a bare "318.9 pounds" still flags;
  3. ``--repair`` could not reach the record the fact read is grounded in (the ledger's ``verdict_note``, a named
     ask/thread, the budget's ``top_line`` dek), so a wrong winner was re-asserted into every rewrite.

No model call: the writers and the fact read are replaced in-process; the staged bundle lives in tmp.

Run:  python3 -m pytest tests/test_story_staging_gate_fixes_4993.py -v
"""

import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from content import story_craft, story_ledger, story_writers  # noqa: E402

_spec = importlib.util.spec_from_file_location("season_rebuild_4993", os.path.join(ROOT, "scripts", "season_rebuild.py"))
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


# ── 1. the repeat gate and the sign-off gate agree on the sign-off ───────────

WK0_LAST = "We find out tomorrow. I'm Elena Voss. This has been The Measured Life."
WK0_OPEN = "Welcome to The Measured Life. I'm Elena Voss, and this is the prologue."


def test_the_sign_off_never_produces_a_repeat_finding():
    previous = {0: f"ELENA: {WK0_OPEN}\n\nELENA: {WK0_LAST}"}
    episode = [
        {"speaker": "elena", "line": "Welcome to The Measured Life. I'm Elena Voss — Week 1 starts on a Monday in the gym."},
        {"speaker": "elena", "line": f"Saturday grades the protein call. {story_craft.SIGN_OFF}"},
    ]
    # the sign-off gate is satisfied by exactly this line …
    assert not [f for f in story_writers.spoken_word_findings(episode) if "sign-off" in f]
    # … and the repeat gate never calls it (or the welcome) a repeat
    assert story_craft.repeat_findings(story_writers.episode_text({"turns": episode}), previous) == []
    # every canonical line, alone, against a week that said all of them
    said_all = " ".join(story_craft.CANONICAL_LINES)
    for line in story_craft.CANONICAL_LINES:
        assert story_craft.repeat_findings(f"ELENA: {line}", {0: f"ELENA: {said_all}"}) == [], line


def test_the_two_gates_read_one_constant():
    assert story_craft.SIGN_OFF_LINE in story_craft.SIGN_OFF and story_craft.SIGN_OFF in story_craft.CANONICAL_LINES
    missing = story_writers.spoken_word_findings([{"speaker": "elena", "line": "I'm Elena Voss — The Measured Life."}])
    assert "episode: the sign-off line is missing from the last turn" in missing


def test_a_real_repeat_still_flags_even_beside_the_sign_off():
    said = "the scale is moving faster than the plan said it would this early"
    previous = {0: f"ELENA: {said}. {story_craft.SIGN_OFF}"}
    found = story_craft.repeat_findings(f"ELENA: Again, {said}. {story_craft.SIGN_OFF}", previous)
    assert found and found[0].startswith("repeat:") and "measured life" not in found[0]


def test_a_run_cannot_reach_across_the_sign_off():
    # the 7-word runs the staged season was refused on, built from the sign-off plus the turn label
    previous = {0: f"ELENA: {WK0_OPEN}\n\nELENA: {WK0_LAST}", 1: "ELENA: Welcome to The Measured Life. I'm Elena Voss. Week 1."}
    wk2 = "ELENA: Welcome to The Measured Life. I'm Elena Voss. Day 10.\n\nELENA: I'm Elena Voss, and this has been The Measured Life."
    assert story_craft.repeat_findings(wk2, previous) == []


# ── 2. a rate is not a body number ───────────────────────────────────────────

# the wk4 episode line as staged in the cycle-17 bundle (2026-10-18), turn 4 — the auditor's A15
WK4_LINE = (
    "A clean result. The scale is down about fifteen pounds from his first weigh-in, and the pace this window is 2.64 pounds "
    "per week — slower than the season average, which is exactly what the plan said would happen as the early water and "
    "glycogen drop fades."
)


@pytest.mark.parametrize(
    "line",
    [WK4_LINE, "the pace is 2.64 pounds/week", "about 12 lb/wk early on", "losing 10 pounds a week", "12 lbs per week", "15 pounds / week"],
)
def test_a_rate_with_a_unit_per_week_is_not_a_body_number(line):
    found = story_writers.spoken_word_findings([{"speaker": "coach", "line": line}, {"speaker": "elena", "line": story_craft.SIGN_OFF}])
    assert not [f for f in found if "body-number" in f], found


@pytest.mark.parametrize("line", ["He stood at 318.9 pounds on Day 10.", "318.9 pounds", "the scale read 312 lbs", "down to 145 kg"])
def test_a_bare_weight_still_flags(line):
    found = story_writers.spoken_word_findings([{"speaker": "coach", "line": line}, {"speaker": "elena", "line": story_craft.SIGN_OFF}])
    assert [f for f in found if "body-number" in f], line


# ── 3. --repair reaches the record ───────────────────────────────────────────

WRONG = "Week 3 bet: week-end weight below the threshold. Bet is right. Elena wins."
RIGHT = "Week 3 bet: week-end weight below the threshold. Bet is right. Elena took the other side; Okafor wins."


def _write(out, name, obj):
    with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
        if isinstance(obj, str):
            fh.write(obj)
        else:
            json.dump(obj, fh)


def _read(out, name):
    with open(os.path.join(out, name), encoding="utf-8") as fh:
        return json.load(fh)


def _fact_findings(out):
    """The fact read's findings in the repaired week's report (the tiny fixture also trips the craft length gates,
    which are not what these tests are about)."""
    rep = _read(out, "wk4_report.json")
    return [f for f in rep["post_findings"] + rep["episode_findings"] if f.startswith(("fact:", "dek: fact:"))]


ASK_TEXT = "Answer the question posed this week about the quiet in the journal."
ASK_ID = story_ledger.ask_id(ASK_TEXT)


def _stage(out):
    """A two-week staged bundle (weeks 4 and 5) whose record carries the wrong winner, a journal-probing ask and a
    thread with an overstated title — the three shapes the cycle-17 audit found."""
    bet3 = {"claim": "the scale is lower by Tuesday", "week": 3, "result": "right", "scored_week": 4, "verdict_note": WRONG}
    ledger4 = {
        **story_ledger.empty_ledger(),
        "week": 4,
        "bets": [bet3, {"claim": "next", "week": 4, "result": "open"}],
        "asks": [{"coach_id": "mind_coach", "ask": ASK_TEXT, "id": ASK_ID, "week": 4, "status": "open"}],
        "threads": [{"id": "the_streak", "title": "The Streak: 24 Days Without a Rest Day", "status": "open", "opened_week": 4}],
        "titles": [{"week": 4, "title": "Old title"}],
    }
    budget4 = {
        "top_line": "A dek that overstates the streak.",
        "bet_scored": {"result": "right", "note": WRONG},
        "bets_scored": [{"bet_week": 3, "result": "right", "winner": "Elena", "note": WRONG}],
        "coach_asks": [{"coach_id": "mind_coach", "ask": ASK_TEXT, "follow_up_by": "2026-10-06"}],
        "thread_actions": [{"thread_id": "the_streak", "action": "open", "title": "The Streak: 24 Days Without a Rest Day"}],
    }
    ledger5 = json.loads(json.dumps({**ledger4, "week": 5}))
    _write(out, "wk3_ledger.json", {**story_ledger.empty_ledger(), "week": 3, "bets": [{**bet3, "result": "open"}]})
    _write(out, "wk3_dossier.json", {"week": 3})
    _write(out, "wk4_ledger.json", ledger4)
    _write(out, "wk4_budget.json", budget4)
    _write(out, "wk5_ledger.json", ledger5)
    _write(
        out, "wk4_dossier.json", {"week": 4, "window": {"start": "2026-09-23", "end": "2026-09-29", "experiment_days": "Day 18 to Day 24"}}
    )
    _write(out, "wk4_report.json", {"week": 4, "post_findings": [], "episode_findings": []})
    _write(out, "wk4_chronicle.md", '"A title"\n\nHe walked home.\n\n---\n*Week 4 of The Measured Life*')
    ep = {"title": "Ep 4", "excerpt": "", "turns": [{"speaker": "elena", "line": f"He walked home. {story_craft.SIGN_OFF}"}]}
    _write(out, "wk4_episode.json", ep)
    _write(out, "wk4_episode.txt", story_writers.episode_text(ep))


@pytest.fixture
def no_model(monkeypatch):
    """The writers return the draft they were given; the fact read flags 'Elena wins' whenever the record it is
    grounded in still says so. Records what each fact read saw."""
    seen = []

    def fact_check(text, dossier, *, context=None, invoke=None):
        scoring = json.dumps((context or {}).get("this_weeks_bet_scoring"))
        seen.append({"text": text, "scoring": scoring})
        return ["fact: the record says Elena wins"] if "Elena wins" in scoring else []

    monkeypatch.setattr(story_writers, "fact_check", fact_check)
    monkeypatch.setattr(story_writers, "write_chronicle", lambda *a, prior_draft=None, **k: (prior_draft, "end_turn"))
    monkeypatch.setattr(story_writers, "write_episode", lambda *a, prior=None, **k: (prior, "end_turn"))
    return seen


def test_repair_corrects_the_verdict_note_and_the_fact_read_reads_the_correction(tmp_path, no_model):
    out = str(tmp_path)
    _stage(out)
    sr.repair_week(out, 4, ledger_notes=[f"verdict_note: {RIGHT}", "winner@3: James Okafor"])
    assert _fact_findings(out) == []
    assert no_model and all("Elena wins" not in s["scoring"] for s in no_model)
    led4, led5, budget = _read(out, "wk4_ledger.json"), _read(out, "wk5_ledger.json"), _read(out, "wk4_budget.json")
    for led in (led4, led5):  # this week's ledger and the later snapshot that carries the same bet
        bet = next(b for b in led["bets"] if b["week"] == 3)
        assert bet["verdict_note"] == RIGHT and bet["winner"] == "James Okafor"
    assert budget["bet_scored"]["note"] == RIGHT
    assert budget["bets_scored"][0] == {"bet_week": 3, "result": "right", "winner": "James Okafor", "note": RIGHT}
    assert next(b for b in _read(out, "wk3_ledger.json")["bets"])["verdict_note"] == WRONG  # an EARLIER week is never rewritten


def test_mutation_control_without_the_record_fix_the_wrong_winner_is_reasserted(tmp_path, no_model):
    out = str(tmp_path)
    _stage(out)
    sr.repair_week(out, 4, notes=[f"the winner is Okafor: {RIGHT}"])
    assert "fact: the record says Elena wins" in _fact_findings(out)


def test_repair_reaches_a_named_ask_a_thread_and_the_dek(tmp_path, no_model):
    out = str(tmp_path)
    _stage(out)
    dek = "He is down from his first weigh-in and still moving; protein fell late in the week."
    notes = [f"verdict_note: {RIGHT}", f"{ASK_ID}: (drop)", "the_streak: The Streak: 23 Days Since a Day Off"]
    sr.repair_week(out, 4, ledger_notes=notes, dek=dek)
    assert _fact_findings(out) == []
    led4, led5, budget = _read(out, "wk4_ledger.json"), _read(out, "wk5_ledger.json"), _read(out, "wk4_budget.json")
    for led in (led4, led5):
        assert not [a for a in led["asks"] if a["id"] == ASK_ID]
        assert led["threads"][0]["title"] == "The Streak: 23 Days Since a Day Off"
    assert budget["coach_asks"] == []
    assert budget["thread_actions"][0]["title"] == "The Streak: 23 Days Since a Day Off"
    assert budget["top_line"] == dek
    with open(os.path.join(out, "wk4_chronicle.md"), encoding="utf-8") as fh:
        assert f"*{dek}*" in fh.read()  # the rendered dek follows the corrected top line
    assert any(s["text"] == dek for s in no_model)  # and the replaced dek was itself fact-read


def test_an_unknown_target_fails_loudly(tmp_path, no_model):
    out = str(tmp_path)
    _stage(out)
    with pytest.raises(SystemExit, match="no ask"):
        sr.repair_week(out, 4, ledger_notes=["ask-00000000: reworded"])
    with pytest.raises(SystemExit, match="expected"):
        sr.parse_ledger_note("verdict_note")
    with pytest.raises(SystemExit, match="never dropped"):
        sr.parse_ledger_note("verdict_note: (drop)")


def test_an_ambiguous_verdict_needs_the_bet_week(tmp_path, no_model):
    out = str(tmp_path)
    _stage(out)
    led = _read(out, "wk4_ledger.json")
    led["bets"].insert(0, {"claim": "older", "week": 2, "result": "wrong", "scored_week": 4, "verdict_note": "x"})
    _write(out, "wk4_ledger.json", led)
    with pytest.raises(SystemExit, match="name one with @"):
        sr.repair_week(out, 4, ledger_notes=[f"verdict_note: {RIGHT}"])
    sr.repair_week(out, 4, ledger_notes=[f"verdict_note@3: {RIGHT}"])
    assert _fact_findings(out) == []


def test_the_cli_wires_the_flags_and_refuses_them_without_repair(tmp_path, no_model):
    out = str(tmp_path)
    _stage(out)
    sr.main(["--out", out, "--repair", "4", "--ledger-note", f"verdict_note: {RIGHT}", "--dek", "A plain line."])
    assert _fact_findings(out) == []
    assert _read(out, "wk4_budget.json")["top_line"] == "A plain line."
    with pytest.raises(SystemExit, match="only with --repair"):
        sr.main(["--out", out, "--dek", "x"])
