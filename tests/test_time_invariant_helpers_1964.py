"""tests/test_time_invariant_helpers_1964.py — the SET guard for the two time invariants.

THE DEFECT (#1964, /fullreview principal-2). ``lambdas/common/pacific_time.py``
has declared itself "the single source of truth — do not re-derive" since it
shipped, and the declaration did not hold. A scan found:

  * **7+ inline Pacific "today" derivations** re-constructing
    ``ZoneInfo("America/Los_Angeles")`` in handler code, plus **3 live
    ``timezone(timedelta(hours=-8))`` sites** — literally the fixed-offset PST
    bug that three of the other call sites' own comments memorialize, still
    running, still an hour wrong for the ~8 months of PDT.
  * **27 inline ``.replace("Z", "+00:00")`` ISO parses** plus **4 private
    ``_parse_iso*`` defs that DISAGREED with each other** about the one question
    that matters: ``site_api_freshness._parse_iso_ts`` and
    ``journal_enrichment._parse_ts`` and ``traffic_digest._parse_iso_utc``
    backfilled ``tzinfo=UTC``; ``whoop_lambda._parse_iso`` left naive naive, so
    its ``_utc_day``'s ``.astimezone()`` read a tz-less stamp in the *runner's*
    zone.

ROOT CAUSE, AND WHY THIS FILE EXISTS. The #1207 consolidation (float→Decimal)
paired its cleanup with a structural guard — ``tests/test_ddb_patterns.py``'s D5
— and that invariant has held. ``pacific_time.py`` shipped with a docstring and
nothing else, and forks accreted underneath it. A convention with no gate is a
suggestion. This is D5's pattern applied to the other two invariants.

GUARD THE SET, NOT THE INSTANCE. Nothing here enumerates the known-bad call
sites — a hand-listed regression test only catches what someone remembered, which
is exactly how #1964 came to exist. Every check AST-scans the tree and asserts an
empty result set, and every check has a paired negative test proving it actually
fires on synthetic offending source (an AST matcher that silently matches nothing
is worse than no guard: it reports green forever).

SCOPE, STATED HONESTLY. ``lambdas/`` + ``mcp/`` — the code that ships in a
deployed bundle (#781) — mirroring D5's ``_iter_python_sources()``.
``deploy/`` and ``scripts/`` are local/CI tooling that runs on an operator's
machine, are not staged into any bundle, and carry 3 further ``_parse_iso`` defs
of their own; they are deliberately NOT covered and this file does not pretend
otherwise. ``tests/`` is excluded too — a test may legitimately construct a raw
``ZoneInfo`` to build a fixture instant.

WHAT IS AND IS NOT CONVERTED. Invariants 1 and 2 (the Pacific frame, the private
parser defs) are at ZERO and guarded at zero — a single new occurrence reds CI.
The third check is a RATCHET, not a zero: 14 inline ``.replace("Z", "+00:00")``
sites across 12 files remain, each inside caller-specific error handling whose
conversion changes behavior per site and is not in #1964's slice. Those files are
frozen in ``_ISO_IDIOM_RESIDUE`` below, and the assertion is a SUBSET check — a
*new* file forking the idiom reds; a listed file converting its sites does not.
Entries come out as sites convert; nothing is ever added.

Run:  python3 -m pytest tests/test_time_invariant_helpers_1964.py -v
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_ROOTS = ("lambdas", "mcp")
_SKIP_PATH_MARKERS = ("__pycache__", "_staging", "cdk.out", "layer-build")

# The one module allowed to construct the Pacific frame and define the ISO parser.
CANONICAL = ROOT / "lambdas" / "common" / "pacific_time.py"

# Pacific tz database names. A future correct spelling belongs in pacific_time.py,
# not in a handler, so all of them are equally banned outside the canonical module.
_PACIFIC_TZ_NAMES = {"America/Los_Angeles", "US/Pacific", "America/Vancouver", "PST8PDT"}

# The fixed-offset resurrection: PT is UTC-8 in winter and UTC-7 in summer, so ANY
# hardcoded 7/8-hour offset is the 2026-06-12 bug class being rewritten.
_PACIFIC_OFFSET_HOURS = {7, 8, -7, -8}

# Private ISO-parser forks. Matched on the *private* (underscore-prefixed) names
# only: a public `parse_timestamp` with a genuinely different contract (e.g.
# health_auto_export's, which strips whitespace and never parses) is not a fork of
# this helper and must not be swept up by a name heuristic.
_PRIVATE_PARSER_STEMS = ("parse_iso", "parse_ts", "iso_parse")

# ── the ratchet (see "WHAT IS AND IS NOT CONVERTED" above) ────────────────────
# Files that still carry an inline `.replace("Z", "+00:00")`. SUBSET-asserted:
# remove entries as they convert, never add. A new path here needs a code review
# answering "why can't this call common.pacific_time.parse_iso_utc?".
_ISO_IDIOM_RESIDUE = frozenset(
    {
        "lambdas/compute/daily_insight_compute_lambda.py",
        "lambdas/compute/daily_metrics_compute_lambda.py",
        "lambdas/compute/dashboard_refresh_lambda.py",
        "lambdas/emails/chronicle_approve_lambda.py",
        "lambdas/emails/daily_brief_lambda.py",
        "lambdas/emails/weekly_digest_lambda.py",
        "lambdas/health/character_engine.py",
        "lambdas/ingestion/dropbox_poll_lambda.py",
        "lambdas/training/hevy_write_client.py",
        "lambdas/web/site_api_intelligence.py",
        "lambdas/web/site_api_vitals.py",
        "lambdas/web/subscriber_onboarding_lambda.py",
    }
)


# ── scanning primitives ──────────────────────────────────────────────────────


def _iter_deployed_sources():
    """Every .py file that ships in a deployed bundle (lambdas/ + mcp/)."""
    for base in SCAN_ROOTS:
        for path in (ROOT / base).rglob("*.py"):
            if any(m in str(path) for m in _SKIP_PATH_MARKERS):
                continue
            yield path


def _called_name(node: ast.Call) -> str | None:
    """The bare callable name of a Call, whether `f(...)` or `mod.f(...)`."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _int_literal(node) -> int | None:
    """`8` → 8, `-8` → -8, anything else → None (handles the UnaryOp AST shape)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _int_literal(node.operand)
        return -inner if inner is not None else None
    return None


# ── the three matchers (pure, so the negative tests can drive them) ──────────


def pacific_frame_forks(source: str, filename: str = "<source>") -> list[str]:
    """Every re-derivation of the Pacific timezone in `source`.

    Two shapes, one bug: constructing ``ZoneInfo("America/Los_Angeles")``
    (a *correct* second frame that can still drift from the canonical one), and
    constructing a fixed ``±7``/``±8``-hour offset (an *incorrect* frame — the
    original DST bug). Structural, so a docstring or comment naming either idiom
    is never flagged.
    """
    findings: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)
        if name == "ZoneInfo" and node.args:
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and str(arg0.value) in _PACIFIC_TZ_NAMES:
                findings.append(f"{filename}:{node.lineno}: {ast.unparse(node)}")
        elif name == "timedelta":
            for kw in node.keywords:
                if kw.arg == "hours" and _int_literal(kw.value) in _PACIFIC_OFFSET_HOURS:
                    findings.append(f"{filename}:{node.lineno}: {ast.unparse(node)} (fixed Pacific offset — PT is not a fixed offset)")
    return findings


def private_iso_parser_defs(source: str, filename: str = "<source>") -> list[str]:
    """Every private ``_parse_iso*`` / ``_parse_ts*`` / ``_iso_parse*`` def."""
    findings: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_") and node.name.lstrip("_").startswith(_PRIVATE_PARSER_STEMS):
            findings.append(f"{filename}:{node.lineno}: def {node.name}(...)")
    return findings


def inline_iso_idiom_sites(source: str, filename: str = "<source>") -> list[str]:
    """Every inline ``<expr>.replace("Z", "+00:00")`` — the forked ISO-parse idiom."""
    findings: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "replace"):
            continue
        if len(node.args) != 2:
            continue
        old, new = node.args
        old_ok = isinstance(old, ast.Constant) and old.value in ("Z", "z")
        new_ok = isinstance(new, ast.Constant) and isinstance(new.value, str) and new.value.startswith("+00:00")
        if old_ok and new_ok:
            findings.append(f"{filename}:{node.lineno}: {ast.unparse(node)}")
    return findings


def _scan(matcher) -> list[str]:
    hits: list[str] = []
    for path in _iter_deployed_sources():
        if path.resolve() == CANONICAL.resolve():
            continue
        try:
            tree_src = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover — no such file today
            continue
        try:
            hits.extend(matcher(tree_src, filename=str(path.relative_to(ROOT))))
        except SyntaxError:  # pragma: no cover — the syntax gate owns this
            continue
    return hits


# ── invariant 1: the Pacific frame is derived in exactly one place ───────────


def test_no_pacific_frame_derived_outside_the_canonical_helper():
    hits = _scan(pacific_frame_forks)
    assert not hits, (
        "Pacific timezone re-derived outside lambdas/common/pacific_time.py (#1964).\n"
        "Import the canonical frame instead:\n"
        "    from common.pacific_time import PACIFIC, pacific_now, pacific_today\n"
        "A hardcoded -7/-8 offset is ALWAYS wrong — PT switches twice a year.\n" + "\n".join(hits)
    )


def test_the_canonical_helper_still_owns_the_frame():
    """The flip side: pacific_time.py must actually construct the frame. Without
    this, deleting `PACIFIC = ZoneInfo(...)` would leave the guard above trivially
    green over a codebase with no Pacific frame at all."""
    assert pacific_frame_forks(CANONICAL.read_text(), filename="pacific_time.py"), "pacific_time.py no longer constructs the Pacific frame"


# ── invariant 2: exactly one ISO parser, with one naive-timestamp semantic ───


def test_no_private_iso_parser_forks():
    hits = _scan(private_iso_parser_defs)
    assert not hits, (
        "Private ISO-parser fork defined outside lambdas/common/pacific_time.py (#1964).\n"
        "The four that existed disagreed on naive-timestamp handling — that is the bug.\n"
        "Import the canonical parser instead:\n"
        "    from common.pacific_time import parse_iso_utc   # naive input == UTC\n" + "\n".join(hits)
    )


def test_inline_iso_idiom_does_not_spread_to_new_files():
    """RATCHET (subset assertion) — see the module docstring."""
    offenders = sorted({h.split(":")[0] for h in _scan(inline_iso_idiom_sites)} - _ISO_IDIOM_RESIDUE)
    assert not offenders, (
        'New inline `.replace("Z", "+00:00")` ISO-parse fork (#1964).\n'
        "Use the canonical parser — it handles Z/z, offsets, and states its\n"
        "naive-timestamp semantic explicitly (tz-less == UTC, never runner-local):\n"
        "    from common.pacific_time import parse_iso_utc\n"
        "If a call site genuinely cannot, add it to _ISO_IDIOM_RESIDUE with a reason.\n"
        "New files: " + ", ".join(offenders)
    )


def test_iso_idiom_residue_list_has_no_dead_entries():
    """Advisory-strength companion to the ratchet: a residue entry whose file no
    longer exists is a stale list. (Files that still exist but converted their
    sites are NOT flagged — that would red main whenever a concurrent PR does the
    right thing, per the merge-train discipline in docs/CONVENTIONS.md.)"""
    missing = sorted(p for p in _ISO_IDIOM_RESIDUE if not (ROOT / p).exists())
    assert not missing, "_ISO_IDIOM_RESIDUE names files that no longer exist — prune them:\n" + "\n".join(missing)


# ── prove each matcher fires (a silent matcher is worse than no guard) ───────


def test_guard_catches_a_synthetic_zoneinfo_fork():
    hits = pacific_frame_forks('PT = ZoneInfo("America/Los_Angeles")\n', filename="synthetic.py")
    assert len(hits) == 1 and "synthetic.py:1" in hits[0]


def test_guard_catches_a_synthetic_fixed_offset_fork():
    """The exact live bug this issue found three times."""
    hits = pacific_frame_forks("pacific = timezone(timedelta(hours=-8))\n", filename="synthetic.py")
    assert len(hits) == 1 and "fixed Pacific offset" in hits[0]

    hits_pdt = pacific_frame_forks("pt = datetime.now(timezone.utc) - timedelta(hours=7)\n", filename="synthetic.py")
    assert len(hits_pdt) == 1


def test_guard_catches_a_synthetic_aliased_zoneinfo_call():
    """`zoneinfo.ZoneInfo(...)` — the attribute-call spelling — too."""
    hits = pacific_frame_forks('PT = zoneinfo.ZoneInfo("US/Pacific")\n', filename="synthetic.py")
    assert len(hits) == 1


def test_guard_ignores_non_pacific_zones_and_unrelated_timedeltas():
    """A UTC frame, another city's zone, and a 24h window are all legitimate."""
    benign = 'utc = ZoneInfo("UTC")\ntokyo = ZoneInfo("Asia/Tokyo")\nwindow = timedelta(hours=24)\nd = timedelta(days=8)\n'
    assert pacific_frame_forks(benign, filename="synthetic.py") == []


def test_guard_ignores_a_docstring_that_names_the_banned_idiom():
    """Structural, not grep — this very file, and pacific_time.py's own docstring,
    discuss the banned idioms in prose and must not self-trip."""
    prose = '"""Do not write ZoneInfo("America/Los_Angeles") or timedelta(hours=-8) here."""\nx = 1\n'
    assert pacific_frame_forks(prose, filename="synthetic.py") == []


def test_guard_catches_a_synthetic_private_parser_def():
    for name in ("_parse_iso", "_parse_iso_ts", "_parse_ts", "__iso_parse"):
        hits = private_iso_parser_defs(f"def {name}(s):\n    return s\n", filename="synthetic.py")
        assert len(hits) == 1, name


def test_guard_ignores_the_canonical_and_unrelated_parser_names():
    """`parse_iso_utc` (public, canonical) and `parse_timestamp` (a different
    contract entirely — health_auto_export's strips whitespace, it does not parse)
    must not be swept up by the name heuristic."""
    benign = "def parse_iso_utc(v):\n    return v\n\ndef parse_timestamp(v):\n    return v\n\ndef _parse_json(v):\n    return v\n"
    assert private_iso_parser_defs(benign, filename="synthetic.py") == []


def test_guard_catches_a_synthetic_inline_iso_idiom():
    hits = inline_iso_idiom_sites('dt = datetime.fromisoformat(s.replace("Z", "+00:00"))\n', filename="synthetic.py")
    assert len(hits) == 1


def test_guard_ignores_unrelated_string_replaces():
    benign = 'a = sk.replace("DATE#", "")\nb = s.replace("Z", "")\nc = s.replace("+00:00", "Z")\n'
    assert inline_iso_idiom_sites(benign, filename="synthetic.py") == []


# ── the semantic the whole guard exists to protect ──────────────────────────


def test_canonical_parser_stamps_a_naive_timestamp_utc():
    """#1964 acceptance #3 — the whoop divergence, pinned.

    ``whoop_lambda._parse_iso`` left a tz-less stamp NAIVE, and ``_utc_day`` then
    called ``.astimezone(timezone.utc)`` on it — which Python resolves using the
    RUNNER's local zone. On the Lambda (UTC) that is accidentally right; under a
    local pytest run or a laptop backfill it silently shifts every Whoop record by
    the operator's offset, and can key a workout to the wrong day. This test fails
    if anyone ever "simplifies" the backfill away.
    """
    import sys

    sys.path.insert(0, str(ROOT / "lambdas"))
    from datetime import datetime, timezone

    from common.pacific_time import parse_iso_utc

    naive = parse_iso_utc("2026-08-04T23:30:00")
    assert naive is not None
    assert naive.tzinfo is not None, "naive input must come back AWARE, never naive"
    assert naive.utcoffset() == timezone.utc.utcoffset(None), "naive input must be interpreted as UTC"
    # The property that matters downstream: the instant is unchanged by a UTC render.
    assert naive.astimezone(timezone.utc) == datetime(2026, 8, 4, 23, 30, tzinfo=timezone.utc)


def test_canonical_parser_accepts_z_and_offset_forms_as_the_same_instant():
    import sys

    sys.path.insert(0, str(ROOT / "lambdas"))
    from common.pacific_time import parse_iso_utc

    forms = ["2026-08-04T23:30:00Z", "2026-08-04T23:30:00z", "2026-08-04T23:30:00+00:00", "2026-08-04T16:30:00-07:00"]
    parsed = [parse_iso_utc(f) for f in forms]
    assert all(p is not None for p in parsed)
    assert len(set(parsed)) == 1, f"the same instant parsed to different values: {parsed}"


def test_canonical_parser_preserves_a_non_utc_offset_rather_than_normalising():
    """Documented contract: an aware input KEEPS its own offset (the instant is
    identical either way, and comparison across offsets is exact). A caller that
    needs the UTC rendering calls .astimezone(timezone.utc) itself."""
    import sys

    sys.path.insert(0, str(ROOT / "lambdas"))
    from datetime import timedelta

    from common.pacific_time import parse_iso_utc

    dt = parse_iso_utc("2026-08-04T16:30:00-07:00")
    assert dt.utcoffset() == timedelta(hours=-7)


def test_canonical_parser_never_raises():
    import sys

    sys.path.insert(0, str(ROOT / "lambdas"))
    from common.pacific_time import parse_iso_utc

    for bad in ("", None, "not-a-date", "2026-13-99T99:99:99Z", 12345, [], {"a": 1}):
        assert parse_iso_utc(bad) is None, bad


def test_whoop_utc_day_is_stable_under_a_naive_timestamp():
    """The end-to-end shape of the whoop fix: a tz-less start_time must key to the
    same UTC day as the Z-suffixed form, whatever zone the test runner is in."""
    import sys

    sys.path.insert(0, str(ROOT / "lambdas"))
    from common.pacific_time import parse_iso_utc

    def utc_day(s):  # the exact body of whoop_lambda._utc_day
        from datetime import timezone

        t = parse_iso_utc(s)
        return t.astimezone(timezone.utc).strftime("%Y-%m-%d") if t else None

    assert utc_day("2026-08-04T23:30:00") == utc_day("2026-08-04T23:30:00Z") == "2026-08-04"
    assert utc_day("2026-08-05T00:30:00") == "2026-08-05"
    assert utc_day(None) is None


if __name__ == "__main__":  # pragma: no cover
    import subprocess
    import sys

    sys.exit(subprocess.run(["python3", "-m", "pytest", __file__, "-v", "--tb=short"], cwd=ROOT).returncode)
