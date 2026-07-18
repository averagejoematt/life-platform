"""tests/test_keep_chronicle_plan_guard.py — #1219.

Two things this locks in:

  1. The regression guard: restart_pipeline's --keep-chronicle cross-check extracts the
     plan figures a kept chronicle installment QUOTES (start weight, calorie target,
     protein floor) and warns when they diverge from the current cycle's constants. The
     evidence case (Prologue Part I: 302 lb / 1,800 kcal / 190 g) MUST flag against the
     current plan (315.65 lb / 1,500 kcal / 170 g). NON-VACUITY: test_cross_check_* fails
     if cross_check_plan_figures is stubbed to return [] (a removed guard).

  2. The Path-to-A fix: restart_leadin_repair bakes a dated Margaret-Calloway editor's note
     into DATE#2026-02-28 ("Before the Numbers") reconciling its pre-plan numbers with Part
     II ("The Plan, On the Record") — without rewriting the dated artifact's body (ADR-104).

Pure/offline — no AWS, no network. Only the DDB-fetch wrapper (not tested here) touches AWS.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# lambdas/ must be importable — load_canonical_plan_figures imports `constants`.
sys.path.insert(0, str(REPO_ROOT / "lambdas"))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pipeline = _load("restart_pipeline")
repair = _load("restart_leadin_repair")

# The exact reader-visible evidence quoted in the issue (verifier reproduction).
PART_I = (
    "His goal weight is 185 pounds. He started at 302. "
    "Phase 1 targets three pounds per week on an 1,800-calorie diet with 190 grams of protein daily."
)
PART_II = "He stepped on the scale at 314.0 pounds on the morning of Day 1. The plan: 1,500 calories a day, a protein floor of 170 grams."

# The current cycle's authoritative plan (constants + config/user_goals.json). Fixed here so
# the non-vacuity assertions don't drift when a future reset re-anchors the baseline weight.
CANONICAL = {"start_weight_lbs": 315.65, "daily_calories": 1500, "protein_floor_g": 170}


# ── extraction ────────────────────────────────────────────────────────────────


def test_extract_part_i_pulls_the_stale_numbers():
    figs = pipeline.extract_plan_figures(PART_I)
    assert figs["start_weight_lbs"] == 302.0  # "started at 302" — NOT the 185 goal weight
    assert figs["daily_calories"] == 1800  # "1,800-calorie"
    assert figs["protein_floor_g"] == 190  # "190 grams of protein"


def test_extract_part_ii_pulls_the_frozen_plan():
    figs = pipeline.extract_plan_figures(PART_II)
    assert figs["start_weight_lbs"] == 314.0  # "314.0 pounds on the morning of Day 1"
    assert figs["daily_calories"] == 1500
    assert figs["protein_floor_g"] == 170  # "protein floor of 170 grams"


def test_extract_returns_none_when_no_figures_quoted():
    figs = pipeline.extract_plan_figures("A quiet paragraph about charging cables and morning light.")
    assert figs == {"start_weight_lbs": None, "daily_calories": None, "protein_floor_g": None}


# ── cross-check (NON-VACUITY: these fail if the guard is removed) ───────────────


def test_cross_check_flags_stale_part_i_on_all_three_figures():
    warns = pipeline.cross_check_plan_figures(pipeline.extract_plan_figures(PART_I), CANONICAL)
    # A removed/stubbed cross-check (return []) fails HERE — the non-vacuity anchor.
    assert warns, "Part I's 302/1,800/190 must flag against the current 315.65/1,500/170 plan"
    joined = " | ".join(warns).lower()
    assert "weight" in joined and "302" in joined  # start-weight mismatch surfaced
    assert "calorie" in joined and "1800" in joined  # calorie-target mismatch surfaced
    assert "protein" in joined and "190" in joined  # protein-floor mismatch surfaced


def test_cross_check_clean_when_prose_matches_current_plan():
    matching = "He started at 315.65 pounds. The plan: 1,500 calories a day and a protein floor of 170 grams."
    warns = pipeline.cross_check_plan_figures(pipeline.extract_plan_figures(matching), CANONICAL)
    assert warns == [], f"consistent figures must NOT flag (no false positives): {warns}"


def test_cross_check_weight_tolerance_absorbs_cycle_rounding():
    # Part II quotes 314.0 vs the 315.65 baseline — a 1.65 lb rounding gap, within tolerance;
    # only gross staleness (like Part I's 13.65 lb gap) should flag on weight.
    warns = pipeline.cross_check_plan_figures({"start_weight_lbs": 314.0}, {"start_weight_lbs": 315.65})
    assert warns == []


def test_cross_check_ignores_absent_figures():
    assert pipeline.cross_check_plan_figures({"daily_calories": None}, CANONICAL) == []


# ── canonical wiring (constants + config are the source of truth) ──────────────


def test_canonical_matches_constants_and_config():
    canon = pipeline.load_canonical_plan_figures()
    goals = json.loads((REPO_ROOT / "config" / "user_goals.json").read_text())
    nutrition = goals["targets"]["nutrition"]
    import constants  # lambdas/ on sys.path

    assert canon["start_weight_lbs"] == float(constants.EXPERIMENT_BASELINE_WEIGHT_LBS)
    assert canon["daily_calories"] == int(nutrition["daily_calories_target"])
    assert canon["protein_floor_g"] == int(nutrition["daily_protein_min_g"])


def test_guard_catches_evidence_case_against_live_canonical():
    # End-to-end on the real current plan: Part I must flag, a current-plan draft must not.
    canon = pipeline.load_canonical_plan_figures()
    assert pipeline.cross_check_plan_figures(pipeline.extract_plan_figures(PART_I), canon), "Part I must flag against the live plan"


# ── Path-to-A: the dated Margaret editor's note on "Before the Numbers" ────────


def test_editors_note_reconciles_part_i_and_survives_header_strip():
    leadin = _load("restart_leadin_pages")
    reg = repair.REPAIRS["DATE#2026-02-28"]
    assert reg.get("editors_note"), "DATE#2026-02-28 must carry a reconciling editor's note"
    # a synthetic vetted body — build_content_fields injects the note above it
    html, md, _ = repair.build_content_fields(reg, "<p>The first thing you notice is the charging cables.</p>")

    # reuses the Margaret device (signed blockquote), references Part II by title, is honest
    assert "Editor's note — Margaret Calloway:" in md
    assert 'class="editors-note"' in html
    assert "The Plan, On the Record" in md and "The Plan, On the Record" in html
    assert "before the plan was frozen" in md.lower()

    # date-agnostic (the reset re-dates this record every cycle) — no month/year/season leaks
    for tok in repair._FORBIDDEN_AFTER_VET:
        assert tok.lower() not in reg["editors_note"].lower(), f"editor's note leaks date-bound/forbidden token: {tok}"

    # the note rides at the TOP of the rendered body (binge reader meets it before the numbers),
    # and it survives the leadin-pages header strip that removes only the h1/byline/hr chrome
    stripped = leadin.body_html_from_record({"content_html": html})
    assert not stripped.startswith("<h1>")
    assert stripped.lstrip().startswith("<blockquote")
    assert "Margaret Calloway" in stripped
