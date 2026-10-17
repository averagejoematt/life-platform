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


# ══ #4632 — the vendor habit id, the id-keyed supplements bridge, the drift check ══════
#
# The ruling-free half of #4632. Rename-keeps-streak and un-tick downgrade semantics are
# HELD on #4644 Q26/Q27 and deliberately not exercised here.

SUPP = next(iter(habitify_lambda.SUPPLEMENT_MAP))  # a real bridge key, read from the code
SUPP_ID = "hid-supp-1"


def _journal_entry(name, hid, status="completed"):
    return {"id": hid, "name": name, "status": status, "goal": {"periodicity": "daily", "value": 1}, "progress": {}}


def test_every_per_day_status_entry_carries_the_vendor_habit_id(monkeypatch):
    """Additive: the map stays name-keyed (legacy readers), and each entry gains `habit_id`."""
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-10-05")
    raw = {
        "area_map": {},
        "journal": [_journal_entry("Floss", "hid-floss"), _journal_entry(SUPP, SUPP_ID, "failed"), {"name": "No Id", "status": "skipped"}],
        "moods": [],
    }
    rec = habitify_lambda.transform(raw, DAY)[0]
    hs = rec["habit_statuses"]
    assert hs["Floss"]["habit_id"] == "hid-floss"
    assert hs[SUPP]["habit_id"] == SUPP_ID
    assert "habit_id" not in hs["No Id"]  # never invented
    assert set(rec["habits"]) == {"Floss", SUPP, "No Id"}  # legacy name-keyed map unchanged


class _SuppTable:
    """A supplements row + the profile row; records puts and deletes."""

    def __init__(self, supplements=None, registry=None):
        self.row = {"supplements": list(supplements)} if supplements is not None else None
        self.registry = registry or {}
        self.puts, self.deletes = [], []

    def get_item(self, Key=None, **kw):  # noqa: N803
        if Key.get("sk") == "PROFILE#v1":
            return {"Item": {"habit_registry": self.registry}}
        return {"Item": self.row} if self.row is not None else {}

    def put_item(self, Item=None, **kw):  # noqa: N803
        self.puts.append(Item)
        self.row = Item

    def delete_item(self, Key=None, **kw):  # noqa: N803
        self.deletes.append(Key)
        self.row = None


def _bridge(monkeypatch, table, statuses):
    monkeypatch.setattr(habitify_lambda, "_table", table)
    monkeypatch.setattr(habitify_lambda, "_ALIAS_GROUPS_CACHE", None)
    habitify_lambda.supplement_bridge([_record(statuses)], DAY)


def test_the_bridge_keys_its_entries_on_the_habit_id(monkeypatch):
    table = _SuppTable()
    _bridge(monkeypatch, table, {SUPP: {"status": "completed", "habit_id": SUPP_ID, "group": "Core"}})
    (entry,) = table.puts[-1]["supplements"]
    assert entry["habit_id"] == SUPP_ID and entry["source"] == "habitify_bridge"
    # A same-day rename (same id, a name the code map does not know) stays the same supplement.
    _bridge(monkeypatch, table, {"Renamed In App": {"status": "completed", "habit_id": SUPP_ID, "group": "Core"}})
    (entry2,) = table.puts[-1]["supplements"]
    assert entry2["habit_id"] == SUPP_ID and entry2["dose"] == entry["dose"]
    assert entry2["logged_at"] == entry["logged_at"]  # the same entry, not a new one


def test_un_ticking_the_last_supplement_habit_of_a_day_retracts_the_stored_entry(monkeypatch):
    """The acceptance box: the completion is withdrawn and the stored entry is gone."""
    table = _SuppTable()
    _bridge(monkeypatch, table, {SUPP: {"status": "completed", "habit_id": SUPP_ID, "group": "Core"}})
    assert table.row and len(table.row["supplements"]) == 1
    _bridge(monkeypatch, table, {SUPP: {"status": "failed", "miss_source": "vendor", "habit_id": SUPP_ID, "group": "Core"}})
    assert table.row is None, "the withdrawn completion's bridge entry survived — no retraction"
    assert table.deletes == [{"pk": habitify_lambda._SUPPLEMENTS_PK, "sk": f"DATE#{DAY}"}]


def test_a_retraction_keeps_the_days_manual_entries(monkeypatch):
    manual = {"name": "Manual Log", "dose": 1, "unit": "x", "source": "mcp"}
    bridged = {"name": SUPP, "habit_id": SUPP_ID, "dose": 1, "unit": "x", "timing": "t", "category": "c", "source": "habitify_bridge"}
    table = _SuppTable(supplements=[manual, bridged])
    _bridge(monkeypatch, table, {SUPP: {"status": "pending", "habit_id": SUPP_ID, "group": "Core"}})
    assert table.deletes == []
    assert table.puts[-1]["supplements"] == [manual]


def test_no_completions_and_nothing_bridged_writes_nothing(monkeypatch):
    table = _SuppTable(supplements=[{"name": "Manual Log", "source": "mcp"}])
    _bridge(monkeypatch, table, {SUPP: {"status": "pending", "habit_id": SUPP_ID, "group": "Core"}})
    assert table.puts == [] and table.deletes == []


def test_a_record_with_no_habit_map_never_retracts(monkeypatch):
    bridged = {"name": SUPP, "habit_id": SUPP_ID, "source": "habitify_bridge"}
    table = _SuppTable(supplements=[bridged])
    monkeypatch.setattr(habitify_lambda, "_table", table)
    habitify_lambda.supplement_bridge([{"date": DAY}], DAY)
    assert table.puts == [] and table.deletes == []


def test_a_failed_read_before_merge_never_retracts(monkeypatch):
    """read_ok=False: the stored row is unknown, so a day with no completions must write and delete nothing."""

    class _Unreadable(_SuppTable):
        def get_item(self, Key=None, **kw):  # noqa: N803
            if Key.get("sk") == "PROFILE#v1":
                return super().get_item(Key=Key)
            raise RuntimeError("throttled")

    bridged = {"name": SUPP, "habit_id": SUPP_ID, "source": "habitify_bridge"}
    table = _Unreadable(supplements=[bridged])
    _bridge(monkeypatch, table, {SUPP: {"status": "failed", "miss_source": "vendor", "habit_id": SUPP_ID, "group": "Core"}})
    assert table.puts == [] and table.deletes == []
    assert table.row == {"supplements": [bridged]}


def test_the_bridge_resolves_a_registry_alias_of_a_supplement_key(monkeypatch):
    table = _SuppTable(registry={SUPP: {"tier": 2, "habitify_names": [SUPP, "Supp New Name"]}})
    _bridge(monkeypatch, table, {"Supp New Name": {"status": "completed", "habit_id": SUPP_ID, "group": "Core"}})
    assert [e["name"] for e in table.puts[-1]["supplements"]] == ["Supp New Name"]


# ── the drift check (scripts/check_habit_registry_drift.py), fixture-driven ──────────

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import check_habit_registry_drift as drift  # noqa: E402


def _fixture(tmp_path, live, registry, bridge):
    p = tmp_path / "habit_drift_4632.json"
    p.write_text(__import__("json").dumps({"journal": [{"name": n} for n in live], "habit_registry": registry, "bridge_keys": bridge}))
    return str(p)


def test_the_drift_check_passes_on_an_aligned_fixture_and_prints_counts_only(tmp_path, capsys):
    reg = {NEW: {"habitify_names": [OLD, NEW]}, "Floss": {}, "Fish Oil": {}}
    path = _fixture(tmp_path, [NEW, "Floss", "Fish Oil"], reg, ["Fish Oil"])
    assert drift.main(["--fixture", path]) == 0
    out = capsys.readouterr().out
    assert "HABIT-REGISTRY-DRIFT: OK" in out
    for name in (NEW, OLD, "Floss", "Fish Oil"):
        assert name not in out, "a habit name reached the drift check's output"


def test_the_drift_check_fails_on_each_kind_of_orphan(tmp_path):
    reg = {NEW: {"habitify_names": [OLD, NEW]}, "Floss": {}, "Gone Habit": {}}
    live = [NEW, "Floss", "Unregistered Habit"]
    counts = drift.drift_counts(set(live), reg, ["Floss", "Gone Supp", OLD])
    assert counts["live_without_registry"] == 1
    assert counts["registry_without_live"] == 1
    assert counts["bridge_without_live"] == 1  # OLD resolves through its live alias; Gone Supp does not
    assert drift.main(["--fixture", _fixture(tmp_path, live, reg, ["Floss"])]) == 1
