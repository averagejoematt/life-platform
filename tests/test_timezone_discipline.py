"""
tests/test_timezone_discipline.py — permanent gate for the 2026-06-12 DST bug class.

Two bug patterns appeared SIX times across the codebase before being swept:

  1. Fixed-offset Pacific math: `datetime.now(timezone.utc) - timedelta(hours=8)`
     pins PST year-round — every derived hour/date is wrong March–November (PDT).
     Found in: whoop sleep hours (mcp/helpers), eightsleep ingestion, qa_smoke
     pt_now(), output_writers + dashboard_refresh friendly timestamps.
     Correct form: `datetime.now(ZoneInfo("America/Los_Angeles"))`.

  2. Aware/naive mixing: `datetime.now(timezone.utc) - datetime.strptime(...)`
     raises TypeError at runtime (killed get_weight_loss_progress live).
     Correct form: subtract `.date()` from `.date()`, or attach tzinfo first.

These greps ban the exact idioms. If a new use is genuinely justified, add the
file:line to the allowlist below WITH a reason — don't weaken the patterns.

Run:  python3 -m pytest tests/test_timezone_discipline.py -v
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["lambdas", "mcp", "deploy", "scripts", "remediation"]

# (pattern, description). Patterns are applied per-line.
BANNED = [
    (
        re.compile(r"now\(timezone\.utc\)\s*[-+]\s*timedelta\(hours\s*=\s*-?[78]\b"),
        "fixed-offset Pacific math — use datetime.now(ZoneInfo('America/Los_Angeles'))",
    ),
    (
        re.compile(r"now\(timezone\.utc\)\s*-\s*datetime\.strptime"),
        "aware-minus-naive subtraction (TypeError) — compare .date() to .date(), or attach tzinfo",
    ),
]

# file-suffix → substrings that exempt a matching line (must carry a tz fix on the line)
LINE_EXEMPT_SUBSTRINGS = ("tzinfo", ".date()")

# Justified exceptions: relative path → reason. Keep this SHORT.
ALLOWLIST: dict[str, str] = {}


def _scan():
    hits = []
    for d in SCAN_DIRS:
        for path in (ROOT / d).rglob("*.py"):
            if "__pycache__" in str(path) or "layer-build" in str(path):
                continue
            rel = str(path.relative_to(ROOT))
            if rel in ALLOWLIST:
                continue
            try:
                lines = path.read_text().splitlines()
            except UnicodeDecodeError:
                continue
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for pat, desc in BANNED:
                    if pat.search(line) and not any(s in line for s in LINE_EXEMPT_SUBSTRINGS):
                        hits.append(f"{rel}:{i}: {desc}\n    {stripped[:110]}")
    return hits


def test_no_fixed_offset_or_naive_mixed_pacific_math():
    hits = _scan()
    assert not hits, "Timezone-discipline violations (see module docstring for the 2026-06-12 bug class):\n" + "\n".join(hits)
