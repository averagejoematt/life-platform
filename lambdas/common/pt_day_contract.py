"""lambdas/common/pt_day_contract.py — the #2813 producer/gate day-default registry.

WHY THIS EXISTS
---------------
Every production timezone escape since the #2506 sweep has been in an INSTRUMENT
(a validator or gate), never a display: #2675 (the grounding gate's own
``generation_date_iso`` default read UTC), #2815 (the quality-gate wire event's
``generation_date`` default did too), #2812/#2816 (the board quality gate's
``day_n`` default did). Each was found, fixed and pinned SEPARATELY — one test
file per incident, with nothing stopping the next one from reaching production
before anybody notices. The platform runs two frames on purpose (UTC for
crons/infra, Pacific for data semantics); "today" is a producer<->consumer
AGREEMENT, not a value, and the existing per-incident pins only ever checked
how ONE side derives its day-string.

This module is the STANDING registry that closes the gap: any real production
function whose "what day is it by default" resolution matters gets ONE
decorator, here, on the actual shipped function — never a test-only shadow.
``tests/test_pt_day_contract_sweep_2813.py`` calls every registered entry at a
PT-evening instant (an instant where the UTC calendar day and the Pacific
calendar day disagree) and asserts the resolved day is the PACIFIC one, not
the UTC one.

DISCOVERY IS STRUCTURAL, NOT A HAND LIST (guard the SET, not the instance)
---------------------------------------------------------------------------
The sweep test AST-scans ``lambdas/`` for every function carrying
``@pt_day_contract`` and imports each hit module before reading
``PT_DAY_CONTRACT_REGISTRY`` below — so a NEW decorated function is swept
automatically, with zero edits to the test file. The companion AST scan for
day-SHAPED default parameters (``generation_date``, ``day_n``, ``today_iso``,
...) that a maintainer forgot to either decorate or explicitly exempt is the
second half of that guard, in the same test module — a function matching that
shape with neither a decorator nor a written exemption fails the build.

USAGE
-----
    from common.pt_day_contract import pt_day_contract

    def cycle_gate_params(generation_date_iso=None):
        ...

    try:  # optional and inert on a partial bundle — mirrors this module's own
          # fail-soft contract; registration must never be what breaks an import.
        cycle_gate_params = pt_day_contract(extract=lambda r: r["generation_date_iso"])(cycle_gate_params)
    except Exception:  # noqa: BLE001
        pass

``extract`` pulls the resolved day-string (``YYYY-MM-DD``) out of whatever the
function returns. ``args``/``kwargs`` are the minimal call the sweep drives —
omit them when every parameter that matters has a usable default (true for
most gates); supply them when the function has other REQUIRED positional
parameters (see ``quality_gate_event`` in ``ai/quality_gate_contract.py``,
which needs a ``coach_id``/``output_text``/``generation_brief`` to construct
at all — its DAY default is still exercised with no ``generation_date``).

Zero behavior change: the decorator registers and returns the SAME function
object, unwrapped. A production call is byte-identical to the undecorated
function; nothing here is on any runtime path.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Sequence


@dataclass(frozen=True)
class ContractEntry:
    """One registered producer/gate default, ready for the sweep to drive."""

    module: str
    qualname: str
    fn: Callable[..., Any]
    extract: Callable[[Any], str]
    args: Sequence[Any] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.module}::{self.qualname}"

    def resolve(self) -> str:
        """Call the function at its DAY default (plus whatever other required
        args this entry supplies) and pull out the resolved day-string."""
        return self.extract(self.fn(*self.args, **self.kwargs))


# The derived registry — populated ONLY as a side effect of importing a module
# that uses the decorator below. Never hand-appended.
PT_DAY_CONTRACT_REGISTRY: List[ContractEntry] = []


def pt_day_contract(extract: Callable[[Any], str], args: Sequence[Any] = (), kwargs: Dict[str, Any] = None):
    """Mark a real production function as part of the #2813 PT-day contract.

    Returns the function UNCHANGED (pure registration side effect) — this is
    a marker, not a wrapper, so decorating a function can never alter its
    production behavior, its signature, or how any other caller sees it.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        PT_DAY_CONTRACT_REGISTRY.append(
            ContractEntry(
                module=fn.__module__,
                qualname=fn.__qualname__,
                fn=fn,
                extract=extract,
                args=tuple(args),
                kwargs=dict(kwargs or {}),
            )
        )
        return fn

    return decorator
