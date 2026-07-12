#!/usr/bin/env python3
"""
restart_verify_semantic.py — deterministic assertions on what the site SAYS
after a reset (#1093).

restart_verify_rendered.py checks that the 40-URL surface RENDERS and greps for
stale tokens; this verifier checks the SEMANTICS — a reset can pass the render
gate while coach surfaces serve the wiped cycle's prose and pre-genesis
experiment-phase rows survive (exactly what the 2026-07-11 manual review
caught). Invoked by restart_pipeline.py right after restart_verify_rendered
(hard gate, apply only); standalone-runnable any time.

Checks (each PASS / FAIL / SKIP — a SKIP is honest, never a silent pass):
  1. /api/snapshot and /api/journey carry pre_start:true (or day_n <= 1) while
     genesis >= today — the #931/#948 countdown contract.
  2. /api/character is zeroed pre-start (level 1, xp_total 0 — the
     _zeroed_pre_experiment state; a computed sheet leaking through the phase
     filter is the failure).
  3. /api/discoveries has NO current-cycle findings pre-start (inner_life and
     ai_findings empty; carried_over ongoing protocols are cross-phase by
     design, #1089, and allowed).
  4. /api/coach_team dispute is null-or-current-cycle (the #1085 class: the
     wiped cycle's argument kept serving pre-start).
  5. /journal/posts.json contains ONLY the curated prologue lead-ins: every
     entry pre-genesis-dated and backed by a live (phase=experiment,
     non-tombstoned) chronicle record — a wiped installment surviving in the
     manifest is the leak.
  6. DDB spot-check: ZERO rows with phase=experiment dated before genesis
     across every raw-timeseries source (phase-taxonomy-derived). Catches the
     ingestion-poisoning class found 2026-07-12: a warm ingestion Lambda with
     stale constants re-stamped whoop DATE#2026-07-08 as phase=experiment
     after the tagger pass.

Checks 1-5 need the live site (skipped honestly under --offline; also skipped
once today > genesis — they are PRE-START assertions; the post-genesis Monday
check is deploy/restart_verify.py). Check 6 uses read-only boto3 and applies
always. Exit 0 = no FAIL; exit 1 otherwise.

Usage:
    python3 deploy/restart_verify_semantic.py               # full run
    python3 deploy/restart_verify_semantic.py --offline     # DDB-only; network checks SKIP
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import phase_taxonomy as taxonomy  # noqa: E402

from lambdas.constants import EXPERIMENT_START_DATE  # noqa: E402

BASE = "https://averagejoematt.com"
REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"
PT = ZoneInfo("America/Los_Angeles")

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


# ──────────────────────────────────────────────────────────────────────────────
# Pure assertion functions (fixture-tested in tests/test_restart_verify_semantic.py)
# Each returns a list of problem strings; empty list = clean.
# ──────────────────────────────────────────────────────────────────────────────


def check_snapshot_pre_start(payload: dict) -> list[str]:
    """/api/snapshot: top-level pre_start true, or the journey day counter <= 1."""
    if payload.get("pre_start") is True:
        return []
    day_n = ((payload.get("journey") or {}).get("journey") or {}).get("day_n")
    if isinstance(day_n, (int, float)) and day_n <= 1:
        return []
    return [f"/api/snapshot: pre_start is {payload.get('pre_start')!r} and journey day_n is {day_n!r} (expected pre_start or day<=1)"]


def check_journey_pre_start(payload: dict) -> list[str]:
    """/api/journey: journey.pre_start true, or day_n <= 1."""
    j = payload.get("journey") or {}
    if j.get("pre_start") is True:
        return []
    day_n = j.get("day_n")
    if isinstance(day_n, (int, float)) and day_n <= 1:
        return []
    return [f"/api/journey: pre_start is {j.get('pre_start')!r} and day_n is {day_n!r} (expected pre_start or day<=1)"]


def check_character_zeroed(payload: dict) -> list[str]:
    """/api/character pre-start = the zeroed state: level 1, xp_total 0. A leveled
    sheet here means a pilot/prior-cycle record leaked through the phase filter."""
    problems = []
    c = payload.get("character") or {}
    level = c.get("level")
    xp = c.get("xp_total")
    if not isinstance(level, (int, float)) or level > 1:
        problems.append(f"/api/character: level is {level!r} (expected 1 — zeroed pre-start state)")
    if not isinstance(xp, (int, float)) or xp != 0:
        problems.append(f"/api/character: xp_total is {xp!r} (expected 0 — zeroed pre-start state)")
    return problems


def check_discoveries_clean(payload: dict) -> list[str]:
    """/api/discoveries pre-start: no current-cycle findings. inner_life and
    ai_findings come from phase-filtered partitions and must be empty; the
    carried_over ongoing-protocol library entries are cross-phase (#1089), allowed."""
    problems = []
    inner = payload.get("inner_life") or []
    findings = payload.get("ai_findings") or []
    if inner:
        titles = ", ".join(repr(x.get("title", "?")) for x in inner[:3])
        problems.append(f"/api/discoveries: {len(inner)} inner_life finding(s) pre-start (e.g. {titles})")
    if findings:
        problems.append(f"/api/discoveries: {len(findings)} ai_findings entr(ies) pre-start")
    return problems


def check_dispute_current(payload: dict, genesis: str) -> list[str]:
    """/api/coach_team: dispute must be null or current-cycle (created_at >= genesis).
    A pre-genesis dispute is the wiped cycle's argument still on the air (#1085)."""
    d = payload.get("dispute")
    if d is None:
        return []
    created = str(d.get("created_at") or "")[:10]
    if created and created >= genesis:
        return []
    return [
        f"/api/coach_team: dispute {d.get('topic')!r} has created_at {d.get('created_at')!r} — pre-genesis (expected null or >= {genesis})"
    ]


def live_chronicle_keys(records: list[dict]) -> set[tuple[str, str]]:
    """(date, title) for every LIVE chronicle record — phase=experiment, not
    tombstoned — the same visibility rule restart_leadin_pages publishes by."""
    out = set()
    for r in records:
        if r.get("tombstone"):
            continue
        if r.get("phase") != "experiment":
            continue
        out.add((str(r.get("date") or str(r.get("sk", "")).replace("DATE#", "")), str(r.get("title") or "")))
    return out


def check_journal_posts(posts_payload: dict, live_records: list[dict], genesis: str) -> list[str]:
    """/journal/posts.json pre-start: only the curated prologue lead-ins — every
    entry dated before genesis AND backed by a live chronicle record (date+title)."""
    problems = []
    live = live_chronicle_keys(live_records)
    for post in posts_payload.get("posts") or []:
        date = str(post.get("date") or "")
        title = str(post.get("title") or "")
        if date >= genesis:
            problems.append(f"posts.json: {title!r} is dated {date} — not pre-genesis (genesis {genesis})")
            continue
        if (date, title) not in live:
            problems.append(
                f"posts.json: {title!r} ({date}) has no live (non-tombstoned, phase=experiment) chronicle record — wiped-cycle leak"
            )
    return problems


def find_poisoned(items: list[dict], genesis: str) -> list[str]:
    """Rows stamped phase=experiment but dated BEFORE genesis — the ingestion-
    poisoning class (a warm Lambda re-stamping with stale constants)."""
    out = []
    for item in items:
        sk = str(item.get("sk", ""))
        row_date = sk.replace("DATE#", "")[:10]
        if item.get("phase") == "experiment" and row_date < genesis:
            out.append(f"{item.get('pk')} / {sk} (phase=experiment, pre-genesis)")
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Fetch / query layer
# ──────────────────────────────────────────────────────────────────────────────


def fetch_json(path: str) -> tuple[int, dict | None]:
    """(status, payload) — (0, None) on network error; payload None on bad JSON."""
    url = BASE + path
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "restart-verify-semantic/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"  [fetch error] {url}: {e}")
        return 0, None


def query_chronicle_records(table) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    items: list[dict] = []
    kwargs = {"KeyConditionExpression": Key("pk").eq(f"USER#{USER}#SOURCE#chronicle")}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def query_pre_genesis_experiment_rows(table, source: str, genesis: str) -> list[dict]:
    """Read-only: pre-genesis DATE# rows for one source still stamped phase=experiment.
    Key-bounded below DATE#<genesis> (exclusive) + a server-side phase filter, so only
    violations come back."""
    from boto3.dynamodb.conditions import Attr, Key

    items: list[dict] = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(f"USER#{USER}#SOURCE#{source}") & Key("sk").between("DATE#0000-00-00", f"DATE#{genesis}"),
        "FilterExpression": Attr("phase").eq("experiment"),
        "ProjectionExpression": "pk, sk, phase",
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    # between() is inclusive at the top — drop the genesis day itself (it IS experiment).
    return [i for i in items if str(i.get("sk", "")).replace("DATE#", "")[:10] < genesis]


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="skip the live-site checks (honest SKIP, not a pass) — DDB check still runs")
    ap.add_argument("--genesis", default=EXPERIMENT_START_DATE, help="override genesis (default: lambdas/constants.py)")
    args = ap.parse_args()

    genesis = args.genesis
    today = datetime.now(PT).date().isoformat()
    pre_start_window = genesis >= today

    print(f"\nrestart_verify_semantic — genesis={genesis} today(PT)={today} pre-start-window={pre_start_window}\n")

    results: list[tuple[str, str, list[str]]] = []  # (check, status, problems)

    def record(name: str, status: str, problems: list[str] | None = None):
        results.append((name, status, problems or []))
        mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "○"}[status]
        print(f"  {mark} {name} — {status}")
        for p in problems or []:
            print(f"      {p}")

    # ── Checks 1-5: pre-start semantics on the LIVE site ──
    net_skip = None
    if args.offline:
        net_skip = "offline mode — live-site checks skipped honestly"
    elif not pre_start_window:
        net_skip = "today > genesis — pre-start assertions not applicable (run deploy/restart_verify.py for the post-genesis check)"

    live_checks = [
        ("snapshot pre_start", "/api/snapshot", check_snapshot_pre_start),
        ("journey pre_start", "/api/journey", check_journey_pre_start),
        ("character zeroed", "/api/character", check_character_zeroed),
        ("discoveries clean", "/api/discoveries", check_discoveries_clean),
        ("coach_team dispute", "/api/coach_team", lambda p: check_dispute_current(p, genesis)),
    ]
    for name, path, checker in live_checks:
        if net_skip:
            record(name, SKIP, [net_skip])
            continue
        status, payload = fetch_json(path)
        if path == "/api/character" and status == 503:
            record(name, PASS, ["503 (compute not yet run) — no sheet can be leaking"])
            continue
        if status != 200 or payload is None:
            record(name, FAIL, [f"{path} returned HTTP {status} (no JSON payload)"])
            continue
        problems = checker(payload)
        record(name, FAIL if problems else PASS, problems)

    # Check 5 needs the live manifest AND the chronicle partition.
    if net_skip:
        record("journal posts curated", SKIP, [net_skip])
        table = None
    else:
        import boto3

        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
        status, posts = fetch_json("/journal/posts.json")
        if status != 200 or posts is None:
            record("journal posts curated", FAIL, [f"/journal/posts.json returned HTTP {status}"])
        else:
            problems = check_journal_posts(posts, query_chronicle_records(table), genesis)
            record("journal posts curated", FAIL if problems else PASS, problems)

    # ── Check 6: the poisoning class — always applies, read-only boto3 ──
    if table is None:
        import boto3

        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    violations: list[str] = []
    for source in taxonomy.RAW_TIMESERIES_SOURCES:
        try:
            rows = query_pre_genesis_experiment_rows(table, source, genesis)
        except Exception as e:
            record("no pre-genesis experiment rows", FAIL, [f"DDB query failed for source {source!r}: {e}"])
            break
        violations.extend(find_poisoned(rows, genesis))
    else:
        record(
            "no pre-genesis experiment rows",
            FAIL if violations else PASS,
            violations or [f"0 poisoned rows across {len(taxonomy.RAW_TIMESERIES_SOURCES)} raw-timeseries sources"],
        )

    # ── Report + exit ──
    failed = [r for r in results if r[1] == FAIL]
    skipped = [r for r in results if r[1] == SKIP]
    print(f"\n══ summary ══\n  {len(results) - len(failed) - len(skipped)} pass · {len(failed)} fail · {len(skipped)} skip")

    report = REPO_ROOT / "docs" / "restart" / "_verify_semantic_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"verify_semantic report — genesis={genesis} today={today}", ""]
    for name, status, problems in results:
        lines.append(f"[{status}] {name}")
        lines.extend(f"    {p}" for p in problems)
    report.write_text("\n".join(lines) + "\n")
    print(f"Report: {report.relative_to(REPO_ROOT)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
