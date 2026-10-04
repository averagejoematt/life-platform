"""tests/test_tuesday_question_4584.py — the Tuesday question and his verbatim reply (#4584, epic #4580).

What is pinned here:
  * the send — Tuesday-evening PT in both DST offsets, reserve-then-send, dark/quiet/not-Tuesday skips, the question
    picked from Monday's guarded set (never one he already answered by email, never an absolute claim);
  * the reply — stored EXACTLY as typed; the fail-closed filter holds on a vocabulary hit, a blocked display name,
    PII, an off-record marker and an unavailable vocabulary; any hold withholds the whole week;
  * the serve — silence is a plain sentence, a held reply is indistinguishable from silence and never leaks;
  * the mutations — the filter replaced by always-clean SERVES the held fixture, and replaced by always-hold
    WITHHOLDS the clean one, so both paths are load-bearing;
  * the transport — the gateway carries the quoted message id and a voice reply, the worker stores an answer with no
    inference and leaves every other message on the coach path;
  * nothing here can generate words in his voice: the module imports no model client.

Every vocabulary term below is the suite's NEUTRAL fixture (tests/conftest.py, #2370) — never a real category.
"""

from __future__ import annotations

import ast
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from content import tuesday_question as tq

PT = ZoneInfo("America/Los_Angeles")
NEUTRAL_VOCAB = {"blocked_vices": ["No fizzlewick", "No grumbleflax"], "blocked_vice_keywords": ["fizzlewick", "grumbleflax", "zzq"]}


class ConditionalCheckFailedException(Exception):
    pass


def _key_conditions(expr, values=None):
    """(pk, prefix) from either a string KeyConditionExpression or a boto3 Key() tree."""
    if isinstance(expr, str):
        return values[":pk"], values.get(":pfx", "")
    pk, pfx = None, ""
    stack = [expr]
    while stack:
        node = stack.pop()
        e = node.get_expression()
        op = e["operator"]
        if op == "AND":
            stack.extend(e["values"])
        elif op == "=":
            pk = e["values"][1]
        elif op == "begins_with":
            pfx = e["values"][1]
    return pk, pfx


class FakeTable:
    def __init__(self, items=None):
        self.items = {(i["pk"], i["sk"]): dict(i) for i in (items or [])}
        self.puts = []

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression:
            cur = self.items.get(key)
            if cur is not None and cur.get("status") != (ExpressionAttributeValues or {}).get(":failed"):
                raise ConditionalCheckFailedException()
        self.items[key] = dict(Item)
        self.puts.append(dict(Item))

    def query(self, KeyConditionExpression, ExpressionAttributeValues=None, ScanIndexForward=True, Limit=None, **_):
        pk, pfx = _key_conditions(KeyConditionExpression, ExpressionAttributeValues)
        rows = sorted((v for (p, s), v in self.items.items() if p == pk and s.startswith(pfx)), key=lambda r: r["sk"])
        if not ScanIndexForward:
            rows.reverse()
        return {"Items": [dict(r) for r in rows[:Limit] if Limit] if Limit else [dict(r) for r in rows]}


# A Tuesday in each offset, at the rule's instant: 02:00 UTC Wednesday.
PDT_SLOT = datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc)  # Tue 2026-10-06 19:00 PDT
PST_SLOT = datetime(2026, 11, 11, 2, 0, tzinfo=timezone.utc)  # Tue 2026-11-10 18:00 PST


def _seat():
    return ("tok", 8675309, "headcoach")


def _send(table, now_pt, *, sender=None, **kw):
    sent = []

    def fake_send(token, chat_id, question):
        sent.append((token, chat_id, question))
        return 4242

    out = tq.send_tuesday_question(
        table=table,
        now_pt=now_pt,
        user_id="matthew",
        seat=kw.pop("seat", _seat()),
        quiet=kw.pop("quiet", lambda now: False),
        send=sender or fake_send,
        **kw,
    )
    return out, sent


def _monday_marker(week, questions):
    return {"pk": "USER#matthew#SOURCE#chronicle", "sk": f"STORYQ#W{week:03d}", "questions_json": json.dumps(questions)}


# ── the clock ─────────────────────────────────────────────────────────────────


def test_the_utc_slot_is_tuesday_evening_pacific_outside_quiet_hours_in_both_offsets():
    from coach import coach_outbound

    bad = []
    for slot in (PDT_SLOT, PST_SLOT):
        pt = slot.astimezone(PT)
        if not (pt.weekday() == 1 and 17 <= pt.hour <= 20) or coach_outbound.in_quiet_hours(pt):
            bad.append(pt.isoformat())
    assert not bad, f"not a Tuesday evening outside quiet hours: {bad}"


def test_a_non_tuesday_pacific_day_sends_nothing():
    t = FakeTable()
    out, sent = _send(t, datetime(2026, 10, 7, 19, 0, tzinfo=PT))
    assert out["reason"] == "not_tuesday_pt" and not sent and not t.puts


def test_a_dark_lead_bot_sends_nothing_and_says_so():
    t = FakeTable()
    out, sent = _send(t, PDT_SLOT.astimezone(PT), seat=(None, None, "headcoach"))
    assert out["reason"] == "dark" and not sent and not t.puts


def test_quiet_hours_are_respected():
    out, sent = _send(FakeTable(), PDT_SLOT.astimezone(PT), quiet=lambda now: True)
    assert out["reason"] == "quiet_hours" and not sent


# ── the send ──────────────────────────────────────────────────────────────────


def test_a_send_reserves_then_records_the_message_id_and_a_second_run_sends_nothing():
    t = FakeTable()
    now = PDT_SLOT.astimezone(PT)
    out, sent = _send(t, now)
    assert out["status"] == tq.STATUS_SENT and len(sent) == 1
    row = t.items[(tq.PK, "TUESDAYQ#2026-10-06#Q")]
    assert row["status"] == tq.STATUS_SENT and row["message_id"] == 4242 and row["chat_id"] == "8675309" and row["route"] == "headcoach"
    assert [p["status"] for p in t.puts] == [tq.STATUS_RESERVED, tq.STATUS_SENT], "reserve BEFORE the send, then record"
    out2, sent2 = _send(t, now)
    assert out2["reason"] == "already_sent" and not sent2, "EventBridge's retry must not double-send"


def test_a_failed_send_is_recorded_and_may_be_retaken():
    t = FakeTable()
    now = PDT_SLOT.astimezone(PT)
    out, _ = _send(t, now, sender=lambda *a: None)
    assert out["reason"] == "send_failed" and t.items[(tq.PK, "TUESDAYQ#2026-10-06#Q")]["status"] == tq.STATUS_SEND_FAILED
    out2, sent2 = _send(t, now)
    assert out2["status"] == tq.STATUS_SENT and len(sent2) == 1


def test_the_question_comes_from_mondays_set_skipping_what_he_answered_by_email():
    from content import story_dossier

    now = PDT_SLOT.astimezone(PT)
    week = story_dossier.week_containing(now.strftime("%Y-%m-%d"))
    assert week is not None, "the fixture Tuesday must fall in a season week"
    n = int(week["week"])
    qs = ["What did Tuesday's walk feel like?", "Which session felt heaviest?", "What would you change next week?"]
    answered = {
        "pk": "USER#matthew#SOURCE#insights",
        "sk": f"STORYQA#W{n:03d}#2026-10-05T18:00:00+00:00",
        "answers_json": json.dumps([{"q": 1, "answer": "fine"}]),
    }
    t = FakeTable([_monday_marker(n, qs), answered])
    out, sent = _send(t, now)
    assert sent[0][2] == qs[1] and out["origin"] == "monday_set"


def test_the_monday_marker_shape_is_the_senders():
    """The writer side of the chronicle seam (ledgers/pair_seam_residue.py): the marker sk and its one field."""
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "..", "lambdas", "emails", "wednesday_chronicle_lambda.py"), encoding="utf-8").read()
    body = src[src.index("def _send_story_questions(") : src.index("def lambda_handler(")]
    assert 'f"STORYQ#W{n:03d}"' in body and '"questions_json": json.dumps(questions)' in body
    t = FakeTable([_monday_marker(5, ["a?", "b?"]), {"pk": "USER#matthew#SOURCE#chronicle", "sk": "STORYQ#W006", "questions_json": "{"}])
    assert tq.monday_questions(t, "matthew", 5) == ["a?", "b?"]
    assert tq.monday_questions(t, "matthew", 6) == [] and tq.monday_questions(t, "matthew", 7) == []


def test_an_email_answer_written_by_the_desk_is_seen():
    """The insights seam: a row built by the desk's own writer reads back as answered."""
    from content import story_questions

    row = story_questions.qa_row(
        "USER#matthew#SOURCE#insights",
        5,
        story_questions.parse_reply("Q2: the deadlift day", ["a?", "b?"]),
        received_at="2026-10-05T19:00:00+00:00",
        source_key="k",
    )
    assert tq.answered_by_email(FakeTable([row]), "matthew", 5) == {2}
    assert tq.answered_by_email(FakeTable([row]), "matthew", 6) == set()


def test_an_absolute_or_forbidden_question_is_never_asked():
    from content import story_questions

    qs = ["You never missed a session — why?", "How was work this week?", "What did Saturday's long walk teach you?"]
    q, origin = tq.pick_question(qs, set())
    assert q == qs[2] and origin == "monday_set"
    q2, origin2 = tq.pick_question(qs[:2], set())
    assert origin2 == "fallback" and q2 in story_questions.FALLBACK and tq.passes_guard(q2)


def test_the_message_is_the_question_plus_fixed_sentences_and_asks_for_a_reply():
    calls = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": 99}}).encode()

    def urlopen(req, timeout):
        calls.append(req)
        return Resp()

    assert tq.send_question("tok", 1, "Which session felt heaviest?", urlopen=urlopen) == 99
    from urllib.parse import parse_qs

    body = parse_qs(calls[0].data.decode())
    assert body["text"][0] == tq.render_question("Which session felt heaviest?")
    assert json.loads(body["reply_markup"][0])["force_reply"] is True
    assert tq.send_question("tok", 1, "q", urlopen=lambda *a, **k: (_ for _ in ()).throw(OSError("down"))) is None


# ── the reply and the filter ──────────────────────────────────────────────────

CLEAN = "Honestly the second walk was easier than I expected, and I slept like a rock."
HELD_VOCAB = "Skipped the fizzlewick all week and it was hard."


def _sent_question(day="2026-10-06", mid=4242):
    return {
        "pk": tq.PK,
        "sk": tq.question_sk(day),
        "status": tq.STATUS_SENT,
        "question": "Which session felt heaviest?",
        "message_id": mid,
        "chat_id": "8675309",
        "route": "headcoach",
        "sent_at": "2026-10-07T02:00:03+00:00",
    }


HITS = [
    (HELD_VOCAB, "vice"),
    ("I said No Grumbleflax, mostly", "vice"),
    ("call me on 206-555-0142 about it", "pii"),
    ("off record: the knee is worse than I let on", tq.HOLD_OFF_RECORD),
]


def test_every_filter_hit_holds():
    misses = []
    for text, kind in HITS:
        verdict, kinds = tq.screen(text)
        if verdict != tq.VERDICT_HELD or kind not in kinds or any("fizzlewick" in k or "grumbleflax" in k for k in kinds):
            misses.append((text, verdict, kinds))
    assert not misses, f"a hit that did not hold (or a hit kind that names the term): {misses}"


def test_a_clean_reply_passes():
    assert tq.screen(CLEAN) == (tq.VERDICT_CLEAN, [])


def test_an_unavailable_vocabulary_holds(monkeypatch):
    from privacy import content_filter_channel, privacy_guard

    monkeypatch.delenv("CONTENT_FILTER_JSON", raising=False)
    monkeypatch.setattr(content_filter_channel, "_from_local_file", lambda: None)
    monkeypatch.setattr(content_filter_channel, "_from_s3_boto", lambda b: None)
    monkeypatch.setattr(content_filter_channel, "_from_s3_cli", lambda b: None)
    content_filter_channel.reset_cache()
    privacy_guard.reset_vocabulary_cache()
    try:
        assert tq.screen(CLEAN) == (tq.VERDICT_HELD, [tq.HOLD_FILTER_UNAVAILABLE])
    finally:
        content_filter_channel.reset_cache()
        privacy_guard.reset_vocabulary_cache()


def test_a_reply_is_stored_verbatim_with_its_verdict_and_the_ack_is_fixed():
    t = FakeTable([_sent_question()])
    weird = "  lowercase, no fixes,,  and two  spaces  "
    ack = tq.handle_reply(table=t, question=_sent_question(), text=weird, received_at="2026-10-07T03:10:00+00:00", message_id=5)
    row = t.items[(tq.PK, "TUESDAYQ#2026-10-06#R#2026-10-07T03:10:00+00:00")]
    assert row["text"] == weird, "stored EXACTLY as received — no trim, no copyedit"
    assert row["verdict"] == tq.VERDICT_CLEAN and row["question"] == "Which session felt heaviest?" and ack == tq.ACK_CLEAN
    ack2 = tq.handle_reply(table=t, question=_sent_question(), text=HELD_VOCAB, received_at="2026-10-07T03:11:00+00:00", message_id=6)
    assert ack2 == tq.ACK_HELD and t.items[(tq.PK, "TUESDAYQ#2026-10-06#R#2026-10-07T03:11:00+00:00")]["text"] == HELD_VOCAB


def test_a_reply_matches_only_the_sent_question_in_the_same_chat_on_the_same_bot():
    rows = [_sent_question(), {**_sent_question("2026-09-29", 11), "status": tq.STATUS_SEND_FAILED}]
    assert tq.match_question(rows, chat_id=8675309, reply_to_message_id=4242, route="headcoach") is not None
    assert tq.match_question(rows, chat_id=-100999888, reply_to_message_id=4242, route="headcoach") is None, "ids are per chat"
    assert tq.match_question(rows, chat_id=8675309, reply_to_message_id=4242, route="nutrition") is None
    assert tq.match_question(rows, chat_id=8675309, reply_to_message_id=11, route="headcoach") is None, "never a failed send"
    assert tq.match_question(rows, chat_id=8675309, reply_to_message_id=None, route="headcoach") is None


# ── the serve ─────────────────────────────────────────────────────────────────


def _reply(text, ts, verdict=None):
    v = verdict or tq.screen(text)[0]
    return {"pk": tq.PK, "sk": tq.reply_sk("2026-10-06", ts), "text": text, "received_at": ts, "verdict": v}


def test_a_clean_reply_is_served_word_for_word_with_the_question_and_date():
    view = tq.public_view([_sent_question(), _reply(CLEAN, "2026-10-07T03:10:00+00:00")], vocabulary=NEUTRAL_VOCAB)
    assert view["state"] == tq.STATE_ANSWERED and view["sentence"] is None
    latest = view["latest"]
    assert latest["answer"]["text"] == CLEAN and latest["question"] == "Which session felt heaviest?"
    assert latest["asked_on"] == "2026-10-06" and latest["answer"]["date"] == "2026-10-06" and view["latest_answered"] == latest


def test_silence_is_a_plain_sentence_never_generated_text():
    view = tq.public_view([_sent_question()])
    assert view["state"] == tq.STATE_NO_ANSWER and view["sentence"] == tq.SILENCE_SENTENCE and view["latest"]["answer"] is None
    assert tq.public_view([])["sentence"] == tq.NOT_ASKED_SENTENCE


def test_a_held_reply_reads_exactly_like_silence_and_never_leaks():
    held = tq.public_view([_sent_question(), _reply(HELD_VOCAB, "2026-10-07T03:10:00+00:00")])
    silent = tq.public_view([_sent_question()])
    assert held == silent, "the public payload must not reveal that a reply was held"
    assert "fizzlewick" not in json.dumps(held).lower()


def test_any_hold_withholds_every_reply_that_week():
    rows = [_sent_question(), _reply(HELD_VOCAB, "2026-10-07T03:10:00+00:00"), _reply(CLEAN, "2026-10-07T03:12:00+00:00")]
    view = tq.public_view(rows)
    assert view["state"] == tq.STATE_NO_ANSWER and CLEAN not in json.dumps(view)


def test_the_serve_screens_again_so_a_grown_vocabulary_still_applies():
    stored_clean = _reply("The plorptangle was the hard part.", "2026-10-07T03:10:00+00:00", verdict=tq.VERDICT_CLEAN)
    grown = {"blocked_vices": [], "blocked_vice_keywords": ["fizzlewick", "plorptangle"]}
    view = tq.public_view([_sent_question(), stored_clean], vocabulary=grown)
    assert view["state"] == tq.STATE_NO_ANSWER


def test_a_failed_read_is_never_shown_as_silence():
    class Boom:
        def query(self, **kw):
            raise RuntimeError("throttled")

    assert tq.read_public(Boom())["state"] == tq.STATE_READ_FAILED


# ── the mutations: both paths are load-bearing ────────────────────────────────


def test_mutation_an_always_clean_filter_would_serve_the_held_fixture(monkeypatch):
    """Negative control for the HOLD path: with the screen mutated to always pass, the held fixture is stored as
    clean and SERVED. That the real screen keeps it off the page (above) is therefore the screen's doing."""
    monkeypatch.setattr(tq, "screen", lambda text, vocabulary=None: (tq.VERDICT_CLEAN, []))
    t = FakeTable([_sent_question()])
    tq.handle_reply(table=t, question=_sent_question(), text=HELD_VOCAB, received_at="2026-10-07T03:10:00+00:00", message_id=5)
    view = tq.public_view(tq.recent_questions(t))
    assert view["state"] == tq.STATE_ANSWERED and view["latest"]["answer"]["text"] == HELD_VOCAB


def test_mutation_an_always_hold_filter_would_withhold_the_clean_fixture(monkeypatch):
    """Negative control for the CLEAN path: with the screen mutated to always hold, the clean fixture never serves."""
    monkeypatch.setattr(tq, "screen", lambda text, vocabulary=None: (tq.VERDICT_HELD, ["vice"]))
    t = FakeTable([_sent_question()])
    tq.handle_reply(table=t, question=_sent_question(), text=CLEAN, received_at="2026-10-07T03:10:00+00:00", message_id=5)
    assert tq.public_view(tq.recent_questions(t))["state"] == tq.STATE_NO_ANSWER


# ── nothing here writes in his voice ──────────────────────────────────────────


def test_the_module_imports_no_model_client():
    src = open(tq.__file__, encoding="utf-8").read()
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
            mods |= {f"{node.module}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
    assert not {m for m in mods if m.startswith("ai") or "bedrock" in m}, mods


# ── the transport ─────────────────────────────────────────────────────────────


def _update(message):
    return {
        "rawPath": "/telegram/headcoach",
        "headers": {"x-telegram-bot-api-secret-token": "s"},
        "body": json.dumps({"update_id": 9, "message": {"message_id": 70, "chat": {"id": 8675309, "type": "private"}, **message}}),
    }


def test_the_gateway_carries_the_quoted_message_id_and_a_voice_reply():
    from coach import telegram_gateway as gw

    kw = {"secret": "s", "routing": {"headcoach": "headcoach"}, "allowed_chat_ids": [8675309]}
    order = gw.route(_update({"text": "an answer", "reply_to_message": {"message_id": 4242}}), **kw)
    assert order["reply_to_message_id"] == 4242 and order["text"] == "an answer"
    assert gw.route(_update({"text": "plain"}), **kw)["reply_to_message_id"] is None
    voice = gw.route(_update({"voice": {"file_id": "v1"}, "reply_to_message": {"message_id": 4242}}), **kw)
    assert voice["kind"] == "voice_reply" and voice["reply_to_message_id"] == 4242 and "text" not in voice
    with pytest.raises(gw.Rejected):
        gw.route(_update({"voice": {"file_id": "v1"}}), **kw)  # a bare voice note is still nothing


@pytest.fixture
def worker(monkeypatch):
    from coach import telegram_worker_lambda as w

    sent, metrics = [], []
    table = FakeTable([_sent_question()])
    monkeypatch.setattr(w, "_table", lambda: table)
    monkeypatch.setattr(w, "_bot_token", lambda key: "tok")
    monkeypatch.setattr(w, "_tg", lambda token, method, payload: sent.append((method, payload)))
    monkeypatch.setattr(w, "_emit_metric", lambda name, cid, value=1: metrics.append(name))
    monkeypatch.setattr(w, "_seen_update", lambda cid, uid: False)
    monkeypatch.setattr(w.coach_chat, "run_turn", lambda **kw: pytest.fail("an answer must never reach inference"))
    return type("W", (), {"w": w, "sent": sent, "table": table, "metrics": metrics})


def test_the_worker_stores_an_answer_with_no_inference_and_sends_the_fixed_ack(worker):
    out = worker.w.lambda_handler({"coach_id": "headcoach", "chat_id": 8675309, "text": CLEAN, "reply_to_message_id": 4242}, None)
    assert out["reason"] == "tuesday_answer"
    replies = [v for (p, s), v in worker.table.items.items() if "#R#" in s]
    assert len(replies) == 1 and replies[0]["text"] == CLEAN
    assert worker.sent == [("sendMessage", {"chat_id": 8675309, "text": tq.ACK_CLEAN})]


def test_the_worker_leaves_every_other_message_on_the_coach_path(worker, monkeypatch):
    called = []
    monkeypatch.setattr(worker.w.telegram_tuesday, "answer", lambda order: called.append(order) or None)
    monkeypatch.setattr(worker.w, "_bot_token", lambda key: None)  # stop right after the capture check
    out = worker.w.lambda_handler({"coach_id": "headcoach", "chat_id": 8675309, "text": "what should I eat?"}, None)
    assert called and out["reason"] == "no token", "the capture check ran, said no, and the coach path continued"


def test_a_reply_to_some_other_message_is_not_an_answer(worker):
    from coach import telegram_tuesday as w

    assert w.answer({"coach_id": "headcoach", "chat_id": 8675309, "text": "x", "reply_to_message_id": 1}) is None
    assert w.answer({"coach_id": "headcoach", "chat_id": 8675309, "text": "x"}) is None
    assert w.answer({"coach_id": "headcoach", "chat_id": 8675309, "text": "x", "reply_to_message_id": 4242, "is_group": True}) is None
    assert not [s for (p, s) in worker.table.items if "#R#" in s]


def test_a_voice_answer_is_told_to_type_and_nothing_is_stored(worker):
    out = worker.w.lambda_handler({"kind": "voice_reply", "coach_id": "headcoach", "chat_id": 8675309, "reply_to_message_id": 4242}, None)
    assert out["reason"] == "voice_not_transcribed" and worker.sent[0][1]["text"] == tq.ACK_VOICE
    out2 = worker.w.lambda_handler({"kind": "voice_reply", "coach_id": "headcoach", "chat_id": 8675309, "reply_to_message_id": 1}, None)
    assert out2["reason"] == "voice_dropped" and len(worker.sent) == 1
    assert not [s for (p, s) in worker.table.items if "#R#" in s]


# ── the read-only route ───────────────────────────────────────────────────────


def test_the_route_serves_the_payload_and_503s_a_failed_read():
    from web import site_api_thirdwall as tw

    def _ok(body, cache_seconds=300):
        return {"statusCode": 200, "body": json.dumps(body)}

    def _error(code, msg):
        return {"statusCode": code, "body": msg}

    g = {"table": FakeTable([_sent_question(), _reply(CLEAN, "2026-10-07T03:10:00+00:00")]), "_error": _error}
    orig = tw._ok
    tw._ok = _ok
    try:
        body = json.loads(tw.handle_tuesday_question({}, _g=g)["body"])
        assert body["state"] == tq.STATE_ANSWERED and body["latest"]["answer"]["text"] == CLEAN
        assert "chat_id" not in json.dumps(body) and "message_id" not in json.dumps(body), "transport ids are never served"

        class Boom:
            def query(self, **kw):
                raise RuntimeError("x")

        assert tw.handle_tuesday_question({}, _g={"table": Boom(), "_error": _error})["statusCode"] == 503
    finally:
        tw._ok = orig


def test_the_dead_man_reds_a_missing_send_and_greens_a_sent_one():
    from operational import story_season_qa as ssq

    class Check:
        def __init__(self):
            self.v = None

        def ok(self, m):
            self.v = ("ok", m)

        def fail(self, m):
            self.v = ("fail", m)

        def warn(self, m):
            self.v = ("warn", m)

    now = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)  # 2 h after the first owed slot
    c = Check()
    ssq.grade_tuesday_question(FakeTable(), "USER#matthew#SOURCE#", c, now)
    assert c.v[0] == "fail" and "TUESDAYQ#2026-10-13#Q" in c.v[1]
    sent = {**_sent_question("2026-10-13"), "sent_at": "2026-10-14T02:00:04+00:00"}
    c2 = Check()
    ssq.grade_tuesday_question(FakeTable([sent]), "USER#matthew#SOURCE#", c2, now)
    assert c2.v[0] == "ok"
    c3 = Check()
    ssq.grade_tuesday_question(FakeTable(), "USER#matthew#SOURCE#", c3, datetime(2026, 10, 8, 4, 0, tzinfo=timezone.utc))
    assert c3.v[0] == "ok" and "first live send" in c3.v[1]

    class Boom:
        def get_item(self, Key):
            raise RuntimeError("AccessDenied")

    c4 = Check()
    ssq.grade_tuesday_question(Boom(), "USER#matthew#SOURCE#", c4, now)
    assert c4.v[0] == "warn" and "no verdict" in c4.v[1], "an unreadable partition is never green"
    c5 = Check()
    failed = {**_sent_question("2026-10-13"), "status": tq.STATUS_SEND_FAILED}
    ssq.grade_tuesday_question(FakeTable([failed]), "USER#matthew#SOURCE#", c5, now)
    assert c5.v[0] == "fail" and "send_failed" in c5.v[1]


def test_the_partition_is_classified_and_its_grant_is_one_named_partition():
    from experiment import phase_taxonomy

    assert phase_taxonomy.SOURCE_CLASS["tuesday_question"] == phase_taxonomy.RAW_TIMESERIES
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "..", "cdk", "stacks", "role_policies_serve.py"), encoding="utf-8").read()
    assert '"dynamodb:LeadingKeys": ["USER#matthew#SOURCE#tuesday_question"]' in src
