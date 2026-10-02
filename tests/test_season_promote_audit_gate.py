"""tests/test_season_promote_audit_gate.py — #4549: nothing publishes without a fresh, clean raw-data audit."""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import season_promote as sp  # noqa: E402


def _stage(tmp_path, audit=None, audit_first=False):
    def files():
        for w in (0, 1):
            (tmp_path / f"wk{w}_chronicle.md").write_text('"T"\n\nbody')
            (tmp_path / f"wk{w}_episode.json").write_text("{}")

    def write_audit():
        (tmp_path / "audit.json").write_text(json.dumps(audit))

    if audit is not None and audit_first:
        write_audit()
        time.sleep(0.02)
        files()
    else:
        files()
        if audit is not None:
            time.sleep(0.02)
            write_audit()
    return str(tmp_path)


def test_no_audit_refuses(tmp_path):
    assert sp.audit_gate(_stage(tmp_path), [0, 1])


def test_blocking_items_refuse(tmp_path):
    assert any("blocking" in r for r in sp.audit_gate(_stage(tmp_path, {"blocking": [{"claim": "x"}]}), [0, 1]))


def test_a_stale_audit_refuses(tmp_path):
    assert any("older" in r for r in sp.audit_gate(_stage(tmp_path, {"blocking": []}, audit_first=True), [0, 1]))


def test_a_fresh_clean_audit_passes(tmp_path):
    assert sp.audit_gate(_stage(tmp_path, {"blocking": []}), [0, 1]) == []
