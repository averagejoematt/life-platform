"""tests/test_predraft_sweep_4732.py — the nightly pre-draft archives the drafts it left behind (#4732).

THE PATH, named from the routine repo (read-only, 2026-10-09): the 02:00Z pre-draft drafts a marked
primary + floor sibling for tomorrow; in chat the owner commits a DIFFERENT routine for that session,
so the marked pair stays `draft` forever. 14 of the 19 live-cycle drafts older than 7 days that
`data:orphan_routine_drafts` counted were those pairs (09-26 → 10-02).

Driven through the REAL `training.routine_repo` (put_versioned, list_by_date_range and the census
itself) over an in-memory table that stores exactly what DynamoDB stores: the immutable
VERSION#<n> item, the VERSION#current pointer, and the date-sorted index row. The fixture rows are
the live 2026-10-02 / 10-09 / 10-10 shapes (ids are the live prefixes).
"""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import routine_repo  # noqa: E402
from training.routine_ir import RoutineSpec  # noqa: E402

from mcp import nightly_predraft as npd  # noqa: E402

GENESIS = "2026-09-06"
TODAY = "2026-10-09"  # the run at 02:00Z 10-10 = 19:00 PT 10-09 drafts 10-10


class _Table:
    """The three item shapes the repo writes, keyed by (pk, sk). Nothing is ever removed."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}
        self.deletes = 0

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.items:
            exc = routine_repo._ddb.meta.client.exceptions.ConditionalCheckFailedException
            raise exc({"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}}, "PutItem")
        self.items[key] = dict(Item)

    def delete_item(self, **kw):  # pragma: no cover — the sweep must never reach it
        self.deletes += 1
        raise AssertionError("the sweep must archive, never delete")

    def query(self, KeyConditionExpression, Limit=100):
        pk_cond, sk_cond = KeyConditionExpression.get_expression()["values"]
        pk = pk_cond.get_expression()["values"][1]
        _key, lo, hi = sk_cond.get_expression()["values"]
        rows = sorted((it for (p, s), it in self.items.items() if p == pk and lo <= s <= hi), key=lambda it: it["sk"])
        return {"Items": rows[:Limit]}


def _marked(rid, day, archetype, variant, role, session_role, version=3):
    """A pre-draft row as `_mark_draft` leaves it (marker stamped, then critics on the primary)."""
    snap = {
        "calendar": {"session_role": session_role},
        npd.MARKER: {"engine": "1.0.0", "role": role, "primary_routine_id": rid, "drafted_at": f"{day}T02:00:05Z"},
    }
    return RoutineSpec(
        routine_id=rid,
        target_date=day,
        archetype=archetype,
        variant=variant,
        status="draft",
        version=version,
        parent_version=version - 1,
        created_by="cron",
        created_at=f"{day}T02:00:00Z",
        inputs_snapshot=snap,
    )


def _plain(rid, day, archetype, status="draft", hevy=None, created=None):
    return RoutineSpec(
        routine_id=rid,
        target_date=day,
        archetype=archetype,
        status=status,
        version=2,
        parent_version=1,
        hevy_routine_id=hevy,
        created_at=f"{created or day}T03:24:00Z",
    )


# The live shapes. 10-02: the marked upper pair, and the chat routine he committed instead.
EXPIRED_PRIMARY = _marked("787ec7b5-primary", "2026-10-02", "upper", "ideal", npd.PRIMARY, "upper_volume")
EXPIRED_SIBLING = _marked("7a412458-sibling", "2026-10-02", "upper", "floor", npd.SIBLING, "upper_volume", version=2)
COMMITTED_1002 = _plain("00ec5957-committed", "2026-10-02", "upper", status="active", hevy="hv-1002")
# 09-28: a chat-authored draft the pre-draft did not write — never its business.
CHAT_DRAFT = _plain("30e24cca-chat", "2026-09-28", "lower")
# 10-09 (today): the marked pair is superseded by the lower routine he committed for today.
TODAY_PRIMARY = _marked("3b63ca9e-primary", TODAY, "lower", "ideal", npd.PRIMARY, "lower_heavy")
TODAY_SIBLING = _marked("d7ea6c80-sibling", TODAY, "lower", "floor", npd.SIBLING, "lower_heavy", version=2)
COMMITTED_TODAY = _plain("c5665674-committed", TODAY, "lower", status="active", hevy="hv-1009")
# 10-10 (tonight's target): drafted, not yet reviewed — out of reach.
TOMORROW_PRIMARY = _marked("cceac1a2-primary", "2026-10-10", "upper", "ideal", npd.PRIMARY, "upper_volume")
# A pre-draft he COMMITTED himself (Hevy-linked): never archived by the sweep.
PUSHED_PREDRAFT = _marked("ff7518cd-pushed", "2026-09-27", "upper", "ideal", npd.PRIMARY, "upper_heavy")
PUSHED_PREDRAFT.status, PUSHED_PREDRAFT.hevy_routine_id = "active", "hv-0927"
# Today's marked draft with no committed routine on the date: he may still train tonight — left alone.
UNSUPERSEDED_TODAY = _marked("aaaa0000-today", TODAY, "upper", "ideal", npd.PRIMARY, "upper_heavy")

ALL = [
    EXPIRED_PRIMARY,
    EXPIRED_SIBLING,
    COMMITTED_1002,
    CHAT_DRAFT,
    TODAY_PRIMARY,
    TODAY_SIBLING,
    COMMITTED_TODAY,
    TOMORROW_PRIMARY,
    PUSHED_PREDRAFT,
    UNSUPERSEDED_TODAY,
]


def _seeded():
    table = _Table()
    with patch.object(routine_repo, "_table", table):
        for ir in ALL:
            routine_repo.put_versioned(RoutineSpec(**{**ir.__dict__}))
    return table


def _census(table):
    with patch.object(routine_repo, "_table", table):
        return routine_repo.stale_draft_census(older_than_days=7, today="2026-10-10", genesis=GENESIS)


def test_the_nightly_run_archives_its_own_expired_and_superseded_drafts_and_nothing_else():
    """One gate over the whole fixture: what is archived, what is left, that history survives, that the
    orphan census drops to the one chat draft — reported together so every offender shows at once."""
    table = _seeded()
    before_keys = set(table.items)
    with (
        patch.object(routine_repo, "_table", table),
        patch("training.routine_repo._live_genesis", return_value=GENESIS),
        patch.object(npd, "scheduled_session", return_value={"label": "walk", "archetype": "aerobic"}),
    ):
        out = npd.run("2026-10-10")
        current = {ir.routine_id: routine_repo.get_current(ir.routine_id) for ir in ALL}

    offenders = []
    archived = {a["routine_id"]: a["reason"] for a in (out.get("sweep") or {}).get("archived", [])}
    want = {
        EXPIRED_PRIMARY.routine_id: "expired",
        EXPIRED_SIBLING.routine_id: "expired",
        TODAY_PRIMARY.routine_id: "superseded",
        TODAY_SIBLING.routine_id: "superseded",
    }
    if archived != want:
        offenders.append(("archived set", archived, (out.get("sweep") or {})))
    for rid in want:
        ir = current[rid]
        if ir.status != "archived" or (ir.inputs_snapshot or {}).get(npd.MARKER, {}).get("archived", {}).get("reason") != want[rid]:
            offenders.append(("not archived with its reason", rid, ir.status))
    for ir in (COMMITTED_1002, CHAT_DRAFT, COMMITTED_TODAY, TOMORROW_PRIMARY, PUSHED_PREDRAFT, UNSUPERSEDED_TODAY):
        got = current[ir.routine_id]
        if got.status != ir.status or int(got.version) != int(ir.version):
            offenders.append(("touched a routine the sweep must leave", ir.routine_id, got.status, got.version))
    # never delete: every item that existed is still there, and each archive ADDED its next version
    if not before_keys <= set(table.items) or table.deletes:
        offenders.append(("an item disappeared", sorted(before_keys - set(table.items))))
    seeded = {ir.routine_id: int(ir.version) for ir in ALL}
    for rid in want:
        for v in (seeded[rid], seeded[rid] + 1):  # the draft version stays; the archive is the NEXT version
            if (f"USER#matthew#ROUTINE#{rid}", f"VERSION#{v:06d}") not in table.items:
                offenders.append(("version item missing", rid, v))
    # the census the qa-smoke leg reads now names only the draft the pre-draft did not author
    live = [ir.routine_id for ir in _census(table)["live"]]
    if live != [CHAT_DRAFT.routine_id]:
        offenders.append(("orphan census after the sweep", live))
    if out.get("outcome") != npd.NO_SESSION:
        offenders.append(("the sweep changed the run's outcome", out.get("outcome")))
    assert not offenders, offenders


def test_mutation_control_without_the_sweep_the_census_holds_the_pre_drafts():
    """The fixture is the defect: unswept, the census counts the marked pairs (the live +2/day)."""
    table = _seeded()
    live = {ir.routine_id for ir in _census(table)["live"]}
    assert {EXPIRED_PRIMARY.routine_id, EXPIRED_SIBLING.routine_id, CHAT_DRAFT.routine_id} <= live


def test_a_failing_sweep_never_stops_the_nights_draft():
    with (
        patch.object(npd, "sweep_expired", side_effect=RuntimeError("ddb down")),
        patch.object(npd, "scheduled_session", return_value={"label": "walk", "archetype": "aerobic"}),
    ):
        out = npd.run("2026-10-10")
    assert out["outcome"] == npd.NO_SESSION and "RuntimeError" in out["sweep"]["error"]
