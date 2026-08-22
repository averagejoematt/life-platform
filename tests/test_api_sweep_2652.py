"""#2652 box 3 — the router-derived /api long-tail sweep.

Boxes 1/2/4 (PR #2728) made the coverage ledger honest: 69 routes read UNCOVERED
because nothing swept them. This box gives them the sweep: a generic
status+JSON-shape tier derived from the router itself (`qa_manifest.
api_sweep_records()`, probed by `scripts/api_sweep_check.py` inside the smoke)
plus the numeric impossible-value scan (tests/accuracy_audit.py widens its
denominator to the same rows). The `light_pct: 106.7` incident is the shape this
closes: the RIGHT rule reading a too-narrow denominator.

The design rule under test everywhere here: the route list is DERIVED, never
hand-typed — hand-adjudicating 69 entries in one pass would be the
grandfathering this issue is about wearing a different hat. Overrides exist only
where a bare 200-JSON GET is the wrong expectation, and each carries a written
reason (an exception is data, not a comment).
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "scripts"), os.path.join(_REPO, "deploy"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

qa_manifest = importlib.import_module("qa_manifest")
endpoint_registry = importlib.import_module("endpoint_registry")
api_sweep_check = importlib.import_module("api_sweep_check")


# ── the derivation ───────────────────────────────────────────────────────────


def test_the_sweep_is_the_router_minus_the_two_adjudicated_classes():
    """Set equality, not spot checks: sweep routes == live /api routes − POST-only
    write doors − declared api_deps. Nothing hand-typed can drift from that."""
    records = endpoint_registry.discover_endpoint_records()
    live = {p for p in records if p.startswith("/api/")}
    doors = {p for p in live if records[p].methods and set(records[p].methods) <= {"POST"}}
    deps = set(qa_manifest.api_dep_endpoints())
    assert set(qa_manifest.api_sweep_routes()) == live - doors - deps
    assert len(qa_manifest.api_sweep_routes()) > 50, "the long tail collapsed — the derivation is broken"


def test_a_new_router_route_autoenters_the_sweep(monkeypatch):
    """The anti-grandfathering property: a route landing in the router is swept the
    same commit, with the generic 200-JSON expectation — no list to remember."""
    records = dict(endpoint_registry.discover_endpoint_records())
    fake = "/api/test_2652_new_route"
    records[fake] = endpoint_registry.EndpointRecord(path=fake, mechanisms={"routes"}, methods={"GET"})
    monkeypatch.setattr(endpoint_registry, "discover_endpoint_records", lambda *a, **k: records)
    rows = {r["route"]: r for r in qa_manifest.api_sweep_records()}
    assert fake in rows
    assert rows[fake]["expect"] == "200" and rows[fake]["fetch"] == fake


def test_a_route_leaving_the_declared_api_deps_falls_into_the_sweep(monkeypatch):
    """A page dropping its api_dep declaration must not orphan the route — it moves
    to the generic tier instead of leaving coverage."""
    deps = qa_manifest.api_dep_endpoints()
    victim = next(d for d in deps if d.startswith("/api/"))
    monkeypatch.setattr(qa_manifest, "api_dep_endpoints", lambda: [d for d in deps if d != victim])
    assert victim in qa_manifest.api_sweep_routes()


# ── overrides: forced adjudication, written reasons ──────────────────────────


def test_every_override_carries_a_written_reason():
    """An exception is data, not a comment (#2652's rule) — and a label is not a
    reason."""
    for route, ov in qa_manifest._API_SWEEP_OVERRIDES.items():
        assert len(ov.get("reason", "")) > 60, f"{route}: an override needs a written reason, not a label"
        assert ov.get("expect", "200") != "200" or ov.get("fetch"), f"{route}: an override that changes nothing is a stale exemption"


def test_a_prefix_route_without_a_probe_raises(monkeypatch):
    """A bare GET on a prefix route 404s — counting that row as swept would be fake
    coverage, so the derivation must refuse to emit until someone adjudicates."""
    records = dict(endpoint_registry.discover_endpoint_records())
    fake = "/api/test_2652_prefix/"
    records[fake] = endpoint_registry.EndpointRecord(path=fake, mechanisms={"inline"}, is_prefix=True)
    monkeypatch.setattr(endpoint_registry, "discover_endpoint_records", lambda *a, **k: records)
    with pytest.raises(AssertionError, match="test_2652_prefix"):
        qa_manifest.api_sweep_records()


def test_a_stale_override_raises(monkeypatch):
    """An override whose route left the router (or moved class) must be removed, not
    silently ignored — a dead exemption is where the next grandfathered set starts."""
    monkeypatch.setattr(
        qa_manifest,
        "_API_SWEEP_OVERRIDES",
        {**qa_manifest._API_SWEEP_OVERRIDES, "/api/test_2652_ghost": {"expect": "400", "reason": "x" * 80}},
    )
    with pytest.raises(AssertionError, match="test_2652_ghost"):
        qa_manifest.api_sweep_records()


# ── the checker's verdicts (offline, injected transport) ─────────────────────


def _rec(route="/api/x", fetch=None, expect="200"):
    return {"route": route, "fetch": fetch or route, "expect": expect, "reason": ""}


def test_verdict_wrong_status_fails():
    state, detail = api_sweep_check.verdict(_rec(), 404, b"{}", set())
    assert state == "FAIL" and "404" in detail


def test_verdict_200_with_malformed_or_empty_body_fails():
    assert api_sweep_check.verdict(_rec(), 200, b"<html>SIGNAL LOST", set())[0] == "FAIL"
    assert api_sweep_check.verdict(_rec(), 200, b"", set())[0] == "FAIL"


def test_verdict_matching_non_200_expectation_passes_without_json_demand():
    """A param-gated route's validator 400 (or the board_ask 405) is the alive signal;
    the body is not required to be anything in particular."""
    assert api_sweep_check.verdict(_rec(expect="400"), 400, b"", set())[0] == "PASS"
    assert api_sweep_check.verdict(_rec(expect="405"), 405, b"", set())[0] == "PASS"


def test_verdict_transport_failure_warns_not_fails():
    """The #2841 posture: a timeout on a pageless route must not auto-rollback a
    healthy deploy. A dead route answers with an HTTP status and still FAILs."""
    state, detail = api_sweep_check.verdict(_rec(), None, b"", set())
    assert state == "WARN" and "2841" in detail


def test_verdict_pending_deploy_404_warns():
    """#2831: a 404 inside the declared merged-but-not-deployed window is a warning,
    not a rollback trigger — and only for the route that declared it."""
    assert api_sweep_check.verdict(_rec(route="/api/x"), 404, b"", {"/api/x"})[0] == "WARN"
    assert api_sweep_check.verdict(_rec(route="/api/y"), 404, b"", {"/api/x"})[0] == "FAIL"


def test_sweep_runs_offline_with_an_injected_fetcher():
    recs = [_rec("/api/a"), _rec("/api/b", expect="400"), _rec("/api/c")]

    def fetcher(url):
        if "/api/a" in url:
            return 200, b'{"ok": true}'
        if "/api/b" in url:
            return 400, b'{"error": "param"}'
        raise TimeoutError("simulated")

    out = api_sweep_check.sweep(recs, "https://example.invalid", fetcher=fetcher)
    assert [r for r, _ in out["pass"]] == ["/api/a", "/api/b"]
    assert [r for r, _ in out["warn"]] == ["/api/c"]
    assert out["fail"] == []


def test_zero_derived_rows_exits_nonzero(monkeypatch):
    """The blindness detector (#2578's rule): a sweep of zero rows reports exactly
    like a clean sweep unless it is made to fail."""
    monkeypatch.setattr(qa_manifest, "api_sweep_records", lambda: [])
    monkeypatch.setattr(sys, "argv", ["api_sweep_check.py"])
    assert api_sweep_check.main() == 1


# ── consumer wiring: the sweep actually runs, and the numeric rubric reads it ─


def test_the_smoke_invokes_the_sweep():
    """qa_audit counts these routes as swept iff the smoke references the checker —
    so the reference had better exist (the presence rule cuts both ways)."""
    with open(os.path.join(_REPO, "deploy", "smoke_test_site.sh"), encoding="utf-8") as f:
        assert "api_sweep_check.py" in f.read()


def test_accuracy_audits_numeric_denominator_includes_the_sweep():
    """The issue's bar: every route gets the numeric/impossible-value sweep, not just
    a status probe. accuracy_audit must derive these rows, not re-list endpoints."""
    accuracy_audit = importlib.import_module("accuracy_audit")
    src = inspect.getsource(accuracy_audit.live_checks)
    assert "api_sweep_records" in src, "accuracy_audit stopped deriving the long tail — the light_pct hole reopens"


def test_the_sweep_rows_emitter_matches_the_records():
    rows = qa_manifest.api_sweep_rows()
    recs = qa_manifest.api_sweep_records()
    assert rows == [f"{r['route']}|{r['fetch']}|{r['expect']}" for r in recs]
    assert all(len(r.split("|")) == 3 for r in rows)
