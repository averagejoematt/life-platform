"""tests/test_fuel_loop_5792.py — a tripped protein, fat or fibre floor rebuilds the menu, its grocery list and ONE
Todoist prep task, at most once per macro per ISO week (#5792, `mcp.fuel_loop`).

Holds:
  1. A TRIPPED WEEK (all three floors) -> exactly one menu build and exactly one Todoist POST, dated tomorrow, the
     menu and the shop in the task; the run result carries no food (the foods ride only in his private task).
  2. NEGATIVE CONTROL: a second run in the same ISO week builds nothing and posts nothing. The next ISO week fires again.
     MUST-FAIL: with the idempotency key varied per call (the guard removed) the second run DOES post — so the
     negative control is not passing for an unrelated reason.
  3. A FAT-ONLY and a FIBRE-ONLY trigger, each counted by `macro_floors.evaluate_day` against the tripwire's own
     `threshold_days` (read, never typed).
  4. A day the menu cannot fit is reported with its misses named (weekly_menu's own report), in the result and the task.
  5. A Todoist failure is reported in the run result and the claims are released, so the next night retries.
  6. A failed read is `read_failed` (never tripped, never clear); a degraded ledger posts nothing.
  7. ONE evaluation: plan_engine's `protein_floor_missed` row and `floor_days_state` agree on every count.
  8. The nightly pre-draft carries the leg on its result and its summary line.

Invented placeholder foods (the repo is public); synthetic intake values (0 g = below any floor, 10 000 g = above).
No AWS, no network (the Todoist HTTP and the ledger table are faked), no clock (every date is fixed), no model.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
from unittest.mock import patch

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from health import weekly_menu as wm  # noqa: E402
from training import food_panel, owner_redlines, plan_engine, training_charter as tc  # noqa: E402

from mcp import fuel_loop as fl, tools_todoist  # noqa: E402

TODAY = "2026-10-25"  # a Sunday: the window is 2026-10-26..2026-11-01, one ISO week; the claim week is 2026-W43
WEEK = "2026-10-26"
LIFTING = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
LOW, HIGH = 0.0, 10000.0  # synthetic: below / above any floor the charter could carry


def _food(fid, kcal, p, c, f, fib, **extra):
    return {"id": fid, "label": f"placeholder {fid}", "serving": "1 test serving", "kcal": kcal, "protein_g": p, "carb_g": c,
            "fat_g": f, "fibre_g": fib, **extra}  # fmt: skip


ANCHORS = [
    _food("t_isolate", 100, 24, 0.5, 0.4, 0, package={"label": "test tub", "servings": 10}),
    _food("t_lean", 120, 26, 0, 1.5, 0),
    _food("t_white", 90, 20, 1, 0.5, 0),
    _food("t_fish", 200, 22, 0, 12, 0, fatty_fish=True, nutrient_tags=["omega3"]),
    _food("t_egg", 70, 6, 0.5, 5, 0),
    _food("t_veg", 25, 2, 5, 0.2, 4, max_per_day=6),
    _food("t_berry", 60, 1.5, 14, 0.7, 8),
    _food("t_seed", 60, 2, 5, 4, 5),
    _food("t_oil", 120, 0, 0, 14, 0),
    _food("t_nut", 165, 6, 6, 14, 3.5),
    _food("t_bean", 120, 8, 20, 0.5, 7),
]
UNFITTABLE = [_food(f"t_fat{i}", 150, 25, 1, 10, 0) for i in range(6)] + [_food("t_fibre", 30, 1, 6, 0, 5)]


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(tc, "_load_private", lambda: tc._from_env(tc.PRIVATE_ENV_VAR))
    tc.reset_cache()
    yield
    tc.reset_cache()


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    """Every run injects its day; the Pacific clock is pinned to the same constant anyway, so a path that falls back to
    `pacific_today()` (calorie_target.resolve's lazy read, run()'s default) can never desync from the fixture dates."""
    from common import pacific_time

    monkeypatch.setattr(pacific_time, "pacific_today", lambda: TODAY)


class ConditionalCheckFailedException(Exception):
    pass


class FakeTable:
    """The claim ledger's semantics (mcp.idempotency.claim's ConditionExpression), in memory."""

    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeValues=None):
        k = (Item["pk"], Item["sk"])
        old = self.items.get(k)
        if ConditionExpression and old is not None and not old.get("released"):
            cutoff = (ExpressionAttributeValues or {}).get(":cutoff")
            if cutoff is None or old["claimed_at"] >= cutoff:
                raise ConditionalCheckFailedException("ConditionalCheckFailedException")
        self.items[k] = dict(Item)

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it else {}


class BrokenTable:
    def put_item(self, **kw):
        raise RuntimeError("ProvisionedThroughputExceededException")

    def get_item(self, **kw):
        raise RuntimeError("down")


def _titration_record():
    band = tc.charter_value("nutrition.calories.prescribed_band_kcal")
    return {
        "week": WEEK, "action": "hold", "step_kcal": 0, "kcal": tc.charter_value("nutrition.calories.target_kcal"),
        "band_low": band[0], "band_high": band[1], "position": "in", "reason_code": "in_band", "reason": "in the band: hold",
        "charter_version": tc.charter_value("version"),
        "inputs": {"steps_avg": tc.charter_value("steps.floor"), "steps_floor": tc.charter_value("steps.floor")},
    }  # fmt: skip


def _rows(fat, fibre, start="2026-10-18", n=7):
    """Synthetic MacroFactor day rows over the protein-gate window (the 7 completed days ending yesterday)."""
    from common.pacific_time import shift_day_key

    return [{"date": shift_day_key(start, i), "total_fat_g": fat, "total_fiber_g": fibre} for i in range(n)]


class Harness:
    """One run's collaborators: the readers, a counting menu build over the real `weekly_menu.build`, the real
    `create_todoist_task` with its HTTP faked, and the shared fake ledger."""

    def __init__(self, *, protein=(6, 7), fat=LOW, fibre=LOW, anchors=None, post=None):
        self.table = FakeTable()
        self.protein, self.fat, self.fibre = protein, fat, fibre
        self.anchors = ANCHORS if anchors is None else anchors
        self.builds, self.posts = [], []
        self.post = post or (lambda payload: {"id": f"task-{len(self.posts)}", "content": payload["content"], "project_id": "inbox"})

    def plan_reader(self, week):
        rec = _titration_record()
        return food_panel.build_food_plan(week, planned_dates=LIFTING, titration_reader=lambda w: rec, case_id="fuel-loop-test")

    def build(self, plan):
        self.builds.append([d["date"] for d in plan["days"]])
        return wm.build(plan, anchors_raw=copy.deepcopy(self.anchors))

    def _request(self, method, path, payload=None):
        assert (method, path) == ("POST", "/tasks"), (method, path)
        self.posts.append(payload)
        return self.post(payload)

    def run(self, today=TODAY, **kw):
        # The tool's own create guard is a 15-minute window; the nightly runs are a day apart, so it is opened here —
        # what stops the second run must be the fuel loop's (macro, ISO week) claim, not the tool's replay window.
        with (
            patch.object(tools_todoist, "_todoist_request", self._request),
            patch.object(tools_todoist, "table", self.table),
            patch.object(tools_todoist, "_CREATE_WINDOW_SECONDS", -1),
        ):
            return fl.run(
                today,
                protein_reader=lambda d: self.protein,
                rows_reader=lambda s, e: _rows(self.fat, self.fibre, start=s),
                plan_reader=self.plan_reader,
                build=self.build,
                table=self.table,
                **kw,
            )


def _threshold():
    return next(t for t in owner_redlines.TRIPWIRES if t["id"] == "protein_floor_missed")["threshold_days"]


# ── 1 + 2. one menu, one task; the same week again is nothing ─────────────────────────────────────────────────
def test_a_tripped_week_builds_one_menu_and_posts_one_task_and_a_second_run_in_the_week_does_nothing():
    h = Harness()
    first = h.run()
    problems = []
    if first["outcome"] != fl.TASK_CREATED or first["fired"] != ["protein", "fat", "fibre"]:
        problems.append(f"first run: {first['outcome']} fired {first['fired']}")
    if len(h.builds) != 1 or h.builds[0] != fl.window_days(TODAY):
        problems.append(f"menu builds: {h.builds}")
    if len(h.posts) != 1:
        problems.append(f"Todoist POSTs: {len(h.posts)}")
    else:
        task = h.posts[0]
        if task.get("due_date") != "2026-10-26":
            problems.append(f"due date {task.get('due_date')}")
        if "protein, fat and fibre" not in task["content"]:
            problems.append(f"content does not name the macros: {task['content']}")
        if "placeholder t_" not in task.get("description", "") or "Grocery list" not in task.get("description", ""):
            problems.append("the task carries no menu or no grocery list")
    if "placeholder" in json.dumps(first, default=str):
        problems.append("a food name reached the run result (the CloudWatch log)")
    second = h.run()
    if second["outcome"] != fl.ALREADY_DONE or len(h.builds) != 1 or len(h.posts) != 1:
        problems.append(f"second run in the same ISO week: {second['outcome']}, builds {len(h.builds)}, posts {len(h.posts)}")
    same_week_later = h.run("2026-10-24")  # the Saturday before: ISO week 2026-W43 too
    if same_week_later["outcome"] != fl.ALREADY_DONE or len(h.posts) != 1:
        problems.append(f"another day of the same ISO week: {same_week_later['outcome']}, posts {len(h.posts)}")
    next_week = h.run("2026-11-01")  # ISO week 2026-W44: the loop fires again
    if next_week["outcome"] != fl.TASK_CREATED or len(h.posts) != 2:
        problems.append(f"the next ISO week: {next_week['outcome']}, posts {len(h.posts)}")
    assert not problems, "\n".join(problems)


def test_must_fail_without_the_idempotency_key_the_second_run_posts_again(monkeypatch):
    """The mutation the negative control must catch: a key that is not stable across runs (the guard removed)."""
    calls = iter(range(10**6))
    monkeypatch.setattr(fl, "claim_key", lambda macro, week: f"{macro}#{week}#{next(calls)}")
    h = Harness()
    h.run()
    h.run()
    assert len(h.posts) == 2, "with no stable key the second run posts again — the negative control above is load-bearing"


# ── 3. fat-only and fibre-only ────────────────────────────────────────────────────────────────────────────────
def test_a_fat_only_and_a_fibre_only_trigger_each_post_one_task_naming_only_that_floor():
    clear_protein = (0, 7)
    problems = []
    for macro, fat, fibre in (("fat", LOW, HIGH), ("fibre", HIGH, LOW)):
        h = Harness(protein=clear_protein, fat=fat, fibre=fibre)
        out = h.run()
        if out["fired"] != [macro] or out["outcome"] != fl.TASK_CREATED or out["claimed"] != [macro]:
            problems.append(f"{macro}: fired {out['fired']} claimed {out.get('claimed')} -> {out['outcome']}")
        trig = out["trigger"]["macros"][macro]
        if trig != {"state": "tripped", "missed": 7, "measured": 7}:
            problems.append(f"{macro}: trigger row {trig}")
        if len(h.posts) != 1 or f"({macro} floor missed)" not in h.posts[0]["content"]:
            problems.append(f"{macro}: posts {[p['content'] for p in h.posts]}")
    assert not problems, "\n".join(problems)


def test_the_floor_count_trips_at_the_tripwires_own_threshold_and_not_one_below():
    n = _threshold()
    problems = []
    for missed, want in ((n, "tripped"), (n - 1, "clear")):
        rows = _rows(LOW, HIGH, n=missed) + [{"date": f"2026-10-{18 + missed + i}", "total_fat_g": HIGH} for i in range(7 - missed)]
        trig = fl.read_trigger(TODAY, protein_reader=lambda d: (0, 7), rows_reader=lambda s, e: rows)
        if trig["macros"]["fat"]["state"] != want or trig["threshold_days"] != n:
            problems.append(f"{missed} missed: {trig['macros']['fat']} (threshold {trig['threshold_days']})")
    unlogged = fl.read_trigger(TODAY, protein_reader=lambda d: (0, 7), rows_reader=lambda s, e: [{"date": "2026-10-20"}])
    if unlogged["macros"]["fibre"] != {"state": "unknown", "missed": None, "measured": 0}:
        problems.append(f"an unlogged day is not a miss: {unlogged['macros']['fibre']}")
    assert not problems, "\n".join(problems)


# ── 4. the unfit day is named ─────────────────────────────────────────────────────────────────────────────────
def test_a_day_the_menu_cannot_fit_is_reported_with_its_misses_named():
    h = Harness(anchors=UNFITTABLE)
    out = h.run()
    unfit = out["menu"]["unfit_days"]
    assert out["outcome"] == fl.TASK_CREATED and unfit, out["menu"]
    assert all(u["misses"] and u["date"] in fl.window_days(TODAY) for u in unfit), unfit
    assert "Days the anchors cannot fit" in h.posts[0]["description"]
    assert out["menu"]["weeks"][0]["fits_all"] is False


# ── 5. a Todoist failure is reported and retried ──────────────────────────────────────────────────────────────
def test_a_todoist_failure_is_reported_in_the_run_result_and_the_next_run_retries():
    def boom(payload):
        raise RuntimeError("Todoist API POST /tasks → 503: unavailable")

    h = Harness(post=boom)
    out = h.run()
    assert out["outcome"] == fl.TASK_FAILED and out["task"]["created"] is False and "503" in out["task"]["error"], out
    h.post = lambda payload: {"id": "task-retry", "content": payload["content"]}
    retry = h.run()
    assert retry["outcome"] == fl.TASK_CREATED and retry["task"]["task_id"] == "task-retry", retry


# ── 6. failed reads and a degraded ledger ─────────────────────────────────────────────────────────────────────
def test_a_failed_read_is_named_and_a_degraded_ledger_posts_nothing():
    def raise_(*a):
        raise TimeoutError("read")

    trig = fl.read_trigger(TODAY, protein_reader=raise_, rows_reader=raise_)
    assert trig["fired"] == [] and {m: r["state"] for m, r in trig["macros"].items()} == dict.fromkeys(fl.MACROS, "read_failed")
    h = Harness()
    out = fl.run(TODAY, protein_reader=lambda d: (7, 7), rows_reader=lambda s, e: [], table=BrokenTable(), create_task=h.posts.append)
    assert out["outcome"] == fl.LEDGER_UNAVAILABLE and out["ledger_degraded"] == ["protein"] and not h.posts, out


def test_a_dry_run_claims_nothing_and_posts_nothing():
    h = Harness()
    out = h.run(dry_run=True)
    assert out["outcome"] == fl.DRY_RUN and not h.posts and not h.table.items and out["menu"]["built"], out


# ── 7. one evaluation ─────────────────────────────────────────────────────────────────────────────────────────
def test_plan_engines_protein_row_and_floor_days_state_are_one_evaluation():
    problems = []
    for n in range(8):
        rows = plan_engine._tripwire_states(
            protein_days_missed_7d=n,
            readiness_low_streak_days=None,
            anchor_lift_drop_pct=None,
            anchor_lift_drop_sessions=None,
            pain_flag_sites=None,
            pain_layer_status=None,
        )
        row = next(r for r in rows if r["id"] == "protein_floor_missed")
        if row["state"] != plan_engine.floor_days_state(n) or row["state"] != ("tripped" if n >= _threshold() else "clear"):
            problems.append(f"{n}: row {row['state']} vs floor_days_state {plan_engine.floor_days_state(n)}")
    assert plan_engine.floor_days_state(None) == "unknown"
    assert not problems, "\n".join(problems)


# ── 8. the host ───────────────────────────────────────────────────────────────────────────────────────────────
def test_the_nightly_predraft_carries_the_leg_and_its_summary():
    from mcp import nightly_predraft as npd
    from mcp.predraft_summary import summarise

    leg = {"outcome": fl.TASK_CREATED, "iso_week": "2026-W43", "fired": ["fat"], "claimed": ["fat"]}
    with (
        patch.object(npd, "run", return_value={"job": "x", "outcome": "skipped"}),
        patch.object(npd, "_may_tracker_leg", return_value={}),
        patch.object(npd, "_fitness_battery_leg", return_value={}),
        patch.object(npd, "_calibration_leg", return_value={}),
        patch.object(npd, "_titration_leg", return_value={}),
        patch("mcp.fuel_loop.nightly_leg", return_value=leg),
    ):
        body = json.loads(npd.lambda_entry({})["body"])
    assert body["fuel_loop"] == leg
    assert summarise(body)["fuel_loop"]["fired"] == ["fat"]
    with patch("mcp.fuel_loop.run", side_effect=RuntimeError("x")):
        assert fl.nightly_leg(TODAY) == {"outcome": fl.FAILED, "error": "RuntimeError"}
