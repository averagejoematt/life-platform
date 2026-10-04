"""tests/test_coach_count_comparison_guard_4585.py — no reader page shows a coach count
without its comparison (#4585, epic #4580 rule 3).

THE SET, NOT AN INSTANCE
------------------------
The set is every piece of reader-served code that can put a coach count on a page:

  * every ES module under ``site/assets/js/``;
  * every inline ``<script>`` body in every ``site/**/*.html`` page;

minus ``site/legacy/`` (never linked from the UI — CLAUDE.md "Public Website"). A member
"shows a coach count" when it reads a field only a coach-record payload serves
(``COUNT_MARKERS`` — the record producer's ``headline_stat`` / ``track_record`` /
``hit_rate_pct`` / ``percent_floor`` / ``by_coach``, the calibration card's
``strata.coaches`` and ``accuracy_pct``) or writes the record's own words ("checked
call"). Such a member must render the comparison — ``coachComparison(`` or
``comparisonText(`` from ``/assets/js/coach_comparison.js``, which prints the
``comparison.sentence`` the API now serves beside every count.

Two narrow, reasoned escape hatches, each re-checked so it cannot rot:

  * ``FORMATTERS`` — a module that only FORMATS a count for others to render. It is not
    excused: every module that imports one of its named count-bearing exports joins the
    set and must render the comparison itself (the count moves; the obligation follows).
  * ``NOT_A_COACH_COUNT`` — a member whose marker is not the coaches' record at all.

Static text is in the set too: a page or data file that bakes "K of N checked calls" into
its own bytes (``STATIC_COUNT_RE``) is a count with no live comparison possible, and is
exempt only by name with a reason.

Mutation controls (``test_*_mutation_*``): a synthetic member with a count and no
comparison is caught; EVERY live compliant member, with its comparison calls stripped,
is caught; an importer of a formatter's count export with no comparison is caught.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

COUNT_MARKERS = re.compile(
    r"\b(?:headline_stat|track_record|hit_rate_pct|percent_floor|accuracy_pct|by_coach)\b" r"|strata\.coaches" r"|\bchecked calls?\b"
)
COMPARISON_RE = re.compile(r"\b(?:coachComparison|comparisonText)\(")
STATIC_COUNT_RE = re.compile(r"\b\d+ of (?:\d+|[a-z-]+) checked calls?\b")
INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/(?:ld\+)?json)[^>]*>(.*?)</script>", re.S | re.I)
IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']/assets/js/([\w.-]+\.js)[\"']")

#: module -> (its exports that carry a coach count, why the module itself renders none).
FORMATTERS = {
    "site/assets/js/coach_today.js": (
        ("chooseTodaysRead", "recordLine"),
        "picks the day's coach and words the board's tally; the pages that import those two print them",
    ),
    "site/assets/js/coach_roster.js": (
        ("rateText", "rateWord", "retiredSeatNote"),
        "formats a coach's rate and a retired seat's call count; its importers print them",
    ),
}

#: member -> why its marker is not the coaches' record.
NOT_A_COACH_COUNT = {
    "site/assets/js/calibration-core.js": "the vendored Brier/accuracy scorer library — computes, renders nothing",
    "site/assets/js/grade_your_coach.js": (
        "scores a ledger the READER pastes (or a static demo) in the browser and already prints its skill vs the "
        "base rate beside it — not the coaches' record"
    ),
}

#: static file -> why a baked-in "K of N checked calls" is allowed to stand.
STATIC_EXEMPT = {
    "site/story/build/beats.json": (
        "the build story quotes the #4220 defect's own wrong counts (one record printed three ways) as history — "
        "a narrative about a bug, not the coaches' record"
    ),
}


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _served(p: Path) -> bool:
    return "legacy" not in p.relative_to(SITE).parts


def members() -> dict[str, str]:
    """{relpath: code} — every module and every page's inline script code."""
    out: dict[str, str] = {}
    for p in sorted((SITE / "assets" / "js").glob("*.js")):
        out[_rel(p)] = p.read_text(encoding="utf-8", errors="replace")
    for p in sorted(SITE.rglob("*.html")):
        if not _served(p):
            continue
        code = "\n".join(INLINE_SCRIPT_RE.findall(p.read_text(encoding="utf-8", errors="replace")))
        if code.strip():
            out[_rel(p)] = code
    return out


def _formatter_importers(code_by_member: dict[str, str]) -> dict[str, set[str]]:
    """{member: {formatter exports it imports}} for every member importing a count export."""
    by_leaf = {Path(k).name: set(v[0]) for k, v in FORMATTERS.items()}
    out: dict[str, set[str]] = {}
    for rel, code in code_by_member.items():
        for names, leaf in IMPORT_RE.findall(code):
            carried = by_leaf.get(leaf, set()) & {n.strip().split(" as ")[0].strip() for n in names.split(",")}
            if carried:
                out.setdefault(rel, set()).update(carried)
    return out


def offenders(code_by_member: dict[str, str]) -> list[str]:
    """Every member that shows a coach count and renders no comparison."""
    bad = []
    importers = _formatter_importers(code_by_member)
    for rel, code in code_by_member.items():
        if rel in NOT_A_COACH_COUNT or rel in FORMATTERS:
            continue
        markers = sorted({m.group(0) for m in COUNT_MARKERS.finditer(code)})
        carried = sorted(importers.get(rel, ()))
        if (markers or carried) and not COMPARISON_RE.search(code):
            why = ", ".join(markers + [f"imports {c}" for c in carried])
            bad.append(f"{rel}: shows a coach count ({why}) and renders no coachComparison(/comparisonText(")
    return bad


def static_offenders() -> list[str]:
    bad = []
    for p in sorted(SITE.rglob("*")):
        if p.suffix not in (".html", ".json") or not p.is_file() or not _served(p):
            continue
        rel = _rel(p)
        if rel in STATIC_EXEMPT:
            continue
        hits = STATIC_COUNT_RE.findall(p.read_text(encoding="utf-8", errors="replace"))
        if hits:
            bad.append(f"{rel}: bakes a coach count into the page ({hits[0]!r}) — no live comparison can sit beside it")
    return bad


# ── the gate ───────────────────────────────────────────────────────────────────────────


def test_no_reader_page_shows_a_coach_count_without_its_comparison():
    bad = offenders(members())
    assert not bad, "Epic #4580 rule 3 / #4585 — every coach count sits beside what a simple guess scored:\n  " + "\n  ".join(bad)


def test_no_static_page_bakes_a_coach_count():
    bad = static_offenders()
    assert not bad, "A baked-in coach count cannot carry the live comparison (#4585):\n  " + "\n  ".join(bad)


def test_the_set_is_not_vacuous():
    """The sweep must actually see the renderers it exists to hold — an empty set is a
    green light wired to nothing."""
    code = members()
    showing = [r for r, c in code.items() if COUNT_MARKERS.search(c) and r not in NOT_A_COACH_COUNT and r not in FORMATTERS]
    for must in (
        "site/assets/js/coaching.js",
        "site/assets/js/evidence_intelligence.js",
        "site/assets/js/v7_coaches.js",
        "site/assets/js/v7_home.js",
    ):
        assert must in showing, f"{must} no longer reads as a coach-count renderer — the markers drifted"
    assert (SITE / "assets" / "js" / "coach_comparison.js").is_file()


def test_every_escape_hatch_is_live():
    """An exemption whose file is gone, or no longer carries the thing it excuses, is
    deleted — never left to licence the next file of that name."""
    code = members()
    for rel in list(FORMATTERS) + list(NOT_A_COACH_COUNT):
        assert rel in code, f"{rel}: exempted but no longer in the set — delete the entry"
    for rel in NOT_A_COACH_COUNT:
        assert COUNT_MARKERS.search(code[rel]), f"{rel}: carries no coach-count marker any more — delete the entry"
    for rel, (exports, _why) in FORMATTERS.items():
        for name in exports:
            assert re.search(rf"export\s+(?:async\s+)?function\s+{name}\b|export\s+const\s+{name}\b", code[rel]), f"{rel}: no export {name}"
    for rel in STATIC_EXEMPT:
        p = ROOT / rel
        assert p.is_file() and STATIC_COUNT_RE.search(p.read_text(encoding="utf-8")), f"{rel}: static exemption is stale"


# ── mutation controls ──────────────────────────────────────────────────────────────────


def test_mutation_a_count_without_a_comparison_is_caught():
    synthetic = {
        "site/assets/js/zz_synthetic.js": "export const f = (c) => `${c.record.confirmed} of ${c.record.n} checked calls right`;",
        "site/zz/index.html": "const r = d.by_coach.sleep;",
    }
    bad = offenders(synthetic)
    assert len(bad) == 2, bad
    ok = {
        "site/assets/js/zz_ok.js": synthetic["site/assets/js/zz_synthetic.js"]
        + "\nimport { coachComparison } from '/assets/js/coach_comparison.js'; coachComparison(c.comparison);"
    }
    assert offenders(ok) == []


def test_mutation_every_live_compliant_member_reds_without_its_comparison():
    """Strip the comparison call out of EACH live member that shows a count: every one must
    turn red. A member that stays green with its comparison removed is guarded by nothing."""
    code = members()
    importers = _formatter_importers(code)
    held = [
        r
        for r, c in code.items()
        if r not in NOT_A_COACH_COUNT and r not in FORMATTERS and (COUNT_MARKERS.search(c) or r in importers) and COMPARISON_RE.search(c)
    ]
    assert held, "no live member renders the comparison — the gate would be vacuous"
    survivors = []
    for rel in held:
        mutated = {rel: COMPARISON_RE.sub("removed(", code[rel])}
        mutated.update({k: v for k, v in code.items() if k != rel})
        if not any(line.startswith(rel + ":") for line in offenders(mutated)):
            survivors.append(rel)
    assert not survivors, f"these stayed green with their comparison stripped: {survivors}"


def test_mutation_an_importer_of_a_formatter_count_is_held():
    code = {"site/assets/js/zz_importer.js": 'import { recordLine } from "/assets/js/coach_today.js";\nel.textContent = recordLine(o);'}
    bad = offenders(code)
    assert bad and "imports recordLine" in bad[0], bad
    harmless = {"site/assets/js/zz_dates.js": 'import { calendarDay } from "/assets/js/coach_today.js";\nel.textContent = calendarDay(d);'}
    assert offenders(harmless) == []


def test_mutation_a_baked_count_is_caught():
    assert STATIC_COUNT_RE.search("Webb reads 0 of 9 checked calls right")
    assert STATIC_COUNT_RE.search("7 of seventeen checked calls")
    assert not STATIC_COUNT_RE.search("each checked call is graded")
