"""tests/test_circadian_public_journal_free.py — /api/circadian never moves with the journal.

Owner ruling 2026-11-03: journal activity, and anything derived from it, is private on public
surfaces, including structured data and indirect inference. The circadian score read two anchors
from the private journal (morning light and the evening wind-down), so its public score, anchor
count, notes and priority moved with whether and what he wrote. The producer now writes a
journal-free ``public`` block and the route serves only that block.

The inference test varies ONLY the journal (synthetic entries, no real text) and asserts the public
block is byte-identical; the mutation control proves the full record does move, so the test can fail.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

import circadian_compliance_lambda as cc  # noqa: E402
from web import site_api_sleep  # noqa: E402

DAY = "2026-07-10"
# Synthetic entries that trip both journal scorers (keywords only, never real text).
JOURNALS = {
    "none": [],
    "morning": [{"template": "morning", "raw_text": "synthetic: sunlight walk"}],
    "evening_screens": [{"template": "evening", "raw_text": "synthetic: scrolling"}],
    "evening_quiet": [{"template": "evening", "raw_text": "synthetic: book"}],
    "both": [
        {"template": "morning", "raw_text": "synthetic: sunrise outside"},
        {"template": "evening", "raw_text": "synthetic: no phone"},
    ],
}


def _world(monkeypatch, journal, *, strava=None):
    monkeypatch.setattr(cc, "fetch_journal_today", lambda d: journal)

    def _src(src, d):
        if src == "macrofactor":
            return {"food_log": [{"logged_at": "20:30"}]}
        if src == "strava":
            return strava
        return None

    monkeypatch.setattr(cc, "fetch_source_date", _src)
    monkeypatch.setattr(cc, "fetch_range", lambda src, s, e: [{"sleep_start": "22:00"} for _ in range(8)])


def _canon(obj):
    return json.dumps(obj, sort_keys=True, default=str)


def _results(monkeypatch, **kw):
    out = {}
    for name, journal in JOURNALS.items():
        _world(monkeypatch, journal, **kw)
        out[name] = cc.compute_circadian_score(DAY)
    return out


def test_public_block_is_byte_identical_across_journal_activity(monkeypatch):
    for strava in (None, {"activities": [{"sport_type": "Walk", "start_date_local": "2026-07-10T07:15:00"}]}):
        results = _results(monkeypatch, strava=strava)
        publics = {name: _canon(r["public"]) for name, r in results.items()}
        assert len(set(publics.values())) == 1, publics


def test_mutation_control_the_full_record_moves_with_the_journal(monkeypatch):
    results = _results(monkeypatch)
    fulls = {_canon({k: v for k, v in r.items() if k != "public"}) for r in results.values()}
    assert len(fulls) > 1  # the private record does read the journal, so the test above can fail


def test_public_block_omits_journal_only_anchors_and_never_names_the_journal(monkeypatch):
    for r in _results(monkeypatch).values():
        pub = r["public"]
        assert set(pub["components"]) == {"morning_light", "meal_timing", "sleep_consistency"}
        assert not (cc.JOURNAL_ONLY_ANCHORS & set(pub["components"]))
        assert "journal" not in _canon(pub).lower()


def test_store_writes_the_public_block(monkeypatch):
    _world(monkeypatch, JOURNALS["both"])
    written = {}
    monkeypatch.setattr(cc.table, "put_item", lambda Item: written.update(Item))
    cc.store_circadian_score(cc.compute_circadian_score(DAY))
    assert set(written["public"]["components"]) == {"morning_light", "meal_timing", "sleep_consistency"}


def _serve(item):
    return json.loads(site_api_sleep.circadian(_g={"_latest_item": lambda src: item})["body"])


def test_route_fails_closed_on_a_record_without_a_public_block():
    legacy = {"date": DAY, "score": 80, "components": {"screen_wind_down": {"score": 25, "note": "x"}}}
    body = _serve(legacy)
    assert body["available"] is False
    assert "score" not in body and "components" not in body


def test_route_serves_only_the_public_block(monkeypatch):
    _world(monkeypatch, JOURNALS["both"])
    result = cc.compute_circadian_score(DAY)
    item = dict(result, public=result["public"])
    body = _serve(item)
    assert body["available"] is True
    assert body["score"] == result["public"]["score"]
    assert set(body["components"]) == {"morning_light", "meal_timing", "sleep_consistency"}
    assert "journal" not in _canon(body).lower()
