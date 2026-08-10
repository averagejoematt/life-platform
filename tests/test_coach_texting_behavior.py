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
  B11 availability voice (#2495): budget-pause/daily-cap replies render per
      persona via run_turn's persona_id, not one shared string
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


# ── B9: time-gap awareness (#2489) ────────────────────────────────────────────
#
# "been a minute" after a quiet week. The line is folded into
# ``read_recent_summaries`` rather than added at a new call site — see the
# module docstring in ``coach_chat_summary.py`` for why (the actual assembly
# point, ``telegram_worker_lambda._memory_block``, is a concurrently-edited,
# size-guarded file this feature must not touch).


def test_no_gap_line_on_a_genuinely_empty_partition():
    """Never invent a gap that isn't there: a coach Matthew has never texted
    must not open with 'been a minute' — there is nothing to be quiet about."""
    from coach import coach_chat_summary as ccs

    pk = "COACH#training_coach"
    table = _FakeTable([])
    assert ccs.time_gap_line(table, pk, today="2026-08-10") == ""


def test_no_gap_line_within_the_quiet_threshold():
    """A same-day or few-day-old thread is normal texting, not a gap — the coach
    must never remark on it."""
    from coach import coach_chat_summary as ccs

    pk = "COACH#sleep_coach"
    table = _FakeTable([_turn(pk, "2026-08-05", "aa", "matthew", "hey")])
    # 2026-08-10 minus 2026-08-05 = 5 days, under QUIET_GAP_DAYS (7).
    assert ccs.time_gap_line(table, pk, today="2026-08-10") == ""


def test_no_gap_line_the_same_day_as_the_last_turn():
    from coach import coach_chat_summary as ccs

    pk = "COACH#sleep_coach"
    table = _FakeTable([_turn(pk, "2026-08-10", "aa", "matthew", "morning")])
    assert ccs.time_gap_line(table, pk, today="2026-08-10") == ""


def test_gap_line_present_and_exact_format_past_the_threshold():
    from coach import coach_chat_summary as ccs

    pk = "COACH#nutrition_coach"
    table = _FakeTable([_turn(pk, "2026-08-01", "aa", "matthew", "how's my protein")])
    # 2026-08-10 minus 2026-08-01 = 9 days, past QUIET_GAP_DAYS (7).
    line = ccs.time_gap_line(table, pk, today="2026-08-10")
    assert line == (
        "TIME GAP: it has been 9 days since your last conversation with Matthew (you last texted on "
        "2026-08-01). That is a real quiet stretch, not an ongoing thread — acknowledge it naturally and briefly, "
        "the way a person notices time passed with someone they know ('hey, been a minute'), then move on to what "
        "he actually said. Never mention this, or any gap, when the thread has been active."
    )


def test_gap_line_triggers_exactly_at_the_threshold_boundary():
    """QUIET_GAP_DAYS is inclusive: exactly 7 days is already a quiet week."""
    from coach import coach_chat_summary as ccs

    pk = "COACH#mind_coach"
    table = _FakeTable([_turn(pk, "2026-08-03", "aa", "matthew", "hey")])
    assert ccs.time_gap_line(table, pk, today="2026-08-10") != ""
    table6 = _FakeTable([_turn(pk, "2026-08-04", "aa", "matthew", "hey")])
    assert ccs.time_gap_line(table6, pk, today="2026-08-10") == ""


def test_gap_line_uses_the_real_turn_date_not_a_lagging_summary_row():
    """A summary is written lazily on the FOLLOWING day's first turn, so its date
    can lag the true last-chat date. The gap must be computed from the real
    CHAT# turn, never the CHAT#summary# row."""
    from coach import coach_chat_summary as ccs

    pk = "COACH#sleep_coach"
    table = _FakeTable(
        [
            _turn(pk, "2026-08-01", "aa", "matthew", "hey"),
            {"pk": pk, "sk": "CHAT#summary#2026-08-01", "type": "chat_summary", "text": "he said hey"},
        ]
    )
    assert ccs._latest_chat_date(table, pk) == "2026-08-01"
    assert ccs.time_gap_line(table, pk, today="2026-08-10") != ""


def test_read_recent_summaries_prepends_the_gap_line_when_both_present():
    from coach import coach_chat_summary as ccs

    pk = "COACH#sleep_coach"
    table = _FakeTable(
        [
            _turn(pk, "2026-08-01", "aa", "matthew", "hey"),
            {"pk": pk, "sk": "CHAT#summary#2026-08-01", "text": "day one"},
        ]
    )
    block = ccs.read_recent_summaries(table, pk, today="2026-08-10")
    assert block.startswith("TIME GAP:")
    assert "RECENT CONVERSATIONS" in block
    assert block.index("TIME GAP") < block.index("RECENT CONVERSATIONS")


def test_read_recent_summaries_unaffected_when_no_gap_and_no_summaries():
    """The existing no-history behaviour ('') must be untouched by this feature."""
    from coach import coach_chat_summary as ccs

    pk = "COACH#career_coach"
    table = _FakeTable([])
    assert ccs.read_recent_summaries(table, pk, today="2026-08-10") == ""


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


def test_unpacked_coach_gets_no_domain_facts_section():
    """A coach with no domain pack contributes no DOMAIN FACTS — but since the
    cycle-13 experiment-awareness slice every texting coach still gets the frame
    (see tests/test_coach_experiment_awareness.py)."""
    from coach import coach_domain_facts as cdf

    block = cdf.domain_facts_block("mind_coach", _RangeTable([]), today="2026-08-09")
    assert "YOUR DOMAIN FACTS" not in block
    assert "EXPERIMENT FRAME:" in block


def test_pack_failure_is_soft():
    from coach import coach_domain_facts as cdf

    class _Boom:
        def query(self, **kw):
            raise RuntimeError("ddb down")

        def get_item(self, **kw):
            raise RuntimeError("ddb down")

    # Storage down costs the DDB-backed sections, never the whole block: the
    # experiment frame is computed from constants and still renders.
    block = cdf.domain_facts_block("nutrition", _Boom(), today="2026-08-09")
    assert "YOUR DOMAIN FACTS" not in block
    assert "Your open call" not in block


# ── B9: chat-tier routing (v2 roster) ────────────────────────────────────────


def test_headcoach_route_resolves_eli_not_string_surgery():
    from coach.persona_registry import persona_for_telegram_route

    pid, p = persona_for_telegram_route("headcoach")
    assert pid == "eli_marsh" and p["name"] == "Dr. Eli Marsh"
    # The retired seat's route is a SUCCESSION alias, not a dead key: the chat
    # Matthew already has open continues with the coach who absorbed the lane.
    assert persona_for_telegram_route("training")[0] == "physical_coach"
    # A route nobody claims still fails closed.
    assert persona_for_telegram_route("astrology") == (None, None)


def test_worker_partitions_chat_tier_by_persona(monkeypatch):
    """The head-coach chat must land in ONE partition derived from the persona,
    not the route string — and the persona/voice must be Eli's."""
    from coach import telegram_worker_lambda as worker

    calls, stored = [], []
    monkeypatch.setattr(worker, "_tg", lambda token, method, payload: calls.append((method, payload.get("text"))))
    monkeypatch.setattr(worker, "_bot_token", lambda cid: "tok")
    monkeypatch.setattr(worker, "_seen_update", lambda cid, uid: False)
    monkeypatch.setattr(worker, "_thread_today", lambda cid: stored.append(("thread", cid)) or [])
    monkeypatch.setattr(worker, "_facts", lambda: {})
    monkeypatch.setattr(worker, "_memory_block", lambda cid: stored.append(("memory", cid)) or "")
    monkeypatch.setattr(worker, "_current_tier", lambda: 3)  # budget-paused: no bedrock call needed
    monkeypatch.setattr(worker, "_s3_client", lambda: None)
    monkeypatch.setattr(worker.telegram_gateway, "is_stale", lambda ts, now: False)
    monkeypatch.setattr(worker.coach_chat, "turn_records", lambda *a, **kw: [])

    out = worker.lambda_handler({"coach_id": "headcoach", "chat_id": 1, "text": "hey"}, None)
    assert out["ok"] is True
    assert ("thread", "eli_marsh") in stored and ("memory", "eli_marsh") in stored


def test_eli_voice_spec_loads_offline():
    from coach import persona_core

    spec = persona_core.load_voice_spec("eli_marsh", force_refresh=True)
    assert spec and spec["display_name"] == "Dr. Eli Marsh"
    assert persona_core.texting_block(spec).startswith("HOW YOU TEXT")
    block = persona_core.persona_block("eli_marsh")
    assert "YOUR SHARED STANDARD" in block and "one decision" in block.lower()


# ── B10: conversation continuity (go-live QA, 2026-08-09 evening) ────────────


def test_system_prompt_carries_the_conversation_rules():
    sysp = coach_chat.build_system_prompt("persona", "", "", "Dr. Lisa Park")
    assert "shared memory, not a to-do list" in sysp
    assert "never restate a number" in sysp
    assert "Do NOT open with your domain data" in sysp
    assert "Never announce the current date" in sysp
    assert "now that I can see it" in sysp


def test_colleagues_block_joins_the_prompt_between_persona_and_memory():
    sysp = coach_chat.build_system_prompt("persona", "MEMORY", "FACTS", "Dr. Lisa Park", colleagues_block="YOUR COLLEAGUES:\n- X")
    assert "YOUR COLLEAGUES" in sysp
    assert sysp.index("YOUR COLLEAGUES") < sysp.index("MEMORY")


def test_worker_colleagues_block_names_and_pronouns():
    import unittest.mock as mock

    from coach import telegram_worker_lambda as worker

    with mock.patch.object(worker, "_s3_client", return_value=None):
        block = worker._colleagues_block("sleep_coach")
    assert "Dr. Nathan Reeves (he/him)" in block
    assert "Dr. Max Reyes (he/him)" in block
    assert "Dr. Lisa Park" not in block  # never lists the coach to themself
    assert "Dr. Amara Patel (she/her)" in block  # consulting tier is citable by name
    assert "Dr. Sarah Chen" not in block  # retired seats are not colleagues to cite


# ── B10: team texture + track-record humility (#2496) ────────────────────────
#
# Two grounded reads of rows that already existed and were never surfaced in chat:
# the coach's OWN graded calls (misses first-class) and the inter-coach threads it
# was actually a party to. The rendering half is pinned here; the gate that stops an
# invented meeting lives in tests/test_coach_chat_grounding.py.
#
# Wall-clock discipline: every date below is injected. Nothing reads the real clock.


def _pred(coach="sleep_coach", claim="a call", status="pending", made="2026-08-11", graded=None, **fields):
    rec = {
        "pk": f"COACH#{coach}",
        "sk": f"PREDICTION#{made}-{abs(hash(claim)) % 9973}",
        "claim_natural": claim,
        "status": status,
        "confidence": 0.7,
        "created_date": made,
    }
    if graded:
        rec["outcome_date"] = graded
    rec.update(fields)
    return rec


def _thread(
    a="sleep_coach", b="nutrition_coach", when="2026-08-09T18:20:00+00:00", topic="whether the deficit is eating his sleep", **fields
):
    rec = {
        "pk": "ENSEMBLE#dispute",
        "sk": f"THREAD#2026-W32#{topic[:20].replace(' ', '_')}",
        "coach_a": a,
        "coach_b": b,
        "topic": topic,
        "created_at": when,
        "turns": [
            {"speaker": a, "name": "Dr. Lisa Park", "line": "He is under-slept because he is under-fed.", "kind": "position"},
            {"speaker": b, "name": "Dr. Nathan Reeves", "line": "The deficit is 500 kcal and it is not the cause.", "kind": "reply"},
        ],
    }
    rec.update(fields)
    return rec


class _RecordingTable(_FakeTable):
    """_FakeTable plus the kwargs boto3 actually saw — the phase-filter pin and the
    one-query pin are both assertions about the CALL, invisible in the result."""

    def __init__(self, items=None):
        super().__init__(items)
        self.query_kwargs = []

    def query(self, **kw):
        self.query_kwargs.append(kw)
        return super().query(**kw)


def _block(coach="sleep_coach", items=(), today="2026-08-12"):
    from coach import coach_domain_facts as cdf

    return cdf.domain_facts_block(coach, _FakeTable(list(items)), today=today)


# — the graded record —


def test_a_coach_names_its_own_miss_as_plainly_as_its_hit():
    """Track-record humility is the whole point: a coach that only quotes its live
    positions is a brochure. WRONG is stated as a word, not implied by an absence."""
    block = _block(items=[_pred(claim="HRV climbs on a 10pm lights-out", status="refuted", graded="2026-08-11")])
    assert "YOUR TRACK RECORD" in block
    assert 'Graded WRONG: "HRV climbs on a 10pm lights-out" (made 2026-08-11, graded 2026-08-11).' in block


def test_a_miss_keeps_its_slot_when_newer_hits_would_crowd_it_out():
    """The selection rule, and the reason it is not plain recency: three fresh hits
    would bury the one refuted call, and a coach is not allowed to present a
    flattering sample of its own record as its record (ADR-104/105)."""
    from coach import coach_team_texture as ctt

    items = [
        _pred(claim="hit three", status="confirmed", made="2026-08-08", graded="2026-08-11"),
        _pred(claim="hit two", status="confirmed", made="2026-08-07", graded="2026-08-10"),
        _pred(claim="hit one", status="confirmed", made="2026-08-06", graded="2026-08-09"),
        _pred(claim="the one he got wrong", status="refuted", made="2026-08-02", graded="2026-08-05"),
    ]
    lines = ctt.terminal_prediction_lines(items)
    assert sum(1 for ln in lines if ln.startswith("Graded ")) == ctt.MAX_TERMINAL_CALLS == 2
    assert any("the one he got wrong" in ln and "WRONG" in ln for ln in lines)
    assert any("hit three" in ln for ln in lines)  # the newest still leads
    # mutation-proof: with no miss to protect, the slots go to the newest two hits
    hits_only = [i for i in items if i["status"] == "confirmed"]
    assert not any("wrong" in ln.lower() for ln in ctt.terminal_prediction_lines(hits_only)[:-1])


def test_the_record_line_carries_n_and_never_counts_an_undecidable_call_as_a_hit():
    """ADR-105: uncertainty and n on every statistical claim. 'inconclusive' and
    'expired' are terminal but they are not outcomes — folding them into either
    column would be the fabrication class aimed at the coach's own record."""
    from coach import coach_team_texture as ctt

    lines = ctt.terminal_prediction_lines(
        [
            _pred(claim="a hit", status="confirmed", graded="2026-08-10"),
            _pred(claim="a miss", status="refuted", graded="2026-08-09"),
            _pred(claim="never decidable", status="inconclusive", graded="2026-08-08"),
            _pred(claim="ran out of window", status="expired", graded="2026-08-07"),
        ]
    )
    assert "Your graded record this cycle: 1 right, 1 wrong out of 2 decided calls" in lines[-1]
    assert "2 more could not be decided — those count as neither" in lines[-1]


def test_a_coach_with_calls_but_none_graded_says_so_rather_than_implying_a_record():
    block = _block(items=[_pred(claim="still open", status="pending")])
    assert "None of your calls has been graded yet this cycle" in block


def test_one_prediction_query_serves_both_the_open_calls_and_the_graded_ones():
    """The chat turn is latency-bound. Two renderers over one partition must not
    become two round-trips."""
    from coach import coach_domain_facts as cdf

    table = _RecordingTable([_pred(claim="open one"), _pred(claim="closed one", status="confirmed", graded="2026-08-10")])
    cdf.domain_facts_block("sleep_coach", table, today="2026-08-12")
    prediction_queries = [q for q in table.query_kwargs if q["ExpressionAttributeValues"].get(":prefix") == "PREDICTION#"]
    assert len(prediction_queries) == 1


# — the team room —


def test_the_team_room_names_the_day_the_colleague_and_both_recorded_lines():
    block = _block(items=[_thread()])
    from coach import coach_team_texture as ctt

    assert ctt.TEAM_ROOM_HEADING in block
    assert "Sunday 2026-08-09 — you and Dr. Nathan Reeves went back and forth about" in block
    assert "He is under-slept because he is under-fed." in block
    assert "The deficit is 500 kcal and it is not the cause." in block


def test_a_thread_the_coach_was_not_a_party_to_is_not_its_memory():
    """Overhearing is not participating. A coach may only say 'we talked' about an
    exchange it was actually in."""
    from coach import coach_team_texture as ctt

    block = _block(coach="mind_coach", items=[_thread()])
    assert ctt.TEAM_ROOM_EMPTY_HEADING in block


def test_a_thread_that_cannot_be_placed_on_a_day_is_dropped_rather_than_dated():
    """Half a memory is not a memory: a thread with no timestamp names no day, and a
    day the coach cannot source is a day it may not claim."""
    from coach import coach_team_texture as ctt

    assert ctt.team_meeting_lines("sleep_coach", _FakeTable([_thread(created_at="")])) == []
    # mutation-proof: the same reader DOES render the identical thread once it is dated
    assert ctt.team_meeting_lines("sleep_coach", _FakeTable([_thread()]))


def test_a_one_sided_thread_is_dropped_rather_than_half_quoted():
    solo = _thread()
    solo["turns"] = [solo["turns"][0]]
    from coach import coach_team_texture as ctt

    assert ctt.team_meeting_lines("sleep_coach", _FakeTable([solo])) == []


def test_the_absence_form_renders_rather_than_silence():
    """The empty heading is not decoration — it is the gate's evidence, and a coach
    told nothing about its team fills the silence from the persona's general idea of
    what a coaching staff does."""
    from coach import coach_team_texture as ctt

    block = _block()
    assert ctt.TEAM_ROOM_EMPTY_HEADING in block
    assert "do not say you did, in any wording" in block


def test_a_chat_tier_coach_reads_no_dispute_partition_at_all():
    """Eli is not a party to an inter-coach thread, so the read could only return
    nothing — and the absence line already tells him so, in words."""
    from coach import coach_domain_facts as cdf, coach_team_texture as ctt

    table = _RecordingTable([_thread()])
    block = cdf.domain_facts_block("eli_marsh", table, today="2026-08-12")
    assert ctt.TEAM_ROOM_EMPTY_HEADING in block
    # Scoped to the DISPUTE partition, which is the property under test. #2493 added a
    # weather read that every texting coach makes, so "no queries at all" would now
    # assert something this test never meant.
    #
    # Scope on :pk, NOT :prefix. The dispute read is pk=ENSEMBLE#dispute /
    # prefix=THREAD# (coach_team_texture.py:132), so a :prefix filter looking for
    # "ENSEMBLE" matches nothing whether or not the read happens — it would pass
    # vacuously and guard exactly nothing. Derived from the module's own constant
    # so a repartition renames it here too.
    dispute_reads = [kw for kw in table.query_kwargs if kw.get("ExpressionAttributeValues", {}).get(":pk") == ctt.DISPUTE_PK]
    assert not dispute_reads, table.query_kwargs


def test_the_dispute_read_goes_through_the_phase_filter(monkeypatch):
    """ADR-058/#1085: the restart wipe tombstones + pilot-tags every ENSEMBLE#dispute
    thread, and an unguarded read has already shipped a WIPED cycle's argument to a
    reader surface once. A coach recounting a deleted cycle's meeting is that bug
    with a warmer voice. The wrapper is invisible in the RESULT, so the pin is on the
    call."""
    from coach import coach_team_texture as ctt
    from experiment import phase_filter

    seen = []
    real = phase_filter.with_phase_filter

    def spy(kwargs, **kw):
        seen.append(dict(kwargs))
        return real(kwargs, **kw)

    monkeypatch.setattr(phase_filter, "with_phase_filter", spy)
    table = _RecordingTable([_thread()])
    ctt.team_meeting_lines("sleep_coach", table)
    assert any(s["ExpressionAttributeValues"][":pk"] == "ENSEMBLE#dispute" for s in seen)
    dispute_query = [q for q in table.query_kwargs if q["ExpressionAttributeValues"].get(":pk") == "ENSEMBLE#dispute"][0]
    assert dispute_query["ExpressionAttributeValues"][":phase_experiment"] == "experiment"


def test_a_storage_failure_costs_the_section_and_never_opens_the_gate():
    """Fail-soft has a direction here. The absence form is the SAFE state (the gate
    then refuses every team-meeting claim); failing open would be the one
    unacceptable outcome."""
    from coach import coach_team_texture as ctt

    class _Boom:
        def query(self, **kw):
            raise RuntimeError("ddb down")

        def get_item(self, **kw):
            raise RuntimeError("ddb down")

    assert ctt.team_meeting_lines("sleep_coach", _Boom()) == []
    assert ctt.TEAM_ROOM_EMPTY_HEADING in ctt.team_room_section([])


# ── B11: availability voice — budget-pause/daily-cap replies (#2495) ─────────


def test_budget_refusal_renders_in_persona_voice_when_paused():
    generic = coach_chat.budget_refusal(2, 0)
    sleep_voice = coach_chat.budget_refusal(2, 0, persona_id="sleep_coach")
    nutrition_voice = coach_chat.budget_refusal(2, 0, persona_id="nutrition_coach")
    assert sleep_voice != generic
    assert sleep_voice != nutrition_voice
    assert "2" in sleep_voice  # the tier is still stated, in whichever voice


def test_budget_refusal_renders_in_persona_voice_when_capped():
    generic = coach_chat.budget_refusal(0, coach_chat.DAILY_TURN_CAP)
    sleep_voice = coach_chat.budget_refusal(0, coach_chat.DAILY_TURN_CAP, persona_id="sleep_coach")
    assert sleep_voice != generic
    assert str(coach_chat.DAILY_TURN_CAP) in sleep_voice


def test_run_turn_passes_persona_id_through_to_the_refusal():
    """run_turn's new persona_id param (#2495) must actually reach
    budget_refusal — a signature change that changes nothing is worse than no
    change at all."""
    result = coach_chat.run_turn(
        coach_id="some-route-string-not-a-persona-id",
        persona_id="nutrition_coach",
        coach_name="Dr. Marcus Webb",
        persona_block="",
        memory_block="",
        facts_block="",
        thread=[],
        inbound="hey",
        model="test-model",
        caller=_fake_caller("unused — refused before inference"),
        grounder=lambda text: [],
        tier=3,
    )
    assert result.status == "paused"
    assert result.text == coach_chat.budget_refusal(3, 0, persona_id="nutrition_coach")


def test_run_turn_falls_back_to_coach_id_when_no_persona_id_given():
    """Older-shaped call sites (coach_id already equal to a persona id) still get
    a coherent, persona-voiced reply without passing persona_id explicitly —
    run_turn falls back to coach_id."""
    result = coach_chat.run_turn(
        coach_id="sleep_coach",
        coach_name="Dr. Lisa Park",
        persona_block="",
        memory_block="",
        facts_block="",
        thread=[],
        inbound="hey",
        model="test-model",
        caller=_fake_caller("unused"),
        grounder=lambda text: [],
        tier=2,
    )
    assert result.status == "paused"
    assert result.text == coach_chat.budget_refusal(2, 0, persona_id="sleep_coach")


# ── The inbound message is evidence (live regression, 2026-08-10) ─────────────


def test_the_inbound_message_reaches_the_grounder_on_the_path_that_carries_his_words():
    """A number Matthew states in his own message must be quotable back to him.

    The live failure: he texted "...just doing a 2.5 mile walk outside instead",
    the reply held TWICE on `fabricated_number`, and he got the deferral string.
    `_assemble` runs BEFORE the turn, so `a["thread"]` holds only PRIOR turns —
    the current message reached the MODEL (`inbound=text`) but not the GATE, so
    the coach could not acknowledge anything he had just said that carried a
    number.

    Pinned at the call site, not on the gate: `build_grounder` was always capable
    of widening on an extra source, and a gate-level test passes with the bug
    still in place. The defect was the wiring.

    Deliberately NOT a blanket rule over every `run_turn` — the other two callers
    are correct as they stand: `_maybe_refer` passes its conversation `tail`, and
    `_morning_checkin`'s frame is a static constant with no numbers in it. This
    pins the one path whose `inbound` is Matthew's own text.
    """
    import ast
    import os

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "lambdas",
        "coach",
        "telegram_worker_lambda.py",
    )
    tree = ast.parse(open(path, encoding="utf-8").read())

    checked = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "run_turn"):
                continue
            kw = {k.arg: k.value for k in node.keywords}
            inbound = kw.get("inbound")
            grounder = kw.get("grounder")
            if inbound is None or grounder is None:
                continue
            # Only the path whose inbound is the raw user message.
            if not (isinstance(inbound, ast.Name) and inbound.id == "text"):
                continue
            checked += 1
            sources = {ast.unparse(arg) for arg in grounder.args}
            assert "text" in sources, (
                f"{fn.name}: run_turn gets inbound=text but its grounder is "
                f"{ast.unparse(grounder)} — the message he just sent must be an "
                f"evidence source, or every number he states reads as fabricated"
            )

    assert checked == 1, f"expected exactly one inbound=text run_turn call site, found {checked}"


# ── B12: weather texture, grounder-safe (#2493) ──────────────────────────────
#
# The coach package contained the word "weather" zero times before this: a coach
# could not say "nice break in the rain" without inventing it, so it either didn't
# say it or said something ungrounded. The row exists and is fresh; this makes it a
# SOURCE. Day-of-week texture is deliberately NOT here — `_current_moment_line()`
# has shipped it since the humanity pass.

_WEATHER_FIELDS = dict(
    condition="Overcast",
    temp_high_f=68.4,
    temp_low_f=55.1,
    precipitation_mm=0,
    humidity_pct=71.2,
    wind_speed_max_mph=9.4,
    aqi=32,
    sunrise_local="05:57",
    sunset_local="20:38",
    daylight_hours=14.68,
)


def test_weather_renders_from_the_row_for_every_texting_coach():
    """Weather is texture, not one seat's domain fact — the sleep coach cares about
    sunrise and the performance coach about heat, so it renders next to the
    experiment frame rather than inside a pack."""
    from coach import coach_domain_facts as cdf

    table = _RangeTable([_ddb_row("weather", "2026-08-09", **_WEATHER_FIELDS)])
    for coach in ("nutrition", "sleep_coach", "physical", "mind_coach", "eli_marsh"):
        block = cdf.domain_facts_block(coach, table, today="2026-08-09")
        assert "TODAY'S CONDITIONS" in block, coach
        assert "Overcast" in block and "high 68F" in block and "low 55F" in block, coach
        assert "humidity 71%" in block and "wind up to 9 mph" in block and "AQI 32" in block, coach
        assert "no measurable precipitation" in block, coach  # a measured zero is a measurement
        assert "Sunrise 05:57, sunset 20:38" in block and "14.7 h of daylight" in block, coach


def test_weather_absence_renders_nothing_at_all():
    """ADR-104: no row for the day means the coach has no weather in its vocabulary
    — never a seasonal default, and never an 'absent' heading it could text about."""
    from coach import coach_domain_facts as cdf

    block = cdf.domain_facts_block("sleep_coach", _RangeTable([]), today="2026-08-09")
    assert "TODAY'S CONDITIONS" not in block and "Weather" not in block
    assert "EXPERIMENT FRAME:" in block  # the rest of the block is unaffected


def test_yesterdays_weather_is_never_relabelled_as_todays():
    """The window is the single named day, matched on its exact DATE# key. A stale
    row is absence, not today's sky — the #2343 day-correspondence class applied to
    a source the night map does not cover."""
    from coach import coach_domain_facts as cdf

    table = _RangeTable([_ddb_row("weather", "2026-08-08", **_WEATHER_FIELDS)])
    assert "TODAY'S CONDITIONS" not in cdf.domain_facts_block("sleep_coach", table, today="2026-08-09")


def test_weather_storage_failure_costs_the_section_not_the_block():
    from coach import coach_domain_facts as cdf

    class _BoomOnWeather(_RangeTable):
        def query(self, **kw):
            if "SOURCE#weather" in kw.get("ExpressionAttributeValues", {}).get(":pk", ""):
                raise RuntimeError("ddb down")
            return super().query(**kw)

    block = cdf.domain_facts_block("sleep_coach", _BoomOnWeather([]), today="2026-08-09")
    assert "TODAY'S CONDITIONS" not in block
    assert "EXPERIMENT FRAME:" in block


# ── B13: one inference per unsolicited turn (#2527 regression) ───────────────


def test_each_unsolicited_path_makes_exactly_one_inference_call():
    """An outbound path must call the model ONCE.

    The live defect: `_maybe_refer` and `_morning_checkin` each did

        result = _unsolicited_turn(...)      # a full run_turn -> Bedrock
        result = coach_chat.run_turn(...)    # ...immediately overwritten

    so every referral and every morning check-in paid for TWO Bedrock round-trips
    and threw the first away. The two calls were argument-for-argument equivalent
    (`_assemble(target, target)` makes `a["persona_id"] == coach_id`, and run_turn
    resolves `persona_id or coach_id`), so the waste was invisible in behaviour —
    it cost money and latency against an $85/month ceiling and nothing else.

    It reads as a botched conflict resolution when #2527's `_unsolicited_turn`
    refactor landed: the helper was added and the inline block was never deleted.
    That is exactly the shape a rebase reintroduces, which is why this is pinned
    structurally rather than left to a behavioural test — every existing coach
    test passed with the bug in place.

    Pinned as "no direct run_turn in these functions" rather than by counting
    Bedrock invocations, because the helper is the single sanctioned assembly
    point (its own docstring: one runner so three outbound paths cannot drift
    into three slightly different coaches wearing the same name).
    """
    import ast
    import os

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "lambdas",
        "coach",
        "telegram_worker_lambda.py",
    )
    tree = ast.parse(open(path, encoding="utf-8").read())

    unsolicited = {"_maybe_refer", "_morning_checkin", "_speak_unsolicited"}
    seen = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name in unsolicited):
            continue
        seen.add(node.name)
        direct = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run_turn"]
        via_helper = [
            n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_unsolicited_turn"
        ]
        assert not direct, f"{node.name} calls run_turn directly; the unsolicited paths must go through _unsolicited_turn"
        assert len(via_helper) == 1, f"{node.name} makes {len(via_helper)} unsolicited turns, expected exactly 1"

    assert seen == unsolicited, f"expected to check {sorted(unsolicited)}, found {sorted(seen)}"
