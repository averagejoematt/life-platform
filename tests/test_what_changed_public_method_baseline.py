"""A day_grade / habit_pct pair is "newly unlocked" only against earlier PUBLIC-METHOD weeks (follow-up to #5847).

The W42-W44 weekly_correlations records predate the public day grade (method 1 carries a journal component) and the
public habit share (it counted the journal habits); they stamp no ``metric_methods``. The what_changed first-seen
ledger was written from them, so live /api/what_changed listed calories -> day_grade as "newly unlocked" in W45 — a
comparison against private-method computations. ``activity_publication.public_newly_unlocked`` re-derives the claim
from public-method records only; both public readers (/api/what_changed and the between-chronicle mail) use it.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

from common import activity_publication as AP  # noqa: E402

STAMP = {"day_grade": AP.PUBLIC_METRIC_METHODS["day_grade"][0], "habit_pct": AP.PUBLIC_METRIC_METHODS["habit_pct"][0]}
WINDOW_END = "2026-11-08"


def _pair(a, b, sig):
    return {"metric_a": a, "metric_b": b, "pearson_r": 0.41, "n_days": 60, "p_value": 0.0001 if sig else 0.6}


def _rec(week, end, pairs, stamped):
    rec = {"pk": "USER#matthew#SOURCE#weekly_correlations", "sk": f"WEEK#{week}", "week": week, "end_date": end}
    rec["correlations"] = {f"{p['metric_a']}_vs_{p['metric_b']}": p for p in pairs}
    if stamped:
        rec["metric_methods"] = dict(STAMP)
    return rec


def _unlock(a, b, first_seen):
    return {"label": f"{a}_vs_{b}", "metric_a": a, "metric_b": b, "r": 0.41, "n": 60, "first_seen": first_seen}


CAL_DG = ("calories", "day_grade")
STEPS_HRV = ("steps", "hrv")

# The live shape: day_grade first significant on an UNSTAMPED (method-1) week, then on the first stamped week.
LIVE_RECORDS = [
    _rec("2026-W42", "2026-10-18", [_pair(*CAL_DG, False)], stamped=False),
    _rec("2026-W43", "2026-10-25", [_pair(*CAL_DG, True)], stamped=False),
    _rec("2026-W44", "2026-11-01", [_pair(*CAL_DG, True)], stamped=False),
    _rec("2026-W45", WINDOW_END, [_pair(*CAL_DG, True), _pair(*STEPS_HRV, True)], stamped=True),
]


def test_pre_method_record_cannot_create_a_newly_unlocked_claim():
    unlocked = [_unlock(*CAL_DG, "2026-10-25"), _unlock(*STEPS_HRV, "2026-11-01")]
    out = AP.public_newly_unlocked(unlocked, LIVE_RECORDS, WINDOW_END)
    assert [(u["metric_a"], u["metric_b"]) for u in out] == [STEPS_HRV]  # a non-versioned pair is untouched


def test_control_the_old_projection_published_the_claim():
    # Must-fail control: the pre-fix reader (private-METRIC filter only) kept this pair, so the fixture reproduces the leak.
    unlocked = [_unlock(*CAL_DG, "2026-10-25")]
    assert [u for u in unlocked if AP.correlation_pair_is_public(u)] == unlocked


def test_control_a_public_method_baseline_does_admit_the_claim():
    # Must-fail control for the gate itself: with an earlier PUBLIC-method week where the pair was not significant,
    # the claim is real and is served — dated from the public record, never from the ledger's pre-method date.
    records = LIVE_RECORDS[:3] + [
        _rec("2026-W45", "2026-11-08", [_pair(*CAL_DG, False)], stamped=True),
        _rec("2026-W46", "2026-11-15", [_pair(*CAL_DG, True)], stamped=True),
    ]
    out = AP.public_newly_unlocked([_unlock(*CAL_DG, "2026-10-25")], records, "2026-11-15")
    assert len(out) == 1 and out[0]["first_seen"] == "2026-11-15"


def test_first_public_method_week_has_no_baseline():
    # Significant from the very first stamped week: nothing public to be "new" against -> omitted.
    records = [_rec("2026-W45", WINDOW_END, [_pair(*CAL_DG, True)], stamped=True)]
    assert AP.public_newly_unlocked([_unlock(*CAL_DG, WINDOW_END)], records, WINDOW_END) == []


def test_significant_only_on_pre_method_records_is_omitted():
    records = LIVE_RECORDS[:3] + [_rec("2026-W45", WINDOW_END, [_pair(*CAL_DG, False)], stamped=True)]
    assert AP.public_newly_unlocked([_unlock(*CAL_DG, "2026-10-25")], records, WINDOW_END) == []


def test_public_unlock_before_the_window_is_not_new():
    records = [
        _rec("2026-W38", "2026-09-20", [_pair("habit_pct", "hrv", False)], stamped=True),
        _rec("2026-W39", "2026-09-27", [_pair("habit_pct", "hrv", True)], stamped=True),
        _rec("2026-W45", WINDOW_END, [_pair("habit_pct", "hrv", True)], stamped=True),
    ]
    assert AP.public_newly_unlocked([_unlock("habit_pct", "hrv", "2026-10-20")], records, WINDOW_END) == []


def test_no_records_withholds_versioned_pairs():
    unlocked = [_unlock(*CAL_DG, "2026-10-25"), _unlock(*STEPS_HRV, "2026-11-01")]
    assert [u["metric_a"] for u in AP.public_newly_unlocked(unlocked, [], WINDOW_END)] == ["steps"]


class _Table:
    def __init__(self, snapshot, records, fail=False):
        self.snapshot, self.records, self.fail, self.queries = snapshot, records, fail, 0

    def get_item(self, Key=None, **kw):
        return {"Item": self.snapshot} if "what_changed" in Key["pk"] else {}

    def query(self, **kw):
        self.queries += 1
        if self.fail:
            raise RuntimeError("throttled")
        return {"Items": list(self.records)}


def _snapshot():
    return {
        "pk": "USER#matthew#SOURCE#what_changed",
        "sk": "SNAPSHOT#current",
        "week": "2026-W45",
        "window_start": "2026-10-10",
        "window_end": WINDOW_END,
        "deltas": [],
        "newly_unlocked": [_unlock(*CAL_DG, "2026-10-25"), _unlock(*STEPS_HRV, "2026-11-01")],
        "honest_null": False,
    }


def test_served_what_changed_drops_the_pre_method_claim():
    from web import site_api_ledger

    body = json.loads(site_api_ledger.what_changed(_g={"table": _Table(_snapshot(), LIVE_RECORDS)})["body"])
    assert [(u["metric_a"], u["metric_b"]) for u in body["newly_unlocked"]] == [STEPS_HRV]


def test_served_what_changed_fails_closed_on_a_read_error():
    from web import site_api_ledger

    table = _Table(_snapshot(), LIVE_RECORDS, fail=True)
    body = json.loads(site_api_ledger.what_changed(_g={"table": table})["body"])
    assert table.queries == 1 and [u["metric_a"] for u in body["newly_unlocked"]] == ["steps"]


def test_no_versioned_pair_reads_no_records():
    snap = dict(_snapshot(), newly_unlocked=[_unlock(*STEPS_HRV, "2026-11-01")])
    table = _Table(snap, LIVE_RECORDS)
    from web import site_api_ledger

    site_api_ledger.what_changed(_g={"table": table})
    assert table.queries == 0


def test_between_chronicle_mail_uses_the_same_projection(monkeypatch):
    import between_chronicle_lambda as bc

    monkeypatch.setattr(bc, "table", _Table(_snapshot(), LIVE_RECORDS))
    digest = bc.gather_digest()
    assert [(u["metric_a"], u["metric_b"]) for u in digest["unlocked"]] == [STEPS_HRV]
