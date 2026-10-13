"""tests/test_site_api_routes.py — Phase 4.5 scoped: validate the router table.

The new _SIMPLE_ROUTES dict in site_api_lambda.py needs to stay in sync:
  - Every entry's handler must exist as a function
  - Every entry's path must look like an API path
  - Allowed methods must be a set of valid HTTP verbs or None
  - No duplicate entries

Doesn't import site_api_lambda directly (requires AWS env). Greps the source.
"""

import copy as _copy
import json as _json
import os
import re
import sys as _sys
from datetime import datetime as _dt, timedelta as _td, timezone as _tz
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "lambdas", "web", "site_api_lambda.py")  # P3.1: moved to web/


def _src():
    with open(SRC, encoding="utf-8") as f:
        return f.read()


def _parse_routes():
    src = _src()
    start = src.find("_SIMPLE_ROUTES = {")
    assert start > 0, "_SIMPLE_ROUTES dict not found"
    end = src.find("\n}\n", start)
    block = src[start:end]
    # Match: "path": ({"METHOD", "METHOD"}, handler) OR (None, handler)
    pattern = re.compile(
        r'"(/api/[a-z0-9_]+)"\s*:\s*\(([^,]+),\s*(_handle_[a-z_]+)\)',
        re.MULTILINE,
    )
    return [(m.group(1), m.group(2).strip(), m.group(3)) for m in pattern.finditer(block)]


def test_routes_dict_parses():
    routes = _parse_routes()
    # 2026-05-25 (P1.1): was ≥10; /api/board_ask removed when dead AI code was purged from
    # site_api_lambda.py — that endpoint lives in life-platform-site-api-ai (ADR-036).
    assert len(routes) >= 9, f"Expected ≥9 routes, found {len(routes)}"


def test_no_duplicate_paths():
    routes = _parse_routes()
    paths = [p for p, _, _ in routes]
    assert len(paths) == len(set(paths)), "Duplicate path(s) in _SIMPLE_ROUTES"


def test_no_duplicate_handlers():
    routes = _parse_routes()
    handlers = [h for _, _, h in routes]
    assert len(handlers) == len(set(handlers)), "Duplicate handler(s) in _SIMPLE_ROUTES — same handler can't serve two paths in this table"


def test_all_handlers_defined():
    """Every handler referenced in _SIMPLE_ROUTES must be defined somewhere in
    the site_api family of modules (site_api_lambda.py + sibling modules
    extracted in P1.1 Phase B)."""
    _src()
    # P1.1 Phase B (2026-05-26): handlers may live in any of the sibling modules.
    sibling_files = [
        SRC,
        os.path.join(ROOT, "lambdas", "web", "site_api_observatory.py"),
        os.path.join(ROOT, "lambdas", "web", "site_api_intelligence.py"),
        os.path.join(ROOT, "lambdas", "web", "site_api_social.py"),
        os.path.join(ROOT, "lambdas", "web", "site_api_common.py"),
    ]
    combined_src = ""
    for f in sibling_files:
        if os.path.exists(f):
            with open(f, encoding="utf-8") as fh:
                combined_src += fh.read() + "\n"

    routes = _parse_routes()
    for path, _, handler in routes:
        pattern = rf"^def {handler}\("
        assert re.search(pattern, combined_src, re.MULTILINE), (
            f"Route {path} references {handler} but no `def {handler}(` " f"found in any site_api_*.py sibling module."
        )


def test_paths_well_formed():
    routes = _parse_routes()
    for path, _, _ in routes:
        assert path.startswith("/api/"), f"Path {path!r} should start with /api/"
        assert " " not in path, f"Path {path!r} has whitespace"


def test_allowed_methods_use_valid_verbs():
    routes = _parse_routes()
    valid = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "None"}
    for path, methods_str, _ in routes:
        # methods_str is either "None" or "{\"GET\", \"OPTIONS\"}"
        if methods_str == "None":
            continue
        # Extract verbs from set literal
        verbs = re.findall(r'"([A-Z]+)"', methods_str)
        assert verbs, f"Route {path} has no recognizable methods in {methods_str!r}"
        for v in verbs:
            assert v in valid, f"Route {path} uses invalid method {v!r}"


def test_dispatch_call_exists_in_handler():
    """Verify lambda_handler actually uses _SIMPLE_ROUTES.get(path)."""
    src = _src()
    assert "_SIMPLE_ROUTES.get(path)" in src, (
        "Dispatch lookup not found in lambda_handler — did the inline branches " "get re-added without removing the table?"
    )


# ── #4582: /api/edition — the front page's one composed document ─────────────────
#
# Fixtures are the WIRE: tests/fixtures/edition_wire_4582/*.json are the bodies the live
# read-only API served on 2026-10-03 ~19:29 PT (curl https://averagejoematt.com/api/<route>;
# /journal/posts.json and /panelcast/episodes.json are the public manifests the shell reads
# from generated/), byte for byte. The clock is FROZEN to that capture (today 2026-10-03 PT,
# now 2026-10-04T02:29Z — the PT evening window, where the UTC date has already rolled), so
# the expectations never read wall time.

_sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from coach import persona_registry as _personas  # noqa: E402
from web import (
    edition_page_reads as _reads,  # noqa: E402
    site_api_edition as _ed,  # noqa: E402
)
from web.prediction_reason import metric_words as _metric_words  # noqa: E402

_WIRE = os.path.join(ROOT, "tests", "fixtures", "edition_wire_4582")


def _wire_clock():
    """The wire's own capture clock, read from its manifest (#4864): the instant it was fetched and that
    instant's Pacific day. Re-running scripts/capture_kit_page_fixtures.py re-dates every test that composes
    the wire, so no literal day or instant is left behind to drift from the files."""
    with open(os.path.join(_WIRE, "_capture.json"), encoding="utf-8") as fh:
        taken = _dt.strptime(_json.load(fh)["captured_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
    return taken.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d"), taken


_CAPTURE_DAY, _CAPTURE_INSTANT = _wire_clock()
_STATES = {"ok", "absent", "stale", "unavailable"}
_CONTRACT_KEYS = ("state", "as_of", "source", "absent_text", "data")


def _wire():
    return {k: _json.load(open(os.path.join(_WIRE, f"{k}.json"), encoding="utf-8")) for k in _ed.SOURCES}


def _edition(bodies):
    return _ed.compose(
        bodies,
        today=_CAPTURE_DAY,
        now=_CAPTURE_INSTANT,
        start_date="2026-09-06",
        persona_of=_personas.resolve,
        persona_of_short=lambda sid: _personas.by_short_id(sid)[1],
        metric_words=_metric_words,
    )


def _contract_offences(name, block):
    out = []
    for key in _CONTRACT_KEYS:
        if key not in block:
            out.append(f"{name}: no `{key}`")
    if block.get("state") not in _STATES:
        out.append(f"{name}: state {block.get('state')!r}")
    if not (isinstance(block.get("absent_text"), str) and block["absent_text"].strip().endswith(".")):
        out.append(f"{name}: absent_text is not a sentence ({block.get('absent_text')!r})")
    if block.get("state") == "unavailable" and block.get("data") is not None:
        out.append(f"{name}: unavailable but carries data")
    if block.get("state") == "unavailable" and "is not served right now." not in block.get("absent_text", ""):
        out.append(f"{name}: unavailable without the not-served sentence")
    return out


def _parts(doc):
    """Every block AND every nested part that carries the same contract."""
    blocks = doc["blocks"]
    yield from blocks.items()
    chapter = blocks["chapter"].get("data") or {}
    if "podcast" in chapter:
        yield "chapter.podcast", chapter["podcast"]
    nxt = blocks["next"].get("data") or {}
    for k in ("chapter", "bet"):
        if k in nxt:
            yield f"next.{k}", nxt[k]
    for k, row in ((blocks.get("life") or {}).get("data") or {}).get("rows", {}).items():
        yield f"life.{k}", row
    for k, part in ((blocks.get("week") or {}).get("data") or {}).get("measures", {}).items():
        yield f"week.{k}", part
    for k, row in ((blocks.get("scorecard") or {}).get("data") or {}).get("rows", {}).items():
        yield f"scorecard.{k}", row


def test_edition_every_block_carries_the_contract_on_the_wire():
    """Every block (and nested part) has state/as_of/source/absent_text/data; the document
    has ONE Pacific as_of and day_n, and the blocks arrive in page order."""
    wire = _wire()
    doc = _edition(wire)
    assert doc["as_of"] == _CAPTURE_DAY and doc["day_n"] == (_dt.fromisoformat(_CAPTURE_DAY) - _dt.fromisoformat("2026-09-06")).days + 1
    assert list(doc["blocks"]) == list(_ed.ORDER) == doc["order"]
    offences = [o for name, block in _parts(doc) for o in _contract_offences(name, block)]
    assert not offences, offences
    # The live wire composes to real values, not placeholders.
    b = doc["blocks"]
    latest = max((p for p in wire["journal"]["posts"] if p["date"] <= _CAPTURE_DAY), key=lambda p: (p["date"], p.get("sequence") or 0))
    assert b["chapter"]["data"]["title"] == latest["title"] and "*" not in b["chapter"]["data"]["dek"]
    assert b["chapter"]["data"]["podcast"]["state"] in _STATES
    j = wire["journey"]["journey"]
    assert b["today"]["data"] == {
        "weight_lbs": j["current_weight_lbs"],
        "date": j["last_weighin_date"],
        "start_weight_lbs": j["start_weight_lbs"],
        "start_date": j["started_date"],
        "goal_weight_lbs": j["goal_weight_lbs"],
        "change_lbs": round(j["current_weight_lbs"] - j["start_weight_lbs"], 1),
    }
    # #4583: a dashboard whose moves are the edition's own day speaks in moves; otherwise the restated text.
    moves_day = (wire["dashboard"].get("moves") or {}).get("date")
    assert (
        b["coach_lines"]["voice"] == ("move" if moves_day == _CAPTURE_DAY else "restated") and len(b["coach_lines"]["data"]["lines"]) <= 3
    )
    assert all("Dr." not in ln["coach"] for ln in b["coach_lines"]["data"]["lines"])
    # #4595: the scorecard is served, one row per area, each decided by a written rule.
    assert b["scorecard"]["state"] == "ok" and b["scorecard"]["data"]["order"] == ["body", "training", "sleep", "food", "mind", "ai"]
    assert b["next"]["data"]["bet"]["data"]["question"].startswith("Will the ")


def test_edition_next_bet_carries_each_coachs_reason_through_the_coach_line_filter():
    """#4809: each side of the open bet carries one clause of that coach's opening position, in
    its served words — the docket's `claims` — through the same honest-text filter and honorific
    strip as the coach lines; a clause the filter refuses, or one too long for the card, is None."""
    wire = _wire()
    sides = _edition(wire)["blocks"]["next"]["data"]["bet"]["data"]["sides"]
    docket = wire["docket"]["open"][0]
    assert len(sides) == 2 and all(isinstance(side["coach"], str) and side["coach"] for side in sides)
    for side in sides:
        pids = [pid for pid, claim in docket["claims"].items() if side["reason"] and side["reason"] in claim]
        assert len(pids) == 1, "each side's reason is a clause of exactly one coach's served claim"
        assert side["says"] == ("yes" if docket["sides"][pids[0]] else "no"), "the side's answer is the docket's own"
    for side in sides:
        assert side["reason"] in " ".join(
            d["claims"][pid] for d in wire["docket"]["open"] for pid in d["claims"]
        ), "verbatim, never rewritten"
    r = _ed.bet_reason
    assert r("Dr. Webb says the floor holds. More later.") == "Webb says the floor holds"
    assert r("A 500 kcal deficit explains it; nothing else") is None, "the honest-number filter the coach lines pass through"
    assert r("This is the 17th start of the experiment") is None
    assert r("x" * (_ed.BET_REASON_MAX_CHARS + 1)) is None, "never cut mid-clause"
    assert r("") is None and r(None) is None
    # a side whose claim the docket did not serve has no reason, and the side still stands
    bare = _copy.deepcopy(wire)
    for d in bare["docket"]["open"]:
        d.pop("claims", None)
    assert [s["reason"] for s in _edition(bare)["blocks"]["next"]["data"]["bet"]["data"]["sides"]] == [None, None]


def _days_back(day, n=7):
    """``day`` and the six before it, newest first — the window the edition reads."""
    return [(_dt.fromisoformat(day) - _td(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def _fake_route(bodies, fail=None):
    """The in-process dispatcher, answering each route with its wire body as `_ok` would."""

    def read(path, qs):
        key = next(k for k, p in _ed.SOURCES.items() if p == path)
        if key == fail:
            return {"statusCode": 500, "body": _json.dumps({"error": "x"})}
        return {"statusCode": 200, "body": _json.dumps(bodies[key])}

    return read


def test_edition_one_upstream_failing_leaves_only_its_block_unavailable():
    """For EACH upstream in turn: a failed read (500 for a route, None for a manifest)
    makes exactly the block(s) it feeds `unavailable` with the not-served sentence and no
    figure; every other block is byte-identical to the all-green edition."""
    wire = _wire()
    baseline = _edition(wire)
    feeds = {
        "journal": {"chapter", "catch_up"},
        "panelcast": {"chapter.podcast"},
        "cadence": {"next.chapter"},
        "docket": {"next.bet"},
        "journey": {"today", "life.body"},
        "sleep": {"life.sleep"},
        "session": {"life.training"},
        "nutrition": {"life.food", "week.food", "scorecard.food"},
        "pulse": {"week.weight", "week.sleep", "scorecard.body", "scorecard.sleep"},
        "training": {"week.training", "scorecard.training"},
        "habits": {"life.habits"},
        "supplements": {"life.supplements"},
        "experiments": {"life.experiments"},
        "dashboard": {"coach_lines"},
        "predictions": {"record", "scorecard.ai"},
        "calibration": {"record", "scorecard.ai"},
        "decisions": {"his_words", "life.mind", "scorecard.mind"},
        # #4584: either source failing is a failed read of his words
        "owner_words": {"his_words", "life.mind", "scorecard.mind"},
        # #4582 box 1: the reads the front page and the week page made beside the edition
        "moves": {"moves"},
        "calls": {"calls"},
        "character": {"sheet"},
        "priority": {"lead_read"},
    }
    offenders = []
    for key, fed in feeds.items():
        s3 = {k: (None if k == key else wire[k]) for k in ("journal", "panelcast")}
        bodies = _ed.read_bodies(
            _fake_route(wire, fail=key), read_s3=lambda k, s3=s3: s3[next(n for n, v in _ed._S3_KEYS.items() if v == k)]
        )
        assert bodies[key] is None and all(bodies[k] is not None for k in _ed.SOURCES if k != key)
        doc = _edition(bodies)
        parts = dict(_parts(doc))
        for name in fed:
            p = parts[name]
            if p["state"] != "unavailable" or p["data"] is not None or not p["absent_text"].endswith("is not served right now."):
                offenders.append(f"{key} failing: {name} -> {p['state']} {p['absent_text']!r}")
        untouched = [n for n in doc["blocks"] if n not in fed and not any(f.startswith(n + ".") for f in fed)]
        if key == "cadence":
            untouched.remove("follow")  # follow carries the cadence date: checked below
            if doc["blocks"]["follow"]["data"]["next_chapter_state"] != "unavailable":
                offenders.append("cadence failing: follow still claims a next chapter date")
        for n in untouched:
            if doc["blocks"][n] != baseline["blocks"][n]:
                offenders.append(f"{key} failing: unrelated block {n} changed")
        offenders += [o for name, block in parts.items() for o in _contract_offences(name, block)]
    # A degraded 200 (a fallback payload from inside an except, #2686) is a failed read too.
    assert _ed.body_of({"statusCode": 200, "body": _json.dumps({"_meta": {"degraded": {"reason": "x"}}, "coaches": []})}) is None
    assert not offenders, offenders


def test_edition_serves_what_the_front_page_read_beside_it():
    """#4582 box 1: the settled calls, seven days of coach lines, the sheet's level and the
    lead's weekly read are blocks of the one document — each under the one as_of."""
    wire = _wire()
    b = _edition(wire)["blocks"]
    calls = b["calls"]
    assert calls["state"] == "ok" and calls["source"] == "/api/calls"
    # The capture holds no call settled after the edition's day (the newest settles on the day itself),
    # so the one-as_of filter is exercised on a copy of the newest call dated the next day (built, not captured).
    newest = max(wire["calls"]["calls"], key=lambda c: c["settled_date"])
    wire["calls"]["calls"].append({**newest, "id": "built-after-the-day", "settled_date": "2026-10-13"})
    b = _edition(wire)["blocks"]
    calls = b["calls"]
    served = [c for c in wire["calls"]["calls"] if c["settled_date"] <= _CAPTURE_DAY]
    later = [c for c in wire["calls"]["calls"] if c["settled_date"] > _CAPTURE_DAY]
    assert later and "built-after-the-day" not in [c["id"] for c in calls["data"]["calls"]]
    assert [c["id"] for c in calls["data"]["calls"]] == [c["id"] for c in sorted(served, key=lambda c: c["settled_date"], reverse=True)]
    assert calls["as_of"] == max(c["settled_date"] for c in served) <= _CAPTURE_DAY
    assert all(set(c) <= set(_reads.FRONT_CALL_FIELDS) for c in calls["data"]["calls"])
    # The sheet: the level and how many areas it is across, dated the edition's day.
    assert b["sheet"]["state"] == "ok" and b["sheet"]["as_of"] == wire["character"]["character"]["as_of_date"]
    assert set(b["sheet"]["data"]["character"]) == {"level", "composite_pillar_count", "composite_pillar_total"}
    # The week's moves are as the wire holds them: a line anywhere in the seven days is "ok", none is "absent".
    spoke = any(d.get("lines") for d in wire["moves"]["days"])
    assert b["moves"]["state"] == ("ok" if spoke else "absent")
    quiet = {"days": [{**d, "state": "absent", "lines": []} for d in wire["moves"]["days"]]}
    silent = _edition({**wire, "moves": quiet})["blocks"]["moves"]
    assert silent["state"] == "absent" and silent["absent_text"] == "No coach line is recorded in these seven days."
    # The lead's weekly read: served when the wire's priority carries one, absent (with no data) when it does not.
    lead = b["lead_read"]
    if wire["priority"].get("weekly_priority"):
        assert lead["state"] in {"ok", "stale"} and lead["data"]
    else:
        assert lead["state"] == "absent" and lead["data"] is None


def test_edition_moves_carry_each_day_as_its_route_serves_it():
    wire = _wire()
    # The capture's newest days carry lines; the state these assertions need (a quiet week with ONE
    # line on the third day) is built from the capture's days with the others emptied.
    days = [{**d, "state": "absent", "lines": []} for d in wire["moves"]["days"]]
    line = {
        "coach_id": "sleep_coach",
        "coach": "Lisa Park",
        "move": "ask",
        "move_label": "An ask",
        "text": "Bed by ten.",
        "replies_to": None,
        "bet_settles": None,
    }
    days[2] = {**days[2], "state": "ok", "lines": [line]}
    # A day outside the window (the route never serves it for this edition) is dropped.
    days.append({**days[0], "date": "2026-09-20", "state": "ok", "lines": [line]})
    block = _edition({**wire, "moves": {"days": days}})["blocks"]["moves"]
    assert block["state"] == "ok" and block["as_of"] == days[2]["date"]
    assert [d["date"] for d in block["data"]["days"]] == _days_back(_CAPTURE_DAY)
    # Read through the route with no date (read_bodies without its narrow readers): one day.
    one = _edition({**wire, "moves": days[0]})["blocks"]["moves"]
    assert one["state"] == "absent"
    # Every day's read failing is a failed read, not a silent week.
    down = [{"state": "unavailable", "date": d["date"], "lines": []} for d in wire["moves"]["days"]]
    assert _edition({**wire, "moves": {"days": down}})["blocks"]["moves"]["state"] == "unavailable"


def test_edition_reads_seven_days_of_moves_and_a_failed_day_is_never_an_empty_one():
    """``read_moves``: one in-process read of /api/coach_moves per day, the edition's day first;
    a day whose read failed is the route's own unavailable body, not a day nobody spoke."""
    asked = []

    def read(path, qs):
        asked.append((path, dict(qs)))
        if qs["date"] == _days_back(_CAPTURE_DAY)[2]:
            return {"statusCode": 503, "body": _json.dumps({"error": "x"})}
        return {"statusCode": 200, "body": _json.dumps({"state": "absent", "date": qs["date"], "lines": []})}

    got = _reads.read_moves(read, _CAPTURE_DAY)
    days = [d["date"] for d in got["days"]]
    assert asked == [("/api/coach_moves", {"date": d}) for d in days]
    assert days == _days_back(_CAPTURE_DAY)
    failed = got["days"][2]
    assert failed["state"] == "unavailable" and failed["absent_text"].endswith("are not served right now.")
    assert _edition({**_wire(), "moves": got})["blocks"]["moves"]["state"] == "absent"


def test_edition_coach_texts_from_different_days_are_each_dated():
    """The wire's own state: the coaches' texts were written on different days. With no current day of
    moves (so the restated path speaks) and every seat but the sleep and nutrition coaches marked absent,
    those two are the lines. Each line carries its own as_of AND says which day it is from; same-day lines
    say nothing extra. The days are read from the wire, never pinned."""
    wire = _wire()
    dash = _json.loads(_json.dumps(wire["dashboard"]))
    dash["moves"] = None

    def spoken(keep):
        """The lines the restated path serves when only the seats in ``keep`` are present."""
        d = _json.loads(_json.dumps(dash))
        for c in d["coaches"]:
            c["absent"] = c["coach_id"] not in keep
        return _edition({**wire, "dashboard": d})["blocks"]["coach_lines"]

    # Which seats the capture's restated text actually serves, and the day each was written.
    day_of = {}
    for c in dash["coaches"]:
        got = spoken({c["coach_id"]})
        if got["data"]:
            day_of[c["coach_id"]] = got["data"]["lines"][0]["as_of"]
    assert len(set(day_of.values())) >= 2, "the capture's coach texts are from at least two different days"
    newest = max(day_of.values())
    older = next(cid for cid, day in day_of.items() if day != newest)
    newer = next(cid for cid, day in day_of.items() if day == newest)
    block = spoken({older, newer})
    lines = block["data"]["lines"]
    assert block["data"]["mixed_days"] is True
    assert {ln["as_of"] for ln in lines} == {day_of[older], day_of[newer]}
    for ln in lines:
        assert ln["when_text"] == f"Written {_ed.day_in_words(ln['as_of'])}."
    # Same-day lines carry no day note.
    same = [cid for cid, day in day_of.items() if day == newest]
    if len(same) > 1:
        one_day = spoken(set(same))["data"]
        assert one_day["mixed_days"] is False and all(ln["when_text"] is None for ln in one_day["lines"])


def test_edition_record_never_serializes_the_count_without_the_comparison():
    """Epic #4580 rule 3: no coach number without what a simple guess would have scored.
    Whenever the record block carries the count it carries `beats_simple_guess` and the
    sentence; with either upstream (or the coaches stratum) missing, no count is served."""
    wire = _wire()
    ok = _edition(wire)["blocks"]["record"]
    served = wire["predictions"]["overall"]
    count_text = f"{served['confirmed']} of {served['confirmed'] + served['refuted']} checked calls right."
    assert ok["data"]["count_text"] == count_text
    skill = wire["calibration"]["platform"]["strata"]["coaches"]["brier_skill"]
    beats = skill > 0
    assert ok["data"]["beats_simple_guess"] is beats
    assert ok["data"]["comparison_text"] == ("So far they beat a simple guess." if beats else "So far they do not beat a simple guess.")
    no_stratum = _json.loads(_json.dumps(wire["calibration"]))
    no_stratum["platform"]["strata"].pop("coaches")
    cases = {
        "ok": wire,
        "calibration failed": {**wire, "calibration": None},
        "predictions failed": {**wire, "predictions": None},
        "no coaches stratum": {**wire, "calibration": no_stratum},
    }
    offenders = []
    for label, bodies in cases.items():
        block = _edition(bodies)["blocks"]["record"]
        data = block.get("data") or {}
        has_count = any(k in data for k in ("right", "decided", "count_text")) or count_text in _json.dumps(block)
        has_comparison = isinstance(data.get("beats_simple_guess"), bool) and bool(data.get("comparison_text"))
        if has_count and not has_comparison:
            offenders.append(f"{label}: count served without the comparison")
        if label != "ok" and (block["state"] != "unavailable" or has_count):
            offenders.append(f"{label}: expected unavailable with no count, got {block['state']}")
    assert not offenders, offenders


def test_edition_is_registered_as_a_get_route():
    """ROUTES reserves the path; _dispatch_route composes it in-process (GET only)."""
    src = _src()
    assert '"/api/edition": None' in src
    assert 'if path == "/api/edition" and method == "GET":' in src
    assert "handle_edition(lambda p, qs: _dispatch_route(" in src


def _moves(day, lines):
    return {"date": day, "generated_at": f"{day}T19:00:00+00:00", "lines": lines, "absent": [], "silent": []}


_MOVE_LINE = {
    "coach_id": "sleep_coach",
    "name": "Dr. Lisa Park",
    "move": "call",
    "move_label": "A call",
    "text": "I think the recovery score holds above 80 this week.",
    "date": _CAPTURE_DAY,
    "replies_to": None,
    "replies_to_name": None,
    "bet": {"description": "recovery stays above 80", "resolution_date": "2026-10-10"},
}


def test_edition_serves_the_days_coach_moves_when_a_current_day_exists():
    """#4583: a current day of moves replaces the restated text, tagged ``voice: move``."""
    wire = _wire()
    wire["dashboard"]["moves"] = _moves(_CAPTURE_DAY, [_MOVE_LINE])
    block = _edition(wire)["blocks"]["coach_lines"]
    assert block["state"] == "ok" and block["voice"] == "move" and block["as_of"] == _CAPTURE_DAY
    (line,) = block["data"]["lines"]
    assert line["coach"] == "Lisa Park" and line["domain"] == "sleep" and line["move"] == "call"
    assert line["text"] == _MOVE_LINE["text"] and line["bet_settles"] == "2026-10-10"


def test_a_day_no_coach_spoke_is_stated_not_backfilled_with_restated_numbers():
    wire = _wire()
    wire["dashboard"]["moves"] = _moves(_CAPTURE_DAY, [])
    block = _edition(wire)["blocks"]["coach_lines"]
    assert block["state"] == "absent" and block["voice"] == "move" and block["data"] is None
    assert block["absent_text"] == f"No coach had anything to say on {_ed.day_in_words(_CAPTURE_DAY)}."


def test_stale_or_missing_moves_fall_back_to_the_restated_text():
    """Mutation control for the two tests above: without a current day the old path stands."""
    for moves in (None, _moves("2026-09-30", [_MOVE_LINE]), {"date": "not-a-day", "lines": [_MOVE_LINE]}):
        wire = _wire()
        wire["dashboard"]["moves"] = moves
        assert _edition(wire)["blocks"]["coach_lines"]["voice"] == "restated"


def test_a_move_line_with_a_deficit_figure_or_a_cycle_count_is_dropped():
    wire = _wire()
    bad = dict(_MOVE_LINE, text="I think the 900 kcal deficit is too steep.")
    wire["dashboard"]["moves"] = _moves(_CAPTURE_DAY, [bad, _MOVE_LINE])
    lines = _edition(wire)["blocks"]["coach_lines"]["data"]["lines"]
    assert [ln["text"] for ln in lines] == [_MOVE_LINE["text"]]


def test_the_whole_life_rows_state_one_served_fact_per_area_in_order():
    """#4586: body, training, sleep, food, habits, supplements, experiments, mind — each a
    fact from its own route, none with a verdict."""
    wire = _wire()
    life = _edition(wire)["blocks"]["life"]
    assert life["state"] == "ok" and life["data"]["order"] == list(_ed.LIFE_ORDER)
    rows = life["data"]["rows"]
    text = {k: (r["data"] or {}).get("text") for k, r in rows.items()}
    # Every figure is read from the wire body the row is made from, or the row's sentence shape is asserted.
    j = wire["journey"]["journey"]
    assert text["body"] == f"{j['lost_lbs']:g} lb down so far; {j['remaining_lbs']:g} lb to go to reach {j['goal_weight_lbs']:g}."
    first = wire["session"]["exercises"][0]["name"]
    assert text["training"].startswith(f"Planned for today: {first}") and text["training"].endswith(".")
    assert re.fullmatch(r"Slept \d+(\.\d)? hours on the night of \w+, \w+ \d+; recovery \d+ out of 100\.", text["sleep"]), text["sleep"]
    n = wire["nutrition"]["nutrition"]
    assert (
        text["food"]
        == f"At or above the {n['protein_floor_g']:g} g protein floor on {n['protein_floor_hit_days']} of {n['days_logged']} logged days."
    )
    hs = wire["habits"]["habit_streaks"]
    assert text["habits"].startswith(f"{hs['tier0_done']} of {hs['tier0_total']} daily habits kept on ")
    assert text["supplements"] == f"{wire['supplements']['total_count']} in the daily stack."
    assert re.fullmatch(r"(None running right now|Running now: .+)(; \d+ ready to start)?\.", text["experiments"]), text["experiments"]
    assert rows["mind"]["state"] == "stale" and rows["mind"]["absent_text"].startswith("Nothing new in his own words since")
    for row in rows.values():
        assert not ({"verdict", "status", "going_well"} & set(row.get("data") or {})), "a row carries a verdict (#4595 owns the rules)"


def test_a_whole_life_row_with_nothing_or_an_old_fact_says_so():
    wire = _wire()
    wire["session"] = {"date": "2026-10-02", "state": "served", "exercises": [{"name": "Squat (Barbell)"}]}
    wire["habits"] = {"habit_streaks": {"as_of_date": "2026-09-28", "tier0_done": 5, "tier0_total": 7}}
    wire["experiments"] = {"experiments": [{"name": "Morning light", "status": "active"}, {"name": "X", "status": "backlog"}]}
    rows = _edition(wire)["blocks"]["life"]["data"]["rows"]
    assert rows["training"]["state"] == "absent" and rows["training"]["absent_text"] == "No session is planned for today."
    assert rows["habits"]["state"] == "stale" and rows["habits"]["absent_text"] == "Nothing newer than Monday, September 28."
    assert rows["experiments"]["data"]["text"] == "Running now: Morning light."


def test_the_last_seven_days_carry_one_value_per_day_and_never_a_zero_for_a_gap():
    """#4586: seven Pacific days ending on the edition's day; a day with no reading is None."""
    week = _edition(_wire())["blocks"]["week"]
    assert week["state"] == "ok"
    d = week["data"]
    assert d["days"] == _days_back(_CAPTURE_DAY)[::-1]
    m = d["measures"]
    wire = _wire()
    # weight: the wire's own weigh-in per day, None for a day without one, and a sentence from those values
    weights = [w for w in m["weight"]["data"]["values"] if w is not None]
    assert len(m["weight"]["data"]["values"]) == 7 and weights, "seven slots, at least one weigh-in"
    assert (
        m["weight"]["data"]["text"].startswith(f"{weights[-1]:g} lb, ")
        and f"across {len(weights)} weigh-ins." in m["weight"]["data"]["text"]
    )
    assert (
        m["training"]["data"]["text"]
        == f"Trained on {sum(1 for x in m['training']['data']['met'] if x)} of {sum(1 for x in m['training']['data']['met'] if x is not None)} days recorded."
    )
    met = m["sleep"]["data"]["met"]
    assert (
        m["sleep"]["data"]["text"]
        == f"Slept 7 hours or more on {sum(1 for x in met if x)} of {sum(1 for x in met if x is not None)} days recorded."
    )
    food = m["food"]["data"]
    floor = wire["nutrition"]["nutrition"]["protein_floor_g"]
    assert [v is None for v in food["values"]] == [v is None for v in food["met"]], "a gap day is a gap in both"
    assert all(
        met_ == (v >= floor) for v, met_ in zip(food["values"], food["met"]) if v is not None
    ), "the floor is the wire's, not a literal"
    kept, logged = sum(1 for x in food["met"] if x), sum(1 for x in food["met"] if x is not None)
    assert food["text"] == f"At or above {floor:g} g protein on {kept} of {logged} days recorded."
    assert d["weight_series"][0]["date"] == wire["journey"]["journey"]["started_date"] and d["weight_series"][-1]["date"] <= _CAPTURE_DAY


def test_a_measure_with_no_reading_this_week_is_absent_not_a_row_of_zeroes():
    wire = _wire()
    wire["training"] = {"daily_modality_minutes_30d": [{"date": "2026-09-01", "total_min": 60}]}
    part = _edition(wire)["blocks"]["week"]["data"]["measures"]["training"]
    assert part["state"] == "absent" and part["data"] is None and part["absent_text"] == "Training has no reading in these seven days."


def test_each_of_the_seven_days_opens_to_what_was_recorded_that_day():
    """#4586 (tap a day): newest first; a measure with no reading that day is left out."""
    wire = _wire()
    detail = _edition(wire)["blocks"]["week"]["data"]["detail"]
    assert [d["date"] for d in detail] == _days_back(_CAPTURE_DAY) and len(detail) == 7
    newest = detail[0]
    assert re.fullmatch(r"\d+\.\d lb( · trained)?( · slept \d+(\.\d)? h)?", newest["summary"]), newest["summary"]
    assert [f["label"] for f in newest["facts"]][:1] == ["Weight"]
    # Steps stay off the front page's day (unreliable on days the phone is not carried).
    assert "Steps" not in [f["label"] for d in detail for f in d["facts"]]
    # A day carries a Food fact exactly when the wire has a food row for it: the day must not invent one,
    # and must not drop one it was served. The protein and kcal are the row's own.
    fed = {r["date"]: r for r in wire["nutrition"]["nutrition_trend"]}
    for d in detail:
        food = [f for f in d["facts"] if f["label"] == "Food"]
        assert bool(food) == (d["date"] in fed), d["date"]
        if food:
            row = fed[d["date"]]
            assert food[0]["text"] == f"{row['protein_g']:g} g protein, {row['calories']:,} kcal"
    assert any("Food" not in [f["label"] for f in d["facts"]] for d in detail), "the capture has a day without a food row"


def test_a_day_with_no_rows_at_all_says_nothing_was_recorded():
    wire = _wire()
    wire["pulse"] = {"pulse_history": []}
    wire["training"] = {"daily_modality_minutes_30d": []}
    wire["nutrition"] = dict(wire["nutrition"], nutrition_trend=[])
    assert all(d["summary"] == "Nothing recorded yet." and d["facts"] == [] for d in _edition(wire)["blocks"]["week"]["data"]["detail"])


def test_todays_zero_training_minutes_is_not_a_day_without_training():
    """Live 2026-10-04 08:14 PT: 'Trained on 6 of 7 days' — the seventh was today, not over.
    Control: the same zero on a past day IS a recorded day without training."""
    wire = _wire()
    rows = [dict(r) for r in wire["training"]["daily_modality_minutes_30d"]]
    rows[-1] = {"date": _CAPTURE_DAY, "total_min": 0}
    wire["training"] = {"daily_modality_minutes_30d": rows}
    week = _edition(wire)["blocks"]["week"]["data"]
    assert week["measures"]["training"]["data"]["values"][-1] is None
    assert week["measures"]["training"]["data"]["text"] == "Trained on 6 of 6 days recorded."
    assert "Training" not in [f["label"] for f in week["detail"][0]["facts"]]
    rows[-2] = {"date": rows[-2]["date"], "total_min": 0}
    past = _edition(wire)["blocks"]["week"]["data"]
    assert past["measures"]["training"]["data"]["text"] == "Trained on 5 of 6 days recorded."
    assert {"label": "Training", "text": "No training recorded."} in past["detail"][1]["facts"]


# ── #4584: his own words — the owner-words store leads, the decisions note is the fallback ──
#
# tests/fixtures/edition_wire_4582/owner_words.json is the route's SILENCE body (the store had no
# entry when the fixture was cut; the route was not yet deployed, so it is the handler's own output,
# pinned to the handler below — not a live capture).


def _owner_words(*entries):
    return {"state": "ok" if entries else "absent", "entries": list(entries), "count": len(entries), "sentence": None}


def _entry(text, day, prompt=None, channel="chat"):
    return {"text": text, "date": day, "date_text": "", "channel": channel, "prompt": prompt}


def test_the_owner_words_fixture_is_the_routes_own_silence_body():
    from content import owner_words as _ow

    body = _json.load(open(os.path.join(_WIRE, "owner_words.json"), encoding="utf-8"))
    body.pop("_meta")
    assert body == _ow.public_view([])


def test_a_fresh_owner_note_leads_his_words_exactly_as_typed_with_its_date_and_prompt():
    wire = _wire()
    typed = "  honestly tired —  but still here,, and the walk helped  "
    fresh, older = _days_back(_CAPTURE_DAY, 3)[2], _days_back(_CAPTURE_DAY, 5)[4]  # inside the 7-day window, relative to the edition's day
    wire["owner_words"] = _owner_words(_entry(typed, fresh, prompt="How did the week feel?"), _entry("older", older))
    block = _edition(wire)["blocks"]["his_words"]
    assert block["state"] == "ok" and block["source"] == "/api/owner_words" and block["as_of"] == fresh
    assert block["data"]["text"] == typed, "served byte for byte: no trim, no tidy"
    assert block["data"]["prompt"] == "How did the week feel?" and block["data"]["date_text"] == _ed.day_in_words(fresh)
    mind = _edition(wire)["blocks"]["life"]["data"]["rows"]["mind"]
    assert mind["state"] == "ok" and mind["as_of"] == fresh


def test_silence_or_an_old_owner_note_falls_back_to_the_decisions_note():
    """Mutation control: with no served entry (silence and a held entry are the same payload), or with
    only an entry older than the decisions note, the block is exactly what the decisions note alone says."""
    baseline = _edition(_wire())["blocks"]["his_words"]
    assert baseline["source"] == "/api/decisions"
    for owner in (_owner_words(), _owner_words(_entry("very old words", "2026-09-01"))):
        wire = _wire()
        wire["owner_words"] = owner
        assert _edition(wire)["blocks"]["his_words"] == baseline


def test_a_stale_owner_note_newer_than_the_decisions_note_is_served_dated():
    wire = _wire()
    note_day = _edition(wire)["blocks"]["his_words"]["as_of"]
    newer = "2026-09-25"
    assert newer > note_day
    wire["owner_words"] = _owner_words(_entry("words from last week", newer))
    block = _edition(wire)["blocks"]["his_words"]
    assert block["state"] == "stale" and block["source"] == "/api/owner_words" and block["data"]["text"] == "words from last week"
    assert block["absent_text"] == "Nothing new in his own words since Friday, September 25."
