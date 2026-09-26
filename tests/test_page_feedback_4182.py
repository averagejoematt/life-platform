"""#4182 — POST /api/page_feedback, the two-question reader door.

"Did this page make sense?" (yes / partly / no) and "what were you looking for?"
(optional free text) — answered from any page's footer, read weekly by Matthew.

Every test runs the WIRE path: a Function-URL envelope carrying
`CloudFront-Viewer-Address` → `site_api_lambda.lambda_handler` → the real route table →
the real handler → the real DynamoDB-backed rate limiter, against the #1438 E2E
harness whose `E2ETable.put_item` refuses a conditional put on an existing key
(fixture = wire). The guard ORDER is pinned by the negative cases: each refusal must
leave the feedback partition empty.
"""

from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
import test_e2e_write_paths as _e2e  # noqa: E402 — the #1438 real-wire harness

PATH = "/api/page_feedback"
PK = "USER#matthew#SOURCE#reader_feedback"
GOOD = {"page": "/coaching/by-coach/", "made_sense": "partly", "looking_for": "which coach owns the sleep numbers"}


@pytest.fixture()
def wp(monkeypatch):
    return _e2e.Harness(monkeypatch)


def _rows(wp):
    return {sk: it for (pk, sk), it in wp.table.store.items() if pk == PK}


# ── the happy path ───────────────────────────────────────────────────────────


def test_a_valid_answer_writes_one_row_with_its_fields(wp):
    status, body = wp.call(PATH, body=GOOD)
    assert status == 200
    assert body["ok"] is True and body["duplicate"] is False and len(body["id"]) == 12
    rows = _rows(wp)
    assert list(rows) == [f"FEEDBACK#{body['id']}"]
    row = rows[f"FEEDBACK#{body['id']}"]
    assert row["page"] == GOOD["page"]
    assert row["made_sense"] == "partly"
    assert row["looking_for"] == GOOD["looking_for"]
    assert row["status"] == "unread"
    assert row["submitted_at"].startswith(_e2e._FROZEN_DT.strftime("%Y-%m-%d")), "submitted_at is a stored FIELD from the clock"
    # No email field, no raw address, no ip_hash: the row carries only the answer.
    assert "email" not in row and "ip_hash" not in row
    assert _e2e.IP_A not in json.dumps(row)


def test_looking_for_is_optional(wp):
    status, body = wp.call(PATH, body={"page": "/", "made_sense": "yes"})
    assert status == 200
    assert _rows(wp)[f"FEEDBACK#{body['id']}"]["looking_for"] == ""


def test_looking_for_is_html_stripped_and_capped(wp):
    status, body = wp.call(PATH, body=dict(GOOD, looking_for="<b>bold</b> " + "x" * 900))
    assert status == 200
    stored = _rows(wp)[f"FEEDBACK#{body['id']}"]["looking_for"]
    assert "<" not in stored and len(stored) == 500


# ── replay ───────────────────────────────────────────────────────────────────


def test_a_replay_is_a_true_no_op_reported_as_duplicate(wp):
    s1, first = wp.call(PATH, body=GOOD)
    s2, second = wp.call(PATH, body=GOOD)
    assert (s1, s2) == (200, 200)
    assert {k: v for k, v in second.items() if k != "_meta"} == {"ok": True, "id": first["id"], "duplicate": True}
    assert len(_rows(wp)) == 1
    assert wp.table.written_pks.count(PK) == 1, "the replay performed a second write"


def test_a_different_answer_on_the_same_page_is_a_new_row(wp):
    wp.call(PATH, body=GOOD)
    wp.call(PATH, body=dict(GOOD, made_sense="no"))
    assert len(_rows(wp)) == 2


# ── refusals: each is a 4xx and leaves the partition empty ──────────────────


@pytest.mark.parametrize("raw", ["[]", '"a string"', "7", "null", "true"])
def test_a_non_object_body_is_a_400_not_a_5xx(wp, raw):
    event = _e2e.Harness.event(PATH, "POST", None)
    event["body"] = raw
    resp = wp.api.lambda_handler(event, None)
    assert resp["statusCode"] == 400, raw
    assert _rows(wp) == {}


def test_invalid_json_is_a_400(wp):
    event = _e2e.Harness.event(PATH, "POST", None)
    event["body"] = "{not json"
    assert wp.api.lambda_handler(event, None)["statusCode"] == 400
    assert _rows(wp) == {}


@pytest.mark.parametrize("made_sense", ["maybe", "YES", "", None, 1, ["yes"], {"a": "yes"}])
def test_a_bad_made_sense_is_a_400(wp, made_sense):
    status, _ = wp.call(PATH, body=dict(GOOD, made_sense=made_sense))
    assert status == 400
    assert _rows(wp) == {}


@pytest.mark.parametrize(
    "page",
    [
        None,
        999,
        "",
        "data/",  # no leading slash
        "/Data/",  # uppercase
        "/data/?q=1",  # query string
        "https://averagejoematt.com/data/",
        "/data/\n",  # a trailing newline must not slip past `$`
        "/<script>/",
        "/" + "a" * 81,  # over the 80-char path cap
    ],
)
def test_a_bad_page_is_a_400(wp, page):
    status, _ = wp.call(PATH, body=dict(GOOD, page=page))
    assert status == 400
    assert _rows(wp) == {}


def test_a_blocked_vice_answer_is_refused_with_no_write(wp, monkeypatch):
    monkeypatch.setattr(wp.social, "_is_blocked_vice", lambda text: "forbidden-term" in (text or ""))
    status, _ = wp.call(PATH, body=dict(GOOD, looking_for="the forbidden-term page"))
    assert status == 400
    assert _rows(wp) == {}


def test_the_sixth_submission_in_an_hour_is_a_429(wp):
    for i in range(5):
        status, _ = wp.call(PATH, body=dict(GOOD, looking_for=f"distinct answer {i}"))
        assert status == 200, i
    status, _ = wp.call(PATH, body=dict(GOOD, looking_for="a sixth distinct answer"))
    assert status == 429
    assert len(_rows(wp)) == 5


def test_the_rate_limit_is_per_reader(wp):
    for i in range(5):
        wp.call(PATH, body=dict(GOOD, looking_for=f"distinct answer {i}"), ip=_e2e.IP_A)
    assert wp.call(PATH, body=GOOD, ip=_e2e.IP_B)[0] == 200


def test_an_unreadable_salt_fails_closed_with_no_write(wp, monkeypatch):
    from web import site_api_social_engage as _engage

    def _boom(*_a, **_k):
        raise RuntimeError("secrets manager unavailable")

    monkeypatch.setattr(_engage, "_get_secret", _boom)
    status, _ = wp.call(PATH, body=GOOD)
    assert status == 503
    assert _rows(wp) == {}


def test_a_storage_failure_is_a_503_not_a_silent_success(wp, monkeypatch):
    def _down(**_kw):
        raise RuntimeError("dynamodb is having a day")

    monkeypatch.setattr(wp.table, "put_item", _down)
    status, _ = wp.call(PATH, body=GOOD)
    assert status == 503


def test_get_is_refused_by_the_route_table(wp):
    status, _ = wp.call(PATH, method="GET")
    assert status == 405
