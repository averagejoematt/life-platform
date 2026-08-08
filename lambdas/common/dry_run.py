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

_TRUTHY = ("1", "true", "yes")


def resolve(event: Mapping[str, Any]) -> bool:
    """Decide whether this invocation is a dry run.

    True when the event carries ``{"dry_run": true}``, or when env ``DRY_RUN``
    is truthy and the caller has not asked for a one-off real send with
    ``{"force_send": true}``.
    """
    if event.get("dry_run"):
        return True
    if event.get("force_send"):
        return False
    return os.environ.get("DRY_RUN", "").lower() in _TRUTHY


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
    if FLAG in event:
        return bool(event[FLAG])
    return resolve(event)


def persistence_enabled(event: Mapping[str, Any], demo_mode: bool = False) -> bool:
    """True when this invocation may write to S3 / DynamoDB / another Lambda.

    Both suppressors in one predicate so a new write site cannot pick up only
    the `demo_mode` half — which is precisely how #2255 happened.
    """
    return not demo_mode and not is_dry_run(event)
