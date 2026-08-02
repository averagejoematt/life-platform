"""tests/test_pt_date_anchor_guard_1937.py — the SET guard for #1937.

THE DEFECT (#1937, following #1936's finding on the same file). `/api/vitals`
anchored its "today" with ``datetime.now(timezone.utc)``, so from 5pm PT to
midnight PT every payload ran a calendar day ahead of the site's own Pacific
day frame (#1922's deterministic checker caught `/api/vitals` claiming "Day 7"
on Day 6). #1936 fixed the ONE handler qa-smoke sweeps and deliberately left
the other 14 UTC date-string anchors in the same file unchurned; this issue
reconciles the rest onto the same Pacific anchor
(``lambdas/common/pacific_time.py`` / the file's own ``PT`` import), matching
the file's own ``_day_n``/``as_of_date`` precedent.

WHY A DERIVED GUARD. #1936 fixed one call site; #1937 exists because the other
14 were left for a human to remember to fix. A hand-listed regression test
would have the same blind spot — it only catches the anchors someone
remembered. So this file does not enumerate: it AST-scans
``lambdas/web/site_api_vitals.py`` for the naked-UTC-day-anchor idiom (any
``datetime.now(timezone.utc)`` / ``datetime.utcnow()`` / bare ``date.today()``
expression whose result is formatted as a *day* string — ``.strftime()`` with
a ``%Y``/``%m``/``%d``-only format, or ``.date()`` with no time component) and
fails if the SET is non-empty. See the memory note "guard the SET, not the
instance".

SCOPE. Deliberately ``lambdas/web/site_api_vitals.py`` only — the file #1937
reconciles — not the whole ``lambdas/web/`` package. A repo-wide sweep at the
time of writing turns up ~50 pre-existing naked UTC day-anchors across roughly
20 other files in that package (og_image_lambda.py, site_api_habits.py,
site_api_training.py, site_stats_refresh_lambda.py, and more); reconciling
all of them is a materially larger, un-scoped change #1937 explicitly is not
("a standalone file-scoped frame reconciliation... not part of the
live-honesty epic's slice"). Claiming this guard covers the whole package
when it does not would be exactly the kind of dishonest surface this platform
polices elsewhere (ADR-104/147) — so it says what it actually covers.

An instant (an ISO-8601 timestamp — ``_today_iso``, ``generated_at``) is not a
day frame and correctly stays UTC (ADR unclear on the point, but #1937's own
acceptance criteria say so explicitly) — the scanner only flags DAY-string
formatting, never ``.isoformat()``.
"""

import ast
import pathlib

_WEB = pathlib.Path(__file__).resolve().parent.parent / "lambdas" / "web"
_VITALS = _WEB / "site_api_vitals.py"

# A strftime format that names a calendar DAY (year/month/day) with no clock
# component. ``%Y-%m-%d`` is the idiom used throughout this codebase; the
# absence check (no %H/%M/%S) is what makes this "a day frame", independent of
# the exact separator/format someone chooses next time.
_DAY_FORMAT_MARKERS = ("%Y", "%y", "%m", "%d", "%j")
_TIME_FORMAT_MARKERS = ("%H", "%I", "%M", "%S", "%f", "%z", "%Z")

# The idiom that anchors "now" in UTC rather than the site's Pacific frame.
# Matched against the *unparsed source* of the expression a day-format is
# applied to, so it catches `datetime.now(timezone.utc)`, offset arithmetic
# built from it (`datetime.now(timezone.utc) - timedelta(days=N)`), and the
# deprecated `datetime.utcnow()` alike.
_UTC_ANCHOR_MARKERS = ("timezone.utc", "utcnow(")


def _is_day_only_format(fmt: str) -> bool:
    if not any(m in fmt for m in _DAY_FORMAT_MARKERS):
        return False
    return not any(m in fmt for m in _TIME_FORMAT_MARKERS)


def naked_utc_date_anchors(source: str, filename: str = "<source>") -> list[str]:
    """Every naked-UTC-day-anchor call site in `source`.

    Returns ``"{filename}:{lineno}: {expr}"`` strings, structural (AST) rather
    than textual so it survives reformatting and doesn't false-positive on a
    comment or docstring mentioning the pattern.
    """
    findings: list[str] = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue

        # Case 1: `<expr>.strftime("<day-only format>")` where <expr> is UTC-anchored.
        if node.func.attr == "strftime" and node.args:
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str) and _is_day_only_format(arg0.value):
                target_src = ast.unparse(node.func.value)
                if any(m in target_src for m in _UTC_ANCHOR_MARKERS):
                    findings.append(f"{filename}:{node.lineno}: {target_src}.strftime({arg0.value!r})")

        # Case 2: `<expr>.date()` where <expr> is UTC-anchored (a day with no
        # clock component, same class as .strftime("%Y-%m-%d")).
        if node.func.attr == "date" and not node.args:
            target_src = ast.unparse(node.func.value)
            if any(m in target_src for m in _UTC_ANCHOR_MARKERS):
                findings.append(f"{filename}:{node.lineno}: {target_src}.date()")

    # Case 3: bare `date.today()` — local-tz "today", which in this platform's
    # Lambda runtime is UTC (no anchor expression to inspect; the call itself
    # IS the anchor).
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "today"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "date"
            and not node.args
        ):
            findings.append(f"{filename}:{node.lineno}: date.today()")

    return findings


# ── the set guard ────────────────────────────────────────────────────────────


def test_site_api_vitals_has_no_naked_utc_date_anchors():
    """Every date-string anchor in site_api_vitals.py derives its day from
    Pacific (#1937's acceptance criterion #1) — no `datetime.now(timezone.utc)`
    (or equivalent) formatted as a calendar day anywhere in the file.
    """
    findings = naked_utc_date_anchors(_VITALS.read_text(), filename=_VITALS.name)
    assert not findings, "naked UTC day-anchor(s) reintroduced in site_api_vitals.py:\n" + "\n".join(findings)


def test_site_api_vitals_still_anchors_instants_in_utc():
    """The flip side of the guard above: full ISO timestamps are NOT a day
    frame and must stay UTC (#1937's acceptance criterion #2) — this test
    fails if a future edit "fixes" `_today_iso`/`generated_at` into PT too,
    which would conflate an instant with a day claim.
    """
    src = _VITALS.read_text()
    assert "datetime.now(timezone.utc).isoformat()" in src


# ── prove the guard actually fires (negative test) ──────────────────────────


def test_guard_catches_a_synthetic_naked_strftime_anchor():
    synthetic = 'today = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n'
    findings = naked_utc_date_anchors(synthetic, filename="synthetic.py")
    assert len(findings) == 1
    assert "synthetic.py:1" in findings[0]


def test_guard_catches_a_synthetic_utc_offset_anchor():
    synthetic = 'd30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")\n'
    findings = naked_utc_date_anchors(synthetic, filename="synthetic.py")
    assert len(findings) == 1


def test_guard_catches_utcnow_and_bare_date_today():
    synthetic = "a = datetime.utcnow().strftime('%Y-%m-%d')\nb = date.today()\n"
    findings = naked_utc_date_anchors(synthetic, filename="synthetic.py")
    assert len(findings) == 2


def test_guard_ignores_pacific_anchored_day_strings():
    """The fixed idiom (`datetime.now(PT)`, the file's own convention) must
    NOT trip the guard — otherwise the guard would force reverting the fix.
    """
    synthetic = 'today = datetime.now(PT).strftime("%Y-%m-%d")\n'
    assert naked_utc_date_anchors(synthetic, filename="synthetic.py") == []


def test_guard_ignores_utc_instants_isoformat():
    """`.isoformat()` timestamps are instants, not day frames — never flagged,
    UTC-anchored or not (mirrors acceptance criterion #2).
    """
    synthetic = "_today_iso = datetime.now(timezone.utc).isoformat()\n"
    assert naked_utc_date_anchors(synthetic, filename="synthetic.py") == []


def test_guard_ignores_utc_anchored_non_day_strftime():
    """A UTC anchor formatted with a clock component (not a day claim) is out
    of scope for this guard — e.g. a log timestamp — only day-only formats
    are a day-frame claim.
    """
    synthetic = 'ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")\n'
    assert naked_utc_date_anchors(synthetic, filename="synthetic.py") == []
