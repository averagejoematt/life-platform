"""tests/test_life_disruption_5122.py — the whole-day life-disruption playbook and the 72-hour lapse protocol (#5122).

Epic #5120 (the coping system). #5088's disruption mode held the TRAINING only; this holds the whole day. The five
acceptance boxes, one block each:

  (1) the playbook is charter DATA: held/paused core habits, paused targets, a no-grading window of up to 14 days;
  (2) the 72-hour lapse protocol: what runs, what pauses, and the plan resumes the next morning;
  (3) no streak-shaming language in the briefs, coaches or emails while the mode is on — over the rendered prompts
      (the coach context, the daily coaches' standing lines, the owner threads, the write path's payload) and over
      the string literals of the NAMED brief/coach/email prompt modules (a fixed list, not a tree sweep);
  (4) entering and leaving is one owner action, and the record is the log;
  (5) the charter and the coach context read the mode through the one assembly (#5071).

The lapse trigger is the #5121 early-warning flag (`USER#matthew#SOURCE#early_warning_flag`); the rows here are that
module's row contract. When `health.early_warning` is importable the parity test holds `flag_episode` to its
`episode` (#5121 is on main, so it always runs); the live read states `not_wired` only if that import ever fails.

Every date is a fixed literal; nothing asserted here reads the clock (#4848).
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from training import (
    coach_context as cc,  # noqa: E402
    disruption as d,  # noqa: E402
    life_disruption as ld,  # noqa: E402
    training_charter as tc,  # noqa: E402
)

RESPONSE = {"owner": "mind_coach", "owner_name": "Nathan Reeves", "line": "Owner: Nathan Reeves (mind_coach)."}


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _rec(template: str, start: str, until: str, words: str = "a rough stretch at work, holding the floors") -> dict:
    return d.build_disruption_record(start_date=start, until=until, words=words, template=template, recorded_at="2026-11-01T15:00:00Z")


def _flag(day: str, active: bool, markers=("weigh_in_cadence", "food_log_gap")) -> dict:
    """One #5121 flag row (health.early_warning.item's shape)."""
    return {
        "pk": "USER#matthew#SOURCE#early_warning_flag",
        "sk": f"DATE#{day}",
        "date": day,
        "active": active,
        "markers": list(markers) if active else [],
        "evidence": {m: f"{m} evidence line" for m in markers} if active else {},
        "tier": "owner_only",
    }


# ── (1) the playbook is charter data ─────────────────────────────────────────────────────────
def test_the_charter_carries_the_whole_day_playbook_with_a_change_log_line():
    c = tc.load_charter()
    assert c["version"] == c["change_log"][-1]["version"]
    assert len([e for e in c["change_log"] if e["what"].startswith("#5122")]) == 1  # by content: later lanes stack after it
    pol = d.policy()
    assert {"life", "lapse"} <= set(pol["templates"]) and ld.whole_day_templates() == ["lapse", "life"]
    assert all(p in d.POOL_NAMES for t in pol["templates"].values() for p in t["pools"])
    assert pol["owner_switched"] is True and pol["imposed"] is False  # the #5088 ruling holds for the whole day too
    assert "disruption" not in tc.public_view()  # owner/engine context, never published


def test_every_core_habit_is_held_or_paused_and_every_paused_target_is_a_charter_path():
    assert ld.habit_problems() == []
    pb = ld.playbook()
    assert pb["held_habits"] and pb["paused_habits"]
    missing = [p for p in pb["paused_targets"] if tc.charter_value(p) is None]
    assert missing == [], f"paused_targets name paths the charter does not carry: {missing}"
    assert pb["grading"]["paused"] and "never as a miss" in pb["grading"]["rule"]


def test_habit_problems_can_fail(monkeypatch):
    bad = dict(ld.playbook(), held_habits=["weigh_in", "calories_in_band", "not_a_core_id"], paused_habits=["calories_in_band"])
    monkeypatch.setattr(ld, "playbook", lambda: bad)
    probs = ld.habit_problems()
    assert any("both held and paused" in p for p in probs)
    assert any("neither held nor paused" in p for p in probs)
    assert any("not a habits.core id" in p for p in probs)


def test_the_no_grading_window_is_at_most_14_days_and_the_record_refuses_a_longer_one():
    assert d.template_max_days("life") == 14
    assert d.template_max_days("travel") == d.template_max_days("busy") == d.policy()["max_days"]  # #5088 unchanged
    assert _rec("life", "2026-11-01", "2026-11-14")["until"] == "2026-11-14"
    with pytest.raises(ValueError, match="within 14 days"):
        _rec("life", "2026-11-01", "2026-11-15")


def test_a_whole_day_template_holds_the_core_habits_beside_the_88_floors():
    holds = d.holds("life")
    assert [h["habit"] for h in holds[:4]] == ["steps", "protein", "sleep", "session"]
    assert holds[-1] == {"habit": "core", "held": ld.playbook()["held_habits"], "source": "charter disruption.whole_day"}
    assert all(h["habit"] != "core" for h in d.holds("travel"))  # a training-only template is unchanged


# ── (2) the 72-hour lapse protocol ───────────────────────────────────────────────────────────
def test_the_lapse_protocol_says_what_runs_what_pauses_and_that_the_plan_resumes_the_next_morning():
    lp = ld.lapse_protocol()
    assert lp["hours"] == 72 and d.template_max_days("lapse") == 3
    assert lp["runs"] and lp["pauses"] and lp["resumes"].startswith("the morning after the last covered day")
    rec = _rec("lapse", "2026-11-01", "2026-11-03")
    m = ld.mode([rec], "2026-11-02", response=RESPONSE)
    assert m["scope"] == ld.SCOPE_WHOLE_DAY and m["lapse"] is True and m["resumes_on"] == "2026-11-04"
    assert m["runs"] == lp["runs"] and m["paused_targets"] == ld.playbook()["paused_targets"]
    # the next morning is the full plan: no step-back-up week after a lapse
    assert d.state([rec], "2026-11-04")["phase"] == d.PHASE_OFF
    assert ld.mode([rec], "2026-11-04")["scope"] == ld.SCOPE_OFF
    with pytest.raises(ValueError, match="within 3 days"):
        _rec("lapse", "2026-11-01", "2026-11-04")


def test_a_life_template_still_steps_the_training_back_up():
    rec = _rec("life", "2026-11-01", "2026-11-10")
    assert d.state([rec], "2026-11-11")["phase"] == d.PHASE_STEP_BACK_UP
    assert ld.mode([rec], "2026-11-11")["scope"] == ld.SCOPE_TRAINING  # the day's targets are back; the training steps up


# ── the trigger: the #5121 early-warning flag, offered by the response owner ──────────────────
def test_an_active_flag_offers_the_lapse_protocol_through_the_response_owner_and_never_applies_it():
    rows = [_flag("2026-11-03", False), _flag("2026-11-04", True), _flag("2026-11-05", True)]
    m = ld.mode([], "2026-11-05", flag_rows=rows, response=RESPONSE)
    offer = m["lapse_offer"]
    assert m["scope"] == ld.SCOPE_OFF and offer["offered"] is True and offer["applies"] is False
    assert offer["since"] == "2026-11-04" and offer["owner"] == "mind_coach" and offer["template"] == "lapse"
    assert offer["hours"] == 72 and len(offer["signals"]) == 2
    text = " ".join(m["lines"])
    assert "Nathan Reeves (mind_coach) OFFERS the 72-hour lapse protocol" in text and "no second ask" in text
    # routed: only the response owner's own thread is told the offer is its to make
    assert any("You own this response" in ln for ln in ld.owner_lines(m, "mind_coach"))
    assert not any("You own this response" in ln for ln in ld.owner_lines(m, "nutrition_coach"))


def test_the_flag_states_are_honest_not_wired_absent_clear():
    assert ld.flag_view(None, "2026-11-05")["state"] == ld.FLAG_NOT_WIRED  # #5121 not on main
    assert ld.flag_view([], "2026-11-05")["state"] == ld.FLAG_ABSENT
    assert ld.flag_view([_flag("2026-10-30", True)], "2026-11-05")["state"] == ld.FLAG_ABSENT  # stale reading
    assert ld.flag_view([_flag("2026-11-05", False)], "2026-11-05")["state"] == ld.FLAG_CLEAR
    assert ld.mode([], "2026-11-05", flag_rows=None)["lapse_offer"] is None


def test_a_mode_already_on_is_not_offered_again():
    rows = [_flag("2026-11-02", True)]
    m = ld.mode([_rec("lapse", "2026-11-01", "2026-11-03")], "2026-11-02", flag_rows=rows, response=RESPONSE)
    assert m["scope"] == ld.SCOPE_WHOLE_DAY and m["lapse_offer"] is None


def test_flag_episode_matches_the_early_warning_modules_own_episode_when_it_is_on_main():
    from health import early_warning as ew  # #5121 (PR #5305) is on main: the parity test runs, never skips

    cases = [
        [_flag("2026-11-01", True), _flag("2026-11-02", False), _flag("2026-11-03", True), _flag("2026-11-05", True)],
        [_flag("2026-11-01", True), _flag("2026-11-02", False)],
        [],
    ]
    for rows in cases:
        ours, theirs = ld.flag_episode(rows), ew.episode(rows)
        assert (ours is None) == (theirs is None)
        if ours:
            assert (ours["start"], ours["latest"]) == (theirs["start"], theirs["latest"])


def test_the_live_read_states_not_wired_when_the_flag_reader_is_absent(monkeypatch):
    monkeypatch.setattr(ld, "FLAG_READER", "health.no_such_flag_reader_5122")
    assert ld.read_flag_rows(object(), "2026-11-05") is None
    m = ld.current(object(), "2026-11-05", records=[], response=RESPONSE)
    assert m is not None and m["flag"]["state"] == ld.FLAG_NOT_WIRED and m["lapse_offer"] is None


# ── (3) no streak-shaming language while the mode is on ─────────────────────────────────────
SPECIMENS = (
    "You broke your 12-day streak yesterday.",
    "Streak: 0 — time to start over.",
    "That's back to day one on the habits.",
    "You missed 3 days in a row.",
    "The tier 0 streak is broken.",
    "He fell off this week.",
    "A 0-day streak.",
)
CLEAN = ("You held the protein floor and weighed in.", "Story threads she may call back to one of.", "The plan resumes tomorrow.")


def test_every_language_pattern_compiles_and_catches_every_specimen_but_no_clean_line():
    assert len(ld.patterns()) == len(ld.language()["never"])
    missed = [s for s in SPECIMENS if not ld.shaming(s)]
    assert missed == [], f"the language rule misses: {missed}"
    flagged = {s: ld.shaming(s) for s in CLEAN if ld.shaming(s)}
    assert flagged == {}, f"false positives: {flagged}"


def _mode_on(**kw) -> dict:
    return ld.mode([_rec("lapse", "2026-11-01", "2026-11-03")], "2026-11-02", response=RESPONSE, **kw)


def _rendered_prompts() -> dict[str, str]:
    """Every prompt/template text the mode touches, rendered with the mode on."""
    m = _mode_on()
    offered = ld.mode([], "2026-11-05", flag_rows=[_flag("2026-11-05", True)], response=RESPONSE)
    line = ld.published_language_line([_rec("lapse", "2026-11-01", "2026-11-03")], ("2026-11-02",))
    return {
        "coach_context.text": cc.assemble("2026-11-02", packet=None, constraint_block=None, response_protocol=RESPONSE, day_mode=m)["text"],
        "charter_goal_lines": cc.charter_goal_lines(line),
        "mind thread": "\n".join(ld.owner_lines(m, "mind_coach")),
        "offer thread": "\n".join(ld.owner_lines(offered, "mind_coach")),
        "playbook text": " ".join(str(v) for k, v in ld.playbook().items() if k not in ("language",)),
        "lapse protocol text": " ".join(str(v) for v in ld.lapse_protocol().values()),
    }


def test_the_mode_holds_its_own_text_to_its_own_rule():
    assert _mode_on()["language_violations"] == []


def test_no_rendered_prompt_carries_streak_shaming_language_while_the_mode_is_on():
    hits = {k: ld.shaming(v) for k, v in _rendered_prompts().items() if ld.shaming(v)}
    assert hits == {}, f"streak-shaming language in a mode-on prompt: {hits}"


def test_the_shaming_check_over_the_prompts_can_fail(monkeypatch):
    orig = ld.lines
    monkeypatch.setattr(ld, "lines", lambda m: orig(m) + ["You broke your streak, back to day one."])
    hits = {k: ld.shaming(v) for k, v in _rendered_prompts().items() if ld.shaming(v)}
    assert "coach_context.text" in hits and "mind thread" in hits


def test_the_daily_coaches_carry_the_language_rule_only_while_a_whole_day_template_is_on():
    records = [_rec("lapse", "2026-11-01", "2026-11-03")]
    on = ld.published_language_line(records, ("2026-11-03",))
    assert on.startswith("- Language today") and on in cc.charter_goal_lines(on)
    assert ld.published_language_line(records, ("2026-11-04",)) == ""  # the next morning: the full plan, no line
    assert ld.published_language_line([_rec("travel", "2026-11-01", "2026-11-03")], ("2026-11-02",)) == ""
    assert cc.charter_goal_lines("") == cc.charter_goal_lines()


def test_the_published_language_line_names_no_mode_record_date_or_word():
    rec = _rec("lapse", "2026-11-01", "2026-11-03", words="my sister called, it is a bad week")
    line = ld.published_language_line([rec], ("2026-11-02",)).lower()
    for leak in ("disruption mode", "lapse", "life template", "2026-11", "sister", "bad week", "early-warning", "early_warning", "flag"):
        assert leak not in line, f"the published line leaks {leak!r}: {line}"


def test_the_daily_coaches_prompt_reads_the_line_from_the_disruption_record_only(monkeypatch):
    from ai import ai_calls

    monkeypatch.setattr(ai_calls, "pacific_today", lambda: "2026-11-03")
    monkeypatch.setattr(ai_calls, "_disruption_language_cache", {})
    monkeypatch.setattr(d, "load_records_failsoft", lambda table=None: [_rec("life", "2026-11-01", "2026-11-02")])
    assert ai_calls._disruption_language_line().startswith("- Language today")  # yesterday (the data day) is covered
    monkeypatch.setattr(ai_calls, "_disruption_language_cache", {})
    monkeypatch.setattr(d, "load_records_failsoft", lambda table=None: [])
    assert ai_calls._disruption_language_line() == ""
    src = (_REPO / "lambdas" / "ai" / "ai_calls.py").read_text(encoding="utf-8")
    assert "early_warning" not in src  # the published side never reads the owner-only flag (#5121)


# The brief/coach/email modules whose string literals are prompt or template text. A NAMED list (not a tree sweep):
# the daily brief and its coaches' prompt, the debrief, the weekly digest, the chronicle prompt, the coach check-in
# and nudge engines and the event triggers.
PROMPT_MODULES = (
    "lambdas/ai/ai_calls.py",
    "lambdas/ai/habit_context.py",
    "lambdas/emails/daily_brief_lambda.py",
    "lambdas/emails/daily_debrief_lambda.py",
    "lambdas/emails/weekly_digest_lambda.py",
    "lambdas/emails/chronicle_prompt.py",
    "lambdas/coach/coach_checkin.py",
    "lambdas/coach/coach_nudge_engine.py",
    "lambdas/coach/coach_event_triggers.py",
    "lambdas/coach/coach_domain_facts.py",
    "lambdas/training/coach_context.py",
    "lambdas/training/life_disruption.py",
)


def _string_literals(rel: str) -> list[tuple[int, str]]:
    tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
    return [(n.lineno, n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_no_prompt_or_template_string_in_the_brief_coach_and_email_modules_shames_a_streak():
    hits = [f"{rel}:{ln}: {ld.shaming(s)}" for rel in PROMPT_MODULES for ln, s in _string_literals(rel) if ld.shaming(s)]
    assert hits == [], "streak-shaming text in a prompt/template module:\n" + "\n".join(hits)


# ── (4) one owner action, logged ──────────────────────────────────────────────────────────
def test_entering_and_leaving_is_one_owner_action_and_the_record_is_the_log(monkeypatch):
    from mcp import tools_training_notes as tn

    written: list = []
    monkeypatch.setattr(tn, "_put_disruption", lambda rec: written.append(dict(rec)))
    refused = tn.tool_get_exercise_notes({"action": "disruption", "template": "lapse", "start_date": "2026-11-01"})
    assert refused["wrote"] is False and not written  # no words, no mode
    ok = tn.tool_get_exercise_notes(
        {"action": "disruption", "template": "lapse", "start_date": "2026-11-01", "words": "rough night, lapse protocol"}
    )
    assert ok["wrote"] is True and len(written) == 1
    rec = written[0]
    assert (rec["start_date"], rec["until"], rec["template"], rec["words"]) == (
        "2026-11-01",
        "2026-11-03",
        "lapse",
        "rough night, lapse protocol",
    )
    assert rec["recorded_at"] and rec["recorded_via"] == "chat"  # the log: when, how, his words verbatim
    assert ok["whole_day"]["scope"] == ld.SCOPE_WHOLE_DAY and ok["whole_day"]["resumes_on"] == "2026-11-04"
    assert not ld.shaming(str(ok))
    monkeypatch.setattr(tn, "_disruption_records", lambda: [dict(rec)])
    ended = tn.tool_get_exercise_notes({"action": "disruption_end", "ended_on": "2026-11-02", "words": "feeling steadier"})
    assert ended["wrote"] is True and len(written) == 2
    assert written[-1]["ended_on"] == "2026-11-02" and written[-1]["end_words"] == "feeling steadier" and written[-1]["ended_recorded_at"]
    assert ld.mode([written[-1]], "2026-11-02")["scope"] == ld.SCOPE_OFF  # off from the day he named


def test_the_tool_schema_offers_the_whole_day_templates():
    from mcp import tools_descriptions

    src = (_REPO / "mcp" / "tools_descriptions.py").read_text(encoding="utf-8")
    assert '"enum": ["travel", "busy", "life", "lapse"]' in src and "#5122" in src
    assert tools_descriptions is not None


# ── (5) the charter and the coach context read the mode through the one assembly ──────────────
def test_the_coach_context_carries_the_day_mode_owner_only():
    m = _mode_on()
    ctx = cc.assemble("2026-11-02", packet=None, constraint_block=None, response_protocol=RESPONSE, day_mode=m)
    assert ctx["day_mode"] is m and "DAY MODE (owner-only)" in ctx["text"] and ld.SOURCE in ctx["text"]
    assert cc.summary(ctx)["day_mode"] == ld.SCOPE_WHOLE_DAY
    assert ctx["context_version"] == "coach-context@1.9.0"  # 1.9.0: #5501 lift_history on the packet; 1.8.1: #5373 the one-hand carry rule
    pub = cc.assemble("2026-11-02", packet=None, constraint_block=None, day_mode=m, published=True)
    assert pub["day_mode"] is None and "DAY MODE" not in pub["text"]
    off = cc.assemble("2026-11-05", packet=None, constraint_block=None, day_mode=ld.mode([], "2026-11-05"))
    assert "DAY MODE" not in off["text"]  # nothing is said on an ordinary day


def test_every_planning_and_owner_thread_caller_passes_the_day_mode():
    """The two assembly callers on main (the MCP planning surfaces and the Telegram coach threads) pass it."""
    for rel in ("mcp/plan_helpers.py", "lambdas/coach/coach_domain_facts.py"):
        tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "assemble"]
        assert calls, rel
        assert all(any(k.arg == "day_mode" for k in c.keywords) for c in calls), f"{rel}: an assemble() call without day_mode"


def test_the_owner_threads_route_the_offer_to_the_response_owner(monkeypatch):
    from coach import coach_domain_facts as cdf

    offered = ld.mode([], "2026-11-05", flag_rows=[_flag("2026-11-05", True)], response=RESPONSE)
    assert any("You own this response" in ln for ln in cdf.life_disruption_lines(offered, "mind_coach"))
    assert not any("You own this response" in ln for ln in cdf.life_disruption_lines(offered, "sleep_coach"))
    assert cdf.life_disruption_lines(None, "mind_coach") == []
    monkeypatch.setattr(ld, "current", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cdf._day_mode(object(), "2026-11-05", RESPONSE) is None  # fail-soft: the chat runs without it
