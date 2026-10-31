#!/usr/bin/env python3
"""scripts/check_served_coach_facts.py — the served coach corpus against the served facts (#4185 box 4, #4343).

WHY
  `coach.coach_input_facts.served_fact_findings` is the generation-time gate: a coach's draft
  that cites a protein / days-logged / logging-gap / weight / loss-rate figure the engine's
  own served facts contradict is regenerated or held (ADR-108). It only ever sees a DRAFT.
  Text that is already served — a lead read, a stored summary, a voice example on the coach
  page — never passes through it again, so a figure that was wrong when written, or became
  wrong when the facts moved, stays on the public surface with nothing saying so.

WHAT IT DOES
  1. Fetches every coach surface a reader can open: `/api/coach/<id>` for every persona the
     `/api/coaches` roster lists, plus `/api/coaching-dashboard`, `/api/coach_team` and
     `/api/coaches` itself, and walks every string longer than 40 characters (JSON path kept).
  2. Builds the served facts through the SAME function the gate uses
     (`coach_input_facts.served_run_facts`), from what the site serves:
     `/api/nutrition_overview.nutrition_trend` (each day's `protein_g` as `total_protein_g`)
     and `/api/journey` (`current_weight_lbs`, `weekly_rate_lbs` and its CI).
  3. A coach line is judged as-of the day it was written (#4580): `moves.lines[].date`, joined to
     the same text served undated as `/api/coach/<id>` `daily`. The window it saw then held days
     the 30-day window has since dropped, so a correct "30 logged days" is not a contradiction
     tomorrow. A text with no discoverable date keeps today's comparison.
  4. Runs `served_fact_findings` on each text and prints one line per finding: the JSON path,
     the cited figure and the served value. Never the whole text — the path is the triage key.

EXIT
  0 — no served text contradicts a served fact.
  1 — at least one finding (each named by path, figure and served value).
  2 — UNEVALUABLE: a fetch failed, the roster was empty, or the facts could not be built.
      Loud, never a pass: a probe that could not look is not a clean corpus.

USAGE
  python3 scripts/check_served_coach_facts.py [--base-url https://averagejoematt.com]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))

DEFAULT_BASE_URL = "https://averagejoematt.com"
MIN_TEXT_CHARS = 40
FIXED_SURFACES = ("/api/coaches", "/api/coaching-dashboard", "/api/coach_team")


def _fetch(base_url: str, path: str) -> dict:
    req = urllib.request.Request(base_url.rstrip("/") + path, headers={"User-Agent": "served-coach-facts/1.0 (#4343)"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 — fixed https host
        return json.loads(resp.read().decode("utf-8"))


def served_texts(payloads: dict) -> list:
    """[(json_path, text)] for every string longer than MIN_TEXT_CHARS in each payload."""
    out: list = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and len(node) > MIN_TEXT_CHARS:
            out.append((path, node))

    for endpoint, body in payloads.items():
        walk(body, f"{endpoint} $")
    return out


def line_dates(payloads: dict) -> dict:
    """{text: day} for every served coach line that carries its own date (#4580).

    `/api/coaching-dashboard` `moves.lines[]` carry `date` beside `text`; the same line is
    served again as `/api/coach/<id>` `daily`, which has no date of its own, so the text is
    the join key. A line was written on its own day against that day's window, so it is judged
    as-of that day. A text with no discoverable date is absent here (today's comparison)."""
    moves = ((payloads.get("/api/coaching-dashboard") or {}).get("moves")) or {}
    out: dict = {}
    for ln in moves.get("lines") or []:
        if isinstance(ln, dict) and isinstance(ln.get("text"), str):
            day = str(ln.get("date") or moves.get("date") or "")[:10]
            if len(day) == 10:
                out[ln["text"]] = day
    return out


def facts_from_served(nutrition_overview: dict, journey: dict, today: str | None = None, as_of: str | None = None) -> dict | None:
    """The gate's facts, built from what the site serves (the SAME `served_run_facts`).

    `as_of` (a day before `today`) builds the facts a line written on that day was judged
    against: the trend rows up to that day, `today=as_of`, and `days_logged` credited with the
    days the 30-day window has since dropped off its front (no longer served, so unknowable;
    an upper bound, the right direction for a "claims more days than exist" check). A real
    over-claim still fires; nothing here is a blanket tolerance (#4580)."""
    from coach import coach_input_facts as cif
    from common.pacific_time import pacific_today

    trend = (nutrition_overview or {}).get("nutrition_trend")
    jr = (journey or {}).get("journey") or {}
    if not isinstance(trend, list):
        return None
    rows = [{"date": r.get("date"), "total_protein_g": r.get("protein_g")} for r in trend if isinstance(r, dict)]
    data = {
        "macrofactor_window": rows,
        "latest_weight": jr.get("current_weight_lbs"),
        "weekly_rate_lbs": jr.get("weekly_rate_lbs"),
        "weekly_rate_ci_low": jr.get("weekly_rate_ci_low"),
        "weekly_rate_ci_high": jr.get("weekly_rate_ci_high"),
    }
    if not as_of or as_of >= (today or pacific_today()):
        return cif.served_run_facts(data, table=None, today=today)
    now = today or pacific_today()
    dropped = _dropped_days(rows, as_of, now)
    data["macrofactor_window"] = [r for r in rows if str(r.get("date") or "")[:10] <= as_of]
    facts = cif.served_run_facts(data, table=None, today=as_of)
    nut = (facts or {}).get("nutrition")
    if nut and dropped:
        facts = {**facts, "nutrition": {**nut, "days_logged": nut["days_logged"] + dropped}}
    return facts


def _dropped_days(rows: list, as_of: str, today: str) -> int:
    """Days of the window ending `as_of` that the window ending `today` no longer serves
    (calendar days from the old window's start up to the new one's, none already in `rows`)."""
    from datetime import date, timedelta

    from common.constants import EXPERIMENT_START_DATE
    from health import nutrition_logging as _nl

    old, new = _nl.window_start(as_of, EXPERIMENT_START_DATE), _nl.window_start(today, EXPERIMENT_START_DATE)
    have = {str(r.get("date") or "")[:10] for r in rows}
    d, n = date.fromisoformat(old), 0
    while d.isoformat() < min(new, (date.fromisoformat(as_of) + timedelta(days=1)).isoformat()):
        n += d.isoformat() not in have
        d += timedelta(days=1)
    return n


def findings(texts: list, facts: dict, today: str | None = None, dates: dict | None = None, facts_for=None) -> list:
    """[(json_path, finding)] — every served text's contradictions of the served facts.

    A text found in `dates` (#4580: {text: day}) is judged against `facts_for(day)` — the facts
    as of the day it was written — and that day; any other text against `facts`, today."""
    from coach import coach_input_facts as cif

    out = []
    for path, text in texts:
        day = (dates or {}).get(text)
        f_as, t_as = (facts_for(day), day) if day and facts_for else (facts, today)
        for f in cif.served_fact_findings(text, f_as or facts, today=t_as if f_as else today):
            out.append((path, f))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = ap.parse_args(argv)
    try:
        roster = _fetch(args.base_url, "/api/coaches")
        ids = [c.get("persona_id") for c in roster.get("coaches") or [] if c.get("persona_id")]
        if not ids:
            print("UNEVALUABLE — /api/coaches served no roster; nothing was checked.")
            return 2
        payloads = {p: (roster if p == "/api/coaches" else _fetch(args.base_url, p)) for p in FIXED_SURFACES}
        for pid in ids:
            payloads[f"/api/coach/{pid}"] = _fetch(args.base_url, f"/api/coach/{pid}")
        nutrition_overview, journey = _fetch(args.base_url, "/api/nutrition_overview"), _fetch(args.base_url, "/api/journey")
        facts = facts_from_served(nutrition_overview, journey)
    except Exception as exc:  # any fetch/parse failure is UNEVALUABLE, never a pass
        print(f"UNEVALUABLE — {type(exc).__name__}: {exc}")
        return 2
    if not facts or not (facts.get("nutrition") or facts.get("weight")):
        print("UNEVALUABLE — the served facts could not be built (no nutrition trend and no weight trajectory).")
        return 2
    texts = served_texts(payloads)
    hits = findings(
        texts,
        facts,
        dates=line_dates(payloads),
        facts_for=lambda day: facts_from_served(nutrition_overview, journey, as_of=day),
    )
    for path, f in hits:
        print(f"  {path}  {f.get('metric')}: cites {f.get('cited')}, served {f.get('canonical')} — {f.get('detail')}")
    verdict = "OK" if not hits else "NONGREEN"
    print(f"SERVED-COACH-FACTS VERDICT {verdict} surfaces={len(payloads)} personas={len(ids)} texts={len(texts)} findings={len(hits)}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
