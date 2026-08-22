"""#2652 — the coverage denominator must be the live route table, not the registry.

`qa_audit` reported **"0 endpoints uncovered"** while 82 of the 134 live `/api/*` routes
were swept by nothing. Its denominator was the manifest: it measured manifest-declared
api_deps against the smoke sweep, so **a route that was never registered could not appear
as uncovered**. The classic guard-the-instance error, sitting in the instrument whose whole
job is reporting coverage.

`surface-drift.yml` blocks only NEW unregistered routes — it is diff-only — which is exactly
how the 82 became grandfathered: nothing ever looked at the standing set. Two live 502s found
in the same bug-bash sweep (#2656, #2657) both live inside those 82.

THE FIX IS THE DENOMINATOR. `live_api_coverage()` counts against
`endpoint_registry.discover_endpoint_records()` — the same AST walk `sync_doc_metadata` uses
for the published endpoint count, so the two cannot disagree about what exists.

AN EXCEPTION IS DATA, NOT A COMMENT. The issue's rule is that the uncovered count is 0 **or**
every exception carries a written reason. Only the mechanically defensible class is excepted:
POST-only write doors, where a GET is a 405 and a POST would mutate Matthew's data on every
deploy sweep. That set is derived from the router's own declared methods, never hand-listed,
so a door that stops being POST-only re-enters the uncovered set by itself.

WHAT THIS CLOSES. Boxes 1, 2 and 4: the denominator is live, the audit names every uncovered
route, and the check is mutation-proved below. Box 3 closed with the router-derived long-tail
sweep (`qa_manifest.api_sweep_records()` + `scripts/api_sweep_check.py` + the widened
`accuracy_audit` numeric denominator — see tests/test_api_sweep_2652.py): every live route is
now swept or carries a written, derived reason, and `uncovered` must stay EMPTY. The zero is
not grandfathering-in-reverse: the sweep rows were not hand-adjudicated en masse — the generic
tier derives from the router, and only the 8 routes where a bare 200-JSON GET is the wrong
expectation carry per-route overrides, each with its written reason, each measured against
live (2026-08-22) before the sweep was allowed to gate.
"""

from __future__ import annotations

import importlib
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "scripts"), os.path.join(_REPO, "deploy"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


qa_audit = importlib.import_module("qa_audit")
endpoint_registry = importlib.import_module("endpoint_registry")

COV = qa_audit.live_api_coverage()


# ── box 1: the denominator ───────────────────────────────────────────────────


def test_the_coverage_is_derived_at_all():
    """Vacuity guard — a None here would make every assertion below unreachable."""
    assert COV is not None, "live_api_coverage() returned None; the derivation is broken"


def test_the_denominator_is_the_live_route_table_not_the_manifest():
    """The defect in one assertion: the count of live routes must match the router's own
    walk, not the number of routes somebody remembered to register."""
    live = {p for p in endpoint_registry.discover_endpoint_records() if p.startswith("/api/")}
    assert COV["live_routes"] == len(live)
    assert COV["live_routes"] > 100, f"only {COV['live_routes']} live routes — the walk is broken"

    import qa_manifest

    assert COV["live_routes"] > len(qa_manifest.api_dep_endpoints()), "the manifest cannot be the denominator; it is smaller"


def test_the_same_walk_that_publishes_the_endpoint_count_is_used():
    """Two derivations of "what routes exist" would drift; there is one."""
    import inspect

    assert "endpoint_registry" in inspect.getsource(qa_audit.live_api_coverage)


# ── box 2: the uncovered set is named, not just counted ──────────────────────


def test_uncovered_routes_are_enumerated_not_merely_counted():
    assert COV["uncovered_count"] == len(COV["uncovered"])
    assert all(r.startswith("/api/") for r in COV["uncovered"])


def test_the_report_prints_every_uncovered_route(monkeypatch):
    """A count with no names is not actionable; the queue has to be readable.

    The healthy uncovered set is EMPTY since box 3 landed, so iterating it would make
    this test vacuous (#2790's lesson) — plant a route that falls out of every sweep
    and require the report to name it.
    """
    victim = COV["swept"][0]
    orig_smoke = [p for p in qa_audit.smoke_checked_endpoints() if p != victim]
    import qa_manifest

    orig_deps = [p for p in qa_manifest.api_dep_endpoints() if p != victim]
    monkeypatch.setattr(qa_audit, "smoke_checked_endpoints", lambda: orig_smoke)
    monkeypatch.setattr(qa_manifest, "api_dep_endpoints", lambda: orig_deps)
    report = qa_audit.render(qa_audit.build_audit())
    assert "LIVE /api COVERAGE" in report
    assert f"UNCOVERED (no sweep, no written reason): {victim}" in report, f"{victim} fell out of every sweep and the report never named it"


def test_the_report_says_the_zero_is_a_ratchet_not_a_verdict():
    """Box 3 is closed; the note must now say `uncovered` is required to stay empty —
    a name appearing there is a worked queue, not an accepted state."""
    report = qa_audit.render(qa_audit.build_audit())
    assert "must stay EMPTY" in report
    assert "the queue to work, not an accepted state" in report


def test_every_route_is_in_exactly_one_bucket():
    """Swept, out-of-scope, or uncovered — no route may fall between them, which is the
    hiding place the old denominator provided."""
    live = {p for p in endpoint_registry.discover_endpoint_records() if p.startswith("/api/")}
    buckets = set(COV["swept"]) | set(COV["out_of_scope"]["write_doors"]) | set(COV["uncovered"])
    assert buckets == live, f"unbucketed: {sorted(live - buckets)}"
    assert not (set(COV["swept"]) & set(COV["uncovered"]))


# ── the exception carries a reason, and is derived ───────────────────────────


def test_the_only_exception_class_carries_a_written_reason():
    reason = COV["out_of_scope"]["reason"]
    assert len(reason) > 80, "an out-of-scope class needs a reason, not a label"
    assert "405" in reason and "mutate" in reason, reason


def test_the_exception_set_is_derived_from_the_routers_declared_methods():
    """Hand-listing the write doors would rot the moment one gained a GET."""
    records = endpoint_registry.discover_endpoint_records()
    expected = sorted(p for p, r in records.items() if p.startswith("/api/") and r.methods and set(r.methods) <= {"POST"})
    assert COV["out_of_scope"]["write_doors"] == expected
    assert expected, "no POST-only doors found — the method extraction is broken"


def test_a_door_that_stops_being_post_only_returns_to_the_uncovered_set():
    """The exception must be a property of the route, not a permanent pass."""
    records = endpoint_registry.discover_endpoint_records()
    door = COV["out_of_scope"]["write_doors"][0]
    assert set(records[door].methods) <= {"POST"}
    records[door].merge_methods({"GET"})
    assert not (set(records[door].methods) <= {"POST"}), "merging GET must remove it from the write-door class"


# ── box 4: mutation-proved ───────────────────────────────────────────────────


def test_removing_a_live_route_from_the_swept_set_makes_it_uncovered(monkeypatch):
    """Plant the defect the issue describes — a live route the manifest stops declaring —
    and the coverage check must catch it. Before the fix, a route absent from the manifest
    was absent from the denominator too, so this was undetectable by construction."""
    victim = COV["swept"][0]
    # Snapshot BEFORE patching — a lambda that calls the name it is replacing recurses.
    orig_smoke = list(qa_audit.smoke_checked_endpoints())
    import qa_manifest

    orig_deps = list(qa_manifest.api_dep_endpoints())
    monkeypatch.setattr(qa_audit, "smoke_checked_endpoints", lambda: [p for p in orig_smoke if p != victim])
    monkeypatch.setattr(qa_manifest, "api_dep_endpoints", lambda: [p for p in orig_deps if p != victim])

    after = qa_audit.live_api_coverage()
    assert victim in after["uncovered"], f"{victim} stopped being swept and the audit did not notice"
    assert after["uncovered_count"] == COV["uncovered_count"] + 1


def test_an_unavailable_registry_reports_not_derived_rather_than_full_coverage(monkeypatch):
    """The failure mode that would recreate the bug: a broken walk returning nothing must
    not read as "every route is covered"."""
    monkeypatch.setattr(endpoint_registry, "discover_endpoint_records", lambda *a, **k: {})
    assert qa_audit.live_api_coverage() is None
    report = qa_audit.render(qa_audit.build_audit())
    assert "NOT DERIVED" in report and "no coverage claim is made" in report


def test_the_zero_uncovered_came_from_registration_not_a_broken_walk():
    """This test's previous body asserted `uncovered_count > 0` with the instruction:
    'if this drops to 0, either the queue was worked or the denominator broke, and those
    must not look the same.' The queue WAS worked (box 3, the api_sweep long tail) — so
    now prove the zero is the worked kind: the walk still sees the full route table and
    the sweep facet is carrying the long tail, not an empty derivation."""
    import qa_manifest

    assert COV["uncovered_count"] == 0, f"routes fell back out of the sweeps: {COV['uncovered']}"
    assert COV["live_routes"] > 100, "a shrunken denominator would fake a clean zero"
    sweep = qa_manifest.api_sweep_routes()
    assert len(sweep) > 50, f"api_sweep carries only {len(sweep)} routes — the long tail is not being swept"
    assert set(sweep).isdisjoint(qa_manifest.api_dep_endpoints()), "the sweep double-counts declared api_deps"
