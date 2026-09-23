"""tests/test_alarm_citation_age_4034.py — the 72h AGE predicate (#4034 box 4).

`scripts/alarm_citation_age.py`: an alarm red >72h whose citation's timestamp does not
POST-DATE its StateTransitionedTimestamp is flagged by the /wrap gate
(`scripts/check_alarm_citations.py`). Includes the planted-stale-citation must-fail
control, driven through the gate's real `main()`.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import alarm_citation_age as age  # noqa: E402
import check_alarm_citations as cac  # noqa: E402

NOW = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
START = NOW - timedelta(hours=100)  # 2026-09-19T14:00Z — past the 72h bar


def _lit(name="qa-smoke-warnings", start=START, **extra):
    a = {"name": name, "updated": start.isoformat(), "transitioned": start.isoformat()}
    a.update(extra)
    return a


@pytest.mark.parametrize(
    "entry, flagged",
    [
        ({"citation": "#1", "cause_observed": "2026-09-18"}, True),  # the day BEFORE the episode (planted stale)
        ({"citation": "#1", "cause_observed": "2026-09-19"}, True),  # same day: cannot prove it post-dates
        ({"citation": "#1", "cause_observed": "2026-09-20"}, False),  # a later day provably post-dates
        ({"citation": "#1", "cause_observed": "2026-09-19T09:00:00Z"}, True),  # full stamp, before 14:00Z
        ({"citation": "#1", "cause_observed": "2026-09-19T15:00:00Z"}, False),  # full stamp, after 14:00Z
        ({"citation": "#1", "added": "2026-09-21"}, False),  # `added` stands in when cause_observed is absent
        ({"citation": "#1", "added": "2026-09-21", "cause_observed": "2026-09-10"}, True),  # cause_observed wins
        ({"citation": "#1"}, True),  # no timestamp cannot post-date anything
    ],
)
def test_the_predicate(entry, flagged):
    out = age.aged_unrefreshed_citations([_lit()], {"qa-smoke-warnings": entry}, now=NOW)
    assert bool(out) is flagged, (entry, out)


def test_under_the_age_bar_is_never_flagged():
    young = _lit(start=NOW - timedelta(hours=70))
    assert age.aged_unrefreshed_citations([young], {"qa-smoke-warnings": {"citation": "#1"}}, now=NOW) == []


def test_an_uncited_alarm_belongs_to_the_1959_leg_not_this_one():
    assert age.aged_unrefreshed_citations([_lit()], {}, now=NOW) == []


def test_a_held_suppressor_is_excluded():
    assert age.aged_unrefreshed_citations([_lit(by_construction=True)], {"qa-smoke-warnings": {"citation": "#1"}}, now=NOW) == []


def test_render_names_the_alarm_and_the_stamp():
    lines = age.render_lines(
        age.aged_unrefreshed_citations([_lit()], {"qa-smoke-warnings": {"citation": "#1", "cause_observed": "2026-09-18"}}, now=NOW)
    )
    assert "qa-smoke-warnings" in "\n".join(lines) and "2026-09-18" in "\n".join(lines)


def _wire_main(monkeypatch, alarms, citations):
    monkeypatch.setattr(cac, "fetch_alarms", lambda: (alarms, None))
    monkeypatch.setattr(cac, "load_citations", lambda: citations)
    monkeypatch.setattr(cac, "load_alarm_audience", lambda: {})
    monkeypatch.setattr(cac, "fetch_alarm_history", lambda: ([], None))
    monkeypatch.setattr(cac, "fetch_all_alarm_names", lambda: ({a["name"] for a in alarms}, None))
    monkeypatch.setattr(cac, "fetch_issue_states", lambda refs: ({str(r): "OPEN" for r in refs}, None))
    monkeypatch.setattr(cac, "fetch_qa_smoke_causes", lambda: ({}, None))
    monkeypatch.setattr(sys, "argv", ["check_alarm_citations.py"])


def test_planted_stale_citation_fails_the_real_gate(monkeypatch, capsys):
    """The must-fail control, through check_alarm_citations.main(): an alarm red ~4 days
    whose citation was stamped the SAME DAY the episode began (so no timestamp proves anyone
    looked after it went red) exits 1, by name — while every pre-existing leg passes it:
    it is cited (#1959), its #N is open (#2996), and a same-day stamp is not "before the
    episode" to #3501's deliberately lenient day-granularity check."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=100)
    stale_day = start.date().isoformat()
    assert (
        cac.stale_episode_citations([{"name": "planted-alarm", "transitioned": start.isoformat()}], {"planted-alarm": {"added": stale_day}})
        == []
    )
    alarm = {"name": "planted-alarm", "updated": start.isoformat(), "transitioned": start.isoformat()}
    _wire_main(monkeypatch, [alarm], {"planted-alarm": {"citation": "#4034", "cause_observed": stale_day, "added": stale_day}})
    assert cac.main() == 1
    out = capsys.readouterr().out
    assert "does not POST-DATE" in out and "planted-alarm" in out

    fresh_day = (start + timedelta(days=1)).date().isoformat()
    _wire_main(monkeypatch, [alarm], {"planted-alarm": {"citation": "#4034", "cause_observed": fresh_day, "added": fresh_day}})
    assert cac.main() == 0, capsys.readouterr().out
