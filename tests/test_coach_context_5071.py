"""tests/test_coach_context_5071.py — the one coaching context and the tool-call order contract (#5071).

What is held here:
  * ``training.coach_context.assemble`` — every section labelled with its source, absence stated
    (never invented), deterministic, no model import; the owner form carries the May frame and the
    published form carries no May target, no rate band and no record name;
  * the order contract — ``order_violations`` on synthetic sequences (each code reachable), on the
    three REAL planning conversations held BEFORE the deploy (tests/fixtures/coach_transcripts_5071/)
    and on the four REAL conversations held AFTER it (.../after/, two resumed after a break and joined
    onto the conversation they continue); the earlier synthesized AFTER (``to_contract``) is kept as
    a labelled fallback;
  * the wiring — the MCP attach helper, the critics' charter summary and its prompt, the Telegram
    training route, the physical_coach ``context_source`` pointer, the retired role-play text and
    the retired training_coach stance file.

The May frame is computed from the ``target_date`` ARGUMENT and the charter's target date — no clock
is read anywhere in the module (#4848 class), and the expectation below is derived the same way.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import pathlib
from datetime import date

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    coach_context as cc,  # noqa: E402
    training_charter as tc,  # noqa: E402
)

_REPO = pathlib.Path(__file__).resolve().parent.parent
_FIXTURES = _REPO / "tests" / "fixtures" / "coach_transcripts_5071"

GUIDANCE_ROWS = [
    {
        "sk": "GUIDANCE#current",
        "rules": ["OWNER-ONLY RULE TEXT"],
        "public_rules": ["Keep effort conversational on the hard days."],
        "effective": "2026-10-01",
    }
]
PACKET = {
    "packet_version": "coach-session-packet@test",
    "fields": {"loss_rate": {"state": "measured", "source": "tools_benchmark._loss_rate_block", "value": {"lb_per_wk": 3.2}}},
}
BLOCK = {
    "session": {"label": "Upper-heavy", "session_role": "upper_heavy"},
    "program_week": 7,
    "rate_target": {
        "band": {
            "floor_lb_wk": 3.0,
            "ceiling_lb_wk": 3.5,
            "floor_pct_bodyweight_per_wk": 1.03,
            "ceiling_pct_bodyweight_per_wk": 1.21,
            "weight_lb": 290.0,
            "guidance_capped": False,
        }
    },
}


def _eval_script():
    spec = importlib.util.spec_from_file_location("coach_transcript_eval_5071", _REPO / "scripts" / "coach_transcript_eval_5071.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── assemble ──────────────────────────────────────────────────────────────────────────────
def test_owner_context_carries_every_section_with_its_source_and_the_may_frame():
    ctx = cc.assemble("2026-10-20", packet=PACKET, constraint_block=BLOCK, guidance=GUIDANCE_ROWS, published=False)
    assert set(ctx["sections"]) == {"charter", "panel_synthesis", "clinical_guidance", "plan_packet", "constraint_block", "may_tracker"}
    for name, sec in ctx["sections"].items():
        assert sec.get("source"), f"{name} has no source"
    assert ctx["charter_version"] == tc.charter_version()
    assert ctx["sections"]["panel_synthesis"]["concessions"] == tc.charter_value("concession_ledger")
    # the owner channel renders the full record's guidance, as reference context
    assert "OWNER-ONLY RULE TEXT" in ctx["text"] and "not a gate" in ctx["text"]
    # May frame: derived from the argument and the charter, never the clock
    target = tc.charter_value("governing_goal.target_date")
    weeks = round((date.fromisoformat(target) - date(2026, 10, 20)).days / 7, 1)
    assert ctx["may_frame"]["weeks_to_target"] == weeks
    assert f"{weeks:g} weeks before the {target} target" in ctx["may_frame"]["line"]
    # the band in lb AND % of bodyweight, from the block's band
    assert "3.0-3.5 lb/wk" in ctx["may_frame"]["line"] and "1.03-1.21% of bodyweight" in ctx["may_frame"]["line"]
    assert ctx["may_frame"]["line"] in ctx["text"]
    # the packet and block numbers ride with their sources
    assert "tools_benchmark._loss_rate_block" in ctx["text"] and "Upper-heavy" in ctx["text"]


def test_absent_inputs_are_stated_never_invented():
    ctx = cc.assemble("2026-10-20", packet=None, constraint_block=None)
    assert ctx["not_supplied"] == ["clinical_guidance", "constraint_block", "may_tracker", "plan_packet"]
    assert "not supplied: this caller read no May tracker" in ctx["text"]
    # without a weight the % of bodyweight is named as missing, not computed from a default
    assert "% of bodyweight needs a weight" in ctx["may_frame"]["line"]
    tracked = cc.assemble("2026-10-20", packet=None, constraint_block=None, tracker={"weeks_on_band": 3})
    assert tracked["sections"]["may_tracker"]["state"] == "measured" and "weeks_on_band" in tracked["text"]
    failed = cc.assemble("2026-10-20", packet=None, constraint_block=None, guidance={"state": "read_failed", "error": "ClientError"})
    assert failed["sections"]["clinical_guidance"] == {
        "source": cc.SRC_GUIDANCE,
        "state": "read_failed",
        "text": "",
        "detail": "ClientError",
    }


def test_published_context_carries_no_may_target_no_rate_band_and_no_record():
    ctx = cc.assemble("2026-10-20", packet=PACKET, constraint_block=None, guidance=GUIDANCE_ROWS, published=True)
    assert ctx["may_frame"] is None
    assert ctx["sections"]["may_tracker"]["state"] == "omitted_published"
    summary = ctx["sections"]["charter"]["summary"]
    assert "rate_band_lb_per_wk" not in summary and "target_date" not in summary and "governing_goal" not in summary
    text = ctx["text"]
    for leak in (tc.charter_value("governing_goal.target_date"), "May", "OWNER-ONLY RULE TEXT", "SOURCE#clinical", "ORDER:"):
        assert leak not in text, f"published context leaks {leak!r}"
    assert "Keep effort conversational on the hard days." in text  # the neutral guardrails only


def test_assembly_is_deterministic_and_calls_no_model():
    a = cc.assemble("2026-10-20", packet=PACKET, constraint_block=BLOCK, guidance=GUIDANCE_ROWS)
    b = cc.assemble("2026-10-20", packet=PACKET, constraint_block=BLOCK, guidance=GUIDANCE_ROWS)
    assert a == b
    tree = ast.parse((_REPO / "lambdas" / "training" / "coach_context.py").read_text())
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not [m for m in imported if m.startswith("ai") or "bedrock" in m or m == "boto3"], imported
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    clocks = {"pacific_now", "pacific_today", "datetime", "time"}
    assert "time" not in imported and not names & clocks, "the context must not read a clock (#4848) — parse_day_key only"


# ── the order contract ────────────────────────────────────────────────────────────────────
def _codes(calls):
    return [v["code"] for v in cc.order_violations(calls)]


def test_the_contract_order_has_no_violation_and_each_code_is_reachable():
    good = [
        "get_coach_session_packet",
        "get_exercise_history",
        "get_exercise_notes",
        "plan_next_session",
        {"tool": "manage_hevy_routine", "args": {"action": "draft"}},
        {"tool": "plan_next_session", "args": {"routine_id": "r"}},
        {"tool": "manage_hevy_routine", "args": {"action": "commit"}},
    ]
    assert cc.order_violations(good) == []
    assert cc.order_violations(["get_workouts", "get_nutrition"]) == []  # not a planning conversation
    assert _codes(["get_exercise_history", "plan_next_session"]) == ["plan_before_preflight"]
    assert cc.order_violations(["get_exercise_history", "plan_next_session"])[0]["missing"] == [
        "exercise_notes",
        "clinical_guidance",
        "charter",
        "may_tracker",
    ]
    pre = ["get_coach_session_packet", "get_exercise_history", "get_exercise_notes"]
    assert _codes(pre + [{"tool": "manage_hevy_routine", "args": {"action": "draft_custom"}}]) == [
        "draft_before_plan",
        "no_plan_next_session",
    ]
    assert _codes([{"tool": "manage_hevy_routine", "args": {"action": "draft"}}])[:2] == ["draft_before_preflight", "draft_before_plan"]
    assert _codes(pre + [{"tool": "manage_hevy_routine", "args": {"action": "commit"}}]) == ["commit_before_plan", "no_plan_next_session"]
    assert cc.ORDER == ("pre_flight", "plan_next_session", "manage_hevy_routine draft")


def test_three_real_planning_conversations_before_and_the_synthesized_fallback():
    """BEFORE: each real conversation planned before its pre-flight. FALLBACK AFTER: the same calls re-ordered to
    the contract by `to_contract` — the contract's shape, not a real conversation (the real AFTER is the next test)."""
    ev = _eval_script()
    fixtures = ev.load_fixtures(str(_FIXTURES))
    assert len(fixtures) == 3
    expected_missing = {
        "planning-2026-09-22": ["exercise_history", "exercise_notes", "clinical_guidance", "charter", "may_tracker"],
        "planning-2026-10-09": ["exercise_history", "exercise_notes"],
        "planning-2026-10-18": ["exercise_history", "exercise_notes", "clinical_guidance", "charter", "may_tracker"],
    }
    problems = []
    for row in ev.evaluate(fixtures):
        before = [(v["code"], v["missing"]) for v in row["before"]]
        if before != [("plan_before_preflight", expected_missing[row["conversation"]])]:
            problems.append(f"{row['conversation']} before: {before}")
        if row["after"]:
            problems.append(f"{row['conversation']} after: {row['after']}")
    assert not problems, problems
    for fx in fixtures:  # the redaction: tool names and the action/routine flag only
        for c in fx["tool_calls"]:
            assert set(c) <= {"at", "tool", "args"} and set(c.get("args", {})) <= {"action", "routine_id"}, c


_ALLOWED_FIXTURE_KEYS = {
    "conversation",
    "phase",
    "source",
    "window_utc",
    "redaction",
    "coach_context_failures_logged",
    "coach_context_failures_basis",
    "continues",
    "continues_basis",
    "tool_calls",
}


def test_real_after_conversations_reach_the_packet_context_but_not_exercise_history():
    """AFTER, from the MCP log of four real planning conversations (2026-10-29..31) under the deployed contract:
    every one called the packet before planning (the charter, the clinical guidance and the May tracker reached, and
    the May frame on the payload), none called get_exercise_history first — the residual the table reports."""
    ev = _eval_script()
    after = ev.load_fixtures(str(_FIXTURES / "after"))
    rows = ev.evaluate_real(ev.load_fixtures(str(_FIXTURES)), after)
    got = {
        r["conversation"]: ([(v["code"], v["missing"]) for v in r["violations"]], r["context_sources"], r["may_frame_on_payload"])
        for r in rows
    }
    packet = ["clinical_guidance", "charter", "may_tracker"]
    all5 = ["exercise_history", "exercise_notes"] + packet
    expected = {
        "planning-2026-09-22": ([("plan_before_preflight", all5)], [], False),
        "planning-2026-10-09": ([("plan_before_preflight", ["exercise_history", "exercise_notes"])], [], False),
        "planning-2026-10-18": ([("plan_before_preflight", all5)], [], False),
        "after-2026-10-29T0020Z": ([("plan_before_preflight", ["exercise_history", "exercise_notes"])], packet, True),
        "after-2026-10-29T0408Z": ([("plan_before_preflight", ["exercise_history"])], ["exercise_notes"] + packet, True),
        "after-2026-10-30T2059Z": ([("plan_before_preflight", ["exercise_history", "exercise_notes"])], packet, True),
        "after-2026-10-31T0433Z": ([("plan_before_preflight", ["exercise_history", "exercise_notes"])], packet, True),
    }
    assert got == expected
    joined = {r["conversation"]: r["continued_by"] for r in rows if r["continued_by"]}
    assert joined == {"after-2026-10-29T0408Z": ["after-2026-10-29T2243Z"], "after-2026-10-30T2059Z": ["after-2026-10-30T2213Z"]}
    s = ev.summarize(rows)
    assert (s["before"]["packet_first"], s["before"]["may_frame_on_payload"]) == (1, 0)
    assert (s["after"]["packet_first"], s["after"]["may_frame_on_payload"], s["after"]["conversations"]) == (4, 4, 4)
    for fx in after:  # the redaction: tool names, timestamps and the action/routine flag only — PUBLIC repo
        assert set(fx) <= _ALLOWED_FIXTURE_KEYS, set(fx) - _ALLOWED_FIXTURE_KEYS
        assert fx["phase"] == "after" and fx["window_utc"][0] >= ev.CONTRACT_DEPLOYED_UTC
        for c in fx["tool_calls"]:
            assert set(c) <= {"at", "tool", "args"} and set(c.get("args", {})) <= {"action", "routine_id"}, c
            assert c.get("args", {}).get("routine_id") in (None, "<present>"), c


def test_a_continuation_without_its_parent_is_refused_not_scored_alone():
    ev = _eval_script()
    orphan = {"conversation": "x", "continues": "gone", "window_utc": ["2026-10-30T00:00:00Z"] * 2, "tool_calls": []}
    try:
        ev.join_continuations([orphan])
    except ValueError as e:
        assert "gone" in str(e)
    else:
        raise AssertionError("an orphan continuation was scored as its own conversation")


# ── the wiring ────────────────────────────────────────────────────────────────────────────
def test_mcp_attach_puts_the_context_on_the_payload_and_leads_with_the_may_terms(monkeypatch):
    from mcp import plan_helpers as r

    monkeypatch.setattr(r, "_clinical_guidance", lambda: GUIDANCE_ROWS)
    monkeypatch.setattr(r, "_may_tracker", lambda d: None)  # #5200: no live table read in a test
    out = r.attach_coach_context({"how_to_use": "Stage 1."}, "2026-10-20", constraint_block=BLOCK)
    assert out["how_to_use"].startswith(r.EXPLAIN_IN_MAY_TERMS) and out["how_to_use"].endswith("Stage 1.")
    assert out["coach_context"]["charter_version"] == tc.charter_version()
    assert "May frame:" in out["coach_context"]["may_frame"] and "OWNER-ONLY RULE TEXT" in out["coach_context"]["text"]
    brief = r.coach_context_brief("2026-10-20")
    assert "text" not in brief and brief["may_frame"]
    monkeypatch.setattr(cc, "assemble", lambda *a, **k: 1 / 0)
    assert r.coach_context_for("2026-10-20")["state"] == "read_failed"  # fail-soft, named


def test_the_critics_read_the_charter_summary_from_the_one_context():
    from coach import critics

    from mcp import plan_helpers as r

    packets = {cid: {"critic": cid, "numbers": {}, "flags": [], "unknown": []} for cid in critics.CRITIC_IDS}
    r.critics_with_charter(packets, "2026-10-20", BLOCK)
    charter = packets[critics.CRITIC_IDS[0]]["charter"]
    assert charter["charter_version"] == tc.charter_version()
    assert charter["headlines"]["split.lifting_days_per_wk"] == tc.charter_value("split.lifting_days_per_wk")
    assert charter["may_frame"].startswith("May frame:")
    user = json.loads(critics._prompt(packets[critics.CRITIC_IDS[0]], {"exercises": []})["messages"][0]["content"].rsplit("\n", 1)[0])
    assert user["packet"]["charter"] == charter
    bare = {"critic": "x", "numbers": {}, "flags": [], "unknown": []}
    assert "charter" not in json.loads(critics._prompt(bare, {})["messages"][0]["content"].rsplit("\n", 1)[0])["packet"]


def test_the_telegram_training_route_reads_the_context_and_other_seats_do_not(monkeypatch):
    from coach import coach_domain_facts as df

    monkeypatch.setattr("health.clinical_facts.clinical_context_block", lambda table, published=True: "CLINICAL BLOCK")
    physical = df._training_context("2026-10-20", "CLINICAL BLOCK")
    assert physical.startswith("CHARTER v") and "CLINICAL BLOCK" in physical and "May frame:" in physical
    assert {"physical", "training"} == set(df._TRAINING_ROUTE_KEYS)

    class _Table:  # every partition empty: only the frame, the clinical block and the context render
        def query(self, **_):
            return {"Items": []}

        def get_item(self, **_):
            return {}

    seat = df.domain_facts_block("physical_coach", _Table(), "2026-10-20")
    other = df.domain_facts_block("sleep_coach", _Table(), "2026-10-20")
    assert "CHARTER v" in seat and "CLINICAL BLOCK" in seat
    assert "CHARTER v" not in other and "CLINICAL BLOCK" in other
    monkeypatch.setattr(cc, "assemble", lambda *a, **k: 1 / 0)
    assert df._training_context("2026-10-20", "CLINICAL BLOCK") == "CLINICAL BLOCK"  # fail-soft: the bare block


def test_physical_coach_points_at_the_context_and_carries_no_charter_copy():
    cfg = json.loads((_REPO / "config" / "coaches" / "physical_coach.json").read_text())
    src = cfg["context_source"]
    mod_path, fn = src["planning_context"].split("::")
    assert (_REPO / mod_path).is_file() and callable(getattr(cc, fn))
    assert src["order_contract"].endswith("::ORDER") and cc.ORDER
    raw = json.dumps(cfg)
    assert tc.charter_value("governing_goal.target_date") not in raw and "concession_ledger" not in raw


def test_the_stale_role_play_and_the_retired_stance_file_are_gone():
    debrief = (_REPO / ".claude" / "skills" / "daily-debrief" / "SKILL.md").read_text()
    assert "Personal Board" not in debrief and "Sarah Chen" not in debrief
    assert not (_REPO / "config" / "coaches" / "training_coach_stance.json").exists()
    # #5071 box 3: the retired voice spec went too — the byline is the personas.json entry, not the spec
    assert not (_REPO / "config" / "coaches" / "training_coach.json").exists()
