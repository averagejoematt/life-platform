"""tests/test_pacific_today_guard_2414.py — the SET guard for reader-facing "today" (#2414).

THE DEFECT CLASS. The site's day boundary is Pacific Time by owner decision
(feedback_site_pacific_time, #1964's one-Pacific-frame invariant), yet #2411's
sweep measured ~15 reader endpoints still anchoring "today" in UTC —
``datetime.now(timezone.utc).strftime("%Y-%m-%d")`` and friends — so every night
17:00–24:00 PT those payloads disagreed with the cockpit about what day it is
(#2392 caught the observatory stamping *tomorrow*). #2414 swept the class; this
file keeps it swept.

GUARD THE SET, NOT THE INSTANCE (the #1964 / D5 pattern). The scanned surface is
DERIVED — every ``.py`` under ``lambdas/web/`` (the reader-serving Lambda code:
site_api_* modules, the og writers, fingerprint, card engines) plus the
reader-bound writers listed in ``_READER_BOUND_WRITERS`` — never a hand-list of
known-bad files. Each matcher has a paired negative test proving it fires on
synthetic offending source, so a matcher that silently matches nothing cannot
report green forever.

WHAT IS BANNED (the "faces of the class", all AST-matched, comments never flag):
  * ``datetime.utcnow()`` / ``datetime.today()`` / ``date.today()`` — naive clocks.
  * ``datetime.now()`` with no tz — the runner-local naive clock.
  * A date-only rendering of a UTC-anchored now: ``.strftime("%Y-%m-%d")`` /
    ``.date()`` / ``.isocalendar()`` / f-string ``{...:%Y-%m-%d}`` where the
    receiver derives from ``datetime.now(timezone.utc)`` — directly, through
    ``timedelta`` arithmetic, or through an intermediate variable assigned from
    it (single-file taint, so the two-statement form can't dodge the guard).

WHAT IS ALLOWED:
  * The PT idiom: ``datetime.now(PT)`` / ``pacific_today()`` / ``pacific_now()``
    (PT is ``common.pacific_time.PACIFIC``, re-exported by site_api_common).
  * UTC *instants*: ``.isoformat()``, ``.timestamp()``, datetime-valued
    ``strftime`` formats (anything carrying ``%H``) — a stored instant is
    frame-free; only its DAY rendering has a frame.
  * An explicit ``.astimezone(...)`` before the day rendering — a deliberate,
    named frame choice is exactly what this guard exists to force.
  * A site marked ``# utc-exempt(#NNNN): <reason>`` on the line or up to three
    lines above — the written in-code exemption the #2414 acceptance box
    requires for a genuinely-UTC computation (e.g. a UTC-keyed partition read;
    see site_api_pulse's boundary-widening query bound).

Run:  python3 -m pytest tests/test_pacific_today_guard_2414.py -v
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

_SKIP_PATH_MARKERS = ("__pycache__", "_staging", "cdk.out", "layer-build")

# Whole packages OUTSIDE lambdas/web/ that are reader-bound writer code end to
# end, scanned like lambdas/web/ itself (glob, not a hand-list). lambdas/content/
# joined 2026-08-19 (#2816): site_writer.py/output_writers.py bake day counts
# into public_stats.json — the homepage mirror — which regrew the #2414 class
# because lambdas/content/ sat outside the guarded surface entirely.
_ADDITIONAL_SURFACE_DIRS = ("lambdas/content",)

# Reader-bound writers OUTSIDE lambdas/web/: modules whose output is served to
# readers even though they live in another package. The observatory renderer
# assembles the /coaching observatory cards (#2392's original defect family).
_READER_BOUND_WRITERS = ("lambdas/coach/coach_observatory_renderer.py",)

# PT-frame instruments (#2814): operator-facing modules whose whole JOB is judging
# PT-keyed days — the coherence sentinel anchored its own frame in UTC, so any
# off-schedule invoke between 17:00 PDT and midnight computed tomorrow's date
# (the schedule-masked latent class: its 18:45Z cron happens to land where UTC
# and PT agree). Down-payment on the fleet-wide ban story: an instrument fixed
# for this class enters the guarded surface here, never a whitelist.
_PT_FRAME_INSTRUMENTS = ("lambdas/operational/coherence_sentinel_lambda.py",)

# The OUTPUT# frame (#2815): every writer that keys a coach's OUTPUT#{date}#...
# DynamoDB sk, plus the sibling naive-clock defaults swept in the same pass, plus
# the consumer whose same-day self-exclusion has to agree with all of them. The
# two `# utc-exempt(#2815)` annotations that used to live in ai_calls.py and
# coach_quality_gate.py are RETIRED — the whole set converted to
# `common.pacific_time.pacific_today()` atomically instead of one side staying
# UTC to avoid desyncing from the other — so these enter the guarded surface
# rather than keep the naive-clock class invisible to this scan.
_OUTPUT_FRAME_WRITERS = (
    "lambdas/ai/ai_calls.py",
    "lambdas/ai/quality_gate_contract.py",
    "lambdas/coach/coach_quality_gate.py",
    "lambdas/coach/coach_state_updater.py",
    "lambdas/coach/inter_coach_dialogue_lambda.py",
    "lambdas/compute/coach_memoir_lambda.py",
)

_EXEMPT_MARKER = "utc-exempt(#"

# A date-ONLY strftime format: names the day, carries no clock time.
_DAY_FMT = "%Y-%m-%d"
_TIME_MARKERS = ("%H", "%M", "%S", "%X", "%c")


def _surface_files() -> list[pathlib.Path]:
    """The DERIVED scan surface: lambdas/web/**/*.py + the additional whole-package
    dirs (lambdas/content/, #2816) + the reader-bound writers + the PT-frame
    instruments + the OUTPUT# frame writers (#2815) — never a hand-list."""
    files = [p for p in (ROOT / "lambdas" / "web").rglob("*.py") if not any(m in str(p) for m in _SKIP_PATH_MARKERS)]
    for rel_dir in _ADDITIONAL_SURFACE_DIRS:
        files += [p for p in (ROOT / rel_dir).rglob("*.py") if not any(m in str(p) for m in _SKIP_PATH_MARKERS)]
    files += [ROOT / rel for rel in _READER_BOUND_WRITERS + _PT_FRAME_INSTRUMENTS + _OUTPUT_FRAME_WRITERS]
    return sorted(files)


# ── AST predicates ───────────────────────────────────────────────────────────


def _is_timezone_utc(node) -> bool:
    """`timezone.utc` (or bare `utc` imported by name)."""
    if isinstance(node, ast.Attribute) and node.attr == "utc":
        return True
    return isinstance(node, ast.Name) and node.id == "utc"


# The value `_import_aliases` binds a local name to when that name refers to the
# `datetime` MODULE (`import datetime` / `import datetime as dt`) rather than to one
# of the classes inside it. A sentinel rather than the string "datetime" because the
# two must not be confused: `datetime.utcnow()` is a clock when `datetime` is the
# CLASS and an AttributeError when it is the MODULE.
_DATETIME_MODULE = "<module:datetime>"

# Reserved key prefix under which a module binding is ALSO recorded. Not a legal
# Python identifier, so it can never shadow a real local alias.
_MODULE_KEY_PREFIX = "module:"


def _import_aliases(tree: ast.AST) -> dict:
    """Map a local name to its canonical `datetime`/`date` name, or to `_DATETIME_MODULE`.

    #2812's half. The repo idiom ``from datetime import date as _date`` (15 files
    across lambdas/+mcp/) makes a naive-clock call site's AST owner literally
    ``_date`` — the matchers below used to compare that owner against the
    string ``"date"``/``"datetime"`` directly, so the alias made the call
    invisible. Walk every ``ImportFrom`` of ``datetime`` in the file first and
    resolve `date`/`datetime` aliases to their canonical name; every matcher
    then looks up the receiver through this map before comparing, so
    ``_date.today()`` is treated exactly like ``date.today()``.

    #2798's half — THE FULLY-QUALIFIED FORM. ``import datetime`` (5 files in the
    scanned packages, `import datetime as _dt` being the house spelling) puts the
    class one attribute deeper: the receiver of ``datetime.date.today()`` is an
    ``ast.Attribute``, not an ``ast.Name``, so ``_owner_name`` returned None and
    BOTH guards walked past it. Two of the six ordinary ways to derive a day were
    therefore unreachable — measured 2026-08-27 with a planted site in a real
    scanned file, which the ratchet did not red. So plain ``Import`` of the module
    is recorded here too, and ``_owner_name`` resolves the extra hop.

    A module binding is recorded TWICE — under the local name, and under the
    reserved ``module:<name>`` key. The reserved key is not a legal Python
    identifier, so it can never collide with a real alias; it exists because
    ``import datetime`` and ``from datetime import datetime`` can BOTH appear in
    one file (the bare name then means whichever ran last), and a guard that had
    to pick one reading would go blind on the other. Both readings match: a guard
    over-approximates, and `utc-exempt(#NNNN)` is the valve.
    """
    aliases: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "datetime":
                    local = alias.asname or "datetime"
                    aliases[local] = _DATETIME_MODULE
                    aliases[_MODULE_KEY_PREFIX + local] = _DATETIME_MODULE
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            for alias in node.names:
                if alias.name in ("date", "datetime"):
                    aliases[alias.asname or alias.name] = alias.name
    return aliases


def _binds_datetime_module(name: str, aliases: dict) -> bool:
    """True if the local name `name` can refer to the `datetime` MODULE.

    The unbound fallback (`name == "datetime"`) is what keeps the synthetic
    snippets in both guards' own test bodies working: they exercise the matcher
    on bare source with no import line at all, exactly as `_owner_name` has always
    defaulted an unresolved `ast.Name` to itself.
    """
    if aliases.get(_MODULE_KEY_PREFIX + name) == _DATETIME_MODULE:
        return True
    return name not in aliases and name == "datetime"


def _owner_name(node, aliases: dict):
    """The alias-resolved canonical owner of a `<node>.attr(...)` receiver, or
    None if the receiver isn't a datetime class reference.

    Two spellings resolve: a plain name (``date`` / ``datetime`` / an alias of
    either) and the fully-qualified ``<datetime-module>.date`` /
    ``<datetime-module>.datetime`` attribute chain (#2798). A name bound to the
    MODULE resolves to None on its own — ``dt.utcnow()`` is not a clock — so the
    receiver has to spell the class out to be read as one.
    """
    if isinstance(node, ast.Name):
        canonical = aliases.get(node.id, node.id)
        return None if canonical == _DATETIME_MODULE else canonical
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.attr in ("date", "datetime"):
        return node.attr if _binds_datetime_module(node.value.id, aliases) else None
    return None


def _is_utc_anchored_now(node, aliases: dict) -> bool:
    """`datetime.now(timezone.utc)` / `datetime.now(tz=timezone.utc)`, alias-resolved."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "now"):
        return False
    if _owner_name(node.func.value, aliases) != "datetime":
        return False
    if node.args and _is_timezone_utc(node.args[0]):
        return True
    return any(kw.arg == "tz" and _is_timezone_utc(kw.value) for kw in node.keywords)


def _is_naive_clock(node, aliases: dict) -> bool:
    """`datetime.utcnow()` / `datetime.today()` / `date.today()` / no-arg
    `datetime.now()`, alias-resolved (#2812) so `_date.today()` etc. fire too."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    func = node.func
    owner = _owner_name(func.value, aliases)
    if owner is None:
        return False
    attr = func.attr
    if owner == "datetime" and attr == "utcnow":
        return True
    if attr == "today" and owner in ("datetime", "date"):
        return True
    if owner == "datetime" and attr == "now" and not node.args and not node.keywords:
        return True
    return False


def _is_day_only_fmt(value) -> bool:
    return isinstance(value, str) and _DAY_FMT in value and not any(t in value for t in _TIME_MARKERS)


def _is_clock_fn_call(node, clock_fns: frozenset) -> bool:
    """A call to a same-file helper whose RETURN is a UTC/naive clock (#2811).

    THE BLINDNESS THIS CLOSES. Every predicate below asks whether an expression
    *contains* a literal `datetime.now(timezone.utc)` or a tainted NAME. A repo
    idiom that is neither — ``now = now or _now_iso()`` followed by ``now[:10]``,
    where ``_now_iso()`` is a one-line helper two hundred lines up — was
    therefore invisible, and #2798 found it in production
    (`reading/reading_store.log_session`) only by reading the pair by hand.
    A call is the third face of "a clock", and it is now matched like the others.

    Only a bare name (`_now_iso()`) or `self.<name>()` counts. Matching any
    `<anything>.<name>()` collides with unrelated methods that happen to share a
    helper's name, which measured as a false-positive generator on the live tree.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in clock_fns
    return isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self" and func.attr in clock_fns


def _clock_returning_functions(tree: ast.AST, aliases: dict) -> frozenset:
    """Functions in this file that RETURN a value built from a UTC/naive clock.

    Deliberately STRICT: the return expression must contain a *literal* clock
    call, not merely a tainted name. The loose form was measured on the live
    tree and cascades — `_latest_item()` returns a record that happens to carry
    a timestamp, every caller of it goes dirty, and the guard starts flagging
    `DATE#`-key normalisations. A guard that cries wolf gets muted, so the
    over-approximation stops one hop out.
    """
    found: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Return) and sub.value is not None):
                continue
            if any(
                isinstance(s, ast.Call) and isinstance(s.func, ast.Attribute) and s.func.attr == "astimezone" for s in ast.walk(sub.value)
            ):
                continue  # a named frame was chosen inside the helper — that is the whole point
            if any(_is_utc_anchored_now(s, aliases) or _is_naive_clock(s, aliases) for s in ast.walk(sub.value)):
                found.add(node.name)
                break
    return frozenset(found)


def _subtree_dirty(node, tainted: set, aliases: dict, clock_fns: frozenset = frozenset()) -> bool:
    """True if `node` derives from a UTC/naive now (directly, via a tainted name,
    or via a call to a clock-returning helper — #2811) and shows NO explicit
    `.astimezone(...)`, the deliberate-frame escape hatch."""
    dirty = False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "astimezone":
            return False
        if _is_utc_anchored_now(sub, aliases) or _is_naive_clock(sub, aliases) or _is_clock_fn_call(sub, clock_fns):
            dirty = True
        elif isinstance(sub, ast.Name) and sub.id in tainted:
            dirty = True
    return dirty


def _tainted_names(tree: ast.AST, aliases: dict) -> set:
    """Names assigned (anywhere in the file) from an expression containing a
    UTC-anchored or naive now. Single-file, scope-blind on purpose — a guard
    over-approximates and the exemption marker is the pressure valve."""
    tainted: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value_has_now = any(_is_utc_anchored_now(s, aliases) or _is_naive_clock(s, aliases) for s in ast.walk(node.value))
        if not value_has_now:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                tainted.add(target.id)
            elif isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple) and len(target.elts) == len(node.value.elts):
                for t_elt, v_elt in zip(target.elts, node.value.elts):
                    if isinstance(t_elt, ast.Name) and any(
                        _is_utc_anchored_now(s, aliases) or _is_naive_clock(s, aliases) for s in ast.walk(v_elt)
                    ):
                        tainted.add(t_elt.id)
    return tainted


def _own_scope_nodes(scope):
    """Every node inside `scope` WITHOUT descending into a nested function/class.

    Scope precision is what keeps the #2811 call-taint from cascading: in
    `compute/episode_detect_lambda.py`, `build_episode_record` assigns
    ``item = {..., "computed_at": _now_iso()}`` while a *different* function
    takes an `item` PARAMETER and slices its stored `DATE#` key. File-wide
    taint conflates the two and flags correct code; per-scope taint does not.
    """
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _taint_index(tree: ast.AST, aliases: dict):
    """`(clock_fns, tainted_at)` — the taint view a site should be judged against.

    `tainted_at(node)` is the file-wide literal-clock taint (unchanged since
    #2414) UNION the clock-helper-call taint of every function scope enclosing
    `node`. Splitting the two is deliberate: literal clocks are rare enough that
    file-wide over-approximation is cheap, while helper calls are ordinary code
    and only mean "a clock" inside the scope that bound the name.
    """
    clock_fns = _clock_returning_functions(tree, aliases)
    file_tainted = _tainted_names(tree, aliases)

    parents: dict = {}
    scope_tainted: dict = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names: set = set()
        for node in _own_scope_nodes(parent):
            if not isinstance(node, ast.Assign):
                continue
            if not any(_is_clock_fn_call(s, clock_fns) for s in ast.walk(node.value)):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        scope_tainted[parent] = names

    cache: dict = {}

    def tainted_at(node) -> set:
        chain: list = []
        cur = parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chain.append(cur)
            cur = parents.get(cur)
        key = tuple(id(c) for c in chain)
        if key not in cache:
            merged = set(file_tainted)
            for fn in chain:
                merged |= scope_tainted.get(fn, set())
            cache[key] = merged
        return cache[key]

    return clock_fns, tainted_at


def naive_utc_today_sites(source: str, filename: str = "<source>") -> list[str]:
    """Every reader-'today'-shaped derivation from a UTC/naive clock in `source`."""
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines()
    aliases = _import_aliases(tree)
    clock_fns, tainted_at = _taint_index(tree, aliases)
    findings: list[str] = []

    def _exempt(lineno: int) -> bool:
        for ln in range(max(1, lineno - 3), lineno + 1):
            if ln <= len(lines) and _EXEMPT_MARKER in lines[ln - 1]:
                return True
        return False

    def _flag(node, why: str) -> None:
        if not _exempt(node.lineno):
            findings.append(f"{filename}:{node.lineno}: {ast.unparse(node)}  [{why}]")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_naive_clock(node, aliases):
            _flag(node, "naive clock — no timezone at all")
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            tainted = tainted_at(node)
            if attr == "strftime" and node.args and _is_day_only_fmt(getattr(node.args[0], "value", None)):
                if _subtree_dirty(node.func.value, tainted, aliases, clock_fns):
                    _flag(node, "date-only strftime on a UTC-anchored now")
            elif attr == "date" and not node.args and _subtree_dirty(node.func.value, tainted, aliases, clock_fns):
                _flag(node, ".date() on a UTC-anchored now")
            elif attr == "isocalendar" and _subtree_dirty(node.func.value, tainted, aliases, clock_fns):
                _flag(node, ".isocalendar() on a UTC-anchored now")
        if isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            spec = "".join(str(v.value) for v in ast.walk(node.format_spec) if isinstance(v, ast.Constant))
            if _is_day_only_fmt(spec) and _subtree_dirty(node.value, tainted_at(node), aliases, clock_fns):
                _flag(node, "date-only f-string format on a UTC-anchored now")
    return findings


# ── the guard itself ─────────────────────────────────────────────────────────


def test_surface_is_derived_and_nonempty():
    """The scan surface comes from the filesystem, not a hand-list — and it must
    actually contain the reader modules this issue swept (a glob that silently
    matches nothing is the classic dead-guard failure)."""
    files = _surface_files()
    rels = {str(p.relative_to(ROOT)) for p in files}
    assert len(files) >= 20, f"suspiciously small reader surface: {sorted(rels)}"
    for expected in (
        "lambdas/web/site_api_rollups.py",
        "lambdas/web/site_api_habits.py",
        "lambdas/web/og_image_lambda.py",
        "lambdas/coach/coach_observatory_renderer.py",
        "lambdas/operational/coherence_sentinel_lambda.py",
        "lambdas/content/site_writer.py",
        "lambdas/content/output_writers.py",
        "lambdas/ai/ai_calls.py",
        "lambdas/ai/quality_gate_contract.py",
        "lambdas/coach/coach_quality_gate.py",
        "lambdas/coach/coach_state_updater.py",
        "lambdas/coach/inter_coach_dialogue_lambda.py",
        "lambdas/compute/coach_memoir_lambda.py",
    ):
        assert expected in rels, f"derived surface lost {expected}"
    for p in files:
        assert p.is_file(), f"listed reader-bound writer missing on disk: {p}"


def test_no_naive_utc_today_on_reader_surface():
    """The #2414 zero: no reader-facing module derives a day from a UTC/naive clock."""
    hits: list[str] = []
    for path in _surface_files():
        src = path.read_text(encoding="utf-8")
        hits.extend(naive_utc_today_sites(src, filename=str(path.relative_to(ROOT))))
    assert not hits, (
        "Reader-facing 'today' anchored in UTC (the site's day boundary is Pacific — "
        "use common.pacific_time (PT/pacific_today), or mark a genuinely-UTC "
        "computation with `# utc-exempt(#NNNN): <reason>`):\n" + "\n".join(hits)
    )


# ── mutation proofs: every matcher must FIRE on a reintroduced site ──────────


def test_fires_on_the_original_rollups_shape():
    src = 'from datetime import datetime, timezone\ntoday = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n'
    assert len(naive_utc_today_sites(src)) == 1


def test_fires_on_timedelta_arithmetic_shape():
    src = 'yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")\n'
    assert len(naive_utc_today_sites(src)) == 1


def test_fires_on_two_statement_taint_shape():
    src = 'now = datetime.now(timezone.utc)\ntoday = now.strftime("%Y-%m-%d")\n'
    assert len(naive_utc_today_sites(src)) == 1


def test_fires_on_date_call_and_kwarg_form():
    src = "d = datetime.now(tz=timezone.utc).date()\n"
    assert len(naive_utc_today_sites(src)) == 1


def test_fires_on_isocalendar():
    src = "iso = datetime.now(timezone.utc).isocalendar()\n"
    assert len(naive_utc_today_sites(src)) == 1


def test_fires_on_fstring_day_format():
    src = 'label = f"as of {datetime.now(timezone.utc):%Y-%m-%d}"\n'
    assert len(naive_utc_today_sites(src)) == 1


def test_fires_on_every_naive_clock_face():
    for face in ("datetime.utcnow()", "datetime.today()", "date.today()", "datetime.now()"):
        src = f"x = {face}\n"
        assert len(naive_utc_today_sites(src)) == 1, f"matcher missed naive face: {face}"


def test_fires_on_a_clock_returning_helper_call():
    """#2811 — THE THIRD FACE OF A CLOCK: a CALL.

    Before this, every predicate asked whether an expression contained a literal
    `datetime.now(timezone.utc)` or a tainted NAME, so a one-line helper laundered
    the clock past the guard completely. `reading/reading_store.py` shipped exactly
    this shape through TWO ratchet slices (#2817 and #2798) reporting green.

    Both routes must fire: calling the helper inline, and binding its result first.
    """
    inline = 'def _now_iso():\n    return datetime.now(timezone.utc)\nday = _now_iso().strftime("%Y-%m-%d")\n'
    assert len(naive_utc_today_sites(inline)) == 1, "a day rendering of a clock-helper CALL must fire"

    bound = 'def _now_iso():\n    return datetime.now(timezone.utc)\n\n\ndef f(now=None):\n    now = now or _now_iso()\n    return now.strftime("%Y-%m-%d")\n'
    assert len(naive_utc_today_sites(bound)) == 1, "a name bound from a clock-helper call must be tainted in that scope"

    method = "class C:\n    def _now(self):\n        return datetime.now(timezone.utc)\n\n    def day(self):\n        return self._now().date()\n"
    assert len(naive_utc_today_sites(method)) == 1, "`self._now()` must fire like a bare helper call"


def test_the_helper_taint_stops_at_a_named_frame_and_at_the_scope_boundary():
    """The judgment half of #2811's call face — both directions, because an
    over-firing guard gets muted and an under-firing one reports false green.

    `_pt_now()` picks a frame; that is the whole point of the guard, so calls to it
    are clean. And the taint a helper call creates belongs to the function that
    BOUND it — `lambdas/compute/episode_detect_lambda.py` has one function assigning
    `item = {..., "computed_at": _now_iso()}` and a *different* one taking an `item`
    PARAMETER whose stored `DATE#` key it slices. File-wide taint flags the second
    one, which is correct code.
    """
    framed = 'def _pt_now():\n    return datetime.now(timezone.utc).astimezone(PT)\nday = _pt_now().strftime("%Y-%m-%d")\n'
    assert naive_utc_today_sites(framed) == [], "a helper that names its frame is not a naive clock"

    scoped = (
        "def _now_iso():\n"
        "    return datetime.now(timezone.utc).isoformat()\n\n\n"
        "def build(rec):\n"
        '    item = {"computed_at": _now_iso()}\n'
        "    return item\n\n\n"
        "def read(item):\n"
        '    return datetime.strptime(item["day"], "%Y-%m-%d").date()\n'
    )
    assert naive_utc_today_sites(scoped) == [], "helper-call taint must not leak across function scopes"


def test_fires_on_the_aliased_date_import_shape():
    """#2812 — THE MUTATION TEST the issue requires. `from datetime import date
    as _date; x = _date.today()` is the repo idiom (15 files across lambdas/+
    mcp/, including the live `board_quality_gate.py:148` site) that evaded the
    plain-owner-name check entirely: `_date` never equals the string `"date"`.
    This must fire exactly like the unaliased form."""
    src = "from datetime import date as _date\nx = _date.today()\n"
    assert len(naive_utc_today_sites(src)) == 1


def test_fires_on_the_aliased_datetime_import_shape():
    """The `datetime as _dt` sibling alias (also a live repo idiom) must fire too —
    both for the bare naive-clock call and for a date-only rendering of it."""
    src = "from datetime import datetime as _dt\nx = _dt.utcnow()\n"
    assert len(naive_utc_today_sites(src)) == 1
    src2 = "from datetime import datetime as _dt, timezone as _tz\ntoday = _dt.now(_tz.utc).strftime('%Y-%m-%d')\n"
    assert len(naive_utc_today_sites(src2)) == 1


def test_fires_on_the_fully_qualified_module_import_shape():
    """#2798's closing box — THE TWO SHAPES BOTH GUARDS COULD NOT SEE.

    Measured 2026-08-27 by probing this matcher with the six ordinary ways to
    derive a calendar day. Four fired. Two did not, and both were the plain
    ``import datetime`` module form, where the class sits one attribute deeper
    than ``_owner_name`` looked:

        A  import datetime  ->  datetime.datetime.utcnow().strftime('%Y-%m-%d')
        D  import datetime  ->  datetime.date.today()

    Neither is exotic; ``import datetime as _dt`` is the house spelling in five
    files inside the #2811 scanned packages. #2812 taught the matcher the
    ``from datetime import date as _date`` alias and stopped there, so the
    fully-qualified chain walked past BOTH this guard's zero and #2811's ratchet
    for two further slices. The blindness was found by a control that came back
    empty and was nearly published as "the surface is clean" — a shape the
    matcher cannot see returns exactly what a clean tree returns.

    Asserted as a SYMMETRY against the unqualified twin of each spelling rather than
    against a hardcoded count. The two are the same program written two ways, so the
    guard owes them the same verdict — and pinning the pair means the day this matcher's
    verdict on `datetime.utcnow().strftime(...)` legitimately changes (it currently
    yields two findings: the naive clock AND its day rendering), this test moves with it
    instead of freezing yesterday's number.
    """
    for qualified, plain, why in (
        (
            "import datetime\nday = datetime.datetime.utcnow().strftime('%Y-%m-%d')\n",
            "from datetime import datetime\nday = datetime.utcnow().strftime('%Y-%m-%d')\n",
            "shape A, plain module name",
        ),
        (
            "import datetime\nday = datetime.date.today()\n",
            "from datetime import date\nday = date.today()\n",
            "shape D, plain module name",
        ),
        (
            "import datetime as dt\nday = dt.datetime.utcnow().strftime('%Y-%m-%d')\n",
            "from datetime import datetime\nday = datetime.utcnow().strftime('%Y-%m-%d')\n",
            "shape A, aliased module",
        ),
        (
            "import datetime as _dt\nday = _dt.date.today()\n",
            "from datetime import date\nday = date.today()\n",
            "shape D, the house alias",
        ),
        (
            "import datetime as _dt\nday = _dt.datetime.today()\n",
            "from datetime import datetime\nday = datetime.today()\n",
            "datetime.today() through the module",
        ),
        (
            "import datetime\nday = datetime.datetime.now(datetime.timezone.utc).date()\n",
            "from datetime import datetime, timezone\nday = datetime.now(timezone.utc).date()\n",
            "qualified tz-aware now",
        ),
        (
            "from datetime import datetime\nimport datetime\nday = datetime.date.today()\n",
            "from datetime import date\nday = date.today()\n",
            "BOTH spellings in one file — the bare name means whichever ran last, so both readings must match",
        ),
    ):
        n_plain = len(naive_utc_today_sites(plain))
        assert n_plain >= 1, f"the unqualified control itself does not fire — this test proves nothing: {plain!r}"
        assert len(naive_utc_today_sites(qualified)) == n_plain, f"still blind to {why}: {qualified!r}"


def test_the_module_form_does_not_over_fire():
    """The precision half. Resolving one more attribute hop must not turn every
    ``<something>.date.today()`` into a finding, and the escape hatches have to keep
    working through the qualified spelling — otherwise the fix buys the two shapes
    at the price of a muted guard."""
    for src, why in (
        ("import foo\nday = foo.date.today()\n", "an unrelated module that happens to expose `date`"),
        ("day = other.datetime.utcnow().strftime('%Y-%m-%d')\n", "an unimported, unrelated receiver"),
        (
            "import datetime as _dt\nfrom web.site_api_common import PT\nday = _dt.datetime.now(_dt.timezone.utc).astimezone(PT).strftime('%Y-%m-%d')\n",
            "the astimezone escape hatch, spelled through the module",
        ),
        (
            "import datetime as _dt\nfrom web.site_api_common import PT\nday = _dt.datetime.now(PT).strftime('%Y-%m-%d')\n",
            "the PT idiom, spelled through the module",
        ),
        (
            "import datetime as _dt\n# utc-exempt(#2414): a UTC-keyed partition bound\nday = _dt.date.today()\n",
            "the written-down exemption still suppresses the qualified form",
        ),
        ("import datetime as _dt\nn = _dt.date.fromisoformat('2026-08-27')\n", "a parse, not a clock"),
    ):
        assert naive_utc_today_sites(src) == [], f"false positive on {why}: {src!r}"


def test_aliased_pt_idiom_is_still_clean():
    """Alias resolution must not turn the PT idiom into a false positive merely
    because the file also imports `date`/`datetime` under an alias elsewhere."""
    src = (
        "from datetime import date as _date\n"
        "from web.site_api_common import PT\n"
        "import datetime as _dt_mod\n"
        'today = _dt_mod.datetime.now(PT).strftime("%Y-%m-%d")\n'
        "n = _date.fromisoformat('2026-08-19')\n"
    )
    assert naive_utc_today_sites(src) == []


def test_pt_idiom_and_utc_instants_are_clean():
    src = (
        "from web.site_api_common import PT\n"
        'today = datetime.now(PT).strftime("%Y-%m-%d")\n'
        "d = datetime.now(PT).date()\n"
        "stamp = datetime.now(timezone.utc).isoformat()\n"
        "epoch = int(datetime.now(timezone.utc).timestamp())\n"
        'ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")\n'
        'day = datetime.now(timezone.utc).astimezone(PT).strftime("%Y-%m-%d")\n'
        "n = pacific_day_n(EXPERIMENT_START)\n"
    )
    assert naive_utc_today_sites(src) == []


def test_exempt_marker_suppresses_with_reason_line():
    src = (
        "# utc-exempt(#2414): widens a UTC-keyed DDB query bound — not a reader 'today'\n"
        'today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n'
    )
    assert naive_utc_today_sites(src) == []
    # ...and the same site WITHOUT the marker fires (the marker is load-bearing).
    assert len(naive_utc_today_sites(src.splitlines()[1] + "\n")) == 1
