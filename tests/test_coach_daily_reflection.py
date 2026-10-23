"""tests/test_coach_daily_reflection.py — the daily moves job's guardrails (offline).

Verifies the PG-10 budget self-skip: at tier >= 2 the batch returns without
touching Bedrock or S3. And #4583 (owner ruling 2026-10-23): the CC-08 per-coach
reflection is RETIRED — the job runs the board's moves and nothing else, so it makes
no reflection call and writes nothing to generated/coach_daily.json.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

from ai import budget_guard  # noqa: E402
from compute import coach_daily_reflection_lambda as writer  # noqa: E402


def test_self_skips_at_tier_2(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    out = writer.lambda_handler({}, None)
    assert out == {"skipped": True, "tier": 2}


def test_self_skips_at_tier_3(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
    out = writer.lambda_handler({}, None)
    assert out.get("skipped") is True


def test_constants_sane():
    assert writer.SKIP_TIER == 2


class _S3:
    def __init__(self):
        self.puts = []

    def get_object(self, **kw):
        raise KeyError(kw.get("Key"))

    def put_object(self, **kw):
        self.puts.append(kw["Key"])


def _run_handler(monkeypatch):
    """The handler at tier 0 with every AWS seam faked; returns (result, s3, run_calls)."""
    from coach import coach_moves, persona_registry

    s3 = _S3()
    calls = []
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(writer.boto3, "client", lambda name, **kw: s3)
    monkeypatch.setattr(writer.boto3, "resource", lambda name, **kw: type("R", (), {"Table": lambda self, n: object()})())
    monkeypatch.setattr(persona_registry, "load_registry", lambda s3_, bucket: {"personas": {}})
    monkeypatch.setattr(coach_moves, "run", lambda table, **kw: calls.append(kw) or {"lines": 1})
    monkeypatch.setattr(writer, "pacific_today", lambda: "2026-10-23")
    return writer.lambda_handler({}, None), s3, calls


def test_the_retired_reflection_is_neither_generated_nor_published(monkeypatch):
    """#4583: the moves run once and are the job's whole output — no reflection loop,
    no generated/coach_daily.json write. Mutation control: restore the reflection
    loop's S3 put and `s3.puts` is non-empty, which reds the second assert."""
    from ai import bedrock_client

    monkeypatch.setattr(bedrock_client, "invoke", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no reflection call")))
    out, s3, calls = _run_handler(monkeypatch)
    assert out == {"moves": {"lines": 1}}
    assert s3.puts == [], s3.puts
    assert len(calls) == 1 and calls[0]["today"] == "2026-10-23"


def test_the_reflection_generation_seams_are_gone():
    """The prompt, gate, generator and #2889 reuse slot left with the surface."""
    for name in ("_SYSTEM_RULES", "_generate", "_accepts", "_gather_facts", "_reuse_or_none", "_store", "OUTPUT_KEY", "MODEL"):
        assert not hasattr(writer, name), name
