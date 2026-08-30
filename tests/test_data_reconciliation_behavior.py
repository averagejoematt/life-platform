"""tests/test_data_reconciliation_behavior.py — behavioural contracts for
``lambdas/operational/data_reconciliation_lambda.py`` (#1658 coverage tranche 5).

Measured **0%** covered before this file — all 112 statements. This is the
weekly Sunday-night job that answers "did any source silently stop writing?",
and it was the highest-missing fully-dark module in the operational package.
Nothing here had ever been executed by a test, including its severity
classifier, which is what decides whether Matthew reads the report at all.

Contracts pinned here:

  * **Severity is a function of the gap DISTRIBUTION, not the total.** One
    source missing 3 days is RED even though four sources missing one day each
    is a larger total; both boundaries are pinned from the docstring's own
    rubric, on both sides.
  * **A DDB read error is "unknown", not "missing".** ``check_source_coverage``
    records ``None`` on failure, ``coverage_emoji`` renders it ❓, and an
    unknown day must not be reported to Matthew as a confirmed gap (ADR-104).
  * **The expected-days facet is honoured** — a weekday-only source that wrote
    5 of 7 days has zero gaps; the same 5/7 on a daily source is 2.
  * **Delivery is the artifact (#2835).** The standalone SES email is retired:
    the handler writes the dated archive key AND ``reconciliation/latest.json``
    (carrying the pre-rendered ``html`` section the Monday ops pack embeds),
    a dry run computes the full report but writes nothing, and a failed
    artifact write RAISES — it is the delivery now, so a silent miss must
    page via the DLQ digest instead of aging into a stale pack section.

No AWS and no network. Arithmetic is hand-derived in the body.
"""

from __future__ import annotations

import os

# Read at import time (conftest supplies fake AWS creds). #2835: the module no
# longer reads EMAIL_RECIPIENT/EMAIL_SENDER — its delivery is the S3 artifact.
os.environ.setdefault("S3_BUCKET", "test-bucket")

import json  # noqa: E402
import re  # noqa: E402

import pytest  # noqa: E402
from common.pacific_time import pacific_today  # noqa: E402  — the handler's own clock; see _all_seven
from ingestion.source_registry import reconciliation_sources  # noqa: E402
from operational import data_reconciliation_lambda as dr  # noqa: E402

DATES = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]


def _result(source, present_days, expected_days=7, notes="n"):
    """Build one source_results row with `present_days` of the week present."""
    coverage = {d: (i < present_days) for i, d in enumerate(DATES)}
    days_present = sum(1 for v in coverage.values() if v is True)
    gaps = max(0, min(expected_days, len(DATES)) - days_present)
    return {
        "source": source,
        "coverage": coverage,
        "days_present": days_present,
        "days_checked": len(DATES),
        "gaps": gaps,
        "expected_days": expected_days,
        "notes": notes,
    }


# ──────────────────────────────────────────────────────────────────────────────
# The source list
# ──────────────────────────────────────────────────────────────────────────────


def test_source_list_is_the_registry_plus_the_local_computed_partitions():
    """#498 (X-10): source rows DERIVE from the registry's expected_days facet.
    The computed partitions stay local because they are compute outputs, whose
    cadence is a schedule, not an ingestion property."""
    assert dr.SOURCES == reconciliation_sources() + dr.COMPUTED_PARTITIONS
    assert {s for s, _, _ in dr.COMPUTED_PARTITIONS} == {
        "day_grade",
        "habit_scores",
        "computed_metrics",
        "character_sheet",
        "adaptive_mode",
        "computed_insights",
    }
    assert all(e == 7 for _, e, _ in dr.COMPUTED_PARTITIONS), "every computed partition runs daily"


def test_the_inert_skip_set_stays_deleted_so_no_source_can_be_silently_unchecked():
    """#2308 (ADR-103/144): ``_SKIP_SOURCES`` was an empty set consulted by a
    ``continue`` arm — dead machinery whose only possible future was a source
    silently dropping out of reconciliation with no line in the report saying
    so. It was deleted; every entry in SOURCES is reconciled."""
    assert not hasattr(dr, "_SKIP_SOURCES")


# ──────────────────────────────────────────────────────────────────────────────
# check_source_coverage
# ──────────────────────────────────────────────────────────────────────────────


class _FakeTable:
    def __init__(self, present=(), boom=()):
        self.present = set(present)
        self.boom = set(boom)
        self.calls: list[dict] = []

    def get_item(self, Key, **kw):
        self.calls.append({"Key": Key, **kw})
        date = Key["sk"].split("#", 1)[1]
        if date in self.boom:
            raise RuntimeError("throttled")
        return {"Item": {"pk": Key["pk"]}} if date in self.present else {}


def test_check_source_coverage_maps_presence_per_day(monkeypatch):
    t = _FakeTable(present={"2026-08-01", "2026-08-03"})
    monkeypatch.setattr(dr, "table", t)
    cov = dr.check_source_coverage("whoop", DATES[:3])
    assert cov == {"2026-08-01": True, "2026-08-02": False, "2026-08-03": True}
    assert [c["Key"]["pk"] for c in t.calls] == ["USER#matthew#SOURCE#whoop"] * 3
    assert all(c["ProjectionExpression"] == "pk" for c in t.calls), "an existence probe must not pull the row"


def test_check_source_coverage_records_a_read_failure_as_unknown_not_missing(monkeypatch):
    """A throttled read is not evidence the day is empty. ADR-104: unknown is a
    third state, and it renders ❓ rather than ❌."""
    monkeypatch.setattr(dr, "table", _FakeTable(present={"2026-08-02"}, boom={"2026-08-01"}))
    cov = dr.check_source_coverage("whoop", DATES[:2])
    assert cov["2026-08-01"] is None
    assert cov["2026-08-02"] is True


def test_coverage_emoji_has_three_states():
    assert dr.coverage_emoji(True) == "✅"
    assert dr.coverage_emoji(False) == "❌"
    assert dr.coverage_emoji(None) == "❓"


# ──────────────────────────────────────────────────────────────────────────────
# classify_severity
# ──────────────────────────────────────────────────────────────────────────────


def test_severity_green_only_when_every_source_is_whole():
    label, color = dr.classify_severity([_result("whoop", 7), _result("strava", 5, expected_days=5)])
    assert label == "GREEN — Full Coverage"
    assert color == "#059669"


def test_severity_yellow_for_a_small_scatter_of_gaps():
    rows = [_result("whoop", 6), _result("notion", 5), _result("todoist", 7)]
    # Hand-derived: gaps 1 + 2 + 0 = 3; max single 2; 2 sources affected.
    assert [r["gaps"] for r in rows] == [1, 2, 0]
    label, color = dr.classify_severity(rows)
    assert label == "YELLOW — Monitor" and color == "#d97706"


def test_severity_red_on_three_missing_days_in_one_source_even_though_the_total_is_small():
    rows = [_result("whoop", 4)]
    assert rows[0]["gaps"] == 3
    assert dr.classify_severity(rows)[0] == "RED — Investigate Gaps"
    # …and two days in one source is still only YELLOW: the boundary is 3.
    assert dr.classify_severity([_result("whoop", 5)])[0] == "YELLOW — Monitor"


def test_severity_red_on_breadth_at_four_sources_and_yellow_at_three():
    three = [_result(f"s{i}", 6) for i in range(3)]
    four = [_result(f"s{i}", 6) for i in range(4)]
    assert dr.classify_severity(three)[0] == "YELLOW — Monitor"
    assert dr.classify_severity(four)[0] == "RED — Investigate Gaps"


def test_severity_on_an_empty_result_set_is_green_not_a_crash():
    assert dr.classify_severity([])[0] == "GREEN — Full Coverage"


# ──────────────────────────────────────────────────────────────────────────────
# build_html_report
# ──────────────────────────────────────────────────────────────────────────────


def test_report_renders_a_row_per_source_with_weekday_headers():
    rows = [_result("whoop", 7, notes="Recovery/sleep"), _result("notion", 5, notes="Journal")]
    html = dr.build_html_report(DATES, rows, "YELLOW — Monitor", "#d97706")
    assert "2026-08-01 → 2026-08-07" in html
    # 2026-08-01 is a Saturday; the header runs Sat…Fri for this window.
    assert re.findall(r"<th style='padding:8px;text-align:center;'>(\w{3})</th>", html) == [
        "Sat",
        "Sun",
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
    ]
    assert "whoop" in html and "notion" in html
    assert "Recovery/sleep" in html and "Journal" in html
    assert "2 sources checked | 2 total gaps | 1 sources affected" in html


def test_report_badges_a_gapped_source_and_colours_by_size():
    two_gaps = dr.build_html_report(DATES, [_result("notion", 5)], "YELLOW", "#d97706")
    assert ">2 gaps<" in two_gaps and "#d97706" in two_gaps

    one_gap = dr.build_html_report(DATES, [_result("notion", 6)], "YELLOW", "#d97706")
    assert ">1 gap<" in one_gap, "singular, not '1 gaps'"

    three_gaps = dr.build_html_report(DATES, [_result("notion", 4)], "RED", "#dc2626")
    assert ">3 gaps<" in three_gaps and "#dc2626" in three_gaps


def test_report_omits_the_recommended_actions_block_when_there_is_nothing_to_do():
    green = dr.build_html_report(DATES, [_result("whoop", 7)], "GREEN — Full Coverage", "#059669")
    assert "Recommended actions" not in green
    assert "All systems nominal" in green


def test_report_lists_the_exact_missing_dates_in_the_actions_block():
    row = _result("notion", 5)
    html = dr.build_html_report(DATES, [row], "YELLOW", "#d97706")
    assert "Recommended actions" in html
    missing = [d for d in DATES if row["coverage"][d] is False]
    assert missing == ["2026-08-06", "2026-08-07"]
    assert "<code>notion</code>: 2 gaps (2026-08-06, 2026-08-07)" in html


def test_report_renders_unknown_days_as_question_marks_not_crosses():
    row = _result("whoop", 7)
    row["coverage"]["2026-08-03"] = None
    html = dr.build_html_report(DATES, [row], "GREEN", "#059669")
    assert "❓" in html


_SUMMARY_STATES = [
    pytest.param([_result("whoop", 7)], "GREEN — Full Coverage", "#059669", "#f0fdf4", id="no-gaps-green"),
    pytest.param([_result("notion", 5)], "YELLOW — Monitor", "#d97706", "#fef3c7", id="gaps-amber"),
]


def _style_attributes(html: str) -> list[str]:
    """Every inline style attribute value the report emits (both quote styles)."""
    return [a or b for a, b in re.findall(r"style=(?:\"([^\"]*)\"|'([^']*)')", html)]


@pytest.mark.parametrize(("rows", "severity", "header_color", "expected_bg"), _SUMMARY_STATES)
def test_summary_bar_background_is_a_valid_css_colour_per_state(rows, severity, header_color, expected_bg):
    """#2308: the bar's colour is chosen in Python before the f-string — a real
    hex value, green when there are no gaps and amber when there are. The old
    template shipped the literal text '#f0fdf4 if 0==0 else #fef3c7' and the
    bar never once rendered."""
    html = dr.build_html_report(DATES, rows, severity, header_color)
    (summary_style,) = re.findall(r'<div style="(padding:16px 24px;background:[^"]*)"', html)
    background = re.search(r"background:([^;]+);", summary_style).group(1).strip()
    assert re.fullmatch(r"#[0-9a-fA-F]{3,8}", background), f"not a CSS colour: {background!r}"
    assert background == expected_bg


@pytest.mark.parametrize(("rows", "severity", "header_color", "expected_bg"), _SUMMARY_STATES)
def test_no_style_attribute_in_the_report_contains_an_unevaluated_conditional(rows, severity, header_color, expected_bg):
    """#2308, derived over the WHOLE built HTML rather than pinned to one line:
    no style attribute the report emits may carry Python conditional text or a
    literal brace token — either means an expression never evaluated."""
    html = dr.build_html_report(DATES, rows, severity, header_color)
    styles = _style_attributes(html)
    assert len(styles) > 10, "the report should emit many inline styles — the extractor is broken if not"
    for style in styles:
        assert " if " not in style and " else " not in style, f"Python conditional shipped as CSS: {style!r}"
        assert "{" not in style and "}" not in style, f"literal brace token shipped as CSS: {style!r}"


# ──────────────────────────────────────────────────────────────────────────────
# lambda_handler
# ──────────────────────────────────────────────────────────────────────────────


class _RecordingS3:
    def __init__(self, boom=False):
        self.puts: list[dict] = []
        self.boom = boom

    def put_object(self, **kw):
        if self.boom:
            raise RuntimeError("AccessDenied")
        self.puts.append(kw)


@pytest.fixture()
def handler_env(monkeypatch):
    """Wire the handler to fakes. Since #2835 the module has NO SES client and
    no send path at all — delivery is the S3 artifact, recorded here."""

    def _install(present_by_source, sources=None, s3_boom=False):
        class _T:
            def get_item(self, Key, **kw):
                source = Key["pk"].rsplit("#", 1)[-1]
                date = Key["sk"].split("#", 1)[1]
                return {"Item": {"pk": Key["pk"]}} if date in present_by_source.get(source, set()) else {}

        s3 = _RecordingS3(boom=s3_boom)
        monkeypatch.setattr(dr, "table", _T())
        monkeypatch.setattr(dr.boto3, "client", lambda name, region_name=None: s3)
        monkeypatch.setattr(dr, "SOURCES", sources or [("whoop", 7, "Recovery"), ("strava", 5, "Cardio")])
        return s3

    return _install


def _all_seven(anchor_days=7):
    """The coverage window the handler will ask for, on the HANDLER's clock.

    `data_reconciliation_lambda` bounds its window with `pacific_today()`
    (#2798/#3206). Deriving these days from `datetime.now(timezone.utc).date()`
    instead put every expected DATE# key one day ahead of the handler between
    17:00 PT and PT midnight — the 7-hour window where the UTC date has rolled
    and the Pacific one has not. The set then missed the handler's oldest day
    and carried a day it never asks for, so a whole week read as YELLOW and the
    archive key was off by one. #3206's CI ran outside that window and was
    green; the first main run to cross 00:00Z after it went red.
    """
    import datetime as _dt

    today = _dt.date.fromisoformat(pacific_today())
    return {(today - _dt.timedelta(days=i)).isoformat() for i in range(anchor_days, 0, -1)}


def test_handler_reports_green_when_every_source_is_whole(handler_env):
    week = _all_seven()
    handler_env({"whoop": week, "strava": week})
    resp = dr.lambda_handler({"dry_run": True}, None)

    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["severity"] == "GREEN — Full Coverage"
    assert body["total_gaps"] == 0 and body["sources_with_gaps"] == 0
    assert len(body["week"].split(" → ")) == 2


def test_handler_counts_gaps_against_each_sources_expected_days(handler_env):
    week = sorted(_all_seven())
    # strava expects 5/7; five present days is complete for it, but the same
    # five days on whoop (expects 7) is a two-day gap.
    handler_env({"whoop": set(week[:5]), "strava": set(week[:5])})
    body = json.loads(dr.lambda_handler({"dry_run": True}, None)["body"])
    assert body["total_gaps"] == 2
    assert body["sources_with_gaps"] == 1


def test_handler_checks_the_last_seven_completed_days_never_today(handler_env):
    import datetime as _dt

    handler_env({})
    dr.lambda_handler({"dry_run": True}, None)
    week_label = json.loads(dr.lambda_handler({"dry_run": True}, None)["body"])["week"]
    start, end = week_label.split(" → ")
    # The handler's clock, not UTC (#2798/#3206). With UTC this assertion goes
    # SLACK between 17:00 PT and PT midnight: `end` is the handler's Pacific
    # yesterday, so comparing it against an already-rolled UTC today would still
    # pass even if the handler had wrongly included its own today. Comparing on
    # the same frame is what makes this a real exclusion check.
    today = pacific_today()
    assert end < today, "ingestion may still be running today; today is deliberately excluded"
    assert (_dt.date.fromisoformat(end) - _dt.date.fromisoformat(start)).days == 6


def test_handler_dry_run_builds_the_full_report_and_writes_nothing(handler_env):
    """#2835 folded shape of the old sends-nothing contract: with no SES send
    left in the module, the manual-invoke hazard is the artifact overwrite —
    a dry run must compute the full verdict and leave S3 untouched (a stray
    latest.json overwrite would change what next Monday's ops pack embeds)."""
    s3 = handler_env({})
    resp = dr.lambda_handler({"dry_run": True}, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["severity"].startswith("RED")
    assert s3.puts == [], "dry run must not overwrite the artifact the ops pack reads"


def test_handler_artifact_carries_the_severity_and_the_rendered_section(handler_env):
    """The folded shape of inbox scannability (#2835): the severity the old
    subject line carried now rides the artifact — the ops pack lifts it into
    the pack subject (ops_subject_suffix) and embeds the html section."""
    s3 = handler_env({})
    dr.lambda_handler({}, None)
    latest = json.loads(next(p for p in s3.puts if p["Key"] == dr.LATEST_ARTIFACT_KEY)["Body"])
    assert latest["severity"] == "RED — Investigate Gaps"
    assert "Weekly Data Reconciliation" in latest["html"]
    assert "<!DOCTYPE" not in latest["html"], "the section must be an embeddable fragment, not a document"


def test_handler_archives_a_machine_readable_summary_to_s3(handler_env):
    week = sorted(_all_seven())
    s3 = handler_env({"whoop": set(week[:6]), "strava": set(week)})
    dr.lambda_handler({}, None)

    dated, latest = s3.puts
    assert dated["Bucket"] == dr.BUCKET
    assert dated["Key"] == f"reconciliation/{week[-1]}_weekly_reconciliation.json"
    assert dated["ContentType"] == "application/json"
    assert latest["Key"] == dr.LATEST_ARTIFACT_KEY
    assert latest["Body"] == dated["Body"], "the stable key and the dated archive must carry the same report"
    summary = json.loads(dated["Body"])
    whoop = next(r for r in summary["results"] if r["source"] == "whoop")
    assert whoop["gaps"] == 1
    assert whoop["missing_dates"] == [week[6]]
    assert summary["severity"] == "YELLOW — Monitor"


def test_handler_raises_when_the_artifact_cannot_be_delivered(handler_env):
    """#2835: the artifact IS the delivery now. A silent write failure would
    age into a stale 'not collected' line in next Monday's pack with no page —
    the handler must fail loudly so the terminal failure reaches the DLQ digest."""
    handler_env({}, s3_boom=True)
    with pytest.raises(RuntimeError, match="AccessDenied"):
        dr.lambda_handler({}, None)
