"""
#385 — the AI quality canary over the public endpoints.

Pins the contract that makes the canary an HONEST alarm: deterministic checks
alone drive the verdict (the advisory judge never does), the three review
regressions are caught (fourth-wall vendor leak, ungrounded number, invalid-
persona 500), a rate-limit collision on the canary's own bucket is a WARN not
an ALARM, a budget-paused endpoint is skipped-OK not a defect, and the record
mirrors the gauge.

All offline — monkeypatch the Lambda invoke + facts; never touches AWS/network.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "operational"))

import ai_quality_canary_lambda as canary  # noqa: E402

FACTS = {"recovery_pct": 64.0, "latest_weight": 300.4, "hrv_ms": 88.0, "rhr_bpm": 58.0}


def _probe(pid):
    return next(p for p in canary.PROBES if p["id"] == pid)


# ── status vocab ──────────────────────────────────────────────────────────────


def test_status_ordering():
    assert canary.worse(canary.OK, canary.WARN) == canary.WARN
    assert canary.worse(canary.ALARM, canary.WARN) == canary.ALARM
    assert canary.overall_status([canary.Finding("a", canary.OK), canary.Finding("b", canary.ALARM)]) == canary.ALARM
    assert canary.overall_status([]) == canary.OK


# ── the pre-registered suite covers the three review regressions ──────────────


def test_probe_suite_has_the_three_regressions():
    ids = {p["id"] for p in canary.PROBES}
    assert "board_meta_pressure" in ids  # fourth-wall break (#356)
    assert "board_invalid_persona" in ids  # invalid-persona 500
    assert "ask_factual" in ids  # ungrounded board (grounded-digit check)
    # the invalid-persona probe expects a 400 BEFORE model spend
    assert _probe("board_invalid_persona")["expect_status"] == 400
    # the factual probe is the only one carrying the strict grounded-digit check
    grounded = [p["id"] for p in canary.PROBES if "grounded" in p["checks"]]
    assert grounded == ["ask_factual"]


# ── deterministic checks ──────────────────────────────────────────────────────


def test_clean_in_character_answer_is_ok():
    f = canary.evaluate_probe(
        _probe("board_meta_pressure"),
        200,
        {"responses": {"training_coach": "I'm Coach on this board — an AI reading of your data. Let's talk about your training block."}},
        FACTS,
    )
    assert canary.overall_status(f) == canary.OK


def test_fourth_wall_vendor_leak_alarms():
    f = canary.evaluate_probe(
        _probe("board_meta_pressure"),
        200,
        {"responses": {"training_coach": "Honestly, I'm Claude, built by Anthropic on Bedrock."}},
        FACTS,
    )
    vendor = next(x for x in f if x.name.endswith(":no_vendor"))
    assert vendor.status == canary.ALARM
    assert canary.overall_status(f) == canary.ALARM


def test_bare_ai_acknowledgement_is_not_a_leak():
    # personas MAY say they are an AI reading; only naming the vendor/model breaks it
    assert canary._vendor_hits("I am an AI coach persona reading your data.") == []
    assert canary._vendor_hits("As an AI, here's my take.") == []


def test_blocked_vice_term_alarms():
    f = canary.evaluate_probe(
        _probe("board_grounded"),
        200,
        {"responses": {"training_coach": "Great work.", "sleep_coach": "Try cutting the marijuana before bed."}},
        FACTS,
    )
    blocked = next(x for x in f if x.name.endswith(":no_blocked"))
    assert blocked.status == canary.ALARM


def test_empty_stub_response_alarms():
    f = canary.evaluate_probe(_probe("ask_causal"), 200, {"answer": "n/a"}, FACTS)
    ne = next(x for x in f if x.name.endswith(":nonempty"))
    assert ne.status == canary.ALARM


def test_grounded_numbers_pass_and_fabrication_alarms():
    good = canary.evaluate_probe(
        _probe("ask_factual"),
        200,
        {"answer": "Matthew's weight is 300 lbs and today's recovery is 64%."},
        FACTS,
    )
    assert next(x for x in good if x.name.endswith(":grounded")).status == canary.OK

    bad = canary.evaluate_probe(
        _probe("ask_factual"),
        200,
        {"answer": "His weight is 250 lbs and recovery is 30% today."},
        FACTS,
    )
    g = next(x for x in bad if x.name.endswith(":grounded"))
    assert g.status == canary.ALARM
    assert "250" in g.detail or "30" in g.detail


def test_grounded_check_ignores_reps_sets_and_years():
    # small numbers (reps/sets/hours) and 4-digit years must never be flagged
    assert canary._ungrounded_numbers("Do 3 sets of 8 reps and sleep 7 hours; it's 2026.", FACTS) == []


def test_grounded_check_degrades_when_no_facts():
    f = canary.evaluate_probe(_probe("ask_factual"), 200, {"answer": "Weight is 250 lbs."}, {})
    g = next(x for x in f if x.name.endswith(":grounded"))
    assert g.status == canary.WARN  # no ground truth → advisory, never alarm


# ── status / transport handling ───────────────────────────────────────────────


def test_invalid_persona_400_is_ok_but_500_alarms():
    ok = canary.evaluate_probe(_probe("board_invalid_persona"), 400, {"error": "Unknown persona id"}, FACTS)
    assert canary.overall_status(ok) == canary.OK
    got500 = canary.evaluate_probe(_probe("board_invalid_persona"), 500, {"error": "boom"}, FACTS)
    assert canary.overall_status(got500) == canary.ALARM
    # a phantom 200 answer for an unknown id is also a failure
    phantom = canary.evaluate_probe(_probe("board_invalid_persona"), 200, {"responses": {}}, FACTS)
    assert canary.overall_status(phantom) == canary.ALARM


def test_rate_limit_on_own_bucket_is_warn_not_alarm():
    f = canary.evaluate_probe(_probe("ask_factual"), 429, {"error": "Rate limit exceeded"}, FACTS)
    assert canary.overall_status(f) == canary.WARN


def test_transport_failure_alarms():
    f = canary.evaluate_probe(_probe("ask_factual"), None, {"error": "timeout"}, FACTS)
    assert canary.overall_status(f) == canary.ALARM


# ── #800/R22-BUG-02: the judge's bedrock_client.invoke() call must use the real
# signature (body: dict, model_name=None) — a `messages=`/`system=`/`model=` kwarg
# call raises TypeError, swallowed by _judge's bare except, so nothing ever ran. ──


def test_judge_calls_bedrock_invoke_with_a_valid_body_dict(monkeypatch):
    import bedrock_client

    captured = {}

    def fake_invoke(body, model_name=None):
        captured["body"] = body
        captured["model_name"] = model_name
        return {"content": [{"type": "text", "text": '{"coherent": true, "notes": []}'}]}

    monkeypatch.setattr(bedrock_client, "invoke", fake_invoke)
    result = canary._judge([{"probe": "ask_factual", "status": 200, "response": {"answer": "ok"}}])

    assert result == {"coherent": True, "notes": []}
    body = captured["body"]
    assert isinstance(body, dict)
    # the real contract: {messages, max_tokens, system?} — no top-level kwargs
    assert isinstance(body.get("messages"), list) and body["messages"]
    assert body["messages"][0]["role"] == "user"
    assert isinstance(body["messages"][0]["content"], str) and body["messages"][0]["content"]
    assert body.get("max_tokens") == 400
    assert isinstance(body.get("system"), str) and body["system"]


def test_judge_failure_is_observable_via_metric(monkeypatch):
    import bedrock_client

    def broken_invoke(*args, **kwargs):
        raise TypeError("invoke() got an unexpected keyword argument 'messages'")

    monkeypatch.setattr(bedrock_client, "invoke", broken_invoke)
    emitted = []
    monkeypatch.setattr(canary._cw, "put_metric_data", lambda **kw: emitted.append(kw))

    result = canary._judge([{"probe": "ask_factual", "status": 200, "response": {"answer": "ok"}}])

    assert result is None  # still advisory / non-fatal
    names = [m["MetricName"] for kw in emitted for m in kw["MetricData"]]
    assert "JudgeFailure" in names


# ── the advisory judge never drives the verdict ───────────────────────────────


def test_advisory_judge_never_flips_the_status(monkeypatch):
    monkeypatch.setattr(canary, "_canonical_facts", lambda: FACTS)
    monkeypatch.setattr(
        canary,
        "_invoke",
        lambda endpoint, body: (
            (400, {"error": "Unknown persona id"})
            if body.get("personas") == ["definitely_not_a_real_coach"]
            else (
                200,
                {
                    "answer": "Matthew's body weight is 300 lbs and today's recovery reads 64%, both steady this week.",
                    "responses": {
                        "training_coach": "Solid week overall — keep the training volume steady and don't chase intensity.",
                        "sleep_coach": "Protect your sleep window; consistency is doing more for you than any single night.",
                    },
                },
            )
        ),
    )
    # judge screams incoherent — must NOT change the deterministic OK verdict
    monkeypatch.setattr(canary, "_judge", lambda transcript: {"coherent": False, "notes": ["I disagree with everything"]})
    findings, transcript, judge = canary.run_probes()
    assert canary.overall_status(findings) == canary.OK
    rec = canary.build_record(findings, judge, "d", canary.overall_status(findings))
    assert rec["status"] == canary.OK  # mirrors the deterministic gauge
    assert rec["advisory_judge"]["coherent"] is False  # kept, but advisory


# ── handler: budget-paused skip + full green, both serializable ───────────────


def test_handler_skips_when_budget_paused(monkeypatch):
    monkeypatch.setattr(canary, "_budget_paused", lambda: True)
    emitted = {}
    monkeypatch.setattr(canary, "_emit_overall", lambda worst: emitted.setdefault("worst", worst))
    monkeypatch.setattr(canary, "_persist", lambda record: None)
    called = {"invoked": False}
    monkeypatch.setattr(canary, "run_probes", lambda: called.__setitem__("invoked", True))
    out = canary.lambda_handler({}, None)
    body = json.loads(out["body"])
    assert out["statusCode"] == 200
    assert body["skipped"] == "budget-paused"
    assert body["status"] == "budget-paused"  # informative record field...
    assert emitted["worst"] == canary.OK  # ...but the gauge the alarm watches is OK
    assert called["invoked"] is False  # never spent a live probe


def test_handler_full_green_emits_ok(monkeypatch):
    monkeypatch.setattr(canary, "_budget_paused", lambda: False)
    monkeypatch.setattr(canary, "_canonical_facts", lambda: FACTS)
    monkeypatch.setattr(canary, "_judge", lambda transcript: None)

    def fake_invoke(endpoint, body):
        if body.get("personas") == ["definitely_not_a_real_coach"]:
            return 400, {"error": "Unknown persona id"}
        if endpoint == "/api/board_ask":
            return 200, {"responses": {p: "A clear, in-character, grounded answer for the week ahead." for p in body["personas"]}}
        return 200, {"answer": "Matthew's weight is 300 lbs and today's recovery is 64%."}

    monkeypatch.setattr(canary, "_invoke", fake_invoke)
    gauges = []
    monkeypatch.setattr(canary._cw, "put_metric_data", lambda **kw: gauges.append(kw))
    puts = []
    monkeypatch.setattr(canary._s3, "put_object", lambda **kw: puts.append(kw["Key"]))

    out = canary.lambda_handler({}, None)
    body = json.loads(out["body"])
    assert body["status"] == canary.OK
    assert body["alarms"] == []
    # OverallAlarm gauge went out as 0.0
    overall = [g for g in gauges for m in g["MetricData"] if m["MetricName"] == "OverallAlarm"]
    assert overall and overall[0]["MetricData"][0]["Value"] == 0.0
    # persisted both latest + dated
    assert any(k.endswith("latest.json") for k in puts)
    # fully serializable
    json.loads(json.dumps(body, default=str))


def test_canary_uses_reserved_non_reader_source_ip():
    # TEST-NET-3 (203.0.113.0/24) is reserved/non-routable — its own rate bucket,
    # so a canary run can never spend a real reader's ask/board_ask quota.
    assert canary.CANARY_IP.startswith("203.0.113.")


# ── #1589: origin header on the synthetic event + transport-blind self-test ───


class _FakePayload:
    def __init__(self, out):
        self._raw = json.dumps(out).encode()

    def read(self):
        return self._raw


def _capture_lambda_invoke(monkeypatch, sent):
    def fake_invoke(FunctionName, InvocationType, Payload):
        sent["event"] = json.loads(Payload.decode())
        return {"Payload": _FakePayload({"statusCode": 200, "body": json.dumps({"answer": "ok"})})}

    monkeypatch.setattr(canary._lambda, "invoke", fake_invoke)


def test_invoke_presents_the_origin_header(monkeypatch):
    monkeypatch.setattr(canary, "_origin_secret", lambda: "shh-origin-value")
    sent = {}
    _capture_lambda_invoke(monkeypatch, sent)
    status, _ = canary._invoke("/api/ask", {"question": "hi"})
    assert status == 200
    assert sent["event"]["headers"]["x-amj-origin"] == "shh-origin-value"
    assert sent["event"]["requestContext"]["http"]["sourceIp"] == canary.CANARY_IP  # rate-bucket identity kept


def test_invoke_goes_headerless_when_secret_unreadable(monkeypatch):
    # Fail-open on the CANARY side: an unreadable secret must not crash the run —
    # the 403s it earns are then classified BLIND, which is the loud path.
    monkeypatch.setattr(canary, "_origin_secret", lambda: "")
    sent = {}
    _capture_lambda_invoke(monkeypatch, sent)
    canary._invoke("/api/ask", {"question": "hi"})
    assert "x-amj-origin" not in sent["event"]["headers"]


def test_blind_requires_every_probe_transport_rejected():
    all_403 = [{"probe": p["id"], "status": 403, "response": {}} for p in canary.PROBES]
    assert canary._blind(all_403) is True
    assert canary._blind([{"probe": "a", "status": None, "response": {}}]) is True  # invoke failures count
    reachable = list(all_403)
    reachable[0] = {"probe": "board_invalid_persona", "status": 400, "response": {}}
    assert canary._blind(reachable) is False  # one reachable endpoint (even an expected 400) = not blind
    assert canary._blind([]) is False


def test_handler_blind_run_alarms_and_names_the_transport(monkeypatch):
    monkeypatch.setattr(canary, "_budget_paused", lambda: False)
    monkeypatch.setattr(canary, "_canonical_facts", lambda: FACTS)
    monkeypatch.setattr(canary, "_judge", lambda transcript: None)
    monkeypatch.setattr(canary, "_invoke", lambda endpoint, body: (403, {"error": "Forbidden"}))
    gauges = []
    monkeypatch.setattr(canary._cw, "put_metric_data", lambda **kw: gauges.append(kw))
    monkeypatch.setattr(canary._s3, "put_object", lambda **kw: None)

    out = canary.lambda_handler({}, None)
    body = json.loads(out["body"])
    assert body["status"] == "BLIND"
    assert body["blind"] is True
    assert "canary_transport" in body["alarms"]
    assert "NOT an AI-quality verdict" in body["digest"]
    flat = [m for g in gauges for m in g["MetricData"]]
    assert any(m["MetricName"] == "Blind" and m["Value"] == 1.0 for m in flat)
    assert any(m["MetricName"] == "OverallAlarm" and m["Value"] == 1.0 for m in flat)


def test_handler_healthy_run_emits_blind_zero(monkeypatch):
    monkeypatch.setattr(canary, "_budget_paused", lambda: False)
    monkeypatch.setattr(canary, "_canonical_facts", lambda: FACTS)
    monkeypatch.setattr(canary, "_judge", lambda transcript: None)

    def fake_invoke(endpoint, body):
        if body.get("personas") == ["definitely_not_a_real_coach"]:
            return 400, {"error": "Unknown persona id"}
        if endpoint == "/api/board_ask":
            return 200, {"responses": {p: "A clear, in-character, grounded answer for the week ahead." for p in body["personas"]}}
        return 200, {"answer": "Matthew's weight is 300 lbs and today's recovery is 64%."}

    monkeypatch.setattr(canary, "_invoke", fake_invoke)
    gauges = []
    monkeypatch.setattr(canary._cw, "put_metric_data", lambda **kw: gauges.append(kw))
    monkeypatch.setattr(canary._s3, "put_object", lambda **kw: None)

    out = canary.lambda_handler({}, None)
    body = json.loads(out["body"])
    assert body["blind"] is False
    flat = [m for g in gauges for m in g["MetricData"]]
    assert any(m["MetricName"] == "Blind" and m["Value"] == 0.0 for m in flat)
