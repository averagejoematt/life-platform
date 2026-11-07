"""tests/test_prediction_publication.py — the call publication rule, unit by unit (owner ruling 2026-11-05).

``common.prediction_publication`` decides; ``web.call_publication`` enforces at the table. Every call here is
SYNTHETIC. The whole-surface inference test is ``tests/test_call_publication_privacy.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "tests"))

from call_publication_fixtures import registered  # noqa: E402
from common import (
    prediction_publication as PP,  # noqa: E402
    prediction_publication_registry as REG,  # noqa: E402
)
from web import call_publication as CP  # noqa: E402

LEGACY = "2026-10-20T12:00:00+00:00"
NEW = "2026-11-06T12:00:00+00:00"
PK = "COACH#sleep_coach"


def _call(pid, at=NEW, claim="Recovery will rise this week.", metric="recovery_score", verdict="gradeable", **extra):
    row = {
        "pk": PK,
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "created_at": at,
        "claim_natural": claim,
        "evaluation": {"type": "directional", "metric": metric, "condition": "up"},
    }
    if verdict:
        row["filing"] = {"verdict": verdict}
    row.update(extra)
    return row


# ── the registry carries no private call ──────────────────────────────────────────────────


def test_the_registry_is_digests_only():
    """The committed registry names no call, carries no words and is nothing but public digests + its instants."""
    src = (ROOT / "lambdas" / "common" / "prediction_publication_registry.py").read_text()
    packed = src.split("_PACKED = (", 1)[1].split(")", 1)[0]
    tokens = re.findall(r"[^\s\",]+", packed)
    assert tokens and all(re.fullmatch(r"[0-9a-f]{16}", t) for t in tokens)
    assert len(REG.PUBLIC_DIGESTS) == len(tokens) > 3000  # the reviewed public record (non-vacuity)
    assert set(REG.THROUGH) == {PP.CALL, PP.ASK, PP.DOCKET}
    assert not re.search(r"journal|silence|diary|pred_|COACH#", packed)


def test_a_digest_is_stable():
    """The identity scheme is a contract with the reviewed registry: changing it silently unlists every call."""
    assert PP.digest("COACH#sleep_coach", "pred_20260101_synthetic") == PP.digest("COACH#sleep_coach", "pred_20260101_synthetic")
    assert PP.digest("COACH#sleep_coach", "pred_20260101_synthetic") != PP.digest("COACH#mind_coach", "pred_20260101_synthetic")
    assert re.fullmatch(r"[0-9a-f]{16}", PP.digest("x", "y"))


# ── legacy calls: the reviewed registry decides ───────────────────────────────────────────


def test_a_legacy_call_is_public_only_when_the_registry_lists_it():
    listed, unlisted = _call("pred_20261020_synthetic_listed", LEGACY), _call("pred_20261020_synthetic_unlisted", LEGACY)
    with registered([listed]):
        assert PP.classify(PK, listed) == (PP.PUBLIC, "registry")
        assert PP.classify(PK, unlisted) == (PP.PRIVATE, "registry_not_public")
    assert PP.classify(PK, listed)[0] == PP.PRIVATE  # unregistered again: fail closed


def test_a_legacy_call_is_not_rescued_by_its_structure():
    """A reviewed-private call with a public metric and a gradeable filing stays private: the review decided it."""
    row = _call("pred_20261020_synthetic_private", LEGACY, claim="Protein recovery will lift his mood.", metric="total_protein_g")
    assert PP.row_is_public(PK, row) is False


# ── new calls: their structure decides; unclassified fails closed ─────────────────────────


@pytest.mark.parametrize(
    "row, expected",
    [
        (_call("pred_20261106_a"), (PP.PUBLIC, "structured_public")),
        (_call("pred_20261106_b", metric="steps"), (PP.PUBLIC, "structured_public")),  # resolved: every source public
        (_call("pred_20261106_c", verdict="observation"), (PP.PRIVATE, "unclassified_subject")),
        (_call("pred_20261106_d", verdict=None), (PP.PRIVATE, "unclassified_subject")),
        (_call("pred_20261106_e", metric="mood_valence"), (PP.PRIVATE, "unclassified_metric")),
        (_call("pred_20261106_f", claim="If he journals, recovery will rise."), (PP.PRIVATE, "private_words")),
        (_call("pred_20261106_g", claim="After the journaling silence, recovery will rise."), (PP.PRIVATE, "private_words")),
        (_call("pred_20261106_h", metric=None), (PP.PRIVATE, "unclassified_subject")),
    ],
)
def test_a_new_call_is_classified_by_its_structure(row, expected):
    assert PP.classify(PK, row) == expected


def test_every_metric_in_a_conditional_spec_must_be_public(monkeypatch):
    row = _call("pred_20261106_cond")
    row["evaluation"] = {"type": "conditional", "metric": "recovery_score", "antecedent": {"metric": "total_protein_g"}}
    assert PP.row_is_public(PK, row)
    from common import activity_publication as AP

    real = AP.source_class
    monkeypatch.setattr(AP, "source_class", lambda s: PP.PRIVATE if s == "macrofactor" else real(s))
    assert PP.classify(PK, row) == (PP.PRIVATE, "private_metric")


def test_a_new_bet_side_is_private_until_reviewed():
    """Owner ruling 2026-11-06: one side cannot show whether the other side is private, so a bet filed after the registry
    — its sides included — waits for the owner's review, whatever its criterion and words."""
    side = {"pk": PK, "sk": "PREDICTION#docket-x-2026-11-06", "prediction_id": "docket-x-2026-11-06", "created_at": NEW}
    clean = {**side, "source": "dispute_docket", "metric": "recovery_score_7day_avg", "claim_natural": "It holds."}
    assert PP.classify(PK, clean) == (PP.PRIVATE, PP.UNREVIEWED_BET)
    with registered([clean]):
        assert PP.classify(PK, clean) == (PP.PUBLIC, "registry")  # the owner's approval


def test_asks_and_bets():
    ask = {
        "pk": PK,
        "sk": "COMMITMENT#c_new",
        "created_at": NEW,
        "commitment_natural": "Walk after dinner.",
        "action_check": {"metric": "steps"},
    }
    assert PP.row_is_public(PK, ask)
    assert not PP.row_is_public(PK, {**ask, "action_check": None})  # a free-text ask: unclassified
    assert not PP.row_is_public(PK, {**ask, "commitment_natural": "Write one journal line."})
    bet = {
        "pk": PP.DOCKET_PK,
        "sk": "RESOLVED#2026-11-08#a__b#x",
        "opened_at": NEW,
        "criterion": {"metric": "hrv"},
        "claims": {"a": "HRV rises."},
    }
    assert PP.classify(PP.DOCKET_PK, bet) == (PP.PRIVATE, PP.UNREVIEWED_BET)  # a new bet waits for review
    with registered([bet]):
        assert PP.row_is_public(PP.DOCKET_PK, bet)
    assert PP.classify(PP.DOCKET_PK, {**bet, "opened_at": "2026-09-01T00:00:00+00:00"}) == (PP.PRIVATE, "registry_not_public")


# ── rows that name a call follow it ───────────────────────────────────────────────────────


def test_a_learning_follows_its_call_and_reads_only_what_it_must():
    reads = []

    def lookup(pk, key):
        reads.append((pk, key))
        return {"filed": _call(key), "private": _call(key, verdict="observation")}.get(key.split("_")[-1])

    learn = {"pk": PK, "sk": "LEARNING#2026-11-07#x"}
    listed = _call("pred_20261020_synthetic_listed", LEGACY)
    with registered([listed]):
        assert PP.classify(PK, {**learn, "prediction_id": listed["prediction_id"]}, lookup) == (PP.PUBLIC, "registry")
    # A legacy-dated id the registry does not list: private WITHOUT a read.
    assert PP.classify(PK, {**learn, "prediction_id": "pred_20261020_other"}, lookup) == (PP.PRIVATE, "registry_not_public")
    assert reads == []
    assert PP.row_is_public(PK, {**learn, "prediction_id": "pred_20261106_filed"}, lookup)
    assert not PP.row_is_public(PK, {**learn, "prediction_id": "pred_20261106_private"}, lookup)
    assert PP.classify(PK, {**learn, "prediction_id": "pred_20261106_gone"}, lookup) == (PP.PRIVATE, "call_unreadable")
    assert len(reads) == 3


def test_a_calibration_void_follows_its_call():
    void = {"pk": "USER#matthew#SOURCE#calibration", "sk": "CALIB#2026-09-06#void#pred#sleep_coach#pred_20261020_v"}
    assert PP.kind_of(void["pk"], void["sk"]) == PP.REFERENCE
    row = {**void, "coach_id": "sleep_coach", "prediction_id": "pred_20261020_v"}
    assert not PP.row_is_public(void["pk"], row)
    with registered([_call("pred_20261020_v", LEGACY)]):
        assert PP.row_is_public(void["pk"], row)
    assert PP.kind_of(void["pk"], "CALIB#2026-10-25#forecast#hrv") is None  # not a call's row


def test_ungoverned_rows_pass():
    assert PP.classify(PK, {"pk": PK, "sk": "OUTPUT#2026-11-07#daily"}) == (PP.PUBLIC, "not_governed")
    assert PP.classify("USER#matthew#SOURCE#whoop", {"sk": "DATE#2026-11-07"}) == (PP.PUBLIC, "not_governed")


def test_the_method_block():
    m = PP.method_block()
    assert m["version"] == 2 and m["effective"] == "2026-11-05" and m["history"][-1]["version"] == 2
    assert m["history"][0]["version"] == 1 and m["note"] == m["history"][-1]["note"]


# ── the table half: Limit, COUNT, projection, get_item ─────────────────────────────────────


class _Raw:
    """A one-partition fake that pages by Limit and resumes after ExclusiveStartKey, like DynamoDB."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query(self, **kw):
        self.calls.append(kw)
        items = list(self.rows)
        start = kw.get("ExclusiveStartKey")
        if start:
            keys = [r["sk"] for r in items]
            items = items[keys.index(start["sk"]) + 1 :]
        out = {"Items": items}
        lim = kw.get("Limit")
        if lim and len(items) > lim:
            out["Items"] = items[:lim]
            out["LastEvaluatedKey"] = {"pk": items[lim - 1]["pk"], "sk": items[lim - 1]["sk"]}
        return out

    def get_item(self, Key=None, **_kw):
        hit = [r for r in self.rows if r["sk"] == Key["sk"]]
        return {"Item": dict(hit[0])} if hit else {}


def _mixed(n=10):
    rows = []
    for i in range(n):
        private = i % 2 == 1
        rows.append(_call(f"pred_20261106_{i:02d}", claim="The journal will return." if private else f"Recovery will rise ({i})."))
    return rows


def test_limit_counts_what_is_served_and_resumes_after_it():
    raw = _Raw(_mixed())
    q = {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": PK}, "Limit": 3}
    page = CP.query(raw, q, PK, None)
    assert [r["prediction_id"] for r in page["Items"]] == ["pred_20261106_00", "pred_20261106_02", "pred_20261106_04"]
    assert page["Count"] == 3 and page["LastEvaluatedKey"]["sk"] == "PREDICTION#pred_20261106_04"
    nxt = CP.query(raw, {**q, "ExclusiveStartKey": page["LastEvaluatedKey"]}, PK, None)
    assert [r["prediction_id"] for r in nxt["Items"]] == ["pred_20261106_06", "pred_20261106_08"]
    assert "LastEvaluatedKey" not in nxt


def test_limit_fill_is_invariant_to_private_rows():
    """The same public rows come back whether or not private rows sit among them (the inference property)."""
    public_only = _Raw([r for r in _mixed() if "journal" not in r["claim_natural"]])
    mixed = _Raw(_mixed())
    q = {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": PK}, "Limit": 4}
    assert CP.query(public_only, q, PK, None)["Items"] == CP.query(mixed, q, PK, None)["Items"]


def test_negative_control_without_the_fill_a_window_moves(monkeypatch):
    """Mutation: one page only (no fill) — the served window now depends on the private rows, which the test above
    would catch."""
    monkeypatch.setattr(CP, "MAX_FILL_PAGES", 1)
    public_only = _Raw([r for r in _mixed() if "journal" not in r["claim_natural"]])
    mixed = _Raw(_mixed())
    q = {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": PK}, "Limit": 4}
    assert CP.query(public_only, q, PK, None)["Items"] != CP.query(mixed, q, PK, None)["Items"]


def test_count_counts_eligible_rows_only():
    out = CP.query(_Raw(_mixed()), {"KeyConditionExpression": "pk = :pk", "Select": "COUNT"}, PK, None)
    assert out["Count"] == 5 and "Items" not in out


def test_a_projected_read_is_widened_then_narrowed():
    raw = _Raw(_mixed(4))
    q = {"KeyConditionExpression": "pk = :pk", "ProjectionExpression": "#s", "ExpressionAttributeNames": {"#s": "status"}}
    sent = None

    def spy(**kw):
        nonlocal sent
        sent = kw
        return {"Items": [{k: v for k, v in r.items()} for r in raw.rows]}

    raw.query = spy
    out = CP.query(raw, q, PK, None)
    assert "#cpg_claim_natural" in sent["ProjectionExpression"] and sent["ExpressionAttributeNames"]["#cpg_filing"] == "filing"
    assert all("claim_natural" not in r and "filing" not in r for r in out["Items"]) and len(out["Items"]) == 2


def test_get_item_of_a_private_call_reads_as_absent():
    raw = _Raw(_mixed(2))
    assert "Item" in CP.get_item(raw, {"Key": {"pk": PK, "sk": "PREDICTION#pred_20261106_00"}}, None)
    assert "Item" not in CP.get_item(raw, {"Key": {"pk": PK, "sk": "PREDICTION#pred_20261106_01"}}, None)


def test_the_commitments_tally_counts_eligible_asks_only():
    from coach import commitment_grading as CG

    ask = {"pk": PK, "created_at": NEW, "action_check": {"metric": "steps"}, "status": "kept"}
    corpus = [{**ask, "sk": "COMMITMENT#a", "commitment_natural": "Walk after dinner."}]
    private = [{**ask, "sk": "COMMITMENT#b", "commitment_natural": "Write one journal line."}]
    clean, mixed = CG.build_tally(corpus), CG.build_tally(corpus + private)
    assert clean == mixed and clean["lifetime"]["total"] == 1 and clean["method"] == PP.METHOD_VERSION
