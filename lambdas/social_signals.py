"""social_signals.py — route enriched social posts to the right coach surface (#1671).

S3 of The Social Membrane (epic #1668). Ingested (#1669) + membrane-stamped (#1670)
social posts are inert until they become coach signal. They must ride the SAME
journal→enrichment→coach path as the Notion journal — "no second pipeline" (the #1572
4th-channel principle, docs/coaching/CHAT_MODES.md) — and reach the coach who can read
them:

  * a training-flavoured post (a lift, a ruck, an RPE, a Zone-2 session) → the
    training / domain coach;
  * a reflective post → the journal / Mind coach.

This module is the PURE, deterministic router over the exact ``enriched_*`` fields the
journal enricher already produces. It is AWS-free and side-effect-free so the routing
decision is exhaustively unit-testable without Bedrock, DynamoDB, or the network — the
enricher computes a post's route ONCE at enrichment time and persists it as
``enriched_coach_route``; the coach surfaces (ai_context._build_training_data /
_build_mind_data) read that field back (falling through to this classifier when a legacy
record predates it).

v1.0.0 — 2026-07-22 (#1671, epic #1668)
"""

from __future__ import annotations

# ── The two coach routes ────────────────────────────────────────────────────────
ROUTE_TRAINING = "training"  # training / domain coach
ROUTE_MIND = "mind"  # journal / Mind coach (the reflective default)
VALID_ROUTES = frozenset({ROUTE_TRAINING, ROUTE_MIND})

# Training-flavoured hints matched against the enriched themes/behaviors/entities blob.
# Deliberately concrete training vocabulary — a reflective post about "work stress" must
# NOT be pulled into the training bucket, so no generic wellness words here.
_TRAINING_HINTS = (
    "workout",
    "training",
    "lift",
    "lifting",
    "squat",
    "deadlift",
    "bench",
    "press",
    "curl",
    "row",
    "gym",
    "rep",
    "reps",
    "set ",
    "sets",
    "pr ",
    " pr",
    "rpe",
    "zone 2",
    "zone2",
    "cardio",
    "strength",
    "mobility",
    "ruck",
    "run",
    "running",
    "ride",
    "cycling",
    "swim",
    "hike",
    "hiking",
    "walk",
    "steps",
    "leg day",
    "push day",
    "pull day",
    "hypertrophy",
    "conditioning",
    "interval",
    "sprint",
    "marathon",
    "5k",
    "10k",
)

# The enrichment dict straight off Haiku uses bare keys; a persisted DDB record uses the
# ``enriched_`` prefixed keys. The router accepts either shape by checking both.
_EXERCISE_KEYS = ("exercise_context", "enriched_exercise_context")
_LIST_KEYS = (
    ("themes", "enriched_themes"),
    ("behaviors", "enriched_behaviors"),
    ("entities", "enriched_entities"),
)


def _first(enriched: dict, keys) -> object:
    for k in keys:
        v = (enriched or {}).get(k)
        if v:
            return v
    return None


def _text_blob(enriched: dict) -> str:
    """Lower-cased join of the routable text signals (themes/behaviors/entities)."""
    parts: list[str] = []
    for bare, prefixed in _LIST_KEYS:
        vals = (enriched or {}).get(bare) or (enriched or {}).get(prefixed) or []
        if isinstance(vals, str):
            vals = [vals]
        parts.extend(str(v) for v in vals)
    return " ".join(parts).lower()


def classify_coach_route(enriched: dict) -> str:
    """Deterministically route an enriched social post to ``training`` or ``mind``.

    Rules (in order):
      1. An ``exercise_context`` present (the enricher only fills it for a workout) → the
         post is unambiguously training.
      2. Any concrete training keyword in the themes/behaviors/entities blob → training.
      3. Otherwise the post is reflective → the Mind coach (the default).

    Accepts both the raw Haiku enrichment dict (bare keys) and a persisted DDB record
    (``enriched_`` keys). A pure function of its argument — no AWS, no I/O.
    """
    if _first(enriched, _EXERCISE_KEYS):
        return ROUTE_TRAINING
    blob = _text_blob(enriched)
    if any(hint in blob for hint in _TRAINING_HINTS):
        return ROUTE_TRAINING
    return ROUTE_MIND


def coach_route_of(record: dict) -> str:
    """Route for a persisted post: the stamped ``enriched_coach_route`` if valid, else
    (legacy/unstamped record) fall through to the live classifier."""
    stamped = (record or {}).get("enriched_coach_route")
    if stamped in VALID_ROUTES:
        return stamped
    return classify_coach_route(record)
