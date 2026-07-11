"""tests/test_restart_site_sweep.py — the genesis literal sweep follows the genesis.

The 2026-07-10 clean-sweep audit: restart_site_copy_sync's JS sweep was
hardcoded to the cycle-1 literal "2026-04-01", so the cycle-4 genesis
"2026-06-14" (coach_popover.js, evidence_body.js, dispatches.js,
evidence_habits.js — ISO and prose forms) survived every later reset. These
tests run the sweep DRY against the real site/ tree with a simulated new
genesis and assert the known offender files are caught, so a regression in the
sweep (or a new hardcoded genesis literal pattern it can't see) fails in CI.
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

OLD = "2026-06-14"  # the cycle-4 genesis actually hardcoded in site JS today
NEW = "2026-07-12"  # a simulated next genesis (never written: apply=False)


def _with_new_genesis(monkeypatch):
    monkeypatch.setattr(scs, "EXPERIMENT_START_DATE", NEW)


def test_iso_sweep_catches_known_offenders(monkeypatch):
    _with_new_genesis(monkeypatch)
    touched = scs.rewrite_js_files(apply=False, old_genesis=OLD)
    for offender in (
        "site/assets/js/coach_popover.js",  # const GENESIS = new Date("2026-06-14T00:00:00")
        "site/assets/js/evidence_body.js",  # export const PHYS_GENESIS = "2026-06-14"
        "site/assets/js/dispatches.js",  # const GENESIS / const GEN = "2026-06-14"
        "site/assets/js/evidence_habits.js",  # cutDate: "2026-06-14"
    ):
        assert offender in touched, f"{offender} not caught by the ISO sweep (touched={touched})"


def test_prose_sweep_catches_known_offenders(monkeypatch):
    _with_new_genesis(monkeypatch)
    touched = scs.rewrite_genesis_prose(apply=False, old_genesis=OLD)
    for offender in (
        "site/assets/js/coach_popover.js",  # "since June 14 2026"
        "site/assets/js/evidence_habits.js",  # "cut starting Jun 14" caption
    ):
        assert offender in touched, f"{offender} not caught by the prose sweep (touched={touched})"


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


def test_sweeps_never_touch_legacy(monkeypatch):
    _with_new_genesis(monkeypatch)
    for touched in (
        scs.rewrite_js_files(apply=False, old_genesis=OLD),
        scs.rewrite_genesis_prose(apply=False, old_genesis=OLD),
        scs.rewrite_html_files(apply=False),
    ):
        legacy = [t for t in touched if "/legacy/" in t]
        assert not legacy, f"/legacy is preserved verbatim (ADR-071) but the sweep touched: {legacy}"


def test_same_genesis_is_noop():
    # re-converge run (old == new) must not rewrite anything
    assert scs.rewrite_js_files(apply=False, old_genesis=scs.EXPERIMENT_START_DATE) == []
    assert scs.rewrite_genesis_prose(apply=False, old_genesis=scs.EXPERIMENT_START_DATE) == []
