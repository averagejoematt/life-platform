"""tests/test_illness_triad_4978.py — the early-illness / overload triad (#4978, epic #4967).

What this holds:
  * each leg (resting heart rate, skin temperature, respiratory rate) is the night's value against the mean of his
    own preceding nights from the same source, and fires at the charter's ``min_rise`` — every threshold READ from
    the charter's ``illness_triad`` block, never typed here (the derivation guard's NOT_APPLICABLE row points here);
  * ``min_legs`` legs together raise ONE flag; one alone never does; a charter with no block evaluates nothing;
  * a leg with no reading or a thin baseline is UNEVALUATED, never zero (ADR-104);
  * THE HR REGIME (#4999): across the 2026-10-10 marker the RHR baseline is cut at the marker, so a pre-marker night
    never moves the comparison; inside the re-baselining window the RHR leg is not evaluated at all; a night
    excluded from the HR baselines is not scored;
  * the Apple Watch twin is reported against the watch's own baseline and never counted (#4974/#4975);
  * the row is owner-only and carries nothing DynamoDB rejects (Decimal, never float); a dry run writes nothing;
  * PRIVACY: the flag partition has exactly its writer, its one owner-channel reader and the registries — and inside
    the anomaly detector only the handler touches it (never the ``anomalies`` row or the mail builders).

Every date is fixed; nothing here reads the clock (#4848). The series are synthetic.
"""

# premerge-gate: #4978: os.walk sweep of lambdas/ mcp/ site/ and the site generators — the owner-only illness-triad flag partition has exactly its writer and one owner-channel reader

from __future__ import annotations

import ast
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from health import (
    hr_regime,  # noqa: E402
    illness_triad as it,  # noqa: E402
)
from training import training_charter as tc  # noqa: E402


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    """The bundled PUBLIC charter only: no owner twin from the laptop env, no S3 probe."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def C(path):
    return tc.charter_value("illness_triad." + path)


def _s():
    return it.settings()


NIGHT = "2026-11-20"  # well after the 2026-10-10 marker's window (through 2026-10-24): no truncation
BASE = {"rhr_up": 60.0, "temp_up": 33.0, "resp_up": 15.0}


def _days_before(night: str, n: int) -> list:
    d = date.fromisoformat(night)
    return [(d - timedelta(days=i)).isoformat() for i in range(n, 0, -1)]


def _series(night: str, leg: str, night_value=None, n=None, base=None):
    n = n if n is not None else C("baseline_days")
    out = {d: (base if base is not None else BASE[leg]) for d in _days_before(night, n)}
    if night_value is not None:
        out[night] = night_value
    return out


def _rise(leg):
    return C(f"legs.{leg}.min_rise")


def _inputs(night=NIGHT, up=(), **over):
    """Every leg present; the legs in `up` sit exactly at their charter line, the rest at baseline."""
    inp = {"excluded": set()}
    for leg in it.LEGS:
        inp[leg] = _series(night, leg, BASE[leg] + (_rise(leg) if leg in up else 0.0))
    inp.update(over)
    return inp


# ── the charter block ────────────────────────────────────────────────────────────────────


def test_the_thresholds_are_the_charter_block_and_name_their_provenance():
    s = _s()
    assert s["min_legs"] == C("min_legs") and s["baseline_days"] == C("baseline_days")
    assert s["min_baseline_n"] == C("min_baseline_n") and s["fresh_days"] == C("fresh_days")
    assert set(s["legs"]) == set(it.LEGS) and all(s["legs"][leg].get("min_rise") is not None for leg in it.LEGS)
    assert "platform default" in C("provenance") and "not a diagnosis" in C("rigor")
    assert s["charter_version"] == tc.charter_version()


def test_a_charter_without_the_block_evaluates_nothing_and_never_raises():
    s = it.settings(charter_reader=lambda path: None)
    res = it.evaluate(_inputs(up=it.LEGS), NIGHT, s)
    assert res["active"] is False and res["up"] == []
    assert {v["state"] for v in res["legs"].values()} == {it.STATE_UNEVALUATED}


# ── the rule ─────────────────────────────────────────────────────────────────────────────


def test_a_quiet_night_is_clear():
    res = it.evaluate(_inputs(), NIGHT, _s())
    assert res["active"] is False and res["up"] == []
    assert {v["state"] for v in res["legs"].values()} == {it.STATE_NORMAL}


def test_each_leg_fires_at_its_line_and_stays_quiet_just_inside_it():
    for leg in it.LEGS:
        at = it.evaluate(_inputs(up=(leg,)), NIGHT, _s())
        assert at["legs"][leg]["state"] == it.STATE_UP, leg
        inside = _inputs(**{leg: _series(NIGHT, leg, BASE[leg] + _rise(leg) * 0.9)})
        assert it.evaluate(inside, NIGHT, _s())["legs"][leg]["state"] == it.STATE_NORMAL, leg


def test_one_leg_alone_never_raises_the_flag():
    for leg in it.LEGS:
        res = it.evaluate(_inputs(up=(leg,)), NIGHT, _s())
        assert res["up"] == [leg] and res["active"] is False


def test_min_legs_together_raise_one_flag():
    up = it.LEGS[: C("min_legs")]
    res = it.evaluate(_inputs(up=up), NIGHT, _s())
    assert res["active"] is True and res["up"] == list(up)
    assert "not a diagnosis" in res["rigor"]


def test_only_a_rise_counts():
    drops = _inputs(**{leg: _series(NIGHT, leg, BASE[leg] - 10 * _rise(leg)) for leg in it.LEGS})
    assert it.evaluate(drops, NIGHT, _s())["up"] == []


def test_no_reading_or_a_thin_baseline_is_unevaluated_never_zero():
    thin = C("min_baseline_n") - 1
    inp = _inputs(up=it.LEGS, temp_up={}, resp_up=_series(NIGHT, "resp_up", 99.0, n=thin))
    res = it.evaluate(inp, NIGHT, _s())
    assert res["legs"]["temp_up"]["state"] == it.STATE_UNEVALUATED and "no reading" in res["legs"]["temp_up"]["line"]
    assert res["legs"]["resp_up"]["state"] == it.STATE_UNEVALUATED and "too thin" in res["legs"]["resp_up"]["line"]
    assert res["up"] == ["rhr_up"] and res["active"] is False


def test_the_night_never_sits_in_its_own_baseline():
    inp = _inputs(up=("temp_up",))
    leg = it.evaluate(inp, NIGHT, _s())["legs"]["temp_up"]
    assert leg["baseline"] == BASE["temp_up"] and leg["basis"]["through"] < NIGHT


# ── the HR regime (#4999) ────────────────────────────────────────────────────────────────

MARKER = hr_regime.HR_REGIME_MARKERS[0]["date"]  # 2026-10-10
CROSS_NIGHT = "2026-11-05"  # its 30-night window reaches back before the marker


def test_across_the_marker_the_rhr_baseline_is_cut_and_pre_marker_nights_never_count():
    post = [d for d in _days_before(CROSS_NIGHT, C("baseline_days")) if d > MARKER]
    pre = [d for d in _days_before(CROSS_NIGHT, C("baseline_days")) if d <= MARKER]
    assert pre and post, "the fixture must straddle the marker"
    rise = _rise("rhr_up")
    # Pre-marker nights sit FAR above the night: averaged in, they would hide the rise entirely.
    rhr = {**{d: BASE["rhr_up"] + 10 * rise for d in pre}, **{d: BASE["rhr_up"] for d in post}, CROSS_NIGHT: BASE["rhr_up"] + rise}
    res = it.evaluate(_inputs(night=CROSS_NIGHT, rhr_up=rhr), CROSS_NIGHT, _s())
    leg = res["legs"]["rhr_up"]
    assert leg["state"] == it.STATE_UP and leg["baseline"] == BASE["rhr_up"]
    assert leg["basis"]["truncated_at_marker"] == MARKER and leg["basis"]["n"] == len(post)
    assert leg["basis"]["since"] > MARKER
    # Not HR-derived: the temperature leg keeps its full window across the marker.
    assert res["legs"]["temp_up"]["basis"]["n"] == C("baseline_days")


def test_inside_the_re_baselining_window_the_rhr_leg_is_not_evaluated():
    night = "2026-10-20"
    assert hr_regime.is_rebaselining(night)
    res = it.evaluate(_inputs(night=night, up=it.LEGS), night, _s())
    assert res["legs"]["rhr_up"]["state"] == hr_regime.REBASELINING and "rhr_up" not in res["up"]
    # The two non-HR legs still read; together they meet the line, so the flag is honest without the HR leg.
    assert res["up"] == ["temp_up", "resp_up"] and res["active"] is (C("min_legs") <= 2)


def test_a_night_excluded_from_hr_baselines_is_not_scored_and_unreadable_exclusions_score_nothing():
    res = it.evaluate(_inputs(up=it.LEGS, excluded={NIGHT}), NIGHT, _s())
    assert res["legs"]["rhr_up"]["state"] == it.STATE_UNEVALUATED
    res = it.evaluate(_inputs(up=it.LEGS, excluded_unreadable=True), NIGHT, _s())
    assert res["legs"]["rhr_up"]["state"] == it.STATE_UNEVALUATED


def test_an_excluded_baseline_day_is_dropped_from_the_rhr_baseline():
    days = _days_before(NIGHT, C("baseline_days"))
    rhr = {**{d: BASE["rhr_up"] for d in days}, NIGHT: BASE["rhr_up"] + _rise("rhr_up")}
    rhr[days[-1]] = 500.0  # an irregular-rhythm day
    leg = it.evaluate(_inputs(rhr_up=rhr, excluded={days[-1]}), NIGHT, _s())["legs"]["rhr_up"]
    assert leg["state"] == it.STATE_UP and leg["basis"]["excluded_days_n"] == 1


# ── the second instrument ────────────────────────────────────────────────────────────────


def test_the_watch_twin_is_reported_never_counted():
    watch = _series(NIGHT, "temp_up", BASE["temp_up"] + 5 * _rise("temp_up"))
    res = it.evaluate(_inputs(watch_temp_up=watch), NIGHT, _s())
    assert res["up"] == [] and res["active"] is False
    assert "Apple Watch" in res["corroboration"]["temp_up"] and "not counted" in res["corroboration"]["temp_up"]


# ── the I/O half ─────────────────────────────────────────────────────────────────────────


def _fetch(night=NIGHT, today_row=True):
    whoop = [
        {"date": d, "sk": "DATE#" + d, "resting_heart_rate": 60, "skin_temp_celsius": 33.0, "respiratory_rate": 15.0}
        for d in _days_before(night, 40)
    ]
    if today_row:
        whoop.append(
            {
                "date": night,
                "sk": "DATE#" + night,
                "resting_heart_rate": 60 + _rise("rhr_up"),
                "skin_temp_celsius": 33.0 + _rise("temp_up"),
                "respiratory_rate": 15.0,
            }
        )
    whoop.append({"date": night, "sk": f"DATE#{night}#WORKOUT#1", "resting_heart_rate": 200})  # a sub-row, never a day
    calls = []

    def fetch(source, start, end):
        calls.append(source)
        return {"whoop": whoop, "apple_health": [], "eightsleep": [], "withings": []}.get(source, [])

    return fetch, calls


def test_gather_and_evaluate_read_the_stored_shapes():
    fetch, calls = _fetch()
    night, inputs = it.gather(fetch, NIGHT, _s())
    assert night == NIGHT and {"whoop", "apple_health", "eightsleep", "withings"} <= set(calls)
    res = it.evaluate(inputs, night, _s())
    assert res["up"] == ["rhr_up", "temp_up"] and res["active"] is True
    assert res["legs"]["rhr_up"]["source"] == "metric_truth:rhr_bpm"


def test_with_no_row_for_the_run_day_the_night_before_is_read_within_fresh_days():
    fetch, _ = _fetch(night="2026-11-19")
    night, _inputs_ = it.gather(fetch, NIGHT, _s())
    assert night == "2026-11-19"
    fetch, _ = _fetch(night="2026-11-10")
    assert it.gather(fetch, NIGHT, _s())[0] is None


def test_a_failed_family_is_unevaluated_never_zero():
    def fetch(source, start, end):
        raise RuntimeError("boom")

    night, inputs = it.gather(fetch, NIGHT, _s())
    res = it.evaluate(inputs, night, _s())
    assert night is None and res["active"] is False


class _Table:
    def __init__(self, rows=()):
        self.put = []
        self.rows = list(rows)

    def put_item(self, Item):
        self.put.append(Item)

    def query(self, **kw):
        return {"Items": self.rows}


def _walk(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)
    else:
        yield x


def test_the_row_is_owner_only_and_carries_nothing_dynamodb_rejects():
    res = it.evaluate(_inputs(up=it.LEGS[:2]), NIGHT, _s())
    row = it.item(res)
    assert row["pk"] == "USER#matthew#SOURCE#illness_triad_flag" and row["sk"] == "DATE#" + NIGHT
    assert row["tier"] == "owner_only" and row["active"] is True and "not a diagnosis" in row["rigor"]
    assert not [v for v in _walk(row) if isinstance(v, float)], "DynamoDB rejects float"
    assert isinstance(row["legs"]["rhr_up"]["deviation"], Decimal)


def test_run_stores_the_night_and_a_dry_run_writes_nothing():
    fetch, _ = _fetch()
    t = _Table()
    out = it.run(t, fetch, NIGHT)
    assert out["active"] is True and t.put and t.put[0]["sk"] == "DATE#" + NIGHT
    t2 = _Table()
    assert it.run(t2, fetch, NIGHT, dry_run=True)["active"] is True and t2.put == []


def test_run_never_raises(monkeypatch):
    monkeypatch.setattr(it, "settings", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert it.run(_Table(), None, NIGHT) == {"active": False, "night": None, "up": []}


def test_the_performance_thread_lines_state_the_flag_a_clear_read_or_an_absence():
    raised = it.item(it.evaluate(_inputs(up=it.LEGS[:2]), NIGHT, _s()))
    clear = it.item(it.evaluate(_inputs(), NIGHT, _s()))
    lines = it.owner_lines([clear, raised], "2026-11-21")
    assert "RAISED" in lines[0] and "not a diagnosis" in lines[0] and len(lines) >= 3
    assert "clear" in it.owner_lines([clear], "2026-11-21")[0]
    assert "absent" in it.owner_lines([raised], "2026-11-30")[0]
    assert "absent" in it.owner_lines([], "2026-11-21")[0]


def test_the_performance_pack_carries_the_triad_line():
    from coach import coach_domain_facts as cdf

    row = it.item(it.evaluate(_inputs(up=it.LEGS[:2]), NIGHT, _s()))

    class T:
        def query(self, **kw):
            pk = kw["ExpressionAttributeValues"][":pk"]
            return {"Items": [row] if pk.endswith("illness_triad_flag") else []}

    lines = cdf._physical_pack(T(), "2026-11-21")
    assert any("Illness/overload triad" in ln and "RAISED" in ln for ln in lines)


# ── PRIVACY: the partition has exactly its writer and one owner-channel reader ───────────

ALLOWED = {
    "lambdas/health/illness_triad.py",
    "lambdas/emails/anomaly_detector_lambda.py",  # the one writer; the handler only (asserted below)
    "lambdas/coach/coach_domain_facts.py",  # the Performance coach's own Telegram thread
    "lambdas/privacy/field_tiers.py",
    "lambdas/experiment/phase_taxonomy.py",
}
_TOKENS = ("illness_triad_flag", "from health import illness_triad", "health.illness_triad", "from health.illness_triad")


def _sweep():
    hits = set()
    for root in (ROOT / "lambdas", ROOT / "mcp", ROOT / "site", ROOT / "scripts"):
        for dirpath, _dirs, files in os.walk(root):
            if "__pycache__" in dirpath or "node_modules" in dirpath:
                continue
            for f in files:
                if not f.endswith((".py", ".js", ".html", ".mjs")):
                    continue
                p = Path(dirpath) / f
                rel = str(p.relative_to(ROOT))
                if rel.startswith("scripts/") and not f.startswith("v4_build_"):
                    continue  # the site generators are the scripts that publish
                try:
                    text = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if any(tok in text for tok in _TOKENS):
                    hits.add(rel)
    return hits


def test_only_the_writer_and_the_owner_thread_touch_the_flag():
    hits = _sweep()
    assert hits == ALLOWED, f"unexpected readers: {sorted(hits - ALLOWED)}; missing: {sorted(ALLOWED - hits)}"
    for rel in hits - {"lambdas/emails/anomaly_detector_lambda.py"}:
        assert not rel.startswith(("lambdas/web/", "lambdas/emails/", "lambdas/content/", "site/", "scripts/"))


def test_inside_the_anomaly_detector_only_the_handler_touches_the_triad():
    tree = ast.parse((ROOT / "lambdas/emails/anomaly_detector_lambda.py").read_text(encoding="utf-8"))
    users = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        for n in ast.walk(fn)
        if isinstance(n, ast.Name) and n.id in ("illness_triad", "triad")
    }
    assert users == {"lambda_handler"}, f"the triad reached {sorted(users)} — never the anomalies row or the mail builders"


def test_the_sweep_sees_a_planted_public_reader(tmp_path, monkeypatch):
    """The guard can fail: a web module that imports the triad is a hit."""
    fake = tmp_path / "lambdas" / "web"
    fake.mkdir(parents=True)
    (fake / "site_api_triad.py").write_text("from health import illness_triad\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert _sweep() == {"lambdas/web/site_api_triad.py"}


def test_the_partition_is_registered_owner_only_and_experiment_scoped():
    from experiment.phase_taxonomy import SOURCE_CLASS
    from privacy.field_tiers import SOURCE_TIERS, TIER_OWNER_ONLY

    assert SOURCE_TIERS[it.SOURCE] == TIER_OWNER_ONLY and SOURCE_CLASS[it.SOURCE] == "experiment_scoped"
