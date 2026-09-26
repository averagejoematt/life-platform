"""tests/test_site_vocabulary_registry.py — the reader-facing vocabulary registry, guarded (#4182).

The registry is site/data/glossary.json (charter primitive 1). This is its derivation guard
and ratchet (primitives 2 + 3): every registered term is counted across reader pages' STATIC
main content (tests/site_text.py), and the count may only move down against the dated ledger
in tests/site_vocabulary_residue.py. A keep-with-gloss term counts only on pages with no gloss
affordance (<dfn> / <abbr title>), so glossing a page is how its count falls.

Why: the 2026-09-26 audit found 71 of 88 reader pages using builder vocabulary undefined and
zero <dfn> on the whole site; the owner's friends could not follow the words. See
docs/SITE_TRANSFORMATION_V6.md §6 for the fifteen rulings.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from tests import site_text
from tests.site_vocabulary_residue import BASELINE

REGISTRY = os.path.join(site_text.REPO, "site", "data", "glossary.json")
RULINGS = {"rename", "cut", "keep-with-gloss"}
_GLOSS_RE = re.compile(r"<dfn\b|<abbr\b[^>]*\btitle=", re.I)


def _registry() -> dict:
    with open(REGISTRY, encoding="utf-8") as f:
        return json.load(f)


def _term_re(term: str) -> re.Pattern:
    # word-bounded, case-insensitive; a space in the term also matches "_" (as_of)
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term).replace(r"\ ", r"[\s_]") + r"(?![A-Za-z0-9])", re.I)


def _has_gloss(rel: str) -> bool:
    with open(os.path.join(site_text.REPO, rel), encoding="utf-8") as f:
        return bool(_GLOSS_RE.search(f.read()))


def census() -> dict[str, list[str]]:
    """term -> reader pages that still carry it (ungloss'd, for keep-with-gloss terms)."""
    reg = _registry()
    pages = site_text.reader_pages()
    texts = {p: site_text.main_text(p) for p in pages}
    out: dict[str, list[str]] = {}
    for t in reg["terms"]:
        rx = _term_re(t["term"])
        hits = [p for p in pages if rx.search(texts[p])]
        if t["ruling"] == "keep-with-gloss":
            hits = [p for p in hits if not _has_gloss(p)]
        out[t["term"]] = hits
    return out


def test_registry_shape():
    reg = _registry()
    assert reg["terms"], "the registry is empty"
    seen = set()
    for t in reg["terms"]:
        assert t["ruling"] in RULINGS, t
        assert t["term"] and t["reader_form"] and t["gloss"], t
        assert t["term"].lower() not in seen, f"duplicate term {t['term']!r}"
        seen.add(t["term"].lower())


def test_every_registered_term_has_a_ledger_row_and_vice_versa():
    reg = _registry()
    terms = {t["term"] for t in reg["terms"]}
    assert terms == set(BASELINE), f"registry/ledger drift: only-in-registry={terms - set(BASELINE)} only-in-ledger={set(BASELINE) - terms}"


@pytest.mark.parametrize("term", sorted(BASELINE))
def test_builder_vocabulary_only_ratchets_down(term):
    """A term's reader-page count may not exceed its dated baseline. Shrinking is always
    allowed; tightening the ledger after a real pass is welcome."""
    hits = census()[term]
    assert len(hits) <= BASELINE[term], (
        f"{term!r} now on {len(hits)} reader pages (ledger {BASELINE[term]}): builder vocabulary "
        f"may only leave reader pages. Pages: {[site_text.page_url(p) for p in hits]}"
    )


def test_census_is_not_vacuous():
    """The guard must be able to see a term — a page that carries one is found."""
    c = census()
    assert any(c.values()), "the census found no term on any page — the extractor is blind"
    # "Third Wall" (ruled cut) is the specimen: it was on 9 pages at landing.
    assert "Third Wall" in c
