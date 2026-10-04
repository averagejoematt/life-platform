"""tests/test_site_api_routes.py — Phase 4.5 scoped: validate the router table.

The new _SIMPLE_ROUTES dict in site_api_lambda.py needs to stay in sync:
  - Every entry's handler must exist as a function
  - Every entry's path must look like an API path
  - Allowed methods must be a set of valid HTTP verbs or None
  - No duplicate entries

Doesn't import site_api_lambda directly (requires AWS env). Greps the source.
"""

import json as _json
import os
import re
import sys as _sys
from datetime import datetime as _dt, timezone as _tz

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
from web import site_api_edition as _ed  # noqa: E402
from web.prediction_reason import metric_words as _metric_words  # noqa: E402

_WIRE = os.path.join(ROOT, "tests", "fixtures", "edition_wire_4582")
_CAPTURE_DAY = "2026-10-03"
_CAPTURE_INSTANT = _dt(2026, 10, 4, 2, 29, tzinfo=_tz.utc)
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


def test_edition_every_block_carries_the_contract_on_the_wire():
    """Every block (and nested part) has state/as_of/source/absent_text/data; the document
    has ONE Pacific as_of and day_n, and the blocks arrive in page order."""
    doc = _edition(_wire())
    assert doc["as_of"] == _CAPTURE_DAY and doc["day_n"] == 28
    assert list(doc["blocks"]) == list(_ed.ORDER) == doc["order"]
    offences = [o for name, block in _parts(doc) for o in _contract_offences(name, block)]
    assert not offences, offences
    # The live wire composes to real values, not placeholders.
    b = doc["blocks"]
    assert b["chapter"]["data"]["title"] == "The Body Answers Back" and "*" not in b["chapter"]["data"]["dek"]
    assert b["chapter"]["data"]["podcast"]["data"]["guest"] == "Marcus Webb"
    assert b["today"]["data"] == {
        "weight_lbs": 311.0,
        "date": "2026-10-03",
        "start_weight_lbs": 327.3,
        "start_date": "2026-09-06",
        "goal_weight_lbs": 185.0,
        "change_lbs": -16.3,
    }
    assert b["coach_lines"]["voice"] == "restated" and len(b["coach_lines"]["data"]["lines"]) <= 3
    assert all("Dr." not in ln["coach"] for ln in b["coach_lines"]["data"]["lines"])
    assert b["scorecard"]["state"] == "absent"
    assert b["next"]["data"]["bet"]["data"]["question"].startswith("Will the morning recovery score")


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
        "nutrition": {"life.food", "week.food"},
        "pulse": {"week.weight", "week.sleep"},
        "training": {"week.training"},
        "habits": {"life.habits"},
        "supplements": {"life.supplements"},
        "experiments": {"life.experiments"},
        "dashboard": {"coach_lines"},
        "predictions": {"record"},
        "calibration": {"record"},
        "decisions": {"his_words", "life.mind"},
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


def test_edition_coach_texts_from_different_days_are_each_dated():
    """The wire's own two-day state: Lisa Park written 2026-10-03, Marcus Webb written
    2026-10-02 (the other seats marked absent, so those two are the lines). Each line
    carries its own as_of AND says which day it is from; same-day lines say nothing extra."""
    wire = _wire()
    dash = _json.loads(_json.dumps(wire["dashboard"]))
    for c in dash["coaches"]:
        if c["coach_id"] not in ("sleep", "nutrition"):
            c["absent"] = True
    wire["dashboard"] = dash
    block = _edition(wire)["blocks"]["coach_lines"]
    lines = block["data"]["lines"]
    assert [ln["coach"] for ln in lines] == ["Lisa Park", "Marcus Webb"]
    assert block["data"]["mixed_days"] is True
    assert {ln["as_of"] for ln in lines} == {"2026-10-03", "2026-10-02"}
    assert [ln["when_text"] for ln in lines] == ["Written Saturday, October 3.", "Written Friday, October 2."]
    # Same-day lines (the unmodified wire's top three are all 2026-10-03) carry no day note.
    same = _edition(_wire())["blocks"]["coach_lines"]["data"]
    assert same["mixed_days"] is False and all(ln["when_text"] is None for ln in same["lines"])


def test_edition_record_never_serializes_the_count_without_the_comparison():
    """Epic #4580 rule 3: no coach number without what a simple guess would have scored.
    Whenever the record block carries the count it carries `beats_simple_guess` and the
    sentence; with either upstream (or the coaches stratum) missing, no count is served."""
    wire = _wire()
    ok = _edition(wire)["blocks"]["record"]
    assert ok["data"]["count_text"] == "41 of 96 checked calls right."
    assert ok["data"]["beats_simple_guess"] is False and ok["data"]["comparison_text"] == "So far they do not beat a simple guess."
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
        has_count = any(k in data for k in ("right", "decided", "count_text")) or "41 of 96" in _json.dumps(block)
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
    assert block["absent_text"] == "No coach had anything to say on Saturday, October 3."


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
    life = _edition(_wire())["blocks"]["life"]
    assert life["state"] == "ok" and life["data"]["order"] == list(_ed.LIFE_ORDER)
    rows = life["data"]["rows"]
    text = {k: (r["data"] or {}).get("text") for k, r in rows.items()}
    assert text["body"] == "16.3 lb down so far; 126 lb to go to reach 185."
    assert text["training"] == "Planned for today: Deadlift (Trap bar), Squat (Barbell) and 3 more."
    assert text["sleep"] == "Slept 8.9 hours on the night of Friday, October 2; recovery 98 out of 100."
    assert text["food"] == "At or above the 170 g protein floor on 9 of 28 logged days."
    assert text["habits"] == "5 of 7 daily habits kept on Friday, October 2."
    assert text["supplements"] == "21 in the daily stack."
    assert text["experiments"] == "None running right now; 1 ready to start."
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
    assert d["days"] == ["2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03"]
    m = d["measures"]
    assert m["weight"]["data"]["values"] == [314.5, 313.2, 312.3, 311.4, 311.7, 311.0, 311.0]
    assert m["weight"]["data"]["text"] == "311 lb, down 3.5 across 7 weigh-ins."
    assert m["training"]["data"]["text"] == "Trained on 7 of 7 days recorded."
    assert m["sleep"]["data"]["text"] == "Slept 7 hours or more on 7 of 7 days recorded."
    assert m["food"]["data"]["values"][0] is None and m["food"]["data"]["met"][0] is None
    assert m["food"]["data"]["text"] == "At or above 170 g protein on 2 of 3 days recorded."
    assert d["weight_series"][0] == {"date": "2026-09-06", "lbs": 327.3} and d["weight_series"][-1]["date"] == "2026-10-03"


def test_a_measure_with_no_reading_this_week_is_absent_not_a_row_of_zeroes():
    wire = _wire()
    wire["training"] = {"daily_modality_minutes_30d": [{"date": "2026-09-01", "total_min": 60}]}
    part = _edition(wire)["blocks"]["week"]["data"]["measures"]["training"]
    assert part["state"] == "absent" and part["data"] is None and part["absent_text"] == "Training has no reading in these seven days."


def test_each_of_the_seven_days_opens_to_what_was_recorded_that_day():
    """#4586 (tap a day): newest first; a measure with no reading that day is left out."""
    detail = _edition(_wire())["blocks"]["week"]["data"]["detail"]
    assert [d["date"] for d in detail][:2] == ["2026-10-03", "2026-10-02"] and len(detail) == 7
    newest = detail[0]
    assert newest["summary"] == "311.0 lb · trained · slept 8.8 h"
    assert newest["facts"] == [
        {"label": "Weight", "text": "311.0 lb"},
        {"label": "Training", "text": "241 minutes of walking"},
        {"label": "Sleep", "text": "8.8 hours; recovery 98 out of 100"},
        {"label": "Food", "text": "153 g protein, 1,732 kcal"},
        {"label": "Steps", "text": "9,913"},
    ]
    oldest = detail[-1]
    assert "Food" not in [f["label"] for f in oldest["facts"]], "no food row was served for that day: the day must not invent one"


def test_a_day_with_no_rows_at_all_says_nothing_was_recorded():
    wire = _wire()
    wire["pulse"] = {"pulse_history": []}
    wire["training"] = {"daily_modality_minutes_30d": []}
    wire["nutrition"] = dict(wire["nutrition"], nutrition_trend=[])
    assert all(d["summary"] == "Nothing recorded yet." and d["facts"] == [] for d in _edition(wire)["blocks"]["week"]["data"]["detail"])
