"""critics_models.py — the four critics' model calls, made CONCURRENTLY with a bounded wait (#5313).

`coach.critics.run_critics` used to call the model once per critic, one after another, so stage 2
paid the sum of four Bedrock round trips on top of its reads, and on 2026-10-20 and 2026-10-25 the
whole call missed the MCP tool cap (30 s) and stored nothing. The four calls are independent — each
critic holds a DISJOINT packet and never sees another's reply — so they run side by side here and
stage 2 pays the slowest one instead of the sum.

What does NOT change:
  * every call still goes through the `invoke` callable the caller hands in, which in production is
    `ai.bedrock_client.invoke` — the ADR-062 chokepoint, with its own tier-3 budget refusal per call.
    The tier gate (`budget_guard.allow("plan_critics")`) is still decided once, before any call, by
    the caller (`tools_plan._model_allowed`);
  * a model failure is RECORDED on its critic's verdict (`{"error": ...}`), never raised past it, and
    the deterministic layer still decides that critic — `critics.reconcile` reads the error;
  * the ContextVar state of the calling thread (e.g. `bedrock_client.attributed_to`'s feature label)
    is copied into each worker, so attribution is the same as a sequential call's.

The wait is bounded: a reply that has not arrived by `timeout_s` is recorded as a TimeoutError on
that critic, and the deterministic layer decides it. The worker is not killed (Python cannot), but
the caller no longer waits on it, so one slow Bedrock reply cannot push stage 2 past its deadline.
This module is PURE apart from the threads: no I/O of its own.
"""

from __future__ import annotations

import concurrent.futures
import contextvars
from typing import Any, Callable

MAX_WORKERS = 4  # one per critic; `critics.CRITIC_IDS` has four


def model_verdicts(
    prompts: dict[str, dict[str, Any]],
    invoke: Callable[[dict[str, Any]], dict[str, Any]],
    parse: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    timeout_s: float | None = None,
) -> dict[str, dict[str, Any]]:
    """`{critic_id: parse(invoke(prompt))}` for every prompt, the calls concurrent.

    A raise from `invoke` or `parse` becomes `{"error": "<Type>: <msg>"}` (200 chars, the shape the
    sequential loop recorded); a call still running at `timeout_s` becomes a TimeoutError entry."""
    if not prompts:
        return {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(prompts)), thread_name_prefix="critic")
    try:
        futures = {
            pool.submit(contextvars.copy_context().run, _one, invoke, parse, prompt): cid  # one context copy per worker
            for cid, prompt in prompts.items()
        }
        done, _pending = concurrent.futures.wait(futures, timeout=timeout_s)
        out: dict[str, dict[str, Any]] = {}
        for fut, cid in futures.items():
            if fut in done:
                out[cid] = fut.result()
            else:
                out[cid] = {"error": f"TimeoutError: no model reply within {timeout_s:.1f}s — the deterministic layer decided"[:200]}
        return out
    finally:
        # Never wait on a straggler (the #3765 lesson: a `with` block's exit would block on it).
        pool.shutdown(wait=False, cancel_futures=True)


def _one(invoke: Callable[[dict[str, Any]], dict[str, Any]], parse: Callable[[dict[str, Any]], dict[str, Any]], prompt: dict[str, Any]):
    try:
        return parse(invoke(prompt))
    except Exception as e:  # noqa: BLE001 — a model failure is recorded on the verdict, not raised past it
        return {"error": f"{type(e).__name__}: {e}"[:200]}
