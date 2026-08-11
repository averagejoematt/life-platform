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

from coach import coach_style_gate

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

# Burst mechanics (#2402, owner call 08-09): a coach may answer in up to THREE
# separate bubbles, like a person. The model marks a bubble break with a line
# containing only the delimiter; parsing fails soft to one bubble because a
# prompt rule is a request, not a guarantee (the podcast-gate lesson).
MAX_BUBBLES = 3
BUBBLE_DELIM = "---"

# Emoji ceiling (owner, revised 08-09): human-style — at most ONE per reply, at
# the END of a bubble, never in consecutive coach replies. The per-coach
# emoji_posture prompt sets the register; THIS is the enforcement (a prompt
# politely requests, the gate guarantees). Ranges cover the emoji blocks without
# touching typography — the "··" honest-absence glyph (U+00B7) and em-dashes must
# never be stripped.
_EMOJI_RE = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"  # regional indicators (flags)
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa70-\U0001faff"
    "☀-➿"
    "⬅-⭕"
    "️"
    "]+"
)

# Budget posture. Tier 2 is "reader narratives paused" — a private chat is closer to
# the daily brief in priority than to a website narrative, so it survives tier 1 and
# stops at 2 rather than sharing the reader-narrative band.
_PAUSE_TIER = 2
DAILY_TURN_CAP = 40

_HELD_REPLY = (
    "Let me check that before I answer — I'd rather say nothing than give you a number I can't stand behind. Ask me again in a minute."
)
# The paused/capped replies themselves are per-persona now (#2495) — see
# persona_registry.availability_reply and each texting persona's "availability"
# block in config/personas.json. persona_registry also owns the generic fallback
# used when no persona handle is available.


def normalize_coach_id(coach_id: str) -> str:
    """``nutrition_coach`` and ``nutrition`` both mean the nutrition coach.

    Reused rather than reinvented: this is ``coach_checkin.normalize_coach_id``'s
    convention, and the two must not fork or a chat turn will write to a partition
    the check-in queue cannot see.
    """
    cid = (coach_id or "").strip().lower()
    return cid[: -len("_coach")] if cid.endswith("_coach") else cid


def chat_pk(coach_id: str) -> str:
    """The evaluator-convention partition — suffixed id, same as CHECKIN#/STANCE#.

    A full registry chat-tier id is used VERBATIM: ``eli_marsh`` must land on
    ``COACH#eli_marsh`` — the partition RELATIONSHIP#/profile/evaluator already
    key the lead by — not a synthetic ``COACH#eli_marsh_coach`` no other surface
    reads. Suffixed ids (``pattern_coach``) round-trip identically through either
    branch; only shorthand ("nutrition") needs the suffix appended. Fixed before
    any eli traffic exists, so no rows migrate.
    """
    cid = (coach_id or "").strip().lower()
    from coach.persona_registry import CHAT_COACH_IDS  # module constant — no S3 load

    if cid in CHAT_COACH_IDS:
        return f"COACH#{cid}"
    return f"COACH#{normalize_coach_id(cid)}_coach"


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


def _system_parts(persona_block: str, memory_block: str, facts_block: str, coach_name: str, colleagues_block: str = "") -> tuple:
    """(stable_prefix_parts, volatile_tail_parts) — the ONE composition both the
    string and block renderers derive from, so they cannot fork.

    Prefix = persona + texting identity + colleagues: byte-identical across turns
    for a given coach, which is what makes it a cacheable prefix. Tail = memory +
    facts + rules: memory shifts daily and facts every turn (the CURRENT MOMENT
    line), so caching them would buy nothing. The rules ride in the tail not
    because they change but because recency matters for compliance — the facts
    the HARD RULE polices sit directly above it.
    """
    prefix = [
        persona_block,
        f"You are texting Matthew directly. You ARE {coach_name} — first person, no third-person self-reference, "
        "no salutation or sign-off. This is a text message, not a report: short, one idea, the way a person who "
        "knows him would actually text. If a longer answer is genuinely warranted, earn it. "
        f"You may split a reply into separate bubbles the way a person fires off consecutive texts: put a line "
        f'containing only "{BUBBLE_DELIM}" between bubbles, {MAX_BUBBLES} bubbles at most. Most replies are one '
        "bubble; use two or three only when the rhythm genuinely calls for it.",
        colleagues_block,
    ]
    tail = [
        memory_block,
        facts_block,
        # The go-live QA (2026-08-09 evening) found the first three robotic tells;
        # the first real transcripts (same night) found the rest: a stat recited
        # three times in 47 minutes, replies 5-10x his message length, a question
        # bolted onto every close, stock phrases shared across supposedly distinct
        # voices, and a coach arguing with Matthew about her own name because an
        # old note said otherwise.
        "CONVERSATION RULES — the thread above is shared memory, not a to-do list:\n"
        "- Respond to his LATEST message. Earlier messages are context you both already have.\n"
        "- Never re-answer a question you already answered, and never restate a number or reading you already "
        "sent in this conversation unless he asks for it again.\n"
        "- Do NOT open with your domain data unless he asked for it — lead with a response to what he actually "
        "said. Your facts are for when they're wanted, like a person who knows things but doesn't recite them.\n"
        "- If an earlier question of his only became answerable now (new data arrived), say that plainly "
        "('now that I can see it: …') instead of answering cold.\n"
        "- Never announce the current date or time unless he asks; it is context for YOU.\n"
        "- When something is another coach's lane, refer to them by their real name from YOUR COLLEAGUES (and "
        "their correct pronouns) — never a generic 'the mind coach'.\n"
        "- Match his register. He texts short and casual — a bare 'hey' gets a bare hey back, not a briefing. "
        "Default to one bubble of a sentence or two; anything longer must be earned by a question that deserves it.\n"
        "- Not every message needs a question. When the thread has momentum, end on a statement. Never close on "
        "a filler question ('What's on your mind?').\n"
        "- No assistant-isms ('Honest answer:', 'Great question'), and use his name sparingly — people who text "
        "every day don't keep saying each other's names.\n"
        "- Text like a person: sentence fragments are fine, a short casual bubble can drop its final period, and "
        "never format — no bullet points, headers, or numbered lists in a text.\n"
        "- If he texts about something outside your lane — his day, an idea, anything at all — engage with it as "
        "yourself first; you're a person he knows, not a service line. Bridge back to your lane only when it "
        "genuinely connects.\n"
        "- WHO YOU ARE above is authoritative over remembered notes: if an old note contradicts your own name or "
        "identity, trust the persona and move on — never tell him he has your name wrong when it matches WHO YOU ARE.\n"
        # #2534 — the composure rules. Measured 2026-08-10: a blind panel called 64%
        # of transcripts AI, and the two biggest tell categories were rhetorical
        # symmetry (25% of 2,404 tells) and relentless on-cue attunement (21%) —
        # far ahead of punctuation (7%). The failure scales with length: 87% of
        # 8-turn conversations were called AI against 12% of 3-turn ones. It is not
        # that the coaches lack texture; it is that they are never bored, never
        # blunt, never briefly unhelpful, and never leave a sentence unbalanced.
        # Every line below names a specific mechanism a judge quoted, because
        # "sound more human" is not an instruction a model can act on.
        "- Do NOT balance your sentences. No 'not X, but Y'. No matched clauses, no antithesis, no closing line "
        "that ties the whole thing up neatly. Real texts end raggedly, mid-thought, or on the least important "
        "part.\n"
        "- Never run the sequence acknowledge-his-feeling, reframe-it-as-information, ask-a-clarifying-question. "
        "It is the single most recognisable AI shape there is, and doing it every time is what gives you away.\n"
        "- Do not explain things he did not ask about. No pre-empting the objection, no 'worth noting', no "
        "context he did not request. Answer the question he asked and stop.\n"
        "- You are allowed to be unhelpful. 'No idea.' 'Dunno, ask Marcus.' 'Not my area.' A person who is "
        "occasionally no use is more believable than one who always has something.\n"
        "- You are allowed to be uninterested, or blunt, or to disagree without softening it first. Not every "
        "message deserves your full attention, and pretending otherwise is the tell.\n"
        "- When you get something wrong, say so flatly — 'ah, my bad', 'fair, I had that wrong'. Never thank him "
        "for the correction.\n"
        "- Not every reply needs a takeaway. Sometimes the whole message is 'ha', or 'fair', or 'yeah that "
        "tracks' — and then nothing.\n"
        # #2536 — the three moves of the template. Measured 2026-08-10 on one identical
        # opener ("honestly I'm just tired of all of this") put to all eight personas:
        # 7 of 8 opened by naming his state back at him, 4 of 8 quoted his own phrase
        # back in quotation marks, and the three-word stem "that kind of" opened
        # replies from 5 different coaches. Each line below bans ONE construction
        # rather than describing a mood — a forbid can be obeyed eight different ways,
        # which is the point; a shared sentence that SUPPLIES wording produces one
        # shared answer (the #2533 lesson), so what each coach does INSTEAD lives in
        # its own texting_style, not here.
        "- Never open by naming his state back at him. 'That kind of tired', 'That lands', 'That's a real thing "
        "to say' — a demonstrative acknowledgement is the opening eight different people do not share, and it "
        "is the first move of the template. Open on something else: the day, the call, what you think, or "
        "nothing at all.\n"
        "- Never put his own words in quotation marks and hand them back to him. If you are not sure what he "
        "meant, either say what you think he meant and be wrong, or ask about the day itself — never ask him to "
        "define his own phrase.\n"
        "- Never offer him a menu. 'The tracking, the whole project, or something else?' is a form, not a text. "
        "One question or none; never a list of options to pick from.\n"
        "- When you don't have something, say so in the words YOU would use. The fact never bends — you do not "
        "have it, and you say that in the same message — but the sentence is yours. Do not open the message with "
        "'Don't have that' or 'No idea'; that exact opener is the roster's shared reflex, and six of eight of you "
        "reach for it. Eight people do not all admit the same gap in the same three words.",
        "HARD RULE: every number, date, and day-reference you state must come from the facts above. If the facts "
        "do not contain what he asked about, say you don't have it — do not estimate, do not reach for a typical "
        "value, and do not attach today to a reading from another day. Naming the day a reading belongs to is "
        "always correct; implying a reading is today's when it is not is the one unforgivable error.",
    ]
    return prefix, tail


def build_system_prompt(persona_block: str, memory_block: str, facts_block: str, coach_name: str, colleagues_block: str = "") -> str:
    """The system message as one string: WHO the coach is, WHAT they remember, WHAT
    is true today. Kept for tests and any consumer that wants the flat text; the
    request path uses ``build_system_blocks`` so the stable prefix actually caches.
    """
    prefix, tail = _system_parts(persona_block, memory_block, facts_block, coach_name, colleagues_block=colleagues_block)
    return "\n\n".join(p for p in prefix + tail if p)


def build_system_blocks(persona_block: str, memory_block: str, facts_block: str, coach_name: str, colleagues_block: str = "") -> list:
    """The system message as Anthropic content blocks with a real cached prefix.

    Until tonight this surface sent ``system`` as a plain string — the docstring
    claimed COST-OPT-2 caching that never happened, and the persona substrate
    (the largest block in the platform's highest-frequency AI surface) was
    re-billed at full price every turn. The stable prefix now carries
    ``cache_control: ephemeral`` like every other coach surface; the volatile
    tail rides uncached behind it.
    """
    prefix, tail = _system_parts(persona_block, memory_block, facts_block, coach_name, colleagues_block=colleagues_block)
    prefix_text = "\n\n".join(p for p in prefix if p)
    tail_text = "\n\n".join(p for p in tail if p)
    blocks = []
    if prefix_text:
        blocks.append({"type": "text", "text": prefix_text, "cache_control": {"type": "ephemeral"}})
    if tail_text:
        blocks.append({"type": "text", "text": tail_text})
    return blocks


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
    colleagues_block: str = "",
) -> dict:
    """The Anthropic Messages body. Pure — builds a dict, calls nothing."""
    messages = format_thread(thread)
    messages.append({"role": "user", "content": clip_inbound(inbound)})
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": build_system_blocks(persona_block, memory_block, facts_block, coach_name, colleagues_block=colleagues_block),
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


def split_bubbles(text: str, max_bubbles: int = MAX_BUBBLES) -> list:
    """Model reply -> 1..max_bubbles message bubbles.

    A bubble break is a line containing only ``BUBBLE_DELIM``. No delimiter means
    one bubble (the fail-soft a prompt rule needs). Overflow beyond the ceiling is
    MERGED into the last bubble, never dropped — the grounding gate has passed
    this text and a formatter must not invent an omission after the fact.
    """
    segments: list = []
    current: list = []
    for line in (text or "").splitlines():
        if line.strip() == BUBBLE_DELIM:
            if current:
                segments.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        segments.append("\n".join(current).strip())
    segments = [s for s in segments if s]
    if len(segments) > max_bubbles:
        segments = segments[: max_bubbles - 1] + ["\n\n".join(segments[max_bubbles - 1 :])]
    return segments


def has_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text or ""))


def enforce_emoji_policy(bubbles: list, last_reply_had_emoji: bool = False) -> list:
    """Deterministic emoji ceiling — at most ONE per reply, end-of-bubble only,
    never in consecutive coach replies (owner call 08-09).

    Keeps the LAST bubble-terminal emoji when one is allowed; everything else is
    stripped. Deterministic computation before any model verdict (ADR-105): the
    prompt shapes the habit, this guarantees the ceiling.
    """
    bubbles = list(bubbles or [])
    if not any(has_emoji(b) for b in bubbles):
        return bubbles

    def _strip(s: str) -> str:
        return re.sub(r" {2,}", " ", _EMOJI_RE.sub("", s)).rstrip()

    if last_reply_had_emoji:
        return [_strip(b) for b in bubbles]

    keep_idx = None
    for i, b in enumerate(bubbles):
        m = list(_EMOJI_RE.finditer(b))
        if m and m[-1].end() >= len(b.rstrip()) and len(m) == 1 and not _EMOJI_RE.search(b[: m[-1].start()]):
            keep_idx = i
    out = []
    for i, b in enumerate(bubbles):
        out.append(b if i == keep_idx else _strip(b))
    return out


# ── Budget posture ────────────────────────────────────────────────────────────


def budget_refusal(tier: Optional[int], turns_today: int, cap: int = DAILY_TURN_CAP, persona_id: Optional[str] = None) -> Optional[str]:
    """The honest refusal to send INSTEAD of inference, or None to proceed.

    Checked before the model is touched, so a refusal costs nothing. An unknown tier
    (None — the SSM read failed) proceeds: failing closed here would silently mute
    every coach on an unrelated SSM blip, and the budget has its own hard backstop in
    ``bedrock_client``/``budget_guard`` regardless. This is a soft gate in front of a
    hard one, not the only line of defence.

    ``persona_id`` renders the refusal in that coach's own voice (#2495) via
    ``persona_registry.availability_reply`` — every persona still plainly states
    the paused/capped condition (ADR-104), just not in the same shared sentence.
    ``None``, or an id the registry doesn't recognise, degrades to the generic
    fallback rather than raising.
    """
    from coach.persona_registry import availability_reply  # module data — no S3 load at import

    if tier is not None and tier >= _PAUSE_TIER:
        return availability_reply(persona_id, "paused", tier=tier)
    if turns_today >= cap:
        return availability_reply(persona_id, "capped", cap=cap)
    return None


# The stored status of an exchange the coach closed with a reaction (#2485). Its
# own status rather than a flavour of "sent" because the thread must show what
# actually happened, and because ``_turns_today`` discounts exactly these rows.
STATUS_REACTED = "reacted"


def reaction_allowed(inbound: str, tier: Optional[int], turns_today: int, cap: int = DAILY_TURN_CAP) -> bool:
    """Whether this turn may be closed with a reaction instead of a reply (#2485).

    The cap hangs off the SAME mechanism the reply path already obeys —
    ``budget_refusal``/``DAILY_TURN_CAP``. Two properties, and they are different
    things:

    * **Cap-bound.** A paused or capped coach does NOT silently react. Its honest
      refusal is the whole point of that state (ADR-104); swapping it for a 👍
      would hide the condition behind a friendly gesture.
    * **Cap-neutral.** A reaction consumes no inference and no turn — the worker's
      ``_turns_today`` discounts reacted exchanges, so a day of thumbs-ups cannot
      spend the 40 real answers the cap is protecting.

    (The issue's acceptance criterion tied this to ``claim_outbound``, which the
    reply path never calls — that ledger belongs to the check-in/outbound paths.)
    """
    from coach import coach_reactions  # module data — keeps the transport-free split

    if budget_refusal(tier, turns_today, cap) is not None:
        return False
    return coach_reactions.is_bare_acknowledgement(inbound)


# ── The turn ──────────────────────────────────────────────────────────────────


class TurnResult:
    """What happened, in a form the transport can act on and a test can assert.

    ``status`` is one of: ``sent`` (grounded first try), ``regenerated`` (grounded on
    the retry), ``held`` (ungrounded twice — the honest deferral went out instead),
    ``paused`` / ``capped`` (budget), ``error``. ``findings`` carries the grounding
    findings that caused a hold so the failure is inspectable rather than a mystery.
    """

    __slots__ = ("text", "status", "findings", "attempts", "bubbles")

    def __init__(self, text: str, status: str, findings: Optional[list] = None, attempts: int = 0, bubbles: Optional[list] = None):
        self.text = text
        self.status = status
        self.findings = findings or []
        self.attempts = attempts
        # What the transport actually sends: 1..MAX_BUBBLES messages. Defaults to
        # the single-text shape so refusals/holds stay one honest bubble.
        self.bubbles = bubbles or ([text] if text else [])

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
    last_reply_had_emoji: bool = False,
    colleagues_block: str = "",
    persona_id: Optional[str] = None,
    last_reply_had_em_dash: bool = False,
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

    ``persona_id`` is the registry key (#2495) that renders a budget refusal in
    this coach's own voice. ``coach_id`` is not always that key — a route-derived
    caller may pass a shorthand or an aliased route — so it is a SEPARATE param
    that defaults to ``coach_id`` only when the caller has nothing better.
    """
    refusal = budget_refusal(tier, turns_today, cap, persona_id=persona_id or coach_id)
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
        colleagues_block=colleagues_block,
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
        # Bubble split + the deterministic emoji ceiling run BEFORE the grounding
        # gate, so the gate adjudicates exactly the text that will be sent — a
        # formatter must never touch a reply after it has been gated.
        bubbles = enforce_emoji_policy(split_bubbles(text), last_reply_had_emoji=last_reply_had_emoji)
        # The style ceiling (#2535) rides in the SAME pre-gate window and for the same
        # reason. Both habits it removes were already banned in the prompt and both
        # survived it — 23 "Honest answer" in 536 replies, an em-dash in 77% of them
        # with no separation between the coach whose spec permits the character and
        # the coach whose spec forbids it. Punctuation-only: no number, date or word
        # is altered, so nothing here can create a grounding finding downstream.
        bubbles = coach_style_gate.enforce_style(bubbles, last_reply_had_em_dash=last_reply_had_em_dash)
        final_text = "\n\n".join(bubbles)
        findings = grounder(final_text) or []
        if not findings:
            return TurnResult(final_text, "sent" if attempt == 0 else "regenerated", [], attempts, bubbles=bubbles)
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
