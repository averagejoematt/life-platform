"""#2677 — a Telegram route that cannot answer must be declared or deleted, never left to rot.

The issue: `ROUTING["training"]` is unreachable, and the comment justifying it references
aliases that do not exist.

Both halves are right, and the second one is right for a sharper reason than "the aliases
were never written". `telegram_route_aliases` is a real mechanism
(`persona_registry.persona_for_telegram_route` resolves it) and it was real DATA for two
days. **ADR-153's 2026-08-12 amendment reversed its own 2026-08-10 one and retired the
alias**, stating the consequence in as many words:

    "`training` is now deliberately unmapped and fails CLOSED in
     gateway.resolve_coach, which is correct: there is no separate training seat."

The registry data was updated that day. `telegram_webhook_lambda.ROUTING` was not. So the
key kept resolving to a coach id no persona claims, and `resolve_coach` — the thing the ADR
names as the gate — never got the chance to fail closed. The comment above the key was
describing a decision that had already been reversed underneath it.

WHY DELETION AND NOT RE-ADDING THE ALIAS. Re-adding it would make the key "work" and would
silently undo a load-bearing decision: the PRIMARY `telegram_route` is the canonical
OUTBOUND route, so a seat reachable only by alias can be texted but can never text first —
Max's morning check-ins and event-triggered outbound would have stayed dark. That is the
whole reason the alias was retired in favour of `@ajm_training_bot` becoming the Performance
seat's primary `physical` route. `tests/test_persona_registry.py` pins
`persona_for_telegram_route("training") == (None, None)` for exactly this reason, and it is
the assertion that caught the wrong fix here before it shipped.

`glucose` looks like the same case and is NOT — which is why the guard declares rather than
deletes. `setup_telegram_bots.OPTIONAL_BOTS` lists @ajm_glucose_bot as deliberately not
created ("an unused bot is a live public webhook endpoint, so it is attack surface bought
for no benefit") while remaining addable with an explicit argument, and
`tests/test_telegram_transport.py` requires every roster key to be routable. Deleting it to
make this file green would have broken a deliberate decision. What the declaration adds is
the part nobody would otherwise notice: creating the bot would not be enough, because
`glucose_coach` carries no `telegram_route` either — the day the bot exists it lands in
exactly the `board` failure below.

A THIRD ROUTE IS WORSE THAN THE ONE FILED, AND CANNOT BE DELETED. `board` has a live bot AND
a chat id in the `life-platform/telegram` secret (read 2026-08-15: board, career, explorer,
headcoach, labs, mind, nutrition, pattern, physical, sleep) and claims no persona. A message
to it resolves nothing, falls back to the derived `board_coach`, and answers as "Matthew's
board coach" — the nameless, persona-free reply `telegram_worker_lambda._assemble`'s own
comment records as an incident. Static reading, not an observed failure: the worker log
holds no board delivery, so the path looks unexercised rather than proven-broken. Declared
in ROUTE_GAPS and filed separately, because the board is meant to be multi-coach Grand
Rounds (#2363) — a design question, not a mapping fix.

THE GUARD IS THE POINT. Three routes were dead in three different ways, each silent in a
different place, and the one that was found was found by a bug bash rather than by CI. So
this file does not assert "training is gone". It asserts that EVERY key in ROUTING resolves
to a persona or appears in ROUTE_GAPS with a reason, and that no key lingers in ROUTE_GAPS
once it works.
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
from coach import telegram_gateway as gateway  # noqa: E402
from coach.persona_registry import persona_for_telegram_route  # noqa: E402
from web.telegram_webhook_lambda import ROUTE_GAPS, ROUTING  # noqa: E402

PERSONAS = json.loads((pathlib.Path(_REPO) / "config" / "personas.json").read_text())["personas"]

# The bots actually provisioned in the life-platform/telegram secret, read 2026-08-15.
# Hard-coded and SAID to be hard-coded: Secrets Manager is not reachable from a unit test,
# and dressing this up as derived would be the more dangerous of the two options.
LIVE_BOTS = ["board", "career", "explorer", "headcoach", "labs", "mind", "nutrition", "pattern", "physical", "sleep"]


def _claiming_persona(route: str):
    """The persona that claims `route`, by primary field or by succession alias."""
    for pid, p in PERSONAS.items():
        if p.get("telegram_route") == route or route in (p.get("telegram_route_aliases") or []):
            return pid
    return None


# ── the guard ────────────────────────────────────────────────────────────────


def test_routing_is_not_empty():
    """Vacuity guard — an empty ROUTING passes every assertion below."""
    assert len(ROUTING) >= 10, f"only {len(ROUTING)} routes — import broke"


@pytest.mark.parametrize("route", sorted(ROUTING))
def test_every_route_either_resolves_to_a_persona_or_is_declared_a_gap(route):
    """A route that cannot answer is DECLARED, never discovered."""
    if _claiming_persona(route):
        return
    assert route in ROUTE_GAPS, (
        f"ROUTING declares {route!r} but no persona claims it via telegram_route or "
        f"telegram_route_aliases, and it is not in ROUTE_GAPS. Delete the key so resolve_coach "
        f"fails closed, give a persona the route, or add a ROUTE_GAPS entry naming what is "
        f"missing and why the key must stay (#2677)."
    )
    assert len(ROUTE_GAPS[route]) > 60, f"{route}'s gap entry must say WHAT is missing, not merely that something is"


@pytest.mark.parametrize("route", sorted(ROUTE_GAPS))
def test_every_declared_gap_names_a_route_that_actually_exists(route):
    """A stale gap entry is its own kind of lie — it excuses a route nobody declared."""
    assert route in ROUTING, f"ROUTE_GAPS excuses {route!r}, which is not in ROUTING at all"


def test_no_route_is_excused_while_it_already_resolves():
    """The ratchet closes: once a route has a persona, its excuse must be deleted."""
    wrongly_excused = [r for r in ROUTE_GAPS if _claiming_persona(r)]
    assert not wrongly_excused, f"these routes resolve and should leave ROUTE_GAPS: {wrongly_excused}"


def test_every_live_bot_has_a_route():
    """A provisioned bot with no ROUTING key is the mirror failure — deliveries rejected outright."""
    unaccounted = [b for b in LIVE_BOTS if b not in ROUTING]
    assert not unaccounted, f"a live bot with no route: {unaccounted}"


# ── the ADR the code had drifted from ────────────────────────────────────────


def test_the_training_route_is_gone_and_fails_closed():
    """ADR-153's 2026-08-12 amendment: "deliberately unmapped and fails CLOSED"."""
    assert "training" not in ROUTING
    with pytest.raises(gateway.Rejected):
        gateway.resolve_coach("training", ROUTING)


def test_no_persona_claims_training_and_none_should():
    """The alias was retired ON PURPOSE. Re-adding it to make the key work would undo the
    reason — a seat reachable only by alias can be texted but can never text first, so
    Max's outbound check-ins would go dark. Guarded here as well as in
    tests/test_persona_registry.py, because this file is where someone would be tempted."""
    assert _claiming_persona("training") is None
    assert persona_for_telegram_route("training") == (None, None)
    assert not any(p.get("telegram_route_aliases") for p in PERSONAS.values()), "no succession alias is live"


def test_glucose_stays_routable_but_is_declared():
    """The route that must NOT be deleted, and the reason it is different from training.

    setup_telegram_bots.OPTIONAL_BOTS lists @ajm_glucose_bot as deliberately not created —
    "an unused bot is a live public webhook endpoint, so it is attack surface bought for no
    benefit" — while staying addable with an explicit argument, and
    tests/test_telegram_transport.py requires every roster key to be routable. Deleting the
    key to make this file's guard pass would have broken that. Declaring it is the honest
    move, and the declaration carries the part nobody would otherwise notice: creating the
    bot alone is not enough, because glucose_coach has no telegram_route either.
    """
    assert ROUTING["glucose"] == "glucose"
    assert PERSONAS["glucose_coach"].get("telegram_route") is None
    assert "glucose" in ROUTE_GAPS and "no telegram_route" in ROUTE_GAPS["glucose"]


def test_every_setup_roster_key_is_still_routable():
    """The invariant the deletion could have broken, checked here as well as in
    tests/test_telegram_transport.py — this file is where the temptation to delete lives."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("setup_telegram_bots", os.path.join(_REPO, "setup", "setup_telegram_bots.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.ALL_KEYS) <= set(ROUTING), f"unroutable bots: {set(mod.ALL_KEYS) - set(ROUTING)}"
    assert "training" not in mod.ALL_KEYS, "ALIAS_BOTS is empty — the roster already retired it"


def test_the_performance_seat_keeps_its_primary_route():
    """The other half of the amendment: @ajm_training_bot is now the `physical` route."""
    assert ROUTING["physical"] == "physical"
    assert persona_for_telegram_route("physical")[0] == "physical_coach"


def test_the_labs_bot_the_amendment_granted_still_resolves():
    """ADR-153 2026-08-12 decision 1 — a bot is granted by telegram_route, not a tier flag."""
    assert ROUTING["labs"] == "labs"
    assert persona_for_telegram_route("labs")[0] == "labs_coach"
    assert PERSONAS["labs_coach"].get("consulting") is True, "still consulting-tier, and still has a bot"


# ── the third route, declared rather than guessed at ─────────────────────────


def test_board_is_kept_and_declared_because_its_bot_is_real():
    assert "board" in ROUTING, "a live, chat-id-bearing bot must keep its route"
    assert _claiming_persona("board") is None
    assert "board" in ROUTE_GAPS and "NO PERSONA" in ROUTE_GAPS["board"]


def test_no_route_survives_only_because_a_comment_says_so():
    """The failure this file replaces: a dead key justified by prose nobody re-checks.

    Every remaining unresolved route is in ROUTE_GAPS — a dict a test reads — rather than
    in a comment, which is what let the `training` key outlive the decision it cited.
    """
    unresolved = {r for r in ROUTING if not _claiming_persona(r)}
    assert unresolved == set(ROUTE_GAPS), f"unresolved routes {unresolved} vs declared {set(ROUTE_GAPS)}"


# ── the security posture, unchanged ──────────────────────────────────────────


@pytest.mark.parametrize("bogus", ["definitely-not-a-bot", "TRAINING", "training ", ""])
def test_an_unknown_bot_key_still_fails_closed(bogus):
    with pytest.raises(gateway.Rejected):
        gateway.resolve_coach(bogus, ROUTING)


def test_the_surviving_routes_all_still_dispatch():
    """The control: removing two keys must not have disturbed the ten that work."""
    for route in ROUTING:
        assert gateway.resolve_coach(route, ROUTING) == ROUTING[route]
