#!/usr/bin/env python3
"""scripts/verify_citations.py — the NETWORK half of the citation contract (#1892 box,
wired to a schedule by #3621 box 4).

THE GAP THIS CLOSES
  tests/test_citation_resolution_1892.py's offline half (a `resolved_title` is present,
  no duplicate PMID, no withdrawn citation carries a URL, …) gates every commit. Its
  NETWORK half — does the cited paper still say what we stored? — used to live only
  in that file's `integration`-marked test, and neither it nor this module ran in any
  CI workflow. A retraction or a PMID reassignment across the ~40 PubMed citations in
  `config/supplement_registry.json` (plus a handful more on `experiment_library.json`'s
  `evidence_for`/`evidence_against` arrays) was therefore invisible until a human
  happened to run the integration test by hand. #3621 box 4 wires this module into
  `.github/workflows/citation-network-check.yml` on a monthly schedule instead.

THE ENUMERATION IS OWNED HERE, NOT DUPLICATED
  `supplement_sources()` / `experiment_sources()` / `all_sources()` / `cited_pmid()`
  are the SAME functions the offline test imports (previously each test defined its
  own private copy) — one registry of "what counts as a citation", read by both the
  offline contract and this network verifier. Growing a second enumeration here would
  be exactly the drift #3621 is about, one layer up.

TWO CITATION FAMILIES, TWO IDENTIFIERS
  * PubMed — `pubmed_citations()` walks `all_sources()` and pulls every URL-embedded
    PMID; re-resolved against NCBI's eutils `esummary` endpoint (`check_pubmed`).
  * DOI — three `experiment_library.json` items (`deep-work-block`, `date-night-weekly`,
    `digital-free-dinner`) carry a top-level `source_url`/`source_resolved_title` pair
    that sits OUTSIDE `evidence_for`/`evidence_against`, so `all_sources()` does not see
    them. `doi_citations()` enumerates those three explicitly; `check_doi` re-resolves
    each against Crossref's `/works/{doi}` (which surfaces a retraction as an
    `update-to` entry of type `retraction` — the DOI-side analogue of eutils' PMID
    withdrawal).

FAILURE MODES DETECTED (both families)
  * 404 / did-not-resolve (a withdrawn PMID, a dead DOI)
  * a retraction notice (eutils record status, or Crossref `update-to`)
  * a stored `resolved_title` that no longer matches the live title (PMID reassignment,
    or a live correction to the DOI's title)
  A matching title is the pass control — `verify()` returns no failure for it.

STDLIB ONLY (#3621 box 4 pricing: $0 on a public repo) — `urllib.request`, no
third-party HTTP client, so the scheduled workflow that runs this needs no
`pip install` step at all.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PM = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
_DOI = re.compile(r"doi\.org/(.+)$")

_USER_AGENT = "life-platform-citation-verify/1.0 (+https://averagejoematt.com)"


def _load(name: str):
    with open(os.path.join(REPO_ROOT, "config", name), encoding="utf-8") as fh:
        return json.load(fh)


# ── the enumeration (shared with tests/test_citation_resolution_1892.py) ────────────


def supplement_sources():
    """(location, source_dict) for every source in the supplement registry."""
    sup = _load("supplement_registry.json")
    for gname, g in sup["groups"].items():
        for i, item in enumerate(g["items"]):
            for j, s in enumerate(item.get("sources", []) or []):
                yield f"supplements/{gname}[{i}]:{item['key']}#{j}", s


def experiment_sources():
    """(location, source_dict) for every evidence_for/evidence_against source."""
    exp = _load("experiment_library.json")
    for e in exp["experiments"]:
        eid = e.get("id") or e.get("key") or "?"
        for fld in ("evidence_for", "evidence_against"):
            for j, s in enumerate(e.get(fld) or []):
                if isinstance(s, dict):
                    yield f"experiments/{eid}.{fld}#{j}", s


def all_sources():
    return list(supplement_sources()) + list(experiment_sources())


def cited_pmid(source: dict) -> str | None:
    m = _PM.search(source.get("url") or "")
    return m.group(1) if m else None


def pubmed_citations() -> list[tuple[str, str, str]]:
    """(location, pmid, stored_title) for every PubMed-cited source `all_sources()`
    enumerates — the 40 supplement_registry citations plus experiment_library's
    evidence_for/evidence_against PMIDs."""
    out = []
    for loc, s in all_sources():
        pmid = cited_pmid(s)
        if pmid:
            out.append((loc, pmid, (s.get("resolved_title") or "").strip()))
    return out


def doi_citations() -> list[tuple[str, str, str]]:
    """(location, doi, stored_title) for every experiment carrying a top-level DOI
    `source_url` — the 3 DOIs #3621 box 4 names by number. These sit OUTSIDE
    evidence_for/evidence_against, so all_sources() does not enumerate them."""
    exp = _load("experiment_library.json")
    out = []
    for e in exp["experiments"]:
        m = _DOI.search(e.get("source_url") or "")
        if m:
            out.append((f"experiments/{e.get('id')}.source_url", m.group(1), (e.get("source_resolved_title") or "").strip()))
    return out


# ── network resolution ───────────────────────────────────────────────────────────────


def _fetch_json(url: str, timeout: float = 30.0):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as fh:  # nosec B310 — fixed https hosts only
        return json.load(fh)


def split_unverified(lines: list[str]) -> tuple[list[str], list[str]]:
    """(drift, unverified) — an UNVERIFIED line is a registry that could not be observed
    (429 / 5xx / network); it is reported, never counted as drift and never silently dropped."""
    unverified = [l for l in lines if l.startswith("UNVERIFIED ")]
    return [l for l in lines if not l.startswith("UNVERIFIED ")], unverified


def check_pubmed(pairs: list[tuple[str, str, str]]) -> list[str]:
    """pairs: [(loc, pmid, stored_title)]. Returns one failure string per drifted
    citation: not-found, retracted, or a live title that no longer matches stored."""
    if not pairs:
        return []
    ids = sorted({pmid for _loc, pmid, _title in pairs})
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=" + ",".join(ids)
    try:
        result = _fetch_json(url)["result"]
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        return [f"eutils lookup failed for {len(ids)} PMID(s): {exc}"]
    failures = []
    for loc, pmid, stored in pairs:
        rec = result.get(pmid) or {}
        if rec.get("error"):
            failures.append(f"{loc}: PMID {pmid} — {rec['error']}")
            continue
        status = (rec.get("status") or "").strip().lower()
        live_title = (rec.get("title") or "").strip()
        if not live_title:
            failures.append(f"{loc}: PMID {pmid} did not resolve (404/withdrawn)")
        elif "retract" in status:
            failures.append(f"{loc}: PMID {pmid} is RETRACTED (status={status!r})")
        elif live_title.rstrip(".").lower() != stored.rstrip(".").lower():
            failures.append(f"{loc}: PMID {pmid} is now {live_title!r}, stored {stored!r}")
    return failures


def check_doi(triples: list[tuple[str, str, str]]) -> list[str]:
    """triples: [(loc, doi, stored_title)]. Crossref surfaces a retraction as an
    `update-to` record of type `retraction` — the DOI-side analogue of eutils'
    withdrawn-PMID status."""
    failures = []
    for loc, doi, stored in triples:
        url = f"https://api.crossref.org/works/{doi}"
        try:
            payload = _fetch_json(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                # the registry could not be OBSERVED (rate limit / outage) — that is YELLOW, not
                # drift: a 429 from Crossref reds nothing, but it is never a silent pass either.
                failures.append(f"UNVERIFIED {loc}: DOI {doi} could not be observed (HTTP {exc.code}); retry later")
            else:
                failures.append(f"{loc}: DOI {doi} did not resolve (HTTP {exc.code})")
            continue
        except (urllib.error.URLError, ValueError) as exc:
            failures.append(f"UNVERIFIED {loc}: DOI {doi} could not be observed ({exc})")
            continue
        msg = payload.get("message") or {}
        titles = msg.get("title") or []
        live_title = (titles[0] if titles else "").strip()
        retraction = next((u for u in (msg.get("update-to") or []) if (u.get("type") or "").lower() == "retraction"), None)
        if retraction:
            failures.append(f"{loc}: DOI {doi} carries a RETRACTION notice (-> {retraction.get('DOI')})")
        elif not live_title:
            failures.append(f"{loc}: DOI {doi} resolved with no title")
        elif live_title.rstrip(".").lower() != stored.rstrip(".").lower():
            failures.append(f"{loc}: DOI {doi} is now {live_title!r}, stored {stored!r}")
    return failures


def verify() -> tuple[list[str], dict[str, int]]:
    """Runs both arms. Returns (failures, counts) — counts are printed even on a
    clean run so 'zero found' and 'zero checked' are never confused (a citation
    registry that silently emptied would otherwise pass this check vacuously)."""
    pm_pairs = pubmed_citations()
    doi_triples = doi_citations()
    failures = check_pubmed(pm_pairs) + check_doi(doi_triples)
    return failures, {"pubmed": len(pm_pairs), "doi": len(doi_triples)}


def main(argv: list[str] | None = None) -> int:
    lines, counts = verify()
    drift, unverified = split_unverified(lines)
    print(f"Checked {counts['pubmed']} PubMed citation(s) + {counts['doi']} DOI citation(s) against their live source.")
    if unverified:
        # YELLOW: the registry could not be observed for these — said out loud, exit 0 only if
        # nothing that WAS observed drifted. The cron-freshness dead-man still sees the run.
        print(f"UNVERIFIED ({len(unverified)}) — could not observe, not drift:")
        for u in unverified:
            print(f"  {u}")
    if drift:
        print(f"CITATION DRIFT ({len(drift)}):")
        for f in drift:
            print(f"  {f}")
        return 1
    if unverified:
        print(f"{len(lines) - len(unverified)} observed citation(s) still resolve to their stored title; {len(unverified)} unverified.")
        return 0
    print("All citations still resolve to their stored title.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
