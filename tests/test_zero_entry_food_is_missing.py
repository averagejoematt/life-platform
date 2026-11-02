"""A summary-only food stub is a missing day everywhere a coach or the engine reads it (acceptance review, 2026-11-02).

On 28–30 October MacroFactor held one stub row a day — `entries_count` 0, no `food_log`, 80 kcal / 15 g. The grader
already read such a row as missing (#5552), but the coaches' inputs counted it as a logged day and cited its 15 g as
"protein eaten", and the character engine scored it as intake (Nutrition 8.3). One predicate now decides all three:
`coach.grading_quality.is_zero_entry_day`.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lambdas"))

from coach import (
    coach_input_facts as CIF,  # noqa: E402
    lead_daily_read as LDR,  # noqa: E402
)
from health.character_engine import compute_nutrition_raw  # noqa: E402

_CONFIG = os.path.join(os.path.dirname(__file__), "..", "config", "character_sheet.json")


def _row(day: str, kcal, protein, entries) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#macrofactor",
        "sk": f"DATE#{day}",
        "date": day,
        "source": "macrofactor",
        "entries_count": Decimal(str(entries)),
        "total_calories_kcal": Decimal(str(kcal)),
        "total_protein_g": Decimal(str(protein)),
        "food_log": [{"food": "x"}] if entries else [],
    }


STUB = _row("2026-10-29", 80, 15, 0)
REAL = [_row(f"2026-10-{d:02d}", 1500, 150, 12) for d in range(15, 28)]


def test_the_coaches_logging_record_does_not_count_a_stub():
    rec = CIF.nutrition_record(REAL + [_row("2026-10-28", 80, 15, 0), STUB], "2026-10-30")
    assert rec["days_logged"] == len(REAL)
    assert rec["latest_log_date"] == "2026-10-27"
    assert rec["protein_avg_g"] == 150.0 and rec["protein_avg_days"] == len(REAL)


def test_the_lead_is_told_the_day_was_not_logged_never_the_stubs_grams():
    cited = LDR.build_cited({"date": "2026-10-29", "macrofactor": STUB}, {"protein_floor_g": 170}, {}, "2026-10-30")
    by = {c["metric"]: c["value"] for c in cited}
    assert by.get("food log") == "not logged (no diary entries)"
    assert "protein eaten (grams)" not in by and "protein floor met" not in by


def test_the_engine_scores_a_stub_as_a_missing_day_not_as_intake():
    cfg = json.load(open(_CONFIG, encoding="utf-8"))
    _, stub = compute_nutrition_raw(
        {"date": "2026-10-29", "macrofactor": STUB, "macrofactor_14d": REAL + [STUB], "latest_weight": None}, cfg
    )
    _, none = compute_nutrition_raw({"date": "2026-10-29", "macrofactor": {}, "macrofactor_14d": REAL, "latest_weight": None}, cfg)
    assert stub == none, "a stub day scores exactly as a day with no record"
