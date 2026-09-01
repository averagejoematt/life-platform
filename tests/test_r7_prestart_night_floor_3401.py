"""#3401 — R7's night floor may not demand a night from the future.

WHAT WENT WRONG. `_night_floor` was `genesis - 1`, unconditionally. A staged FUTURE
genesis is the sanctioned reset shape (#931/#939), and on the day before Day 1 that floor
names TONIGHT — a night nobody has slept yet. The rule was unsatisfiable for the whole
pre-start window.

Measured live 2026-08-31, the eve of the cycle-15 launch. `/api/vitals` served:

    as_of_date = 2026-08-31
    night_of   = 2026-08-30

`night_of + 1 == as_of_date`, which is the platform's OWN documented convention
(`reader_truth_evidence.py`: "a night is dated by the evening it began, the payload by the
morning it is read"). R7 raised a `high` against it, the nightly qa-smoke failed on it, and
`qa-smoke-failures` sat in ALARM through launch eve — the moment a lit alarm is most
expensive to read.

WHY `min` AND NOT A PRE-START SKIP. R6/R7 deliberately run OUTSIDE the pre-start guard,
because a staged genesis is exactly when a stale prior-cycle row is most likely to leak.
Skipping R7 pre-start would drop that coverage entirely. Bounding the floor keeps the rule
live and merely stops it asking for the impossible: pre-start it flags anything older than
last night, and post-start `today - 1 >= genesis - 1` makes the bound inert, so nothing
about Day-1-and-after behaviour changes. Both halves are asserted below — the fix is only
worth having if the leak it was built for still reds.
"""

import importlib.util
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
spec = importlib.util.spec_from_file_location("_pp_3401", os.path.join(_REPO, "lambdas", "operational", "phase_plausibility.py"))
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)

GENESIS = "2026-09-01"
EVE = "2026-08-31"

# The payload as it was actually served on launch eve — not a hand-shaped approximation.
LIVE_EVE_VITALS = {"vitals": {"as_of_date": "2026-08-31", "night_of": "2026-08-30"}}


def _findings(payload, start_date=GENESIS, today=None):
    return pp._pre_genesis_night_findings("/api/vitals", payload, start_date, today)


def test_the_recorded_launch_eve_payload_stops_being_a_finding():
    """The exact shape that held qa-smoke-failures in ALARM on 2026-08-31."""
    assert _findings(LIVE_EVE_VITALS, today=EVE) == []


def test_it_reds_without_the_fix_floor():
    """Negative control on the FLOOR itself, so the case above cannot pass vacuously.

    Same payload, same clock, the old unconditional `genesis - 1` floor: a finding. If
    this stops failing, the test above is asserting nothing.
    """
    assert pp._night_floor(GENESIS) == "2026-08-31"
    assert pp._night_floor(GENESIS, EVE) == "2026-08-30"
    assert _findings(LIVE_EVE_VITALS, today=None) != []


def test_a_genuine_pre_start_leak_still_reds():
    """Coverage preserved: two nights early is still a leak, pre-start or not."""
    stale = {"vitals": {"as_of_date": "2026-08-31", "night_of": "2026-08-29"}}
    (finding,) = _findings(stale, today=EVE)
    assert finding["severity"] == "high"
    assert finding["category"] == "temporal_contradiction"


def test_day_one_and_after_is_completely_unchanged():
    """Post-start the bound is inert: `today - 1 >= genesis - 1`, so the floor is genesis - 1."""
    for today in ("2026-09-01", "2026-09-03", "2026-10-15"):
        assert pp._night_floor(GENESIS, today) == "2026-08-31", today
    # ...and the leak R7 exists for still reds on Day 3.
    leak = {"vitals": {"night_of": "2026-08-30"}}
    assert _findings(leak, today="2026-09-03") != []
    # ...while the legitimate genesis-eve night still passes.
    ok = {"vitals": {"night_of": "2026-08-31"}}
    assert _findings(ok, today="2026-09-03") == []


def test_without_a_clock_the_floor_is_the_old_one():
    """Fail-soft, and deliberately so (#3337): a caller that cannot say what day it is
    does not get the today-aware branch. Production always can — `sweep_payloads` passes
    `phase["today"]` — so this is the degraded path, not the live one."""
    assert pp._night_floor(GENESIS) == "2026-08-31"
    assert _findings(LIVE_EVE_VITALS) != []


def test_the_live_sweep_actually_passes_the_clock():
    """The fix is only real if production supplies `today`. A today-aware rule silently
    running without a clock is the #3337 defect this must not repeat."""
    source = open(os.path.join(_REPO, "lambdas", "operational", "phase_plausibility.py")).read()
    assert 'today=phase["today"]' in source, "sweep_payloads no longer passes the clock — R7's floor is dark"
