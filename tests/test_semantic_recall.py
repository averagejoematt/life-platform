"""tests/test_semantic_recall.py — #1384 semantic recall.

Covers the load-bearing acceptance criteria:
  AC1 deterministic retrieval (same query → same ranked list + scores; score surfaces)
  AC2 grounded-gate BLOCK on an unresolvable precedent
  AC3 honest no-match (recall card absent below threshold)
  AC5 cross-reset cycle labeling on every precedent
  + the vector codec, cosine, and the ADR-105 non-causal copy discipline.
"""

import json

import pytest
import semantic_recall as sr
from fakes import FakeDdbTable


def _row(kind, date, vector, *, cycle=None, link="", artifact_pk="ARTPK", artifact_sk="ARTSK", doc_date=None):
    return sr.make_embedding_item(
        kind=kind,
        date=date,
        doc_date=doc_date or date,
        text=f"{kind} {date}",
        vector=vector,
        cycle=cycle,
        artifact_pk=artifact_pk,
        artifact_sk=artifact_sk,
        link=link,
    )


# ── vector codec + cosine ────────────────────────────────────────────────────
def test_encode_decode_roundtrip():
    vec = [0.1, -0.25, 0.9, 0.0, 1.0]
    back = sr.decode_vector(sr.encode_vector(vec))
    assert len(back) == len(vec)
    for a, b in zip(vec, back):
        assert abs(a - b) < 1e-6  # float32 precision


def test_cosine_bounds():
    assert sr.cosine([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert sr.cosine([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)
    assert sr.cosine([1, 0], []) == 0.0  # mismatched/empty → 0, never raises
    assert sr.cosine([0, 0], [0, 0]) == 0.0  # zero-norm


# ── AC1: deterministic retrieval ─────────────────────────────────────────────
def _det_corpus():
    return [
        {
            "vector": [1.0, 0.0, 0.0],
            "kind": "chronicle",
            "doc_date": "2026-04-06",
            "cycle": 9,
            "link": "/a",
            "sk": "DOC#chronicle#2026-04-06",
        },
        {
            "vector": [0.9, 0.1, 0.0],
            "kind": "chronicle",
            "doc_date": "2026-05-01",
            "cycle": 9,
            "link": "/b",
            "sk": "DOC#chronicle#2026-05-01",
        },
        {"vector": [0.0, 1.0, 0.0], "kind": "journal", "doc_date": "2026-03-01", "cycle": 8, "link": "/c", "sk": "DOC#journal#2026-03-01"},
    ]


def test_retrieval_is_deterministic_with_scores():
    q = [1.0, 0.05, 0.0]
    r1 = sr.rank_precedents(q, _det_corpus(), top_k=3, threshold=0.5)
    r2 = sr.rank_precedents(q, _det_corpus(), top_k=3, threshold=0.5)
    assert r1 == r2  # identical ranked list AND identical scores
    # scores surface WITH the match (never a bare vibe)
    assert all("similarity" in p and isinstance(p["similarity"], float) for p in r1)
    # highest-similarity first
    sims = [p["similarity"] for p in r1]
    assert sims == sorted(sims, reverse=True)
    # the orthogonal journal entry is below threshold and excluded
    assert all(p["date"] != "2026-03-01" for p in r1)


def test_ties_break_deterministically():
    # two docs with identical vectors → identical similarity; order must be stable
    corpus = [
        {"vector": [1.0, 0.0], "kind": "chronicle", "doc_date": "2026-05-02", "cycle": 9, "link": "", "sk": "DOC#chronicle#2026-05-02"},
        {"vector": [1.0, 0.0], "kind": "chronicle", "doc_date": "2026-05-01", "cycle": 9, "link": "", "sk": "DOC#chronicle#2026-05-01"},
    ]
    ranked = sr.rank_precedents([1.0, 0.0], corpus, top_k=2, threshold=0.1)
    # tie broken by ascending doc_date → the earlier date is first
    assert [p["date"] for p in ranked] == ["2026-05-01", "2026-05-02"]


def test_exclude_dates_prevents_self_match():
    corpus = _det_corpus()
    ranked = sr.rank_precedents([1.0, 0.0, 0.0], corpus, top_k=3, threshold=0.5, exclude_dates={"2026-04-06"})
    assert all(p["date"] != "2026-04-06" for p in ranked)


# ── AC3: honest no-match ─────────────────────────────────────────────────────
def test_honest_no_match_card_absent():
    # query orthogonal to everything → nothing clears threshold → no card
    corpus = [{"vector": [0.0, 1.0, 0.0], "kind": "chronicle", "doc_date": "2026-04-06", "cycle": 9, "link": "/a", "sk": "s"}]
    ranked = sr.rank_precedents([1.0, 0.0, 0.0], corpus, threshold=0.75)
    assert ranked == []
    assert sr.recall_card(ranked) is None


def test_recall_card_renders_when_match():
    precedents = [
        {"date": "2026-04-06", "similarity": 0.87, "cycle": 9, "kind": "chronicle", "source": "chronicle", "link": "/chronicle/week-12/"}
    ]
    card = sr.recall_card(precedents, threshold=0.75)
    assert card is not None
    assert card["resembles_date"] == "2026-04-06"
    assert card["similarity"] == 0.87
    assert card["cycle"] == 9
    assert "2026-04-06" in card["phrase"] and "0.87" in card["phrase"]
    # ADR-105: resembles, never causal
    assert "resembles" in card["phrase"].lower()
    assert "caused" not in json.dumps(card).lower() and "because" not in json.dumps(card).lower()


def test_card_below_threshold_absent():
    precedents = [{"date": "2026-04-06", "similarity": 0.60, "cycle": 9, "kind": "chronicle", "source": "chronicle", "link": "/x"}]
    assert sr.recall_card(precedents, threshold=0.75) is None


# ── AC5: cross-reset cycle labeling ──────────────────────────────────────────
def test_cross_reset_cycle_labeled_on_every_precedent():
    corpus = [
        {"vector": [1.0, 0.0], "kind": "chronicle", "doc_date": "2026-04-06", "cycle": 9, "link": "/a", "sk": "s1"},
        {"vector": [0.99, 0.01], "kind": "chronicle", "doc_date": "2026-06-01", "cycle": 10, "link": "/b", "sk": "s2"},
    ]
    ranked = sr.rank_precedents([1.0, 0.02], corpus, top_k=2, threshold=0.5)
    cycles = {p["date"]: p["cycle"] for p in ranked}
    assert cycles["2026-04-06"] == 9  # prior cycle preserved
    assert cycles["2026-06-01"] == 10
    # the source cycle is visible in the rendered line
    line = sr.render_precedent_line(ranked[0] if ranked[0]["date"] == "2026-04-06" else ranked[1])
    assert "cycle 9" in line


def test_load_corpus_spans_all_cycles():
    rows = [_row("chronicle", "2026-04-06", [1.0, 0.0], cycle=9), _row("chronicle", "2026-06-01", [0.0, 1.0], cycle=10)]
    table = FakeDdbTable(rows=rows)
    corpus = sr.load_corpus(table)
    assert {c["cycle"] for c in corpus} == {9, 10}
    assert all(c["vector"] for c in corpus)  # vectors decoded


# ── AC2: grounded-gate block on an unresolvable precedent ────────────────────
def test_precedent_citation_findings_blocks_unresolved():
    resolved = [{"date": "2026-04-06"}]
    # cites a DIFFERENT, unresolved precedent week
    text = "This period resembles the week of 2026-01-15 — a similar dip."
    findings = sr.precedent_citation_findings(text, resolved)
    assert len(findings) == 1
    assert findings[0]["type"] == "unresolvable_precedent"
    assert findings[0]["claimed"] == "2026-01-15"


def test_precedent_citation_findings_passes_resolved():
    resolved = [{"date": "2026-04-06"}]
    text = "This period echoes the week of 2026-04-06."
    assert sr.precedent_citation_findings(text, resolved) == []


def test_ordinary_data_dates_not_flagged_as_precedents():
    # a non-precedent-framed date (a weigh-in) must NOT be flagged
    resolved = [{"date": "2026-04-06"}]
    text = "Your last weigh-in was 2026-07-20 and protein held."
    assert sr.precedent_citation_findings(text, resolved) == []


def test_resolve_precedent_true_and_false():
    # a resolvable artifact is seeded into the store; an unresolvable one is not
    art = {"pk": "USER#matthew#SOURCE#chronicle", "sk": "DATE#2026-04-06", "title": "real"}
    table = FakeDdbTable(rows=[art])
    assert sr.resolve_precedent(table, {"artifact_pk": art["pk"], "artifact_sk": art["sk"]}) is True
    assert sr.resolve_precedent(table, {"artifact_pk": "GONE", "artifact_sk": "GONE"}) is False
    assert sr.resolve_precedent(table, {}) is False  # no ref → does not resolve


def test_retrieve_drops_unresolvable_precedents():
    # corpus has two similar docs; only one artifact exists in the store
    rows = [
        _row("chronicle", "2026-04-06", [1.0, 0.0], cycle=9, artifact_pk="A", artifact_sk="a"),
        _row("chronicle", "2026-05-01", [0.99, 0.01], cycle=9, artifact_pk="B", artifact_sk="b"),
    ]
    table = FakeDdbTable(rows=rows)
    # only artifact A exists → precedent for 2026-05-01 (B) must be dropped by resolve
    table.store.clear()
    table.store[("A", "a")] = {"pk": "A", "sk": "a"}
    out = sr.retrieve(table, [1.0, 0.02], top_k=5, threshold=0.5, resolve=True)
    assert [p["date"] for p in out] == ["2026-04-06"]


# ── copy discipline (ADR-105) ────────────────────────────────────────────────
def test_rendered_precedent_line_is_non_causal():
    # the READER-FACING copy (the cited line + the card phrase) must never assert cause
    p = {"date": "2026-04-06", "similarity": 0.9, "cycle": 9, "link": "/x"}
    line = sr.render_precedent_line(p).lower()
    assert "echo" in line or "resembl" in line
    assert "caused" not in line and "because" not in line
    assert "0.90" in line and "2026-04-06" in line and "cycle 9" in line


def test_recall_block_lists_precedents_with_scores():
    precedents = [{"date": "2026-04-06", "similarity": 0.9, "cycle": 9, "link": "/x"}]
    block = sr.recall_block(precedents).lower()
    assert "resembl" in block or "echo" in block
    assert "0.90" in block and "2026-04-06" in block  # date + score shown
    # the block's RULES intentionally instruct the model to never claim cause
    assert "hypothesis" in block
    assert sr.recall_block([]) == ""  # no precedents → no block


def test_resolved_precedent_dates():
    assert sr.resolved_precedent_dates([{"date": "2026-04-06"}, {"date": "2026-05-01"}, {}]) == {"2026-04-06", "2026-05-01"}


# ── grounded_generation composition (AC2 end-to-end shape) ───────────────────
def test_findings_compose_with_grounded_generation():
    import grounded_generation as gg

    resolved = [{"date": "2026-04-06"}]
    text = "Recovery is fine. This resembles the week of 2026-01-15."
    combined = gg.grounding_findings(text, facts=None, allowed=set()) + sr.precedent_citation_findings(text, resolved)
    types_seen = {f["type"] for f in combined}
    assert "unresolvable_precedent" in types_seen
    # correction_prompt renders the new finding class without KeyError
    note = gg.correction_prompt([f for f in combined if f["type"] == "unresolvable_precedent"])
    assert "precedent" in note.lower()
