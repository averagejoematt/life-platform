"""test_recall_cycle_labels_1828.py — a precedent's cycle label agrees with the
authoritative record, across resets (ADR-104 / ADR-077).

#1828: the `cycle` stamp on a recall-embedding row is frozen at backfill time, but
chronicle records are RE-STAMPED by every experiment reset (ADR-077 carry-forward).
Nothing re-stamps `recall_embeddings` — it is correctly CROSS_PHASE, so the tagger skips
it, and the backfill's `text_sha` idempotency perpetuates the stale value — so the two
labels drift. Live at filing:

  - chronicle DATE#2026-02-28 stamped cycle=11 (carried forward) · embedding row said 10
  - chronicle DATE#2026-07-21 stamped cycle=11 · embedding row had NO cycle attribute,
    and `_cycle_label(None)` rendered the literal "an earlier cycle" — about a
    CURRENT-cycle installment

`rank_precedents` only excludes the generation date, so current-cycle docs ARE eligible
precedents; the coach prompt (and any coach text repeating it) therefore asserted a false
"when". Two fixes, pinned here:

  1. RE-DERIVE at render time from the chronicle record — `reconcile_precedent` reuses
     the AC2 resolution read, so the authoritative stamp wins with no extra I/O.
  2. NO CLAIM when unknown — an unstamped record renders without a cycle clause instead
     of asserting "an earlier cycle" (ADR-104: absence stays absent).

Hermetic — no AWS, no Bedrock.

Run with:   python3 -m pytest tests/test_recall_cycle_labels_1828.py -v
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import semantic_recall as sr  # noqa: E402

CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"


class _Table:
    """Serves the recall partition from `rows` and chronicle records from `artifacts`."""

    def __init__(self, rows, artifacts):
        self.rows = rows
        self.artifacts = artifacts
        self.get_calls = 0

    def query(self, **_kw):
        return {"Items": list(self.rows)}

    def get_item(self, Key=None, **_kw):
        self.get_calls += 1
        item = self.artifacts.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}


def _row(date, *, cycle, link="/journal/posts/week-03/"):
    item = {
        "pk": sr.RECALL_PK,
        "sk": sr.sk_for(sr.KIND_CHRONICLE, date),
        "kind": sr.KIND_CHRONICLE,
        "doc_date": date,
        "emb": sr.encode_vector([1.0, 0.0]),
        "link": link,
        "artifact_pk": CHRONICLE_PK,
        "artifact_sk": f"DATE#{date}",
    }
    if cycle is not None:
        item["cycle"] = cycle
    return item


def _artifact(date, *, cycle):
    item = {"pk": CHRONICLE_PK, "sk": f"DATE#{date}", "date": date}
    if cycle is not None:
        item["cycle"] = cycle
    return item


# ── 1. The two live discrepancies ────────────────────────────────────────────
def test_stale_stamp_is_corrected_from_the_chronicle_record():
    """Live repro A: embedding row says cycle 10, the carried-forward chronicle record
    says 11. ADR-077 makes the record authoritative."""
    table = _Table([_row("2026-02-28", cycle=10)], {(CHRONICLE_PK, "DATE#2026-02-28"): _artifact("2026-02-28", cycle=11)})
    precedents = sr.retrieve(table, [1.0, 0.0])
    assert len(precedents) == 1
    assert precedents[0]["cycle"] == 11
    assert "cycle 11" in sr.render_precedent_line(precedents[0])
    assert "cycle 10" not in sr.render_precedent_line(precedents[0])


def test_unstamped_row_takes_the_records_cycle_not_the_earlier_cycle_string():
    """Live repro B: the embedding row has NO cycle; the record is current-cycle 11. The
    old renderer called it 'an earlier cycle'."""
    table = _Table([_row("2026-07-21", cycle=None)], {(CHRONICLE_PK, "DATE#2026-07-21"): _artifact("2026-07-21", cycle=11)})
    line = sr.render_precedent_line(sr.retrieve(table, [1.0, 0.0])[0])
    assert "cycle 11" in line
    assert "an earlier cycle" not in line


# ── 2. Unknown stays unknown (no fabricated 'when') ──────────────────────────
def test_unknown_cycle_makes_no_cycle_claim_anywhere():
    """Neither side carries a stamp ⇒ the line states date + similarity only."""
    table = _Table([_row("2026-05-06", cycle=None)], {(CHRONICLE_PK, "DATE#2026-05-06"): _artifact("2026-05-06", cycle=None)})
    p = sr.retrieve(table, [1.0, 0.0])[0]
    assert p["cycle"] is None
    line = sr.render_precedent_line(p)
    assert "an earlier cycle" not in line and "cycle" not in line
    assert "2026-05-06" in line and "similarity" in line

    assert sr._cycle_label(None) == ""
    assert sr._cycle_label("") == ""
    assert sr._cycle_label(9) == "cycle 9"


def test_recall_card_provenance_omits_an_unknown_cycle():
    card = sr.recall_card([{"date": "2026-05-06", "similarity": 0.9, "cycle": None, "kind": "chronicle"}])
    assert "an earlier cycle" not in card["provenance"]
    assert card["provenance"].endswith("2026-05-06")
    assert card["cycle"] is None


# ── 3. Reconciliation costs no extra read, and stays fail-closed ─────────────
def test_reconciliation_reuses_the_resolution_read():
    """One get_item per precedent — the AC2 resolution read IS the cycle join."""
    table = _Table(
        [_row("2026-02-28", cycle=10), _row("2026-07-21", cycle=None)],
        {
            (CHRONICLE_PK, "DATE#2026-02-28"): _artifact("2026-02-28", cycle=11),
            (CHRONICLE_PK, "DATE#2026-07-21"): _artifact("2026-07-21", cycle=11),
        },
    )
    assert len(sr.retrieve(table, [1.0, 0.0])) == 2
    assert table.get_calls == 2


def test_unresolvable_precedent_is_still_dropped():
    """AC2 is unchanged: a precedent whose artifact is gone is never cited."""
    table = _Table([_row("2026-02-28", cycle=10)], {})
    assert sr.retrieve(table, [1.0, 0.0]) == []
    assert sr.reconcile_precedent(table, {"artifact_pk": CHRONICLE_PK, "artifact_sk": "DATE#nope"}) is None
    assert sr.resolve_precedent(table, {"artifact_pk": CHRONICLE_PK, "artifact_sk": "DATE#nope"}) is False


def test_reconciliation_is_fail_closed_on_a_read_error():
    class _Boom:
        def get_item(self, **_kw):
            raise RuntimeError("ddb down")

    assert sr.reconcile_precedent(_Boom(), {"artifact_pk": CHRONICLE_PK, "artifact_sk": "DATE#2026-02-28"}) is None


def test_a_non_integer_cycle_stamp_degrades_to_no_claim():
    table = _Table(
        [_row("2026-02-28", cycle=10)],
        {(CHRONICLE_PK, "DATE#2026-02-28"): {"pk": CHRONICLE_PK, "sk": "DATE#2026-02-28", "cycle": "eleven"}},
    )
    p = sr.retrieve(table, [1.0, 0.0])[0]
    assert p["cycle"] is None
    assert "cycle" not in sr.render_precedent_line(p)
