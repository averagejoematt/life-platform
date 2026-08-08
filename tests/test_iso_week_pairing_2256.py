"""tests/test_iso_week_pairing_2256.py — the `%Y-W%V` ISO-week class, guarded as a SET (#2256).

THE DEFECT. `datetime.strftime("%Y-W%V")` pairs the CALENDAR year (`%Y`) with the ISO
week NUMBER (`%V`). They disagree at every year boundary: 2027-01-01 belongs to ISO week
2026-W53, but `%Y-W%V` labels it `2027-W53`. One true ISO week therefore splits into two
buckets — and because these labels are sorted lexically, `2027-W53` sorts AFTER
`2027-W01`, so the chart draws late December to the RIGHT of the following week. The
correct pairing is `%G` (ISO week-year) with `%V`.

WHY A DERIVED GUARD. This class has now been found three times by three different
readers, each time by someone eyeballing one module:

  * tranche 1 fixed the instances it happened to see;
  * tranche 2 (#1658/#2208) found a survivor in `site_api_meals.py`;
  * tranche 3 (PR #2229 → this issue) found three more in `site_api_training.py`.

"Fix the instance" demonstrably does not converge on this class, so this file does not
enumerate the offenders: it AST-scans every `.py` under `lambdas/` and `mcp/` for string
literals that mispair a year directive with a week-number directive, in EITHER direction,
and fails on any hit. A new mispairing fails this test the moment it is written.
See the memory note "guard the SET, not the instance".

THE RULE, both directions:

  * `%V` (ISO week number, 01–53) is only meaningful beside `%G` (ISO week-year).
    `%Y`/`%y` beside `%V` is the bug above.
  * `%U`/`%W` (calendar-year week numbers) are only meaningful beside `%Y`/`%y`.
    `%G` beside `%U`/`%W` is the same bug mirrored — an ISO year stamped on a
    calendar week — and it would be just as invisible to a reader.

NON-VACUITY. A scanner that silently matches nothing passes forever. Two tests below
prove this one does not: `test_the_scanner_flags_a_planted_violation` writes a synthetic
module containing the exact defect and asserts the scanner reports it, and
`test_the_scan_actually_reaches_the_shipped_correct_call_sites` asserts the walk finds
the known-good `%G-W%V` call sites in the real tree (so the scan cannot be passing
because it walked an empty file set).
"""

from __future__ import annotations

import ast
import pathlib
import sys
from datetime import datetime, timezone

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from web import site_api_common as sac, site_api_training as training  # noqa: E402

_ROOTS = (_REPO / "lambdas", _REPO / "mcp")

# ──────────────────────────────────────────────────────────────────────────────
# The derived-set scanner
# ──────────────────────────────────────────────────────────────────────────────

_ISO_WEEK = "%V"
_ISO_YEAR = "%G"
_CAL_WEEKS = ("%U", "%W")
_CAL_YEARS = ("%Y", "%y")


def mispairing(fmt: str) -> str | None:
    """The mispairing in one strftime/strptime format string, or None.

    `%%` is a literal percent, not a directive, so it is stripped before the
    directive scan — `"100%%Y"` must not read as a `%Y`.
    """
    s = fmt.replace("%%", "")
    if _ISO_WEEK in s and any(y in s for y in _CAL_YEARS):
        return "ISO week number %V paired with a CALENDAR year (%Y/%y) — use %G"
    if _ISO_YEAR in s and any(w in s for w in _CAL_WEEKS):
        return "calendar week number (%U/%W) paired with the ISO year %G — use %Y"
    return None


def scan(roots) -> dict[str, str]:
    """Every string literal under `roots` that mispairs a year with a week number.

    Structural (`ast`) rather than a regex over raw source: a textual grep also
    matches prose in comments and docstrings — including the ones in this file and
    in the tests that document the trap — none of which any code executes. Only
    real string constants are scanned, which is exactly where a format string
    reaches `strftime`/`strptime`.
    """
    found: dict[str, str] = {}
    for root in roots:
        for path in sorted(pathlib.Path(root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(), filename=str(path))
            except SyntaxError:  # pragma: no cover - a broken file is another gate's problem
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    why = mispairing(node.value)
                    if why:
                        rel = path.relative_to(_REPO) if _REPO in path.parents else path
                        found[f"{rel}:{node.lineno}: {node.value!r}"] = why
    return found


# ──────────────────────────────────────────────────────────────────────────────
# 1. The set guard
# ──────────────────────────────────────────────────────────────────────────────


def test_no_module_pairs_a_calendar_year_with_an_iso_week_number():
    """Zero mispairings anywhere under `lambdas/` or `mcp/`.

    The four fixed by #2256 were `site_api_training.py:437,565,821` and
    `site_api_meals.py:318`; the guard is over the SET, so a fifth fails here.
    """
    hits = scan(_ROOTS)
    assert hits == {}, "ISO/calendar week mispairing:\n" + "\n".join(f"  {k} — {v}" for k, v in sorted(hits.items()))


@pytest.mark.parametrize(
    "fmt,flagged",
    [
        ("%Y-W%V", True),  # the shipped defect
        ("%y-W%V", True),  # the two-digit calendar year, same bug
        ("%G-W%U", True),  # the mirror image: ISO year on a calendar week
        ("%G-W%V", False),  # the correct ISO pairing
        ("%G-W%V-%u", False),  # ...plus ISO weekday (conversation_enrichment's parse)
        ("%Y-%m-%d", False),  # an ordinary calendar date
        ("%Y-W%W", False),  # calendar year + calendar week — internally consistent
        ("100%% of %Y", False),  # `%%` is a literal percent, not a directive
    ],
)
def test_the_rule_itself(fmt, flagged):
    """The predicate the set guard is built on, stated directly.

    Without this, a bug in `mispairing()` that made it return None for everything
    would leave the set guard passing vacuously forever.
    """
    assert (mispairing(fmt) is not None) is flagged


# ──────────────────────────────────────────────────────────────────────────────
# 2. Non-vacuity of the scan
# ──────────────────────────────────────────────────────────────────────────────


def test_the_scanner_flags_a_planted_violation(tmp_path):
    """Plant the exact defect in a synthetic module; the scanner must report it.

    This is the mutation proof: it fails if `scan()` stops walking, stops parsing,
    or stops matching.
    """
    pkg = tmp_path / "planted"
    pkg.mkdir()
    (pkg / "handler.py").write_text('from datetime import datetime\n\n\ndef week(dt):\n    return dt.strftime("%Y-W%V")\n')
    hits = scan([tmp_path])
    assert len(hits) == 1, hits
    (where,) = hits
    assert where.endswith(": '%Y-W%V'") and "handler.py:5" in where


def test_the_scan_actually_reaches_the_shipped_correct_call_sites():
    """The real walk sees real code.

    If `scan()` returned {} because it walked nothing, test 1 would pass for the
    wrong reason. These four `%G-W%V` sites are the ones that already had the
    correct pairing before #2256; finding them proves both roots are being read.
    """
    seen: set[str] = set()
    for root in _ROOTS:
        for path in pathlib.Path(root).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and "%V" in node.value:
                    seen.add(str(path.relative_to(_REPO)))
    for expected in (
        "lambdas/compute/character_sheet_lambda.py",
        "lambdas/ai/conversation_enrichment.py",
        "mcp/tools_nutrition.py",
        "mcp/tools_training.py",
    ):
        assert expected in seen, f"{expected} carries a %V format string but the scan never saw it: {sorted(seen)}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. The behaviour the fix buys, through the real training handlers
# ──────────────────────────────────────────────────────────────────────────────

_NOW = datetime(2027, 1, 5, 18, 0, 0, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    """A `datetime` subclass with a pinned `now()` — a subclass, not a Mock, so
    `strptime`/`strftime`/`timedelta` on the same name keep working."""

    @classmethod
    def now(cls, tz=None):
        return _NOW.replace(tzinfo=None) if tz is None else _NOW.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return _NOW.replace(tzinfo=None)


class FakeSources:
    """Stand-in for `site_api_common._query_source`: honours the inclusive
    `[start, end]` window the real `sk BETWEEN` applies, returns `[]` for an
    unknown source, and hands back copies."""

    def __init__(self, **by_source):
        self.data = {k: list(v) for k, v in by_source.items()}
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, source, start, end, include_pilot=False):
        self.calls.append((source, start, end))
        if start > end:
            return []
        rows = self.data.get(source, [])
        return [dict(r) for r in rows if start <= (r.get("date") or str(r.get("sk", "")).replace("DATE#", "")) <= end]


def _make_g(sources: FakeSources) -> dict:
    return {
        "_query_source": sources,
        "_experiment_date": lambda days: (_NOW - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d"),
        "EXPERIMENT_START": "2026-01-01",
        "table": None,
    }


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(training, "datetime", _FrozenDatetime)
    monkeypatch.setattr(sac, "datetime", _FrozenDatetime)
    sac.set_request_id(None)
    yield
    sac.set_request_id(None)


def _body(resp: dict) -> dict:
    import json

    return json.loads(resp["body"])


def _hevy(date: str, weight: float, reps: int) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{date}",
        "exercises": [{"exercise_name": "Bench Press", "sets": [{"weight_lbs": weight, "reps": reps}]}],
    }


def test_strength_volume_for_a_week_that_straddles_new_year_is_one_bucket():
    """`/api/strength_deep_dive` — 2026-12-31 and 2027-01-01 are the Thursday and
    Friday of the SAME ISO week (2026-W53). One bucket, one summed volume.

    Under `%Y-W%V` this produced two rows labelled '2026-W53' and '2027-W53', and
    the lexical sort put the January-1st row LAST, after '2027-W01'.
    """
    src = FakeSources(
        hevy=[
            _hevy("2026-12-31", 100.0, 10),  # ISO 2026-W53 — 1000 lbs
            _hevy("2027-01-01", 100.0, 5),  # ISO 2026-W53 — 500 lbs, same week
            _hevy("2027-01-05", 200.0, 5),  # ISO 2027-W01 — 1000 lbs
        ]
    )
    trend = _body(training.strength_deep_dive(_g=_make_g(src)))["volume_trend"]
    assert trend == [
        {"week": "2026-W53", "volume_lbs": 1500},  # 100x10 + 100x5
        {"week": "2027-W01", "volume_lbs": 1000},  # 200x5
    ], f"the straddling week split into {trend}"


def _strava(date: str, minutes: float) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": f"DATE#{date}",
        "activities": [{"sport_type": "Run", "duration_minutes": minutes, "average_heartrate": 120}],
    }


def test_training_weekly_trend_for_a_week_that_straddles_new_year_is_one_bucket():
    """`/api/training_overview` — the same contract on the workouts/minutes chart
    (the `site_api_training.py:565` instance)."""
    src = FakeSources(
        strava=[
            _strava("2026-12-31", 30.0),  # ISO 2026-W53
            _strava("2027-01-01", 20.0),  # ISO 2026-W53 — same week
            _strava("2027-01-05", 40.0),  # ISO 2027-W01
        ]
    )
    trend = _body(training.training_overview(_g=_make_g(src)))["weekly_trend"]
    assert [(t["week"], t["workouts"], t["minutes"]) for t in trend] == [
        ("2026-W53", 2, 50),  # 30 + 20
        ("2027-W01", 1, 40),
    ], f"the straddling week split into {trend}"


def _ah_breathwork(date: str, minutes: float) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#apple_health",
        "sk": f"DATE#{date}",
        "breathwork_minutes": minutes,
        "breathwork_sessions": 1,
    }


def test_breathwork_weekly_trend_for_a_week_that_straddles_new_year_is_one_bucket():
    """`/api/training_overview` — the breathwork chart (the
    `site_api_training.py:437` instance). Its window is 30 days, so both boundary
    dates are inside it from 2027-01-05."""
    src = FakeSources(
        apple_health=[
            _ah_breathwork("2026-12-31", 10.0),  # ISO 2026-W53
            _ah_breathwork("2027-01-01", 5.0),  # ISO 2026-W53 — same week
            _ah_breathwork("2027-01-05", 7.0),  # ISO 2027-W01
        ]
    )
    trend = _body(training.training_overview(_g=_make_g(src)))["breathwork"]["weekly_trend"]
    assert [(t["week"], t["sessions"], t["minutes"]) for t in trend] == [
        ("2026-W53", 2, 15.0),  # 10 + 5
        ("2027-W01", 1, 7.0),
    ], f"the straddling week split into {trend}"
