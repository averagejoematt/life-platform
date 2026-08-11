"""tests/test_reading_resonance_2349.py — the `journal_resonance` WRITER (#2349).

Before this module existed, `reading_recommender.score_one` read
`state["journal_resonance"]` and multiplied it by `w_res` on every production call —
and nothing anywhere wrote the key, so the term was permanently `w_res * 0.0`. These
tests pin the two halves of the fix that can silently rot:

  1. the writer really WRITES (the term is non-zero and moves `fit` and the ranking);
  2. it fails SOFT — budget pause, no themes, or a Bedrock error return exactly
     today's 0.0 rather than an error.

Every assertion below is mutation-proven in both directions: breaking the writer (or
its fail-soft path) turns the relevant test red. A test that passed either way would
be the same class of defect the issue reports.
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from reading import reading_recommender as rr, reading_resonance as res, reading_store as rs  # noqa: E402
from reading_fakes import FakeTable  # noqa: E402

from mcp import tools_reading as tr  # noqa: E402

_TODAY = "2026-08-10"
# The one resonance fragment the recommender owns — read from the module rather than
# retyped, so a reworded clause moves these tests instead of silently orphaning them
# ("gate prose is a parsed interface").
_CLAUSE = rr._REASON["resonance"]


# ── a deterministic, offline stand-in for Titan ───────────────────────────────
# Bag-of-tokens vectors over a shared vocabulary: cosine is then REAL lexical overlap,
# so "the journal has been circling grief and memory" genuinely scores higher against a
# grief/memory book than against a naval history. No Bedrock, no network, no sampling.
def _fake_embed(text: str) -> list:
    vocab = sorted({w for w in "".join(c if c.isalnum() else " " for c in _CORPUS.lower()).split()})
    tokens = "".join(c if c.isalnum() else " " for c in (text or "").lower()).split()
    return [float(tokens.count(w)) for w in vocab]


_CORPUS = "grief memory loss mourning remembrance naval history colonial rivalry ships admiralty"


def _cos(a, b):
    d = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return d / (na * nb) if na and nb else 0.0


_GRIEF_BOOK = {"bookId": "grief1", "title": "The Year of Magical Thinking", "themes": ["grief", "memory", "loss", "mourning"]}
_NAVAL_BOOK = {"bookId": "naval1", "title": "The Wager", "themes": ["naval history", "colonial rivalry", "ships"]}


def _journal_row(date: str, themes, template="journal", suffix="1"):
    return {
        "pk": "USER#matthew#SOURCE#notion",
        "sk": f"DATE#{date}#journal#{template}#{suffix}",
        "date": date,
        "enriched_themes": list(themes),
        # The prose the writer must never read. Present here on purpose.
        "raw_text": "SECRET JOURNAL PROSE — nothing may transfer this out of the table.",
        "body_text": "SECRET JOURNAL PROSE — nothing may transfer this out of the table.",
    }


@pytest.fixture
def table():
    t = FakeTable()
    t.put_item(_journal_row("2026-08-01", ["grief", "memory", "mourning"]))
    t.put_item(_journal_row("2026-07-28", ["loss", "remembrance"], suffix="2"))
    return t


# ── the calibration map (pure) ────────────────────────────────────────────────
def test_calibrate_is_zero_at_and_below_the_measured_floor():
    assert res.calibrate(res.COSINE_FLOOR) == 0.0
    assert res.calibrate(res.COSINE_FLOOR - 0.05) == 0.0
    assert res.calibrate(-1.0) == 0.0


def test_calibrate_saturates_at_the_measured_ceiling_and_is_monotone():
    assert res.calibrate(res.COSINE_CEILING) == 1.0
    assert res.calibrate(0.9) == 1.0
    mid = res.calibrate((res.COSINE_FLOOR + res.COSINE_CEILING) / 2)
    assert 0.0 < mid < 1.0
    assert res.calibrate(res.COSINE_FLOOR + 0.01) < mid < res.calibrate(res.COSINE_CEILING - 0.01)


# ── the writer produces a real, non-zero, DISCRIMINATING score ────────────────
def test_writer_scores_the_matching_book_above_the_unrelated_one(table):
    out = res.compute(table, [_GRIEF_BOOK, _NAVAL_BOOK], today=_TODAY, embed=_fake_embed, budget_allow=lambda _f: True)
    assert out["status"] == res.OK
    assert out["n_entries"] == 2
    assert out["window"] == ["2026-07-28", "2026-08-01"]
    # the whole point of the issue: this is NOT 0.0 any more
    assert out["scores"]["grief1"] > 0.0
    assert out["scores"]["grief1"] > out["scores"]["naval1"]
    # provenance carries the RAW cosine behind each calibrated score (AC3)
    assert out["raw"]["grief1"] == pytest.approx(
        _cos(_fake_embed("grief; memory; mourning; loss; remembrance"), _fake_embed("grief; memory; loss; mourning")), abs=1e-3
    )


def test_resonance_moves_fit_and_flips_the_ranking(table):
    """The term is LIVE end to end: the same two books rank differently with the
    writer's scores than with the dead 0.0 the recommender saw before."""
    out = res.compute(table, [_GRIEF_BOOK, _NAVAL_BOOK], today=_TODAY, embed=_fake_embed, budget_allow=lambda _f: True)
    # Give the naval book the breadth advantage, so resonance is the only thing that
    # can reorder them — if the term were still dead, naval would win.
    base_state = {
        "curriculum_phase": 2,
        "week_color": "GREEN",
        "wheel_distribution": {"grief": 6, "naval": 4},
        "n_finished": 20,
        "n_abandoned": 5,
        "trust_ladder_mode": "shortlist",
    }
    books = [dict(_GRIEF_BOOK, domainTags=["grief"], pageCount=280), dict(_NAVAL_BOOK, domainTags=["naval"], pageCount=280)]

    dead = rr.rank(books, dict(base_state), top_n=2)
    live = rr.rank(books, dict(base_state, journal_resonance=out["scores"]), top_n=2)

    assert dead["recommendations"][0]["bookId"] == "naval1"  # breadth wins when resonance is dead
    assert live["recommendations"][0]["bookId"] == "grief1"  # resonance flips it
    lift = live["recommendations"][0]["fit"] - dead["recommendations"][1]["fit"]
    assert lift > 0.0


def test_high_resonance_surfaces_the_reason_clause(table):
    """AC3: `_reason_string` already emits a resonance clause — verify a REAL written
    value reaches it, rather than adding a second reason path."""
    out = res.compute(table, [_GRIEF_BOOK], today=_TODAY, embed=_fake_embed, budget_allow=lambda _f: True)
    scored = rr.score_one(
        dict(_GRIEF_BOOK, domainTags=["grief"], pageCount=280),
        {"curriculum_phase": 2, "journal_resonance": out["scores"]},
        rr.WEIGHTS[2],
    )
    assert scored["resonance"] > 0.45
    assert _CLAUSE in scored["reason"]


def test_weak_resonance_stays_out_of_the_reason(table):
    """The other half of AC3: the clause is a CLAIM about the journal, so a book the
    journal is not circling must not carry it. A weak (or zero) term stays silent."""
    book = dict(_NAVAL_BOOK, domainTags=["naval"], pageCount=280)
    out = res.compute(table, [_NAVAL_BOOK], today=_TODAY, embed=_fake_embed, budget_allow=lambda _f: True)
    assert out["scores"]["naval1"] <= 0.45  # no lexical overlap with a grief/memory journal
    weak = rr.score_one(book, {"curriculum_phase": 2, "journal_resonance": out["scores"]}, rr.WEIGHTS[2])
    assert _CLAUSE not in weak["reason"]
    # and with the key absent entirely (the pre-#2349 world) it is likewise silent
    assert _CLAUSE not in rr.score_one(book, {"curriculum_phase": 2}, rr.WEIGHTS[2])["reason"]


# ── fail-soft: every degraded path is EXACTLY today's 0.0, never an error ─────
def test_budget_pause_yields_no_scores_and_spends_nothing(table):
    calls = []

    def _counting_embed(text):
        calls.append(text)
        return _fake_embed(text)

    out = res.compute(table, [_GRIEF_BOOK], today=_TODAY, embed=_counting_embed, budget_allow=lambda _f: False)
    assert out["status"] == res.SKIPPED_BUDGET
    assert out["scores"] == {}
    assert calls == []  # a paused feature must not reach Bedrock at all


def test_bedrock_failure_is_fail_soft_not_an_error(table):
    def _boom(_text):
        raise RuntimeError("bedrock unavailable")

    out = res.compute(table, [_GRIEF_BOOK], today=_TODAY, embed=_boom, budget_allow=lambda _f: True)
    assert out["scores"] == {}
    assert out["status"].startswith(res.UNAVAILABLE)
    # and the recommender then behaves exactly as it did before the writer existed
    assert rr.score_one(_GRIEF_BOOK, {"journal_resonance": out["scores"]}, rr.WEIGHTS[2])["resonance"] == 0.0


def test_no_themed_journal_entries_is_honest_absence():
    empty = FakeTable()
    empty.put_item(_journal_row("2026-08-01", []))  # an entry that was never enriched
    out = res.compute(empty, [_GRIEF_BOOK], today=_TODAY, embed=_fake_embed, budget_allow=lambda _f: True)
    assert out["status"] == res.SKIPPED_NO_JOURNAL_THEMES and out["scores"] == {}


def test_book_without_themes_is_honest_absence(table):
    out = res.compute(table, [{"bookId": "b1", "title": "Un-enriched"}], today=_TODAY, embed=_fake_embed, budget_allow=lambda _f: True)
    assert out["status"] == res.SKIPPED_NO_BOOK_THEMES and out["scores"] == {}


def test_oversized_queue_withholds_the_WHOLE_map_not_a_prefix(table):
    many = [dict(_GRIEF_BOOK, bookId=f"b{i}") for i in range(res.MAX_CANDIDATES + 1)]
    out = res.compute(table, many, today=_TODAY, embed=_fake_embed, budget_allow=lambda _f: True)
    assert out["status"] == res.SKIPPED_TOO_MANY_CANDIDATES
    assert out["scores"] == {}  # a partial map would silently zero the un-embedded tail


# ── AC2: no journal prose ever leaves DynamoDB ────────────────────────────────
def test_journal_query_projects_themes_only_and_never_prose(table):
    seen = []

    class Recording:
        def query(self, **kw):
            seen.append(kw)
            return table.query(**{k: v for k, v in kw.items() if k not in ("ProjectionExpression", "ExpressionAttributeNames")})

    out = res.compute(Recording(), [_GRIEF_BOOK], today=_TODAY, embed=_fake_embed, budget_allow=lambda _f: True)
    assert out["status"] == res.OK
    assert len(seen) == 1
    projection = seen[0]["ProjectionExpression"]
    assert "enriched_themes" in projection
    for prose_field in ("raw_text", "body_text", "content", "summary", "notes"):
        assert prose_field not in projection


def test_journal_entries_are_reduced_to_date_and_themes_only(table):
    """Second line of defence behind the projection: even handed a full item (as the
    FakeTable returns — it does not honour ProjectionExpression), the gather drops
    everything but the date and the themes, so prose cannot reach the digest."""
    entries = res.journal_theme_entries(table, today=_TODAY)
    assert entries and all(set(e) == {"date", "themes"} for e in entries)


def test_gather_is_capped_and_keeps_the_MOST_RECENT_entries():
    t = FakeTable()
    for i in range(res.MAX_ENTRIES + 4):
        t.put_item(_journal_row(f"2026-07-{i + 1:02d}", [f"theme{i}"], suffix=str(i)))
    entries = res.journal_theme_entries(t, today=_TODAY)
    assert len(entries) == res.MAX_ENTRIES
    assert entries[0]["date"] == "2026-07-16"  # newest first, oldest 4 dropped
    assert min(e["date"] for e in entries) == "2026-07-05"


def test_gather_excludes_entries_older_than_the_lookback_window():
    t = FakeTable()
    t.put_item(_journal_row("2026-08-01", ["recent"]))
    t.put_item(_journal_row("2024-01-02", ["ancient"], suffix="2"))  # well outside 180d
    entries = res.journal_theme_entries(t, today=_TODAY)
    assert [e["date"] for e in entries] == ["2026-08-01"]


def test_theme_digest_reads_only_the_themes_field():
    """Third line of defence: the digest is built from `themes`, not from whatever
    else happens to be on the entry."""
    entry = {"date": "2026-08-01", "themes": ["grief"], "raw_text": "SECRET JOURNAL PROSE", "body_text": "SECRET JOURNAL PROSE"}
    assert res.theme_digest([entry]) == "grief"


def test_embedded_text_is_themes_only_never_journal_prose(table):
    """And the composition of the three: nothing prose-shaped reaches Bedrock."""
    embedded = []

    def _recording_embed(text):
        embedded.append(text)
        return _fake_embed(text)

    res.compute(table, [_GRIEF_BOOK], today=_TODAY, embed=_recording_embed, budget_allow=lambda _f: True)
    assert embedded  # something was embedded
    for text in embedded:
        assert "SECRET JOURNAL PROSE" not in text


# ── the MCP tool wiring: the key actually lands on the recommender state ──────
@pytest.fixture
def wired(monkeypatch, table):
    monkeypatch.setattr(rs, "table", table)
    monkeypatch.setattr(tr, "table", table)
    monkeypatch.setattr("ai.bedrock_client.embed_text", lambda text, **_kw: _fake_embed(text))
    monkeypatch.setattr("ai.budget_guard.allow", lambda _f: True)
    return table


def test_tool_state_carries_written_resonance_and_provenance(wired, monkeypatch):
    monkeypatch.setattr(tr, "_candidates_from_queue", lambda: [_GRIEF_BOOK, _NAVAL_BOOK])
    state, envelope = tr._build_recommender_state([_GRIEF_BOOK, _NAVAL_BOOK])
    assert state["journal_resonance"]["grief1"] > 0.0
    assert envelope["status"] == res.OK

    out = tr.tool_get_reading_recommendation({})
    prov = out["resonance_provenance"]
    assert prov["status"] == res.OK
    assert prov["n_journal_entries"] == 2
    assert prov["journal_window"] == ["2026-07-28", "2026-08-01"]
    assert prov["raw_cosine"]["grief1"] > prov["raw_cosine"]["naval1"]
    assert out["recommendations"][0]["resonance"] > 0.0
