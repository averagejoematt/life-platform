"""coach_chat.py — the conversational turn engine (#2364, epic #2363).

Every coach surface before this one is either a BROADCAST (the daily cards, the
narratives, the ensemble digest) or a QUEUE (``coach_checkin`` — the coach asks,
Matthew answers, via MCP). Nothing let Matthew *initiate*, in his own words, and get
a reply in that coach's voice. This module is that missing turn.

WHAT THIS MODULE IS NOT. It contains no Telegram vocabulary, no boto3 client
construction, and no network call it makes itself. It is the brain; the transport
(``lambdas/web/telegram_webhook_lambda.py``) is a separate, thin thing. Everything
here is a pure function of its arguments so the interesting behaviour — grounding
holds, budget refusals, memory assembly — is unit-testable without AWS. The one
exception is ``bedrock_client.invoke``, which is INJECTED (``caller=``) exactly the
way ``coach_checkin.generate_questions`` injects it.

THE PERSONALITY IS NOT BUILT HERE. It already exists and is deep: the voice specs in
``config/coaches/*.json`` (preferred and FORBIDDEN opening patterns, sentence rhythm,
uncertainty style, analogy domain, humor, declared relationships to the other
coaches), the rapport arc in ``RELATIONSHIP#state``, the memory in the ``COACH#``
partitions. This module's job is to ASSEMBLE those into a chat turn, never to invent
character. If a coach reads flat in a text, the fix is in the voice spec or the
memory, not in a prompt tweak here — the same rule ``coach_dossier`` states for the
public dossier ("if it reads badly verbatim, the fix is better memory").

THE HONESTY CONTRACT (the reason this file is careful). A freeform chat is the
highest-risk AI surface on the platform. A wrong number delivered in a trusted voice
on Matthew's phone is worse than the same number on a web page, because he will act
on it and there is no cockpit next to it to contradict it. #2343 — a coach citing
2026-08-07's real HRV as today's — is the exact failure to design against, and note
its shape: the VALUES were real and present in the fact set. An existence-only
grounding check cannot catch it. So:

  * every reply crosses ``grounding_findings`` with the ``night`` class armed
    (day-correspondence), not just ``numbers`` (existence);
  * a reply with unresolved findings is regenerated ONCE and then HELD — never sent.
    This is ADR-108's regenerate-or-hold, deliberately NOT the keep-if-better shape
    that #2362's review found publishing known-ungrounded narratives (AIQ-2);
  * a held reply still answers, with an honest "let me check that" — silence would
    read as the platform being broken, and an unanswered text is its own small lie.

BUDGET. Chat is unbounded spend against an $85/month ceiling that sits at tier >=1 by
default (ADR-063/133). This module refuses BEFORE inference at tier >= _PAUSE_TIER
and above a daily turn cap, and says so plainly. A coach that admits it is paused is
honest; one that quietly eats the daily brief's budget is not.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Storage: the SAME partition family the dossier and narratives already read ──
# Texting a coach must make that coach know Matthew better. A side-channel thread
# would give him the FEELING of being known while the memory stayed empty, which is
# the kind of gap this platform exists to refuse.
CHAT_SK_PREFIX = "CHAT#"
PROVENANCE = "telegram"

ROLE_MATTHEW = "matthew"
ROLE_COACH = "coach"

# How much thread the model sees. Long enough that the coach remembers what was said
# three messages ago (the thing that makes a chat feel like a person rather than a
# vending machine); short enough that a long evening doesn't linearly inflate cost.
MAX_THREAD_TURNS = 12
MAX_INBOUND_CHARS = 2000
MAX_REPLY_CHARS = 1200

# Budget posture. Tier 2 is "reader narratives paused" — a private chat is closer to
# the daily brief in priority than to a website narrative, so it survives tier 1 and
# stops at 2 rather than sharing the reader-narrative band.
_PAUSE_TIER = 2
DAILY_TURN_CAP = 40

_HELD_REPLY = (
    "Let me check that before I answer — I'd rather say nothing than give you a number I can't stand behind. Ask me again in a minute."
)
_PAUSED_REPLY = "I'm paused for the month — the AI budget guard is holding at tier {tier} and a private chat isn't worth pausing your daily brief over. The site and your brief still run."
_CAPPED_REPLY = "That's {cap} messages today, which is where I stop — not because you're bothering me, but because the budget cap is the reason the rest of the platform keeps running. Pick it up tomorrow."


def normalize_coach_id(coach_id: str) -> str:
    """``nutrition_coach`` and ``nutrition`` both mean the nutrition coach.

    Reused rather than reinvented: this is ``coach_checkin.normalize_coach_id``'s
    convention, and the two must not fork or a chat turn will write to a partition
    the check-in queue cannot see.
    """
    cid = (coach_id or "").strip().lower()
    return cid[: -len("_coach")] if cid.endswith("_coach") else cid


def chat_pk(coach_id: str) -> str:
    """The evaluator-convention partition — suffixed id, same as CHECKIN#/STANCE#."""
    return f"COACH#{normalize_coach_id(coach_id)}_coach"


def new_chat_sk(date_str: Optional[str] = None, uid: Optional[str] = None) -> str:
    d = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{CHAT_SK_PREFIX}{d}#{(uid or uuid.uuid4().hex)[:8]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Prompt assembly ───────────────────────────────────────────────────────────


def clip_inbound(text: str) -> str:
    """Bound what Matthew can send in one message.

    Not a hostile-input guard — it is his own phone. It bounds the token cost of a
    pasted wall of text, and it is applied BEFORE storage so the stored thread and
    the prompt agree about what was said.
    """
    t = (text or "").strip()
    return t[:MAX_INBOUND_CHARS]


def format_thread(thread: list, max_turns: int = MAX_THREAD_TURNS) -> list:
    """Stored turns -> Anthropic ``messages``, oldest-first, Matthew-first.

    Anthropic requires strictly alternating user/assistant turns starting with user.
    A stored thread can violate that — two Matthew messages in a row when he texts
    twice before the coach answers, which is exactly what a real person does. Rather
    than drop one (losing what he said) the consecutive same-role turns are MERGED,
    so nothing he wrote is silently discarded.
    """
    turns = [t for t in (thread or []) if (t or {}).get("text")][-max_turns:]
    messages: list = []
    for t in turns:
        role = "user" if t.get("role") == ROLE_MATTHEW else "assistant"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] = f"{messages[-1]['content']}\n\n{t['text']}"
            continue
        messages.append({"role": role, "content": t["text"]})
    # A leading assistant turn (the coach texted first — the outbound story) is not a
    # legal opener; drop it from the PROMPT only. It stays in storage and in the
    # reader's scrollback: this is a protocol requirement, not a memory edit.
    while messages and messages[0]["role"] == "assistant":
        messages.pop(0)
    return messages


def build_system_prompt(persona_block: str, memory_block: str, facts_block: str, coach_name: str) -> str:
    """The system message: WHO the coach is, WHAT they remember, WHAT is true today.

    Order is deliberate. Persona first because it is the largest and most stable
    block, which is what makes it worth caching (COST-OPT-2 wraps the system message
    as a cached content block, and cache hits require a stable prefix). Facts last
    because they change every day and are what the grounding gate will check against.
    """
    return "\n\n".join(
        p
        for p in [
            persona_block,
            f"You are texting Matthew directly. You ARE {coach_name} — first person, no third-person self-reference, "
            "no salutation or sign-off. This is a text message, not a report: short, one idea, the way a person who "
            "knows him would actually text. If a longer answer is genuinely warranted, earn it.",
            memory_block,
            facts_block,
            "HARD RULE: every number, date, and day-reference you state must come from the facts above. If the facts "
            "do not contain what he asked about, say you don't have it — do not estimate, do not reach for a typical "
            "value, and do not attach today to a reading from another day. Naming the day a reading belongs to is "
            "always correct; implying a reading is today's when it is not is the one unforgivable error.",
        ]
        if p
    )


def build_request(
    *,
    persona_block: str,
    memory_block: str,
    facts_block: str,
    coach_name: str,
    thread: list,
    inbound: str,
    model: str,
    max_tokens: int = 400,
) -> dict:
    """The Anthropic Messages body. Pure — builds a dict, calls nothing."""
    messages = format_thread(thread)
    messages.append({"role": "user", "content": clip_inbound(inbound)})
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": build_system_prompt(persona_block, memory_block, facts_block, coach_name),
        "messages": messages,
    }


def extract_text(response: dict) -> str:
    """Pull the text out of a Messages response, tolerating a missing/odd shape."""
    for block in (response or {}).get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return (block.get("text") or "").strip()
    return ""


def clip_reply(text: str) -> str:
    """Keep a reply text-message shaped, cutting on a sentence boundary.

    A hard character truncation would strand a half-sentence — and a half-sentence
    containing half a number is a NEW honesty defect invented by the formatter, after
    the grounding gate has already passed the text. So the cut lands on the last
    sentence terminator, or nowhere.
    """
    t = (text or "").strip()
    if len(t) <= MAX_REPLY_CHARS:
        return t
    cut = t[:MAX_REPLY_CHARS]
    m = list(re.finditer(r"[.!?](?:\s|$)", cut))
    return cut[: m[-1].end()].strip() if m else cut.rstrip()


# ── Budget posture ────────────────────────────────────────────────────────────


def budget_refusal(tier: Optional[int], turns_today: int, cap: int = DAILY_TURN_CAP) -> Optional[str]:
    """The honest refusal to send INSTEAD of inference, or None to proceed.

    Checked before the model is touched, so a refusal costs nothing. An unknown tier
    (None — the SSM read failed) proceeds: failing closed here would silently mute
    every coach on an unrelated SSM blip, and the budget has its own hard backstop in
    ``bedrock_client``/``budget_guard`` regardless. This is a soft gate in front of a
    hard one, not the only line of defence.
    """
    if tier is not None and tier >= _PAUSE_TIER:
        return _PAUSED_REPLY.format(tier=tier)
    if turns_today >= cap:
        return _CAPPED_REPLY.format(cap=cap)
    return None


# ── The turn ──────────────────────────────────────────────────────────────────


class TurnResult:
    """What happened, in a form the transport can act on and a test can assert.

    ``status`` is one of: ``sent`` (grounded first try), ``regenerated`` (grounded on
    the retry), ``held`` (ungrounded twice — the honest deferral went out instead),
    ``paused`` / ``capped`` (budget), ``error``. ``findings`` carries the grounding
    findings that caused a hold so the failure is inspectable rather than a mystery.
    """

    __slots__ = ("text", "status", "findings", "attempts")

    def __init__(self, text: str, status: str, findings: Optional[list] = None, attempts: int = 0):
        self.text = text
        self.status = status
        self.findings = findings or []
        self.attempts = attempts

    @property
    def grounded(self) -> bool:
        return self.status in ("sent", "regenerated")

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<TurnResult {self.status} attempts={self.attempts} findings={len(self.findings)}>"


def run_turn(
    *,
    coach_id: str,
    coach_name: str,
    persona_block: str,
    memory_block: str,
    facts_block: str,
    thread: list,
    inbound: str,
    model: str,
    caller: Callable[[dict], dict],
    grounder: Callable[[str], list],
    tier: Optional[int] = None,
    turns_today: int = 0,
    cap: int = DAILY_TURN_CAP,
) -> TurnResult:
    """One conversational turn: budget -> generate -> ground -> regenerate-or-hold.

    ``caller`` is ``bedrock_client.invoke`` (ADR-062's single chokepoint) and
    ``grounder`` is a closure over ``grounding_findings`` with this surface's gate
    classes already armed — injected so this function is testable with no AWS and so
    the ARMING is the transport's declared responsibility, visible to the
    ``tests/grounding_wiring.py`` registry rather than hidden in a default here.

    The retry is NOT keep-if-better. #2362's review (AIQ-2) measured the expert
    analyzer publishing narratives whose finding count merely *dropped* — a rewrite
    that goes 6 findings to 2 still ships two ungrounded claims. Here the retry must
    come back CLEAN or the reply is held.
    """
    refusal = budget_refusal(tier, turns_today, cap)
    if refusal:
        return TurnResult(refusal, "paused" if tier is not None and tier >= _PAUSE_TIER else "capped")

    request = build_request(
        persona_block=persona_block,
        memory_block=memory_block,
        facts_block=facts_block,
        coach_name=coach_name,
        thread=thread,
        inbound=inbound,
        model=model,
    )

    attempts = 0
    last_findings: list = []
    for attempt in range(2):
        attempts += 1
        try:
            text = clip_reply(extract_text(caller(request)))
        except Exception as e:
            logger.warning("[coach_chat] %s inference failed on attempt %d: %s", coach_id, attempts, e)
            return TurnResult(_HELD_REPLY, "error", last_findings, attempts)
        if not text:
            last_findings = [{"type": "empty_reply", "detail": "model returned no text"}]
            continue
        findings = grounder(text) or []
        if not findings:
            return TurnResult(text, "sent" if attempt == 0 else "regenerated", [], attempts)
        last_findings = findings
        logger.warning("[coach_chat] %s grounding findings on attempt %d: %s", coach_id, attempts, [f.get("type") for f in findings])
        # The retry is told what it got wrong. A blind re-roll is a coin flip; naming
        # the offending claim is what makes the second attempt better than the first.
        request = dict(
            request,
            messages=list(request["messages"])
            + [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": (
                        "That reply contains a claim I can't ground: "
                        + "; ".join(str(f.get("detail") or f.get("type")) for f in findings[:3])
                        + ". Rewrite it using only what's in the facts above. If the answer isn't there, say you don't have it."
                    ),
                },
            ],
        )

    return TurnResult(_HELD_REPLY, "held", last_findings, attempts)


def turn_records(coach_id: str, coach_name: str, inbound: str, result: TurnResult, cycle=None, date_str: Optional[str] = None) -> list:
    """The two DynamoDB items for one exchange — his message and the reply.

    Both are stored, including a HELD reply, because the deferral is part of the
    honest record: a later reader must be able to see that the coach declined to
    answer and why, not find a gap. ``findings`` rides on the coach item for exactly
    that reason.
    """
    pk = chat_pk(coach_id)
    d = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stamp = now_iso()
    base: dict = {
        "pk": pk,
        "coach_id": normalize_coach_id(coach_id),
        "coach_name": coach_name,
        "provenance": PROVENANCE,
        "created_at": stamp,
    }
    if cycle is not None:
        base["cycle"] = cycle
    items: list[dict] = [
        dict(base, sk=new_chat_sk(d), role=ROLE_MATTHEW, text=clip_inbound(inbound)),
        dict(base, sk=new_chat_sk(d), role=ROLE_COACH, text=result.text, status=result.status, attempts=result.attempts),
    ]
    if result.findings:
        items[1]["findings"] = [str(f.get("type") or "unknown") for f in result.findings]
    return items
