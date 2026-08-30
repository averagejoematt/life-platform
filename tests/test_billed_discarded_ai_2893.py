"""#2893 — the fleet must not pay Bedrock for output it then throws away.

Three mechanisms, each pinned here by the measurement that found it (30 days to
2026-08-23, CloudWatch Logs Insights + the LifePlatform/AI namespace):

1. **Truncation discard.** A call whose `max_tokens` cap is below what the model
   wants returns 200, is billed in full, and then fails `json.loads`. The caller
   logs at WARN and substitutes a fallback, so `Errors` stays at 0.0.
     · coach-state-updater — 116 of 359 metered calls (32.3%) logged
       `LLM returned non-dict extraction … — using default`; AnthropicOutputTokens
       Maximum == 1500.0 exactly (its call-site cap), Average 1297.
     · coach-quality-gate — 84 of 484 (17.4%) logged `Quality gate LLM returned
       non-dict … — using fallback`; AnthropicOutputTokens Maximum == 800.0
       exactly (its cap), Average 632.
   The state-updater case is the sharpest: `_call_haiku`'s docstring records a
   2026-05-03 bump of the default 1500 → 3000 *for this exact failure*, and the
   single call site passed `max_tokens=1500`, reinstating it.

2. **Retry re-bill.** Both transport wrappers destructure the response INSIDE
   their retry `try` (`resp["content"][0]["text"]`). An empty `content` list —
   the exact shape of a `max_tokens` stop with no emitted text — raises
   IndexError, is caught by the generic `except Exception`, and re-invokes the
   model up to 4×. Zero occurrences in the 30-day window, so this is latent, not
   active. Fixed in `common/retry_utils` here; `ai/ai_calls` carried the same
   defect behind a strict xfail (it was at 2396/2396 on the #1665 ratchet, so the
   fix could not land without an extraction) and was fixed by **#3082**, which
   moved the transport layer to `lambdas/ai/ai_transport.py`. That xfail is now a
   live assertion. #3084 then narrowed what retries at all: `BudgetExceeded` is a
   refusal raised before `invoke_model`, never a transport error — pinned in
   `tests/test_budget_stop_not_retried_3084.py`.

3. **Blind by construction.** `stop_reason` was read in exactly ZERO places
   across the tree, so mechanism 1 could only ever be found by a hand audit.
   `bedrock_client` now meters it (`TruncatedResponses`/`TruncatedCostUSD`).

These are behavior pins, not string pins: each asserts against the wire body the
call site actually builds, so raising a cap back or moving a parse back inside a
retry loop reds the suite.
"""

from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from ai import bedrock_client  # noqa: E402

# The measured caps. A discarded call is billed at exactly these numbers.
_OLD_STATE_UPDATER_CAP = 1500
_OLD_QUALITY_GATE_CAP = 800


def _messages_response(text: str = '{"ok": true}', stop_reason: str = "end_turn") -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 2200, "output_tokens": 700},
    }


# ══════════════════════════════════════════════════════════════════════════════
# Mechanism 1 — the caps that were below what the model wanted
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def wire(monkeypatch):
    """Capture the Messages body each coach module actually puts on the wire.

    The assertion has to be on the wire, not on a constant: the state-updater bug
    was a call-site override of a correct module default, so reading the default
    would have shown green while production truncated a third of its calls.
    """
    sent: list[dict] = []

    def _fake_call_anthropic_raw(req, timeout=55):
        body = req if isinstance(req, dict) else json.loads(req.data.decode("utf-8"))
        sent.append(body)
        return _messages_response()

    import common.retry_utils as _ru

    monkeypatch.setattr(_ru, "call_anthropic_raw", _fake_call_anthropic_raw)
    return sent


def test_state_updater_extraction_no_longer_caps_at_the_truncating_value(wire, monkeypatch):
    from coach import coach_state_updater as csu

    monkeypatch.setattr(csu, "_load_voice_spec", lambda coach_id: {})
    monkeypatch.setattr(csu, "_write_output_record", lambda *a, **k: None)
    monkeypatch.setattr(csu, "_update_voice_state", lambda *a, **k: None)
    monkeypatch.setattr(csu, "_create_thread_records", lambda *a, **k: None)
    monkeypatch.setattr(csu, "_resolve_threads", lambda *a, **k: None, raising=False)

    try:
        csu.lambda_handler(
            {"coach_id": "labs_coach", "output_text": "some output text", "output_type": "daily", "generation_date": "2026-08-23"},
            None,
        )
    except Exception:
        # Downstream state writes are not what this test pins; the wire body is.
        pass

    assert wire, "the extraction call never reached the wire"
    cap = wire[0]["max_tokens"]
    assert cap > _OLD_STATE_UPDATER_CAP, f"extraction cap is back at the measured truncation value ({cap})"
    assert cap == 3000, "the extraction must inherit _call_haiku's 2026-05-03 default, not a fresh literal"


def test_quality_gate_no_longer_caps_at_the_truncating_value(wire):
    from coach import coach_quality_gate as cqg

    report = cqg._run_quality_gate("labs_coach", "draft output", {}, {})

    assert wire, "the quality-gate call never reached the wire"
    cap = wire[0]["max_tokens"]
    assert cap > _OLD_QUALITY_GATE_CAP, f"quality-gate cap is back at the measured truncation value ({cap})"
    assert cap == cqg.QUALITY_GATE_MAX_TOKENS
    assert isinstance(report, dict)


def test_a_truncated_quality_gate_report_now_fails_closed(wire, monkeypatch):
    """The KNOWN HOLE this test used to pin is CLOSED — the conscious, reviewed
    flip it existed to force happened.

    #3083 (owner decision 2026-08-29, ADR-108 amendment): `_build_fallback_report`
    returns `passed: False`, so an unjudgeable draft is held under the
    regenerate-or-hold contract instead of being rubber-stamped (each of the 84
    measured discards had silently passed a draft the blocking gate never
    evaluated). The decision was priced on the re-measured rate: #3081 removed
    the dominant trigger (post-fix fallback rate 0/42) and `TruncatedResponses`
    guards its recurrence, so the hold path fires rarely — and a hold darkens
    only that coach's section (#966 CoachHold is terminal per-domain), never the
    brief.
    """
    from coach import coach_quality_gate as cqg

    monkeypatch.setattr(cqg, "_call_haiku", lambda **kw: "I'll evaluate this draft. The coach opens with a pattern rather th")
    report = cqg._run_quality_gate("labs_coach", "draft output", {}, {})
    assert report["_fallback"] is True
    assert report["passed"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Mechanism 2 — a paid-for response must never be retried
# ══════════════════════════════════════════════════════════════════════════════


_EMPTY_CONTENT = {"content": [], "stop_reason": "max_tokens", "usage": {"input_tokens": 2200, "output_tokens": 800}}


def test_retry_utils_does_not_rebill_on_an_empty_content_response(monkeypatch):
    import common.retry_utils as _ru

    calls = {"n": 0}

    def _invoke(body, model_name=None):
        calls["n"] += 1
        return _EMPTY_CONTENT

    monkeypatch.setattr(bedrock_client, "invoke", _invoke)
    monkeypatch.setattr(_ru, "_emit_failure_metric", lambda: None)
    monkeypatch.setattr(_ru.time, "sleep", lambda s: pytest.fail(f"backoff slept {s}s on an already-billed response"))

    with pytest.raises(ValueError):
        _ru.call_anthropic_api("hello", max_tokens=800)

    assert calls["n"] == 1, f"an already-billed response was re-invoked {calls['n']}× (the #2893 re-bill)"


def test_ai_calls_does_not_rebill_on_an_empty_content_response(monkeypatch):
    """Was a strict xfail when #3081 landed; FIXED by #3082 and now a live assertion.

    The blocker was never the fix, it was where the fix had to go: `lambdas/ai/
    ai_calls.py` sat at 2396/2396 on the #1665 ratchet and the standing rule is
    'do NOT raise the number — extract a cohesive sibling and pay for your lines'.
    #3082 did the extraction (the transport layer → `lambdas/ai/ai_transport.py`),
    which is why this can now assert instead of documenting its own absence.

    Deliberately driven through `ai_calls.call_anthropic` — the facade name every
    caller in the fleet actually imports — so the pin covers the re-export too.
    """
    from ai import ai_calls, ai_transport

    calls = {"n": 0}

    def _invoke(body, model_name=None):
        calls["n"] += 1
        return _EMPTY_CONTENT

    monkeypatch.setattr(bedrock_client, "invoke", _invoke)
    monkeypatch.setattr(ai_transport, "_emit_failure_metric", lambda metric_name="AnthropicAPIFailure": None)
    monkeypatch.setattr(ai_transport.time, "sleep", lambda s: pytest.fail(f"backoff slept {s}s on an already-billed response"))

    out = ai_calls.call_anthropic("hello", max_tokens=600)

    assert out == "[AI_UNAVAILABLE]"
    assert calls["n"] == 1, f"an already-billed response was re-invoked {calls['n']}× (the #2893 re-bill)"


def test_transport_failures_are_still_retried(monkeypatch):
    """The fix must narrow what retries, not switch retrying off."""
    import botocore.exceptions as bce
    import common.retry_utils as _ru

    calls = {"n": 0}

    def _invoke(body, model_name=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise bce.ClientError({"Error": {"Code": "ThrottlingException"}}, "InvokeModel")
        return _messages_response("recovered")

    monkeypatch.setattr(bedrock_client, "invoke", _invoke)
    monkeypatch.setattr(_ru.time, "sleep", lambda s: None)

    assert _ru.call_anthropic_api("hello") == "recovered"
    assert calls["n"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# Mechanism 3 — truncation is now metered at the one chokepoint
# ══════════════════════════════════════════════════════════════════════════════


class _StubBody:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload


class _StubBedrock:
    def __init__(self, payload: dict):
        self._payload = payload

    def invoke_model(self, **kwargs):
        return {"body": _StubBody(self._payload)}


@pytest.fixture
def chokepoint(monkeypatch):
    """Drive bedrock_client.invoke() and capture every CloudWatch datapoint."""
    emitted: list[dict] = []

    class _StubCW:
        def put_metric_data(self, Namespace, MetricData):
            for m in MetricData:
                emitted.append({**m, "Namespace": Namespace})

    monkeypatch.setattr(bedrock_client, "_CW", _StubCW())

    def _run(payload: dict, body: dict):
        monkeypatch.setattr(bedrock_client, "_BEDROCK", _StubBedrock(payload))
        return bedrock_client.invoke(body, model_name="claude-haiku-4-5-20251001")

    return _run, emitted


def _names(emitted):
    return {m["MetricName"] for m in emitted}


def test_a_truncated_response_is_metered_at_the_chokepoint(chokepoint):
    run, emitted = chokepoint
    run(
        {
            "content": [{"type": "text", "text": '{"score": 8'}],
            "stop_reason": "max_tokens",
            "usage": {"input_tokens": 2200, "output_tokens": 800},
        },
        {"max_tokens": 800, "messages": [{"role": "user", "content": "x"}]},
    )
    assert "TruncatedResponses" in _names(emitted)
    assert "TruncatedCostUSD" in _names(emitted)

    # Per-feature attribution AND a platform-wide series — one alarmable, one
    # answers "which Lambda". A dimensioned-only metric cannot be summed fleet-wide.
    trunc = [m for m in emitted if m["MetricName"] == "TruncatedResponses"]
    assert any("Dimensions" in m for m in trunc)
    assert any("Dimensions" not in m for m in trunc)

    # Haiku: 2200 in @ $1/M + 800 out @ $5/M = $0.0062. The dollars ARE the finding.
    cost = [m for m in emitted if m["MetricName"] == "TruncatedCostUSD"][0]["Value"]
    assert cost == pytest.approx(0.0062, abs=1e-6)


def test_a_normal_response_emits_no_truncation_metric(chokepoint):
    run, emitted = chokepoint
    run(_messages_response(), {"max_tokens": 800, "messages": [{"role": "user", "content": "x"}]})
    assert "TruncatedResponses" not in _names(emitted)
    assert "AnthropicOutputTokens" in _names(emitted), "usage metering must be unaffected"


def test_truncation_telemetry_never_breaks_the_ai_call(monkeypatch):
    """Fail-open, like every other side channel at this chokepoint."""

    class _ExplodingCW:
        def put_metric_data(self, **kwargs):
            raise RuntimeError("PutMetricData denied")

    payload = {"content": [{"type": "text", "text": "hi"}], "stop_reason": "max_tokens", "usage": {"input_tokens": 10, "output_tokens": 5}}
    monkeypatch.setattr(bedrock_client, "_CW", _ExplodingCW())
    monkeypatch.setattr(bedrock_client, "_BEDROCK", _StubBedrock(payload))

    out = bedrock_client.invoke({"max_tokens": 5, "messages": [{"role": "user", "content": "x"}]}, model_name="claude-haiku-4-5-20251001")
    assert out["content"][0]["text"] == "hi"


# ══════════════════════════════════════════════════════════════════════════════
# first_text — the helper both wrappers now share
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "resp,expected",
    [
        ({"content": [{"type": "text", "text": "hello"}]}, "hello"),
        # A thinking-first response: the text block is not index 0. The old
        # `content[0]["text"]` raised KeyError here and re-billed the call.
        ({"content": [{"type": "thinking", "thinking": "…"}, {"type": "text", "text": "hello"}]}, "hello"),
        ({"content": []}, None),
        ({}, None),
        (None, None),
    ],
)
def test_first_text_never_raises(resp, expected):
    assert bedrock_client.first_text(resp) == expected
