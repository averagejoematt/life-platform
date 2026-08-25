"""#3118 — the two site-API write paths DIL-025's census marked **N** on replay.

The census (docs/IDEMPOTENCY.md §4) found this surface mostly well-guarded and named
its own model: the vote/follow/certify family writes a *conditional dedup row first*,
so the counter `ADD` is structurally unreachable a second time. Two doors departed.

**1. The board follow-up append.** Its ConditionExpression enforced the cap and the
originating IP and nothing else, so a duplicate delivery of the SAME follow-up
appended the turn twice and burned two of the reader's three turns — a reader-visible
loss of a paid-for AI interaction. Turn identity is now first-class at two levels:
the handler recognises a redelivery BEFORE any model spend and serves the stored
answer, and the conditional write records a `turn_ids` set so the truly-simultaneous
delivery the pre-check cannot see is refused at the database.

**2. The date-prefixed S3 capture doors.** `submit_finding` and `board_question` were
content-addressed *within a wall-clock prefix* and written unconditionally, so a retry
crossing the UTC day/month boundary landed on a SECOND key, and — worse — a replay of
an already-moderated item overwrote `status` back to `"pending"`, silently undoing a
moderation decision. Both now key on the content hash ALONE and write with S3's
`IfNoneMatch="*"` conditional put, the exact analogue of the `attribute_not_exists`
the strongest door on the surface (`/api/experiment_suggest`) already used.

Every test here drives the REAL handlers offline: the AI half through
`site_api_ai_lambda._handle_board_followup` against the shared `tests/fakes.py`
table double (whose update hook now emulates the turn-identity condition — fixture
must be the wire), the S3 half through `site_api_lambda.lambda_handler` on the #1438
E2E harness (whose fake S3 now REFUSES a conditional put on an existing key, so a
"stored" answer cannot come from a wire that is unable to say no).

Each pair is mutation-proved: the second call's effect is asserted against the first
call's recorded state, so reverting either guard turns a passing test red rather than
leaving it silently vacuous.
"""

from __future__ import annotations

import json
import os
import sys
import time

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
from bundle_stubs import stub_bundled_module  # noqa: E402
from fakes import FakeDdbTable, json_safe_put_hook, make_session_update_hook  # noqa: E402

TOKEN = "r" * 32  # matches the minted token shape; the store never sees a raw token
IP = "iphash-3118"
PERSONA = "sleep_coach"
Q = "Does the late caffeine actually explain the REM dip?"


# ══════════════════════════════════════════════════════════════════════════════
# Half 1 — the board follow-up append (site-api-ai)
# ══════════════════════════════════════════════════════════════════════════════


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


class _FakeBedrock:
    """Records every invocation — the assertion that a replay costs $0."""

    reqs: list = []

    @classmethod
    def invoke(cls, req):
        cls.reqs.append(req)
        return {"content": [{"type": "text", "text": "REM held steady; the caffeine is not the driver."}], "usage": {}}


@pytest.fixture()
def board(monkeypatch):
    """A live one-coach thread + a recording Bedrock, wired into the real handler."""
    ai = _ai()
    table = FakeDdbTable(put_item_hook=json_safe_put_hook, update_item_hook=make_session_update_hook(enforce_cap=True))
    table.store[(f"BOARDSESS#{TOKEN}", "SESSION")] = {
        "pk": f"BOARDSESS#{TOKEN}",
        "sk": "SESSION",
        "ip_hash": IP,
        "followup_count": 0,
        "threads": {PERSONA: [{"q": "How is my sleep?", "a": "Steady, seven hours."}]},
        "ttl": int(time.time()) + 3000,
    }
    monkeypatch.setattr(ai, "table", table)
    monkeypatch.setattr(ai, "_get_anthropic_key", lambda: "test-key")
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda *a, **k: {})
    monkeypatch.setattr(ai, "_write_board_interaction", lambda *a, **k: None)

    class _B(_FakeBedrock):
        pass

    _B.reqs = []
    stub_bundled_module(monkeypatch, "ai.bedrock_client", _B)
    return ai, table, _B


def _followup(ai, question):
    resp = ai._handle_board_followup({"session_token": TOKEN, "persona": PERSONA, "question": question}, IP)
    return resp["statusCode"], json.loads(resp["body"])


def _session(table):
    return table.store[(f"BOARDSESS#{TOKEN}", "SESSION")]


def test_a_redelivered_followup_does_not_burn_a_second_turn(board):
    """THE defect: the reader retried once and lost two of three turns."""
    ai, table, bedrock = board

    status, first = _followup(ai, Q)
    assert status == 200
    assert first["followups_remaining"] == 2
    after_first = {
        "count": _session(table)["followup_count"],
        "turns": len(_session(table)["threads"][PERSONA]),
        "calls": len(bedrock.reqs),
    }
    assert after_first == {"count": 1.0, "turns": 2, "calls": 1}

    # The redelivery — byte-identical body, same session, same network.
    status, replay = _followup(ai, Q)
    assert status == 200
    assert replay["replay"] is True
    assert replay["response"] == first["response"], "a replay must serve the answer the reader already paid for"
    assert replay["followups_remaining"] == 2, "the retry consumed a turn"
    assert _session(table)["followup_count"] == after_first["count"], "followup_count moved on a replay"
    assert len(_session(table)["threads"][PERSONA]) == after_first["turns"], "the same turn was appended twice"
    assert len(bedrock.reqs) == after_first["calls"], "a replay bought model time"


def test_a_replay_is_recognised_through_whitespace_and_case(board):
    """A retrying client may re-wrap the body; the identity is the normalised text."""
    ai, table, bedrock = board
    _followup(ai, Q)
    status, replay = _followup(ai, f"  {Q.upper()}\n ")
    assert (status, replay.get("replay")) == (200, True)
    assert len(bedrock.reqs) == 1


def test_a_genuinely_new_followup_still_costs_a_turn(board):
    """The other direction — the guard must not swallow real work."""
    ai, table, bedrock = board
    _followup(ai, Q)
    status, second = _followup(ai, "And what about the magnesium — worth keeping?")
    assert status == 200
    assert "replay" not in second
    assert second["followups_remaining"] == 1
    assert _session(table)["followup_count"] == 2.0
    assert len(_session(table)["threads"][PERSONA]) == 3
    assert len(bedrock.reqs) == 2


def test_re_asking_the_opening_question_is_a_real_followup_not_a_replay(board):
    """Turn 0 of a thread is the board_ask opening, not a follow-up. Echoing it
    back ("you said X — why?") must still be a genuine, billable turn."""
    ai, table, bedrock = board
    status, body = _followup(ai, "How is my sleep?")
    assert (status, body.get("replay")) == (200, None)
    assert _session(table)["followup_count"] == 1.0
    assert len(bedrock.reqs) == 1


def test_the_database_refuses_a_duplicate_turn_the_pre_check_cannot_see(board):
    """The simultaneous-delivery race: two deliveries both read the session before
    either writes, so the handler's pre-check clears both. The ConditionExpression
    is what makes the second append impossible."""
    ai, table, _ = board
    assert ai._append_board_turn(TOKEN, IP, PERSONA, Q, "first answer") is True
    assert ai._append_board_turn(TOKEN, IP, PERSONA, Q, "second answer") is False, "the same turn was accepted twice"
    assert _session(table)["followup_count"] == 1.0
    assert len(_session(table)["threads"][PERSONA]) == 2


def test_the_condition_names_turn_identity_alongside_the_cap_and_the_ip(board):
    """The census row's exact claim, pinned: the condition enforced the cap and the
    IP and *never* turn identity."""
    ai, table, _ = board
    ai._append_board_turn(TOKEN, IP, PERSONA, Q, "an answer")
    call = table.updates[-1]
    cond = call["ConditionExpression"]
    assert "followup_count < :cap" in cond and "ip_hash = :ip" in cond
    assert "contains(turn_ids, :tid)" in cond
    assert "ttl" not in call["UpdateExpression"], "a follow-up must not extend the 1h session life"


def test_the_replay_survives_the_whole_function_url_envelope(board, monkeypatch):
    """#3118 acceptance box 5: the wire shape, not just the handler. A redelivered
    Function-URL POST goes through routing, the budget check and the real per-IP
    rate limiter before it reaches the follow-up path."""
    ai, table, bedrock = board
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_rate_limit_identity", lambda _e: "203.0.113.9")
    monkeypatch.setattr(ai, "_ddb_rate_check", lambda *a, **k: (True, 4, 0))
    monkeypatch.setattr(ai, "table", table)
    # The follow-up path derives its own ip_hash from the same identity the mint used.
    import hashlib

    table.store[(f"BOARDSESS#{TOKEN}", "SESSION")]["ip_hash"] = hashlib.sha256(b"203.0.113.9").hexdigest()[:16]

    def _post():
        return ai.lambda_handler(
            {
                "rawPath": "/api/board_ask",
                "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
                "headers": {"CloudFront-Viewer-Address": "203.0.113.9:16225"},
                "body": json.dumps({"session_token": TOKEN, "persona": PERSONA, "question": Q}),
            },
            None,
        )

    first = json.loads(_post()["body"])
    assert first.get("response") and "replay" not in first
    second = json.loads(_post()["body"])
    assert second["replay"] is True and second["response"] == first["response"]
    assert second["followups_remaining"] == first["followups_remaining"]
    assert len(bedrock.reqs) == 1, "the wire replay bought a second model call"
    assert _session(table)["followup_count"] == 1.0


def test_the_same_question_to_a_different_coach_is_a_different_turn():
    from web import site_api_ai_session as sess

    assert sess.turn_id("sleep_coach", Q) != sess.turn_id("labs_coach", Q)
    assert sess.turn_id("sleep_coach", Q) == sess.turn_id("sleep_coach", f" {Q.upper()} ")


# ══════════════════════════════════════════════════════════════════════════════
# Half 2 — the date-prefixed S3 capture doors (site-api)
# ══════════════════════════════════════════════════════════════════════════════

FINDING = {
    "metric_a": "sleep",
    "metric_b": "hrv",
    "finding": "e2e-test finding: more sleep tracks higher hrv across the whole cycle",
}
QUESTION = {"question": "e2e-test question: is the morning-daylight protocol moving sleep onset?"}

DOORS = [
    ("/api/submit_finding", FINDING, "generated/findings/", "finding_id"),
    ("/api/board_question", QUESTION, "generated/board_questions/", "id"),
]


@pytest.fixture()
def wp(monkeypatch):
    return _e2e.Harness(monkeypatch)


def _only_key(wp, prefix):
    keys = {k for k in wp.s3.objects if k.startswith(prefix)}
    assert len(keys) == 1, f"expected exactly one object under {prefix}, found {sorted(keys)}"
    return keys.pop()


@pytest.mark.parametrize("path,body,prefix,id_field", DOORS, ids=["submit_finding", "board_question"])
def test_a_capture_key_carries_no_clock(wp, path, body, prefix, id_field):
    """The duplication mechanism was the wall-clock prefix. A key with no date in
    it has no boundary to cross."""
    status, first = wp.call(path, body=body)
    assert status == 200
    key = _only_key(wp, prefix)
    assert key == f"{prefix}{first[id_field]}.json"


@pytest.mark.parametrize("path,body,prefix,id_field", DOORS, ids=["submit_finding", "board_question"])
def test_a_retry_across_the_utc_boundary_lands_on_the_same_object(wp, monkeypatch, path, body, prefix, id_field):
    """The census's exact failure: a retry that crossed midnight (or the month)
    duplicated the pending item. The harness clock is advanced by a day AND a
    month between the two identical submissions."""
    from datetime import datetime, timedelta, timezone

    status, first = wp.call(path, body=body)
    assert status == 200
    after_first = sorted(wp.s3.objects)

    later = _e2e._FROZEN_DT + timedelta(days=40)

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return later.astimezone(tz) if tz else later.replace(tzinfo=None)

    monkeypatch.setattr(wp.social, "datetime", _Later)
    monkeypatch.setattr(wp.social, "_FALLBACK_RATE_STORE", {})  # a new hour would reset the limiter too
    assert _Later.now(timezone.utc).strftime("%Y-%m-%d") != _e2e._FROZEN_DT.strftime("%Y-%m-%d")

    status, second = wp.call(path, body=body)
    assert status == 200
    assert second[id_field] == first[id_field]
    assert sorted(wp.s3.objects) == after_first, "a boundary-crossing retry minted a second moderation row"


@pytest.mark.parametrize("path,body,prefix,id_field", DOORS, ids=["submit_finding", "board_question"])
def test_a_replay_cannot_un_moderate_an_already_decided_item(wp, path, body, prefix, id_field):
    """The severe half: the unconditional put reset `status` to "pending", silently
    reversing a moderation decision. Mutation-proved — the stored object is moved to
    a decided state between the two identical submissions."""
    assert wp.call(path, body=body)[0] == 200
    key = _only_key(wp, prefix)

    decided = json.loads(wp.s3.objects[key])
    decided.update({"status": "answered", "moderated_at": "2026-08-24T00:00:00+00:00", "note": "published"})
    wp.s3.objects[key] = json.dumps(decided).encode()

    status, replay = wp.call(path, body=body)
    assert status == 200
    assert replay["duplicate"] is True, "a replay of a moderated item reported itself as a fresh capture"
    stored = json.loads(wp.s3.objects[key])
    assert stored["status"] == "answered", "the replay reset a moderation decision back to pending"
    assert stored["note"] == "published", "the moderator's own fields were overwritten"


@pytest.mark.parametrize("path,body,prefix,id_field", DOORS, ids=["submit_finding", "board_question"])
def test_a_genuinely_new_submission_still_reaches_moderation(wp, path, body, prefix, id_field):
    """The other direction — the conditional put must not swallow real submissions."""
    assert wp.call(path, body=body)[0] == 200
    field = "finding" if path.endswith("submit_finding") else "question"
    status, second = wp.call(path, body=dict(body, **{field: body[field] + " (a different observation entirely)"}))
    assert status == 200
    assert second["duplicate"] is False
    assert len({k for k in wp.s3.objects if k.startswith(prefix)}) == 2
    for k in {k for k in wp.s3.objects if k.startswith(prefix)}:
        assert json.loads(wp.s3.objects[k])["status"] == "pending"


def test_the_conditional_put_fails_open_when_the_runtime_cannot_express_it():
    """A Lambda runtime whose botocore predates `IfNoneMatch` must still capture the
    reader's submission. Losing a submission is worse than a duplicate pending row."""
    from botocore.exceptions import ParamValidationError
    from web.site_api_capture_store import put_capture_record

    class _OldBotocore:
        def __init__(self):
            self.objects = {}

        def put_object(self, Bucket=None, Key=None, Body=None, **kw):
            if "IfNoneMatch" in kw:
                raise ParamValidationError(report='Unknown parameter in input: "IfNoneMatch"')
            self.objects[Key] = Body

        def head_object(self, Bucket=None, Key=None, **_kw):
            if Key not in self.objects:
                raise Exception("NoSuchKey")
            return {}

    s3 = _OldBotocore()
    assert put_capture_record(s3, "b", "k.json", {"id": "k"}, '{"id": "k"}', door="t") is True
    assert s3.objects["k.json"] == '{"id": "k"}'
    # ...and it still degrades to a no-op rather than clobbering what is already there.
    assert put_capture_record(s3, "b", "k.json", {"id": "k"}, '{"id": "k", "status": "x"}', door="t") is False
    assert s3.objects["k.json"] == '{"id": "k"}'


def test_an_unclassified_s3_error_still_reaches_the_callers_503():
    """Fail-open is scoped to the two known shapes; a real outage must not read as
    a successful capture."""
    from web.site_api_capture_store import put_capture_record

    class _Down:
        def put_object(self, **_kw):
            raise RuntimeError("s3 unavailable")

    with pytest.raises(RuntimeError):
        put_capture_record(_Down(), "b", "k.json", {"id": "k"}, "{}", door="t")
