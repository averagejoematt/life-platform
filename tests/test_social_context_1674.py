"""tests/test_social_context_1674.py — contextual social embeds (#1674, epic #1668, S6).

Proves the acceptance criteria against the actual code (offline, fakes only):

  AC1  a post whose enriched fields route to "training" (exercise_context, or a concrete
       training keyword) surfaces via GET /api/social_context?route=training.
  AC2  a reflective post routes to "mind" and surfaces via ?route=mind.
  AC3  only origin:human + sensitivity-cleared posts are eligible — a held (uncleared) or
       platform-origin post never surfaces contextually, even when its content would
       otherwise route to the requested surface.
  AC4  facade cards only (thumbnail + caption + link-out) — the same shape /api/broadcast
       already emits, so this is a pure narrowing, never a second card format. No iframe,
       no CSP-relevant field.
  AC5  an unenriched post (no enriched_at) never surfaces contextually — it stays in the
       general broadcast feed rather than being guessed into a topic page.
  AC6  route is a required, closed enum — an invalid/missing route 400s rather than
       silently returning an empty or unfiltered list.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_social as social  # noqa: E402


class _FakeTable:
    def __init__(self, items):
        self._items = items

    def query(self, **kw):
        return {"Items": list(self._items)}


def _event(route=None):
    qs = {"route": route} if route is not None else {}
    return {"queryStringParameters": qs}


def _body(resp):
    return json.loads(resp["body"])


def _row(
    post_id,
    *,
    origin="human",
    sensitivity="cleared",
    enriched_at="2026-08-01T00:00:00Z",
    themes=None,
    exercise_context=None,
    coach_route=None,
    title="a post",
):
    row = {
        "sk": f"DATE#2026-08-0{post_id}#{post_id}",
        "date": f"2026-08-0{post_id}",
        "post_id": post_id,
        "channel": "youtube",
        "title": title,
        "description": "",
        "thumbnail_url": f"https://img.example/{post_id}.jpg",
        "url": f"https://youtube.com/{post_id}",
        "origin": origin,
        "sensitivity_status": sensitivity,
    }
    if enriched_at is not None:
        row["enriched_at"] = enriched_at
    if themes is not None:
        row["enriched_themes"] = themes
    if exercise_context is not None:
        row["enriched_exercise_context"] = exercise_context
    if coach_route is not None:
        row["enriched_coach_route"] = coach_route
    return row


# ── AC6: route is a required closed enum ──────────────────────────────────────────────


def test_missing_route_400s(monkeypatch):
    monkeypatch.setattr(social, "table", _FakeTable([]))
    resp = social._handle_social_context(_event())
    assert resp["statusCode"] == 400


def test_invalid_route_400s(monkeypatch):
    monkeypatch.setattr(social, "table", _FakeTable([]))
    resp = social._handle_social_context(_event("cooking"))
    assert resp["statusCode"] == 400


# ── AC1/AC2: training and reflective posts route to their own surface ─────────────────


def test_training_post_surfaces_on_training_route(monkeypatch):
    rows = [
        _row(1, exercise_context={"sport": "lifting"}),  # unambiguous training
        _row(2, themes=["gratitude", "work stress"]),  # reflective
    ]
    monkeypatch.setattr(social, "table", _FakeTable(rows))
    body = _body(social._handle_social_context(_event("training")))
    assert body["route"] == "training"
    assert body["total"] == 1
    assert body["items"][0]["id"] == "1"


def test_reflective_post_surfaces_on_mind_route(monkeypatch):
    rows = [
        _row(1, exercise_context={"sport": "lifting"}),
        _row(2, themes=["gratitude", "work stress"]),
    ]
    monkeypatch.setattr(social, "table", _FakeTable(rows))
    body = _body(social._handle_social_context(_event("mind")))
    assert body["route"] == "mind"
    assert body["total"] == 1
    assert body["items"][0]["id"] == "2"


def test_stamped_coach_route_is_honored_over_reclassification(monkeypatch):
    # enriched_coach_route is the persisted, authoritative stamp (#1671) — a row that
    # carries it should route on the stamp, not a live re-classification of its content.
    rows = [_row(1, themes=["squat", "deadlift"], coach_route="mind")]
    monkeypatch.setattr(social, "table", _FakeTable(rows))
    training_body = _body(social._handle_social_context(_event("training")))
    mind_body = _body(social._handle_social_context(_event("mind")))
    assert training_body["total"] == 0
    assert mind_body["total"] == 1


# ── AC3: only origin:human + sensitivity-cleared posts are eligible ───────────────────


def test_held_post_never_surfaces_contextually(monkeypatch):
    rows = [_row(1, exercise_context={"sport": "lifting"}, sensitivity="pending")]
    monkeypatch.setattr(social, "table", _FakeTable(rows))
    body = _body(social._handle_social_context(_event("training")))
    assert body["total"] == 0


def test_platform_origin_post_never_surfaces_contextually(monkeypatch):
    rows = [_row(1, exercise_context={"sport": "lifting"}, origin="platform")]
    monkeypatch.setattr(social, "table", _FakeTable(rows))
    body = _body(social._handle_social_context(_event("training")))
    assert body["total"] == 0


def test_unstamped_sensitivity_fails_closed(monkeypatch):
    row = _row(1, exercise_context={"sport": "lifting"})
    del row["sensitivity_status"]
    monkeypatch.setattr(social, "table", _FakeTable([row]))
    body = _body(social._handle_social_context(_event("training")))
    assert body["total"] == 0


# ── AC5: an unenriched post never surfaces contextually ───────────────────────────────


def test_unenriched_post_never_surfaces_contextually(monkeypatch):
    row = _row(1, exercise_context={"sport": "lifting"}, enriched_at=None)
    monkeypatch.setattr(social, "table", _FakeTable([row]))
    training_body = _body(social._handle_social_context(_event("training")))
    mind_body = _body(social._handle_social_context(_event("mind")))
    assert training_body["total"] == 0
    assert mind_body["total"] == 0
    # But it IS still visible on the general broadcast feed — enrichment gates
    # contextual ROUTING only, never the membrane feed itself.
    broadcast_body = _body(social.handle_broadcast())
    assert broadcast_body["total"] == 1


# ── AC4: facade card shape — the same reduce as /api/broadcast, no iframe field ───────


def test_card_shape_is_the_broadcast_facade_shape(monkeypatch):
    rows = [_row(1, exercise_context={"sport": "lifting"}, title="Leg day")]
    monkeypatch.setattr(social, "table", _FakeTable(rows))
    body = _body(social._handle_social_context(_event("training")))
    card = body["items"][0]
    assert set(card.keys()) == {"id", "date", "channel", "caption", "excerpt", "thumbnail_url", "link_out", "permalink"}
    assert card["caption"] == "Leg day"
    assert card["link_out"] == "https://youtube.com/1"
    assert "iframe" not in json.dumps(card).lower()


# ── The membrane row-fetch is shared, not duplicated, between broadcast + context ─────


def test_broadcast_and_context_share_one_membrane_query(monkeypatch):
    calls = []
    rows = [_row(1, exercise_context={"sport": "lifting"})]
    ft = _FakeTable(rows)
    real_query = ft.query
    ft.query = lambda **kw: (calls.append(kw), real_query(**kw))[1]
    monkeypatch.setattr(social, "table", ft)
    social.handle_broadcast()
    social._handle_social_context(_event("training"))
    # One table.query per source, per call — both call sites go through
    # _membrane_visible_rows, not a second hand-rolled query.
    assert len(calls) == len(social._BROADCAST_SOURCES) * 2
