"""tests/test_telegram_transport.py — the webhook + worker wiring (#2364).

The pure decisions (gateway gates, turn engine, grounding arm) have their own
suites. What is pinned here is the WIRING those suites cannot see: the webhook
answering 200-silent on every path, the async handoff, the worker assembling the
real parts and never letting a Telegram failure re-run inference.
"""

from __future__ import annotations

import json

import pytest
from web import telegram_webhook_lambda as hook


class FakeLambda:
    def __init__(self):
        self.invocations = []

    def invoke(self, **kw):
        self.invocations.append(kw)
        return {"StatusCode": 202}


SECRET_STORE = {
    "webhook_secret": "wh-secret",
    "nutrition": {"bot_token": "tok-n", "chat_ids": [8675309]},
    "training": {"bot_token": "tok-t", "chat_ids": []},
    "board": {"bot_token": "tok-b", "chat_ids": [-100999888]},
}


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    self = type("S", (), {})()
    self.lam = FakeLambda()
    monkeypatch.setattr(hook, "_store", lambda: dict(SECRET_STORE))
    monkeypatch.setattr(hook, "_lambda", self.lam)
    yield self


def tg_event(*, text="protein?", chat_id=8675309, secret="wh-secret", path="/telegram/nutrition"):  # noqa: S107 — test fixture token
    return {
        "rawPath": path,
        "headers": {"x-telegram-bot-api-secret-token": secret},
        "body": json.dumps({"update_id": 1, "message": {"message_id": 7, "text": text, "chat": {"id": chat_id, "type": "private"}}}),
    }


# ── The webhook contract: fast, silent, identical ─────────────────────────────


def test_a_valid_message_is_handed_to_the_worker_async(_wire):
    resp = hook.handler(tg_event(), None)
    assert resp["statusCode"] == 200
    assert len(_wire.lam.invocations) == 1
    inv = _wire.lam.invocations[0]
    assert inv["InvocationType"] == "Event", "inference must happen OFF the webhook path"
    order = json.loads(inv["Payload"])
    assert order["coach_id"] == "nutrition"
    assert order["chat_id"] == 8675309
    assert order["text"] == "protein?"


def test_a_rejected_request_gets_the_IDENTICAL_response_and_no_worker_call(_wire):
    """A distinguishable rejection is an oracle; a non-2xx makes Telegram redeliver."""
    ok = hook.handler(tg_event(), None)
    for bad in (
        tg_event(secret="wrong"),
        tg_event(chat_id=424242),
        tg_event(path="/telegram/unknown-bot"),
    ):
        rej = hook.handler(bad, None)
        assert rej == ok, "accepted and rejected must be indistinguishable to the caller"
    assert len(_wire.lam.invocations) == 1, "only the valid message reached the worker"


def test_a_garbage_event_answers_200_rather_than_500ing_into_telegram_retries(_wire):
    assert hook.handler({"rawPath": None, "headers": None, "body": "\x00"}, None)["statusCode"] == 200
    assert hook.handler({}, None)["statusCode"] == 200
    assert _wire.lam.invocations == []


def test_an_unreadable_secret_store_fails_closed(_wire, monkeypatch):
    monkeypatch.setattr(hook, "_store", dict)  # empty store — no webhook_secret
    assert hook.handler(tg_event(), None)["statusCode"] == 200
    assert _wire.lam.invocations == []


def test_the_board_group_routes_with_its_negative_chat_id(_wire):
    hook.handler(tg_event(path="/telegram/board", chat_id=-100999888), None)
    assert json.loads(_wire.lam.invocations[0]["Payload"])["coach_id"] == "board"


def test_chat_ids_authorize_across_bots_so_a_new_bots_first_message_routes(_wire):
    """The union decision: training has no discovered chat id yet, but the id is
    known from the nutrition bot — Matthew's first message to the new contact must
    not read as a stranger."""
    hook.handler(tg_event(path="/telegram/training"), None)
    assert len(_wire.lam.invocations) == 1


def test_a_worker_invoke_failure_still_answers_200(_wire, monkeypatch):
    class Boom:
        def invoke(self, **kw):
            raise RuntimeError("throttled")

    monkeypatch.setattr(hook, "_lambda", Boom())
    assert hook.handler(tg_event(), None)["statusCode"] == 200


def test_every_setup_roster_key_is_routable():
    """The webhook's ROUTING map and the setup script's roster must not drift — a
    bot Matthew can create must be a bot the webhook can route."""
    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "setup_telegram_bots", os.path.join(os.path.dirname(__file__), "..", "setup", "setup_telegram_bots.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.ALL_KEYS) <= set(hook.ROUTING), f"unroutable bots: {set(mod.ALL_KEYS) - set(hook.ROUTING)}"


# ── The worker: assembly + the one-inference guarantee ────────────────────────


class TestWorker:
    @pytest.fixture(autouse=True)
    def _wire(self, monkeypatch):
        from coach import telegram_worker_lambda as worker

        self.worker = worker
        self.sent = []
        self.stored = []
        monkeypatch.setattr(worker, "_bot_token", lambda key: "tok")
        monkeypatch.setattr(worker, "_tg", lambda token, method, payload: self.sent.append((method, payload)))
        monkeypatch.setattr(worker, "_thread_today", lambda cid, limit=40: [])
        monkeypatch.setattr(worker, "_memory_block", lambda cid: "You remember: the 170 g floor.")
        monkeypatch.setattr(worker, "_facts", dict)
        monkeypatch.setattr(worker, "_current_tier", lambda: 0)

        class T:
            put_item = staticmethod(lambda Item: self.stored.append(Item))

        monkeypatch.setattr(worker, "_table", lambda: T())

        import coach.coach_chat as cc

        self.cc = cc
        yield

    def _run(self, monkeypatch, reply_text="148 g. Logged.", grounder=lambda t: []):
        monkeypatch.setattr(
            self.worker.coach_chat,
            "run_turn",
            lambda **kw: self.cc.TurnResult(reply_text, "sent", [], 1),
        )
        return self.worker.handler({"coach_id": "nutrition", "chat_id": 8675309, "text": "protein?"}, None)

    def test_a_turn_sends_typing_then_the_reply(self, monkeypatch):
        out = self._run(monkeypatch)
        assert out["ok"] is True
        methods = [m for m, _ in self.sent]
        assert methods == ["sendChatAction", "sendMessage"]
        assert self.sent[1][1]["text"] == "148 g. Logged."

    def test_the_exchange_is_stored_on_the_coach_partition(self, monkeypatch):
        self._run(monkeypatch)
        assert len(self.stored) == 2
        assert all(i["pk"] == "COACH#nutrition_coach" for i in self.stored)

    def test_a_storage_failure_never_retries_inference(self, monkeypatch):
        """The reply is already SENT when storage runs; raising would make Lambda
        re-run the handler — a second inference and a second text for one message."""

        class BoomTable:
            def put_item(self, Item):
                raise RuntimeError("ddb down")

        monkeypatch.setattr(self.worker, "_table", lambda: BoomTable())
        out = self._run(monkeypatch)
        assert out["ok"] is True, "storage failure is logged, never raised"

    def test_a_missing_token_drops_without_inference(self, monkeypatch):
        monkeypatch.setattr(self.worker, "_bot_token", lambda key: None)
        called = []
        monkeypatch.setattr(self.worker.coach_chat, "run_turn", lambda **kw: called.append(1))
        out = self.worker.handler({"coach_id": "nutrition", "chat_id": 1, "text": "hi"}, None)
        assert out["ok"] is False and called == []

    def test_a_malformed_order_is_refused_without_inference(self, monkeypatch):
        called = []
        monkeypatch.setattr(self.worker.coach_chat, "run_turn", lambda **kw: called.append(1))
        for order in ({}, {"coach_id": "x"}, {"coach_id": "x", "chat_id": 1, "text": "   "}):
            assert self.worker.handler(order, None)["ok"] is False
        assert called == []
