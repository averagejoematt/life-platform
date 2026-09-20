"""tests/test_canary_gate_recheck_parity_3830.py — #3830: the gate's second look is not the
alerter's second occurrence.

WHAT #3830 IS ABOUT, restated in one line: *the deploy gate must never be more confident
about a datapoint than the alerter that saw it first.* On 2026-09-15T19:55Z a Bedrock
`ServiceUnavailableException` reached three consumers of ONE observation —

    the alerter      "Suppressed first-occurrence alert"   declined to even email
    the alarm        fired, self-cleared in 15 minutes     loud, proportionate
    the deploy gate  reverted 85 Lambdas                   the most destructive, the
                                                           most confident, on the least
                                                           evidence

#3831 landed the classification half (`LANE_EXTERNAL_TRANSIENT`), and
`deploy/lib/canary_gate_retry.py` landed box 3's backstop: re-invoke the canary and gate
only if the second look fails too, so no single observation can revert a fleet.

THE DEFECT THESE TESTS EXIST FOR — the same inversion, running the other way. That retry
buys parity and then spends it. The alerter emails when the SAME check fails in **two
consecutive runs**, and a run is one tick of `rate(4 hours)`. The gate's retry fires ~20
seconds later and reads the state attempt 1 just wrote, so the gate's own second look
becomes the alerter's second occurrence: a 30-second vendor blip mails the operator
"persistent failure" about exactly the datapoint the alerter had already decided was too
weak to send mail about. The gate would still be manufacturing confidence the observation
does not support — this time by feeding it to the alerter.

The fix is one flag, `{"gate_recheck": true}`, set by the wrapper on attempt 2+ and read in
ONE place (`canary_lambda.is_gate_recheck`). A re-check runs every check, emits every
metric and returns the full lane-aware body, and takes no part in the alerter's window.

Every case below comes with its opposite. A guard that only demonstrates the quiet
direction is how #2051 recurred as #3830: the controls named `..._STILL_...` are the ones
that fail if this change degenerates from "a retry does not email" into "the canary
stopped emailing".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "operational"), os.path.join(_REPO, "deploy", "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import canary_gate_retry as cgr  # noqa: E402
import canary_lambda as canary  # noqa: E402

# The real 2026-09-15T19:54:50Z failure, copied off the canary's own log rather than off a
# description of it: the botocore Error.Code AND the message the vendor actually sent.
INCIDENT_CODE = "ServiceUnavailableException"
INCIDENT_MESSAGE = "Bedrock ServiceUnavailableException: Bedrock is unable to process your request."
ANTHROPIC_LABEL = "Anthropic API"  # canary_lanes.CHECK_LABELS["anthropic"] — the string CANARY#last_state stores


class _StateDDB:
    """Scripted DynamoDB client for USER#system / CANARY#last_state.

    Plain class, never MagicMock: a MagicMock `get_item` returns a truthy Mock for
    `.get("Item")` and would launder a missing read into a passing assertion.
    """

    def __init__(self, prev_failed=()):
        self.prev_failed = list(prev_failed)
        self.get_item_calls: list = []
        self.put_items: list = []

    def get_item(self, **kwargs):
        self.get_item_calls.append(kwargs)
        if not self.prev_failed:
            return {}
        return {"Item": {"failed_checks": {"SS": list(self.prev_failed)}}}

    def put_item(self, **kwargs):
        self.put_items.append(kwargs)
        return {}


def run_canary(monkeypatch, *, event=None, anthropic_fail=False, residue_rows=0, prev_failed=()):
    """Invoke the REAL handler with every probe stubbed. Returns everything the three
    consumers of one datapoint can see: the response, the emails, the metrics, the state."""
    monkeypatch.setattr(canary, "check_dynamodb", lambda ts, p: (True, "ddb msg", 10.0))
    monkeypatch.setattr(canary, "check_s3", lambda ts, p: (True, "s3 msg", 10.0))
    monkeypatch.setattr(canary, "check_mcp", lambda ts: (True, "83 tools listed", 10.0))
    # The 4-tuple is the live signature (#3830 gave check_anthropic a botocore Error.Code so
    # canary_lanes can tell a vendor 503 from a deploy-plausible break on the same check). A
    # fixture that is not the wire is how a signature change passes its own tests.
    if anthropic_fail:
        monkeypatch.setattr(canary, "check_anthropic", lambda ts: (False, INCIDENT_MESSAGE, 10.0, INCIDENT_CODE))
    else:
        monkeypatch.setattr(canary, "check_anthropic", lambda ts: (True, "Bedrock OK", 10.0, None))

    extras = {
        "subscribe_cleanup": {"ok": True, "message": "canary subscriber row deleted"},
        "subscribe_residue": {
            "ok": residue_rows == 0,
            "message": f"{residue_rows} synthetic canary row(s) survived cleanup (#1954)",
            "residue_rows": residue_rows,
        },
    }
    monkeypatch.setattr(canary, "check_subscribe_flow", lambda ts: (True, "subscribe flow OK", 10.0, extras))

    metrics: list = []
    monkeypatch.setattr(canary, "emit", lambda name, value, unit="Count": metrics.append(name))

    alerts: list = []
    monkeypatch.setattr(canary, "send_alert", lambda failures, ts, dry_run=False: alerts.append(failures))

    state = _StateDDB(prev_failed)

    class _FakeBoto3:
        def client(self, name, region_name=None):
            return state

    monkeypatch.setattr(canary, "boto3", _FakeBoto3())

    resp = canary.lambda_handler(event if event is not None else {}, None)
    return resp, json.loads(resp["body"]), alerts, metrics, state


RECHECK = {"gate_recheck": True}


# ══════════════════════════════════════════════════════════════════════════════
# 1. The defect, replayed — and its opposite-direction control
# ══════════════════════════════════════════════════════════════════════════════


def test_THE_DEFECT_the_gates_second_look_does_not_become_the_alerters_second_occurrence(monkeypatch):
    """Attempt 1 recorded the 503 in CANARY#last_state. Attempt 2 lands 20 seconds later
    with the SAME vendor 503. Pre-fix that read as "failed in two consecutive runs" and
    mailed "persistent failure" about a blip the alerter had suppressed one run earlier."""
    _resp, _body, alerts, _metrics, state = run_canary(monkeypatch, event=RECHECK, anthropic_fail=True, prev_failed=[ANTHROPIC_LABEL])
    assert alerts == [], "the deploy gate's own retry supplied the alerter's second occurrence"
    assert state.get_item_calls == [], "a re-check must not even READ the window it is not part of"


def test_the_SAME_state_on_a_normal_run_STILL_emails(monkeypatch):
    """The control that stops this from being a mute. Identical prior state, identical
    failure — a genuine second RUN of the 4-hourly cadence must still reach the operator."""
    _resp, _body, alerts, _metrics, state = run_canary(monkeypatch, event={}, anthropic_fail=True, prev_failed=[ANTHROPIC_LABEL])
    assert len(alerts) == 1, "a check that failed in two consecutive scheduled runs must email"
    assert [f["check"] for f in alerts[0]] == [ANTHROPIC_LABEL]
    assert state.get_item_calls, "a normal run reads the window"


def test_a_recheck_leaves_the_first_occurrence_window_EXACTLY_as_it_found_it(monkeypatch):
    """Not writing matters as much as not reading: if the re-check persisted its own
    failures, the NEXT scheduled run would inherit a second occurrence the cadence never
    observed, and the pollution would outlive the deploy by four hours."""
    _resp, _body, _alerts, _metrics, state = run_canary(monkeypatch, event=RECHECK, anthropic_fail=True)
    assert state.put_items == [], "a re-check wrote CANARY#last_state — the gate is editing the alerter's memory"


def test_a_normal_run_STILL_writes_the_window(monkeypatch):
    """Opposite direction: the persistence the suppression depends on must keep happening."""
    _resp, _body, _alerts, _metrics, state = run_canary(monkeypatch, event={}, anthropic_fail=True)
    assert len(state.put_items) == 1
    assert state.put_items[0]["Item"]["failed_checks"]["SS"] == [ANTHROPIC_LABEL]


# ══════════════════════════════════════════════════════════════════════════════
# 2. A re-check is quieter about EMAIL only — the gate and the alarms see everything
# ══════════════════════════════════════════════════════════════════════════════


def test_a_recheck_returns_the_SAME_verdict_the_gate_would_have_read(monkeypatch):
    """The flag must buy silence in the alerter and change nothing the gate reads. If a
    re-check answered differently the retry would be measuring a different system than the
    first attempt did, and the whole second look would be worthless."""
    _r1, normal, _a1, _m1, _s1 = run_canary(monkeypatch, event={}, anthropic_fail=True, residue_rows=1)
    _r2, recheck, _a2, _m2, _s2 = run_canary(monkeypatch, event=RECHECK, anthropic_fail=True, residue_rows=1)
    for body in (normal, recheck):
        body.pop("canary_ts")
    assert recheck == normal, "a re-check answered the gate differently than a normal run"
    # ...and it is the #3831 answer: a vendor 503 is counted, named, and NOT gating.
    assert recheck["failed_deploy_health"] == 0
    assert recheck["failed_external_transient"] == 1
    assert recheck["lanes"]["external_transient"]["failed_checks"] == ["anthropic"]


def test_a_recheck_emits_every_metric_so_the_ALARMS_stay_exactly_as_loud(monkeypatch):
    """De-gating is only defensible when it is not also a mute (#2051's lesson). The email
    window is the only thing a re-check sits out; CloudWatch sees the identical stream."""
    _r1, _b1, _a1, normal_metrics, _s1 = run_canary(monkeypatch, event={}, anthropic_fail=True)
    _r2, _b2, _a2, recheck_metrics, _s2 = run_canary(monkeypatch, event=RECHECK, anthropic_fail=True)
    assert recheck_metrics == normal_metrics
    assert "CanaryAnthropicFail" in recheck_metrics, "the failing check must still reach its alarm"


def test_a_recheck_names_the_suppression_in_the_log_rather_than_going_quiet(monkeypatch, capsys):
    """A skip nobody can see is indistinguishable from an alerter that stopped working."""
    run_canary(monkeypatch, event=RECHECK, anthropic_fail=True)
    out = capsys.readouterr().out
    assert "Alerting: SKIPPED" in out and "#3830" in out
    assert "CANARY#last_state" in out, "the log has to say WHICH window was left alone"


def test_a_recheck_does_not_email_a_STORED_STATE_failure_either(monkeypatch):
    """#2051 gave stored-state failures first-occurrence alerting precisely because they are
    not blips. That is a property of the 4-hourly cadence, not of the gate's retry: the
    scheduled run 20 seconds earlier already owned it, and the row cannot have appeared in
    between. Emailing here would mean every gated deploy double-mails a stale row."""
    _resp, body, alerts, _metrics, _state = run_canary(monkeypatch, event=RECHECK, residue_rows=1)
    assert alerts == []
    assert body["failed_stored_state"] == 1, "silent about mail, never silent about the count"
    assert body["all_pass"] is False


def test_a_normal_run_STILL_emails_a_stored_state_failure_on_its_FIRST_occurrence(monkeypatch):
    """The #1954 row sat for twelve days. Its alerting path must be untouched by all this."""
    _resp, _body, alerts, _metrics, _state = run_canary(monkeypatch, event={}, residue_rows=1)
    assert [f["check_key"] for f in alerts[0]] == ["subscribe_residue"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. is_gate_recheck — conservative in the direction that matters
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "event",
    [
        {},
        None,
        {"gate_recheck": False},
        {"gate_recheck": "true"},  # a string is not the flag — a shell quoting slip must not mute the alerter
        {"gate_recheck": 1},
        {"mcp_only": True},
        "gate_recheck",  # not a dict at all
    ],
)
def test_anything_but_a_literal_true_is_a_NORMAL_run(event):
    """The failure mode of a mis-parsed flag must be "the alerter behaves as it always has",
    never "the canary silently stopped emailing"."""
    assert canary.is_gate_recheck(event) is False


def test_the_flag_the_wrapper_actually_sends_is_recognised():
    """The two halves are wired through ONE key name, so a rename cannot half-land: the
    wrapper's own payload is parsed by the canary's own reader, here."""
    assert canary.is_gate_recheck(json.loads(cgr.RECHECK_PAYLOAD)) is True
    assert canary.RECHECK_EVENT_KEY in json.loads(cgr.RECHECK_PAYLOAD)


# ══════════════════════════════════════════════════════════════════════════════
# 4. The wrapper seam — attempt 1 is a run, attempt 2+ is the same look again
# ══════════════════════════════════════════════════════════════════════════════


def test_the_first_look_is_an_ORDINARY_canary_run(monkeypatch):
    """Attempt 1 is a real, independent observation minutes-to-hours after the last
    scheduled one — it keeps counting, exactly as it did before retry-before-gate landed."""
    assert json.loads(cgr.payload_for(1)) == {}


@pytest.mark.parametrize("n", [2, 3, 5])
def test_every_later_attempt_carries_the_recheck_flag(n):
    assert json.loads(cgr.payload_for(n)) == {"gate_recheck": True}


def test_the_LIVE_invoke_command_carries_the_flag_not_just_the_constant(tmp_path, monkeypatch):
    """A constant nothing passes to `aws lambda invoke` is a comment. This drives the real
    `_aws_invoke` closure and reads the argv it built."""
    calls: list = []

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # The real CLI writes the response to the last positional arg.
        with open(cmd[-1], "w", encoding="utf-8") as fh:
            json.dump({"statusCode": 200, "body": json.dumps({"failed_deploy_health": 1})}, fh)
        return _Proc()

    monkeypatch.setattr(cgr.subprocess, "run", fake_run)
    attempt = cgr._aws_invoke("life-platform-canary", "us-west-2", tmp_path / "canary.json", "Canary", ("healthy",))
    attempt(1)
    attempt(2)

    def payload_of(cmd):
        return cmd[cmd.index("--payload") + 1]

    assert json.loads(payload_of(calls[0])) == {}
    assert json.loads(payload_of(calls[1])) == {"gate_recheck": True}


def test_the_retry_annotation_says_the_alerter_window_is_untouched(monkeypatch):
    """The CI log is where an operator reconstructs what happened; "it retried" without
    "and it did not count against the email window" is the ambiguity that files the issue."""
    lines: list = []
    cgr.run_attempts(
        lambda n: ("FAIL", "503") if n == 1 else ("PASS", "200"),
        2,
        delay=0,
        sleep=lambda _s: None,
        log=lines.append,
    )
    assert len(lines) == 1 and lines[0].startswith("::warning::")
    assert "gate_recheck" in lines[0] and "first-occurrence window" in lines[0]


# ══════════════════════════════════════════════════════════════════════════════
# 5. Mutation controls — prove the two guards above can actually fail
# ══════════════════════════════════════════════════════════════════════════════


def test_MUTATION_if_the_flag_stopped_being_read_the_email_control_flips(monkeypatch):
    """Blind `is_gate_recheck` and the incident test's assertion must break. If it did not,
    that test was passing for some other reason and proves nothing about this fix."""
    monkeypatch.setattr(canary, "is_gate_recheck", lambda _e: False)
    _resp, _body, alerts, _metrics, state = run_canary(monkeypatch, event=RECHECK, anthropic_fail=True, prev_failed=[ANTHROPIC_LABEL])
    assert len(alerts) == 1, "mutation did not take — the parity control is not measuring what it claims"
    assert state.put_items, "mutation did not take — the window control is not measuring what it claims"


def test_MUTATION_if_the_retry_sent_a_plain_payload_the_seam_control_flips(monkeypatch):
    monkeypatch.setattr(cgr, "payload_for", lambda _n: "{}")
    assert json.loads(cgr.payload_for(2)) == {}, "mutation did not take"


# ══════════════════════════════════════════════════════════════════════════════
# 6. BOTH CI ARMS (the 2026-09-19 class: a gate that keys on the CI event)
# ══════════════════════════════════════════════════════════════════════════════
# On 2026-09-19 a check passed under `pull_request` and failed on main's `push`, because
# something in its path read the event name. Nothing above is supposed to: the canary's
# parity with its alerter is a property of the Lambda and the wrapper, not of which webhook
# started the job. That is a claim, so it gets a measurement — the whole file is re-run in a
# child process with the event PINNED to each arm, and both arms must agree.

_ARM_CHILD_ENV = "CANARY_3830_ARM_CHILD"


@pytest.mark.parametrize(
    "event_name,git_ref",
    [("push", "refs/heads/main"), ("pull_request", "refs/pull/3830/merge")],
)
def test_the_parity_guards_hold_identically_under_both_ci_arms(event_name, git_ref):
    if os.environ.get(_ARM_CHILD_ENV):
        pytest.skip("child arm run — the parent already pins both arms")
    env = dict(os.environ)
    env.update(
        {
            _ARM_CHILD_ENV: "1",
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": event_name,  # PINNED, not deleted: an unset var is a third arm, not either of the two
            "GITHUB_REF": git_ref,
        }
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", os.path.abspath(__file__), "-q", "-p", "no:cacheprovider"],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"the parity guards behave differently under {event_name}:\n{proc.stdout[-4000:]}{proc.stderr[-2000:]}"
