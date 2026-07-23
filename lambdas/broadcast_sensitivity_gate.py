"""broadcast_sensitivity_gate.py — the fail-closed auto-publish sensitivity gate (#1673).

Epic #1668 (The Social Membrane, inbound half). Decision (2) makes the Broadcast feed
(#1672, S4) an AUTOMATIC public feed — low-touch, not a manual approval queue. But two
absolutes are non-negotiable: the privacy vices (marijuana / porn) and PII never go
public, and #1563 is explicit that Matthew's words are NEVER auto-published blind. The
reconciliation is THIS gate: an automatic classifier runs on every ``origin:human`` post
and only a post that clears the fail-closed filter is eligible to auto-publish; anything
flagged HOLDS for Matthew's review. Automatic display, but fail-closed.

Where it sits in the membrane stack (#1670 `social_provenance.py:161`):
    is_displayable_voice = is_human_origin   # S4 shows human posts …
    #                                          … S5 (THIS module) adds the gate ON TOP.
The S4 feed query composes both: ``human_origin_filter_expression() AND
cleared_filter_expression()`` — a platform echo OR an un-cleared post is simply absent.

## The verdict seam (#1672 codes to this)
Every classified post row carries three attributes, written next to #1670's ``origin``:
  * ``sensitivity_status``  ∈ {``"cleared"``, ``"held"``}   (STATUS_ATTR)
  * ``sensitivity_reason``  — human-readable hold reason      (REASON_ATTR)
  * ``sensitivity_categories`` — list of triggered categories (CATEGORIES_ATTR)
#1672's feed query filters on ``sensitivity_status == "cleared"`` via
``cleared_filter_expression()`` / ``is_cleared(post)`` / ``filter_cleared(posts)``.
FAIL-CLOSED BY CONSTRUCTION: the filter is a POSITIVE match on ``"cleared"`` (unlike
#1670's origin filter, which is ``!= platform`` so unstamped legacy rows survive). A
missing / unknown / un-classified status is therefore NOT cleared → absent from the feed.
Auto-publish is reachable ONLY through this gate — nothing else writes ``"cleared"``.

## Fail-closed posture (reused, not re-invented)
The deterministic spine is `privacy_guard` — already fail-closed and already the
canonical vice policy (its ``VICE_KEYWORDS`` is a documented superset of the S3
``config/content_filter.json`` ``blocked_vice_keywords``). We do NOT hand-roll a second
vice list; the marijuana/porn categories are DERIVED from ``privacy_guard`` hits. On top
of that deterministic layer sits an OPTIONAL semantic off-topic classifier (Haiku, via
`bedrock_client`, budget-gated). Every uncertain path — a classifier error, a budget
pause, a low-confidence verdict, or simply no classifier wired — resolves to HOLD, never
publish (ADR-104/105: deterministic computation before any LLM verdict; honest hold when
the machine cannot vouch for it).

Pure module: no AWS / no boto3 at import (the bedrock + budget imports are lazy, inside
`bedrock_offtopic_classifier`), so the decision logic is exhaustively unit-testable
offline with an injected classifier — the `social_provenance` house style.

v1.0.0 — 2026-07-22 (#1673, epic #1668)
"""

from __future__ import annotations

import re
from collections import namedtuple

import privacy_guard

# ── Verdict seam constants (the stable contract #1672 consumes) ────────────────────
STATUS_ATTR = "sensitivity_status"
REASON_ATTR = "sensitivity_reason"
CATEGORIES_ATTR = "sensitivity_categories"

SENSITIVITY_CLEARED = "cleared"
SENSITIVITY_HELD = "held"

# ── Flagged categories (the canonical policy list — NOT ad-hoc) ────────────────────
# marijuana / porn come from `privacy_guard` (the canonical vice policy); pii + off_topic
# are this gate's additions. `real_name` reuses privacy_guard's public-figure guard as an
# extra privacy hold. `classifier_error` is the fail-closed catch-all.
CATEGORY_MARIJUANA = "marijuana"
CATEGORY_PORN = "porn"
CATEGORY_PII = "pii"
CATEGORY_OFF_TOPIC = "off_topic"
CATEGORY_REAL_NAME = "real_name"
CATEGORY_CLASSIFIER_ERROR = "classifier_error"

# The four AC-named flagged categories, sourced here so callers/tests reference the
# policy, never a local literal.
FLAGGED_CATEGORIES = (CATEGORY_MARIJUANA, CATEGORY_PORN, CATEGORY_PII, CATEGORY_OFF_TOPIC)

# Below this the off-topic classifier's own confidence is treated as "cannot vouch" → hold.
CONFIDENCE_FLOOR = 0.6


class Verdict(namedtuple("Verdict", ["status", "categories", "reason", "confidence"])):
    """The gate's decision for one post. ``status`` is the seam value written to the row."""

    @property
    def cleared(self) -> bool:
        return self.status == SENSITIVITY_CLEARED


# The off-topic classifier's return shape. ``on_topic`` is tri-state:
#   True  → confidently on-topic     False → confidently off-topic     None → uncertain
# ``None`` (or a low ``confidence``) is fail-closed to HOLD, same as an exception.
OfftopicResult = namedtuple("OfftopicResult", ["on_topic", "confidence"])


# ── Policy mapping: privacy_guard hit → this gate's category ───────────────────────
def _category_for_privacy_hit(kind: str, term: str) -> str:
    """Map a `privacy_guard.find_violations` hit to a flagged category.

    Derived from `privacy_guard`'s own sets — porn keywords → porn; every other vice
    (the cannabis family + nicotine) → the marijuana/substance category; a banned real
    public figure → real_name. No independent keyword list lives here.
    """
    if kind == "real_name":
        return CATEGORY_REAL_NAME
    # kind == "vice": split porn from the substance family using privacy_guard's terms.
    if term in ("porn", "pornography"):
        return CATEGORY_PORN
    return CATEGORY_MARIJUANA


# ── Deterministic PII detection (always on; no AWS, no AI) ─────────────────────────
_PII_PATTERNS = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Phone: require separators so we don't flag an arbitrary 10-digit run (e.g. view counts).
    ("phone", re.compile(r"(?<!\d)(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # Card / long account number: 13–19 digits, optional space/dash grouping.
    ("card", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?<=\d)")),
)


def find_pii(text: str) -> list:
    """Return the list of PII kinds found (empty = none). Deterministic, offline."""
    if not text:
        return []
    return [kind for kind, pat in _PII_PATTERNS if pat.search(text)]


# ── Deterministic layer (the fail-closed spine) ────────────────────────────────────
def deterministic_findings(text: str) -> list:
    """Every hard-block category found by the deterministic spine (privacy_guard + PII).

    Order-stable, de-duplicated. Empty ⇒ the post is deterministically clean and only the
    semantic off-topic layer remains. This layer NEVER depends on AI/budget/network, so
    the privacy absolutes hold by construction even at budget tier 3 / a Bedrock outage.
    """
    cats = []
    for kind, term in privacy_guard.find_violations(text or ""):
        cat = _category_for_privacy_hit(kind, term)
        if cat not in cats:
            cats.append(cat)
    if find_pii(text or ""):
        if CATEGORY_PII not in cats:
            cats.append(CATEGORY_PII)
    return cats


# ── The classifier ─────────────────────────────────────────────────────────────────
def classify_sensitivity(text: str, *, offtopic_classifier=None) -> Verdict:
    """Classify one post's text; return a fail-closed :class:`Verdict`.

    Sequence (ADR-105 — deterministic before any LLM):
      1. Deterministic hard block (privacy_guard vices/real-names + PII). Any hit ⇒ HELD.
      2. Semantic off-topic layer (the injected ``offtopic_classifier``). Anything but a
         confident on-topic verdict ⇒ HELD:
           * no classifier wired            → HELD (cannot evaluate → fail closed)
           * classifier raises              → HELD (classifier_error)
           * on_topic is False              → HELD (off_topic)
           * on_topic is None / low conf    → HELD (classifier could not vouch)
      3. Only a deterministically-clean AND confidently-on-topic post is CLEARED.

    ``offtopic_classifier`` is a callable ``text -> OfftopicResult`` (injected so the
    module stays AWS-free and unit-testable). Production wires
    :func:`bedrock_offtopic_classifier`.
    """
    det = deterministic_findings(text)
    if det:
        return Verdict(SENSITIVITY_HELD, tuple(det), "flagged: " + ", ".join(det), 1.0)

    if offtopic_classifier is None:
        return Verdict(
            SENSITIVITY_HELD,
            (CATEGORY_OFF_TOPIC,),
            "off-topic relevance could not be evaluated (no classifier available)",
            0.0,
        )

    try:
        result = offtopic_classifier(text)
    except Exception as e:  # noqa: BLE001 — ANY classifier failure is fail-closed to HOLD
        return Verdict(SENSITIVITY_HELD, (CATEGORY_CLASSIFIER_ERROR,), f"classifier error: {e}", 0.0)

    if result is None:
        return Verdict(SENSITIVITY_HELD, (CATEGORY_CLASSIFIER_ERROR,), "classifier returned no verdict", 0.0)
    if result.on_topic is False:
        return Verdict(SENSITIVITY_HELD, (CATEGORY_OFF_TOPIC,), "off-topic for the platform's subject", float(result.confidence or 0.0))
    if result.on_topic is None or (result.confidence or 0.0) < CONFIDENCE_FLOOR:
        return Verdict(
            SENSITIVITY_HELD,
            (CATEGORY_OFF_TOPIC,),
            "off-topic classifier could not vouch (uncertain / low confidence)",
            float(result.confidence or 0.0),
        )
    return Verdict(SENSITIVITY_CLEARED, (), "cleared: deterministically clean and confidently on-topic", float(result.confidence))


# ── Row stamping (called at ingestion, next to #1670's origin stamp) ───────────────
def sensitivity_attrs(verdict: Verdict) -> dict:
    """The attributes to merge onto a post's DDB record — the seam #1672 reads."""
    attrs = {STATUS_ATTR: verdict.status, REASON_ATTR: verdict.reason}
    if verdict.categories:
        attrs[CATEGORIES_ATTR] = list(verdict.categories)
    return attrs


def classify_and_stamp(text: str, *, offtopic_classifier=None) -> dict:
    """Convenience for a writer: classify ``text`` and return the row attributes to merge."""
    return sensitivity_attrs(classify_sensitivity(text, offtopic_classifier=offtopic_classifier))


# ── Read-side seam (the feed / review surfaces filter on these) ────────────────────
def is_cleared(post: dict) -> bool:
    """True iff a post explicitly cleared the gate — the ONLY auto-publishable state.

    Fail-closed: a missing / unknown status is NOT cleared (unlike #1670's origin, an
    absent stamp is never treated as safe here).
    """
    return (post or {}).get(STATUS_ATTR) == SENSITIVITY_CLEARED


def is_held(post: dict) -> bool:
    """True iff a post is held for review (explicitly, or by an absent/unknown stamp)."""
    return not is_cleared(post)


def filter_cleared(posts):
    """Keep only cleared posts — the gate applied to any in-memory list (S4 feed)."""
    return [p for p in posts if is_cleared(p)]


def cleared_filter_expression():
    """A boto3 ``FilterExpression`` selecting only cleared posts, for the S4 feed query.

    Usage (#1672, composed with the #1670 membrane):
        table.query(
            ...,
            FilterExpression=social_provenance.human_origin_filter_expression()
                             & broadcast_sensitivity_gate.cleared_filter_expression(),
        )
    A positive ``== "cleared"`` match (not ``!= "held"``) so an unstamped row is excluded —
    fail-closed by construction.
    """
    from boto3.dynamodb.conditions import Attr

    return Attr(STATUS_ATTR).eq(SENSITIVITY_CLEARED)


def held_filter_expression():
    """A boto3 ``FilterExpression`` selecting held posts — Matthew's review surface."""
    from boto3.dynamodb.conditions import Attr

    return Attr(STATUS_ATTR).ne(SENSITIVITY_CLEARED)


def review_record(post: dict) -> dict:
    """Compact record of a held post for Matthew's review queue (not silently dropped).

    Surfaces WHY it held so the decision is informed; the fields come straight off the
    stamped row.
    """
    p = post or {}
    return {
        "post_id": p.get("post_id"),
        "channel": p.get("channel"),
        "title": p.get("title"),
        "url": p.get("url"),
        "status": p.get(STATUS_ATTR),
        "reason": p.get(REASON_ATTR),
        "categories": p.get(CATEGORIES_ATTR, []),
    }


# ── Production off-topic classifier (Bedrock; lazy imports; fail-closed) ────────────
# Budget feature name. Deliberately NOT registered in budget_guard._FEATURE_CUTOFF, so it
# inherits the "unknown feature" cutoff (tier 3) — this cheap Haiku pass keeps the feed
# low-touch until the hard stop, at which point bedrock_client's own tier-3 backstop
# raises anyway and we hold. (Promotable into an ADR-125 band later if telemetry warrants.)
_BUDGET_FEATURE = "broadcast_sensitivity"

_OFFTOPIC_SYSTEM = (
    "You are a topic-relevance gate for a public feed about ONE person's health, fitness, "
    "training, nutrition, sleep, recovery, longevity, and a self-quantification experiment. "
    "Decide whether a social post plausibly belongs on that feed. On-topic: anything about "
    "training/workouts, nutrition/diet, sleep/recovery, health metrics/labs, the experiment, "
    "coaching, or personal reflection on that journey. Off-topic: unrelated news, politics, "
    "advertising/spam, or content with no connection to the health/fitness journey. "
    'Reply with ONLY a JSON object: {"on_topic": true|false, "confidence": 0.0-1.0}.'
)


def bedrock_offtopic_classifier(text: str) -> OfftopicResult:
    """Semantic off-topic verdict via Haiku on Bedrock — fail-closed at every seam.

    Budget-gated (`budget_guard`) and routed through the single `bedrock_client.invoke`
    chokepoint (ADR-062 — IAM auth, never a raw key). Any failure raises so
    :func:`classify_sensitivity` holds:
      * budget-paused → ``OfftopicResult(None, 0.0)`` (uncertain → hold)
      * Bedrock/parse error → the exception propagates (caught upstream → classifier_error)
    """
    try:
        import budget_guard

        if not budget_guard.allow(_BUDGET_FEATURE):
            return OfftopicResult(None, 0.0)  # paused → cannot vouch → hold
    except ImportError:  # pragma: no cover — budget_guard always bundled in prod
        pass

    import json

    import bedrock_client

    body = {
        "max_tokens": 60,
        "system": _OFFTOPIC_SYSTEM,
        "messages": [{"role": "user", "content": (text or "")[:4000]}],
    }
    resp = bedrock_client.invoke(body, model_name="haiku")
    raw = ""
    for block in resp.get("content") or []:
        if block.get("type") == "text":
            raw += block.get("text", "")
    parsed = json.loads(re.search(r"\{.*\}", raw, re.DOTALL).group(0))
    on_topic = parsed.get("on_topic")
    if not isinstance(on_topic, bool):
        return OfftopicResult(None, 0.0)  # unparseable verdict → uncertain → hold
    return OfftopicResult(on_topic, float(parsed.get("confidence", 0.0)))
