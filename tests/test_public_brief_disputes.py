"""tests/test_public_brief_disputes.py — brief-native disagreements (Coaching Room CR3 milestone, owner approval 2026-11-12).

Pins, offline (no AWS; Bedrock replaced by canned replies per coach):

  1. REGISTRY ORDER: a later coach is shown only the earlier coaches' current-cycle calls on metrics it also reads (the
     rendered claim, never their words); the first coach is shown none.
  2. THE OPPOSITION RULE: same metric, same kind, and opposite direction or the other side of the trailing-7-day mean.
     Must-fail controls: a dispute that AGREES with its target, sits on the mean, switches kind or metric, names an
     unknown call or cites nothing is dropped and nothing is written.
  3. EACH SIDE IS A GRADEABLE LEDGER CALL: the disputing side is filed through validate_filing (source public_brief, so
     dark like every brief call); no ENSEMBLE#docket row, no dispute_docket source.
  4. THE RECORD: PUBLIC_BRIEF#<cycle>#DISPUTE#<pair>#<metric> holds both prediction ids, both rendered claims, the cited
     observation ids, the frozen criterion and a provenance derived from both briefs; it is written once (conditional
     put) and a second write is refused.
  5. PRIVACY + PROVENANCE: a rationale with private-activity or relationship words is dropped; a target brief whose
     provenance is not publishable is never offered; a dispute row whose provenance is private is omitted when served;
     the route stays 404 while the switch is off.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("CONTENT_FILTER_JSON", json.dumps({"blocked_vices": [], "blocked_vice_keywords": ["fixtureblockedword"]}))

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import pytest  # noqa: E402
from coach import persona_registry, public_brief as PB, public_brief_disputes as DISP  # noqa: E402
from common import narrative_provenance as NP, prediction_publication as PP, public_brief_policy as POL  # noqa: E402
from test_public_brief import SERIES, Table, _series, good_draft, tolerance_for  # noqa: E402
from web import narrative_publication as NPUB, site_api_coach_brief as API  # noqa: E402

CYCLE = "2026-11-16"
FIRST, LATER = "nutrition_coach", "physical_coach"
PAIR = DISP.pair_key(FIRST, LATER)
DATA = dict(SERIES, steps=_series("2026-10-19", 28, 9000.0, 10.0))


def _personas():
    ps = persona_registry.personas()
    return {FIRST: ps[FIRST], LATER: ps[LATER]}  # registry order: nutrition before physical


def readings(metric, start, end):
    return [(d, v) for d, v in DATA.get(metric, []) if start <= d <= end]


def later_draft(**dispute):
    d = {
        "against": "x1",
        "kind": "direction",
        "direction": "up",
        "confidence": 0.6,
        "rationale": "Steps held steady, so the scale should drift back up.",
        "cites": ["o2"],
    }
    d.update(dispute)
    return {
        "interpretations": [{"text": "Daily steps held steady across the last 7 days.", "cites": ["o1"]}],
        "predictions": [],
        "recommendations": [],
        "position_changes": [],
        "disputes": [d],
    }


def _invoke(first, later):
    names = {c: p["name"] for c, p in _personas().items()}

    def invoke(body, model_name=None):
        invoke.calls.append(body)
        reply = later if names[LATER] in body["system"] else first
        return {"content": [{"type": "text", "text": json.dumps(reply)}], "usage": {"input_tokens": 900, "output_tokens": 300}}

    invoke.calls = []
    return invoke


def _run(table=None, later=None, first=None, persist=True):
    table = table if table is not None else Table()
    invoke = _invoke(first or good_draft(), later if later is not None else later_draft())
    out = PB.run(
        table,
        today=CYCLE,
        invoke=invoke,
        allow=lambda f: True,
        readings=readings,
        tolerance_for=tolerance_for,
        personas=_personas(),
        persist=persist,
    )
    return out, invoke, table


def _dispute_rows(table):
    return [r for (pk, sk), r in table.store.items() if POL.DISPUTE_TAG in sk]


# ── 1. registry order ───────────────────────────────────────────────────────────────────────
def test_the_later_coach_sees_only_the_earlier_calls_on_shared_metrics():
    _out, invoke, _t = _run()
    first_user, later_user = (c["messages"][0]["content"] for c in invoke.calls)
    assert "Other coaches' calls" not in first_user and '"disputes"' not in invoke.calls[0]["system"]
    assert "x1 |" in later_user and "Weight will fall over the next 28 days." in later_user
    assert "protein" not in later_user.lower()  # not a metric the later coach reads
    assert "below the 28-day mean" not in later_user  # the earlier coach's own words are never shown


# ── 2/3/4. a valid dispute ──────────────────────────────────────────────────────────────────
def test_an_opposing_call_is_filed_gradeable_and_recorded_with_both_sides():
    out, _invoke_, table = _run()
    assert out["results"][LATER]["disputes"] == 1 and out["results"][LATER]["status"] == "written"
    calls = {r["prediction_id"]: r for r in table.puts if r["sk"].startswith("PREDICTION#")}
    mine = next(r for r in calls.values() if r.get("dispute_ref"))
    theirs = calls[mine["dispute_ref"]["prediction_id"]]
    for c in (mine, theirs):
        assert c["source"] == POL.BRIEF_CALL_SOURCE and c["filing"]["verdict"] == "gradeable" and c["status"] == "pending"
        assert PP.classify_call(c["pk"], c) == (NP.PRIVATE, PP.PUBLIC_BRIEF_DARK)  # dark with every brief call
    assert mine["pk"] == f"COACH#{LATER}" and theirs["pk"] == f"COACH#{FIRST}"
    assert mine["claim_natural"] == "Weight will rise over the next 28 days."
    assert mine["evaluation"]["window_end"] == theirs["evaluation"]["window_end"]  # the same window
    (row,) = _dispute_rows(table)
    assert row["pk"] == f"COACH#{LATER}" and row["sk"] == POL.dispute_sk(CYCLE, PAIR, "weight_lbs")
    assert [s["prediction_id"] for s in row["sides"]] == [theirs["prediction_id"], mine["prediction_id"]]
    assert [s["claim"] for s in row["sides"]] == [theirs["claim_natural"], mine["claim_natural"]]
    assert row["sides"][0]["cited_observations"] == ["o1", "o3"] and row["sides"][1]["cited_observations"] == ["o2"]
    assert row["criterion"]["rule"] == DISP.OPPOSITE_DIRECTION
    assert not any(str(r["pk"]).startswith("ENSEMBLE#") for r in table.puts)  # not the docket, not its throttle
    assert all(r.get("source") != "dispute_docket" for r in calls.values())
    brief = table.store[(f"COACH#{LATER}", POL.brief_sk(CYCLE))]
    assert [p["id"] for p in brief["predictions"]] == ["d1"] and brief["predictions"][0]["against"]["coach_id"] == FIRST


def test_the_dispute_provenance_is_derived_from_both_briefs():
    _out, _i, table = _run()
    (row,) = _dispute_rows(table)
    first_brief = table.store[(f"COACH#{FIRST}", POL.brief_sk(CYCLE))]
    later_brief = table.store[(f"COACH#{LATER}", POL.brief_sk(CYCLE))]
    fams = set(row[NP.PROVENANCE_KEY]["families"])
    assert set(first_brief[NP.PROVENANCE_KEY]["families"]) <= fams and set(later_brief[NP.PROVENANCE_KEY]["families"]) <= fams
    assert row[NP.PROVENANCE_KEY]["producer"] == "coach.public_brief.dispute" and NP.is_publishable(row)


# ── 2. must-fail controls on the opposition rule ────────────────────────────────────────────
@pytest.mark.parametrize(
    "change",
    [
        {"direction": "down"},  # agrees with its target
        {"against": "x9"},  # an unknown call
        {"metric": "steps"},  # another metric
        {"kind": "level", "target": 200},  # switches kind
        {"cites": []},  # cites nothing
        {"confidence": 0.99},  # outside the confidence band
        {"rationale": "He skipped his journal, so the scale will climb."},  # private activity
        {"rationale": "Dinners with his partner will push the scale up."},  # a person
    ],
)
def test_a_dispute_that_fails_a_check_is_dropped_and_nothing_is_recorded(change):
    out, _i, table = _run(later=later_draft(**change))
    res = out["results"][LATER]
    assert res["disputes"] == 0 and res["dropped"]["disputes"] == 1
    assert _dispute_rows(table) == [] and not any(r.get("dispute_ref") for r in table.puts)


def test_level_calls_oppose_only_across_the_trailing_mean():
    theirs = {"metric": "weight_lbs", "kind": "level", "target": 188.0}
    assert DISP.opposition(theirs, {"metric": "weight_lbs", "kind": "level", "target": 190.0}, 189.0) == DISP.OTHER_SIDE_OF_MEAN
    assert DISP.opposition(theirs, {"metric": "weight_lbs", "kind": "level", "target": 187.0}, 189.0) is None  # same side
    assert DISP.opposition(theirs, {"metric": "weight_lbs", "kind": "level", "target": 189.0}, 189.0) is None  # on the mean
    assert DISP.opposition(theirs, {"metric": "weight_lbs", "kind": "level", "target": 190.0}, None) is None  # no mean
    assert DISP.opposition(theirs, {"metric": "hrv", "kind": "level", "target": 190.0}, 189.0) is None
    up = {"metric": "weight_lbs", "kind": "direction", "direction": "up"}
    assert DISP.opposition(up, {**up, "direction": "down"}, None) == DISP.OPPOSITE_DIRECTION
    assert DISP.opposition(up, up, None) is None


def test_a_level_dispute_across_the_mean_is_filed():
    first = good_draft()
    first["predictions"][0] = dict(first["predictions"][0], kind="level", target=180, direction=None)
    mean = PB.observe(["weight_lbs"], CYCLE, readings)[0]["last7"]["mean"]
    assert 180 < mean
    out, _i, table = _run(first=first, later=later_draft(kind="level", target=round(mean + 1), direction=None))
    assert out["results"][LATER]["disputes"] == 1
    (row,) = _dispute_rows(table)
    assert row["criterion"]["rule"] == DISP.OTHER_SIDE_OF_MEAN and float(row["criterion"]["trailing_7_day_mean"]) == mean
    out, _i, table = _run(first=first, later=later_draft(kind="level", target=170, direction=None))  # control: same side
    assert out["results"][LATER]["disputes"] == 0 and _dispute_rows(table) == []


# ── 4. frozen ───────────────────────────────────────────────────────────────────────────────
def test_the_frozen_criterion_is_never_rewritten():
    _out, _i, table = _run()
    (row,) = _dispute_rows(table)
    before = json.dumps(row, default=str, sort_keys=True)
    theirs = next(t for t in DISP.shared_calls(FIRST, PB._plain(table.store[(f"COACH#{FIRST}", POL.brief_sk(CYCLE))])))
    mine_row = next(r for r in table.puts if r.get("dispute_ref"))
    pred = {"metric": "weight_lbs", "kind": "level", "window_days": 28, "cites": ["o9"], "rule": DISP.OTHER_SIDE_OF_MEAN, "mean": 1.0}
    prov = row[NP.PROVENANCE_KEY]
    assert PB.write_disputes(table, LATER, CYCLE, [(("d1", pred, mine_row), theirs, prov)]) == 0  # the conditional put refuses
    assert json.dumps(_dispute_rows(table)[0], default=str, sort_keys=True) == before
    n = len(table.puts)
    out, invoke, _t = _run(table)  # a re-run of the cycle: both briefs exist; nothing is called or written
    assert {r["status"] for r in out["results"].values()} == {"exists"} and invoke.calls == [] and len(table.puts) == n


def test_a_rerun_of_the_later_coach_alone_still_sees_the_earlier_stored_calls():
    table = Table()
    _run(table, later={"interpretations": [{"text": "He felt slow.", "cites": ["o1"]}]})  # the later coach is held
    assert _dispute_rows(table) == []
    invoke = _invoke(good_draft(), later_draft())
    out = PB.run(
        table,
        today=CYCLE,
        coach_ids=[LATER],
        invoke=invoke,
        allow=lambda f: True,
        readings=readings,
        tolerance_for=tolerance_for,
        personas=_personas(),
    )
    assert out["results"][LATER]["disputes"] == 1 and len(_dispute_rows(table)) == 1


# ── 5. provenance + privacy ─────────────────────────────────────────────────────────────────
def test_a_target_brief_that_is_not_publishable_is_never_offered():
    brief = {
        "predictions": [{"id": "p1", "prediction_id": "x", "metric": "weight_lbs", "kind": "direction", "direction": "down"}],
        "evaluation_criteria": [{"prediction_id": "x", "evaluation_window_days": 28}],
    }
    assert DISP.shared_calls(FIRST, {**brief, NP.PROVENANCE_KEY: NP.stamp(["withings"], producer="t")})  # control
    assert DISP.shared_calls(FIRST, {**brief, NP.PROVENANCE_KEY: NP.stamp(["withings", "journal"], producer="t")}) == []
    assert DISP.shared_calls(FIRST, brief) == []  # no provenance at all


def test_the_dry_run_writes_no_dispute_and_reports_its_provenance():
    out, _i, table = _run(persist=False)
    res = out["results"][LATER]
    assert res["status"] == "dry_run" and res["disputes"] == 1 and table.puts == []
    assert res["checks"]["dispute_provenance_publishable"] == [True] and "_shared" not in res


def _served(table, coach=LATER):
    resp = API.handle_coach_brief({"queryStringParameters": {"coach": coach}}, table=NPUB.wrap(table), live=None, today=CYCLE)
    return resp, (json.loads(resp["body"]) if resp.get("body") else None)


def test_serving_stays_dark_and_shapes_the_disagreement_whole(monkeypatch):
    _out, _i, table = _run()
    resp, _b = _served(table)
    assert resp["statusCode"] == 404  # the switch is off: the route is dark
    monkeypatch.setattr(POL, "PUBLICATION_LIVE", True)
    _resp, body = _served(table)
    (d,) = body["briefs"][0]["disputes"]
    assert d["metric"] == "weight_lbs" and d["criterion"]["rule"] == DISP.OPPOSITE_DIRECTION
    assert [s["coach_id"] for s in d["sides"]] == [FIRST, LATER] and all(s["ledger"]["status"] == "pending" for s in d["sides"])
    (row,) = _dispute_rows(table)
    row[NP.PROVENANCE_KEY] = NP.stamp(["withings", "journal"], producer="t")  # a private dispute row is omitted
    _resp, body = _served(table)
    assert body["briefs"][0]["disputes"] == []


def test_evidence_and_brief_lookups_skip_dispute_rows():
    sk = POL.dispute_sk(CYCLE, PAIR, "weight_lbs")
    assert not POL.is_brief_sk(sk) and not POL.is_brief_sk(sk, CYCLE)
    assert POL.is_brief_sk(POL.brief_sk(CYCLE), CYCLE) and not POL.is_brief_sk(POL.evidence_sk(CYCLE, "r1"))


# ── the settled sample (scripts/public_brief_dispute_sample.py, read-only) ──────────────────
def _sample(table, **kw):
    sys.path.insert(0, os.path.join(_REPO, "scripts"))
    import public_brief_dispute_sample as S

    before = len(table.puts)
    rows = S.sample(table, [FIRST, LATER], **kw)
    assert len(table.puts) == before  # reads only
    return rows


def _grade(table, pid_coach, status, notes='{"algo_version": "x"}'):
    pid, coach = pid_coach
    row = table.store[(f"COACH#{coach}", f"PREDICTION#{pid}")]
    row.update(status=status, outcome=status, outcome_date="2026-12-15", outcome_notes=notes)


def test_a_dispute_is_sampled_only_once_both_sides_are_settled():
    _out, _i, table = _run()
    (row,) = _dispute_rows(table)
    sides = [(s["prediction_id"], s["coach_id"]) for s in row["sides"]]
    assert _sample(table) == []  # nothing settled: nothing is manufactured
    (pending,) = _sample(table, include_pending=True)
    assert pending["settled"] is False and [s["status"] for s in pending["sides"]] == ["pending", "pending"]
    _grade(table, sides[0], "confirmed")
    assert _sample(table) == []  # one side settled is not a settled dispute
    _grade(table, sides[1], "inconclusive", '{"grading_open": true}')  # provisional: still open
    assert _sample(table) == []
    _grade(table, sides[1], "refuted")
    (got,) = _sample(table)
    assert got["settled"] is True and got["metric"] == "weight_lbs" and got["criterion"]["rule"] == DISP.OPPOSITE_DIRECTION
    assert [s["claim"] for s in got["sides"]] == [s["claim"] for s in row["sides"]]
    assert [s["status"] for s in got["sides"]] == ["confirmed", "refuted"]
    for s in got["sides"]:  # the frozen test of each side, as filed
        assert s["frozen_evaluation"]["metric"] == "weight_lbs" and s["frozen_evaluation"]["window_end"]
        assert s["filing"]["verdict"] == "gradeable"
    assert _sample(table, cycle="2026-11-23") == [] and len(_sample(table, cycle=CYCLE)) == 1


def test_a_brief_or_evidence_row_is_never_a_sampled_dispute():
    assert DISP.is_dispute_sk(POL.dispute_sk(CYCLE, PAIR, "weight_lbs"))
    assert not DISP.is_dispute_sk(POL.brief_sk(CYCLE)) and not DISP.is_dispute_sk(POL.evidence_sk(CYCLE, "r1"))
