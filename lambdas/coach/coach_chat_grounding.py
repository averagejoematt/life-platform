"""coach_chat_grounding.py — the fact block and the gate arming for the coach chat
(#2364, epic #2363).

Kept separate from ``coach_chat`` so that module can stay a pure, AWS-free turn
engine. This is the half that knows what is TRUE today, and it is deliberately thin:
everything here is a call into machinery that already exists, because a chat surface
inventing its own notion of "the facts" is exactly how two doors end up telling a
reader two truths.

NOTHING IS REIMPLEMENTED. The first draft of this module carried its own
``allowed_numbers``/``allowed_dates`` walkers; review caught that
``ai.grounded_generation`` already exports both (``coach_history_summarizer``
imports them), and the shared versions are *better*: they derive the allow-list from
EVERYTHING the model was given — facts, memory, the thread — not just the fact dict.
That difference is behavioural, not cosmetic: a coach quoting its own memory block
("you committed to 170 g") must not read as fabricating 170, and a fact-dict-only
walker would have flagged it. Benign small integers are likewise the gate's own
``_BENIGN_NUMBERS``, not a local list.

WHY THIS SURFACE ARMS ALL FIVE GATE CLASSES

Every other coach surface in ``tests/grounding_wiring.py`` exempts at least one class
with a written reason — most commonly ``night``, for want of a night map. A freeform
chat cannot take those exemptions, and the reason is structural rather than
cautious: on a broadcast surface the platform chooses the subject, so a surface that
never discusses sleep can honestly exempt the night class. **Here Matthew chooses the
subject.** He can ask the nutrition coach about his HRV, and #2343 is precisely that
case — a card whose declared fact block queried macrofactor only, citing a single
night's real recovery and HRV as today's. The values existed; the DAY was wrong.

So the arming is:

  numbers    — the ADR-104 floor, allow-list derived from facts + memory + thread.
  dates      — #1242, a cited calendar date must appear in what the model was given.
  freshness  — #1691/#1897 via ``cycle_gate_params()``, spread LITERALLY at the call
               site so the registry's AST scan can see the class armed (folding it
               into a local dict is what made a freshness gate unverifiable in
               #2323 — behaviour unchanged, declaration no longer checkable).
  behavioral — #1699. Load-bearing right now: with MacroFactor quiet 45 days (#2326)
               a nutrition coach asked "how'd I do yesterday" has no food log at all,
               and this is the class that stops "you hit your protein" being said
               into that silence. ARMING IT TAKES A READ, and until #2564 that read
               did not happen: the class needs `available_logs`, the gate returns []
               without one, and the live chat call site passed none — declared as
               coverage, dark in production. `chat_available_logs` below is the read.
  night      — #1968/#2343, the day-correspondence class. The one that matters most
               here and the one a chat can least afford to skip.
  team       — #2496, composed on top rather than passed as a kwarg: an invented
               inter-coach meeting ("we talked about you Tuesday") contains no
               number and no calendar date, so every class above passes it.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from common.pacific_time import pacific_today  # #2811: THE Pacific day helper — DATE# keys are Pacific days

logger = logging.getLogger(__name__)

USER_ID = os.environ.get("USER_ID", "matthew")


def _gen_date(generation_date_iso: Optional[str]) -> str:
    """The ONE generation day this surface adjudicates against.

    Both the grounder and the availability map below default the same way, and they
    have to: a map built for UTC-today against a gate adjudicating Pacific-today would
    grade a claim against the wrong day's logs, which is #2343's failure shape wearing
    #1699's clothes. One definition, two callers.
    """
    return generation_date_iso or pacific_today()


def chat_available_logs(table, generation_date_iso: Optional[str] = None):
    """#2564 — the #1699 availability map for the CHAT surface.

    `build_grounder` has always ARMED the behavioral class, and the registry has always
    declared it armed with no exemption. But `ungrounded_behavioral_findings` returns []
    the moment `available_logs` is None, and the live chat call site never passed one:
    the class read as coverage and could not fire. This is the read that makes it real.

    The derivation is `ai.behavior_logs.available_logs_from_presence` — the SAME helper
    `coach_history_summarizer` uses for the stance and compression gates, deliberately
    not a second walker over the same record. What is chat-specific is only WHERE the
    signal comes from: one GetItem of the platform-wide engagement_state STATE#current
    record, read through `singleton_visible` because that singleton is exactly the kind
    a restart tombstones in place (#1969) and a wiped cycle's map is worse than none.

    Fail-soft to None — the summarizer's guarded posture, kept verbatim: no signal, an
    unreadable table, or a missing module leaves the class DARK for that turn. None is
    the honest value there. An empty set would be a lie in the other direction: it means
    "nothing was logged", and every true same-day claim would flag as fabricated.
    """
    try:
        from ai.behavior_logs import available_logs_from_presence
        from experiment.phase_filter import singleton_visible

        resp = table.get_item(Key={"pk": f"USER#{USER_ID}#SOURCE#engagement_state", "sk": "STATE#current"}) or {}
        signal = resp.get("Item")
        if not signal or not singleton_visible(signal):
            return None
        return available_logs_from_presence(signal, _gen_date(generation_date_iso))
    except Exception as e:
        logger.warning("[coach_chat] presence signal unavailable — behavioral class dark for this turn: %s", e)
        return None


def build_facts_block(facts: dict) -> str:
    """The AUTHORITATIVE FACTS block, from the one renderer every surface uses.

    Reuses ``grounded_generation.authoritative_facts_block`` rather than forking a
    chat-specific wording: the #2113 rider it carries (facts WITHHELD when the record
    predates this cycle's genesis) is load-bearing, and a fork would silently drop it.
    """
    try:
        from ai.grounded_generation import authoritative_facts_block

        block = authoritative_facts_block(facts or {})
    except Exception as e:  # pragma: no cover — a bundle/import edge, never a normal path
        logger.warning("[coach_chat] facts block unavailable: %s", e)
        block = ""
    if not block:
        # Silence is never the honest default: a coach with no facts must be TOLD it
        # has none, or it will answer from the persona's general knowledge and sound
        # exactly as confident as one that checked.
        return "AUTHORITATIVE FACTS: none available for this cycle. You have no numbers to cite. Say so if asked for one."
    return block


def build_grounder(
    facts: dict,
    *,
    generation_date_iso: Optional[str] = None,
    available_logs=None,
    extra_sources=(),
) -> Callable[[str], list]:
    """Return ``grounder(text) -> findings`` with all five gate classes armed.

    ``run_turn`` takes this closure rather than reaching for the gate itself, which
    keeps the turn engine pure AND puts the arming here, where the wiring registry's
    AST scan can see which classes this surface declares.

    ``extra_sources`` is the rest of what the model was shown — the memory block and
    the thread text. Numbers and dates appearing there are part of the model's
    legitimate vocabulary (quoting the memory, or Matthew's own words back to him, is
    not fabrication). The FACTS remain the only source of *vitals adjudication*: the
    night map is built from ``facts`` alone, so a remembered figure quoted against the
    wrong night is still caught by the night class even though the number itself is
    allowed.
    """
    from ai.grounded_generation import allowed_dates, allowed_numbers, grounding_findings
    from ai.grounding_gate_params import cycle_gate_params
    from ai.night_scope import nightly_vitals_from_facts

    gen_date = _gen_date(generation_date_iso)
    allowed = allowed_numbers(facts or {}, *extra_sources)
    dates = allowed_dates(facts or {}, *extra_sources)
    vitals = nightly_vitals_from_facts(facts)

    def grounder(text: str) -> list:
        # `**cycle_gate_params(...)` is spread LITERALLY here on purpose. #2323 folded
        # an equivalent call into a local dict and the freshness class became
        # invisible to the registry — behaviour unchanged, declaration no longer
        # checkable, which is the same defect shape as a guard that guards nothing.
        return grounding_findings(
            text,
            facts=facts,
            allowed=allowed,
            allowed_dates=dates,
            available_logs=available_logs,
            nightly_vitals=vitals,
            **cycle_gate_params(gen_date),
        )

    # #2496 — the team-texture class, composed HERE rather than at each transport.
    # "We talked about you Tuesday" carries no number and no calendar date, so it is
    # invisible to all five classes above; and per-transport wiring is precisely how
    # #1967 found 4 of 15 surfaces arming a class they all believed they had. The
    # check adjudicates against ``extra_sources`` because that is literally what the
    # model was shown. Fail-soft to the five-class grounder: a missing sibling module
    # must not disarm the gate that does exist.
    try:
        from coach.coach_team_texture import with_team_meeting_gate

        return with_team_meeting_gate(grounder, *extra_sources)
    except Exception as e:  # pragma: no cover — bundle edge
        logger.warning("[coach_chat] team-texture gate unavailable: %s", e)
        return grounder
