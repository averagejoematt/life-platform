"""#2820 — the subscriber-promise delivery dead-man.

The Wednesday chronicle (and Sunday Weekly Signal) are public subscriber
promises whose silent no-send produced zero signal on every channel: the Viktor
guard is a clean no-op, DLQ alarms need a crash, and qa_check_subscriber_promise
verifies the SWITCH, not delivery. #2820 makes every non-dry-run sender run emit
ONE LifePlatform/Email datapoint (ChronicleSent / WeeklySignalSent), alarmed by
the email_stack delivery heartbeats (Sum < 1 across 7 daily buckets, BREACHING).

Two halves proven here, offline (no AWS):

A. EMISSION — the handlers' REAL paths emit the right datapoint per state,
   including a missed Wednesday injected into the real checker path (the DDB
   query returns no installment; `_get_this_weeks_installment` itself runs):
     - missed week, budget healthy      -> 0   (the datapoint that lets it page)
     - missed week, budget-paused       -> 1   (sanctioned emit-and-skip, #2490)
     - real send                        -> N   (actual SES sends)
     - kill-switch / zero subscribers   -> 0   (outcome-honest; #1951 names cause)
     - dry_run                          -> no emit at all
     - a crash                          -> no emit (missing data = BREACHING)

B. CONTRACT — the CDK alarm and the emitting lambda are a "must agree" pair
   (charter standing rule 3): the alarm's namespace/metric-name are asserted
   equal to the lambda modules' own constants, and the alarm shape (Sum, daily
   period, 7x7, LT 1, BREACHING, urgent topic) is verified by AST over
   cdk/stacks/email_stack.py — NEVER by importing it (aws_cdk is not installed
   in the unit/deploy-critical lanes; an import fails at collection).
"""

import ast
import importlib
import os
import re
import sys
from unittest import mock

import pytest

# #416 / ADR-117: a delivery dead-man whose metric name silently diverges from
# its alarm is exactly the "wiring silently broken" class.
pytestmark = pytest.mark.deploy_critical

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EMAIL_STACK = os.path.join(_REPO, "cdk", "stacks", "email_stack.py")
_ROLE_POLICIES = os.path.join(_REPO, "cdk", "stacks", "role_policies_email.py")

for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "emails"), os.path.join(_REPO, "lambdas", "compute")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

cel = importlib.import_module("chronicle_email_sender_lambda")
wsl = importlib.import_module("weekly_signal_lambda")


def _emitted(cw_mock):
    """Unpack (metric_name, value) pairs from a mocked put_metric_data client."""
    out = []
    for _, kwargs in cw_mock.put_metric_data.call_args_list:
        assert kwargs["Namespace"] == "LifePlatform/Email"
        for md in kwargs["MetricData"]:
            out.append((md["MetricName"], md["Value"]))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# A. chronicle-email-sender emission
# ─────────────────────────────────────────────────────────────────────────────


def _run_chronicle(monkeypatch, *, ddb_items, tier, subscribers=None, event=None, ses_ok=True):
    """Run the REAL handler: the installment checker executes against a mocked
    table.query (the wire the missed Wednesday is injected on), the budget tier
    is pinned via ai.budget_guard.current_tier, and cw is a mock we inspect."""
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    cw_mock = mock.MagicMock()

    def _send(**kwargs):
        if not ses_ok:
            raise RuntimeError("SES down")
        return {"MessageId": "fake"}

    with (
        mock.patch.object(cel, "cw", cw_mock),
        mock.patch.object(cel.table, "query", return_value={"Items": ddb_items}),
        mock.patch.object(cel.table, "update_item"),
        mock.patch.object(cel.table, "put_item"),
        mock.patch.object(cel, "_get_confirmed_subscribers", return_value=subscribers or []),
        mock.patch.object(cel.ses, "send_email", side_effect=_send),
        mock.patch.object(cel, "time") as fake_time,
        mock.patch("ai.budget_guard.current_tier", return_value=tier),
    ):
        fake_time.sleep.return_value = None
        fake_time.time.return_value = 1_700_000_000.0
        result = cel.lambda_handler(event or {}, None)
    return result, cw_mock


def _published_installment():
    return {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": "DATE#2026-08-19",
        "date": "2026-08-19",
        "week_number": 3,
        "title": "A Week",
        "status": "published",
        "content_html": "<p>x</p>",
    }


def test_missed_wednesday_emits_zero_through_the_real_checker_path(monkeypatch):
    """THE issue scenario: no installment row exists this week (generation died
    silently), budget healthy. The real `_get_this_weeks_installment` runs, finds
    nothing, and the run must emit ChronicleSent=0 — the datapoint that lets
    chronicle-delivery-heartbeat page instead of a clean silent no-op."""
    result, cw_mock = _run_chronicle(monkeypatch, ddb_items=[], tier=0)
    assert result["skipped"] is True
    assert _emitted(cw_mock) == [("ChronicleSent", 0.0)]


def test_missed_wednesday_on_budget_paused_week_emits_sanctioned_datapoint(monkeypatch):
    """Tier >= 2 pauses chronicle generation (ADR-125), so an absent installment
    is a sanctioned state: the #2490 emit-and-skip datapoint (value 1) keeps the
    dead-man quiet without inventing a delivery."""
    result, cw_mock = _run_chronicle(monkeypatch, ddb_items=[], tier=2)
    assert result["skipped"] is True
    assert _emitted(cw_mock) == [("ChronicleSent", 1.0)]


def test_real_send_emits_actual_send_count(monkeypatch):
    subs = [{"email": "a@example.com", "status": "confirmed"}, {"email": "b@example.com", "status": "confirmed"}]
    result, cw_mock = _run_chronicle(monkeypatch, ddb_items=[_published_installment()], tier=0, subscribers=subs)
    assert result["sent"] == 2
    assert _emitted(cw_mock) == [("ChronicleSent", 2.0)]


def test_total_send_failure_emits_honest_zero(monkeypatch):
    """Every SES call failing must emit 0, never the attempted count — sent==0
    also leaves the installment unmarked, so a later trigger retries and the
    dead-man pages if none succeeds within the week (ADR-104: honest numbers)."""
    subs = [{"email": "a@example.com", "status": "confirmed"}]
    result, cw_mock = _run_chronicle(monkeypatch, ddb_items=[_published_installment()], tier=0, subscribers=subs, ses_ok=False)
    assert result["sent"] == 0
    assert _emitted(cw_mock) == [("ChronicleSent", 0.0)]


def test_kill_switch_skip_emits_zero_not_sanctioned(monkeypatch):
    """A switched-off week is still an unfulfilled promise — 0, not 1. The
    #1951 kill-switch alarm names the cause; this metric tracks the outcome."""
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "false")
    cw_mock = mock.MagicMock()
    with mock.patch.object(cel, "cw", cw_mock):
        result = cel.lambda_handler({}, None)
    assert result["skipped"] is True
    assert _emitted(cw_mock) == [("ChronicleSent", 0.0)]


def test_zero_subscribers_emits_zero_not_sanctioned(monkeypatch):
    """The subscriber query fail-softs to [] on a DDB error; a sanctioned
    datapoint here would let a broken read mask a missed delivery."""
    result, cw_mock = _run_chronicle(monkeypatch, ddb_items=[_published_installment()], tier=0, subscribers=[])
    assert result["sent"] == 0
    assert _emitted(cw_mock) == [("ChronicleSent", 0.0)]


def test_dry_run_emits_nothing(monkeypatch):
    """A diagnostic invoke is not the scheduled path — it must leave no
    datapoint (neither fulfilling nor breaching the week)."""
    cw_mock = mock.MagicMock()
    with (
        mock.patch.object(cel, "cw", cw_mock),
        mock.patch.object(cel.table, "query", return_value={"Items": [_published_installment()]}),
        mock.patch.object(cel, "_get_confirmed_subscribers", return_value=[]),
    ):
        result = cel.lambda_handler({"dry_run": True}, None)
    assert result["dry_run"] is True
    cw_mock.put_metric_data.assert_not_called()


def test_budget_paused_helper_fails_toward_paging(monkeypatch):
    """An unreadable tier must read as NOT sanctioned — a broken SSM read makes
    the dead-man MORE likely to page, never less."""
    with mock.patch("ai.budget_guard.allow", side_effect=RuntimeError("ssm down")):
        assert cel._chronicle_budget_paused() is False
    with mock.patch("ai.budget_guard.current_tier", return_value=0):
        assert cel._chronicle_budget_paused() is False
    with mock.patch("ai.budget_guard.current_tier", return_value=2):
        assert cel._chronicle_budget_paused() is True


def test_emit_is_failsoft(monkeypatch):
    """A metrics outage must never fail a send — and a persistently failed emit
    IS a missing datapoint, which the alarm treats as BREACHING."""
    cw_mock = mock.MagicMock()
    cw_mock.put_metric_data.side_effect = RuntimeError("cloudwatch down")
    with mock.patch.object(cel, "cw", cw_mock):
        cel._emit_sent_metric(1, "test")  # must not raise
    with mock.patch.object(wsl, "cw", cw_mock):
        wsl._emit_sent_metric(1, "test")  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# A2. weekly-signal emission (the same one-metric pattern)
# ─────────────────────────────────────────────────────────────────────────────


def _run_weekly_signal(monkeypatch, *, subscribers, event=None):
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    cw_mock = mock.MagicMock()
    with (
        mock.patch.object(wsl, "cw", cw_mock),
        mock.patch.object(wsl, "_s3_json", return_value=None),
        mock.patch.object(wsl, "_get_weekly_insight", return_value=None),
        mock.patch.object(wsl, "_get_confirmed_subscribers", return_value=subscribers),
        mock.patch.object(wsl.ses, "send_email", return_value={"MessageId": "fake"}),
        mock.patch.object(wsl, "time") as fake_time,
    ):
        fake_time.sleep.return_value = None
        result = wsl.lambda_handler(event or {}, None)
    return result, cw_mock


def test_weekly_signal_send_emits_count(monkeypatch):
    subs = [{"email": "a@example.com", "status": "confirmed"}]
    result, cw_mock = _run_weekly_signal(monkeypatch, subscribers=subs)
    assert result["sent"] == 1
    assert _emitted(cw_mock) == [("WeeklySignalSent", 1.0)]


def test_weekly_signal_zero_subscribers_emits_zero(monkeypatch):
    result, cw_mock = _run_weekly_signal(monkeypatch, subscribers=[])
    assert result["sent"] == 0
    assert _emitted(cw_mock) == [("WeeklySignalSent", 0.0)]


def test_weekly_signal_kill_switch_emits_zero(monkeypatch):
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "false")
    cw_mock = mock.MagicMock()
    with mock.patch.object(wsl, "cw", cw_mock):
        result = wsl.lambda_handler({}, None)
    assert result["skipped"] is True
    assert _emitted(cw_mock) == [("WeeklySignalSent", 0.0)]


def test_weekly_signal_dry_run_emits_nothing(monkeypatch):
    cw_mock = mock.MagicMock()
    with (
        mock.patch.object(wsl, "cw", cw_mock),
        mock.patch.object(wsl, "_s3_json", return_value=None),
        mock.patch.object(wsl, "_get_weekly_insight", return_value=None),
        mock.patch.object(wsl, "_get_confirmed_subscribers", return_value=[]),
    ):
        result = wsl.lambda_handler({"dry_run": True}, None)
    assert result["dry_run"] is True
    cw_mock.put_metric_data.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# B. alarm <-> emitter contract (AST over email_stack.py — no aws_cdk import)
# ─────────────────────────────────────────────────────────────────────────────

# CloudWatch caps evaluation_periods x period at 604800s (7 days) — the reason
# the issue's "8 days" landed as 7x86400 (see the email_stack comment).
_CW_EVAL_CAP_S = 604800


def _alarm_calls():
    with open(_EMAIL_STACK, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "Alarm":
            kw = {k.arg: k.value for k in node.keywords}
            name = kw.get("alarm_name")
            if isinstance(name, ast.Constant):
                found[name.value] = kw
    return found


def _metric_kwargs(alarm_kw):
    metric_call = alarm_kw["metric"]
    assert isinstance(metric_call, ast.Call), "alarm metric must be an inline cloudwatch.Metric(...) call"
    return {k.arg: k.value for k in metric_call.keywords}


@pytest.mark.parametrize(
    "alarm_name,lambda_module",
    [
        ("chronicle-delivery-heartbeat", cel),
        ("weekly-signal-delivery-heartbeat", wsl),
    ],
)
def test_alarm_watches_exactly_what_the_lambda_emits(alarm_name, lambda_module):
    """The must-agree pair: alarm namespace/metric-name == the emitting module's
    own constants. A rename on either side reds this before it ships dark."""
    alarms = _alarm_calls()
    assert alarm_name in alarms, f"{alarm_name} not defined in email_stack.py"
    mkw = _metric_kwargs(alarms[alarm_name])
    assert mkw["namespace"].value == lambda_module.METRIC_NAMESPACE
    assert mkw["metric_name"].value == lambda_module.SENT_METRIC_NAME


@pytest.mark.parametrize("alarm_name", ["chronicle-delivery-heartbeat", "weekly-signal-delivery-heartbeat"])
def test_alarm_shape_is_the_weekly_deadman(alarm_name):
    """Sum over daily buckets, 7-of-7 below 1, missing data BREACHING: no
    delivery (and no sanctioned pause) for a week pages; a dead cron — which
    emits nothing at all — pages too. 7x86400 is the CloudWatch quota maximum,
    and a healthy fixed-UTC weekly send leaves at most 6 empty daily buckets,
    so the alarm cannot false-fire on cadence alone."""
    kw = _alarm_calls()[alarm_name]
    mkw = _metric_kwargs(kw)
    assert mkw["statistic"].value == "Sum"
    period_call = mkw["period"]
    assert isinstance(period_call, ast.Call) and period_call.args[0].value == 86400
    assert kw["threshold"].value == 1
    assert kw["evaluation_periods"].value == 7
    assert kw["datapoints_to_alarm"].value == 7
    assert kw["evaluation_periods"].value * period_call.args[0].value <= _CW_EVAL_CAP_S
    assert kw["comparison_operator"].attr == "LESS_THAN_THRESHOLD"
    assert kw["treat_missing_data"].attr == "BREACHING"


def test_alarms_page_urgent_not_digest():
    """The issue's severity call: a missed subscriber promise is urgent. Both
    heartbeats must action the alerts topic (never only the digest)."""
    src = open(_EMAIL_STACK, encoding="utf-8").read()
    for var in ("_chronicle_delivery_heartbeat", "_weekly_signal_delivery_heartbeat"):
        m = re.search(rf"{var}\.add_alarm_action\(cw_actions\.SnsAction\((\w+)\)\)", src)
        assert m, f"{var} has no add_alarm_action in email_stack.py"
        assert m.group(1) == "local_alerts_topic", f"{var} pages {m.group(1)}, expected local_alerts_topic (urgent)"


def test_sender_roles_carry_the_new_grants():
    """The emit path is only reachable if the roles grant it: PutMetricData on
    both senders, plus the budget-tier SSM read the sanctioned-pause check
    needs on the chronicle sender (fail-open would otherwise mask nothing —
    but a silently Denied emit would be a missing datapoint every week)."""
    src = open(_ROLE_POLICIES, encoding="utf-8").read()
    tree = ast.parse(src)
    bodies = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("email_chronicle_sender", "email_weekly_signal"):
            bodies[node.name] = ast.get_source_segment(src, node)
    assert set(bodies) == {"email_chronicle_sender", "email_weekly_signal"}
    for name, body in bodies.items():
        assert "cloudwatch:PutMetricData" in body, f"{name} lacks the PutMetricData grant"
    assert "life-platform/budget-tier" in bodies["email_chronicle_sender"], "chronicle sender lacks the budget-tier SSM read"
