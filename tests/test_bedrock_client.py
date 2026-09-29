"""
tests/test_bedrock_client.py — model routing + adaptive-surface param hygiene.

Covers:
  - resolve_model_id maps Anthropic-style names to Bedrock inference profiles
    (including fable / opus-4-8, added 2026-06-12, and the Claude 5 family, #4275)
  - an UNMAPPED NAME raises UnknownModelError naming the input and the known keys
    (#4275 — it used to fall back to Haiku 4.5 silently; the negative control
    below is the mutation proof: restore `.get(name, _DEFAULT_PROFILE)` and it reds)
  - no name at all still takes the default profile (absent is not unknown)
  - profile ids / ARNs pass through untouched
  - invoke() scrubs sampling params (temperature/top_p/top_k) for Fable 5 and
    Opus 4.7+ AND the Claude 5 line (those models 400 on them) and drops an
    explicit thinking:{type:"disabled"} on Fable / Opus 5.5 — while leaving
    Sonnet 4.6 bodies intact
  - the price registry: every mapped model prices by an explicit row, the 5-family
    rows carry their own (not their family's) rates, every row has provenance, the
    first-match and longest-match orderings agree, and today's live models price
    exactly as they did before #4275 (the governor's projection must not move)
  - both retry wrappers refuse an unknown name immediately — no invoke_model call,
    no backoff sleep — and the brief-facing wrapper returns the outage sentinel

Run:  python3 -m pytest tests/test_bedrock_client.py -v
"""

import importlib
import json
import os
import re
import sys
import types
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from ai import bedrock_client as bc  # noqa: E402
from bundle_stubs import stub_bundled_module

# The four Claude 5 profile ids, read live from
# `aws bedrock list-inference-profiles --region us-west-2` on 2026-09-26 (all ACTIVE,
# SYSTEM_DEFINED). If Bedrock ever renames one, this table is the thing to re-read.
_CLAUDE_5_PROFILES = {
    "claude-fable-5-1": "us.anthropic.claude-fable-5-1",
    "claude-opus-5": "us.anthropic.claude-opus-5",
    "claude-opus-5-5": "us.anthropic.claude-opus-5-5",
    "claude-sonnet-5": "us.anthropic.claude-sonnet-5",
}


def test_fable_and_opus48_map_to_us_profiles():
    assert bc.resolve_model_id("claude-fable-5") == "us.anthropic.claude-fable-5"
    assert bc.resolve_model_id("claude-opus-4-8") == "us.anthropic.claude-opus-4-8"


@pytest.mark.parametrize("name,profile", sorted(_CLAUDE_5_PROFILES.items()))
def test_claude_5_family_names_resolve_to_the_live_us_profiles(name, profile):
    assert bc.resolve_model_id(name) == profile


# ── #4275: unknown is loud, absent is the default ────────────────────────────


def test_unmapped_model_name_raises_naming_the_input_and_the_known_keys():
    """The negative control. Before #4275 this returned the Haiku 4.5 profile for
    ANY string — `AI_MODEL=claude-sonnet-5` downgraded every narrative surface to
    Haiku with no error anywhere. Mutation proof: put `.get(name, _DEFAULT_PROFILE)`
    back in resolve_model_id and this test fails."""
    with pytest.raises(bc.UnknownModelError) as ei:
        bc.resolve_model_id("claude-future-9")
    msg = str(ei.value)
    assert "claude-future-9" in msg, "the error must name the input"
    for known in ("claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-sonnet-5"):
        assert known in msg, f"the error must list the resolvable names (missing {known})"
    assert ei.value.model_name == "claude-future-9"
    assert isinstance(ei.value, ValueError), "the issue's acceptance names ValueError; callers may except either"


def test_planted_ai_model_env_var_with_a_nonsense_name_raises(monkeypatch):
    """The literal acceptance line: plant AI_MODEL=claude-nonsense, assert the raise —
    through the same env var every Lambda's default-model line reads."""
    monkeypatch.setenv("AI_MODEL", "claude-nonsense")
    with pytest.raises(bc.UnknownModelError, match="claude-nonsense"):
        bc.resolve_model_id(os.environ["AI_MODEL"])


def test_no_model_name_at_all_still_takes_the_default_profile():
    """Absent is not unknown. A raw body with no "model" key (call_anthropic_raw's
    `body.get("model")`) keeps the pre-#4275 default so no caller crash-loops on a
    body shape that worked yesterday; only a NAME that resolves to nothing raises."""
    assert bc.resolve_model_id(None) == bc._DEFAULT_PROFILE
    assert bc.resolve_model_id("") == bc._DEFAULT_PROFILE
    assert "haiku-4-5" in bc._DEFAULT_PROFILE


def test_profile_ids_and_arns_pass_through():
    assert bc.resolve_model_id("us.anthropic.claude-fable-5") == "us.anthropic.claude-fable-5"
    assert bc.resolve_model_id("global.anthropic.claude-sonnet-4-6") == "global.anthropic.claude-sonnet-4-6"
    arn = "arn:aws:bedrock:us-west-2:1:inference-profile/x"
    assert bc.resolve_model_id(arn) == arn


# ── invoke(): the sampling / thinking scrub ──────────────────────────────────


def _stub_budget_guard(monkeypatch):
    """Stub budget_guard so invoke() never touches SSM."""
    stub = types.ModuleType("budget_guard")
    stub.BudgetExceeded = RuntimeError
    stub.current_tier = lambda: 0
    stub_bundled_module(monkeypatch, "ai.budget_guard", stub)


def _invoke_and_capture(monkeypatch, body, model_name):
    """Run bc.invoke with mocked Bedrock + budget guard; return the sent body."""
    _stub_budget_guard(monkeypatch)
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = {"body": MagicMock(read=lambda: b'{"content": []}')}
    monkeypatch.setattr(bc, "_client", lambda: fake_client)

    bc.invoke(body, model_name=model_name)
    return json.loads(fake_client.invoke_model.call_args.kwargs["body"])


def test_invoke_scrubs_sampling_params_on_fable(monkeypatch):
    body = {"messages": [], "max_tokens": 10, "temperature": 0.7, "top_p": 0.9, "top_k": 5}
    sent = _invoke_and_capture(monkeypatch, body, "claude-fable-5")
    assert "temperature" not in sent and "top_p" not in sent and "top_k" not in sent


@pytest.mark.parametrize("name", sorted(_CLAUDE_5_PROFILES))
def test_invoke_scrubs_sampling_params_on_the_claude_5_family(monkeypatch, name):
    """Sonnet 5 / Opus 5 / Opus 5.5 / Fable 5.1 all 400 on temperature/top_p/top_k;
    ~40 `_call_haiku(..., temperature=0.2)` helpers still pass one. The chokepoint
    scrub is what keeps them model-agnostic when #4278 flips a surface."""
    body = {"messages": [], "max_tokens": 10, "temperature": 0.2, "top_p": 0.9, "top_k": 5}
    sent = _invoke_and_capture(monkeypatch, body, name)
    assert "temperature" not in sent and "top_p" not in sent and "top_k" not in sent


def test_invoke_drops_explicit_thinking_disabled_on_fable(monkeypatch):
    body = {"messages": [], "max_tokens": 10, "thinking": {"type": "disabled"}}
    sent = _invoke_and_capture(monkeypatch, body, "claude-fable-5")
    assert "thinking" not in sent


@pytest.mark.parametrize("name", ["claude-fable-5-1", "claude-opus-5-5"])
def test_invoke_drops_explicit_thinking_disabled_where_the_model_rejects_it(monkeypatch, name):
    body = {"messages": [], "max_tokens": 10, "thinking": {"type": "disabled"}}
    sent = _invoke_and_capture(monkeypatch, body, name)
    assert "thinking" not in sent


@pytest.mark.parametrize("name", ["claude-sonnet-5", "claude-opus-5"])
def test_invoke_keeps_explicit_thinking_disabled_where_the_model_accepts_it(monkeypatch, name):
    """Opus 5 accepts `disabled` at effort high or below and Sonnet 5 accepts it
    outright — a scrub there would silently turn thinking ON and change the bill."""
    body = {"messages": [], "max_tokens": 10, "thinking": {"type": "disabled"}}
    sent = _invoke_and_capture(monkeypatch, body, name)
    assert sent["thinking"] == {"type": "disabled"}


def test_invoke_keeps_adaptive_thinking_on_fable(monkeypatch):
    body = {"messages": [], "max_tokens": 10, "thinking": {"type": "adaptive"}}
    sent = _invoke_and_capture(monkeypatch, body, "claude-fable-5")
    assert sent["thinking"] == {"type": "adaptive"}


def test_invoke_leaves_sonnet_body_untouched(monkeypatch):
    body = {"messages": [], "max_tokens": 10, "temperature": 0.3}
    sent = _invoke_and_capture(monkeypatch, body, "claude-sonnet-4-6")
    assert sent["temperature"] == 0.3


def test_invoke_refuses_an_unknown_name_before_touching_bedrock(monkeypatch):
    """The chokepoint raises BEFORE invoke_model — nothing billed, no Haiku call."""
    _stub_budget_guard(monkeypatch)
    fake_client = MagicMock()
    monkeypatch.setattr(bc, "_client", lambda: fake_client)
    with pytest.raises(bc.UnknownModelError):
        bc.invoke({"messages": [], "max_tokens": 10, "model": "claude-nonsense"})
    fake_client.invoke_model.assert_not_called()


# ── the price registry (#4275) ───────────────────────────────────────────────


def test_every_mapped_model_prices_by_an_explicit_row_never_the_unknown_default():
    for name, profile in bc._MODEL_MAP.items():
        key = bc.price_key_for(profile)
        assert key is not None, f"{name} -> {profile} matched no PRICES row; it would meter at the unknown-model default"


@pytest.mark.parametrize(
    "profile,key,in_rate,out_rate,cache_read",
    [
        ("us.anthropic.claude-sonnet-5", "sonnet-5", 2.00, 10.00, 0.20),
        ("us.anthropic.claude-opus-5", "opus-5", 5.00, 25.00, 0.50),
        ("us.anthropic.claude-opus-5-5", "opus-5-5", 4.00, 20.00, 0.20),
        ("us.anthropic.claude-fable-5-1", "fable-5-1", 10.00, 50.00, 0.25),
    ],
)
def test_claude_5_family_prices_at_its_own_rates_not_its_family_row(profile, key, in_rate, out_rate, cache_read):
    """The issue's third defect: Sonnet 5 would have metered at Sonnet 4.6's $3/$15.
    Rates read from https://platform.claude.com/docs/en/about-claude/pricing on
    2026-09-26 (Sonnet 5's $2/$10 made permanent; Fable 5.1 / Opus 5.5 cache reads at
    0.025x / 0.05x base). Chokepoint AND governor must agree — they are the two halves
    of CostMetricDriftRatio (#2883)."""
    from operational import cost_governor_lambda as cg

    assert bc.price_key_for(profile) == key
    for price in (bc._price_for(profile), cg._price_for(profile)):
        assert price["in"] == in_rate and price["out"] == out_rate and price["cache_read"] == cache_read
    assert bc._price_for(profile) is cg._price_for(profile), "one registry object, both halves"


def test_todays_live_models_price_exactly_as_before_4275():
    """The governor's month-end projection must NOT move with this change. Today's
    Bedrock ModelIds (the ones `list_metrics` returns) and the batch/embedding ids all
    still land on the same family rows at the same numbers."""
    from operational import cost_governor_lambda as cg

    pinned = {
        "us.anthropic.claude-haiku-4-5-20251001-v1:0": ("haiku", 1.00, 5.00, 0.10, 1.25),
        "us.anthropic.claude-sonnet-4-6": ("sonnet", 3.00, 15.00, 0.30, 3.75),
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0": ("sonnet", 3.00, 15.00, 0.30, 3.75),
        "us.anthropic.claude-fable-5": ("fable", 10.00, 50.00, 1.00, 12.50),
        "us.anthropic.claude-opus-4-8": ("opus", 5.00, 25.00, 0.50, 6.25),
        "amazon.titan-embed-text-v2:0": ("titan", 0.02, 0.00, 0.00, 0.00),
    }
    for model_id, (key, in_rate, out_rate, cache_read, cache_write) in pinned.items():
        assert bc.price_key_for(model_id) == key, model_id
        for price in (bc._price_for(model_id), cg._price_for(model_id)):
            assert (price["in"], price["out"], price["cache_read"], price["cache_write"]) == (
                in_rate,
                out_rate,
                cache_read,
                cache_write,
            ), model_id
    # The unknown-model default is untouched: still the most expensive tier.
    assert bc._price_for("some-model-from-2027") is bc._DEFAULT_PRICE
    assert bc._DEFAULT_PRICE is bc.PRICES["fable"]


def test_insertion_order_first_match_agrees_with_longest_match_for_every_mapped_model():
    """Three consumers still iterate PRICES in insertion order and take the FIRST
    substring hit (`web/site_api_budget._price_for_model`, `scripts/ai_spend_attribution`,
    `scripts/batch_feasibility`). Keeping specific rows ahead of family rows is what
    keeps them on the same row as `price_key_for`; this pins that ordering."""
    ids = list(bc._MODEL_MAP.values()) + ["amazon.titan-embed-text-v2:0", "global.anthropic.claude-sonnet-5"]
    for model_id in ids:
        first = next((k for k in bc.PRICES if k in model_id.lower()), None)
        assert first == bc.price_key_for(model_id), f"{model_id}: first-match {first!r} != longest-match {bc.price_key_for(model_id)!r}"


def test_every_price_row_carries_a_source_and_a_verified_on_date():
    """A row with no source is a remembered number (#2883's Titan was one, 500x off)."""
    assert set(bc.PRICE_PROVENANCE) == set(bc.PRICES), "provenance and PRICES must name the same rows"
    for key, prov in bc.PRICE_PROVENANCE.items():
        assert prov["source"].startswith("https://"), key
        assert len(prov["verified_on"]) == 10 and prov["verified_on"][4] == "-", key


def test_the_new_rows_keep_the_registry_invariants_the_lockstep_test_holds():
    """Same shape as tests/test_price_registry_lockstep_2883.py — 5m write = 1.25x in,
    1h write = 2x in — asserted here on the 5-family rows by name so a mistyped rate
    is caught next to the row that carries it."""
    for key in ("fable-5-1", "opus-5-5", "opus-5", "sonnet-5"):
        p = bc.PRICES[key]
        assert abs(p["cache_write"] - p["in"] * 1.25) < 1e-9, key
        assert abs(p["cache_write_1h"] - p["in"] * 2.0) < 1e-9, key
        assert p["cache_write_1h"] > p["cache_write"] > p["cache_read"] > 0, key


# ── the two retry wrappers: unknown is refused, not retried (#4275 / #3084) ──


def _never_sleep(seconds):
    raise AssertionError(f"the backoff ladder ran (slept {seconds}s) — an unknown model name must not be retried")


def test_retry_utils_with_a_planted_nonsense_ai_model_raises_without_billing_or_backoff(monkeypatch):
    """End to end through `common.retry_utils.call_anthropic_api`, whose default model
    is `os.environ["AI_MODEL"]` read at import: plant the nonsense name, reload, call.
    No invoke_model call (nothing billed), no sleep (no 5+15+45s ladder), the typed
    error propagates with the input and the known names in it."""
    from common import retry_utils

    monkeypatch.setenv("AI_MODEL", "claude-nonsense")
    ru = importlib.reload(retry_utils)
    try:
        assert ru.AI_MODEL == "claude-nonsense"
        _stub_budget_guard(monkeypatch)
        fake_client = MagicMock()
        monkeypatch.setattr(bc, "_client", lambda: fake_client)
        monkeypatch.setattr(ru.time, "sleep", _never_sleep)
        monkeypatch.setattr(ru, "_emit_failure_metric", lambda: None)
        with pytest.raises(bc.UnknownModelError) as ei:
            ru.call_anthropic_api("hello")
        assert "claude-nonsense" in str(ei.value) and "claude-sonnet-5" in str(ei.value)
        fake_client.invoke_model.assert_not_called()
    finally:
        monkeypatch.delenv("AI_MODEL", raising=False)
        importlib.reload(retry_utils)


def test_retry_utils_raw_wrapper_refuses_an_unknown_name_the_same_way(monkeypatch):
    from common import retry_utils as ru

    _stub_budget_guard(monkeypatch)
    fake_client = MagicMock()
    monkeypatch.setattr(bc, "_client", lambda: fake_client)
    monkeypatch.setattr(ru.time, "sleep", _never_sleep)
    monkeypatch.setattr(ru, "_emit_failure_metric", lambda: None)
    with pytest.raises(bc.UnknownModelError):
        ru.call_anthropic_raw({"model": "claude-nonsense", "max_tokens": 5, "messages": []})
    fake_client.invoke_model.assert_not_called()


def test_ai_transport_returns_the_outage_sentinel_immediately_on_an_unknown_name(monkeypatch):
    """The daily brief's wrapper. Its contract on a hard Bedrock error is the
    `[AI_UNAVAILABLE]` sentinel (R17-16) — each coach degrades, the brief ships.
    An unknown name keeps that contract and reaches it in seconds: no ladder, no
    invoke_model, and the failure metric fires so the misconfiguration is visible."""
    from ai import ai_transport as at

    _stub_budget_guard(monkeypatch)
    fake_client = MagicMock()
    monkeypatch.setattr(bc, "_client", lambda: fake_client)
    monkeypatch.setattr(at.time, "sleep", _never_sleep)
    fired = []
    monkeypatch.setattr(at, "_emit_failure_metric", lambda *a, **k: fired.append(1))
    out = at.call_anthropic("hello", model="claude-nonsense")
    assert out == at.AI_UNAVAILABLE_SENTINEL
    fake_client.invoke_model.assert_not_called()
    assert fired, "the failure metric must fire — a silent sentinel would hide the misconfiguration again"


# ── #4279: ONE retry policy for every Bedrock call ───────────────────────────
#
# Before: botocore `{"max_attempts": 2, "mode": "adaptive"}` (= 3 sends — botocore
# reads client-config max_attempts as RETRIES and adds one) under three app-level
# 4-attempt loops at 5/15/45 s: 12 invoke_model sends and >= 65 s of sleep per call
# on a sustained throttle. After: botocore sends once; `invoke_with_retry` is the
# only loop: 3 sends, <= 20 s of jittered sleep. The tests below drive REAL botocore
# (a before-send hook answers every send with a 400 ThrottlingException), so the
# counts are the wire's, not a mock's.


class _RawBody:
    def __init__(self, data: bytes):
        self._data = data

    def stream(self, **_kw):
        yield self._data

    def read(self, *_a, **_kw):
        return self._data


def _throttle_every_send(client) -> list:
    """Answer every InvokeModel send with a Bedrock ThrottlingException; return the send log."""
    from botocore.awsrequest import AWSResponse

    sends: list = []

    def _answer(request, **_kw):
        sends.append(request.url)
        body = b'{"message":"Too many requests, please wait before trying again."}'
        headers = {"x-amzn-ErrorType": "ThrottlingException:http://internal.amazon.com/coral/", "Content-Type": "application/json"}
        return AWSResponse(request.url, 400, headers, _RawBody(body))

    client.meta.events.register("before-send.bedrock-runtime.InvokeModel", _answer)
    return sends


@pytest.fixture
def _fake_aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "FAKEKEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "FAKESECRET")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)


@pytest.fixture
def _recorded_sleep(monkeypatch):
    """Record every sleep (botocore's and the policy's — both call time.sleep); jitter at max."""
    import time as _time

    slept: list = []
    monkeypatch.setattr(_time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(bc, "_jitter", lambda: 1.0)
    return slept


def _real_client(monkeypatch):
    """The production `_client()` construction, fresh (not the cached singleton)."""
    monkeypatch.setattr(bc, "_BEDROCK", None)
    client = bc._client()
    monkeypatch.setattr(bc, "_BEDROCK", client)
    return client


def test_botocore_makes_exactly_one_send_per_invoke(monkeypatch, _fake_aws, _recorded_sleep):
    """The production client config retries nothing: one throttled send, one raise."""
    import botocore.exceptions as bce

    sends = _throttle_every_send(_real_client(monkeypatch))
    with pytest.raises(bce.ClientError):
        bc._client().invoke_model(modelId="us.anthropic.claude-sonnet-4-6", body=b"{}", contentType="application/json")
    assert len(sends) == 1, f"botocore sent {len(sends)}x — its retries must be OFF; invoke_with_retry is the one policy"


def test_the_old_client_config_sent_three_times_not_two(_fake_aws, _recorded_sleep):
    """The negative control, and the proof of the stacking arithmetic: the retired
    `{"max_attempts": 2, "mode": "adaptive"}` config made THREE sends (botocore adds
    one for the initial request), so each of the old 4-attempt app loops cost up to
    4 x 3 = 12 sends. If this ever reads 2, the 'before' figure in #4279 is wrong."""
    import boto3
    import botocore.exceptions as bce
    from botocore.config import Config

    old = boto3.client("bedrock-runtime", region_name="us-west-2", config=Config(retries={"max_attempts": 2, "mode": "adaptive"}))
    sends = _throttle_every_send(old)
    with pytest.raises(bce.ClientError):
        old.invoke_model(modelId="us.anthropic.claude-sonnet-4-6", body=b"{}", contentType="application/json")
    assert len(sends) == 3


def _wrapper_calls():
    from ai import ai_transport as at
    from common import retry_utils as ru

    return {
        "ai_transport.call_anthropic": lambda: at.call_anthropic("hello", model="claude-sonnet-4-6"),
        "retry_utils.call_anthropic_api": lambda: ru.call_anthropic_api("hello", model="claude-sonnet-4-6"),
        "retry_utils.call_anthropic_raw": lambda: ru.call_anthropic_raw(
            {"model": "claude-sonnet-4-6", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}
        ),
    }


@pytest.mark.parametrize("wrapper", sorted(_wrapper_calls()))
def test_every_wrapper_makes_the_policy_attempts_on_the_wire_and_no_more(monkeypatch, _fake_aws, _recorded_sleep, wrapper):
    """End to end: wrapper → invoke_with_retry → invoke → REAL botocore → the throttling
    hook. The count is invoke_model sends on the wire. The mutation control: put a
    local retry loop back in any wrapper (or turn botocore retries back on) and the
    count multiplies — this test fails naming that wrapper."""
    import botocore.exceptions as bce
    from ai import ai_transport as at
    from common import retry_utils as ru

    _stub_budget_guard(monkeypatch)
    monkeypatch.setattr(ru, "_emit_failure_metric", lambda *a, **k: None)
    monkeypatch.setattr(at, "_emit_failure_metric", lambda *a, **k: None)
    sends = _throttle_every_send(_real_client(monkeypatch))
    try:
        out = _wrapper_calls()[wrapper]()
        assert out == at.AI_UNAVAILABLE_SENTINEL, f"{wrapper} returned {out!r} on a sustained throttle"
    except bce.ClientError:  # the raising wrappers re-raise the final ClientError
        pass
    assert len(sends) == bc.INVOKE_MAX_ATTEMPTS == 3, (
        f"{wrapper}: {len(sends)} invoke_model sends on a sustained throttle — the one policy allows "
        f"{bc.INVOKE_MAX_ATTEMPTS}. A retry loop is stacked on invoke_with_retry (or botocore retries are back on)."
    )
    assert sum(_recorded_sleep) == sum(bc.INVOKE_RETRY_BASE_DELAYS) == 20, f"{wrapper}: slept {_recorded_sleep}"


def test_retry_delay_is_jittered_and_bounded_by_its_base(monkeypatch):
    monkeypatch.setattr(bc, "_jitter", lambda: 0.0)
    assert [bc.retry_delay(a) for a in (1, 2)] == [2.5, 7.5]
    monkeypatch.setattr(bc, "_jitter", lambda: 1.0)
    assert [bc.retry_delay(a) for a in (1, 2)] == [5.0, 15.0]
    assert len(bc.INVOKE_RETRY_BASE_DELAYS) == bc.INVOKE_MAX_ATTEMPTS - 1
    assert bc.INVOKE_MAX_ATTEMPTS <= 4, "#4279 acceptance: total attempts per call bounded at 4"


def test_invoke_with_retry_never_retries_an_unknown_model_name(monkeypatch, _recorded_sleep):
    """#4306/#4275 kept exactly: a model name that resolves to nothing is a refusal
    raised before invoke_model — ZERO retries, zero sleep, zero sends."""
    _stub_budget_guard(monkeypatch)
    fake_client = MagicMock()
    monkeypatch.setattr(bc, "_client", lambda: fake_client)
    with pytest.raises(bc.UnknownModelError):
        bc.invoke_with_retry({"max_tokens": 5, "messages": []}, model_name="claude-nonsense")
    fake_client.invoke_model.assert_not_called()
    assert _recorded_sleep == []


def test_invoke_with_retry_does_not_retry_a_non_retryable_code(monkeypatch, _recorded_sleep):
    import botocore.exceptions as bce

    calls = {"n": 0}

    def _invoke(body, model_name=None):
        calls["n"] += 1
        raise bce.ClientError({"Error": {"Code": "ValidationException"}}, "InvokeModel")

    monkeypatch.setattr(bc, "invoke", _invoke)
    with pytest.raises(bce.ClientError):
        bc.invoke_with_retry({"messages": []}, model_name="claude-sonnet-4-6")
    assert calls["n"] == 1 and _recorded_sleep == []


# ── #4275 box 4: ONE Sonnet default ─────────────────────────────────────────────────────
_SONNET_LITERAL_RE = re.compile(r"(?:us\.|global\.)?(?:anthropic\.)?claude-sonnet-[\w.:-]+")
# The resolution map (names → profile ids) is the one place model names MUST be spelled out.
_SONNET_LITERAL_HOMES = {"lambdas/ai/bedrock_client.py", "lambdas/ai/model_defaults.py"}


def _sonnet_literals_outside_the_homes(root):
    import ast
    import pathlib

    root = pathlib.Path(root)
    found = []
    for p in sorted([*root.glob("lambdas/**/*.py"), *root.glob("mcp/**/*.py")]):
        rel = p.relative_to(root).as_posix()
        if rel in _SONNET_LITERAL_HOMES:
            continue
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _SONNET_LITERAL_RE.fullmatch(node.value):
                found.append(f"{rel}:{node.lineno} {node.value}")
    return found


def test_no_module_carries_a_sonnet_default_outside_the_one_constant():
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    assert _sonnet_literals_outside_the_homes(root) == []


def test_the_one_constant_is_a_mapped_name_and_its_value_is_unchanged():
    from ai.model_defaults import NARRATIVE_MODEL

    assert NARRATIVE_MODEL == "claude-sonnet-4-6"  # moving it is #4278 (gate:owner), not #4275
    assert bc.resolve_model_id(NARRATIVE_MODEL) == "us.anthropic.claude-sonnet-4-6"


def test_mutation_control_a_planted_default_literal_is_found(tmp_path):
    (tmp_path / "lambdas" / "emails").mkdir(parents=True)
    (tmp_path / "lambdas" / "emails" / "x.py").write_text('import os\nM = os.environ.get("AI_MODEL", "claude-sonnet-4-6")\n')
    assert _sonnet_literals_outside_the_homes(tmp_path) == ["lambdas/emails/x.py:2 claude-sonnet-4-6"]
