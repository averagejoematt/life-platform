"""tests/test_outbound_trial_6176.py — the owner's two-week outbound-mail trial (#6176, owner ruling 2026-11-22 §9).

Held here, for every item of ``common/outbound_trial.py``:
  * the switchboard ships with every item OFF, and OFF is today's behaviour: each gated sender takes its old path;
  * ON does what the ruling asked, and a suppressed send logs ONE ``[outbound-trial]`` line (a recognised state):
      1. the Sunday slot sends the "what changed" email (text + HTML, same recipient, no model call); Compass is held;
      2. the Plate is held and its code-built section rides the Nutrition Review (tested in
         test_nutrition_review_behavior.py, beside the Review's own handler harness), with no calorie target stated;
      3. the Review Pack is built and logged, not emailed;
      4. the story questions and the owner-words question are held before generation, and story_season_qa reads
         the pause as the recognised state (no false red);
      5. the Telegram 20:00 prompt is held but still stamps its EVAL# row (the dead-man stays fed), and the nudge
         drops items unlogged for 14+ days and sends nothing when none remain;
      6. the DLQ summary is held only when its SNS escalation went out; a canary failure is held only when a DECLARED
         alarm carries it; the Monday ops pack is logged, not emailed;
  * the trial's end date turns every item off by itself;
  * the set of modules allowed to read the switchboard — no subscriber sender, no Morning Brief, no chronicle preview.

No test here reaches AWS or a real clock for an asserted value (#4848): every client is a fake and every day is passed in.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "owner@example.invalid")
os.environ.setdefault("EMAIL_SENDER", "platform@example.invalid")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "lambdas", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import outbound_trial as ot  # noqa: E402

ITEMS = tuple(ot.TRIAL)


@pytest.fixture
def trial_on(monkeypatch):
    """Turn the named items on for one test (never the committed default)."""

    def _on(*items):
        for item in items:
            monkeypatch.setitem(ot.TRIAL, item, True)

    monkeypatch.setattr(ot, "TRIAL_ENDS_ON", None)
    return _on


def _trial_lines(caplog_or_list):
    return [ln for ln in caplog_or_list if str(ln).startswith(ot.LOG_TAG)]


# ── the switchboard ────────────────────────────────────────────────────────────────────────────


def test_every_item_ships_off_and_has_a_description():
    """The trial starts by a deliberate, reviewed line — never by merging this lane."""
    assert ITEMS and all(v is False for v in ot.TRIAL.values()), ot.TRIAL
    assert ot.TRIAL_ENDS_ON is None
    assert set(ot.DESCRIPTIONS) == set(ot.TRIAL)
    assert all(not ot.is_on(i, "2026-11-22") for i in ITEMS)


def test_an_unknown_item_raises_instead_of_reading_off():
    with pytest.raises(KeyError):
        ot.is_on("sunday_what_chnaged", "2026-11-22")


def test_the_end_date_turns_every_item_off_by_itself(trial_on, monkeypatch):
    trial_on(*ITEMS)
    monkeypatch.setattr(ot, "TRIAL_ENDS_ON", "2026-12-06")
    assert all(ot.is_on(i, "2026-12-05") for i in ITEMS)
    assert not any(ot.is_on(i, "2026-12-06") for i in ITEMS)


def test_a_suppression_is_one_parseable_line():
    lines = []
    rec = ot.suppressed(ot.OPS_MONDAY_PACK, "life-platform-traffic-digest", log=lines.append, subject="x")
    assert len(lines) == 1 and lines[0].startswith("[outbound-trial] ")
    parsed = json.loads(lines[0][len("[outbound-trial] ") :])
    assert parsed == rec and parsed["event"] == "suppressed" and parsed["reason"] == ot.DESCRIPTIONS[ot.OPS_MONDAY_PACK]


def test_status_page_reads_a_paused_sender_as_paused_only_when_on(trial_on):
    assert ot.status_page_note("weekly_plate", "2026-11-22") is None
    trial_on(ot.PLATE_INTO_NUTRITION_REVIEW, ot.SUNDAY_WHAT_CHANGED)
    assert "folded into the Saturday Nutrition Review" in ot.status_page_note("weekly_plate", "2026-11-22")
    assert ot.status_page_note("monday_compass", "2026-11-22").startswith("Paused during a two-week email trial")
    assert ot.status_page_note("nutrition_review", "2026-11-22") is None  # the Review keeps its weekly cadence
    assert ot.status_page_note("weekly_digest", "2026-11-22") is None  # its slot still sends (the new email)


# ── who may read the switchboard ───────────────────────────────────────────────────────────────

# premerge-gate: 6176: an rglob sweep of lambdas/ for importers of common.outbound_trial — a subscriber sender, the Morning Brief or the chronicle preview that starts reading the owner's trial switchboard must red BEFORE merge.
ALLOWED_READERS = {
    "lambdas/emails/weekly_digest_lambda.py",
    "lambdas/emails/weekly_what_changed_send.py",
    "lambdas/emails/monday_compass_lambda.py",
    "lambdas/emails/weekly_plate_lambda.py",
    "lambdas/emails/nutrition_review_lambda.py",
    "lambdas/emails/ai_review_pack_lambda.py",
    "lambdas/emails/wednesday_chronicle_lambda.py",
    "lambdas/emails/evening_nudge_lambda.py",
    "lambdas/coach/evening_checkin.py",
    "lambdas/operational/dlq_consumer_lambda.py",
    "lambdas/operational/canary_lambda.py",
    "lambdas/operational/traffic_digest_lambda.py",
    "lambdas/operational/story_season_qa.py",
    "lambdas/web/site_api_status.py",
}
#: Senders the trial must never touch: subscriber mail, the Morning Brief (#6175 owns it), the chronicle preview and
#: its approval path, the ADR-170 digest, the continuity switch, qa-smoke's urgent deploy-health mail.
NEVER_READERS = {
    "lambdas/compute/weekly_signal_lambda.py",
    "lambdas/emails/chronicle_email_sender_lambda.py",
    "lambdas/emails/between_chronicle_lambda.py",
    "lambdas/web/email_subscriber_lambda.py",
    "lambdas/web/subscriber_onboarding_lambda.py",
    "lambdas/emails/daily_brief_lambda.py",
    "lambdas/emails/chronicle_store.py",
    "lambdas/operational/alert_digest_lambda.py",
    "lambdas/operational/permanence_lambda.py",
    "lambdas/operational/qa_smoke_lambda.py",
}


def _imports_outbound_trial(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "common" and any(a.name == "outbound_trial" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "common.outbound_trial":
            return True
        if isinstance(node, ast.Import) and any(a.name == "common.outbound_trial" for a in node.names):
            return True
    return False


def test_only_the_owner_facing_senders_read_the_switchboard():
    readers = {str(p.relative_to(ROOT)) for p in (ROOT / "lambdas").rglob("*.py") if _imports_outbound_trial(p)}
    assert (
        readers == ALLOWED_READERS
    ), f"unexpected readers {sorted(readers - ALLOWED_READERS)}; missing {sorted(ALLOWED_READERS - readers)}"
    for path in NEVER_READERS:
        assert (ROOT / path).exists(), f"{path} moved — re-point this guard"
        assert path not in readers


# ── item 1: the Sunday email; Compass held ─────────────────────────────────────────────────────


def _week(**over):
    base = {
        "withings": {"weight_avg": 288.0},
        "whoop": {"recovery_avg": 64.0, "hrv_avg": 55.5, "rhr_avg": 52.0},
        "sleep": {"duration_avg_hrs": 7.6},
        "mf_workouts": {"workout_count": 6},
        "apple": {"steps_avg": 9200.0},
        "macrofactor": {"calories_avg": 1198.0, "protein_avg_g": 145.0, "days_logged": 7},
        "habitify": {"mvp_avg_pct": 70.0},
    }
    base.update(over)
    return base


DATES = {"this_start": "2026-11-15", "this_end": "2026-11-21", "prior_start": "2026-11-08", "prior_end": "2026-11-14"}


def test_what_changed_splits_by_threshold_and_never_prints_an_absence_as_zero():
    from emails import sunday_what_changed as swc

    this = _week(withings={"weight_avg": 285.1}, apple={"steps_avg": None}, habitify=None)
    prior = _week(withings={"weight_avg": 290.7}, whoop={"recovery_avg": 66.0, "hrv_avg": 56.0, "rhr_avg": 52.0})
    out = swc.compare(this, prior)
    assert any(ln.startswith("Weight (weekly mean): 290.7 lb → 285.1 lb (−5.6 lb)") for ln in out["changed"])
    assert any(ln.startswith("Recovery (mean): 66% → 64%") for ln in out["unchanged"])  # 2 < the 5-point threshold
    assert any("Steps" in ln and "no Apple Health reading this week" in ln for ln in out["unknown"])
    assert any("Essential habits" in ln and "no Habitify reading" in ln for ln in out["unknown"])
    assert not any("Steps" in ln for ln in out["changed"] + out["unchanged"])


def test_the_sunday_email_has_one_decision_at_most_and_states_no_calorie_target():
    from emails import sunday_what_changed as swc

    advice = {"readable": True, "decisions_this_week": 0, "decisions_last_week": 6}
    email = swc.build({"this": _week(), "prior": _week(), "dates": DATES}, advice, week_number=11)
    assert email["subject"].startswith("Week 11: nothing new needs you")
    assert email["sections"]["ONE DECISION"] == ["Nothing new needs you this week."]
    status = " ".join(email["sections"]["ADVICE STATUS"])
    assert "not recorded" in status and "nothing is inferred from sensor, training or food data" in status
    for forbidden in ("target", "1,500", "1,600", "1,900", "Board", "Chair"):
        assert forbidden not in email["text"], forbidden
    assert email["html"].count("<h2") == 5 and "<script" not in email["html"]


def test_an_owner_marked_undecided_ask_is_the_one_decision():
    from emails import sunday_what_changed as swc

    advice = {"readable": True, "open_decision": {"coach_id": "nutrition_coach", "ask_id": "a1", "since": "2026-11-18"}}
    email = swc.build({"this": _week(), "prior": _week(), "dates": DATES}, advice)
    assert email["subject"].startswith("one decision")
    assert "'not yet decided' on 2026-11-18" in email["sections"]["ONE DECISION"][0]


def test_unreadable_advice_status_says_so_and_is_never_zero():
    from emails import sunday_what_changed as swc

    lines = swc.advice_lines({"readable": False, "error": "ClientError"})
    assert lines == ["Advice status could not be read this week, so none is shown. Nothing here is a zero."]
    assert swc.decision_lines({"readable": False}) == ["Nothing new needs you this week."]


def test_advice_status_counts_only_what_he_recorded():
    from emails import advice_status as AS

    decisions = [
        {"sk": "DECISION#2026-11-16T10:00:00.000Z", "date": "2026-11-16", "followed": True},
        {"sk": "DECISION#2026-11-10T10:00:00.000Z", "date": "2026-11-10", "followed": False},
    ]
    answers = {
        ("nutrition_coach", "a1"): {"state": "acted_on", "recorded_at": "2026-11-17T00:00:00Z", "revisions": 1},
        ("nutrition_coach", "a2"): {"state": "not_yet_decided", "recorded_at": "2026-11-12T00:00:00Z", "revisions": 1},
        ("sleep_coach", "a3"): {"state": "declined", "recorded_at": "2026-11-01T00:00:00Z", "revisions": 2},
    }
    out = AS.summarize(decisions, answers, "2026-11-15", "2026-11-21", "2026-11-08", "2026-11-14")
    assert (out["decisions_this_week"], out["decisions_last_week"]) == (1, 1)
    assert out["ask_answers_this_week"] == {"acted_on": 1}  # the 11-01 answer is not this week's
    assert out["open_decision"] == {"coach_id": "nutrition_coach", "ask_id": "a2", "since": "2026-11-12"}
    assert "linked_states" not in out  # links have one reader, the owner's MCP tool — never this email


def test_advice_status_narrows_on_decisions_hides_tombstones_and_reports_a_read_failure(monkeypatch):
    from emails import advice_status as AS

    seen = []

    class T:
        def __init__(self, items=None, err=None):
            self.items, self.err = items or [], err

        def query(self, **kw):
            seen.append(kw["KeyConditionExpression"].get_expression()["values"][1].get_expression()["values"][1])
            if self.err:
                raise self.err
            return {"Items": self.items}

    monkeypatch.setattr(AS, "_answers", lambda table, user_id: {})
    wiped = {"sk": "DECISION#2026-11-16T10:00:00.000Z", "date": "2026-11-16", "tombstone": True}
    assert AS.read(T([wiped]), "matthew", "2026-11-15", "2026-11-21", "2026-11-08", "2026-11-14")["decisions_this_week"] == 0
    assert seen == ["DECISION#"]
    assert AS.read(T(err=RuntimeError("x")), "matthew", "2026-11-15", "2026-11-21", "2026-11-08", "2026-11-14") == {
        "readable": False,
        "error": "RuntimeError",
    }


@pytest.fixture
def digest(monkeypatch):
    from emails import weekly_digest_lambda as wd, weekly_what_changed_send as wws

    sent, recorded = [], []
    monkeypatch.setattr(wd.send_ledger, "should_skip_replay", lambda *a, **k: False)
    monkeypatch.setattr(wws, "guarded_send_email", lambda ses, dry, **kw: sent.append(kw) or {"MessageId": "m"})
    monkeypatch.setattr(wd, "record_email_send", lambda table, name, key: recorded.append((name, key)))
    monkeypatch.setattr(wd, "call_haiku", lambda *a, **k: pytest.fail("the Sunday email makes no model call"))
    monkeypatch.setattr(wws.advice_status, "read", lambda *a, **k: {"readable": True, "decisions_this_week": 0, "decisions_last_week": 0})
    return wd, sent, recorded


def test_sunday_slot_off_is_the_weekly_report_path(digest, monkeypatch):
    wd, sent, _ = digest
    from emails import weekly_what_changed_send as wws

    monkeypatch.setattr(wws, "send", lambda *a, **k: pytest.fail("trial path taken with the item off"))
    monkeypatch.setattr(wd, "gather_all", lambda: None)
    assert wd.lambda_handler({}, None) == {"statusCode": 500, "body": "Failed to gather data"}
    assert sent == []


def test_sunday_slot_on_sends_the_what_changed_email_once(digest, monkeypatch, trial_on):
    wd, sent, recorded = digest
    trial_on(ot.SUNDAY_WHAT_CHANGED)
    monkeypatch.setattr(wd, "gather_all", lambda: ({"this": _week(), "prior": _week(), "dates": DATES}, {}))
    resp = wd.lambda_handler({}, None)
    assert resp["statusCode"] == 200 and len(sent) == 1
    msg = sent[0]
    assert msg["Destination"] == {"ToAddresses": [wd.RECIPIENT]}
    body = msg["Content"]["Simple"]["Body"]
    assert set(body) == {"Text", "Html"} and "WHAT CHANGED" in body["Text"]["Data"]
    assert msg["EmailTags"] == [{"Name": "message_type", "Value": "weekly_what_changed"}]
    assert recorded and recorded[0][0] == "weekly_digest"  # the same replay ledger: never twice in one week


def test_compass_is_held_before_any_read_when_on(monkeypatch, trial_on):
    from emails import monday_compass_lambda as mc

    monkeypatch.setattr(mc.send_ledger, "should_skip_replay", lambda *a, **k: True)
    assert "already sent" in mc.lambda_handler({}, None)["body"]  # OFF: today's path (the replay guard runs)
    trial_on(ot.SUNDAY_WHAT_CHANGED)
    monkeypatch.setattr(mc.send_ledger, "should_skip_replay", lambda *a, **k: pytest.fail("no read when held"))
    body = json.loads(mc.lambda_handler({}, None)["body"])
    assert body["suppressed"] is True and body["item"] == ot.SUNDAY_WHAT_CHANGED and body["function"] == "monday-compass"


# ── item 2: the Plate held (the fold is tested with the Review's own harness) ─────────────────


def test_plate_is_held_before_any_read_when_on(monkeypatch, trial_on):
    from emails import weekly_plate_lambda as wp

    monkeypatch.setattr(wp.send_ledger, "should_skip_replay", lambda *a, **k: True)
    assert "already sent" in wp.lambda_handler({}, None)["body"]
    trial_on(ot.PLATE_INTO_NUTRITION_REVIEW)
    monkeypatch.setattr(wp, "gather_data", lambda: pytest.fail("no read when held"))
    body = json.loads(wp.lambda_handler({}, None)["body"])
    assert body["suppressed"] is True and body["function"] == "weekly-plate"


def test_plate_fold_counts_foods_and_states_no_target():
    from emails import plate_fold

    rows = [
        {"food_log": [{"food_name": "Greek Yogurt"}, {"food_name": "Creatine"}, {"food_name": "eggs"}]},
        {"food_log": [{"food_name": "greek yogurt"}, {"food_name": "Eggs"}, {"food_name": "Eggs"}]},
        {"food_log": None},
    ]
    assert plate_fold.top_foods(rows) == [("eggs", 3), ("Greek Yogurt", 2)]
    html = plate_fold.html_section(plate_fold.top_foods(rows), menu_built=True)
    assert plate_fold.TARGET_NOTE in html and "kcal" not in html and "Creatine" not in html
    assert "nothing to count" in plate_fold.html_section([], menu_built=False)


# ── item 3: the Review Pack built and logged, not emailed ──────────────────────────────────────


@pytest.fixture
def pack(monkeypatch):
    from emails import ai_review_pack_lambda as arp

    sent, logged = [], []
    monkeypatch.setattr(arp.send_ledger, "should_skip_replay", lambda *a, **k: False)
    monkeypatch.setattr(arp, "gather_week", lambda dates: ({"chronicle": [{"_key": "k1", "date": "2026-11-18", "text": "draft"}]}, {}, 0))
    monkeypatch.setattr(arp, "compute_ranking", lambda by, **kw: None)
    monkeypatch.setattr(arp, "compute_promotion_proposals", lambda t: None)
    monkeypatch.setattr(arp, "guarded_send_email", lambda ses, dry, **kw: sent.append(kw))
    monkeypatch.setattr(arp, "record_email_send", lambda *a: None)
    monkeypatch.setattr(arp.logger, "info", lambda msg, *a: logged.append(str(msg)))
    return arp, sent, logged


def test_review_pack_off_still_emails(pack):
    arp, sent, logged = pack
    arp.lambda_handler({}, None)
    assert len(sent) == 1 and not _trial_lines(logged)


def test_review_pack_on_is_built_and_logged_not_emailed(pack, trial_on):
    arp, sent, logged = pack
    trial_on(ot.REVIEW_PACK_NOT_EMAILED)
    resp = arp.lambda_handler({}, None)
    assert sent == [] and resp["suppressed"] is True
    assert any(ln.startswith("[ai-review-pack] pack_record") and "key=k1" in ln for ln in logged)
    assert len(_trial_lines(logged)) == 1


# ── item 4: the story desk's questions held; its dead-man reads the pause ──────────────────────


def test_story_questions_are_held_before_generation(monkeypatch, trial_on):
    from emails import wednesday_chronicle_lambda as wc

    class Table:
        def get_item(self, **kw):
            raise AssertionError("no marker read when held")

    monkeypatch.setattr(wc, "table", Table())
    monkeypatch.setattr(wc, "ses", None)
    trial_on(ot.STORY_QUESTIONS_PAUSED)
    for event in ({"story_questions": True}, {"tuesday_question": True}):
        body = json.loads(wc.lambda_handler(event, None)["body"])
        assert body["status"] == "suppressed" and body["item"] == ot.STORY_QUESTIONS_PAUSED


def test_story_questions_off_take_the_old_path(monkeypatch):
    from emails import wednesday_chronicle_lambda as wc

    class Table:
        def get_item(self, **kw):
            return {"Item": {"sk": kw["Key"]["sk"]}}  # already sent -> the old idempotent no-op

    monkeypatch.setattr(wc, "table", Table())
    from content import story_dossier

    monkeypatch.setattr(story_dossier, "week_containing", lambda d: {"week": 11, "start": "2026-11-16", "end": "2026-11-22"})
    for event in ({"story_questions": True}, {"tuesday_question": True}):
        assert json.loads(wc.lambda_handler(event, None)["body"])["status"] == "already_sent"


def _questions_check(now):
    from operational import story_season_qa as ssq
    from operational.qa_check import CONTENT_TRUTH, Check

    class T:
        def query(self, **kw):
            return {"Items": []}

    out = ssq.check_story_season(T(), "USER#matthew#SOURCE#", Check, CONTENT_TRUTH, lambda: now, site_base_url="https://x.invalid")
    return next(c for c in out if c.name == ssq.QUESTIONS_CHECK)


def test_story_season_dead_man_reads_the_pause_as_recognised(trial_on, monkeypatch):
    import operational.story_season_qa as ssq

    monkeypatch.setattr(ssq, "week_containing", lambda d: {"week": 11, "start": "2026-11-16", "end": "2026-11-22"})
    now = datetime(2026, 11, 17, 20, 0, tzinfo=timezone.utc)  # Tuesday: Monday 09:00 PT's send is owed
    assert _questions_check(now).passed is False  # OFF: a missing marker is a miss, exactly as today
    trial_on(ot.STORY_QUESTIONS_PAUSED)
    c = _questions_check(now)
    assert c.passed is True and "paused by the outbound trial" in c.message


# ── item 5: one channel at 20:00, and the quiet rule ───────────────────────────────────────────


def test_telegram_prompt_is_held_and_still_feeds_its_dead_man(trial_on):
    from coach import evening_checkin as ec
    from common.pacific_time import PACIFIC

    stamps = []

    class T:
        def get_item(self, **kw):
            return {}

        def put_item(self, Item, **kw):
            stamps.append(Item)

        def update_item(self, **kw):
            raise AssertionError("no prompt claimed when held")

    evening = datetime(2026, 11, 20, 20, 0, tzinfo=PACIFIC)
    seat = lambda persona: ("tok", 1)  # noqa: E731
    trial_on(ot.EVENING_ONE_CHANNEL)
    out = ec.run_prompt(T(), evening, seat, lambda *a: pytest.fail("held prompt was sent"), now_utc=evening.astimezone(timezone.utc))
    assert out["reason"] == ec.OUTBOUND_TRIAL_REASON
    assert [s["sk"] for s in stamps] == ["EVAL#2026-11-20"] and stamps[0]["reason"] == ec.OUTBOUND_TRIAL_REASON


def test_quiet_rule_split_is_pure():
    from emails import evening_nudge_lambda as en

    missing = [{"name": "Supplements"}, {"name": "Journal"}]
    kept, dropped = en.split_stale(missing, {"Supplements": 2, "Journal": None})
    assert [m["name"] for m in kept] == ["Supplements"] and [m["name"] for m in dropped] == ["Journal"]


@pytest.fixture
def nudge(monkeypatch):
    from emails import evening_nudge_lambda as en

    sent, logged = [], []
    today = "2026-11-21"
    monkeypatch.setattr(en, "pacific_today", lambda: today)
    monkeypatch.setattr(en, "_run_named_human_contact_leg", lambda *a: None)
    monkeypatch.setattr(en.send_ledger, "should_skip_replay", lambda *a, **k: False)
    monkeypatch.setattr(en.send_ledger, "record_sent", lambda *a, **k: None)
    monkeypatch.setattr(en, "guarded_send_email", lambda ses, dry, **kw: sent.append(kw))
    monkeypatch.setattr(en, "manual_capture_sources", lambda: {})
    monkeypatch.setattr(en, "_build_ritual_section", lambda d, m: "<ritual/>")
    monkeypatch.setattr(en, "_build_morning_note_section", lambda d: "")
    # Supplements were last logged 3 days ago; journal, How We Feel and the ritual not in the window.
    monkeypatch.setattr(en, "_check_supplements", lambda d: (d == "2026-11-18", ""))
    monkeypatch.setattr(en, "_check_journal", lambda d: (False, "No journal entries"))
    monkeypatch.setattr(en, "_check_how_we_feel", lambda d: (False, ""))
    monkeypatch.setattr(en, "_check_evening_ritual", lambda d: (["connection", "mood_valence", "intake_count"], "Not logged yet"))
    monkeypatch.setattr(en.logger, "info", lambda msg, *a: logged.append(str(msg)))
    return en, sent, logged


def _subject(msg):
    return msg["Content"]["Simple"]["Subject"]["Data"]


def test_nudge_off_lists_all_four_as_today(nudge):
    en, sent, _ = nudge
    en.lambda_handler({}, None)
    assert _subject(sent[0]) == "Evening nudge · 4 thing(s) to log before bed"


def test_nudge_on_drops_stale_items(nudge, trial_on):
    en, sent, logged = nudge
    trial_on(ot.EVENING_ONE_CHANNEL)
    en.lambda_handler({}, None)
    assert _subject(sent[0]) == "Evening nudge · 1 thing(s) to log before bed"
    html = sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "<ritual/>" not in html  # the dropped ritual's tap block goes with it


def test_nudge_on_sends_nothing_when_every_item_is_stale(nudge, trial_on, monkeypatch):
    en, sent, logged = nudge
    monkeypatch.setattr(en, "_check_supplements", lambda d: (False, "No supplements logged"))
    trial_on(ot.EVENING_ONE_CHANNEL)
    resp = en.lambda_handler({}, None)
    assert sent == [] and resp["suppressed"] is True
    rec = json.loads(_trial_lines(logged)[0][len(ot.LOG_TAG) + 1 :])
    assert rec["function"] == "evening-nudge" and sorted(rec["dropped"]) == ["Evening Ritual", "How We Feel", "Journal", "Supplements"]


def test_an_item_logged_thirteen_days_ago_is_not_stale(monkeypatch):
    from emails import evening_nudge_lambda as en

    monkeypatch.setattr(en, "_check_supplements", lambda d: (d == "2026-11-08", ""))
    assert en.last_logged_within("Supplements", "2026-11-21") == 13
    monkeypatch.setattr(en, "_check_supplements", lambda d: (d == "2026-11-07", ""))
    assert en.last_logged_within("Supplements", "2026-11-21") is None  # 14 days unlogged, today included


# ── item 6: ordinary ops mail ──────────────────────────────────────────────────────────────────


@pytest.fixture
def dlq(monkeypatch):
    from operational import dlq_consumer_lambda as d

    calls = []
    monkeypatch.setattr(d, "send_alert", lambda esc, dry_run=False: calls.append("ses"))
    return d, calls


def _drive_dlq(d, monkeypatch, paged):
    monkeypatch.setattr(d, "DLQ_URL", "https://sqs.invalid/q")
    monkeypatch.setattr(d, "page_operator", lambda esc: paged)

    def process(msg, stats, escalations):
        escalations.append({"function_name": "whoop-data-ingestion", "message_id": "m1"})

    monkeypatch.setattr(d, "process_message", process)

    class SQS:
        n = 0

        def receive_message(self, **kw):
            SQS.n += 1
            return {"Messages": [{"MessageId": "m1"}]} if SQS.n == 1 else {"Messages": []}

    monkeypatch.setattr(d, "sqs", SQS())
    monkeypatch.setattr(d, "_time_left_ms", lambda ctx, started: 1000)
    d.lambda_handler({}, None)


@pytest.mark.parametrize("on,paged,emailed", [(False, True, True), (True, True, False), (True, False, True)])
def test_dlq_summary_held_only_when_the_sns_escalation_went_out(dlq, monkeypatch, trial_on, on, paged, emailed):
    d, calls = dlq
    if on:
        trial_on(ot.OPS_DLQ_SUMMARY)
    _drive_dlq(d, monkeypatch, paged)
    assert (calls == ["ses"]) is emailed


def test_canary_only_holds_failures_a_declared_alarm_carries():
    import platform_model_alarms as pma
    from operational import canary_lambda as cl

    declared = set(pma.extract_alarms())
    assert set(cl.CHECK_ALARM_NAMES.values()) <= declared, sorted(set(cl.CHECK_ALARM_NAMES.values()) - declared)
    email, alarmed = cl.split_alarmed([{"check_key": "dynamodb"}, {"check_key": "subscribe"}, {"check_key": "s3"}])
    assert [f["check_key"] for f in email] == ["subscribe"]  # no alarm behind it: still emailed
    assert [f["check_key"] for f in alarmed] == ["dynamodb", "s3"]


def test_ops_pack_text_is_readable():
    from operational import ops_pack_record

    text = ops_pack_record.pack_text(
        "<html><style>.x{}</style><h2>Weekly ops</h2><p>17 views &amp; 4 visitors</p><table><tr><td>a</td></tr></table></html>"
    )
    assert text.splitlines()[:2] == ["Weekly ops", "17 views & 4 visitors"] and ".x" not in text


# ── the measurement script ─────────────────────────────────────────────────────────────────────


def test_measurement_windows_are_consecutive_weeks_ending_on_the_end_day():
    from datetime import date

    import owner_outbound_volume as oov

    w = oov.windows(date(2026, 11, 20), 2)
    assert w == [(date(2026, 11, 7), date(2026, 11, 13)), (date(2026, 11, 14), date(2026, 11, 20))]
    assert all(group.startswith("/aws/lambda/") for _, group, _ in oov.SENDS)
