"""tests/test_support_contact_prompts_5125.py — the support contact's weekly prompt and pre-agreed call (#5125).

Holds:
  * the weekly prompt is due once per ISO week from its (default) weekday, keyed on the week's Monday;
  * the pre-agreed call is due once the early-warning flag (#5121) or disruption mode (#5088) has been up for the
    (default) number of days — one reminder per episode, one text when both are due, and a later second trigger
    names only itself;
  * quiet hours, a dark seat and a failed send send nothing and never raise; an unreadable partition is "not up";
  * delivered through the worker's real ``event_outbound`` handler at budget tier 3 (no model turn), to the lead's
    private seat;
  * PRIVACY: the prompts go to the OWNER only. The module never imports the named-human path, never reads its
    private config and never touches S3 / SES, so the contact's identity cannot reach a text or a log line.

No clock is read: every moment is injected (#4848).
"""

from __future__ import annotations

import ast
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

from coach import (
    coach_event_triggers as cet,  # noqa: E402
    named_human_contact as nhc,  # noqa: E402
    support_contact_prompts as scp,  # noqa: E402
)
from common.pacific_time import PACIFIC  # noqa: E402
from training import disruption  # noqa: E402

SUNDAY = "2026-10-25"
SUNDAY_9AM = datetime(2026, 10, 25, 9, 0, tzinfo=PACIFIC)
SATURDAY_9AM = datetime(2026, 10, 24, 9, 0, tzinfo=PACIFIC)
WEDNESDAY_9AM = datetime(2026, 10, 28, 9, 0, tzinfo=PACIFIC)
NIGHT = datetime(2026, 10, 25, 22, 30, tzinfo=PACIFIC)
OFF = {"phase": disruption.PHASE_OFF}


def plus(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def flag(d: str, active: bool = True) -> dict:
    return {"pk": scp.FLAG_PK, "sk": f"DATE#{d}", "date": d, "active": active}


def seat(p):
    return ("lead-token", 777) if p == cet.LEAD_OWNER else (None, None)


class Ledger:
    """The event ledger's write-once put; `query` answers nothing unless rows are seeded."""

    def __init__(self, rows_by_pk=None):
        self.rows, self.queries, self.by_pk = {}, [], dict(rows_by_pk or {})

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803 — boto3 signature
        if Item["sk"] in self.rows:
            raise RuntimeError("ConditionalCheckFailedException")
        self.rows[Item["sk"]] = Item

    def query(self, **kw):
        self.queries.append(kw)
        return {"Items": list(self.by_pk.get(kw["ExpressionAttributeValues"][":pk"], []))}


def test_the_fixtures_are_the_weekdays_they_claim():
    assert date.fromisoformat(SUNDAY).weekday() == 6 and SATURDAY_9AM.weekday() == 5 and WEDNESDAY_9AM.weekday() == 2


def test_the_cadence_numbers_are_labelled_defaults():
    src = (ROOT / "lambdas" / "coach" / "support_contact_prompts.py").read_text(encoding="utf-8")
    for name in ("WEEKLY_PROMPT_WEEKDAY", "CALL_AFTER_DAYS"):
        line = next(ln for ln in src.splitlines() if ln.startswith(f"{name} ="))
        assert "DEFAULT" in line, f"{name} carries no owner ruling and must say it is a default: {line}"


# ── the weekly prompt ───────────────────────────────────────────────────────────────────────
def test_the_weekly_prompt_is_due_from_its_weekday_once_per_iso_week():
    assert scp.weekly_due(plus(SUNDAY, -1)) is None  # Saturday: not yet
    due = scp.weekly_due(SUNDAY)
    assert due == {"event_id": f"SUPPORT_CHECKIN#{plus(SUNDAY, -6)}", "text": scp.WEEKLY_TEXT}
    assert scp.weekly_due(plus(SUNDAY, 1)) is None  # Monday: a new ISO week, not yet its weekday
    assert scp.weekly_due(plus(SUNDAY, 1), weekday=0)["event_id"] == f"SUPPORT_CHECKIN#{plus(SUNDAY, 1)}"  # one constant to move
    assert scp.weekly_due(plus(SUNDAY, 7))["event_id"] == f"SUPPORT_CHECKIN#{plus(SUNDAY, 1)}"  # next Sunday, next key
    assert "your support person" in scp.WEEKLY_TEXT and "this week" in scp.WEEKLY_TEXT


def test_the_weekly_prompt_sends_once_then_waits_for_next_week():
    ledger, sent = Ledger(), []
    out = scp.run(ledger, SUNDAY_9AM, seat, lambda t, c, text: sent.append((t, c, text)), flag_rows=[], disruption_state=OFF)
    assert out == {"reason": "sent", "sent": ["weekly"]} and sent == [("lead-token", 777, scp.WEEKLY_TEXT)]
    again = scp.run(ledger, SUNDAY_9AM, seat, lambda t, c, text: sent.append(text), flag_rows=[], disruption_state=OFF)
    assert again == {"reason": "already sent", "sent": []} and len(sent) == 1
    assert scp.run(ledger, WEDNESDAY_9AM, seat, lambda *a: sent.append(a), flag_rows=[], disruption_state=OFF)["reason"] == "none due"


# ── the pre-agreed call ─────────────────────────────────────────────────────────────────────
def test_the_flag_call_is_due_on_its_default_day_and_once_per_episode():
    n = scp.CALL_AFTER_DAYS
    start = "2026-10-20"
    rows = [flag(plus(start, i)) for i in range(n)]
    today = plus(start, n - 1)
    assert scp.calls_due(plus(start, n - 2), flag_rows=rows[:-1]) == []  # one day short
    [due] = scp.calls_due(today, flag_rows=rows)
    assert due == {"trigger": "early_warning", "start": start, "days": n, "event_id": f"SUPPORT_CALL#early_warning#{start}"}
    later = scp.calls_due(plus(today, 2), flag_rows=rows + [flag(plus(today, 2))])  # a missing day does not end it
    assert later[0]["event_id"] == due["event_id"], "a flag that stays up re-derives the id it already spent"


def test_a_clear_row_or_a_stale_flag_is_not_up():
    start, n = "2026-10-20", scp.CALL_AFTER_DAYS
    rows = [flag(plus(start, i)) for i in range(n)]
    today = plus(start, n - 1)
    assert scp.calls_due(today, flag_rows=rows + [flag(today, False)]) == []
    assert scp.calls_due(plus(today, scp.FLAG_FRESH_DAYS + 1), flag_rows=rows) == []
    assert scp.calls_due(today, flag_rows=[{**r, "active": "true"} for r in rows]) == []  # only a real bool counts
    # a clear day in the middle starts a new episode at the next active day
    gap = [flag(start), flag(plus(start, 1), False)] + [flag(plus(start, 2 + i)) for i in range(n)]
    [due] = scp.calls_due(plus(start, 1 + n), flag_rows=gap)
    assert due["start"] == plus(start, 2)


def test_disruption_mode_active_for_the_default_days_is_due_and_step_back_up_is_not():
    assert disruption.PHASE_ACTIVE == "active", "calls_due reads the mode's own phase literal"
    n, start = scp.CALL_AFTER_DAYS, "2026-12-20"
    st = {"phase": disruption.PHASE_ACTIVE, "start_date": start, "template": "travel"}
    assert scp.calls_due(plus(start, n - 2), disruption_state=st) == []
    [due] = scp.calls_due(plus(start, n - 1), disruption_state=st)
    assert due["event_id"] == f"SUPPORT_CALL#disruption#{start}" and due["days"] == n
    assert scp.calls_due(plus(start, 9), disruption_state={**st, "phase": disruption.PHASE_STEP_BACK_UP}) == []


def test_disruption_state_is_read_through_the_modes_own_rule():
    start = "2026-12-20"
    rec = disruption.build_disruption_record(
        start_date=start, until=plus(start, 9), words="away for the holidays", template="travel", recorded_at=f"{start}T08:00:00Z"
    )
    rec.update({"pk": disruption.DISRUPTION_PK, "sk": disruption.disruption_sk(start)})
    st = scp.read_disruption_state(Ledger({disruption.DISRUPTION_PK: [rec]}), plus(start, 3))
    assert st["phase"] == disruption.PHASE_ACTIVE and st["start_date"] == start


def test_both_due_send_one_text_and_a_later_trigger_names_only_itself():
    n, start = scp.CALL_AFTER_DAYS, "2026-10-19"
    today = plus(start, n - 1)  # a Wednesday-or-earlier day so the weekly prompt is not in play
    assert date.fromisoformat(today).weekday() < scp.WEEKLY_PROMPT_WEEKDAY
    now = datetime.combine(date.fromisoformat(today), datetime.min.time(), tzinfo=PACIFIC).replace(hour=9)
    rows = [flag(plus(start, i)) for i in range(n)]
    ledger, sent = Ledger(), []
    out = scp.run(ledger, now, seat, lambda t, c, text: sent.append(text), flag_rows=rows, disruption_state=OFF)
    assert out["sent"] == ["early_warning"] and len(sent) == 1
    assert sent[0].startswith("Pre-agreed call: the early-warning flag has been up since") and "your support person" in sent[0]
    # two days on, disruption mode reaches its line too: one new text, naming only the mode
    st = {"phase": disruption.PHASE_ACTIVE, "start_date": plus(today, 2 - (n - 1))}
    later_day = plus(today, 2)
    later = now + timedelta(days=2)
    out2 = scp.run(ledger, later, seat, lambda t, c, text: sent.append(text), flag_rows=rows + [flag(later_day)], disruption_state=st)
    assert out2["sent"] == ["disruption"] and len(sent) == 2
    assert "disruption mode" in sent[1] and "early-warning" not in sent[1]
    # both fresh on one run -> one text naming both
    both, sent3 = Ledger(), []
    out3 = scp.run(both, later, seat, lambda t, c, text: sent3.append(text), flag_rows=rows + [flag(later_day)], disruption_state=st)
    assert out3["sent"] == ["early_warning", "disruption"] and len(sent3) == 1
    assert "early-warning flag" in sent3[0] and "disruption mode" in sent3[0]


def test_the_call_text_carries_dates_and_counts_only():
    text = scp.call_text([{"trigger": "early_warning", "start": "2026-10-20", "days": 3}])
    stripped = text.replace("2026-10-20", "")
    assert re.findall(r"\d+", stripped) == ["3"], "one day count; no reading, marker or number of his"


# ── failure shapes ──────────────────────────────────────────────────────────────────────────
def test_quiet_hours_a_dark_seat_and_a_failed_send_send_nothing_and_never_raise():
    sent = []
    assert scp.run(Ledger(), NIGHT, seat, lambda *a: sent.append(a), flag_rows=[], disruption_state=OFF)["reason"] == "quiet hours"
    dark = scp.run(Ledger(), SUNDAY_9AM, lambda p: (None, None), lambda *a: sent.append(a), flag_rows=[], disruption_state=OFF)
    assert dark == {"reason": "dark", "sent": [], "due": ["weekly"]} and sent == []

    def boom(*a):
        raise RuntimeError("telegram down")

    heard: list[str] = []

    class _Tap(logging.Handler):  # the module logs on the worker's PLATFORM logger (#5106), which does not propagate to root
        def emit(self, record):
            heard.append(record.getMessage())

    tap = _Tap(level=logging.WARNING)
    scp.logger.addHandler(tap)
    try:
        out = scp.run(Ledger(), SUNDAY_9AM, seat, boom, flag_rows=[], disruption_state=OFF)
    finally:
        scp.logger.removeHandler(tap)
    assert out["sent"] == [] and any(scp.FAILED_TOKEN in m for m in heard)


def test_an_unreadable_partition_is_not_up():
    class Broken:
        def query(self, **kw):
            raise RuntimeError("ddb")

    assert scp.read_flag_rows(Broken(), SUNDAY) == [] and scp.read_disruption_state(Broken(), SUNDAY)["phase"] == "off"
    out = scp.run(Broken(), WEDNESDAY_9AM, seat, lambda *a: None)
    assert out == {"reason": "none due", "sent": []}


def test_the_flag_read_is_the_partition_projected_to_presence_and_current_cycle():
    t = Ledger({scp.FLAG_PK: [flag("2026-10-24")]})
    assert scp.read_flag_rows(t, "2026-10-25") == [flag("2026-10-24")]
    kw = t.queries[0]
    assert kw["ExpressionAttributeValues"][":pk"] == "USER#matthew#SOURCE#early_warning_flag"
    assert kw["ProjectionExpression"] == "sk, #d, active", "never the evidence lines"
    assert "FilterExpression" in kw, "current cycle only (phase filter)"


# ── through the real worker ─────────────────────────────────────────────────────────────────
def test_delivered_through_the_worker_at_budget_tier_3(monkeypatch):
    from coach import telegram_worker_lambda as worker

    ledger, sends, turns = Ledger(), [], []
    monkeypatch.setattr(worker, "_tg", lambda token, method, payload: sends.append((token, method, dict(payload))))
    monkeypatch.setattr(worker, "_current_tier", lambda: 3)
    monkeypatch.setattr(worker, "_table", lambda: ledger)
    monkeypatch.setattr(worker, "_pacific_now", lambda: SUNDAY_9AM)
    monkeypatch.setattr(worker, "_bot_seat", seat)
    monkeypatch.setattr(worker, "_emit_metric", lambda *a, **k: None)
    monkeypatch.setattr(worker.coach_chat, "run_turn", lambda **kw: turns.append(kw))
    out = worker.lambda_handler({"kind": "event_outbound"}, None)
    assert out["reason"] == "budget" and out["support_contact"]["sent"] == ["weekly"]
    texts = [p["text"] for t, m, p in sends if m == "sendMessage" and t == "lead-token" and p["chat_id"] == 777]
    assert scp.WEEKLY_TEXT in texts and turns == []


# ── privacy: to the owner only; the contact's identity cannot reach it ─────────────────────
def _imports(path: Path) -> set:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def test_the_module_never_reaches_the_contact_or_their_private_config():
    path = ROOT / "lambdas" / "coach" / "support_contact_prompts.py"
    imported = _imports(path)
    assert imported, "the AST walk found the module's imports"
    bad = [m for m in imported if "named_human" in m or m.startswith(("boto3", "botocore", "ai")) or "ses" in m or "budget" in m]
    assert bad == [], bad
    code = re.sub(r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.S)
    code = re.sub(r"#.*", "", code)
    for token in (nhc.CONFIG_KEY, "named_human", "s3", "send_email", "Destination", "EMAIL_RECIPIENT"):
        assert token not in code, f"{token!r} in support_contact_prompts.py code"


def test_no_text_can_carry_an_identity():
    texts = [scp.WEEKLY_TEXT, scp.call_text([{"trigger": t, "start": "2026-10-20", "days": 3} for t in scp._TRIGGER_WORDS])]
    for text in texts:
        assert "@" not in text and "your support person" in text
        assert "nothing was sent to them" in text or "has not contacted them" in text
    # The worker's role holds no grant on the private object: the name cannot be fetched by this host at all.
    policy = (ROOT / "cdk" / "stacks" / "role_policies_serve.py").read_text(encoding="utf-8")
    body = policy[policy.index("def telegram_worker(") :]
    nxt = body.find("\ndef ", 1)
    body = body if nxt < 0 else body[:nxt]
    assert body.strip() and nhc.CONFIG_KEY not in body and "config/coaching" not in body


def test_the_silence_alert_is_still_the_only_path_to_the_contact():
    assert not any("support_contact_prompts" in m for m in _imports(ROOT / "lambdas" / "coach" / "named_human_contact.py"))
    assert scp.PERSONA == cet.LEAD_OWNER


def test_week_key_is_the_monday():
    assert date.fromisoformat(scp.week_key(SUNDAY)).weekday() == 0 and scp.week_key("not a day") is None
