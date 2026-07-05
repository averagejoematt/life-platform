"""tests/test_sync_doc_metadata_check.py — the doc-drift gate (#389) actually gates.

sync_doc_metadata.py used to only ever rewrite docs on --apply; nothing ran the
diff assertively, so a fixed literal (e.g. CLAUDE.md's "~85 Lambdas") re-drifted
the moment the underlying fact changed again and nobody happened to rerun
--apply. --check reuses the exact same rule-matching machinery (RULES +
process_doc) but exits non-zero instead of silently reporting, so CI catches
drift instead of a diligent human.

Two isolated unit tests exercise the core mechanism (process_doc / main()
exit-code branching) against a synthetic doc in tmp_path — never the real repo
files, so these can't corrupt anything a concurrent session is editing. One
integration test runs the real script against the real repo HEAD to confirm
the gate is actually clean (the state this PR is required to leave main in).
"""

import os
import subprocess
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import sync_doc_metadata as sync  # noqa: E402


def _isolate(monkeypatch, tmp_path, doc_text, widget_count):
    """Point sync at a synthetic single-doc/single-rule world in tmp_path.

    Keeps the test from touching real repo docs or lambdas/web/site_api_common.py
    (both of which _sync_platform_stats / the real RULES would otherwise reach for).
    """
    doc = tmp_path / "FAKE_DOC.md"
    doc.write_text(doc_text, encoding="utf-8")
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "RULES", [("FAKE_DOC.md", r"\d+ Widgets", "{widget_count} Widgets")])
    monkeypatch.setattr(sync, "PLATFORM_FACTS", {**sync.PLATFORM_FACTS, "widget_count": widget_count})
    monkeypatch.setattr(sync, "_apply_auto_discovered", lambda facts: facts)  # no real AST/CDK discovery
    monkeypatch.setattr(sync, "_sync_platform_stats", lambda facts, dry_run: [])  # no real site_api_common.py
    return doc


def test_check_exits_nonzero_on_drift(tmp_path, monkeypatch):
    """A deliberately-wrong literal (doc says 99, truth is 42) fails --check."""
    doc = _isolate(monkeypatch, tmp_path, "Header: v1 (99 Widgets)\n", widget_count=42)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == 1
    assert doc.read_text(encoding="utf-8") == "Header: v1 (99 Widgets)\n", "--check must never write"


def test_check_exits_zero_when_current(tmp_path, monkeypatch):
    """The doc already matches the discovered value -> --check passes clean."""
    doc = _isolate(monkeypatch, tmp_path, "Header: v1 (42 Widgets)\n", widget_count=42)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == 0
    assert doc.read_text(encoding="utf-8") == "Header: v1 (42 Widgets)\n"


def test_check_and_apply_are_mutually_exclusive(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path, "Header: v1 (42 Widgets)\n", widget_count=42)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check", "--apply"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == 2


def test_check_is_clean_on_repo_head():
    """Integration smoke test: the real gate, against the real repo, must pass.

    This is the state #389 requires main to be in before --check ships as a CI
    gate — if this test ever reds, a doc literal has drifted from the value
    sync_doc_metadata.py auto-discovers and `--apply` needs to be rerun.
    """
    result = subprocess.run(
        [sys.executable, os.path.join(_REPO, "deploy", "sync_doc_metadata.py"), "--check"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        "sync_doc_metadata.py --check found drift on repo HEAD — run "
        f"`python3 deploy/sync_doc_metadata.py --apply` and commit the fix.\n{result.stdout}\n{result.stderr}"
    )
