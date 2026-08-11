"""test_recall_consent_2587.py — the recall index enforces consent, and the coach
retrieval path enforces a kind allowlist.

#2587, the chain that was verified live on 2026-08-11:

  1. `privacy/diary_consent.py` makes ``private`` the default for ANY unmarked /
     malformed / unknown entry, and says the raw body is never public unless a specific
     line was owner-cleared AND it grounds.
  2. `deploy/backfill_recall_embeddings.py` stored ``snippet=_snippet(doc["text"])`` — a
     verbatim excerpt of that body.
  3. `semantic_recall.retrieve()` applied NO kind predicate, so anything indexed was
     retrievable.
  4. `recall_block()` injects the result into the coach prompt, and coach narrative is
     published.

PR #2580 made 60 journal rows and 851 coach outputs *eligible* to be indexed. Nothing has
been. These tests are the gate that has to exist before that backfill runs.

WHAT THESE TESTS DO THAT A HAPPY-PATH FIXTURE WOULD NOT:

  * they GUARD THE SET, not the instance — the policy registry and both consumer
    registries are compared against `semantic_recall.KINDS`, so a kind added upstream
    goes red until someone writes the decision down, and the derived tuples exclude it
    in the meantime;
  * they mutation-prove in BOTH directions — an unmarked entry reaching the corpus turns
    the guard red, and a cleared entry still flows;
  * they assert on the STORED ROW and the ASSEMBLED PROMPT BLOCK, not on the verdict
    object, because the verdict is not what leaks;
  * the structural test pins the WRITER SET, so a third writer that skips the gate is a
    failure rather than a silent bypass.

Hermetic — no AWS, no Bedrock, no network.

Run with:   python3 -m pytest tests/test_recall_consent_2587.py -v
"""

import os
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from ai import recall_consent as rc, recall_indexer as ri, semantic_recall as sr  # noqa: E402
from privacy import diary_consent  # noqa: E402
from web import ask_retrieval as ar  # noqa: E402

# A realistic private journal row: the live shape is pk USER#matthew#SOURCE#notion,
# sk DATE#<date>#journal#<template>, body in `raw_text` (#2569 / common.record_text).
_BODY = "I told nobody about the thing with my brother. I have been carrying it since Tuesday and it is heavy."
_CLEARED_LINE = "I have been carrying it since Tuesday"


def _journal_record(**overrides):
    rec = {
        "pk": "USER#matthew#SOURCE#notion",
        "sk": "DATE#2026-08-03#journal#daily",
        "raw_text": _BODY,
        "date": "2026-08-03",
        "dominant_theme": "relationships",
        "channel": "video_diary",
    }
    rec.update(overrides)
    return rec


def _journal_doc(record):
    return {
        "kind": sr.KIND_JOURNAL,
        "date": "2026-08-03#journal#daily",
        "doc_date": "2026-08-03",
        "text": record.get("raw_text", ""),
        "artifact_pk": record["pk"],
        "artifact_sk": record["sk"],
        "link": "/story/journal/",
        rc.RECORD_KEY: record,
    }


class RecordingTable:
    """Captures put_item/update_item so a test can assert on the row that WOULD be
    written — the thing that leaks — rather than on the return value."""

    def __init__(self, stored=None):
        self.stored = stored or {}
        self.puts = []
        self.updates = []

    def get_item(self, Key=None, **_):  # noqa: N803 — boto3's own casing
        item = self.stored.get((Key or {}).get("sk"))
        return {"Item": item} if item else {}

    def put_item(self, Item=None, **_):  # noqa: N803
        self.puts.append(Item)
        return {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    def query(self, **_):
        return {"Items": list(self.stored.values())}


def _fake_embed(_text):
    return [1.0, 0.0, 0.0]


# ── the SET, not the instance ───────────────────────────────────────────────
def test_every_corpus_kind_has_an_explicit_consent_policy():
    """A kind added to `semantic_recall.KINDS` must arrive with a written-down policy.

    Derived from KINDS rather than hand-listed, so this is the test that goes red when
    someone adds a fourth kind and does not decide how consent applies to it.
    """
    missing = [k for k in sr.KINDS if k not in rc.KIND_POLICY]
    assert not missing, f"corpus kinds with no consent policy in recall_consent.KIND_POLICY: {missing}"
    stale = [k for k in rc.KIND_POLICY if k not in sr.KINDS]
    assert not stale, f"KIND_POLICY entries for kinds that no longer exist: {stale}"


def test_every_corpus_kind_has_an_explicit_decision_for_both_consumers():
    for name, decisions in (("COACH_KIND_DECISIONS", sr.COACH_KIND_DECISIONS), ("READER_KIND_DECISIONS", sr.READER_KIND_DECISIONS)):
        assert set(decisions) == set(sr.KINDS), f"{name} must carry exactly one explicit decision per semantic_recall.KINDS"
    assert set(sr.COACH_KINDS) <= set(sr.KINDS)
    assert set(sr.READER_KINDS) <= set(sr.KINDS)


def test_an_unregistered_kind_is_excluded_by_default_everywhere():
    """The excluded-by-default property, exercised rather than asserted about.

    A kind nobody has decided on is not indexable, is not in either derived tuple, and is
    dropped by the retrieval filter.
    """
    rogue = "checkin_transcript"
    assert rogue not in sr.KINDS  # if this ever ships, it needs its own decisions
    assert rc.decide(rogue, "verbatim text", {}).indexable is False
    assert rogue not in sr.COACH_KINDS and rogue not in sr.READER_KINDS
    assert sr.filter_kinds([{"kind": rogue, "doc_date": "2026-08-03"}], sr.COACH_KINDS) == []


def test_filter_kinds_fails_closed_on_empty_and_missing():
    corpus = [{"kind": sr.KIND_CHRONICLE}, {"kind": ""}, {}]
    assert sr.filter_kinds(corpus, ()) == [], "an empty allowlist must permit nothing, not everything"
    assert sr.filter_kinds(corpus, sr.COACH_KINDS) == [{"kind": sr.KIND_CHRONICLE}]


# ── index-time consent: mutation-proven in BOTH directions ──────────────────
def test_unmarked_journal_entry_is_not_indexed_at_all():
    """Direction 1 — an unmarked entry reaching the corpus turns the guard red.

    `private` is the default for any entry without an owner marker, and the decision
    (documented in `recall_consent`) is NOT INDEXED rather than indexed-without-a-snippet.
    """
    record = _journal_record()
    assert diary_consent.resolve_consent(record) == diary_consent.TIER_PRIVATE

    decision = rc.decide_doc(_journal_doc(record))
    assert decision.indexable is False
    assert decision.exposure == rc.EXPOSURE_NONE
    assert decision.snippet == ""

    table = RecordingTable()
    status = ri.index_document(table, _journal_doc(record), embed=_fake_embed, now="2026-08-11T00:00:00+00:00")
    assert status == ri.SKIPPED_CONSENT
    assert table.puts == [], "an unmarked private entry must produce NO corpus row"
    assert table.updates == []


@pytest.mark.parametrize("marker", ["", None, "public_ok", "PRIVATE", 1, "quotes"])
def test_malformed_or_unknown_markers_are_private(marker):
    record = _journal_record(**{diary_consent.CONSENT_FIELD: marker})
    assert rc.decide_doc(_journal_doc(record)).indexable is False


def test_a_journal_doc_with_no_source_record_is_withheld():
    """Fail-closed on the plumbing, not just on the data: a gatherer that forgets to
    attach the source record cannot resolve consent, so the entry is private."""
    doc = _journal_doc(_journal_record())
    doc.pop(rc.RECORD_KEY)
    decision = rc.decide_doc(doc)
    assert decision.indexable is False
    assert "unresolvable" in decision.reason


def test_cleared_quote_entry_still_flows_and_stores_only_the_cleared_line():
    """Direction 2 — a cleared entry still flows.

    And the QUOTE permission is scoped to the line the owner cleared: the rest of the
    body must not ride along, which is exactly what the pre-#2587 writer would have done
    by storing `_snippet(doc["text"])`.
    """
    record = _journal_record(**{diary_consent.CONSENT_FIELD: "quote", diary_consent.QUOTE_FIELD: _CLEARED_LINE})
    decision = rc.decide_doc(_journal_doc(record))
    assert decision.indexable is True
    assert decision.exposure == rc.EXPOSURE_QUOTE
    assert decision.snippet == _CLEARED_LINE

    table = RecordingTable()
    status = ri.index_document(table, _journal_doc(record), embed=_fake_embed, now="2026-08-11T00:00:00+00:00")
    assert status == ri.INDEXED
    (row,) = table.puts
    assert row["snippet"] == _CLEARED_LINE
    assert "my brother" not in row["snippet"], "clearing one line is not clearing the entry"
    assert row["kind"] == sr.KIND_JOURNAL


def test_allude_entry_flows_with_a_paraphrase_and_no_verbatim_text():
    """`allude` and `quote` are DIFFERENT permissions — allude buys a coarse theme, not a
    verbatim excerpt. The stored descriptor is built from the sanctioned projection, so
    no run of words from the body appears in it."""
    record = _journal_record(**{diary_consent.CONSENT_FIELD: "allude"})
    decision = rc.decide_doc(_journal_doc(record))
    assert decision.indexable is True
    assert decision.exposure == rc.EXPOSURE_ALLUDE

    table = RecordingTable()
    assert ri.index_document(table, _journal_doc(record), embed=_fake_embed, now="n") == ri.INDEXED
    (row,) = table.puts
    stored = row["snippet"]
    assert "relationships" in stored, "the coarse laundered theme is what allude grants"
    # No 5-word run of the private body may appear in the stored snippet.
    words = _BODY.split()
    runs = [" ".join(words[i : i + 5]) for i in range(len(words) - 4)]
    leaked = [r for r in runs if r.lower() in stored.lower()]
    assert not leaked, f"allude tier stored verbatim journal text: {leaked}"


def test_quote_that_does_not_ground_degrades_to_allude_not_to_a_paraphrased_quote():
    """ADR-104: a cleared line that is not a literal substring of the body licenses
    nothing verbatim. `diary_consent` already decides this — the point here is that the
    index honours the degraded tier instead of trusting the marker."""
    record = _journal_record(**{diary_consent.CONSENT_FIELD: "quote", diary_consent.QUOTE_FIELD: "a line he never actually wrote"})
    decision = rc.decide_doc(_journal_doc(record))
    assert decision.indexable is True
    assert decision.exposure == rc.EXPOSURE_ALLUDE
    assert "never actually wrote" not in decision.snippet


def test_published_artifacts_keep_their_verbatim_excerpt():
    """The gate must not break the 19 live chronicle rows: a published installment is a
    page the reader can already open, so a verbatim excerpt discloses nothing new."""
    for kind in (sr.KIND_CHRONICLE, sr.KIND_COACH):
        decision = rc.decide(kind, "Week 4 of The Measured Life. The wall arrived on a Tuesday.", None)
        assert decision.indexable is True
        assert decision.exposure == rc.EXPOSURE_QUOTE
        assert decision.snippet.startswith("Week 4 of The Measured Life")


# ── retrieval: the kind allowlist reaches the assembled prompt ──────────────
def _corpus_row(kind, date, snippet_text):
    return {
        "vector": [1.0, 0.0, 0.0],
        "kind": kind,
        "doc_date": date,
        "cycle": 13,
        "link": "/journal/posts/week-01/",
        "snippet": snippet_text,
        "artifact_pk": "USER#matthew#SOURCE#x",
        "artifact_sk": f"DATE#{date}",
        "sk": sr.sk_for(kind, date),
    }


def test_retrieve_drops_a_kind_that_is_not_on_the_coach_allowlist(monkeypatch):
    """The guard is asserted on the ASSEMBLED PROMPT BLOCK, because that is the artifact
    that reaches the model — not on the corpus list, which nobody publishes."""
    rows = [
        _corpus_row(sr.KIND_CHRONICLE, "2026-07-14", "published installment lead"),
        _corpus_row("checkin_transcript", "2026-07-15", "MATTHEW SAID SOMETHING PRIVATE"),
    ]
    monkeypatch.setattr(sr, "load_corpus", lambda _table: rows)
    table = RecordingTable(stored={})
    monkeypatch.setattr(sr, "reconcile_precedent", lambda _t, p: dict(p))

    got = sr.retrieve(table, [1.0, 0.0, 0.0])
    kinds = {p["kind"] for p in got}
    assert kinds == {sr.KIND_CHRONICLE}
    block = sr.recall_block(got)
    assert "2026-07-15" not in block
    assert "PRIVATE" not in block


def test_journal_is_retrievable_by_the_coach_but_not_by_a_reader_surface(monkeypatch):
    """The two consumers differ, and the difference is enforced rather than documented."""
    rows = [_corpus_row(sr.KIND_JOURNAL, "2026-08-03", "journal entry (video_diary) — theme: relationships.")]
    monkeypatch.setattr(sr, "load_corpus", lambda _table: rows)
    monkeypatch.setattr(sr, "reconcile_precedent", lambda _t, p: dict(p))
    table = RecordingTable(stored={})

    assert [p["kind"] for p in sr.retrieve(table, [1.0, 0.0, 0.0])] == [sr.KIND_JOURNAL]
    assert sr.retrieve(table, [1.0, 0.0, 0.0], kinds=sr.READER_KINDS) == []


def test_the_two_reader_surfaces_share_one_decision():
    """`/api/ask` and the chronicle recall card read the same corpus; #2587 derives both
    from one registry so they cannot drift into disagreeing about what a reader may see."""
    assert ar.PUBLISHED_KINDS == sr.READER_KINDS
    assert sr.READER_KINDS == (sr.KIND_CHRONICLE,)


# ── structural: a third writer cannot skip the gate ─────────────────────────
def _sources_calling(fragment):
    hits = []
    for root in ("lambdas", "deploy", "scripts", "mcp"):
        base = os.path.join(_REPO, root)
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
                if fragment in text:
                    hits.append((os.path.relpath(path, _REPO), text))
    return hits


def test_every_corpus_writer_goes_through_the_consent_gate():
    """`make_embedding_item` is the ONLY way a corpus row is built. Every file that calls
    it must also call the consent gate — so a new writer that forgets is a red test, not a
    quiet bypass. The definition site itself is excluded."""
    writers = {rel: text for rel, text in _sources_calling("make_embedding_item(") if rel != "lambdas/ai/semantic_recall.py"}
    assert set(writers) == {
        "lambdas/ai/recall_indexer.py",
        "deploy/backfill_recall_embeddings.py",
    }, f"unexpected corpus writer set — each must be consent-gated: {sorted(writers)}"
    for rel, text in writers.items():
        assert "recall_consent" in text and "decide_doc(" in text, f"{rel} builds a corpus row without calling the #2587 consent gate"
        assert "snippet=decision.snippet" in text, f"{rel} must store the consent-permitted snippet, not a raw excerpt of the body"


def test_the_gate_does_not_reimplement_the_consent_precedence():
    """The tier must come from `diary_consent`, not from a second copy of the rules."""
    with open(os.path.join(_REPO, "lambdas", "ai", "recall_consent.py"), "r", encoding="utf-8") as fh:
        src = fh.read()
    assert "diary_consent.public_context(" in src
    assert f'"{diary_consent.CONSENT_FIELD}"' not in src, "read the tier through diary_consent, never by re-reading its field"
