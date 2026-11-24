"""tests/test_unscorable_sentence_6254.py — an unscorable call's simple-guess sentence survives the publication gate (#6254).

THE DEFECT, as measured read-only on 2026-11-23: `/api/ledger_export` served ``simple_guess.text == ""`` on every
``unscorable`` item (8 of the first 100, 14 of the first 200). The sentence ended with the row's STORED reason string.
One withheld graded row keeps a frozen copy of its engine stamp under ``original_grade.baseline.unscorable``; the gate
skips a row's top-level ``baseline`` (``TAINT_SKIP_KEYS``) but walks ``original_grade``, so the stored reason became
withheld text and every served sentence carrying the same six-word run was emptied.

THE FIX is in the sentence, not the gate: fixed words per reason CODE (``coach_baseline.UNSCORABLE_CODES`` ->
``site_api_calls.UNSCORABLE_WORDS``), sharing no six-word run with any stored reason. Everything here runs the REAL
gate (``web.narrative_publication`` + ``web.publication_snapshot``) over wire-shaped, Decimal-typed synthetic rows.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import coach_baseline as cb  # noqa: E402
from web import (  # noqa: E402
    narrative_publication as G,
    public_call_id as P,
    publication_snapshot as S,
    site_api_calls as calls,
    site_api_ledger_export as ledger,
)
from web.site_api_common import _decimal_to_float  # noqa: E402

TODAY = "2026-11-23"
STORED_REASONS = (cb.NO_FILED_READING, cb.NO_GRADED_READING, cb.NO_RULE, cb.NOT_GRADED, cb.INCOMPLETE_SPEC)
WITHHELD_CLAIM = "Synthetic: the fixture subject will log seven quiet evenings of reading before the month ends."
_PRIVATE = {"v": Decimal(1), "families": ["journal_presence"], "producer": "t", "stamped_at": "2026-11-02T12:00:00+00:00"}
# Stored correction notes of the kind a ruled row keeps (the #6102 corpus) — withheld text the sentences must not echo.
_STORED_NOTES = (
    "Could not be checked as filed: it depends on a condition that no record measures. The original grade is kept.",
    "Could not be checked as filed: the stored test checks a different claim from the sentence. The original grade is kept.",
    "Its condition was measured over the call's own window and did not happen, so the forecast was never tested. It was never graded.",
    "1 more could not be checked against the guess.",
)


class _Partitions:
    """A raw table answering a query by its partition key (the snapshot's loader filters the sort-key prefix)."""

    def __init__(self, rows):
        self.rows = list(rows)

    def query(self, **kw):
        pk = G._requested_pk(kw.get("KeyConditionExpression"), kw.get("ExpressionAttributeValues"), kw.get("ExpressionAttributeNames"))
        return {"Items": [dict(r) for r in self.rows if r["pk"] == pk]}

    def get_item(self, **kw):
        return {}


def _stamp(reason: str) -> dict:
    """An unscorable ``baseline`` stamp as DynamoDB returns it (``version`` is a Decimal on the wire)."""
    return {"rule": cb.RULE_ID, "version": Decimal(cb.RULE_VERSION), "unscorable": reason}


def _withheld_row(n: int, reason: str, note: str) -> dict:
    """A WITHHELD graded row (private provenance) that keeps a frozen copy of its stamp under ``original_grade`` —
    the live row's shape: the copy is outside ``TAINT_SKIP_KEYS``, so its reason string is withheld text."""
    return {
        "pk": "COACH#nutrition_coach",
        "sk": f"PREDICTION#pred_2026110{n}_synthetic_withheld_call",
        "prediction_id": f"pred_2026110{n}_synthetic_withheld_call",
        "coach_id": "nutrition_coach",
        "claim_natural": WITHHELD_CLAIM,
        "created_at": f"2026-11-0{n}T12:00:00.000004+00:00",
        "created_date": f"2026-11-0{n}",
        "status": "expired",
        "confidence": Decimal("0.6"),
        "provenance": _PRIVATE,
        "baseline": _stamp(reason),
        "outcome_notes": note,
        "original_grade": {
            "status": "refuted",
            "outcome_date": f"2026-11-1{n}",
            "snapshot_at": "2026-11-15T12:00:00+00:00",
            "baseline": _stamp(reason),
        },
    }


def _unscorable_row(reason: str = cb.NOT_GRADED, slug: str = "pred_20261110_synthetic_open_call") -> dict:
    """A servable graded call whose stamp is unscorable — a directional call that settled without a verdict."""
    return {
        "pk": "COACH#sleep_coach",
        "sk": f"PREDICTION#{slug}",
        "prediction_id": slug,
        "coach_id": "sleep_coach",
        "claim_natural": "",
        "created_at": "2026-11-10T12:00:00.000001+00:00",
        "created_date": "2026-11-10",
        "phase": "experiment",
        "status": "inconclusive",
        "outcome_date": "2026-11-17",
        "confidence": Decimal("0.55"),
        "evaluation": {"type": "directional", "metric": "recovery_score", "condition": "up", "evaluation_window_days": Decimal(7)},
        "baseline": _stamp(reason),
    }


def _corpus() -> list:
    """One withheld row per stored reason (so EVERY reason string is withheld text), each with a stored note."""
    return [_withheld_row(i + 1, reason, _STORED_NOTES[i % len(_STORED_NOTES)]) for i, reason in enumerate(STORED_REASONS)]


@pytest.fixture
def gate():
    """The real gate, opened on a table holding the withheld corpus — the complete-record half (#6111) taints it."""

    def _reset():
        G.reset_taint()
        G.begin_request()
        P.reset()
        S.reset()

    _reset()
    S.begin_request(_Partitions(_corpus()))
    yield
    _reset()


def _route(rows: list, **qs) -> dict:
    """The handler on Decimal-typed rows read the way the route's own fetch reads them: ``_query_partition`` hands
    the handler each DynamoDB item through ``_decimal_to_float``."""
    fetched = [_decimal_to_float(r) for r in rows]
    resp = ledger.handle_ledger_export({"queryStringParameters": qs}, fetch=lambda: ({"sleep": fetched}, [], []), today=TODAY)
    assert resp["statusCode"] == 200
    return resp


def _served(rows: list) -> list:
    """The route's items for ``rows``, through the handler and then the wire half of the gate (``annotate``)."""
    return json.loads(G.annotate(_route(rows, page="1", size="200"))["body"])["items"]


def _old_sentence(reason: str) -> str:
    """The pre-#6254 wording: the fixed lead followed by the row's STORED reason string."""
    return f"{calls.UNSCORABLE_LEAD}: {reason}."


def test_the_premise_holds_the_stored_reasons_are_withheld_text(gate):
    """The corpus reproduces the live cause: a frozen stamp under ``original_grade`` taints the stored reason, so the
    wording that ended with it is emptied by the real gate. Without this the tests below would pass against nothing."""
    assert G.is_tainted(_old_sentence(cb.NOT_GRADED)) and G.is_tainted(_old_sentence(cb.NO_FILED_READING))
    assert G.scrub_payload({"text": _old_sentence(cb.NOT_GRADED)}) == {"text": ""}


def test_an_unscorable_call_beside_a_withheld_row_with_the_same_reason_words_serves_its_sentence(gate):
    items = _served([_unscorable_row(reason, f"pred_2026111{i}_synthetic_open_call") for i, reason in enumerate(STORED_REASONS)])
    assert len(items) == len(STORED_REASONS)
    by_text = {i["simple_guess"]["text"] for i in items}
    assert by_text == {f"{calls.UNSCORABLE_LEAD}: {w}." for w in calls.UNSCORABLE_WORDS.values()}, "one fixed sentence per reason"
    for item in items:
        guess = item["simple_guess"]
        assert guess["state"] == "unscorable" and guess["right"] is None
        assert guess["text"] and guess["short"] == "could not be checked on this call"


def test_mutation_serving_the_stored_reason_again_is_emptied(gate, monkeypatch):
    """Revert the fix (the sentence ends with the stored string again) and the same route serves it empty."""
    monkeypatch.setattr(calls, "unscorable_text", lambda baseline: _old_sentence(str(baseline.get("unscorable"))))
    assert [i["simple_guess"]["text"] for i in _served([_unscorable_row()])] == [""]


def test_a_withheld_calls_words_are_still_emptied(gate):
    """The gate is untouched: the withheld row's claim, its stored note and its stored reason are emptied wherever a
    payload echoes them — in the same response that serves the fixed sentence."""
    resp = _route([_unscorable_row()])
    body = json.loads(resp["body"])
    body["echo"] = {
        "claim": WITHHELD_CLAIM,
        "note": f"Elsewhere: {_STORED_NOTES[0]}",
        "why": cb.NOT_GRADED,
        "old": _old_sentence(cb.NOT_GRADED),
    }
    out = json.loads(G.annotate({**resp, "body": json.dumps(body, default=str)})["body"])
    assert out["echo"] == {"claim": "", "note": "", "why": "", "old": ""}
    assert out["items"][0]["simple_guess"]["text"] == f"{calls.UNSCORABLE_LEAD}: {calls.UNSCORABLE_WORDS['not_graded']}."


def test_every_reason_code_has_fixed_words_that_pass_the_gate(gate):
    """SET, not instance: every stored reason has a code, every code has words, and no served sentence — nor the short
    form, nor the generic one — is tainted while every stored reason and note is withheld text."""
    named = {v for k, v in vars(cb).items() if k.isupper() and isinstance(v, str) and k.startswith(("NO_", "NOT_", "INCOMPLETE_"))}
    assert named == set(STORED_REASONS) == set(cb.UNSCORABLE_CODES), "a new stored reason needs a code"
    assert set(cb.UNSCORABLE_CODES.values()) == set(calls.UNSCORABLE_WORDS), "every code has reader words, and no stray one"
    for reason in STORED_REASONS:
        guess = calls.simple_guess(_stamp(reason), "direction", coach_right=False)
        assert guess["text"] and not G.is_tainted(guess["text"]) and not G.is_tainted(guess["short"]), reason
        assert reason not in guess["text"], "the stored string is never served"
    assert not G.is_tainted(calls.UNSCORABLE_GENERIC)
    # structural, independent of which rows are withheld today: no six-word run shared with ANY stored reason
    stored_runs = {r[i : i + G.SHINGLE] for r in map(G._norm_words, STORED_REASONS) for i in range(len(r) - G.SHINGLE + 1)}
    for text in [*(f"{calls.UNSCORABLE_LEAD}: {w}." for w in calls.UNSCORABLE_WORDS.values()), calls.UNSCORABLE_GENERIC]:
        words = G._norm_words(text)
        assert not {words[i : i + G.SHINGLE] for i in range(len(words) - G.SHINGLE + 1)} & stored_runs, text


def test_an_unknown_stored_reason_serves_the_generic_sentence_never_the_stored_string(gate):
    stored = "Synthetic: a reason some later writer stored about seven quiet evenings of reading."
    for stamp in (_stamp(stored), {"rule": cb.RULE_ID, "version": Decimal(1), "unscorable": Decimal(3)}):
        guess = calls.simple_guess(stamp, "number", coach_right=True)
        assert guess == {
            "state": "unscorable",
            "right": None,
            "text": calls.UNSCORABLE_GENERIC,
            "short": "could not be checked on this call",
        }
    assert cb.unscorable_code(_stamp(stored)) is None and cb.unscorable_code(None) is None
    # a stamp with no verdict and no stored reason is the rule's own default, as ``stamp()`` writes it
    assert cb.unscorable_code({"rule": cb.RULE_ID}) == cb.UNSCORABLE_CODES[cb.NO_RULE]


def test_no_unscorable_sentence_claims_a_comparison_happened():
    """ADR-104/105: an unscorable call was NOT compared. Every sentence says so and none states an outcome — the words a
    scored sentence uses for one ("That guess was …", "also") never appear, and the verdict stays null."""
    sentences = [
        calls.simple_guess(_stamp(r), k, coach_right=c)["text"]
        for r in STORED_REASONS
        for k in ("number", "direction")
        for c in (True, False)
    ]
    sentences.append(calls.UNSCORABLE_GENERIC)
    for text in sentences:
        assert text.startswith(calls.UNSCORABLE_LEAD) and "could not be checked" in text and text.endswith(".")
        low = text.lower()
        assert "that guess was" not in low and "also" not in low and "beat" not in low and "%" not in text
        assert not any(ch.isdigit() for ch in text), "no figure: nothing was measured"
    assert len({calls.simple_guess(_stamp(cb.NOT_GRADED), "direction", coach_right=c)["text"] for c in (True, False)}) == 1
