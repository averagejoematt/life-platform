"""telegram_reply_gate.py — the coach never claims a write it cannot make (#4170).

THE DEFECT. Telegram, 2026-09-25 19:10 PT. Matthew: "New standing constraint - no
current injuries or ailments - remember this". The coach: "Got it." Matthew: "approve
you to write this". The coach: "Noted." A read at 02:1xZ found the training memory
holding **0 records**. The Telegram worker is a conversational persona with NO tool
access — it cannot write memory, cannot enqueue a pending write (#4078), cannot run the
red team (#4076) — and its replies claimed the write had happened anyway. #4078's class
(a write acknowledged, never written) on a second surface; the reader believes the
constraint is stored and it is not (ADR-104: honest numbers everywhere, and an honest
"nothing was stored" is one of them).

THE RULING (owner, 2026-09-25, session AU — option (b) on the issue). The Telegram coach
does not claim a write and does not queue one either. Asked to remember, approve or
veto something, it says plainly that it can't save that on Telegram and that the request
belongs in the Claude chat, which has the tools. No pending-writes wiring; the persona
is never granted a direct write.

WHY A GATE AND NOT A PROMPT LINE. The same reason ``coach_style_gate`` exists: a prompt
rule shapes a habit, a deterministic gate guarantees the ceiling. "Got it." is the
model's cheapest possible reply to an instruction, and no system-prompt sentence will
make it zero. Deterministic computation before any model verdict (ADR-105), and no
second Bedrock call to "regenerate" — a re-roll can re-claim, the routing line cannot.

ORDERING. This runs AFTER the model and after the grounding gate, on exactly the text
the transport is about to send — the hazard gate and the grounder stay in front of the
model where they belong. It is the last deterministic check before ``_send_bubbles``.

THE TWO RULES, named so a reader can grep them:

  * ``WRITE_REQUEST_RE`` — the INBOUND is a remember / approve / veto request.
  * ``WRITE_CLAIM_RE``   — the OUTBOUND claims a write happened.

Both must hold for the gate to fire — a "got it" to "how did I sleep?" is not a false
claim, and a genuinely honest reply to "remember this" passes untouched. The hook
``wrote_this_turn`` exists so that IF a future path ever performs a real write on this
surface, it declares so and the acknowledgement stands; today nothing on the worker can
set it, which is the point.
"""

# gate-entrypoint: the false-acknowledgement gate — `enforce()` swaps a write-claiming reply
# for the honest routing line and the CALLER (telegram_worker_lambda) sends what comes back.
# Nothing here raises by design (a failed gate must never cost Matthew his reply), so the
# census's exit/raise scan cannot see it; the gate can still FAIL — proved in
# scripts/gate_census_proofs.py (GUARD_PROOFS).

from __future__ import annotations

import re

from coach.coach_chat import TurnResult

# The inbound rule: a request to store, approve or veto something. Word-bounded so
# "remembered how good that felt" (a reminiscence) does not trip it.
WRITE_REQUEST_RE = re.compile(
    r"\b(remember (this|that|it)|standing constraint|approve (you|this|it|that|the write)|"
    r"(save|note|store|log|write|record) (this|that|it)( down| for me)?|veto|make a note|add (this|that|it) to)\b",
    re.IGNORECASE,
)

# The outbound rule: a claim that the write happened. Bounded and short by design — the
# gate refuses a CLAIM, not a topic, so "I can't save that" (which contains "save") is
# not matched; only the past/committed forms are.
WRITE_CLAIM_RE = re.compile(
    r"\b(got it|noted|saved|stored|logged|recorded|approved|vetoed|on file|written down|locked in|"
    r"i(?:'ll| will) remember|i(?:'ve| have) (noted|saved|stored|logged|recorded|written)|"
    r"consider it (done|noted|saved)|added to (your|the) (memory|notes|constraints)|remembered)\b",
    re.IGNORECASE,
)

# The stored status of a turn whose reply was swapped for the routing line — its OWN
# value, never a flavour of "sent", so the thread shows what happened and so
# ``coach_voice`` (which speaks only grounded statuses) cannot read it as a reply.
STATUS_ROUTED = "routed_write"

# The honest line. Plain and coach-agnostic: what it must carry is (a) nothing was stored,
# (b) where the request belongs. No number, no date, so it can never mint a grounding finding.
ROUTING_LINE = (
    "I can't save that from here. Nothing is stored on Telegram, and I don't have a way to write it. "
    "Say it in the Claude chat, which has the tools, and it will be written there."
)


def is_write_request(inbound: str) -> bool:
    """Whether the message Matthew just sent asks the coach to remember, approve or veto."""
    return bool(WRITE_REQUEST_RE.search(inbound or ""))


def claims_write(outbound: str) -> bool:
    """Whether the reply text claims a write happened."""
    return bool(WRITE_CLAIM_RE.search(outbound or ""))


def enforce(inbound: str, result: TurnResult, *, wrote_this_turn: bool = False) -> TurnResult:
    """The gate. Returns ``result`` untouched unless the inbound is a write request AND the
    reply claims a write AND no write happened this turn — then the routing line, as a
    fresh ``TurnResult`` with ``STATUS_ROUTED`` and a finding naming the refused claim.

    The finding rides to storage with the turn (``coach_chat.turn_records``), so a later
    reader sees the coach was about to claim a write and was stopped, not a gap.
    """
    if wrote_this_turn or not result.grounded:
        return result
    if not is_write_request(inbound):
        return result
    if not claims_write(result.text):
        return result
    match = WRITE_CLAIM_RE.search(result.text or "")
    claim = match.group(0) if match else "write claim"
    finding = {
        "type": "write_claim",
        "detail": f"reply claimed a write ({claim!r}) on a surface with no write tools; routed to the Claude chat",
        "refused_text": result.text,
    }
    return TurnResult(ROUTING_LINE, STATUS_ROUTED, [finding], result.attempts, bubbles=[ROUTING_LINE])
