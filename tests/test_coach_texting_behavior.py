"""tests/test_coach_texting_behavior.py — the character layer's texting mechanics (#2402).

Pins the Wave-2 contract of the coaching-team v2 session (2026-08-09):

  B1  split_bubbles: delimiter parsing fails soft, ceiling merges rather than drops
  B2  enforce_emoji_policy: the deterministic ceiling (≤1/reply, end-position,
      never consecutive replies) — enforcement, not a polite prompt request
  B3  run_turn: bubbles + emoji policy applied BEFORE the grounding gate, and the
      gate adjudicates the JOINED text that is actually sent
  B4  the system prompt carries the burst instruction
  B5  the worker sends one sendMessage per bubble, typing indicator between
  B6  persona_core: the shared MOS substrate prefixes every resolving persona and
      never substitutes for a missing one; the texting register renders only from
      texting_style
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from coach import coach_chat, persona_core  # noqa: E402

# ── B1: bubbles ───────────────────────────────────────────────────────────────


def test_split_bubbles_parses_delimiter_lines():
    assert coach_chat.split_bubbles("one\n---\ntwo") == ["one", "two"]


def test_split_bubbles_without_delimiter_is_one_bubble():
    assert coach_chat.split_bubbles("no delimiter, one bubble") == ["no delimiter, one bubble"]


def test_split_bubbles_overflow_merges_into_last_never_drops():
    out = coach_chat.split_bubbles("a\n---\nb\n---\nc\n---\nd")
    assert len(out) == coach_chat.MAX_BUBBLES
    assert "c" in out[-1] and "d" in out[-1]  # gated text is never truncated by a formatter


def test_split_bubbles_ignores_empty_segments_and_whitespace():
    assert coach_chat.split_bubbles("---\n\nonly one\n---\n   \n") == ["only one"]


def test_inline_dashes_are_not_a_bubble_break():
    text = "a range — like 3---4 inline --- stays prose"
    assert coach_chat.split_bubbles(text) == [text]


# ── B2: the emoji ceiling ─────────────────────────────────────────────────────


def test_single_end_position_emoji_survives():
    assert coach_chat.enforce_emoji_policy(["Real PR today 💪"]) == ["Real PR today 💪"]


def test_multiple_emoji_are_stripped_to_zero():
    # Two mid-text emoji = decorative use; the human pattern keeps none of them.
    assert coach_chat.enforce_emoji_policy(["Nice 💪 work 🔥 today"]) == ["Nice work today"]


def test_mid_text_emoji_is_stripped_even_when_single():
    assert coach_chat.enforce_emoji_policy(["Nice 💪 work today"]) == ["Nice work today"]


def test_consecutive_reply_rule_strips_everything():
    assert coach_chat.enforce_emoji_policy(["Another one 💪"], last_reply_had_emoji=True) == ["Another one"]


def test_multi_bubble_reply_keeps_at_most_one():
    out = coach_chat.enforce_emoji_policy(["first 💪", "second 📈"])
    assert out == ["first", "second 📈"]


def test_typography_is_never_touched():
    text = "sleep ·· absent — that's honest, not zero"
    assert coach_chat.enforce_emoji_policy([text]) == [text]
    assert coach_chat.has_emoji(text) is False
    assert coach_chat.has_emoji("earned 💪") is True


def test_emoji_free_reply_passes_through_unchanged():
    assert coach_chat.enforce_emoji_policy(["plain text"]) == ["plain text"]


# ── B3: run_turn integration ──────────────────────────────────────────────────


def _fake_caller(reply_text):
    return lambda body: {"content": [{"type": "text", "text": reply_text}]}


def test_run_turn_returns_bubbles_and_grounds_the_joined_text():
    seen = []

    def grounder(text):
        seen.append(text)
        return []

    result = coach_chat.run_turn(
        coach_id="sleep_coach",
        coach_name="Dr. Lisa Park",
        persona_block="",
        memory_block="",
        facts_block="",
        thread=[],
        inbound="how'd I sleep?",
        model="test-model",
        caller=_fake_caller("short answer\n---\nsecond bubble"),
        grounder=grounder,
    )
    assert result.status == "sent"
    assert result.bubbles == ["short answer", "second bubble"]
    assert result.text == "short answer\n\nsecond bubble"
    assert seen == ["short answer\n\nsecond bubble"]  # the gate saw exactly what is sent


def test_run_turn_enforces_emoji_ceiling_before_gating():
    result = coach_chat.run_turn(
        coach_id="sleep_coach",
        coach_name="Dr. Lisa Park",
        persona_block="",
        memory_block="",
        facts_block="",
        thread=[],
        inbound="hey",
        model="test-model",
        caller=_fake_caller("Nice 💪 work 🔥 today"),
        grounder=lambda text: [],
    )
    assert result.text == "Nice work today"
    assert result.bubbles == ["Nice work today"]


def test_run_turn_consecutive_emoji_rule_uses_the_flag():
    result = coach_chat.run_turn(
        coach_id="sleep_coach",
        coach_name="Dr. Lisa Park",
        persona_block="",
        memory_block="",
        facts_block="",
        thread=[],
        inbound="hey",
        model="test-model",
        caller=_fake_caller("Earned it 💪"),
        grounder=lambda text: [],
        last_reply_had_emoji=True,
    )
    assert result.text == "Earned it"


def test_held_reply_stays_one_bubble():
    result = coach_chat.run_turn(
        coach_id="sleep_coach",
        coach_name="Dr. Lisa Park",
        persona_block="",
        memory_block="",
        facts_block="",
        thread=[],
        inbound="hey",
        model="test-model",
        caller=_fake_caller("ungrounded claim"),
        grounder=lambda text: [{"type": "number", "detail": "fabricated"}],
    )
    assert result.status == "held"
    assert len(result.bubbles) == 1


# ── B4: the prompt carries the burst instruction ─────────────────────────────


def test_system_prompt_names_the_delimiter_and_ceiling():
    sysp = coach_chat.build_system_prompt("persona", "", "", "Dr. Lisa Park")
    assert coach_chat.BUBBLE_DELIM in sysp
    assert str(coach_chat.MAX_BUBBLES) in sysp


# ── B5: the worker sends bubbles ─────────────────────────────────────────────


def test_worker_sends_one_message_per_bubble(monkeypatch):
    from coach import telegram_worker_lambda as worker

    calls = []
    monkeypatch.setattr(worker, "_tg", lambda token, method, payload: calls.append((method, payload.get("text"))))
    monkeypatch.setattr(worker, "_bot_token", lambda cid: "tok")
    monkeypatch.setattr(worker, "_seen_update", lambda cid, uid: False)
    monkeypatch.setattr(worker, "_thread_today", lambda cid: [])
    monkeypatch.setattr(worker, "_facts", lambda: {})
    monkeypatch.setattr(worker, "_memory_block", lambda cid: "")
    monkeypatch.setattr(worker, "_current_tier", lambda: 0)
    monkeypatch.setattr(worker, "_s3_client", lambda: None)
    monkeypatch.setattr(worker.telegram_gateway, "is_stale", lambda ts, now: False)
    monkeypatch.setattr("time.sleep", lambda s: None)

    result = coach_chat.TurnResult("a\n\nb", "sent", bubbles=["a", "b"])
    monkeypatch.setattr(worker.coach_chat, "run_turn", lambda **kw: result)
    monkeypatch.setattr(worker.coach_chat, "turn_records", lambda *a, **kw: [])

    out = worker.lambda_handler({"coach_id": "sleep", "chat_id": 1, "text": "hi"}, None)
    assert out["ok"] is True
    sends = [c for c in calls if c[0] == "sendMessage"]
    assert [t for _, t in sends] == ["a", "b"]
    # typing indicator precedes the burst continuation
    assert calls.index(("sendMessage", "b")) > calls.index(("sendMessage", "a"))
    assert any(m == "sendChatAction" for m, _ in calls)


def test_worker_last_reply_emoji_flag_reads_the_thread():
    from coach import telegram_worker_lambda as worker

    thread = [
        {"role": "matthew", "text": "hey"},
        {"role": "coach", "text": "solid day 💪"},
    ]
    assert worker._last_reply_had_emoji(thread) is True
    assert worker._last_reply_had_emoji([{"role": "coach", "text": "plain"}]) is False
    assert worker._last_reply_had_emoji([]) is False


# ── B6: persona substrate + texting register ─────────────────────────────────


def test_shared_standard_config_loads_and_renders():
    block = persona_core.shared_block()
    assert block.startswith("YOUR SHARED STANDARD")
    assert "MISSION:" in block
    assert "RULES:" in block
    assert "WORKING MODEL OF MATTHEW" in block
    assert "BEFORE REPLYING, SILENTLY ASK:" in block
    # deterministic — the prompt-cache contract
    assert block == persona_core.shared_block()


def test_persona_block_prefixes_substrate_for_resolving_coach():
    block = persona_core.persona_block("sleep_coach")
    assert block.startswith("YOUR SHARED STANDARD")
    assert "YOUR VOICE" in block


def test_persona_block_missing_coach_stays_empty_never_substrate_only():
    # A substrate-only persona would make every degraded coach the same generic
    # person — the nameless-coach defect in a nicer shirt.
    assert persona_core.persona_block("no_such_coach") == ""


def test_texting_block_renders_only_from_texting_style():
    assert persona_core.texting_block({"coach_id": "x"}) == ""
    spec = {
        "texting_style": {
            "burst_shape": "usually one bubble",
            "emoji_posture": "essentially never",
        }
    }
    block = persona_core.texting_block(spec)
    assert block.startswith("HOW YOU TEXT")
    assert "usually one bubble" in block
    assert "essentially never" in block


# ── B7: chat long memory (CHAT#summary) ──────────────────────────────────────


class _FakeTable:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.put_calls = []

    def query(self, **kw):
        vals = kw.get("ExpressionAttributeValues", {})
        pk, pfx = vals.get(":pk"), vals.get(":pfx", "")
        rows = [i for i in self.items if i.get("pk") == pk and str(i.get("sk", "")).startswith(pfx)]
        rows.sort(key=lambda r: r["sk"], reverse=not kw.get("ScanIndexForward", True))
        limit = kw.get("Limit")
        return {"Items": rows[:limit] if limit else rows}

    def get_item(self, Key=None):
        for i in self.items:
            if i.get("pk") == Key["pk"] and i.get("sk") == Key["sk"]:
                return {"Item": i}
        return {}

    def put_item(self, Item=None, **kw):
        self.put_calls.append(Item)
        self.items.append(Item)


def _turn(pk, date, uid, role, text):
    return {"pk": pk, "sk": f"CHAT#{date}#{uid}", "role": role, "text": text}


def test_summary_written_for_last_unsummarized_past_day():
    from coach import coach_chat_summary as ccs

    pk = "COACH#sleep_coach"
    table = _FakeTable(
        [
            _turn(pk, "2026-08-07", "aa", "matthew", "slept badly"),
            _turn(pk, "2026-08-07", "ab", "coach", "opportunity was short"),
            _turn(pk, "2026-08-08", "ba", "matthew", "better tonight?"),
            _turn(pk, "2026-08-08", "bb", "coach", "protect the bedtime"),
        ]
    )
    caller = lambda body: {"content": [{"type": "text", "text": "Matthew reported poor sleep; you tied it to a short opportunity."}]}
    out = ccs.ensure_daily_summary(table, pk, "Dr. Lisa Park", caller, today="2026-08-09", cycle=13)
    assert out == "2026-08-08"  # the most recent PAST day, not the oldest
    row = table.put_calls[-1]
    assert row["sk"] == "CHAT#summary#2026-08-08"
    assert row["type"] == "chat_summary"
    assert row["cycle"] == 13


def test_summary_not_rewritten_when_row_exists():
    from coach import coach_chat_summary as ccs

    pk = "COACH#sleep_coach"
    table = _FakeTable(
        [
            _turn(pk, "2026-08-08", "ba", "matthew", "hi"),
            {"pk": pk, "sk": "CHAT#summary#2026-08-08", "type": "chat_summary", "text": "done"},
        ]
    )
    assert ccs.ensure_daily_summary(table, pk, "X", lambda b: 1 / 0, today="2026-08-09") is None


def test_summary_never_covers_today():
    from coach import coach_chat_summary as ccs

    pk = "COACH#sleep_coach"
    table = _FakeTable([_turn(pk, "2026-08-09", "aa", "matthew", "hey")])
    assert ccs.ensure_daily_summary(table, pk, "X", lambda b: {"content": []}, today="2026-08-09") is None
    assert table.put_calls == []


def test_recent_summaries_render_oldest_first():
    from coach import coach_chat_summary as ccs

    pk = "COACH#sleep_coach"
    table = _FakeTable(
        [
            {"pk": pk, "sk": "CHAT#summary#2026-08-07", "text": "day one"},
            {"pk": pk, "sk": "CHAT#summary#2026-08-08", "text": "day two"},
        ]
    )
    block = ccs.read_recent_summaries(table, pk)
    assert block.startswith("RECENT CONVERSATIONS")
    assert block.index("2026-08-07") < block.index("2026-08-08")


def test_summary_caller_failure_is_soft():
    from coach import coach_chat_summary as ccs

    pk = "COACH#sleep_coach"
    table = _FakeTable([_turn(pk, "2026-08-08", "aa", "matthew", "hey")])
    assert (
        ccs.ensure_daily_summary(table, pk, "X", lambda b: (_ for _ in ()).throw(RuntimeError("bedrock down")), today="2026-08-09") is None
    )


def test_worker_thread_reader_excludes_summary_rows():
    """CHAT#summary# sorts INSIDE the CHAT# prefix — the role filter is what
    keeps a summary from masquerading as a conversation turn."""
    from coach import telegram_worker_lambda as worker

    pk = "COACH#sleep_coach"
    table = _FakeTable(
        [
            _turn(pk, "2026-08-09", "aa", "matthew", "hi"),
            {"pk": pk, "sk": "CHAT#summary#2026-08-08", "type": "chat_summary", "text": "yesterday compressed"},
        ]
    )
    import unittest.mock as mock

    with mock.patch.object(worker, "_table", return_value=table):
        thread = worker._thread_today("sleep")
    assert [t["text"] for t in thread] == ["hi"]


# ── B8: domain fact packs (site-parity nutrition, absence-honest) ────────────


def _ddb_row(source, date, **fields):
    return {"pk": f"USER#matthew#SOURCE#{source}", "sk": f"DATE#{date}", **fields}


class _RangeTable(_FakeTable):
    def query(self, **kw):
        vals = kw.get("ExpressionAttributeValues", {})
        if ":lo" in vals:
            pk, lo, hi = vals[":pk"], vals[":lo"], vals[":hi"]
            rows = [i for i in self.items if i.get("pk") == pk and lo <= str(i.get("sk", "")) <= hi]
            rows.sort(key=lambda r: r["sk"])
            return {"Items": rows}
        return super().query(**kw)


def test_nutrition_pack_prefers_macrofactor_adaptive_like_the_site():
    from coach import coach_domain_facts as cdf
    from web.site_api_nutrition import _resolve_mf_tdee

    mf_rows = [_ddb_row("macrofactor", "2026-08-05", expenditure_kcal=2870, calories=2100)]
    table = _RangeTable(mf_rows)
    block = cdf.domain_facts_block("nutrition_coach", table, today="2026-08-09")
    site_tdee, site_label = _resolve_mf_tdee(mf_rows)
    assert str(round(site_tdee)) in block  # phone cites the site's own number
    assert "MacroFactor adaptive" in block
    assert str(round(site_tdee) - 500) in block  # ADR-152 target = TDEE - 500


def test_nutrition_pack_falls_back_to_the_shared_energy_budget():
    from coach import coach_domain_facts as cdf
    from health import tdee as health_tdee

    table = _RangeTable(
        [
            _ddb_row("withings", "2026-08-08", weight_lbs=321.6),
            {"pk": "USER#matthew", "sk": "PROFILE#v1", "height_inches": 71, "date_of_birth": "1988-01-01"},
        ]
    )
    block = cdf.domain_facts_block("nutrition", table, today="2026-08-09")
    assert "Mifflin" in block and "estimate" in block
    # True parity pin: the rendered TDEE is exactly what the shared ADR-152
    # engine computes from the same inputs (same resolve_age, same empty
    # exercise window) — not merely a similar-looking number.
    age_years, age_basis, _ = health_tdee.resolve_age("1988-01-01")
    ex = health_tdee.exercise_energy([], 321.6 * health_tdee.LB_TO_KG)
    budget = health_tdee.energy_budget(
        weight_lbs=321.6,
        height_inches=71,
        age_years=age_years,
        age_basis=age_basis,
        exercise_kcal=ex["kcal"],
        exercise_energy_days=ex["days"],
        exercise_energy_basis=ex["basis"],
    )
    assert budget is not None
    assert f"TDEE (maintenance): {budget['tdee']} kcal" in block
    assert f"calorie target: {budget['tdee'] - 500} kcal" in block


def test_nutrition_pack_states_absence_instead_of_guessing():
    from coach import coach_domain_facts as cdf

    block = cdf.domain_facts_block("nutrition", _RangeTable([]), today="2026-08-09")
    assert "not computable" in block
    assert "absent, not zero" in block  # the 45-day MacroFactor silence (#2326) stays honest


def test_sleep_pack_names_the_night_and_the_trend():
    from coach import coach_domain_facts as cdf

    rows = [
        _ddb_row("whoop", "2026-08-07", sleep_duration_hours=6.4),
        _ddb_row("whoop", "2026-08-08", sleep_duration_hours=7.2),
        _ddb_row("whoop", "2026-08-09", sleep_duration_hours=6.9),
    ]
    block = cdf.domain_facts_block("sleep_coach", _RangeTable(rows), today="2026-08-09")
    assert "night ending 2026-08-09" in block and "6.9" in block
    assert "3 recorded nights" in block


def test_physical_pack_serves_recovery_and_last_lift():
    from coach import coach_domain_facts as cdf

    rows = [
        _ddb_row("whoop", "2026-08-07", recovery_score=44),
        _ddb_row("whoop", "2026-08-08", recovery_score=52),
        _ddb_row("whoop", "2026-08-09", recovery_score=61),
        _ddb_row("hevy", "2026-08-08", title="Push Day"),
    ]
    block = cdf.domain_facts_block("physical", _RangeTable(rows), today="2026-08-09")
    assert "7-day average" in block
    assert "Last logged lift: 2026-08-08 (Push Day)" in block


def test_unpacked_coach_gets_no_domain_block():
    from coach import coach_domain_facts as cdf

    assert cdf.domain_facts_block("mind_coach", _RangeTable([]), today="2026-08-09") == ""


def test_pack_failure_is_soft():
    from coach import coach_domain_facts as cdf

    class _Boom:
        def query(self, **kw):
            raise RuntimeError("ddb down")

        def get_item(self, **kw):
            raise RuntimeError("ddb down")

    assert cdf.domain_facts_block("nutrition", _Boom(), today="2026-08-09") == ""
