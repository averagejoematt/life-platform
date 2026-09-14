"""recap_gate.py — nothing reaches a public grid without passing this first (#3746).

WHY THIS LANDS BEFORE THE RENDERER

The daily recap card goes to a dedicated Instagram account. A public Instagram grid is
more findable than the site: it is indexed, it is reshared, and a single frame lives on in
someone's screenshot long after a page could be corrected. The card's own copy will name
foods, habits, workout titles and whether he journaled — every one of those a string that
comes from a partition with rules about it.

The machinery to enforce those rules already exists and is used by the site. What did not
exist was a caller for a surface that had not been written yet. So the gate ships first,
and the renderer may not send until it passes.

THE ORDER IS THE CONTRACT

  1. vocabulary, REQUIRED — `content_filter_channel.load(require=True)`. Unavailable is
     not "no blocked terms today"; it is a refusal. The vocabulary lives off-repo (#2503)
     precisely so a public repo cannot leak it, which means an environment that cannot
     reach it is an environment that cannot judge a card.
  2. per-item screen — every workout title, exercise name and habit label against the
     blocked vocabulary. A hit drops that TEMPLATE (the picker re-picks once) rather than
     failing the whole day: one blocked exercise name should cost a card variant, not the
     day's post.
  3. whole-card screen — `privacy_guard.assert_clean` over every string that will be drawn
     plus the caption, as one unit. Real names and vice terms are caught here even when
     they arrived through a field nobody screened individually.

FAIL CLOSED MEANS FAIL CLOSED

Every failure path returns "do not send". There is no degraded mode that posts anyway,
because the thing being protected is not the run — it is a public, permanent artifact.

WHAT THIS DELIBERATELY DOES NOT RUN (v1)

`broadcast_sensitivity_gate.classify_sensitivity` is not called. With no classifier wired
it HOLDS everything, its deterministic layer duplicates step 3, and in v1 every string on
the card is a numeric formatter or a fixed label — there is no free text for a semantic
classifier to judge. The compensating control is a test asserting no card field is sourced
from journal body text or food-item names. When the coach line lands (#3749) that changes,
and this module is where it changes.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# "cleared", matching broadcast_sensitivity_gate's vocabulary — one word for one
# meaning across both publish gates.
VERDICT_CLEARED = "cleared"
VERDICT_HELD = "held"
VERDICT_UNAVAILABLE = "unavailable"


class GateResult:
    """What the gate decided, and enough of why to act on it without re-running it."""

    def __init__(
        self, verdict: str, *, reason: str = "", blocked_templates: list[str] | None = None, hits: list[tuple[str, str]] | None = None
    ):
        self.verdict = verdict
        self.reason = reason
        self.blocked_templates = blocked_templates or []
        self.hits = hits or []

    @property
    def may_send(self) -> bool:
        return self.verdict == VERDICT_CLEARED

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.verdict}
        if self.reason:
            out["reason"] = self.reason
        if self.blocked_templates:
            out["blocked_templates"] = self.blocked_templates
        if self.hits:
            # Kinds only. The card's privacy record must not itself become a copy of the
            # vocabulary — a leak through the audit trail is still a leak.
            out["hit_kinds"] = sorted({k for k, _ in self.hits})
        return out

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"GateResult({self.verdict!r}, blocked={self.blocked_templates!r})"


def _word(term: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)


def item_is_blocked(name: str, *, vocabulary: dict[str, Any] | None = None) -> bool:
    """Is this workout/exercise/habit label a blocked-category item?

    Mirrors `site_api_common._is_blocked_vice` without importing it: that module builds
    boto3 clients and reads site config at import, which a card renderer has no business
    pulling in. The SEMANTICS are what must match, and the shared vocabulary is what makes
    them match — both sides read the same off-repo list.

    Unavailable vocabulary returns True — over-hide, never leak (the site's own posture).
    """
    if not name or not name.strip():
        return False
    from privacy import content_filter_channel as cfc

    data = vocabulary if vocabulary is not None else cfc.load()
    if data is None:
        return True
    lowered = name.strip().lower()
    for v in data.get("blocked_vices", []) or []:
        if isinstance(v, str) and v.strip() and v.strip().lower() == lowered:
            return True
    for kw in data.get("blocked_vice_keywords", []) or []:
        if isinstance(kw, str) and kw.strip() and kw.strip().lower() in lowered:
            return True
    return False


def screen_items(items: Iterable[tuple[str, str]], *, vocabulary: dict[str, Any] | None = None) -> list[str]:
    """(template_name, label) pairs in → the template names that must be dropped."""
    blocked: list[str] = []
    for template, label in items:
        if item_is_blocked(label, vocabulary=vocabulary) and template not in blocked:
            blocked.append(template)
    return blocked


def gate(strings: Iterable[str], *, items: Iterable[tuple[str, str]] | None = None, context: str = "recap-card") -> GateResult:
    """The one call a card renderer makes before it is allowed to send.

    `strings` is everything that will be drawn plus the caption. `items` is the
    (template, label) pairs whose names came from a partition with category rules.
    """
    from privacy import content_filter_channel as cfc, privacy_guard

    # 1. The vocabulary, required. An environment that cannot judge does not publish.
    try:
        vocabulary = cfc.load(require=True)
    except Exception as e:  # noqa: BLE001 — ContentFilterUnavailable, or any channel fault
        return GateResult(VERDICT_UNAVAILABLE, reason=f"content filter unavailable ({type(e).__name__}) — failing closed, no card sent")

    # 2. Per-item: a blocked label costs its template, not the day.
    blocked_templates = screen_items(items or [], vocabulary=vocabulary)

    # 3. The whole card as one unit.
    blob = "\n".join(s for s in strings if s)
    try:
        privacy_guard.assert_clean(blob, context=context)
    except privacy_guard.PrivacyViolation as e:
        return GateResult(
            VERDICT_HELD,
            reason="card copy did not pass the publish gate — nothing sent",
            blocked_templates=blocked_templates,
            hits=[(k, t) for k, t in e.violations if k != "context"],
        )

    return GateResult(VERDICT_CLEARED, blocked_templates=blocked_templates)
