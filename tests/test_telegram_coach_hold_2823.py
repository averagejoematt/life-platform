"""tests/test_telegram_coach_hold_2823.py — #2823's derivation guard + mutation proof.

The defect (elite review 2026-08-16, WS-B; verifier CONFIRMED): a held Telegram
coach reply was a log line and nothing else. Precedent: the 2026-08-10 P2 held
every reply containing a number for ~9h and left exactly one INFO log line as its
only trace — no metric, no alarm, and `slo-ai-coaching-success` cannot see a gate
hold either (it watches AnthropicAPIFailure; a hold rides a SUCCESSFUL Bedrock
call). `tests/test_coach_chat_grounding.py` pins the underlying wiring defect that
CAUSED the 08-10 hold; this file pins the missing OPERATOR SIGNAL #2823 closes.

The fix mirrors the #2763 fail-soft-silence shape (a swallowing path logs a
literal token, a CloudWatch MetricFilter mints a metric, an alarm turns the
silence into news — see cdk/stacks/monitoring_silence_alarms.py) applied to the
chat surface, with one twist: FOUR hold sites share one token, not one, because
`telegram_worker_lambda.py`'s `if not result.grounded:` shape repeats across the
primary reply and all three unsolicited-outbound paths (referral/checkin/event).

Guard the SET, not the instance (this repo's own repeated review-discipline
lesson): rather than hand-listing the four call sites and asserting each one
calls `_emit_hold`, the structural test below finds EVERY `if not
result.grounded:` branch in the module FROM SOURCE and asserts every one of them
does — so a fifth hold path added later either inherits the alarm by
construction or reds this test the instant it's added without the call, the same
derivation-guard shape as `tests/test_route_metric_coverage_2876.py`.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coach import coach_chat, telegram_worker_lambda as worker  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402

SRC_PATH = os.path.join(_REPO, "lambdas", "coach", "telegram_worker_lambda.py")
SRC = open(SRC_PATH, encoding="utf-8").read()
SRC_LINES = SRC.splitlines()

WEDNESDAY_10AM = datetime(2026, 8, 12, 10, 15, tzinfo=PACIFIC)


# ── Structural guard: every hold branch calls the emitter (guard the SET) ─────

_HOLD_BRANCH_RE = re.compile(r"^\s*if not result\.grounded:\s*$")


def _block_after(line_index: int) -> str:
    """Every source line inside the indented block that starts one line below
    `line_index` (0-indexed) — i.e. the body of that `if`."""
    indent = len(SRC_LINES[line_index]) - len(SRC_LINES[line_index].lstrip())
    body = []
    for line in SRC_LINES[line_index + 1 :]:
        if line.strip() == "":
            body.append(line)
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return "\n".join(body)


def test_every_not_grounded_branch_calls_emit_hold():
    """Derived from source, not hand-listed: a NEW hold branch anywhere in the
    file is picked up automatically the moment it matches the shape every
    existing hold site already uses."""
    branches = [i for i, line in enumerate(SRC_LINES) if _HOLD_BRANCH_RE.match(line)]
    assert len(branches) >= 4, (
        f"expected at least the primary reply + 3 unsolicited hold sites (referral/checkin/event), found {len(branches)} — "
        "the shape this guard scans for may have changed"
    )
    offenders = [i + 1 for i in branches if "_emit_hold(" not in _block_after(i)]
    assert offenders == [], (
        f"hold branch(es) at line(s) {offenders} never call _emit_hold(...) — a held reply on that "
        "path would go unmetered, exactly #2823's defect"
    )


def test_emit_hold_logs_the_alarm_token():
    """Direct unit test of the helper: the log line carries the exact literal
    the CloudWatch MetricFilter scans for, plus the kind/status it was called with."""
    logged: list = []

    class _Capture(logging.Handler):
        def emit(self, record):
            logged.append(record.getMessage())

    handler = _Capture()
    worker.logger.addHandler(handler)
    try:
        worker._emit_hold("sleep_coach", worker.HOLD_KIND_REPLY, "held")
    finally:
        worker.logger.removeHandler(handler)
    assert logged, "no log line emitted"
    assert worker.TELEGRAM_COACH_HOLD_TOKEN in logged[0]
    assert "kind=reply" in logged[0]
    assert "status=held" in logged[0]
    assert "sleep_coach" in logged[0]


# ── The twin pin: lambda token == CDK MetricFilter token (the #2654 pattern) ──


def test_hold_token_twin_with_monitoring_filter():
    """The CDK MetricFilter literal and the lambda's token may not drift — the
    same twin discipline #2763 and #2977 already carry, resolved across the
    whole cdk/stacks tree so a future extraction (like #2977's own move into
    this sibling module) cannot silently break the pin."""
    import cdk_alarm_pins

    tokens = cdk_alarm_pins.filter_tokens_for("telegram-coach-hold")
    assert tokens, "no CDK stack wires the telegram-coach-hold alarm to a literal filter token"
    assert tokens == {worker.TELEGRAM_COACH_HOLD_TOKEN}, f"CDK filter token(s) {sorted(tokens)} != {worker.TELEGRAM_COACH_HOLD_TOKEN!r}"


# ── Mutation proof: a forced hold on each of the four real paths ──────────────
#
# The harness mirrors tests/test_coach_outbound_behavior.py's `wired` fixture —
# every AWS edge replaced, the clock injected, nothing here reads real time or
# touches the network.

STORE = {
    "sleep": {"bot_token": "tok-sleep", "chat_ids": [4242]},
    "pattern": {"bot_token": "tok-pattern", "chat_ids": [4242]},
}


class QuietTable:
    """Reads return nothing; writes are recorded."""

    def __init__(self):
        self.puts: list = []

    def query(self, **kwargs):
        return {"Items": []}

    def get_item(self, **kwargs):
        return {}

    def put_item(self, **kwargs):
        self.puts.append(kwargs["Item"])

    def update_item(self, **kwargs):
        return {}


class Harness:
    def __init__(self):
        self.sends: list = []
        self.warnings: list = []
        self.table = QuietTable()


@pytest.fixture
def wired(monkeypatch):
    h = Harness()

    class _Capture(logging.Handler):
        def emit(self, record):
            h.warnings.append(record.getMessage())

    cap = _Capture()
    worker.logger.addHandler(cap)

    monkeypatch.setattr(worker, "_tg", lambda token, method, payload: h.sends.append((token, method, dict(payload))))
    monkeypatch.setattr(worker, "_secret_entry", lambda key: dict(STORE.get(key) or {}))
    monkeypatch.setattr(worker, "_seen_update", lambda cid, uid: False)
    monkeypatch.setattr(worker, "_chat_rows", lambda cid, limit=40: [])
    monkeypatch.setattr(worker, "_facts", lambda: {})
    monkeypatch.setattr(worker, "_memory_block", lambda cid: "")
    monkeypatch.setattr(worker, "_current_tier", lambda: 0)
    monkeypatch.setattr(worker, "_s3_client", lambda: None)
    monkeypatch.setattr(worker, "_cycle", lambda: 13)
    monkeypatch.setattr(worker, "_table", lambda: h.table)
    monkeypatch.setattr(worker, "_pacific_now", lambda: WEDNESDAY_10AM)
    monkeypatch.setattr(worker.telegram_gateway, "is_stale", lambda ts, now: False)
    monkeypatch.setattr("coach.coach_domain_facts.domain_facts_block", lambda pid, table: "")
    monkeypatch.setattr("time.sleep", lambda s: None)
    yield worker, h
    worker.logger.removeHandler(cap)


def _held(text="Let me check that.", status="held"):
    return coach_chat.TurnResult(text, status, [{"type": "night"}], 2, bubbles=[text] if text else [])


def _sent(text="A clean, grounded reply."):
    return coach_chat.TurnResult(text, "sent", [], 1, bubbles=[text])


def _hold_lines(h, kind):
    return [m for m in h.warnings if worker.TELEGRAM_COACH_HOLD_TOKEN in m and f"kind={kind}" in m]


def test_a_held_primary_reply_emits_the_hold_token(wired, monkeypatch):
    worker_mod, h = wired
    monkeypatch.setattr(worker_mod.coach_chat, "run_turn", lambda **kw: _held())
    out = worker_mod.lambda_handler({"coach_id": "sleep", "chat_id": 4242, "text": "how's my HRV trending?"}, None)
    assert out["status"] == "held"
    assert h.sends, "the honest deferral must still be sent (#2517) — the hold branch is metric-only"
    lines = _hold_lines(h, worker_mod.HOLD_KIND_REPLY)
    assert len(lines) == 1, f"expected exactly one reply-hold token, got: {h.warnings}"
    assert "status=held" in lines[0]


def test_a_grounded_primary_reply_emits_no_hold_token(wired, monkeypatch):
    """Control: the happy path must not touch the alarm's metric at all."""
    worker_mod, h = wired
    monkeypatch.setattr(worker_mod.coach_chat, "run_turn", lambda **kw: _sent())
    out = worker_mod.lambda_handler({"coach_id": "sleep", "chat_id": 4242, "text": "how's my HRV trending?"}, None)
    assert out["status"] == "sent"
    assert not _hold_lines(h, worker_mod.HOLD_KIND_REPLY)


def test_a_held_referral_emits_the_hold_token(wired, monkeypatch):
    """The primary reply is CLEAN and carries a referral marker; the referred
    coach's own turn is what holds — the unsolicited-outbound class."""
    worker_mod, h = wired
    replies = [_sent("Sleep first, then the rest.\n[[refer: pattern_coach]]"), _held()]
    calls = {"n": 0}

    def fake_run_turn(**kw):
        result = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return result

    monkeypatch.setattr(worker_mod.coach_chat, "run_turn", fake_run_turn)
    out = worker_mod.lambda_handler({"coach_id": "sleep", "chat_id": 4242, "text": "can't switch off at night"}, None)
    assert "referred_to" not in out, "a held referral must never reach Matthew's phone"
    lines = _hold_lines(h, worker_mod.HOLD_KIND_REFERRAL)
    assert len(lines) == 1, f"expected exactly one referral-hold token, got: {h.warnings}"
    # The primary reply itself was grounded — no reply-hold token alongside it.
    assert not _hold_lines(h, worker_mod.HOLD_KIND_REPLY)


def test_a_held_checkin_emits_the_hold_token(wired, monkeypatch):
    worker_mod, h = wired
    monkeypatch.setattr(worker_mod, "_secret_entry", lambda key: {"bot_token": "tok-eli", "chat_ids": [4242]})
    monkeypatch.setattr(worker_mod.coach_chat, "run_turn", lambda **kw: _held())
    out = worker_mod.lambda_handler({"kind": "morning_checkin"}, None)
    assert out == {"ok": True, "reason": "held"}
    assert h.sends == []
    lines = _hold_lines(h, worker_mod.HOLD_KIND_CHECKIN)
    assert len(lines) == 1, f"expected exactly one checkin-hold token, got: {h.warnings}"


def test_a_held_event_ping_emits_the_hold_token(wired, monkeypatch):
    worker_mod, h = wired
    import unittest.mock as mock

    from coach import coach_event_triggers as triggers

    with mock.patch.object(
        triggers,
        "run_sweep",
        side_effect=lambda **kw: kw["speak"](
            {"persona_id": "sleep_coach", "frame": "frame", "evidence": [], "provenance": "telegram_concern", "event_id": "e1"},
            "tok-sleep",
            4242,
        ),
    ):
        monkeypatch.setattr(worker_mod.coach_chat, "run_turn", lambda **kw: _held())
        out = worker_mod.lambda_handler({"kind": "event_outbound"}, None)
    assert out == {"ok": True, "reason": "held"}
    assert h.sends == []
    lines = _hold_lines(h, worker_mod.HOLD_KIND_EVENT)
    assert len(lines) == 1, f"expected exactly one event-hold token, got: {h.warnings}"
