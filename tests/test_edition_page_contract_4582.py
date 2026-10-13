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

# #4582 box 1, "the front page makes one data request": met 2026-10-11, when the last routes
# the front page read beside the edition (/api/calls, /api/character and seven days of
# /api/coach_moves) and the week page's /api/weekly_priority became blocks of the edition.
# The front page's mount makes NO read of its own; the week page's only other read is the
# chapter's published transcript, addressed by the edition's own podcast URL.


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
    the coach_lines block speaks in, so its fields are part of the route's shape too — and a
    week of served lines and a weekly read from the lead (the capture's week had neither), so
    the moves and lead_read blocks' served fields are part of it as well."""
    wire = _wire()
    days = copy.deepcopy(wire["moves"]["days"])
    days[0] = {
        **days[0],
        "state": "ok",
        "lines": [
            {
                "coach_id": "physical_coach",
                "coach": "Max Reyes",
                "move": "push_back",
                "move_label": "Push back",
                "text": "I disagree.",
                "replies_to": "Lisa Park",
                "bet_settles": "2026-10-06",
            }
        ],
    }
    wire["moves"] = {"days": days}
    wire["priority"] = {
        **wire["priority"],
        "weekly_priority": "The priority this week is sleep.",
        "data_through": CAPTURE_DAY,
        "coach_name": "Eli Marsh",
    }
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
        # #4583 box 5: who sat out, and why — served beside the lines as data.absent
        "sidelined": [{"coach": "glucose_coach", "state": "absent", "reason": "This coach had nothing new to add."}],
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
    assert {"frontSlots", "frontReadSlots", "mountFront", "mountWeek", "todayBandHTML"} <= set(
        fns
    ), f"scanned {fns} — the block-read scan has gone blind"
    assert len(read) >= 6, f"found only {sorted(read)} — the block-read scan has gone blind"
    unknown = sorted(read - set(_ed.ORDER))
    assert not unknown, f"the page reads blocks /api/edition does not serve: {unknown}"


def _body(src: str, head: str) -> str:
    """The text of the top-level function starting ``head``, up to the next top-level one."""
    at = src.index(head)
    nxt = _NEXT_FN.search(src, at + len(head))
    return src[at : nxt.start() if nxt else len(src)]


_ANY_READ = re.compile(r"\b(?:tryJSON|fetch)\(")


def test_the_front_page_makes_one_data_request():
    """#4582 box 1. The mount reads the edition once, for every page; the front page's own
    mount, and every builder it fills from, reads nothing else — not a route, not a file, not
    a templated address (the seven /api/coach_moves?date= reads were a template literal that
    an exact-string scan never saw)."""
    pages = _read(PAGES_JS)
    assert len(re.findall(r'tryJSON\("/api/edition"\)', pages)) == 1
    mount = _body(pages, "export async function mount()")
    assert len(_ANY_READ.findall(mount)) == 1, "mount() reads something besides the edition"
    for head in ("async function mountFront", "export function frontReadSlots", "export function frontSlots"):
        assert not _ANY_READ.findall(_body(pages, head)), f"{head} reads something besides the edition"
    # The builders the front page fills from are pure: ck_front.js reads nothing at all.
    assert not _ANY_READ.findall(_read(FRONT_JS)), "ck_front.js reads a route — the front page's builders must be pure"


def test_the_week_page_reads_only_the_transcript_beside_the_edition():
    week = _body(_read(PAGES_JS), "async function mountWeek")
    assert _ANY_READ.findall(week) == ["tryJSON("], "the week page reads more than the chapter's transcript"
    assert "tryJSON(transcriptUrl)" in week


def test_MUST_FAIL_the_one_request_scan_sees_a_templated_read():
    """The control: the scan catches the read shape it once missed."""
    planted = "async function mountFront(edition, b) {\n  const m = await tryJSON(`/api/coach_moves?date=${d}`);\n}\n"
    assert _ANY_READ.findall(_body(planted, "async function mountFront")) == ["tryJSON("]


if __name__ == "__main__":
    print(json.dumps(build_contract(), indent=1, sort_keys=False, ensure_ascii=False))
