#!/usr/bin/env python3
"""scripts/capture_kit_page_fixtures.py — re-capture every kit page fixture in ONE pass (#4671).

The kit page gate (tests/kit_page_gate.py) and the kit page JS tests (tests/js/ck_*.test.mjs)
read committed captures of the live site's routes from tests/fixtures/kit_pages_4586/. Taken
file by file on different days, those captures contradicted each other (a record of 41 of 96
on the front page, 45 of 106 on every coach page), and every local render and red-team round
showed the mismatch as if the live site carried it.

This script is the only way that directory is written:

  * every route is fetched first, with read-only GETs against the live site, and nothing is
    written until every fetch has answered 200 with JSON;
  * the captured set is checked for one record (``record_disagreements`` below — the same
    check tests/test_kit_page_fixtures_agree_4671.py holds the committed set to) and nothing
    is written if it disagrees (a CloudFront copy one cache window older than its neighbour
    can do that: wait the window out and run again);
  * then every file is written, and ``_capture.json`` records the one capture time, the site
    it came from and the address behind each file.

The day pages' coach lines are captured for every day the gate opens (each ``?d=`` in
``KIT_PAGES``) and for the newest day the captured pulse and workouts carry (the day page with
no ``?d=``), one ``coach_moves_<day>.json`` each; the gate routes each file to its own day.

Usage:
    python3 scripts/capture_kit_page_fixtures.py            # capture and write
    python3 scripts/capture_kit_page_fixtures.py --check    # capture, report, write nothing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(REPO, "tests", "fixtures", "kit_pages_4586")
MANIFEST = "_capture.json"
BASE = "https://averagejoematt.com"
USER_AGENT = "life-platform-kit-fixture-capture/4671 (read-only)"

#: fixture file -> the address it is captured from. Every file the gate routes and every file
#: a kit page JS test loads; a file in the directory that is not here is stale by definition.
CAPTURES = {
    "edition.json": "/api/edition",
    "posts.json": "/journal/posts.json",
    "episodes.json": "/panelcast/episodes.json",
    "transcript_wk4.json": "/panelcast/wk4.transcript.json",
    "coaches.json": "/api/coaches",
    "coach_docket.json": "/api/coach_docket",
    "coach_docket_full.json": "/api/coach_docket",
    "coach_sleep_coach.json": "/api/coach/sleep_coach",
    "coach_physical_coach.json": "/api/coach/physical_coach",
    "coach_glucose_coach.json": "/api/coach/glucose_coach",
    "coach_mind_coach.json": "/api/coach/mind_coach",
    "coach_eli_marsh.json": "/api/coach/eli_marsh",
    "predictions.json": "/api/predictions",
    "predictions_sleep.json": "/api/predictions?coach_id=sleep&status=pending&limit=200",
    "predictions_physical.json": "/api/predictions?coach_id=physical&status=pending&limit=200",
    "predictions_glucose.json": "/api/predictions?coach_id=glucose&status=pending&limit=200",
    "calls.json": "/api/calls",
    "timeline.json": "/api/timeline",
    "pulse_history.json": "/api/pulse_history",
    "workouts.json": "/api/workouts",
    "training_overview.json": "/api/training_overview",
    "nutrition_overview.json": "/api/nutrition_overview",
    "frequent_meals.json": "/api/frequent_meals",
    "weekly_priority.json": "/api/weekly_priority",
    "character.json": "/api/character",
    "achievements.json": "/api/achievements",
    "platform_stats.json": "/api/platform_stats",
    "receipts.json": "/api/receipts",
}

_DAY = re.compile(r"[?&]d=(\d{4}-\d{2}-\d{2})\b")


def moves_file(day: str) -> str:
    return f"coach_moves_{day}.json"


def gate_days() -> list:
    """Every day the kit page gate opens a day page on (the ``?d=`` in its KIT_PAGES)."""
    sys.path.insert(0, os.path.join(REPO, "tests"))
    import kit_page_gate  # stdlib-only at import; playwright is imported inside its main()

    return sorted({m.group(1) for path in kit_page_gate.KIT_PAGES for m in [_DAY.search(path)] if m})


def latest_day(pulse: dict, workouts: dict) -> str:
    """The day page with no ``?d=`` opens on this day — ck_depth.js latestDay, in Python."""
    days = [r.get("date") for r in (pulse or {}).get("pulse_history") or [] if isinstance(r, dict)]
    days += [w.get("date") for w in (workouts or {}).get("workouts") or [] if isinstance(w, dict)]
    days = sorted(d for d in days if isinstance(d, str) and d)
    return days[-1] if days else ""


def fetch(path: str, base: str = BASE):
    req = urllib.request.Request(base + path, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — a fixed https origin
        if resp.status != 200:
            raise RuntimeError(f"{path}: HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


# ── the one-record check ─────────────────────────────────────────────────────────────────


def _record(rec):
    """confirmed/refuted/n, or None for a coach with no checked call (the lead: the Coaches list
    serves null where the coach's own page serves zeros — both say "no record")."""
    if not isinstance(rec, dict) or not rec.get("n"):
        return None
    return {k: rec.get(k) for k in ("confirmed", "refuted", "n")}


def _record_of_coach_file(body):
    return _record((((body or {}).get("report_card") or {}).get("track_record") or {}).get("record"))


def record_disagreements(fx: dict) -> list:
    """Every way the captured set disagrees about the coaches' record, as sentences.

    ``fx`` maps fixture file name -> parsed body. Holds: the front page's record (edition
    ``record``: right of decided) equals the predictions totals (confirmed of confirmed +
    refuted) equals the sum of every coach's checked calls on the Coaches list; and each
    coach's record on the Coaches list equals the record its own coach file carries. A file
    the check needs that is missing is itself a disagreement — an unchecked set never passes.
    """
    out = []
    need = ("edition.json", "predictions.json", "coaches.json")
    missing = [n for n in need if not isinstance(fx.get(n), dict)]
    if missing:
        return [f"missing {', '.join(missing)}: the record cannot be checked"]

    rec = (((fx["edition.json"].get("blocks") or {}).get("record") or {}).get("data")) or {}
    edition = (rec.get("right"), rec.get("decided"))
    overall = fx["predictions.json"].get("overall") or {}
    predictions = (overall.get("confirmed"), (overall.get("confirmed") or 0) + (overall.get("refuted") or 0))
    if overall.get("decided") is not None and overall.get("decided") != predictions[1]:
        out.append(f"/api/predictions says decided {overall.get('decided')} but confirmed + refuted is {predictions[1]}")

    coaches = fx["coaches.json"].get("coaches") or []
    listed = {c.get("persona_id"): c.get("record") for c in coaches if isinstance(c, dict)}
    right = sum((r or {}).get("confirmed") or 0 for r in listed.values())
    decided = sum((r or {}).get("n") or 0 for r in listed.values())
    summed = (right, decided)

    if edition != predictions:
        out.append(f"the front page says {edition[0]} of {edition[1]} but /api/predictions says {predictions[0]} of {predictions[1]}")
    if summed != predictions:
        out.append(
            f"the coaches' checked calls sum to {summed[0]} of {summed[1]} but /api/predictions says {predictions[0]} of {predictions[1]}"
        )

    for name, body in sorted(fx.items()):
        if not (name.startswith("coach_") and name.endswith(".json")) or name.startswith(("coach_docket", "coach_moves")):
            continue
        pid = body.get("persona_id") if isinstance(body, dict) else None
        if pid not in listed:
            out.append(f"{name}: coach {pid!r} is not on the Coaches list")
            continue
        on_list = _record(listed[pid])
        own = _record_of_coach_file(body)
        if on_list != own:
            out.append(f"{name}: the Coaches list says {on_list} but the coach's own page says {own}")
    return out


def bet_disagreements(fx: dict) -> list:
    """A bet a day's coach lines name that the coach docket does not carry (#4671: the old
    2026-10-02 day file carried an October 9 bet no other capture had)."""
    docket = fx.get("coach_docket_full.json") or {}
    known = {e.get("resolution_date") for side in ("open", "resolved") for e in (docket.get(side) or []) if isinstance(e, dict)}
    out = []
    for name, body in sorted(fx.items()):
        if not name.startswith("coach_moves_") or not isinstance(body, dict):
            continue
        for line in body.get("lines") or []:
            settles = (line or {}).get("bet_settles")
            if settles and settles not in known:
                out.append(f"{name}: {line.get('coach')}'s bet settling {settles} is on no other capture (the docket has none that day)")
    return out


def capture(base: str = BASE) -> tuple:
    """Fetch the whole set -> ({file: body}, {file: address}). Writes nothing."""
    bodies, sources = {}, {}
    for name, path in CAPTURES.items():
        bodies[name], sources[name] = fetch(path, base), path
    days = set(gate_days())
    newest = latest_day(bodies["pulse_history.json"], bodies["workouts.json"])
    if newest:
        days.add(newest)
    for day in sorted(days):
        path = f"/api/coach_moves?date={day}"
        bodies[moves_file(day)], sources[moves_file(day)] = fetch(path, base), path
    return bodies, sources


def write(bodies: dict, sources: dict, captured_at: str, base: str, out_dir: str = FIXTURES_DIR) -> list:
    os.makedirs(out_dir, exist_ok=True)
    stale = sorted(n for n in os.listdir(out_dir) if n.endswith(".json") and n != MANIFEST and n not in bodies)
    for name in stale:  # a file no capture writes is a file from another day
        os.remove(os.path.join(out_dir, name))
    for name, body in bodies.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(body, indent=1, ensure_ascii=True) + "\n")
    manifest = {
        "captured_at": captured_at,
        "base": base,
        "by": "scripts/capture_kit_page_fixtures.py (#4671) — one pass, read-only GETs; re-run it, never hand-edit a file",
        "files": dict(sorted(sources.items())),
    }
    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, indent=1, ensure_ascii=True) + "\n")
    return stale


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", default=FIXTURES_DIR)
    ap.add_argument("--check", action="store_true", help="capture and report; write nothing")
    args = ap.parse_args(argv)

    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bodies, sources = capture(args.base)
    problems = record_disagreements(bodies) + bet_disagreements(bodies)
    for p in problems:
        print(f"DISAGREES: {p}")
    if problems:
        print("capture_kit_page_fixtures: the live set disagrees with itself — nothing written (a cache window? run again)")
        return 1
    print(f"capture_kit_page_fixtures: {len(bodies)} files agree, captured {captured_at}")
    if args.check:
        return 0
    stale = write(bodies, sources, captured_at, args.base, args.out)
    for name in stale:
        print(f"removed {name}: no capture writes it")
    print(f"wrote {len(bodies)} files + {MANIFEST} to {os.path.relpath(args.out, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
