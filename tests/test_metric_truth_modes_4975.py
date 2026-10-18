"""tests/test_metric_truth_modes_4975.py — METRIC_TRUTH truth modes, and the tables collapsed onto it (#4975).

Four things are pinned here:

1. The mode matrix: `primary` (the default — today's first_positive_else_first_zero),
   `primary_backup` (the truth source, else the ONE named backup, `source_used` returned) and
   `mean` (the mean of the usable values, `n_sources` + per-source `values` returned), each
   through the ONE function every reader already calls, `common.metric_truth.resolve`.
2. The registry refuses a malformed mode facet at import-time validation.
3. No facet on main has a mode other than `primary`: which mode a metric uses is the owner's
   ruling (#4975 gate:owner, after the #4974 agreement study), so a lane that sets one reds here.
4. The collapse: `mcp/config.py`'s domain owners for physiology/sleep and
   `web/vitals_resolver.py`'s hrv/rhr/sleep READ the registry facet (a mutation of the facet
   moves their answer). The tree sweep — no hand-written `*SOURCE_OF_TRUTH*` table under
   lambdas/ or mcp/ states a source by literal for a domain the registry owns — extends the
   #4630 box-5 guard in tests/test_steps_truth_resolver_4630.py (one structural gate, not two).
"""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, ROOT)

for _k, _v in (
    ("TABLE_NAME", "life-platform-test"),
    ("USER_ID", "matthew"),
    ("S3_BUCKET", "test-bucket"),
    ("AWS_ACCESS_KEY_ID", "FAKE"),
    ("AWS_SECRET_ACCESS_KEY", "FAKE"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
):
    os.environ.setdefault(_k, _v)

from common import metric_truth as mt  # noqa: E402
from ingestion import source_registry as reg  # noqa: E402

M = "test_metric_4975"


def _facet(**over):
    base = {
        "truth_source": "whoop",
        "unit": "ms",
        "fallback_order": ("whoop", "apple_health", "garmin"),
        "field_by_source": {"whoop": "hrv", "apple_health": "hrv_apple", "garmin": "hrv_garmin"},
        "min_by_source": {},
        "overlap_rule": "first_positive_else_first_zero",
        "ruling": "test fixture",
    }
    base.update(over)
    return base


@pytest.fixture
def facet(monkeypatch):
    def _install(**over):
        monkeypatch.setitem(reg.METRIC_TRUTH, M, _facet(**over))
        reg._validate_metric_truth()

    return _install


W = {"hrv": Decimal("61.2")}
A = {"hrv_apple": Decimal("48.8")}
G = {"hrv_garmin": Decimal("55.0")}


# ── 1. the mode matrix ───────────────────────────────────────────────────────


def test_primary_is_the_default_and_is_todays_rule(facet):
    facet()  # no mode key at all
    r = mt.resolve(M, {"whoop": W, "apple_health": A})
    assert (r.mode, r.source_used, r.value, r.n_sources) == ("primary", "whoop", pytest.approx(61.2), 1)
    r = mt.resolve(M, {"whoop": {}, "apple_health": A})
    assert (r.source_used, r.value) == ("apple_health", pytest.approx(48.8))
    r = mt.resolve(M, {"whoop": {"hrv": 0}, "apple_health": A})
    assert r.source_used == "apple_health", "a zero report never beats another source's positive value"
    r = mt.resolve(M, {"whoop": {"hrv": 0}, "apple_health": {}})
    assert (r.source_used, r.value) == ("whoop", 0.0)


def test_primary_backup_uses_the_primary_when_present(facet):
    facet(mode="primary_backup", backup="apple_health")
    r = mt.resolve(M, {"whoop": W, "apple_health": A, "garmin": G})
    assert (r.mode, r.source_used, r.field, r.value, r.n_sources) == ("primary_backup", "whoop", "hrv", pytest.approx(61.2), 1)


def test_primary_backup_falls_to_the_named_backup_only(facet):
    facet(mode="primary_backup", backup="apple_health")
    r = mt.resolve(M, {"whoop": None, "apple_health": A, "garmin": G})
    assert (r.source_used, r.value) == ("apple_health", pytest.approx(48.8))
    assert "backup" in r.reason and "whoop" in r.reason
    # a third source is never consulted, even when it is the only one with a value
    r = mt.resolve(M, {"whoop": None, "apple_health": None, "garmin": G})
    assert (r.value, r.source_used, r.n_sources) == (None, None, 0)
    assert set(r.candidates) == {"whoop", "apple_health"}


def test_primary_backup_keeps_a_primary_zero_reading(facet):
    facet(mode="primary_backup", backup="apple_health")
    r = mt.resolve(M, {"whoop": {"hrv": 0}, "apple_health": A})
    assert (r.source_used, r.value) == ("whoop", 0.0)


def test_mean_of_the_sources_present(facet):
    facet(mode="mean")
    r = mt.resolve(M, {"whoop": W, "apple_health": A, "garmin": {}})
    assert r.mode == "mean"
    assert r.value == pytest.approx((61.2 + 48.8) / 2)
    assert r.n_sources == 2 and r.sources_used == ("whoop", "apple_health")
    assert r.values == {"whoop": pytest.approx(61.2), "apple_health": pytest.approx(48.8)}
    assert r.source_used is None and r.field is None, "a mean over two sources has no single source"


def test_mean_over_one_source_names_it(facet):
    facet(mode="mean")
    r = mt.resolve(M, {"whoop": None, "apple_health": A})
    assert (r.value, r.source_used, r.field, r.n_sources) == (pytest.approx(48.8), "apple_health", "hrv_apple", 1)


def test_mean_drops_a_zero_while_any_source_is_positive(facet):
    facet(mode="mean")
    r = mt.resolve(M, {"whoop": {"hrv": 0}, "apple_health": A})
    assert (r.value, r.n_sources) == (pytest.approx(48.8), 1)
    r = mt.resolve(M, {"whoop": {"hrv": 0}, "apple_health": {"hrv_apple": 0}})
    assert (r.value, r.n_sources) == (0.0, 2)
    r = mt.resolve(M, {})
    assert (r.value, r.n_sources) == (None, 0)


def test_modes_flow_through_resolve_by_date(facet):
    facet(mode="mean")
    rows = {
        "whoop": [{"sk": "DATE#2026-10-14", **W}, {"sk": "DATE#2026-10-15", "hrv": 70}],
        "apple_health": [{"sk": "DATE#2026-10-14", **A}],
    }
    out = mt.resolve_by_date(M, rows)
    assert out["2026-10-14"].value == pytest.approx(55.0) and out["2026-10-14"].n_sources == 2
    assert out["2026-10-15"].value == 70.0 and out["2026-10-15"].source_used == "whoop"


def test_mode_mutation_changes_the_answer(facet):
    """Mutation control for the matrix: one row set, three modes, three different answers."""
    rows = {"whoop": None, "apple_health": A, "garmin": G}
    answers = {}
    for mode, extra in (("primary", {}), ("primary_backup", {"backup": "garmin"}), ("mean", {})):
        facet(mode=mode, **extra)
        answers[mode] = mt.resolve(M, rows).value
    assert answers == {"primary": pytest.approx(48.8), "primary_backup": pytest.approx(55.0), "mean": pytest.approx(51.9)}


# ── 2. the registry refuses a malformed mode ─────────────────────────────────


def test_registry_refuses_a_malformed_mode(monkeypatch):
    cases = (
        ({"mode": "median"}, "unknown mode"),
        ({"mode": "primary_backup"}, "backup"),
        ({"mode": "primary_backup", "backup": "whoop"}, "backup"),
        ({"mode": "primary_backup", "backup": "withings"}, "backup"),
        ({"mode": "mean", "backup": "apple_health"}, "only meaningful"),
    )
    accepted = []
    for over, match in cases:
        monkeypatch.setitem(reg.METRIC_TRUTH, M, _facet(**over))
        try:
            reg._validate_metric_truth()
            accepted.append(over)
        except ValueError as e:
            assert match in str(e), (over, str(e))
    assert not accepted, f"malformed mode facets accepted: {accepted}"


# ── 3. no mode is chosen in code: every facet on main is `primary` ───────────


def test_every_facet_on_main_is_primary():
    """The per-metric mode is the owner's ruling (#4975 gate:owner) — a facet carrying any
    other mode is a lane choosing it. When he rules, this test moves WITH the quoted words."""
    modes = {m: reg.metric_truth(m)["mode"] for m in reg.METRIC_TRUTH}
    assert modes and set(modes.values()) == {"primary"}, modes
    assert all("backup" not in f for f in reg.METRIC_TRUTH.values())


def test_the_vitals_facets_are_todays_single_source_answer():
    for metric, fld in (("hrv_ms", "hrv"), ("rhr_bpm", "resting_heart_rate"), ("sleep_hours", "sleep_duration_hours")):
        f = reg.metric_truth(metric)
        assert f["fallback_order"] == ("whoop",) and f["field_by_source"] == {"whoop": fld}, metric
        assert "#4975" in f["ruling"] and "pending" in f["ruling"], metric
        # the writer seam (#2847): the field the facet reads is the field the Whoop writer writes
        with open(os.path.join(ROOT, "lambdas", "ingestion", "whoop_lambda.py"), encoding="utf-8") as fh:
            assert f'_set_dec(fields, "{fld}"' in fh.read(), fld


def test_no_facet_key_is_a_stored_field_name():
    """anomaly_detector routes a METRICS field through the resolver whenever the field name is a
    METRIC_TRUTH key; a facet keyed by a raw field ("hrv") would silently re-route its baseline."""
    from emails import anomaly_detector_lambda as ad

    collide = {m for m in reg.METRIC_TRUTH if m != "steps"} & {f for _, f, _, _ in ad.METRICS}
    assert not collide, collide


# ── 4. the collapse ──────────────────────────────────────────────────────────


def test_mcp_domain_owners_read_the_facet():
    from mcp import config

    assert config._DEFAULT_SOURCE_OF_TRUTH["physiology"] == reg.metric_truth("hrv_ms")["truth_source"] == "whoop"
    assert config._DEFAULT_SOURCE_OF_TRUTH["sleep"] == reg.metric_truth("sleep_hours")["truth_source"] == "whoop"


class _FakeTable:
    def __init__(self, by_pk):
        self.by_pk = by_pk

    def query(self, **kw):
        cond = kw["KeyConditionExpression"]
        pk = cond._values[0]._values[1]
        items = sorted(self.by_pk.get(pk, []), key=lambda i: i["sk"], reverse=True)
        return {"Items": items[: kw.get("Limit") or None]}


_NOW = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
_WHOOP = [
    {"sk": "DATE#2026-10-18", "sleep_duration_hours": Decimal("7.9")},  # unscored yet
    {"sk": "DATE#2026-10-17", "recovery_score": Decimal("64"), "hrv": Decimal("58.4"), "resting_heart_rate": Decimal("54")},
]


def _vitals():
    from web import vitals_resolver

    return vitals_resolver.resolve_vitals(_FakeTable({"USER#matthew#SOURCE#whoop": _WHOOP}), "USER#matthew#SOURCE#", now=_NOW)


def test_vitals_answer_is_unchanged_through_the_facet():
    out = _vitals()
    assert (out["recovery_pct"], out["hrv_ms"], out["rhr_bpm"], out["recovery_as_of"]) == (64.0, 58.4, 54.0, "2026-10-17")
    assert (out["sleep_hours"], out["sleep_as_of"]) == (7.9, "2026-10-18")


def test_vitals_reads_the_facet_mutation_control(monkeypatch):
    """Point the facets at fields the row does not carry: the served vitals follow the REGISTRY,
    so they go honest-null — a module still naming "hrv" by hand would keep serving 58.4."""
    for metric, wrong in (("hrv_ms", "hrv_x"), ("rhr_bpm", "rhr_x"), ("sleep_hours", "sleep_x")):
        monkeypatch.setitem(reg.METRIC_TRUTH, metric, dict(reg.METRIC_TRUTH[metric], field_by_source={"whoop": wrong}))
    out = _vitals()
    assert (out["hrv_ms"], out["rhr_bpm"], out["sleep_hours"]) == (None, None, None)
    assert out["recovery_pct"] == 64.0, "recovery has no second source and is not a facet"


def test_intelligence_common_table_is_retired():
    from intelligence import intelligence_common as ic

    assert not hasattr(ic, "_SOURCE_OF_TRUTH")
