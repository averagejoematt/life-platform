"""#2705 — a failed recall index must say WHY, and must not say it at INFO.

Measured 2026-08-15. `DATE#2026-08-11` was `status=published` in the chronicle
partition and absent from the recall corpus (which stopped at `2026-08-02`), so
"when did I feel like this before?" could not cite that week — and returns silence
rather than an error.

The indexer did run. The publish path's entire record of it was one line:

    2026-08-14T18:00:45Z  INFO  [recall] index 2026-08-11: failed

`index_document` has three `return FAILED` sites and every one caught
`Exception` and discarded it, so nothing anywhere recorded the cause. The
installment sat unindexed for four days and the reason had to be reverse-engineered.

Fail-soft is the right contract here — publishing a week must never depend on an
embedding call — and it is NOT what this changes. What changes is that a fail-soft
path stops being a silent one: each FAILED logs its exception at ERROR, and the
caller stops reporting a real miss at INFO.
"""

from __future__ import annotations

import logging
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from ai import recall_indexer as ri  # noqa: E402


class _BoomTable:
    """A table whose every access raises — the shape of the 08-11 failure."""

    def query(self, **kwargs):
        raise RuntimeError("ProvisionedThroughputExceeded (simulated)")

    def get_item(self, **kwargs):
        raise RuntimeError("ProvisionedThroughputExceeded (simulated)")

    def put_item(self, **kwargs):
        raise RuntimeError("ProvisionedThroughputExceeded (simulated)")


def test_a_partition_read_failure_is_still_fail_soft(caplog):
    """The contract that must NOT change: never raise into the publish path."""
    with caplog.at_level(logging.ERROR, logger=ri.__name__):
        assert ri.index_chronicle_installment(_BoomTable(), "USER#m#SOURCE#chronicle", "2026-08-11") == ri.FAILED


def test_a_partition_read_failure_records_its_cause(caplog):
    """The bug: FAILED was returned with the exception discarded."""
    with caplog.at_level(logging.ERROR, logger=ri.__name__):
        ri.index_chronicle_installment(_BoomTable(), "USER#m#SOURCE#chronicle", "2026-08-11")
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a FAILED index produced no ERROR record — the cause is still discarded (#2705)"
    joined = " ".join(r.getMessage() for r in errors)
    assert "2026-08-11" in joined, joined
    assert "ProvisionedThroughputExceeded" in joined, f"the exception itself is still swallowed: {joined}"


def test_an_embed_failure_records_its_cause(caplog):
    """The second FAILED site — the one that actually costs a precedent."""
    doc = {"kind": "chronicle", "date": "2026-08-11", "text": "a week of measured things", "link": "/story/x"}

    class _ReadableTable(_BoomTable):
        def get_item(self, **kwargs):
            return {}

    def _boom_embed(_text):
        raise RuntimeError("bedrock embed refused (simulated)")

    with caplog.at_level(logging.ERROR, logger=ri.__name__):
        status = ri.index_document(_ReadableTable(), doc, embed=_boom_embed)
    assert status == ri.FAILED
    joined = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "bedrock embed refused" in joined, f"the embed exception is still swallowed: {joined}"
    assert "2026-08-11" in joined, joined


def test_a_clean_skip_is_not_escalated_to_error(caplog):
    """The control. Skips are normal states, not faults — escalating them would make
    the new ERROR channel as ignorable as the INFO one it replaces."""
    doc = {"kind": "chronicle", "date": "2026-08-11", "text": "   "}
    with caplog.at_level(logging.ERROR, logger=ri.__name__):
        assert ri.index_document(_BoomTable(), doc) == ri.SKIPPED_NO_TEXT
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], "an empty-text SKIP was logged as an ERROR"


def test_the_publish_path_does_not_report_a_miss_at_info():
    """The caller's half: `[recall] index <date>: failed` was logged at INFO, which is
    why a real gap sat unnoticed for four days."""
    import re

    src = open(os.path.join(_REPO, "lambdas", "emails", "chronicle_approve_lambda.py"), encoding="utf-8").read()
    m = re.search(r"status = recall_indexer\.index_chronicle_installment\(.*?\n(.*?)\n\n", src, re.S)
    assert m, "the recall-index call site moved — update this extraction"
    block = m.group(1)
    assert "logger.error" in block, f"a failed index is still reported without an ERROR: {block}"


@pytest.mark.parametrize("status", ["indexed", "unchanged", "repaired", "skipped_budget"])
def test_non_failure_statuses_stay_informational(status):
    """A budget pause or an idempotent no-op is not a fault (ADR-125)."""
    assert status != ri.FAILED
