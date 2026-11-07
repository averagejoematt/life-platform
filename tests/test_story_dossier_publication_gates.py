"""The public chronicle reads the same publication decision the public API does (owner rulings 2026-11-03/06).

A regenerated draft still spoke of the journal because the Story Desk's dossier read coach text and call claims straight
from the table. Vary only the private rows: the dossier is byte-identical. Controls: a publishable text and a public call
do reach it, and lifting a gate lets the private row through. All values are synthetic.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from common import (
    narrative_provenance as NP,  # noqa: E402
    prediction_publication as PP,  # noqa: E402
)
from content import autopublish_audit, story_dossier as SD  # noqa: E402

WK = {"start": "2026-10-05", "end": "2026-10-11"}
ROSTER = {"mind_coach": "Synthetic Coach"}


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **kw):
        return {"Items": list(self.rows)}


def _output(text, families):
    return {
        "pk": "COACH#mind_coach",
        "sk": "OUTPUT#2026-10-08#x",
        "public_summary": text,
        "key_recommendation": text,
        "themes": [text],
        NP.PROVENANCE_KEY: NP.stamp(families, producer="test"),
    }


def _call(pid, claim):
    return {"pk": "COACH#mind_coach", "sk": f"PREDICTION#{pid}", "prediction_id": pid, "cycle": "17", "created_date": "2026-10-06",
            "claim_natural": claim, "status": "refuted", "outcome_date": "2026-10-08"}  # fmt: skip


def _setup(monkeypatch):
    monkeypatch.setattr(SD, "_operational", lambda: ("mind_coach",))


def test_private_coach_text_never_reaches_the_dossier(monkeypatch):
    _setup(monkeypatch)
    private = _output("synthetic private read", ["whoop", "journal_presence"])
    unstamped = {k: v for k, v in private.items() if k != NP.PROVENANCE_KEY}
    assert SD._coaches(_Table([private]), WK, ROSTER) == SD._coaches(_Table([unstamped]), WK, ROSTER) == []
    assert json.dumps(SD._coaches(_Table([private]), WK, ROSTER)) == json.dumps(SD._coaches(_Table([]), WK, ROSTER))


def test_control_publishable_coach_text_is_served(monkeypatch):
    _setup(monkeypatch)
    out = SD._coaches(_Table([_output("synthetic public read", ["whoop"])]), WK, ROSTER)
    assert out and out[0]["latest_public_summary"] == "synthetic public read"


def test_mutation_control_an_open_gate_would_leak(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(NP, "is_publishable", lambda r: True)
    assert SD._coaches(_Table([_output("synthetic private read", ["journal_presence"])]), WK, ROSTER)


def _predictions(rows, monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(SD, "load_prereg", lambda: {})
    return SD._predictions(_Table(rows), WK, ROSTER)


def test_private_calls_reach_neither_claims_nor_records(monkeypatch):
    public = _call("pub", "synthetic public call")
    monkeypatch.setattr(PP, "row_is_public", lambda pk, row, lookup=None: row["prediction_id"] == "pub")
    with_private = _predictions([public, _call("priv", "synthetic private call")], monkeypatch)
    assert json.dumps(with_private, sort_keys=True) == json.dumps(_predictions([public], monkeypatch), sort_keys=True)
    assert with_private["graded_this_week_count"] == 1
    monkeypatch.setattr(PP, "row_is_public", lambda pk, row, lookup=None: True)  # mutation control
    assert _predictions([public, _call("priv", "synthetic private call")], monkeypatch)["graded_this_week_count"] == 2


def test_a_draft_naming_private_activity_never_publishes_itself():
    clean = {"date": "2026-10-13", "title": "T", "content_markdown": "He walked five miles on Tuesday."}
    named = dict(clean, content_markdown="The journal stayed quiet all week.")
    reason = "names private activity"
    assert not any(reason in b for b in autopublish_audit.blocking_items(clean))
    assert any(reason in b for b in autopublish_audit.blocking_items(named))


def test_the_snapshot_contract_and_the_site_schema_agree_on_claim_withheld():
    """#5667 added `no_words` to the site schema only: fixtures never hit it, and the live root build refused the snapshot."""
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    contract = open(os.path.join(root, "scripts", "publish_snapshot_contract.py"), encoding="utf-8").read()
    schema = open(os.path.join(root, "www", "src", "content.config.ts"), encoding="utf-8").read()
    served = set(re.search(r'"claim_withheld": \("enum:([^"]+)"', contract).group(1).split("|"))
    assert served == set(re.findall(r'"(\w+)"', re.search(r"claim_withheld: z\.enum\(\[([^\]]+)\]", schema).group(1)))
    assert "no_words" in served
