"""#3646 — the system-model gate gives a stale merge commit the same `pending-reconcile` verdict the
literal gate gives: on a push to main, `generate_platform_model.py --check` warns and exits 0 when
its artifacts are stale (the reconcile job regenerates them next); everywhere else it still exits 1.

Mutation control: delete the `if _reconcile_bot_follows_this_run():` branch → the push-to-main
case below exits 1 and `test_a_stale_model_on_a_push_to_main_is_pending_reconcile_not_red` reds."""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

REPO = os.path.join(os.path.dirname(__file__), "..")


def _gpm():
    spec = importlib.util.spec_from_file_location("gpm_3646", os.path.join(REPO, "scripts", "generate_platform_model.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gpm_3646"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def stale_model(monkeypatch, tmp_path):
    """Point the generator at EMPTY artifact paths so `--check` sees drift without rebuilding the world."""
    gpm = _gpm()
    monkeypatch.setattr(gpm, "ROOT", tmp_path)  # the DRIFT line prints paths relative to ROOT
    monkeypatch.setattr(gpm, "MODEL_PATH", tmp_path / "platform_model.json")
    monkeypatch.setattr(gpm, "DOC_PATH", tmp_path / "DEPENDENCY_GRAPH.md")
    monkeypatch.setattr(gpm, "build_model", lambda: {"meta": {"counts": {}}}, raising=False)
    monkeypatch.setattr(gpm, "serialize", lambda m: "MODEL\n", raising=False)
    monkeypatch.setattr(gpm, "render_doc", lambda m: "DOC\n", raising=False)
    monkeypatch.setattr(sys, "argv", ["generate_platform_model.py", "--check"])
    return gpm


def test_a_stale_model_on_a_push_to_main_is_pending_reconcile_not_red(stale_model, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    assert stale_model.main() == 0
    out = capsys.readouterr().out
    assert "DRIFT:" in out and "VERDICT: pending-reconcile" in out and "::warning title=pending-reconcile::" in out


@pytest.mark.parametrize(
    "event, ref",
    [("pull_request", "refs/pull/1/merge"), ("push", "refs/heads/feature"), ("workflow_dispatch", "refs/heads/main"), (None, None)],
)
def test_everywhere_else_a_stale_model_still_fails(stale_model, monkeypatch, capsys, event, ref):
    for k, v in (("GITHUB_EVENT_NAME", event), ("GITHUB_REF", ref)):
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    assert stale_model.main() == 1
    assert "pending-reconcile" not in capsys.readouterr().out


def test_a_current_model_is_a_plain_pass_on_main_too(stale_model, monkeypatch, capsys):
    stale_model.MODEL_PATH.write_text("MODEL\n", encoding="utf-8")
    stale_model.DOC_PATH.write_text("DOC\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    assert stale_model.main() == 0
    assert "pending-reconcile" not in capsys.readouterr().out


def test_the_verdict_is_the_literal_gates_own_derivation():
    """One predicate, imported — the two gates cannot disagree about when a bot follows."""
    sys.path.insert(0, os.path.join(REPO, "deploy"))
    import doc_drift_verdict as ddv  # noqa: E402

    gpm = _gpm()
    for env in (
        {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"},
        {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/pull/9/merge"},
    ):
        for k, v in env.items():
            os.environ[k] = v
        try:
            assert gpm._reconcile_bot_follows_this_run() == ddv.reconcile_bot_follows_this_run()
        finally:
            for k in env:
                os.environ.pop(k, None)
