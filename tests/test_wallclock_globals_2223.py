"""tests/test_wallclock_globals_2223.py — #2223 guard: no NEW module-level
wall-clock global in tests/*.py.

THE DEFECT. Four tests red `main` once a night: two test files sampled the
live clock ONCE, at IMPORT time (`_NOW = datetime.now(...)` / `_TODAY =
datetime.now(...).strftime(...)`), to build every fixture date, while the
handlers under test read the SAME kind of clock again at CALL time. pytest
imports every test module up front at collection, then runs them — minutes
can separate the two reads on a big suite. A run whose EXECUTION crosses a
day boundary after COLLECTION desyncs them: fixtures built as "Day 5" get
asserted against a handler that has already ticked to "Day 6". This fired
verbatim on `main` (CI run 31244919499, commit 520a7c12, 2026-08-08 —
job started 06:56Z = 23:56 PDT, the four failing tests ran 07:00-07:02Z =
00:00-00:02 PDT, `EXPERIMENT_START_DATE=2026-08-03` made that literally
`assert 6 == 5`).

THE FIX PATTERN (see tests/test_window_name_honesty_1917.py,
tests/test_routine_endpoint.py, tests/test_honest_read_guards_1084.py,
tests/test_inference_receipt_batching.py): replace the live `.now()` read
with a FIXED literal instant, and freeze the handler module's own `datetime`
name — an autouse `monkeypatch.setattr(<handler module>, "datetime",
_FrozenDateTime)`, the pattern already proven in
tests/test_home_og_day_frame_1955.py and tests/test_site_api_meals_behavior.py
— to that SAME instant, so fixture-build time and handler call-time can never
disagree regardless of the real wall clock.

WHY A DERIVED GUARD. An AST sweep for this shape found FIVE files, not the
two that had actually fired: the other three "looked" safe on a first read
and needed the actual call graph traced to tell which of them were real bugs
merely waiting for an unlucky CI run (two were: test_honest_read_guards_1084.py
and test_inference_receipt_batching.py each feed a live handler clock that
disagrees with their import-time fixture) versus genuinely inert
(test_budget_headroom.py's `_NOW` only ever feeds an ELAPSED-SECONDS
comparison, never a calendar-day identity claim). A reviewer who fixed the two
visibly red files and stopped would leave real bugs for the next multi-minute
CI run to find — the exact "guard the SET, not the instance" failure shape
this repo keeps hitting. So this file does not enumerate the fix; it
AST-scans `tests/*.py` for every module-level assignment whose value calls
`.now()`/`.today()`/`.utcnow()` and requires each to be justified in
ALLOWED_WALLCLOCK_GLOBALS below, with the actual invariant that makes it safe
— not just an assertion that it is.

Deliberately NON-recursive over each file's top-level statements only
(`tree.body`, not `ast.walk(tree)`): a `.now()` read inside a test FUNCTION
happens at call time, alongside whatever the handler itself reads, and is not
this bug class.
"""

import ast
import pathlib

# "filename:varname" -> the load-bearing reason a module-level wall-clock read
# here cannot desync from a handler's call-time clock the way #2223 did.
ALLOWED_WALLCLOCK_GLOBALS = {
    "test_budget_headroom.py:_NOW": (
        "elapsed-SECONDS arithmetic only (budget_guard.read_breakdown: "
        "`datetime.now(utc) - computed_at > max_age_s`, a 48h threshold with "
        ">=1h margin in every test in this file), never a calendar-day IDENTITY "
        "comparison — the gap between this import-time read and the live "
        "call-time read inside read_breakdown() is bounded by the test's own "
        "wall-clock runtime (milliseconds), which cannot approach an hour, let "
        "alone 48."
    ),
}

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_WALLCLOCK_METHODS = {"now", "today", "utcnow"}


def _scan_wallclock_globals(root: pathlib.Path) -> dict[str, list[int]]:
    """Every module-level assignment in `root`/*.py whose value calls
    `.now()`/`.today()`/`.utcnow()` anywhere in its expression tree (so a
    chained call like `datetime.now(tz).strftime(...)` — the exact shape that
    fired in tests/test_routine_endpoint.py — is still caught, not just a bare
    `x = datetime.now()`) — keyed "filename:varname" -> the line number(s) it
    was assigned on.
    """
    found: dict[str, list[int]] = {}
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:  # top level ONLY — see module docstring
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            hits = [
                n
                for n in ast.walk(value)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _WALLCLOCK_METHODS
            ]
            if not hits:
                continue
            for t in targets:
                names = [t.id] if isinstance(t, ast.Name) else [e.id for e in getattr(t, "elts", []) if isinstance(e, ast.Name)]
                for name in names:
                    found.setdefault(f"{path.name}:{name}", []).append(node.lineno)
    return found


def test_no_unregistered_module_level_wallclock_global():
    """A new import-time `.now()`/`.today()`/`.utcnow()` fixture must be
    justified here or frozen at the source — see the module docstring."""
    found = _scan_wallclock_globals(_TESTS_DIR)
    unregistered = {k: v for k, v in found.items() if k not in ALLOWED_WALLCLOCK_GLOBALS}
    assert not unregistered, (
        "Module-level wall-clock global(s) in tests/*.py, sampled once at IMPORT "
        "time. If the handler under test reads its OWN clock again at call time, "
        "a CI run whose execution crosses a day boundary after collection will "
        "desync the two (#2223). Either freeze the handler's clock to the SAME "
        "fixed instant (see tests/test_window_name_honesty_1917.py) or add a "
        "justified entry to ALLOWED_WALLCLOCK_GLOBALS in this file:\n"
        + "\n".join(f"  {k}  (line {v})" for k, v in sorted(unregistered.items()))
    )


def test_allowlist_has_no_dead_entries():
    """Keep the allowlist derived — an entry for a fixture that was since
    fixed or deleted is a stale exemption, not a real one."""
    found = _scan_wallclock_globals(_TESTS_DIR)
    dead = sorted(k for k in ALLOWED_WALLCLOCK_GLOBALS if k not in found)
    assert not dead, f"ALLOWED_WALLCLOCK_GLOBALS lists entr(y/ies) no longer present in tests/*.py; delete them: {dead}"


def test_scanner_fires_on_an_injected_module_level_now(tmp_path):
    """Negative test: prove the scan catches an injected fixture — without
    this, a scanner that silently matched nothing would pass every assertion
    above (the #1908 failure shape: a green nobody earned)."""
    (tmp_path / "test_injected_scratch.py").write_text("from datetime import datetime\n\n_INJECTED_NOW = datetime.now()\n")
    found = _scan_wallclock_globals(tmp_path)
    assert "test_injected_scratch.py:_INJECTED_NOW" in found

    # A chained call (the test_routine_endpoint.py shape: `.now(...).strftime(...)`)
    # must also be caught — matching only the OUTERMOST call would miss it.
    (tmp_path / "test_injected_chained.py").write_text("from datetime import datetime\n\n_TODAY = datetime.now().strftime('%Y-%m-%d')\n")
    assert "test_injected_chained.py:_TODAY" in _scan_wallclock_globals(tmp_path)

    # ...and a CALL-TIME read inside a function (not the bug class) is ignored.
    (tmp_path / "test_injected_calltime.py").write_text(
        "from datetime import datetime\n\n\ndef f():\n    x = datetime.now()\n    return x\n"
    )
    assert not any(k.startswith("test_injected_calltime.py:") for k in _scan_wallclock_globals(tmp_path))
