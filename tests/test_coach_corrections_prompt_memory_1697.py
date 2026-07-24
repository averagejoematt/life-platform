"""test_coach_corrections_prompt_memory_1697.py — S5 (#1697, epic #1687).

The first live CONSUMER of the coach-corrections ledger: each coach's generation
prompt gains its OWN "prior corrections — do not repeat" block. This file pins the
`ai_calls` wiring (the ledger-side read/scope/render is pinned in
`tests/test_coach_corrections.py`):

  1. CACHE BOUNDARY (COST-OPT-2 / ADR-049): the dynamic corrections block rides the
     USER portion of the model call, never the cached system prefix — so prompt
     caching still engages (the system block keeps its `cache_control`) with the
     block attached. `test_corrections_ride_user_message_not_cached_system`.

  2. SEEDED "315 lbs" ROW CHANGES THE PROMPT for the relevant coach (the #1697
     acceptance): `test_seeded_stale_baseline_correction_changes_metabolic_prompt`
     + `test_corrections_are_scoped_per_coach_not_global`.

  3. FAIL-SOFT: a corrections lookup can never break a generation.

Fully offline — no Bedrock/AWS: `bedrock_client.invoke` is monkeypatched and the
ledger table is the in-memory `FakeDdbTable`.

Run with:   python3 -m pytest tests/test_coach_corrections_prompt_memory_1697.py -v
"""

import json
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import ai_calls  # noqa: E402
import bedrock_client  # noqa: E402
import coach_corrections as cc  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402


def _seed_correction(coach, *, cid, cls="stale-baseline", text, surface="coach_brief", date="2026-07-22"):
    return cc.build_correction_item(
        {"surface": surface, "coach": coach},
        text,
        cls,
        now=datetime.fromisoformat(f"{date}T12:00:00+00:00").astimezone(timezone.utc),
        correction_id=cid,
    )


# ── 1. Cache boundary ────────────────────────────────────────────────────────
def test_corrections_ride_user_message_not_cached_system(monkeypatch):
    """The corrections block lands in the dynamic USER message; the cached system
    prefix is unchanged and keeps its `cache_control` (caching still engages)."""
    captured = {}

    def _fake_invoke(body, model_name=None):
        captured["body"] = body
        return {"content": [{"type": "text", "text": "ok"}], "usage": {}}

    monkeypatch.setattr(bedrock_client, "invoke", _fake_invoke)

    corrections_block = cc.render_corrections_block(
        [{"error_class": "stale-baseline", "correction_text": "Stop citing 315 lbs as current — the baseline is 321.4."}]
    )
    assert "315" in corrections_block  # guard: the block really carries the corrected figure

    system_prefix = "You are Dr. Sarah Chen, metabolic specialist. " + "voice rules " * 400  # the cached prefix
    user_message = "TODAY'S DATA: weight 321.4 lbs\n\n" + corrections_block

    ai_calls.call_anthropic(user_message, system=system_prefix, cache_system=True, max_tokens=10)

    body = captured["body"]
    # Caching still engages: the system block is a cache_control-tagged content block.
    assert isinstance(body["system"], list)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    # The dynamic corrections figure is NOT inside the cached system prefix …
    assert "315" not in json.dumps(body["system"])
    # … it is in the dynamic user message the model receives.
    assert "315" in body["messages"][0]["content"]


def test_build_system_block_still_tags_cache_control():
    """Sanity: the cache mechanism itself (COST-OPT-2) is intact — a system string
    with caching on becomes a `cache_control: ephemeral` content block."""
    block = ai_calls._build_system_block("some system prompt", cache_system=True)
    assert block == [{"type": "text", "text": "some system prompt", "cache_control": {"type": "ephemeral"}}]


# ── 2. Seeded "315 lbs" row changes the prompt (scoped per coach) ─────────────
def test_seeded_stale_baseline_correction_changes_metabolic_prompt():
    """The seeded '315 lbs' stale-baseline row demonstrably changes the next
    generation's prompt for the coach it targets."""
    table = FakeDdbTable(
        rows=[
            _seed_correction(
                "metabolic_coach",
                cid="a1b2c3d4",
                text="You cited 315 lbs as the current baseline — it's stale (cycle-9). Baseline is 321.4 as of genesis.",
            )
        ]
    )
    block = ai_calls._coach_corrections_block("metabolic_coach", surface="coach_brief", table=table)
    assert block  # non-empty → the prompt changes for this coach
    assert "315 lbs" in block
    assert "[stale-baseline]" in block

    # Concretely: appending the block changes the assembled user prompt.
    base_user_message = "TODAY'S DATA: weight 321.4 lbs"
    without = base_user_message
    with_corrections = base_user_message + "\n\n" + block
    assert with_corrections != without
    assert "315 lbs" in with_corrections and "315 lbs" not in without


def test_corrections_are_scoped_per_coach_not_global():
    """Each coach carries only its OWN open corrections — never the global list."""
    table = FakeDdbTable(
        rows=[
            _seed_correction("metabolic_coach", cid="a1b2c3d4", text="315 lbs baseline is stale"),
            _seed_correction("sleep_coach", cid="e5f6a7b8", cls="ungrounded-behavioral", text="no 8h streak claim"),
        ]
    )
    metabolic = ai_calls._coach_corrections_block("metabolic_coach", surface="coach_brief", table=table)
    assert "315 lbs" in metabolic
    assert "8h streak" not in metabolic  # the sleep coach's correction must not leak in

    sleep = ai_calls._coach_corrections_block("sleep_coach", surface="coach_brief", table=table)
    assert "8h streak" in sleep
    assert "315 lbs" not in sleep

    # A coach with no corrections gets nothing to inject.
    assert ai_calls._coach_corrections_block("mind_coach", surface="coach_brief", table=table) == ""


# ── 3. Fail-soft ─────────────────────────────────────────────────────────────
def test_coach_corrections_block_is_fail_soft_on_table_error():
    class _BoomTable:
        def query(self, **kwargs):
            raise RuntimeError("ddb down")

    assert ai_calls._coach_corrections_block("metabolic_coach", surface="coach_brief", table=_BoomTable()) == ""
