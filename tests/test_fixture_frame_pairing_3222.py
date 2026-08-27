"""tests/test_fixture_frame_pairing_3222.py — the FIXTURE half of the PT-day contract (#3222, epic #2798).

THE RULE, STATED ONCE
─────────────────────
**A fixture computes its expectation on the handler's own clock.** Not "never UTC" — the
platform has genuinely-UTC handlers (a vendor deadline, a billing month, an API window)
and a UTC fixture against one of those is *correct*. The defect is a fixture and a
handler that disagree about what day it is.

WHAT WENT WRONG (#3206 → #3222)
───────────────────────────────
#3206 moved `permanence_lambda` and `data_reconciliation_lambda` to `pacific_today()`
and left their fixtures on `datetime.now(timezone.utc).date()`. Between 17:00 PT and PT
midnight the UTC date has rolled and the Pacific one has not, so every expectation sat
one day ahead of the handler: `tests/test_permanence_lambda_1400.py` and
`tests/test_data_reconciliation_behavior.py` failed **7 hours of every 24**. #3223 fixed
those two. This file exists so the *class* cannot re-enter — and the class is real:
`_days_ago`'s docstring in the permanence test spent paragraphs explaining why a
hard-coded date is a time bomb, and then read the wrong clock.

**It shipped green because a time-dependent gate ran outside its own failure window.**
#3206's CI ran ~13:00 PT, where UTC and Pacific agree, so its own suite could not see
its own bug; `main` went red 24 hours later on unrelated work. A gate that only ever
runs where it cannot fail is not a gate. See `test_the_pt_evening_window_is_exercised`
at the bottom: this file pins the window with a **frozen clock**, not with wall time, so
the 17:00-PT-to-midnight case is exercised on every run at every hour.

ONE MATCHER, NOT A SECOND COPY
──────────────────────────────
The day-semantics classification is IMPORTED from
`tests/test_utc_day_fleet_ratchet_2811.py` (which imports its predicates in turn from
`tests/test_pacific_today_guard_2414.py` — `_clock_returning_functions`, `_taint_index`
and friends). Nothing here re-implements "is this a UTC day". A forked classifier that
drifts from the original is exactly how #3212 happened; the fork *is* the bug.

This file adds two things the matcher does not have, both DERIVED, never hand-listed:

  1. `pt_clock_modules()` — every module under `lambdas/` or `mcp/` that asks a clock
     "what Pacific day is it": `pacific_today()`, `pacific_now()`, `pacific_day_n()`, or
     `datetime.now(PACIFIC|PT)`. Note `pacific_date_of()` is deliberately NOT in the set:
     it converts a *given* instant and never reads the clock, so it cannot disagree with
     a fixture about today.

  2. `pt_paired_utc_today_sites()` — the pairing. A finding needs BOTH halves:
       * the test file derives a UTC/naive **today** (offset zero — see the boundary
         below), and
       * the test file references at least one PT-clock module.
     A UTC fixture in a file that touches no PT-clock module is OUTSIDE this surface
     entirely and can never fire here. That is the "leave correct tests alone" direction,
     and it is load-bearing: `test_whoop_reconcile.py`, `test_strava_reconcile_window.py`
     and `test_budget_headroom.py` all pair a UTC fixture with a handler whose UTC day is
     written down and reasoned (`utc-exempt(#2811)` on the Whoop/Strava vendor API
     windows, `utc-exempt(#2798)` on the cost governor's billing month). They are right,
     and this guard says nothing about them.

THE BOUNDARY — offset ZERO, honestly drawn
──────────────────────────────────────────
Only a **today** is flagged: a day rendering with no arithmetic in it. An offset day
(`now - timedelta(days=5)`) is excluded, and that is a measurement rather than an
oversight. Measured on `origin/main` @ `6ae6310f`, the tests/ tree carries 44 UTC day
sites paired with a PT-clock module; 25 of them are offset zero. The other 19 are
relative fixture rows — "five days of history" — which stay self-consistent when the two
calendars disagree, because both ends of the comparison move together. A *today* never
does: it is the one value that must equal the handler's own answer exactly, and it is
the shape that broke #3206 twice. Flagging the offsets too would have meant ~19 more
in-code exemptions whose reason is "this is fine", and a guard that cries wolf gets
muted. The residual is named here rather than left invisible.

THE BLIND SPOT, NAMED (do not certify this file clean)
──────────────────────────────────────────────────────
`reads_pt_clock` is a DIRECT read: a module is PT only if it names `pacific_today` /
`pacific_now` / `pacific_day_n` / `datetime.now(PT)` **itself**. 65 handler modules
delegate their day instead — `site_api_vitals` takes `_experiment_date` from
`site_api_common`, whose bounds are `datetime.now(PT)` — and a test file naming only the
delegate does not pair. That is a false-GREEN route, and #2811 is the reason it is
written down instead of assumed away: its two prior slices both certified a package at
zero, and both certifications were true of the matcher and false of the code.

It is left open **on a measurement, not a shrug.** Widening to a one-hop import closure
was measured (2026-08-26): it adds 5 test files / 17 sites, and 12 of those sites are in
`test_whoop_reconcile.py`, `test_strava_reconcile_window.py` and
`test_receipts_endpoint.py` — all three CORRECT (`utc-exempt` vendor/billing handlers).
A 70%-false-positive widening is how a guard gets muted. The two genuinely-unruled files
the closure surfaces (`test_achievements_badges_1126.py`, `test_last_sync.py`) were read
by hand and run inside the 17:00-PT-to-midnight window: both green, both benign — the
badge fixture's day is filtered by a fake table that does not enforce the handler's
bounds, and last_sync's day is a granularity fallback behind real `ingested_at` instants.
`test_the_one_hop_blind_spot_stays_measured` pins that set, so a SIXTH file entering it
reds this guard and gets ruled instead of silently joining the blind spot.

Faces this file also cannot see, inherited from the matcher it imports: a day built by
hand (`f"{d.year}-{d.month:02d}-{d.day:02d}"`), `time.gmtime()`, or a `.split()[0]` on an
ISO string. All three measured at ZERO occurrences in `tests/` on 2026-08-26 — absent,
not handled.

THE RATCHET
───────────
`_PT_PAIRED_RESIDUE` maps a repo-relative test file to the MAXIMUM paired UTC-today
sites it may contain — the `_UTC_DAY_RESIDUE` / `_ISO_IDIOM_RESIDUE` precedent (#1964,
#2811). It only ever shrinks. A file over its number reds; a file **absent from the map
must be at zero**; an entry naming a file that no longer exists must be pruned; an entry
whose file reached zero must be pruned so the ratchet cannot license a regrowth back to
the old number. Every entry below is a RULING — the file was read, its handler's clock
was read, and the verdict is recorded in the comment beside it.

Run:  python3 -m pytest tests/test_fixture_frame_pairing_3222.py -v
"""

import ast
import functools
import pathlib
from datetime import datetime, timedelta, timezone

# The classification, imported rather than forked (see the header). `_import_aliases`
# comes from #2414 by way of #2811; both re-export cleanly for exactly this reason.
from test_utc_day_fleet_ratchet_2811 import utc_day_semantics_sites

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

_SKIP_PATH_MARKERS = ("__pycache__", "_staging", "cdk.out", "layer-build")

# The packages a test file's subject can live in.
_HANDLER_PACKAGES = ("lambdas", "mcp")

# The clock-reading faces of "what Pacific day is it". `pacific_date_of` is absent on
# purpose: it converts a supplied instant, so it has no opinion about today and cannot
# disagree with a fixture.
_PT_CLOCK_FUNCS = ("pacific_today", "pacific_now", "pacific_day_n")
_PT_ZONE_NAMES = ("PACIFIC", "PT")


# ── THE RESIDUE ──────────────────────────────────────────────────────────────
#
# Ruled 2026-08-26 against `origin/main` @ `6ae6310f`. Each entry names the handler, the
# clock that handler actually reads, and why the UTC fixture is not a defect. Shrink only.
_PT_PAIRED_RESIDUE: dict[str, int] = {
    # `hl.transform(raw, day)` / `hab.transform(raw, day)` — habitify_lambda.py:274 is
    # `utc-exempt(#2811)`: it classifies `in_progress` as pending-vs-failed against
    # HABITIFY'S OWN UTC deadline, the vendor's day boundary, never a DATE# key. The
    # fixtures match that declared frame. Paired here only because these files also
    # import `ingestion_framework`, which is PT for its DATE# writes — a file-level
    # over-approximation the residue absorbs rather than papering over with 13 markers.
    "tests/test_habitify_notes.py": 4,
    "tests/test_habitify_status_resolution.py": 9,
    "tests/test_now_remainder_batch.py": 1,
    # `cost_governor_lambda._active_ceilings()` — `utc-exempt(#2798)`: the dated ADR-133
    # ceiling window is scoped to a BILLING month and reverts as the AWS budget month
    # rolls. Pacific would revert it 7-8h late. The fixture is in the handler's frame.
    "tests/test_budget_headroom.py": 2,
    # `coach_state_updater._is_gradable`'s liveness window — `utc-exempt(#2815)`: a
    # widened 30-day DATE# scan bound, deliberately not the OUTPUT# frame. The module
    # ALSO calls `pacific_today()` in `_write_state` (a different function), which is
    # what pairs the file; the tested path is the UTC one and the fixture agrees with it.
    "tests/test_gradability_liveness_cross_phase_2023.py": 2,
    # Not a fixture at all: `report["measured_at"]` is the calibration harness stamping
    # its own report, with no handler on the other side to disagree with. Left as a UTC
    # stamp rather than converted, because converting it would change a published record
    # key for no behavioral reason.
    "tests/judge_calibration.py": 1,
}


# ── the derived halves ───────────────────────────────────────────────────────


def _handler_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for pkg in _HANDLER_PACKAGES:
        files += [p for p in (ROOT / pkg).rglob("*.py") if not any(m in str(p) for m in _SKIP_PATH_MARKERS)]
    return sorted(files)


def _test_files() -> list[pathlib.Path]:
    return sorted(p for p in TESTS.rglob("*.py") if not any(m in str(p) for m in _SKIP_PATH_MARKERS))


def reads_pt_clock(source: str) -> bool:
    """True if `source` asks a clock what the PACIFIC day is."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
        if name in _PT_CLOCK_FUNCS:
            return True
        if name == "now" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Name) and arg.id in _PT_ZONE_NAMES:
                return True
            if isinstance(arg, ast.Attribute) and arg.attr in _PT_ZONE_NAMES:
                return True
    return False


@functools.lru_cache(maxsize=1)
def pt_clock_modules() -> frozenset:
    """Module BASENAMES under lambdas/ + mcp/ that read a Pacific clock. Derived."""
    return frozenset(p.stem for p in _handler_files() if reads_pt_clock(p.read_text(encoding="utf-8")))


def referenced_module_names(tree: ast.AST) -> set:
    """Every module basename a test file could be naming as its subject.

    Imports (`from ingestion import whoop_lambda as whoop`, `import coach_state_updater`)
    plus dotted STRING constants, which is how `importlib.import_module(...)` and
    `monkeypatch.setattr("web.site_api_x.f", ...)` name a module. Over-approximate by
    design — the residue above is the pressure valve, and a missed subject is a false
    GREEN, which is the failure mode this epic keeps paying for.
    """
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.split("."))
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.update(a.name.split("."))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "." in node.value:
            names.update(node.value.split("."))
    return names


def _is_offset_zero(finding: str) -> bool:
    """True if the reported expression is a **today** — a day rendering with no
    arithmetic. See the header's boundary section for why offsets are out of scope.

    Reads the matcher's own `ast.unparse` output rather than re-walking the tree, so
    there is exactly one place that decides what a day site is. An expression that will
    not round-trip is treated as a today (flag), never as clean.
    """
    expr = finding.split(": ", 1)[1].rsplit("  [", 1)[0]
    try:
        parsed = ast.parse(expr, mode="eval")
    except SyntaxError:
        return True
    return not any(isinstance(n, ast.BinOp) for n in ast.walk(parsed))


def pt_paired_utc_today_sites(source: str, filename: str, pt_modules) -> list[str]:
    """Every UTC/naive **today** in `source`, when `source` names a PT-clock module."""
    findings = [f for f in utc_day_semantics_sites(source, filename=filename) if _is_offset_zero(f)]
    if not findings:
        return []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []
    if not (referenced_module_names(tree) & set(pt_modules)):
        return []
    return findings


@functools.lru_cache(maxsize=1)
def _measure() -> dict:
    pt_modules = pt_clock_modules()
    counts: dict = {}
    for path in _test_files():
        rel = str(path.relative_to(ROOT))
        hits = pt_paired_utc_today_sites(path.read_text(encoding="utf-8"), rel, pt_modules)
        if hits:
            counts[rel] = hits
    return counts


# ── the surface is real ──────────────────────────────────────────────────────


def test_the_pt_clock_module_set_is_derived_and_nonempty():
    """A glob that matches nothing is the classic dead guard. The set must be derived
    from the filesystem AND must contain the handlers this issue was written about."""
    mods = pt_clock_modules()
    assert len(mods) >= 50, f"suspiciously small PT-clock module set: {len(mods)}"
    for expected in ("permanence_lambda", "data_reconciliation_lambda", "site_api_ai_context", "digest_utils", "tools_labs"):
        assert expected in mods, f"derived PT-clock set lost {expected}"


def test_the_test_surface_is_derived_and_nonempty():
    files = _test_files()
    rels = {str(p.relative_to(ROOT)) for p in files}
    assert len(files) >= 200, f"suspiciously small tests/ surface: {len(files)}"
    for expected in ("tests/test_permanence_lambda_1400.py", "tests/test_data_reconciliation_behavior.py"):
        assert expected in rels, f"derived test surface lost {expected}"


# ── the ratchet ──────────────────────────────────────────────────────────────


def test_no_pt_paired_utc_today_outside_the_residue():
    """THE GUARD. A test file whose subject reads a Pacific clock must not compute its
    own 'today' from a UTC/naive one."""
    measured = _measure()
    offenders = {rel: hits for rel, hits in measured.items() if rel not in _PT_PAIRED_RESIDUE}
    assert not offenders, (
        "A fixture computes 'today' on a UTC/naive clock while the handler it tests reads "
        "the Pacific one (#3222 — the 17:00-PT-to-midnight window). Call the handler's own "
        "helper (`common.pacific_time.pacific_today` / `pacific_now`), or mark a genuinely-UTC "
        "computation with `# utc-exempt(#NNNN): <reason>`:\n" + "\n".join(f"  {h}" for hits in offenders.values() for h in hits)
    )


def test_the_two_files_that_redded_main_stay_at_zero():
    """#3206's instances, pinned by name. #3223 fixed them; this is what keeps them fixed
    — a ratchet whose entries are all prose can drift back without anyone noticing."""
    measured = _measure()
    for rel in ("tests/test_permanence_lambda_1400.py", "tests/test_data_reconciliation_behavior.py"):
        assert rel not in measured, f"{rel} regrew a UTC 'today' against its Pacific handler: {measured.get(rel)}"
        assert rel not in _PT_PAIRED_RESIDUE, f"{rel} must never be baselined — it is the instance this guard is named for"


def test_residue_entries_do_not_grow():
    measured = _measure()
    grown = {rel: (len(measured.get(rel, [])), cap) for rel, cap in _PT_PAIRED_RESIDUE.items() if len(measured.get(rel, [])) > cap}
    assert not grown, "residue entr(ies) grew past their recorded count (the ratchet only shrinks): %s" % grown


def test_residue_has_no_stale_entries():
    """An entry for a file that no longer exists, or that has reached zero, must be
    DELETED — otherwise the map silently licenses a regrowth back to the old number."""
    measured = _measure()
    missing = [rel for rel in _PT_PAIRED_RESIDUE if not (ROOT / rel).is_file()]
    assert not missing, "residue entr(ies) name file(s) that no longer exist — delete them: %s" % missing
    drained = [rel for rel in _PT_PAIRED_RESIDUE if rel not in measured]
    assert not drained, "residue entr(ies) whose file reached zero — delete them, the ratchet has tightened: %s" % drained


def test_residue_is_exactly_the_measured_debt_with_no_slack():
    """A cap ABOVE the file's real count is headroom the next slice can regrow into
    without reddening anything — the ratchet's quiet failure mode. Every entry equals
    what is actually there."""
    measured = _measure()
    slack = {rel: (cap, len(measured.get(rel, []))) for rel, cap in _PT_PAIRED_RESIDUE.items() if cap > len(measured.get(rel, []))}
    assert not slack, "residue entr(ies) carry unused headroom — tighten them to the measured count: %s" % slack


def test_residue_values_are_positive_ints():
    bad = sorted(rel for rel, cap in _PT_PAIRED_RESIDUE.items() if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0)
    assert not bad, "residue values must be a positive int (the maximum allowed site count), not a note: %s" % bad


# ── the blind spot, monitored rather than assumed ────────────────────────────


# The one-hop closure's members as measured 2026-08-26 @ `6ae6310f`. See the header:
# widening the guard to include these was rejected on a false-positive measurement, so
# this set is pinned instead. A SIXTH file entering it must be ruled, not absorbed.
_ONE_HOP_BLIND_SPOT = {
    # correct — `utc-exempt(#2811)` vendor API windows / `utc-exempt(#2798)` billing month
    "tests/test_whoop_reconcile.py",
    "tests/test_strava_reconcile_window.py",
    "tests/test_receipts_endpoint.py",
    # ruled by hand 2026-08-26, run inside the 17:00-PT-to-midnight window: both green,
    # both benign (a fake table that does not enforce the handler's bounds; a day-
    # granularity fallback behind real `ingested_at` instants).
    "tests/test_achievements_badges_1126.py",
    "tests/test_last_sync.py",
}


@functools.lru_cache(maxsize=1)
def _one_hop_pt_modules() -> frozenset:
    """PT-clock modules plus every module that imports FROM one — the delegation route
    `reads_pt_clock` cannot see (`site_api_vitals` ← `site_api_common._experiment_date`)."""
    direct = pt_clock_modules()
    adjacent: set = set()
    for path in _handler_files():
        if path.stem in direct:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[-1] in direct:
                adjacent.add(path.stem)
                break
    return frozenset(direct | adjacent)


def test_the_one_hop_blind_spot_stays_measured():
    """The honest half of this guard: it does NOT claim the class is closed.

    #2811's lesson stated as a test — two prior slices certified a package at zero and
    both certifications were true of the matcher and false of the code. This one names
    what it cannot see and fails when that set changes, so a new delegating-handler test
    gets a ruling instead of inheriting a false green.
    """
    direct = pt_clock_modules()
    wide = _one_hop_pt_modules()
    surfaced = set()
    for path in _test_files():
        rel = str(path.relative_to(ROOT))
        src = path.read_text(encoding="utf-8")
        if pt_paired_utc_today_sites(src, rel, direct):
            continue  # the guard already catches it
        if pt_paired_utc_today_sites(src, rel, wide):
            surfaced.add(rel)
    assert (
        surfaced == _ONE_HOP_BLIND_SPOT
    ), "the one-hop blind spot changed — rule the difference, do not widen the set blindly " "(new: %s / gone: %s)" % (
        sorted(surfaced - _ONE_HOP_BLIND_SPOT),
        sorted(_ONE_HOP_BLIND_SPOT - surfaced),
    )


# ── mutation proofs: BOTH directions ─────────────────────────────────────────


_PT_HANDLER_FIXTURE = (
    "from ingestion import permanence_lambda as perm\n"
    "from datetime import datetime, timezone\n"
    "\n"
    "def test_days_silent():\n"
    "    today = datetime.now(timezone.utc).date()\n"
    '    assert perm.handler({}, None)["day"] == today.isoformat()\n'
)

_UTC_HANDLER_FIXTURE = (
    "from ingestion import whoop_lambda as whoop\n"
    "from datetime import datetime, timezone\n"
    "\n"
    "def test_reconcile_window():\n"
    "    today = datetime.now(timezone.utc).date()\n"
    '    assert whoop._reconcile({}, None)["end"] == today.isoformat()\n'
)


def test_fires_on_a_planted_utc_fixture_against_a_pacific_handler():
    """DIRECTION 1 — the guard must FAIL on the defect. `permanence_lambda` reads
    `pacific_today()`; a fixture computing its expectation from the UTC clock is the
    exact shape that redded `main` at `81662a9d`."""
    pt_modules = pt_clock_modules()
    assert "permanence_lambda" in pt_modules, "the fixture's premise is gone — permanence_lambda no longer reads a PT clock"
    hits = pt_paired_utc_today_sites(_PT_HANDLER_FIXTURE, "tests/test_planted.py", pt_modules)
    assert len(hits) == 1, f"a UTC 'today' against a pacific_today() handler must fire: {hits}"


def test_does_not_fire_on_a_utc_fixture_against_a_genuinely_utc_handler():
    """DIRECTION 2 — and it must NOT fire on correct code. `whoop_lambda`'s reconcile
    window is `utc-exempt(#2811)`: it bounds a UTC ISO range sent to Whoop's own API,
    whose collection boundaries are UTC. Getting this direction wrong breaks working
    tests, which is the faster way to get a guard deleted."""
    pt_modules = pt_clock_modules()
    assert "whoop_lambda" not in pt_modules, "whoop_lambda started reading a PT clock — re-rule tests/test_whoop_reconcile.py"
    assert pt_paired_utc_today_sites(_UTC_HANDLER_FIXTURE, "tests/test_planted.py", pt_modules) == []


def test_a_planted_site_reds_the_guard_in_a_real_file():
    """The synthetic proofs above run the matcher on a string. This one proves the
    ratchet itself fails — that a real, currently-zero file going non-zero is caught,
    not merely that the predicate can return a list."""
    pt_modules = pt_clock_modules()
    rel = "tests/test_permanence_lambda_1400.py"
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert pt_paired_utc_today_sites(src, rel, pt_modules) == [], "precondition: the file is clean today"
    planted = src + "\n\ndef _planted():\n    from datetime import datetime, timezone\n\n    return datetime.now(timezone.utc).date()\n"
    hits = pt_paired_utc_today_sites(planted, rel, pt_modules)
    assert hits, "a reintroduced UTC 'today' in the file that redded main must fire"
    assert rel not in _PT_PAIRED_RESIDUE, "…and the residue must not be shielding it"


def test_the_exempt_marker_is_the_valve_and_is_load_bearing():
    """A genuinely-UTC computation in a PT-paired file writes the reason down."""
    pt_modules = pt_clock_modules()
    marked = _PT_HANDLER_FIXTURE.replace(
        "    today = datetime.now(timezone.utc).date()",
        "    # utc-exempt(#3222): vendor-frame day, not the platform's\n    today = datetime.now(timezone.utc).date()",
    )
    assert pt_paired_utc_today_sites(marked, "tests/test_planted.py", pt_modules) == []
    assert pt_paired_utc_today_sites(_PT_HANDLER_FIXTURE, "tests/test_planted.py", pt_modules) != []


def test_an_offset_day_is_deliberately_out_of_scope():
    """The boundary, pinned so a future reader sees it was a decision. A relative
    fixture row moves with the clock on BOTH sides of the comparison; a 'today' does not.
    If this ever needs to change, it changes here, visibly."""
    pt_modules = pt_clock_modules()
    offset = _PT_HANDLER_FIXTURE.replace(
        "datetime.now(timezone.utc).date()",
        "(datetime.now(timezone.utc) - timedelta(days=5)).date()",
    )
    assert pt_paired_utc_today_sites(offset, "tests/test_planted.py", pt_modules) == []


def test_a_pt_fixture_is_clean():
    """The fix shape itself must not be a finding — otherwise the guard punishes the
    only remedy it offers."""
    pt_modules = pt_clock_modules()
    fixed = (
        "from ingestion import permanence_lambda as perm\n"
        "from common.pacific_time import pacific_today\n"
        "\n"
        "def test_days_silent():\n"
        "    today = pacific_today()\n"
        '    assert perm.handler({}, None)["day"] == today\n'
    )
    assert pt_paired_utc_today_sites(fixed, "tests/test_planted.py", pt_modules) == []


# ── the CI-window answer (#3222's open acceptance box) ───────────────────────


def _frame_disagreement(instant: datetime) -> bool:
    """True if the UTC and Pacific calendar days differ at `instant`."""
    from common.pacific_time import PACIFIC

    return instant.astimezone(timezone.utc).date() != instant.astimezone(PACIFIC).date()


def test_the_pt_evening_window_is_exercised_without_waiting_for_it():
    """#3222's last acceptance box, answered: the suite must exercise the
    17:00-PT-to-midnight window on EVERY run, not on the runs that happen to land in it.

    #3206 shipped green because its CI ran ~13:00 PT — inside its own blind spot's
    complement. Pinning a nightly job would only move the coin flip. The cheap, complete
    answer is to freeze the clock: assert the disagreement exists at a CONSTRUCTED
    instant rather than at `now`. This is what makes every proof above hour-independent —
    they run the matcher on source text, never on wall time.

    23:30 PT on a PDT day is 06:30Z the NEXT day: the two calendars disagree, which is the
    whole mechanism. 09:00 PT is 16:00Z the same day: they agree, which is why the daily
    crons (and #3206's CI) never saw it.
    """
    from common.pacific_time import PACIFIC

    evening = datetime(2026, 8, 26, 23, 30, tzinfo=PACIFIC)
    assert _frame_disagreement(evening), "the PT-evening window must be a real disagreement, or this guard is theatre"
    assert evening.astimezone(timezone.utc).date() - evening.astimezone(PACIFIC).date() == timedelta(days=1)

    morning = datetime(2026, 8, 26, 9, 0, tzinfo=PACIFIC)
    assert not _frame_disagreement(morning), "09:00 PT must agree with UTC — the schedule-masked case #3206's CI ran in"
