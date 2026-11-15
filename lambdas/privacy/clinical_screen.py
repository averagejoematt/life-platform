"""clinical_screen.py — the owner-only clinical record never reaches a public surface (#5947).

docs/DATA_GOVERNANCE.md: the owner clinical record is "Never on a public surface — no projection, no
aggregate, no count". It may enter an AI coach's context (ADR-155 amendment) under a non-disclosure
instruction — and a prompt instruction is a hope, not a guarantee, so this is the code gate behind it.

THE VOCABULARY IS NOT HERE. The words that name the record are themselves the guarded data and this
repo is public, so they live only in the ER-06 non-committed channel
(``content_filter_channel.clinical_keywords`` — env / gitignored local file / the private S3 config).
Nothing in this module, its logs or its errors echoes a term.

TWO POSTURES, chosen by the caller:

  * ``mentions(text, require=True)`` — a PUBLISH/CURATE decision on one text. Fail closed: an unarmed
    channel raises ``ContentFilterUnavailable`` and the caller withholds (a screen with an empty
    vocabulary guards nothing).
  * ``guard_response(response)`` — the WIRE layer behind every public API response
    (``common.journal_silence.guard_api_response`` chains it). Defence in depth across every route, so
    an unarmed channel is a no-op here rather than an outage of the whole API (a surface with its own
    publication stamp fails closed at its own door instead).
    Degradation is the journal-silence guard's: a list element whose subtree hits is dropped, any other
    string loses the sentence, keys are never rewritten, clean payloads are returned untouched.

Matching is whole-word and case-insensitive; a multi-word term matches across any run of whitespace
or hyphens. A keyword screen cannot see a paraphrase — it is the backstop. The policy for a surface
that publishes curated AI text is a positive, fail-closed publication stamp at its own door
(``reading.horizons_publication`` is the first).

Pure module: no AWS at import (the channel's S3 leg is lazy).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from common import journal_silence

from privacy import content_filter_channel

_SEPARATOR = re.compile(r"[\s\-]+")
_compiled: tuple = ((), None)  # (vocabulary, pattern) — recompiled only when the channel's list changes


def _compile(terms: tuple) -> Optional[re.Pattern]:
    parts = []
    for term in sorted(terms, key=len, reverse=True):
        words = [re.escape(w) for w in _SEPARATOR.split(term) if w]
        if words:
            parts.append(r"[\s\-]+".join(words))
    if not parts:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


def pattern(require: bool = False) -> Optional[re.Pattern]:
    """The compiled clinical pattern, or None when the channel is unarmed (``require=True`` raises instead)."""
    global _compiled
    terms = tuple(content_filter_channel.clinical_keywords(require=require))
    if terms != _compiled[0] or (terms and _compiled[1] is None):
        _compiled = (terms, _compile(terms))
    return _compiled[1] if terms else None


def mentions(text: Any, require: bool = True) -> bool:
    """True when ``text`` carries a clinical term. Fail closed by default (see the module docstring)."""
    pat = pattern(require=require)
    if pat is None:
        return False
    return bool(pat.search(str(text or "")))


def scrub_payload(payload: Any, require: bool = False) -> tuple:
    """A JSON-shaped payload with clinical copy withheld, and the number of spans withheld."""
    pat = pattern(require=require)
    if pat is None:
        return payload, 0
    return journal_silence._scrub(payload, pat)


def guard_response(response: Any, logger: Any = None) -> Any:
    """The wire half: a public API response with every clinical span withheld. The count is LOGGED, never
    served (owner ruling 2026-11-05: no withheld counts on public responses)."""
    if not isinstance(response, dict) or response.get("isBase64Encoded"):
        return response
    body = response.get("body")
    if not isinstance(body, str):
        return response
    pat = pattern(require=False)
    if pat is None:
        return response
    headers = response.get("headers") or {}
    content_type = str(headers.get("Content-Type") or headers.get("content-type") or "")
    new_body, hits = journal_silence._scrub_text_body(body, content_type, pat)
    if not hits:
        return response
    if logger is not None:
        logger.warning("clinical-record copy withheld from a public response: %d span(s) (#5947)", hits)
    return {**response, "body": new_body}
