"""tests/test_recall_indexer.py — the recall corpus gets written without a human.

THE DEFECT. `semantic_recall` (#1384) shipped a read path with no writer. The only thing
that ever wrote the corpus was `deploy/backfill_recall_embeddings.py`, run by hand.
Measured on the live table 2026-08-08: 17 rows, every `embedded_at` inside one
three-second window on 2026-07-25, newest `doc_date` 2026-07-21 — while the chronicle
installment for 2026-08-02 sat unindexed and reader-visible, as every future week would
have. Retrieval does not fail loudly when its index stops growing; it returns fewer
precedents, which is indistinguishable from "there is no precedent" (ADR-104: that is
manufactured absence, the thing this platform is not allowed to do).

What is pinned here:
  WRITER    — a published installment lands in the corpus, with the artifact join keys
              and the published link, and re-running is free (text_sha idempotency).
  GATES     — a draft is NOT indexed (its text can still change and its page does not
              exist yet); a budget pause writes nothing; an empty body writes nothing.
  FAIL-SOFT — an embedder that raises returns FAILED and never propagates, because
              indexing must not be able to block a week from publishing.
  PARITY    — the doc the publish-time indexer builds is the doc the backfill builds,
              so a week embedded by either path produces the identical row.

Hermetic — no AWS, no Bedrock, no network, no wall clock.

Run with:   python3 -m pytest tests/test_recall_indexer.py -v
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pytest  # noqa: E402
from ai import recall_indexer as ri, semantic_recall as sr  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402

CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
_NOW = "2026-08-08T12:00:00+00:00"


def _week(n: int) -> str:
    """The date of post-genesis week `n`, derived from EXPERIMENT_START_DATE.

    Hardcoded dates rot: this file was first written with 2026-07-26 / 2026-08-02, which
    a re-anchor to a 2026-08-03 genesis silently turned into PRE-genesis installments —
    still passing, but exercising the prologue branch of the link ordering rather than
    the week branch these tests mean to cover.
    """
    from datetime import datetime, timedelta

    genesis = datetime.strptime(EXPERIMENT_START_DATE, "%Y-%m-%d").date()
    return (genesis + timedelta(days=7 * n)).isoformat()


WEEK_1, WEEK_2 = _week(0), _week(1)


def _vec(text):
    """Deterministic stand-in for Titan — the row's content matters here, not the geometry."""
    return [float(len(text) % 7), 1.0, 0.0]


def _inst(date, *, week_number=1, status="published", body="a body", phase="experiment", cycle=12):
    return {
        "pk": CHRONICLE_PK,
        "sk": f"DATE#{date}",
        "date": date,
        "week_number": week_number,
        "title": f"Week {week_number}",
        "subtitle": "Of The Measured Life",
        "content_markdown": body,
        "status": status,
        "phase": phase,
        "cycle": cycle,
    }


def condition_values(cond):
    """Every literal string inside a boto3 KeyConditionExpression, recursively.

    A test double MUST dispatch on the actual key, not on `repr(cond)` — boto3 conditions
    repr as `<boto3.dynamodb.conditions.And object at 0x...>`, so a repr substring check
    silently never matches and the fake answers every query from one branch. That is how
    the first draft of these tests passed while exercising nothing.
    """
    out = []
    try:
        values = cond.get_expression()["values"]
    except Exception:  # noqa: BLE001 — a plain value, not a condition
        return [cond] if isinstance(cond, str) else []
    for v in values:
        if isinstance(v, str):
            out.append(v)
        else:
            out.extend(condition_values(v))
    return out


class FakeTable:
    """Minimal DDB double: one chronicle partition to query, one recall partition to write."""

    def __init__(self, installments=(), rows=None):
        self.installments = list(installments)
        self.rows = dict(rows or {})
        self.puts = []
        self.updates = []
        self.query_calls = 0

    def query(self, **kwargs):
        self.query_calls += 1
        return {"Items": list(self.installments)}

    def get_item(self, Key):  # noqa: N803 — boto3's parameter name
        item = self.rows.get(Key["sk"])
        return {"Item": item} if item else {}

    def put_item(self, Item):  # noqa: N803 — boto3's parameter name
        self.puts.append(Item)
        self.rows[Item["sk"]] = Item

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues=None):  # noqa: N803
        """Applies the exact contract `refresh_metadata` emits: a name WITH a value is a
        SET, a name with no value is a REMOVE."""
        self.updates.append(UpdateExpression)
        row = self.rows.setdefault(Key["sk"], {})
        values = ExpressionAttributeValues or {}
        for ph, attr in ExpressionAttributeNames.items():
            vph = ":v" + ph[2:]
            if vph in values:
                row[attr] = values[vph]
            else:
                row.pop(attr, None)
        return {}


# ── WRITER ──────────────────────────────────────────────────────────────────
def test_a_published_installment_lands_in_the_corpus():
    """The whole point: publishing a week makes it citable as a precedent."""
    date = WEEK_2
    table = FakeTable([_inst(date)])

    assert ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_vec, now=_NOW) == ri.INDEXED

    (row,) = table.puts
    assert row["pk"] == sr.RECALL_PK
    assert row["sk"] == sr.sk_for(sr.KIND_CHRONICLE, date)
    assert row["kind"] == sr.KIND_CHRONICLE
    assert row["doc_date"] == date
    assert row["embedded_at"] == _NOW
    # AC2: the row joins back to a REAL record, which is what `resolve_precedent` checks.
    assert (row["artifact_pk"], row["artifact_sk"]) == (CHRONICLE_PK, f"DATE#{date}")
    # AC5: the source cycle rides along.
    assert row["cycle"] == 12
    # The vector round-trips through the base64 codec rather than being stored raw.
    assert sr.decode_vector(row["emb"]) == pytest.approx(_vec("Week 1 Of The Measured Life a body"))


def test_the_stored_link_is_the_published_post_url_not_the_dead_slug():
    """#1827's defect must not be reintroduced by the new writer: the link a coach may
    cite has to be a page that opens, or nothing at all."""
    date = WEEK_2
    table = FakeTable([_inst(date)])
    ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_vec, now=_NOW)

    link = table.puts[0]["link"]
    assert link.startswith("/journal/posts/week-")
    assert not link.startswith("/chronicle/week-")
    # And it survives the read-side dead-form filter unchanged.
    assert sr.safe_link(link) == link


def test_reindexing_unchanged_text_writes_nothing():
    """AC4 idempotency — the hook fires on every publish and on the sweep's retry path,
    so a re-run must cost neither a Bedrock call nor a write."""
    date = WEEK_2
    table = FakeTable([_inst(date)])
    assert ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_vec, now=_NOW) == ri.INDEXED
    assert len(table.puts) == 1

    def _explode(_text):
        raise AssertionError("re-embedded text that had not changed")

    assert ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_explode, now=_NOW) == ri.UNCHANGED
    assert len(table.puts) == 1


def test_edited_text_is_reindexed():
    """The other half of idempotency: `text_sha` must actually track the content, or a
    corrected installment would keep its stale vector forever."""
    date = WEEK_2
    table = FakeTable([_inst(date, body="original")])
    ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_vec, now=_NOW)

    table.installments = [_inst(date, body="revised after a correction")]
    assert ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_vec, now=_NOW) == ri.INDEXED
    assert len(table.puts) == 2
    assert table.puts[1]["text_sha"] != table.puts[0]["text_sha"]


# ── GATES ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status", ["draft", "changes_requested", ""])
def test_an_unpublished_installment_is_never_indexed(status):
    """A draft's text can still change and `/journal/posts/week-NN/` does not exist for
    it yet, so indexing one would put uncitable text into the coach's precedent pool."""
    date = WEEK_2
    table = FakeTable([_inst(date, status=status)])
    assert ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_vec, now=_NOW) == ri.SKIPPED_NOT_PUBLISHED
    assert table.puts == []


def test_a_missing_record_is_reported_not_invented():
    date = WEEK_2
    table = FakeTable([_inst(WEEK_1)])
    assert ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_vec, now=_NOW) == ri.SKIPPED_NO_RECORD
    assert table.puts == []


def test_an_empty_installment_body_writes_no_row():
    """An empty embedding is not a precedent — it is a zero vector that would match
    everything at whatever the threshold happened to allow."""
    date = WEEK_2
    empty = _inst(date, body="")
    empty["title"] = ""
    empty["subtitle"] = ""
    table = FakeTable([empty])
    assert ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_vec, now=_NOW) == ri.SKIPPED_NO_TEXT
    assert table.puts == []


def test_a_budget_pause_writes_nothing(monkeypatch):
    """Band 2 (ADR-125): recall pauses with the reader narrative it decorates. The gate
    has to sit BEFORE the embed call, or a paused tier still spends."""
    import ai.budget_guard as bg

    monkeypatch.setattr(bg, "allow", lambda feature: False)
    date = WEEK_2
    table = FakeTable([_inst(date)])

    def _explode(_text):
        raise AssertionError("embedded while the budget guard said no")

    assert ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_explode, now=_NOW) == ri.SKIPPED_BUDGET
    assert table.puts == []


# ── FAIL-SOFT ───────────────────────────────────────────────────────────────
def test_an_embedder_that_raises_never_propagates():
    """Indexing must not be able to block a week from publishing. The status is FAILED —
    kept distinct from the 'nothing to do' skips so a broken embedder cannot read as a
    quiet no-op to whoever is looking at the logs."""
    date = WEEK_2
    table = FakeTable([_inst(date)])

    def _boom(_text):
        raise RuntimeError("bedrock is having a day")

    assert ri.index_chronicle_installment(table, CHRONICLE_PK, date, embed=_boom, now=_NOW) == ri.FAILED
    assert table.puts == []


def test_an_unreadable_table_never_propagates():
    class Broken(FakeTable):
        def query(self, **kwargs):
            raise RuntimeError("throttled")

    assert ri.index_chronicle_installment(Broken(), CHRONICLE_PK, WEEK_2, embed=_vec, now=_NOW) == ri.FAILED


# ── PARITY with the backfill ────────────────────────────────────────────────
def test_the_publish_hook_and_the_backfill_build_the_same_doc():
    """Two writers, one row shape. If they diverged, a week's row would depend on which
    path happened to embed it — and the backfill's metadata-refresh pass would flap."""
    import importlib.util

    path = os.path.join(_REPO, "deploy", "backfill_recall_embeddings.py")
    spec = importlib.util.spec_from_file_location("backfill_recall_embeddings", path)
    bf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bf)

    installments = [_inst(WEEK_1, week_number=1), _inst(WEEK_2, week_number=2)]
    table = FakeTable(installments)

    from_backfill = {d["date"]: d for d in bf.gather_chronicle(table)}
    links = ri.published_post_links(installments)
    for inst in installments:
        assert ri.chronicle_doc(inst, links) == from_backfill[inst["date"]]


def test_the_backfill_still_exposes_the_moved_helpers():
    """`published_post_links` moved into the bundled indexer so the Lambda and the script
    share ONE definition — the absence of which is how #1827's dead slug reached all 17
    live rows. The script's public surface must not have changed underneath its tests."""
    import importlib.util

    path = os.path.join(_REPO, "deploy", "backfill_recall_embeddings.py")
    spec = importlib.util.spec_from_file_location("backfill_recall_embeddings", path)
    bf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bf)

    assert bf.published_post_links is ri.published_post_links
    assert bf._date_from_sk is ri.date_from_sk
    assert bf._snippet is ri.snippet


def test_the_fixture_dates_stay_post_genesis():
    """The rot-guard that caught this file's first draft: hardcoded 2026-07-26/08-02
    fixtures went PRE-genesis when the experiment re-anchored to 2026-08-03, quietly
    moving these tests onto the prologue branch of the link ordering. `_week()` derives
    them instead, so a re-anchor moves the fixture with it."""
    assert WEEK_1 >= EXPERIMENT_START_DATE
    assert WEEK_2 > WEEK_1


# ── WIRING: the indexer is actually CALLED on publish ───────────────────────
# The bug this whole file exists to fix was a write path that was never invoked. A
# correct indexer nobody calls is the same outage with more code — `recall_card()` sat
# written-and-unreachable in this very module's read half for exactly that reason. So
# the call sites are pinned, not just the callee.
def _approve_mod(monkeypatch):
    import importlib.util

    monkeypatch.setenv("S3_BUCKET", "matthew-life-platform")
    path = os.path.join(_REPO, "lambdas", "emails", "chronicle_approve_lambda.py")
    spec = importlib.util.spec_from_file_location("chronicle_approve_lambda", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_autopublish_sweep_indexes_the_week_it_publishes(monkeypatch):
    from unittest import mock

    mod = _approve_mod(monkeypatch)
    draft = {"sk": f"DATE#{WEEK_2}", "date": WEEK_2, "status": "draft", "week_number": 1}
    with (
        mock.patch.object(mod, "_find_stale_drafts", return_value=[draft]),
        mock.patch.object(mod, "_publish_to_s3", return_value=[]),
        mock.patch.object(mod, "_invalidate_cloudfront"),
        mock.patch.object(mod, "_commit_recap"),
        mock.patch.object(mod, "_mark_published"),
        mock.patch.object(mod, "_invoke_elena_state_updater"),
        mock.patch.object(mod, "_invoke_email_sender"),
        mock.patch.object(mod, "_invoke_coach_panel_podcast"),
        mock.patch.object(mod, "_index_for_recall") as indexed,
    ):
        mod._sweep_stale_drafts(48)
    indexed.assert_called_once_with(WEEK_2)


def test_indexing_runs_after_the_record_is_marked_published(monkeypatch):
    """Ordering is load-bearing, not incidental: the indexer refuses anything whose
    stored status is not `published`, so calling it before `_mark_published` would make
    every publish a silent no-op — green tests, empty corpus."""
    from unittest import mock

    mod = _approve_mod(monkeypatch)
    order = []
    draft = {"sk": f"DATE#{WEEK_2}", "date": WEEK_2, "status": "draft", "week_number": 1}
    with (
        mock.patch.object(mod, "_find_stale_drafts", return_value=[draft]),
        mock.patch.object(mod, "_publish_to_s3", return_value=[]),
        mock.patch.object(mod, "_invalidate_cloudfront"),
        mock.patch.object(mod, "_commit_recap"),
        mock.patch.object(mod, "_invoke_elena_state_updater"),
        mock.patch.object(mod, "_invoke_email_sender"),
        mock.patch.object(mod, "_invoke_coach_panel_podcast"),
        mock.patch.object(mod, "_mark_published", side_effect=lambda d: order.append("mark")),
        mock.patch.object(mod, "_index_for_recall", side_effect=lambda d: order.append("index")),
    ):
        mod._sweep_stale_drafts(48)
    assert order == ["mark", "index"]


def test_the_publish_hook_swallows_an_indexer_failure(monkeypatch):
    """`_index_for_recall` is the outermost fail-soft boundary: a week must publish even
    if the corpus write is impossible."""
    from unittest import mock

    mod = _approve_mod(monkeypatch)
    with mock.patch.object(mod, "table", None):  # any use of it raises AttributeError
        mod._index_for_recall(WEEK_2)  # must not raise


# ── AC3: the recall card finally has a caller ───────────────────────────────
# `semantic_recall.recall_card` shipped with #1384 and had ZERO production callers until
# now — written, unit-tested, and unreachable. That is the same class of defect as the
# missing writer above: the code exists, so it reads as done, and nothing proves it runs.
def _precedent_corpus(table, date, *, link="/journal/posts/week-01/"):
    """Put one real precedent in the corpus and make it resolvable."""
    table.rows[sr.sk_for(sr.KIND_CHRONICLE, date)] = sr.make_embedding_item(
        kind=sr.KIND_CHRONICLE,
        date=date,
        text="an earlier week",
        vector=[1.0, 0.0, 0.0],
        cycle=12,
        artifact_pk=CHRONICLE_PK,
        artifact_sk=f"DATE#{date}",
        link=link,
        snippet="the week the sleep debt caught up",
        dims=3,
        embedded_at=_NOW,
    )


class CorpusTable(FakeTable):
    """Adds the corpus Query + artifact resolution `retrieve()` needs."""

    def query(self, **kwargs):
        if sr.RECALL_PK in condition_values(kwargs.get("KeyConditionExpression")):
            return {"Items": [r for k, r in self.rows.items() if k.startswith("DOC#")]}
        return {"Items": list(self.installments)}

    def get_item(self, Key):  # noqa: N803
        if Key["pk"] == CHRONICLE_PK:  # artifact resolution (AC2)
            item = next((i for i in self.installments if i["sk"] == Key["sk"]), None)
            return {"Item": item} if item else {}
        return super().get_item(Key)


def test_a_real_precedent_produces_a_card():
    table = CorpusTable([_inst(WEEK_1)])
    _precedent_corpus(table, WEEK_1)
    card = ri.recall_card_for_text(table, "this week", embed=lambda _t: [1.0, 0.0, 0.0])
    assert card is not None
    assert card["resembles_date"] == WEEK_1
    assert card["similarity"] >= sr.DEFAULT_THRESHOLD
    assert card["link"] == "/journal/posts/week-01/"


def test_no_precedent_above_threshold_produces_no_card():
    """ADR-104: the card must be ABSENT, not a weak match dressed up as a resemblance."""
    table = CorpusTable([_inst(WEEK_1)])
    _precedent_corpus(table, WEEK_1)
    assert ri.recall_card_for_text(table, "this week", embed=lambda _t: [0.0, 1.0, 0.0]) is None


def test_an_empty_corpus_produces_no_card():
    assert ri.recall_card_for_text(CorpusTable(), "this week", embed=lambda _t: [1.0, 0.0, 0.0]) is None


def test_a_budget_pause_produces_no_card(monkeypatch):
    import ai.budget_guard as bg

    monkeypatch.setattr(bg, "allow", lambda feature: False)
    table = CorpusTable([_inst(WEEK_1)])
    _precedent_corpus(table, WEEK_1)
    assert ri.recall_card_for_text(table, "this week", embed=lambda _t: [1.0, 0.0, 0.0]) is None


def test_a_failing_embedder_produces_no_card_and_never_raises():
    def _boom(_t):
        raise RuntimeError("bedrock is having a day")

    assert ri.recall_card_for_text(CorpusTable([_inst(WEEK_1)]), "this week", embed=_boom) is None


# ── AC3 render: the card reaches the published page ─────────────────────────
def _render():
    import importlib.util

    path = os.path.join(_REPO, "lambdas", "emails", "chronicle_render.py")
    spec = importlib.util.spec_from_file_location("chronicle_render", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_card_renders_the_score_and_refuses_to_claim_causation():
    """ADR-105: similarity is a hypothesis generator. The copy says 'resembles', shows the
    number, and says so explicitly — it must never assert that one week caused another."""
    cr = _render()
    html = cr._recall_card_html(
        {
            "resembles_date": WEEK_1,
            "similarity": 0.87,
            "link": "/journal/posts/week-01/",
            "snippet": "the week the sleep debt caught up",
            "provenance": "cosine similarity 0.87 vs the chronicle of " + WEEK_1,
        }
    )
    assert "resembles" in html
    assert "0.87" in html
    assert "not a cause" in html
    assert f'<a href="/journal/posts/week-01/">the week of {WEEK_1}</a>' in html
    for banned in ("because", "caused", "due to"):
        assert banned not in html.lower()


def test_no_card_renders_nothing_at_all():
    """Honest absence is an empty string, not an empty box saying 'no precedent found'."""
    assert _render()._recall_card_html(None) == ""


def test_a_precedent_with_no_page_is_cited_by_date_without_a_link():
    """#1827: a wiped prior-cycle installment has no reader page. Cite the date alone."""
    html = _render()._recall_card_html({"resembles_date": WEEK_1, "similarity": 0.9, "link": "", "provenance": "p"})
    assert f"the week of {WEEK_1}" in html
    assert "<a href=" not in html


def test_the_card_escapes_its_snippet():
    """The snippet is installment prose flowing into a published page."""
    html = _render()._recall_card_html(
        {"resembles_date": WEEK_1, "similarity": 0.9, "link": "", "snippet": "<script>x</script>", "provenance": "p"}
    )
    assert "<script>" not in html


def test_the_post_template_actually_interpolates_the_card():
    """The wiring assertion: `_recall_card_html` must be reachable FROM the page, not just
    correct in isolation — the exact gap that left `recall_card` dead for weeks."""
    import inspect

    src = inspect.getsource(_render().publish_to_journal)
    assert "recall_card_html" in src
    assert "{recall_card_html}" in src


# ── REPAIR (#2366): the idempotency gate fixes rot instead of shrugging at it ──
def _boom(text):
    raise AssertionError("re-embedded unchanged text — the repair path must never pay for an embed")


def _indexed(table, date, **kwargs):
    return ri.index_chronicle_installment(table, CHRONICLE_PK, date, **kwargs)


def test_a_rotted_link_on_unchanged_text_is_repaired_without_a_reembed():
    """THE defect: all 17 live rows carried #1827's retired `/chronicle/week-N/` slug, and
    because `text_sha` matched, `index_document` early-returned UNCHANGED forever — the
    corpus was unrepairable without an operator `--force` paying to re-embed unchanged
    text. The gate must repair the metadata for free instead."""
    date = WEEK_2
    table = FakeTable([_inst(date)])
    assert _indexed(table, date, embed=_vec, now=_NOW) == ri.INDEXED

    sk = sr.sk_for(sr.KIND_CHRONICLE, date)
    good_link = table.rows[sk]["link"]
    assert good_link.startswith("/journal/posts/week-")
    table.rows[sk]["link"] = "/chronicle/week-1/"  # the retired scheme

    assert _indexed(table, date, embed=_boom, now=_NOW) == ri.REPAIRED
    assert table.rows[sk]["link"] == good_link
    assert len(table.puts) == 1  # metadata refresh only — no second embedded row


def test_the_mutation_pair_a_correct_row_is_left_untouched():
    """The other half of the proof: a row whose link already resolves must NOT be
    rewritten — otherwise every publish would churn the corpus and REPAIRED would stop
    meaning anything."""
    date = WEEK_2
    table = FakeTable([_inst(date)])
    assert _indexed(table, date, embed=_vec, now=_NOW) == ri.INDEXED
    assert _indexed(table, date, embed=_boom, now=_NOW) == ri.UNCHANGED
    assert table.updates == []


def test_a_drifted_cycle_stamp_is_refreshed_with_the_link():
    """#2366 sub-face: a reset's carry-forward re-stamps the chronicle record's `cycle`
    while the corpus row keeps the value frozen at embed time."""
    date = WEEK_2
    table = FakeTable([_inst(date, cycle=10)])
    assert _indexed(table, date, embed=_vec, now=_NOW) == ri.INDEXED

    table.installments = [_inst(date, cycle=12)]  # the reset re-stamped the source record
    assert _indexed(table, date, embed=_boom, now=_NOW) == ri.REPAIRED
    assert table.rows[sr.sk_for(sr.KIND_CHRONICLE, date)]["cycle"] == 12


def test_a_cycle_that_went_away_is_removed_not_zeroed():
    """An unstamped source record must yield NO cycle claim on the corpus row rather
    than a stale or invented one (ADR-104)."""
    date = WEEK_2
    table = FakeTable([_inst(date, cycle=12)])
    assert _indexed(table, date, embed=_vec, now=_NOW) == ri.INDEXED

    table.installments = [_inst(date, cycle=None)]
    assert _indexed(table, date, embed=_boom, now=_NOW) == ri.REPAIRED
    assert "cycle" not in table.rows[sr.sk_for(sr.KIND_CHRONICLE, date)]


def test_repair_runs_even_when_the_budget_is_paused(monkeypatch):
    """The repair is one update_item — no Bedrock, no spend — so a band-2 pause
    (ADR-125) must not hold the corpus in a known-rotted state. The embed path, which
    DOES cost money, stays gated."""
    date = WEEK_2
    table = FakeTable([_inst(date)])
    assert _indexed(table, date, embed=_vec, now=_NOW) == ri.INDEXED
    sk = sr.sk_for(sr.KIND_CHRONICLE, date)
    table.rows[sk]["link"] = "/chronicle/week-1/"

    monkeypatch.setattr(ri, "_budget_allows", lambda: False)
    assert _indexed(table, date, embed=_boom, now=_NOW) == ri.REPAIRED

    fresh = FakeTable([_inst(date)])  # nothing stored ⇒ would need a paid embed ⇒ gated
    assert _indexed(fresh, date, embed=_boom, now=_NOW) == ri.SKIPPED_BUDGET
    assert fresh.puts == []


def test_a_failed_repair_reports_failed_not_a_raise():
    """Fail-soft like every other indexer outcome — and FAILED, not UNCHANGED, so the
    freshness guard keeps reporting the rot instead of a quiet no-op."""
    date = WEEK_2

    class _Throttled(FakeTable):
        def update_item(self, **kwargs):
            raise RuntimeError("throttled")

    table = _Throttled([_inst(date)])
    assert _indexed(table, date, embed=_vec, now=_NOW) == ri.INDEXED
    table.rows[sr.sk_for(sr.KIND_CHRONICLE, date)]["link"] = "/chronicle/week-1/"
    assert _indexed(table, date, embed=_boom, now=_NOW) == ri.FAILED
