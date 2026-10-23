"""tests/test_may_tracker_coach_context_5200.py — the May tracker reaches the coach context on every caller path (#5200).

Before: `mcp.plan_helpers.coach_context_for` passed no tracker to `training.coach_context.assemble`, so every MCP
caller (plan_next_session, the nightly pre-draft, the session packet) listed `may_tracker` under `not_supplied`
although the weekly row existed; the Telegram training route did the same. Held here:
  * `may_tracker.latest_completed_row` reads the newest stored week whose Sunday is before the target date
    (`measured`), names an older one `stale` (still supplied), and states `absent` / `read_failed` distinctly;
  * each MCP caller path (the three entry points in `plan_helpers`, with the args each caller passes), over a fake
    table holding a real `build_week` row, supplies the tracker and drops it from `not_supplied`; with no row the
    section is the honest `not_supplied` with its reason;
  * the packet's absence on plan_next_session and the pre-draft is explained in `not_supplied_reason`;
  * the Telegram training route reads the same row;
  * every `coach_context.assemble(` call outside the assembly module passes a tracker (the class, not the specimen).

Mutation (run): drop `tracker=_may_tracker(target_date)` from `plan_helpers.coach_context_for` -> the caller-path
test reds on all three paths; drop `tracker=tracker` from `coach_domain_facts._training_context` -> the Telegram
test and the source sweep red.

No clock: every date is an argument (#4848); no live table read, no model call.
"""

# premerge-gate: #5200: rglob sweep of lambdas/ and mcp/ for coach_context.assemble calls that pass no tracker

from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import may_tracker as mt  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parent.parent
MON, SUN = "2026-10-12", "2026-10-18"
TARGET = "2026-10-20"  # its newest completed week is MON..SUN
FLOOR = float(charter_value("governing_goal.rate_band_lb_per_wk.floor"))


def _row(monday: str = MON) -> dict:
    sun = mt.shift(monday, 6)
    weight = mt.weight_section(
        sun,
        {"rate_lb_wk": FLOOR + 0.2, "counted": True, "status": "complete", "n_weighins": 6},
        {"rate_lb_wk": FLOOR + 0.2, "provisional": False},
        (sun, 300.0),
        None,
    )
    steps = mt.steps_section([{"date": mt.shift(monday, i), "steps": 13000, "degraded": None} for i in range(7)])
    return mt.build_week(
        monday,
        weight=weight,
        waist=mt.waist_section([], sun),
        steps=steps,
        anchors=mt.anchors_section({}, sun),
        volume=mt.volume_section({"muscles": {}}),
        fitness=mt.fitness_section(None),
    )


class _Table:
    """The tracker partition: honours the `sk BETWEEN :lo AND :hi` key condition and the newest-first order."""

    def __init__(self, rows=(), fail=False):
        self.rows, self.fail, self.calls = list(rows), fail, []

    def query(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("down")
        v = kw["ExpressionAttributeValues"]
        hits = [r for r in self.rows if r["pk"] == v[":pk"] and v.get(":lo", "") <= r["sk"] <= v.get(":hi", "￿")]
        hits.sort(key=lambda r: r["sk"], reverse=not kw.get("ScanIndexForward", True))
        return {"Items": hits[: kw.get("Limit", 100)]}


# ── the read ────────────────────────────────────────────────────────────────────────────
def test_latest_completed_row_states_measured_stale_absent_and_read_failed():
    got = mt.latest_completed_row(_Table([_row("2026-10-05"), _row(MON)]), TARGET)
    assert got["state"] == "measured" and got["row"]["week_start"] == MON and got["expected_week_start"] == MON
    # a week that has not completed by the target date is never the context's row
    early = mt.latest_completed_row(_Table([_row("2026-10-05"), _row(MON)]), SUN)
    assert early["state"] == "measured" and early["row"]["week_start"] == "2026-10-05"
    stale = mt.latest_completed_row(_Table([_row("2026-10-05")]), TARGET)
    assert stale["state"] == "stale" and stale["row"]["week_start"] == "2026-10-05" and MON in stale["detail"]
    assert mt.latest_completed_row(_Table(), TARGET)["state"] == "absent"
    failed = mt.latest_completed_row(_Table(fail=True), TARGET)
    assert failed["state"] == "read_failed" and failed["error"] == "RuntimeError" and failed["row"] is None


# ── every MCP caller path ───────────────────────────────────────────────────────────────
def _paths(r):
    """Each caller's entry, called the way the caller calls it (tools_plan, nightly_predraft, tools_coach_packet)."""
    packet = {"packet_version": "coach-session-packet@test", "fields": {"loss_rate": {"state": "measured", "source": "x", "value": 1}}}
    return {
        "plan_next_session": lambda: r.attach_coach_context(
            {}, TARGET, constraint_block={"program_week": 7}, packet_reason=r.PACKET_NOT_REREAD
        )["coach_context"],
        "nightly_predraft": lambda: r.coach_context_brief(TARGET),
        "get_coach_session_packet": lambda: r.attach_coach_context({}, TARGET, packet=packet)["coach_context"],
    }


def _wire(monkeypatch, table):
    from mcp import config, plan_helpers as r

    monkeypatch.setattr(r, "_clinical_guidance", lambda: [])
    monkeypatch.setattr(config, "table", table)
    return r


def test_every_caller_path_supplies_the_tracker_and_drops_it_from_not_supplied(monkeypatch):
    r = _wire(monkeypatch, _Table([_row(MON)]))
    offenders = []
    for name, call in _paths(r).items():
        ctx = call()
        if ctx.get("states", {}).get("may_tracker") != "measured" or "may_tracker" in (ctx.get("not_supplied") or []):
            offenders.append((name, ctx.get("states"), ctx.get("not_supplied")))
        elif ctx.get("may_tracker_week") != MON:
            offenders.append((name, "week", ctx.get("may_tracker_week")))
        elif "text" in ctx and f"week: {MON}..{SUN}" not in ctx["text"]:
            offenders.append((name, "the tracker week is not in the prompt text"))
    assert not offenders, offenders


def test_with_no_row_every_caller_path_states_the_honest_not_supplied(monkeypatch):
    r = _wire(monkeypatch, _Table())
    offenders = []
    for name, call in _paths(r).items():
        ctx = call()
        reason = (ctx.get("not_supplied_reason") or {}).get("may_tracker") or ""
        if "may_tracker" not in (ctx.get("not_supplied") or []) or "no May-tracker week" not in reason:
            offenders.append((name, ctx.get("not_supplied"), reason))
    assert not offenders, offenders


def test_a_failed_tracker_read_is_named_never_not_supplied(monkeypatch):
    r = _wire(monkeypatch, _Table(fail=True))
    ctx = r.coach_context_brief(TARGET)
    assert ctx["states"]["may_tracker"] == "read_failed" and "may_tracker" not in ctx["not_supplied"]


def test_the_packet_absence_is_explained_on_plan_next_session_and_the_predraft(monkeypatch):
    r = _wire(monkeypatch, _Table([_row(MON)]))
    paths = _paths(r)
    plan = paths["plan_next_session"]()
    assert plan["not_supplied"] == ["plan_packet"] and plan["not_supplied_reason"]["plan_packet"] == r.PACKET_NOT_REREAD
    brief = paths["nightly_predraft"]()
    assert brief["not_supplied_reason"]["plan_packet"] == r.PACKET_NOT_READ_PREDRAFT
    assert "plan_packet" not in paths["get_coach_session_packet"]()["not_supplied"]
    src = (_REPO / "mcp" / "tools_plan.py").read_text()
    assert "packet_reason=PACKET_NOT_REREAD" in src, "plan_next_session must state why it carries no packet"


def test_the_nightly_tracker_leg_runs_before_the_draft_reads_its_context(monkeypatch):
    from mcp import nightly_predraft as npd

    order = []
    monkeypatch.setattr(npd, "_may_tracker_leg", lambda: order.append("tracker") or {"outcome": "written"})
    monkeypatch.setattr(npd, "run", lambda t: order.append("run") or {"outcome": npd.FAILED})
    for leg in ("_fitness_battery_leg", "_calibration_leg", "_titration_leg"):
        monkeypatch.setattr(npd, leg, lambda: {})
    npd.lambda_entry({})
    assert order == ["tracker", "run"]


# ── the Telegram training route ─────────────────────────────────────────────────────────
def test_the_telegram_training_route_reads_the_same_tracker_row():
    from coach import coach_domain_facts as df

    text = df._training_context(TARGET, "CLINICAL BLOCK", _Table([_row(MON)]))
    assert f"week: {MON}..{SUN}" in text and "not supplied: this caller read no May tracker" not in text
    assert "no May-tracker week through" in df._training_context(TARGET, "CLINICAL BLOCK", _Table())


# ── the class: no assembly caller skips the tracker ─────────────────────────────────────
def test_every_assemble_call_outside_the_module_passes_a_tracker():
    """The set: every `coach_context.assemble(...)` call in lambdas/ and mcp/ (git-tracked sources, not tests)."""
    offenders, seen = [], 0
    for root in ("lambdas", "mcp"):
        for path in sorted((_REPO / root).rglob("*.py")):
            if path.name == "coach_context.py" or "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                f = getattr(node, "func", None)
                if isinstance(node, ast.Call) and isinstance(f, ast.Attribute) and f.attr == "assemble":
                    if not (isinstance(f.value, ast.Name) and f.value.id == "coach_context"):
                        continue
                    seen += 1
                    if "tracker" not in {k.arg for k in node.keywords}:
                        offenders.append(f"{path.relative_to(_REPO)}:{node.lineno}")
    assert seen >= 2, "the sweep found no assemble callers — it is not looking"
    assert not offenders, offenders
