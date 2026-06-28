"""
privacy_guard.py — deterministic last-line privacy scrub for public AI content.

Privacy on this platform is enforced by prompt instructions AND — because a prompt
is a hope, not a guarantee — by this fail-closed code gate at every publish/serve
chokepoint. Two leak classes the truth audit (2026-06-27) caught:
  • real public figures named as if they were the platform's coaches/sources
    (every coach here is fictional — Layne Norton → Dr. Marcus Webb, etc.);
  • vices/substances the subject is working to moderate (never public).

Usage:
  - PUBLISH chokepoints (chronicle, podcast, digests) → `assert_clean(text)` —
    raises PrivacyViolation so a leaking artifact is NOT published (fail-closed).
  - SERVE chokepoints (/api/ask, /api/board_ask) → `scrub(text)` — redacts inline
    so the request still answers without leaking.
  - Stamp generated content with `GUARD_VERSION`; refuse to publish anything older
    (kills the stale pre-guard drafts the audit found).

Pure module (no AWS), layer-deployed. No external deps.
"""

import re

# Bump when the banned sets below change; publish paths refuse drafts stamped older.
GUARD_VERSION = "2026-06-28"

# Vices/substances — never public. Mirrors site_api_ai_lambda `blocked_vice_keywords`
# (kept in sync) plus nicotine. Alcohol is deliberately NOT a hard block — it appears
# in too much legitimate nutrition context; the prompt handles it.
VICE_KEYWORDS = (
    "marijuana",
    "cannabis",
    "weed",
    "thc",
    "pornography",
    "porn",
    "nicotine",
)

# Real public figures (health/fitness influencers) the AI tends to name as coaches.
# Match on the FULL name — unambiguous.
BANNED_FULL_NAMES = (
    "peter attia",
    "andrew huberman",
    "rhonda patrick",
    "layne norton",
    "james clear",
    "david goggins",
    "vivek murthy",
    "paul conti",
    "matthew walker phd",  # the sleep scientist — only the disambiguated forms,
    "dr. matthew walker",  # never bare "Matthew Walker" (that IS the subject)
)

# Standalone surnames safe to match alone because they are NOT also the subject's
# name or common words. (Deliberately EXCLUDES walker/patrick/clear/norton/murthy —
# ambiguous or collide with the subject; those are caught by BANNED_FULL_NAMES.)
BANNED_SURNAMES = (
    "attia",
    "huberman",
    "goggins",
)


class PrivacyViolation(Exception):
    """Raised by assert_clean when banned content would be published."""

    def __init__(self, violations):
        self.violations = violations
        super().__init__("privacy violations: " + "; ".join(f"{k}:{v}" for k, v in violations))


def _word(term):
    return re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)


def find_violations(text):
    """Return a list of (kind, term) for every banned vice/name found. Empty = clean."""
    if not text:
        return []
    lowered = text.lower()
    hits = []
    for kw in VICE_KEYWORDS:
        if _word(kw).search(text):
            hits.append(("vice", kw))
    for nm in BANNED_FULL_NAMES:
        if nm in lowered:
            hits.append(("real_name", nm))
    for sn in BANNED_SURNAMES:
        if _word(sn).search(text):
            hits.append(("real_name", sn))
    return hits


def is_clean(text):
    return not find_violations(text)


def assert_clean(text, context=""):
    """Fail-closed publish gate: raise PrivacyViolation if `text` leaks. Returns text if clean."""
    v = find_violations(text)
    if v:
        raise PrivacyViolation([(k, t) for k, t in v] + ([("context", context)] if context else []))
    return text


def scrub(text, redaction="[redacted]"):
    """Serve-time gate: redact banned vices/names inline so the response still answers.

    Returns (scrubbed_text, hit_count). Use where blocking the whole response is worse
    than redacting (the public Q&A endpoints).
    """
    if not text:
        return text, 0
    n = 0
    out = text
    for kw in VICE_KEYWORDS:
        out, c = _word(kw).subn(redaction, out)
        n += c
    for sn in BANNED_SURNAMES:
        out, c = _word(sn).subn(redaction, out)
        n += c
    for nm in BANNED_FULL_NAMES:
        new = re.sub(re.escape(nm), redaction, out, flags=re.IGNORECASE)
        if new != out:
            n += 1
            out = new
    return out, n


def is_stale_draft(guard_version):
    """True if a stored draft was generated before the current guard (must not publish)."""
    return (guard_version or "") < GUARD_VERSION
