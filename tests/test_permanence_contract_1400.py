#!/usr/bin/env python3
"""tests/test_permanence_contract_1400.py — the written promise may not outlive
the mechanism (#1400).

The Permanence Contract exists twice on purpose: as prose in
``docs/PERMANENCE_CONTRACT.md``, and as data in
``lambdas/operational/permanence_terms.py``. This file asserts the two agree —
clause for clause, version for version, amendment for amendment — and that
every clause claiming a mechanism names a function that actually exists and is
importable.

That last one is the whole point. A document promising a nightly archive is
worth nothing six months after the archive Lambda was deleted in a cleanup, and
prose does not go red in CI. This does.

It also enforces the shape of an honest contract:

* a ``limit`` clause is **mandatory**. A permanence promise with no stated
  limits is an over-promise by construction, and the one thing worse than a
  narrow promise here is a broad one that quietly is not kept.
* the reader-facing section carries no infrastructure detail — the issue's own
  rigor note, and the constraint the second (public-page) PR inherits.
"""

from __future__ import annotations

import importlib
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "lambdas") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from operational import permanence_terms as terms  # noqa: E402

DOC = os.path.join(ROOT, "docs", "PERMANENCE_CONTRACT.md")
READER_START = "<!-- BEGIN READER TERMS -->"
READER_END = "<!-- END READER TERMS -->"


@pytest.fixture(scope="module")
def doc() -> str:
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def reader_section(doc: str) -> str:
    start = doc.index(READER_START) + len(READER_START)
    end = doc.index(READER_END)
    body = doc[start:end]
    assert len(body) > 1500, "the reader-facing terms section is suspiciously short"
    return body


# ── the two copies agree ────────────────────────────────────────────────────
def test_every_clause_appears_in_the_document(reader_section: str):
    for clause in terms.CLAUSES:
        heading = f"### {clause['id']} · {clause['title']}"
        assert heading in reader_section, f"{clause['id']} is in the code but not in the document (expected heading: {heading!r})"


def test_every_documented_clause_exists_in_code(reader_section: str):
    """The reverse ratchet: prose promising something the code has never heard
    of is exactly the failure mode this file exists to catch."""
    documented = set(re.findall(r"^### (P\d+) · ", reader_section, flags=re.M))
    coded = {c["id"] for c in terms.CLAUSES}
    assert (
        documented == coded
    ), f"documented but not in code: {sorted(documented - coded)}; in code but not documented: {sorted(coded - documented)}"


def test_clause_text_is_reproduced_faithfully(reader_section: str):
    """Not a paraphrase check — a substring check on the first sentence of each
    clause. The archive's README ships the coded text to readers who may never
    see the website, so the two must not drift into saying different things."""
    normalised = re.sub(r"\s+", " ", reader_section)
    for clause in terms.CLAUSES:
        first_sentence = clause["text"].split(". ")[0]
        assert (
            first_sentence in normalised
        ), f"{clause['id']}: the document no longer opens with the coded text\n  coded: {first_sentence!r}"


def test_version_and_effective_date_match(doc: str, reader_section: str):
    assert f"**Contract version:** {terms.TERMS_VERSION}" in doc
    assert f"**Effective:** {terms.TERMS_EFFECTIVE}" in doc
    assert f"**Version {terms.TERMS_VERSION} — effective {terms.TERMS_EFFECTIVE}**" in reader_section


def test_amendment_history_matches_row_for_row(doc: str):
    rows = re.findall(r"^\| (\d+\.\d+\.\d+) \| (\d{4}-\d{2}-\d{2}) \| #(\d+) \| (.+?) \|$", doc, flags=re.M)
    assert len(rows) == len(terms.AMENDMENTS), f"the document has {len(rows)} amendment rows, the code has {len(terms.AMENDMENTS)}"
    for row, amendment in zip(rows, terms.AMENDMENTS):
        version, day, issue, summary = row
        assert version == amendment["version"]
        assert day == amendment["date"]
        assert int(issue) == amendment["issue"]
        assert summary.strip() == amendment["summary"]


def test_amendments_are_append_only_and_ordered():
    seen: list[tuple[int, ...]] = []
    for amendment in terms.AMENDMENTS:
        parts = tuple(int(p) for p in amendment["version"].split("."))
        assert (
            not seen or parts > seen[-1]
        ), f"{amendment['version']} does not follow {seen[-1] if seen else None} — the history must only move forward"
        seen.append(parts)
    assert terms.AMENDMENTS[-1]["version"] == terms.TERMS_VERSION, "the current version must be the newest amendment"


# ── the promise may not outlive the mechanism ───────────────────────────────
def test_every_mechanism_clause_names_a_real_callable():
    """The load-bearing assertion. Delete the archive builder and this goes red
    before anyone notices the download stopped."""
    missing: list[str] = []
    for clause in terms.CLAUSES:
        if clause["kind"] != terms.MECHANISM:
            continue
        ref = clause["mechanism"]
        assert ref, f"{clause['id']} is declared a mechanism clause but names no mechanism"
        module_name, _, attr = ref.partition(":")
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            missing.append(f"{clause['id']}: cannot import {module_name} ({exc})")
            continue
        target = getattr(module, attr, None)
        if not callable(target):
            missing.append(f"{clause['id']}: {ref} is not a callable")
    assert not missing, "the contract promises things the code no longer does:\n" + "\n".join(f"  {m}" for m in missing)


def test_non_mechanism_clauses_declare_no_mechanism():
    for clause in terms.CLAUSES:
        if clause["kind"] == terms.MECHANISM:
            continue
        assert clause["mechanism"] is None, f"{clause['id']} is a {clause['kind']} clause but names a mechanism — pick one"


def test_a_limits_clause_is_mandatory():
    """A permanence promise with no stated limits is an over-promise by
    construction. Removing the limits clause must fail the build."""
    limits = [c for c in terms.CLAUSES if c["kind"] == terms.LIMIT]
    assert limits, "the contract has no `limit` clause — an unlimited permanence promise is not one this platform can keep"
    body = " ".join(c["text"] for c in limits)
    for admission in ("does not promise", "third-party mirror", "absence of data"):
        assert admission in body, f"the limits clause no longer admits: {admission!r}"


def test_the_limits_clause_admits_the_single_point_of_failure():
    """The honest version of "permanent" on one cloud account. If this sentence
    ever disappears, the contract has started lying."""
    body = " ".join(c["text"] for c in terms.CLAUSES if c["kind"] == terms.LIMIT)
    assert "one cloud" in body and "lapses" in body


def test_every_clause_is_well_formed():
    ids = [c["id"] for c in terms.CLAUSES]
    assert len(ids) == len(set(ids)), "duplicate clause ids"
    for clause in terms.CLAUSES:
        assert clause["kind"] in (terms.POLICY, terms.MECHANISM, terms.LIMIT), f"{clause['id']}: unknown kind"
        assert len(clause["title"]) >= 10, f"{clause['id']}: title too thin"
        assert len(clause["text"]) >= 120, f"{clause['id']}: a clause this short is not a term, it is a slogan"


def test_clause_lookup_raises_rather_than_returning_none():
    assert terms.clause("P1")["kind"] == terms.POLICY
    with pytest.raises(KeyError):
        terms.clause("P999")


# ── what the reader gets ────────────────────────────────────────────────────
_INFRA_TELLS = (
    "matthew-life-platform",
    "arn:aws",
    ".amazonaws.com",
    "s3://",
    "dynamodb",
    "cloudfront",
    "boto3",
    "lambda_handler",
    "us-west-2",
    "generated/",
)


def test_reader_facing_terms_carry_no_infrastructure_detail(reader_section: str):
    """The issue's rigor note, and the constraint the public-page PR inherits:
    the terms a reader sees name no internal hostname, bucket, service, or
    module. Section 4 of the document may — that is why the markers exist."""
    lowered = reader_section.lower()
    leaks = [tell for tell in _INFRA_TELLS if tell in lowered]
    assert not leaks, f"the reader-facing terms leak infrastructure detail: {leaks}"


def test_published_terms_payload_carries_no_infrastructure_detail():
    """``public_terms()`` is what ships inside the archive and (later) to the
    public page. It must drop the mechanism wiring, not merely omit it by
    accident."""
    payload = terms.public_terms()
    blob = repr(payload).lower()
    leaks = [tell for tell in _INFRA_TELLS if tell in blob]
    assert not leaks, f"the published terms payload leaks infrastructure detail: {leaks}"
    carried = [c["id"] for c in payload["clauses"] if "mechanism" in c]
    assert not carried, f"these clauses shipped their module wiring to readers: {carried}"
    assert {c["id"] for c in payload["clauses"]} == {c["id"] for c in terms.CLAUSES}
    assert payload["version"] == terms.TERMS_VERSION


def test_the_document_is_registered_in_the_docs_index():
    """A permanence document nobody can find is its own kind of joke."""
    with open(os.path.join(ROOT, "docs", "README.md"), encoding="utf-8") as fh:
        index = fh.read()
    assert "PERMANENCE_CONTRACT.md" in index
