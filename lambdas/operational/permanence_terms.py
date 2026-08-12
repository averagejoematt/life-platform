#!/usr/bin/env python3
"""The Permanence Contract, in a form the code can be checked against (#1400).

The written commitment and the machinery that keeps it are two halves of one
thing, and the failure mode worth designing against is the promise outliving
the mechanism. So the terms live here as data:

* ``docs/PERMANENCE_CONTRACT.md`` is the prose the reader gets.
* ``CLAUSES`` below is the same contract as a list of clauses, each one naming
  the function that implements it (or declaring, explicitly, that it has no
  mechanism and is a policy statement only).
* ``tests/test_permanence_contract_1400.py`` asserts the two agree: every
  clause id appears in the doc, the version and amendment history match, and
  every ``mechanism`` string resolves to a real importable callable.

Delete the code behind a clause and the test goes red. Write a promise the
platform does not keep and the test goes red. That is the whole point.

**Scope of the version number.** ``TERMS_VERSION`` is semantic over the
*promise*, not the implementation: a clause that narrows or removes an
obligation is a major bump, a clause that adds one is a minor bump, and a
wording change that alters no obligation is a patch bump. Amendments are
append-only — a superseded clause is marked superseded, never edited away.
"""

from __future__ import annotations

TERMS_VERSION = "1.0.0"
TERMS_EFFECTIVE = "2026-08-10"

# Append-only. Newest last. Mirrored by the amendment table in
# docs/PERMANENCE_CONTRACT.md, which the gate test compares row for row.
AMENDMENTS: tuple[dict, ...] = (
    {
        "version": "1.0.0",
        "date": "2026-08-10",
        "issue": 1400,
        "summary": "First edition: the nightly public archive, its admission gate, and the continuity clock.",
    },
)

POLICY = "policy"
MECHANISM = "mechanism"
LIMIT = "limit"

CLAUSES: tuple[dict, ...] = (
    {
        "id": "P1",
        "kind": POLICY,
        "title": "Nothing here is for sale",
        "text": (
            "No reader's email address, question, or submitted finding is ever sold, rented, "
            "or handed to an advertiser, a data broker, or a sponsor. Neither is any of "
            "Matthew's own health data. There is no advertising business here to be tempted by."
        ),
        "mechanism": None,
    },
    {
        "id": "P2",
        "kind": MECHANISM,
        "title": "The public record is rebuilt as a single download every night",
        "text": (
            "Every night the platform packages everything it already publishes — the data, "
            "the methods, the chronicle, the sealed pre-registrations — into one compressed "
            "archive at a fixed address, and overwrites yesterday's. It is not generated on "
            "request and it is not gated: it is simply there."
        ),
        "mechanism": "operational.public_archive:build_archive",
    },
    {
        "id": "P3",
        "kind": MECHANISM,
        "title": "What may enter the archive is decided by a gate, not by hand",
        "text": (
            "Nothing enters because someone remembered to add it. An artefact enters only if "
            "the public site already serves it at a public address, and only if a registry "
            "classifies that address as part of the published record. Anything the registry "
            "does not classify is refused. The API portion is fetched with no credentials at "
            "all, over the same public address a reader would use, so it can contain nothing "
            "a reader could not already fetch themselves."
        ),
        "mechanism": "operational.public_archive_registry:admits_generated_key",
    },
    {
        "id": "P4",
        "kind": MECHANISM,
        "title": "Every archive publishes its own inventory and checksum",
        "text": (
            "Alongside the archive sits a manifest listing every file in it with a size and a "
            "SHA-256, the checksum of the archive as a whole, the moment it was built, and — "
            "in the same document — a list of what was deliberately left out and why. You do "
            "not have to trust the description; you can check it."
        ),
        "mechanism": "operational.public_archive:build_manifest",
    },
    {
        "id": "P5",
        "kind": MECHANISM,
        "title": "Silence is measured out loud",
        "text": (
            "The platform watches for its own silence: the number of days since the last "
            "signal from any source that only produces data when a living person is doing "
            "something. That number, and the state it puts the contract in, are published in "
            "the same place as the archive, every night, whether the news is good or not."
        ),
        "mechanism": "operational.continuity_watch:evaluate",
    },
    {
        "id": "P6",
        "kind": MECHANISM,
        "title": "Ninety days of silence freezes the record and raises the alarm",
        "text": (
            "At 30 days of silence the contract enters a notice state, at 60 a warning state, "
            "and at 90 the switch trips: the archive stops being overwritten and is sealed as "
            "a final, dated edition, the published state says so plainly, and the people "
            "configured as continuity contacts are told where the record is and how to check "
            "it. Any new signal from any watched source resets the clock — the switch is a "
            "measurement, and it is reversible."
        ),
        "mechanism": "operational.continuity_watch:apply_transition",
    },
    {
        "id": "P7",
        "kind": LIMIT,
        "title": "What this contract does not promise",
        "text": (
            "It does not promise the archive outlives the bill: everything here sits in one "
            "cloud account, and if that account lapses the archive lapses with it. This "
            "edition grants no mirroring rights, so that single point of failure is not "
            "mitigated by anything written here. It does not promise a third-party mirror — "
            "no automatic "
            "copy is made to any host outside this account, and any claim that one exists "
            "would be false. It does not promise the archive is complete: audio, artwork, and "
            "the site's presentation layer are excluded, and the manifest names every "
            "exclusion. It does not promise the switch detects a person: it detects the "
            "absence of data, which a long holiday, a hardware failure, or a vendor lockout "
            "can also produce — that is why the first two thresholds notify rather than act. "
            "And it does not promise to publish anything currently private: the archive is a "
            "repackaging of the public surface, never a widening of it."
        ),
        "mechanism": None,
    },
    {
        "id": "P8",
        "kind": MECHANISM,
        "title": "The terms are versioned, and amendments are append-only",
        "text": (
            "This contract carries a version and a dated amendment history. Clauses are added "
            "or superseded, never quietly rewritten, and the published version number tells "
            "you which edition you are reading."
        ),
        "mechanism": "operational.permanence_terms:public_terms",
    },
)


def clause(clause_id: str) -> dict:
    """Look a clause up by id. Raises KeyError rather than returning None —
    a missing clause is a broken contract, not a soft miss."""
    for c in CLAUSES:
        if c["id"] == clause_id:
            return c
    raise KeyError(f"no such contract clause: {clause_id}")


def public_terms() -> dict:
    """The reader-facing form of the contract.

    Deliberately drops the ``mechanism`` field: which module implements a
    clause is repo-side wiring, and the issue's own rigor note asks that no
    internal infrastructure detail ride along on the published terms.
    """
    return {
        "version": TERMS_VERSION,
        "effective": TERMS_EFFECTIVE,
        "clauses": [{"id": c["id"], "kind": c["kind"], "title": c["title"], "text": c["text"]} for c in CLAUSES],
        "amendments": [dict(a) for a in AMENDMENTS],
    }
