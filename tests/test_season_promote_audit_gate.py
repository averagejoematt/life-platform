"""tests/test_season_promote_audit_gate.py — #4549: nothing publishes without a clean raw-data audit of THIS staging.

The gate fails closed. Each refusal class has its own fixture: no audit, an unreadable or malformed one, a stale one (a
staged file changed after the audit — by content hash, so a touched timestamp cannot pass an older audit), an audit that
does not cover a promoted week, one below the agent's own floors, and one with blocking items. The end-to-end tests drive
``main(["--apply"])`` with every AWS step replaced by a recorder: a refused gate exits 5 having called none of them, and
the mutation control (gate forced open) shows the same recorder DOES see the writes — so the refusal test cannot pass
vacuously.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import season_promote as sp  # noqa: E402

WEEKS = [0, 1]


def _stage(tmp_path, weeks=WEEKS):
    for w in weeks:
        (tmp_path / f"wk{w}_chronicle.md").write_text(f'"T{w}"\n\nbody {w}')
        (tmp_path / f"wk{w}_episode.json").write_text(json.dumps({"turns": [], "w": w}))
        (tmp_path / f"wk{w}_ledger.json").write_text(json.dumps({"date": f"2026-09-0{w + 1}"}))
        (tmp_path / f"wk{w}_dossier.json").write_text(json.dumps({"week": w}))
    return str(tmp_path)


def _clean_audit(staging, weeks=WEEKS, **over):
    audit = {
        "auditor": "story-auditor",
        "date": "2026-10-09T00:00:00Z",
        "items_checked": sp.ITEMS_PER_WEEK * len(weeks),
        "raw_verified": sp.RAW_VERIFIED_PER_WEEK * len(weeks),
        "blocking": [],
        "advisory": [],
        "verdict": "publishable",
        "staged_sha256": sp.staged_hashes(staging, weeks),
    }
    audit.update(over)
    return audit


def _write(staging, audit):
    with open(os.path.join(staging, "audit.json"), "w", encoding="utf-8") as fh:
        fh.write(audit if isinstance(audit, str) else json.dumps(audit))


# ── the pass case ───────────────────────────────────────────────────────────


def test_a_fresh_clean_audit_passes(tmp_path):
    st = _stage(tmp_path)
    _write(st, _clean_audit(st))
    assert sp.audit_gate(st, WEEKS) == []


def test_an_audit_of_the_whole_season_passes_a_one_week_promote(tmp_path):
    st = _stage(tmp_path)
    _write(st, _clean_audit(st))
    assert sp.audit_gate(st, [1]) == []


# ── missing / unreadable / malformed ────────────────────────────────────────


def test_no_audit_refuses(tmp_path):
    assert any("no audit.json" in r for r in sp.audit_gate(_stage(tmp_path), WEEKS))


def test_an_unreadable_or_non_object_audit_refuses(tmp_path):
    st = _stage(tmp_path)
    passed = []
    for raw in ["", "{not json", "[]", "null", '"publishable"']:
        _write(st, raw)
        reasons = sp.audit_gate(st, WEEKS)
        if not any("unreadable" in r or "malformed" in r for r in reasons):
            passed.append(raw)
    assert passed == [], f"these audit.json bodies were not refused as unreadable/malformed: {passed}"


def test_a_blocking_field_that_is_not_a_list_refuses(tmp_path):
    """Absent is not zero: an audit that never wrote its blocking list did not say nothing blocks."""
    st = _stage(tmp_path)
    passed = []
    for blocking in ["__absent__", None, 0, "", "none", {}]:
        audit = _clean_audit(st)
        if blocking == "__absent__":
            del audit["blocking"]
        else:
            audit["blocking"] = blocking
        _write(st, audit)
        if not any("`blocking` must be a list" in r for r in sp.audit_gate(st, WEEKS)):
            passed.append(blocking)
    assert passed == [], f"these `blocking` values were not refused: {passed}"


def test_a_verdict_other_than_publishable_refuses(tmp_path):
    st = _stage(tmp_path)
    _write(st, _clean_audit(st, verdict="fix-then-publish"))
    assert any("verdict" in r for r in sp.audit_gate(st, WEEKS))


def test_an_audit_below_the_agents_own_floors_refuses(tmp_path):
    st = _stage(tmp_path)
    passed = []
    cases = [("items_checked", 1), ("items_checked", None), ("items_checked", True), ("raw_verified", 0), ("raw_verified", "15")]
    for field, value in cases:
        _write(st, _clean_audit(st, **{field: value}))
        if not any(field in r for r in sp.audit_gate(st, WEEKS)):
            passed.append((field, value))
    assert passed == [], f"these under-floor audits were not refused: {passed}"


# ── blocking ────────────────────────────────────────────────────────────────


def test_blocking_items_refuse(tmp_path):
    st = _stage(tmp_path)
    _write(st, _clean_audit(st, blocking=[{"week": 1, "claim": "x", "problem": "wrong weekday"}]))
    assert any("1 blocking item" in r for r in sp.audit_gate(st, WEEKS))


# ── stale: the audit is tied to the exact staged content ────────────────────


def test_an_audit_without_content_hashes_refuses(tmp_path):
    st = _stage(tmp_path)
    audit = _clean_audit(st)
    del audit["staged_sha256"]
    _write(st, audit)
    assert any("staged_sha256" in r for r in sp.audit_gate(st, WEEKS))


def test_a_staged_file_changed_after_the_audit_refuses(tmp_path):
    """The re-stage / --repair / hand-edit case, for every file that publishes. The audit file is written LAST (newest
    mtime), so a timestamp rule would pass this; only the content hash catches it."""
    passed = []
    for i, name in enumerate(f"wk1_{k}" for k in sp.AUDITED_FILES):
        (tmp_path / str(i)).mkdir()
        st = _stage(tmp_path / str(i))
        audit = _clean_audit(st)
        with open(os.path.join(st, name), "a", encoding="utf-8") as fh:
            fh.write(" ")
        _write(st, audit)
        if not any(name in r and "changed after the audit" in r for r in sp.audit_gate(st, WEEKS)):
            passed.append(name)
    assert passed == [], f"an edit to these files after the audit was not refused: {passed}"


def test_an_audit_that_did_not_cover_a_promoted_week_refuses(tmp_path):
    st = _stage(tmp_path, weeks=[0, 1, 2])
    _write(st, _clean_audit(st, weeks=WEEKS))  # audited weeks 0-1, promoting 0-2
    reasons = sp.audit_gate(st, [0, 1, 2])
    assert any("does not cover wk2_chronicle.md" in r for r in reasons), reasons


def test_a_missing_staged_file_refuses(tmp_path):
    st = _stage(tmp_path)
    _write(st, _clean_audit(st))
    os.remove(os.path.join(st, "wk0_ledger.json"))
    assert any("wk0_ledger.json is missing" in r for r in sp.audit_gate(st, WEEKS))


# ── end to end: --apply refuses before any write; the mutation control ──────


@pytest.fixture
def recorder(monkeypatch):
    calls = []
    monkeypatch.setattr(sp, "plan", lambda staging, weeks: {"staging_findings": [], "chronicle": []})
    for step in ("backup", "apply_chronicle", "apply_ledger", "apply_panel"):
        monkeypatch.setattr(sp, step, lambda *a, _s=step, **k: calls.append(_s))
    for step in ("apply_pages", "apply_effects", "apply_recap"):
        monkeypatch.setattr(sp, step, lambda *a, _s=step, **k: calls.append(_s))
    return calls


def test_apply_with_a_blocking_audit_exits_5_and_writes_nothing(tmp_path, recorder, capsys):
    st = _stage(tmp_path)
    _write(st, _clean_audit(st, blocking=[{"claim": "x"}]))
    assert sp.main(["--staging", st, "--weeks", "0-1", "--apply"]) == 5
    assert recorder == []
    assert "REFUSING: the audit gate is not satisfied" in capsys.readouterr().out


def test_apply_with_no_audit_exits_5_and_writes_nothing(tmp_path, recorder):
    st = _stage(tmp_path)
    assert sp.main(["--staging", st, "--weeks", "0-1", "--apply"]) == 5
    assert recorder == []


def test_apply_with_a_clean_current_audit_runs_every_step(tmp_path, recorder):
    st = _stage(tmp_path)
    _write(st, _clean_audit(st))
    assert sp.main(["--staging", st, "--weeks", "0-1", "--apply"]) == 0
    assert recorder == ["backup", "apply_chronicle", "apply_ledger", "apply_pages", "apply_effects", "apply_panel", "apply_recap"]


def test_MUTATION_CONTROL_with_the_gate_removed_a_blocking_audit_would_publish(tmp_path, recorder, monkeypatch):
    """Remove the check (gate forced open) and the same blocking audit reaches every write step — so the recorder can
    see a publish, and the refusal tests above are not passing because nothing was ever going to be called."""
    monkeypatch.setattr(sp, "audit_gate", lambda staging, weeks: [])
    st = _stage(tmp_path)
    _write(st, _clean_audit(st, blocking=[{"claim": "x"}]))
    assert sp.main(["--staging", st, "--weeks", "0-1", "--apply"]) == 0
    assert "backup" in recorder and "apply_chronicle" in recorder


def test_dry_run_reports_the_refusal_and_writes_nothing(tmp_path, recorder, capsys):
    st = _stage(tmp_path)
    assert sp.main(["--staging", st, "--weeks", "0-1"]) == 0
    assert recorder == []
    assert "AUDIT GATE: no audit.json" in capsys.readouterr().out


def test_audit_hashes_prints_the_map_the_gate_checks(tmp_path, capsys):
    st = _stage(tmp_path)
    assert sp.main(["--staging", st, "--weeks", "0-1", "--audit-hashes"]) == 0
    assert json.loads(capsys.readouterr().out) == sp.staged_hashes(st, WEEKS)
