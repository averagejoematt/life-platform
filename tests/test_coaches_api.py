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

import budget_guard  # noqa: E402
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


# ── My Team (/api/coach_team, CC-10) ─────────────────────────────────────────


def test_team_view_shape():
    data = _body(api.handle_coach_team({}))
    assert len(data["huddle"]) == 8
    for c in data["huddle"]:
        assert c.get("name") and c.get("headline") and c.get("stage_id")
        assert "watch" in c
    assert data["team_focus"] and len(data["team_focus"]) == len(set(data["team_focus"]))
    assert isinstance(data["tensions"], list)  # honest empty pre-data, never an error
    assert "AI character" in data["disclosure"]


def test_team_stage_mix_is_honest():
    data = _body(api.handle_coach_team({}))
    stages = {c["persona_id"]: c["stage_id"] for c in data["huddle"]}
    # weight-banded coaches sit at 'foundation' from the baseline; nutrition
    # (logging consistency) sits at 'visibility' — so not all on one stage label.
    assert stages["training_coach"] == "foundation"
    assert stages["nutrition_coach"] == "visibility"
    assert data["all_same_stage"] is False


# ── predictions (/api/predictions, R22-BUG-03 #819) ──────────────────────────


def test_predictions_overall_accuracy_pct_null_when_nothing_resolved(monkeypatch):
    class _EmptyTable:
        def query(self, **kw):
            return {"Items": []}

    monkeypatch.setattr(api, "table", _EmptyTable())
    data = _body(api.handle_predictions({}))
    o = data["overall"]
    assert o["decided"] == 0
    # ADR-104: an unearned 0% would read as "the board is bad at this" when in
    # truth nothing has graded yet — must be an honest absence, not a fabricated zero.
    assert o["accuracy_pct"] is None


def test_predictions_overall_accuracy_pct_rounds_when_some_resolved(monkeypatch):
    calls = []

    class _FakeTable:
        def query(self, **kw):
            calls.append(kw)
            # scan_coaches iterates in a fixed order (sleep first) — hand the first
            # coach queried a mix of graded calls, every other coach comes back empty.
            if len(calls) == 1:
                return {
                    "Items": [
                        {"status": "confirmed", "created_date": "2026-07-01", "claim_natural": "a"},
                        {"status": "confirmed", "created_date": "2026-07-02", "claim_natural": "b"},
                        {"status": "confirmed", "created_date": "2026-07-03", "claim_natural": "c"},
                        {"status": "refuted", "created_date": "2026-07-04", "claim_natural": "d"},
                        {"status": "pending", "created_date": "2026-07-05", "claim_natural": "e"},
                    ]
                }
            return {"Items": []}

    monkeypatch.setattr(api, "table", _FakeTable())
    data = _body(api.handle_predictions({}))
    o = data["overall"]
    assert o["confirmed"] == 3
    assert o["refuted"] == 1
    assert o["decided"] == 4
    assert o["accuracy_pct"] == 75.0


# ── /api/coach_analysis regeneration-paused disclosure (#802, R22-CONTENT-03) ─
# coach_narrative_orchestrator skips a coach's OUTPUT# write entirely at budget
# tier >= 2 — a served analysis can be a HELD read from before the pause. The
# endpoint now carries `regeneration_paused`, derived from budget_guard's
# "coach_narrative" feature cutoff, alongside the existing `generated_at`.


def _fake_query_first_call_only(item):
    """table.query stub: the first call (the OUTPUT# lookup) returns `item`;
    every later call (threads/ensemble/computation/learning, each individually
    try/except-wrapped in handle_coach_analysis) raises, exercising the
    fail-soft fallback for those secondary reads."""
    calls = {"n": 0}

    def _query(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"Items": [item]}
        raise RuntimeError("offline test — no secondary reads")

    return _query


def test_coach_analysis_flags_regeneration_paused_at_tier_2(monkeypatch):
    out_item = {
        "pk": "COACH#sleep_coach",
        "sk": "OUTPUT#2026-06-29",
        "content": "the analysis text",
        "generated_at": "2026-06-29T14:00:00Z",
    }
    monkeypatch.setattr(api.table, "query", _fake_query_first_call_only(out_item))
    monkeypatch.setattr(api.table, "get_item", lambda Key: {})
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    data = _body(api.handle_coach_analysis({"queryStringParameters": {"domain": "sleep"}}))
    assert data["analysis"] == "the analysis text"
    assert data["regeneration_paused"] is True


def test_coach_analysis_not_paused_at_tier_0(monkeypatch):
    out_item = {
        "pk": "COACH#sleep_coach",
        "sk": "OUTPUT#2026-06-29",
        "content": "the analysis text",
        "generated_at": "2026-06-29T14:00:00Z",
    }
    monkeypatch.setattr(api.table, "query", _fake_query_first_call_only(out_item))
    monkeypatch.setattr(api.table, "get_item", lambda Key: {})
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    data = _body(api.handle_coach_analysis({"queryStringParameters": {"domain": "sleep"}}))
    assert data["regeneration_paused"] is False
