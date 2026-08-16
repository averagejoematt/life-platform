"""#2705, the read half — the query distinguishes no-match from coverage-gap.

The 2026-08-11 installment sat published-but-unindexed for three days; a reader
asking about that week got the model's honest-sounding "the archive doesn't
cover it" — silence indistinguishable from absence. `retrieve_block` now knows
the difference: it reuses the nightly checker's own published-installment
derivation, and an incomplete index says so IN the prompt block. With no gaps
the block is byte-identical to before (including the empty-retrieval ""
contract) — the note is exceptional-state-only.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import ask_retrieval as ar  # noqa: E402


class _T:
    """Chronicle-partition double: the wire shape published_installment_dates reads."""

    def __init__(self, items):
        self._items = items

    def query(self, **kw):
        return {"Items": self._items}


PUBLISHED = [
    {"pk": "USER#matthew#SOURCE#chronicle", "sk": "DATE#2026-08-02", "status": "published"},
    {"pk": "USER#matthew#SOURCE#chronicle", "sk": "DATE#2026-08-11", "status": "published"},
    {"pk": "USER#matthew#SOURCE#chronicle", "sk": "DATE#2026-08-19", "status": "draft"},  # drafts never count
]

CORPUS_FULL = [{"sk": "DOC#chronicle#2026-08-02"}, {"sk": "DOC#chronicle#2026-08-11"}]
CORPUS_GAPPED = [{"sk": "DOC#chronicle#2026-08-02"}]


def test_a_missing_published_installment_is_a_named_gap():
    assert ar.coverage_gaps(_T(PUBLISHED), CORPUS_GAPPED) == ["2026-08-11"]


def test_a_complete_index_has_no_gaps_and_adds_nothing():
    assert ar.coverage_gaps(_T(PUBLISHED), CORPUS_FULL) == []
    assert ar.coverage_note([]) == ""


def test_drafts_never_count_as_gaps():
    corpus = list(CORPUS_FULL)
    assert "2026-08-19" not in ar.coverage_gaps(_T(PUBLISHED), corpus)


def test_the_note_names_the_dates_and_forbids_the_absence_phrasing():
    note = ar.coverage_note(["2026-08-11"])
    assert "2026-08-11" in note and "INCOMPLETE" in note
    assert "never say the archive doesn't cover them" in note


def test_gap_read_failure_is_fail_soft():
    class _Boom:
        def query(self, **kw):
            raise RuntimeError("ddb down")

    assert ar.coverage_gaps(_Boom(), CORPUS_GAPPED) == []
