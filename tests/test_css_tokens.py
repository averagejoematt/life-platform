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
