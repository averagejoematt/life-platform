"""tests/test_lab_findings_over_time.py — the Laboratory's findings over time (2026-11-11) and the method-stamp gate.

PRIVACY (owner rulings 2026-11-03/05/06; fail closed). The weekly correlation run names two METHOD-VERSIONED metrics:
the day grade (method 1 carries a journal component, ``scoring_engine.score_journal``; the public grade is
``health.day_grade_public``) and habit_pct (method 1 counted every habit, the Morning/Evening Journal habits among
them; the public share is ``health.habit_pct_public``). The live records for W42-W44 were computed before the public
methods and stamp no ``metric_methods``; /api/discoveries served their Day Grade and Habit Completion pairs, and the
Laboratory counted them in "listed N of M weeks". A pair naming either metric is now published only from a record
stamped with the public method — at the Site API (``activity_publication.public_correlations``), at the Lab's snapshot
producer (``publish_snapshot_lab.shape_findings``) and at render (``www/src/lib/laboratory.js findingIsPublic``, its
own test with a must-fail control in ``www/tests/lab_findings_over_time.test.mjs``).
"""

import json
import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "web"), os.path.join(_REPO, "scripts"), _REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import publish_snapshot_lab as LAB  # noqa: E402
from common import activity_publication as AP  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from health import day_grade_public, habit_pct_public  # noqa: E402

STAMPED = {"day_grade": day_grade_public.METHOD_VERSION, "habit_pct": habit_pct_public.METHOD_VERSION}


def _pair(a, b, r=0.5, p=0.001):
    return {"metric_a": a, "metric_b": b, "pearson_r": r, "n_days": 60, "n_eff": 40.0, "p_value": p, "fdr_significant": True}


CORRS = {
    "hrv_vs_recovery": _pair("hrv", "recovery_score", 0.7),
    "calories_vs_day_grade": _pair("calories", "day_grade", 0.43),
    "readiness_vs_day_grade": _pair("readiness", "day_grade", 0.57),
    "habit_pct_vs_recovery": _pair("habit_pct", "recovery_score", 0.44),
}


# ── the version tables agree ────────────────────────────────────────────────────────────────


def test_the_public_method_versions_are_one_table_in_three_places():
    assert AP.PUBLIC_METRIC_METHODS["day_grade"] == tuple(day_grade_public.METHOD_VERSIONS)
    assert AP.PUBLIC_METRIC_METHODS["habit_pct"] == (habit_pct_public.METHOD_VERSION,)
    js = open(os.path.join(_REPO, "www", "src", "lib", "laboratory.js")).read()
    m = re.search(r"export const PUBLIC_METHODS = (\{[^\n]+\});", js)
    assert m, "laboratory.js PUBLIC_METHODS not found"
    served = json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1)))
    assert {k: tuple(v) for k, v in served.items()} == AP.PUBLIC_METRIC_METHODS


# ── the Site API gate ───────────────────────────────────────────────────────────────────────


def test_an_unstamped_record_serves_no_day_grade_or_habit_pair():
    served = AP.public_correlations(CORRS)  # a pre-2026-11-05 record: no metric_methods
    assert set(served) == {"hrv_vs_recovery"}
    served = AP.public_correlations(CORRS, metric_methods={})
    assert set(served) == {"hrv_vs_recovery"}
    # a stamp that is not a public method version is not a stamp (fail closed)
    served = AP.public_correlations(CORRS, metric_methods={"day_grade": "method-1", "habit_pct": "habit-pct-v0"})
    assert set(served) == {"hrv_vs_recovery"}


def test_a_stamped_record_serves_them_the_control():
    """The must-fail control for the test above: the same pairs, stamped, ARE served — so the gate is the stamp."""
    served = AP.public_correlations(CORRS, metric_methods=STAMPED)
    assert set(served) == set(CORRS)
    served = AP.public_correlations(list(CORRS.values()), metric_methods={"day_grade": STAMPED["day_grade"]})
    assert sorted((p["metric_a"], p["metric_b"]) for p in served) == [
        ("calories", "day_grade"),
        ("hrv", "recovery_score"),
        ("readiness", "day_grade"),
    ]


def _record(week, metric_methods=None):
    rec = {
        "pk": "USER#matthew#SOURCE#weekly_correlations",
        "sk": f"WEEK#{week}",
        "week": week,
        "start_date": "2026-08-11",
        "end_date": "2026-11-08",
        "phase": "experiment",
        "correlations": json.loads(json.dumps(CORRS)),
    }
    if metric_methods is not None:
        rec["metric_methods"] = metric_methods
    return rec


class _RaisingS3:
    def get_object(self, **kwargs):
        raise RuntimeError("not needed")


class _FakeBoto3:
    def client(self, *a, **k):
        return _RaisingS3()


def _discoveries(rows):
    from web import site_api_ledger

    resp = site_api_ledger.discoveries(_g={"boto3": _FakeBoto3(), "table": FakeDdbTable(rows=rows)})
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


def test_discoveries_withholds_the_pre_method_weeks_and_stamps_the_rest():
    body = _discoveries([_record("2026-W44"), _record("2026-W45", STAMPED)])
    by_week: dict = {}
    for f in body["ai_findings"]:
        by_week.setdefault(f["week"], set()).add((f["metric_a"], f["metric_b"]))
    assert by_week["2026-W44"] == {("HRV", "Recovery")}
    assert ("readiness", "Day Grade") in by_week["2026-W45"] and ("Habit Completion", "Recovery") in by_week["2026-W45"]
    for f in body["ai_findings"]:
        if f["metric_b"] == "Day Grade":
            assert f["metric_methods"] == {"day_grade": STAMPED["day_grade"]}
        assert f["window_start"] == "2026-08-11" and f["window_end"] == "2026-11-08"


# ── the Laboratory's producer ───────────────────────────────────────────────────────────────


def _served(week, a, b, methods=None, r=0.5):
    f = {
        "week": week,
        "metric_a": a,
        "metric_b": b,
        "r": r,
        "n": 60,
        "n_eff": 40.0,
        "evidence": {"ci95": [0.2, 0.7], "fdr_significant": True},
    }
    if methods is not None:
        f["metric_methods"] = methods
    return f


def test_the_producer_excludes_an_unstamped_method_versioned_finding_and_tells_the_operator():
    excluded: list = []
    rows = [
        _served("2026-W44", "readiness", "Day Grade"),  # what /api/discoveries served before this fix
        _served("2026-W44", "Habit Completion", "Recovery"),
        _served("2026-W44", "Calories", "Day grade", {"day_grade": "method-1"}),  # relabelled + a non-public stamp
        _served("2026-W44", "HRV", "Recovery"),
        _served("2026-W45", "readiness", "Day Grade", {"day_grade": STAMPED["day_grade"]}),
    ]
    out = LAB.shape_findings({"ai_findings": rows}, excluded)
    assert [(f["week"], f["metric_a"], f["metric_b"]) for f in out] == [
        ("2026-W45", "readiness", "Day Grade"),
        ("2026-W44", "HRV", "Recovery"),
    ]
    assert out[0]["methods"] == {"day_grade": STAMPED["day_grade"]}
    assert len(excluded) == 3 and all(k == "finding" for k, _i, _w in excluded)
    assert "excluded" not in json.dumps(out)
    # the control: with every row stamped the same rows all pass, so the exclusion above is the stamp's doing
    stamped = [dict(r, metric_methods=dict(STAMPED)) for r in rows]
    assert len(LAB.shape_findings({"ai_findings": stamped}, [])) == len(rows)


def test_the_producer_fails_closed_without_the_policy_table():
    out = LAB.shape_findings({"ai_findings": [_served("2026-W45", "readiness", "Day Grade", dict(STAMPED))]}, [], public_methods={})
    assert out == []


def test_the_committed_fixture_carries_no_unstamped_method_versioned_finding():
    fx = json.load(open(os.path.join(_REPO, "www", "content", "fixtures", "lab.json")))
    for f in fx["lab_findings"]:
        assert LAB.finding_method_is_public(dict(f, metric_methods=f.get("methods"))), f["id"]
