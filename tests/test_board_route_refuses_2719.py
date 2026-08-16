"""#2719 — a route that resolves to no persona must refuse, not answer as a nameless coach.

Found while working #2677, 2026-08-15. `@ajm_board_bot` is **live**: provisioned in the
`life-platform/telegram` secret with a `bot_token` and a discovered `chat_id`. No persona
carries `telegram_route: "board"` — checked in `config/personas.json` and in the live
`s3://matthew-life-platform/config/personas.json`. So a board message walked all the way
through:

    ROUTING["board"] = "board"                         webhook accepts it
    persona_for_telegram_route("board") -> (None, None)  no seat claims the route
    derived = "board_coach"                             the f-string fallback
    _persona_is_retired("board_coach") -> False         it is not RETIRED, it is ABSENT
    _assemble("board_coach", "board")                   display_name returns the raw id
      -> TelegramPersonaMissing, name degraded to "Matthew's board coach"

…and answered with no persona block, no voice spec, and a name derived from an internal
id. That is the exact failure `_assemble`'s own comment records as an incident: "the pair
of paths that was MISSING when every conversation ran nameless ('I'm mind_coach') and
persona-free."

The retired-seat guard added in the ADR-153 amendment catches a derived id that names a
RETIRED persona. It does not catch one that names NO persona, and it says so implicitly by
returning False for both cases. `board_coach` is the second kind.

STATIC READING, NOT AN OBSERVED FAILURE. `aws logs filter-log-events` over
`/aws/lambda/telegram-coach-worker` for 30 days returns no board delivery, and
`LifePlatform/Telegram` publishes only `EventSweepCompleted`. The path looks unexercised
rather than proven-broken; the first message Matthew sends to the board bot is what would
prove it. That is why this fixes the REFUSAL and not the routing: which persona (or
multi-coach assembly) should answer Grand Rounds is a design question under #2363, and
guessing it here would silently decide it.

THE DISTINCTION THAT KEEPS THIS FROM DARKING A WORKING COACH is registry READABLE versus
persona ABSENT, and it is why `_persona_known` returns three values rather than a bool:

    False  registry read fine, no such persona   -> permanent misconfiguration, refuse
    None   registry unreadable, or empty         -> transient, fall through to the old
                                                    degraded-but-answering behaviour
    True   persona exists                        -> proceed

`bool(personas().get(pid))` answers False for the first two alike, and would have turned
every registry outage into total silence across all ten bots — a far worse failure than
the one this guard exists to fix, and the same reasoning `_persona_is_retired` documents
for its own fail-soft.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from coach import telegram_worker_lambda as worker  # noqa: E402

PERSONAS = json.loads((pathlib.Path(_REPO) / "config" / "personas.json").read_text())["personas"]


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch):
    """Nothing here talks to AWS, and nothing here may send a message.

    The three guards that sit BEFORE persona resolution are stubbed to their pass-through
    values — dedupe (DynamoDB), staleness (wall clock) and the bot token. Leaving any of
    them live would short-circuit the handler before the code under test, which is how a
    test ends up proving nothing while looking green (§9a).
    """
    monkeypatch.setattr(worker, "_s3_client", lambda: None)
    monkeypatch.setattr(worker, "_bot_token", lambda key: "tok")
    monkeypatch.setattr(worker, "_emit_metric", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_seen_update", lambda *a, **k: False)
    monkeypatch.setattr(worker.telegram_gateway, "is_stale", lambda *a, **k: False)
    sent = []
    monkeypatch.setattr(worker, "_tg", lambda token, method, payload: sent.append((method, payload)))
    return sent


def _order(coach_id):
    return {"coach_id": coach_id, "chat_id": 1, "text": "hello", "message_id": 7, "update_id": 1}


def test_the_fixture_reaches_the_code_under_test(monkeypatch):
    """Vacuity guard for the stubs above: a working route must reach _assemble, or every
    refusal assertion below could be a dedupe/staleness short-circuit wearing a costume."""
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: dict(PERSONAS))
    monkeypatch.setattr(worker, "_assemble", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reached assembly")))
    with pytest.raises(AssertionError, match="reached assembly"):
        worker.lambda_handler(_order("sleep"), None)


# ── the precondition, updated by the resolution it demanded ──────────────────
# #2719 owner decision (2026-08-16): Grand Rounds is CHAIRED BY THE LEAD —
# eli_marsh claims `board` via telegram_route_aliases. The refusal tests below
# keep their full mechanism coverage by testing the SAME route and derived id
# against a registry snapshot WITHOUT the alias (the exact pre-resolution
# shape); the live registry now resolves, and the last test in this file pins
# that board reaches assembly like the other ten routes.


def _registry_without_board_alias():
    """The pre-#2769 registry shape: board resolves to nothing, board_coach absent."""
    reg = {k: dict(v) for k, v in PERSONAS.items()}
    reg["eli_marsh"]["telegram_route_aliases"] = [a for a in (reg["eli_marsh"].get("telegram_route_aliases") or []) if a != "board"]
    return reg


def test_the_board_route_is_claimed_by_the_lead():
    claimed = [
        pid for pid, p in PERSONAS.items() if p.get("telegram_route") == "board" or "board" in (p.get("telegram_route_aliases") or [])
    ]
    assert claimed == ["eli_marsh"], f"board must be chaired by the lead (#2719 owner decision): {claimed}"
    assert "board_coach" not in PERSONAS, "the derived fallback id must stay absent — the refusal guard protects that class"


# ── the three-valued existence check ─────────────────────────────────────────


def test_a_known_persona_reads_true(monkeypatch):
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: dict(PERSONAS))
    assert worker._persona_known("sleep_coach") is True


def test_an_absent_persona_reads_false(monkeypatch):
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: dict(PERSONAS))
    assert worker._persona_known("board_coach") is False


def test_a_raising_registry_reads_none_not_false(monkeypatch):
    """THE distinction. False and None must never collapse, or an outage darks every bot."""

    def _boom(*_a, **_k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr("coach.persona_registry.personas", _boom)
    assert worker._persona_known("sleep_coach") is None


def test_an_empty_registry_reads_none_not_false(monkeypatch):
    """A failed S3 read plus a missing local file looks exactly like an empty dict."""
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: {})
    assert worker._persona_known("sleep_coach") is None


# ── the refusal ──────────────────────────────────────────────────────────────


def test_an_unmapped_route_refuses_rather_than_answering_nameless(monkeypatch, _no_aws):
    """The refusal mechanism, on the exact pre-resolution registry shape."""
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: _registry_without_board_alias())
    result = worker.lambda_handler(_order("board"), None)
    assert result == {"ok": True, "reason": "route_unmapped"}, result
    assert _no_aws == [] or all(m != "sendMessage" for m, _ in _no_aws), f"a refusal must send nothing: {_no_aws}"


def test_the_refusal_is_a_2xx_so_telegram_does_not_redeliver(monkeypatch, _no_aws):
    """`ok: True` is the transport contract, not a claim that the message was answered."""
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: _registry_without_board_alias())
    assert worker.lambda_handler(_order("board"), None)["ok"] is True


def test_the_refusal_is_loud(monkeypatch):
    """A silent refusal is the same defect wearing a different coat.

    The logger is captured by monkeypatching `logger.error` rather than with `caplog`:
    the platform logger is a configured, non-propagating instance, so caplog sees nothing
    and the assertion would pass vacuously against a refusal that logged nothing at all.
    """
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: _registry_without_board_alias())
    emitted, logged = [], []
    monkeypatch.setattr(worker, "_emit_metric", lambda name, *a, **k: emitted.append(name))
    monkeypatch.setattr(worker.logger, "error", lambda msg, *a, **k: logged.append(msg % a if a else msg))
    worker.lambda_handler(_order("board"), None)
    assert "TelegramUnmappedRouteRefused" in emitted, emitted
    assert any("not in the registry" in m for m in logged), logged
    assert any("board_coach" in m for m in logged), "the log must name the id it could not find"


# ── the controls: what must NOT change ───────────────────────────────────────


def test_a_registry_outage_still_falls_through_to_the_old_behaviour(monkeypatch):
    """The fail-soft. Darking every coach on a transient read is worse than a degraded name.

    An outage is modelled as `personas()` returning `{}` rather than raising, because that
    is what one actually looks like: `load_registry` already swallows both the S3 error and
    a missing local file and returns `{"personas": {}}`. A test that raised here would be
    testing a path the real registry cannot produce.
    """
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: {})
    monkeypatch.setattr(worker, "_assemble", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reached assembly — correct")))
    with pytest.raises(AssertionError, match="reached assembly"):
        worker.lambda_handler(_order("board"), None)


def test_a_retired_seat_still_refuses_with_its_own_reason(monkeypatch):
    """The ADR-153 guard is untouched — retired and absent stay distinguishable."""
    reg = dict(PERSONAS)
    reg["training_coach"] = {"retired": True, "name": "Dr. Sarah Chen"}
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: reg)
    assert worker.lambda_handler(_order("training"), None) == {"ok": True, "reason": "route_retired"}


@pytest.mark.parametrize("route", ["sleep", "nutrition", "physical", "headcoach", "labs", "pattern", "career", "explorer", "mind", "board"])
def test_every_route_that_resolves_today_still_reaches_assembly(monkeypatch, route):
    """The live routes that work must be untouched — a guard that stops a working
    coach is a worse bug than the nameless reply it replaces. `board` joined the
    set with the #2719 resolution (chaired by the lead)."""
    monkeypatch.setattr("coach.persona_registry.personas", lambda *a, **k: dict(PERSONAS))
    monkeypatch.setattr(worker, "_assemble", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reached assembly")))
    with pytest.raises(AssertionError, match="reached assembly"):
        worker.lambda_handler(_order(route), None)
