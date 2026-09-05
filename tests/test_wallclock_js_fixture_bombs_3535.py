"""tests/test_wallclock_js_fixture_bombs_3535.py — #3535: the JS leg of the
wall-clock fixture-bomb family (#2223 / #2376).

WHY THIS FILE EXISTS. The two Python guards sweep ``tests/*.py`` and nothing
else. ``tests/js/*.test.mjs`` — run by the v4 site gate's bare ``node --test``,
which gates site-deploy — had no equivalent. That is not theoretical:

    2026-09-04. tests/js/coach_asof.test.mjs pinned
    "2026-08-27T14:02:46.793290+00:00" and asserted the FRESH rendering of
    weeklyAsOf(). weeklyAsOf appends "— next refresh pending" past
    WEEKLY_STALE_HOURS (8 days). Exactly 8 days after the stamp was written the
    suffix appeared and the file redded `main` on a commit that touched none of
    it (#3479, fixed per-instance in 8b94c0d2d — no class guard).

The incident showed TWO shapes off ONE input, and this file guards both:

  A. THE DATED-STAMP BOMB. A hardcoded ISO *instant* literal handed as a direct
     argument to a function in a module that reads the wall clock, with NO clock
     injected into the same call. Fixture and handler agree on the day the test
     was written and desync on a calendar date nobody chose. This is the same
     predicate as #2376's (a) + (b) + (c), re-derived for JS — see WHY THE
     PREDICATE DIFFERS below.

  B. THE PREFIX ASSERTION THAT PASSES WRONGLY. ``assert.match(<expr containing a
     hardcoded dated literal>, /^…/)`` — anchored at the START and not at the
     END. #3479's sibling case was exactly this: when the staleness suffix
     appeared, the strict-equality case failed loudly and the prefix case kept
     passing off *identical input*. A partial assertion over a string the module
     under test can append to reports green for a rendering nobody asserted. The
     fix pattern is a total assertion (``assert.equal`` / a ``$``-anchored
     regex), not a wider prefix.

WHY THE PREDICATE DIFFERS FROM #2376's. #2376 keys on a NAME that claims clock
agreement (TODAY, NOW, YESTERDAY) because in Python the bomb is a named module
constant. #3479's bomb had no name at all — the literal was inline in the call
argument — so a name-keyed predicate would have missed it entirely. The JS
signature is instead **an inline dated literal with no injected clock**, which is
the same idea (``_only_ever_injected``) read off the call site rather than off
the variable: ``genesisCount(new Date("2026-09-10T01:32:00Z"))`` and
``ptDaysAgo("2026-08-18T14:03:00Z", PT_MORNING)`` inject the as-of instant and
are NOT flagged; ``weeklyAsOf("2026-08-27T14:02:46.793290+00:00", 11)`` does not
and is.

KNOWN RECALL LIMITS, accepted deliberately (state them, don't pretend):
  * Only full ISO **instants** (``YYYY-MM-DDTHH:MM…``) count as dated literals.
    A bare ``"2026-08-27"`` is a DATE#-row key in this corpus — 179 of them in
    tests/js — and sweeping those returns an allowlist nobody would maintain
    honestly. #3479's literal was an instant, as every freshness fixture is.
  * A literal nested inside a container argument (``datableTensions([{
    generated_at: "…" }])``) is data payload, not an as-of argument, and is
    skipped. Only DIRECT arguments of the call are considered.
  * Import resolution is direct-only, like #2376's: a clock read reached
    transitively through a re-export is invisible.

Each remaining hit is either fixed or gets a named entry in ALLOWED_JS_DATED_CALLS
/ ALLOWED_JS_PREFIX_ASSERTIONS below with the load-bearing reason it cannot
desync — not just an assertion that it is safe. Both lists are shrink-only: a
dead entry fails, so they can only get smaller.
"""

import pathlib
import re

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_REPO = _TESTS_DIR.parent
_JS_TESTS = _TESTS_DIR / "js"
_FIXTURE_3479 = _TESTS_DIR / "fixtures" / "js_wallclock" / "coach_asof_prefix_3479.mjs.fixture"

# ─────────────────────────────────────────────────────────────────────────────
# THE ALLOWLISTS. Keyed "<test file>:<callee>:<literal>" — stable under line
# movement (a line number is not, and this corpus moves), specific enough that
# two different uses of the SAME literal in one file are separate decisions.
# Every entry below was verified by reading the module under test on 2026-09-05.
ALLOWED_JS_DATED_CALLS: dict[str, str] = {
    "coach_asof.test.mjs:coachAsOf:2026-07-27T14:00:00Z": (
        "paused=true. coachAsOf returns at the `if (paused)` branch, which sits ABOVE "
        "the `Date.now() - d.getTime()` staleness comparison — no clock is read on this "
        "path at all, so the rendering is a pure function of the literal. If the paused "
        "branch is ever moved below the comparison this entry is wrong and must go."
    ),
    "coach_asof.test.mjs:coachAsOf:2026-08-26T17:02:28Z": (
        "same paused=true short-circuit as the entry above (the #3252 day-number cases "
        "— coachAsOf(iso, true, 10) and the bad-asOfDayN loop); the asserted string is "
        "the pause disclosure, which the clock cannot reach."
    ),
    "coach_asof.test.mjs:weeklyAsOf:2026-07-28T03:00:00Z": (
        "a PERMANENTLY-PAST instant asserted TOTALLY. 03:00Z on Jul 28 is 20:00 PDT on "
        "Jul 27, so it is the instant that can tell the Pacific frame from UTC — the "
        "point of the test — and it is years past WEEKLY_STALE_HOURS, so the "
        "'— next refresh pending' suffix is monotonic: staleness only increases, the "
        "rendering can never change again. The assertion is assert.equal on the WHOLE "
        "string including the suffix, which is what #3479's `^`-anchored sibling was not."
    ),
    "evidence_shared.test.mjs:fmtShort:2026-03-05T00:00:00": (
        "fmtShort is a pure date FORMATTER (evidence_shared.js) — it parses the string "
        "and renders 'Mar 5'; it makes no comparison against any clock. The file is in "
        "scope only because evidence_shared.js reads a clock in a DIFFERENT export that "
        "this call does not reach."
    ),
}

ALLOWED_JS_PREFIX_ASSERTIONS: dict[str, str] = {
    # Empty by construction: #3479's specimen was the only one in the corpus and it is
    # fixed. An entry here would be a promise that a `^`-anchored, `$`-less assertion
    # over a hardcoded dated literal cannot pass wrongly — which is the exact promise
    # #3479 disproved. Prefer making the assertion total.
}

# ─────────────────────────────────────────────────────────────────────────────
# A full ISO instant: date + 'T' + at least HH:MM. See the recall limit above.
_ISO_INSTANT = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[^\"']*"
_ISO_INSTANT_LITERAL_RE = re.compile(r"""^["'](%s)["']$""" % _ISO_INSTANT)
_ISO_INSTANT_ANY_RE = re.compile(r"""["'](%s)["']""" % _ISO_INSTANT)

# A wall-clock read in a site module (or, for (c), a clock CONTROL idiom in the test).
_JS_CLOCK_RE = re.compile(r"Date\.now\s*\(\s*\)|new\s+Date\s*\(\s*\)")
# node:test's clock control. No file uses it today; the branch exists so adopting it
# retires the finding rather than tripping the gate.
_JS_CLOCK_CONTROL_RE = re.compile(r"mock\.timers|setSystemTime|MockDate")

# `const X = new Date(...)` / `Date.now()` — an identifier bound to a clock instant.
_CLOCK_BINDING_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*[^;\n]*?(?:new\s+Date\s*\(|Date\.now\s*\()")

# A site module import specifier, matched on its repo-relative tail so the scanner
# resolves the same way for a file in tests/js and for the #3479 fixture in a tmp dir.
_SITE_IMPORT_RE = re.compile(r"""["'][^"']*?(site/assets/js/[\w.\-]+\.js)["']""")

_CALLEE_RE = re.compile(r"\b((?:[A-Za-z_$][\w$]*\.)?[A-Za-z_$][\w$]*)\s*\(")
# Callees that ARE the injection idiom, never the measured value.
_NOT_A_CALLEE = frozenset({"Date", "new Date", "if", "for", "while", "switch", "catch", "function", "return", "typeof"})


def _strip_comments(src: str) -> str:
    """Blank out // and /* */ comments, preserving line structure. Comment text
    carries dated literals all over this corpus (#3479's own fix comment quotes
    the bomb verbatim) and none of it executes."""
    out = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                out.append(src[i])
                if src[i] == "\\":
                    i += 2
                    if i - 1 < n:
                        out.append(src[i - 1])
                    continue
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append("\n" * src.count("\n", i, end))
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _arg_text(src: str, open_paren: int) -> tuple[str, int] | None:
    """The text between `open_paren` and its balancing `)`, string-aware."""
    depth = 0
    i, n = open_paren, len(src)
    while i < n:
        ch = src[i]
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < n and src[i] != quote:
                i += 2 if src[i] == "\\" else 1
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return src[open_paren + 1 : i], i
        i += 1
    return None


def _split_args(text: str) -> list[str]:
    """Top-level comma split, string- and bracket-aware."""
    args, depth, buf = [], 0, []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'`":
            quote = ch
            buf.append(ch)
            i += 1
            while i < n and text[i] != quote:
                buf.append(text[i])
                i += 2 if text[i] == "\\" else 1
                if text[i - 1] == "\\" and i - 1 < n:
                    buf.append(text[i - 1])
            buf.append(quote)
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    args.append("".join(buf))
    return [a.strip() for a in args if a.strip()]


def _reads_wall_clock(specifier_tail: str) -> bool:
    path = _REPO / specifier_tail
    return path.is_file() and bool(_JS_CLOCK_RE.search(path.read_text()))


def _drives_a_clock_module(src: str) -> list[str]:
    """(b): the site modules this test imports that read a wall clock."""
    return sorted({tail for tail in _SITE_IMPORT_RE.findall(src) if _reads_wall_clock(tail)})


def scan_js_dated_calls(path: pathlib.Path) -> dict[str, str]:
    """Shape A: "<file>:<callee>:<literal>" -> the clock modules the file drives."""
    raw = path.read_text()
    if _JS_CLOCK_CONTROL_RE.search(raw):
        return {}  # (c) — the file controls the clock; out of the class
    src = _strip_comments(raw)
    clocked = _drives_a_clock_module(src)
    if not clocked:
        return {}
    drives = ", ".join(clocked)
    hits: dict[str, str] = {}
    for m in _CALLEE_RE.finditer(src):
        callee = m.group(1)
        if callee in _NOT_A_CALLEE or src[max(0, m.start() - 4) : m.start()].endswith("new "):
            continue
        span = _arg_text(src, m.end() - 1)
        if span is None:
            continue
        args = _split_args(span[0])
        dated = [lit.group(1) for lit in (_ISO_INSTANT_LITERAL_RE.match(a) for a in args) if lit]
        if not dated:
            continue
        # An injected clock ANYWHERE in the same call takes the call out of the class:
        # fixture and as-of then derive from the same instant (the #2376 anti-bomb).
        bound = set(_CLOCK_BINDING_RE.findall(src))
        injected = any(_JS_CLOCK_RE.search(a) or "new Date(" in a or a in bound for a in args)
        if injected:
            continue
        for lit in dated:
            hits[f"{path.name}:{callee}:{lit}"] = drives
    return hits


def scan_js_prefix_assertions(path: pathlib.Path) -> dict[str, str]:
    """Shape B: "<file>:assert.match:<literal>" -> the offending regex source."""
    src = _strip_comments(path.read_text())
    hits: dict[str, str] = {}
    for m in re.finditer(r"\bassert\.match\s*\(", src):
        span = _arg_text(src, m.end() - 1)
        if span is None:
            continue
        args = _split_args(span[0])
        if len(args) < 2:
            continue
        subject, pattern = args[0], args[1]
        lit = _ISO_INSTANT_ANY_RE.search(subject)
        if not lit:
            continue
        if not pattern.startswith("/^"):
            continue
        if re.search(r"\$/[gimsuyd]*$", pattern):
            continue  # totally anchored — not the class
        hits[f"{path.name}:assert.match:{lit.group(1)}"] = pattern
    return hits


def _scan_dir(root: pathlib.Path):
    a: dict[str, str] = {}
    b: dict[str, str] = {}
    for path in sorted(root.glob("*.test.mjs")):
        a.update(scan_js_dated_calls(path))
        b.update(scan_js_prefix_assertions(path))
    return a, b


# ─────────────────────────────────────────────────────────────────────────────
# The gates.


def test_no_unregistered_dated_literal_against_a_js_handler_clock():
    """Shape A: a hardcoded ISO instant driven at a clock-reading site module,
    with no clock injected into the same call — see the module docstring."""
    found, _ = _scan_dir(_JS_TESTS)
    unregistered = {k: v for k, v in found.items() if k not in ALLOWED_JS_DATED_CALLS}
    assert not unregistered, (
        "tests/js file(s) hand a hardcoded ISO instant to a module that reads the wall\n"
        "clock, with no clock injected into the same call. This is the class that redded\n"
        "main on 2026-09-04 (#3479): green the day it was written, red 8 days later on a\n"
        "commit that touched none of it, in the gate that blocks site-deploy. Either\n"
        "derive the stamp from Date.now() (the fix in 8b94c0d2d), inject the as-of instant\n"
        "into the call, or add a justified entry to ALLOWED_JS_DATED_CALLS in\n"
        "tests/test_wallclock_js_fixture_bombs_3535.py:\n" + "\n".join(f"  {k}  -> drives {v}" for k, v in sorted(unregistered.items()))
    )


def test_no_unregistered_prefix_assertion_over_a_dated_literal():
    """Shape B: a `^`-anchored, `$`-less assert.match over a hardcoded dated
    literal — the assertion that PASSED WRONGLY in #3479."""
    _, found = _scan_dir(_JS_TESTS)
    unregistered = {k: v for k, v in found.items() if k not in ALLOWED_JS_PREFIX_ASSERTIONS}
    assert not unregistered, (
        "assert.match over a hardcoded dated literal anchored at the START but not the\n"
        "END. #3479's sibling case was exactly this: the module grew a '— next refresh\n"
        "pending' suffix, the strict-equality case failed loudly and this shape kept\n"
        "passing off IDENTICAL input — one green nobody earned. Make the assertion total\n"
        "(assert.equal, or anchor the regex with `$`):\n" + "\n".join(f"  {k}  -> {v}" for k, v in sorted(unregistered.items()))
    )


def test_allowlists_have_no_dead_entries():
    """Both lists are shrink-only: an entry for a call the scan no longer flags
    is a stale exemption, not a real one."""
    a, b = _scan_dir(_JS_TESTS)
    dead_a = sorted(k for k in ALLOWED_JS_DATED_CALLS if k not in a)
    dead_b = sorted(k for k in ALLOWED_JS_PREFIX_ASSERTIONS if k not in b)
    assert not dead_a, f"ALLOWED_JS_DATED_CALLS lists entr(ies) the scan no longer flags; delete them: {dead_a}"
    assert not dead_b, f"ALLOWED_JS_PREFIX_ASSERTIONS lists entr(ies) the scan no longer flags; delete them: {dead_b}"


def test_the_guard_catches_the_real_3479_specimen(tmp_path):
    """THE NEGATIVE CONTROL, and the only one that matters: the pre-fix
    tests/js/coach_asof.test.mjs (verbatim at 8b94c0d2d^) must fire BOTH shapes.
    A guard that would not have caught #3479 has failed its only real test case,
    and a synthetic control alone cannot tell you that."""
    specimen = tmp_path / "coach_asof.test.mjs"
    specimen.write_text(_FIXTURE_3479.read_text())
    a, b = _scan_dir(tmp_path)

    bomb = "coach_asof.test.mjs:weeklyAsOf:2026-08-27T14:02:46.793290+00:00"
    assert bomb in a, f"shape A missed the #3479 bomb; scan returned {sorted(a)}"
    assert "coach_asof.js" in a[bomb]

    prefix = "coach_asof.test.mjs:assert.match:2026-08-27T14:02:46.793290+00:00"
    assert prefix in b, f"shape B missed the #3479 sibling assertion; scan returned {sorted(b)}"
    assert "$" not in b[prefix]

    # ...and the SHIPPED fix of that same file is clean, so the guard scores the
    # incident the way the incident was actually resolved.
    live_a = scan_js_dated_calls(_JS_TESTS / "coach_asof.test.mjs")
    live_b = scan_js_prefix_assertions(_JS_TESTS / "coach_asof.test.mjs")
    assert not [k for k in live_a if k not in ALLOWED_JS_DATED_CALLS]
    assert not [k for k in live_b if k not in ALLOWED_JS_PREFIX_ASSERTIONS]


def test_the_guard_does_not_flag_the_injection_pattern(tmp_path):
    """The positive control's other half: the fix patterns the guard prescribes
    must PASS, or the gate punishes the only exits it offers."""
    header = 'const { weeklyAsOf, genesisCount, ptDaysAgo } = await import("../../site/assets/js/coach_asof.js");\n'

    # (1) a stamp DERIVED from the clock — 8b94c0d2d's actual fix.
    (tmp_path / "derived.test.mjs").write_text(
        header + "const FRESH = new Date(Date.now() - 2 * 3600e3).toISOString();\n" "weeklyAsOf(FRESH, 11);\n"
    )
    # (2) the as-of instant INJECTED as an argument (genesis_pt_2941 / entry_age idiom).
    (tmp_path / "injected.test.mjs").write_text(
        header + 'const PT_MORNING = new Date("2026-08-23T16:00:00Z");\n' 'ptDaysAgo("2026-08-18T14:03:00Z", PT_MORNING);\n'
    )
    # (3) a literal constructed straight into a Date and handed over as the clock.
    (tmp_path / "ctor.test.mjs").write_text(header + 'genesisCount(new Date("2026-09-10T01:32:00Z"));\n')
    a, b = _scan_dir(tmp_path)
    assert not a, f"the guard flagged a prescribed fix pattern (shape A): {sorted(a)}"
    assert not b, f"the guard flagged a prescribed fix pattern (shape B): {sorted(b)}"

    # Shape B's prescribed fix is a TOTAL assertion. Anchoring both ends clears shape B;
    # it does NOT clear shape A, which is correct and deliberate — a hardcoded instant
    # still has to earn its keep in ALLOWED_JS_DATED_CALLS with a reason it cannot
    # desync. The two shapes are independent findings off the same line.
    total = tmp_path / "total.test.mjs"
    total.write_text(header + 'assert.match(weeklyAsOf("2026-07-28T03:00:00Z"), /^as of Jul 27 — next refresh pending$/);\n')
    assert not scan_js_prefix_assertions(total)
    assert "total.test.mjs:weeklyAsOf:2026-07-28T03:00:00Z" in scan_js_dated_calls(total)

    # ...and a file that imports NO clock-reading module is out of the class entirely.
    (tmp_path / "noclock.test.mjs").write_text(
        'const { fmt } = await import("../../site/assets/js/evidence_bar.js");\nfmt("2026-03-05T00:00:00");\n'
    )
    assert not scan_js_dated_calls(tmp_path / "noclock.test.mjs")


def test_the_guard_fires_on_a_synthetic_bomb(tmp_path):
    """Mutation proof against the #1908 shape (a scanner that silently matches
    nothing greens every assertion above). Synthetic, in the #2223 idiom, on top
    of the real-specimen control."""
    header = 'const { weeklyAsOf } = await import("../../site/assets/js/coach_asof.js");\n'
    (tmp_path / "synthetic.test.mjs").write_text(header + 'assert.equal(weeklyAsOf("2030-01-02T03:04:05Z"), "as of Jan 1");\n')
    a, _ = _scan_dir(tmp_path)
    assert "synthetic.test.mjs:weeklyAsOf:2030-01-02T03:04:05Z" in a

    (tmp_path / "synthetic_prefix.test.mjs").write_text(header + 'assert.match(weeklyAsOf("2030-01-02T03:04:05Z"), /^as of Jan 1/);\n')
    _, b = _scan_dir(tmp_path)
    assert "synthetic_prefix.test.mjs:assert.match:2030-01-02T03:04:05Z" in b

    # A comment quoting the bomb is not the bomb (this very repo's fix comment does).
    (tmp_path / "commented.test.mjs").write_text(header + '// weeklyAsOf("2030-01-02T03:04:05Z") used to be pinned here\n')
    assert not scan_js_dated_calls(tmp_path / "commented.test.mjs")


# ─────────────────────────────────────────────────────────────────────────────
# #3535's third leg: the genesis anchor must be DERIVED, not retyped.
#
# The acceptance checkbox asked for "no tests/js/*.mjs or tests/test_*.py hand-types
# the literal value of EXPERIMENT_START_DATE". Swept as a bare string that returns
# eleven files of pure coincidence — `assert by_text["frozen"]["date"] ==
# "2026-09-05"` in tests/test_coaches_api.py is a DDB row echoed back through the
# API and claims nothing about the anchor; tests/js/charts_axes_from_data has a
# spend series that happens to run through it. Keyed the other way round, on the
# subject alone, it returns four MORE files that inject their own genesis
# ("2026-07-19", "2099-01-01") and assert the round trip — safe by construction.
#
# The defect is the INTERSECTION, and this rule is both halves at once: an equality
# assertion whose SUBJECT is named for the genesis anchor AND whose expected value
# is the LIVE anchor, read out of lambdas/common/constants.py at scan time rather
# than typed here. That is the only shape that silently rots when a reset moves the
# anchor, and the rule itself obeys the discipline it enforces — nothing below
# hardcodes a date.
# The needle is READ FROM THE OWNER at scan time, never typed here — the same
# discipline the rule enforces. A round-trip fixture that injects its own genesis
# ("2026-07-19") and asserts it comes back is safe by construction no matter where
# the anchor sits; only a retype of the LIVE anchor rots when a reset moves it.
_LIVE_GENESIS = re.search(
    r"""^EXPERIMENT_START_DATE\s*=\s*["'](\d{4}-\d{2}-\d{2})["']""",
    (_REPO / "lambdas" / "common" / "constants.py").read_text(),
    re.MULTILINE,
).group(1)

_GENESIS_SUBJECT = r"[\w$.\[\]\"']*(?i:genesis|experiment_start)[\w$.\[\]\"']*"
_GENESIS_EQ_RES = (
    re.compile(r"""%s\s*==\s*["']%s["']""" % (_GENESIS_SUBJECT, _LIVE_GENESIS)),
    re.compile(r"""["']%s["']\s*==\s*%s""" % (_LIVE_GENESIS, _GENESIS_SUBJECT)),
    re.compile(
        r"""assert(?:\.\w+)*\.?(?:equal|strictEqual|deepEqual|deepStrictEqual)\(\s*%s\s*,\s*["']%s["']"""
        % (_GENESIS_SUBJECT, _LIVE_GENESIS)
    ),
)

# file -> why this file is allowed to retype the anchor.
ALLOWED_HANDTYPED_GENESIS = {
    "genesis_pt_2941.test.mjs": (
        "THE DESIGNATED DRIFT DETECTOR. Its whole first test is "
        '`assert.equal(GENESIS_ISO, "<genesis>")` — a deliberate tripwire so that a '
        "reset which moves the anchor reds this file loudly and its hand-computed PT "
        "day-boundary instants get regenerated with the sweep rather than loosened. "
        "Deriving the literal here would delete the detector."
    ),
}


def _scan_handtyped_genesis(root: pathlib.Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(list(root.glob("test_*.py")) + list((root / "js").glob("*.test.mjs"))):
        if path.name == pathlib.Path(__file__).name:
            continue  # this guard names the shapes it hunts; scanning itself is circular
        src = _strip_comments(path.read_text()) if path.suffix == ".mjs" else path.read_text()
        for rx in _GENESIS_EQ_RES:
            for m in rx.finditer(src):
                found.setdefault(path.name, []).append(m.group(0).strip()[:90])
    return found


def test_the_genesis_anchor_is_derived_not_retyped():
    """An equality assertion on a genesis-named subject must read the anchor from
    its owner (lambdas/common/constants.EXPERIMENT_START_DATE, or the site
    module's own GENESIS_ISO), not repeat the date — see the block comment above."""
    found = _scan_handtyped_genesis(_TESTS_DIR)
    unregistered = {k: v for k, v in found.items() if k not in ALLOWED_HANDTYPED_GENESIS}
    assert not unregistered, (
        "Test(s) assert a genesis-named value equals a HARDCODED date. The anchor moves\n"
        "at every experiment reset, so this reds on a reset rather than on a defect —\n"
        "derive it from EXPERIMENT_START_DATE / the module's own export, or register the\n"
        "file in ALLOWED_HANDTYPED_GENESIS with the reason it is a deliberate detector:\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(unregistered.items()))
    )


def test_the_genesis_allowlist_has_no_dead_entries():
    found = _scan_handtyped_genesis(_TESTS_DIR)
    dead = sorted(k for k in ALLOWED_HANDTYPED_GENESIS if k not in found)
    assert not dead, f"ALLOWED_HANDTYPED_GENESIS lists file(s) the scan no longer flags; delete them: {dead}"


def test_the_genesis_scan_fires_on_a_synthetic_retype(tmp_path):
    """Mutation proof, and the discrimination that makes the rule fact-keyed
    rather than value-keyed."""
    (tmp_path / "js").mkdir()
    (tmp_path / "test_injected_genesis.py").write_text(
        'from common.constants import EXPERIMENT_START_DATE\n\n\ndef test_x():\n    assert EXPERIMENT_START_DATE == "2026-09-05"\n'
    )
    assert "test_injected_genesis.py" in _scan_handtyped_genesis(tmp_path)

    (tmp_path / "js" / "injected.test.mjs").write_text('assert.equal(GENESIS_ISO, "2026-09-05");\n')
    assert "injected.test.mjs" in _scan_handtyped_genesis(tmp_path)

    # A date that merely HAPPENS to equal the anchor, asserted on a subject that
    # claims nothing about it, is not this class (tests/test_coaches_api.py's
    # fixture round-trip is the live specimen).
    (tmp_path / "test_injected_coincidence.py").write_text('def test_y(by_text):\n    assert by_text["frozen"]["date"] == "2026-09-05"\n')
    assert "test_injected_coincidence.py" not in _scan_handtyped_genesis(tmp_path)

    # The prescribed fix — comparing against the imported constant — must pass.
    (tmp_path / "test_injected_derived.py").write_text(
        'from common.constants import EXPERIMENT_START_DATE\n\n\ndef test_z(payload):\n    assert payload["genesis"] == EXPERIMENT_START_DATE\n'
    )
    assert "test_injected_derived.py" not in _scan_handtyped_genesis(tmp_path)
