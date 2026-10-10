"""#4582 — the contract between GET /api/edition and the page that reads it.

The route is tested from the live wire (tests/test_site_api_routes.py, fixtures in
tests/fixtures/edition_wire_4582/) and the page from a live capture of the route
(tests/js/ck_pages_4586.test.mjs, tests/fixtures/kit_pages_4586/edition.json). Nothing held
the two together: the route could rename a field the page reads, or the page could read a
block the route never serves, and both suites stayed green on their own fixtures — the page
would print the generic "This is not served right now." for a block that IS served.

This file is the route's half of the contract; tests/js/edition_contract_4582.test.mjs is
the page's half. They meet in ONE committed file, tests/fixtures/edition_contract_4582/
editions.json: the documents ``compose()`` makes from the wire with every upstream in turn
failing (and all of them at once). Here it is held equal to the route's own output; there
the page's real block-to-slot wiring (``frontSlots``) renders each one, and every failed
block must print its own absence sentence, not a blank and not the green figure.

Regenerate after a deliberate change to ``compose()``:
    python3 tests/test_edition_page_contract_4582.py > tests/fixtures/edition_contract_4582/editions.json
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from coach import persona_registry as _personas  # noqa: E402
from web import site_api_edition as _ed  # noqa: E402
from web.prediction_reason import metric_words as _metric_words  # noqa: E402

WIRE_DIR = os.path.join(ROOT, "tests", "fixtures", "edition_wire_4582")
CONTRACT = os.path.join(ROOT, "tests", "fixtures", "edition_contract_4582", "editions.json")
PAGE_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "kit_pages_4586", "edition.json")
PAGES_JS = os.path.join(ROOT, "site", "assets", "js", "ck_pages.js")
FRONT_JS = os.path.join(ROOT, "site", "assets", "js", "ck_front.js")

# The wire's own capture clock (tests/test_site_api_routes.py): today 2026-10-03 PT.
CAPTURE_DAY = "2026-10-03"
CAPTURE_INSTANT = datetime(2026, 10, 4, 2, 29, tzinfo=timezone.utc)
START_DATE = "2026-09-06"

# What the front page still reads besides the edition (#4582 box 1, "the front page makes
# one data request", is NOT met while this set is non-empty). A ratchet: it may only shrink.
# The transcript is read from the edition's own podcast URL, so it is not a route.
FRONT_EXTRA_READS = {"/api/calls", "/api/weekly_priority", "/api/character"}


def _wire() -> dict:
    out = {}
    for key in _ed.SOURCES:
        with open(os.path.join(WIRE_DIR, f"{key}.json"), encoding="utf-8") as fh:
            out[key] = json.load(fh)
    return out


def _compose(bodies: dict) -> dict:
    return _ed.compose(
        bodies,
        today=CAPTURE_DAY,
        now=CAPTURE_INSTANT,
        start_date=START_DATE,
        persona_of=_personas.resolve,
        persona_of_short=lambda sid: _personas.by_short_id(sid)[1],
        metric_words=_metric_words,
    )


def build_contract() -> dict:
    """The green edition, plus — for every upstream failing in turn, and all at once — the
    blocks that differ from it. The page side rebuilds each case as green-with-these-blocks."""
    wire = _wire()
    green = _compose(wire)
    cases = {"all": _compose({key: None for key in _ed.SOURCES})}
    for key in _ed.SOURCES:
        cases[key] = _compose({**wire, key: None})
    out = {}
    for name, doc in cases.items():
        assert doc["as_of"] == green["as_of"] and doc["day_n"] == green["day_n"], name
        out[name] = {"blocks": {k: v for k, v in doc["blocks"].items() if v != green["blocks"][k]}}
    return {
        "_about": "#4582 — GET /api/edition's own compose() output over tests/fixtures/edition_wire_4582 "
        f"(today {CAPTURE_DAY} PT). `cases[<upstream>]` holds only the blocks that differ from `green` when that "
        "upstream's read fails; `all` is every upstream failing. Regenerate with "
        "`python3 tests/test_edition_page_contract_4582.py`; held equal by tests/test_edition_page_contract_4582.py.",
        "green": green,
        "cases": out,
    }


def _paths(node, pre: str = "") -> set:
    out = set()
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{pre}.{k}" if pre else k
            out.add(p)
            out |= _paths(v, p)
    elif isinstance(node, list):
        for v in node:
            out |= _paths(v, pre + "[]")
    return out


def _moves_wire() -> dict:
    """The wire with a current day of coach moves (#4583) on the dashboard — the other voice
    the coach_lines block speaks in, so its fields are part of the route's shape too."""
    wire = _wire()
    dash = copy.deepcopy(wire["dashboard"])
    dash["moves"] = {
        "date": CAPTURE_DAY,
        "lines": [
            {"coach_id": "sleep_coach", "name": "Lisa Park", "text": "Bed by ten tonight.", "move": "ask", "move_label": "An ask"},
            {
                "coach_id": "physical_coach",
                "name": "Max Reyes",
                "text": "I disagree.",
                "move": "push_back",
                "move_label": "Push back",
                "replies_to_name": "Lisa Park",
                "bet": {"resolution_date": "2026-10-06"},
            },
        ],
    }
    wire["dashboard"] = dash
    return wire


def _route_paths() -> set:
    """Every key path the route composes, across its states (green, the moves voice, each
    upstream failing, all failing)."""
    wire = _wire()
    out = _paths(_compose(wire)) | _paths(_compose(_moves_wire())) | _paths(_compose({}))
    for key in _ed.SOURCES:
        out |= _paths(_compose({**wire, key: None}))
    return out


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_the_contract_fixture_is_the_routes_own_output():
    """The documents the page-side contract test renders are exactly what compose() makes
    now. A change to a block's sentence, state or fields is red here until the fixture is
    regenerated — and then the page's half re-checks it."""
    with open(CONTRACT, encoding="utf-8") as fh:
        committed = json.load(fh)
    fresh = build_contract()
    assert len(fresh["cases"]) == len(_ed.SOURCES) + 1
    drifted = sorted(k for k in set(fresh["cases"]) | set(committed.get("cases", {})) if fresh["cases"].get(k) != committed["cases"].get(k))
    if fresh["green"] != committed.get("green"):
        drifted.insert(0, "green")
    assert not drifted, (
        f"compose() no longer makes the committed contract documents for {drifted}. Regenerate: "
        "python3 tests/test_edition_page_contract_4582.py > tests/fixtures/edition_contract_4582/editions.json"
    )
    # Every case fails at least one block, and every failed read reaches the page as a sentence.
    for name, case in fresh["cases"].items():
        assert case["blocks"], f"{name} failing changed no block"


def test_the_page_fixture_carries_only_fields_the_route_composes():
    """The page's tests run on a live capture of the route. Every field in it must be one the
    route composes today — a field the route renamed or dropped would leave the page tested
    against a document the route no longer serves."""
    with open(PAGE_FIXTURE, encoding="utf-8") as fh:
        page = json.load(fh)
    page_paths = {p for p in _paths(page) if not p.startswith("_meta")}
    route = _route_paths()
    assert len(page_paths) >= 100, f"only {len(page_paths)} paths in the page fixture — the capture has gone thin"
    orphaned = sorted(page_paths - route)
    assert not orphaned, f"the page is tested on fields the route no longer composes: {orphaned}"
    assert list(page["blocks"]) == list(_ed.ORDER) == page["order"]


_EDITION_FN = re.compile(r"^(?:export )?(?:async )?function (\w+)\(edition, b\b", re.M)
_NEXT_FN = re.compile(r"^(?:export )?(?:async )?function |^const |^export const ", re.M)


def _blocks_read_by_page() -> tuple[set, list]:
    """Every ``b.<block>`` read inside a function that takes ``(edition, b)`` — the page's
    convention for "b is the edition's blocks" (mount*, frontSlots, todayBandHTML)."""
    read, fns = set(), []
    for path in (PAGES_JS, FRONT_JS):
        src = _read(path)
        for m in _EDITION_FN.finditer(src):
            nxt = _NEXT_FN.search(src, m.end())
            body = src[m.end() : nxt.start() if nxt else len(src)]
            fns.append(m.group(1))
            read |= set(re.findall(r"\bb\.([a-z_]+)\b", body))
    return read, fns


def test_the_page_reads_only_blocks_the_route_serves():
    """A block name the page reads that the route does not serve resolves to the generic
    UNSERVED stand-in, so a typo would print "not served" forever on a served block."""
    read, fns = _blocks_read_by_page()
    assert {"frontSlots", "mountFront", "todayBandHTML"} <= set(fns), f"scanned {fns} — the block-read scan has gone blind"
    assert len(read) >= 6, f"found only {sorted(read)} — the block-read scan has gone blind"
    unknown = sorted(read - set(_ed.ORDER))
    assert not unknown, f"the page reads blocks /api/edition does not serve: {unknown}"


def test_the_front_page_reads_nothing_new_beside_the_edition():
    """#4582 box 1 is one data request. The front page still reads FRONT_EXTRA_READS after
    the edition; that set is named here and may only shrink."""
    pages = _read(PAGES_JS)
    front = pages[pages.index("async function mountFront") : pages.index("async function mountStart")]
    reads = set(re.findall(r'tryJSON\("([^"]+)"\)', front))
    assert "tryJSON(transcriptUrl)" in front, "the transcript read moved — re-check this scan"
    grown = sorted(reads - FRONT_EXTRA_READS)
    assert not grown, f"the front page reads more besides /api/edition: {grown} — fold it into the edition instead"
    # The mount reads the edition once, for every page.
    assert len(re.findall(r'tryJSON\("/api/edition"\)', pages)) == 1


if __name__ == "__main__":
    print(json.dumps(build_contract(), indent=1, sort_keys=False, ensure_ascii=False))
