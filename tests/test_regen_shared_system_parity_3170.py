#!/usr/bin/env python3
"""tests/test_regen_shared_system_parity_3170.py — #3170: the ADR-108 regen call inside
`_gate_prose` must run under the SAME `shared_system` as the primary generation call, not
a weaker one. Before the fix, `_regen`'s `_anthropic_req(...)` call carried NO system
block at all — a held-then-regenerated verdict was produced under different system
context than the first attempt, so it wasn't attributable to the correction note alone.

Pinned here: the primary call's request body and the regen call's request body carry the
IDENTICAL `system` block (same shared_system text, same cache_control shape). Mutation
proof: reverting `_regen` to drop the `system=shared_system` kwarg reds this test — the
regen request loses its `system` key entirely while the primary request keeps its own.

Offline by construction: the model seam (`common.retry_utils.call_anthropic_raw`) is
monkeypatched and DynamoDB is a dict; no AWS, no Bedrock.
"""

import json
import os
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "intelligence"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_import_err = None
try:
    import ai_expert_analyzer_lambda as az
    from common import retry_utils
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    az = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"ai_expert_analyzer_lambda unavailable: {_import_err}")  # type: ignore

# A number that appears in NO prompt/facts these tests build — the #2290 fabrication class,
# same constant `test_analyzer_gate_all_paths_2421.py` uses to force exactly one regen.
FABRICATED = "You averaged 8412 steps across the week."
CLEAN = "Hold the evening walk and let the pattern speak for itself."
SHARED_SYSTEM = "PERSONA + AUTHORITATIVE FACTS — the module's cached system block."


class FakeTable:
    """Dict-backed DDB double."""

    def __init__(self):
        self.items: dict = {}
        self.writes: list = []

    def put_item(self, Item):
        self.writes.append(Item)
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        row = self.items.setdefault((Key["pk"], Key["sk"]), dict(Key))
        row["analysis"] = ExpressionAttributeValues[":a"]

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, **kwargs):
        return {"Items": []}


class FakeModel:
    """Queued replies in order (the last repeats); records every request body verbatim
    so a test can inspect exactly what `system` block (if any) each call carried."""

    def __init__(self, *replies):
        self.replies = list(replies) or [""]
        self.requests: list = []

    def __call__(self, req, timeout=None):
        self.requests.append(json.loads(req.data.decode()))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return {"content": [{"type": "text", "text": reply}]}


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(az, "table", t)
    return t


@pytest.fixture
def model(monkeypatch):
    def _install(*replies):
        m = FakeModel(*replies)
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", m)
        monkeypatch.setattr(az, "_get_api_key", lambda: "sk-test")
        return m

    return _install


@pytest.fixture(autouse=True)
def hermetic(monkeypatch, table):
    """No canonical-facts read, no persona/intelligence side trips, no presence I/O —
    same posture as `test_analyzer_gate_all_paths_2421.py`'s `hermetic` fixture."""
    az._CANON_FACTS_CACHE.clear()
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: {})
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: {})
    monkeypatch.setattr(az, "_presence_block", lambda: "")
    monkeypatch.setattr(az, "gather_data_for_expert", lambda key: {})
    monkeypatch.setattr(az, "build_prompt", lambda *a, **k: "PROMPT")
    monkeypatch.setattr(az, "_load_prior_analysis", lambda key: ("", ""))
    yield
    az._CANON_FACTS_CACHE.clear()


class TestRegenReusesSharedSystem:
    def test_the_regen_call_carries_the_same_system_block_as_the_primary_call(self, table, model):
        """A fabricated number in the first draft forces exactly one corrective rewrite
        (#2391's regen_once). Both requests must carry the IDENTICAL system block."""
        m = model(FABRICATED, CLEAN)
        out = az.generate_and_cache("sleep", shared_system=SHARED_SYSTEM)

        assert out == CLEAN, "the regen must self-correct and publish"
        assert len(m.requests) >= 2, "the gate must attempt exactly one corrective rewrite before this assertion is meaningful"

        primary_system = m.requests[0].get("system")
        regen_system = m.requests[1].get("system")
        assert primary_system, "precondition: the primary call must itself carry a system block"
        assert regen_system == primary_system, (
            "#3170: the regen call must reuse the primary call's shared_system verbatim — "
            f"primary={primary_system!r} regen={regen_system!r}"
        )

    def test_no_shared_system_means_neither_call_carries_one(self, table, model):
        """Control: with no shared_system supplied at all, parity still holds by both
        calls agreeing to omit `system` — never one carrying a stale/different block."""
        m = model(FABRICATED, CLEAN)
        out = az.generate_and_cache("sleep")

        assert out == CLEAN
        assert len(m.requests) >= 2
        assert "system" not in m.requests[0]
        assert "system" not in m.requests[1]
