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
    """#3650: the fake now serves `query`, because the check no longer reconstructs a key.

    Rows are given as {sk: attrs}; the sk is injected into each row and, unless the case
    states otherwise, `date` DEFAULTS to the sk's date. That default is what keeps every
    pre-#3650 case meaningful — those rows had sk == date, which was true then and is the
    special case now, not the rule.
    """

    def __init__(self, rows):
        self.rows = []
        for sk, attrs in rows.items():
            r = dict(attrs)
            r["sk"] = sk
            r.setdefault("date", sk.replace("DATE#", ""))
            self.rows.append(r)

    def query(self, **kwargs):
        return {"Items": list(self.rows)}


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


# ── #3650: the false positive that reded the nightly for days ────────────────
def test_a_redated_post_whose_sk_diverges_from_its_date_is_NOT_a_red():
    """The live 2026-09-07 specimen, and the regression this fix exists for.

    "Before the Numbers" is `sk=DATE#2026-02-28` carrying `date=2026-08-31` — a reset
    re-dated it by writing the attribute and leaving the sk alone, which is the designed
    behaviour. A DIFFERENT, tombstoned cycle-15 row occupies `DATE#2026-08-31`.

    The old check fetched that other row by reconstructed key and called the manifest
    archived. The site was never serving it.
    """
    posts = [{"date": "2026-08-31", "title": "Before the Numbers"}]
    rows = {
        # the row the manifest actually serves — live, cycle 17
        "DATE#2026-02-28": {"status": "published", "date": "2026-08-31", "title": "Before the Numbers", "phase": "experiment", "cycle": 17},
        # the decoy the old code fetched — same slot, tombstoned, previous cycle
        "DATE#2026-08-31": {
            "status": "published",
            "date": "2026-08-31",
            "title": "The Plan, On the Record",
            "tombstone": True,
            "phase": "pilot",
            "cycle": 15,
        },
    }
    c = _run(posts, rows)
    assert c.state == "ok", f"a re-dated post must not red: {c.msg}"


def test_the_decoy_row_alone_still_reds():
    """The negative control for the case above: if the manifest really IS serving the
    tombstoned row, the check must still fail. The fix must not have bought its green by
    becoming blind."""
    posts = [{"date": "2026-08-31", "title": "The Plan, On the Record"}]
    rows = {
        "DATE#2026-08-31": {
            "status": "published",
            "date": "2026-08-31",
            "title": "The Plan, On the Record",
            "tombstone": True,
            "phase": "pilot",
            "cycle": 15,
        },
    }
    c = _run(posts, rows)
    assert c.state == "fail" and "previous cycle" in c.msg


def test_two_rows_claiming_one_post_are_reported_not_silently_resolved():
    """Ambiguity is a data fault worth naming. Picking whichever row sorts first would
    hide it behind a green check — the failure mode this whole file guards."""
    posts = [{"date": "2026-08-31", "title": "Same Title"}]
    rows = {
        "DATE#2026-02-28": {"status": "published", "date": "2026-08-31", "title": "Same Title", "phase": "experiment"},
        "DATE#2026-08-31": {"status": "published", "date": "2026-08-31", "title": "Same Title", "phase": "experiment"},
    }
    c = _run(posts, rows)
    assert c.state == "fail" and "more than one chronicle row" in c.msg


def test_a_unique_date_match_does_not_need_the_title():
    """Title only disambiguates. A post that was re-titled after publication is still
    matched when its date picks out exactly one row."""
    posts = [{"date": "2026-08-31", "title": "Renamed Since Publication"}]
    rows = {"DATE#2026-02-28": {"status": "published", "date": "2026-08-31", "title": "Original Title", "phase": "experiment"}}
    c = _run(posts, rows)
    assert c.state == "ok", c.msg
