"""Reaction emojis — when the human move is a reaction, not another bubble (#2485).

After a bare "thanks", a real person taps a reaction and lets the thread close.
A coach that answers it with a fresh paragraph is the tell that nobody is there.

Two decisions live here, both deterministic and both made BEFORE inference so a
reaction never costs a model call (which would defeat the point):

1. **Whether the turn qualifies** — ``is_bare_acknowledgement`` is a closed list of
   terminal acknowledgements, matched on the WHOLE normalized message. Substring
   matching is deliberately not used: "thanks, but what about my sleep?" opens a
   thread rather than closing one, and must get a real answer.
2. **Which emoji, if any** — ``reaction_for`` reads the persona's own
   ``texting_style.emoji_posture`` (``config/coaches/<coach>.json``, surfaced by
   ``persona_core.load_voice_spec`` / rendered by ``persona_core.texting_block``).
   A posture that says "essentially never" means essentially never: that coach
   does not start throwing 👍 because a new transport learned a new verb. And a
   persona with no posture configured at all gets NO reaction — absence honesty
   (ADR-104) applies to voice, not just numbers; inventing a register for a coach
   is the same class of error as inventing a number for a day.

Telegram permits only a fixed emoji set for reactions, so persona config is
validated against ``ALLOWED_REACTIONS`` rather than trusted — an unlisted emoji is
an API error, and a coach whose configured mark is not reactable (physical's 💪,
explorer's 📉/📈 — none of the three are on Telegram's list) simply does not react.

Transport-free by design: the worker owns ``setMessageReaction``, this owns the
decision, and a test can therefore pin the behaviour without a Telegram double.
"""

from __future__ import annotations

import re
from typing import Optional

# Telegram Bot API ``ReactionTypeEmoji`` — the complete permitted set, in the
# order the API documents it. Ordered (not just a set) because "the first legal
# emoji this posture names" must be deterministic. NB: 💪, 📈 and 📉 are NOT on
# this list; that omission is Telegram's, and it is load-bearing here.
ALLOWED_REACTIONS = (
    "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", "🤩", "🤮",
    "💩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳", "❤‍🔥", "🌚", "🌭", "💯", "🤣", "⚡",
    "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭", "🤓", "👻", "👨‍💻",
    "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿",
    "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷‍♂", "🤷", "🤷‍♀", "😡",
)  # fmt: skip
_ALLOWED = frozenset(ALLOWED_REACTIONS)

# The trigger class. Terminal acknowledgements ONLY — every phrase here ends a
# thread. Deliberately absent: "yeah", "yep", "right", "sure". Those are answers
# to a coach's question, and reacting to an answer leaves his question hanging.
_ACKNOWLEDGEMENTS = frozenset(
    {
        "thanks",
        "thank you",
        "thanks man",
        "thanks a lot",
        "thanks so much",
        "thx",
        "ty",
        "ok",
        "okay",
        "k",
        "kk",
        "got it",
        "gotcha",
        "understood",
        "noted",
        "cool",
        "nice",
        "perfect",
        "awesome",
        "love it",
        "sounds good",
        "will do",
        "on it",
        "copy that",
        "roger that",
        "makes sense",
        "fair enough",
        "appreciate it",
        "appreciate you",
    }
)

# A bare emoji from Matthew is itself a thread-closer. Kept tiny and explicit: a
# lone "🤔" is a prompt for more, not a close, and must not land here.
_EMOJI_ACKNOWLEDGEMENTS = frozenset({"👍", "🙏", "👌", "💪", "🔥", "❤️", "❤"})

# An austere posture, read off the posture's OPENING clause — that is where the
# register is set ("Essentially never.", "Rare to never."), and five of the eight
# shipped coaches open exactly that way. Scanning the whole string instead would
# be wrong: physical's posture opens permissively and ends "Never decorative",
# which is a qualifier on HOW it uses an emoji, not on whether.
_NEVER_RE = re.compile(r"\bnever\b", re.IGNORECASE)
_CLAUSE_RE = re.compile(r"[.!?]")

_WORDS_RE = re.compile(r"[^a-z' ]+")
_SPACE_RE = re.compile(r"\s+")

# Cheap pre-filter before normalizing: a real message is longer than any
# acknowledgement in the list, and normalizing every inbound paragraph to find
# that out is wasted work on the hot path.
_MAX_ACK_CHARS = 24


def normalize(text: str) -> str:
    """The comparison form: lowercased, letters and spaces only, collapsed.

    Strips trailing punctuation and decoration so "Thanks!!", "thanks :)" and
    "thanks 🙏" are the same acknowledgement — which is how they read on a phone.
    """
    return _SPACE_RE.sub(" ", _WORDS_RE.sub(" ", (text or "").strip().lower())).strip()


def is_bare_acknowledgement(text: str) -> bool:
    """Whether this message is a thread-closing acknowledgement and nothing else."""
    raw = (text or "").strip()
    if not raw or len(raw) > _MAX_ACK_CHARS:
        return False
    if raw in _EMOJI_ACKNOWLEDGEMENTS:
        return True
    return normalize(raw) in _ACKNOWLEDGEMENTS


def posture_permits_emoji(posture: str) -> bool:
    """Whether this persona's ``emoji_posture`` permits an emoji at all.

    An unconfigured posture is not permission to improvise one (ADR-104), and a
    posture whose opening clause says "never" means it.
    """
    p = (posture or "").strip()
    return bool(p) and not _NEVER_RE.search(_CLAUSE_RE.split(p)[0])


def reaction_for(spec: Optional[dict]) -> Optional[str]:
    """The emoji this persona reacts with, or None for "this coach does not react".

    Resolution order, most-specific first:

    1. a Telegram-legal emoji the posture itself names (the coach's own mark);
    2. ``texting_style.reaction_emoji`` — the explicit per-persona reaction, for
       coaches whose posture permits emoji but whose named marks are not on
       Telegram's list (or who name none);
    3. otherwise None.

    There is deliberately no shared default at the end of that chain. A default
    would make every coach react identically, which is the one outcome the
    per-coach ``emoji_posture`` exists to prevent.
    """
    style = (spec or {}).get("texting_style") if isinstance(spec, dict) else None
    if not isinstance(style, dict):
        return None
    posture = str(style.get("emoji_posture") or "")
    if not posture_permits_emoji(posture):
        return None

    named = [e for e in ALLOWED_REACTIONS if e in posture]
    if named:
        return min(named, key=posture.index)

    explicit = str(style.get("reaction_emoji") or "").strip()
    return explicit if explicit in _ALLOWED else None
