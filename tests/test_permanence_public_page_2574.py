#!/usr/bin/env python3
"""The public terms page cannot drift from the contract (#2574).

#1400 wrote the Permanence Contract twice — prose in
``docs/PERMANENCE_CONTRACT.md``, data in
``lambdas/operational/permanence_terms.py`` — and
``tests/test_permanence_contract_1400.py`` pins those two together. #2574 adds a
third surface, the public page at ``/privacy/#permanence``, and this file is the
pin for it.

The failure mode being designed against is specific and boring: somebody edits a
clause on the website. A clause that exists in three places and is enforced in
two is not a contract, it is three drafts. So the page's clause list is
*generated* (``scripts/v4_build_permanence_terms.py``) and this file asserts the
checked-in HTML is exactly what the generator produces from the document today.

The second thing asserted here is what the page must NOT say. The draft contract
carried a clause granting readers standing permission to mirror and redistribute
the archive; it was cut before merge, and the limits clause now says in as many
words that this edition grants no mirroring rights. Copy that invites mirroring
would contradict the terms it sits beside — so the page is checked for it.
"""

from __future__ import annotations

import html
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for extra in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "scripts")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import v4_build_permanence_terms as builder  # noqa: E402
from operational import permanence_terms as terms  # noqa: E402

PAGE = os.path.join(ROOT, "site", "privacy", "index.html")


@pytest.fixture(scope="module")
def page() -> str:
    with open(PAGE, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def generated_block(page: str) -> str:
    start = page.index(builder.PAGE_START)
    end = page.index(builder.PAGE_END) + len(builder.PAGE_END)
    return page[start:end]


# ── the page is derived, not typed ──────────────────────────────────────────
def test_the_checked_in_page_is_what_the_generator_produces(page: str):
    """The whole point. If this fails, run:
    ``python3 scripts/v4_build_permanence_terms.py``."""
    assert builder.build() == page, "site/privacy/index.html has drifted from docs/PERMANENCE_CONTRACT.md — regenerate it"


def test_every_clause_reaches_the_reader(generated_block: str):
    for clause in terms.CLAUSES:
        assert f'id="clause-{clause["id"]}"' in generated_block, f"{clause['id']} is in the contract but not on the page"
        assert html.escape(clause["title"]) in generated_block, f"{clause['id']}: title missing from the page"


def test_the_page_carries_no_clause_the_contract_does_not(generated_block: str):
    rendered = set(re.findall(r'id="clause-(P\d+)"', generated_block))
    assert rendered == {c["id"] for c in terms.CLAUSES}


def test_clause_text_is_verbatim(generated_block: str):
    """First-sentence substring check against the coded text, matching the
    1400 gate's method — the page must not paraphrase a term."""
    normalised = re.sub(r"\s+", " ", generated_block)
    for clause in terms.CLAUSES:
        first_sentence = clause["text"].split(". ")[0]
        assert html.escape(first_sentence) in normalised, f"{clause['id']}: the page no longer opens with the contract's own words"


# ── what the reader must not be told ────────────────────────────────────────
def test_the_page_leaks_no_infrastructure_detail(generated_block: str):
    lowered = generated_block.lower()
    leaks = [tell for tell in builder.INFRA_TELLS if tell in lowered]
    assert not leaks, f"the public terms leak infrastructure detail: {leaks}"


_MIRRORING_INVITATIONS = (
    "you may keep a copy",
    "you may mirror",
    "feel free to mirror",
    "permission to mirror",
    "please mirror",
    "you are welcome to redistribute",
    "redistribute it freely",
    "host your own copy",
)


def test_the_page_does_not_invite_mirroring(page: str):
    """P5 "You may keep a copy" was cut from the contract before it merged, and
    the limits clause states that this edition grants no mirroring rights.
    Withholding permission is not a prohibition — ordinary copyright simply
    applies — but the page must not imply a grant the contract does not make."""
    lowered = re.sub(r"\s+", " ", page.lower())
    found = [phrase for phrase in _MIRRORING_INVITATIONS if phrase in lowered]
    assert not found, f"the page implies a mirroring grant the contract withholds: {found}"


def test_the_limits_clause_still_says_no_mirroring_rights():
    limit = terms.clause("P7")
    assert "grants no mirroring rights" in limit["text"], "P7 no longer withholds mirroring — the page's copy assumes it does"


# ── the version is read live, never baked in ────────────────────────────────
def test_the_version_is_not_stated_as_static_copy(page: str, generated_block: str):
    """The issue's own note: a stated version must come from the published
    continuity document. The built-from edition may ride on a data attribute
    (the script reconciles the two and speaks up on a mismatch), but the number
    must appear nowhere a reader reads it as fact."""
    assert f'data-built-version="{terms.TERMS_VERSION}"' in generated_block
    stripped = re.sub(r'data-built-version="[^"]*"', "", page)
    assert terms.TERMS_VERSION not in stripped, "the contract version is hard-coded into the page's visible copy"
    assert 'data-perm="version"' in page, "the page has no slot for the live edition"


def test_the_live_panel_reads_both_published_documents(page: str):
    for url in ("/archive/manifest.json", "/archive/continuity.json", "/archive/latest.tar.gz"):
        assert url in page, f"the page never references {url}"
    for slot in ("built", "bytes", "entries", "version", "state", "sha", "note"):
        assert f'data-perm="{slot}"' in page, f"the live panel has no {slot} slot"


def test_absent_numbers_are_stated_absent_not_blank(page: str):
    """ADR-104 on the front end: a fetch that fails must say so. Guarding the
    literal because a refactor that drops it renders an empty box, which reads
    as zero."""
    assert 'var ABSENT = "not available";' in page
    assert 'el.setAttribute("data-absent", "1")' in page


def test_a_malformed_two_hundred_is_explained_not_silently_blank(page: str):
    """Render QA found it: a manifest that answers 200 with a half-written body
    left four slots reading "not available" with no note. A number that is
    absent because the document was incomplete must say so as loudly as one
    absent because the document was missing — otherwise the reader cannot tell
    a broken build from a build that has not happened."""
    assert "var incomplete = [];" in page, "the incomplete-document branch is gone"
    assert "did not carry every number this panel states" in page
    assert "Could not read " in page
    assert "var mismatch = null;" in page, "the edition mismatch must compose with the absence notes, not replace them"


def test_the_download_hedge_is_gated_on_the_manifest_having_failed(page: str):
    """If only the continuity clock is unreadable, the panel has already
    published this archive's build time, size and checksum — warning that the
    download "may not answer" would contradict evidence the page is showing on
    the same screen. The hedge belongs to the manifest's failure alone."""
    assert 'unreadable.indexOf("the manifest") !== -1' in page, "the download hedge is no longer gated on the manifest failing"
    hedge = "The download address above is fixed and does not move"
    assert page.count(hedge) == 1, "the hedge appears outside its guard"


# ── the generator refuses to write a page it cannot verify ──────────────────
def test_generator_rejects_a_document_whose_clause_set_disagrees_with_the_code():
    parsed = [{"id": "P1", "title": "Nothing here is for sale", "paragraphs": ["x"]}]
    with pytest.raises(ValueError, match="disagree"):
        builder.reconcile(parsed)


def test_generator_rejects_a_retitled_clause():
    parsed = [dict(c, title="Everything here is for sale", paragraphs=["x"]) for c in terms.CLAUSES]
    with pytest.raises(ValueError, match="title differs"):
        builder.reconcile(parsed)


def test_generator_escapes_rather_than_interprets_clause_text():
    rendered = builder.render([{"id": "P1", "title": "T", "kind": terms.POLICY, "paragraphs": ["<script>alert(1)</script>"]}])
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;" in rendered
