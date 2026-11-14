"""tests/test_tag_record_phase_shape_5931.py — #5931: a tagged compute item's `phase` is a
provenance STRING or absent, never a domain value.

The defect: state_of_matthew_lambda stored its #1086 day/week/stage map under the key
`phase`; `tag_record` preserved any pre-set `phase`, so the provenance attribute held a
dict. `experiment.phase_filter.singleton_visible` admits only `phase` None or the current
experiment phase, so every cycle row was rejected and `/api/state_of_matthew` served
`{"available": false}` for the whole cycle (10 rows, DATE#2026-09-06 .. DATE#2026-11-08).

Three layers, each with a must-fail control. The STATIC layer (every `tag_record` caller
under lambdas/ mcp/ deploy/ scripts/ swept for a non-string-literal `"phase"` key) is a
repo-shape ratchet, so it lives in the pre-merge provenance gate
tests/test_scoped_writer_provenance_guard_3599.py beside the `stamped` class it protects.
This file holds the two behaviour layers:

  2. RUNTIME — `tag_record` itself never emits a non-string `phase`, whatever a writer
     pre-set (dict, list, number, None). Control: a string pre-set is still preserved.
  3. LIVE SHAPE — the state_of_matthew item built the way the Lambda builds it (assemble_state
     -> build_summary_item -> tag_record), with the stage map whose key set and value types
     were read (read-only, 2026-11-14) from the live DATE#2026-11-08 row, passes
     `singleton_visible` and is served `available: true` by /api/state_of_matthew. Control:
     that live row's own shape (dict under `phase`) is rejected and served unavailable.

Fixture dates derive from EXPERIMENT_START_DATE, never the wall clock (#4848).
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "compute"))
sys.path.insert(0, str(_REPO / "lambdas" / "web"))

import state_of_matthew_lambda as som  # noqa: E402
from common.compute_metadata import tag_record  # noqa: E402
from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE  # noqa: E402
from experiment.phase_filter import singleton_visible  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_common as common,  # noqa: E402
    site_api_intelligence as intel,  # noqa: E402
)

_GENESIS = date.fromisoformat(EXPERIMENT_START_DATE)
# Week 10 of the cycle — the same distance into the cycle as the live DATE#2026-11-08 row.
_RUN_DAY = (_GENESIS + timedelta(days=63)).isoformat()


# ── 2. runtime: tag_record's own invariant ──────────────────────────────────


def test_tag_record_never_emits_a_non_string_phase():
    sk = f"DATE#{_RUN_DAY}"
    bad = {
        "dict": {"days_in": Decimal(64), "stage": "x"},
        "list": ["experiment"],
        "int": 1,
        "decimal": Decimal("1"),
        "none": None,
        "bool": True,
    }
    wrong = []
    for label, value in bad.items():
        out = tag_record({"pk": "USER#matthew#SOURCE#t", "sk": sk, "phase": value}, source_id="t")
        if not isinstance(out.get("phase"), str) or out["phase"] != EXPERIMENT_PHASE_CURRENT:
            wrong.append((label, out.get("phase")))
    assert not wrong, f"tag_record let a non-string `phase` through: {wrong}"


def test_tag_record_still_preserves_a_string_preset_phase():
    """Control: the overwrite is ONLY for non-strings — a deliberate string pre-set
    (e.g. a writer stamping "pilot" itself) is preserved, as before #5931."""
    out = tag_record({"pk": "USER#matthew#SOURCE#t", "sk": f"DATE#{_RUN_DAY}", "phase": "pilot"}, source_id="t")
    assert out["phase"] == "pilot"


# ── 3. live shape: state_of_matthew through singleton_visible and the endpoint ──


def _live_stage_map() -> dict:
    """The #1086 section exactly as the live row carries it after a DDB round trip
    (numbers come back Decimal). Key set + value types read from DATE#2026-11-08."""
    return {
        "pre_start": False,
        "days_until_start": Decimal(0),
        "start_date": EXPERIMENT_START_DATE,
        "as_of": _RUN_DAY,
        "days_in": Decimal(64),
        "week_num": Decimal(10),
        "stage": "foundation",
    }


def _built_item() -> dict:
    state = som.assemble_state(None, None, None, None, _RUN_DAY)
    narration = {"narrative": "A quiet week.", "narrated": False, "model": "m"}
    return som.build_summary_item(state, narration, _RUN_DAY)


def _pre_fix_live_row() -> dict:
    """The live row's shape before #5931: the stage map under `phase`, stamped by the
    old tag_record which preserved it. Never passed through the fixed tagger."""
    item = _built_item()
    item.pop("phase_context", None)
    item["phase"] = _live_stage_map()
    return item


def _serve(monkeypatch, row) -> dict:
    start = (datetime.now(common.PT).date() - timedelta(days=30)).isoformat()
    for mod in (common, intel):
        monkeypatch.setattr(mod, "EXPERIMENT_START", start, raising=False)
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[row]))
    resp = intel.handle_state_of_matthew()
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def test_state_of_matthew_item_is_visible_and_served(monkeypatch):
    item = _built_item()
    assert isinstance(item["phase"], str) and item["phase"] == EXPERIMENT_PHASE_CURRENT
    assert set(item["phase_context"]) == set(_live_stage_map())
    assert singleton_visible(item)
    body = _serve(monkeypatch, item)
    assert body["available"] is True
    assert "phase" not in body  # _INTERNAL still strips the provenance tag
    assert body["phase_context"]["week_num"] == 10


def test_pre_fix_live_shape_is_rejected_and_the_fixed_tagger_rescues_it(monkeypatch):
    """Must-fail control: the live row's shape is invisible and served unavailable —
    the exact #5931 symptom. Re-tagging it with the fixed tag_record makes it visible."""
    row = _pre_fix_live_row()
    assert not singleton_visible(row)
    assert _serve(monkeypatch, row)["available"] is False
    retagged = tag_record(dict(row), source_id="state_of_matthew")
    assert retagged["phase"] == EXPERIMENT_PHASE_CURRENT
    assert singleton_visible(retagged)
