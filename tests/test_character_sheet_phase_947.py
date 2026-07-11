"""tests/test_character_sheet_phase_947.py — #947: pre-genesis pilot records
must not chain into Day-1 character compute.

`fetch_range` applies `with_phase_filter` (ADR-058: allow
`phase == EXPERIMENT_PHASE_CURRENT` or no phase attribute), but `fetch_date`
went through a bare get_item with only a tombstone check — so
`load_previous_state`'s 7-day back-scan happily returned the phase='pilot'
character_sheet records the pre-genesis countdown cron writes, chaining pilot
xp_debt/streaks/mood into genesis Day 1 regardless of when the Sunday
pipeline re-run tombstones them (the 16:30 UTC cron re-creates the pilot
record for yesterday either way).

These tests prove:
  1. fetch_date skips phase='pilot' records (mirroring with_phase_filter),
  2. fetch_date still passes untagged and current-phase records,
  3. fetch_date still honors the tombstone check,
  4. load_previous_state on genesis day, with ONLY pilot records in the
     7-day back-scan window, returns None — a genuine level-1 cold start.

All offline — the module-level boto3 table is monkeypatched with the shared
FakeDdbTable (get_item serves from its (pk, sk)-keyed store).
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "compute"))

os.environ.setdefault("S3_BUCKET", "test-bucket")

import character_sheet_lambda as csl  # noqa: E402
from constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

CHAR_PK = "USER#matthew#SOURCE#character_sheet"

# Genesis Day-1 compute target = EXPERIMENT_START_DATE itself (the Monday cron
# computes yesterday=genesis); its back-scan window is the 7 pre-genesis days.
GENESIS = EXPERIMENT_START_DATE


def _pilot_sheet(date_str, **extra):
    """A pre-genesis countdown character_sheet record, as the cron writes it
    (character_engine.store_character_sheet stamps phase='pilot' on
    pre-genesis dates)."""
    row = {
        "pk": CHAR_PK,
        "sk": "DATE#" + date_str,
        "date": date_str,
        "phase": "pilot",
        "character_level": 1,
        "character_tier": "Foundation",
        "xp_debt": 3.57,
        "character_mood": "dormant",
    }
    row.update(extra)
    return row


def _dates_before(anchor, days):
    dt = datetime.strptime(anchor, "%Y-%m-%d")
    return [(dt - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, days + 1)]


def _install(monkeypatch, rows):
    fake = FakeDdbTable(rows=rows)
    monkeypatch.setattr(csl, "table", fake)
    return fake


# ── fetch_date phase semantics (mirror with_phase_filter) ────────────────────


def test_fetch_date_skips_pilot_record(monkeypatch):
    day = _dates_before(GENESIS, 1)[0]
    _install(monkeypatch, [_pilot_sheet(day)])
    assert csl.fetch_date("character_sheet", day) is None


def test_fetch_date_passes_current_phase_record(monkeypatch):
    _install(
        monkeypatch,
        [
            {
                "pk": CHAR_PK,
                "sk": "DATE#" + GENESIS,
                "date": GENESIS,
                "phase": EXPERIMENT_PHASE_CURRENT,
                "character_level": 1,
            }
        ],
    )
    rec = csl.fetch_date("character_sheet", GENESIS)
    assert rec is not None
    assert rec["character_level"] == 1


def test_fetch_date_passes_untagged_record(monkeypatch):
    # Records without a phase attribute pass, exactly like
    # with_phase_filter's attribute_not_exists(#phase) branch.
    _install(
        monkeypatch,
        [{"pk": CHAR_PK, "sk": "DATE#" + GENESIS, "date": GENESIS, "character_level": 2}],
    )
    rec = csl.fetch_date("character_sheet", GENESIS)
    assert rec is not None
    assert rec["character_level"] == 2


def test_fetch_date_still_skips_tombstoned_record(monkeypatch):
    _install(
        monkeypatch,
        [
            {
                "pk": CHAR_PK,
                "sk": "DATE#" + GENESIS,
                "date": GENESIS,
                "phase": EXPERIMENT_PHASE_CURRENT,
                "tombstone": True,
                "character_level": 8,
            }
        ],
    )
    assert csl.fetch_date("character_sheet", GENESIS) is None


# ── load_previous_state: genesis-day cold start ──────────────────────────────


def test_load_previous_state_genesis_day_only_pilot_records_cold_start(monkeypatch):
    """The #947 regression: the full 7-day back-scan window holds only
    phase='pilot' countdown records — Day 1 must be a cold start (None), not
    inherit pilot xp_debt/dormant mood/streaks."""
    rows = [_pilot_sheet(d) for d in _dates_before(GENESIS, 7)]
    _install(monkeypatch, rows)
    assert csl.load_previous_state(GENESIS) is None


def test_load_previous_state_skips_pilot_but_finds_current_phase(monkeypatch):
    """Continuity within the current phase is preserved: a pilot record on the
    nearest day must be skipped, and an older current-phase record found."""
    days = _dates_before(GENESIS, 7)
    rows = [_pilot_sheet(days[0])]
    rows.append(
        {
            "pk": CHAR_PK,
            "sk": "DATE#" + days[2],
            "date": days[2],
            "phase": EXPERIMENT_PHASE_CURRENT,
            "character_level": 3,
        }
    )
    _install(monkeypatch, rows)
    state = csl.load_previous_state(GENESIS)
    assert state is not None
    assert state["date"] == days[2]
    assert state["character_level"] == 3
