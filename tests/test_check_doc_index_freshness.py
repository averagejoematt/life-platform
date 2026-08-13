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


# ── #2619: exemption-by-omission is closed + the failure is legible ───────────
#
# THE DEFECT: gate 5 (above) can only see a doc that declares BOTH a
# `**Sources of truth:**` line and a `**Verified:**` stamp. Anything else was a silent
# `(note) skip …` — so the only way to be exempt from the gate was to be incomplete, and
# the least-maintained engine doc got the least scrutiny. Gate 6 turns that skip into a
# failure unless the doc is on the written ENGINE_DOC_EXEMPT allowlist.


def _write_engine_doc(tmp_path, monkeypatch, name="FAKE.md", verified="2026-07-10", sources_line=True):
    """A synthetic ROOT holding ONE engine doc under `name`, with its source on disk."""
    engines = tmp_path / "docs" / "engines"
    engines.mkdir(parents=True, exist_ok=True)
    (tmp_path / "lambdas").mkdir(exist_ok=True)
    (tmp_path / "lambdas" / "fake_engine.py").write_text("VERSION = 1\n", encoding="utf-8")
    text = _HEADER.format(verified=verified) if verified else "# Fake Engine\n\n> **Status:** canonical\n"
    if sources_line:
        text += _SOURCES.format(src="lambdas/fake_engine.py")
    (engines / name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(cdi, "ROOT", tmp_path)
    monkeypatch.setattr(cdi, "ENGINES", engines)


def test_engine_doc_without_a_sources_line_fails_rather_than_skips(tmp_path, monkeypatch):
    """MUTATION PROOF: strip the sources line and the gate must RED, not go quiet."""
    _write_engine_doc(tmp_path, monkeypatch, sources_line=False)
    monkeypatch.setattr(cdi, "ENGINE_DOC_EXEMPT", {})
    problems, exemptions = cdi.check_engine_doc_coverage()
    assert exemptions == []
    assert len(problems) == 1, problems
    assert "docs/engines/FAKE.md" in problems[0] and "Sources of truth" in problems[0]


def test_engine_doc_without_a_verified_stamp_fails_rather_than_skips(tmp_path, monkeypatch):
    """MUTATION PROOF: strip the `Verified:` stamp and the gate must RED, not go quiet."""
    _write_engine_doc(tmp_path, monkeypatch, verified=None)
    monkeypatch.setattr(cdi, "ENGINE_DOC_EXEMPT", {})
    problems, _ = cdi.check_engine_doc_coverage()
    assert len(problems) == 1, problems
    assert "Verified:" in problems[0]


def test_engine_doc_whose_sources_resolve_to_nothing_fails(tmp_path, monkeypatch):
    """A sources line full of typos is as ungated as no sources line at all."""
    engines = tmp_path / "docs" / "engines"
    engines.mkdir(parents=True)
    (engines / "FAKE.md").write_text(
        _HEADER.format(verified="2026-07-10") + "> **Sources of truth:** `lambdas/typo_not_a_file.py`\n", encoding="utf-8"
    )
    monkeypatch.setattr(cdi, "ROOT", tmp_path)
    monkeypatch.setattr(cdi, "ENGINES", engines)
    monkeypatch.setattr(cdi, "ENGINE_DOC_EXEMPT", {})
    problems, _ = cdi.check_engine_doc_coverage()
    assert len(problems) == 1 and "resolves to a repo file" in problems[0], problems


def test_allowlisted_engine_doc_is_exempt_and_reports_its_reason(tmp_path, monkeypatch):
    """An exemption is a written decision — never a silent skip. The reason comes back."""
    _write_engine_doc(tmp_path, monkeypatch, name="FROZEN.md", verified=None, sources_line=False)
    monkeypatch.setattr(cdi, "ENGINE_DOC_EXEMPT", {"FROZEN.md": "frozen audit record, by decision"})
    problems, exemptions = cdi.check_engine_doc_coverage()
    assert problems == []
    assert exemptions == [("docs/engines/FROZEN.md", "frozen audit record, by decision")]


def test_coverage_failure_exits_nonzero_through_main(monkeypatch):
    """Gate 6 is BLOCKING, not advisory — and unlike gate 5 it has no --advisory escape."""
    monkeypatch.setattr(cdi, "check_engine_source_freshness", lambda git_date_fn=None: ([], []))
    monkeypatch.setattr(cdi, "check_engine_doc_coverage", lambda: (["engine doc is not gated (#2619): docs/engines/X.md is missing …"], []))
    for argv in (["check_doc_index.py"], ["check_doc_index.py", "--advisory"]):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exc:
            cdi.main()
        assert exc.value.code == 1, f"{argv} must exit 1 on an ungated engine doc"


def test_every_real_engine_doc_is_gated_or_explicitly_exempt():
    """The live corpus: no doc under docs/engines/ escapes by being incomplete."""
    problems, exemptions = cdi.check_engine_doc_coverage()
    assert problems == [], "ungated engine doc(s) on repo HEAD:\n" + "\n".join(problems)
    for name, reason in cdi.ENGINE_DOC_EXEMPT.items():
        assert (cdi.ENGINES / name).is_file(), f"ENGINE_DOC_EXEMPT names a file that does not exist: {name}"
        assert len(reason.split()) >= 10, f"ENGINE_DOC_EXEMPT[{name}] needs a real written reason, got: {reason!r}"


def test_drift_failure_prints_how_to_clear_it(monkeypatch, capsys):
    """#2619 (d): a gate that reds without saying how to clear it costs a session each
    time. The strict failure must carry the remediation, not just the drift statement."""
    monkeypatch.setattr(cdi, "check_engine_source_freshness", lambda git_date_fn=None: _FAKE_DRIFT)
    monkeypatch.setattr(sys, "argv", ["check_doc_index.py"])
    with pytest.raises(SystemExit):
        cdi.main()
    out = capsys.readouterr().out
    assert "docs/engines/FAKE.md" in out
    assert "is a CLAIM, not a date field" in out, f"missing the remediation block:\n{out}"
    assert "NEVER bump the date alone" in out


def test_coverage_failure_prints_how_to_clear_it(monkeypatch, capsys):
    monkeypatch.setattr(cdi, "check_engine_source_freshness", lambda git_date_fn=None: ([], []))
    monkeypatch.setattr(
        cdi, "check_engine_doc_coverage", lambda: (["engine doc is not gated (#2619): docs/engines/X.md is missing a stamp"], [])
    )
    monkeypatch.setattr(sys, "argv", ["check_doc_index.py"])
    with pytest.raises(SystemExit):
        cdi.main()
    out = capsys.readouterr().out
    assert "ENGINE_DOC_EXEMPT" in out and "no longer an exemption" in out, out


def test_headroom_is_enumerated_from_source_not_hand_listed(tmp_path, monkeypatch):
    """headroom = Verified − newest source commit. ≤0 means the next commit reds CI."""
    _write_engine_doc(tmp_path, monkeypatch, verified="2026-08-09")
    monkeypatch.setattr(cdi, "ENGINE_DOC_EXEMPT", {})
    zero = cdi.engine_doc_headroom(git_date_fn=lambda p: date(2026, 8, 9))
    assert zero == [(0, "docs/engines/FAKE.md", "lambdas/fake_engine.py", "2026-08-09", "2026-08-09")]
    roomy = cdi.engine_doc_headroom(git_date_fn=lambda p: date(2026, 8, 2))
    assert roomy[0][0] == 7


def test_headroom_skips_exempt_and_ungated_docs(tmp_path, monkeypatch):
    """Headroom is a claim about GATED docs only — an exempt doc has no stamp to defend."""
    _write_engine_doc(tmp_path, monkeypatch, name="FROZEN.md", verified=None, sources_line=False)
    monkeypatch.setattr(cdi, "ENGINE_DOC_EXEMPT", {"FROZEN.md": "frozen"})
    assert cdi.engine_doc_headroom(git_date_fn=lambda p: date(2026, 8, 9)) == []
