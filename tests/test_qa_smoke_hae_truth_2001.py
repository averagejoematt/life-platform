"""tests/test_qa_smoke_hae_truth_2001.py — #2001 qa-smoke days-dark truth guard.

The D-4/#468 honesty surface exists to say "dark N days", but the liveness scan
lost the number exactly when the lapse was longest (BP ~114d / SoM ~122d rendered
`days_dark: null`). check_hae_liveness_truth() asserts the repaired contract at
runtime: any dark:true datatype whose partition holds ANY findable historical
record for its fields must carry a numeric age — an unnumbered dark is only
honest when the deep horizon truly holds nothing.
"""

import os
import sys

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402


class _FakeTable:
    """get_item serves the DATATYPE_LIVENESS sentinel; query (the probe) serves
    `probe_pages` in order (a filtered page can be empty WITH a LastEvaluatedKey)."""

    def __init__(self, sentinel, probe_pages=None):
        self.sentinel = sentinel
        self.probe_pages = list(probe_pages or [{"Items": []}])
        self.probe_calls = 0

    def get_item(self, **kwargs):
        return {"Item": self.sentinel} if self.sentinel is not None else {}

    def query(self, **kwargs):
        assert "FilterExpression" in kwargs and "BETWEEN" in kwargs["KeyConditionExpression"]
        self.probe_calls += 1
        idx = min(self.probe_calls - 1, len(self.probe_pages) - 1)
        return self.probe_pages[idx]


def _sentinel(datatypes):
    return {"pk": "USER#matthew#SOURCE#apple_health", "sk": "DATATYPE_LIVENESS", "datatypes": datatypes}


def _run(monkeypatch, sentinel, probe_pages=None):
    fake = _FakeTable(sentinel, probe_pages)
    monkeypatch.setattr(qa, "table", fake)
    checks = qa.check_hae_liveness_truth()
    assert len(checks) == 1
    return checks[0], fake


def test_unnumbered_dark_with_findable_record_fails(monkeypatch):
    # The exact live defect: BP dark with age None while a real record exists.
    sent = _sentinel([{"key": "blood_pressure", "label": "Blood pressure", "dark": True, "age_days": None}])
    c, _ = _run(monkeypatch, sent, probe_pages=[{"Items": [{"sk": "DATE#2026-04-10", "blood_pressure_systolic": 118}]}])
    assert c.passed is False
    assert "blood_pressure" in c.message


def test_numbered_dark_passes_without_probing(monkeypatch):
    sent = _sentinel([{"key": "blood_pressure", "label": "Blood pressure", "dark": True, "age_days": 114}])
    c, fake = _run(monkeypatch, sent)
    assert c.passed is True
    assert fake.probe_calls == 0  # a numbered dark needs no partition probe


def test_unnumbered_dark_with_truly_empty_horizon_passes(monkeypatch):
    # Honest absence: nothing findable in the deep horizon → unnumbered dark is right.
    sent = _sentinel([{"key": "state_of_mind", "label": "State of Mind", "dark": True, "age_days": None}])
    c, _ = _run(monkeypatch, sent, probe_pages=[{"Items": []}])
    assert c.passed is True


def test_probe_follows_empty_filtered_page_with_lek(monkeypatch):
    # A filtered page can be empty yet carry a LastEvaluatedKey — the probe must
    # keep paging rather than concluding absence (the same trap as the checker's).
    sent = _sentinel([{"key": "blood_pressure", "label": "Blood pressure", "dark": True, "age_days": None}])
    pages = [
        {"Items": [], "LastEvaluatedKey": {"pk": "x", "sk": "DATE#2026-05-01"}},
        {"Items": [{"sk": "DATE#2026-04-10", "blood_pressure_diastolic": 76}]},
    ]
    c, fake = _run(monkeypatch, sent, probe_pages=pages)
    assert c.passed is False
    assert fake.probe_calls == 2


def test_missing_sentinel_warns_never_fails(monkeypatch):
    c, _ = _run(monkeypatch, None)
    assert c.passed is None  # warn — checker hasn't run; not evidence of a defect
