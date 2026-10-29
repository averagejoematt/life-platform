"""tests/test_stage2_dry_run_4076.py — stage 2's side-effect-free dry run (#4076).

The 2026-10-28 synthetic proof of the owner-override path was blocked because a real stage-2 run
WRITES: the routine's new version + VERSION#current + a `routine_index` row (`put_versioned`), the
`#critics` training-coach thread row keyed by today (`_write_thread`, which can overwrite tonight's
real row), and the corrections-ledger row for an applied override. `plan_next_session(routine_id,
dry_run=true)` runs the same critics, the same override and the same change application, writes
none of the three and returns each put under `critics.would_write`.

What these tests hold, on the 09-22 shape (the historian vetoes, the owner overrides it) with a
DETERMINISTIC joints change beside it — the stale-lift cap (#4161), the change that was lost on
09-22 when stage 2 was skipped:

  * dry run: ZERO writes — every DynamoDB table the path writes is a fake that records puts, the
    botocore API layer and urllib (the Hevy client's transport) are sentinels — and the result
    still carries the overridden plan with the joints cap applied, plus the would-be items;
  * mutation control: the identical run WITHOUT dry_run makes exactly the puts the dry run listed
    (same tables, same keys, same order) — so the dry run's silence is the flag, not a dead path;
  * the tool schema exposes `dry_run` (no new tool — tests/test_wiring_coverage.py holds the count).
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from fakes import FakeDdbTable  # noqa: E402
from test_critic_veto_override_4076 import WORDS, _fixture_evidence, _reply, _routine  # noqa: E402
from test_tools_plan_critics_3752 import _approving, _stage2_patches  # noqa: E402

from mcp import tools_plan as tp  # noqa: E402

TEST_WORDS = "TEST #4076 synthetic proof — " + WORDS
# A gap of 93 days on exposure 1 is the `short` class: cap 2 working sets (critics_fatigue.STALE_CAPS).
STALE = {"exposure": 1, "gap_days": 93, "gap_class": "short"}
_WRITE_OPS = {"PutItem", "UpdateItem", "DeleteItem", "BatchWriteItem", "TransactWriteItems", "PutObject", "CopyObject", "DeleteObject"}


def _model(body):
    """The historian escalates to a veto (the 09-22 shape); every other critic approves — the joints
    cap below is the deterministic, governed stale-lift change, which no model reply can soften."""
    if "blueprint_historian" in body["system"]:
        return _reply({"verdict": "veto", "metric": "band_top_lbs[0]", "value": 198.4, "field": None, "to": None, "sentence": "Too heavy."})
    return _approving(body)


def _evidence():
    ev = _fixture_evidence()
    ev["exercises"][1]["stale"] = dict(STALE)  # Move 1: 4 working sets drafted, back after 93 days
    return ev


def _run(*, dry_run, override=True):
    """One stage-2 run with the REAL writers (`put_versioned`, `_write_thread`, `_record_override_correction`)
    over fake tables. Returns (out, ir, routine_table, config_table, api_calls, http_calls)."""
    ir = _routine()
    routine_table, config_table = FakeDdbTable(), FakeDdbTable()
    api_calls, http_calls = [], []

    def api(self, operation_name, params):
        # Every botocore call is recorded and refused — reads fail soft (the readers' own contract), so a
        # WRITE op in this list is a write that bypassed the fake tables (S3 PutObject, a raw client put).
        api_calls.append(operation_name)
        raise ConnectionError(f"offline test: {operation_name}")

    def http(*a, **kw):
        http_calls.append(a)
        raise AssertionError("no HTTP (Hevy) call may leave stage 2")

    args = {"target_date": "2026-09-22", "routine_id": ir.routine_id}
    if override:
        args["veto_override"] = {"critic": "blueprint_historian", "owner_words": TEST_WORDS}
    if dry_run:
        args["dry_run"] = True
    real_writers = ("_write_thread", "put_versioned")
    with ExitStack() as st:
        for cm in _stage2_patches(ir, _evidence(), invoke=_model):
            if getattr(cm, "attribute", None) not in real_writers:  # the writers run for real, over the fakes
                st.enter_context(cm)
        st.enter_context(patch("training.routine_repo._table", routine_table))
        st.enter_context(patch("mcp.config.table", config_table))
        st.enter_context(patch("coach.coach_checkin.read_cycle", return_value=17))
        st.enter_context(patch("mcp.tools_plan._readiness_low_streak", return_value=(0, {"state": "measured"})))
        st.enter_context(patch("botocore.client.BaseClient._make_api_call", api))
        st.enter_context(patch("urllib.request.urlopen", http))
        out = tp.tool_plan_next_session(args)
    return out, ir, routine_table, config_table, api_calls, http_calls


def _joints_cap(crit):
    return [c for c in crit["changes"] if c["critic"] == "joints_tendons" and c["field"] == "exercises[1].set_count"]


def _keys(rows):
    return [(r["pk"], r["sk"]) for r in rows]


def test_dry_run_writes_nothing_and_returns_the_overridden_plan_with_the_joints_cap():
    """Mutation controls: (a) delete the `if dry_run: return ...dry_run_result(...)` branch in `_run_stage_2`
    -> the routine table gets 3 puts and this reds; (b) pass `_record_override_correction` unconditionally
    as `record_correction` -> the ledger row lands on the config table and this reds; (c) drop the
    `dry_run=` argument at the `_run_stage_2` call site -> every write lands and this reds."""
    out, ir, routine_table, config_table, api_calls, http_calls = _run(dry_run=True)
    assert "error" not in out, out
    crit = out["critics"]

    # zero writes, anywhere
    assert routine_table.puts == [] and config_table.puts == [], (routine_table.puts, config_table.puts)
    assert routine_table.updates == config_table.updates == [] and routine_table.deletes == config_table.deletes == []
    assert not set(api_calls) & _WRITE_OPS and http_calls == [], api_calls
    assert crit["written"] is False and crit["verdict_state"] == "dry_run" and crit["dry_run"] is True
    assert crit["thread"]["written"] is False and crit["next"].startswith("DRY RUN — nothing was written")

    # the override path ran for real: the historian still said veto, carries his words verbatim, no veto stands
    hist = next(v for v in crit["verdicts"] if v["critic"] == "blueprint_historian")
    assert hist["verdict"] == "veto" and hist["owner_override"]["owner_words"] == TEST_WORDS
    assert crit["veto"] is False and crit["recheck"]["passed"] is True
    [rec] = crit["owner_overrides"]
    assert rec["applied"] is True and rec["owner_words"] == TEST_WORDS and "OVERRIDDEN" in crit["next"]

    # the joints critic's set cap is APPLIED beside the override — the change 09-22 lost
    [cap] = _joints_cap(crit)
    assert cap["applied"] is True and cap["to"] == 2, crit["changes"]
    assert len(ir.exercises[1].sets) == 2 and sum(len(e.sets) for e in ir.exercises) == 18

    # and every put a real run makes is returned, in write order, with the routine the commit would read
    kinds = [w["kind"] for w in crit["would_write"]]
    assert kinds == ["corrections_ledger", "routine_version", "routine_current", "routine_index", "coach_thread"], kinds
    ledger, _, current, index, thread = crit["would_write"]
    assert ledger["item"]["correction_text"] == TEST_WORDS and ledger["sk"] == rec["correction_id"]
    assert ledger["item"]["item_ref"]["critic"] == "blueprint_historian" and ledger["item"]["cycle"] == 17
    assert current["sk"] == "VERSION#current" and len(current["item"]["exercises"][1]["sets"]) == 2
    stored = current["item"]["inputs_snapshot"]["critics"]
    assert stored["owner_overrides"][0]["owner_words"] == TEST_WORDS and stored["veto"] is False
    assert index["pk"].endswith("#SOURCE#routine_index") and index["sk"] == "DATE#2026-09-22#ROUTINE#r-4076"
    assert thread["sk"].endswith("#critics") and thread["item"]["owner_overrides"][0]["owner_words"] == TEST_WORDS
    json.dumps(out, default=str)  # the MCP response serialises


def test_without_dry_run_the_same_run_makes_exactly_the_puts_the_dry_run_listed():
    """The mutation control for the test above: the identical run, no dry_run -> the writes ARE made, on the
    tables the dry run named, with the keys it named, in its order. Mutation control: make `put_versioned`
    skip the index put -> the key lists differ and this reds."""
    dry, *_ = _run(dry_run=True)
    live, ir, routine_table, config_table, api_calls, http_calls = _run(dry_run=False)
    crit = live["critics"]
    assert crit["written"] is True and crit["verdict_state"] == "landed" and "would_write" not in crit
    assert len(routine_table.puts) == 3 and len(config_table.puts) == 2, (routine_table.puts, config_table.puts)
    assert not set(api_calls) & _WRITE_OPS and http_calls == []

    by_kind = {w["kind"]: w for w in dry["critics"]["would_write"]}
    routine_kinds = ["routine_version", "routine_current", "routine_index"]
    assert _keys(routine_table.puts) == _keys([by_kind[k] for k in routine_kinds])
    assert _keys(config_table.puts) == _keys([by_kind["corrections_ledger"], by_kind["coach_thread"]])
    # same plan either way: the joints cap applied, the historian overridden
    assert _joints_cap(crit)[0]["applied"] is True and len(ir.exercises[1].sets) == 2
    assert routine_table.puts[1]["exercises"][1]["sets"] == by_kind["routine_current"]["item"]["exercises"][1]["sets"]


def test_dry_run_without_an_override_leaves_the_veto_standing_and_lists_no_ledger_row():
    out, ir, routine_table, config_table, api_calls, _ = _run(dry_run=True, override=False)
    crit = out["critics"]
    assert crit["veto"] is True and crit["owner_overrides"] == [] and "a veto STANDS" in crit["next"]
    assert [w["kind"] for w in crit["would_write"]] == ["routine_version", "routine_current", "routine_index", "coach_thread"]
    assert routine_table.puts == config_table.puts == [] and not set(api_calls) & _WRITE_OPS
    assert _joints_cap(crit)[0]["applied"] is True, "the cap is applied to the draft with or without the veto"


def test_a_dry_run_past_the_write_deadline_still_returns_its_would_be_writes():
    """The #5313 deadline guards a WRITE racing the MCP cap; a dry run writes nothing, so it is not refused
    (a laptop proof run's prod reads can pass 26 s). Mutation control: gate `late` on the deadline alone ->
    the result is `not_written` with no `would_write` and this reds."""
    with patch("mcp.plan_call_scope.past_write_deadline", return_value="NOT WRITTEN — late"):
        out, *_ = _run(dry_run=True)
        live, _, routine_table, *_ = _run(dry_run=False)
    assert out["critics"]["verdict_state"] == "dry_run" and len(out["critics"]["would_write"]) == 5
    assert live["critics"]["verdict_state"] == "not_written" and routine_table.puts == [], "the real run still refuses late"


def test_put_versioned_writes_exactly_versioned_items():
    """The dry run's routine items come from `routine_repo.versioned_items` — the SAME builder `put_versioned`
    writes from. Mutation control: hand-build any one item in `put_versioned` differently -> this reds."""
    from training import routine_repo

    ir, table = _routine(), FakeDdbTable()
    expected = routine_repo.versioned_items(_routine())
    with patch.object(routine_repo, "_table", table):
        routine_repo.put_versioned(ir)
    assert table.puts == expected


def test_the_tool_schema_exposes_dry_run():
    from mcp.registry import TOOLS

    props = TOOLS["plan_next_session"]["schema"]["inputSchema"]["properties"]
    assert props["dry_run"]["type"] == "boolean" and "would_write" in props["dry_run"]["description"]
    assert set(props) == {"target_date", "routine_id", "veto_override", "dry_run"}
