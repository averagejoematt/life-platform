"""#1103 — the CSS token guard, enforced.

The swept sheets (story/evidence/cockpit) must draw every font-size from the
--fs-* type triad (or carry an explicit inline `/* fs-ok: reason */` sanction),
and every var(--x) reference must resolve to a token that actually exists —
a reference to an undefined token means its fallback is silently always active
(the story.css:351 bug class). Offline, repo-only: safe in the CI unit-test job.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_css_tokens  # noqa: E402


def test_swept_sheets_stay_on_the_type_scale():
    findings = check_css_tokens.check()
    assert not findings, "CSS token guard findings:\n" + "\n".join(findings)


def test_raw_hex_check_is_non_vacuous():
    """#1211 — the raw-hex guard actually fires. Proves it catches the exact live
    off-palette literals it was written for (lead-coach sky #0ea5e9, vice-hold green
    #16a34a), ignores hex inside comments (issue refs), and honours the sanction."""
    # A live declaration with a raw hex is caught.
    assert check_css_tokens.raw_hex_findings(".team-lead { border-left: 3px solid #0ea5e9; }") == [(1, "#0ea5e9")]
    assert check_css_tokens.raw_hex_findings(".vice-hold { border-left-color: #16a34a; }") == [(1, "#16a34a")]
    # A hex inside a comment (an issue ref) is NOT a colour literal.
    assert check_css_tokens.raw_hex_findings("/* see #1112 for the lead tier */ .x { color: var(--ember); }") == []
    # A deliberate literal carrying the sanction is exempt.
    assert check_css_tokens.raw_hex_findings(".pl-lost { color: #dc2626; } /* hex-ok: status colour */") == []
