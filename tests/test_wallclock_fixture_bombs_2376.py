"""tests/test_wallclock_fixture_bombs_2376.py — #2376 guard: the wall-clock
TIME-BOMB class (dated fixture literal + unfrozen handler clock) gets its
structural gate.

THE DEFECT CLASS. A behaviour test seeds fixture rows at FIXED calendar dates
("2026-08-07", `datetime(2026, 8, 8, ...)`) and then drives a handler that
derives "today" from the REAL clock at call time. The two agree on exactly the
day the test was written and desync at the next UTC midnight: the test reds on
`main` with nobody having touched it. This detonated in-window —
tests/test_pipeline_health_check_behavior.py went red at 2026-08-09T00:00Z
(fixed per-instance in 8e0b002c), and its two sibling tests were green only by
accident (they asserted rows MISSING, which a date mismatch also produces).

WHY THE SIBLING SWEEP CANNOT SEE IT. tests/test_wallclock_globals_2223.py
guards the INVERSE shape — a live `.now()` read sampled once at import time —
and is deliberately non-recursive over module top-level statements. This class
has NO import-time clock read at all: the fixture side is a dead literal and
the live read is inside the handler. Hence this side-car, not a fork:
same allowlist-with-reasons idiom, same tests/ sweep, the complementary
predicate.

WHAT IS FLAGGED. A tests/*.py file that combines ALL THREE of:
  (a) a CLOCK-CLAIMING dated fixture — an assignment (module or function
      scope) binding an ISO-dated literal or a `datetime(YYYY, M, D, ...)`
      constructor to a name whose tokens claim clock agreement (TODAY,
      YESTERDAY, NOW, ...). Naming a fixed date "today" is the bomb's
      signature: it asserts that day IS the day the handler will derive at
      call time. Names used ONLY as direct call arguments are skipped — that
      is the dependency-injection anti-bomb pattern, not the bomb;
  (b) an import that resolves to a source module (lambdas/**, mcp/*) whose text
      reads a wall clock (`.now(` / `.today(` / `.utcnow(`); and
  (c) NO clock-control idiom anywhere in the file — no
      `monkeypatch.setattr(<mod>, "<clock name>", ...)`, no frozen-datetime
      subclass, no freeze fixture/class (anything named frozen/freeze), no
      freezegun.

KNOWN RECALL LIMIT, accepted deliberately: a bomb that names its fixed date
something neutral (`D1 = "2026-08-07"`) is invisible to (a). The first sweep
of this predicate over the FULL literal population returned 183 files — an
allowlist nobody would maintain honestly — while the clock-claiming form
returned 17, every real historical instance among them. A gate people trust
at 17 beats a gate people rubber-stamp at 183.

THE FIX PATTERN, when a hit is a real bomb: freeze the handler module's own
`datetime` name to an instant DERIVED from the fixture constant (see
`frozen_handler_clock` in tests/test_pipeline_health_check_behavior.py — the
8e0b002c fix is the exemplar: the freeze reads its date FROM the TODAY constant
rather than repeating it, because two literals that must agree is exactly how
this drifts back into a bomb).

FALSE POSITIVES ARE EXPECTED and are the point of the allowlist: a dated
literal that is a HISTORICAL pin (a golden transcript, a sealed prereg date, a
regression fixture for a specific past day) can legitimately meet (a)+(b) when
the handler's clock read sits on a code path the test never exercises, or when
the assertion is not a calendar-day identity claim. Each such file gets a named
entry in EXEMPT_DATED_FIXTURE_FILES below with the load-bearing reason it
cannot desync — not just an assertion that it is safe. An exemption is
file-scoped: adding a NEW genuinely-bomb-shaped test to an exempted file will
not be caught, so keep reasons specific enough that a future reader can tell
when they've broken the invariant.
"""

import ast
import pathlib
import re

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_REPO = _TESTS_DIR.parent
_LAMBDAS = _REPO / "lambdas"

# "filename" -> the load-bearing reason its dated literals cannot desync from
# the handler's call-time clock the way #2354 did. Every entry below was
# verified by reading the call sites on 2026-08-09: in each, the pinned date is
# INJECTED into the function under test (an explicit today=/now=/window
# argument the handler honours), so fixture rows and the handler's notion of
# "today" derive from the same constant and cannot disagree at UTC midnight.
# The scanner already skips names used ONLY as direct call arguments; these
# files also use the constant for date arithmetic / row-building / assertion
# text, which is what keeps them in the scan.
EXEMPT_DATED_FIXTURE_FILES: dict[str, str] = {
    "test_quiet_behavioral_notice_2326.py": (
        "every scan_quiet_behavioral_sources call receives _TODAY explicitly as an "
        "argument — the module under test takes today as a parameter and consults no "
        "call-time clock on any asserted path; freshness_checker_lambda is imported "
        "only for set-membership asserts (SOURCES/BEHAVIORAL_SOURCES) and a "
        "count_infra_stale call on a literal list, never its handler"
    ),
    "test_anomaly_detector_lambda.py": (
        "check_anomalies(yesterday, today) takes BOTH days as arguments (_run_check "
        "passes YESTERDAY straight through and derives today as yesterday+1); the "
        "fixture rows and the queried day co-derive from the same module constants, "
        "so no call-time clock is consulted on the asserted path."
    ),
    "test_business_logic.py": (
        "compute_tsb(records, today) is a pure function of its arguments; the local "
        "`today = date(2026, 3, 14)` builds the records AND is passed in as the "
        "as-of day, so both sides move together and the wall clock is never read."
    ),
    "test_daily_insight_changepoints.py": (
        "_compute_changepoints(yesterday.isoformat(), ...) receives its day "
        "explicitly; the same local `yesterday` builds the fetched series, and "
        "fetch_range is stubbed — nothing on the path derives a day from now()."
    ),
    "test_genesis_blind_brief_windows_2089.py": (
        "every call passes explicit windows or _TODAY (fetch_range(*_win(n)), "
        "compute_tsb(..., _TODAY)); the module docstring pins this as a contract — "
        "'Every date here is PINNED; nothing does' [wall-clock reads] — and no "
        "lambda_handler-style self-clocked entrypoint is driven."
    ),
    "test_hae_datatype_liveness_468.py": (
        "compute_datatype_liveness/check_apple_health_datatypes/alert_episode_decision "
        "all take NOW as an explicit argument; age_days assertions compare fixture "
        "dates against that injected instant, never against the live clock."
    ),
    "test_notion_journal_dark_1480.py": (
        "check_notion_journal_staleness(table, NOW, ...) takes its clock as an "
        "argument; NOW.date() arithmetic builds the fixture sk dates from the same "
        "injected instant."
    ),
    "test_prediction_metadata_stamp_725.py": (
        "stamp_thread_predictions(..., today=TODAY) — the handler's signature is "
        "`today: str = None` with `today = today or datetime.now(...)`, so the "
        "injected value wins and the now() fallback is never taken in these tests."
    ),
    "test_qa_archive.py": (
        "build_key/build_body/archive_text all take now=NOW explicitly; the "
        "remaining NOW uses are assertions on the injected instant's own "
        "isoformat/serialization, not calendar claims against a live clock."
    ),
    "test_subscriber_retention_sweep.py": (
        "retention_cutoff_iso(now) is a pure function of its argument; the local "
        "`now` exists only to compute the expected value of that same call."
    ),
}

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_HANDLER_CLOCK_RE = re.compile(r"\.(now|today|utcnow)\s*\(")

# Any of these anywhere in a test file counts as clock CONTROL: the author has
# reached for the handler's clock, so the file is out of the "unfrozen" class.
# Deliberately lenient (file-scoped, substring-level) — this gate hunts files
# with NO clock discipline at all; per-function scoping would triple the cost
# for marginal precision.
_CLOCK_CONTROL_RES = (
    # monkeypatch.setattr(mod, "datetime", ...) and every attr-name variant the
    # repo's freeze idioms use (datetime/date/now/today/utcnow/clock/time).
    re.compile(r"""setattr\([^)]*,\s*["'][^"']*(datetime|date|now|today|utcnow|clock|time)[^"']*["']"""),
    re.compile(r"[Ff]rozen|[Ff]reeze"),  # _FrozenDatetime, frozen_handler_clock, freeze_time
    re.compile(r"freezegun"),
)


# Names that CLAIM clock agreement. A literal date bound to one of these is the
# bomb's signature: the test is asserting "this fixed day IS the day the handler
# will derive at call time" — true on the day it was written, false at the next
# UTC midnight. A golden/historical pin named for what it is (GOLDEN_DAY,
# SEALED_ON, _AUG_7) makes no such claim and is not flagged.
_CLOCK_CLAIMING_TOKENS = frozenset({"TODAY", "YESTERDAY", "TOMORROW", "NOW", "TONIGHT"})


def _is_dated_value(value: ast.AST) -> bool:
    """A whitespace-free string containing an ISO date ("2026-08-07",
    "DATE#2026-08-07"), or a datetime/date constructor with literal int
    year/month/day — anywhere in the assigned expression tree, so
    `datetime(2026, 8, 8, tzinfo=utc).strftime(...)` still counts."""
    for node in ast.walk(value):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _ISO_DATE_RE.search(node.value) and not re.search(r"\s", node.value):
                return True
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if name in ("datetime", "date") and len(node.args) >= 3:
                first_three = node.args[:3]
                if all(isinstance(a, ast.Constant) and isinstance(a.value, int) for a in first_three) and 1900 < node.args[0].value < 2100:
                    return True
    return False


def _only_ever_injected(tree: ast.AST, name: str) -> bool:
    """True when every LOAD of `name` is a direct call argument — the
    dependency-injection anti-bomb pattern (`compute_tsb(records, today)`,
    `next_chronicle_draft_date(now)`): the test hands the handler its clock
    instead of hoping the handler's own clock agrees. Any other use — an
    f-string, a dict value, date arithmetic, an assert operand — keeps the
    name in play, because that is how the detonated file used YESTERDAY (to
    build fixture rows a self-clocked handler then dated differently)."""
    loads = injected = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, ast.Name) and arg.id == name:
                    arg._direct_arg = True  # type: ignore[attr-defined]
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
            loads += 1
            injected += getattr(node, "_direct_arg", False)
    return loads > 0 and loads == injected


def _clock_claiming_dated_names(tree: ast.AST) -> list[str]:
    """(a): every assignment — module OR function scope — binding a dated
    literal to a name whose underscore-tokens claim the clock (TODAY,
    YESTERDAY, NOW, ...), excluding names that are only ever INJECTED into
    calls. Returns "name@line" for the triage message."""
    hits: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        names = []
        for t in targets:
            names += [t.id] if isinstance(t, ast.Name) else [e.id for e in getattr(t, "elts", []) if isinstance(e, ast.Name)]
        claiming = [n for n in names if _CLOCK_CLAIMING_TOKENS & set(n.upper().split("_"))]
        if claiming and _is_dated_value(value):
            for n in claiming:
                if n not in seen and not _only_ever_injected(tree, n):
                    seen.add(n)
                    hits.append(f"{n}@{node.lineno}")
    return hits


def _imported_source_files(tree: ast.AST) -> set[pathlib.Path]:
    """(b), first half: every import in the test that resolves to a repo source
    module. Handles the three import styles the suite uses: dotted package
    (`from operational import x`, `from web.site_api_common import y`,
    `import mcp.tools_health`), and flat legacy names (`import whoop_lambda`),
    which conftest.py's sys.path shims resolve from any lambdas/ subpackage."""
    out: set[pathlib.Path] = set()

    def _resolve(dotted: str) -> None:
        rel = dotted.replace(".", "/")
        for base in (_LAMBDAS, _REPO):
            p = base / f"{rel}.py"
            if p.is_file():
                out.add(p)
                return
        if "." not in dotted:  # flat legacy name — search the subpackages
            out.update(_LAMBDAS.glob(f"*/{dotted}.py"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _resolve(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            _resolve(node.module)
            for alias in node.names:  # `from operational import pipeline_health_check_lambda`
                _resolve(f"{node.module}.{alias.name}")
    return out


_CLOCK_VERDICT_CACHE: dict[pathlib.Path, bool] = {}


def _module_reads_wall_clock(path: pathlib.Path) -> bool:
    """(b), second half: does the resolved source module read a wall clock?"""
    if path not in _CLOCK_VERDICT_CACHE:
        _CLOCK_VERDICT_CACHE[path] = bool(_HANDLER_CLOCK_RE.search(path.read_text()))
    return _CLOCK_VERDICT_CACHE[path]


def _scan_fixture_bombs(root: pathlib.Path) -> dict[str, list[str]]:
    """Every tests/*.py in `root` matching (a) AND (b) AND (c) — keyed filename
    -> the clock-reading source modules it drives (repo-relative), for the
    triage message."""
    found: dict[str, list[str]] = {}
    for path in sorted(root.glob("test_*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        src = path.read_text()
        if any(rx.search(src) for rx in _CLOCK_CONTROL_RES):
            continue  # (c) fails — the file controls a clock somewhere
        tree = ast.parse(src, filename=str(path))
        claiming = _clock_claiming_dated_names(tree)
        if not claiming:
            continue
        clocked = sorted(str(p.relative_to(_REPO)) for p in _imported_source_files(tree) if _module_reads_wall_clock(p))
        if clocked:
            found[path.name] = [f"binds {', '.join(claiming)}; drives {m}" for m in clocked]
    return found


def test_no_unfrozen_dated_fixture_against_a_handler_clock():
    """A dated fixture literal driven at a clock-reading handler needs a
    frozen-clock idiom or a justified exemption — see the module docstring."""
    found = _scan_fixture_bombs(_TESTS_DIR)
    unregistered = {k: v for k, v in found.items() if k not in EXEMPT_DATED_FIXTURE_FILES}
    assert not unregistered, (
        "Test file(s) seed dated fixture literals against a handler that reads its own\n"
        "wall clock, with no frozen-clock idiom anywhere in the file. This is the class\n"
        "that red-mained main at 2026-08-09T00:00Z (#2354): green all the day it was\n"
        "written, red at the next UTC midnight. Either freeze the handler's clock to an\n"
        "instant DERIVED from the fixture constant (see frozen_handler_clock in\n"
        "tests/test_pipeline_health_check_behavior.py) or add a justified entry to\n"
        "EXEMPT_DATED_FIXTURE_FILES in tests/test_wallclock_fixture_bombs_2376.py:\n"
        + "\n".join(f"  {k}  -> drives {', '.join(v)}" for k, v in sorted(unregistered.items()))
    )


def test_exemptions_have_no_dead_entries():
    """Keep the exemption list derived — an entry for a file that was since
    frozen, fixed or deleted is a stale exemption, not a real one."""
    found = _scan_fixture_bombs(_TESTS_DIR)
    dead = sorted(k for k in EXEMPT_DATED_FIXTURE_FILES if k not in found)
    assert not dead, f"EXEMPT_DATED_FIXTURE_FILES lists file(s) the scan no longer flags; delete them: {dead}"


def test_scanner_fires_on_a_synthetic_bomb(tmp_path):
    """Mutation proof: a synthetic dated-fixture-unfrozen-clock file is caught
    — without this, a scanner that silently matched nothing would green every
    assertion above (the #1908 failure shape: a green nobody earned). The
    synthetic file imports the REAL detonated handler, so the import-resolution
    and clock-read halves are exercised end-to-end, not stubbed."""
    bomb = (
        "from operational import pipeline_health_check_lambda as phc\n"
        "\n"
        "YESTERDAY = '2026-08-07'\n"
        "\n"
        "def test_something():\n"
        "    assert phc is not None\n"
    )
    (tmp_path / "test_injected_bomb.py").write_text(bomb)
    found = _scan_fixture_bombs(tmp_path)
    assert "test_injected_bomb.py" in found
    assert any("pipeline_health_check_lambda" in m for m in found["test_injected_bomb.py"])

    # The SAME file with the repo's freeze idiom present must NOT be flagged —
    # otherwise the gate punishes the fix pattern it prescribes.
    (tmp_path / "test_injected_bomb.py").write_text(
        bomb + "\n\ndef test_frozen(monkeypatch):\n    monkeypatch.setattr(phc, 'datetime', object)\n"
    )
    assert "test_injected_bomb.py" not in _scan_fixture_bombs(tmp_path)

    # A dated literal with NO handler import (a pure-fixture golden) is not
    # this class and must not be flagged.
    (tmp_path / "test_injected_golden.py").write_text("GOLDEN_DAY = '2025-01-01'\n\n\ndef test_g():\n    assert GOLDEN_DAY\n")
    assert "test_injected_golden.py" not in _scan_fixture_bombs(tmp_path)

    # A datetime(...) CONSTRUCTOR fixture (the NOW = datetime(2026, 8, 8, ...)
    # shape from the detonated file) is a dated literal too.
    (tmp_path / "test_injected_ctor.py").write_text(
        "from datetime import datetime, timezone\n"
        "from operational import pipeline_health_check_lambda as phc\n"
        "\n"
        "NOW = datetime(2026, 8, 8, 16, 58, tzinfo=timezone.utc)\n"
        "\n"
        "def test_c():\n    assert phc and NOW\n"
    )
    assert "test_injected_ctor.py" in _scan_fixture_bombs(tmp_path)
