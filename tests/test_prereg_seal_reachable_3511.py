"""tests/test_prereg_seal_reachable_3511.py — the seal must survive the ledger's slice.

#3511 box 4 ("_PREDICTION_PROJECTION_FIELDS carries pre_registered + pre_registered_at
and the ledger table renders sealed vs unsealed") shipped complete and was still vacuous
in EFFECT. A pre-registered bet is dated at GENESIS, so it is the oldest row in the
season; the handler sorted date-descending and took `[:limit]`, and the page requests no
limit at all. Measured live 2026-09-18, cycle 17 Day 12, AFTER the 16 stranded rows were
restamped into the season:

    curl -s 'https://averagejoematt.com/api/predictions?limit=50'  -> 0 of 50 sealed
    curl -s 'https://averagejoematt.com/api/predictions?limit=200' -> 16 of 200 sealed

So the provenance column rendered "in-cycle" for every row a reader could reach, and
would have for the remainder of the cycle. These tests bind the fix to that measurement
rather than to the shape of the code.
"""

import importlib.util
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ledger():
    """Import the module by path — `lambdas/` is packaged for a Lambda bundle, and the
    handler's own module-level imports resolve against the bundle root."""
    for p in (os.path.join(REPO, "lambdas"), os.path.join(REPO, "lambdas", "web")):
        if p not in sys.path:
            sys.path.insert(0, p)
    path = os.path.join(REPO, "lambdas", "web", "site_api_coach_ledger.py")
    spec = importlib.util.spec_from_file_location("_site_api_coach_ledger", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # pragma: no cover - environment-dependent import chain
        pytest.skip(f"site_api_coach_ledger not importable here: {e}")
    return mod


def _row(date, sealed=False, n=0):
    return {"date": date, "pre_registered": sealed, "text": f"call-{date}-{n}"}


def _season(in_cycle=200, sealed=16, genesis="2026-09-06"):
    """Date-descending, exactly the order the handler hands to the slice."""
    rows = [_row(f"2026-09-{18 - (i % 12):02d}", False, i) for i in range(in_cycle)]
    rows += [_row(genesis, True, i) for i in range(sealed)]
    rows.sort(key=lambda x: x["date"], reverse=True)
    return rows


def test_the_measured_live_case_default_limit_50_now_serves_every_sealed_row():
    """The exact shape read off production: 16 sealed at genesis behind 200 in-cycle
    calls, sliced to the page's default 50. Before the fix this served 0 sealed."""
    mod = _ledger()
    out = mod.admit_sealed(_season(in_cycle=200, sealed=16), 50)
    assert len(out) == 50, "the slice must stay exactly `limit` long"
    assert sum(1 for r in out if r["pre_registered"]) == 16


def test_row_order_stays_date_descending():
    mod = _ledger()
    out = mod.admit_sealed(_season(), 50)
    dates = [r["date"] for r in out]
    assert dates == sorted(dates, reverse=True)


def test_sealed_rows_displace_the_oldest_in_cycle_never_the_newest():
    mod = _ledger()
    season = _season(in_cycle=200, sealed=16)
    out = mod.admit_sealed(season, 50)
    newest = [r for r in season if not r["pre_registered"]][:34]
    assert all(r in out for r in newest), "the newest in-cycle calls must all survive"


def test_no_sealed_rows_is_a_plain_slice():
    mod = _ledger()
    season = _season(in_cycle=200, sealed=0)
    assert mod.admit_sealed(season, 50) == season[:50]


def test_limit_below_the_sealed_count_degrades_to_sealed_only_not_a_silent_drop():
    mod = _ledger()
    out = mod.admit_sealed(_season(in_cycle=200, sealed=16), 10)
    assert len(out) == 10
    assert all(r["pre_registered"] for r in out)


def test_limit_at_or_above_the_season_returns_everything():
    mod = _ledger()
    season = _season(in_cycle=20, sealed=16)
    assert mod.admit_sealed(season, 200) == season
