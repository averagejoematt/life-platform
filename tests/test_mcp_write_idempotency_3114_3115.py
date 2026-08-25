"""tests/test_mcp_write_idempotency_3114_3115.py — a replayed MCP write is a no-op.

DIL-025's census (`docs/IDEMPOTENCY.md` §5) found two classes of write-capable MCP
tool that appended on replay rather than converging:

  #3114 — writes keyed on `datetime.now()` or `uuid4()`. A retried tool call minted a
          second decision / insight / correction / reading session that no later read
          could distinguish from a genuine second event. `manage_reading debrief` was
          the worst: it wrote a duplicate takeaway AND started a second
          spaced-repetition clock, silently doubling a book's retention schedule.
  #3115 — creates against a third party. A replayed `create_todoist_task` or
          `manage_hevy_routine commit` minted a remote object no local dedup could
          retract, and Todoist's REST surface offers no idempotency header at all.

Every test here drives the REAL tool handler (several through
`mcp.handler.handle_tools_call`, the dispatch path the live server uses) with the
transport stubbed. **No live MCP tool is invoked and no vendor API is called** — the
Todoist client's single network function and the Hevy client's `list_routines` /
`urlopen` are patched, and DynamoDB is `reading_fakes.FakeTable`, which really does
evaluate the ConditionExpression rather than accepting every put.

Both directions are proved for each tool, because only one of them is the bug: a
replay must be a no-op AND a genuinely distinct second event must still write. A
guard that suppresses everything is not idempotency, it is data loss.
"""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from coach import coach_checkin as cc, coach_corrections as ccor  # noqa: E402
from reading import reading_store as rs  # noqa: E402
from reading_fakes import ConditionalCheckFailedException, FakeTable  # noqa: E402
from training import hevy_write_client as wc, routine_generator as rg, routine_repo as repo  # noqa: E402

from mcp import idempotency as idem, tools_decisions as td, tools_lifestyle as tl, tools_reading as tr, tools_todoist as tt  # noqa: E402
from mcp.audit import is_write_tool  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402


def rows(table, prefix, pk=None):
    """Stored items whose sk begins with `prefix` (optionally within one pk)."""
    return [v for (p, s), v in table.store.items() if s.startswith(prefix) and (pk is None or p == pk)]


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — the write-tool SET is derived, so a 27th tool must declare its semantics
# ══════════════════════════════════════════════════════════════════════════════


def derived_write_tools(tools=None) -> set:
    """The write set, DERIVED from the live registry via the central verb rule —
    never hand-listed here. Parameterised so the mutation test below can drive it."""
    return {name for name in (tools if tools is not None else TOOLS) if is_write_tool(name)}


def missing_declarations(tools=None, declared=None) -> list:
    return sorted(derived_write_tools(tools) - set(idem.REPLAY_SEMANTICS if declared is None else declared))


def test_the_derivation_actually_found_the_write_set():
    """Sanity floor first: if the derivation returned an empty set, every assertion
    below would pass vacuously — which is exactly how a set-guard rots."""
    assert len(derived_write_tools()) >= 25, f"only {len(derived_write_tools())} write tools derived — the verb rule is broken"


def test_every_write_tool_declares_its_replay_semantics():
    """THE test. A 27th write tool must say what happens when it runs twice."""
    missing = missing_declarations()
    assert not missing, (
        "write-capable MCP tools with no entry in mcp/idempotency.py::REPLAY_SEMANTICS.\n"
        "Say what a replay of this tool does — an honest 'residual' with a reason is a\n"
        "fine answer; silence is not (#3114/#3115).\n  " + "\n  ".join(missing)
    )


def test_every_declaration_names_a_known_mechanism_and_a_reason():
    for tool, entry in idem.REPLAY_SEMANTICS.items():
        mechanism, reason = entry
        assert mechanism in idem.VALID_MECHANISMS, f"{tool}: unknown mechanism {mechanism!r}"
        assert len(reason) > 20, f"{tool}: the declaration's reason is a stub — say WHY it is safe"


def test_the_declaration_registry_has_no_entries_for_read_tools():
    """Scope control: a declaration for a read tool means the verb rule and the
    registry disagree about what a write is, which is worse than a missing row."""
    stale = sorted(set(idem.REPLAY_SEMANTICS) - derived_write_tools())
    assert not stale, f"declared but not write-capable (or no longer registered): {stale}"


def test_mutation_a_new_write_tool_without_a_declaration_is_caught():
    """Non-vacuity: inject a 27th write tool and prove the guard names it."""
    injected = dict.fromkeys(list(TOOLS) + ["log_something_new"], {})
    assert missing_declarations(injected) == ["log_something_new"]
    assert missing_declarations(injected, declared=dict(idem.REPLAY_SEMANTICS, log_something_new=("x", "y"))) == []


# ══════════════════════════════════════════════════════════════════════════════
# The claim ledger itself
# ══════════════════════════════════════════════════════════════════════════════


def test_a_second_claim_on_the_same_key_loses_and_echoes_the_first():
    t = FakeTable()
    first = idem.claim(t, "scope", "k1", payload={"id": "abc"})
    second = idem.claim(t, "scope", "k1", payload={"id": "def"})
    assert first["claimed"] is True
    assert second["claimed"] is False
    assert idem.first_payload(second) == {"id": "abc"}, "the loser must echo the WINNER's id, not its own"


def test_a_different_content_key_still_claims():
    t = FakeTable()
    assert idem.claim(t, "scope", "k1")["claimed"] is True
    assert idem.claim(t, "scope", "k2")["claimed"] is True


def test_a_windowed_claim_reopens_once_the_window_passes():
    from datetime import datetime, timedelta, timezone

    t = FakeTable()
    t0 = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    assert idem.claim(t, "s", "k", window_seconds=600, now=t0)["claimed"] is True
    assert idem.claim(t, "s", "k", window_seconds=600, now=t0 + timedelta(seconds=60))["claimed"] is False
    assert idem.claim(t, "s", "k", window_seconds=600, now=t0 + timedelta(seconds=601))["claimed"] is True


def test_release_hands_the_claim_back_without_a_delete():
    """The MCP role has PutItem and no DeleteItem — a release that needed a delete
    would silently fail in production and block every honest retry."""
    t = FakeTable()
    assert idem.claim(t, "s", "k")["claimed"] is True
    idem.release(t, "s", "k")
    assert not hasattr(t, "delete_item"), "the fake has no delete_item — a release that needed one would have failed here"
    assert idem.claim(t, "s", "k")["claimed"] is True


def test_the_ledger_fails_OPEN_so_a_broken_guard_never_swallows_a_write():
    class Broken:
        def put_item(self, **_kw):
            raise RuntimeError("throttled")

    result = idem.claim(Broken(), "s", "k")
    assert result["claimed"] is True and result["degraded"] is True


def test_only_a_conditional_failure_counts_as_a_duplicate():
    """Mutation guard on the error classification: if any exception were read as a
    duplicate, a throttled ledger would silently suppress real writes."""

    class Conditional:
        def put_item(self, **_kw):
            raise ConditionalCheckFailedException("nope")

        def get_item(self, Key):
            return {"Item": {"payload": {"id": "prior"}}}

    assert idem.claim(Conditional(), "s", "k")["claimed"] is False


def test_dedup_rows_live_in_their_own_partition():
    """A ledger row beside the records it guards would be returned by the tools'
    partition queries and counted as a decision / an insight."""
    t = FakeTable()
    idem.claim(t, "log_decision", "k")
    assert list(t.store)[0][0] == idem.LEDGER_PK
    assert "SOURCE#decisions" not in idem.LEDGER_PK


# ══════════════════════════════════════════════════════════════════════════════
# #3114 — log_decision / save_insight
# ══════════════════════════════════════════════════════════════════════════════


def test_log_decision_replay_writes_one_row_and_a_distinct_decision_still_writes(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(td, "_table_ref", t)
    args = {"decision": "Skip the evening lift", "source": "daily_brief", "followed": True, "date": "2026-08-24"}

    first = td.tool_log_decision(dict(args))
    replay = td.tool_log_decision(dict(args))
    assert first["status"] == "logged"
    assert replay["status"] == "duplicate" and replay["sk"] == first["sk"]
    assert len(rows(t, "DECISION#")) == 1

    # Count PUTS to the decisions partition, not stored rows: the sk is a millisecond
    # stamp, and two calls inside one millisecond (a test loop, never a human) share it.
    distinct = td.tool_log_decision(dict(args, decision="Take the rest day instead"))
    assert distinct["status"] == "logged"
    assert (
        len([p for p in t.put_calls if p["pk"].endswith("SOURCE#decisions")]) == 2
    ), "a genuinely different decision must still be recorded"


def test_save_insight_replay_writes_one_row_and_a_distinct_insight_still_writes(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(tl, "table", t)
    args = {"text": "Caffeine after 2pm wrecks deep sleep", "tags": ["sleep"], "source": "chat"}

    first = tl.tool_save_insight(dict(args))
    replay = tl.tool_save_insight(dict(args))
    assert first["saved"] is True
    assert replay["saved"] is False and replay["duplicate"] is True
    assert replay["insight_id"] == first["insight_id"]
    assert len(rows(t, "INSIGHT#")) == 1

    # The sk is second-granular, so two writes in the same second share it; count the
    # PUTS to the insights partition, which is what "did the write happen" means here.
    tl.tool_save_insight(dict(args, text="Zone 2 before breakfast feels better"))
    assert len([p for p in t.put_calls if p["pk"].endswith("SOURCE#insights")]) == 2


# ══════════════════════════════════════════════════════════════════════════════
# #3114 — the coach-correction ledger (log_coach_correction / audit_coach_dossier)
# ══════════════════════════════════════════════════════════════════════════════


def test_the_same_correction_derives_the_same_id_and_a_different_one_does_not():
    ref = {"surface": "dossier", "coach": "mind_coach", "record_sk": "PATTERN#1"}
    same = ccor.derive_correction_id(ref, "  You never  observed that. ", "framing")
    assert same == ccor.derive_correction_id(ref, "You never observed that.", "framing"), "whitespace is formatting, not identity"
    assert same != ccor.derive_correction_id(ref, "You never observed that.", "checkable-metric")
    assert same != ccor.derive_correction_id({**ref, "record_sk": "PATTERN#2"}, "You never observed that.", "framing")
    assert same == ccor.derive_correction_id(
        {"record_sk": "PATTERN#1", "coach": "mind_coach", "surface": "dossier"}, "You never observed that.", "framing"
    )


def test_a_replayed_correction_does_not_append_and_does_not_reset_its_status():
    t = FakeTable()
    ref = {"surface": "dossier", "coach": "mind_coach", "record_sk": "PATTERN#1"}
    sk = ccor.write_correction(t, ref, "That claim is not grounded.", "ungrounded-behavioral")
    # a downstream consumer moves it along
    t.store[(ccor.PK, sk)]["status"] = "applied-to-prompt"

    again = ccor.write_correction(t, ref, "That claim is not grounded.", "ungrounded-behavioral")
    assert again == sk
    assert len(rows(t, ccor.SK_PREFIX)) == 1
    assert t.store[(ccor.PK, sk)]["status"] == "applied-to-prompt", "a replay must not re-open a consumed correction"

    ccor.write_correction(t, ref, "Actually the number itself is wrong.", "checkable-metric")
    assert len(rows(t, ccor.SK_PREFIX)) == 2


def test_a_real_ddb_error_on_a_correction_write_still_raises():
    """Corrections are user-initiated feedback: a lost one must never be silent.
    Only a conditional failure may be swallowed."""

    class Broken:
        def put_item(self, **_kw):
            raise RuntimeError("throttled")

    with pytest.raises(RuntimeError):
        ccor.write_correction(Broken(), {"a": 1}, "text", "framing")


# ══════════════════════════════════════════════════════════════════════════════
# #3114 — manage_reading: log_session / add_note / debrief
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def reading_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(rs, "table", t)
    monkeypatch.setattr(tr, "table", t)
    return t


def _manage(**args):
    return tr.tool_manage_reading({"dry_run": False, **args})


def test_log_session_replay_is_suppressed_but_a_different_session_records(reading_table):
    args = {"action": "log_session", "bookId": "b1", "minutes": 30, "pages": 12, "date": "2026-08-24"}
    assert _manage(**args)["status"] == "committed"
    assert _manage(**args)["status"] == "duplicate"
    assert len(rows(reading_table, "SESSION#")) == 1

    assert _manage(**dict(args, minutes=45))["status"] == "committed"
    assert len(rows(reading_table, "SESSION#")) == 2


def test_add_note_replay_overwrites_in_place_and_a_new_note_still_lands(reading_table):
    args = {"action": "add_note", "bookId": "b1", "text": "The middle third is the whole argument."}
    first = _manage(**args)
    replay = _manage(**args)
    assert first["note"]["noteId"] == replay["note"]["noteId"], "the same text on the same book is the same note"
    assert len(rows(reading_table, "NOTE#")) == 1

    _manage(**dict(args, text="A different thought entirely."))
    assert len(rows(reading_table, "NOTE#")) == 2


def test_an_explicit_note_id_still_wins(reading_table):
    _manage(action="add_note", bookId="b1", text="why this book", note_id="coach-why", type="intention")
    assert rows(reading_table, "NOTE#coach-why")


def test_debrief_replay_never_starts_a_second_recall_clock(reading_table):
    """The #3114 headline. A replayed debrief used to write a second takeaway AND a
    second RECALL# probe, so the book's retention schedule silently doubled."""
    first = _manage(action="debrief", bookId="b1", takeaway="Attention is the scarce resource.")
    assert first["recall_clock"] == "started"
    probe = dict(rows(reading_table, "RECALL#")[0])

    replay = _manage(action="debrief", bookId="b1", takeaway="Attention is the scarce resource.")
    assert replay["recall_clock"].startswith("already running")
    assert len(rows(reading_table, "RECALL#")) == 1
    assert len(rows(reading_table, "NOTE#")) == 1
    assert rows(reading_table, "RECALL#")[0] == probe, "the running probe must be byte-identical — not re-put with a fresh nextDue"


def test_debrief_with_a_revised_takeaway_updates_the_note_but_leaves_the_clock(reading_table):
    _manage(action="debrief", bookId="b1", takeaway="First reading.")
    due = rows(reading_table, "RECALL#")[0]["nextDue"]
    out = _manage(action="debrief", bookId="b1", takeaway="On reflection: it is about attention.")
    assert out["note"]["text"] == "On reflection: it is about attention."
    assert len(rows(reading_table, "NOTE#")) == 1
    assert rows(reading_table, "RECALL#")[0]["nextDue"] == due


def test_debrief_recognises_a_LEGACY_timestamped_probe(reading_table):
    """Books debriefed before #3114 carry `probe-<timestamp>`. Missing those is how a
    second clock would get started on precisely the books that already had one."""
    rs.put_recall("b1", prompt_id="probe-20260101T090000", prompt="legacy", interval_index=2, next_due="2026-12-01")
    out = _manage(action="debrief", bookId="b1", takeaway="Late debrief.")
    assert out["recall_clock"].startswith("already running")
    assert len(rows(reading_table, "RECALL#")) == 1
    assert rows(reading_table, "RECALL#")[0]["intervalIndex"] == 2, "the legacy clock keeps its position"


# ══════════════════════════════════════════════════════════════════════════════
# #3114 — curate_horizon's follow-up check-in
# ══════════════════════════════════════════════════════════════════════════════


def test_the_prescription_followup_uid_is_content_derived():
    fu = {"type": "question", "text": "Did the essay change how you plan Sundays?"}
    a = cc.build_prescription_followup_item("2026-W30", "mind", dict(fu))
    b = cc.build_prescription_followup_item("2026-W30", "mind", dict(fu))
    c = cc.build_prescription_followup_item("2026-W30", "mind", {**fu, "text": "Something else entirely?"})
    assert a["sk"] == b["sk"] and a["sk"] != c["sk"]
    assert cc.new_checkin_sk() != cc.new_checkin_sk(), "a coach's freshly generated question is still uuid-keyed"


def test_a_replayed_curate_does_not_queue_the_followup_twice(reading_table, monkeypatch):
    from reading import horizons_verify

    monkeypatch.setattr(horizons_verify, "_urllib_fetch", lambda _u, _t: (200, b"x" * 500))
    monkeypatch.setattr(cc, "read_cycle", lambda *a, **k: 14)
    args = {
        "url": "https://example.com/essay",
        "title": "An Essay",
        "format": "essay",
        "rationale_tag": "topical",
        "week": "2026-W35",
        "dry_run": False,
        "follow_up_question": "What stuck?",
    }
    assert tr.tool_curate_horizon(dict(args))["status"] == "committed"
    queued = rows(reading_table, "CHECKIN#")
    assert len(queued) == 1
    reading_table.store[(queued[0]["pk"], queued[0]["sk"])]["status"] = "answered"

    assert tr.tool_curate_horizon(dict(args))["status"] == "committed"
    queued2 = rows(reading_table, "CHECKIN#")
    assert len(queued2) == 1, "a re-curate must not queue the same question again"
    assert queued2[0]["status"] == "answered", "and must not re-open one Matthew already answered"


# ══════════════════════════════════════════════════════════════════════════════
# #3115 — Todoist
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def todoist_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(tt, "table", t)
    return t


def test_create_todoist_task_replay_does_not_POST_twice(todoist_table):
    """Todoist mints a task id per call and offers no idempotency header, so the
    only thing between a retry and a duplicate task is this local claim."""
    args = {"content": "Book the dentist", "due_string": "Friday", "project_id": "p1"}
    with patch.object(tt, "_todoist_request", return_value={"id": 991, "content": "Book the dentist"}) as req:
        first = tt.create_todoist_task(dict(args))
        replay = tt.create_todoist_task(dict(args))
    assert req.call_count == 1, "the replay must never reach the vendor"
    assert first["created"] is True and first["task_id"] == "991"
    assert replay["created"] is False and replay["task_id"] == "991", "the replay echoes the REAL task id"


def test_a_different_task_still_reaches_todoist(todoist_table):
    with patch.object(tt, "_todoist_request", return_value={"id": 1, "content": "x"}) as req:
        tt.create_todoist_task({"content": "Book the dentist"})
        tt.create_todoist_task({"content": "Book the optician"})
    assert req.call_count == 2


def test_a_failed_create_releases_the_claim_so_an_honest_retry_works(todoist_table):
    """Fail-CLOSED is the danger here: if a failed POST kept its claim, the retry
    Matthew makes on purpose would be silently swallowed for the whole window."""
    calls = {"n": 0}

    def flaky(_method, _path, _payload=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Todoist API POST /tasks → 500")
        return {"id": 7, "content": "Book the dentist"}

    with patch.object(tt, "_todoist_request", side_effect=flaky):
        failed = tt.create_todoist_task({"content": "Book the dentist"})
        retried = tt.create_todoist_task({"content": "Book the dentist"})
    assert "error" in failed
    assert retried["created"] is True and retried["task_id"] == "7"


def test_close_todoist_task_refuses_a_replay(todoist_table):
    """On a RECURRING task, close ADVANCES the recurrence — a replay marks a future
    occurrence done that Matthew never did."""
    with patch.object(tt, "_todoist_request", return_value={}) as req:
        first = tt.close_todoist_task({"task_id": "42"})
        replay = tt.close_todoist_task({"task_id": "42"})
        other = tt.close_todoist_task({"task_id": "43"})
    assert req.call_count == 2, "one close per distinct task, and the replay never reached Todoist"
    assert first["closed"] is True
    assert replay["closed"] is False and "replay window" in replay["reason"]
    assert other["closed"] is True


# ══════════════════════════════════════════════════════════════════════════════
# #3115 — Hevy routines
# ══════════════════════════════════════════════════════════════════════════════


def test_a_routine_id_is_derived_from_the_session_it_programs():
    same = rg._new_routine_id("2026-08-24", "upper", "ideal")
    assert same == rg._new_routine_id("2026-08-24", "upper", "ideal")
    assert same != rg._new_routine_id("2026-08-24", "upper", "floor")
    assert same != rg._new_routine_id("2026-08-25", "upper", "ideal")
    assert len(same) == 32 and all(c in "0123456789abcdef" for c in same), "same shape uuid4().hex had"


def test_generate_routines_gives_the_same_ids_on_a_second_run():
    inputs = rg.GeneratorInputs(target_date="2026-06-01", recovery_tier="green", volume_7d={}, z2_minutes_7d=120)
    first = [r.routine_id for r in rg.generate_routines(inputs)]
    second = [
        r.routine_id
        for r in rg.generate_routines(rg.GeneratorInputs(target_date="2026-06-01", recovery_tier="green", volume_7d={}, z2_minutes_7d=120))
    ]
    assert first == second and len(set(first)) == len(first), "distinct variants keep distinct ids"


def _spec(version=1, **kw):
    from training.routine_ir import ExerciseBlock, RoutineSpec, Set

    base = dict(
        routine_id="rid-1",
        target_date="2026-06-01",
        archetype="upper",
        variant="ideal",
        version=version,
        status="draft",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
    )
    base.update(kw)
    return RoutineSpec(**base)


def test_a_redraft_becomes_the_next_version_and_carries_the_hevy_link(monkeypatch):
    stored = _spec(version=3, status="active", hevy_routine_id="hevy-abc", hevy_updated_at="2026-06-01T10:00:00Z", hevy_folder_id=9)
    puts = []
    monkeypatch.setattr(repo, "get_current", lambda _rid: stored)
    monkeypatch.setattr(repo, "put_versioned", lambda ir: puts.append(ir) or ir)

    fresh = _spec(version=1)
    out = repo.draft_versioned(fresh)
    assert out.version == 4 and out.parent_version == 3, "a re-draft is a new VERSION, never a second routine"
    assert out.hevy_routine_id == "hevy-abc", "carrying the link is what makes the next commit UPDATE instead of re-create"
    assert out.hevy_folder_id == 9
    assert puts == [fresh]


def test_a_redraft_does_NOT_resurrect_an_archived_routine(monkeypatch):
    stored = _spec(version=2, status="archived", hevy_routine_id="hevy-old")
    monkeypatch.setattr(repo, "get_current", lambda _rid: stored)
    monkeypatch.setattr(repo, "put_versioned", lambda ir: ir)
    out = repo.draft_versioned(_spec(version=1))
    assert out.version == 3 and not out.hevy_routine_id


def test_a_first_draft_is_a_plain_put(monkeypatch):
    monkeypatch.setattr(repo, "get_current", lambda _rid: None)
    monkeypatch.setattr(repo, "put_versioned", lambda ir: ir)
    out = repo.draft_versioned(_spec(version=1))
    assert out.version == 1 and out.parent_version is None


def test_the_version_counter_does_not_advance_on_a_refused_write(monkeypatch):
    """The census's quietest #3115 finding: `ir.version += 1` at the call site ran
    before the conditional put, so a RoutineConflict left the in-memory IR one
    version ahead of anything that exists."""

    class RefusingTable:
        def put_item(self, **_kw):
            raise repo._ddb.meta.client.exceptions.ConditionalCheckFailedException(
                {"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem"
            )

    monkeypatch.setattr(repo, "_table", RefusingTable())
    ir = _spec(version=5, parent_version=4)
    with pytest.raises(repo.RoutineConflict):
        repo.put_versioned(ir)
    assert ir.version == 4, "the counter must rewind to what is actually persisted"


def test_create_routine_links_an_existing_title_instead_of_posting_a_second_one():
    """The find-or-create shape `_ensure_folder` and `create_template` already had,
    which the routine create was the one write missing."""
    posted = []

    def _no_post(*a, **k):
        posted.append(a)
        raise AssertionError("create_routine must not POST when the routine already exists")

    listing = {"routines": [{"id": "hevy-99", "title": "Push A  #12", "updated_at": "2026-06-01T10:00:00Z"}]}
    with patch.object(wc, "list_routines", return_value=listing), patch.object(wc, "_request", side_effect=_no_post):
        resp = wc.create_routine({"routine": {"title": "Push A #12", "exercises": []}})
    assert resp["linked_existing"] is True
    assert resp["routine"]["id"] == "hevy-99"
    assert posted == []


def test_create_routine_still_posts_when_the_title_is_new():
    with patch.object(wc, "list_routines", return_value={"routines": [{"id": "x", "title": "Pull B #3"}]}):
        with patch.object(wc, "_request", return_value={"routine": {"id": "new-1"}}) as req:
            resp = wc.create_routine({"routine": {"title": "Push A #12", "exercises": []}})
    assert resp["routine"]["id"] == "new-1"
    assert req.call_args[0][0] == "POST"


def test_the_title_lookup_fails_SOFT_so_a_lookup_outage_never_blocks_a_push():
    """A blocked push is a session Matthew cannot train; a duplicate routine is a
    thing he can delete. The failure directions are not symmetric."""
    with patch.object(wc, "list_routines", side_effect=RuntimeError("Hevy 503")):
        assert wc.find_routine_by_title("Push A #12") is None


def test_the_title_lookup_walks_a_bounded_number_of_pages():
    pages = []

    def _listing(page=1, page_size=10):
        pages.append(page)
        return {"routines": [{"id": f"r{page}-{i}", "title": f"other {page}-{i}"} for i in range(page_size)]}

    with patch.object(wc, "list_routines", side_effect=_listing):
        assert wc.find_routine_by_title("Nowhere To Be Found") is None
    assert pages == list(range(1, wc.FIND_MAX_PAGES + 1)), "an unbounded walk turns one write into an open-ended read loop"
