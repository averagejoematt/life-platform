"""tests/test_telegram_setup_chat_ids.py — chat-id discovery survives a live webhook (#2600).

The incident: ``register_telegram_webhooks.py`` is documented to run AFTER
``setup_telegram_bots.py``, and running it permanently disables that script's
chat-id discovery — Telegram serves ``getUpdates`` OR a webhook, never both.
``discover_chat_ids`` threw the reason away (``if not r.get("ok"): return []``),
so a 409 rendered as "no chat id yet — send the bot a message, then re-run":
advice that can never succeed, repeated forever, blaming the operator.

The consequence was not cosmetic. A missing chat id gates OUTBOUND, so every
coach added after the first webhook registration was silently unable to text
first while looking healthy from the phone.

What is pinned here is the DISTINCTION, in both directions — the same function,
opposite inputs, mutually exclusive advice:

  * a genuinely unmessaged bot must still get the original advice, because there
    it is true and it works;
  * a webhook-blocked bot must get the new branch and must NOT be told to send a
    message.

Plus the guardrail the whole script exists for: no token ever reaches stdout.
"""

from __future__ import annotations

import importlib.util
import os

import pytest

pytest.importorskip("boto3")  # the script imports it at module scope

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SETUP = os.path.join(_REPO, "setup", "setup_telegram_bots.py")
_REGISTER = os.path.join(_REPO, "setup", "register_telegram_webhooks.py")


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tg = _load(_SETUP, "setup_telegram_bots_under_test")

# Telegram's real 409 body, verbatim (measured 2026-08-12 against the live bots).
WEBHOOK_409 = {
    "ok": False,
    "error_code": 409,
    "description": "Conflict: can't use getUpdates method while webhook is active",
}
EMPTY_OK = {"ok": True, "result": []}
TOKEN = "1234567:AA-this-must-never-be-printed"  # noqa: S105 — fake, and that is the point
OWNER_ID = 8724185006


def _api_returning(response: dict):
    def _fake(token: str, method: str, timeout: int = 15) -> dict:
        assert method == "getUpdates"
        return response

    return _fake


# ── discover_chat_ids: the reason is carried, not discarded ───────────────────


def test_a_webhook_409_is_reported_with_telegrams_own_words(monkeypatch):
    monkeypatch.setattr(tg, "_api", _api_returning(WEBHOOK_409))
    ids, reason = tg.discover_chat_ids(TOKEN)
    assert ids == []
    assert reason == WEBHOOK_409["description"], "the description must survive, not be swallowed by `return []`"
    assert tg.is_webhook_conflict(reason)


def test_a_genuinely_unmessaged_bot_reports_no_reason_at_all(monkeypatch):
    monkeypatch.setattr(tg, "_api", _api_returning(EMPTY_OK))
    ids, reason = tg.discover_chat_ids(TOKEN)
    assert (ids, reason) == ([], None), "Telegram answered — empty means empty, and that is a different state"


def test_updates_still_yield_ids_when_getupdates_works(monkeypatch):
    monkeypatch.setattr(
        tg,
        "_api",
        _api_returning({"ok": True, "result": [{"message": {"chat": {"id": OWNER_ID, "type": "private"}}}]}),
    )
    assert tg.discover_chat_ids(TOKEN) == ([OWNER_ID], None)


def test_an_unauthorized_token_is_not_mistaken_for_a_webhook_conflict(monkeypatch):
    monkeypatch.setattr(tg, "_api", _api_returning({"ok": False, "error_code": 401, "description": "Unauthorized"}))
    _ids, reason = tg.discover_chat_ids(TOKEN)
    assert reason == "Unauthorized"
    assert not tg.is_webhook_conflict(reason)


def test_the_other_409_keeps_the_generic_branch():
    # 409 is also "terminated by other getUpdates request" — a different problem
    # with different advice, so the webhook branch must not claim it.
    assert not tg.is_webhook_conflict("Conflict: terminated by other getUpdates request")


# ── resolve_chat_ids: mutation-proven in both directions ──────────────────────


def test_an_unmessaged_bot_still_gets_the_original_advice(monkeypatch, capsys):
    monkeypatch.setattr(tg, "_api", _api_returning(EMPTY_OK))
    added = tg.resolve_chat_ids("labs", TOKEN, {}, {})
    out = capsys.readouterr().out
    assert added == []
    assert "send the bot a message" in out, "where getUpdates works, the old advice is correct and must remain"
    assert "webhook" not in out.lower()


def test_a_webhook_blocked_bot_gets_the_new_branch_instead(monkeypatch, capsys):
    monkeypatch.setattr(tg, "_api", _api_returning(WEBHOOK_409))
    monkeypatch.setattr(tg, "_ask", lambda prompt: "")  # ENTER = accept the offer
    payload = {"nutrition": {"bot_token": "other", "chat_ids": [OWNER_ID]}}

    added = tg.resolve_chat_ids("labs", TOKEN, {}, payload)
    out = capsys.readouterr().out

    assert added == [OWNER_ID], "the bot must end up outbound-capable without a hand-edit of the secret"
    assert "webhook" in out.lower()
    assert WEBHOOK_409["description"] in out
    assert "send the bot a message" not in out, "the impossible advice is exactly the bug"


def test_declining_the_offer_falls_back_to_a_typed_id(monkeypatch, capsys):
    monkeypatch.setattr(tg, "_api", _api_returning(WEBHOOK_409))
    answers = iter(["n", str(OWNER_ID)])
    monkeypatch.setattr(tg, "_ask", lambda prompt: next(answers))
    payload = {"nutrition": {"bot_token": "other", "chat_ids": [111]}}
    assert tg.resolve_chat_ids("labs", TOKEN, {}, payload) == [OWNER_ID]
    capsys.readouterr()


def test_with_no_other_bot_to_copy_from_it_prompts_rather_than_dead_ends(monkeypatch, capsys):
    monkeypatch.setattr(tg, "_api", _api_returning(WEBHOOK_409))
    monkeypatch.setattr(tg, "_ask", lambda prompt: str(OWNER_ID))
    assert tg.resolve_chat_ids("labs", TOKEN, {}, {}) == [OWNER_ID]
    capsys.readouterr()


def test_a_non_numeric_answer_records_nothing(monkeypatch, capsys):
    monkeypatch.setattr(tg, "_api", _api_returning(WEBHOOK_409))
    monkeypatch.setattr(tg, "_ask", lambda prompt: "my-chat")
    assert tg.resolve_chat_ids("labs", TOKEN, {}, {}) == []
    assert "not a number" in capsys.readouterr().out


def test_a_webhook_blocked_bot_that_already_has_an_id_is_left_alone(monkeypatch, capsys):
    monkeypatch.setattr(tg, "_api", _api_returning(WEBHOOK_409))
    monkeypatch.setattr(tg, "_ask", lambda prompt: pytest.fail("must not prompt when the id is already known"))
    added = tg.resolve_chat_ids("labs", TOKEN, {"chat_ids": [OWNER_ID]}, {})
    assert added == []
    assert "keeping known chat id" in capsys.readouterr().out


def test_no_token_is_ever_printed_on_any_branch(monkeypatch, capsys):
    monkeypatch.setattr(tg, "_ask", lambda prompt: "")
    payload = {"nutrition": {"bot_token": TOKEN, "chat_ids": [OWNER_ID]}}
    for response in (WEBHOOK_409, EMPTY_OK, {"ok": False, "error_code": 401, "description": "Unauthorized"}):
        monkeypatch.setattr(tg, "_api", _api_returning(response))
        tg.resolve_chat_ids("labs", TOKEN, {}, payload)
        assert TOKEN not in capsys.readouterr().out


# ── adoption is only valid for PRIVATE chats ──────────────────────────────────


def test_group_chat_ids_are_never_offered_for_adoption():
    # A private chat's id is the user; a negative id is the ROOM, and carries none
    # of that equivalence — adopting the board's id would allow-list a group.
    payload = {
        "board": {"chat_ids": [-100999888]},
        "nutrition": {"chat_ids": [OWNER_ID]},
        "sleep": {"chat_ids": [OWNER_ID, -100999888]},
    }
    assert tg.other_bot_chat_ids(payload, exclude="labs") == [OWNER_ID]


def test_the_bots_own_ids_are_not_offered_back_to_it():
    payload = {"labs": {"chat_ids": [777]}, "webhook_secret": "not-a-bot-entry"}
    assert tg.other_bot_chat_ids(payload, exclude="labs") == []


def test_the_most_corroborated_id_sorts_first():
    payload = {"a": {"chat_ids": [5]}, "b": {"chat_ids": [OWNER_ID]}, "c": {"chat_ids": [OWNER_ID]}}
    assert tg.other_bot_chat_ids(payload, exclude="labs")[0] == OWNER_ID


# ── --show: token without chat id is a warning, not a neutral dash ────────────


def test_show_flags_a_token_without_a_chat_id_as_unable_to_text_first(capsys):
    tg.show({"labs": {"bot_token": TOKEN}})
    out = capsys.readouterr().out
    assert "cannot text first" in out
    assert "labs" in out
    assert TOKEN not in out


def test_show_does_not_warn_when_the_chat_id_is_present(capsys):
    tg.show({"labs": {"bot_token": TOKEN, "chat_ids": [OWNER_ID]}})
    out = capsys.readouterr().out
    assert "cannot text first" not in out
    assert str(OWNER_ID) in out


def test_an_unconfigured_bot_is_not_a_warning(capsys):
    tg.show({})
    assert "cannot text first" not in capsys.readouterr().out


# ── the ordering dependency is written down where each operator will look ─────


@pytest.mark.parametrize("path", [_SETUP, _REGISTER])
def test_both_docstrings_state_the_ordering_dependency(path):
    doc = _load(path, "doc_" + os.path.basename(path)[:-3]).__doc__ or ""
    low = doc.lower()
    assert "getupdates" in low and "webhook" in low
    assert "setup_telegram_bots.py" in doc and "register_telegram_webhooks.py" in doc
    assert "never both" in low, "the mutual exclusion is the fact an operator needs; state it, do not imply it"
