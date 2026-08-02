"""tests/test_citation_resolution_1892.py — a citation must resolve to the paper it claims.

THE DEFECT (#1892). 20 PubMed citations on the two live public registries pointed
at completely unrelated papers: NAC's three sources resolved to a bacterial
sphingomyelinase, post-caesarean gum chewing, and a working-hours survey;
myo-inositol's three to metabolite profiling, sentinel lymph nodes, and whale
falls; the ACTIVE tongkat-ali protocol cited a paper on neighborhood dental
visits and carried an invented 'cortisol -16% / testosterone +37%' summary.

WHY THE PREVIOUS GUARD MISSED IT. #1216's check (tests/test_supplement_registry.py)
validates the URL SHAPE only — it rejects `?term=` searches and accepts
`/\\d+/`. Replacing a search URL with plausible-looking digits passed it cleanly.
A citation's identity is the PAPER, not the URL's grammar.

THE CONTRACT. Every citation now stores `resolved_title` — the real PubMed title,
fetched from NCBI at the time it was verified. That turns an unverifiable claim
("this PMID supports X") into a checkable one, two ways:

  * OFFLINE (this file, always runs): every url-bearing source MUST carry a
    non-empty resolved_title, so a new citation cannot be added without someone
    resolving it; withdrawn citations carry no url; no item cites the same PMID
    twice; and any item with zero surviving citations must not claim more than
    'emerging' evidence.
  * NETWORK (scripts/verify_citations.py, and the `integration` test below):
    re-resolves every PMID against NCBI and fails on a 404, a retraction, or a
    title that no longer matches what is stored.

The offline half is the one that gates every commit; the network half catches
retractions and PMID reassignment on demand without making the unit lane depend
on eutils being up.
"""

import json
import os
import re

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PM = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")


def _load(name):
    with open(os.path.join(_REPO, "config", name), encoding="utf-8") as fh:
        return json.load(fh)


def _supplement_sources():
    """(location, source_dict) for every source in the supplement registry."""
    sup = _load("supplement_registry.json")
    for gname, g in sup["groups"].items():
        for i, item in enumerate(g["items"]):
            for j, s in enumerate(item.get("sources", []) or []):
                yield f"supplements/{gname}[{i}]:{item['key']}#{j}", s


def _experiment_sources():
    exp = _load("experiment_library.json")
    for e in exp["experiments"]:
        eid = e.get("id") or e.get("key") or "?"
        for fld in ("evidence_for", "evidence_against"):
            for j, s in enumerate(e.get(fld) or []):
                if isinstance(s, dict):
                    yield f"experiments/{eid}.{fld}#{j}", s


def _all_sources():
    return list(_supplement_sources()) + list(_experiment_sources())


def _cited(source):
    m = _PM.search(source.get("url") or "")
    return m.group(1) if m else None


# ── the offline contract ────────────────────────────────────────────────────


def test_every_citation_carries_the_resolved_paper_title():
    """A PMID without a resolved title is an unverified claim about a paper."""
    missing = [loc for loc, s in _all_sources() if _cited(s) and not (s.get("resolved_title") or "").strip()]
    assert not missing, (
        "Citation(s) with no resolved_title — resolve the PMID against NCBI and store the real "
        "paper title beside the claim (that is what makes the citation checkable):\n  " + "\n  ".join(missing)
    )


def test_withdrawn_citations_carry_no_url():
    """The honest form is a claim with NO citation, not a claim with a bad one."""
    bad = [loc for loc, s in _all_sources() if "open question" in (s.get("title") or "").lower() and s.get("url")]
    assert not bad, f"an 'Open question' entry must not carry a citation URL: {bad}"


def test_no_item_cites_the_same_paper_twice():
    """Two different claims backed by one PMID means at least one is mislabeled
    (that is how #1892's electrolytes/glutamine/cordyceps mislabels read)."""
    sup = _load("supplement_registry.json")
    dupes = []
    for gname, g in sup["groups"].items():
        for item in g["items"]:
            pmids = [p for p in (_cited(s) for s in item.get("sources", []) or []) if p]
            for pmid, n in {p: pmids.count(p) for p in pmids}.items():
                if n > 1:
                    dupes.append(f"{gname}:{item['key']} cites {pmid} {n}×")
    assert not dupes, f"one paper backing two distinct claims: {dupes}"


def test_an_item_with_no_citations_cannot_claim_more_than_emerging_evidence():
    """An evidence rating is a claim about evidence. With every citation
    withdrawn, 'moderate' is exactly the kind of unearned number #1892 is about."""
    sup = _load("supplement_registry.json")
    bad = []
    for gname, g in sup["groups"].items():
        for item in g["items"]:
            if not [s for s in item.get("sources", []) or [] if s.get("url")]:
                if item.get("ev") != "emerging" or (item.get("evPct") or 100) > 33:
                    bad.append(f"{gname}:{item['key']} ev={item.get('ev')} evPct={item.get('evPct')}")
                assert item.get("evidence_note"), f"{gname}:{item['key']} must explain why it has no citations"
    assert not bad, f"item(s) claiming evidence they no longer cite: {bad}"


def test_the_2026_08_01_fabrications_are_gone():
    """Replay: the specific PMIDs the #1892 audit resolved to unrelated papers
    must not be cited anywhere in either registry."""
    fabricated = {
        "17693028",  # near-infrared stroke therapy, cited for glycine sleep
        "27253365",  # Zika reply, cited for glycine effect size
        "10802676",  # GFP cardiomyopathy, cited for apigenin GABA-A
        "25920354",  # precision medicine, cited for electrolytes
        "27053525",  # mTORC1/leucine, cited for collagen synthesis
        "28426424",  # Demodex cDNA, cited for glutamine gut barrier
        "26462366",  # celery seed, cited for reishi
        "23647674",  # intranasal curcumin, cited for zinc/copper
        "24629205",  # gum chewing, cited for NAC
        "17284826",  # sphingomyelinase, cited for NAC
        "25974857",  # working time, cited for NAC
        "17921406",  # skin aging, cited for multivitamin
        "36129998",  # Tofersen ALS, cited as the COSMOS trial
        "29495902",  # postpartum depression, cited for B6 neuropathy
        "27510537",  # metabolite profiles, cited for myo-inositol
        "26905542",  # sentinel lymph node, cited for inositol
        "28954909",  # whale falls, cited for inositol/PCOS
        "22747440",  # thyroid carcinoma miRNA, cited for green tea
        "23615780",  # neighborhood dental visits, cited for tongkat ali
        "22198837",  # histone chaperone, cited for berberine AMPK
    }
    live = {p for p in (_cited(s) for _loc, s in _all_sources()) if p}
    assert not (live & fabricated), f"a withdrawn fabricated citation is live again: {sorted(live & fabricated)}"


def test_the_invented_tongkat_quantitative_summary_is_gone():
    raw = open(os.path.join(_REPO, "config", "experiment_library.json"), encoding="utf-8").read()
    assert "cortisol 16%" not in raw and "testosterone 37%" not in raw, "the invented effect sizes are back"


def test_the_supplement_registry_twin_stays_in_sync():
    """The registry is SERVED from S3 config/, which is synced from site/config/ —
    so a fix applied only to the repo-root copy never reaches a reader. Both
    copies must be byte-identical (the same trap experiment_library.json's guard
    already covers)."""
    root = open(os.path.join(_REPO, "config", "supplement_registry.json"), encoding="utf-8").read()
    site = open(os.path.join(_REPO, "site", "config", "supplement_registry.json"), encoding="utf-8").read()
    assert root == site, "config/ and site/config/ supplement_registry.json diverged — the served copy is site/config/"


# ── the network half (opt-in; catches retraction + PMID drift) ──────────────


@pytest.mark.integration
def test_every_citation_still_resolves_to_its_stored_title():
    import urllib.request

    pairs = [(loc, _cited(s), s["resolved_title"]) for loc, s in _all_sources() if _cited(s)]
    ids = sorted({p for _l, p, _t in pairs})
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=" + ",".join(ids)
    with urllib.request.urlopen(url, timeout=30) as fh:
        result = json.load(fh)["result"]
    drift = []
    for loc, pmid, stored in pairs:
        rec = result.get(pmid) or {}
        live_title = (rec.get("title") or "").strip()
        if not live_title:
            drift.append(f"{loc}: PMID {pmid} did not resolve (404/withdrawn)")
        elif live_title.rstrip(".").lower() != stored.rstrip(".").lower():
            drift.append(f"{loc}: PMID {pmid} is now {live_title!r}, stored {stored!r}")
    assert not drift, "citation drift:\n  " + "\n  ".join(drift)
