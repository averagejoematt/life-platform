"""tests/test_narrative_annotations.py — dated corrections for historical coach words (owner ruling 2026-11-10, item 4).

What is pinned:
  * APPROVAL: the four 2026-11-10 entries stay unapproved and are superseded; the four 2026-11-11 entries (owner ruling
    2026-11-11, second message, item 3) are approved and are the ones served — their exact notes are pinned below;
    the annotated reads are not on the bare-words CR2 allowlist;
  * APPEND-ONLY: a published annotation never changes or disappears — a later correction is a new entry that
    ``supersedes`` it (digests pinned below; add a line for a new entry, never edit one);
  * NEVER WITHOUT ITS ANNOTATION: the narrative gate cannot publish an annotated read's words alone, even if its key
    were listed; the only path is ``annotated_words``, whose output always carries the dated note;
  * FAIL CLOSED: switch off, out of scope, unapproved, changed words, a provenance record of its own, a private cited
    field — each withholds.

Gate tests use synthetic words and patched hashes (the real words live in the table, never in the repo).
"""

# premerge-gate: CR2 annotations (owner 2026-11-10, 4): pins each annotation's digest — editing a published correction must red before merge.
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from common import (
    narrative_allowlist as NA,  # noqa: E402
    narrative_annotations as NANN,  # noqa: E402
)
from web import narrative_publication as G  # noqa: E402

#: Append-only ledger: annotation_id -> digest. Add a line for a new annotation; never edit or delete one.
PINNED = {
    "ann-2026-11-10-lead-2026-10-02": "2e0ab206f14112034ccc8cf4d5151611a36de8a3ef11e4d000200e389c525b03",
    "ann-2026-11-10-lead-2026-10-07": "7cb0248d2cc827d27cbf8b10b2cd8ee6e9492757412271005125659f0d957165",
    "ann-2026-11-10-lead-2026-10-17": "0dc323f7d1aa1c3f51d71ab650e73524af3fdc4726eed2e7da8f19704157e30e",
    "ann-2026-11-10-lead-2026-10-28": "6f3b19a1adcf9fcc6381a28312f8ffa1a3ef5415a98285c7795f75b81de319b6",
    "ann-2026-11-11-lead-2026-10-02": "287edcbf68b2753ec1acea6bc60c455e7fc16146801540b52e67a11cab9c2dba",
    "ann-2026-11-11-lead-2026-10-07": "03dde6831954a50c331da31c790b68dd1af4901de75bd5484e0dccd859bb9027",
    "ann-2026-11-11-lead-2026-10-17": "6f1758ca8ee23b1f2fdfbd7bdf93bddc8899991d9879ab5946356679cf2546dc",
    "ann-2026-11-11-lead-2026-10-28": "e29e06a34c443151fb184a4dbbf6f9bb440cab0b1f3e3c9f2247c5c007ffa6e9",
}
SUPERSEDED = {f"ann-2026-11-10-lead-{d}" for d in ("2026-10-02", "2026-10-07", "2026-10-17", "2026-10-28")}

#: The exact reader-facing notes the 2026-11-11 check verified (owner ruling 2026-11-11, second message, item 3). A
#: change to the render or to an entry reds here; a new wording is a new superseding entry, never an edit.
NOTES = {
    "ann-2026-11-11-lead-2026-10-02": (
        "Correction added 11 November 2026. These words are shown exactly as written on 2 October 2026. Since then the "
        "record has changed: protein for 1 October now reads 186 g, not 166 g. Two food-log entries for that day were not "
        "in the export the read's figure came from (received at 03:33 UTC on 2 October 2026); they first reached the "
        "platform in an export received at 04:33 UTC on 4 October 2026, after the read was written. The export does not "
        "record when they were logged. With the corrected figure the 170 g protein floor was met that day."
    ),
    "ann-2026-11-11-lead-2026-10-07": (
        "Correction added 11 November 2026. These words are shown exactly as written on 7 October 2026. Since then the "
        "record has changed: the recovery score on 7 October now reads 78, not 77; sleep the night before 7 October now "
        "reads 8.2 hours, not 7.9 hours. Whoop's recovery and sleep records for that morning were last updated at 18:15 "
        "UTC on 7 October 2026, after the read was written. The platform's copy took the updated figures after that; the "
        "exact time is not recorded, but it held them by 10 October 2026."
    ),
    "ann-2026-11-11-lead-2026-10-17": (
        "Correction added 11 November 2026. These words are shown exactly as written on 17 October 2026. Since then the "
        "record has changed: the recovery score on 17 October now reads 62, not 60; sleep the night before 17 October now "
        "reads 8.8 hours, not 7.4 hours. Whoop's recovery and sleep records for that morning were last updated at 17:30 "
        "UTC on 17 October 2026, after the read was written, and the platform's copy took the updated figures at 19:00 UTC "
        "the same day. The updated sleep record now ends at 17:04 UTC, after the read was written at 17:00 UTC, so it "
        "covers time the read could not have seen."
    ),
    "ann-2026-11-11-lead-2026-10-28": (
        "Correction added 11 November 2026. These words are shown exactly as written on 28 October 2026. Since then the "
        "record has changed: protein for 27 October now reads 139 g, not 111 g. One food-log entry for that day was not in "
        "the export the read's figure came from (received at 06:54 UTC on 28 October 2026); it first reached the platform "
        "in an export received at 06:54 UTC on 3 November 2026, after the read was written. The export does not record "
        "when it was logged. The corrected figure is still below the 170 g protein floor."
    ),
}
#: Words a published correction must never carry (restricted data, or the unproven claims the 11-10 notes made).
NEVER_IN_A_NOTE = re.compile(
    r"\bLDL\b|lipid|cholesterol|statin|journal|diary|state of mind|mood|video|genom|medication|metoprolol|"
    r"logged after the read|record updated",
    re.IGNORECASE,
)
ACCURACY_HOLD_DAYS = {"2026-10-02", "2026-10-07", "2026-10-17", "2026-10-28"}

WORDS = "A synthetic dated lead read: protein came in under the floor yesterday and recovery held steady."
CITED = [
    {"metric": "hrv", "value": "50", "as_of": "2026-10-05", "source_field": "whoop.hrv"},
    {"metric": "protein", "value": "111", "as_of": "2026-10-27", "source_field": "macrofactor.total_protein_g"},
    {"metric": "start", "value": "Sunday, September 6", "as_of": "2026-09-06", "source_field": "profile.journey_start_date"},
]


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@pytest.fixture
def cr2_on(monkeypatch):
    monkeypatch.setattr(NA, "CR2_PUBLIC", True)


@pytest.fixture
def approved(monkeypatch):
    """The 10-28 annotation, approved, over synthetic words (the real words stay private until the owner's GO)."""
    a = NANN.INDEX[("COACH#eli_marsh", "LEAD_DAILY#2026-10-28")]._replace(text_sha256=_sha(WORDS), owner_approved=True)
    monkeypatch.setattr(NANN, "INDEX", {**NANN.INDEX, (a.pk, a.sk): a})
    return {"pk": a.pk, "sk": a.sk, "text": WORDS, "generated_at": a.read_written_at, "cited": list(CITED)}


# ── dark + the set ───────────────────────────────────────────────────────────────────────────


def test_only_the_verified_supersessions_are_approved_and_none_is_on_the_allowlist():
    by_id = {a.annotation_id: a for a in NANN.ANNOTATIONS}
    for old in SUPERSEDED:
        assert not by_id[old].owner_approved, f"{old} made unproven claims and must never be served"
        assert any(a.supersedes == old for a in NANN.ANNOTATIONS), f"{old} has no superseding entry"
    approved = {a.annotation_id for a in NANN.ANNOTATIONS if a.owner_approved}
    assert approved == set(NOTES), "approving an annotation is the owner's call (ruling 2026-11-11, second message, 3)"
    assert {a.annotation_id for a in NANN.INDEX.values()} == set(NOTES), "INDEX serves the newest entry per read only"
    assert NANN.KEYS.isdisjoint(NA.INDEX), "an annotated read is never on the bare-words allowlist"
    assert {a.sk.split("#", 1)[1] for a in NANN.ANNOTATIONS} == ACCURACY_HOLD_DAYS


def test_the_approved_notes_are_exactly_the_verified_wording():
    for ann_id, note in NOTES.items():
        a = next(x for x in NANN.ANNOTATIONS if x.annotation_id == ann_id)
        assert NANN.render_note(a) == note, ann_id
        assert not NEVER_IN_A_NOTE.search(note), (ann_id, NEVER_IN_A_NOTE.search(note).group(0))
        assert "exactly as written" in note and a.supersedes in SUPERSEDED


def test_the_ledger_is_append_only():
    by_id = {a.annotation_id: a for a in NANN.ANNOTATIONS}
    assert len(by_id) == len(NANN.ANNOTATIONS), "a duplicated annotation id"
    for ann_id, pinned in PINNED.items():
        assert ann_id in by_id, f"{ann_id} was removed — a correction is superseded by a new entry, never deleted"
        assert NANN.digest(by_id[ann_id]) == pinned, f"{ann_id} was edited — append a superseding entry instead"
    unpinned = {i: NANN.digest(by_id[i]) for i in set(by_id) - set(PINNED)}
    assert not unpinned, f"pin the new annotation(s): {unpinned}"
    for a in NANN.ANNOTATIONS:
        assert a.supersedes is None or a.supersedes in by_id, a.annotation_id


def test_every_annotation_is_dated_sourced_and_free_of_coach_words():
    for a in NANN.ANNOTATIONS:
        assert re.fullmatch(r"[0-9a-f]{64}", a.text_sha256) and a.author in (NANN.AUTHOR_ENGINE, NANN.AUTHOR_OWNER)
        assert a.corrections and a.method
        for c in a.corrections:
            assert c.cause in (NANN.CAUSE_LATE_LOGGED, NANN.CAUSE_VENDOR_REVISION, *NANN.PROVEN_CAUSES) and c.evidence
            assert c.as_cited != c.record_now and c.record_rewritten_at > a.read_written_at, a.annotation_id
            assert c.source_field.split(".")[0] in ("macrofactor", "whoop")
        note = NANN.render_note(a)
        day = NANN._day(a.annotated_at)
        assert note.startswith(f"Correction added {day}.") and "exactly as written" in note
        assert all(c.as_cited in note and c.record_now in note for c in a.corrections)


# ── never without its annotation ─────────────────────────────────────────────────────────────


def test_the_gate_never_publishes_an_annotated_read_alone(cr2_on, approved, monkeypatch):
    """Even listed on the allowlist by mistake, in scope with the switch on, the bare words stay withheld."""
    e = NA.Entry(approved["pk"], approved["sk"], "text", _sha(WORDS), NA.DERIVED_FROM_CITED)
    monkeypatch.setattr(NA, "INDEX", {**NA.INDEX, (e.pk, e.sk): e})
    with NA.serving(NA.SCOPE_CR2):
        assert NA.record_for(approved) is None
        G.begin_request()
        out = G.gate_item(dict(approved))
        assert out["text"] == "" and out[G.PUBLICATION_KEY]["state"] == "withheld"


def test_an_approved_annotated_read_is_served_only_as_the_pair(cr2_on, approved):
    with NA.serving(NA.SCOPE_CR2):
        out = NANN.annotated_words(approved)
    assert out["words"] == WORDS, "the original words, verbatim"
    ann = out["annotation"]
    assert ann["kind"] == "correction" and ann["annotated_at"] == "2026-11-11" and ann["author"] == NANN.AUTHOR_ENGINE
    assert ann["note"] == NOTES["ann-2026-11-11-lead-2026-10-28"]
    assert ann["supersedes"] == "ann-2026-11-10-lead-2026-10-28"
    assert ann["corrections"][0]["record_now"] == "139"


def test_the_superseded_note_is_never_served(cr2_on, approved, monkeypatch):
    """Even approved by mistake, a superseded entry is not in INDEX: the reader only ever sees the newest note."""
    old = next(a for a in NANN.ANNOTATIONS if a.annotation_id == "ann-2026-11-10-lead-2026-10-28")
    assert NANN.INDEX[(old.pk, old.sk)].annotation_id != old.annotation_id
    with NA.serving(NA.SCOPE_CR2):
        out = NANN.annotated_words(approved)
    assert "logged after the read was written" not in out["annotation"]["note"]


# ── fail closed ──────────────────────────────────────────────────────────────────────────────


def test_switch_off_or_out_of_scope_nothing_is_served(approved, monkeypatch):
    monkeypatch.setattr(NA, "CR2_PUBLIC", False)
    with NA.serving(NA.SCOPE_CR2):
        assert NANN.annotated_words(approved) is None  # the switch off
    monkeypatch.setattr(NA, "CR2_PUBLIC", True)
    assert NANN.annotated_words(approved) is None  # outside the scope
    with NA.serving("cr3"):
        assert NANN.annotated_words(approved) is None


def test_an_unapproved_annotation_is_not_served(cr2_on, approved, monkeypatch):
    a = NANN.INDEX[(approved["pk"], approved["sk"])]._replace(owner_approved=False)
    monkeypatch.setattr(NANN, "INDEX", {**NANN.INDEX, (a.pk, a.sk): a})
    with NA.serving(NA.SCOPE_CR2):
        assert NANN.annotated_words(approved) is None


def test_words_that_are_not_the_annotated_original_are_never_served(cr2_on):
    """The negative control on the real keys: any words but the pinned originals are withheld, approved or not."""
    with NA.serving(NA.SCOPE_CR2):
        for a in NANN.ANNOTATIONS:
            assert NANN.annotated_words({"pk": a.pk, "sk": a.sk, "text": WORDS, "cited": list(CITED)}) is None


@pytest.mark.parametrize(
    "change",
    [
        {"text": WORDS + " "},
        {"provenance": {"v": 1, "families": ["whoop"], "producer": "t"}},
        {"cited": CITED + [{"metric": "m", "value": "3", "as_of": "2026-10-05", "source_field": "journal.days_since_last_entry"}]},
        {"cited": CITED + [{"metric": "m", "value": "3", "as_of": "2026-10-05", "source_field": "a_source_nobody_classified.x"}]},
    ],
)
def test_changed_words_own_record_or_private_cited_field_fail_closed(cr2_on, approved, change):
    with NA.serving(NA.SCOPE_CR2):
        assert NANN.annotated_words({**approved, **change}) is None


def test_words_naming_private_activity_fail_closed(cr2_on, approved, monkeypatch):
    words = "A synthetic lead read that says the journal went quiet this week."
    a = NANN.INDEX[(approved["pk"], approved["sk"])]._replace(text_sha256=_sha(words))
    monkeypatch.setattr(NANN, "INDEX", {**NANN.INDEX, (a.pk, a.sk): a})
    with NA.serving(NA.SCOPE_CR2):
        assert NANN.annotated_words({**approved, "text": words}) is None
