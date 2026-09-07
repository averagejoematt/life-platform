"""mcp/tools_platform.py — the three hot-path named tools (#3668).

The index (``describe_platform_surfaces``) carries the long tail. These three are the
questions the owner asks constantly, where a NAMED tool beats an index lookup because
discoverability is the whole problem:

  ``get_experiment_cycle``   — "what cycle are we on, and what day?"  ← the specimen
  ``get_habit_completion``   — "how are my habits going?"
  ``get_platform_cost``      — "what is this costing me?"

Two of the three are thin wrappers over the SAME waiter machinery the index uses, on
purpose: a named tool that re-implemented the fetch would be a second copy of the rule
declaration, which is the defect this issue exists to close.

THE CYCLE NUMBER IS NOT RE-DERIVED
----------------------------------
It is authoritative in three places that already agree::

    CYCLE_GENESES (lambdas/web/site_api_data.py)   17 entries, cycle 17 -> 2026-09-06
    SSM /life-platform/experiment-cycle            17
    experiment_stamp()                             {'phase': 'experiment', 'cycle': 17}

``get_experiment_cycle`` returns ``experiment_stamp()["cycle"]`` and nothing else — a
fourth derivation is exactly how four unreconciled cycle numbers ended up in one journal
entry. ``tests/test_mcp_surface_index_3668.py`` asserts the equality, so the tool and the
stamp cannot drift apart.

SSM is read as a CROSS-CHECK only, never as the answer, and never fatally: the reset
bumps SSM *before* genesis, so during a countdown SSM legitimately names the NEXT cycle.
Disagreement in that window is expected and is reported as such rather than resolved.
"""

from __future__ import annotations

from mcp.config import logger
from mcp.tools_surfaces import record_unanswered, tool_get_platform_surface

_CYCLE_SSM_PARAM = "/life-platform/experiment-cycle"


def tool_get_experiment_cycle(args=None):
    """Which experiment cycle is running, which day of it is today, and what phase."""
    args = args or {}
    as_of = (args.get("date") or "").strip() or None

    try:
        from common.constants import EXPERIMENT_START_DATE
        from experiment.phase_taxonomy import experiment_stamp
        from web.site_api_data import CYCLE_GENESES
    except Exception as e:  # noqa: BLE001
        rec = record_unanswered("what cycle are we on?", detail=f"cycle registry import failed: {e}")
        return {"error": f"cycle registry unavailable: {str(e)[:200]}", "miss_recorded": rec}

    stamp = experiment_stamp(as_of=as_of) if as_of else experiment_stamp()
    cycle = stamp.get("cycle")
    genesis = CYCLE_GENESES.get(cycle) if cycle is not None else None

    # Day-N comes from `common.constants.day_n` — the ONE derivation the rest of the
    # platform uses. A private (d - start).days here would be a fourth cycle arithmetic
    # in a tool whose entire reason for existing is that a fourth derivation is how four
    # unreconciled cycle numbers reached one journal entry. It also keeps this module out
    # of the #3609 hand-rolled-fromisoformat census.
    day_number = None
    pre_start = None
    try:
        from common.constants import day_n
        from common.pacific_time import pacific_today

        today = as_of or pacific_today()
        day_number = day_n(today)  # 0 == pre-genesis, by that helper's own contract
        pre_start = day_number == 0
    except Exception as e:  # noqa: BLE001 — an unknown day is reported, never invented (ADR-104)
        logger.warning(f"[#3668] day_n unavailable: {e}")

    ssm_value: int | None = None
    ssm_status = "not read"
    try:
        from coach.coach_checkin import read_cycle

        ssm_value = read_cycle()
        ssm_status = "read" if ssm_value is not None else "unavailable (fail-soft): no value returned"
    except Exception as e:  # noqa: BLE001 — a cross-check must never be the reason an answer fails
        ssm_status = f"unavailable (fail-soft): {type(e).__name__}"

    agreement = None
    if cycle is not None and ssm_value is not None:
        agreement = (
            "agree"
            if int(ssm_value) == int(cycle)
            else (
                "DISAGREE — expected during a countdown window: the reset bumps SSM before genesis, so SSM names the "
                "NEXT cycle until Day 1. CYCLE_GENESES is the answer; SSM is the cross-check."
            )
        )

    return {
        "cycle": cycle,
        "cycle_genesis": genesis,
        "day_n": day_number,
        "pre_start": pre_start,
        "phase": stamp.get("phase"),
        "experiment_start_date": EXPERIMENT_START_DATE,
        "as_of": as_of or "today (Pacific)",
        "authority": {
            "answer_from": "experiment_stamp() — lambdas/experiment/phase_taxonomy.py",
            "registry": "CYCLE_GENESES (lambdas/web/site_api_data.py)",
            "cycles_on_record": len(CYCLE_GENESES),
            "ssm_cross_check": {"param": _CYCLE_SSM_PARAM, "value": ssm_value, "status": ssm_status, "agreement": agreement},
            "note": "One derivation, three witnesses. This tool never computes a cycle number of its own.",
        },
        "rule": {
            "date_basis": "Pacific calendar day (America/Los_Angeles) — the calendar every genesis is declared in.",
            "phase_filter": "n/a — the cycle registry is a config fact, not a phase-tagged partition read.",
            "cycle_for_date": "the highest cycle whose genesis is <= the date (cycle_for_date)",
        },
        "prior_cycles": {str(k): v for k, v in sorted(CYCLE_GENESES.items())},
        "why_this_tool_exists": (
            "Asked on 2026-09-06 and answered 'the platform doesn't track it' while three sources held it. "
            "A journal entry that same day carried four unreconciled cycle numbers; three of the four were "
            "accurate snapshots of a number that had since moved."
        ),
    }


def _surface(name: str, params: dict | None = None) -> dict:
    return tool_get_platform_surface({"name": name, "params": params or {}})


def tool_get_habit_completion(args=None):
    """How the habits are going — completion, streaks, and the date rule behind them."""
    args = args or {}
    want_registry = bool(args.get("include_registry"))

    habits = _surface("habits")
    streaks = _surface("habit_streaks")
    out: dict = {
        "habits": habits.get("data"),
        "streaks": streaks.get("data"),
        "rule": habits.get("rule"),
        "streaks_rule": streaks.get("rule"),
        "vintage": habits.get("vintage"),
    }
    if want_registry:
        reg = _surface("habit_registry")
        out["registry"] = reg.get("data")
        out["registry_rule"] = reg.get("rule")

    if habits.get("error"):
        out["error"] = habits["error"]
    # The #3668 habits specimen: rows were CAPTURED and mis-dated, and the surface said
    # "0 of 61 completed". A zero that carries no date rule is indistinguishable from an
    # empty day, so the zero is annotated rather than left to speak for itself.
    out["reading_this_honestly"] = (
        "A completion count of 0 here means 0 rows matched on THIS surface's date basis (see rule.date_basis) "
        "under THIS surface's phase filter (see rule.phase_filter). It does NOT mean nothing was logged: a row "
        "written against the adjacent calendar day, or tagged phase=pilot, is invisible to this read by design. "
        "Check get_daily_snapshot with include_pilot=true and the neighbouring date before concluding a miss."
    )
    return out


def tool_get_platform_cost(args=None):
    """What the platform is costing — the budget envelope and the AI spend receipts."""
    args = args or {}
    receipts = _surface("receipts")
    out: dict = {
        "budget_envelope": receipts.get("data"),
        "rule": receipts.get("rule"),
        "vintage": receipts.get("vintage"),
    }
    if receipts.get("error"):
        out["error"] = receipts["error"]
    if not args.get("skip_inference"):
        inference = _surface("inference_receipt")
        out["inference_receipt"] = inference.get("data")
        out["inference_rule"] = inference.get("rule")
    out["reading_this_honestly"] = (
        "These are the platform's OWN accounting surfaces (the Glass Engine envelope + the AI inference "
        "receipt), not an AWS Cost Explorer query. The month-end projection they carry is the cost governor's "
        "projection; treat it as a forecast, and read the tier alongside it."
    )
    return out
