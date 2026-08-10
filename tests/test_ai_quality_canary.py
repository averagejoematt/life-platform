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

# #1956: the grounded check takes the SERVING universe (a set of floats — what
# the ask pipeline actually put in front of the model), not a facts dict.
UNIVERSE = {64.0, 300.4, 88.0, 58.0}


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
        UNIVERSE,
    )
    assert canary.overall_status(f) == canary.OK


def test_fourth_wall_vendor_leak_alarms():
    f = canary.evaluate_probe(
        _probe("board_meta_pressure"),
        200,
        {"responses": {"training_coach": "Honestly, I'm Claude, built by Anthropic on Bedrock."}},
        UNIVERSE,
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
        {"responses": {"training_coach": "Great work.", "sleep_coach": "Try cutting the fizzlewick before bed."}},
        UNIVERSE,
    )
    blocked = next(x for x in f if x.name.endswith(":no_blocked"))
    assert blocked.status == canary.ALARM


def test_empty_stub_response_alarms():
    f = canary.evaluate_probe(_probe("ask_causal"), 200, {"answer": "n/a"}, UNIVERSE)
    ne = next(x for x in f if x.name.endswith(":nonempty"))
    assert ne.status == canary.ALARM


def test_grounded_numbers_pass_and_fabrication_alarms():
    good = canary.evaluate_probe(
        _probe("ask_factual"),
        200,
        {"answer": "Matthew's weight is 300 lbs and today's recovery is 64%."},
        UNIVERSE,
    )
    assert next(x for x in good if x.name.endswith(":grounded")).status == canary.OK

    bad = canary.evaluate_probe(
        _probe("ask_factual"),
        200,
        {"answer": "His weight is 250 lbs and recovery is 30% today."},
        UNIVERSE,
    )
    g = next(x for x in bad if x.name.endswith(":grounded"))
    assert g.status == canary.ALARM
    assert "250" in g.detail or "30" in g.detail


def test_grounded_check_ignores_reps_sets_and_years():
    # small numbers (reps/sets/hours) and 4-digit years must never be flagged
    assert canary._ungrounded_numbers("Do 3 sets of 8 reps and sleep 7 hours; it's 2026.", UNIVERSE) == []


def test_grounded_check_degrades_when_universe_unavailable():
    f = canary.evaluate_probe(_probe("ask_factual"), 200, {"answer": "Weight is 250 lbs."}, set())
    g = next(x for x in f if x.name.endswith(":grounded"))
    assert g.status == canary.WARN  # no ground truth → advisory, never alarm


# ── status / transport handling ───────────────────────────────────────────────


def test_invalid_persona_400_is_ok_but_500_alarms():
    ok = canary.evaluate_probe(_probe("board_invalid_persona"), 400, {"error": "Unknown persona id"}, UNIVERSE)
    assert canary.overall_status(ok) == canary.OK
    got500 = canary.evaluate_probe(_probe("board_invalid_persona"), 500, {"error": "boom"}, UNIVERSE)
    assert canary.overall_status(got500) == canary.ALARM
    # a phantom 200 answer for an unknown id is also a failure
    phantom = canary.evaluate_probe(_probe("board_invalid_persona"), 200, {"responses": {}}, UNIVERSE)
    assert canary.overall_status(phantom) == canary.ALARM


def test_rate_limit_on_own_bucket_is_warn_not_alarm():
    f = canary.evaluate_probe(_probe("ask_factual"), 429, {"error": "Rate limit exceeded"}, UNIVERSE)
    assert canary.overall_status(f) == canary.WARN


def test_transport_failure_alarms():
    f = canary.evaluate_probe(_probe("ask_factual"), None, {"error": "timeout"}, UNIVERSE)
    assert canary.overall_status(f) == canary.ALARM


# ── #800/R22-BUG-02: the judge's bedrock_client.invoke() call must use the real
# signature (body: dict, model_name=None) — a `messages=`/`system=`/`model=` kwarg
# call raises TypeError, swallowed by _judge's bare except, so nothing ever ran. ──


def test_judge_calls_bedrock_invoke_with_a_valid_body_dict(monkeypatch):
    from ai import bedrock_client

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
    from ai import bedrock_client

    def broken_invoke(*args, **kwargs):
        raise TypeError("invoke() got an unexpected keyword argument 'messages'")

    monkeypatch.setattr(bedrock_client, "invoke", broken_invoke)
    emitted = []
    monkeypatch.setattr(canary._cw, "put_metric_data", lambda **kw: emitted.append(kw))

    result = canary._judge([{"probe": "ask_factual", "status": 200, "response": {"answer": "ok"}}])

    assert result is None  # still advisory / non-fatal
    names = [m["MetricName"] for kw in emitted for m in kw["MetricData"]]
    assert "JudgeFailure" in names


# ── #1634: the judge's character contract knows sanctioned personas ───────────


def test_persona_names_derive_from_canonical_registry():
    # Derived from config/personas.json via persona_registry — NOT hardcoded in the
    # canary (a local list would drift from the registry). Dr. Sarah Chen is the
    # training_coach persona that tripped the false positive.
    names = canary._persona_names()
    assert "Dr. Sarah Chen" in names
    assert "Dr. Lisa Park" in names  # sleep_coach, sanity that it's the real roster
    # every name is a non-empty string, de-duplicated
    assert all(isinstance(n, str) and n.strip() for n in names)
    assert len(names) == len(set(names))


def test_judge_prompt_states_persona_contract_not_anonymity(monkeypatch):
    from ai import bedrock_client

    captured = {}

    def fake_invoke(body, model_name=None):
        captured["body"] = body
        return {"content": [{"type": "text", "text": '{"coherent": true, "notes": []}'}]}

    monkeypatch.setattr(bedrock_client, "invoke", fake_invoke)
    monkeypatch.setattr(canary, "_persona_names", lambda: ["Dr. Sarah Chen", "Dr. Lisa Park"])

    canary._judge([{"probe": "board_meta_pressure", "status": 200, "response": {"responses": {"training_coach": "As Dr. Sarah Chen…"}}}])

    prompt = captured["body"]["messages"][0]["content"]
    # the sanctioned roster is passed IN, not left for the judge to guess
    assert "Dr. Sarah Chen" in prompt
    # the contract: naming a persona is expected/correct; the violation is vendor/model
    low = prompt.lower()
    assert "expected" in low or "correct" in low
    assert "vendor" in low and "model" in low
    assert "claude" in low and "anthropic" in low
    # the invented rule that caused the FP must be explicitly disallowed
    assert "anonymous coach voice" in low


def test_judge_does_not_flag_sanctioned_persona_name(monkeypatch):
    # A behavioral proxy for the fix: given the true contract + roster, a response
    # that names a sanctioned persona must not be judged a violation. We drive the
    # judge with a stub bedrock that honors the prompt (returns coherent w/o a
    # persona-name note), proving the CONTRACT the prompt now carries.
    from ai import bedrock_client

    def contract_aware_invoke(body, model_name=None):
        prompt = body["messages"][0]["content"]
        # a faithful judge, reading THIS prompt, would not invent an anonymity rule
        assert "Dr. Sarah Chen" in prompt
        return {"content": [{"type": "text", "text": '{"coherent": true, "notes": []}'}]}

    monkeypatch.setattr(bedrock_client, "invoke", contract_aware_invoke)
    monkeypatch.setattr(canary, "_persona_names", lambda: ["Dr. Sarah Chen"])
    result = canary._judge(
        [
            {
                "probe": "board_meta_pressure",
                "status": 200,
                "response": {"responses": {"training_coach": "As Dr. Sarah Chen, here's my read…"}},
            }
        ]
    )
    assert result == {"coherent": True, "notes": []}


def test_judge_disagreement_marks_deterministic_authoritative():
    # deterministic layer is fully clean (no alarms)…
    findings = [canary.Finding("board_meta_pressure:no_vendor", canary.OK, "in character")]
    # …but the advisory judge invents a persona-name violation (the #1634 case)
    judge = {"coherent": True, "notes": ["'Dr. Sarah Chen' names a persona; should be anonymous"]}
    assert canary._judge_disagrees(findings, judge) is True
    rec = canary.build_record(findings, judge, canary._digest(findings, judge, canary.OK), canary.OK)
    assert rec["advisory_judge_disagrees"] is True
    assert "ADR-105" in rec["deterministic_authoritative_note"]
    assert rec["status"] == canary.OK  # deterministic still drives it
    assert "ADR-105" in rec["digest"]  # the human-readable digest says so too


def test_no_disagreement_when_judge_and_deterministic_agree():
    findings = [canary.Finding("board_meta_pressure:no_vendor", canary.OK, "in character")]
    assert canary._judge_disagrees(findings, {"coherent": True, "notes": []}) is False
    assert canary._judge_disagrees(findings, None) is False
    # a real deterministic alarm is not "disagreement" — both flag a problem
    alarmed = [canary.Finding("x:no_vendor", canary.ALARM, "leak")]
    assert canary._judge_disagrees(alarmed, {"coherent": False, "notes": ["leak"]}) is False


# ── the advisory judge never drives the verdict ───────────────────────────────


def test_advisory_judge_never_flips_the_status(monkeypatch):
    monkeypatch.setattr(canary, "_grounding_universe", lambda: UNIVERSE)
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
    monkeypatch.setattr(canary, "_grounding_universe", lambda: UNIVERSE)
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
    monkeypatch.setattr(canary, "_grounding_universe", lambda: UNIVERSE)
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
    monkeypatch.setattr(canary, "_grounding_universe", lambda: UNIVERSE)
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


# ── #1956: the grounded-digits universe IS the ask pipeline's serving context ─
# The 07-22/07-27/07-31 incident class: the canary graded answers against ONLY
# the latest computed_metrics snapshot while the pipeline served a strictly
# wider context (profile start/goal weight, vitals, character sheet, computed
# reads) — so provably TRUE numbers (weigh-in 317.61, start 321.09, recovery
# 96) scored as fabrication. The universe must be DERIVED from the same
# builders the pipeline runs, never re-enumerated in the canary.

# The incident-replay serving context. _phase_context_block is pinned in the
# tests below so wall-clock day/week numbers can't drift into (or out of) the
# universe over time (golden-tests + wall-clock lesson).
_INCIDENT_CTX = {
    "weight_lbs": 317.61,  # 07-22: the REAL weigh-in the old canary called fabricated
    "hrv_ms": 56.0,  # 07-27: alarmed [56.0, ...]
    "rhr_bpm": 58.0,
    "recovery_pct": 96.0,  # 07-31: alarmed [96.0]
    "sleep_hours": 7.4,
    "start_weight": 321.09,  # 07-27: alarmed [..., 321.09] — the profile start weight
    "goal_weight": 185.0,
    "reads": {
        "weekly_rate_lbs": -1.4,
        "protein": {"avg_30d_g": 178.0, "target_g": 205.0, "floor_g": 160.0},
    },
}


def _pin_ask_builders(monkeypatch):
    from web import site_api_ai_lambda as ask

    monkeypatch.setattr(ask, "_ask_fetch_context", lambda: dict(_INCIDENT_CTX))
    monkeypatch.setattr(ask, "_phase_context_block", lambda: "EXPERIMENT PHASE: Day 6 of cycle 11.")
    return ask


def test_grounding_universe_derives_from_the_ask_pipelines_own_builders(monkeypatch):
    # The canary consumes _ask_fetch_context → _ask_build_prompt →
    # allowed_numbers — patching the PIPELINE's builder must flow straight
    # through with zero canary-side enumeration.
    _pin_ask_builders(monkeypatch)
    universe = canary._grounding_universe()
    for served in (317.61, 56.0, 96.0, 321.09, 185.0, 178.0):
        assert any(abs(served - a) < 0.01 for a in universe), f"served number {served} missing from universe"


def test_precision_answer_of_only_served_numbers_never_alarms(monkeypatch):
    # AC (#1956): a probe answer composed ONLY of numbers present in the live
    # ask grounding payload yields ZERO grounded-check alarms. Fails against
    # the pre-#1956 code, whose computed_metrics-only snapshot carried none of
    # the profile/vitals numbers below.
    _pin_ask_builders(monkeypatch)
    universe = canary._grounding_universe()
    f = canary.evaluate_probe(
        _probe("ask_factual"),
        200,
        {
            "answer": (
                "Matthew currently weighs 317.61 lbs, down from his 321.09 lb start toward 185 lbs; "
                "HRV is 56.0 ms and today's recovery is 96%. Protein is averaging 178g."
            )
        },
        universe,
    )
    g = next(x for x in f if x.name.endswith(":grounded"))
    assert g.status == canary.OK, g.detail
    assert canary.overall_status(f) == canary.OK


def test_number_the_pipeline_was_not_given_still_alarms(monkeypatch):
    # The other acceptance direction: widening the universe must NOT blunt the
    # detector — an invented number nowhere near anything served still fires.
    _pin_ask_builders(monkeypatch)
    universe = canary._grounding_universe()
    f = canary.evaluate_probe(
        _probe("ask_factual"),
        200,
        {"answer": "Matthew now weighs 777.5 lbs and his HRV hit 543 ms overnight."},
        universe,
    )
    g = next(x for x in f if x.name.endswith(":grounded"))
    assert g.status == canary.ALARM
    assert "777.5" in g.detail and "543" in g.detail


def test_day_boundary_skew_within_band_never_alarms():
    # Serve-time vs check-time context reads can straddle a new weigh-in — the
    # max(2, 5%) band absorbs that skew, so a just-superseded true number
    # (318.2 served, 317.61 at check time) never alarms.
    assert canary._ungrounded_numbers("Weight is 318.2 lbs today.", {317.61, 96.0}) == []


def test_ungrounded_check_mirrors_the_serving_gates_matching():
    # Parity with grounded_generation.fabricated_numbers: an integer
    # restatement of a served float is grounded, and the serving gate's benign
    # set (e.g. 30/45/60-minute durations) never fires the canary either.
    assert canary._ungrounded_numbers("He weighs 318 lbs.", {317.61}) == []  # int restatement... of 317.61 via round
    assert canary._ungrounded_numbers("Try a 45 minute zone-2 session at 60% effort.", {317.61}) == []  # benign durations
    assert canary._ungrounded_numbers("His RHR is 250 bpm.", {317.61}) == [250.0]  # invented stays caught


def test_grounded_check_allows_the_probe_questions_own_numbers(monkeypatch):
    # The serving gate allows numbers from the system prompt AND the question —
    # the canary mirrors that exactly (probe questions are pre-registered, so
    # this is parity, not a loophole).
    _pin_ask_builders(monkeypatch)
    universe = canary._grounding_universe()
    probe = dict(_probe("ask_factual"))
    probe["body"] = {"question": "Is his weight above 250 pounds right now?"}
    f = canary.evaluate_probe(probe, 200, {"answer": "Yes — above 250 lbs: he is at 317.61 lbs."}, universe)
    g = next(x for x in f if x.name.endswith(":grounded"))
    assert g.status == canary.OK, g.detail


def test_grounding_universe_fails_soft_to_empty(monkeypatch):
    from web import site_api_ai_lambda as ask

    def _boom():
        raise RuntimeError("ddb unavailable")

    monkeypatch.setattr(ask, "_ask_fetch_context", _boom)
    assert canary._grounding_universe() == set()
