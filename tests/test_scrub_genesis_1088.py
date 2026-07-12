"""tests/test_scrub_genesis_1088.py — #1088: the time-travel scrub floor follows genesis.

The cockpit's time-travel scrub (site/assets/js/cockpit.js) must derive its
floor from a RUNTIME genesis source — the /api/snapshot payload first
(top-level start_date pre-start, journey.started_date after), with the single
swept client literal (GENESIS_ISO in coach_popover.js) as the boot fallback —
never a per-cycle literal of its own. History: the scrub min was hardcoded
"2026-04-01" (the cycle-1 / all-cycles floor), and a stranded genesis literal
is exactly the class of bug that has broken on past re-anchors.

Guards pinned here:
  1. cockpit.js carries NO quoted ISO-date literal at all — nothing to strand.
  2. cockpit.js consumes the runtime sources (GENESIS_ISO import + the
     snapshot payload fields) and coach_popover.js exports the swept literal.
  3. A SIMULATED re-anchor (the real sweep, deploy/restart_site_copy_sync.py
     rewrite_js_files, run over copies of the real files) moves GENESIS_ISO to
     the new genesis while cockpit.js needs no sweep — i.e. the scrub floor
     follows genesis with no literal left behind.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

COCKPIT = REPO_ROOT / "site" / "assets" / "js" / "cockpit.js"
POPOVER = REPO_ROOT / "site" / "assets" / "js" / "coach_popover.js"

_spec = importlib.util.spec_from_file_location("restart_site_copy_sync", REPO_ROOT / "deploy" / "restart_site_copy_sync.py")
scs = importlib.util.module_from_spec(_spec)
sys.modules["restart_site_copy_sync"] = scs
_spec.loader.exec_module(scs)

# A quoted ISO date literal ('2026-04-01' / "2026-04-01" / "2026-04-01T12:00:00").
# Regex-source date shapes (/^\d{4}-\d{2}-\d{2}$/) are unquoted and don't match.
_ISO_LITERAL = re.compile(r"""['"]\d{4}-\d{2}-\d{2}(?:T[^'"]*)?['"]""")

_GENESIS_ISO_LINE = re.compile(r"""export\s+const\s+GENESIS_ISO\s*=\s*["'](\d{4}-\d{2}-\d{2})["']""")


def test_cockpit_has_no_iso_date_literal():
    src = COCKPIT.read_text()
    hits = _ISO_LITERAL.findall(src)
    assert not hits, f"cockpit.js must not carry a quoted ISO date literal (a stranded scrub floor): {hits}"


def test_cockpit_scrub_uses_runtime_genesis_sources():
    src = COCKPIT.read_text()
    assert re.search(
        r"import\s*\{[^}]*\bGENESIS_ISO\b[^}]*\}\s*from\s*['\"]/assets/js/coach_popover\.js['\"]", src
    ), "cockpit.js must import GENESIS_ISO (the single swept client literal) as the scrub-floor fallback"
    # Payload-first: the snapshot's genesis fields feed configureScrub at load time.
    assert (
        "start_date" in src and "started_date" in src
    ), "cockpit.js must read the snapshot payload's genesis (start_date / journey.started_date)"
    assert "configureScrub" in src, "the re-entrant scrub configuration hook must exist"


def test_popover_exports_the_swept_genesis_literal():
    src = POPOVER.read_text()
    m = _GENESIS_ISO_LINE.search(src)
    assert m, "coach_popover.js must export GENESIS_ISO as a plain quoted ISO literal (the reset sweep rewrites that form)"
    # GENESIS (the Date the countdown math uses) must derive from the same literal,
    # so the sweep can never split the two.
    assert re.search(
        r"new Date\(`\$\{GENESIS_ISO\}T00:00:00`\)", src
    ), "GENESIS must derive from GENESIS_ISO — one literal, one sweep target"


def test_simulated_reanchor_moves_the_scrub_floor(tmp_path, monkeypatch):
    """Run the REAL sweep over copies of the REAL files: the fallback literal
    follows the new genesis; cockpit.js has nothing to sweep and nothing stale."""
    cur = _GENESIS_ISO_LINE.search(POPOVER.read_text())
    assert cur, "coach_popover.js must carry GENESIS_ISO"
    old_genesis = cur.group(1)
    new_genesis = "2027-01-01"  # a simulated next re-anchor (synthetic tree only)

    for f in (COCKPIT, POPOVER):
        dst = tmp_path / f.relative_to(REPO_ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(f.read_text())

    monkeypatch.setattr(scs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(scs, "EXPERIMENT_START_DATE", new_genesis)
    touched = scs.rewrite_js_files(apply=True, old_genesis=old_genesis)

    popover_after = (tmp_path / "site/assets/js/coach_popover.js").read_text()
    cockpit_after = (tmp_path / "site/assets/js/cockpit.js").read_text()

    assert "site/assets/js/coach_popover.js" in touched, f"the sweep must catch GENESIS_ISO (touched={touched})"
    m = _GENESIS_ISO_LINE.search(popover_after)
    assert m and m.group(1) == new_genesis, "GENESIS_ISO must follow the re-anchor"
    assert old_genesis not in popover_after, "no stale genesis may survive in coach_popover.js"

    # The point of #1088: the cockpit has NO literal for the sweep to catch or miss.
    assert "site/assets/js/cockpit.js" not in touched, "cockpit.js must have no genesis literal for the sweep to rewrite"
    assert cockpit_after == COCKPIT.read_text(), "cockpit.js must be byte-identical across a re-anchor"
    assert old_genesis not in cockpit_after and "2026-04-01" not in cockpit_after
