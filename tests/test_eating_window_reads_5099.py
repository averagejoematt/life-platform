"""tests/test_eating_window_reads_5099.py — the eating window is the charter's, and its consumers READ it (#5099, epic #5091).

# premerge-gate: a repo-shape ratchet — sweeps lambdas/ and mcp/ for a hard-coded eating-window literal in a code string

The owner ruled 16:8 on 2026-10-23 (R2 on #5091) and charter 1.21.0 stated it as `nutrition.eating_window`. Before this
lane nothing read it: the day grade never looked at meal times, and four prompts typed their own window ("16:8 IF
(eating window ~11am-7pm)" in the Weekly Plate prompt and payload, "~11am-7pm (16:8)" twice in the Saturday nutrition
review, "16:8 … ~11am-7pm" in the hypothesis engine), while the nutrition door hard-coded an 8-hour reference. Four legs:

  (a) the reader: `health.eating_window` validates the block, grades a day on the span between its first and last
      timed meal (a duration — the charter names no clock time), and an untimed day / unreadable block is UNKNOWN;
  (b) the scorer: `score_nutrition` grades the window as a known-only 0.10 slot — inside 100, outside 0, unknown drops
      the slot so an untimed day scores exactly what it scored before (never a miss);
  (c) the published surfaces read it through `public_view()` (the whitelist carries the block): the plate prompt and
      payload, the review's fallback prompt, the nutrition door's reference hours;
  (d) the SET guard: no code string under lambdas/ or mcp/ types an eating window ("16:8", "11am-7pm", "8-hour
      eating window"); docstrings and comments are prose and are not swept. Positive and negative controls included.

NOT SEEN, stated: config files (config/user_goals.json still carries the owner's practice note "11:30am-7:30pm" with
its morning-smoothie exception, read by intelligence_common's context block — a hand-owned note, not a hard-coded
literal; the generic experiment/challenge catalogs describe a 16:8 protocol as a library entry, not his plan) and
site/ JS (the ribbon's "vs 16:8" label and `|| 8` fallback are front-end).
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import sys
from typing import List

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (_REPO / "lambdas", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
for _k, _v in (
    ("TABLE_NAME", "life-platform"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("AWS_REGION", "us-west-2"),
    ("EMAIL_RECIPIENT", "reader@example.invalid"),
    ("EMAIL_SENDER", "sender@example.invalid"),
    ("S3_BUCKET", "test-bucket"),
    ("AI_VALIDATOR_AUTOLOAD", "off"),
    ("USER_ID", "matthew"),
):
    os.environ.setdefault(_k, _v)

from health import (
    eating_window as ew,  # noqa: E402
    scoring_engine as se,  # noqa: E402
)
from training import training_charter as tc  # noqa: E402

WINDOW = {"type": "16:8", "eating_hours": 8, "fasting_hours": 16, "rule": "one 8-hour window"}


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    """No live S3 probe and no laptop twin: the tracked charter file is the only input."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _row(t, kcal=400.0, **kw):
    r = {"food_name": "x", "calories_kcal": kcal, "protein_g": 40.0}
    if t is not None:
        r["time"] = t
    r.update(kw)
    return r


# ── (a) the reader ────────────────────────────────────────────────────────────────────────
def test_the_live_charter_block_is_16_8_by_the_owner_ruling():
    raw = json.loads((_REPO / "config/training_charter.json").read_text())["nutrition"]["eating_window"]
    b = ew.block()
    assert b is not None and b["type"] == raw["type"] == "16:8"
    assert b["eating_hours"] == raw["eating_hours"] == 8 and b["fasting_hours"] == raw["fasting_hours"] == 16
    assert raw["provenance"] == "owner" and "R2" in raw["ruling"]
    assert ew.describe() == "16:8 (one 8-hour eating window)"
    assert ew.eating_minutes() == 480


def test_a_day_inside_the_window_is_inside():
    v = ew.evaluate_day([_row("19:00"), _row("11:30"), _row("15:00")], WINDOW)
    assert (v["status"], v["inside"], v["first"], v["last"], v["span_min"]) == ("inside", True, "11:30", "19:00", 450)


def test_the_edge_is_inside_and_one_minute_past_it_is_outside():
    assert ew.evaluate_day([_row("11:00"), _row("19:00")], WINDOW)["status"] == "inside"
    v = ew.evaluate_day([_row("11:00"), _row("19:01")], WINDOW)
    assert (v["status"], v["inside"], v["span_min"]) == ("outside", False, 481)


def test_one_timed_meal_fits_any_window():
    assert ew.evaluate_day([_row("08:15")], WINDOW)["status"] == "inside"


def test_an_untimed_day_is_unknown_never_a_miss():
    for log in (None, [], [_row(None), _row(None)], [_row("not a time")]):
        v = ew.evaluate_day(log, WINDOW)
        assert (v["status"], v["inside"]) == ("unknown", None), log


def test_a_zero_energy_row_does_not_open_the_window():
    log = [_row("06:00", kcal=0.0, protein_g=0.0), _row("12:00"), _row("19:00")]
    v = ew.evaluate_day(log, WINDOW)
    assert (v["status"], v["first"]) == ("inside", "12:00")
    # a row with no calorie figure but food energy IS a meal
    v2 = ew.evaluate_day([{"time": "06:00", "protein_g": 30.0}, _row("19:00")], WINDOW)
    assert v2["status"] == "outside"


def test_untimed_meals_leave_a_fitting_day_unknown_but_cannot_rescue_a_wide_one():
    fits = ew.evaluate_day([_row("12:00"), _row("18:00"), _row(None)], WINDOW)
    assert (fits["status"], fits["untimed_meals"], fits.get("reason")) == ("unknown", 1, "untimed_meals")
    wide = ew.evaluate_day([_row("08:00"), _row("20:00"), _row(None)], WINDOW)
    assert wide["status"] == "outside"  # an untimed row can only widen the span


def test_an_unreadable_or_malformed_block_is_an_absence_never_a_remembered_window():
    for bad in ({}, {"type": "16:8"}, {"eating_hours": 0}, {"eating_hours": 30}, {"eating_hours": 8, "fasting_hours": 14}, "16:8"):
        assert ew.block(bad) is None, bad
        assert ew.evaluate_day([_row("12:00"), _row("13:00")], bad)["status"] == "unknown"
        assert "not stated" in ew.describe(bad)


def test_the_window_follows_the_charter_not_a_constant():
    ten_hours = {"type": "14:10", "eating_hours": 10, "fasting_hours": 14}
    log = [_row("09:00"), _row("18:30")]
    assert ew.evaluate_day(log, WINDOW)["status"] == "outside"
    assert ew.evaluate_day(log, ten_hours)["status"] == "inside"
    assert ew.describe(ten_hours) == "14:10 (one 10-hour eating window)"


# ── (b) the scorer ────────────────────────────────────────────────────────────────────────
def _mf(food_log):
    mf = {"total_calories_kcal": 1500.0, "total_protein_g": 175.0, "total_fat_g": 66.0, "total_carbs_g": 60.0, "total_fiber_g": 36.0}
    if food_log is not None:
        mf["food_log"] = food_log
    return mf


def _score(food_log):
    return se.score_nutrition({"macrofactor": _mf(food_log), "date": "2026-10-20"}, {})


def test_scoring_grades_the_window_as_a_known_only_slot():
    s_in, d_in = _score([_row("11:30"), _row("19:00")])
    s_out, d_out = _score([_row("07:00"), _row("19:00")])
    s_none, d_none = _score(None)
    s_untimed, d_untimed = _score([_row(None)])
    assert d_in["eating_window"]["status"] == "inside" and d_in["window_score"] == 100
    assert d_out["eating_window"]["status"] == "outside" and d_out["window_score"] == 0
    assert s_out < s_in
    # unknown drops the slot: the score is exactly the pre-#5099 three-slot score, never a miss
    assert "window_score" not in d_none and "window_score" not in d_untimed
    assert d_untimed["eating_window"]["status"] == "unknown"
    assert s_untimed == s_none


# ── (c) the published surfaces ────────────────────────────────────────────────────────────
def test_the_published_whitelist_carries_the_window_and_no_clock_time():
    view = tc.public_view()
    blk = ew.published_block(view)
    assert ew.block(blk) == ew.block()
    assert ew.published_text() == ew.describe() and ew.published_eating_hours() == 8
    assert ew.published_block({}) == {} and ew.published_block(None) == {}


def test_the_weekly_plate_prompt_and_payload_state_the_charter_window(monkeypatch):
    from emails import weekly_plate_lambda as wpl

    monkeypatch.setattr(wpl, "build_weight_context", lambda *a, **k: "W")
    monkeypatch.setattr(wpl, "target_kcal", lambda *a, **k: 1500)
    system = wpl.build_system_prompt({}, [])
    assert "eating window 16:8 (one 8-hour eating window)" in system
    assert "11am" not in system and "7pm" not in system
    monkeypatch.setattr(wpl, "extract_food_data", lambda mf: ([], []))
    monkeypatch.setattr(wpl, "analyze_food_patterns", lambda foods: {})
    monkeypatch.setattr(wpl, "extract_weight_trend", lambda w: {})
    payload = json.loads(wpl.build_user_message({"macrofactor": [], "withings": [], "profile": {}}))
    assert payload["profile_targets"]["eating_window"] == ew.describe()


def test_the_nutrition_review_fallback_prompt_takes_the_window_at_build_time():
    from emails import nutrition_review_lambda as nrl

    assert "{eating_window}" in nrl._FALLBACK_SYSTEM_PROMPT and "11am" not in nrl._FALLBACK_SYSTEM_PROMPT
    system = nrl._FALLBACK_SYSTEM_PROMPT.format(
        calorie_target=1500, protein_target_g=170, feeding_threshold_g=nrl._feeding_threshold_text(), eating_window=ew.published_text()
    )
    assert "Eating window 16:8 (one 8-hour eating window): every feeding fits inside it." in system


# ── (d) the SET guard ─────────────────────────────────────────────────────────────────────
SWEPT_DIRS = ("lambdas", "mcp")
WINDOW_LITERAL = re.compile(
    r"\b(?:14:10|16:8|18:6|20:4)\b"  # a fasting:eating ratio that completes a day
    r"|\b\d{1,2}(?::\d{2})?\s*[ap]m\s*[-–]\s*\d{1,2}(?::\d{2})?\s*[ap]m\b"  # a clock window — 11am-7pm, 11:30am–7:30pm
    r"|\b\d{1,2}[- ]?h(?:ou)?r?\s+eating\s+window\b",  # 8-hour eating window, 8h eating window
    re.IGNORECASE,
)


def _docstring_ids(tree: ast.AST) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def window_findings(src: str, rel: str = "<src>") -> List[str]:
    """Every code string (constants and f-string parts — docstrings and comments excluded) that types an eating window."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    skip = _docstring_ids(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            m = WINDOW_LITERAL.search(node.value)
            if m:
                out.append(f"{rel}:{node.lineno}: {m.group(0)!r}")
    return sorted(set(out))


def _swept() -> List[pathlib.Path]:
    return sorted(p for d in SWEPT_DIRS for p in (_REPO / d).rglob("*.py") if "__pycache__" not in p.parts)


def test_no_code_string_types_its_own_eating_window():
    """THE SET guard: one test over lambdas/ and mcp/, every offender reported."""
    files = _swept()
    found: List[str] = []
    for path in files:
        found += window_findings(path.read_text(encoding="utf-8"), path.relative_to(_REPO).as_posix())
    assert len(files) > 700, f"the sweep walked only {len(files)} modules — a tree moved"
    assert (
        not found
    ), "the eating window is the charter's (nutrition.eating_window, read by health.eating_window, #5099):\n  " + "\n  ".join(found)


def test_the_detector_sees_each_shape_and_passes_the_clean_ones():
    shapes = {
        'P = "Targets: 16:8 IF (eating window ~11am-7pm)."\n': 2,
        'P = {"eating_window": "11am-7pm (16:8 IF)"}\n': 1,
        'P = f"Eating window ~11:30am–7:30pm, cal {x}"\n': 1,
        'P = "Keep the 8-hour eating window"\n': 1,
        'P = "an 8h eating window"\n': 1,
        'P = "14:10 protocol"\n': 1,
        # clean: a docstring, a comment, a time of day, a ratio that is not a window, an interpolated window
        'def f():\n    """16:8 is the plan."""\n    return 1  # 11am-7pm\n': 0,
        'P = "runs at 11:30 PT"\n': 0,
        'P = "aspect 16:9"\n': 0,
        'P = f"Eating window {ew.describe()}"\n': 0,
        'P = "between 16:80"\n': 0,
    }
    for src, n in shapes.items():
        got = window_findings(src)
        assert len(got) == min(n, 1) if n else not got, (src, got)
    assert len({m.group(0) for m in WINDOW_LITERAL.finditer("Targets: 16:8 IF (eating window ~11am-7pm).")}) == 2
