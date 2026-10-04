"""tests/test_narrative_cadence_4589.py — the long per-coach narratives, twice a week (#4589).

What is pinned, producer and consumers together (one constant, read by both sides):

  1. the cadence itself — Monday and Thursday, longest gap 4 days;
  2. the PRODUCER — on an off day the daily brief makes no v2 coach call and does not
     fan out the ensemble digest, holds nothing (no gate judged anything, #966) and still
     writes the short daily pieces; on a narrative day all of it runs (the mutation
     control);
  3. the CONSUMERS — the ENSEMBLE#digest dead-man expects a row only on narrative days
     (an off day is never a hole, a missed narrative day still is), and the coherence
     sentinel keeps a 4-day-old narrative in coverage, judged against its own day.
"""

import datetime as dt
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.invalid")
os.environ.setdefault("EMAIL_SENDER", "qa@example.invalid")
os.environ.setdefault("SITE_BASE_URL", "https://averagejoematt.com")

from coach import narrative_cadence as nc  # noqa: E402

MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = (
    "2026-10-05",
    "2026-10-06",
    "2026-10-07",
    "2026-10-08",
    "2026-10-09",
    "2026-10-10",
    "2026-10-11",
)


# ── 1. the cadence ────────────────────────────────────────────────────────────


def test_the_two_days_are_monday_and_thursday():
    assert [d for d in (MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY) if nc.is_narrative_day(d)] == [MONDAY, THURSDAY]
    assert nc.describe() == "Monday and Thursday"


def test_the_oldest_newest_narrative_is_four_days():
    assert nc.max_gap_days() == 4
    assert nc.last_narrative_day(SUNDAY) == dt.date.fromisoformat(THURSDAY)
    assert nc.next_narrative_day(SUNDAY) == dt.date.fromisoformat("2026-10-12")
    assert nc.last_narrative_day(MONDAY) == dt.date.fromisoformat(MONDAY)


def test_the_off_day_log_line_names_the_cadence_and_both_neighbours():
    line = nc.skip_line(SATURDAY)
    assert "Monday and Thursday" in line and THURSDAY in line and "2026-10-12" in line and "#4589" in line


def test_plan_runs_nothing_on_an_off_day_and_holds_nothing_either_way():
    roster = [("sleep", None, "Sleep"), ("labs", None, "Labs")]
    assert nc.plan(SATURDAY, roster) == ([], set())
    assert nc.plan(THURSDAY, roster) == (roster, set())


# ── 2. the producer: the daily brief ──────────────────────────────────────────

_V2 = [
    "call_sleep_coach_v2",
    "call_nutrition_coach_v2",
    "call_training_coach_v2",
    "call_mind_coach_v2",
    "call_physical_coach_v2",
    "call_glucose_coach_v2",
    "call_labs_coach_v2",
    "call_explorer_coach_v2",
]

_KW = dict(
    data={"date": "2026-10-09", "journal_entries": [{"raw_text": "quiet day"}]},
    profile={"goal_weight_lbs": 185},
    day_grade_score=79,
    grade="B+",
    component_scores={},
    component_details={},
    readiness_score=72,
    readiness_colour="#059669",
    character_sheet=None,
    brief_mode="standard",
)


@pytest.fixture()
def brief(monkeypatch):
    import daily_brief_lambda as m

    for name in _V2:
        monkeypatch.setattr(m.ai_calls, name, MagicMock(return_value="v2 text"))
    for name in ["call_board_of_directors", "call_journal_coach", "daily_brief_shared_system"]:
        monkeypatch.setattr(m.ai_calls, name, MagicMock(return_value="mock text"))
    monkeypatch.setattr(m.ai_calls, "call_tldr_and_guidance", MagicMock(return_value={"tldr": "t", "guidance": []}))
    monkeypatch.setattr(m.ai_calls, "call_training_nutrition_coach", MagicMock(return_value={"training": "t", "nutrition": "n"}))
    fake_boto = MagicMock()
    monkeypatch.setattr(m, "boto3", fake_boto)
    monkeypatch.setattr(m, "_daily_brief_ai_allowed", lambda: True)
    from coach import lead_daily_read

    monkeypatch.setattr(lead_daily_read, "run", lambda *a, **k: "stubbed")
    return m, fake_boto


def _ensemble_invokes(fake_boto):
    return [c for c in fake_boto.client.return_value.invoke.call_args_list if c.kwargs.get("FunctionName") == "coach-ensemble-digest"]


def test_an_off_day_makes_no_long_narrative_call_and_no_fan_out(brief, monkeypatch):
    m, fake_boto = brief
    monkeypatch.setattr(m, "pacific_today", lambda: SATURDAY)
    result = m._run_ai_coach_pipeline(**_KW)

    for name in _V2:
        getattr(m.ai_calls, name).assert_not_called()
    assert all(result[f"{d}_coach_v2_text"] == "" for d in ("sleep", "nutrition", "mind", "physical", "glucose", "labs", "explorer"))
    # Nothing to summarise, so no ensemble fan-out.
    assert _ensemble_invokes(fake_boto) == []
    # The short daily pieces stay daily, and nothing was HELD: the 2-4-sentence legacy
    # training/nutrition note runs with both domains intact.
    m.ai_calls.call_board_of_directors.assert_called_once()
    m.ai_calls.call_training_nutrition_coach.assert_called_once()
    assert result["training_nutrition"] == {"training": "t", "nutrition": "n"}


def test_a_narrative_day_runs_the_whole_roster_and_the_fan_out(brief, monkeypatch):
    """MUTATION CONTROL for the test above — the same fixture on a Thursday runs everything,
    so the off-day assertions cannot pass because the mocks were never reachable."""
    m, fake_boto = brief
    monkeypatch.setattr(m, "pacific_today", lambda: THURSDAY)
    result = m._run_ai_coach_pipeline(**_KW)

    for name in _V2:
        if name == "call_training_coach_v2":  # ADR-153: the training seat is retired from the roster
            continue
        getattr(m.ai_calls, name).assert_called_once()
    m.ai_calls.call_training_nutrition_coach.assert_called_once()
    assert result["sleep_coach_v2_text"] == "v2 text"
    calls = _ensemble_invokes(fake_boto)
    assert len(calls) == 1 and calls[0].kwargs["InvocationType"] == "Event"
    assert THURSDAY in calls[0].kwargs["Payload"].decode()


def test_a_dry_run_on_a_narrative_day_still_never_fans_out(brief, monkeypatch):
    """#2255 is unchanged by the cadence: a dry run is never a write."""
    m, fake_boto = brief
    monkeypatch.setattr(m, "pacific_today", lambda: MONDAY)
    m._run_ai_coach_pipeline(**_KW, persist=False)
    assert _ensemble_invokes(fake_boto) == []


# ── 3a. consumer: the ENSEMBLE#digest dead-man ────────────────────────────────


class _Table:
    def __init__(self, cycles):
        self.cycles = set(cycles)

    def query(self, **kw):
        exp = kw["KeyConditionExpression"].get_expression()
        lo, hi = None, None
        for v in exp["values"]:
            e = getattr(v, "get_expression", lambda: None)()
            if e and e.get("operator") == "BETWEEN":
                lo, hi = e["values"][1], e["values"][2]
        assert lo and hi, "the dead-man must range its query"
        return {"Items": [{"sk": "CYCLE#" + c} for c in sorted(self.cycles) if lo <= "CYCLE#" + c <= hi]}


def _deadman(cycles, iso_utc):
    from operational import ensemble_digest_qa as edq
    from operational.qa_check import CONTENT_TRUTH, Check

    moment = dt.datetime.fromisoformat(iso_utc).replace(tzinfo=dt.timezone.utc)
    return edq.check_ensemble_digest_liveness(_Table(cycles), Check, CONTENT_TRUTH, lambda: moment)[0]


def test_the_dead_man_never_counts_an_off_day_as_a_hole():
    """Saturday evening: Fri/Sat have no row BY DESIGN; Thursday's row is the one due."""
    c = _deadman([THURSDAY], f"{SATURDAY}T18:30:00")
    assert c.passed is True, c.message
    assert THURSDAY in c.message and FRIDAY not in c.message


def test_the_dead_man_still_fails_a_missed_narrative_day():
    """MUTATION CONTROL: Thursday's row missing on Thursday evening is the live FAIL."""
    c = _deadman([MONDAY], f"{THURSDAY}T18:30:00")
    assert c.passed is False, c.message
    assert f"CYCLE#{THURSDAY}" in c.message


def test_the_dead_man_window_always_holds_a_due_cycle():
    """Wednesday evening (the longest stretch since a write): Monday is still in the window."""
    c = _deadman([], f"{WEDNESDAY}T18:30:00")
    assert c.passed is False and MONDAY in c.message


# ── 3b. consumer: the coherence sentinel's freshness floor ────────────────────


def test_the_sentinel_keeps_a_four_day_old_narrative_in_coverage_judged_on_its_own_day(monkeypatch):
    from operational import coherence_sentinel_lambda as cs

    now = dt.datetime.fromisoformat(f"{MONDAY}T09:00:00-07:00")
    monkeypatch.setattr(cs.pacific_time, "pacific_now", lambda: now)
    old = (now.date() - dt.timedelta(days=nc.max_gap_days())).isoformat()  # last Thursday

    class _T:
        def get_item(self, **kw):
            return {}

        def query(self, **kw):
            return {"Items": [{"sk": f"OUTPUT#{old}#daily_brief_sleep", "content": "slept 7 hours"}]}

    monkeypatch.setattr(cs, "table", _T())
    monkeypatch.setattr(cs, "_latest", lambda *_a, **_k: {})
    monkeypatch.setattr(cs, "_facts_as_of_generation", lambda day: {"as_of_marker": day})
    _facts, narratives, labels, overrides = cs._gather_facts_and_narratives()
    sleep_label = f"coach:{cs.V2_COACHES[0]}"
    assert sleep_label in labels, f"a {nc.max_gap_days()}-day-old narrative fell out of coverage: {labels}"
    assert overrides[sleep_label]["as_of"] == old, "an aged narrative must be judged against its OWN day's facts (#2792)"
