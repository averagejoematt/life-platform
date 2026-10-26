"""tests/test_strava_readers_one_count_5398.py — six more readers count one gym visit once (#5398).

#5387 moved fifteen readers onto THE session count (`training.session_count`). Its AST guard then found six
more that still counted or summed Strava activities directly — the AI training analyst, the dashboard / clinical /
buddy writers, the chronicle's signal data, the weekly correlation engine's `training_mins`, the hydration view's
exercise minutes and the periodization view's weekly sessions. On a gym day the Strava partition holds Hevy's own
push of the WHOLE session and the watch's ride inside it, so each read ONE visit as two sessions and 220 minutes.

THE FIXTURE is #5369's shared one (the 2026-10-25 wire's structure, synthetic numbers), run on both wires exactly as
the #5387 Set test runs it (`tests/test_strava_session_count_set_5387.py`): 1 visit, 160 minutes; before, 2 / 220.

ONE assertion reports every offender (member x wire). The mutation controls:
  * `test_the_old_readings_would_fail_every_probe` swaps `session_count` for the retired direct count (one visit per
    Strava activity, the minutes summed) and asserts EVERY probe then differs from its expectation — so the
    expectation is not vacuous and a revert of any member is red;
  * the correlation series keeps its old definition BEFORE the dated cut-over (ADR-105) and takes THE count's minutes
    from it; moving the constant changes the series, and the stored record carries the amendment.
"""

from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "emails"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _k, _v in {
    "AWS_REGION": "us-west-2",
    "AWS_DEFAULT_REGION": "us-west-2",
    "S3_BUCKET": "matthew-life-platform",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "EMAIL_RECIPIENT": "test@example.com",
    "EMAIL_SENDER": "noreply@example.com",
    "CHRONICLE_SENDER": "noreply@example.com",
}.items():
    os.environ.setdefault(_k, _v)

import test_strava_session_count_set_5387 as set5387  # noqa: E402 — the #5387 Set test's fixture helpers
from common.strava_read_seam import strava_read_seam  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from pacific_clock import freeze_pacific  # noqa: E402
from training import session_count  # noqa: E402

DAY = set5387.DAY  # 2026-10-25
VISIT_MIN = set5387.VISIT_MIN  # 160.0
WIRES = set5387.WIRES
strava_row = set5387.strava_row
hevy_row = set5387.hevy_row


def seamed_row(wire: str) -> dict:
    """The Strava day row as every reader sees it: through the read seam (#4419), which folds the WHOOP lift
    pieces into Hevy's push — 2 activities / 220 minutes, the day totals' reading."""
    return strava_read_seam("strava", [strava_row(wire)])[0]


def _rows_by_source(wire: str) -> dict:
    return {"strava": [seamed_row(wire)], "hevy": [hevy_row()]}


def _query_source(wire: str):
    rows = _rows_by_source(wire)

    def query(source, start, end, *a, **k):
        return [copy.deepcopy(r) for r in rows.get(source, []) if start <= r["date"] <= end]

    return query


# ── one probe per member: what it serves for the gym day, read from its own output ────────────────────


class _FrozenAnalyzer(datetime):
    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 10, 26, 19, 0, 0)
        return base.replace(tzinfo=tz) if tz else base


def probe_ai_expert_analyzer(wire, monkeypatch):
    from intelligence import ai_expert_analyzer_lambda as az

    monkeypatch.setattr(az, "datetime", _FrozenAnalyzer)
    freeze_pacific(monkeypatch, az, _FrozenAnalyzer)
    monkeypatch.setattr(az, "table", FakeDdbTable(query_hook=lambda t, **kw: {"Items": []}, get_item_hook=lambda t, key, **kw: {}))
    monkeypatch.setattr(az, "_query_source", _query_source(wire))
    out = az.gather_data_for_expert("training")
    return {
        "hevy_sessions": out["hevy_sessions"],
        "outside_gym_sessions": out["strava_sessions"],
        "total_active_min": out["total_active_min"],
        "modalities": out["modality_breakdown"],
    }


class _FrozenWriters(datetime):
    """Sunday 2026-10-25 20:00 PT — the fixture's gym day is 'today', inside the week and the 28-day window."""

    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 10, 26, 3, 0, 0, tzinfo=timezone.utc)
        return base if tz is not None else base.replace(tzinfo=None)


def _writers(wire, monkeypatch):
    import test_output_writers as tow
    from content import output_writers as ow

    monkeypatch.setattr(ow, "datetime", _FrozenWriters)
    # buddy's friendly timestamp reads a live Pacific clock
    from common import pacific_time

    monkeypatch.setattr(pacific_time, "pacific_now", lambda: datetime(2026, 10, 25, 20, 0, 0))
    ranges = tow.FakeRanges(_rows_by_source(wire))
    s3, _, _ = tow._init(fetch_range=ranges)
    return ow, tow, s3


def probe_output_writers(wire, monkeypatch):
    ow, tow, s3 = _writers(wire, monkeypatch)
    dash = tow._write_dashboard(s3)
    ow.write_clinical_json({"tsb": 1.0, "whoop": {}, "journal": []}, tow.PROFILE, "2026-10-25")
    activity = s3.written(tow._CLINICAL_KEY)["activity"]
    ow.write_buddy_json({}, tow.PROFILE, "2026-10-25")
    exercise = next(line["text"] for line in s3.written(tow._BUDDY_KEY)["status_lines"] if line["area"] == "Exercise")
    return {
        "dashboard_zone2_min": dash["zone2_min"],
        "clinical_sessions_per_week": activity["avg_sessions_week"],
        "clinical_zone2_per_week": activity["avg_zone2_min"],
        "buddy_exercise_line": exercise,
    }


def probe_chronicle_render(wire, monkeypatch):
    from emails import chronicle_render as cr

    row = seamed_row(wire)
    day_row = cr.build_weekly_signal_data({"strava": row, "hevy": [hevy_row()]}, 5)["training_sessions"]
    by_date = cr.build_weekly_signal_data({"strava": {DAY: row}, "hevy": [hevy_row()]}, 5)["training_sessions"]
    no_hevy = cr.build_weekly_signal_data({"strava": {DAY: row}}, 5)["training_sessions"]
    return {"day_row": day_row, "by_date": by_date, "without_hevy_rows": no_hevy}


def _correlation_series(wire, monkeypatch, cutover=None):
    import weekly_correlation_compute_lambda as wc
    from compute import training_mins_series as tms

    rows = _rows_by_source(wire)
    monkeypatch.setattr(wc, "fetch_range", lambda source, start, end: copy.deepcopy(rows.get(source, [])))
    if cutover:
        monkeypatch.setattr(tms, "TRAINING_MINS_CUTOVER_DATE", cutover)
    return wc.assemble_daily_series(DAY, DAY)[DAY]["training_mins"]


def probe_weekly_correlation(wire, monkeypatch):
    # the cut-over moved onto the fixture's own day: that day's `training_mins` is THE count's minutes
    return {"training_mins": _correlation_series(wire, monkeypatch, cutover=DAY)}


def probe_tools_health(wire, monkeypatch):
    from mcp import tools_health as th

    water = {"date": DAY, "sk": f"DATE#{DAY}", "water_intake_ml": 3000}
    rows = {"apple_health": [water], "withings": [], **_rows_by_source(wire)}
    monkeypatch.setattr(th, "query_source", lambda source, start, end, **k: copy.deepcopy(rows.get(source, [])))
    out = th._get_hydration_score({"start_date": DAY, "end_date": DAY, "target_ml": 2500})
    return {"exercise_min": out["daily_breakdown"][0]["exercise_min"]}


def probe_tools_training(wire, monkeypatch):
    from mcp import tools_training as tt

    rows = _rows_by_source(wire)
    monkeypatch.setattr(tt, "query_source", lambda source, start, end, **k: copy.deepcopy(rows.get(source, [])))
    monkeypatch.setattr(tt, "get_profile", lambda: {"max_heart_rate": 184})
    out = tt._get_training_periodization({"start_date": DAY, "end_date": DAY})
    (week,) = out["weekly_breakdown"]
    return {
        "sessions": week["sessions"],
        "total_minutes": week["total_minutes"],
        "cardio_minutes": week["cardio_minutes"],
        "strength_minutes": week["strength_minutes"],
        "cardio_sessions": week["cardio_sessions"],
        "strength_sessions": week["strength_sessions"],
    }


def _zone2(wire, *, with_hevy):
    return set5387.the_zone2(wire, with_hevy=with_hevy)


#: member -> (probe, the expected reading on a wire). One visit, 160 minutes; Zone 2 is THE computation's number.
MEMBERS: dict[str, tuple] = {
    "lambdas/intelligence/ai_expert_analyzer_lambda.py": (
        probe_ai_expert_analyzer,
        lambda w: {
            "hevy_sessions": 1,
            "outside_gym_sessions": 0,  # the gym visit is one session, not an extra Strava one
            "total_active_min": VISIT_MIN,
            "modalities": {"strength": 1, "Ride": 1, "Mobility": 1},
        },
    ),
    "lambdas/content/output_writers.py": (
        probe_output_writers,
        lambda w: {
            "dashboard_zone2_min": round(_zone2(w, with_hevy=True)),
            "clinical_sessions_per_week": 0.2,  # 1 visit / 4 weeks (was 2 / 4 = 0.5)
            "clinical_zone2_per_week": round(_zone2(w, with_hevy=True) / 4),
            "buddy_exercise_line": "1 session so far this week",
        },
    ),
    "lambdas/emails/chronicle_render.py": (
        probe_chronicle_render,
        lambda w: {"day_row": 1, "by_date": 1, "without_hevy_rows": 1},
    ),
    "lambdas/compute/weekly_correlation_compute_lambda.py": (probe_weekly_correlation, lambda w: {"training_mins": VISIT_MIN}),
    "mcp/tools_health.py": (probe_tools_health, lambda w: {"exercise_min": VISIT_MIN}),
    "mcp/tools_training.py": (
        probe_tools_training,
        lambda w: {
            "sessions": 1,
            "total_minutes": VISIT_MIN,
            "cardio_minutes": 60.0,
            "strength_minutes": VISIT_MIN - 60.0 - 18.0,
            "cardio_sessions": 1,
            "strength_sessions": 1,
        },
    ),
}


def _no_aws(*_a, **_k):
    raise AssertionError("a probe reached AWS — every read here is a fixture")


def _run_all(monkeypatch, mutate=None) -> list[str]:
    import botocore.client

    offenders = []
    for member, (probe, expected) in MEMBERS.items():
        for wire in WIRES:
            want = expected(wire)
            monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", _no_aws)
            if mutate:
                mutate(monkeypatch)  # re-applied per probe: each probe ends with monkeypatch.undo()
            try:
                got = probe(wire, monkeypatch)
            except Exception as e:  # noqa: BLE001 — a member that cannot read the wire is an offender too
                got = {"error": f"{type(e).__name__}: {e}"}
            if got != want:
                offenders.append(f"{member} [{wire}]: served {got}, expected {want}")
            monkeypatch.undo()
    return offenders


def test_the_set_is_the_issues_six():
    assert len(MEMBERS) == 6


def test_every_member_counts_one_gym_visit_once_on_both_wires(monkeypatch):
    """One visit, 160 minutes, THE Zone 2 — never 2 visits / 220 minutes / an average-HR Zone 2. Every
    offender (member x wire) in one report. No probe may reach AWS (botocore is stubbed to raise)."""
    offenders = _run_all(monkeypatch)
    assert not offenders, "a Strava-activity counter counts one gym visit wrong (#5398):\n  " + "\n  ".join(offenders)


def _direct_count(*, strava=None, hevy=None, whoop=None, apple=None, start_date=None, end_date=None):
    """The RETIRED reading: one session per Strava activity, the activities' minutes summed."""
    acts = [a for row in (strava or ()) for a in (row.get("activities") or ())]
    mins = round(sum(float(a.get("moving_time_seconds") or 0) for a in acts) / 60.0, 1)
    by_sport: dict = {}
    for a in acts:
        by_sport.setdefault(a.get("sport_type") or "Unknown", {"parts": 0, "minutes": 0.0})["parts"] += 1
    return {"sessions": len(acts), "parts": len(acts), "minutes": mins, "by_sport": by_sport, "by_family": {}, "by_date": {}}


def _direct_visits(*, strava=None, hevy=None, whoop=None, apple=None):
    out = []
    for row in strava or ():
        for a in row.get("activities") or ():
            secs = float(a.get("moving_time_seconds") or 0)
            part = {
                "family": "strength" if a.get("sport_type") == "WeightTraining" else "cycling",
                "sport": a.get("sport_type"),
                "seconds": secs,
                "minutes": secs / 60.0,
                "activities": [a],
            }
            out.append({"date": row.get("date"), "seconds": secs, "minutes": secs / 60.0, "parts": [part], "hevy_sessions": []})
    return out


def test_the_old_readings_would_fail_every_probe(monkeypatch):
    """Mutation control: with `session_count` replaced by the retired direct count (one visit per Strava activity,
    minutes summed), EVERY member's reading differs from its expectation on at least one wire — so the expectations
    above are not vacuous and a revert of any member to a direct count is red."""

    def retired(mp):
        mp.setattr(session_count, "count", _direct_count)
        mp.setattr(session_count, "visits", _direct_visits)
        mp.setattr(session_count, "zone2_total", lambda *a, **k: 0.0)

    offenders = _run_all(monkeypatch, retired)
    names = {o.split(" [")[0] for o in offenders}
    assert names == set(MEMBERS), f"a probe survived the retired reading: {sorted(set(MEMBERS) - names)}"


def test_the_fixture_is_what_the_issue_says():
    """The shared fixture's direct reading is 2 sessions / 220 minutes (the bug), THE count's is 1 / 160."""
    for wire in WIRES:
        row = seamed_row(wire)
        direct = _direct_count(strava=[row])
        assert (direct["sessions"], direct["minutes"]) == (2, 220.0), wire
        counted = session_count.count(strava=[row], hevy=[hevy_row()])
        assert (counted["sessions"], counted["minutes"]) == (1, VISIT_MIN), wire


# ── the correlation series: a dated cut-over, never a silent redefinition (ADR-105) ─────────────────────


def test_training_mins_keeps_its_old_definition_before_the_cut_over(monkeypatch):
    """A day BEFORE `TRAINING_MINS_CUTOVER_DATE` is the series the stored correlations were computed on (the summed
    Strava rows, 220 here): the engine never re-derives the old days under the new rule."""
    from compute import training_mins_series as tms

    assert DAY < tms.TRAINING_MINS_CUTOVER_DATE, "the fixture day is before the real cut-over"
    for wire in WIRES:
        assert _correlation_series(wire, monkeypatch) == 220.0, wire


def test_training_mins_reads_the_one_count_from_the_cut_over(monkeypatch):
    from compute import training_mins_series as tms

    for wire in WIRES:
        assert _correlation_series(wire, monkeypatch, cutover=DAY) == VISIT_MIN, wire
        monkeypatch.undo()
    # the day before the (moved) cut-over keeps the old reading; the cut-over day itself takes THE count
    monkeypatch.setattr(tms, "TRAINING_MINS_CUTOVER_DATE", "2026-10-26")
    assert _correlation_series("post", monkeypatch) == 220.0


def test_an_absent_strava_day_is_unmeasured_not_zero(monkeypatch):
    """ADR-104: no Strava row -> None on either side of the cut-over (a Hevy-only day is not a measured 0)."""
    from compute import training_mins_series as tms

    assert tms.training_mins("2026-10-20", None, {}) is None
    assert tms.training_mins("2026-11-20", None, {"2026-11-20": 30.0}) is None
    assert tms.training_mins("2026-11-20", {"activities": [{"moving_time_seconds": 600}]}, {}) == 0.0  # a measured row, no visit minutes


def test_the_stored_record_carries_the_amendment(monkeypatch):
    import weekly_correlation_compute_lambda as wc
    from compute import training_mins_series as tms

    class Table:
        def __init__(self):
            self.puts = []

        def put_item(self, Item):  # noqa: N803 — boto3's kwarg name
            self.puts.append(Item)

    t = Table()
    monkeypatch.setattr(wc, "table", t)
    wc.store_correlations("2026-W44", {}, "2026-08-01", "2026-10-30", "2026-11-01T00:00:00+00:00")
    (item,) = t.puts
    (amend,) = item["series_amendments"]
    assert amend["effective_from"] == tms.TRAINING_MINS_CUTOVER_DATE and amend["metrics"] == ["training_mins"]
    assert amend["pairs"] == ["training_mins_vs_recovery"] and amend["issue"] == "#5398"
    assert "changed definition" in amend["change"]


def test_the_cut_over_is_a_valid_pacific_day_after_the_fixture():
    from datetime import date

    from compute import training_mins_series as tms

    assert date.fromisoformat(tms.TRAINING_MINS_CUTOVER_DATE) > date.fromisoformat(DAY)


# ── no new IAM: every Hevy read here rides a grant the reader's role already holds ───────────────────────


def test_no_new_grant_is_needed_the_hevy_reads_are_table_level():
    """IAM read grants are table-level (`_compute_base` / the MCP role), not per-partition: the weekly correlation
    role already reads the Hevy partition in `_compute_centenarian_progress`, and the writers fetch through the
    brief's own `fetch_range`. This pins that the lambda already names the partition, so the new read adds no grant."""
    path_ = os.path.join(_REPO, "lambdas", "compute", "weekly_correlation_compute_lambda.py")
    with open(path_, encoding="utf-8") as fh:
        text = fh.read()
    assert text.count('fetch_range("hevy"') >= 2  # the centenarian read (pre-existing) and the session-count read
    with open(os.path.join(_REPO, "cdk", "stacks", "role_policies_compute.py"), encoding="utf-8") as fh:
        policy = fh.read()
    assert "LeadingKeys" not in policy.split("def compute_weekly_correlations")[1].split("def compute_dashboard_refresh")[0]
