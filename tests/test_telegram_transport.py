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
    resp = hook.lambda_handler(tg_event(), None)
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
    ok = hook.lambda_handler(tg_event(), None)
    for bad in (
        tg_event(secret="wrong"),
        tg_event(chat_id=424242),
        tg_event(path="/telegram/unknown-bot"),
    ):
        rej = hook.lambda_handler(bad, None)
        assert rej == ok, "accepted and rejected must be indistinguishable to the caller"
    assert len(_wire.lam.invocations) == 1, "only the valid message reached the worker"


def test_a_garbage_event_answers_200_rather_than_500ing_into_telegram_retries(_wire):
    assert hook.lambda_handler({"rawPath": None, "headers": None, "body": "\x00"}, None)["statusCode"] == 200
    assert hook.lambda_handler({}, None)["statusCode"] == 200
    assert _wire.lam.invocations == []


def test_an_unreadable_secret_store_fails_closed(_wire, monkeypatch):
    monkeypatch.setattr(hook, "_store", dict)  # empty store — no webhook_secret
    assert hook.lambda_handler(tg_event(), None)["statusCode"] == 200
    assert _wire.lam.invocations == []


def test_the_board_group_routes_with_its_negative_chat_id(_wire):
    hook.lambda_handler(tg_event(path="/telegram/board", chat_id=-100999888), None)
    assert json.loads(_wire.lam.invocations[0]["Payload"])["coach_id"] == "board"


def test_chat_ids_authorize_across_bots_so_a_new_bots_first_message_routes(_wire):
    """The union decision: the pattern bot has no discovered chat id yet, but the
    id is known from the nutrition bot — Matthew's first message to the new
    contact must not read as a stranger. (Was the training route pre-retirement;
    any not-yet-messaged live route exercises the same union.)"""
    hook.lambda_handler(tg_event(path="/telegram/pattern"), None)
    assert len(_wire.lam.invocations) == 1


def test_a_worker_invoke_failure_still_answers_200(_wire, monkeypatch):
    class Boom:
        def invoke(self, **kw):
            raise RuntimeError("throttled")

    monkeypatch.setattr(hook, "_lambda", Boom())
    assert hook.lambda_handler(tg_event(), None)["statusCode"] == 200


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
        # Hermetic: no real S3 client (registry reads fall through to the repo's
        # local config/), and metric emissions are recorded, not sent.
        self.metrics = []
        monkeypatch.setattr(worker, "_s3_client", lambda: None)
        monkeypatch.setattr(worker, "_emit_metric", lambda name, cid: self.metrics.append((name, cid)))

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
        return self.worker.lambda_handler({"coach_id": "nutrition", "chat_id": 8675309, "text": "protein?"}, None)

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
        out = self.worker.lambda_handler({"coach_id": "nutrition", "chat_id": 1, "text": "hi"}, None)
        assert out["ok"] is False and called == []

    def test_a_malformed_order_is_refused_without_inference(self, monkeypatch):
        called = []
        monkeypatch.setattr(self.worker.coach_chat, "run_turn", lambda **kw: called.append(1))
        for order in ({}, {"coach_id": "x"}, {"coach_id": "x", "chat_id": 1, "text": "   "}):
            assert self.worker.lambda_handler(order, None)["ok"] is False
        assert called == []

    # ── The transport truths (the go-live screenshot defects) ─────────────────

    def test_a_redelivered_update_is_answered_exactly_once(self, monkeypatch):
        """Telegram redelivers pending updates after an outage; the go-live
        double-greeting was this. Same update_id ⇒ one inference, one reply."""
        monkeypatch.setattr(self.worker, "_seen_update", lambda cid, uid: uid == 77)
        called = []
        monkeypatch.setattr(self.worker.coach_chat, "run_turn", lambda **kw: called.append(1))
        out = self.worker.lambda_handler({"coach_id": "nutrition", "chat_id": 1, "text": "hi", "update_id": 77}, None)
        assert out == {"ok": True, "reason": "duplicate"}
        assert called == [] and self.sent == []

    def test_seen_update_reads_the_conditional_failure_as_a_duplicate(self, monkeypatch):
        class Dup(Exception):
            pass

        Dup.__name__ = "ConditionalCheckFailedException"

        class T:
            def put_item(self, **kw):
                raise Dup()

        monkeypatch.setattr(self.worker, "_table", lambda: T())
        assert self.worker._seen_update("nutrition", 42) is True

    def test_seen_update_fails_open_on_storage_errors(self, monkeypatch):
        class T:
            def put_item(self, **kw):
                raise RuntimeError("ddb down")

        monkeypatch.setattr(self.worker, "_table", lambda: T())
        assert self.worker._seen_update("nutrition", 42) is False, "a dropped real message looks like a broken bot"

    def test_a_stale_backlogged_message_is_skipped_without_inference(self, monkeypatch):
        import time

        called = []
        monkeypatch.setattr(self.worker.coach_chat, "run_turn", lambda **kw: called.append(1))
        old = time.time() - 7 * 3600
        out = self.worker.lambda_handler({"coach_id": "nutrition", "chat_id": 1, "text": "hi", "message_date": old}, None)
        assert out == {"ok": True, "reason": "stale"}
        assert called == [] and ("TelegramStaleSkipped", "nutrition") in self.metrics

    def test_the_coach_knows_what_day_it_is(self, monkeypatch):
        """The screenshots' 'I don't have access to the current date or time' —
        the current moment must reach BOTH the facts block and the grounder's
        allowed vocabulary."""
        seen = {}

        def spy(**kw):
            seen.update(kw)
            return self.cc.TurnResult("ok.", "sent", [], 1)

        monkeypatch.setattr(self.worker.coach_chat, "run_turn", spy)
        self.worker.lambda_handler({"coach_id": "nutrition", "chat_id": 1, "text": "what day is it?"}, None)
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
        assert "CURRENT MOMENT:" in seen["facts_block"] and today in seen["facts_block"]

    def test_an_unreadable_registry_degrades_to_an_honest_role_name_and_alarms(self, monkeypatch):
        """'I'm mind_coach' must never happen again: a registry miss emits the
        fail-loud metric and the coach speaks as a ROLE, never as an internal id."""
        monkeypatch.setattr(self.worker, "display_name", lambda pid, s3_client=None, bucket=None: pid)
        seen = {}

        def spy(**kw):
            seen.update(kw)
            return self.cc.TurnResult("ok.", "sent", [], 1)

        monkeypatch.setattr(self.worker.coach_chat, "run_turn", spy)
        self.worker.lambda_handler({"coach_id": "mind", "chat_id": 1, "text": "who are you?"}, None)
        assert seen["coach_name"] == "Matthew's mind coach"
        assert ("TelegramPersonaMissing", "mind") in self.metrics

    def test_a_healthy_registry_gives_the_coach_their_real_name(self, monkeypatch):
        """With config/ readable (the repo's own file here, the bundled/S3 copy in
        Lambda) the coach IS their cast name — the whole point of the fix."""
        seen = {}

        def spy(**kw):
            seen.update(kw)
            return self.cc.TurnResult("ok.", "sent", [], 1)

        monkeypatch.setattr(self.worker.coach_chat, "run_turn", spy)
        self.worker.lambda_handler({"coach_id": "nutrition", "chat_id": 1, "text": "hey"}, None)
        assert seen["coach_name"] not in ("nutrition_coach", ""), "registry resolved a real display name"
        assert seen["persona_block"], "voice spec loaded — the conversation is in character"
        assert self.metrics == []


# ── #4170: the coach never claims a write it cannot make ──────────────────────
#
# The fixture is the 2026-09-25 19:10 PT exchange VERBATIM from the issue. The worker
# has no write tools; "Got it." / "Noted." shipped and 0 training-memory rows existed.
# Owner ruling (option b): route to the Claude chat, never queue, never grant a write.

from coach import telegram_reply_gate as reply_gate  # noqa: E402

EXCHANGE_09_25 = (
    ("New standing constraint - no current injuries or ailments - remember this", "Got it."),
    ("approve you to write this", "Noted."),
)
VETO_TURN_09_25 = ("give me something i can veto", "Push the walk to 45 minutes tomorrow. Your call.")


class TestWriteClaimGate4170:
    @pytest.fixture(autouse=True)
    def _wire(self, monkeypatch):
        from coach import telegram_worker_lambda as worker

        self.worker = worker
        self.sent, self.stored, self.metrics = [], [], []
        monkeypatch.setattr(worker, "_bot_token", lambda key: "tok")
        monkeypatch.setattr(worker, "_tg", lambda token, method, payload: self.sent.append((method, payload)))
        monkeypatch.setattr(worker, "_thread_today", lambda cid, limit=40: [])
        monkeypatch.setattr(worker, "_memory_block", lambda cid: "")
        monkeypatch.setattr(worker, "_facts", dict)
        monkeypatch.setattr(worker, "_current_tier", lambda: 0)
        monkeypatch.setattr(worker, "_s3_client", lambda: None)
        monkeypatch.setattr(worker, "_emit_metric", lambda name, cid: self.metrics.append((name, cid)))

        class T:
            put_item = staticmethod(lambda Item: self.stored.append(Item))

        monkeypatch.setattr(worker, "_table", lambda: T())
        import coach.coach_chat as cc

        self.cc = cc
        yield

    def _turn(self, monkeypatch, inbound, model_reply, status="sent"):
        monkeypatch.setattr(self.worker.coach_chat, "run_turn", lambda **kw: self.cc.TurnResult(model_reply, status, [], 1))
        return self.worker.lambda_handler({"coach_id": "nutrition", "chat_id": 8675309, "text": inbound}, None)

    def _text_sent(self):
        return [p["text"] for m, p in self.sent if m == "sendMessage"]

    # ── the two rules, on the exchange itself ─────────────────────────────────

    @pytest.mark.parametrize("inbound,reply", EXCHANGE_09_25)
    def test_both_turns_of_the_09_25_exchange_are_a_write_request_met_by_a_write_claim(self, inbound, reply):
        assert reply_gate.is_write_request(inbound), inbound
        assert reply_gate.claims_write(reply), reply

    def test_the_veto_turn_is_a_request_but_the_motivational_line_claims_nothing(self):
        inbound, reply = VETO_TURN_09_25
        assert reply_gate.is_write_request(inbound)
        assert not reply_gate.claims_write(reply)

    @pytest.mark.parametrize(
        "inbound,reply",
        [
            ("how did I sleep?", "Got it. 7h12 last night, HRV steady."),  # a claim-word with no request behind it
            ("remember this: no injuries", "I can't save that from here, it needs the Claude chat."),  # already honest
            ("I remembered how good that walk felt", "Noted. Same route tomorrow?"),  # reminiscence, not a request
        ],
    )
    def test_the_gate_needs_both_rules_so_neither_alone_fires_it(self, inbound, reply):
        result = self.cc.TurnResult(reply, "sent", [], 1)
        assert reply_gate.enforce(inbound, result) is result

    def test_the_refusal_names_the_claim_and_keeps_the_refused_text(self):
        inbound, false_ack = EXCHANGE_09_25[1]
        out = reply_gate.enforce(inbound, self.cc.TurnResult(false_ack, "sent", [], 1))
        assert out.status == reply_gate.STATUS_ROUTED and out.bubbles == [reply_gate.ROUTING_LINE]
        (finding,) = out.findings
        assert finding["type"] == "write_claim" and "'Noted'" in finding["detail"] and finding["refused_text"] == false_ack

    def test_a_held_reply_is_never_touched(self):
        held = self.cc.TurnResult("Let me check that before I answer.", "held", [{"type": "night"}], 2)
        assert reply_gate.enforce(EXCHANGE_09_25[0][0], held) is held

    def test_a_declared_real_write_keeps_its_acknowledgement(self):
        """The hook for a future path that actually writes: it says so, and the ack stands."""
        result = self.cc.TurnResult("Got it.", "sent", [], 1)
        assert reply_gate.enforce(EXCHANGE_09_25[0][0], result, wrote_this_turn=True) is result

    # ── wired: the worker sends the routing line, not the false ack ───────────

    @pytest.mark.parametrize("inbound,false_ack", EXCHANGE_09_25)
    def test_the_worker_sends_the_routing_line_instead_of_the_false_ack(self, monkeypatch, inbound, false_ack):
        out = self._turn(monkeypatch, inbound, false_ack)
        assert out == {"ok": True, "status": reply_gate.STATUS_ROUTED}
        assert self._text_sent() == [reply_gate.ROUTING_LINE]
        assert false_ack not in "\n".join(self._text_sent())
        assert ("TelegramWriteClaimRefused", "nutrition") in self.metrics

    def test_the_stored_record_shows_the_refusal_not_a_gap(self, monkeypatch):
        inbound, false_ack = EXCHANGE_09_25[0]
        self._turn(monkeypatch, inbound, false_ack)
        coach_rows = [r for r in self.stored if r.get("role") == self.cc.ROLE_COACH]
        assert len(coach_rows) == 1
        row = coach_rows[0]
        assert row["text"] == reply_gate.ROUTING_LINE
        assert row["status"] == reply_gate.STATUS_ROUTED
        assert row["findings"] == ["write_claim"]  # turn_records stores the finding TYPES

    def test_a_regenerated_reply_is_gated_too(self, monkeypatch):
        """`grounded` covers both first-try and retry successes; the gate must not
        depend on which one the model needed."""
        self._turn(monkeypatch, EXCHANGE_09_25[1][0], "Noted.", status="regenerated")
        assert self._text_sent() == [reply_gate.ROUTING_LINE]

    def test_the_routed_status_is_not_one_coach_voice_speaks(self):
        from coach import coach_voice

        assert reply_gate.STATUS_ROUTED not in coach_voice.GROUNDED_STATUSES

    # ── mutation control: gate off → the false ack ships ──────────────────────

    def test_MUTATION_control_with_the_gate_neutered_the_false_ack_ships(self, monkeypatch):
        """What the wired tests above are worth: with `enforce` a passthrough (the
        pre-#4170 worker), the exact 09-25 reply reaches the phone and is stored as
        `sent`. If this ever FAILS, the fixture no longer exercises the gate."""
        monkeypatch.setattr(self.worker.telegram_reply_gate, "enforce", lambda inbound, result, **kw: result)
        inbound, false_ack = EXCHANGE_09_25[0]
        out = self._turn(monkeypatch, inbound, false_ack)
        assert out["status"] == "sent"
        assert self._text_sent() == [false_ack]
        assert ("TelegramWriteClaimRefused", "nutrition") not in self.metrics

    # ── structural: where the gate sits in the worker ─────────────────────────

    def test_the_gate_runs_after_the_model_and_before_the_send_in_the_primary_path(self):
        import inspect

        src = inspect.getsource(self.worker.lambda_handler)
        i_turn = src.index("coach_chat.run_turn(")
        i_gate = src.index("telegram_reply_gate.enforce(text, result, wrote_this_turn=False)")
        i_send = src.index("_send_bubbles(")
        assert i_turn < i_gate < i_send, "the reply gate is AFTER the model and BEFORE the send — the hazard gate stays in front"
