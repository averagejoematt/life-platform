"""tests/test_dossier_prereg_policy_6199.py — #6199 G3: the sealed pre-registration list passes the publication policy.

A sealed entry reaches the dossier only when it matches a live call row the policy publishes; a private or unmatched
entry is withheld (fail closed). The count the writer sees is the sealed file's HISTORICAL total, and the withheld
entries are counted separately, only when there are any. Synthetic sealed document and synthetic call rows.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from content import story_dossier as D  # noqa: E402

WK = {"week": 1, "start": D.GENESIS, "end": "2099-01-01"}
CLAIMS = ("Synthetic walking counts will rise across the window.", "Synthetic scale line will fall.", "Synthetic quiet-hours call.")


def _row(i, public):
    return {
        "sk": f"PREDICTION#pred_synthetic_{i}",
        "prediction_id": f"pred_synthetic_{i}",
        "cycle": "17",
        "created_date": D.GENESIS,
        "status": "pending",
        "claim_natural": CLAIMS[i],
        "_test_public": public,
    }


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **kw):
        pk = kw["KeyConditionExpression"]._values[0]._values[1]
        return {"Items": self.rows if pk == "COACH#alpha_coach" else []}


def _run(monkeypatch, publics):
    monkeypatch.setattr(D, "_operational", lambda: ("alpha_coach",))
    monkeypatch.setattr(D.prediction_publication, "row_is_public", lambda pk, it: bool(it.get("_test_public")))
    sealed = {
        "coaches": {"alpha_coach": {"coach_name": "Avery Quill", "predictions": [{"claim_natural": c, "window_days": 14} for c in CLAIMS]}}
    }
    monkeypatch.setattr(D, "load_prereg", lambda: sealed)
    return D._predictions(_Table([_row(i, p) for i, p in enumerate(publics)]), WK, {"alpha_coach": "Avery Quill"})


def test_a_private_sealed_entry_is_withheld_and_the_historical_total_kept(monkeypatch):
    out = _run(monkeypatch, (True, True, False))
    assert [p["claim"] for p in out["pre_registered"]] == list(CLAIMS[:2])
    assert out["pre_registered_count"] == 3 and out["pre_registered_withdrawn_count"] == 1
    assert CLAIMS[2] not in json.dumps(out)


def test_an_unmatched_sealed_entry_is_withheld_fail_closed(monkeypatch):
    out = _run(monkeypatch, (True, True))  # no live row for the third
    assert len(out["pre_registered"]) == 2 and out["pre_registered_withdrawn_count"] == 1


def test_an_all_public_sealed_list_carries_no_withdrawn_field(monkeypatch):
    out = _run(monkeypatch, (True, True, True))
    assert out["pre_registered_count"] == len(out["pre_registered"]) == 3
    assert "pre_registered_withdrawn_count" not in out, "a clean week's dossier gains no field"


def test_the_grading_caveat_example_is_neutral():
    import inspect

    src = inspect.getsource(D._predictions)
    assert "a count claim (a number of days past a line)" in src
