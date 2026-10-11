"""#4635 — a vendor flag or enum is stored with the vendor's meaning.

Two sources, one class. Both fixtures are built from archived raw payloads (the
framework's archived `fetch_day` envelope) with the vendor's key structure intact;
see each fixture's `_provenance` for what was blanked for a public repo.

Eight Sleep: the day entry's `incomplete` / `processing` / `lagMinutes` were never
read. The fixture is ONE night as the vendor sent it on two consecutive evenings —
flagged the first time, unflagged the second with the same durations and a revised
score. The contract: the writer stores the night as sent and labels it; it does not
drop the night, alter its numbers, or store a missing flag as False.

Todoist: API priority is 1 = normal … 4 = urgent (the app's p1 is API 4). The
writer stores the count per API integer and derives the p1..p4 view from it; the
MCP reader corrects rows stored before the fix, whose labels were mirrored; the
MCP create tool no longer defaults to the vendor's most urgent level.

Every expected number below is counted by hand from the fixture, never captured
from the code's output.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from decimal import Decimal
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "deploy"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import repair_vendor_flags_4635 as repair  # noqa: E402
from common.numeric import floats_to_decimal  # noqa: E402
from ingestion import eightsleep_lambda as es, todoist_lambda as td  # noqa: E402

import mcp.tools_todoist as tt  # noqa: E402
from mcp import handler as h  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


ES = _load("eightsleep_wire_4635.json")
TD = _load("todoist_wire_4635.json")
NIGHT = "2026-09-09"  # the one night both Eight Sleep fetches carry


def _es_record(fetch, date=NIGHT):
    out = es.transform(copy.deepcopy(ES[fetch]["raw"]), date)
    assert len(out) == 1, out
    return out[0]


# ── Eight Sleep ───────────────────────────────────────────────────────────────


def test_the_fixture_is_one_night_sent_twice_flagged_then_unflagged():
    """Guards the premise: if the fixture stops saying this, the tests below prove nothing."""

    def day(fetch):
        return next(d for d in ES[fetch]["raw"]["trends"]["days"] if d["day"] == NIGHT)

    first, second = day("flagged_fetch"), day("next_day_fetch")
    assert (first["incomplete"], first["processing"], first["lagMinutes"]) == (True, True, 2.50325)
    assert second["incomplete"] is False and "processing" not in second and "lagMinutes" not in second
    assert first["sleepDuration"] == second["sleepDuration"] == 24240
    assert (first["score"], second["score"]) == (85, 78)


def test_a_flagged_night_is_stored_as_sent_and_labelled():
    rec = _es_record("flagged_fetch")
    assert rec["vendor_incomplete"] is True
    assert rec["vendor_processing"] is True
    assert rec["vendor_lag_minutes"] == 2.50325  # as sent — not rounded
    # Not dropped, not altered: 24240 s / 3600 = 6.7333… → 6.73 h; score as sent.
    assert rec["sleep_duration_hours"] == 6.73
    assert rec["sleep_score"] == 85.0
    assert rec["date"] == NIGHT and rec["source"] == "eightsleep"


def test_an_unflagged_night_stores_false_and_no_flag_the_vendor_did_not_send():
    rec = _es_record("next_day_fetch")
    assert rec["vendor_incomplete"] is False
    assert "vendor_processing" not in rec and "vendor_lag_minutes" not in rec
    assert rec["sleep_duration_hours"] == 6.73
    assert rec["sleep_score"] == 78.0


def test_the_flag_changes_no_other_stored_field():
    """Same night, flag flipped on the wire → every non-flag field is byte-identical."""
    raw = copy.deepcopy(ES["flagged_fetch"]["raw"])
    flagged = es.transform(copy.deepcopy(raw), NIGHT)[0]
    for d in raw["trends"]["days"]:
        if d["day"] == NIGHT:
            d["incomplete"] = False
            del d["processing"], d["lagMinutes"]
    plain = es.transform(raw, NIGHT)[0]
    flags = {"vendor_incomplete", "vendor_processing", "vendor_lag_minutes"}
    assert {k: v for k, v in flagged.items() if k not in flags} == {k: v for k, v in plain.items() if k not in flags}


def test_a_missing_or_non_boolean_flag_is_absent_never_false():
    for bad in ("absent", None, "true", 1, 0):
        raw = copy.deepcopy(ES["flagged_fetch"]["raw"])
        for d in raw["trends"]["days"]:
            if d["day"] == NIGHT:
                if bad == "absent":
                    del d["incomplete"]
                else:
                    d["incomplete"] = bad
        rec = es.transform(raw, NIGHT)[0]
        assert "vendor_incomplete" not in rec, (bad, rec.get("vendor_incomplete"))


def test_the_flags_survive_the_decimal_cast_as_booleans():
    stored = floats_to_decimal(_es_record("flagged_fetch"))
    assert stored["vendor_incomplete"] is True and stored["vendor_processing"] is True
    assert stored["vendor_lag_minutes"] == Decimal("2.50325")


def test_the_flag_fields_are_documented_where_the_field_list_lives():
    doc = es.__doc__ or ""
    with open(os.path.join(ROOT, "docs", "SCHEMA.md"), encoding="utf-8") as fh:
        schema = fh.read()
    for name in ("vendor_incomplete", "vendor_processing", "vendor_lag_minutes"):
        assert name in doc and f"`{name}`" in schema, name


# ── Todoist: writer ───────────────────────────────────────────────────────────


def _td_raw():
    return {k: copy.deepcopy(TD[k]) for k in ("date", "project_map", "completed_raw", "active_tasks", "overdue_tasks", "due_today_tasks")}


def test_the_fixture_active_list_is_the_sample_its_provenance_states():
    assert [t["priority"] for t in TD["active_tasks"]] == [1, 1, 1, 1, 1, 2, 2, 2, 3, 3, 4]
    assert [t["priority"] for t in TD["completed_raw"]] == [3, 2, 2]


def test_the_writer_stores_the_vendor_integers_and_derives_the_app_order_view():
    rec = td.transform(_td_raw(), TD["date"])[0]
    # The stored fact: count per API integer, as sent.
    assert rec["priority_counts_vendor"] == {"1": 5, "2": 3, "3": 2, "4": 1}
    # Derived: API 4 is the app's p1 (urgent); API 1 is p4 (normal).
    assert rec["priority_breakdown"] == {"p1_urgent": 1, "p2_high": 2, "p3_medium": 3, "p4_normal": 5}
    assert rec["active_count"] == 11


def test_a_stored_task_priority_is_the_vendors_integer_untouched():
    raw = _td_raw()
    raw["due_today_tasks"] = copy.deepcopy(TD["active_tasks"][-2:])  # API 3 and API 4, same wire shape
    rec = td.transform(raw, TD["date"])[0]
    assert [t["priority"] for t in rec["completed_tasks"]] == [3, 2, 2]
    assert [t["priority"] for t in rec["tasks_due_today"]] == [3, 4]


def test_a_task_without_a_usable_priority_is_counted_unknown_not_defaulted():
    raw = _td_raw()
    del raw["active_tasks"][0]["priority"]  # one of the five API-1 tasks
    raw["active_tasks"][-1]["priority"] = None  # the only API-4 task
    raw["due_today_tasks"] = [copy.deepcopy(raw["active_tasks"][0])]
    rec = td.transform(raw, TD["date"])[0]
    assert rec["priority_counts_vendor"] == {"1": 4, "2": 3, "3": 2, "4": 0, "unknown": 2}
    assert rec["priority_breakdown"] == {"p1_urgent": 0, "p2_high": 2, "p3_medium": 3, "p4_normal": 4}
    assert "priority" not in rec["tasks_due_today"][0]


# ── Todoist: MCP read side ────────────────────────────────────────────────────

# A row as stored BEFORE #4635 for the fixture's active list: API 1 was labelled
# p1_urgent, API 4 p4_normal.
LEGACY_ROW = {
    "date": "2026-10-01",
    "priority_breakdown": {"p1_urgent": Decimal(5), "p2_high": Decimal(3), "p3_medium": Decimal(2), "p4_normal": Decimal(1)},
}


def test_the_reader_agrees_on_both_row_generations():
    new_row = td.transform(_td_raw(), TD["date"])[0]
    want = {"p1_urgent": 1, "p2_high": 2, "p3_medium": 3, "p4_normal": 5}
    assert tt.priority_breakdown(new_row) == want
    assert tt.priority_breakdown(LEGACY_ROW) == want
    assert tt.vendor_priority_counts(LEGACY_ROW) == {"1": 5, "2": 3, "3": 2, "4": 1}
    assert tt.priority_breakdown({"date": "2023-01-01"}) == {} and tt.vendor_priority_counts({}) is None


def test_both_snapshot_views_serve_the_corrected_breakdown_for_a_legacy_row(monkeypatch):
    monkeypatch.setattr(tt, "query_source", lambda *a, **k: [dict(LEGACY_ROW, active_count=11)])
    for view in ("load", "today"):
        out = tt.tool_get_todoist_snapshot({"view": view, "date": "2026-10-01"})
        assert out["priority_breakdown"] == {"p1_urgent": 1, "p2_high": 2, "p3_medium": 3, "p4_normal": 5}, (view, out)
        assert "4 = urgent" in out["priority_scale"] and "1 = normal" in out["priority_scale"]


def test_the_reader_and_writer_share_one_label_map():
    assert (
        tt._LABEL_BY_VENDOR
        == td.PRIORITY_LABEL_BY_VENDOR
        == repair.LABEL_BY_VENDOR
        == {4: "p1_urgent", 3: "p2_high", 2: "p3_medium", 1: "p4_normal"}
    )


# ── Todoist: MCP write side ───────────────────────────────────────────────────


def _dispatch_create(arguments):
    with (
        patch("mcp.tools_todoist._todoist_request", return_value={"id": 1, "content": "x"}) as req,
        patch.object(tt._idem, "guard", return_value=None),
        patch.object(tt._idem, "record"),
    ):
        h.handle_tools_call({"name": "create_todoist_task", "arguments": arguments})
    assert req.call_count == 1
    return req.call_args[0][2]


def test_create_without_a_priority_sends_the_vendors_normal():
    assert _dispatch_create({"content": "Redacted task"}) == {"content": "Redacted task", "priority": 1}


def test_create_with_a_priority_sends_it_unchanged():
    for p in (1, 2, 3, 4):
        assert _dispatch_create({"content": "Redacted task", "priority": p})["priority"] == p


def test_every_priority_description_states_the_vendors_scale():
    texts = [
        tt.create_todoist_task.__doc__,
        tt.update_todoist_task.__doc__,
        TOOLS["create_todoist_task"]["schema"]["inputSchema"]["properties"]["priority"]["description"],
        TOOLS["update_todoist_task"]["schema"]["inputSchema"]["properties"]["priority"]["description"],
    ]
    for text in texts:
        flat = " ".join(text.split())
        assert "4=urgent" in flat and "1=normal" in flat, flat
        assert "1=urgent" not in flat and "4=normal" not in flat, flat


# ── The repair planners (pure; the script's AWS shell is not exercised here) ──


def _stored_night(**extra):
    return {"sk": f"DATE#{NIGHT}", "sleep_duration_hours": Decimal("6.73"), "sleep_score": Decimal("85"), **extra}


def test_repair_adds_the_flags_to_a_stored_flagged_night_and_nothing_else():
    archive = {"fetched_at": "2026-09-10T05:15:30+00:00", "raw": ES["flagged_fetch"]["raw"]}
    status, fields = repair.plan_eightsleep(_stored_night(), archive)
    assert status == "update"
    assert fields == {"vendor_incomplete": True, "vendor_processing": True, "vendor_lag_minutes": 2.50325}


def test_repair_is_idempotent_and_refuses_a_night_the_archive_no_longer_matches():
    archive = {"raw": ES["flagged_fetch"]["raw"]}
    done = _stored_night(vendor_incomplete=True, vendor_processing=True, vendor_lag_minutes=Decimal("2.50325"))
    assert repair.plan_eightsleep(done, archive)[0] == "current"
    other = dict(_stored_night(), sleep_duration_hours=Decimal("7.5"))
    assert repair.plan_eightsleep(other, archive) == ("night-differs", {})
    assert repair.plan_eightsleep({"sk": "DATE#2026-01-01"}, archive) == ("no-day", {})


def test_repair_relabels_todoist_from_the_archive_or_by_mirroring_and_flags_a_disagreement():
    archive = {"raw": _td_raw()}
    want = {
        "priority_counts_vendor": {"1": 5, "2": 3, "3": 2, "4": 1},
        "priority_breakdown": {"p1_urgent": 1, "p2_high": 2, "p3_medium": 3, "p4_normal": 5},
    }
    assert repair.plan_todoist(dict(LEGACY_ROW), archive) == ("update-archive", want)
    assert repair.plan_todoist(dict(LEGACY_ROW), None) == ("update-mirrored", want)
    assert repair.plan_todoist({"sk": "DATE#2023-01-01"}, None) == ("no-priority-data", {})
    assert repair.plan_todoist(dict(LEGACY_ROW, priority_counts_vendor=want["priority_counts_vendor"]), archive)[0] == "current"
    wrong = dict(LEGACY_ROW, priority_breakdown={"p1_urgent": 9, "p2_high": 3, "p3_medium": 2, "p4_normal": 1})
    assert repair.plan_todoist(wrong, archive)[0] == "disagree"
