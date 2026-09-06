"""analyzer_grounding.py — the two SHARED groundings ai_expert_analyzer_lambda restated locally.

#3517 — THE EXPERIMENT FRAME.
`gather_data_for_expert`, `build_prompt` and `generate_and_cache` each carried their own
copy of `max(1, (today - genesis).days + 1)`. On a PRE-START day that clamp is a lie: with
genesis 2026-09-06 and today 2026-09-05 the true day count is 0, and the clamp made every
observatory prompt assert "started 2026-09-06, now day 1". The models did what they were
told — live `/api/coach_analysis?domain=physical` read "No weight reading has arrived since
the September 5th reset", a past-tense claim about a genesis that had not happened, twice,
and it passed every deterministic gate and the quality gate at 92. The impossible tense was
the PROMPT's, not only the model's.

The platform already owns the honest answer: `ai.ai_context.build_experiment_phase_context`
+ `format_experiment_phase_context` — the ONE shared phase block (#1086) that the public AI
surfaces ground on, with a `pre_start` branch and the "numbers that cannot exist yet"
guardrail. The analyzer was simply not wired to it. `experiment_frame()` is that wiring: one
derivation, three call sites, and NO clamp before genesis.

#3516 — THE SOURCE FACET.
`movement_source_state: {"garmin": "paused"}` handed the prompt a bare label with no reason,
and coaches supplied one: "Garmin step data isn't syncing to my dashboard yet". Garmin is
paused by ADR-074 and cannot report at all. `movement_source_reasons()` attaches the source
registry's OWN `method` string to each state, so the reason is the registry's, not the
model's invention.

Fail-soft by construction: every helper degrades to the pre-#3517 arithmetic (or to an empty
reason map) rather than raising into a weekly cron.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple


class ExperimentFrame(NamedTuple):
    """The analyzer's phase view. `days_in` is 0 before genesis — never clamped to 1.

    `as_of` is the PACIFIC calendar day the frame was resolved for — the #2813 contract's
    observable, so the sweep can drive this function at a PT-evening instant and prove the
    default day is Pacific rather than UTC.
    """

    days_in: int
    week_num: int
    pre_start: bool
    period: str
    phase_block: str
    as_of: str


def _pt_today() -> str:
    """Today, PACIFIC (#2811/#2813). Never `date.today()` — the analyzer's DATE# queries,
    the site and every gate name the Pacific day, and a naive clock silently disagrees
    with all three for seven hours a day."""
    try:
        from common.pacific_time import pacific_today

        return pacific_today()
    except Exception:  # noqa: BLE001 — a weekly cron never dies on a clock read
        return date.today().isoformat()  # utc-exempt(#3517): unreachable fallback when the PT helper is absent from the bundle


def _fallback_frame(start_str: str, today_iso: str, days_in=None, week_number=None) -> ExperimentFrame:
    """The pre-#3517 arithmetic, minus the clamp — used only if the shared block is unreadable."""
    today_iso = str(today_iso or _pt_today())
    try:
        delta = (date.fromisoformat(today_iso) - date.fromisoformat(start_str)).days + 1
    except Exception:  # noqa: BLE001
        delta = 1
    # PRE-START IS DECIDED BY THE CLOCK, BEFORE any caller override is applied. The
    # reverse order is the defect: `generate_and_cache` passes an explicit
    # `days_in_experiment`, so honouring it first would let a clamped 1 reinstate exactly
    # the "now day 1" claim this exists to remove.
    if delta <= 0:
        return ExperimentFrame(
            0, 0, True, f"pre-start (genesis {start_str} has not arrived)", _PRE_START_LINE.format(start=start_str), today_iso
        )
    d = days_in if days_in is not None else max(0, delta)
    w = week_number if week_number is not None else max(1, d // 7 + 1)
    line = f"This is Week {w} of the experiment (started {start_str}, now day {d})."
    return ExperimentFrame(d, w, False, f"experiment days 1-{d}", line, today_iso)


_PRE_START_LINE = (
    "PRE-START: the experiment has NOT begun. Genesis is {start} and it is still in the FUTURE. "
    "There is no Day 1, no week number, and no experiment data. Never write about the genesis, "
    "the reset, or any cycle event in the past tense."
)


def experiment_frame(days_in=None, week_number=None, today_iso=None) -> ExperimentFrame:
    """The analyzer's phase frame, derived from the shared #1086 block.

    `days_in` / `week_number` override the derived values when a caller has its own (the
    `build_prompt(expert_key, data, days_in, week_num)` signature); `pre_start` and the
    prompt block are ALWAYS derived from the clock, so an override cannot resurrect the
    "now day 1" claim on a pre-start day.

    `today_iso` is the CALLER's clock instant — the analyzer passes its own
    `pacific_today()`. Threading it rather than reading a second clock in here is what
    keeps the frame anchored to the same Pacific day the caller's DATE# queries use
    (#2811), and is what lets a frozen-clock test reach this derivation at all.
    """
    try:
        from common.constants import EXPERIMENT_START_DATE as _start
    except Exception:  # noqa: BLE001
        _start = ""
    today_iso = str(today_iso or _pt_today())
    try:
        from ai.ai_context import build_experiment_phase_context, format_experiment_phase_context

        pctx = build_experiment_phase_context(current_date_str=today_iso)
        block = format_experiment_phase_context(pctx)
    except Exception:  # noqa: BLE001 — a weekly cron never dies on a grounding read
        return _fallback_frame(_start, today_iso, days_in, week_number)

    start_str = str(pctx.get("start_date") or _start)
    as_of = str(pctx.get("as_of") or today_iso)
    if pctx.get("pre_start"):
        # No clamp, no week number, and the shared PRE-START block leads the prompt.
        return ExperimentFrame(
            0, 0, True, f"pre-start (genesis {start_str} has not arrived)", _PRE_START_LINE.format(start=start_str) + "\n" + block, as_of
        )
    d = days_in if days_in is not None else int(pctx.get("days_in") or 1)
    w = week_number if week_number is not None else int(pctx.get("week_num") or 1)
    line = f"This is Week {w} of the experiment (started {start_str}, now day {d})."
    return ExperimentFrame(d, w, False, f"experiment days 1-{d}", line + "\n" + block, as_of)


# #2813: the day-default contract. `experiment_frame()` decides what "today" is for every
# observatory prompt, so the sweep drives it at a PT-evening instant and asserts the
# resolved day is the PACIFIC one. Registration is inert at runtime (the decorator returns
# the same function object) and fail-soft on a partial bundle.
try:
    from common.pt_day_contract import pt_day_contract

    experiment_frame = pt_day_contract(extract=lambda f: f.as_of)(experiment_frame)
except Exception:  # noqa: BLE001
    pass


def movement_source_reasons(source_states) -> dict:
    """{source: registry reason} for every source in `source_states` that has a facet (#3516).

    Only PAUSED / LAG-BY-DESIGN sources appear: a live source's absence needs no caveat, and
    emitting an empty string for one would invite a coach to narrate it. The strings are the
    registry's `method` facet verbatim — the ADR reference and the cadence come from the one
    place they are maintained.
    """
    try:
        from ingestion.source_registry import availability_facet
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for src in source_states or {}:
        caveat = availability_facet(src)["caveat"]
        if caveat:
            out[src] = caveat
    return out
