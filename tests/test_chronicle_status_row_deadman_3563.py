"""tests/test_chronicle_status_row_deadman_3563.py — #3563 box 3, third clause.

WHAT IS NEW HERE, and what is deliberately NOT re-created.

  NOT re-created: the IAM-parity contract test (box 1). That is
  `tests/test_role_family_write_scope.py` (#3596) — it AST-reads every
  put_item/update_item pk in the owning module of every `create_platform_lambda`
  site and asserts ⊆ the role's actions/LeadingKeys, with mutation controls in
  both arms and an explicit non-vacuity assertion naming this issue's two
  incident modules. It shipped RED as its own positive control and its
  KNOWN_GAPS ledger is now empty. Nothing in this file duplicates it.

  NOT re-created: the swallowed-denial visibility tests (box 3, clauses 1-2) —
  `tests/test_denied_write_silence_3563.py` and
  `tests/test_swallowed_denial_visibility_3563.py`.

  NEW: the WRITE-LIVENESS dead-man, which no existing instrument can answer.
  The three live alarms all fire on a LOGGED failure. The class this covers is a
  send that reports success and writes no status row WITHOUT RAISING — nothing
  to filter on. `chronicle-delivery-heartbeat` is structurally blind to it
  (delivery succeeded; only the row write was lost), and
  `tests/test_heartbeat_completeness.py` quantifies over scheduled Lambda
  function NAMES, so the clause's literal home cannot hold a DynamoDB partition
  — the category error Sessions AG and AI both recorded on #3563.

THE FIXTURES ARE THE LIVE PARTITIONS, read read-only 2026-09-19. They carry this
issue's own defect AND its fix, so the positive and negative controls are both
drawn from real history rather than manufactured:

    delivered_at (USER#matthew#SOURCE#chronicle)   status row (email_log#…)
    2026-08-14T18:00:46.974872Z                    ABSENT   <- the #3563 defect
    2026-08-21T18:00:46.286496Z                    ABSENT   <- the #3563 defect
    2026-08-28T18:00:46.710515Z                    ABSENT   <- the #3563 defect
    2026-09-11T18:00:47.104442Z                    2026-09-11T18:00:47.121691Z  (+17 ms)
    2026-09-18T18:00:47.261917Z                    2026-09-18T18:00:47.269157Z  (+8 ms)

The grant landed 2026-09-06. Every delivery after it paired inside 20 ms;
every delivery before it is a breach.
"""

import datetime as dt
import json
import os
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("SITE_BASE_URL", "https://averagejoematt.com")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.invalid")
os.environ.setdefault("EMAIL_SENDER", "qa@example.invalid")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from operational import chronicle_status_row_qa as csr  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, Check  # noqa: E402

UTC = dt.timezone.utc
PT = dt.timezone(dt.timedelta(hours=-7))
USER_PREFIX = "USER#matthew#SOURCE#"

# ── the live chronicle partition, 2026-09-19. The RECAP#/RAWCACHE# rows are
# included on purpose: the check's begins_with("DATE#") has to exclude them, and
# a fake store that only held DATE# rows could not show that it does.
LIVE_INSTALLMENTS = [
    {"sk": "DATE#2026-06-20"},
    {"sk": "DATE#2026-07-22"},
    {"sk": "DATE#2026-08-02"},
    {"sk": "DATE#2026-08-11", "delivered_at": "2026-08-14T18:00:46.974872+00:00"},
    {"sk": "DATE#2026-08-16"},
    {"sk": "DATE#2026-08-18", "delivered_at": "2026-08-21T18:00:46.286496+00:00"},
    {"sk": "DATE#2026-08-25", "delivered_at": "2026-08-28T18:00:46.710515+00:00"},
    {"sk": "DATE#2026-08-31"},
    {"sk": "DATE#2026-09-01"},
    {"sk": "DATE#2026-09-04"},
    {"sk": "DATE#2026-09-05"},
    {"sk": "DATE#2026-09-08", "delivered_at": "2026-09-11T18:00:47.104442+00:00"},
    {"sk": "DATE#2026-09-15", "delivered_at": "2026-09-18T18:00:47.261917+00:00"},
    {"sk": "RAWCACHE#2026-09-15", "delivered_at": "2026-09-15T00:00:00+00:00"},
    {"sk": "RECAP#2026-09-15"},
    {"sk": "RECAP#latest"},
]

LIVE_STATUS_ROWS = [
    {"sk": "DATE#2026-06-24", "sent_at": "2026-06-24T15:01:28.142453+00:00"},
    {"sk": "DATE#2026-07-01", "sent_at": "2026-07-01T15:01:34.494517+00:00"},
    {"sk": "DATE#2026-07-08", "sent_at": "2026-07-08T15:02:18.525281+00:00"},
    {"sk": "DATE#2026-07-15", "sent_at": "2026-07-15T15:02:15.812291+00:00"},
    {"sk": "DATE#2026-07-22", "sent_at": "2026-07-22T15:02:01.887806+00:00"},
    {"sk": "DATE#2026-09-11", "sent_at": "2026-09-11T18:00:47.121691+00:00"},
    {"sk": "DATE#2026-09-18", "sent_at": "2026-09-18T18:00:47.269157+00:00"},
]

INSTALLMENT_PK = USER_PREFIX + "chronicle"
STATUS_PK = USER_PREFIX + "email_log#wednesday_chronicle"


def _condition(cond):
    """(pk equality value, sk begins_with prefix) out of a REAL boto3 condition tree.

    Read rather than assumed, so a check that queried the wrong partition — or
    dropped the DATE# prefix and swept RECAP# rows in — cannot read green off a
    fake table that answers any query (the fixture-must-be-the-wire rule).
    """
    eq, begins = [], []

    def walk(node):
        expr = getattr(node, "get_expression", None)
        if expr is None:
            return
        e = expr()
        op, vals = e.get("operator"), e["values"]
        if op == "=":
            eq.append((vals[0].name, vals[1]))
        elif op == "begins_with":
            begins.append((vals[0].name, vals[1]))
        for v in vals:
            walk(v)

    walk(cond)
    assert len(eq) == 1 and eq[0][0] == "pk", f"expected exactly one pk equality, got {eq}"
    assert len(begins) == 1 and begins[0][0] == "sk", f"expected exactly one sk begins_with, got {begins}"
    return eq[0][1], begins[0][1]


class FakeTable:
    """Paginated (page=2, so the LastEvaluatedKey loop is exercised) and it
    honours both the pk and the sk prefix it was actually asked for."""

    def __init__(self, store, raises=None, page=2):
        self.store = store
        self.raises = raises
        self.page = page
        self.queries = 0
        self.pks_read = []

    def query(self, **kw):
        self.queries += 1
        if self.raises:
            raise self.raises
        pk, prefix = _condition(kw["KeyConditionExpression"])
        self.pks_read.append(pk)
        rows = [r for r in self.store.get(pk, []) if str(r["sk"]).startswith(prefix)]
        rows = sorted(rows, key=lambda r: r["sk"])
        start = int(kw.get("ExclusiveStartKey", {}).get("n", 0))
        out = {"Items": rows[start : start + self.page]}
        if start + self.page < len(rows):
            out["LastEvaluatedKey"] = {"n": start + self.page}
        return out


def _pt_now(iso_utc):
    return lambda: dt.datetime.fromisoformat(iso_utc).replace(tzinfo=UTC).astimezone(PT)


def _run(iso_utc, installments=None, status_rows=None, raises=None):
    store = {
        INSTALLMENT_PK: LIVE_INSTALLMENTS if installments is None else installments,
        STATUS_PK: LIVE_STATUS_ROWS if status_rows is None else status_rows,
    }
    table = FakeTable(store, raises=raises)
    results = csr.check_chronicle_status_row_liveness(table, USER_PREFIX, Check, CONTENT_TRUTH, _pt_now(iso_utc))
    assert len(results) == 1
    return results[0], table


# ══════════════════════════════════════════════════════════════════════════════
# The two controls, both drawn from real history
# ══════════════════════════════════════════════════════════════════════════════


def test_the_founding_incident_replays_as_a_fail_naming_both_sends():
    """2026-08-29, the day after the third swallowed denial. The window holds the
    08-21 and 08-28 deliveries and neither has a row. This is the state that sat
    unreported for 44 days while /api/status read RED."""
    c, _ = _run("2026-08-29T18:30:00")
    assert c.passed is False, c.message
    assert "DATE#2026-08-18" in c.message and "DATE#2026-08-25" in c.message
    assert "2026-08-21T18:00:46" in c.message and "2026-08-28T18:00:46" in c.message


def test_negative_control_the_post_grant_window_is_green():
    """The other half of the same real history: after the 2026-09-06 grant, both
    deliveries paired. Without this arm every red above proves nothing."""
    c, table = _run("2026-09-19T18:30:00")
    assert c.passed is True, c.message
    assert "DATE#2026-09-08" in c.message and "DATE#2026-09-15" in c.message
    assert table.queries > 2, "pagination loop was never exercised"


def test_the_check_reads_exactly_the_two_partitions_it_pairs():
    _, table = _run("2026-09-19T18:30:00")
    assert set(table.pks_read) == {INSTALLMENT_PK, STATUS_PK}


def test_the_finding_is_content_truth_so_it_can_never_roll_back_the_fleet():
    """#1921: a missing row from a cron days ago is not evidence about the deploy
    in flight, and reverting 100 Lambdas cannot conjure it."""
    c, _ = _run("2026-08-29T18:30:00")
    assert c.partition == CONTENT_TRUTH


# ══════════════════════════════════════════════════════════════════════════════
# Mutation controls — each red must be caused by the thing it names
# ══════════════════════════════════════════════════════════════════════════════


def test_MUTATION_removing_the_newest_status_row_reds_by_name():
    rows = [r for r in LIVE_STATUS_ROWS if r["sk"] != "DATE#2026-09-18"]
    c, _ = _run("2026-09-19T18:30:00", status_rows=rows)
    assert c.passed is False, c.message
    assert "DATE#2026-09-15" in c.message  # the installment whose delivery lost its row
    assert "DATE#2026-09-08" not in c.message  # the one that kept its row is not implicated


def test_MUTATION_an_older_breach_behind_a_clean_head_is_a_warn_not_a_fail():
    """Holes heal at the head and stay in the body: the newest delivery landing
    its row must not hide an earlier one that did not, and must not be reported
    at the same severity either."""
    rows = [r for r in LIVE_STATUS_ROWS if r["sk"] != "DATE#2026-09-11"]
    c, _ = _run("2026-09-19T18:30:00", status_rows=rows)
    assert c.passed is None, c.message
    assert c.chronic is False, "a novel write-liveness breach is never a chronic warn"
    assert "DATE#2026-09-08" in c.message
    assert "DATE#2026-09-15" in c.message and "working now" in c.message


@pytest.mark.parametrize(
    "skew_seconds, expect_pass",
    [
        (59, True),  # inside the clause's 60s — paired
        (61, False),  # outside it — a row that belongs to some other instant
    ],
)
def test_MUTATION_the_60s_pairing_window_is_load_bearing_in_both_directions(skew_seconds, expect_pass):
    rows = []
    for r in LIVE_STATUS_ROWS:
        if r["sk"] == "DATE#2026-09-18":
            moved = dt.datetime.fromisoformat(r["sent_at"]) + dt.timedelta(seconds=skew_seconds)
            rows.append({"sk": r["sk"], "sent_at": moved.isoformat()})
        else:
            rows.append(r)
    c, _ = _run("2026-09-19T18:30:00", status_rows=rows)
    assert (c.passed is True) is expect_pass, f"skew={skew_seconds}s: {c.message}"
    assert csr.PAIRING_WINDOW_SECONDS == 60


def test_MUTATION_a_delivery_in_the_FUTURE_cannot_demote_todays_breach():
    """The upper bound of the window, pinned because its absence was a real
    defect in the first draft of this module: the founding incident replayed as
    a WARN rather than a FAIL, because the (later) 2026-09-15 delivery — which
    had not happened yet on the replayed date — was counted as "the newest
    delivery in the window" and it had a row.
    """
    c, _ = _run("2026-08-29T18:30:00")
    assert c.passed is False, c.message
    assert "DATE#2026-09-15" not in c.message, "a delivery after `now` must not be in the window at all"


def test_MUTATION_a_status_row_without_a_delivery_is_never_a_finding():
    """One-directional by design. The 2026-06-24 .. 07-22 rows predate #2112's
    delivered_at marker; quantifying in that direction would red forever on
    history nobody can change."""
    assert csr.unpaired([], csr.status_instants(LIVE_STATUS_ROWS)) == []
    c, _ = _run("2026-07-25T18:30:00")  # window holds status rows, zero deliveries
    assert c.passed is True, c.message
    assert "chronicle-delivery-heartbeat" in c.message  # names whose class a delivery GAP is


# ══════════════════════════════════════════════════════════════════════════════
# Non-vacuity and the read-failure arm — a check that cannot fail is worse than none
# ══════════════════════════════════════════════════════════════════════════════


def test_the_extractors_actually_see_the_live_witnesses():
    """If either extraction returned nothing, every assertion in this file would
    pass for free. Pinned against the real partition contents."""
    delivered = csr.deliveries(LIVE_INSTALLMENTS)
    recorded = csr.status_instants(LIVE_STATUS_ROWS)
    # Ordered by the delivery INSTANT, not by sk — the RAWCACHE row's stamp
    # (09-15) falls between DATE#2026-09-08's (09-11) and DATE#2026-09-15's
    # (09-18). It is here to show the raw extractor is honest about what it is
    # handed; the live path never sees it, because `_query_partition` asks for
    # `begins_with("DATE#")` (pinned by test_the_check_reads_exactly_… below).
    assert [sk for sk, _ in delivered] == [
        "DATE#2026-08-11",
        "DATE#2026-08-18",
        "DATE#2026-08-25",
        "DATE#2026-09-08",
        "RAWCACHE#2026-09-15",
        "DATE#2026-09-15",
    ]
    assert len(recorded) == 7
    # The measured spread on the two sends that wrote BOTH witnesses: 17 ms, 8 ms.
    pairs = {sk: when for sk, when in delivered}
    stamps = {sk: when for sk, when in recorded}
    assert abs((stamps["DATE#2026-09-11"] - pairs["DATE#2026-09-08"]).total_seconds()) < 0.05
    assert abs((stamps["DATE#2026-09-18"] - pairs["DATE#2026-09-15"]).total_seconds()) < 0.05


def test_a_partition_with_no_delivered_at_anywhere_warns_instead_of_passing():
    """The witness-side non-vacuity guard: if a refactor renames or drops
    delivered_at, this check must say so rather than report every week clean —
    which is the #3563 failure mode one level up."""
    c, _ = _run("2026-09-19T18:30:00", installments=[{"sk": r["sk"]} for r in LIVE_INSTALLMENTS])
    assert c.passed is None, c.message
    assert "delivered_at" in c.message and "No verdict" in c.message


def test_an_empty_installment_partition_is_not_a_pass():
    c, _ = _run("2026-09-19T18:30:00", installments=[])
    assert c.passed is None, c.message
    assert "broken read" in c.message


def test_a_query_failure_warns_and_never_reports_clean():
    c, _ = _run("2026-09-19T18:30:00", raises=RuntimeError("AccessDeniedException: dynamodb:Query"))
    assert c.passed is None, c.message
    assert "no verdict was reached" in c.message
    assert "AccessDeniedException" in c.message


# ══════════════════════════════════════════════════════════════════════════════
# Wiring — an unwired dead-man is a dead dead-man
# ══════════════════════════════════════════════════════════════════════════════


def test_the_check_is_wired_into_the_nightly_run_list():
    import qa_smoke_lambda as qa

    labels = [label for label, _ in qa.check_steps()]
    assert "chronicle_status_row" in labels


# ══════════════════════════════════════════════════════════════════════════════
# #4539 — the Story Desk's dead-men (operational/story_season_qa.py)
#
# Housed in this module because it is the chronicle partition's dead-man family and
# shares its paginated, condition-reading FakeTable. Enrolment (the heartbeat ledger
# row, the leg's registration, the Monday rule's cron) is asserted in
# tests/test_heartbeat_completeness.py.
#
# THE FIXTURES ARE THE LIVE ROWS, read read-only 2026-10-03: the six published
# cycle-17 installments, the five LEDGER# rows the season promote wrote, and the
# five episodes /panelcast/episodes.json serves. The pilot-phase, draft and unlisted
# rows are kept on purpose — the check has to exclude them, and a fixture holding
# only season rows could not show that it does.
# ══════════════════════════════════════════════════════════════════════════════

from operational import story_season_qa as ssq  # noqa: E402
from operational.census_probe import ProbeBudget  # noqa: E402

_REBUILT = "story-desk season rebuild (#4537)"
SEASON_ROWS = [
    {"sk": "DATE#2026-02-22", "date": "2026-02-22", "phase": "pilot", "cycle": "5", "status": "published", "week_number": "1"},
    {
        "sk": "DATE#2026-02-28",
        "date": "2026-08-31",
        "phase": "experiment",
        "cycle": "17",
        "status": "published",
        "week_number": "0",
        "approved_at": "2026-10-02T18:31:35Z",
        "rebuilt_by": _REBUILT,
    },
    {
        "sk": "DATE#2026-07-21",
        "date": "2026-09-05",
        "phase": "experiment",
        "cycle": "17",
        "status": "published",
        "week_number": "1",
        "unlisted": True,
        "approved_at": "2026-07-24T18:00:44.139427+00:00",
    },
    {"sk": "DATE#2026-09-01", "date": "2026-09-01", "phase": "pilot", "cycle": "15", "status": "draft", "week_number": "1"},
    {"sk": "DATE#2026-09-05", "date": "2026-09-05", "phase": "experiment", "cycle": "17", "status": "published", "week_number": "0"},
    {
        "sk": "DATE#2026-09-08",
        "date": "2026-09-08",
        "phase": "experiment",
        "status": "published",
        "week_number": "1",
        "approved_at": "2026-09-11T18:00:44.191941+00:00",
        "delivered_at": "2026-09-11T18:00:47.104442+00:00",
    },
    {
        "sk": "DATE#2026-09-15",
        "date": "2026-09-15",
        "phase": "experiment",
        "status": "published",
        "week_number": "2",
        "approved_at": "2026-09-18T18:00:44.273958+00:00",
        "delivered_at": "2026-09-18T18:00:47.261917+00:00",
    },
    {
        "sk": "DATE#2026-09-22",
        "date": "2026-09-22",
        "phase": "experiment",
        "status": "published",
        "week_number": "3",
        "approved_at": "2026-09-25T18:00:43.932235+00:00",
        "delivered_at": "2026-09-25T18:00:47.026077+00:00",
    },
    {
        "sk": "DATE#2026-09-29",
        "date": "2026-09-29",
        "phase": "experiment",
        "status": "published",
        "week_number": "4",
        "approved_at": "2026-10-02T18:31:37Z",
    },
    {"sk": "RAWCACHE#2026-09-29", "week_number": "4"},
    {"sk": "RECAP#2026-09-29", "status": "published"},
    {"sk": "RECAP#latest", "status": "published"},
]
SEASON_LEDGERS = [
    {"sk": f"LEDGER#{d}", "record_type": "story_ledger", "cycle": "17", "phase": "experiment"}
    for d in ("2026-08-31", "2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29")
]
# /panelcast/episodes.json as served 2026-10-03 (the fields this check reads, plus the title).
SEASON_EPISODES = [
    {"week": 4, "title": "EP4 · The Body Answers Back", "date": "2026-10-01", "url": "/panelcast/wk4.mp3"},
    {"week": 3, "title": "EP3 · Storming Mode", "date": "2026-09-24", "url": "/panelcast/wk3.mp3"},
    {"week": 2, "title": "EP2 · Nine Days and Counting", "date": "2026-09-17", "url": "/panelcast/wk2.mp3"},
    {"week": 1, "title": "EP1 · The Strap Said 76%", "date": "2026-09-10", "url": "/panelcast/wk1.mp3"},
    {"week": 0, "title": "EP0 · Before the Numbers", "date": "2026-09-05", "url": "/panelcast/wk0.mp3"},
]
SITE = "https://averagejoematt.com"


def _episodes(weeks, pending=None):
    doc = {"episodes": [e for e in SEASON_EPISODES if e["week"] in weeks]}
    if pending:
        doc["pending"] = pending
    return doc


def _hold(week, noted_at):
    """The marker exactly as coach_panel_podcast_lambda._set_pending writes it from _hold_and_alert
    (pinned to the producer by test_the_hold_marker_fixture_is_the_producers_shape)."""
    return {
        "week": week,
        "reason": "held_for_review",
        "display": "This week's episode is in final review — it'll drop here as soon as it clears the quality bar.",
        "expected_date": None,
        "noted_at": noted_at,
    }


def _season(iso_utc, rows=None, ledgers=None, markers=None, doc=None, http=(200, None), raises=None):
    rows = SEASON_ROWS if rows is None else rows
    ledgers = SEASON_LEDGERS if ledgers is None else ledgers
    table = FakeTable({INSTALLMENT_PK: list(rows) + list(ledgers) + list(markers or [])}, raises=raises)
    body = json.dumps(_episodes({0, 1, 2, 3, 4}) if doc is None else doc) if http[1] is None else http[1]
    fetched = []

    def opener(url, timeout):
        fetched.append(url)
        return http[0], body

    out = ssq.check_story_season(
        table, USER_PREFIX, Check, CONTENT_TRUTH, _pt_now(iso_utc), site_base_url=SITE, budget=ProbeBudget(opener=opener)
    )
    by = {c.name: c for c in out}
    # #4584 added the fourth check, the Tuesday question; it reads its own partition and is exercised in
    # tests/test_tuesday_question_4584.py.
    assert set(by) == {ssq.EPISODE_CHECK, ssq.LEDGER_CHECK, ssq.QUESTIONS_CHECK, ssq.TUESDAY_CHECK}
    return by, table, fetched


def _as_of(day):
    """The season rows as they stood on `day`: nothing approved later exists yet."""
    return [r for r in SEASON_ROWS if (r.get("approved_at") or r.get("date") or "")[:10] <= day and "rebuilt_by" not in r]


def test_the_live_season_is_green_on_all_three_checks():
    by, table, fetched = _season("2026-10-03T18:30:00")
    assert all(c.passed is True for c in by.values()), {n: c.message for n, c in by.items()}
    assert "5 published season week" in by[ssq.EPISODE_CHECK].message  # weeks 0-4: pilot, draft and unlisted rows excluded
    assert set(table.pks_read) == {INSTALLMENT_PK} and fetched == [SITE + "/panelcast/episodes.json"]
    assert all(c.partition == CONTENT_TRUTH for c in by.values())


def test_HISTORY_episodes_1_and_2_would_have_alarmed_two_days_after_each_week_published():
    """#4365: weeks 1 and 2 published 09-11 and 09-18; their episodes first existed 10-02."""
    by, _, _ = _season("2026-09-13T17:59:00", rows=_as_of("2026-09-13"), doc=_episodes({0}))
    assert by[ssq.EPISODE_CHECK].passed is True and "inside its 48 h window" in by[ssq.EPISODE_CHECK].message
    by, _, _ = _season("2026-09-13T18:30:00", rows=_as_of("2026-09-13"), doc=_episodes({0}))
    assert by[ssq.EPISODE_CHECK].passed is False and "week 1" in by[ssq.EPISODE_CHECK].message
    by, _, _ = _season("2026-09-20T18:30:00", rows=_as_of("2026-09-20"), doc=_episodes({0}))
    msg = by[ssq.EPISODE_CHECK].message
    assert by[ssq.EPISODE_CHECK].passed is False and "week 1" in msg and "week 2" in msg and "week 0" not in msg


def test_HISTORY_the_week_3_hold_is_sanctioned_for_a_week_and_then_escalates():
    """Held 2026-09-25 (the day is the record; the instant is the Friday publish it followed)."""
    hold = _hold(3, "2026-09-25T18:05:00+00:00")
    rows = _as_of("2026-10-01")
    by, _, _ = _season("2026-10-01T18:30:00", rows=rows, doc=_episodes({0, 1, 2}, hold))
    assert by[ssq.EPISODE_CHECK].passed is True and "week 3 held since 2026-09-25" in by[ssq.EPISODE_CHECK].message
    by, _, _ = _season("2026-10-02T18:30:00", rows=rows, doc=_episodes({0, 1, 2}, hold))
    assert by[ssq.EPISODE_CHECK].passed is False and "HELD more than 7 days" in by[ssq.EPISODE_CHECK].message


def test_MUTATION_a_re_hold_cannot_keep_a_hold_young():
    """_set_pending rewrites noted_at on every retry. The overdue clock is the one a retry cannot reset."""
    fresh = _hold(3, "2026-10-04T18:00:00+00:00")
    by, _, _ = _season("2026-10-05T18:30:00", rows=_as_of("2026-10-01"), doc=_episodes({0, 1, 2}, fresh))
    assert by[ssq.EPISODE_CHECK].passed is False and "week 3 held since 2026-10-04" in by[ssq.EPISODE_CHECK].message


def test_MUTATION_only_a_named_dated_hold_on_that_week_excuses_a_missing_episode():
    for pending in (
        _hold(2, "2026-09-26T18:00:00+00:00"),  # a hold on ANOTHER week excuses nothing
        {**_hold(3, "2026-09-26T18:00:00+00:00"), "reason": "awaiting_material"},  # not a hold: the week IS published
        _hold(3, None),  # undated
    ):
        by, _, _ = _season("2026-09-28T18:30:00", rows=_as_of("2026-09-28"), doc=_episodes({0, 1, 2}, pending))
        assert by[ssq.EPISODE_CHECK].passed is False and "NO Panel episode" in by[ssq.EPISODE_CHECK].message, pending


def test_the_hold_marker_fixture_is_the_producers_shape():
    """Fixture must be the wire: every key and the reason literal this check reads are what the Panel writes."""
    src = open(os.path.join(_REPO, "lambdas", "emails", "coach_panel_podcast_lambda.py"), encoding="utf-8").read()
    setter = src[src.index("def _set_pending(") : src.index("def ", src.index("def _set_pending(") + 10)]
    for key in _hold(3, "x"):
        assert f'"{key}":' in setter, f"_set_pending no longer writes {key!r}"
    holder = src[src.index("def _hold_and_alert(") :]
    assert f'"{ssq.HOLD_REASON}"' in holder[: holder.index("\ndef ")], "_hold_and_alert no longer publishes HOLD_REASON"
    assert 'Key=f"{PREFIX}/episodes.json"' in setter and ssq.EPISODES_PATH == "/panelcast/episodes.json"


def test_MUTATION_a_week_with_no_ledger_row_reds_by_name():
    by, _, _ = _season("2026-10-03T18:30:00", ledgers=[r for r in SEASON_LEDGERS if r["sk"] != "LEDGER#2026-09-29"])
    assert by[ssq.LEDGER_CHECK].passed is False
    assert "week 4" in by[ssq.LEDGER_CHECK].message and "LEDGER#2026-09-29" in by[ssq.LEDGER_CHECK].message
    assert by[ssq.EPISODE_CHECK].passed is True  # independent verdicts


def test_MUTATION_a_tombstoned_ledger_row_is_not_a_ledger():
    dead = [{**r, "tombstone": True} if r["sk"] == "LEDGER#2026-09-22" else r for r in SEASON_LEDGERS]
    by, _, _ = _season("2026-10-03T18:30:00", ledgers=dead)
    assert by[ssq.LEDGER_CHECK].passed is False and "week 3" in by[ssq.LEDGER_CHECK].message


def test_week_0_is_filed_under_its_date_attribute_not_its_url_slot():
    """The prologue's sk is DATE#2026-02-28 and its ledger is LEDGER#2026-08-31."""
    weeks = ssq.published_weeks(SEASON_ROWS)
    assert sorted(weeks) == [0, 1, 2, 3, 4] and "2026-08-31" in weeks[0]["dates"]
    assert weeks[0]["published"].isoformat() == "2026-09-05T00:00:00+00:00"  # the plan post, the week's first appearance


def _marker(week, sent_at="2026-10-05T16:00:21.412233+00:00"):
    """The row wednesday_chronicle_lambda._send_story_questions puts after SES accepts."""
    return {"sk": f"STORYQ#W{week:03d}", "questions_json": "[]", "sent_at": sent_at, "message_id": "0101-test", "phase": "experiment"}


def test_the_monday_questions_send_is_owed_from_its_first_live_monday():
    by, _, _ = _season("2026-10-03T18:30:00")
    assert by[ssq.QUESTIONS_CHECK].passed is True and "2026-09-28" in by[ssq.QUESTIONS_CHECK].message  # before the rule existed
    by, _, _ = _season("2026-10-05T16:30:00")
    assert by[ssq.QUESTIONS_CHECK].passed is True  # inside the grace hour: still last week's slot
    by, _, _ = _season("2026-10-05T18:30:00")
    assert by[ssq.QUESTIONS_CHECK].passed is False and "STORYQ#W005" in by[ssq.QUESTIONS_CHECK].message
    by, _, _ = _season("2026-10-05T18:30:00", markers=[_marker(5)])
    assert by[ssq.QUESTIONS_CHECK].passed is True
    by, _, _ = _season("2026-10-11T18:30:00", markers=[_marker(4)])  # last week's marker is not this week's send
    assert by[ssq.QUESTIONS_CHECK].passed is False
    by, _, _ = _season("2026-10-12T18:30:00", markers=[_marker(5)])
    assert by[ssq.QUESTIONS_CHECK].passed is False and "STORYQ#W006" in by[ssq.QUESTIONS_CHECK].message


def test_the_dead_man_and_the_sender_name_the_same_week():
    """One definition (story_dossier.week_containing), and the sender calls it."""
    from content import story_dossier

    assert ssq.week_containing is story_dossier.week_containing
    assert story_dossier.week_containing("2026-10-05")["week"] == 5 and story_dossier.week_containing("2026-09-06")["week"] == 1
    assert story_dossier.week_containing("2026-09-05") is None  # before genesis: no week, no send owed
    sender = open(os.path.join(_REPO, "lambdas", "emails", "wednesday_chronicle_lambda.py"), encoding="utf-8").read()
    body = sender[sender.index("def _send_story_questions(") : sender.index("def lambda_handler(")]
    assert "story_dossier.week_containing(" in body and "season_weeks(" not in body
    assert f'f"{ssq.QUESTIONS_PREFIX}{{n:03d}}"' in body


def test_no_verdict_is_never_reported_as_green():
    by, _, _ = _season("2026-10-03T18:30:00", raises=RuntimeError("AccessDenied"))
    # The chronicle-partition checks. #4584's Tuesday check reads a different partition, and on this date owes no
    # send by the clock alone; its own unreadable-partition case is pinned in tests/test_tuesday_question_4584.py.
    assert all(c.passed is None and "no verdict" in c.message for n, c in by.items() if n != ssq.TUESDAY_CHECK)
    by, _, _ = _season("2026-10-03T18:30:00", rows=[r for r in SEASON_ROWS if r.get("phase") == "pilot"])
    assert by[ssq.EPISODE_CHECK].passed is None and by[ssq.LEDGER_CHECK].passed is None
    for http in ((503, "upstream"), (200, "<html>"), (200, '{"pending": {}}')):
        by, _, _ = _season("2026-10-03T18:30:00", http=http)
        assert by[ssq.EPISODE_CHECK].passed is None and "no verdict" in by[ssq.EPISODE_CHECK].message, http
        assert by[ssq.LEDGER_CHECK].passed is True  # the ledger verdict does not depend on the site read


def test_the_story_season_leg_is_wired_into_the_nightly_run_list():
    import qa_smoke_lambda as qa

    assert "story_season" in [label for label, _ in qa.check_steps()]
