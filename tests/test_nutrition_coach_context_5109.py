"""tests/test_nutrition_coach_context_5109.py — #5109 (epic #5094) + #5183: the nutrition coach speaks from the charter.

  (1) ASSEMBLY: the nutrition coach's input carries `training.coach_context.nutrition_context` — the charter's nutrition
      block, the redlines' nutrition rules, the ONE calorie target with its provenance, the protein engine's and the
      macro floors' grade of the data day — stamped with `charter_version()`, through `coach_input_facts.coach_inputs`.
  (2) PERSONAS: no calorie / protein / fibre / steps / loss-rate figure in a coach persona (config/coaches/*.json)
      disagrees with the charter; the pre-#5109 few-shots are the mutation control.
  (3) GROUNDING: a coach output fixture citing the resolver target and the protein engine's figure passes the served-
      fact gate; a plan-framed figure no engine serves (the stale 190 g, the legacy 30 g line) is flagged. The
      #5183 specimen class — a recovery trend read as a protein figure because the sentence also says "protein" —
      no longer yields a protein claim in either reader (`weight_truth_qa.classify_claims`).
  (4) PRIVACY: the published context carries none of the titration record's owner-only fields
      (`privacy.field_tiers`: nutrition_titration is TIER_OWNER_ONLY), no feeding clock times, no May target.
  (5) LEGACY: the ingest's 30 g protein-distribution score has no reader in coach or panel text.

Offline: no AWS, no model, no clock (every day is passed in).
"""

import glob
import json
import os
import re
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from ai.plan_facts_gate import plan_quantity_claims  # noqa: E402
from coach import coach_input_facts as ci  # noqa: E402
from health import calorie_target, protein_engine  # noqa: E402
from operational import weight_truth_qa as wq  # noqa: E402
from privacy import field_tiers  # noqa: E402
from training import coach_context as cc, training_charter as tc  # noqa: E402

# premerge-gate: sweeps config/coaches/*.json (every persona vs the charter) and lambdas/ai + lambdas/coach (the legacy 30 g score) — repo-shape ratchets
_FIXTURE = os.path.join(_REPO, "tests", "fixtures", "nutrition_coach_5109", "coach_output.json")
with open(_FIXTURE, encoding="utf-8") as _fh:
    FIX = json.load(_fh)
DAY, ROW = FIX["day"], FIX["day_row"]


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    """The bundled PUBLIC charter only: no owner twin from the laptop's env, no live S3 probe, no titration read."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    ci._run.clear()
    yield
    tc.reset_cache()
    ci._run.clear()


# ── (1) the assembly ─────────────────────────────────────────────────────────────────────
def test_the_context_is_the_charter_the_redlines_the_resolver_and_the_engines_stamped_with_the_charter_version():
    ctx = cc.nutrition_context(DAY, day_row=ROW)
    s = ctx["sections"]
    assert ctx["charter_version"] == tc.charter_version() and ctx["charter_version"]
    assert ctx["context_version"] == cc.NUTRITION_CONTEXT_VERSION
    for path in cc.NUTRITION_PUBLISHED_PATHS:
        assert s["charter_nutrition"]["values"][path] == tc.charter_value(path), path
    assert set(s["redlines"]["rules"]) == {k for k, _f in cc.REDLINE_NUTRITION_RULES}
    assert s["redlines"]["rules"]["energy_floor_kcal"]["floor_any_day"] == tc.charter_value("nutrition.calories.floor_any_day_kcal")
    want = calorie_target.resolve(DAY)
    assert s["calorie_target"]["kcal"] == want["kcal"] and s["calorie_target"]["resolved_from"] == want["source"]
    assert s["calorie_target"]["provenance"]
    day = protein_engine.evaluate_day(ROW)
    assert s["protein_day"]["total_g"] == day["total_g"] and s["protein_day"]["hit"] == day["hit"]
    assert s["floors_day"]["fat"]["floor_g"] == tc.charter_value("nutrition.floors.fat.floor_g")
    assert f"v{ctx['charter_version']}" in ctx["text"] and cc.NUTRITION_CITE_RULE in ctx["text"]


def test_an_absent_day_row_is_stated_never_a_miss():
    s = cc.nutrition_context(DAY)["sections"]
    assert s["protein_day"]["state"] == cc.NOT_SUPPLIED and "hit" not in s["protein_day"]
    assert s["floors_day"]["state"] == cc.NOT_SUPPLIED


def test_the_nutrition_coach_input_carries_the_context_and_no_other_coach_does(monkeypatch):
    monkeypatch.setattr(ci, "pacific_today", lambda: DAY)  # the run's day, frozen (#4848)
    data = {"date": ROW["date"], "macrofactor": ROW, "macrofactor_window": [ROW]}
    out = ci.coach_inputs("nutrition_coach", {"protein_g": 150.0}, data)
    ctx = out["charter_context"]
    assert ctx["charter_version"] == tc.charter_version()
    assert ctx["sections"]["calorie_target"]["kcal"] == calorie_target.resolve(DAY)["kcal"]
    assert ctx["sections"]["protein_day"]["total_g"] == protein_engine.evaluate_day(ROW)["total_g"]
    ci._run.clear()
    assert "charter_context" not in ci.coach_inputs("sleep_coach", {"sleep_score": 80}, data)


def test_the_daily_coach_prompt_states_the_charters_targets_not_typed_ones():
    lines = cc.charter_goal_lines()
    assert f"{tc.charter_value('steps.floor'):,}" in lines and f"{tc.charter_value('steps.target'):,}" in lines
    assert f"{tc.charter_value('nutrition.protein.range_g.low'):g} g floor" in lines
    assert ", ".join(tc.charter_value("split.sequence")) in lines
    src = open(os.path.join(_REPO, "lambdas", "ai", "ai_calls.py"), encoding="utf-8").read()
    assert "{charter_goal_lines()}" in src
    assert "190g/day" not in src and "8,000+ steps/day" not in src  # the pre-charter typed targets


# ── (2) persona figures vs the charter ───────────────────────────────────────────────────
_RATE_LINE = re.compile(r"([−-]?\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\s*(?:per|/|a)\s*(?:week|wk)\b", re.IGNORECASE)


def _charter_figures() -> dict:
    fig = cc.nutrition_context(DAY, published=False)["served_figures"]
    allowed = {q: set(v) for q, v in fig.items()}
    allowed["steps"] = {float(tc.charter_value("steps.floor")), float(tc.charter_value("steps.target"))}
    band = tc.charter_value("governing_goal.rate_band_lb_per_wk") or {}
    allowed["rate"] = {float(band["floor"]), float(band["ceiling"])}
    return allowed


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def persona_disagreements(persona: dict, allowed: dict) -> list:
    """Every calorie / protein / fibre / steps / loss-rate figure in a persona that the charter does not state."""
    out = []
    for text in _strings(persona):
        for c in plan_quantity_claims(text):
            if c["value"] not in allowed.get(c["quantity"], set()):
                out.append(f"{c['quantity']} {c['value']:g} in {c['claim']!r}")
        for m in _RATE_LINE.finditer(text):
            if abs(float(m.group(1).replace("−", "-"))) not in allowed["rate"]:
                out.append(f"rate {m.group(0)!r}")
    return out


def test_no_coach_persona_states_a_figure_the_charter_does_not():
    allowed = _charter_figures()
    bad = {}
    for path in sorted(glob.glob(os.path.join(_REPO, "config", "coaches", "*.json"))):
        if os.path.basename(path) == "tuning_log.json":
            continue  # a dated history of past edits: it names superseded figures by construction
        with open(path, encoding="utf-8") as fh:
            found = persona_disagreements(json.load(fh), allowed)
        if found:
            bad[os.path.basename(path)] = found
    assert not bad, f"persona figures the charter does not state (read them from the charter context or drop them): {bad}"


def test_mutation_control_the_pre_charter_few_shots_are_flagged():
    stale = {
        "few_shot_examples": [
            "Amara's suggestion would bring you to about 1,650 calories on training days.",
            "You're losing 0.7 lbs per week, protein is adequate.",
            "your dinner protein has been consistent at 55-60g for three weeks.",
        ]
    }
    found = persona_disagreements(stale, _charter_figures())
    assert any(f.startswith("calories 1650") for f in found) and any(f.startswith("rate") for f in found)
    assert any(f.startswith("protein_g 60") for f in found)  # 55 is the charter feeding target; 60 is not


# ── (3) grounding ────────────────────────────────────────────────────────────────────────
def _facts():
    ctx = cc.nutrition_context(DAY, day_row=ROW)
    from ai.plan_facts_gate import cached_plan_facts

    facts = {"nutrition_context": ctx, "protein_series": [(ROW["date"], float(ROW["total_protein_g"]))], "nutrition": {}}
    return ctx, {**facts, "plan_facts": cached_plan_facts()}


def _rendered(ctx) -> str:
    s = ctx["sections"]
    return FIX["text"].format(
        protein_total_g=f"{s['protein_day']['total_g']:g}",
        protein_floor_g=f"{s['charter_nutrition']['values']['nutrition.protein.range_g.low']:g}",
        calorie_target_kcal=f"{s['calorie_target']['kcal']:,}",
        feeding_threshold_g=f"{s['charter_nutrition']['values']['nutrition.protein.feeding_threshold_g']:g}",
    )


def test_the_fixture_output_cites_the_resolver_target_and_the_engines_figure_and_passes_the_gate():
    ctx, facts = _facts()
    text = _rendered(ctx)
    assert f"{calorie_target.resolve(DAY)['kcal']:,} kcal target" in text
    assert f"{protein_engine.evaluate_day(ROW)['total_g']:g} g of protein" in text
    report = ci.served_fact_gate({"passed": True}, text, facts)
    assert report["passed"] is True and ci.SERVED_FACT_REPORT_KEY not in report


def test_a_target_no_engine_serves_is_flagged_before_publishing():
    _ctx, facts = _facts()
    missed = []
    for name, text in sorted(FIX["mutants"].items()):
        report = ci.served_fact_gate({"passed": True}, text, facts)
        if report["passed"] is not False or [f["metric"] for f in report[ci.SERVED_FACT_REPORT_KEY]] != ["protein_g"]:
            missed.append(name)
        elif not report["suggestions"]:
            missed.append(f"{name} (no correction)")
    assert not missed, f"mutants the served-fact gate let through: {missed}"


def test_without_a_nutrition_context_the_target_check_is_disarmed():
    assert ci.target_findings(FIX["mutants"]["stale_protein_target"], {"nutrition": {}}) == []


# The #5183 shape (synthetic figures): a recovery trend in a sentence that also names protein.
SPECIMEN = (
    "Recovery dropped from 80.0% to 70.5% over the past week, and deep sleep declined from 19.0% to 15.5% over 14 days — "
    "the opposite of what I predicted when he committed to escalating protein."
)


def test_5183_a_recovery_trend_is_never_read_as_a_protein_figure():
    claims = wq.coach_quantity_claims({"analysis": SPECIMEN})
    assert "protein" not in claims
    assert claims["recovery"] == [(70.5, "trend_end")]  # the second pair names no keyword before it: nobody's
    ok, msg = wq.assess_cross_surface_coach_vs_engine([{"name": "coach", "analysis": SPECIMEN}], nutrition={"avg_protein_g": 140.0})
    assert ok, msg


def test_5183_a_protein_trend_is_still_a_protein_figure_and_still_judged():
    text = "Protein rose from 120 g to 135 g over 14 days, while recovery held."
    assert wq.coach_quantity_claims({"analysis": text})["protein"] == [(135.0, "trend_end")]
    ok, _msg = wq.assess_cross_surface_coach_vs_engine([{"name": "coach", "analysis": text}], nutrition={"avg_protein_g": 160.0})
    assert not ok


def test_5183_mutation_control_first_pair_to_every_keyword_misreads_the_specimen(monkeypatch):
    """The old rule (every quantity named in the sentence takes the FIRST pair) re-run: 70.5 becomes protein."""

    def old_owners(sentence, quantities):
        m = wq._FROM_TO_NUMBERS.search(sentence)
        return {q: [m] for q in quantities if m and wq._QUANTITY_KEYWORD[q].search(sentence)}

    monkeypatch.setattr(wq, "_from_to_owners", old_owners)
    assert wq.coach_quantity_claims({"analysis": SPECIMEN}).get("protein") == [(70.5, "trend_end")]


# ── (4) privacy ──────────────────────────────────────────────────────────────────────────
def test_the_published_context_carries_no_owner_only_field():
    assert not field_tiers.is_publishable(field_tiers.source_tier_of("nutrition_titration"))  # the precondition the strip serves
    titrated = {
        "kcal": 2000,
        "base_kcal": 2000,
        "source": "titration",
        "provenance": "titration record WEEK#2026-10-19 (OWNER_ONLY_REASON)",
        "band_low": 1950,
        "band_high": 2050,
        "floor_any_day_kcal": 1600,
        "floor_lifting_day_kcal": 1900,
        "charter_version": tc.charter_version(),
        "week": "2026-10-19",
    }
    pub = cc.nutrition_context(DAY, day_row=ROW, calorie=titrated, published=True)
    blob = json.dumps({k: pub[k] for k in ("sections", "rule")}) + pub["text"]
    assert "OWNER_ONLY_REASON" not in blob and "band_low" not in blob and "WEEK#" not in blob
    assert pub["sections"]["calorie_target"]["kcal"] == 2000  # the kcal itself is what the resolver states anywhere
    assert "feedings" not in pub["sections"]["protein_day"] and "08:00" not in blob  # no clock times
    for path in cc.NUTRITION_PUBLISHED_PATHS:
        assert not path.startswith(tc.NEVER_PUBLISHED) and path.split(".")[0] not in tc.PRIVATE_KEYS, path
    assert "governing_goal" not in blob and "target_date" not in blob and "training_day" not in blob
    owner = cc.nutrition_context(DAY, day_row=ROW, calorie=titrated, published=False)
    assert "OWNER_ONLY_REASON" in owner["text"] and owner["sections"]["protein_day"]["feedings"]  # mutation control


def test_the_daily_brief_assembles_the_published_form():
    src = open(os.path.join(_REPO, "lambdas", "coach", "coach_input_facts.py"), encoding="utf-8").read()
    assert "nutrition_context(today, day_row=row if isinstance(row, dict) else None, published=True)" in src


# ── (5) the legacy per-meal score ────────────────────────────────────────────────────────
LEGACY_FIELDS = ("protein_distribution_score", "meals_above_30g_protein")


def test_the_legacy_30g_score_has_no_reader_in_coach_or_panel_text():
    producers = sorted(glob.glob(os.path.join(_REPO, "lambdas", "ai", "*.py")) + glob.glob(os.path.join(_REPO, "lambdas", "coach", "*.py")))
    producers.append(os.path.join(_REPO, "lambdas", "emails", "nutrition_review_lambda.py"))
    assert len(producers) > 20
    readers = [os.path.relpath(p, _REPO) for p in producers if any(f in open(p, encoding="utf-8").read() for f in LEGACY_FIELDS)]
    assert readers == [], f"coach/panel text reads the legacy 30 g score — read health.protein_engine instead: {readers}"
