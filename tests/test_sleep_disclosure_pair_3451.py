"""tests/test_sleep_disclosure_pair_3451.py — #3451: the sleep disclosure pair.

Two gaps, verifier-confirmed (calc-proof pass, 2026-09-02):

1. The weekly-signal email's sleep row rendered "Avg Sleep X hrs" with no window
   label, next to the #1917-fixed weight row which DOES state its real window
   ("(↓X lbs 7d)"). Pins the fix: the sleep row now carries its n + window too.

2. Home vitals (Whoop SoT) and the /sleep hero (Eight Sleep) can disagree on the
   same night with nothing disclosing they're two different devices. #2921
   sanctioned the dual numbers; its own closing rule — "saying so, every time" —
   was not enforced anywhere. `weight_truth_qa.assess_cross_surface_sleep_disclosure`
   is the regression guard: a real divergence with a device label is a clean pass,
   the SAME divergence with no label FAILS.

(The front-end render proof — the /sleep hero DOM actually carrying the caption —
lives in tests/test_sleep_device_disclosure_3451.py, a Playwright render-qa test.)
"""

import importlib
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "compute")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

wsl = importlib.import_module("weekly_signal_lambda")

from operational.weight_truth_qa import (  # noqa: E402
    CROSS_SURFACE_SLEEP_DISCLOSURE_TOL_HRS,
    assess_cross_surface_sleep_disclosure,
)

# ── the weekly-signal sleep row ─────────────────────────────────────────────


def test_the_sleep_row_carries_its_n_and_window():
    """Matches the #1917-fixed weight row's discipline: a real number beside the
    span it actually covers, not a bare "30d" that could be covering 3 nights."""
    html = wsl._build_numbers({"vitals": {"sleep_hours_30d_avg": 7.2, "sleep_hours_30d_n": 20}, "character": {}})
    assert "7.2 hrs" in html
    assert "20n" in html or "20" in html, "the n must be visible beside the average"
    assert "30d" in html, "the window must be named, not implied"


def test_the_sleep_row_degrades_cleanly_with_no_n():
    """A pre-#3451 payload (no n key at all) must still render the average —
    the window label is additive, never a hard requirement to show the number."""
    html = wsl._build_numbers({"vitals": {"sleep_hours_30d_avg": 7.2}, "character": {}})
    assert "7.2 hrs" in html
    assert "Avg Sleep" in html


def test_the_sleep_row_is_absent_with_no_average():
    html = wsl._build_numbers({"vitals": {}, "character": {}})
    assert "Avg Sleep" not in html


# ── the cross-surface disclosure gate ───────────────────────────────────────


def test_agreement_within_tolerance_needs_no_disclosure():
    vitals = {"sleep_hours": 7.0}
    sleep_detail = {"total_sleep_hours": 7.0 + CROSS_SURFACE_SLEEP_DISCLOSURE_TOL_HRS}
    ok, msg = assess_cross_surface_sleep_disclosure(vitals, sleep_detail)
    assert ok, msg


def test_a_real_divergence_with_a_device_label_is_a_clean_pass():
    """The live #3451 specimen shape: 6.8h (Whoop) vs 1.1h (Eight Sleep), same
    night — divergent, but disclosed, so #2921's dual-number posture stands."""
    vitals = {"sleep_hours": 6.8}
    sleep_detail = {"total_sleep_hours": 1.1, "figure_scope": {"total_sleep_hours_source": "eightsleep"}}
    ok, msg = assess_cross_surface_sleep_disclosure(vitals, sleep_detail)
    assert ok, msg
    assert "eightsleep" in msg


def test_the_same_divergence_with_no_disclosure_fails():
    """The regression this check exists to catch: same numbers, but the API
    payload forgot to name the device — the #3451 defect, verbatim."""
    vitals = {"sleep_hours": 6.8}
    sleep_detail = {"total_sleep_hours": 1.1}  # no figure_scope at all
    ok, msg = assess_cross_surface_sleep_disclosure(vitals, sleep_detail)
    assert not ok
    assert "no device" in msg.lower() or "no device disclosure" in msg.lower()


def test_the_same_divergence_with_an_empty_figure_scope_still_fails():
    vitals = {"sleep_hours": 6.8}
    sleep_detail = {"total_sleep_hours": 1.1, "figure_scope": {"total_sleep_hours_source": None}}
    ok, _ = assess_cross_surface_sleep_disclosure(vitals, sleep_detail)
    assert not ok


def test_absence_on_either_side_is_a_clean_pass():
    """ADR-104: a null reading is nothing to contradict, on either surface."""
    ok, msg = assess_cross_surface_sleep_disclosure({"sleep_hours": None}, {"total_sleep_hours": 1.1})
    assert ok, msg
    ok, msg = assess_cross_surface_sleep_disclosure({"sleep_hours": 6.8}, {})
    assert ok, msg
    ok, msg = assess_cross_surface_sleep_disclosure(None, {"total_sleep_hours": 1.1})
    assert ok, msg


# ── checks() wiring: a third leg, fetched independently ─────────────────────


class _FakeCheck:
    """Mirrors operational.qa_check.Check's public shape without importing it,
    so this stays a pure-unit test of weight_truth_qa's OWN wiring."""

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


def _fake_urlopen_factory(payloads_by_path, failing_paths=frozenset()):
    import io

    def _fake_urlopen(req, timeout=15):
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        path = "/" + path
        if path in failing_paths:
            raise OSError(f"simulated fetch failure for {path}")
        import json as _json

        body = _json.dumps(payloads_by_path.get(path, {})).encode("utf-8")

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp(body)

    return _fake_urlopen


def test_checks_returns_three_named_legs(monkeypatch):
    import operational.weight_truth_qa as wq

    payloads = {
        "/api/vitals": {"vitals": {"sleep_hours": 6.8, "weight_lbs": 200}},
        "/api/coaching-dashboard": {"coaches": []},
        "/api/sleep_detail": {"sleep_detail": {"total_sleep_hours": 6.8}},
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen_factory(payloads))
    results = wq.checks(_FakeCheck, "http://example.test", "content_truth")
    names = {c.name for c in results}
    assert names == {"cross_surface:weight", "cross_surface:vitals", "cross_surface:sleep_disclosure"}
    assert all(c.passed for c in results), [(c.name, c.message) for c in results]


def test_a_sleep_detail_only_outage_does_not_blank_the_weight_and_vitals_legs(monkeypatch):
    import operational.weight_truth_qa as wq

    payloads = {
        "/api/vitals": {"vitals": {"sleep_hours": 6.8, "weight_lbs": 200}},
        "/api/coaching-dashboard": {"coaches": []},
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen_factory(payloads, failing_paths={"/api/sleep_detail"}))
    results = wq.checks(_FakeCheck, "http://example.test", "content_truth")
    by_name = {c.name: c for c in results}
    assert by_name["cross_surface:weight"].passed is True
    assert by_name["cross_surface:vitals"].passed is True
    assert by_name["cross_surface:sleep_disclosure"].passed is None  # warned, not failed


def test_a_vitals_outage_warns_all_three_legs_fail_soft(monkeypatch):
    import operational.weight_truth_qa as wq

    payloads = {"/api/coaching-dashboard": {"coaches": []}, "/api/sleep_detail": {"sleep_detail": {"total_sleep_hours": 6.8}}}
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen_factory(payloads, failing_paths={"/api/vitals"}))
    results = wq.checks(_FakeCheck, "http://example.test", "content_truth")
    assert all(c.passed is None for c in results), [(c.name, c.passed) for c in results]
