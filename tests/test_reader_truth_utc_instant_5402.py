"""A UTC instant read as "after today" when its Pacific date is not (#5402).

THE PRODUCTION FINDING (`/api/coaches` e8f2c1, confirmed `high` four times 2026-10-25
03:02Z-05:30Z, which is the `qa-smoke-failures` ALARM, and again 10-26 06:16Z): the judge's
ground truth is the PACIFIC date, `_meta.generated_at` is a UTC instant, and between
~00:00Z and ~07:00Z the UTC calendar date is a day ahead. 06:15Z on 10-26 is 23:15 PDT on
10-25 -- the same day. The judge also drops the trailing Z when it quotes the instant, so
the ruling reads tz-less stamps through `common.pacific_time.parse_iso_utc` (naive = UTC).

Hermetic: no model call, no AWS, a fixed `today` (no clock read).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from operational import (
    reader_truth_qa as rt,  # noqa: E402
    reader_truth_rulings as R,  # noqa: E402
)

# A pinned phase anchor passed EXPLICITLY (today_iso=) -- it claims no agreement with the wall clock.
PINNED_DAY = "2026-10-25"

# Synthetic copy of the live note's closing sentences (finding e8f2c1, 2026-10-26T06:16Z run).
LIVE_NOTE = (
    "The headline_stat for Lisa Park (sleep_coach) reads '19 of 47 checked calls right (40%) through October 25'. "
    "The record object confirms this: confirmed=19, refuted=28, n=47, through='2026-10-25'. However, the API was "
    "generated at 2026-10-26T06:15:02 but reports data 'through October 25', which is yesterday. "
    "The _meta.generated_at timestamp shows 2026-10-26T06:15:02, which is AFTER the current date of 2026-10-25. "
    "The payload timestamp contradicts the ground truth phase date."
)


def _f(note, page="/api/coaches", category="temporal_contradiction"):
    return {"page": page, "category": category, "severity": "high", "note": note}


def test_the_live_e8f2c1_note_is_dropped():
    assert R.is_utc_instant_read_as_future(_f(LIVE_NOTE), PINNED_DAY) is True


def test_the_trailing_z_form_is_dropped_too():
    assert R.is_utc_instant_read_as_future(_f(LIVE_NOTE.replace("T06:15:02", "T06:15:02Z")), PINNED_DAY) is True


def test_the_synthetic_one_sentence_form_is_dropped():
    note = "_meta.generated_at timestamp shows 2026-10-26T06:15:02, which is AFTER the current date of 2026-10-25"
    assert R.is_utc_instant_read_as_future(_f(note), PINNED_DAY) is True


def test_a_genuinely_future_instant_is_kept():
    """07:00Z on 10-26 is 00:00 PDT on 10-26 -- the Pacific date IS after today."""
    note = "_meta.generated_at shows 2026-10-26T07:00:00Z, which is AFTER the current date of 2026-10-25"
    assert R.is_utc_instant_read_as_future(_f(note), PINNED_DAY) is False
    far = "_meta.generated_at shows 2026-11-02T12:00:00Z, a week after today 2026-10-25"
    assert R.is_utc_instant_read_as_future(_f(far), PINNED_DAY) is False


def test_one_future_instant_among_benign_ones_keeps_the_finding():
    note = "generated_at 2026-10-26T06:15:02Z is fine but computed_at 2026-10-27T15:00:00Z is after 2026-10-25"
    assert R.is_utc_instant_read_as_future(_f(note), PINNED_DAY) is False


def test_an_instant_not_ahead_in_utc_is_not_this_class():
    note = "generated_at 2026-10-25T18:00:00Z contradicts the page"
    assert R.is_utc_instant_read_as_future(_f(note), PINNED_DAY) is False


def test_a_staleness_claim_citing_an_older_date_survives():
    """The 10-24 e8f2c1 note: a real 6-day staleness objection that merely mentions the stamp."""
    note = (
        "headline_stat reads 'through October 18', but today is 2026-10-25 (Day 50); the payload is generated "
        "2026-10-26T04:45:01 and reports data 6 days old."
    )
    assert R.is_utc_instant_read_as_future(_f(note), PINNED_DAY) is False


def test_a_bare_future_date_survives():
    note = "generated_at 2026-10-26T06:15:02 is after 2026-10-25, and the page also says 'closes 2026-11-03'."
    assert R.is_utc_instant_read_as_future(_f(note), PINNED_DAY) is False


def test_other_category_and_missing_today_and_no_instant_survive():
    assert R.is_utc_instant_read_as_future(_f(LIVE_NOTE, category="duplicated_narrative"), PINNED_DAY) is False
    assert R.is_utc_instant_read_as_future(_f(LIVE_NOTE), None) is False
    assert R.is_utc_instant_read_as_future(_f("today is 2026-10-25 and the page says 2026-10-26."), PINNED_DAY) is False


def test_the_conversion_is_dst_exact():
    """In January 06:15Z is 22:15 PST the previous day -- still not after the Pacific date."""
    note = "generated_at 2026-01-27T06:15:02 is AFTER the current date of 2026-01-26"
    assert R.is_utc_instant_read_as_future(_f(note), "2026-01-26") is True
    late = "generated_at 2026-01-27T08:15:02 is AFTER the current date of 2026-01-26"  # 00:15 PST on the 27th
    assert R.is_utc_instant_read_as_future(_f(late), "2026-01-26") is False


def test_the_ruling_uses_the_one_pacific_frame():
    src = open(R.__file__, encoding="utf-8").read()
    body = src.split("def is_utc_instant_read_as_future")[1].split("\n# ── ")[0]
    assert "pacific_date_of" in body and "ZoneInfo" not in body


def test_wired_into_assess_prose_and_printed():
    src = open(rt.__file__, encoding="utf-8").read()
    body = src.split("if is_utc_instant_read_as_future(f, phase[")[1][:600]
    assert "print(" in body and "continue" in body


def _run_pipeline(monkeypatch):
    """The e8f2c1 copy through the real assess_prose loop with a canned judge (no model call)."""
    import json

    monkeypatch.setattr("common.constants.EXPERIMENT_START_DATE", "2026-09-06")
    reply = {"findings": [_f(LIVE_NOTE)], "severity": "high"}

    def fake_invoke(body, model_name=None):
        return {"content": [{"type": "text", "text": json.dumps(reply)}]}

    findings, _errors = rt.assess_prose([{"name": "c", "path": "/api/coaches", "prose": "x"}], fake_invoke, today_iso=PINNED_DAY)
    return findings


def test_e8f2c1_is_dropped_by_the_real_pipeline(monkeypatch, capsys):
    findings = _run_pipeline(monkeypatch)
    assert [f for f in findings if f["page"] == "/api/coaches" and f["category"] == "temporal_contradiction"] == []
    assert "UTC vs Pacific frame, #5402" in capsys.readouterr().out, "the drop must be printed"


def test_mutation_control_without_the_ruling_the_e8f2c1_copy_survives(monkeypatch):
    """Disable the ruling at the call site and the very same finding reaches the gate."""
    monkeypatch.setattr(rt, "is_utc_instant_read_as_future", lambda f, today=None: False)
    findings = _run_pipeline(monkeypatch)
    assert len(findings) == 1 and findings[0]["note"] == LIVE_NOTE


def test_prompt_states_the_utc_frame():
    phase = {
        "pre_start": False,
        "today": PINNED_DAY,
        "day_n": 50,
        "start_date": "2026-09-06",
        "cycle": None,
    }
    for pre in (False, True):
        p = dict(phase, pre_start=pre, days_until_start=1)
        line = rt._phase_line(p)
        assert "UTC instants" in line and "PACIFIC date" in line
