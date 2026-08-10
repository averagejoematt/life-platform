"""coach_voice.py — voice notes: a reply spoken in the persona's own voice (#2494).

Real texting threads occasionally carry a voice note. Every decision about
whether one is appropriate — and the multipart encoding Telegram needs to carry
audio at all — lives here, deliberately away from the worker: the worker owns the
``sendVoice`` call, this owns the judgement, and a test can therefore pin the
behaviour without a Telegram double or a real TTS call.

Five gates, in the order a defect would actually appear. Every one of them can
only ever REMOVE a voice note; the typed reply is what happens when any of them
says no, so a coach can never fall silent because of this file.

1. **Grounded only.** Synthesis runs on the text that already passed the grounding
   gate (``sent``/``regenerated``). A held, paused or capped turn is never spoken —
   the honest deferral is a thing to read, not a thing to hear a friend say.
2. **Budget.** Delegated to ``coach_chat.budget_refusal`` rather than a second
   tier literal, so voice notes pause at exactly the tier chat pauses. TTS is not
   Bedrock spend, but it is spend, and the acceptance is explicit: a tier that
   silences the coach's words silences the coach's voice.
3. **Content class, deterministic.** One short bubble, no figures. A reply with
   three numbers in it is a table read aloud — unusable on a phone and impossible
   to scroll back to. Data stays text.
4. **The persona's own posture.** ``texting_style.voice_note_posture`` in
   ``config/coaches/<coach>.json``, read the same way ``emoji_posture`` is. **No
   posture configured means no voice notes** — inventing a register for a coach is
   the ADR-104 error, the same class as inventing a number for a day. This is why
   the feature ships dark: arming a coach is a deliberate per-coach config edit by
   the owner, not a default this module gets to choose.
5. **The persona's own voice.** ``persona_registry.tts_voice`` — the registry
   field the podcasts already speak in, so a coach sounds the same on the phone as
   in the panelcast. No ``tts_voice`` ⇒ no voice note, never a stand-in voice.

Occasional-ness is the posture's own rate word sampled over a stable digest of the
reply text: deterministic (the same sentence always makes the same choice, so the
behaviour is pinnable and a defect is reproducible) but unpredictable across the
stream of real replies, which is what "occasionally" has to mean in practice.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Optional

logger = logging.getLogger("coach-voice")

# The uploaded part. MP3 because ``google_tts.synthesize`` returns MP3 frames and
# the Bot API accepts .MP3 for ``sendVoice`` — no transcode, no second codec path.
FILENAME = "voice.mp3"
AUDIO_CONTENT_TYPE = "audio/mpeg"

# Statuses whose text cleared the grounding gate. Anything else is a refusal, a
# hold, or an error, and none of those are spoken.
GROUNDED_STATUSES = frozenset({"sent", "regenerated"})

# A voice note is a sentence or two, not a monologue: past this the reply is
# something to read. Also keeps the multipart upload small enough that the
# worker's 15 s ``urlopen`` timeout is never the thing that eats a reply.
MAX_CHARS = 400

# Three or more figures is data. Two survives ("down 2 lbs since Tuesday" is a
# sentence; "170 g, 2,100 kcal, 38 %" is a table).
_MAX_FIGURES = 2
_FIGURE_RE = re.compile(r"\d")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")

# Structure that only reads on a screen — a spoken bullet list is noise.
_STRUCTURE_RE = re.compile(r"(^\s*[-*•\d]+[.)]?\s+)|(\n)", re.MULTILINE)

_NEVER_RE = re.compile(r"\bnever\b", re.IGNORECASE)
_CLAUSE_RE = re.compile(r"[.!?]")

# Rate words a posture may open with → how often a QUALIFYING reply is spoken.
# Ordered most-specific-first; the first word found in the posture wins. A posture
# that names no rate at all gets the most conservative nonzero rate rather than a
# generous default — an under-spoken coach is a smaller error than a chatty one.
_RATES = (
    ("rarely", 0.08),
    ("rare", 0.08),
    ("occasionally", 0.25),
    ("occasional", 0.25),
    ("sometimes", 0.25),
    ("often", 0.5),
    ("frequently", 0.5),
)
_DEFAULT_RATE = 0.08


def posture_permits_voice(posture: Optional[str]) -> bool:
    """Whether this persona's ``voice_note_posture`` permits a voice note at all.

    Absent posture ⇒ False. A posture whose OPENING clause says "never" means it —
    the same reading ``coach_reactions.posture_permits_emoji`` applies, and for the
    same reason: the register is set in the first clause, and a later "never" is
    usually a qualifier on HOW ("never for numbers"), not on whether.
    """
    p = (posture or "").strip()
    return bool(p) and not _NEVER_RE.search(_CLAUSE_RE.split(p)[0])


def posture_rate(posture: Optional[str]) -> float:
    """How often a qualifying reply is spoken, from the posture's own rate word."""
    if not posture_permits_voice(posture):
        return 0.0
    low = (posture or "").lower()
    for word, rate in _RATES:
        if word in low:
            return rate
    return _DEFAULT_RATE


def is_data_heavy(text: str) -> bool:
    """Whether this reply is something to READ rather than hear.

    Deterministic and content-only — no model call. Numbers, structure, or length;
    any one of them disqualifies. Counting number TOKENS rather than digits so a
    single "2,100" reads as one figure, which is how a listener hears it.
    """
    body = text or ""
    if len(body) > MAX_CHARS or _STRUCTURE_RE.search(body):
        return True
    return len(_NUMBER_RE.findall(body)) > _MAX_FIGURES or len(_FIGURE_RE.findall(body)) > 8


def qualifies(bubbles, *, status: Optional[str], tier: Optional[int]) -> bool:
    """The transport-free decision: may THIS reply be spoken? (gates 1–3)."""
    from coach import coach_chat  # module data — keeps this file transport- and AWS-free

    if status not in GROUNDED_STATUSES:
        return False
    # turns_today=0 so only the TIER arm of the shared refusal can fire here: the
    # daily cap was already enforced upstream by the reply this note would speak,
    # and re-charging it would double-count one turn.
    if coach_chat.budget_refusal(tier, 0) is not None:
        return False
    sendable = [b for b in (bubbles or []) if (b or "").strip()]
    return len(sendable) == 1 and not is_data_heavy(sendable[0])


def sampled(text: str, rate: float) -> bool:
    """Whether this particular reply is the occasional one, deterministically.

    A stable digest of the text, not ``random`` — the same reply always makes the
    same choice, so a behaviour pin is possible and a report ("it spoke this one")
    is reproducible, while across a real stream of different replies the selection
    is as unpredictable as a coin.
    """
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    digest = hashlib.sha1((text or "").encode("utf-8")).hexdigest()  # noqa: S324 — sampling, not security
    return (int(digest[:8], 16) % 1000) < int(rate * 1000)


def multipart_body(fields: dict, files: dict) -> tuple:
    """``(bytes, content-type)`` for a multipart/form-data Bot API call.

    Hand-rolled because the platform ships no HTTP library (stdlib urllib only) and
    ``sendVoice`` cannot use a form body. ``files`` maps a field name to
    ``(filename, blob)``; every other value is a plain text part, stringified the
    way ``urlencode`` would have.
    """
    boundary = "----lp" + uuid.uuid4().hex
    sep = f"--{boundary}\r\n".encode()
    parts = []
    for key, value in fields.items():
        parts.append(sep + f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    for key, (filename, blob) in files.items():
        head = f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\nContent-Type: {AUDIO_CONTENT_TYPE}\r\n\r\n'
        parts.append(sep + head.encode() + bytes(blob) + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def voice_note(bubbles, *, persona_id: str, status: Optional[str], tier: Optional[int], s3=None, bucket=None, synth=None):
    """MP3 bytes for this reply, or ``None`` for "send it as text" (all five gates).

    ``None`` on every failure — an unreadable spec, a missing voice, a TTS error.
    The caller's fallback is the typed reply it was always going to send, so the
    worst case of this whole feature is the behaviour that shipped before it.
    """
    try:
        if not persona_id or not qualifies(bubbles, status=status, tier=tier):
            return None
        text = [b for b in (bubbles or []) if (b or "").strip()][0].strip()

        from coach.persona_core import load_voice_spec
        from coach.persona_registry import tts_voice

        style = (load_voice_spec(persona_id, s3_client=s3, bucket=bucket) or {}).get("texting_style") or {}
        if not sampled(text, posture_rate(style.get("voice_note_posture"))):
            return None
        voice_name = tts_voice(persona_id, s3, bucket)
        if not voice_name:
            # Posture says speak, registry says with WHAT voice — and it has none.
            # A stand-in voice would be a different person answering (ADR-104).
            logger.warning("[coach-voice] %s has a voice-note posture but no tts_voice — sending text", persona_id)
            return None
        if synth is None:
            from ai.google_tts import synthesize as synth  # lazy: builds a Secrets Manager client at import
        return synth(text, voice_name) or None
    except Exception as e:
        logger.warning("[coach-voice] synthesis skipped for %s (%s) — sending text", persona_id, e)
        return None
