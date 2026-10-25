"""tests/test_plan_stage2_latency_5313.py — plan_next_session stage 2 fits inside the MCP cap, and says so when it does not.

Live: request faaf5b99 (2026-10-25T00:26:57Z) ran stage 2 into the 30 s soft timeout; nothing
was stored, and the handler answered WRITE_IN_FLIGHT, "may still be completing" — false, because
the Lambda freezes when the response returns. Three changes, each held here:

  1. the four critics' model calls run CONCURRENTLY (`coach.critics_models`), with a bounded
     wait — proved with a barrier no sequential loop can pass, through the real stage-2 wiring;
  2. stage 2 makes each read ONCE: the Hevy history/bodyweight indexes (read twice before) and
     the 400-day Hevy read behind every drafted exercise (read once per exercise before) —
     proved by counting calls on fakes, plus the whole-charter deep copy `charter_value` made
     ~2,900 times per call;
  3. stage 2 refuses to START its write past `STAGE_2_WRITE_DEADLINE_SECS` (below the cap), so
     the handler's timeout message — "the red-team verdicts were NOT written" — is true by
     construction. The timing test with controllable latencies is the last test in the file.

Clock use: the concurrency proofs read a Barrier and an in-flight counter, not the clock (the
#3849 lesson). The one wall-time assertion bounds the critics' share of a real stage 2 — four
0.5 s fake calls, sequential floor 2.0 s — at 1.5 s, while the concurrent cost is ~0.5 s (3x
headroom on a busy runner); the deadline test monkeypatches the call clock instead of sleeping.
"""

from __future__ import annotations

import contextvars
import os
import threading
import time
from contextlib import ExitStack
from unittest.mock import patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import test_plan_critics_3752 as pc  # noqa: E402 — the pure-critic packets (tests/ is on sys.path)
import test_tools_plan_critics_3752 as base  # noqa: E402 — the stage-2 offline harness
from coach import critics, critics_models  # noqa: E402

from mcp import plan_call_scope  # noqa: E402

_APPROVE = {"content": [{"type": "text", "text": '{"verdict":"approve","metric":null,"sentence":"Fine."}'}], "stop_reason": "end_turn"}


def _packets():
    """The four packets from the pure-critic suite's own builder (test_plan_critics_3752._packets)."""
    d = critics.draft_summary(pc._ir())
    return d, pc._packets(d)


# ── 1. the critics run concurrently ─────────────────────────────────────────────
def test_the_four_critic_calls_are_in_flight_at_once():
    """A 4-party barrier: a sequential loop would hold the first call at the barrier forever (it
    times out and every verdict records a BrokenBarrierError). Mutation control: restore the
    sequential loop in `run_critics` -> every model entry is an error and this reds."""
    barrier = threading.Barrier(4, timeout=5)
    inflight, peak, lock = [0], [0], threading.Lock()

    def invoke(body):
        with lock:
            inflight[0] += 1
            peak[0] = max(peak[0], inflight[0])
        try:
            barrier.wait()
            return _APPROVE
        finally:
            with lock:
                inflight[0] -= 1

    d, packets = _packets()
    out = critics.run_critics(packets, d, invoke=invoke, model_allowed=True)
    assert [v["critic"] for v in out] == list(critics.CRITIC_IDS), "the verdict ORDER is still CRITIC_IDS"
    errors = {v["critic"]: (v.get("model") or {}).get("error") for v in out if (v.get("model") or {}).get("error")}
    assert not errors, f"a critic's call did not run beside the others: {errors}"
    assert peak[0] == 4


def test_a_slow_critic_is_cut_off_at_the_timeout_and_the_deterministic_layer_decides_it():
    """One reply that never comes must not hold stage 2: it is recorded as a TimeoutError on THAT
    critic, the other three keep their replies, and the call returns."""
    release = threading.Event()

    def invoke(body):
        if "You are the rate_advocate critic" in body["system"]:
            release.wait(10)
        return _APPROVE

    d, packets = _packets()
    try:
        out = critics.run_critics(packets, d, invoke=invoke, model_allowed=True, model_timeout_s=0.3)
    finally:
        release.set()
    by = {v["critic"]: v for v in out}
    assert "TimeoutError" in str(by["rate_advocate"].get("model")), by["rate_advocate"]
    assert by["rate_advocate"]["verdict"] in critics.VERDICTS, "the deterministic layer still issued a verdict"
    for cid in ("muscle_defense", "joints_tendons", "blueprint_historian"):
        assert not (by[cid].get("model") or {}).get("error"), by[cid]


def test_a_raising_call_is_recorded_on_its_verdict_never_raised():
    def invoke(body):
        if "You are the joints_tendons critic" in body["system"]:
            raise RuntimeError("ThrottlingException")
        return _APPROVE

    d, packets = _packets()
    by = {v["critic"]: v for v in critics.run_critics(packets, d, invoke=invoke, model_allowed=True)}
    assert by["joints_tendons"]["model"]["error"].startswith("RuntimeError: ThrottlingException")


def test_the_callers_context_reaches_every_worker():
    """`bedrock_client.attributed_to` labels spend through a ContextVar; a worker thread that did
    not inherit it would book the critics' spend to `unknown`."""
    label: contextvars.ContextVar[str | None] = contextvars.ContextVar("label_5313", default=None)
    seen = []

    def invoke(body):
        seen.append(label.get())
        return _APPROVE

    token = label.set("plan_critics")
    try:
        critics_models.model_verdicts({str(i): {"system": ""} for i in range(4)}, invoke, lambda r: r)
    finally:
        label.reset(token)
    assert seen == ["plan_critics"] * 4


def test_a_paused_tier_makes_no_model_call_at_all():
    calls = []
    d, packets = _packets()
    out = critics.run_critics(packets, d, invoke=lambda b: calls.append(b) or _APPROVE, model_allowed=False, model_paused_reason="tier 2")
    assert calls == [] and all(v["model"] == {"paused": "tier 2"} for v in out)


# ── 2. each read once ───────────────────────────────────────────────────────────
def test_the_history_indexes_are_read_once_per_plan_call_and_every_time_outside_one(monkeypatch):
    """The session loads (`tools_plan._load_anchor_indexes`) and the critics' floor clamp
    (`hevy_prescription_gate._load_indexes`) read the same full-partition index. Mutation control:
    drop the `scope(ANCHOR_INDEXES)` in `plan_call` -> 2 history reads and this reds."""
    from training import exercise_history

    from mcp import hevy_prescription_gate, tools_plan

    reads = {"history": 0, "bodyweight": 0}

    def history(lookback_days=None, today=None):
        reads["history"] += 1
        return {"T1": [{"date": "2026-10-20"}]}, {}

    def bodyweight(*a, **k):
        reads["bodyweight"] += 1
        return {"2026-10-20": 300.0}

    monkeypatch.setattr(exercise_history, "load_history_indexes", history)
    monkeypatch.setattr(exercise_history, "load_bodyweight_index", bodyweight)

    @plan_call_scope.plan_call
    def one_call():
        a = tools_plan._load_anchor_indexes()
        b = hevy_prescription_gate._load_indexes()
        return a, b

    (h1, w1), (h2, w2, err) = one_call()
    assert reads == {"history": 1, "bodyweight": 1}
    assert h1 is h2 and w1 is w2 and err is None
    tools_plan._load_anchor_indexes()
    hevy_prescription_gate._load_indexes()
    assert reads == {"history": 3, "bodyweight": 3}, "outside a plan call nothing is memoized (commit path, cron)"


def test_every_drafted_exercise_shares_one_400_day_hevy_read(monkeypatch):
    """Before #5313 `_gather_draft_evidence` read the Hevy partition once PER drafted exercise,
    over the identical window. Mutation control: drop the `scope(HEVY_ALL_PHASES)` around the
    exercise loop -> one read per exercise (2 here) and this reds."""
    from mcp import plan_draft_evidence, tools_strength

    windows = []

    def read(source, start, end, lean=False):
        windows.append((source, start, end))
        return []

    monkeypatch.setattr(tools_strength, "query_source_cross_phase", read)
    monkeypatch.setattr(plan_draft_evidence, "_resolver", lambda: (lambda key: key.split(":")[-1]))
    monkeypatch.setattr(plan_draft_evidence, "_core_anchor_identities", lambda: {})
    monkeypatch.setattr(plan_draft_evidence, "_workout_dates", lambda *a: [])
    monkeypatch.setattr(plan_draft_evidence, "_training_streaks", lambda *a: {"active_day_streak": 0, "loaded_lifting_streak": 0})
    monkeypatch.setattr("mcp.tools_training_notes.tool_get_exercise_notes", lambda args: {"error": "offline"})
    monkeypatch.setattr("mcp.tools_strength.template_alias_map", lambda: ({}, {"status": "offline"}))

    ev = plan_draft_evidence._gather_draft_evidence(base._ir(), "2026-10-25", "ok")
    assert len(ev["exercises"]) == 2
    long_reads = [w for w in windows if w[1] == "2025-09-20"]
    assert long_reads == [("hevy", "2025-09-20", "2026-10-25")], windows
    # and the memo closes with the loop: the same window read again outside it is a fresh read
    tools_strength._read_hevy_all_phases("2025-09-20", "2026-10-25")
    assert len([w for w in windows if w[1] == "2025-09-20"]) == 2


def test_a_raised_read_is_not_cached():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("blip")
        return "ok"

    with plan_call_scope.scope("k"):
        with pytest.raises(RuntimeError):
            plan_call_scope.memoized("k", "x", flaky)
        assert plan_call_scope.memoized("k", "x", flaky) == "ok"
        assert plan_call_scope.memoized("k", "x", flaky) == "ok"
    assert len(calls) == 2


def test_charter_value_copies_the_value_not_the_whole_charter(monkeypatch):
    """~2,900 charter_value calls per stage 2 each deep-copied the WHOLE merged charter. The value
    is still a private copy (mutating it cannot reach the cache)."""
    from training import training_charter as tc

    monkeypatch.setattr(tc, "load_charter", lambda: (_ for _ in ()).throw(AssertionError("charter_value must not copy the whole charter")))
    v = tc.charter_value("version")
    assert v is None or isinstance(v, str)
    whole = tc._cache or {}
    key = next((k for k, val in whole.items() if isinstance(val, dict)), None)
    if key is None:
        pytest.skip("no dict-valued charter key in this checkout")
    got = tc.charter_value(key)
    got["__mutated_5313__"] = True
    assert "__mutated_5313__" not in tc._cache[key]


# ── 3. the write deadline and the truthful timeout ──────────────────────────────
def test_the_write_deadline_sits_below_the_handler_cap_with_room_for_the_tail():
    from mcp import handler

    assert plan_call_scope.STAGE_2_WRITE_DEADLINE_SECS + 3 <= handler.TOOL_TIMEOUT_SECS
    assert plan_call_scope.MODEL_RESERVE_SECS < plan_call_scope.STAGE_2_WRITE_DEADLINE_SECS


def test_stage_2_past_its_write_deadline_stores_nothing_and_says_not_written(monkeypatch):
    """Mutation control: delete the `past_write_deadline()` guard in `_run_stage_2` -> the version is
    stored and this reds."""
    monkeypatch.setattr(plan_call_scope, "elapsed_secs", lambda: plan_call_scope.STAGE_2_WRITE_DEADLINE_SECS + 1.0)
    ir = base._ir()
    out, stored, thread = base._run(ir, base._evidence())
    crit = out["critics"]
    assert stored == [] and thread == [], "nothing may be written past the deadline"
    assert crit["written"] is False and crit["verdict_state"] == "not_written"
    assert crit["next"].startswith("NOT WRITTEN") and "NOT red-teamed" in crit["next"]
    assert "critics" not in (ir.inputs_snapshot or {}) and ir.version == 1
    assert "critics.written" in out["how_to_use"]


def test_a_landed_stage_2_says_so():
    out, stored, _thread = base._run(base._ir(), base._evidence())
    assert stored and out["critics"]["written"] is True and out["critics"]["verdict_state"] == "landed"


def test_a_timed_out_stage_2_is_told_its_verdicts_were_not_written():
    from mcp.handler import _timeout_error

    err = _timeout_error("plan_next_session", {"routine_id": "a035abae", "target_date": "2026-10-25"})
    assert err["error_code"] == "VERDICTS_NOT_WRITTEN" and err["kind"] == "transport"
    assert "verdicts were NOT written" in err["error"] and "a035abae" in err["error"]
    assert "in flight" not in err["error"].lower() and "may still" not in err["error"]


def test_a_timed_out_write_is_not_confirmed_and_a_read_is_still_too_broad():
    from mcp.handler import _timeout_error

    w = _timeout_error("manage_hevy_routine", {"action": "draft"})
    assert w["error_code"] == "WRITE_NOT_CONFIRMED" and "NOT confirmed" in w["error"]
    assert "may still" not in w["error"] and "in flight" not in w["error"].lower()
    s1 = _timeout_error("plan_next_session", {"target_date": "2026-10-25"})  # stage 1 names no routine
    assert s1["error_code"] != "VERDICTS_NOT_WRITTEN"
    r = _timeout_error("get_daily_summary", {})
    assert r["error_code"] == "QUERY_TOO_BROAD"


# ── the timing test: controllable latencies through the real stage-2 wiring ─────
def test_stage_2_pays_the_slowest_critic_not_the_sum_and_reads_the_indexes_once(monkeypatch):
    """Each fake critic call sleeps 0.5 s (2.0 s if sequential); the history-index fake sleeps
    0.2 s and counts. Stage 2 runs end to end through `tool_plan_next_session` (the real
    plan_call scope, `_run_stage_2`, `run_critics`, `critics_models`). Recorded on the PR."""
    from training import exercise_history

    reads = []

    def history(lookback_days=None, today=None):
        reads.append(lookback_days)
        time.sleep(0.2)
        return {}, {}

    monkeypatch.setattr(exercise_history, "load_history_indexes", history)
    monkeypatch.setattr(exercise_history, "load_bodyweight_index", lambda *a, **k: {})

    def slow_invoke(body):
        time.sleep(0.5)
        return _APPROVE

    ir = base._ir()
    ir.variant = "ideal"
    stored = []
    with ExitStack() as st:
        for cm in base._stage2_patches(ir, base._evidence(), invoke=slow_invoke, stored=stored):
            st.enter_context(cm)
        # the session loads read the index too: give stage 1's block a prescription so both readers run
        real_cb = __import__("training.plan_engine", fromlist=["constraint_block"]).constraint_block

        def with_rx(**kw):
            block = real_cb(**kw)
            block.setdefault("session", {}).setdefault("prescription", [{"slot": "anchor"}])
            return block

        st.enter_context(patch("training.plan_engine.constraint_block", side_effect=with_rx))
        st.enter_context(patch("training.load_ramp.annotate_prescription", return_value={"status": "fake"}))
        real_run, critic_wall = critics.run_critics, []

        def timed_run(*a, **kw):
            c0 = time.monotonic()
            try:
                return real_run(*a, **kw)
            finally:
                critic_wall.append(time.monotonic() - c0)

        st.enter_context(patch("coach.critics.run_critics", side_effect=timed_run))
        t0 = time.monotonic()
        out = __import__("mcp.tools_plan", fromlist=["x"]).tool_plan_next_session(
            {"target_date": "2026-09-20", "routine_id": ir.routine_id}
        )
        wall = time.monotonic() - t0
    crit = out["critics"]
    assert crit["written"] is True and stored, crit.get("next")
    assert all(not (v.get("model") or {}).get("error") for v in crit["verdicts"]), crit["verdicts"]
    assert len(reads) == 1, f"the history index was read {len(reads)}x in one stage 2 — the session loads and the floor clamp must share it"
    assert len(critic_wall) == 1
    print(
        f"\n[#5313 timing] stage 2 wall {wall:.2f}s; the critics' share {critic_wall[0]:.2f}s for 4 x 0.5 s calls "
        "(sequential floor 2.0 s); history index read 1x (0.2 s)"
    )
    assert critic_wall[0] < 1.5, f"the critics took {critic_wall[0]:.2f}s — the four 0.5 s calls ran one after another (sum 2.0 s)"
