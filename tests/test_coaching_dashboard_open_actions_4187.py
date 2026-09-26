"""tests/test_coaching_dashboard_open_actions_4187.py — #4187: the coaching-
dashboard door's "what should I do" slot (`open_actions`) served `[]` while
`/api/coach/{id}.dossier.commitments` held pending commitments one endpoint
over (`lambdas/web/site_api_lambda.py::_dispatch_route`, the
`/api/coaching-dashboard` branch — historically queried a `coach_actions`
partition that never carried a single record).

The fix reuses `web.site_api_coach._dossier_block` — the EXACT reader
`/api/coach/{id}` serves `dossier.commitments` from — rather than opening a
second reader of the COMMITMENT# rows. This file pins:

  1. a fixture of two coaches' dossiers (one pending commitment due
     2026-10-02, one completed) -> `open_actions` carries exactly the
     pending one, with every field the issue names;
  2. a mutation control: the OLD behaviour (`open_actions == []` regardless
     of pending dossier state) must not recur;
  3. a contract test: every commitment `/api/coach/{id}` serves with
     `status == "pending"` (across the roster) appears in `open_actions`,
     through the SAME fixture as the dossier endpoint;
  4. soonest-due-first ordering, with a no-due-date commitment sorted last
     rather than first.

Offline: no AWS. `web.site_api_coach.table` (what `_dossier_block` reads,
via its own module globals — NOT `web.site_api_lambda.table`, a different
name binding to the same object only in production) is patched to a
pk/sk-dispatching `FakeDdbTable`, mirroring `tests/test_coach_dossier.py`'s
own site-layer harness. `web.site_api_lambda.table` is patched separately
(empty) for the dashboard's own OUTPUT#/coach-thread reads, which this
fixture does not exercise.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from ai import budget_guard  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_coach as coach_api,  # noqa: E402
    site_api_lambda as L,  # noqa: E402
)

_DASHBOARD_EVENT = {"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}

# Two coaches carrying commitments; a third with a pending-but-undated-due
# commitment exercises the nulls-last sort. All are in OPERATIONAL_COACH_IDS
# (config/personas.json), so the registry-derived roster reaches them.
_PHYSICAL_PENDING = {
    "pk": "COACH#physical_coach",
    "sk": "COMMITMENT#commit_protein",
    "created_date": "2026-09-25",
    "commitment_natural": "reach 170 g protein per day for seven consecutive days",
    "status": "pending",
    "due_date": "2026-10-02",
    "action_check": {"metric": "protein", "direction": "at_least"},
}
_NUTRITION_COMPLETED = {
    "pk": "COACH#nutrition_coach",
    "sk": "COMMITMENT#commit_done",
    "created_date": "2026-09-10",
    "commitment_natural": "log macros daily for a week",
    "status": "completed",
    "due_date": "2026-09-17",
}
_NUTRITION_PENDING_NO_DUE = {
    "pk": "COACH#nutrition_coach",
    "sk": "COMMITMENT#commit_undated",
    "created_date": "2026-09-20",
    "commitment_natural": "cut added sugar to under 25g on training days",
    "status": "pending",
}
_SLEEP_PENDING_SOONER = {
    "pk": "COACH#sleep_coach",
    "sk": "COMMITMENT#commit_lights_out",
    "created_date": "2026-09-24",
    "commitment_natural": "lights off by 10pm through the weekend",
    "status": "pending",
    "due_date": "2026-09-28",
}

_ROWS_BY_PK = {
    "COACH#physical_coach": [_PHYSICAL_PENDING],
    "COACH#nutrition_coach": [_NUTRITION_COMPLETED, _NUTRITION_PENDING_NO_DUE],
    "COACH#sleep_coach": [_SLEEP_PENDING_SOONER],
}


def _cond_parts(cond):
    """(pk, sk_prefix_or_None) out of a boto3 Key condition — mirrors
    tests/test_coach_dossier.py's own hook-dispatch helper."""
    expr = cond.get_expression()
    if expr.get("operator") == "AND":
        a, b = expr["values"]
        pk = a.get_expression()["values"][1]
        sk = b.get_expression()["values"][1]
        return pk, sk
    return expr["values"][1], None


def _query_hook(table, **kw):
    pk, sk = _cond_parts(kw["KeyConditionExpression"])
    if pk in _ROWS_BY_PK and (sk or "").startswith("COMMITMENT#"):
        return {"Items": [dict(i) for i in _ROWS_BY_PK[pk]]}
    return {"Items": []}  # learnings/docket/relationship/corrections — all honest-empty


def _get_item_hook(table, key, **kw):
    return {}  # no RELATIONSHIP#state seeded — not exercised by this fixture


def _dossier_table():
    return FakeDdbTable(query_hook=_query_hook, get_item_hook=_get_item_hook)


def _dashboard_body(monkeypatch):
    # `_dossier_block` (imported into site_api_lambda from site_api_coach) reads
    # `table` off site_api_coach's OWN module globals at call time — a SEPARATE
    # name binding from `site_api_lambda.table` in tests (both point at the same
    # boto3 object only at prod cold-start). Both must be patched.
    monkeypatch.setattr(coach_api, "table", _dossier_table())
    monkeypatch.setattr(L, "table", FakeDdbTable())
    monkeypatch.setattr(L, "_integrator_digest", lambda: None)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    resp = L.lambda_handler(dict(_DASHBOARD_EVENT), None)
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def test_open_actions_serves_the_pending_commitment_with_every_field(monkeypatch):
    body = _dashboard_body(monkeypatch)
    physical = [a for a in body["open_actions"] if a["coach_id"] == "physical"]
    assert len(physical) == 1, body["open_actions"]
    action = physical[0]
    assert action == {
        "coach_id": "physical",
        "coach_name": "Dr. Max Reyes",
        "text": "reach 170 g protein per day for seven consecutive days",
        "asked_on": "2026-09-25",
        "due": "2026-10-02",
        "status": "pending",
        "check": {"metric": "protein", "direction": "at_least"},
        "evidence_link": "/data/nutrition/",
    }


def test_open_actions_excludes_completed_commitments(monkeypatch):
    body = _dashboard_body(monkeypatch)
    texts = [a["text"] for a in body["open_actions"]]
    assert "log macros daily for a week" not in texts


def test_open_actions_sorts_soonest_due_first_nulls_last(monkeypatch):
    body = _dashboard_body(monkeypatch)
    ordered = [(a["coach_id"], a["due"]) for a in body["open_actions"]]
    assert ordered == [
        ("sleep", "2026-09-28"),
        ("physical", "2026-10-02"),
        ("nutrition", None),
    ]


def test_open_actions_is_no_longer_the_old_always_empty_list(monkeypatch):
    """Mutation control (#4187): before the fix, `open_actions` was `[]`
    regardless of how many dossier commitments were pending — it queried a
    `coach_actions` partition that never carried a record. A revert back to
    that dead reader must turn this test red."""
    body = _dashboard_body(monkeypatch)
    assert body["open_actions"] != []
    assert len(body["open_actions"]) == 3


def test_every_pending_commitment_the_coach_endpoint_serves_appears_in_open_actions(monkeypatch):
    """Contract test: the SAME fixture, read through BOTH paths. Every
    commitment `/api/coach/{id}` serves under `dossier.commitments` with
    `status == "pending"` must appear in `/api/coaching-dashboard.open_actions`
    — same coach, same text. This is what makes `_dossier_block` reuse (not a
    second COMMITMENT# reader) an enforced invariant, not just an intent."""
    monkeypatch.setattr(coach_api, "table", _dossier_table())
    monkeypatch.setattr(L, "table", FakeDdbTable())
    monkeypatch.setattr(L, "_integrator_digest", lambda: None)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)

    expected = []
    for coach_id in ("physical_coach", "nutrition_coach", "sleep_coach"):
        resp = coach_api.handle_coach({"rawPath": f"/api/coach/{coach_id}"})
        assert resp["statusCode"] == 200, resp
        dossier = json.loads(resp["body"])["dossier"]
        for commitment in dossier["commitments"]:
            if commitment.get("status") == "pending":
                expected.append((coach_id.replace("_coach", ""), commitment["text"]))

    assert expected, "fixture must seed at least one pending commitment"

    body = L.lambda_handler(dict(_DASHBOARD_EVENT), None)
    assert body["statusCode"] == 200
    open_actions = json.loads(body["body"])["open_actions"]
    served = [(a["coach_id"], a["text"]) for a in open_actions]
    for pair in expected:
        assert pair in served, f"{pair} served by /api/coach/{{id}} but missing from open_actions"
