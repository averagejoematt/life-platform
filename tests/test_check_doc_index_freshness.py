"""tests/test_check_doc_index_freshness.py — the source-newer-than-verify gate (#973).

check_doc_index.py's calendar freshness (90d advisory / 180d blocking) had zero
linkage to whether a doc's declared "Sources of truth" files changed after its
Verified date — docs/engines/CHARACTER.md re-verified today would stay "fresh"
for months even if character_engine.py were rewritten tomorrow. Gate 5 compares
git last-commit dates of the declared sources against the Verified date:
BLOCKING by default since #1965 (local == CI), advisory only under --advisory,
which must print a loud "would RED CI under --strict" banner.

Unit tests drive check_engine_source_freshness() against synthetic engine docs
in tmp_path with an injected git-date function — no live-git assumptions beyond
the repo itself. One integration test runs the real script flagless (the strict
default — the exact command every local path runs) against the repo to confirm
the docs-ci wiring stays green.
"""

import os
import subprocess
import sys
from datetime import date

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import check_doc_index as cdi  # noqa: E402

_HEADER = "# Fake Engine\n\n> **Status:** canonical · **Owner:** Matthew · **Verified:** {verified}\n"
_SOURCES = "> **Sources of truth:** `{src}` (v1.0), plus `_some_symbol` and `s3://bucket/key.json`\n"


def _engine_doc(tmp_path, monkeypatch, verified="2026-07-10", sources_line=True, make_source=True):
    """A synthetic ROOT with one engine doc + (optionally) its declared source file."""
    engines = tmp_path / "docs" / "engines"
    engines.mkdir(parents=True)
    src_rel = "lambdas/fake_engine.py"
    if make_source:
        (tmp_path / "lambdas").mkdir()
        (tmp_path / "lambdas" / "fake_engine.py").write_text("VERSION = 1\n", encoding="utf-8")
    text = _HEADER.format(verified=verified)
    if sources_line:
        text += _SOURCES.format(src=src_rel)
    (engines / "FAKE.md").write_text(text, encoding="utf-8")
    monkeypatch.setattr(cdi, "ROOT", tmp_path)
    monkeypatch.setattr(cdi, "ENGINES", engines)
    return src_rel


def test_source_committed_after_verify_is_flagged(tmp_path, monkeypatch):
    src_rel = _engine_doc(tmp_path, monkeypatch, verified="2026-07-10")
    flagged, notes = cdi.check_engine_source_freshness(git_date_fn=lambda p: date(2026, 7, 12))
    assert flagged == [("docs/engines/FAKE.md", src_rel, "2026-07-12", "2026-07-10")]


def test_source_committed_on_or_before_verify_is_clean(tmp_path, monkeypatch):
    _engine_doc(tmp_path, monkeypatch, verified="2026-07-10")
    for committed in (date(2026, 7, 10), date(2026, 7, 1)):
        flagged, _ = cdi.check_engine_source_freshness(git_date_fn=lambda p, c=committed: c)
        assert flagged == []


def test_missing_sources_line_is_a_note_not_a_crash(tmp_path, monkeypatch):
    _engine_doc(tmp_path, monkeypatch, sources_line=False)
    flagged, notes = cdi.check_engine_source_freshness(git_date_fn=lambda p: date(2026, 7, 12))
    assert flagged == []
    assert any("no '**Sources of truth:**' line" in n for n in notes)


def test_missing_verified_date_is_a_note_not_a_crash(tmp_path, monkeypatch):
    engines = tmp_path / "docs" / "engines"
    engines.mkdir(parents=True)
    (tmp_path / "lambdas").mkdir()
    (tmp_path / "lambdas" / "fake_engine.py").write_text("VERSION = 1\n", encoding="utf-8")
    (engines / "FAKE.md").write_text(
        "# Fake\n\n> **Status:** canonical\n" + _SOURCES.format(src="lambdas/fake_engine.py"), encoding="utf-8"
    )
    monkeypatch.setattr(cdi, "ROOT", tmp_path)
    monkeypatch.setattr(cdi, "ENGINES", engines)
    flagged, notes = cdi.check_engine_source_freshness(git_date_fn=lambda p: date(2026, 7, 12))
    assert flagged == []
    assert any("no '**Verified:**" in n for n in notes)


def test_non_path_backtick_tokens_are_ignored(tmp_path, monkeypatch):
    """Symbol names and s3:// targets on the sources line must not be treated as files."""
    src_rel = _engine_doc(tmp_path, monkeypatch)
    seen = []

    def git_date(p):
        seen.append(p)
        return date(2026, 7, 12)

    cdi.check_engine_source_freshness(git_date_fn=git_date)
    assert seen == [src_rel], f"only the real repo path should be date-checked, got {seen}"


def test_source_that_does_not_exist_on_disk_is_a_note(tmp_path, monkeypatch):
    """A sources line whose only path token doesn't exist → note, never a crash."""
    _engine_doc(tmp_path, monkeypatch, make_source=False)
    flagged, notes = cdi.check_engine_source_freshness(git_date_fn=lambda p: date(2026, 7, 12))
    assert flagged == []
    assert any("no source token resolves to a repo file" in n for n in notes)


def test_unavailable_git_date_is_a_note(tmp_path, monkeypatch):
    _engine_doc(tmp_path, monkeypatch)
    flagged, notes = cdi.check_engine_source_freshness(git_date_fn=lambda p: None)
    assert flagged == []
    assert any("git last-commit date unavailable" in n for n in notes)


_FAKE_DRIFT = ([("docs/engines/FAKE.md", "lambdas/fake_engine.py", "2026-07-12", "2026-07-10")], [])


def test_default_mode_is_strict_and_promotes_drift_to_failure(monkeypatch):
    """#1965: the bare, flagless invocation — what wrap.md and CONVENTIONS §8 run —
    fails on drift exactly like Docs CI's --strict run. Local == CI, no memory
    reflex required. --strict stays accepted as an explicit synonym."""
    monkeypatch.setattr(cdi, "check_engine_source_freshness", lambda git_date_fn=None: _FAKE_DRIFT)

    for argv in (["check_doc_index.py"], ["check_doc_index.py", "--strict"]):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exc:
            cdi.main()
        assert exc.value.code == 1, f"{argv} must exit 1 on engine-doc drift"


def test_advisory_optout_reports_instead_of_failing(monkeypatch, capsys):
    """--advisory demotes the same drift to a report — but the banner must name the
    CI consequence loudly ("N ... would RED CI under --strict"), so an advisory
    green can never be mistaken for a CI green (#1965 regression guard).
    Relies on the real repo's other gates being green, which
    test_default_mode_is_green_on_repo_head asserts."""
    monkeypatch.setattr(cdi, "check_engine_source_freshness", lambda git_date_fn=None: _FAKE_DRIFT)

    monkeypatch.setattr(sys, "argv", ["check_doc_index.py", "--advisory"])
    cdi.main()  # must not raise
    out = capsys.readouterr().out
    assert "1 advisory item(s) would RED CI under --strict" in out, f"missing the would-RED-CI banner:\n{out}"
    assert "docs/engines/FAKE.md" in out


def test_default_mode_is_green_on_repo_head():
    """Integration: the real script, flagless (the strict default — the same gate
    Docs CI runs with --strict), must be green on repo HEAD. This is the parity
    proof: if this passes locally on a full clone, Docs CI's run passes too."""
    result = subprocess.run(
        [sys.executable, os.path.join(_REPO, "scripts", "check_doc_index.py")],
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"check_doc_index.py failed on repo HEAD:\n{result.stdout}\n{result.stderr}"


def test_real_engine_docs_metadata_is_parseable():
    """Every real docs/engines/*.md either parses (sources + Verified) or is skipped
    with a note — the gate must classify each one, never crash on the live corpus."""
    flagged, notes = cdi.check_engine_source_freshness(git_date_fn=lambda p: None)
    # git_date_fn=None-returning means nothing can be flagged; parse errors would raise.
    assert flagged == []
    parsed_docs = {p.name for p in cdi.ENGINES.glob("*.md")}
    assert parsed_docs, "expected real engine docs to exist"
