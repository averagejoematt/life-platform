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

  4. semantic screen on FREE TEXT ONLY — `broadcast_sensitivity_gate.classify_sensitivity`
     over the card's prose fields. Runs last because ADR-105 is explicit that the
     deterministic computation comes before any LLM verdict, and because a card held by
     step 3 should never have cost a classifier call.

THE FOURTH STEP LANDED WITH THE COACH LINE (#3749), AND WHY IT COULD NOT BEFORE

v1 of this module said, in this spot, that the sensitivity gate was deliberately not
called: with no classifier wired it HOLDS everything, its deterministic layer duplicated
step 3, and every string on a v1 card was a numeric formatter or a fixed label — there
was no free text for a semantic classifier to judge. The compensating control was a test
asserting no card field came from journal body text or a food-item name.

All three of those changed at once when the card grew a coach line. There is now prose on
the card, so the classifier has something to judge; and it is wired, so the gate no longer
holds by default. The classifier is `_first_party_editorial_classifier`, and it is the
`horizons_retrospective` precedent exactly: a coach's `public_summary` is first-party
editorial about this platform's own subject, written by a coach this platform runs and
already through that coach's own ADR-104 grounding gate — on-topic by construction. It
vouches on-topic at full confidence, spends no Bedrock, and is INJECTABLE, so a stricter
semantic screen can be wired later without touching a caller.

What that classifier deliberately does NOT do is weaken the gate. On-topic is the only
question it answers. The load-bearing protection for a sentence written by a model is the
same deterministic spine every other publish path uses — `privacy_guard`'s vice
vocabulary, its public-figure real-name guard, and the PII patterns — and step 4 runs all
of it over the coach line whether or not the classifier has an opinion. A coach line that
ever names a blocked-category term, a real person or a phone number holds the card, and
`tests/test_recap_coach_line_3749.py` plants each of those to prove it.

Free text ONLY, and the narrowness is deliberate in both directions. Running step 4 over
the whole card would re-screen forty numeric formatters for a semantic property they
cannot have, and — worse — would make the classifier's verdict a gate on the numbers,
which is precisely the "LLM in front of a deterministic answer" shape ADR-105 forbids.
Running it over nothing would be a gate that cannot fail. So it runs over
`DayFacts.free_text()`, and when there is no free text on a card there is no step 4:
absence of prose is not an unjudgeable card, it is the v1 card, which needed no judge.
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


def _first_party_editorial_classifier(text: str):
    """The off-topic layer for a coach line — on-topic by construction.

    The `horizons_retrospective._default_offtopic_classifier` precedent, for the same
    reason. A coach's `public_summary` is first-party editorial ABOUT this platform's own
    subject, written by a coach this platform runs, on a day of the experiment the card is
    reporting. There is no plausible reading on which it is off-topic for the account, so
    a Bedrock call to ask would spend money to return the answer we already have.

    It answers ONLY the relevance question. Every protective judgment — vices, real names,
    PII — is the gate's deterministic spine, which runs before this and is unaffected by
    what this returns. Injectable, so wiring a real semantic screen later is a parameter
    and not a rewrite.
    """
    from privacy import broadcast_sensitivity_gate as bsg

    return bsg.OfftopicResult(True, 1.0)


def screen_free_text(texts: Iterable[str], *, offtopic_classifier=None, context: str = "recap-card") -> tuple[str, list[tuple[str, str]]]:
    """Step 4 over the card's prose. Returns (verdict, hits) — `hits` are (kind, term).

    Empty input is CLEARED and runs no classifier: a card with no prose on it has nothing
    for a semantic layer to judge, and holding it would be a gate firing on the absence of
    its own subject. Every other path resolves through `classify_sensitivity`, which is
    fail-closed on all of them.
    """
    from privacy import broadcast_sensitivity_gate as bsg

    prose = [t for t in texts if t and str(t).strip()]
    if not prose:
        return VERDICT_CLEARED, []

    classifier = offtopic_classifier if offtopic_classifier is not None else _first_party_editorial_classifier
    hits: list[tuple[str, str]] = []
    for text in prose:
        verdict = bsg.classify_sensitivity(str(text), offtopic_classifier=classifier)
        if verdict.status != bsg.SENSITIVITY_CLEARED:
            # Categories only, never the text. The record must not become a copy of the
            # thing that was too sensitive to publish — the `to_dict` rule, one layer up.
            hits.extend((c, context) for c in (verdict.categories or ("sensitivity",)))
    return (VERDICT_HELD if hits else VERDICT_CLEARED), hits


def gate(
    strings: Iterable[str],
    *,
    items: Iterable[tuple[str, str]] | None = None,
    free_text: Iterable[str] | None = None,
    context: str = "recap-card",
    offtopic_classifier=None,
) -> GateResult:
    """The one call a card renderer makes before it is allowed to send.

    `strings` is everything that will be drawn plus the caption. `items` is the
    (template, label) pairs whose names came from a partition with category rules.
    `free_text` is the card's prose — today the coach line — which additionally goes
    through the semantic sensitivity screen (#3749).
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

    # 4. The semantic screen, over prose only, last (ADR-105: deterministic first).
    sens_verdict, sens_hits = screen_free_text(free_text or [], offtopic_classifier=offtopic_classifier, context=context)
    if sens_verdict != VERDICT_CLEARED:
        return GateResult(
            VERDICT_HELD,
            reason="card prose did not pass the sensitivity gate — nothing sent",
            blocked_templates=blocked_templates,
            hits=sens_hits,
        )

    return GateResult(VERDICT_CLEARED, blocked_templates=blocked_templates)
