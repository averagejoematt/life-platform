"""tests/test_ask_retrieval_2348.py — #2348: /api/ask retrieval.

THE DEFECT this pins. `/api/ask` fetched a fixed six-block snapshot and built the prompt
from it; the reader's question influenced NOTHING about what was fetched. Every test here
is a sentence about what a reader gets, and the two that matter most are the pair:
the question CHANGES the context (the feature), and when retrieval declines the prompt is
BYTE-IDENTICAL to the pre-#2348 one (the safety property).

Offline by construction — no AWS, no Bedrock, no model spend. Vectors are 4-dim so every
cosine in here is checkable by hand.

Every assertion below was mutation-proven: the code under test was broken (the kind
filter dropped, the link filter dropped, the query vector ignored, the floor removed, the
z-gate removed, the resolution pass removed, the fake table's pk filter inverted) and each
test was confirmed RED before the code was restored. A test that cannot go red is not a
test — it is a comment with a pytest decorator.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ai import semantic_recall as sr  # noqa: E402
from bundle_stubs import stub_bundled_module  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import ask_retrieval as ar  # noqa: E402

CHRON_PK = "USER#matthew#SOURCE#chronicle"


# ── corpus fixtures ─────────────────────────────────────────────────────────
def _row(kind, date, vector, *, link="", snippet="", cycle=13):
    """One recall-embeddings item, built through the SAME writer helper production uses
    (`make_embedding_item`), so a change to the stored shape breaks these tests loudly
    instead of letting them assert against a hand-rolled shape that no longer exists."""
    return sr.make_embedding_item(
        kind=kind,
        date=date,
        text=f"{kind}-{date}",
        vector=vector,
        artifact_pk=CHRON_PK,
        artifact_sk=f"DATE#{date}",
        link=link,
        snippet=snippet or f"the installment of {date}",
        cycle=cycle,
        dims=len(vector),
    )


def _artifact(date, cycle=13):
    """The record a precedent points at — present ⇒ the passage resolves (AC2)."""
    return {"pk": CHRON_PK, "sk": f"DATE#{date}", "cycle": cycle, "status": "published"}


def _recall_query_hook(table, **kwargs):
    """Answer `query()` by actually EVALUATING the KeyConditionExpression against the
    store, rather than handing back every row regardless of what was asked.

    This matters: a fake that ignores the key condition would make
    `test_the_corpus_load_reads_only_the_recall_partition` vacuous — it would pass even
    if `load_corpus` queried the wrong partition. The both-directions proof is that same
    test, which asserts the recall pk finds the recall rows AND that a decoy row under a
    different pk is not returned, then re-queries the decoy's own pk through this hook
    and gets the decoy back.
    """
    from boto3.dynamodb.conditions import ConditionExpressionBuilder

    built = ConditionExpressionBuilder().build_expression(kwargs["KeyConditionExpression"], is_key_condition=True)
    wanted = list(built.attribute_value_placeholders.values())[0]
    return {"Items": [i for i in table.store.values() if i.get("pk") == wanted]}


def _table(rows):
    return FakeDdbTable(rows=rows, query_hook=_recall_query_hook)


def _published_pair():
    """Two PUBLISHED installments pointing in different directions, plus their artifacts.
    A question near [1,0,0,0] should reach the first; one near [0,1,0,0] the second."""
    rows = [
        _row(sr.KIND_CHRONICLE, "2026-07-01", [1.0, 0.0, 0.0, 0.0], link="/journal/posts/week-01/", snippet="sleep held at eight hours"),
        _row(
            sr.KIND_CHRONICLE,
            "2026-07-08",
            [0.0, 1.0, 0.0, 0.0],
            link="/journal/posts/week-02/",
            snippet="the deadlift moved for the first time",
        ),
    ]
    return rows + [_artifact("2026-07-01"), _artifact("2026-07-08")]


class _FakeEmbed:
    """Stub for ai.bedrock_client — maps a question to a canned vector, records calls."""

    def __init__(self, mapping=None, raises=None):
        self.mapping = mapping or {}
        self.raises = raises
        self.seen: list = []

    def embed_text(self, text, **kwargs):
        self.seen.append(text)
        if self.raises is not None:
            raise self.raises
        return self.mapping.get(text, [1.0, 0.0, 0.0, 0.0])


def _wire(monkeypatch, embedder, *, budget_allows=True):
    stub_bundled_module(monkeypatch, "ai.bedrock_client", embedder)

    class _Guard:
        @staticmethod
        def allow(feature):
            return budget_allows

    stub_bundled_module(monkeypatch, "ai.budget_guard", _Guard)


# ══════════════════════════════════════════════════════════════════════════
# The feature: the reader's question decides what is fetched
# ══════════════════════════════════════════════════════════════════════════


def test_two_different_questions_select_two_different_archive_passages(monkeypatch):
    rows = _published_pair()
    embedder = _FakeEmbed({"how has sleep been?": [0.98, 0.2, 0.0, 0.0], "how is the deadlift going?": [0.2, 0.98, 0.0, 0.0]})
    _wire(monkeypatch, embedder)

    sleep_block, sleep_tel = ar.retrieve_block("how has sleep been?", table=_table(rows))
    lift_block, lift_tel = ar.retrieve_block("how is the deadlift going?", table=_table(rows))

    assert sleep_tel["status"] == "hit" and lift_tel["status"] == "hit"
    # The whole point of the issue: the two prompts differ, and each one leads with the
    # installment its own question is about.
    assert sleep_block != lift_block
    assert "2026-07-01" in sleep_block.split("\n")[2] and "sleep held at eight hours" in sleep_block
    assert "2026-07-08" in lift_block.split("\n")[2] and "the deadlift moved" in lift_block
    # Each call embedded ITS OWN question — the one thing the pre-#2348 path never did.
    assert embedder.seen == ["how has sleep been?", "how is the deadlift going?"]
    assert lift_tel["n"] == 2 and lift_tel["top"] is not None


def test_the_block_cites_a_date_a_score_and_an_openable_page_for_every_passage(monkeypatch):
    rows = _published_pair()
    _wire(monkeypatch, _FakeEmbed({"q": [1.0, 0.0, 0.0, 0.0]}))
    block, tel = ar.retrieve_block("q", table=_table(rows))

    assert tel["status"] == "hit"
    cited = [ln for ln in block.split("\n") if ln.strip().startswith("- ")]
    assert cited, "a hit must render at least one passage line"
    for line in cited:
        assert "similarity" in line
        assert "/journal/posts/week-" in line, "every cited passage must carry an openable page (AC2)"


# ══════════════════════════════════════════════════════════════════════════
# AC1 — published content only, guarded as a SET
# ══════════════════════════════════════════════════════════════════════════


def test_every_corpus_kind_is_explicitly_classified_reader_visible_or_withheld():
    """The guard is over the KIND NAMESPACE, not over today's three rows.

    `semantic_recall.KINDS` is the corpus vocabulary; a kind added there (a coach output,
    a journal enrichment, or something not yet invented) must be a deliberate decision to
    show or withhold. Deriving the case list from `sr.KINDS` means a new kind arrives here
    unclassified and this test fails until someone decides — rather than defaulting into
    reader answers because a hardcoded list in a test never mentioned it.
    """
    assert set(ar.PUBLISHED_KINDS) <= set(sr.KINDS), "a reader-visible kind must exist in the corpus vocabulary"
    withheld = [k for k in sr.KINDS if k not in ar.PUBLISHED_KINDS]
    assert withheld, "if every kind were reader-visible this test would assert nothing"

    for kind in sr.KINDS:
        # Same doc, same openable link, only the kind varies — so the kind is provably
        # the thing doing the work.
        doc = {"kind": kind, "link": "/journal/posts/week-01/", "vector": [1.0, 0.0, 0.0, 0.0], "doc_date": "2026-07-01"}
        kept = ar.published_corpus([doc])
        if kind in ar.PUBLISHED_KINDS:
            assert kept == [doc], f"{kind} is reader-visible and must survive the filter"
        else:
            assert kept == [], f"{kind} is not a published reader page and must never reach an answer"


@pytest.mark.parametrize("link", ["", "   ", "/chronicle/week-3/"])
def test_an_installment_with_no_live_page_never_reaches_a_reader(monkeypatch, link):
    """No link at all (a wiped prior-cycle installment, still in the index because
    cross-cycle memory is the point) and the retired `/chronicle/week-N/` form (#1827,
    a 404) are both "not published" — even when the vector is a perfect match."""
    rows = [_row(sr.KIND_CHRONICLE, "2026-05-04", [1.0, 0.0, 0.0, 0.0], link=link), _artifact("2026-05-04")]
    _wire(monkeypatch, _FakeEmbed({"q": [1.0, 0.0, 0.0, 0.0]}))

    block, tel = ar.retrieve_block("q", table=_table(rows))
    assert block == ""
    assert tel["status"] == "miss:no-published-corpus"
    assert "2026-05-04" not in block


def test_a_passage_with_no_openable_page_is_never_rendered_whoever_asks():
    """`render_block` is a public pure function, so the citability guarantee has to live
    IN it — not only in the corpus filter upstream of today's single caller."""
    linked = {"date": "2026-07-01", "similarity": 0.71, "link": "/journal/posts/week-01/", "snippet": "sleep held"}
    assert "2026-07-01" in ar.render_block([linked])
    for dead in ("", "   ", "/chronicle/week-3/"):
        assert ar.render_block([{**linked, "link": dead}]) == "", f"link {dead!r} is not an openable page"
    assert ar.render_block([]) == ""


# ══════════════════════════════════════════════════════════════════════════
# AC4 — honest absence, never the best of a bad lot
# ══════════════════════════════════════════════════════════════════════════


def test_a_question_the_archive_does_not_cover_returns_no_passage_at_all(monkeypatch):
    rows = _published_pair()
    _wire(monkeypatch, _FakeEmbed({"what about my taxes?": [0.0, 0.0, 1.0, 0.0]}))

    block, tel = ar.retrieve_block("what about my taxes?", table=_table(rows))
    assert block == ""
    assert tel["status"] == "miss:below-floor"
    # The honest-absence property: there WAS a highest-scoring passage; it was not served.
    assert tel["n"] == 2 and tel["top"] == 0.0


def test_a_uniformly_mediocre_corpus_is_a_miss_even_when_every_score_clears_the_floor():
    """AC4's harder half. When nothing stands out, the top score is 'best of a uniform
    mess', not a match — the variance test (ADR-105: thresholds from variance, not magic
    numbers) is what catches that, and it only runs once n supports it."""
    corpus = [
        {"kind": sr.KIND_CHRONICLE, "link": f"/journal/posts/week-0{i}/", "doc_date": f"2026-07-0{i}", "vector": [1.0, 0.0, 0.0, 0.0]}
        for i in range(1, 7)
    ]
    passages, tel = select_all(corpus, [1.0, 0.0, 0.0, 0.0])
    assert tel["n"] == 6 >= ar.MIN_STATS_N
    assert tel["basis"] == "floor", "identical scores have no spread — z is not computable and must not be claimed"
    assert tel["status"] == "hit" and passages, "an identical-vector corpus is a genuine (if uninformative) hit"

    # Now give one document a real edge and one a flat middle: the z-test separates them.
    spread = [dict(d) for d in corpus]
    spread[0]["vector"] = [1.0, 0.0, 0.0, 0.0]
    for d in spread[1:]:
        d["vector"] = [0.60, 0.80, 0.0, 0.0]
    _, sharp = select_all(spread, [1.0, 0.0, 0.0, 0.0])
    assert sharp["basis"] == "floor+z" and sharp["z"] is not None
    assert sharp["status"] == "hit"

    # And the inverse: raise the separation bar above the measured z and the same corpus
    # is now honestly a miss. Proves the z gate is load-bearing, not decoration.
    passages_blocked, blocked = ar.select_passages([1.0, 0.0, 0.0, 0.0], spread, floor=0.1, z_min=sharp["z"] + 1.0)
    assert blocked["status"] == "miss:no-separation" and passages_blocked == []


def select_all(corpus, vector):
    """`select_passages` with a permissive floor, so the test isolates the statistic
    under examination instead of accidentally testing the floor."""
    return ar.select_passages(vector, corpus, floor=0.1)


# ══════════════════════════════════════════════════════════════════════════
# ADR-105 — every statistical claim carries n
# ══════════════════════════════════════════════════════════════════════════


def test_the_telemetry_states_n_on_every_path_and_withholds_z_when_n_cannot_support_it(monkeypatch):
    small = [{"kind": sr.KIND_CHRONICLE, "link": "/journal/posts/week-01/", "doc_date": "2026-07-01", "vector": [1.0, 0.0, 0.0, 0.0]}]
    _, tel_small = ar.select_passages([1.0, 0.0, 0.0, 0.0], small, floor=0.1)
    assert tel_small["n"] == 1
    assert tel_small["z"] is None and tel_small["basis"] == "floor", "a z from n=1 would be a number with no evidence behind it"

    # n=3 with a REAL spread — the arithmetic would happily produce a z here. It is
    # withheld because MIN_STATS_N says three points is not a distribution, which is the
    # half of the rule a sd>0 check alone would not enforce.
    mid = []
    for i, v in enumerate(([1.0, 0.0, 0.0, 0.0], [0.5, 0.87, 0.0, 0.0], [0.7, 0.71, 0.0, 0.0]), start=1):
        mid.append({"kind": sr.KIND_CHRONICLE, "link": f"/journal/posts/week-0{i}/", "doc_date": f"2026-07-0{i}", "vector": v})
    _, tel_mid = ar.select_passages([1.0, 0.0, 0.0, 0.0], mid, floor=0.1)
    assert tel_mid["n"] == 3 and tel_mid["sd"] > 0
    assert tel_mid["z"] is None and tel_mid["basis"] == "floor", f"n=3 < MIN_STATS_N={ar.MIN_STATS_N} cannot support a separation claim"

    big = []
    for i in range(1, 8):
        v = [1.0, 0.0, 0.0, 0.0] if i == 1 else [0.5, 0.87, 0.0, 0.0]
        big.append({"kind": sr.KIND_CHRONICLE, "link": f"/journal/posts/week-0{i}/", "doc_date": f"2026-07-0{i}", "vector": v})
    _, tel_big = ar.select_passages([1.0, 0.0, 0.0, 0.0], big, floor=0.1)
    assert tel_big["n"] == 7 and tel_big["z"] is not None and tel_big["basis"] == "floor+z"


def test_every_retrieval_reports_its_own_wall_clock_so_the_added_latency_is_measurable(monkeypatch):
    """The added p95 on a synchronous reader path has to be answerable from the logs, not
    estimated — and ADR-150's revisit trigger is stated in exactly this quantity."""
    _wire(monkeypatch, _FakeEmbed({"q": [1.0, 0.0, 0.0, 0.0]}))
    for table, question in ((_table(_published_pair()), "q"), (_table([]), "q"), (_table(_published_pair()), "")):
        _, tel = ar.retrieve_block(question, table=table)
        assert isinstance(tel.get("elapsed_ms"), float), f"no wall-clock on the {tel.get('status')} path"


# ══════════════════════════════════════════════════════════════════════════
# AC2 — a cited passage resolves to a real record
# ══════════════════════════════════════════════════════════════════════════


def test_a_passage_whose_installment_no_longer_exists_is_never_cited(monkeypatch):
    """The embedding row survives; the record it points at does not. The passage must be
    dropped before it can inform an answer — an unresolvable citation is exactly what the
    grounding gate exists to stop."""
    rows = [_row(sr.KIND_CHRONICLE, "2026-07-01", [1.0, 0.0, 0.0, 0.0], link="/journal/posts/week-01/")]  # no _artifact()
    _wire(monkeypatch, _FakeEmbed({"q": [1.0, 0.0, 0.0, 0.0]}))

    block, tel = ar.retrieve_block("q", table=_table(rows))
    assert block == ""
    assert tel["status"] == "miss:unresolved" and tel["selected"] == 1 and tel["resolved"] == 0


def test_the_corpus_load_reads_only_the_recall_partition(monkeypatch):
    """Both directions, so the scoping claim is not vacuous: a decoy row under a
    DIFFERENT pk is absent from the loaded corpus, and the very same fake — asked for the
    decoy's own partition — hands the decoy back. If the fake simply returned nothing,
    the second half fails; if the read were unscoped, the first half fails."""
    decoy = _row(sr.KIND_CHRONICLE, "2026-06-01", [1.0, 0.0, 0.0, 0.0], link="/journal/posts/week-09/")
    decoy = {**decoy, "pk": "USER#matthew#SOURCE#some_other_partition"}
    table = _table(_published_pair() + [decoy])

    loaded = sr.load_corpus(table)
    assert {d["doc_date"] for d in loaded} == {"2026-07-01", "2026-07-08"}

    from boto3.dynamodb.conditions import Key

    other = table.query(KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#some_other_partition"))
    assert [i["sk"] for i in other["Items"]] == [decoy["sk"]], "the fake must be able to return the decoy, or the scoping proof is vacuous"


# ══════════════════════════════════════════════════════════════════════════
# Fail-soft — retrieval may cost the reader a block, never the answer
# ══════════════════════════════════════════════════════════════════════════


def test_a_budget_pause_silently_falls_back_to_the_fixed_snapshot(monkeypatch):
    embedder = _FakeEmbed({"q": [1.0, 0.0, 0.0, 0.0]})
    _wire(monkeypatch, embedder, budget_allows=False)

    block, tel = ar.retrieve_block("q", table=_table(_published_pair()))
    assert block == "" and tel["status"] == "skipped:budget"
    assert embedder.seen == [], "a paused retrieval must not spend on an embedding first"


def test_an_embedding_failure_costs_the_reader_the_block_and_nothing_else(monkeypatch):
    _wire(monkeypatch, _FakeEmbed(raises=RuntimeError("bedrock throttled")))
    block, tel = ar.retrieve_block("q", table=_table(_published_pair()))
    assert block == "" and tel["status"].startswith("skipped:error")


def test_a_dynamodb_failure_costs_the_reader_the_block_and_nothing_else(monkeypatch):
    _wire(monkeypatch, _FakeEmbed({"q": [1.0, 0.0, 0.0, 0.0]}))

    def _boom(**kwargs):
        raise RuntimeError("throttled")

    block, tel = ar.retrieve_block("q", table=FakeDdbTable(query_hook=lambda t, **k: _boom()))
    assert block == "" and tel["status"].startswith("skipped:error")


def test_an_empty_question_never_reaches_bedrock(monkeypatch):
    embedder = _FakeEmbed()
    _wire(monkeypatch, embedder)
    block, tel = ar.retrieve_block("   ", table=_table(_published_pair()))
    assert block == "" and tel["status"] == "skipped:no-question" and embedder.seen == []


# ══════════════════════════════════════════════════════════════════════════
# The safety property: a declining retrieval leaves the prompt exactly as it was
# ══════════════════════════════════════════════════════════════════════════


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


def test_when_retrieval_returns_nothing_the_prompt_is_byte_identical_to_the_old_one():
    """The safety property, stated so it can actually fail.

    Comparing "missing key" against "empty string" is NOT enough — both take the same
    branch, so that comparison passes even if the empty branch injects text. The real
    claim is that the archive section is PURELY ADDITIVE: the prompt with a block equals
    the prompt without it plus exactly that block, and the no-retrieval prompt contains no
    archive scaffolding at all.
    """
    ai = _ai()
    sentinel = "\nARCHIVE PASSAGES (1 excerpt(s)): sentinel-passage\n"
    ctx = {"weight_lbs": 205.0, "hrv_ms": 54.0, "reads": {}}

    empty = ai._ask_build_prompt({**ctx, "archive_block": ""})
    with_block = ai._ask_build_prompt({**ctx, "archive_block": sentinel})

    assert "ARCHIVE" not in empty, "a declined retrieval must leave no trace in the prompt"
    assert with_block.replace(sentinel, "") == empty, "the archive section must be purely additive"
    assert ai._ask_build_prompt(dict(ctx)) == empty, "a ctx with no archive key behaves like an empty block"


def test_a_retrieved_block_actually_lands_in_the_system_prompt():
    ai = _ai()
    ctx = {"weight_lbs": 205.0, "reads": {}, "archive_block": "\nARCHIVE PASSAGES (1 excerpt(s)):\n  - 2026-07-01 ...\n"}
    prompt = ai._ask_build_prompt(ctx)
    assert "ARCHIVE PASSAGES" in prompt and "2026-07-01" in prompt
    # It must sit inside the grounded context the answer is checked against, ahead of RULES.
    assert prompt.index("ARCHIVE PASSAGES") < prompt.index("RULES:")


def test_the_ask_endpoint_hands_the_readers_own_question_to_retrieval(monkeypatch):
    """The regression this issue is about: `_ask_fetch_context()` never saw the question.
    Whatever else changes, /api/ask must pass the READER'S question — not a template, not
    the previous turn — into retrieval, and the returned block must reach the prompt."""
    ai = _ai()
    seen: list = []

    def _fake_retrieve(question, *, table=None, top_k=None):
        seen.append(question)
        return "\nARCHIVE PASSAGES (1 excerpt(s)): sentinel-passage\n", {"status": "hit"}

    monkeypatch.setattr(ai, "_ask_retrieve", _fake_retrieve)
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda: {"reads": {}})
    monkeypatch.setattr(ai, "_get_anthropic_key", lambda: "k")
    monkeypatch.setattr(ai, "_ask_rate_check", lambda ip_hash, limit=5: (True, limit))
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_emit_token_metrics", lambda usage, endpoint: None)

    captured: dict = {}

    class _B:
        @staticmethod
        def invoke(req):
            captured.update(req)
            return {"content": [{"type": "text", "text": "the archive covers that."}], "usage": {}}

    stub_bundled_module(monkeypatch, "ai.bedrock_client", _B)

    resp = ai._handle_ask(
        {
            "rawPath": "/api/ask",
            "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
            "body": '{"question": "what did the deadlift week look like?"}',
            "headers": {},
        }
    )
    assert resp["statusCode"] == 200
    assert seen == ["what did the deadlift week look like?"]
    assert "sentinel-passage" in captured["system"]
