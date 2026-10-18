"""#4624 backlog row: the habit-completion trend channel reads closed days only.

`completion_pct` is pending-aware (pending habits leave the denominator), so an OPEN day reads
higher than its strict figure (0.40 vs 0.23 on the day checked) and, being the newest row, sits
in the last-third average of /api/deficit_sustainability.
"""

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from web.site_api_nutrition import _closed_habit_days  # noqa: E402


def test_open_day_is_dropped_and_closed_days_kept():
    rows = [
        {"sk": "DATE#2026-10-16", "completion_pct": 0.5},
        {"sk": "DATE#2026-10-17", "completion_pct": 0.4},
        {"sk": "DATE#2026-10-18", "completion_pct": 0.4, "completion_pct_strict": 0.23},
    ]
    kept = _closed_habit_days(rows, "2026-10-18")
    assert [r["sk"] for r in kept] == ["DATE#2026-10-16", "DATE#2026-10-17"]
    assert _closed_habit_days([{"date": "2026-10-19"}, {"date": "2026-10-18"}], "2026-10-18") == []


def test_the_endpoint_routes_its_habit_read_through_the_filter():
    """Control: the channel must actually use it (a helper nobody calls is the specimen again)."""
    src = (REPO / "lambdas/web/site_api_nutrition.py").read_text()
    assert re.search(r'habit = _closed_habit_days\(_by_day\("habitify"\), today\)', src)
    assert 'habit = _by_day("habitify")' not in src
