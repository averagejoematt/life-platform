"""tests/test_coach_plain_calls_4714.py — the plain-words check reaches a pending call and the set-aside list (#4714).

#4649 checked a coach's ``focused_on_now`` only. Two neighbours printed jargon unchecked: a pending call's
sentence under "Next" (the live sleep page: "Protein-slow-wave hypothesis could activate once protein EWMA
reaches 145g+ threshold.") and ``set_aside_for_now``. Held here, no model called:

  * the rule catches the EWMA sentence (a trade term a short word carries past the length rules);
  * a call is flagged ``reader_plain: False`` at emission but stays pending and gradable;
  * /api/predictions lists only plain pending calls, still counts the held one, and judges the words
    (so a row written before the rule goes too);
  * the writer asks once more for either list, and stores only plain items in both;
  * the route withholds a stored jargon set-aside item.
"""

import json
import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

from coach import plain_words, prediction_emission, stance_lint  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as api  # noqa: E402

EWMA_CALL = "Protein-slow-wave hypothesis could activate once protein EWMA reaches 145g+ threshold."
PLAIN_CALL = "His deep sleep should be longer tomorrow night than tonight."
SPEC = {"type": "directional", "metric": "sleep_duration_hours", "direction": "up", "window_days": 7}


def test_the_rule_catches_the_ewma_sentence_and_keeps_a_plain_call():
    assert plain_words.reasons(EWMA_CALL, plain_words.CALL_MAX_CHARS) == ["a specialist term: EWMA, slow wave, hypothesis"]
    assert plain_words.is_plain(PLAIN_CALL, plain_words.CALL_MAX_CHARS)
    # a call is a sentence: past the 80-char watch cap, still plain
    assert len(PLAIN_CALL * 2) > plain_words.MAX_CHARS and plain_words.is_plain(PLAIN_CALL * 2, plain_words.CALL_MAX_CHARS)
    assert not plain_words.is_plain(PLAIN_CALL * 3, plain_words.CALL_MAX_CHARS)
    assert plain_words.is_plain("the weighted average of his sleep") and not plain_words.is_plain("his EMA of sleep")


def test_emission_flags_a_jargon_call_but_leaves_it_pending_and_gradable():
    held = prediction_emission.build_prediction_record("sleep_coach", "2026-10-05", EWMA_CALL, SPEC, 0.6, "observational")
    ok = prediction_emission.build_prediction_record("sleep_coach", "2026-10-05", PLAIN_CALL, SPEC, 0.6, "observational")
    assert held["reader_plain"] is False and "reader_plain" not in ok
    assert (held["status"], held["gradeable_by"], held["evaluation"]) == (ok["status"], ok["gradeable_by"], SPEC)
    assert held["status"] == "pending"


def _rows():
    def row(pid, claim):
        return {
            "pk": "COACH#sleep_coach",
            "sk": f"PREDICTION#{pid}",
            "prediction_id": pid,
            "status": "pending",
            "created_date": "2026-10-05",
            "phase": "experiment",
            "claim_natural": claim,
            "evaluation": dict(SPEC),
            "subdomain": "sleep",
            "confidence": 0.6,
        }

    return [row("p_ewma", EWMA_CALL), row("p_plain", PLAIN_CALL)]


def test_the_ledger_lists_only_plain_pending_calls_and_still_counts_the_held_one(monkeypatch):
    def hook(table, **kw):
        pk = kw["KeyConditionExpression"]._values[0]._values[1]
        return {"Items": [dict(r) for r in _rows()] if pk == "COACH#sleep_coach" else []}

    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=hook))
    body = json.loads(api.handle_predictions({})["body"])
    texts = [p["text"] for p in body["predictions"]]
    assert texts == [PLAIN_CALL], texts
    assert body["by_coach"]["sleep"]["total"] == 2 and body["by_coach"]["sleep"]["pending"] == 2


def test_the_writer_retries_and_stores_only_plain_set_aside_items(monkeypatch):
    from coach import coach_history_summarizer as chs

    jargon = "Protein intake stabilization at threshold as a mechanistic lever for slow-wave architecture"
    draft = {"headline_read": "steady", "focused_on_now": ["log food most days"], "set_aside_for_now": [jargon, "one bad night"]}
    assert jargon in stance_lint.self_correction(draft)
    assert stance_lint.self_correction({**draft, "set_aside_for_now": ["one bad night"]}) == ""
    better = {**draft, "set_aside_for_now": ["one bad night"]}
    assert stance_lint.retry_is_better(better, draft) and not stance_lint.retry_is_better(draft, better)
    written = []
    monkeypatch.setattr(chs, "_put_item", lambda item: written.append(item) or True)
    assert chs._write_stance("sleep_coach", dict(draft, as_of="2026-10-05"))
    assert [w["set_aside_for_now"] for w in written] == [["one bad night"], ["one bad night"]]
    assert [w["focused_on_now"] for w in written] == [["log food most days"]] * 2


def test_the_route_withholds_a_stored_jargon_set_aside_item(monkeypatch):
    stored = {
        "headline_read": "I am waiting on steadier nights before I say more.",
        "focused_on_now": ["log food most days"],
        "set_aside_for_now": [EWMA_CALL, "one bad night"],
        "stage": {"label": "Waiting", "rationale": "Too few clean nights so far."},
        "as_of": "2026-10-05",
    }
    monkeypatch.setattr(api, "_stance_latest", lambda cid: stored if cid == "sleep_coach" else None)
    st = json.loads(api.handle_coach({"rawPath": "/api/coach/sleep_coach"})["body"])["stance"]
    assert st["set_aside_for_now"] == ["one bad night"]
