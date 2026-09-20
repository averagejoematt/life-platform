"""#3942 — `dry_run=True` on the recap card generator writes NOTHING: no S3 put on the daily,
detail or weekly card, no DynamoDB row on any path — and the result still carries the would-be
keys (marked `storage: "dry_run"`) plus the rendered bytes, so a dry run remains an inspection.

The incident: one "dry run" meant to look at a card republished three live `recap/` objects and
moved the row's `rendered_at` (Session AN, 2026-09-19). The flag gated delivery only.

Mutation control: in `render_for_date`, make `_store` / `_rec` ignore `dry_run` (delete the two
`if dry_run: return` lines) → `test_a_dry_run_writes_nothing_on_the_daily_detail_and_weekly_paths`
reds on the S3 puts and the record; the positive control below proves the same harness DOES write
when dry_run is False, so the zero is measured, not vacuous.
"""

from __future__ import annotations

import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.dirname(__file__))

pytest.importorskip("PIL")

from test_recap_detail_3741 import GRADES, WEIGHTS, _full  # noqa: E402 — the sibling's fixtures are the wire


@pytest.fixture
def harness(monkeypatch):
    from content import recap_data, recap_deliver, recap_gate
    from web import recap_card_lambda as C

    puts: dict[str, bytes] = {}
    records: dict[str, dict] = {}
    monkeypatch.setattr(C._s3, "put_object", lambda Bucket, Key, Body, **kw: puts.__setitem__(Key, Body))
    monkeypatch.setattr(C, "_record", lambda sk, payload: records.__setitem__(sk, payload))
    monkeypatch.setattr(C, "_existing", lambda sk: None)
    monkeypatch.setattr(C.boto3, "client", lambda *a, **k: None)
    monkeypatch.setattr(C, "EXPERIMENT_START_DATE", "2026-09-06")
    monkeypatch.setattr(C, "_week_totals", lambda *a, **k: {"sessions": 6, "sets": 117, "misses": "recovery — 24/100 at its worst"})
    monkeypatch.setattr(recap_data, "trailing", lambda *a, **k: [])
    monkeypatch.setattr(recap_data, "cycle_series", lambda *a, **k: (WEIGHTS, GRADES))
    monkeypatch.setattr(recap_data, "coach_line", lambda *a, **k: ("The Garmin pause has created a data blind spot.", "OUTPUT#x", "ok"))
    monkeypatch.setattr(recap_gate, "gate", lambda strings, **k: recap_gate.GateResult(recap_gate.VERDICT_CLEARED))
    monkeypatch.setattr(recap_deliver, "deliver", lambda png, caption, **k: {"telegram": "dry_run", "email": "dry_run"})
    # 2026-09-19 is day 14 of a 2026-09-06 genesis: the daily, the detail AND the weekly card
    monkeypatch.setattr(recap_data, "day_facts", lambda *a, **k: _full(date="2026-09-19", day_n=14))
    return C, puts, records


def test_a_dry_run_writes_nothing_on_the_daily_detail_and_weekly_paths(harness):
    C, puts, records = harness
    out = C.render_for_date("2026-09-19", deliver=True, force=True, dry_run=True)
    assert puts == {}, f"a dry run put objects to S3: {sorted(puts)}"
    assert records == {}, f"a dry run wrote a DynamoDB row: {sorted(records)}"
    # the would-be keys are still reported, and marked
    assert out["s3_key"] == "recap/2026-09-19.png"
    assert out["detail_s3_key"] == "recap/2026-09-19-detail.png"
    assert out["weekly"]["s3_key"] == "recap/week-02.png", out.get("weekly")
    assert out["storage"] == "dry_run" and out["weekly"]["storage"] == "dry_run"
    # and the bytes are reachable — a dry run is an inspection, not a no-op
    for k in ("png_base64", "detail_png_base64"):
        assert base64.b64decode(out[k])[:8] == b"\x89PNG\r\n\x1a\n", k
    assert base64.b64decode(out["weekly"]["png_base64"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_same_harness_writes_three_objects_and_one_row_when_not_a_dry_run(harness):
    """Positive control for the zero above: the harness CAN observe writes."""
    C, puts, records = harness
    out = C.render_for_date("2026-09-19", deliver=True, force=True, dry_run=False)
    assert set(puts) == {"recap/2026-09-19.png", "recap/2026-09-19-detail.png", "recap/week-02.png"}
    assert set(records) == {"DATE#2026-09-19"}
    assert out["storage"] == "written" and out["weekly"]["storage"] == "written"
    assert "png_base64" not in out and "png_base64" not in out["weekly"], "bytes ride only on a dry run"


def test_a_dry_run_that_the_gate_holds_writes_no_row_either(harness, monkeypatch):
    """The held paths recorded a row before; box 1 says NO DynamoDB write on ANY path."""
    from content import recap_gate

    C, puts, records = harness
    monkeypatch.setattr(recap_gate, "gate", lambda strings, **k: recap_gate.GateResult("held", reason="planted"))
    out = C.render_for_date("2026-09-19", deliver=True, force=True, dry_run=True)
    assert out["outcome"] == "held"
    assert puts == {} and records == {}
    out = C.render_for_date("2026-09-19", deliver=True, force=True, dry_run=False)
    assert out["outcome"] == "held" and set(records) == {"DATE#2026-09-19"}, "the held row IS written when not a dry run"
