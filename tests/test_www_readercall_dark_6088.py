"""#6088 — the reader-call control is built DARK: the deploy scan refuses a dist that carries it.

Owner ruling 2026-11-16: "Develop and test privately." The control (www/src/components/ReaderCall.astro + the island
injected by www/src/lib/readercall.js) exists only in a WEB_READERCALL=1 build. Every deploy runs
``scripts/check_www_build.py --scan-only``; ``readercall_leaks`` is the clause of that scan that refuses such a dist.
The switch, the self-gating component and the words are www/tests/readercall.test.mjs; the master proof — a recursive
diff of dist/ against main built from the same snapshot — is recorded in the PR.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import check_www_build  # noqa: E402


def _dist(tmp_path, files: dict) -> str:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


CLEAN = {
    "index.html": "<html><body><main>front</main></body></html>",
    "system/ledger/sleep-x/index.html": "<html><body><section aria-label='Surfaces in'></section></body></html>",
    "_astro/page.abc.js": "export const x = 1;",
}


def test_a_clean_dist_passes_and_every_planted_leak_is_refused(tmp_path):
    """The clean control passes; each of the three shapes a WEB_READERCALL=1 build leaves is refused by name."""
    assert check_www_build.readercall_leaks(_dist(tmp_path / "clean", CLEAN)) == []
    planted = {
        "marker on a page": {"system/ledger/sleep-x/index.html": '<section data-readercall="open" data-call="sleep-x"></section>'},
        "the island chunk": {"_astro/page.def.js": 'document.querySelectorAll("[data-readercall]")'},
        "the route in data": {"data/x.json": '{"api": "/api/reader_call"}'},
    }
    for name, extra in planted.items():
        leaks = check_www_build.readercall_leaks(_dist(tmp_path / name.replace(" ", "_"), {**CLEAN, **extra}))
        assert len(leaks) == 1 and "WEB_READERCALL=1" in leaks[0], (name, leaks)


def test_the_deploy_scan_runs_the_readercall_clause():
    """`scan()` is what `--scan-only` runs on every deploy; the clause must be inside it, not merely defined."""
    src = open(os.path.join(_REPO, "scripts", "check_www_build.py"), encoding="utf-8").read()
    body = src[src.index("def scan(") : src.index("\ndef ", src.index("def scan(") + 1)]
    assert "issues.extend(readercall_leaks(dist))" in body


def test_a_private_build_never_rewrites_the_committed_deploy_maps():
    """postbuild leaves owned_paths.json / reach.json as committed on a WEB_READERCALL=1 build (the room's rule)."""
    src = open(os.path.join(_REPO, "www", "scripts", "postbuild.mjs"), encoding="utf-8").read()
    assert "const readercall = readerCallEnabled();" in src
    assert "const room = privateRoom || lab || story || readercall;" in src
    assert "if (!room) writeFileSync(OWNED_OUT" in src and "if (!room) writeFileSync(REACH_OUT" in src


def test_the_api_switch_and_the_page_switch_are_both_off():
    """Two switches, both off: the API's committed constant and the page's private-only env switch (no go-live line)."""
    sys.path.insert(0, os.path.join(_REPO, "lambdas"))
    from web import reader_call_rules

    assert reader_call_rules.READER_CALL_LIVE is False
    lib = open(os.path.join(_REPO, "www", "src", "lib", "readercall.js"), encoding="utf-8").read()
    assert 'env[READERCALL_ENV] === "1"' in lib and "LIVE" not in lib.replace("READER_CALL_LIVE", "")
