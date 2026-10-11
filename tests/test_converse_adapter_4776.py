"""#4776 — the Converse adapter inside `bedrock_client.invoke()` (ADR-062's one chokepoint).

Nothing here reaches AWS: the bedrock-runtime client is a fake whose `converse()` returns a
canned Converse reply and whose `invoke_model()` is the Anthropic path; CloudWatch is a fake.
What is pinned:

  * each non-Anthropic family (gpt-oss, Qwen, Nova) is detected from a name, a profile id or an
    ARN, and every Claude / Titan id is NOT — so the Anthropic path is byte-for-byte what it was;
  * the Messages body is translated faithfully (system + user text, max_tokens/temperature/
    top_p/stop_sequences, a json_schema output_config as an instruction), the untranslatable
    (image, tool_use, tools, a non-schema output_config) REFUSES before any send;
  * the reply is translated back into the Messages shape every caller already parses (content
    blocks, usage keys, stop_reason vocabulary), and `first_text` / `estimate_cost_usd` read it;
  * every guard and meter of `invoke()` stays in the path for a Converse call: the tier-3 budget
    stop fires BEFORE `converse`, the dev-session cap is checked and charged, usage metrics are
    emitted on the family's own price row (never the Fable default), truncation is metered;
  * a refusal is NEVER retried — counted through each of the three retry loops (`invoke_with_retry`,
    both `common/retry_utils` wrappers, `ai_transport.call_anthropic`): one attempt, no sleep, no
    send; the verifier's reproduction had the one loop retrying it 3x with ~20 s of backoff;
  * the four candidates are mapped, priced on their own rows, IAM names EXACTLY those ARNs, and
    `resolve_model_id` passes through ONLY those ids — an unmapped sibling or a bare profile-only
    id is an UnknownModelError, never a quiet pass-through metered at the Fable default;
  * the swap-eval harness drives all three internal features through the adapter end to end
    with the stub transport — twelve feature x candidate runs — and its deterministic gate still
    bites through the adapter.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "lambdas"), os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import visual_ai_qa  # noqa: E402

# The refusal tests need an image content block as INPUT. It comes from the repo's ONE
# image-block implementation (`visual_ai_qa._png_block`, #3079) rather than a literal here:
# that census allows no second construction site, and the shared helper's output is the
# exact wire shape a real caller would hand the adapter (media_type included). The adapter
# itself builds no image block — it refuses one before any send.
_IMAGE_BLOCK = visual_ai_qa._png_block(b"\x89PNG\r\n\x1a\n")

from ai import (  # noqa: E402
    bedrock_client as bc,
    budget_guard,  # imported here, BEFORE any test patches it, so dev_session_cap binds the real BudgetExceeded
    dev_session_cap,
)

CANDIDATES = {
    "gpt-oss-120b": ("openai.gpt-oss-120b-1:0", "gpt-oss", "gpt-oss-120b"),
    "gpt-oss-20b": ("openai.gpt-oss-20b-1:0", "gpt-oss", "gpt-oss-20b"),
    "qwen3-32b": ("qwen.qwen3-32b-v1:0", "qwen", "qwen3-32b"),
    "nova-micro": ("us.amazon.nova-micro-v1:0", "nova", "nova-micro"),
}
HAIKU_55 = "claude-haiku-5-5"


def _converse_reply(text, in_tok=120, out_tok=40, stop="end_turn", extra_blocks=None, **usage_extra):
    usage = {"inputTokens": in_tok, "outputTokens": out_tok, "totalTokens": in_tok + out_tok, **usage_extra}
    content = list(extra_blocks or []) + [{"text": text}]
    return {
        "ResponseMetadata": {"RequestId": "req-4776"},
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": usage,
        "metrics": {"latencyMs": 5},
    }


def _messages_reply(text, in_tok=120, out_tok=40):
    body = {
        "id": "msg-4776",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
    }
    return {"body": MagicMock(read=lambda: json.dumps(body).encode())}


class _FakeBedrock:
    """A bedrock-runtime stand-in: records every call, answers from the reply factories."""

    def __init__(self, converse_text="ok", messages_text="ok"):
        self.converse_calls = []
        self.invoke_calls = []
        self.converse_text = converse_text
        self.messages_text = messages_text
        self.converse_reply = None  # a full reply overrides converse_text

    def converse(self, **kwargs):
        self.converse_calls.append(kwargs)
        text = self.converse_text(kwargs) if callable(self.converse_text) else self.converse_text
        return dict(self.converse_reply) if self.converse_reply else _converse_reply(text)

    def invoke_model(self, **kwargs):
        self.invoke_calls.append(kwargs)
        text = self.messages_text(kwargs) if callable(self.messages_text) else self.messages_text
        return _messages_reply(text)


class _FakeCloudWatch:
    def __init__(self):
        self.metric_data = []

    def put_metric_data(self, Namespace, MetricData):
        self.metric_data.append((Namespace, MetricData))

    def get_metric_statistics(self, **kwargs):
        return {"Datapoints": []}


@pytest.fixture
def wired(monkeypatch):
    """invoke() with a fake Bedrock, a fake CloudWatch, budget tier 0, and a fresh dev-session
    cap on a WORKSTATION (no Lambda / CI markers) — so the cap applies and can be asserted on."""
    tier = {"n": 0}
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier["n"])  # invoke() imports it at call time
    for var in ("AWS_LAMBDA_FUNCTION_NAME", "GITHUB_ACTIONS", "CI", "INVOCATION_CONTEXT", "DEV_AI_BUDGET_USD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DEV_AI_CAP_UNDER_TEST", "1")  # the cap stands down under pytest unless told otherwise
    fake = _FakeBedrock()
    cw = _FakeCloudWatch()
    monkeypatch.setattr(bc, "_client", lambda: fake)
    monkeypatch.setattr(bc, "_cw", lambda: cw)
    dev_session_cap._reset_for_tests()
    yield fake, cw, tier
    dev_session_cap._reset_for_tests()


# ── family detection + the map / price rows ──────────────────────────────────────────────


def test_converse_family_is_detected_for_names_profiles_and_arns_and_never_for_claude_or_titan():
    for name, (model_id, family, _row) in CANDIDATES.items():
        assert bc.resolve_model_id(name) == model_id
        assert bc.converse_family(model_id) == family, model_id
        assert bc.converse_family(f"arn:aws:bedrock:us-west-2::foundation-model/{model_id.removeprefix('us.')}") == family
        assert bc.resolve_model_id(model_id) == model_id, "a Converse-family id passes through like a us. id"
    assert bc.converse_family("us.amazon.nova-micro-v1:0") == "nova"
    assert bc.converse_family("arn:aws:bedrock:*:1:inference-profile/us.amazon.nova-micro-v1:0") == "nova"
    for anthropic in list(bc._MODEL_MAP.values()) + ["amazon.titan-embed-text-v2:0", "global.anthropic.claude-sonnet-5", None, ""]:
        if anthropic in {m for m, _f, _r in CANDIDATES.values()}:
            continue
        assert bc.converse_family(anthropic) is None, anthropic
    with pytest.raises(bc.UnknownModelError):
        bc.resolve_model_id("gpt-oss-240b")
    # #4275's refuse-to-guess rule holds for a bare Converse-family id too: ONLY the mapped ids pass
    # through. The family prefix alone let `openai.gpt-oss-safeguard-20b` (unmapped, unpriced — it
    # would meter at the Fable default) and a bare `amazon.nova-micro-v1:0` (profile-only) through.
    for unmapped in ("openai.gpt-oss-safeguard-20b", "openai.gpt-oss-safeguard-120b-1:0", "amazon.nova-micro-v1:0", "qwen.qwen3-235b-v1:0"):
        with pytest.raises(bc.UnknownModelError, match="refusing to guess"):
            bc.resolve_model_id(unmapped)
    assert bc.resolve_model_id("us.amazon.nova-micro-v1:0") == "us.amazon.nova-micro-v1:0", "the profile id is the mapped one"
    assert bc._CONVERSE_MAPPED_IDS == {m for m, _f, _r in CANDIDATES.values()}


def test_the_four_candidates_price_on_their_own_rows_with_no_cache_leg():
    """An unpriced model meters at the Fable default — the issue's defect (c)."""
    from operational import cost_governor_lambda as cg

    for name, (model_id, _family, row) in CANDIDATES.items():
        assert bc.price_key_for(model_id) == row, name
        assert bc._price_for(model_id) is cg._price_for(model_id) is bc.PRICES[row]
        p = bc.PRICES[row]
        assert p["in"] > 0 and p["out"] > 0, row
        assert p["cache_read"] == p["cache_write"] == p["cache_write_1h"] == 0, f"{row}: the adapter translates no cachePoint"
        assert row in bc.PRICE_PROVENANCE and "UNVERIFIED" in bc.PRICE_PROVENANCE[row]["note"], row
    # the arithmetic of the kill criterion's price arm, from the rows themselves
    h = bc.PRICES["haiku-5-5"]
    eps = 1e-9  # gpt-oss-20b's $0.07 input sits EXACTLY on the 30% bar; 0.7 * 0.10 is 0.0699… in floating point
    cheaper = {
        row
        for _m, _f, row in CANDIDATES.values()
        if bc.PRICES[row]["in"] <= 0.7 * h["in"] + eps and bc.PRICES[row]["out"] <= 0.7 * h["out"] + eps
    }
    assert cheaper == {"gpt-oss-20b", "nova-micro"}, "gpt-oss-120b and qwen3-32b are dearer than Haiku 5.5: a non-price benefit is required"
    # the safeguard models exist on Bedrock but carry no price here, so they are NOT mapped
    assert not [k for k in bc._MODEL_MAP if "safeguard" in k]
    assert bc.price_key_for("openai.gpt-oss-safeguard-20b") is None  # would meter at the Fable default — conservative


def test_iam_names_exactly_the_mapped_converse_models_in_both_directions():
    """`role_policies_base._bedrock_statement` grants the four candidates and nothing else beyond
    the Claude pair + Titan. Derived from the chokepoint's map, so adding or dropping a candidate
    on one side without the other reds."""
    import test_role_family_write_scope as family

    if family.CDK_DIR not in sys.path:
        sys.path.insert(0, family.CDK_DIR)
    from stacks.constants import ACCT, REGION

    stmt = family.RP._bedrock_statement()
    assert "bedrock:InvokeModel" in stmt.actions
    resources = set(stmt.resources)
    baseline = {r for r in resources if "anthropic.claude" in r or "titan-embed" in r}
    assert len(baseline) == 3, baseline
    expected = set()
    for model_id in {m for m, _f, _r in CANDIDATES.values()}:
        if model_id.startswith("us."):
            bare = model_id[len("us.") :]
            expected.add(f"arn:aws:bedrock:*:{ACCT}:inference-profile/{model_id}")
            expected.add(f"arn:aws:bedrock:*::foundation-model/{bare}")
        else:
            expected.add(f"arn:aws:bedrock:{REGION}::foundation-model/{model_id}")
    assert resources - baseline == expected
    mapped_converse = {v for v in bc._MODEL_MAP.values() if bc.converse_family(v)}
    assert mapped_converse == {m for m, _f, _r in CANDIDATES.values()}


# ── the translation, both directions, pure ───────────────────────────────────────────────


def test_to_converse_request_translates_the_messages_body_and_records_what_it_dropped():
    body = {
        "system": [{"type": "text", "text": "You judge.", "cache_control": {"type": "ephemeral"}}],
        "messages": [
            {"role": "user", "content": "Evaluate this."},
            {"role": "assistant", "content": [{"type": "text", "text": "{"}]},
        ],
        "max_tokens": 300,
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": 5,
        "stop_sequences": ["END"],
        "thinking": {"type": "disabled"},
        "output_config": bc.structured_output_config({"type": "object", "properties": {"ok": {"type": "boolean"}}}),
    }
    req, note = bc.to_converse_request(body, "openai.gpt-oss-120b-1:0")
    assert req["modelId"] == "openai.gpt-oss-120b-1:0"
    assert req["messages"] == [
        {"role": "user", "content": [{"text": "Evaluate this."}]},
        {"role": "assistant", "content": [{"text": "{"}]},
    ]
    assert req["system"][0] == {"text": "You judge."}
    assert req["system"][1]["text"].startswith(bc.CONVERSE_SCHEMA_INSTRUCTION)
    assert json.loads(req["system"][1]["text"][len(bc.CONVERSE_SCHEMA_INSTRUCTION) :]) == {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
    }
    assert req["inferenceConfig"] == {"maxTokens": 300, "temperature": 0.1, "topP": 0.9, "stopSequences": ["END"]}
    assert note == {"family": "gpt-oss", "schema_via": "instruction", "dropped": ["cache_control", "thinking", "top_k"]}
    assert set(req) == {"modelId", "messages", "system", "inferenceConfig"}, "nothing Anthropic-specific leaks onto the wire"
    assert "anthropic_version" not in json.dumps(req)
    # a bare body: no system, no inferenceConfig keys it was not given
    req2, note2 = bc.to_converse_request({"messages": [{"role": "user", "content": "hi"}]}, "qwen.qwen3-32b-v1:0")
    assert set(req2) == {"modelId", "messages"} and note2 == {"family": "qwen", "schema_via": None, "dropped": []}


def test_the_untranslatable_refuses_before_any_send(monkeypatch):
    """One test over every refusal (one gate, not one per case)."""
    monkeypatch.setattr(bc, "_client", lambda: (_ for _ in ()).throw(AssertionError("a refused body reached the client")))
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    user = {"role": "user", "content": "x"}
    refused = [
        ({"messages": [{"role": "user", "content": [_IMAGE_BLOCK]}]}, "image"),
        ({"messages": [{"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "f", "input": {}}]}]}, "tool_use"),
        ({"messages": [user], "tools": [{"name": "f"}]}, "tools"),
        ({"messages": [user], "stream": True}, "stream"),
        ({"messages": [user], "output_config": {"format": {"type": "text"}}}, "output_config"),
        ({"messages": [{"role": "system", "content": "x"}]}, "role"),
    ]
    missed = []
    for body, needle in refused:
        try:
            bc.invoke(dict(body), model_name="gpt-oss-20b")
        except bc.ConverseUnsupported as e:
            if needle not in str(e):
                missed.append((needle, str(e)))
        else:
            missed.append((needle, "no refusal"))
    assert missed == []
    with pytest.raises(bc.ConverseUnsupported, match="not a Converse-family"):
        bc.to_converse_request({"messages": [user]}, "us.anthropic.claude-haiku-5-5")


def test_a_refusal_is_never_retried_by_any_of_the_three_loops(wired, monkeypatch):
    """Counted, not inferred from the class hierarchy. The first cut asserted only
    `issubclass(ConverseUnsupported, ValueError)`; the one loop's `refusals` tuple did not name
    the class, so a refused body fell into `except Exception` and was retried 3x with ~20 s of
    jittered sleep (the verifier measured attempts=3, sleeps=[3.93, 11.41]). Mutation proof: drop
    `ConverseUnsupported` from `invoke_with_retry`'s `refusals` and the first block reds."""
    from ai import ai_transport as at
    from common import retry_utils as ru

    fake, _cw, _tier = wired
    sleeps = []
    monkeypatch.setattr(bc.time, "sleep", lambda s: sleeps.append(s))
    attempts = {"n": 0}
    real_invoke = bc.invoke

    def counting_invoke(body, model_name=None):
        attempts["n"] += 1
        return real_invoke(body, model_name=model_name)

    monkeypatch.setattr(bc, "invoke", counting_invoke)  # invoke_with_retry looks `invoke` up at call time
    user = {"role": "user", "content": "x"}

    # 1. the one loop
    with pytest.raises(bc.ConverseUnsupported, match="tools"):
        bc.invoke_with_retry({"messages": [user], "max_tokens": 5, "tools": [{"name": "f"}]}, model_name="gpt-oss-20b")
    assert (attempts["n"], sleeps) == (1, []), "a refusal entered the backoff ladder"

    # 2. both retry_utils wrappers re-raise it at once, metric fired
    fired = []
    monkeypatch.setattr(ru, "_emit_failure_metric", lambda: fired.append("ru"))
    attempts["n"] = 0
    with pytest.raises(bc.ConverseUnsupported, match="stream"):
        ru.call_anthropic_raw({"model": "qwen3-32b", "max_tokens": 5, "messages": [user], "stream": True})
    assert (attempts["n"], sleeps, fired) == (1, [], ["ru"])
    attempts["n"] = 0
    with pytest.raises(bc.ConverseUnsupported, match="image"):
        ru.call_anthropic_api("hi", model="gpt-oss-120b", system=[_IMAGE_BLOCK])
    assert (attempts["n"], sleeps, fired) == (1, [], ["ru", "ru"])

    # 3. the brief's wrapper: the outage sentinel in one attempt, failure metric fired
    monkeypatch.setattr(at, "_emit_failure_metric", lambda *a, **k: fired.append("at"))
    attempts["n"] = 0
    out = at.call_anthropic("hi", model="nova-micro", system=[_IMAGE_BLOCK])
    assert out == at.AI_UNAVAILABLE_SENTINEL
    assert (attempts["n"], sleeps, fired[-1]) == (1, [], "at")
    assert fake.converse_calls == [] and fake.invoke_calls == [], "nothing was sent, nothing billed"


def test_from_converse_response_is_the_messages_shape_every_caller_parses():
    reply = _converse_reply(
        '{"coherent": true, "issues": []}',
        in_tok=1000,
        out_tok=50,
        stop="max_tokens",
        extra_blocks=[{"reasoningContent": {"reasoningText": {"text": "thinking..."}}}],
        cacheReadInputTokens=200,
        cacheWriteInputTokens=300,
    )
    out = bc.from_converse_response(reply, "openai.gpt-oss-120b-1:0", {"family": "gpt-oss", "schema_via": None, "dropped": []})
    assert out["content"] == [{"type": "text", "text": '{"coherent": true, "issues": []}'}], "reasoning blocks are not text"
    assert bc.first_text(out) == '{"coherent": true, "issues": []}'
    assert out["usage"] == {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 200, "cache_creation_input_tokens": 300}
    assert out["stop_reason"] == "max_tokens" and out["role"] == "assistant" and out["type"] == "message"
    assert out["model"] == "openai.gpt-oss-120b-1:0" and out["id"] == "req-4776" and out["_converse"]["family"] == "gpt-oss"
    assert bc.estimate_cost_usd(out["usage"], "openai.gpt-oss-120b-1:0") == pytest.approx((1000 * 0.15 + 50 * 0.60) / 1e6)
    # an unknown stop reason passes through visibly; an empty reply is an empty content list, not a crash
    assert (
        bc.from_converse_response(_converse_reply("x", stop="guardrail_intervened"), "qwen.qwen3-32b-v1:0")["stop_reason"]
        == "guardrail_intervened"
    )
    empty = bc.from_converse_response({"output": {"message": {"content": []}}, "usage": {}}, "qwen.qwen3-32b-v1:0")
    assert empty["content"] == [] and bc.first_text(empty) is None and empty["usage"] == {"input_tokens": 0, "output_tokens": 0}


# ── invoke(): each family through converse, every guard and meter still in the path ─────


def _cost_points(cw):
    return [m["Value"] for _ns, md in cw.metric_data for m in md if m["MetricName"] == "EstimatedCostUSD" and not m.get("Dimensions")]


def test_invoke_routes_every_family_through_converse_with_every_guard_and_meter_in_the_path(wired):
    fake, cw, _tier = wired
    body = {
        "system": [{"type": "text", "text": "judge", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "x"}],
        "max_tokens": 40,
        "temperature": 0.1,
    }
    spent_before = dev_session_cap._run_spent
    for name, (model_id, family, row) in CANDIDATES.items():
        n_conv, n_inv, n_cost = len(fake.converse_calls), len(fake.invoke_calls), len(_cost_points(cw))
        out = bc.invoke(dict(body), model_name=name)
        assert len(fake.converse_calls) == n_conv + 1 and len(fake.invoke_calls) == n_inv, name
        assert fake.converse_calls[-1]["modelId"] == model_id and "anthropic_version" not in json.dumps(fake.converse_calls[-1])
        assert out["_converse"]["family"] == family and bc.first_text(out) == "ok"
        # metered on the family's own row, not the Fable default, and charged to the dev-session cap
        expected = bc.estimate_cost_usd(out["usage"], model_id)
        assert expected == pytest.approx((120 * bc.PRICES[row]["in"] + 40 * bc.PRICES[row]["out"]) / 1e6)
        assert _cost_points(cw)[n_cost:] == [pytest.approx(expected)], name
        assert dev_session_cap._run_spent == pytest.approx(spent_before + expected), name
        spent_before = dev_session_cap._run_spent
        # asked for caching, got none: the no-op meter fires honestly on this path
        assert any(m["MetricName"] == "PromptCacheNoOp" for _ns, md in cw.metric_data[-2:] for m in md), name
    # the Anthropic path is untouched: a Claude name still goes through invoke_model with the version string
    n_conv = len(fake.converse_calls)
    out = bc.invoke(dict(body), model_name=HAIKU_55)
    assert len(fake.converse_calls) == n_conv and fake.invoke_calls[-1]["modelId"] == "us.anthropic.claude-haiku-5-5"
    assert json.loads(fake.invoke_calls[-1]["body"])["anthropic_version"] == "bedrock-2023-05-31" and "_converse" not in out


def test_the_tier_3_budget_stop_and_the_dev_cap_refuse_a_converse_call_before_any_send(wired, monkeypatch):
    fake, _cw, tier = wired
    body = {"messages": [{"role": "user", "content": "x"}], "max_tokens": 5}
    tier["n"] = 3
    with pytest.raises(budget_guard.BudgetExceeded):
        bc.invoke(dict(body), model_name="nova-micro")
    tier["n"] = 0
    dev_session_cap.record("dev-session", dev_session_cap.PER_RUN_USD + 1.0)  # this run is already over its cap
    with pytest.raises(dev_session_cap.DevSessionBudgetExceeded):
        bc.invoke(dict(body), model_name="nova-micro")
    assert fake.converse_calls == [] and fake.invoke_calls == []


def test_a_truncated_converse_reply_is_metered_and_a_throttle_is_retried_by_the_one_policy(wired, monkeypatch):
    import botocore.exceptions as bce

    fake, cw, _tier = wired
    fake.converse_reply = _converse_reply("partial", stop="max_tokens")
    out = bc.invoke({"messages": [{"role": "user", "content": "x"}], "max_tokens": 40}, model_name="gpt-oss-20b")
    assert out["stop_reason"] == "max_tokens"
    assert any(m["MetricName"] == "TruncatedResponses" for _ns, md in cw.metric_data for m in md)
    # the retry policy sees a Converse ClientError exactly as an InvokeModel one
    attempts = {"n": 0}

    def throttled(**kwargs):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise bce.ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse")
        return _converse_reply("after retry")

    fake.converse_reply = None
    monkeypatch.setattr(fake, "converse", throttled)
    monkeypatch.setattr(bc.time, "sleep", lambda s: None)
    out = bc.invoke_with_retry({"messages": [{"role": "user", "content": "x"}], "max_tokens": 40}, model_name="gpt-oss-20b")
    assert bc.first_text(out) == "after retry" and attempts["n"] == 2


# ── the swap-eval harness through the adapter, stub transport, all three internal features ─


def _structured_text(kwargs):
    """A schema-valid reply for whatever schema the request carries (Converse: the trailing
    system instruction; InvokeModel: output_config in the body)."""
    import model_swap_eval as mse

    if "body" in kwargs:
        schema = ((json.loads(kwargs["body"]).get("output_config") or {}).get("format") or {}).get("schema")
    else:
        inst = next((b["text"] for b in kwargs.get("system") or [] if b["text"].startswith(bc.CONVERSE_SCHEMA_INSTRUCTION)), None)
        schema = json.loads(inst[len(bc.CONVERSE_SCHEMA_INSTRUCTION) :]) if inst else None
    return json.dumps(mse.schema_stub(schema)) if schema else "ok"


def test_the_three_internal_features_build_from_the_live_builders_over_the_labelled_corpus():
    import model_swap_eval as mse

    for name in ("coach_quality_gate", "coach_state_update", "coherence_semantic"):
        f = mse.FEATURES[name]
        cases = mse.build_cases(name)
        assert f.structured and all(c.schema for c in cases), name
        assert all("model" not in c.body and c.body["messages"] for c in cases), name
        assert mse.incumbent_model(f) == "claude-haiku-4-5-20251001", f"{name}: today's incumbent is the workhorse tier"
    with_facts = sum(1 for _l, fx, _t in mse._labelled_briefs() if fx.get("authoritative_facts"))
    assert len(mse.build_cases("coach_quality_gate")) == 45 and len(mse.build_cases("coherence_semantic")) == with_facts >= 20
    assert len(mse.build_cases("coach_state_update")) == 30
    # the judge's prompt carries the deterministic number verdict and the cache marker production sends
    c = next(c for c in mse.build_cases("coach_quality_gate") if c.id == "canary_hrv_fabricated")
    assert "Number Grounding" in c.body["messages"][0]["content"] and c.body["system"][0]["cache_control"]
    assert (
        c.gate(
            {
                "passed": True,
                "score": 90,
                "anti_pattern_violations": [],
                "decision_class_violations": [],
                "voice_distinctiveness_score": 80,
                "cross_coach_similarity_flags": [],
                "number_grounding_violations": [],
                "suggestions": [],
            }
        )[0]["gate"]
        == "missed_seeded_fault"
    )
    s = next(c for c in mse.build_cases("coherence_semantic"))
    assert (
        s.gate({"coherent": True, "issues": ["x"]})[0]["gate"] == "coherent_but_issues_listed"
        and s.gate({"coherent": True, "issues": []}) == []
    )


def test_the_swap_eval_drives_every_feature_x_candidate_through_the_adapter_with_a_stub_transport(wired):
    """The plumbing proof the issue asks for: twelve runs, Haiku 5.5 as the incumbent, each
    candidate through `invoke()` → Converse, the incumbent through `invoke()` → InvokeModel, the
    judge faked. Nothing leaves the machine; a stub transport can never report NON_INFERIOR."""
    import model_swap_eval as mse

    fake, cw, _tier = wired
    fake.converse_text = _structured_text
    fake.messages_text = _structured_text

    def through_the_chokepoint(body, model):
        return bc.invoke(dict(body), model_name=model)

    def tie_judge(body, model):
        return {
            "content": [{"type": "text", "text": json.dumps({"winner": "tie", "reason": "stub"})}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    n = 3
    table = []
    for feature in ("coach_quality_gate", "coach_state_update", "coherence_semantic"):
        for name, (model_id, _family, row) in CANDIDATES.items():
            conv_before, inv_before = len(fake.converse_calls), len(fake.invoke_calls)
            r = mse.run(feature, name, incumbent=HAIKU_55, n=n, invoker=through_the_chokepoint, judge_invoker=tie_judge, enforce_cap=False)
            assert r["resolved"] == {
                "incumbent": "us.anthropic.claude-haiku-5-5",
                "candidate": model_id,
                "judge": "us.anthropic.claude-sonnet-4-6",
            }
            assert r["price_rows"] == {"incumbent": "haiku-5-5", "candidate": row, "judge": "sonnet"}
            assert len(fake.converse_calls) - conv_before == n, (feature, name)
            assert {c["modelId"] for c in fake.converse_calls[conv_before:]} == {model_id}
            assert len(fake.invoke_calls) - inv_before == n and {c["modelId"] for c in fake.invoke_calls[inv_before:]} == {
                "us.anthropic.claude-haiku-5-5"
            }
            assert r["gate_failures"] == {"incumbent": {}, "candidate": {}}, (feature, name, r["gate_failures"])
            assert r["stats"]["n"] == n == r["stats"]["ties"] and r["verdict"] == mse.INCONCLUSIVE, (feature, name, r["verdict_reason"])
            assert r["cost_usd"]["candidate"] > 0 and r["calls"] == {"incumbent": n, "candidate": n, "judge": n}
            table.append((feature, name, r["verdict"], r["stats"]["n"]))
    assert len(table) == 12 and len(_cost_points(cw)) >= 24, "every arm call was metered at the chokepoint"


def test_the_deterministic_gate_bites_through_the_adapter(wired):
    """A candidate that waves a seeded fault through is BLOCKED_BY_GATE whatever the judge says."""
    import model_swap_eval as mse

    fake, _cw, _tier = wired
    waved = {
        "passed": True,
        "score": 95,
        "anti_pattern_violations": [],
        "decision_class_violations": [],
        "voice_distinctiveness_score": 90,
        "cross_coach_similarity_flags": [],
        "number_grounding_violations": [],
        "suggestions": [],
    }
    fake.converse_text = json.dumps(waved)
    fake.messages_text = _structured_text

    def through_the_chokepoint(body, model):
        return bc.invoke(dict(body), model_name=model)

    def candidate_wins(body, model):
        user = body["messages"][0]["content"]
        a = user.split("=== RESPONSE A ===", 1)[1].split("=== RESPONSE B ===", 1)[0]
        return {
            "content": [{"type": "text", "text": json.dumps({"winner": "A" if '"score": 95' in a else "B", "reason": "stub"})}],
            "usage": {},
        }

    r = mse.run(
        "coach_quality_gate",
        "gpt-oss-120b",
        incumbent=HAIKU_55,
        invoker=through_the_chokepoint,
        judge_invoker=candidate_wins,
        enforce_cap=False,
    )
    assert r["stats"]["wins"] == r["stats"]["n"] == r["inputs"] == 45
    assert r["verdict"] == mse.BLOCKED_BY_GATE, r["verdict_reason"]
    missed = set(r["gate_failures"]["candidate"]["missed_seeded_fault"])
    assert missed and missed <= {c["id"] for c in r["cases"] if c["id"].startswith("canary_")}
    assert "canary_anti_pattern" in missed and "canary_hrv_fabricated" in missed
    assert r["gate_failures"]["incumbent"] == {}
