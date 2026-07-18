"""#1103/#1211/#1212 — the CSS token guard, enforced.

The seven CONSUMER sheets (story/evidence/cockpit/mind/fonts/section_toc/subscribe)
must draw every font-size from the --fs-* type triad (or carry an explicit inline
`/* fs-ok: reason */` sanction), carry no raw hex colour (#1211), and every var(--x)
reference must resolve to a token that actually exists — a reference to an undefined
token means its fallback is silently always active (the story.css:351 bug class).
Every (max|min)-width breakpoint across site/assets/css must be one of the nine
sanctioned §10.1 numbers (#1212). Offline, repo-only: safe in the CI unit-test job.
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


def test_sweep_covers_all_consumer_sheets():
    """#1212 — the sweep actually reaches every consumer sheet (the vacuous-scan trap:
    a scan whose file set silently covers nothing). tokens.css is the definitions /
    allowlist source and is deliberately NOT a swept target (it would flag its own
    scale + palette). The evidence pointer: mind.css was previously unswept."""
    for sheet in ["story.css", "evidence.css", "cockpit.css", "mind.css", "fonts.css", "section_toc.css", "subscribe.css"]:
        assert sheet in check_css_tokens.SWEPT, f"{sheet} must be swept"
    assert "tokens.css" not in check_css_tokens.SWEPT  # the allowlist/definitions file, never swept
    # And the sweep genuinely fires on a planted violation in a (now-swept) mind-style sheet.
    assert check_css_tokens.raw_hex_findings(".sp-face { background: #1d1810; }") == [(1, "#1d1810")]


def test_font_size_check_is_non_vacuous():
    """The font-size guard fires on a raw literal and a live var()-with-literal-fallback,
    passes a real token, and honours the /* fs-ok: */ sanction."""
    assert check_css_tokens.font_size_findings("x.css", ".a { font-size: 0.62rem; }")
    assert check_css_tokens.font_size_findings("x.css", ".a { font-size: var(--fs-display, 4.5rem); }")
    assert not check_css_tokens.font_size_findings("x.css", ".a { font-size: var(--fs-small); }")
    assert not check_css_tokens.font_size_findings("x.css", ".a { font-size: 0.62rem; /* fs-ok: micro-mono */ }")


def test_breakpoint_check_is_non_vacuous():
    """#1212 — the §10.1 nine-number invariant fires on a rogue value and passes each
    sanctioned one. Proves it catches the exact pre-fix story.css:582 (max-width: 520px)."""
    # The pre-fix rogue value is caught.
    assert check_css_tokens.breakpoint_findings_in("story.css", "@media (max-width: 520px) { .cb-style { grid-template-columns: 1fr; } }")
    assert check_css_tokens.breakpoint_findings_in("x.css", "@media (min-width: 500px) {}")  # any tenth value
    # Every sanctioned breakpoint passes.
    for bp in sorted(check_css_tokens.SANCTIONED_BREAKPOINTS):
        prefix = "min" if bp in (601, 761, 821, 901) else "max"
        assert not check_css_tokens.breakpoint_findings_in("x.css", f"@media ({prefix}-width: {bp}px) {{}}"), bp
    # A breakpoint inside a comment is not a live query.
    assert not check_css_tokens.breakpoint_findings_in("x.css", "/* was (max-width: 520px) */ @media (max-width: 600px) {}")
