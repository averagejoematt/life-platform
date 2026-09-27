"""tests/test_coaches_api.py — CC-01/CC-02 site-api roster + coach page.

Offline structural tests: DynamoDB reads fail and fall through to the
shaped-empty paths, while persona_registry / coach_stance fall back to the local
config files — so we can assert the response *shape* (roster fields, stance rung
resolution, report-card scaffold, honesty caveats) without AWS.
"""

import json
import os
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from ai import budget_guard  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as api  # noqa: E402
from web.site_api_common import EXPERIMENT_START  # noqa: E402


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


# ── roster (/api/coaches) ────────────────────────────────────────────────────


def test_roster_returns_lead_plus_staff():
    # #1112: the head coach leads the roster (lead tier), then the operational
    # coaches in registry order (7 since the 2026-08-10 retirement).
    data = _body(api.handle_coaches({}))
    staff_n = len(api.persona_registry.OPERATIONAL_COACH_IDS)
    assert data["count"] == 1 + staff_n
    ids = [c["persona_id"] for c in data["coaches"]]
    assert ids == [api.persona_registry.LEAD_PERSONA_ID] + api.persona_registry.OPERATIONAL_COACH_IDS
    assert [c["tier"] for c in data["coaches"]] == ["lead"] + ["staff"] * staff_n
    for c in data["coaches"]:
        for f in ("name", "domain", "short_bio", "emoji", "board_role", "headline_stat"):
            assert c.get(f), f"{c['persona_id']} missing {f}"
    assert "AI character" in data["disclosure"]


def test_roster_headline_is_honest_pre_data(monkeypatch):
    # #4220: no checked call yet -> every staff coach says so in words, never a fake
    # rate and never a zero record — and the lead never carries a track-record line at
    # all (he makes no graded calls; his headline is his role).
    monkeypatch.setattr(api, "table", FakeDdbTable(rows=[]))
    data = _body(api.handle_coaches({}))
    staff = [c for c in data["coaches"] if c["tier"] == "staff"]
    assert all(c["headline_stat"] == "no checked call yet" for c in staff)
    assert all(c["record"] == {"confirmed": 0, "refuted": 0, "n": 0, "through": None} for c in staff)
    lead = data["coaches"][0]
    assert lead["tier"] == "lead"
    assert lead["headline_stat"] == "runs the program"
    assert lead["record"] is None


def test_roster_headline_says_unavailable_when_the_ledger_read_fails():
    # ADR-104: a failed read is not a clean slate. The default module table is the real
    # boto3 handle under FAKE creds — every query raises — so the record is null and the
    # headline says so, instead of the old producer's "track record accruing" (a zero
    # count rendered as a fresh start).
    data = _body(api.handle_coaches({}))
    staff = [c for c in data["coaches"] if c["tier"] == "staff"]
    assert all(c["record"] is None for c in staff)
    assert all(c["headline_stat"] == "record unavailable" for c in staff)


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
    # #1113: the authored cast sheet rides the payload (bundled module, works offline)
    ts = data["trait_scores"]
    assert len(ts["axes"]) == 5
    for a in ts["axes"]:
        assert a["label"] and a["low"] and a["high"] and 0 <= a["score"] <= 100
    assert "uthored" in ts["disclosure"]


def test_coach_page_character_carries_data_sources(monkeypatch):
    """#1113 prompt transparency: _character surfaces the config-authored source
    list (what the coach's prompt actually reads). Offline the S3 board config
    isn't reachable, so feed the local file through the loader seam."""
    import json as _json

    def _local_s3_json(key, name):
        if key == "config/board_of_directors.json":
            with open(os.path.join(_REPO, "config", "board_of_directors.json")) as f:
                return _json.load(f)
        return {}

    monkeypatch.setattr(api, "_load_s3_json", _local_s3_json)
    data = _body(api.handle_coach({"rawPath": "/api/coach/sleep_coach"}))
    assert data["character"]["data_sources"] == ["whoop", "eightsleep"]


def test_coach_page_id_via_query_param():
    data = _body(api.handle_coach({"queryStringParameters": {"id": "physical_coach"}}))
    assert data["persona_id"] == "physical_coach"
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
    # #1112: lead:true opens the door for the head coach ONLY — every other
    # non-operational persona (the narrator included) still 404s.
    resp3 = api.handle_coach({"rawPath": "/api/coach/elena_voss"})
    assert resp3["statusCode"] == 404


# ── the head coach (lead tier, #1112) ────────────────────────────────────────


def test_lead_coach_detail_route_shape():
    data = _body(api.handle_coach({"rawPath": "/api/coach/eli_marsh"}))
    assert data["persona_id"] == api.persona_registry.LEAD_PERSONA_ID
    assert data["tier"] == "lead"
    assert data["name"] == "Dr. Eli Marsh"
    assert "AI character" in data["disclosure"]
    # lead extras are config-authored persona fields
    assert data["philosophy"] and "One experiment at a time" in data["philosophy"]
    assert data["expertise"]
    # the authored cast sheet covers the lead too (#1113 machinery)
    ts = data["trait_scores"]
    assert ts and len(ts["axes"]) == 5 and "uthored" in ts["disclosure"]
    # the standard dynamic sections are present and honest-empty pre-data:
    # no ladder scaffold is fabricated for him (source "none", never "ladder")
    assert data["stance"]["source"] == "none"
    assert data["working_hypotheses"] == []
    assert data["stance_history"] == []
    assert data["recent_outputs"] == []
    # no generation voice spec exists for the lead — null, never a fabricated spec
    assert data["voice"] is None
    # report card scaffold stays shaped + honest (no decided calls, ever, so far)
    assert data["report_card"]["track_record"]["hit_rate_pct"] is None


def test_lead_leads_the_roster_before_staff():
    data = _body(api.handle_coaches({}))
    assert data["coaches"][0]["persona_id"] == "eli_marsh"
    assert data["coaches"][0]["board_role"].startswith("Principal Investigator")


# ── My Team (/api/coach_team, CC-10) ─────────────────────────────────────────


def test_team_view_shape():
    data = _body(api.handle_coach_team({}))
    assert len(data["huddle"]) == len(api.persona_registry.OPERATIONAL_COACH_IDS)
    from coach.audience_guard import is_owner_directed

    for c in data["huddle"]:
        assert c.get("name") and c.get("stage_id")
        # #4213: the headline is a reader slot — the authored text, or "" where the
        # authored rung addresses Matthew ("First, I just need to see what you eat.").
        assert isinstance(c.get("headline"), str) and not is_owner_directed(c["headline"])
        assert not is_owner_directed(c.get("graduation_gate") or "")
        assert "watch" in c
    assert sum(1 for c in data["huddle"] if c["headline"]) >= len(data["huddle"]) - 2  # not a blanking machine
    assert data["team_focus"] and len(data["team_focus"]) == len(set(data["team_focus"]))
    assert isinstance(data["tensions"], list)  # honest empty pre-data, never an error
    assert "AI character" in data["disclosure"]


def test_team_stage_mix_is_honest():
    data = _body(api.handle_coach_team({}))
    stages = {c["persona_id"]: c["stage_id"] for c in data["huddle"]}
    # weight-banded coaches sit at 'foundation' from the baseline; nutrition
    # (logging consistency) sits at 'visibility' — so not all on one stage label.
    assert stages["physical_coach"] == "foundation"
    assert stages["nutrition_coach"] == "visibility"
    assert data["all_same_stage"] is False


# ── predictions (/api/predictions, R22-BUG-03 #819) ──────────────────────────


def test_predictions_overall_accuracy_pct_null_when_nothing_resolved(monkeypatch):
    monkeypatch.setattr(api, "table", FakeDdbTable(rows=[]))
    data = _body(api.handle_predictions({}))
    o = data["overall"]
    assert o["decided"] == 0
    # ADR-104: an unearned 0% would read as "the board is bad at this" when in
    # truth nothing has graded yet — must be an honest absence, not a fabricated zero.
    assert o["accuracy_pct"] is None


def test_predictions_overall_accuracy_pct_rounds_when_some_resolved(monkeypatch):
    def _query_hook(table, **kw):
        # scan_coaches iterates in a fixed order (sleep first) — hand the first
        # coach queried a mix of graded calls, every other coach comes back empty.
        # (query_calls already includes THIS call — appended before the hook runs.)
        if len(table.query_calls) == 1:
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

    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_query_hook))
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


# ── /api/coach_analysis ensemble-fallback disclosure (#2333) ──────────────────
# coach_ensemble_digest stamps `_fallback: True` on a digest produced without the
# LLM (budget-paused at tier >= 1, ADR-125 — the common case per #1927, not the
# rare one). Nothing downstream of _latest_cycle_digest checked the mark, so a
# template-generated digest served on /api/coach_analysis indistinguishably from
# a genuine cross-coach read. `ensemble_fallback` closes that.


def _fake_query_by_pk(routes, default_out=None):
    """table.query stub that routes by the queried pk (extracted from the real
    boto3 Key(...) condition tree) rather than by call order — the OUTPUT# lookup
    happens first, but the ensemble-digest lookup (#1085: pk=ENSEMBLE#digest) can
    land on any later call, and this test cares about that read succeeding."""

    def _pk_of(condition):
        expr = condition.get_expression()
        if expr["operator"] == "AND":
            for v in expr["values"]:
                found = _pk_of(v)
                if found is not None:
                    return found
            return None
        key = expr["values"][0]
        return expr["values"][1] if getattr(key, "name", None) == "pk" else None

    def _query(**kwargs):
        pk = _pk_of(kwargs["KeyConditionExpression"])
        return {"Items": routes.get(pk, default_out or [])}

    return _query


def test_coach_analysis_flags_ensemble_fallback(monkeypatch):
    out_item = {
        "pk": "COACH#sleep_coach",
        "sk": "OUTPUT#2026-06-29",
        "content": "the analysis text",
        "generated_at": "2026-06-29T14:00:00Z",
    }
    digest_item = {
        "pk": "ENSEMBLE#digest",
        "sk": "CYCLE#2026-06-29",
        "_fallback": True,
        "active_disagreements": [],
        "coach_summaries": [],
    }
    monkeypatch.setattr(
        api.table,
        "query",
        _fake_query_by_pk({"COACH#sleep_coach": [out_item], "ENSEMBLE#digest": [digest_item]}),
    )
    monkeypatch.setattr(api.table, "get_item", lambda Key: {})
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    data = _body(api.handle_coach_analysis({"queryStringParameters": {"domain": "sleep"}}))
    assert data["ensemble_fallback"] is True


def test_coach_analysis_ensemble_fallback_false_for_a_genuine_digest(monkeypatch):
    out_item = {
        "pk": "COACH#sleep_coach",
        "sk": "OUTPUT#2026-06-29",
        "content": "the analysis text",
        "generated_at": "2026-06-29T14:00:00Z",
    }
    digest_item = {
        "pk": "ENSEMBLE#digest",
        "sk": "CYCLE#2026-06-29",
        "active_disagreements": [],
        "coach_summaries": [],
    }
    monkeypatch.setattr(
        api.table,
        "query",
        _fake_query_by_pk({"COACH#sleep_coach": [out_item], "ENSEMBLE#digest": [digest_item]}),
    )
    monkeypatch.setattr(api.table, "get_item", lambda Key: {})
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    data = _body(api.handle_coach_analysis({"queryStringParameters": {"domain": "sleep"}}))
    assert data["ensemble_fallback"] is False


def test_coach_analysis_ensemble_fallback_false_with_no_digest_at_all(monkeypatch):
    out_item = {
        "pk": "COACH#sleep_coach",
        "sk": "OUTPUT#2026-06-29",
        "content": "the analysis text",
        "generated_at": "2026-06-29T14:00:00Z",
    }
    monkeypatch.setattr(api.table, "query", _fake_query_by_pk({"COACH#sleep_coach": [out_item]}))
    monkeypatch.setattr(api.table, "get_item", lambda Key: {})
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    data = _body(api.handle_coach_analysis({"queryStringParameters": {"domain": "sleep"}}))
    assert data["ensemble_fallback"] is False


def test_predictions_serve_the_freeze_instant_beside_the_effective_date(monkeypatch):
    """#3480: a pre-registered claim's `date` is genesis by construction (the day it
    grades FROM); the instant it was frozen is a different fact and is served as
    `pre_registered_at` so the page never labels a 09-04 freeze as "made 09-05".
    An in-cycle coach call has no freeze instant — it serves None, never a fabricated one."""

    def _query_hook(table, **kw):
        if len(table.query_calls) == 1:
            return {
                "Items": [
                    {
                        "status": "pending",
                        "created_date": "2026-09-05",
                        "claim_natural": "frozen",
                        "pre_registered_at": "2026-09-04T16:53:28+00:00",
                    },
                    {"status": "pending", "created_date": "2026-09-05", "claim_natural": "in-cycle"},
                ]
            }
        return {"Items": []}

    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_query_hook))
    by_text = {p["text"]: p for p in _body(api.handle_predictions({}))["predictions"]}
    assert by_text["frozen"]["date"] == "2026-09-05"
    assert by_text["frozen"]["pre_registered_at"] == "2026-09-04T16:53:28+00:00"
    assert by_text["in-cycle"]["pre_registered_at"] is None


# ── E1 / #4182: the ledger line (`latest_checked`) ───────────────────────────
#
# Rows are built by the REAL producers — `prediction_emission.build_prediction_record`
# for the emitted PREDICTION# row and `prediction_grading.build_outcome_notes` for the
# grader's write-back (the exact JSON `_update_prediction_status` stores) — never
# hand-typed, so the fixture is the wire shape.


def _emitted(coach_id, day, claim, metric="hrv_7day_avg", condition=">=", threshold=50):
    from coach.prediction_emission import build_prediction_record

    spec = {"type": "machine", "metric": metric, "condition": condition, "threshold": threshold, "window_days": 14}
    return build_prediction_record(coach_id, day, claim, spec, 0.6, "coach_read")


def _graded(row, status, graded_on, actual):
    from coach.prediction_grading import build_outcome_notes

    notes = build_outcome_notes({"status": status, "actual_value": actual, "reason": "r"}, "1.0")
    return dict(row, status=status, outcome=status, outcome_date=graded_on, outcome_notes=notes)


def _ledger_table(routes):
    return FakeDdbTable(query_hook=lambda table, **kw: {"Items": list(routes.get(_fake_pk(kw), []))})


def _fake_pk(kwargs):
    expr = kwargs["KeyConditionExpression"].get_expression()
    while expr["operator"] == "AND":
        expr = expr["values"][0].get_expression()
    return expr["values"][1]


def _two_coach_routes():
    older = _graded(_emitted("sleep_coach", "2026-09-06", "Matthew's HRV average will trend up."), "refuted", "2026-09-13", 41.2)
    newest = _graded(
        _emitted("sleep_coach", "2026-09-10", "Matthew's 7-day HRV average will reach 50 ms."), "confirmed", "2026-09-24", 51.73
    )
    pending_newer = _emitted("sleep_coach", "2026-09-25", "Matthew's sleep will hold 7.5 hours.")
    nutrition_pending = _emitted("nutrition_coach", "2026-09-20", "Protein will average 180 g this week.", metric="protein_g")
    return {
        "COACH#sleep_coach": [pending_newer, newest, older],
        "COACH#nutrition_coach": [nutrition_pending],
    }


def test_latest_checked_serves_the_most_recent_graded_call_and_null_otherwise(monkeypatch):
    routes = _two_coach_routes()
    monkeypatch.setattr(api, "table", _ledger_table(routes))

    sleep = _body(api.handle_coach({"rawPath": "/api/coach/sleep_coach"}))["latest_checked"]
    assert sleep == {
        "prediction_id": routes["COACH#sleep_coach"][1]["prediction_id"],  # the producer's own id
        "claim": "Matthew's 7-day HRV average will reach 50 ms.",
        "created_date": "2026-09-10",
        "pre_registered_at": None,
        "outcome_date": "2026-09-24",
        "metric": "hrv_7day_avg",
        "eval_type": "machine",
        "condition": ">=",
        "threshold": 50,
        "actual_value": 51.73,
        "status": "confirmed",
    }
    # A coach whose only call is still pending has NO ledger line — null, never a placeholder.
    assert _body(api.handle_coach({"rawPath": "/api/coach/nutrition_coach"}))["latest_checked"] is None

    roster = {c["persona_id"]: c for c in _body(api.handle_coaches({}))["coaches"]}
    assert roster["sleep_coach"]["latest_checked"] == sleep
    assert roster["nutrition_coach"]["latest_checked"] is None
    assert roster[api.persona_registry.LEAD_PERSONA_ID]["latest_checked"] is None
    # Every staff roster entry carries the key (the site can tell absent from missing).
    assert all("latest_checked" in c for c in roster.values())


def test_latest_checked_claim_is_audience_guarded():
    """#2972/#4213: the claim is born guarded — owner-register text never crosses; the
    graded numbers still stand beside a null claim (nothing is rewritten)."""
    from coach import latest_checked

    addressed = _graded(_emitted("mind_coach", "2026-09-08", "You will sleep 7.5 hours on 5 of 7 nights."), "confirmed", "2026-09-15", 7.6)
    vocative = _graded(_emitted("mind_coach", "2026-09-09", "Matthew, your HRV will climb."), "refuted", "2026-09-16", 38.0)
    for row in (addressed, vocative):
        block = latest_checked.to_block(row)
        assert block["claim"] is None
        assert block["actual_value"] is not None and block["status"] in ("confirmed", "refuted")
    table = _ledger_table({"COACH#mind_coach": [addressed, vocative]})
    served = latest_checked.for_coach(table, "mind_coach")
    assert served["outcome_date"] == "2026-09-16"
    import re

    for block in (served, latest_checked.for_coach(_ledger_table(_two_coach_routes()), "sleep_coach")):
        assert not re.search(r"\byou", block["claim"] or "", re.IGNORECASE), block["claim"]


def test_latest_checked_skips_undecided_and_archived_rows_and_degrades_to_null():
    from coach import latest_checked

    base = _emitted("physical_coach", "2026-09-07", "Matthew's weight will fall.", metric="weight_lbs", condition="<", threshold=320)
    inconclusive = _graded(base, "inconclusive", "2026-09-21", None)
    expired = _graded(base, "expired", "2026-09-22", None)
    archived = dict(_graded(base, "confirmed", "2026-09-23", 318.0), tombstone=True)
    assert latest_checked.select_latest([inconclusive, expired, archived, base]) is None

    class _Boom:
        def query(self, **_kw):
            raise RuntimeError("ddb down")

    assert latest_checked.for_coach(_Boom(), "physical_coach") is None


# ── #4220: ONE record producer — the four endpoints agree per coach ───────────
#
# THE LIVE CORPUS, 2026-09-26/27 (Session AV/AW inventory, /api/* read 02:47Z):
#
#   coach              /api/coaches headline   /api/calibration + /api/predictions   /api/wrong by_coach
#   Webb (nutrition)   "80% hit-rate · n=25"   n 5 · 0 confirmed / 5 refuted         20 confirmed / 5 refuted
#   Brandt (explorer)  "12% hit-rate · n=24"   n 4 · 3 / 1                           3 / 21
#
# Two producers: /api/coaches and /api/wrong re-counted LEARNING# rows; the scorecard
# counted PREDICTION#. Twenty of Webb's learnings were ONE dispute docket re-recorded
# daily 09-07 → 09-26 (#4216: the resolver re-grades a stranded pre-cycle OPEN# row every
# run; its LEARNING# key carries today's date, its PREDICTION# key does not, so
# `_put_unique` wrote -2…-5 suffixed copies and then raised). Measured on Webb's live
# partition 2026-09-27: five PREDICTION#docket-… rows, ONE prediction_id, every one
# stamped phase=pilot cycle=16 tombstone=true (the reset/reconcile stamp,
# deploy/reconcile_provenance_2026_09.py `after=`).
#
# THE FIXTURE IS THE WIRE. Every row below is written by the REAL producer that writes
# it live — `prediction_emission.build_prediction_record` + `prediction_grading.
# build_outcome_notes` for the graded calls, `coach_prediction_evaluator.
# _write_learning_record` for their learnings, `dispute_docket._write_docket_learning`
# / `_write_docket_prediction` (through the real `_put_unique`, against a table that
# enforces its ConditionExpression) for the docket trail — twenty resolver days, in the
# resolver's own write order. Since #4317 the prediction writer writes once and REFUSES
# the nineteen re-runs (asserted); the four suffixed PREDICTION# copies the retired
# writer left on the live table (measured 2026-09-27, still there until #4216's cleanup
# box) are added as that measured shape, because the consumer must count them once.
# Dates derive from the live genesis (never literals — the #2376 dated-fixture timebomb
# class): the docket opens 34 days before Day 1, its criterion day is 27 days before,
# the re-runs run Day 1 → Day 20.


def _day(offset):
    from datetime import date, timedelta

    return (date.fromisoformat(EXPERIMENT_START) + timedelta(days=offset)).isoformat()


class _ConditionalTable(FakeDdbTable):
    """A FakeDdbTable whose put_item honours `attribute_not_exists(pk) AND
    attribute_not_exists(sk)` the way DynamoDB does — so `_put_unique`'s real
    disambiguation trail (and its exhaustion) is exercised, not assumed."""

    def put_item(self, Item=None, **kwargs):  # noqa: N803 — boto3's own kwarg casing
        from botocore.exceptions import ClientError

        item = Item if Item is not None else kwargs.get("Item")
        if kwargs.get("ConditionExpression") and self._key_of(item) in self.store:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}}, "PutItem")
        return super().put_item(Item=item, **kwargs)


def _docket_0810():
    """The one docket behind the 20 re-writes — the live row's own fields (topic, pair,
    criterion, opened/criterion dates relative to genesis)."""
    opened = _day(-34)
    criterion_day = _day(-27)
    return {
        "sk": "OPEN#explorer_coach__nutrition_coach#calories",
        "coach_a": "explorer_coach",
        "coach_b": "nutrition_coach",
        "pair_key": "explorer_coach__nutrition_coach",
        "subdomain": "calories",
        "topic": "Caloric variance interpretation: distribution modeling vs point estimates",
        "topic_slug": "caloric-variance-interpretation-distribution-modeling-vs-poi",
        "criterion": {
            "metric": "total_calories_kcal_7day_avg",
            "condition": "gte",
            "threshold": 2200,
            "description": f"total_calories_kcal_7day_avg >= 2200 on {criterion_day}",
        },
        "claims": {
            "explorer_coach": "The 7-day calorie average will sit under 2200.",
            "nutrition_coach": "The 7-day calorie average will hold at or above 2200.",
        },
        "stakes": {},
        "opened_date": opened,
        "opened_at": f"{opened}T17:41:16+00:00",
    }


def _write_live_0926_wire(monkeypatch):
    """Drive the real writers into ONE conditional table; return it."""
    from coach import coach_prediction_evaluator as ev, dispute_docket as dd

    table = _ConditionalTable(rows=[])
    monkeypatch.setattr(ev, "table", table)
    monkeypatch.setattr(dd, "table", table)

    def _graded_call(coach_id, made, claim, status, graded_on, actual, metric, condition):
        row = _graded(_emitted(coach_id, made, claim, metric=metric, condition=condition, threshold=1), status, graded_on, actual)
        table.put_item(Item=row)
        ev._write_learning_record(
            coach_id,
            graded_on,
            {
                "prediction_id": row["prediction_id"],
                "status": status,
                "metric": metric,
                "condition": condition,
                "actual_value": actual,
                "evaluation_type": "directional",
                "reason": f"{metric} trend=up (slope={actual}), predicted=down",
            },
        )
        return row

    # Webb: five in-cycle directional calls, every one refuted (the live 0 of 5).
    webb = [
        _graded_call(
            "nutrition_coach",
            _day(6),
            "Protein will trend down after the disrupted dinner.",
            "refuted",
            _day(20),
            0.0314,
            "total_protein_g",
            "down",
        ),
        _graded_call(
            "nutrition_coach",
            _day(6),
            "Recovery will trend down if evening carbs are cut.",
            "refuted",
            _day(20),
            0.0778,
            "recovery_score",
            "down",
        ),
        _graded_call(
            "nutrition_coach", _day(7), "Calories will trend down this week.", "refuted", _day(19), 0.0859, "total_calories_kcal", "down"
        ),
        _graded_call(
            "nutrition_coach", _day(8), "Protein will trend down over the weekend.", "refuted", _day(18), 0.0383, "total_protein_g", "down"
        ),
        _graded_call(
            "nutrition_coach", _day(9), "Recovery will trend down under the deficit.", "refuted", _day(18), 0.1439, "recovery_score", "down"
        ),
    ]
    # Brandt: three confirmed, one refuted (the live 3 of 4).
    brandt = [
        _graded_call(
            "explorer_coach", _day(5), "HRV will trend up as the deficit settles.", "confirmed", _day(16), 0.02, "hrv_7day_avg", "up"
        ),
        _graded_call("explorer_coach", _day(6), "Sleep hours will trend up.", "confirmed", _day(17), 0.03, "sleep_hours", "up"),
        _graded_call("explorer_coach", _day(7), "Resting heart rate will trend down.", "confirmed", _day(18), -0.01, "rhr_bpm", "down"),
        _graded_call(
            "explorer_coach", _day(8), "Calorie variance will trend down.", "refuted", _day(19), 0.05, "total_calories_kcal", "down"
        ),
    ]

    # The docket, resolved by the real resolver path twenty days running (its order:
    # both learnings, then both predictions — #4216's mechanism verbatim).
    docket = _docket_0810()
    refused = []
    for offset in range(1, 21):
        day = _day(offset)
        dd._write_docket_learning("nutrition_coach", day, docket, "confirmed")
        dd._write_docket_learning("explorer_coach", day, docket, "refuted", concession="CONCESSION — I lost the docket dispute.")
        w = dd._write_docket_prediction("nutrition_coach", docket, "confirmed", 2310.0, day)
        l = dd._write_docket_prediction("explorer_coach", docket, "refuted", 2310.0, day)
        if offset > 1:
            refused.append((w, l))
    assert len(refused) == 19 and all(w is None and l is None for w, l in refused), "#4317: the docket writer refuses every re-run"
    # The retired writer's trail, as the live table still carries it (2026-09-27): four
    # suffixed copies of each side's docket row, one later outcome_date per daily re-run.
    for (pk, sk), row in list(table.store.items()):
        if str(sk).startswith("PREDICTION#docket-"):
            for n in (2, 3, 4, 5):
                table.store[(pk, f"{sk}-{n}")] = dict(row, sk=f"{sk}-{n}", outcome_date=_day(n))

    # The reset/reconcile stamp the live docket rows carry (measured 2026-09-27 on all
    # five of Webb's PREDICTION#docket-… rows): phase=pilot, tombstone=true, cycle=16 —
    # the `after=` shape of deploy/reconcile_provenance_2026_09.py.
    for (_pk, sk), row in table.store.items():
        if str(sk).startswith("PREDICTION#docket-"):
            row.update({"phase": "pilot", "tombstone": True, "cycle": "16"})

    return table, {"webb": webb, "brandt": brandt}


def _route_table(store_table):
    """A query fake that routes by pk AND sk prefix — the two partitions a coach's pk
    holds (PREDICTION#, LEARNING#) must not answer each other's query."""

    def _pk_sk(kw):
        expr = kw["KeyConditionExpression"].get_expression()
        pk = prefix = None
        if expr["operator"] == "AND":
            left, right = expr["values"]
            pk = left.get_expression()["values"][1]
            r = right.get_expression()
            if r["operator"] == "begins_with":
                prefix = r["values"][1]
        else:
            pk = expr["values"][1]
        return pk, prefix

    def _hook(table, **kw):
        pk, prefix = _pk_sk(kw)
        rows = [dict(r) for (p, s), r in store_table.store.items() if p == pk and (prefix is None or str(s).startswith(prefix))]
        rows.sort(key=lambda r: str(r.get("sk") or ""), reverse=not kw.get("ScanIndexForward", True))
        return {"Items": rows}

    return FakeDdbTable(query_hook=_hook)


def _served_four(monkeypatch, table):
    from web import site_api_intelligence as intel

    routed = _route_table(table)
    monkeypatch.setattr(api, "table", routed)
    monkeypatch.setattr(intel, "table", routed)
    coaches = _body(api.handle_coaches({}))
    calibration = _body(api.handle_calibration({}))
    predictions = _body(api.handle_predictions({"queryStringParameters": {"limit": "200"}}))
    wrong = _body(intel.handle_wrong())
    return coaches, calibration, predictions, wrong


def _assert_one_record(short_id, coaches, calibration, predictions, wrong):
    """The #4220 guard: for one coach, the four endpoints serve ONE record."""
    roster = {c["persona_id"]: c for c in coaches["coaches"]}
    cal = {c["coach_id"]: c for c in calibration["coaches"]}[short_id]
    pred = predictions["by_coach"][short_id]
    wrong_by = {r["coach"]: r for r in wrong["predictions"]["by_coach"]}
    record = roster[f"{short_id}_coach"]["record"]
    assert record is not None, f"{short_id}: /api/coaches served no record"
    assert set(record) == {"confirmed", "refuted", "n", "through"}
    assert record["n"] == record["confirmed"] + record["refuted"]
    assert cal["record"] == record, f"{short_id}: /api/calibration.record disagrees with /api/coaches.record"
    assert (cal["n"], cal["confirmed"], cal["refuted"]) == (record["n"], record["confirmed"], record["refuted"]), short_id
    assert pred["record"] == record, f"{short_id}: /api/predictions.record disagrees"
    assert (pred["decided"], pred["confirmed"], pred["refuted"]) == (record["n"], record["confirmed"], record["refuted"]), short_id
    if record["n"]:
        assert wrong_by[short_id] == {"coach": short_id, **record}, f"{short_id}: /api/wrong.by_coach disagrees"
    else:
        assert short_id not in wrong_by
    return record


def test_4220_the_four_endpoints_serve_one_record_per_coach(monkeypatch):
    table, rows = _write_live_0926_wire(monkeypatch)
    served = _served_four(monkeypatch, table)
    coaches, calibration, predictions, wrong = served

    webb = _assert_one_record("nutrition", *served)
    assert webb == {"confirmed": 0, "refuted": 5, "n": 5, "through": _day(20)}
    brandt = _assert_one_record("explorer", *served)
    assert brandt == {"confirmed": 3, "refuted": 1, "n": 4, "through": _day(19)}
    # Every operational coach, not just the two the issue named.
    for c in calibration["coaches"]:
        if f"{c['coach_id']}_coach" in {x["persona_id"] for x in coaches["coaches"]}:
            _assert_one_record(c["coach_id"], *served)

    # The docket contributed zero to this cycle's record on either side; career counts
    # it ONCE per side (five suffixed rows, one prediction_id).
    assert calibration["coaches"] and {c["coach_id"]: c["lifetime"]["n"] for c in calibration["coaches"]}["nutrition"] == 6
    assert predictions["by_coach"]["nutrition"]["lifetime"] == {
        **predictions["by_coach"]["nutrition"]["lifetime"],
        "confirmed": 1,
        "decided": 6,
    }
    # Below n = 10 the headline prints counts, never a percentage — and names the day.
    roster = {c["persona_id"]: c for c in coaches["coaches"]}
    from coach.coach_record import day_words

    assert roster["nutrition_coach"]["headline_stat"] == f"0 of 5 checked calls right through {day_words(_day(20))}"
    assert roster["explorer_coach"]["headline_stat"] == f"3 of 4 checked calls right through {day_words(_day(19))}"
    assert "%" not in roster["nutrition_coach"]["headline_stat"]


def test_4220_mutation_control_the_learning_count_fails_on_webb(monkeypatch):
    """Restore the retired producer — `_track_record`'s LEARNING# count — over the SAME
    wire and hand its numbers to the guard: it must fail on Webb (25 ≠ 5)."""
    table, _rows = _write_live_0926_wire(monkeypatch)
    coaches, calibration, predictions, wrong = _served_four(monkeypatch, table)
    old = api._track_record("nutrition_coach")
    assert old["decided"] == 25 and old["confirmed"] == 20, old  # the live headline's numbers, reproduced
    forged = json.loads(json.dumps(coaches))
    for c in forged["coaches"]:
        if c["persona_id"] == "nutrition_coach":
            c["record"] = {"confirmed": old["confirmed"], "refuted": old["refuted"], "n": old["decided"], "through": _day(20)}
    with pytest.raises(AssertionError, match="calibration.record disagrees"):
        _assert_one_record("nutrition", forged, calibration, predictions, wrong)
    # And the guard is not one-sided: a scorecard that drifted from the roster also reds.
    forged_cal = json.loads(json.dumps(calibration))
    for c in forged_cal["coaches"]:
        if c["coach_id"] == "nutrition":
            c["confirmed"] = 1
    with pytest.raises(AssertionError):
        _assert_one_record("nutrition", coaches, forged_cal, predictions, wrong)


def test_4220_a_prediction_resolves_once_and_in_the_cycle_it_resolved_in():
    """The two counting rules, pure: re-writes collapse to the EARLIEST resolution; a
    graded row resolved before genesis never counts in the current record even when its
    stamp says it is visible; the docket trail counts once in career."""
    from coach import coach_record as cr

    original = {"prediction_id": "p1", "sk": "PREDICTION#p1", "status": "confirmed", "outcome_date": _day(-27), "confidence": 0.5}
    rewrites = [
        {"prediction_id": "p1", "sk": f"PREDICTION#p1-{i}", "status": "confirmed", "outcome_date": _day(i), "confidence": 0.5}
        for i in range(2, 6)
    ]
    in_cycle = {"prediction_id": "p2", "sk": "PREDICTION#p2", "status": "refuted", "outcome_date": _day(12), "confidence": 0.5}
    pending = {"prediction_id": "p3", "sk": "PREDICTION#p3", "status": "pending", "confidence": 0.5}
    archived = {
        "prediction_id": "p4",
        "sk": "PREDICTION#p4",
        "status": "confirmed",
        "outcome_date": _day(3),
        "phase": "pilot",
        "tombstone": True,
    }
    rows = rewrites + [in_cycle, pending, original, archived]

    once = cr.resolved_once(rows)
    assert [r["sk"] for r in once] == ["PREDICTION#p2", "PREDICTION#p3", "PREDICTION#p1", "PREDICTION#p4"]
    assert cr.record_from_rows(rows, genesis=EXPERIMENT_START) == {"confirmed": 0, "refuted": 1, "n": 1, "through": _day(12)}
    assert cr.record_from_rows(rows, genesis=EXPERIMENT_START, career=True) == {"confirmed": 2, "refuted": 1, "n": 3, "through": _day(12)}
    # The pre-genesis original is visible (no stamp) and still excluded: resolved_date < genesis.
    assert cr.counts_this_cycle(original, EXPERIMENT_START) is False
    assert cr.counts_this_cycle(in_cycle, EXPERIMENT_START) is True
    assert cr.counts_this_cycle(pending, EXPERIMENT_START) is True  # an ungraded row is judged by visibility alone
    assert cr.counts_this_cycle(archived, EXPERIMENT_START) is False
    # A graded row with no identity is its own resolution — never collapsed into another.
    anon = [{"status": "confirmed", "outcome_date": _day(2)}, {"status": "confirmed", "outcome_date": _day(3)}]
    assert cr.record_from_rows(anon, genesis=EXPERIMENT_START)["n"] == 2
    # Headline copy at the three bands.
    assert cr.headline(None) == "record unavailable"
    assert cr.headline({"confirmed": 0, "refuted": 0, "n": 0, "through": None}) == "no checked call yet"
    assert cr.headline({"confirmed": 1, "refuted": 0, "n": 1, "through": None}) == "1 of 1 checked call right"
    assert (
        cr.headline({"confirmed": 7, "refuted": 10, "n": 17, "through": _day(20)})
        == f"7 of 17 checked calls right (41%) through {cr.day_words(_day(20))}"
    )


@pytest.mark.parametrize("pt_clock", ["23:30", "08:00"])
def test_4220_pair10_holds_under_a_frozen_pacific_clock(monkeypatch, pt_clock):
    """#3222-class control for PAIR 10: the contract must hold at 23:30 PT (a UTC day ahead
    of the Pacific day) and at 08:00 PT alike. Every clock the producer's writers read is
    frozen — `dispute_docket` / `coach_prediction_evaluator` / `prediction_emission`'s
    `datetime`, and `common.pacific_time`'s `pacific_today`/`pacific_now` (the names
    `phase_taxonomy._write_date` imports for the write-time stamp) — and the freeze is
    proved to have reached the writer through the row's own `resolved_at`. The 2026-09-27
    red on main was NOT this class (it was #4317 retiring the writer's -N trail); this pins
    that the pair never becomes one."""
    from datetime import datetime, timezone

    import pair_contract_registry  # noqa: F401 — populates the registry
    from coach import coach_prediction_evaluator as ev, dispute_docket as dd, prediction_emission as pe
    from common import pacific_time
    from common.pacific_time import PACIFIC
    from pacific_clock import freeze_pacific
    from pair_contract import PAIR_CONTRACT_REGISTRY

    pair = next(p for p in PAIR_CONTRACT_REGISTRY if p.name.startswith("coach PREDICTION# resolutions"))
    hour, minute = (int(x) for x in pt_clock.split(":"))
    pt_day = datetime.fromisoformat(_day(12)).replace(hour=hour, minute=minute, tzinfo=PACIFIC)
    frozen_utc = pt_day.astimezone(timezone.utc)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_utc.astimezone(tz) if tz else frozen_utc.replace(tzinfo=None)

    for mod in (dd, ev, pe):
        monkeypatch.setattr(mod, "datetime", _FrozenDatetime)
    pinned = freeze_pacific(monkeypatch, pacific_time, _FrozenDatetime)
    assert pinned.strftime("%H:%M") == pt_clock and pacific_time.pacific_today() == _day(12)
    if pt_clock == "23:30":
        assert frozen_utc.date().isoformat() != _day(12), "the control must sit where the UTC day and the Pacific day disagree"

    produced = pair.produce()
    consumed = pair.consume(produced)
    pair.agree(produced, consumed)
    docket_row = produced["rows"][1]
    assert str(docket_row["resolved_at"]).startswith(frozen_utc.isoformat()[:16]), "the frozen clock did not reach the writer"
    assert consumed == {"confirmed": 1, "refuted": 1, "n": 2, "through": _day(9)}
