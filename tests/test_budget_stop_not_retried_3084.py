"""#3084 + #3082 — a budget stop is a refusal, and the transport layer is its own module.

**#3084.** At tier 3 `bedrock_client.invoke()` raises `budget_guard.BudgetExceeded`
*before* `invoke_model` — nothing is billed, and nothing about a second attempt
could differ. Both retry wrappers caught it with a generic `except Exception` and
put it through the backoff ladder: 5 + 15 + 45 = **65 seconds of sleeps per call**
before returning the sentinel, logged as a transport-shaped WARN that buried the
real cause. The daily brief makes ~62 AI calls, so a hard budget stop became ~67
minutes of accumulated sleeps against a Lambda timeout — a failure risk created
exactly when the platform is already over its ceiling.

The pins below are on SLEEPS and INVOCATIONS, not on log text: `time.sleep` is
monkeypatched to fail the test if it is ever reached on the budget path, so
re-generalising the catch (deleting the `except _BudgetStop` clause and letting
`except Exception` take it again) reds all four of them. The one string assertion
checks the log line names the budget, per the issue's second acceptance bullet.

**#3082.** The facade tests pin the extraction itself: `ai_calls` must keep
re-exporting every transport name the fleet imports (`call_anthropic`,
`AI_MODEL_HAIKU`, `AI_UNAVAILABLE_SENTINEL`, `_build_system_block`,
`_emit_failure_metric`, …) and must not carry a second, drifting copy of any of
them. That is the whole risk of a facade split — a re-export that silently becomes
a fork — and it is checked by object identity, not by name.
"""

from __future__ import annotations

import ast
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
from ai import ai_calls, ai_transport, bedrock_client  # noqa: E402
from ai.budget_guard import BudgetExceeded  # noqa: E402

# The measured ladder. Every one of these seconds was spent for a result that
# could not change — the whole finding, expressed as a number.
_LADDER_SECONDS = 5 + 15 + 45


@pytest.fixture
def tier3(monkeypatch):
    """Bedrock refuses with the real tier-3 exception; any sleep fails the test."""
    calls = {"n": 0}

    def _invoke(body, model_name=None):
        calls["n"] += 1
        raise BudgetExceeded("AI paused — monthly budget ceiling reached (tier 3). Auto-resumes at month rollover.")

    def _no_sleep(seconds):
        raise AssertionError(
            f"backoff slept {seconds}s on a tier-3 budget stop — nothing was billed and nothing "
            f"can change; the full ladder is {_LADDER_SECONDS}s per call × ~62 brief calls (#3084)"
        )

    monkeypatch.setattr(bedrock_client, "invoke", _invoke)
    monkeypatch.setattr(ai_transport.time, "sleep", _no_sleep)
    import common.retry_utils as _ru

    monkeypatch.setattr(_ru.time, "sleep", _no_sleep)
    return calls


# ══════════════════════════════════════════════════════════════════════════════
# Wrapper 1 — ai/ai_transport.call_anthropic (the daily-brief path)
# ══════════════════════════════════════════════════════════════════════════════


def test_transport_returns_the_sentinel_immediately_on_a_budget_stop(tier3):
    out = ai_calls.call_anthropic("hello", max_tokens=600)

    assert out == "[AI_UNAVAILABLE]", "a budget stop must degrade to the R17-16 sentinel, same as an outage"
    assert tier3["n"] == 1, f"the budget stop was re-attempted {tier3['n']}× (#3084)"


def test_transport_logs_the_budget_stop_not_a_transport_error(tier3, capsys):
    ai_calls.call_anthropic("hello", max_tokens=600)
    out = capsys.readouterr().out.lower()

    assert "budget" in out, "the log line must name the budget stop — it used to read as a generic Bedrock error"
    assert "retrying in" not in out, "a budget stop must not announce a retry"


def test_transport_emits_no_failure_metric_for_a_budget_stop(tier3, monkeypatch):
    """A refusal is not an API failure. Charging AnthropicAPIFailure for it would
    corrupt the series `slo-ai-coaching-success` keys on (the #2668 rule)."""
    seen: list[str] = []
    monkeypatch.setattr(ai_transport, "_emit_failure_metric", lambda metric_name="AnthropicAPIFailure": seen.append(metric_name))

    ai_calls.call_anthropic("hello", max_tokens=600)

    assert seen == [], f"a budget stop emitted transport-failure metrics {seen} (#3084)"


# ══════════════════════════════════════════════════════════════════════════════
# Wrapper 2 — common/retry_utils (call_anthropic_api + call_anthropic_raw)
# ══════════════════════════════════════════════════════════════════════════════


def test_retry_utils_api_raises_the_budget_stop_immediately(tier3):
    import common.retry_utils as _ru

    with pytest.raises(BudgetExceeded):
        _ru.call_anthropic_api("hello", max_tokens=800)

    assert tier3["n"] == 1, f"the budget stop was re-attempted {tier3['n']}× (#3084)"


def test_retry_utils_raw_raises_the_budget_stop_immediately(tier3):
    import common.retry_utils as _ru

    with pytest.raises(BudgetExceeded):
        _ru.call_anthropic_raw({"model": "claude-haiku-4-5-20251001", "max_tokens": 100, "messages": [{"role": "user", "content": "x"}]})

    assert tier3["n"] == 1, f"the budget stop was re-attempted {tier3['n']}× (#3084)"


# ══════════════════════════════════════════════════════════════════════════════
# The fix must NARROW what retries, not switch retrying off
# ══════════════════════════════════════════════════════════════════════════════


def test_a_real_transport_error_still_walks_the_backoff_ladder(monkeypatch):
    """The counterweight to every test above: an ordinary Bedrock failure must
    still get its four attempts. A `BudgetExceeded` clause that accidentally
    swallowed transport errors would pass the tests above and break production."""
    import botocore.exceptions as bce

    attempts = {"n": 0}
    slept: list[int] = []

    def _invoke(body, model_name=None):
        attempts["n"] += 1
        raise bce.ClientError({"Error": {"Code": "ThrottlingException"}}, "InvokeModel")

    monkeypatch.setattr(bedrock_client, "invoke", _invoke)
    monkeypatch.setattr(ai_transport.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(ai_transport, "_emit_failure_metric", lambda metric_name="AnthropicAPIFailure": None)

    assert ai_calls.call_anthropic("hello") == "[AI_UNAVAILABLE]"
    assert attempts["n"] == 4, "a throttle must still get all four attempts"
    assert slept == [5, 15, 45], f"the backoff ladder changed: {slept}"


def test_budget_stop_cls_is_the_real_exception_and_fails_open(monkeypatch):
    """`bedrock_client.budget_stop_cls()` resolves the guard's class, and degrades
    to a never-raised sentinel if `budget_guard` is unimportable — so a missing
    guard leaves the generic retry path exactly as it was, never an ImportError
    on the AI path (the same fail-open posture `invoke()` already has)."""
    assert bedrock_client.budget_stop_cls() is BudgetExceeded

    import builtins

    real_import = builtins.__import__

    def _boom(name, *a, **kw):
        if name == "ai.budget_guard":
            raise ImportError("simulated missing guard")
        return real_import(name, *a, **kw)

    monkeypatch.delitem(sys.modules, "ai.budget_guard", raising=False)
    monkeypatch.setattr(builtins, "__import__", _boom)

    fallback = bedrock_client.budget_stop_cls()
    assert fallback is not BudgetExceeded
    assert issubclass(fallback, BaseException)
    assert not issubclass(Exception, fallback), "the fallback must never catch an ordinary error"


# ══════════════════════════════════════════════════════════════════════════════
# #3082 — the facade must stay a facade, not become a fork
# ══════════════════════════════════════════════════════════════════════════════


_REEXPORTED = [
    "call_anthropic",
    "_build_system_block",
    "_emit_failure_metric",
    "AI_MODEL",
    "AI_MODEL_HAIKU",
    "AI_UNAVAILABLE_SENTINEL",
    "AIOutputType",
    "_AI_VALIDATOR_AVAILABLE",
    "_BACKOFF_DELAYS",
    "_CW_NAMESPACE",
]


@pytest.mark.parametrize("name", _REEXPORTED)
def test_ai_calls_re_exports_the_transport_name_by_identity(name):
    """Identity, not equality: a re-export that quietly became a second copy is the
    one way a facade split breaks callers, and equality would not catch it."""
    assert hasattr(ai_calls, name), f"ai_calls stopped re-exporting {name} — every caller importing it breaks"
    assert getattr(ai_calls, name) is getattr(ai_transport, name), f"ai_calls.{name} has forked from ai_transport.{name}"


def test_the_transport_source_no_longer_lives_in_ai_calls():
    """The extraction must be a MOVE. A copy left behind would keep the file at its
    old size and let the two definitions drift silently."""
    src = open(os.path.join(_REPO, "lambdas", "ai", "ai_calls.py"), encoding="utf-8").read()
    for defn in ("def call_anthropic(", "def _build_system_block(", "def _emit_failure_metric("):
        assert defn not in src, f"{defn.strip()} is still defined in ai_calls.py — the transport split is a copy, not a move"


def _retry_try_blocks(rel: str):
    """Every `try:` that is the body of a `for attempt in range(...)` retry loop.

    AST, not text: prose in a docstring that *describes* the old destructure would
    trip a substring search (it does — the modules explain the defect at length),
    and the point of the pin is the shape of the protected block, not the words.
    """
    tree = ast.parse(open(os.path.join(_REPO, rel), encoding="utf-8").read())
    blocks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not (isinstance(node.iter, ast.Call) and getattr(node.iter.func, "id", "") == "range"):
            continue
        blocks += [stmt for stmt in node.body if isinstance(stmt, ast.Try)]
    return blocks


def test_the_parse_is_outside_the_retry_try_in_both_wrappers():
    """The structural half of the #2893 pin.

    Inside a retry `try`, the response variable may only be WRITTEN (the invoke
    call's assignment target). Any read of it in there is, by construction, a
    parse of a response the platform has already paid for — and if that parse
    raises, the loop re-invokes the model. `call_anthropic_raw` is the sanctioned
    exception: it returns the whole response and parses nothing.
    """
    for rel in ("lambdas/ai/ai_transport.py", "lambdas/common/retry_utils.py"):
        blocks = _retry_try_blocks(rel)
        assert blocks, f"{rel}: found no retry loop to check — the guard would pass vacuously"
        checked = 0
        for block in blocks:
            targets = {t.id for stmt in block.body if isinstance(stmt, ast.Assign) for t in stmt.targets if isinstance(t, ast.Name)}
            if not targets:
                continue
            checked += 1
            # `return resp` (call_anthropic_raw) hands the whole response back
            # unparsed — nothing there can raise, so it is not a re-bill risk.
            inspected = [s for s in block.body if not (isinstance(s, ast.Return) and isinstance(s.value, ast.Name))]
            reads = {
                n.id
                for stmt in inspected
                for n in ast.walk(stmt)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in targets
            }
            assert not reads, (
                f"{rel} line {block.lineno}: the retry `try` reads back {sorted(reads)} — "
                "a response you have already paid for is being parsed inside the retry loop (#2893)"
            )
        assert checked, f"{rel}: no retry `try` assigns a response — the guard would pass vacuously"
        src = open(os.path.join(_REPO, rel), encoding="utf-8").read()
        assert "first_text" in src, f"{rel} must parse through bedrock_client.first_text (#2893)"
