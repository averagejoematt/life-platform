"""tests/test_third_wall_widen_1569.py — the widened Third Wall (#1569).

The one-reply-per-week Third Wall (AI's read ↔ Matthew's response) is extended to
two more surfaces, reusing the SAME two-voice pattern and the field-notes-style
serving — NO new pipeline:

  (a) an experiment CARD carries an optional verbatim Matthew note, written at
      creation (create_experiment) or review (end_experiment).
  (b) a logged DECISION with an opt-in verbatim note renders on the experiment
      archive, dated, voice-tagged human — served by a new site_api_coach handler.

The load-bearing contract (AC3): the write path is opt-in per item, and an ABSENT
note renders NOTHING — no key on the payload, no nag state. New verbatim fields are
user content, so they pass through the runtime content filter (the same term list
the CI content-policy scan enforces) at serve time.
"""

import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_decisions as td  # noqa: E402
import mcp.tools_lifestyle as tl  # noqa: E402

# The runtime content filter's term source — pinned here so scrubbing is deterministic
# and hits no S3. This is the SAME shape site_api_common._load_content_filter returns.
_FILTER = {
    "blocked_vices": ["No porn", "No marijuana"],
    "blocked_vice_keywords": ["porn", "pornography", "marijuana", "cannabis", "weed", "thc"],
}


class _FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)

    def get_object(self, **kw):
        raise RuntimeError("S3 not used in this test")


# ── (AC1) experiment card: the note is opt-in at create time ──────────────────


def _create(monkeypatch, args):
    table = FakeDdbTable(rows=[])
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "s3_client", _FakeS3())
    base = {"name": "Cold plunge AM", "hypothesis": "raises daytime energy", "start_date": "2026-07-13"}
    base.update(args)
    return tl.tool_create_experiment(base), table


def test_create_experiment_stores_verbatim_note_when_given(monkeypatch):
    note = "I said yes because the cortisol angle finally clicked — worth two weeks."
    res, table = _create(monkeypatch, {"matthew_note": note})
    assert res.get("matthew_note") == note  # echoed back
    stored = table.puts[-1]
    assert stored["matthew_note"] == note
    assert stored.get("matthew_note_at")  # dated


def test_create_experiment_absent_note_writes_nothing(monkeypatch):
    """AC3: opt-in — no note arg means no field on the record and no echo."""
    res, table = _create(monkeypatch, {})
    stored = table.puts[-1]
    assert "matthew_note" not in stored  # cleaned None → absent, not empty-string
    assert "matthew_note_at" not in stored
    assert "matthew_note" not in res


def test_create_experiment_note_is_length_capped(monkeypatch):
    res, table = _create(monkeypatch, {"matthew_note": "x" * 900})
    assert len(table.puts[-1]["matthew_note"]) == 500


# ── (AC1) experiment card: the note is writable at review time ────────────────


def test_end_experiment_sets_note_at_review(monkeypatch):
    exp = {
        "pk": "USER#matthew#SOURCE#experiments",
        "sk": "EXP#cold-plunge-am_2026-07-13",
        "experiment_id": "cold-plunge-am_2026-07-13",
        "name": "Cold plunge AM",
        "status": "active",
        "start_date": "2026-07-13",
    }
    table = FakeDdbTable(rows=[exp])
    monkeypatch.setattr(tl, "table", table)
    tl.tool_end_experiment(
        {"experiment_id": "cold-plunge-am_2026-07-13", "outcome": "Energy up", "matthew_note": "Honestly the best two weeks in months."}
    )
    upd = table.updates[-1]
    assert ":mn" in upd["ExpressionAttributeValues"]
    assert upd["ExpressionAttributeValues"][":mn"] == "Honestly the best two weeks in months."
    assert "matthew_note = :mn" in upd["UpdateExpression"]


def test_end_experiment_without_note_does_not_touch_it(monkeypatch):
    exp = {
        "pk": "USER#matthew#SOURCE#experiments",
        "sk": "EXP#x_2026-07-13",
        "experiment_id": "x_2026-07-13",
        "name": "X",
        "status": "active",
        "start_date": "2026-07-13",
    }
    table = FakeDdbTable(rows=[exp])
    monkeypatch.setattr(tl, "table", table)
    tl.tool_end_experiment({"experiment_id": "x_2026-07-13", "outcome": "meh"})
    upd = table.updates[-1]
    assert ":mn" not in upd["ExpressionAttributeValues"]


# ── (AC2) decision journal: the note is opt-in at log time ────────────────────


def _log_decision(monkeypatch, args):
    table = FakeDdbTable(rows=[])
    monkeypatch.setattr(td, "_table_ref", table)
    base = {"decision": "Take a rest day"}
    base.update(args)
    return td.tool_log_decision(base), table


def test_log_decision_stores_verbatim_note(monkeypatch):
    res, table = _log_decision(monkeypatch, {"note": "Brief said rest but my legs felt great, so I trained.", "followed": False})
    assert res.get("note", "").startswith("Brief said rest")
    stored = table.puts[-1]
    assert stored["note"].startswith("Brief said rest")
    assert stored.get("note_at")


def test_log_decision_absent_note_writes_nothing(monkeypatch):
    res, table = _log_decision(monkeypatch, {})
    stored = table.puts[-1]
    assert "note" not in stored
    assert "note_at" not in stored
    assert "note" not in res


def test_get_decisions_surfaces_the_note(monkeypatch):
    row = {
        "pk": "USER#matthew#SOURCE#decisions",
        "sk": "DECISION#2026-07-20T10:00:00.000Z",
        "date": "2026-07-20",
        "decision": "Take a rest day",
        "note": "Trained anyway — legs felt great.",
        "note_at": "2026-07-20T10:00:00.000Z",
        "followed": False,
    }
    table = FakeDdbTable(rows=[row])
    monkeypatch.setattr(td, "_table_ref", table)
    # _apply_phase_filter is a passthrough on the fake; get_decisions filters by date.
    out = td.tool_get_decisions({"days": 3650})
    d0 = out["decisions"][0]
    assert d0["note"] == "Trained anyway — legs felt great."
    assert d0["note_at"]


# ── (AC1/AC3) serving: /api/experiments carries the scrubbed note, omits absent ─


def _protocols_module(monkeypatch, rows):
    import web.site_api_common as common
    import web.site_api_protocols as prot

    monkeypatch.setattr(common, "_content_filter_cache", dict(_FILTER))
    table = FakeDdbTable(rows=rows)
    g = dict(prot.__dict__)  # real module globals (with_phase_filter, USER_PREFIX, _public_note, …)
    g["table"] = table
    g["_experiment_catalog"] = lambda ids, names: []  # no library overlay
    return prot, g


def _exp_row(**over):
    row = {
        "pk": "USER#matthew#SOURCE#experiments",
        "sk": "EXP#cold-plunge-am_2026-07-13",
        "name": "Cold plunge AM",
        "status": "active",
        "start_date": "2026-07-13",
        "hypothesis": "raises daytime energy",
    }
    row.update(over)
    return row


def _body(resp):
    import json

    return json.loads(resp["body"])


def test_experiments_serves_scrubbed_note(monkeypatch):
    prot, g = _protocols_module(monkeypatch, [_exp_row(matthew_note="Said yes for the energy.", matthew_note_at="2026-07-13T09:00:00")])
    exp = _body(prot.experiments(_g=g))["experiments"][0]
    assert exp["matthew_note"] == "Said yes for the energy."
    assert exp["matthew_note_at"] == "2026-07-13T09:00:00"


def test_experiments_omits_absent_note(monkeypatch):
    """AC3: no note on the record → no key on the payload (not null)."""
    prot, g = _protocols_module(monkeypatch, [_exp_row()])
    exp = _body(prot.experiments(_g=g))["experiments"][0]
    assert "matthew_note" not in exp
    assert "matthew_note_at" not in exp


def test_experiments_drops_note_that_fails_content_filter(monkeypatch):
    """A verbatim note mentioning a blocked vice is withheld entirely → renders
    nothing (never a partially-scrubbed fragment on this public card)."""
    prot, g = _protocols_module(monkeypatch, [_exp_row(matthew_note="Cut back on marijuana this cycle.")])
    exp = _body(prot.experiments(_g=g))["experiments"][0]
    assert "matthew_note" not in exp


# ── (AC2/AC3/AC4) serving: /api/decisions — only noted decisions, dated, human ─


def _coach_decisions(monkeypatch, rows, event=None):
    import web.site_api_coach as coach
    import web.site_api_common as common

    monkeypatch.setattr(common, "_content_filter_cache", dict(_FILTER))
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=rows))
    return _body(coach.handle_decisions(event or {}))


def _dec_row(sk, **over):
    row = {
        "pk": "USER#matthew#SOURCE#decisions",
        "sk": f"DECISION#{sk}",
        "date": "2026-07-20",
        "decision": "Take a rest day",
        "source": "daily_brief",
    }
    row.update(over)
    return row


def test_decisions_returns_only_noted_decisions(monkeypatch):
    rows = [
        _dec_row(
            "2026-07-20T10:00:00.000Z",
            note="Trained anyway — legs felt great.",
            note_at="2026-07-20T10:00:00.000Z",
            followed=False,
            override_reason="Legs felt great",
        ),
        _dec_row("2026-07-19T10:00:00.000Z"),  # no note — must NOT appear (AC3)
    ]
    body = _coach_decisions(monkeypatch, rows)
    assert body["count"] == 1
    d0 = body["decisions"][0]
    assert d0["note"] == "Trained anyway — legs felt great."
    assert d0["note_at"] == "2026-07-20T10:00:00.000Z"  # dated
    assert d0["date"] == "2026-07-20"
    assert d0["decision"] == "Take a rest day"  # the machine voice half
    assert d0["override_reason"] == "Legs felt great"


def test_decisions_empty_when_no_notes(monkeypatch):
    """AC3: a partition full of note-less decisions serves an empty feed → the page
    renders nothing (no nag)."""
    rows = [_dec_row("2026-07-20T10:00:00.000Z"), _dec_row("2026-07-19T10:00:00.000Z")]
    body = _coach_decisions(monkeypatch, rows)
    assert body["count"] == 0
    assert body["decisions"] == []


def test_decisions_content_filters_the_note(monkeypatch):
    rows = [_dec_row("2026-07-20T10:00:00.000Z", note="Skipped the marijuana this week.", note_at="2026-07-20T10:00:00.000Z")]
    body = _coach_decisions(monkeypatch, rows)
    # The note is withheld by the filter → the decision has no publishable note → not shown.
    assert body["count"] == 0


def test_decisions_respects_limit(monkeypatch):
    rows = [_dec_row(f"2026-07-{d:02d}T10:00:00.000Z", note=f"note {d}", note_at=f"2026-07-{d:02d}T10:00:00.000Z") for d in range(10, 25)]
    body = _coach_decisions(monkeypatch, rows, {"queryStringParameters": {"limit": "3"}})
    assert body["count"] == 3
