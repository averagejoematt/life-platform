"""tests/test_story_ledger_public_view_6199.py — #6199 G2: the season ledger's read doors return its public view.

Synthetic ledgers only. A thread, bet or ask that names a private call (``call_refs``) is dropped; an arc whose
``arc_refs`` do is dropped; a ``withheld_paths`` annotation on the ROW removes exactly the entries, fields or sentences
it names, and the stored ``ledger_json`` is never touched. A ledger with neither is returned as the same object.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

from content import private_call_check as P, story_ledger as L  # noqa: E402

PRIV, PUB = "COACH#alpha_coach/pred_20261201_synthetic_private", "COACH#alpha_coach/pred_20261201_synthetic_public"


def _is_private(pk, cid):
    return cid.endswith("_private")


def _ledger():
    return {
        "week": 5,
        "threads": [
            {"id": "t-priv", "status": "open", "note": "A private one.", "call_refs": [PRIV]},
            {"id": "t-pub", "status": "open", "note": "A public one.", "call_refs": [PUB]},
            {"id": "t-old", "status": "advanced", "note": "First line stays. Second line goes. Third line stays."},
        ],
        "bets": [{"week": 4, "claim": "a bet", "result": "open", "call_refs": [PRIV]}],
        "asks": [{"ask": "ask one", "status": "open"}, {"ask": "ask two", "status": "open"}],
        "arcs": {"alpha_coach": "Arc line one. Arc line two.", "beta_coach": "Beta arc."},
        "arc_refs": {"beta_coach": [PRIV]},
        "leads": [],
        "titles": [],
    }


def test_a_private_ref_drops_its_entry_and_keeps_the_public_one():
    view = L.public_view(_ledger(), _is_private)
    assert [t["id"] for t in view["threads"]] == ["t-pub", "t-old"]
    assert view["bets"] == []
    assert "beta_coach" not in view["arcs"] and view["arcs"]["alpha_coach"] == "Arc line one. Arc line two."


def test_a_sentence_address_removes_that_sentence_and_keeps_its_neighbours():
    view = L.public_view(_ledger(), _is_private, ["threads[2].note#sentence=2", "arcs.alpha_coach#sentence=1", "asks[0]"])
    old = next(t for t in view["threads"] if t["id"] == "t-old")
    assert old["note"] == "First line stays. Third line stays."
    assert view["arcs"]["alpha_coach"] == "Arc line two."
    assert [a["ask"] for a in view["asks"]] == ["ask two"], "a whole-entry path drops it; indices are the stored ones"


def test_two_sentences_of_one_field_address_the_same_split():
    view = L.public_view(_ledger(), _is_private, ["threads[2].note#sentence=1", "threads[2].note#sentence=3"])
    assert next(t for t in view["threads"] if t["id"] == "t-old")["note"] == "Second line goes."


def test_an_unreadable_classification_drops_the_entry_fail_closed():
    def broken(pk, cid):
        raise RuntimeError("classification unavailable")

    view = L.public_view(_ledger(), broken)
    assert [t["id"] for t in view["threads"]] == ["t-old"]
    unnamed = {**_ledger(), "threads": [{"id": "x", "status": "open", "note": "n", "call_refs": ["pred_without_partition"]}]}
    assert L.public_view(unnamed, lambda pk, cid: False)["threads"] == [], "a ref naming no partition cannot be classified"


def test_an_unresolvable_path_withholds_its_section_and_a_malformed_one_the_row():
    view = L.public_view(_ledger(), _is_private, ["threads[9].note#sentence=1"])
    assert view["threads"] == []
    assert L.public_view(_ledger(), _is_private, ["%%% not a path"]) == L.empty_ledger()


def test_ledger_for_prompt_of_the_view_carries_no_withheld_string():
    paths = ["threads[2].note#sentence=2", "asks[0]"]
    prompt = json.dumps(L.ledger_for_prompt(L.public_view(_ledger(), _is_private, paths), 6))
    for withheld in ("Second line goes", "A private one", "ask one", "Beta arc"):
        assert withheld not in prompt
    assert "A public one" in prompt and "ask two" in prompt


def test_a_ledger_with_neither_field_is_returned_as_the_same_object():
    clean = {k: v for k, v in _ledger().items() if k != "arc_refs"}
    for t in clean["threads"] + clean["bets"]:
        t.pop("call_refs", None)
    assert L.public_view(clean, _is_private) is clean
    assert L.public_view(clean, _is_private, []) is clean


class _Table:
    def __init__(self, items):
        self.items, self.queries = items, 0

    def query(self, **kw):
        self.queries += 1
        return {"Items": self.items}

    def get_item(self, Key):
        return {"Item": next((i for i in self.items if i["sk"] == Key["sk"]), None)}


def _row(ledger, **extra):
    return {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": "LEDGER#2026-12-01",
        "cycle": "17",
        "phase": "experiment",
        "ledger_json": json.dumps(ledger),
        **extra,
    }


def test_latest_visible_returns_the_view_and_a_clean_row_byte_identically(monkeypatch):
    monkeypatch.setattr("experiment.phase_filter.singleton_visible", lambda it: True)
    clean = {"week": 4, "threads": [{"id": "a", "status": "open", "note": "Plain."}], "asks": [{"ask": "Walk daily.", "status": "open"}]}
    t = _Table([_row(clean)])
    got = L.latest_visible(t, "USER#matthew#SOURCE#chronicle", "2026-12-08", cycle="17")
    assert json.dumps(got) == json.dumps(clean) and t.queries == 1, "a clean row: same bytes, no extra read"
    annotated = _Table([_row(clean, withheld_paths=["asks[0]"])])
    assert L.latest_visible(annotated, "USER#matthew#SOURCE#chronicle", "2026-12-08", cycle="17")["asks"] == []
    assert json.loads(annotated.items[0]["ledger_json"]) == clean, "the stored ledger_json is never rewritten"


def test_latest_visible_classifies_refs_through_the_policy_and_fails_closed(monkeypatch):
    monkeypatch.setattr("experiment.phase_filter.singleton_visible", lambda it: True)
    t = _Table([_row(_ledger())])
    monkeypatch.setattr(P, "load", lambda table: P.CallSet(classes={("COACH#alpha_coach", "pred_20261201_synthetic_public"): "public"}))
    got = L.latest_visible(t, "USER#matthew#SOURCE#chronicle", "2026-12-08", cycle="17")
    assert [x["id"] for x in got["threads"]] == ["t-pub", "t-old"]
    monkeypatch.setattr(P, "load", lambda table: (_ for _ in ()).throw(RuntimeError("down")))
    got = L.latest_visible(t, "USER#matthew#SOURCE#chronicle", "2026-12-08", cycle="17")
    assert [x["id"] for x in got["threads"]] == ["t-old"], "unreadable calls: every ref is private"


def test_the_panels_season_ledger_door_returns_the_same_view(monkeypatch):
    from emails import panelcast_desk

    monkeypatch.setattr(panelcast_desk, "visible", lambda it: it or {})
    t = _Table([_row(_ledger(), sk="LEDGER#2026-12-01", withheld_paths=["asks[1]"])])
    t.items[0]["sk"] = "LEDGER#2026-12-01"
    monkeypatch.setattr(P, "load", lambda table: P.CallSet(classes={}))
    got = panelcast_desk.season_ledger({"date": "2026-12-01"}, _g={"USER_ID": "matthew", "table": t, "logger": None})
    assert got["bets"] == [] and [a["ask"] for a in got["asks"]] == ["ask one"]


def test_apply_budget_records_lineage_forward():
    budget = {
        "thread_actions": [{"thread_id": "n1", "action": "open", "title": "N", "note": "x", "call_refs": [PUB]}],
        "arc_updates": [
            {"who": "alpha_coach", "line": "moved", "call_refs": [{"pk": "COACH#alpha_coach", "id": "pred_20261201_synthetic_public"}]}
        ],
        "bet": {"claim": "c", "metric": "m", "rule": "r", "call_refs": [PUB]},
        "coach_asks": [{"ask": "do a thing", "call_refs": [PUB]}],
    }
    led = L.apply_budget(L.empty_ledger(), budget, week=1, date="2026-12-01", title="T")
    assert led["threads"][0]["call_refs"] == [PUB] and led["arc_refs"]["alpha_coach"] == [PUB]
    assert led["bets"][0]["call_refs"] == [PUB] and led["asks"][0]["call_refs"] == [PUB]
    again = L.apply_budget(led, {"arc_updates": [{"who": "alpha_coach", "line": "no refs now"}]}, week=2, date="2026-12-08", title="U")
    assert "alpha_coach" not in again.get("arc_refs", {}), "an arc rewritten without refs drops the old lineage"


def test_a_plain_budget_writes_no_lineage_fields():
    led = L.apply_budget(
        L.empty_ledger(), {"thread_actions": [{"thread_id": "a", "action": "open", "note": "n"}]}, week=1, date="2026-12-01", title="T"
    )
    assert "call_refs" not in led["threads"][0] and "arc_refs" not in led


def test_the_live_invariant_ties_the_annotation_to_the_detector(monkeypatch):
    """A visible row whose view still carries a private call's words is named; annotating the sentence clears it."""
    monkeypatch.setattr("experiment.phase_filter.singleton_visible", lambda it: True)
    words = "The subject will log nine quiet hours across the stated testing fortnight without a break."
    call = {
        "sk": "PREDICTION#pred_20261201_synthetic_q",
        "prediction_id": "pred_20261201_synthetic_q",
        "created_at": "2026-12-01T00:00:00Z",
        "claim_natural": words,
    }
    calls = P.build([("COACH#alpha_coach", call)], {})
    led = {"week": 3, "threads": [{"id": "t", "status": "open", "note": f"Kept sentence. {words} Also kept."}]}
    row = _row(led)
    assert list(P.ledger_findings([row], calls, "17")) == ["LEDGER#2026-12-01"]
    assert P.ledger_findings([_row(led, withheld_paths=["threads[0].note#sentence=2"])], calls, "17") == {}
    assert P.ledger_findings([{**row, "cycle": "16"}], calls, "17") == {}, "a row another cycle owns is no one's memory"
