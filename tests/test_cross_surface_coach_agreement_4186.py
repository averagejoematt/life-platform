"""tests/test_cross_surface_coach_agreement_4186.py — #4186: the reader-truth leg
never compares coach-to-coach or coach-to-engine.

THE LIVE CORPUS, 2026-09-25 (Session AV B3 audit). One `/api/coaching-dashboard`
page served, on the same night `cross_surface:vitals` went red on a TREND
sentence (#4180):

  * protein: Eli Marsh "his average intake has dropped to 106.9 grams across 14
    logged days" vs Marcus Webb "His protein EWMA sits at 154g from 19 logged
    days" vs `/api/nutrition_overview` `avg_protein_g` 153.3
  * a logging gap: Webb "The food log went dark after September 19th … Six days
    without logs" vs `/api/nutrition_overview` `days_logged` 20 / `lag_days` 0
  * loss rate: Eli "3.7 pounds per week" vs Dr. Okafor "−4.4 lb/week" vs
    `/api/journey` `weekly_rate_lbs` −4.58, CI [−4.86, −2.66]

`cross_surface:*` stayed green through all of it — nothing compared a coach to
another coach, or a coach to the engine's own served facts, for nutrition or the
loss rate.

THE FIX: two new legs, `cross_surface:coach_consistency` and
`cross_surface:coach_vs_engine`, both built on `coach_quantity_claims` — the
SAME #4180 classifier, so a trend's start (or a dated/target-framed figure) is
skipped and named, never mis-compared here either.

CHOSEN RULES (stated here, not just in code, per the acceptance):
  * Two `current`/`trend_end` claims for the SAME quantity from DIFFERENT coaches
    are compared UNCONDITIONALLY — a differently-named window/day-count is NOT
    an excuse (106.9 matches no served field for ANY window).
  * `rate` is the one quantity compared by MAGNITUDE (a coach's unsigned "X
    pounds per week" vs the engine's signed `weekly_rate_lbs`) — sign is never
    read, only size. Tolerance is the engine's own CI half-width where served.
  * `days_logged` (a coach's own stated window size) is compared coach-to-coach
    ONLY, never coach-to-engine (ambiguous: a coach's own trailing window vs the
    engine's query-window total are not the same fact). `log_gap_days` (a
    claimed logging GAP) carries no such ambiguity and IS compared to `lag_days`.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from operational import weight_truth_qa as wq  # noqa: E402

# ── The 2026-09-25 corpus, as measured (paste verbatim per the issue) ─────────

ELI_PROTEIN = {"name": "Eli Marsh", "position_summary": "his average intake has dropped to 106.9 grams across 14 logged days"}
WEBB_PROTEIN = {"name": "Marcus Webb", "position_summary": "His protein EWMA sits at 154g from 19 logged days"}
WEBB_GAP = {
    "name": "Marcus Webb",
    "position_summary": "The food log went dark after September 19th … Six days without logs",
}
ELI_RATE = {"name": "Eli Marsh", "position_summary": "3.7 pounds per week"}
OKAFOR_RATE = {"name": "Dr. Okafor", "position_summary": "−4.4 lb/week"}

NUTRITION_09_25 = {"avg_protein_g": 153.3, "days_logged": 20, "lag_days": 0}
JOURNEY_09_25 = {"weekly_rate_lbs": -4.58, "weekly_rate_ci_low": -4.86, "weekly_rate_ci_high": -2.66}
_RATE_CI_09_25 = (JOURNEY_09_25["weekly_rate_ci_low"], JOURNEY_09_25["weekly_rate_ci_high"])


# ── (i) protein: coach-to-coach AND coach-to-engine, both FAIL ────────────────


def test_i_protein_coach_consistency_fails_106_9_vs_154():
    ok, msg = wq.assess_cross_surface_coach_consistency([ELI_PROTEIN, WEBB_PROTEIN])
    assert not ok, msg
    assert "106.9" in msg and "154" in msg and "protein" in msg
    assert "Eli Marsh" in msg and "Marcus Webb" in msg


def test_i_protein_coach_vs_engine_fails_on_106_9_only():
    ok, msg = wq.assess_cross_surface_coach_vs_engine([ELI_PROTEIN, WEBB_PROTEIN], nutrition=NUTRITION_09_25, journey=JOURNEY_09_25)
    assert not ok, msg
    assert "106.9" in msg and "153.3" in msg
    # Webb's 154 is within COACH_CONSISTENCY_TOL of the engine's 153.3g — it must
    # not ALSO be named as a disagreement (only 106.9 is a real contradiction).
    assert "154" not in msg.split("engine's own served fact —", 1)[-1].split("(claims:")[0]


def test_i_a_differently_named_window_is_not_an_excuse_for_protein():
    """Both sentences name their own day-count window (14 vs 19 logged days) —
    the chosen rule is that this does NOT excuse the protein disagreement,
    because 106.9 matches no served field for ANY window."""
    ok, _msg = wq.assess_cross_surface_coach_consistency([ELI_PROTEIN, WEBB_PROTEIN])
    assert not ok


# ── (ii) a logging gap vs the engine's own lag_days ───────────────────────────


def test_ii_log_gap_fails_against_engine_lag_days():
    ok, msg = wq.assess_cross_surface_coach_vs_engine([WEBB_GAP], nutrition=NUTRITION_09_25, journey=JOURNEY_09_25)
    assert not ok, msg
    assert "log_gap_days" in msg and "6" in msg and "engine 0" in msg


def test_ii_the_word_number_six_is_parsed_not_just_digits():
    claims = wq.coach_quantity_claims(WEBB_GAP)
    assert claims.get("log_gap_days") == [(6.0, "current")], claims


def test_ii_days_logged_is_not_compared_to_the_engine_days_logged_field():
    """Documented limit: a coach's own window size is ambiguous against the
    engine's query-window total, so `days_logged` is coach-to-coach only."""
    ok, msg = wq.assess_cross_surface_coach_vs_engine([WEBB_PROTEIN], nutrition=NUTRITION_09_25, journey=JOURNEY_09_25)
    assert ok, msg  # 154 agrees with 153.3; days_logged=19 is never checked here at all
    assert "days_logged" not in msg


# ── (iii) loss rate: magnitude comparison against a signed engine CI ──────────


def test_iii_rate_consistency_passes_by_magnitude_within_the_engine_ci_half_width():
    ok, msg = wq.assess_cross_surface_coach_consistency([ELI_RATE, OKAFOR_RATE], rate_ci=_RATE_CI_09_25)
    assert ok, msg


def test_iii_rate_vs_engine_passes_for_both_coaches():
    ok, msg = wq.assess_cross_surface_coach_vs_engine([ELI_RATE, OKAFOR_RATE], nutrition=NUTRITION_09_25, journey=JOURNEY_09_25)
    assert ok, msg


def test_iii_the_unicode_minus_sign_is_parsed():
    claims = wq.coach_quantity_claims(OKAFOR_RATE)
    assert claims.get("rate") == [(-4.4, "current")], claims


def test_iii_a_rate_disagreement_past_the_ci_half_width_still_fails():
    """Negative control: a genuinely differing rate (outside the CI half-width)
    must still fail — the magnitude rule narrows what disagrees, it does not
    widen it to everything."""
    far_off = {"name": "Dr. Someone", "position_summary": "9.5 lb/week"}
    ok, msg = wq.assess_cross_surface_coach_vs_engine([far_off], nutrition=NUTRITION_09_25, journey=JOURNEY_09_25)
    assert not ok, msg
    assert "rate" in msg


# ── (iv) mutation control: the same figure cited twice → PASS ─────────────────


def test_iv_the_same_figure_twice_passes_consistency():
    a = {"name": "A", "position_summary": "protein intake is 150 grams."}
    b = {"name": "B", "position_summary": "protein intake is 150 grams."}
    ok, msg = wq.assess_cross_surface_coach_consistency([a, b])
    assert ok, msg


def test_iv_the_same_coach_citing_itself_twice_is_not_a_disagreement():
    coach = {"name": "A", "position_summary": "Protein was 150g at breakfast and protein was 150g total."}
    ok, msg = wq.assess_cross_surface_coach_consistency([coach])
    assert ok, msg


# ── #4180's classifier is shared: a trend's start is skipped and named, never
# mis-compared by either #4186 leg ─────────────────────────────────────────────


def test_a_trend_start_is_skipped_by_coach_quantity_claims():
    coach = {"name": "c", "position_summary": "His recovery EWMA has climbed from 71.7% to 82.2% over seven days."}
    claims = wq.coach_quantity_claims(coach)
    values = [v for v, _cls in claims.get("recovery", [])]
    assert 71.7 not in values
    assert claims.get("recovery") == [(82.2, "trend_end")]


def test_the_4180_trend_sentence_is_skipped_and_named_by_both_4186_legs():
    coach = {"name": "c", "position_summary": "His recovery EWMA has climbed from 71.7% to 82.2% over seven days."}
    ok, msg = wq.assess_cross_surface_coach_consistency([coach])
    assert ok, msg
    assert "1 skipped as trend-start" in msg


# ── the dead-man: both legs ALWAYS emit a claim count, pass or fail ───────────


def test_consistency_leg_emits_a_count_on_a_clean_pass():
    ok, msg = wq.assess_cross_surface_coach_consistency([])
    assert ok, msg
    assert "claims: 0 extracted" in msg


def test_vs_engine_leg_emits_a_count_when_no_engine_payload_is_supplied():
    ok, msg = wq.assess_cross_surface_coach_vs_engine([ELI_PROTEIN])
    assert ok, msg  # absence of an engine fact is a clean pass (ADR-104)
    assert "claims:" in msg and "skipped — no served engine field" in msg


# ── checks() wiring: the two new legs ride the coaching-dashboard fetch ───────


class _FakeCheck:
    def __init__(self, name, category, partition):
        self.name, self.category, self.partition = name, category, partition
        self.passed = None
        self.message = ""

    def ok(self, msg=""):
        self.passed, self.message = True, msg
        return self

    def fail(self, msg=""):
        self.passed, self.message = False, msg
        return self

    def warn(self, msg="", chronic=False):
        self.passed, self.message = None, msg
        return self


def _fake_urlopen_factory(payloads_by_path):
    import io
    import json as _json

    def _fake_urlopen(req, timeout=15):
        path = "/" + req.full_url.split("://", 1)[1].split("/", 1)[1]
        body = _json.dumps(payloads_by_path.get(path, {})).encode("utf-8")

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp(body)

    return _fake_urlopen


def test_checks_wires_both_new_legs_and_fails_on_the_live_corpus(monkeypatch):
    payloads = {
        "/api/vitals": {"vitals": {}},
        "/api/coaching-dashboard": {"coaches": [ELI_PROTEIN, WEBB_PROTEIN]},
        "/api/sleep_detail": {"sleep_detail": {}},
        "/api/nutrition_overview": {"nutrition": NUTRITION_09_25},
        "/api/journey": {"journey": JOURNEY_09_25},
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen_factory(payloads))
    results = wq.checks(_FakeCheck, "http://example.test", "content_truth")
    by_name = {c.name: c for c in results}
    assert "cross_surface:coach_consistency" in by_name
    assert "cross_surface:coach_vs_engine" in by_name
    assert by_name["cross_surface:coach_consistency"].passed is False
    assert by_name["cross_surface:coach_vs_engine"].passed is False


def test_checks_new_legs_warn_fail_soft_when_the_dashboard_fetch_fails(monkeypatch):
    def _raise(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    results = wq.checks(_FakeCheck, "http://example.test", "content_truth")
    by_name = {c.name: c for c in results}
    assert by_name["cross_surface:coach_consistency"].passed is None
    assert by_name["cross_surface:coach_vs_engine"].passed is None


# ── mutation control: disabling the log-gap word-number parse reds fixture (ii) ─


def test_mutation_disabling_number_words_reds_fixture_ii(monkeypatch):
    monkeypatch.setattr(wq, "_NUMBER_WORDS", {})
    ok, _msg = wq.assess_cross_surface_coach_vs_engine([WEBB_GAP], nutrition=NUTRITION_09_25, journey=JOURNEY_09_25)
    assert ok, "disabling word-number parsing must silently lose the 'Six days without logs' claim, turning the FAIL into a PASS"
