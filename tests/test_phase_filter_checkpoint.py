"""tests/test_phase_filter_checkpoint.py — ADR-058 §13 checkpoint mechanism (#383).

Covers the date arithmetic (checkpoints derive from EXPERIMENT_START_DATE, not a
fixed calendar date), the due/upcoming/recorded status machine, the record
guard-rails (no recording before the due date, no silent double-record), and
the static include_pilot=True diagnostic scan. Tests never touch the real
docs/reviews/PHASE_FILTER_CHECKPOINTS.{json,md} audit trail — STATE_PATH/
NARRATIVE_PATH are monkeypatched to a tmp_path for every test that writes.
"""

from __future__ import annotations

import importlib
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

pfc = importlib.import_module("phase_filter_checkpoint")


@pytest.fixture(autouse=True)
def isolated_audit_trail(tmp_path, monkeypatch):
    """Redirect the audit trail to a scratch dir so tests never write to docs/reviews/."""
    monkeypatch.setattr(pfc, "STATE_PATH", tmp_path / "PHASE_FILTER_CHECKPOINTS.json")
    monkeypatch.setattr(pfc, "NARRATIVE_PATH", tmp_path / "PHASE_FILTER_CHECKPOINTS.md")
    yield


def test_genesis_date_matches_constants():
    from lambdas.constants import EXPERIMENT_START_DATE

    assert pfc.genesis_date() == date.fromisoformat(EXPERIMENT_START_DATE)


def test_checkpoint_due_dates_derive_from_genesis():
    genesis = date(2026, 6, 14)
    assert pfc.checkpoint_due_date(genesis, 30) == date(2026, 7, 14)
    assert pfc.checkpoint_due_date(genesis, 60) == date(2026, 8, 13)
    assert pfc.checkpoint_due_date(genesis, 90) == date(2026, 9, 12)


def test_status_before_any_checkpoint_is_all_upcoming():
    genesis = pfc.genesis_date()
    today = genesis  # day 0
    result = pfc.build_status(today)
    assert result["days_elapsed"] == 0
    assert all(row["status"] == "upcoming" for row in result["checkpoints"])
    assert result["next_actionable_checkpoint"] is None
    assert "diagnostic_snapshot" not in result


def test_status_on_due_date_is_due_with_diagnostic_snapshot():
    genesis = pfc.genesis_date()
    due_30 = pfc.checkpoint_due_date(genesis, 30)
    result = pfc.build_status(due_30)
    rows = {row["checkpoint_days"]: row for row in result["checkpoints"]}
    assert rows[30]["status"] == "due"
    assert rows[60]["status"] == "upcoming"
    assert result["next_actionable_checkpoint"] == 30
    assert "diagnostic_snapshot" in result
    assert result["diagnostic_snapshot"]["include_pilot_true_call_site_count"] >= 1


def test_status_past_due_date_stays_due_until_recorded():
    genesis = pfc.genesis_date()
    due_30 = pfc.checkpoint_due_date(genesis, 30)
    well_past = date.fromordinal(due_30.toordinal() + 5)
    result = pfc.build_status(well_past)
    rows = {row["checkpoint_days"]: row for row in result["checkpoints"]}
    assert rows[30]["status"] == "due"


def test_record_before_due_date_is_rejected(capsys):
    genesis = pfc.genesis_date()
    before_due = date.fromordinal(pfc.checkpoint_due_date(genesis, 30).toordinal() - 1)
    args = _record_args(checkpoint=30, verdict="keep-as-is", notes="too early", today=before_due)
    rc = pfc.cmd_record(args)
    assert rc == 1
    assert not pfc.STATE_PATH.exists()
    err = capsys.readouterr().err
    assert "not due until" in err


def test_record_on_due_date_succeeds_and_persists():
    genesis = pfc.genesis_date()
    due_30 = pfc.checkpoint_due_date(genesis, 30)
    args = _record_args(checkpoint=30, verdict="keep-as-is", notes="no change needed", today=due_30)
    rc = pfc.cmd_record(args)
    assert rc == 0
    assert pfc.STATE_PATH.exists()
    assert pfc.NARRATIVE_PATH.exists()

    state = pfc.load_state()
    recorded = pfc.recorded_checkpoints(state)
    assert 30 in recorded
    assert recorded[30]["verdict"] == "keep-as-is"
    assert recorded[30]["reviewer"] == "matthew"

    narrative = pfc.NARRATIVE_PATH.read_text()
    assert "30-day checkpoint" in narrative
    assert "keep-as-is" in narrative


def test_recording_re_arms_the_next_checkpoint_not_lapse():
    genesis = pfc.genesis_date()
    due_30 = pfc.checkpoint_due_date(genesis, 30)
    args = _record_args(checkpoint=30, verdict="keep-as-is", notes="fine", today=due_30)
    pfc.cmd_record(args)

    # After recording 30, the 60/90 checkpoints must still be visible/pending, not dropped.
    result = pfc.build_status(due_30)
    rows = {row["checkpoint_days"]: row for row in result["checkpoints"]}
    assert rows[30]["status"] == "recorded"
    assert rows[60]["status"] == "upcoming"
    assert rows[90]["status"] == "upcoming"


def test_double_record_without_force_is_rejected(capsys):
    genesis = pfc.genesis_date()
    due_30 = pfc.checkpoint_due_date(genesis, 30)
    pfc.cmd_record(_record_args(checkpoint=30, verdict="keep-as-is", notes="first pass", today=due_30))
    rc = pfc.cmd_record(_record_args(checkpoint=30, verdict="widen-read-paths", notes="second pass", today=due_30))
    assert rc == 1
    err = capsys.readouterr().err
    assert "already recorded" in err

    state = pfc.load_state()
    assert pfc.recorded_checkpoints(state)[30]["verdict"] == "keep-as-is"  # unchanged


def test_double_record_with_force_overwrites():
    genesis = pfc.genesis_date()
    due_30 = pfc.checkpoint_due_date(genesis, 30)
    pfc.cmd_record(_record_args(checkpoint=30, verdict="keep-as-is", notes="first pass", today=due_30))
    rc = pfc.cmd_record(_record_args(checkpoint=30, verdict="widen-read-paths", notes="revised", today=due_30, force=True))
    assert rc == 0
    state = pfc.load_state()
    assert pfc.recorded_checkpoints(state)[30]["verdict"] == "widen-read-paths"


def test_scan_include_pilot_bypasses_finds_known_site():
    sites = pfc.scan_include_pilot_bypasses()
    files = {s.file for s in sites}
    assert any("mcp/tools_benchmark.py" == f or f.endswith("tools_benchmark.py") for f in files)
    # phase_filter.py itself defines include_pilot as a parameter, never `= True` — must be excluded.
    assert not any(f.endswith("phase_filter.py") for f in files)


def test_diagnostic_snapshot_reports_scoped_sources():
    snap = pfc.diagnostic_snapshot()
    assert "computed_metrics" in snap["experiment_scoped_sources"]
    assert "labs" in snap["cross_phase_sources"]


def _record_args(*, checkpoint, verdict, notes, today, reviewer="matthew", force=False):
    class _Args:
        pass

    a = _Args()
    a.checkpoint = checkpoint
    a.verdict = verdict
    a.notes = notes
    a.reviewer = reviewer
    a.force = force
    a.today = today.isoformat()
    return a
