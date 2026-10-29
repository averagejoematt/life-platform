"""#5473 box 4: the SessionStart pre-flight prints the open Dependabot alert count by severity, and the main CI/CD
line reads the ci-cd.yml workflow's own runs (the repo-wide list is all Deploy dead-man runs on main)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mod():
    sys.path.insert(0, str(ROOT / "scripts" / "hooks"))
    spec = importlib.util.spec_from_file_location("_preflight_5473", ROOT / "scripts" / "hooks" / "session_preflight.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_counts_by_severity_and_says_triage():
    # the 2026-10-28 shape: 41 Pillow alerts (mixed severities) + 1 certifi
    line = _mod().dependabot_line(["high"] * 20 + ["medium"] * 21 + ["low"])
    assert line.startswith("42 open (20 high, 21 medium, 1 low)") and "triage" in line


def test_zero_is_a_clean_line_and_unknown_severity_is_counted():
    m = _mod()
    assert m.dependabot_line([]) == "0 open"
    assert "1 other" in m.dependabot_line(["critical", "unknown"])


def test_a_failed_query_is_unverified_never_zero(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "gh", lambda *a, **k: (1, ""))
    assert m._dependabot().startswith("UNVERIFIED")


def test_main_line_queries_the_ci_cd_workflow_not_the_repo_run_list(monkeypatch):
    m = _mod()
    calls = []

    def fake_gh(*args, **k):
        calls.append(args)
        return 0, "success 4dfd03633"

    monkeypatch.setattr(m, "gh", fake_gh)
    monkeypatch.setattr(m, "git", lambda *a, **k: (0, "main"))
    assert m._main_green() == "branch=main  main CI/CD=success 4dfd03633"
    assert any("workflows/ci-cd.yml/runs" in a for a in calls[0])
