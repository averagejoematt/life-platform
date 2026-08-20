"""tests/test_check_alarm_citations.py — regression guard for the #1959 /wrap
alarm-citation gate (scripts/check_alarm_citations.py).

Proves, with synthetic input, that:
  * an alarm in ALARM >72h with NO citation entry is flagged (the negative test the
    #1959 brief calls for — the gate must actually bite);
  * an alarm >72h WITH a citation entry is not flagged;
  * an alarm <=72h is never flagged regardless of citation state;
  * the render()/main() contract matches check_main_green.py's decode shape
    (uncited -> exit 1; --decoded -> exit 0 with an acknowledgement line);
  * AWS-unreachable degrades honestly (never crashes, never reports a false-clean
    board) — no live AWS/creds required anywhere in this file;
  * docs/alarm_citations.json is well-formed and its entries are non-empty;
  * the 72h threshold constant doesn't silently drift from remediation/agent.py's
    twin ALARM_AGE_ESCALATION_HOURS (#1204) — a plain source grep, no import (this
    script deliberately avoids importing remediation/agent.py's module-level boto3
    clients / drift_report dependency).
"""

import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_alarm_citations as cac  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_sync():
    """deploy/sync_doc_metadata.py by path — it is not importable by name, and this
    avoids putting deploy/ on sys.path for the whole suite."""
    path = os.path.join(REPO, "deploy", "sync_doc_metadata.py")
    spec = importlib.util.spec_from_file_location("_sync_doc_metadata", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _alarm(name, hours_old, now):
    return {"name": name, "updated": (now - timedelta(hours=hours_old)).isoformat()}


# ── uncited_long_reds — the negative test (#1959: prove the gate fires) ────────


def test_uncited_long_red_is_flagged():
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    alarms = [_alarm("mystery-alarm", 100, now)]  # >72h, no citation
    out = cac.uncited_long_reds(alarms, citations={}, now=now)
    assert out == [("mystery-alarm", 100.0)]


def test_cited_long_red_is_not_flagged():
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    alarms = [_alarm("known-alarm", 100, now)]
    citations = {"known-alarm": {"citation": "#1234", "note": "explained"}}
    out = cac.uncited_long_reds(alarms, citations, now=now)
    assert out == []


def test_short_red_never_flagged_even_uncited():
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    alarms = [_alarm("fresh-alarm", 10, now)]  # well under 72h
    out = cac.uncited_long_reds(alarms, citations={}, now=now)
    assert out == []


def test_exactly_at_threshold_not_flagged_strictly_greater_required():
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    alarms = [_alarm("boundary-alarm", 72, now)]
    out = cac.uncited_long_reds(alarms, citations={}, now=now)
    assert out == []


def test_just_over_threshold_flagged():
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    alarms = [_alarm("boundary-alarm", 72.01, now)]
    out = cac.uncited_long_reds(alarms, citations={}, now=now)
    assert len(out) == 1 and out[0][0] == "boundary-alarm"


def test_citation_with_blank_string_still_counts_as_uncited():
    """A registry entry with no actual citation text is not a real citation."""
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    alarms = [_alarm("half-entered", 100, now)]
    citations = {"half-entered": {"citation": "  ", "note": "placeholder"}}
    out = cac.uncited_long_reds(alarms, citations, now=now)
    assert out == [("half-entered", 100.0)]


def test_unparseable_timestamp_never_manufactures_a_citation_requirement():
    alarms = [{"name": "bad-timestamp", "updated": "not-a-date"}]
    out = cac.uncited_long_reds(alarms, citations={})
    assert out == []


def test_mixed_board_flags_only_the_uncited_long_red():
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    alarms = [
        _alarm("cited-old", 200, now),
        _alarm("uncited-old", 200, now),
        _alarm("uncited-young", 5, now),
    ]
    citations = {"cited-old": {"citation": "#1", "note": "x"}}
    out = cac.uncited_long_reds(alarms, citations, now=now)
    assert out == [("uncited-old", 200.0)]


# ── render() — exit-code + message contract (mirrors check_main_green.py) ──────


def test_render_uncited_is_gate_failure():
    code, message = cac.render([("some-alarm", 96.0)], unreachable_error=None)
    assert code == 1
    assert "some-alarm" in message
    assert "4.0d" in message or "96h" in message


def test_render_clean_board_is_ok():
    code, message = cac.render([], unreachable_error=None)
    assert code == 0
    assert "cites an incident row or issue" in message


def test_render_unreachable_degrades_honestly_not_a_false_clean():
    code, message = cac.render([], unreachable_error="NoCredentialsError")
    assert code == 0
    assert "UNVERIFIED" in message
    assert "unreachable" in message.lower()


# ── main()/CLI — --decoded contract, no live AWS/creds required ────────────────


def test_main_exits_nonzero_on_uncited_and_zero_with_decoded(monkeypatch, capsys):
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(cac, "fetch_alarms", lambda: ([_alarm("uncited-alarm", 100, now)], None))
    monkeypatch.setattr(cac, "load_citations", lambda: {})
    # Freeze uncited_long_reds' `now` via a wrapper so the synthetic alarm reads as old
    # regardless of wall-clock — reuse the pure function directly with the fixed now.
    monkeypatch.setattr(cac, "uncited_long_reds", lambda alarms, citations, now=None, threshold_hours=72: [("uncited-alarm", 100.0)])

    monkeypatch.setattr(sys, "argv", ["check_alarm_citations.py"])
    assert cac.main() == 1
    out = capsys.readouterr().out
    assert "uncited-alarm" in out

    monkeypatch.setattr(sys, "argv", ["check_alarm_citations.py", "--decoded"])
    assert cac.main() == 0
    out = capsys.readouterr().out
    assert "--decoded acknowledged" in out


def test_main_clean_board_exits_zero(monkeypatch):
    monkeypatch.setattr(cac, "fetch_alarms", lambda: ([], None))
    monkeypatch.setattr(cac, "load_citations", lambda: {})
    monkeypatch.setattr(sys, "argv", ["check_alarm_citations.py"])
    assert cac.main() == 0


def test_main_aws_unreachable_never_crashes_and_exits_zero(monkeypatch):
    def _boom():
        return [], "botocore.exceptions.NoCredentialsError: Unable to locate credentials"

    monkeypatch.setattr(cac, "fetch_alarms", _boom)
    monkeypatch.setattr(cac, "load_citations", lambda: {})
    monkeypatch.setattr(sys, "argv", ["check_alarm_citations.py"])
    assert cac.main() == 0


# ── fetch_alarms() — real function, but boto3 failure must degrade, not raise ──


def test_fetch_alarms_degrades_on_any_exception(monkeypatch):
    class _FakeBoto3Module:
        @staticmethod
        def client(*_a, **_k):
            raise RuntimeError("Unable to locate credentials")

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3Module())
    alarms, err = cac.fetch_alarms()
    assert alarms == []
    assert err is not None
    assert "credentials" in err.lower()


# ── load_citations() — missing/malformed file degrades to {} ───────────────────


def test_load_citations_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert cac.load_citations(missing) == {}


def test_load_citations_malformed_json_returns_empty(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert cac.load_citations(bad) == {}


def test_load_citations_non_dict_json_returns_empty(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    assert cac.load_citations(arr) == {}


# ── the real registry file — well-formed, non-empty citations ──────────────────


def test_real_registry_file_is_well_formed():
    data = cac.load_citations()
    assert data, "docs/alarm_citations.json loaded empty — check it exists and is valid JSON"
    for name, entry in data.items():
        if name == "_comment":
            continue
        assert isinstance(entry, dict), f"{name}: entry must be an object"
        assert str(entry.get("citation", "")).strip(), f"{name}: citation must be non-empty"
        assert re.search(
            r"#\d+|closed|incident", entry["citation"], re.I
        ), f"{name}: citation should reference an issue/incident: {entry['citation']!r}"


def test_real_registry_entries_all_name_a_real_alarm():
    """Every citation must name an alarm that actually exists in the CDK-declared
    inventory — so a typo, a rename, or an entry left behind after an alarm is
    deleted fails here instead of sitting in the registry looking like coverage.

    REPLACES a pin on three hardcoded names (2026-08-20). The old form asserted
    that `qa-paused-by-budget`, `qa-smoke-warnings` and `ingest-auth-unhealthy-24h`
    were always present, describing them as "the documented >72h reds" **as of its
    filing (#1959)**. All three have since recovered — qa-paused-by-budget OK since
    2026-08-03, ingest-auth-unhealthy-24h since 2026-08-19, qa-smoke-warnings the
    same week — and their issues (#1927, #1934, #2670) are closed. The registry's
    own header says an entry is removed "once the underlying issue closes AND the
    alarm has actually cleared live", so the pin had come to gate *against* the
    documented lifecycle: pruning correctly (#2917) made it red.

    A snapshot of which alarms happen to be red rots by construction. The invariant
    that does not is: an entry may only cite an alarm that exists. Live *coverage*
    — every >72h red having a citation — is enforced against real CloudWatch by
    `scripts/check_alarm_citations.py` at wrap time, which is where it belongs;
    the flag-the-uncited behaviour itself is pinned by the unit tests above.
    """
    names = _load_sync()._auto_discover_alarm_names()
    if not names:  # AST discovery unavailable — do not manufacture a false pass
        pytest.skip("alarm-name discovery returned nothing; cannot verify entries")
    data = cac.load_citations()
    entries = [n for n in data if n != "_comment"]
    assert entries, "docs/alarm_citations.json has no citation entries"
    unknown = sorted(n for n in entries if n not in names)
    assert not unknown, (
        f"citation entries name alarms not declared in cdk/stacks/*.py: {unknown} — "
        "either the alarm was renamed/deleted (drop the entry) or the name is a typo"
    )


# ── constant-drift guard (no import of remediation/agent.py) ───────────────────


def test_threshold_matches_remediation_agent_constant():
    agent_src = open(os.path.join(REPO, "remediation", "agent.py"), encoding="utf-8").read()
    m = re.search(r"^ALARM_AGE_ESCALATION_HOURS\s*=\s*(\d+)", agent_src, re.MULTILINE)
    assert m, "remediation/agent.py no longer defines ALARM_AGE_ESCALATION_HOURS — update the cross-reference"
    assert int(m.group(1)) == cac.ALARM_AGE_CITATION_HOURS, (
        "scripts/check_alarm_citations.py's ALARM_AGE_CITATION_HOURS has drifted from "
        "remediation/agent.py's ALARM_AGE_ESCALATION_HOURS (#1204) — keep the two 72h "
        "windows in sync or document why they diverge."
    )


def test_json_file_itself_parses_with_stdlib_json():
    path = os.path.join(REPO, "docs", "alarm_citations.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, dict)


# ── issueless_ancient_reds — the 14-day mandatory issue-or-fix tenure (#2378) ──


def test_ancient_red_with_prose_citation_is_red_flagged():
    """#2378 acceptance 3: past 14 days, a citation LINE without a filed-issue
    reference no longer clears the board — the exact qa-smoke-warnings shape
    (structurally red 21+ days behind a tidy prose citation)."""
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    alarms = [_alarm("old-alarm", 15 * 24, now)]
    citations = {"old-alarm": {"citation": "incident 2026-07-20 — measured, no code defect", "note": "..."}}
    out = cac.issueless_ancient_reds(alarms, citations, now=now)
    assert out == [("old-alarm", 15 * 24.0)]


def test_ancient_red_with_issue_citation_is_not_flagged():
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    alarms = [_alarm("old-alarm", 20 * 24, now)]
    citations = {"old-alarm": {"citation": "#2378", "note": "tracked"}}
    assert cac.issueless_ancient_reds(alarms, citations, now=now) == []


def test_under_14_days_prose_citation_still_suffices():
    """The 72h..14d band keeps the #1959 contract: any citation counts."""
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    alarms = [_alarm("newish-alarm", 10 * 24, now)]
    citations = {"newish-alarm": {"citation": "incident row 2026-08-01", "note": "..."}}
    assert cac.issueless_ancient_reds(alarms, citations, now=now) == []
    assert cac.uncited_long_reds(alarms, citations, now=now) == []


def test_ancient_uncited_alarm_is_flagged_by_both_gates():
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    alarms = [_alarm("forgotten-alarm", 30 * 24, now)]
    assert cac.uncited_long_reds(alarms, citations={}, now=now) == [("forgotten-alarm", 30 * 24.0)]
    assert cac.issueless_ancient_reds(alarms, citations={}, now=now) == [("forgotten-alarm", 30 * 24.0)]


def test_unparseable_timestamp_never_manufactures_a_tenure_flag():
    assert cac.issueless_ancient_reds([{"name": "x", "updated": "not-a-date"}], citations={}) == []


def test_render_ancient_is_gate_failure_with_mandate_language():
    code, message = cac.render([], unreachable_error=None, ancient=[("old-alarm", 15 * 24.0)])
    assert code == 1
    assert "MANDATORY issue-or-fix" in message
    assert "old-alarm" in message


def test_render_clean_board_mentions_both_contracts():
    code, message = cac.render([], unreachable_error=None, ancient=[])
    assert code == 0
    assert "filed issue" in message
