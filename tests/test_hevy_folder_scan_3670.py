"""#3670 — the half of the folder fix that the page_size change does NOT cover.

Box 1 of the issue is "`list_folders` page_size <= 10; a fresh draft_custom ->
commit lands in its type folder". Capping the page size is what stops the 400
(`pageSize=11 -> 400 {"error":"pageSize must be less than or equal to 10"}`,
swept live 2026-09-06) — but it is not, on its own, what makes foldering work.

Reading the call site: `ensure_folder` did a find-or-create over ONE page. At
`pageSize=50` that page was the whole folder list for any plausible account; at
the corrected `pageSize=10` it stops being the whole list at eleven folders. The
folder then sits on page 2, the scan misses it, and the "fix" creates a SECOND
"Push" next to the real one. That failure is worse than the 400 it replaces,
because it reports success and looks like success in the Hevy app too — the
routine really is in a folder called Push, just not the athlete's.

So the scan walks every page (`hevy_write_client.list_all_folders`), and when the
walk hits its own page bound without finding the folder it reports a miss instead
of creating a maybe-duplicate. Fail-soft, and still never silent: the reason
lands in the commit result's `folder` key like every other miss (#3670 box 2).

Box 5 is also guarded here, behaviourally rather than by reading the comment that
explains it: `folder_id` is create-only in Hevy, `to_update_body` omits it, and no
path attempts a retroactive move. The tests below assert the wire body, not the
prose.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, ROOT)

from training import hevy_write_client as wc  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import tools_hevy_routine as t  # noqa: E402

_TITLE_CTX = {"phase": "Foundation", "type_count_in_phase": 1, "all_time_count": 1}


def _verified(folder_id=None):
    """Stub the #3718 readback so these tests measure foldering, not verification."""
    return patch.object(
        wc,
        "verify_commit_landed",
        lambda rid, body, before: {"verified": True, "reason": None, "folder_id": folder_id, "updated_at": "2026-09-08T12:00:00Z"},
    )


def _pages(*pages: list[dict], page_count: int | None = None):
    """A fake `list_folders` serving the given pages (1-indexed)."""
    total = page_count if page_count is not None else len(pages)
    calls: list[int] = []

    def fake(page: int = 1, page_size: int = 10):
        calls.append(page)
        batch = pages[page - 1] if page - 1 < len(pages) else []
        return {"page": page, "page_count": total, "routine_folders": batch}

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


def _folders(*titles: str, start_id: int = 1) -> list[dict]:
    return [{"id": start_id + i, "title": ti} for i, ti in enumerate(titles)]


# ── list_all_folders: the walk itself ─────────────────────────────────────────


def test_list_all_folders_walks_every_page():
    page1 = _folders(*[f"F{i}" for i in range(10)], start_id=100)
    page2 = _folders("Push", "Pull", start_id=200)
    fake = _pages(page1, page2)
    with patch.object(wc, "list_folders", side_effect=fake):
        folders, truncated = wc.list_all_folders()
    assert fake.calls == [1, 2], "the scan must not stop at page 1 — pageSize is capped at 10"
    assert [f["title"] for f in folders][-2:] == ["Push", "Pull"]
    assert len(folders) == 12
    assert truncated is False


def test_list_all_folders_makes_one_call_when_there_is_one_page():
    """Positive control: the walk is not a fixed number of requests."""
    fake = _pages(_folders("Push", "Pull", "Legs"))
    with patch.object(wc, "list_folders", side_effect=fake):
        folders, truncated = wc.list_all_folders()
    assert fake.calls == [1]
    assert len(folders) == 3 and truncated is False


def test_list_all_folders_tolerates_a_payload_with_no_page_count():
    """An older/leaner payload must read as 'one page', never as an infinite walk."""
    with patch.object(wc, "list_folders", return_value={"routine_folders": _folders("Push")}) as m:
        folders, truncated = wc.list_all_folders()
    assert m.call_count == 1
    assert len(folders) == 1 and truncated is False


def test_list_all_folders_stops_at_its_page_bound_and_says_so():
    """A mis-reported page_count must bound the client, and truncation is REPORTED."""
    fake = _pages(*[_folders(f"F{i}", start_id=i) for i in range(30)], page_count=30)
    with patch.object(wc, "list_folders", side_effect=fake):
        folders, truncated = wc.list_all_folders(max_pages=4)
    assert fake.calls == [1, 2, 3, 4]
    assert len(folders) == 4
    assert truncated is True, "a truncated sweep that reports False is the silent-swallow shape again"


# ── ensure_folder over the walk ───────────────────────────────────────────────


def test_ensure_folder_finds_a_folder_on_page_two_instead_of_creating_a_duplicate():
    """THE residual defect behind box 1. Pre-fix (page-1-only scan) this created a
    second "Push"; the commit then reported a folder it had just invented."""
    fake = _pages(_folders(*[f"F{i}" for i in range(10)], start_id=500), _folders("Push", start_id=777))
    with (
        patch.object(wc, "list_folders", side_effect=fake),
        patch.object(wc, "create_folder") as create_mock,
    ):
        folder_id, reason = t._ensure_folder("Push")
    assert folder_id == 777, "the existing Push on page 2 must win"
    assert reason is None
    create_mock.assert_not_called()


def test_ensure_folder_still_creates_when_the_folder_genuinely_is_absent():
    """Negative control for the test above: a complete walk that finds nothing is
    still allowed to create. The guard is about UNKNOWN, not about never creating."""
    fake = _pages(_folders(*[f"F{i}" for i in range(10)], start_id=500), _folders("Pull", start_id=777))
    with (
        patch.object(wc, "list_folders", side_effect=fake),
        patch.object(wc, "create_folder", return_value={"routine_folder": {"id": 900}}) as create_mock,
    ):
        folder_id, reason = t._ensure_folder("Push")
    assert folder_id == 900 and reason is None
    create_mock.assert_called_once_with("Push")


def test_ensure_folder_refuses_to_create_a_duplicate_when_the_walk_was_truncated():
    """Not finding it in a truncated list is not evidence it is absent. Report the
    miss (the commit result carries it) rather than create a possible duplicate."""
    fake = _pages(*[_folders(f"F{i}", start_id=i) for i in range(40)], page_count=40)
    with (
        patch.object(wc, "list_folders", side_effect=fake),
        patch.object(wc, "create_folder") as create_mock,
    ):
        folder_id, reason = t._ensure_folder("Push")
    create_mock.assert_not_called()
    assert folder_id is None
    assert reason and "truncated" in reason and "duplicate" in reason, reason


def test_commit_reports_the_truncated_walk_in_its_own_result():
    """Box 2's contract applied to the new miss: it rides in `folder`, not a log."""
    ir = RoutineSpec(
        routine_id="r-trunc",
        target_date="2026-09-08",
        archetype="push",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
    )
    fake = _pages(*[_folders(f"F{i}", start_id=i) for i in range(40)], page_count=40)
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned"),
        patch("training.routine_repo.upsert_id_map"),
        patch("training.hevy_template_cache.resolve_movement", return_value="55E6546B"),
        patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
        patch.object(wc, "list_folders", side_effect=fake),
        patch.object(wc, "create_folder"),
        patch.object(wc, "create_routine", return_value={"routine": {"id": "new-id", "updated_at": "2026-09-08T12:00:00Z"}}),
        _verified(),
        # #4079: stub the spec-ledger write — tested on its own in test_routine_spec_ledger_4079.py.
        patch("mcp.routine_spec_ledger.save_routine_spec", return_value={"saved": True, "key": "stub.json"}),
    ):
        result = t.tool_manage_hevy_routine({"action": "commit", "routine_id": "r-trunc"})
    assert result["status"] == "committed"
    assert result["folder"].startswith("unfoldered: "), result["folder"]
    assert "truncated" in result["folder"]


# ── box 5: no retroactive backfill, asserted on the wire ──────────────────────


def _committed_ir(routine_id: str, folder_id) -> RoutineSpec:
    ir = RoutineSpec(
        routine_id=routine_id,
        target_date="2026-09-08",
        archetype="push",
        title="Foundation - Push - 1 - 1",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
    )
    ir.hevy_routine_id = "existing-id"
    ir.hevy_updated_at = "2026-09-08T10:00:00Z"
    ir.hevy_folder_id = folder_id
    return ir


def test_update_branch_never_puts_folder_id_on_the_wire_even_when_the_ir_holds_one():
    """Box 5. `folder_id` is create-only in Hevy: `to_update_body` omits it
    deliberately (hevy_compiler.py). The omission is asserted on the BODY, so a
    future "helpful" backfill that re-adds it reds here rather than shipping a
    PUT Hevy silently ignores while the result claims the routine moved."""
    ir = _committed_ir("r-no-backfill", 3087792)
    captured: dict = {}

    def fake_update(routine_id, body, expected_updated_at=None):
        captured["body"] = body
        return {"routine": {"id": routine_id, "updated_at": "2026-09-08T12:00:00Z"}}

    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned"),
        patch("training.routine_repo.upsert_id_map"),
        patch("training.hevy_template_cache.resolve_movement", return_value="55E6546B"),
        patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
        patch.object(wc, "list_folders") as folders_mock,
        patch.object(wc, "create_folder") as create_mock,
        patch.object(wc, "update_routine_with_guard", side_effect=fake_update),
        _verified(folder_id=3087792),
        # #4079: stub the spec-ledger write — tested on its own in test_routine_spec_ledger_4079.py.
        patch("mcp.routine_spec_ledger.save_routine_spec", return_value={"saved": True, "key": "stub.json"}),
    ):
        result = t.tool_manage_hevy_routine({"action": "commit", "routine_id": "r-no-backfill"})

    assert "folder_id" not in captured["body"]["routine"], "a folder backfill reached the wire — Hevy ignores it"
    # ...and no folder I/O was attempted at all on the update branch: there is
    # nothing to move it INTO, so looking one up would only imply a move.
    folders_mock.assert_not_called()
    create_mock.assert_not_called()
    assert "create-only" in result["folder"]


def test_archive_renames_and_does_not_send_a_folder_move():
    """The archive path resolves an Archive folder id and stores it locally, but the
    PUT still carries no folder_id — the rename is the only thing that lands."""
    ir = _committed_ir("r-archive", None)
    captured: dict = {}

    def fake_update(routine_id, body, expected_updated_at=None):
        captured["body"] = body
        return {"routine": {"id": routine_id, "updated_at": "2026-09-08T12:00:00Z"}}

    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned"),
        patch("training.hevy_template_cache.resolve_movement", return_value="55E6546B"),
        patch.object(wc, "list_folders", side_effect=_pages(_folders("Push", "Archive", start_id=10))),
        patch.object(wc, "create_folder") as create_mock,
        patch.object(wc, "update_routine_with_guard", side_effect=fake_update),
    ):
        result = t.tool_manage_hevy_routine({"action": "archive", "routine_id": "r-archive"})

    assert result["status"] == "archived"
    assert result["archive_folder_id"] == 11, "found the existing Archive folder"
    create_mock.assert_not_called()
    assert "folder_id" not in captured["body"]["routine"]
    assert captured["body"]["routine"]["title"].startswith("[archived ")
