"""tests/test_site_api_reading.py — public reading endpoints (Phase C).

Proves the public surface goes through the visibility chokepoint: a populated
book with PRIVATE fields (retentionScore, etc.) must never appear in the
endpoint payload. Honest empty states when there's no reading data.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from reading import reading_store as rs  # noqa: E402
from reading_fakes import FakeTable  # noqa: E402
from web import site_api_reading as sar  # noqa: E402


@pytest.fixture(autouse=True)
def fake_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(rs, "table", t)
    return t


def _body(resp):
    return json.loads(resp["body"])


def test_empty_shelf_is_honest():
    resp = sar.handle_reading_shelf()
    body = _body(resp)
    assert body["reading"] == [] and body["finished"] == [] and body["set_down"] == []
    assert body["counts"]["finished"] == 0


def test_shelf_joins_book_and_state_public_only():
    bid = rs.add_book(
        {"title": "Klara and the Sun", "author": "Ishiguro", "domainTags": ["fiction"]}, initial_status="reading", enricher=lambda m: {}
    )
    # stamp a PRIVATE field on the state — it must NOT leak
    rs.put_reading_state(bid, "reading", fields={"retentionScore": 0.9, "lastProbeAt": "2026-07-01", "rating": 5})
    body = _body(sar.handle_reading_shelf())
    assert len(body["reading"]) == 1
    item = body["reading"][0]
    assert item["book"]["title"] == "Klara and the Sun"
    assert item["state"]["status"] == "reading"
    # the proof: private fields are gone from the public payload
    blob = json.dumps(body)
    assert "retentionScore" not in blob and "lastProbeAt" not in blob and "0.9" not in blob


def test_recall_and_retention_never_in_overview():
    bid = rs.add_book({"title": "T", "author": "A"}, initial_status="reading", enricher=lambda m: {})
    rs.put_recall(bid, prompt_id="p1", prompt="what stuck?", next_due="2026-06-01T00:00:00")
    rs.put_reading_state(bid, "reading", fields={"retentionScore": 0.4})
    blob = json.dumps(_body(sar.handle_reading_overview()))
    assert "what stuck" not in blob and "retentionScore" not in blob and "RECALL" not in blob


def test_overview_wheel_and_streak():
    b1 = rs.add_book({"title": "F", "author": "A", "domainTags": ["fiction"]}, enricher=lambda m: {})
    rs.update_reading_status(b1, "finished")
    rs.log_session(b1, minutes=20, date=sar._today())
    body = _body(sar.handle_reading_overview())
    assert body["wheel"]["distribution"].get("fiction") == 1
    assert body["stats"]["read_today"] is True
    assert body["stats"]["input_streak_days"] >= 1


def test_overview_profile_exposes_only_wheel():
    rs.put_profile({"wheelDistribution": {"fiction": 2}, "tasteHypothesis": "secret", "trustLadderMode": "propose"})
    body = _body(sar.handle_reading_overview())
    assert body["profile"] == {"wheelDistribution": {"fiction": 2}}
    assert "secret" not in json.dumps(body)
