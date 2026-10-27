"""tests/test_step_back_up_min_days_5122.py — a mode that covered fewer than `step_back_up.min_days` days owes no
step-back-up week (#5122).

Specimen: on 2026-10-26 the owner switched disruption mode on (busy, until 2026-10-26) and off 3 seconds later; the plan
entered `step_back_up` through 2026-11-01 (7 days of the minimum session) for a mode that covered one day.

The rule: no step-back-up when the mode covered fewer than `disruption.step_back_up.min_days` days (default 3, an
owner-default per ADR-105) or when it was ended the day it started; otherwise unchanged (7 days of the minimum, then the
full split). The lapse template has no step-back-up (its own `step_back_up: false`).

Every date is a fixed literal and the one clock read (the chat write path's default `ended_on`) is frozen (#4848).
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from common.pacific_time import shift_day_key  # noqa: E402
from training import (  # noqa: E402
    disruption as d,
    life_disruption as ld,
    training_charter as tc,
)


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _rec(template: str, start: str, until: str, ended_on: str | None = None) -> dict:
    rec = d.build_disruption_record(start_date=start, until=until, words="testing the switch", template=template, recorded_at="t")
    return d.end_record(rec, ended_on=ended_on, words="done", recorded_at="t") if ended_on else rec


def _phases(recs: list[dict], first: str, n: int) -> list[str]:
    return [d.state(recs, shift_day_key(first, i))["phase"] for i in range(n)]


def test_the_charter_carries_min_days_beside_days_and_labels_it_an_owner_default():
    sbu = d.policy()["step_back_up"]
    assert sbu["days"] == 7 and sbu["min_days"] == 3
    assert "owner-default" in sbu["min_days_basis"] and "ADR-105" in sbu["min_days_basis"]
    assert tc.charter_value("disruption.step_back_up.min_days") == 3


def test_the_specimen_on_and_off_the_same_day_owes_no_step_back_up_week():
    rec = _rec("busy", "2026-10-26", "2026-10-26", ended_on="2026-10-26")
    assert d.owes_step_back_up(rec) is False
    # the day itself, then every day through the old step_back_up_through (2026-11-01) and past it: off
    assert _phases([rec], "2026-10-26", 10) == ["off"] * 10
    assert d.state([rec], "2026-11-01") == {"phase": "off", "template": None, "pools": [], "sessions_per_wk": None}


def test_a_long_mode_ended_the_day_it_started_owes_none_either():
    rec = _rec("travel", "2026-12-20", "2026-12-30", ended_on="2026-12-20")
    assert d.covered_days(rec) == 0 and d.owes_step_back_up(rec) is False
    assert set(_phases([rec], "2026-12-20", 12)) == {"off"}


def test_a_two_day_mode_is_active_for_its_days_then_off():
    rec = _rec("busy", "2026-11-02", "2026-11-03")
    assert d.covered_days(rec) == 2 and d.owes_step_back_up(rec) is False
    assert _phases([rec], "2026-11-01", 4) == ["off", "active", "active", "off"]
    assert set(_phases([rec], "2026-11-04", 10)) == {"off"}


def test_a_long_mode_switched_off_after_two_days_owes_none_but_after_three_it_does():
    two = _rec("travel", "2026-11-02", "2026-11-12", ended_on="2026-11-04")  # covered 11-02, 11-03
    three = _rec("travel", "2026-11-02", "2026-11-12", ended_on="2026-11-05")  # covered 11-02..11-04
    assert (d.covered_days(two), d.owes_step_back_up(two)) == (2, False)
    assert (d.covered_days(three), d.owes_step_back_up(three)) == (3, True)
    assert d.state([two], "2026-11-04")["phase"] == "off"
    assert d.state([three], "2026-11-05")["phase"] == "step_back_up"


def test_a_three_day_mode_steps_back_up_for_seven_days_then_off():
    rec = _rec("busy", "2026-11-02", "2026-11-04")
    assert d.covered_days(rec) == 3 and d.owes_step_back_up(rec) is True
    phases = _phases([rec], "2026-11-01", 14)  # 11-01 .. 11-14
    assert phases == ["off"] + ["active"] * 3 + ["step_back_up"] * 7 + ["off"] * 3
    sbu = d.state([rec], "2026-11-05")
    assert sbu["step_back_up_through"] == "2026-11-11" and sbu["pools"] == ["gym_minimum", "bodyweight"] and sbu["then"] == "the full split"


def test_the_min_days_threshold_is_read_from_the_charter_not_hard_coded(monkeypatch):
    rec = _rec("busy", "2026-11-02", "2026-11-03")
    assert d.state([rec], "2026-11-04")["phase"] == "off"
    pol = d.policy()
    monkeypatch.setattr(d, "policy", lambda: {**pol, "step_back_up": {**pol["step_back_up"], "min_days": 2}})
    assert d.state([rec], "2026-11-04")["phase"] == "step_back_up"


def test_the_lapse_template_still_has_no_step_back_up_week():
    rec = _rec("lapse", "2026-11-01", "2026-11-03")  # 3 days: long enough, but the template says no
    assert d.covered_days(rec) == 3 and d.owes_step_back_up(rec) is False
    assert _phases([rec], "2026-11-01", 12) == ["active"] * 3 + ["off"] * 9


def test_an_active_state_says_whether_the_end_owes_a_week_and_the_owner_text_follows():
    short, long_ = _rec("life", "2026-11-01", "2026-11-02"), _rec("life", "2026-11-01", "2026-11-10")
    assert d.state([short], "2026-11-01")["owes_step_back_up"] is False
    assert d.state([long_], "2026-11-01")["owes_step_back_up"] is True
    short_text = "\n".join(ld.mode([short], "2026-11-01")["lines"])
    long_text = "\n".join(ld.mode([long_], "2026-11-01")["lines"])
    assert "no step-back-up week" in short_text and "stepping back up first" not in short_text
    assert "stepping back up first" in long_text and "no step-back-up week" not in long_text


def test_the_chat_write_path_reports_whether_ending_owes_a_week(monkeypatch):
    from mcp import tools_training_notes as tn

    written: list[dict] = []
    stored = d.build_disruption_record(
        start_date="2026-10-26", until="2026-10-26", words="testing the switch", template="busy", recorded_at="2026-10-27T04:03:45Z"
    )
    stored["sk"] = d.disruption_sk("2026-10-26")
    monkeypatch.setattr(tn, "_disruption_records", lambda: [dict(stored)])
    monkeypatch.setattr(tn, "_put_disruption", lambda rec: written.append(rec))
    monkeypatch.setattr(tn, "_now_z", lambda: "2026-10-27T04:03:48Z")
    monkeypatch.setattr(tn, "pacific_now", lambda: __import__("datetime").datetime(2026, 10, 26, 21, 3, 48))  # frozen: the owner's evening
    out = tn.tool_get_exercise_notes({"action": "disruption_end", "words": "testing the switch"})
    assert out["wrote"] is True and written[-1]["ended_on"] == "2026-10-26"
    assert out["owes_step_back_up"] is False
    assert d.state([written[-1]], "2026-10-27")["phase"] == "off"


def test_mutation_control_without_the_rule_the_specimen_reds(monkeypatch):
    """Remove the min_days / same-day check (the pre-fix, template-only rule): the specimen is back in step_back_up."""
    rec = _rec("busy", "2026-10-26", "2026-10-26", ended_on="2026-10-26")
    assert d.state([rec], "2026-10-27")["phase"] == "off"
    pre_fix = lambda r: ((d.policy().get("templates") or {}).get(r.get("template")) or {}).get("step_back_up") is not False  # noqa: E731
    monkeypatch.setattr(d, "owes_step_back_up", pre_fix)
    mutated = d.state([rec], "2026-10-27")
    assert mutated["phase"] == "step_back_up" and mutated["step_back_up_through"] == "2026-11-01"
