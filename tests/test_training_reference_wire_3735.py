#!/usr/bin/env python3
"""tests/test_training_reference_wire_3735.py — the reference record must carry what the
reference computes (#3735).

`build_reference` returns eight keys. `build_training_reference_record` — the function
that turns that dict into the DynamoDB item — copied six, and the two it dropped were
`reference_schema` and `proven_bands`: the exact pair #3710 added so a consumer could
tell a STALE v1 record from a v2 one that genuinely found no comparable period.

The comment #3710 wrote above those two fields says why they matter:

    consumers MUST be able to tell a v1 record (no proven table, no per-band n) from a
    v2 record that genuinely found no comparable period. Without this the prescription
    view reports "nothing to prescribe from" for a stale reference, which reads as a
    finding about his history when it is a deploy problem.

The writer one function below dropped them, so the failure the comment describes
happened anyway — in the more confusing direction. Measured live on 2026-09-13, minutes
after #3713 deployed:

    episode-detect re-run 04:33:10Z -> DATE#2026-09-13 written with attrs
      {bands, confidence, derived_at, n_episodes_with_covariates, pk, proven_curve,
       sk, source_window}
    get_benchmark view=prescription  ->  "training_reference is v1 (no proven_bands, no
      per-band n). This is a STALE REFERENCE ... episode-detect needs redeploying and
      re-running."

It had just been redeployed and re-run. The message could never clear, because the
writer could not produce what the reader was looking for. Every `prescription` and
`campaign` answer — #3709, #3710, #3711, the top of the backlog — was inert from the
moment it shipped, and reported its own inertness as an operations problem.

THE GUARD IS DERIVED, NOT A RESTATED LIST. `test_every_computed_field_survives_the_write`
calls the real `build_reference` on a synthetic history and asserts that every key it
returns reaches the item. A ninth field added to the reference later is covered without
anyone remembering to add it here — which is the whole failure mode.

Offline, stdlib-only: no DynamoDB, no clock reads beyond the module's own.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

from compute import episode_detect_lambda as ed  # noqa: E402

# Keys that are deliberately NOT columns of their own on the item. `sk` is derived from
# `derived_at`; anything else added here needs a stated reason, because "it does not need
# to be stored" is exactly what was silently true of the two fields this issue is about.
NOT_STORED = {}


def _history(days: int = 900):
    """A descending weight series long enough for episode detection to find a loss
    episode, plus the per-activity rows the reference buckets by band.

    Shapes match `_load_inputs`'s output exactly — `weigh_ins` is (date_str, lb) tuples
    and an activity is {date, kind, hours, miles, hr} — because a fixture that is not
    the wire proves nothing about the wire.
    """
    start = date(2024, 1, 1)
    weigh_ins, activities = [], []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        weigh_ins.append((d, max(240.0, 330.0 - i * 0.08)))
        activities.append({"date": d, "kind": "walk", "hours": 0.75, "miles": 3.0, "hr": 112.0})
    return weigh_ins, activities


def _reference():
    weigh_ins, activities = _history()
    idx, vals = ed.smooth_weight(weigh_ins)
    assert idx, "the fixture history is too short to smooth — fix the fixture, not the test"
    episodes = ed.enrich_episodes(idx, vals, ed.detect_episodes(idx, vals), activities, {})
    return ed.build_reference(idx, vals, episodes, activities, {}, {}, {})


def test_every_computed_field_survives_the_write():
    """THE CONTRACT. Derived from `build_reference`'s own return value, so it cannot go
    stale the way a restated key list would.

    MUTATION PROOF: delete `"reference_schema"` or `"proven_bands"` from
    `build_training_reference_record`'s item dict and this names the missing key.
    """
    ref = _reference()
    item = ed.build_training_reference_record(ref)
    missing = sorted(k for k in ref if k not in item and k not in NOT_STORED)
    assert not missing, (
        "build_reference computes these and build_training_reference_record does not store them, "
        f"so no reader can ever see them: {missing}"
    )


def test_the_schema_marker_is_stored_and_is_v3():
    """The specific field whose absence made the prescription view permanently wrong.
    Asserted as a VALUE, not just presence — a stored `reference_schema: 1` would read
    as an honest stale record and be just as wrong. #4427 moved it 2 -> 3: a schema-2
    record is the twin-counted table (history, superseded)."""
    item = ed.build_training_reference_record(_reference())
    assert "reference_schema" in item, "the v1/v2/v3 discriminator is not on the record at all"
    assert int(item["reference_schema"]) == 3, f"stored schema is {item['reference_schema']}, expected 3"


def test_the_proven_table_is_stored():
    """`proven_bands` is the other half: `reference_schema: 2` with no proven table is a
    record that claims to be v2 and cannot answer a v2 question."""
    item = ed.build_training_reference_record(_reference())
    assert "proven_bands" in item, "proven_bands is computed and dropped"


def test_the_stored_types_are_decimal_not_float():
    """boto3 rejects a Python float (the repo's Decimal-before-DDB-write convention).
    The two newly-stored fields go through the same `_deep_dec`/`_to_dec` path as their
    siblings, so a nested float in `proven_bands` would 500 the weekly run — a failure
    that would only appear in production, on a Sunday."""
    from decimal import Decimal

    item = ed.build_training_reference_record(_reference())

    def walk(value, path="proven_bands"):
        if isinstance(value, float):
            raise AssertionError(f"a raw float survived to the item at {path} — boto3 will reject it")
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}")
        elif isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")

    walk(item.get("proven_bands", {}))
    assert isinstance(item["reference_schema"], (Decimal, int)), type(item["reference_schema"])


def test_the_record_still_carries_the_fields_it_always_did():
    """A regression net around the fix: adding two keys must not disturb the six that
    were already stored, nor the key shape readers query on."""
    item = ed.build_training_reference_record(_reference())
    for k in ("pk", "sk", "bands", "proven_curve", "source_window", "derived_at", "confidence", "n_episodes_with_covariates"):
        assert k in item, f"{k} fell off the record"
    assert item["sk"].startswith("DATE#")
    assert item["sk"][5:] == item["derived_at"][:10], "sk must stay the derived_at day — readers take the newest in-range record"


def test_no_phase_attribute_keeps_the_reference_cross_phase():
    """States the premise the reader rests on: the reference spans 14 years of history,
    so a `phase` attribute would let an experiment restart hide it (ADR-058/#2109)."""
    item = ed.build_training_reference_record(_reference())
    assert "phase" not in item, "a phase attribute would make the reference experiment-scoped"


# ── #4427 (TB-7): the band table counts each 2024–25 session once ─────────────────────────
#
# The wire is the two REAL day rows #4419 read from DDB (2024-10-01, 2024-10-05), reused
# from tests/test_shared_modules.py so there is one copy of them: WHOOP and the Garmin both
# pushed each walk, the Garmin copies read 49–54 bpm, and on 10-05 WHOOP split one long
# Garmin walk into two chunks (a triple). They reach the band builder through the lambda's
# own `_load_inputs`, with only the DynamoDB read replaced.

from training import blueprint_rederive as br  # noqa: E402


def _load_inputs_over(monkeypatch, strava_rows):
    from tests.test_shared_modules import _real_day_2024_10_01, _real_day_2024_10_05  # noqa: F401

    seen = {}

    def fake_read(source, start="2010-01-01", end=None, keep_duplicates=""):
        seen[source] = keep_duplicates
        return list(strava_rows) if source == "strava" else []

    monkeypatch.setattr(ed, "_read_all_history", fake_read)
    out = ed._load_inputs()
    return out, seen


def _real_rows():
    from tests.test_shared_modules import _real_day_2024_10_01, _real_day_2024_10_05

    return [_real_day_2024_10_01(), _real_day_2024_10_05()]


def test_4427_real_2024_days_count_each_session_once_with_a_plausible_hr(monkeypatch):
    """11 device records on the two real days are 5 sessions: the 10-01 walk (twin), ride
    (WHOOP + Zwift), lift (WHOOP + Hevy), and on 10-05 one long walk (Garmin + two WHOOP
    chunks) and one lift. Hours are the longest member's moving time; HR is the highest
    plausible member average (the Garmin's 49.3 / 54.1 and Zwift's 53.0 are rejected)."""
    (_w, activities, *_rest, basis), seen = _load_inputs_over(monkeypatch, _real_rows())
    assert seen["strava"], "the strava read must opt out of the seam and cluster every device's record here"
    walks = [a for a in activities if a["kind"] == "walk"]
    assert [(a["date"], a["n_records"]) for a in walks] == [("2024-10-01", 2), ("2024-10-05", 3)]
    assert round(walks[0]["hours"], 4) == round(3656.0 / 3600, 4) and walks[0]["hr"] == 103.5 and walks[0]["miles"] == 3.0
    assert round(walks[1]["hours"], 4) == round(12605.0 / 3600, 4) and walks[1]["hr"] == 116.4 and walks[1]["miles"] == 10.31
    rides = [a for a in activities if a["kind"] == "cycle"]
    assert len(rides) == 1 and rides[0]["hr"] == 121.2 and rides[0]["miles"] == 7.16
    assert sorted(a["kind"] for a in activities) == ["cycle", "lift", "lift", "walk", "walk"]
    assert basis["walk"] == {
        "records": 5,
        "sessions": 2,
        "hours_records_summed": round((3599 + 3656 + 6389 + 6749 + 12605) / 3600, 1),
        "hours_sessions": round((3656 + 12605) / 3600, 1),
        "hr_rejected_records": 2,
        "sessions_with_hr": 2,
    }


def test_4427_the_band_rates_halve_and_the_hr_artefact_leaves_the_band(monkeypatch):
    """The same records through `weekly_covariates`: twin-counted (every record an activity,
    as before #4427) vs clustered. Walks and hours drop to the distinct sessions; the band
    walking HR is the time-weighted plausible reading, not dragged below 100 by the Garmin."""
    (_w, sessions, *_rest), _seen = _load_inputs_over(monkeypatch, _real_rows())
    twin_counted = [
        {
            "date": r["date"],
            "kind": ed.classify_activity(a["sport_type"]),
            "hours": a["moving_time_seconds"] / 3600,
            "miles": a["distance_miles"] or 0.0,
            "hr": a["average_heartrate"],
        }
        for r in _real_rows()
        for a in r["activities"]
    ]
    week = {f"2024-10-0{d}" for d in range(1, 8)}  # day-set mode: exactly one week, as a band sums
    old = ed.weekly_covariates(twin_counted, "2024-10-01", "2024-10-07", day_set=week)
    new = ed.weekly_covariates(sessions, "2024-10-01", "2024-10-07", day_set=week)
    assert old["walks_wk"] == 5.0 and new["walks_wk"] == 2.0
    assert new["walk_hr_wk"] < 0.6 * old["walk_hr_wk"]
    assert old["walk_bpm"] < 100, "the fixture must carry the artefact the rule removes"
    expected = round((103.5 * 3656 + 116.4 * 12605) / (3656 + 12605))
    assert new["walk_bpm"] == expected, (new["walk_bpm"], expected)


def test_4427_implausible_device_averages_are_rejected_never_averaged():
    lo, hi = br.PLAUSIBLE_AVG_HR_BPM
    assert br.plausible_hr(lo - 0.1) is None and br.plausible_hr(hi + 1) is None and br.plausible_hr(None) is None
    assert br.plausible_hr(lo) == lo
    only_artefact = br.distinct_sessions(
        [{"date": "2024-10-02", "kind": "walk", "start": "2024-10-02T08:00:00Z", "elapsed_s": 3600, "moving_s": 3500, "hr": 52.0}]
    )
    assert only_artefact[0]["hr"] is None, "absence, never the artefact and never 0 (ADR-104)"


def test_4427_separate_walks_on_one_day_stay_separate():
    """The rule must not merge two real walks: 07:00 for 60 min and 18:00 for 45 min."""
    rec = [
        {"date": "2024-10-03", "kind": "walk", "start": "2024-10-03T07:00:00Z", "elapsed_s": 3600, "moving_s": 3600, "hr": 105.0},
        {"date": "2024-10-03", "kind": "walk", "start": "2024-10-03T18:00:00Z", "elapsed_s": 2700, "moving_s": 2700, "hr": 101.0},
        {"date": "2024-10-03", "kind": "walk", "start": "2024-10-03T07:40:00Z", "elapsed_s": 3600, "moving_s": 3600, "hr": 99.0},
    ]
    out = br.distinct_sessions(rec)
    # 07:40 overlaps the 07:00 walk by 20 min of the shorter 60 -> < half -> a separate walk.
    assert len(out) == 3


def test_4427_method_n_and_supersedes_travel_on_the_record():
    """The #3735 lesson for the three #4427 fields: computed AND stored."""
    ref = _reference()
    ref["supersedes"] = br.supersedes_label({"sk": "DATE#2026-09-27", "reference_schema": 2}, ref)
    item = ed.build_training_reference_record(ref)
    assert item["method"]["id"] == br.METHOD_ID
    assert "n" in item and "cut_bands" in item and item["cut_window"] == "..".join(br.CUT_WINDOW)
    assert item["supersedes"]["sk"] == "DATE#2026-09-27" and item["supersedes"]["status"] == "superseded"


def test_4427_supersedes_labels_only_a_different_method():
    new = {"reference_schema": 3, "method": br.method()}
    assert br.supersedes_label(None, new) is None
    old = br.supersedes_label({"sk": "DATE#2026-09-27", "reference_schema": 2}, new)
    assert old["status"] == "superseded" and "twin" in old["reason"]
    same = br.supersedes_label({"sk": "DATE#2026-10-04", "reference_schema": 3, "method": br.method()}, new)
    assert "status" not in same, "a weekly re-derivation by the same method is not a supersession"


class _FakeTable:
    def __init__(self, newest=None):
        self.puts, self.newest = [], newest

    def put_item(self, Item):
        self.puts.append(Item)

    def query(self, **kw):
        return {"Items": [self.newest] if self.newest else []}


def test_4427_dry_run_writes_nothing_and_reports_the_rebuild(monkeypatch):
    weigh_ins, activities = _history()
    basis = {"window": "x", "walk": {"sessions": 1}}
    monkeypatch.setattr(ed, "_load_inputs", lambda: (weigh_ins, activities, {}, {}, {}, basis))
    fake = _FakeTable(newest={"sk": "DATE#2026-09-27", "reference_schema": 2})
    monkeypatch.setattr(ed, "table", fake)
    monkeypatch.setattr(ed, "run_prescription_forecast", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry run forecast")))
    out = ed.lambda_handler({"dry_run": True}, None)
    assert fake.puts == [], "a dry run wrote to DynamoDB"
    assert out["dry_run"] is True and out["n"] == basis and out["method"]["id"] == br.METHOD_ID
    assert out["supersedes"]["status"] == "superseded" and out["cut_bands"] is not None


def test_4427_a_real_run_stamps_supersedes_on_the_written_reference(monkeypatch):
    weigh_ins, activities = _history()
    monkeypatch.setattr(ed, "_load_inputs", lambda: (weigh_ins, activities, {}, {}, {}, {"window": "x"}))
    fake = _FakeTable(newest={"sk": "DATE#2026-09-27", "reference_schema": 2})
    monkeypatch.setattr(ed, "table", fake)
    monkeypatch.setattr(ed, "run_prescription_forecast", lambda *a, **k: {"issued": False})
    ed.lambda_handler({}, None)
    refs = [p for p in fake.puts if p["pk"].endswith("#training_reference")]
    assert len(refs) == 1 and refs[0]["supersedes"]["sk"] == "DATE#2026-09-27"
    assert refs[0]["supersedes"]["status"] == "superseded" and int(refs[0]["reference_schema"]) == 3
