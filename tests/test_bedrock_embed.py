"""tests/test_bedrock_embed.py — #1384 Titan-v2 embeddings arm of bedrock_client.

Mirrors tests/test_bedrock_client.py's monkeypatch+MagicMock convention (no moto).
"""

import json
import sys
import types
from unittest.mock import MagicMock

import bedrock_client as bc
import pytest


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    # never touch CloudWatch or SSM in these tests
    monkeypatch.setattr(bc, "_cw", lambda: MagicMock())
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: 0

    class _BE(RuntimeError):
        pass

    stub.BudgetExceeded = _BE
    monkeypatch.setitem(sys.modules, "budget_guard", stub)
    monkeypatch.delenv("BEDROCK_SHADOW_MODE", raising=False)
    yield


def _fake_titan_client(embedding, tokens=5):
    fc = MagicMock()
    body = json.dumps({"embedding": embedding, "inputTextTokenCount": tokens}).encode("utf-8")
    fc.invoke_model.return_value = {"body": MagicMock(read=lambda: body)}
    return fc


def test_embed_text_calls_titan_and_returns_vector(monkeypatch):
    fc = _fake_titan_client([0.1, 0.2, 0.3])
    monkeypatch.setattr(bc, "_client", lambda: fc)
    vec = bc.embed_text("how do I feel today", dimensions=3)
    assert vec == [0.1, 0.2, 0.3]
    kw = fc.invoke_model.call_args.kwargs
    assert kw["modelId"] == bc.TITAN_EMBED_MODEL_ID
    sent = json.loads(kw["body"])
    assert sent["inputText"] == "how do I feel today"
    assert sent["dimensions"] == 3
    assert sent["normalize"] is True


def test_embed_text_empty_raises(monkeypatch):
    monkeypatch.setattr(bc, "_client", lambda: _fake_titan_client([0.1]))
    with pytest.raises(ValueError):
        bc.embed_text("   ")


def test_embed_text_tier3_blocks(monkeypatch):
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: 3

    class _BE(RuntimeError):
        pass

    stub.BudgetExceeded = _BE
    monkeypatch.setitem(sys.modules, "budget_guard", stub)
    fc = _fake_titan_client([0.1])
    monkeypatch.setattr(bc, "_client", lambda: fc)
    with pytest.raises(_BE):
        bc.embed_text("blocked at tier 3")
    fc.invoke_model.assert_not_called()


def test_shadow_mode_is_deterministic(monkeypatch):
    monkeypatch.setenv("BEDROCK_SHADOW_MODE", "1")
    # no _client needed — shadow path never calls Bedrock
    v1 = bc.embed_text("same text", dimensions=16)
    v2 = bc.embed_text("same text", dimensions=16)
    v3 = bc.embed_text("different text", dimensions=16)
    assert v1 == v2  # deterministic
    assert v1 != v3
    assert len(v1) == 16
    # unit-length
    assert abs(sum(x * x for x in v1) ** 0.5 - 1.0) < 1e-6


def test_titan_priced_not_defaulted():
    # the "titan" price entry keeps embeddings from mispricing as the fable tier
    assert "titan" in bc._PRICES
    cost = bc.estimate_cost_usd({"input_tokens": 1_000_000, "output_tokens": 0}, "amazon.titan-embed-text-v2:0")
    assert cost == pytest.approx(0.02, abs=1e-9)
