"""tests/test_social_enrichment_1671.py — social post enrichment → coach signal (#1671, epic #1668).

S3 of The Social Membrane. Proves the four load-bearing invariants of the enrichment
Lambda + its coach-surface consumption, all offline (no Bedrock, no DynamoDB):

  1. THE MEMBRANE (S2/#1670): only origin:human posts enter enrichment — an origin:platform
     echo NEVER reaches the Haiku call (asserted both as a pure filter and at the handler).
  2. GROUNDING (ADR-104): the reused deterministic gate drops a causal hint whose quote is
     not verbatim in the post text.
  3. ROUTING by enriched content: a training-flavoured post routes to the training coach,
     a reflective post to Mind, and an exercise_context forces training.
  4. CONSUMPTION with channel provenance: apply_enrichment stamps channel + coach route on
     the record, and the existing coach surfaces (ai_context) surface the routed signals —
     no second pipeline.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("SOCIAL_CHANNELS", "youtube")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "ingestion"))

import ai_context  # noqa: E402
import social_enrichment_lambda as se  # noqa: E402
import social_signals as sig  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────────
def _post(post_id, origin="human", title="", description="", **extra):
    p = {
        "pk": "USER#matthew#SOURCE#youtube",
        "sk": f"DATE#2026-07-20#{post_id}",
        "post_id": post_id,
        "channel": "youtube",
        "source": "youtube",
        "origin": origin,
        "date": "2026-07-20",
        "title": title,
        "description": description,
    }
    p.update(extra)
    return p


_HUMAN = _post("AAA", title="Leg day, week 3", description="Squats and a long walk. Felt strong today.")
_PLATFORM = _post("BBB", origin="platform", title="New dashboard is live", description="Full write-up at averagejoematt.com")


# ── 1. THE MEMBRANE ───────────────────────────────────────────────────────────────
def test_select_enrichable_excludes_platform_origin():
    kept = se.select_enrichable([_HUMAN, _PLATFORM])
    assert [p["post_id"] for p in kept] == ["AAA"]  # the platform echo is filtered out


def test_select_enrichable_keeps_unstamped_legacy_as_human():
    legacy = _post("CCC")
    del legacy["origin"]  # a legacy/unstamped row is human, not a platform echo
    assert se.select_enrichable([legacy]) == [legacy]


def test_platform_post_never_reaches_haiku(monkeypatch):
    """Handler-level: a platform-origin post is excluded BEFORE any Haiku call."""
    seen_texts = []

    monkeypatch.setattr(se, "query_channel_posts", lambda ch, s, e: [_HUMAN, _PLATFORM])
    monkeypatch.setattr(
        se, "call_haiku", lambda text, channel, date: (seen_texts.append(text) or {"themes": ["consistency"], "sentiment": "positive"})
    )
    monkeypatch.setattr(se, "apply_enrichment", lambda item, enrichment: True)

    resp = se.lambda_handler({"date": "2026-07-20", "channels": ["youtube"]}, None)
    import json

    body = json.loads(resp["body"])
    assert body["platform_excluded"] == 1
    assert body["enriched"] == 1
    # The platform post's text (its self-backlink description) must never have been extracted.
    assert not any("averagejoematt.com" in t for t in seen_texts)
    assert any("Squats" in t for t in seen_texts)


# ── 2. GROUNDING GATE (ADR-104, reused from journal_enrichment) ───────────────────
def test_grounding_drops_ungrounded_causal_hint():
    text = "Squats and a long walk. Felt strong today."
    hints = [
        {"cause": "walk", "effect": "felt strong", "quote": "Felt strong today."},  # grounded (verbatim)
        {"cause": "coffee", "effect": "energy", "quote": "The coffee gave me energy."},  # NOT in the post
    ]
    kept, dropped = se._ground_causal_hints(hints, text)
    assert dropped == 1
    assert [h["cause"] for h in kept] == ["walk"]


def test_apply_enrichment_runs_grounding_before_write(monkeypatch):
    captured = {}
    monkeypatch.setattr(se.table, "update_item", lambda **kw: captured.update(kw))
    enrichment = {
        "themes": ["physical achievement"],
        "sentiment": "positive",
        "causal_hints": [{"cause": "x", "effect": "y", "quote": "not present anywhere"}],
    }
    se.apply_enrichment(_HUMAN, enrichment)
    # The ungrounded hint was dropped → no enriched_causal_hints written.
    assert ":causal_hints" not in captured["ExpressionAttributeValues"]


# ── 3. ROUTING by enriched content ─────────────────────────────────────────────────
def test_route_training_from_exercise_context():
    assert sig.classify_coach_route({"exercise_context": "felt strong on squats"}) == sig.ROUTE_TRAINING


def test_route_training_from_theme_keyword():
    assert sig.classify_coach_route({"themes": ["a hard workout"], "behaviors": []}) == sig.ROUTE_TRAINING


def test_route_mind_for_reflective_post():
    assert sig.classify_coach_route({"themes": ["gratitude", "family connection"]}) == sig.ROUTE_MIND


def test_coach_route_of_prefers_stamped_then_falls_through():
    assert sig.coach_route_of({"enriched_coach_route": "mind", "enriched_exercise_context": "squats"}) == "mind"
    # legacy record, no stamp → live classify from enriched content
    assert sig.coach_route_of({"enriched_exercise_context": "squats"}) == sig.ROUTE_TRAINING


# ── 4. CHANNEL PROVENANCE + coach route stamped on the record ──────────────────────
def test_apply_enrichment_stamps_channel_and_route(monkeypatch):
    captured = {}
    monkeypatch.setattr(se.table, "update_item", lambda **kw: captured.update(kw))
    se.apply_enrichment(_HUMAN, {"exercise_context": "felt strong", "themes": ["physical achievement"], "sentiment": "positive"})
    vals = captured["ExpressionAttributeValues"]
    assert vals[":ec"] == "youtube"  # channel provenance
    assert vals[":ecr"] == "training"  # routed by the exercise_context
    assert vals[":enriched_exercise_context"] == "felt strong"


# ── 5. CONSUMPTION by the existing coach surfaces (no second pipeline) ─────────────
def _enriched(origin, route, **fields):
    base = {"origin": origin, "enriched_at": "2026-07-20T18:00:00+00:00", "enriched_coach_route": route}
    base.update(fields)
    return base


def test_coach_surfaces_consume_routed_social_signals():
    data = {
        "social_posts": [
            _enriched("human", "training", enriched_exercise_context="strong squats", enriched_themes=["physical achievement"]),
            _enriched("human", "mind", enriched_sentiment="positive", enriched_themes=["gratitude"], enriched_entities=["the platform"]),
            _enriched("platform", "mind", enriched_sentiment="negative", enriched_themes=["should never appear"]),  # membrane
        ]
    }
    training = ai_context._build_training_data(data)
    assert training["social_post_count"] == 1
    assert "strong squats" in training["social_exercise_context"]

    mind = ai_context._build_mind_data(data)
    assert mind["social_post_count"] == 1  # platform echo excluded read-side
    assert mind["social_sentiment"] == "positive"
    assert "gratitude" in mind["social_enriched_themes"]
    assert "should never appear" not in mind["social_enriched_themes"]


def test_coach_surfaces_no_social_posts_is_safe():
    training = ai_context._build_training_data({})
    mind = ai_context._build_mind_data({})
    assert training["social_post_count"] == 0
    assert mind["social_post_count"] == 0
