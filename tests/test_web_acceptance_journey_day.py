"""The owner's Journey/Day acceptance review (2026-11-02): the exporter halves of items 1, 2, 3 and 8.

1. A prediction's `summary` is the call's OWN outcome, the same word the pages use (www/src/lib/format.js) —
   never the simple guess's result, which the rail printed as "wrong" under a call graded right.
2. Coach lines stay verbatim; a correction is ADDED beside a figure quoted from an incomplete food record, a
   logged-days count the record does not support, and a reading said to climb to a value it fell to.
3. Every program-week chapter carries the explicit interval /api/chapters serves; the Day exporter and the
   chapter intervals agree on every day (12 September is Week 1, 21 October is Week 7).
8. A chapter excerpt loses the editor's note the body opens with, and the literal Markdown emphasis.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from publish_snapshot_chapters import CALL_OUTCOME, apply_week_intervals, clean_excerpt, week_interval  # noqa: E402
from publish_snapshot_corrections import annotate_coach_lines  # noqa: E402
from publish_snapshot_day import week_of  # noqa: E402

# /api/chapters as served on 2 November 2026 (weeks 1, 7, 8, 9)
WEEKS_API = {
    "genesis": "2026-09-06",
    "weeks": [
        {"week": 1, "start": "2026-09-06", "end": "2026-09-12", "status": "published"},
        {"week": 7, "start": "2026-10-18", "end": "2026-10-24", "status": "skipped"},
        {"week": 8, "start": "2026-10-25", "end": "2026-10-31", "status": "held"},
        {"week": 9, "start": "2026-11-01", "end": "2026-11-07", "status": "pending"},
    ],
}


def test_call_outcome_matches_the_pages_mapping():
    js = open(os.path.join(REPO, "www", "src", "lib", "format.js"), encoding="utf-8").read()
    block = re.search(r"export const CALL_OUTCOME = \{([^}]*)\}", js).group(1)
    pairs = dict(re.findall(r'(\w+):\s*"([^"]+)"', block))
    assert pairs == CALL_OUTCOME
    assert CALL_OUTCOME["confirmed"] == "right" and CALL_OUTCOME["refuted"] == "wrong"


def test_prediction_summary_is_the_calls_outcome_not_the_simple_guess():
    src = open(os.path.join(REPO, "scripts", "publish_snapshot.py"), encoding="utf-8").read()
    assert "summary=CALL_OUTCOME.get(status, status)" in src
    assert '(sg or {}).get("short")' not in src, "the simple guess's word must never be the call's summary"


def test_week_intervals_are_the_served_ones_and_arithmetic_only_as_fallback():
    chapters = [
        {"id": "week-04", "week": 1, "date": "2026-09-08"},
        {"id": "week-05", "week": 2, "date": "2026-09-15"},
        {"id": "program-week-07", "week": 7, "date": "2026-10-18"},
        {"id": "week-01", "week": 0, "date": "2026-08-31"},
    ]
    apply_week_intervals(chapters, WEEKS_API, None)
    got = {c["id"]: (c["week_start"], c["week_end"]) for c in chapters}
    assert got["week-04"] == ("2026-09-06", "2026-09-12")  # published on the 8th, the week is 6–12
    assert got["week-05"] == ("2026-09-13", "2026-09-19")  # not served → genesis arithmetic
    assert got["program-week-07"] == ("2026-10-18", "2026-10-24")
    assert got["week-01"] == (None, None)  # a prologue has no program week
    assert week_interval(3, None, {}) == (None, None)


def test_the_day_exporter_and_the_chapter_intervals_agree_on_every_day():
    spans = [(w["week"], w["start"], w["end"]) for w in WEEKS_API["weeks"]]
    served = {n: (a, b) for n, a, b in spans}
    for n in range(1, 10):
        a, b = week_interval(n, "2026-09-06", served)
        for day_number in range(1, 64):
            from datetime import date, timedelta

            iso = (date(2026, 9, 6) + timedelta(days=day_number - 1)).isoformat()
            assert (a <= iso <= b) == (week_of(day_number, iso, spans) == n), (n, iso)
    assert week_of(7, "2026-09-12", spans) == 1
    assert week_of(46, "2026-10-21", spans) == 7


def test_excerpt_drops_the_editors_note_and_the_markdown_markers():
    raw = (
        "*Editor's note, October 2026 — Margaret Calloway: this installment was rewritten after a review.*\n\n"
        "*Three days in, the experiment is live: two fully…"
    )
    assert clean_excerpt(raw) == "Three days in, the experiment is live: two fully…"
    assert clean_excerpt("*After 23 days — a season high.*\n\n*Day 31 · 327.3 →…") == "After 23 days — a season high.\n\nDay 31 · 327.3 →…"
    assert clean_excerpt("2*3 and snake_case stay") == "2*3 and snake_case stay"
    assert clean_excerpt(None) is None


def _day(iso, *, food=None, food_state="served", recovery=None, lines=()):
    return {
        "date": iso,
        "food": food,
        "food_state": food_state if food else "not logged",
        "readings": {"recovery_pct": recovery},
        "coach_lines": [{"coach": "C", "coach_id": "x_coach", "move": "reply", "move_label": None, "text": t} for t in lines],
    }


STUB = {"calories": 80, "protein_g": 15.0, "logging_gap": True}
FULL = {"calories": 1500, "protein_g": 150.0, "logging_gap": False}


def test_corrections_beside_the_three_unsupported_readings_and_the_quote_untouched():
    days = [_day(f"2026-10-{d:02d}", food=FULL, recovery=70) for d in range(1, 28)]
    days += [
        _day("2026-10-28", food=STUB, recovery=76),
        _day("2026-10-29", food=STUB, recovery=74, lines=["only 15 grams logged Wednesday"]),
        _day(
            "2026-10-30",
            food=STUB,
            recovery=58,
            lines=["recovery climbing to 58 while protein sat at 15 grams yesterday", "30 logged days this month, every one of them"],
        ),
        _day("2026-10-31", recovery=94, lines=["the deadlift moved well"]),
    ]
    annotate_coach_lines(days)
    by = {d["date"]: d for d in days}
    l29 = by["2026-10-29"]["coach_lines"][0]
    assert l29["text"] == "only 15 grams logged Wednesday"
    assert len(l29["corrections"]) == 1 and "Wednesday 28 October and Thursday 29 October" in l29["corrections"][0]
    assert "unknown" in l29["corrections"][0]
    climb, count = by["2026-10-30"]["coach_lines"]
    assert any("fell to 58 on Friday 30 October from 74" in c for c in climb["corrections"])
    assert count["corrections"] == [
        "Correction: through Friday 30 October, 27 of the 30 days this month have a complete food log; 3 are incomplete records "
        "(Wednesday 28 October, Thursday 29 October, Friday 30 October)."
    ]
    assert by["2026-10-31"]["coach_lines"][0]["corrections"] == []


def test_no_correction_when_the_record_supports_the_line():
    days = [
        _day("2026-10-01", food=FULL, recovery=60),
        _day("2026-10-02", food=FULL, recovery=70, lines=["recovery climbing to 70", "150 grams of protein, as planned"]),
    ]
    annotate_coach_lines(days)
    assert all(ln["corrections"] == [] for ln in days[1]["coach_lines"])


def _dist(tmp_path, journey_html, front_html="<a href='/data/'>x</a>"):
    (tmp_path / "data" / "journey").mkdir(parents=True)
    (tmp_path / "data" / "journey" / "index.html").write_text(journey_html, encoding="utf-8")
    (tmp_path / "index.html").write_text(front_html, encoding="utf-8")
    return str(tmp_path)


def test_heart_coverage_holds_both_charts_and_the_front_page_budget(tmp_path):
    from check_www_build import heart_coverage

    fig = '<figure class="figure" data-heart><p>{n} · bpm</p><svg data-points="[{{&quot;x&quot;:1}}]"></svg></figure>'
    both = fig.format(n="Resting heart rate") + fig.format(n="Heart-rate variability")
    assert heart_coverage(_dist(tmp_path / "ok", both)) == []
    missing = heart_coverage(_dist(tmp_path / "missing", fig.format(n="Resting heart rate")))
    assert missing == ["data/journey/index.html: the Heart-rate variability chart is missing (#5598 heart coverage)"]
    empty = both.replace('data-points="[{&quot;x&quot;:1}]"', 'data-points="[]"', 1)
    assert "no inspectable points" in heart_coverage(_dist(tmp_path / "empty", empty))[0]
    linked = heart_coverage(_dist(tmp_path / "linked", both, '<a href="/next/v9/data/hrv/">HRV</a>'))
    assert linked and "link budget" in linked[0]
