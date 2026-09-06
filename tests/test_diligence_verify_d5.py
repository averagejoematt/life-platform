"""tests/test_diligence_verify_d5.py — the can-it-fail proof for the acceptance instrument.

`scripts/diligence_verify.py` is the A-Grade Program's evidence generator (D5, #3042): it
runs the external diligence report's §15 playbooks against live state and produces the
bundle the owner attaches to the re-grade. It currently reports 12/12 PASS.

An instrument that reports all-green and has never been shown capable of reporting
anything else is the exact defect this program keeps finding in its own machinery —
`drift_sentinel.check_codeql_alerts` had declared itself armed for weeks while never once
successfully reading the code-scanning API (#3112: three independent sufficient defects,
each of which produced a clean-looking result). #2578 turned that into a standing
question: *can this gate fail?* An evidence pack assembled by an unfalsifiable instrument
is worth less than no evidence pack, because it launders an unknown into a claim.

So every playbook is mutation-proved here. Each test plants a defect at the seam the
playbook reads — a demoted GitHub control, a leaked field in a live payload, a weakened
CSP header, an incoherent calibration claim — and asserts the verdict flips to FAIL. A
second group asserts the UNVERIFIED path: transport failures, auth failures and
unexpected exceptions must NOT be laundered into PASS.

No test here touches the network or AWS: every seam is monkeypatched, so this runs
offline and deterministically in the pre-merge lane.
"""

import json
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import diligence_verify as dv  # noqa: E402

FAIL, PASS, UNVERIFIED = dv.FAIL, dv.PASS, dv.UNVERIFIED


# ── the registry itself ──────────────────────────────────────────────────────────


def test_every_playbook_is_registered_with_a_family_and_a_dil_id():
    """An unregistered playbook never runs; a mis-familied one is silently skipped."""
    assert dv.PLAYBOOKS, "the playbook registry is empty"
    for pid, family, dil, fn in dv.PLAYBOOKS:
        assert family in dv.FAMILIES, f"{pid} declares unknown family {family!r}"
        assert dil.startswith("DIL-"), f"{pid} carries no DIL id"
        assert callable(fn), f"{pid} is not callable"


def test_dil_coverage_is_derived_from_the_registry_not_hand_typed():
    """The register quotes 'N of 52'; a hand-maintained copy is the #3101 drift class.

    Also pins the multi-id parse: one playbook may answer several findings
    ("DIL-008/011"), and collapsing that to a single id would silently understate
    coverage.
    """
    results = [{"dil": "DIL-008/011"}, {"dil": "DIL-004"}, {"dil": "DIL-008"}]
    assert dv.covered_dils(results) == {"DIL-008", "DIL-011", "DIL-004"}
    assert dv.TOTAL_DIL_FINDINGS == 52

    live = dv.covered_dils([{"dil": d} for _, _, d, _ in dv.PLAYBOOKS])
    assert live, "the registry asserts no DIL ids at all"
    assert len(live) <= dv.TOTAL_DIL_FINDINGS, "coverage cannot exceed the finding count"


def test_every_family_has_at_least_one_playbook():
    """A family with no playbooks would report a vacuous clean run for that whole domain."""
    covered = {family for _, family, _, _ in dv.PLAYBOOKS}
    assert covered == set(dv.FAMILIES), f"families with no playbook: {set(dv.FAMILIES) - covered}"


# ── FAIL paths: each control, demoted ────────────────────────────────────────────


def test_production_gate_fails_when_reviewers_are_removed(monkeypatch):
    monkeypatch.setattr(dv, "_gh", lambda ep, method="GET": (0, json.dumps({"protection_rules": [{"type": "branch_policy"}]})))
    v = dv.control_production_approval_gate()
    assert v.status == FAIL and "required_reviewers" in v.summary


def test_main_ruleset_fails_when_a_protection_rule_is_dropped(monkeypatch):
    def fake(ep, method="GET"):
        if ep.endswith("/rulesets"):
            return 0, json.dumps([{"id": 1, "enforcement": "active"}])
        return 0, json.dumps({"name": "weakened", "rules": [{"type": "deletion"}]})  # non_fast_forward gone

    monkeypatch.setattr(dv, "_gh", fake)
    v = dv.control_main_ruleset_active()
    assert v.status == FAIL and "non_fast_forward" in v.summary


def test_main_ruleset_fails_when_no_ruleset_is_active(monkeypatch):
    monkeypatch.setattr(dv, "_gh", lambda ep, method="GET": (0, json.dumps([{"id": 1, "enforcement": "disabled"}])))
    assert dv.control_main_ruleset_active().status == FAIL


def test_vulnerability_alerts_fails_on_the_disabled_404(monkeypatch):
    """The 404 that means 'disabled' must FAIL, and must not be confused with a transport 404."""
    monkeypatch.setattr(dv, "_gh", lambda ep, method="GET": (1, "gh: Not Found (HTTP 404)"))
    v = dv.control_vulnerability_alerts_enabled()
    assert v.status == FAIL and "DISABLED" in v.summary


def test_codeql_fails_when_alerts_are_open(monkeypatch):
    alerts = [{"rule": {"id": "js/redos", "security_severity_level": "high"}}]
    monkeypatch.setattr(dv, "_gh", lambda ep, method="GET": (0, json.dumps(alerts)))
    v = dv.control_codeql_alerts_triaged()
    assert v.status == FAIL and "1 open CodeQL alert" in v.summary


def test_private_marker_playbook_fails_on_a_planted_marker(monkeypatch, tmp_path):
    """Plant a real marker through the CANONICAL predicate, not a substring stand-in."""
    sys.path.insert(0, os.path.join(_REPO, "tests"))
    from test_no_private_markers_3043 import file_carries_private_marker

    planted = "> **Status:** PRIVATE / internal. Owner-only coaching material.\n"
    assert file_carries_private_marker(planted), "fixture is not actually a marker — test would be vacuous"

    monkeypatch.setattr(dv.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "docs/planted.md\n", "returncode": 0})())
    monkeypatch.setattr("builtins.open", lambda *a, **k: __import__("io").StringIO(planted))
    v = dv.privacy_no_private_markers_in_tree()
    assert v.status == FAIL and "PRIVATE marker" in v.summary


def test_relocated_docs_fail_if_one_is_served_again(monkeypatch):
    def fake_http(url, timeout=20):
        return (200 if "COACH_STANCE" in url else 404), {}, b""

    monkeypatch.setattr(dv, "_http", fake_http)
    v = dv.privacy_relocated_docs_are_404()
    assert v.status == FAIL and "COACH_STANCE.md" in str(v.summary)


def test_public_api_playbook_fails_when_an_owner_only_field_leaks(monkeypatch):
    """The leak check must fire on a field the registry classes owner-only."""
    from privacy.field_tiers import TIER_OWNER_ONLY, fields_at_tier

    leaked = sorted(fields_at_tier(TIER_OWNER_ONLY))[0]
    monkeypatch.setattr(dv, "_json_api", lambda path: {leaked: 42})
    v = dv.privacy_public_api_serves_no_owner_only_field()
    assert v.status == FAIL and leaked in " ".join(v.evidence)


def test_calibration_fails_when_it_claims_unearned_skill(monkeypatch):
    """The honesty invariant: `skilled` must follow from brier_skill, not precede it."""
    monkeypatch.setattr(dv, "_json_api", lambda p: {"platform": {"n": 40, "brier_skill": -0.05, "skilled": True}})
    v = dv.prediction_calibration_is_reported_honestly()
    assert v.status == FAIL and "claims skill" in v.summary


def test_calibration_fails_when_it_understates_demonstrated_skill(monkeypatch):
    """Dishonesty in the modest direction is still incoherence, and still fails."""
    monkeypatch.setattr(dv, "_json_api", lambda p: {"platform": {"n": 40, "brier_skill": 0.17, "skilled": False}})
    assert dv.prediction_calibration_is_reported_honestly().status == FAIL


def test_calibration_fails_on_nothing_graded(monkeypatch):
    monkeypatch.setattr(dv, "_json_api", lambda p: {"platform": {"n": 0, "brier_skill": 0.0, "skilled": False}})
    v = dv.prediction_calibration_is_reported_honestly()
    assert v.status == FAIL and "n=0" in v.summary


def test_gradable_share_fails_when_its_alarm_is_deleted(monkeypatch):
    """The DIL-007 failure mode is invisibility, so a MISSING alarm must FAIL, not skip."""

    class _CW:
        # #3503: AlarmTypes is stated on every alarm read now; the fake takes it so the
        # fixture is the wire (a fake that rejects a real kwarg turns a shape change into
        # a fake FAIL, which is what this signature did on the first run).
        def describe_alarms(self, AlarmNames, AlarmTypes=None):  # noqa: N803 — boto3 kwarg names
            assert AlarmTypes == ["MetricAlarm"], "the caller must state its alarm types"
            return {"MetricAlarms": []}

    monkeypatch.setitem(sys.modules, "boto3", type("m", (), {"client": staticmethod(lambda *a, **k: _CW())}))
    v = dv.prediction_gradable_share_healthy()
    assert v.status == FAIL and "does not exist" in v.summary


def test_csp_fails_when_unsafe_inline_returns(monkeypatch):
    weak = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'"
    monkeypatch.setattr(dv, "_http", lambda url, timeout=20: (200, {"content-security-policy": weak}, b""))
    v = dv.edge_csp_is_hardened()
    assert v.status == FAIL and "unsafe-inline" in v.summary


def test_csp_fails_when_a_cdn_is_reallowlisted(monkeypatch):
    weak = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net"
    monkeypatch.setattr(dv, "_http", lambda url, timeout=20: (200, {"content-security-policy": weak}, b""))
    assert dv.edge_csp_is_hardened().status == FAIL


def test_csp_fails_when_the_header_is_absent_entirely(monkeypatch):
    monkeypatch.setattr(dv, "_http", lambda url, timeout=20: (200, {}, b""))
    v = dv.edge_csp_is_hardened()
    assert v.status == FAIL and "no Content-Security-Policy" in v.summary


def test_rate_limit_fails_when_the_nightly_observation_is_unwired(monkeypatch):
    """Deleting the observation, or merely unhooking it, must be visible."""
    real_open = open

    def fake_open(path, *a, **k):
        if "qa_smoke_lambda" in str(path):
            return __import__("io").StringIO("# handler with the edge check removed\n")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    v = dv.edge_rate_limit_enforced()
    assert v.status == FAIL and "NOT wired" in v.summary


def test_freshness_fails_on_stale_data(monkeypatch):
    monkeypatch.setattr(dv, "_json_api", lambda p: {"vitals": {"as_of_date": "2020-01-01", "window_disclosure": "x"}})
    v = dv.edge_public_data_is_fresh()
    assert v.status == FAIL and "days old" in v.summary


def test_freshness_fails_when_the_honest_window_disclosure_is_dropped(monkeypatch):
    """ADR-104's behavioural-absence contract is part of the claim, not decoration."""
    from datetime import date

    monkeypatch.setattr(dv, "_json_api", lambda p: {"vitals": {"as_of_date": date.today().isoformat()}})
    v = dv.edge_public_data_is_fresh()
    assert v.status == FAIL and "window_disclosure" in v.summary


# ── UNVERIFIED paths: a check that could not run must never read as a pass ───────


@pytest.mark.parametrize(
    "playbook",
    [
        dv.control_production_approval_gate,
        dv.control_main_ruleset_active,
        dv.control_vulnerability_alerts_enabled,
        dv.control_codeql_alerts_triaged,
    ],
)
def test_github_auth_failure_is_unverified_not_pass(monkeypatch, playbook):
    """The #3112 shape: a token that cannot read the API must not yield a clean result."""
    monkeypatch.setattr(dv, "_gh", lambda ep, method="GET": (1, "gh: Resource not accessible by integration (HTTP 403)"))
    v = playbook()
    assert v.status == UNVERIFIED, f"{playbook.__name__} laundered an auth failure into {v.status}"


@pytest.mark.parametrize(
    "playbook",
    [
        dv.privacy_public_api_serves_no_owner_only_field,
        dv.prediction_calibration_is_reported_honestly,
        dv.edge_public_data_is_fresh,
    ],
)
def test_api_transport_failure_is_unverified_not_pass(monkeypatch, playbook):
    def boom(path):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(dv, "_json_api", boom)
    v = playbook()
    assert v.status == UNVERIFIED, f"{playbook.__name__} laundered a transport failure into {v.status}"


def test_codeql_empty_non_list_response_is_unverified(monkeypatch):
    """An API shape change must not be read as 'no alerts' — the #3112 fail-soft."""
    monkeypatch.setattr(dv, "_gh", lambda ep, method="GET": (0, json.dumps({"message": "moved"})))
    assert dv.control_codeql_alerts_triaged().status == UNVERIFIED


def test_owner_only_vocabulary_emptied_is_unverified_not_pass(monkeypatch):
    """If the registry declares nothing owner-only, the leak check observed nothing."""
    monkeypatch.setattr(dv, "_json_api", lambda p: {})
    import privacy.field_tiers as ft

    monkeypatch.setattr(ft, "fields_at_tier", lambda tier, source=None: frozenset())
    v = dv.privacy_public_api_serves_no_owner_only_field()
    assert v.status == UNVERIFIED and "not a pass" in v.summary


def test_an_unexpected_exception_becomes_unverified_not_a_swallowed_pass(monkeypatch):
    """The runner's own safety net: a raising playbook is UNVERIFIED, never skipped."""

    def explode():
        raise ValueError("unexpected")

    monkeypatch.setattr(dv, "PLAYBOOKS", [("boom", "control", "DIL-000", explode)])
    results = dv.run_playbooks(["control"])
    assert len(results) == 1
    assert results[0]["status"] == UNVERIFIED and "ValueError" in results[0]["summary"]


# ── exit-code contract ───────────────────────────────────────────────────────────


def _fixed(status):
    return lambda: dv.Verdict(status, "fixture")


def test_exit_code_1_on_fail(monkeypatch, capsys):
    monkeypatch.setattr(dv, "PLAYBOOKS", [("x", "control", "DIL-000", _fixed(FAIL))])
    assert dv.main([]) == 1
    capsys.readouterr()


def test_exit_code_0_when_all_pass(monkeypatch, capsys):
    monkeypatch.setattr(dv, "PLAYBOOKS", [("x", "control", "DIL-000", _fixed(PASS))])
    assert dv.main([]) == 0
    capsys.readouterr()


def test_unverified_passes_by_default_but_exits_2_under_strict(monkeypatch, capsys):
    """The evidence pack is generated under --strict, where an unobserved row is fatal."""
    monkeypatch.setattr(dv, "PLAYBOOKS", [("x", "control", "DIL-000", _fixed(UNVERIFIED))])
    assert dv.main([]) == 0
    assert dv.main(["--strict"]) == 2
    capsys.readouterr()


def test_fail_outranks_unverified_in_the_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(
        dv,
        "PLAYBOOKS",
        [("a", "control", "DIL-000", _fixed(UNVERIFIED)), ("b", "control", "DIL-001", _fixed(FAIL))],
    )
    assert dv.main(["--strict"]) == 1
    capsys.readouterr()


def test_json_bundle_is_deterministic(monkeypatch, tmp_path, capsys):
    """Two runs over unchanged state must diff clean, or the bundle cannot show movement."""
    monkeypatch.setattr(dv, "PLAYBOOKS", [("x", "control", "DIL-000", _fixed(PASS))])
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    dv.main(["--json", str(a)])
    dv.main(["--json", str(b)])
    capsys.readouterr()
    assert a.read_text() == b.read_text(), "the evidence bundle is not reproducible"
