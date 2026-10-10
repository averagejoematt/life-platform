"""
prompt_cache.py — the per-model minimum-cacheable-prefix registry, and the
assembly helper that keeps a cached prefix byte-stable (#2888, epic #2801).

WHY THIS EXISTS
---------------
Anthropic prompt caching is a **prefix match with a model-dependent minimum**.
A `cache_control` block placed on a prefix shorter than that minimum is accepted
by the API and then does **nothing**: no error, no warning, no beta-header
complaint — `cache_creation_input_tokens` simply stays 0 forever. The failure is
invisible at the call site and invisible in the logs. The only place it shows up
is the bill.

That is not hypothetical here. Measured live on 2026-08-24 (`LifePlatform/AI`,
trailing 30d), every one of these features wraps its system prompt in
`cache_control` and has **0 cache-write and 0 cache-read tokens** — the wrapper
has never once cached anything:

    feature                     uncached in    cache_read  cache_write
    daily-brief                   4,673,440             0            0
    ai-expert-analyzer            2,410,788             0            0
    life-platform-qa-smoke        2,037,117             0            0
    coach-quality-gate            1,079,357             0            0
    coach-state-updater             815,612             0            0

The cause is one number. **`claude-haiku-4-5` requires a 4,096-token stable
prefix — the highest floor of any model the platform runs, 4x Sonnet 4.6's
1,024.** ADR-049 routes structured tasks to Haiku because it is cheap per token;
the unstated consequence is that the platform's cheapest tier is also the one
that is hardest to cache, and three of the features above have a *whole prompt*
smaller than the floor:

    ai-expert-analyzer  shared_system   3,652-5,077 chars  ~1,000-1,400 tok
    reader_truth_qa     rubric H+F              6,657 chars  ~1,849 tok
    coach-quality-gate  system prompt           3,033 chars  ~842 tok

The counter-example proves the mechanism rather than the theory:
`coach_narrative_orchestrator` is also on Haiku and *does* cache (27.4% hit rate,
862K write / 1.12M read tokens over the same window) because its shared block is
~28K tokens. Its own docstring already names the reason — "the shared block is
also what pushes the cached prefix over Haiku's minimum cacheable length (the old
system-only block was too small to cache at all)". That knowledge existed in one
module and nowhere else; this module is where it lives now.

WHAT THIS MODULE DOES
---------------------
Two things, deliberately separated:

  * `cache_floor()` / `clears_floor()` — the registry. Advisory, pure, and
    unit-testable: what the floor IS per model, and whether a candidate prefix
    is big enough to be worth a `cache_control` at all.
  * `cached_prefix_blocks()` — the assembly helper. Builds `[stable, volatile]`
    content blocks with the breakpoint on the stable half, and refuses to build
    a shape where day-varying bytes land *inside* the cached prefix.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not gate `cache_control` on the estimated token count. Estimation is a
heuristic (`estimate_tokens` is chars/3.6); gating on it would trade a silent
no-op for a silent *skip*, which is strictly worse — a prefix we wrongly judged
too small would never get the chance to prove us wrong on the wire. Applying
`cache_control` to a sub-floor prefix costs nothing beyond what is already being
paid, so the helper applies it optimistically and lets **the wire** decide.

The ground truth is `bedrock_client._note_cache_noop()`, which compares what the
request ASKED for against what `usage` actually reported and emits
`PromptCacheNoOp` when a caller asked for caching and got none. That converts a
permanent invisible no-op into a metric — the dead-man this whole class of bug
needed (charter primitive 5). The registry below is what makes that metric
*actionable*: it tells you how far under the floor you are.

THE BYTE-STABILITY RULE
-----------------------
A cache hit needs the prefix to be byte-identical, not merely semantically
identical. Everything that varies within the cache's lifetime must sit AFTER the
last breakpoint. The usual culprits are not obvious — a day counter, a record
count, an f-string `{k}` for "how many items follow", `json.dumps` without
`sort_keys`, a `set` iteration order. `reader_truth_qa.build_prompt` interpolates
BOTH a batch size and a phase day-line into the very first line of its otherwise
static 6.2KB rubric, which would defeat caching even on a model whose floor it
cleared.

Reordering to put the stable half first is explicitly sanctioned (#2888): the
model must see the same *information*, not the same byte order.
"""

from __future__ import annotations

from typing import Any, Optional

# ── The registry ────────────────────────────────────────────────────────────
# Anthropic's documented minimum cacheable prefix, in tokens, keyed by a
# substring of the resolved model id (same matching discipline as
# bedrock_client._PRICES, so a `us.anthropic.claude-haiku-4-5-...` inference
# profile resolves correctly).
#
# These minimums are NOT monotonic across generations and are NOT
# platform-specific: they apply on Bedrock exactly as on the first-party API.
# An unknown model gets the most conservative (largest) floor so a new model can
# never be assumed cacheable without someone checking.
#
# #4778: the 5.5 generation (Haiku 5.5, Sonnet 5.5, Opus 5.5) sits on the 512 tier.
# Before these rows, `…-haiku-5-5` matched the generic "haiku" row (4,096) and
# `…-sonnet-5-5` matched "sonnet-5" (1,024) — both conservative, so nothing over-
# claimed caching, but a DECLINED decision made against those floors could never be
# flagged as stale once a caller moved: the floor the guard compared against was the
# old one. Haiku/Sonnet 5.5 at 512 are from the Bedrock model card (#4772/#4778), and
# Bedrock CountTokens REJECTS both 5.5 base ids ("The provided model doesn't support
# counting tokens", probed 2026-10-10) — so on these models the floor is wire-proven
# only by `usage.cache_creation_input_tokens` after a real move, i.e. by the
# `AnthropicCacheReadTokens` / `PromptCacheNoOp` series, never by CountTokens.
MIN_CACHEABLE_PREFIX_TOKENS: dict[str, int] = {
    "haiku-5-5": 512,
    "haiku-4-5": 4096,
    "haiku": 4096,
    "sonnet-5-5": 512,
    "sonnet-4-6": 1024,
    "sonnet-5": 1024,
    "sonnet": 1024,
    "opus-4-6": 4096,
    "opus-5-5": 512,
    "opus-5": 512,
    "opus": 512,
    "fable": 512,
}

# Used when no key matches: assume the worst so an unrecognised model is never
# silently assumed cacheable.
_CONSERVATIVE_FLOOR = 4096

# Average characters per token for English prose with embedded JSON. Deliberately
# on the LOW side (a token is usually ~3.6-4 chars here), so `estimate_tokens`
# over-estimates slightly and `clears_floor` is the conservative direction for a
# test assertion: a block this says clears the floor comfortably does.
_CHARS_PER_TOKEN = 3.6


# ── The per-caller decision register (#3085) ────────────────────────────────
# `cache_control` on a call site is NOT evidence that the call site caches. The
# registry above says what the floor IS; this one says, per caller, what we
# DECIDED about that floor and on what measurement — so a reader at a call site
# carrying `cache_control` can tell "this caches" from "this was measured and
# deliberately left un-caching" without re-running the numbers.
#
# `prefix_tokens` is a WIRE measurement, not `estimate_tokens`: Bedrock
# `CountTokens` against the BASE id of the measured model (`anthropic.claude-…`;
# CountTokens rejects the `us.` inference-profile id itself), counting a request
# with the system block minus the same request without it. Re-measure with that
# method if you change a prompt. `measured_on` is the floor-registry FAMILY key the
# measurement holds for ("haiku-4-5", "sonnet-4-6") — a family shares a tokenizer,
# and a family key keeps model-name literals in bedrock_client / model_defaults
# only (#4275). CountTokens does NOT support the 5.5 models (probed 2026-10-10); a
# caller that moves to one is measured from the `usage` block of its first real
# call instead (`input_tokens` + `cache_creation_input_tokens` with and without the
# system block), and `measured_on` becomes the 5.5 family key.
#
# #4778 — THE MODEL IS DERIVED, NOT RECORDED. Until #4778 each entry carried a
# hand-written `model` string, and the floor check ran against THAT — so the day a
# caller moved to a 512-floor 5.5 model through its env var, the register would have
# kept checking it against the 4,096 Haiku 4.5 floor and stayed green on a decision
# whose premise had just dissolved. Each entry now names HOW its caller resolves a
# model (`model_env`, falling back to `model_default` — the same
# `os.environ.get(env, default)` the caller module does) and which model the
# measurement was taken ON (`measured_on`). `resolved_model()` is the model the
# caller actually runs on; `decision_drift()` reports every way a decision has
# stopped describing it:
#   * the caller now resolves to a different model family than `measured_on` —
#     re-measure on the new model (tokenizers differ: Haiku 5.5 is reported ~30%
#     heavier for the same text) and re-decide against its floor;
#   * the prompt clears the resolved model's floor but the entry says declined, or
#     the reverse;
#   * the entry says engaged but fewer than 2 calls land inside one cache TTL
#     (`calls_within_ttl`), so every write is a premium nothing reads.
# `tests/test_prompt_cache_floor_derivation_4778.py` holds `model_env` /
# `model_default` to the caller module AND to the deployed env the CDK stack sets.
#
# The LIVE counterpart is `PromptCacheNoOp` (#2888): this register is the
# intent, that metric is the outcome. `tests/test_prompt_cache_decisions_3085.py`
# holds the two consistent.
_HAIKU_4_5 = "claude-haiku-4-5-20251001"

CACHING_DECISIONS: dict[str, dict[str, Any]] = {
    "coach-quality-gate": {
        "engaged": False,
        "model_env": "AI_MODEL_HAIKU",
        "model_default": _HAIKU_4_5,
        "caller": "coach/coach_quality_gate.py",
        "cdk_stack": "compute_stack.py",
        "measured_on": "haiku-4-5",
        "prefix_tokens": 814,
        "calls_within_ttl": None,
        "decided": "2026-08-27",
        "issue": 3085,
        "why": (
            "814 tok against Haiku 4.5's 4,096 floor — needs 5.03x growth to cache at all. "
            "The largest legitimate prefix available is 2,238 tok (the whole of "
            "config/coaches/_shared_standard.json hoisted in), 55% of the floor, so reaching "
            "it needs ~1,858 tok of PURE PADDING inside a quality-JUDGE prompt. Measured prize "
            "for padding both callers to the floor: $0.29/mo; the ceiling if the floor did not "
            "exist at all is $0.69/mo (0.32% of the $215 ADR-133 ceiling). Not worth degrading "
            "the judge for. Re-confirmed 2026-10-10 (#4778): 814 tok on the wire again. On a "
            "512-floor 5.5 model it CLEARS — `decision_drift` reds the day this caller moves."
        ),
    },
    "coach-state-updater": {
        "engaged": False,
        "model_env": "AI_MODEL_HAIKU",
        "model_default": _HAIKU_4_5,
        "caller": "coach/coach_state_updater.py",
        "cdk_stack": "compute_stack.py",
        "measured_on": "haiku-4-5",
        "prefix_tokens": 2039,
        "calls_within_ttl": None,
        "decided": "2026-10-10",
        "issue": 4778,
        "why": (
            "2,039 tok on the wire (re-measured 2026-10-10, #4778; 1,783 at #3085 on 2026-08-27 — "
            "the extraction prompt grew on its merits) against Haiku 4.5's 4,096 floor — needs "
            "2.01x growth. Its user turn is the per-coach narrative (volatile by construction) and "
            "the metric allow-list is already inside the system prompt, so there is no run-"
            "invariant block left to hoist: the remaining ~2,057 tok would be padding. Same "
            "$0.29/mo joint prize as the gate above. On a 512-floor 5.5 model it clears 4x over."
        ),
    },
    # #4778 acceptance 2: the daily brief's shared system prefix, recorded either way.
    # Built once per brief by `ai_calls.daily_brief_shared_system` and passed with
    # `cache_system=False` to the four coach calls (BoD, training+nutrition, journal,
    # TL;DR) — all in ONE invocation, inside one 5m TTL, so the call-count half of the
    # re-enable test (>=2 within the TTL) is already met. SIZE is the binding half.
    "daily-brief": {
        "engaged": False,
        "model_env": "AI_MODEL",
        "model_default": "NARRATIVE_MODEL",  # ai.model_defaults.NARRATIVE_MODEL, resolved below
        "caller": "ai/ai_transport.py",
        "cdk_stack": "email_stack.py",
        "measured_on": "sonnet-4-6",
        "prefix_tokens": 530,
        "calls_within_ttl": 4,
        "decided": "2026-10-10",
        "issue": 4778,
        "why": (
            "530 tok on the wire for the minimal shape (phase block + profile snapshot + rules; "
            "Bedrock CountTokens, Sonnet 4.6, 2026-10-10), ~784 est. with the presence and "
            "journal-signal blocks a real day adds — under Sonnet 4.6's 1,024 floor either way, "
            "so the marker would be silently ignored. 4 calls inside one TTL satisfies the "
            "call-count criterion; size does not. NOTE the prefix carries day-varying bytes "
            "(date, day-grade, journal signals), so only in-invocation reuse is ever available — "
            "#2888 priced that prize at ~$0.8-1.1/mo. On a 512-floor 5.5 model even the minimal "
            "shape clears: re-enable then, after re-measuring on that model."
        ),
    },
}


def _resolve_default(default: str) -> str:
    """`model_default` is a literal model name, or the sentinel "NARRATIVE_MODEL" for a
    caller whose fallback is `ai.model_defaults.NARRATIVE_MODEL` — kept symbolic so the
    register cannot drift from that one constant (#4275)."""
    if default == "NARRATIVE_MODEL":
        from ai.model_defaults import NARRATIVE_MODEL

        return NARRATIVE_MODEL
    return default


def resolved_model(fn: str, environ: Optional[dict[str, str]] = None) -> str:
    """The model `fn` actually runs on under `environ` (the Lambda's env vars).

    Same resolution the caller module performs: `environ[model_env]` if set and
    non-empty, else `model_default`. Pass the deployed environment; `None` means
    "no override", i.e. the default.
    """
    entry = CACHING_DECISIONS[fn]
    env = environ or {}
    return env.get(entry["model_env"]) or _resolve_default(entry["model_default"])


def model_family(model_id: Optional[str]) -> Optional[str]:
    """The floor-registry key `model_id` resolves to (longest substring match), or None.

    Two ids in the same family share a floor AND a tokenizer, so a measurement taken on
    one holds for the other (`us.anthropic.claude-haiku-4-5-20251001-v1:0` and
    `claude-haiku-4-5-20251001` are both "haiku-4-5"). Different families need a fresh
    measurement even when the floors happen to match.
    """
    mid = (model_id or "").lower()
    for key in sorted(MIN_CACHEABLE_PREFIX_TOKENS, key=len, reverse=True):
        if key in mid:
            return key
    return None


def decision_drift(fn: str, prompt: str, environ: Optional[dict[str, str]] = None) -> list[str]:
    """Every way `CACHING_DECISIONS[fn]` has stopped describing the caller (#4778).

    Empty list == the decision still holds for the model the caller resolves to under
    `environ`. Pure: no I/O, so the same check runs in CI against the CDK-derived
    environment and against a hypothetical one ("what if this caller moved to 5.5?").
    """
    entry = CACHING_DECISIONS[fn]
    model = resolved_model(fn, environ)
    floor = cache_floor(model)
    problems: list[str] = []
    measured_family, live_family = model_family(entry["measured_on"]), model_family(model)
    if measured_family != live_family:
        problems.append(
            f"{fn}: resolves to {model} ({live_family}, {floor} tok floor) but prefix_tokens was measured on "
            f"{entry['measured_on']} ({measured_family}) — re-measure the prefix on the wire against the new model "
            "and re-decide `engaged` against its floor (#4778)"
        )
    clears = clears_floor(prompt, model)
    if clears is not entry["engaged"]:
        est = estimate_tokens(prompt)
        problems.append(
            f"{fn}: recorded engaged={entry['engaged']} but the prefix is ~{est} tok against the {floor} tok floor of "
            f"{model} — "
            + (
                "a marker below the floor is silently ignored and cache reads stay 0 forever (#3085)"
                if entry["engaged"]
                else "it now clears, so the 'too small to cache' rationale no longer holds — re-decide it (#4778)"
            )
        )
    calls = entry.get("calls_within_ttl")
    if entry["engaged"] and (calls is None or calls < 2):
        problems.append(
            f"{fn}: engaged with calls_within_ttl={calls!r} — a cache write needs >=2 calls inside one TTL to be read "
            "at all; record the measured count (#4778)"
        )
    return problems


def cache_floor(model_id: Optional[str]) -> int:
    """The minimum cacheable prefix, in tokens, for `model_id`.

    Matching is by substring, longest key first, so `haiku-4-5` wins over the
    generic `haiku` fallback. An unrecognised model returns the conservative
    4,096 rather than an optimistic default — see the module docstring.
    """
    family = model_family(model_id)
    return MIN_CACHEABLE_PREFIX_TOKENS[family] if family else _CONSERVATIVE_FLOOR


def estimate_tokens(text: str) -> int:
    """Rough token count for `text`. ADVISORY ONLY — never gate billing or
    routing on this; the wire is the source of truth (see the module docstring).
    """
    return int(len(text or "") / _CHARS_PER_TOKEN)


def clears_floor(text: str, model_id: Optional[str]) -> bool:
    """Would a `cache_control` block on `text` plausibly engage on `model_id`?

    Advisory. Used by tests to assert that a feature's stable prefix is actually
    big enough to be worth caching, so a prefix that shrinks back under the floor
    fails a test instead of silently reverting to full-price input.
    """
    return estimate_tokens(text) >= cache_floor(model_id)


def cached_block(text: str, *, ttl: str = "5m") -> dict[str, Any]:
    """One Anthropic content block carrying `text`, marked as a cache breakpoint.

    `ttl` is "5m" (default, 1.25x write premium) or "1h" (2x). Prefer "5m"
    unless the reuse genuinely spans more than five minutes: a 1h write needs
    ~3 reads to pay for itself where a 5m write needs 2.
    """
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral", "ttl": ttl}}


def cached_prefix_blocks(
    stable: str,
    volatile: str = "",
    *,
    ttl: str = "5m",
) -> list[dict[str, Any]]:
    """Build `[cached stable block, uncached volatile block]` content blocks.

    This is the shape `coach_narrative_orchestrator._build_user_message` proved
    works on Haiku: the run-invariant bytes first, carrying the breakpoint; the
    per-call bytes after it, outside the cache.

    `volatile` may be empty (a prompt that is entirely stable), in which case a
    single cached block is returned. `stable` must be non-empty — a breakpoint on
    nothing is always a no-op, and asking for one is a caller bug rather than a
    runtime condition, so it raises.
    """
    if not (stable or "").strip():
        raise ValueError("cached_prefix_blocks: `stable` must be non-empty — a cache breakpoint on an empty prefix can never engage")
    blocks = [cached_block(stable, ttl=ttl)]
    if (volatile or "").strip():
        blocks.append({"type": "text", "text": volatile})
    return blocks


def _iter_content_blocks(body: dict[str, Any]):
    """Every content block in a Messages request body, system and messages alike."""
    system = body.get("system")
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict):
                yield block
    for message in body.get("messages") or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    yield block


def requests_caching(body: dict[str, Any]) -> bool:
    """Does this request body carry at least one `cache_control` breakpoint?

    The question `bedrock_client` has to answer before it can tell a cache MISS
    (asked for caching, got none — a defect) apart from a request that simply
    never asked (not a defect). Structural, not heuristic: it walks the same
    blocks the API does.
    """
    if not isinstance(body, dict):
        return False
    if body.get("cache_control"):  # top-level auto-caching
        return True
    return any(block.get("cache_control") for block in _iter_content_blocks(body))


def cacheable_prefix_text(body: dict[str, Any]) -> str:
    """The concatenated text of every block up to and including the LAST
    `cache_control` breakpoint — i.e. the bytes that actually have to clear the
    model's floor.

    Render order is tools -> system -> messages, so walking system before
    messages matches what the API hashes. Tool definitions are not included: they
    are counted by the API but are not text blocks, so this returns a LOWER bound
    on the real prefix (safe for a "this is under the floor" diagnosis).
    """
    texts: list[str] = []
    prefix: list[str] = []
    for block in _iter_content_blocks(body):
        texts.append(block.get("text") or "")
        if block.get("cache_control"):
            prefix = list(texts)
    return "".join(prefix)
