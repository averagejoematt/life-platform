"""tests/test_site_api_decisions_residue_guard_4190.py — #4190, serve-time half.

Defence in depth (AC2): the write door now strips tool-call XML residue going
forward (`tests/test_mcp_tool_call_residue_guard_4190.py`), but the 2026-09-08
`log_decision` record is ALREADY stored dirty — its `decision` field ends
`…Foundation - Push - 3 - 11.</decision>\\n<parameter name="followed">true` and
`/api/decisions` served it straight through to `/protocols/experiments/`. The
serializer (`lambdas/web/site_api_thirdwall.py::handle_decisions`) applies the
SAME shared strip (`common.text_guards.strip_tool_call_residue`) at serve time,
so an already-dirty row is cleaned until the owner scrubs it (an owner-approved
DDB write — out of scope here, #4190 AC4).

Same test harness as `tests/test_third_wall_widen_1569.py` (`FakeDdbTable`,
`web.site_api_coach.handle_decisions` thin-delegates to `site_api_thirdwall`).
"""

from __future__ import annotations

import json
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

from common.text_guards import has_tool_call_residue  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

# The runtime content filter's term source — same fixture shape site_api_common
# ._load_content_filter returns, pinned so scrubbing is deterministic (no S3).
_FILTER = {"blocked_vices": [], "blocked_vice_keywords": []}

LIVE_RESIDUE_DECISION = 'Committed to Hevy as Foundation - Push - 3 - 11.</decision>\n<parameter name="followed">true'
LIVE_RESIDUE_CLEAN = "Committed to Hevy as Foundation - Push - 3 - 11."


def _body(resp):
    return json.loads(resp["body"])


def _dec_row(sk, **over):
    row = {
        "pk": "USER#matthew#SOURCE#decisions",
        "sk": f"DECISION#{sk}",
        "date": "2026-09-08",
        "decision": "Take a rest day",
        "source": "mcp",
    }
    row.update(over)
    return row


def _coach_decisions(monkeypatch, rows, event=None):
    import web.site_api_coach as coach
    import web.site_api_common as common

    monkeypatch.setattr(common, "_content_filter_cache", dict(_FILTER))
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=rows))
    return _body(coach.handle_decisions(event or {}))


def test_decisions_field_residue_is_stripped_at_serve_time(monkeypatch):
    """The exact filed scenario: a decision field ending in tool-call XML residue,
    served through the real /api/decisions handler."""
    rows = [
        _dec_row(
            "2026-09-08T05:08:54.979Z",
            decision=LIVE_RESIDUE_DECISION,
            followed=True,
            note="Went with the platform's call.",
            note_at="2026-09-08T05:08:54.979Z",
        )
    ]
    body = _coach_decisions(monkeypatch, rows)
    assert body["count"] == 1
    d0 = body["decisions"][0]
    assert d0["decision"] == LIVE_RESIDUE_CLEAN
    assert not has_tool_call_residue(d0["decision"])


def test_override_reason_residue_is_stripped_at_serve_time(monkeypatch):
    rows = [
        _dec_row(
            "2026-09-08T05:08:54.979Z",
            followed=False,
            override_reason=LIVE_RESIDUE_DECISION,
            note="My call.",
            note_at="2026-09-08T05:08:54.979Z",
        )
    ]
    body = _coach_decisions(monkeypatch, rows)
    d0 = body["decisions"][0]
    assert d0["override_reason"] == LIVE_RESIDUE_CLEAN
    assert not has_tool_call_residue(d0["override_reason"])


def test_note_residue_is_stripped_before_the_all_or_nothing_screen(monkeypatch):
    """`_public_decision_note` compares a scrubbed copy against the raw note to
    decide all-or-nothing withholding — residue must be stripped BEFORE that
    compare, or `_scrub_blocked_terms` (which has no reason to touch `<...>`)
    finds scrubbed == raw and lets the residue sail through as a clean quote."""
    rows = [
        _dec_row(
            "2026-09-08T05:08:54.979Z",
            followed=True,
            note="Went with the platform's call." + LIVE_RESIDUE_DECISION,
            note_at="2026-09-08T05:08:54.979Z",
        )
    ]
    body = _coach_decisions(monkeypatch, rows)
    assert body["count"] == 1, "a note carrying residue must still publish once the residue is stripped, not be withheld"
    d0 = body["decisions"][0]
    assert not has_tool_call_residue(d0["note"])
    # Only the tool-call-XML TAIL (from the first `<`) is residue — everything
    # before it, including "Committed to Hevy..." run together with no space, is
    # real prior text and must survive.
    assert d0["note"] == "Went with the platform's call.Committed to Hevy as Foundation - Push - 3 - 11."


def test_clean_decision_is_unaffected_by_the_new_strip(monkeypatch):
    rows = [
        _dec_row(
            "2026-09-08T05:08:54.979Z",
            decision="Take a rest day.",
            followed=True,
            note="Needed it.",
            note_at="2026-09-08T05:08:54.979Z",
        )
    ]
    body = _coach_decisions(monkeypatch, rows)
    assert body["decisions"][0]["decision"] == "Take a rest day."
    assert body["decisions"][0]["note"] == "Needed it."
