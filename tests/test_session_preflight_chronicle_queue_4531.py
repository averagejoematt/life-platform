"""#4531 — the SessionStart pre-flight prints the chronicle approve queue.

Incident 2026-10-14 (docs/INCIDENT_LOG.md): week 6 was drafted by the legacy writer after the
desk failed twice (#4914), the preview email went out at 15:04:40Z, nobody approved it, and
two sessions booted inside the 48-hour review window with no line saying a draft was waiting.
The fixture is the wire: the real `DATE#2026-10-13` row's attributes as the sweep reads them.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "scripts" / "hooks" / "session_preflight.py"


def _load():
    spec = importlib.util.spec_from_file_location("_preflight_4531", HOOK)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# The real week-6 row (projection read 2026-10-17T03:10Z): status draft, no phase, no tombstone.
WEEK6 = {"sk": "DATE#2026-10-13", "status": "draft", "week_number": Decimal("6"), "generated_at": "2026-10-14T15:04:39.677000+00:00"}
WEEK5 = {"sk": "DATE#2026-10-06", "status": "published", "week_number": Decimal("5"), "phase": "experiment"}
NOW = dt.datetime(2026, 10, 17, 3, 10, tzinfo=dt.timezone.utc)


def test_the_held_week6_draft_is_printed_with_its_age_and_the_way_out():
    lines = _load().chronicle_queue_lines([WEEK5, WEEK6], NOW)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "DRAFT DATE#2026-10-13 (week 6)" in line
    assert "unapproved 2d12h" in line
    assert "HELD by the 48-h sweep" in line and "force the desk" in line


def test_a_published_row_is_not_a_queue_entry():
    assert _load().chronicle_queue_lines([WEEK5], NOW) == ["  chronicle   no draft awaiting approval"]


def test_a_fresh_draft_inside_the_review_window_says_so():
    fresh = dict(WEEK6, generated_at="2026-10-15T15:04:39+00:00")
    (line,) = _load().chronicle_queue_lines([fresh], NOW)
    assert "unapproved 1d12h" in line and "inside the review window" in line and "HELD" not in line


def test_a_tombstoned_draft_is_flagged_as_history_never_hidden():
    old = dict(WEEK6, sk="DATE#2026-08-31", tombstone=True, phase="pilot")
    (line,) = _load().chronicle_queue_lines([old], NOW)
    assert "DATE#2026-08-31" in line and "history, the sweep skips it" in line


def test_the_hook_prints_an_unverified_chronicle_line_when_inert():
    env = dict(os.environ, CLAUDE_HOOK_INERT="1")
    proc = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, timeout=60, env=env, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    assert "  chronicle   UNVERIFIED (hook inert" in proc.stdout, proc.stdout
