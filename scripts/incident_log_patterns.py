#!/usr/bin/env python3
"""incident_log_patterns.py — derive INCIDENT_LOG's pattern distribution from its rows (#2840).

WHY THIS EXISTS. `docs/INCIDENT_LOG.md`'s "Patterns & Observations" section was a
hand-tallied list ("Deployment errors — 9 incidents", "CDK drift — 3 incidents", ...)
written during the V2 audit and stamped **2026-05-19**. It never moved again. By
2026-08-21 the corpus held well over a hundred dated rows, most of them post-June, and the
three classes that dominate the recent record — lane-subset/union-breach main reds,
deploy-plane wedges/strands/races, and QA-oracle false positives — appeared in it
**nowhere**. Only the "Last updated" line moved per session, which is the worst possible
combination: a section that looks maintained and is three months stale.

(No row count is quoted in this docstring on purpose. Run the script — quoting one here
would be the same stale-literal defect, one file to the left. The live numbers live in the
generated output and in `docs/INCIDENT_LOG.md`, which a guard keeps in sync.)

A hand recount would buy one correct snapshot and then rot exactly the same way. So the
section is DERIVED instead: this script reads the table and emits the distribution, and
`tests/test_incident_log_patterns_2840.py` fails when the committed section disagrees with
what the rows actually say.

WHAT IT DOES NOT DO. Classification is keyword-based over each row's Summary + Root Cause,
which is a coarse instrument on free prose — a row can match two classes, and some match
none. That is stated in the output rather than hidden: `unclassified` is printed, and the
guard asserts it stays a minority. This is a distribution, not a taxonomy with a
correctness proof. Refining a class means editing `CLASSES` here, in one place, and
re-running — not re-tallying the whole table by hand.

THE SILENCE AXIS. Silence is scored ORTHOGONALLY (loud/silent × class), not as a class of
its own, because it cuts across classes and is the single strongest predictor of
time-to-detect in this corpus. The TTD asymmetry it produces is the finding worth keeping.

THE WRITER (#2975). This script used to only EMIT — a human read the output and pasted
numbers into the doc by hand. That made it the one derived artifact in the repo with a
guard and no writer, and it failed in a specific, repeating way: a wrap adds incident rows,
touches `docs/**` only, and so triggers `Docs CI` (which ran no pytest) and NOT `CI/CD`
(whose path filter has no `docs/**`). Main read green. The next unrelated push touching
`tests/**` then went red on four assertions about a doc it never touched. Every wrap adds
rows by design, so the misattributed red was structural, not bad luck.

Both halves are fixed here: `--apply` rewrites the marker-delimited derived blocks in place
(so the reconcile job in `run_generators()` self-heals it like every other generator
output), and `--check` is the non-mutating verdict, run by **Docs CI** — the lane a
`docs/**` change actually triggers, so a stale section reds the commit that staled it.

Usage:
    python3 scripts/incident_log_patterns.py            # human-readable
    python3 scripts/incident_log_patterns.py --json     # machine-readable (the guard reads this)
    python3 scripts/incident_log_patterns.py --check    # non-mutating: is the doc current?
    python3 scripts/incident_log_patterns.py --apply    # rewrite the derived blocks in place
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INCIDENT_LOG = REPO_ROOT / "docs" / "INCIDENT_LOG.md"

# A dated table row: | YYYY-MM-DD | <severity> | summary | root cause | TTD | TTR | ...
#
# The severity cell is read GENERICALLY and normalized, never pattern-matched against one
# spelling. The first version of this script required `**Pn**` exactly and silently dropped
# 18 of the rows then present — the older unbolded `P3`, the annotated `**P4** (false positive)`, and the
# non-P severities `Low` / `**Info**` / `**DR drill**`. A derivation that quietly discards
# 13% of its population is the same defect as the frozen hand-tally it replaces, so the
# guard now asserts this parser sees every dated row a bare date-match finds.
_ROW = re.compile(r"^\|\s*(20\d{2}-\d{2}-\d{2})\s*\|([^|]*)\|(.*)$")
_SEVERITY = re.compile(r"\b(P[1-4]|Low|Info|DR drill)\b", re.I)

# Root-cause classes, keyed on vocabulary the rows actually use. Ordered most-specific
# first; a row is credited to EVERY class it matches (they are not mutually exclusive —
# a lane-subset red on a deploy-plane change is genuinely both).
CLASSES: dict[str, tuple[str, ...]] = {
    "lane-subset / union-breach main red": (
        "deselect",
        "pre-merge lane",
        "main red",
        "red main",
        "red-main",
        "collection",
        "collect",
        "union",
    ),
    "deploy-plane wedge / strand / race": (
        "wedge",
        "stranded",
        "strand",
        "approval gate",
        "cancel-in-progress",
        "queued behind",
        "lease",
        "invalidation race",
        "asset race",
    ),
    "QA-oracle false positive": (
        "false positive",
        "false red",
        "auto-rollback",
        "rolled back",
        "rollback reverted",
        "healthy deploy",
        "canary residue",
        "cold-start",
        "cold lambda",
    ),
    "timezone / wallclock": ("timezone", "utc", "pacific", "wallclock", "dst", "midnight"),
    "IAM / permission": ("iam", "accessdenied", "permission", "policy", "grant", "role"),
    "deployment error": ("deploy", "bundle", "zip", "packaging", "handler", "cdk drift"),
    "stale config / literal drift": ("stale", "literal", "drift", "hardcoded", "env var"),
    "data quality / scoring": ("scoring", "dedup", "sign error", "zero-score", "arithmetic"),
    "secret / credential": ("secret", "credential", "token", "re-auth", "oauth"),
}

# The orthogonal axis. A row is SILENT when it failed without announcing itself — nothing
# paged, nothing reddened, and it was found by someone looking. These are the phrases the
# corpus uses for that.
_SILENT_MARKERS = (
    "silent",
    "silently",
    "swallow",
    "no alarm",
    "nothing alarms",
    "went green",
    "reads green",
    "unnoticed",
    "invisible",
    "no signal",
    "dark",
    "undetected",
)


def _parse_ttd(cell: str) -> float | None:
    """Minutes from a TTD cell, or None when it states no duration.

    Deliberately conservative: it reads the FIRST duration in the cell and ignores prose.
    A cell like "~2 min — the post-merge run check, not a notification" is 2.0; a cell like
    "Real-time (deploy watcher)" is 0.0; anything it cannot read is None and is excluded
    from the medians rather than counted as zero.
    """
    text = cell.lower()
    if "real-time" in text or "immediate" in text or "realtime" in text:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes|wk|week|weeks)\b", text)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)
    if unit.startswith("d"):
        return value * 1440
    if unit.startswith("w"):
        return value * 10080
    if unit.startswith(("h",)):
        return value * 60
    return value


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values)) if values else None


def _ttd_profile(rows: list[dict]) -> dict:
    """The TTD facts the doc's silent-vs-loud sub-table states.

    #2975 acceptance box 4: `ttd_parseable`, `mean_ttd` and `exceeded_1_day` were stated
    in the doc but never emitted — they were recomputed BY HAND through parse_rows() when
    the section was written, which is the exact rot the #2840 derivation replaced, one
    column to the right. Emitted now, so the sub-table regenerates with everything else.
    """
    parsed = [r["ttd_minutes"] for r in rows if r["ttd_minutes"] is not None]
    return {
        "rows": len(rows),
        "ttd_parseable": len(parsed),
        "median_ttd_minutes": _median(parsed),
        "mean_ttd_minutes": _mean(parsed),
        "exceeded_1_day": sum(1 for v in parsed if v > 1440),
        "exceeded_1_week": sum(1 for v in parsed if v > 10080),
    }


def parse_rows(path: Path | None = None) -> list[dict]:
    """Every dated incident row, with its class matches and silence verdict."""
    text = (path or INCIDENT_LOG).read_text(encoding="utf-8")
    rows: list[dict] = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        date, sev_cell, rest = m.group(1), m.group(2), m.group(3)
        sev_match = _SEVERITY.search(sev_cell)
        severity = (
            sev_match.group(1).upper().replace("DR DRILL", "DR drill").replace("LOW", "Low").replace("INFO", "Info")
            if sev_match
            else "unlabelled"
        )
        cells = [c.strip() for c in rest.split("|")]
        body = " ".join(cells[:2]).lower()  # summary + root cause
        ttd_cell = cells[2] if len(cells) > 2 else ""
        matched = [name for name, kws in CLASSES.items() if any(k in body for k in kws)]
        rows.append(
            {
                "date": date,
                "month": date[:7],
                "severity": severity,
                "classes": matched,
                "silent": any(k in body for k in _SILENT_MARKERS),
                "ttd_minutes": _parse_ttd(ttd_cell),
            }
        )
    return rows


def _months_zero_filled(rows: list[dict]) -> dict[str, int]:
    """Every month from the first row to the last, INCLUDING the empty ones.

    A Counter over observed months silently omits April, which is the single most
    load-bearing zero in the section (the "pre-July frequencies are FLOORS" finding is
    exactly that April has none). An omitted month reads as "no data collected"; a stated
    zero reads as "nothing was logged" — and only the second is the claim being made.
    """
    counts = Counter(r["month"] for r in rows)
    if not counts:
        return {}
    lo, hi = min(counts), max(counts)
    out, year, month = {}, int(lo[:4]), int(lo[5:7])
    while f"{year:04d}-{month:02d}" <= hi:
        key = f"{year:04d}-{month:02d}"
        out[key] = counts.get(key, 0)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def build(path: Path | None = None) -> dict:
    rows = parse_rows(path)
    silent = [r for r in rows if r["silent"]]
    loud = [r for r in rows if not r["silent"]]
    # Deterministic ordering: count desc, then name — never Counter insertion order, so a
    # tie cannot reshuffle the rendered table between runs and dirty the reconcile job.
    by_class = dict(sorted(Counter(c for r in rows for c in r["classes"]).items(), key=lambda kv: (-kv[1], kv[0])))
    return {
        "total_rows": len(rows),
        "newest_row": max((r["date"] for r in rows), default=""),
        "by_month": _months_zero_filled(rows),
        "by_severity": dict(sorted(Counter(r["severity"] for r in rows).items())),
        "by_class": by_class,
        "unclassified": sum(1 for r in rows if not r["classes"]),
        "post_june_rows": sum(1 for r in rows if r["month"] >= "2026-07"),
        "ttd_unparseable": sum(1 for r in rows if r["ttd_minutes"] is None),
        "silence_axis": {
            "silent_rows": len(silent),
            "loud_rows": len(loud),
            "median_ttd_minutes_silent": _median([r["ttd_minutes"] for r in silent if r["ttd_minutes"] is not None]),
            "median_ttd_minutes_loud": _median([r["ttd_minutes"] for r in loud if r["ttd_minutes"] is not None]),
            "silent": _ttd_profile(silent),
            "loud": _ttd_profile(loud),
            "silent_by_class": dict(Counter(c for r in silent for c in r["classes"]).most_common()),
        },
    }


# ── the writer (#2975) ────────────────────────────────────────────────────────
#
# Marker-delimited so the DERIVED numbers and the INTERPRETIVE prose can share the
# section without the generator owning the judgement. Everything between a START and its
# END is regenerated wholesale; everything outside is hand-written and never touched. The
# split is deliberate: "38 of 155 rows are silent" is arithmetic, "every mitigation that
# has moved the numbers works by making a silent class loud" is a conclusion, and a
# generator that rewrote the second would delete the reason the section exists.
_MARK = "<!-- INCIDENT-PATTERNS:{name}:{edge} (generated by scripts/incident_log_patterns.py — do not hand-edit) -->"
_MARK_END = "<!-- INCIDENT-PATTERNS:{name}:END -->"

# The doc's severity ordering — severity rank first, then the non-P labels. `sorted()`
# would print "DR drill · Info · Low · P1 …", which reads as noise-first.
_SEVERITY_ORDER = ("P1", "P2", "P3", "P4", "Low", "Info", "DR drill")

# Display names for the three classes the pre-#2840 hand tally omitted (plural prose
# forms of the CLASSES keys, which appear verbatim in the table above them).
_TOP3 = {
    "QA-oracle false positive": "QA-oracle false positives",
    "lane-subset / union-breach main red": "lane-subset/union-breach main reds",
    "deploy-plane wedge / strand / race": "deploy-plane wedges/strands/races",
}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _ratio(a: float | None, b: float | None) -> str:
    """'~N.N×' for a vs b, or '(not comparable)' when either side has no median."""
    if not a or not b:
        return "(not comparable)"
    return f"~{a / b:.1f}×"


def _mins(value: float | None) -> str:
    """A minute count for prose: no trailing '.0', thousands separated."""
    return "—" if value is None else f"{int(value):,}" if float(value).is_integer() else f"{value:,.1f}"


_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_SPELLED = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def _spell(n: int) -> str:
    return _SPELLED[n] if n < len(_SPELLED) else str(n)


def _month_name(key: str) -> str:
    return _MONTH_NAMES[int(key[5:7]) - 1]


def _and_list(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def render_distribution(d: dict) -> str:
    lines = [f"**Distribution — {d['total_rows']} dated rows, {d['post_june_rows']} post-June** (newest row {d['newest_row']}):", ""]
    lines += ["| month | rows |", "|---|---|"]
    for month, n in d["by_month"].items():
        lines.append(f"| {month} | {'**0**' if n == 0 else n} |")
    known = [s for s in _SEVERITY_ORDER if s in d["by_severity"]]
    rest = [s for s in d["by_severity"] if s not in _SEVERITY_ORDER]
    lines += ["", "**By severity:** " + " · ".join(f"{s} {d['by_severity'][s]}" for s in known + rest) + "."]
    lines += [
        "",
        "**By root-cause class** (keyword-derived over Summary + Root Cause; a row may match more",
        f"than one, and {d['unclassified']} match none):",
        "",
        "| n | class |",
        "|---|---|",
    ]
    for name, n in d["by_class"].items():
        lines.append(f"| {n} | {name} |")
    lines.append(f"| {d['unclassified']} | *(unclassified)* |")
    return "\n".join(lines)


def render_top_classes(d: dict) -> str:
    ranks = {name: i + 1 for i, name in enumerate(d["by_class"])}
    parts = [f"**{_TOP3[k]} ({d['by_class'].get(k, 0)})**" for k in _TOP3 if k in d["by_class"]]
    named = _and_list(parts)
    places = [_ordinal(ranks[k]) for k in _TOP3 if k in ranks]
    where = _and_list(places) or "unranked"
    largest = next(iter(d["by_class"]), "—")
    return (
        f"The three classes the old list omitted entirely — {named} — are now the {where} largest. "
        f"They are the shape of this platform's failures *today*; **{largest}** remains the largest single "
        "class but is increasingly a co-tag on those three rather than a category of its own."
    )


def render_silence(d: dict) -> str:
    ax = d["silence_axis"]
    s, ln = ax["silent"], ax["loud"]
    total = d["total_rows"]
    mean_gap = _pct(
        abs((s["mean_ttd_minutes"] or 0) - (ln["mean_ttd_minutes"] or 0)), max(s["mean_ttd_minutes"] or 1, ln["mean_ttd_minutes"] or 1)
    )
    day_rate_s, day_rate_l = _pct(s["exceeded_1_day"], s["ttd_parseable"]), _pct(ln["exceeded_1_day"], ln["ttd_parseable"])
    return "\n".join(
        [
            f"**{s['rows']} of {total} rows are silent.**",
            "",
            "| | silent | loud |",
            "|---|---|---|",
            f"| rows | {s['rows']} | {ln['rows']} |",
            f"| TTD parseable | {s['ttd_parseable']} | {ln['ttd_parseable']} |",
            f"| median TTD | **{_mins(s['median_ttd_minutes'])} min** | {_mins(ln['median_ttd_minutes'])} min |",
            f"| mean TTD | {_mins(s['mean_ttd_minutes'])} min | {_mins(ln['mean_ttd_minutes'])} min |",
            f"| exceeded 1 day | {s['exceeded_1_day']} ({day_rate_s}% of parsed) | {ln['exceeded_1_day']} ({day_rate_l}% of parsed) |",
            "",
            f"Silent rows take **{_ratio(s['median_ttd_minutes'], ln['median_ttd_minutes'])} longer to detect at the "
            f"median** and are **{_ratio(day_rate_s, day_rate_l)} more likely to run past a day**. But the *means* are "
            f'only {mean_gap}% apart, and the "days-scale TTD for silent vs minutes for loud" framing does **not** '
            "reproduce over the population — it comes from reading the worst handful of silent rows, and the loud set "
            f"has its own long tail ({ln['exceeded_1_week']} rows past a week, vs {s['exceeded_1_week']} silent). "
            "**Two caveats that bound all of this:** the classifier is keyword-based over free prose, and "
            f"**{d['ttd_unparseable']} of {total} TTD cells ({_pct(d['ttd_unparseable'], total)}%) state no parseable "
            "duration** — they are excluded rather than counted as zero.",
        ]
    )


def render_floors(d: dict) -> str:
    """The pre-July-vs-post-July sentence. Its numbers are the same per-month counts the
    table above states, and were hand-pasted — so the section arguing that a stale
    denominator misleads a reader carried its own staling denominators."""
    months = d["by_month"]
    pre = [(k, v) for k, v in months.items() if k < "2026-07"]
    post = [(k, v) for k, v in months.items() if k >= "2026-07"]
    empty = [_month_name(k) for k, v in pre if v == 0]
    nonempty = [f"{_month_name(k)} has {_spell(v)}" for k, v in pre if v > 0 and k >= "2026-04"]
    lead = _and_list([f"{m} has zero rows" for m in empty] + nonempty) or "the pre-July months are near-empty"
    against = _and_list([f"{v} in {_month_name(k)}" for k, v in post])
    return (
        f"**{lead}**, against {against}. The platform was not stable in those months — it was under-logged. "
        'Two proofs: the 2026-08-02 Whoop row cites *"the same class as the 2026-06 outage"* and no June Whoop '
        "row existed until #2840 backfilled it, and two shipped timezone fixes (#2675, #2670) left no rows at all. "
        "Never compare a pre-July class frequency against a post-July one and call the difference a trend; the "
        "denominator is not the same instrument."
    )


_RENDERERS = {
    "DISTRIBUTION": render_distribution,
    "TOPCLASSES": render_top_classes,
    "SILENCE": render_silence,
    "FLOORS": render_floors,
}


def render_doc(src: str, data: dict) -> str:
    """Rewrite every marker-delimited derived block. Missing markers are a hard error —
    a writer that silently wrote nothing would be the #2840 defect wearing a fix's clothes.
    """
    out = src
    for name, renderer in _RENDERERS.items():
        start, end = _MARK.format(name=name, edge="START"), _MARK_END.format(name=name)
        if start not in out or end not in out:
            raise SystemExit(f"error: {name} markers not found in {INCIDENT_LOG} — add {start} … {end} around the derived block")
        pre, rest = out.split(start, 1)
        _, post = rest.split(end, 1)
        out = f"{pre}{start}\n{renderer(data)}\n{end}{post}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--check", action="store_true", help="non-mutating: exit 1 if the derived blocks are stale")
    ap.add_argument("--apply", action="store_true", help="rewrite the derived blocks in docs/INCIDENT_LOG.md")
    args = ap.parse_args()
    data = build()

    if args.check and args.apply:
        print("error: --check and --apply are mutually exclusive", file=sys.stderr)
        return 2

    if args.check or args.apply:
        # Sanity floor, same reflex as generate_adr_index: a parse regression must never
        # be allowed to WRITE. Regenerating from a broken parse would replace correct
        # numbers with confident wrong ones and pass its own guard doing it.
        if data["total_rows"] < 100:
            print(f"error: only {data['total_rows']} rows parsed (< 100) — refusing to regenerate", file=sys.stderr)
            return 2
        src = INCIDENT_LOG.read_text(encoding="utf-8")
        new = render_doc(src, data)
        if new == src:
            print(f"✅ INCIDENT_LOG Patterns section current ({data['total_rows']} rows, {data['post_june_rows']} post-June).")
            return 0
        if args.check:
            print(
                f"❌ INCIDENT_LOG Patterns section is STALE — the rows now say {data['total_rows']} dated "
                f"({data['post_june_rows']} post-June). Fix: python3 scripts/incident_log_patterns.py --apply",
                file=sys.stderr,
            )
            return 1
        INCIDENT_LOG.write_text(new, encoding="utf-8")
        print(f"✅ regenerated INCIDENT_LOG Patterns section ({data['total_rows']} rows, {data['post_june_rows']} post-June).")
        return 0

    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    print(f"INCIDENT_LOG — {data['total_rows']} dated rows ({data['post_june_rows']} post-June)\n")
    print("By month:")
    for month, n in data["by_month"].items():
        print(f"  {month}  {n:3}  {'#' * n}")
    print("\nBy severity:")
    for sev, n in data["by_severity"].items():
        print(f"  {sev}  {n:3}")
    print("\nBy root-cause class (a row may match several):")
    for name, n in data["by_class"].items():
        print(f"  {n:3}  {name}")
    print(f"  {data['unclassified']:3}  (unclassified — no keyword matched)")
    axis = data["silence_axis"]
    print("\nSilence axis (orthogonal to class):")
    print(f"  silent rows {axis['silent_rows']}   loud rows {axis['loud_rows']}")
    print(f"  median TTD  silent {axis['median_ttd_minutes_silent']}  loud {axis['median_ttd_minutes_loud']}  (minutes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
