"""tests/test_field_notes_grounded_inputs_6270.py — the W46/W47 holds, fixed at the INPUTS.

The field note was HELD by the grounding gate two Sundays running (2026-W46, 2026-W47).
The retained drafts show four finding classes, all invited by the generator's inputs:

  1. round approximation — "roughly 1,000 calories" for an average the payload states exactly;
  2. unsupported estimate — calories "below maintenance" (the payload carries no maintenance);
  3. self-computed multi-week total — "N pounds across the last two weeks";
  4. weight "from X to Y" with no window — the payload's bare `start`/`end` keys, which the
     baseline-framing rule reads as a from-the-start claim (and a prior week's reading
     called the "starting point").

The fix is in the payload (window-labelled weight keys + the journey start), the prompt
(rules forbidding classes 1-4, with NO digits — the prompt is the allow-list) and the one
rewrite (every finding, with the shared per-class instruction). The gate is untouched: the
tests below run the drafts through the UNCHANGED gate and show the ungrounded forms still
hold while the forms the prompt now asks for pass. All figures are synthetic.
"""

import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import field_notes_lambda as fnl  # noqa: E402
from ai.grounded_generation import allowed_dates, allowed_numbers, grounding_findings  # noqa: E402
from ai.grounding_gate_params import cycle_gate_params  # noqa: E402
from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

# A fixed generation date (#4848): the baseline-framing rule's day index reads it.
_GEN_DATE = "2026-11-22"
_WEEK = "2026-W47"

# Synthetic week — no reading from the owner's data.
_WITHINGS = [
    {"sk": "DATE#2026-11-16", "weight_lbs": 251.4},
    {"sk": "DATE#2026-11-19", "weight_lbs": 249.9},
    {"sk": "DATE#2026-11-22", "weight_lbs": 248.2},
]
_MACROFACTOR = [{"sk": f"DATE#2026-11-{d}", "total_calories_kcal": 1640 + d, "total_protein_g": 140} for d in range(16, 22)]


def _payload(monkeypatch):
    monkeypatch.setattr(fnl, "table", FakeDdbTable())
    rows = {"withings": _WITHINGS, "macrofactor": _MACROFACTOR}
    monkeypatch.setattr(fnl, "_query_source", lambda src, s, e: rows.get(src, []))
    return fnl.gather_week_data("2026-11-16", "2026-11-22")


def _findings(text, prompt):
    return grounding_findings(
        text, allowed=allowed_numbers(prompt), allowed_dates=allowed_dates(prompt), **cycle_gate_params(generation_date_iso=_GEN_DATE)
    )


# ── payload ────────────────────────────────────────────────────────────────


def test_weight_block_names_its_window_and_carries_the_journey_start(monkeypatch):
    w = _payload(monkeypatch)["weight"]
    assert not {"start", "end", "change"} & set(w), "bare start/end keys invite a windowless 'from X to Y' (W47)"
    assert "this week" in w["window"]
    assert w["first_reading_this_week_lbs"] == 251.4
    assert w["last_reading_this_week_lbs"] == 248.2
    assert w["change_this_week_lbs"] == -3.2
    # the SAME constant the gate's baseline-framing rule measures against
    assert w["journey_start_lbs"] == cycle_gate_params(generation_date_iso=_GEN_DATE)["baseline_lbs"] == EXPERIMENT_BASELINE_WEIGHT_LBS
    assert w["change_since_journey_start_lbs"] == round(248.2 - EXPERIMENT_BASELINE_WEIGHT_LBS, 1)


def test_payload_adds_no_target_or_estimate_field(monkeypatch):
    """Grounding by payload covers only the public weight journey. Maintenance, deficits and
    targets stay OUT (owner-only band / target rulings) — the prompt forbids them instead."""
    data = _payload(monkeypatch)
    flat = repr(data).lower()
    for word in ("maintenance", "deficit", "target", "goal", "tdee", "burn"):
        assert word not in flat, word


# ── prompt ─────────────────────────────────────────────────────────────────


def test_number_rules_carry_no_digits():
    """The prompt IS the gate's allow-list: a digit in the rules would ground that figure in
    every note. The rules must forbid round figures without writing one."""
    assert re.findall(r"\d", fnl.NUMBER_INSTRUCTIONS) == []
    assert re.findall(r"\d", fnl._REWRITE_INSTRUCTIONS) == []


def test_prompt_forbids_each_held_class(monkeypatch):
    prompt = fnl.build_prompt(_WEEK, _payload(monkeypatch), [])
    low = prompt.lower()
    assert "only numbers that appear in the data" in low
    assert "roughly" in low and "never round" in low  # class 1
    assert "maintenance" in low and "deficits" in low and "targets" in low  # class 2
    assert "no totals across weeks" in low  # class 3
    assert "names its window" in low and "this week" in low and "since the start" in low  # class 4
    assert "the only starting or baseline weight is journey_start_lbs" in low


# ── the unchanged gate on the W46/W47 shapes ───────────────────────────────


def test_windowless_weight_pair_still_holds_and_the_windowed_form_passes(monkeypatch):
    """Class 4 against the UNCHANGED gate: the W47 sentence shape still holds; the sentence the
    prompt now asks for passes; a 'since the start' sentence is grounded by the payload."""
    prompt = fnl.build_prompt(_WEEK, _payload(monkeypatch), [])
    held = _findings("A 3.2-pound drop, from 251.4 to 248.2 pounds.", prompt)
    assert [f["type"] for f in held] == ["stale_baseline"]
    assert _findings("This week brought a 3.2-pound drop, from 251.4 to 248.2 pounds.", prompt) == []
    since = round(EXPERIMENT_BASELINE_WEIGHT_LBS - 248.2, 1)
    assert _findings(f"Since the start, from {EXPERIMENT_BASELINE_WEIGHT_LBS:g} to 248.2 pounds, {since:g} pounds are gone.", prompt) == []


def test_prior_reading_called_a_starting_point_still_holds(monkeypatch):
    """W46 shape: a prior week's reading framed as the starting point — still a finding."""
    prompt = fnl.build_prompt(_WEEK, _payload(monkeypatch), [{"week": "2026-W44", "tone": "mixed", "present": "Weight read 262.5 lb."}])
    held = _findings("You are well below your starting weight of 262.5 lb.", prompt)
    assert any(f["type"] == "stale_baseline" for f in held)


def test_round_approximation_and_estimates_still_hold(monkeypatch):
    """Classes 1-3 against the UNCHANGED gate: still findings, so the prompt rules — not a
    loosened gate — are what must keep them out of the draft."""
    data = _payload(monkeypatch)
    prompt = fnl.build_prompt(_WEEK, data, [])
    avg = data["nutrition"]["avg_calories"]
    assert _findings(f"Intake averaged {avg:,} calories.", prompt) == []
    for bad in (
        "Intake ran at roughly 1,700 calories.",
        "That is 1,500+ calories below maintenance.",
        "You lost 9.2 pounds across two weeks.",
    ):
        assert [f["type"] for f in _findings(bad, prompt)] == ["fabricated_number"], bad


# ── the one rewrite ────────────────────────────────────────────────────────


def test_rewrite_prompt_carries_every_finding_with_its_instruction(monkeypatch):
    prompt = fnl.build_prompt(_WEEK, _payload(monkeypatch), [])
    findings = _findings(
        "Intake ran at roughly 1,700 calories. You lost 9.2 pounds across two weeks. "
        "That is 1,500 calories below maintenance. A drop from 251.4 to 248.2 pounds.",
        prompt,
    )
    assert len(findings) == 4  # more than the old three-detail cap
    fix = fnl.rewrite_prompt(prompt, findings)
    assert fix.startswith(prompt)
    assert "CORRECTION REQUIRED" in fix
    for f in findings:
        assert f["detail"] in fix
    assert f"Use {EXPERIMENT_BASELINE_WEIGHT_LBS:g} lb" in fix  # the shared stale_baseline instruction
    assert "describe the pattern qualitatively" in fix  # the shared fabricated_number instruction
    assert "same sentence" in fix


def _stub_side_writers(monkeypatch):
    import common.qa_archive as qa_archive
    import experiment.eval_retention as eval_retention

    monkeypatch.setattr(eval_retention, "retain", lambda *a, **k: True)
    monkeypatch.setattr(qa_archive, "archive_text", lambda *a, **k: None)


def test_held_marker_names_the_held_drafts_findings(monkeypatch):
    """W46's HELD line said '1 finding(s)' and listed the first draft's three — the marker and
    log now describe the draft that was actually held."""
    t = FakeDdbTable(seed_store=False)
    monkeypatch.setattr(fnl, "table", t)
    monkeypatch.setattr(fnl, "_get_api_key", lambda: "k")
    monkeypatch.setattr(fnl, "gather_week_data", lambda s, e: {})
    monkeypatch.setattr(fnl, "get_prior_notes", lambda w: [])
    monkeypatch.setattr(fnl, "build_prompt", lambda w, d, p: "this week resting heart rate 64 bpm")
    _stub_side_writers(monkeypatch)
    drafts = [
        {"ai_present": "Heart rate 51 bpm, 77 bpm and 88 bpm.", "ai_tone": "mixed"},
        {"ai_present": "Heart rate 93 bpm.", "ai_tone": "mixed"},
    ]
    monkeypatch.setattr(fnl, "_call_notes_model", lambda p, k: drafts.pop(0))
    result = fnl.generate_field_notes("2026-W27")
    assert result == {"status": "held", "week": "2026-W27", "findings": 1}
    marker = [p for p in t.puts if p["pk"] == fnl.FN_HELD_PK][0]
    assert "93" in marker["detail"] and "51" not in marker["detail"]
    assert [p for p in t.puts if p["pk"] == fnl.FN_PK] == []
