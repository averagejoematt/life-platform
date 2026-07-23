"""tests/test_broadcast_sensitivity_gate_1673.py — the fail-closed auto-publish gate (#1673).

Epic #1668 (The Social Membrane, inbound half). Decision (2) makes the Broadcast feed
(#1672, S4) automatic; this gate is what lets it be low-touch WITHOUT ever leaking a
sensitive post or auto-publishing Matthew's words blind (#1563). These tests pin the AC:

  * every flagged category (marijuana / porn / PII / off-topic) HOLDS (does not publish);
  * a clearly-safe post auto-publishes with no manual step;
  * error / low-confidence / no-classifier ⇒ HOLD (privacy_guard's fail-closed posture);
  * held posts are surfaced (with a recorded reason), never silently dropped;
  * auto-publish is reachable ONLY through the fail-closed filter (reconciles #1563);
  * the vice policy is DERIVED from privacy_guard (the canonical list), not ad-hoc.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import broadcast_sensitivity_gate as gate  # noqa: E402
import privacy_guard  # noqa: E402


# ── Injectable classifiers (the module is AWS-free; these stand in for Bedrock) ──────
def _on_topic(text):
    return gate.OfftopicResult(True, 0.95)


def _off_topic(text):
    return gate.OfftopicResult(False, 0.95)


def _uncertain(text):
    return gate.OfftopicResult(None, 0.0)


def _low_confidence(text):
    return gate.OfftopicResult(True, 0.1)


def _raises(text):
    raise RuntimeError("bedrock unavailable")


# ── AC: a clearly-safe post auto-publishes with no manual step ───────────────────────
def test_clearly_safe_post_auto_publishes():
    v = gate.classify_sensitivity("Leg day PR — 3x5 back squat at 225. Slept 8h, HRV up.", offtopic_classifier=_on_topic)
    assert v.status == gate.SENSITIVITY_CLEARED
    assert v.cleared
    assert v.categories == ()
    # The stamp a writer would persist — the seam #1672 reads.
    assert gate.sensitivity_attrs(v)[gate.STATUS_ATTR] == gate.SENSITIVITY_CLEARED


# ── AC: each flagged category HOLDS (a post with it does NOT auto-publish) ────────────
def test_marijuana_holds():
    # An on-topic classifier must NOT be able to rescue a vice hit — deterministic first.
    v = gate.classify_sensitivity("Recovery day. Tried an edible to sleep — marijuana helps.", offtopic_classifier=_on_topic)
    assert v.status == gate.SENSITIVITY_HELD
    assert gate.CATEGORY_MARIJUANA in v.categories


def test_porn_holds():
    v = gate.classify_sensitivity("Rest day thoughts on porn and dopamine.", offtopic_classifier=_on_topic)
    assert v.status == gate.SENSITIVITY_HELD
    assert gate.CATEGORY_PORN in v.categories


def test_pii_holds():
    for sensitive in (
        "Reach me at matthew@example.com",
        "call 415-555-0132 for the plan",
        "SSN 123-45-6789 on the form",
        "card 4111 1111 1111 1111 saved",
    ):
        v = gate.classify_sensitivity(sensitive, offtopic_classifier=_on_topic)
        assert v.status == gate.SENSITIVITY_HELD, sensitive
        assert gate.CATEGORY_PII in v.categories, sensitive


def test_off_topic_holds():
    v = gate.classify_sensitivity("Hot take on the election results and celebrity gossip.", offtopic_classifier=_off_topic)
    assert v.status == gate.SENSITIVITY_HELD
    assert gate.CATEGORY_OFF_TOPIC in v.categories


def test_every_flagged_category_is_covered():
    """The four AC-named categories all resolve to HOLD via a representative post."""
    cases = {
        gate.CATEGORY_MARIJUANA: ("weed after the workout", _on_topic),
        gate.CATEGORY_PORN: ("pornography discussion", _on_topic),
        gate.CATEGORY_PII: ("email me at a@b.com", _on_topic),
        gate.CATEGORY_OFF_TOPIC: ("unrelated political rant", _off_topic),
    }
    for category, (text, clf) in cases.items():
        v = gate.classify_sensitivity(text, offtopic_classifier=clf)
        assert v.status == gate.SENSITIVITY_HELD, category
        assert category in v.categories, category
    # And the module publishes exactly this policy list (referenced, not re-typed).
    assert set(gate.FLAGGED_CATEGORIES) == set(cases)


# ── AC: fail-closed posture (error / low-confidence / uncertain / no classifier) ─────
def test_classifier_error_holds():
    v = gate.classify_sensitivity("Perfectly clean training post.", offtopic_classifier=_raises)
    assert v.status == gate.SENSITIVITY_HELD
    assert gate.CATEGORY_CLASSIFIER_ERROR in v.categories


def test_low_confidence_holds():
    v = gate.classify_sensitivity("Ambiguous clean post.", offtopic_classifier=_low_confidence)
    assert v.status == gate.SENSITIVITY_HELD


def test_uncertain_verdict_holds():
    v = gate.classify_sensitivity("Ambiguous clean post.", offtopic_classifier=_uncertain)
    assert v.status == gate.SENSITIVITY_HELD


def test_no_classifier_holds():
    # With no off-topic classifier wired, a deterministically-clean post STILL holds —
    # off-topic relevance cannot be vouched for, so fail closed.
    v = gate.classify_sensitivity("Clean training post, no classifier available.")
    assert v.status == gate.SENSITIVITY_HELD
    assert gate.CATEGORY_OFF_TOPIC in v.categories


# ── AC: auto-publish reachable ONLY through the fail-closed filter (#1563) ────────────
def test_auto_publish_only_through_the_gate():
    """The ONLY route to a publishable state is: deterministically clean AND a confident
    on-topic verdict. Every other path (vice/PII hit, off-topic, uncertain, error, no
    classifier) holds — so nothing reaches the feed 'blind'."""
    # Deterministic hit cannot be overridden by a confident on-topic classifier.
    assert gate.classify_sensitivity("marijuana", offtopic_classifier=_on_topic).status == gate.SENSITIVITY_HELD
    # The read-side seam only admits an EXPLICIT cleared stamp.
    assert gate.is_cleared({gate.STATUS_ATTR: gate.SENSITIVITY_CLEARED})
    assert not gate.is_cleared({gate.STATUS_ATTR: gate.SENSITIVITY_HELD})
    assert not gate.is_cleared({})  # unstamped/unknown row is NOT publishable — fail-closed
    assert not gate.is_cleared({"origin": "human"})  # membrane-clean but ungated → still held


def test_cleared_filter_is_a_positive_match():
    """The feed FilterExpression selects '== cleared' (not '!= held'), so an unstamped or
    legacy row is excluded by construction — the fail-closed seam #1672 relies on."""
    posts = [
        {"post_id": "a", gate.STATUS_ATTR: gate.SENSITIVITY_CLEARED},
        {"post_id": "b", gate.STATUS_ATTR: gate.SENSITIVITY_HELD},
        {"post_id": "c"},  # unstamped
    ]
    assert [p["post_id"] for p in gate.filter_cleared(posts)] == ["a"]
    # The DDB expression reads back as an equality on the status attr == "cleared".
    ge = gate.cleared_filter_expression().get_expression()
    assert ge["operator"] == "="
    assert ge["values"][0].name == gate.STATUS_ATTR
    assert ge["values"][1] == gate.SENSITIVITY_CLEARED


# ── AC: held posts are surfaced to Matthew (not silently dropped); reason recorded ───
def test_held_post_is_surfaced_with_recorded_reason():
    v = gate.classify_sensitivity("smoked weed", offtopic_classifier=_on_topic)
    attrs = gate.sensitivity_attrs(v)
    # The reason and categories are persisted on the row → reviewable, not dropped.
    assert attrs[gate.STATUS_ATTR] == gate.SENSITIVITY_HELD
    assert attrs[gate.REASON_ATTR]
    assert gate.CATEGORY_MARIJUANA in attrs[gate.CATEGORIES_ATTR]

    held_row = {"post_id": "vid1", "channel": "youtube", "title": "t", "url": "u", **attrs}
    rec = gate.review_record(held_row)
    assert rec["post_id"] == "vid1"
    assert rec["status"] == gate.SENSITIVITY_HELD
    assert rec["reason"]
    assert gate.CATEGORY_MARIJUANA in rec["categories"]
    # The review-surface filter selects held rows (the inverse of the feed filter).
    he = gate.held_filter_expression().get_expression()
    assert he["operator"] == "<>"
    assert he["values"][0].name == gate.STATUS_ATTR


# ── AC: the vice policy is DERIVED from privacy_guard (canonical), not ad-hoc ─────────
def test_vice_policy_is_sourced_from_privacy_guard():
    """Every canonical privacy_guard vice keyword classifies to a flagged category — proof
    the marijuana/porn list is the canonical one (a superset of content_filter.json), not a
    second hand-rolled list that could silently drift narrower."""
    for kw in privacy_guard.VICE_KEYWORDS:
        v = gate.classify_sensitivity(f"a post mentioning {kw} here", offtopic_classifier=_on_topic)
        assert v.status == gate.SENSITIVITY_HELD, kw
        assert set(v.categories) & {gate.CATEGORY_MARIJUANA, gate.CATEGORY_PORN}, kw
    # A banned real public figure (privacy_guard's other guard) also holds — extra privacy.
    v = gate.classify_sensitivity("as Andrew Huberman says", offtopic_classifier=_on_topic)
    assert v.status == gate.SENSITIVITY_HELD
    assert gate.CATEGORY_REAL_NAME in v.categories


# ── The production Bedrock classifier is fail-closed at the budget seam ───────────────
def test_bedrock_classifier_holds_when_budget_paused(monkeypatch):
    import budget_guard

    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    res = gate.bedrock_offtopic_classifier("any text")
    # Budget-paused → uncertain (on_topic None, confidence 0) → classify_sensitivity holds.
    assert res.on_topic is None
    assert gate.classify_sensitivity("clean", offtopic_classifier=gate.bedrock_offtopic_classifier).status == gate.SENSITIVITY_HELD
