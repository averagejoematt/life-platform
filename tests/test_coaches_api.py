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
        pk = prefix = span = None
        if expr["operator"] == "AND":
            left, right = expr["values"]
            pk = left.get_expression()["values"][1]
            r = right.get_expression()
            if r["operator"] == "begins_with":
                prefix = r["values"][1]
            elif r["operator"] == "BETWEEN":  # the MCP reader's LEARNING#{cutoff}..LEARNING#z window
                span = (r["values"][1], r["values"][2])
        else:
            pk = expr["values"][1]
        return pk, prefix, span

    def _hook(table, **kw):
        pk, prefix, span = _pk_sk(kw)
        rows = [
            dict(r)
            for (p, s), r in store_table.store.items()
            if p == pk and (prefix is None or str(s).startswith(prefix)) and (span is None or span[0] <= str(s) <= span[1])
        ]
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
    _assert_obituaries_are_the_record(short_id, record, wrong)
    return record


def _assert_obituaries_are_the_record(short_id, record, wrong):
    """#4220 box 2 on the rendered page: /method/'s obituary list is not a second
    derivation — one card per refuted resolution the record counts, no more, no fewer."""
    cards = [o for o in wrong["obituaries"] if o["coach"] == short_id]
    assert len(cards) == record["refuted"], f"{short_id}: {len(cards)} obituaries vs a record of {record['refuted']} refuted"
    assert wrong["obituary_count"] == len(wrong["obituaries"])


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


def _retired_learning_count(table, coach_id):
    """The retired producer, kept as the mutation: `_track_record`'s pre-#4220 LEARNING#
    re-count (every data row with a confirmed/refuted status, no identity check)."""
    rows = [r for (pk, sk), r in table.store.items() if pk == f"COACH#{coach_id}" and str(sk).startswith("LEARNING#")]
    data = [r for r in rows if (r.get("channel") or "data") != "conversation"]
    confirmed = sum(1 for r in data if r.get("status") == "confirmed")
    refuted = sum(1 for r in data if r.get("status") == "refuted")
    return {"confirmed": confirmed, "refuted": refuted, "decided": confirmed + refuted}


def test_4220_mutation_control_the_learning_count_fails_on_webb(monkeypatch):
    """Restore the retired producer — `_track_record`'s LEARNING# count — over the SAME
    wire and hand its numbers to the guard: it must fail on Webb (25 ≠ 5)."""
    table, _rows = _write_live_0926_wire(monkeypatch)
    coaches, calibration, predictions, wrong = _served_four(monkeypatch, table)
    old = _retired_learning_count(table, "nutrition_coach")
    assert old["decided"] == 25 and old["confirmed"] == 20, old  # the live headline's numbers, reproduced
    # And the report card, which re-counted LEARNING# until #4220's box 3 slice, now prints the record.
    card = api._track_record("nutrition_coach")
    roster = {c["persona_id"]: c for c in coaches["coaches"]}["nutrition_coach"]
    assert (card["record"], card["headline"], card["decided"]) == (roster["record"], roster["headline_stat"], 5), card
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


def _mcp_track_record(monkeypatch, table, short_id):
    """The owner-facing MCP reader over the SAME wire the four endpoints read."""
    import mcp.tools_coach_intelligence as tci

    monkeypatch.setattr(tci, "table", _route_table(table))
    # A window wide enough to hold every fixture day for as long as this genesis stands
    # (the fixture dates derive from genesis; a 30-day default would age them out).
    return tci.tool_get_coach_track_record({"coach_id": short_id, "days": 36500})


def _assert_mcp_is_the_record(short_id, coaches, mcp_out):
    """#4220 box 4: get_coach_track_record prints the record /api/coaches prints."""
    record = {c["persona_id"]: c for c in coaches["coaches"]}[f"{short_id}_coach"]["record"]
    assert mcp_out["record"] == record, f"{short_id}: MCP record {mcp_out['record']} vs /api/coaches {record}"
    assert mcp_out["decided_count"] == record["n"], f"{short_id}: MCP decided {mcp_out['decided_count']} vs {record['n']}"
    expected_pct = round(100 * record["confirmed"] / record["n"], 1) if record["n"] else None
    assert mcp_out["hit_rate_pct"] == expected_pct, short_id


def test_4220_the_mcp_track_record_reads_the_one_record(monkeypatch):
    """Box 4. Measured 2026-09-27 before the docket learnings were re-stamped pilot: the
    MCP reader said Webb 74.1 % (20/27) and Brandt 11.5 % (3/26) while /api/predictions
    said 0 of 7 and 3 of 6. Over the live-shaped wire (twenty blank-prediction_id docket
    learnings per side, in-cycle, NOT phase-stamped) it now prints the one record."""
    table, _rows = _write_live_0926_wire(monkeypatch)
    coaches, _cal, _pred, _wrong = _served_four(monkeypatch, table)
    for short_id in ("nutrition", "explorer"):
        _assert_mcp_is_the_record(short_id, coaches, _mcp_track_record(monkeypatch, table, short_id))

    webb = _mcp_track_record(monkeypatch, table, "nutrition")
    assert webb["headline"] == {c["persona_id"]: c for c in coaches["coaches"]}["nutrition_coach"]["headline_stat"]
    # The breakdowns count one result per prediction; the docket trail names none.
    assert webb["by_outcome"] == {"refuted": 5}, webb["by_outcome"]
    assert webb["excluded_learnings"] == {"no_prediction_id": 20, "repeat_result_for_a_prediction": 0}
    assert all(r["prediction_id"] for r in webb["recent_evaluations"])
    brandt = _mcp_track_record(monkeypatch, table, "explorer")
    assert brandt["by_outcome"] == {"confirmed": 3, "refuted": 1}, brandt["by_outcome"]


def test_4220_mcp_track_record_a_repeated_result_counts_once_and_a_failed_ledger_read_is_absence(monkeypatch):
    import mcp.tools_coach_intelligence as tci

    table, _rows = _write_live_0926_wire(monkeypatch)
    # A second result for an already-resolved prediction (a re-grade on a later day).
    for (pk, sk), row in list(table.store.items()):
        if pk == "COACH#explorer_coach" and str(sk).startswith("LEARNING#") and row.get("prediction_id"):
            later = f"LEARNING#{_day(25)}#{str(sk).split('#', 2)[2]}-regrade"
            table.store[(pk, later)] = dict(row, sk=later, date=_day(25), status="confirmed")
            break
    out = _mcp_track_record(monkeypatch, table, "explorer")
    assert out["excluded_learnings"]["repeat_result_for_a_prediction"] == 1
    assert sum(out["by_outcome"].values()) == 4

    # The ledger read fails -> no record, no rate; never a zero that reads as a clean slate.
    routed = _route_table(table)

    def _ledger_down(t, **kw):
        sk_cond = kw["KeyConditionExpression"].get_expression()["values"][1].get_expression()
        if sk_cond["operator"] == "begins_with" and sk_cond["values"][1] == "PREDICTION#":
            raise RuntimeError("throttled")
        return routed._query_hook(t, **kw)

    monkeypatch.setattr(tci, "table", FakeDdbTable(query_hook=_ledger_down))
    down = tci.tool_get_coach_track_record({"coach_id": "explorer", "days": 36500})
    assert down["record"] is None and down["decided_count"] is None and down["hit_rate_pct"] is None
    assert down["headline"] == "record unavailable"


# ── #4220: a graded call's reason is served in reader words ──────────────────
# Wire strings: `outcome_notes` exactly as /api/predictions served them 2026-09-29 16:24Z
# (build_outcome_notes' JSON blob), beside the evaluation spec the same rows carry.


def _pred_row(status, ev, **notes):
    return {"status": status, "evaluation": ev, "outcome_notes": json.dumps({"algo_version": "1.0", "beats_null": False, **notes})}


_DIR_UP = {"type": "directional", "metric": "hrv_7day_avg", "condition": "up", "threshold": None}
_DIR_DOWN = {"type": "directional", "metric": "recovery_score", "condition": "down", "threshold": None}
_POINT = {"type": "point", "metric": "sleep_duration_hours", "condition": "within", "threshold": 7.1}


@pytest.mark.parametrize(
    "row,expected",
    [
        (
            _pred_row("confirmed", _DIR_UP, actual_value=0.2341, reason="hrv_7day_avg trend=up (slope=0.2341), predicted=up"),
            ("Heart-rate variability (7-day average) went up, as called", True),
        ),
        (
            _pred_row("refuted", _DIR_DOWN, actual_value=0.1439, reason="recovery_score trend=up (slope=0.1439), predicted=down"),
            ("Morning recovery score went up — the call was for it to go down", True),
        ),
        (
            _pred_row(
                "refuted",
                _DIR_DOWN,
                actual_value=-0.0037,
                reason="predicted down, metric flat (slope=-0.0037, within \u00b10.02 noise band) \u2014 no movement to confirm the call",
            ),
            ("Morning recovery score held flat — the call was for it to go down", True),
        ),
        (
            _pred_row(
                "refuted",
                _POINT,
                actual_value=4.7,
                reason="sleep_duration_hours=4.70 on 2026-09-11 vs predicted 7.1 ±1.1708; |Δ|=2.40 → outside tolerance",
            ),
            ("Sleep time came in at 4.7 hours against a call of 7.1 hours — outside its usual day-to-day range", True),
        ),
        (
            _pred_row(
                "inconclusive",
                {"type": "directional", "metric": "blood_glucose_avg", "condition": "down"},
                actual_value=None,
                reason="Insufficient data to determine trend for 'blood_glucose_avg'",
                grading_open=True,
            ),
            ("not gradable yet — not enough average blood glucose data to read it", False),
        ),
        (
            _pred_row(
                "refuted",
                {"type": "machine", "metric": "total_calories_kcal", "condition": "gt", "threshold": None},
                actual_value=-0.0346,
                reason="[null-threshold machine spec re-routed to directional] total_calories_kcal trend=down (slope=-0.0346), predicted=up",
            ),
            ("Calories eaten went down — the call was for it to go up", True),
        ),
        (
            _pred_row(
                "expired",
                {"type": "qualitative"},
                actual_value=None,
                reason="Retired unevaluated at window end (14d): eval_type=qualitative has no deterministic grading path",
            ),
            ("retired ungraded — a call like this has no measurable test", False),
        ),
        # A metric with no reader words: the grader's own sentence, unwrapped — never a guess.
        (
            _pred_row(
                "refuted", {"type": "directional", "metric": "strain", "condition": "up"}, actual_value=-0.5, reason="strain trend=down"
            ),
            ("strain trend=down", True),
        ),
        # No reason written -> none served (ADR-104); nothing came back yet -> the flag is None.
        (_pred_row("inconclusive", _DIR_UP, actual_value=None, reason=None), (None, False)),
        ({"status": "pending", "evaluation": _DIR_UP, "outcome_notes": ""}, (None, None)),
        ({"status": "confirmed", "evaluation": _DIR_UP, "outcome_notes": "plain grader note"}, ("plain grader note", True)),
    ],
)
def test_4220_prediction_reason_in_reader_words(row, expected):
    from web import prediction_reason

    assert prediction_reason.reason_words(row) == expected


def test_4220_every_measurable_metric_has_reader_words():
    from experiment.measurable_metrics import METRIC_SOURCES, base_metric
    from web import prediction_reason

    assert {base_metric(k) for k in METRIC_SOURCES} == set(prediction_reason.METRIC_WORDS)


def test_4220_predictions_serve_reason_and_graded_on_data_beside_the_raw_notes(monkeypatch):
    table, _rows = _write_live_0926_wire(monkeypatch)
    _coaches, _cal, predictions, _wrong = _served_four(monkeypatch, table)
    from web import prediction_reason

    served = predictions["predictions"]
    webb = [p for p in served if p["coach_id"] == "nutrition" and p["status"] == "refuted"]
    assert len(webb) == 5, "the wire serves Webb's five refuted calls"
    for p in webb:
        assert p["outcome_notes"].startswith("{"), "outcome_notes stays the grader's blob (compatibility)"
        assert p["graded_on_data"] is True
        # The wire's grader wrote reason "r" on a machine spec with no reader-word shape:
        # the grader's own text is served, unwrapped — never the blob, never a guess.
        assert p["reason"] == "r", p["reason"]
    # Every served row's reason is the one function's answer over its stored row.
    stored = {
        (row.get("claim_natural"), row.get("created_date")): row
        for (_pk, sk), row in table.store.items()
        if str(sk).startswith("PREDICTION#") and not str(sk).startswith("PREDICTION#docket-")
    }
    checked = 0
    for p in served:
        row = stored.get((p["text"], p["date"]))
        if row is None:
            continue
        assert (p["reason"], p["graded_on_data"]) == prediction_reason.reason_words({**row, "status": p["status"]}), p
        checked += 1
    assert checked >= 9


_LIVE_WRONG_4220 = os.path.join(_REPO, "tests", "fixtures", "wrong_obituaries_4220", "live_2026-09-27.json")


def _served_wrong_over_live_rows(monkeypatch):
    """/api/wrong over the captured live partitions (explorer + nutrition), genesis pinned
    to the capture's own — the fixture is the wire, read-only from DynamoDB 2026-09-27."""
    from web import site_api_intelligence as intel

    with open(_LIVE_WRONG_4220) as fh:
        live = json.load(fh)
    store = FakeDdbTable(rows=live["rows"])
    monkeypatch.setattr(intel, "table", _route_table(store))
    monkeypatch.setattr(intel, "EXPERIMENT_START", live["genesis"])
    return live, _body(intel.handle_wrong())


def test_4220_obituaries_are_the_records_refutations_on_the_live_wire(monkeypatch):
    """The live defect, 2026-09-27T23:09Z: /api/wrong served 23 explorer obituaries — twenty
    'settled against the call by the dispute docket on August 10', dated Day 1 → Day 20 —
    beside a record of 3 refuted. Over the same rows the cards now equal the record."""
    live, wrong = _served_wrong_over_live_rows(monkeypatch)
    before = live["served_before_fix"]
    was = {c: sum(1 for o in before["obituaries"] if o["coach"] == c) for c in ("explorer", "nutrition")}
    assert was == {"explorer": 23, "nutrition": 7}, "the captured defect"
    assert sum("dispute docket on August 10" in o["what_changed"] for o in before["obituaries"]) == 20

    records = {r["coach"]: r for r in wrong["predictions"]["by_coach"]}
    # The record itself is unchanged by this fix — it is what the live ledger served.
    assert {c: records[c] for c in records} == {r["coach"]: r for r in before["by_coach"]}
    for coach in ("explorer", "nutrition"):
        _assert_obituaries_are_the_record(coach, records[coach], wrong)
    assert records["explorer"]["refuted"] == 3
    assert not any("dispute docket" in o["what_changed"] for o in wrong["obituaries"]), "the 08-10 docket is cycle 16's, never 17's"
    # Every card is dated in this cycle, and the surviving cards keep their live ids
    # (the permalink / OG card / RSS entry are keyed on the id).
    assert all(o["date"] >= live["genesis"] for o in wrong["obituaries"])
    assert {o["id"] for o in wrong["obituaries"]} <= {o["id"] for o in before["obituaries"]}


def test_4220_mutation_control_the_learning_derivation_fails_on_explorer(monkeypatch):
    """Restore the retired obituary path — every refuted live LEARNING# row is a card —
    over the SAME live rows: the guard must fail on explorer (23 ≠ 3)."""
    from web import site_api_foresight as fs

    def _old_path(table, coach, refuted):
        from boto3.dynamodb.conditions import Key

        r = table.query(KeyConditionExpression=Key("pk").eq(f"COACH#{coach}_coach") & Key("sk").begins_with("LEARNING#"))
        return [
            x
            for x in fs._decimal_to_float(r.get("Items", []))
            if not x.get("tombstone") and (x.get("channel") or "data") != "conversation" and x.get("status") == "refuted"
        ]

    monkeypatch.setattr(fs, "_obituary_sources", _old_path)
    _live, wrong = _served_wrong_over_live_rows(monkeypatch)
    records = {r["coach"]: r for r in wrong["predictions"]["by_coach"]}
    with pytest.raises(AssertionError, match="explorer: 23 obituaries vs a record of 3 refuted"):
        _assert_obituaries_are_the_record("explorer", records["explorer"], wrong)


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


# ── #4185: a stored pre-fix read whose dated logging gap the served record contradicts ──
# The live wire (public /api/coach/{nutrition,physical}_coach recent_outputs + /api/nutrition_overview,
# read 2026-09-29): the nutrition coach's 09-23/24/25 reads say logging stopped after September 19th
# and the physical coach's 09-13 read says after September 10th — the served record has a log on every
# day through 09-26. Rebuilt into the stored OUTPUT# shape and served through the REAL _recent_outputs.
_GAP_FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "coach_superseded_gap_4185", "live_wire_2026-09-29.json")))


def _gap_rows(coach_id):
    rows = []
    for o in _GAP_FX["coaches"][coach_id]:
        row = {"pk": f"COACH#{coach_id}", "sk": f"OUTPUT#{o['date']}#daily_brief", "created_at": o["generated_at"]}
        if o.get("summary"):
            row["public_summary"] = o["summary"]
        if o.get("data_through"):
            row["data_through"] = o["data_through"]
        rows.append(row)
    return rows


def _served_recent(monkeypatch, coach_id, *, macrofactor=True):
    mf = [{"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{d}", "date": d} for d in _GAP_FX["nutrition_overview"]["trend_dates"]]
    routes = {f"COACH#{coach_id}": _gap_rows(coach_id), "USER#matthew#SOURCE#macrofactor": mf if macrofactor else []}
    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=lambda _t, **kw: _fake_query_by_pk(routes)(**kw)))
    return api._recent_outputs(coach_id)


def test_the_four_pre_fix_gap_reads_are_served_superseded_and_nothing_else(monkeypatch):
    """Exactly the four live reads — nutrition 09-23/24/25, physical 09-13 — lose their false summary and
    carry `superseded`; every other read (including the post-fix 09-28/29 reads that mention September 19th)
    is served byte-for-byte. Mutation controls: drop the `served_last_log > d` comparison or the pre-fix
    condition — more reads supersede and the set assertion reds; remove the `apply` call — none do."""
    assert _GAP_FX["nutrition_overview"]["nutrition"]["latest_date"] == "2026-09-26"
    hit = {}
    for cid in ("nutrition_coach", "physical_coach"):
        served = _served_recent(monkeypatch, cid)
        wire = _GAP_FX["coaches"][cid]
        assert [o["date"] for o in served] == [o["date"] for o in wire]
        for o, w in zip(served, wire):
            if o.get("superseded"):
                hit[(cid, o["date"])] = o["superseded"]["claimed_logging_stopped_after"]
                assert o["summary"] is None and o["superseded"]["served_last_log"] == "2026-09-26"
                assert o["superseded"]["note"] == "superseded — generated before the logging-record fix"
            else:
                assert o["summary"] == (w["summary"] or ""), (cid, o["date"])
    assert hit == {
        ("nutrition_coach", "2026-09-25"): "2026-09-19",
        ("nutrition_coach", "2026-09-24"): "2026-09-19",
        ("nutrition_coach", "2026-09-23"): "2026-09-19",
        ("physical_coach", "2026-09-13"): "2026-09-10",
    }


def test_an_unread_or_uncontradicting_record_supersedes_nothing(monkeypatch):
    """ADR-104: no macrofactor rows (an unread/empty record) contradicts no claim — every read passes
    through; and a claimed stop the record agrees with (last log ON the claimed date) is not superseded."""
    served = _served_recent(monkeypatch, "nutrition_coach", macrofactor=False)
    assert not any(o.get("superseded") for o in served)
    from web import superseded_gap_reads as g

    wire = _GAP_FX["coaches"]["nutrition_coach"]
    assert not any(o.get("superseded") for o in g.mark(wire, "2026-09-19"))
    assert sum(1 for o in g.mark(wire, "2026-09-20") if o.get("superseded")) == 3


def test_only_a_pre_fix_read_is_superseded_a_post_fix_one_is_left_to_the_gate():
    """The same 09-25 sentence written AFTER #4227 (stamped `data_through`, or generated after the fix
    instant) is not superseded here: a post-fix read was produced against the served record and judged by
    the #4227 served-fact gate — this filter only repairs the stored past. Mutation control: make
    `_before_fix` return True — both reds."""
    from web import superseded_gap_reads as g

    (dark,) = [o for o in _GAP_FX["coaches"]["nutrition_coach"] if o["date"] == "2026-09-25"]
    assert g.mark([dark], "2026-09-26")[0].get("superseded")
    stamped = {**dark, "data_through": "2026-09-24"}
    later = {**dark, "generated_at": "2026-09-28T17:03:12.000000+00:00"}
    assert [o.get("superseded") for o in g.mark([stamped, later], "2026-09-26")] == [None, None]
