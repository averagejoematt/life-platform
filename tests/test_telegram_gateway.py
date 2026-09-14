"""tests/test_telegram_gateway.py — the three safety gates on the coach chat webhook
(#2364, epic #2363).

A FunctionURL is a public, unauthenticated URL and a Telegram bot username is
discoverable. Everything here defends one property: **nothing reaches inference
except a real Telegram delivery, for a declared bot, from Matthew.** A gap in any of
the three lets a stranger interrogate his health data in a coach's trusted voice and
spend his Bedrock budget doing it.
"""

from __future__ import annotations

import base64
import json

import pytest
from coach import telegram_gateway as tg

SECRET = "s3cret-token-value"
ROUTING = {"webb": "nutrition", "park": "sleep"}
ALLOWED = ["8675309", "-100999888"]  # Matthew, and the board group (groups are negative)


def event(*, text="how'd protein go?", chat_id=8675309, secret=SECRET, path="/telegram/webb", chat_type="private", **over):
    msg = {"message_id": 11, "text": text, "chat": {"id": chat_id, "type": chat_type}}
    ev = {
        "rawPath": path,
        "headers": {"X-Telegram-Bot-Api-Secret-Token": secret} if secret is not None else {},
        "body": json.dumps({"update_id": 1, "message": msg}),
    }
    ev.update(over)
    return ev


def route(ev, **kw):
    params = dict(secret=SECRET, routing=ROUTING, allowed_chat_ids=ALLOWED)
    params.update(kw)
    return tg.route(ev, **params)


# ── Gate 1: is this actually Telegram? ────────────────────────────────────────


def test_a_valid_delivery_routes():
    order = route(event())
    assert order["coach_id"] == "nutrition"
    assert order["chat_id"] == 8675309
    assert order["text"] == "how'd protein go?"


def test_a_request_with_no_secret_header_is_rejected():
    with pytest.raises(tg.Rejected):
        route(event(secret=None))


def test_a_request_with_the_wrong_secret_is_rejected():
    with pytest.raises(tg.Rejected):
        route(event(secret="not-the-secret"))


def test_an_unconfigured_secret_fails_CLOSED():
    """An unconfigured webhook that accepted everything would be strictly worse than
    one that accepts nothing — it would look like it was working."""
    with pytest.raises(tg.Rejected):
        route(event(), secret=None)
    with pytest.raises(tg.Rejected):
        route(event(), secret="")


def test_the_secret_header_is_matched_case_insensitively():
    """Header names are case-insensitive over the wire and Lambda does not normalize;
    a case-sensitive lookup would reject every real delivery."""
    ev = event()
    ev["headers"] = {"x-telegram-bot-api-secret-token": SECRET}
    assert route(ev)["coach_id"] == "nutrition"


def test_a_near_miss_secret_is_still_rejected():
    with pytest.raises(tg.Rejected):
        route(event(secret=SECRET[:-1]))
    with pytest.raises(tg.Rejected):
        route(event(secret=SECRET + "x"))


# ── Gate 2: which coach was texted? ───────────────────────────────────────────


def test_the_bot_path_selects_the_coach_not_the_message_text():
    """Inferring a coach from content would let phrasing redirect a question to a
    persona whose fact block was never built for it — the #2343 shape."""
    assert route(event(path="/telegram/park", text="what about my protein?"))["coach_id"] == "sleep"


def test_an_unmapped_bot_is_rejected_rather_than_defaulting_to_a_coach():
    with pytest.raises(tg.Rejected):
        route(event(path="/telegram/stranger"))


def test_a_trailing_slash_still_resolves():
    assert route(event(path="/telegram/webb/"))["coach_id"] == "nutrition"


def test_the_path_can_come_from_the_request_context_when_rawpath_is_absent():
    ev = event()
    del ev["rawPath"]
    ev["requestContext"] = {"http": {"path": "/telegram/webb"}}
    assert route(ev)["coach_id"] == "nutrition"


# ── Gate 3: is this Matthew? ──────────────────────────────────────────────────


def test_an_unknown_chat_id_is_rejected_before_any_inference():
    with pytest.raises(tg.Rejected):
        route(event(chat_id=112233))


def test_the_board_group_chat_is_authorized():
    order = route(event(chat_id=-100999888, chat_type="supergroup"))
    assert order["chat_id"] == -100999888
    assert order["is_group"] is True


def test_a_private_chat_is_not_marked_as_a_group():
    assert route(event())["is_group"] is False


def test_chat_ids_compare_as_strings_so_a_numeric_id_matches_a_configured_string():
    """Telegram ids arrive as JSON numbers and are configured as env strings.
    `123 != "123"` would reject the real owner — a failure that looks exactly like a
    broken bot rather than a security control."""
    assert route(event(chat_id=8675309), allowed_chat_ids=["8675309"])["chat_id"] == 8675309
    assert route(event(chat_id=8675309), allowed_chat_ids=[8675309])["chat_id"] == 8675309


def test_no_configured_chat_ids_fails_CLOSED():
    with pytest.raises(tg.Rejected):
        route(event(), allowed_chat_ids=[])
    with pytest.raises(tg.Rejected):
        route(event(), allowed_chat_ids=None)


def test_blank_entries_in_the_allow_list_do_not_authorize_anyone():
    """A trailing comma in an env var must not become a wildcard."""
    with pytest.raises(tg.Rejected):
        route(event(), allowed_chat_ids=["", "  "])


def test_an_update_with_no_chat_id_is_rejected():
    ev = event()
    ev["body"] = json.dumps({"message": {"text": "hi", "message_id": 3}})
    with pytest.raises(tg.Rejected):
        route(ev)


# ── Update parsing ────────────────────────────────────────────────────────────


def test_a_base64_body_is_decoded():
    ev = event()
    ev["body"] = base64.b64encode(ev["body"].encode()).decode()
    ev["isBase64Encoded"] = True
    assert route(ev)["text"] == "how'd protein go?"


def test_an_unparseable_body_is_rejected_rather_than_crashing():
    with pytest.raises(tg.Rejected):
        route(event(body="{not json"))


def test_a_non_message_update_is_rejected_quietly():
    """Telegram delivers reactions, joins, callbacks. Only a new text message is a
    turn."""
    ev = event()
    ev["body"] = json.dumps({"update_id": 2, "my_chat_member": {"chat": {"id": 8675309}}})
    with pytest.raises(tg.Rejected):
        route(ev)


def test_an_EDITED_message_does_not_start_a_second_turn():
    """Re-answering an edit would leave two contradictory replies in the scrollback
    with no way to tell which is current."""
    ev = event()
    ev["body"] = json.dumps({"update_id": 3, "edited_message": {"message_id": 11, "text": "changed", "chat": {"id": 8675309}}})
    with pytest.raises(tg.Rejected):
        route(ev)


def test_a_photo_with_no_usable_size_is_still_nothing_at_all():
    """#3758 made a photo actionable; an EMPTY photo array is still not a photo.

    This test asserted the old behaviour — that any `photo` message was rejected — and
    rewriting it was the deliberate half of #3758, not collateral. What survives verbatim
    is the assertion itself, because `photo: []` carries no `file_id` and therefore no
    file: the array is what makes a message a photo, not the key's presence. A webhook
    that sends the key with nothing in it is malformed, and malformed stays rejected.
    """
    ev = event()
    ev["body"] = json.dumps({"update_id": 4, "message": {"message_id": 5, "photo": [], "chat": {"id": 8675309}}})
    with pytest.raises(tg.Rejected):
        route(ev)


def test_a_real_photo_routes_as_a_capture_and_never_as_a_coach_turn():
    """The new shape, and the property that keeps it out of the inference path.

    A photo is discriminated on `kind`, exactly like the scheduled outbound events, so a
    malformed work order can never drift into becoming one. It carries no `text`, which
    is what guarantees it cannot fall through to the coach turn path even if the `kind`
    dispatch were removed — the worker's malformed-order check would reject it first.
    """
    ev = event()
    ev["body"] = json.dumps(
        {
            "update_id": 5,
            "message": {
                "message_id": 6,
                "chat": {"id": 8675309, "type": "private"},
                "caption": "/progress front",
                "photo": [
                    {"file_id": "small", "file_unique_id": "u1", "width": 90, "height": 120, "file_size": 1200},
                    {"file_id": "large", "file_unique_id": "u2", "width": 900, "height": 1200, "file_size": 240000},
                ],
            },
        }
    )
    order = route(ev)

    assert order["kind"] == "progress_photo"
    assert order["caption"] == "/progress front"
    assert "text" not in order, "a photo order must not present as a coach turn"
    assert order["bot_key"], "the capture bot must travel with the order — only one bot may capture"
    assert [p["file_id"] for p in order["photo"]] == ["small", "large"]


def test_a_captioned_photo_still_goes_through_the_chat_authorization():
    """A stranger's photo is refused by the SAME gate a stranger's text is."""
    ev = event()
    ev["body"] = json.dumps(
        {
            "update_id": 6,
            "message": {
                "message_id": 7,
                "chat": {"id": 111111, "type": "private"},
                "caption": "/progress front",
                "photo": [{"file_id": "x", "file_unique_id": "ux", "width": 9, "height": 12, "file_size": 10}],
            },
        }
    )
    with pytest.raises(tg.Rejected):
        route(ev)


# ── The response is always the same, whatever happened ────────────────────────


def test_every_outcome_answers_200_empty():
    """Telegram retries any non-2xx, so a 403 on a stranger's message would make
    Telegram redeliver it on a schedule. And an indistinguishable response means
    probing the URL reveals nothing about which bots exist or who is authorized."""
    ok = tg.silent_ok()
    assert ok["statusCode"] == 200
    assert json.loads(ok["body"]) == {}


def test_the_ok_response_is_a_fresh_dict_each_call():
    """A shared mutable default would let one request's mutation leak into the next."""
    a = tg.silent_ok()
    a["statusCode"] = 500
    assert tg.silent_ok()["statusCode"] == 200


def test_a_rejection_carries_a_reason_for_the_log_but_not_for_the_caller():
    with pytest.raises(tg.Rejected) as e:
        route(event(chat_id=999))
    assert e.value.reason, "the log needs a reason"


def test_an_unauthorized_id_is_not_echoed_in_full_in_the_reason():
    """The log line should not become a record of arbitrary strangers' full ids."""
    with pytest.raises(tg.Rejected) as e:
        route(event(chat_id=112233445566))
    assert "112233445566" not in e.value.reason


# ── Ordering: the cheapest, least revealing gate runs first ───────────────────


def test_an_unauthorized_chat_with_a_bad_secret_fails_on_the_SECRET_first():
    """Gate order is load-bearing: a stranger must not learn that their chat id was
    the problem, because that reveals that the secret was right."""
    with pytest.raises(tg.Rejected) as e:
        route(event(chat_id=999, secret="wrong"))
    assert "secret" in e.value.reason


def test_an_unmapped_bot_is_caught_before_the_chat_id_is_examined():
    with pytest.raises(tg.Rejected) as e:
        route(event(path="/telegram/nope", chat_id=999))
    assert "no coach mapped" in e.value.reason


# ── The work order carries the redelivery + staleness signals (#2364 go-live) ─


def test_the_order_carries_update_id_and_message_date():
    """update_id keys the worker's dedupe (Telegram redelivers pending updates);
    the message date is the staleness signal. Both ride the work order so the
    worker never re-parses transport."""
    msg = {"message_id": 11, "text": "hi", "chat": {"id": 8675309, "type": "private"}, "date": 1754700000}
    ev = {
        "rawPath": "/telegram/webb",
        "headers": {"X-Telegram-Bot-Api-Secret-Token": SECRET},
        "body": json.dumps({"update_id": 4242, "message": msg}),
    }
    order = route(ev)
    assert order["update_id"] == 4242
    assert order["message_date"] == 1754700000


def test_a_missing_date_or_update_id_still_routes():
    order = route(event())
    assert order["update_id"] == 1  # the event() helper's update_id
    assert order["message_date"] is None


def test_is_stale_truth_table():
    now = 1_754_700_000.0
    assert tg.is_stale(now - 60, now) is False, "a minute old is a live text"
    assert tg.is_stale(now - 5 * 3600, now) is False, "inside the window still answers"
    assert tg.is_stale(now - 7 * 3600, now) is True, "a 7h backlog reads as a bot waking up"
    assert tg.is_stale(None, now) is False, "no timestamp must NOT drop a real message"
    assert tg.is_stale("garbage", now) is False, "unparseable is not stale — fail open"
