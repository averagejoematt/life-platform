"""tests/test_paused_envelope_vintage_3252.py — an envelope may not claim more
freshness than its stalest member (measured live 2026-08-27/28).

THE DEFECT, as it actually happened. The gating visual/AI-QA judge failed `main`
on /method/board/ with a reproduced high:

    [temporal_contradiction] Dr. Eli Marsh states "he's been eleven days into the
    cycle with no active logging (food, training, or journal entries since August
    17th)"

The site auto-rollback then ran and reported success. It reverted `site/`. The
flagged sentence is a STORED AI artifact served out of DynamoDB, so the rollback
could not reach it, and its green report was the only thing between the defect and
a reader.

THE THING THAT MAKES IT ROT. Every narrative block on /api/coaching-dashboard is a
stored record, so the response has two different times — the instant the wrapper was
assembled, and the instant the prose was written — and it published only the first.
Pulled from production 2026-08-28T00:28Z (the values in LIVE_* below are that
payload, verbatim):

    _meta.generated_at                    2026-08-28T00:28:08Z   <- request time
    regeneration_paused                   true                   <- tier 2, ADR-125
    weekly_priority.generated_at          2026-08-27T14:02:46Z   <- Day 11
    weekly_priority.as_of_day_n           ABSENT                 <- no anchor at all
    coaches[sleep].analysis_generated_at  2026-08-26T17:02:28Z   <- Day 10
    coaches[6 others]                     Day 11

While budget_guard pauses regeneration the prose stops moving and the stamp does
not, so a held read wears a fresher date on every fetch and the board's members
drift further apart every day. An ADR-104 honest-numbers violation that worsens by
itself, exactly like the #3206 dateline it sits next to.

THE POSTURE, and it is the house one, not a fourth convention: SERVE THE OLD
CONTENT UNDER AN HONEST STAMP. #802/#1971 serve a held coach read and disclose the
pause; #3206 serves frozen prose under a day-numbered dateline; #2686 puts the
honesty marker in `_meta` so no field a client already reads has to change. Blanking
a paused narrative would be a new convention and a worse one — the reader loses the
content and gains nothing the stamp doesn't already tell them.

The properties, and the mutation each one kills:

  1. the 2026-08-28 replay — the served envelope reports the OLDEST constituent;
  2. OLDEST, never newest — a max() implementation lets the freshest member launder
     the rest, which is the same laundering the request stamp already did;
  3. parsed instants, never string order — `…:28Z` sorts AFTER `…:28.557831+00:00`
     lexicographically and BEFORE it in time, so a string min() reports the later
     record as the vintage;
  4. `served_at` survives — a fix that merely renamed the field would lose the one
     honest use of request time (`is the API answering?`) and is not this fix;
  5. an unparseable declared vintage is DROPPED, not published — `_meta` is the layer
     a reader checks freshness against;
  6. handlers that declare nothing are BYTE-FOR-BYTE unchanged on `generated_at` —
     ~130 endpoints share this envelope;
  7. `weekly_priority` carries the day its claim was true for, derived from the
     record's own timestamp and never from a clock;
  8. a mixed-vintage board is DISCLOSED (`content_day_span`), because reconciling
     would mean withholding six current reads or restating one stale read as current;
  9. the SET — /api/weekly_priority reads the SAME stored record on /coaching/'s week
     lens, and #802's lesson is that fixing one surface leaves the other lying;
 10. the front-end actually consumes it — a served field no renderer reads is the
     #2703 class.
"""

import json
import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import pytest  # noqa: E402
from ai import budget_guard  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import (  # noqa: E402
    site_api_coach as C,
    site_api_common as common,
    site_api_lambda as L,
)

# ── the wire, verbatim ────────────────────────────────────────────────────────
#
# Not a hand-authored fixture. `LIVE_INTEGRATOR` is the `USER#matthew#SOURCE#ai_analysis
# / EXPERT#integrator` item read straight out of the production table on 2026-08-28
# (prose truncated, every other field and every timestamp untouched), and LIVE_COACH_STAMPS
# are the seven `analysis_generated_at` values served by production /api/coaching-dashboard
# in the same minute. Note the timestamp SHAPE those writers actually emit —
# microseconds and a literal `+00:00`, not `Z` — which is the shape a hand-written
# fixture reliably gets wrong.
GENESIS = "2026-08-17"

LIVE_INTEGRATOR = {
    "pk": "USER#matthew#SOURCE#ai_analysis",
    "sk": "EXPERT#integrator",
    "expert_key": "integrator",
    "generated_at": "2026-08-27T14:02:46.793290+00:00",
    "week_number": 2,
    "analysis": "Matthew, you've held autonomic stability across eleven days without logging a single meal, workout, or journal entry.",
    "public_summary": (
        "I'm watching Matthew hold metabolic and autonomic stability across an unusual stretch: he's been eleven days "
        "into the cycle with no active logging (food, training, or journal entries since August 17th)."
    ),
    "cross_domain_notes": {"sleep": "Sleep architecture continues to favor early wake."},
}
LIVE_INTEGRATOR_DAY = 11  # 2026-08-27 PT, genesis 2026-08-17

# domain -> the exact `created_at` on that coach's newest OUTPUT# row.
LIVE_COACH_STAMPS = {
    "sleep": "2026-08-26T17:02:28.557831+00:00",  # Day 10 — the odd one out, and the board's true vintage
    "nutrition": "2026-08-27T17:02:37.845317+00:00",
    "mind": "2026-08-27T17:03:17.133770+00:00",
    "physical": "2026-08-27T17:04:05.045277+00:00",
    "glucose": "2026-08-27T17:04:35.825243+00:00",
    "labs": "2026-08-27T17:05:36.345279+00:00",
    "explorer": "2026-08-27T17:06:05.205289+00:00",
}
LIVE_OLDEST = LIVE_COACH_STAMPS["sleep"]
LIVE_NEWEST = LIVE_COACH_STAMPS["explorer"]

_COACH_ID = {
    "sleep": "sleep_coach",
    "nutrition": "nutrition_coach",
    "mind": "mind_coach",
    "physical": "physical_coach",
    "glucose": "glucose_coach",
    "labs": "labs_coach",
    "explorer": "explorer_coach",
}


def _live_coach_rows():
    """The OUTPUT# rows, in the production shape (`OUTPUT#{date}#daily_brief_{domain}`,
    `created_at`, a reader-safe `public_summary` so audience_guard.public_blurb yields
    a blurb rather than dropping the card)."""
    rows = []
    for domain, stamp in LIVE_COACH_STAMPS.items():
        rows.append(
            {
                "pk": f"COACH#{_COACH_ID[domain]}",
                "sk": f"OUTPUT#{stamp[:10]}#daily_brief_{domain}",
                "created_at": stamp,
                "cycle": 14,
                "phase": "experiment",
                "content": f"The {domain} read, written on {stamp[:10]}.",
                "public_summary": f"Matthew's {domain} signal held steady through the window.",
                "emotional_investment": "neutral",
            }
        )
    return rows


def _pk_of(cond):
    """The partition the handler asked for, pulled out of a boto3 Key() condition tree.

    The dashboard builds `Key("pk").eq(...) & Key("sk").begins_with("OUTPUT#")`, so
    FakeDdbTable's `filter_by_pk` (which reads ExpressionAttributeValues) cannot route
    it; this walks the condition instead. Routing by real partition — rather than
    handing every query the same canned rows — is what makes the seven-coach span in
    this file a property of the HANDLER and not of the stub.
    """
    try:
        exp = cond.get_expression()
    except AttributeError:
        return None
    op, values = exp.get("operator"), exp.get("values", ())
    if op in ("AND", "OR"):
        for sub in values:
            found = _pk_of(sub)
            if found:
                return found
        return None
    if op == "=" and getattr(values[0], "name", None) == "pk":
        return values[1]
    return None


def _dashboard_table():
    rows = _live_coach_rows()
    by_pk = {}
    for row in rows:
        by_pk.setdefault(row["pk"], []).append(row)

    def _query(table, **kwargs):
        pk = _pk_of(kwargs.get("KeyConditionExpression"))
        return {"Items": list(by_pk.get(pk, []))}

    return FakeDdbTable(rows=rows, query_hook=_query)


@pytest.fixture
def dashboard(monkeypatch):
    """The live board, assembled by the real handler. Returns a callable so a test can
    vary the budget tier without re-stating the wiring."""

    def _run(tier=2, integrator=LIVE_INTEGRATOR, genesis=GENESIS):
        monkeypatch.setattr(L, "table", _dashboard_table())
        monkeypatch.setattr(C, "table", FakeDdbTable(store_items=[integrator] if integrator else []))
        monkeypatch.setattr(L, "EXPERIMENT_START", genesis)
        monkeypatch.setattr(C, "EXPERIMENT_START", genesis)
        monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)
        resp = L.lambda_handler({"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}, None)
        assert resp["statusCode"] == 200, resp
        return json.loads(resp["body"])

    return _run


# ── 1. the replay ─────────────────────────────────────────────────────────────


def test_replays_the_live_board_the_envelope_reports_the_content_not_the_request(dashboard):
    body = dashboard()
    assert body["regeneration_paused"] is True, "the tier-2 pause is correct and stays — this fix does not touch it"
    meta = body["_meta"]
    # The stalest member IS the envelope's vintage. Before this fix the value here was
    # `datetime.now()`, which is what made a frozen board look refreshed on every fetch.
    assert (
        meta["generated_at"] == LIVE_OLDEST
    ), f"the board's oldest member is the sleep coach at {LIVE_OLDEST}; the envelope reported {meta['generated_at']!r}"
    assert meta["content_as_of"] == LIVE_OLDEST, "a declared vintage is stated explicitly, not only implied by generated_at"


def test_the_envelope_never_out_claims_its_stalest_member(dashboard):
    """The invariant, derived from the SERVED payload rather than from a constant — so it
    keeps holding when the fixture's records change."""
    body = dashboard()
    stamps = [body["weekly_priority"]["generated_at"]] + [c["analysis_generated_at"] for c in body["coaches"]]
    stamps = [s for s in stamps if s]
    assert stamps, "the payload must carry constituent stamps for this invariant to mean anything"
    assert body["_meta"]["generated_at"] == min(stamps), "the envelope claimed a freshness no field under it has"


def test_served_at_still_carries_the_request_instant(dashboard):
    """Property 4. Request time is not deleted, it is NAMED. A fix that merely renamed
    `generated_at` would answer the issue and lose 'when did the API answer'."""
    body = dashboard()
    meta = body["_meta"]
    assert "served_at" in meta, "the assembly instant must survive under its own name"
    assert meta["served_at"] > meta["generated_at"], "served_at is now; generated_at is the frozen content"
    now = common.datetime.now(common.timezone.utc)
    served = common.datetime.fromisoformat(meta["served_at"])
    assert abs((now - served).total_seconds()) < 120, "served_at must be the request instant, not a copy of the content stamp"


# ── 2/3. oldest, and by instant ───────────────────────────────────────────────


def test_content_vintage_takes_the_oldest_of_the_live_board(dashboard):
    stamps = list(LIVE_COACH_STAMPS.values()) + [LIVE_INTEGRATOR["generated_at"]]
    assert common.content_vintage(*stamps) == LIVE_OLDEST
    # ...and the order of the arguments cannot decide it (a "first parseable wins" bug).
    assert common.content_vintage(*reversed(stamps)) == LIVE_OLDEST
    assert common.content_vintage(*stamps) != LIVE_NEWEST, "max() would let the freshest member launder the rest"


def test_a_z_suffix_and_a_microsecond_offset_are_ordered_as_INSTANTS():
    """Property 3 — the must-fail case for a `min(strings)` implementation.

    `…:28Z` is the EARLIER instant and the LATER string ('.' 0x2E < 'Z' 0x5A), and both
    shapes are live in this codebase — the coach/integrator writers emit `+00:00`,
    as_of_day_n's contract accepts `Z`. A string comparison here reports the later
    record as the envelope's vintage, i.e. it fails in the dishonest direction.
    """
    earlier, later = "2026-08-26T17:02:28Z", "2026-08-26T17:02:28.557831+00:00"
    assert min(earlier, later) == later, "the premise of this test: string order disagrees with time order here"
    assert common.content_vintage(earlier, later) == earlier
    assert common.content_vintage(later, earlier) == earlier


def test_a_bare_calendar_date_is_midnight_and_can_be_the_vintage():
    """The OUTPUT# sk fallback (`OUTPUT#{YYYY-MM-DD}`) the dashboard drops to when a row
    carries no `created_at`. It is a real constituent shape, so it must participate."""
    assert common.content_vintage("2026-08-27T00:05:00+00:00", "2026-08-26") == "2026-08-26"


def test_unparseable_members_are_ignored_not_treated_as_the_oldest():
    """A record that lost its timestamp must not backdate the whole envelope to the
    epoch — which is what any `sorted(..., key=lambda s: s or "")` shape would do."""
    assert common.content_vintage("", None, "not-a-date", "   ", 20260826, LIVE_OLDEST) == LIVE_OLDEST
    assert common.content_vintage("", None, "not-a-date") is None


# ── 5/6. the envelope's own contract ──────────────────────────────────────────


def test_an_unparseable_declared_vintage_is_dropped_never_published():
    body = json.loads(common._ok({"x": 1}, content_as_of="not-a-date")["body"])
    meta = body["_meta"]
    assert "content_as_of" not in meta, "a stamp nothing can parse must not reach _meta at all"
    assert meta["generated_at"] == meta["served_at"], "an undeclarable vintage falls back to the old behaviour"


def test_a_handler_that_declares_nothing_is_unchanged():
    """Property 6 — ~130 endpoints share this envelope and none of them asked for a
    behaviour change. Absent `content_as_of` means UNKNOWN vintage, never 'fresh'."""
    body = json.loads(common._ok({"x": 1})["body"])
    meta = body["_meta"]
    assert meta["generated_at"] == meta["served_at"]
    assert "content_as_of" not in meta
    assert meta["cache_seconds"] == 300


# ── 7. the day the claim was true for ─────────────────────────────────────────


def test_the_weekly_priority_carries_the_day_its_claim_was_true_for(dashboard):
    """The board's most prominent block asserts "eleven days into the cycle". Until this
    field existed nothing could compare that sentence to anything."""
    wp = dashboard()["weekly_priority"]
    assert (
        wp["as_of_day_n"] == LIVE_INTEGRATOR_DAY
    ), f"the integrator record was written {wp.get('generated_at')} against genesis {GENESIS} — Day {LIVE_INTEGRATOR_DAY}"


def test_the_day_number_tracks_the_record_not_the_wall_clock(dashboard):
    """The mutation guard for a `_current_day_n()` wiring: two stored records, one
    process, two different day numbers. A clock-derived implementation returns the same
    value for both — and would still pass the assertion above on exactly one day a year."""
    older = {**LIVE_INTEGRATOR, "generated_at": "2026-08-18T14:00:00.000000+00:00"}
    a = dashboard(integrator=older)["weekly_priority"]["as_of_day_n"]
    b = dashboard()["weekly_priority"]["as_of_day_n"]
    assert (a, b) == (2, LIVE_INTEGRATOR_DAY), f"expected (Day 2, Day {LIVE_INTEGRATOR_DAY}) from the two records, got ({a}, {b})"


def test_an_undatable_integrator_record_yields_no_day_number_never_a_guess(dashboard):
    wp = dashboard(integrator={**LIVE_INTEGRATOR, "generated_at": ""})["weekly_priority"]
    assert wp["as_of_day_n"] is None, "unknown renders nothing — never Day 0, never a guess (#1971)"


# ── 8. the board's span, disclosed ────────────────────────────────────────────


def test_a_board_spanning_two_days_says_so(dashboard):
    span = dashboard()["content_day_span"]
    assert span == {
        "oldest_day_n": 10,
        "newest_day_n": 11,
        "mixed": True,
    }, "six coaches on Day 11 and one on Day 10 is the measured live state — the payload must name the span"


def test_a_single_day_board_is_not_disclosed_as_mixed(dashboard):
    """The disclosure has to be able to say NO, or it is decoration. Re-stamp every
    coach onto the integrator's day and the span collapses."""
    same_day = {d: LIVE_INTEGRATOR["generated_at"] for d in LIVE_COACH_STAMPS}
    original = dict(LIVE_COACH_STAMPS)
    try:
        LIVE_COACH_STAMPS.update(same_day)
        span = dashboard()["content_day_span"]
    finally:
        LIVE_COACH_STAMPS.clear()
        LIVE_COACH_STAMPS.update(original)
    assert span["mixed"] is False and span["oldest_day_n"] == span["newest_day_n"] == LIVE_INTEGRATOR_DAY


# ── 9. the SET — /coaching/'s week lens reads the same record ─────────────────


def test_the_weekly_priority_endpoint_carries_the_same_anchor_and_vintage(monkeypatch):
    monkeypatch.setattr(C, "table", FakeDdbTable(store_items=[LIVE_INTEGRATOR]))
    monkeypatch.setattr(C, "EXPERIMENT_START", GENESIS)
    resp = C.handle_weekly_priority({"queryStringParameters": {}})
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body["as_of_day_n"] == LIVE_INTEGRATOR_DAY, "#802 shipped ONE surface and left the other lying — not again"
    assert body["_meta"]["generated_at"] == LIVE_INTEGRATOR["generated_at"]
    assert body["_meta"]["content_as_of"] == LIVE_INTEGRATOR["generated_at"]


# ── 10. the renderer actually reads it (the #2703 class) ──────────────────────

_JS = os.path.join(_REPO, "site", "assets", "js")


def _read_js(name):
    with open(os.path.join(_JS, name), encoding="utf-8") as fh:
        return fh.read()


def test_the_board_page_datelines_the_integrators_call_above_the_prose():
    """The flagged surface. A served field no renderer reads is a fix that passes its
    tests and does nothing; a dateline a reader meets AFTER the claim it frames is a
    footnote, not a frame."""
    src = _read_js("evidence_meta.js")
    assert "coach_asof.js" in src, "/method/board/ must use the ONE dateline helper, not a second copy of the copy"
    assert "wp.as_of_day_n" in src, "the board's chair block must pass the API's derived day number"
    assert "board-asof" in src and "rd-primary" in src
    assert src.index("board-asof") < src.index('chairStamp}<p class="rd-primary"'), "the dateline must render ABOVE the call"
    assert "content_day_span" in src, "a mixed-vintage board must be disclosed on the page, not only in the payload"


def test_the_week_lens_datelines_the_same_call():
    src = _read_js("coaching.js")
    assert "weeklyAsOf(wp.generated_at, wp.as_of_day_n)" in src, "the week's call must carry the day its claim was true for"
    # Scoped to the week's-call block: `rp-text` is also the daily line's class on the
    # Today lens further up the file, and an unscoped index() would compare the wrong two.
    block = src[src.index("weeklyAsOf(wp.generated_at") :].split("</section>")[0]
    assert "rp-asof" in block and "rp-text" in block, "the week's call lost its dateline or its quote"
    assert block.index("rp-asof") < block.index("rp-text"), "the dateline must render ABOVE the quote"


def test_no_dateline_call_site_hardcodes_a_day_number():
    """The #1971 set-guard idiom, extended to weeklyAsOf: a literal third argument would
    be a fabricated anchor, which is strictly worse than none."""
    offenders = []
    for fn in sorted(os.listdir(_JS)):
        if not fn.endswith(".js") or fn == "coach_asof.js":
            continue
        for m in re.finditer(r"weeklyAsOf\(([^)]*)\)", _read_js(fn)):
            args = [a.strip() for a in m.group(1).split(",")]
            if len(args) > 1 and re.fullmatch(r"\d+|true|false|null|undefined", args[1]):
                offenders.append(f"{fn}: weeklyAsOf({m.group(1)}) — day number hardcoded as a literal")
    assert not offenders, "\n".join(offenders)
