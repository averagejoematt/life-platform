"""tests/test_elena_chronicle_tombstone_1200.py — #1200: Elena's persistent-memory
reads in the chronicle prompt builders must honor the restart tombstone.

The intelligence wipe (ADR-077, restart_intelligence_wipe.py) stamps
tombstone=true + phase=pilot on every PERSONA#elena record (THREAD#/CALLBACK#/
STANCE#/MOTIF#). The #946 fix guarded elena_state_updater and the site-api coach
readers, but missed the chronicle *prompt builders* that feed Elena's notebook
into the draft — so cycle-N story threads/promises paid off in cycle-N+1 drafts
with a phantom citation (the exact failure phase_taxonomy.py:203-207 names).

These tests seed tombstoned PERSONA#elena rows and assert:
  - wednesday_chronicle_lambda._elena_notebook_block() returns ''
  - wednesday_chronicle_lambda._due_callback_promises() returns []
  - between_chronicle_lambda.gather_digest() carries no elena_note
and that a clean current-cycle record still flows through (no over-filtering).

Non-vacuous by construction: without the singleton_visible guards the seeded
tombstoned rows (status=open/pending, so they pass the status filter) leak into
the block / list / digest and every "empty after wipe" assertion fails.
"""

import os
import sys
from datetime import date, timedelta

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import between_chronicle_lambda as bc  # noqa: E402
import wednesday_chronicle_lambda as chron  # noqa: E402
from constants import EXPERIMENT_START_DATE  # noqa: E402

GENESIS = date.fromisoformat(EXPERIMENT_START_DATE)
PRE_GENESIS = (GENESIS - timedelta(days=7)).isoformat()
POST_GENESIS = (GENESIS + timedelta(days=2)).isoformat()

# The exact shape the wipe stamps (restart_intelligence_wipe.build_update).
TOMBSTONED = {"tombstone": True, "phase": "pilot", "tombstoned_reason": f"experiment_restart_{EXPERIMENT_START_DATE}"}


class _KeyedFakeTable:
    """DDB stand-in that routes get_item by (pk, sk) and query by pk-prefix.

    get_item: `items` maps (pk, sk) -> dict.
    query:    `query_map` maps (pk, sk_prefix) -> [rows]; matched by the
              KeyConditionExpression's Key("pk").eq(...) & begins_with(sk, ...).
    """

    def __init__(self, items=None, query_map=None):
        self.items = items or {}
        self.query_map = query_map or {}

    def get_item(self, Key=None, **kw):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it is not None else {}

    def query(self, **kw):
        cond = kw.get("KeyConditionExpression")
        pk, prefix = _parse_key_condition(cond)
        return {"Items": list(self.query_map.get((pk, prefix), []))}


def _parse_key_condition(cond):
    """Extract (pk_value, sk_prefix) from a boto3 Key condition or a raw string.

    The chronicle code builds `Key("pk").eq(pk) & Key("sk").begins_with("THREAD#")`.
    boto3's ConditionBase stores operands we can walk; fall back to string parse
    for the between-lambda's raw-string form.
    """
    try:
        # boto3.dynamodb.conditions.And -> _values = (Equals, BeginsWith)
        vals = getattr(cond, "_values", None)
        if vals:
            pk_val = None
            prefix = None
            for sub in vals:
                sub_vals = getattr(sub, "_values", ())
                name = getattr(sub_vals[0], "name", None) if sub_vals else None
                if name == "pk":
                    pk_val = sub_vals[1]
                elif name == "sk":
                    prefix = sub_vals[1]
            return pk_val, prefix
    except Exception:
        pass
    return None, None


# ── wednesday: _elena_notebook_block ─────────────────────────────────────────


def _wednesday_table(threads, callbacks, stance=None, motif=None):
    items = {}
    if stance is not None:
        items[("PERSONA#elena", "STANCE#latest")] = stance
    if motif is not None:
        items[("PERSONA#elena", "MOTIF#state")] = motif
    query_map = {
        ("PERSONA#elena", "THREAD#"): threads,
        ("PERSONA#elena", "CALLBACK#"): callbacks,
    }
    return _KeyedFakeTable(items=items, query_map=query_map)


def test_notebook_block_empty_when_all_persona_state_tombstoned(monkeypatch):
    """The live-DDB shape from the issue: 7 open THREAD# + 2 pending CALLBACK#,
    all tombstone=True, plus a tombstoned STANCE#/MOTIF#. Every one must drop."""
    threads = [
        {"sk": f"THREAD#{PRE_GENESIS}#the-sunday-walks", "status": "open", "slug": "the-sunday-walks", "summary": "walks", **TOMBSTONED}
        for _ in range(7)
    ]
    callbacks = [
        {"sk": f"CALLBACK#{PRE_GENESIS}#p{i}", "status": "pending", "due_by_week": 1, "promise": "pay it off", **TOMBSTONED}
        for i in range(2)
    ]
    stance = {"headline_stance": "the body keeps receipts", "positions": ["x"], **TOMBSTONED}
    motif = {"motifs": ["the pre-experiment period documented in the prologue"], **TOMBSTONED}
    monkeypatch.setattr(chron, "table", _wednesday_table(threads, callbacks, stance=stance, motif=motif))
    assert chron._elena_notebook_block(current_week=1) == ""


def test_notebook_block_serves_current_cycle_state(monkeypatch):
    """A clean current-cycle notebook must still render — the guard must not
    over-filter unphased/current-phase rows."""
    threads = [
        {"sk": f"THREAD#{POST_GENESIS}#fresh", "status": "open", "slug": "fresh-thread", "summary": "a live thread", "opened_week": 1}
    ]
    callbacks = [{"sk": f"CALLBACK#{POST_GENESIS}#due", "status": "pending", "due_by_week": 1, "promise": "a live promise"}]
    stance = {"headline_stance": "a grounded current read", "positions": ["p1"]}
    motif = {"motifs": ["a live motif"]}
    monkeypatch.setattr(chron, "table", _wednesday_table(threads, callbacks, stance=stance, motif=motif))
    block = chron._elena_notebook_block(current_week=1)
    assert "fresh-thread" in block
    assert "a live promise" in block
    assert "a grounded current read" in block
    assert "a live motif" in block


def test_notebook_block_mixed_keeps_only_current_cycle(monkeypatch):
    """A wiped thread and a live thread in the same partition: only the live one
    survives (the reset-generation boundary the wipe draws)."""
    threads = [
        {"sk": f"THREAD#{PRE_GENESIS}#wiped", "status": "open", "slug": "wiped-thread", "summary": "old", **TOMBSTONED},
        {"sk": f"THREAD#{POST_GENESIS}#live", "status": "open", "slug": "live-thread", "summary": "new", "opened_week": 1},
    ]
    monkeypatch.setattr(chron, "table", _wednesday_table(threads, [], stance=None, motif=None))
    block = chron._elena_notebook_block(current_week=1)
    assert "live-thread" in block
    assert "wiped-thread" not in block


# ── wednesday: _due_callback_promises (Margaret's critique input) ────────────


def test_due_callback_promises_empty_when_tombstoned(monkeypatch):
    callbacks = [
        {"sk": f"CALLBACK#{PRE_GENESIS}#zone2", "status": "pending", "due_by_week": 1, "promise": "the Sunday walks payoff", **TOMBSTONED}
    ]
    monkeypatch.setattr(chron, "table", _wednesday_table([], callbacks))
    assert chron._due_callback_promises(week_num=5) == []


def test_due_callback_promises_serves_current_cycle(monkeypatch):
    callbacks = [{"sk": f"CALLBACK#{POST_GENESIS}#live", "status": "pending", "due_by_week": 1, "promise": "a live debt"}]
    monkeypatch.setattr(chron, "table", _wednesday_table([], callbacks))
    assert chron._due_callback_promises(week_num=5) == ["a live debt"]


# ── between: gather_digest elena_note ────────────────────────────────────────


def _between_table(elena_stance):
    # gather_digest also reads what_changed + COACH#* predictions/stance; return
    # empty for all of those so the test isolates the elena_note path.
    items = {("PERSONA#elena", "STANCE#latest"): elena_stance}
    return _KeyedFakeTable(items=items, query_map={})


def test_between_elena_note_dropped_when_tombstoned(monkeypatch):
    stance = {"headline_stance": "a wiped cycle's editorial read", **TOMBSTONED}
    monkeypatch.setattr(bc, "table", _between_table(stance))
    digest = bc.gather_digest()
    assert digest.get("elena_note") is None


def test_between_elena_note_kept_for_current_cycle(monkeypatch):
    stance = {"headline_stance": "a grounded current read"}
    monkeypatch.setattr(bc, "table", _between_table(stance))
    digest = bc.gather_digest()
    assert digest.get("elena_note") == "a grounded current read"


# ── phase_taxonomy contract: PERSONA#elena is EXPERIMENT_SCOPED (wipe tombstones it) ──


def test_persona_elena_is_experiment_scoped():
    """The read-side guard only closes the bug because the wipe actually
    tombstones PERSONA#elena — pin that classification so a taxonomy change that
    would silently reopen this bug fails here too."""
    import phase_taxonomy as pt

    assert pt.classify("PERSONA#elena", "THREAD#2026-07-07#x") == pt.EXPERIMENT_SCOPED
    assert pt.classify("PERSONA#elena", "STANCE#latest") == pt.EXPERIMENT_SCOPED


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
