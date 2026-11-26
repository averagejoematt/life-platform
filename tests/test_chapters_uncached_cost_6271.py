"""tests/test_chapters_uncached_cost_6271.py — the uncached cost of /api/chapters and /api/vitals_depth (#6271).

Measured 2026-11-25 (``route_metric``, live): an origin read of /api/chapters took ~6.3 s from 2026-11-23, when the
second editions went live (#6219), against ~80 ms before; /api/vitals_depth took ~11 s on every origin read. The
editions' serve-time gate re-read every coach partition three times per container refresh (the complete publication
snapshot, the private-call check, the withheld outputs), and the vitals arc read every whole Apple Health day since 2010
for one field. What this file holds — the change is speed only, never what is served:

  * the private-call set built from the snapshot's call rows is EQUAL to the one ``private_call_check.load`` builds by
    reading every partition itself, and the chapters route no longer reads a coach partition's calls a second time;
  * the snapshot's call rows are offered only while every coach partition has a fresh good read — a failed re-read
    falls back to the check's own read, so the check still fails closed exactly as before;
  * the withheld-output read returns the same rows, keyed in partition order, and still raises on any failed read;
  * the two pure text checks the edition gate runs are remembered per text and give the same findings;
  * the vitals reads project the date and the one field the resolver reads, and their fakes return only what is
    projected, so a field read but not projected would empty a panel here (tests/test_vitals_depth_421.py).

Synthetic rows only: invented coaches, claims and ids.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _k, _v in {"TABLE_NAME": "life-platform", "S3_BUCKET": "matthew-life-platform", "AWS_REGION": "us-west-2"}.items():
    os.environ.setdefault(_k, _v)
if os.path.join(ROOT, "lambdas") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from common import metric_truth, public_forecast_policy as FPOL  # noqa: E402
from content import chapter_editions as CE, private_call_check as P, story_checks  # noqa: E402
from web import narrative_publication as NPub, publication_snapshot as PS, withheld_outputs as WO  # noqa: E402

ALPHA, BETA, DOCKET = "COACH#alpha_coach", "COACH#beta_coach", PS.DOCKET_PK
NAMES = {"alpha_coach": ("Avery Quill", "Quill"), "beta_coach": ("Rowan Fenn", "Fenn")}
FILED = "2026-12-01T09:00:00+00:00"
PRIVATE_ID = "pred_20261201_synthetic_quiet_hours"
PRIVATE_CLAIM = "The subject will log nine quiet hours across the stated testing fortnight without a single break."
PUBLIC_CLAIM = "Daily walking counts will climb past a modest line by the end of the coming test week."
ASK_TEXT = "Rate your mood each morning before opening any screen, and send the rating along unedited."


def _rows():
    private_call = {
        "sk": f"PREDICTION#{PRIVATE_ID}",
        "prediction_id": PRIVATE_ID,
        "created_at": FILED,
        "cycle": "17",
        "filing": {"verdict": "observation"},
        "evaluation": {"metric": "sleep_duration_hours"},
        "claim_natural": PRIVATE_CLAIM,
    }
    public_call = {
        "sk": "PREDICTION#pred_20261201_synthetic_walking_line",
        "prediction_id": "pred_20261201_synthetic_walking_line",
        "created_at": FILED,
        "cycle": "17",
        "filing": {"verdict": "gradeable"},
        "evaluation": {"metric": "steps"},
        "claim_natural": PUBLIC_CLAIM,
    }
    ask = {"sk": "COMMITMENT#commit_20261201_synthetic_rating", "created_at": FILED, "commitment_natural": ASK_TEXT}
    learning = {"sk": "LEARNING#l_20261201_synthetic", "created_at": FILED, "text": "A synthetic learning the check never reads."}
    output = {"sk": "OUTPUT#2026-12-01#daily", "created_at": FILED, "content": "A synthetic daily read nobody approved for publication."}
    return [(ALPHA, private_call), (ALPHA, public_call), (ALPHA, learning), (ALPHA, output), (BETA, ask), (BETA, output)]


class _Table:
    """query(pk == x AND begins_with(sk, y)) over in-memory rows, one page; get_item by key; every query recorded."""

    def __init__(self, rows, fail_pk=None):
        self.rows, self.fail_pk, self.queries = rows, fail_pk, []

    def query(self, **kw):
        vals = [c._values for c in kw["KeyConditionExpression"]._values]
        pk, prefix = vals[0][1], vals[1][1]
        if pk == self.fail_pk:
            raise RuntimeError("throttled")
        self.queries.append((pk, prefix))
        return {"Items": [dict(r, pk=p) for p, r in self.rows if p == pk and str(r.get("sk", "")).startswith(prefix)]}

    def get_item(self, Key, **_kw):
        hit = [dict(r, pk=p) for p, r in self.rows if p == Key["pk"] and r.get("sk") == Key["sk"]]
        return {"Item": hit[0]} if hit else {}


@pytest.fixture
def snapshot(monkeypatch):
    """Two synthetic coach partitions and the docket; a fresh snapshot state, reset afterwards."""
    monkeypatch.setattr(PS, "partitions", lambda: (ALPHA, BETA, DOCKET))
    monkeypatch.setattr(P, "coach_names", lambda ids: {i: NAMES[i] for i in ids})
    PS.reset()
    NPub.begin_request()
    yield
    PS.reset()
    NPub.begin_request()


def _open(table):
    NPub.begin_request()
    PS.begin_request(table)
    PS.complete()


def test_the_call_set_from_the_snapshot_equals_the_check_reading_every_partition(snapshot):
    t = _Table(_rows())
    _open(t)
    got = PS.coach_call_rows()
    assert got is not None
    key, rows = got
    assert key == ((ALPHA, PS._PARTS[ALPHA]["version"]), (BETA, PS._PARTS[BETA]["version"]))
    assert all(r["sk"].startswith(PS.CALL_ROW_PREFIXES) for _pk, r in rows), "only calls and asks, never a learning or output"
    before = len(t.queries)
    fast = P.load(t, coach_rows=rows)
    assert t.queries[before:] == [(FPOL.FORECAST_PK, "PREDICTION#"), (FPOL.FORECAST_PK, "COMMITMENT#")], "only the forecast is read"
    full = P.load(t)
    assert fast == full
    assert len(fast.private) == 2  # the private call AND the private ask
    assert P.findings(PRIVATE_CLAIM, fast) == P.findings(PRIVATE_CLAIM, full) != []
    assert P.findings(PUBLIC_CLAIM, fast) == []


def test_the_prefixes_kept_are_the_checks_and_the_snapshot_already_reads_them():
    assert set(PS.CALL_ROW_PREFIXES) <= set(NPub.COUNTED_SK_PREFIXES)
    import inspect

    assert '("PREDICTION#", "COMMITMENT#")' in inspect.getsource(P.load), "the check's own prefixes changed: re-pin CALL_ROW_PREFIXES"


def test_no_call_rows_without_a_fresh_good_read_of_every_coach_partition(snapshot):
    t = _Table(_rows())
    PS.begin_request(None)
    assert PS.coach_call_rows() is None, "no snapshot request open"
    _open(t)
    assert PS.coach_call_rows() is not None
    for p in PS._PARTS.values():  # every partition past its TTL; the next request re-reads, and BETA's read fails
        p["at"] -= PS.TTL_S + 1
    t.fail_pk = BETA
    _open(t)
    assert BETA in PS._PARTS, "the taint keeps serving the last good read of BETA (stale) — unchanged by #6271"
    assert PS.coach_call_rows() is None, "the private-call check never builds from a stale partition: it reads for itself"
    with pytest.raises(RuntimeError):
        P.load(t)  # ... and that read fails closed, exactly as before


def test_the_chapters_route_builds_the_calls_from_the_snapshot_and_rebuilds_when_it_is_re_read(snapshot, monkeypatch):
    from web import site_api_chapters as chapters

    t = _Table(_rows())
    monkeypatch.setattr(chapters, "table", t)
    monkeypatch.setattr(chapters, "_CALLS_CACHE", {"at": None, "calls": None, "snap": None})
    _open(t)
    calls = chapters._private_calls()
    coach_reads = [q for q in t.queries if q[0] in (ALPHA, BETA) and q[1] in PS.CALL_ROW_PREFIXES]
    assert sorted(coach_reads) == sorted({(pk, pre) for pk in (ALPHA, BETA) for pre in PS.CALL_ROW_PREFIXES}), "each read ONCE"
    assert calls == P.load(t)
    n = len(t.queries)
    assert chapters._private_calls() is calls and len(t.queries) == n, "held while the snapshot is unchanged"
    for p in PS._PARTS.values():
        p["at"] -= PS.TTL_S + 1
    _open(t)
    assert chapters._private_calls() is not calls, "a re-read snapshot rebuilds the set"


def test_without_a_snapshot_the_route_reads_the_calls_itself_and_fails_closed(snapshot, monkeypatch):
    from web import site_api_chapters as chapters

    monkeypatch.setattr(chapters, "_CALLS_CACHE", {"at": None, "calls": None, "snap": None})
    PS.begin_request(None)
    seen = []
    monkeypatch.setattr(P, "load", lambda table: seen.append(table) or (_ for _ in ()).throw(RuntimeError("AccessDenied")))
    assert chapters._private_calls() is None and len(seen) == 1


def test_the_withheld_outputs_read_is_the_same_rows_in_partition_order_and_raises_on_a_failed_read(snapshot):
    t = _Table(_rows())
    got = WO.read(t)
    assert list(got) == [ALPHA, BETA], "the docket is not an output partition; the order is the partitions'"
    assert got == {pk: [dict(r, pk=pk) for p, r in _rows() if p == pk and r["sk"].startswith("OUTPUT#")] for pk in (ALPHA, BETA)}
    with pytest.raises(RuntimeError):
        WO.read(_Table(_rows(), fail_pk=BETA))


def test_the_edition_gates_pure_checks_are_remembered_and_unchanged():
    text = "After a previous cycle that stalled, he walked every day. The desk flagged nothing."
    direct = tuple(f"truth: {f}" for f in (*story_checks.staged_encounter_findings(text), *story_checks.reader_surface(text)))
    assert direct, "the fixture must carry a finding, or the comparison proves nothing"
    assert CE._truth_findings(text) == direct
    hits = CE._truth_findings.cache_info().hits
    assert CE._truth_findings(text) == direct and CE._truth_findings.cache_info().hits == hits + 1
    found = CE.gate_findings(text, tainted=lambda t: False, private_calls=CE.PRIVATE_CALLS_NOT_WIRED, filter_hits=lambda t: [])
    assert found == list(direct)
    assert P._runs(PRIVATE_CLAIM) == P._runs.__wrapped__(PRIVATE_CLAIM)


def test_the_vitals_reads_project_the_resolvers_fields(monkeypatch):
    from web import site_api_vitals_depth as vd

    asked = {}

    def q(source, start, end, include_pilot=False, projection=None):
        asked[source] = projection
        return []

    monkeypatch.setattr(vd, "_query_source", q)
    vd._vo2max_arc()
    vd._walking_hr()
    fields = metric_truth.metric_truth(metric_truth.VO2_MAX)["field_by_source"]
    assert {s: asked[s] for s in metric_truth.sources_for(metric_truth.VO2_MAX)} == {s: ("date", fields[s]) for s in fields}
    assert asked["strava"] == ("date", "activities")
