"""#4580 B-22 — the Food pillar reads the stored MacroFactor row's real field names.

The fixture IS the wire: the 2026-10-17 `USER#matthew#SOURCE#macrofactor` / `DATE#2026-10-17` row
(read 2026-10-18, schema_version 1) and the 14 stored days before the compute, as boto3 returns them
(Decimal, `total_calories_kcal` / `total_protein_g` / `meals_above_30g_protein`, no calorie target,
no `meals` list). Before the fix the engine spelled `calories` / `protein`, so all four behavioral
Food components scored ABSENT (0 at full weight) on a logged day.

Mutation control: `test_mutation_legacy_names_only_reads_absent` re-runs the pre-fix read (the legacy
names only) over the same wire row and shows it yields the four absences this test forbids.
"""

import json
import os
import sys
from decimal import Decimal

LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

from common import macrofactor_fields as mff  # noqa: E402
from health.calorie_target import target_kcal  # noqa: E402
from health.character_engine import compute_nutrition_raw  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "character_sheet.json")

ROW_2026_10_17 = {
    "pk": "USER#matthew#SOURCE#macrofactor",
    "sk": "DATE#2026-10-17",
    "date": "2026-10-17",
    "schema_version": Decimal("1"),
    "source": "macrofactor",
    "entries_count": Decimal("13"),
    "total_calories_kcal": Decimal("1561"),
    "total_protein_g": Decimal("133"),
    "total_carbs_g": Decimal("162"),
    "total_fat_g": Decimal("37"),
    "meals_above_30g_protein": Decimal("1"),
    "protein_distribution_score": Decimal("100"),
    "total_meals": Decimal("1"),
    "total_snacks": Decimal("4"),
    "food_log": [{"food_name": "Morning Smoothies", "time": "07:30", "calories_kcal": Decimal("80"), "protein_g": Decimal("0")}],
}

# date, total_calories_kcal, total_protein_g, meals_above_30g_protein — stored rows 2026-10-04..10-17.
_DAYS = [
    ("2026-10-04", "1407", "109", "1"),
    ("2026-10-05", "1632", "146", "1"),
    ("2026-10-06", "1622", "182", "2"),
    ("2026-10-07", "1512", "185", "2"),
    ("2026-10-08", "1235", "120", "1"),
    ("2026-10-09", "1911", "158", "2"),
    ("2026-10-10", "1935", "120", "2"),
    ("2026-10-11", "1512", "173", "1"),
    ("2026-10-12", "1286", "155", "2"),
    ("2026-10-13", "1579", "166", "2"),
    ("2026-10-14", "1311", "152", "2"),
    ("2026-10-15", "873", "98", "0"),
    ("2026-10-16", "1460", "166", "2"),
    ("2026-10-17", "1561", "133", "1"),
]
ROWS_14D = [
    {"date": d, "total_calories_kcal": Decimal(c), "total_protein_g": Decimal(p), "meals_above_30g_protein": Decimal(m)}
    for d, c, p, m in _DAYS
]


def _config():
    with open(_CONFIG_PATH) as fh:
        return json.load(fh)


def _details():
    _, details = compute_nutrition_raw({"macrofactor": ROW_2026_10_17, "macrofactor_14d": ROWS_14D, "latest_weight": None}, _config())
    return details


def test_logged_day_has_no_absent_food_behaviors():
    details = _details()
    absent = [k for k, v in details.items() if isinstance(v, dict) and v.get("absent")]
    assert absent == [], f"logged day scored absent: {absent}"


def test_food_components_score_the_wire_row():
    d = _details()
    # #5095: the reference is the ONE calorie target (charter nutrition.calories, 2,100 at v1.8.0, was the
    # retired 1,500 constant): |1561 - 2100| / 2100 = 25.7 % against a 20 % band -> clamped to 0.0
    assert target_kcal("2026-10-17") == 2100
    assert d["calorie_adherence"]["score"] == 0.0
    # 133 g / 170 g target, perfect at 1.2x -> 65.2
    assert d["protein_total"]["score"] == 65.2
    # #5214: feedings are the protein engine's (charter threshold) — the one timed row carries 0 g -> 0 feedings -> 0.0
    assert d["protein_distribution"]["score"] == 0.0
    # 2 of 14 days (1,911 and 1,935) within 10 % of 2,100 kcal
    assert d["consistency"]["score"] == 14.3


def test_shared_accessor_resolves_by_presence():
    assert mff.macro_value(ROW_2026_10_17, "calories") == 1561.0
    assert mff.macro_value(ROW_2026_10_17, "protein") == 133.0
    assert mff.macro_value({"total_protein_g": Decimal("0")}, "protein") == 0.0  # a logged zero is a value
    assert mff.macro_value({}, "protein") is None
    assert mff.macro_value({"calories": 2400}, "calories") == 2400.0  # legacy spelling still reads


def test_shared_names_are_the_schema_names():
    schema = open(os.path.join(os.path.dirname(__file__), "..", "docs", "SCHEMA.md")).read()
    section = schema.split("### macrofactor\n", 1)[1].split("\n### ", 1)[0]
    for quantity in ("calories", "protein"):
        assert f"`{mff.MACRO_FIELDS[quantity][0]}`" in section
    assert f"`{mff.MEALS_ABOVE_30G_PROTEIN_FIELD}`" in section


def test_mutation_legacy_names_only_reads_absent(monkeypatch):
    """The control: restore the pre-fix spelling and the four absences come back on the same row."""
    monkeypatch.setitem(mff.MACRO_FIELDS, "calories", ("calories", "total_calories"))
    monkeypatch.setitem(mff.MACRO_FIELDS, "protein", ("protein", "total_protein"))
    monkeypatch.setattr(mff, "MEALS_ABOVE_30G_PROTEIN_FIELD", "meals")
    d = _details()
    absent = sorted(k for k, v in d.items() if isinstance(v, dict) and v.get("absent"))
    # calorie_adherence keeps the plan target but loses the intake, so it is absent too
    # #5214: the distribution slot no longer reads the legacy stored count, so it is not among the absences
    assert absent == ["calorie_adherence", "consistency", "protein_total"]


def test_distribution_counts_engine_feedings_not_the_legacy_stored_count():
    """#5214: 1 feeding at the charter threshold of a 4-feeding target, perfect at 1.25x -> 20.0; the stored legacy
    count (meals_above_30g_protein = 1) is not what is graded, and an untimed day is unknown, never 0."""
    thr = float(charter_value("nutrition.protein.feeding_threshold_g"))
    timed = dict(ROW_2026_10_17, food_log=[{"time": "08:00", "protein_g": thr, "calories_kcal": 400}], meals_above_30g_protein=Decimal("4"))
    _, d = compute_nutrition_raw({"macrofactor": timed, "macrofactor_14d": ROWS_14D, "latest_weight": None}, _config())
    assert d["protein_distribution"]["score"] == 20.0
    untimed = dict(ROW_2026_10_17, food_log=[{"protein_g": thr}], meals_above_30g_protein=Decimal("4"))
    _, d = compute_nutrition_raw({"macrofactor": untimed, "macrofactor_14d": ROWS_14D, "latest_weight": None}, _config())
    assert d["protein_distribution"].get("absent")
