"""lambdas/ai/grounding_gate_params.py — the cycle-freshness gate params, in ONE place (#1967).

``grounded_generation.grounding_findings()`` arms its phase-aware classes only when the
caller supplies the cycle anchors:

* ``generation_date_iso`` + ``start_date_iso`` -> ``stale_phase`` (#1691) and
  ``experiment_span`` (#1897 — the "seven days of an experiment" Day-1 leak)
* ``baseline_lbs`` -> ``stale_baseline`` (#1691)

That signature is all-optional by design (backward compat, #1691), which is exactly why
coverage drifted into convention: every grounding caller had to hand-wire the same three
constants and nothing failed when one didn't. This module is the single provider, so a
caller arms the whole class with ``**cycle_gate_params()`` and there is one place to
change when the anchors change.

``tests/grounding_wiring.py`` treats a ``**cycle_gate_params()`` spread as arming the
``freshness`` gate class (see ``PARAM_PROVIDERS`` there) — renaming the function without
updating that map fails the wiring test rather than silently disarming eleven surfaces.

Both freshness classes are FRAMING-SCOPED: ``stale_phase``/``experiment_span`` only look
at text that frames a "Day N" / "N days of the experiment" claim, and ``stale_baseline``
only at a weight token next to baseline framing. Arming them on a surface that never uses
that framing is therefore a no-op, never new noise — which is what makes wiring them
broadly safe.
"""

from datetime import date as _date
from typing import Any, Dict, Optional


def cycle_gate_params(generation_date_iso: Optional[str] = None) -> Dict[str, Any]:
    """Kwargs that arm the cycle-freshness gate classes; spread into the gate call.

    Usage (the pattern every wired caller follows)::

        grounding_findings(text, allowed=allowed, **cycle_gate_params())

    ``generation_date_iso`` defaults to today in the PACIFIC frame (#2675). It
    defaulted to UTC until 2026-08-16, which armed the Day-N gate with a clock
    one day AHEAD of the platform's own every PT evening: the prompt's phase
    block asserts the pacific_day_n day (#1955, THE one day-index formula), so
    between 17:00 PDT and midnight the gate flagged a coach who echoed the
    prompt's correct day and PASSED one who said the UTC day — which is exactly
    how two board voices published two different cycle days in one response on
    2026-08-13 PT (#2675), both blessed by their own gate. Pass it explicitly
    when the surface narrates a fixed date.

    Fail-soft by contract: if the constants module is unavailable (a partial bundle,
    an import-order edge) this returns ``{}``, which leaves the caller at EXACT
    pre-#1691 behavior. A grounding gate must never be the thing that takes a
    narrative surface down.
    """
    try:
        from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE
    except Exception:  # noqa: BLE001 — see the fail-soft contract above
        return {}
    if generation_date_iso is None:
        try:
            from common.pacific_time import pacific_today

            generation_date_iso = pacific_today()
        except Exception:  # noqa: BLE001 — same fail-soft contract: degrade to UTC, never take the surface down
            generation_date_iso = _date.today().isoformat()
    return {
        "generation_date_iso": generation_date_iso,
        "start_date_iso": EXPERIMENT_START_DATE,
        "baseline_lbs": EXPERIMENT_BASELINE_WEIGHT_LBS,
    }
