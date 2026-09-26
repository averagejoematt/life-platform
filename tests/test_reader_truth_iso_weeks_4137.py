"""
tests/test_reader_truth_iso_weeks_4137.py — the judge is TOLD the ISO week calendar (#4137).

Specimen: visual-qa-standalone run 35915366139 (2026-09-23, Day 18 of cycle 17,
genesis 2026-09-06). The reader-truth judge gated two pages HIGH on a correctly
dated `WEEK 2026-W38` field note by computing W38's boundaries itself, two
different wrong ways in one run:

  /coaching/lab-notes/  "Week W38 runs 2026-09-22 to 2026-09-28 (ISO week standard)"
  /data/mind/           "W38 runs ~2026-09-13 to 2026-09-19"

The truth is Mon 2026-09-14 .. Sun 2026-09-20, so a W38 note dated 2026-09-20
is the week's own last day. #2959's rule — ground truth is fed, never inferred —
applied to week labels. These tests pin the calendar the prompt states, using an
explicit phase dict so the specimen's dates are fixture inputs, not wall-clock.
"""

from datetime import date, timedelta

from operational import reader_truth_qa as rtq


def _phase(start, today, day_n=None, cycle=17):
    s, t = date.fromisoformat(start), date.fromisoformat(today)
    n = (t - s).days + 1 if day_n is None else day_n
    return {"today": today, "start_date": start, "day_n": max(n, 0), "pre_start": t < s, "days_until_start": 0, "cycle": cycle}


def test_the_specimen_week_is_stated_with_its_true_boundaries():
    line = rtq._iso_week_line(_phase("2026-09-06", "2026-09-23"))
    assert "2026-W38 = 2026-09-14 (Mon) to 2026-09-20 (Sun), Days 9–15" in line
    # both of the judge's invented W38 ranges are absent
    assert "2026-09-22 (Mon)" not in line and "2026-09-13 (Mon)" not in line


def test_every_week_from_day_one_to_today_is_listed_in_order():
    line = rtq._iso_week_line(_phase("2026-09-06", "2026-09-23"))
    labels = ["2026-W36", "2026-W37", "2026-W38", "2026-W39"]
    positions = [line.index(lbl) for lbl in labels]
    assert positions == sorted(positions)
    assert "2026-W35" not in line and "2026-W40" not in line


def test_the_day_one_week_names_its_pre_cycle_days_and_the_current_week_is_in_progress():
    line = rtq._iso_week_line(_phase("2026-09-06", "2026-09-23"))
    assert "2026-W36 = 2026-08-31 (Mon) to 2026-09-06 (Sun), Day 1; 6 pre-cycle day(s)" in line
    assert "2026-W39 = 2026-09-21 (Mon) to 2026-09-27 (Sun), Days 16–18; in progress" in line


def test_the_calendar_agrees_with_the_stdlib_for_every_day_of_a_long_cycle():
    """Can-fail control: every stated Monday must be the ISO week's own Monday per
    `date.isocalendar()` — an off-by-one in the Monday arithmetic reds this."""
    start = date(2026, 12, 20)  # crosses the ISO year boundary (2026-W53 -> 2027-W01)
    for offset in range(0, 70, 3):
        today = start + timedelta(days=offset)
        line = rtq._iso_week_line(_phase(start.isoformat(), today.isoformat()))
        for chunk in line.split(": ", 1)[1].rstrip(".").split("; "):
            if " = " not in chunk:
                continue
            label, rest = chunk.split(" = ", 1)
            mon = date.fromisoformat(rest[:10])
            y, w, wd = mon.isocalendar()
            assert wd == 1 and label == f"{y}-W{w:02d}", (today, chunk)


def test_a_long_cycle_is_capped_but_keeps_the_day_one_week():
    line = rtq._iso_week_line(_phase("2026-09-06", "2026-12-23"))
    assert line.count(" (Mon) to ") == rtq.ISO_WEEK_LINE_MAX_WEEKS
    assert "2026-W36 = 2026-08-31" in line  # Day 1's week always stays
    assert "2026-W52 = 2026-12-21 (Mon) to 2026-12-27 (Sun)" in line  # the current week always stays


def test_pre_start_states_no_week_calendar():
    assert rtq._iso_week_line(_phase("2026-09-06", "2026-09-03")) == ""


def test_the_calendar_reaches_the_built_prompt():
    phase = _phase("2026-09-06", "2026-09-23")
    prompt = rtq.build_prompt([{"name": "Lab notes", "path": "/coaching/lab-notes/", "prose": "WEEK 2026-W38"}], phase)
    assert "2026-W38 = 2026-09-14 (Mon) to 2026-09-20 (Sun)" in prompt
    assert "never compute your own" in prompt


def test_the_bare_experiment_week_is_stated_apart_from_the_iso_calendar():
    """#4163: on 2026-09-25 (Day 20) the judge read the header 'DAY 20 · WEEK 3' as ISO
    W38 because the line said every week label is ISO, and gated a correct header HIGH.
    The site's header week is floor((day-1)/7)+1 (site/assets/js/coach_popover.js
    genesisCount); the line must state that number for today, apart from the ISO list."""
    line = rtq._iso_week_line(_phase("2026-09-06", "2026-09-25"))
    assert "DAY 20 · WEEK 3" in line
    assert "Week 3 = 2026-09-20..2026-09-26)" in line
    assert "2026-W39 = 2026-09-21 (Mon) to 2026-09-27 (Sun), Days 16–20; in progress" in line
    # mutation control: the old claim that EVERY week label is ISO must not return
    assert "Week labels on this site are ISO-8601 weeks" not in line


def test_the_experiment_week_matches_the_site_header_formula_across_a_cycle():
    start = date(2026, 9, 6)
    for n in range(1, 60):
        today = start + timedelta(days=n - 1)
        line = rtq._iso_week_line(_phase(start.isoformat(), today.isoformat()))
        assert f"DAY {n} · WEEK {(n - 1) // 7 + 1}' is the experiment week" in line
