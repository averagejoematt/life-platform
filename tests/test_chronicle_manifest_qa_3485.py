"""#3485 — the qa-smoke dead-man: the served journal manifest never carries an archived post."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from operational import chronicle_manifest_qa as cmq  # noqa: E402


class _Check:
    def __init__(self, name, group, tier):
        self.name, self.group, self.tier = name, group, tier
        self.state, self.msg = None, ""

    def ok(self, msg):
        self.state, self.msg = "ok", msg

    def warn(self, msg, **kw):
        self.state, self.msg = "warn", msg

    def fail(self, msg):
        self.state, self.msg = "fail", msg


class _S3:
    def __init__(self, posts):
        self._body = json.dumps({"posts": posts}).encode()

    def get_object(self, Bucket, Key):
        assert Key == cmq.MANIFEST_KEY
        return {"Body": type("B", (), {"read": lambda s: self._body})()}


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def get_item(self, Key):
        return {"Item": self.rows.get(Key["sk"])} if Key["sk"] in self.rows else {}


def _run(posts, rows):
    (c,) = cmq.check_chronicle_manifest_provenance(_Table(rows), _S3(posts), "b", _Check, "tier")
    return c


def test_the_2026_09_04_specimen_is_a_red():
    """Four cycle-15 posts served on Day 0 of cycle 16 behind a tombstoned row."""
    posts = [{"date": "2026-09-01", "title": "328.1"}, {"date": "2026-08-30", "title": "Before the Numbers"}]
    rows = {
        "DATE#2026-09-01": {"status": "published", "tombstone": True, "phase": "pilot", "cycle": 15},
        "DATE#2026-08-30": {"status": "published"},
    }
    c = _run(posts, rows)
    assert c.state == "fail" and "328.1" in c.msg and "previous cycle" in c.msg


def test_a_non_current_phase_without_a_tombstone_is_still_a_red():
    c = _run([{"date": "2026-09-01", "title": "x"}], {"DATE#2026-09-01": {"status": "published", "phase": "pilot"}})
    assert c.state == "fail"


def test_current_rows_are_green():
    posts = [{"date": "2026-09-04", "title": "The Night Before Everything"}, {"date": "2026-08-30", "title": "Before the Numbers"}]
    rows = {"DATE#2026-09-04": {"status": "published"}, "DATE#2026-08-30": {"status": "published", "phase": "experiment"}}
    c = _run(posts, rows)
    assert c.state == "ok" and "2 post(s)" in c.msg


def test_a_post_with_no_chronicle_row_warns_not_reds():
    c = _run([{"date": "2026-08-30", "title": "lead-in"}], {})
    assert c.state == "warn"


def test_an_unreadable_manifest_is_a_red_not_a_silent_pass():
    class _BrokenS3:
        def get_object(self, Bucket, Key):
            raise RuntimeError("boom")

    (c,) = cmq.check_chronicle_manifest_provenance(_Table({}), _BrokenS3(), "b", _Check, "tier")
    assert c.state == "fail"
