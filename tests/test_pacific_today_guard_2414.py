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


def _import_aliases(tree: ast.AST) -> dict:
    """Map a local alias name to its canonical `datetime`/`date` name (#2812).

    THE FIX. The repo idiom ``from datetime import date as _date`` (15 files
    across lambdas/+mcp/) makes a naive-clock call site's AST owner literally
    ``_date`` — the matchers below used to compare that owner against the
    string ``"date"``/``"datetime"`` directly, so the alias made the call
    invisible. Walk every ``ImportFrom`` of ``datetime`` in the file first and
    resolve `date`/`datetime` aliases to their canonical name; every matcher
    then looks up the receiver through this map before comparing, so
    ``_date.today()`` is treated exactly like ``date.today()``.
    """
    aliases: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            for alias in node.names:
                if alias.name in ("date", "datetime"):
                    aliases[alias.asname or alias.name] = alias.name
    return aliases


def _owner_name(node, aliases: dict):
    """The alias-resolved canonical owner of a `<node>.attr(...)` receiver, or
    None if the receiver isn't a plain name (e.g. a call or subscript)."""
    if not isinstance(node, ast.Name):
        return None
    return aliases.get(node.id, node.id)


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


def _subtree_dirty(node, tainted: set, aliases: dict) -> bool:
    """True if `node` derives from a UTC/naive now (directly or via a tainted name)
    and shows NO explicit `.astimezone(...)` — the deliberate-frame escape hatch."""
    dirty = False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "astimezone":
            return False
        if _is_utc_anchored_now(sub, aliases) or _is_naive_clock(sub, aliases):
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


def naive_utc_today_sites(source: str, filename: str = "<source>") -> list[str]:
    """Every reader-'today'-shaped derivation from a UTC/naive clock in `source`."""
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines()
    aliases = _import_aliases(tree)
    tainted = _tainted_names(tree, aliases)
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
            if attr == "strftime" and node.args and _is_day_only_fmt(getattr(node.args[0], "value", None)):
                if _subtree_dirty(node.func.value, tainted, aliases):
                    _flag(node, "date-only strftime on a UTC-anchored now")
            elif attr == "date" and not node.args and _subtree_dirty(node.func.value, tainted, aliases):
                _flag(node, ".date() on a UTC-anchored now")
            elif attr == "isocalendar" and _subtree_dirty(node.func.value, tainted, aliases):
                _flag(node, ".isocalendar() on a UTC-anchored now")
        if isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            spec = "".join(str(v.value) for v in ast.walk(node.format_spec) if isinstance(v, ast.Constant))
            if _is_day_only_fmt(spec) and _subtree_dirty(node.value, tainted, aliases):
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
