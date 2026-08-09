"""tests/test_chronicle_sk_invariant_2367.py — the sk-vs-date invariant spot check.

#2367: sk is the chronicle row's identity; `date` is display/as-of and may be
rewritten by the ADR-077 --keep-chronicle carry-forward, which stamps
`redated_from_sk` when it does. The nightly check exempts by that MARKER, never
by hand-listed sks — so the next reset's carried lead-ins are born compliant.
Offline: a fake table, no AWS.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")

from operational.qa_check_outputs import check_chronicle_sk_date_invariant  # noqa: E402


class _FakeTable:
    def __init__(self, items):
        self._items = items

    def query(self, **kwargs):
        return {"Items": list(self._items)}


def _run(items):
    (c,) = check_chronicle_sk_date_invariant(_FakeTable(items))
    return c


def test_matching_rows_pass():
    c = _run([{"sk": "DATE#2026-08-05", "date": "2026-08-05"}])
    assert c.passed is True


def test_carried_row_with_marker_is_exempt():
    c = _run(
        [
            {
                "sk": "DATE#2026-02-28",
                "date": "2026-08-09",
                "redated_from_sk": "DATE#2026-02-28",
                "cycle": 13,
            }
        ]
    )
    assert c.passed is True


def test_mismatch_without_marker_fails_naming_the_sk():
    c = _run([{"sk": "DATE#2026-07-21", "date": "2026-08-02"}])
    assert c.passed is False
    assert "DATE#2026-07-21" in c.message and "2026-08-02" in c.message


def test_tombstoned_mismatch_is_ignored():
    c = _run([{"sk": "DATE#2026-07-21", "date": "2026-08-02", "tombstone": True}])
    assert c.passed is True


def test_query_failure_is_a_warn_not_a_fail():
    class _Boom:
        def query(self, **kwargs):
            raise RuntimeError("ddb down")

    (c,) = check_chronicle_sk_date_invariant(_Boom())
    assert c.passed is None  # warn — fail-soft, the nightly stays legible


def test_wired_into_the_nightly_run_list(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    from operational import qa_smoke_lambda as qa

    labels = [label for label, _fn in qa.check_steps()]
    assert "chronicle_sk_invariant" in labels
