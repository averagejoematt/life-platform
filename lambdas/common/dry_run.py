"""common/dry_run.py — one definition of what a DRY_RUN invocation means (#2255).

Before this module, "dry run" meant whatever each email Lambda's flag happened
to gate. In `daily_brief_lambda` it gated exactly the two `ses.send_email`
calls, which made "use `dry_run` to test the daily brief safely" false advice:

  * the write path was gated on `demo_mode` alone, so a dry run re-published
    `generated/public_stats.json` and `pulse.json` — the artifacts
    averagejoematt.com actually serves — and re-ran every DynamoDB write on the
    path, exactly as a real run does;
  * `record_email_send()` ran unconditionally, stamping `status: "success"` and
    a `sent_at` into the `email_log` partition the status page and the
    missing-send alarm read, for mail that was never sent.

So a dry run has two obligations, and the second is the dangerous one — an
overwritten artifact is corrected by the next real run, a silenced alarm is not:

  1. **write nothing** — no SES send, no S3 object, no DynamoDB item;
  2. **report honestly** — leave no record claiming the real run happened.

What a dry run deliberately does NOT suppress: reads, rendering, and AI
generation (the point of the exercise is usually to look at the generated
brief; suppress spend with the budget tier, not with this flag), plus
observability datapoints that describe the *pipeline* rather than this run.

Usage — resolve once at the top of the handler, then gate every write:

    _dry = dry_run.stash(event)          # resolves + records on the event
    ...
    if dry_run.persistence_enabled(event, demo_mode):
        write_the_artifacts()

`stash()` records the resolved value under `FLAG` so deeper call sites can read
the decision off the event without re-deriving it (and without re-reading the
environment, which would let a `force_send` override drift between sites).
"""

from __future__ import annotations

import os
from typing import Any, Mapping, MutableMapping

#: Key under which `stash()` records the resolved decision on the event.
FLAG = "_dry_run_resolved"

#: Event keys that request a build-but-do-not-send/write run. This is THE
#: vocabulary — #2222 folded the SES send-suppressor's alias list in here rather
#: than keep a second one next door. Two modules each answering "is this a dry
#: run" with different keys is worse than one narrow answer: `{"no_send": true}`
#: suppressed 17 Lambdas and was silently ignored by the daily brief, which sent
#: for real. `dryRun` is accepted because a hand-typed console invoke is as
#: likely to camelCase it.
SUPPRESSOR_EVENT_KEYS = ("dry_run", "dryRun", "no_send", "preview_mode", "test_mode")

#: Keys that ask for a one-off REAL run despite an environment-level suppressor.
FORCE_SEND_EVENT_KEYS = ("force_send", "forceSend")

#: The same meaning as SUPPRESSOR_EVENT_KEYS, for the Lambdas whose trigger
#: payload is not under an operator's control (EventBridge scheduled rules).
SUPPRESSOR_ENV_VARS = ("DRY_RUN", "NO_SEND", "PREVIEW_MODE", "TEST_MODE")

#: String values that mean "no". Everything else non-empty means yes — a safety
#: flag fails toward suppressing. The important half is that `"false"` and `"0"`
#: are NOT a dry run: `resolve` used plain truthiness before #2222, so
#: `{"dry_run": "false"}` — the exact shape a JSON-ish console payload produces —
#: silently disabled the send it was meant to permit.
_FALSEY_STRINGS = frozenset({"", "0", "false", "no", "off", "none"})


def _truthy(value: Any) -> bool:
    """Truthiness with string semantics — ``"false"``/``"0"`` are False."""
    if isinstance(value, str):
        return value.strip().lower() not in _FALSEY_STRINGS
    return bool(value)


def _scopes(event: Any):
    """The event itself, plus an EventBridge ``detail`` wrapper if present.

    A scheduled rule that carries a constant payload nests it under `detail`,
    so a flag set there has to count. A non-mapping event (an S3/SES `Records`
    list) yields nothing rather than raising — that is a legitimate shape.
    """
    if not isinstance(event, Mapping):
        return
    yield event
    detail = event.get("detail")
    if isinstance(detail, Mapping):
        yield detail


def _any_flag(event: Any, keys) -> bool:
    return any(key in scope and _truthy(scope[key]) for scope in _scopes(event) for key in keys)


def resolve(event: Mapping[str, Any]) -> bool:
    """Decide whether this invocation is a dry run.

    True when the event carries any of `SUPPRESSOR_EVENT_KEYS` truthily, or
    when any of `SUPPRESSOR_ENV_VARS` is truthy and the caller has not asked for
    a one-off real run with `{"force_send": true}`. An explicit suppressor on
    the event outranks `force_send` — asking for both is a mistake, and the
    safe reading of a mistake is "do not send".
    """
    if _any_flag(event, SUPPRESSOR_EVENT_KEYS):
        return True
    if _any_flag(event, FORCE_SEND_EVENT_KEYS):
        return False
    return any(_truthy(os.environ.get(name, "")) for name in SUPPRESSOR_ENV_VARS)


def force_requested(event: Mapping[str, Any]) -> bool:
    """True when the caller explicitly asked for a one-off real run.

    Exposed (DIL-025) so the *replay* guard in `common.send_ledger` can honour
    the same `force_send` override the dry-run gate already honours, without
    re-deriving the vocabulary. `send_guard` learned this lesson the hard way
    (#2255/#2222): two modules each answering "did the operator ask for X" with
    their own key list is how `{"no_send": true}` came to suppress 17 Lambdas
    and be silently ignored by the 18th. One list, one reader.

    Note this is deliberately NOT `not resolve(event)` — `resolve` folds in the
    environment and the suppressor precedence rules. This answers only the
    narrow question "is `force_send` present and truthy on this event".
    """
    return _any_flag(event, FORCE_SEND_EVENT_KEYS)


def stash(event: MutableMapping[str, Any]) -> bool:
    """Resolve the dry-run decision and record it on the event under `FLAG`."""
    decided = resolve(event)
    event[FLAG] = decided
    return decided


def is_dry_run(event: Mapping[str, Any]) -> bool:
    """Read the stashed decision, falling back to resolving it.

    The fallback matters: a gate that silently reads `False` off an event the
    handler forgot to `stash()` is a suppressor that does not suppress.
    """
    if isinstance(event, Mapping) and FLAG in event:
        return bool(event[FLAG])
    return resolve(event)


def persistence_enabled(event: Mapping[str, Any], demo_mode: bool = False) -> bool:
    """True when this invocation may write to S3 / DynamoDB / another Lambda.

    Both suppressors in one predicate so a new write site cannot pick up only
    the `demo_mode` half — which is precisely how #2255 happened.
    """
    return not demo_mode and not is_dry_run(event)
