"""tests/test_coach_reactions.py — behavior pins for reaction emojis (#2485).

The mechanism: a bare acknowledgement can be closed with a Telegram
``setMessageReaction`` on Matthew's own message INSTEAD of a reply bubble.

What is pinned here, in the order the defects would actually appear:

* the trigger is deterministic and narrow — an acknowledgement that carries a
  real question is not an acknowledgement;
* the emoji is governed by each persona's own ``emoji_posture``, derived from the
  SHIPPED configs rather than a hand-written fixture, so a future posture edit
  that silently makes an austere coach chatty reds this file;
* the reaction is a genuine ALTERNATIVE to a reply — nothing is sent, and the
  cap accounting stays whole in BOTH directions (a capped coach does not react
  instead of admitting the cap; a day of reactions does not spend the cap).
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from coach import coach_chat, coach_reactions  # noqa: E402

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config", "coaches")


def _spec(name):
    with open(os.path.join(_CONFIG_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── The trigger class ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["thanks", "Thanks!", "thank you.", "ok", "Got it", "gotcha", "will do", "noted", "👍", "ty"])
def test_bare_acknowledgements_qualify(text):
    assert coach_reactions.is_bare_acknowledgement(text)


@pytest.mark.parametrize(
    "text",
    [
        "thanks, but what about my sleep?",  # an acknowledgement wrapping a question
        "ok so should I lift today or not",
        "yeah",  # an ANSWER to the coach's question — reacting leaves it hanging
        "yep",
        "I ran 3 miles",
        "🤔",  # a prompt for more, not a close
        "",
        "   ",
    ],
)
def test_real_messages_do_not_qualify(text):
    assert not coach_reactions.is_bare_acknowledgement(text)


def test_trigger_is_whole_message_not_substring():
    """The defect this prevents: substring matching would close a thread that
    Matthew had just opened, because he happened to be polite about it."""
    assert not coach_reactions.is_bare_acknowledgement("thanks — one more thing, is that deficit too aggressive")


# ── Posture governance, off the shipped configs ───────────────────────────────


@pytest.mark.parametrize("coach", ["mind_coach", "career_coach", "pattern_coach", "sleep_coach", "eli_marsh"])
def test_austere_personas_never_react(coach):
    """ "Essentially never" / "Rare to never" means never. These coaches do not
    start throwing 👍 because a new transport learned a new verb."""
    assert coach_reactions.reaction_for(_spec(coach)) is None


@pytest.mark.parametrize("coach,expected", [("physical_coach", "👍"), ("nutrition_coach", "👌")])
def test_permissive_personas_react_in_their_own_mark(coach, expected):
    assert coach_reactions.reaction_for(_spec(coach)) == expected


def test_no_shared_default_across_coaches():
    """The AC's real requirement: never one emoji for everyone. Every coach that
    reacts at all reacts with a DISTINCT mark, and most react with nothing."""
    marks = [coach_reactions.reaction_for(_spec(c[: -len(".json")])) for c in os.listdir(_CONFIG_DIR) if c.endswith("_coach.json")]
    reacting = [m for m in marks if m]
    assert len(reacting) == len(set(reacting)), f"two coaches share a reaction: {reacting}"


def test_unconfigured_posture_reacts_with_nothing():
    """ADR-104 absence honesty applied to voice: no posture, no invented one."""
    assert coach_reactions.reaction_for({"texting_style": {}}) is None
    assert coach_reactions.reaction_for({}) is None
    assert coach_reactions.reaction_for(None) is None


def test_posture_named_emoji_wins_when_telegram_permits_it():
    spec = {"texting_style": {"emoji_posture": "At most a 🔥 when a session genuinely earns it.", "reaction_emoji": "👍"}}
    assert coach_reactions.reaction_for(spec) == "🔥"


def test_illegal_emoji_in_config_is_rejected_not_sent():
    """Telegram permits a FIXED reaction set; 💪 and 📈 are not on it. Config is
    validated against the set rather than trusted — an unlisted mark is an API
    error, so the honest outcome is no reaction at all."""
    assert "💪" not in coach_reactions.ALLOWED_REACTIONS
    assert coach_reactions.reaction_for({"texting_style": {"emoji_posture": "One 💪 after a PR."}}) is None
    assert coach_reactions.reaction_for({"texting_style": {"emoji_posture": "Rare.", "reaction_emoji": "💪"}}) is None
    # …and the explorer's shipped 📉/📈 posture is exactly that case, live.
    assert coach_reactions.reaction_for(_spec("explorer_coach")) is None


def test_qualifier_never_does_not_silence_a_permissive_posture():
    """physical's posture ENDS "Never decorative" — a rule about how, not whether.
    Scanning the whole string for "never" would have silenced it."""
    posture = _spec("physical_coach")["texting_style"]["emoji_posture"]
    assert "Never" in posture and coach_reactions.posture_permits_emoji(posture)


# ── The cap, on the mechanism that actually runs ──────────────────────────────


def test_reaction_is_cap_bound_to_the_real_gate():
    """The live cap on the reply path is DAILY_TURN_CAP via budget_refusal (the
    issue's `claim_outbound` is never called here). A capped or paused coach says
    so plainly instead of hiding the condition behind a friendly gesture."""
    assert coach_chat.reaction_allowed("thanks", 0, 0) is True
    assert coach_chat.reaction_allowed("thanks", 0, coach_chat.DAILY_TURN_CAP) is False
    assert coach_chat.reaction_allowed("thanks", 3, 0) is False
    assert coach_chat.reaction_allowed("what should I eat today", 0, 0) is False


def test_reactions_do_not_spend_the_turn_cap():
    """Cap-neutrality, at the counter that enforces it: N reacted exchanges leave
    the day's remaining answers untouched."""
    import telegram_worker_lambda as w

    real = [
        {"role": coach_chat.ROLE_MATTHEW, "text": "how did I sleep"},
        {"role": coach_chat.ROLE_COACH, "text": "6h14m.", "status": "sent"},
    ]
    reacted = [
        {"role": coach_chat.ROLE_MATTHEW, "text": "thanks"},
        {"role": coach_chat.ROLE_COACH, "text": "👍", "status": coach_chat.STATUS_REACTED},
    ]
    assert w._turns_today(real) == 1
    assert w._turns_today(real + reacted * 5) == 1


# ── The transport: a reaction INSTEAD of a reply ──────────────────────────────


@pytest.fixture
def worker():
    import telegram_worker_lambda as w

    return w


def _react(worker, spec, text="thanks", message_id=77, thread=None):
    calls = []
    with (
        patch.object(worker, "_tg", side_effect=lambda t, m, p: calls.append((m, p))),
        patch.object(worker, "_current_tier", return_value=0),
        patch.object(worker, "_cycle", return_value=13),
        patch.object(worker, "_table", return_value=MagicMock()),
        patch.object(worker, "_s3_client", return_value=None),
        patch.object(worker, "_emit_metric"),
        patch("coach.persona_core.load_voice_spec", return_value=spec),
    ):
        fired = worker._react("tok", 42, message_id, "physical_coach", "Coach", text, thread or [])
    return fired, calls


def test_reaction_replaces_the_reply_and_calls_setmessagereaction(worker):
    fired, calls = _react(worker, _spec("physical_coach"))
    assert fired is True
    assert [m for m, _ in calls] == ["setMessageReaction"], "a reaction must be an ALTERNATIVE to a reply, never an extra bubble"
    payload = calls[0][1]
    assert payload["message_id"] == 77 and payload["chat_id"] == 42
    assert json.loads(payload["reaction"]) == [{"type": "emoji", "emoji": "👍"}]


def test_austere_persona_sends_nothing_and_falls_through_to_a_real_reply(worker):
    fired, calls = _react(worker, _spec("mind_coach"))
    assert fired is False and calls == []


def test_a_real_question_falls_through_to_inference(worker):
    fired, calls = _react(worker, _spec("physical_coach"), text="should I lift today")
    assert fired is False and calls == []


def test_missing_message_id_falls_through(worker):
    """Telegram cannot be asked to react to a message id we do not have; the
    honest fallback is a normal reply, not a dropped turn."""
    fired, calls = _react(worker, _spec("physical_coach"), message_id=None)
    assert fired is False and calls == []


def test_the_exchange_still_joins_memory_with_a_reacted_status(worker):
    """A reaction is not a gap: the thread must show his message and the coach's
    answer, or a later reader sees a message that was never answered."""
    import telegram_worker_lambda as w

    table = MagicMock()
    with (
        patch.object(w, "_tg"),
        patch.object(w, "_current_tier", return_value=0),
        patch.object(w, "_cycle", return_value=13),
        patch.object(w, "_table", return_value=table),
        patch.object(w, "_s3_client", return_value=None),
        patch.object(w, "_emit_metric"),
        patch("coach.persona_core.load_voice_spec", return_value=_spec("physical_coach")),
    ):
        assert w._react("tok", 42, 77, "physical_coach", "Coach", "thanks", []) is True

    stored = [c.kwargs["Item"] for c in table.put_item.call_args_list]
    assert [i["role"] for i in stored] == [coach_chat.ROLE_MATTHEW, coach_chat.ROLE_COACH]
    assert stored[1]["text"] == "👍" and stored[1]["status"] == coach_chat.STATUS_REACTED


def test_the_handler_reacts_before_it_ever_reaches_inference(worker):
    """The AST pin at the call site: a gate that runs AFTER run_turn would have
    already paid for the model call it exists to avoid, and every unit test of
    _react would still pass. Pin the ORDER in the handler source."""
    import ast
    import inspect

    src = inspect.getsource(worker.lambda_handler)
    tree = ast.parse(src.strip())
    calls = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))
    names = [c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", "") for c in calls]
    assert "_react" in names, "lambda_handler must consult the reaction path"
    assert names.index("_react") < names.index("run_turn"), "the reaction gate must precede run_turn"
