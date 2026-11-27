"""tests/test_nutrition_consistency_6195.py — the target-neutral nutrition consistency switchboard (#6195, owner ruling
2026-11-22, remaster-2 section 11).

Held here, for every item of ``common/nutrition_consistency.py``:
  * the switchboard ships with every item OFF, the two activation groups partition it, and a typo raises;
  * OFF is today's output byte-for-byte: every touched surface, rendered from synthetic fixtures by
    ``tests/nutrition_consistency_6195_surfaces.py``, equals the golden that the same harness wrote from origin/main
    (``tests/fixtures/nutrition_consistency_6195/off_golden.json``);
  * each item ON changes only its own surface, and does what the ruling asked;
  * with EVERY item ON, no calorie target, deficit cut-off, protein line, rate band, titration rule, clinical stop line
    or training-prescription value changes — the resolved values are compared, not the text;
  * the new public sentences survive the publication gate (``web.narrative_publication.is_tainted``);
  * the set guard: no public module or config persona text carries the retired clearance or "1,500 kcal deficit"
    wording outside the switch's OFF branch.

No test here reaches AWS or a live clock for an asserted value (#4848): every reader is a fake and the day is pinned.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from unittest import mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (ROOT / "lambdas", ROOT, ROOT / "tests", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nutrition_consistency_6195_surfaces as surfaces  # noqa: E402  (sets the env the email modules read at import)
from common import nutrition_consistency as nc  # noqa: E402

COMMITTED = dict(nc.SWITCHES)  # captured at import, before the conftest baseline fixture touches it
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "nutrition_consistency_6195" / "off_golden.json").read_text(encoding="utf-8"))


def _diff_paths(a, b, path=""):
    """Every leaf path at which two JSON values differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += _diff_paths(a.get(k, "<absent>"), b.get(k, "<absent>"), f"{path}.{k}" if path else k)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff_paths(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [path]


@pytest.fixture(scope="module")
def off_render():
    return surfaces.render()


# ── the switchboard itself ───────────────────────────────────────────────────────────────────────────────────────────
def test_every_item_ships_off():
    # Committed state (owner ruling 2026-11-22): GROUP 1 (LABELLING) ON, GROUP 2 (COMPUTED) OFF. The name is historical.
    # ROLLBACK: set the item back to False in common/nutrition_consistency.py, then fleet + site API + MCP deploys.
    # 2026-11-27 (owner, the 21 November partial-day defect): ONE computed item is on — DAY_PAGE_PARTIAL_LABELLED — after
    # its before/after was read on the live record (one day page changes). Every other computed item stays off.
    activated = {nc.DAY_PAGE_PARTIAL_LABELLED}
    assert COMMITTED == {k: (k in nc.LABELLING or k in activated) for k in nc.SWITCHES}, COMMITTED
    assert COMMITTED and all(COMMITTED[k] is True for k in nc.LABELLING)
    assert all(COMMITTED[k] is False for k in nc.COMPUTED if k not in activated)


def test_the_two_activation_groups_partition_the_switchboard():
    assert set(nc.LABELLING) | set(nc.COMPUTED) == set(nc.SWITCHES)
    assert not set(nc.LABELLING) & set(nc.COMPUTED)


def test_an_unknown_item_raises_rather_than_reading_off():
    with pytest.raises(KeyError):
        nc.on("public_verdict_not_clearence")


# ── OFF is today ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_off_renders_every_surface_exactly_as_origin_main_did(off_render):
    assert _diff_paths(GOLDEN, off_render) == []
    assert off_render == GOLDEN


# ── each item ON changes only its own surface ────────────────────────────────────────────────────────────────────────
#: item -> the surface paths (prefixes) it may change, and nothing else.
OWNED = {
    nc.PUBLIC_VERDICT_NOT_CLEARANCE: ("site_api.deficit_sustainability.deficit_sustainability.",),
    nc.MAINTENANCE_LABELLED: (
        "site_api.deficit_sustainability.deficit_sustainability.deficit.tdee_as_of",
        "site_api.nutrition_overview.nutrition.tdee_as_of",
    ),
    nc.RATE_LINE_WORDING: ("site_api.nutrition_overview.loss_rate.rate_line_v2",),
    nc.MCP_SUSTAINABILITY_WORDING: ("mcp.deficit_tool.recommendation", "mcp.description"),
    nc.OWNER_TARGET_LAYERS: ("brief.profile_calorie_line", "brief.bod_phase_targets", "emails."),
    nc.BRIEF_TILE_LAYERS: ("brief.tile_calorie_label",),
    nc.OVERSHOOT_OPTION_LAYERS: ("critics.overshoot_to_text",),
    nc.PARTIAL_EXPORT_EXCLUDED: ("site_api.deficit_sustainability.deficit_sustainability.deficit.", "mcp.deficit_tool."),
    nc.DAY_PAGE_MAINTENANCE_DATED: ("day_pages.",),
    nc.DAY_PAGE_PARTIAL_LABELLED: ("day_pages.",),
    nc.BOD_INTRO_CHARTER_RATE: ("brief.bod_phase_targets",),
}


def test_every_item_has_an_ownership_row():
    assert set(OWNED) == set(nc.SWITCHES)


def test_each_item_on_alone_changes_only_its_own_surface(off_render):
    for item, owned in OWNED.items():
        on = surfaces.render({item} | ({nc.MAINTENANCE_LABELLED} if item == nc.DAY_PAGE_MAINTENANCE_DATED else set()))
        base = surfaces.render({nc.MAINTENANCE_LABELLED}) if item == nc.DAY_PAGE_MAINTENANCE_DATED else off_render
        changed = _diff_paths(base, on)
        assert changed, f"{item}: switching it on changed nothing"
        stray = [p for p in changed if not p.startswith(owned)]
        assert not stray, f"{item} changed surfaces it does not own: {stray}"


# ── the ON behaviour, per fix ────────────────────────────────────────────────────────────────────────────────────────
def test_f1_the_public_verdict_is_not_a_clearance_and_carries_its_basis_and_date():
    ds = surfaces.render({nc.PUBLIC_VERDICT_NOT_CLEARANCE})["site_api"]["deficit_sustainability"]["deficit_sustainability"]
    assert ds["severity"] == "channels_holding"
    v = ds["verdict"]
    assert "absorbing" not in v and "holding while the weight comes off" not in v
    # "safe"/"sustainable" appear only inside the sentence that says the read cannot say so
    assert re.sub(r"does not say whether the deficit itself is safe or sustainable", "", v).count("safe") == 0
    assert "Apr 27" in v and "May 10" in v
    assert "fails its own plausibility check" in v  # the fixture's deficit is refused, and the verdict says so
    assert ds["as_of"] == surfaces.TODAY
    assert ds["based_on"] == ["HRV", "sleep quality", "recovery", "habit completion", "training output"]
    assert {"food intake", "protein", "blood tests"} <= set(ds["not_based_on"])
    assert "not a statement that the deficit is safe" in ds["honesty"]
    # the channel count is what MEASURED steady: the training channel had too few days, so 4 of 5, and it says so
    assert v.startswith("4 of 5 recovery channels held steady from Apr 27 to May 10; 1 had too few days to read.")


def test_f1_a_channel_that_fell_under_its_strain_line_is_not_called_steady():
    from web import site_api_nutrition as nut

    channels = [
        {"status": "stable", "direction": "stable"},
        {"status": "stable", "direction": "improving"},
        {"status": "stable", "direction": "declining"},  # fell, but not past its cut-off
        {"status": "stable", "direction": "insufficient_data"},
        {"status": "degraded", "direction": "declining"},
    ]
    assert nut._held(channels) == (2, 1, 1)
    v = nc.public_holding_verdict(2, "2026-04-27", "2026-05-10", True, drifting=1, too_few=1)
    assert v.startswith(
        "2 of 5 recovery channels held steady from Apr 27 to May 10; 1 drifted down without crossing its strain line; 1 had"
    )


def test_f1_the_strain_verdicts_are_untouched_with_the_switch_on():
    from web import site_api_common as sac, site_api_nutrition as nut

    src = surfaces._flat_sources()
    wdays = [surfaces._day(i) for i in range(6, 0, -1)]
    src.data["whoop"] = [
        dict(r, hrv=h, sleep_efficiency_pct=e, recovery_score=c)
        for r, h, e, c in zip(src.data["whoop"], [100, 100, 90, 90, 70, 70], [100, 100, 90, 90, 70, 70], [100, 100, 90, 90, 70, 70])
    ]
    assert len(wdays) == len(src.data["whoop"])

    def run():
        with (
            mock.patch.object(nut, "datetime", surfaces._FrozenDatetime),
            mock.patch.object(sac, "datetime", surfaces._FrozenDatetime),
            mock.patch.object(sac, "EXPERIMENT_START", surfaces.GENESIS),
            mock.patch.object(nut, "_get_profile", lambda: {"height_inches": 72}),
        ):
            g = {"_query_source": src, "_experiment_date": sac._experiment_date}
            return json.loads(nut.deficit_sustainability(_g=g)["body"])["deficit_sustainability"]

    off = run()
    with mock.patch.dict(nc.SWITCHES, {nc.PUBLIC_VERDICT_NOT_CLEARANCE: True}):
        on = run()
    assert off["severity"] == "warning"
    assert {k: on[k] for k in off} == off  # a strain verdict states strain; only the additive basis fields join it
    assert set(on) - set(off) == {"as_of", "based_on", "not_based_on", "honesty"}


def test_f3_a_partial_export_is_not_a_day_eaten_in_the_public_or_mcp_mean():
    off, on = surfaces.render(), surfaces.render({nc.PARTIAL_EXPORT_EXCLUDED})
    pub_off = off["site_api"]["deficit_sustainability"]["deficit_sustainability"]["deficit"]
    pub_on = on["site_api"]["deficit_sustainability"]["deficit_sustainability"]["deficit"]
    # 13 complete days at 1,000 kcal and one 80 kcal partial export: (13 * 1000 + 80) / 14 = 934.3 -> 934 when counted
    assert (pub_off["avg_intake_kcal"], pub_on["avg_intake_kcal"]) == (934, 1000)
    mcp_off, mcp_on = off["mcp"]["deficit_tool"], on["mcp"]["deficit_tool"]
    assert (mcp_off["deficit"]["avg_intake_kcal"], mcp_on["deficit"]["avg_intake_kcal"]) == (934, 1000)
    assert (mcp_off["period"]["days_with_data"], mcp_on["period"]["days_with_data"]) == (14, 13)
    # the maintenance figure the deficit is computed against does not move
    assert pub_off["tdee"] == pub_on["tdee"] and mcp_off["deficit"]["estimated_tdee"] == mcp_on["deficit"]["estimated_tdee"]


def test_f3_the_critics_and_tripwires_read_a_partial_export_as_an_unlogged_day(monkeypatch):
    from mcp import nutrition_critics_inputs as nci

    rows = surfaces.macrofactor_rows()
    monkeypatch.setattr(
        nci, "query_source", lambda src, a, b: [dict(r) for r in rows if a <= r["date"] <= b] if src == "macrofactor" else []
    )
    monkeypatch.setattr(nci, "_lab_draws", lambda: [])
    monkeypatch.setattr(nci, "_walking_hours", lambda end: 1.0)
    monkeypatch.setattr(nci, "_metabolic_severity", lambda end: None)
    monkeypatch.setattr(nci, "_above_prescription_weeks", lambda end: (0, False))
    monkeypatch.setattr(nci, "_guidance_cap", lambda: None)
    monkeypatch.setattr(nci.shared_quantities, "dxa_scans", lambda end: [])
    monkeypatch.setattr(nci, "day_n", lambda end: 70)

    off = nci.resolve(surfaces.TODAY, include_metabolic=False)["inputs"]
    with mock.patch.dict(nc.SWITCHES, {nc.PARTIAL_EXPORT_EXCLUDED: True}):
        on = nci.resolve(surfaces.TODAY, include_metabolic=False)["inputs"]
    assert off["intake_kcal_by_day"][-1] == 80 and off["fat_g_by_day"][-1] == 0
    assert on["intake_kcal_by_day"][-1] is None and on["fat_g_by_day"][-1] is None  # unlogged, never a low day
    assert on["intake_kcal_by_day"][:-1] == off["intake_kcal_by_day"][:-1]


def test_f4_maintenance_carries_the_date_of_the_row_it_was_read_from():
    on = surfaces.render({nc.MAINTENANCE_LABELLED})["site_api"]
    assert on["nutrition_overview.nutrition"]["tdee_as_of"] == "2026-05-01"  # the one row carrying expenditure
    assert on["deficit_sustainability"]["deficit_sustainability"]["deficit"]["tdee_as_of"] == "2026-05-01"


def test_f4_a_formula_estimate_is_dated_today():
    from web import site_api_nutrition as nut

    assert nut._tdee_as_of([], "estimate_mifflin", "2026-05-10") == "2026-05-10"
    assert nut._tdee_as_of([{"date": "2026-05-01", "expenditure_kcal": "--"}], "macrofactor_adaptive", "2026-05-10") is None


def test_f5_day_pages_date_the_estimate_and_label_a_partial_export():
    on = surfaces.render({nc.MAINTENANCE_LABELLED, nc.DAY_PAGE_MAINTENANCE_DATED, nc.DAY_PAGE_PARTIAL_LABELLED})["day_pages"]
    assert on["before_as_of"]["tdee"] is None and on["before_as_of"]["tdee_as_of"] is None  # it did not exist yet
    assert on["after_as_of"]["tdee"] == 3000 and on["after_as_of"]["tdee_as_of"] == "2026-05-01"
    assert on["partial"]["partial"] is True and on["after_as_of"]["partial"] is False


def test_f5_the_day_schema_accepts_the_switched_keys_and_still_refuses_a_bad_one():
    import publish_snapshot_contract as psc
    import publish_snapshot_day as pd

    row = {"date": "2026-05-05", "calories": 1000, "protein_g": 150, "carbs_g": 80, "fat_g": 40, "partial_export": True}
    with mock.patch.dict(nc.SWITCHES, {nc.DAY_PAGE_MAINTENANCE_DATED: True, nc.DAY_PAGE_PARTIAL_LABELLED: True}):
        d = pd.day_detail(
            "2026-05-05",
            workouts=[],
            night_row=None,
            food_row=row,
            covered={"workouts": {"2026-05-05"}, "sleep": {"2026-05-05"}, "nutrition": {"2026-05-05"}},
            gap_days=set(),
            floor_g=170,
            tdee=3000,
            tdee_as_of="2026-05-01",
        )
    assert d["food"]["partial"] is True and d["food"]["tdee_as_of"] == "2026-05-01"
    pd.check_layers(d, "day")
    with pytest.raises(psc.SchemaError):
        pd.check_layers(dict(d, food={**d["food"], "partial": "yes"}), "day")
    with pytest.raises(psc.SchemaError):
        pd.check_layers(dict(d, food={**d["food"], "tdee_as_of": "May 1"}), "day")


def test_f7_the_api_flags_the_new_rate_line_only_with_its_switch():
    assert "rate_line_v2" not in surfaces.render()["site_api"]["nutrition_overview.loss_rate"]
    assert surfaces.render({nc.RATE_LINE_WORDING})["site_api"]["nutrition_overview.loss_rate"]["rate_line_v2"] is True


def test_f9_to_f13_the_owner_facing_lines_name_the_layers():
    on = surfaces.render({nc.OWNER_TARGET_LAYERS, nc.BRIEF_TILE_LAYERS, nc.BOD_INTRO_CHARTER_RATE})
    layers = "1600 kcal on rest days and 1900 kcal on lifting days (the served daily minimums, owner ruling 2026-11-11); the base plan is 1500 kcal"
    assert layers in on["brief"]["profile_calorie_line"]
    assert layers in on["emails"]["nutrition_review_fallback_calorie_line"]
    assert "vs the calorie target (" in on["emails"]["nutrition_review_fallback_calorie_line"]
    assert on["emails"]["weekly_plate_targets_line"].startswith(f"Targets: {layers}")
    assert "cal/day" not in on["emails"]["weekly_plate_targets_line"]
    assert on["brief"]["tile_calorie_label"] == "/1600–1900"
    bod = on["brief"]["bod_phase_targets"]
    assert "rate band 3–3.5 lb/week (charter)" in bod and "kcal deficit" not in bod and "3 lbs/week" not in bod


def test_f12_the_tile_still_grades_against_the_same_number():
    """Label only: the tile's colour reads `cal_target` (target_kcal), which no switch touches."""
    src = (ROOT / "lambdas" / "content" / "html_builder.py").read_text(encoding="utf-8")
    assert "cal_pct = round(cals / cal_target * 100) if cal_target else 0" in src
    assert '("Calories", fmt_num(cals), _cal_tile_label(data.get("date"), cal_target), cal_color)' in src


def test_f14_the_overshoot_option_names_what_the_step_moves():
    on = surfaces.render({nc.OVERSHOOT_OPTION_LAYERS})["critics"]["overshoot_to_text"]
    assert on == "base 1500 -> 1650; served minimums: rest days 1600 -> 1650, lifting days 1900 -> 1950"


def test_f15_the_mcp_holding_line_is_not_a_clearance_and_keeps_its_severity_token():
    tool = surfaces.render({nc.MCP_SUSTAINABILITY_WORDING})["mcp"]["deficit_tool"]
    assert tool["severity"] == "SUSTAINABLE"  # read by the critics and the deload word; the token is unchanged
    rec = tool["recommendation"]
    assert "appears sustainable" not in rec and "not a clearance of the deficit" in rec
    assert rec.endswith("A critic vetoed on this window.")  # the fixture's critics block carries a veto
    assert nc.mcp_holding_recommendation(False, False).endswith(nc.MCP_REFUSED_SUFFIX)


def test_f16_the_description_stops_routing_is_my_deficit_sustainable():
    desc = surfaces.render({nc.MCP_SUSTAINABILITY_WORDING})["mcp"]["description"]
    assert "'is my deficit sustainable?'" not in desc and "not a clearance on its own" in desc
    from mcp import tools_descriptions

    assert "'is my deficit sustainable?'" in tools_descriptions.GET_DEFICIT_SUSTAINABILITY_DESCRIPTION  # restored after


# ── no target moves ──────────────────────────────────────────────────────────────────────────────────────────────────
def _target_values() -> dict:
    """Every number the platform serves, grades against or prescribes, resolved through its own reader."""
    from common import constants
    from health import calorie_target, deficit_disclosures, titration
    from training import owner_redlines
    from training.training_charter import charter_value

    no_record = {"titration_reader": lambda week: None}
    out = {
        "resolve": {str(dt): calorie_target.resolve("2026-05-11", day_type=dt, **no_record) for dt in (None, "rest", "lifting", "travel")},
        "target_kcal": calorie_target.target_kcal("2026-05-11", **no_record),
        "calorie_band": calorie_target.calorie_band("2026-05-11", **no_record),
        "titrated_band": calorie_target.titrated_band(1650, target=1500, band=[1600, 1900], floor_any=1600, floor_lift=1900, uplift=300),
        "protein_floor_g": constants.PLAN_DAILY_PROTEIN_MIN_G,
        "charter": {p: charter_value(p) for p in ("nutrition", "governing_goal", "training")},
        "redlines": owner_redlines.REDLINES,
        "deficit_thresholds": deficit_disclosures.thresholds_block(),
        "titration_constants": {k: getattr(titration, k) for k in dir(titration) if k.isupper()},
    }
    return json.loads(json.dumps(out, default=str, sort_keys=True))


def _served_numbers(render: dict) -> dict:
    """The target-type numbers inside the rendered surfaces (never a mean the exclusion legitimately moves)."""
    site, mcp_ = render["site_api"], render["mcp"]["deficit_tool"]
    ov = site["nutrition_overview.nutrition"]
    return {
        "overview": {k: ov[k] for k in ("protein_target_g", "protein_floor_g", "tdee")},
        "public_tdee": site["deficit_sustainability"]["deficit_sustainability"]["deficit"]["tdee"],
        "loss_rate_floor": site["nutrition_overview.loss_rate"]["protein_floor_g"],
        "mcp_tdee": mcp_["deficit"]["estimated_tdee"],
        "mcp_thresholds": mcp_["thresholds"],
        "mcp_severity_token": mcp_["severity"],
        "day_floor": {k: v["floor_g"] for k, v in render["day_pages"].items()},
    }


def test_every_switch_on_moves_no_target_value(off_render):
    off_targets = _target_values()
    with mock.patch.dict(nc.SWITCHES, {k: True for k in nc.SWITCHES}):
        on_targets = _target_values()
    assert on_targets == off_targets
    on_render = surfaces.render(set(nc.SWITCHES))
    assert _served_numbers(on_render) == _served_numbers(off_render)
    # the critics' energy block (the numbers a calorie step would move) is the same object either way
    from health import nutrition_critics as ncr

    with mock.patch.object(ncr.calorie_target, "resolve", surfaces.fake_resolve):
        e_off = ncr._energy({"window_end": "2026-05-11"})
        with mock.patch.dict(nc.SWITCHES, {k: True for k in nc.SWITCHES}):
            e_on = ncr._energy({"window_end": "2026-05-11"})
    assert json.dumps(e_on, default=str, sort_keys=True) == json.dumps(e_off, default=str, sort_keys=True)


# ── the publication gate ─────────────────────────────────────────────────────────────────────────────────────────────
def test_the_new_public_sentences_survive_the_publication_gate():
    """A served sentence that shares a six-word run with a withheld row's stored text is served EMPTY. The stored texts a
    coach row could echo here are the old verdict and the owner-side honesty line; the new sentences share no such run."""
    from health import deficit_disclosures as dd
    from web import narrative_publication as NP

    stored = [
        "The body's absorbing the deficit — recovery, sleep, and output are holding while the weight comes off.",
        dd.DEFICIT_SUSTAINABILITY_HONESTY,
        "Deficit appears sustainable. All systems holding.",
        "A fast rate is contested. The bench is split on it — defensible early at this size if it's monitored.",
    ]
    new = [
        nc.public_holding_verdict(4, "2026-04-27", "2026-05-10", False),
        nc.public_holding_verdict(5, "2026-04-27", "2026-05-10", True),
        nc.public_holding_verdict(3, "2026-04-27", "2026-05-10", True, drifting=1, too_few=1),
        nc.PUBLIC_HONESTY,
        "How fast is too fast is contested, and this page does not rate the pace as safe or unsafe. What it can show is the protein floor beside it.",
        "Recovery channels during the cut — the five-channel read",
        "three or more slipping at once is the strain signal this read can give, and all of them holding is not a clearance.",
    ]
    NP.reset_taint()
    try:
        for text in stored:
            NP._taint_text(text)
        for text in new:
            assert not NP.is_tainted(text), text
        assert NP.is_tainted(stored[0])  # the control: the same check catches an echo
    finally:
        NP.reset_taint()


# ── the set guard ────────────────────────────────────────────────────────────────────────────────────────────────────
# premerge-gate: sweeps every public site-API module, site JS file and config JSON for the retired clearance wording
RETIRED_PUBLIC = re.compile(r"absorbing the deficit|deficit appears sustainable|deficit remains sustainable", re.I)
RETIRED_CONFIG = re.compile(
    r"1,?500\s*kcal\s*deficit|deficit is aggressive \(\d|deficit is aggressive at \d|deficit remains sustainable|says is safe|rates as sustainable",
    re.I,
)
#: The one place the retired public verdict may still live: the switch's OFF branch (today's output, kept for rollback).
ALLOWED_PUBLIC = {"lambdas/web/site_api_nutrition.py": 1}


def test_the_retired_clearance_wording_lives_only_in_the_off_branch():
    hits: dict[str, int] = {}
    for path in sorted((ROOT / "lambdas" / "web").glob("site_api_*.py")) + sorted((ROOT / "site" / "assets" / "js").glob("*.js")):
        n = len(RETIRED_PUBLIC.findall(path.read_text(encoding="utf-8")))
        if n:
            hits[str(path.relative_to(ROOT))] = n
    assert hits == ALLOWED_PUBLIC, hits
    src = (ROOT / "lambdas" / "web" / "site_api_nutrition.py").read_text(encoding="utf-8")
    i = src.index("The body's absorbing the deficit")
    assert "_switched_verdict(severity, verdict" in src[i : i + 400], "the old verdict must sit directly above its switch"


def test_no_config_persona_or_catalog_text_calls_1500_a_deficit_or_the_monitor_a_safety_rating():
    hits = []
    for path in sorted((ROOT / "config").rglob("*.json")) + sorted((ROOT / "site" / "config").rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        hits += [f"{path.relative_to(ROOT)}: {m.group(0)}" for m in RETIRED_CONFIG.finditer(text)]
    assert hits == [], hits


def test_the_set_guard_catches_a_planted_copy():
    """Mutation control: each retired form is caught by the regex that guards it."""
    for planted in ("His deficit is aggressive (1500 kcal) so", "At a 1500 kcal deficit, protein", "the monitor says is safe"):
        assert RETIRED_CONFIG.search(planted), planted
    assert RETIRED_PUBLIC.search("The body's absorbing the deficit — recovery")


IMPORTS_SWITCHBOARD = re.compile(
    r"^\s*(from common import [^\n]*\bnutrition_consistency\b|import common\.nutrition_consistency|\s+nutrition_consistency as )", re.M
)


def test_the_switchboard_reaches_only_the_modules_it_was_written_for():
    """The set of modules that read the switchboard. A new reader is a reviewed addition here, never silent."""
    readers = set()
    for base in ("lambdas", "mcp", "scripts"):
        for path in (ROOT / base).rglob("*.py"):
            if IMPORTS_SWITCHBOARD.search(path.read_text(encoding="utf-8")) and path.name != "nutrition_consistency.py":
                readers.add(str(path.relative_to(ROOT)))
    assert readers == {
        "lambdas/ai/ai_calls.py",
        "lambdas/content/html_builder.py",
        "lambdas/emails/nutrition_review_lambda.py",
        "lambdas/emails/weekly_plate_lambda.py",
        "lambdas/health/nutrition_critics.py",
        "lambdas/web/site_api_nutrition.py",
        "mcp/nutrition_critics_inputs.py",
        "mcp/tools_descriptions.py",
        "mcp/tools_nutrition.py",
        "scripts/publish_snapshot_day.py",
    }, readers
    assert not any(r.startswith("lambdas/training/") for r in readers)  # frozen to 2026-11-29


def test_the_conftest_baseline_holds_the_switchboard_off():
    assert all(v is False for v in nc.SWITCHES.values())
