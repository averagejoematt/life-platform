"""#2888 — the input-token diet: prompt-cache floors, byte-stability, and the no-op dead-man.

What these tests defend, in order of how expensive the bug was:

  1. The coach-v2 generation call passes `system=` at all. It used to concatenate
     the system prompt into the user turn, which left `body["system"]` unset, which
     meant the ADR-049 auto-wrap had nothing to wrap — the seven largest calls in
     the daily brief carried no cache_control whatsoever. Measured live
     (LifePlatform/AI, trailing 30d, 2026-08-24): 4,673,440 uncached input tokens,
     0 cache-read AND 0 cache-write. The zero on the WRITE side is the tell.

  2. The cached prefix is byte-stable across two consecutive same-day calls. That
     is the cache's actual requirement — a prefix match, not a semantic one — and
     it is what a stray timestamp, an unsorted json.dumps, or an item-count
     interpolation silently breaks.

  3. The day-varying payload sits AFTER every cache_control block.

  4. A cache_control on a prefix below the model's floor is reported rather than
     silently doing nothing forever.
"""

import json
import re
from pathlib import Path

import pytest
from ai import prompt_cache

# ── 1. the registry ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model_id,expected",
    [
        # The number this whole issue turned on: Haiku 4.5 needs FOUR TIMES the
        # stable prefix Sonnet does, and ADR-049 routes structured tasks to Haiku.
        ("us.anthropic.claude-haiku-4-5-20251001-v1:0", 4096),
        ("claude-haiku-4-5-20251001", 4096),
        ("us.anthropic.claude-sonnet-4-6", 1024),
        ("claude-sonnet-4-6", 1024),
        ("claude-opus-4-6", 4096),
    ],
)
def test_cache_floor_matches_anthropic_documented_minimums(model_id, expected):
    assert prompt_cache.cache_floor(model_id) == expected


def test_unknown_model_gets_the_conservative_floor():
    """A model nobody has checked must never be ASSUMED cacheable — an optimistic
    default would reintroduce exactly the silent no-op this module exists to end."""
    assert prompt_cache.cache_floor("claude-something-unreleased") == 4096
    assert prompt_cache.cache_floor(None) == 4096


def test_haiku_floor_is_higher_than_sonnet_floor():
    """The counter-intuitive fact that makes the cheap tier the hard one to cache.
    If a future model table update inverts this, the module docstring's whole
    argument needs re-reading — so pin it."""
    assert prompt_cache.cache_floor("claude-haiku-4-5") > prompt_cache.cache_floor("claude-sonnet-4-6")


# ── 2. request introspection (what the dead-man keys on) ────────────────────


def test_requests_caching_detects_a_system_block_breakpoint():
    body = {"system": [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}], "messages": []}
    assert prompt_cache.requests_caching(body) is True


def test_requests_caching_detects_a_user_turn_breakpoint():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "b"}],
            }
        ]
    }
    assert prompt_cache.requests_caching(body) is True


def test_requests_caching_is_false_when_nothing_asked():
    """A request that never asked for caching is not a defect — the dead-man must
    stay silent for it, or PromptCacheNoOp becomes noise nobody reads."""
    assert prompt_cache.requests_caching({"system": "plain string", "messages": [{"role": "user", "content": "hi"}]}) is False
    assert prompt_cache.requests_caching({}) is False
    assert prompt_cache.requests_caching(None) is False


def test_cacheable_prefix_text_stops_at_the_last_breakpoint():
    """Only the bytes up to the final cache_control have to clear the floor —
    that is what the WARN line reports, so it has to measure the right span."""
    body = {
        "system": [{"type": "text", "text": "AAA", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "BBB"}]}],
    }
    assert prompt_cache.cacheable_prefix_text(body) == "AAA"


def test_cacheable_prefix_text_spans_system_then_messages_in_render_order():
    body = {
        "system": [{"type": "text", "text": "SYS"}],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "SHARED", "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "VOLATILE"},
                ],
            }
        ],
    }
    # tools -> system -> messages; the breakpoint is on SHARED, so SYS+SHARED is the prefix.
    assert prompt_cache.cacheable_prefix_text(body) == "SYSSHARED"
    assert "VOLATILE" not in prompt_cache.cacheable_prefix_text(body)


# ── 3. the assembly helper ──────────────────────────────────────────────────


def test_cached_prefix_blocks_puts_the_breakpoint_on_the_stable_half_only():
    blocks = prompt_cache.cached_prefix_blocks("stable bytes", "day-varying bytes")
    assert len(blocks) == 2
    assert blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    assert "cache_control" not in blocks[1], "the volatile block must never carry a breakpoint"


def test_cached_prefix_blocks_rejects_an_empty_stable_prefix():
    """A breakpoint on nothing can never engage; asking for one is a caller bug."""
    with pytest.raises(ValueError, match="must be non-empty"):
        prompt_cache.cached_prefix_blocks("   ", "volatile")


def test_cached_prefix_blocks_omits_an_empty_volatile_block():
    assert len(prompt_cache.cached_prefix_blocks("stable", "")) == 1


# ── 4. THE byte-stability property (the cache's actual requirement) ─────────


def _assemble(day_payload, *, items):
    """Stand-in for a feature's prompt assembly: a stable rubric plus a payload
    that changes every day. Mirrors the real shape — a static instruction block
    followed by per-run data."""
    stable = "RUBRIC: judge the payload below.\n" * 40
    volatile = f"ITEMS ({items}):\n{json.dumps(day_payload, sort_keys=True)}"
    return prompt_cache.cached_prefix_blocks(stable, volatile)


def test_stable_prefix_is_byte_identical_across_two_consecutive_same_day_calls():
    """The cache's requirement is a BYTE match. Two calls in the same run must
    produce an identical cached block even though their payloads differ."""
    a = _assemble({"weight": 214.2, "as_of": "2026-08-24"}, items=5)
    b = _assemble({"weight": 213.8, "as_of": "2026-08-24"}, items=6)
    assert a[0]["text"] == b[0]["text"]
    assert a[0]["text"].encode() == b[0]["text"].encode()
    # ...and the volatile halves genuinely differ, or the test proves nothing.
    assert a[1]["text"] != b[1]["text"]


def test_day_varying_payload_sits_after_every_cache_control_block():
    """The silent-invalidator check: no bytes that change per call may appear at
    or before a breakpoint."""
    blocks = _assemble({"weight": 214.2, "as_of": "2026-08-24"}, items=5)
    cut = max(i for i, b in enumerate(blocks) if b.get("cache_control"))
    prefix = "".join(b["text"] for b in blocks[: cut + 1])
    for varying in ("214.2", "2026-08-24", "ITEMS (5)"):
        assert varying not in prefix, f"day-varying {varying!r} leaked into the cached prefix"


# ── 5. the coach-v2 regression this issue actually fixed ───────────────────

_AI_CALLS = Path(__file__).resolve().parents[1] / "lambdas" / "ai" / "ai_calls.py"


def test_coach_v2_never_concatenates_the_system_prompt_into_the_user_turn():
    """The #2888 regression guard, asserted on the real shipped source.

    `call_anthropic(system_prompt + "\\n\\n" + user_message_full, ...)` leaves
    `body["system"]` unset, so ADR-049's auto-wrap produces no cache_control and
    the largest calls in the brief bill full-price input forever. Any
    reintroduction of that concatenation — in the base call or in any of the four
    regen paths — fails here.
    """
    src = _AI_CALLS.read_text()
    offenders = re.findall(r"call_anthropic\(\s*system_prompt\s*\+", src)
    assert not offenders, f"{len(offenders)} call_anthropic site(s) concatenate system_prompt into the user turn (#2888)"


def test_every_coach_v2_generation_call_passes_system_explicitly():
    """All five coach-v2 call sites (base + 4 regens) must hand `system_prompt` to
    the `system=` parameter, which is what `cache_system=True` then wraps."""
    src = _AI_CALLS.read_text()
    # The regen paths keep their correction/note in the user turn; every one of
    # them still has to name system_prompt as the system argument.
    assert src.count("system=system_prompt") == 5, (
        "expected exactly 5 coach-v2 call sites passing system=system_prompt "
        "(base generation + grounding, quality-gate, presence-ack and self-graded-verdict regens)"
    )


def test_corrections_stay_outside_the_cached_prefix():
    """A correction/gate note is dynamic by construction. If one ever migrated into
    `system_prompt` it would bust the prefix on every regen — the exact 90%-discount
    loss #1697 called out."""
    src = _AI_CALLS.read_text()
    for dynamic in ("_corr", "_note", "correction_prompt("):
        assert f"system=system_prompt + {dynamic}" not in src
        assert f'system=system_prompt + "\\n\\n" + {dynamic}' not in src


# ── 6. the 2026-08-24 call-site sweep (#2888's second wave) ─────────────────
#
# The first wave fixed the coach-v2 concat bug. Re-running the census over every
# production Bedrock call site turned up three more decisions, each of which is a
# fact about a MEASURED prefix size and a MEASURED call frequency — so each gets a
# test rather than a comment, because both facts are the kind that drift silently.

_EMAILS = Path(__file__).resolve().parents[1] / "lambdas" / "emails"


def test_the_panelcast_intro_carries_a_real_breakpoint():
    """WIRED. ~2,080 tok of show-bible prompt on Sonnet 4.6 (floor 1,024), rebuilt
    byte-identically on each of up to 3 `_QA_MAX_ATTEMPTS` generations inside ONE
    invocation — so unlike a once-a-week call, a cache READ is actually reachable.

    It goes straight to `bedrock_client.invoke`, which (unlike `call_anthropic`)
    does NOT auto-wrap: a plain-string `system` there has never cached, and never
    would have, without anything anywhere reporting it.
    """
    src = (_EMAILS / "panelcast_scripts.py").read_text()
    assert '"system": [prompt_cache.cached_block(system)]' in src, "the Episode-0 writer must carry an explicit cache breakpoint (#2888)"


def test_the_panelcast_weekly_writer_is_deliberately_not_cached():
    """NOT WIRED, on purpose. Its prefix would clear Sonnet's floor, but
    `_build_weekly_script` is called ONCE per weekly invocation (no attempt loop),
    so a breakpoint buys a 1.25x write premium against a read that cannot happen.
    Caching it would be a third instance of the D-01 inverse, not a saving."""
    src = (_EMAILS / "panelcast_scripts.py").read_text()
    assert '"model": deps["writer_model"], "max_tokens": 3500, "system": system' in src
    assert "#2888: deliberately NOT cached" in src, "the decision must stay explained where the next reader will look"


@pytest.mark.parametrize("module", ["monday_compass_lambda.py", "weekly_plate_lambda.py"])
def test_the_weekly_single_call_emails_turn_caching_off(module):
    """UN-WIRED. Both clear Sonnet's floor, so the ADR-049 auto-wrap engaged and
    paid the write premium — and both make exactly ONE Bedrock call per weekly run,
    seven days apart, past even a 1h TTL. Same measured inverse as D-01 (0 reads /
    10K writes per 14d) and state-of-matthew (24,159 writes / 0 reads)."""
    src = (_EMAILS / module).read_text()
    assert "cache_system=False" in src, f"{module} pays a cache write it can never read (#2888)"


def test_the_coach_v2_system_prompt_clears_the_sonnet_floor():
    """The precondition for the telemetry half of #2888: `AnthropicCacheWriteTokens`
    is emitted by `bedrock_client` only when the wire actually reports a nonzero
    count, so `LambdaFunction=daily-brief` can only appear once a coach-v2 prefix is
    big enough to engage. The static skeleton alone (before the facts, recall,
    memory and few-shot blocks are interpolated) is ~4.7K chars.

    NOTE, stated rather than overclaimed: this makes the WRITE reachable. Cross-DAY
    reads are not — `_facts_block` and friends sit inside the system slot and change
    daily. The read side is repaid only by an in-invocation gate regen.
    """
    src = _AI_CALLS.read_text()
    start = src.index('system_prompt = f"""You are {voice_spec[')
    end = src.index('"""', src.index("Write 2-4 paragraphs", start))
    skeleton = re.sub(r"\{[^{}]*\}", "", src[start:end])
    assert prompt_cache.clears_floor(skeleton, "us.anthropic.claude-sonnet-4-6"), (
        f"the coach-v2 system prompt skeleton is ~{prompt_cache.estimate_tokens(skeleton)} tok against a "
        f"{prompt_cache.cache_floor('us.anthropic.claude-sonnet-4-6')} floor — below it, daily-brief can never "
        "appear in the LifePlatform/AI cache-token series at all"
    )
