"""tests/test_coaches_api.py — CC-01/CC-02 site-api roster + coach page.

Offline structural tests: DynamoDB reads fail and fall through to the
shaped-empty paths, while persona_registry / coach_stance fall back to the local
config files — so we can assert the response *shape* (roster fields, stance rung
resolution, report-card scaffold, honesty caveats) without AWS.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from web import site_api_coach as api  # noqa: E402


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


# ── roster (/api/coaches) ────────────────────────────────────────────────────


def test_roster_returns_eight_coaches():
    data = _body(api.handle_coaches({}))
    assert data["count"] == 8
    ids = [c["persona_id"] for c in data["coaches"]]
    assert ids == api.persona_registry.OPERATIONAL_COACH_IDS  # registry order preserved
    for c in data["coaches"]:
        for f in ("name", "domain", "short_bio", "emoji", "board_role", "headline_stat"):
            assert c.get(f), f"{c['persona_id']} missing {f}"
    assert "AI character" in data["disclosure"]


def test_roster_headline_is_honest_pre_data():
    data = _body(api.handle_coaches({}))
    # no predictions decided yet -> every coach reads "accruing", never a fake rate
    assert all(c["headline_stat"] == "track record accruing" for c in data["coaches"])


# ── coach page (/api/coach/{id}) ─────────────────────────────────────────────


def test_coach_page_shape_and_stance_rung():
    resp = api.handle_coach({"rawPath": "/api/coach/sleep_coach"})
    data = _body(resp)
    assert data["persona_id"] == "sleep_coach"
    assert data["name"] == "Dr. Lisa Park"
    assert "AI character" in data["disclosure"]
    # stance resolves to the entry rung from the baseline weight (~306 -> foundation)
    assert data["stance"]["band_metric"] == "weight_lbs"
    assert data["stance"]["rung"]["stage_id"] == "foundation"
    assert data["stance"]["ladder"]  # full ladder surfaced for the page
    # report card scaffold present + honest caveats (CC-02 / ER-05)
    rc = data["report_card"]
    assert rc["track_record"]["hit_rate_pct"] is None  # pre-data
    assert rc["track_record"]["preliminary"] is True
    assert "self-assessment" in rc["track_record"]["caveat"].lower()
    assert "self-assessment" in rc["quality_trend"]["caveat"].lower()
    assert "tuning_log" in rc
    # voice + relationships keys present (content may be empty offline)
    assert set(["decision_style", "structural_voice_rules", "few_shot_example"]) <= set(data["voice"])
    assert set(["leans_on", "leaned_on_by"]) <= set(data["relationships"])


def test_coach_page_id_via_query_param():
    data = _body(api.handle_coach({"queryStringParameters": {"id": "training_coach"}}))
    assert data["persona_id"] == "training_coach"
    assert data["stance"]["rung"]["stage_id"] == "foundation"


def test_nutrition_coach_resolves_entry_rung_without_data():
    # nutrition bands on logging_consistency (None pre-data) -> entry rung 'visibility'
    data = _body(api.handle_coach({"rawPath": "/api/coach/nutrition_coach"}))
    assert data["stance"]["band_metric"] == "logging_consistency"
    assert data["stance"]["rung"]["stage_id"] == "visibility"


def test_unknown_coach_404():
    resp = api.handle_coach({"rawPath": "/api/coach/not_a_coach"})
    assert resp["statusCode"] == 404
    # a board-only persona is not an operational coach
    resp2 = api.handle_coach({"rawPath": "/api/coach/the_chair"})
    assert resp2["statusCode"] == 404
