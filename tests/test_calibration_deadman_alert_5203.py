"""tests/test_calibration_deadman_alert_5203.py — the calibration dead-man reaches the owner at ANY budget tier (#5203).

Owner ruling 2026-10-23: BOTH a plain fixed-text Telegram message (no AI, any tier, $0) AND a CloudWatch email alarm.

Holds:
  * the dead-man left the AI sweep (`detect_calibration` no longer emits it), so `_PAUSE_TIER` cannot silence it;
  * `coach.calibration_deadman_alert` never imports the chat / AI / budget path (structural, AST);
  * through the worker's real `event_outbound` handler at tier 2 AND tier 3 the AI sweep stands down with
    `reason: budget` and the plain text is still delivered, once per cycle, to the lead's private seat;
  * a dark seat sends nothing and says so; a failed send is loud, never raised;
  * the nightly witness emits `CalibrationDeadman{Job=calibration}` and the `calibration-deadman` alarm reads that
    exact series, breaches on >= 1, treats missing as not-breaching, and routes to the ALERTS topic (email).

No clock is read: every moment is injected (#4848).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

from coach import (
    calibration_deadman_alert as cda,  # noqa: E402
    coach_event_triggers as cet,  # noqa: E402
)
from common.pacific_time import PACIFIC  # noqa: E402
from training import calibration_cadence as cc  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

CYCLE = int(charter_value("calibration.tape_and_photos.every_weeks")) * 7
GENESIS = "2026-09-06"
LAST = "2026-10-05"
MORNING = datetime(2026, 11, 16, 9, 0, tzinfo=PACIFIC)  # a Monday, 09:00 PT — outside quiet hours
NIGHT = datetime(2026, 11, 16, 22, 30, tzinfo=PACIFIC)


def plus(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def dead_block(today: str) -> dict:
    return cc.compute(today, {"tape": lambda: [LAST], "photos": lambda: [today], "dexa": lambda: []}, anchor=GENESIS)


class Ledger:
    def __init__(self):
        self.rows = {}

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803 — boto3 signature
        if Item["sk"] in self.rows:
            raise RuntimeError("ConditionalCheckFailedException")
        self.rows[Item["sk"]] = Item


def _today() -> str:
    return MORNING.strftime("%Y-%m-%d")


# ── the AI sweep no longer carries it ──────────────────────────────────────────────────────
def test_the_deadman_is_not_an_ai_sweep_candidate():
    today = plus(LAST, CYCLE * 3)
    block = dead_block(today)
    assert cc.deadman_kinds(block) == ["tape"]
    assert [e for e in cet.detect_calibration(block, today) if e["kind"] == "calibration_deadman"] == []
    assert cda.due(block)[0]["event_id"] == f"CALIB_DEADMAN#tape#{LAST}"


def test_the_alert_module_never_touches_the_ai_or_budget_path():
    src = (ROOT / "lambdas" / "coach" / "calibration_deadman_alert.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    bad = [
        m
        for m in imported
        if m in ("ai", "coach.coach_chat") or m.startswith("ai.") or "budget" in m or "bedrock" in m or m.endswith(".coach_chat")
    ]
    assert bad == [], bad
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    assert "_PAUSE_TIER" not in code and "tier" not in re.sub(r"#.*", "", code)


def test_the_seat_is_the_leads():
    assert cda.PERSONA == cet.LEAD_OWNER


# ── delivery ────────────────────────────────────────────────────────────────────────────────
def test_sends_plain_text_once_per_cycle():
    block = dead_block(_today())
    ledger, sent = Ledger(), []
    seat = lambda p: ("tok", 4242)  # noqa: E731
    out = cda.run(ledger, MORNING, seat, lambda t, c, text: sent.append((t, c, text)), block=block)
    assert out == {"reason": "sent", "sent": ["tape"]}
    assert sent == [("tok", 4242, cda.PREFIX + cc.deadman_alert(block["kinds"]["tape"]))]
    assert "tape has gone" in sent[0][2] and LAST in sent[0][2]
    again = cda.run(ledger, MORNING, seat, lambda t, c, text: sent.append(text), block=block)
    assert again["sent"] == [] and len(sent) == 1


def test_quiet_hours_and_a_dark_seat_send_nothing():
    block, sent = dead_block(_today()), []
    assert cda.run(Ledger(), NIGHT, lambda p: ("tok", 1), lambda *a: sent.append(a), block=block)["reason"] == "quiet hours"
    dark = cda.run(Ledger(), MORNING, lambda p: (None, None), lambda *a: sent.append(a), block=block)
    assert dark["reason"] == "dark" and dark["due"] == ["tape"] and sent == []


def test_a_failed_send_or_read_is_loud_never_raised(caplog):
    def boom(*a):
        raise RuntimeError("telegram down")

    out = cda.run(Ledger(), MORNING, lambda p: ("tok", 1), boom, block=dead_block(_today()))
    assert out["sent"] == [] and cda.FAILED_TOKEN in caplog.text

    class Broken:
        def query(self, **kw):
            raise RuntimeError("ddb")

    assert cda.run(Broken(), MORNING, lambda p: ("tok", 1), boom)["reason"] in ("read_failed", "none due")


@pytest.mark.parametrize("tier", [2, 3])
def test_delivered_through_the_worker_at_budget_tier(tier, monkeypatch):
    from coach import telegram_worker_lambda as worker

    block = dead_block(_today())
    ledger, sends, turns = Ledger(), [], []
    monkeypatch.setattr(worker, "_tg", lambda token, method, payload: sends.append((token, method, dict(payload))))
    monkeypatch.setattr(worker, "_current_tier", lambda: tier)
    monkeypatch.setattr(worker, "_table", lambda: ledger)
    monkeypatch.setattr(worker, "_pacific_now", lambda: MORNING)
    monkeypatch.setattr(worker, "_bot_seat", lambda persona: ("lead-token", 777) if persona == cet.LEAD_OWNER else (None, None))
    monkeypatch.setattr(worker, "_emit_metric", lambda *a, **k: None)
    monkeypatch.setattr(worker.coach_chat, "run_turn", lambda **kw: turns.append(kw))
    monkeypatch.setattr(cc, "read", lambda table, today: block)

    out = worker.lambda_handler({"kind": "event_outbound"}, None)
    assert out["reason"] == "budget"  # the AI sweep stood down ...
    assert out["calibration_deadman"]["sent"] == ["tape"]  # ... and the dead-man went anyway
    assert [(t, m, p["chat_id"]) for t, m, p in sends] == [("lead-token", "sendMessage", 777)]
    assert sends[0][2]["text"].startswith(cda.PREFIX) and turns == []  # no model turn


# ── the email alarm ─────────────────────────────────────────────────────────────────────────
def test_the_witness_emits_the_series_the_alarm_reads(monkeypatch, capsys):
    from mcp import calibration_leg as leg

    line = json.loads(leg.emf_line(2))
    m = line["_aws"]["CloudWatchMetrics"][0]
    assert (m["Namespace"], m["Metrics"][0]["Name"], line["Job"], line[leg.METRIC_NAME]) == (
        "LifePlatform/HevyRoutine",
        "CalibrationDeadman",
        "calibration",
        2,
    )
    stack = (ROOT / "cdk" / "stacks" / "mcp_stack.py").read_text(encoding="utf-8")
    body = re.search(r'"CalibrationDeadman",\s*alarm_name="calibration-deadman",(.*?)\n\n', stack, re.S)
    assert body, "the calibration-deadman alarm is declared in mcp_stack.py"
    text = body.group(1)
    assert f'namespace="{leg.METRIC_NAMESPACE}"' in text and f'metric_name="{leg.METRIC_NAME}"' in text
    assert 'dimensions_map={"Job": "calibration"}' in text and "threshold=1," in text
    assert "GREATER_THAN_OR_EQUAL_TO_THRESHOLD" in text and "TreatMissingData.NOT_BREACHING" in text
    assert "calibration_deadman_alarm.add_alarm_action(cw_actions.SnsAction(local_alerts_topic))" in text


def test_the_nightly_leg_prints_one_datapoint_on_a_successful_check(monkeypatch, capsys):
    import types

    from mcp import calibration_leg as leg

    fake_core = types.ModuleType("mcp.core")
    fake_core.table = object()
    monkeypatch.setitem(sys.modules, "mcp.core", fake_core)
    import mcp

    monkeypatch.setattr(mcp, "core", fake_core, raising=False)
    monkeypatch.setattr(cc, "read", lambda table, today: dead_block(today))
    out = leg.calibration_leg(_today())
    assert out["deadman"] == ["tape"]
    emf = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    assert [e["CalibrationDeadman"] for e in emf] == [1]
