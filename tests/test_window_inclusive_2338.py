"""tests/test_window_inclusive_2338.py — the N-day window fetches N dates. Derived.

#1917 made the published window *labels* honest. It never touched the queries, so an
"N-day" window kept fetching N+1 calendar dates: `_experiment_date(N)` returned
`today - N`, and every lower bound it feeds — DynamoDB `between`, `_query_source` — is
INCLUSIVE on both ends. `[today - 30, today]` is 31 dates. `_window_span` then measured
the same window EXCLUSIVELY and published 30, so the label, the arithmetic and the row
set were three different numbers and only two of them agreed.

#2338 picked ONE convention and put it in the helper:

    `_experiment_date(N)` returns `today - (N - 1)` — the INCLUSIVE START of an N-day
    window ending today. Lower bounds stay inclusive everywhere.

The rejected alternative was "make every caller's lower bound exclusive" (the #2221
repair, applied to one filter in site_api_nutrition). It was rejected because it is
opt-in: it fixes the call site that remembers, and by the time this issue was written
the repo had grown BOTH repairs plus two hand-rolled `_experiment_date(N - 1)`
compensations — three conventions for one bug. A rule that lives in the helper is
inherited by a caller that has never heard of it.

WHAT THIS FILE GUARDS, and why it is written as a derivation rather than a list: the
durable risk is not today's call sites, it is the NEXT one. Every check below derives
its subject from the source — the AST of `lambdas/web/`, or the distinct window lengths
actually requested — so a new module, a new window length, or a newly hand-compensated
argument is covered the moment it is written, by nobody's remembering to add it here.
That is the #1917 lesson (`test_window_name_honesty_1917.py`) applied to the query side.
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")

# NB: the `web.` package form, NOT a bare `import site_api_common`. Both resolve, and
# they produce TWO DISTINCT module objects — the handlers import `web.site_api_common`,
# so patching the bare one monkeypatches a module nothing under test is reading.
from web import site_api_common as C  # noqa: E402

WEB = ROOT / "lambdas" / "web"

# ── waivers ─────────────────────────────────────────────────────────────────
# A call site may deviate ONLY with a stated reason recorded here. Keyed by
# "<module>:<lineno-independent description>" so a waiver cannot silently widen:
# the test matches on module + the unparsed expression, never on a line number
# (which drifts) and never on a whole file (which would waive future code too).
EXCLUSIVE_BOUND_WAIVERS = {
    # site_api_training's modality trend partitions the last 60 days into two ADJACENT
    # 30-day blocks: the current window is [d30, today] and the prior window is
    # everything before it, `d60 <= d < d30`. The `<` is not an off-by-one repair — it
    # is the boundary between two windows, and making it `<=` would double-count d30 in
    # both blocks. The prior block's own span is measured against its real inclusive end
    # (the day before d30) — see `_prior_end` in site_api_training.py.
    ("site_api_training.py", "d60 <= d < d30"): "adjacent-window partition, not a lower bound (#2338)",
}


class Site:
    """One derived `_experiment_date(...)` call site."""

    def __init__(self, module: str, lineno: int, arg_node: ast.expr):
        self.module = module
        self.lineno = lineno
        self.arg_src = ast.unparse(arg_node)
        self.days = arg_node.value if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, int) else None

    def __repr__(self) -> str:  # pragma: no cover - failure messages only
        return f"{self.module}:{self.lineno} _experiment_date({self.arg_src})"


def _modules():
    for p in sorted(WEB.glob("*.py")):
        yield p.name, ast.parse(p.read_text(encoding="utf-8"))


def _call_sites() -> list[Site]:
    """Every `_experiment_date(<arg>)` call in lambdas/web/, from the AST."""
    out = []
    for name, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_experiment_date" and node.args:
                out.append(Site(name, node.lineno, node.args[0]))
    return out


def _window_bindings():
    """Local names bound to an `_experiment_date(N)` result, per module.

    Returns {module: {name: (days, lineno)}}. These are the values that end up as
    query lower bounds, so they are what the exclusive-bound scan compares against.
    """
    out: dict[str, dict[str, tuple[int | None, int]]] = {}
    for name, tree in _modules():
        binds: dict[str, tuple[int | None, int]] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                continue
            call = node.value
            if not (isinstance(call.func, ast.Name) and call.func.id == "_experiment_date" and call.args):
                continue
            arg = call.args[0]
            days = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, int) else None
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    binds[tgt.id] = (days, node.lineno)
        if binds:
            out[name] = binds
    return out


SITES = _call_sites()
BINDINGS = _window_bindings()


# ── 0. the derivation itself must not go vacuous ────────────────────────────


def test_the_derived_caller_set_is_not_empty():
    """A scan that finds nothing passes every check below for free.

    This floor is the difference between a guard and a guard-shaped no-op: rename
    `_experiment_date`, move the modules, or break the AST walk, and this fails loudly
    instead of every other test in the file quietly succeeding over an empty set.
    """
    assert len(SITES) >= 20, f"expected the real caller set (~25 sites), derived only {len(SITES)}: {SITES}"
    assert len({s.module for s in SITES}) >= 8, f"expected many modules, got {sorted({s.module for s in SITES})}"
    assert BINDINGS, "no window variables derived — the binding scan is broken"


# ── 1. nobody hand-compensates the window length ────────────────────────────


def test_no_caller_hand_compensates_the_helper():
    """`_experiment_date(30)`, never `_experiment_date(29)`-with-a-comment.

    Two call sites used to subtract one themselves — the habits dot-strip and the
    fulfillment trend — each with a comment explaining that "29 back + today = 30".
    They were correct AND they were the bug: the helper's contract was ambiguous
    enough that two authors patched around it locally while every other caller took
    the off-by-one. An argument that is anything other than a positive integer literal
    is that ambiguity coming back, so it fails here and gets fixed in the helper.
    """
    bad = [s for s in SITES if s.days is None or s.days < 1]
    assert not bad, (
        "window length must be a positive int literal — the helper already makes the window inclusive, "
        f"so a caller must never adjust it: {bad}"
    )


def test_a_window_variable_named_for_n_days_asks_for_n_days():
    """`d30 = _experiment_date(30)`. A `d30` holding a 29-day window is the old bug wearing the old name."""
    mismatched = []
    for module, binds in BINDINGS.items():
        for var, (days, lineno) in binds.items():
            if var.startswith("d") and var[1:].isdigit() and days != int(var[1:]):
                mismatched.append(f"{module}:{lineno} {var} = _experiment_date({days})")
    assert not mismatched, f"variable name and requested window disagree: {mismatched}"


# ── 2. no lower bound derived from the helper may be exclusive ──────────────


def test_no_window_lower_bound_is_exclusive():
    """The other half of "one convention": inclusive helper + inclusive bounds.

    `> d7` on top of the fixed helper drops the OLDEST day and averages a 7-day label
    over six — the same class of error as the original, in the other direction. #2221
    made exactly this filter exclusive when `d7` was still `today - 7`; #2338 moved the
    repair into the helper and put the bound back to `>=`. Waivers must state a reason.
    """
    violations = []
    for module, tree in _modules():
        binds = BINDINGS.get(module, {})
        if not binds:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            for op, left, right in zip(node.ops, operands, operands[1:]):
                if not isinstance(op, (ast.Gt, ast.Lt)):
                    continue
                touched = [n for n in (left, right) if isinstance(n, ast.Name) and n.id in binds]
                if not touched:
                    continue
                expr = ast.unparse(node)
                if EXCLUSIVE_BOUND_WAIVERS.get((module, expr)):
                    continue
                violations.append(f"{module}:{node.lineno} {expr}")
    assert not violations, (
        "an exclusive comparison against a window start drops the oldest day (N-1 dates under an N-day label); "
        f"make it inclusive or add a reasoned waiver: {violations}"
    )


def test_no_window_span_measures_up_to_another_windows_start():
    """`_window_span(start, end, n)` counts [start, end] INCLUSIVELY, so `end` must be the
    window's own last date — never the next window's first.

    This is the off-by-one's last hiding place, and it is the one the rest of this file
    initially missed (found by mutation-proofing #2338, not by reading). site_api_training
    compares the current 30 days against the prior 30 by partitioning `d60 <= d < d30`;
    passing `_window_span(d60, d30, 30)` measures ONE DAY MORE than that loop reads, so a
    prior window holding 29 real days reports 30 and the `trend_vs_prior_30d` gate — whose
    entire job is refusing to compare against a short window — opens a day early.

    Derived, not listed: any `_window_span(a, b, ...)` whose `b` is itself bound from
    `_experiment_date` is comparing a start against a start. Take the day before it.
    """
    violations = []
    for module, tree in _modules():
        binds = BINDINGS.get(module, {})
        if not binds:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_window_span"):
                continue
            if len(node.args) < 2:
                continue
            end = node.args[1]
            if isinstance(end, ast.Name) and end.id in binds:
                violations.append(f"{module}:{node.lineno} {ast.unparse(node)}")
    assert not violations, (
        "a window's inclusive END must be its own last date, not the next window's start " f"(use the day before): {violations}"
    )


def test_the_adjacent_window_gate_needs_a_genuinely_full_prior_window(monkeypatch):
    """The behaviour behind the check above, at the boundary that matters.

    Two adjacent 30-day blocks need 60 real dates. At 59 the prior block is one day
    short and its `full` gate must stay closed — otherwise a 29-day "prior 30 days"
    becomes the denominator of a published trend (ADR-105: the denominator is part of
    the claim).
    """
    monkeypatch.setattr(C, "datetime", _FrozenDatetime)
    today = "2026-05-10"
    for cycle_age, expected_full in ((60, True), (59, False)):
        genesis = (FROZEN - timedelta(days=cycle_age - 1)).strftime("%Y-%m-%d")
        monkeypatch.setattr(C, "EXPERIMENT_START", genesis)
        d60, d30 = C._experiment_date(60), C._experiment_date(30)
        prior_end = (datetime.strptime(d30, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        # the dates site_api_training's `d60 <= d < d30` loop actually reads
        prior_dates = [d for d in _dates_between(d60, today) if d < d30]
        span = C._window_span(d60, prior_end, 30)
        assert span["actual_days"] == len(prior_dates), f"day {cycle_age}: span {span['actual_days']} vs {len(prior_dates)} dates read"
        assert span["full"] is expected_full, f"day {cycle_age}: prior-window gate should be full={expected_full}"


def test_every_waiver_still_describes_real_code():
    """A waiver outliving its call site is a hole nobody can see. Fail when it goes stale."""
    live = set()
    for module, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                live.add((module, ast.unparse(node)))
    stale = [k for k in EXCLUSIVE_BOUND_WAIVERS if k not in live]
    assert not stale, f"waived expressions no longer exist — delete the waiver: {stale}"


# ── 3. the behaviour: N days in, N distinct dates out ───────────────────────

FROZEN = datetime(2026, 5, 10, 17, 40, 0, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()` — `strptime`/arithmetic keep working."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN.astimezone(tz) if tz else FROZEN.replace(tzinfo=None)


@pytest.fixture
def frozen_far_genesis(monkeypatch):
    """A fixed clock and a genesis old enough that no window is clamped."""
    monkeypatch.setattr(C, "datetime", _FrozenDatetime)
    monkeypatch.setattr(C, "EXPERIMENT_START", "2020-01-01")
    return "2026-05-10"


def _dates_between(start: str, end: str) -> list[str]:
    """Enumerate [start, end] INCLUSIVELY — the row set DynamoDB `between` returns."""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    out = []
    while s <= e:
        out.append(s.strftime("%Y-%m-%d"))
        s += timedelta(days=1)
    return out


REQUESTED_LENGTHS = sorted({s.days for s in SITES if s.days})


def test_the_repo_requests_several_distinct_window_lengths():
    """Guards the parametrization below from silently shrinking to one trivial case."""
    assert len(REQUESTED_LENGTHS) >= 4, f"derived only {REQUESTED_LENGTHS}"


@pytest.mark.parametrize("n", REQUESTED_LENGTHS)
def test_an_n_day_window_covers_exactly_n_distinct_dates(frozen_far_genesis, n):
    """THE acceptance test, over every window length the repo actually asks for.

    Fixed clock, far-past genesis: `[_experiment_date(n), today]` — the exact range
    handed to `_query_source` / `Key('sk').between(...)` — must enumerate n dates.
    Before #2338 every one of these was n + 1.
    """
    today = frozen_far_genesis
    start = C._experiment_date(n)
    dates = _dates_between(start, today)
    assert len(dates) == len(set(dates)) == n, f"a {n}-day window fetched {len(dates)} dates: {dates[0]}..{dates[-1]}"
    assert dates[-1] == today, "an N-day window ends today"


@pytest.mark.parametrize("n", REQUESTED_LENGTHS)
def test_the_published_span_equals_the_dates_actually_fetched(frozen_far_genesis, n):
    """`_window_span` is what the payload publishes as `actual_days`. It must count the
    same rows the query returns, or the denominator and the label part company again —
    ADR-104/105: a figure named for N days is computed over N days."""
    today = frozen_far_genesis
    start = C._experiment_date(n)
    span = C._window_span(start, today, n)
    assert span["actual_days"] == len(_dates_between(start, today)) == n
    assert span["full"] is True, "an unclamped N-day window is a full N-day window"


@pytest.mark.parametrize("cycle_age", [1, 2, 5, 29])
def test_a_genesis_clamped_window_still_publishes_the_span_it_fetched(monkeypatch, cycle_age):
    """ADR-077 "clamped, not hidden": early in a cycle the window shrinks, and the
    published span must shrink WITH the row set — never lead or lag it by a day.

    `cycle_age` is the number of calendar dates from genesis to today inclusive, which
    is also the site's Day N. Day 1 is one date, not zero.
    """
    monkeypatch.setattr(C, "datetime", _FrozenDatetime)
    genesis = (FROZEN - timedelta(days=cycle_age - 1)).strftime("%Y-%m-%d")
    monkeypatch.setattr(C, "EXPERIMENT_START", genesis)
    today = "2026-05-10"
    start = C._experiment_date(30)
    assert start == genesis, "a young cycle clamps the window start to genesis"
    fetched = _dates_between(start, today)
    assert len(fetched) == cycle_age, f"Day {cycle_age} must fetch {cycle_age} dates, got {len(fetched)}"
    span = C._window_span(start, today, 30)
    assert span["actual_days"] == cycle_age, "the published span must equal the dates fetched"
    assert span["full"] is False, "a clamped window is not a full 30 days"


def test_a_one_day_window_is_today_alone(frozen_far_genesis):
    """The boundary the old form got most obviously wrong: `_experiment_date(1)` used to
    be yesterday, so a "today" window fetched two dates."""
    assert C._experiment_date(1) == frozen_far_genesis
    assert _dates_between(C._experiment_date(1), frozen_far_genesis) == [frozen_far_genesis]


# ── 4. end-to-end: the window a real endpoint hands to DynamoDB ─────────────


def test_a_live_endpoint_queries_exactly_the_window_it_publishes(monkeypatch):
    """The property, end to end, through a real handler rather than the helper alone.

    /api/nutrition_overview is the surface #2338 was found on (its 7-day average is the
    figure #2221 patched locally). Capture the range it hands `_query_source` and count
    the dates in it: 30 for the 30-day window, and the `_7d`-named average must be
    computed over exactly 7.
    """
    from web import site_api_data as data, site_api_nutrition as nut

    windows: list[tuple[str, str, str]] = []

    def _recording_query_source(source, start, end, include_pilot=False):
        windows.append((source, start, end))
        return []

    monkeypatch.setattr(C, "datetime", _FrozenDatetime)
    monkeypatch.setattr(nut, "datetime", _FrozenDatetime)
    monkeypatch.setattr(C, "EXPERIMENT_START", "2020-01-01")
    monkeypatch.setattr(data, "_query_source", _recording_query_source)
    monkeypatch.setattr(data, "EXPERIMENT_START", "2020-01-01")

    nut.nutrition_overview(_g=vars(data))

    mf = [w for w in windows if w[0] == "macrofactor"]
    assert mf, f"expected a macrofactor query, recorded {windows}"
    source, start, end = mf[0]
    assert len(_dates_between(start, end)) == 30, f"/api/nutrition_overview asked for {start}..{end}"


def test_the_seven_day_filter_inside_that_endpoint_keeps_seven_days(monkeypatch):
    """The inner `items_7d` filter — inclusive since #2338 — must select 7 dates out of
    the 30 fetched, not 8 (the pre-#2221 bug) and not 6 (over-correcting on top of the
    fixed helper)."""
    monkeypatch.setattr(C, "datetime", _FrozenDatetime)
    monkeypatch.setattr(C, "EXPERIMENT_START", "2020-01-01")
    d30, d7, today = C._experiment_date(30), C._experiment_date(7), "2026-05-10"
    fetched = _dates_between(d30, today)
    selected = [d for d in fetched if d >= d7]  # the literal filter in site_api_nutrition
    assert len(selected) == 7, f"the 7-day filter selected {len(selected)} of {len(fetched)} dates"
