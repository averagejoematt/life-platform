"""#5074 — the owner's 3.0 / 3.5 lb/wk rate band is read from the charter by every rate reader.

Covers: the band in both units at two bodyweights, in/below/above, the redline target + the critics reading it,
the landing hand-off, the clinical-guidance precedence (neutral fixture wording) and that nothing from the clinical
record is logged or carried, and that the band comes from the CHARTER (a changed charter value moves every reader).
"""

import json
import logging
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (_REPO / "lambdas", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from coach import critics  # noqa: E402
from health import nutrition_critics as nc  # noqa: E402
from training import owner_redlines, rate_band, redline_rate, training_charter  # noqa: E402

# A neutral clinical-guidance line (fixture wording only): it caps a loss rate.
CAP_RULE = "Example public rule: keep the weekly loss rate under 2.0 lb/wk; prescribe intensity by effort."
OTHER_RULE = "Example public rule: prescribe intensity by effort, not numbers."


# ── the band, both units, two bodyweights ─────────────────────────────────────────────
@pytest.mark.parametrize("weight,floor_pct,ceiling_pct", [(300.0, 1.0, 1.17), (250.0, 1.2, 1.4)])
def test_the_band_is_the_charters_in_both_units_at_the_current_weight(weight, floor_pct, ceiling_pct):
    b = rate_band.band(weight)
    assert (b["floor_lb_wk"], b["ceiling_lb_wk"]) == (3.0, 3.5)
    assert (b["floor_pct_bw"], b["ceiling_pct_bw"]) == (floor_pct, ceiling_pct)
    assert b["governs"] is True and b["guidance_capped"] is False


@pytest.mark.parametrize("rate,pos", [(2.4, "below"), (3.0, "in"), (3.3, "in"), (3.5, "in"), (3.9, "above"), (None, None)])
def test_in_below_above_band(rate, pos):
    v = rate_band.band_view(300.0, rate)
    assert v["position"] == pos and v["in_band"] is (None if pos is None else pos == "in")


def test_the_band_follows_the_charter_not_a_copy(monkeypatch):
    real = training_charter.charter_value
    monkeypatch.setattr(
        training_charter,
        "charter_value",
        lambda path, default=None: {"governing_goal.rate_band_lb_per_wk.floor": 2.0, "governing_goal.rate_band_lb_per_wk.ceiling": 2.5}.get(
            path, real(path, default)
        ),
    )
    assert (rate_band.band(300.0)["floor_lb_wk"], rate_band.band(300.0)["ceiling_lb_wk"]) == (2.0, 2.5)
    rt = owner_redlines.rate_target_lb_per_wk(300.0)
    assert (rt["low_lb_wk"], rt["high_lb_wk"], rt["target_lb_wk"], rt["cap_lb_wk"]) == (2.0, 2.5, 2.5, 2.5)


def test_an_unreadable_charter_serves_no_target_rather_than_a_guess(monkeypatch):
    monkeypatch.setattr(training_charter, "charter_value", lambda path, default=None: default)
    assert rate_band.band(300.0) is None and rate_band.band_view(300.0, 3.2) is None
    assert owner_redlines.rate_target_lb_per_wk(300.0) is None
    assert owner_redlines.rate_target_lb_per_wk(210.0) is not None  # the landing schedule is his own, not the charter's


# ── the redline target, and how it composes with the landing ──────────────────────────
def test_the_redline_target_reads_the_band_above_the_landing_and_his_schedule_below():
    above = owner_redlines.rate_target_lb_per_wk(300.0)
    assert (above["low_lb_wk"], above["high_lb_wk"], above["target_lb_wk"], above["cap_lb_wk"]) == (3.0, 3.5, 3.5, 3.5)
    assert above["band"]["floor_pct_bw"] == 1.0 and above["landing_phase"] is False
    at_landing = owner_redlines.rate_target_lb_per_wk(240.0)  # NOT above 240: the landing schedule governs
    assert at_landing["landing_phase"] is True and at_landing["target_lb_wk"] == 2.25 and at_landing["band"]["governs"] is False
    assert at_landing["high_lb_wk"] != 3.5  # the %BW envelope, not the charter band


# ── the critics read the band ─────────────────────────────────────────────────────────
def _advocate(rate, weight=300.0, **kw):
    return critics.build_rate_advocate_packet(
        {"total_sets": 20},
        tripwires=[],
        walking=None,
        rate_target=owner_redlines.rate_target_lb_per_wk(weight, **kw),
        current_rate_lb_wk=rate,
        lifting_sessions_7d=3,
    )


def _rate_flags(p):
    return [f for f in p["flags"] if f.get("field") == "current_rate_lb_wk" or "band he set" in json.dumps(f)]


def test_the_rate_advocates_flag_is_graded_against_the_band():
    assert "under the 3.0-3.5 lb/wk band" in json.dumps(_rate_flags(_advocate(2.4)))
    assert not _rate_flags(_advocate(3.2))  # in band: nothing to say
    assert "ABOVE the 3.0-3.5 lb/wk band" in json.dumps(_rate_flags(_advocate(3.9)))
    n = _advocate(3.2)["numbers"]
    assert (n["rate_band_low_lb_wk"], n["rate_band_high_lb_wk"]) == (3.0, 3.5)
    assert n["rate_band_floor_pct_bw"] and n["rate_band_ceiling_pct_bw"] > n["rate_band_floor_pct_bw"]


def test_the_deficit_advocate_reads_the_band_and_the_schedule_cap():
    n = nc.build_deficit_advocate_packet({"weight_lb": 300.0})["numbers"]
    assert (n["rate_band_low_lb_wk"], n["rate_band_high_lb_wk"], n["rate_target_lb_wk"], n["rate_cap_lb_wk"]) == (3.0, 3.5, 3.5, 3.5)
    assert (n["rate_band_floor_pct_bw"], n["rate_band_ceiling_pct_bw"]) == (1.0, 1.17)


# ── precedence: the clinical guidance outranks the band ───────────────────────────────
def test_a_guidance_line_that_caps_the_rate_is_parsed_and_one_that_does_not_is_ignored():
    assert rate_band.guidance_cap_lb_wk([OTHER_RULE, CAP_RULE]) == 2.0
    assert rate_band.guidance_cap_lb_wk([OTHER_RULE]) is None and rate_band.guidance_cap_lb_wk(None) is None
    assert rate_band.guidance_cap_lb_wk(["Example: 5 lb/wk was his 2024 pace."]) is None  # no cap word, no cap


def test_the_guidance_cap_outranks_the_band_in_every_reader():
    b = rate_band.band(300.0, 2.0)
    assert (b["floor_lb_wk"], b["ceiling_lb_wk"], b["guidance_capped"]) == (2.0, 2.0, True)
    rt = owner_redlines.rate_target_lb_per_wk(300.0, guidance_cap_lb_wk=2.0)
    assert (rt["high_lb_wk"], rt["target_lb_wk"], rt["cap_lb_wk"]) == (2.0, 2.0, 2.0)
    assert "ABOVE the 2.0-2.0 lb/wk band" in json.dumps(_rate_flags(_advocate(2.6, guidance_cap_lb_wk=2.0)))
    n = nc.build_deficit_advocate_packet({"weight_lb": 300.0, "guidance_cap_lb_wk": 2.0})["numbers"]
    assert (n["rate_band_high_lb_wk"], n["rate_target_lb_wk"], n["rate_cap_lb_wk"]) == (2.0, 2.0, 2.0)
    q = {"value": 2.6, "provisional": False, "experiment_week": 7}
    assert redline_rate.rate_ceiling_check(q, 300.0)["state"] == "clear"
    assert redline_rate.rate_ceiling_check(q, 300.0, 2.0)["state"] == "tripped"
    assert rate_band.flag_threshold_lb_wk(300.0, 2.0) == 2.0 and rate_band.flag_threshold_lb_wk(300.0) == 3.5
    v = rate_band.band_view(300.0, 2.6, 2.0)
    assert v["position"] == "above" and v["guidance_capped"] is True


class _Table:
    def __init__(self, items=None, error=None):
        self.items, self.error = items, error

    def query(self, **kw):
        if self.error:
            raise self.error
        return {"Items": self.items}


def test_the_guidance_is_read_from_the_clinical_partition_failsoft():
    row = {"pk": "USER#matthew#SOURCE#clinical", "sk": "GUIDANCE#current", "public_rules": [CAP_RULE], "rules": ["PRIVATE-DETAIL-XYZ"]}
    assert rate_band.guidance_cap_for(_Table([row])) == 2.0
    assert rate_band.guidance_cap_for(_Table([])) is None and rate_band.guidance_cap_for(None) is None
    with pytest.raises(rate_band.GuidanceReadError):  # a broken read is not 'no cap' (ADR-105)
        rate_band.guidance_cap_for(_Table(error=RuntimeError("boom")))


# ── privacy: no clinical detail is logged, carried or published ───────────────────────
def test_no_reader_logs_or_carries_clinical_detail(caplog):
    secret = "PRIVATE-DETAIL-XYZ"
    row = {"pk": "p", "sk": "GUIDANCE#current", "public_rules": [CAP_RULE], "rules": [secret]}
    with caplog.at_level(logging.DEBUG):
        cap = rate_band.guidance_cap_for(_Table([row]))
        with pytest.raises(rate_band.GuidanceReadError) as ei:
            rate_band.guidance_cap_for(_Table(error=RuntimeError(f"denied {secret} {CAP_RULE}")))
    assert secret not in str(ei.value)
    assert cap == 2.0
    assert secret not in caplog.text and CAP_RULE not in caplog.text and "denied" not in caplog.text
    carried = json.dumps(
        [
            rate_band.band(300.0, cap),
            rate_band.band_view(300.0, 2.6, cap),
            owner_redlines.rate_target_lb_per_wk(300.0, guidance_cap_lb_wk=cap),
        ]
    )
    assert secret not in carried and "Example public rule" not in carried and "under 2.0" not in carried


def test_the_band_is_not_on_the_published_charter_view():
    assert "governing_goal" not in training_charter.public_view()
    assert "rate_band" not in json.dumps(training_charter.public_view())


def test_a_broken_guidance_read_is_reported_not_read_as_no_cap(monkeypatch):
    from health import clinical_facts as cf

    from mcp import nutrition_critics_inputs as nci

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(cf, "fetch_clinical_rows", boom)
    monkeypatch.setattr(nci, "_guidance_cap", lambda: rate_band.guidance_cap_for(_Table([])))
    with pytest.raises(rate_band.GuidanceReadError):
        rate_band.guidance_cap_for(_Table([]))
