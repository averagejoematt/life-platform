"""Shared loader for the #4185 reader-check fixtures (tests/grounding_corpus/reader_checks/).

Not a test module — the eight ``test_reader_check_<class>_4185.py`` files import it so
each check class is proven against the SAME frozen live specimens and positive controls.

A fixture is ``{id, kind, surface, coach_id, date, slot, text, served_facts,
expected_findings, expected_claims}``. The allow-list for the number classes is built
from ``served_facts`` by the real ``grounded_generation.allowed_numbers`` — the same
function the generation path uses — so a fixture can never carry a hand-picked list.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "lambdas"))

from ai import grounded_generation  # noqa: E402
from coach import reader_checks  # noqa: E402

CORPUS_DIR = os.path.join(_HERE, "grounding_corpus", "reader_checks")
STAMP_NAME = "corpus.sha256.json"


def load_fixtures():
    out = []
    for name in sorted(os.listdir(CORPUS_DIR)):
        if name.endswith(".json") and name != STAMP_NAME:
            with open(os.path.join(CORPUS_DIR, name)) as fh:
                fx = json.load(fh)
            fx["_file"] = name
            out.append(fx)
    return out


FIXTURES = load_fixtures()


def fired(fx, checks=None):
    """The findings the checks return on a fixture, with its frozen facts + allow-list.

    ``checks=None`` is the PRODUCTION selection (``reader_findings``' own default): the
    narrative classes always, the reader-slot classes only when the fixture names a slot,
    ``ask_cardinality`` only for ``public_ask``. A fixture's ``expected_findings`` is the
    exact set of classes it fails under that selection.
    """
    facts = fx.get("served_facts") or {}
    allowed = grounded_generation.allowed_numbers(facts)
    return reader_checks.reader_findings(fx["text"], facts=facts, allowed=allowed, slot=fx.get("slot"), checks=checks)


def fired_classes(fx, checks=None):
    return {f["check"] for f in fired(fx, checks)}


def specimens_for(check):
    return [fx for fx in FIXTURES if fx["kind"] == "specimen" and check in fx["expected_findings"]]


def controls_clear_of(check):
    """Every fixture (control or specimen) that must NOT trip ``check``."""
    return [fx for fx in FIXTURES if check not in fx["expected_findings"]]


def caught(fx, check):
    """True iff ``check`` fires on ``fx`` AND every expected claim for it is among the findings."""
    hits = [f for f in fired(fx) if f["check"] == check]
    if not hits:
        return False
    want = (fx.get("expected_claims") or {}).get(check) or []
    got = {f.get("claimed") for f in hits}
    return all(float(w) in got for w in want)


def assert_class_contract(check, monkeypatch):
    """The per-class contract every test file runs: specimens fail, clean fixtures pass,
    and the MUTATION CONTROL — the class replaced by a no-op — lets every specimen through."""
    specs = specimens_for(check)
    assert specs, f"no live specimen exercises {check} — the class is unproven"
    for fx in specs:
        assert caught(fx, check), f"{fx['_file']}: {check} no longer fails the specimen (got {sorted(fired_classes(fx))})"
    for fx in controls_clear_of(check):
        hits = [f for f in fired(fx) if f["check"] == check]
        assert hits == [], f"{fx['_file']}: {check} over-fires on a fixture that must pass it: {hits}"
    monkeypatch.setitem(reader_checks._CHECKS, check, (lambda *a, **k: [], reader_checks._CHECKS[check][1]))
    for fx in specs:
        assert not caught(fx, check), f"mutation control is vacuous: with {check} dropped, {fx['_file']} still fails it"
