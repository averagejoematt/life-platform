#!/usr/bin/env python3
"""scripts/check_coach_verdict_agreement.py — do the public surfaces' coach texts agree with each call's CURRENT grade?

Owner ruling (2026-11-03): "Corrected authoritative grades must flow into coach-facing summaries and future
narratives. A coach must not continue claiming a prediction was wrong, right or measurable after its authoritative
classification has changed … Fix the Mind coach's incorrect protein narrative and verify that the dashboard, coach
page, ledger and Day pages agree."

READ-ONLY. Public GETs against the site, plus (``--statuses ddb``, the default) a projected Query of every coach's
``PREDICTION#`` partition for the authoritative status of every call — including the calls the public ledger withholds
by the journal-silence rule (#5131), which a public-only check could not see. ``--statuses api`` uses the public
ledger alone. Nothing is written anywhere.

WHAT IS CHECKED. Every prose string on:

* ``/api/coaching-dashboard`` — each coach's ``position_summary``, the lead's daily read, the moves, the open asks;
* ``/api/coach/<persona_id>`` for every coach on ``/api/coaches`` — every string leaf (stance, daily, timeline,
  learnings, memoir, latest-checked …);
* ``/api/ledger_export`` (all pages) — each item's grader words (``grading.outcome_notes``) against its own status;
* the v9 Day pages ``/data/day/<date>/`` (``--days N`` newest, default 30) — every verbatim coach quotation, with the
  dated correction notes printed beside it.

A text FAILS when it calls a call right / wrong / checked against that call's current grade
(``lambdas/coach/verdict_claims.findings`` — the same rule the writer and the read sites apply), matched against
every coach's calls (a coach quoting another coach's call is checked too). A finding on a text that already carries a
dated correction beside it (``corrections`` / ``summary_corrections`` / ``grade_correction`` on the same object, or a
``<p class="correction">`` in the Day page's figure) is reported as ANNOTATED, not as a failure: a verbatim quotation
with its correction beside it is the ruling's intended state.

Exit 0: no unannotated contradiction. Exit 1: at least one. Exit 2: a surface could not be read.

    python3 scripts/check_coach_verdict_agreement.py                 # live, statuses from DynamoDB (read-only)
    python3 scripts/check_coach_verdict_agreement.py --statuses api  # public ledger only
    python3 scripts/check_coach_verdict_agreement.py --json out.json
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.request
from typing import Any, Iterator

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))

from coach import verdict_claims  # noqa: E402
from coach.persona_registry import OPERATIONAL_COACH_IDS  # noqa: E402 — the roster, never a hand copy (#2334)

BASE = "https://averagejoematt.com"
_TODAY = __import__("datetime").date.today().isoformat()
_ANNOTATION_KEYS = ("corrections", "summary_corrections", "grade_correction", "grade_corrections")
#: Not coach prose about calls: identifiers, the persona's static character sheet, and the correction records
#: themselves (their registered explanations ARE the authoritative words).
_SKIP_KEYS = frozenset(
    (
        "_meta",
        "prediction_id",
        "item_id",
        "sk",
        "pk",
        "id",
        "voice",
        "trait_scores",
        "philosophy",
        "short_bio",
        "character",
        "expertise",
        "disclosure",
        "corrections",
        "summary_corrections",
        "grade_correction",
        "grade_corrections",
    )
)
_FIGURE = re.compile(r'<figure class="voice[^"]*">(.*?)</figure>\s*((?:<p class="correction"[^>]*>.*?</p>\s*)*)', re.S)
_QUOTE = re.compile(r'<blockquote[^>]*data-verbatim="coach"[^>]*>(.*?)</blockquote>', re.S)
_CORR = re.compile(r'<p class="correction"[^>]*>(.*?)</p>', re.S)
_TAG = re.compile(r"<[^>]+>")
_WORDY = re.compile(r"[A-Za-z]{3,}.*\s.*[A-Za-z]{3,}")


def get_json(path: str, base: str = BASE, timeout: float = 30.0) -> Any:
    req = urllib.request.Request(base + path, headers={"User-Agent": "life-platform-verdict-agreement/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed https base
        return json.loads(r.read().decode())


def get_text(path: str, base: str = BASE, timeout: float = 30.0) -> str:
    req = urllib.request.Request(base + path, headers={"User-Agent": "life-platform-verdict-agreement/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return r.read().decode()


def ledger_items(base: str = BASE) -> list[dict]:
    first = get_json("/api/ledger_export?page=1&size=100", base)
    items = list(first.get("items") or [])
    for p in range(2, int(first.get("pages") or 1) + 1):
        items.extend(get_json(f"/api/ledger_export?page={p}&size=100", base).get("items") or [])
    return items


def calls_from_ledger(items: list[dict]) -> list[dict]:
    return [
        {"prediction_id": i.get("prediction_id"), "coach": i.get("coach_id"), "claim": i.get("claim") or "", "status": i.get("status")}
        for i in items
        if i.get("claim")
    ]


def calls_from_ddb(shorts: list[str]) -> list[dict]:
    import boto3
    from coach import authoritative_grades

    table = boto3.resource("dynamodb", region_name="us-west-2").Table(os.environ.get("TABLE_NAME", "life-platform"))
    out = []
    for short in shorts:
        rows = authoritative_grades.prediction_rows(table, f"{short}_coach")
        for c in authoritative_grades.calls_of(rows):
            out.append({**c, "coach": short})
    return out


def string_leaves(obj: Any, path: str = "", parent: Any = None) -> Iterator[tuple[str, str, Any]]:
    """``(path, text, the object holding it)`` for every prose-like string leaf."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SKIP_KEYS:
                continue
            yield from string_leaves(v, f"{path}.{k}" if path else k, obj)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from string_leaves(v, f"{path}[{i}]", parent if not isinstance(v, dict) else v)
    elif isinstance(obj, str) and len(obj) > 25 and _WORDY.search(obj):
        yield path, obj, parent


def annotated(holder: Any) -> bool:
    return isinstance(holder, dict) and any(holder.get(k) for k in _ANNOTATION_KEYS)


def _short(coach_id: Any) -> str:
    c = str(coach_id or "")
    return c[: -len("_coach")] if c.endswith("_coach") else c


def scoped(calls: list[dict], text: str, owner: str | None, names: dict[str, str]) -> list[dict]:
    """The calls a text can be about: its own coach's, and those of any coach it names (full or last name)."""
    who = {_short(owner)} if owner else set()
    low = text.lower()
    for name, short in names.items():
        if name.lower() in low or name.split()[-1].lower() in low:
            who.add(short)
    return [c for c in calls if c.get("coach") in who] if who else calls


def _owner(holder: Any, default: str | None) -> str | None:
    if isinstance(holder, dict):
        for k in ("coach_id", "persona_id"):
            if holder.get(k) and str(holder.get(k)) not in ("eli_marsh",):
                return str(holder[k])
    return default


def check_json(surface: str, payload: Any, calls: list[dict], names: dict[str, str] | None = None, owner: str | None = None) -> list[dict]:
    out = []
    for path, text, holder in string_leaves(payload):
        for f in verdict_claims.findings(text, scoped(calls, text, _owner(holder, owner), names or {}), as_of=_TODAY):
            out.append({"surface": surface, "path": path, **f, "annotated": annotated(holder), "text": text[:300]})
    return out


def check_ledger(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        notes = ((it.get("grading") or {}).get("outcome_notes")) or ""
        call = [{"prediction_id": it.get("prediction_id"), "claim": it.get("claim") or "", "status": it.get("status")}]
        for f in verdict_claims.findings(notes, call, as_of=None):
            out.append(
                {
                    "surface": "/api/ledger_export",
                    "path": f"{it.get('item_id')}.grading.outcome_notes",
                    **f,
                    "annotated": False,
                    "text": notes[:300],
                }
            )
    return out


_WHO = re.compile(r'<figcaption class="who">(.*?)</figcaption>', re.S)


def check_day_html(day: str, page: str, calls: list[dict], names: dict[str, str] | None = None) -> list[dict]:
    names = names or {}
    out = []
    for m in _FIGURE.finditer(page):
        body, tail = m.group(1), m.group(2)
        q = _QUOTE.search(body)
        if not q:
            continue
        text = html.unescape(_TAG.sub("", q.group(1))).strip()
        who = _WHO.search(body)
        speaker = html.unescape(_TAG.sub("", who.group(1))).split("·")[0].strip() if who else ""
        notes = [html.unescape(_TAG.sub("", c)).strip() for c in _CORR.findall(body + tail)]
        for f in verdict_claims.findings(text, scoped(calls, text, names.get(speaker), names), as_of=day):
            out.append(
                {"surface": f"/data/day/{day}/", "path": "coach_lines", **f, "annotated": bool(notes), "notes": notes, "text": text[:300]}
            )
    return out


def run(base: str, statuses: str, days: int) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    items = ledger_items(base)
    shorts = sorted({str(i.get("coach_id")) for i in items if i.get("coach_id")} | {_short(c) for c in OPERATIONAL_COACH_IDS})
    calls = calls_from_ddb(shorts) if statuses == "ddb" else calls_from_ledger(items)
    findings: list[dict] = []
    try:
        dash = get_json("/api/coaching-dashboard", base)
    except Exception as e:  # noqa: BLE001
        dash, _ = None, errors.append(f"/api/coaching-dashboard: {e}")
    try:
        coaches = get_json("/api/coaches", base).get("coaches") or []
    except Exception as e:  # noqa: BLE001
        coaches, _ = [], errors.append(f"/api/coaches: {e}")
    roster = [c.get("persona_id") for c in coaches if c.get("persona_id")]
    names = {
        str(c["name"]): _short(c["persona_id"]) for c in coaches if c.get("name") and c.get("persona_id") and c["persona_id"] != "eli_marsh"
    }
    if dash is not None:
        findings += check_json("/api/coaching-dashboard", dash, calls, names)
    for pid in roster:
        try:
            findings += check_json(
                f"/api/coach/{pid}", get_json(f"/api/coach/{pid}", base), calls, names, owner=None if pid == "eli_marsh" else pid
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"/api/coach/{pid}: {e}")
    findings += check_ledger(items)
    try:
        index = get_json("/data/days.json", base)
        for d in [x.get("date") for x in index if isinstance(x, dict)][-days:]:
            try:
                findings += check_day_html(d, get_text(f"/data/day/{d}/", base), calls, names)
            except Exception as e:  # noqa: BLE001
                errors.append(f"/data/day/{d}/: {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"/data/days.json: {e}")
    return findings, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--statuses", choices=("ddb", "api"), default="ddb")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", help="write the findings here")
    a = ap.parse_args(argv)
    findings, errors = run(a.base, a.statuses, a.days)
    bad = [f for f in findings if not f["annotated"]]
    for f in findings:
        tag = "ANNOTATED" if f["annotated"] else "CONTRADICTS"
        print(
            f"{tag:11} {f['surface']} {f['path']}\n            says {f['asserted']!r} about {f['prediction_id']} (current: {f['status_words']})\n            “{f['sentence'][:220]}”"
        )
    for e in errors:
        print(f"UNREAD      {e}")
    print(f"\n{len(bad)} unannotated contradiction(s), {len(findings) - len(bad)} annotated, {len(errors)} surface(s) unread.")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"findings": findings, "errors": errors}, fh, indent=2, default=str)
    return 2 if errors else (1 if bad else 0)


if __name__ == "__main__":
    sys.exit(main())
