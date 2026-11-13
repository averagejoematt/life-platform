"""The live API's contract stays fresh: every route the v9 site reads has a shape baseline under 30 days old.

Owner ruling 2026-11-13: the v8 kit captures (tests/fixtures/kit_pages_4586/, edition_wire_4582/) are frozen as
historical evidence (tests/test_kit_fixtures_fresh_4839.py), and the freshness requirement moves to the contracts
production actually depends on. Those are the routes the v9 build reads, at build time through
scripts/publish_snapshot*.py and in the reader's browser from www/src/. The set is DERIVED by scanning those
sources for ``/api/<name>``, never hand-listed, so a route a page starts reading joins the check on the same change.

For each route, tests/api_schemas/ (deploy/capture_api_schemas.py, shapes only, never values) must hold either a
snapshot whose ``captured_at`` is at most ``MAX_AGE_DAYS`` old, or a reasoned entry in ``_exemptions.json`` (a
route the owner has kept dark, say). A stale baseline is the same failure the kit captures had: a description of
an API that has since changed. Before re-baselining, run ``--check-drift`` and read what moved; a removed key that
a page still reads is a defect, not a baseline update. The recapture is ritual ``live-contract-recapture`` on
docs/OPERATING_CALENDAR.md; ``python3 tests/test_live_contract_shapes_fresh.py`` prints the exact commands.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "deploy"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capture_api_schemas as cas  # noqa: E402

MAX_AGE_DAYS = 30
SCHEMA_DIR = os.path.join(ROOT, "tests", "api_schemas")
SOURCES = ("scripts/publish_snapshot*.py", "www/src/**/*")
_ROUTE = re.compile(r"/api/[a-z_]+")


def read_routes() -> set:
    """Every ``/api/<name>`` the v9 build and its pages name."""
    found = set()
    for pattern in SOURCES:
        for path in glob.glob(os.path.join(ROOT, pattern), recursive=True):
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    found |= set(_ROUTE.findall(fh.read()))
    return found


def contract() -> dict:
    """{discovered route: plan entry} for every route the v9 surfaces read (a prefix route matches ``/api/x/``)."""
    plan = {p["path"]: p for p in cas.build_plan()}
    out = {}
    for name in read_routes():
        for path, entry in plan.items():
            if path == name or path == name + "/":
                out[path] = entry
    return out


def age_days(captured_at: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(captured_at)).total_seconds() / 86400


def stale_or_missing(now: datetime) -> list:
    with open(os.path.join(SCHEMA_DIR, "_exemptions.json"), encoding="utf-8") as fh:
        exemptions = json.load(fh)
    problems = []
    for path, entry in sorted(contract().items()):
        snap = os.path.join(SCHEMA_DIR, cas.slug_for(path, is_prefix=entry.get("is_prefix", False)))
        if os.path.exists(snap):
            with open(snap, encoding="utf-8") as fh:
                taken = json.load(fh)["captured_at"]
            if age_days(taken, now) > MAX_AGE_DAYS:
                problems.append(f"{path}: baseline captured {taken[:10]}, {age_days(taken, now):.0f} days ago")
        elif not (exemptions.get(path) or {}).get("reason"):
            problems.append(f"{path}: no shape baseline and no reasoned exemption")
    return problems


def recapture_commands() -> str:
    only = " ".join(f"--only {p}" for p in sorted(p for p, e in contract().items() if e["action"] == "capture"))
    return f"python3 deploy/capture_api_schemas.py --check-drift {only}\npython3 deploy/capture_api_schemas.py {only}"


def test_the_route_set_is_derived_and_not_empty():
    """The scan is the guard: if it went blind, every assertion below would pass vacuously."""
    routes = contract()
    for must in ("/api/edition", "/api/predictions", "/api/coach_docket", "/api/chapters", "/api/ledger_export"):
        assert must in routes, f"{must} is read by the v9 build but the scan did not find it"
    assert len(routes) >= 25, f"only {len(routes)} v9 routes found — the scan has narrowed"


def test_the_age_rule_on_a_frozen_clock():
    taken = "2026-11-13T18:00:00.000000+00:00"
    at = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
    assert age_days(taken, at + timedelta(days=29, hours=23)) < MAX_AGE_DAYS
    assert age_days(taken, at + timedelta(days=30, hours=1)) > MAX_AGE_DAYS


def test_a_baseline_older_than_the_limit_is_named():
    """Negative control: on a clock 31 days past the newest baseline, every captured route is named stale."""
    stamps = []
    for path, entry in contract().items():
        snap = os.path.join(SCHEMA_DIR, cas.slug_for(path, is_prefix=entry.get("is_prefix", False)))
        if os.path.exists(snap):
            with open(snap, encoding="utf-8") as fh:
                stamps.append(datetime.fromisoformat(json.load(fh)["captured_at"]))
    later = max(stamps) + timedelta(days=MAX_AGE_DAYS + 1)
    assert len(stale_or_missing(later)) == len(stamps)


def test_every_v9_route_has_a_fresh_shape_baseline():
    problems = stale_or_missing(datetime.now(timezone.utc))
    assert not problems, (
        "the live API contract the v9 site reads has gone stale:\n  "
        + "\n  ".join(problems)
        + "\nRead the drift first, then re-baseline (ritual live-contract-recapture):\n"
        + recapture_commands()
    )


if __name__ == "__main__":
    print(recapture_commands())
