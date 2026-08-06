"""
social_consent.py — the public-context gate for a coach reaction to a SOCIAL post (#1675).

Epic #1668 (The Social Membrane, inbound half). #1574/#1756 built the coach-reaction
mechanism for Video Diary entries; #1675 extends that SAME mechanism to the social
channel. What differs between the two channels is not the reaction machinery — it is
the *permission question*, and this module answers it for social exactly the way
``diary_consent`` answers it for the diary.

The two channels ask opposite questions, which is why they need two gates and one
mechanism:

  * A **diary entry is private by default**. ``diary_consent`` therefore asks "did the
    owner explicitly opt this entry in?" and fails closed to ``private``.
  * A **social post is already public by construction** — Matthew published it himself,
    to a public platform, in his own words. There is nothing to consent to. The
    permission question is instead "is this really HIS public voice, and did it clear
    the platform's own auto-publish gate?" — i.e. the membrane's two existing gates:

        S2 (#1670, ``social_provenance``)         origin:human, never a platform echo
        S5 (#1673, ``broadcast_sensitivity_gate``) sensitivity_status == "cleared"

    Both are REUSED here, never re-implemented. A platform echo would make the coaches
    react to the platform's own outbound voice (the #1668 spanning-tree failure); an
    un-cleared post is exactly the post Matthew has not let auto-publish, so a public
    coach reaction to it would route around his own hold. Both fail closed.

ADR-104 grounding. The context handed to the generator is built field-by-field from an
allowlist (never copied-and-filtered from the record), and the single verbatim line it
may carry is selected DETERMINISTICALLY from the post's own text and then re-verified as
a literal (whitespace-normalised) substring of that text — the same invariant
``diary_consent._grounded_quote`` enforces. No enrichment field, no title metadata, and
no engagement number ever reaches the prompt: a coach reacting to a post cannot cite a
number it was never given.

The exposure vocabulary (``quote`` / ``allude``) and the 8-way laundered public theme are
imported from ``diary_consent`` rather than redefined, so both channels report exposure in
one vocabulary and the render surface needs no per-channel special case.

Pure module: no AWS, no boto3, no I/O — the leak/gate invariants are unit-testable with
zero live calls (the ``social_provenance`` house style).

v1.0.0 — 2026-08-05 (#1675, epic #1668)
"""

from __future__ import annotations

import re

from content import social_signals

from privacy import broadcast_sensitivity_gate as gate, social_provenance as prov
from privacy.diary_consent import TIER_ALLUDE, TIER_QUOTE, public_theme

# The reaction "kind" stamped on the context + the stored row, so one render surface can
# tell the two channels apart without inspecting the channel name.
KIND_SOCIAL = "social"

# Block reasons — the strings the trigger reports (and the tests assert on).
REASON_PLATFORM_ORIGIN = "platform_origin"  # S2: the platform's own echo, not his voice
REASON_HELD = "held"  # S5: not cleared for auto-publish

# A quotable line must be short enough to read as a pull-quote beside the coach's
# reaction. Longer candidates are rejected outright rather than truncated — a truncated
# quote would stop being a literal substring, breaking the ADR-104 grounding invariant.
MAX_QUOTE_CHARS = 200

# Sentence break: a terminator followed by whitespace. Deliberately simple and
# deterministic — a mis-split just yields a candidate that fails the length or grounding
# check, and we fall through to the next candidate (or to allude exposure).
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")

_SAFE_URL = re.compile(r"^https://[A-Za-z0-9.\-]+(?:/[^\s]*)?$")


def _norm(s) -> str:
    return " ".join(str(s or "").split()).lower()


def post_text(post: dict) -> str:
    """The post's own public text — the ONE definition, shared with the enricher.

    Delegates to ``social_signals.post_text`` so the text the ADR-104 grounding gate
    verifies a quote against is byte-for-byte the text the enricher grounded its causal
    hints against. Two definitions of "the post's text" would let a quote ground against
    one and not the other.
    """
    return social_signals.post_text(post)


def blocked_reason(post: dict):
    """Why this post may NOT receive a public coach reaction, or ``None`` if it may.

    FAIL-CLOSED at both gates, and evaluated BEFORE anything is generated or read:

      * ``platform_origin`` — S2 (#1670). Only ``origin:human`` posts are Matthew's
        voice; a re-ingested platform echo must never become coach signal.
      * ``held``            — S5 (#1673). ``is_cleared`` is a POSITIVE match on
        ``"cleared"``, so a missing, unknown or un-classified sensitivity stamp is NOT
        cleared and holds here too.
    """
    post = post or {}
    if not prov.is_human_origin(post):
        return REASON_PLATFORM_ORIGIN
    if not gate.is_cleared(post):
        return REASON_HELD
    return None


def is_reactable(post: dict) -> bool:
    """True iff both membrane gates pass — the coaches may react to this post."""
    return blocked_reason(post) is None


def public_quote(post: dict):
    """One deterministically-selected, literally-grounded line of the post, or ``None``.

    Candidates in order — the post's opening sentence, then its title, then its first
    line — and each is accepted only if it is short enough to render AND grounds as a
    literal (whitespace-normalised) substring of the post's own text. No LLM chooses the
    quote and nothing is truncated, so the ADR-104 invariant ("the quote is verbatim in
    the source") holds by construction rather than by inspection. ``None`` ⇒ the reaction
    is produced at allude strength — theme only, no verbatim text.
    """
    text = post_text(post)
    if not text:
        return None
    body = _norm(text)
    candidates = (
        (_SENTENCE_BREAK.split(text.strip()) or [""])[0],
        str((post or {}).get("title") or ""),
        text.splitlines()[0] if text.splitlines() else "",
    )
    for cand in candidates:
        cand = str(cand or "").strip()
        if not cand or len(cand) > MAX_QUOTE_CHARS:
            continue
        n = _norm(cand)
        if n and n in body:
            return cand
    return None


def post_url(post: dict):
    """The post's canonical public URL, or ``None`` — the reader's "he posted" half.

    Only an ``https://`` URL is returned (the same posts #1672's Broadcast feed already
    links out to); anything else — a scheme we don't vouch for, a ``javascript:`` string,
    a bare id — is dropped rather than served.
    """
    url = str((post or {}).get("url") or "").strip()
    return url if _SAFE_URL.match(url) else None


def public_context(post: dict):
    """The ONLY fields safe to hand a public-facing coach-reaction generator, or ``None``.

    ``None`` when either membrane gate blocks (⇒ no reaction is generated, nothing is
    stored, nothing renders — the same contract as ``diary_consent.public_context``).

    The dict is CONSTRUCTED key-by-key from the allowlist below; the post record is never
    copied and filtered, so an enrichment field, an engagement count, or a future column
    cannot ride along into a prompt:

        kind · tier · theme · channel · date · quote? · url?
    """
    if blocked_reason(post) is not None:
        return None

    post = post or {}
    quote = public_quote(post)
    ctx = {
        "kind": KIND_SOCIAL,
        # The ACTUAL exposure, in the same vocabulary the diary channel reports.
        "tier": TIER_QUOTE if quote else TIER_ALLUDE,
        # The same 8-way laundered public theme every allude surface uses (imported, not
        # re-derived) — computed from the post's enriched themes.
        "theme": public_theme(post),
        "channel": str(post.get("channel") or post.get("enriched_channel") or "social"),
        "date": post.get("date") or post.get("entry_date"),
    }
    if quote:
        ctx["quote"] = quote
    url = post_url(post)
    if url:
        ctx["url"] = url
    return ctx
