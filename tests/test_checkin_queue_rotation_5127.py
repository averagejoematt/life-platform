"""tests/test_checkin_queue_rotation_5127.py — the coach check-in queue unsticks and rotates (#5127).

The specimen: from 2026-10-10 the queue held three open nutrition questions, each driven by the
food-delivery channel ("Food delivery is the longest-dark manual channel (196d dark)"). #5006 paused
that source, but an open question never left the queue, so no coach was asked anything new.

Pinned here: a question on a paused source is retired with its reason recorded (status `retired`,
never a skip); an open question rotates out after the window; the asking coach rotates instead of
the last asker winning the dark-channel preference again; and the nightly queue-age check alarms on
a queue that was served past its rotation (and on the paused-source specimen), not on a quiet week.
Every test runs on a frozen clock (#4848).
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

from coach import coach_checkin as cc  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from operational import coach_checkin_queue_qa as qq  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, Check  # noqa: E402

import mcp.tools_coach_checkin as tcc  # noqa: E402

ASKED = "2026-10-11T02:13:53Z"
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)  # ~10 h after the specimen was asked
SPECIMEN_REASON = "Food delivery is the longest-dark manual channel (196d dark)"


def _row(uid, coach="nutrition", asked=ASKED, reason=SPECIMEN_REASON, **over):
    item = {
        "pk": cc.checkin_pk(coach),
        "sk": f"CHECKIN#{asked[:10]}#{uid}",
        "record_type": "coach_checkin",
        "coach_id": coach,
        "coach_name": coach,
        "question": "What's been going on this week?",
        "tags": [],
        "status": cc.STATUS_OPEN,
        "asked_at": asked,
        "provenance": "mcp",
        "context_reason": reason,
        "generated_by": "bedrock",
    }
    item.update(over)
    return item


def _specimen():
    return [_row("a7c377cb"), _row("681314b9"), _row("54ada794")]


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(cc, "utcnow", lambda: NOW)
    monkeypatch.setattr(cc, "_cycle_cache", {"value": None, "read": True})


def _wire(monkeypatch, fake, manual_signal=None):
    monkeypatch.setattr(tcc, "_table_ref", fake)
    monkeypatch.setattr(tcc, "_manual_source_signal", lambda: manual_signal or [])
    monkeypatch.setattr(tcc, "_presence_snapshot", lambda: {})
    monkeypatch.setattr(tcc, "_adaptive_mode_snapshot", lambda: {})
    monkeypatch.setattr(tcc, "_coach_bio", lambda cid: "")
    monkeypatch.setattr(cc, "generate_questions", lambda *a, **k: [{"question": "How are evenings feeling?", "tags": ["sleep"]}])


# ── the specimen ─────────────────────────────────────────────────────────────


def test_the_three_food_delivery_questions_are_retired_with_the_reason_and_a_new_coach_asks(monkeypatch):
    fake = FakeDdbTable(rows=_specimen())
    _wire(monkeypatch, fake)
    out = tcc.tool_get_coach_checkin_queue({})

    retires = [u for u in fake.updates if ":ret" in u.get("ExpressionAttributeValues", {})]
    assert len(retires) == 3
    for u in retires:
        vals = u["ExpressionAttributeValues"]
        assert vals[":ret"] == cc.STATUS_RETIRED == "retired"
        assert vals[":code"] == cc.RETIRED_SOURCE_PAUSED
        assert "food_delivery is paused" in vals[":why"] and "#5006" in vals[":why"]
        assert u["ConditionExpression"] == "#st = :open"  # an answer that lands first wins
    assert [r["retired_code"] for r in out["retired"]] == [cc.RETIRED_SOURCE_PAUSED] * 3

    assert out["generated"] is True
    assert out["asking_coach"]["coach_id"] != "nutrition"  # the last asker does not get the turn again
    assert len(fake.puts) == 1 and fake.puts[0]["coach_id"] != "nutrition"


def test_a_retire_write_that_loses_the_race_still_leaves_the_question_out(monkeypatch):
    def _cond_fail(table, **kw):
        if ":ret" in kw.get("ExpressionAttributeValues", {}):
            raise RuntimeError("ConditionalCheckFailedException")
        return {}

    fake = FakeDdbTable(rows=_specimen(), update_item_hook=_cond_fail)
    _wire(monkeypatch, fake)
    out = tcc.tool_get_coach_checkin_queue({})
    assert "retired" not in out  # nothing claimed as retired that was not written
    assert all("Food delivery" not in (q.get("context_reason") or "") for q in out["open_questions"])


# ── the pure rules ───────────────────────────────────────────────────────────


def test_question_source_reads_the_key_then_the_legacy_label_and_never_guesses():
    assert cc.question_source({"source_key": "notion", "context_reason": SPECIMEN_REASON}) == "notion"
    assert cc.question_source({"context_reason": SPECIMEN_REASON}) == "food_delivery"
    assert cc.question_source({"context_reason": "Nowhere is the longest-dark manual channel (3d dark)"}) is None
    assert cc.question_source({"context_reason": "rotation — least-recently-asked coach"}) is None
    assert cc.question_source({}) is None


def test_food_delivery_is_paused_in_the_registry():
    assert "food_delivery" in cc.paused_sources()


def test_rotation_window_boundary_and_the_prescription_week():
    paused = set()
    asked = NOW - timedelta(hours=cc.QUEUE_ROTATE_HOURS)
    fresh = _row("f1", coach="mind", asked=(asked + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), reason="rotation")
    due = _row("f2", coach="mind", asked=asked.strftime("%Y-%m-%dT%H:%M:%SZ"), reason="rotation")
    assert cc.retire_verdict(fresh, now=NOW, paused=paused) is None
    code, why = cc.retire_verdict(due, now=NOW, paused=paused)
    assert code == cc.RETIRED_ROTATED and "not a skip" in why

    rx = dict(due, generated_by="prescription_followup")
    assert cc.retire_verdict(rx, now=NOW, paused=paused) is None  # a Horizons follow-up keeps its week
    rx_old = dict(rx, asked_at=(NOW - timedelta(hours=cc.PRESCRIPTION_ROTATE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert cc.retire_verdict(rx_old, now=NOW, paused=paused)[0] == cc.RETIRED_ROTATED

    for status in (cc.STATUS_ANSWERED, cc.STATUS_SKIPPED, cc.STATUS_RETIRED):
        assert cc.retire_verdict(dict(due, status=status), now=NOW, paused=paused) is None


def test_servable_open_drops_what_the_queue_would_retire():
    fresh = _row("ok1", coach="mind", asked="2026-10-11T09:00:00Z", reason="rotation")
    assert cc.servable_open(_specimen() + [fresh], now=NOW) == [fresh]


_COACHES = ["sleep", "nutrition", "training", "mind", "physical", "glucose", "labs", "explorer"]
_DARK = [{"source": "macrofactor", "label": "MacroFactor", "days_since": 30, "stale_days": 2, "coach": "nutrition"}]


def test_the_last_asker_never_wins_the_dark_channel_twice_in_a_row():
    recent = [{"coach_id": "nutrition", "asked_at": ASKED}, {"coach_id": "mind", "asked_at": "2026-10-01T00:00:00Z"}]
    pick = cc.pick_asking_coach_detail(_COACHES, _DARK, recent)
    assert pick["coach"] == "sleep" and pick["source"] is None and "rotation" in pick["reason"]


def test_a_dark_channel_still_wins_for_a_coach_who_did_not_ask_last_and_names_its_source():
    recent = [{"coach_id": "mind", "asked_at": ASKED}]
    pick = cc.pick_asking_coach_detail(_COACHES, _DARK, recent)
    assert pick == {"coach": "nutrition", "reason": "MacroFactor is the longest-dark manual channel (30d dark)", "source": "macrofactor"}
    assert cc.pick_asking_coach(_COACHES, _DARK, recent) == (pick["coach"], pick["reason"])


def test_a_generated_question_records_its_driving_source(monkeypatch):
    fake = FakeDdbTable()
    _wire(monkeypatch, fake, manual_signal=_DARK)
    tcc.tool_get_coach_checkin_queue({})
    assert fake.puts[0]["source_key"] == "macrofactor"


def test_serving_the_queue_stamps_last_served(monkeypatch):
    fresh = _row("ok1", coach="mind", asked="2026-10-11T09:00:00Z", reason="rotation")
    fake = FakeDdbTable(rows=[fresh])
    _wire(monkeypatch, fake)
    out = tcc.tool_get_coach_checkin_queue({})
    assert out["generated"] is False
    served = [u for u in fake.updates if "last_served_at" in u["UpdateExpression"]]
    assert len(served) == 1 and served[0]["Key"] == {"pk": fresh["pk"], "sk": fresh["sk"]}


# ── the nightly queue-age check ──────────────────────────────────────────────


def _check(rows, now=NOW):
    (c,) = qq.check_queue_age(FakeDdbTable(rows=rows), Check, CONTENT_TRUTH, coach_ids=_COACHES, now=now)
    return c


def test_queue_age_check_warns_on_the_paused_source_specimen():
    c = _check(_specimen())
    assert c.passed is None and "PAUSED source" in c.message and "food_delivery" in c.message


def test_queue_age_check_warns_when_a_question_was_served_past_rotation():
    asked = NOW - timedelta(hours=100)
    row = _row(
        "st1",
        coach="mind",
        asked=asked.strftime("%Y-%m-%dT%H:%M:%SZ"),
        reason="rotation",
        last_served_at=(asked + timedelta(hours=80)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    c = _check([row])
    assert c.passed is None and "never rotated" in c.message and "80h" in c.message


def test_queue_age_check_does_not_page_a_quiet_week():
    asked = NOW - timedelta(hours=200)
    quiet = _row("q1", coach="mind", asked=asked.strftime("%Y-%m-%dT%H:%M:%SZ"), reason="rotation")  # never served since
    c = _check([quiet])
    assert c.passed is True and "oldest open question 200h" in c.message
    assert _check([]).passed is True


def test_queue_age_check_is_wired_into_the_nightly_run():
    src = open(os.path.join(_REPO, "lambdas", "operational", "qa_smoke_lambda.py"), encoding="utf-8").read()
    assert '("coach_checkin_queue_age", lambda: coach_checkin_queue_qa.check_queue_age(' in src
