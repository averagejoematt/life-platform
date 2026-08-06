"""tests/test_experiment_library_citations_1983.py — an experiment-library citation is
either a resolving link or an honest "no direct study" label. Never prose alone.

THE DEFECT (#1983). 63 of 67 entries in `config/experiment_library.json` carried an
`evidence_citation` prose string ("Wilkinson et al., Cell Metabolism 2020") and nothing
else — the public catalog rendered "src: <author, journal, year>" with no way for a
reader to check it. `source_url` was not even a field: the site API derived it from
`evidence_for[0].url`, so the 4 entries that DID link were linking whatever paper
happened to sit first in a different list. That is how nmn shipped a real 2023 RCT
under the label "Yoshino et al., Science 2021".

THE CONTRACT (same family as #1892's, extended to this file).

  * Every entry carries `citation_status`, exactly one of:
      - "verified"        → `source_url` is set AND `source_resolved_title` stores the
                            title the resolver returned, verbatim, at verification time.
      - "no-direct-study" → `source_url` is null AND `citation_note` says why.
  * No entry may carry a URL without a resolved title (that is an unverified claim
    about a paper — precisely #1892's shape).
  * No entry may carry a `source_url` while claiming "no-direct-study".
  * A "no-direct-study" entry must not carry citation prose that reads as a study
    citation without saying so — its `evidence_citation` must announce the absence.
  * URLs are PubMed record links or DOI links; a `?term=` search URL is not a citation.

The offline half gates every commit. The network half (`integration`) re-resolves each
PubMed record against NCBI and each DOI against Crossref and fails on a 404, a
withdrawal, or a title that no longer matches what is stored.
"""

import json
import os
import re

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_REPO, "config", "experiment_library.json")
_TWIN = os.path.join(_REPO, "site", "config", "experiment_library.json")

_PUBMED = re.compile(r"^https://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/?$")
_DOI = re.compile(r"^https://doi\.org/(10\.\d{4,9}/\S+)$")

_STATUSES = {"verified", "no-direct-study"}


def _experiments():
    with open(_LIB, encoding="utf-8") as fh:
        return json.load(fh)["experiments"]


# ── the offline contract ────────────────────────────────────────────────────


def test_every_entry_declares_a_citation_status():
    """The whole point: 'has prose, no link' is no longer a representable state."""
    bad = [e["id"] for e in _experiments() if e.get("citation_status") not in _STATUSES]
    assert not bad, "entry(ies) with no citation_status — every experiment must declare either " f"'verified' or 'no-direct-study': {bad}"


def test_a_verified_entry_has_a_url_and_the_resolved_paper_title():
    """A URL with no resolved title is an unverified claim about a paper (#1892)."""
    bad = []
    for e in _experiments():
        if e.get("citation_status") != "verified":
            continue
        if not (e.get("source_url") or "").strip():
            bad.append(f"{e['id']}: citation_status=verified but no source_url")
        elif not (e.get("source_resolved_title") or "").strip():
            bad.append(f"{e['id']}: has a source_url but no source_resolved_title")
    assert not bad, "resolve the source and store the real title beside the claim:\n  " + "\n  ".join(bad)


def test_a_no_study_entry_carries_no_url_and_explains_itself():
    """The honest form is a claim with NO citation plus a reason — not a bare claim."""
    bad = []
    for e in _experiments():
        if e.get("citation_status") != "no-direct-study":
            continue
        if e.get("source_url"):
            bad.append(f"{e['id']}: labelled no-direct-study but carries a source_url")
        if not (e.get("citation_note") or "").strip():
            bad.append(f"{e['id']}: no-direct-study with no citation_note explaining why")
        if "no direct study" not in (e.get("evidence_citation") or "").lower():
            bad.append(f"{e['id']}: evidence_citation still reads as a study citation: {e.get('evidence_citation')!r}")
    assert not bad, "\n  " + "\n  ".join(bad)


def test_no_url_bearing_entry_is_missing_its_citation_prose():
    """A resolving link with no author/journal/year prose is unattributed."""
    bad = [e["id"] for e in _experiments() if e.get("source_url") and not (e.get("evidence_citation") or "").strip()]
    assert not bad, f"linked entry(ies) with no citation prose: {bad}"


def test_source_urls_are_record_links_not_searches():
    """#1216's lesson: a `?term=` search URL is a gesture at a literature, not a citation."""
    bad = []
    for e in _experiments():
        url = e.get("source_url")
        if not url:
            continue
        if not (_PUBMED.match(url) or _DOI.match(url)):
            bad.append(f"{e['id']}: {url}")
    assert not bad, "source_url must be a PubMed record link or a DOI link:\n  " + "\n  ".join(bad)


def test_the_2026_08_01_fabrications_are_not_cited_here():
    """Replay of #1892's withdrawn PMIDs against this file's new URL field."""
    fabricated = {
        "23615780",  # neighborhood dental visits, cited for tongkat ali
        "22198837",  # histone chaperone, cited for berberine AMPK
        "24629205",
        "17284826",
        "25974857",
        "27510537",
        "26905542",
        "28954909",
    }
    live = set()
    for e in _experiments():
        m = _PUBMED.match(e.get("source_url") or "")
        if m:
            live.add(m.group(1))
    assert not (live & fabricated), f"a withdrawn fabricated citation is live again: {sorted(live & fabricated)}"


def test_the_nmn_misattribution_stays_fixed():
    """#1983's headline: 'Yoshino et al., Science 2021' pointed at a 2023 multicenter
    RCT by different authors. The citation prose and the link must name one paper."""
    nmn = next(e for e in _experiments() if e["id"] == "nmn-nad-precursor")
    assert "Yoshino" in nmn["evidence_citation"], "nmn citation prose changed — re-check the link matches it"
    assert nmn["source_url"] == "https://pubmed.ncbi.nlm.nih.gov/33888596/", (
        "nmn source_url must be the Yoshino et al. Science 2021 record the citation names, " f"got {nmn.get('source_url')!r}"
    )
    assert "insulin sensitivity in prediabetic women" in (nmn.get("source_resolved_title") or "").lower()


def test_the_twin_stays_in_sync():
    """The library is SERVED from S3 config/, synced from site/config/ — a fix applied
    only to the repo-root copy never reaches a reader (#2019)."""
    with open(_LIB, encoding="utf-8") as fh:
        root = fh.read()
    with open(_TWIN, encoding="utf-8") as fh:
        site = fh.read()
    assert root == site, "config/ and site/config/ experiment_library.json diverged — the served copy is site/config/"


# ── the network half (opt-in; catches retraction + record drift) ────────────


@pytest.mark.integration
def test_every_citation_still_resolves_to_its_stored_title():
    import urllib.parse
    import urllib.request

    pubmed, dois = {}, {}
    for e in _experiments():
        url = e.get("source_url") or ""
        title = e.get("source_resolved_title") or ""
        m = _PUBMED.match(url)
        if m:
            pubmed[e["id"]] = (m.group(1), title)
            continue
        m = _DOI.match(url)
        if m:
            dois[e["id"]] = (m.group(1), title)

    drift = []

    ids = sorted({p for p, _t in pubmed.values()})
    api = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=" + ",".join(ids)
    with urllib.request.urlopen(api, timeout=45) as fh:
        result = json.load(fh)["result"]
    for eid, (pmid, stored) in sorted(pubmed.items()):
        live = ((result.get(pmid) or {}).get("title") or "").strip()
        if not live:
            drift.append(f"{eid}: PMID {pmid} did not resolve (404/withdrawn)")
        elif live.rstrip(".").lower() != stored.rstrip(".").lower():
            drift.append(f"{eid}: PMID {pmid} is now {live!r}, stored {stored!r}")

    for eid, (doi, stored) in sorted(dois.items()):
        api = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
        with urllib.request.urlopen(api, timeout=45) as fh:
            msg = json.load(fh)["message"]
        live = ((msg.get("title") or [""])[0]).strip()
        if not live:
            drift.append(f"{eid}: DOI {doi} did not resolve")
        elif live.rstrip(".").lower() != stored.rstrip(".").lower():
            drift.append(f"{eid}: DOI {doi} is now {live!r}, stored {stored!r}")

    assert not drift, "citation drift:\n  " + "\n  ".join(drift)
