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


def _frozen_pacific_today():
    """The handler's clock, frozen to the fixture's TODAY (#2376): `run()` with no target derives
    tomorrow from `pacific_today()`, so the production default path is driven, not a back-dated call."""
    return patch("common.pacific_time.pacific_today", return_value=TODAY)


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
        _frozen_pacific_today(),
    ):
        out = npd.run()  # the scheduled call: no target, tomorrow derived from the (frozen) Pacific day
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
    if out.get("target_date") != TOMORROW_PRIMARY.target_date:
        offenders.append(("the run did not target tomorrow off the frozen clock", out.get("target_date")))
    if out.get("outcome") != npd.NO_SESSION:
        offenders.append(("the sweep changed the run's outcome", out.get("outcome")))
    assert not offenders, offenders


def test_mutation_control_without_the_sweep_the_census_holds_the_pre_drafts():
    """The fixture is the defect: unswept, the census counts the marked pairs (the live +2/day)."""
    table = _seeded()
    live = {ir.routine_id for ir in _census(table)["live"]}
    assert {EXPIRED_PRIMARY.routine_id, EXPIRED_SIBLING.routine_id, CHAT_DRAFT.routine_id} <= live


def test_an_on_demand_run_for_a_future_date_never_archives_a_draft_whose_day_has_not_come():
    """An on-demand run for D+3 (today = D) must sweep as of the REAL Pacific today, not target − 1:
    unclamped it treats D+2 as today and archives the real D+1 pre-draft (tonight's) as "expired"."""
    table = _seeded()
    with (
        patch.object(routine_repo, "_table", table),
        patch("training.routine_repo._live_genesis", return_value=GENESIS),
        patch.object(npd, "scheduled_session", return_value={"label": "walk", "archetype": "aerobic"}),
        _frozen_pacific_today(),
    ):
        out = npd.run(target_date="2026-10-12")  # D+3 off the frozen TODAY (10-09)
        tomorrow = routine_repo.get_current(TOMORROW_PRIMARY.routine_id)
    sweep = out.get("sweep") or {}
    archived = {a["routine_id"] for a in sweep.get("archived", [])}
    offenders = []
    if TOMORROW_PRIMARY.routine_id in archived or tomorrow.status != "draft":
        offenders.append(("archived the D+1 pre-draft before its day", tomorrow.status, sweep))
    if (sweep.get("window") or {}).get("end") != TODAY:
        offenders.append(("the sweep's today is not the real Pacific today", sweep.get("window")))
    assert not offenders, offenders


def test_a_failing_sweep_never_stops_the_nights_draft():
    with (
        patch.object(npd, "sweep_expired", side_effect=RuntimeError("ddb down")),
        patch.object(npd, "scheduled_session", return_value={"label": "walk", "archetype": "aerobic"}),
        _frozen_pacific_today(),
    ):
        out = npd.run()
    assert out["outcome"] == npd.NO_SESSION and "RuntimeError" in out["sweep"]["error"]


# ── owner ruling 2026-10-11: a draft the pre-draft did NOT author, untouched 14 days, is archived ──
# The live shapes (routine repo, read-only, 2026-10-10): chat `draft_custom` drafts carrying `authored`
# and (when red-teamed) a `critics` record whose `ran_at` is their last touch, and unmarked
# `cron_generated` / floor drafts from the generator. Ids are the live prefixes.
STALE_TODAY = "2026-10-11"  # cutoff 09-27


def _chat(rid, day, archetype, created, critics_ran_at=None, version=2, hevy=None, status="draft"):
    snap = {
        "authored": {"by": "chat", "rationale": "owner-built in the evening chat"},
        "cardio_cues": [],
        "created_exercises": [],
        "exercise_count": 6,
        "force_title": True,
        "total_sets": 18,
    }
    if critics_ran_at:
        snap["critics"] = {"ran_at": critics_ran_at, "verdicts": [{"critic": "load", "verdict": "pass"}], "binding": {"version": version}}
    return RoutineSpec(
        routine_id=rid,
        target_date=day,
        archetype=archetype,
        variant="ideal",
        status=status,
        version=version,
        parent_version=version - 1,
        created_by="chat",
        source_action="draft_custom",
        created_at=created,
        hevy_routine_id=hevy,
        inputs_snapshot=snap,
    )


def _cron(rid, day, archetype, variant, created, version=3):
    snap = (
        {"calendar": {"session_role": f"{archetype}_heavy"}}
        if variant == "ideal"
        else {"session_role": f"{archetype}_heavy", "variant": variant}
    )
    return RoutineSpec(
        routine_id=rid,
        target_date=day,
        archetype=archetype,
        variant=variant,
        status="draft",
        version=version,
        parent_version=version - 1,
        created_by="cron",
        source_action="cron_generated" if variant == "ideal" else variant,
        created_at=created,
        inputs_snapshot=snap,
    )


# untouched since 09-26 (≤ cutoff 09-27) → archived
STALE_CHAT = _chat("2c101a6f-chat", "2026-09-26", "lower", "2026-09-26T04:03:45.264667+00:00", "2026-09-26T04:04:08.437664+00:00")
STALE_UNREVIEWED = _chat("6b310125-chat", "2026-09-27", "lower", "2026-09-26T17:03:49.148957+00:00", version=1)
STALE_CRON = _cron("8409f757-cron", "2026-09-20", "lower", "ideal", "2026-09-20T02:00:38.731040+00:00")
# touched inside the window → kept
RECENT_CHAT = _chat("34a34a5a-chat", "2026-09-28", "lower", "2026-09-28T02:03:47.944385+00:00", "2026-09-28T02:04:10.719319+00:00")
OLD_BUT_RETOUCHED = _chat("38995601-chat", "2026-09-26", "flex", "2026-09-26T17:15:46.834097+00:00", "2026-10-05T17:16:08Z")
# old, but its day has not come — a planned session is never read as abandoned
OLD_FUTURE_DAY = _chat("f00dfeed-chat", "2026-10-14", "upper", "2026-09-20T17:00:00Z")
# pushed to Hevy / committed / already archived — never the rule's business
OLD_PUSHED = _chat("bead0001-pushed", "2026-09-20", "upper", "2026-09-19T17:00:00Z", hevy="hv-0920")
OLD_ACTIVE = _chat("bead0002-active", "2026-09-21", "upper", "2026-09-20T17:00:00Z", status="active", hevy="hv-0921")
OLD_ARCHIVED = _chat("bead0003-archived", "2026-09-22", "upper", "2026-09-21T17:00:00Z", status="archived")
# no stamp at all: an unknown age is never read as old
UNSTAMPED = _chat("bead0004-nostamp", "2026-09-23", "lower", "")

STALE_ALL = [
    STALE_CHAT,
    STALE_UNREVIEWED,
    STALE_CRON,
    RECENT_CHAT,
    OLD_BUT_RETOUCHED,
    OLD_FUTURE_DAY,
    OLD_PUSHED,
    OLD_ACTIVE,
    OLD_ARCHIVED,
    UNSTAMPED,
]
STALE_WANT = {STALE_CHAT.routine_id, STALE_UNREVIEWED.routine_id, STALE_CRON.routine_id}


def _stale_seeded():
    table = _Table()
    with patch.object(routine_repo, "_table", table):
        for ir in STALE_ALL:
            routine_repo.put_versioned(RoutineSpec(**{**ir.__dict__, "inputs_snapshot": dict(ir.inputs_snapshot)}))
    return table


def _sweep(table, today=STALE_TODAY):
    with patch.object(routine_repo, "_table", table):
        out = npd.sweep_expired(today, "2026-10-11T02:00:01Z", genesis=GENESIS)
        current = {ir.routine_id: routine_repo.get_current(ir.routine_id) for ir in STALE_ALL}
    return out, current


def test_a_non_predraft_draft_untouched_14_days_is_archived_never_deleted_and_nothing_else_moves():
    table = _stale_seeded()
    before_keys = set(table.items)
    out, current = _sweep(table)
    offenders = []
    archived = {a["routine_id"]: a["reason"] for a in out["archived"]}
    if archived != {rid: npd.STALE_REASON for rid in STALE_WANT}:
        offenders.append(("archived set", archived))
    if out["window"].get("stale_cutoff") != "2026-09-27" or out["errors"]:
        offenders.append(("window / errors", out["window"], out["errors"]))
    seeded = {ir.routine_id: int(ir.version) for ir in STALE_ALL}
    for rid in STALE_WANT:
        ir = current[rid]
        stamp = (ir.inputs_snapshot or {}).get(npd.AUTO_ARCHIVE_KEY) or {}
        if ir.status != "archived" or stamp.get("reason") != npd.STALE_REASON or not stamp.get("last_touched"):
            offenders.append(("not archived with its stamp", rid, ir.status, stamp))
        if npd.MARKER in (ir.inputs_snapshot or {}):
            offenders.append(("a chat draft now reads as a pre-draft", rid))
        if int(ir.version) != seeded[rid] + 1:
            offenders.append(("the archive is not the NEXT version", rid, ir.version))
        for v in (seeded[rid], seeded[rid] + 1):
            if (f"USER#matthew#ROUTINE#{rid}", f"VERSION#{v:06d}") not in table.items:
                offenders.append(("version item missing", rid, v))
    for ir in STALE_ALL:
        if ir.routine_id in STALE_WANT:
            continue
        got = current[ir.routine_id]
        if got.status != ir.status or int(got.version) != int(ir.version):
            offenders.append(("touched a routine the rule must leave", ir.routine_id, got.status, got.version))
    if not before_keys <= set(table.items) or table.deletes:
        offenders.append(("an item disappeared", sorted(before_keys - set(table.items))))
    # the qa-smoke census drops the archived ones; the recent / unstamped drafts stay counted
    with patch.object(routine_repo, "_table", table):
        live = {ir.routine_id for ir in routine_repo.stale_draft_census(older_than_days=7, today=STALE_TODAY, genesis=GENESIS)["live"]}
    if live & STALE_WANT:
        offenders.append(("census still counts an archived draft", sorted(live & STALE_WANT)))
    assert not offenders, offenders


def test_a_second_run_is_a_no_op():
    table = _stale_seeded()
    _sweep(table)
    out, _ = _sweep(table)
    assert out["archived"] == [] and out["errors"] == []


def test_the_threshold_is_fourteen_days_to_the_day():
    """Touched on the cutoff day (today − 14) → archived; one day later → kept."""
    on_cutoff = _chat("edge0001", "2026-09-27", "lower", "2026-09-27T23:59:00Z")
    day_after = _chat("edge0002", "2026-09-28", "lower", "2026-09-28T00:00:01Z")
    assert npd._stale_reason(on_cutoff, STALE_TODAY, "2026-09-27") == npd.STALE_REASON
    assert npd._stale_reason(day_after, STALE_TODAY, "2026-09-27") is None
    assert npd.STALE_DRAFT_DAYS == 14


def test_the_rule_alone_never_reaches_a_day_still_ahead():
    """The sweep's window already ends at today; the rule holds on its own too (another caller may pass
    a wider list): an old draft for a day still ahead, or for today, is a planned session."""
    for day in (STALE_TODAY, OLD_FUTURE_DAY.target_date):
        ir = _chat("ahead0001", day, "upper", "2026-09-01T17:00:00Z")
        assert npd._stale_reason(ir, STALE_TODAY, "2026-09-27") is None, day


def test_mutation_check_the_rule_is_what_archives_them():
    """Mutation control: with `_stale_reason` disarmed the same fixture archives NOTHING (none of it is the
    pre-draft's), and with the last-touch reduced to `created_at` alone the re-touched draft is wrongly
    archived — so the fixture discriminates both the rule and its notion of "touched"."""
    table = _stale_seeded()
    with patch.object(npd, "_stale_reason", return_value=None):
        out, _ = _sweep(table)
    assert out["archived"] == []

    table = _stale_seeded()
    with patch.object(npd, "_last_touched_day", lambda ir: str(ir.created_at or "")[:10]):
        out, _ = _sweep(table)
    assert OLD_BUT_RETOUCHED.routine_id in {a["routine_id"] for a in out["archived"]}
