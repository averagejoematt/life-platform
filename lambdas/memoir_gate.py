"""memoir_gate.py — ADR-104 deterministic post-check specific to coach memoirs (#553).

A coach memoir is a first-person retrospective over the coach's own quarterly
LEARNING# record. The platform's honesty differentiator collapses if a coach
narrates only its hits — issue #553's acceptance bar is "misses must outnumber
humblebrags," enforced here in the weak, deterministic sense that actually
holds up mechanically: when at least one graded miss (a refuted LEARNING#)
exists for the quarter, the memoir must engage with at least one of them,
specifically or in honest plain language — never just a highlight reel.

Paired with grounded_generation.py (the general ADR-104 number-fabrication
gate, reused as-is by the memoir batch) — this module adds the memoir-specific
"don't dodge your own record" check. Pure functions, no AWS.
"""

# Phrases that, on their own, signal the coach is naming something it got
# wrong — used when the miss is paraphrased rather than quoting a metric/
# subdomain string verbatim (normal, honest prose shouldn't be penalized for
# not repeating jargon).
MISS_PHRASES = (
    "i was wrong",
    "i got it wrong",
    "i missed",
    "i overcalled",
    "i undercalled",
    "that didn't hold up",
    "that call didn't hold",
    "i should have",
    "i need to revise",
    "i have to walk back",
    "walking back",
    "refuted",
    "didn't pan out",
    "didn't play out",
    "i was too confident",
    "i overestimated",
    "i underestimated",
    "i was off",
    "that one didn't land",
)


def refuted_markers(learnings) -> list:
    """Lowercase metric/subdomain substrings pulled from refuted LEARNING#
    records — citing one of these verbatim counts as engaging with that miss."""
    markers = []
    for item in learnings or []:
        if str((item or {}).get("status", "")).strip().lower() != "refuted":
            continue
        for field in ("subdomain", "metric"):
            v = item.get(field)
            if v and str(v).strip():
                markers.append(str(v).strip().lower())
    return markers


def cites_a_miss(text: str, learnings) -> tuple:
    """(ok: bool, reason: str).

    ok=True when there's nothing to cite (no refuted learning this quarter),
    OR the text names a specific refuted metric/subdomain, OR the text uses
    honest miss-acknowledgment language. ok=False means the memoir had at
    least one real miss available and dodged all of them — a humblebrag reel.
    """
    markers = refuted_markers(learnings)
    if not markers:
        return True, "no_refuted_learnings_this_quarter"
    low = (text or "").lower()
    for marker in markers:
        if marker and marker in low:
            return True, f"cites_specific_miss:{marker}"
    for phrase in MISS_PHRASES:
        if phrase in low:
            return True, "cites_generic_miss_language"
    return False, "no_miss_cited_despite_refuted_learnings"
