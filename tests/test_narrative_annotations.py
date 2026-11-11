"""tests/test_narrative_annotations.py — dated corrections for historical coach words (owner ruling 2026-11-10, item 4).

What is pinned:
  * DARK: every annotation is unapproved on main; the annotated reads are not on the CR2 allowlist;
  * APPEND-ONLY: a published annotation never changes or disappears — a later correction is a new entry that
    ``supersedes`` it (digests pinned below; add a line for a new entry, never edit one);
  * NEVER WITHOUT ITS ANNOTATION: the narrative gate cannot publish an annotated read's words alone, even if its key
    were listed; the only path is ``annotated_words``, whose output always carries the dated note;
  * FAIL CLOSED: switch off, out of scope, unapproved, changed words, a provenance record of its own, a private cited
    field — each withholds.

The four reads' words are private until the owner approves, so gate tests use synthetic words and patched hashes.
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
}
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


def test_every_annotation_is_unapproved_and_off_the_allowlist():
    assert not any(a.owner_approved for a in NANN.ANNOTATIONS), "approving an annotation is the owner's call (ruling 2026-11-10, 4)"
    assert NANN.KEYS.isdisjoint(NA.INDEX), "an annotated read is never on the bare-words allowlist"
    assert {a.sk.split("#", 1)[1] for a in NANN.ANNOTATIONS} == ACCURACY_HOLD_DAYS


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
            assert c.cause in (NANN.CAUSE_LATE_LOGGED, NANN.CAUSE_VENDOR_REVISION) and c.evidence
            assert c.as_cited != c.record_now and c.record_rewritten_at > a.read_written_at, a.annotation_id
            assert c.source_field.split(".")[0] in ("macrofactor", "whoop")
        note = NANN.render_note(a)
        assert note.startswith("Correction added 10 November 2026.") and "exactly as written" in note
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
    assert ann["kind"] == "correction" and ann["annotated_at"] == "2026-11-10" and ann["author"] == NANN.AUTHOR_ENGINE
    assert "111" in ann["note"] and "139" in ann["note"] and "logged after the read was written" in ann["note"]
    assert ann["corrections"][0]["record_now"] == "139"


# ── fail closed ──────────────────────────────────────────────────────────────────────────────


def test_switch_off_or_out_of_scope_nothing_is_served(approved, monkeypatch):
    with NA.serving(NA.SCOPE_CR2):
        assert NANN.annotated_words(approved) is None  # switch off on main
    monkeypatch.setattr(NA, "CR2_PUBLIC", True)
    assert NANN.annotated_words(approved) is None  # outside the scope
    with NA.serving("cr3"):
        assert NANN.annotated_words(approved) is None


def test_an_unapproved_annotation_is_not_served(cr2_on, approved, monkeypatch):
    a = NANN.INDEX[(approved["pk"], approved["sk"])]._replace(owner_approved=False)
    monkeypatch.setattr(NANN, "INDEX", {**NANN.INDEX, (a.pk, a.sk): a})
    with NA.serving(NA.SCOPE_CR2):
        assert NANN.annotated_words(approved) is None


def test_the_real_rows_are_not_served_today(cr2_on):
    """The four real annotations are unapproved: whatever words a row carries under their keys, nothing is served."""
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
