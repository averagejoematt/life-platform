#!/usr/bin/env python3
"""
test_a11y_shrink_deadman_3546.py — the clock on the a11y shrink list (#3546).

WHAT THIS EXISTS FOR
--------------------
`tests/a11y_audit.py::shrink_candidates` has printed "a11y ledger: N shrink
candidate(s)" on every sweep since #1990. Nobody harvested it. The series is
in the issue: 5 (2026-08-24) → 7 (08-29) → 7 (08-31) → 11 (09-04) → **50 across
48 pages** (09-19). A printed line with no consumer is not a consumer.

The cost is not cosmetic. `gate_findings` keys the a11y gate on
`(page path, axe rule id)`, so a rule that sits in `tests/a11y_baseline.json`
for a page that no longer violates it will classify a genuinely NEW violation
of that rule as "baselined — recorded, not gating". Fifty unharvested keys is
fifty (page, rule) pairs where the serious/critical gate is silently off.

So the sweep now persists its shrink list to ONE committed file —
`tests/a11y_shrink_ledger.json`, one row per (page, rule) with the date it was
FIRST seen unharvested — and this test reds when any row is older than
`a11y_audit.SHRINK_MAX_AGE_DAYS`. This file reads that one named JSON and the
`a11y_audit` pure helpers; it walks no trees and enumerates no registries.

THE THRESHOLD IS LOAD-BEARING — MUTATION-PROVEN
-----------------------------------------------
`test_stale_entry_is_caught` plants a row dated 30 days back and asserts it is
returned. Setting `SHRINK_MAX_AGE_DAYS = 10_000` in `tests/a11y_audit.py` makes
that planted control PASS (i.e. the dead-man stops firing), which is what proves
the budget — not the file's existence — is what does the work. Verified by
running the mutation and restoring it; see the PR body for the transcript.

NO WALL-CLOCK TIME BOMB (#2376 / the #2354 class)
--------------------------------------------------
A dead-man is, by construction, a test about dates, so it is one careless line
away from the class that red-mained main at 2026-08-09T00:00Z: a fixed fixture
date plus a handler that derives "today" from the real clock, agreeing only on
the day the test was written. Two things keep this file out of it:

  * ONE pinned as-of day, `_AS_OF`, with every fixture date derived from it by
    arithmetic (`_STALE_SINCE`, `_FRESH_SINCE`) — never a second literal that
    must agree — and handed to `stale_shrink_entries(ledger, today_iso)` as the
    argument it already takes. Fixture and assertion co-derive; UTC midnight
    cannot separate them.
  * a real freeze where the read is: `frozen_sweep_clock` pins
    `common.pacific_time`'s OWN `datetime`, because `pacific_today()` reads that
    module's name and no consumer-side patch reaches it (tests/pacific_clock.py).
    `test_fresh_entry_is_not_stale` asserts the frozen value comes back, so the
    freeze is proven to bite rather than decorating a scanner.

The ONE test that deliberately reads the real calendar is
`test_committed_shrink_ledger_has_no_stale_entry` — ageing a committed file
against the actual clock is that test's entire contract, and freezing it would
make it a gate that cannot fail.

Run it alone:  python3 -B -m pytest tests/test_a11y_shrink_deadman_3546.py -q
"""

import json
import os
import sys
from datetime import date, timedelta, timezone

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import a11y_audit  # noqa: E402

# ── the pinned as-of day, and every fixture date DERIVED from it (#2376) ──────
#
# `stale_shrink_entries(ledger, today_iso)` takes the as-of day as a PARAMETER,
# so the anti-bomb shape is available and is used: one constant generates the
# fixture `first_seen` values AND is handed to the function under test, and the
# two cannot desync at UTC midnight the way #2354 did. The name says what the
# value IS — an injected as-of argument — rather than claiming it is the day a
# clock will read, because it never is one.
#
# Deriving `_STALE_SINCE`/`_FRESH_SINCE` by arithmetic rather than writing a
# second literal is the other half: two dated literals that must agree is
# exactly how this class drifts back into a bomb (the `frozen_handler_clock`
# exemplar in tests/test_pipeline_health_check_behavior.py makes the same point).
_AS_OF = "2026-09-19"
_STALE_SINCE = (date.fromisoformat(_AS_OF) - timedelta(days=30)).isoformat()
_FRESH_SINCE = (date.fromisoformat(_AS_OF) - timedelta(days=1)).isoformat()


@pytest.fixture
def frozen_sweep_clock(monkeypatch):
    """Pin the PT clock the sweep reads to an instant DERIVED from `_AS_OF`.

    The sweep's own day (`capture_today_pt`) comes from `pacific_today()`, which
    lives in `common.pacific_time` and reads THAT module's own `datetime` — a
    patch on any consumer's namespace cannot reach it (tests/pacific_clock.py's
    docstring records the measurement). So the freeze goes where the read is.

    Used by the tests that exercise the live-clock path. The committed-ledger
    dead-man below deliberately does NOT take it: ageing a committed file
    against the real calendar is that test's entire contract, and freezing it
    would be a gate that cannot fail.
    """
    a11y_audit._ensure_lambda_path()
    import common.pacific_time as pacific_time

    year, month, day = (int(x) for x in _AS_OF.split("-"))

    class _FrozenDatetime(pacific_time.datetime):
        @classmethod
        def now(cls, tz=None):
            # Noon UTC on _AS_OF is early morning PT on the SAME calendar day,
            # so the Pacific frame and the constant agree in both directions.
            return pacific_time.datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc).astimezone(tz or timezone.utc)

    monkeypatch.setattr(pacific_time, "datetime", _FrozenDatetime)
    return _AS_OF


def _today():
    """The sweep's clock, not the runner's — PT, same as capture_today_pt."""
    a11y_audit._ensure_lambda_path()
    from common.pacific_time import pacific_today

    return pacific_today()


# ── the dead-man over the COMMITTED file ──────────────────────────────────────


def test_committed_shrink_ledger_has_no_stale_entry():
    """No (page, rule) may sit unharvested for more than a week.

    To clear a red here: run `python3 tests/visual_qa.py --update-baseline`
    against live, review the `tests/a11y_baseline.json` diff, and commit both
    it and the regenerated sidecar. Hand-deleting the row is not a fix — the
    next sweep re-adds it with today's date and the gate stays off.
    """
    ledger = a11y_audit.load_shrink_ledger()
    stale = a11y_audit.stale_shrink_entries(ledger, _today())
    assert not stale, (
        f"{len(stale)} a11y shrink candidate(s) older than {a11y_audit.SHRINK_MAX_AGE_DAYS}d — each one is a "
        f"(page, rule) pair where the serious/critical gate has silently stopped gating (#3546): "
        + "; ".join(f"{p}:{r} first seen {fs} ({age}d)" for p, r, fs, age in stale[:8])
    )


def test_committed_shrink_ledger_is_well_formed():
    """Every row carries the three fields the dead-man ages and decides on."""
    ledger = a11y_audit.load_shrink_ledger()
    assert isinstance(ledger.get("entries"), list)
    for r in ledger["entries"]:
        assert r.get("page") and r.get("rule"), f"row missing page/rule: {r}"
        date.fromisoformat(r["first_seen"])  # raises on a malformed date
        assert isinstance(r.get("phase_dependent"), bool), f"row missing the #3546 phase flag: {r}"


# ── positive control: a planted stale row MUST be caught ──────────────────────


def test_stale_entry_is_caught():
    """The must-fail control. A row dated 30 days ago is returned as stale.

    This is the assertion the 10,000-day mutation flips green.
    """
    planted = {
        "_meta": {},
        "entries": [
            {"page": "/cockpit/", "rule": "region", "first_seen": _STALE_SINCE, "phase_dependent": True},
            {"page": "/data/labs/", "rule": "color-contrast", "first_seen": _AS_OF, "phase_dependent": False},
        ],
    }
    stale = a11y_audit.stale_shrink_entries(planted, _AS_OF)
    assert len(stale) == 1, f"expected exactly the 30-day row, got {stale}"
    page, rule, first_seen, age = stale[0]
    assert (page, rule, first_seen) == ("/cockpit/", "region", _STALE_SINCE)
    assert age == 30


def test_stale_control_survives_a_file_round_trip(tmp_path):
    """Same control through the real load path — a fixture COPY on disk, so the
    dead-man is exercised end-to-end (read → age → verdict), not just in RAM."""
    fixture = tmp_path / "a11y_shrink_ledger.json"
    fixture.write_text(
        json.dumps(
            {
                "_meta": {"note": "planted fixture"},
                "entries": [
                    {"page": "/method/board/ @390px", "rule": "heading-order", "first_seen": _STALE_SINCE, "phase_dependent": True}
                ],
            }
        )
    )
    ledger = a11y_audit.load_shrink_ledger(str(fixture))
    assert a11y_audit.stale_shrink_entries(ledger, _AS_OF)


def test_a_row_that_cannot_be_aged_is_not_young():
    """An absent/garbled first_seen returns as stale with age -1 — silence is
    never health (the #2938 rule applied to a date field)."""
    ledger = {"entries": [{"page": "/x/", "rule": "region", "first_seen": None}]}
    assert a11y_audit.stale_shrink_entries(ledger, _AS_OF) == [("/x/", "region", None, -1)]


def test_fresh_entry_is_not_stale(frozen_sweep_clock):
    """…and the negative control, so the test is not vacuously red-happy.

    Takes `frozen_sweep_clock` so the live-clock path (`_today()` →
    `pacific_today()`) is exercised at a PINNED instant: the assertion below
    that it equals `_AS_OF` is what proves the freeze actually reaches
    `common.pacific_time`'s own `datetime`, rather than being decoration that
    satisfies a scanner."""
    assert _today() == _AS_OF, "the freeze did not reach common.pacific_time"
    ledger = {"entries": [{"page": "/cockpit/", "rule": "region", "first_seen": _FRESH_SINCE, "phase_dependent": True}]}
    assert a11y_audit.stale_shrink_entries(ledger, _today()) == []


# ── carry-forward: the clock must not restart on every sweep ──────────────────


def test_merge_carries_first_seen_forward():
    """The whole dead-man rests on this: a candidate seen again keeps its
    ORIGINAL date. Re-stamping today on every run would make the ledger a
    perpetual-motion machine that can never age past zero."""
    prior = {"_meta": {}, "entries": [{"page": "/cockpit/", "rule": "region", "first_seen": _STALE_SINCE, "phase_dependent": True}]}
    merged = a11y_audit.merge_shrink_ledger({"/cockpit/": ["region"]}, _AS_OF, prior=prior, swept_pages={"/cockpit/"})
    assert merged["entries"][0]["first_seen"] == _STALE_SINCE
    assert a11y_audit.stale_shrink_entries(merged, _AS_OF)


def test_merge_drops_a_harvested_row_on_a_swept_page():
    """Harvest the baseline entry → the candidate disappears → so does its row
    (and with it its clock). Otherwise a paid debt reds this test forever."""
    prior = {"_meta": {}, "entries": [{"page": "/cockpit/", "rule": "region", "first_seen": _STALE_SINCE, "phase_dependent": True}]}
    merged = a11y_audit.merge_shrink_ledger({}, _AS_OF, prior=prior, swept_pages={"/cockpit/"})
    assert merged["entries"] == []


def test_merge_preserves_rows_for_pages_this_run_never_drove():
    """A `--page` / `--max-tier` sweep must not clear the rest of the dead-man —
    the same contract `a11y_audit.update_baseline` keeps for the baseline."""
    prior = {
        "_meta": {},
        "entries": [{"page": "/data/labs/", "rule": "color-contrast", "first_seen": _STALE_SINCE, "phase_dependent": False}],
    }
    merged = a11y_audit.merge_shrink_ledger({}, _AS_OF, prior=prior, swept_pages={"/cockpit/"})
    assert [r["page"] for r in merged["entries"]] == ["/data/labs/"]
    assert merged["entries"][0]["first_seen"] == _STALE_SINCE


# ── box 2: the phase flag ─────────────────────────────────────────────────────


def test_phase_derivation_matches_the_two_facets_it_composes():
    """The derivation is stated in `phase_dependent_page`'s docstring; these are
    its three shapes, each asserted against a page that really exists.

      /cockpit/    live-data, deps resolve to nothing (aggregate endpoints) → True
      /data/labs/  live-data, /api/labs → CROSS_PHASE in phase_taxonomy    → False
      /story/about/ static                                                 → False
    """
    assert a11y_audit.phase_dependent_page("/cockpit/") is True
    assert a11y_audit.phase_dependent_page("/data/labs/") is False
    assert a11y_audit.phase_dependent_page("/story/about/") is False
    # an in-page anchor is not a manifest page and is never flagged
    assert a11y_audit.phase_dependent_page("/coaching/by-coach/#eli_marsh") is False


@pytest.mark.parametrize("viewport_key", ["/cockpit/", "/cockpit/ @390px"])
def test_phase_dependent_entry_is_no_candidate_on_day_3_but_is_on_day_13(viewport_key):
    """Box 2's acceptance, both ledger axes: on Day 3 a phase-dependent page's
    fixed rule is neither a shrink candidate nor harvestable; on Day 13 it is."""
    gate = {viewport_key: {"fixed": ["color-contrast"]}}
    assert a11y_audit.shrink_candidates(gate, day_n=3) == {}
    assert a11y_audit.shrink_candidates(gate, day_n=13) == {viewport_key: ["color-contrast"]}
    # and with no clock supplied at all, pre-#3546 behaviour exactly
    assert a11y_audit.shrink_candidates(gate) == {viewport_key: ["color-contrast"]}


def test_a_cross_phase_page_is_a_candidate_even_on_day_3():
    """The flag must not be a blanket pause — /data/labs/ reads CROSS_PHASE
    clinical data that a reset never thins, so its shrink signal is honest on
    Day 3 as much as Day 13."""
    gate = {"/data/labs/": {"fixed": ["color-contrast"]}}
    assert a11y_audit.shrink_candidates(gate, day_n=3) == {"/data/labs/": ["color-contrast"]}


def test_thin_window_boundary_is_day_7():
    gate = {"/cockpit/": {"fixed": ["region"]}}
    assert a11y_audit.shrink_candidates(gate, day_n=6) == {}
    assert a11y_audit.shrink_candidates(gate, day_n=a11y_audit.PHASE_THIN_DAYS) == {"/cockpit/": ["region"]}


def test_update_baseline_carries_a_phase_row_forward_on_day_3(tmp_path):
    """The 'not harvestable' half. A row that vanished from a phase-dependent
    page inside the thin window survives an --update-baseline; the same run on
    Day 13 harvests it. This is the exact failure the issue's own comment
    warns about: harvest on a thin day, red as 'NEW serious' when the chart draws.
    """
    path = str(tmp_path / "a11y_baseline.json")
    seeded = {
        "_meta": {},
        "pages": {"/cockpit/": [{"id": "color-contrast", "impact": "serious", "help": "h", "nodes": 4, "issue": "#3546"}]},
    }
    open(path, "w").write(json.dumps(seeded))

    a11y_audit.update_baseline({"/cockpit/": []}, path=path, day_n=3)
    kept = json.load(open(path))["pages"].get("/cockpit/")
    assert kept and kept[0]["id"] == "color-contrast", "a thin-day harvest removed a phase-dependent row"

    a11y_audit.update_baseline({"/cockpit/": []}, path=path, day_n=13)
    assert "/cockpit/" not in json.load(open(path))["pages"], "Day 13 must harvest normally"


def test_merge_records_the_phase_flag_on_every_row():
    merged = a11y_audit.merge_shrink_ledger(
        {"/cockpit/": ["region"], "/data/labs/": ["color-contrast"]}, _AS_OF, prior=None, swept_pages=None
    )
    flags = {r["page"]: r["phase_dependent"] for r in merged["entries"]}
    assert flags == {"/cockpit/": True, "/data/labs/": False}


# ── the clock itself ──────────────────────────────────────────────────────────


def test_experiment_day_n_is_the_journey_number():
    """`/api/journey` serves `pacific_day_n(EXPERIMENT_START)`; this reads the
    same genesis constant, so the two cannot disagree about which day it is."""
    a11y_audit._ensure_lambda_path()
    from constants import EXPERIMENT_START_DATE

    assert a11y_audit.experiment_day_n(EXPERIMENT_START_DATE) == 1
    assert a11y_audit.experiment_day_n("2026-01-01") == 0  # pre-genesis clamps
    assert a11y_audit.experiment_day_n(_today()) >= 0
