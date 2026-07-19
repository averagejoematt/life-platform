"""tests/test_data_governance_retention_coverage.py — #1350 retention-row guard.

Extends the pii_surface_guard pattern inward (see docs/DATA_GOVERNANCE.md's own
"Scope note: the PII guard vs the repo itself"): every DDB partition holding PII
belonging to someone OTHER than Matthew must have a matching row in
docs/DATA_GOVERNANCE.md's retention table — either a SIGNED row (names a window the
purge code can read) or the explicit UNSIGNED marker while the decision is pending.

Registry: scripts/data_governance_registry.py::NON_OWNER_PII_PARTITIONS — the ONE
place a new non-owner-PII partition must be declared (mirrors phase_taxonomy's
SOURCE_CLASS pattern).

Today: "subscribers" is UNSIGNED (#1350, [gate:owner]) — these tests PASS on the
template row as written. They go RED the moment someone:
  - deletes the row entirely (test_every_non_owner_pii_partition_has_a_retention_row), or
  - "signs" it (removes the UNSIGNED marker) without naming a day-count window
    (test_unsigned_or_signed_with_a_readable_window) — a signed row must be
    actionable by deploy/subscriber_retention_purge.py, not just prose.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from data_governance_registry import NON_OWNER_PII_PARTITIONS  # noqa: E402

DOC = ROOT / "docs" / "DATA_GOVERNANCE.md"


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_registry_is_non_empty():
    """Non-vacuity: the registry must actually name something, or every check below
    passes on zero iterations and proves nothing."""
    assert NON_OWNER_PII_PARTITIONS, "NON_OWNER_PII_PARTITIONS is empty — the guard has nothing to guard"


def test_every_non_owner_pii_partition_has_a_retention_row():
    text = _doc_text()
    for key, meta in NON_OWNER_PII_PARTITIONS.items():
        label = meta["doc_label"]
        assert label in text, (
            f"{key!r} (non-owner PII, pk={meta['pk_pattern']}) has no retention row in "
            f"docs/DATA_GOVERNANCE.md — every partition in NON_OWNER_PII_PARTITIONS needs "
            f"one (a signed window row, or the explicit UNSIGNED marker while pending; "
            f"{meta['issue']})."
        )


def test_unsigned_or_signed_with_a_readable_window():
    """A retention row must be actionable: either explicitly UNSIGNED, or it names a
    day-count window the purge script can actually read (not silently unenforceable
    prose)."""
    text = _doc_text()
    for key, meta in NON_OWNER_PII_PARTITIONS.items():
        label = meta["doc_label"]
        row_lines = [line for line in text.splitlines() if label in line]
        assert row_lines, f"{key!r} row vanished between the two guard tests (flaky read?)"
        row = row_lines[0]
        if "UNSIGNED" in row:
            continue  # pending decision — explicitly marked, not a silent gap
        assert re.search(r"\b\d+\s*-?\s*days?\b", row, re.I), (
            f"{key!r} retention row is marked signed (no UNSIGNED marker) but names no "
            f"day-count window for {meta['runner']} to read — a signed row must be "
            f"actionable, not just prose ({meta['issue']})."
        )


def test_guard_is_not_vacuous_on_a_planted_gap():
    """The two checks above must actually FIRE on a planted violation — proves this
    isn't a scan that passes on anything (the #1189 vacuous-scan lesson)."""
    fake_registry = {
        "ghost_partition": {
            "pk_pattern": "USER#nobody#SOURCE#ghost",
            "doc_label": "Ghost Partition That Does Not Exist In The Doc",
            "owner_module": "nowhere.py",
            "runner": "nowhere_runner.py",
            "issue": "#0",
        }
    }
    text = _doc_text()
    label = fake_registry["ghost_partition"]["doc_label"]
    assert label not in text, "the fake label accidentally collided with real doc text"

    # replays test_every_non_owner_pii_partition_has_a_retention_row's assertion logic
    # against the fake registry — must fail (proving the real test isn't vacuous).
    missing = [k for k, meta in fake_registry.items() if meta["doc_label"] not in text]
    assert missing == ["ghost_partition"], "planted gap was not detected — guard is vacuous"

    # a row present but with neither UNSIGNED nor a day-count window — must also flag.
    unreadable_row = "| **Ghost Partition That Does Not Exist In The Doc** | some pk | signed, forever, no window named at all |"
    assert "UNSIGNED" not in unreadable_row
    assert not re.search(r"\b\d+\s*-?\s*days?\b", unreadable_row, re.I), "planted unreadable row accidentally names a window"
