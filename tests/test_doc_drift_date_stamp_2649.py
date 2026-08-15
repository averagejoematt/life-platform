"""#2649 — the literal-drift gate must fail on substance, not on the calendar.

`sync_doc_metadata.py` sets `facts["date"]` to *today's* UTC date on every run, so
under `--check` every doc's "Last updated:" stamp went stale at 00:00Z and stayed
stale until the next merge re-stamped it. Docs CI was 40/40 red.

The expensive part was not the red itself — `main` is not branch-protected, so
nothing was blocked. It is that a date-only diff and a genuine drift were reported
**identically**, with no severity split. A real drift (a wrong Lambda count, a wrong
tool count) was invisible inside daily noise that everyone had learned to ignore.

The contract, in four cases — the last two are the ones that matter:

  A  stale date only            -> PASS   (was FAIL: the bug)
  B  substantive drift only     -> FAIL   (must not be weakened by the fix)
  C  stale date AND drift       -> FAIL   (masking must not HIDE real drift)
  D  clean tree                 -> PASS

Case C is why the masking is per-change rather than per-file: `docs/ARCHITECTURE.md`
carries the date and the Lambda count on the SAME line, so a naive "ignore any line
containing a date" would have swallowed the count too.

`--apply` still refreshes the stamp; only `--check` ignores it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "deploy" / "sync_doc_metadata.py"
_DOC = _REPO / "docs" / "ARCHITECTURE.md"


def _check() -> int:
    """Run the real gate exactly as CI does, and return its exit code."""
    return subprocess.run(  # nosec B603 — fixed argv
        [sys.executable, str(_SCRIPT), "--check"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    ).returncode


@pytest.fixture
def doc_text():
    """Restore ARCHITECTURE.md byte-for-byte however the test exits."""
    original = _DOC.read_text(encoding="utf-8")
    yield original
    _DOC.write_text(original, encoding="utf-8")


def _stale_the_date(text: str) -> str:
    """Roll the 'Last updated:' stamp back one day — the state every doc is in at
    00:00Z before the day's first merge."""
    import re

    def back_one_day(m):
        from datetime import date, timedelta

        y, mo, d = (int(x) for x in m.group(1).split("-"))
        return "Last updated: " + (date(y, mo, d) - timedelta(days=1)).isoformat()

    new, n = re.subn(r"Last updated: (\d{4}-\d{2}-\d{2})", back_one_day, text, count=1)
    assert n == 1, "could not find a 'Last updated: <date>' stamp to age"
    return new


@pytest.mark.skipif(not _SCRIPT.exists(), reason="sync_doc_metadata.py not present")
def test_d_a_clean_tree_passes(doc_text):
    """Baseline. If this fails, every other case below is uninterpretable."""
    assert _check() == 0, "the gate is not green on a clean tree — fix that before reading the rest"


@pytest.mark.skipif(not _SCRIPT.exists(), reason="sync_doc_metadata.py not present")
def test_a_a_stale_date_stamp_alone_is_not_drift(doc_text):
    """The bug: this used to exit 1 once per UTC midnight."""
    _DOC.write_text(_stale_the_date(doc_text), encoding="utf-8")
    assert _check() == 0, "a date-only difference still fails the gate (#2649)"


@pytest.mark.skipif(not _SCRIPT.exists(), reason="sync_doc_metadata.py not present")
def test_b_a_substantive_drift_still_fails(doc_text):
    """The fix must not buy green by weakening the gate."""
    assert "104 Lambdas" in doc_text or "Lambdas" in doc_text
    _DOC.write_text(doc_text.replace("104 Lambdas", "999 Lambdas", 1), encoding="utf-8")
    assert _check() == 1, "a wrong Lambda count no longer fails the gate — the guard is gone"


@pytest.mark.skipif(not _SCRIPT.exists(), reason="sync_doc_metadata.py not present")
def test_c_a_stale_date_does_not_hide_a_substantive_drift(doc_text):
    """The subtle one. Both literals live on the SAME line, so masking the date must
    not mask the count that shares it."""
    both = _stale_the_date(doc_text).replace("104 Lambdas", "999 Lambdas", 1)
    _DOC.write_text(both, encoding="utf-8")
    assert _check() == 1, "a stale date stamp masked a real drift on the same line (#2649)"


def test_the_date_masker_is_not_a_blanket_line_ignore():
    """Unit-level statement of the same contract, so a refactor that reverts to
    line-level ignoring fails here even if the subprocess cases are skipped."""
    sys.path.insert(0, str(_REPO / "deploy"))
    os.environ.setdefault("AWS_REGION", "us-west-2")
    from sync_doc_metadata import _differs_only_by_date_stamp

    assert _differs_only_by_date_stamp("Last updated: 2026-08-14 (v8.6.0)", "Last updated: 2026-08-15 (v8.6.0)")
    assert not _differs_only_by_date_stamp(
        "Last updated: 2026-08-14 (v8.6.0 — 104 Lambdas)",
        "Last updated: 2026-08-15 (v8.6.0 — 999 Lambdas)",
    )
    assert not _differs_only_by_date_stamp("76 tools", "88 tools")
