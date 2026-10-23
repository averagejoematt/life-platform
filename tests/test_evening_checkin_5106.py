"""tests/test_evening_checkin_5106.py — #5106: the 20-second evening check-in and its weekly read against intake.

What is held here:
  * capture round-trip from the WIRE: a real Telegram update through `telegram_gateway.route` and the worker's
    `lambda_handler` lands one `evening_checkin` row and never reaches a coach turn;
  * idempotency per evening (Telegram and MCP through the one writer), the 04:00 PT rollover, the group refusal,
    and the prompt-only rule for a bare reply;
  * the scheduled prompt: one send per evening, the dead-man's EVAL stamp on every run, dark/quiet/already-logged;
  * the dead-man check in the nightly qa-smoke and its contract with the writer's ledger key;
  * the pair join (THE calorie target, THE protein hit, late eating, an incomplete log is None, never low);
  * the weekly family through the engine's OWN compute_correlations: the under-powered path says 'too early to
    say', a powered synthetic path survives FDR and is worded as an association, never a cause;
  * privacy: no web or email module reads either partition; the family is stored apart from the public record.

Every clock is passed in (no test here reaches `datetime.now` for an asserted value, #4848).
"""

# premerge-gate: #5106: os.walk sweep of lambdas/web/ and lambdas/emails/ — no published module names the owner-only check-in partitions; also reads config/schedules.json

from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "lambdas", "compute"))

from coach import evening_checkin as ec  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402
from health import checkin_intake_pairs as cip  # noqa: E402

EVENING = datetime(2026, 10, 28, 20, 0, tzinfo=PACIFIC)  # the 20:00 PT prompt
EVENING_UTC = EVENING.astimezone(timezone.utc)
DAY = "2026-10-28"


class Table:
    """A small DynamoDB double that APPLIES what the code sends: SET updates with names/values and
    UPDATED_OLD, conditional puts on attribute_not_exists, get_item, and pk/sk-prefix queries."""

    def __init__(self):
        self.store: dict = {}
        self.calls: list = []

    def get_item(self, Key):
        self.calls.append(("get", Key))
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None):
        self.calls.append(("put", Item))
        k = (Item["pk"], Item["sk"])
        if ConditionExpression and "attribute_not_exists" in ConditionExpression and k in self.store:
            raise type("ConditionalCheckFailedException", (Exception,), {})("ConditionalCheckFailed")
        self.store[k] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None, ReturnValues=None):
        self.calls.append(("update", Key))
        names = ExpressionAttributeNames or {}
        k = (Key["pk"], Key["sk"])
        row = self.store.setdefault(k, dict(Key))
        old = {}
        for part in UpdateExpression[len("SET ") :].split(","):
            lhs, rhs = (x.strip() for x in part.split("="))
            attr = names.get(lhs, lhs)
            if attr in row:
                old[attr] = row[attr]
            row[attr] = ExpressionAttributeValues[rhs]
        return {"Attributes": old} if ReturnValues == "UPDATED_OLD" and old else {}

    def rows(self, pk):
        return [v for (p, _s), v in sorted(self.store.items()) if p == pk]


def _seat_for(store):
    return lambda persona: store.get(persona, (None, None))


# ── capture: the wire ───────────────────────────────────────────────────────────────────────────


def _telegram_event(text, chat_type="private"):
    """An API Gateway event carrying a REAL Telegram update body (the gateway's input)."""
    from coach import telegram_gateway

    update = {
        "update_id": 7001,
        "message": {
            "message_id": 55,
            "date": int(EVENING_UTC.timestamp()) + 60,
            "chat": {"id": 4242, "type": chat_type},
            "from": {"id": 4242, "is_bot": False, "first_name": "M"},
            "text": text,
        },
    }
    return {"headers": {telegram_gateway.TELEGRAM_SECRET_HEADER: "hook-token-test"}, "body": json.dumps(update)}


@pytest.fixture
def worker(monkeypatch):
    """The coach worker with every AWS edge replaced; a coach turn would be recorded (and must not happen)."""
    from coach import telegram_worker_lambda as w

    table, sends, turns = Table(), [], []
    monkeypatch.setattr(w, "_tg", lambda token, method, payload: sends.append((token, method, dict(payload))))
    monkeypatch.setattr(w, "_secret_entry", lambda key: {"bot_token": f"tok-{key}", "chat_ids": [4242]})
    monkeypatch.setattr(w, "_seen_update", lambda cid, uid: False)
    monkeypatch.setattr(w, "_table", lambda: table)
    monkeypatch.setattr(w, "_s3_client", lambda: None)
    monkeypatch.setattr(w, "_pacific_now", lambda: EVENING + timedelta(minutes=1))
    monkeypatch.setattr(w.telegram_gateway, "is_stale", lambda ts, now: False)
    monkeypatch.setattr(w.coach_chat, "run_turn", lambda **kw: turns.append(kw) or 1 / 0)
    return w, table, sends, turns


def _route(text, chat_type="private"):
    from coach import telegram_gateway

    return telegram_gateway.route(
        _telegram_event(text, chat_type),
        secret="hook-token-test",
        routing={"nutrition": "nutrition"},
        allowed_chat_ids=[4242],
        bot_key_of=lambda e: "nutrition",
    )


def test_capture_round_trip_from_the_wire_never_reaches_a_coach_turn(worker):
    w, table, sends, turns = worker
    table.store[(ec.LEDGER_PK, f"PROMPT#{DAY}")] = {"pk": ec.LEDGER_PK, "sk": f"PROMPT#{DAY}", "status": "sent"}
    out = w.lambda_handler(_route("2 3 1 Tired"), None)
    assert out == {"ok": True, "reason": "evening_checkin"}
    assert turns == []  # deterministic: no model call
    row = table.store[(ec.PK, f"DATE#{DAY}")]
    assert (row["hunger"], row["stress"], row["cravings"], row["word"], row["source"]) == (2, 3, 1, "tired", "telegram")
    assert sends[-1][2]["text"].startswith(f"Logged the check-in for {DAY}")


def test_a_second_answer_overwrites_the_evening_in_place(worker):
    w, table, sends, _ = worker
    table.store[(ec.LEDGER_PK, f"PROMPT#{DAY}")] = {"pk": ec.LEDGER_PK, "sk": f"PROMPT#{DAY}", "status": "sent"}
    w.lambda_handler(_route("2 3 1 tired"), None)
    w.lambda_handler(_route("/checkin 1 4 2 wired"), None)
    rows = table.rows(ec.PK)
    assert len(rows) == 1 and (rows[0]["stress"], rows[0]["word"]) == (4, "wired")
    assert sends[-1][2]["text"].startswith("Updated the check-in")


def test_a_bare_reply_without_tonights_prompt_is_an_ordinary_message():
    table = Table()
    assert ec.capture_reply(table, "2 3 1 tired", EVENING) is None  # no PROMPT# row: the coach answers as usual
    assert table.rows(ec.PK) == []
    assert ec.capture_reply(table, "/checkin 2 3 1 tired", EVENING).startswith("Logged")  # the command works any time
    assert ec.capture_reply(table, "/checkin hungry", EVENING) == ec.USAGE_TEXT
    assert ec.capture_reply(table, "I ate 3 eggs at 2", EVENING) is None


def test_never_in_the_board_room():
    table = Table()
    assert ec.capture_reply(table, "/checkin 2 3 1 tired", EVENING, is_group=True) is None
    assert table.rows(ec.PK) == []


def test_a_reply_after_midnight_belongs_to_the_previous_evening():
    assert ec.evening_day(datetime(2026, 10, 29, 1, 30, tzinfo=PACIFIC)) == DAY
    assert ec.evening_day(datetime(2026, 10, 29, 4, 0, tzinfo=PACIFIC)) == "2026-10-29"


@pytest.mark.parametrize("bad", [{"stress": 5}, {"hunger": -1}, {"cravings": "lots"}, {"stress": 2.5}, {"word": "two words"}])
def test_validate_refuses_values_off_the_scale(bad):
    with pytest.raises(ValueError):
        ec.validate(bad)


def test_mcp_door_writes_the_same_row_and_count_becomes_optional(monkeypatch):
    from mcp import tools_lifestyle as tl
    from mcp.registry import TOOLS

    table = Table()
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "pacific_today", lambda: DAY)
    monkeypatch.setattr(tl, "pacific_now", lambda: EVENING)
    fn = TOOLS["log_evening_intake"]["fn"]
    out = fn({"stress": 3, "word": "Busy"})
    assert out["logged"] and out["date"] == DAY and out["stress"] == 3 and out["word"] == "busy"
    assert table.rows("USER#matthew#SOURCE#private_intake") == []  # no count given: the drinks ledger is untouched
    both = fn({"count": 0, "hunger": 2})
    assert both["count"] == 0 and both["checkin"]["hunger"] == 2 and both["checkin"]["updated"] is False  # a new field
    again = fn({"stress": 1})
    assert again["updated"] is True and again["previous"] == {"stress": 3}  # the same field again: replaced in place, said so
    row = table.store[(ec.PK, f"DATE#{DAY}")]
    assert (row["stress"], row["hunger"], row["source"]) == (1, 2, "mcp") and len(table.rows(ec.PK)) == 1
    with pytest.raises(ValueError):
        fn({})
    with pytest.raises(ValueError):
        fn({"count": 1, "stress": 9})
    schema = TOOLS["log_evening_intake"]["schema"]["inputSchema"]
    assert {"hunger", "stress", "cravings", "word", "count"} <= set(schema["properties"]) and schema["required"] == []


def test_mcp_door_after_midnight_files_last_evening_and_the_next_prompt_still_goes_out(monkeypatch):
    """00:30 PT with no date: the check-in keys to the previous evening (the Telegram door's rollover), so the
    next evening's 20:00 run is not fooled into `already_logged`. An explicit date is honoured as given."""
    from mcp import tools_lifestyle as tl
    from mcp.registry import TOOLS

    table = Table()
    after_midnight = EVENING + timedelta(hours=4, minutes=30)  # 00:30 PT the next calendar day
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "pacific_today", lambda: after_midnight.date().isoformat())
    monkeypatch.setattr(tl, "pacific_now", lambda: after_midnight)
    out = TOOLS["log_evening_intake"]["fn"]({"hunger": 2, "stress": 3, "cravings": 1, "word": "late"})
    assert out["date"] == DAY and (ec.PK, f"DATE#{DAY}") in table.store
    assert (ec.PK, f"DATE#{after_midnight.date().isoformat()}") not in table.store
    next_evening = EVENING + timedelta(days=1)
    seat = _seat_for({"nutrition_coach": ("tok-n", 4242)})
    assert ec.decide(table, next_evening.date().isoformat(), next_evening, seat)[0] == "send"  # not `already_logged`
    explicit = TOOLS["log_evening_intake"]["fn"]({"stress": 2, "date": "2026-10-20"})
    assert explicit["date"] == "2026-10-20"


# ── the scheduled prompt ────────────────────────────────────────────────────────────────────────


def test_prompt_goes_out_once_and_every_run_is_stamped():
    table, sent = Table(), []
    seat = _seat_for({"nutrition_coach": ("tok-n", 4242)})
    first = ec.run_prompt(table, EVENING, seat, lambda tok, chat, text: sent.append((tok, chat, text)), now_utc=EVENING_UTC)
    again = ec.run_prompt(table, EVENING, seat, lambda tok, chat, text: sent.append((tok, chat, text)), now_utc=EVENING_UTC)
    assert (first["reason"], again["reason"]) == ("sent", "already_prompted")
    assert sent == [("tok-n", 4242, ec.PROMPT_TEXT)] and len(ec.PROMPT_TEXT) <= 150
    assert table.store[(ec.LEDGER_PK, f"PROMPT#{DAY}")]["status"] == "sent"
    assert table.store[(ec.LEDGER_PK, f"EVAL#{DAY}")]["reason"] == "already_prompted"


def test_prompt_falls_back_to_the_lead_then_goes_dark_and_still_stamps():
    table, sent = Table(), []
    lead = _seat_for({"eli_marsh": ("tok-e", 4242)})
    assert ec.run_prompt(table, EVENING, lead, lambda *a: sent.append(a), now_utc=EVENING_UTC)["reason"] == "sent"
    assert sent[0][0] == "tok-e"
    dark_table = Table()
    assert ec.run_prompt(dark_table, EVENING, _seat_for({}), lambda *a: 1 / 0, now_utc=EVENING_UTC)["reason"] == "dark"
    assert dark_table.store[(ec.LEDGER_PK, f"EVAL#{DAY}")]["reason"] == "dark"


def test_no_prompt_when_tonight_is_logged_or_in_quiet_hours():
    table = Table()
    ec.write(table, DAY, {"hunger": 1, "stress": 1, "cravings": 1}, "mcp", now_utc=EVENING_UTC)
    seat = _seat_for({"nutrition_coach": ("tok-n", 4242)})
    assert ec.run_prompt(table, EVENING, seat, lambda *a: 1 / 0, now_utc=EVENING_UTC)["reason"] == "already_logged"
    late = datetime(2026, 10, 28, 21, 30, tzinfo=PACIFIC)
    assert ec.run_prompt(Table(), late, seat, lambda *a: 1 / 0, now_utc=EVENING_UTC)["reason"] == "quiet_hours"


def test_a_failing_send_path_still_feeds_the_dead_man():
    table = Table()
    out = ec.run_prompt(table, EVENING, lambda p: 1 / 0, lambda *a: None, now_utc=EVENING_UTC)
    assert out["ok"] is False and table.store[(ec.LEDGER_PK, f"EVAL#{DAY}")]["reason"] == "error:ZeroDivisionError"


# ── the dead-man (nightly qa-smoke) ─────────────────────────────────────────────────────────────


class _Check:
    def __init__(self, name, cat, tier):
        self.name, self.state, self.msg = name, None, ""

    def ok(self, m):
        self.state, self.msg = "ok", m
        return self

    def fail(self, m):
        self.state, self.msg = "fail", m
        return self


class _QTable:
    def __init__(self, rows):
        self._rows = rows

    def query(self, **kw):
        return {"Items": list(self._rows)}


def test_dead_man_reds_a_completed_day_with_no_stamp_and_passes_when_stamped():
    from operational import nudge_ledger_qa as q

    assert q.EVENING_CHECKIN_LEDGER_PK == ec.LEDGER_PK and q.STEPS_EVAL_PREFIX == ec.EVAL_PREFIX  # the pair contract
    now = datetime(2026, 11, 2, 11, 0, tzinfo=PACIFIC)
    days = ["2026-10-30", "2026-10-31", "2026-11-01"]
    red = q.check_evening_checkin_liveness(_QTable([{"sk": f"EVAL#{days[0]}"}]), _Check, "t", lambda: now)[0]
    assert red.state == "fail" and red.name == "evening_checkin_nudge:eval_liveness" and days[2] in red.msg
    green = q.check_evening_checkin_liveness(_QTable([{"sk": f"EVAL#{d}"} for d in days]), _Check, "t", lambda: now)[0]
    assert green.state == "ok"
    before = q.check_evening_checkin_liveness(_QTable([]), _Check, "t", lambda: datetime(2026, 10, 20, 11, tzinfo=PACIFIC))[0]
    assert before.state == "ok" and "pending" in before.msg  # not armed yet: no evidence, never a red


def test_dead_man_is_registered_in_the_nightly_run():
    src = open(os.path.join(REPO, "lambdas", "operational", "qa_smoke_lambda.py"), encoding="utf-8").read()
    assert "nudge_ledger_qa.check_evening_checkin_liveness(" in src


def test_the_evening_rule_is_owner_required_cdk_and_not_on_main_yet():
    """The schedule row, the rule (its Lambda permission) and the worker's write grant are owner-required CDK:
    they land together in PR #5218 with the owner's attended `cdk_deploy.sh LifePlatformServe`, which replaces
    this test with the quiet-hours/row/rule/grant assertions."""
    rows = json.load(open(os.path.join(REPO, "config", "schedules.json"), encoding="utf-8"))["schedules"]
    assert "telegram-coach-worker#TelegramEveningCheckin" not in rows


# ── the pair join ───────────────────────────────────────────────────────────────────────────────

LINE = 300.0  # a synthetic complete-log line for the fixture (the live one is the redline the titration rule names)


def _food(kcal, protein, times=()):
    return {"sk": "DATE#x", "total_calories_kcal": Decimal(str(kcal)), "total_protein_g": protein, "food_log": [{"time": t} for t in times]}


def test_join_day_uses_the_target_the_hit_and_the_last_timed_row():
    row = cip.join_day(
        {"hunger": 2, "stress": 3, "cravings": 1}, _food(1100, 90, ("08:10", "21:45", "13:00")), {}, 1000, LINE, lambda g: g >= 50
    )
    assert (row["kcal_over_target"], row["protein_hit"], row["last_meal_min"]) == (100.0, 1.0, 21 * 60 + 45)
    assert row["mood_valence"] is None


def test_an_incomplete_or_absent_log_is_unknown_never_a_low_day():
    partial = cip.join_day({"stress": 4}, _food(150, 10, ("09:00",)), {}, 1000, LINE, lambda g: g >= 50)
    absent = cip.join_day({"stress": 4}, None, None, 1000, LINE, lambda g: g >= 50)
    for row in (partial, absent):
        assert row["kcal_over_target"] is None and row["protein_hit"] is None and row["last_meal_min"] is None
    no_target = cip.join_day({"stress": 1}, _food(1000, 40), {}, None, LINE, lambda g: False)
    assert no_target["kcal_over_target"] is None and no_target["protein_hit"] == 0.0


# ── the weekly family through the engine's own pipeline ─────────────────────────────────────────


def _engine():
    import weekly_correlation_compute_lambda as wc

    return wc.compute_correlations


def _series(n, *, coupled):
    rng = random.Random(5106)
    d0 = datetime(2026, 8, 1)
    out = {}
    for i in range(n):
        stress = rng.randint(0, 4)
        kcal = 1000 + (90 * stress if coupled else 0) + rng.gauss(0, 60)
        food = _food(round(kcal), 60, ("12:00",))
        out[(d0 + timedelta(days=i)).strftime("%Y-%m-%d")] = cip.join_day(
            {"hunger": rng.randint(0, 4), "stress": stress, "cravings": rng.randint(0, 4)}, food, {}, 1000, LINE, lambda g: g >= 50
        )
    return out


def test_under_powered_family_says_too_early_to_say():
    results = cip.evaluate_family(_series(6, coupled=True), _engine(), 10)
    assert set(results) == {p[2] for p in cip.PAIRS}
    assert all(r["verdict"].startswith("too early to say") for r in results.values())


def test_an_empty_window_still_names_every_pair_honestly():
    results = cip.evaluate_family({}, _engine(), 10)
    assert {r["verdict"] for r in results.values()} == {"too early to say: 0 paired day(s), 10 needed"}


def test_powered_synthetic_stress_to_intake_is_found_and_worded_as_an_association():
    results = cip.evaluate_family(_series(70, coupled=True), _engine(), 10)
    hit = results["stress_vs_kcal_over_target"]
    assert hit["fdr_significant"] is True and hit["direction"] == "positive" and hit["n_eff"] is not None
    assert "association" in hit["verdict"] and "not a cause" in hit["verdict"] and "95% CI" in hit["verdict"]
    null = cip.evaluate_family(_series(70, coupled=False), _engine(), 10)["stress_vs_kcal_over_target"]
    assert null["verdict"].startswith("no reliable link yet")


def test_run_stores_the_owner_only_record_apart_from_the_public_one(monkeypatch):
    rng = random.Random(7)
    days = [(datetime(2026, 8, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]
    src = {
        "evening_checkin": [{"sk": f"DATE#{d}", "date": d, "stress": Decimal(rng.randint(0, 4))} for d in days],
        "macrofactor": [{"sk": f"DATE#{d}", "date": d, "total_calories_kcal": Decimal(900 + rng.randint(0, 200))} for d in days],
        "apple_health": [],
    }
    puts = []
    monkeypatch.setattr("health.titration.settings", lambda: {"complete_log_kcal": LINE})
    item = cip.run(
        fetch=lambda s, a, b: src[s],
        correlate=_engine(),
        put_item=lambda Item: puts.append(Item),
        week_key="2026-W35",
        start_date=days[0],
        end_date=days[-1],
        computed_at="2026-08-30T18:30:00+00:00",
        target_for=lambda d: 1000,
    )
    assert item["pk"] == "USER#matthew#SOURCE#checkin_intake_pairs" and item["sk"] == "WEEK#2026-W35" and item["tier"] == "owner_only"
    assert item["n_checkin_days"] == 30 and len(item["pairs"]) == 30 and isinstance(puts[0]["pairs"][0]["kcal"], Decimal)
    assert "stress_vs_kcal_over_target" in item["correlations"]


def test_the_weekly_engine_wires_the_family_and_keeps_its_public_pairs():
    import weekly_correlation_compute_lambda as wc

    src = open(wc.__file__, encoding="utf-8").read()
    assert "checkin_intake_pairs.run(" in src and "correlate=compute_correlations" in src
    public = {p[2] for p in wc.CORRELATION_PAIRS}
    assert not public & {p[2] for p in cip.PAIRS}  # the private family never joins the served record


# ── privacy ─────────────────────────────────────────────────────────────────────────────────────


def test_no_published_module_reads_either_partition():
    offenders = []
    for top in ("web", "emails"):
        for root, _dirs, files in os.walk(os.path.join(REPO, "lambdas", top)):
            for f in files:
                if f.endswith(".py"):
                    text = open(os.path.join(root, f), encoding="utf-8").read()
                    if any(s in text for s in ("evening_checkin", "checkin_intake_pairs")):
                        offenders.append(os.path.join(root, f))
    assert offenders == []


def test_both_partitions_are_owner_only_and_classed():
    from experiment.phase_taxonomy import SOURCE_CLASS, classify
    from privacy.field_tiers import SOURCE_TIERS, TIER_OWNER_ONLY

    assert SOURCE_TIERS["evening_checkin"] == SOURCE_TIERS["checkin_intake_pairs"] == TIER_OWNER_ONLY
    assert SOURCE_CLASS["evening_checkin"] == "raw_timeseries" and SOURCE_CLASS["checkin_intake_pairs"] == "cross_phase"
    assert classify(ec.LEDGER_PK, f"EVAL#{DAY}") == "system_state"
