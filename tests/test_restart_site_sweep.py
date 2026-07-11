"""tests/test_restart_site_sweep.py — the genesis literal sweep follows the genesis.

The 2026-07-10 clean-sweep audit: restart_site_copy_sync's JS sweep was
hardcoded to the cycle-1 literal "2026-04-01", so the cycle-4 genesis
"2026-06-14" (coach_popover.js, evidence_body.js, dispatches.js,
evidence_habits.js — ISO and prose forms) survived every later reset. These
tests pin the property that mattered: the sweep catches the ISO and prose
forms that actually leaked, in the file types they leaked in.

They run against a SYNTHETIC site tree (tmp_path, planted offender literals),
not the live site/ — asserting the live tree still carries the outgoing
genesis made the test eat itself the moment a real reset legitimately swept
those literals away (exactly what happened on the cycle-5 reset). The sweep
functions read the module-global REPO_ROOT at call time, so the fixture just
repoints it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("restart_site_copy_sync", REPO_ROOT / "deploy" / "restart_site_copy_sync.py")
scs = importlib.util.module_from_spec(_spec)
sys.modules["restart_site_copy_sync"] = scs
_spec.loader.exec_module(scs)

OLD = "2026-06-14"  # a planted outgoing genesis (the cycle-4 literal that leaked)
NEW = "2026-07-12"  # a simulated next genesis (never written: apply=False)

# The offender shapes from the 2026-07-10 audit, planted verbatim.
_FIXTURES = {
    "site/assets/js/coach_popover.js": (f'const GENESIS = new Date("{OLD}T00:00:00");\nconst stamp = "since June 14 2026";\n'),
    "site/assets/js/evidence_body.js": f'export const PHYS_GENESIS = "{OLD}";\n',
    "site/assets/js/dispatches.js": f"const GEN = '{OLD}';\n",
    "site/assets/js/evidence_habits.js": (f'const cfg = {{ cutDate: "{OLD}" }};\nconst caption = "the cut starting Jun 14";\n'),
    # prose + bare-ISO forms in HTML (the html-iso branch of the prose sweep)
    "site/story/index.html": (f'<p>Day 1 was June 14, 2026.</p>\n<time datetime="{OLD}">{OLD}</time>\n'),
    # /legacy is preserved verbatim (ADR-071): planted literal must NOT be touched
    "site/legacy/assets/old.js": f'const GENESIS = "{OLD}"; // since June 14 2026\n',
}

JS_OFFENDERS = (
    "site/assets/js/coach_popover.js",  # const GENESIS = new Date("...T00:00:00")
    "site/assets/js/evidence_body.js",  # export const PHYS_GENESIS = "..."
    "site/assets/js/dispatches.js",  # const GEN = '...'
    "site/assets/js/evidence_habits.js",  # cutDate: "..."
)

PROSE_OFFENDERS = (
    "site/assets/js/coach_popover.js",  # "since June 14 2026"
    "site/assets/js/evidence_habits.js",  # "cut starting Jun 14" caption
)


def _fixture_tree(tmp_path, monkeypatch):
    """Build the synthetic site/ tree and point the sweep at it (NEW genesis)."""
    for rel, text in _FIXTURES.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    monkeypatch.setattr(scs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(scs, "EXPERIMENT_START_DATE", NEW)


def test_iso_sweep_catches_known_offenders(tmp_path, monkeypatch):
    _fixture_tree(tmp_path, monkeypatch)
    touched = scs.rewrite_js_files(apply=False, old_genesis=OLD)
    for offender in JS_OFFENDERS:
        assert offender in touched, f"{offender} not caught by the ISO sweep (touched={touched})"


def test_prose_sweep_catches_known_offenders(tmp_path, monkeypatch):
    _fixture_tree(tmp_path, monkeypatch)
    touched = scs.rewrite_genesis_prose(apply=False, old_genesis=OLD)
    for offender in PROSE_OFFENDERS:
        assert offender in touched, f"{offender} not caught by the prose sweep (touched={touched})"
    # HTML carries both a prose form and a bare ISO literal — the html branch must see it.
    assert "site/story/index.html" in touched, f"html prose/ISO form not caught (touched={touched})"


def test_prose_patterns_forms():
    pats = scs._genesis_prose_patterns(OLD, NEW)
    text = "since June 14 2026 · started June 14, 2026 · the cut starting Jun 14 · ringed June 14 marker"
    for pat, repl in pats:
        text = pat.sub(repl, text)
    assert text == "since July 12 2026 · started July 12, 2026 · the cut starting Jul 12 · ringed July 12 marker"


def test_iso_rewrite_preserves_time_suffix_and_other_dates():
    import re

    pat = re.compile(rf"(['\"]){re.escape(OLD)}(T[^'\"]*)?\1")
    src = 'const GENESIS = new Date("2026-06-14T00:00:00"); const other = "2026-05-01"; const g = \'2026-06-14\';'

    def repl(m):
        q, suffix = m.group(1), m.group(2) or ""
        return f"{q}{NEW}{suffix}{q}"

    out = pat.sub(repl, src)
    assert '"2026-07-12T00:00:00"' in out
    assert "'2026-07-12'" in out
    assert '"2026-05-01"' in out  # unrelated dates untouched


def test_sweeps_never_touch_legacy(tmp_path, monkeypatch):
    # The fixture plants the SAME offender literal inside site/legacy/ — the
    # sweep must skip it even though it would match (ADR-071: verbatim rollback).
    _fixture_tree(tmp_path, monkeypatch)
    for touched in (
        scs.rewrite_js_files(apply=False, old_genesis=OLD),
        scs.rewrite_genesis_prose(apply=False, old_genesis=OLD),
        scs.rewrite_html_files(apply=False),
    ):
        legacy = [t for t in touched if "/legacy/" in t]
        assert not legacy, f"/legacy is preserved verbatim (ADR-071) but the sweep touched: {legacy}"


def test_same_genesis_is_noop(tmp_path, monkeypatch):
    # re-converge run (old == new) must not rewrite anything, even with matches present
    _fixture_tree(tmp_path, monkeypatch)
    assert scs.rewrite_js_files(apply=False, old_genesis=scs.EXPERIMENT_START_DATE) == []
    assert scs.rewrite_genesis_prose(apply=False, old_genesis=scs.EXPERIMENT_START_DATE) == []
