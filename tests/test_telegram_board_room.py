"""tests/test_telegram_board_room.py — the board room's who-speaks rule (epic #2363).

The room's safety property is that ONE worker answers each group message and the
rest stay silent, computed independently by every worker from the update alone.
Pinned here: the pure decision matrix, the WIRE-shaped extraction (Telegram entity
offsets are UTF-16 code units — the fixture carries an emoji to prove the slice),
the convention the mention-match depends on (every roster username is ajm_*_bot),
the chair constant's derivation from the persona registry, and the two outbound
call sites that must never text a group id.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "setup"))

from coach import coach_chat, telegram_gateway as gateway, telegram_group as room, telegram_worker_lambda as worker

# ── The wire fixture: a real Telegram group update, as delivered ──────────────
# Shape per https://core.telegram.org/bots/api#update — this is the payload a
# FunctionURL receives from Telegram for a supergroup message with one mention.
# The leading emoji (non-BMP, 2 UTF-16 units / 1 Python char) is the point: the
# entity offset counts UTF-16 units, so a naive text[off:off+len] slice misses.


def _group_update(text="🔥 @ajm_nutrition_bot thoughts?", entities=None, reply_to=None):
    msg = {
        "message_id": 71,
        "from": {"id": 8675309, "is_bot": False, "first_name": "Matthew"},
        "chat": {"id": -100999888, "title": "Grand Rounds", "type": "supergroup"},
        "date": 1756500000,
        "text": text,
    }
    if entities is not None:
        msg["entities"] = entities
    if reply_to is not None:
        msg["reply_to_message"] = reply_to
    return {"update_id": 900001, "message": msg}


_MENTION_ENTITIES = [{"offset": 3, "length": 18, "type": "mention"}]  # UTF-16: emoji=2 + space=1


# ── Extraction (gateway — the only module that sees the raw update) ───────────


def test_mention_extraction_uses_utf16_offsets():
    msg = _group_update(entities=_MENTION_ENTITIES)["message"]
    assert gateway.extract_mentions(msg) == ["ajm_nutrition_bot"]


def test_mention_extraction_ignores_non_mention_entities_and_garbage():
    msg = _group_update(
        entities=[
            {"offset": 3, "length": 18, "type": "bot_command"},
            {"offset": "x", "length": 18, "type": "mention"},
            {"type": "mention"},
        ]
    )["message"]
    assert gateway.extract_mentions(msg) == []


def test_reply_to_bot_requires_a_bot_author():
    bot_reply = {"message_id": 60, "from": {"id": 1, "is_bot": True, "username": "AJM_Sleep_Bot"}, "text": "earlier"}
    human_reply = {"message_id": 61, "from": {"id": 8675309, "is_bot": False, "username": "matthew"}, "text": "earlier"}
    assert gateway.extract_reply_to_bot(_group_update(reply_to=bot_reply)["message"]) == "ajm_sleep_bot"
    assert gateway.extract_reply_to_bot(_group_update(reply_to=human_reply)["message"]) is None
    assert gateway.extract_reply_to_bot(_group_update()["message"]) is None


def test_route_order_carries_the_room_signals():
    event = {
        "headers": {"X-Telegram-Bot-Api-Secret-Token": "wh-secret"},
        "rawPath": "/telegram/nutrition",
        "body": json.dumps(_group_update(entities=_MENTION_ENTITIES)),
    }
    order = gateway.route(event, secret="wh-secret", routing={"nutrition": "nutrition"}, allowed_chat_ids=[-100999888])
    assert order["is_group"] is True
    assert order["mentions"] == ["ajm_nutrition_bot"]
    assert order["reply_to_bot"] is None


# ── The decision matrix (pure, identical in every worker) ─────────────────────


@pytest.mark.parametrize(
    "mentions,reply_to,me,chair,speaks",
    [
        # A coach mention names the speaker — everyone else silent, chair included.
        (["ajm_nutrition_bot"], None, "ajm_nutrition_bot", False, True),
        (["ajm_nutrition_bot"], None, "ajm_sleep_bot", False, False),
        (["ajm_nutrition_bot"], None, "ajm_headcoach_bot", True, False),
        # Two mentions: both speak.
        (["ajm_nutrition_bot", "ajm_sleep_bot"], None, "ajm_sleep_bot", False, True),
        # A NON-roster mention (a human, some other bot) must not silence the chair.
        (["some_friend"], None, "ajm_headcoach_bot", True, True),
        (["some_friend"], None, "ajm_sleep_bot", False, False),
        # No mention: reply-to re-addresses that coach.
        ([], "ajm_sleep_bot", "ajm_sleep_bot", False, True),
        ([], "ajm_sleep_bot", "ajm_headcoach_bot", True, False),
        # Nothing addressed: the chair speaks, alone.
        ([], None, "ajm_headcoach_bot", True, True),
        ([], None, "ajm_sleep_bot", False, False),
        # getMe failed (username unknown): never claim an address; chair fallback survives.
        (["ajm_nutrition_bot"], None, None, False, False),
        ([], None, None, True, True),
    ],
)
def test_who_speaks(mentions, reply_to, me, chair, speaks):
    assert room.who_speaks(mentions=mentions, reply_to_bot=reply_to, my_username=me, is_chair=chair) is speaks


def test_every_roster_username_matches_the_mention_convention():
    """who_speaks recognizes a coach mention by the ajm_*_bot convention — a roster
    bot whose username breaks it would be un-addressable in the room (its mentions
    would read as human mentions and summon the chair instead). Guard the SET."""
    import setup_telegram_bots as setup

    for _key, username, _who in setup.ALL_BOTS:
        assert room.BOT_MENTION.match(username.lower()), f"roster username {username!r} breaks the ajm_*_bot convention"


def test_chair_route_is_the_leads_telegram_route():
    """CHAIR_ROUTE is a constant for speed; the persona registry owns the decision
    (#2719: 'the lead chairs Grand Rounds'). This pins the two together."""
    with open(os.path.join(os.path.dirname(__file__), "..", "config", "personas.json")) as f:
        personas = json.load(f)
    from coach.persona_registry import LEAD_PERSONA_ID

    lead = personas["personas"][LEAD_PERSONA_ID]
    assert lead["telegram_route"] == room.CHAIR_ROUTE


# ── The room thread ───────────────────────────────────────────────────────────


def test_room_thread_prefixes_coach_turns_with_the_speaker():
    rows = [
        {"role": "matthew", "text": "how did I sleep"},
        {"role": "coach", "coach_name": "Dr. Sana Okafor", "text": "well.", "status": "sent"},
        {"role": "coach", "text": "nameless row survives un-prefixed"},
    ]
    thread = room.room_thread(rows)
    assert thread[0]["text"] == "how did I sleep"
    assert thread[1]["text"] == "[Dr. Sana Okafor] well."
    assert thread[2]["text"] == "nameless row survives un-prefixed"


# ── Outbound may never text the room ──────────────────────────────────────────


def test_first_private_chat_id_skips_group_ids():
    assert room.first_private_chat_id([-100999888, 8675309]) == 8675309
    assert room.first_private_chat_id([-100999888]) is None
    assert room.first_private_chat_id(["junk", None, "8675309"]) == "8675309"
    assert room.first_private_chat_id([]) is None


def test_bot_seat_never_returns_a_group_id(monkeypatch):
    import coach.persona_registry as registry

    monkeypatch.setattr(registry, "resolve", lambda pid, *a, **k: {"telegram_route": "sleep"})
    monkeypatch.setattr(worker, "_bot_token", lambda route: "tok")
    monkeypatch.setattr(worker, "_bot_chat_ids", lambda route: [-100999888, 8675309])
    monkeypatch.setattr(worker, "_s3_client", lambda: None)
    assert worker._bot_seat("sleep_coach") == ("tok", 8675309)
    monkeypatch.setattr(worker, "_bot_chat_ids", lambda route: [-100999888])
    assert worker._bot_seat("sleep_coach") == (None, None)


# ── The worker branch: group orders take the room path, listeners cost nothing ─


def _order(coach_id, mentions=(), reply_to=None):
    return {
        "coach_id": coach_id,
        "chat_id": -100999888,
        "text": "morning all",
        "message_id": 71,
        "is_group": True,
        "mentions": list(mentions),
        "reply_to_bot": reply_to,
        "update_id": 900001,
        "message_date": 9999999999,  # far future — never stale against real now()
    }


@pytest.fixture()
def _room_wire(monkeypatch):
    monkeypatch.setattr(worker, "_seen_update", lambda pid, uid: False)
    monkeypatch.setattr(worker, "_bot_token", lambda cid: "tok")
    calls = {"tg": [], "metrics": []}
    monkeypatch.setattr(worker, "_tg", lambda token, method, payload: calls["tg"].append(method))
    monkeypatch.setattr(worker, "_emit_metric", lambda name, cid, value=1: calls["metrics"].append(name))
    return calls


def test_group_order_branches_to_the_room(monkeypatch, _room_wire):
    seen = {}
    monkeypatch.setattr(room, "group_turn", lambda order, token: seen.update(order=order, token=token) or {"ok": True, "reason": "x"})
    out = worker.lambda_handler(_order("sleep"), None)
    assert out == {"ok": True, "reason": "x"}
    assert seen["token"] == "tok"
    # The 1:1 path's typing indicator must NOT have fired for a group order.
    assert "sendChatAction" not in _room_wire["tg"]


def test_silent_listener_never_types_never_infers(monkeypatch, _room_wire):
    monkeypatch.setattr(room, "bot_username", lambda token: "ajm_sleep_bot")
    monkeypatch.setattr(worker, "_resolve_persona", lambda cid: (_ for _ in ()).throw(AssertionError("listener resolved a persona")))
    out = room.group_turn(_order("sleep", mentions=["ajm_nutrition_bot"]), "tok")
    assert out == {"ok": True, "reason": "group_listener"}
    assert "TelegramGroupListenerSilent" in _room_wire["metrics"]
    assert _room_wire["tg"] == []


def test_speaker_runs_the_turn_and_stamps_the_room(monkeypatch, _room_wire):
    monkeypatch.setattr(room, "bot_username", lambda token: "ajm_nutrition_bot")
    monkeypatch.setattr(worker, "_resolve_persona", lambda cid: ("nutrition_coach", None))
    monkeypatch.setattr(
        worker,
        "_assemble",
        lambda pid, cid, allow_referral=True: {
            "coach_name": "Dr. Marcus Webb",
            "persona": "P",
            "memory": "M",
            "facts_block": "F",
            "colleagues": "C",
            "thread": [],
        },
    )
    monkeypatch.setattr(worker, "_chat_rows", lambda cid, limit=40: [])
    monkeypatch.setattr(worker, "_current_tier", lambda: 0)
    monkeypatch.setattr(worker, "_cycle", lambda: 14)
    monkeypatch.setattr(worker, "_grounder_for", lambda a, *extra: (lambda text: []))
    sent_calls = []
    monkeypatch.setattr(
        worker,
        "_send_bubbles",
        lambda token, chat_id, bubbles, **kw: sent_calls.append((chat_id, list(bubbles))) or list(bubbles),
    )
    put_items = []
    monkeypatch.setattr(worker, "_table", lambda: type("T", (), {"put_item": lambda self, Item: put_items.append(Item)})())

    captured = {}

    def fake_run_turn(**kw):
        captured.update(kw)
        return coach_chat.TurnResult("one good point", "sent", [], 1, bubbles=["one good point"])

    monkeypatch.setattr(coach_chat, "run_turn", fake_run_turn)

    out = room.group_turn(_order("nutrition", mentions=["ajm_nutrition_bot"]), "tok")
    assert out["ok"] is True and out["room"] == room.ROOM_ID
    assert "TelegramGroupSpeaker" in _room_wire["metrics"]
    assert "sendChatAction" in _room_wire["tg"]  # the SPEAKER types; listeners never do
    # The room frame reaches the prompt, and the reply lands in the group chat.
    assert room.ROOM_FRAME.strip() in captured["colleagues_block"]
    assert sent_calls and sent_calls[0][0] == -100999888
    # Both rows land on the ROOM's shared partition; the coach row is speaker-stamped.
    assert put_items and all(i["pk"] == coach_chat.chat_pk(room.ROOM_ID) for i in put_items)
    coach_rows = [i for i in put_items if i.get("role") == coach_chat.ROLE_COACH]
    assert coach_rows and coach_rows[0]["speaker"] == "nutrition_coach"


# ── Setup: discovery banks group ids in the store's board_group entry ─────────


def test_bank_group_ids_routes_negatives_to_board_group(capsys):
    import setup_telegram_bots as setup

    payload = {"nutrition": {"bot_token": "t", "chat_ids": [8675309]}}
    private = setup.bank_group_ids([-100999888, 8675309, "junk"], payload)
    assert private == [8675309]
    assert payload[setup.BOARD_GROUP_KEY]["chat_ids"] == [-100999888]
    # Idempotent: a re-discovery adds nothing and prints nothing new.
    capsys.readouterr()
    assert setup.bank_group_ids([-100999888], payload) == []
    assert payload[setup.BOARD_GROUP_KEY]["chat_ids"] == [-100999888]
    assert "recorded" not in capsys.readouterr().out
