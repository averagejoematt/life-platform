"""#4655 — re-ingesting a day stored before a Habitify rename must not double-count the habit.

`upgrade_only_merge` restores a stored terminal habit that is missing from the new journal
("vanished upstream"). After a rename the old name IS missing but the habit is not gone —
it arrives under the new name — so the merged day held both rows and both counted
(observed live on DATE#2026-09-24: 62 rows instead of 61). The vanished branch now resolves
the stored name through the registry's `habitify_names` aliases (the same resolution
`scoring_engine.habitify_reading` uses, #4362) and drops the old-name row when an alias is
present. Also: the `[UPGRADE-ONLY]` log line carries counts and transitions, never names.

Run:  python3 -m pytest tests/test_habitify_rename_alias_merge_4655.py -v
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

# The real ingestion_framework (no sys.modules shim — a shim installed here would leak into
# test_now_remainder_batch.py, which asserts on the real IngestionConfig). It reads these at
# config build time; same setdefaults as that file.
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import habitify_lambda  # noqa: E402
from habitify_lambda import _aggregate, alias_groups_from_registry, upgrade_only_merge  # noqa: E402

DAY = "2026-09-24"
GROUPS = {"Core", "Recovery"}
OLD = "Nighttime Red Light Blocking Glasses"
NEW = "Red-Light Glasses (Night)"
REGISTRY = {
    NEW: {"tier": 1, "habitify_names": [OLD, NEW]},
    "Floss": {"tier": 2},
}


def _record(statuses: dict) -> dict:
    rec = {"date": DAY, "habit_statuses": statuses}
    rec.update(_aggregate(statuses, GROUPS))
    return rec


def _setup(monkeypatch, registry=REGISTRY):
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-10-05")
    monkeypatch.setattr(habitify_lambda, "_ALIAS_GROUPS_CACHE", alias_groups_from_registry(registry))


class _RecordingLogger:
    """The module logs through platform_logger (JSON to stdout), so record the call itself."""

    def __init__(self):
        self.lines = []

    def _log(self, msg, *args, **kw):
        self.lines.append(msg % args if args else msg)

    info = warning = error = debug = _log


def test_a_renamed_habit_is_one_row_and_a_genuinely_vanished_one_is_still_restored(monkeypatch):
    _setup(monkeypatch)
    rec_logger = _RecordingLogger()
    monkeypatch.setattr(habitify_lambda, "logger", rec_logger)
    stored = _record(
        {
            OLD: {"status": "completed", "group": "Recovery", "completed_at": "2026-09-25T05:00:00Z"},
            "Floss": {"status": "completed", "group": "Core"},
            "Retired Habit": {"status": "completed", "group": "Core"},
        }
    )
    later = _record(
        {
            NEW: {"status": "completed", "group": "Recovery"},
            "Floss": {"status": "completed", "group": "Core"},
        }
    )
    merged = upgrade_only_merge(stored, later)
    hs = merged["habit_statuses"]
    # The rename: exactly one row for the habit, under its new name.
    assert OLD not in hs
    assert hs[NEW]["status"] == "completed"
    # The genuinely vanished habit (no live alias) is still restored.
    assert hs["Retired Habit"]["status"] == "completed"
    assert sorted(hs) == sorted([NEW, "Floss", "Retired Habit"])
    assert merged["total_possible"] == 3
    assert merged["total_completed"] == 3

    # The log line carries counts and transitions by status only — never a habit name.
    lines = [line for line in rec_logger.lines if "[UPGRADE-ONLY]" in line]
    assert lines, "expected an [UPGRADE-ONLY] log line"
    for line in lines:
        for name in (OLD, NEW, "Floss", "Retired Habit"):
            assert name not in line, f"habit name {name!r} leaked into the log: {line}"
    assert "restored-completed x1" in lines[-1]


def test_rename_alone_leaves_totals_unchanged(monkeypatch):
    _setup(monkeypatch)
    stored = _record({OLD: {"status": "completed", "group": "Recovery"}, "Floss": {"status": "completed", "group": "Core"}})
    later = _record({NEW: {"status": "completed", "group": "Recovery"}, "Floss": {"status": "completed", "group": "Core"}})
    before = (later["total_possible"], later["total_completed"])
    merged = upgrade_only_merge(stored, later)
    assert list(merged["habit_statuses"]) == [NEW, "Floss"]
    assert (merged["total_possible"], merged["total_completed"]) == before == (2, 2)


def test_the_old_names_decision_holds_over_a_weaker_new_name_row(monkeypatch):
    """Upgrade-only still holds across a rename: a stored completion beats a platform miss."""
    _setup(monkeypatch)
    stored = _record({OLD: {"status": "completed", "group": "Recovery", "completed_at": "2026-09-25T05:00:00Z"}})
    later = _record({NEW: {"status": "failed", "miss_source": "platform", "group": "Recovery"}})
    merged = upgrade_only_merge(stored, later)
    hs = merged["habit_statuses"]
    assert OLD not in hs
    assert hs[NEW]["status"] == "completed"
    assert hs[NEW]["completed_at"] == "2026-09-25T05:00:00Z"
    assert "miss_source" not in hs[NEW]
    assert merged["total_possible"] == 1 and merged["total_completed"] == 1


def test_an_already_double_counted_day_heals_on_re_ingest(monkeypatch):
    """The live 09-24 shape: the stored day already holds BOTH names; a re-ingest yields one."""
    _setup(monkeypatch)
    stored = _record({OLD: {"status": "completed", "group": "Recovery"}, NEW: {"status": "completed", "group": "Recovery"}})
    assert stored["total_possible"] == 2
    later = _record({NEW: {"status": "completed", "group": "Recovery"}})
    merged = upgrade_only_merge(stored, later)
    assert list(merged["habit_statuses"]) == [NEW]
    assert merged["total_possible"] == 1


def test_an_unreadable_registry_falls_back_to_restoring(monkeypatch):
    """Fail-soft: no aliases means the pre-#4655 behaviour, never a dropped decision."""
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-10-05")
    monkeypatch.setattr(habitify_lambda, "_ALIAS_GROUPS_CACHE", None)

    class _Boom:
        def get_item(self, **kw):
            raise RuntimeError("no table")

    monkeypatch.setattr(habitify_lambda, "_table", _Boom())
    stored = _record({OLD: {"status": "completed", "group": "Recovery"}})
    later = _record({NEW: {"status": "completed", "group": "Recovery"}})
    merged = upgrade_only_merge(stored, later)
    assert OLD in merged["habit_statuses"]


def test_the_registry_is_read_from_the_canonical_profile_row(monkeypatch):
    monkeypatch.setattr(habitify_lambda, "_ALIAS_GROUPS_CACHE", None)
    seen = {}

    class _Table:
        def get_item(self, Key=None, **kw):
            seen["key"] = Key
            return {"Item": {"habit_registry": REGISTRY}}

    monkeypatch.setattr(habitify_lambda, "_table", _Table())
    groups = habitify_lambda._habit_alias_groups()
    assert seen["key"] == {"pk": f"USER#{habitify_lambda.USER_ID}", "sk": "PROFILE#v1"}
    assert groups == [frozenset({OLD, NEW})]  # singletons (no rename) are not alias groups
