"""tests/test_oauth_reauth_breaker_clear_coverage.py — #2085.

Guards the SET, not the instance (a recurring bug class in this repo — see
CLAUDE.md/MEMORY notes on hand-enumerated source lists drifting from the
registry). The issue's fix must apply to every oauth-facet source's re-auth
path *as derived from `source_registry.oauth_source_ids()`* — not a
hand-typed list of "whoop, dropbox, ..." that silently stops covering a new
script added later (say, a future `setup_hevy_auth.py`).

This test doesn't hand-enumerate either: it scans every `setup/*.py` file,
finds the ones that write a secret named `life-platform/<source>` where
`<source>` is a REGISTERED oauth-facet source, and asserts each one calls
`clear_breaker_after_reauth` somewhere in its source. A new re-auth script
that forgets the wire-up fails this test the moment it's added, instead of
silently reintroducing the #2085 gap.
"""

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_LAMBDAS = _REPO / "lambdas"
if str(_LAMBDAS) not in sys.path:
    sys.path.insert(0, str(_LAMBDAS))

from ingestion.source_registry import oauth_source_ids  # noqa: E402

_SECRET_RE = re.compile(r'SECRET_(?:NAME|ID)\s*=\s*"life-platform/([a-zA-Z0-9_-]+)"')


def _oauth_facet_reauth_scripts():
    """Yield (path, source_name) for every setup/*.py file that writes a
    `life-platform/<source>` secret where <source> is registry-oauth-facet."""
    oauth_sources = set(oauth_source_ids())
    setup_dir = _REPO / "setup"
    for py_file in sorted(setup_dir.glob("*.py")):
        if py_file.name == "oauth_reauth_common.py":
            continue  # the helper itself, not a re-auth script
        text = py_file.read_text()
        match = _SECRET_RE.search(text)
        if not match:
            continue
        source = match.group(1)
        if source in oauth_sources:
            yield py_file, source, text


def test_every_oauth_facet_reauth_script_clears_the_breaker():
    scripts = list(_oauth_facet_reauth_scripts())

    # Guard the guard: if the registry/secret-naming convention ever drifts
    # such that this scan stops matching anything, that's itself a silent
    # regression of this test's coverage — fail loudly rather than pass empty.
    assert scripts, "expected at least one setup/*.py script writing an oauth-facet source's secret"

    missing = [path.name for path, _source, text in scripts if "clear_breaker_after_reauth" not in text]
    assert not missing, (
        "these re-auth scripts write credentials for a registry oauth-facet source but never call "
        f"clear_breaker_after_reauth (setup/oauth_reauth_common.py): {missing} — a verified re-auth there "
        "would leave the AUTH_FAILURE breaker latched for up to 24h (#2085)."
    )


def test_non_oauth_facet_secret_scripts_are_correctly_excluded():
    """Sanity check on the scanner itself: setup/ has re-auth scripts for
    sources that are NOT in the oauth facet (monarch, onedrive,
    google-calendar aren't ingestion sources tracked by source_registry) —
    confirm the scan skips them rather than accidentally matching zero files
    because the regex/glob is broken."""
    setup_dir = _REPO / "setup"
    all_py = {p.name for p in setup_dir.glob("*.py")}
    covered = {path.name for path, _source, _text in _oauth_facet_reauth_scripts()}
    assert all_py - covered, "expected at least one setup/*.py file to be a non-oauth-facet script (sanity on the scanner)"
