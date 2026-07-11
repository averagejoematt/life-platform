"""tests/test_coach_checkin_tools.py — #915 ad-hoc coach check-in loop.

Mirrors the #422 test idiom (test_habit_reflection_tools.py): hermetic — the
DDB table is the shared FakeDdbTable, the Bedrock seam is an injected caller
(never a live call). Pins the psychology-panel contract: persisted open
questions are returned as-is (no regeneration), max 3 open, autonomy-supportive
prompt rules, skip is a zero-penalty answer, verbatim storage, and the
consumption seam's "declined to answer" framing.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import coach_checkin as cc  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_coach_checkin as tcc  # noqa: E402


def _open_item(coach_id="mind", date="2026-07-09", uid="aaaa1111", **over):
    item = {
        "pk": cc.checkin_pk(coach_id),
        "sk": f"CHECKIN#{date}#{uid}",
        "record_type": "coach_checkin",
        "coach_id": coach_id,
        "coach_name": "Dr. Nathan Reeves",
        "question": "What's been taking up the most mental space this week?",
        "tags": ["mood"],
        "status": cc.STATUS_OPEN,
        "asked_at": f"{date}T18:00:00Z",
        "provenance": "mcp",
    }
    item.update(over)
    return item


def _fresh_cycle_cache(monkeypatch, value=None):
    monkeypatch.setattr(cc, "_cycle_cache", {"value": value, "read": True})


# ── keys ─────────────────────────────────────────────────────────────────────


def test_pk_normalizes_both_id_forms():
    assert cc.checkin_pk("mind") == "COACH#mind_coach"
    assert cc.checkin_pk("mind_coach") == "COACH#mind_coach"


def test_new_checkin_sk_shape():
    sk = cc.new_checkin_sk("2026-07-10", "abcd1234")
    assert sk == "CHECKIN#2026-07-10#abcd1234"


# ── queue: persistence beats regeneration ────────────────────────────────────


def test_queue_returns_open_questions_without_regenerating(monkeypatch):
    fake = FakeDdbTable(rows=[_open_item()])
    monkeypatch.setattr(tcc, "_table_ref", fake)

    def _boom(*a, **k):
        raise AssertionError("must not generate while open questions exist")

    monkeypatch.setattr(cc, "generate_questions", _boom)
    out = tcc.tool_get_coach_checkin_queue({})
    assert out["generated"] is False
    assert len(out["open_questions"]) == 1
    q = out["open_questions"][0]
    assert q["checkin_id"] == "CHECKIN#2026-07-09#aaaa1111"
    assert q["coach_id"] == "mind"
    assert not fake.puts, "re-calls must not write new questions"


def test_queue_caps_open_questions_at_three(monkeypatch):
    rows = [_open_item(uid=f"aaaa000{i}", date=f"2026-07-0{i + 1}") for i in range(5)]
    monkeypatch.setattr(tcc, "_table_ref", FakeDdbTable(rows=rows))
    out = tcc.tool_get_coach_checkin_queue({})
    assert len(out["open_questions"]) == cc.MAX_OPEN_QUESTIONS == 3


def test_queue_returns_open_questions_oldest_first(monkeypatch):
    rows = [
        _open_item(uid="bbbb2222", date="2026-07-08", asked_at="2026-07-08T18:00:00Z"),
        _open_item(uid="aaaa1111", date="2026-07-05", asked_at="2026-07-05T18:00:00Z"),
    ]
    monkeypatch.setattr(tcc, "_table_ref", FakeDdbTable(rows=rows))
    out = tcc.tool_get_coach_checkin_queue({})
    ids = [q["checkin_id"] for q in out["open_questions"]]
    assert ids == ["CHECKIN#2026-07-05#aaaa1111", "CHECKIN#2026-07-08#bbbb2222"]


def test_answered_and_skipped_items_do_not_block_generation(monkeypatch):
    rows = [
        _open_item(uid="cccc3333", status=cc.STATUS_ANSWERED, answer="fine"),
        _open_item(uid="dddd4444", status=cc.STATUS_SKIPPED, skipped=True),
    ]
    fake = FakeDdbTable(rows=rows)
    monkeypatch.setattr(tcc, "_table_ref", fake)
    monkeypatch.setattr(tcc, "_manual_source_signal", lambda: [])
    monkeypatch.setattr(tcc, "_presence_snapshot", lambda: {})
    monkeypatch.setattr(tcc, "_adaptive_mode_snapshot", lambda: {})
    monkeypatch.setattr(tcc, "_coach_bio", lambda cid: "")
    _fresh_cycle_cache(monkeypatch)
    monkeypatch.setattr(cc, "generate_questions", lambda *a, **k: [{"question": "How are evenings feeling?", "tags": ["sleep"]}])
    out = tcc.tool_get_coach_checkin_queue({})
    assert out["generated"] is True
    assert len(fake.puts) == 1


# ── queue: generation path ───────────────────────────────────────────────────


def _wire_generation(monkeypatch, fake, questions=None, manual_signal=None, cycle=None):
    monkeypatch.setattr(tcc, "_table_ref", fake)
    monkeypatch.setattr(tcc, "_manual_source_signal", lambda: manual_signal or [])
    monkeypatch.setattr(tcc, "_presence_snapshot", lambda: {"presence_class": "present"})
    monkeypatch.setattr(tcc, "_adaptive_mode_snapshot", lambda: {"mode_label": "standard"})
    monkeypatch.setattr(tcc, "_coach_bio", lambda cid: "A test bio.")
    _fresh_cycle_cache(monkeypatch, cycle)
    if questions is not None:
        monkeypatch.setattr(cc, "generate_questions", lambda *a, **k: list(questions))


def test_generation_persists_pending_items_with_contract_fields(monkeypatch):
    fake = FakeDdbTable()
    _wire_generation(
        monkeypatch,
        fake,
        questions=[{"question": "What got in the way this week?", "tags": ["barriers"]}],
        cycle=3,
    )
    out = tcc.tool_get_coach_checkin_queue({})
    assert out["generated"] is True and out["generated_by"] == "bedrock"
    assert len(fake.puts) == 1
    item = fake.puts[0]
    assert item["pk"].startswith("COACH#") and item["pk"].endswith("_coach")
    assert item["sk"].startswith("CHECKIN#")
    assert item["status"] == "open"
    assert item["provenance"] == "mcp"
    assert item["record_type"] == "coach_checkin"
    assert item["cycle"] == 3
    assert item["question"] == "What got in the way this week?"
    assert out["open_questions"][0]["checkin_id"] == item["sk"]


def test_generation_without_cycle_omits_the_stamp(monkeypatch):
    fake = FakeDdbTable()
    _wire_generation(monkeypatch, fake, questions=[{"question": "Q?", "tags": []}], cycle=None)
    tcc.tool_get_coach_checkin_queue({})
    assert "cycle" not in fake.puts[0]


def test_generation_falls_back_deterministically_when_bedrock_fails(monkeypatch):
    fake = FakeDdbTable()
    _wire_generation(monkeypatch, fake, questions=[])  # generate_questions → [] (fail-soft)
    out = tcc.tool_get_coach_checkin_queue({"coach_id": "glucose"})
    assert out["generated_by"] == "fallback"
    assert len(fake.puts) == 1
    assert fake.puts[0]["question"] == cc.FALLBACK_QUESTIONS["glucose"]


def test_explicit_coach_override_and_unknown_coach_error(monkeypatch):
    fake = FakeDdbTable()
    _wire_generation(monkeypatch, fake, questions=[{"question": "Q?", "tags": []}])
    out = tcc.tool_get_coach_checkin_queue({"coach_id": "mind"})
    assert out["asking_coach"]["coach_id"] == "mind"
    assert out["asking_coach"]["why"] == "explicitly requested"
    err = tcc.tool_get_coach_checkin_queue({"coach_id": "astrology"})
    assert "error" in err


def test_count_arg_is_clamped(monkeypatch):
    fake = FakeDdbTable()
    captured = {}

    def _gen(coach_id, coach_name, bio, snapshot, n, caller=None):
        captured["n"] = n
        return [{"question": f"Q{i}?", "tags": []} for i in range(n)]

    _wire_generation(monkeypatch, fake)
    monkeypatch.setattr(cc, "generate_questions", _gen)
    tcc.tool_get_coach_checkin_queue({"count": 99})
    assert captured["n"] == 3


# ── coach selection ──────────────────────────────────────────────────────────

_COACHES = ["sleep", "nutrition", "training", "mind", "physical", "glucose", "labs", "explorer"]


def test_pick_coach_prefers_most_overdue_manual_channel():
    signal = [
        {"source": "notion", "label": "Notion", "days_since": 30, "stale_days": 14, "coach": "mind"},
        {"source": "macrofactor", "label": "MacroFactor", "days_since": 3, "stale_days": 2, "coach": "nutrition"},
    ]
    coach, reason = cc.pick_asking_coach(_COACHES, signal, [])
    assert coach == "mind"  # 30/14 ≈ 2.1 beats 3/2 = 1.5
    assert "longest-dark" in reason and "Notion" in reason


def test_pick_coach_never_seen_channel_is_maximally_informative():
    signal = [
        {"source": "measurements", "label": "Measurements", "days_since": None, "stale_days": 60, "coach": "physical"},
        {"source": "notion", "label": "Notion", "days_since": 20, "stale_days": 14, "coach": "mind"},
    ]
    coach, _ = cc.pick_asking_coach(_COACHES, signal, [])
    assert coach == "physical"


def test_pick_coach_rotation_fallback_is_least_recently_asked():
    # No channel is overdue → deterministic rotation.
    signal = [{"source": "notion", "label": "Notion", "days_since": 1, "stale_days": 14, "coach": "mind"}]
    recent = [
        {"coach_id": cid, "asked_at": f"2026-07-0{i + 1}T00:00:00Z"}
        for i, cid in enumerate(["sleep", "nutrition", "training", "mind", "physical", "glucose", "labs"])
    ]
    coach, reason = cc.pick_asking_coach(_COACHES, signal, recent)
    assert coach == "explorer"  # never asked → sorts first
    assert "rotation" in reason


def test_pick_coach_rotation_ties_resolve_by_canonical_order():
    coach, _ = cc.pick_asking_coach(_COACHES, [], [])
    assert coach == "sleep"


# ── prompt contract (psychology panel) ───────────────────────────────────────


def test_prompt_encodes_autonomy_rules_and_json_shape():
    body = cc.build_generation_prompt("mind", "Dr. Nathan Reeves", "Bio.", {"presence": {}}, 3)
    system = body["system"][0]["text"]
    assert "AUTONOMY-SUPPORTIVE" in system
    assert "did you take your supplements?" in system  # the forbidden example is spelled out
    assert "ZERO penalty" in system
    assert "guilt" in system
    assert '"questions"' in system
    assert body["model"] == cc.MODEL
    user = body["messages"][0]["content"]
    assert "exactly 3 check-in question(s)" in user


def test_prompt_flags_dark_presence_for_barrier_framing():
    dark = cc.build_generation_prompt("mind", "N", "", {"presence": {"presence_class": "dark"}}, 2)
    assert "rule 3 applies to EVERY question" in dark["messages"][0]["content"]
    present = cc.build_generation_prompt("mind", "N", "", {"presence": {"presence_class": "present"}}, 2)
    assert "rule 3 applies" not in present["messages"][0]["content"]


def test_generate_questions_parses_injected_caller_and_caps():
    payload = {"questions": [{"question": f"Q{i}?", "tags": ["a", "b", "c", "d"]} for i in range(5)]}
    caller = lambda body: {"content": [{"type": "text", "text": json.dumps(payload)}]}  # noqa: E731
    qs = cc.generate_questions("mind", "N", "", {}, 3, caller=caller)
    assert len(qs) == 3
    assert qs[0]["tags"] == ["a", "b", "c"]  # tags capped at 3


def test_generate_questions_fail_soft_on_error_and_garbage():
    def _raise(body):
        raise RuntimeError("bedrock down")

    assert cc.generate_questions("mind", "N", "", {}, 3, caller=_raise) == []
    garbage = lambda body: {"content": [{"type": "text", "text": "not json"}]}  # noqa: E731
    assert cc.generate_questions("mind", "N", "", {}, 3, caller=garbage) == []


def test_parse_questions_strips_markdown_fences():
    text = '```json\n{"questions": [{"question": "Q?", "tags": ["x"]}]}\n```'
    assert cc.parse_questions(text) == [{"question": "Q?", "tags": ["x"]}]


# ── log tool ─────────────────────────────────────────────────────────────────


def test_log_answer_records_verbatim(monkeypatch):
    fake = FakeDdbTable(rows=[_open_item()])
    monkeypatch.setattr(tcc, "_table_ref", fake)
    answer = "Honestly? Work ate the week — I wasn't avoiding it, I just never sat down."
    out = tcc.tool_log_coach_checkin({"checkin_id": "CHECKIN#2026-07-09#aaaa1111", "coach_id": "mind", "answer": answer})
    assert out["status"] == "saved" and out["outcome"] == "answered"
    upd = fake.updates[0]
    assert upd["Key"] == {"pk": "COACH#mind_coach", "sk": "CHECKIN#2026-07-09#aaaa1111"}
    vals = upd["ExpressionAttributeValues"]
    assert vals[":ans"] == answer  # verbatim — byte-for-byte
    assert vals[":st"] == "answered"
    assert vals[":sk"] is False
    assert vals[":prov"] == "mcp"


def test_log_skip_is_zero_penalty(monkeypatch):
    fake = FakeDdbTable(rows=[_open_item()])
    monkeypatch.setattr(tcc, "_table_ref", fake)
    out = tcc.tool_log_coach_checkin({"checkin_id": "CHECKIN#2026-07-09#aaaa1111", "skip": True})
    assert out["outcome"] == "skipped"
    assert "zero penalty" in out["message"]
    vals = fake.updates[0]["ExpressionAttributeValues"]
    assert vals[":st"] == "skipped" and vals[":sk"] is True
    assert ":ans" not in vals


def test_log_finds_item_without_coach_hint(monkeypatch):
    fake = FakeDdbTable(rows=[_open_item(coach_id="glucose", coach_name="Dr. Amara Patel")])
    monkeypatch.setattr(tcc, "_table_ref", fake)
    out = tcc.tool_log_coach_checkin({"checkin_id": "CHECKIN#2026-07-09#aaaa1111", "answer": "the sensor lapsed while traveling"})
    assert out["status"] == "saved"
    assert fake.updates[0]["Key"]["pk"] == "COACH#glucose_coach"


def test_log_requires_answer_or_skip_and_valid_id(monkeypatch):
    monkeypatch.setattr(tcc, "_table_ref", FakeDdbTable(rows=[_open_item()]))
    assert "error" in tcc.tool_log_coach_checkin({"checkin_id": "CHECKIN#2026-07-09#aaaa1111"})
    assert "error" in tcc.tool_log_coach_checkin({"answer": "x"})
    assert "error" in tcc.tool_log_coach_checkin({"checkin_id": "CHECKIN#2026-01-01#missing00", "answer": "x"})


# ── consumption seam ─────────────────────────────────────────────────────────


def test_recent_checkins_block_formats_answers_and_skips():
    rows = [
        _open_item(
            uid="eeee5555",
            status=cc.STATUS_ANSWERED,
            answer="It was travel, mostly.",
            answered_at="2026-07-08T20:00:00Z",
        ),
        _open_item(
            coach_id="nutrition",
            coach_name="Dr. Marcus Webb",
            uid="ffff6666",
            status=cc.STATUS_SKIPPED,
            skipped=True,
            answered_at="2026-07-07T20:00:00Z",
        ),
        _open_item(uid="gggg7777"),  # still open — must not appear
    ]
    block = cc.recent_checkins_block(table=FakeDdbTable(rows=rows), coach_ids=["mind", "nutrition"])
    assert "RECENT COACH CHECK-IN ANSWERS" in block
    assert 'A (verbatim): "It was travel, mostly."' in block
    assert "(declined to answer — respect that)" in block
    assert "Dr. Marcus Webb" in block
    assert "gggg7777" not in block and block.count("Q:") == 2


def test_recent_checkins_block_caps_items():
    rows = [
        _open_item(uid=f"aaaa00{i:02d}", status=cc.STATUS_ANSWERED, answer=f"answer {i}", answered_at=f"2026-07-0{(i % 8) + 1}T00:00:00Z")
        for i in range(10)
    ]
    block = cc.recent_checkins_block(max_items=2, table=FakeDdbTable(rows=rows), coach_ids=["mind"])
    assert block.count("A (verbatim)") == 2


def test_recent_checkins_block_empty_and_fail_soft():
    assert cc.recent_checkins_block(table=FakeDdbTable(), coach_ids=["mind"]) == ""

    class _Boom:
        def query(self, **kw):
            raise RuntimeError("ddb down")

    assert cc.recent_checkins_block(table=_Boom(), coach_ids=["mind"]) == ""


# ── cycle stamp ──────────────────────────────────────────────────────────────


def test_read_cycle_fail_soft_and_cached(monkeypatch):
    monkeypatch.setattr(cc, "_cycle_cache", {"value": None, "read": False})
    calls = {"n": 0}

    class _Ssm:
        def get_parameter(self, Name):
            calls["n"] += 1
            raise RuntimeError("AccessDenied")

    assert cc.read_cycle(ssm_client=_Ssm()) is None
    assert cc.read_cycle(ssm_client=_Ssm()) is None
    assert calls["n"] == 1  # container-lifetime cache


def test_read_cycle_parses_int(monkeypatch):
    monkeypatch.setattr(cc, "_cycle_cache", {"value": None, "read": False})

    class _Ssm:
        def get_parameter(self, Name):
            assert Name == "/life-platform/experiment-cycle"
            return {"Parameter": {"Value": "2"}}

    assert cc.read_cycle(ssm_client=_Ssm()) == 2


# ── registry wiring ──────────────────────────────────────────────────────────


def test_tools_are_registered_with_known_audit_verbs():
    from mcp import audit
    from mcp.registry import TOOLS

    for name in ("get_coach_checkin_queue", "log_coach_checkin"):
        assert name in TOOLS
        assert TOOLS[name]["schema"]["name"] == name
    assert audit.is_write_tool("log_coach_checkin") is True
    assert audit.is_write_tool("get_coach_checkin_queue") is False  # documented trade-off (#915)
