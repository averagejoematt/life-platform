"""tests/test_suppressor_registry_4034.py — the suppressor registry (#4034 box 3).

A suppressor is an alarm whose ALARM state gates a composite — usually a NOT() term, so
while it is red a real page is withheld. #3503 taught the sweeps to stop triaging the one
member (`cdk/stacks/constants.BY_CONSTRUCTION_FLAG_ALARMS`) as an incident. That left the
opposite hole: a suppressor stuck red withholds its composite's page forever, and the
exclusion hid exactly that. #4034 makes the registry say what it means:

  * every member names the composites whose ALARM_RULE consumes it — contract-tested here
    against the LIVE alarm-plane builder (scripts/platform_model_alarms.extract_alarms),
    never the committed model; on its first run this found the registry naming 2 of the 4
    composites that consume the genesis gauge;
  * every alarm that appears under an `AlarmRule.not_(...)` term anywhere in cdk/stacks is a
    registry member (guard the SET — an unregistered suppressor is the specimen, not a style
    nit);
  * every member carries a window with a stated end condition, and a dead-man reds past it
    in BOTH sweeps (remediation/agent.py's needs-human email and the /wrap citation gate);
  * the sweeps exclude by TYPE (`suppression_holds`), never by a name written in the sweep.
"""

import ast
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("cdk", "scripts", "remediation", "lambdas"):
    p = os.path.join(_REPO, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from stacks import constants  # noqa: E402
from stacks.constants import (  # noqa: E402
    ALARM_TYPE_INCIDENT,
    ALARM_TYPE_SUPPRESSOR,
    SUPPRESSOR_REGISTRY,
    alarm_type,
    suppression_holds,
    suppressor_overdue,
)

STACKS_DIR = os.path.join(_REPO, "cdk", "stacks")
SWEEP_SOURCES = ("remediation/agent.py", "scripts/check_alarm_citations.py")
GAUGE = "token-alarm-genesis-window-active"


# ── registry shape ──────────────────────────────────────────────────────────


def test_registry_is_not_empty_and_the_alias_is_the_same_object():
    assert SUPPRESSOR_REGISTRY, "suppressor registry emptied — every check below is vacuous"
    assert SUPPRESSOR_REGISTRY is constants.BY_CONSTRUCTION_FLAG_ALARMS


@pytest.mark.parametrize("name", sorted(SUPPRESSOR_REGISTRY))
def test_every_member_declares_type_window_and_end_condition(name):
    row = SUPPRESSOR_REGISTRY[name]
    assert row.get("type") == ALARM_TYPE_SUPPRESSOR, f"{name}: type must be {ALARM_TYPE_SUPPRESSOR!r}"
    assert isinstance(row.get("window_hours"), int) and row["window_hours"] > 0, f"{name}: window_hours must be a positive int"
    assert len(str(row.get("end_condition", "")).strip()) >= 40, f"{name}: state the END CONDITION of the window (>= 40 chars)"
    assert row.get("composites"), f"{name}: a suppressor that gates no composite is not a suppressor"


# ── contract: composites named == composites whose alarm_rule consumes it ───


def _live_alarm_plane():
    import platform_model_alarms  # scripts/ — the AST builder, run live

    return platform_model_alarms.extract_alarms()


def test_named_composites_equal_the_alarm_rule_consumers():
    plane = _live_alarm_plane()
    bad = []
    for name, row in sorted(SUPPRESSOR_REGISTRY.items()):
        assert name in plane, f"{name} is not an alarm the live CDK alarm plane knows"
        live = set(plane[name].get("composites") or [])
        declared = set(row["composites"])
        if live != declared:
            bad.append(f"  {name}: declared {sorted(declared)} but the alarm_rule AST consumes it in {sorted(live)}")
        for comp in declared:
            if plane.get(comp, {}).get("kind") != "composite":
                bad.append(f"  {name}: {comp} is not a composite alarm in cdk/stacks")
    assert not bad, "Suppressor registry disagrees with the composites that actually consume each member:\n" + "\n".join(bad)


def _not_term_alarms(tree: ast.AST) -> set:
    """Alarm names under an `AlarmRule.not_(...)` term, resolved through the variables
    `x = Alarm(..., alarm_name="...")` and `r = AlarmRule.from_alarm(x, ...)`."""
    alarm_var, rule_var = {}, {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        call = node.value
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        name_kw = next((kw.value for kw in call.keywords if kw.arg == "alarm_name"), None)
        if isinstance(name_kw, ast.Constant) and isinstance(name_kw.value, str):
            for t in targets:
                alarm_var[t] = name_kw.value
        if isinstance(call.func, ast.Attribute) and call.func.attr == "from_alarm" and call.args and isinstance(call.args[0], ast.Name):
            for t in targets:
                rule_var[t] = call.args[0].id
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "not_":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name):
                    var = rule_var.get(sub.id, sub.id)
                    if var in alarm_var:
                        out.add(alarm_var[var])
    return out


def test_every_not_term_alarm_is_a_registered_suppressor():
    found = set()
    for fn in sorted(os.listdir(STACKS_DIR)):
        if fn.endswith(".py"):
            with open(os.path.join(STACKS_DIR, fn), encoding="utf-8") as fh:
                found |= _not_term_alarms(ast.parse(fh.read()))
    assert GAUGE in found, "the NOT()-term discoverer no longer finds the genesis gauge — it rotted, and a rotted guard passes"
    missing = sorted(found - set(SUPPRESSOR_REGISTRY))
    assert not missing, (
        "Alarm(s) used as a NOT() term in a composite ALARM_RULE — i.e. suppressors by construction — with no row in "
        "cdk/stacks/constants.SUPPRESSOR_REGISTRY (#4034). Register each with type/window/end_condition/composites:\n  "
        + "\n  ".join(missing)
    )


def test_not_term_discoverer_catches_a_planted_unregistered_suppressor():
    src = (
        "g = cloudwatch.Alarm(s, 'G', alarm_name='planted-gauge')\n"
        "r = cloudwatch.AlarmRule.from_alarm(g, cloudwatch.AlarmState.ALARM)\n"
        "c = cloudwatch.CompositeAlarm(s, 'C', composite_alarm_name='c', alarm_rule=cloudwatch.AlarmRule.not_(r))\n"
    )
    assert _not_term_alarms(ast.parse(src)) == {"planted-gauge"}


def test_genesis_window_covers_the_stamped_window():
    """The declared window must cover what token_alarm_window.py actually stamps."""
    from common import token_alarm_window as taw

    floor_hours = (taw.WINDOW_DAYS_BEFORE + taw.WINDOW_DAYS_AFTER + 1) * 24
    declared = SUPPRESSOR_REGISTRY[GAUGE]["window_hours"]
    assert (
        declared >= floor_hours
    ), f"{GAUGE}: window_hours {declared} < the stamped window {floor_hours}h — the dead-man would fire in-window"
    assert (
        declared <= floor_hours + 48
    ), f"{GAUGE}: window_hours {declared} is far wider than the stamped {floor_hours}h — a wide window is a mute"


# ── exclusion by TYPE, never by name ────────────────────────────────────────


@pytest.mark.parametrize("rel", SWEEP_SOURCES)
def test_sweeps_exclude_by_type_not_by_name(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
        src = fh.read()
    assert "suppression_holds" in src, f"{rel} does not exclude through suppression_holds() (type + window, #4034)"
    literal = [name for name in SUPPRESSOR_REGISTRY if name in src]
    assert not literal, f"{rel} names suppressor(s) {literal} literally — exclude by TYPE via the registry, never by name"


# ── the window and the dead-man ─────────────────────────────────────────────

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat()


def test_type_lookup():
    assert alarm_type(GAUGE) == ALARM_TYPE_SUPPRESSOR
    assert alarm_type("qa-smoke-failures") == ALARM_TYPE_INCIDENT


def test_window_holds_inside_and_expires_past_it():
    window = SUPPRESSOR_REGISTRY[GAUGE]["window_hours"]
    assert suppression_holds(GAUGE, _ago(window - 1), NOW)
    assert not suppressor_overdue(GAUGE, _ago(window - 1), NOW)
    assert not suppression_holds(GAUGE, _ago(window + 1), NOW)
    assert suppressor_overdue(GAUGE, _ago(window + 1), NOW)
    # an incident is never held, however young
    assert not suppression_holds("qa-smoke-failures", _ago(1), NOW)


def test_unreadable_episode_start_fails_closed():
    assert suppressor_overdue(GAUGE, "", NOW)
    assert not suppression_holds(GAUGE, "not-a-timestamp", NOW)


def _agent():
    import agent  # noqa: PLC0415 — remediation/agent.py builds boto3 clients at import

    return agent


def test_agent_holds_an_in_window_suppressor_and_escalates_an_overdue_one():
    agent = _agent()
    window = SUPPRESSOR_REGISTRY[GAUGE]["window_hours"]
    young = {"name": GAUGE, "updated": _ago(100), "transitioned": _ago(100)}
    assert dict(agent.aged_alarm_escalations({"alarms": [young]}, now=NOW, audience={})) == {}

    stuck = {"name": GAUGE, "updated": _ago(window + 5), "transitioned": _ago(window + 5)}
    esc = dict(agent.aged_alarm_escalations({"alarms": [stuck]}, now=NOW, audience={}))
    assert GAUGE in esc, "a suppressor past its window was NOT escalated — the #4034 dead-man cannot fire"
    assert "past its declared" in esc[GAUGE]["issue"] and "ai-tokens-platform-daily-total-urgent" in esc[GAUGE]["issue"]
    # the ack ratchet never double-reports it
    assert agent.ack_ratchet_escalations({"alarms": [stuck]}, {GAUGE: {"renewals": 9}}, now=NOW) == []


def test_citation_gate_grades_an_overdue_suppressor_like_any_red(monkeypatch):
    import check_alarm_citations as cac

    window = SUPPRESSOR_REGISTRY[GAUGE]["window_hours"]

    class _CW:
        def __init__(self, hours):
            self.hours = hours

        def describe_alarms(self, **_):
            ts = NOW - timedelta(hours=self.hours)
            return {"MetricAlarms": [{"AlarmName": GAUGE, "StateUpdatedTimestamp": ts, "StateTransitionedTimestamp": ts}]}

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    import boto3

    monkeypatch.setattr(cac, "datetime", _Frozen)
    for hours, held in ((window - 2, True), (window + 2, False)):
        monkeypatch.setattr(boto3, "client", lambda *a, _h=hours, **k: _CW(_h))
        alarms, err = cac.fetch_alarms()
        assert err is None and alarms[0]["by_construction"] is held, (hours, alarms)
    # and past the window it now needs a citation like any other long red
    assert cac.uncited_long_reds(alarms, {}, now=NOW) != []
