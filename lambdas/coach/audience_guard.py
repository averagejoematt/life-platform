"""audience_guard.py — the PUBLIC-audience frame for coach narratives (#2972).

THE CLASS
---------
Every text a coach produces — `content`, `observatory_summary`, `key_recommendation`,
the coach-thread `position_summary` — is written in the coaching register: the coach
speaking TO Matthew, in the second person, because that is precisely what those
artifacts are. The public board (`/method/board/`) and the coaching door's stacked
digest (`/coaching/read/`) then served that register to site VISITORS: a reader met
"You've logged two training sessions" and "Matthew — and I want to name that plainly"
on an exhibit page, which reads as a leaked private channel (two `high`
`audience_violation` reader-truth findings, run 32580634729).

The #2972 root-cause census measured why no per-page patch can fix it: the field the
board preferred (`position_summary`) was empty in 175 of 175 OUTPUT# rows (it is
written to a DIFFERENT partition — `SOURCE#coach_thread`, the same reader/writer
mismatch class as #2569), so the read always fell through to `content`; and NO
producer anywhere wrote reader-facing prose, so a read-time guard alone would have
blanked every coach blurb on the flagship page.

THE CONTRACT
------------
The audience frame is a property of the SURFACE a narrative renders on, not of the
prompt an author remembered to write. This module is that property, stated once:

  * The extraction producer (`coach_extraction_prompt` task 12) now emits
    `public_summary` — the coach's read written ABOUT Matthew for an audience,
    third person for the subject, grounded by the same ADR-104 gate as the rest of
    the derived-prose set (`coach_derived_prose.DERIVED_PROSE_FIELDS`).
  * The writer (`coach_state_updater._write_output_record`) persists it through
    `reader_safe()` — an owner-directed candidate is rejected at write time.
  * The public read seams (`/api/coaching-dashboard`'s blurb slot via
    `public_blurb()`, `/api/coach_analysis`'s `public_read` field via
    `public_read()`, the integrator's weekly text via `is_owner_directed()` in
    `site_api_coach_stance._integrator_digest`) serve ONLY guard-passed public
    text. There is deliberately NO fallback to `observatory_summary` or `content`:
    those are the owner's channel by design, and an empty public slot (the
    front-ends' existing honest-empty states) is the correct degradation.

TWO RULES THE FIRST ATTEMPT GOT WRONG (recorded so they stay wrong only once)
-----------------------------------------------------------------------------
  * The check runs on the FULL stored text, before any truncation — a 200-char
    slice of addressing prose can pass a check its source fails, which launders
    the defect it was meant to catch. `public_blurb()` guards first, then cuts.
  * A read-time guard with no producer is a blanking machine, not a fix. The
    guard here is the enforcement HALF of the contract; the producer is the other.

Deterministic, zero-AI-cost, pure (no boto3, no clock, no network) — the #1987
`voice_register_guard` posture, pointed the other way: that module rejects
third-person meta-narration from the OWNER-facing voice slots; this one rejects
second-person address from the PUBLIC-facing slot.
"""

import os
import re

from common.text_utils import truncate_at_word

# The subject's display name, derived from the same USER_ID the writers use —
# never a second hand-typed copy of it.
_OWNER_NAME = os.environ.get("USER_ID", "matthew").strip().title() or "Matthew"

# Second-person address: you / your / yours / yourself / you're / you've / you'll /
# you'd. `\byou\b` also matches the "you" in "you're" (the apostrophe is a word
# boundary), and the explicit alternates keep the intent readable. Case-insensitive.
_SECOND_PERSON_RE = re.compile(r"\byou(?:rs(?:el(?:f|ves))?|r|'(?:re|ve|ll|d))?\b", re.IGNORECASE)

# Vocative address by name — "…quiet for three days, Matthew — …", a sentence
# opening "Matthew — and I want…", a "Matthew," salutation. A vocative is set off
# on BOTH sides, which is what separates it from ordinary third person: ", Matthew
# logged two sessions" and "Matthew's recovery" are the public register working
# exactly as intended and deliberately do NOT match. Case-sensitive — the
# second-person arm above carries the recall; this arm is precision.
_VOCATIVE_RE = re.compile(
    r"(?:,\s*" + re.escape(_OWNER_NAME) + r"\s*(?:[,.!?;—–-]|$)"  # "…, Matthew —" / "…, Matthew."
    r"|(?:^|[.!?]\s+)" + re.escape(_OWNER_NAME) + r"\s*[,—–-])",  # "Matthew — and I want…"
    re.MULTILINE,
)


def is_owner_directed(text) -> bool:
    """True if `text` addresses the owner directly — second person, or vocative name.

    Callers MUST pass the full stored text, never a truncated slice (see module
    docstring). Falsy input is not an address.
    """
    if not text:
        return False
    text = str(text)
    return bool(_SECOND_PERSON_RE.search(text) or _VOCATIVE_RE.search(text))


def reader_safe(text, coach_id=None, logger=None):
    """The WRITE-side seam: return `text` only if it is safe for a public audience.

    Owner-directed text returns None — the slot is held empty rather than
    published — and the rejection is logged when a logger is supplied, so a
    producer that keeps drifting into second person is visible in the run logs.
    Falsy input returns None (an absent candidate, not a rejection).
    """
    if not text or not str(text).strip():
        return None
    text = str(text).strip()
    if is_owner_directed(text):
        if logger is not None:
            logger.warning(
                "public_summary rejected for %s (addresses the owner directly) — the public slot is held empty (#2972)",
                coach_id or "unknown-coach",
            )
        return None
    return text


def public_read(output_item):
    """The READ-side seam, untruncated: the OUTPUT# row's public narrative or None.

    Reads ONLY `public_summary`. `observatory_summary` and `content` are the
    owner's channel — falling back to them is the exact defect this module
    exists to remove, so no such fallback is offered here.
    """
    item = output_item or {}
    value = item.get("public_summary")
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if is_owner_directed(value):  # belt for rows written before the write-side seam
        return None
    return value


def public_blurb(output_item, limit=200) -> str:
    """The card-sized public blurb: guard the FULL text first, truncate second.

    Order is load-bearing — truncation can delete the very pronoun that makes a
    text an address, so a `check(truncate(x))` shape passes on a slice whose
    source fails (#2972). Returns "" when no reader-safe text exists; the
    front-ends' blurb renderers already drop empty entries honestly.
    """
    value = public_read(output_item)
    if not value:
        return ""
    return truncate_at_word(value, limit)
