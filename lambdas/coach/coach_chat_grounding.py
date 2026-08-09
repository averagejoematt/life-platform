"""coach_chat_grounding.py — the fact block and the gate arming for the coach chat
(#2364, epic #2363).

Kept separate from ``coach_chat`` so that module can stay a pure, AWS-free turn
engine. This is the half that knows what is TRUE today, and it is deliberately thin:
almost everything here is a call into machinery that already exists, because a chat
surface inventing its own notion of "the facts" is exactly how two doors end up
telling a reader two truths.

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

  numbers    — the ADR-104 floor.
  dates      — #1242, a cited calendar date must be one the facts contain.
  freshness  — #1691/#1897 via ``cycle_gate_params()``, spread LITERALLY at the call
               site so the registry's AST scan can see the class armed (folding it
               into a local dict is what made a freshness gate unverifiable in
               #2323 — behaviour unchanged, declaration no longer checkable).
  behavioral — #1699. Load-bearing right now: with MacroFactor quiet 45 days (#2326)
               a nutrition coach asked "how'd I do yesterday" has no food log at all,
               and this is the class that stops "you hit your protein" being said
               into that silence.
  night      — #1968/#2343, the day-correspondence class. The one that matters most
               here and the one a chat can least afford to skip.

THE ALLOW-LIST IS DERIVED, NOT HAND-LISTED. ``allowed_numbers`` walks the fact dict
rather than naming fields, so a fact added upstream is grounded automatically instead
of becoming a fabrication finding on its first appearance — the guard-the-SET
discipline, applied to the numbers gate itself.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Numbers that are never "fabricated" wherever they appear — small integers a coach
# uses conversationally ("one more day", "the 3 sets you did"). The gate has its own
# benign handling; this is the chat's narrow addition for ordinals in speech.
_BENIGN = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 10, 12, 24, 100})


def allowed_numbers(facts: dict) -> set:
    """Every numeric value the facts contain, flattened — the numbers gate's input.

    DERIVED from the fact dict, never hand-listed. A hand list rots the moment an
    upstream fact is added: the new field's value would read as a fabrication on its
    first appearance, and the reflex fix (widen the list) is how allow-lists quietly
    stop meaning anything. Walks nested dicts and lists because canonical_facts is
    not flat.
    """
    out: set = set(_BENIGN)

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        elif isinstance(node, bool):
            return  # True/False are not numbers a coach cites
        elif isinstance(node, (int, float)):
            out.add(node)

    walk(facts or {})
    return out


def _is_iso_date(v) -> bool:
    """A real YYYY-MM-DD, not merely a 10-char string with well-placed dashes."""
    if not (isinstance(v, str) and len(v) == 10):
        return False
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def allowed_dates(facts: dict) -> set:
    """Calendar dates the facts legitimately contain (#1242).

    An EMPTY set is meaningful and is not the same as ``None``: it means "no date is
    legitimate", which is the correct posture when the facts carry none. Passing
    ``None`` would switch the date class off entirely.
    """
    out: set = set()

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        elif _is_iso_date(node):
            out.add(node)

    walk(facts or {})
    return out


def build_facts_block(facts: dict, memory_block: str = "") -> str:
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


def build_grounder(facts: dict, *, generation_date_iso: Optional[str] = None, available_logs=None) -> Callable[[str], list]:
    """Return ``grounder(text) -> findings`` with all five gate classes armed.

    ``run_turn`` takes this closure rather than reaching for the gate itself, which
    keeps the turn engine pure AND puts the arming here, where the wiring registry's
    AST scan can see which classes this surface declares.
    """
    from ai.grounded_generation import grounding_findings
    from ai.grounding_gate_params import cycle_gate_params
    from ai.night_scope import nightly_vitals_from_facts

    gen_date = generation_date_iso or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    allowed = allowed_numbers(facts)
    dates = allowed_dates(facts)
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

    return grounder
