"""tests/test_qa_smoke_inverse_census_wireup_3915.py — #3915 box 4: the phase-stamp
coverage check must render `pk_census.format_inverse_census(audit)` into its own
detail EVERY night, regardless of which of the check's three branches fires (the
inverse defect, the unstamped-rows finding, or the all-clear).

Box 4's own words: "The phase-stamp coverage guard enumerates the four families
explicitly rather than leaving them invisible to the check." The `wrongly_stamped`
leg only ever sees the COACH#/ENSEMBLE# subset (`inverse_pks`); calibration,
recall_embeddings and milestones are never in it and never reach `unstamped` either
(they are CROSS_PHASE, not EXPERIMENT_SCOPED) — so without this wire-up those three
families are structurally invisible to every branch of this check's message, on
every run, forever. `format_inverse_census` is the one thing that reads the FULL
`inverse_census` dict, not the narrowed leg.

The fake audits below bypass the live scan entirely (monkeypatching
`experiment.pk_census.scoped_stamp_audit`, the function the check imports by name at
call time) so the wire-up is proven independent of DynamoDB and independent of
`phase_taxonomy.classify()`'s live behaviour — this is a rendering test, not a
classification test (that is `tests/test_cross_phase_provenance_rulings_3915.py`).
"""

import os
import sys

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402
from experiment import pk_census  # noqa: E402


class _FakeTable:
    """Never actually scanned: `scan_provenance_pages` is a generator, and the fake
    `scoped_stamp_audit` below never iterates the pages argument it's handed."""

    def scan(self, **kwargs):
        raise AssertionError("the fake audit must short-circuit before any real scan")


def _base_audit(**overrides):
    audit = {
        "rows": 500,
        "families_audited": {"SOURCE#insights"},
        "unstamped": {},
        "deferred": {},
        "wrongly_stamped": [],
        "by_design": 0,
        "unclassified": 0,
        "inverse_census": {},
        "remediable": {},
        "unruled_provenance": {},
    }
    audit.update(overrides)
    return audit


def _patch_audit(monkeypatch, audit):
    monkeypatch.setattr(qa, "table", _FakeTable())
    monkeypatch.setattr(pk_census, "scoped_stamp_audit", lambda pages, inverse_pks=(): audit)


def test_the_ok_branch_names_every_census_family(monkeypatch):
    """The all-clear path: no wrongly_stamped, no unstamped — the census must still
    surface calibration and COACH, which no other branch of this message would ever
    have named."""
    audit = _base_audit(
        inverse_census={
            "SOURCE#calibration": {"rows": 2211, "attrs": ["cycle"], "verdict": pk_census.RULED_LABEL, "pks": []},
            "COACH": {"rows": 64, "attrs": ["cycle"], "verdict": pk_census.RULED_IN_SCOPE, "pks": []},
        }
    )
    _patch_audit(monkeypatch, audit)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is True
    assert "#3915" in c.message
    assert "SOURCE#calibration 2211" in c.message
    assert "COACH 64" in c.message
    assert pk_census.RULED_LABEL in c.message
    assert pk_census.RULED_IN_SCOPE in c.message
    assert "2275 cross-phase row(s) carry provenance" in c.message  # 2211 + 64


def test_the_unstamped_branch_still_carries_the_census(monkeypatch):
    """The unstamped-rows finding must not crowd out the inverse census — both are
    real findings on the same nightly run and neither may silence the other."""
    audit = _base_audit(
        unstamped={"USER#matthew#SOURCE#insights": ["USER#matthew#SOURCE#insights/INSIGHT#x"]},
        inverse_census={
            "SOURCE#milestones": {"rows": 27, "attrs": ["cycle"], "verdict": pk_census.RULED_LABEL, "pks": []},
        },
    )
    _patch_audit(monkeypatch, audit)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None
    assert "SOURCE#milestones 27" in c.message
    assert pk_census.RULED_LABEL in c.message


def test_the_wrongly_stamped_branch_still_carries_the_census(monkeypatch):
    """The alarmed inverse leg (COACH#/ENSEMBLE# only) fires first; the full
    table-wide census must still ride along, naming families the alarmed leg
    itself never reaches."""
    audit = _base_audit(
        wrongly_stamped=["COACH#eli_marsh/CHAT#2026-09-18#deadbeef[cycle]"],
        inverse_census={
            "COACH": {"rows": 64, "attrs": ["cycle"], "verdict": pk_census.RULED_IN_SCOPE, "pks": []},
            "SOURCE#recall_embeddings": {"rows": 883, "attrs": ["cycle"], "verdict": pk_census.RULED_LABEL, "pks": []},
        },
    )
    _patch_audit(monkeypatch, audit)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None
    assert "COACH 64" in c.message
    assert "SOURCE#recall_embeddings 883" in c.message


def test_a_zero_family_census_renders_the_none_wording_not_an_empty_string(monkeypatch):
    """MUTATION CONTROL: an audit with zero cross-phase-provenance families must still
    contribute a non-empty, explicit sentence — the census is a verdict every night
    ("zero families carry it"), not a silent no-op that vanishes into the rest of the
    message. A caller (or a formatter) that only appends this string when truthy would
    pass every test above and still make the sentence disappear on an all-clear night."""
    audit = _base_audit()  # inverse_census == {}
    _patch_audit(monkeypatch, audit)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is True
    note = pk_census.format_inverse_census(audit)
    assert note != "" and note.strip() != ""
    assert "0 cross-phase row(s)" in note
    assert note in c.message


def test_format_inverse_census_itself_never_returns_empty():
    """The formatter's own contract, isolated from the check: box 4 says the families
    are enumerated by the check, never invisible to it — a formatter that renders ""
    for the clean case makes that literally false on the nights it matters most."""
    assert pk_census.format_inverse_census({"inverse_census": {}}) != ""
    assert pk_census.format_inverse_census({}) != ""
