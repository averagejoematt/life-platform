"""A character pillar computed only from private sources is never published (owner rulings 2026-11-03/04).

Relationships reads only the journal and its enrichment pass, so its value exists only on days he wrote: the
published 62 and 36 on the two journal days of this cycle named those days. And a progression receipt named
the journal's own rows (a journal sort key is its date, template and entry id). Every public reader of the
character sheet now reads it through ``character_privacy.public_sheet``, and the receipt route through
``_public_receipt``. These tests vary ONLY the private inputs and assert byte-identical public output, with
mutation controls proving each test can fail.
"""

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from common import activity_publication  # noqa: E402
from health import character_privacy  # noqa: E402
from web import (
    site_api_character as C,  # noqa: E402
    site_api_vitals as vitals,  # noqa: E402
)

_GENESIS = "2026-09-06"
_PUBLIC_PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "consistency"]


def _pillar(raw, cov=1.0, ni=False, xp=0.0):
    return {
        "raw_score": raw,
        "level_score": raw,
        "level": 1.0,
        "tier": "Foundation",
        "xp_delta": xp,
        "xp_earned": xp,
        "xp_total": xp,
        "data_coverage": cov,
        "coverage_hold": ni,
        "not_instrumented": ni,
        "not_instrumented_note": None,
        "absent_behaviors": [],
        "drivers": {"top": ["social_quality"] if not ni else [], "dragging": [], "absent": [], "no_data": []},
    }


def _sheet(day, rel):
    rec = {"pk": "USER#matthew#SOURCE#character_sheet", "sk": f"DATE#{day}", "date": day, "character_level": 3, "character_xp": 40}
    for p in _PUBLIC_PILLARS:
        rec[f"pillar_{p}"] = _pillar(60.0)
    rec["pillar_relationships"] = rel
    return rec


# A journal day (relationships instrumented from the entry) and a quiet day (never instrumented).
JOURNAL_DAY = _pillar(61.5, xp=1.93)
QUIET_DAY = _pillar(50.0, cov=0.0, ni=True)


class _Table:
    def __init__(self, items):
        self.items = items

    def query(self, **kw):
        return {"Items": copy.deepcopy(self.items)}

    def get_item(self, **kw):
        return {"Item": copy.deepcopy(self.items[0])} if self.items else {}


def _served(rel, monkeypatch, date="2026-09-09"):
    monkeypatch.setattr(vitals, "table", _Table([_sheet("2026-09-09", rel), _sheet("2026-09-08", QUIET_DAY)]))
    monkeypatch.setattr(vitals, "EXPERIMENT_START", _GENESIS)
    body = json.loads(vitals.handle_character(date)["body"])
    body.pop("_meta", None)
    return json.dumps(body, sort_keys=True)


@pytest.mark.parametrize("date", [None, "2026-09-09"])
def test_character_is_byte_identical_on_a_journal_day_and_a_quiet_day(monkeypatch, date):
    monkeypatch.setattr(C, "_attach_pillar_absence", lambda *a, **k: None)
    assert _served(JOURNAL_DAY, monkeypatch, date) == _served(QUIET_DAY, monkeypatch, date)
    body = json.loads(_served(JOURNAL_DAY, monkeypatch, date))
    rel = next(p for p in body["pillars"] if p["name"] == "relationships")
    assert rel["not_instrumented"] is True and rel["not_instrumented_note"] == character_privacy.PRIVATE_PILLAR_NOTE
    assert body["character"]["composite_pillar_count"] == 6


def test_mutation_control_a_published_relationships_pillar_would_move(monkeypatch):
    monkeypatch.setattr(C, "_attach_pillar_absence", lambda *a, **k: None)
    monkeypatch.setattr(activity_publication, "source_is_public", lambda s: True)
    assert _served(JOURNAL_DAY, monkeypatch) != _served(QUIET_DAY, monkeypatch)


def test_public_sheet_is_pure_and_holds_only_private_pillars():
    rec = _sheet("2026-09-09", JOURNAL_DAY)
    before = copy.deepcopy(rec)
    out = character_privacy.public_sheet(rec)
    assert rec == before, "the stored record is never changed"
    assert out["pillar_relationships"] == character_privacy.public_sheet(_sheet("2026-09-08", QUIET_DAY))["pillar_relationships"]
    for p in _PUBLIC_PILLARS:
        assert out[f"pillar_{p}"] == rec[f"pillar_{p}"]
    assert character_privacy.pillar_is_publishable("mind") and not character_privacy.pillar_is_publishable("relationships")


def _receipt(journal: bool):
    rows = [
        {"pk": "USER#matthew#SOURCE#whoop", "sks": ["DATE#2026-09-09"]},
        {"pk": "USER#matthew#SOURCE#character_sheet", "sks": ["DATE#2026-09-08"]},
        {"pk": "USER#matthew#SOURCE#engagement_state", "sks": ["DATE#2026-09-09"]},
    ]
    if journal:
        rows += [
            {"pk": "USER#matthew#SOURCE#notion", "sks": ["DATE#2026-09-09#journal#evening#synthetic"]},
            {"pk": "USER#matthew#SOURCE#flourishing", "sks": ["DATE#2026-09-09"]},
        ]
    rel = {"inputs": {"raw_score": 35.5 if journal else 50.0, "data_coverage": 1.0 if journal else 0.0}, "outputs": {"level": 1.0}}
    return {
        "date": "2026-09-09",
        "digest": "d",
        "input_rows": rows,
        "transitions": {
            "day_number": 4,
            "headline": {},
            "pillars": {"sleep": {"inputs": {"raw_score": 60.0}, "outputs": {}}, "relationships": rel},
        },
    }


def test_the_receipt_omits_private_rows_and_the_private_pillar():
    a = C._public_receipt(_receipt(journal=True))
    b = C._public_receipt(_receipt(journal=False))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    s = json.dumps(a)
    assert "notion" not in s and "flourishing" not in s and "engagement_state" not in s and "relationships" not in s
    assert {r["pk"].split("#SOURCE#")[-1] for r in a["input_rows"]} == {"whoop", "character_sheet"}


def test_mutation_control_an_unfiltered_receipt_would_move(monkeypatch):
    monkeypatch.setattr(activity_publication, "source_is_public", lambda s: True)
    assert json.dumps(C._public_receipt(_receipt(True)), sort_keys=True) != json.dumps(C._public_receipt(_receipt(False)), sort_keys=True)


def test_every_public_reader_of_the_sheet_goes_through_public_sheet():
    """Guard the SET: every web/ module that reads a character_sheet pillar for a public answer imports the mask.
    A new reader that forgets it fails here (site_api_mind reads only pillar_mind, which is publishable)."""
    import glob
    import re

    readers = []
    for path in sorted(
        glob.glob(os.path.join(ROOT, "lambdas", "web", "*.py")) + [os.path.join(ROOT, "lambdas", "emails", "chronicle_data.py")]
    ):
        src = open(path, encoding="utf-8").read()
        if "character_sheet" in src and re.search(r"pillar_(\{|relationships)|f\"pillar_\{", src):
            readers.append((os.path.basename(path), "public_sheet" in src or "public_pillar" in src))
    missing = [name for name, ok in readers if not ok]
    assert readers, "the walk found no readers — the pattern is broken"
    assert not missing, f"these modules read character_sheet pillars without character_privacy.public_sheet: {missing}"
