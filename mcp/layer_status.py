"""mcp/layer_status.py — the derived-layer honesty contract (#3769, epic #3762).

A tool that reads a DERIVED partition (a projection some job computed, not a fact
somebody logged) has two ways to return nothing and they mean opposite things: "the
thing you asked about did not happen" and "the layer that would know never ran / could
not be read". #3767 fixed that on `get_exercise_notes` and left the vocabulary + rule in
`mcp.core` (`LAYER_OK|DEGRADED|DARK|UNKNOWN`, `derived_layer_status`). This module is
the one place the contract is spelled out for every OTHER derived-layer reader, and the
registry the structural test (`tests/test_layer_status_contract_3769.py`) derives the
reader set from. The owner's rule, verbatim: *empty should be indistinguishable from
"we couldn't look" only if it actually is.*

THE CONTRACT
  * every response carries `layer_status` — one of `ok | degraded | dark | unknown |
    unavailable` — and, on anything but `ok`, a plain-English `layer_reason`;
  * a count from a layer that could not be read is `None`, never `0`, and the list it
    would have counted is ABSENT, never `[]` (an empty list is a claim);
  * `degraded` still returns its rows and counts — they are real, the caveat is on the
    producer — so a caller can read them with the reason attached.

WHY THE LIST IS EXPLICIT (and small)
  `phase_taxonomy.py` classes partitions by what a RESET does to them, not by who writes
  them: `training_notes` is RAW_TIMESERIES there ("frozen-as-data") although an extractor
  computes it, and `sick_days`/`habit_causality` are RAW because the owner logs them. So
  "derived" cannot be read off the taxonomy. The set below was verified reader-by-reader
  against the live table on 2026-09-19 (the table is in PR #3769's body); `sick_days`
  and `habit_causality` were checked and are NOT derived — their only writers are the
  owner's own MCP tools (`log_sick_day`, `log_habit_reflection`) plus `sick_day_checker.
  write_sick_day`, which is the same owner action from a Lambda.
"""

from __future__ import annotations

from datetime import date as _date

from common.pacific_time import pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days

from mcp.core import LAYER_DARK, LAYER_DEGRADED, LAYER_OK, LAYER_UNKNOWN, derived_layer_status  # noqa: F401 — re-exported

# The read itself failed (throttle, auth, timeout). Distinct from `unknown` (the read
# succeeded but the layer has no health signal to consult) — #3767 needed only the latter.
LAYER_UNAVAILABLE = "unavailable"

# Statuses on which a reader may still report its counts. `dark`/`unknown`/`unavailable`
# withhold them — the number would read as a measured zero.
COUNTS_REPORTABLE_ON = (LAYER_OK, LAYER_DEGRADED)

# name → how the layer is written + the pk fragment a READ of it carries. The structural
# test walks `mcp/tools_*.py` by AST for these fragments (or a module constant equal to
# the bare name) inside any function that calls `.query(`, and asserts that function
# references `layer_status`. Adding a derived layer here makes every reader of it subject
# to the contract; adding a reader of a listed layer without the contract reds the test.
DERIVED_LAYERS: dict[str, dict] = {
    "training_notes": {
        "producer": "hevy_backfill_lambda note extractor (training.training_notes)",
        "health": "training.training_notes.training_notes_health",
        "cadence_days": None,  # on-ingest; health is the extractor's own dark/degraded tally
    },
    "coach_thread": {
        "producer": "ai-expert-analyzer via intelligence_common.write_coach_thread",
        "health": None,
        "cadence_days": 7,  # EventBridge weekly, Mon 14:00 UTC (compute_stack.py, #3366)
    },
    "platform_memory": {
        "producer": "compute lambdas (channel=computed) + MCP write_platform_memory (channel=conversation)",
        "health": None,
        "cadence_days": None,  # per category; retention_days in ai.platform_memory is a RELEVANCE window, not a cadence
    },
}


def read_status(
    *, error: BaseException | None = None, newest_date: str | None = None, cadence_days: int | None = None, as_of: str | None = None
):
    """(status, reason) for a derived layer that has no health function of its own.

    `error` — the exception the read raised, if any → `unavailable`.
    `newest_date` / `cadence_days` — when both are known and the newest record is more
    than two cadences old, the rows are real but the producer may have stopped →
    `degraded` (counts still reported, with the reason). Neither known → `ok`: a
    successful read with nothing to caveat IS a measured result.
    """
    if error is not None:
        return (
            LAYER_UNAVAILABLE,
            f"the read failed ({type(error).__name__}: {error}) — counts from this layer are withheld: they would read as measured zeros",
        )
    if newest_date and cadence_days:
        try:
            # #2817: the tools run interactively in PT evenings, when a UTC "today" is tomorrow's empty day.
            today = _date.fromisoformat(str(as_of)[:10] if as_of else pacific_today())
            age = (today - _date.fromisoformat(str(newest_date)[:10])).days
        except ValueError:
            return LAYER_UNKNOWN, f"newest record carries an unparseable date ({newest_date!r}); producer cadence cannot be checked"
        if age > 2 * cadence_days:
            return (
                LAYER_DEGRADED,
                f"newest record is {age}d old against a {cadence_days}d producer cadence — the rows are real, the producer may be dark",
            )
    return LAYER_OK, ""


def layer_fields(status: str, reason: str = "", **health) -> dict:
    """The response keys the contract requires, in the shape #3767 established
    (`layer_status`, `layer_reason` only when there is one, `layer_health`)."""
    out = {"layer_status": status, "layer_health": dict(health)}
    if reason:
        out["layer_reason"] = reason
    return out


def counted(status: str, value):
    """`value` when the layer's counts are reportable, else None — the rule, in one place."""
    return value if status in COUNTS_REPORTABLE_ON else None
