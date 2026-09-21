"""tests/test_verify_citations_3621.py — the citation NETWORK arm runs on a schedule
(#3621 box 4).

THE GAP. tests/test_citation_resolution_1892.py's offline half gates every commit,
but scripts/verify_citations.py's network re-resolution (does a PMID/DOI still say
what we stored — a 404, a retraction, a title that drifted?) ran in ZERO workflows:
a retraction or PMID reassignment across the ~40 supplement_registry PubMed
citations + 3 experiment_library DOIs was invisible until a human ran the
`integration`-marked test by hand.

THIS FILE covers what #1892's own suite structurally cannot (it must stay
network-free to run in the pre-merge lane):
  * the enumeration — pure counts, cross-checked against an independently-written
    regex sweep of the same JSON, never the module's own logic reused as its own
    proof;
  * every failure mode `check_pubmed`/`check_doi` must detect — a 404, a
    retraction, a stored-title mismatch — each with a matching-title PASS control,
    so a detector that always reports drift (or never does) is caught either way;
  * the workflow's shape: a schedule exists, the step actually runs
    scripts/verify_citations.py, and the workflow is registered `watched` in
    scripts/scheduled_workflow_registry.py so scripts/check_cron_freshness.py — the
    platform's silence-is-not-a-pass dead-man — reports if this cron ever stops.

NO NETWORK CALLS ANYWHERE IN THIS FILE (none of these tests carry `@pytest.mark.
integration`) — every eutils/Crossref response is a canned fixture passed through
monkeypatched `verify_citations._fetch_json`, which is the one function that ever
calls `urllib.request.urlopen`.
"""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import scheduled_workflow_registry as reg  # noqa: E402
import verify_citations as vc  # noqa: E402

_WORKFLOW = os.path.join(_REPO, ".github", "workflows", "citation-network-check.yml")


# ── the enumeration (cross-checked against an independent regex sweep) ──────────────


def _independent_supplement_pmid_count():
    """A hand-rolled recount of config/supplement_registry.json, written without
    calling any verify_citations function — so this is a real cross-check, not the
    module proving itself with its own logic."""
    path = os.path.join(_REPO, "config", "supplement_registry.json")
    data = json.load(open(path, encoding="utf-8"))
    pat = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
    n = 0
    for g in data["groups"].values():
        for item in g["items"]:
            for s in item.get("sources") or []:
                if pat.search(s.get("url") or ""):
                    n += 1
    return n


def _independent_doi_count():
    path = os.path.join(_REPO, "config", "experiment_library.json")
    data = json.load(open(path, encoding="utf-8"))
    from urllib.parse import urlparse

    # host check, not a substring (CodeQL py/incomplete-url-substring-sanitization)
    return sum(1 for e in data["experiments"] if urlparse(e.get("source_url") or "").netloc in ("doi.org", "dx.doi.org"))


def test_pubmed_enumeration_includes_the_full_supplement_registry_count():
    """#3621 box 4 names '40 supplement_registry citations' explicitly as in scope."""
    pairs = vc.pubmed_citations()
    supplement_pairs = [p for p in pairs if p[0].startswith("supplements/")]
    assert len(supplement_pairs) == _independent_supplement_pmid_count()
    assert len(supplement_pairs) >= 30, "population floor — a derivation returning near-zero has gone blind"


def test_doi_enumeration_finds_the_3_dois_box_4_names():
    """These sit OUTSIDE evidence_for/evidence_against, so all_sources() alone never
    reaches them — doi_citations() is a second, deliberate enumeration."""
    triples = vc.doi_citations()
    assert len(triples) == _independent_doi_count()
    assert len(triples) == 3, triples


def test_every_pubmed_citation_carries_a_pmid_and_stored_title():
    for loc, pmid, stored in vc.pubmed_citations():
        assert pmid.isdigit(), (loc, pmid)
        assert stored, f"{loc} has no stored_title to compare drift against"


def test_every_doi_citation_carries_a_doi_and_stored_title():
    for loc, doi, stored in vc.doi_citations():
        assert "/" in doi, (loc, doi)
        assert stored, f"{loc} has no stored_title to compare drift against"


# ── check_pubmed: every failure mode, each with a matching-title pass control ───────


def _esummary(pmid, title=None, status=None, error=None):
    rec = {}
    if title is not None:
        rec["title"] = title
    if status is not None:
        rec["status"] = status
    if error is not None:
        rec["error"] = error
    return {"result": {pmid: rec}}


def test_check_pubmed_passes_when_the_live_title_matches_stored(monkeypatch):
    monkeypatch.setattr(vc, "_fetch_json", lambda url, timeout=30.0: _esummary("111", title="A Real Paper Title."))
    failures = vc.check_pubmed([("loc/a", "111", "A Real Paper Title")])
    assert failures == [], failures


def test_check_pubmed_reports_a_404(monkeypatch):
    """No live title at all — eutils' shape for a withdrawn/never-existed PMID."""
    monkeypatch.setattr(vc, "_fetch_json", lambda url, timeout=30.0: _esummary("222", title=""))
    failures = vc.check_pubmed([("loc/b", "222", "Some Stored Title")])
    assert len(failures) == 1
    assert "222" in failures[0] and "did not resolve" in failures[0]


def test_check_pubmed_reports_a_retraction(monkeypatch):
    monkeypatch.setattr(vc, "_fetch_json", lambda url, timeout=30.0: _esummary("333", title="Retracted: Some Paper", status="retracted"))
    failures = vc.check_pubmed([("loc/c", "333", "Retracted: Some Paper")])
    assert len(failures) == 1
    assert "RETRACTED" in failures[0]


def test_check_pubmed_reports_a_title_mismatch(monkeypatch):
    monkeypatch.setattr(vc, "_fetch_json", lambda url, timeout=30.0: _esummary("444", title="A Completely Different Paper"))
    failures = vc.check_pubmed([("loc/d", "444", "The Originally Cited Paper")])
    assert len(failures) == 1
    assert "444" in failures[0] and "is now" in failures[0]


def test_check_pubmed_reports_an_eutils_error_record(monkeypatch):
    monkeypatch.setattr(vc, "_fetch_json", lambda url, timeout=30.0: _esummary("555", error="cannot get document summary"))
    failures = vc.check_pubmed([("loc/e", "555", "Stored Title")])
    assert len(failures) == 1 and "555" in failures[0]


def test_check_pubmed_with_no_pairs_makes_no_network_call(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("check_pubmed must not call _fetch_json with zero pairs")

    monkeypatch.setattr(vc, "_fetch_json", _boom)
    assert vc.check_pubmed([]) == []


# ── check_doi: same three failure modes + pass control ──────────────────────────────


def _crossref(title=None, retracted_doi=None):
    msg: dict = {}
    if title is not None:
        msg["title"] = [title]
    if retracted_doi:
        msg["update-to"] = [{"type": "retraction", "DOI": retracted_doi}]
    return {"message": msg}


def test_check_doi_passes_when_the_live_title_matches_stored(monkeypatch):
    monkeypatch.setattr(vc, "_fetch_json", lambda url, timeout=30.0: _crossref(title="A Real Paper Title."))
    failures = vc.check_doi([("loc/a", "10.1/abc", "A Real Paper Title")])
    assert failures == [], failures


def test_check_doi_reports_a_404(monkeypatch):
    import urllib.error

    def _raise(url, timeout=30.0):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(vc, "_fetch_json", _raise)
    failures = vc.check_doi([("loc/b", "10.1/dead", "Some Stored Title")])
    assert len(failures) == 1
    assert "10.1/dead" in failures[0] and "404" in failures[0]


def test_check_doi_reports_a_retraction(monkeypatch):
    monkeypatch.setattr(vc, "_fetch_json", lambda url, timeout=30.0: _crossref(title="Some Paper", retracted_doi="10.1/retraction-notice"))
    failures = vc.check_doi([("loc/c", "10.1/retracted-paper", "Some Paper")])
    assert len(failures) == 1
    assert "RETRACTION" in failures[0]


def test_check_doi_reports_a_title_mismatch(monkeypatch):
    monkeypatch.setattr(vc, "_fetch_json", lambda url, timeout=30.0: _crossref(title="A Completely Different Paper"))
    failures = vc.check_doi([("loc/d", "10.1/reassigned", "The Originally Cited Paper")])
    assert len(failures) == 1
    assert "is now" in failures[0]


def test_verify_combines_both_arms_and_reports_counts(monkeypatch):
    monkeypatch.setattr(vc, "pubmed_citations", lambda: [("loc/a", "1", "T")])
    monkeypatch.setattr(vc, "doi_citations", lambda: [("loc/b", "10.1/x", "U")])
    monkeypatch.setattr(vc, "check_pubmed", lambda pairs: ["pubmed drift"])
    monkeypatch.setattr(vc, "check_doi", lambda triples: ["doi drift"])
    failures, counts = vc.verify()
    assert failures == ["pubmed drift", "doi drift"]
    assert counts == {"pubmed": 1, "doi": 1}


def test_main_exits_nonzero_on_drift_and_zero_when_clean(monkeypatch, capsys):
    monkeypatch.setattr(vc, "verify", lambda: (["a citation drifted"], {"pubmed": 1, "doi": 0}))
    assert vc.main([]) == 1
    assert "CITATION DRIFT" in capsys.readouterr().out

    monkeypatch.setattr(vc, "verify", lambda: ([], {"pubmed": 1, "doi": 0}))
    assert vc.main([]) == 0
    assert "All citations still resolve" in capsys.readouterr().out


# ── the workflow itself: scheduled, runs the verifier, watched by the dead-man ──────


def _workflow_doc():
    yaml = pytest.importorskip("yaml")
    with open(_WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_the_workflow_file_exists_and_declares_a_schedule():
    assert os.path.isfile(_WORKFLOW), "citation-network-check.yml is missing"
    doc = _workflow_doc()
    on = doc.get("on") or doc.get(True) or {}  # PyYAML parses bare `on:` as boolean True on some loaders
    schedules = (on.get("schedule") or []) if isinstance(on, dict) else []
    assert schedules, "no on.schedule declared"
    cron_expr = schedules[0]["cron"]
    assert len(cron_expr.split()) == 5, cron_expr
    assert "workflow_dispatch" in on, "no manual-trigger escape hatch"


def test_the_workflow_actually_invokes_the_verifier_script():
    raw = open(_WORKFLOW, encoding="utf-8").read()
    assert "scripts/verify_citations.py" in raw


def test_the_workflow_cadence_is_monthly_per_3621s_pricing_note():
    """#3621 box 4: 'monthly ... demote to quarterly after 12 clean monthly runs' —
    this only pins the CURRENT declared cadence; the demotion is a future, separate
    registry edit, not something this test can (or should) anticipate."""
    doc = _workflow_doc()
    on = doc.get("on") or doc.get(True) or {}
    cron_expr = on["schedule"][0]["cron"]
    gap = reg.cron_max_gap_hours(cron_expr)
    assert 27 * 24 <= gap <= 32 * 24, f"cron {cron_expr!r} does not read as monthly (gap {gap}h)"


def test_the_workflow_is_registered_watched_in_the_scheduled_workflow_registry():
    policy = reg.WATCH_POLICY.get("citation-network-check.yml")
    assert policy is not None, "citation-network-check.yml has no WATCH_POLICY row — unruled_workflows() would report it"
    assert policy["watched"] is True
    assert policy["grace_hours"] and policy["grace_hours"] > 0
    assert policy["basis"], "a grace_hours with no basis is the thing ADR-105 forbids"
    assert policy["reason"], "watched=True with no reason is a silent ruling"


def test_the_registry_agrees_the_workflow_is_watched_and_not_orphaned():
    rows = reg.discover_scheduled_workflows()
    assert "citation-network-check.yml" in rows
    assert rows["citation-network-check.yml"]["watched"] is True
    assert "citation-network-check.yml" not in reg.unruled_workflows()
    assert "citation-network-check.yml" not in reg.orphaned_policy_rows()
